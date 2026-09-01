# Module Design Notes — Issuer Intelligence MVP

> 逐模块设计讨论的记录。基准架构见 [TARGET_ARCHITECTURE.md](TARGET_ARCHITECTURE.md)。
> 模块地图与编号(M1–M13)以及全局三规则在此固定,后续每定一个模块追加一节。

## 全局设计规则(适用所有模块)

- **规则 A — Fail loud at the boundary**:外部依赖缺失(key/网络/数据)或校验失败 = 该步 failed、时间线可见、run 停止。不做 mock、不做静默降级。现有 `DirectLlmAgent._mock_output` 模式不复制到任何新代码。
- **规则 B — 用 schema 消灭解析规则**:LLM 输出一律 structured outputs / tool-call 强制形状,不写 "strip fences → json.loads → 失败当 markdown" 类补丁链。引用靠生成 schema 中必填 `citations[]` 字段结构性保证,不靠事后正则。
- **规则 C — 正交工具替代路由规则**:不写问题分类器/router。工具面正交(每个工具一种证据类型),meta-agent 的工具选择即路由。
- 澄清:规则 B/C 反对的是 **LLM 调用路径上的规则补丁**。确定性层内部的映射表、校验逻辑(如 XBRL concept 映射)是正交模块的实现细节,不在此限。

> 注:模块讨论已全部完成(M1–M13,M12 取消并入 M10;M7/M9 合并)。累积修订已于 2026-07-23 回写至 TARGET_ARCHITECTURE.md **v3**(修订清单见该文档附录 B)。本文档保留为逐模块设计的详细依据。

---

## M1 — Company Identity(2026-07-23 定稿)

### 职责(单一)

ticker → company(name/CIK/exchange/sector/industry)的**唯一事实源**。下游(M2 filing 发现、UI issuer 入口)只认 `companies` 表,永远不直接碰 EdgarTools。

### 核心设计:写路径与读路径是两个操作,不是一个操作的两种情况

反模式(fallback 链,禁止):`lookup(ticker)` → 查表 → 没有就现场调 EdgarTools → 还没有就返回 None。

```
写路径(有副作用,只在两处发生):
  ① seed 脚本:10 个 ticker 写入;8 只股票带手工核对的 CIK;
     TLT/HYG 写入但 is_investigable=false
  ② IssuerResearchWorkflow 第 1 步 resolve_company:
     经 EdgarToolsFilingProvider 验证/补全公司信息并 upsert。
     失败 = 步骤 failed,run 停止(规则 A)

读路径(无副作用,任何时候):
  company_service.get_by_ticker() 只查表。
  查不到 → 明确异常(不是 None,不是现场解析)
  is_investigable=false → 明确异常;UI 据此不渲染 Investigate 按钮
```

- 读路径永不触网、永不隐式写。"查不到"是数据问题,在写路径解决,不在读路径打补丁。
- ETF 处理是**数据属性**(`is_investigable`),不是运行时 if 分支。判断发生在 seed 时一次,运行时只读旗标。未来支持 ETF(N-CSR),改数据和 M2,不改散落的条件逻辑。

### 与 LLM 的关系

零。公司识别是查表,不让模型猜 CIK。meta-agent 的 `resolve_company` 工具是读路径的直通封装,返回结构化行或结构化错误。

### 已定决策(默认采纳建议方案,可推翻)

1. **CIK 来源**:seed 硬编码 8 个手工核对的 CIK;`resolve_company` 步只做验证不做发现(发现失败的爆炸半径更小)。
2. **sector 口径**:companies 表存 EDGAR 口径(SIC/industry),组合分析继续用 positions 手工口径,**两者不合并**——组合视角与发行人视角是两个域。

---

## M2 — Filing Ingestion(方向已定,parse 细节待实测,2026-07-23)

### 职责(单一)

SEC 世界 → 库内可引用证据:`filings` / `filing_documents` / `filing_sections` / `financial_facts` 四表的唯一生产者。**只搬运和映射,不计算**(加总/比率/期次对齐归 M3)。

### 五个核心设计

1. **内部两条正交子流水线,互不依赖、独立成败**:
   - M2a 文本流:discover_filings → filing_documents → parse_sections(按 SEC Item)——供 M5 RAG
   - M2b 事实流:XBRL facts → map_concepts → financial_facts——供 M3
2. **Provider 边界用 DTO 隔离**:`FilingProvider` 返回自定义 dataclass(FilingMeta/FilingDoc/SectionDTO/FactDTO),edgartools 对象不上浮出 provider。换 provider 不改 ingestion。
3. **幂等 = 每 filing 一个 DB 事务**:元数据+文本+sections 全进或全不进。消灭"半吊子摄取被幂等跳过"这个错误类别,不用状态机补丁。幂等判断简化为 accession 存在即跳过。
4. **Item 解析失败不做盲切 fallback**(规则 A):解析不出 sections → 该步 failed。盲切退路存在会让坏解析永远不被发现。
5. **concept 映射是版本化静态映射表**(~15 个 us-gaap → 10 指标),严格 1:1。映射不到的 concept 照样入库(`normalized_metric=NULL`)——raw 永远保真,归一是增量注释,不是 fallback。

### 明确不做

chunk/embedding(M5)、任何计算(M3)、10-K/10-Q 之外表单、修正案(只记 is_amendment,取最新原始版)。

### ⚠ 用户标记(定稿前必须处理)

- **parse 方式需要反复实测才能定**——用户此前做过类似项目,section 解析质量不能靠假设,实现期先做 parse 质量评估(对 8 家公司的真实 10-K/10-Q 跑解析、人工抽查),再定最终 parse 方案。
- **可能有 external 项目/skill 可复用**——实现前先盘点用户已有的相关项目/skill,避免重写已验证过的 parse 逻辑。EdgarTools 只是当前候选,不是定论。

### 已定(2026-07-24,实测后)

1. 事实流数据源:**company-facts API**(一次拿全历史,每条 fact 带 accession)。实测 8 家共 61,642 条,NVDA FY2025 营收 $130.50B 与真实披露一致。
2. Q4 单季推导:**归 M3**。实测确认 NVDA 每财年只有 3 条 ~90d 季度 fact(Q1/Q2/Q3),Q4 必须用 `年报 − (Q1+Q2+Q3)` 推导,M2 只存 as-reported。
3. 映射指标集:在原 11 个基础上增加 **cost_of_revenue** 与 **pretax_income** 两个独立指标(mapping v2)。
   - `cost_of_revenue` 让 M3 能为不披露 GrossProfit 的公司(AMZN/GOOGL/LLY/XOM/JPM)**计算**毛利;计算归 M3,M2 仍严格 1 fact→1 metric。
   - `pretax_income` **刻意不并入 operating_income**——两者经济含义不同,合并会让覆盖率好看但数值是另一个东西。JPM/XOM/LLY 没有 OperatingIncomeLoss 就是真的没有,保持可见。已用测试锁死。
4. **schema 修正(改动 P0)**:`financial_facts` 增加 `source_accession` 并纳入 UNIQUE 键。原键会把重述折叠——实测会丢 NVDA 45% 的 fact(7635→4182),M3 的"重述择新"将无对象可选。
5. **fiscal_year/fiscal_quarter 标签不可信**:同一期间 `2025-01-27→2025-04-27` 在两份 filing 里分别被标成 FY2027 与 FY2026(值相同)。**period_start/period_end 才是权威键**,M3 的 period_ladder 不得用 FY 标签做 key。
6. 存在 half(~180d)/9mo(~270d)累计口径 fact(共 189 条),period_ladder 必须按时长过滤,不能误当季度。

### ★ M2a parse 方案定稿(2026-07-24,基于 16 份真实 filing 实测)

**决定:统一采用 edgartools 的 typed filing object(`filing.obj()` + Item 访问),10-K 与 10-Q 都走这条。**

证据(完整表见 `docs/spikes/M2_PARSE_EVAL.md`):
- **obj / 10-K**:8 家全部拿到 Item 1 / 1A / 7 / 7A / 8,篇幅正常(Item 1A 35k–114k 字符)
- **obj / 10-Q**:8 家全部拿到 Part I Item 1(财报)与 Part I Item 2(MD&A),7/8 拿到 Part II Item 1A(XOM 本期确实未列风险因素)
- **regex(原始文本按 `Item N` 切)被否决**:MSFT 10-K 被切成 144 段、每段仅 4–7k(obj 为 48k–128k),JPM 10-K Item 1 = 0k,XOM 10-K Item 7/8 为空;且结构上**无法区分 10-Q 的 Part I Item 1 与 Part II Item 1**(前者财报、后者法律诉讼)

⚠ **过程教训**:第一版 spike 曾误判「obj 在 10-Q 上完全失败」,根因是比对键用了裸 `Item 2`,而 TenQ 的 items 是 `Part I, Item 2`。修正归一化后结论完全反转。**负面结论必须先排除自己的测量 bug**。

配套规则(不变):Item 解析不出 → 该步 failed,**不退回固定窗口盲切**(规则 A)。

---

## M3 — Analysis Primitives & Computation Ledger(2026-07-23 定稿,经重定义;**序列部分于 2026-08-27 由 M18 取代**——`period_ladder`、`get_fact_series`、四个 `compute_*` 已删,下文保留为历史)

> 重定义:M3 不是"预先定死的指标清单",而是**分析原语 + 计算台账**架构。
> 具体算哪些指标是 recipe 内容(随时可改,不在架构讨论范围);架构回答的是:
> **agent 怎样在不亲自算数的前提下自由分析**——算术归工具,编排归 agent。

### 三层结构

```
消费者层(同一套原语,四种驱动)
  ① Workflow 标准 recipe:固定脚本序列(内容后议)
  ② 分析 agent:自由组合原语,预算硬顶
  ③ Meta-agent 交互问答
  ④ 外部宿主经 MCP(★ 2026-08-03 封存,见 M10——今天的消费者只有 ①②③)
计算代数层(封闭原语集,每次调用自动落台账)
  combine_series(a, b, op ∈ {add, sub, divide})
  compute_change(series, mode ∈ {yoy, qoq, pct, abs})
  compute_stat(series, op ∈ {cagr, avg, min, max, std})
  compute_window_return(ticker, window, benchmark?)
数据原语层(只读,带血统)
  list_available_data(company)      ← agent 的"地图"
  get_fact_series(company, concept|metric, period_type)
  get_price_series(ticker, range)
  (period_ladder 期次对齐在这层内部,对上透明:Q4 推导、重述择新
   只写一处,agent 拿到的序列已对齐,没有"自己对期次"的机会)
```

