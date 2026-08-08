# Target Architecture — Portfolio Exposure Analytics + Issuer Intelligence

> **版本**:v3(2026-07-23,模块讨论完成后回写;v2 → v3 修订清单见文末附录 B)
> **性质**:目标架构基准文档,记录系统不变量与拓扑。逐模块设计细节见 [MODULE_NOTES.md](MODULE_NOTES.md)(M1–M13)。
> **关系**:现有系统的架构记录在 [ARCHITECTURE.md](ARCHITECTURE.md)。现有 `ExposureWorkflow`、分析层、worker、事件时间线**全部保留**,本架构是在其上加层,不是替换。

---

## 0. 骨架

**用户只面对一个 meta-agent;一切重活由后台任务承担、一切轻触发由前端按钮直连 wrapper;所有 LLM 生成的工具调用走唯一的 MCP 面;所有执行痕迹与证据引用由确定性层自动记录,UI 全程可穿透。**

### 全局三规则(一切模块设计的前提)

- **规则 A — Fail loud at the boundary**:外部依赖缺失或校验失败 = 该步 failed、时间线可见、run 停止。无 mock、无静默降级、无"陈旧数据顶上"。想跳过某能力 = 显式参数(schema 可见、审计留痕)。
- **规则 B — 用 schema 消灭解析规则**:LLM 输出一律 tool-call 强制形状;引用靠必填 `citations[]` 字段结构性保证。不写 parse-fallback 补丁链。
- **规则 C — 正交能力替代路由规则**:不写问题分类器。工具面正交,agent 的工具选择即路由,路由是涌现行为不是代码。
- 澄清:规则 B/C 反对的是 **LLM 调用路径上的规则补丁**;确定性层内部的映射表/校验逻辑是正交模块的实现细节,不在此限。

## 1. 用户功能地图与三能力分组

| # | 功能 | 形态 | 时延 |
|---|---|---|---|
| F1 | 组合监控(现有 ExposureWorkflow) | 按钮/定期 | 分钟 |
| F2 | **即问即答**(日常主体):任意粒度、跨证据类型、跨公司 | 对话 | 秒级 |
| F3 | 深度调查(低频正式动作)→ Issuer Risk Brief | 对话/按钮,后台 | 分钟 |
| F4 | 证据浏览(filing 原文/财务趋势/来源) | 纯 UI,无 agent | 即时 |
| F5 | 数据就绪(通常隐式) | 委托/按钮 | 分钟 |
| F6 | 审计监测(轨迹/引用穿透,横切) | 纯 UI | 即时 |

三组正交能力,**pipeline 只是组合之一**:

```
能力 A:数据就绪(机械,幂等,无判断)——摄取/索引/行情/recipe 基线,本质是"状态"
能力 B:证据工具面(只读+计算)——ready 后任何时刻可用,不需要任何 run
能力 C:委托研究会话(判断,产 artifact)——唯一天然 run 形状的东西
组合:F2 = B(未 ready 时先委托 A);F3 = A + C;F1/F4/F6 无 agent 也完整
```

## 2. 总图

