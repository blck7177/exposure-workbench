# IMPLEMENTATION PLAN V2 — 分析状态、可恢复交接与确定性边界（2026-09-28，草稿）

> 依据：`dev_note/exposure/architecture-and-repair-plan.md` v0.4（2026-09-27，"基于 origin/desk-v1 的修订设计稿"，下称「设计」）。设计审的是 `b4f979f`；本计划的起点是 `desk-v1@6d40614`，比它多两个提交：`f34b54d`（V1 步骤 6，风格指南单源，措辞 A–F 已过目）与 `6d40614`（V1 步骤 7 的跨族系列与仪器）。这两个提交分别关掉了设计 G8 的前半句，并给了 P0 要用的仪器。设计要求"为完整取证先改仪器，须单独提交并记录新基线"——这一条已经照做。
> 状态：待 boss 拍板后执行；未实施；本文不代表已有能力。
> 读法：每个工作包一组提交、一个机械验收；实测期冻结代码（phase_e.sh 有 tracked 改动即拒绝测量）；按节点沟通表分析；发给模型的文字改动一律走措辞过目（§5 单列）。V1 计划 `docs/IMPLEMENTATION_PLAN_V1.md` 继续作为步骤 1–7 的执行记录；它的步骤 7（E 轮）就是本计划的 P0。

## 0. 一句话，与不变量

**一句话**：在 V1 的四角色边界不动的前提下，给主分析师一份由 runtime 投影出来的分析状态（要求、发现、缺口、任务、预算），让交接与读取契约不再静默丢东西，让所有模型写出的事实性文字走同一道确定性检查，然后用冻结 E 轮和三轮 20 题验收。

**设计已定、不留给实验的三条边界**（设计 §01、§05、§13）：
1. 语义 reviewer 只做离线测量，不进入运行时：不放行、不阻断、不路由修复、不改状态、不回填 context，不按类别或阈值启用。
2. lease 保持 V2-E：`TASK_LEASE_SECONDS=1800`、`TURN_LEASE_SECONDS=900`，不续期、不心跳、不新增写入 fencing，`parallel_analysts=False` 不动。
3. 模型写入的一切分析状态文字（结论、假设的事实前提、反驳摘要、冲突描述、缺口原因、caveat、why、follow_up）与 finding 共用同一个确定性检查入口；candidate / hypothesis / unverified 标签不豁免；未通过的原文只进审计，不进状态、不进摘要、不进后续 turn 的 context。

**V1 不变量继续有效**：工具是资源动词不是报表；主分析师不持面（ask、open、repair_answer 三件事）；三位分析师按资源族裁面；登记簿是数值、单位、来源、方法的唯一权威；日志由 why 长出，不另写报告；不恢复 compiler、digest、14 域；不加 fallback，不在 LLM 路径上打规则补丁；模型不给度量起名。

## 1. 设计里已定的决定（作为前提）

| 来源 | 决定 |
|---|---|
| 设计 §03 | 主分析师、三位分析师、12 动词（含进程内 submit，各面 9/6/7）、登记簿、手册、8 字段事实、两态交接、why 日志、类型化期间、PostgreSQL 持久化全部保留；"合并 brief/report"不再安排 |
| 设计 §05 | 迭代能力放进现有主循环，不加控制 agent；Redis 不作前置；Runtime 从现有 harness 渐进抽取，不是新进程；"主 agent 直调高层工具"不默认实施，E 轮有证据再单独实验 |
| 设计 §07 | 第一阶段只做三个逻辑对象：AnalysisPlan/WorkState、TaskState、Result/Delivery index；复用其余存储；不建事件平台、不建跨任务知识库 |
| 设计 §08 | 沿用 ask / submit / open；ask 可加要求关联与 scope 引用；是否新增"计划更新接口"在最小切片里决定；open 要能完整可恢复地读 |
| 设计 §09 | 保留"工具描述资源操作、手册描述如何分析"的边界；Q13 再配置是能力差距不是 bug；Q20 不把删政策当 bugfix；Q10/Q13 的 withheld 不直接解除 |
| 设计 §10 | 运行时验证保持确定性；不引入模型填写的第二套 claims DSL；风格指南单源补完（已由 f34b54d 完成） |
| 设计 §11 | 顺序 P0 → P1 → P2 → P3 → P4 → P5 → P6；P1/P4 可按阻塞提前；P2/P3 从 Q16 切片开始，再 Q04、Q13；P2 依赖 P1 的共用事实边界先可用 |
| 设计 §12 | 发布门槛：候选配置连续 3 轮、每轮 20/20 满足预登记要求；新增约束的验收 A1–A5 与 20 题评分分开记 |
| V1 §5（9/19 拍板，仍有效） | 报表不是工具；program_service 退役；D 轮不跑；K5 stash 不动；scenario 现行语义（卖出所得离开书、买入资金来自书外、已持有不再买）是拍过的——设计 G5 要求重新定义，见 §6 待拍板 |

## 2. 现状核查：设计的每一项在 6d40614 上是什么

设计 §04 的九个缺口，逐条对源码。"状态"是相对 6d40614 说的。

