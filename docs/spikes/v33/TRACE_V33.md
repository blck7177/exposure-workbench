# V33 逐步 trace：LLM / tool / validation 每一步的输入输出（2026-09-13）

对象：`FINDINGS_V33.md` 登记的问题。方法：从 `exposure_battery` 的 `agent_steps` 按 seq 重放每一步，
门的判决用**当步账本**（seq 小于该步、status=completed 的 evidence_refs）重跑 `claims.check`。
逐题全文在 `trace/Q*.md`，每题一个文件；工具面 schema 在 `trace/tools_schema_meta_face.json`；A 轮的 respond 载荷在 `trace/A_round_respond_attempts.txt`。

## 0. 哪些是原始记录，哪些是重放，哪些丢了

| 层 | 内容 | 状态 |
|---|---|---|
| LLM 输出 | 每次 tool call 的 args（program、claims+prose） | **原始**，`agent_steps.args` jsonb，未截断 |
| LLM 输出 | 与 tool call 并列的 assistant 文本、推理 | **未记录** |
| LLM 输入 | system prompt、推送的 domain 文本 | **可确定性重建**（代码 + 问题的纯函数） |
| LLM 输入 | 每个工具返回给模型的 `facts` 块 | **可精确重建**：`facts.block_for_model(evidence_refs)` 与当时同一函数 |
| LLM 输入 | `run` 返回的 `nodes` note、describe/read_book 的 payload | **未记录**，本文按 facts 近似重建并标注 |
| LLM 输入 | 门退回给模型的 `problems`/`detail` | **未记录**（`result_summary` 只存 `error: <code>`），本文用当步账本重放 |
| 校验 | 19 个通过答案的重放渲染 vs 落库答案 | **19/19 逐字一致**，所以重放的拒绝原文就是模型当时读到的 |
| 工具 | 每步 `prompt_tokens`/`completion_tokens` | **原始**（`llm_call` 行） |

**这本身是一条发现：trace 记录了模型"做了什么"，没有记录模型"读到了什么"和门"说了什么"。**
9/10 的 AGENT_GAP 文档为 V7-Q2 手工重建过一次 turn，今天仍需重建。

## 1. 各题 trace

记法：`LLM#k` 是该 session 第 k 次 completion；括号内是该次真实 prompt_tokens。

---

### T1 · Q08 两个最高级同时反向，零拒绝  （`trace/Q08-capex-roic-three-way.md`）

**链路**

```
LLM#1 (4592)  → describe(subject=null)            → 10 facts（8 条 not_held/cannot absence + 2 个 count）
LLM#2 (7990)  → run(program: 6 个 method last_n=3，
                     capex_rank = rank(vector{AMZN:$amzn_capex, MSFT:…, GOOGL:…}),
                     roic_rank  = rank(vector{…}))
              ← TOOL: 6 个 series 成功；两个 rank 节点 absence：
                 "type_mismatch: vector: entry 'MSFT' is not a settled scalar binding"
              → read_book(run_e2945c5ebd5a, 8 个名字) ← 4 个 weight facts
LLM#3 (11815) → respond(6 个 series claim + 3 个 level，散文里写最高级)
              ← GATE: ACCEPTED
```

**错误出生点：三处叠加**

1. **tool**：模型的意图是对的——建 vector 再 rank。但 `vector` 只收 settled scalar，模型给的是 `last_n=3` 的 series。拒绝原文说"不是 settled scalar binding"，没说"对 series 先 `latest`"。
2. **LLM**：收到拒绝后没有再试（整轮只有 3 次 completion），改在散文里直接下结论，而且**读反了**：facts 块里最新点 capex AMZN 0.1839 < GOOGL 0.2270 < MSFT 0.2291，ROIC AMZN 0.1622 < GOOGL 0.2476 < MSFT 0.2971。
3. **validation**：六个比较全声明 `series`，`_check_relation` 对 `series` 只查"是不是 series fact"。排序在 `ANSWER_SCHEMA` 里无法表达，谓词落进散文，散文里无人读。

