# C 轮的工具层：工具本身的错误，以及工具的返回有没有让模型读错（2026-09-16）

> **问题**（用户 9/16）：先分析 tool：tool 本身的错误，以及 tool 返回的结果是否不够清晰，导致模型理解错误。
> **材料**：`V37C`（gpt-5.4-mini）与 `V37C_sol`（gpt-5.6-sol）两轮，共 40 个 session。另写了一个只读重放 `tools/replay_read.py`，按记录顺序重建了每个域分析师每次取证调用读到的全文：mini 111 次，sol 212 次。重建依次经过记录的事实、`F.cap`、带 `seen` 的 `digest.render` 和 `dumps_capped`，每个 completion 的读入上限按实际调用数均分。
> **重建的可信度**：在「一次 completion 只有一次 run」的读入上，重建字符数与记录的 `read.chars` 对比如下：mini 48/48 相差不到 5%（35 次完全相同），sol 92 次里 88 次不到 5%（67 次完全相同）。偏差来自重建里没有 `made` 情景条目（sol Q13）。
> **代码**：未动。
> **与 `ATTRIBUTION_V37C.md` 的关系**：本文把那份文档里的 C 类、D 类和 B 类往工具层再追一层。凡改变那份文档结论的地方，都列在 §5。

## 0. 结论

**一、工具没有执行模型写下的意图。**

- 程序的 `return` 只是声明。执行器把每个中间节点的事实都交出来，工具上限（`F.cap`）和 digest 都不看 `return`。
- mini 的 56 次 run 都写了 `return`，分析师读到的图形里有 45% 属于没点名的节点；sol 是 58%。点名的数被扣、没点名的反而显示出来的 run，mini 有 12 次，sol 有 26 次。
- 点名节点里有图形从没到过分析师眼前的：mini 296 个里有 115 个，sol 801 个里有 274 个。其中一个数都没显示的：mini 107 个，sol 264 个。
- 扣下提示要分析师「只在 `return` 里点名需要的节点再跑一次」，这个办法并不存在。归因文档里的「缺陷一：上限按生成顺序截断」只是这件事的症状。
- 同类问题还有三处：
  - 写在 `vector.entries` 里的嵌套表达式不求值，而语言页恰恰引导模型这样写；
  - `book.reconcile` 的工具面上缺「因子贡献合计」这个键；
  - 窗口收益有两套入口。

**二、工具的输出不是「完整的事实，或拒绝」。**

模型读到的结果里，有 10 种静默丢失：

1. 工具上限扣下的数；
2. **拒绝本身**：工具上限不分数值和拒绝，mini 有 30 条、sol 有 52 条拒绝没到分析师眼前。两轮 Q13 的买入被拒（`no_sector`）都属于这种，分析师始终不知道买入没做成；
3. digest 截掉的数；
4. 截掉之前已被登记为「已显示」、后来被吞掉的数；
5. 节点的种类：digest 只列节点名，一个被拒的节点和一个算出来的节点看起来一样；
6. 向量里被拒的条目；
7. 字面量节点的值（峰谷日期）；
8. 工具已写在节点备注里的话（V37/S1 的「总债务只含短端」）；
9. 参数错误的具体字段；
10. 第 3 个以后的类型问题。

另有两类结果没有任何说明：完全空的结果，mini 4 次、sol 17 次；只有一条扣下提示的结果，mini 4 次、sol 8 次。

**三、工具自己的值、身份和单位有错。**

- **数值：**天数公式不论窗口长短一律乘 365；存量除以季度流量的比率不做年化；总债务只有短端时，`fcf_to_debt` 仍然出值；流量类方法不认 `at`，写哪个日期都返回最新一期。
- **说明：**净 beta 的正负号约定只写在代码里，skill 和语言页的说明是错的（只说 TLT、HYG 反号，SPY、QQQ、IWM 其实也反号）。
- **单位：**beta 按百分比显示。
- **主体：**`pick` 取出的数被拆成「主体 `equity_down`、度量 `portfolio.integration.net_beta`」；分析结果的主体是不透明的 calc id。
- **窗口：**min/max 不带窗口。
- **名次：**`place` 在 20 条异类限额检查里排名。

**工具的返回有没有让模型读错：17 条假陈述逐条判断（详见 §4）**

| 判断 | 条数 | 哪几条 |
|---|---|---|
| 工具的值本身错 | 2 | sol Q02 FCF/debt；sol Q09 季度天数表 |
| 工具没交出点名的数，模型在空白处断言或心算 | 7 | mini Q08 上一期；Q11 排序；Q15 三条；Q16 两条 |
| 工具交了，但说明缺失或写错，诱导读错 | 4 | mini Q08「净空头」两条；mini Q09「三年」；sol Q18 对账 |
| 工具交得清楚，模型自己读错 | 3 | mini Q01 存货；sol Q09 方向两条 |
| 与工具无关 | 1 | sol Q04（门误拒，加上交接只取最后一次提交） |

17 条里有 13 条有工具原因。工具交得清楚、仍然读错的只有 3 条。

## 1. 先判角色：工具越界，或没做自己的工作

判定口径是 boss 的四角色规则。对工具的要求是：正交，让 LLM 能执行它想做的事，输出永远是完整的事实或拒绝，只执行机械约束。

