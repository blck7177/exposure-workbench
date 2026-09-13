# V33 — 20 题跨域实测，问题登记册（2026-09-13）

**性质：只记录，不修改。** 代码树在整个测量期间未动（HEAD `99804d6`，tree `f33139c0`，`git status` 仅 `docs/spikes/v33/` 未跟踪）。
本册只登记观察到的问题与其发生位置，不含任何修复建议的实施。

## 0. 仪器条件

| 项 | 值 |
|---|---|
| 被测代码 | 工作树 HEAD `99804d6`（**不是**生产容器，生产容器仍是 V30 之前的镜像，无 `claims.py`） |
| 工具面 | fixture face，`127.0.0.1:8105`，uvicorn 直接服务工作树代码 |
| 数据 | `exposure_battery`，由生产库快照还原，**只读镜像**；fixture 上无 worker，`start` 入队的任务永不完成，故 `latest_completed_run` 不会被测量本身改变 |
| 模型 | `gpt-5.4-mini`（`.env` 默认，即产品默认） |
| 面 | 完整产品面（`--deny submit_brief` 对 meta 面是文档化的 no-op，见 `mcp_server._served` 注释），**`start` 在面上** |
| 并发 | 5，每题独立 session，单轮 |
| 轮次 | A 轮与 B 轮，见下 |

**A 轮作废为测量，保留为证据。** A 轮用的 9/9 快照早于 `infra/migrations/v31_metric_lineage.sql`，fixture 缺 `metric_lineage` 表，`run` 在 20 题中 21 次抛 `UndefinedTableError` → `tool_error`。B 轮重取 9/13 生产快照（该表存在，0 行，代码路径正常返回 None），`run` 的崩溃从 21 次降到 1 次。**下文除 §1 外全部依据 B 轮。**

原始文件：

| 文件 | 内容 |
|---|---|
| `questions_v33.json` | 20 题原文 |
| `V33A.json` / `V33A_forensics.txt` / `V33A_answers.txt` / `run_v33A.log` | A 轮 |
| `V33B.json` / `V33B_forensics.txt` / `V33B_answers.txt` / `run_v33B.log` | B 轮 |
| `V33_counters.txt` | 两轮计数 |

## 1. 计数

| | A 轮 | B 轮 |
|---|---|---|
| 题数 | 20 | 20 |
| 出了答案 / 门耗尽 | 20 / 0 | 19 / 1 |
| respond 次数 | 62 | 61 |
| 被门拒绝 | 42（67%） | 42（68%） |
| `relation_does_not_fit` | 22 | 25 |
| `unsourced_figure` | 7 | 9 |
| `not_on_ledger` | 10 | 7 |
| `malformed_answer` / `id_in_prose` | 3 / 0 | 0 / 1 |
| 工具调用 | 121 | 106 |
| 工具失败 | 31（其中 `run` 崩 21） | 3（`run` 崩 1，`read_filings` 参数错 2） |
| 读者散文里出现"the chart below / the table below" | 1 | **39（其中 16 次出现在该放数值的位置）** |
| 拒绝原文被拼进散文（"was not computed"） | 15 | 9 |
| 同一数字连续渲染两遍 | 5 | 0 |
| 未取整原始浮点出现在散文 | 4 | 3 |

respond 每轮次数分布（B 轮）：1 次 5 题、2 次 6 题、3 次 1 题、4 次 2 题、5 次 4 题、6 次 1 题、7 次 1 题。

## 2. 读者可见的假陈述

逐条给出原话、账本值、发生位置、以及**门为什么没拦住**。

### F1 — 两个最高级同时反向，零次拒绝（Q08）

答案原话：

> On the latest readings, Amazon spends the most relative to revenue: its capex intensity is the chart below, above Microsoft's the chart below and Alphabet's the chart below latest points. Microsoft earns the least on that spending on the latest ROIC reading: the chart below, below Alphabet's the chart below and Amazon's the chart below.

同一答案自己附的图表最新点：

| | capex intensity | ROIC |
|---|---|---|
| MSFT | 22.9% | 29.7% |
| GOOGL | 22.7% | 24.8% |
| AMZN | **18.4%（最低）** | **16.2%（最低）** |

Amazon 花得**最少**被说成"spends the most"；Microsoft 赚得**最多**被说成"earns the least"。**两个最高级都恰好反了，`gate_refusals=0`。**

门为何不拦：六个比较全部声明为 `relation: series`（见 `V33B_forensics.txt` Q08 respond seq 7）。`claims._check_relation` 对 `series` 只检查"指向的是不是 series fact"，通过。排序这件事在 `claims.ANSWER_SCHEMA` 里**无法表达**——`rank` 只能指向"一个已排序节点的一个条目"，而模型这里根本没建 rank 节点。谓词落进散文，散文里没有任何东西检查它。这正是 `AGENT_GAP_2026-09-10.md` §13 的论点，第一次有了反向最高级的实例。

