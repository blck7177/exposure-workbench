# Agent 架构 V36:meta-agent + 按域 sub-analyst(设计稿摘要 + as-built 偏差,2026-09-15)

> 正本是 9/15 的设计稿 artifact <https://claude.ai/code/artifact/eb21e96e-22b0-4bdc-9edb-ee30e265f4b7>(源 HTML 在当时的 scratchpad,未入库)。本文是它的 markdown 摘要,末尾加一节「as built 与设计稿的偏差」,按 HEAD 上的代码写。
> 计划 `docs/IMPLEMENTATION_PLAN_V36.md`;冒烟 `SMOKE_V36.md`;A 轮验收 `ACCEPTANCE_V36.md`;措辞过目单 `WORDING.md`。承接 `docs/spikes/v33/AGENT_ARCHITECTURE.md`(9/13 讨论稿「分析师 + 证据子 agent」;broker 是它在 D1 结构化请求、D2 LLM 只在组合处 两个决定下的实现)。
> 依据:J 轮 Q11 的节点沟通表(9/15)、V33I / V33J 的 trace、9/15 五项决定;外部参照:Anthropic orchestrator-worker(子 agent 是 intelligent filter;交接四要素;telephone game 靠持久化产物解决——我们的 ledger)、Anthropic 2026-01「按上下文边界拆,不按问题类型拆」、Cognition 2026-04「写单线程,子 agent 贡献智能不贡献动作」、Magentic-One 的 facts-to-derive 账本、MAST FM-2.6 reasoning-action mismatch。

## 0. 五项决定与不变的部分

| 决定 | 内容 | 落点 |
|---|---|---|
| D1 职责 | sub-analyst 回给 meta 它需要的信息,用容易理解的形式;同时记录 evidence、tracking,和一份更可信的分析报告备查 | brief 给 meta 读(E10);report 经核对后落 `analyst_reports`,`read_report` 按需取;每个值带 id,evidence 就是账本 |
| D2 粒度 | 按域:skill 的 14 个 PROCEDURES,一域一个 sub-analyst | 域的 procedure 文本就是该分析师的 system;ROSTER 让 meta 按域派单 |
| D3 边界 | 同一 session、同一 bearer | 同一 tool_session、同一 session_id / message_id;facts 落在门读的同一本账上;新增 `agent_steps.actor` 区分谁做的 |
| D4 预算 | 成本可接受 | §7 的默认上限 |
| D5 范围 | research_session 与日报不动 | 只改对话线 |

**不变**:MCP 面的挂载与 bearer;registry 四步 wrapper(校验 → 预算 → fn → 适配器)与 Fact 的出生;`services/ledger.py` 与 `services/answer_check.py`(G1–G5、一次报全、两次上限、repair_answer);API 的 claim_turn / 413 / 429 顺序;web 端 blocks 与 LinkText;program_service 的语言、typecheck、执行器;program_builder 的确定性编译(改为 sub-analyst 的工具)。
**删除**:`agents/evidence_broker.py`(编译器 + 兜底作者 + digest 拼装)、`agents/evidence_request.py`(request_evidence 与它的 ask 字段)。digest 的渲染迁到 `services/digest.py`;作者 LLM 不再存在,它的工作是 sub-analyst 的本职。

## 1. 四角色落位:V35 → V36

先按角色判:V35 的错在于「把意图翻成 desk 语言」没有主人。分析师是通才,skill 只作为文本推送给它,builder 只读字段不读 ask,作者只在 builder 编不出时出场。J 轮 Q11 的 room 意图写在 ask 里,无人读;I 轮 Q11 的 room 由分析师自己写成 derive,算出来又被 digest 扣掉。V36 给这件事一个主人:sub-analyst 是 LLM 拿着该域的 procedure 做的分析;作者从兜底变成本职;skill 从推送文本变成可执行的知识所在。

| 角色 | 模块 | 读 | 写 | 不做 |
|---|---|---|---|---|
| LLM · meta | `agents/meta_agent.py` | 角色 + 一条规则、BRIEFING、ROSTER、delegate 的返回、read_report 的返回 | `delegate(tasks)`、散文、`repair_answer` | program、id 拼写、MCP |
| LLM + skill · sub-analyst | `agents/sub_analyst.py` · `analytics/skill.py` | task、本任务主体的目录、该域 PROCEDURE、语言签名、工具结果(值 + id + place/of) | program / 工具参数、`submit(brief, report)` | 给读者写字、派 analyst、编 id、心算 |
| tool · 正交执行 | `program_builder.compile_request` · `program_service` · `tools/registry` · `services/digest` | — | compile 只编不跑;run 经 MCP 执行,每个节点成 Fact;digest 把每个值渲染成 `16.0% [f_…]` 并带 place/of | 领域判断 |
| validation | `agents/delegation.handoff_check` · `services/answer_check` · `services/ledger` | brief、report、散文、本 session 账本 | 交接核对(覆盖 + 指针查表);门(不变) | 语义判断 |

