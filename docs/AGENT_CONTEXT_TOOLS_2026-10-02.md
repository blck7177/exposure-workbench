# Exposure Workbench：一个 agent + 它该拿到的 context + 它能用的 tools

日期：2026-10-02 · 基线：`codex/simplify-agent-loop-s2` @ `6574718` · 状态：分析稿。没有改代码。简化后的设计还没有实跑；现有架构在一道题上实跑了两次，证据并在第 6 节。

依据：只读源码，加上用仓库自己的纯函数做的离线渲染和校验（不连数据库、不发网络请求）。第 6 节里标"实跑"的条目来自现有架构在夹具库上的两次实跑，每次模型请求和每次工具调用都留了原样记录。脚本和产物在 `docs/spikes/agent_context_tools/`，第 9 节有复现方法。

## 1. 命题

我们已经有一套基础工具。剩下的事，是让模型把它们组合起来取数、做分析。所以需要的只有三样：agent、agent 该拿到的 context、agent 能用的 tools。只要 agent 理解四件事，问题就解决了：

- 自己能干吗
- 怎么干
- 资源都在哪儿
- 自己在干嘛

这份稿子按这个命题把聊天路径重新画一遍。有两件事先放下不谈：validation（答案怎么核对），以及调用次数和轮次的上限。

## 2. 结论

命题大体成立。

1. **四件事需要的材料，代码里都已经有了。** 现在它们被分给四个 agent（一个主分析师、三个分析师），每个只拿到一部分，中间靠派单、交接、状态投影这一套机制搬运。
2. **交给一个 agent 之后，context 可以用现有材料拼出来。** 新写的文字只有角色一段。工具层的逻辑不用改：现有的 `meta` 挂载本来就提供全部 11 个动词。第一次 completion 的 prompt 约 14.7k token：比主分析师单独一轮的 8.9k 大，和"主分析师加一个分析师任务"的 13.5k–17.6k 在同一量级。
3. **离线验证的结果是"信息够用"。** 14 道题的参考路径共 60 次调用，全部通过工具自己的 schema 和形状规则。7 个只看得到这份 context 的盲读者为这 14 道题写了 71 次调用，71 次也全部通过这两层检查；其中 1 次会在运行时因为行标签写错被拒（见 6.1）。每道题都找到了走得通的路径，两道"桌子做不了"的题也都从手册里读出了边界。
4. **理解之后还剩的问题分三类**：context、tool、skill，第 6 节逐条列出。证据有两个来源：盲测，和现有架构上的两次实跑。属于 tool 和 skill 的那些，在现在的设计里同样存在：工具、描述和手册是同一份。
5. **模型本身拿着这份 context 做得怎么样，离线回答不了。** 盲读者是 Claude，线上默认是 gpt-5.4-mini。两次实跑跑的是现有架构，不是这份 context。要实跑。

## 3. 现在这四件事各在谁手里

"主分析师"是和用户对话的那个 agent。"分析师"是它派单的三个 agent，各管一族资源：issuer（申报）、market（行情）、risk（组合）。

| 要理解的 | 主分析师拿到的 | 分析师拿到的 |
|---|---|---|
| 能干吗 | 自己能调 6 个动词。另外 5 个（检索申报文本的两个、网页搜索、交易情景、后台准备）被 token 里的 deny 列表拿掉，只能通过 `ask` 让分析师做。分析师能做什么，它只从 roster 的散文里知道 | 自己那一族的 5–8 个动词和度量。别的族的动词和度量名在它的工具列表里不存在 |
| 怎么干 | `metric` 的 schema 里有全部 45 个度量名。讲这些度量怎么读、拿什么比什么的手册章节不常驻，要 `open("handbook:…")` 才拿到。另外要背协议：派单怎么写、八条引用规则、被拒后怎么修 | 自己那一章手册，八条引用规则，`submit` 的格式 |
| 资源在哪 | 桌面目录（DESK 块），但每家公司"哪些科目中断、哪些度量算不了、哪些 Item 有索引"那一段被去掉了；`list` | 只有本任务主体的那一段目录；`list` |
| 自己在干嘛 | 用户原话和对话在它这里。取数过程在分析师那里，回来的是一张回执，内容靠 runtime 拼的 STATE 块转述 | 主分析师改写过的任务行，加用户原话。看不到对话历史，看不到别的分析师的结果 |

没有一个 agent 同时拿到四样。`ask`、`submit`、STATE、`input_refs` 做的全部事情，就是在它们之间搬东西，约 2,100 行代码。

当初分成三个分析师，换来的是"够不着的动词根本不存在"：行情分析师的工具列表里没有申报动词，不需要靠一句话去禁止。代价是上面这套搬运。