```
                    ┌──────────────── 用户 ────────────────┐
                    │            │                         │
                 对话(唯一 agent 口)   按钮(无 agent)      浏览
                    │            │                         │
                    ▼            ▼                         ▼
┌────────────────────────┐  ┌──────────────┐  ┌─────────────────────┐
│ Meta-Agent             │  │ REST Wrappers │  │ 只读 API             │
│ (FastAPI 进程内循环)     │  │ 纯参数校验+入队│  │ (/api/evidence/{id} │
└──────────┬─────────────┘  └──────┬───────┘  │  等,零判断)         │
    每 turn 建对                    │          └─────────────────────┘
           ▼                       ▼
┌─────────────────────┐   ┌──────────────────────────────────────┐
│ in-memory MCP 对     │   │ Task Queue(tasks 表)→ Worker        │
│ client ↔ server      │   │  ├ exposure_update(现有,不动)       │
│ build_mcp_server(    │   │  ├ company_readiness(能力 A,recipe) │
│  registry, face,     │   │  └ issuer_research(能力 C):         │
│  session, identity)  │   │     readiness 前置 → 分析 subagent    │
│ 参数化构造;所有 LLM   │   │     (worker 进程内每 run 建对,        │
│ 生成的调用            │   │      同一 in-memory 通路)→ finalize   │
└──────────┬──────────┘   └──────────────────┬────────────────────┘
           │  tools/call → invoke()          │
           ▼                                 │
┌──────────────────────────────────────────┐ │
│ Registry Wrapper(唯一关口)               │◀┘ recipe/wrapper 代码直调 fn
│  入参语义校验 / 预算记账 / 轨迹+台账自动落盘 │
└──────────┬───────────────────────────────┘
           ▼
   tools fn → services(ingestion 写 / query 读)→ providers / analytics / db

侧门(local-dev debug):stdio 入口 = 同一构造器,MCP_STDIO_USER_ID 显式身份
══════════════════════════════════════════════════════════════════════
 Observability Plane(横切):agent_sessions/messages/steps + workflow_events
 + calc ledger + evidence 四库 ──▶ Chat 面板 / Agent Monitor / Run 时间线 / 引用抽屉
══════════════════════════════════════════════════════════════════════
```

## 3. Code 层:目录即架构,import 方向即法律

```
src/exposure_workbench/
  providers/     外部世界唯一入口(EDGAR/yfinance/Tavily/embedding),DTO 出境,
                 第三方对象不上浮
  services/      摄取(写库)与查询(读库)分离;语义校验的家
  analytics/     纯函数(现有五模块不动;新增 period_ladder 等确定性组件)
  workflow/      确定性编排(ExposureWorkflow 不动;readiness/research 两个新编排)
  agents/        meta-agent 循环 + 分析 subagent 会话。只 import tools 客户端与 llm
  tools/         ToolRegistry:工具五元组 + wrapper(强制与追踪的唯一关口)
  llm/           chat_complete + embed_texts,provider 可插拔
  db/            models + session(现有)

apps/
  api/           FastAPI:REST wrappers + 只读 API
  mcp/           stdio 调试门入口(同一 build_mcp_server 构造器)
  worker/        任务轮询(现有)+ 新 handler 注册
  web/           Next.js 薄客户端
```

**依赖单向规则**(code review 硬卡):`apps → tools → services → providers/db`;`agents → tools(经 MCP)`;`analytics` 不依赖任何上层;禁止 routes/agents/analytics/tools 中 import edgar/yfinance/tavily。

## 4. Database 层:四区 + Runtime 区

| 区 | 表 | 写入者 | 纪律 |
|---|---|---|---|
| **Raw** | companies, filings, filing_documents, market_prices, factor_prices | ingestion services | 带 provider/retrieved_at;**append-only** |
| **Normalized 证据** | filing_sections, filing_chunks(+embedding), financial_facts, research_sources | ingestion/index services | 引用锚点;raw_concept 与 normalized_metric 并存;**append-only** |
| **Calc Ledger** | calc_ledger(v2 之 derived_financial_metrics 更名重定性) | 计算原语经 wrapper 自动写 | 每次计算一行,含输入 refs/操作/参数/原语版本;**append-only** |
| **Artifact** | daily_reports(现有), issuer_briefs, evidence_packs | agents 经提交门落库 | 带 llm_model/tokens/confidence;LLM 产物只能落这一区 |
| **Runtime** | tasks, exposure_runs, research_runs, schedules, workflow_events, agent_sessions, agent_messages, agent_steps | 框架自动 | 轨迹 append-only |

### 铁律

1. **LLM 产物只落 Artifact 区**;Raw/Normalized/Ledger 对 agent 只读。LLM 产物永不回流成证据。
2. **证据四库(fact/chunk/calc/source)禁 UPDATE/DELETE**——行级稳定是"轨迹存引用不存副本"的地基;重述/修正一律走新行。
3. 文本证据、数字事实、计算结果、生成报告是四种数据类型,分表,禁止宽表合并。
4. 每行证据带出处;每行计算带输入 refs 与原语版本。