正交性来源:计算代数**封闭**——四原语两两不重叠,表达力靠组合(利润率=divide;FCF=sub;增长=change;CAGR=stat;事件反应=window_return),不靠加工具。

### Computation Ledger(核心机制)

`derived_financial_metrics` 定性为 **append-only 计算台账**:

- 每次计算原语调用 → 自动落行(输入 fact_ids/spec、操作、参数、结果、原语版本)→ 返回 `calc_id`
- **agent 引用数字只能引 calc_id / fact_id**——想写一个数,必须先有留痕的工具调用。转抄/心算在审计面无处藏身
- 台账由工具层自动写,与 agent 是否记得无关(同构 sm-master"连接器自动落证据")
- UI Financials tab = recipe 跑出的台账行;agent 自由分析同样进台账、同样可穿透

### 拓扑修正(回写 TARGET_ARCHITECTURE.md,见文首注②)

分析 subagent 允许 tool-calling,但仅限本注册表、预算硬顶、非对话。不变量:所有 agent 自由度流经同一 ToolRegistry。

### 禁区

- **没有 SQL 工具、没有自由公式/eval 工具**。自由封在封闭代数的组合空间内;新分析能力 = 加正交原语(架构评审动作),不是开 escape hatch
- 数据原语返回序列有硬上限(工具内强制)
- 缺数语义:None + quality_flag,永不插值、不拿上期顶替、无行业特判分支

### 已定决策

1. 组合方式:MVP 用 **stateless series spec**(每次调用自带完整数据规格);calc_id 链式引用(血统 DAG)作后续演进。
2. 封闭代数边界:四原语集合定稿;增删原语是架构评审动作。

### 待定(实现期)

- ~~分析 agent 大脑位置:应用内 bounded loop vs 外部宿主(OpenClaw/Claude Code)经 MCP 驱动~~ ★ 已定(2026-08-03):**应用内 bounded loop**(已实现为 `agents/research_session.py`);外部宿主出范围,见 M10 ★2026-08-03 拍板。"强制与追踪沉在 transport 之下"这半句仍然成立,也是 in-memory 迁移零强制改动的原因。

---

## M4 — Market Data Ingestion(2026-07-23 定稿)

### 职责(单一)

外部行情 → `market_prices` 的唯一生产者。查询侧 `market_data_service` 一行不改——M3 的 `get_price_series` 原语与现有 `ExposureWorkflow` 读同一张表。

### 结构

```
YFinanceMarketDataProvider   → PriceBar DTO(yfinance 对象不上浮)
MarketDataIngestionService   → (ticker, price_date) upsert,天然幂等
触发:workflow refresh_market_data 步 / UI 按钮 / delegation 工具
收益计算用 adj_close;MVP 无定时调度
```

### 规则 A:显式参数替代隐式降级

- refresh 失败 = 该步 failed,run 停止。**不做**"拉不到就静默用库内旧数据"(金融场景最危险的 fallback:拿旧价格算风险且不告知)
- 明知外部源不可用仍想跑 → 创建 run 时显式带 `skip_market_refresh=true`(schema 可见、审计留痕)。同一需求,fallback 形态 vs 架构形态的分界线

### ★ 已定决策:种子退役,全库真实化(方案 A)

- seed 脚本不再生成合成价格,改为调 M4 ingestion 拉全部 ticker(10 持仓 + SPY + factor_config 因子 ETF)的真实历史;`factor_prices` 一并真实化,source='yfinance' 统一
- 理由:同一 ticker 序列里合成段+真实段拼接,算出的收益/波动率是**看不出来的垃圾**,源头污染审计面救不了;按 source 隔离(方案 B)则让每个读路径永久背负过滤参数复杂度税
- 现有 `ExposureWorkflow` 零改动(只管读表);demo 初始化从此依赖网络,没网 loud fail,不装能跑

### 明确不做

实时/盘中行情、公司行动明细(直接吃 yfinance 复权)、多 provider 路由、定时调度(schedules 表保留,MVP 不接)。

---

## M5 — Filing Index & Retrieval(2026-07-23 定稿)

### 职责(单一)

`filing_sections` → `filing_chunks`(+embedding)的唯一生产者 + 向量检索的唯一提供者。吃 M2a 产出,喂 agent 工具面。**纯确定性模块,零 LLM 生成调用**。

### 四个核心设计

1. **没有 FilingQAService**:QA = meta-agent 拿检索工具自己干。单独 QA 服务 = 第二个 LLM 调用点、第二套 prompt、第二条审计路径——冗余消灭。
2. **写读分离,SectionChunker 是可替换正交组件**:
   - 写路径(index_filings 步):sections → SectionChunker → embed → chunks;幂等键 (filing_id, embedding_model);每 filing 单事务
   - 读路径:`search_filing_passages` / `get_filing_section` 只读工具
   - chunker 单独成组件的原因:M2 parse 要反复实测,chunk 质量依赖 section 质量——隔离后 parse 迭代时 embedding/索引/检索零改动。chunk 参数与 M2 parse 实测捆绑为同一轮评估
3. **两个检索工具正交而非冗余**:`search_filing_passages` 找位置(语义),`get_filing_section` 读全文(按 Item 直读)。后者是对"RAG 只看碎片"偏差的架构性解法——agent 定位后可拉整节确认上下文。
4. **引用锚点在 chunk 行内冗余存全**(chunk_id/accession/form_type/filing_date/item_code/char_span/source_url),检索零 join,引用完整性由返回结构保证。

### 规则 A

- 无 embedding key → index_filings 步 failed;不存在"退化为关键词搜索"暗道
- 未索引 → 工具返回结构化错误"未索引"(修正:出路是触发轻量 readiness 任务,**不是**跑完整 research run——见 M8 重构),不用空列表冒充"没搜到"——**"没数据"与"搜不到"是两种事实**,混淆是最隐蔽的 fallback

### 明确不做

rerank、HNSW(8 家×2 filing 精确检索足够)、hybrid BM25(检索质量实测后再议)、跨公司联合检索。

### 已定决策

1. Embedding 模型:**OpenAI text-embedding-3-small(1536 维)**,DDL 已按此;换模型 = 按幂等键重索引。
2. 检索范围:**默认覆盖该公司全部已索引 filing**(结果带 form_type 标签),filters 可收窄;收窄权在 agent 的参数,不拆成两个工具。

---

## M6 — External Research(2026-07-23 定稿)

> 用户备注:此模块设计可随时更换(provider/预算/策略)而不影响其他部分——正交性使然,按当前方案定稿。

### 职责(单一)

Tavily → `research_sources` 的唯一生产者。补全证据宇宙第四类型:**fact / chunk / calc / source** 全部落库带 id。

### 四个核心设计

1. **采集与消费分离**:`search_external_research(company, query, reason)` 为 delegation 类工具(消耗预算、reason 必填),落库返回 source_ids;`list_research_sources` 只读。agent 引用只能引 source_id——模型记忆里的市场信息在引用系统里**没有座位**,不靠 prompt 禁止。
2. **query 是 agent 的判断,不写 query 模板规则**:workflow recipe 无确定性搜索步;搜什么/搜几轮/哪些来源可信全是分析 agent 的判断,经工具行使、全部留痕。由此确立工作流内分工线:**判断类步骤归 agent+工具强制,机械类步骤(摄取/索引)归确定性 recipe**。
3. **relevance score 是数据不是过滤器**:返回全部入库,不写阈值筛选。阈值会静默丢证据,审计面看不见"被丢掉的东西"。
4. **web 内容是不可信输入**:source 内容进 agent 上下文永远作为带引号的数据字段,不拼指令区;只存 Tavily snippet/extracted content,不二次抓取(最小化注入表面);审计轨迹是第二道防线。

### 规则 A

无 TAVILY_KEY → 工具结构化报错,agent 如实告知;跳过外部研究 = 显式 `skip_external_research=true`。

### 已定决策

预算:**5 次/run**,超顶工具拒绝;数值在配置不在代码。

### 明确不做

多 provider 路由、二次抓取全文、新闻流、来源可信度评分模型。

---

## M7+M9 — Evidence Trail & Brief Agent(2026-07-23 定稿,合并)

### 核心重定义:EvidencePack → Evidence Trail(审计产物,非输入契约)

- 旧形态(确定性代码事先组装证据包喂 agent)**取消**——组装逻辑本质是 rule-based 的"该带哪些证据"判断,固化在代码里
- 新形态:**agent 会话实际触达的证据集合**,从 agent_steps.evidence_refs 自动导出,run 收尾时物化进 `evidence_packs` 表
- 回答的问题从"我们决定给 agent 看什么"变为**"agent 生成 Brief 时实际看了什么"**——机器记录的真相,不是人手拼的清单

### Brief Agent = 分析 subagent 会话的收尾,不是独立实体

每个 research run 只有一个 agent 会话:探索者就是写作者,无交接物。

```
workflow 确定性步(摄取→索引→行情→recipe 基线)全绿后:
分析 agent 会话(bounded,预算硬顶):
  自由探索:get_fact_series / compute_* / search_filing_passages /
           get_filing_section / search_external_research / get_issuer_snapshot / think
  收尾:submit_brief(...)   ← 会话唯一出口
workflow 收尾步:物化 Evidence Trail,run completed
```

组合关联不特殊:`get_issuer_snapshot` 返回的敞口/权重/告警是普通证据,带 id 可引用。

### submit_brief:门在工具里,不在事后

- 六块结构(financial_summary / key_changes / management_explanation / market_context / portfolio_implications / open_questions)+ `confidence_flags`(★ 2026-08-03 更正:此处原写 `confidence_notes`,schema 与 `issuer_briefs` 列名都是 `confidence_flags`。schema 收口前,照文档写的键会被 `**blocks` 静默丢弃;收口后是显式拒绝),tool-call 形态强制
- 每块 `citations[]` 必填(唯一豁免:open_questions——问题不是事实断言)
- **提交时同步校验**:每个 citation id 必须 ∈ 本会话 Evidence Trail 且 ∈ 数据库;不过 → 结构化错误(具体到哪个 id),agent 预算内修正重提;耗尽 → run failed
- 这不是 fallback:错误反馈是会话内结构化对话,终局二值(合格 Brief 或可见失败),无"降级产物"第三态。相比 sm-master 的事后校验,门前移到提交时——hallucinated citation 在落库前拦死

### 被 schema 消灭的错误类别

