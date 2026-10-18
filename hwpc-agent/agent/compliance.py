"""合规检查(C)。

检查软文中的禁用词、价格护栏、虚假承诺等合规问题。
"""
import re
from pathlib import Path
from typing import Any

import yaml

from .contracts import Draft


def load_banned_terms() -> dict:
    """加载禁用词表。"""
    terms_file = Path(__file__).parent.parent / "data" / "banned_terms.yaml"
    if not terms_file.exists():
        return {"banned_terms": []}

    with open(terms_file, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f)
    return data or {"banned_terms": []}


def compliance_check(draft: Draft, price_records: list[dict] | None = None) -> list[dict[str, Any]]:
    """合规检查。

    Args:
        draft: 待检查的软文草稿
        price_records: 价格记录（可选），用于价格护栏

    Returns:
        list[dict]: 合规检查结果列表，每项包含：
            - type: 检查类型
            - term: 命中的词
            - position: 位置（title/lead/body/cta/tags）
            - category: 类别
            - severity: blocking/warning
            - suggestion: 改写建议
            - blocking: 是否阻断（bool）
    """
    results = []

    # 1. 禁用词检查
    banned_results = _check_banned_terms(draft)
    results.extend(banned_results)

    # 2. 价格护栏
    if price_records is not None:
        price_results = _check_price_compliance(draft, price_records)
        results.extend(price_results)

    # 3. 禁止项检查
    forbidden_results = _check_forbidden_content(draft)
    results.extend(forbidden_results)

    return results


def _check_banned_terms(draft: Draft) -> list[dict[str, Any]]:
    """检查禁用词。"""
    results = []
    banned_data = load_banned_terms()
    banned_terms = banned_data.get("banned_terms", [])

    # 待检查的字段
    check_fields = {
        "title": draft.title,
        "lead": draft.lead,
        "body": draft.body,
        "cta": draft.call_to_action,
        "tags": " ".join(draft.tags) if draft.tags else "",
    }

    # 对每个字段进行检查
    for position, text in check_fields.items():
        if not text:
            continue

        for term_obj in banned_terms:
            term = term_obj.get("term", "")
            category = term_obj.get("category", "")
            severity = term_obj.get("severity", "warning")
            suggestion = term_obj.get("suggestion", "")
            context = term_obj.get("context", "")

            # 检查是否命中
            if _match_term(text, term):
                # 检查上下文例外
                if context and _match_context_exception(text, term, context):
                    continue

                results.append({
                    "type": "banned_term",
                    "term": term,
                    "position": position,
                    "category": category,
                    "severity": severity,
                    "suggestion": suggestion,
                    "blocking": severity == "blocking",
                    "matched_text": _extract_matched_text(text, term)
                })

    return results


def _check_price_compliance(draft: Draft, price_records: list[dict]) -> list[dict[str, Any]]:
    """价格护栏检查。

    规则：
    1. 正文中的金额必须能在price_records中找到对应记录
    2. 必须带价格类型和核验日期
    3. 预估到手价不能当现价，官网参考起价只作参考
    4. 优惠（券、积分、分期、赠品）必须分行说明
    5. 国补、以旧换新、教育优惠：知识库无数值，一律拦截
    """
    results = []

    # 合并所有文本
    full_text = f"{draft.title}\n{draft.lead}\n{draft.body}\n{draft.call_to_action}"

    # 1. 提取金额（匹配 "数字+元" 或 "¥数字" 或 "数字+"）
    price_pattern = r'(?:¥|￥)?\s*(\d{1,6}(?:[,，]\d{3})*(?:\.\d{1,2})?)\s*(?:元|块|rmb)?'
    matches = re.findall(price_pattern, full_text, re.IGNORECASE)

    if not matches:
        return results  # 没有价格信息，无需检查

    # 清理数字中的逗号
    amounts = [float(m.replace(',', '').replace('，', '')) for m in matches]

    # 构建price_records的金额集合
    valid_amounts = set()
    for record in price_records:
        if record.get("amount") is not None:
            valid_amounts.add(float(record["amount"]))
        if record.get("reference_amount") is not None:
            valid_amounts.add(float(record["reference_amount"]))

    # 2. 检查每个金额是否有依据
    for amount in amounts:
        if amount not in valid_amounts:
            results.append({
                "type": "unverified_price",
                "amount": amount,
                "severity": "blocking",
                "blocking": True,
                "issue": f"金额 {amount} 元在知识库价格记录中无依据",
                "suggestion": "删除无依据的价格，或使用知识库中的价格并标注类型和日期"
            })

    # 3. 检查价格类型说明
    has_price_type = any(
        keyword in full_text
        for keyword in ["预估到手价", "官网参考起价", "当前价格", "价格类型", "核验日期"]
    )

    if amounts and not has_price_type:
        results.append({
            "type": "missing_price_context",
            "severity": "blocking",
            "blocking": True,
            "issue": "价格信息缺少类型说明和核验日期",
            "suggestion": "添加价格类型（如'官网参考起价'）和核验日期"
        })

    # 4. 检查禁止的价格相关词汇
    forbidden_price_terms = [
        ("国补", "知识库无国补数值，不得使用"),
        ("教育优惠.*元", "知识库无教育优惠数值，不得使用"),
        ("以旧换新.*元", "知识库无以旧换新数值，不得使用"),
        ("学生价", "知识库无学生价数值，不得使用"),
    ]

    for term, reason in forbidden_price_terms:
        if re.search(term, full_text):
            results.append({
                "type": "forbidden_price_term",
                "term": term,
                "severity": "blocking",
                "blocking": True,
                "issue": reason,
                "suggestion": "删除或标记为'待人工确认'"
            })

    return results