### 相对现有 schema 的改动

- `workflow_events.run_id` **去外键**(exposure/research 两类 run 共用时间线管道)
- Postgres 镜像换 `pgvector/pgvector:pg16` + `CREATE EXTENSION vector`
- `research_runs.agent_session_id` 列(run ↔ 会话双向可查,两层时间线连接点)
- `market_prices`/`factor_prices` **种子退役全库真实化**(yfinance 拉真实历史;合成与真实数据不得混一序列)
- schema 双份维护(init.sql + models.py)照旧,新表两处同步 + 幂等补丁脚本
- 关键新表 DDL:`calc_ledger{id, company_id, operation, params JSONB, result JSONB, input_refs JSONB, primitive_version, invoked_by, created_at}`;`evidence_packs.pack` 为 **refs 清单**(非 JSON 快照);其余(companies/filings/…/agent_steps)沿用 v2 草案,以 models.py 实现为准

## 5. Agent 层

### 拓扑:1 + 1,树深封顶 2

| 实体 | 性质 |
|---|---|
| **Meta-Agent**(唯一对话实体) | FastAPI 进程内循环,经 MCP client 连工具面;长驻会话 |
| **分析 subagent**(每 research run 一个会话) | tool-calling、预算硬顶、**非对话**;探索者即写作者,以 submit_brief 收尾;face 无 delegation → 不能再委派,**树深架构性封顶为 2** |

**不变量:所有 agent 自由度流经同一 ToolRegistry,受同一预算强制,落同一份轨迹。**

### Meta-Agent 禁区(FIXED,架构强制不靠 prompt)

| 禁区 | 强制点 |
|---|---|
| 数值计算 | 数字只能引 calc_id/fact_id,心算值无 id 可引 |
| 直接 SQL / 触库 | agents 不 import db;工具面是全部视野;**无 SQL/eval 工具** |
| 直接触网 | providers 只被 ingestion services 引用 |
| inline 执行长任务 | delegation 只入队(非阻塞,发起即返 run_id),执行权在 worker |
| 无出处引用 | respond/submit_brief 提交门校验 citations ∈ Evidence Trail |

系统 prompt 只写角色与证据纪律的"为什么",不写行为规则清单——prompt 里堆规则 = 承认架构没堵住。

### 双触发汇流

按钮路径(REST wrapper,零判断零 LLM)与对话路径(delegation 工具)汇于同一 `tasks` 表;审计面同构,只差 `triggered_by`(`manual` / `agent:<session_id>`)。

### 任务类型(worker 执行)

- **`company_readiness`(能力 A)**:resolve_company → ingest_filings(每 filing 单事务)→ extract_facts → index_filings → refresh_market(可显式 skip)→ standard_recipe。全机械全幂等,已 ready 整体秒过;幂等键详见 MODULE_NOTES M8。
- **`issuer_research`(能力 C)**:readiness 前置检查 → 分析 subagent 会话 → finalize(物化 Evidence Trail)。判断步刻意不幂等——重跑就该产生新判断。
- **singleflight 在共享 ingest 上,不在 run 上**(★ V2-H 更正,原文写「同 company 同时一个活跃 research run」)。锁按 company 加在 `run_readiness` 内(Postgres advisory lock),两个租户同时研究同一公司只 ingest 一次;research run 本身是**每用户每 issuer 一个活跃**(冲突 409 + 返回**该用户自己的** run_id)。理由:贵的是 ingest,而 ingest 产出的是共享证据;brief 是 RLS 私有的每用户产物,全局锁会让用户 B 不是「晚点拿到」而是**永远拿不到**,并且拿回一个属于别的租户的 `rrun_` id(随后 404)= 拒绝 + 存在性预言机。同一把锁顺带盖住 `company_readiness`——它今天连守卫都没有。
- skip 参数 = **工具面裁剪**(组装会话时不给该工具),不是步内 if——能力边界即物理边界。

### 提交门(规则 B 的完全体)

