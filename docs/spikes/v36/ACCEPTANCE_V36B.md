# V36.1 验收记录：B 轮 20 题，与 A 轮对照（2026-09-15）

> 仪器：`scripts/battery_fixture.sh restore /home/ubuntu/backups/battery/battery-2026-09-13.sql.gz`（还原后补跑
> `v36_actor.sql` 与 `v36_analyst_reports.sql`）→ `serve`（:8105，服务工作树代码，日志确认 `/mcp/meta serving 4 tools`）→
> `scripts/conversation_battery.py docs/spikes/v33/questions_v33.json docs/spikes/v36/V36B.json --fixture --concurrency 5 --deny submit_brief`，
> `BATTERY_OWNER_ID=user_3IDBMeAxLTbecvGorzwV7FCeroR`，gpt-5.4-mini。**与 A 轮同问题、同快照、同模型、同并发、同 deny。**
> 文件：`V36B.json`、`V36B_forensics.txt`（沟通表）、`V36B_schema.md`（76 种载体的真实载荷）、`V36B_answers.txt`、
> `V36B_audit.txt`（每条通过的答案与它引用的每条事实并排）、`V36B_run.log`。
>
> **实测期冻结代码。**开跑前 HEAD `baef5fb` / 树 `89ec3a9`；跑完一样，`git status --porcelain --untracked-files=no` 为空，
> `find src tests scripts -newermt <HEAD 提交时间>` 无输出。本轮遇到的每个问题只记录，没有改任何一行代码。
>
> 被测的是 V36.1 的八处修法（`COMMUNICATION_V36A.md` §9）。

## 1. 数字

| | J（V35） | A（V36） | **B（V36.1）** |
|---|---|---|---|
| 出答案 / 20 | 9 | 14 | **15** |
| 通过答案里含读者可见假陈述的题 | 3/9 | 5/14 | **9/15** |
| 假陈述条数 | 3 | 8 | **10** |
| 主分析师 completion 合计 / 中位 | — | 59 / 3 | 60 / 3 |
| 主分析师 prompt 峰值 中位 | 16.9k | 8.2k | 8.3k |
| 域分析师 completion 合计 | — | 220 | 224 |
| 交接覆盖 asked / done / not_done / refused | — | 156 / 111 / 28 / 30 | **142 / 76 / 48 / 18** |
| 报告 verified / refused | — | 21 / 13 | 19 / 15 |

**假陈述的两个数不可直接对照。**A 轮的审计没有查"周期措辞对不对"这一类；按本轮的读法回看 A 轮，`Q09` 把六个年度点写成
"quarter-by-quarter path"、把五年跨度写成 "three-year range"，是同一类而当时没计。所以 A 的真实条数 ≥ 9、题数 ≥ 6。
本轮 10 条里 5 条属这一类（见 §4），它不是 V36.1 造成的，是这一轮才被查的。

**逐题**（A → B）:
```
Q01 ✓→✓  Q02 ✓→✓  Q03 ✓→✗  Q04 ✓→✓  Q05 ✗→✓  Q06 ✗→✓  Q07 ✗→✗  Q08 ✓→✗  Q09 ✓→✓  Q10 ✓→✗
Q11 ✓→✓  Q12 ✓→✓  Q13 ✓→✓  Q14 ✗→✓  Q15 ✗→✓  Q16 ✓→✓  Q17 ✗→✓  Q18 ✓→✗  Q19 ✓→✓  Q20 ✓→✓
```
回来五题 Q05 / Q06 / Q14 / Q15 / Q17；丢四题 Q03 / Q08 / Q10 / Q18。**Q15 是四轮来第一次通过。**

## 2. 八处修法，各自的读数

