# Architecture As Built — 2026-09-01

> **性质**:现状快照。不变量与目标拓扑见 [TARGET_ARCHITECTURE.md](TARGET_ARCHITECTURE.md)(v3),逐模块设计见 [MODULE_NOTES.md](MODULE_NOTES.md)(M1–M18),部署与租户见 [PRODUCTION.md](PRODUCTION.md)。本文只回答"今天有什么、怎么连、能做什么"。
> **规模**:`src/` ~21k 行 Python、`apps/web` ~3.3k 行 TS;**1560 offline** 测试;V15(桌面)已落地,见 §7。线上 https://desk-for-one.com。

---

## 1. 一句话

**用户只面对一个 meta-agent;它能调 32 个工具;每一个数字都能回溯到账本里的一行;模型不写数字,只写桌面上的名字(V15);算错的类别由代码消灭,选错的类别由知识降低,指错的类别由结构消灭,剩下的交给门拒绝。**

四条设计律贯穿一切(TARGET §0):**A** 边界处大声失败,无静默降级;**B** 用 schema 消灭解析规则;**C** 正交能力替代路由规则,不写问题分类器;**D**(V9 起)世界结构进代码、方法定义进数据、分析交给智能,**不存在发行人行为规则**。

## 2. 拓扑

```
 浏览器(Clerk 登录)
   │
   ▼
 ┌──────────────────── exposure-web (Next.js) ────────────────────┐
 │  /            组合工作台:run 摘要 · 持仓 · 告警 · 时间线 · 引用抽屉 · 对话面板   │
 │  /issuer/[t]  发行人页:Financials · Filings · Brief · Research 四个 tab · 对话   │
 └────────────────────────────┬────────────────────────────────────┘
                              │ REST
                              ▼
 ┌──────────────────── exposure-api (FastAPI) ────────────────────┐
 │  只读 API(证据/发行人/组合/run)· 写入口(组合上传/克隆/入队)· /agent (meta-agent 循环在此进程内)  │
 │  quota 记账 · Clerk 校验 · 每 turn 铸内部 bearer                                       │
 └──────┬─────────────────────────────────┬───────────────────────┘
        │ 入队 (tasks 表)                   │ bearer + JSON-RPC (仅 compose 内网)
        ▼                                 ▼
 ┌─ exposure-worker ×3 ─┐        ┌──────────── exposure-mcp ────────────┐
 │  exposure_update      │        │  /mcp/meta      29 工具                │
 │  company_readiness    │───────▶│  /mcp/research  15 工具                │
 │  issuer_research      │        │  中间件:验 token → 绑 user/session/face │
 │  market_data_sync     │        │  Registry wrapper:入参校验·预算·轨迹落盘 │
 │  scheduled_update     │        └──────────────────┬─────────────────────┘
 └──────────────────────┘                           ▼
                                   tools → services → analytics / providers
                                                     │
                                                     ▼
                              Postgres 16 (+pgvector)  app_rls + RLS,35 张表
                              providers:EDGAR(edgartools)· yfinance · Tavily
```

**LLM 调用只发生在 api(meta-agent)与 worker(research 子会话)的循环里**,MCP 门后没有 completion。模型:`gpt-5.4-mini`。

## 3. 数据层(35 张表,四区 + Runtime)

| 区 | 表 | 今天的规模 | 纪律 |
|---|---|---|---|
| **Raw** | companies · filings · filing_documents · market_prices · factor_prices · security_master | 10 家(8 发行人 + HYG/TLT)· 16 份申报 · 15,776 日价 · 6,601 因子价 | append-only,带 provider/retrieved_at |
| **Normalized 证据** | filing_sections · filing_chunks(+embedding)· financial_facts · research_sources | 3,078 chunk · **62,473 事实,其中 8,352 已映射**(`mapping v3`,39 个指标)· 25 条外部来源 | raw_concept 与 normalized_metric 并存;映射不决定存储 |
| **Calc Ledger** | calc_ledger | **25,119 行** | 每次计算一行:操作、参数、输入 refs、原语版本;**V11 起失败也铸行**(`absence.*`) |
| **Artifact** | daily_reports · issuer_briefs · evidence_packs | 10 份 brief | LLM 产物**只**落这一区,永不回流成证据 |
| **Runtime** | tasks · exposure_runs · research_runs · schedules · workflow_events · agent_sessions · agent_messages · agent_steps · usage_daily · users | 26 个 run · 1,273 个会话 · 3,008 步 | 轨迹 append-only |
| **风控配置** | portfolios · positions · risk_limits · risk_alerts · limit_checks · stress_results · factor_attributions · factor_residuals · issuer_exposures · sector_exposures · exposure_metrics | 7 个组合 · 44 个持仓 | `risk_limits` 是 mandate 的唯一真相(M16) |

