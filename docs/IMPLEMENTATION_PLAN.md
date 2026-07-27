# Implementation Plan — Issuer Intelligence MVP

> **版本**:2026-07-23
> **读者**:执行实现的 agent(假定没有架构讨论的对话上下文,本文档自足)
> **前置阅读(必读,按序)**:
> 1. [TARGET_ARCHITECTURE.md](TARGET_ARCHITECTURE.md) v3 —— 系统不变量与拓扑,**任何实现与它冲突时以它为准并停下来问用户**
> 2. [MODULE_NOTES.md](MODULE_NOTES.md) —— M1-M13 逐模块设计定稿,含每个模块的"明确不做"
> 3. [ARCHITECTURE.md](ARCHITECTURE.md) —— 现有系统(保留不动的部分)

---

## 0. 执行者须知

### 0.1 三条全局规则(违反 = 返工)

1. **Fail loud**:无 mock、无静默降级、无"旧数据顶上"。跳过能力 = 显式参数。现有 `agents/direct_llm_agent.py` 的 `_mock_output` 是旧代码遗留,**禁止复制该模式到任何新代码**。
2. **Schema 消灭解析**:LLM 输出一律 tool-call 强制形状;禁止写 "strip fences → json.loads → 失败兜底" 类代码。
3. **正交替代路由**:禁止问题分类器、阈值过滤器、query 模板集。

### 0.2 硬性代码纪律

- import 单向:`apps → tools → services → providers/db`;`agents` 只 import tools 客户端与 llm;**routes/agents/analytics/tools 中出现 `edgar`/`yfinance`/`tavily` import = 违规**(P9 有 grep 验收)
- 证据四库(financial_facts / filing_chunks / calc_ledger / research_sources)与轨迹表 **append-only,代码中禁止 UPDATE/DELETE**
- 现有文件除计划点名的小改外一律不动;`apps/web/app/page.tsx` 只加入口按钮,不重构
- schema 双份维护:每张新表同时进 `infra/init.sql` 与 `db/models.py`
- 新代码风格对齐现有代码(dataclass 分析结果、service 函数式模块、`_StepContext` 事件模式)

### 0.3 环境前置(P0 前用户提供)

```
OPENAI_API_KEY      必需(chat + embedding)
TAVILY_API_KEY      必需(P6 起)
EDGAR_IDENTITY      必需(SEC 要求 UA 含联系邮箱,如 "Name email@x.com")
网络访问            必需(EDGAR / yfinance / Tavily / OpenAI)
```

缺 key 时相关步骤按规则 A 失败——这是预期行为,不要绕。

### 0.4 测试与提交约定

- 单测:离线、fixture 数据、断言确定值,放 `tests/`(现为空目录);命名 `test_<module>.py`
- 集成测(需网络/key):标 `@pytest.mark.live`,默认 `pytest -m "not live"` 全绿
- 每阶段结束:`pytest -m "not live"` 全绿 + 该阶段验收全过 + git commit(消息 `P{n}: <摘要>`)
- **回归红线**:任何阶段结束时,现有 exposure run(POST /api/exposure-runs → 11 步全绿)必须仍然工作

### 0.5 本计划中已钉死的实现常量

| 项 | 值 |
|---|---|
| id 前缀 | `fact_` `chunk_` `calc_` `src_`(沿用 `utils/ids.new_id` 模式) |
| embedding | OpenAI `text-embedding-3-small`,1536 维 |
| 预算(settings 字段,env 可覆盖) | `SESSION_TOOL_BUDGET=40` `EXTERNAL_SEARCH_BUDGET=5` `SUBMIT_BRIEF_RETRIES=2` `RESPOND_RETRIES=1` |
| MCP | FastMCP 挂 FastAPI `/mcp`,server 名 `exposure-workbench` |
| 新 task type | `company_readiness` / `issuer_research` |
| series spec(计算工具入参) | `{ticker, metric?|concept?, period_type: "quarterly"\|"annual", last_n?: int}` |
| 映射指标集(M2b,10 个) | revenue / operating_income / net_income / gross_profit / operating_cash_flow / capex / cash_and_equivalents / short_term_debt / long_term_debt / current_assets / current_liabilities |
| 验收主角 | **NVDA**(P2-P7 验收全部以 NVDA 端到端;8 家全量放 P9) |