V35 与 V36 的区别在一条边:V35 的分析师把字段交给编译器,ask 里的意图无人读;V36 的 meta 把 want_to_know 交给持有域 procedure 的 sub-analyst,它写 program、读结果、写 brief,经代码核对后 meta 才读到。ledger 与门两侧相同。

## 2. 一轮对话的时序(E1–E13)

五个节点:用户/API、meta、sub-analyst(每域一个)、工具与 MCP 面、账本与两处核对。

| 边 | 方向 | 载体 | 要点 |
|---|---|---|---|
| E1–E2 | 用户 → API → meta | `POST /agent/sessions/{id}/messages` → `handle_message` | claim_turn、413 预判、429 扣配额先于任何 LLM 调用;不变 |
| E3 | 系统 → meta | messages:system 角色 + BRIEFING + ROSTER;history;tool 返回;拒绝信 | ROSTER 取代 skill 推送:meta 只读每个域「能回答什么」,不读示例 program |
| E4 | meta → sub | `delegate(tasks)`,进程内,step `delegate` | 1–4 个 task;每 task:domain(ROSTER 内)、subjects(BRIEFING 里的名字)、want_to_know 1–8 行、可选 facts_to_derive / constraints / context / follow_up_of |
| E5 | 系统 → sub | 独立的 messages 数组,不含 meta 的历史 | system = 角色 + `skill.system_text(域)` + `signature_text()` + 引用与 brief 规则;user = task + 主体目录切片 + boundaries |
| E6 | sub → 工具 | `compile`(进程内)· `run` · `read_filings` · `search_web` · `start`(经 MCP,同一 bearer) | compile 把 request 编成 program 不执行;sub-analyst 可改 program 后再 run |
| E7a/b | 工具 → 账本 / → sub | registry 落 agent_steps + facts;`digest.render` | figures / series / passages / started / boundaries / nodes / held_back;每个结果 ≤16k chars;扣下的图形铸 held_back 事实 |
| E8 | sub → 交接核对 | `submit(brief, report)`,step `brief`(completed / rejected) | brief = findings[{want, facts, finding}] + not_done[{want, why, boundary}] + caveats + follow_ups;report = {title, text} |
| E9 | 核对 → sub | problems + coverage | 一次修复机会,再次 submit 时 `tool_choice=required` |
| — | 核对 → analyst_reports | report 过 `answer_check` → 落库,step `report` | verified 存正文与 blocks;refused 存 problems |
| E10 | 核对 → meta | delegate 的工具返回 | analysts[{domain, task_id, report_id, status, coverage, findings, not_done, caveats, follow_ups, refused, cost}] + how_to_cite |
| E11 | meta ↔ 门 | 散文 → `answer_check`;拒绝信 → `repair_answer` | 不变;账本由 `ledger.load(session_id)` 读全部 completed 步骤,sub 取的事实自然在内 |
| E12 | meta → 读者 | AgentMessage{text, citations, meta.delegations, meta.reports} | 新增 delegations / reports 两个 meta 字段 |
| E13 | 读者 → 报告 | `GET /agent/sessions/{sid}/reports/{rid}` | 每份报告一枚 chip(域名 + 已核 / 未核),抽屉复用 blocks 渲染;refused 显示 problems |

多个域时 E4–E10 每域一份;Phase 1 串行,Phase 3 并行(推迟,见 §8)。

## 3. 沟通 schema(摘要;全文见设计稿 §3,真实载荷见 `V36A_schema.md`)

