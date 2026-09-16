# IMPLEMENTATION PLAN V38 — 工具层的修复（C 轮之后，2026-09-16）

> 依据：`docs/spikes/v37/TOOLS_V37C.md`（工具层分析）、`ATTRIBUTION_V37C.md`、`ACCEPTANCE_V37.md`，加上本次对代码的逐处核实（每条带 `文件:行`，按 HEAD `0986dca` 读；`src/` 自 `b79354f` 未动）。
> 起点：HEAD `0986dca`，`pytest -m "not live" -q` 基线 **2603 passed / 11 skipped / 311 deselected / 20s**。
> 范围：用户 9/16 点名的五组——`return` 不起作用、拒绝被扣下、digest 丢信息、`vector.entries` 嵌套不求值、五处数值与身份。每条先说把工作还给哪个角色，再说落在哪一层、改哪一行、怎么测、用什么数验收。
> 读法：验收分两级。**离线重放**用 C 轮 40 个 session 记录下的事实与程序，不花额度，改完当天就能量；**D 轮**才看读者面前的数。
>
> **本次核对新发现三处，都改变了既有文档的结论：**
> 1. XOM 的长期债务在 fixture 里**有**：`us-gaap:LongTermDebtAndCapitalLeaseObligations` 38 条、到 2026-03-31、$33.1B，另有 `…Current` $6.2B——只是 `concept_mapping.py:124-146` 没映射这两个标签。V37 Phase C 的 S1 结论「该发行人无长期债务科目，cover 因此完整」不成立：不是没申报，是桌子不读那个标签。KO（$45.0B）同样。
> 2. sol Q13 seq13 的 `method(book.buy, params={buys:[{ticker, weight:"$freed_w"}]})` 被拒为 `invalid_params`，离线重查：把 `$freed_w` 换成数字就通过。类型检查只在 params 顶层替换 `$` 引用（`program_service.py:629`），嵌套在 `buys[0].weight` 里的没替换，交给 schema 查成「不是 number」。执行器（`_substitute_literals` :752）是递归的。**这是一条假类型错**，归因文档记的 B 应改 C。
> 3. mini 13 次类型拒绝里 8 次、sol 2 次，是 `vector.entries` 里的嵌套表达式（`latest(...)`、`at(...)`、`avg(...)`）没被 `hoist` 展开（`program_service.py:187-197` 只进有 `fn` 的字典），查成 `got: object`，拒绝原话「takes scalar」；语言页还写着「latest(of) first」引导这么写。归因文档记的 B 应改 C。

## 0. 一句话，与不变量

**一句话**：工具现在既不执行模型写下的意图（`return`、嵌套表达式、`at`），也不守「输出永远是完整的事实或拒绝」（拒绝被扣下、备注被丢、空结果不说原因）。本计划把这两条还给工具；数值与身份的五处错落在 service 层，也一并修；模型不需要学任何新东西——它写的程序本来就是对的。

**不变量**（与 V37 §0 相同）：
- registry 四步 wrapper、ledger 按 session、两处核对只查表、agent 树深仍为 2、import 法则不变（typed_calculator 不得 import program_service，见 S4）。
- **账本记全部事实**（V37/T6）：本计划只改「显示什么」，不改「记录什么」。
- 模型不给 measure 起名；不加 fallback；每条改动消灭一类错误。
- 措辞（`HOW_TO_CITE`、skill 文字）进 `WORDING.md`，D 轮前一次过目（V37 §5 的决定）。
- 实测期冻结代码。

## 1. 清单总表

| # | 层 | 还给谁 | 问题（C 轮证据） | 改法一句 | 阶段 |
|---|---|---|---|---|---|
| T1 | tool | tool | `return` 只是声明：显示的图形 45%（mini）/58%（sol）属未点名节点；点名节点有图从未显示 115/296、274/801；扣下提示教的办法不存在 | 显示按 `return` 裁剪；未点名的节点只列名字和条数；扣下提示按节点名说 | B |
| T2 | tool | tool | 拒绝被上限扣下 mini 30、sol 42，另 10 条被 `dumps_capped` 截掉；两轮 Q13 的 `no_sector` 分析师都没见过；`nodes` 只列名不列种类 | 拒绝不进上限；`depends_on_refused` 链折叠到根；`nodes` 带种类；最终截断最后才动 boundaries | B |
| T3 | tool | tool | digest 丢掉工具已说的话：cover 备注（S1）、向量被拒条目、字面量值、参数错误字段、第 3 个以后的类型问题、`not_alone` 半句话 | 备注上事实（`made_of`）；被拒条目铸成 absence 事实；字面量显示并说明怎么引；问题逐字段、全部显示 | A/B |
| T4 | tool | tool | `seen` 在截尾前登记：从未显示却被吞掉 mini 343、sol 789；全空结果 4/17，只剩提示 4/8 | 先合并（只读 seen）、再截尾、最后登记幸存者；被合并的在本次结果里留痕（`repeated`） | B |
| L1 | service（语言） | tool | `vector.entries` 里的 `{fn}` 不求值，拒绝原话与语言页互相矛盾；mini 8 次、sol 2 次类型拒绝 | `hoist` 进入普通字典与列表；拒绝原话与语言页改口 | A |
| L2 | service（语言） | tool | params 里嵌套的 `$name` 类型检查不替换：sol Q13 seq13 `book.buy` 假类型错 | 占位替换递归，与 `_substitute_literals` 同形 | A |
| S1 | service | tool | 天数公式固定 ×365：季度天数放大 4 倍（sol Q09 整张表） | 按窗口天数换算（12→365、9→274、6→182、3→91），公式文字随之 | C |
| S2 | service | tool | 流量类方法不认 `at`：sol 18 条事实 `params.at=2021` 而 `as_of=2026-03-31`；sol Q10 五次空调用 | `at` 同时钉住流量窗口（≤ at 的最近一个 `months` 窗口）；`get_flow(end=…)` 单独给也生效 | C |
| S3 | service（数据） | tool | 总债务只含短端：XOM/KO 的长期债务在未映射标签下；`fcf_to_debt` 254%、9209.8% | 映射两个标签；containment 的替代成员点名使用；`made_of` 随事实 | C |
| S4 | service | tool | `pick` 把 `…net_beta.equity_down` 拆成主体 `equity_down`；同一图形两个门两种身份；措辞表误报 `net beta` ×27 | 一个命名函数两个门共用 | A |
| S5 | service（面） | tool | 语言页 `book.reconcile` 缺 `sum_of_factor_contributions`、`alpha_plus_residual`（服务记了，面没列） | yields 补全；机械测试：每个 run/portfolio 方法的 yields ⊇ 服务声明的结果键 | A |
| K5 | skill | skill | 「TLT and HYG enter with the sign opposite」——代码里 SPY/QQQ/IWM 也反号（`integration.py:37-45`）；mini Q08 两条「净空头」 | 三处文字改口；测试把文字和 `_RISK_SENSE` 钉在一起 | B（措辞过目） |

