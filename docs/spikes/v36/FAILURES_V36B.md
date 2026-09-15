# B 轮五道未出答案的题：问题出在哪儿（2026-09-15）

> 读法同 `COMMUNICATION_V36A.md`：先看每题在节点之间走了几次、每次带了什么，再判谁越界。
> 材料：`V36B_forensics.txt` 的沟通表与当步账本重放、fixture 库 `exposure_battery` 里这五个 session 的
> 全量 `agent_steps.args` 与 `analyst_reports`、以及对 `answer_check` 的只读复现。代码未动。
> 五题：Q03 / Q07 / Q08 / Q10 / Q18。

## 0. 一眼看完

| 题 | 门拒绝两次的首因 | 根因落在 | 一句话 |
|---|---|---|---|
| Q03 | `not_on_ledger` ×2 | **validation**（+ LLM） | 只在申报正文里的数字，门指的两条出路互相指回去；主分析师索性编了一个数和一个 id |
| Q07 | `superlative_without_rank` ×2 | **skill**（+ LLM） | 问题第一个词就是 Rank，可这个域的知识里没有跨发行人排序的程序；五次被拒都没人去跑 rank |
| Q08 | `superlative_without_rank` → `measure_mismatch` | **LLM**（+ tool） | 排序第二次派单时算出来了，主分析师却拿第一次派单的事实去支撑它 |
| Q10 | `not_on_ledger` ×2 | **tool（T10，我引入的）** | 域分析师用尽轮数的兜底事实记在 rejected 步上，账本读不到，而它的 id 已交给主分析师 |
| Q18 | `not_on_ledger` ×2 | **tool（T10，同上）** | 同上 |

五题共同的两件事：
- **每题都有一个域分析师什么也没交出来**（Q03/Q10/Q18 是用尽轮数的兜底；Q07/Q08 是交了但整条被拒）。它取到的事实一条也没到主分析师手里。
- **第二次机会没有改变任何东西**：Q03 与 Q18 两次答案**一字不差**，Q07 只把 "weakest" 换成 "lowest-ranked"（支撑没变），Q10 只删掉了引号留下了 id。修复这一步在这五题里近乎不存在。

## 1. Q03 — 申报正文里的那个数，门指的出路走不通

问题第三行：「whether the filing states how much buyback authorization remains」。

沟通表（37 步，主 5 次 completion、域 11 次）：

| 步 | 方向 | 带了什么 | 结果 |
|---|---|---|---|
| 2 | meta → sub | issuer_capital_allocation [NVDA] 3 行 | |
| 4–8 | sub → tools | run ×2、read_filings item 7、read_filings query | 拿到 capex / 回购 / 分红 / SBC 的份额与序列 |
| 10 | sub → check | 三行全答 | **拒**：`unsourced_figure '$58.5 billion' / '$60.0 billion' / '25'` + `date_expected '25'` |
| 14 | sub → check | 同上重来 | **拒**：同样四条 |
| 17 | meta → gate | 「The filing states that **$14.7B [f_8e5d0f8bc1e3]** remained under authorization」 | **拒** `not_on_ledger` |
| 19 | meta → store | read_report | 报告是 refused，按 T9 只回 problems，**0 chars** |
| 21 | meta → sub | 只为这一行再派一次 | |
| 29 | sub → check | 「… is **$99.3 billion [f_bb4ba7fb29de]**」 | **拒** `mark_mismatch`：*f_… is a passage and does not state this figure: **quote the passage's own words**, or point at the fact that holds it* |
| 33 | sub → check | 「… is **“$99.3 billion”** [f_4e3aba48f2df]」（照做，加了引号） | **拒** `unsourced_figure`：*a number the ledger cannot account for: request the figure, **quote the passage that states it**, or drop it* |
| 35 | sub → check | 用尽轮数的兜底，args 只有 task_id | **拒**（T10） |
| 37 | meta → gate | **与 seq 17 一字不差** | **拒** `not_on_ledger` → 门槛收场 |

**段落里写得清清楚楚**（`f_4e3aba48f2df`）：

> As of July 26, 2026, we were authorized, subject to certain specifications, to repurchase up to **$99.3 billion** of our common stock.

**只读复现**（同一条 passage 事实喂给 `answer_check.check`）：

| 分析师怎么写 | 结果 |
|---|---|
| `是 “$99.3 billion” [f_…]`（实际写法，2 词引文） | `unsourced_figure` — `quoted_spans` 返回空 |
| `说 “authorized to repurchase up to $99.3 billion” [f_…]`（4 词但非逐字） | `unverified_quote` + `unsourced_figure` |
| `说 “we were authorized, subject to certain specifications, to repurchase up to $99.3 billion of our common stock” [f_…]` | **通过** |
| `是 $99.3 billion [f_…]`（只指段落不加引号） | `mark_mismatch` |

根因：`gate._MIN_QUOTED_WORDS = 4`。**少于四个词的引号根本不算引文**——既不按引文核，也不给里面的数字豁免。
于是一个只在正文里出现的数字，唯一能说出口的写法是"把包含它的、≥4 个词的一整段原话逐字引下来"，
而三条拒绝信没有一条说了这件事：`mark_mismatch` 说"引这段的原话"，分析师引了（两个词），换来 `unsourced_figure`
说"引出这个数的那一段"——它引的正是那一段。**两条出路互相指回去。**

