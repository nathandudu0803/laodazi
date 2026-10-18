"""事实与图片核验(C)。

核验Draft中的陈述是否与Fact和ImageRef一致。
"""
import re
from typing import Any

from .contracts import Draft, Fact, ImageRef, Report


def verify(draft: Draft, facts: list[Fact], images: list[ImageRef]) -> Report:
    """核验软文草稿的事实准确性和图片一致性。

    Args:
        draft: 待核验的软文草稿
        facts: 可用的事实列表（已筛选）
        images: 可用的图片列表

    Returns:
        Report: 核验报告，包含fact_check, image_check, to_confirm, blocked
    """
    report = Report()

    # 1. 事实核验
    fact_check_results = _verify_facts(draft, facts)
    report.fact_check = fact_check_results

    # 2. 图片核验
    image_check_results = _verify_images(draft, images)
    report.image_check = image_check_results

    # 3. 汇总待确认项
    report.to_confirm = _collect_to_confirm(facts, fact_check_results)

    # 4. 判断是否阻断
    # 阻断条件：有未通过的事实核验、有未通过的图片核验、型号冲突
    has_failed_facts = any(
        item.get("status") == "failed" for item in fact_check_results
    )
    has_failed_images = any(
        item.get("status") == "failed" for item in image_check_results
    )

    if has_failed_facts or has_failed_images:
        report.blocked = True
        reasons = []
        if has_failed_facts:
            failed_count = sum(
                1 for item in fact_check_results if item.get("status") == "failed"
            )
            reasons.append(f"事实核验失败 {failed_count} 项")
        if has_failed_images:
            failed_count = sum(
                1 for item in image_check_results if item.get("status") == "failed"
            )
            reasons.append(f"图片核验失败 {failed_count} 项")
        report.block_reason = "；".join(reasons)

    return report


def _verify_facts(draft: Draft, facts: list[Fact]) -> list[dict[str, Any]]:
    """核验Draft中的事实陈述。

    策略：
    1. 从正文中提取可核验陈述（数值+单位、型号、配置）
    2. 与Draft.used_fact_ids对应的Fact比对
    3. 检查数值、限定条件、配置是否一致
    """
    results = []

    # 构建fact_id到Fact的映射
    fact_map = {f.fact_id: f for f in facts}

    # 合并所有文本内容
    full_text = f"{draft.title}\n{draft.lead}\n{draft.body}\n{draft.call_to_action}"

    # 1. 型号一致性检查
    models_in_facts = {f.model for f in facts}
    if len(models_in_facts) > 1:
        results.append({
            "type": "model_consistency",
            "status": "failed",
            "issue": f"事实来源涉及多个型号：{', '.join(models_in_facts)}",
            "suggestion": "确认目标型号，不得混用不同型号的事实"
        })

    # 2. 检查Draft中引用的fact_ids
    for fact_id in draft.used_fact_ids:
        fact = fact_map.get(fact_id)
        if not fact:
            results.append({
                "type": "missing_fact",
                "fact_id": fact_id,
                "status": "failed",
                "issue": "引用了不存在的fact_id",
                "suggestion": "检查fact_id是否正确"
            })
            continue

        # 检查fact的review_status
        if fact.review_status == "pending_review":
            results.append({
                "type": "pending_review",
                "fact_id": fact_id,
                "field": fact.field,
                "value": fact.value,
                "status": "warning",
                "issue": f"待复核字段：{fact.review_note}",
                "suggestion": "此字段不应出现在软文中，应移至'待确认信息'"
            })

    # 3. 提取正文中的数值陈述并核验
    # 匹配模式：数字+单位（如"16GB""2.8K""70Wh""18mm"等）
    number_pattern = r'(\d+(?:\.\d+)?)\s*([A-Za-z]+|英寸|小时|毫米|克)'
    matches = re.findall(number_pattern, full_text)

    for number, unit in matches:
        # 检查这个数值是否能在facts中找到依据
        value_str = f"{number}{unit}" if unit.isalpha() else f"{number} {unit}"
        found = False

        for fact in facts:
            # 简化的匹配：检查fact.value中是否包含这个数值
            if number in fact.value and (unit in fact.value or unit.lower() in fact.value.lower()):
                found = True
                # 检查限定条件是否保留
                if fact.qualifier and fact.qualifier not in full_text:
                    results.append({
                        "type": "qualifier_missing",
                        "fact_id": fact.fact_id,
                        "field": fact.field,
                        "value": value_str,
                        "status": "failed",
                        "issue": f"数值 {value_str} 缺少限定条件：{fact.qualifier}",
                        "suggestion": f"应表述为：{value_str}（{fact.qualifier}）"
                    })
                break

        if not found and _is_spec_value(unit):
            # 这是一个规格参数，但在facts中找不到依据
            results.append({
                "type": "unverified_value",
                "value": value_str,
                "status": "failed",
                "issue": f"数值 {value_str} 在知识库中无依据",
                "suggestion": "删除或替换为有依据的数值"
            })

    # 如果没有发现问题，添加一条通过记录
    if not results:
        results.append({
            "type": "overall",
            "status": "passed",
            "message": "事实核验通过"
        })

    return results


