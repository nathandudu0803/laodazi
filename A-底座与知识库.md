# Claude A:底座与知识库接入(关键路径)

先读:`00-总览与协作规则.md`、`知识库速查.md`。

## 角色与目标

你负责整个项目的地基:仓库骨架、数据契约、大模型封装、知识库检索、事实点提取和流程编排。B、C、D 都依赖你的第 0 步,所以先把第 0 步做完并通知。

## 你可以改的文件

- `hwpc-agent/agent/contracts.py`、`pipeline.py`、`llm.py`、`facts.py`
- `hwpc-agent/agent/retriever/base.py`、`ima.py`、`local.py`
- `hwpc-agent/data/model_aliases.yaml`
- `hwpc-agent/README.md`、`.env.example`、`requirements.txt`、`.gitignore` 的初始版本(其余人之后只在文件末尾追加自己的段落)
- `hwpc-agent/docs/handoff.md` 的创建与追加

其余文件只读。

## 依赖

- 无上游。B、C、D 都依赖你。

## 分步任务

### 第 0 步:骨架与契约(先做,做完立刻通知)

1. 在 `F:\华为浙克松\hwpc-agent\` 建立 `00-总览与协作规则.md` 第 5 节的目录结构,每个文件先放可导入的空壳和 docstring。
2. 写 `contracts.py`,用 dataclass 定义 `TaskInput`、`SceneProfile`、`PlatformPlan`、`Fact`、`ImageRef`、`Draft`、`Report`,字段见总览第 6 节。给每个字段写类型和一句注释。
3. 写 `retriever/base.py`:`Retriever` 抽象类,至少包含:
   - `find_models(query) -> list[str]`:把用户输入解析为规范型号
   - `get_facts(model) -> list[Fact]`
   - `get_selling_points(model) -> dict`:可用结论、表达边界、发布前必须追问
   - `get_images(model) -> list[ImageRef]`
   - `get_price_records(model) -> list[dict]`
4. 写 `llm.py`:OpenAI 兼容客户端,读 `LLM_BASE_URL`、`LLM_API_KEY`、`LLM_MODEL`。提供 `chat(messages, **kw)` 和 JSON 结构化输出的辅助函数,带重试和超时。日志里不得打印 Key。
5. 写 `.env.example`(只放变量名和占位符)、`.gitignore`(含 `.env`、`__pycache__`、`*.key`)、`requirements.txt`(版本固定)。
6. 创建 `docs/handoff.md`,第一条写"第 0 步完成",列出各契约字段和各接口签名。
7. 通知用户:第 0 步完成,B、C 可以开工。

### 第 1 步:LocalRetriever

1. 读取本地知识库,路径用环境变量 `LOCAL_KB_ROOT`,默认值指向 `知识库速查.md` 第 1 节的目录。
2. 解析 `产品事实.md`:二级标题分节,"标签 / 空行 / 值"交替,保留脚注和多配置的原文,过滤文末网页噪音。
3. 解析 `卖点与限制.md`:按固定骨架切出可用结论、支撑事实、表达边界、发布前必须追问。
4. 解析 `图片索引.csv`(utf-8-sig):兼容 MateBook 14 "商城款式图片" 那套不同表头。图片路径要能指向真实文件,生成 `ImageRef`。选图依据用"官网图片说明"和文件名中的画面主题,不用"建议用途"列。
5. 解析 `官方价格快照.csv`:原样保留价格类型、条件摘要、核验时间、官方 URL,空金额保持为空,不转 0。
6. 每个 `Fact` 都带来源标题和来源路径。多配置值保持原样并保留限定条件。
7. 尺寸与重量:D 16 的标签与数值错位。解析后用 `卖点与限制.md` 交叉校验;对不上的字段打上"待复核"标记,不要自行猜测。

### 第 2 步:型号别名与易混淆对

1. 写 `data/model_aliases.yaml`:10 个型号的规范名、目录名、官方全称、常见叫法(如 "D14""D 16 SE""GT14""非凡大师")。
2. 登记易混淆对(见 `知识库速查.md` 第 4 节),每对写出关键区分字段。
3. `find_models` 返回候选时,命中易混淆对且信息不足,返回多个候选并标记需要追问,不要自行二选一。

### 第 3 步:facts.py 与 pipeline.py

1. `facts.py`:根据场景从全量事实里选出相关事实点,每条仍带来源。不要让大模型补事实。
2. `pipeline.py`:串起 9 步:场景解析(B)、平台策略(B)、检索(你)、事实点提取(你)、图文编排(B)、软文生成(B)、事实与图片核验(C)、合规检查(C)、导出(C)。
3. 信息不足时返回追问列表,不进入生成。
4. 资料冲突、型号无法确定、核验失败时把 `Report` 的阻断标志置为真,并带原因。
5. 用桩函数先跑通,B、C 的模块完成后替换成真实调用。

### 第 4 步:ImaRetriever(等用户配好凭证)

1. 凭证只读环境变量 `IMA_OPENAPI_CLIENTID`、`IMA_OPENAPI_APIKEY`。不要向用户索要具体值,不要写入任何文件或日志。
2. 通过 `node ima-skill/ima_api.cjs` 调用,脚本由用户安装并放在项目外或 `ima-skill/`(该目录不要提交到仓库,除非主办方许可)。
3. 流程:`search_knowledge_base` 按名称"任德耀新建华为PC知识库"查找并取 `kb_id` → `search_knowledge` 搜型号 → `get_media_info` 取原文或链接。
4. 手册明确:**搜索为空不等于无权限**。为空时必须用 `get_knowledge_list` 浏览目录,进入 P1-产品参数库,再读取具体型号的 `article.md`。
5. `kb_id` 仅在程序内部使用,不展示、不进日志。
6. 实现后与 LocalRetriever 对同一型号做结果比对,差异写进 handoff.md。

## 验收标准

- `LocalRetriever` 对 10 个型号都能返回 `Fact` 和 `ImageRef`,每条带来源。
- 易混淆型号输入(如只写 "D 系列")会返回多候选并要求追问。
- D 16 尺寸在复核前被标记为待复核。
- 价格记录原样返回,空金额不是 0。
- 更换 `Retriever` 实现,上层代码不需要改。
- 仓库里搜不到任何密钥。

## 禁止事项

- 禁止让大模型补充知识库没有的事实。
- 禁止改动 B、C、D 名下的文件。
- 禁止修改本地知识库副本里的任何文件。
- 禁止合并不同配置的参数值。
- 禁止把凭证写入任何文件、日志、测试夹具。

## 汇报

每完成一步,在 `docs/handoff.md` 追加:完成内容、改动文件、验证方法、下游需要注意的点。

## 启动口令

> 你是 Claude A。请先读 `F:\华为浙克松\分工\00-总览与协作规则.md`、`知识库速查.md`、`A-底座与知识库.md`,然后从"第 0 步"开始执行。完成第 0 步后停下来向我汇报。