| 缺口 | 代码现状（文件:行） | 状态 |
|---|---|---|
| G1 caveats / why / follow_ups 不受同等检查 | `agents/delegation.py` `handoff_check`：只有 settled 行的 `finding` 过 `answer_check.check`（:330）；caveat 只查 `line` 在 1..n（:341–343）；`why` 与 `follow_ups` 文本不检查。`for_lead` 把 caveats 原文附在行旁（:407–411）；`sub_analyst._store_report` 把 `caveats`、`not_done.why`、`follow_ups` 原文存进 `analyst_reports.brief`（:414–416）；`apps/web/app/components/analyst/Reports.tsx` 把 `brief.caveats` 与 `not_done.why` 原文渲染给读者（:97–98、:158–160） | 成立 |
| G2 修复协议不保留正确行 | `delegation.refusal_message` 对分析师说 "Every entry not named here is kept"（:355）；`sub_analyst._fill` 用新 brief 整体覆盖 `result.lines`（:367）；两次机会用完即 `done`。分析师若只重交被点名的行，C1 判 `uncovered_line`，上次通过的行随之丢失 | 成立，提示与代码不一致 |
| G3 open 结果静默不完整 | `agents/meta_agent._open`：`r_` / `calc_` 返回 `rows[:80]`，无总数、无范围、无翻页（:204）；`open` 的 schema 只有 `id`（delegation.py `OPEN_TOOL`）。另：`services/facts.value_of` 对 series 只显示 `_thin` 后的 60 点，行上不说"显示 k 点 / 共 n 点"（`when_of` 只给总点数） | 成立 |
| G4 无持久分析状态；follow_up_of 不恢复 | 主分析师的 `delegated` 是本轮局部变量（meta_agent.py:361）；`_load_history` 只带 agent_messages 正文，无 `[f_…]`；`follow_up_of` 只随 `Task.as_dict()` 进分析师 prompt（delegation.py:158），程序不按它加载任何东西 | 成立 |
| G5 Q13 超出情景语义 | `services/scenario_service.hypothetical_trades`：`{sell}` 与 `{buy}` 列表按序应用；`reads_as` 明写"sale proceeds leave the book and purchase money comes from outside it"；`tools/primitives.py:724–725` 明写拒绝 "a name already held bought again"；demo 书持有 TLT（`configs/demo_portfolios.yaml:72`），所以"卖 NVDA 买 TLT"在现行语义下被正确拒绝 | 成立，是 9/19 拍板的语义 |
| G6 风险经理不用 book.analysis | V1 §5 第 1 条同一件事；6d40614 的 `battery_counters.py` 已能按分析师 × 动词计数 | 成立，待 E 轮量 |
| G7 取证截断 | `scripts/conversation_battery.py:26` `_ARGS_CAP, _RESULT_CAP = 4000, 1000`（导出 JSON 时 `left()`）；`services/trace_service.py` 每个字符串参数 4096、summary 2000；`meta_agent._record_answer` 只存 `text[:4000]`（:266）；被拒的回复草稿只存在 answer step 里。异常路径：`apps/api/routes/agent.py` 的 503/413 不写 assistant 消息，`message_id` 不返回给调用方，电池无法把该轮的 steps 关联到一条消息 | 成立 |
| G8 风格指南未落地；语义质量测量不足 | 前半句已由 `f34b54d` 关掉：`services/style_guide.py` 八条、`rule_of`、两份角色说明各引入一次、拒绝带 rule 号，`tests/test_v1_style_guide.py` 42 条；后半句（离线标注评测）没有任何东西 | 前半已关，后半成立 |
| G9 逐题能力清单 | 与 V1 §5 第 6、7、8 条及代办重合；未逐项审计 | 待审计 |

设计引用的其他事实核对：`b4f979f` 提交记录 2926 passed ✓；天数按窗口在 V38 `297a436` 改（`analytics/formulas.py:221` "days in the window (365 for twelve months)"）✓；XOM 长期债务读进总债务同一提交 ✓；`calc` 的 `factor` 是裸 number（primitives.py:684），`filter` 的 `level` 也收裸数字 ✓；lease 不续期是刻意设计（settings.py:96、agent_session_service.py:92）✓；`ejson.dumps_capped` 截断时在 `truncated` 字段说明丢了什么（utils/json.py:83–123）✓；E 轮脚本 `docs/spikes/v1/tools/phase_e.sh` 依赖 `docs/spikes/v37/tools/{credit_probe,v37c_audit}.py` 均在 ✓。

设计写"隔离复核四项"的附件在评审者本机；上表是按源码独立重推的结果，结论相同。

## 3. 工作包

顺序按设计 §11：P0 → P1 → P2 → P3 → P4 → P5 → P6。每个包写四样：改什么（落点到函数）、不改什么、机械验收、发给模型的文字改动（走 §5 过目）。"拍板"标记的项在 §6 汇总，开工前要定。

### P0 · 冻结 E 轮与完整取证（基线 `6d40614`）

设计 §11："锁定最新基线、补完整取证和独立规格，运行冻结 E 轮；P0 先记录未改行为的 baseline；如果为完整取证先改仪器，单独提交并记录新基线。"

**P0a · 仪器提交（一个提交，提交后的哈希就是 E 轮基线）**——只动取证，不动模型看到的任何东西：

1. 电池导出不截断：`scripts/conversation_battery.py:26` 的 `_ARGS_CAP, _RESULT_CAP = 4000, 1000` 改为与存储同宽（trace_service 每个字符串参数 4096、summary 2000），导出的 JSON 与 `agent_steps` 逐字一致；`v36_forensics.py` 与 `battery_counters.py` 本来读库，不受影响。
2. 被拒的回复草稿全文入 trace：`meta_agent._record_answer` 的 `text[:4000]` 与 `trace_service.bound_args` 的 4096 让长草稿被切。改法：`record_step` 增加 `unbounded: tuple[str, ...]` 参数，只有 answer step 的 `text` 键免于 `bound_args`；其余步骤照旧。被接受的正文本来就在 `agent_messages.content` 里全文保存，不动。（拍板：接受草稿全文入库带来的行宽。）
3. 异常路径保留关联：`apps/api/routes/agent.py` 的 503（ToolFaceUnavailable）、413（provider context）与 500 现在不写任何消息，`message_id` 也不返回，电池无法把那一轮的 steps 归到一条消息。改法：`message_id` 在路由铸出并传入 `handle_message`（签名加一个参数）；异常时写一行 `agent_steps`（`step_type="turn_error"`，status `error`，args `{"error": <code>}`，带 message_id），错误体带 `message_id`。**不写 assistant 消息**——那条"文字不过门不到读者"的规则不动。
4. `docs/spikes/v1/tools/phase_e.sh` 的 FREEZE 段把基线哈希写进 run log 已有；加一行记录 `git describe --always` 与本包的哈希对照。

