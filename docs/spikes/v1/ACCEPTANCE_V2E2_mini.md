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