| 错误类别 | 消灭方式 |
|---|---|
| 无引用断言 | citations 必填字段,生成不出来 |
| 编造 citation id | 提交门比对 Evidence Trail,落不了库 |
| JSON 形状不对 | tool-call 强制,不存在解析 |
| agent 心算数字 | 数字只能引 calc_id,心算值无 id 可引(M3) |

### 已定决策(默认采纳,可推翻)

1. ~~提交门修正预算:**2 次重提**(初提+2 修正),耗尽 run failed;数值进配置。~~
   ★ V3-A0-4 更正:**从未实现**。`submit_brief_retries` 在 settings 里躺了两个阶段、被 test_p0_schema 断言、被这一行写成已定决策,而**没有任何生产代码读它**。真实的界是`max_turns`(research 30)加会话工具预算;配置项已删除,`tests/test_p0_schema.py` 的结构守卫现在会让下一个这样的死旋钮直接测试失败。
2. open_questions 免引用豁免:**采纳**,其余五块强制。

### 明确不做

Brief 的 LLM 后处理/改写规则、多轮人工审批流、brief 版本 diff。每 run 一份 Brief(UNIQUE research_run_id),重新生成 = 新 run。

---

## 插节 — 用户功能地图与三能力重构(2026-07-23,M8 讨论中的关键修正)

> 背景:M8 初稿把系统讲成了"一条流水线+一个按钮"。从用户视角重新盘功能后,
> 发现两处真实的耦合错误,并确立"pipeline 只是组合之一"的定位。

### 用户功能地图

| # | 功能 | 形态 | 时延 |
|---|---|---|---|
| F1 | 组合监控(现有 ExposureWorkflow) | 按钮/定期 | 分钟 |
| F2 | **即问即答**(日常主体):任意粒度、跨证据类型、跨公司 | 对话 | 秒级 |
| F3 | 深度调查(低频正式动作)→ Brief 产物 | 对话/按钮,后台 | 分钟 |
| F4 | 证据浏览(filing 原文/财务趋势/来源) | 纯 UI,无 agent | 即时 |
| F5 | 数据就绪(通常隐式) | 委托/按钮 | 分钟 |
| F6 | 审计监测(轨迹/引用穿透,横切) | 纯 UI | 即时 |

### 三组正交能力(pipeline 只是组合之一)

```
能力 A:数据就绪(机械,幂等,无判断)= 摄取/索引/行情/recipe 基线,本质是"状态"
能力 B:证据工具面(只读+计算)= ready 后任何时刻可用,不需要任何 run
能力 C:委托研究会话(判断,产 artifact)= 唯一天然 run 形状的东西
组合:F2 = B(未 ready 时 meta-agent 先委托 A);F3 = A + C;F1/F4/F6 无 agent
```

### 修正的两个耦合错误

1. M5 错误提示曾把 B 耦合到 C("未索引→先跑 research run")→ 改为:能力 A 独立可触发。
2. 摄取曾只能经 research run 到达 → 拆出独立 task type `company_readiness`。

### Agent 被 enable 的功能(直接回答)

- **Meta-agent**:随时用 B 做即时分析(含跨公司循环组合,免费);数据不 ready 自主委托 A;受托发起 C 并汇报进度;全程留痕
- **分析 subagent**:C 内用同一套 B + 外部搜索,提交门收尾
- **无 agent 也完整**:F1/F4/F6 及按钮触发的 A/C

---

## M8 — Readiness 任务 + Research 会话(2026-07-23 定稿,经重构)

### 拆成两个任务类型

**`company_readiness`(能力 A,独立 task type)**——全机械、全幂等:

```
1. resolve_company   M1 写路径          幂等:验证+upsert
2. ingest_filings    M2a               幂等:accession(每 filing 单事务)
3. extract_facts     M2b               幂等:(company, concept, period, dim_hash) upsert
4. index_filings     M5                幂等:(filing_id, embedding_model)
5. refresh_market    M4(可显式 skip)  幂等:(ticker, price_date) upsert
6. standard_recipe   M3 消费者①        台账 append,确定性自证
触发:ensure_company_ready delegation 工具 / UI 按钮 / research run 前置
已 ready 时整体秒过。步序 MVP 串行(不为省两分钟引入并发复杂度)。
```

**`issuer_research`(能力 C)**——三段:

```
1. readiness 前置检查(未 ready 则先跑 A,已 ready 秒过)
2. agent 会话(bounded):B 组工具 + search_external_research + think → submit_brief
3. finalize:物化 Evidence Trail,run completed
```

### skip 参数 = 工具面裁剪,不是步内 if

`skip_external_research` 的实现是组装会话时**不给该工具**——能力边界即物理边界,无"调用被拒"噪音、无 prompt 禁令。`skip_market_refresh` 作用于机械步,时间线标 skipped-by-request(与 failed 区分)。

### 并发与状态

- ★ V2-H 更正(原文:「同 company 同时一个活跃 run」)。分两层:**共享 ingest 同 company 单飞**(`ingest_lock_service` advisory lock,加在 `run_readiness` 内,`company_readiness` 与 `issuer_research` 两个调用方共用同一把锁);**research run 每用户每 issuer 一个活跃**(pending/running 冲突 → 409 + 该用户自己的 run_id,UI 跳转)。全局 run 级守卫已被否决:brief 是 RLS 私有产物,拒绝 B 等于 B 永远拿不到,且会把别的租户的 run_id 递给 B
- 状态机沿用 pending → running → completed | failed;会话失败(预算尽/提交门耗尽/LLM 错)= run failed
- schema 补列:`research_runs.agent_session_id`(两层时间线连接点)

### 两层时间线

外层 workflow_events(宏观步序,机械步无内层);判断步(会话)点开 → agent_steps 轨迹。**监测粒度与自由度成正比**。

### 已定决策(默认采纳)

1. 会话总预算:**40 次工具调用/会话**(含 think 与提交门往返;外部搜索 5 次是子预算),进配置。
   ★ V3-B2 起改为双轨:对话是 **15 次/轮**(claim_turn 时归零),40 次退为终身上限;
   research 与 MCP host 只走终身那一轨(V3-R6 才让后者真的如此)。
2. readiness 步序 MVP 串行。

### 明确不做

定时调度、跨 issuer 批量 run、断点续跑(失败即重跑,幂等保证廉价)、步级自动 retry。

---

## M10 — ToolRegistry + Meta-Agent(2026-07-23 定稿)

### ToolRegistry:一份定义,四个消费者,两层强制

- 工具五元组:`{name, json_schema, fn, class: read|delegation|reflection, budget_key}`,注册一次
- 消费者:meta-agent / 分析 subagent(两者经 MCP client 连常驻 exposure-mcp,★2026-08-03 起走 MCP,★MCP_PLAN R4 起走 HTTP)/ workflow recipe(fn 直调);~~MCP 外部宿主~~ 已封存
- **Registry wrapper 自动做三件事**:入参语义校验、预算记账(调用前扣减,超顶结构化拒绝)、轨迹落盘(agent_steps,evidence_refs 从返回值 id 字段自动抽取,不靠工具作者手动报)

### 工具面(face)是声明式配置

```
FACE_META_AGENT = read 全集 + delegation{ensure_company_ready, start_issuer_research,
                  start_exposure_run} + think + respond
FACE_RESEARCH   = read 全集 + search_external_research + think + submit_brief
                  (无 delegation → agent 树深度架构性封顶为 2,防递归不靠约定)
FACE_RECIPE     = 数据+计算原语 fn 直调(无 LLM,无预算,只留台账)
```

skip 参数裁剪作用于 face;"agent 能干什么"的答案在一处配置,审计一眼看全。任何消费者拿 face 同款——同权、同预算、同轨迹,无特权通道(★2026-08-03 起消费者 = 内部两个 agent;这句话对未来任何新消费者依然成立)。

★ MCP_PLAN R1/R4:face 现在还有一个**名字**(`FACE_NAME_META="meta"` / `FACE_NAME_RESEARCH="research"`),因为它同时是挂载点路径、token 的 `face` claim 和构造 server 的名字——三处拼同一个字面量,拼错时报的会是签名不符,查起来指向错的方向。裁剪也换了地方:发起方不再自己裁 face(那意味着两处裁同一个面),而是在 token 里带一张 `deny` 名单,挂载点服务的是**自己的面减去 deny**,只削不加。`skip_external_research` 因此仍是"能力不存在",只是不存在这件事由门口决定。

### Meta-Agent:循环极薄,行为由 face + 门塑造

- 系统 prompt 只写角色与证据纪律的"为什么",不写行为规则清单——prompt 里堆规则 = 承认架构没堵住
- delegation 全部非阻塞(发起即返 run_id,进度靠追问/UI 时间线),meta-agent 永远秒级响应
- MVP 单活跃会话,无跨会话记忆,无自主定时行为

### ★ 已定:respond 也是工具(选项 1)

`respond(text, citations[])` 是会话唯一出口:citations 结构化提交,wrapper 校验每个 id ∈ 本轮 Evidence Trail。**但凡引了,必须是真的**。一套门机制服务 chat 消息与 Brief 两种产物。

★ V3 两处更正:①「1 次重试」**从未实现**(`respond_retries` 同 M9,已删,见上);真实的界是 `max_turns=16` 加工具预算。②「`citations=[]` 合法(非事实性回复)」在 V3-A0-1 之后**只对不含数字的回复成立**:文本里出现实质数字而 citations 为空 → `citations_required`,问候与澄清反问仍可零引用。schema 的 `required` 仍只有 `text` —— 强制在 gate 语义层,因为把 citations 设成 schema 必填会连无数字回复一起堵死。

### ★ 已定:MCP 双轨规则(2026-07-23 定稿;★ 2026-08-03 修订:消费者收敛为内部 agent)

> **Agent 面 = MCP,唯一;代码面 = fn 直调;两面共穿一个 wrapper。**