**LLM#3 的原始输入**：system prompt + 推送 `issuer_capital_allocation`/`book_composition` + 问题 + describe 的 10 facts + run 的 10 facts（含两条 type_mismatch absence，原文见上）+ read_book 的 4 facts。共 11815 tokens。

**LLM#3 的原始输出（节选）**

```json
"prose": ["…", "On the latest readings, Amazon spends the most relative to revenue: its capex intensity is {c5},
  above Microsoft's {c1} and Alphabet's {c3} latest points. Microsoft earns the least on that spending on the
  latest ROIC reading: {c2}, below Alphabet's {c4} and Amazon's {c6}.", "…"],
"claims": [{"id":"c1","of":"f_20c0f6dec891","relation":"series"}, … 六个 series …,
           {"id":"c7","of":"f_784b357fe205","relation":"level"}, …]
```

**GATE 输入/输出**：账本 24 facts；c1–c6 → kind=series ✓；c7–c9 → scalar 非 tier ✓；G3 散文无裸数字。→ ACCEPTED。
**读者看到**："its capex intensity is the chart below, above Microsoft's the chart below…"，图表里的数字与句子相反。

---

### T2 · Q14 日期槽位被填进百分比，且是门把正确答案逼掉的  （`trace/Q14-worst-drawdown-episode.md`）

**链路**

```
LLM#1 (4401) → describe(expand=…, subject=null)  ← error: expand_needs_a_subject
LLM#2 (4574) → describe(expand=…, subject=port_001)
LLM#3 (7088) → run(program: episodes=method(book.drawdown_episodes);
                    depth=pick(episodes, "portfolio.drawdown_episodes.deepest_depth");
                    peak=pick(episodes, "episodes[0].peak_date");  trough=pick(…trough_date);
                    explain=method(book.explain_episode, params{peak:$peak, trough:$trough});
                    book_return=pick(explain, "portfolio.window_return");
                    holdings_ret=column(explain, holdings, window_return); worst_names=rank(holdings_ret, lowest);
                    market_ret=method(price.window_return, subject=[…12 个含 BAC GS MRK…]))
             ← TOOL: 36 facts。peak/trough 节点 kind=table（字面量），**没有产出任何 fact**；
                explain 的 facts window=None、as_of=n/a；账本上**没有任何 fact 携带 2026-01-07**
LLM#4 (12064) → read_filings(MSFT, item 7)   ← 1 passage
LLM#5 (14711) → read_filings(LLY, item 7)    ← 1 passage
LLM#6 (17599) → respond  prose[0]="…started on 2026-01-07 and troughed on 2026-03-27, with a depth of {c1}."
                         c6/c7 = absent → passage
              ← GATE: relation_does_not_fit — "absent: f_a86392b938df is a passage of a filing… state it with relation 'quote'"
LLM#7 (18208) → （0 个 tool call，completion 3 tokens）  ← loop: "Call respond to reply to the user."
LLM#8 (18226) → respond  同样的日期，c6/c7 仍 absent → 同样拒绝
LLM#9 (18824) → respond  c6/c7 改成 quote(span=Item 7 标题)
              ← GATE: unsourced_figure — {"at":"prose[0]","figure":"2026-01-07",
                 "detail":"a number the ledger cannot account for: state it through a claim, quote the passage that says it, or drop it"}
LLM#10        → respond  prose[0]="…started on {c1} and troughed on 2026-03-27, with a depth of {c2}."
                         c1 = f_3499a880b819 (portfolio.deepest_depth, 0.1196 RATIO)
              ← GATE: ACCEPTED
```

**错误出生点**

