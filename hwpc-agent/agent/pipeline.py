"""流程编排(A):场景解析→平台策略→检索→事实点→编排→生成→核验→合规→导出。

B、C 的模块未就绪时使用桩函数,桩只做确定性处理,不调用大模型、不补事实。
真实模块就绪后通过 steps 参数替换,pipeline 本身不改。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable

from agent.contracts import Draft, ImageRef, PlatformPlan, Report, SceneProfile, TaskInput
from agent.facts import FactSelection, select_facts
from agent.retriever.base import Retriever

PLATFORM_IMAGE_RANGE = {"公众号": (2, 4), "小红书": (3, 6), "朋友圈": (1, 3), "海报": (1, 1)}


@dataclass
class PipelineResult:
    status: str = "ok"  # ok / need_info / blocked
    questions: list[str] = field(default_factory=list)  # 需要用户补充或确认的问题
    task: TaskInput | None = None
    scene: SceneProfile | None = None
    plan: PlatformPlan | None = None
    facts: list = field(default_factory=list)  # 该型号全部事实(含待复核)
    selection: FactSelection | None = None
    images: list[ImageRef] = field(default_factory=list)
    draft: Draft | None = None
    report: Report = field(default_factory=Report)
    exported: object = None
    trace: list[str] = field(default_factory=list)  # 每步状态,便于追溯


# ---------- 桩(B、C 完成后替换) ----------
def stub_scene(task: TaskInput) -> SceneProfile:
    missing = []
    if not task.audience:
        missing.append("目标人群")
    if not task.scene:
        missing.append("使用场景")
    return SceneProfile(audience=task.audience, usage_scene=task.scene, missing_info=missing)


def stub_platform(task: TaskInput, scene: SceneProfile) -> PlatformPlan:
    lo, hi = PLATFORM_IMAGE_RANGE.get(task.platform, (1, 3))
    return PlatformPlan(platform=task.platform, image_count_min=lo, image_count_max=hi)


def stub_compose(task: TaskInput, scene: SceneProfile, plan: PlatformPlan, sel: FactSelection, images: list[ImageRef]) -> Draft:
    facts = sel.usable[:6]
    body = "\n".join(f"- {f.field}{'(' + f.qualifier + ')' if f.qualifier else ''}:{f.value}" for f in facts)
    return Draft(title=f"{task.model}(桩草稿)", body=body, image_plan=images[: plan.image_count_max],
                 used_fact_ids=[f.fact_id for f in facts])


def stub_verify(draft: Draft, sel: FactSelection, images: list[ImageRef]) -> Report:
    ok_ids = {f.fact_id for f in sel.usable}
    bad = [i for i in draft.used_fact_ids if i not in ok_ids]
    r = Report(fact_check=[{"fact_id": i, "status": "ok" if i in ok_ids else "unsupported"} for i in draft.used_fact_ids])
    if bad:
        r.blocked, r.block_reason = True, f"草稿引用了无依据的事实: {bad}"
    return r


def stub_compliance(draft: Draft) -> list[dict]:
    return []


def stub_export(draft: Draft, report: Report):
    return {"title": draft.title, "body": draft.body}


@dataclass
class Steps:
    scene: Callable = stub_scene
    platform: Callable = stub_platform
    compose: Callable = stub_compose
    verify: Callable = stub_verify
    compliance: Callable = stub_compliance
    export: Callable = stub_export


def _block(res: PipelineResult, reason: str) -> PipelineResult:
    res.status = "blocked"
    res.report.blocked = True
    res.report.block_reason = reason
    res.report.to_confirm.append(reason)
    return res


def run(task: TaskInput, retriever: Retriever, steps: Steps | None = None) -> PipelineResult:
    st = steps or Steps()
    res = PipelineResult(task=task)

    # 1 型号解析:不确定就追问,不二选一
    match = retriever.find_models(task.model or task.product)
    if match.need_clarify or len(match.candidates) != 1:
        res.status = "need_info"
        res.questions.append(match.clarify_hint or "请提供具体产品型号")
        res.trace.append("型号解析:需追问")
        return res
    task.model = match.candidates[0]
    res.trace.append(f"型号解析:{task.model}")

    # 2 场景解析
    res.scene = st.scene(task)
    if res.scene.missing_info:
        res.status = "need_info"
        res.questions = [f"请补充:{m}" for m in res.scene.missing_info]
        res.trace.append("场景解析:信息不足,需追问")
        return res
    res.trace.append("场景解析完成")

    # 3 平台策略
    if not task.platform:
        res.status = "need_info"
        res.questions.append("请选择发布平台:公众号 / 小红书 / 朋友圈 / 海报")
        return res
    res.plan = st.platform(task, res.scene)
    res.trace.append(f"平台策略:{task.platform}")

    # 4 检索
    try:
        facts = retriever.get_facts(task.model)
        res.images = retriever.get_images(task.model)
    except Exception as exc:  # noqa: BLE001  检索失败即阻断,不让下游自行补全
        return _block(res, f"知识库检索失败: {type(exc).__name__}")
    if not facts:
        return _block(res, "知识库没有该型号的事实资料")
    res.facts = facts
    res.trace.append(f"检索:{len(facts)} 条事实,{len(res.images)} 张图片")

    # 5 事实点提取
    res.selection = select_facts(facts, res.scene, task.extra_requirements)
    for f in res.selection.pending:
        res.report.to_confirm.append(f"待复核:{f.field}({f.review_note[:40]})")
    if not res.selection.usable:
        return _block(res, "没有可用的已核实事实")
    res.trace.append(f"事实点:可用 {len(res.selection.usable)},待复核 {len(res.selection.pending)}")

    # 6-7 图文编排与软文生成
    try:
        res.draft = st.compose(task, res.scene, res.plan, res.selection, res.images)
    except Exception as exc:  # noqa: BLE001  生成失败(含模型未配置/调用失败)即阻断,不输出半成品
        return _block(res, f"软文生成失败: {exc}")
    res.trace.append("软文生成完成")

    # 8 核验与合规
    vr = st.verify(res.draft, res.selection, res.images)
    res.report.fact_check, res.report.image_check = vr.fact_check, vr.image_check
    res.report.blocked, res.report.block_reason = vr.blocked, vr.block_reason
    res.report.to_confirm += vr.to_confirm
    res.report.compliance = st.compliance(res.draft)
    res.report.blocked = res.report.blocked or any(c.get("blocking") for c in res.report.compliance)
    if res.report.blocked:
        res.status = "blocked"
        res.trace.append(f"核验阻断:{res.report.block_reason}")
        return res
    res.trace.append("核验与合规通过")

    # 9 导出
    res.exported = st.export(res.draft, res.report)
    res.trace.append("导出完成")
    return res


def real_steps(retriever: Retriever, llm_config=None, use_llm_scene: bool = False) -> Steps:
    """接入 B、C 的真实模块。

    llm_config 为界面填写的大模型配置(agent.llm.LLMConfig);为 None 时
    compose 回退到环境变量,仍未配置则 compose 抛错,run 不会导出。
    use_llm_scene 打开场景解析的模型层(默认关闭,纯规则结果可复现)。
    """
    from functools import partial

    from agent import compliance as comp_mod
    from agent import compose as compose_mod
    from agent import export as export_mod
    from agent import platform_rules, scene
    from agent import verify as verify_mod

    ctx: dict = {}

    chat_json = None
    if llm_config is not None:
        from agent import llm

        chat_json = partial(llm.chat_json, config=llm_config)

    def scene_step(task):
        return scene.parse_scene(task, use_llm=use_llm_scene, llm_config=llm_config)

    def compose(task, sc, plan, sel, images):
        ctx["model"] = task.model
        return compose_mod.compose_draft(task, sc, plan, sel, images, chat_json=chat_json)

    def verify(draft, sel, images):
        return verify_mod.verify(draft, sel.usable + sel.pending, images)

    def compliance(draft):
        records = retriever.get_price_records(ctx["model"]) if ctx.get("model") else []
        return comp_mod.compliance_check(draft, records)

    return Steps(scene=scene_step, platform=platform_rules.platform_step, compose=compose,
                 verify=verify, compliance=compliance, export=export_mod.export_markdown)