| 修法 | A 轮 | B 轮 | 判 |
|---|---|---|---|
| **T1** desk 原话随 id 上行 | 门拒绝首因 `unverified_quote` 11 次，吃掉 Q05/Q06/Q14/Q17 四题 | **4 次**，四题全部通过 | **成立**。Q16 引 "net_beta was not computed — unknown_name: run_… holds no figure named '…'"、Q12 引 "bac_roe was not computed — unknown_company: "、Q01 引 "64 more figures were computed and not shown…"，都带 id 过门。Q05/Q20 则把 desk 的意思用主分析师自己的话说出来、不加引号——正是改后的规则 |
| **T2+T3** 拒绝理由与 schema | `read_filings` 被拒 16 次，理由是 "invalid_arguments — ; " | **1 次** | **成立**。read_filings 总调用也从 60 降到 33 |
| **T4** start 不是证据 | 22 次，Q14 的 8/8 预算全花在 readiness 上、题死 | **13 次**，Q14 通过 | **成立** |
| **T5** 造出的书有句柄 | Q13 三条假陈述（基准书当成卖出后的书） | Q13 **零假陈述**，并在答案里说 "I can ask the desk again using the scenario book id it built this turn" | **成立**。句柄进了语言 |
| **V1** brief 一列 lines | 交接首因 `answered_and_explained` **18 次** | **0 次** | **成立**。这一类从协议里消失了 |
| **T6** filter 的拒绝带范围与单位 | Q11 四次静默 `no_entry_satisfies` | 本轮无 | 无复发样本 |
| **T7** run 的 portfolio 错类 id 静态拒 | Q13 一条链八个 absence | **触发 11 次**，type_errors 10→28 | **按设计成立，代价可见**：早拒一次换掉八个静默 absence，但十一次说明分析师照旧这么写（§5 C1） |
| **T9** 报告与 brief 一个口径 | Q11 被拒的断言经 report(verified)→read_report 回到主分析师 | 报告 verified 21→19 / refused 13→15；`read_report` 4 次，其中对 refused 报告只回 problems | **成立** |
| **I1+I2** 仪器 | 8 条边靠推断 | `read_report` 4 步、不合形派单 2 步都在表上；每个 completion 的行带它读进的 chars | **成立**，本文的沟通表不再有推断的边 |

## 3. 我引入的一处回归：Q10 与 Q18

两题都死于 `not_on_ledger`，根因同一处，**是 T1 带来的**：

- 域分析师没能在轮数内交出 brief 时，兜底会铸一条边界事实（"the domain analyst did not file a brief within its turns"），
  记在一个 `status="rejected"` 的 `brief` 步上；
- `ledger.load` 只读 **completed** 步骤，所以这条事实**不在账本上**；
- T1 之前主分析师看不到它的文字和 id，也就引不了；T1 之后 `not_done` 带 `said` 与 `boundary` id 交到主分析师手里，
  它照规则引用，门查账本、查不到 → `unverified_quote` / `not_on_ledger`，两次机会用尽。

证据：`f_8cd751aa3ed5`（Q18）与 `f_eec56db014a9`（Q10）都在 `facts` 表里、`step_id` 指向一个 `brief · rejected` 步；
全轮 4 个这样的步骤。

修法（未做，一行）：兜底的那一步记为 `completed`（分析师确实交代了它做不到），或把边界事实记到单独的 `boundary` 步上——
其余边界事实本来就是这么记的。

另两题不是回归：**Q03** 主分析师给 "$14.7B" 编了一个不存在的 id（`f_8e5d0f8bc1e3` 不在 facts 表），门正确拦下，两次
重写交的是同一段文字；**Q08** 死于 `superlative_without_rank`，是 A 轮就有的老类。

## 4. 十条假陈述，五条属同一类

逐条：句子 / 它引用的事实 / 事实实际是什么。并排见 `V36B_audit.txt`。

### 类 P — 周期措辞不对着事实自己的日期查（5 条）

**① Q04**「It did settle net margin **over the last twelve quarters**: 19.7%, 21.9%, 15.4%, 23.5%, and 31.7%」。
`f_1f94cd5ad569` 是 **5 个年度点**（2021-12-31…2025-12-31）。A 轮同一题写的是 "net margin **for annual points only** …
**That is not the requested twelve-quarter series**"——A 轮说对了，B 轮说错了。

**② Q09**「Days sales outstanding moved from 21.43 to 26.22, …」+「the **three-year** low of -75.83 and the **three-year** high of -56.36」。
`f_4aa8e0c4ceb0` 是 **6 个年度点**，跨 2020-09-26 到 2025-09-27（五年）。问题问的是十二个季度。

**③ Q12**「Its equity multiplier **over the last three years** was 12.66×, 12.21×, and 13.46×」。
`f_44f920287b4f` 的三个点是 **2025-09-30 / 2025-12-31 / 2026-03-31**——三个季度末。

**④ Q06**「Interest expense was $5.55B, $26.10B, and $81.32B. Pretax income was $61.61B, $75.08B, and $72.59B…
the earnings bridge has been fairly steady **over the last three annual points**」。
利息费用的窗口是 **2021–2023**，税前与净利的窗口是 **2023–2025**。两个不同的三年被当成同一个三年并排。

**⑤ Q02**「One year earlier, the same four **quarter-ends** were …」。两条序列都是**年度**点（nd 2022–2025、nd_prev 2021–2025）。

**这一类的机制是确切的，而且在同一个句子里就能看见。**B 轮 Q09 的 finding 原文：