- **tool（根因）**：`_p_pick` 对字面量返回 `TABLE, payload={"literal": "2026-01-07"}`，`_facts_of` 对无 entries 的 TABLE 返回 `[]`——desk 把日期给模型看了，却不给它一个 id。`book.explain_episode` 的 facts 也不携带自己的 window，所以 `identity_tokens` 里没有起点日期。trough 日期 2026-03-27 能留在散文里，只因为它恰好是 window_return facts 的 `as_of`。
- **validation**：G3 对 2026-01-07 找不到任何 fact → 拒绝。规则本身没错，错在它拒绝的是**desk 自己算出来并显示给模型的日期**。
- **LLM**：三次被拒后把 depth fact 指进日期槽。这是模型错误，但账本上确实没有任何合法指向。

**门带来的后果**：第一版散文（LLM#6）的日期是对的；被拒两次的理由与日期无关（absent 指向 passage）；等这两处修好，第三次才因日期被拒；第四次日期换成 depth 通过。**门用四轮把一句真话换成了一句通过校验的假话。**

同题另外两处：`with a depth of {c2}` 的 c2 是 `portfolio.window_return`（-0.1196），不是 depth（+0.1196），读者看到"depth of -12.0%"，身份错位；"MSFT has a filed 10-K Item 7 passage on the desk, titled {c6}"用 `quote` 关系把 Item 7 的标题当成"该窗口内有 filing"的证据，问题被偷换。

---

### T3 · Q17（B 轮）门的一次拒绝让十个数字全部错位一个名字  （`trace/Q17-events-touching-holdings.md`）

**链路**

```
LLM#5 (?)     → respond：c1–c5 rank(top5)；c6–c10 = ret1m(AAPL,AMZN,JPM,LLY,GOOGL)；c11–c15 = 52w 距离；
                          c16–c20 = absent → "newsAAPL was not computed — unknown_primitive: 'search_web' is not a primitive"
              ← GATE: relation_does_not_fit ×5 — "refused_not_absent: … fix the call and run it again"
LLM#6 (14306) → think("Need final respond without claiming absent for search_web refused…")
LLM#7 (14393) → respond：把 c16–c20 删掉；c6 改成 absent → 10-day 窗口拒绝的 fact
              ← GATE: relation_does_not_fit（同类 refused_not_absent）
LLM#8         → respond：c6 改成 f_5b7aa7060345 = **AAPL ret1m**；其后每个 claim 编号**整体前移一位**，散文里的名字没动
              ← GATE: ACCEPTED
```

**LLM#8 输出与账本的对照（原始）**

| 散文 | 指向 | fact 实际身份 |
|---|---|---|
| "cannot give a valid 10-day number from the ledger {c6}" | c6 | AAPL 1m return +8.76% |
| "below the 52-week high…: AAPL {c7}" | c7 | **AMZN** 1m return -5.83% |
| "AMZN {c8}" | c8 | **JPM** 1m return -0.69% |
| "JPM {c9}" | c9 | **LLY** 1m return -5.79% |
| "LLY {c10}" | c10 | **GOOGL** 1m return -1.54% |
| "GOOGL {c11}" | c11 | **AAPL** 52w 距离 -3.89% |
| "gaps are AAPL {c12}" | c12 | **AMZN** 52w -11.3% |
| "AMZN {c13}" | c13 | **JPM** 52w -3.18% |
| "JPM {c14}" | c14 | **LLY** 52w -12.3% |
| "LLY {c15}, and GOOGL {c15}" | c15 | GOOGL 52w -17.3%（LLY 那格也是它） |

十个数字，十个名字全错。且在**所有**版本里，"below the 52-week high"那句挂的都是 1 个月收益（c7–c11 = `price.window_return`），measure 本身就贴错了。

**错误出生点**：LLM 重编号时没同步散文，纯模型错误；但触发它的是门对 `absent` 的两次拒绝。**validation** 从头到尾看不见"AAPL {c7}"里的 AAPL 与 c7 fact 的 subject=AMZN 不一致——散文里的主体词不参与任何检查。

