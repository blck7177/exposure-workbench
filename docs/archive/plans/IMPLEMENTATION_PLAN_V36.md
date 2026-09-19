# IMPLEMENTATION PLAN V36 — meta-agent + 按域 sub-analyst

> 依据：V36 架构设计稿（artifact `eb21e96e`，2026-09-15）、9/15 五项决定、`docs/spikes/v33/{AGENT_ARCHITECTURE,MODEL_CONTRACT,ACCEPTANCE_V33}.md`、V33I/V33J 的 Q11 trace。
> 起点：HEAD `d2911e7`，`pytest -m "not live" -q` 基线 **2443 passed / 11 skipped / 306 deselected / 17s**；工作树干净，仅 `docs/spikes/v32/` 未跟踪。
> 已定决策：D1 sub-analyst 回给 meta 易读信息，并记录 evidence / tracking / 更可信的报告备查；D2 按域（skill 的 14 个 PROCEDURES）；D3 同一 session、同一 bearer；D4 预算可接受；D5 research_session 与日报不动。

## 0. 目标与非目标

**目标**：把「意图 → desk 语言」这一步交给一个持有域 procedure 的 LLM（sub-analyst），删掉确定性 broker 与它的兜底作者；meta 只做决定与写作；上行分 brief（给 meta 读）与 report（核过后落库备查）两层；两处核对都是代码查表。

```
meta（agents/meta_agent.py）              sub-analyst（agents/sub_analyst.py，一域一个）        validation
 读：角色+一条规则、BRIEFING、ROSTER、       读：task、本任务主体的目录、该域 PROCEDURE、        交接核对（agents/delegation.handoff_check）：
     delegate 的返回、read_report 的返回         语言签名、工具结果（值+id+place/of）                覆盖 / 指针 / id / 边界 / 报告，≤1 次修复
 写：delegate(tasks)、散文、repair_answer    做：compile / run / read_filings / search_web / start  门（services/answer_check）：不变
 不做：program、id 拼写、MCP                 写：submit(brief, report)                              账本（services/ledger）：不变
                                            不做：给读者写字、派 analyst、编 id、心算
```

**非目标（本轮不做，列入 §6）**：research_session / submit_brief 的同形改造；日报改读 ledger；`measure_mismatch` 去留；V35 §21 的 tool 身份三处（price.beta 的 benchmark、派生向量无 window、book.analysis 的 subject）；MCP 容器与镜像重建（面收窄只改代码与测试，容器在 Phase 4 前重建一次即可）。

**不变量**：每次证据调用仍经 registry.invoke（校验 / 预算 / adapter / 落 step + facts）；ledger 仍按 session；agent 树深度仍为 2（sub-analyst 只能 `start` 后台任务）；web 读的 blocks 形状不变；API 的 claim_turn → 413 → 429 顺序不变；`answer_check` 的 G1–G5 与两次上限不变；import 法则不变（agents 只经 `llm_session` 到 provider、只经 `tool_session` 到工具；`tests/test_v2_audit.py`）。

**一处更正**：设计稿 §7 把「每轮 15 次证据调用」当成了每条消息内的调用上限。V23 起 `agent_session_service.reserve` 的单位是**消息**：一条消息的第一次证据调用扣一个单位并把 message_id 盖在 session 行上，同一消息内后续调用不再扣轮预算（只计入终身 `tools_used` 审计数）。所以 sub-analyst 的调用上限由它自己的 loop 计数（`sub_analyst_evidence_calls`），不改 registry，也不需要「每增加一个 analyst +5」。

## 1. 分阶段

每阶段结束时 `pytest -m "not live"` 全绿（≥2443 + 新增）；Phase 0 与 Phase 3 各有一组 `live` 测试；Phase 4 用 V33 的 20 题做验收。每阶段一个或几个提交，提交信息写清「删了什么、为什么」；Phase 1 开始前给 `d2911e7` 打 tag `v35-final`，Phase 4 不过则回到它。