| 失职或越界 | 表现 | 节 |
|---|---|---|
| 工具没让 LLM 执行它的意图 | `return` 不起作用；entries 里的嵌套不求值；`book.reconcile` 缺键；窗口收益有两套入口；毛利只有 `gross_profit` 一条路径；流量类方法不认 `at` | §3.1、§3.6、§3.8、§3.9 |
| 输出既不完整、也不拒绝 | 拒绝本身被扣下；扣下、截尾、吞掉、部分向量、字面量、节点种类与备注、参数细节被丢；空结果不说原因 | §3.1b–§3.5 |
| 把实现暴露给 LLM | 扣下提示列的是 `calc_…:度量`，不是节点名；主体是 calc id、`reconcile`、`equity_down`；LLM 得自己知道 `return` 不过滤、entries 里不能嵌套 | §3.3、§3.6、§3.9 |
| 工具做了（错的）领域判断 | 天数固定乘 365；季度流量不年化；分母不全仍出比率；`place` 跨异类检查排名 | §3.9 |
| skill 的知识写错了（顺带记下） | 「TLT and HYG enter with the sign opposite」，而 SPY/QQQ/IWM 也反号 | §4 mini Q08 |

## 2. 工具通道的沟通：次数与 schema

### 2.1 次数

| 方向 | 载体 | mini | sol |
|---|---|---|---|
| 域分析师 → tools | `run` | 69 次：56 次有结果，13 次类型拒绝 | 168 次：156 次有结果，12 次拒绝 |
| 域分析师 → tools | `read_filings` | 42 次：33 次有段落，7 次 `section_not_found`，2 次参数拒绝 | 44 次，都有段落 |
| 域分析师 → tools | `compile` | 7 次：4 次出程序，3 次 no program | 0 |
| 域分析师 → worker | `search_web` | 13 次：6 次有结果，7 次额度用尽 | 11 次：6 次、5 次 |
| 域分析师 → worker | `start` | 6 | 3 |
| 域分析师 → check | `submit` | 58 次：13 次收下，45 次拒绝；另有 2 次兜底 | 98 次：39 次、59 次；另有 2 次兜底 |
| 宣告了但没落库（多为原样重发，在本地作答） | — | 24（宣告 219 次，记录 195 次） | 11（宣告 335 次，记录 324 次） |
| 主分析师 → delegate | tasks | 26 次，37 个任务；另有 2 次派单被拒 | 50 次，59 个任务 |
| 主分析师 → read_report | — | 7 次：1 次 verified，5 次 refused，1 次 unknown | 3 次，都是 refused |
| 主分析师 → answer | — | 31 次：13 次收下，18 次拒绝 | 28 次：18 次、10 次 |

### 2.2 schema：真实载荷

**`run` 请求**（mini Q16 seq4，节选）

```json
{"program": {"let": [
  ["analysis_prev", {"fn": "method", "name": "book.analysis", "subject": "$book_prev"}],
  ["net_beta_prev", {"fn": "pick", "of": "$analysis_prev", "key": "portfolio.integration.net_beta.equity_down"}],
  ["change_net_beta", {"fn": "sub", "a": "$net_beta_latest", "b": "$net_beta_prev"}]],
 "return": ["beta_spy", "beta_qqq", "net_beta_latest", "net_beta_prev", "change_net_beta"]}}
```

**`run` 结果**，即分析师读到的 digest。键为 `request, figures[], series[], passages[], started[], boundaries[], nodes[], made?`。同一次调用里的样例如下：

```json
{"id": "f_088d1d4d7afe", "subject": "calc_cdeb54145930", "measure": "portfolio.integration.net_beta.equity_down",
 "value": "-86.0% [f_088d1d4d7afe]", "unit": "RATIO", "as_of": "2026-09-10", "node": "analysis_latest",
 "label": "portfolio.integration.net_beta.equity_down", "method": "book.analysis"}
{"id": "f_123903763bce", "subject": "AAPL", "measure": "price.beta", "value": "0.68× [f_123903763bce]",
 "unit": "MULTIPLE", "as_of": "2026-09-10", "node": "beta_spy", "place": 6, "of": 10, "label": "AAPL", "method": "price.beta"}
{"class": "held_back", "text": "54 more figures were computed and are on the ledger, not shown here: run the same program again with `return` naming only the nodes you need",
 "measures": ["AAPL:price.beta", "AMZN:price.beta", "GOOGL:price.beta", "…（共 20 条，按字母排序截断）"]}
{"class": "held_back", "by": "digest", "count": 37, "text": "figures computed and on the ledger but not shown here: the request was too wide for one digest; ask again for the names you need",
 "measures": ["calc_3e32bf7addaa:portfolio.integration.gross_beta.credit_spreads_widen", "…（共 30 条）"]}
"nodes": ["beta_spy", "beta_qqq", "book_latest", "book_prev", "analysis_latest", "analysis_prev", "net_beta_latest", "net_beta_prev", "change_net_beta", "book_betas"]
```

series 条目的字段是 `{id, subject, measure, unit, n, node, spacing, span, first, last, points?(≤12 个点)}`。

**类型拒绝**：工具返回 `{"error": "type_errors", "problems": [{at, reason, arg?, expected?, got?, fix?, detail?, problems?, params_schema?}], "detail"}`。digest 把它压成一条 boundary 文字，只取前 3 个 problem 的 `fix`、`detail`、`problem`、`reason` 中的第一个：