另：模型把 `search_web` 写进 program 当 primitive（它是工具面上的工具，不是 program 原语），拒绝原文 "'search_web' is not a primitive of this desk" 之后，它对读者说 "the web-search tool is not available here"。A 轮同题用 `search_web` 工具成功取回 5 条新闻。

---

### T4 · Q18 "factor share 0.85%" 与 "$1.83 的回撤"  （`trace/Q18-attribution-reconcile.md`）

**LLM 输出（唯一一次 respond，ACCEPTED）**

```
prose[0]: "…factor contributions sum to {c1}, alpha is {c2}, and residual is {c3}. The published reconciliation
           table also shows factor share {c4} and unexplained share {c6}."
c4 → f_f767534b0cbc  portfolio.reconcile.alpha_plus_residual  = 0.00847461   （被叫做 factor share）
c5 → f_4dab5aa823eb  portfolio.reconcile.factor_share         = -1.2547      （声明了，散文没放，静默丢弃）
c6 → f_9b06a9808c65  portfolio.reconcile.unexplained_share    = 2.2547 ✓
c8 → f_629a3ec920d6  HYG.drawdown.fall  = 1.8287  MONEY_PER_SHARE   （program 里 key="fall"，应为 "depth"）
```

**更正 FINDINGS F4 的机制描述**：0.85% 不是"值匹配放行"，是模型把 `{c4}` 指向了 alpha_plus_residual、散文却写 "factor share"；真正的 factor_share 声明为 c5 但没有放进任何段落，`validate_shape` 的规则是"a claim the prose does not place is not refused"，于是它消失了。结果同类：右边的字、错边的指针。

**角色**：LLM 指错；validation 不比对散文里的名词与 fact 的 measure；`price.drawdown` 的 yields（peak/trough/fall/depth）由 tool 正确公告，选 `fall` 是 LLM 错，但"回撤"在散文里对应哪个 yield 无人检查。

---

### T5 · Q15 0.25 vs 20%、混列表格、散文与表格不一致  （`trace/Q15-liquidity-and-limits.md`）

**LLM#3 输出（program）**

```json
{"name":"days","expr":{"fn":"div","a":"$mv","b":{"fn":"scale","of":"$adv","factor":0.25}}}
```

问题原文是 "at **20%** of ADV"。工具照算，fact measure = `divide(issuer_exposures.market_value, scale(price.adv, 0.25))`，unit=COUNT。表头经 `answer._words()`（`.`→空格）渲染为 `scale(price adv, 0 25)`。

**c13 表格的构成（账本原始）**

```
AAPL: limit_checks.current_value 0.15195 | risk_alerts.limit_value  0.15
LLY : limit_checks.current_value 0.12541 | risk_alerts.limit_value  0.12
MSFT: limit_checks.current_value 0.16039 | risk_alerts.limit_value  0.15
NVDA: limit_checks.current_value 0.04064 | limit_checks.breach_level 0.20   ← 另一个 measure
```

散文写 "NVDA is not near its issuer limit at 4.1% against 15.0%"：G3 对 "15.0%" 找到十余个 `warning_level=0.15` 的 fact → 放行；表格那格却是 breach 20.0%。**同一答案里，散文与表格对同一件事给了两个数。**

**角色**：0.25 是 LLM 错，validation 与 tool 都没有"用户参数 vs 程序参数"的比对；混列是 LLM 选错行，`derive_table` 的 explicit 模式让它合法；"0 25" 是渲染缺陷。

---

### T6 · Q13（B 轮）七次拒绝到耗尽：造 id、以及一个被拒的正确 change  （`trace/Q13-sell-half-nvda-into-tlt.md`）

**拒绝序列（重放）**

