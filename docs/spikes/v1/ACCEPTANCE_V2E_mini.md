# V2E_mini 实测记录：desk-v2-wip 全 gpt-5.4-mini 一臂，20 题 + 跨族 8 段（2026-09-29）

> **被测的**：`desk-v2-wip` HEAD `e3a450f`（树 `25a9625`）= 远端 `83ffa79`（评审修复）+ 一个只重渲染措辞单的提交（引号差异，模型文字无变化）。离线 3085 passed / 10 skipped。
> **过目门**：P1/P2b/P3/P4 与 83ffa79 改动的模型文字均**未过目**；本轮按 boss 9/29 指示"开始做实例测试"跑在草稿措辞上，run log 已记。
> **条件**：`docs/spikes/v1/tools/phase_e.sh V2E_mini` 一键：credit 探针 → 冻结 → `battery_fixture.sh restore backups/battery/battery-2026-09-13.sql.gz` → v36_actor / v36_analyst_reports / v39_fact_means / v40_analysis_state 四个迁移 + v5 remap → 面 `:8105`（issuer 8 / market 5 / risk 6 / research 10 / meta 11）→ 20 题 concurrency 5 → X 系列 concurrency 4 → 取证 → 冻结检查。`--deny submit_brief`，owner `user_3IDBMeAxLTbecvGorzwV7FCeroR`。全程 03:04:40–03:10:54。
> **模型**：lead 98 次 completion、analysts 314 次，全部由 `gpt-5.4-mini-2026-03-17` 应答（X 系列 45 / 117）。
> **实测期冻结代码**：开跑前后 HEAD/树哈希相同，`git status --porcelain --untracked-files=no` 为空，`find src tests scripts -newermt <HEAD 提交时间>` 无输出；untracked 只有本轮 14 个产物文件。跑的过程中遇到的错误只记录，没有改一行代码。
> **强模型臂没跑**：探针实测 gpt-5.6-sol 在 `/v1/chat/completions` 带函数工具仍要求 `reasoning_effort="none"`（否则 400），当前 client 不设该参数，要像 V37C_sol 那样用不改树的包装脚本；待拍板。E 基线臂（`fe8a447`）也未跑。
> **文件**：`V2E_mini.json` / `V2E_mini_X.json` 轮次；`*_forensics.txt` 沟通表与当步账本重放；`*_schema.md` 每种载体的真实载荷；`*_counters.txt/json`；`*_answers.txt`；`*_audit.txt`；`V2E_mini_run.log`。

## 0. 一眼看完

| | V37C（mini） | V37C（sol） | **V2E_mini（本轮）** |
|---|---|---|---|
| 出答案 / 20 | 13 | 18 | **10** |
| 门耗尽 / 轮内崩溃 | 6 / 1 | 2 / 0 | **10 / 0** |
| 出答案里 completed / completed_with_boundaries / partial | — | — | 1 / 3 / 6 |
| 分析师覆盖 asked → done（占比） | 135 → 72（0.53） | 154 → 83（0.54） | **146 → 34（0.23）** |
| 分析师任务数；空返 / 预算停止 | 35 | 59 | 46；26 / 6 |
| submit 被拒 / submit | 43 / 56 | 61 / 100 | 45 / 69 |
| 主分析师 ask 被拒 | 2 | 0 | **21** |
| 分析师工具调用被拒占比 | — | — | 101 / 409（0.28） |
| 每题 prompt token 合计中位 | 120.5k | 164k | **194k** |
| 主分析师 prompt 峰值中位 | 8.9k | 10.0k | 13.9k |
| 分析师 completion 合计 | 182 | 254 | 314 |
| 每题用时中位 | 39s | 129s | 38s |
| 主分析师 read_reports / open | 7 / — | 3 / — | **0 / 13** |
| X 系列出答案 / 9 | — | — | 3 |

**V2 这一臂没有过线，而且不能当 V2 的成绩读。** 三件事把这一轮的读数压住了，两件是运行时的（一件是评审修复带进来的缺陷，一件是回合控制与新退回类型不匹配），一件是夹具的（没有 worker）。把它们分开之后，剩下的才是设计要量的东西（小模型的工具语法与括号纪律、跨族转手）。

## 1. 运行时缺陷：date 进 JSONB，状态与报告都写不进库（83ffa79 引入）

