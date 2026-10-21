"""场景解析(B):提取人群、场景、购买阶段、主要问题、内容目标;信息不足时给出追问。

分两层,保证没有大模型时也能跑、也不会乱补:
  1. 规则层:关键词匹配 data/scene_library.yaml 里的 8 类场景,给出默认阶段、切入点、事实优先级。
  2. 模型层(可选):用 chat_json 把自由文本整理成结构化字段。模型只能"整理用户说过的话",
     不得发明用户没提供的信息;用户没说的,留空并进入 missing_info。

SceneProfile 契约(A 冻结):audience / usage_scene / purchase_stage / main_problem /
content_goal / missing_info。missing_info 非空时,pipeline 会返回追问而不进入生成。
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

import yaml

from agent.contracts import SceneProfile, TaskInput

logger = logging.getLogger(__name__)

_LIB_FILE = Path(__file__).resolve().parents[1] / "data" / "scene_library.yaml"
_PROMPT_FILE = Path(__file__).resolve().parents[1] / "prompts" / "02_scene.md"

VALID_STAGES = ("了解", "比较", "决策", "已购")

# 场景关键词 -> 场景库 key。顺序即优先级,先命中先用。
SCENE_KEYWORDS: list[tuple[str, tuple[str, ...]]] = [
    ("back_to_school", ("开学", "新生", "入学", "大学", "宿舍", "上课", "网课", "论文", "学生", "考研")),
    ("enterprise_procurement", ("采购", "团队", "公司批量", "批量", "企业", "中小企业", "行政", "IT")),
    ("new_launch", ("新品", "首发", "新款", "刚发布", "发布会")),
    ("festival", ("节日", "送礼", "礼物", "春节", "中秋", "国庆", "双十一", "618", "母亲节", "父亲节", "教师节")),
    ("family_refresh", ("换新", "换机", "旧电脑", "家庭", "给父母", "给孩子", "老人", "迁移")),
    ("creator", ("设计", "剪辑", "摄影", "视频", "创作", "绘图", "手写", "自媒体", "渲染")),
    ("office", ("办公", "出差", "差旅", "会议", "职场", "商务", "通勤", "汇报")),
    ("store_visit", ("到店", "门店", "路过", "体验", "附近")),
]


@dataclass
class SceneContext:
    """给 compose 用的场景上下文:SceneProfile 之外的切入点、事实优先级、禁区。"""

    key: str = ""  # 场景库 key,空表示走兜底
    name: str = ""
    angle: str = ""
    angle_variant: str = ""
    fact_priority: list[str] = field(default_factory=list)
    reader_questions: list[str] = field(default_factory=list)
    must_not: list[str] = field(default_factory=list)
    note: str = ""
    visit_intent: bool = False


@lru_cache(maxsize=1)
def load_library() -> dict:
    with open(_LIB_FILE, encoding="utf-8") as fh:
        return yaml.safe_load(fh)


def match_scene_key(text: str) -> str:
    """按关键词匹配场景库 key;没有命中返回空串(走兜底)。"""
    for key, words in SCENE_KEYWORDS:
        if any(w in text for w in words):
            return key
    return ""


def pick_variant(key: str, audience: str) -> str:
    """按人群选 angle_variants 里的一个变体,没有合适的返回空串。"""
    variants = (load_library()["scenes"].get(key) or {}).get("angle_variants") or {}
    hints = {
        "student": ("新生", "学生", "研究生", "大学"),
        "parent": ("家长", "父母"),
        "commuter": ("出差", "差旅", "通勤", "商务"),
        "manager": ("管理", "经理", "主管", "负责人"),
        "designer": ("设计", "摄影"),
        "video": ("视频", "剪辑", "自媒体"),
        "for_parents": ("父母", "老人", "长辈"),
        "multi_user": ("全家", "家人", "孩子"),
        "small_team": ("小团队", "小公司", "中小"),
        "it_manager": ("IT", "运维", "信息化"),
        "first_time": ("第一次", "新客"),
        "returning": ("老客户", "老用户", "复购"),
        "upgrader": ("换代", "升级", "老用户"),
        "newcomer": ("新用户", "第一次买"),
        "gift_for_parents": ("父母", "长辈", "老人"),
        "gift_for_student": ("学生", "孩子", "新生"),
    }
    for vkey, vtext in variants.items():
        if any(h in audience for h in hints.get(vkey, ())):
            return vtext
    return ""


def build_context(scene: SceneProfile, task: TaskInput | None = None) -> SceneContext:
    """根据 SceneProfile(+ 原始任务)生成 SceneContext。"""
    lib = load_library()
    text = " ".join(
        [scene.audience, scene.usage_scene, scene.main_problem, scene.content_goal]
        + ([task.scene, task.audience, task.extra_requirements] if task else [])
    )
    key = match_scene_key(text)
    if not key:
        fb = lib["fallback"]
        inherited: list[str] = []
        for s in lib["scenes"].values():
            inherited += [m for m in s.get("must_not", []) if m not in inherited]
        return SceneContext(name=fb["name"], angle=fb["strategy"], must_not=inherited)
    s = lib["scenes"][key]
    return SceneContext(
        key=key,
        name=s["name"],
        angle=s["angle"],
        angle_variant=pick_variant(key, scene.audience),
        fact_priority=list(s.get("fact_priority", [])),
        reader_questions=list(s.get("reader_questions", [])),
        must_not=list(s.get("must_not", [])),
        note=s.get("note", ""),
        visit_intent=bool(s.get("visit_intent", False)),
    )


def _default_stage(key: str, text: str) -> tuple[str, bool]:
    """返回 (阶段, 是否为推断)。用户明说的阶段词优先于场景默认。"""
    explicit = {
        "已购": ("已买了", "刚买", "已经买", "已入手", "买了"),
        "决策": ("准备下单", "马上买", "确定买", "选哪个配置", "买哪个版本"),
        "比较": ("对比", "比较", "纠结", "哪个好", "怎么选"),
        "了解": ("了解", "想看看", "有什么", "推荐"),
    }
    for stage, words in explicit.items():
        if any(w in text for w in words):
            return stage, False
    stage = (load_library()["scenes"].get(key) or {}).get("default_stage", "比较")
    return stage, True


def clarifying_questions(task: TaskInput, scene: SceneProfile, ctx: SceneContext) -> list[str]:
    """按 scene_library.clarify_rules 生成追问,最多 3 条,只问会改变内容方向的。"""
    lib = load_library()
    qs = lib["clarifying_questions"]
    out: list[str] = []
    if not scene.audience:
        out.append(qs["audience"]["ask"])
    if not scene.usage_scene:
        out.append(qs["usage"]["ask"])
    # 宽泛需求:只给了品类、没给用途和出行信息
    broad = not scene.usage_scene and not ctx.key
    if broad:
        out.append(qs["mobility"]["ask"])
    # 兜底场景下补问软件,避免写出空泛内容
    if not ctx.key and scene.usage_scene and len(out) < 3:
        out.append(qs["software"]["ask"])
    # 去重并截断
    seen, uniq = set(), []
    for q in out:
        if q not in seen:
            uniq.append(q)
            seen.add(q)
    return uniq[:3]


def _llm_enrich(task: TaskInput, llm_config=None) -> dict:
    """可选:让模型把自由文本整理成结构化字段。模型不可用时返回空,走纯规则。"""
    try:
        from agent import llm

        system = _PROMPT_FILE.read_text(encoding="utf-8")
        user = (
            "只整理用户已经说过的内容,没说的字段留空字符串,不要猜测。\n"
            f"产品:{task.product}\n人群:{task.audience}\n场景:{task.scene}\n"
            f"平台:{task.platform}\n额外要求:{task.extra_requirements}\n\n"
            '只输出 JSON:{"main_problem":"","content_goal":"","purchase_stage":""}。'
            "purchase_stage 只能取 了解/比较/决策/已购 之一,或留空。"
        )
        data = llm.chat_json(
            [{"role": "system", "content": system}, {"role": "user", "content": user}],
            config=llm_config,
            temperature=0,
        )
        return data if isinstance(data, dict) else {}
    except Exception as exc:  # noqa: BLE001  模型不可用不应阻断规则层
        logger.info("场景解析跳过模型层: %s", type(exc).__name__)
        return {}


def parse_scene(task: TaskInput, use_llm: bool = False, llm_config=None) -> SceneProfile:
    """pipeline.Steps.scene 的签名:scene(task) -> SceneProfile。

    use_llm=False(默认)时纯规则,结果可复现,适合测试与离线演示。
    llm_config 为界面填写的大模型配置;为 None 时回退到环境变量。
    """
    audience = (task.audience or "").strip()
    usage = (task.scene or "").strip()
    text = " ".join([audience, usage, task.extra_requirements or ""])
    key = match_scene_key(text)
    lib_scene = load_library()["scenes"].get(key) or {}

    enriched = _llm_enrich(task, llm_config) if use_llm else {}
    stage, inferred = _default_stage(key, text)
    m_stage = enriched.get("purchase_stage")
    if m_stage in VALID_STAGES:
        stage, inferred = m_stage, False

    main_problem = (enriched.get("main_problem") or "").strip()
    if not main_problem and lib_scene.get("core_conflict"):
        main_problem = lib_scene["core_conflict"]  # 场景库的通用矛盾,明确标注为推断
    content_goal = (enriched.get("content_goal") or "").strip() or load_library()["stages"][stage]["goal"]

    # 契约要求 purchase_stage 只取 了解/比较/决策/已购,不能带后缀。
    # 阶段是否为推断,由 is_stage_inferred() 单独回答,供 compose 在策略说明里写明。
    scene = SceneProfile(
        audience=audience,
        usage_scene=usage,
        purchase_stage=stage,
        main_problem=main_problem,
        content_goal=content_goal,
    )
    ctx = build_context(scene, task)
    scene.missing_info = clarifying_questions(task, scene, ctx)
    return scene


def is_stage_inferred(task: TaskInput) -> bool:
    """用户没有明说阶段、由场景默认值推断时为 True。"""
    text = " ".join([task.audience or "", task.scene or "", task.extra_requirements or ""])
    return _default_stage(match_scene_key(text), text)[1]


def scene_step(task: TaskInput) -> SceneProfile:
    return parse_scene(task, use_llm=False)
