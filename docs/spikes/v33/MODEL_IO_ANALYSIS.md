# 模型的输入输出原文，以及它们为什么引发问题（2026-09-13）

对象：V33 两轮 20 题。层级：信息架构，不是字段。问题是三个：模型被告知了什么，缺了什么，写出的东西为什么容易错。
原文来源：`trace/tools_schema_meta_face.json`（工具面）、`trace/Q*.md` §0（系统提示与推送文本）、`trace/model_io_samples/`（在 fixture 上重新生成的 describe 与 run 返回，与当时同一函数）。

## 0. 模型一轮开始时读到的东西，按体量

| 段 | tokens | 内容性质 |
|---|---|---|
| 系统提示 | 500 | 一半是角色，一半是回答语法 |
| 8 个工具的 description+schema | 3679 | `run` 占 1604，几乎全是名字表；`respond` 占 658，是 11 种关系的散文定义 |
| 推送的领域知识 | 平均 871 | 该 domain 的比较方式、收口方式、缺失声明，以及 1–2 个带占位符的现成 program |
| 用户问题 | 56 | |
| **合计** | **≈4.5k** | 与 `llm_call` 第一行实测 4.2–4.8k 一致 |

之后每个工具返回加 2–7k；到 respond 时 12–28k，最高 51k（Q02）。增量几乎全是 facts 表格。

## 1. 输入：模型被告知什么

### 1.1 系统提示：告诉它"怎么说"，不告诉它"怎么算"

500 tokens 里与分析有关的只有开头两句。其余是：

> Figures come from ONE tool: run(program). Write the whole computation as one program … every node comes back typed, dated and on the ledger as a fact (f_…). A superlative rests on a rank node; a change on yoy/qoq or two readings … A node that refuses says why; fix the program, do not guess.
> The answer is CLAIMS and PROSE (respond). Each figure you state is a claim with a relation its facts must fit — level, change, ratio, rank, room, absent, quote, series, table — and the prose writes {cN} where the figure goes. Write {cN} in the prose where claim cN's figure goes … A number you write out yourself is accepted only when the ledger accounts for it …
> Finish every turn by calling respond. If respond refuses, it names the claim or the number and the reason: fix that claim, run the program that produces the figure, or drop it.

三个后果直接对应实测：

- "Figures come from ONE tool"与"what the filings cannot hold is search_web"并列，模型在 Q17 把 `search_web` 写进 program 当原语，被拒 `unknown_primitive`，随后告诉读者"the web-search tool is not available here"。系统提示没有区分**工具**与**原语**。
- "fix that claim … or drop it"给了三条出路，没有第四条"这个问题 desk 表达不了"。Q11 的 8% 上限、Q06 的一年前、Q17 的十日窗口都是表达不了的，模型只能在三条里选：Q11 选了 drop（白卷），Q06 选了换问题（30d vs 252d 窗口），Q17 选了编 id。
- "A number you write out yourself is accepted only when the ledger accounts for it"把数字赶出散文。模型学到的是：所有数值位置都写 `{cN}`。它对 series 也这么做，于是 39 处 "the chart below"。

### 1.2 工具面：schema 几乎不约束，约束全在散文里

`run` 的 JSON schema 对 program 的约束只有：

```json
"let": {"type":"array","minItems":1,"maxItems":60,"items":{"type":["array","object"],"description":"[name, expression]"}}
```

其它一切——原语名、参数名、哪个参数收什么类型、字面量能不能做操作数、vector 要什么——都在 1604 tokens 的 description 里以名字表的形式出现：

> Arithmetic add/sub/mul/div(a, b) (vector∘scalar broadcasts, vector∘vector aligns by label), scale(of, factor); … vector(entries={label:$scalar}) …
> price methods (subject: ticker or [tickers]): price.volatility(window_days), price.beta(benchmark,window) key=beta|alpha|r_squared, price.momentum_12_1, price.distance_from_52w_high, …

它没说的：`sub` 的 `b` 不能是数字（只能是绑定或 id）；`vector` 的 entry 不能是 series（`last_n` 的结果）；`pick` 出来的日期没有 id；价格方法没有 as-of；`issuer.panel` 的返回 `run` 不会定型。这些全是**类型规则**，全在执行期以拒绝的形式第一次出现。

schema 宽松的直接证据：模型在 B 轮写 program 用了三种 `let` 项写法，parser 全部接受：

| 写法 | 次数 |
|---|---|
| `[name, expr]`（schema 描述的那种） | 30 |
| `{"name":…, "expr":…}` | 74 |
| `{"name":…, "expression":…}` | 156 |

宽松本身不是错，但它说明 schema 没有在教模型任何东西——模型是从推送示例和拒绝里学语法的。

`respond` 的 schema 同样：`relation` 是 11 个枚举值，`of`/`against`/`rows`/`span` 全是可选字符串。每种关系对 fact 的要求（change 要同 measure 同 subject 不同期；room 的 against 要是同一档的 tier；rank 要 params 里有 rank）只在 658 tokens 的 description 里以半句话出现。**门检查的是类型化的关系约束，模型读到的是散文。**