- **现象**：run log 里 108 次 `could not save the analysis state`、48 次 `could not store the record`，全是 `TypeError: Object of type date is not JSON serializable`（经 SQLAlchemy `StatementError`）。两处：`meta_agent._save_state → analysis_state.save`（INSERT `analysis_state`）与 `sub_analyst._store_report → analyst_reports.store`（INSERT `analyst_reports`）。两处都被 `except Exception: logger.exception(...)` 接住，turn 继续。
- **来源**：`services/analysis_state.py:100–118 scope_of()`（83ffa79）把 briefing 目录里的 `portfolios[*].runs / positions_as_of` 与 `issuers[*].latest_period_end / filings / prices` 深拷贝进 `scope.snapshots`；目录里这些是 `datetime.date`（`portfolio_service.py:702` 直接放 `as_of_date`）。同文件 `_signature()` 用 `default=str` 做哈希，说明作者知道里面有 date，但存库那条路没转。分析师报告的 `input_version` / `accepted_lines[*].validation` 也内嵌同一个 `scope_of(...)`，所以一起坏。
- **为什么离线 3085 绿**：`tests/test_v2_review_regressions.py` 把 DB transport 换掉、`latest_period_end` 用字符串喂；没有一条测试把真实目录行经 JSONB 列写出去。
- **影响**：20 题里 14 题 `state_version=0`（凡 briefing 含书的 turn 都存不下），46 个分析师任务只落库 13 份报告（`report` 步 13）。P2 的 `<prior>`、`follow_up_of` 读上一任务的记录、`open(rep_…)`（本轮 read_reports 0）这些机制**在这一轮没有被测到**。同主体的 6 题（Q03/Q04/Q05/Q09/X08-t2 等）scope 无书时能存（version 4–8），说明其余逻辑本身能跑。
- **角色判断**：service 层的实现缺陷，不是角色越界；越界的是验收——"可追溯"这条 validation 职责（状态与记录落库）没有任何离线测试证明，评审修复在 mock 上通过就推了。修法：`scope_of` 出口只放 ISO 字符串（或 `_fields()` 统一序列化），加一条"真实目录行 → `json.dumps(_fields(state))`"的测试。**本轮没改。**

## 2. 覆盖退回吃掉了修复机会：10 次耗尽里 7 次与它有关

10 个耗尽 turn 的退回序列：

| 形状 | 题 | 次数 |
|---|---|---|
| 覆盖退回在前，第二次回复撞句检 | Q07、Q09、Q12、Q17、Q20 | 5 |
| 句检退回在前，repair 通过句检，覆盖退回把它结束 | Q01、Q10 | 2 |
| 两次都是句检 | Q02（unpointed×2）、Q04（unsourced×2）、Q11（mark_mismatch×2） | 3 |

- **机制**：`MAX_ANSWER_ATTEMPTS = 2`（V1 基线 6d40614 就是 2）。P3 加了 `requirement_unaddressed`（回复的句子全过，但有要求既无 finding 也无边界被回复指到），并让它 `attempts += 1`。文本回复路径有守卫 `attempts < MAX_ANSWER_ATTEMPTS - 1`（覆盖退回只在还剩一次时发生，第二次放行为 partial）；**`repair_answer` 路径（meta_agent.py:576–591）没有这个守卫**——句检退回（attempts=1）→ repair 通过句检 → 覆盖退回（attempts=2）→ `attempts >= MAX` → 耗尽。Q01 第 46 步的文本每句都通过了检查、写明"issuer 分析师没有返回逐季数据，只能给仓位读数"，读者拿到的却是"我无法给出答案"。
- 覆盖退回在前的 5 题，主分析师用最后一次机会重写整篇，再撞 `unverified_quote`（4 次）或 `id_in_prose`（1 次）；V1 基线下它本有两次句检机会。
- **角色判断**：validation 判的是结构（要求有没有被回复触及），没越界；越界的是 harness 的回合控制——把"结构退回"按"句子退回"计费，且两条路径不一致，违反 P3 自己写的"退回一次后 partial"。修法在 harness、不动模型文字：覆盖退回不计入句子尝试；repair 路径加同一守卫。**本轮没改。**
- 另一处结构性后果：`unaddressed()` 规定带 `execution_failed` 缺口的要求永远关不上（评审修复"执行失败不能改名成边界"）。这条是设计意图，但它意味着只要一位分析师有一行没交（见 §3），该题上限就是 partial。

## 3. 分析师把预算花在学工具语法与括号纪律上，账本上已有的行没交付