### F2 — `series`/`table` 关系渲染成"the chart below"，被塞进句子中该放数值的位置（Q01/Q02/Q03/Q04/Q08/Q09/Q10）

`claims._runs_for` 对 `series` 返回 `["the chart below"]`，对 `table` 返回 `["the table below"]`。模型把 `{cN}` 写在句中，于是读者看到：

> Amazon's cash generation still exceeds reported profit in the latest trailing twelve months: operating cash flow was the chart below and net income was the chart below, while cash conversion was 163.6%. （Q01）

> Apple's working-capital days over the last six annual periods were: DSO the chart below, inventory days the chart below, payable days the chart below, and cash conversion cycle the chart below. （Q09）

> Over the last three fiscal years, Microsoft's capex intensity rose **from the chart below**, while its ROIC stayed **around the chart below**. （Q08）

B 轮共 39 处，其中 16 处在"was / is / from / at / above"之后，即语法上必须是一个数值的位置。全部通过门。

### F3 — 日期槽位填进了百分比，且是门把正确答案逼掉的（Q14，两轮均复现）

> The book's worst drawdown over the last year **started on 12.0%** and troughed on 2026-03-27, with a depth of -12.0%.

A 轮同一题第一次 respond 写的是 **`started on 2026-01-07`**，被 `unsourced_figure` 拒；第二次模型把这个正确日期换成了 `{c1}`，而 `c1` 指向 depth fact（0.1196 RATIO），于是"started on 12.0%"被接受。

根因在工具层：程序里 `pick(of=$episodes, key="episodes[0].peak_date")` 的节点 kind 是 `table`，**没有产出任何日期 fact**（B 轮 `verified.matches` 里只有 depth 和 window_return，没有 peak_date）。trough 日期 `2026-03-27` 能留在散文里，只因为它恰好是别的 fact 的 `as_of`，被 `resolve_identity` 认领。**desk 知道的日期无法成为 fact，门又禁止写不在账本上的数字，模型唯一的合法出路就是指错。**

同题还有：

> Over that same window, the book's return was -12.0%, so the market against what we held in the episode is captured by that same moved book-window figure.

depth = 0.11956851201824671，window_return = -0.11956851201824648，**同一个数取反，被当成两件事并列**，然后用一句含糊的因果把它们连起来。这是 §12 W05 类的复现。

### F4 — "right citation, wrong number"：0.85% 被叫做 factor share（Q18）

> The published reconciliation table also shows **factor share 0.85%** and unexplained share 225.5%.

账本：

| fact | 值 |
|---|---|
| `portfolio.reconcile.factor_share` | **-1.2547（即 -125.5%）** |
| `portfolio.reconcile.unexplained_share` | 2.2547（225.5%）✓ |
| `portfolio.reconcile.alpha_plus_residual` | **0.00847461（0.85%）** |

0.85% 是 `alpha_plus_residual`，被写成 factor share。**机制更正（见 TRACE_V33.md T4）**：不是值匹配放行，而是模型把 `{c4}` 指向了 alpha_plus_residual 这个 fact，散文却写 "factor share"；真正的 factor_share 声明为 c5 但没放进任何段落，`validate_shape` 的规则是"a claim the prose does not place is not refused"，于是它静默消失。结果同类：右边的字、错边的指针——门比对的是指针与 fact 的 kind，从不比对 `{cN}` 旁的名词与 fact 的 measure。这正是 `numeric_verification` 自己 docstring 写的那句：*"The citation gate proves an id is real. It says nothing about the NUMBER standing next to it."* 该模块是 v1 路径，不在 chat 出口上。

同题还有：**`price.drawdown` 取了 `key: "fall"`，拿到 `HYG.drawdown.fall = 1.8287 MONEY_PER_SHARE`，写成 "For HYG, the drawdown over the period is $1.83."** 回撤报成每股美元。单位声明是对的，选错的是 key，没有任何东西检查这个 key 是否回答了被问的问题。

### F5 — 散文与它自己的表格互相矛盾（Q15）

> The names near issuer limits are in the table below: AAPL is at 15.2% against a 15.0% warning, LLY at 12.5% against 12.0%, and MSFT at 16.0% against 15.0%; **NVDA is not near its issuer limit at 4.1% against 15.0%.**

同一答案的表格：

```
issuer_concentration:AAPL | 15.2% | risk alerts limit value: 15.0%
issuer_concentration:LLY  | 12.5% | risk alerts limit value: 12.0%
issuer_concentration:MSFT | 16.0% | risk alerts limit value: 15.0%
issuer_concentration:NVDA | 4.06% | limit checks breach level: 20.0%
```

