# Architecture As Built — 2026-09-02

> **性质**:现状快照。不变量与目标拓扑见 [TARGET_ARCHITECTURE.md](TARGET_ARCHITECTURE.md)(v3),逐模块设计见 [MODULE_NOTES.md](MODULE_NOTES.md)(M1–M18),部署与租户见 [PRODUCTION.md](PRODUCTION.md)。本文只回答"今天有什么、怎么连、能做什么"。
> **规模**:`src/` ~21k 行 Python、`apps/web` ~3.3k 行 TS;**1937 offline** 测试;V15(桌面)已落地,见 §7;V16(单位代数·方法登记·价格分析)与 V17(发行人自举·读法·排序)已落地,V17 待线上复核。线上 https://desk-for-one.com。

---

## 1. 一句话

**用户只面对一个 meta-agent;它能调 41 个工具;每一个数字都能回溯到账本里的一行;模型不写数字,只写桌面上的名字(V15);算错的类别由代码消灭,选错的类别由知识降低,指错的类别由结构消灭,剩下的交给门拒绝。**

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
 │  exposure_update      │        │  /mcp/meta      41 工具                │
 │  company_readiness    │───────▶│  /mcp/research  24 工具                │
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
| **Raw** | companies(**V17 起有第二个写入者**:`company_service.admit` 从上市宇宙建行,见 §9-F5)· filings · filing_documents · market_prices · factor_prices · security_master | 10 家(8 发行人 + HYG/TLT)· 16 份申报 · 15,776 日价 · 6,601 因子价 | append-only,带 provider/retrieved_at |
| **Normalized 证据** | filing_sections · filing_chunks(+embedding)· financial_facts · research_sources | 3,078 chunk · **62,473 事实,其中 8,352 已映射**(`mapping v3`,39 个指标)· 25 条外部来源 | raw_concept 与 normalized_metric 并存;映射不决定存储 |
| **Calc Ledger** | calc_ledger | **25,119 行** | 每次计算一行:操作、参数、输入 refs、原语版本;**V11 起失败也铸行**(`absence.*`) |
| **Artifact** | daily_reports · issuer_briefs · evidence_packs | 10 份 brief | LLM 产物**只**落这一区,永不回流成证据 |
| **Runtime** | tasks · exposure_runs · research_runs · schedules · workflow_events · agent_sessions · agent_messages · agent_steps · usage_daily · users | 26 个 run · 1,273 个会话 · 3,008 步 | 轨迹 append-only |
| **风控配置** | portfolios · positions · risk_limits · risk_alerts · limit_checks · stress_results · factor_attributions · factor_residuals · issuer_exposures · sector_exposures · exposure_metrics | 7 个组合 · 44 个持仓 | `risk_limits` 是 mandate 的唯一真相(M16) |

铁律:证据四库禁 UPDATE/DELETE;重述走新行(`restatement_key = (filing_date, accession)`);租户隔离靠 Postgres RLS(`app_rls` 角色 + `SET LOCAL`),不靠应用层过滤。

## 4. 分析层(`analytics/`,纯函数,14 个模块)

这是 **"世界结构进代码"** 的那一层。V9 的四条公理 + 组合风控的五个既有模块 + V12 的语义表:

