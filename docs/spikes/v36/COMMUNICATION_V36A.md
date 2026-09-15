# V36 A 轮：按节点沟通读 20 题（2026-09-15）

> 读法（9/15 定）：先列节点；数每对节点之间沟通了几次；每种沟通给字段名和一条真实样例；再按四角色判谁越界，再按七层讲位置 / 原因 / 修法 / 效果。
> 材料：`V36A.json`（20 题，args 截到 4000）；fixture 库 `exposure_battery` 的 `agent_steps`（这 20 个 session 共 660 行，args 未截断）与 `analyst_reports`（34 行）；`V36A_forensics.txt` 的沟通表与当步账本重放。三种没有落库的正文——工具结果给域分析师的 digest（E7b）、交接核对的退回信（E9）、delegate 的返回（E10）——按代码从账本与报告表重建，方法写在 §3 各条下。
> 与 `ACCEPTANCE_V36.md` 的关系：那份读结果（出答案数、假陈述）；这份读过程（每次往返带了什么、白跑了多少）。两处结论不同的地方在 §7 列出。

## 1. 节点

| 节点 | 是什么 | 读 | 写 |
|---|---|---|---|
| user / API | 问题进、消息出 | — | `POST /messages {text}`；`AgentMessage{content, citations, meta}` |
| meta | 主分析师 LLM（`agents/meta_agent.py`），一题一个 | 角色 + 一条规则、BRIEFING、ROSTER、delegate 的返回、read_report 的返回、拒绝信 | `delegate(tasks)`、散文、`repair_answer` |
| sub:<域> | 域分析师 LLM（`agents/sub_analyst.py`），一 task 一个；本轮 40 个 | task、主体目录、该域 PROCEDURE、语言签名、工具结果的 digest | `compile`、`run`、`read_filings`、`search_web`、`start`、`submit` |
| tools | MCP 面上的 `run` / `read_filings`（registry 门后）；`compile` 进程内 | 参数 | 结果 + facts，或拒绝 |
| worker | `start` / `search_web`（registry 记为 delegation 类） | 参数 | task id / 来源。fixture 下 `start` 的任务无人执行，轮内本来也不会返回 |
| ledger | 账本：registry 落的 facts + 域分析师铸的边界事实（step `boundary`） | — | — |
| check | 交接核对 `delegation.handoff_check`（代码，不用 LLM） | brief + report + 当步账本 | 退回信；通过则拼 E10 |
| store | `analyst_reports`（step `report` 写，`read_report` 读） | report 正文过 `answer_check` | verified / refused |
| gate | `answer_check`（代码） | 散文 + 账本 | accepted / 拒绝信 |

## 2. 沟通了几次

### 2.1 全轮（20 题）每对节点

| 边 | 载体 | 次数 | 其中没把信息往前推的 | 说明 |
|---|---|---|---|---|
| user → meta | 问题 | 20 | — | |
| meta → sub | delegate | 26 次调用 / 40 个 task | 3 次派单不合形（未记步，§5 W8） | 12 题一次派单，8 题两次；Q13 第二次派了两个域 |
| sub → tools | run | 79 | type_errors 10；带 absence 节点 31 | 每个分析师中位 2 次。**与 J 轮完全相同：79 次** |
| sub → tools | read_filings | 60 | invalid arguments 16；section_not_found 8；not_indexed 1 | 16 次拒绝到分析师手里是**空理由**（W1） |
| sub → tools | compile | 7 | — | 5 个分析师用过；用过的分析师随后的 run 没有 type_errors |
| sub → worker | start | 22 | 22 | 计入分析师的 8 次证据预算（W4） |
| sub → worker | search_web | 7 | 1（预算耗尽 5/5） | |
| tools → sub | digest（E7b） | 146（= 79 + 60 + 7） | 15 次 held_back；16 次空理由 | 未落库；§3.4 重建 |
| sub → ledger | boundary 步 | 49 步 / 49 条边界事实 | — | error 24（invalid_arguments 16 + section_not_found 8）、held_back 15、type 10、data_absent 3、budget 1 |
| sub → check | submit | 67 | 51 被退回 | 每个分析师 1.68 次 |
| check → sub | 退回信（E9） | 51 | — | 首因：answered_and_explained 18、mark_mismatch 8、measure_mismatch 5、id_in_prose 4、其余 16 |
| sub → store | report | 34 | — | verified 21 / refused 13 |
| check → meta | E10 | 26 | — | 合计 asked 156 / done 111 / not_done 28 / refused 30 |
| meta → store | read_report | 推断 5 | — | **未记步**（W8）；从 26–76 个输出 token 的 completion 与随后答案的措辞推断 |
| meta → gate | answer | 30 | 16 被拒 | 首因 unverified_quote 9、superlative_without_rank 6、measure_mismatch 1 |
| gate → meta | 拒绝信 | 16 | — | |
| meta → user | AgentMessage | 20 | 6 条是门槛文案 | |

节点自己在干活的次数（不是沟通）：meta completion 59（中位 3）；sub completion 220（每题中位 11，每分析师中位 5）。**sub 的 220 次里 28 次是 0 个 tool call 被 nudge**：15 次输出 ≤10 个 token（近乎空白，模型没说话），13 次写了散文没调工具；这 28 次占 sub prompt 开销的 13%（312k tokens）。

往返合计 326（含 28 次 nudge），其中 143 次没把信息往前推（44%）：read_filings 空理由 16、type_errors 10、start 22、submit 退回 51、answer 拒绝 16、nudge 28。submit 退回是核对在干活，但每次都是一次 sub completion（平均 12k prompt tokens）。

Token 与时间：prompt tokens 全轮 2.85M（meta 403k / sub 2.44M），J 轮 913k；每题中位 146k 对 J 的 39k（3.7 倍）；主分析师峰值中位 8.2k 对 J 的 16.9k。completion 279 对 J 的 84。20 题 809 秒（并发 5），最长 Q15 86 s、Q13 75 s。**取证的量没变（run 79 = 79），变的是写字的人和写的遍数。**

### 2.2 逐题