- **工具调用**：409 次，101 次被拒（0.28）。按码：`invalid_params` 35、`unknown_name` 16、`not_held` 9、`metric_not_filed` 6、`not_alone` 5、`input_unavailable` 5、`withheld` 4、`series_not_derivable` 4、`run_not_completed` 3、其余 ≤3；另有 14 次在 schema 门被拒（`invalid arguments: 1 problem(s)`，trace 里没记模型看到的问题文字——仪器缺口）。
- **`invalid_params` 全是期间语法**，缺席行的出路句把规则说了一遍，每次一个 completion：`metric(name, last_n=8)` 无 period →"ask it with {"fy":"latest"} or {"quarter":"latest"}"；`filings_read(accounts_receivable, period={quarter:latest}, last_n=8)` →"a balance's series is its last 8 filed dates: ask it with {"at":"latest"} or no period"；schema 门拒的是 `metric(name="net_income"|"pretax_income", …)`（科目名不是登记簿度量名，该走 filings_read）与 `period={"ttm_to":"latest"}`（ttm_to 收日期）。Q01 的 issuer 分析师 17 次调用里 6 次是这类，等它学会时预算已到第 9 个 completion，最后一步 `submit` 只带 `task_id`（"the analyst stopped without filing a brief"）→ 任务 refused → 4 条要求 unresolved；而它拉到的 8 季 OCF/NI/revenue/accruals 序列都在账本上（31 条事实）。
- **handoff**：submit 69 次、被拒 45 次；问题 220 条里规则 1（每个数字带方括号、id 不裸写）143 条：`id_in_prose` 53、`unpointed_figure` 35、`unsourced_figure` 30；其余 `not_a_boundary` 8、`mark_mismatch` 7、`superlative_without_rank` 5、`measure_mismatch` 5、`not_on_ledger` 6、`date_expected` 4。
- **结果**：46 个任务里 settled 4、partial 20、unsettled 14、refused 8；`tasks_returned_empty` 26，预算停止 6；拉到了行却未交付的任务 22 个。`mark_delivery_missing` 会把这些行作为缺口告诉主分析师，但主分析师 20 题只 `open` 了 13 次（r_ 4、tsk_ 5、f_ 4），每题 completion 中位 5（上限 16），它选择重写回复而不是去开账本。
- **角色判断**：validation 的规则 1 没越界（它只判指向）；LLM（mini）的书写纪律是模型变量，sol 臂能把它分离出来。**越界的是 tool 层**：期间语法（fy / quarter / ttm_to / at）、余额与流量的差别、度量名与科目名的差别是工具的内部结构，现在要模型记住并靠拒绝逐个学——"tool 让 LLM 能执行它想做的事"没做到。修法方向（待拍板，不是 fallback 补丁）：把期间收成一种由行的种类推出的类型化期间，让 `last_n=8` 这种显然的意图一次表达；`metric` 收到科目名时的出路句已点名 filings_read，可看它是否被读到。
- 主分析师 `ask` 被拒 21 次：13 次"requirements are declared once, on the first ask"（后续 ask 又带了 requirements），4 次"tasks[0] says which requirement(s) it is for"，其余是 `for` 形状。相同的重复声明被拒是形式判断不是正确性判断，可机械化（相同则接受），不动模型文字。

## 4. 夹具没有 worker：`start` / `scenario` 的 run 永远 pending

`start` 调用 50 次（issuer 36、risk 5、market 9），`run_not_completed` 3、X 系列 `not_run` 2。Q13（scenario 卖 NVDA 买 TLT）、Q15（流动性表要新 run）、Q14（风险 run 的回撤行）、X07、X08 在这个夹具上本来就到不了终点——生产 worker 容器绑的是生产库，`exposure_battery` 没有 worker。这是 phase_e.sh 的测量边界，不是桌子的；V37C 的条件相同。修法：给 fixture 起一个绑 `exposure_battery` 的 worker，或 `--deny start,scenario` 让边界显式。

## 5. Q01 沟通表（按节点；全文见 `V2E_mini_forensics.txt` 第 1–90 行）

| 步 | 方向 | 载体 | 内容 |
|---|---|---|---|
| 2 | meta → sub:issuer+risk | ask | issuer [AMZN] 4 行（8 季 OCF/NI、accruals、应收/库存 vs 收入）；risk [port_001] 3 行 |
| 4–25 | sub:issuer → tools | 17 次调用 | 4 次 `invalid_params`（period 语法）、2 次 `not_a_series`；8 季 OCF、NI、revenue、accruals 最终都拉到 |
| 27、30 | sub:issuer → ledger | boundaries | 铸 2 条边界行 |
| 28–29 | ctx · sub:issuer | completion | 各 3 个输出 token、0 调用（预算末） |
| 31 | sub:issuer → check | submit（只带 task_id） | **rejected：stopped without filing a brief** |
| 33–41 | sub:risk → tools | 4 次调用 | 权重 7.03%、市值、上一 run 7.07% |
| 42 | sub:risk → check | submit | 2/3 settled；第 3 行指 `f_policy_no_forecast` |
| 44 | meta → gate | answer | rejected：`measure_mismatch`（"accruals ratio" 旁边的数字是权重） |
| 46 | meta → gate | repair 后 answer | 句检全过；**rejected：`requirement_unaddressed` R1–R5**（attempts=2 → 耗尽） |