| 模块 | 公理 / 职责 | 实证 |
|---|---|---|
| `interval_algebra` | **R1** 流量事实 = 边界图上的一条边;任意窗口 = 带符号路径(Dijkstra)。Q4/H1/TTM 是同一个算法 | Q4 parity 290/290;季度序列 1439/1439、年度 484/484 |
| `containment` | **R3** 求和项不得嵌套;11 条经语料验证的包含边(787 次共现零违反);`cover()` 给出反链 | 六家六种债务形状,零发行人规则 |
| `services/typed_calculator` | **R4** 类型化四则:四种拒绝(不同时点相加 / 重叠区间相加 / 嵌套相加 / 单位类不合);V11 加 `scale`;**V22 操作数可为 `ref:name`(run/分析行/情景行上的具名量),`Typed` 多一根 base 轴(这是哪本 book 的量),两本 book 相加/相乘、book 与申报量相加、份额 × 非本 book 的钱三类拒绝** | 43 次真实会话零算术错;V22 活库 headroom parity 20/20 |
| `formulas` | **方法定义进数据**:16 个具名度量,带表达式、输入、基准、`family`、`citation`/`authority`、具名替代、`note`;**零阈值**(测试守) | SEC C&DI 103.01/103.02/102.07 |
| `semantics` | **V12**:21 条指标 gotcha(事实+后果)、6 条已验证示例;零数字零阈值(测试守) | 总债务路由 50%→100% |
| `series_ops` / `drawdown` | 序列变换(yoy/qoq/cagr/…);峰谷回撤段检测 | V10 并轨,V8-D |
| `scenario` | **V22** 卖出后的 book(纯算术):余下权重重归一化、行业随之、收益离开 book;五种拒绝 | 卖 NVDA:集中度告警 2→4 |
| `exposure` · `factor_model` · `risk_metrics` · `stress` · `pnl` · `limits` · `limit_defaults` | 既有组合风控:敞口、8 因子回归(750 日窗,VIF 共线标记)、VaR/ES/波动、压力情景、P&L、限额 | ExposureWorkflow 的四个计算步 |

## 5. 服务层(45 个模块)——按写/读/门分

**摄取(写)**:`filing_ingestion`(EDGAR → sections/chunks/facts)· `market_data_ingestion` · `document_index`(embedding)· `concept_mapping`(v3,39 指标;映射永不决定存储)· `security_master` · `research_search`(Tavily)

**查询(读,给工具)**:`fundamentals`(`get_flow` 任意窗口 / `get_balance_sheet` 单时点 / 序列)· `formula`(`evaluate_formula` / `build_panel`)· `calc`(账本记录 + 指标地图)· `series` · `run_reads`(归因/风险态/告警/限额/新鲜度)· `reconcile`(单日分解:两条恒等式 + `factor_share`)· `drawdown` · `scenario`(**V22** 情景行:run 子表镜像,`check_limits` 同一引擎重跑限额,β 不结转)· `integration`(**V22** 起行自述类型,面板在代数之上、parity 钉住)· `filing_retrieval` · `portfolio` · `brief` · `evidence_resolver`

**V11–V12 新增的"诚实层"**:`absence_service`(六种拒绝各铸可引的行,statement 服务端拼,带 `superseded_by` 与逐输入覆盖)· `period_semantics`(财年历从年度事实推;累计申报是指标属性)

**桌面与门(V15)**:`quantities`(唯一拼名)· `table`(声明/构造/加载)· `resolver`(六不变量)· `answer_blocks`(文法与渲染)· `display_conventions`(读者精度,py/ts 双向锁);`numeric_verification` 只剩 v1 散文路径(日报门)(见 §7)

**运行时**:`task`(租约/回收)· `agent_session` · `trace` · `context_budget`(tiktoken 计量,80k 软上限)· `usage`(quota)· `schedule` · `workflow_event`

## 6. 工具面(`tools/`,V23 起 **10 + 8**)

面是声明式数据(`faces.py`),缺一个工具即构建错误。**V23**:工具按**数据域 × 动词**正交——describe / read_fundamentals / read_filings / read_prices / read_book / compute / think / start / search_web / respond,meta 面 10 个,research 面 8 个(去 read_book 与 start,加 submit_brief)。原 13 个“方法工具”成为 `analytics/skill.py` 登记表里的方法,由 compute 执行;原三个定位工具合成 describe;原七条读 run 的路合成 read_book。下表按 V23 重写。**每个工具返回值要么带 id,要么是类型化拒绝**——没有第三态。**V15 起每个工具在注册时声明它的结果把什么放上桌面**(`Tool.evidence`:结果里的 id、run 子表作用域、委派任务),关口据此构造 `result["table"]`——名字 = 读者精度值——并把声明存为该步的 evidence;没有声明的工具(`get_task_status`/`list_risk_limits`/`get_run_freshness`)不产生证据。

