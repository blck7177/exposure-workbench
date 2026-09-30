# 架构读数（2026-09-30）：agent loop · tool · skill · subagent · validation 的边界，从三轮实测的输入输出判

> 依据：三轮同题同模型（gpt-5.4-mini）实测——`V2E_mini`（desk-v2-wip e3a450f）、`V2E2_mini`（68a52e1，三处修复后）、`S2_mini`（codex/simplify-agent-loop-s2 f26c7f9，S1+S2 简化后）；记录在 `docs/spikes/v1/ACCEPTANCE_*.md`。每个判断先说角色边界（9/8 规则：LLM = intelligence、skill = domain knowledge、tool = 正交且让 LLM 能表达意图、validation = 正确性与可追溯），再落到载体与代码。外部依据列在末尾。

## 0. 结论

**最核心的问题：正确性的负担落在"模型把结构化事实转写成散文"这一步上，而 validation 核对的是转写的文法，不是含义。**

桌子里的事实本来就是带 id、主体、度量、期间、单位、意义、来源的行。架构让它两次经过小模型的散文——分析师把行写成 finding 句（V2），主分析师再把 finding 写成答案——每一次都要求模型自己带上括号、id、单位、期间、排名、方向（风格指南 8 条是模型要背的门规）。三轮实测里**全部**耗尽都死在这套文法上（括号、裸 id、mark_mismatch、最高级），而抽查出的假陈述（把 `rates_up` 净 beta 写成 "net beta to SPY"、把 NVDA 权重写成损失占书份额、AWS 份额取错年份且 "16%" 靠账本另一段的 "$16.5 billion" 对上）门全部放行。S2 去掉了分析师那一次转写（证据行直达主分析师），但把主分析师那一次留着，所以死因从分析师的括号变成主分析师的 mark_mismatch（8/8）。

按角色说：**LLM 被要求另持一份 validation 的规则**（把出处文法背在头上），**validation 判的是自己规则的形式而不是事实与句子的关系**。修法先归位：模型只**指**行，数字由桌子**写**（答案与 note 只允许引用表达，渲染层从 id 填数与单位）；validation 改成核对"句子里的度量词 / 基准 / 主体 / 期间与所指行的元数据一致"——这是机械检查，不是语义判断。做完这一步，三轮里 60–70% 的退回类别（unpointed、unsourced、id_in_prose、mark_mismatch）不再存在，门的力气才能花在 SPY/权重/年份这类真正的错上。

其余问题按重要度：工具语法要模型记内部结构（期间形状、因子表行名、交易"全部所得"、段落里的数），三轮稳定 25–28% 调用被拒；分析师预算不按题规模；同题单次运行不是测量（次间翻转 5–8 题）；没有一个主分析师与分析师共读共写的工作状态对象；S1 撤掉 requirements 之后，"用户问的答完没有"在系统里没有任何表示。

## 1. 五个角色，各自的输入输出与边界判断

### 1.1 agent loop（主分析师循环）

| 输入（实测载体） | 大小 |
|---|---|
| `_ROLE` 角色说明 + 风格指南 8 条（system） | ≈3.1k + 1.6k 字符 |
| `<desk>` 目录简报：主体、持仓名、日期、覆盖，无数字 | 题而异 |
| `<roster>` 三位分析师能答什么（金融语言，无度量键） | 6.4k 字符 |
| `<readings>` 意义层（读法，无数字） | 3.6k 字符 |
| `<state>` 工作视图（V2：要求/发现/缺口/任务；S1 起分页，每页 ≤40 卡 / 24k 字符） | 变动 |
| ask 回单（tool result，≤28,000 字符；S1 起只有 id 与计数） | ≤28k |
| 历史、退回信（`rule N — reason: way out`） | — |
| 工具：`ask`（schema 2.0k 字符）、`open`（0.9k）、`repair_answer`（0.7k） | — |

实测：第一次 completion 的 prompt ≈ 30–36k 字符，峰值中位 41k、最大 127k（V2E2）；S2 峰值中位 12.3k token；每题 completion 中位 5（V2）/ 3（S2），上限 16；答案句检 2 次机会。