- 凡 **LLM 生成**的工具调用一律走 MCP——**meta-agent 与分析 subagent 均以 MCP client 连入常驻的 `exposure-mcp`**(streamable HTTP + `stateless=True`,仅 compose 内网 + 宿主 loopback(127.0.0.1,live 套件用);每 chat turn / 每 research run 铸一枚内部 bearer,不再建 client-server 对;会话预算状态在 DB,跨进程一致——这条是常驻化零成本的前提,预算从来不在进程里)
- 凡**确定性代码**的调用(recipe/wrapper)直调 fn——代码无"生成调用"动作,不存在需生成时堵的错误类别,MCP 徒增序列化开销
- 与 sm-master 分裂的本质区别:那是"两条 **agent** 通路、两套强制";这是"一条 agent 通路 + 一条代码通路、**一套强制**"(wrapper 是两轨共同关口)
- 内部走 MCP 买到:工具面的定义与消费解耦(大脑可换是构造不是声称)、门面因日常流量不烂、审计口径唯一
- ★ 2026-08-03 拍板(取代 MCP_BOUNDARY_PLAN v1,该文件已删,内容在 git 历史):**本项目没有外部宿主消费者**——OpenClaw/Claude Code 不是本系统的大脑,此前"与外部宿主同一 server 同一接口"从目标降为架构副产品。HTTP 传输 / OAuth 边界 / staging 验收(旧计划 B1/B2/B5)整体封存,唤醒条件 = 出现真实远程消费或第三方产品目标;**公网部署与 MCP 自此解耦**。stdio 入口定位为 local-dev debug 门(env 显式身份,fail loud,非目标路径)。执行方案见 `docs/MCP_PLAN.md`
- **M12(MCP Facade)作为独立模块取消**,并入本节

### ★ 已定:server 按挂载点构造,身份逐请求(MCP_PLAN R1–R4,2026-08-08 落地)

- **server 是构造出来的,现在按 MOUNT 构造、按 REQUEST 认身份**:`build_mcp_server(registry, face, *, db_factory, face_name)`。in-memory 阶段每 turn 现造一个,身份是构造参数,所以"弄错租户"在物理上不可能;常驻把这条换掉了——一个活过所有 turn 的 server 服务这张桌子的所有租户,user/session/message 就不可能是它的属性。它们成了请求的属性:`apps/mcp/middleware.py` 验 bearer 并绑 contextvar,`call_tool` 里那个 P2 就有的显式绑定站原样留着、只换来源,库看到的仍是同一个 GUC。这是常驻的**真实价格**(构造时绑定 → 中间件必须正确),用"唯一解 token 处 + 负例矩阵 + 双租户并发实测"三层补偿
- **两个 face 两个挂载点,一个进程**:`/mcp/meta`(20 工具)与 `/mcp/research`(14 工具)各自 registry、各自 server 对象、各自门。拒绝"单端点 + token 选 face",那是 `available()` 静默裁剪换个签名回来
- **工具执行搬进 mcp 容器**(N10):tools fn、它们的库连接与 provider 凭证都在门后;**LLM completion 没有搬**,仍在 api / worker 的 loop 里,门后只有工具自己发起的检索 embedding
- **agents 层剩下什么**:一个 face 名和一枚铸出的 token。没有 registry、没有 db_factory、没有 server —— 这句话是"工具面是一个容器"的具体形状
- **传输故障不穿工具错误的衣服**:工具拒绝仍是结构化返回、loop 照常继续;连不上或 401 则在 `async with tool_session(...)` 处抛出,不喂给模型。一个 401 不是"某个工具失败了",是这一轮丢了身份,而它没有第二个身份可试
- **B1 以内部形态唤醒,B2/B5 仍封存**(MCP_PLAN N12):上一节"HTTP 传输 / OAuth 边界整体封存"里的 HTTP 半句自此作废——HTTP 已经在内网落地。但内部 bearer 不是对外边界:两端都是本仓库、同批部署、共享密钥,token 不向任何上游转发,B2 的唤醒条件一字未变

---

## M11 — Observability(2026-07-23 定稿)

### 职责(单一)

把 wrapper 与 `_StepContext` 自动产出的轨迹变成**可查询、可穿透、不可篡改**的审计资产。零采集逻辑(采集在 M10 wrapper 免费发生),只做存储纪律 + 读取面。

### ★ 已定(地基):轨迹存引用不存副本 + 证据四库 append-only 禁改

- `agent_steps` 存:工具名、脱敏入参、一行结果摘要、evidence_refs[]、耗时、token;**不存**完整返回数据体
- 成立前提(写死的纪律,约束 M2/M3 实现):fact/chunk/calc/source 四库**禁 UPDATE/DELETE**,行级稳定、只增不改,重述/修正一律走新行。轨迹回放 = 按 refs 反查,无需快照
- Evidence Trail 物化(M7)随之简化:`evidence_packs.pack` 从完整 JSON 快照简化为 **refs 清单**——一致性由证据库不可变性保证,不靠复制

### 全系统一个引用解析器

`GET /api/evidence/{id}`,id 前缀路由(fact_/chunk_/calc_/src_/alert_),返回统一信封 {type, 本体, provenance, 上游链接}(fact→跳 filing,calc→跳输入 fact)。citation chip / 引用抽屉 / Brief 渲染 / Monitor 共用同一组件同一端点;新增证据类型 = 解析器加分支,chip 自动生效。

### 读取面(四个,全走现有 2s 轮询模式)

| 面 | 数据源 |
|---|---|
| Agent Monitor | agent_steps,双色渲染(tool_call/delegation=机器记录实线;think/respond=agent 自述虚线) |
| Run 时间线 | workflow_events(现有组件零改,判断步可点开进内层轨迹) |
| 引用抽屉 | /api/evidence/{id} |
| 会话列表 | agent_sessions,MVP 只列表+回看 |

### 成本入账

token 已行级落库,session/run 汇总 = 两个 SQL 视图。MVP 呈现只到会话/Brief 页脚(token+调用次数)——**账全、看板薄**,放量后建仪表盘随时有账。

### ★ 已定:入参脱敏 MVP 只脱 API key 类字段;用户消息本身是审计对象,原文入库

### 明确不做

轨迹搜索 UI、成本仪表盘、导出、跨会话对比、SIEM 对接——append-only 纪律保证这些日后全是纯读取功能,不回头改采集。

---

## M13 — UI Workspace(2026-07-23 定稿;M12 已并入 M10 取消)

### 职责(单一)

纯读取+纯触发的薄客户端:渲染结构化数据、发按钮请求、轮询。**零业务逻辑、零数据组装、零判断**。

### 页面结构

```
/                    现有三栏工作台:page.tsx 不重构,只加 [Investigate] 入口
                     (持仓/issuer 行、告警行;is_investigable 控制渲染)
/issuer/[ticker]     新 issuer 工作区(组件化,不延续单文件模式),5 tab:
  Snapshot / Financials(台账行+chip)/ Filings(Item 浏览器)/
  Research(来源列表)/ Brief(六块+chips+页脚成本+时间线入口)
```

### 三个全局组件(M11 读取面的前端化)

- **CitationChip + EvidenceDrawer**:全站唯一引用组件,只认 `/api/evidence/{id}`
- **RunTimeline**:现有时间线组件参数化,两类 run 共用
- **AgentTrace**:双色轨迹,chat 内嵌 + 会话回看共用

### Chat 面板(已定)

- **全局常驻右侧可收起面板**,portfolio/issuer 页共享;跨公司问题无页面归属,全局是唯一不别扭的形态
- **切页面保持同一会话**;★ **"+新会话"按钮显式开新**——session_id 存 localStorage,刷新恢复同一会话;"开新会话"是显式动作(与显式参数哲学一致)
- 实时感 = 轮询 agent_steps 逐条显示进行中的工具调用(AgentTrace 紧凑形态),不是转圈动画

### 规则 A 的 UI 形态

failed 红色+error_message 原文;skipped-by-request 灰色;未就绪给 [Load data] 按钮(触发 readiness)。**UI 从不美化失败**。

### 已定决策

图表:MVP 表格+CSS 迷你图,**不装图表库**——可穿透性(每个数字带 chip)是卖点,不是图表美观度。

### 明确不做

暗色主题打磨、移动端、多用户/权限、WebSocket(全站 2s 轮询)。

---

## M14 — 多用户 Portfolio 工作台与生产化(2026-07-24 定稿;**A–G 全部实现完成 2026-07-28**)

> **状态**:V2-A 身份 → B 组合 → C RLS → D 宇宙 → E 并发/配额/新鲜度 → F 部署 → G 终验,全部落地。
> 199 offline + 32 live 测试全绿(实测复核 2026-07-30);终验数字与实测证据见 [spikes/V2_COVERAGE.md](spikes/V2_COVERAGE.md)。
> 执行计划见 [IMPLEMENTATION_PLAN_V2.md](IMPLEMENTATION_PLAN_V2.md),生产口径见 [PRODUCTION.md](PRODUCTION.md)。
> 实现期推翻的两条原设计已在下文就地标 ★ 改写(重投白名单、配额不进 wrapper);
> 尚未做完的部分集中记在 V2_COVERAGE 的「Known gaps」一节(`owner_id NOT NULL` 收紧、
> Clerk 仍是 dev 实例;删号路径已在 V2-H 关闭,**`check_limits` 的死参数已在 V2-H4 关闭**——
> ★ 这句话曾经是假的,被 V3-R 复核当场戳穿(`db_limits` 由 workflow 装载并传入,函数体
> 一次都没读),现在才成立。V2-H4 把 `risk_limits` 行做成运行时唯一的阈值来源:
> `LimitBook` 没有第三参数,`limits_config` / `db_limits` / cfg() 的 16 个字面量 /
> `configs/risk_limits.yaml` 全部删除,缺行在步骤 3 与价格陈旧同一次抛出。行为变更已实证:
> demo 重跑多出一条 LLY 0.13809 vs 它自己的 0.12(此前被 0.15 默认值盖掉)。见 §M16)。
> **公网链接前仍需人工完成**:DNS 记录 +
> 机器上的 `/etc/caddy/Caddyfile`(样例在 `infra/Caddyfile.example`)。

背景:项目定位是个人展示,但要呈现 production/deployment-ready。讨论结论:展示型项目的"生产就绪"是叙事资产——每个会坏的边界上有一个能指出来的正交模块,而不是堆基础设施。既有优势直接入账:审计轨迹、预算强制、append-only、幂等 upsert、任务 claim 已是 `FOR UPDATE SKIP LOCKED`(task_service.py)。

### 身份(Clerk)

- 注册/登录/OAuth/邮箱验证整类外包 Clerk;后端集成面 = **一个 FastAPI dependency**(JWKS 验 session JWT → user_id 进 contextvar,与 `_session_ctx` 同构),此外全库零 auth 逻辑
- 首登 bootstrap:upsert `users` 行(clerk_user_id 主键),幂等
- ★ 已定:匿名边界 = **读公开、写门禁**——demo 组合/brief 标 `is_public` 作为匿名展示面;chat、research/run 触发、上传要登录

### 租户隔离(先分类数据,再选强制点)