## 2. 分层细目

### 2.1 tool 层：适配器与 digest

**T1 · 显示按 `return` 裁剪**

- 角色：工具没执行 LLM 写下的意图。`return` 在语言页的说明是「the bindings the answer will point at」，执行器和显示都没用它。
- 位置：
  - `services/program_service.py:1967-2008` `run()`：`for name, node in ctx.nodes.items(): facts += node.facts`，结果带 `"returns": parsed.returns`（`parse` :222 默认为全部非 `_` 绑定）。**这一处不改**：账本要全部事实。
  - `services/fact_adapters.py:716-722` `run_program`：原样取出；`:754-790` `adapt`：`kept, held = F.cap(facts)`（:782），`READ_BY_NAME["run"]`（:749）。
  - `services/digest.py:269` `entry["nodes"] = [n for n in nodes …]` 只有名字；`:277-290` 扣下提示文案（V37/T5(d)）；`:51-67` `HOW_TO_CITE`。
- 改法（全部在 tool 层）：
  1. `adapt`：适配器返回后、`F.cap` 之前，`show, omitted = _to_show(tool, facts, note)`。对 `run`：`returns = set(note.get("returns") or [])`；`show = [f for f in facts if f.kind == F.ABSENCE or f.params.get("node") in returns]`；其余按节点计数进 `note["not_returned"] = {node: n}`。`kept, held = F.cap(show)`。`_ALL.set(facts)` 不变（账本与 facts 表仍记全部，T6 不动）。其它工具 `show = facts`。
  2. `held`（点名内容自身超上限时才有）：加 `nodes: {node: n_dropped}`；`READ_BY_NAME["run"]` 改为「these nodes are large: return fewer of them, or pick(of=$node, key=…) / top(of=$node, n=…) the entries you need」。
  3. digest：`nodes` 从名字列表改为条目列表 `[{name, kind}, …]`；未点名的节点 `{name, kind, figures: n, shown: false}`；扣下提示改为「N more figures of the nodes you named are on the ledger and not shown: {node: n}. Return fewer of them, or pick the entries you need」。`made`（情景 id）仍从 `res["nodes"]` 全部节点取——建了的书就是建了。
  4. `HOW_TO_CITE` 两句（进 `WORDING.md`）：*`nodes` lists every binding with its kind; a node you did not name in `return` shows its figure count only — name it in `return` to read it.*
- 测试：
  - `tests/test_fact_adapters.py`：三个节点、`return` 一个 → `adapt` 的 `kept` 只有该节点的事实加全部 absence，`adapt_all` 的 `made` 是全部，`note["not_returned"]` 计数正确；没写 `return` 的程序显示全部绑定；`held` 带 `nodes`。
  - `tests/test_v36_digest.py`：`nodes` 条目形状；扣下提示按节点名；`test_held_back_figures_are_said_and_recorded` 改文案。
  - `tests/test_v37_context_labels.py:78-95` 的 fixture 保留 `measures`，加 `nodes`。
- 验收信号：
  - 离线重放（§4.1）：「点名节点有图从未显示」mini 115 → 0、sol 274 → 0，例外只允许点名内容自身超 24k 字符的 run（报数）；「点名的被扣、未点名的显示」12/26 → 0。
  - D 轮：`held_back` 提示（工具上限 + digest 截尾；C 轮 mini 18+13=31 条、sol 33+29=62 条）下降；Q08/Q11/Q15/Q16 的分析师读到 `prev_exposure`、`ranked_warning`、`net_beta_prev`。

**T2 · 拒绝不进上限，种类可见**