### 1.3 推送的领域知识：模型真正复制的是示例 program

以 Q08 为例，推送了 `issuer_capital_allocation` 与 `book_composition` 两个 domain，各含比较方式、收口方式、"absent here"一句，以及现成 program：

```
program — is capex outrunning revenue:
{"let":[["capex",{"fn":"fundamentals","ticker":"<T>","metric":"capex","months":12,"last_n":5}], …
        ["intensity",{"fn":"method","name":"capex_intensity","subject":"<T>","params":{"last_n":5}}]]}
```

模型确实照着写了 `method(capex_intensity, last_n=3)`。但示例里没有一个是**跨发行人排序**的形状，模型自己拼了 `rank(vector{…series…})`，被拒。20 题全是组合题，推送的是单 domain 的标准形；组合处正是模型自己发挥、也正是出错的地方。

推送是按用户问题的词面匹配选的（`skill.match_domains`）。Q15 问流动性，推送的是 `issuer_business_risk_from_filings` + `book_liquidity`；Q17 问事件，推送 `issuer_price_context` 之外没有 `book_events`。匹配是词袋，不是意图。

### 1.4 describe：是地图，但地图上有几处标错

模型几乎每轮先调 `describe()`，读到 14.6k 字符：7 个 portfolio、已准备的 issuer、5 个数据域、14 个 procedure 的问题与触发句、5 条 desk_rules、not_held/cannot 各几条（各带一个 absence fact id）。再调 `describe(port, expand=<domain>)` 读到 6–10k 字符：该 domain 的 evidence/compare/close 句子、方法列表（含 `call` 示例、`params` 名字、`yields`、`fails_when`）。

对判断有影响的三处：

- **`issuers_prepared` 列的是"已登记"不是"已就绪"**。B 轮中 Q04/Q12 的 `start(readiness)` 立刻把 MRK/BAC/GS 写进 companies 表，之后并发的 Q14/Q16 读到的根目录就把它们列为 prepared，program 里带上了它们，各自被拒"no price history"。这是测量的一处交叉污染，也是产品信息缺陷。
- **方法的 `params` 只有名字，没有类型和取值**：`"params": ["months","at","last_n"]`。模型看不到 `at` 要 YYYY-MM-DD（Q07 写了 `"prev"`），看不到 `price.distance_from_52w_high` 的 params 为空所以"一年前"不可问（Q06）。
- **`describe(ticker, expand='methods')` 返回 `methods: {}`**（重新生成确认）。方法视图是空的；方法信息只在不带 expand 的 issuer 描述里（10.6k 字符）。

### 1.5 工具返回：facts 表 + note；模型要用的 id 埋在表格里

每个返回是两半：`facts` 块——列声明一次，一行一个图形，模型形态的值已取到读者精度；`note`——原 payload 里每个数字换成 fact id。以 Q14 的 program 为例，模型读到的 note 里 `peak` 节点是：

```json
"peak": {"kind": "table", "deps": ["episodes"], "entries": {}, "literal": "2026-01-07"}
```

日期在这里，**有值、无 id**。模型看见了、写进了散文、被门拒了"a number the ledger cannot account for"，四轮后把 depth 的 id 填进日期槽。desk 给模型看了一个它不允许模型复述的东西。

facts 行的身份列是 `subject / measure / unit / as_of / window / params`。三处对本轮问题不够用：

- `column(run, issuer_exposures, weight)` 的 fact 只有 `subject=ticker`，**没有 sector**。"our five technology holdings"（Q07）在这些 fact 上判断不出来；sector 只在 `read_book(port, ['positions'])` 里（重生成确认：GOOGL 标为 Communication_Services，AMZN 为 Consumer_Discretionary），两轮都没读它。A 轮按权重取前五把 JPM/LLY 叫做 tech，B 轮按常识取了五家大科技。
- scenario 产出的量与 run 产出的同一量**命名不同**（`sector_exposures.Technology.weight`/subject=calc 与 `sector_exposures.weight`/subject=Technology），门用这两个字段判"同一 measure"，正确的 change 被拒（Q13 第 5 次）。
- `book.explain_episode` 的 facts 不带 window，所以起点日期不在任何 fact 的身份里，`resolve_identity` 找不到它。

被 cap 截掉的图形（`held_back`）只以 `{"count", "measures": [...]}` 出现，**没有 id、不上账本**。Q13 三次 run 各 83 个 facts 加 held_back，模型随后写 `f_held_beta`、`f_held_stress`——它知道有东西被截掉了，以为那些东西有 id。

## 2. 缺的关键输入，归类