这个分支已经走了一半：主分析师现在能直接调 6 个动词。差的是另外 5 个动词、常驻的手册、完整的桌面目录。

## 4. 简化后的设计

### 4.1 agent：一个循环

```text
messages = [角色, 手册, 桌面目录] + 对话历史（最后一条是这次的问题）
重复:
    把 messages 和 11 个工具交给模型
    模型调了工具 → 逐个执行，把返回的行接到 messages 后面
    模型写了文字 → 这就是答案，结束
```

循环里没有派单，没有交接，没有 STATE，没有门，没有计数器。它这一轮的全部调用和返回都在 messages 里，这就是它的"自己在干嘛"。

答案原样存进对话历史，模型写下的行 id 留在里面，下一轮可以直接指回上一轮的行。现在存的是去掉 id 的文本。

实现量：新增一个循环文件，约 120–150 行。连工具服务用现有的 `tool_session("meta", …)`，不带 deny 列表。每次 completion 和每次工具调用照旧记 trace，工具返回的行照旧进会话账本。这两样在 `llm_session` 和工具层里，不在被拿掉的部分里。

### 4.2 tools：现有的 11 个动词，逻辑不改

| 动词 | 做什么 |
|---|---|
| `list` | 桌子上有什么：名字和日期，不返回数字 |
| `filings_read` | 一条申报科目 × 一个期间，可以一次读多家 |
| `filings_search`、`filings_section` | 在申报文本里检索段落；读某个 Item 的原文 |
| `web_search` | 申报里没有的东西 |
| `prices_read` | 一个价格字段：一段窗口的序列，或某一天的读数 |
| `book_read` | 组合某张表上的数字 |
| `scenario` | 一笔交易之后的组合，得到一本新的组合 |
| `metric` | 按名字取一个度量，共 45 个 |
| `calc` | 对已经拿到的行做一步运算，共 19 种 |
| `start` | 启动后台准备，只返回 id |

### 4.3 context：四块对四件事

| 要理解的 | context 里对应的东西 | 来源（都已有） | 大小 |
|---|---|---|---|
| 自己在干嘛 | 角色的第一段；用户问题和对话；这一轮自己的调用与返回 | 新写一段；`agent_messages`；循环本身 | 角色整段 512 token |
| 能干吗 | 11 个工具的 schema；角色里一张"哪类资源用哪个动词"的小表，由实际挂载的工具生成；手册每章的 "Absent here" 和政策 | `tools/primitives.py`、`analytics/handbook.py` | schema 6,321 token |
| 怎么干 | 手册三章：能问什么、哪些度量回答它、每个度量是什么、怎么读、拿什么比什么 | `handbook.chapter_text` 三章，政策只说一次 | 7,239 token |
| 资源在哪 | 桌面目录（DESK）：桌上有哪些公司；用户的组合，含 id、最近两次 run、持仓和行业、定义了哪些检查；题目点名的公司，含申报和行情的日期、哪些科目中断、哪些度量算不了。其余用 `list` 查 | `briefing.for_question` 的完整输出 | 276–670 token，随题目变 |

合计：第一次 completion 的 prompt 是 14.5k–14.9k token。

对照现在：主分析师每次 completion 固定 8.9k，不含 DESK、STATE 和历史。每派一个分析师任务，那个分析师每次 completion 再固定 4.6k（market）、6.4k（risk）或 8.7k（issuer）。所以主分析师自己直接取数的题，现在更省；只要派出一个任务，两边相加就是 13.5k–17.6k。

模型要背的协议也少了。现在是 `ask`、`open`、`repair_answer`、`submit` 四个 schema 共 1,284 token，八条引用规则 389 token，再加两段角色说明里讲协议的部分。简化后只剩"答案怎么写"一句。

### 4.4 新写的只有角色这一段

下面是离线验证时用的草稿，措辞待过目。"WHAT YOU CAN DO" 下面的动词表不是手写的，由实际挂载的工具生成：`start` 被拿掉时，那一行不会出现。