括号里是没把信息往前推的次数：run(type_errors / 带 absence 节点)、read_filings(拒 / 错)、submit(退回)、answer(拒)、sub 完成(空转)。

| 题 | 结果 | 域 | meta 完成 | sub 完成(空转) | run(type/absence) | read_filings(拒/错) | start | submit(拒) | answer(拒) | 覆盖 done/asked | sub prompt tok | 秒 |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| Q01 | ✓ | 2 | 2 | 8(1) | 5(1/1) | 1(0/1) | 0 | 3(2) | 1(0) | 5/5 | 70k | 34 |
| Q02 | ✓ | 4 | 2 | 17(2) | 3(0/2) | 9(6/1) | 1 | 5(3) | 1(0) | 9/13 | 146k | 37 |
| Q03 | ✓ | 1 | 3 | 6(0) | 1(0/0) | 5(5/0) | 0 | 2(2) | 1(0) | 1/3 | 67k | 27 |
| Q04 | ✓ | 4 | 3 | 24(4) | 5(0/5) | 8(2/3) | 4 | 6(4) | 1(0) | 10/14 | 208k | 57 |
| Q05 | ✗ | 1 | 4 | 5(0) | 1(0/0) | 3(0/0) | 0 | 2(1) | 2(2) | 6/6 | 60k | 34 |
| Q06 | ✗ | 2 | 3 | 6(1) | 2(0/1) | 0(0/0) | 0 | 2(0) | 2(2) | 7/7 | 48k | 20 |
| Q07 | ✗ | 2 | 3 | 16(2) | 11(4/1) | 1(1/0) | 3 | 3(3) | 2(2) | 7/9 | 188k | 40 |
| Q08 | ✓ | 2 | 2 | 14(2) | 7(2/1) | 3(0/0) | 0 | 4(3) | 1(0) | 6/7 | 178k | 42 |
| Q09 | ✓ | 2 | 2 | 9(2) | 1(0/0) | 7(0/0) | 0 | 3(1) | 1(0) | 9/9 | 123k | 45 |
| Q10 | ✓ | 2 | 4 | 13(1) | 6(1/2) | 4(2/0) | 0 | 3(3) | 2(1) | 1/7 | 142k | 37 |
| Q11 | ✓ | 1 | 3 | 7(1) | 4(0/4) | 0(0/0) | 0 | 2(2) | 1(0) | 3/4 | 96k | 29 |
| Q12 | ✓ | 1 | 4 | 4(0) | 2(0/2) | 0(0/0) | 2 | 2(1) | 2(1) | 5/5 | 36k | 19 |
| Q13 | ✓ | 3 | 4 | 16(1) | 7(0/5) | 0(0/0) | 1 | 6(5) | 2(1) | 6/12 | 183k | 75 |
| Q14 | ✗ | 2 | 3 | 10(5) | 2(0/0) | 6(0/1) | 8 | 3(3) | 2(2) | 4/7 | 135k | 30 |
| Q15 | ✗ | 2 | 3 | 13(1) | 7(0/1) | 0(0/0) | 1 | 4(3) | 2(2) | 7/10 | 191k | 86 |
| Q16 | ✓ | 1 | 3 | 5(1) | 2(0/2) | 0(0/0) | 0 | 2(2) | 2(1) | 2/6 | 55k | 27 |
| Q17 | ✗ | 2 | 3 | 12(1) | 3(0/0) | 0(0/0) | 0 | 4(3) | 2(2) | 8/9 | 141k | 60 |
| Q18 | ✓ | 2 | 2 | 11(1) | 4(0/2) | 0(0/0) | 2 | 3(3) | 1(0) | 7/8 | 85k | 32 |
| Q19 | ✓ | 2 | 4 | 13(1) | 4(2/0) | 8(0/1) | 0 | 4(4) | 1(0) | 5/8 | 168k | 46 |
| Q20 | ✓ | 2 | 2 | 11(1) | 2(0/2) | 5(0/2) | 0 | 4(3) | 1(0) | 3/7 | 112k | 32 |

三条一眼能读出的：Q10 覆盖 1/7 仍"出了答案"（答案是诚实的部分答）；Q14 的 8 次 `start` 就是它的死因（§5 W4）；Q02 的 9 次 read_filings 里 6 次是同一分析师连续被拒（§5 W1）。

## 3. 每种沟通的 schema 与一条真实样例

每条：字段名 → 一条本轮的真实载荷（截短），→ 之后是对方收到它时的摘要。

### 3.1 meta → sub：`delegate`（E4，进程内，step `delegate`）

字段：`tasks[]{domain, subjects[], want_to_know[1..8], facts_to_derive[]?, constraints{window?, compare?}?, context?, follow_up_of?}` + 循环加的 `task_id`。

```json
{"tasks": [{"domain": "book_limits_and_triggers", "task_id": "tsk_34ecff453a86", "subjects": ["port_001"],
  "want_to_know": [
   "1. For each held issuer-concentration check in this portfolio, give the current reading, the warning tier, and the breach tier.",
   "2. Identify which single position is closest to its warning tier, and show the room left to warning for that name.",
   "3. Show the price move in that one name alone that would take it to the breach tier, with everything else fixed.",
   "4. If any single issuer were capped at 8%, list every name that would be over that cap."],
  "facts_to_derive": ["room to warning = warning tier minus current reading",
                      "move to breach in one name alone = the percentage change in that holding's weight needed to reach the breach tier, with all other holdings fixed"],
  "constraints": {"window": "latest", "compare": "ranked by smallest room to warning"}}]}
```
（Q11 seq 2，1062 chars）→ 摘要 `book_limits_and_triggers [port_001] 4 line(s) +2 derive`。

主分析师写的是人话，且把算术写进了 `facts_to_derive`——设计稿要的形状。Q13 把交易本身写进了 `facts_to_derive`（`"sell half of NVDA and buy TLT with the proceeds"`），字段名对不上但域分析师读懂了。

### 3.2 系统 → sub（E5）