```
run(): the program did not run: … — entries.MSFT: vector.entries.MSFT takes scalar; entries.MSFT: …
```

**工具返回里有、模型却看不到的**：

- 每个节点备注里的 `value`、`window`、`basis`、`no_facts_for_issuer`、`missing_at_this_date`、`refused_entries`、`literal`（digest 只保留节点名）；
- 顶层的 `returns`、`settled`、`refused`、`partial`；
- `held_back.how`；
- `problems[].problems` 与 `params_schema`。

**E10**（delegate 的返回，主分析师读）：

```
{analysts: [{domain, task_id, status, report_id?, coverage,
             findings: [{want, asked, finding, desk_said?}], not_done,
             caveats?, follow_ups?, refused?, made?, shown?, cost}],
 how_to_cite}
```

`finding` 是带 `[id]` 的散文，数值本身不带主体、度量和日期。`shown` 只保留 `value, subject, measure, as_of, place, of, node, unit`，没有 `window`。

## 3. 工具本身的错误

### 3.1 `return` 不起作用

**位置**：

- `program_service.run` 对每个节点都执行 `facts += node.facts`；
- `fact_adapters.run_program` 原样取出；
- `F.cap` 从头保留；
- `digest.absorb` 不读 `returns`。

语言页上 `return` 的说明是「the bindings the answer will point at (default: all)」。V37/T5(d) 把扣下提示改成「用 `return` 收窄」，但没有代码实现收窄。

**证据**：

| | mini | sol |
|---|---|---|
| 写了 `return` 的 run | 56/56 | 146/156 |
| 事实：点名节点 / 未点名节点 | 1544 / 1531 | 1985 / 4720 |
| 显示：点名节点 / 未点名节点 | 610 / 498（未点名占 45%） | 770 / 1057（未点名占 58%） |
| 点名的数被扣、未点名的却显示 | 12 次 | 26 次 |
| 点名节点中，有图形从未显示的 | 115/296（26 次 run，10 题） | 274/801（55 次 run，10 题） |
| 其中一个数都没显示的 | 107 | 264 |
| 按节点计的原因 | 工具上限 87，fit 截掉 19，先登记后吞掉 16，孪生被截 2 | 工具上限 231，fit 15，吞掉 18，拒绝被 dump 截掉 8，序列被 dump 截掉 2，孪生 2 |

以 mini Q08 seq24 为例：`return` 只有 `latest_exposure` 和 `prev_exposure` 两个标量。执行器生成了 98 条事实，两张 48 行的分析表排在前面，这两个标量排第 97、98 位。`F.cap` 在 65 条处停下（23,665 字符），两个点名的数都被扣下。分析师读到的 31 个图形全部来自 `analysis_latest`。

**七层**：落在 tool 层（适配器与 digest 不认 `return`）和 service 层（执行器交出全部节点）。越界的是工具：它没执行 LLM 写下的意图。

**修法落在 tool 层**：账本照旧记下全部事实；显示按 `return` 裁剪，没点名的节点只列名字和事实条数。

**效果**：工具上限只在点名内容本身过大时才会触发，扣下提示也就可以执行。

### 3.1b 拒绝也被上限扣下

`F.cap` 按条数和字符数截断，不区分数值事实和拒绝（absence）事实。拒绝事实跟在它所属节点后面生成，经常排在一张大表之后。digest 的 `nodes` 又只列名字，不列 `kind`，所以分析师连「这个节点被拒了」都看不出来。

| | mini | sol |
|---|---|---|
| run 产生的拒绝事实，已显示 | 52 | 208 |
| 被工具上限扣下 | 30 | 42 |
| 被 `dumps_capped` 截掉 | 0 | 10 |

`dumps_capped` 截掉的是 sol Q04 seq4、Q06 seq16 结果末尾的 boundary 条目。它留下的说明是「omitted to fit the message size limit — these were computed and can be requested individually」，可被截掉的恰恰是拒绝，不是算出来的数。

两轮 Q13 是最重的例子：

- **mini Q13 seq4、8、13**：`after2 = buy(run=$after, buys=[{TLT, 0.05}])` 三次都被拒，原话是「no_sector: TLT has no sector on this desk…」，三次都被扣下。
  - 分析师读到的 TLT 6.14%（`f_016cdc1c631f`）来自节点 `after`，也就是只做了卖出的那本书：卖掉一半 NVDA 后，TLT 的权重从 6.01% 被动升到 6.14%。
  - 它把这个数读成了买入的结果：「Sell half the NVIDIA holding and use the proceeds to buy TLT is reflected in the scenario book … TLT is at 6.14%」。
  - 重建出的读入里，`no_sector` 一次也没出现过。
- **sol Q13 seq4、7、10、22**：同一个拒绝被扣了 4 次，分析师也从没读到过。
  - 它在 seq13 换成 `method(book.buy, …)` 去试，又撞上「params do not fit the method's schema」，而这条拒绝的字段细节被丢掉了（§3.5d）。
- **mini Q16 seq10**：`pick(key=portfolio.integration.net_beta)` 的拒绝（`unknown_name`）被扣下，分析师不知道自己为什么没拿到数，接着又写了一遍「两期相同」。

### 3.2 digest 先登记「已显示」，再截尾