```text
You are the analyst of a portfolio risk & issuer-intelligence desk, and the one the user talks to.

WHAT YOU ARE DOING
Answering the user's question from the desk's own evidence. The analysis is yours: take the question apart, decide what has to be known to answer it, get it with your tools, and say what it shows and what it means for the question asked. Keep the question in view as you work. You are done when you can answer it, or can say exactly what the desk does not hold.

WHAT YOU CAN DO
Your tools are verbs over the desk's resources; each says what it does and what it takes.
- see what the desk holds: list
- an issuer's filed figures: filings_read
- the text of its filings: filings_search, filings_section
- what the filings cannot hold: web_search
- a name's prices: prices_read
- the book's figures: book_read
- the book after a trade: scenario
- a measure, by name: metric
- one operation on rows you already have: calc
- background preparation: start
Every result is rows. A row carries its id (f_…), what it is, whose, over what period, the value, what it means and where it came from. A refusal is a row too, with its reason and the way out; it describes that one call and does not prove the question is unanswerable. Use tool arithmetic, not mental arithmetic.

HOW TO DO IT
The HANDBOOK block is the desk's method, one chapter per family of evidence: an issuer from its filings, a name from its prices, the book. For each it says what can be asked, which measures answer it, how each reads, what to set against what, and what the desk does not hold or does not say.

WHERE THE RESOURCES ARE
The DESK block is the desk's map for this question: the issuers it holds, the user's books with their runs and holdings, and how far each name's filings and prices reach. It carries names, dates and coverage, and no figure. `list` shows the rest: the measures, a name's filed lines, its filings and its price span, a book's tables, rows and checks.

YOUR ANSWER
Plain prose, to the user. Write a figure as its row shows it, with the row's id in brackets after it: 16.0% [f_2592baab170e].
```

另外两块各有一行标签，说明它是什么、怎么用：

```text
<handbook source="the desk's handbook" use="method — what a thing is, how it reads, what to set against what; it holds no figure">
<desk source="the desk's catalogue" trust="names, dates and coverage only — no figure here" use="find the subjects and what the desk holds for them; check the question's premises">
```

手册正文是现有三章的原文，只把章名从"某某分析师"换成资源族的名字，政策一节从三份并成一份。完整文本见 `docs/spikes/agent_context_tools/handbook.txt`，一道题的完整 prompt 见 `sample_prompt_Q09.txt`。

### 4.5 聊天路径里不再需要的

- 派单与交接：`agents/delegation.py`、`agents/handoff.py`、`agents/sub_analyst.py`，共 1,312 行。
- 状态投影与交付追踪：`services/analysis_state.py`、`agents/delivery.py`、`services/analyst_reports.py`、`agents/evidence_context.py`，共 828 行。
- 主分析师的 roster 和 readings 两个块：内容都在手册章节里。
- 三个分析师的挂载点：工具服务留 `meta` 一个就够。
- 现在的主循环 `agents/meta_agent.py`（690 行）换成 4.1 的循环。

研究简报是 worker 里跑的另一个循环，不受影响，这份稿子不讨论它。

## 5. 这份 context 够不够：两项离线验证

题目共 14 道：前端自带的 7 条建议问题，加上按手册自己列的问题类型出的 7 道（交易情景、流动性、波动率、杠杆、被扣住的度量、没准备过的公司、跨资源族）。原文在 `docs/spikes/agent_context_tools/questions.json`。

### 5.1 参考路径

我为每道题写了一条用这 11 个动词走通的路径，再逐条校验。校验器用的是工具自己的 schema，加上每个动词在读数据之前就执行的形状规则，比如"流量科目不能按某一天读""`scale` 只收一个输入"。10 个反例（该被拒的调用）全部被它拒掉。

| 题 | 路径 | 调用数 |
|---|---|---|
| Q01 What is my largest exposure right now? | `book_read` → `calc` → `book_read` | 3 |
| Q02 Why did the book move on the last run? | `metric` → `book_read` ×3 → `calc` | 5 |
| Q03 Which limits am I closest to breaching, and how much room is left on each? | `metric` → `calc` | 2 |
| Q04 Put MSFT, AAPL and GOOGL 2025 full-year net income side by side in a table. | `filings_read` | 1 |
| Q05 Add up AAPL's debt … then net the cash off so I have net debt. | `filings_read` → `calc` ×2 → `metric` | 4 |
| Q06 How has NVDA's revenue grown over the last four quarters? | `filings_read` → `calc` | 2 |
| Q07 Search the web for the latest news on LLY from the past week … | `web_search` | 1 |
| Q08 If I sold half of my largest position, what would the book look like and which checks would change? | `book_read` → `calc` → `scenario` → `book_read` ×3 | 6 |
| Q09 How many days would it take to sell each of my holdings if I traded 20% of its average daily volume? | `book_read` → `metric` → `calc` ×10 → `calc` ×10 → `calc` | 23 |
| Q10 Has MSFT become more volatile lately, or is it just the market? | `metric` ×2 → `calc` ×2 | 4 |
| Q11 Is JPM more levered than it was a year ago? | `metric` → `calc` | 2 |
| Q12 What is the book's value at risk, and how much would it lose in a stress scenario? | `metric` → `book_read`，并说明这两项被扣住 | 2 |
| Q13 How does TSLA's net margin compare with AAPL's over the last fiscal year? | `metric` → `start` | 2 |
| Q14 Which of my holdings has the weakest 12-1 momentum, and how big is it in the book? | `metric` → `calc` → `book_read` | 3 |