- 角色：工具的输出该是「完整的事实或拒绝」，现在拒绝本身会丢。
- 位置：
  - `services/facts.py:196-211` `cap`：按条数和字符数从尾部弹出，不分 kind。absence 事实由 `_facts_of` :1949-1953 在它的节点位置生成，常排在整表之后。
  - `services/digest.py:251-262` absence → boundary；`:269` nodes 无种类。
  - `agents/sub_analyst.py:375` `ejson.dumps_capped(res, room)` 不带 `keep`；`utils/json.py:79-108` 的 `keep` 是「最后才丢的容器」（`research_session.py:160` 已在用）。sol Q04 seq4、Q06 seq16 被截的正是 `boundaries`，截断说明还写「these were computed and can be requested individually」。
- 改法：
  1. `cap`：`absences` 不计条数、不计字符；只对其余事实计；返回时保持原顺序。`held` 语义不变。
  2. digest：`code == "depends_on_refused"` 的 boundary 折叠到根节点的条目下：根显示一次，加 `blocks: [依赖它的节点名]`（`_facts_of` 已把 `root` 写进 params :1950）。sol Q13 seq4 那 20 多条同根拒绝变成一条加一个名单。
  3. `nodes[].kind`：absence 节点写 `refused` 并带 `boundary: f_…`。
  4. `sub_analyst.py:375`：`dumps_capped(res, room, keep=("boundaries", "nodes", "made", "started"))`——超 room 时先丢 figures，最后才丢拒绝。
- 测试：
  - `tests/test_fact_adapters.py`：300 条标量后跟 40 条 absence，`per_result=200` → 40 条 absence 全在 `kept`；字符上限同理。
  - `tests/test_v36_digest.py`：1 根 + 9 依赖 → 1 条 boundary，`blocks` 9 个名字；`nodes` 里 absence 节点 `kind == "refused"`。
  - `tests/test_v37_*`（T5 的每 completion 上限测试旁）：200 图形 + 30 boundary、room 4000 → boundaries 全在，figures 被截。
- 验收信号：离线重放「拒绝被扣下」mini 30 → 0、sol 52 → 0。D 轮：Q13 类题目，分析师 brief 必须写出「买入被拒（no_sector）」（人工核对；`no_sector` 本身本轮不改，见 §7）。

**T3 · 工具已说的话到分析师手里**

(a) 组成备注（S1 的三个键）

- 位置：`program_service._note_of` :2055-2058 只写在节点备注上，digest 不读；`formula_service.evaluate_formula` :385-394 只有 `total_debt` 分支带三个键，比率的 `out`（:528-545）不带——所以 `fcf_to_debt` 节点的备注里本来就没有；`evaluate_formula_series` :551-660 逐点不带。`_facts_of` :1907-1916 标量/序列的 params `p`。
- 改法：`evaluate_formula` 收集各 operand 带的 `formula`/三个键/`substituted`（S3）成 `out["made_of"] = {input: {...}}`；`_facts_of` 对 SCALAR/SERIES 把 `payload["made_of"]`（及 `substituted_inputs`）写进事实 `params`——事实自己说明它由什么组成，账本与抽屉都有；`evaluate_formula_series` 把最新可算点的 `made_of`放进序列 payload；digest 图形/序列条目复制 `made_of`；`HOW_TO_CITE` 一句：*`made_of` on a figure names the filed lines a composed total was built from and what it lacks: say it beside the figure.*
- 测试：`tests/test_registry_conditions.py` 的 `Desk` 桩：只申报短端的发行人 → `fcf_to_debt` 的 `out["made_of"]["total_debt"]["no_facts_for_issuer"]` 非空；`_facts_of` 带到 params；digest 显示。

(b) 向量里被拒的条目

- 位置：`_p_method` :1210-1233 把被拒主体收进 `payload["refused"]`（:1223）；`_note_of` :2078 `refused_entries`；`run()` :2007 顶层 `partial`。digest 三处都不读（sol Q12 seq22 的 GS）。
- 改法：`_facts_of` VECTOR/RANKING 分支为每个被拒条目铸一条 ABSENCE 事实（measure = 节点 measure，subject = 该主体，text = `f"{node.name}[{subject}] was not computed — {error}: {detail}"`，params 带 node/label/error）。它从此和别的拒绝一样走 boundary、上账本、可引用。digest 不需要新逻辑。
- 测试：`tests/test_program_service.py`（`:139` 那类假方法派发）：两主体一拒 → 事实里有一条 absence，digest boundaries 显示。

(c) 字面量节点

- 位置：`_note_of` :2059-2062 返回 `{"kind": "literal", "value"}`，digest :269 丢；`_declared_dates` :1873-1887 与 `_facts_of` :1900-1902 已把字面量写到用它的节点的事实上（`params.peak`、`window`）；`ledger.py:101-125` 把 window/params 里的日期编进身份索引；`answer_check.py:463-467` 日期按全账本身份解析。所以日期本来就可引——分析师只是看不见值，也没人告诉它怎么引。
- 改法：digest `nodes` 条目 `{name, kind: "literal", value, used_by: [声明里带它的节点]}`；`HOW_TO_CITE` 一句：*a literal (a picked date or name) is not a figure and has no bracket of its own: write it beside a figure of the node it was passed to — that figure's `window` or `as_of` carries it.*
- 测试：digest：字面量节点 + 带 window 的 explain 图形 → 条目有 value 与 used_by。
- 验收：sol/mini Q14 重放能看到 `peak 2026-01-07`。

(d) 参数错误的字段

