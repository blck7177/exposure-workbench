# V13 措辞过目单

> 本文件 S2 时创建、随各步追加;本版(8/31)把 S4a/S6c 已上线的句子补齐,并新增 W1–W7 七条待批改动。S2 的失败句表原样保留在 §二-B。

按计划 §S7 的约定：LLM 路径与读者可见的句子只改**措辞**，且全部过目后才动。本单分两部分——**待批准的改动**（每条给现文/提文/理由/牵动面，批一条我改一条）与**已上线句子的回溯过目**（S2/S4a 按"占位句先合并、守卫只查非空"的纪律先上了线，句子是我写的，你没看过）。

编号引用格式：✅ 同意照改 / ✏️ 改成你给的版本 / ❌ 不动。

---

## 一、待批准的改动

### W1 · 日报 prompt 的负数例句

**文件**:`src/exposure_workbench/agents/prompts/daily_exposure_report.md:30-33`
**现文**:

> **Copy figures exactly as supplied, including the minus sign.** Do not put the sign in a word: write "down $-141,973", never "a loss of $141,973". …

**提文**:例句改为 `write "down -$141,973"`（符号在 `$` 外）。
**理由**:喂给模型的输入已改为 `-$141,973`（确定性 formatter 修复，已提交）；例句保持旧形会与"exactly as supplied"自相矛盾。门的提取器现在三种写法（`-$X`、`$-X`、`−$X`）都读对符号与 MONEY 类型，所以这纯粹是一致性，不再有判据风险。
**牵动**:无——`report_verification` 判据一行未改，回归测试 103 条全绿。

### W2 · brief prompt 加一句：引用贴着论断

**文件**:`src/exposure_workbench/agents/research_session.py`(`_SYSTEM`)
**现文**:

> Every factual claim in the brief must cite the evidence ids (fact_/calc_/chunk_/src_) that a tool returned to you this session.

**提文**:句后追加：

> Place each citation immediately after the claim it supports — never collected at the end of a paragraph, where a reader cannot tell which id backs which sentence.

**实测依据**:活库 AAPL brief 的 `financial_summary` 共 535 字符，8 个引用全部位于 383–517 段尾；前 383 字符的论断零引用。
**牵动**:brief 门只验证 id 有效性，不验证位置——这句只影响生成，不影响判据。旧 brief 不变。

### W3 · `_SYSTEM` 的 run id 句

**文件**:`src/exposure_workbench/agents/meta_agent.py`(`_SYSTEM`)
**现文**:

> For a full written brief, call start_issuer_research and give the user the run id to follow.

**提文**:

> For a full written brief, call start_issuer_research and tell the user the brief is being prepared and will appear on the issuer's page in a minute or two.

**理由**:V13 全批的判据是读者层零内部 id;这句是模型往回答里写 `rrun_…` 的直接指令来源。
**牵动**:chat 门不看这句;S4 里"chat 文本检测 `rrun_` 渲染链接卡"一项因此从待办降为防御(见遗留清单)。

### W4 · `_SYSTEM` 加精度句

**同文件**,新增一句(位置:数字纪律段):

> Write figures at the precision an analyst would say them aloud; the verification accepts correctly rounded values.

**理由**:`numeric_verification.py` 的半 ulp 舍入判据本来就支持;现在模型偶尔照抄全精度(`0.13558095`),读者层显得像机器转录。
**牵动**:无判据改动。

### W5 · 日报停止索取 `recommended_actions`(§9-⑦,建议采纳 D8)

**现状**:prompt 第 19/48 行索取("Consider trimming NVDA to reduce…"),线上日报正文含"Consider trimming LLY…"。
**提议**:prompt 的 JSON 模板与说明删去该字段;`report_verification._REQUIRED_FIELDS` 同步移除;读者层已由 alerts 生成限额事实(S6c 的 Warnings 面板)。旧报告的该字段照存,前端不再渲染。
**替代方案**(若不删):保留索取,仅移入审计层。
**牵动**:`report_verification` 必填集一处 + 前端 Briefing 组件删一个 block + `test_v2_audit` 若守该字段需同步。

### W6 · 免责一行(待 §9-② / §9-⑥ 拍板)

composer 下方一行(现无):

> Analysis of filed and derived figures — not investment advice. Every number links to its source.

首登确认按 §9-② 决定存 `users.disclaimer_acknowledged_at`(D9)或仅 localStorage 后实施。**此条批文字即可,机制另批。**

### W7 · 命名统一(§S7)

`layout.tsx` 的 `<title>` 与顶栏字标:`Exposure Workbench` → `desk-for-one`;meta description 去掉 "LLM reporting" → `Portfolio exposure and issuer intelligence, every figure traceable to its source.`
**牵动**:纯前端;S6c 时我保留旧名等这一条。

---

## 二、已上线句子·回溯过目

### A. 工具 display 短语(S4a 已上线,回溯过目;从三个注册表机械提取)

