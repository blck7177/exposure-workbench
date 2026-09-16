# IMPLEMENTATION PLAN V37 — 七层落点的修复（B 轮之后，2026-09-15）

> 依据：`docs/spikes/v36/ACCEPTANCE_V36B.md`、`FAILURES_V36B.md`、`SOURCE_OF_ERROR_V36B.md`、`CONTEXT_ENGINEERING_V36B.md`，加上本次按域重算的 33 次派单交付表与对代码的逐处核实（每条都带 `文件:行`，按 HEAD `8834583` 读）。
> 起点：HEAD `8834583`，B 轮之后 `src/` 未动；`pytest -m "not live" -q` 基线 **2515 passed / 11 skipped / 309 deselected / 19s**。
> 读法：每一条先说把工作还给哪个角色（LLM = intelligence，skill = domain knowledge，tool = 正交且让 LLM 能执行意图，validation = 正确性与可追溯），再说落在七层的哪一层、改哪一行、怎么测、C 轮的哪个数应当动。
> 两处对既有文档的更正随本计划一并生效：`FAILURES_V36B` §2 说 Q07 "三次同一个程序"不对，`V36B.json` seq 10/11/12 的 ticker 是 AAPL / MSFT / NVDA；B 轮第 11 条假陈述是 Q02 的 "The book's beta to USO is 0.33×"，事实 `f_4a739ad98a13` 是 `XOM.beta.USO`，审计未计。
> **2026-09-16 拍板**：§5 的五项按"最小且 robust"三问判定（错在哪出生、改完同类错还能不能从别的路进来、模型要不要学新东西）并已定案；两处因此改写：A3 不引 Jinja2，改为标签 + 字段测试；措辞过目不再逐提交设门，K1 由测试守卫，四处文字在 Phase F 前一次过目。

## 0. 一句话，与四条不变量

**一句话**：系统现在只保证"读者看到的每个数字都是真的、可打开的"，两道核对都在守这一条；读者真正信的另外两件事没人保证——数字旁边的词（周期、范围、主体）对不对，取到的事实有没有完整到写字的人手里。本计划把这两件事各自还给该做它的角色：可查的变查表（validation），该交的必须交（tool），桌子知道的告诉模型（skill），模型只剩它真正该做的（LLM）。

**不变量**（与 V36 计划 §2 相同，加一条）：
- registry 四步 wrapper、ledger 按 session、两处核对只查表、agent 树深仍为 2、import 法则不变。
- **模型不给 measure 起名**（`docs/PROGRAM_LANGUAGE.md` 规则 1；9/9 复审 R3 的 AWS 案例）。本计划里所有"命名"都是桌子按自己的公式命名，没有任何 `as_quantity` 交给 LLM。
- 不加 fallback。每条改动消灭一类错误，或把一份已有的知识交到该读它的人手里。
- 实测（Phase F）期间冻结代码，只记录。

## 1. 清单总表

| # | 层 | 还给谁 | 问题（B 轮证据） | 改法一句 | 阶段 |
|---|---|---|---|---|---|
| A1 | agent | tool → LLM | 主分析师提示词没有 `caveats` 一词；Q04/Q06/Q12 域分析师 caveat 写对、finding 写错，主分析师只读 finding | 两段 prompt 各一句 + `HOW_TO_CITE` 一句，caveat 与它限定的数字并排 | D |
| A2 | agent | LLM → tool | 一字不差重发：Q03/Q18 两次答案相同，Q08 同一程序四连发，Q07 五次被拒仍写最高级 | 复用 `agents/repeats.py`（V31 规则）到两个 loop：重发不计次、第一次 nudge、第二次结束 | D |
| A3 | agent | tool → LLM | 两段 system prompt 与 E10 都是"一行头 + 生 JSON"，字段语义靠字段名；一个新字段进 E10 没人负责告诉读者（caveats 就是这样） | 现有拼装代码里给每块加 `source` / `use` 标签；一条机械测试：`for_lead` 的每个顶层键必须在 system 文字里被解释。不引 Jinja2 | D |
| M1 | MCP | 仪器 | `tool_call` 行无 actor，沟通表靠"最后开口者"推断（`~`） | actor 随每次调用的 MCP `_meta` 走，bearer 不变 | A |
| T1 | tool | tool | **T10**：兜底边界事实记在 `rejected` 的 brief 步，`ledger.load` 只读 completed，T1 又把 id 交了出去 → Q10/Q18 归零 | 兜底事实记到 `boundary` 步（其余 48 条边界本来就这么记） | A |
| T2 | tool | tool | 用尽轮数的分析师取到的事实一条不上行（Q03/Q10/Q18 三个分析师各 8 轮） | 兜底时把 `seen` 里显示过的图形按 E10 交出（`shown`） | D |
| T3 | tool | tool | `unknown_name` 拒绝信让分析师去 `describe(run_id)`，`describe` 不在域分析师的面上；net beta 是 `book.analysis` 的 yield，拒绝信不说 | 拒绝信只写面上有的动词；带 `nearest` 与 `route`（方法 yield 命中时给 `method(...)` 写法）；静态测试禁面外动词 | C |
| T4 | tool | tool | **T11**：`run(portfolio=run_/calc_)` 静态拒 11 次；Q13 交易域自己的分析师两次都这么写 | `run` 接受 port_ / run_ / calc_ 三种 id，id 自己说明它是什么 | C |
| T5 | tool | tool | 一次 completion 读入无上限（43.5k → 3 token 空回复）；每个结果重复 726 字 `how_to_cite`；序列不带点距；held_back 提示不可执行 | 每 completion 读入上限均分；`how_to_cite` 只在 system；序列带 `spacing`/`span`；held_back 文案给可照抄的 `return` 写法 | D |
| T6 | tool | tool | held_back 的事实在账本、不在 facts 表：抽屉点开为空（Q11、Q15） | `registry.invoke` 写 facts 表时用 `made or shown` | A |
| T7 | service | tool | **T12**：同一个量三条身份（`capex.divide.revenue` / `capex_intensity` / `vector(capex_intensity)`），主分析师挑了没位次的 | 两个 filed line 相除且命中桌子公式时，按公式命名与定单位；模型不命名 | C |
| S1 | service | tool | `fcf_to_debt` 显示 9209.8%（底层 92.1） | 先在 fixture 复算比值与两个输入，再决定改口径还是改 unit_class | C |
| K1 | skill | skill | ROSTER 承诺桌子不给的：`book_market_risk` offers 写 stress losses 与 book factor betas，desk 行写 withheld、run 的 beta 是 not_alone；该域 7 次派单 43 次 completion 换 6 行，23 次 run 只 1 次干净 | 14 域 offers 对 desk / absent / BOUNDARIES 逐条对齐；测试钉住 | E |
| K2 | skill | skill | 域知识缺程序：net beta（`book.analysis`）、跨发行人 cash conversion 排序（Q07 零次 rank）、卖出后用所得买入（Q13） | 三条示例程序，全部在 fixture 上执行 | E |
| K3 | skill | skill | `READINGS` 只被 `describe` 读，`describe` 不在面上：读法从未到过域分析师；缺 factor_share、days-to-liquidate 两条读法 | `system_text` 加 readings 段；新增两条 Reading | E |
| K4 | skill | skill | `issuer_earnings_quality.compare` 三条全是对自己过去比；增速读成份额（Q19）无桌子规则 | compare / desk 行各加一句 | E |
| V4 | validation | LLM → validation | 周期词不对着事实的点距查：5 条假陈述（Q02/Q04/Q09/Q12），日期就印在括号里 | 闭集周期词 × 序列点距的一次查表，交接与门共用 | B |
| V1 | validation | validation | 无数字句子里的最高级不查（Q11 "The closest … is for LLY." 没有图形，整句算 judgement） | 句中点名账本主体时，查该主体有无 place 落在两端 | B |
| V2 | validation | validation | `subject_mismatch` 只认 ticker："the book's beta" 引的是 XOM 的 beta（Q02 第 11 条） | 闭集 book 词 × ticker 主体的查表 | B |
| V3 | validation | validation | `[rep_…]` 留在读者文字里（B Q06，A Q20 ×5） | 非 f_ 的方括号 id 按 `id_in_prose` 拒 | B |
| V5 | validation | tool → validation | 门执行 `_MIN_QUOTED_WORDS = 4` 却从不说；Q03 两条拒绝信互指，五次打转 | `mark_mismatch` / `unsourced_figure` 命中段落时，拒绝信直接给出含该数的 ≥4 词原句 | B |
| V6 | validation | validation | 拼写日期误判：`As of June 30, 2025` 的 30 报 `date_expected`，`January 25, 2026` 的 25 报 `unsourced_figure`；交接首因 6 次 | tokenizer 认月份日期；`date_expected` 认日期与年份 | B |
| U1 | user report | tool | = T6 | | A |
| U2 | user report | validation | = V3 | | B |
| I1 | 仪器 | — | 计数器没有按域的交付表；沟通表不标重发 | `battery_counters` 加按域表；forensics 标 `repeat` | A |