| 缺什么 | 后果 | 实例 |
|---|---|---|
| **类型规则**：哪些位置收什么 | 意图正确的 program 在执行期被拒，拒绝只说"不是 X"不说"怎么变成 X" | Q08 vector 收不了 series；Q11 sub 收不了 0.08；Q07 `at:"prev"` 崩溃 |
| **可表达性边界**：desk 做不了什么 | 模型在"改问题 / 编 id / 放弃"里选，且不告诉读者问题被改了 | Q06 一年前→252d 窗口；Q17 十日→一个月；Q11 8% 上限→白卷 |
| **图形的身份维度** | 需要按身份判断（属于哪个 sector、是不是同一量、哪个窗口）时无从判断 | Q07 tech 五家；Q13 run vs scenario 同名不同写；Q14 无 window |
| **可引用性**：显示给模型的值哪些有 id | 模型复述了 desk 给它看的东西，被门拒 | Q14 日期；Q13 held_back |
| **工具 vs 原语** | 把工具写进 program，再对读者说工具不存在 | Q17 |
| **每个 subject 的拒绝明细** | 一句 "no subject produced a figure" 覆盖五家公司各自的原因 | Q07 issuer.panel |
| **方法的返回能否被 run 定型** | 注册表里有、describe 里公告、run 里永远 untyped | Q07 issuer.panel |

## 3. 输出：两种结构化产物为什么招错

### 3.1 program：语言宽松，类型严格，错误在执行期爆出

模型写的是一个小语言：绑定名、原语、`$name`、字面量、嵌套表达式。它没有类型标注，也没有编译期检查——除了参数名的存在性（`type_mismatch: fn takes …; missing …`），所有类型错误都在执行到那个节点时才出现，并且沿依赖链把后续节点全部变成 absence。一个 program 十几个节点，模型一次只能修一个错。B 轮 36 次 run 里，只有 Q15、Q18 一次写对；Q13、Q11 各写了 3 次。

字面量在语言里的地位不一致：`scale(of, factor=0.25)` 收数字；`sub(a, b=0.08)` 不收；`vector(entries={A: 0.08})` 不收；`params: {"peak": "$peak"}` 收字面量节点。模型无法从任何输入推出这张表。

### 3.2 respond：两处手工维护的对应关系，加一条把数字赶出散文的规则

模型要同时维护两张表：`claims[i].id ↔ prose 里的 {cN}`，以及 `claims[i].of ↔ 账本上的 f_id`。两张表都靠模型抄写。Q17 第三次 respond 删掉了 5 个被拒的 absent claim，编号整体前移，散文没动，十个数字全挂到错的公司上，门看不见——因为门只看 `{cN}` 指向的 fact 的 kind，不看 `{cN}` 旁边的公司名。Q18 把 alpha_plus_residual 的 id 填给了 "factor share {c4}"，真正的 factor_share 声明了却没放进散文，规则是"未放置的 claim 不拒绝"，它静默消失。

PROSE_RULE 的效果是把一切数值位置写成占位符。对 scalar 这是设计意图；对 series，占位符渲染成 "the chart below"，落在 "was / is / from / above" 之后。Q01 第一次用 table 放 series 被拒（格子须是 scalar），改成 inline series 通过——门的三条出路里没有一条能让 series 的值出现在句子里。

`absent` claim 的渲染是 absence fact 的原文，即 `_absence_text` 产生的内部诊断句（"aws was not computed — metric_not_filed: AMZN has no filed facts under 'revenue_including_assessed_tax'"）。模型被要求"以 claim 说 absence"，读者读到的是节点名和错误码。

### 3.3 门的拒绝作为输入：告诉规则，不告诉修法；一次只说一类

拒绝的形状是 `{error, problems[{at, reason, detail}], detail}`。三个特点决定了模型的反应模式：

- **一次只报最先命中的一类**（G1 → G2 → G3 顺序返回）。Q14 前两次因 absent 指向 passage 被拒，第三次修好后才因日期被拒，第四次才通过——四轮修一个答案。
- **说规则不说路径**："a number the ledger cannot account for: state it through a claim, quote the passage that says it, or drop it"——当那个数字是 desk 自己算出来显示给模型的日期时，三条路径都走不通。
- **refused_not_absent 说 "fix the call and run it again"**——当问题在语言里不可表达时（Q11 的 8%），这句话让模型重复 run 三次。

模型对拒绝的四种反应，按频次：换关系声明（不动散文）、删 claim（不动散文）、编 id、原样重发。四种里没有一种是"重新做分析"。`repeats.STOP=2` 只拦完全相同的载荷，前三种都绕过它。

## 4. 一句话

**模型读到的是一张名字表加一套说话规则，没读到类型规则、表达边界和图形的身份维度；它写出的是一门无类型的小语言和一份靠序号手工对齐的双表；门只在执行期和出口处逐类退回，退回的话告诉它规则而不告诉它路径。**按四角色：validation 与 tool 之间缺一层"语言的类型与边界"，这一层今天由拒绝循环代替，代价是每题平均 8 次 completion、68% 的 respond 被拒、以及四次被门改坏的答案。LLM 自身的错误——读反序列、0.25、选错 key、编 id——在这套输入下都是可预期的行为，不是异常。