- `submit_brief(六块结构,每块 citations[] 必填;open_questions 唯一豁免)`:提交时同步校验每个 citation ∈ 本会话 Evidence Trail 且 ∈ 数据库;结构化拒绝 + 预算内修正重提(2 次);耗尽 = run failed。
- `respond(text, citations[])`:meta-agent 会话唯一出口,同一门机制轻量版(1 次重试);`citations=[]` 合法,**但凡引了必须是真的**。
- 被消灭的错误类别:无引用断言(字段必填,生成不出来)/ 编造 id(门前拦死)/ JSON 形状错(tool-call 强制)/ 心算数字(无 id 可引)。

### Evidence Trail(v2 之 EvidencePack 重定义)

不是事先组装的输入契约,而是**会话实际触达证据的 refs 集合**——从 agent_steps.evidence_refs 自动导出,run 收尾物化进 `evidence_packs`。回答的是"agent 生成 Brief 时实际看了什么"(机器记录),一致性由证据库不可变性保证。

## 6. Tool 层:ToolRegistry

工具五元组 `{name, json_schema, fn, class: read|delegation|reflection, budget_key}` 注册一次;wrapper 自动做入参语义校验、预算记账(调用前扣减)、轨迹落盘(evidence_refs 自动抽取)。

### 工具清单

| 类 | 工具 | 说明 |
|---|---|---|
| 数据原语(read) | `list_available_data` / `get_fact_series` / `get_price_series` | 序列已经 period_ladder 对齐,agent 无"自己对期次"的机会;返回带 fact_id |
| 计算代数(read,落台账) | `combine_series(add/sub/divide)` / `compute_change(yoy/qoq/pct/abs)` / `compute_stat(cagr/avg/min/max/std)` / `compute_window_return` | **封闭代数**:表达力靠组合不靠加工具;增删原语是架构评审动作 |
| 检索(read) | `search_filing_passages`(找位置,默认全 filing 覆盖+filters 收窄)/ `get_filing_section`(读全文) | 正交而非冗余:对抗"RAG 只看碎片"偏差 |
| 组合/状态(read) | `get_issuer_snapshot` / `list_alerts` / `list_research_sources` / `get_run_status` | 组合敞口/告警是普通证据,带 id 可引用 |
| delegation | `ensure_company_ready` / `start_issuer_research` / `start_exposure_run` / `search_external_research(query, reason)` | reason 必填(判断留痕);外部搜索仅在 FACE_RESEARCH |
| reflection | `think` | 无副作用,只写轨迹 |
| 出口(门) | `respond`(meta)/ `submit_brief`(research) | §5 提交门 |

### 工具面 = 声明式配置

```
FACE_META_AGENT = read 全集 + delegation{ensure_company_ready, start_issuer_research,
                  start_exposure_run} + think + respond
FACE_RESEARCH   = read 全集 + search_external_research + think + submit_brief(无 delegation)
FACE_RECIPE     = 数据+计算原语 fn 直调(无 LLM 无预算,只留台账)
```

"agent 能干什么"的答案在一处配置;face 即建 server 时传入的 registry,能力是"物理不存在"而非 in-loop if;stdio 调试门同一构造器,无特权通道。

### 预算(数值全在配置)

会话总预算 40 次/会话;external_search 子预算 5 次/run;submit_brief 重提 2 次;respond 重试 1 次。超顶 = 工具结构化拒绝,不留给 agent 自觉。

## 7. LLM 层

- `llm/client.py` 两个动词:`chat_complete()` + `embed_texts()`(embedding:OpenAI text-embedding-3-small,1536 维);provider 可插拔,OpenAI 先行
- **LLM 不算数、不触库、不触网**;web 内容经 Tavily 落库后作为带引号的数据供读(不可信输入不拼指令区)
- **无 key = fail loud**(v2 的"mock 降级常驻"废除;现有 DirectLlmAgent 的 mock 是旧代码遗留,不复制到任何新代码)

## 8. MCP 层:双轨规则