14 道题共 60 次调用，全部通过。13 道题在 6 次以内。Q09 要 23 次，原因见 6.3。

### 5.2 盲测

方法：7 个新开的 agent，每个负责两道题。它只读得到这两道题的 prompt 文件，也就是简化后的 agent 在那一轮开头拿到的全部东西：角色、手册、DESK、11 个工具的 schema、用户问题。它看不到代码库。它写出自己会发的调用序列（逐字可发送的 JSON），并报告 context 里哪些地方让它不得不猜。写出的调用用 5.1 的同一个校验器检查。

结果：

- 14 份计划共写出 71 次调用，71 次全部通过校验器。重复的调用只写了一次，所以实际次数更多，比如 Q09 展开后和参考路径一样是 23 次。
- 校验器查不到需要数据的规则。对照代码，71 次里有 1 次会在运行时被拒：Q12 的读者把 DESK 里检查的显示名 "One-day loss" 填进了 `book_read` 的 `row`，而 `row` 要的是内部标签（见 6.1）。
- 13 道题的关键调用和参考路径一致或等价。Q04 的那一次调用除 `why` 外和参考路径逐字相同。Q12 两边都先说明这两项被扣住，再各自给了不同的相邻读数。
- 需要从 context 里读出边界的题都读出来了：
  - Q06：从 DESK 看出 NVDA 的 `revenue` 科目在 2022 年中断，改读 `total_revenues`。
  - Q11：从手册和 DESK 看出以债务和利息为基础的杠杆度量对银行不适用，改用 equity multiplier。
  - Q12：从手册看出 VaR 和压力结果被扣住，说明不会用别的数字重建。
  - Q13：从 DESK 看出 TSLA 不在桌上，先 `start`，再读 AAPL。
- 盲读者的路径普遍比参考路径长。它们照手册"compare and close"的要求，把相对上一次 run 的变化、排第二的名字、检查的档位都读了。比如 Q01 参考路径 3 次，盲读者写了 10 次。
- 4 道题的第一步是 `list`：两道为了找组合表的列名（见 6.1），一道为了看 `book.reconcile` 收什么参数，一道为了看有哪些检查。
- 14 份计划一共报告了 136 条不清楚的地方，第 6 节归类。

逐题的调用、校验结果和每条不清楚之处在 `docs/spikes/agent_context_tools/blind_scored.txt`。

### 5.3 这两项验证说明不了什么

- 盲读者是 Claude，线上默认是 gpt-5.4-mini。结果说明"信息够不够"，不说明"mini 模型做不做得到"。
- DESK 是合成的：形状照 `briefing.for_question`，持仓取自 demo 组合的种子文件，日期和各公司的覆盖情况是编的。
- 只验证到"调用成形"。没有真实返回，后续步骤里的行 id 是占位符。校验器不查需要数据才能判断的规则，比如某家公司有没有报这个科目。

## 6. 理解之后还剩什么

这一节的证据有两个来源。

**盲测**（5.2）针对简化后的 context。盲读者报告的 136 条里，有一部分是题目本身的歧义："exposure" 指什么、"一年前"以哪天为准、"2025 全年"是财年还是日历年。这类出现在 10 道题里，是 agent 该自己判断并在回答里说明的，不算缺口。

**两次实跑**针对现有架构（主分析师加三个分析师）。夹具库，同一道题各跑一次，一次 gpt-5.4-mini，一次 gpt-5.6-sol。题目同时要报表数据和组合数据：

> Rank our five technology holdings by cash conversion, operating cash flow over net income, for the trailing twelve months and by the change in that ratio against the prior twelve months. Which name has the weakest conversion, and is it also the one whose weight in the book grew most since the previous run?

两次运行里，主分析师的第一个请求逐字相同（只差 STATE 的 id），工具 schema 和分析师的 system 也相同，所以差别只来自模型。两次都是 0 推理 token：harness 走 chat completions 接口，这条路上 gpt-5.6 带工具只接受 `reasoning_effort="none"`。

| | gpt-5.4-mini | gpt-5.6-sol |
|---|---|---|
| 结果 | 没答出，只给了 AAPL 的权重 | 答出：三家的排名、变化、和权重的对照 |
| "五家科技股"这个前提 | 没核对，按五家派单 | 纠正为桌面上标 Technology 的三家 |
| 派单 | `ask` 被拒 3 次，最后 1 张 issuer 任务 | 没有被拒，issuer 和 risk 各 1 张 |
| issuer 分析师取的数 | accruals 两个度量 | 经营现金流、净利润两条申报科目 |
| issuer 分析师的 16 次调用 | 用完，没有算出比率 | 用完，没有算出比率，NVDA 还缺 3 行 |
| 交回 | 没交 | 交了 13 行和 2 条 note |
| 主分析师收尾 | 放弃，写"答不了" | 自己补 3 次读、11 次 `calc` |
| 模型请求 / 工具调用 | 13 / 23 | 18 / 42 |
| prompt token | 164k | 244k |