### 0.6 阶段依赖图

```
P0 ─▶ P1 ─▶ P2(事实流+spike)─▶ P4(计算)─┐
        └──▶ P3(文本流+索引)──────────────┼─▶ P5(Registry+MCP)─▶ P6(研究会话)─▶ P7(meta-agent)─▶ P8(UI)─▶ P9
P2 与 P3 可并行;其余串行。总预估 ~9.5 agent 工作日。
```

---

## P0 — 地基(0.5d)

**范围**:镜像、schema、依赖、配置。不写业务逻辑。

**任务**:
1. `docker-compose.yml`:postgres 镜像换 `pgvector/pgvector:pg16`;api/worker 环境变量加 `TAVILY_API_KEY` `EDGAR_IDENTITY`
2. `infra/init.sql`:`CREATE EXTENSION vector`;新表 DDL(companies / filings / filing_documents / filing_sections / filing_chunks / financial_facts / research_sources / calc_ledger / research_runs / evidence_packs / issuer_briefs / agent_sessions / agent_messages / agent_steps——列定义按 TARGET_ARCHITECTURE v3 §4 与 MODULE_NOTES,calc_ledger 用 v3 的台账形状);`workflow_events` 去 FK;`research_runs.agent_session_id` 列
3. `db/models.py`:镜像追加全部新模型(不改现有类)
4. `pyproject.toml`:+`edgartools` `tavily-python` `pgvector`;`.env.example` 更新
5. `app_state/settings.py`:+`tavily_api_key` `edgar_identity` `embedding_model` + 0.5 节四个预算字段
6. DB 重建路径:MVP 用 `docker compose down -v && up`(P1 会重灌数据);在 README 开发段落记一句

**验收**:
- [ ] `docker compose up -d --build` 四容器 healthy
- [ ] `psql: \dx` 显示 vector;`\dt` 含全部新表;`workflow_events` 无 run_id 外键
- [ ] 现有 exposure run 回归通过(合成 seed 此时仍在,P1 才替换)
- [ ] `pytest -m "not live"` 通过(此阶段允许 0 条新测试)

**禁止**:实现任何 provider/service;动现有表列。

---

## P1 — 公司主数据 + 行情真实化(0.5d)

**范围**:M1 全部;M4 全部。种子退役。

**任务**:
1. `providers/market_data_provider.py`(协议)+ `providers/yfinance_market_data_provider.py`(返回 PriceBar DTO)
2. `services/market_data_ingestion_service.py`:(ticker, price_date) upsert,`source='yfinance'`
3. `services/company_service.py`:`get_by_ticker`(只查表;查不到抛 `CompanyNotFound`;`is_investigable=false` 抛 `NotInvestigable`)
4. `scripts/seed_demo_db.py` 改造:①companies 写入 10 行(8 股票硬编码手工核对的 CIK;TLT/HYG `is_investigable=false`)②删除合成价格生成,改调 ingestion 拉全部 ticker(10 持仓+SPY+factor_config 因子 ETF)一年真实日线,factor_prices 一并真实化 ③持仓/限额 seed 保留
5. REST wrapper:`POST /api/market-data/sync`(纯入队;handler 注册 `market_data_sync` 调 ingestion——顺手补上这个现有占位)

**验收**:
- [ ] seed 后 `market_prices` 中 `source='yfinance'` 行数 > 2500(12 ticker × ~250 交易日),无 `source='seed'` 价格行
- [ ] 现有 exposure run 在**真实数据**上 11 步全绿,指标值非零
- [ ] 单测:company_service 三分支(存在/不存在/不可调查)——mock DB 会话即可
- [ ] `curl POST /api/market-data/sync` → task 完成,重复执行不产生重复行(幂等)

**禁止**:改 `services/market_data_service.py`(查询侧零改动);改现有 analytics。

**用户检查点**:seed 里 8 个 CIK 值列表让用户过目确认。

---

## P2 — 事实流 + Parse Spike(1d,可与 P3 并行)

**范围**:M2b 完整实现;M2a 的 parse 方案 spike(只评估,不定版)。