## 2. 分层细目

### 2.1 agent / LLM 层

**A1 · caveats 进主分析师**（SOURCE_OF_ERROR ②，CONTEXT_ENGINEERING C1 的一半）

- 位置：`agents/meta_agent.py:66-75`（`_SYSTEM` 的 "Each analyst comes back with…" 段）；`agents/delegation.py:423-430`（`HOW_TO_CITE`）；`agents/sub_analyst.py:94`（"What you had to assume or leave out goes in caveats; the lead states those to the reader" ——单向承诺）。`for_lead` 已带 `caveats`（`delegation.py:444`），不改。
- 改法（措辞落 `WORDING.md`，Phase F 前一次过目，见 §5）：
  - meta `_SYSTEM` 加：*Each analyst's `caveats` say where a finding is not what your line asked — a series on other dates or another spacing, a proxy used in place of the thing you named. A caveat is stated beside the figure it qualifies; a finding is not complete without it.*
  - `HOW_TO_CITE` 加：*`caveats` qualify the findings above them: write each beside the figures it qualifies.*
  - sub `_SYSTEM` 改：*A figure that does not match the line as asked — other dates, another spacing, a proxy — is said so in the finding itself, and again in caveats.*
- 测试：`tests/test_v36a_fixes.py` 风格：两段 prompt 含 `caveats`；`for_lead` 的 caveats 在 E10（已有）。
- 验收信号：Q04 / Q06 / Q12 型（caveat 写对、finding 写错）为 0；V4 兜底。

**A2 · 重发不算第二次机会**（复用 `agents/repeats.py`，V31 规则，现只 `research_session.py:18` 用）

- 位置：`meta_agent.py:379-395`（repair）、`:422-435`（answer）；`sub_analyst.py:259-269`（run）、`:280-309`（submit）。
- 改法：
  - meta：一轮一个 `Repeats()`。answer / repair 产出的文本与一份已被拒的文本同 sha → 不计 `attempts`，tool 结果或 user 消息用 `repeats.nudge()` 重述被点名的 token；同一文本第二次 → 结束本轮，`gate_refusals` 记 `repeated_answer`。
  - sub：`run` 的 program 与本 loop 内一份返回 `type_errors`（或全 absence）的 program 同 sha → 原结果再回一次 + nudge 一行，**不扣证据预算**；第二次同 sha → 仍回原结果，计数照旧。`submit` 与一份被退回的 submission 同 sha → nudge；第二次 → 走兜底（T1/T2）。
  - 改了一个字节的载荷照常放行：约束的是重复，不是努力。
- 测试：`tests/test_v36_sub_analyst.py` 脚本化分析师三连发同一程序 → 第二次不扣预算、有 nudge；`test_v36_turn_offline.py` 主分析师原文重发 → 不计 attempts。
- 验收信号：B 轮 Q03 / Q18 两次一字不差、Q08 四连发在 C 轮不再消耗 attempts / 预算。

**A3 · 每块上下文带标签，每个字段被解释一次**（CONTEXT_ENGINEERING §2 六处观察；2026-09-16 定案：不引 Jinja2）

- 要消灭的类：模型拿到一块上下文却没被告知它是什么、来自谁、拿它干什么；更根本的是，一个新字段进了 E10，没有任何东西要求有人向读者解释它——`caveats` 从 V36 Phase 1 起就在 E10 里，主分析师的 system 里一次没出现过这个词。模板引擎解决不了这一类，反而有反向风险：JSON 直出至少让每个字段可见，模板里没写到的字段直接不可见。
- 位置：`meta_agent.py:298-313`（三块 system 的拼装）；`sub_analyst.py:179-186`（system + user）；`delegation.for_lead`（E10 的 JSON）与 `HOW_TO_CITE`（`delegation.py:423-430`）；`scripts/v36_wording.py` 不改（仍从代码原样生成过目单）。
- 改法（在现有拼装代码里，不加依赖、不建模板文件）：
  - 三块 system 的一行头改成带 `source` / `trust` / `use` 的标签，正文仍是 JSON：
    ```
    <briefing source="desk catalogue" trust="names and dates only; no figure" use="pick subjects; check the question's premises">{…}</briefing>
    <roster source="skill" use="pick the analyst by what you need to know, not by the question's words">[…]</roster>
    ```
  - E10 的 tool 结果同样包一层 `<analysts source="handoff check, passed" use="copy figures exactly as shown">{…}</analysts>`；域分析师的 user 消息包 `<task>` / `<subjects>` / `<boundaries>`，工具结果包 `<result tool="run">`；`how_to_cite` 移到 system（T5b）。
  - 字段的含义只在 system 说一次：`_SYSTEM` 与 `HOW_TO_CITE` 里每个 E10 顶层键（`status / coverage / findings / not_done / caveats / follow_ups / refused / made / shown / cost / report_id`）各有一句（A1 补的是 `caveats`，T2 补的是 `shown`）。