不是一条消息，是域分析师的整个初始上下文：system = `sub_analyst._SYSTEM`（≈500 tok）+ `skill.system_text(域)`（question / this desk / compare / close / absent / 示例 program）+ `program_service.signature_text()`；user = `{task, subjects: briefing 切片, boundaries}`。**实测第一次 completion 的 prompt：Q01 6.9k、Q11 6.9k、Q13 7.8k tokens。**之后每个工具结果加 2–6k：Q11 seq 3 → 7 从 6.9k 到 12.5k（一份 16.6k chars 的 digest）。

### 3.3 sub → tools / worker（E6，五种载体）

`compile {request{subjects, want[], derive[], window, compare}}` → `{program, skipped, note}`：
```json
{"request": {"want": ["issuer_exposures.weight", "book"], "derive": ["top5 = issuer_exposures.weight"], "window": "latest", "compare": "rank", "subjects": ["port_001"]}}
```
（Q17 seq 21）→ `13 binding(s), 1 skipped`。

`run {program{let[]{name, expr}, return[]}}`：
```json
{"program": {"let": [
  {"name": "run_now", "expr": {"fn": "run", "which": "latest", "portfolio": "port_001"}},
  {"name": "amzn_weight", "expr": {"fn": "pick", "of": "$run_now", "key": "issuer_exposures:AMZN"}},
  {"name": "book_mv", "expr": {"fn": "pick", "of": "$run_now", "key": "exposure_metrics.portfolio_market_value"}}],
 "return": ["amzn_weight", "book_mv"]}}
```
（Q01 seq 18）→ `keys: program_id, returns, nodes, settled, refused, facts | nodes: run_now=run, amzn_weight=absence, book_mv=scalar`——`issuer_exposures:AMZN` 拼错（该是 `issuer_exposures.AMZN.weight`），下一次 run 才对。

`read_filings {ticker, query?, item?, k?, form_type?}`：
```json
{"k": 10, "item": "7", "query": "commercial paper", "ticker": "MSFT", "form_type": "10-K"}
```
（Q10 seq 9）→ `invalid arguments: 2 problem(s)`。registry 的 problems 是 `[{"field": "query", "problem": "query searches the passages and item reads one Item whole: give one of them, not both", "value": null}, {"field": "item", …}]`。**这段文字域分析师没有看到**，见 3.4。

`search_web {ticker, query, days, reason}`（Q17 seq 6）→ `keys: ticker, query, days, reason, sources, facts`。
`start {kind, subject, reason}`（Q14 seq 21，`readiness AAPL`）→ `keys: enqueued, task_id, kind, ticker, reason, fact, facts`。

### 3.4 tools → sub：digest（E7b，未落库，`services/digest.render`）

字段：`{request, figures[]{id, subject, measure, value("16.0% [f_…]"), unit, as_of, node, place, of, label, rank?, also?}, series[], passages[], started[], boundaries[]{class, fact, text, code?, node?, count?, measures?}, how_to_cite}`。

重建方法：把该 run 步 `evidence_refs` 里的 facts 摆回 `{"facts": {"columns", "rows"}}` 喂给 `digest.render(cap=16000)`；缺的只有 note 里的 `nodes / refused` 两个键。忠实的重建要用 `facts.row_for_model`（absence 的整句在 value 列），本样例没有，见下方更正。Q11 seq 4 那次 run：账本落了 163 条事实，digest 显示 49 条 figure、3 条 boundary，其余 102 条扣下：
```json
{"figures": [
  {"id": "f_62c2e30eaf5e", "subject": "gross_exposure", "measure": "limit_checks.current_value", "value": "100.0% [f_62c2e30eaf5e]", "unit": "RATIO", "as_of": "2026-09-10", "node": "current", "place": 1, "of": 20, "label": "gross_exposure"},
  {"id": "f_b5284856f4cc", "subject": "issuer_concentration:AAPL", "measure": "limit_checks.current_value", "value": "15.2% [f_b5284856f4cc]", "unit": "RATIO", "as_of": "2026-09-10", "node": "current", "place": 4, "of": 20, "label": "issuer_concentration:AAPL"}, "…47 more"],
 "boundaries": [
  {"class": "data_absent", "fact": "f_5eed73ba348b", "node": "over_8pct", "code": "no_entry_satisfies", "text": ""},
  {"class": "data_absent", "fact": "f_8beacb49767b", "node": "price_move_to_breach", "code": "misaligned_vectors", "text": ""},
  {"class": "held_back", "fact": "f_03b1fdf8014f", "by": "digest", "count": 102, "text": "figures computed and on the ledger but not shown here: the request was too wide for one digest; ask again for the names you need",
   "measures": ["AAPL:issuer_exposures.weight", "…", "daily_loss:subtract(limit_checks.breach_level, limit_checks.current_value)", "…"]}]}
```
渲染后 16,650 chars（上限 16,000，扣图后仍贴着上限）。**更正（9/15 晚）**：样例里两条 data_absent 的 `text` 为空是重建的假象——重建喂的是账本的记录形（text 单列），而实际给模型的行形（`facts.row_for_model`）把 absence 的整句放在 `value` 里，域分析师当时读到的是 "over_8pct was not computed — no_entry_satisfies: no entry of $issuer_weights is > 8"。这让 §6 的 L2 更重：分析师看见了这句，仍把 want 4 归咎于 held_back。

**同一入口渲染一次拒绝**（3.3 那次 read_filings，用 registry 的 problems 原样复现）：
```json
{"boundaries": [{"class": "error", "fact": "f_270a1b946cea", "code": "invalid_arguments", "text": "invalid_arguments — ; "}]}
```
`digest.absorb` 拼理由用的是 `p.get("fix") or p.get("detail") or p.get("reason")`，registry 给的键是 `field / problem / value`——两边字段名不一致，理由在传输里丢了。这就是 Q02 一个分析师连续六次发同一个调用的原因：它每次收到的都是 `"invalid_arguments — ; "`。

### 3.5 sub → ledger：`boundary` 步

