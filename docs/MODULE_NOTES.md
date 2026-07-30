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

## M3 — Analysis Primitives & Computation Ledger(2026-07-23 定稿,经重定义)

> 重定义:M3 不是"预先定死的指标清单",而是**分析原语 + 计算台账**架构。
> 具体算哪些指标是 recipe 内容(随时可改,不在架构讨论范围);架构回答的是:
> **agent 怎样在不亲自算数的前提下自由分析**——算术归工具,编排归 agent。

### 三层结构

```
消费者层(同一套原语,四种驱动)
  ① Workflow 标准 recipe:固定脚本序列(内容后议)
  ② 分析 agent:自由组合原语,预算硬顶
  ③ Meta-agent 交互问答
  ④ 外部宿主经 MCP
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

- 分析 agent 大脑位置:应用内 bounded loop vs 外部宿主(OpenClaw/Claude Code)经 MCP 驱动。架构两者都支持(强制与追踪沉在 transport 之下),MVP 先做哪个实现期定。

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

- 六块结构(financial_summary / key_changes / management_explanation / market_context / portfolio_implications / open_questions)+ confidence_notes,tool-call 形态强制
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

1. 提交门修正预算:**2 次重提**(初提+2 修正),耗尽 run failed;数值进配置。
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
2. readiness 步序 MVP 串行。

### 明确不做

定时调度、跨 issuer 批量 run、断点续跑(失败即重跑,幂等保证廉价)、步级自动 retry。

---

## M10 — ToolRegistry + Meta-Agent(2026-07-23 定稿)

### ToolRegistry:一份定义,四个消费者,两层强制

- 工具五元组:`{name, json_schema, fn, class: read|delegation|reflection, budget_key}`,注册一次
- 消费者:meta-agent / 分析 subagent / MCP 外部宿主 / workflow recipe(fn 直调)
- **Registry wrapper 自动做三件事**:入参语义校验、预算记账(调用前扣减,超顶结构化拒绝)、轨迹落盘(agent_steps,evidence_refs 从返回值 id 字段自动抽取,不靠工具作者手动报)

### 工具面(face)是声明式配置

```
FACE_META_AGENT = read 全集 + delegation{ensure_company_ready, start_issuer_research,
                  start_exposure_run} + think + respond
FACE_RESEARCH   = read 全集 + search_external_research + think + submit_brief
                  (无 delegation → agent 树深度架构性封顶为 2,防递归不靠约定)
FACE_RECIPE     = 数据+计算原语 fn 直调(无 LLM,无预算,只留台账)
```

skip 参数裁剪作用于 face;"agent 能干什么"的答案在一处配置,审计一眼看全。MCP 外部宿主拿 FACE_META_AGENT 同款——同权、同预算、同轨迹,无特权通道。

### Meta-Agent:循环极薄,行为由 face + 门塑造

- 系统 prompt 只写角色与证据纪律的"为什么",不写行为规则清单——prompt 里堆规则 = 承认架构没堵住
- delegation 全部非阻塞(发起即返 run_id,进度靠追问/UI 时间线),meta-agent 永远秒级响应
- MVP 单活跃会话,无跨会话记忆,无自主定时行为

### ★ 已定:respond 也是工具(选项 1)

`respond(text, citations[])` 是会话唯一出口:citations 结构化提交,wrapper 校验每个 id ∈ 本轮 Evidence Trail,编造被拒(1 次重试)。`citations=[]` 合法(非事实性回复);**但凡引了,必须是真的**。一套门机制服务 chat 消息与 Brief 两种产物。

### ★ 已定:MCP 双轨规则(2026-07-23,吸收 M12)

> **Agent 面 = MCP,唯一;代码面 = fn 直调;两面共穿一个 wrapper。**

- 凡 **LLM 生成**的工具调用一律走 MCP——内部 meta-agent 循环也作为 MCP client 连入,与外部宿主(OpenClaw/Claude Code)字面上同一 server 同一接口
- 凡**确定性代码**的调用(recipe/wrapper)直调 fn——代码无"生成调用"动作,不存在需生成时堵的错误类别,MCP 徒增序列化开销
- 与 sm-master 分裂的本质区别:那是"两条 **agent** 通路、两套强制";这是"一条 agent 通路 + 一条代码通路、**一套强制**"(wrapper 是两轨共同关口)
- 内部走 MCP 额外买到:大脑可换是构造不是声称(随时换 OpenClaw 当 meta-agent)、门面因日常流量不烂、审计口径唯一
- MVP 部署:FastMCP 挂 FastAPI 进程内(ASGI `/mcp`),meta-agent 经 in-memory client 连;不加容器;会话预算状态在 DB,跨进程一致。独立 MCP 进程留给放量后
- **M12(MCP Facade)作为独立模块取消**,并入本节

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
> Clerk 仍是 dev 实例;删号路径与 `check_limits` 死参数已在 V2-H 关闭)。**公网链接前仍需人工完成**:DNS 记录 +
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