散文说 NVDA 对 **15.0%**，表格说 **20.0%**；散文说 4.1%，表格说 4.06%。且该表第二列同时混了 `risk_alerts.limit_value`（三行）和 `limit_checks.breach_level`（一行）——`derive_table` 因为 measure 不同而进入 explicit 模式，把列名留空、每格自报其名，散文却把四行统称为 "warning"。`gate_refusals=0`。

### F6 — 用户说 20%，程序用了 25%，而唯一能让读者发现的地方被渲染坏了（Q15）

问题问的是 "days to liquidate at **20%** of ADV"。程序写的是：

```json
{"fn": "div", "a": "$mv", "b": {"fn": "scale", "of": "$adv", "factor": 0.25}}
```

表头渲染为 `divide(issuer exposures market value, scale(price adv, 0 25))` —— `answer._words()` 把 `.` 替换成空格，`0.25` 变成 `0 25`。**参数被改了，而唯一暴露它的字符串自己被毁掉了。**

另：结果 `JPM 0.0032 (#1)` 被称作 "longest-to-sell name"。单位是天，0.0032 天 = 4.6 分钟。算术自洽，作为答案荒谬，没有任何量纲常识检查。

### F7 — room 指着错误的 tier，负数被说成"还剩多少"（Q11，A 轮）

> MSFT is the closest issuer to its warning tier at 16.1%. The room left to warning is **-1.10% against 20.0%**, which is the smallest warning gap among the issuer-concentration checks shown here.

账本：`of` = `subtract(limit_checks.warning_level, limit_checks.current_value)` = **-0.01105**（已越过 warning），`against` = `limit_checks.breach_level` = **0.20**。

即：**"room to warning" 被渲染成"对着 breach tier"**，且 room 为负却说成 "closest to"（实际已经越线）。`claims._check_relation` 的 `room` 分支只要求 `of` 的 measure 以 `subtract(` 开头或含 `room_to`，`against` 是任意 tier —— warning 的差额配 breach 的门槛，**类型全部合法**。

同题另外两问（到 breach 需要多大涨幅、8% 上限谁会超）被静默丢弃，答案里一个字没提。

### F8 — 引文挂在错误的主体上（Q17，A 轮）

> For AAPL, recent material news includes a trade-secret dispute. Reuters says Apple alleged a defendant in its trade secret case against OpenAI accessed a power converter circuit schematic while at OpenAI **"Eli Lilly (NYSE: LLY) has secured Food and Drug Administration approval for its diabetes drug Mounjaro…"** [Eli Lilly … foreignpolicyjournal com]

> For JPM, the recent material item is litigation: … **"A federal judge on Wednesday rejected the Justice Department's request to dismantle Google's online advertising business"** [Google Avoids Breakup … WSJ]

`quote` 关系只校验 span 是否逐字出现在被引 passage 里。**passage 是否讲的是句子点名的那家公司，没有任何检查。** 这是 Fin-RATE 错误分类 B1-2（entity-attribute hallucination）的直接实例。

### F9 — 同一个量在相邻两句给出两套完全不同的数字（Q17，B 轮）

> Price is already below the 52-week high for every one of the five: AAPL -5.83%, AMZN -0.69%, JPM -5.79%, LLY -1.54%, and GOOGL -3.89%.
> Measured from the 52-week high, the gaps are AAPL -11.3%, AMZN -3.18%, JPM -12.3%, LLY -17.3%, and GOOGL -17.3%.

两句话说同一件事，十个数字无一相同。两句都过门。且前一句刚列的 top five 是 MSFT/AAPL/JPM/LLY/GOOGL，这两句里 MSFT 消失、AMZN 出现。

同题还有：**"I therefore cannot give a valid 10-day number from the ledger 8.76%."** —— 说"给不出数字"的句子末尾挂着一个数字芯片。

同题还有：**"the web-search tool is not available here"** —— `search_web` 在 meta 面上，A 轮同一题用它成功取回了 5 条新闻。模型对自己能力做了一个假陈述。

### F10 — 拒绝原文被逐字拼进读者散文

`absence` 关系的渲染是 fact 的 `text`，即 `program_service._absence_text` 产生的内部诊断句。模型把 `{cN}` 放在句中，读者于是看到：

> …the relevant ratio nodes refused as absent **rank_ratio was not computed: ocf was refused — metric_not_filed: ['AAPL', 'MSFT', 'NVDA', 'AMZN', 'GOOGL'] has no filed facts under 'operating_cash_flow'** and rank_chg was not computed: … （Q07，A 轮）

> AWS's share of Amazon revenue is **aws was not computed — metric_not_filed: AMZN has no filed facts under 'revenue_including_assessed_tax'**; the desk does not hold… （Q19，B 轮）