铁律:证据四库禁 UPDATE/DELETE;重述走新行(`restatement_key = (filing_date, accession)`);租户隔离靠 Postgres RLS(`app_rls` 角色 + `SET LOCAL`),不靠应用层过滤。

## 4. 分析层(`analytics/`,纯函数,13 个模块)

这是 **"世界结构进代码"** 的那一层。V9 的四条公理 + 组合风控的五个既有模块 + V12 的语义表:

| 模块 | 公理 / 职责 | 实证 |
|---|---|---|
| `interval_algebra` | **R1** 流量事实 = 边界图上的一条边;任意窗口 = 带符号路径(Dijkstra)。Q4/H1/TTM 是同一个算法 | Q4 parity 290/290;季度序列 1439/1439、年度 484/484 |
| `containment` | **R3** 求和项不得嵌套;11 条经语料验证的包含边(787 次共现零违反);`cover()` 给出反链 | 六家六种债务形状,零发行人规则 |
| `services/typed_calculator` | **R4** 类型化四则:四种拒绝(不同时点相加 / 重叠区间相加 / 嵌套相加 / 单位类不合);V11 加 `scale` | 43 次真实会话零算术错 |
| `formulas` | **方法定义进数据**:16 个具名度量,带表达式、输入、基准、`family`、`citation`/`authority`、具名替代、`note`;**零阈值**(测试守) | SEC C&DI 103.01/103.02/102.07 |
| `semantics` | **V12**:21 条指标 gotcha(事实+后果)、6 条已验证示例;零数字零阈值(测试守) | 总债务路由 50%→100% |
| `series_ops` / `drawdown` | 序列变换(yoy/qoq/cagr/…);峰谷回撤段检测 | V10 并轨,V8-D |
| `exposure` · `factor_model` · `risk_metrics` · `stress` · `pnl` · `limits` · `limit_defaults` | 既有组合风控:敞口、8 因子回归(750 日窗,VIF 共线标记)、VaR/ES/波动、压力情景、P&L、限额 | ExposureWorkflow 的四个计算步 |

## 5. 服务层(44 个模块)——按写/读/门分

**摄取(写)**:`filing_ingestion`(EDGAR → sections/chunks/facts)· `market_data_ingestion` · `document_index`(embedding)· `concept_mapping`(v3,39 指标;映射永不决定存储)· `security_master` · `research_search`(Tavily)

**查询(读,给工具)**:`fundamentals`(`get_flow` 任意窗口 / `get_balance_sheet` 单时点 / 序列)· `formula`(`evaluate_formula` / `build_panel`)· `calc`(账本记录 + 指标地图)· `series` · `run_reads`(归因/风险态/告警/限额/新鲜度)· `reconcile`(单日分解:两条恒等式 + `factor_share`)· `drawdown` · `filing_retrieval` · `portfolio` · `brief` · `evidence_resolver`

**V11–V12 新增的"诚实层"**:`absence_service`(六种拒绝各铸可引的行,statement 服务端拼,带 `superseded_by` 与逐输入覆盖)· `period_semantics`(财年历从年度事实推;累计申报是指标属性)

**桌面与门(V15)**:`quantities`(唯一拼名)· `table`(声明/构造/加载)· `resolver`(六不变量)· `answer_blocks`(文法与渲染)· `display_conventions`(读者精度,py/ts 双向锁);`numeric_verification` 只剩 v1 散文路径(日报门)(见 §7)

**运行时**:`task`(租约/回收)· `agent_session` · `trace` · `context_budget`(tiktoken 计量,80k 软上限)· `usage`(quota)· `schedule` · `workflow_event`

## 6. 工具面(`tools/`,29 + 15)

面是声明式数据(`faces.py`),缺一个工具即构建错误。**每个工具返回值要么带 id,要么是类型化拒绝**——没有第三态。**V15 起每个工具在注册时声明它的结果把什么放上桌面**(`Tool.evidence`:结果里的 id、run 子表作用域、委派任务),关口据此构造 `result["table"]`——名字 = 读者精度值——并把声明存为该步的 evidence;没有声明的工具(`get_task_status`/`list_risk_limits`/`get_run_freshness`)不产生证据。