mini 掉进去、5.6 自己绕过去的，是模型能力的差别。换成 5.6 之后还在的，才算设计缺口：下面标"实跑"的条目都是这一类，每条都对到了代码或原样记录。每个模型只跑了一次，上表里模型行为的差别是单次观察。

5.6 那一轮的计算其实是主分析师自己做完的。两个分析师循环用了 121k prompt token，交回的是 9 行申报读数和 3 个权重差值。

实跑暴露的缺口里，有几条是派单结构自己带来的。合成一个 agent 之后它们随结构一起消失，下面逐条标出。

缺口归成三类：context（6.1）、tool（6.2 是描述没说清的，6.3 是做不到或输出不完整的）、skill（6.4）。盲测的条目我都对照代码核过；只来自读者报告、我没有在代码里逐一核实的，单独标出。

### 6.1 context 里缺的：补进 DESK 或角色就行

| 缺什么 | 表现 | 补法 |
|---|---|---|
| 组合各张表的列名 | `book_read` 的 `column` 是自由字符串。列名要调 `list(what="book")` 才看得到，而 `list` 的描述只说"tables and rows"。出现在 6 道题里。Q01 的读者不知道有 `weight_change` 这一列，改成读上一次 run 再相减。实跑后核实：这一列对持仓从来是空的（见 6.3），读上一次 run 再相减是现在唯一的路 | 这张表是静态的，6 张表约 250 token，直接放进 DESK |
| 检查的行标签 | DESK 里检查的名字是给人看的写法，如 "Issuer weight: AAPL"；`book_read` 的 `row` 要的是内部标签，如 `issuer_concentration:AAPL`。照 DESK 的写法填会被拒，拒绝里会列出可用的标签 | DESK 里的检查改用内部标签，或两个都给 |
| 一行是什么 | 角色说"a row carries … the value"，`book_read` 又说"one row across its columns"。读者不确定一行是一个数字还是一条多列记录，一条序列是一个 id 还是每个点一个。出现在 10 道题里。代码里一个数字就是一行，一条序列是一行 | 角色里说清：一行一个数字，各有自己的 id；一条序列是一行 |
| 当前日期 | 问"现在""过去一周"时，它只看得到数据的截止日。出现在 4 道题里 | DESK 加今天的日期 |
| 持仓的覆盖信息 | DESK 的公司条目只收题目里点名的公司。问"我的持仓……"时这一段是空的，持仓的行情和申报覆盖到哪天不在图上；SPY 这类因子工具有没有行情也不在图上。角色草稿里那句"how far each name's filings and prices reach"在这类题上说过头了。实跑印证，见下表第一行 | 组合进入 DESK 时，带上持仓各自的覆盖摘要 |
| 申报往回覆盖到哪年 | DESK 对每种表单只给最新一份的日期 | 加最早一份的日期 |
| 几张表和几项检查是什么 | `exposure_metrics`、`risk_alerts`、`count`、`trade` 四张表，"Gross exposure" 这项检查量什么，各项检查越线的方向，手册没有说。只来自读者报告 | 进手册组合一章的"桌子持有什么" |
| 答案格式 | 角色说 plain prose，Q04 的用户要表格。说"桌子没有这个"时该引用什么也没规定 | 和 validation 一起定 |

实跑（现有架构）看到的：

