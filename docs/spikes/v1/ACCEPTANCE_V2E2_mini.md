# V2E2_mini 复测记录：三处修复之后，同题同模型再跑一臂（2026-09-29）

> **被测的**：`desk-v2-wip` HEAD `68a52e1`（树 `b265496`）= 第一臂的 `e3a450f` + 修 1 `c5f0f8c`（date 进 JSONB）+ 修 2 `25ebf6e`（覆盖退回不计句子尝试）+ 修 3 `68a52e1`（夹具停表、`start` 拒绝）。离线 3090 passed。模型文字无变化（措辞单 `--check` 无差异）。
> **条件**：与 V2E_mini 完全相同（`phase_e.sh V2E2_mini`：同一快照、同四个迁移 + remap、面 :8105、20 题并发 5、X 系列并发 4、全 gpt-5.4-mini），差别只有 `--deny submit_brief --deny start`（第一臂只 deny 了 submit_brief）与还原后停表（1 个调度停用，快照无遗留 pending）。03:34:40–03:40:12。lead 完成 106 次、analysts 274 次（X 系列 49 / 126），全部 `gpt-5.4-mini-2026-03-17`。
> **冻结**：开跑前后 HEAD/树相同、无 tracked 改动、src/tests/scripts 无新于 HEAD 的文件；中途未改任何东西。
> **文件**：`V2E2_mini*` 与 `V2E2_mini_X*` 各一套，同第一臂。

## 0. 一眼看完

| | V37C（mini） | V2E_mini（第一臂） | **V2E2_mini（复测）** |
|---|---|---|---|
| 出答案 / 20 | 13 | 10 | **14** |
| 门耗尽 | 6 | 10 | **6** |
| 出答案里 completed / with_boundaries / partial | — | 1 / 3 / 6 | 0 / 0 / 14 |
| X 系列出答案 / 9（其中 completed） | — | 3（0） | **9（3）** |
| `could not save` / `could not store`（写库失败） | — | 108 / 48 | **0 / 0** |
| turn 的状态从未落库（state_version=0） | — | 22 / 29 | **0 / 29** |
| 分析师报告落库 / 任务 | — | 13 / 46 | 47 / 48（29 verified、18 refused） |
| 分析师覆盖 done / asked | 72 / 135 | 34 / 146 | 35 / 141 |
| 分析师工具调用被拒 | — | 101 / 409 | 107 / 408 |
| submit 被拒 / submit | 43 / 56 | 45 / 69 | 54 / 79 |
| 主分析师 ask 被拒 | 2 | 21 | 16 |
| 每题 prompt 合计中位 / 用时中位 | 120k / 39s | 194k / 38s | 190k / 40s |
| tasks pending（夹具） | — | 80 | **0** |

**修 1、修 2 在实测上成立；修 3 的原因我在第一轮记录里写错了（§3）。** 分析师侧的读数基本没动，这才是 V2 现在真正的水位。

## 1. 三处修复各自在实测里的样子

**修 1（date 进 JSONB）**：写库失败 0；29 个 turn 每个都有 `analysis_state` 行（version 4–8）；分析师报告 66 行落库（含重交）。P2 的机制这一轮第一次真的在跑：X08 第二回合 10.5 秒、6 次调用出 completed 答案，带过了上一回合找到的 GOOGL（`carried`）。

**修 2（覆盖退回不计句子尝试）**：6 次耗尽的退回序列——Q04 `unsourced_figure`×2、Q11 `mark_mismatch`×2、Q14 `unsourced_figure` + `superlative_without_rank`、Q15 覆盖 + `id_in_prose`×2、Q16 覆盖 + `id_in_prose`×2、Q17 `superlative_without_rank`×2——**全部是两次句检退回**，覆盖退回不再结束任何 turn。第一臂因覆盖退回耗尽的 7 题（Q01/Q07/Q09/Q10/Q12/Q17/Q20）这次 6 题出答案，Q17 换了死法（两次最高级不带排名）。代价：答案退回次数 27 → 35（多出的都是第二次机会），lead prompt 峰值中位 13.9k → 13.0k，每题 token 合计中位没涨。

