# handoff(只追加,不修改既有条目)

## [2026-10-18] A:第 0 步完成

完成了什么:仓库骨架、数据契约、Retriever 抽象接口、llm 封装、配置文件。B、C 可以开工。

仓库位置:`huawei/hwpc-agent/`(`F:\华为浙克松\` 在本机不存在,按相对路径处理)。

改动文件:`agent/contracts.py`、`agent/retriever/base.py`、`agent/llm.py`、`.gitignore`、`.env.example`、`requirements.txt`、`README.md`、`docs/handoff.md`,以及各模块空壳。

### 契约字段(`agent/contracts.py`,已冻结)

- `TaskInput`:product, audience, scene, platform, extra_requirements, model
- `SceneProfile`:audience, usage_scene, purchase_stage, main_problem, content_goal, missing_info(list)
- `PlatformPlan`:platform, title_style, length, structure(list), tone, image_count_min, image_count_max, call_to_action
- `Fact`:fact_id, model, field, value, qualifier, footnote, source_title, source_path, review_status("ok"|"pending_review"), review_note
- `ImageRef`:filename, model, source, caption, suggested_position, file_path, source_page
- `Draft`:title, lead, body, image_plan(list[ImageRef]), call_to_action, tags(list), used_fact_ids(list)
- `Report`:fact_check, image_check, compliance(均为 list[dict]), to_confirm(list[str]), blocked(bool), block_reason
- `ModelMatch`:candidates(list[str]), need_clarify(bool), clarify_hint

相对总览第 6 节新增的字段:`Fact.fact_id/footnote/review_status/review_note`、`ImageRef.file_path/source_page`、`Draft.used_fact_ids`、`Report.block_reason`、`TaskInput.model`、`ModelMatch`。

### 接口签名(`agent/retriever/base.py`)

- `find_models(query: str) -> ModelMatch`
- `get_facts(model: str) -> list[Fact]`
- `get_selling_points(model: str) -> dict`(键:positioning, angles, must_ask, compliance_examples)
- `get_images(model: str) -> list[ImageRef]`
- `get_price_records(model: str) -> list[dict]`

### llm(`agent/llm.py`)

- `chat(messages, retries=3, **kw) -> str`
- `chat_json(messages, retries=3, **kw)`:解析失败带提示重试
- `extract_json(text)`、`redact(text)`、`LLMError`
- 环境变量:`LLM_BASE_URL`、`LLM_API_KEY`、`LLM_MODEL`、`LLM_TIMEOUT`

### 下游需要知道

- `Fact.review_status == "pending_review"` 的事实,C 的核验要透传为"待确认",B 生成时不得当确定结论使用。
- 价格空金额是 `None`,不是 0。
- 易混淆型号 `need_clarify=True` 时 pipeline 会返回追问,不进入生成。
- 本机 Python 为 3.14,依赖已按能装的版本固定。

## [2026-10-18] A:第 1、2 步完成(LocalRetriever + 型号别名)

完成了什么:`LocalRetriever` 可对 10 个型号返回 Fact / 卖点 / ImageRef / 价格记录;`find_models` 对易混淆输入返回多候选并置 `need_clarify`。

改动文件:`agent/retriever/local.py`、`agent/retriever/local_parsers.py`(新增)、`data/model_aliases.yaml`、`tests/test_local_retriever.py`。

怎么验证:`py -m pytest tests -q`,28 项通过。用法:`LocalRetriever()`(读 `LOCAL_KB_ROOT`,默认 `../华为PC全板块深度知识库_v7`);另有 `list_models()`。

下游需要知道:
- 规范型号以图片索引"产品型号"列为准,共 10 个,见 `data/model_aliases.yaml`。传给 `get_*` 的必须是规范型号,否则抛 `KeyError`。
- `Fact.field` 形如 `屏幕.亮度`、`尺寸与重量.重量`;多配置各自一条,`qualifier` 记配置(如 标准屏版、Windows 版、标准版)。脚注在 `footnote`,原样保留。
- 尺寸"长度/宽度/厚度"三条在 D 14、D 16、D 16 SE、X Pro 酷睿 Ultra 微绒典藏版 4 个型号上标为 `pending_review`,`review_note` 写明依据。数值按原文保留,没有自动更正,这 4 个型号的尺寸在复核前不得写进软文。其余 6 个型号未发现此错位。
- GT 14 的高度 15.3 mm 为标称,脚注里有最大厚度 18.4 mm,两个数都保留。
- `get_images`:只返回图片索引里登记且文件真实存在的图,型号与索引一致。HUAWEI MateBook 14(鸿蒙版)另含 15 张商城款式图(`vmall_` 开头,来源为商品页),共 19 张;其余型号不含商城图。P6 通用商城图不在本接口内。
- 部分图片 `官网图片说明` 为空时,说明取自文件名里的画面主题;`suggested_position` 是按说明关键词给的建议,不是官方信息。
- `get_price_records`:原样返回 CSV 全部字段,另加 `amount`、`reference_amount`(空为 None,绝不转 0)、`model`。4 个鸿蒙型号有现价,6 个 Windows 型号仅 1 条官网参考起价(不是当前商城价,不得当现价写)。价格类型必须随数字一起展示。
- `find_models("D 16")`、`"Pro"`、`"MateBook 14"`、`"D系列"` 会返回多候选且 `need_clarify=True`;查询里同时提到多个型号(如"D14和D16")也返回全部并要求确认。

## [2026-10-18] A:第 3 步完成(facts.py + pipeline.py)

完成了什么:事实点筛选和流程编排,B、C 模块用桩跑通端到端。

改动文件:`agent/facts.py`、`agent/pipeline.py`、`tests/test_pipeline.py`。

怎么验证:`py -m pytest tests -q`,38 项通过。

下游需要知道:
- 入口 `pipeline.run(task, retriever, steps=None) -> PipelineResult`。`status` 取 `ok` / `need_info`(看 `questions`)/ `blocked`(看 `report.block_reason`)。
- 替换桩:构造 `Steps(scene=..., platform=..., compose=..., verify=..., compliance=..., export=...)` 传入,pipeline 不用改。签名:
  - B:`scene(task) -> SceneProfile`(`missing_info` 非空即追问);`platform(task, scene) -> PlatformPlan`;`compose(task, scene, plan, sel: FactSelection, images) -> Draft`
  - C:`verify(draft, sel, images) -> Report`(置 `blocked` 和 `block_reason`);`compliance(draft) -> list[dict]`(任一项含 `"blocking": True` 即阻断);`export(draft, report)`
- `FactSelection.usable` 才能写进软文;`pending`(待复核)只能作为待确认项。`Draft.used_fact_ids` 必须填,核验靠它对照。
- 型号不确定、场景信息缺失、平台未选、检索失败、无可用事实、核验或合规阻断,都不会进入导出。
- 桩 compose/verify 只做确定性处理,仅用于联调,不是正式实现。

## [2026-10-18] B:第 1 到 4 步完成(平台、场景、提示词、编排)

完成了什么:平台参数表、场景库、8 个系统提示词模块,以及 `platform_rules.py` / `scene.py` / `compose.py` 三个模块。用 A 的 `LocalRetriever` 与 `pipeline` 做过端到端联调(模型为本地替身,未调用真实大模型)。

改动文件:`agent/platform_rules.py`、`agent/scene.py`、`agent/compose.py`、`data/platform_specs.yaml`、`data/scene_library.yaml`、`prompts/01_role.md` 至 `08_compliance.md`、`tests/test_b_modules.py`,以及 `.gitignore` 末尾追加几行(未改 A 已有的行)。

怎么验证:`py -m pytest tests/test_b_modules.py -q`,21 项通过。

### 接入 pipeline 的写法

```python
from agent.pipeline import Steps, run
from agent.scene import scene_step
from agent.platform_rules import platform_step
from agent.compose import compose_step

steps = Steps(scene=scene_step, platform=platform_step, compose=compose_step)
res = run(task, retriever, steps)
```

### 对齐 A 契约的取舍

- `TaskInput.platform` 取 公众号 / 小红书 / 朋友圈 / 海报。`platform_rules.normalize_platform` 会把"微信公众号""门店海报"等别名归一;无法识别抛 `UnknownPlatform`。
- `SceneProfile.purchase_stage` 只取 了解 / 比较 / 决策 / 已购。原先想用的"到店"并入"决策",用 `visit_intent` 保留差异。阶段是否为推断,单独用 `scene.is_stage_inferred(task)` 回答,不污染契约字段。
- 契约未改动。`compose` 返回 `ComposedDraft`(继承 `Draft`),多出三个字段,pipeline / verify / export 不需要改:
  - `strategy`:内容策略说明(切入点、卖点顺序、不写什么、图片安排),手册要求评委能看到"为什么这样写"
  - `title_options`:备选标题
  - `pending`:待确认项

### 给 C 的提示

- 请把 `getattr(draft, "pending", [])` 并入 `Report.to_confirm`。导出 Markdown 可直接用 `compose.render_markdown(draft)`,它会带上策略说明、配图方案和待确认项。
- 模型若编造事实点 ID,我**故意保留**在 `used_fact_ids` 里,让 `verify` 去阻断,不在 compose 里悄悄删掉。
- 模型若编造图片文件名,compose 直接丢弃并写进 `pending`,不会把它换成别的图。
- 同型号可用图片少于平台下限时,不用其他型号补数,在 `pending` 里写"可用同型号图片不足"。

### 给 A 的提示

- `compose` 只接受 `FactSelection.usable` 里的事实,`pending` 不会进入提示词。提示词里事实点按场景的 `fact_priority` 排序,最多 14 条。
- `scene.parse_scene(task, use_llm=False)` 默认纯规则,可复现;打开 `use_llm=True` 才会用模型整理自由文本,模型不可用时自动退回规则层。
- 追问最多 3 条,来源于 `data/scene_library.yaml` 的 `clarifying_questions`。

### 已知限制

- 尚未用真实大模型验证写作质量,等 `LLM_API_KEY` 配好后做。
- 尚未接 ima(用的是本地副本)。
- 场景匹配目前是关键词规则,8 类之外会走兜底场景,兜底只写"人群、任务、事实、限制"四件事。
- 增强模块(客户洞察卡、1/3/7 天跟进)只写在 `prompts/06_generation.md` 末尾,代码里还没有实现。