往返：meta→gate 2、meta→analysts 1、issuer→tools 17、risk→tools 4、issuer→check 1、risk→check 1；completion meta 3 · issuer 9 · risk 6。

## 6. 按原始 65 项要求（评审矩阵 `acceptance_matrix.draft.json`）——**运行时自报，不是独立 oracle**

主分析师自己声明了 73 项（矩阵 65 项；Q13 声明 6 项对矩阵 4 项、Q14 只声明 1 项对矩阵 4 项——声明粒度与矩阵不一致，要在 P0b 转换 schema 时对齐）。按运行时状态：covered 8、boundary 21、unresolved 44。逐题：

| 题 | 结果 | completion | 矩阵 | 声明 | covered | boundary | unresolved |
|---|---|---|---|---|---|---|---|
| Q01 | 耗尽 | partial | 4 | 5 | 0 | 1 | 4 |
| Q02 | 耗尽 | partial | 3 | 4 | 0 | 0 | 4 |
| Q03 | 答 | completed_with_boundaries | 3 | 4 | 3 | 1 | 0 |
| Q04 | 耗尽 | partial | 4 | 6 | 0 | 2 | 4 |
| Q05 | 答 | partial | 3 | 3 | 0 | 0 | 3 |
| Q06 | 答 | partial | 3 | 4 | 1 | 0 | 3 |
| Q07 | 耗尽 | partial | 4 | 4 | 0 | 0 | 4 |
| Q08 | 答 | partial | 3 | 3 | 0 | 1 | 2 |
| Q09 | 耗尽 | partial | 3 | 3 | 0 | 1 | 2 |
| Q10 | 耗尽 | partial | 3 | 3 | 0 | 1 | 2 |
| Q11 | 耗尽 | partial | 3 | 4 | 0 | 0 | 4 |
| Q12 | 耗尽 | partial | 3 | 3 | 1 | 2 | 0 |
| Q13 | 答 | partial | 4 | 6 | 0 | 0 | 6 |
| Q14 | 答 | completed | 4 | 1 | 1 | 0 | 0 |
| Q15 | 答 | partial | 3 | 4 | 0 | 1 | 3 |
| Q16 | 答 | completed_with_boundaries | 3 | 5 | 1 | 4 | 0 |
| Q17 | 耗尽 | partial | 3 | 2 | 0 | 2 | 0 |
| Q18 | 答 | completed_with_boundaries | 3 | 5 | 0 | 5 | 0 |
| Q19 | 答 | partial | 3 | 3 | 1 | 0 | 2 |
| Q20 | 耗尽 | partial | 3 | 1 | 0 | 0 | 1 |

出去的 10 篇答案里没有做独立数值核对（P0b 的 gold_v1 未建）。一处读者会被误导的写法：Q19 把 10-K Item 8 表格里的 AWS 净销售写成 "$90,757"（表的单位是百万），数字与出处一致、单位没跟着走。

## 7. X 系列（跨族 8 段 9 回合）

3 答 / 6 耗尽。转手读数：up_front 3（X01、X02、X06）、carried 2（X03、X05）、shotgun 1（X04）、not_carried 1（X07）、wrong_name 1（X08-t2）；`in_sequence` 只有 X05 一段。计划步骤 7 的决策规则（in_sequence 是否明显更贵/更常失败）**这一轮读不出来**：6 次耗尽都是 §2/§3 的形状（X01/X02/X04/X08 覆盖退回 + 句检；X06 direction_conflict×2；X07 unpointed + measure_mismatch），转手还没轮到起作用。X08 第二回合 8 秒 1 次调用就答（读到上一回合铸的边界行）——跨回合走的是账本，不是 analysis_state（它没存下来）。

## 8. 这一轮之后

- **不改代码的前提下能做的**：强模型臂（需要 reasoning_effort 包装，待拍板）；E 基线臂 `fe8a447`（同一 phase_e.sh，从 worktree 起）。
- **要改代码才能再测 V2 的**（都不动模型文字）：§1 date 序列化 + 真 JSONB 测试；§2 覆盖退回不计句子尝试、repair 路径同守卫；§4 夹具 worker 或显式 deny。
- **拍板项**：§3 期间语法收成一种（tool 层）；ask 重复声明的处理；P0b 声明粒度与矩阵对齐；是否给分析师"预算尽时交已通过的行"的出路。
- 本轮产物未提交；`e3a450f` 未推送。
