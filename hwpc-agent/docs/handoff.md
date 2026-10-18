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