验收：三处各一条离线测试（导出宽度等于存储宽度；answer step 存全文、其他步骤仍受 4096 约束；503 路径落 `turn_error` 步并返回 message_id）；`scripts/v1_wording.py --check` 通过且措辞单无差异（本包不改模型文字）；离线套件绿。

**P0b · 独立规格与数值 oracle（不依赖 P0a，可并行）**：

1. 验收矩阵进仓库：`docs/spikes/v1/acceptance_matrix.json`，20 题 × 65 项要求，每项 `{question_id, requirement_id, anchor（用户原文片段）, deliverable, constraints{subject, period, method}, prelabel}`，`prelabel ∈ {supported, implementation_gap, data_missing, method_boundary, policy}`。来源是评审者本机的 `test-acceptance-matrix.json`（拍板：请评审者交付；仓库里没有）。设计 §12 要求 prelabel 在评分前填好；`policy` 与 `method_boundary` 只有经确认才可作为允许输出。
2. 数值 oracle：`scripts/gold_derive.py v1` → `tests/battery/gold_v1.json`。对矩阵里每一项带数字交付的要求，在 `exposure_gold`（同一快照 + v36/v39 迁移 + v5 remap）上从原始表直接算，不经过工具与登记簿（设计 §10："独立原始数据 oracle 和方法不变量仍然必需"）。现有 `scripts/gold/v24.py` 是形状参考。
3. 逐要求评分脚本：`docs/spikes/v37/tools/v37c_audit.py` 现在按题给 ANSWERED / EXHAUSTED / ERROR；加一个 `scripts/requirement_score.py`，读矛阵、答案、账本与 gold，对每项要求给 `delivered_correct | delivered_wrong | boundary_ok | boundary_unjustified | silent_omission | not_answered`。这是设计 §12 "验收分母使用原始用户要求"的实现。

**P0c · 跑 E（不改代码）**：`phase_e.sh` 两臂：`LEAD_MODEL=<强> ANALYST_MODEL=<弱>` 与反向；每臂先还原 `backups/battery/battery-2026-09-13.sql.gz`（在），跑 v36_actor、v36_analyst_reports、v39_fact_means 三个迁移与 v5 remap，工具面在 :8105，20 题 concurrency 5，X 系列 concurrency 4，`--deny submit_brief`。产物到 `docs/spikes/v1/V1E_*`。分析按节点沟通表（`v36_forensics.py`）与 `battery_counters.py`。

E 轮要为后面的包读出的数（写进 `docs/spikes/v1/ACCEPTANCE_V1E.md`）：

| 读数 | 供哪个包 |
|---|---|
| 第二次 submit 只因 `uncovered_line` 被拒的次数；被拒后丢掉的已通过行数 | P1 G2 的基线 |
| 已存 brief 的 caveats / why / follow_ups 里，按 answer_check 离线复核会被拒的条数 | P1 G1 的暴露面 |
| `open(r_…)` 命中超过 80 行的次数 | P1 G3 |
| 每位分析师 `metric` 对 `book_read`+`calc` 的比、`calc` 里逐对相减的串数 | P4 第 1、2 条 |
| X 系列每题 carried / shotgun / wrong_name / up_front / never_asked / not_carried；`in_sequence` 对 `together` 的成本与结清率 | V1 步骤 7 决策规则（面由任务组合与否） |
| 两臂之间：出答案、假陈述（按矩阵）、拒绝按 rule 号、prompt 峰值 | P0 固定主验收模型 |
| 静默遗漏：矩阵里没有任何交付也没有边界的要求数 | P3 覆盖检查的基线 |

验收：FREEZE CHECK 干净；措辞单 `--check` 通过；`requirement_score.py` 给出 20 题 × 65 项的逐项结果；ACCEPTANCE_V1E.md 写明实际服务的模型（llm_call 行）、迁移、remap、预算。**设计 §01：不能把 V37 的 13/20、18/20 当作当前分支成绩；E 轮之前也不宣称任何当前成绩。**

### P1 · 交接与读取契约（G1、G2、G3、序列化）

设计 §11 P1："修当前交接和证据读取契约；落点 delegation.handoff_check、sub_analyst._fill、meta_agent._open、序列化；完成证据：G1/G2/G3 的真实函数回归、正确行保留、所有结果可定位重读、无事实性旁路。"

**P1.1 · G1 统一事实性通道**（校验层）
- `delegation.handoff_check` 加三条，与 C2 用同一个入口 `answer_check.check(text, ledger, question=task.asked_text())`：C6 每条 caveat 的 `text`（`where=caveats[i]`）；C7 每条 unsettled 的 `why`（`where=line n / why`）；C8 每条 `follow_ups[i]`。follow_up 是问题不是断言，但设计 §07 明写"隐含的事实前提仍受同一边界约束"，一句不含数字、不带引号、不写 id 的 follow_up 本来就零成本通过。
- 未通过的 caveat：不进 `for_lead` 的 `caveats`，不进 `analyst_reports.brief.caveats`，进 `problems`（带 rule 号，`style_guide.ruled`）；未通过的 `why`：该 unsettled 行按 refused 处理，主分析师读到 "did not pass the desk's check"；未通过的 follow_up：删去并进 problems。`_store_report` 的 `brief` 只存通过的。
- `apps/web/app/components/analyst/Reports.tsx` 只渲染通过的 caveats 与 why；未通过的已经在 `problems` 里有位置（拍板：是否保留"显示原文但标为未过检查"的形态；推荐不显示原文）。
- `battery_counters.py`：拒绝按通道计数（finding / caveat / why / follow_up）。
- 验收：`tests/test_v2_boundary_channels.py`——同一句无据事实分别放进 finding、caveat、why、follow_up，reason 码相同；同一句有据事实四处都过（A2 的前半）；变异验证能变红。