**边界判断**：主分析师不持工具面、只 ask/open/写——这条边界是对的，实测里它没有越界去拉数。缺位有三处：① V2 的 validation 要它的结论也拿一行证据（"伞形要求"4 题永远 partial），S1 撤了这条却没有替代，现在 `completion=null`，系统里没有人知道"问的答完没有"；② 同一信息两条载体（ask 回单 vs STATE 块），Q05 实测它盯着被截断的回单说"没有可引用的行"，而 STATE 里四条 finding 全在；③ 它的 prompt 是五块 system 文本叠加 + 历史 + 回单，41k 字符中位——Anthropic 的多 agent 研究系统里子 agent 返回给主 agent 的是 1–2k token 的精炼结果，这里 V2 回单是整段 finding + 行，S1 改为 id + 计数是对的方向。

**robust**：不。同题两轮翻转 5–8 题（Q14/Q15/Q16 一轮耗尽一轮出答案），单次运行的 12/14/10 不构成方向。τ-bench 的 pass^k 就是为此设的：同题 8 次全过的概率对 gpt-4o 在零售域约 25%。这里没有 pass^k，只有 pass@1。

### 1.2 subagent（三位分析师）

| 输入（实测载体） | 大小 |
|---|---|
| `_SYSTEM` 角色 + 风格指南 + **本章手册**（issuer 14.5k / risk 12.0k / market 6.6k 字符） | 17–20k 字符 |
| 本面工具 schema（issuer 8 动词 15.0k 字符 / risk 6 动词 9.5k / market 5 动词 7.2k） | ≈2–4k token |
| `<task>`（analyst、subjects、lines、context、follow_up_of）、`<coverage>`（目录）、`<question>`（用户原话）、`<prior>`（跟进时） | — |
| 工具结果：行（`r_… verb(…) → k rows`）或缺席行（reason + 出路句） | — |
| 预算：16 次证据调用、10 次 completion | — |