def _verify_images(draft: Draft, images: list[ImageRef]) -> list[dict[str, Any]]:
    """核验Draft中的图片引用。

    检查：
    1. 每张图是否在images列表中
    2. 图片型号与事实型号是否一致
    3. 来源、说明、位置是否完整
    """
    results = []

    # 构建filename到ImageRef的映射
    image_map = {img.filename: img for img in images}

    # 检查Draft中的每张图
    for draft_image in draft.image_plan:
        filename = draft_image.filename

        # 1. 检查图片是否在可用列表中
        if filename not in image_map:
            results.append({
                "type": "unknown_image",
                "filename": filename,
                "status": "failed",
                "issue": "图片不在知识库ImageRef清单中",
                "suggestion": "删除此图或使用知识库中的图片"
            })
            continue

        kb_image = image_map[filename]

        # 2. 检查型号一致性
        if draft_image.model != kb_image.model:
            results.append({
                "type": "model_mismatch",
                "filename": filename,
                "draft_model": draft_image.model,
                "kb_model": kb_image.model,
                "status": "failed",
                "issue": f"图片型号不一致：Draft中为 {draft_image.model}，知识库中为 {kb_image.model}",
                "suggestion": "修正型号或更换图片"
            })

        # 3. 检查必需字段
        if not draft_image.source:
            results.append({
                "type": "missing_source",
                "filename": filename,
                "status": "failed",
                "issue": "图片缺少来源说明",
                "suggestion": "添加来源说明"
            })

        if not draft_image.caption:
            results.append({
                "type": "missing_caption",
                "filename": filename,
                "status": "warning",
                "issue": "图片缺少说明",
                "suggestion": "添加图片说明"
            })

        if not draft_image.suggested_position:
            results.append({
                "type": "missing_position",
                "filename": filename,
                "status": "warning",
                "issue": "图片缺少建议插入位置",
                "suggestion": "指定插入位置"
            })

    # 如果没有发现问题，添加一条通过记录
    if not results:
        results.append({
            "type": "overall",
            "status": "passed",
            "message": "图片核验通过"
        })

    return results


def _collect_to_confirm(facts: list[Fact], fact_check_results: list[dict]) -> list[str]:
    """收集待确认信息。

    包括：
    1. review_status为pending_review的字段
    2. 核验中发现的问题
    """
    to_confirm = []

    # 1. 待复核字段
    for fact in facts:
        if fact.review_status == "pending_review":
            to_confirm.append(
                f"{fact.field}：{fact.value}（{fact.review_note}）"
            )

    # 2. 核验警告项
    for item in fact_check_results:
        if item.get("status") == "warning":
            to_confirm.append(item.get("issue", ""))

    return to_confirm


def _is_spec_value(unit: str) -> bool:
    """判断单位是否属于规格参数。

    规格参数包括：存储、内存、屏幕、电池、尺寸、重量等。
    """
    spec_units = {
        # 存储和内存
        "gb", "tb", "mb",
        # 屏幕
        "英寸", "inch", "k", "hz", "nits", "nit",
        # 电池
        "wh", "mah", "w",
        # 尺寸和重量
        "mm", "cm", "毫米", "厘米", "g", "kg", "克", "千克",
        # 处理器
        "ghz", "core", "核",
    }
    return unit.lower() in spec_units