- 数据分类(核心判断):**证据层全局共享、无 owner**(companies/filings/chunks/facts/prices/sources——公共事实,按用户复制 = 浪费 + 不一致);**用户活动层严格隔离**(agent_sessions/messages/steps、research_runs、预算);portfolios policy 写 `owner OR is_public`
- ★ 已定:**calc_ledger 归共享层**(纯公司级确定性派生,零用户数据;invoked_by 元数据小泄露可接受);**issuer_briefs 归用户**——用户组合上线后 portfolio_implications 含用户持仓,brief 是含机密输入的分析产物;demo 的 brief 标 `is_public` 作为公开样例
- ★ 已定:强制点 = **Postgres RLS**。运行时用非 owner 角色 `app_rls`(owner 天然 bypass RLS,这是头号坑);owner 列只在五张主表(users/portfolios/agent_sessions/research_runs/issuer_briefs),子表一律 `EXISTS(父表)` 级联;每事务 `SET LOCAL app.user_id`,单一 choke point `tenant_session()`;**安全归 RLS、业务语义归显式谓词**(标注 semantic),两层不混
- 附带:登录后会话列表按 user 从 DB 拉,替换 localStorage(现状 = 拿到 session id 即可读任意会话,公网不可接受)

### 并发(三平面)

- **Worker 面(唯一必写的新代码)**:lease + requeue(`lease_until` 列,轮询顺带回收)——治 P6 亲历的 stuck-run 类事故;之后 `--scale worker=N` 零代码横扩
  - ★ 已改(V2-E 实测推翻原设计):原文写「配合既有幂等步骤 = 正确的 at-least-once」,**此断言为假**。实测幂等的只有 `company_readiness` 与 `market_data_sync`(全链 `ON CONFLICT DO UPDATE` + 索引短路);`exposure_workflow._persist_outputs` 是裸 `db.add` INSERT,打在 `exposure_metrics`/`daily_reports`/`sector_exposures`/`issuer_exposures`/`factor_attributions` 五个 `UNIQUE(run_id…)` 上,第二次必 IntegrityError(`risk_alerts` 无唯一键则静默重复);`issuer_research_workflow` 模块 docstring 自陈 "deliberately NOT idempotent"。因此**重投集是白名单**:前两类过期回 `pending` 并计 `retry_count`,后两类 task 与 run 双双标 `failed`(`app_rls` 无 DELETE,半截 run 在应用层清不掉,标红让用户显式重跑是唯一诚实解),这同时解开 research 的 `ActiveRunExists` 永久 409 死锁
- Agent 面:每 session 单 in-flight turn(防双击交叉写 trace);research per-company singleflight **下沉到共享 ingest**(★ V2-H 更正,原文「保持全局」)——锁按 company 加在 `run_readiness` 内,两个用户触发同一公司只 ingest 一次,但各自拿到自己的 brief;run 级守卫按用户。等锁期间时间线上**显式记一步 `await_ingest`**:它确实向 B 透露「此刻有人在 ingest 这个 ticker」,但那是公司粒度、不可归因到人、与任何人(含 demo 哨兵)点 readiness 按钮不可区分,而且一个更弱的同类信号已经存在且无法移除——`_is_ready` 读的是共享表,B 从延迟就能判断该公司是否被 ingest 过。用一段无解释的数分钟死白换这点不可归因的信息,不划算
- API/DB 面:async + append-only 天然并发友好,只需池尺寸确认;写进文档,不写代码

### 预算(公网 + 真 key 的硬前提)

- ★ 已改(V2-E 定稿,推翻原「进 wrapper」设计):强制点 = **`usage_daily` 计数表 + 两个扣费点**。理由有二:①wrapper 只看得见工具调用,而 exposure/readiness/research 各有 REST 路由与 agent 委派**两条平行入口**,wrapper 拦不住路由面;②按 `agent_steps` 数当日用量要 join `agent_sessions` 再对无索引的 `created_at` 做范围扫描,而这落在每次工具调用的热路径上
- 形状:`usage_daily(user_id, day, kind, used)`,**共享层不加 RLS**(同 `tasks`)——全局兜底池必须跨租户计数,任何 `user_id = current_setting(...)` 的策略都会让它只数到调用者自己 = fail-open 的假兜底;放共享层后全局池就是同表的保留行 `user_id = '_global'`,一个原语覆盖两级。读路由按 user 过滤须标 `# semantic, not security`
- 唯一原语 `usage_service.charge(db, user_id, kind, limit)`,形状照抄 `agent_session_service.reserve` 的条件 upsert(`ON CONFLICT … DO UPDATE … WHERE used < :limit RETURNING used`,0 行 → 抛 `QuotaExceeded`)。`user_id` 为 None → 抛错,不静默放行
- 扣费点(V2-E 两个,★ V2-H 增至五个):`task_service.create_task`(按 task type 映射,**映射表无默认值** → 将来新增 task type 忘配额 = KeyError fail loud,这一个点同时盖住 REST 与 agent 委派两条面)、`POST /agent/sessions/{id}/messages`(`chat_turn`;**chat_turn 本身**不可改扣在 session 创建上——一个 session 能发无限条消息)、`portfolio_service.create_portfolio`(`portfolio_create`,一处同时盖住新建与克隆 demo)、`POST /api/portfolios/{id}/upload`(`position_upload`)、`POST /api/agent/sessions`(`agent_session`,扣在路由层)。先扣 user 池再扣全局池、同一事务,任一超限即回滚 → **不需要任何退款/补偿逻辑**
  - ★ V2-H 例外,必须写明否则下一个读者会以为上一句仍然全称成立:`chat_turn` 与 `position_upload` 走**先提交的门事务**,不与调用方共事务。判据是**花销发生在哪里**——其余三类的贵活在 worker 上,请求内失败回滚扣费是对的;这两类的钱(LLM / 至多 ~400 次 yfinance)在请求内就花掉了,共事务等于每次被拒都退款,把 fail-loud 校验变成免费重试循环。`usage_service` 模块 docstring 必须同步,否则它自己就是那句谎
- 可见面 `GET /api/me/usage` **直查表,禁止建视图**——V2-E0 刚修掉的 `session_cost` 越权正是视图默认绕过 RLS 造成的,再造一个等于把洞重开
- wrapper 内既有的 session 预算(工具调用数 / external_search 数)保持不变,与日配额是两个正交维度;`cost views` 仅供 owner 侧核账,不作为配额数据源

### 部署呈现

- EC2 + Caddy(已有):子域反代 web;**API 走同源 /api 反代**——顺带消灭 `NEXT_PUBLIC_API_URL` build 期烧死 localhost:8103 的问题(docker-compose.yml)与 CORS
- `docs/PRODUCTION.md`:身份/租户/并发/预算/审计五节,每节写「强制点在哪、消灭了哪类错误」

### 功能扩展定稿(2026-07-24 晚,与上述生产化合并为一条执行线)

- **用户组合**:创建 / CSV 上传(`ticker,quantity[,cost_basis]`,≤200 行,整单原子拒绝)/ 一键克隆 demo;重传 = 新 as_of_date 快照(append-only);新组合默认 USD/SPY + demo 限额模板
- **U1 → U2 连做**:U1 限已覆盖 ticker;U2 引入 `security_master` 宇宙表——**来源修正**:Yahoo 无全量列表口,用 NASDAQ Trader 两个上市文件(实测 ~13k 行,含 ETF 与 Test-Issue 标志)+ SEC company_tickers.json(实测 10,429 家,直接给 CIK)。yfinance 只当价格 provider;符号映射 `BRK.A→BRK-A` 只在 provider 调用点
- **识别 = 确定性搜索 + 人点选确认**:ticker 精确 > ticker 前缀 > 名称子串,typeahead 下拉带能力徽章(价格✓/ETF/研究✓),**永不自动选**(实测搜 "apple" 命中 5 家——自动挑选即赌错误类);CSV 批量保持精确 ticker,不做名称解析
- **三道门**:在宇宙表(能加)→ 拉得到价(U2 回填,fail-loud 拒行)→ 有 CIK 且显式触发(issuer 研究,仍限策展集)
- 并发补齐:worker lease+requeue(治 stuck-run 类,重投走白名单)、per-session 单飞行 turn(lease 版)、per-user/全局日配额走 `usage_daily`(见上「预算」节的 ★ 改写)

### 排期估算

~7 天,V2-A 身份 → B 组合 U1 → C RLS → D 宇宙 U2 → E 并发+预算 → F 部署 → G 终验;逐阶段任务/验收/红线见 [IMPLEMENTATION_PLAN_V2.md](IMPLEMENTATION_PLAN_V2.md)。

### 明确不做

k8s/微服务/消息中间件(Redis/Celery)、企业 SSO、组织/团队模型、用户间共享、组合原地编辑与删除流、agent 写组合工具、非美市场、分库分表、alembic。

---

## M15 — Harness 组件补全(2026-08-02 完成)

> **状态**:Verify / Context / Memory / Evals 四个组件全部落地,16 commits;
> 其后 V3-R 按对抗式 review 收口 +7(见本节末)。
> 278 offline + 89 live 全绿(V3-R 后 313 + 98);终验数字与实测证据见 [spikes/V3_COVERAGE.md](spikes/V3_COVERAGE.md),
> 执行计划见 [IMPLEMENTATION_PLAN_V3.md](IMPLEMENTATION_PLAN_V3.md)。

背景:把系统对到 agent harness 的标准组件清单(loop / tools / context / guardrails /
verification / memory / observability / evals)上之后,V2 之前散着的一堆问题合并成了一句话:
**这个系统的"可信"靠的是「引用的 ID 为真」+「计算可回放」,而这两条都不管"回答里的那个数字对不对"。**

### 设计上值得记住的四条

- **验证的判据是「写法精度的半个 ulp」,不是相对容差**。语义是"真值必须能四舍五入成模型写下的
  那个数"。相对容差两头都错:正确的舍入被拒(0.04061908 写成 `4.1%` 相对误差 0.94%),
  末位篡改被接受(`$82.886B` 的 rtol 开出 ±$414M 窗口)。
- **单位由 schema 推导,不猜**。fact 的 `unit` 列、calc 的 `operation` 名、run 子表的列名
  各自决定单位类;只有 PERCENT↔RATIO 换算,系数恰好 100。曾经写进计划的"缩放族"
  `{v, v/1e3, v/1e6, v/1e9, v*100}` 是五路"我不知道单位",在无 fallback 的模块里尤其不能要 ——
  实测反例:一行 risk_alert 同时有 0.158 / 0.15 / 0.792,缩放族会把"用到限额的 15.8%"当成对的。