args `{"of": "run"}`；`evidence_refs = [{"facts": [Fact…]}]`，Fact 形如：
```json
{"id": "f_9e7602f2ee88", "kind": "absence", "measure": "request", "subject": null, "as_of": "n/a", "value": null, "group": "boundary", "standalone": false,
 "text": "the program did not run: every node with a type problem is listed with its fix; nodes that depend on one are not repeated — 'operating_cash_flow' is a FILED LINE, not a method: {fn: 'fundamentals', ticker: '<ticker>', metric: 'operating_cash_flow'}; …",
 "params": {"code": "type_errors", "class": "type", "reason": "cannot"}}
```
（Q01 seq 5）。49 条里 `text` 是整句的只有 type（10）与 held_back（15）；error 类 24 条里 16 条是上面那个空理由，8 条是 `section_not_found`；data_absent 的 text 是代码本身（Q14 的一条是 `"not_indexed"` 四个字）。

### 3.6 sub → check：`submit`（E8，step `brief`）

字段：`brief{findings[]{want, facts[], finding}, not_done[]{want, why, boundary?}, caveats[]?, follow_ups[]?}`、`report{title, text}`；步的 args 另带核对算出的 `coverage`。
```json
{"brief": {"findings": [{"want": 1, "facts": ["f_a1d7242023b3", "f_4e04b8d08dbc", "f_dcda396d3358"],
   "finding": "The current AMZN position size is $756K [f_a1d7242023b3], and it is 7.03% [f_4e04b8d08dbc] of the book. The portfolio market value is $10.75M [f_dcda396d3358], which is the base for that share."}],
  "not_done": [], "follow_ups": [],
  "caveats": ["I answered position size as market value because the desk exposes AMZN’s current issuer exposure that way; the request did not specify share count."]},
 "report": {"title": "AMZN position size and book share in port_001", "text": "I read the latest portfolio run for port_001 as of 2026-09-10. The AMZN issuer exposure is $756K [f_a1d7242023b3] … The earlier attempt to pick AMZN by a colon-style key failed because the run names it issuer_exposures.AMZN.weight rather than issuer_exposures:AMZN.weight."},
 "coverage": {"asked": 1, "done": 1, "not_done": 0, "refused": 0}}
```
（Q01 seq 22，1,076 chars）→ `accepted`。本轮 67 次 submit 的 args 中位 3.4k chars，最大 7.1k。

### 3.7 check → sub：退回信（E9，未落库，`delegation.refusal_message`）

格式：`"{n} problem(s) with your submission. Everything not named here is kept."` + 每条 `[findings[i]] reason ('figure'): fix` + 结尾两句。用当步账本重放 Q13 seq 10 那次退回（5 条问题）：
```
5 problem(s) with your submission. Everything not named here is kept.

[findings[1]] measure_mismatch ('gross exposure'): the sentence says 'gross exposure' but the figure beside it is limit_checks.breach_level, limit_checks.current_value, …; the ledger holds exposure_metrics.gross…
[findings[2]] measure_mismatch ('gross exposure'): …
[findings[2]] change_conflict: limit_checks.current_value and sector_exposures.weight are two different quantities; a change is one measure of one subject at two dates
[findings[3]] measure_mismatch ('gross exposure'): …
[findings[4]] superlative_without_rank ('nearest'): a largest/smallest/most/least rests on the figure's own place in an ordering the desk built; this figure does not hold that place — request compare: rank over it, or drop the word

Submit again with those entries replaced. Request the evidence a fix needs first if you were not shown the figure; a line the desk cannot settle belongs in not_done with its boundary.
```
步的摘要只存首因：`refused: 5 problem(s); measure_mismatch`。C1 的覆盖问题（answered_and_explained 18 次）不在重放里，因为重放跑的是 answer_check 而不是 handoff_check；两个数要合着读。

### 3.8 sub → store：`report` 步

args `{"status": "verified", "report_id": "rep_884fd0d76322"}` → `verified: AMZN position size and book share in port_001`。表 `analyst_reports` 一行：`id, session_id, message_id, task_id, domain, status, title, brief(JSONB), text, blocks, citations, verified, problems, prompt_tokens, completion_tokens, evidence_calls, created_at`。Q11 那行：verified，text 861 chars，brief 里 want 2 在 `refused`。

### 3.9 check → meta：delegate 的返回（E10，未落库，`delegation.for_lead`）

字段：`analysts[]{domain, task_id, report_id?, status(verified|partial|absent|refused), coverage, findings[]{want, asked, finding}, not_done[]{want, why, boundary}, caveats[]?, follow_ups[]?, refused[]{want, reason}?, cost{completions, evidence_calls}}` + `how_to_cite`。从 `analyst_reports.brief` + task 重建 Q13 第一次派单的返回：
```json
{"analysts": [{"domain": "book_hypothetical_trades", "task_id": "tsk_614d83f12ff0", "report_id": "rep_…", "status": "partial",
  "coverage": {"asked": 5, "done": 2, "not_done": 3, "refused": 3},
  "findings": [
   {"want": 1, "asked": "1. Show the book after selling half of NVDA and buying TLT with the full proceeds.",
    "finding": "After selling half of NVDA and buying TLT with the proceeds, the book market value is $10.53M [f_dbf932713d02]. The post-trade issuer weights shown are NVDA at 2.07% [f_feb9e5a3a670] and TLT at 6.14% [f_96ed1c545071]."},
   {"want": 3, "asked": "3. Tell me the new gross exposure, Technology sector concentration, book beta to QQQ, and stress loss under tech_selloff.",
    "finding": "The new gross exposure is $10.53M [f_edda41789488] and Technology sector concentration is 34.0% [f_8a926c09a998]. The beta to QQQ and the stress loss under tech_selloff were requested but were held back in the digest, so I cannot state them from the evidence shown."}],
  "not_done": [
   {"want": 3, "why": "figures computed and on the ledger but not shown here: the request was too wide for one digest; ask again for the names you need", "boundary": "f_af422d476242"},
   {"want": 4, "why": "…同上…", "boundary": "f_af422d476242"}, {"want": 5, "why": "…同上…", "boundary": "f_af422d476242"}],
  "caveats": ["The desk withheld several figures needed to compare every check and to settle the single nearest limit exactly.",
              "I used the prepared portfolio id port_001; the unrecognized run id in the prompt was not used."],
  "refused": [{"want": 2, "reason": "measure_mismatch"}, {"want": 4, "reason": "measure_mismatch"}, {"want": 5, "reason": "superlative_without_rank"}],
  "cost": {"completions": 6, "evidence_calls": 3}}],
 "how_to_cite": "Every figure below is written exactly as you must write it, bracket included: the bracket is the desk's id for that reading and a figure written without it is refused. `read_report(report_id)` opens an analyst's full report."}
```
34 份 brief 的 JSON 中位 2.4k chars，最大 10.3k。19 条 not_done **全部带 boundary id**；62 条 caveats。**E10 里没有任何一处是 desk 的原话**：`why` 是分析师写的，`boundary` 只有 id，边界事实的 `text` 不随行。