**修 3（夹具）**：`start` 被拒后没有任何 run 入队（tasks pending 0），第一臂 Q13/Q14/Q15 读 pending run 的死法消失。但我第一轮把原因写成"夹具没有 worker、scenario 的 run 永远 pending"是**错的**：读 `services/scenario_service._scenario` 与本轮 X02/X06 的行——`scenario` 在进程内同步重定价、重跑集中度与敞口检查、记成一本 calc_ 书（X06 返回 7 行，含 sector/issuer/limit_checks），回归拟合的检查（daily_loss、rolling_volatility_30d）与因子 beta 按设计标为 `not_run`（"the book after the sale has no return history"）；它不入队。第一臂的 pending 是风险分析师先 `start(exposure_run)` 重跑真书、再对那个 pending run 调 scenario。所以真正的修法只有"冻结夹具拒绝 `start` + 停表"；68a52e1 加的夹具 worker 整轮一个任务都没领到，已在后续提交拿掉。

## 2. 剩下的耗尽与 partial 是什么

- **6 次耗尽全是主分析师的书写纪律**（规则 1 括号、最高级要指排名行）：裸数字（Q04、Q14）、`f_` id 裸写进句子（Q15、Q16 各两次）、数字与所指行不符（Q11 两次）、"largest/most" 不指排名行（Q14、Q17）。Q14、Q16 第一臂出答案这次耗尽——同题同模型的次间波动，不是修复造成的（退回原因与修复无关）。
- **14 篇答案全是 partial**：runtime 自报要求 covered 13 / boundary 12 / unresolved 50（声明 75 项，矩阵 65）。unresolved 的来源在分析师侧：48 个任务 settled 4 / partial 24 / unsettled 16 / refused 4，空返 29、预算停止 7；工具调用被拒 107/408，按码 `invalid_params` 32（期间语法，与第一臂同类）、`unknown_name` 28（其中 20 次是 `book_read(factor_attributions, row=<ticker 或 QQQ/SPY>)`——按名字读因子表里不存在的行，是"桌子不持有逐名 beta"这个数据缺席被表达成了名字错误）、`input_unavailable` 15；handoff 被拒 54/79，`not_a_boundary` 14（第一臂 3）：分析师把未结行的边界指向一条数据行而不是缺席行。
- **Q13 换了死法**：scenario 这次被引擎正当拒绝——`insufficient_proceeds`："the purchases need 9,235,090.00 and the sales in this trade freed 218,360.00"。分析师把"把所得换成 TLT"写成 `{"buy": "TLT", "weight": 0.5}`（占书一半），而卖出所得只是买入所需的 2.4%。用户的意思（"全部所得"）在交易语法里没有词：`funding=proceeds` 说了钱从哪来，没说"有多少买多少"。属 tool 边界，待拍板。
- **X07**：completed，但答的是"每股损失 $44.14"，问的是"我们的仓位会损失多少美元"（计数器判 `not_carried`：书的市值行没带过去）。**X06**：卖的是 XOM 不是弱动量的 MSFT（`wrong_name`）。X 系列 9/9 出答案后，转手读数才第一次可读：up_front 3、carried 3、wrong_name 1、not_carried 1；这一轮没有 `in_sequence` 回合——主分析师都在第一次 ask 里把两族一起问了，步骤 7 的"面由任务组合"决策规则仍读不出成本差。

## 3. 角色判断（按 9/8 规则）

- 修 1：service 层缺陷，验收层缺一条真序列化测试——已补，不再是问题。
- 修 2：harness 回合控制把结构退回按句子退回计费——已归位；validation 仍只判结构。
- 修 3：**我的记录错误**——把设计内的 `not_run` 边界读成了夹具缺陷；夹具真正的边界是 `start`。改正后夹具只做两件事：停表、拒绝 `start`。
- 剩下的两类都在 tool ↔ LLM 边界：期间语法与因子表的行名要模型记住工具内部结构（`invalid_params` 32、`unknown_name` 28）；交易语法表达不了"全部所得"。规则 1 的括号纪律与最高级排名是模型变量（sol 臂能分离）。

## 4. 这一轮之后

- 不改代码可做：sol 臂（需要 `reasoning_effort=none` 包装）、E 基线臂 `fe8a447`（同一 phase_e.sh）。
- 拍板项：期间语法收成一种（tool）；`book_read` 的行名缺席应说明表里有什么行（tool 的出路句）；scenario 交易语法加"全部所得"（tool）；`not_a_boundary` 的出路句是否够清楚（validation 文字，要过目）；ask 重复声明机械接受；P0b 的声明粒度与矩阵对齐（75 vs 65）。