**P1.2 · G2 修复契约**（agent 层；拍板：patch 还是整份替换，推荐 patch——提示已经这么承诺，主分析师侧 `repair_answer` 也是 patch）
- `sub_analyst._run`：保留 `kept: dict[int, entry]` = 上一次裁决里没有任何问题的条目（settled 且通过 C2/C3，或 unsettled 且 C4/C7 通过）。第二次 submit：`merged = {**kept, **new}`（同 n 以新为准），`handoff_check(task, merged, ledger)`，`_fill(result, merged, verdict)`；"逐字节相同"判定用 merged 的 digest。
- 同一有效输入版本：一个任务内账本只增不改，事实不可变，kept 条目对当前账本仍成立；跨任务不合并（follow_up_of 是 P2 的事）。
- `delegation.refusal_message` 末句改为只要求重交被点名的条目（措辞 → §5）。
- 验收：只重交失败行 → kept 保留、coverage 按合并后计；重交整份 → 与今天相同；两次机会用完 → 结果含 kept；变异验证。

**P1.3 · G3 open 可恢复读取**（工具层）
- `delegation.OPEN_TOOL` 加 `offset`（integer ≥ 0，默认 0）；`meta_agent._open` 对 `r_` / `calc_` 返回 `{"rows": <80 行一页>, "total": n, "shown": [start, end], "next_offset": …（有则给）}`；`f_` 单行不变；`tsk_` 日志不变。
- 序列行：`services/facts.value_of` 对 series 在 `_thin` 生效时于值后追加 "(k of n points shown; open the row's id for the rest)" 之类的标记；对应 `tests/test_v1_fact_means.py` 与金标准行按"行是存储行的纯函数"更新。`open(f_…)` 对 series 支持 `offset` 分页返回全部点。
- 验收：100 行的一次调用 → `total=100`、两页可读完；90 点序列 → 行上有标记，两次 open 读完全部点；变异验证。
- 措辞：`OPEN_TOOL` 描述与 `offset` 说明；序列行标记文字 → §5。

**P1.4 · 序列化**：`utils/json.dumps_capped` 截断时 `truncated.detail`（`_CAP_DETAIL`）要说出路（"open <r_id> with offset…"），与 P1.3 对齐 → §5。每次 completion 的读入上限（主分析师 28k、分析师 16k/次按调用均分、floor 4k）不动。

P1 完成证据：三组真实函数回归 + 通道测试；`v1_wording.py` 重生成措辞单，第 1.3、9.2、9.3 组新增/改动的句子过目后提交；离线套件绿；`docs/WORDING_V1.md` 的 `--check` 通过。

### P2 · 最小持久状态（WorkState / TaskState / Delivery）

设计 §07："第一阶段优先实现三个逻辑对象，复用其余既有存储；主 agent/分析师提交的是分析状态提案，不是可直接写入的权威记忆；通过事实边界的内容才能成为可投影的分析状态。"设计 §11："P2 对分析文字的持久化依赖 P1 共用事实边界先可用。"

**P2.1 · 表与迁移**（`infra/migrations/v40_analysis_state.sql` + `infra/init.sql` 同步 + `tests/test_rls_parity.py` 加对应断言；RLS 策略与 `facts` 同形，经 `agent_sessions.owner_id`）：
- 新表 `analysis_state`：`id (ast_…)`, `session_id` FK, `message_id`, `version INT`, `question TEXT`（用户原文）, `requirements JSONB`, `scope JSONB`, `findings JSONB`, `gaps JSONB`, `tasks JSONB`, `budget JSONB`, `completion VARCHAR(32)`, `created_at`, `updated_at`；索引 `(session_id, message_id)`。
- `analyst_reports` 加列（TaskState 扩展既有表，设计 §07）：`requirement_ids JSONB`, `input_version JSONB`（`{state_version, ledger_seq}`）, `accepted_lines JSONB`（通过的行原文 + facts/boundary id）, `attempts INT`, `receipts JSONB`（`start` 回执的 task/run id）。
- `agent_steps` 加列 `task_id VARCHAR(64)`：`sub_analyst._record` 直接写；工具调用经 MCP 时 task_id 与 `actor` 同路走请求 meta（`tool_session.call(meta={"actor", "task_id"})` → `mcp_server` 读出 → `registry.invoke(task_id=…)` → `record_step`）。这让 `delegation.log_from_steps` 能分开同一分析师的两个任务（V1 §6 验收"log 由 why 长出"在 `parallel_analysts` 打开前的前提）。
- Delivery index 不建表：`llm_call` 步的 `args`（现在是 `{"read": {"chars", "results"}}`）加 `delivered: {"facts": [f_…], "pulls": [r_…], "rows": k}`，由两个循环的 `_append` 从上一次 completion 以来追加进 messages 的工具/用户内容里收集 `[f_…]` 与 `r_…`。设计 §07："facts/ledger 的存在与某 actor 的实际收到分别记录。"