- **gate 的产物不是证据**。`respond` 拒绝时会把它刚拒掉的 id 回显在 `problems[]` 里,而这次调用
  是 `completed` —— 于是伪造 id 被 harvest 进 trail,重试时就过了 trail 检查。GATE 类工具的
  返回值一律不 harvest。
- **抽取器要拿真语料建,不能拿想出来的例子建**。四个 bug 全是跑真实 `agent_messages` /
  `issuer_briefs` 才暴露的,其中最危险的一个让 `AAPL 15.8%` 被当成 `Microsoft 365` 那样的
  产品名豁免掉 —— 真实回答里三个 issuer 权重被吞了两个。

### 与既有模块的接缝

- M3 计算代数新增 `series` 恒等原语。看着冗余,实则必要:季度序列里的**派生 Q4**
  (年度 − Q1 − Q2 − Q3)在任何表里都没有对应行,它携带的四个 fact id 各自是**别的数**,
  所以"引用正确且数字正确"在结构上无法验证。给它一个自己的 calc id 才关掉这个误拒类别。
- M9/M10 的 gate 增加第二道:引用 ID 为真之后,再查数字。chat 走整条回答,brief **按 block 用
  该 block 自己的引用** —— 合并检查会让 market_context 的数字被 financial_summary 的引用"担保",
  那正是一份内部自洽、逐条无据的 brief 的成因。
- M11 审计面新增 `agent_messages.meta`:gate 失败标记与 prompt token 数。**不能复用 `role`** ——
  `_load_history` 把 role 原样喂进 provider 的 messages 数组。
- ★ M5 的"检索质量实测后再议"结清了:24 query 基线已记录。**首次实测最有价值的产出不是分数,
  而是 recall@5 = 1.000 说明这个指标在本语料上饱和、测不出回归**,故回归守的是 precision@k。

### 明确不做(V3 范围)

B3 上下文摘要(B0 实测显示一整轮只有几千 token 对 80k 上限,现在建等于猜)、LLM-as-judge
评测(确定性检查还没用尽)、passage 级检索标注(要人读 3,078 个 chunk)、MCP 自己的 face
(属 MCP 计划,现为 `docs/MCP_PLAN.md`;写此清单时的 MCP_BOUNDARY_PLAN 已于 2026-08-03 删除)。

### ★ V3-R —— 对抗式 review 的回答(2026-08-02,+7 commits)

> 六个维度交付五个(第六个按指示叫停),每条发现**先手工复现再采信**。
> 313 offline + 98 live;执行计划见 [IMPLEMENTATION_PLAN_V3R.md](IMPLEMENTATION_PLAN_V3R.md),
> 逐条清单、驳回理由与遗留见 V3_COVERAGE §Adversarial review。

两条新踩坑,和上面四条同级:

- **豁免正则的每一支都要有对抗测试**。V3 给 designator 写了"大写词 + 数字"这一支,并且
  有测试证明 `AAPL 15.8%` 不被吞——但那条测试只覆盖了**后面跟单位**的形状。
  `AAPL 5000` 后面什么都不跟,于是整句话抽不出数字,A0-1 连"有数字"这个前提都不成立,
  零引用直接放行。**一条豁免规则的测试必须同时给出"它该盖住的"和"它绝不能盖住的"**,
  后者要按该规则的每一个自由维度各来一个,不是给一个反例就算完。
  同源教训:窄化一条豁免前先跑真语料——旧 designator 顺手在盖 `March 28`,
  删掉它会开始误拒"quarter ended March 28",这是语料告诉我的,不是我想出来的。
- **测 RLS 必须用非特权角色**。`exposure` 是表 owner 且 `rolbypassrls`,拿它连上去写的
  "另一个租户看不见"断言在 RLS 整个关掉时也照样绿。V3-C 的两条可见性主张(brief 归属、
  跨租户 rrun_)就是这么"验证"的。改成 `app_rls` + 事务内 `set_config('app.user_id')` 之后,
  再把连接换回 owner 跑一遍确认变红——**一条在被测机制关闭后仍然通过的测试,比没有测试更坏**。

补充一条给"证据身份"的:**铸 id 的地方每多一处,就多一次漏前缀的机会**。
`alert<hex>`(V1)、seed 的 `str(uuid.uuid4())` 位置(V3-R,10 行 demo 持仓)是同一个 bug 的
第一次和第三次。四方对称测试(harvest / gate / resolver / numeric)挡住了"prefix 只加三处",
但挡不住"铸造点不走 `new_id`"——后者现在由 live 语料断言(`positions` 全表必须 `pos_` 形)守。

---

## M16 — risk_limits 收口成单一真相(2026-08-03 完成)

> **状态**:V2-H 步④,被 V3 与 V3-R 各推迟一次,现已落地。8 个 commit
> (`c5a9997`…`ff7b631` + 文档),313 → 410 offline / 98 → 102 live 全绿。
> 迁移已应用到活库(`risk_limits` 78 → 104 行),demo 已在重建后的栈上重跑验证。

**问题**:`check_limits` 声明 `db_limits`、workflow 每次运行都专门查库把它建出来并传进去,
**函数体一次都没读过**。真正生效的阈值来自 `configs/risk_limits.yaml`,以及函数自己 `cfg()`
闭包里的 16 个硬编码字面量 —— 而 API 容器**根本没有 `/app/configs`**,配置文件缺失时的处理
是打一行 warning 返回 `{}`,于是那 16 个字面量被静默提升为线上阈值。后果不是"死参数"这么轻:
用户在产品里设的限额完全无效,`GET /portfolios/{id}/limits` 却一直把它们当"生效中的政策"展示。

### 设计上值得记住的四条

- **删掉别的路,而不是加优先级规则**。`LimitBook` 没有第三参数;`limits_config`、`db_limits`、
  `cfg()` 与 16 个字面量、`configs/risk_limits.yaml` **整体删除**而非置空。置空是不够的:
  容器无 `/app/configs`,那条 `文件不存在 → warn + {}` 的路径已经在把 16 个字面量喂给每一次调用,
  一个"清空 config 但保留 cfg()"的半切换在实测上完全不可见。
- **种子常量与引擎之间那条缺失的 import 边,就是全部保证**。`analytics/limits.py` 不许 import
  `limit_defaults`;由**解析 import 图**的测试守(不是 grep 字符串 —— 模块 docstring 自己要写明
  这条禁令,子串检查会把那句话判成违规,同时漏掉 `importlib.import_module`)。
- **完整性是数据库事实,不是读取时的仲裁**。partial unique index 让"一个 check 只能有一条默认行"
  成为约束;缺行在**步骤 3** 与价格陈旧同一次抛出(不在 `check_limits` 里 —— 那时 run 已经付过
  价格同步、因子回归、压力测试的代价)。`MissingLimit` 是保险丝,永不该响,不许 catch。
- **行存在 ≠ 检查执行**。八个 check 各自守在输入是否存在上,而一个短历史持仓会通过
  收益面板的取交集(V5 前是 `pivot.ffill().dropna()`,现为 `total_return_panel` 的
  `dropna`)截断整条收益序列,静默让 VaR/ES/波动三项不运行 —— run 照样绿、
  页面照样写"所有限额在范围内"。现在 run 认证"8 行齐备"之后,读者更会把它当成"8 项已执行",
  所以 `check_limits` 额外返回 `evaluated` 并写进事件的 `payload_summary`。

### 约束能做的与不能做的(如实)

三条 CHECK 排除的是两类**机械性自摆乌龙**:warning 非正;两档相等或倒挂(都会杀掉 warning 档,
因为 breach 先测)。它们**不能**判断一个数字对这个 check 而言是否合理 —— `daily_loss` 的 breach
填 9.99 满足全部约束且永不触发。上界必须 per-check(`gross_exposure` 合法地 >1),而 per-check
上界等于把阈值数字写回 schema,正是这次删掉的第四份来源。所以今天没有任何东西抓它,文档如实写着。

### 方法上的两条(承自 V3-R,这次又各印证一次)

- **先红后绿**:`test_limit_completeness_live.py` 在迁移前跑出三条红,输出直接进了 commit
  message —— 它顺带独立推翻了侦察报告的说法:缺默认行的是**全部 7 个组合**(6 个各缺 4 条、
  `port_rvprobe` 缺全部 8 条),不是 1 个。
- **改完要拿变异证明测试有牙齿**。切引擎前跑了三次变异全部转红:override 查到了却不用
  (原始 bug 逐字复刻)、某个 check 不再查表、entity 作用域的限额按整本书查。第三条是漂移钉
  **断言 scope 而不只是名字**的理由 —— 投影掉 `entity_id` 的版本会在"所有 override 全部失效"时
  保持绿,而那正是这次要修的状态。

### 实证(重建后的栈)

demo 重跑 11 步全绿,告警从 2 条变 3 条:AAPL 0.16187 / JPM 0.15402 原样(对全局 0.15),
**新增 LLY 0.13809 对它自己的 0.12** —— per-portfolio 阈值第一次真正生效。事件 payload 记下
8 个 check 共 27 个 (check, entity) 对,`inert_overrides` 为空。匿名红线(`/`、`/issuer/NVDA`、
`latest-brief`、run 详情)全部 200。

---

## M17 — 量化产物读 + 轨迹判据 + 回撤取证(V8-A…D,2026-08-27 完成)

**一句话**:确定性层早就算出来、门早就认得、而 agent 读不到的东西,现在读得到;并且第一次有一道门看的是**这一轮做事的形状**,而不是答案本身。

### 为什么是"读不到"而不是"没有"

`_RUN_CHILDREN` 自 V3 起就能把 `run_` 解析到 `factor_attributions.beta`、`issuer_exposures.contribution`。V8-P 又把回归元数据、压力情景、限额检查落成了行。所以证据解析器一直能回答"这个数字在不在这个 run 里",而**没有任何工具能让模型先看见这些数字**。结果是模型只能猜写什么 —— 一个当日归因躺在表里,而"这本书为什么跌"被十五次 filing 检索回答。

A 批五个读、B 批一个方法工具,全部 META_ONLY:它们回答的是**关于这张桌子自己的书**的问题,而 research 面按构造是 issuer-scoped 的。一个能读持有人归因的写 brief 的 agent,写的是错的公司。

### 两处"断言缺席"