## 5. 14 篇 partial 逐模块看：每个模块收到什么、交出什么、在哪里断（2026-09-29，boss："分析每个模块的输入输出，找问题的 source 在哪里"）

方法：14 个 turn 的最终 `analysis_state`（要求状态、每个任务行的 `for` 与结局、缺口类型）+ round 文件里的步骤（调用、brief、答案）+ 缺口指向的缺席行的 reason 码，逐条要求找**第一个断掉的模块**；主分析师侧另查"已通过的 finding 有没有被回复引用"。14 篇里共 75 条要求：covered 13、boundary 12、**unresolved 29**（一条要求可能有多个任务行，按首断点归一处）。

### 5.1 管线：模块、输入、输出、这一轮断在哪

| # | 模块 | 输入（真实载体） | 输出（真实载体） | 这 14 篇里断的（要求数） | 源头判断 |
|---|---|---|---|---|---|
| M1 | 主分析师：拆要求 | 用户原话 | `ask.requirements[{id, anchor}]`，anchor 逐字（例 Q02：R1 "How much room does Exxon have if oil falls?"、R2 "net debt to EBITDA, EBIT interest coverage and FCF to debt for the latest four quarters…"、R3 "read what the 10-K says about debt maturities…"、R4 "relate that to our XOM weight and the book's beta to USO"） | **伞形要求 4**（Q02 R1、Q03 R1 "Where does NVIDIA's cash go?"、Q06 R3 "Note where the desk's issuer methods do not apply to a bank"、Q10 R1 "Microsoft's leverage story changed"）：问题的总纲被声明成一条要求，没有任何分析师行能结它，`unaddressed` 每次都退回 → 这 4 题上限就是 partial。另有碎片化（Q08 把一个交付拆成 R1 "capex intensity"、R2 "ROIC"、R3 "the last three fiscal years"，三条要求指向同三行，一行被拒三条全 unresolved） | **validation 越界到 intelligence**：P3 要求每条要求由 finding 或缺席行关闭，而总纲这种要求只能由主分析师自己的结论关闭——这条路径不存在。修在 harness/validation（要求可以标为"由回复自身结清"，或 anchor 只收交付项），不在模型 |
| M2 | 主分析师：派单 | requirements + roster（金融语言的 can_be_asked） | `ask.tasks[{analyst, subjects, lines, for, follow_up_of}]`（例 Q02 seq 37：issuer [XOM] 5 行，`for` = R2+R3 整任务） | `for` 粗：Q02 五行整体 for R2+R3，一行被拒两条要求同时 unresolved；16 次 ask 被 schema 拒（13 次是后续 ask 重复声明 requirements），每次一个 lead completion；再问平均 2.3 个任务/题，有在用 follow_up | LLM 的映射粒度；"只声明一次"是形式判断，相同的重复声明可机械接受（validation 文字/规则，不动模型） |
| M3 | 分析师：调工具 | 任务行 + 本面 12 动词（每次 `why`） | 行（`r_… verb(…) → k rows`）或缺席行（reason + 出路句） | **5**：Q03 R3（16 次调用预算用尽——4 项用途 × 3 年，16 次 ok 调用一次没浪费也不够）、Q07 R2（预算用尽前 `unknown_name` ×4）、Q12 R1（预算用尽前 `invalid_params` ×6 + `not_held` ×4）、Q09 R2（`price.window_return` 的 window 不收 "3y"）、Q10 R2（`net_debt_to_ebitda` 要 window）。全轮 107/408 被拒：`invalid_params` 32、`unknown_name` 28（20 次是 `book_read(factor_attributions, row=<ticker/QQQ/SPY>)`，因子表按因子不按名字）、`input_unavailable` 15 | **tool ↔ LLM 边界**：期间/窗口语法与表的行名是工具内部结构，小模型只能靠拒绝逐个学；**harness 预算**：`sub_analyst_evidence_calls=16` 对"多名 × 多期"题本身不够，且没有批量算术（P4-2 未做）。另 Q07 R1 是 LLM：OCF/NI 可以用 `calc divide` 算，它取了 `accruals` 再心算写 "1.0x" |
| M4 | 工具：缺席行 | 被拒的调用 | `f_… absence`，`means.reason` ∈ {not_held, no_such_name, not_prepared, meaningless, policy, param_out_of_range, cannot…} + 出路句 | **3**：Q13 R1–R3 `insufficient_proceeds`（引擎正当拒绝：分析师写 `buy TLT weight 0.5`，所得只是所需 2.4%）——用户的"全部所得"在交易语法里没有词；Q19 R1/R2 背后：AWS 分段收入只在段落表格里，`calc` 拒 `not_a_quantity`，没有把段落里的数变成 quantity 的动词，分析师只好自己写 $37.587 billion（段落写的是 $37,587）→ unsourced | **tool 表达力**：scenario 缺"有多少买多少"；段落表格里的数无法成为可算的行 |
| M5 | 分析师：交 brief | 行 + 缺席行 | `submit.brief.lines[{n, settled, finding+facts \| why+boundary}]` → handoff verdict（`problems[{n, reason, way_out}]`） | **16**：括号纪律 13（`unpointed_figure` Q02 R2/R3——数在账本上没带括号；`unsourced_figure` Q07 R1 心算比值、Q19 单位改写；`id_in_prose` Q08 ×4、Q18 ×4；`mark_mismatch` Q19 ×2），边界指错 2（Q01 R3 指了数据行 `not_a_boundary`，Q06 R2 `measure_mismatch`），最后一次 brief 丢行 1（Q20 R1 的 L2/L3）。48 个任务 31 个交了两次，其中 21 个第二次仍被拒 | **LLM（mini）的书写**——模型变量，sol 臂可分离；validation 判得对。其中 Q19 的根在 M4 |
| M6 | 状态合并 | verdict 逐行 + 缺席行 reason | findings / gaps（`GAP_OF_REASON`）/ 要求状态 | 55 个缺口里 **6 个类型记错**：`cannot` 族被记成 execution_failed（永不关闭）——`insufficient_observations` 2（Q06 R1：beta 要 60 个观测）、`incomplete_cover` 1（Q10 R2：total_debt 组件不齐），这些是方法/数据边界；反向：`no_such_name`（unknown_name）2 与 `unknown_portfolio` 1 被记成 data_missing（可关闭）——分析师叫错行名/主体被当成桌子的数据缺席，Q08 R5、Q18 R5 就是这样关成 boundary 的 | **validation 层的映射表**用错误码族判类型，"cannot" 里混着方法边界与执行失败，"no_such_name" 里混着数据缺席与叫错名字 |
| M7 | 主分析师：写回复 | `<state>` 块（要求状态、finding 全文 + 行、缺口 + 边界行）+ ask 回单（tool result，≤28,000 字符） | 回复正文（数字带 `[f_…]`） | **11 条已通过的 finding 没被引用**：Q05 4/4（三条要求全 covered，回复写"没有可引用的行、回单被截断"→ 被覆盖检查退回后以 partial 出去，结尾把三条 covered 的要求列为 Still open）、Q09 4/5（DSO/DIO/DPO 三条序列与 10-K 措辞都在，回复一条没写，结尾把 R1、R3 列为 Still open）、Q06 2、Q07 1。主分析师 prompt 峰值中位 41k 字符、最大 127k（Q02）；Q05 最后一步一次涨 59k | **LLM（mini）读记录**：同一信息走两条载体（回单与状态块），模型盯着回单；**harness 文字**：`_PARTIAL_TEXT` 的 "Still open" 把"没写"说成"没结"，14 篇结尾列的 36 条里 5 条其实已 covered（要过目） |
| M8 | 答案门 | 回复 | 通过 / 句检退回 | 不在这 14 篇（6 次耗尽在 §2） | — |