```jsonc
// E4 delegate
{"tasks": [{"domain": "book_limits_and_triggers", "subjects": ["port_001"],
            "want_to_know": ["which position's issuer-concentration check is nearest its warning tier",
                             "how much room it has left to warning and to breach",
                             "what single-name percentage move takes it to breach with everything else fixed",
                             "which issuers would be over an 8% single-issuer cap"],
            "facts_to_derive": ["move to breach = room to breach / the name's weight"],   // 可选
            "constraints": {"window": "latest", "compare": "rank lowest"},                 // 可选
            "context": "…", "follow_up_of": null}]}                                      // 可选

// E8 submit
{"brief": {"findings": [{"want": 1, "facts": ["f_…"], "finding": "MSFT is nearest: … 16.0% [f_…] …"}],
           "not_done": [{"want": 4, "why": "desk 的原话", "boundary": "f_…"}],
           "caveats": ["…"], "follow_ups": ["…"]},
 "report": {"title": "…", "text": "…散文,数字带 [f_…],可用 [table: node] / [chart: node]…"}}

// E9 verdict(代码,不用 LLM)
{"ok": false,
 "problems": [{"where": "findings[3]", "reason": "mark_mismatch", "figure": "25.0%", "id": "f_…", "holds": "24.9%", "fix": "…"},
              {"where": "coverage", "reason": "uncovered_want", "want": 4, "fix": "…"}],
 "coverage": {"asked": 4, "done": 3, "not_done": 0, "refused": 1}}

// E10 delegate 的返回
{"analysts": [{"domain": "…", "task_id": "tsk_…", "report_id": "rep_…",
               "status": "verified | partial | absent | refused",
               "coverage": {"asked": 4, "done": 4, "not_done": 0, "refused": 0},
               "findings": [/* E8 里通过的条目,原文 */], "not_done": [], "caveats": [], "follow_ups": [],
               "refused": [/* {want, finding, problems} */],
               "cost": {"completions": 2, "evidence_calls": 2}}],
 "how_to_cite": "Every figure below is written exactly as you must write it, bracket included …"}
```

五条交接规则:**C1** 覆盖——findings ∪ not_done 的 want 集合 = 全部行号,缺的报 `uncovered_want`,多的报 `unknown_want`,一行既答又解释报 `answered_and_explained`;**C2** 指针——每条 finding 的文本过 `answer_check.check`;**C3** id——facts 里每个 id 在账本上;**C4** 边界——not_done 带的 id 是 absence 事实,或 why 非空;**C5** 报告——report.text 过 `answer_check.check`。第二次仍不过:逐条通过的 finding 照交,不通过的列进 refused;report 落库时状态记 refused 并附 problems。

## 4. Sub-analyst 内部

一个 sub-analyst 是 `agents/sub_analyst.py` 里的一个 loop:一个域、一个 task、自己的 messages 数组、共用的 tool_session 与 db_factory、自己的 `LlmSession(actor="sub:<domain>")`。它不见 meta 的对话历史,只见 task、主体目录和自己取的结果。

| 段 | 来源 | 体量(估) |
|---|---|---|
| 角色与规则 | 固定文本(`sub_analyst._SYSTEM`) | ≈500 tokens |
| DOMAIN 段 | `skill.system_text(procedure)`:question / this desk / compare / close / absent / 示例 program | 0.8–2.5k tokens |
| THE LANGUAGE | `program_service.signature_text()` | ≈1.6k tokens |
| task + 主体目录 + boundaries | E4 的一项 + briefing 切片 | 0.5–3k tokens |
| 每个工具结果 | `digest.render`,≤16k chars | ≤4k tokens 每个 |

循环:completion #1 读 task,决定各行 want 需要哪些 desk 名字与算术,通常先 compile 一次拿到 program,改后 run,或直接写 program → 工具结果回来,不足则再取(上限 `sub_analyst_max_turns=8` 次 completion、`sub_analyst_evidence_calls=8` 次证据调用)→ submit → 交接核对,不过一次修复(`tool_choice=required`)→ E10 给 meta,report 经 `answer_check` 后写入 `analyst_reports`。空回复、无 tool call、超 max_turns:状态 refused,not_done 为全部行,铸一条 boundary 事实。

它不做的:不给读者写字(散文只进 analyst_reports);不派其他 analyst、不开 LLM 子 agent(`start` 只登记后台任务,树深仍为 2);不见 meta 的历史、不改 task 的问法;不编 id、不心算。

## 5. Meta-agent 内部

`handle_message` 的骨架不变:一次 briefing、≤16 次 completion、门、落库。变的是三件:工具从 `request_evidence` 换成 `delegate` 与 `read_report`;system 里的 skill 推送换成 ROSTER;loop 里 `broker.fulfil(items)` 换成派单。预期一轮 2–4 次 completion。

| 工具 | 何时在面上 | 参数 | 返回 |
|---|---|---|---|
| `delegate` | 始终 | E4 | E10 |
| `read_report` | 本轮派过单之后(as built;设计稿写「始终」) | {report_id} | verified:{domain, status, title, text, citations};refused:{…, problems 前 6 条},正文不给 |
| `repair_answer` | 仅当 verdict 悬而未决,`tool_choice=required` | {replacements} | {accepted, refusal?}(不变) |