- `get_flow` → “Reading {ticker}'s {metric} over the periods it reports”
- `get_balance_series` → “Reading {ticker}'s {metric} at each reported date”
- `series_stat` → “Taking the {op} over that series”
- `describe_issuer` → “Looking up what {ticker} reports and what can be computed from it”
- `get_balance_sheet` → “Reading {ticker}'s balance sheet”
- `calculate` → “Computing {op} of two figures”
- `evaluate_formula` → “Evaluating {name} for {ticker}”
- `get_fundamental_panel` → “Building the measures panel for {ticker}”
- `get_portfolio_snapshot` → “Reading this desk's books and their latest run”
- `get_task_status` → “Checking whether the delegated work has finished”
- `get_portfolio_positions` → “Reading the holdings”
- `read_issuer_brief` → “Opening the latest brief on {ticker}”
- `get_attribution` → “Reading what the regression attributed the day to”
- `get_risk_state` → “Reading the run's risk measures”
- `list_run_alerts` → “Reading which mandate limits the run raised”
- `list_risk_limits` → “Reading this book's mandate limits”
- `get_run_freshness` → “Checking how current the latest run is”
- `reconcile_move` → “Splitting the day's move into market and stock-specific parts”
- `get_portfolio_analysis` → “Ordering the exposures and measuring the room left”
- `get_drawdown_episodes` → “Measuring the drawdowns over the window”
- `explain_episode` → “Explaining what happened between {peak} and {trough}”
- `get_market_stats` → “Reading {ticker}'s price return”
- `search_filing_passages` → “Searching {ticker}'s filings for \u201c{query}\u201d”
- `get_filing_section` → “Reading {item_code} of {ticker}'s filing in full”
- `list_alerts` → “Checking for alerts naming {ticker}”
- `think` → “Making a note before going on”

- `ensure_company_ready` → “Preparing {ticker}'s filings and prices”
- `start_issuer_research` → “Starting a research run on {ticker}”
- `start_exposure_run` → “Starting an exposure run”
- `respond` → “Resolving every figure against the ledger, then answering”
- `search_external_research` → “Searching the web for \u201c{query}\u201d”
- `submit_brief` → “Submitting the brief for checking”

### B. 运行失败的句子(S2 已上线;本节自 S2 版原样保留,含表与理由)

`apps/web/lib/errors.ts` 的 `RUN_ERROR_WORDING`。规则:**有 code 且后端存了 message → 显示 message**(后端只在"这句话本来就是写给读者的"时才存);**有 code 无 message → 下表**;**无 code → 通用句,并忽略 message**(V13 之前的行带着供应商原文且没有 code,不回填、也不信任)。

| code | 什么时候 | 句子 |
|---|---|---|
| `inputs_unusable` | run 拒绝了自己的输入(价格陈旧/缺失、无持仓、限额行指向不存在的检查) | This run could not use the data it was given, and stopped before writing anything. |
| `provider_quota` | 模型服务 429 | The model service refused this run — its rate or spend limit was reached. Nothing was written; it is worth trying again later. |
| `provider_unavailable` | 连不上 / 超时 / 5xx | The model service could not be reached, so the run stopped before writing anything. Try again. |
| `provider_refused` | 4xx(非 429)——我方缺陷 | The model service rejected the request. That is a fault on our side, not yours — nothing was written, and it has been logged. |
| `tool_face_unavailable` | 工具容器不可达或拒绝本次 bearer | The analysis service this run needs was unavailable, so it stopped before writing anything. Try again shortly. |
| `ingest_failed` | 取源数据失败 | Fetching the source data failed, so the run stopped before writing anything. Try again. |
| `brief_not_submitted` | research agent 用完预算未提交 brief(**不是缺陷**) | The analyst worked through its whole allowance without reaching a brief it could stand behind, so none was written. A narrower question usually gets there. |
| `lease_expired` | worker 停止上报,被 reaper 结算 | (后端已有句子,`task_service.LEASE_EXPIRED_ERROR`,原样沿用) |
| `run_failed` | 其余,含缺陷 | This run stopped before finishing. Nothing was written, and the failure has been logged. |
| —(无 code) | V13 之前的行 | This run stopped before finishing. Nothing was written. |

**两处值得单独看的**:
- `provider_quota` 说的是"值得晚点再试",而 `provider_refused` 说的是"这是我们的问题,不是你的"——两者都不把供应商的原文给读者(那是一段计费关系,读者不是当事人)。
- `brief_not_submitted` 刻意不说"失败":什么都没坏,是工作没收敛,而"narrower question usually gets there"是读者真能采取的下一步。

**保持不变的**(后端存的、写给读者的原句):
- `Cannot value this portfolio as of 2026-08-26 — newest price older than 10 days for: AAPL (30d old), … Re-run once the data is available, or remove the holdings.`
- `lease expired — the worker holding this task stopped reporting. This task type is not safe to replay, so it was failed rather than requeued; start it again to retry.`

---


### C. 告警句模板(S6c 已上线)

结构化字段拼装(不再打印存储的 `[WARNING]` 原句):

> **{限额簿的 label}** is **{current}**, against a {limit} {severity} tier.
> 副行:{Issuer concentration | Sector concentration | Stress, propagated through each holding's beta | Portfolio} · this book's own limit

### D. 面板注脚(S6c 已上线,句子在组件内)

每张图的"它不是什么"句——估值假设、held-flat、VIF 不可单引、"27/27 在记录之前就跑了"等。源文件:`apps/web/app/components/book/panels.tsx`、`issuer/panels.tsx`、`book/sections.tsx`(grep `note=` 即得全部)。量大,建议抽查而非逐句。

---

*生成于 2026-08-31,对应分支 issuer-intelligence。批注直接回在对话里即可。*