**任务(M2b 事实流)**:
1. `providers/filing_provider.py`(协议:`resolve_company(ticker)->CompanyDTO`、`latest_filings(cik, forms)->list[FilingMeta]`、`fetch_filing_text(accession)->FilingDoc`、`fetch_sections(accession)->list[SectionDTO]`、`fetch_company_facts(cik)->list[FactDTO]`)+ `providers/edgartools_filing_provider.py`(仅实现本阶段用到的方法;EDGAR_IDENTITY 缺失时构造即抛错)
2. `services/concept_mapping.py`:静态映射表(us-gaap concept → 0.5 节 10 指标),带 `MAPPING_VERSION = "v1"`;映射不到 → `normalized_metric=NULL` 照样入库
3. `services/filing_ingestion_service.py`(事实流部分):company-facts → `financial_facts` upsert(UNIQUE 键见 DDL);一家公司一批次一事务

**任务(M2a parse spike——先问再做)**:
4. **开工前问用户**:"是否有可复用的 filing parse 项目/skill?"(用户明确说过做过类似项目,可能有现成资产)。有 → 纳入候选;无 → 继续
5. 对 8 家公司最新 10-K+10-Q(16 份)跑 edgartools 的 Item 解析(以及用户提供的候选方案),产出 `docs/spikes/M2_PARSE_EVAL.md`:每份 filing 的 Item 覆盖表(哪些 Item 解析出来了、字符量、明显缺漏)、失败清单、方案推荐

**验收**:
- [ ] NVDA `financial_facts`:10 个 normalized_metric 各有 ≥8 个季度期次,raw_concept 保留;JPM 无 gross_profit 行(银行无此概念——是数据形状不是 bug)
- [ ] 单测:concept_mapping(给定 FactDTO fixture → 断言映射/NULL);ingestion 幂等(同批跑两遍行数不变)
- [ ] spike 报告完成,**用户检查点:用户拍板 parse 方案后 P3 才能开工**

**禁止**:在 M2b 里做任何加总/推导(Q4 推导归 P4);盲切 chunk 兜底。

---

## P3 — 文本流 + 索引检索(1d,依赖 P2 的 parse 拍板)

**范围**:M2a 完整实现(按拍板方案);M5 全部。

**任务**:
1. `filing_ingestion_service`(文本流部分):discover → `filings` + `filing_documents` + `filing_sections`,**每 filing 单事务**(全进或全不进);accession 存在即跳过
2. `services/section_chunker.py`:独立组件;按 Item 边界,节内按段落滚动(目标 ~1500 字符,参数常量集中一处——与 parse 捆绑后续调优);**解析不出 sections = 抛错,无盲切退路**
3. `llm/client.py`:+`embed_texts(texts)->list[vector]`(复用现有 client 获取模式;无 key 抛错)
4. `services/document_index_service.py`:sections → chunks → embeddings → `filing_chunks`;幂等键 (filing_id, embedding_model);每 filing 单事务;检索过滤列(form_type/filing_date/period_end)冗余写入
5. `services/filing_retrieval_service.py`:`search(company_id, query, filters, k≤10)` 向量检索(pgvector cosine,精确检索不建 HNSW),返回 passage + 完整锚点(chunk_id/accession/item/char_span/source_url);`get_section(filing_id, item_code)` 直读。**未索引 → 抛 `NotIndexed`(语义为"没数据",区别于空结果"没搜到")**

**验收**:
- [ ] NVDA 最新 10-K+10-Q 摄取:filings 2 行、sections 覆盖 spike 报告认定的 Item 集、chunks 全部带 embedding
- [ ] 检索冒烟(live 测):query "data center revenue growth" → 返回的 passages 锚点完整,人工抽查相关性合格
- [ ] 幂等:重跑摄取+索引,库内行数不变,耗时 < 5s
- [ ] 单测:chunker(fixture section → 断言切分边界与 char_span);retrieval 的 NotIndexed 分支
- [ ] 中断一个摄取事务(测试注入异常)→ 该 filing 零残留行

**禁止**:rerank、HNSW、hybrid、FilingQAService(不存在这个东西)。

---

## P4 — 计算原语 + 台账 + Recipe(1d)

**范围**:M3 全部。