`_BUDGET_FREE_TOOLS = (delegate, read_report, repair_answer)`:三个都不取证,域分析师的证据调用在它自己的 loop 里计。

## 6. 数据

**`analyst_reports`**(`infra/migrations/v36_analyst_reports.sql`;RLS 经 `agent_sessions.owner_id`;`delete_user.py` 在 facts 之前删):`id rep_…` · `session_id`(FK,CASCADE)· `message_id` · `task_id` · `domain` · `status verified|refused` · `title` · `brief`(JSONB)· `text` · `blocks` · `citations` · `verified` · `problems` · `prompt_tokens` · `completion_tokens` · `evidence_calls` · `created_at`;索引 `(session_id, message_id)`。

**`agent_steps.actor VARCHAR(64) NULL`**(`v36_actor.sql`):旧行 NULL 读作 meta。每条边在 agent_steps 里的样子:

| 边 | step_type | tool_name | actor | args | evidence_refs | status |
|---|---|---|---|---|---|---|
| E3 completion | llm_call | – | NULL(= meta) | –(token 列) | – | completed |
| E4 | delegate | delegate | NULL | {tasks} | – | completed |
| E5 completion | llm_call | – | sub:<domain> | – | – | completed |
| E6 compile | tool_call | compile | sub:… | {request} | –(只编不跑) | completed |
| E6/E7a run 等 | tool_call / delegation | run / read_filings / search_web / start | **NULL**(registry 在 MCP 门后写;沟通表按"最后开口的分析师"推断,打 `~`) | {program} 等 | facts | completed |
| 边界事实 | boundary | 触发它的工具名 | sub:… | – | 该事实 | completed |
| E8/E9 | brief | submit | sub:… | {brief, report 前 4k, coverage} | 本次铸的边界事实 | completed / rejected |
| report 落库 | report | report | sub:… | {report_id, status} | – | completed |
| E11 | answer | answer | NULL | {text} | – | completed / rejected |

## 7. 预算(设计默认 → 实际)

| 项 | 设计稿 | as built |
|---|---|---|
| meta completion 上限 | 16 | 16(不变) |
| sub-analyst completion 上限 | 8 每 analyst | `sub_analyst_max_turns = 8` |
| 一次 delegate 的 task 数 / 每 task 行数 | ≤4 / ≤8 | `delegation.MAX_TASKS = 4` / `MAX_WANTS = 8`(协议常量,不是 settings) |
| 证据调用 | 每轮 15 + 每 analyst +5,每 analyst ≤8 | **更正**:V23 起轮预算按消息计,同一消息内后续调用不再扣;sub-analyst 的上限在自己 loop 内计,`sub_analyst_evidence_calls = 8`;registry 不改 |
| 工具结果给 sub-analyst 的上限 | 16k chars | `sub_analyst_result_chars = 16_000` |
| E10 每域 / report 上限 | 8k / 6k chars | 未设旋钮(`report_max_chars` 撤销:声明了没人读的旋钮比没有更糟);E10 整体经 `dumps_capped(TOOL_RESULT_LIMIT)` |
| context 软上限 | 80k,只按 meta 的 prompt 峰值算 | 不变 |
| 并行 | Phase 3 | `parallel_analysts = False` |

## 8. 阶段与验收(设计 → 实际)

| 阶段 | 设计的验收 | 实际 |
|---|---|---|
| Phase 0 仪器 | 对 V33J.json 跑出 V35 基线的沟通表,与 9/15 手工整理的 Q11 表一致 | ✅ `c9f3a44`;`scripts/v36_forensics.py` 对 J 轮 Q11 与手工表一致 |
| Phase 1 串行 | 离线重放 Q11 过 C1–C5、散文过门;既有离线全绿;live 5 题冒烟 | ✅ 四提交 `c5ccc29`…`5271baf` + 冒烟 `2e7903a`:Q11 第一次出答案,主分析师 prompt 峰值中位 20k→6.2k;查出并修了两处交接缺陷(一行既答又解释;什么都没 settle 却叫 verified → absent) |
| Phase 2 报告 | 抽屉里每个数字点开是事实;refused 显示 problems | ✅ `d349238`;live 验证报告落库、refused 只回 problems |
| Phase 3 并行 | 三域题墙钟 ≤ 单域的 1.5 倍;三个 actor 的 seq 无重号 | ⏸ `4dcf02f`:三前提实测——seq 重号 18/20(红)、MCP 并发正确但收益测不出、归属设计上红;推迟,等「每个域分析师是否拿自己的 tool session」 |
| Phase 4 实测 | Q04 / Q10 / Q11 / Q15 至少通过一次;假陈述不高于 J;每题沟通表能指出每次往返的贡献 | `26a9c1f` A 轮:出答案 14/20(J 9)✅;Q04 / Q10 / Q11 ✓、Q15 ✗;**假陈述 8 条 / 5 题(J 3 / 3)✗**;沟通表 ✅。结论不回滚 v35-final,先做 T1 与 V1/V2(`ACCEPTANCE_V36 §6–§7`) |