- 位置：`digest._problem_text` :166-175 只取一层文字；`program_service._absence_text` :1955-1964 只用 `detail`；嵌套的 `problems` 在 `_check_method` :633-634（类型检查）和 `_p_method` :1189（运行时）都交了出来。
- 改法：两处都把嵌套 `problems` 逐条追加为 `field: problem`；`fix` 从 `params_schema.properties` 生成一行「params take: buys: [{ticker, weight}], …」（一层即可，不带整份 schema）。
- 测试：类型检查与运行时两条路径，`book.buy` 错字段的拒绝文字都点名字段。

(e) 类型问题只显示前 3 个

- 位置：`digest.absorb` :191 `res["problems"][:3]`。mini Q07 seq7 第 4 个问题就是 entries 嵌套，下一次 seq10 卡在那里。
- 改法：全部显示，按 `at` 分组，相同文字合并计数（`×3`）。类型检查每个节点只报一个问题，长度有界。
- 测试：5 个问题 → 5 个都在文字里；3 条相同 → 一条带 `×3`。

(f) `not_alone` 的半句话

- 位置：`services/quantities.py:447-448`「…no single beta is determined; their sum, X, is」——后面本来接的是同一行加进去的 `factor_attributions.sum_of_contributions`（:451），但读到的是一句断在「is」的话；`_p_column` :1055 原样转发；sol Q18 seq4 它重复了 9 遍（T2 的折叠解决重复）。
- 改法：文字改为「…no single beta is determined; their sum is, and this run holds it: pick(of=$run, key='factor_attributions.sum_of_contributions'), or method(name='book.reconcile', subject=$run, key='portfolio.reconcile.sum_of_factor_contributions')」（S5 补全后这个键在面上）。
- 测试：`tests/test_v37_refusals_on_face.py` 的静态扫描照旧（`pick`/`method` 是语言词）；一条文字测试。

**T4 · 先合并，再截尾，最后登记**

- 角色：工具把「一个读数只显示一次」执行成了「登记过就算显示过」。
- 位置：`digest.render` :381-392 顺序 absorb → `tell_apart(items, seen)` → `stamp_ids` → `fit`；`tell_apart` :293-316 把每个图形登记进 `seen`，`fit` :335-378 之后才截。被截掉的图形已在 `seen` 里。合并只挂在早先那个条目对象的 `also` 上（:315），本次结果里没有任何痕迹——所以有 4/17 次全空结果。
- 改法：拆成两步：`collapse(items, seen)`（只读 `seen`：读数已在其中的图形从 `figures` 移走，记到 `entry["repeated"] = [{id, node, shown_as: 早先的 id}]`；同一次调用内的重复仍并入首个的 `also`）→ `stamp_ids` → `fit` → `register(items, seen)`（只登记幸存的图形及其 `also`）。`render` 只在非空时带 `repeated`。`FOR_THE_ANALYST_TO_READ` 加 `repeated`；`HOW_TO_CITE` 一句：*`repeated` names figures this call produced that you were shown before, with the id they were shown under: write that id.*
- 测试：
  - `tests/test_v36_digest.py::test_a_reading_fetched_twice_in_two_calls_collapses…` 改：第二次 `figures == []`，`repeated[0]["shown_as"] == "f_first"`；第一次的条目不再被事后改写。
  - 新：120 个图形、cap 只显示 13 → 第二次只要两个被截掉的 → 两个都显示（归因文档 §6 的合成案例）；全部重复 → `repeated` 列全、`figures` 空。
- 验收：离线重放 `SWALLOWED_NEVER_SHOWN` mini 343 → 0、sol 789 → 0；全空结果 mini 4 → 0、sol 17 → 0（每次结果至少有 figures、series、passages、boundaries、repeated 之一）。

### 2.2 service 层：程序语言

**L1 · `vector.entries` 里的嵌套表达式**

- 角色：语言页说「latest(of) first」，语言的解析器不认写在 entries 里的 `latest`，类型检查再用一句「takes scalar」把责任推回模型。
- 位置：`program_service.parse.hoist` :187-197（只展开带 `fn` 的字典，普通字典原样返回）；`_check_vector` :649-671（`got: object`）；`_fix` :478-501（末行通用「takes」）；`signature_text` :361-362 vector 文案；`docs/PROGRAM_LANGUAGE.md:97`；`services/name_table.py:118` 符号表。`_p_vector` :1555-1597 只认 `$ref`，不用改。
- 改法：
  - `hoist` 进入普通字典与列表：`entries`、`params`、`sales`/`buys` 里的 `{fn}` 各成一个绑定 `$_<父>_<路径>_<n>`，路径经 `[^A-Za-z0-9_] → _` 清洗（节点名不含点）。`params` 里的嵌套值经此变成 `$ref`，运行时 `_substitute_literals` :752 已能把 SCALAR 节点代成数——`params: {peak: pick(...)}` 也就能写了。
  - `_fix`：`entries.*` 上 `got == object` 改为「an entry is $name, a number, or an expression that yields one figure ({fn: latest|at|avg…}); an object with no fn is not a figure」。
  - 语言页与符号表：「{label: $scalar | number | {fn: …} that yields a scalar}」。