### 3.10 meta → gate：answer（E11，step `answer`）与 gate → meta：拒绝信

args `{"text": "…"}`（Q01 seq 25，2,183 chars，accepted；见 `V36A_schema.md` 首条）。拒绝信格式（`meta_agent._refusal_message`）：`"{n} sentence(s) of your reply did not pass. Everything else is KEPT exactly as you wrote it."` + `Replace only these:` + 每句 `[tag] 原句` + 缩进的 `reason ('quote'): fix`。Q05 seq 18 的那条：
```
[…] The desk does hold product and geographic revenue as filing prose, not as computed figures.
      unverified_quote ('The desk holds product and geographic revenue as filing prose, not as computed figures'): quotation marks say these words are verbatim in a text this turn holds — a passage the desk read, the desk's own words for what it could not do, or the question
```
步的摘要：`refused: unverified_quote; 1 problem(s), all listed; the first: prose[3] …`。

### 3.11 meta → user：AgentMessage.meta（E12）与 读者 → store（E13）

E12 的 `meta`（Q01）：`{"prompt_tokens": 8003, "completions": 2, "delegations": [{"domain": "issuer_earnings_quality", "task_id": "tsk_e89c78452e52", "status": "partial", "coverage": {"asked": 4, "done": 4, "not_done": 0, "refused": 0}, "cost": {"completions": 5, "evidence_calls": 4}}, {"domain": "book_composition", …}], "reports": [{"domain": "issuer_earnings_quality", "report_id": "rep_d216c948e152", "status": "refused", "title": "Amazon earnings quality reading"}, …], "briefing_subjects": […], "verified": {…}, "format": "blocks"}`。E13 = `GET /agent/sessions/{sid}/reports/{rid}` 回 3.8 那一行。

## 4. 三题逐步读

### 4.1 Q11 — 设计稿的标准路径，实际走成什么样

设计稿 §6 预期：2 + 2 次 completion、delegate 一次、submit 一次、≈28k prompt tokens。实际：meta 3 + sub 7 次 completion，run 4 次，submit 2 次（都被退回），96k sub prompt tokens。

| 步 | 方向 | 带了什么 | 这次往返推进了什么 |
|---|---|---|---|
| 2 | meta → sub | 4 行 + 2 条派生 + `compare: ranked by smallest room to warning`（3.1 原文） | 意图完整到达；比 J 轮的 request 多了 room 的算术 |
| 4 | sub → tools run | 9 个节点：current / warning / breach / room_to_warning / **nearest = rank(room_to_warning, lowest)** / over_8pct = **filter(weight, >, 8)** … | 排序算了；`over_8pct` 回 `no_entry_satisfies: no entry is > 8`——权重事实是 RATIO 0.16，level 写成 8；163 条事实落账，102 条扣下 |
| 6 | sub（空白 completion，3 个输出 token） | — | 空转一次，12.5k prompt |
| 8 / 11 / 16 | sub → tools run ×3 | 同一程序改写三遍，return 9 → 10 → 10 → 10；`level: 8` 四次没改 | 三次都 held_back；没有一次收窄；no_entry_satisfies 四次相同 |
| 14 | sub → check submit | coverage 1/4：want 2 `nearest` 无排序图形被拒（superlative_without_rank ×2）、want 1 tier_mismatch | 退回信有 3 条问题 |
| 19 | sub → check submit | coverage 3/4：want 2 仍被拒（`nearest`），want 4 写成 not_done「held back」 | 第二次仍不过 → 逐条交：want 1、3 交，want 2 进 refused，want 4 not_done |
| 20 | sub → store report | report 过 answer_check → **verified**；正文含 "The ranked output shows LLY as the nearest issuer-concentration check to warning, followed by AAPL and MSFT in the ordering the desk built" | 这句没数字，核对不跑；被交接拒掉的断言在报告里通过了 |
| 21 | meta → store（推断 read_report） | 26 个输出 token 的 tool call，未记步 | 读到了报告 |
| 23 | meta → gate | "LLY is the closest issuer-concentration check to its warning tier, and the desk’s ranked output puts it first [f_b4fd5940f3e1]" | 通过。事实 f_b4fd… 自带 rank=2；第一是 MSFT |

三处掉落：(a) `filter` 的 level 单位——digest 显示 `16.0%`，语言取 0.16，PROCEDURE 的例子没写 level 是分数；四次同错，分析师最后把 want 4 归咎于 held_back（错误的边界归因）；(b) held_back 的提示「ask again for the names you need」没有导致收窄；(c) **两条上行通道两种过滤**：brief 里 want 2 被 C2 拒两次，同一断言不带数字写进 report 就是 verified，主分析师从 read_report 抄回来，门也不拦——ACCEPTANCE 把 ③ 记为 validation 的执行条件，从沟通上看它先是通道问题。

### 4.2 Q05 — 一句话从工具描述走到读者面前