## 9. 待拍板小项的处置

| 小项 | 处置 |
|---|---|
| 预算默认值是否照 §7 起步 | 已按表落 settings(8 / 8 / 16k),task 数 4 为协议常量 |
| 同一域一轮内是否允许第二次 delegate | 允许:`follow_up_of` 带上一次的 task_id;同一次 delegate 调用内每域至多一项(`parse_tasks`) |
| 报告抽屉随 Phase 2 上线,还是先只落库 | 随 Phase 2 上线(chip + 抽屉 + GET 端点) |
| ROSTER 的 14 段 offers 由谁写 | Claude 起草,已按草稿落进 `analytics/skill._OFFERS`;**待 boss 过目**,过目单 `WORDING.md` |

## 10. as built 与设计稿的偏差

- `delegation.run(tasks, ctx)` 拆成 `sub_analyst.run_tasks`(跑,含 `parallel_analysts` 分支)+ `delegation.for_lead`(拼 E10):delegation 不 import sub_analyst,避免环。
- `program_builder.compile` 叫 `compile_request`;成功回 `{program, skipped, note}`,失败回 `{program: None, reason, nearest, skipped}`,没有 `typecheck` 字段——类型报告由 `run` 一次报全。
- `read_report` 派过单之后才上面(设计:始终);refused 的报告只回 problems,不回正文。
- E10 的 status 多一种 `absent`(核对过了但一条都没答);C1 多一条 `answered_and_explained`。两处都是冒烟查出后加的。
- step 表多一种 `boundary`(域分析师铸的边界事实);`brief` 步的 args 带 coverage;`compile` 的 tool_call 行有 actor(进程内记),MCP 门后的 tool_call 行没有。
- `report_max_chars` 与 `delegate_max_tasks` 不进 settings;证据预算不按「每 analyst +5」而按 loop 内计数(§7)。
- `skill.roster()` 按 `match_domains` 给全部 14 条排序(设计:前两条置顶,其余原序)。
- Phase 3 推迟;`tests/test_v36_parallel_live.py` 三个 live 测试留作前提的记录(1 passed、2 strict xfail)。
- 计划里的 `tests/test_v36_skill_roster.py` 未单独建,roster 用例在 `tests/test_v36_delegation.py`。
- 措辞过目(计划 §5)先落代码后过目,过目单 `WORDING.md`。

## 11. 风险与沿用的缺口

- 意图仍可能错位:sub-analyst 也是 LLM,可能选错分母、漏行。交接核对拦住漏行与错指,拦不住指向正确的语义错——A 轮的 8 条假陈述是它的实证。缓解:report 可查、抽检、PROCEDURE 写清读法。
- ROSTER 选错域:sub-analyst 用 not_done 说「这不是我的域」,meta 多花一轮。
- digest 扣图形:I 轮 Q11 的病根在这一层,V36 只是把读者换成 sub-analyst;A 轮 Q11 的 8% 上限那问被如实报成「digest 扣下了」而不是用眼睛数。
- **A 轮新发现**(`ACCEPTANCE_V36 §6`):T1 brief 的 `not_done.why` / `caveats` 展示给主分析师却不在账本上(4 题);T2 `unreadable_window` 守卫只在 compile 路径,域分析师 79 次 run 只 7 次 compile;V1 / V2 `superlative_without_rank` 与 `subject_mismatch` 只在句子里有图形 / ticker 时才跑;V3 `[rep_…]` 这类非事实标记原样留在读者看到的文字里;T3 `fcf_to_debt` 的 unit_class;T4 held_back 事实在账本上、不在 facts 表里。
- 沿用的缺口:V35 §21 的 tool 身份三处(price.beta 的 benchmark、派生向量无 window、book.analysis 的 subject)与 `measure_mismatch` 去留;ROSTER 与 BRIEFING 文字不在账本上。