- 测试：`tests/test_program_service.py`：mini Q07 seq10 形状（entries 里 `latest(of=$series)`）解析出命名节点、类型检查为空、执行得一个 VECTOR；`params` 里的 `{fn}` 同样展开；展开出的名字不含点。既有 `test_parse_hoists_nested_expressions_into_named_nodes` 不动。
- 验收：把 C 轮 25 个类型拒绝的程序（mini 13、sol 12）离线重查：entries 类 mini 8、sol 2 → 0。mini Q08 seq13 会从「takes scalar」变成真错「`$msft_capex_intensity` is not bound earlier in the program」（它引用了上一个程序的绑定），这是对的。

**L2 · params 里嵌套的 `$name`**

- 位置：`_check_method` :629-630（`_placeholder` 只替换顶层 `$`），schema 校验 `validate_args` 对嵌套值原样查。运行时 `_substitute_literals` :752-773 递归。同一件事两个门：`buy` 原语（`_p_scenario` :1721）不查 schema，所以 K2 的示例程序（用原语）通过；`method(book.buy)` 查 schema，所以 sol Q13 seq13 被拒。已离线复现（见页首）。
- 改法：`_placeholder_sub(value, schema_node)` 递归进字典与列表，按路径上的 schema 节点选占位类型；与 `_substitute_literals` 同形。
- 测试：`tests/test_v33_typecheck.py`：`w = mul(...)` 后 `method(book.buy, params={buys:[{ticker:"TLT", weight:"$w"}]})` 为空；写错字段名仍拒且点名字段。
- 验收：sol Q13 seq13 重查为空。

### 2.3 service 层：数值与身份

**S1 · 天数按窗口换算**

- 位置：`formula_service.evaluate_formula` :496-521（`scaled_to_days` → `tc.scale(..., DAYS_IN_YEAR)`），`DAYS_IN_YEAR` :39；`analytics/formulas.py:220-236` 三条天数公式的 `expression`，`validate` :487-493 要求表达式含「365」；`tests/test_registry_conditions.py:236, 251-253, 318-336`。`months` 在 `evaluate_formula` 签名里（:361），序列路径 :627 逐点传入。
- 改法：因子 = 窗口的名义天数 `_DAYS_IN_WINDOW = {12: 365, 9: 274, 6: 182, 3: 91}`（按 `months`）；scale 行的 `basis` 写「scaled by 91」；表达式改「accounts receivable ÷ revenue × days in the window (365 for twelve months)」；`validate` 改为要求含「days」；`Formula.note` 加一句。`cash_conversion_cycle` 是三者之差，自动跟随。
- 测试：既有三条改口（默认 12 个月因子仍 365，注意「365」断言改「days」）；新：`months=3` → 因子 91，`quantity` 仍是公式名。
- 验收（fixture live）：`days_sales_outstanding(AAPL, months=3, last_n=12)` 在 2023-09-30 ≈ 30.0（= 120.34 × 91 / 365），年度 28.10 不变。sol Q09 那张 4 倍的表不可能再出现。

**S2 · `at` 钉住流量窗口**

- 位置：`_dispatch_method` :1258 把 `at` 传给 `evaluate_formula`；`evaluate_formula` :410 `_common_window(db, ticker, f, months, invoked_by)` 不带 `at`；`_common_window` :251-282 对每个流量取「最近可达窗口」；`_operand` :147-152 流量按 `window` 或 `months` 取；`fundamentals_service.get_flow` :232-236 只有 `start and end` 才按日期取，单给 `end` 被忽略；`interval_algebra.latest_window` :234-260 没有上界。事实身份：`_typed_identity` :786-800 的 `as_of` 来自区间末端，`_declared_dates` 把 `at` 写进 params——两者矛盾就是 sol 那 18 条。`PROGRAM_LANGUAGE.md:246` 把这个行为写成了规则（「`at=` on a flow-based method shifts only its balances」）。
- 改法：
  - `latest_window(facts, months, not_after: date | None = None)`：`ends` 过滤 `<= not_after`；找不到 → `Unreachable`，reason 写「no {months}-month window ends on or before {not_after}; the latest ends {…}」。
  - `get_flow`：单给 `end`（无 `start`）→ `latest_window(..., not_after=end)`。
  - `_common_window(..., not_after=at)` → 逐流量 `get_flow(months=months, end=at)`；`evaluate_formula` 传 `at`。余额仍按 `at` 取（:137-141 不变）。
  - `PROGRAM_LANGUAGE.md:246` 改为「`at=` on a formula pins the balances at `at` and every flow to the latest `months` window ending on or before it」；规则 6（:121）关于原语 `fundamentals(at=)` 拒绝流量的部分不动（见 §5.1）。
- 测试：`latest_window(not_after)` 单元；`get_flow(end=…)` 单独给；`Desk` 桩：`roe(at=2023-06-30)` 用到的净利润窗口以 2023-06-30 结束而不是最新；`at` 早于最早窗口 → 拒绝而不是最新。
- 验收（fixture live）：`method(ebit_interest_coverage, MSFT, params={at: "2021-06-30"})` → `as_of 2021-06-30`、31.31×（等于 sol Q10 seq55 引用的年度序列点；五个财年末 31.31 / 41.58 / 46.38 / 37.72 / 52.84 逐一相等）；`roe(JPM, at=2023-12-31)` 净利润窗口为 2023 年。sol Q10 那五次空调用不会再发生。

**S3 · 总债务：映射两个标签，替代成员点名**

