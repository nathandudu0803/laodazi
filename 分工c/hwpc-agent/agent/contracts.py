"""数据契约(由 A 维护,第 0 步冻结后其余只读)。

需要改字段时,先在 docs/handoff.md 追加申请,A 同意并通知全员后才能改。
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class TaskInput:
    """用户输入的任务。"""

    product: str  # 用户填写的产品/型号原文,例如 "D14""MateBook Pro"
    audience: str = ""  # 目标人群,例如 "大学新生"
    scene: str = ""  # 使用场景,例如 "宿舍写论文"
    platform: str = ""  # 目标平台:公众号 / 小红书 / 朋友圈 / 海报
    extra_requirements: str = ""  # 临时修改或额外要求
    model: str = ""  # 已解析出的规范型号,find_models 后由 pipeline 回填


@dataclass
class SceneProfile:
    """场景解析结果(B 产出)。"""

    audience: str = ""  # 人群
    usage_scene: str = ""  # 使用场景
    purchase_stage: str = ""  # 购买阶段:了解/比较/决策/已购
    main_problem: str = ""  # 用户主要问题或痛点
    content_goal: str = ""  # 内容目标:种草/转化/答疑等
    missing_info: list[str] = field(default_factory=list)  # 缺失信息,非空则需追问


@dataclass
class PlatformPlan:
    """平台策略(B 产出)。"""

    platform: str = ""  # 平台名
    title_style: str = ""  # 标题风格
    length: str = ""  # 篇幅要求
    structure: list[str] = field(default_factory=list)  # 段落结构
    tone: str = ""  # 语气
    image_count_min: int = 0  # 图片数量下限
    image_count_max: int = 0  # 图片数量上限
    call_to_action: str = ""  # 行动引导方式


@dataclass
class Fact:
    """一条带来源的产品事实。多配置绝不合并,各自独立成条。"""

    fact_id: str  # 稳定 ID,同一来源同一字段同一限定下不变
    model: str  # 规范型号
    field: str  # 字段名,例如 "屏幕尺寸""电池容量"
    value: str  # 原值,原样保留,不改写
    qualifier: str = ""  # 限定条件:配置名/版本/"最高""约"等
    footnote: str = ""  # 原文脚注
    source_title: str = ""  # 来源标题,例如 "产品事实.md"
    source_path: str = ""  # 本地为相对路径;ima 下为文档标识
    review_status: str = "ok"  # "ok" 或 "pending_review"(待复核)
    review_note: str = ""  # 待复核原因


@dataclass
class ImageRef:
    """一张来自知识库、与型号一致的图片。"""

    filename: str  # 文件名
    model: str  # 规范型号
    source: str  # 来源说明,例如 "官网图片 / P1 图片索引"
    caption: str  # 图片说明(依据官网图片说明或文件名主题)
    suggested_position: str = ""  # 建议插入位置
    file_path: str = ""  # 本地真实路径或 ima 媒体标识
    source_page: str = ""  # 图片来源页面 URL(如有)


@dataclass
class Draft:
    """生成的软文草稿(B 产出)。"""

    title: str = ""  # 标题
    lead: str = ""  # 导语
    body: str = ""  # 正文
    image_plan: list[ImageRef] = field(default_factory=list)  # 配图方案
    call_to_action: str = ""  # 行动引导
    tags: list[str] = field(default_factory=list)  # 标签
    used_fact_ids: list[str] = field(default_factory=list)  # 引用的事实 ID,供核验


@dataclass
class Report:
    """核验与合规报告(C 产出,A 的 pipeline 也会在阻断时填写)。"""

    fact_check: list[dict] = field(default_factory=list)  # 事实核验结果
    image_check: list[dict] = field(default_factory=list)  # 图片核验结果
    compliance: list[dict] = field(default_factory=list)  # 合规结果
    to_confirm: list[str] = field(default_factory=list)  # 待确认项
    blocked: bool = False  # 是否阻断输出
    block_reason: str = ""  # 阻断原因


@dataclass
class ModelMatch:
    """find_models 的返回结果。"""

    candidates: list[str] = field(default_factory=list)  # 规范型号候选
    need_clarify: bool = False  # 为 True 时不得自行二选一,必须追问
    clarify_hint: str = ""  # 追问提示,例如 "D14 还是 D16"