- 测试：`tests/test_v37_context_labels.py`：用 `for_lead` 对一份含全部字段的 `AnalystResult` 产出 E10，断言它的每个顶层键（递归到 analyst 一层）都出现在 `meta_agent._SYSTEM + delegation.HOW_TO_CITE` 的文字里；同样断言域分析师 user 消息与工具结果的每个顶层键出现在 `sub_analyst._SYSTEM + digest.HOW_TO_CITE` 里。以后任何人往 E10 加字段而不解释，这条测试先红。`test_v36_turn_offline.py` 加断言：主分析师 prompt 里 `<analysts` 标签内含 `"caveats"`。
- 验收信号：主分析师 prompt 峰值不升（B 中位 8.3k）；C 轮 caveat 类假陈述 0。Jinja2 模板留到提示词的循环与条件多到拼装代码读不下去时再议（§7），那是可读性问题，不是正确性问题。

### 2.2 MCP 层

**M1 · actor 随调用走 `_meta`**（AGENT_ARCHITECTURE_V36 §6 的 "NULL（registry 在 MCP 门后写）"）

- 位置：`agents/tool_session.py:119-157`（`ToolSession.call`）；`tools/mcp_server.py:126-147`（`call_tool`）；`tools/registry.py:196-204`（`invoke` 签名）与 `:328-331`（`record_step`）；`sub_analyst.py:249,266`（两处 `ctx.tools_session.call(name, args)`）；`scripts/v36_forensics.py:28-34`（推断规则）。
- 事实：MCP SDK 1.28.1 的 `ClientSession.call_tool(..., *, meta: dict | None)` 与 `Server.request_context.meta` 都在。bearer 不动（D3：同 session 同 bearer），并行的 seq 问题仍等"每个域分析师是否自己的 tool session"，但**归属不再等那个决定**。
- 改法：`call(name, args, *, actor=None)` → `self._client.call_tool(name, args, meta={"actor": actor} if actor else None)`；`call_tool` 里 `meta = server.request_context.meta`，`actor = getattr(meta, "actor", None) or ((getattr(meta, "model_extra", None) or {}).get("actor"))`；`R.invoke(..., actor=actor)` 透传到 `record_step`（四处：unknown tool、invalid args、budget、正常）。sub loop 两处 `call(name, args, actor=actor)`。forensics：有 actor 的 `tool_call` 行不再打 `~`。
- 测试：`tests/test_mcp_identity_binding.py` 加：带 meta 的调用落 `step.actor="sub:x"`；不带 → NULL；`test_v36_actor.py` 加 `invoke(actor=)`。
- 验收信号：C 轮沟通表零推断边。

### 2.3 tool 层

**T1 · 兜底边界事实记到 `boundary` 步**（旧 T10；我在 V36.1 引入的回归）

- 位置：`agents/sub_analyst.py:320-333`；对照 `:256-257` / `:277-278`（其余边界事实的记法）；`services/ledger.py:319-331`（`load` 只读 completed）。
- 改法：兜底分两步记：`_record(ctx, actor, "boundary", "submit", {"of": "submit"}, text, facts=[fact])`（completed，事实上账），再 `_record(ctx, actor, "brief", "submit", {"task_id": …}, text, status="rejected")`（不带事实）。`ledger.load` 不改：账本的定义仍是"completed 步的事实"。
- 测试：`test_v36_sub_analyst.py`：脚本化分析师八轮不 submit → 用记下的步重建 `Ledger`，`holds(fact.id)` 为真；E10 的 `not_done[*].said` / `boundary` 指向它；`answer_check.check` 接受引用它的一句。
- 验收信号：门拒绝 `not_on_ledger` 中此类 0（B 4 次，Q10 / Q18 两题）。

**T2 · 用尽轮数的分析师交出所取**（CONTEXT_ENGINEERING C5）

- 位置：`sub_analyst.py:171`（`seen`：本分析师显示过的每个图形，value 已被 `stamp_ids` 原地改成 `16.0% [f_…]`）；`:320-333`（兜底）；`delegation.py:172-186`（`AnalystResult`）、`:433-450`（`for_lead`）、`:423-430`（`HOW_TO_CITE`）。
- 改法：`AnalystResult.shown: list[dict]`；loop 另收集 `shown_series`（digest 里 series 条目的 id / measure / subject / first / last）。兜底时 `result.shown = [{"value": f["value"], "subject", "measure", "as_of", "place"?, "of"?} for f in seen.values()][:40] + series[:10]`；状态仍 `refused`。`for_lead` 带 `shown`；`HOW_TO_CITE` 加：*`shown` are figures an analyst fetched and did not file: they are on the ledger; write them exactly as shown.* 这些事实来自 completed 的 `tool_call` 步，可引。
- 测试：兜底且 `seen` 非空 → E10 含 `shown`；主分析师引其中一条 → 门通过（offline）。
- 验收信号：Q03 / Q10 / Q18 型：用尽轮数分析师的事实至少一条进入答案或被明确放弃。

**T3 · 拒绝信只写面上有的动词，并带 route**

- 位置：`services/typed_calculator.py:223-230`（`unknown_name`："A run's names are listed by describe(run_id)…"；`describe` 不在 `tools/faces.py:51-53` 的面上）；`services/program_service.py:1027-1028`、`:1051-1052`、`:1080`（同类拒绝，形状可以）；`analytics/skill.py:225-227`（`book.analysis` yields `portfolio.integration.net_beta.<risk>`）；`services/name_table.py:221-226`（`route`）。
- 改法：
  - `unknown_name` 文案：`{rid} holds no figure named {name!r}. Nearest names it holds: …`；去掉 describe 句。
  - 加 `route`：`name_table.route(name)`；再按方法 yield 匹配：`for m in skill.METHODS.values(): if any(fnmatch(name, y.replace("<risk>", "*").replace("<check>", "*")) for y in m.yields)` → `{"is": "a yield of method " + m.name, "call": {fn: "method", name: m.name, subject: "$<run node>", key: name}}`。Q16 的 net beta 由此得到写法。
  - 静态测试 `tests/test_v37_refusals_on_face.py`：扫 `program_service.py` / `typed_calculator.py` / `program_builder.py` / `digest.py` 的字符串字面量，出现 `describe(` / `read_book(` / `compute(` / `read_fundamentals(` / `read_prices(` 即失败（面外动词），除非该名在 `faces.FACE_META_AGENT`。
- 验收信号：C 轮 `unknown_name` 之后的下一次 run 用上 route 给的写法（沟通表可数）。