**位置**：`digest.render` 先 `tell_apart(items, seen)`，再 `fit`。被 `fit` 剪掉的图形已经进了 `seen`。

**证据**：从未显示、却被当作已显示吞掉的事实，mini 343 条，sol 789 条，涉及点名节点 mini 16 个、sol 18 个。几个例子：

- mini Q01 seq28、seq30：余量重跑，65 条和 63 条事实，读到 196 和 159 字符，0 个图形；
- mini Q11 seq13：0 个图形；
- mini Q19 seq32：AMZN 贡献，22 条全被吞掉，读到 192 字符。

### 3.3 扣下提示既做不到，也读不懂

**提示文字**：见 §2.2。它要求的操作不存在（§3.1）。所列的 `measures` 是「主体:度量」，按字母排序后截到 20 或 30 条。大写代码排在前面，`calc_…` 开头的条目排在后面、最先被截掉。提示从不写节点名。

**证据**：

- 有图形丢失的点名节点中，提示里一条都没列出的：mini 102 个里有 33 个，sol 245 个里有 101 个（`tools/notice_check.py`）。
- mini Q16 seq4 扣下 54 条，列出的是 `AAPL:price.beta`、`AMZN:price.beta` 等；`net_beta_prev`、`change_net_beta` 不在列表里。
- digest 的截尾提示列出了 `calc_3e32bf7addaa:portfolio.integration.net_beta.equity_down`，但分析师无从知道 `calc_3e32bf7addaa` 就是它自己的 `analysis_prev`。

### 3.4 没有说明的空结果

「一个读数只显示一次」按设计会合并重复。但合并若发生在跨调用之间，这一次的结果里不留任何痕迹：`also` 只挂在本次调用显示出来的图形上，而 `HOW_TO_CITE` 也从没解释过合并。

| | mini | sol |
|---|---|---|
| 事实有、结果全空（没有 figures、series、boundaries） | 4 次：Q01 seq28、seq30；Q07 seq25；Q19 seq32 | 17 次 |
| 结果里只有一条扣下提示 | 4 次：Q11 seq13；Q15 seq14、19、22 | 8 次 |

以 sol Q10 为例，分析师想取 MSFT 五个财年末的覆盖率：

- seq53 一次写了 5 个 `method(ebit_interest_coverage, params={at: 2021-06-30 … 2025-06-30})`。工具不认 `at`（§3.9），5 个节点得出同一个读数：2026-03-31 的 55.65×。分析师只读到 1 个图形，`node` 是 `coverage_2021`，`as_of` 是 2026-03-31，`also` 里挂着另外 4 个 id。
- seq57–61 又逐个单独重取，每次读到的都是同样 121 个字符：

```
{"request": {}, "figures": [], "series": [], "passages": [], "started": [], "boundaries": [], "nodes": ["coverage_2021"]}
```

分析师最后改用年度序列上的点，写对了数，所以没有造成错话，但花掉了 5 次取证额度。工具从头到尾没说过一句「你给的日期没被使用」。

### 3.5 digest 丢掉了工具已经说出的话

`digest.absorb` 只保留节点名，`_problem_text` 只取一层文字。

- **(a) V37/S1 的补救没送到分析师。**`program_service._note_of` 把 `no_facts_for_issuer`、`missing_at_this_date`、`overlapping_not_added` 写进了节点备注，digest 把它们丢了。见 sol Q02（§4）。
- **(b) 向量中被拒的条目。**sol Q12 seq22 的 `roe_by_bank = method(roe, [JPM, GS])` 里，GS 那一项被拒。结果只显示 JPM，完全没提 GS；只能从排序节点的「got 1」间接推出来。
- **(c) 字面量节点的值。**
  - sol Q14 seq4、6、10 的 `return` 点名了 `peak`、`trough`（seq4 还有 `recovery_date`），结果里一个日期也没有。seq10 的 `return` 只有这两个节点，读到的却是 `episodes` 表的 4 个图形（三个深度、一个片段数）。
  - 分析师的原话：「the episode output did not expose the peak date, trough date, or recovery status as ledger figures」。
  - mini Q14 seq4 也是同样情况。
- **(d) 参数错误的具体字段。**
  - 工具把 `invalid_params` 的逐字段 `problems` 和 `params_schema` 都交了出来，分析师读到的只有「book.buy: params do not fit the method's schema」。
  - 出现在 sol Q13 seq13（分析师改写买入腿的那一次）、sol Q06 seq5、sol Q18 seq19。
- **(e) 只显示前 3 个类型问题。**mini Q07 seq7 有 4 个问题，第 4 个（entries 嵌套）没显示；下一次 seq10 就卡在这个问题上。

### 3.6 `vector.entries` 里的嵌套表达式不求值

**位置**：`program_service.parse.hoist` 会展开写在参数位置的 `{fn: …}`，但不进入值为普通字典的参数（`entries`）。类型检查因此看到 `got: object`，写出的修法是「vector.entries.X takes scalar」。可 `latest(...)`、`at(...)`、`avg(...)` 本来就产出一个数。

语言页对 `vector` 的说明是「{label: $scalar | number}; a series is not a scalar — latest(of) first」，模型照字面把 `latest(of=…)` 直接写进了 entries。

**离线复现**：

```
entries={"AAPL": {"fn":"latest","of":"$conv"}}  → got "object"，"vector.entries.AAPL takes scalar"
先绑定 l = latest($conv)，再写 entries={"AAPL": "$l"} → 无问题
```

