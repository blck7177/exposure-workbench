# 模型的信息契约：它应该知道什么，输出什么（设计稿，2026-09-13）

前提：V33 的 trace 与 I/O 分析（`TRACE_V33.md`、`MODEL_IO_ANALYSIS.md`）。
已定的两项：回答是自然语言，对不上的数字退回重写最多两次；关系词要查。
四角色：LLM 是智能，skill 是领域知识，tool 正交且让 LLM 能执行意图，validation 管正确与可追溯。

## 0. 一条原则

**模型只做决定，不做抄写。**
需要它判断的——看什么、比什么、算什么、结果意味着什么、desk 做不到时说什么——是它的工作。
需要它一字不差地复制的——名字的拼法、fact 的 id、类型的转换、序号的对齐、关系的声明——每一处都是错误面，都不该是它的工作。
V33 里模型自己犯的错（读反序列、写 0.25、选错 key、编 id）在这条原则下大半消失，因为它们发生在抄写处，不在决定处。

## 1. 模型应该知道的（输入）

### 1.1 角色，和唯一的一条规则

系统提示只保留两件事：你是这台 desk 的分析师，分析是你的工作；**你写出的每个数字必须是你被展示过的，照它显示的写，拿不准指哪个就带上它的 id**。
删掉：claims 语法、11 种关系、`{cN}`、"figures come from ONE tool"、三条出路。
理由：这些是 validation 的类型工作漏进了 LLM 的输入；"三条出路"没有第四条，导致 Q11 白卷、Q06 换问题、Q17 编 id。

### 1.2 问题涉及主体的目录，带身份维度，开轮即推

今天模型每轮先 `describe()` 再 `describe(subject, expand)`，43 次 describe 占 106 次调用的四成，且读不到判断需要的维度。改为：问题里能识别出的主体（ticker、port_、run_），其目录在第一次 completion 之前就在输入里，形式是**类型化对象**而不是名字：

| 主体 | 模型必须看到 | V33 里因为看不到而错的 |
|---|---|---|
| 组合 | 每个持仓的 ticker、**sector**、asset_class、weight、market_value；每个检查的 current/warning/breach 与所属实体；可用的 run 及日期（latest、prev） | Q07 把 JPM/LLY 当 tech；Q11 room 指错档 |
| 发行人 | 已 filed 的行及其覆盖（flow/instant、最新期、缺口）；**可计算与不可计算的方法各带原因**；方法的**类型化参数签名**（不是名字列表）；已索引的 filing 与日期；价格覆盖区间 | Q07 `at:"prev"`；Q06 一年前不可问；Q19 该走 read_filings |
| desk | 不持有什么、不能做什么，每条一句读者级的话 | Q13 编 `f_held_beta` 而非引 `scenario_refit` |

两处今天的信息本身是错的，必须改对：`issuers_prepared` 应只列就绪的（B 轮里 `start` 让 MRK/BAC/GS 立刻出现在别的 session 的目录里）；`describe(ticker, expand='methods')` 返回空。

### 1.3 语言的类型签名与边界，作为数据

`run` 的 1604 tokens 名字表换成每个原语和方法的**签名**：参数位置收什么类型（scalar / vector / series / run / label 列表 / 数字字面量 / 日期字面量），返回什么类型，哪些参数决定返回类型（`last_n` → series；subject 列表 → vector）。同样体量，信息量完全不同。

以及**边界**，明说：价格方法没有 as-of；没有按阈值筛选的原语；scenario 不重估 beta 与 stress。模型知道边界才能说"这一问 desk 表达不了，最近的是 X"，而不是把问题改掉不告诉读者。

模型不应从这里学到的：怎么把 series 变 scalar 才能进 vector、字面量什么时候能当操作数——这类**类型转换**是 tool 的活：签名声明了就要么接受要么在一次类型检查里全部指出（见 1.6）。

### 1.4 领域程序，作为可直接调用的东西

skill 今天推送的 program 示例，模型是复制后改的（Q08 照抄 `method(capex_intensity, last_n)`，自己拼的 rank 部分错了）。复制加编辑是错误进入的地方。模型应看到的是：每个 procedure 的名字、它回答什么问题、要填什么（subject、window）、产出什么；能直接以 `procedure(name, fills)` 请求。只有 procedure 不覆盖的组合才写 program。
推送的选择按问题里识别出的主体与意图，不按词袋（Q15 问流动性被推了 `issuer_business_risk_from_filings`）。

### 1.5 工具返回：显示给模型的每个值都可引用

规则要么是"你看到的都能说"，要么模型必须一眼看出哪些不能说。今天两者都不是：`pick` 出来的日期显示为 `"literal": "2026-01-07"` 无 id（Q14），`held_back` 只剩 `{count, measures}` 无 id（Q13）。
契约：**tool 返回里出现的每个值都带 id，或者不出现**。日期、计数、字面量一律成 fact。被 cap 截掉的图形上账本，只是不展开，模型看到"另有 N 个图形，按名读取"。
facts 的身份列要够判断：run 与 scenario 对同一个量用同一个 measure 与 subject 写法（Q13 第 5 次）；方法结果携带自己的 window（Q14 起点日期）；持仓携带 sector。