**P2.2 · 服务 `services/analysis_state.py`**（runtime 的统一写入口；模型不直接写）
- `open_turn(db, session_id, message_id, question, briefing) -> State`：新行 version 1；从本 session 上一条状态继承 scope 仍匹配（主体 ⊆ 本轮 briefing 主体、书相同）的 accepted findings，标 `inherited`；requirements 为空，等 P3 的 ask 声明。
- `propose_text(state, channel, text, ledger, question) -> Verdict`：**模型文字进入状态的唯一入口**，调用 P1 用的同一个 `answer_check.check`。未通过：写一行 `agent_steps`（`step_type="state_proposal"`, status `rejected`, args 含原文与 problems）——只进审计，不进 `analysis_state`（A3）。
- `merge_task(state, task, result, ledger)`：通过的 settled 行 → `findings[{text, refs, requirement_ids(来自 task.for), check_version, status: accepted}]`；unsettled 行 → `gaps[{requirement_ids, type, boundary: f_id, tried: [task_id]}]`，`type` 由边界行的 `means.reason` 机械映射：`not_held / no_such_name / not_prepared → data_missing`；`meaningless / not_comparable → method_unsupported`；`policy → policy_boundary`；`param_out_of_range / cannot / not_on_this_face / analyst_budget → execution_failed`；refused 行 → 不进状态（审计在 `analyst_reports.problems`）。
- `mark_delivery_missing(state, ledger, delivered)`：账本上有、但从未交付给主分析师的行所对应的要求 → gap `delivery_missing`（设计 §06 表第一行"结果在账本但未完整交付"）。
- `conflicts(state, ledger)`：两条 accepted 行同 (measure, subject, 期间键) 而值在展示精度外不同 → gap `evidence_conflict`（查表，无判断）。
- `invalidate(state, new_scope)`：主体/书/as_of 变化 → refs 落在新 scope 之外的 findings 标 `stale`，不再投影（A4）。
- `save(db, state)`：`UPDATE … WHERE version = :expected`，不匹配抛 `StaleState`，调用方重读再合并（设计 §07"事务和分析状态版本检查"，不是 lease、不是 fencing）。
- `view(state, ledger) -> dict`：主分析师读的 AnalysisView（P3 用）：要求与状态、accepted findings 附 `F.line` 行原文、gaps 按类型附边界行、任务（id、分析师、状态、coverage）、剩余预算、`state_version / scope_version`。不含任何被拒文字。

**P2.3 · follow_up_of 真正恢复**（agent 层）：`sub_analyst._run` 若 `task.follow_up_of` 是本 session 的任务，读其 TaskState（`analyst_reports.accepted_lines` + 关联 gaps），以 `<prior source="the desk's record of task tsk_…" use="…">` 块给分析师：通过的行及其账本行原文、缺口及边界行；被拒条目永不进入（A3）。措辞 → §5。

**P2.4 · 历史投影不变**：`_load_history` 仍只带正文；缺的 id 由 P3 的 `<state>` 块提供，不改历史消息（设计 §08："历史消息…必须执行相同投影规则"）。

验收：RLS parity 新行；版本冲突测试；A3（被拒提案不在 view、不在 `<prior>` 块、不在下一轮继承里；打开审计保留 rejected 身份）；A4（scope 变更 → stale 不投影）；映射表测试；离线套件绿；`docs/spikes/v1/tools/phase_e.sh` 的迁移列表加 `v40_analysis_state`。

### P3 · 主分析师按状态推进（Q16 → Q04 → Q13 切片）

设计 §06："要增加的是稳定、可更新的 AnalysisView，让下一步基于明确工作状态；每项 requirement 有一条返回只是结构覆盖，还必须检查它是否回答对应问题；Requirement 分解需对照用户原文核实。"设计 §08："沿用 ask/submit/open；ask 可增加要求关联和 scope 引用；是否新增显式计划更新接口，在最小切片中决定。"

**P3.1 · 要求声明与映射**（拍板：扩展 `ask`，推荐；或新 `plan` 工具）
- `ask` schema 加顶层可选 `requirements: [{id: "R1", anchor: "<用户原话片段>"}]`（本轮尚无要求时才接受），每个任务加 `for: ["R1", …]`（要求存在后必填）。
- 机械核实"对照原文"：每个 `anchor` 必须是用户问题的逐字子串，否则 `invalid_ask`（`BadDelegation`）说明哪一条不在原文里；`R` 号不认识也拒。runtime 把 requirements 写进 `analysis_state.requirements`，状态 `unresolved`。这是设计 §06"不能用 agent 自定清单缩小验收范围"的可机械执行的那一半；语义上是否漏拆由 P0b 的矩阵离线对照。
- 措辞：`ASK_TOOL` 描述与两个新字段说明、`_ROLE` 里加一句"先把问题拆成要求" → §5。

**P3.2 · AnalysisView 进 prompt**
- `<state source="the desk's record of this analysis" use="…">` 块，内容 = `analysis_state.view()`；作为 system 消息放在 `<readings>` 之后，**每次 completion 替换而不追加**（`messages` 里只有一份）。`context_budget.count_prompt` 记它的大小（V3-B0 的观测继续）。措辞 → §5。
- 主分析师循环：每次 `ask` 返回后 `merge_task` + `mark_delivery_missing` + `conflicts` + `save`；`open` 的读取记入 delivered；`repair_answer` 不动。

**P3.3 · 覆盖与完成判断**（校验层）
- 回复草稿先过 `coverage_check(state, cited_ids)`：每项要求要么 `covered`（≥1 条 accepted finding 的行被回复引用），要么 `boundary`（回复引用了该要求某个 gap 的边界行），否则 `requirement_unaddressed`，`way_out` 点出 anchor。问题进同一份 verdict，与 answer_check 的问题一起退回（不带 rule 号：它是覆盖不是写法）。
- 完成状态由 runtime 算并写进 `analysis_state.completion` 与 `agent_messages.meta.completion`：全部 covered → `completed`；有 boundary 无 unresolved → `completed_with_boundaries`；有 unresolved → `partial`。
- partial 的放行规则（拍板）：推荐"第一次退回，第二次若 answer_check 通过则放行并标 partial，runtime 在回复后附一段自己写的、点名未覆盖 anchor 的固定文字"。设计 §06 允许"技术失败、预算用尽和无新进展结束一次运行，但不能自动转换成问题已解决"——partial 正是那个不转换的状态。固定文字是用户读的模板 → §5。
- 主分析师循环的唤醒条件不变（分析师仍在 ask 内运行）。