```
The last twelve quarter readings for days sales outstanding are
21.43 [f_4aa8e0c4ceb0@2020-09-26], 26.22 [f_…@2021-09-25], 26.09 [f_…@2022-09-24],
28.10 [f_…@2023-09-30], 31.19 [f_…@2024-09-28], and 34.89 [f_…@2025-09-27].
```
六个年度日期就印在括号里，句子说 "twelve quarter"。Q04 的 finding 更直白：同一句里既写 "over the last twelve quarters"
又写 "the intervening **annual** points"。Q12 的分析师甚至把真相写进了 caveat——"JPM's equity-multiplier series came back
on quarter-end dates rather than three year-end dates"——**然后在 finding 里照写 "over the last three years"**，
主分析师读 finding、不读 caveat。

**角色**：validation。`answer_check` 查数字指向哪条事实、查日期词后面是不是日期（`date_expected`），**但没有一条规则把
"twelve quarters" / "three years" / "a year earlier" 这类周期词对着它旁边那条事实的 `window` 与点间距查**。事实自带
`window {start, end}` 与每个点的日期，这是一次查表，不是判断。交接核对与门用的是同一个 `check`，所以两处一起漏。

### 类 R — 各自独立的四条

**⑥ Q02**「FCF to debt is **9209.8%**, 817.8%, 619.9%, 254.0%」。底层 92.1 / 8.18 / 6.20 / 2.54，unit=RATIO 显示 ×100。
`fcf_to_debt` 的 unit_class 判错，**与 A 轮 ② 同一条，本轮未改**（ACCEPTANCE_V36 §6 的 T3）。

**⑦ Q11**「The **closest** issuer-concentration warning is for LLY」，同一段又说「the desk did not return the warning tier
or breach tier for that issuer concentration check」——**没有档位还断言最接近**。它引的 `f_7cde0c5a0499` 带 `place=8 of=20`，
那是"当前读数"这个向量里的位次，不是"离档位的余量"的位次；MSFT 在同一排序里是 place=3、读数 16.0%。
门没拦：句子里有已链接的图形，`superlative_without_rank` 只要求那个图形**有一个** place，不问它是哪个排序里的 place。
**与 A 轮 ③ 同一条**（ACCEPTANCE_V36 §6 的 V1）。同题还有一条引用 `f_02b28bdcfffe` **不在 facts 表**（A 轮 T4 那一类，读者点开是空的）；Q15 另有一条 `f_00070db93e17` 同样。

**⑧ Q14**「a market factor share of -125.5%, sum of position contributions of 0.38%, and 225.5% unexplained. Read plainly,
that points to the drawdown being **overwhelmingly a market move**」。factor_share **−125.5%** 与 unexplained **+225.5%**
是构造上和为 1 的两个份额；−125.5% 说明因子解释的是**反向**，不是"压倒性的市场移动"。与 A 轮 ⑦ 同一族（份额与收益混读）。

**⑨ Q15**「Ranked slowest to fastest to liquidate at 20% of ADV: JPM 0.0040, LLY 0.0023, …」。这些事实是
`divide(issuer_exposures.market_value, …)` 的**比值**，不是"按 20% ADV 计的天数"。排序是对的，读者看到的数不是问题问的量。

**⑩ Q19**「**AWS is 20% of Amazon's revenue** in the latest annual filing period」。它引的段落说的是
"AWS sales **increased** 20% in 2025"——**增速被读成了份额**，而问题问的正是份额。角色：LLM + skill（读法）。

### 清白的六题

Q01、Q05、Q13、Q16、Q17、Q20。其中 **Q13 / Q16 / Q20 是诚实的部分答**：说清 desk 给不了什么、引用 desk 的原话、
不越界推断。Q13 尤其值得记：A 轮它"出了答案"并带三条假陈述，B 轮它出答案、零假陈述。

## 5. 按节点沟通读这一轮

### 5.1 每对节点（20 题合计）

| 边 | 载体 | A | B |
|---|---|---|---|
| meta → sub | delegate | 26 | **33**（含 2 次不合形，现已记步） |
| sub → tools | run | 79 | **100**（type_errors 10 → 28） |
| sub → tools | read_filings | 60 | **33**（被拒 16 → **1**） |
| sub → tools | compile | 7 | 10 |
| sub → worker | start | 22 | **13** |
| sub → worker | search_web | 7 | 6 |
| sub → ledger | boundary | 49 | 48 |
| sub → check | submit | 67 | 67（退回 51 → 48） |
| sub → store | report | 34 | 34 |
| meta → store | read_report | 推断 5 | **4，已记步** |
| meta → gate | answer | 30 | 30（被拒 16 → 15） |
| 域分析师空转（0 tool call） | — | 28 | 22 |

