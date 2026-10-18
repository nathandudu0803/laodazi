# C 模块完成清单

## ✅ 已完成的工作

### 1. 禁用词表 (`data/banned_terms.yaml`)
- [x] 从知识库提取 50+ 条禁用词
- [x] 分 6 大类：绝对化、虚假承诺、价格误导、竞品贬低、体验虚构、其他风险
- [x] 每条包含：term（支持正则）、category、severity、suggestion、context
- [x] 来源可追溯：P6/08-合规、P6/02-平台模板、P3/08-竞品对比

### 2. 事实核验 (`agent/verify.py`)
- [x] 型号一致性检查（facts 中不得涉及多个型号）
- [x] fact_id 引用检查（Draft.used_fact_ids 必须在 facts 中存在）
- [x] 待复核字段警告（review_status == "pending_review"）
- [x] 数值依据核验（提取"数字+单位"，与 facts 比对）
- [x] 限定条件检查（qualifier 必须在正文中保留）
- [x] 图片核验（filename、model、source、caption、position）
- [x] 返回结构化报告（Report.fact_check、image_check、to_confirm、blocked）

### 3. 合规检查 (`agent/compliance.py`)
- [x] 禁用词扫描（title/lead/body/cta/tags 五个位置）
- [x] 正则匹配支持（如"最.*"、".*元"）
- [x] 上下文例外处理（如"第一代""第一步"不拦截"第一"）
- [x] 价格护栏：
  - [x] 金额必须在 price_records 中
  - [x] 必须带价格类型和核验日期
  - [x] 拦截国补、教育优惠、以旧换新（知识库无数值）
- [x] 禁止内容检查：第一人称体验、用户评价、销量、奖项、库存
- [x] 自动改写尝试（auto_fix_and_recheck，最多 2 轮）
- [x] 返回结构化结果（含 blocking 标记）

### 4. 导出功能 (`agent/export.py`)
- [x] export_markdown(draft, report) - Markdown 格式
- [x] export_text(draft, report) - 纯文本格式
- [x] export_report_only(report) - 仅导出报告
- [x] save_to_file(content, filepath) - 保存文件
- [x] 阻断状态明确标注（⚠️ 警告横幅）
- [x] 配图方案完整展示（文件名、型号、来源、说明、位置）
- [x] 核验报告附加在末尾（事实/图片/合规/待确认）

### 5. Gradio 界面 (`app.py`)
- [x] 输入区：产品(必填)、人群、场景、平台(下拉)、临时要求
- [x] 输出区：四个 Tab（场景判断 / 知识库依据 / 图文软文 / 核验结果）
- [x] 导出区：Markdown 和纯文本两个 Tab
- [x] 知识库状态显示（不显示密钥）
- [x] 追问提示（信息不足时）
- [x] 阻断警示（🚫 明确标记）
- [x] 异常处理（网络、接口、模型错误）
- [x] 使用说明和注意事项

### 6. 文档与测试
- [x] 更新 `docs/handoff.md`（C 的第 1-5 步完成记录）
- [x] 更新 `README.md`（添加核验、合规、界面说明）
- [x] 创建 `tests/test_c_modules.py`（单元测试样例）

## 📊 数据统计

- **禁用词数量**: 50+ 条
- **代码行数**: 
  - verify.py: ~250 行
  - compliance.py: ~300 行
  - export.py: ~200 行
  - app.py: ~250 行
  - 总计: ~1000+ 行

- **核验能力**:
  - 型号一致性 ✓
  - 事实依据 ✓
  - 限定条件 ✓
  - 待复核字段 ✓
  - 图片型号 ✓
  - 禁用词 ✓
  - 价格护栏 ✓
  - 虚假内容 ✓

## 🧪 验证方式

### 方式 1：运行测试脚本
```bash
cd hwpc-agent
python tests/test_c_modules.py
```

### 方式 2：启动界面
```bash
cd hwpc-agent
python app.py
# 访问 http://localhost:7860
```
输入测试数据：
- 产品：MateBook 14
- 人群：大学新生
- 场景：宿舍写论文
- 平台：小红书

### 方式 3：手工构造
```python
from agent.verify import verify
from agent.compliance import compliance_check
from agent.contracts import Draft, Fact, ImageRef

# 构造包含问题的 Draft
draft = Draft(
    title="全网最低价！最后三台",
    body="亲测好用，碾压竞品，国补立减 500 元"
)

# 运行合规检查
results = compliance_check(draft)
# 应拦截：全网最低、最后三台、亲测、碾压、国补
```

## ⚠️ 已知限制

1. **数值匹配简化**：采用子串匹配，复杂表述需人工复核
2. **自动改写有限**：只删除禁用词，不生成替代文本
3. **图片预览缺失**：界面不显示图片，只展示文件名和来源
4. **价格类型未细检**：未检查"预估到手价"误当"现价"

## 🔄 接下来

### 等待 B 完成：
- `agent/scene.py` - 场景解析
- `agent/platform_rules.py` - 平台策略
- `agent/compose.py` - 软文生成

完成后可进行：
- 端到端联调
- 替换 pipeline 中的桩函数
- 全流程测试

### 等待 D 完成：
- 测试用例设计
- 对抗样本测试
- 边界条件测试
- 文档整理

## 📝 使用示例

### 示例 1：正常流程
```python
from agent import pipeline
from agent.retriever.local import LocalRetriever

retriever = LocalRetriever()
task = TaskInput(
    product="MateBook 14",
    audience="大学新生",
    scene="宿舍写论文",
    platform="小红书"
)

result = pipeline.run(task, retriever)
# result.status == "ok"
# result.draft 包含生成的软文
# result.report 包含核验报告
```

### 示例 2：阻断情况
```python
# 假设 B 生成了包含禁用词的 Draft
# C 的合规检查会拦截：
result = pipeline.run(task, retriever)
# result.status == "blocked"
# result.report.blocked == True
# result.report.block_reason == "合规检查失败：阻断项 5 项"
```

### 示例 3：导出
```python
from agent.export import export_markdown, save_to_file

markdown = export_markdown(result.draft, result.report)
save_to_file(markdown, "output/draft.md")
```

## 🎯 核心价值

C 模块作为最后一道防线，确保：

1. **事实准确**：型号不混、数值有据、限定条件保留
2. **图片合规**：来自知识库、型号一致、来源可追溯
3. **价格可靠**：金额有依据、类型明确、日期标注
4. **表述规范**：拦截禁用词、虚假承诺、竞品贬低
5. **结果透明**：核验报告完整、阻断原因明确、待确认项清晰

直接影响评分：
- 事实准确性（20 分）
- 图文生成与图片引用（15 分）
- 合规与安全（5 分）
- 功能完成度与体验（10 分）

**总计 50 分，占比 50%！**

---

**状态**: ✅ C 的第 1-5 步全部完成
**最后更新**: 2026-10-18
**负责人**: C