| # | LLM 写了 | 门说 |
|---|---|---|
| 1–4 | `c4: of="f_held_beta"`, `c5: of="f_held_stress"`, `c3.against="f_35298108"` | not_on_ledger ×3（id 是模型编的，账本上从未出现） |
| 5 | c3 = change(of=after_sell 的 `sector_exposures.Technology.weight`, against=run 的 `sector_exposures.weight`/Technology) | **different_measures**："calc_6f2c70be64e1 sector_exposures.Technology.weight against Technology sector_exposures.weight are not one measure of one subject" |
| 6 | 同一对改成 versus | different_measures："…is neither" |
| 7 | 又回到编 id | not_on_ledger |

第 5 次值得单独记：**这是一个真正正确的前后对比**——同一个 Technology 权重，run 里的读数和 scenario 里的读数。但 run 的 fact 是 `measure=sector_exposures.weight, subject=Technology`，scenario 的 fact 是 `measure=sector_exposures.Technology.weight, subject=calc_…`。**两个生产者对同一个量的命名不同**，门的同 measure 同 subject 检查因此把正确的 change 拒了，模型换成 versus 也被拒。（对应 9/12 记忆里的 R3"派生名不是单射"。）

账本查询确认：Q13 三次 run 各记录 83 个 facts，`held_back` 非空，**账本上没有任何 beta/stress/QQQ fact**。模型可以引用的诚实 absence 是 describe 给的 `scenario_refit`（"a scenario … does not re-fit betas, volatility or P&L"），它没有引，编了 `f_held_beta`。`repeats.STOP=2` 只对完全相同的 payload 生效，七次载荷各差几个字符，从未触发。LLM#11、#15 各产出 0 个 tool call、3 个 completion token（约 28k prompt 各一次）。

---

### T7 · Q11（B 轮）第一版是最好的，被一个编造 id 拒掉；最后交了白卷  （`trace/Q11-closest-to-issuer-limit.md`）

```
LLM#4 (13793) → respond：
   c1 rank  → room_to_warning(MSFT) = -0.01039  （"closest… smallest on the ledger"）
   c2 room  → room_to_breach(MSFT) = 0.0396  against breach_level 0.20   ✓ 正确的 room
   c3 ratio → 同一个 room_to_breach（散文说这是"到 breach 需要的涨幅"，其实是差额，未除以权重）
   c4 absent → of="held_back"                                                ← 编造的 id
 ← GATE: not_on_ledger（只因 c4）
LLM#5 → run(over8 = sub($w, 0.08))       ← "type_mismatch: an operand is a binding ($name) or an id; got 0.08"
LLM#6 → respond … c1 改成 rank 指 weight（无 rank）→ no_ordering；c4 absent 指 type_mismatch → refused_not_absent
LLM#7 → run(over8 = sub($w, vector{AAPL:0.08,…}))   ← "vector: entry 'AAPL' is not a settled scalar binding"
LLM#8、#10 → respond 仍指 type_mismatch absence → refused_not_absent ×2
LLM#11 → 0 tool call
LLM#12 → respond(claims=[], prose="I can't finish the answer yet because the 8% cap part is still unresolved…")  ← ACCEPTED
```

**角色**：`sub` 不收字面量、`vector` 不收字面量、没有 filter/阈值原语——"谁超过 8%" 在 program 语言里**不可表达**，这是 tool 的表达力缺口。validation 正确地拒绝把 type_mismatch 当 absence，但没有任何路径让模型说"这个问题 desk 表达不了"。LLM 在被一个编造 id 拒掉后，把三个算对的部分全丢了。A 轮同题则是给了错答案（F7）。两轮是同一个门的两种失败方向。

---

### T8 · Q07（B 轮）崩溃、无法定型的方法、原始浮点  （`trace/Q07-tech-cash-conversion-rank.md`）