| 动词 \\ 域 | 工具 | 说明 |
|---|---|---|
| **描述** | `describe(subject, expand)` | 一个跨域目录:ticker / port_ / run_ / calc_ / 空;各域存在性、计数、范围;三种“缺”(not_reported / not_held / cannot);适用方法与分析程序;默认层 ≤ 8k,expand 展开一域 |
| **读** | `read_fundamentals` · `read_filings` · `read_prices` · `read_book` · `search_web` | 发行人数字(窗口/时点/序列,instant 与 flow 由事实判定)· 申报文本(query 或 item)· 价格(序列或单日)· 桌子自己的产物(run/情景按名字、portfolio 的五个 section、brief、任务状态;仅 meta 面)· 网络(两面共用) |
| **算** | `compute(op \\| method, operands \\| subject, params)` | 唯一算入口与账本唯一写口:四则/rank/regress/序列统计走类型化计算器;46 条登记表方法(32 公式 + panel + 价格 7 + book 6)按 executor 分发;method 与 subject 接受列表;research 面的 compute 拒 book 方法 |
| **发起** | `start(kind, subject, reason)` | readiness / research / exposure_run 三合一,立即返回 id |
| **反思/门** | `think` · `respond` · `submit_brief` | 不变 |

**V24**:每个工具结果 = `{...note, facts: {columns, rows}, held_back?}`——note 是载荷中每个数字被其 fact id 替换后的结构,facts 一行一事实(id、kind、subject、measure、unit、value、as_of、window、params、sources);`respond` 的块只有 paragraph / table / chart,指针是 `{fact: id}`。

预算:每 turn 15 个单位,**V23 起按 assistant 消息计**(同一消息内多次调用一个单位;REFLECTION/GATE 免计);`describe_issuer` 载荷 ≤ 12KB(live 断言,八家全过)。

研究面 = READ_CORE 23 + `search_external_research` + `submit_brief`。V19 前 `search_external_research` 只在研究面,chat 里"帮我搜一下"没有工具可走,而"本面不能联网"那句能力声明只随 `describe_run` 返回、发行人问题从未读到。

## 7. 门(`respond` / `submit_brief`,V24)——核的是指得对不对,不是数据对不对

**账本**(`services/ledger.py`)是唯一的对象:本会话每次工具调用记录在步骤上的 Fact(`agent_steps.evidence_refs` 的 `{facts: [...]}`),同一事务写入 `facts` 表作索引。模型看到的 `facts` 块与门加载的是同一份记录,不重建。一个 Fact 在工具边界由 adapter 造一次(`services/fact_adapters.py`,不变量:note 里无数字、每条有 as_of 或 window、每个数字键有单位),随后原样传递。

出口只能写指针:`paragraph {runs: [str | {fact: id}], cites}` / `table {rows: [[id]]}` / `chart {kind, fact}`(`services/answer.py`)。门(`services/gate.py`)按顺序做三个**查表**:

1. **G1 在账本上**:每个 id ∈ 本会话账本(`not_on_ledger`)
2. **G2 排版容得下**:格子=独立标量、图=序列、`standalone:false` 不可单独站(`kind_does_not_fit` / `not_standalone`);`cites` 可为本段依据的任何事实
3. **G3 正文可对账**:每个数字 token 解析到等值事实(唯一或多条)、事实的身份字段(as_of 与年份、period、window、params 如置信度、measure 里的数字)、所引段落、或用户本轮问题;否则 `unsourced_figure`(算 / 引 / 删)。另:`pointer_written_as_text`、`id_in_prose`、`name_in_prose`、`unverified_quote`(引号 ≥4 词逐字在所引段落)

零豁免类;门里唯一的正则找 token(在 answer.py),不判。`accepted()` 把指针填成事实(含 display 与身份)、把解析到的正文数字切成链接片段;`verified` 记门当时所见。日报门保留 v1(`numeric_verification`,引号核验从 gate 导入)。

被整体删除的(V24):`quantities` 的门角色、`table.py`(声明→切片→砍范围)、`resolver.py`、`answer_blocks.py`(六种块、九类数字豁免、槽 `{ref, name}`)、`prose_critic.py`、`Tool.evidence` 声明。留下的 `quantities.py` 只为 run 子表命名(compute 的 `ref:name` 操作数、read_book 按名读);compute 的操作数也接受 `f_` id。

## 8. Agent 层

**拓扑 1 + 1,树深封顶 2**:meta-agent(api 进程内,面向用户)+ research 子会话(worker 内,产 brief)。

