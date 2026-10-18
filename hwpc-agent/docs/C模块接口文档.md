# C 模块接口文档

> 供 B、D 同学调用 C 模块功能的快速参考

## 核心函数

### 1. verify() - 事实与图片核验

```python
from agent.verify import verify
from agent.contracts import Draft, Fact, ImageRef, Report

def verify(draft: Draft, facts: list[Fact], images: list[ImageRef]) -> Report:
    """
    核验软文草稿的事实准确性和图片一致性。
    
    Args:
        draft: 待核验的软文草稿（B 生成的）
        facts: 可用的事实列表（A 的 FactSelection.usable）
        images: 可用的图片列表（A 的 retriever.get_images()）
    
    Returns:
        Report: 核验报告
            - fact_check: 事实核验结果（list[dict]）
            - image_check: 图片核验结果（list[dict]）
            - to_confirm: 待确认信息（list[str]）
            - blocked: 是否阻断（bool）
            - block_reason: 阻断原因（str）
    """
```

**检查内容**:
- ✅ 型号一致性（facts 中不得涉及多个型号）
- ✅ fact_id 引用（Draft.used_fact_ids 必须都存在）
- ✅ 待复核字段（review_status == "pending_review" 标记警告）
- ✅ 数值依据（提取"数字+单位"，检查是否在 facts 中）
- ✅ 限定条件（qualifier 必须在正文中保留）
- ✅ 图片核验（filename、model、source、caption）

**调用示例**:
```python
# B 在 compose() 中生成 Draft 后
draft = Draft(
    title="MateBook 14：学生党首选",
    body="屏幕 14 英寸，电池 56 Wh（标准版）...",
    image_plan=[...],
    used_fact_ids=["f1", "f2", "f3"]  # 必须填写！
)

# 调用 C 的核验
report = verify(draft, facts, images)

if report.blocked:
    print(f"核验未通过：{report.block_reason}")
    # 不应进入导出
else:
    print("核验通过")
    # 继续合规检查
```

---

### 2. compliance_check() - 合规检查

```python
from agent.compliance import compliance_check

def compliance_check(
    draft: Draft, 
    price_records: list[dict] | None = None
) -> list[dict]:
    """
    合规检查：禁用词、价格护栏、虚假承诺。
    
    Args:
        draft: 待检查的软文草稿
        price_records: 价格记录（可选，来自 retriever.get_price_records()）
    
    Returns:
        list[dict]: 合规检查结果
            - type: 检查类型
            - term: 命中的词
            - position: 位置（title/lead/body/cta/tags）
            - category: 类别
            - severity: blocking/warning
            - suggestion: 改写建议
            - blocking: 是否阻断（bool）
    """
```

**检查内容**:
- 🚫 禁用词（50+ 条，分 6 大类）
- 💰 价格护栏（金额有依据、类型明确、日期标注）
- ⚠️ 禁止内容（第一人称、用户评价、销量、奖项）

**调用示例**:
```python
# 调用合规检查
price_records = retriever.get_price_records(model)
results = compliance_check(draft, price_records)

# 检查是否有阻断项
blocking_items = [item for item in results if item.get("blocking")]
if blocking_items:
    print(f"合规未通过：{len(blocking_items)} 个阻断项")
    # Report.blocked = True
    # Report.compliance = results
else:
    print("合规通过")
```

**阻断判断**:
```python
# pipeline 中判断阻断的逻辑
has_blocking = any(item.get("blocking") for item in compliance_results)
if has_blocking:
    report.blocked = True
    report.block_reason = f"合规检查失败：阻断项 {len(blocking_items)} 项"
```

---

### 3. export_markdown() / export_text() - 导出

```python
from agent.export import export_markdown, export_text, save_to_file

def export_markdown(draft: Draft, report: Report | None = None) -> str:
    """导出为 Markdown 格式，含核验报告。"""

def export_text(draft: Draft, report: Report | None = None) -> str:
    """导出为纯文本格式，不含 Markdown 标记。"""

def save_to_file(content: str, filepath: str | Path) -> None:
    """保存内容到文件。"""
```

**调用示例**:
```python
# 导出 Markdown
markdown = export_markdown(draft, report)
save_to_file(markdown, "output/draft.md")

# 导出纯文本
text = export_text(draft, report)
save_to_file(text, "output/draft.txt")
```

---

## Pipeline 集成

### 在 pipeline.py 中的调用顺序

```python
# A 的 pipeline.py（第 3 步）
def run(task: TaskInput, retriever: Retriever, steps: Steps | None = None):
    # ... 前面的步骤 ...
    
    # B 生成软文
    draft = steps.compose(task, scene, plan, fact_selection, images)
    
    # C 核验事实与图片
    report = steps.verify(draft, fact_selection.usable, images)
    
    if report.blocked:
        return PipelineResult(
            status="blocked",
            task=task,
            report=report
        )
    
    # C 合规检查
    price_records = retriever.get_price_records(task.model)
    compliance_results = steps.compliance(draft, price_records)
    report.compliance = compliance_results
    
    # 检查合规阻断
    has_blocking = any(item.get("blocking") for item in compliance_results)
    if has_blocking:
        report.blocked = True
        blocking_count = sum(1 for item in compliance_results if item.get("blocking"))
        report.block_reason = f"合规检查失败：阻断项 {blocking_count} 项"
        return PipelineResult(
            status="blocked",
            task=task,
            draft=draft,
            report=report
        )
    
    # C 导出
    steps.export(draft, report)
    
    return PipelineResult(
        status="ok",
        task=task,
        scene=scene,
        plan=plan,
        facts=fact_selection.usable,
        draft=draft,
        report=report
    )
```

