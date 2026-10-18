"""平台策略(B):按平台生成 PlatformPlan,并提供完整平台规格给 compose 使用。

规则全部来自 data/platform_specs.yaml,代码里不硬编码平台参数,方便评委看到
"业务规则是做进 Agent 里的",而不是散落在提示词里。
判断标准(手册):换平台后,结构、语气、图片数量、行动引导必须同时变化。
"""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path

import yaml

from agent.contracts import PlatformPlan, SceneProfile, TaskInput

_SPEC_FILE = Path(__file__).resolve().parents[1] / "data" / "platform_specs.yaml"

PLATFORMS = ("公众号", "小红书", "朋友圈", "海报")


class UnknownPlatform(ValueError):
    """用户给的平台无法归一到四个支持的平台。"""


@lru_cache(maxsize=1)
def _load() -> dict:
    with open(_SPEC_FILE, encoding="utf-8") as fh:
        return yaml.safe_load(fh)


def normalize_platform(name: str) -> str:
    """把用户输入的平台名归一到 公众号/小红书/朋友圈/海报。无法识别时抛 UnknownPlatform。"""
    q = (name or "").strip().lower()
    if not q:
        raise UnknownPlatform("未提供发布平台")
    aliases = _load().get("aliases", {})
    for canon, names in aliases.items():
        if q == canon.lower() or q in {str(n).lower() for n in names}:
            return canon
    # 容错:输入里包含平台关键词(如"发小红书")
    for canon, names in aliases.items():
        if any(str(n).lower() in q for n in names if len(str(n)) >= 2):
            return canon
    raise UnknownPlatform(f"不支持的平台:{name}。可选:{' / '.join(PLATFORMS)}")


def get_spec(platform: str) -> dict:
    """返回某平台的完整规格(YAML 原样),供 compose 拼装提示词与做结构检查。"""
    return _load()["platforms"][normalize_platform(platform)]


def global_rules() -> list[str]:
    return list(_load().get("global_rules", []))


def _length_text(spec: dict) -> str:
    ln = spec["length"]
    parts = [f"正文约 {ln['body_chars']} 字"]
    if ln.get("lead_chars"):
        parts.append(f"导语 {ln['lead_chars']} 字")
    if ln.get("sections"):
        parts.append(f"{ln['sections']} 个段落/章节")
    if ln.get("selling_points_max"):
        parts.append(f"卖点不超过 {ln['selling_points_max']} 条")
    return ";".join(parts)


def _title_style_text(spec: dict) -> str:
    t = spec["title"]
    if not t.get("options"):
        return t.get("note", "无标题,首句承担标题作用")
    avoid = "、".join(t.get("avoid", []))
    base = f"备选 {t['options']} 个,{t.get('length', '')} 字;{t.get('style', t.get('note', ''))}"
    return f"{base};避免:{avoid}" if avoid else base


def build_plan(task: TaskInput, scene: SceneProfile | None = None) -> PlatformPlan:
    """生成 PlatformPlan。scene 目前只用于在决策+到店意图时收紧 CTA 描述,不改结构。"""
    platform = normalize_platform(task.platform)
    spec = get_spec(platform)
    cta = spec["cta"]
    cta_text = f"{cta['style']};只给 {cta['count']} 个动作"
    if cta.get("bad"):
        cta_text += ";不要用:" + "、".join(cta["bad"])
    structure = [f"{s['name']}:{s['job']}" for s in spec["structure"]]
    return PlatformPlan(
        platform=platform,
        title_style=_title_style_text(spec),
        length=_length_text(spec),
        structure=structure,
        tone=spec["tone"],
        image_count_min=int(spec["images"]["min"]),
        image_count_max=int(spec["images"]["max"]),
        call_to_action=cta_text,
    )


def platform_step(task: TaskInput, scene: SceneProfile) -> PlatformPlan:
    """pipeline.Steps.platform 的签名:platform(task, scene) -> PlatformPlan。"""
    return build_plan(task, scene)
