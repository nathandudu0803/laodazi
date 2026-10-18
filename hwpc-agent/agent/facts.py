"""事实点提取(A):按场景从全量 Fact 中规则筛选。

只做筛选和分组,不改写 value,不让大模型补事实。待复核的事实单独列出,不进入可用集合。
"""
from __future__ import annotations

from dataclasses import dataclass, field

from agent.contracts import Fact, SceneProfile

# 始终保留的基础事实,保证型号身份和版本限定不丢
CORE_SECTIONS = ("操作系统", "屏幕", "处理器", "电池", "尺寸与重量")

# 场景关键词 -> 额外相关的事实小节
TOPIC_SECTIONS: list[tuple[tuple[str, ...], tuple[str, ...]]] = [
    (("学生", "学习", "宿舍", "网课", "论文", "办公", "文档", "会议", "职场"), ("内存", "存储", "键盘和触控板", "特色应用", "摄像头", "音频")),
    (("出差", "通勤", "便携", "轻薄", "携带"), ("接口", "包装清单")),
    (("设计", "剪辑", "创作", "绘图", "手写", "笔"), ("显卡", "内存", "存储", "键盘和触控板")),
    (("协同", "手机", "平板", "多设备", "互联"), ("无线连接", "特色应用")),
    (("游戏", "性能", "高性能"), ("显卡", "内存", "存储")),
    (("影音", "追剧", "视频", "音乐", "娱乐"), ("音频", "摄像头")),
]


@dataclass
class FactSelection:
    usable: list[Fact] = field(default_factory=list)  # 可进入软文的事实
    pending: list[Fact] = field(default_factory=list)  # 待复核,不得当确定结论使用
    sections: list[str] = field(default_factory=list)  # 实际选中的小节


def _section(f: Fact) -> str:
    return f.field.split(".")[0]


def select_facts(facts: list[Fact], scene: SceneProfile | None = None, extra_text: str = "") -> FactSelection:
    text = " ".join([extra_text] + ([scene.audience, scene.usage_scene, scene.main_problem, scene.content_goal] if scene else []))
    wanted = list(CORE_SECTIONS)
    for keys, secs in TOPIC_SECTIONS:
        if any(k in text for k in keys):
            wanted += [s for s in secs if s not in wanted]
    sel = FactSelection(sections=wanted)
    for f in facts:
        if _section(f) not in wanted:
            continue
        (sel.pending if f.review_status != "ok" else sel.usable).append(f)
    return sel