### 5.2 29 条未解决要求，逐条

| 题 | 要求 | 首断点 | 证据 |
|---|---|---|---|
| Q01 | R3 应收/库存 vs 收入 | M5 边界指错 | 未结行指向数据行 f_bdf511293170 → `not_a_boundary`；前面 2 次 `invalid_params`（余额序列语法） |
| Q02 | R1 总纲 | M1 伞形 | 没有任何行 for 它 |
| Q02 | R2 三个杠杆比 | M5 括号 | 5 行全 `unpointed_figure`（数在账本上） |
| Q02 | R3 10-K 债务措辞 | M5 括号 | 同上（同一任务） |
| Q03 | R1 总纲 | M1 伞形 | 没有任何行 for 它 |
| Q03 | R3 三年变化 | M3 预算 | 16 次调用全成功仍不够（4 用途 × 3 年 × 两个输入） |
| Q06 | R1 30 日波动/beta/距高点 | M6 记错 + M5 | `insufficient_observations` 记成 execution_failed；L2 `unpointed_figure` |
| Q06 | R2 利息费用与税前/净利差 | M5 | `measure_mismatch` ×2、`not_a_boundary`；两条已通过 finding 回复没引 |
| Q06 | R3 银行不适用的方法 | M1 伞形 | 没有行 for 它（回复靠 roster 知识答了，无 finding） |
| Q07 | R1 现金转换排名 | M5（LLM 心算） | 写 "1.0x" 三家相同，账本上没有 → `unsourced` ×3 |
| Q07 | R2 最弱者与权重变化 | M3 预算 | `unknown_name` ×4 后 16 次用尽 |
| Q08 | R1–R4 capex 强度/ROIC/三年/谁最高 | M5 | 第二个 issuer 任务三行全 `id_in_prose`（第一个任务只交了边界） |
| Q09 | R2 周期对三年高低 | M3 语法 → M5 | `window: '3y'` 不在 [1m,3m,6m,1y]；分析师把这条拒绝当边界 |
| Q10 | R1 总纲 | M1 伞形 | 没有行 for 它 |
| Q10 | R2 五年债务序列 | M6 记错 + M3 | `incomplete_cover` 记成 execution_failed；L3 `net_debt_to_ebitda` 缺 window |
| Q12 | R1 三家 ROE/权益乘数 | M3 预算 | `invalid_params` ×6 + `not_held` ×4（BAC/GS 未准备）后用尽 |
| Q13 | R1–R3 卖 NVDA 换 TLT | M4 交易语法 | `insufficient_proceeds`：weight 0.5 vs 所得 2.4% |
| Q18 | R1–R4 归因对账 | M5 | 一个 risk 任务三行 `id_in_prose` + `unpointed_figure` |
| Q19 | R1 AWS 份额 | M4 → M5 | 段落数字不能算；分析师改写单位 → `unsourced`、`mark_mismatch` |
| Q19 | R2 三年变化 | M4 → M5 | 同上 |
| Q20 | R1 明年利润率 | M5 | 最后一次 brief 丢了 L2/L3（前面 `series_not_derivable` ×2：LLY 无 gross_profit 科目） |