**T4 · `run` 接受 port_ / run_ / calc_**（旧 T11；FAILURES §C1）

- 位置：`program_service.py:331`（`Sig`："a book's completed run: which = latest | prev | a run_… id"）、`:581-590`（V36.1 的静态拒，删）、`:950-985`（`_p_run`：`which.startswith("run_")` 已能按 id 取 run，此时 `portfolio` 无用）、`:988-995`（`_run_ref` 已接受 `calc_` 字符串）；`tools/definitions.py:414-429`（`RUN_DESCRIPTION`）；`services/name_table.py` 符号表那行 `run(portfolio,which=latest|prev|run_id)`；`docs/PROGRAM_LANGUAGE.md`。
- 改法：`_p_run`：`portfolio.startswith("run_")` → `which = portfolio`；`portfolio.startswith("calc_")` → `resolved = await qn.of_ref(ctx.db, portfolio)`，`node.kind, node.ref = RUN, portfolio`，`as_of` 取行的 `params.as_of`（`_named_context`）；此时若给了 `which` → `type_mismatch "which applies to a portfolio: this is already one run"`。`Sig` 文案：*portfolio: a port_… id (the book; which = latest | prev | a run_… id), or a run_… / calc_… id itself*。删 `:581-590`。
- 需先确认：`scenario_service.hypothetical_book(db, run_id, sales)`（`:104`）对 `calc_` 基书的处理（T5 的文字说 `sell(run=calc_id)` 可用；确认后 Q13 的"卖了再买"可以链式写）。
- 测试：typecheck 接受三种 id；`_p_run("run_x")` 得 RUN ref `run_x`；`_p_run("calc_x")` 后 `column(run=$it, issuer_exposures, weight)` 读到情景书（live，fixture 有 calc 行）。
- 验收信号：type_errors 中 portfolio 错类 0（B 11）；Q13 的 `book_hypothetical_trades` 分析师自己跑通 sell / buy。

**T5 · digest 四处**

- 位置：`services/digest.py:51-58`（`HOW_TO_CITE`）、`:207-216`（series 条目）、`:250-254` 与 `:319-328`（held_back）、`:350-360`（`render`）；`sub_analyst.py:179-186`（system）、`:217-316`（loop）、`:315-316`（`dumps_capped(res, cap)`）。
- 改法：
  - (a) 每次 completion 的读入上限：loop 里本次 completion 有 k 个 tool call → 每个结果 `cap = max(4000, settings.sub_analyst_result_chars // k)`（Q09 seq 12 一次读 43.5k 就是 3 个结果各 16k）。
  - (b) `render(..., how_to_cite=False)`；`dg.HOW_TO_CITE` 拼进域分析师 system 一次。
  - (c) series 条目加 `spacing`（daily / weekly / monthly / quarterly / annual，由点距中位数判；`services/facts.py` 新 `spacing_of(points)`，V4 共用）与 `span`（`"2020-09-26..2025-09-27, 6 points"`）。
  - (d) held_back 文案：*figures computed and on the ledger but not shown: run the same program again with `return` naming only the nodes you need. Their measures: …*
- 测试：`tests/test_v36_digest.py`：spacing 五类；render 无 how_to_cite；loop 一次三个 tool call 的总读入 ≤ 上限。
- 验收信号：3 token 空回复紧跟 >9k 读入 0（B 5）；域分析师 prompt 峰值中位下降（B 每题中位 11 次 completion）。

**T6 · held_back 的事实进 facts 表**

- 位置：`tools/registry.py:334`：`rows_for(shown, …)` → `rows_for(made or shown, …)`（`:324` 账本已用 `made or shown`；`fact_adapters.adapt_all` `:797-804` 返回 `made` = 全部事实）。
- 测试：adapter 扣图的 invoke → `FactRecord` 行数 = `made`。
- 验收信号：抽屉点开为空 0（B：Q11、Q15 各一）。

**T7 · 派生商按桌子自己的公式命名**（旧 T12）

- 位置：`program_service.py:1325`（`_p_binary`）；`typed_calculator.py:836-846`（`_derived_name`：`net_income.divide.total_revenues is nobody's word for a margin`）、`:849-868`（`calculate(as_quantity, as_unit_class)`，`units.refine` 只在算术留有选择时接受声明）；`analytics/formulas.py`（`Formula.inputs / op / unit_class / alternatives`；`capex_intensity` `:378-385`，`inputs=("capex","revenue")`）。
- 改法：`_p_binary` 的 `div` 分支：当 a、b 都是 `fundamentals` 节点（各一条 metric、同 ticker、同 window / months）且存在 `Formula` 满足 `op == "divide"` 且 `inputs == (a.metric, b.metric)`（含 `alternatives`）→ 调 `calculate(..., as_quantity=formula名, as_unit_class=formula.unit_class)`；否则维持 lineage 名。序列对序列同规则（逐点）。**模型不命名**：只有桌子登记过的公式才配名。
- 测试：`div(fundamentals(capex), fundamentals(revenue))` → measure `capex_intensity`、unit ratio、与 `method(capex_intensity)` 同值；`div(ocf, ni)` 无公式 → lineage。
- 验收信号：Q08 型"同量三身份"降为两身份（vector 与 rank 各铸一份不在本轮）。

### 2.4 service 层

**S1 · `fcf_to_debt` 9209.8%**

- 位置：`analytics/formulas.py:186-191`（`inputs=("free_cash_flow","total_debt")`，`unit_class="ratio"`）；`analytics/display_conventions.py:45-50`（RATIO ×100）。
- 事实：B 轮 Q02 的四个底层值 92.1 / 8.18 / 6.20 / 2.54。XOM 的 FCF 对总债不可能是 92 倍，所以先查值再改类：在 fixture 上复算四季的 `free_cash_flow` 与 `total_debt`（`alternatives` 是否把 `total_debt` 解析成了短期或单条科目）。比值本身错 → 修输入口径；比值对而显示错 → `unit_class="multiple"`。
- 测试：fixture 上 XOM `fcf_to_debt` 落在 (0, 5)。
- S2 / S3 / S4 分别并入 T3（yield 的 route、拒绝文案）与 T7。

### 2.5 skill 层（措辞进 `WORDING.md`；K1 由测试守卫，四处文字在 Phase F 前一次过目，见 §5）

**K1 · offers 对 desk / absent / BOUNDARIES 逐条对齐**（先建测试，再落字）