### Phase 0 — 仪器：actor 列与沟通表脚本（不改行为）

文件：`infra/init.sql`、新 `infra/migrations/v36_actor.sql`、`db/models.py`、`services/trace_service.py`、`agents/llm_session.py`、新 `scripts/v36_forensics.py`、`scripts/conversation_battery.py`、`apps/api/routes/agent.py`（StepOut）；新 `tests/test_v36_actor.py`。

1. **`agent_steps.actor VARCHAR(64) NULL`**。`init.sql` 的 CREATE TABLE 加列；`v36_actor.sql` 是 `ALTER TABLE agent_steps ADD COLUMN IF NOT EXISTS actor VARCHAR(64);`，幂等。旧行 NULL 读作 `meta`。`AgentStep.actor` 映射。
2. **`trace_service.record_step(..., actor: str | None = None)`**；`LlmSession(db_factory, session_id, message_id, actor=None)` 把 actor 写进 llm_call 行；`llm_session(...)` 上下文管理器透传。现有调用方不改（默认 None）。
3. **StepOut 增 `actor`**（`SessionDetailOut.steps`），web 端不读也无妨。
4. **`scripts/v36_forensics.py`**：按 session 读 `agent_steps`，输出**每轮的沟通表**：`seq | 方向（actor → actor）| 载体（step_type / tool_name）| status | 大小（args chars、result_summary chars、prompt/completion tokens）| 内容摘要 | schema keys（args 的顶层键）`；末尾给每对节点的沟通次数；answer / brief 步在当步账本上重放核对（沿用 `v35_forensics._ledger_before`）。方向的推断规则写在脚本里：llm_call 的 actor 是发起者；delegate 是 meta → sub；tool_call 是 actor → tools；brief 是 sub → check；answer 是 meta → gate。
5. **`conversation_battery.py`** 的 `_STEPS` SQL 带 `actor`；`battery_counters.py` 增加 delegations 数、coverage、report status 的计数（Phase 1 后才有值，先留列）。

验收：`v36_forensics.py docs/spikes/v33/V33J.json --db exposure_battery` 对 J 轮 Q11 打出的表与 9/15 手工整理的一致（request 两次、digest 两次、answer 两次；V35 的 request/digest 步 actor 为 NULL，脚本按 tool_name 归为 broker）；`test_v36_actor.py` 断言 `record_step(actor="sub:x")` 落列、`LlmSession(actor=...)` 的 llm_call 行带 actor；live：迁移在 `exposure_battery` 上跑一遍幂等。

### Phase 1 — sub-analyst（串行）、delegation、digest 迁出、meta 换工具、broker 退场

文件：新 `agents/delegation.py`、新 `agents/sub_analyst.py`、新 `services/digest.py`、`services/program_builder.py`（`compile`）、`analytics/skill.py`（`offers` / `roster()` / `system_text()`）、`agents/meta_agent.py`（重写 loop 的工具段）、`tools/faces.py`、`app_state/settings.py`；删 `agents/evidence_broker.py`、`agents/evidence_request.py`；测试：新 `tests/test_v36_delegation.py`、`tests/test_v36_sub_analyst.py`、`tests/test_v36_digest.py`、`tests/test_v36_skill_roster.py`、`tests/test_v36_turn_offline.py`；改 `tests/test_meta_agent_gate.py`、`tests/test_v21_batch.py`；删 `tests/test_v33_broker.py`（20 个，改写进 digest / delegation 两处）。

建议拆成四个提交，顺序如下，每个提交离线全绿：

**1a · `services/digest.py`（自 broker 迁出，行为等价 + place/of/rank）**