def _check_forbidden_content(draft: Draft) -> list[dict[str, Any]]:
    """检查明确禁止的内容。

    包括：
    - 第一人称使用体验
    - 用户评价
    - 销量
    - 奖项
    - 库存
    - 无来源对比
    """
    results = []
    full_text = f"{draft.title}\n{draft.lead}\n{draft.body}\n{draft.call_to_action}"

    forbidden_patterns = [
        (r"我.*用|亲测|实测|我的体验", "第一人称体验", "删除第一人称体验，使用产品参数"),
        (r"用户.*说|客户.*表示|.*评价|买家.*反馈", "用户评价", "不得引用未授权的用户评价"),
        (r"销量.*|卖出.*台|.*万台", "销量数据", "知识库无销量数据，删除"),
        (r"获奖|.*奖.*项|荣获", "奖项", "需提供官方授权和证明，否则删除"),
        (r"库存|现货|有货|缺货", "库存信息", "不得提及动态库存信息"),
        (r"第.*名|排名.*|.*榜", "排名信息", "需提供权威机构来源和日期，否则删除"),
    ]

    for pattern, category, suggestion in forbidden_patterns:
        if re.search(pattern, full_text):
            results.append({
                "type": "forbidden_content",
                "category": category,
                "pattern": pattern,
                "severity": "blocking",
                "blocking": True,
                "issue": f"包含禁止内容：{category}",
                "suggestion": suggestion
            })

    return results


def _match_term(text: str, term: str) -> bool:
    """匹配词汇（支持正则）。"""
    try:
        return bool(re.search(term, text))
    except re.error:
        # 如果不是有效的正则，当作普通字符串匹配
        return term in text


def _match_context_exception(text: str, term: str, context: str) -> bool:
    """检查是否符合上下文例外。

    例如：term="第一"，context="允许：'第一代''第一步'"
    提取允许的短语，检查term是否出现在这些短语中。
    """
    # 提取context中的允许短语（在引号内）
    allowed_phrases = re.findall(r"[''\"](.*?)['\"]", context)

    # 检查term在text中的匹配是否属于允许的短语
    for phrase in allowed_phrases:
        if phrase in text:
            return True

    return False


def _extract_matched_text(text: str, term: str, context_length: int = 20) -> str:
    """提取匹配到的文本片段（带上下文）。"""
    try:
        match = re.search(term, text)
        if match:
            start = max(0, match.start() - context_length)
            end = min(len(text), match.end() + context_length)
            snippet = text[start:end]
            # 在匹配部分加标记
            matched_part = match.group()
            snippet = snippet.replace(matched_part, f"【{matched_part}】")
            return f"...{snippet}..."
        return ""
    except:
        return ""


def auto_fix_and_recheck(draft: Draft, compliance_results: list[dict], max_rounds: int = 2) -> tuple[Draft, list[dict], bool]:
    """自动改写后复检。

    Args:
        draft: 原始草稿
        compliance_results: 合规检查结果
        max_rounds: 最多复检轮数

    Returns:
        tuple: (改写后的draft, 最终合规结果, 是否通过)
    """
    current_draft = draft
    current_results = compliance_results
    rounds = 0

    while rounds < max_rounds:
        # 检查是否有阻断项
        blocking_items = [item for item in current_results if item.get("blocking")]
        if not blocking_items:
            return current_draft, current_results, True

        # 尝试自动修复
        fixed_draft = _auto_fix_draft(current_draft, blocking_items)

        # 如果没有任何改动，停止尝试
        if _drafts_equal(current_draft, fixed_draft):
            return current_draft, current_results, False

        # 重新检查
        current_draft = fixed_draft
        current_results = compliance_check(current_draft)
        rounds += 1

    # 达到最大轮数仍未通过
    return current_draft, current_results, False


def _auto_fix_draft(draft: Draft, blocking_items: list[dict]) -> Draft:
    """尝试自动修复合规问题。

    简单策略：删除或替换有问题的词汇。
    """
    # 创建副本
    fixed_draft = Draft(
        title=draft.title,
        lead=draft.lead,
        body=draft.body,
        image_plan=draft.image_plan[:],
        call_to_action=draft.call_to_action,
        tags=draft.tags[:],
        used_fact_ids=draft.used_fact_ids[:]
    )

    for item in blocking_items:
        if item.get("type") == "banned_term":
            term = item.get("term", "")
            # 从各字段中删除禁用词
            fixed_draft.title = re.sub(term, "", fixed_draft.title)
            fixed_draft.lead = re.sub(term, "", fixed_draft.lead)
            fixed_draft.body = re.sub(term, "", fixed_draft.body)
            fixed_draft.call_to_action = re.sub(term, "", fixed_draft.call_to_action)

    return fixed_draft


def _drafts_equal(draft1: Draft, draft2: Draft) -> bool:
    """比较两个Draft是否相同。"""
    return (
        draft1.title == draft2.title
        and draft1.lead == draft2.lead
        and draft1.body == draft2.body
        and draft1.call_to_action == draft2.call_to_action
    )