- 位置：
  - `services/concept_mapping.py:124-146`：债务五个概念（`LongTermDebt`、`LongTermDebtNoncurrent`、`LongTermDebtCurrent`、`DebtCurrent`、`ShortTermBorrowings`）；`MAPPING_VERSION = "v4"` :37；`normalize_concept` :361。
  - fixture（`exposure_battery`，未映射的余额类债务标签）：XOM `LongTermDebtAndCapitalLeaseObligations` 38 条到 2026-03-31（2025-12-31 $34.24B、2026-03-31 $33.13B），`…Current` 9 条（2025-12-31 $6.23B）；KO 同两标签（$44.98B / $4.49B）；GOOGL `LongTermDebtAndCapitalLeaseObligations` 30 条到 2025-03-31（$14.82B），**但 GOOGL 同时申报 `LongTermDebtNoncurrent`**；LLY `NotesPayable` $29.47B（2024-12-31，另有映射过的长期债务，本轮只记录不改）；JPM 只有 `TransfersAccountedForAsSecuredBorrowings…`（不是债务）。
  - `analytics/containment.py:50-54` 债务家族；`cover` :150-225：`no_facts_for_issuer` = 从未在映射标签下申报，设计上「不算缺」（:219-222 注释）。`_total_debt` :158-250。
  - `fundamentals_service.get_balance_sheet` :285-300：同一 (metric, date) 只留一条，按申报先后——两个原始标签映到同一个 metric 时，赢的是后申报的那条，不是按概念决定。**所以不能把新标签直接映到 `long_term_debt_noncurrent`**（GOOGL 两个标签同日不同值，会被申报日期静默裁决）。
  - `scripts/remap_concepts.py`：按当前映射重写已存事实的 `normalized_metric`（不是 backfill，V9-M1 的做法）。
- 改法：
  1. 两个新 metric：`long_term_debt_and_leases_noncurrent` ← `LongTermDebtAndCapitalLeaseObligations`；`current_portion_long_term_debt_and_leases` ← `LongTermDebtAndCapitalLeaseObligationsCurrent`；`MAPPING_VERSION = "v5"`；fixture 上跑 `remap_concepts.py --apply`（生产库等部署放行时一起跑）。
  2. containment：`SUBSTITUTES = {"long_term_debt_noncurrent": ("long_term_debt_and_leases_noncurrent",), "current_portion_long_term_debt": ("current_portion_long_term_debt_and_leases",)}`——只在成员属于 `no_facts_for_issuer`（从未申报）且替代在该日期已申报时使用；替代继承成员在包含图里的位置；`Cover.substituted = {member: alt}`，`formula` 写「debt_current_total + long_term_debt_and_leases_noncurrent [for long_term_debt_noncurrent]」。GOOGL 申报了正主，不受影响。这与 `Formula.alternatives` 是同一条纪律：点名使用，从不静默。
  3. `made_of`（T3a）带上 `substituted`。
  4. 仪器：`scripts/unmapped_family_concepts.py`——列出已准备发行人下 `normalized_metric IS NULL` 且名字匹配 `LongTermDebt|Borrowings|NotesPayable|CommercialPaper|DebtCurrent|DebtNoncurrent`（排除 `Maturities|InterestRate|Receivable|FairValue|Capacity`）的原始标签；一条 live 测试要求十只持仓在改后只剩已知三条（JPM 的 secured borrowings、KO 的授信额度、LLY 的 `NotesPayable`），新增即红。这是「桌子不读的标签」第一次可见。
- 测试：`normalize_concept` 两条；containment：成员从未申报 + 替代在场 → cover 完整且 `substituted` 非空；成员在场 → 替代不用；`test_v9_containment`/`test_v13_issuer_panels` 语义不变。
- 验收（fixture live）：XOM `total_debt` at 2025-12-31 = 9.296 + 34.241 = **$43.54B**，formula 点名替代；`fcf_to_debt` FY2025 从 254.0% 降到约 54%（254% × 9.296 / 43.54）；`debt_to_ebitda` 相应重算并记入验收记录。sol Q02 的 254%/9209.8% 不可能再出现。
- 更正既有文档：V37 §3.2 的 S1 结论（「该发行人无长期债务科目」）改为「长期债务在桌子不读的标签下」。

**S4 · 一个命名函数，两个门共用**

- 位置：`typed_calculator._parse_book_name` :149-163（`portfolio.integration.<key>.<label>` 四段 → 度量前三段、主体 label；任何三段名 → `a.c` 与 `b`）；`_resolve_named` :251-273 用它给 `pick` 出来的数定身份。`program_service._facts_of` :1937-1944 表路径只拆 `_LABELLED_TABLES`（:262-263）的三段名，其余整名。同一个 `portfolio.integration.net_beta.equity_down`：表门 = 度量整名、主体 calc id；pick 门 = 度量 `portfolio.integration.net_beta`、主体 `equity_down`。`answer_check._measure_words` :237-244 取最后一段成词——pick 门的度量成了「net beta」两个词，C 轮 `measure_mismatch 'net beta'` mini 17 次、sol 10 次由此而来。`portfolio.reconcile.sum_of_position_contributions` 同理拆成主体 `reconcile`。
- 改法：`analytics/resources.py` 加 `identity_of(label) -> (measure, subject)`，数据表驱动：
  - 三段且首段在 `LABELLED_TABLES`（从 program_service 搬到这里）→ `(table.col, label)`；
  - `portfolio.integration.room_to_{warning,breach}.<check>` → `(portfolio.integration.room_to_*, check)`——检查是一个实体（`answer_check._same_check` :246-253 已按此比较）；
  - `portfolio.integration.{net_beta,gross_beta}.<risk>` → `(整名, None)`——风险名不是实体；
  - 其余（`portfolio.reconcile.*`、`portfolio.drawdown_episodes.*`、`exposure_metrics.*`）→ `(整名, None)`。
  - `_facts_of` 表分支与 `_parse_book_name` 都调用它。主体为 None 时仍回落到 base（calc 行 / run），与今天的表路径相同。import 法则：typed_calculator 不 import program_service，`LABELLED_TABLES` 因此搬到 analytics。