- `render(result: dict, *, subject: str | None, cap: int, mint) -> dict`：把 broker 的 `_absorb` / `_tell_apart` / `_stamp_ids` / `_fit` / `_display` / `_cited` 原样搬入，一个入口。figure 字段在 V35 的 `node / rank / op / label / method` 之外加 `place / of`（`for k in ("node","rank","op","label","method","place","of")`）。
- `boundary(text, *, want, subject, cls, code, nearest) -> tuple[dict, Fact]`：铸 absence fact 的逻辑（原 `Broker._boundary`），返回条目与事实，由调用方收集事实落账。
- `claims.SPELLING_REFUSALS` 的引用保留（services → services，合法）。
- `tests/test_v36_digest.py`：把 `test_v33_broker.py` 里关于 digest 形状的用例改写（值带 id、`also` 合并、held_back 铸事实、passage 截断、边界分类），新增「ranked 条目的 place/of 出现在 figure 上」。

**1b · `agents/delegation.py` + `analytics/skill.py`**

- skill：`Procedure` 增 `offers: tuple[str, ...] = ()`；`roster() -> list[dict]`（`domain / subject_kind / question / offers / absent`；`offers` 为空时由 `close` 生成）；`system_text(p) -> str`（question / this desk / compare / close / absent / programs，即今天 `push_text([p])` 的单域形，1.6k chars 上下）；`book_limits_and_triggers.compare` 补一句「a cap the mandate does not define is a filter over weights」。14 段 `offers` 文字我起草、你审后再提交（见 §5）。
- delegation：`DELEGATE_TOOL` / `SUBMIT_TOOL` / `READ_REPORT_TOOL` 的 JSON schema（设计稿 E4 / E8；`additionalProperties: false`）；`parse_tasks(args, roster) -> list[Task]`（域在 roster 内、同域不重复、subjects 与 want_to_know 非空、行数 ≤8、tasks ≤ `delegate_max_tasks`；否则 `ValueError`，meta 收到 `{"error": "invalid_delegation", "detail"}`）；`Task` / `TurnContext` / `HandoffVerdict` 三个 dataclass；`handoff_check(task, brief, report, ledger) -> HandoffVerdict`：
  - C1 覆盖：`findings ∪ not_done` 的 `want` 集合 = `{1..n}`，缺的报 `uncovered_want`，多的报 `unknown_want`；
  - C2 指针：每条 `finding` 文本过 `answer_check.check(text, ledger)`，problems 挂到 `findings[i]`；
  - C3 id：`facts` 里每个 id `ledger.holds`；
  - C4 边界：`not_done[*].boundary` 是账本上的 absence 事实，或 `why` 非空；
  - C5 报告：`report.text` 过 `answer_check.check`，problems 挂到 `report`；
  - 返回 `ok`（C1–C4 全过）、`problems`、`coverage {asked, done, not_done, refused}`、`accepted_findings`（逐条通过的）、`report_verdict`。
- `run(tasks, ctx) -> dict`（E10 的拼装）：Phase 1 串行 `for task in tasks: await sub_analyst.run_sub_analyst(task, ctx)`；每域一段，`how_to_cite` 固定文案。
- `tests/test_v36_delegation.py`：parse 的合法 / 非法形；C1–C5 各一正一反；第二次仍不过时逐条接受；E10 形状。

**1c · `agents/sub_analyst.py` + `program_builder.compile`**