| 步 | 方向 | 带了什么 |
|---|---|---|
| 1 | meta（1 tool call，未记步） | 第一次派单不合形（推断），下一次才成 |
| 3 | meta → sub | 6 行给 issuer_business_risk_from_filings，第 6 行「does the desk hold any of that as figures?」 |
| 5–11 | sub → tools | read_filings item 1A、compile、run（四条序列）、read_filings item 7、read_filings query |
| 13 | sub → check | **被退回 unverified_quote ×2**：分析师在 finding 里引号引了「figures stated only in filing prose (segment, product and geographic revenue; customers; backlog) are not filed facts: r…」与「The desk does not forecast.」——前者是 `read_filings` 工具 description 的转述，后者是 skill 的 absent 行 |
| 15 | sub → check | 去掉引号，同样的字照写：finding 6 = "The desk holds product and geographic revenue as filing prose, not as computed figures. … but the desk boundary says figures stated only in filing prose … are not filed facts: read_filings quotes them, no program computes them [f_eec4a057a302]" → **通过**（f_eec4a057a302 其实是 Item 8 的一段 passage，不是边界） |
| 17–18 | meta → gate | 主分析师按规则「引 desk 对做不到的原话」把 finding 6 加引号写进答案 → unverified_quote |
| 19–20 | meta → gate（repair） | 改了一个词（does hold），引号还在 → 再拒 → 门槛收场 |

这句话的内容是**真的**，也是 desk 的知识（工具 description、skill 的 absent 行都这么说），但它在账本上没有一条事实；域分析师被交接拒了一次后学会了「不加引号」，主分析师没有这条经验，把分析师的散文当成了 desk 的原话。Q06（"the desk's price methods read the latest session and do not take an as-of date"，finding 3）、Q17（finding 6）、Q14（not_done.why "I ran out of evidence calls…"，它背后的边界事实 text 是 `"not_indexed"` 四个字）同一形状。**四题八次门拒绝，被引的全是域分析师自己的句子；desk 对「做不到」的原话一处都没有到过主分析师手里。**

### 4.3 Q13 — 三个域分析师，一本 after-book，没有通道

| 步 | 方向 | 带了什么 |
|---|---|---|
| 2 | meta → sub hypothetical_trades | 5 行；交易写在 `facts_to_derive`；subjects `[port_001, NVDA, TLT]` |
| 4 | sub → tools run | `run(portfolio="run_e2945c5ebd5a")`——把 BRIEFING 里的 run id 当 portfolio 传，**语言没拒，整条链 8 个节点全 absence**（"checks_after was not computed"…） |
| 6 | sub → tools run | `sell NVDA fraction 0.5` → `buy TLT weight 0.05`：任务说的是「用所得买」，程序写的是固定 5% 权重，没有节点算过所得；after-book 造出来了（TLT 6.14%、NVDA 2.07%），但 return 太宽 → held_back |
| 8 | sub 空白 completion | 3 个输出 token |
| 10 | sub → check | coverage 1/5；5 条问题（3.7 原文）：'gross exposure' 旁边的数是 limit_checks 而不是 exposure_metrics.gross…，'nearest' 无排序 |
| 12 | sub → tools run | 同一程序 return 10 → 11，仍 held_back |
| 15 | sub → check | coverage 2/5；want 2/4/5 进 refused，3/4/5 not_done 共用一条 held_back 边界 → 报告 refused |
| 18 | meta → sub ×2 | 「after the same trade」派给 book_market_risk（beta、stress）与 book_limits_and_triggers（re-run the full limit set after the same trade）；subjects 只能写 `[port_001]`——**after-book 是第一个分析师程序里的一个节点，E10 没有把它作为对象交出来，E4 也写不出它** |
| 20–24 | market_risk → tools | `before/after/… = absence`（unknown_name）→ `start exposure_run` → `run` 基准书：beta=vector、stress=absence |
| 26–28 | market_risk → check | 第一次退回（answered_and_explained），第二次通过：finding "After the trade, the book's beta to QQQ is 1.32× [f_d7514ee79270]"——这条事实是 NVDA 的 price.beta，跑在基准书上 |
| 31–41 | limits → compile → run ×2 → submit ×2 | `run_port_001 = run(latest)`：**基准书**，lc_current 等标成 post-trade；两次退回（'closest' 无排序、mark_mismatch 10.0% / 4.7% 是 room 而不是 tier） |
| 44 | meta → gate | 拒 1 句（measure_mismatch 'gross exposure'） |
| 46 | meta → gate（repair） | 删掉 gross exposure 那句，通过：「After the trade, Technology sector concentration is 35.3% …The book’s beta to QQQ is 1.32×」——两个数都来自基准书 |

三个分析师、16 次 sub completion、184k prompt tokens、75 秒，产出两条假陈述和一条诚实的「不知道」。掉落点不在任何一次核对，而在**没有的那条边**：sub → meta「我造了一本 after-book，它叫 X」和 meta → sub「用 X」。域拆分把一个对象切给了三个人。附带的：`run(portfolio=<run id>)` 该在类型检查处拒（法则 A），却以 8 个 absence 通过。

## 5. 没把信息往前推的往返，按类

