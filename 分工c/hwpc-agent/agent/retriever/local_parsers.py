"""本地知识库文件解析器(A)。纯函数,不访问网络,不修改知识库文件。"""
from __future__ import annotations

import csv
import hashlib
import re
from pathlib import Path

from agent.contracts import Fact

NOISE_MARK = "即将离开consumer.huawei.com"

# 采用"标签 / 值"交替结构的小节及其标签集合;其余小节每个块都是一个独立的值。
LABEL_SECTIONS: dict[str, set[str]] = {
    "尺寸与重量": {"长度", "宽度", "厚度", "深度", "高度", "重量"},
    "屏幕": {"尺寸", "类型", "屏占比", "屏幕比例", "分辨率", "刷新率", "亮度", "峰值亮度",
             "色域", "色准", "色深", "对比度", "可视角度", "触摸屏"},
    "无线连接": {"WLAN", "蓝牙", "星闪", "NFC"},
    "电池": {"材料", "容量"},
}
SKIP_SECTIONS = {"来源", "官方规格摘录"}
MODEL_PREFIX_RE = re.compile(r"^(HUAWEI\s+)?MateBook[^：:]*?(版|屏版|典藏版|\d{4}|Pro S|Pro|Fold|Ultra)\s*(?=[^：:]*[：:])")


def read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8-sig")


def _blocks(section_text: str) -> list[str]:
    return [b.strip() for b in re.split(r"\n\s*\n", section_text) if b.strip()]


def _split_qualifier(block: str, model_title: str) -> tuple[str, str]:
    """把 "配置名：值" 拆成 (限定, 值)。无前缀返回 ("", 原文)。"""
    m = re.match(r"^([^：:\n]{1,60})[：:]\s*(.+)$", block, re.S)
    if not m:
        return "", block
    qual, val = m.group(1).strip(), m.group(2).strip()
    # 去掉限定里重复的整机名,例如 "HUAWEI MateBook Pro S 标准屏版" -> "标准屏版"
    q2 = re.sub(r"^HUAWEI\s+MateBook\s+[A-Za-z0-9 ]*?(?=[一-鿿])", "", qual).strip()
    if q2 == qual:
        q2 = re.sub(r"^HUAWEI\s+MateBook\s+Pro S\s*", "", qual).strip() or qual
    # 时间/数值类前缀(如 "12:30")不当限定
    if re.fullmatch(r"[\d.\s]+", qual):
        return "", block
    return q2 or qual, val


def _fact_id(model: str, field: str, qualifier: str, value: str, idx: int) -> str:
    h = hashlib.sha1(f"{model}|{field}|{qualifier}|{value}|{idx}".encode("utf-8")).hexdigest()
    return "F-" + h[:10]


def parse_product_facts(text: str, model: str, source_title: str, source_path: str) -> list[Fact]:
    """解析 产品事实.md。多配置、重复标签各自成独立 Fact,不合并。"""
    text = text.split(NOISE_MARK)[0]
    parts = re.split(r"(?m)^##\s+", text)
    facts: list[Fact] = []
    counter = 0
    for part in parts[1:]:
        title, _, body = part.partition("\n")
        section = title.strip()
        if section in SKIP_SECTIONS:
            continue
        labels = LABEL_SECTIONS.get(section)
        cur_label = ""
        pending_qual = ""
        group: list[Fact] = []  # 当前标签下已产出的事实,脚注挂到整组
        section_facts: list[Fact] = []
        for block in _blocks(body):
            if block.startswith("*"):
                note = block.lstrip("*").strip()
                targets = group if labels else (section_facts if note.startswith("以上") else (group[-1:] if group else []))
                for f in targets:
                    f.footnote = (f.footnote + "\n" + note).strip() if f.footnote else note
                continue
            if labels and block in labels:
                cur_label, pending_qual, group = block, "", []
                continue
            if re.fullmatch(r"[^\n：:]{1,30}[：:]", block):  # 单独一行 "标准版:" 作后续值的限定
                pending_qual = block.rstrip("：:").strip()
                continue
            qual, val = "", block
            if pending_qual:
                qual = pending_qual
            else:
                qual, val = _split_qualifier(block, "")
            field = f"{section}.{cur_label}" if labels and cur_label else section
            counter += 1
            f = Fact(
                fact_id=_fact_id(model, field, qual, val, counter),
                model=model, field=field, value=val, qualifier=qual,
                source_title=source_title, source_path=source_path,
            )
            facts.append(f)
            group.append(f)
            section_facts.append(f)
    return facts