- `program_builder.compile(request, held_in) -> dict`：包 `build`；成功 `{"program", "typecheck": [], "skipped"}`；`NotExpressible` 时 `{"program": None, "reason", "nearest", "skipped"}`。不执行。
- `run_sub_analyst(task, ctx) -> AnalystResult`：
  - messages：system = 角色 + `skill.system_text(domain)` + `ps.signature_text()` + 引用规则 + brief 规则（设计稿 §4 的草稿）；user = `{task, subjects: briefing 切片, boundaries}`。
  - tools：`COMPILE_TOOL`（进程内）、`ctx.tools_session.tools` 里按名取 `run / read_filings / search_web / start` 的 schema、`SUBMIT_TOOL`。
  - loop ≤ `settings.sub_analyst_max_turns`（默认 8）：compile 记 `tool_call/compile` 步（`trace_service.record_step` 直接记，无 facts）；其余经 `ctx.tools_session.call`，结果经 `digest.render(cap=settings.sub_analyst_result_chars)` 后 `ejson.dumps_capped` 回给模型；证据调用计数 ≤ `settings.sub_analyst_evidence_calls`（默认 8），超出回 `{"error": "analyst_budget", ...}`；
  - submit → `handoff_check`；不过：tool 结果 = problems，下一次 completion `tool_choice="required"`，面上仍是全部工具（修复可能先要取证）；第二次仍不过：`accepted_findings` 照交、其余进 `refused`；
  - 记 `brief` 步（completed / rejected；`evidence_refs` = 本次铸的边界事实，同时写 facts 表，沿用 `ledger_svc.step_entry` / `rows_for`）；Phase 1 的 report 只记进 `brief` 步 args 的前 4k（Phase 2 落表）；
  - `AnalystResult`：`domain / task_id / status / findings / not_done / caveats / follow_ups / refused / report{title,text,verdict} / cost{completions, evidence_calls, prompt_tokens} / minted`。
  - 空回复、无 tool call、超 max_turns：状态 `refused`，`not_done` 为全部行，`why = "the analyst did not file a brief"`，铸一条 boundary 事实。
- 新 settings：`sub_analyst_max_turns=8`、`sub_analyst_evidence_calls=8`、`sub_analyst_result_chars=16_000`、`parallel_analysts=False`。`report_max_chars` 撤到 Phase 2：本仓库的法则是声明了没人读的旋钮比没有更糟（`test_p0_schema`），而它的读者在 Phase 2 才出现。`delegate_max_tasks` 成了 `delegation.MAX_TASKS`，因为它是协议的一部分而不是部署旋钮。
- `tests/test_v36_sub_analyst.py`：脚本化 LLM（沿用 `test_v33_broker._Llm` 的形：按序回 tool_calls）+ 假 tools_session（沿用 `test_meta_agent_gate._stub_tools`）：compile → run → submit 通过；submit 被拒一次后修复通过；两次不过时逐条接受；证据上限；空回复的 refused 形；步骤序列与 actor。

**1d · `meta_agent.py` 换工具、faces 收窄、broker 删除**

- system：删 `request_evidence` 段，加 ROSTER 段（设计稿 §5 草稿）；`skill.push_text` 不再推送（`settings.push_domains` 改为控制 ROSTER 顺序是否按 `match_domains` 置顶）。
- tools：`[DELEGATE_TOOL] + ([REPAIR_TOOL] if standing)`；Phase 2 再加 `READ_REPORT_TOOL`。`_BUDGET_FREE_TOOLS = ("delegate", "read_report", "repair_answer")`（`test_v21_batch` 断言其首项不在 meta registry 里，仍成立）。
- loop：`delegate` → `delegation.parse_tasks` → `delegation.run(tasks, ctx)` → tool 消息 `dumps_capped(result, TOOL_RESULT_LIMIT)`；`requests` 计数改 `delegations`；meta dict 写 `delegations / reports / completions`。
- `faces.FACE_META_AGENT = ["run", "read_filings", "search_web", "start"]`；`test_mcp_server_build` / `test_mcp_stdio_live` 按变量比对，自动跟随；`docs/MCP_PLAN.md`、`ARCHITECTURE_AS_BUILT.md §6` 的面清单同步。
- 删 `evidence_broker.py`、`evidence_request.py`、`test_v33_broker.py`；`test_meta_agent_gate.py` 里对 `evidence_broker.Broker._record` 的 stub 改为 stub `meta_agent.delegation.run`；`_MAY_REACH_THE_PROVIDER` 不需改（新模块不碰 provider）。
- `tests/test_v36_turn_offline.py`：**Q11 的离线重放**。脚本化 LLM 按序：meta #1 → delegate（四行）；sub #1 → compile；sub #2 → run（含 room / move / filter 节点）；sub #3 → submit；meta #2 → 散文。假 tools 返回与 J 轮同形的 facts 行（含 place/of）。断言：coverage 4/4；散文过门；`agent_steps` 序列为 `llm_call(meta) → delegate → llm_call(sub) → tool_call/compile → llm_call(sub) → tool_call/run → llm_call(sub) → brief → llm_call(meta) → answer`；散文里的四个数字全部指向 sub 取的事实。