> **Agent 面 = MCP,唯一;代码面 = fn 直调;两面共穿一个 wrapper。**

- 凡 **LLM 生成**的工具调用一律走 MCP——meta-agent 每 chat turn、research subagent 每 run,以 in-memory transport 建一对 client-server(`build_mcp_server(registry, face, session, identity…)` 参数化构造);face 与租户身份在建对时绑定、call_tool 内显式重绑,对随 turn/run 消亡
- 凡**确定性代码**的调用(recipe/REST wrapper)直调 fn——代码无"生成调用"动作,不存在需生成时堵的错误类别
- 与 sm-master 分裂教训的区别:那是"两条 **agent** 通路、两套强制";这是"一条 agent 通路 + 一条代码通路、**一套强制**"(wrapper 是共同关口)
- 内部走 MCP 买到:门面因日常流量不烂、schema 诚实由协议层强制曝光、审计口径唯一;传输不改变记录内容由常驻 parity 测试钉死
- 侧门:stdio 入口 = local-dev debug 门,同一构造器,MCP_STDIO_USER_ID 显式身份(users 表校验),借 app_rls factory,无特权通道

## 9. Observability Plane(金融级审计面,横切)

1. **事实由机器记,叙述由 agent 记,分色呈现**:工具调用由 wrapper 自动落 `agent_steps`(实线);think/respond 文本是 agent 自述(虚线)。
2. **追踪沉在 transport 之下**:落盘点在 wrapper,三种驱动(内部 agent/stdio 调试门/按钮)产生同构轨迹。
3. **轨迹存引用不存副本**:agent_steps 存工具名/脱敏入参(MVP 只脱 key 类)/一行摘要/evidence_refs/耗时/token;完整证据体在四库,append-only 保证 refs 永久有效。
4. **每个事实输出可双击穿透**:全系统一个解析器 `GET /api/evidence/{id}`(前缀路由 fact_/chunk_/calc_/src_/alert_,统一信封含 provenance 与上游链接);chip/抽屉/Brief/Monitor 共用一个组件。
5. **成本与模型版本入账**:token 行级落库,session/run 汇总 = SQL 视图;账全、看板薄。
6. **两层时间线,监测粒度与自由度成正比**:外层 workflow_events(机械步无内层);判断步点开进 agent_steps 轨迹。

## 10. UI 层(薄客户端)

- 零业务逻辑零判断;现有 page.tsx 只加 [Investigate] 入口不重构;新增 `/issuer/[ticker]` 五 tab 工作区(Snapshot/Financials/Filings/Research/Brief),组件化
- 三个全局组件:CitationChip+EvidenceDrawer(只认 /api/evidence)、RunTimeline(两类 run 共用)、AgentTrace(chat 内嵌 + 回看共用)
- **Chat 全局常驻面板**:跨页同一会话(session_id 存 localStorage,刷新恢复),**"+新会话"按钮显式开新**;进行中透明 = 轮询 agent_steps 逐条显示工具调用,非转圈动画
- 规则 A 的 UI 形态:failed 红+error 原文、skipped-by-request 灰、未就绪给 [Load data];**UI 从不美化失败**
- MVP:表格+CSS 迷你图,不装图表库;全站 2s 轮询,无 WebSocket

## 11. 设计脊柱(五条不变量)

1. **单自由体面向用户**:唯一对话实体是 meta-agent;分析 subagent 非对话且树深封顶 2;wrapper 是管道
2. **一条 agent 通路(MCP)+ 一条代码通路(fn),一套强制(wrapper)**:工具定义、预算/引用/幂等校验、审计落盘各只有一份
3. **证据单向流 + 全程可穿透**:providers → raw → normalized → ledger → agent → artifact;agent 对上游只读;每跳引用 UI 可双击到底
4. **委派而非执行**:agent 对重活只有入队权,执行权在确定性 worker;机械归 recipe,判断归 agent 且必留痕
5. **Fail loud,无降级第三态**:产物要么合格要么可见失败;跳过是显式参数不是隐式退路

## 12. 已定 / 留白