**meta-agent 循环**(`agents/meta_agent.py`):系统提示(六条不变量 + 已验证示例,V15 起含 `describe_run → read_quantities` 路径与块出口说明)+ 43 个 schema → `llm.chat` → 工具调用经 `dumps_capped`(按条目截断并声明,28KB;`table` 切片从不在此截断,它在构造器里按整表收窄)进上下文 → 直到 `respond` 过门。**V21 起一条 assistant 消息里的多个调用按序分发、每个工具止于第一次"调用本身被拒"**(`agents/batch.py`:有 `error` 且桌上无物=调用被拒,同名其余调用不发、回 `not_attempted`、不计预算;带 absence 行的拒绝是发现,不截;预算池空则其余全部不发,pause/exit 除外),两个循环共用。每次 `llm_call` 记一行(token 用量),每步一行 `agent_steps`(被截住的调用由循环记为 `rejected`)。**没有路由器、没有问题分类器、没有 SKILL.md 加载器**——知识随定位工具返回值到达。

**research 会话**(`agents/research_session.py` + `workflow/issuer_research_workflow.py`):readiness 前置 → 子会话在研究面上工作 → `submit_brief`(六节 × 同一块文法,同一解析器;五节各须指向证据)→ `issuer_briefs`(文本列 + `blocks` JSONB)。

**ExposureWorkflow**(`workflow/exposure_workflow.py`,确定性,worker 执行):加载 → 校验 → 行情 → `calculate_exposure` → `calculate_attribution`(8 因子回归)→ `calculate_risk`(VaR/ES/压力/限额)→ `generate_report`;每步 `workflow_events`,run 三切片(metrics / attributions / alerts)。

## 9. 用户能做什么(F1–F6 对照 TARGET §1)

| | 功能 | 今天的形态 | 状态 |
|---|---|---|---|
| **F1** | 组合监控 | 上传/克隆组合 → `start_exposure_run` → 敞口、归因、风险、告警、时间线、日报 | ✅ 既有,V5/V6 量化收口 |
| **F2** | **即问即答** | 发行人报表分析(任意窗口、任意具名度量、跨发行人比较、申报原文引用)+ 组合分解(单日 vs 回撤段、市场 vs 个股、因子) | ✅ V9–V12 主线;实测见 §10 |
| **F3** | 深度调查 → Brief | `start_issuer_research` → 后台子会话 → 分块引用的 Issuer Risk Brief | ✅ M7+M9,10 份 |
| **F4** | 证据浏览 | 发行人页四 tab(Financials recipe v2 / Filings / Brief / Research)+ 引用抽屉穿透到 fact/chunk/calc | ✅ |
| **F5** | 数据就绪 | `ensure_company_ready` 隐式委派;readiness workflow。**V17:发行人宇宙从 8 家封闭名单变为整个上市宇宙** —— `company_service.admit` 在请求路径上按 `security_master`(13,024 只在市证券,其中 7,096 有 CIK)建 company 行,昂贵的活仍在 worker 上;三种拒绝各说各的(不在上市宇宙 / ETF 无报表 / 上市但无 SEC CIK)。发行人页对未准备的持仓给出「Prepare」而不是「不认识这个代码」 | ✅ 待线上复核 |
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
- **四个量化度量算而不发（V20）**：VaR/ES（无数值测试、分位约定未写明、无回测）、压力情景与四个 stress loss（冲击幅度无来源、三个情景依赖各自共线的单个 β、未冲击因子按 0）——run 照算照存，`analytics/withheld.py` 一处声明，桌面/清单/门/限额/日报/API/证据卡全部由它派生；单个因子 β 在 `collinear` 下由 API 置空。每条附放行条件
- **段落里的错标由门外 critic 读,不进门(V21)**——`services/prose_critic.py` 读渲染后的块,给第二个模型每个槽的桌名,判 agrees/disagrees/unclear;今天只在离线席位(`scripts/critic.py`,电池或会话),是否每 turn 内联为非阻塞批注是产品决定,未做
- **拆股结转只覆盖陈述日→run 日(V21)**:`stock_splits` 随价格同步写入,同步前的旧 run 未结转;陈述日之前的持仓历史本来就没有
- **去掉 ^VIX 后仍然共线**:`scripts/reattribute_runs.py`(V21)对生产库 dry-run 显示 28 个历史 run 可重拟合到七因子、max VIF 17.9→16.8,来源是 SPY/QQQ/IWM;`--apply` 改写生产行,待 boss 放行后执行;单个 β 仍在 `collinear` 下置空
- **比较级散文仍不被判**——门保证出处,不保证句子。V17 把「谁最高」变成一次 `rank` 计算(有操作数、有拒绝、落账本、每个名次是桌上的一个名字),消灭的是"顺序从未被算过"这一类;直接写进散文的最高级仍是散文
- **历史行的读法靠迁移改正,不靠回算**:`v17_multiple_unit.sql` 只改 326 行的 `unit_class`(值、操作数、基准、输入引用一概不动)
- 单价格源、无基准成分股、单币种:IPV / Brinson / 货币归因**明确不做**(MODULE_NOTES 插节)
- **上市宇宙里约 45% 没有 CIK**(基金、部分外国发行人、`BRK.A` 这类 feed 里符号形式对不上的),它们拒绝在 `not_an_sec_filer`,价格侧照常可用