| # | 类 | 次数 | 在哪几题 | 机制 |
|---|---|---|---|---|
| W1 | read_filings `invalid arguments`，理由到分析师手里是空串 | 16 / 60 | Q02 ×6（同一分析师连发）、Q03 ×5、Q04 ×2、Q10 ×2、Q08 ×1 | registry 的 problems 键是 `field/problem/value`，`digest.absorb` 读 `fix/detail/reason`；`query` 与 `item` 二选一只写在 wrapper 的 `shapes` 里，schema 里两者都是可空字符串。Q03 的 want 3 与 Q10 的 10-K 段因此丢失；Q02 的一个分析师 0/3 |
| W2 | run `type_errors` | 10 / 79 | Q07 ×4（同一分析师）、Q08 ×2、Q19 ×2、Q01、Q10 | 类型报告一次报全，多数下一次就对；Q07 的 `cash_conversion_cycle: params do not fit the method's schema` 连错两次——这条修法文字没说哪个参数 |
| W3 | run 带 absence 节点 | 31 / 79（126 个节点） | Q04 ×5、Q13 ×5、Q11 ×4 … | 三类：依赖链（Q13 base 传了 run id → 8 个节点全 absence）；`series_not_derivable`；`no_entry_satisfies`（Q11 的 8 对 0.16，四次） |
| W4 | `start` | 22 / 22 | Q14 ×8、Q04 ×4（同一 MRK）、Q07 ×3、Q12 ×2、Q18 ×2 … | 计入分析师 8 次证据预算；不带回任何轮内可用的东西；重复 start 不拒。Q14 的 book_events 8/8 花在 8 个持仓名的 readiness 上 → refused 0/2 → 题死 |
| W5 | submit 被退回 | 51 / 67 | 20 题里 19 题 | 首因 answered_and_explained 18（同一 want 既在 findings 又在 not_done；schema 允许，规则再禁）；其余 33 是分析师写数的错：mark_mismatch、measure_mismatch、id_in_prose、superlative、unsourced——J 轮主分析师犯的那几类，现在在交接处被拦 |
| W6 | sub 空转（0 tool call） | 28 / 220 | 19 题 | 15 次输出 ≤10 token（provider 给了空 completion，多发生在收到一份大 digest 或边界之后），13 次写散文不调工具；每次 nudge 一句、再花一次完整 prompt |
| W7 | answer 被拒 | 16 / 30 | 10 题 | unverified_quote 9（全是分析师散文，§4.2）、superlative_without_rank 6（Q07、Q15 各两次死于此）、measure_mismatch 1 |
| W8 | 未记步的 meta 工具调用 | 8 | Q04/Q05/Q12 的 seq 1（派单不合形）、Q03/Q10/Q11/Q19×2（read_report） | `_read_report` 与 `BadDelegation` 两条路都不 `record_step`；沟通表里这两条边不存在 |
| W9 | held_back 之后 | 15 次扣图；之后同一分析师的下一次 run 收窄 3、不变或更宽 3 | Q15 8 → 16 个 return | 「ask again for the names you need」没有可执行的形状（没有「按名取」的动词，只有再写一个程序） |

## 6. 按四角色判：谁在做不是自己的工作

**tool（没做自己的工作，或输出了不完整的东西）——本轮的大头。**

- T1 **desk 对「做不到」的原话不上行。** 它散在三处：工具 description、skill 的 absent 行、边界事实的 text；只有第三处在账本上，而 E10 只带分析师的转述（`why`、finding）与边界 id，不带原话；边界事实的 text 又常是代码（Q14 的 `not_indexed` 四个字）。结果是主分析师按规则「引 desk 原话」时手里只有分析师的话。4 题 / 8 次门拒绝。（ACCEPTANCE 的 T1 说的是 `not_done.why` 与 caveats；实测 3/4 在 finding 正文。）
- T2 **registry 与 digest 对「一个 problem」的字段名不一致**，拒绝理由在两个 tool 层组件之间丢失。16 次往返。
- T3 **`read_filings` 的二选一不在 schema 里**（法则 B：用 schema 消灭解析规则）。与 T2 合起来就是 W1。
- T4 **`start` 被当证据计预算，且不幂等。** Q14 一题因此死；Q04 同一主体起 4 次。
- T5 **分析师造出的对象没有句柄。** after-book 只存在于第一个分析师的程序里，E10 交不出去、E4 写不进去。Q13 的 ④⑤。这是设计稿 §6「横向发现共享」的最小实例。
- T6 **`filter` 的 level 不做单位检查**：RATIO 0.16 的向量对着 8 比，四次静默 `no_entry_satisfies`；digest 给分析师看的是 `16.0%`。Q11 的 want 4。
- T7 **`run(portfolio=<run id>)` 以 absence 通过而不是类型拒绝**。Q13 seq 4 一整条链。
- T8 **held_back 的提示不可执行**：没有「按名再取」的动词，分析师只能重写整个程序，6 次里 3 次更宽。
- T9 **两条上行通道两种过滤**：brief 里被 C2 拒掉的断言，不带数字写进 report 就 verified，`read_report` 又不记步。Q11 的 ③。

**validation**
- V1 C1 的 `answered_and_explained` 在替 schema 干活：SUBMIT_TOOL 允许同一 want 出现在两列，规则再去禁，18 次退回换来的是 schema 一开始就能表达的形状（每 want 一条，`{finding, facts}` 与 `{why, boundary}` 二选一）。
- V2 报告的「verified」标签覆盖的是「有数字的句子可核」；无数字的断言（Q11 的 nearest）不在覆盖内，标签却让主分析师把它读成可抄。与 ACCEPTANCE 的 V1/V2（superlative / subject 只在句里有图形 / ticker 时才跑）同一形状。

**LLM**
- L1 域分析师写数的错 33 次（mark / measure / id / superlative / unsourced）：核对在离错最近的地方拦住了，代价是 completion。
- L2 误读边界：Q11 把 `no_entry_satisfies` 记成 held_back；Q14 把 `not_indexed` 写成「I ran out of evidence calls」。
- L3 语义翻译：「用所得买 TLT」→ `weight 0.05`；「一年前的同四个季度」→ 同一序列两遍（Q02，绕开了 compile 的守卫）。两处核对都查不到。
- L4 空 completion 15 次（provider 侧）。
- L5 主分析师把分析师散文当 desk 原话引用——被 T1 与提示词诱导。

**skill**
- S1 PROCEDURE 的 `filter(of, >, level)` 没写 level 是分数。
- S2 `book_hypothetical_trades` 的 offers 承诺「with every check re-run」，digest 的 16k 上限交付不了（Q13 not_done 3/4/5 共用一条 held_back）。
- S3 情景类问题按域拆是 D2 的代价：ROSTER 把 beta / stress / 限额放在三个域，主分析师照着拆，对象就断了。

**仪器**
- I1 `read_report` 与不合形的派单不记步（W8）。
- I2 E7b / E9 / E10 不落库，本文靠重建；至少该把大小（chars）记在步上。
- I3 tool_call 行无 actor（已知，Phase 3）。

### 七层：五处最值得先动的