---

## Draft 必须字段

B 在生成 Draft 时，必须填写以下字段：

```python
draft = Draft(
    title="...",           # 标题
    lead="...",            # 导语（可为空）
    body="...",            # 正文（必填）
    image_plan=[...],      # 配图方案（ImageRef 列表）
    call_to_action="...",  # 行动引导（可为空）
    tags=[...],            # 标签（可为空）
    used_fact_ids=[...]    # 🔴 重要！引用的 fact_id 列表
)
```

**⚠️ 特别注意**：
- `used_fact_ids` 必须填写，C 的核验依赖它来对照事实
- 不能只填 `body`，其他字段留空

---

## Report 结构

```python
@dataclass
class Report:
    fact_check: list[dict] = []      # 事实核验结果
    image_check: list[dict] = []     # 图片核验结果
    compliance: list[dict] = []      # 合规检查结果
    to_confirm: list[str] = []       # 待确认信息
    blocked: bool = False            # 是否阻断
    block_reason: str = ""           # 阻断原因
```

**fact_check / image_check 中的 dict 结构**:
```python
{
    "type": "qualifier_missing",     # 问题类型
    "fact_id": "f1",                 # 相关的 fact_id
    "field": "电池.容量",            # 字段名
    "value": "56 Wh",                # 数值
    "status": "failed",              # passed/warning/failed
    "issue": "数值缺少限定条件",     # 问题描述
    "suggestion": "应标注配置"       # 改进建议
}
```

**compliance 中的 dict 结构**:
```python
{
    "type": "banned_term",           # 检查类型
    "term": "全网最低",              # 命中的词
    "position": "title",             # 位置
    "category": "价格误导",          # 类别
    "severity": "blocking",          # blocking/warning
    "suggestion": "删除价格比较",    # 改写建议
    "blocking": True,                # 是否阻断
    "matched_text": "...【全网最低】..."  # 匹配的上下文
}
```

---

## 禁用词表

位置：`data/banned_terms.yaml`

**分类**:
1. 绝对化用语：唯一、第一、最强、全面领先、零风险、永不卡
2. 虚假承诺：终身免费、无条件退换、全部覆盖、绝对兼容
3. 虚假稀缺：最后三台、仅剩、库存告急、懂的私聊、内部价
4. 价格误导：全网最低、国补立减、教育优惠、以旧换新、到手价
5. 竞品贬低：碾压、吊打、秒杀、完爆、完胜、远超
6. 体验虚构：亲测、实测、我用、效率翻倍、客户反馈

**追加方式**:
```yaml
banned_terms:
  - term: "新增的禁用词"
    category: "类别"
    severity: "blocking"  # 或 warning
    suggestion: "改写建议"
    context: "允许：'合理上下文'"  # 可选
```

---

## 测试用例

### 对抗样例（D 可用）

```python
# 1. 型号混用
draft = Draft(
    body="MateBook D 14 的续航达到 70 Wh",  # 70Wh 是 D 16 的数据
    used_fact_ids=["d14_battery"]  # 但引用的是 D 14 的 fact
)
# 预期：verify() 应标记为 "unverified_value"

# 2. 缺失限定条件
draft = Draft(
    body="电池容量 56 Wh，长续航",  # 缺少"标准版"限定
    used_fact_ids=["f2"]
)
# 预期：verify() 应标记为 "qualifier_missing"

# 3. 使用待复核字段
draft = Draft(
    body="重量约 1.39 kg",  # D 14 的重量字段是 pending_review
    used_fact_ids=["d14_weight_pending"]
)
# 预期：verify() 应标记为 "pending_review"，to_confirm 非空

# 4. 禁用词
draft = Draft(
    title="全网最低价！最后三台",
    body="亲测好用，碾压竞品"
)
# 预期：compliance_check() 应返回 4 个 blocking 项

# 5. 价格无依据
draft = Draft(
    body="现价 5999 元"  # 但 price_records 中没有 5999
)
# 预期：compliance_check() 应标记为 "unverified_price"

# 6. 国补
draft = Draft(
    body="国补立减 500 元"
)
# 预期：compliance_check() 应标记为 "forbidden_price_term"
```

---

## 常见问题

### Q1: 为什么我的 Draft 核验失败？
**A**: 检查以下几点：
1. `used_fact_ids` 是否填写？
2. 正文中的数值是否都能在 facts 中找到？
3. 限定条件（qualifier）是否保留在正文中？
4. 图片的 model 是否与 facts 的 model 一致？

### Q2: 如何判断是否阻断？
**A**: 检查两处：
1. `report.blocked == True`（verify 阶段）
2. `any(item.get("blocking") for item in compliance_results)`（compliance 阶段）

### Q3: 自动改写能修复所有问题吗？
**A**: 不能。`auto_fix_and_recheck()` 只做简单删除，复杂问题需人工修改。

### Q4: 价格怎么写才不会被拦截？
**A**: 
1. 金额必须在 `price_records` 中
2. 必须标注价格类型（"预估到手价""官网参考起价"）
3. 必须标注核验日期
4. 不得使用国补、教育优惠、以旧换新（知识库无数值）

### Q5: 图片怎么选才不会被拦截？
**A**:
1. 只使用 `retriever.get_images(model)` 返回的图片
2. 保持 `ImageRef.model` 与目标型号一致
3. 填写完整的 source、caption、suggested_position

---

## 联系方式

如有疑问，查看：
- `docs/handoff.md` - 完整交接记录
- `docs/C模块完成清单.md` - 功能清单
- `tests/test_c_modules.py` - 测试样例

---

**最后更新**: 2026-10-18  
**负责人**: C