| 缺什么 | 两次实跑里的表现 | 简化后 |
|---|---|---|
| 任务主体的覆盖信息 | 两次运行里 issuer 分析师的 `<coverage>` 都是 `{}`。目录只为用户原话里点名的公司建条目（`services/briefing.py:61-67`），分析师那边按任务主体去查（`agents/sub_analyst.py:116`）；主体是主分析师从持仓里挑的，所以查不到。5.6 用 3 次 `list`（11.7k 字符）查出各家的最新期末，再自己推出一年前的期末。mini 一直不知道该问哪个日期 | 仍在。就是上表"持仓的覆盖信息"那一条，补法相同 |
| 调用上限 | 分析师的 system 里没有"16 次""被拒也算""`list` 不算"。5.6 一次发了 12 次读，当时只剩 9 次，NVDA 的四行只读到一行 | 上限接回来时才有，见第 7 节 |
| 分工边界 | 分析师拿到用户的整句问题，不知道哪一半归别人。mini 的 issuer 分析师 5 次去 `list` 仓位。5.6 的 issuer 分析师用 1 次调用读了仓位。5.6 的 risk 分析师去找现金转化的度量，交了一条"这张桌子排不了现金转化"的 note；这条没有数字，原样进了 STATE 的 findings | 消失：没有分工 |
| 没执行的调用 | STATE 的任务卡里 28 条操作全是 `returned`，被上限挡回的 3 次 NVDA 读不在里面。主分析师补读时，上一期的期末日期是它自己推的。另外 7 条 `delivery_missing` 和证据列表是同一批行 | 消失：没有 STATE，调用和返回都在 messages 里 |
| 上限用完后的提示 | 固定提示仍然说"或者继续读你还需要的行"（`agents/sub_analyst.py:76`）。mini 又发了 10 次调用，全被挡回；三次文字回复后循环停下，26 行一行没交。5.6 没有掉进去 | 消失：没有分析师循环 |

### 6.2 工具描述没说清的：工具做得到，描述没写

| 哪里 | 没说清什么 | 代码里实际是 |
|---|---|---|
| `calc` | 相减相除哪个在前；`by` 参数没有描述；`rank`、`top` 返回什么；`yoy`、`qoq`、`pct` 怎么定义；哪些数字不能相减。出现在 10 道题里，是报告最多的一项 | 第一个减、除以第二个。`yoy`、`qoq` 按日期配对，`pct` 和上一个点比。两本组合的数字可以相减相除，不能相加相乘 |
| `metric` 的 `params` 说明 | 把 4 个既不收参数也不收期间的度量归进了"其它度量——窗口用 `period`"：`price.momentum_12_1`、`price.distance_from_52w_high`、`book.analysis`、`book.reconcile`。在 4 道题里被指出，其中两位读者指出它和同一个描述里的另一句矛盾 | 给这 4 个度量传 `period` 会被拒 |
| `metric` 的 `last_n` | 对纯余额的度量，该配 `{"quarter": "latest"}` 还是 `{"at": "latest"}`，和 `filings_read` 的说法不一样。实跑：两个模型都先写了十二个月窗口加 `last_n: 2`，见 6.3 | 度量一律配财年或季度 |
| `list`、`book_read` | `list` 没说会列出列名；`book_read` 的 `row` 标签长什么样没说；`book_read` 管上一次 run 叫 `prior`，DESK 叫 `prev` | — |
| 每个动词必填的 `why` | 描述还是"which line of your task this step serves"。单 agent 没有任务行，读者在 4 道题里指出不知道它指什么 | 另有一处拒绝文案还在说"the risk analyst's" |
| `scenario`、`start` | 返回什么、没有重跑的检查在新组合里怎么呈现、`start` 之后怎么知道准备好了。只来自读者报告 | — |
| 期间 | 财年和财季按哪一年编号；`ttm_to` 的日期不落在季度末时怎么办。只来自读者报告 | 财年标签是发行人自己的。实跑里 5.6 自己推的日期恰好都是期末，工具照收，并在行上写出实际窗口；不落在期末的情形没有碰到 |
| `list` 的拒绝（实跑） | issuer 分析师的 `list` 不收 `book`。mini 写了 5 次 `list(what="book.position")`，拒绝只列出可用的枚举，不提 `book.position` 是 `metric` 的度量名 | 5.6 直接从 `metric` 的枚举里找到了它 |
| `ask`（实跑；简化后消失） | "同一个分析师加同一组主体，一次只能一张任务"只写在拒绝里。描述里反而有一句 "several issuers studied in depth are one task each"，而一次最多 4 张任务。mini 撞了 3 次 | 规则在 `agents/delegation.py:275` |

### 6.3 工具做不到或输出不完整的：要改工具