**角色**：validation。门的规则是对的（短引号不可核），但它**没有把能走通的那条路说出来**，而 `_MIN_QUOTED_WORDS`
是写作者看不见的常量。附带：主分析师在拿不到这个数时**编了 `$14.7B` 和一个不存在的 id `f_8e5d0f8bc1e3`**（LLM），
第二次原样重发（修复无效）。

## 2. Q07 — 问题的第一个词是 Rank，而这个域不会排序

问题：「**Rank** our five technology holdings by cash conversion … Which name has the weakest conversion」。

| 步 | 方向 | 带了什么 | 结果 |
|---|---|---|---|
| 2 | meta → sub | 派单 | **不合形，拒**（本轮起已记步） |
| 4 | meta → sub | issuer_earnings_quality [AAPL,MSFT,NVDA] 4 行；book_composition 3 行 | 五个名字里只派了三个 |
| 6–8 | sub → worker | start ×3（AAPL/MSFT/NVDA readiness） | |
| 10–12 | sub → tools | run ×3，**三次同一个程序**（每次 804 chars） | 各拿到一家的 conversion |
| 14 | sub → check | | **拒** 7 条：`mark_mismatch '100%' holds='114.4%'`、`direction_conflict`、**`superlative_without_rank` ×3**（strongest / weakest / largest） |
| 16–21 | sub → tools | 一次 type_errors，再两次 run | |
| 23 | sub → check | | **拒** 6 条：**`superlative_without_rank` ×2 仍在**、`subject_mismatch '-2.71%'`（拿了 NVDA 的数说 AAPL/MSFT） |
| 35 | meta → gate | 「AAPL is the **weakest** converter」 | **拒** `superlative_without_rank` |
| 37 | meta → gate | 「AAPL is the **lowest-ranked** converter」 | **拒** 同上 → 门槛收场 |

**没有任何一步跑过排序。**分析师把三家的 conversion 各算各的，用眼睛比出"最弱"。交接连着两次告诉它
*"request compare: rank over it, or drop the word"*，它既没排也没删。主分析师读到 findings 里的比较句，照抄。
第二次只把形容词换了个词——支撑没有变。

为什么它不去排？**`issuer_earnings_quality` 这个域的知识里没有跨发行人排序这件事。**
它的 offers 是"经营现金流与净利并排""应计比率""周转天数"；`issuer_profitability` 才有
"several issuers on one line at once, **ordered**, with the runner-up and the gap"。cash conversion 属前者，
"排序五个名字"属后者，主分析师按内容派到了前者——**ROSTER 没派错域，是那个域的 procedure 缺了这件事的程序**
（要 `vector(三家的比值)` 再 `rank`，语言支持，procedure 里没有示例）。

**角色**：skill 第一（域知识缺跨发行人排序的程序）+ LLM（五次被拒仍写最高级）。
顺带：五个名字只派了三个，另两个 start 后本轮不会回来——问题问的"五个"从一开始就答不全。

## 3. Q08 — 排序算出来了，主分析师指了另一条事实

| 步 | 方向 | 带了什么 | 结果 |
|---|---|---|---|
| 4 / 7 / 10 / 13 | sub → tools | **同一个程序连发四次**（各约 2245 chars） | **四次 type_errors**，四条边界事实 |
| 17 | sub → tools | run | 成 |
| 19 | sub → check | capex 份额用 `capex.divide.revenue` 手算 | **拒** `mark_mismatch` ×2（29.6% vs 29.7%、26.7% vs 26.6%——差 0.1 的抄写错） |
| 26 / 28 | sub(book_market_risk) → check | 两次空 brief | **拒** |
| 31 | meta → gate | 「Microsoft had the **highest** capex intensity …」 | **拒** `superlative_without_rank` ×3 |
| 33 | meta → sub | **再派一次，只要排序** | |
| 41 / 43 | sub → check | 「Capex intensity **ranks**: MSFT, GOOGL, AMZN … 22.9% [f_4875a6487596] …」 | **过**（seq 43 verified） |
| 46 | meta → gate | 「Microsoft ranked highest on capex intensity, with 22.9% **[f_d61ded64c97a@2025-06-30]**」 | **拒** `superlative_without_rank` + `measure_mismatch` → 门槛收场 |

**排序确实被算出来了，而且交接放行了。**主分析师却在说"排第一"的时候，引了**第一次派单**里那条手算的
`capex.divide.revenue` 序列点，而不是第二次派单里带位次的 `capex_intensity` 标量。门的拒绝信把正确的候选
都列了出来（`f_0c165dc97685 vector(capex_intensity) MSFT`、`f_4875a6487596 capex_intensity MSFT`），
还额外报了 `measure_mismatch`：*the sentence says 'capex intensity' but the figure beside it is
capex.divide.revenue; the ledger holds capex_intensity as its own*。

