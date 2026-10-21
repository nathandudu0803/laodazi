"""图文编排与软文生成(B)。

流程:选事实 -> 选图 -> 拼提示词(prompts/ 8 模块 + 平台规格 + 场景切入点)-> 模型生成 JSON
-> 校验并整理成 Draft。模型只拿到"可用事实"(sel.usable)和"图片清单",拿不到别的资料。

契约(A 冻结)里的 Draft 没有"策略说明"字段。手册要求评委看得到"为什么这样写",
所以用 ComposedDraft 子类扩展:它仍是 Draft,pipeline / verify / export 无需改动。
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Callable

from agent import platform_rules
from agent import scene as scene_mod
from agent.contracts import Draft, ImageRef, PlatformPlan, SceneProfile, TaskInput
from agent.facts import FactSelection

logger = logging.getLogger(__name__)

_PROMPT_DIR = Path(__file__).resolve().parents[1] / "prompts"
MAX_FACTS = 14  # 喂给模型的事实上限,避免堆参数


class ComposeError(RuntimeError):
    """生成失败(模型不可用或输出无法解析)。调用方应提示用户,不得改用无依据的内容。"""


@dataclass
class ComposedDraft(Draft):
    strategy: dict = field(default_factory=dict)  # 切入点 / 卖点顺序 / 不写什么 / 图片安排
    title_options: list[str] = field(default_factory=list)
    pending: list[str] = field(default_factory=list)  # 待确认项,供界面展示,供 C 并入报告


def load_system_prompt() -> str:
    """按编号顺序拼接 prompts/ 下 8 个模块,评委可以逐个模块查看。"""
    parts = []
    for p in sorted(_PROMPT_DIR.glob("0[1-8]_*.md")):
        parts.append(p.read_text(encoding="utf-8").strip())
    if len(parts) != 8:
        raise ComposeError(f"系统提示词模块不完整:找到 {len(parts)} 个,应为 8 个")
    return "\n\n---\n\n".join(parts)


def _fact_line(f) -> str:
    q = f"[{f.qualifier}]" if f.qualifier else ""
    fn = f" (脚注:{f.footnote})" if f.footnote else ""
    return f"{f.fact_id} | {f.field}{q} | {f.value}{fn} | 来源:{f.source_title}"


def rank_facts(sel: FactSelection, ctx: scene_mod.SceneContext) -> list:
    """按场景的 fact_priority 排序后截断。只排序,不改写任何值。"""
    prio = {name: i for i, name in enumerate(ctx.fact_priority)}

    def key(f):
        section = f.field.split(".")[0]
        return (prio.get(section, len(prio)), f.field)

    return sorted(sel.usable, key=key)[:MAX_FACTS]


def pick_images(images: list[ImageRef], plan: PlatformPlan, model: str) -> list[ImageRef]:
    """候选图:型号必须一致,数量不超过平台上限。是否真正采用由模型按段落挑选。"""
    same = [i for i in images if i.model == model]
    return same[: max(plan.image_count_max * 2, plan.image_count_max)]


def _image_line(i: ImageRef) -> str:
    return f"{i.filename} | 说明:{i.caption} | 来源:{i.source} | 建议位置:{i.suggested_position}"


def build_user_prompt(task, scene, plan, ctx, facts, images, stage_inferred: bool) -> str:
    spec = platform_rules.get_spec(plan.platform)
    lines = [
        "# 任务",
        f"目标型号(唯一):{task.model}",
        f"平台:{plan.platform}",
        f"人群:{scene.audience};场景:{scene.usage_scene};购买阶段:{scene.purchase_stage}"
        + ("(由场景推断,不是用户明说)" if stage_inferred else ""),
        f"主要问题:{scene.main_problem}",
        f"内容目标:{scene.content_goal}",
        f"额外要求:{task.extra_requirements or '无'}",
        "",
        "# 场景切入点",
        f"场景类型:{ctx.name};切入点:{ctx.angle}",
        f"人群变体:{ctx.angle_variant or '无'}",
        "读者最想问:" + ";".join(ctx.reader_questions),
        "本场景禁区:" + ";".join(ctx.must_not),
        "",
        "# 平台规格",
        f"结构:{' → '.join(plan.structure)}",
        f"篇幅:{plan.length}",
        f"标题:{plan.title_style}",
        f"语气:{plan.tone}",
        f"图片:{plan.image_count_min} 到 {plan.image_count_max} 张,{spec['images']['placement']}",
        f"行动引导:{plan.call_to_action}",
        f"版本免责(结尾必须保留):{spec['disclaimer']}",
        "",
    ]
    lines += ["# 可用事实点(只能用这些,fact_id 必须原样回填)"] + [_fact_line(f) for f in facts]
    lines += ["", "# 可用图片(只能从这里选,文件名原样写出)"] + [_image_line(i) for i in images]
    return "\n".join(lines)


OUTPUT_FORMAT = """
# 输出格式
只输出一个 JSON 对象,不要任何解释。字段:
{
  "strategy": {"切入点": "", "卖点顺序": "", "不写什么": "", "图片安排": ""},
  "title_options": ["备选标题1", "备选标题2", "备选标题3"],
  "title": "采用的标题(朋友圈无标题时留空字符串)",
  "lead": "导语(没有则留空)",
  "body": "正文,按平台结构分段",
  "call_to_action": "只有一个动作",
  "tags": ["小红书必填,其余可空"],
  "image_plan": [{"filename": "清单里的原文件名", "caption": "这张图在这里的作用", "position": "具体到段落"}],
  "used_fact_ids": ["正文里实际用到的事实点 fact_id"],
  "pending": ["待确认项,每条写清:是什么、为什么不能确定"]
}
规则:正文里每个数字、型号、功能都必须能对应到 used_fact_ids 中的某一条;
没有对应事实点的内容不要写。图片只能用清单里的文件名。
""".strip()


def _parse(raw: dict, images: list[ImageRef], facts, plan: PlatformPlan) -> ComposedDraft:
    by_name = {i.filename: i for i in images}
    valid_ids = {f.fact_id for f in facts}

    picked: list[ImageRef] = []
    dropped: list[str] = []
    for it in raw.get("image_plan") or []:
        name = (it or {}).get("filename", "")
        src = by_name.get(name)
        if not src:  # 模型编了一个清单外的文件名:直接丢弃,不尝试"修"成别的图
            dropped.append(name)
            continue
        if any(p.filename == name for p in picked):
            continue
        picked.append(
            replace(
                src,
                caption=(it.get("caption") or src.caption).strip(),
                suggested_position=(it.get("position") or src.suggested_position).strip(),
            )
        )
    picked = picked[: plan.image_count_max]

    used = [i for i in (raw.get("used_fact_ids") or []) if i in valid_ids]
    unknown = [i for i in (raw.get("used_fact_ids") or []) if i not in valid_ids]

    pending = [str(p) for p in (raw.get("pending") or [])]
    if dropped:
        pending.append(f"模型引用了图片清单之外的文件,已丢弃:{dropped}")
    if unknown:
        # 不静默吞掉:无依据的 fact_id 要让 verify 看到,所以保留在 used_fact_ids 里,由 C 阻断
        used += unknown
        pending.append(f"模型引用了不存在的事实点 ID:{unknown}")
    if len(picked) < plan.image_count_min:
        pending.append(f"可用同型号图片不足:需要至少 {plan.image_count_min} 张,实际采用 {len(picked)} 张")

    return ComposedDraft(
        title=(raw.get("title") or "").strip(),
        lead=(raw.get("lead") or "").strip(),
        body=(raw.get("body") or "").strip(),
        image_plan=picked,
        call_to_action=(raw.get("call_to_action") or "").strip(),
        tags=[str(t).strip() for t in (raw.get("tags") or []) if str(t).strip()],
        used_fact_ids=used,
        strategy=raw.get("strategy") or {},
        title_options=[str(t) for t in (raw.get("title_options") or [])],
        pending=pending,
    )


def compose_draft(
    task: TaskInput,
    scene: SceneProfile,
    plan: PlatformPlan,
    sel: FactSelection,
    images: list[ImageRef],
    chat_json: Callable | None = None,
) -> ComposedDraft:
    """pipeline.Steps.compose 的签名:compose(task, scene, plan, sel, images) -> Draft。

    chat_json 可注入,便于测试时不用真实模型。默认使用 agent.llm.chat_json。
    """
    if chat_json is None:
        from agent import llm

        chat_json = llm.chat_json

    ctx = scene_mod.build_context(scene, task)
    facts = rank_facts(sel, ctx)
    if not facts:
        raise ComposeError("没有可用事实点,不能生成")
    cand_images = pick_images(images, plan, task.model)
    user = build_user_prompt(task, scene, plan, ctx, facts, cand_images, scene_mod.is_stage_inferred(task))

    try:
        raw = chat_json(
            [
                {"role": "system", "content": load_system_prompt()},
                {"role": "user", "content": user + "\n\n" + OUTPUT_FORMAT},
            ],
            temperature=0.7,
        )
    except Exception as exc:  # noqa: BLE001
        from agent.llm import LLMError, redact

        # LLMError 的文本已脱敏且带可操作提示(如"配置不完整,缺少 API Key"),
        # 要透出给使用者;其他异常只给类型名,避免把地址或凭证带进界面。
        detail = redact(exc) if isinstance(exc, LLMError) else type(exc).__name__
        raise ComposeError(f"模型生成失败:{detail}") from exc
    if not isinstance(raw, dict):
        raise ComposeError("模型输出不是 JSON 对象")

    draft = _parse(raw, cand_images, facts, plan)
    for f in sel.pending:  # 待复核事实不得入文,但要让使用者看到
        draft.pending.append(f"待复核,本文未使用:{f.field}")
    return draft


def compose_step(task, scene, plan, sel, images) -> Draft:
    return compose_draft(task, scene, plan, sel, images)


def render_markdown(draft: Draft) -> str:
    """把草稿渲染成 Markdown(含策略说明与配图方案),供界面与导出使用。"""
    out = []
    strat = getattr(draft, "strategy", None) or {}
    if strat:
        out.append("## 内容策略说明")
        out += [f"- **{k}**:{v}" for k, v in strat.items()]
        out.append("")
    if draft.title:
        out.append(f"# {draft.title}")
    if draft.lead:
        out.append(f"\n{draft.lead}")
    out.append(f"\n{draft.body}")
    if draft.call_to_action:
        out.append(f"\n**行动引导**:{draft.call_to_action}")
    if draft.tags:
        out.append("\n" + " ".join(f"#{t.lstrip('#')}" for t in draft.tags))
    if draft.image_plan:
        out.append("\n## 配图方案")
        out.append("| 序号 | 图片名称 | 来源 | 图片说明 | 建议插入位置 |")
        out.append("|---|---|---|---|---|")
        for n, i in enumerate(draft.image_plan, 1):
            out.append(f"| {n} | {i.filename} | {i.source} | {i.caption} | {i.suggested_position} |")
    pend = getattr(draft, "pending", None) or []
    if pend:
        out.append("\n## 待确认项")
        out += [f"- {p}" for p in pend]
    return "\n".join(out)