| | 位置 | 原因 | 修法（把工作还给谁） | A 轮能救回 |
|---|---|---|---|---|
| T1 | tool：`delegation.for_lead` / `sub_analyst._fill`（E10 的形状）；service：absence_service 的 statement | desk 原话不在 E10 里；边界事实 text 不是句子 | 还给 tool：E10 每条 not_done 与被引边界带 `said: <fact.text>`（从账本取，不由 LLM 转）；边界事实的 text 由服务端拼成整句（V11 已有先例）；meta 的引用规则改为「只引 E10 里带 id 的 said」；skill 的 absent 行与工具 description 要么铸成事实要么不许引 | Q05 / Q06 / Q14 / Q17 的 8 次门拒绝；其中 Q05、Q06 其余句子已全部通过 |
| T2+T3 | tool：`tools/registry` 与 `services/digest.absorb` 的 problem 键名；`tools/definitions.read_filings` 的 schema | 两个 tool 组件各持一套字段；二选一只在 wrapper 里 | 一个 problem 一种形状（registry 的 `problem` 就是 digest 的 `detail`）；`read_filings` 拆成两个动词或在 schema 里 oneOf——一个动词一个能力 | 16 次往返；Q03 一行、Q10 的 10-K 段、Q02 一个分析师 |
| T4 | tool：`sub_analyst.EVIDENCE_TOOLS`；`start` 的幂等 | start 不带回证据却占额度；重复起不拒 | start 不计证据；同主体重复回 `already_started` | Q14 一题；Q04 4 次 |
| T5 | 协议：E10 / E4 | 造出的对象没有名字可以跨分析师 | E10 加 `made[]{kind, id, label}`；E4 的 subjects 接受它 | Q13 两条假陈述、约 8 次 completion |
| V1 | validation → tool：SUBMIT_TOOL schema | 规则替 schema 干活 | 每 want 一条 entry，二选一 | 18 次退回（51 的 35%） |

其次：T6（level 类型检查 + PROCEDURE 写清分数）、T9（report 的核对与 brief 同口径；read_report 记步）、T7（run 的 portfolio 参数类型拒绝）、I1/I2（仪器）。

## 7. 与 ACCEPTANCE_V36 不同的结论

- F1 / T1 的出处：4 题里 3 题引的是 finding 正文（Q05、Q06、Q17），1 题是 not_done.why（Q14）；Q05 那句的源头是 `read_filings` 的工具 description，Q06 是 skill 的 absent 知识。修法因此不是「把 why 铸成事实」，而是「desk 原话随 id 上行」。
- Q11 ③：先是通道问题（brief 里被拒的断言经 report → read_report 回到主分析师），validation 的执行条件是第二层。
- 对验收线「每题沟通表能指出每次往返的贡献」：能指出，结论是 326 次往返里 143 次没把信息往前推；没有一次派单是派错域的，但 40 个分析师里 2 个一行都没交回（Q02 的 business_risk、Q14 的 book_events），都死于 W1 / W4。
- 与 J 轮的可比数：run 79 = 79；prompt tokens 3.1 倍、completion 3.3 倍；主分析师峰值中位 16.9k → 8.2k（表里的 20k 是冒烟五题）。

## 8. 一句话

架构换对了主人（意图→desk 语言有人负责，run 的次数没变、覆盖率上去了），但**新加的那条边（sub ↔ meta）只运分析师的话，不运 desk 的话**；本轮 44% 的往返是空的，其中最贵的三类（空理由的拒绝、占预算的 start、退回信）都在 tool 层，两条上行通道过滤口径不一致。先动 T1、T2+T3、T4、T5、V1，都是协议与 schema 的改动，不动循环。

## 9. 执行记录（2026-09-15，boss 拍板按 §8 顺序执行，tool 缺口修完再修仪器）

| 缺口 | 提交 | 改了什么 | 验证 |
|---|---|---|---|
| T1 | `f391f80` | E10 的 not_done 带 `said`（账本上边界事实的 text），引用了边界的 finding 带 `desk_said`；工具拒绝铸的边界带上它回答的调用（"read_filings(ticker='MSFT', item='7'): not_indexed"）；主分析师的引号只给带 id 来的文字；域分析师的 why 是读法不是引文 | 离线 +5 |
| T2+T3 | `8b25799` | `digest._problem_text` 读 registry 的 {field, problem} 与核对的 {reason, fix} 两种形状，带字段名，route 随行；read_filings 的 description 写明 EXACTLY ONE of query or item | 用 registry 自己的校验产出拒绝再渲染，断言分析师读到的句子 |
| T4 | `b76d14d` | start 单独计数（`sub_analyst_start_calls=3`），证据预算只算 run / read_filings / search_web；同 (kind, subject) 第二次回 already_started；cost 多 starts | 离线 +1 |
| T5 | `9336ef6` | `_note_of` 对 table 节点带 calc_ ref；digest 列 `made`；分析师收集、E10 带上；parse_tasks 接受 calc_ id，`_subjects_of` 解释它；两段 prompt 各一句 | 离线 +2 |
| V1 | `50452ca` | SUBMIT_TOOL 的 brief 改成 `lines[]`，每条 settled（finding+facts）或 not（why+boundary）；parse_submission 在核对前拒绝既是又不是 / 什么都不是 / 同行两条；旧两列形状仍可解析，规则改名 duplicate_want | 离线 +5 |
| T6+T7 | `b477c04` | filter 的 no_entry_satisfies 带条目范围，level 不可能被满足时说 RATIO 是分数；PROCEDURE 同句；`run(portfolio=run_…/calc_…)` 静态 type_mismatch 并给写法 | 离线 +4 |
| T9 | `669c55d` | 报告 verified 仅当整份 brief 过了且正文过了；否则 refused，problems 全记 | 离线 +1 |
| I1+I2 | `2aff485` | read_report 与不合形派单记步；LlmSession.chat(note) 把 completion 读进的 chars / results 写进 llm_call 行；brief 步带 verdict.problems；forensics 与 counters 读新行 | 离线 +3；两个脚本在 A 轮数据上照常 |

未动：I3（tool_call 行的 actor）等"每个分析师是否自己的 tool session"的决定；validation 的 V2（superlative / subject 只在句里有图形 / ticker 时才跑）与 ACCEPTANCE §6 的 T3 / T4 / S1 未在本轮范围。离线 2490 → 2515。四段 prompt 的改动已重生成进 `WORDING.md`，仍待过目。**这些修法的效果要等下一轮实测（B 轮）才算数**，本文的数字都是 A 轮的。