- **没有逐对的运算。** `scale` 一次只收一个输入，`divide` 的列表形式只能共用一个除数。"每个持仓按 20% 日均成交量要卖几天"是 10 次 `scale` 加 10 次 `divide`，所以 Q09 要 23 次调用。实跑印证：三家公司、两条科目、两个窗口，最少要 12 次读、6 次除、3 次减、2 次排名，共 23 次；五家要 37 次。两次读出的行不能按公司对齐相除，5.6 的主分析师手写了 11 次 `calc`、22 个行 id。`filings_read` 能一次读多家，但两个模型都是一家一家读的：上一期的窗口每家日期不同。
- **一次问多个主体的 `metric`，被拒的那个不出现在返回里。** 离线复现（把这个动词在这种情况下返回的结构交给仓库自己的适配器）：问 `["TSLA", "AAPL"]` 的净利率，模型读到的是"→ 1 row"，只有 AAPL 一行，没有任何一行提到 TSLA。单独问 TSLA 才有拒绝行。返回里没有任何东西告诉 agent TSLA 被拒了。实跑补充：桌上有、只是输入不全的主体不会被吞。mini 那一轮一次问五家的 debt / cash from operations，MSFT 和 NVDA 各回了一条缺席行。
- **（实跑）"本期十二个月对上期十二个月"没有一次调用的写法。** 两个模型的第一反应都是 `{"ttm_to": "latest"}` 加 `last_n: 2`：mini 在 `metric` 上写了 5 次，5.6 在 `filings_read` 上写了 6 次，全部被拒。拒绝行的出路只说改用财年或季度序列，没有提"把日期写成一年前的期末"。走得通的写法要先知道每家的最新期末（6.1 的覆盖信息），再自己算出一年前的期末。
- **（实跑）`calc` 的结果行有三处问题。**
  - 两个百分比相减，行上写 `1.79%`，实际是百分点。答案要照行原样写，所以最终答案里是 "up 1.79%"。
  - 9/10 的权重减 9/09 的权重，行上的窗口是 "2026-09-10 to 2026-09-10"，存下来的起止都是 9/10，基期丢了。risk 分析师的 note 写了"从 2026-09-09 到 2026-09-10"，被拒：它引用的排名行和这些差值行一样，只带 9/10。它只好把日期删掉。
  - 行名是机械拼出来的："issuer exposures: weight − issuer exposures: weight"。
- **（实跑）"自上次 run 以来的权重变化"没有动词。** `list` 列出了 `issuer_exposures.weight_change` 这一列，但工作流对每一行都写 NULL（`workflow/exposure_workflow.py:834`）。算这个差值的是 `services/run_series_service.py`，只给网页用，agent 够不着。5.6 用 2 次读、3 次减、1 次排名重算了一遍。
- **（实跑；上限接回来时才有）被拒的调用照样计数，上限行的标签是错的。** "十二个月窗口加 `last_n`" 那几次拒绝各算一次：mini 5 次，5.6 6 次，都在 16 次里。上限行写的是任务的第一个主体和第一个撞上限的动词：挡的是 NVDA 的读和一次 `calc`，行上是 "filings read, AAPL"。5.6 的分析师把这行当证据交了回去。
- **没准备过的公司，拒绝里给不给出路，取决于走哪个动词。** `filings_read` 的拒绝会说用 `start(kind='readiness')`。按财年或季度问 `metric`，得到的是"没有可放进财年日历的期间"，不提怎么办。
- **读者想做而没有现成动词的。** 这几项来自读者报告，对照 schema 属实：
  - 单日或一周的收益没有度量：`price.window_return` 最短一个月，要自己用两次 `prices_read` 加 `calc` 拼。
  - `filings_search` 不能按"早于某日"或某一份申报收窄。
  - 卖出所得不能留在组合里当现金。
  - 申报文本的表单只有 10-K 和 10-Q，没有 8-K。

### 6.4 skill：手册和登记簿

盲测报告的两条，是手册内部不一致：

- 对金融发行人，政策句只说"以利息为基础的杠杆和覆盖"不适用。登记簿里实际有 25 个度量对金融发行人拒绝，包括毛利率和流动比率。Q11 的读者不知道解释拒绝时该引用哪个范围。
- 手册一直说"the index"，没说就是 SPY；"短窗口和长窗口"取哪两个也没说。只来自读者报告。

实跑看到的四条，是手册和登记簿里没有的：

- **登记簿里没有"经营现金流 ÷ 净利润"这个度量，手册把这个问题指到了别的度量上。** 手册 earnings quality 一节把 "operating cash flow beside net income" 的 Measured by 写成 accruals 系列（`analytics/handbook.py:99-109`）。mini 照着做，在 accruals 上花了 15 次调用，拿到的是另一个量。5.6 没有照手册做，读了两条科目再相除。5.6 的 risk 分析师也去 `list` 里找过这个度量。有了这个度量，这道题的前半是一两次 `metric` 调用。
- **"上一个十二个月"怎么取、财年不同的公司怎么比，手册没有说。** 三家的最新期末是 3/28、3/31、7/26。5.6 自己定了口径：各自的最新期末往前一年，答案里写明每家的窗口。
- **比率的变化按百分点读，手册讲读法的一节没有这一条。** 和 6.3 里 `calc` 行的单位是同一件事的两面。
- **用户的口径和桌面的口径不一致时怎么答，没有规矩。** 用户说五家科技股，桌面上标 Technology 的是三家。5.6 纠正成三家后，没有说被排除的是 AMZN 和 GOOGL，也没有说它们在桌面上归哪个行业。