每种沟通的真实载荷见 `V36B_schema.md`（76 种）。E10 现在多三个字段：`said`（not_done 旁 desk 的原话）、
`desk_said`（finding 引了边界时同上）、`made`（本轮造出的 scenario 书，按 id）。

### 5.2 三处结构性观察

**C1 · T7 触发 11 次说明分析师照旧把 run id 当 portfolio 传。** 早拒是对的（一次类型报告换掉八个静默 absence），
但十一次意味着这是常态写法而不是偶发。它和 T5 是同一件事的两面：主分析师现在可以把 `calc_…` 写进 subjects，
域分析师拿到后**最自然的写法就是 `run(portfolio=<那个 id>)`**，然后被类型拒。要么 `run` 的 `portfolio` 接受
run_/calc_ id（一个动词一个能力，id 自己说明它是什么），要么域分析师的 system 里把"它在 column(run=…) 处用"说得更前。

**C2 · 覆盖率下降换来了诚实。** done 的占比从 0.71 掉到 0.54，not_done 从 28 涨到 48。同一时间出答案数上升、
Q13/Q16/Q20 变成诚实的部分答。V1 把"没settle"变成了一等条目（一行两选一），分析师更容易如实填它；
交接退回的首因也从"一行既答又解释"变成了"这个数没有事实"（`unsourced_figure` 13 次为首因、全轮重放 38 次）。
**这一轮的产品含义是：桌子更愿意说它不知道。**

**C3 · 交接核对的问题总量没降。** 重放里 `unsourced_figure` 38、`mark_mismatch` 34、`superlative_without_rank` 22、
`not_on_ledger` 18。域分析师写数的错仍是最大的一类，核对仍在离错最近的地方拦住它——代价是每次一个 completion。

## 6. 按角色的遗留清单

**validation（新的一条最重）**
- **V4（新，最高价值）周期词不查事实的窗口**：5 条假陈述出自这里，且句子里就印着日期。`answer_check` 已有
  `date_expected`（日期词后须是日期），缺的是"周期词对事实的 window 与点间距"。一次查表。交接与门共用同一个
  `check`，改一处两处都收。
- V1（沿用）`superlative_without_rank` 只要求图形**有一个** place，不问是哪个排序的 place → Q11 ⑦。
- V2（沿用）`subject_mismatch` 只在句子里有 ticker 时跑。
- V3（沿用）`[rep_…]` 这类非事实标记留在读者可见的文字里 → Q06 一处（A 轮 Q20 五处）。

**tool**
- **T10（新，我引入的）兜底边界事实记在 rejected 步上，账本读不到**，而它的 id 与文字已交给主分析师 → Q10 / Q18 两题。**先改这条。**
- T11（新）`run(portfolio=…)` 不接受 run_/calc_ id，与 T5 给主分析师的新能力对不上 → 11 次类型拒。
- T3（沿用）`fcf_to_debt` 的 unit_class → Q02 ⑥。
- T4（沿用）`held_back` 的事实在账本上、不在 `facts` 表里 → Q11、Q15 各一条引用点开是空的。

**LLM（门拦不住的语义错）**
- L1 份额与收益混读 → Q14 ⑧。
- L2 比值当成问题问的量 → Q15 ⑨。
- L3 增速读成份额 → Q19 ⑩。
- L4 编造 id → Q03（门拦下了，题也没了）。

**skill**
- S2（新）`window_return.relative`、`reconcile.factor_share`、`divide(market_value, adv)` 这三处的读法没写进域知识——
  ⑧⑨⑩ 各对应一条。

## 7. 对验收线的结论

| 验收线（沿用 Phase 4 的四条） | 结果 |
|---|---|
| 出答案不低于 A 轮的 14 | **过**：15 |
| 假陈述不高于 A 轮 | **不过**：10 对 8。但两个数不同口径（§1），按同一口径 A ≥ 9 |
| A 轮未通过的四题至少通过一次 | **过**：Q05 / Q06 / Q14 / Q17 全过，另加 Q15（四轮首次） |
| 每题沟通表能指出每次往返的贡献 | **过**，且本轮不再有推断的边（I1+I2） |

**八处修法里七处在数字上成立，一处（T7）按设计成立但暴露了它的对侧（T11）。**买到的是诚实：
四道被引文噎死的题全部回来，Q13 从"三条假陈述"变成"零假陈述的部分答"，桌子更愿意说不知道。
没有买到的是语义正确性——这一点设计稿 §6 写明过，两处核对都只查表。

**下一步按价值排：T10（两题，一行）→ V4（五条假陈述，一次查表，交接与门同时收）→ T11 → V1。**
前两件都不大，且 V4 是第一条能真正压住假陈述条数的规则：它把"周期"变成和"日期""档位""方向"同一类的可查事实。