- 位置：`analytics/skill.py:848-935`（`_OFFERS`）；`:718-737`（`book_market_risk`：desk 行 "stress results are withheld pending validation"，absent 行 "correlations … not measures"）；`program_service.py:382-391`（BOUNDARIES："a scenario … does not re-fit betas, volatility, VaR or stress losses"）。
- 已知两条矛盾：`book_market_risk` offers 第 2 行 "the stress losses the desk's shocks produce"、第 1 行 "the book's own factor betas"（run 的 `factor_attributions.beta` 是 not_alone，Q16 原话 "these factors are collinear"）。B 轮该域 7 次派单、43 次 completion、6/24 行，run 23 次只有 1 次干净——主分析师照 ROSTER 派，派进的是桌子给不了的。
- 改法（草案）：`book_market_risk` →
  1. *each name's own sensitivity to the market, to rates and to credit: beta to SPY, TLT and HYG*
  2. *the book's netted beta per risk, from the run's factor fit; the legs name by name are collinear and not given*
  3. *whether risk has risen: a short volatility window against a long one, name by name and for the index*
  4. *how much of a move was market-wide and how much specific, and which names*
  5. *no stress loss: stress results are withheld pending validation, and a scenario does not re-fit them*
  6. *no correlation between holdings and no hidden common bet*
  其余 13 域按同一读法过一遍（`issuer_price_context` 的 "return against a benchmark over a window" 对 BOUNDARIES 第 1 条 "never an as-of date"：加 "over the latest window only, never as of a past date"）。
- 测试（**先于改字提交**，对今天的 offers 必须先红）：`tests/test_v37_offers.py`：每个域的 offers 不得含它自己 `absent` / `desk` 行与 BOUNDARIES 里否定的词（闭集：stress、forecast、correlation、look-through、as of a past date、P/E、EV/EBITDA、FCF yield、name by name 的 factor beta），除非该行以 "no " 开头。这条测试是 K1 的守卫：9/15 的泄漏不是没过目，是没有任何东西把 offers 对着 desk 行查。测试绿了 offers 就可以提交，过目是质量而不是安全。
- 验收信号：`book_market_risk` 派单的 done/asked ≥ 0.5（B 0.25）。

**K2 · 三条示例程序**（`_PROGRAMS`；`tests/test_v30_skill_programs.py` 在 fixture 上逐条执行，live）

- `book_market_risk` 加 *the book's netted beta per risk, and the room to each tier*：`book = run(<port>)` → `analysis = method(book.analysis, subject=$book)` → `net_mkt = pick($analysis, "portfolio.integration.net_beta.market")`、`room_warn = pick($analysis, "portfolio.integration.room_to_warning.<check>")`。
- `issuer_earnings_quality` 加 *cash conversion across names, then the ordering*：每家 `div(fundamentals(ocf, 12m), fundamentals(ni, 12m))` → `conv = vector(entries={<T1>: $c1, <T2>: $c2, <T3>: $c3})` → `weakest = rank($conv, lowest)`；T7 落地后各家的商即得公式名（若登记 `cash_conversion` 公式；否则 lineage）。
- `book_hypothetical_trades` 加 *sell, then buy with the proceeds*：`w = pick(run, "issuer_exposures.<T>.weight")` → `half = mul($w, 0.5)` → `after = buy(sell(run, [{<T>, fraction: 0.5}]), [{<N>, weight: "$half"}])`（`_p_scenario` `:1640` 对 trades 做 `_substitute_literals`，`$half` 可作 weight）。

**K3 · Readings 到达域分析师**

- 位置：`skill.py:351-380`（`READINGS`：`ebit_interest_coverage`、`price.beta`、`book.analysis` 三条）；`:992-1011`（`system_text` / `push_text`：desk / compare / close / absent / programs，**没有 readings**）；`services/catalogue_service.py:697`（唯一读者，在 `describe` 里，`describe` 不在面上）。
- 改法：`push_text` 加 `readings:` 段，列该域 `methods` 中有 Reading 的每条：`{method}: {reads}; meaningless when {meaningless_when}`。新增：
  - `Reading("book.reconcile", "factor_share is the factor-explained share of the move: negative means the factors explain the opposite direction, and unexplained = 1 − factor_share; neither is a return", "a run not completed", "the two accounting identities of return attribution")`
  - `Reading("price.adv", "days to liquidate = market value ÷ (participation × ADV in dollars): the quotient of market value over ADV alone is a ratio, not days, and is not written as days", "fewer than the window's sessions of volume", "CFA Program, market microstructure")`
- 验收信号：Q14 ⑧、Q15 ⑨ 型读错 0。

**K4 · compare / desk 行**

- `issuer_earnings_quality.compare` 加：*across names on one window: the ordering is a rank node, never read by eye*。
- `issuer_business_risk_from_filings.desk` 加：*a percentage in filing prose is what its own sentence says it is: "increased 20%" is growth, not a share; only the quoted words carry it*（Q19）。
- `book_liquidity.desk` 加 days 的读法（与 K3 同句）。

### 2.6 validation 层（`services/answer_check.py`；交接与门共用 `check`，改一处两处收）

**V6 · 拼写日期**（先做：6 次交接首因 + Q03 的 `unsourced '25'`）

- 位置：`services/answer.py:194-204`（`TOKEN`：日期只认 ISO）；`answer_check.py:325-419`（token 循环）、`:603-609`（`date_expected`：日期词后 12 字符内的 `num` 一律报）。
- 改法：`TOKEN` 加 `(?P<date>(?:Jan|Feb|…|December)\.?\s+\d{1,2},?\s+\d{4}|\d{1,2}\s+(?:January|…)\s+\d{4})`；循环里 `kind == "date"`：ISO 化后 `ledger.resolve_identity(iso)` 命中 → identity 链接；否则 `resolve_in_passages` 用原拼写在段落里找 → passage 链接；都没有 → `unsourced_figure` 如今。`date_expected`：`nxt["kind"] in ("date",)` 或 `nxt` 是 `resolve_identity` 命中的四位年份 → 满足。
- 测试：`tests/test_v33_answer_check.py`：`“As of June 30, 2025, we had no commercial paper …” [f_passage]` 通过；`as of June 30` 且事实 as_of 2025-06-30 通过；`as of 30` 仍 `date_expected`。
- 验收信号：交接首因 `date_expected` 0（B 6）。

**V4 · 周期词对点距**（5 条假陈述）

- 位置：`answer_check.py:546-677`（`_check_sentence`）；闭集词表在 `:75-101` 附近；`facts.spacing_of(points)`（T5c 共用）。
- 改法：`PERIOD_WORDS = {quarterly: {"quarter","quarters","quarterly","quarter-end","quarter-ends"}, annual: {"annual","annually","yearly","year-end","year-ends","fiscal year","fiscal years","fiscal-year"}, monthly: {"monthly","month-end"}, daily: {"daily","session","sessions"}}`。规则：句中命中一类周期词，且句中有 ≥1 个**序列点**链接（`period is not None`），且没有任何一个链接序列的 `spacing_of(points)` 等于该类 → `period_mismatch {word, id, spacing, span, fix: "this series is annual (6 points, 2020-09-26..2025-09-27): say annual, or request the quarterly series"}`。第一版只看序列点，不看带 window 的标量（"four quarters" 对一个 12m 流量的歧义留到看 C 轮）。
- 测试：回归语料 `tests/data/v36b_accepted.json`（从 `V36B.json` 抽 15 条通过答案 + 当步账本）→ 新版 `check` 的新增拒绝**恰为** {Q02 "quarter-ends", Q04 "twelve quarters", Q09 "twelve quarter", Q12 "three years"}，其余 11 条不变。
- 验收信号：C 轮通过答案里周期词类假陈述 0（B 5）。