**P3.4 · 三个切片**（设计 §11："从一个完整切片开始"）
- Q16 当前对前次组合 beta：`ask(risk, for=[R1,R2])` → `book_read(which='prior')` + `metric book.analysis` + `calc subtract` → merge → view 显示两期行与差 → 若行在账本未交付则 `delivery_missing` 促使 `open` → 覆盖检查 → 追问轮"驱动是什么"继承状态；中断（api 进程在 ask 中被杀）→ 900s 后 turn 释放 → 新轮 `open_turn` 继承已 accepted 的行。
- Q04 LLY 利润率归因与 MRK：`start(readiness, MRK)` 回执进 `analyst_reports.receipts`，要求 R(MRK) 落 gap `execution_failed(not_prepared)`，回复 partial 并点名；准备完成后的下一轮继承并补证。
- Q13 卖 NVDA 买 TLT：P4 第 3 条拍板前，切片只证明"正确拒绝 + 要求以边界收场 + 完成状态不是 completed"（设计 §02 的例子）；拍板后再跑再配置。
- 验收：`tests/test_v2_loop_slices.py`，用脚本化 provider（monkeypatch `llm_client.chat_with_tools`）驱动 ask → merge → view → 覆盖退回 → partial 的完整路径；A3、A4 在真实写入与投影路径上再测一次（设计 §12："不能只验证孤立 validator"）。

### P4 · 能力补齐（E 轮之后按数据，每项一提交）

设计 §09 的清单逐项落点。凡改工具描述、手册句、登记簿读法的都是模型文字 → §5。

| # | 设计条目 | 落点 | 动作 | 验收 | 拍板 |
|---|---|---|---|---|---|
| 1 | book.analysis 难发现 | `analytics/registry._BOOK_METHODS`、`handbook.RISK`、`primitives` | 按 E 的 `metric` 选择率决定：拆成 `book.net_exposures` 与 `book.room_to_tiers`（V1 §5-1），或加输出选择参数；不加大报表 | 面上 enum 与手册 §1"Measured by"一致；E2 复测选择率 | E 后 |
| 2 | 逐项算术耗调用 | `primitives._calc` | 按 E 的逐对相减串数决定是否给 `subtract/divide` 的双列表形式（`by` 已支持一列）加逐对模式；不恢复 DSL | 同一题调用数下降、正确性不变 | E 后 |
| 3 | Q13 再配置 | `analytics/scenario.py`、`scenario_service.hypothetical_trades`、`primitives` scenario 描述、`registry.READS` | 定义：买入资金来源 `funding ∈ {external, proceeds}`（默认 external 保持 8b8887b），`buy` 已持有名字 = 增持，原子性（已是），ETF 用 `positions.asset_class` 归类 | 情景金标准行；typed_calculator 书代数 R1–R3 不变 | **是**（是否推翻 9/19 语义） |
| 4 | 行业来源 | `companies.sector`（SIC 码）对 portfolio 的 sector 标签 | 审计脚本列出不一致；要么配置 SIC→行业映射表，要么买入无映射名字时拒绝并说明 | 生产 11 家逐家核对 | **是**（V1 §5-6） |
| 5 | 财务天数 | `analytics/formulas.py` 表达式、`registry.READS` | 保留"按窗口天数（12 个月 365）"，在读法里写清；实际财年天数如采用另起一轮 | 金标准行 | 天数单位类（V1 §5-7） |
| 6 | XOM 债务 | fixture 上的 total_debt 行 | 在 E 的 fixture 上核对 `made_of / substituted` 到行；不重修映射 | gold_v1 对照 | 否 |
| 7 | LLY 毛利 | `gross_margin` 的 revenue 标签路径 | 核对 fixture 上走的标签；若补备用定义，同主体、同窗、同口径，登记簿新条目 | gold_v1 对照 | 若新定义 |
| 8 | 历史统计 | `price.*` 度量的 `params` | 今天"只算最新窗口，不能问过去时点"（手册 market §5）。要么给 `as_of` 并证明无未来数据泄漏，要么保持方法边界 | 截止日隔离测试 | **是** |
| 9 | 文档数据 | `filings_section` 的表格 | 单位、列日期、行列归属另立验收 | 抽样核对 | 否 |
| 10 | 常量来源 | `primitives._calc`（`scale.factor`、`filter.level` 裸数） | 裸数必须带 `source ∈ {user_assumption, method_constant}`；登记簿 `BASIS` 加两个词，结果行 `means.basis` 带之；无来源裸数拒绝并说出路 | 行上有依据词；无来源被拒 | 否 |
| 11 | 展示审计 | `fact_adapters` | days 的 COUNT 显示、序列行的 accession、`book.position` 行说哪本书（V1 §5-8） | 金标准行 | 否 |

另三条设计点名的政策项：Q19 "收入份额不等于超额收益的因果份额"进手册 risk 章 §4 的 close 句（措辞）；Q20 条件性前瞻与 `f_policy_no_forecast` 的关系（拍板，若改则 POLICY 文字过目）；Q10/Q13 的 VaR 与压力结果保持 withheld（拍板，推荐保持）。

### P5 · 确定性边界统一与离线语义测量

设计 §10："运行时验证保持确定性；Finding、事实性 caveat、why、follow_up 以及所有分析状态文字共用检查入口和规则；语义 reviewer 的全部职责是离线 shadow 评测一份冻结的标注语料。"

**P5.1 · 入口单一化**：`services/fact_boundary.py` 只做一件事——`check_text(channel, text, ledger, question) -> Verdict`，内部就是 `answer_check.check`；answer、finding、caveat、why、follow_up、state proposal、`<prior>` 块的构建全部经它。`tests/test_v2_boundary_channels.py` 扩到全部通道（A2 完整）：同一句在每个通道得同一判定；字段名、角色、candidate 标签、持久化位置都不改变待遇。

**P5.2 · 误拦回归**：E 轮里被拒但人工判为正确的句子（P0 语料）逐条成测试，修在事实层的身份字段上（例：同公司跨期身份、所有格主体），不加语义法官。9/19 已记的两处一并进来。