**本轮实例**（逐次重跑类型检查）：

- mini 13 次类型拒绝里有 8 次属于这一类，共 23 条问题：Q07 seq4、7、10、13；Q08 seq4、8、13；Q12 seq10。
- sol 有 2 次：Q13 seq54、Q15 seq4。

它还把别的错误藏了起来：mini Q08 seq13 引用了上一个程序的绑定，因为嵌套对象不会被检查，这一条从没被报出来。

**影响**：mini Q07 的现金转换排序、mini Q08 的三家各年排序、mini Q12 的排序都因此没做成。

### 3.7 其他拒绝原话

- **`read_filings(ticker='NVDA', item='7', form_type='10-Q', k=3): section_not_found`**
  - 整条只有错误代码，mini 出现 7 次：Q04、Q14 四次、Q19、Q20。
  - 没说 10-Q 的 MD&A 在 Item 2，也没列出可读的 Item。Q14 换了四个代码重试同一个 Item。
- **「did you mean book.buy, book.sell, book.analysis?」**
  - 对 `_aws_text_basis_1`（mini Q19 seq10）和 `scenario`（sol Q10 seq41）给出，与模型想做的事无关。
- **`not_alone` 的拒绝**
  - 原话是「…these factors are collinear, so no single beta is determined; their sum, -0.00471605, is」。
  - 合计只出现在散文里，不是可引用的事实；句子不完整；经 `depends_on_refused` 在 sol Q18 seq4 里重复了 9 遍。
- **「total_debt was not computed — series_not_derivable: … none of its inputs () is filed as a series by XOM」**
  - 列表是空的。
- **「after was not computed — no_sector: RATES_SHOCK_UP has no sector…」**（mini Q10）
  - 情景名被当成股票代码，拒绝理由写成「没有行业」；主分析师后来把这句当作做不到的原因转述给了读者。

### 3.8 工具面上写的，与服务实际做的不一致

- **`book.reconcile` 的键不全。**
  - 语言页列出的键：`sum_of_position_contributions | factor_share | unexplained_share`。
  - 服务实际记录的还有 `sum_of_factor_contributions` 和 `alpha_plus_residual`（`reconcile_service.py:252-256`）。见 sol Q18。
- **`book.analysis` 的 `key=…net_beta.<risk>` 没列出 `<risk>` 可取的值，也没说正负号的含义。**
  - skill 的读法与 `book_market_risk` 的 desk 文字都写着「TLT and HYG enter with the sign opposite to the risk they proxy」。
  - 代码里 SPY、QQQ、IWM 在 `equity_down` 上同样按 −1 计入（`integration.py:42-44`）。
  - 最新一期：SPY 1.2587、QQQ −0.2034、IWM −0.1954，三者之和 0.8599，`net_beta.equity_down` 为 −0.8599，即净多头。见 mini Q08。
- **窗口收益有两个入口。**
  - 方法 `price.window_return` 只接受 1m/3m/6m/1y，原语 `window_return(ticker, start, end)` 接受日期。
  - mini Q17 用了方法（1y，却把节点命名为 10d），sol 用了原语。
- **issuer 方法的默认 `months` 没写明。**
  - 默认是 12；`last_n: 12` 不带 `months` 时，返回 6 个年度点，不说明「12 个里只有 6 个」。序列带了 `spacing: annual`，但 mini Q01、Q04、Q09 仍写成季度。
- **`gross_margin` 只认 `gross_profit`。**没有「收入减营业成本」这条路径（Q04、Q20）。
- **情景买入要求行业。**已持有的 TLT 因此被拒：`no_sector`（mini Q13）。
- **`mul` 和 `scale` 接受单边字面量乘数。**sol Q19 借此把自己算的份额写进了账本。

### 3.9 值、身份、单位

- **天数公式固定乘 365。**
  - `formula_service` 对所有 `count` 类除法执行 `scale(…, DAYS_IN_YEAR)`，不看 `months`。
  - 季度版因此放大约 4 倍：2023-09-30 的应收天数，季度版 120.34，年度版 28.10（sol Q09）。
- **存量除以流量的比率在季度窗口上不年化。**
  - `debt_to_ebitda`、`net_debt_to_ebitda`、`fcf_to_debt` 用的是 3 个月的流量。
  - mini Q02 经 `compile("last 4 quarters")` 得到季度净债务/EBITDA 0.44×，这个数没有到读者面前。
- **总债务只有短端时，`fcf_to_debt` 仍然出值。**
  - XOM 只申报 `debt_current_total`。
  - sol Q02 seq4 读到的 `fcf_to_debt` 为 843.1%、9209.8%、817.8%、619.9%、254.0%，`debt_to_ebitda` 为 0.01×–0.14×。同一个结果里，`total_debt` 却被判为做不到。
- **流量类方法不认 `at`。**
  - 语言页写着 issuer 方法都接受 `at (date)`。余额类（`total_debt`、`net_debt`、`equity_multiplier`）确实按日期取数，流量类却不管 `at`，一律返回截至 2026-03-31 的最新窗口。
  - 事实的 `params.at` 写着 2021-06-30，`as_of` 却是 2026-03-31，身份自相矛盾。
  - sol 共 18 条：Q10 的 `ebit` 5 条（五个财年末都是 $157.33B）、`ebit_interest_coverage` 10 条（都是 55.65×），Q12 的 `roe` 2 条，Q20 的 `net_margin` 1 条。
  - ROE 的两个数不同（17.96%、17.08%）、`as_of` 相同，说明日期只移动了余额那一腿，利润仍是最新一期，算出来的是两个时点拼起来的数。
  - 这 18 条都没有被写进 brief 或答案，但 sol Q10 因此多花了 5 次调用（§3.4）。