| 组 | 工具 | 说明 |
|---|---|---|
| **定位** | `describe_issuer` | 唯一定位工具(V10 三合一)。**V12 起携带知识**:`period_semantics`(财年历、财季是否对齐日历)、每条指标的 `kind`/`windows_filed`/`do_not_add_to`/`superseded_by`/`do_not_combine_with`/`for_a_total_call`/`note`、每个公式的 `family`/`computable`/`missing_inputs` |
| **取数** | `get_flow`(窗口或序列)· `get_balance_sheet`(单时点)· `get_balance_series` | 区间代数直出;不可导出即拒绝,带 `absence_id` |
| **算** | `calculate`(类型化四则,标量或序列)· `series_stat` · `evaluate_formula` · `get_fundamental_panel` | 每一步落账本 |
| **文本** | `search_filing_passages` · `get_filing_section` | 语义检索 / 整节原文,带引用锚 |
| **book 清单(V15)** | `describe_run` · `read_quantities` | book 侧的 `describe_issuer` / `evaluate_formula(name)`:一个 run 持有的全部量按"回答什么"分组(book/concentration/mandate/stress/factor_exposure/attribution/risk/counts,pattern × labels),缺什么、共线撤下了什么、这个面能做什么不能做什么;`read_quantities(run_id, names)` 按名一次取 |
| **组合** | `get_portfolio_snapshot`(入口)· `get_portfolio_positions` · `get_attribution` · `get_risk_state` · `list_run_alerts` · `list_risk_limits` · `get_run_freshness` · `reconcile_move` · `get_drawdown_episodes` · `explain_episode` · `list_alerts` · `get_market_stats` | 全集返回、**禁 top_k**;共线时 `quotable_individually: false` |
| **委派** | `ensure_company_ready` · `start_issuer_research` · `start_exposure_run` · `get_task_status` · `read_issuer_brief` | 立即返回 id,不阻塞;预算计入 |
| **反思/门** | `think`(免预算)· `respond`(**唯一出口**,GATE 类,免预算) | |

预算:每 turn 15 次工具调用(REFLECTION/GATE 免计);`describe_issuer` 载荷 ≤ 12KB(live 断言,八家全过)。

研究面 = READ_CORE 13 + `search_external_research` + `submit_brief`。

## 7. 门(`respond` / `submit_brief` 的解析链,V15)——可追溯是怎么被执行的

**桌面**(`services/table.py`)是唯一的对象:每轮工具声明的并集,同时是上下文载荷、门的全集、审计记录。出口只能写桌面上的名字,门只做查找。

按顺序,全部**机械、封闭、无阈值、无按值反推**(`services/resolver.py`):

1. **形状**:`RESPOND_SCHEMA`(oneOf 六种论断:paragraph / metric_table / chart / trend / absence / action)在关口拒绝一切非文法形状;槽只有 `{ref, name}`;文本 `\d` 为空,豁免类封闭且短(日期、年份、表单号、期间标签、法规引证、附着型号、窗口标签),id 写进正文按整个 token 拒
2. **来源**:每个 ref ∈ 本 session 桌面(`not_on_table`)
3. **名字**:每个槽的 name ∈ 该 ref 持有的量(`unknown_name`,拒绝信列出该 ref 的全部名字)
4. **引号逐字**:引号内 ≥4 词 ∈ 该块 `cites` 指向的原文
5. **断言行类型**:trend/chart → 序列行;absence → 缺席行;action → 本轮任务

`not_alone`(共线单系数)不在门里判:它们**不上桌**(`table._place`),模型看不见就写不出。四个出口(`respond`、`submit_brief`)调同一个 `resolver.resolve`;日报门保留 v1 散文路径(`numeric_verification.verify`,证据集由服务端装配)。

被整体删除的:按值解析(`_COMPATIBLE`、半 ulp 匹配槽、`held_instead_by`)、`_DERIVATIONS` 出路搜索、20 条豁免正则、26 个运行时形状码、`trajectory_gate`(R1 进 rubric,R2 由 action 谓词取代)、id 形状收割器与 `collect_trail`。

## 8. Agent 层

**拓扑 1 + 1,树深封顶 2**:meta-agent(api 进程内,面向用户)+ research 子会话(worker 内,产 brief)。

**meta-agent 循环**(`agents/meta_agent.py`):系统提示(六条不变量 + 已验证示例,V15 起含 `describe_run → read_quantities` 路径与块出口说明)+ 32 个 schema → `llm.chat` → 工具调用经 `dumps_capped`(按条目截断并声明,28KB;`table` 切片从不在此截断,它在构造器里按整表收窄)进上下文 → 直到 `respond` 过门。每次 `llm_call` 记一行(token 用量),每步一行 `agent_steps`。**没有路由器、没有问题分类器、没有 SKILL.md 加载器**——知识随定位工具返回值到达。