**已定**(变更需回到本文档修订):全局三规则;三能力分组与两个新任务类型;1+1 拓扑与树深封顶;封闭计算代数(四原语);提交门机制(respond/submit_brief);MCP 双轨规则;证据四库 append-only 与 refs-not-copies;种子退役全库真实化;工具面声明式配置;预算数值进配置;全局引用解析器;Chat 全局面板与"+新会话"。

**留白**(实现期再定):M2 parse 方案(需实测 + 盘点用户已有项目/skill,见 MODULE_NOTES M2);chunk 参数(与 parse 捆绑评估);Anthropic 通道时机;向量索引切 HNSW 阈值;独立 MCP 进程时机;成本仪表盘。

---

## 附录 A:与现有系统的对接清单(只加不改的边界)

| 现有资产 | 角色 |
|---|---|
| ExposureWorkflow + analytics 五模块 | 原样保留,F1 的生产者 |
| worker 轮询 + task_service | 唯一执行引擎,+2 个 handler 注册 |
| workflow_events + _StepContext + 时间线 UI | 审计面既有半壁,去 FK 后覆盖两类 run |
| market_data_service(查询侧) | 不动;新 ingestion 写它读的表 |
| DirectLlmAgent / daily_reports | 旧代码原样保留(含其 mock);新代码不复制该模式 |
| 三栏工作台 UI | 保留;加入口 + 新路由 + 全局 Chat/引用组件 |

## 附录 B:v2 → v3 修订清单

1. "mock 降级常驻"与"validate_brief 降级为 confidence flag" **废除** → 全局规则 A(fail loud)
2. 1+N+0(subagent 无工具单发)→ **1+1**(分析 subagent tool-calling、预算硬顶、非对话、树深封顶 2);不变量改述为"所有 agent 自由度流经同一 ToolRegistry"
3. derived_financial_metrics(预算指标表)→ **calc_ledger**(append-only 计算台账);固定指标清单让位于封闭计算代数 + recipe
4. EvidencePack(输入契约)→ **Evidence Trail**(轨迹导出的审计产物,refs 清单)
5. FilingQAService **取消**(QA = meta-agent + 检索工具);EvidencePackService **取消**
6. 14 步 IssuerResearchWorkflow → **company_readiness + issuer_research 两个任务类型**(三能力 A/B/C 重构,pipeline 只是组合之一)
7. MCP 从"第三个消费者/门面"升级为 **agent 面唯一通路**(双轨规则);独立 M12 模块取消并入 M10
8. respond 成为工具(chat 与 Brief 共用提交门);外部搜索的 query 判断归 agent(无确定性搜索步)
9. 种子行情数据退役,全库真实化;skip 语义统一为显式参数/工具面裁剪
10. workflow_events 步序表述、agent_sessions 与 research_runs 关联列等细节按 MODULE_NOTES 为准

---

## 13. 租户拓扑(V2 多用户;2026-07-24)

单机 demo 升级为多用户产品:用户注册/登录(Clerk)、创建/上传自己的 portfolio、chat 与分析私有。核心判断是**数据分三层**,隔离强制点沉到数据库(Postgres RLS),与 §5「所有 agent 自由度流经同一 ToolRegistry」同构——都是把强制沉在调用方之下。

### 13.1 三层归属

| 层 | 表 | 归属 | 理由 |
|---|---|---|---|
| **公司层(共享)** | companies, filings, filing_*, financial_facts, research_sources, **calc_ledger**, market_prices, factor_prices, security_master | 无 owner,全局读 | SEC/市场公共事实与其确定性派生;按用户复制 = 浪费 + 不一致。calc_ledger 只含公司级确定性计算(零用户数据),共享 = 纯去重 |
| **用户层(私有)** | users, portfolios, positions, exposure_runs(及全部子表), agent_sessions/messages/steps, research_runs, **issuer_briefs**, evidence_packs | owner + RLS | 用户活动与含用户输入的产物。issuer_briefs 私有:portfolio_implications 引用用户持仓,是含机密输入的分析物 |
| **Demo(公开只读)** | demo 组合 port_001、demo 的 NVDA/AAPL brief | `is_public=true` | 匿名访客的展示面(读公开、写门禁);新用户登录后亦可见 |

