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

## [2026-10-18] C:第 1-5 步完成(核验、合规、导出、界面)

完成了什么:禁用词表、事实与图片核验、合规检查与价格护栏、导出功能、Gradio 界面。

改动文件:`data/banned_terms.yaml`(新建)、`agent/verify.py`、`agent/compliance.py`、`agent/export.py`、`app.py`。

### 第 1 步:禁用词表(`data/banned_terms.yaml`)

- 从知识库原文(P6/08-合规、P6/02-平台模板、P3/08-竞品对比、P5-培训赋能)提取,未凭空编造。
- 分 6 类:绝对化用语(唯一、第一、最强等)、虚假承诺与稀缺(终身免费、最后三台等)、价格误导(全网最低、国补立减等)、竞品贬低(碾压、吊打等)、体验虚构(亲测、客户反馈等)、其他风险。
- 每条含:term(词或正则)、category、severity(blocking/warning)、suggestion、context(可能误伤的上下文)。
- 共 50+ 条禁用词,覆盖知识库明确提到的全部红线。

### 第 2 步:事实核验(`agent/verify.py`)

签名:`verify(draft, facts, images) -> Report`

核验逻辑:
1. **型号一致性**:检查 facts 中是否涉及多个型号,多型号混用则阻断。
2. **fact_id 引用**:检查 `Draft.used_fact_ids` 是否都能在 facts 中找到。
3. **待复核字段**:`Fact.review_status == "pending_review"` 的事实标记为警告,提示不应出现在软文中。
4. **数值核验**:从正文提取"数字+单位"(如 16GB、70Wh、18mm),与 facts 比对,检查是否有依据。
5. **限定条件**:如果数值有 `qualifier`(如"最高""约""仅某版本"),检查正文是否保留,缺失则阻断。
6. **图片核验**:检查 `Draft.image_plan` 中的每张图是否在 images 列表中、型号是否一致、来源/说明/位置是否完整。

返回:`Report.fact_check`(list[dict])、`Report.image_check`(list[dict])、`Report.to_confirm`(list[str])、`Report.blocked`(bool)。

### 第 3 步:合规检查与价格护栏(`agent/compliance.py`)

签名:`compliance_check(draft, price_records) -> list[dict]`

检查内容:
1. **禁用词扫描**:加载 `banned_terms.yaml`,对 title/lead/body/cta/tags 逐条匹配,支持正则和上下文例外。
2. **价格护栏**:
   - 提取正文中的金额(¥数字、数字+元),检查是否在 `price_records` 的 amount/reference_amount 中。
   - 检查是否有价格类型(预估到手价、官网参考起价)和核验日期。
   - 拦截知识库无数值的:国补、教育优惠、以旧换新、学生价。
3. **禁止内容**:第一人称体验(我用、亲测)、用户评价、销量、奖项、库存、无来源排名。
4. **自动改写**:`auto_fix_and_recheck(draft, results, max_rounds=2)` 尝试删除禁用词并重新检查,最多 2 轮。

返回:list[dict],每项含 type、term、position、category、severity、suggestion、blocking。任一项 `blocking=True` 即阻断。

### 第 4 步:导出(`agent/export.py`)

提供三个函数:
- `export_markdown(draft, report) -> str`:导出 Markdown,含标题、正文、配图方案、行动引导、标签、核验报告。阻断状态明确带警示。
- `export_text(draft, report) -> str`:导出纯文本,格式简洁,适合复制。
- `export_report_only(report) -> str`:仅导出核验与合规报告,便于单独审查。
- `save_to_file(content, filepath)`:保存到文件。

### 第 5 步:Gradio 界面(`app.py`)

界面结构:
- **输入区**:产品(必填)、目标人群、使用场景、发布平台(下拉)、临时要求。
- **输出区**:四个 Tab 展示统一输出格式(一、场景判断 / 二、知识库依据 / 三、图文软文 / 四、核验结果),另有两个 Tab 提供 Markdown 和纯文本导出。
- **知识库状态**:显示是否连接本地知识库(不显示密钥)。
- **信息不足**:显示追问,不进入生成。
- **阻断状态**:明确显示 🚫 和阻断原因。
- **异常处理**:网络、接口、模型超时会显示错误提示,不会白屏。

运行:`py app.py` 或 `python app.py`,访问 `http://localhost:7860`。

### 怎么验证

1. **禁用词表**:打开 `data/banned_terms.yaml`,确认 50+ 条禁用词已录入。
2. **核验逻辑**:需要 B 完成 compose 后联调,或手写 Draft 样例测试。构造以下样例:
   - 型号混用(D 14 参数写进 D 16)
   - 错型号图片
   - 缺失限定条件(70Wh 不标注配置)
   - 待复核字段(D 16 的尺寸)
3. **合规检查**:构造包含"全网最低""国补立减""最后三台""亲测""碾压"的 Draft,检查是否全部拦截。
4. **价格护栏**:构造包含知识库没有的价格(如 5999 元)的 Draft,检查是否阻断。
5. **导出**:运行 pipeline,检查导出的 Markdown 和纯文本格式是否完整。
6. **界面**:运行 `py app.py`,在浏览器访问,输入"MateBook 14 / 大学新生 / 小红书",检查是否能完成流程并展示四段输出。