### 1.6 反馈：一次全量、带类别、带路径

三种反馈模型会读到，每种都要满足这三条：

- **program 的类型报告**：执行前静态检查，**一次报出所有类型错误**，每条含期望类型、实际类型、可用的转换。今天一个 program 十几个节点，一次只爆一个，Q13/Q11 各写了三次。
- **答案的核对结果**：最多两次，每次列出**全部**对不上的数字与冲突的关系词，每条带账本上的候选。
- **每条拒绝带类别**：`spelling`（改拼法）、`type`（改类型）、`boundary`（desk 做不到，可以告诉读者）、`data_absent`（desk 没有，可以告诉读者）。今天 `SPELLING_REFUSALS` 这张表只有门知道，模型不知道哪种拒绝可以转述给读者，于是 `refused_not_absent` 反复出现。

拒绝的措辞讲路径不只讲规则："vector 收 scalar，你给的是 series；对每个 entry 取 latest，或去掉 last_n"，而不是 "not a settled scalar binding"。

## 2. 模型应该输出的

### 2.1 分析请求

`procedure(name, fills)`，或 `program`。program 保留 JSON——它是分析本身，正交于自然语言回答——但：

- **一种写法**，由 strict schema 强制（B 轮三种写法 30/74/156，schema 是 `["array","object"]`，教不了任何东西）。
- 叶子引用模型**被展示过的东西**：id、label、目录里的名字。不再从全局名字表里挑拼法。
- 字面量是一等公民：数字与日期在任何操作数位置都合法，类型由签名判。

模型不再自己做的：类型转换、名字路由、猜返回形状。

### 2.2 回答

自然语言。三样附加物，都是**可选且极轻**：

- 数字后可带 `[f_…]`，只在核对结果说有歧义时需要；
- `[table: node]`、`[chart: node]`，指向自己在 program 里起的绑定名，渲染器画；
- 讲 desk 做不到或不持有时，可带那条 absence/boundary fact 的 id，让核对能认出这句话有依据。

必须包含的：问题里 desk 表达不了或没有的部分，**在回答里说出来**，用 boundary/data_absent 类拒绝作依据。这是今天缺的第四条出路。

### 2.3 不再输出

claims、relation、`{cN}`、作为必填的 fact id、absence fact 的原文、渲染指令。

## 3. 模型不需要知道的

| 不需要 | 谁负责 |
|---|---|
| 11 种关系及其约束 | 关系在 fact 上（rank/op/as_of/tier），validation 对照句子里的关系词 |
| 全局 metric/表/列名字表 | 主体目录里给已 filed 的行；tool 做名字路由 |
| 类型转换规则 | tool 的静态类型检查与转换 |
| 哪些值有 id | 全部有 |
| 渲染 | 渲染器读 fact 身份 |
| 哪种拒绝能转述 | 拒绝自带类别 |

## 4. 对其他三角色的前提（只列要求，不展开实现）

- **tool**：签名表与边界表作为数据导出；静态类型检查一次报全；字面量统一；每个显示值成 fact；同一量在 run 与 scenario 下同名；方法结果带 window；`issuer.panel` 这类不可定型的方法要么可定型要么不公告；崩溃变拒绝。
- **skill**：procedure 可直接调用，按主体与意图推送。
- **validation**：数字对账本（已定）；关系词对相邻芯片的 rank/op/as_of/tier（已定）；`[f_…]` 消歧；两次上限（已定）；不再读 claims。

## 5. 用 V33 的实例检验

| 实例 | 今天 | 契约下 |
|---|---|---|
| Q08 最高级反向 | rank 被拒后在散文里下结论，门看不见 | 签名说 vector 收 scalar，类型报告给出 `latest`；散文里的 "most/least" 由关系词检查对照 rank fact |
| Q14 日期变百分比 | 日期无 id，门拒，模型指错 | 日期是 fact；explain 结果带 window；正确日期直接通过 |
| Q17 十个名字错位 | 序号手抄 | 没有序号；散文里 "AAPL -5.83%" 由值与身份对账本，主体词不一致时拒 |
| Q11 白卷 | 8% 不可表达且模型不知道 | 边界表说没有阈值筛选；模型答前三部分，说明第四部分 desk 表达不了 |
| Q07 tech 五家 | 权重 fact 无 sector | 组合目录带 sector；模型看到 desk 只把三家标为 Technology，先纠正前提 |
| Q06 一年前 | 价格方法无 as-of 且模型不知道 | 边界表明说；模型说 desk 只有当前读数 |
| Q13 编 id | held_back 无 id；scenario_refit 有 fact 但模型没引 | 显示即有 id；目录里的 cannot 条目就在输入里 |
| Q01 "the chart below" | 数字被赶出散文 | 模型照抄系列的端点值，图表另附 |