### 13.2 强制点(单一,fail-closed)

- 运行时用**非 owner 角色 `app_rls`**(owner 天然 bypass RLS,是头号坑);无 DELETE 权限,append-only 在权限层顺带硬化。
- owner 列只在**五张主表**(users/portfolios/agent_sessions/research_runs/issuer_briefs);子表一律 `EXISTS(父表)` 级联,不加冗余 owner。
- 每事务 `SET LOCAL app.user_id`,单一 choke point;缺失 → `current_setting` 为 NULL → 只放行 is_public(fail-closed:忘设身份 = 看不到数据,不泄)。
- **安全归 RLS、业务语义归显式谓词**:service/route 里的 owner 过滤只用于"哪个是我的组合"这类语义,标注 `# semantic, not security`;绝不作为隔离手段。

### 13.3 身份

Clerk 外包注册/登录/OAuth/MFA;后端唯一 auth 代码 = 一个 dependency(`auth/clerk.py` JWKS 验 RS256 → `auth/context.current_user_ctx`),与 `tools/registry._session_ctx` 是**两个平行 contextvar**(前者租户、后者工具会话,永不合并)。写路径 `require_user` 门禁 + 落 owner;读路径不加门禁,可见性由 RLS 决定。

### 13.4 三平面并发(V2-E)

- Worker:`FOR UPDATE SKIP LOCKED`(已有)+ lease/requeue(治 stuck-run)。**重投是白名单,不是默认**——实测只有 `company_readiness` / `market_data_sync` 全链 upsert 因而幂等;`exposure_update` 的 `_persist_outputs` 是裸 INSERT 打在五个 `UNIQUE(run_id…)` 上,`issuer_research` 会在烧完整轮 LLM 预算**之后**才撞 `issuer_briefs UNIQUE(research_run_id)`。这两类 lease 过期一律把 task 与 run 双双标 failed,让用户显式重跑——比伪装成功或炸在第二次写入诚实,也解开 research 的 `ActiveRunExists` 永久 409 死锁。
- Agent:每 session 单飞行 turn(`turn_started_at` + 条件 UPDATE 认领,取值够宽 + 到期自愈,**无心跳/续租线程**);research per-company singleflight **落在共享 ingest 上**(★ V2-H 更正,原文写「保持全局」):`ingest_lock_service` 的 advisory lock 按 company 加在 `run_readiness` 内,同公司只 ingest 一次;research run 本身按用户,详见 §5。锁走**专用连接**而非调用方 session(step_context 每步进出都 commit,连接会还回池),且靠连接断开自愈——无 lease、无心跳、无 reaper,同 §0.5「取值够宽 + 到期自愈」。
- 预算:**按用户动作计数的 `usage_daily` 表 + 五个扣费点**(★ V2-H:原为两个。`task_service.create_task` 覆盖四类 task,`POST /agent/sessions/{id}/messages` 扣 chat turn,`portfolio_service.create_portfolio` 扣建仓,`POST /api/portfolios/{id}/upload` 扣重传,`POST /api/agent/sessions` 扣建会话;逐点口径见 IMPLEMENTATION_PLAN_V2 §0.5),user 池与 `_global` 兜底池同表、同事务扣两次,任一超限即整体回滚(因此不需要退款/补偿逻辑)。**不进 ToolRegistry wrapper**:wrapper 只看得见工具调用,而 exposure/readiness/research 各有 REST 路由与 agent 委派**两条平行入口**,wrapper 拦不住路由面。wrapper 内既有的 session 预算(工具调用数/external_search 数)保持不变,与日配额是两个正交维度。

> 分阶段落地(A 身份 → B 组合 → C RLS → D 宇宙 → E 并发/预算 → F 部署)见 [IMPLEMENTATION_PLAN_V2.md](IMPLEMENTATION_PLAN_V2.md)。