**V1 · 无数字句子里的最高级**

- 位置：`answer_check.py:586-601`（`if words & SUPERLATIVES and groups:` ——Q11 "The closest issuer-concentration warning is for LLY." 无图形，整句归 judgement）。
- 改法：`words & SUPERLATIVES` 且 `not groups` 且句中点名了账本上的 ticker（已有 `named`）→ 取该主体所有带 `place/of` 的事实，`_place_fits` 任一满足即过；否则 `superlative_without_rank`，candidates 给该排序里 place 1 / of 的事实。没点名主体的句子仍是 judgement。
- 验收信号：Q11 ⑦ 型 0。

**V2 · "the book's" 对 ticker 主体**

- 位置：`answer_check.py:555-565`（只认 `tickers`）。
- 改法：`BOOK_WORDS = {"book","book's","portfolio","portfolio's"}`；句中有 book 词、没点名任何 ticker，而某个链接图形的 subject 是 ticker 且 measure 不以 `issuer_exposures.` / `limit_checks.` / `sector_exposures.` / `factor_attributions.` 开头 → `subject_mismatch {fix: "this figure is XOM's price.beta; the sentence says the book's"}`。
- 验收信号：Q02 第 11 条型 0。

**V3 · 非事实括号**

- 位置：`answer_check.py:309-322`（`_CITATION` 只认 `f_`）。
- 改法：`_CITATION` 之后再扫 `\[\s*(rep|tsk|task|rrun|run|calc|sess|msg)_[A-Za-z0-9]+\s*\]` → `id_in_prose {fix: "a report or task id is not for the reader: say what it said, or cite a fact"}`。
- 验收信号：读者可见文字里的 `[rep_…]` 0（B 1，A 5）。

**V5 · 拒绝信给可照抄的原话**（Q03；旧 V5 / C4）

- 位置：`answer_check.py:357-368`（passage 的 `mark_mismatch`）、`:408-419`（G2 的 passages 与 `unsourced_figure`）；`services/ledger.py:306-314`（`resolve_in_passages` 只回 pid）。
- 改法：`ledger.quote_for(tok, pids) -> (pid, span)`：在段落文本里定位该数，取包含它的句子，裁到 ≤30 词、≥4 词。`mark_mismatch`（passage）与 `unsourced_figure`（`resolve_in_passages(tok, all_passages)` 命中）都带 `quote` 与 `passage`，fix 改为 *write it as: “<span>” [pid]*。`delegation.refusal_message` 与 `meta_agent._refusal_message` 渲染 `quote`。`_MIN_QUOTED_WORDS` 不动——规则对，只是从此说出口。
- 验收信号：Q03 型第一次退回信就含可照抄句；同题 submit ≤ 2。

### 2.7 user report 层

- U1 = T6（抽屉不再空）。U2 = V3。web 不改；`ReportPanel` 不显示 `shown`（那是主分析师的输入，不是读者的）。

### 2.8 仪器

- I1 `scripts/battery_counters.py:142+`（`tally`）加按域表：派单数、asked/done、completion、evidence、run 总数 / type_errors / 带 absence / 干净数（M1 之后按 actor 精确）；`scripts/v36_forensics.py` 每行加 `rep` 列（args 的 sha 与前一同载体同 sha → `=`）。
- I2 `tests/data/v36b_accepted.json` 回归语料（V4 用），从 `V36B.json` 与 forensics 的当步账本抽。

## 3. 阶段与顺序

| 阶段 | 内容 | 文件 | 估 |
|---|---|---|---|
| **A** ✅ 一行级 + 仪器 | T1、T6、M1、I1 | `sub_analyst.py`、`registry.py`、`tool_session.py`、`mcp_server.py`、两个脚本 | 已完成 `4e7ecbb` `98ee402` |
| **B** ✅ validation 查表 | 语料 → V6 → V4 → V1 → V2 → V3 → V5 | `answer.py`、`answer_check.py`、`ledger.py`、`facts.py`、`tests/test_v33_answer_check.py`、`tests/data/v36b_accepted.json.gz`、`scripts/v37_corpus.py` | 已完成 `39e6a1c`…`b460a89` |
| **C** ✅ 书侧语言 | T3 → T4 → T7 → S1 | `typed_calculator.py`、`program_service.py`、`skill.py`、`run_reads_service.py`、`tests/test_v37_refusals_on_face.py` | 已完成 `40af76b`…`ab959e6` |
| **D** ✅ 组装层 | T5 → T2 → A2 → A1 → A3 | `digest.py`、`sub_analyst.py`、`delegation.py`、`meta_agent.py`、`v36_wording.py`、`tests/test_v37_context_labels.py` | 已完成 `32f9ee6`…`1d81118` |
| **E** ✅ skill | K1（测试先红后绿）→ K3 → K4 → K2 | `skill.py`、`tests/test_v37_offers.py`、`test_v30_skill_programs.py`（live） | 已完成 `b7600cb` |
| **过目门** | `WORDING.md` 一次过目：A1 三句、K1 十四域 offers、K3 两条 Reading、K4 三句；改一处同步一处后重跑脚本 | `docs/spikes/v36/WORDING.md` | 一次 |
| **F** ✅ C 轮实测 | 同 B 轮条件（fixture、20 题、gpt-5.4-mini、并发 5、deny submit_brief），冻结代码；产出 ACCEPTANCE_V37 + 按域表 + 沟通表；另按用户指示同码跑 gpt-5.6-sol 对照 | `docs/spikes/v37/` | 已跑（2026-09-16），见 §3.4 |

顺序的理由：A 是四处一行级且证据最硬（两题、抽屉、归属）；B 是唯一能压假陈述条数的一层，且有回归语料可以离线证明不误伤；C 决定 book 域的交付率（B 轮 13/20 题的后半句派到 book 域）；D、E 按草稿推进、离线测试全绿即提交，措辞的过目门只设一道，在 F 之前。每阶段一个或几个提交，离线全绿；Phase A 前给 `8834583` 打 tag `v36.1-final`。

## 3.1 已完成（2026-09-16，离线 2515 → 2553）