- **`get_attribution` 没有 `top_k`/`limit`**,并有测试断言这个"没有"。尺寸参数正是一个答案点两个名字、暗示其余八个没动的那个机制。集合小就整个回来;哪天不小了,答案是**带总数的分页**,不是模型自选大小的截断。
- **`analytics/drawdown` 没有深度分解**。这不是谨慎,是**它不存在**:回撤深度是路径统计量 —— 依赖收益的**顺序**,端点由数据自己挑 —— 因此跨期不可加,没有任何一组逐名数字加得出它。任何自称是它的东西,是另一个量顶着这个名字,通常是两日期之间那段窗口的累计贡献。那个真实的量正是 `explain_episode` 返回的,并如实标注。**缺席写在模块导出面上,不是运行时拒绝**:存在而拒绝的函数,是模型会重试的函数。

### `quotable_individually` —— docstring 变成字段

`factor_model` 的 docstring 自 V6 起就论证:共线性下**因子集之和**是良定的,而每个系数不是。那个论证住在 docstring 里,**写答案的模型读不到**。现在它是每个 beta 上的一个字段。它看起来像判断而不是:它陈述的是**估计量的确定性**(VIF 越线,回归自己算的),不是这个数字是不是好消息。

### 轨迹判据:两条,以及为什么每条都必须留一条免费的出路

- **R1 顺序**:回复同时引用了组合证据(`run_`/`alert_`)与 filing 证据(`chunk_`/`src_`),而本轮没有任何一步读过持仓贡献 → 拒。**只在两种证据同时出现时触发** —— 只问一家公司 filing 的答案不是它要管的,在那里触发会让"AAPL 有多少债"也要求调组合工具。
- **R2 委派节制**:本轮完成的 `start_issuer_research` 超过 2 个,回复必须列出全部 run id。失败/被拒的委派**不计**——它们什么都没入队,计它们等于要求模型说出一个不存在的 run。

两条的出路都**零工具成本**,而且拒绝文案明说是哪条:删掉 filing 引用;或者把已经在上下文里的 id 写出来。这是 DP4,不是体贴 —— V7-Q2 造出过一道**只能靠花掉已经花光的预算才能满足**的门,那一轮于是根本没有出口。每条判据都有一个专门跑这条免费出路的测试。

**作用域是 message 不是 session**。C1 在 `_session_ctx` 旁边加了 `_message_ctx`:`invoke()` 从追踪学会按轮分组起就一直收着 `message_id` 并直接传给 `record_step`,所以这个值写进了每一行、而**在工具函数里够不着**。按 session 计会被四个问题以前的一次调用满足,然后**永远**被满足 —— 那是一条停止批评的判据。

> `_respond` 的 docstring 曾声称"零引用分支从不碰 db"。它不能再这么说了:R2 要管的正是"入队六个、一个没说"的那一轮,而那种回复**什么都不引用**。跳过零引用分支的判据,恰好跳过了它要抓的形状。现在写的是那句更弱的真话(没有 message 作用域就没有查询),并有测试断言查询数为 0。

### 判据的容差从 schema 推导

`reconcile_move` 的两个恒等式:每一项都是 `Numeric(12, 8)`,所以一个 ulp 是 1e-8,n 项相加再与另一个存储值比较,容许 `(n+1)` 个半 ulp。**固定 epsilon 是某人挑的数字**,列的标度一改就过期;**相对容差两头都错**(V3)。

### 恒等式 A 不成立时,份额字段是**不存在**而不是 null

一个 null 份额邀请"未知的份额";一个不存在的键根本读不出来。用一个 frozen dataclass,只在成立分支合并进 payload,于是"这次归因我们没能验证"与"这是这次移动的份额"**由构造互斥**,而不是靠调用方记得查 flag。

余项叫 `alpha_plus_residual`,并有测试**禁止** `specific_return`:alpha 是因子集在整个窗口上平均漏掉的,residual 是今天漏掉的,两者相加是一个**关于模型**的陈述。另一个名字把它说成持仓的属性,授权一句关于选股的话 —— 而这里没有任何东西测量过它。

### 三条实证纠正(细节见 `docs/spikes/V8_COVERAGE.md` §3)

`utilization` 是 `current/breach_level` 而 `limit_value` 是**被越过的那一档**,计划里的示例文案对本代码库是错的;恒等式 B 的左边必须是 `attribution_portfolio_return`(差 2.4e-6 全部是分红历史);benchmark 要按 **ticker 对本台是什么**选价格表,而这个问题从 DB 事实回答**不从 YAML 读**(api 容器没有 `/app/configs`,是 M16 那个 bug 的同形)。


---

## M18 — 序列并轨:一种取数、一种算、一条路(V10,2026-08-27 完成)

**一句话**:V9 把"取一个窗口"做对了但没做"取一串";V3 有"一串"但窗口是错的枚举。把"一串"建在 V9 的窗口上,然后把 V3 删掉。工具面 36 → 31,不新增任何分析能力。

### 为什么不是"删 V3"

起草时我写过「V3 能做的 V9 都能做」,对着代码核是错的:`interval_algebra` 只有 `derive(start,end)` 与 `latest_window(months)`,一次一个窗口;`get_fact_series` 给 N 个期间的阶梯。真实使用(yoy over 4–8 季,113 次)正是 V9 缺的形状,而 `recipe.py`(issuer 页 Financials tab)直接依赖 V3 路径。所以 V10 是三步:建序列维度 → 全语料 parity → 迁 recipe → 整体删旧路(DP3,V2-H4 的"半切换不可见")。

### 序列 = 连续窗口,而且有相位

`consecutive_windows(facts, months, last_n)`:锚点是语料自己的期末日,相邻两两 `derive`。它取代的不只是 `build_ladder`,还有 `derive_q4` 这个特例——Q4 就是一个窗口(常为 FY − 9M)。

全语料 parity 逼出两条设计,都在"序列从哪里结束、怎么走":

- **相位是发行人的**。第一版从 `latest_window` 的 end 起步——对 AAPL 十二个月那是到 6 月季末的 TTM,往回走出来的是一串 6 月,484 个财年点"缺"了 420 个。`_series_end` 取该长度的**原生报告期**(年度看 FY 事实、季度看 Q1 事实)的期末,选最新的、与之相差整数个 span 的边界。季度落在最新的 6 月边界(比最后一个 Q1 事实晚两个可推导的季度),年度落在 9 月。**单窗口 = 最近可推导的那个;序列 = 发行人自己的报告期按序**,两者不共享 end,`get_flow` 的 docstring 写明。
- **缺口留在原位,走法不停**。NVDA FY2023 的 capex 只报了 9M 与 FY,往前一个季度没有任何边界,第一版在这里停下,FY2022 的四个已申报季度永远够不着。现在缺边界的槽按名义日期留一个 Unreachable(DP2)继续走,下一个靠近真实边界的槽重新对齐。最老一端的连续 Unreachable 修掉——它们只说明"数据从更晚开始"。

**parity 数字**:季度 1439/1439、年度 484/484(A6 容差);季度多出 252 个窗口,全部是累计申报的现金流指标上的 2 项推导(H1−Q1、9M−H1 那种形状),年度零多余。

### 工具面:8 个替 13 个

```
定位  describe_issuer                       ← get_issuer_snapshot ⊃ list_available_data,+ list_formulas(每家相同的 16 条,加"这家能算哪些")
取    get_flow(…, last_n?)                  ← + get_fact_series(quarterly/annual)
      get_balance_sheet(不变)
      get_balance_series                    ← get_fact_series(instant):一条线在每个日期,不推导不填
算    calculate(序列对齐)                   ← + compute_ratio(=combine.divide,docstring 自认)+ compute_combine
      series_stat(series_id, op)            ← compute_change ∪ compute_stat(真实使用 yoy 74 / latest 4 / qoq 2 / abs 1,无一可删)
      evaluate_formula / get_fundamental_panel(不变)
```

`series_stat` 只收一个 id 和一个 op——`compute_change` 收 `(ticker, metric, period_type, last_n, mode)`,把"取"和"算"绑在一次呼吸里,五个工具共 21 个参数。算法层 `series_ops.compute_change/compute_stat` 原封不动(它们吃 `SeriesPoint[]`,从不认识 ladder,所以活了下来);`combine_series` 删,`typed_calculator._align` 是唯一的对齐器。

`calculate` 升到序列:按 end 对齐(容差就是引擎的 `BOUNDARY_TOLERANCE_DAYS`,不是新数字),每一对过同一套 `_check`,**一对被拒整体拒并点名槽位**——静默丢一个点的序列在长度上说谎。未匹配的期数丢弃并计数(`combine_series` 一直的规则)。

每个序列行记录 `result_type`,`_from_calc` **先信记录的类型再查 op 名表**:`stat.latest` 对一个 margin 序列是比率,op 名说不出这一点。

### recipe v2 与 manifest

同一组标签,经新原语组合;结尾**一条 manifest 行**记每个标签的 calc_id。Financials 路由读 manifest,不再按 `invoked_by='recipe'` 扫台账、按 `params.series.metric` 分组——v2 的 yoy 行 `series` 参数是它所取序列的 id,每次运行都不同,"每 metric 最新一行"没有稳定的 key。

实跑 8 家:AAPL/NVDA 是仅有的两家跑过 v1 的;AAPL 两代共有的 77 个点**逐点相同**,v2 更多(ocf yoy 8 vs 5,fcf 12 vs 6——S1 量出的累计申报增益到页面上)。**三件撞出的既存事实**:NVDA `revenue` 的 v1 行是 7/24 的、早于 V9-M1 把 NVDA 2022 后收入拆到 `total_revenues`,今天 v1 同样取不到——recipe 硬编码 `revenue` 而 V9 公式表有具名替代,是 recipe 的问题不是 V10 的;LLY capex 事实止于 2022-09 与 ocf 零重叠,`misaligned_series` 是正确的拒绝(v1 会给空序列带 calc_id);六家从没有过 Financials tab。

### 冻结的 ladder

`period_ladder.py` 不在产品代码里了,但在 `tests/legacy_ladder.py`:一份冻结的参考实现,只有两个 parity 测试 import 它。A6 的 290/290 与 S1 的 1439/1439 是某一刻的证明;作为常驻测试它们是守卫,守卫需要一个固定的东西来产生分歧。它不会漂移,因为没有别的东西够得到它;`restatement_key` 从引擎 import,一条规则还是一条。

### 本批记下的两条