## 7. 先放下的事以后怎么接回来

- **validation。** 它是循环结束后对答案做的一步，接在循环外面。它不需要 agent 多背规则的前提是：数字由桌子按行 id 写进答案，而不是让模型抄。这一点另议。
- **上限。** 它是循环里的一个计数器。接回来时要把剩余额度写进 context：有两位盲读者问了"有没有调用次数上限"，因为这决定它该展开做还是省着做。即使不设上限，实现时也该留一个很高的保险值，防止循环停不下来。实跑里的情形：现有的上限按次计，每张任务 16 次，被拒的调用也算；而工具是一次调用一个格子，三家公司的题最少要 23 次（6.3）。两个模型的 issuer 分析师都在算出第一个比率之前把 16 次用完了。
- **数据外发。** 合成一个 agent 后，私有持仓和外发的 `web_search` 在同一个 context 里。现在 issuer 分析师那里已经是这样：它有 `book.position`，也有 `web_search`。要不要加机械的隔离，另议。

## 8. 下一步

1. 定稿 4.4 的角色措辞，以及 6.1 里属于 context 的几项补充。
2. 实现 4.1 的循环。现有的对话 battery 脚本直接调 `meta_agent.handle_message`，给它加一个开关换成新循环。
3. 在夹具库上用同一批题实跑，和现在的分支对比：答出率、调用被拒率和原因、每题的调用数和 token。这一版没有门，答案对不对要离线核。
4. 按实跑结果决定 6.2、6.3 先修哪些。
5. 再回头谈第 7 节的三件事。

## 9. 复现

脚本只读仓库，输出写在自己所在的目录。在仓库根目录执行：

```bash
A=docs/spikes/agent_context_tools
export MCP_INTERNAL_SECRET=offline PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=$A

.venv/bin/python $A/build_context.py                         # 拼 context、量 token、生成每道题的 prompt
.venv/bin/python $A/reference_paths.py                       # 校验 14 条参考路径
.venv/bin/python $A/score_blind.py $A/blind_journal.jsonl    # 给盲测计划打分
```

| 文件 | 内容 |
|---|---|
| `build_context.py` | 角色草稿、手册拼接、合成 DESK、14 道题 |
| `validate_plans.py` | 校验器：工具的 schema 加读数据之前的形状规则 |
| `reference_paths.py` | 14 条参考路径 |
| `blind_workflow.js` | 盲测的编排脚本和给盲读者的指令原文 |
| `blind_journal.jsonl` | 7 位盲读者的原始返回 |
| `score_blind.py`、`blind_scored.txt`、`blind_scored.json` | 盲测打分脚本和结果 |
| `role.txt`、`handbook.txt`、`tools.json` | 渲染出的角色、手册、工具 schema |
| `prompts/`、`sample_prompt_Q09.txt` | 每道题的完整 prompt |

本文的 token 数用仓库的 `context_budget.count_tokens`（o200k_base）量得。两次实跑的 token 数是 provider 返回的用量。

两次实跑的原样记录在 `docs/spikes/agent_context_tools/instance_run/`：

| 目录或文件 | 内容 |
|---|---|
| `q07_live/` | gpt-5.4-mini 那一轮 |
| `q07_gpt56/` | gpt-5.6-sol 那一轮。`param_probe.txt` 是这个型号带工具时接受哪些参数的探测结果 |
| 两个目录里的 `wire.jsonl` | 每次模型请求的原样请求体和完整响应，每次工具调用的原样参数和结果 |
| `transcript.md`、`timeline.txt` | 逐次的可读版；一行一个事件的时间线 |
| `battery_out.json` | 这一轮存下的步骤、答案和元数据 |
| `run.log` | 这一轮的控制台输出：起止时间、运行条件、一行结果摘要 |
| `run_live.py`、`render_wire.py` | 包装脚本，只在模型请求和工具调用两处挂钩，仓库不动；把 `wire.jsonl` 渲染成上面两个文件的脚本 |
| `freeze_before.txt`、`freeze_after.txt` | 运行前后仓库树和夹具库的状态 |
| `q07_live/gate_probe.py` | 离线复跑答案检查 |

`instance_run/` 顶层的 `q01_*` 和 `reconstruct.py` 是 9/30 一轮旧记录的重建，本文没有用到。

复跑一轮会真的调用模型，并在夹具库里多写一个会话：

```bash
cd /home/ubuntu/exposure-workbench
BATTERY_OWNER_ID=<owner> .venv/bin/python \
  docs/spikes/agent_context_tools/instance_run/q07_gpt56/run_live.py \
  docs/spikes/v33/questions_v33.json Q07-tech-cash-conversion-rank gpt-5.6-sol
```