- 测试：`identity_of` 表测试；两个门对同一标签给同一身份（net_beta、room、issuer_exposures 各一）；`tests/test_v37_answer_check_corpus.py` 不受影响（语料是记录下的事实）。
- 验收：把 C 轮 27 次 `measure_mismatch 'net beta'` 所在的 brief 用新身份重查（语料带账本，把 pick 事实的 measure 按 `identity_of` 改写后过 `handoff_check`）→ 0。

**S5 · `book.reconcile` 的键列全**

- 位置：`analytics/skill.py:229-236` yields 三个；`analytics/resources.py:211-214` `CALC_RESULTS["portfolio.reconcile"]` 声明五个（单位齐全）；`reconcile_service.py:252-256` 记录五个；`signature_text` :698-705 从 yields 渲染语言页；`method_for_yield`/`call_for_yield`（skill :312、:341）从 yields 路由。
- 改法：yields 加 `portfolio.reconcile.sum_of_factor_contributions`、`portfolio.reconcile.alpha_plus_residual`。机械测试：每个 `subject_kind in (run, portfolio)` 的方法，`CALC_RESULTS[<family>]` 的键 ⊆ 它的 yields——「语言页列出服务记录的每一个数」。
- 测试：上述守卫（先红后绿：先看它还揪出谁）；`signature_text` 含新键。
- 验收：sol Q18 那类「用持仓合计对账」不再是面上唯一能选的键；D 轮 Q18 的对账句用因子合计。

### 2.4 skill 层

**K5 · 净 beta 的符号说明**（措辞，过目后落）

- 位置：`analytics/skill.py:803`（`book_market_risk.desk`：「the netted exposure enters TLT and HYG with the sign opposite to the risk they proxy」）、`:424-430`（`Reading("book.analysis")` 同一句）、`:221`（`Method book.analysis.procedure`）。代码 `analytics/integration.py:37-45` `_RISK_SENSE`：TLT、HYG、SPY、QQQ、IWM 五个都是 −1。最新一期 SPY 1.2587 + QQQ −0.2034 + IWM −0.1954 = 0.8599 → `net_beta.equity_down` = −0.8599，即净多头；mini Q08 按 skill 的话读成了「净空头」。
- 改法：三处改为「every factor enters with the sign of the risk's effect on the book: a positive beta to SPY, QQQ or IWM is a loss when equities fall (equity_down), a positive TLT beta a loss when rates rise (rates_up), a positive HYG beta a loss when spreads widen (credit_spreads_widen); a net beta below zero means the book loses when that risk happens — it is long the risk, not short it」。
- 测试：`tests/test_v37_offers.py` 旁加一条：desk 文字点名 `_RISK_SENSE` 里每个 sense 为 −1 的因子（文字和代码钉在一起，改一处另一处红）。
- 措辞进 `WORDING.md`，与 T1/T3/T4 的 `HOW_TO_CITE` 四句一起过目。

## 3. 阶段与顺序

| 阶段 | 内容 | 为什么这个顺序 |
|---|---|---|
| **A · 语言与身份**（纯离线，不涉措辞） | L1、L2、S4、S5、T3(d)(e)(f) | 都是解析/命名/文字的小改，各自有离线重放可验；先做，B 的重放数字才干净 |
| **B · 显示** | T1、T2、T3(a)(b)(c)、T4、K5 文字 | 四句 `HOW_TO_CITE` + K5 三句 → 重跑 `scripts/v36_wording.py` → `WORDING.md` 差异一次过目 |
| **C · 数值** | S1、S2、S3（含 fixture `remap_concepts.py --apply`） | 改的是服务的数，验收靠 fixture live |
| **D · 验收** | §4.1 离线重放脚本 + §4.2 fixture live + A-R1 已修（前置，见 topic next ①）→ 先跑 `credit_probe.py` → D 轮（模型按 boss） | 不花额度先把能量的量完 |

每阶段一次离线全量（`pytest -m "not live" -q`）；C 阶段另跑 fixture 的 live 标记测试。每条改动一笔提交，提交信息带条目号。

## 4. 验收线

### 4.1 离线重放（C 轮记录，不花额度）

把 `docs/spikes/v37/tools/replay_read.py` 改成 `tools/replay_v38.py`：仍按记录顺序取每次 `run` 的事实与程序（`args.program.return` 有记录），经过**新**的 `adapt`/`cap`/`render` 重放；类型拒绝用 `typecheck` 重查记录下的程序；措辞误报用语料重查。