### 下游需要知道

- C 的三个核心函数签名:
  - `verify(draft, facts, images) -> Report`
  - `compliance_check(draft, price_records) -> list[dict]`
  - `export_markdown(draft, report) -> str` / `export_text(draft, report) -> str`
- pipeline 已在第 3 步中集成桩,替换 B 的真实 compose 后即可端到端运行。
- `Report.blocked` 为 `True` 时不得输出,必须人工确认或修改。
- 禁用词表支持追加,格式见文件顶部注释。
- Gradio 界面依赖 `LOCAL_KB_ROOT` 环境变量,未设置或路径不存在会显示"知识库未加载"。
- 界面与日志中不会显示任何密钥(Client ID、API Key、kb_id)。

### 已知限制

- 事实核验的"数值匹配"采用简化策略(子串匹配),复杂表述(如"约 16GB 起")可能需要人工复核。
- 自动改写(`auto_fix_and_recheck`)仅做简单删除,不生成替代文本,复杂合规问题仍需人工。
- 图片预览未实现(Gradio 需要图片真实路径或 base64),当前只展示文件名和来源。
- 价格护栏只检查金额是否在 price_records 中,未检查价格类型误用(如把"预估到手价"当"现价"),需 B 在生成时注意。

### 测试提示(给 D)

- 测试样本见知识库:`P1-产品参数库/08-官方公开价格快照/04-Agent价格问答测试集.md`(10 个对抗用例)。
- 易混淆型号对:`data/model_aliases.yaml` 中的 4 对,专项测试型号不被串用。
- 待复核字段:D 14、D 16、D 16 SE、X Pro 酷睿 Ultra 的"尺寸与重量"(长度/宽度/厚度),核验应标记为"待确认"。
- 构造包含全部 6 类禁用词的测试稿,检查拦截率。
- 界面压力测试:连续提交、中断、异常型号。

## [2026-10-21] B:ima 检索接入,已用真实凭证验证

### 新增与改动

- 新增 `agent/retriever/ima_api.py`:ima OpenAPI 客户端(Python + httpx,不依赖 Node)。
- 新增 `agent/retriever/model_index.py`:型号解析,从 `local.py` 抽出的共享实现。A 可改成引用本模块。
- 重写 `agent/retriever/ima.py`:`ImaRetriever` 实现 `Retriever` 接口,解析复用 A 的 `local_parsers`,
  保证 ima 与本地产出同构的 Fact。
- 新增 `tests/test_ima_retriever.py`(26 项,全部用假客户端,不联网、不需凭证)。
- **改动了 C 名下的 `app.py`**:修 Gradio 6 的启动报错。`Textbox` 去掉 `show_copy_button` 改用
  `buttons=["copy"]`;`theme` 从 `gr.Blocks()` 移到 `demo.launch()`;`server_name` 从 `0.0.0.0`
  改成 `127.0.0.1`(原来监听所有网卡而界面无登录验证),用 `GRADIO_SERVER_NAME` 可覆盖,部署魔搭时设 `0.0.0.0`。

### 为什么不用官方 ima_api.cjs

魔搭创空间是 Python 镜像不保证有 node;官方 Skill 包属第三方文件不随本仓库发布;该脚本每天检查一次
Skill 更新,发现新版本会拒绝发送原请求(返回 -200)。官方脚本做的事等价于 POST
`https://ima.qq.com/<path>` 带三个请求头,无签名无加密,故用 httpx 直接实现。

### 接口文档与实测不一致的三处(以实测为准)

1. 知识库字段是 `kb_id` / `kb_name`,不是 `api.md` 写的 `id` / `name`。用 `kb_id_of()` / `kb_name_of()` 兼容两者。
2. `get_knowledge_list` 的条目**统一只有 `media_id`**,文件夹靠 `media_type == 99` 和 `media_id` 的
   `folder_` 前缀区分,**没有独立的 `folder_id` 字段**(`folder_id` 只出现在 `current_path` 里)。
   文件夹的 `media_id`(形如 `folder_123`)才是可回传的 `folder_id`。
3. 导入 ima 后**根层只有一个与知识库同名的包裹文件夹**,P1~P8 在它下面一层;本地副本里 P1~P8 直接在根层。
   `_top_folder()` 会自动穿透,但仅在该层恰好只有一个文件夹时才穿,避免误跳进兄弟目录。

### 安全约束

- 只实现读接口白名单(`search_knowledge_base`、`get_knowledge_base`、`get_knowledge_list`、
  `search_knowledge`、`get_media_info`),写接口直接拒绝(手册禁止修改知识库)。
- `base_url` 固定不从环境变量读,避免凭证被指向其他主机。
- 凭证只经请求头发往 ima.qq.com,不写文件、不进日志。`_redact()` 对异常文本脱敏,`__repr__` 不暴露凭证。
- `ImaCredentials.from_env()` 读 `IMA_OPENAPI_CLIENTID` / `IMA_OPENAPI_APIKEY`,也可由界面传入。