```
LLM#2 (7795) → run(issuer.panel key=operating_cash_flow subject=[5 tickers] params{months:12, at:"prev"}, …)
             ← TOOL: **tool_error**（13.7s）：fundamentals_service.get_balance_sheet → date.fromisoformat("prev") ValueError
                整个 program 作废，模型读到 {"error":"tool_error","detail":"Invalid isoformat string: 'prev'"}
LLM#3 (8332) → run(去掉 at；issuer.panel ×4 …；weights/weights_prev/weight_chg/rank_weight_chg)   27.2s
             ← TOOL: ocf/ni/ocf_prev/ni_prev 全部 absence："untyped_result: issuer.panel: no subject produced a figure"
                weight 相关 41 facts 成功
LLM#4       → respond：prose 含裸数字 "+0.00468063"；c2 rank AAPL 0.00468 (#1)；c3 rank NVDA -0.00114 (#10)
            ← GATE: ACCEPTED；G3: '+0.00468063' → value 匹配 f_8891ff564402（精度按书写位数，8 位小数精确等于）
```

**为什么 issuer.panel 一个 subject 都没出图形**：`formula_service.build_panel` 返回 `{"ticker":…, "lines": {name: {...}}, …}`，图形嵌在 `lines` 下；`program_service._from_payload` 只扫**顶层**键找 `calc_id+value`，找不到 → `untyped_result`。方法在注册表里、describe 会公告它的 32 个 yields，但 `run` 永远无法给它定型。此外模型要的 `operating_cash_flow`/`net_income` 根本不在 panel 的 yields 里，它们是 `fundamentals` 的 filed line——两个错叠加，模型只看到一句 "no subject produced a figure"，每个 subject 各自的拒绝原因在 `node.refusal["refused"]` 里，**没有复制到 absence fact 上，也没有落盘**。

**角色**：LLM（`at:"prev"`；找错门）；tool（panel 不可定型；日期解析崩溃而不是 refusal；refused 明细丢失）；validation（原始浮点按值放行，悬挂芯片合法）。

---

### T9 · Q19 用错门的拒绝被当成"AWS 占比"的答案  （`trace/Q19-aws-share-explains-return.md`）

describe 的 facts 明确写着：`segment_revenue — not held as figures (companyfacts carries no dimensions); stated in the 10-K's segment note and Item 7 — read_filings`。模型没有调用 read_filings，写了 `fundamentals(AMZN, metric="revenue_including_assessed_tax")` → `metric_not_filed` absence，然后：

```
prose[1]: "AWS's share of Amazon revenue is {c2}; …"   c2 = absent → 该 absence fact
```

`metric_not_filed` 不在 `SPELLING_REFUSALS`，门视为可引用的 absence → ACCEPTED。读者看到 "AWS's share of Amazon revenue is aws was not computed — metric_not_filed: AMZN has no filed facts under 'revenue_including_assessed_tax'"。**这个 absence 讲的是一个错误的 metric 名，不是 AWS**；validation 无法知道 `revenue_including_assessed_tax` 不是 AWS。LLM 忽略了 describe 给的路由。

---

### T10 · Q06 "现在 vs 一年前"被工具的表达力改写  （`trace/Q06-jpm-riskier-than-a-year-ago.md`）

program 里 `dist_now` 与 `dist_1y` 是**两条完全相同的表达式** `method(price.distance_from_52w_high, subject=JPM)`——该方法 `params_schema` 为空，没有 as-of。`vol_now`/`vol_1y` 用 `window_days` 30 与 252 代替"现在与一年前"。模型随后把重复写成一个发现："on the same current date the desk's 1-year reading is the same, because both facts reference the same trailing-year high"。

**角色**：tool——价格方法没有 as-of 维度，问题里的时间轴不可表达；LLM——把重复叙述成结论。

---

### T11 · Q01 门把一张会显示数值的表逼成十二个 "the chart below"  （`trace/Q01-amzn-earnings-quality.md`）

```
LLM#3 → respond：c1 = table(rows=[[f_33c8ba9a52b1, f_6d4d6bbe0cb6], …])   ← 表格格子是 series
      ← GATE: relation_does_not_fit — "kind_does_not_fit: a table cell is a scalar fact (a series point is f_…@period)"
LLM#4 → respond：所有 series 改成 inline `series` claim：
        "operating cash flow was {c1} and net income was {c2}, while cash conversion was {c7}"
      ← GATE: ACCEPTED
```