**Phase A**（`4e7ecbb`、`98ee402`）。T1 兜底边界事实拆到 `boundary` 步（Q10/Q18
的 `not_on_ledger` 根因）；T6 `registry.invoke` 的 facts 表写 `made or shown`
（抽屉不再点开为空）；M1 actor 随 MCP `_meta` 走（SDK 1.28.1 的 `call_tool(meta=)`
与 `request_context.meta`，bearer 不动，真 mount 上测），沟通表的 `~` 因此在新
轮里消失；I1 按域一行的计数表 + 重发标记。**按域表在 B 轮上复现了手算数字**，
并纠正 `FAILURES_V36B` §3：Q08 四次 run 里只有 seq 10 与 13 一字不差，全轮真
重发 7 处（两次答案原样重发、四次程序、一次同一 completion 内重复的 read_filings）。

**Phase B**（`39e6a1c`…`b460a89`）。先建回归语料 `scripts/v37_corpus.py` →
`tests/data/v36b_accepted.json.gz`（15 条通过答案 + 各自当时那本账，2661 条事实，
392 KiB），并证明它能复现该轮；此后每条规则都在它上面量过：

| 规则 | 形状（与计划的差异） | B 轮上的效果 |
|---|---|---|
| V6 拼写日期 | 比计划更小：finder 把 "June 30, 2025" 读成一个 date 令牌并归一成 ISO，`date_expected` 自然满足，账本不动 | 去 16 次拒绝，新增 6 次都指真的缺失日期；Q10 seq 17 的 brief 变干净 |
| V4 周期词 | 两个面（节奏对间距、计数对读数或跨度）；**按实测收窄**：单数 `year-end` 命名一个日期不是节奏 | 恰好拒分析点名的四题（Q02×3/Q04/Q09/Q12），其余十一条不动；全轮 +29，Q09 四句在交接处被拦 |
| V1 无图形的最高级 | **三处按实测收窄**：序数命名自己的位次（"9th-largest" 是真的，顺带修了原规则与 finder 把序数读成数字）、句子要说全那个读数的名字、最高级要被 is/are 断言 | 宽版在 258 段上开火 10 次只有 2 次是目标；收窄后恰好 2 次，都在 Q11 |
| V2 book 词对 ticker 主体 | 按计划；桌子自己的行（issuer_exposures 等）例外 | +2，其中一次在交接处；这是该轮审计漏掉的第 11 条假陈述 |
| V3 `[rep_…]` | 比计划更小：`rep_`/`tsk_` 加进 finder 的 id 前缀表，复用已有 `id_in_prose` | +1（Q06） |
| V5 | **计划错了**：不是"拒绝信给原话"，根因是 `resolve_in_passages` 剥掉令牌的空格而不剥段落的，带单位词的数字永远查不到 | 去 27 次拒绝、零新增；Q03 那次死锁的 finding 变干净 |

全轮 258 段受门文字的拒绝条数 269 → 260，形状比总数重要：去掉约 43 次假拒绝
（unsourced_figure 82→53、date_expected 13→2、mark_mismatch 61→58），加上 34
次真拒绝（period_mismatch 0→29、superlative 34→36、subject_mismatch 1→3、
id_in_prose 10→11）。

## 3.2 Phase C / D / E 的实际形状（2026-09-16，离线 2553 → 2603）

**C（书侧语言）**。T3：拒绝信只说读者叫得动的动词——`describe` 不在域分析师面上，
而三处拒绝都指向它；新增 `skill.method_for_yield` / `call_for_yield`，一个名字若是
某个 book 方法声明的产出就直接给出程序节点（Q16 的净 beta），并加静态扫描
`tests/test_v37_refusals_on_face.py`（七个模块的全部字符串字面量，面从 registry 读）。
T4：`run(portfolio=…)` 收 port_/run_/calc_ 三种 id，删掉 V36.1 的静态拒（那条文字在场，
B 轮仍错十一次）；三种都在 fixture 上实测。T7：两条 filed line 相除且精确命中登记公式时
由桌子命名（模型不命名）。**S1 的结论与计划不同**：在 fixture 上复算后，两样都不该改——
比值算术正确，分母是 XOM 的短端（该发行人一条长期债务科目都没报，cover 因此"完整"），
单位是一个写明理由的旧决定（按机构惯例 FFO/债务是百分比）。真正缺的是 cover 算出的
"没覆盖到什么"没上到事实上：三个键随 note 上行。

**D（组装层）**。T5 四处：读入上限改为每次 completion 的、由它读的结果分摊（B 轮一次
递过 43.5k 换回三个 token）；序列自报 `spacing`/`span`（与门查的是同一个 `facts.spacing_of`）；
726 字的引用规则搬进 system 一次（`book_market_risk` 一轮读过九遍）；held_back 说该写
什么（`return` 收窄）。T2：用尽轮数的分析师把它已看到的图形与序列按 `shown` 交出。
A2：V31 的重发规则搬到两个 loop——重发不计次、不扣证据额度、第二次结束。A1+A3 合成
一处：两侧各把载荷的键分成"要读的"与"记账的"两半写在代码里（`FOR_THE_LEAD_TO_READ`
等），由测试守住——要读的必须在 system 文字里被解释，新键按声明归类；主分析师那段因此
逐键重写并写明 caveat 挨着它限定的数字；五块推送上下文各带 `source`/`use` 标签，提成
命名常量（**工具结果不包标签**：它是 JSON，说明它的 `how_to_cite` 本来就在里面）。

**E（skill）**。K1 的守卫先红后绿，表里每条都注明桌子在哪儿说过、由第一个测试核对，
因为"代码旁边的表能让构建变红，文档里的表不能"（9/15 的过目单挂了一天没人读）。
K3 把 `READINGS` 随域下发（它唯一的读者是面外的 `describe`）并补两条读法。K4 三句。
K2 三条程序全部在 fixture 上执行过，顺带查明 `net_beta` 的风险名是 rates_up /
credit_spreads_widen / equity_down——Q16 用三种拼法要的 "market" 从来不存在。

**一次失误记下来**：`git checkout src/.../skill.py` 一次抹掉了当时未提交的全部 Phase E
改动，重做了一遍。此后改 skill.py 的脚本一律"全部断言通过才写盘"。

## 3.3 过目门（当前所在）

`docs/spikes/v36/WORDING.md` 已重生成（新增 A2 五个标签、B4 digest 读法两节，状态行
写明 V37 动了哪四处、新增哪两处）。待过目：主分析师那段（A1）、`HOW_TO_CITE` 两处、
五个标签、14 段 offers 中改动的两域、两条 Reading 与三句知识。过目之后才跑 Phase F。

## 3.4 Phase F 的实测（2026-09-16）

过目门未过：用户指示 push 之后直接跑 F，本轮用的是 `WORDING.md` 里的草稿措辞。第一次尝试因 OpenAI 余额为零全部失败，充值后重跑；同一套代码又按用户指示用 gpt-5.6-sol 跑了一遍对照。记录在 `docs/spikes/v37/ACCEPTANCE_V37.md`。