## 12. 版本弧(每批一句)

V2 多用户 + 生产化 → V3 harness(Verify/Context/Memory/Evals)+ 数值门 → V4 失败可解释、开销有账 → V5 量化正确性(一种价格、一次回归)→ V6 窗口够长、报告过门 → V7 公网上线 + 配额 + 门死锁修复 → V8 产物读 + `reconcile_move` + 轨迹判据 + 回撤取证 → **V9 四公理 + 公式登记 + 只铺证据** → V10 收敛(面 36→31,一种取数一种算)→ **V11 电池驱动的六处环上修复**(传输、缺席、门的文本半边、漂移检测)→ **V12 知识层**(50%→100%)→ V13–V15 桌面与门 → V16 单位代数 + 方法登记 + 价格分析(substitution 8 题 2→0)→ **V17 三处收口**:发行人自举(封闭 8 家 → 整个上市宇宙)、无量纲的读法(`multiple` 进代数,8 条杠杆/周转比率与 beta 不再显示成百分数)、排序进类型化计算(`rank`)→ **V19 三处收口**:表格/trend 的标签由槽名派生(模型不再有格子写标签,`Peak-to-trough decline | $205.10` 这类错标在结构上消失)、联网搜索进 meta 面(chat 能搜了,能力声明改口)、证据链补两个断点(fact 卡到 SEC 原文链接、run 卡到持仓)→ **V20 算而不发**:量化审计后 VaR/ES/压力情景/共线下的单个 β 从所有读取面撤下(开关在 `analytics/withheld.py`,不在 UI),保留的度量各配一句由代码常量写成的英文方法说明(`analytics/methods.py`,页面 ⓘ),`^VIX` 退出因子集 → **V21 五条残余逐条关**:批次止于首次拒绝(十次同名错调用只花一次)、`get_drawdown` 四行(减法进工具)、股数按拆股结转到 run 日(`stock_splits`)、历史 run 重拟合到七因子的脚本(dry-run 28 个,apply 待放行)、门外 critic 离线席位(段落标签的判断在门外)。 → **V22 组合量进代数**:`ref:name` 具名操作数 + `Typed.base` 轴(两本 book 不相加、book 与申报不相加、份额不乘别人的钱),`get_portfolio_analysis` 行自述类型成为代数之上的面板(parity 活库 20/20),一个情景原语 `hypothetical_book`(卖出后的 book 是一条 run 形状的行;电池 C01#t3 那问的答案是"更紧":告警 2→4)。 → **V23 目录、一个 compute、skill 三种条目**:工具按数据域×动词 44→10 一次切;`describe(subject)` 一个跨域目录带三种“缺”;46 条方法进 `analytics/skill.py`(每条 authority + fails_when)由 compute 执行,17 条读法、13 条分析程序作为数据随 describe 到达;提示词缩到契约;预算按消息计。
- **V24**(2026-09-05):事实自带身份——Fact 在工具边界造一次(adapter),账本 + facts 表双写,三种块、三查表的门(零数字豁免,正文数字按账本对账否则拒),critic 与起名器的门角色删除;前端事实芯片与链接;live 三轮四问后 compute 接受 `f_` 操作数、情景可链式。