输出：V2 `submit.brief.lines[{n, settled, finding+facts | why+boundary}]`；S2 `submit{evidence:[ids], notes:[{text, refs}]}`。实测：任务数 46/48/36，空返 26/29/**0**，handoff 被拒 45/69、54/79、40/55，prompt 峰值中位 15k token。

**边界判断**：面按资源族裁、每次 why、行自带意义——正确。越界两处：① 分析师被要求做 validation 的文法（V2 每行造边界、写括号；S2 note 仍要"数字与 refs 一致"），这是把门规放进了 intelligence 的工作；② 分析师自己做算术（Q07 心算 "1.0x"，desk 有 `calc divide` 它没用）——LLM 越界到 tool。缺位：每个分析师只看到自己的任务与账本，看不到同一 turn 里另一位分析师的发现；跨族转手全靠主分析师再问（X 系列 carried 2–3 / 9）。

### 1.3 tool（12 动词三面）

输入：schema（期间 `oneOf` 五形 + "latest" + `last_n` 三种搭配；`metric` 名 enum issuer 34 个；`book_read` 的 table/row/column 三维；`calc` op；`scenario` trades）。输出：行或缺席行。

实测三轮调用被拒 101/409、107/408、100/383——**25–28%，跨三轮不变，说明是接口不是模型波动**。按码：`invalid_params` 35/32/19 全是期间语法（余额不能 quarter+last_n、度量要 window、`ttm_to` 要日期）；`unknown_name` 16/28/19（S2 轮 20 次是按名字读因子表里不存在的行）；`not_held`/`input_unavailable` 是真数据缺席。另有表达不了的意图：交易"把所得全买入"（Q13 三轮）、段落表格里的数进不了 quantity（Q19 三轮）。

**边界判断**：正交、拒绝成行、每次 why——设计对。没做到的是"让 LLM 一次表达意图"：期间语法要模型知道哪条科目是余额哪条是流量，行名要模型知道因子表按因子不按名字，这些是工具内部结构。Anthropic 的 ACI 建议（工具文档、示例、"让犯错变难"）与 OpenAI 的 strict schema（约束解码，schema 形状 100% 服从）都只解决"形状"，解决不了"选哪一形"——`oneOf` 五形本身就是把选择推给模型。修法在 tool：期间由行的种类推断（tool 知道 balance/flow，模型给 `last_n=8` 就够）；`book_read` 行名缺席时列出表里有什么行；trades 加 all-proceeds；段落表格进 quantity 的路径（S3）。

### 1.4 skill（手册三章 + roster + readings + 登记簿）

输入给主分析师：roster（金融语言）与 readings（意义层）；给分析师：本章手册（问题 → "Measured by: …"）。**边界判断**：知识在被读不被执行的位置——对；实测没有看到 skill 写成脚本或 tool 替 skill 判断。缺位一处：手册说 "measured by accruals ratio…"，工具 enum 要 `accruals_ratio` 键，映射靠 `list(what='metrics')`（每任务先调一次，25 次/轮）——可接受的成本，但 Q07 的分析师读到"现金转换"却找不到对应度量，就自己算了：skill 与 tool 的词汇表没有对齐到"每个可问的问题都有一条可算的路"。

### 1.5 validation（风格指南 → fact_boundary 六通道 → answer_check → handoff 检查 → 状态类型）

输入：句子 + 账本；输出：verdict{problems[{rule, reason, where, way_out}]}。判：出处（每个数有行）、指向（id 在账本上）、转写（数与行一致）、最高级、期间、主体、方向、引文。

实测它做对的：三轮没有一个凭空数字进到读者眼前。它做错的（离线复现）：

| 放行的句子 | 事实 | 机制 |
|---|---|---|
| "net beta to SPY is 0.01× [f_…]"（Q16，V2E2 与 S2 同句） | 行是 `portfolio.integration.net_beta.rates_up` | 度量词取点号尾部 → "rates up"；句子里的 "SPY" 与任何元数据都不比对 |
| "would lose $52.22K … That is 4.06% of the book"（X07） | 4.06% 是 NVDA 权重，不是损失占书份额 | 数字与行一致；"份额/权重"这类度量词不在检查里 |
| "16% in the year before that [passage]"（Q19） | 所指段落无 16%；账本另一段有 "$16.5 billion" | "账本能对上"按数字串在任一段落出现放行，不看所指行、不看单位 |

另两处越界：① 风格指南 8 条是**写给模型背的门规**——validation 的规则住进了 LLM；② V2 的 `GAP_OF_REASON` 用错误码族替桌子判"这是数据缺席还是叫错名"（`unknown_name` 记成可关闭的 data_missing；`insufficient_observations` 记成永不关闭的 execution_failed）。

**robust**：对形式 robust（三轮零漏数字），对含义不 robust（抽查 3/3 假陈述）。没有独立 oracle（P0b 未做），所以"多少假陈述"至今是手数。

## 2. schema 定义是否清晰

- **ask**：S1 后四字段（analyst/subjects/lines/context/follow_up_of），清晰；V2 的 requirements/anchor/for 让 21/16 次 ask 被拒（13 次重复声明），S1 撤了——对。
- **submit**：V2 的 lines/settled/finding/why/boundary 要分析师给每条未结行造一个缺席行（`not_a_boundary` 14 次），S2 的 evidence + notes 清晰且少——对；代价是"什么算交完"没有表示。
- **工具 schema**：定义清晰（每个参数有类型、模式、说明），问题是**不可推断**：期间五形 + `last_n` 搭配、`metric.params` 每度量不同、`book_read` 的行名不在 schema 里、`scenario` trades 语法缺一种意图。清晰度不是问题，可猜性是。
- **STATE / 回单**：S2 视图字段 question/scope/findings(text, refs, rows)/gaps(type, call, rows_not_handed)/tasks(execution, operations, stop_reason)/evidence/budget/paging——清晰；问题在体量（一页 24k 字符）与两份载体重复。
- **退回信**：`rule N — reason: way out` 统一、可追溯——好；但 way out 常常是"再问或指向缺席行"，对预算已尽的分析师是空话。

## 3. agent 拿到的 context（实测）

| | 主分析师 | 分析师 |
|---|---|---|
| 固定 system | 角色 3.1k + 风格 1.6k + roster 6.4k + readings 3.6k 字符 | 角色 1.5k + 风格 1.6k + 本章 6.6–14.5k 字符 + 工具 schema 7–15k 字符 |
| 变动 | `<desk>` 简报、`<state>`（分页）、回单、退回信、历史 | `<task>`、`<coverage>`、`<question>`、`<prior>`、行、缺席行 |
| 实测规模 | 首次 30–36k 字符；峰值中位 41k（V2E2）/ 12.3k token（S2）；最大 127k 字符 | 峰值中位 15k token |
| 看不到的 | 原始行（要 open）；分析师被拒的原文 | 另一位分析师的发现；主分析师的状态；被拒 note 原文（S2） |

判断：主分析师的 context 是"五块说明 + 一份投影 + 一份回单"，两处重复、一处截断（28k）；分析师的 context 是"手册 + schema + 任务"，其中手册 + schema ≈ 20–30k 字符是常驻成本，每题 × 任务数。Anthropic 的做法是子 agent 返回精炼结果、主 agent 只做综合；这里 S1 把回单缩成 id + 计数是同一方向，但 STATE 一页 24k 又把体量放回去了。

## 4. 是否存在全局 state management

有存储，没有"一个状态"。现状：

| 存储 | 谁写 | 谁读 | 粒度 |
|---|---|---|---|
| `facts`（账本） | 工具（每次调用铸行） | 门、主分析师（open）、分析师（自己的调用） | session，只增 |
| `calc_ledger` | calc / scenario | book_read | session |
| `analysis_state` | 主分析师循环（版本化 CAS） | 主分析师（投影为 STATE）、下一 turn（继承需重验） | turn |
| `analyst_reports` | 分析师 store | 页面、follow_up 的 `<prior>` | task |
| `agent_steps` | 所有节点（trace） | 取证工具 | step |
| `agent_messages` | 主分析师 | 下一 turn 的历史 | message |
| 内存 `Delivered` | 主分析师循环 | 记 llm_call 步 | completion |

判断：**碎片化、以主分析师为中心**。分析师之间没有共享的"本 turn 已发现什么"（只共享账本行，不共享结论）；主分析师的状态是每次 completion 重算的投影，不是各节点共读共写的对象；跨 turn 只靠发现的重验继承；S1 之后"用户要什么、答了什么"没有结构化表示。参照 LangGraph 的做法——一个 typed 的共享状态、reducer 合并、checkpoint 持久化、节点之间用显式契约转手——这里最接近的是 `analysis_state`，缺的是：分析师也写它、要求/交付项这一格、以及它作为唯一载体（回单只给 id）。

## 5. 修在哪（按角色，不改模型文字的先做）

1. **validation / tool（最核心）**：数由桌子写。答案与 note 只允许引用表达（`[f_x]` 或 `{ref, part}`），渲染层从行填数字与单位；门改查"句子的度量词 / 基准 / 主体 / 期间与所指行元数据一致"（用行的 `measure`、`params.benchmark`、`subject`、`window`，不用点号尾部词）；段落只允许引文，段落表格里的数走 quantity 路径。一步消灭 unpointed / unsourced / id_in_prose / mark_mismatch 四类。
2. **tool**：期间由行的种类推断；`book_read` 行名缺席列出行；`scenario` 加 all-proceeds；`metric` 收到科目名时直接转 filings_read。
3. **harness**：分析师预算按题规模（名字数 × 期数）或加批量算术；同题跑 3 次以 pass^k 读数；同一信息一条载体（回单只 id，正文只在 STATE）。
4. **state**：一个 turn 的工作状态对象（问题、交付项、证据、发现、缺口、预算）作为唯一载体，分析师写证据与 note，主分析师写结论，持久化版本化——S1 的视图已是雏形，补"交付项"一格；"答完没有"由它机械给出（每个交付项有 finding 或缺席行），不再要求主分析师的结论也拿证据。
5. **测量**：先建独立 oracle（P0b），再谈成绩；现有 answered/exhausted 只量门，不量对错。

## 外部依据

- Anthropic, How we built our multi-agent research system（orchestrator–worker；子 agent 精炼后返回；主 agent 的任务描述要写清目标、输出格式、工具、边界）：https://www.anthropic.com/engineering/multi-agent-research-system
- Anthropic, Effective context engineering for AI agents（子 agent 返回 1–2k token 摘要；结构化笔记；按需检索）：https://www.anthropic.com/engineering/effective-context-engineering-for-ai-agents
- Anthropic, Building effective agents（ACI：工具文档、示例、让犯错变难）：https://www.anthropic.com/engineering/building-effective-agents
- τ-bench（pass^k：同题 k 次全过；gpt-4o 零售域 pass^8 ≈ 25%）：https://arxiv.org/abs/2406.12045
- OpenAI, Introducing Structured Outputs（约束解码，schema 服从 100%——解决形状，不解决选形）：https://openai.com/index/introducing-structured-outputs-in-the-api/
- LangGraph 状态管理（单一共享状态、reducer、checkpoint、显式契约转手）：https://langchain-ai.github.io/langgraph/concepts/low_level/