| | B | C mini | C sol |
|---|---|---|---|
| 出答案 | 15 | 13 | 18 |
| 假陈述 条 / 题 | 12 / 10（含本次更正） | 10 / 5 | 5 / 3 |
| 轮内崩溃 | 0 | 1 | 0 |

mini 不过线，不回滚。查表与协议类修法在各自瞄准的题上成立（T1、T2、T4、T6、M1、K1、K3、K4、V3、V5）；V1 不成立，V4、V6 各有一处误报；**A2 在修复分支上有一处回归，第二次原样重发让本轮崩溃**（Q13）。mini 七道未答题里五道的首要死因是门的误报，误报分八类、漏报分五类，清单与下一步在验收记录 §8、§9。

## 4. C 轮验收线（对照 B）

| 线 | B | C 目标 |
|---|---|---|
| 出答案 | 15 / 20 | ≥ 15 |
| 出答案且派单每行都做完 | 1 / 15 | ≥ 5 |
| 通过答案里的假陈述 | 11 条 / 9 题（含 Q02 book beta） | ≤ 3 条，且周期词 / 主体 / 最高级 / rep 四类为 0 |
| 交接覆盖 done / asked | 76 / 142（0.54） | ≥ 0.65 |
| `book_market_risk` run 干净率 | 1 / 23 | ≥ 1 / 2 |
| run `type_errors` | 28 / 100 | ≤ 12 / 100，portfolio 错类 0 |
| 门拒绝 `not_on_ledger` 中兜底事实类 | 4 | 0 |
| 交接首因 `date_expected` | 6 | 0 |
| 域分析师 3 token 空回复紧跟 >9k 读入 | 5 | 0 |
| 一字不差重发计入 attempts / 预算 | Q03、Q18、Q08 | 0 |
| 沟通表推断边 | 全部 tool_call | 0 |

不过线不回滚整轮：按层回滚（每阶段独立提交），并把不过的那层写进 ACCEPTANCE_V37。

## 5. 已拍板（2026-09-16）

判法：三问。错在哪出生，改在出生处不改下游；改完之后同一类错还能不能从别的路进来，能就不 robust；模型要不要学新东西，要就不最小（模型学的会忘，schema 与查表不会）。有现成机制就复用。

| 项 | 定案 | 三问的答案 |
|---|---|---|
| **T4** | `run` 收 port_ / run_ / calc_ 三种 id；`which` 配 run_ / calc_ 时明确 `type_mismatch` | 出生处是 E4 与 E6 两端词汇不一致，不在模型；`_run_ref` 在别处早已收三种，入口动词是唯一不一致的地方；保留静态拒等于让模型学改写规则，B 轮那段文字在场仍错 11 次 |
| **A3** | 不引 Jinja2；现有拼装代码加 `source` / `use` 标签，加"E10 每个顶层键必须在 system 里被解释"的机械测试 | 要消灭的类是"新字段无人解释"，模板消灭不了它、还会让没写到的字段不可见；测试把这一类永久关掉，零依赖。模板是可读性问题，留到 §7 |
| **T7** | 两条 filed line 相除且精确命中登记公式（含 `alternatives` 的显式映射）时，由桌子命名与定单位类；无公式仍是 lineage 名 | 歧义在事实出生时由工具制造；E10 标同读数是应付，拒绝手算商与 skill 自己的示例程序打架且拒绝了工具能做的事；按公式命名让名字只能通过算出该公式得到，模型不命名（规则 1 / R3 不动）。`calculate(as_quantity, as_unit_class)` 已存在 |
| **A2** | V31 原样：第一次重发 nudge、第二次结束；`run` 的重发不走 MCP、不扣证据额度；`submit` 的第二次重发走兜底 | 错在循环把重复当尝试；只加提醒照扣额度依赖模型读提醒，Q08 已演示不读；硬停不依赖模型。`repeats.py` 现成，哈希按 `sort_keys`，改一字节即放行，收窄 `return` 的重跑不是重复 |
| **措辞** | K1 由 `test_v37_offers.py` 守卫，先红后绿再提交；A1 / K3 / K4 与 K1 的文字合成一份 `WORDING.md` 差异，Phase F 前一次过目；D、E 按草稿推进 | 9/15 的泄漏不是没过目，是 offers 没被对着 desk 行查；有机械源的靠测试，没有机械源的（规则、读法）靠过目；门设一道在实测前，而不是五道在每次提交前。"措辞批准与意图批准分开"的规则不变 |

## 6. 风险

| 风险 | 处理 |
|---|---|
| V4 误伤真句子（同一句既提季度序列又提年度序列） | 规则只在"句中**没有任何**链接序列是该点距"时触发；回归语料 15 条通过答案必须只新增四条拒绝 |
| V6 的月份日期正则吞掉别的 token（"May 5" 是日期还是量） | 只认 "月份 + 日 + 年" 三段全的形；两段形不认 |
| T4 放宽后 `which` 与 run_ id 同时给 | 明确 `type_mismatch`；`prev` 对 run_ id 无意义，拒绝信说 |
| T7 的公式匹配把非公式的商错配（`alternatives` 的口径） | 只在 inputs 精确相等（含 alternatives 的显式映射）时命名；`units.refine` 仍校验单位；测试覆盖 capex/revenue 与一个无公式的商 |
| A2 把改动过的载荷当重复 | sha 在 `sort_keys` 序列化上算；改一个字节即放行（V31 已验） |
| A3 加标签后有人再往 E10 加字段却不解释 | `test_v37_context_labels.py` 对 `for_lead` 的每个顶层键查 system 文字，先红 |
| D、E 按草稿推进，过目门在 F 前：草稿文字在离线测试里跑过、没在实测里跑过 | 过目改动只改文字不改代码；改完重跑离线与 `v36_wording.py`，再进 F；F 冻结代码期间不改措辞 |
| T5a 均分读入让单个大结果被裁 | 裁的是 tail rows 并铸 held_back 事实（`fit` 现有行为），不是字节截断 |
| K1 改 offers 让主分析师少派某域 | 这正是目的：ROSTER 只承诺桌子给得了的；沟通表数派单去向 |
| M1 的 `_meta` 被某个中间件剥掉 | `test_mcp_identity_binding.py` 在真 mount 上断言 actor 落行 |

## 7. 本轮不做

- Phase 3 并行与"每个域分析师自己的 tool session"（M1 解决归属，不解决 seq 重号）。
- vector 与 rank 各铸一份事实（T7 只处理手算商的身份）。
- 带 window 的标量的周期词核对（V4 第二版，看 C 轮）。
- research_session / 日报；生产库迁移与镜像；`measure_mismatch` 去留。
- 主分析师在轮内用 `made` 句柄二次派单（Q13）是 LLM 的决定，不用代码逼它。
- Jinja2 分节模板（2026-09-16 定案不引）：等两段提示词的循环与条件多到拼装代码读不下去时再议；那是可读性问题，A3 的标签与字段测试已经关掉正确性那一类。