- **切一块代码时,数它中间夹着什么**。从 `SeriesSpec` 切到 `load_price_series` 把 `_company_id` 一起切走了——五个序列函数都在那一段,它们共用的那个 helper 也在。offline 全绿(没有测试碰数据库),live 第一条就 NameError。V3 那句"全绿只是测试碰巧盖到的"又一次。
- **一个真实的 store 规则只能有一个家**。`_benchmark_series` 的选表规则(V8-D 写在 drawdown_service)搬进 `market_data_service.price_points`,`window_return` 与 `explain_episode` 都经它;`get_market_stats` 同时改用服务端日期(V5 修 recipe 时漏了这个工具)。

## M19 — 桌面:量带名字上桌、出口按论断类型指名、验证只解析(V15,2026-09-01 完成)

**一句话**:模型可以指的东西放进一个对象(桌面),由一个构造器建一次,同时是上下文载荷、门的全集、审计记录;出口只写桌面上的名字,门只做查找。组合半边由此拿到发行人半边早有的四件套——身份、清单、具名生产者、挂在对象上的知识。

### 为什么是这个形状(而不是修出口)

V15 初稿的三个方案(按值重指 / 按值反推补算 / 规范量归并)全部被实测证否:同值多标签 45%、等价推导中位 24 条、结构性重复只占歧义 30%。共同死因是**值不携带意图**。9/1 一条真实 session 把它演到底:模型写 `{value: 0.06}` 说是预警线,门按半 ulp 在 235 个值里找到 `issuer_exposures.TLT.weight = 0.0607` 并**接受**,读者看到 "0.06073614 warning level",hover 显示 TLT weight。这不是模型错、不是门实现错,是身份没有随值交付。

同一 session 还演了另外两件:靠两段 10-K 原文支撑的段落没有数字,块文法里没有"引原文"这种论断,模型把 `Evidence ids: chunk_…` 写进正文,引号核对因语料空而没查,渲染为纯文本;一条消息 20 个并行 `describe_issuer`/`get_market_stats`,因为 book 作用域的问题只有 issuer 作用域的定位工具。

### 三条边界 + 一个构造器

- **A 输入**:`Tool.evidence` 是注册时的声明(`Evidence(scope=…|names_from=…|tasks_from=…)`),关口据此 `table.declare` → `table.build`,把 `result["table"] = {quantities: {ref: {唯一名: 读者精度值}}, passages, rows}` 附在结果上,并把声明存为 `agent_steps.evidence_refs`。名字由 `services/quantities.py` 唯一拼出(`resources` 列 × `display_names` 行标签;alert 加 `entity_id` 限定后 235/235 唯一)。共线单系数**不上桌**(投影,不是验证)。`describe_run` 是 book 侧的 `describe_issuer`:按"回答什么"分组的名字清单(pattern × labels 压到 7.9k 字符)、缺什么、共线、face 能力声明;`read_quantities(run_id, names)` 是 book 侧的 `evaluate_formula(name)`。
- **B 出口**:`RESPOND_SCHEMA` 用 oneOf 表达六种论断:paragraph/metric_table(槽 `{ref,name}`、`cites`)、chart、trend、absence、action。`slot.value` 不存在;文本 `\d` 为空,豁免类封闭且短(日期、年份、表单号、期间标签、法规引证、附着型号、窗口标签),id 写进正文按整个 token 拒。`submit_brief` = 六节 × 同一文法(`BLOCK_SCHEMAS` 直接 import),`issuer_briefs.blocks` 落 JSONB。
- **C 验证**:`services/resolver.py` 六不变量,全是集合/字典查找:形状(schema)→ ref ∈ 桌面 → name ∈ 该 ref 的量 → 引号 ∈ 该块 `cites` 的原文 → kind 谓词。四出口同一函数(`test_one_resolver`)。
- **构造器**:`table.load(session)` = 全部 completed 步声明的并集,session 作用域即跨轮继承;跨会话永不上桌。

### 整体删除(DP3)

`extract_evidence_refs` 遍历、`_harvestable`、`collect_trail` + 存在性查询、`trajectory_gate`(R1 进 rubric,R2 由 action 谓词取代)、`_COMPATIBLE`/`_DERIVATIONS`/`held_instead_by`/按值解析槽、26 个运行时形状码、散文 `_respond`。`numeric_verification` 只剩 v1 散文路径(日报门 + 读时 eval),1041 → 534 行。

### 实测纠正了计划的三处

① 计划说"日期唯一豁免";实测三条已存储的块答案因 "30-day rolling volatility" 被拒——窗口标签是量的**名字**不是值,豁免类是封闭的七项而非一项。② 计划写 "ref ∈ 本轮账本";代码里 trail 一直是 session 作用域,"跨轮继承"是既有事实而不是新动作。③ `portfolio.window_return` 43 行既无 `unit_class` 也无 `result_type`,又不在冻结的 14 项 legacy 集里,被门当 MONEY——写入侧改为带单位,`v15_window_return_unit.sql` 回填。

### 守卫

`test_table`(三出口同源)、`test_quantities`(235/235 唯一、载荷 ≤ 16k)、`test_symmetry`(每个面上每个工具要么声明证据要么在显式白名单;分组 pattern 双向覆盖真实名字)、`test_output_grammar`(schema 拒一切非文法形状;`slot.value` 不存在于源码)、`test_one_resolver`(两出口同一解析器;`not_alone` 只在 table.py 决定)、`test_display_conventions`(py/ts 共读 `tests/fixtures/display_cases.json`)、`test_v15_table_live`(缺席行经 `get_flow` 拒绝 → 上桌 → absence 块过门)。

## M20 — 单位代数与器械:值出生即完整,方法是数据,Agent 只做分析(V16,2026-09-01 完成)

**一句话**:Agent 的工作是做分析,tool/skill/validation 是服务于分析的器械——tool 是值的唯一出生地(名字/单位/期间/意义齐了才出生),skill 是带 authority 与失效条件的方法数据,validation 是永久封闭的五种查找(本批**零新增**,源码钉住的测试未动)。两条元规则铺满全表面:跨模块约定=共享常量或对称测试二选一;"作者必须记住"=构造期报错/红测试/删除约定三选一。

### 形状

- **单位代数**(`analytics/units.py`,单一属主):四元 {money, ratio, count, money_per_share};乘除查 PRODUCTS/QUOTIENTS(交换键,结果与操作数顺序无关;money×money **未定义即拒绝**,不再默认 money);`fact_unit()` 单点判定(此前 quantities 判 COUNT、typed_calculator 判 RATIO,同一行两个答案);`POINT_PERIOD_KEY` 统一写端(读端三键 tuple 冻结,随旧行消亡)。`calc_service._record` 拒绝携值而无 quantity/unit_class 的行——NULL 后备整体删除。
- **映射 v4**:每股/资本配置层。三个股数是三个量(语料期间形态实证:weighted=duration 配 flow,outstanding=instant 配市值),互为 do_not_combine;eps 不重导(ASC 260);dividends 双 tag 发行人集合零交集,broad tag 或含 preferred——注在 semantics,不隐藏。
- **意义上桌(M2)**:载荷 `名字→[值, 组]` + 每表一次的组图例(RUN_GROUPS 移居 resources,manifest 与桌面同源);被投影量的 not_alone 理由随 unknown_name 到达模型(此前死在无人读的字段里);id 前缀正则由常量程序化构建(三份手写收敛为一);`_NOT_A_FIGURE` 九条冻结禁增(死法是 M2,不是第十条正则)。
- **Tier 1 / Tier 2**:登记表 +16 条(returns/reinvestment/quality),每条带 authority 与自己的失效条件(负权益拒 roe 并给理由;银行不适用是 per-formula 数据 `not_for_financials`,ROE 正是银行指标所以**不**排除——JPM 面板从整面拒绝变成逐条如实);`calculate(as_quantity=)` 开放给面,`named_by="session"` 记录谁起的名(可见,永不权威)。formula_service 五处位置耦合(len-2 哨兵、signs[0] 不读、else-即-divide、双列表)全部改为 import 期校验或显式命名。
- **价格线(H1+H3)**:`price_analytics_service` 八工具(两价分立、vol/beta/momentum/52w/ADV 各携 n),最低观测数是**生产者参数**(vol 20/beta 60/momentum 200,注释带 C 路出处);不足即有原因拒绝(needs/have 可引用),绝不静默缩窗。工具由模块自带 `_TOOL_SPECS` 数据注册,schema/display/evidence 与生产者同居。
- **注册期强制**:`Tool.evidence` 无默认——`Evidence(...)` 或显式 `NOT_EVIDENCE`,都不说就 register() 拒绝(静默默认曾让 src_ 证据整批不可引)。prompt 收缩 6.6k→2.6k 字符:路径归工具描述、方法归登记表、规则归拒绝信,留下角色与 why。

### 实测纠正(S6 电池抓到、套件没盖到的)

`get_beta` 的两条 ~250 点 returns series 撑爆 16k 切片,`build()` 收缩无路时把**整个申报清空**——beta 因输入太大而死,模型被告知自己刚算的数不在桌上,诚实拒绝了。修:第二收缩相(整条掉尾、series 优先、掉了记录在案)。该修的初稿带一个 NameError 而全绿套件毫无反应——路径零覆盖,两条 pin 测试因此存在。这是两条元规则在本批自己的修复上现身说法。

### 电池(S0→S6,8 题缺口电池,判据=顶替=0)

顶替 S0 ≥2(beta 问题拿 debt/EBITDA 顶、TSR 拿收入增长顶)→ **S6 = 0**。S6 新答对:股数下降(G3)、ROE DuPont 全具名(G4)、应计比率跨发行人(G6)、OCF/NI 背离表(G8);正确拒绝:JPM EV/EBITDA(G5)、TSR 分解(G2,缺口=倍数序列,本批声明不做)。残余是另一类:槽全真而句子错(as-of 日期不可 slot 于是价格槽被误用;比较级排序断言为假)——门保证指向不保证句子,由电池计量,非阻塞批评者留 V17。细节 `docs/spikes/V16_COVERAGE.md`。

### 守卫

`test_unit_algebra`(代数表逐行+交换律+_record 拒绝)、`test_share_counts`、`test_price_quantities`/`test_determinacy`(n 不足=有原因拒绝,决不缩窗)、`test_table_meaning`(三元组+图例+投影理由全链路)、`test_registry_conditions`(失效条件逐条+import 校验反例)、`test_table` 第二收缩相双 pin、`test_symmetry` 扩(前缀三处一集合、RUN_GROUPS 同源、alert 列派生)、registration 拒绝无声明工具(白名单从测试移进注册处本身)。