验收（Phase 1 整体）：离线全绿；`tests/test_v2_audit.py` 全绿（import 法则、面）；live 冒烟 `scripts/conversation_battery.py --fixture --only Q11 --only Q01 --only Q13 --only Q18 --only Q20`，每题 `v36_forensics.py` 打出的沟通表可读，且 Q11 的散文里没有心算的数字。

### Phase 2 — 报告：表、核对、read_report、API、web

文件：`infra/init.sql`、新 `infra/migrations/v36_analyst_reports.sql`、`db/models.py`、新 `services/analyst_reports.py`、`agents/sub_analyst.py`、`agents/delegation.py`（READ_REPORT_TOOL）、`agents/meta_agent.py`、`apps/api/routes/agent.py`、`scripts/delete_user.py`、`tests/test_v2_audit.py`（TENANT_TABLES）、`apps/web/lib/api.ts`、`apps/web/app/components/analyst/Dock.tsx`、新 `apps/web/app/components/analyst/Reports.tsx`；测试：新 `tests/test_v36_reports.py`、`apps/web/tests/reports.test.tsx`。

1. **表 `analyst_reports`**（设计稿 §7 的列）：`session_id REFERENCES agent_sessions(id) ON DELETE CASCADE`；索引 `(session_id, message_id)`；RLS policy 照抄 `facts` 的（经 `agent_sessions.owner_id`）。`TENANT_TABLES` 加 `analyst_reports`；`delete_user.py` 的 `DELETION_ORDER` 在 `facts` 之前加 `("analyst_reports", "session_id = ANY(%(sessions)s)")`（子先于父，`test_erasure_*` 三条自动核）。
2. **`services/analyst_reports.py`**：`store(db, **cols) -> report_id`（`rep_` 前缀，`utils.ids.new_id`）；`load(db, session_id, report_id) -> dict | None`（RLS 之下按 session 取，跨租户即 None）。
3. **sub-analyst 落库**：submit 通过后 `answer_check.check(report.text, ledger)`；过则 `accepted()` 出 blocks / citations / verified，`status=verified`；不过则 `status=refused`，存 problems，blocks 为空；记 `report` 步 `{report_id, status}`。E10 里带 `report_id / status`。
4. **`read_report` 工具**（meta）：`{report_id}` → `{domain, title, text, tables}`（≤ `report_max_chars`）；只回本 session 的报告；数字已在账本，meta 可照抄。
5. **API**：`GET /agent/sessions/{session_id}/reports/{report_id}` → `ReportOut`（设计稿 E13）；先 `agent_session_service.get_session` 得 404，再 `analyst_reports.load`；`require_user`。`MessageOut.meta` 已透传 `reports`。
6. **web**：`api.ts` 加 `getReport(sessionId, reportId)`；`Dock.tsx` 三处读 `meta` 的地方加 `reports`；`Reports.tsx`：每份报告一枚 chip「域名 · 已核 / 未核」，点开抽屉；抽屉复用 `AnswerBlocks`（blocks 里已带填好的 fact，无需另取）与 `Verified`；`refused` 的报告显示 problems 列表而不是散文。vitest：chip 渲染、抽屉打开、refused 分支。

验收：`test_v36_reports.py`（store/load、跨 session 取不到、refused 形）；`test_v2_audit.py` 三条 erasure 测试与 RLS 表清单全绿；live：迁移在 `exposure_battery` 上幂等；web 手工：抽屉里每个数字点开是事实。

### Phase 3 — 并行 sub-analyst（**前提已实测；推迟**，2026-09-15）

文件：新 `tests/test_v36_parallel_live.py`（三个前提各一个 live 测试）；`app_state/settings.py` 的 `parallel_analysts`（默认 False）与 `sub_analyst.run_tasks` 的分支已在 Phase 1c 就位。