- **净 beta 的单位是 RATIO。**显示成 −86.0%、0.86%，读起来像仓位占比。
- **主体。**
  - `book.analysis` 的图形，主体是不透明的 calc id，latest 和 prev 两期只能靠节点名区分。
  - `pick` 取出的数经 `typed_calculator._parse_book_name` 定身份，带点号的键被拆开：
    - `…net_beta.equity_down` 变成主体 `equity_down`、度量 `portfolio.integration.net_beta`（mini Q08 seq24、Q16 seq4）；
    - `portfolio.reconcile.sum_of_position_contributions` 变成主体 `reconcile`、度量 `portfolio.sum_of_position_contributions`（sol Q18 seq6）。
  - 向量条目的标签被铸成主体：`vector(entries={USO: XOM 的 beta})` 的主体是 USO（mini Q02）。
- **min/max 不带窗口，`as_of` 为 null。**如 `cash_conversion_cycle.min` = −75.83（mini Q09）。
- **`place` 在 20 条异类限额检查里排名，并列时顺序随意。**
  - 20 条混着毛敞口、行业、日亏损和各发行人。9 家同为 15.0% 的预警档，排名却是第 9 到第 17（mini Q11 seq4、Q15 seq11）。
  - 本轮没有直接造成错话，但 `HOW_TO_CITE` 要求最高级以 `place` 为据。
- **段落抽取。**标签与数字粘在一起（sol Q05 `Accessories7,901`）；切块从句子中间开始（sol Q10）。
- **搜索额度在一轮内共用，只有 5 次。**mini Q17、sol Q17 都用尽。

## 4. 工具的返回让模型读错了吗：逐条

### 4.1 到了读者面前的 17 条假陈述

| 案 | 模型写了什么 | 当时读到的工具原文 | 判断 |
|---|---|---|---|
| mini Q08（两条） | 「exposure … is -86.0%, so the book is short that proxy」「materially short」 | 图形 `portfolio.integration.net_beta.equity_down` = `-86.0%`，单位 RATIO；语言页 `key= portfolio.integration.net_beta.<risk>`；skill「TLT and HYG enter with the sign opposite」 | **说明写错，诱导读错。**按 skill 的说法，SPY 不反号，−86% 就是净空头；实际上 SPY 也反号，这个数表示净多头。sol 同一数字只写「integrated net equity sensitivity −86.0%」，没有判断方向 |
| mini Q08 | 「the prior run's exposure is also -86.0% [f_1318e759a4f9]」 | seq24、seq29 都只显示 `analysis_latest` 的 31 个图形；点名的 `prev_exposure` 被扣下；两条提示只列 calc id | **工具没交付，提示不可读。**分析师从没拿到过 −0.857。它引用的 id 在 `node` 字段里写明是 `analysis_latest`，挪作上一期是它自己的错 |
| mini Q16（两条） | 「latest and prior readings are identical … the change is zero」 | seq4：`net_beta_latest`、`net_beta_prev`、`change_net_beta` 全被扣下，只显示一个 −86.0%；seq10 同样。它的 w3、w4 给最新和上一期引用了同一个 id `f_088d1d4d7afe`；caveat 写着「The prior-run net beta matches the latest run in the ledger」 | **工具没交付，提示不可读。**sol 同样被扣时如实写了「withheld」，再由主分析师改派小程序拿到 −0.857 |
| mini Q11 | 「ranked by smallest room left to warning as LLY, MSFT, AAPL, JPM」 | seq4 显示了各家当前值和预警档（LLY 的预警档 12.0% 可见），余量被截、排序被扣；seq7 只有 10 个权重；seq13 是 0 个图形加一条只列权重的扣下提示 | **工具没交付；模型心算排错。**手里的数足够算出 MSFT −1.0、LLY −0.5、AAPL −0.2、JPM +0.2，它自己在 caveat 里写了「inferred from the displayed current and warning figures」 |
| mini Q15（三条） | 「AAPL, MSFT, JPM, LLY …」「AAPL … closest」「slowest are not the closest」 | seq11 同 Q11 seq4；seq14、19、22 都是 0 个图形，扣下提示只列 ADV | **工具没交付；模型排错。**它基本按当前值排，把各家预警档都当成 15%，也没管余量的正负（「AAPL has 0.2% room」，实际是 −0.195%） |
| mini Q09 | 「the three-year low of -75.83 … high of -56.36」 | `cash_conversion_cycle.min` = −75.83，`as_of: null`，没有窗口；同批序列 `spacing: annual`，`span: 2020-09-26..2025-09-27`（主分析师从 `shown` 读到的也是这些） | **身份不全，诱导读错。**极值没说自己跨哪段、落在哪天，主分析师套上了问题里的「三年」。上游：程序没加 `months: 3`，语言页也没写默认值 |
| mini Q01 | 「inventory is not growing faster than revenue across the same quarterly windows」 | 价差序列 7 个点都有显示，其中 3 个为正；答案自己也把这三个点列了出来 | **工具清楚，模型读错** |
| sol Q02 | 「FCF/debt: 254.0% … substantially exceeded debt」 | `fcf_to_debt` 为 843.1%、9209.8%、817.8%、619.9%、254.0%；旁边是「total_debt was not computed … none of its inputs () is filed」；`debt_to_ebitda` 为 0.01×–0.14×；说明分母只含短端的备注被 digest 丢掉 | **工具的值错，说明被丢，信号互相矛盾** |
| sol Q09（整张表） | 季度应收、存货、应付天数与现金周期 | 数值约放大 4 倍，结果里没有任何能看出问题的信号 | **工具的值错** |
| sol Q09（两条） | 「latest sequential deterioration」「inventory increase outweighed the payable benefit」 | 周期从 −215.58 到 −227.86；DIO +14.89，DPO +25.41，数值显示清楚 | **工具清楚，主分析师读错。**现金周期越负越好属于 skill 知识 |
| sol Q18 | 「does not reconcile … gap −0.85%」 | seq4：因子列被拒，合计 −0.00471605 只出现在拒绝原话里，重复 9 遍；语言页上 `book.reconcile` 的键没有因子合计；seq6 图形的主体是 `reconcile`、度量是 `portfolio.sum_of_position_contributions`，数值 0.38%，与组合收益相同 | **工具面诱导选错键。**分析师在 caveat 里写明「labeled sum of position contributions, although the requested identity calls for the sum of factor contributions」；主分析师照登 caveat，却仍下了「不对账」的结论，这一步是它的错 |
| sol Q04 | 「does not support calling the broader margin expansion mix-led」 | `read_report` 对被拒报告只返回问题代码；E10 只带最后一次提交，w1 没到主分析师手里 | **不是读错。**信息在门和交接环节丢了（E） |