**P5.3 · 离线 reviewer（仪器，不在运行时）**：新建顶层目录 `evals/semantic_review/`——不在 `src/`、`apps/`、`scripts/` 下，Dockerfile 不 COPY：`corpus.py` 把一轮的答案、被拒草稿、事实与出处冻结成 `evals/corpus/<TAG>.jsonl`；`labels/<TAG>.json` 人工标签 `{sentence, verdict, reason}`；`review.py` 让模型只读冻结语料出意见；`score.py` 对标标签报误报、漏检、未决率。意见只落在 `evals/reports/`，不进任何表。人工标注的语料先定 schema 再标（拍板：谁标、标多少）。

**P5.4 · A1 不可达性测试**：`tests/test_v2_audit.py` 加：`src/`、`apps/`、`scripts/` 下没有任何 `import evals`；三个 Dockerfile 不含 `evals`；`apps/api` 路由、`tools/`、两个循环不引用 `evals`。这是设计 §12 A1 要求的"依赖/调用路径检查"，不是靠两次运行结果相同。

验收：A1、A2 测试；误拦/漏检回归表；离线套件绿；措辞单 `--check`。

### P6 · 全量、泛化、恢复与对照

- **三轮 20 题**：P0 固定的配置（模型、预算、并发、快照、迁移、remap、时钟）不变，`phase_e.sh` 同款脚本按轮打 TAG，`requirement_score.py` 逐项对矩阵与 gold_v1 评分；门槛按设计 §12：候选配置连续 3 轮、每轮 20/20 满足预登记要求（拍板：门槛本身）。
- **泛化集** `docs/spikes/v2/questions_generalization.json`：改写、换主体/日期（书里其他名字、上一财年）、两回合追问、冲突用例（重述值对原值）；每题像 X 系列一样先在 fixture 上只读推导期望，写进题里。
- **恢复**：ask 中途杀 api → 900s 后 turn 释放、下一轮继承 accepted（P3.4 已含）；issuer_research 过期 → run 失败、不重放（A5 现有测试 `tests/test_task_lease.py`、`test_task_lease_live.py`、`test_turn_budget_live.py`）；scope 变更 → stale（A4）；重复 `start` → 单一任务（`started` 去重 + `active_run` 预检）。
- **对照臂**（设计 §11）：同配置下 (A) 现行三位分析师；(B) P4 之后的原语粒度/批量；(C) 仅当 V1 步骤 7 决策规则触发时的"面由任务组合"更少 worker。"主 agent 直调高层工具"不在这里跑，需要独立实验与决策记录。
- **报告字段**（设计 §12）：完整完成题数、逐要求正确率、真实边界、静默遗漏、错误事实、误拒/漏检、恢复成功、工具调用及机械算术比例、重试、token 与耗时、实际配置；基础设施失败单列不剔除；Q17 冻结新闻回放与实时检索分开。

## 4. 验收总表（机械，红了就是越界）

设计 §12 的 A1–A5 与分层验收，落到测试或脚本：

| ID | 设计要求 | 落点 | 包 |
|---|---|---|---|
| A1 | reviewer 运行时不可达；相反意见或移除组件不改变放行、路由、状态、context | `tests/test_v2_audit.py`：import 图（src/apps/scripts ⟂ evals）、Dockerfile 无 evals、路由/工具/循环不引用 | P5 |
| A2 | 同一句无据事实换到任何通道、任何角色、任何标签都同判；有据对照句不因迁移误拒 | `tests/test_v2_boundary_channels.py`（P1 先覆盖 finding/caveat/why/follow_up，P5 扩到 state proposal 与 prior 块） | P1、P5 |
| A3 | 被拒提案不进默认 context、状态、摘要、follow-up、恢复；审计读取保留失败身份 | `tests/test_v2_state.py` 走真实写入与投影路径（`propose_text` → `agent_steps` rejected → `view()` / `<prior>` / `open_turn` 都不含） | P2、P3 |
| A4 | scope 变更后旧接受标记不替代核查；过期结果不投影 | 同上：`invalidate` 后 `view()` 无 stale | P2 |
| A5 | lease 回归无行为改变：409、到期恢复、旧释放不清新 lease、重排白名单、非幂等失败；无新增续期/心跳 | 现有 `tests/test_task_lease.py`、`test_task_lease_live.py`、`test_turn_budget_live.py` 全绿；加一条断言 `settings` 默认 1800/900 与 `agent_session_service` 无续期代码路径 | P2 |

分层验收（设计 §12 表）对应产物：当前代码基线 → P0c 的 `ACCEPTANCE_V1E.md`；确定性回归 → 各包的测试；20 题目标 → P6 三轮；确定性门质量 → P5.2 误拦/漏检表；离线语义测量 → `evals/reports/`；泛化与恢复 → P6；真实外部服务 → P6 单列。

V1 §6 的验收总表继续有效（面 9/6/7、主分析师无词汇、图例为零、log 由 why 长出、每条知识只在一处、能问⇔可达）；本计划的改动不得让其中任何一行变红——尤其 `<state>` 与 `<prior>` 块不得带度量 key、动词名或未过检查的文字。

## 5. 措辞过目清单（发给模型或读者的文字，按包）

按仓库规则，每个包在提交前停下来过目本包的句子；`scripts/v1_wording.py` 的生成器要加上新块（`<state>`、`<prior>`）与 `ask`/`open`/`calc` 的新字段说明，措辞单才算完整。

| 包 | 句子 |
|---|---|
| P1.2 | `delegation.refusal_message` 末段：只重交被点名的条目，其余按原样保留 |
| P1.3 | `OPEN_TOOL` 描述与 `offset` 说明；序列行"显示 k 点 / 共 n 点"的标记 |
| P1.4 | `utils/json._CAP_DETAIL`：截断后的出路句 |
| P2.3 | `<prior>` 块的 source/use 标签 |
| P3.1 | `ASK_TOOL` 的 `requirements` / `anchor` / `for` 说明；`_ROLE` 加的一句"先把问题拆成要求" |
| P3.2 | `<state>` 块的标签与视图里的固定词（要求状态词 unresolved / covered / boundary、缺口类型词） |
| P3.3 | `requirement_unaddressed` 的 way_out；partial 时 runtime 附给读者的固定文字 |
| P4 | `calc` 描述（常量 `source`）；`scenario` 描述与 READS（若 Q13 改语义）；手册 risk 章 Q19 一句；days 读法；POLICY（若 Q20 改） |
| P5 | 无（若误拦回归改了出路句，按 9.3 组过目） |