def parse_selling_points(text: str) -> dict:
    """按固定骨架切 卖点与限制.md。"""
    secs: dict[str, str] = {}
    for part in re.split(r"(?m)^##\s+", text)[1:]:
        t, _, b = part.partition("\n")
        secs[t.strip()] = b.strip()

    def bullets(s: str) -> list[str]:
        out, seen = [], set()
        for ln in s.splitlines():
            ln = ln.strip()
            if ln.startswith("- "):
                v = ln[2:].strip()
                if v and v not in seen:
                    seen.add(v)
                    out.append(v)
        return out

    positioning = secs.get("一句话定位", "").split("\n\n")[0].strip()
    angles = []
    for part in re.split(r"(?m)^###\s+", secs.get("六个沟通角度", ""))[1:]:
        t, _, b = part.partition("\n")
        m = re.search(r"\*\*可用结论\*\*\s*(.*?)\s*\*\*支撑事实\*\*\s*(.*?)\s*\*\*表达边界\*\*\s*(.*)", b, re.S)
        if not m:
            continue
        angles.append({
            "title": t.strip(),
            "conclusion": m.group(1).strip(),
            "supporting_facts": bullets(m.group(2)),
            "boundaries": bullets(m.group(3)),
        })
    must_ask_text = secs.get("发布或销售前必须追问", "")
    return {
        "positioning": positioning,
        "angles": angles,
        "suitable_tasks": bullets(secs.get("适合进入候选清单的任务", "")),
        "unsuitable_tasks": bullets(secs.get("不适合直接下结论的任务", "")),
        "must_ask": bullets(must_ask_text),
        "compliance_examples": secs.get("合规表达示例", "").strip(),
    }


def find_dimension_line(selling_text: str) -> str:
    """卖点与限制.md 里描述宽/深/厚的那一行,用于尺寸交叉校验。"""
    for ln in selling_text.splitlines():
        if "mm" in ln and "宽" in ln:
            return ln.strip().lstrip("-").strip()
    return ""


def _num(value: str) -> float | None:
    m = re.search(r"\d+(?:\.\d+)?", value)
    return float(m.group()) if m else None


def flag_dimension_labels(facts: list[Fact], selling_text: str) -> None:
    """长度/宽度/厚度 三联里"长度"最小说明标签与数值错位(厚度被标成长度)。
    只标记待复核并附上卖点与限制.md 的对照行,不自行更正数值。"""
    dims = {f.field.split(".")[-1]: f for f in facts if f.field.startswith("尺寸与重量.") and not f.qualifier}
    if not {"长度", "宽度", "厚度"} <= dims.keys():
        return
    a, b, c = (_num(dims[k].value) for k in ("长度", "宽度", "厚度"))
    if a is None or b is None or c is None:
        return
    if a < b and a < c:
        ref = find_dimension_line(selling_text)
        note = (f"标签疑似错位:产品事实.md 记为 长度{dims['长度'].value}/宽度{dims['宽度'].value}/厚度{dims['厚度'].value},"
                f"其中'长度'数值最小,更像厚度。卖点与限制.md 对照: {ref or '无对应描述'}。未自动更正,待人工复核。")
        for k in ("长度", "宽度", "厚度"):
            dims[k].review_status = "pending_review"
            dims[k].review_note = note


def read_csv_rows(path: Path) -> list[dict]:
    with path.open(encoding="utf-8-sig", newline="") as fh:
        return [{(k or "").strip(): (v or "").strip() for k, v in row.items()} for row in csv.DictReader(fh)]


def topic_from_filename(name: str) -> str:
    """hwpc_{slug}_{画面主题}_{序号}[_{哈希}].ext -> 画面主题。"""
    stem = Path(name).stem
    m = re.match(r"^(?:hwpc|vmall)_[^_]+_(.+?)_\d+(?:_[0-9a-f]{8})?$", stem)
    return m.group(1) if m else stem


_POSITION_RULES = [
    (("续航", "快充", "电池"), "续航与充电段"),
    (("屏幕", "护眼", "OLED", "显示", "柔光屏"), "屏幕与显示段"),
    (("处理器", "性能", "芯片", "散热"), "性能段"),
    (("协同", "互联", "终端", "手机", "分享"), "多设备协同段"),
    (("手写", "笔", "创作"), "创作与手写段"),
    (("接口", "侧面", "拓展"), "接口与便携段"),
    (("配色", "外观", "颜色", "原野绿", "樱粉", "深空灰", "细节", "正面", "A面", "开合", "键盘"), "开篇外观段"),
]


def suggest_position(caption: str) -> str:
    for keys, pos in _POSITION_RULES:
        if any(k in caption for k in keys):
            return pos
    return "正文相关段落(按画面含义)"