> …那些 absent 的原因 **netbeta was not computed — unknown_name: run_34042d64f60c holds no figure named 'portfolio.integration.net_beta.market'. A run's names are listed by describe(run_id); an analysis or scenario row's names are on its table.** （Q16，A 轮）

B 轮 9 处，A 轮 15 处。内部节点名、run id、以及给模型看的修复提示，全部进入读者视野。

### F11 — 未取整原始浮点直接给读者（Q07，B 轮）

> the biggest increase in weight since the prior run was AAPL, with a **+0.00468063** change in issuer_exposures.weight; that change ranks first among positions 0.47% (#1).

同一句里，同一个量先以八位原始浮点出现（被 `resolve_number` 精确匹配而放行），再以芯片 `0.47% (#1)` 出现。句尾另有一个 `-0.11% (#10)` 悬挂在一句讲别的事的话后面。

### F12 — 单位跨类的 change，靠声明成两个 level 绕过检查（Q13，A 轮）

> Selling half of NVDA lowers gross exposure **from $10.63M to 100.0%**
> Technology concentration moves **from 33.7% before the sale to $3.58M after the sale**

账本：`exposure_metrics.gross_exposure` = 10629332.0 **MONEY**；`limit_checks.gross_exposure.current_value` = 1.0 **RATIO**。两个不同的 measure、不同的单位，被"from … to …"连成一次变化。**声明为两个 `level` 而不是一个 `change`，`change` 的同 measure 同 subject 检查就不会运行。** 这是 §12 所述"选择更弱的关系即可移除检查"的实例，且 §13 已论证 relation 不能从 fact 推导，所以这条路今天是敞开的。

同题还有：**"versus its warning tier the warning tier of 110.0%"** —— 模型写的"versus its warning tier"加上 `tier` 关系渲染出的"the warning tier of 110.0%"，措辞重复。

### F13 — 越过检查条件后，同一份 payload 被反复重发（Q13）

B 轮 Q13 共 7 次 respond 全被拒，最终走 `_GATE_EXHAUSTED_TEXT`。A 轮同题 8 次 respond，前四次 payload 完全一致（`not_on_ledger` ×4）。`agents/repeats.py` 的 `STOP=2` 只在**完全相同**的 payload 上触发；模型每次改动一两个字符即可绕开，于是整轮预算耗在同一处。

## 3. 按四角色归属

| 角色 | 越界/失职 | 证据 |
|---|---|---|
| **LLM** | 选错 `price.drawdown` 的 key（F4）、把 20% 写成 25%（F6）、对自身能力做假陈述（F9）、重发 payload（F13） | 这些是真正的模型错误，但其中 F4/F6 无人可查，F13 被门的措辞放大 |
| **skill（领域知识）** | 未失职。`push_domains` 每题推送了 2 个 domain，程序骨架被采用 | `meta.pushed` 每题非空 |
| **tool（正交且让 LLM 能执行意图）** | **失职**：`pick(episodes[0].peak_date)` 不产出日期 fact（F3）；`book.explain_episode` 的 holdings 列名与 `column` 能读的名字不一致（A 轮 Q14）；`fundamentals` 接受 ticker 列表却把列表当作单个 ticker 去查（A 轮 Q07 `metric_not_filed: ['AAPL','MSFT',…]`）；`issuer.panel` 返回 `untyped_result`（B 轮 Q07） | F3 直接制造了一句假话 |
| **validation（正确性与可追溯）** | **主要失职**，且是设计性的：排序无法表达故最高级不受检（F1）；`series`/`table` 关系的渲染文本可以出现在数值位置（F2）；数值只对值不对身份（F4）；room 的 `against` 不必是 `of` 所属的那一档（F7）；`quote` 不校验主体（F8）；同一量的两次陈述之间无约束（F9）；跨单位变化可用两个 level 规避（F12）；absence 的内部文本直接出厂（F10） | 见 §2 |

**门的整体表现：61 次 respond 拒掉 42 次，通过的 19 个答案里至少 12 个含读者可见的假陈述或废话。** 拒绝集中在"怎么说"（`relation_does_not_fit` 25 次占 60%），而真正的假陈述全部从 `relation` 合法的路径走出去。

## 4. 一条与设计讨论直接相关的观察

F3 是最值得单独记的一条：**门拒绝了一个正确的日期，模型据此把答案改成了假的。** A 轮 Q14 第一次 respond 里写着 `started on 2026-01-07`，被 `unsourced_figure` 拒绝，因为该日期没能成为 fact；第二次模型改指 depth fact，得到"started on 12.0%"并被接受。在这一步上，门把一个可核验的真陈述换成了一个通过核验的假陈述。