### 真实验证结果(2026-10-21)

目录结构与 `data/model_aliases.yaml` 的 `dir` 完全对得上,型号资料文件名是 `产品事实.md`
(不是手册提到的 `article.md`)。与本地副本逐型号比对,事实/图片/价格三项全部一致:

| 型号 | 事实 | 图片 | 价格 |
|---|---|---|---|
| D 14 2024 | 65 | 7 | 4 |
| MateBook 14(鸿蒙版) | 49 | 19 | 15 |
| Fold 非凡大师 | 57 | 5 | 10 |
| MateBook Pro | 46 | 8 | 11 |
| MateBook Pro S | 54 | 6 | 17 |

尺寸三项正确标为 `pending_review`。图片临时链接可取。

### 已知限制

- **取原文有每日配额**:用尽时返回 `code=220021`「资料获取次数已达上限」,目录浏览不受限。
  已包装成 `ImaQuotaError` 并给出可操作提示,界面不应显示成"找不到资料"。
  剩余 5 个型号(14 酷睿 Ultra、D 16、D 16 SE、GT 14、X Pro)因配额用尽未逐一比对,解析逻辑共用,风险较低。
- 搜索为空**必须**回退到 `get_knowledge_list` 逐级浏览(手册明确要求,有测试覆盖)。
- ima 下 `ImageRef.file_path` 存的是 media_id 而非本地路径,展示与导出都要走 `image_url()` 取临时链接。
- 图片要同时满足"索引登记"和"库里真实存在"两个条件,型号不一致不输出。
  官网图走 `images/图片索引.csv`,商城款式图走 `商城款式图片/图片索引.csv`(7 列、无产品型号列,
  靠"仅限本型号目录"保证型号),两份索引都要读。
- 价格空金额保持 `None`,绝不转 0。

### 怎么验证

```bash
cd hwpc-agent
export PYTHONIOENCODING=utf-8 PYTHONUTF8=1
export LOCAL_KB_ROOT="<本地知识库副本路径>"
python -m pytest tests -q   # 90 passed
```

真实连接自测(不含凭证,凭证走环境变量):

```bash
python -c "from agent.retriever.ima import ImaRetriever; print(ImaRetriever().check_connection())"
```

### 还没做

- 界面填 Key:`ImaRetriever(creds=...)` 与 `ImaCredentials` 已支持传入,界面侧未实现。
- `app.py` 仍写死 `LocalRetriever`,需按 `RETRIEVER` 环境变量在 local / ima 之间切换。
- 魔搭创空间部署:入口文件位置、环境变量配置方式待验证。

## [2026-10-23] A:合规误杀修复 + 魔搭部署闭环

完成了什么:修掉三处会让正常软文被"流程已阻断"的缺陷,并把魔搭创空间的发布流程跑通。

改动文件:`agent/compliance.py`、`agent/pipeline.py`、`data/banned_terms.yaml`。

三处缺陷:
- 价格正则把"元"设为可选,导致型号 14、重量 1.4、电池 56Wh、分辨率 1920x1200 全部被当成"无依据的价格"。
  现在只识别带 `¥/￥` 前缀或 `元/块` 后缀的数字。
- `banned_terms.yaml` 里 `第一`、`唯一`、`任何.*都`、`保证.*|一定.*`、`永不.*|终身.*` 等正则过宽,
  "不是唯一变量""第一款软件""一定要带清单"都会被拦。已收窄为真实排名/承诺表达
  (第一名、全网第一、唯一的正确选择、保证续航、终身免费等),并用 15 条正反用例验证。
- 合规阻断时 `Report.block_reason` 为空,界面只显示"🚫 流程已阻断:",使用者无从下手。
  现在 `pipeline.run` 会把命中的合规项写进 reason。

怎么验证:
- 合规正反用例 15 条全部符合预期(误报 0,真违规仍拦截)。
- `py -m pytest tests -q`(排除需要 openai/httpx/gradio 的三组)64 passed。
- 真实 DeepSeek + 本地知识库跑通全流程:状态 ok,生成 800+ 字、4-5 张图、11-14 条事实引用,
  事实/图片/合规核验全部通过。

魔搭部署必读(踩坑记录):
- **git push 到创空间后不会自动重建**,必须再调
  `POST https://www.modelscope.cn/openapi/v1/studios/<user>/<name>/deploy`(Bearer token),
  然后轮询 `GET /api/v1/studio/<user>/<name>` 的 `Status`(`CreatingBuildingImage` → `Creating` → `Running`),
  单次构建约 10-20 分钟。
- 创空间实际 SDK 为 Gradio 6.29.1,`buttons=["copy"]`、`theme` 放 `launch()` 均兼容。
- 云端没有本地知识库副本,访客需在界面「连接配置」里填 ima 凭证与大模型配置;只连 ima 不配模型会阻断,
  提示为"模型生成失败:缺少模型名"。