### 5.3 按源头计数

| 源头 | 要求数 / 29 | 角色 |
|---|---|---|
| M5 分析师书写（括号、裸 id、心算、边界指错、丢行） | 16 | LLM（模型变量） |
| M3 工具语法 + 16 次调用预算 | 5 | tool 边界 + harness 预算 |
| M1 伞形要求（无路可关） | 4 | validation 越界：要 LLM 的结论也拿一行证据 |
| M4 工具表达力（交易"全部所得"、段落数字不可算） | 3（+Q19 的 2 条根在此） | tool |
| M6 缺席 reason → 缺口类型记错 | 1（另 5 处影响类型，含 2 条误关成 boundary） | validation 映射表 |

再加主分析师侧不产生 unresolved 但直接决定读者拿到什么的 M7：11 条已通过 finding 没写进回复，结尾误报 5 条"未结"。

### 5.4 修在哪个模块（不动模型文字的先做；动文字的过目）

- M1/validation：要求允许由回复自身结清（总纲类），或 `parse_requirements` 只收交付项 anchor——这是 P3 契约的补丁，要拍板。
- M6/validation：`GAP_OF_REASON` 按具体错误码而不是 reason 族：`insufficient_observations`、`incomplete_cover`、`series_not_derivable` → method_unsupported/data_missing；`unknown_name`、`unknown_portfolio` → execution_failed（叫错名字不是桌子缺数据）。纯映射表，无模型文字。
- M7/harness：`_PARTIAL_TEXT` 分开"未结"与"已结未写"（文字，要过目）；ask 回单与状态块两份同信息——考虑回单只给行 id、正文只在状态块（结构改动，拍板）。
- M3/tool：期间与窗口语法收成一种；`book_read` 行名缺席的出路句列出表里有什么行；预算按题的名字数 × 期数给，或加批量算术（P4-2）。
- M4/tool：scenario 加"全部所得"；段落表格里的数进 quantity 的路径（这一条大）。
- M5：模型变量，先跑 sol 臂再说。