实测结果（fixture 库 + fixture 面）：

| 前提 | 结果 |
|---|---|
| 1 seq 分配 | **红**。两个 agent 同时记步骤，20 个位置里 18 个重号。`record_step` 的 `max(seq)+1` 在任何锁之外，(session_id, seq) 也没有唯一约束，所以冲突是静默的——而沟通表就是这一轮的全部读法。 |
| 2 MCP 并发 | **正确性绿**：并发调用全部返回、各自落行、没有重号。**收益未测出**：这台机器上每个工具都在几十毫秒返回，重叠与排队的差别落在噪声里（8 次并发 vs 8 次串行，连续两轮的比值是 1.91 和 0.72）。在这些工具上断言一个阈值等于在测试里掷硬币。 |
| 3 归属 | **设计上红**。tool_call 行由 MCP 门后的 registry 写，bearer 只告诉它 session 与 message。串行下取证脚本按"最后开口的那个"推断（打 `~`），并行下无从推断。 |

**结论：并行推迟，而它等的不是三个修法。**一个是机械的（seq 在锁下分配）。另外两个是同一个问题：**每个域分析师是否拿自己的 tool session？**一个 session 就是一条连接加一个 token——而"每个分析师一个 token"正是 `auth/internal_token` 那句"token 不是塞 context 的地方"会从反对变成赞成的地方：actor 到那时不是上下文，是身份。它也是"并发调用到底重不重叠"第一次值得测的形状，因为一分析师一 session 就是一分析师一条流。

这个决定要 boss 拍板，本轮不替他做。串行版本照常跑，它的 trace 是精确的。

### Phase 4 — 实测与验收记录

仪器：`scripts/battery_fixture.sh restore && serve`（`exposure_battery` + :8105 面）、`scripts/conversation_battery.py tests/battery/conversations_v33.json docs/spikes/v36/V36A.json --fixture --concurrency 5`（20 题同 J 轮）、`scripts/v36_forensics.py`、`scripts/v35_round_summary.py` 改名沿用。

- 读数（按优先级）：每题的沟通表；出答案数 / 20；通过答案里读者可见的假陈述（逐条回到指向的事实）；coverage 分布；report 的 verified / refused 比；每题 completions 与 prompt tokens（meta 与 sub 分列）；从未通过的四题 Q04 / Q10 / Q11 / Q15 是否至少通过一次。
- 记录：`docs/spikes/v36/ACCEPTANCE_V36.md`，形状同 `ACCEPTANCE_V33 §21`：与 J 轮的对照表 + 逐题的沟通表摘要 + 按角色的遗留清单。
- **实测期冻结代码**：跑的过程中遇到错误不改任何东西，只记错误与 log；收尾用 `git status` 证明树未动。

验收线：出答案数不低于 J 轮的 9；假陈述不高于 J 轮的 3 且全部可追溯；Q11 通过；每题沟通表能指出每次往返的贡献（没有「白跑一次」的 delegate）。

## 2. 角色边界（实现时的四条红线）

- **meta 不碰 program、id、MCP**：`meta_agent.py` 不 import `program_builder` / `program_service` / `digest`；它的三个工具全在进程内。
- **sub-analyst 不给读者写字**：它的散文只进 `analyst_reports`；`AgentMessage.content` 只来自 meta。
- **两处核对都是查表**：`handoff_check` 与 `answer_check` 只做集合运算与账本查表，没有任何「这个数大概是那个」的推断（V34 的教训）。
- **每个显示给任一 LLM 的值都在账本上**：digest 的 held_back 铸事实；boundary 铸事实；ROSTER 与 BRIEFING 不含数字（这两处文字仍不在账本上，是 V35 §21 的遗留，本轮不解）。

## 3. 风险

