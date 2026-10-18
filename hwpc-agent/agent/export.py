"""导出(C)。

导出软文为Markdown和纯文本格式，附带核验与合规报告。
"""
from pathlib import Path

from .contracts import Draft, Report


def export_markdown(draft: Draft, report: Report | None = None) -> str:
    """导出为Markdown格式。

    Args:
        draft: 软文草稿
        report: 核验与合规报告（可选）

    Returns:
        str: Markdown格式的内容
    """
    lines = []

    # 阻断警示
    if report and report.blocked:
        lines.append("⚠️ **警告：此内容未通过核验或合规检查，请勿发布** ⚠️\n")
        lines.append(f"**阻断原因**：{report.block_reason}\n")
        lines.append("---\n")

    # 标题
    lines.append(f"# {draft.title}\n")

    # 导语
    if draft.lead:
        lines.append(f"**{draft.lead}**\n")

    # 正文
    if draft.body:
        lines.append(draft.body)
        lines.append("")

    # 配图方案
    if draft.image_plan:
        lines.append("## 📷 配图方案\n")
        for i, img in enumerate(draft.image_plan, 1):
            lines.append(f"### 图 {i}: {img.filename}\n")
            lines.append(f"- **型号**: {img.model}")
            lines.append(f"- **来源**: {img.source}")
            if img.caption:
                lines.append(f"- **说明**: {img.caption}")
            if img.suggested_position:
                lines.append(f"- **建议位置**: {img.suggested_position}")
            if img.source_page:
                lines.append(f"- **来源页面**: {img.source_page}")
            lines.append("")

    # 行动引导
    if draft.call_to_action:
        lines.append("## 💡 行动引导\n")
        lines.append(draft.call_to_action)
        lines.append("")

    # 标签
    if draft.tags:
        lines.append("## 🏷️ 标签\n")
        lines.append(" ".join(f"`#{tag}`" for tag in draft.tags))
        lines.append("")

    # 附加核验报告
    if report:
        lines.append("---\n")
        lines.append("## 📋 核验与合规报告\n")

        # 事实核验
        if report.fact_check:
            lines.append("### 事实核验\n")
            for item in report.fact_check:
                status_emoji = "✅" if item.get("status") == "passed" else "⚠️" if item.get("status") == "warning" else "❌"
                lines.append(f"- {status_emoji} **{item.get('type')}**")
                if item.get("issue"):
                    lines.append(f"  - 问题：{item.get('issue')}")
                if item.get("suggestion"):
                    lines.append(f"  - 建议：{item.get('suggestion')}")
            lines.append("")

        # 图片核验
        if report.image_check:
            lines.append("### 图片核验\n")
            for item in report.image_check:
                status_emoji = "✅" if item.get("status") == "passed" else "⚠️" if item.get("status") == "warning" else "❌"
                lines.append(f"- {status_emoji} **{item.get('type')}**")
                if item.get("filename"):
                    lines.append(f"  - 文件：{item.get('filename')}")
                if item.get("issue"):
                    lines.append(f"  - 问题：{item.get('issue')}")
                if item.get("suggestion"):
                    lines.append(f"  - 建议：{item.get('suggestion')}")
            lines.append("")

        # 合规检查
        if report.compliance:
            lines.append("### 合规检查\n")
            for item in report.compliance:
                blocking_emoji = "🚫" if item.get("blocking") else "⚠️"
                lines.append(f"- {blocking_emoji} **{item.get('category', item.get('type'))}**")
                if item.get("term"):
                    lines.append(f"  - 命中词：{item.get('term')}")
                if item.get("matched_text"):
                    lines.append(f"  - 匹配文本：{item.get('matched_text')}")
                if item.get("issue"):
                    lines.append(f"  - 问题：{item.get('issue')}")
                if item.get("suggestion"):
                    lines.append(f"  - 建议：{item.get('suggestion')}")
            lines.append("")

        # 待确认信息
        if report.to_confirm:
            lines.append("### 待确认信息\n")
            for item in report.to_confirm:
                lines.append(f"- {item}")
            lines.append("")

    return "\n".join(lines)