### 4.2 没出答案的题与没交付的项中，工具的份

- **mini Q02（主分析师写错）**
  - E10 里 `asked` 是「Give the book's beta to USO.」，`finding` 是「XOM's beta to USO is 0.33×」，两者并排，所以**工具清楚**。
  - 但桌子上其实有账簿对 USO 的腿（β −0.0074），因共线被扣着不能单独引用；工具面和 skill 都没提到这条腿，分析师也没去问。
- **mini Q07、Q08、Q12**：排序程序被 §3.6 的嵌套缺陷挡住。归因文档把这几次记作 B，应改为 C（见 §5）。
- **mini Q13**：`no_sector` 挡住了买入腿（C），而这条拒绝本身被扣下（§3.1b），节点种类也看不到。
  - 分析师把只卖不买的书里 TLT 被动上升的 6.14% 读成「买入已反映」，主分析师照写「After selling half … and moving the proceeds into TLT」。
  - **这是工具诱导的读错。**它没到读者面前，是因为门误报挡住了这句，随后代码崩溃。
- **sol Q13**：买入腿同样因 `no_sector` 被拒，拒绝被扣了 4 次（§3.1b）；分析师改写成 `method(book.buy)` 后，撞上一条没有字段细节的参数拒绝（§3.5d）；限额分析师又被扣下 3 次（§3.1）。
  - 主分析师最后写对了「appears to reflect only the sale leg」，死于门误报。
- **mini Q18**：因子合计只在散文里出现（§3.7），另有门误报。
- **mini Q04、Q14、Q19、Q20**：`section_not_found` 只有错误代码。
- **sol Q14**：峰谷日期不显示（§3.5c）。
- **mini Q01 余量、mini Q19 AMZN 贡献**：先登记后被吞掉（§3.2）。
- **sol Q11、Q15、Q16 多派的轮次**：§3.1。
- **sol Q10 的 5 次空调用**：流量类方法不认 `at`（§3.9），加上合并不留痕迹（§3.4）。

## 5. 对 `ATTRIBUTION_V37C.md` 的更正

1. **§6「缺陷一」的根不是截断顺序，而是 `return` 根本不起作用**（§3.1）。修法应是「显示按 `return` 裁剪」，而不只是「点名的排前面」。
2. **mini Q07、Q08、Q12 的类型错大多不是 B。**
   - Q07 seq4、10、13，Q08 seq4、8、13，Q12 seq10 都是 entries 嵌套不求值，加上误导性的拒绝原话（§3.6），应记 C。
   - 仍是 B 的：Q07 seq7、seq15（对标量用 `latest`），Q08 seq13（引用了上一个程序的绑定）。
   - 相应地，§2 mini Q07 的上游与 §4 的 Q07、Q08 两行，都应改为「C（嵌套不求值），B 为次因」。
3. **mini Q08 的「净空头」（D）不是说明「没交代」符号，而是说明写错了。**skill 和语言页都说只有 TLT、HYG 反号，所以这是被诱导的 D，上游是 skill 文字错误加上工具的单位与命名。
4. **sol Q18 的 B 是被工具面诱导的**：键列表缺因子合计，拒绝原话把合计藏在散文里。上游记 C。
5. **sol Q02 补一句**：V37/S1 加的「分母组成」备注被 digest 丢掉，分析师看不到。
6. **sol Q14**：峰谷日期不是「分析师没用解释事实的窗口」，而是 digest 根本不显示字面量节点的值（§3.5c）。
7. **§4 表中 mini Q14「窗口内的申报」（B）**：`section_not_found` 不给任何线索，这一条应加记 C。
8. **两轮 Q13。**
   - 归因文档写的「C：买入 TLT 被拒」没错，但默认分析师看到了这条拒绝。实际上两轮都没看到（§3.1b）。
   - mini 的「只含卖出腿的情景写成卖出并买入之后」（D）是被工具诱导的：拒绝被扣下、节点种类不显示，只卖不买的书里 TLT 又被动升到 6.14%。
   - sol 的上游应改为「C（`no_sector` 且拒绝被扣下），B（`method(book.buy)` 参数不合）为次因」。