**角色**：LLM 第一（同一个量的两条事实都在账本上，它挑了旧的那条）+ tool（**同一个量有两种说法、两种身份**：
手算的 `capex.divide.revenue` 与登记方法 `capex_intensity`，都在账本上，只有后者带位次）。
附带一条：同一个程序连发四次 type_errors，四次读的是同一份类型报告（read 1187 ch ×3）——
类型报告一次报全是对的，但**分析师没有从中学到东西**，四次里三次一字未改。

## 4. Q10 与 Q18 — 我引入的那处回归（T10）

两题同一个形状，且都**只差这一条**就能出答案。

**Q18**（34 步）：第一个域分析师 `book_drawdown_and_attribution` 干得很好，seq 11 的 brief 通过、报告 verified，
对账那四行答了两行、两行如实说没有。第二个域分析师 `issuer_price_context` 花掉 8 次 completion、5 次 run、
2 次 start，**一条也没交**——seq 30 是用尽轮数的兜底 submit，args 只有 `{task_id}`，记为 **rejected**，
上面挂着边界事实 `f_8cd751aa3ed5`（"the domain analyst did not file a brief within its turns"）。

主分析师拿到的 `not_done` 带着 `said`（那句话）与 `boundary`（那个 id）——**这是 T1 给它的**——于是它照规则写进
答案第三段。门读账本，而 `ledger.load` 只读 **completed** 步骤，这条事实在一个 rejected 步上，查不到：

```
prose[2] not_on_ledger 'f_8cd751aa3ed5'
  this bracket names no fact the desk showed this turn: copy the id from the evidence, or drop the bracket
```

第二次答案**一字不差**，再拒一次，门槛收场。**Q10 完全同形**（`f_eec56db014a9`，`sub:book_market_risk` 在 seq 58 的兜底），
唯一差别是第一次还多报了一条 `unverified_quote`（它把那句话加了引号），第二次删掉引号、留下 id，照样被拒。

全轮这样的兜底步骤共 4 个：Q03 seq 35、Q10 seq 58、Q11 seq 45、Q18 seq 30。**Q11 侥幸活下来**——它没有去引那一条。

**角色**：tool，而且是 V36.1 的 T1 造成的：T1 之前主分析师看不见这条事实的文字和 id，引不了；
T1 之后交给了它，而事实所在的那一步不被账本读。修法一行：那一步记 `completed`（分析师确实交代了它做不到），
或把边界事实记到单独的 `boundary` 步上——**其余 48 条边界事实本来就是这么记的**。

Q10 另有两件值得记：`book_market_risk` 一个域烧掉 **16 次 completion**（全题 21 次里的大半）、5 次 type_errors、
2 次 start；主分析师 read_report 读到的是 refused 报告（按 T9 只回 problems）。

## 5. 五题共同的三处

**A · 用尽轮数的分析师什么都不留下。**Q03/Q10/Q18 各有一个域分析师跑满 8 轮、取了一堆事实（Q10 那个跑了 9 次工具调用），
最后一条 finding 也没交。它取到的事实**在账本上**，主分析师却完全不知道它们存在——上行只有一句
"did not file a brief within its turns"。信息在这里整段掉落，而且掉的是最贵的那一段。

**B · 第二次机会是空的。**五题十次答案里，两次一字不差（Q03、Q18），一次只换了个形容词（Q07），
一次只删了引号（Q10）。原因是结构性的：修复需要的是**证据**，而拒绝信只说哪句话不行。
主分析师在 Q03、Q08 都试过"再派一次单"（这是对的路），Q08 甚至拿到了正确的排序——然后引错了事实。

**C · 同一个程序连发、同一条拒绝连收。**Q08 的四次 type_errors 是同一个程序，Q07 的三次 run 是同一个程序，
Q03 的两次 submit 是同一段文字。类型报告与拒绝信都是"一次报全"的，但**重发的成本是零**，
所以模型倾向于重发而不是改。

## 6. 按角色的修法（按本轮证据排序）

| # | 角色 | 修什么 | 本轮能救回 |
|---|---|---|---|
| **T10** | tool | 兜底的那次 submit 记 `completed`，或把边界事实记到单独的 `boundary` 步 | **Q10、Q18 两题**，一行 |
| **V5** | validation | 拒绝信说出能走通的那条路：`mark_mismatch`/`unsourced_figure` 命中 passage 时，直接给出**那段里包含这个数的 ≥4 词原话**，让它照抄 | **Q03 一题**（分析师五次都在这条路上打转） |
| **S3** | skill | `issuer_earnings_quality`（及同类按发行人算的域）补一条跨发行人排序的程序：`vector(各家的比值)` → `rank` | **Q07 一题** |
| **T12** | tool | 同一个量不要有两条身份不同的事实：手算的 `capex.divide.revenue` 与登记方法 `capex_intensity` | **Q08 一题**（或至少让 `measure_mismatch` 的候选直接写进 repair 的建议） |
| — | LLM | 编造数字与 id（Q03）、五次被拒仍写最高级（Q07）、指旧事实（Q08） | 门都拦住了，代价是题 |

T10 与 V5 加起来是三题，两处都不大。S3 是 skill 的文字，T12 是身份问题（与 §21 遗留的 tool 身份三处同族）。