def export_text(draft: Draft, report: Report | None = None) -> str:
    """导出为纯文本格式。

    Args:
        draft: 软文草稿
        report: 核验与合规报告（可选）

    Returns:
        str: 纯文本格式的内容
    """
    lines = []

    # 阻断警示
    if report and report.blocked:
        lines.append("=" * 60)
        lines.append("⚠️  警告：此内容未通过核验或合规检查，请勿发布  ⚠️")
        lines.append(f"阻断原因：{report.block_reason}")
        lines.append("=" * 60)
        lines.append("")

    # 标题
    lines.append(draft.title)
    lines.append("=" * len(draft.title))
    lines.append("")

    # 导语
    if draft.lead:
        lines.append(draft.lead)
        lines.append("")

    # 正文
    if draft.body:
        lines.append(draft.body)
        lines.append("")

    # 配图方案
    if draft.image_plan:
        lines.append("-" * 60)
        lines.append("配图方案")
        lines.append("-" * 60)
        for i, img in enumerate(draft.image_plan, 1):
            lines.append(f"\n[图 {i}] {img.filename}")
            lines.append(f"型号：{img.model}")
            lines.append(f"来源：{img.source}")
            if img.caption:
                lines.append(f"说明：{img.caption}")
            if img.suggested_position:
                lines.append(f"建议位置：{img.suggested_position}")
        lines.append("")

    # 行动引导
    if draft.call_to_action:
        lines.append("-" * 60)
        lines.append("行动引导")
        lines.append("-" * 60)
        lines.append(draft.call_to_action)
        lines.append("")

    # 标签
    if draft.tags:
        lines.append("标签：" + "  ".join(f"#{tag}" for tag in draft.tags))
        lines.append("")

    return "\n".join(lines)


def export_report_only(report: Report) -> str:
    """仅导出核验与合规报告。

    Args:
        report: 核验与合规报告

    Returns:
        str: Markdown格式的报告
    """
    lines = []
    lines.append("# 核验与合规报告\n")

    # 总体状态
    if report.blocked:
        lines.append(f"**状态**: 🚫 已阻断\n")
        lines.append(f"**原因**: {report.block_reason}\n")
    else:
        lines.append("**状态**: ✅ 通过\n")

    lines.append("---\n")

    # 事实核验
    if report.fact_check:
        lines.append("## 事实核验\n")
        for item in report.fact_check:
            status = item.get("status", "unknown")
            emoji = {"passed": "✅", "warning": "⚠️", "failed": "❌"}.get(status, "❓")
            lines.append(f"### {emoji} {item.get('type')}\n")
            for key in ["fact_id", "field", "value", "issue", "suggestion"]:
                if key in item and item[key]:
                    lines.append(f"- **{key}**: {item[key]}")
            lines.append("")

    # 图片核验
    if report.image_check:
        lines.append("## 图片核验\n")
        for item in report.image_check:
            status = item.get("status", "unknown")
            emoji = {"passed": "✅", "warning": "⚠️", "failed": "❌"}.get(status, "❓")
            lines.append(f"### {emoji} {item.get('type')}\n")
            for key in ["filename", "draft_model", "kb_model", "issue", "suggestion"]:
                if key in item and item[key]:
                    lines.append(f"- **{key}**: {item[key]}")
            lines.append("")

    # 合规检查
    if report.compliance:
        lines.append("## 合规检查\n")
        blocking_count = sum(1 for item in report.compliance if item.get("blocking"))
        warning_count = len(report.compliance) - blocking_count
        lines.append(f"- 阻断项：{blocking_count}")
        lines.append(f"- 警告项：{warning_count}\n")

        for item in report.compliance:
            blocking = item.get("blocking", False)
            emoji = "🚫" if blocking else "⚠️"
            category = item.get("category", item.get("type", "unknown"))
            lines.append(f"### {emoji} {category}\n")
            for key in ["term", "matched_text", "position", "issue", "suggestion"]:
                if key in item and item[key]:
                    lines.append(f"- **{key}**: {item[key]}")
            lines.append("")

    # 待确认信息
    if report.to_confirm:
        lines.append("## 待确认信息\n")
        for i, item in enumerate(report.to_confirm, 1):
            lines.append(f"{i}. {item}")
        lines.append("")

    return "\n".join(lines)


def save_to_file(content: str, filepath: str | Path) -> None:
    """保存内容到文件。

    Args:
        content: 要保存的内容
        filepath: 文件路径
    """
    filepath = Path(filepath)
    filepath.parent.mkdir(parents=True, exist_ok=True)

    with open(filepath, "w", encoding="utf-8") as f:
        f.write(content)