| 量 | C 轮（mini / sol） | 目标 |
|---|---|---|
| 点名节点有图从未显示（节点数） | 115 / 274 | 0 / 0（例外：点名内容自身 > 24k 字符的 run，逐条列出） |
| 点名的被扣、未点名的显示（run 数） | 12 / 26 | 0 / 0 |
| 拒绝事实未到分析师眼前 | 30 / 52 | 0 / 0 |
| 先登记后吞掉（`SWALLOWED_NEVER_SHOWN`） | 343 / 789 | 0 / 0 |
| 全空结果 / 只剩扣下提示 | 4+4 / 17+8 | 0 / 0 |
| 类型拒绝（重查记录的程序） | 13 / 12 | mini 8（清掉 Q07 seq10/13、Q08 seq4/8、Q12 seq10；剩 Q07 seq4 unknown_method、Q07 seq7/15 latest 用在标量、Q03/Q10 seq4 read_filings 当原语、Q19 seq10/19、Q08 seq13 变成真错「未绑定」）/ sol 10（清掉 Q13 seq13、Q15 seq4；Q13 seq54 的 `abs.of` 仍是真错） |
| `measure_mismatch 'net beta'`（语料重查） | 17 / 10 | 0 / 0 |

### 4.2 fixture live

- S1：AAPL 季度 DSO 2023-09-30 ≈ 30.0，年度 28.10。
- S2：MSFT `ebit_interest_coverage(at=财年末)` 五个数 = 年度序列五个点；`as_of` = `at`。
- S3：XOM `total_debt(at=2025-12-31)` = $43.54B，formula 点名替代；`fcf_to_debt` FY2025 ≈ 54%；`unmapped_family_concepts` 只剩已知三条。
- S5：`signature_text` 含两个新键；守卫测试绿。

### 4.3 D 轮（对照 C，同 fixture、同条件）

| 线 | C（mini / sol） | 目标 |
|---|---|---|
| 假陈述源头为 C（工具）的条数 | 7 / 2 | ≤ 1 / 0 |
| 「工具没交付后断言或心算」类假陈述 | 7 / 0 | 0 |
| `held_back` 提示（工具上限 + digest 截尾） | 31 / 62 | ≤ 8 / ≤ 12 |
| type_errors 占 run 的比例 | 18.8% / 7.1% | < 8% / < 4% |
| Q08、Q11、Q15、Q16 | mini 全错 | 出答案且无假陈述 |
| Q13 | 两轮都没看到买入被拒 | brief 写出「buy refused: no_sector」 |
| Q10（sol） | 5 次空调用 | 0 |

## 5. 需拍板

1. **原语 `fundamentals(at=)` 对流量**：V33 规则 6 让它拒绝（`program_service.py:918-927`）。S2 之后 `at` 对方法的含义是「截至 at」，原语是否同样接受（`at` + `months` = 以 at 为止的窗口）？我建议接受，一条规则两个门；不接受也行，拒绝原话已经指路。
2. **含租赁的长期债务作为替代成员**：`LongTermDebtAndCapitalLeaseObligations` 含融资租赁义务，比 `LongTermDebtNoncurrent` 略宽。S3 的做法是只在正主从未申报时点名替代（XOM、KO），GOOGL 不动。另一个选项是给它自己的家族成员地位（总债务就含租赁）——那会改 GOOGL 的总债务。我建议前者。
3. **存量除以季度流量的比率**（`debt_to_ebitda`、`net_debt_to_ebitda`、`fcf_to_debt` 在 `months=3` 上）：年化，还是保持现状但事实带窗口？本计划不动（mini Q02 的 0.44× 没到读者面前）。
4. **字面量是显示还是铸成事实**：T3(c) 选显示 + 引用规则（V33 的决定不变）。
5. **K5 三句与四句 `HOW_TO_CITE`**：措辞过目。

## 6. 风险

- **T1 藏起中间节点**：分析师有时想看没点名的整表（mini Q08 seq29 就是主动 `return` 两张表）。`nodes` 条目带条数，再跑一次即可；`return` 省略时仍显示全部。
- **T2 拒绝不进上限**：一个程序几十条 `depends_on_refused` 会撑大结果——T2 的折叠把它压成一条加名单；`dumps_capped(keep=…)` 是最后一道。
- **S3 改动存量数据**：`remap_concepts.py` 重写 fixture 与生产库的 `normalized_metric`；生产库随部署放行一起跑，跑前备份（`backups/battery/` 的做法）。
- **S4 改表门身份**：`room_to_*` 图形在表门的主体从 calc id 变成检查名，门的 tier 规则据此比较——单元测试覆盖两个门；语料测试不受影响。
- **S1 改 scale 行**：`cash_conversion_cycle` 的三次 scale 因子随窗口变，`test_registry_conditions` 的调用序列断言要跟着改。
- **`HOW_TO_CITE` 变长**：+4 句约 120 token，只在 system 出现一次（V37/T5(b)）。
- **A-R1 未修就跑 D 轮**：会再崩。它在 topic 的 next ①，本计划不含，但 D 轮前置。

## 7. 本轮不做（有记录，各有出处）

- 情景买入已持有的 TLT 报 `no_sector`（`scenario_service`；ATTRIBUTION §6）——T2 之后分析师至少能看见这条拒绝。
- `mul`/`scale` 接受单边字面量（sol Q19 的自算份额）。
- `place` 在 20 条异类限额检查里排名、并列随意（TOOLS §3.9）。
- 净 beta 单位 RATIO 显示成百分比。
- `section_not_found` 不列可读的 Item；`window_return` 两个入口；`months` 默认值不在语言页。
- 搜索额度 5 次共用；段落抽取粘连。
- 门的八类误报与五类漏报（topic next ③④）。