**任务**:
1. `analytics/period_ladder.py`:as-reported facts → 规整季度序列;含 Q4 推导(FY−Q1..Q3,flag `derived_q4`)、重述择新(flag `restated_superseded`)、缺季(flag `missing_quarter`);纯函数
2. `analytics/series_ops.py`:combine(add/sub/divide)、change(yoy/qoq/pct/abs)、stat(cagr/avg/min/max/std)、window_return(交易日对齐,支持 benchmark 相对);纯函数,缺数返回 None+flag,**永不插值**
3. `services/calc_service.py`:series spec 解析(读 facts/prices 经 ladder/直取)→ 调 analytics → **写 calc_ledger 一行**(operation/params/result/input_refs/primitive_version/invoked_by)→ 返回 calc_id+结果
4. `services/recipe.py`:标准 recipe = 对 10 指标各:季度序列(last 8)+ yoy change;三利润率 divide;FCF sub;return 1m/3m/1y + 相对 SPY。直调 calc_service(`invoked_by='recipe'`)。内容集中一个文件,改 recipe 不碰其他代码

**验收**:
- [ ] 单测(本阶段重点,fixture facts → 断言到小数):ladder 的 Q4 推导/重述/缺季三场景;四类 series_ops 各典型+边界(空序列/单点/含 None)
- [ ] NVDA 跑 recipe:calc_ledger 落 ~40 行,每行 input_refs 非空且指向真实 fact id;revenue yoy 与 NVDA 实际公开数据人工核对一致
- [ ] recipe 重跑:追加新行(append-only),新旧行 result 相同(确定性自证)
- [ ] `grep -rn "UPDATE\|\.delete(" src/exposure_workbench/services/calc_service.py` 为空

**禁止**:阈值异常判定;行业特判分支;LLM 参与。

---

## P5 — ToolRegistry + Wrapper + MCP(1d)

**范围**:M10 的注册表半边(agent 循环在 P7)。这是全系统枢纽,宁慢勿糙。

**任务**:
1. `tools/registry.py`:五元组注册(`name/json_schema/fn/class/budget_key`);wrapper 实现三职责——入参语义校验、预算记账(读写 agent_sessions 的计数,调用前扣减,超顶返回结构化拒绝)、轨迹落盘(`agent_steps` 行;evidence_refs 从返回值 id 字段自动抽取;args 脱敏仅 key 类)
2. `tools/definitions/`:注册全部 read 工具(数据 3 + 计算 4 + 检索 2 + 组合状态 4:get_issuer_snapshot/list_alerts/list_research_sources/get_run_status)+ think。fn 一律薄封装调 services
3. `tools/faces.py`:FACE_META_AGENT / FACE_RESEARCH / FACE_RECIPE 声明式清单(delegation/出口工具本阶段注册占位、face 引用,P6/P7 补 fn)
4. `apps/api/main.py`:FastMCP 挂 `/mcp`,server 名 `exposure-workbench`,按 face 暴露工具(MCP tool schema 由注册表 json_schema 机械生成)
5. 会话管理最小件:`services/agent_session_service.py`(create/get,预算状态在行上)

**验收**:
- [ ] **用真实 MCP client 验收**(如 Claude Code 连 `http://localhost:8103/mcp`):list_tools 见到 FACE_META_AGENT 工具集;调 `get_fact_series(NVDA revenue)` 返回带 fact_ids 的序列
- [ ] 每次 MCP 调用后 `agent_steps` 自动出现对应行,evidence_refs 已抽取
- [ ] 预算测试:会话预算设 3,第 4 次调用收到结构化拒绝(HTTP 200,业务错误体),agent_steps 记录被拒调用
- [ ] 单测:wrapper 三职责各自独立可测(fake fn 注入);evidence_refs 抽取器对四种 id 前缀
- [ ] `compute_change` 经 MCP 调用 → calc_ledger 落行且 `invoked_by=<session_id>`

**禁止**:任何工具 fn 里写业务逻辑(必须调 service);SQL/eval 类工具。

---

## P6 — 任务类型 + 研究会话 + 提交门(1.5d)

**范围**:M8 全部;M6 全部;M7/M9 全部。