| 风险 | 处理 |
|---|---|
| sub-analyst 选错分母、错读法（指向正确的语义错） | 两处核对都放行；靠 report 可查与 Phase 4 抽检；skill 的 PROCEDURE 文字写清读法 |
| ROSTER 选错域 | sub-analyst 用 not_done 说「不是我的域」，meta 多花一轮；ROSTER 按 `match_domains` 打分把前两条置顶 |
| digest 扣图形后 sub-analyst 不再取 | system 明说「held_back 时按名再取」；沟通表里数这类往返 |
| 并行三前提任一不成立 | Phase 3 推迟，`parallel_analysts=False` 串行照常 |
| 离线测试对 loop 的 stub 面变大 | `test_v36_turn_offline.py` 只 stub `tool_session` / `llm_session` / `_briefing` / `_record_*`，和今天一样 |
| token 成本 | 单域题预计 ≤ V35；三域题 2–3 倍；`context_soft_limit_tokens` 只按 meta 的 prompt 峰值算，sub-analyst 各自独立 |
| 面收窄影响 MCP 容器上线上的行为 | 面是代码常量；容器在 Phase 4 前按工作树重建一次（`battery_fixture.sh serve` 用的是工作树，测得到） |

## 4. 与既有文档

- `docs/spikes/v36/AGENT_ARCHITECTURE_V36.md`：设计稿的 markdown 摘要 + artifact 链接（Phase 0 时建目录）。
- `docs/ARCHITECTURE_AS_BUILT.md`：§6 工具面清单、§8 Agent 层改写；`docs/MCP_PLAN.md` 面清单同步。
- `docs/MODULE_NOTES.md`：新增 agents 层一节（meta / sub-analyst / delegation 的职责与红线）。
- `docs/PROGRAM_LANGUAGE.md`：不变（compile 只是包装）。
- `docs/spikes/v33/ACCEPTANCE_V33.md`：末尾加一行指向 V36。

**收尾(2026-09-15,A 轮之后)**:以上五项与 `MCP_PLAN.md` 的面清单、`ARCHITECTURE_AS_BUILT.md` §1/§2/§3/§5/§8/§12 已同步;`AGENT_ARCHITECTURE_V36.md` 含一节「as built 与设计稿的偏差」。Phase 0 第 5 条的 `battery_counters.py` 三类计数(delegations / coverage / report status;另有交接拒绝按首因、completions 按 actor 分列)与 Phase 2 的 `apps/web/tests/reports.test.tsx`(chip、`panelFor`、抽屉四态;react-dom/server 静态渲染,无 DOM,点击本身归浏览器 smoke)也在这次补上;`ReportPanel` 拆成取数壳与纯视图 `ReportPanelView`。

## 5. 执行

- 顺序：Phase 0 → 1a → 1b → 1c → 1d → 2 → 3 → 4；每步一个提交；Phase 1 开始前打 tag `v35-final`。
- 需要你过目再提交的文字：14 段 `offers`；meta 与 sub-analyst 的两段 system prompt；ROSTER 的段落文案。我先起草放在 `docs/spikes/v36/WORDING.md`，你审完我再落进代码。
  **实际(9/15)**:为不阻塞 Phase 1,三处文字按草稿直接落进了代码并随 Phase 1b/1c/1d 提交;过目单 `docs/spikes/v36/WORDING.md` 由 `scripts/v36_wording.py` 从代码原样生成(带 `文件:行`),**仍待过目**,改一处同步一处后重跑脚本。
- 粗估工作量：Phase 0 半天；Phase 1 两到三天（1c 最重）；Phase 2 一天；Phase 3 一天含 live 测试；Phase 4 半天跑 + 一天取证。
- 每阶段结束报告：离线测试数、live 结果、沟通表样例各一。

## 6. 后续（本轮不做）

- research_session 与日报的同形改造（9/13 D8）。
- ROSTER 与 BRIEFING 文字上账本（V35 §21 J 轮 Q05/Q06 的拒绝）。
- `measure_mismatch` 去留；tool 身份三处。
- sub-analyst 之间的横向发现共享（Cognition 2026 的「children surface discoveries」），今天靠 meta 二次 delegate。