风格指南八条本计划不改；若任何包想改其中一条，先回到 §6 拍板。

## 6. 待拍板（开工前）

1. 采纳本计划为现行计划；V1 计划保留为步骤 1–7 的执行记录。
2. P1.2 修复契约：patch 合并（推荐）还是整份替换。
3. P3.1 要求声明的接口：扩展 `ask`（推荐）还是新 `plan` 工具；anchor 必须是原文逐字子串（推荐）。
4. P3.3 partial 放行：第一次退回、第二次放行并由 runtime 附未覆盖清单（推荐），还是一律退回到覆盖为止。
5. P1.1 follow_ups 是否按事实性文字检查（设计要求一致待遇；推荐是）；Reports 抽屉是否显示未过检查的 caveats / why 原文（推荐否）。
6. P4-3 Q13 再配置语义：是否允许卖出所得用于买入、增持已持有名字（会改 9/19 的 8b8887b 语义；推荐加 `funding` 参数、默认不变）；ETF 分类来源。
7. P4-4 行业来源：SIC→行业映射表，还是无映射即拒绝。
8. P4-5 天数单位类（V1 §5-7）。
9. P4-8 历史时点统计：`price.*` 加 `as_of`（须证明无未来数据）还是保持方法边界。
10. Q20 条件性前瞻与 `no_forecast`；VaR 与压力结果保持 withheld（推荐保持）。
11. 发布门槛 3×20/20；E 轮两臂的模型分配与其后固定的主验收模型。
12. 验收矩阵 JSON 由评审者交付进仓库（P0b 前置）；谁来做人工标注语料、标多少（P5.3）。
13. P0a-2 答案草稿全文入 trace；P0a-3 错误体返回 message_id 并落 `turn_error` 步。
14. `agent_steps.task_id` 经 MCP 请求 meta 传递（推荐，与 actor 同路）。
15. 是否 push `6d40614` 到 origin/desk-v1，让评审者看到步骤 6/7 已落地。

## 7. 与 V1 计划及旧决定的关系

- V1 步骤 1–6 已完成；步骤 7（E 轮）= 本计划 P0c，仪器已在 `6d40614`。V1 步骤 7 的决策规则（`in_sequence` 对 `together`、X 系列 carried 占比 → 是否做"面由任务组合"）继续有效，读数来自 P0c。
- V1 §5 待拍板：第 1 条 → P4-1；第 3 条（回到高点所需涨幅）→ 仍待拍板，属 P4；第 4 条 → P4-11；第 6 条 → P4-4；第 7 条 → P4-5；第 8 条 → P4-11。
- V1 §4 代办不变：RAG 召回、代码组合（P4-2 只做批量，不做沙箱）、估值倍数、web_fetch、市场分析师去留（P6 对照臂）、docs/spikes 清理。
- 9/24 记录里的建议项已被设计吸收：`checked` 按跨度记（P0a 取证一并看）、每 completion 记实际工具面与注入事实 id（P2.1 Delivery）、task id 进 trace（P2.1）。私有数据外发的机械规则（`book.position` 与 `web_search` 同面）设计未提，仍是待拍板，不进本计划。

## 8. 执行顺序与提交粒度

| 顺序 | 包 | 提交 | 冻结/过目 |
|---|---|---|---|
| 1 | P0a 仪器 | 1 个 | 无模型文字；提交后哈希记为 E 基线 |
| 2 | P0b 矩阵 + gold_v1 + 评分脚本 | 1–2 个 | 无 |
| 3 | P0c E 轮两臂 | 0 个（产物与 ACCEPTANCE_V1E.md 事后 1 个） | 实测期冻结代码；按节点沟通表分析 |
| 4 | P1 | 3 个（G1、G2、G3+序列化） | 每个提交前过目 §5 对应句 |
| 5 | P2 | 2 个（迁移+模型；服务+follow_up_of） | `<prior>` 过目 |
| 6 | P3 | 2 个（要求声明+视图；覆盖+完成） | `ask`、`<state>`、partial 文字过目 |
| 7 | Q16 / Q04 切片 | 测试随 P3 | 活体核对在 fixture 面，不碰生产 |
| 8 | P4 | 每项 1 个 | 逐项过目 |
| 9 | P5 | 2 个（边界模块+通道测试；evals 仪器+A1） | 无 |
| 10 | P6 | 轮次产物 | 冻结 |

生产环境不在本计划范围：容器仍是 `e6c290b`，desk-for-one.com 处于 Caddy 维护模式，生产库未应用 v39/v40 迁移；上线是另一份决定。

## 9. 风险与对策

- 要求 anchor 要求逐字子串：改写型问题里主分析师必须原样引用，否则被拒；E2 里数 `invalid_ask(anchor)` 的次数，若多，改为"anchor 是原文子串或 R 号只引用不带 anchor 的整句"——仍是机械规则，不加语义匹配。
- `<state>` 块随任务增长会推高 prompt 峰值：`count_prompt` 每轮记录，80k 软上限不动；视图只放行原文与 id，不放日志。
- 覆盖退回会多用一次机会：P3.3 的放行规则由拍板 4 决定；E2 量它对出答案率的影响。
- v40 迁移扩大 RLS 面：parity 测试与 `test_v2_audit` 的租户表清单同步更新。
- Q13 若改书代数：typed_calculator 的 R1–R3 与书的代数是 V1 不变量，任何改动先加金标准行再动引擎。