**任务**:
1. `workflow/readiness_workflow.py` + handler + task type `company_readiness`:6 机械步串行,`_StepContext` 落事件;已 ready 各步秒过;`skip_market_refresh` 支持(时间线标 skipped-by-request)
2. `providers/tavily_*.py` + `services/research_search_service.py`:落 `research_sources`(run 内按 url 去重);注册 `search_external_search`(delegation,reason 必填,budget_key=external_search)
3. `agents/research_session.py`:分析 subagent 会话循环——OpenAI tool-calling,工具面 = FACE_RESEARCH 经 MCP client(worker 进程连 API `/mcp`);系统 prompt 只写角色与证据纪律的"为什么"(≤40 行,禁止行为规则清单)
4. `tools/definitions/submit_brief.py`:六块结构 schema(五块 citations[] 必填,open_questions 豁免);fn 内同步校验 citations ∈ 会话 Evidence Trail ∩ DB;拒绝时返回具体到 id 的结构化错误;2 次重提耗尽 → 会话失败
5. `workflow/issuer_research_workflow.py` + handler + task type `issuer_research`:readiness 前置(未 ready 先跑)→ 会话 → finalize(Evidence Trail refs 物化进 evidence_packs;issuer_briefs 落库)
6. `services/research_run_service.py`(照抄 exposure_run_service 模式)+ REST wrapper `POST /api/research-runs`(同 company 活跃 run 冲突 409+现有 run_id)+ `GET /api/research-runs/{id}`
7. worker `_get_handler` 注册两个新 type;`skip_external_research` = face 裁剪实现

**验收**(live,NVDA):
- [ ] `POST /api/research-runs {ticker:NVDA}` → run completed;workflow_events 时间线三段结构清晰;`research_runs.agent_session_id` 非空
- [ ] `issuer_briefs` 一行:五块每块 citations 非空;**逐一抽查 5 个 citation id,DB 均存在且与正文语义相符**
- [ ] evidence_packs.pack(refs 清单)⊆ 该会话 agent_steps 的 evidence_refs 并集(脚本断言)
- [ ] 提交门单测(不用 LLM,直接调 fn):合法提交过、编造 id 拒、缺 citations 字段被 schema 拒
- [ ] 预算测试:external_search 设 1,会话中第二次搜索被拒且会话能继续走向提交
- [ ] 重复 POST 同 company → 409;首次 run 后再 POST(前次已完成)→ readiness 各步秒过(时间线 duration 证明)
- [ ] 失败路径:临时置空 TAVILY_KEY 且不带 skip → 会话内该工具报错,agent 仍可提交(confidence_notes 如实说明)——检查 Brief 里没有编造的外部信息

**禁止**:EvidencePackService/组装器;query 模板;score 阈值过滤。

---

## P7 — Meta-Agent + respond 门(1d)

**范围**:M10 的 agent 半边。

**任务**:
1. `agents/meta_agent.py`:对话循环(FastAPI 进程内,in-memory MCP client,FACE_META_AGENT);delegation 全部非阻塞
2. 注册 delegation fn:`ensure_company_ready` / `start_issuer_research` / `start_exposure_run`(reason 必填,入队即返 run_id/task_id)
3. `tools/definitions/respond.py`:会话唯一出口;citations 校验同提交门(1 次重试);`citations=[]` 合法
4. API:`POST /api/agent/sessions`(新会话)、`POST /api/agent/sessions/{id}/messages`(发消息,同步返回 respond 结果)、`GET /api/agent/sessions/{id}`(消息+steps,轮询用)

**验收**(live):
- [ ] 结构化问答:"NVDA 近四个季度营收增速?"→ respond.citations 含 calc_id,数值与 P4 台账一致
- [ ] filing 问答:"最新 10-K 里管理层怎么描述数据中心需求?"→ citations 含 chunk_id,抽查原文相符
- [ ] 未就绪路径:问一家未 ready 的公司(如 JPM)→ agent 委托 ensure_company_ready 并如实告知(轨迹可见 delegation 步),**而非**编造回答
- [ ] 委托路径:"给我一份 NVDA 风险简报" → start_issuer_research 被调、返回 run_id、respond 引导查看进度
- [ ] respond 门单测:编造 citation 被拒重试;两次仍编造 → 会话该轮 failed(消息可见错误)
- [ ] 跨公司:"对比 NVDA 和 MSFT 毛利率"(两家均 ready)→ 多次工具调用组合,citations 覆盖两家 calc_id