9. **sol Q10**：多出的 5 次调用源于流量类方法不认 `at`（§3.9），这一条应记 C，不是分析师的问题。

## 6. 修法方向：先说工作还给谁，再说代码

以下只列方向，没有实施。

- **还给 tool：执行 LLM 写下的意图。**
  - 显示按 `return` 裁剪；
  - entries 里的嵌套照常求值；
  - `book.reconcile` 列全键；
  - 窗口收益只留一个入口；
  - 写明 `months` 的默认值，返回点数少于所要时明说；
  - 补上毛利的第二条路径；
  - 已持有的名字可以在情景里加仓。
- **还给 tool：输出要么完整、要么拒绝。**
  - 拒绝不进上限，永远显示；`nodes` 带上种类；
  - `seen` 只登记真正显示了的图形；
  - 被合并的读数写明「已作为 f_… 显示过」；
  - 扣下提示按节点名列出；
  - 节点备注（分母组成、被拒条目、字面量值）进 digest；
  - 参数错误逐字段显示，类型问题全部显示；
  - `section_not_found` 列出可读的 Item；
  - 共线合计作为可引用的事实给出。
- **还给 tool：身份与数值正确。**
  - 天数和存量/流量比率按窗口换算；
  - `at` 同时移动流量窗口，做不到就拒绝，不静默返回最新一期；
  - 分母不全时拒绝出比率；
  - 净 beta 用 MULTIPLE 单位，并带上符号的含义；
  - `pick` 不拆方法产出的键；
  - 向量标签不铸成主体；
  - 极值带窗口和日期；
  - `place` 只在同类条目里排名，并列时名次相同；
  - `mul`、`scale` 不接受单边字面量。
- **还给 skill：知识写对。**
  - 「SPY/QQQ/IWM 在 equity_down 上同样反号，净 beta 为负表示风险发生时账簿亏钱」；
  - 现金周期越负越好；
  - 账簿的因子里有 USO、GLD，但共线、不能单独引用。

**七层落点**：

- §3.1–§3.5 落在 tool 层：registry、fact_adapters、digest。
- §3.6 落在 service 层（程序语言的解析与类型检查），语言页的文字在 tool 层。
- §3.8、§3.9 的数值与身份问题落在 service 层：`formula_service`、`typed_calculator`、`integration`、`scenario_service`。
- 正负号说明落在 skill 层。

这些修法的效果都在 LLM 层：分析师看得到自己点名的数，不必在空白处断言，也不会被写错的说明带偏。

## 7. 复现

```bash
SP=docs/spikes/v37/tools
.venv/bin/python $SP/replay_read.py exposure_battery docs/spikes/v37/V37C.json mini /tmp/reads          # 每次读入全文 + 每条事实的去向
.venv/bin/python $SP/replay_read.py exposure_battery_sol docs/spikes/v37/V37C_sol.json sol /tmp/reads
.venv/bin/python $SP/validate_replay.py exposure_battery docs/spikes/v37/V37C.json /tmp/reads/mini_rows.json   # 与记录的 read.chars 对照
.venv/bin/python $SP/return_share.py exposure_battery docs/spikes/v37/V37C.json /tmp/reads/mini_rows.json mini # §3.1 的表
.venv/bin/python $SP/notice_check.py exposure_battery docs/spikes/v37/V37C.json /tmp/reads/mini_rows.json mini # §3.3
.venv/bin/python $SP/hidden_refusals.py exposure_battery docs/spikes/v37/V37C.json /tmp/reads/mini_rows.json mini # §3.1b
```

sol 轮把库换成 `exposure_battery_sol`、round 文件换成 `V37C_sol.json`、标签换成 `sol` 即可。§3.6 的类型检查结论可以离线复现：对每次类型拒绝，把记录下的 `args.program` 交给 `program_service.typecheck`，看 `got` 字段。

事实去向的标签：

| 标签 | 含义 |
|---|---|
| `SHOWN` | 已显示 |
| `TWIN_SHOWN` | 本次调用里合并进另一个已显示的图形 |
| `SEEN_SHOWN_EARLIER` | 早先显示过，按设计合并 |
| `HELD_TOOL_CAP` | 被工具上限扣下 |
| `CUT_FIT` | 被 digest 的 fit 截掉 |
| `SWALLOWED_NEVER_SHOWN` | 早先登记为已显示，但其实从没显示过 |
| `SWALLOWED_TWIN_CUT` | 合并进的那个图形被截掉了 |
| `CUT_DUMP` | 渲染后被 `dumps_capped` 截掉 |
| `NOT_RENDERED` | 不是数值或序列，也没出现在读入里（本轮都是被 `dumps_capped` 截掉的拒绝） |