**research 会话**(`agents/research_session.py` + `workflow/issuer_research_workflow.py`):readiness 前置 → 子会话在研究面上工作 → `submit_brief`(六节 × 同一块文法,同一解析器;五节各须指向证据)→ `issuer_briefs`(文本列 + `blocks` JSONB)。

**ExposureWorkflow**(`workflow/exposure_workflow.py`,确定性,worker 执行):加载 → 校验 → 行情 → `calculate_exposure` → `calculate_attribution`(8 因子回归)→ `calculate_risk`(VaR/ES/压力/限额)→ `generate_report`;每步 `workflow_events`,run 三切片(metrics / attributions / alerts)。

## 9. 用户能做什么(F1–F6 对照 TARGET §1)

| | 功能 | 今天的形态 | 状态 |
|---|---|---|---|
| **F1** | 组合监控 | 上传/克隆组合 → `start_exposure_run` → 敞口、归因、风险、告警、时间线、日报 | ✅ 既有,V5/V6 量化收口 |
| **F2** | **即问即答** | 发行人报表分析(任意窗口、任意具名度量、跨发行人比较、申报原文引用)+ 组合分解(单日 vs 回撤段、市场 vs 个股、因子) | ✅ V9–V12 主线;实测见 §10 |
| **F3** | 深度调查 → Brief | `start_issuer_research` → 后台子会话 → 分块引用的 Issuer Risk Brief | ✅ M7+M9,10 份 |
| **F4** | 证据浏览 | 发行人页四 tab(Financials recipe v2 / Filings / Brief / Research)+ 引用抽屉穿透到 fact/chunk/calc | ✅ |
| **F5** | 数据就绪 | `ensure_company_ready` 隐式委派;readiness workflow | ✅ |
| **F6** | 审计 | `agent_steps` 逐步轨迹、`calc_ledger` 逐算、`workflow_events`、`/me/usage` 配额 | ✅ 横切 |

**生产化**(V2/V7):Clerk 登录、Postgres RLS 多租户、日配额(`usage_daily`,`QUOTA_UNLIMITED_USERS` 白名单)、任务租约与回收、备份、公网可注册。

## 10. 已被实证的(2026-08-27/28 的 43 + 24 + 24 次真实会话)

| 主张 | 证据 |
|---|---|
| 带 `calc_id` 的数字零算术错 | 43 次会话,所有 calc 回账本核对 |
| 区间代数从三张累计报表拼出无人申报过的 TTM,分毫不差 | T06 |
| 包含图在六种债务形状上零发行人规则 | T09/T13/T14/R |
| 类型计算器拒绝用户明令的双重计数 | T11 |
| 缺席有身份,措辞由服务端出 | V11 后 T04/T07/T12 |
| **知识层让路由从抽签变确定**:总债务 12/24 → **24/24**;回撤测量 2/5 → **8/8**;假缺席 → 0 | V12_COVERAGE |

## 11. 仍在的边界(如实)

- **判决禁令、引号外的方法句、"为什么"的叙事拉力**——真值在自由散文里,只能测量不能消灭([GAPS.md](../dev_note/portfolio-demo/agent-battery/GAPS.md) 右列)
- **G2 剩余项**:`describe_issuer.definition` 仍是未经计算的承诺;`computable` 仍是"名字存在"而非"窗口可达";`get_balance_sheet` 未带 `do_not_add_to`;`reconcile_move` 无 `larger_share`
- **LLY capex 未映射**(`test_v11_tag_drift_live` 唯一的 `unmapped_candidate`),补映射前须先验证语料
- **系统提示未变短**(V12 判据 6 未达标:4918→5071 字符),示例换了更便宜的位置而非变小
- 单价格源、无基准成分股、单币种:IPV / Brinson / 货币归因**明确不做**(MODULE_NOTES 插节)

## 12. 版本弧(每批一句)

V2 多用户 + 生产化 → V3 harness(Verify/Context/Memory/Evals)+ 数值门 → V4 失败可解释、开销有账 → V5 量化正确性(一种价格、一次回归)→ V6 窗口够长、报告过门 → V7 公网上线 + 配额 + 门死锁修复 → V8 产物读 + `reconcile_move` + 轨迹判据 + 回撤取证 → **V9 四公理 + 公式登记 + 只铺证据** → V10 收敛(面 36→31,一种取数一种算)→ **V11 电池驱动的六处环上修复**(传输、缺席、门的文本半边、漂移检测)→ **V12 知识层**(50%→100%)。