**禁止**:阻塞等待 run 完成;系统 prompt 写行为规则清单;多活跃会话管理。

---

## P8 — Observability API + UI(1.5d)

**范围**:M11 读取面;M13 全部。

**任务**:
1. `GET /api/evidence/{id}`:前缀路由解析器(fact_/chunk_/calc_/src_/alert_),统一信封 {type, 本体, provenance, 上游链接}
2. 会话/轨迹 API 补全(P7 已有主体);成本汇总 SQL 视图 ×2(session/run)
3. UI 全局组件:CitationChip+EvidenceDrawer(只认 /api/evidence)、RunTimeline(参数化现有时间线组件)、AgentTrace(双色:tool_call/delegation 实线,think/respond 虚线)
4. `/issuer/[ticker]` 五 tab:Snapshot / Financials(台账行,表格+CSS 迷你图,每数字带 chip)/ Filings(Item 浏览器,读 sections)/ Research(来源列表)/ Brief(六块+chips+页脚 token/调用数+时间线入口);未就绪状态给 [Load data] 按钮
5. 全局 Chat 面板:右侧可收起;跨页同会话(session_id 存 localStorage,刷新恢复);**"+新会话"按钮**;进行中轮询 agent_steps 逐条显示工具调用
6. `page.tsx` 加 [Investigate] 入口(持仓行/issuer 行/告警行,`is_investigable` 控制;仅此改动)
7. `lib/api.ts`/`types.ts` 追加

**验收**(浏览器走查脚本,逐条截图或录屏):
- [ ] portfolio 页 → NVDA 行 [Investigate] → issuer 页;TLT 行无该按钮
- [ ] 触发 research run → RunTimeline 实时推进 → Brief tab 渲染,点任一 chip → 抽屉穿透到 fact/chunk/calc/src,chunk 的 SEC 链接可跳
- [ ] Chat:提问 → 面板逐条显示进行中工具调用 → 回答带 chips;切到 issuer 页会话不断;"+新会话"生效;刷新恢复原会话
- [ ] Financials:每个数字有 chip;JPM 的 gross_margin 显示为缺(不是 0)
- [ ] 失败呈现:人为断网跑 readiness → 时间线红色 + error 原文;skip 参数步显示灰色 skipped
- [ ] `grep -rn "if.*severity\|if.*breach" apps/web --include=*.tsx` 无业务判断新增(样式映射除外)

**禁止**:图表库;WebSocket;重构 page.tsx;暗色/移动端打磨。

---

## P9 — 全量验证 + 加固(0.5d)

**任务与验收合一**:
- [ ] 8 家股票逐一 `ensure_company_ready` 全绿;每家 Financials tab 有数;记录每家 facts/sections/chunks 计数表到 `docs/spikes/P9_COVERAGE.md`
- [ ] 第二家公司(选 AAPL)完整 research run → Brief 合格(同 P6 抽查标准)
- [ ] 架构 grep 审计(全部为空):
  - `grep -rn "edgar\|yfinance\|tavily" src/exposure_workbench/{analytics,tools}/ apps/api/routes/`(providers/services 之外无第三方)
  - `grep -rn "_mock_output\|mock_mode" src/` 仅现有 direct_llm_agent 一处
  - 新 services 中无 UPDATE/DELETE 于证据四库
- [ ] 幂等三连:同一公司 readiness ×3、recipe ×2、research run ×2(前次完成后),行为均符合 MODULE_NOTES M8 幂等地图
- [ ] 回归终验:exposure run 11 步全绿;243..不适用——`pytest -m "not live"` 全绿,live 套件全绿各一遍
- [ ] 文档收尾:README 更新 Quick Start(真实数据 seed、新 env);TARGET_ARCHITECTURE v3 "留白"清单核对,已定的划掉

---

## 附:执行中的升级路径

- **计划与架构文档冲突** → 架构文档赢,停下问用户
- **架构文档内部矛盾 / 现实不可行**(如 EDGAR 字段缺失导致某设计不成立)→ 停下问用户,不自行发明 fallback
- **P2 spike 结论是 edgartools 不可用** → 停下,连同候选方案评估一起交用户拍板
- 每个"用户检查点"(P1 CIK 表、P2 复用盘点、P2 parse 拍板)未确认前,不进入依赖它的阶段