读者看到 "operating cash flow was the chart below and net income was the chart below…"，一段 12 处。门拒绝的理由是对的（表格格子应是 scalar），但它给的三条出路里没有一条能让数值出现在句子里，模型选了合法但对读者最坏的那条。

---

### T12 · A 轮 Q13 两个 level 拼成的假 change  （`trace/A_round_respond_attempts.txt`）

```
"…lowers gross exposure from {c1} to {c2}"     c1 exposure_metrics.gross_exposure  $10.63M  MONEY  (calc_9ce1…)
                                                c2 limit_checks.gross_exposure.current_value  1.0 RATIO (calc_9ce1…)
"Technology concentration moves from {c3} before the sale to {c4} after the sale"
                                                c3 sector_exposures.Technology.weight        0.3367 (calc_9ce1…)
                                                c4 sector_exposures.Technology.market_value  $3.58M (calc_9ce1…)
```

四个 fact 全来自**同一个** after-sale scenario（calc_9ce1a857e0d5），没有一个是 before。两句"from…to…"都声明为独立 `level`，`change` 的同 measure/同 subject/不同期检查一次都没运行（§12）。

### T13 · A 轮 Q11 room 指向别的档

`c2: room(of=subtract(warning_level, current_value) = -0.01105, against=breach_level = 0.20)`。`_check_relation` 的 room 分支：`of` 以 `subtract(` 开头 → 视为距离；`against` 是 tier → 通过。warning 的差额配 breach 的门槛合法。读者："room left to warning is -1.10% against 20.0%"。

### T14 · A 轮 Q17 引文挂错主体

`c9: quote(of=f_db060617ff9d, span="Eli Lilly (NYSE: LLY) has secured FDA approval…")` 被放在 AAPL 那句里；`c10: quote(Google antitrust)` 放在 JPM 那句里。`quote` 只查 span 是否逐字在 passage 里；句子点名的公司与 passage 的 subject 之间没有检查。

## 2. 跨题的观察

**门的拒绝改变了答案内容的方向，而且四次改坏了：** T2（正确日期→depth）、T3（重编号→十个名字错位）、T7（正确的三部分→白卷）、T11（表格→"the chart below"）。这四次里门的每条规则单独看都成立。

**空 completion 的回合**：Q14 #7、Q13 #11/#15、Q11 #11 各产出 0 个 tool call、3 个 token，prompt 18k–28k。loop 追加 "Call respond to reply to the user." 后下一回合才动。

**LLM 自身的错误**（不由工具或门诱发）：Q08 读反序列、Q15 的 0.25、Q18 的 key="fall" 与 c4 指错、Q07 的 `at:"prev"` 与找错门、Q19 忽略 read_filings 路由、Q13/Q11 编造 id、Q17 把工具写成原语并称其不存在。

**tool 的表达力与定型缺口**（模型的意图正确但无法执行）：vector/sub 不收字面量、无 filter 原语（Q11）；vector 不收 series、拒绝不提 `latest`（Q08）；pick 字面量不成 fact、explain_episode 不带 window（Q14）；价格方法无 as-of（Q06）；issuer.panel 不可定型（Q07）；run 与 scenario 对同一 measure 命名不一致（Q13 第 5 次）。

**validation 看不见的东西**（全部通过）：散文里的最高级与方向词（Q08）；`{cN}` 旁的名词与 fact 的 subject/measure 是否一致（Q17、Q18、Q14 的 depth/return）；两个 level 是否在同一句里构成一次 change（A-Q13）；room 的两端是否同一档（A-Q11）；quote 的 passage 是否关于句子的主体（A-Q17）；series/table 关系的渲染文本是否落在数值位置（Q01/Q08）；用户参数与程序参数是否一致（Q15）；absence 的内部文本直接出厂（Q19、Q07）。
