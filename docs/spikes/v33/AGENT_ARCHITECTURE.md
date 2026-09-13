# Agent 架构：现状，与"分析师 + 证据子 agent"提案（讨论稿，2026-09-13）

承接 `MODEL_CONTRACT.md`（分析师只做决定不做抄写；回答是自然语言）。本稿回答：那么谁来填 schema、调工具、派发执行；这个角色放在哪、和 ledger/门是什么关系；要拍板的决定是哪几个。

## 1. 现状（as built，读自代码）

```
用户 ─ POST /agent/sessions/{id}/messages ─▶ meta_agent.handle_message   （api 进程内，同步，秒级）
   claim_turn + 扣 chat_turn 配额（先于任何 LLM 调用）
   loop ≤16 次 completion：
       LLM ⇄ 面 [describe, run, read_filings, read_book, search_web, start, think, respond]
       每个 tool call → MCP client → /mcp/meta → registry.invoke：校验参数 → 预算 → 执行 → adapter 变 facts → 落 agent_steps + facts
       出口 = respond（claims 门，读 ledger(session_id)）；门不收就 _GATE_EXHAUSTED_TEXT
   start(kind) → tasks 表 → worker（另一个进程）
       readiness / exposure_run：机械、幂等，无 LLM
       issuer_research → research_session：第二个 LLM loop，自己的 agent_session，face 无委托工具（树深封顶 2），出口 submit_brief = 同一个门 → brief
   brief 回到对话：read_book(ticker,['brief']) → adapter → 新 facts（brief 本身不是证据）

日报（另一条路）：exposure_workflow 组 ReportInput → direct_llm_agent 一次 completion → report_verification 逐数核对该 run 的行；不重试
```

四条今天成立的性质：

- **循环极薄，行为由 face 与门塑造**；系统提示只讲角色与"为什么"（MODULE_NOTES M10）。
- **探索者即写作者，无交接**（`research_session` docstring："the explorer IS the writer — no hand-off — so every number it writes is one it just fetched"）。两个 loop 都是这个形状。
- **ledger 按 session**；门只认本 session 完成步骤的 facts。research run 的 facts 不在对话 session 上。
- **委托非阻塞**，进度靠 `read_book(task_…)`；每轮 15 次证据调用、终身 40；context 软上限 80k。

日报那条路是仓库里唯一的反例：证据由代码组、模型只写、门逐数核。`report_verification` 自己写了为什么它能比另两个门更严——"the model is never asked for [the evidence set]"。

## 2. V33 对"探索者即写作者"说了什么

那条设计的前提是：写作者自己取过的数，写出来就是对的。V33 的 19 个通过答案里 12 个含读者可见的假陈述，数字确实都是它取的（Q08 反向最高级、Q17 十个名字错位、Q18 指错 fact、Q14 日期槽填百分比）。**取到 ≠写对**；保证正确的从来是门和共享的 ledger，不是"同一个人取和写"。

同时这个人的上下文里装着两份工作的材料：到 respond 时 12–51k tokens，几乎全是工具 JSON 与拒绝；20 题里 36 次 run、61 次 respond；program 平均写 1.8 次才过。分析与抄写在一个 context 里争注意力。

所以你提的交接，在今天的证据下是成立的：**只要 ledger 共享、门照核，交接不损失正确性；它拿走的是抄写。**

## 3. 提案按四角色落位

```
分析师（LLM，智能）             证据子 agent（tool + skill 的操作者）              validation
  读：目录（带身份维度）、        读：分析师的请求、签名表、目录                     读：分析师的自然语言、本 session ledger
      证据摘要、边界              做：procedure(fills) / 写 program / 调工具 / 派发     查：数字对账本；关系词对 fact 身份；≤2 次
  写：证据请求（决策级）、            处理 type/spelling 拒绝；分类 boundary
      自然语言回答                写：facts（上 ledger）+ 边界 fact + 摘要
  不做：任何 schema、任何 id      不做：解释结果、写任何给读者的话
```

子 agent 不是第五个角色：它是 tool 与 skill 被**操作**的地方。两条互斥线要画死：分析师不碰 program，子 agent 不写 prose。否则要么两个操作者，要么两个写作者。

## 4. 要拍板的决定

**D1 请求的形式：自然语言，还是决策级结构。**
自然语言完全符合"分析师只说人话"，但让第二个大脑猜第一个大脑指的是哪个主体、哪个量、哪个窗口——这是 9/9 复审的 R2，错了无法归属。决策级结构是 `{subjects, what, window, compare}` 这类字段，值全部是分析师刚在目录里看到的名字；这正是分析师本来就必须决定的东西，不含拼写、类型、id。**推荐后者**；值允许目录里的显示名，名字路由是子 agent 的事。

**D2 子 agent 里的 LLM 用在哪。** 三层：`procedure(fills)` 是确定性的；filing/news/start 是参数平凡的工具调用，从请求直接映射；只有 procedure 不覆盖的**组合**需要一个 program 作者。推荐：LLM 只在组合处，它读的是签名表 + 目录 + 请求，写完先过静态类型检查（一次报全），再执行。请求越结构化，这一层越接近编译器。

**D3 子 agent 跑在哪。必须在同一 session、同一 message 内，共享 tool_session 的 token。** 这是与现有 research 子 agent 的本质区别：research run 另开 session，产物是 brief；这里的产物是 facts，而门只认本 session 的 ledger。子 agent 若另开 session，分析师写的每个数字都会被拒 not_on_ledger。

**D4 子 agent 返回什么。** facts 摘要（值按读者精度、身份、id）与边界（分类过的 absence/boundary fact），不返回 program、拒绝原文、原始 payload。**返回里出现的每个值都在 ledger 上**，否则 Q14 重演。

**D5 分析师有哪些工具。** 只有 `request_evidence`（进程内，不走 MCP），出口是纯文本。read_filings/search_web/start 全部经子 agent；分析师的请求里说"要 filing 里关于 X 的原文"、"要 T 近两周的新闻"、"把 T 准备好"。

**D6 预算与深度。** 每轮 15 次证据调用归子 agent；子 agent 没有 LLM 子 agent（只能 start 后台任务），在轮深度仍是 2；research run 仍是后台、异步、另 session。

**D7 观测。** 新 step 类型记录 request / program / typecheck 报告 / digest，把今天不落盘的 note 与拒绝原文一并落盘。trace 才能回答"分析师要的 vs 子 agent 做的"。

**D8 另两条路的走向。** research run 与日报改成同一形状：子 agent 组证据（brief 六节多半是 procedure）→ 写作者写自然语言 → 门核数。日报已经是这个形状，只差把写作者的证据换成 ledger。

## 5. 风险与代价

| 风险 | 缓解 |
|---|---|
| 意图在交接处丢失 | D1：请求是决策级字段，值来自目录；子 agent 不做业务判断 |
| 分析师收到边界却不告诉读者 | desk_rule 要求说出；门无法强制，靠抽检；摘要里边界排在最前 |
| 子 agent 在类型错误上循环 | 静态检查一次报全，通常 1–2 轮；上限后返回 boundary，不吞掉 |
| 摘要给多给少 | 分析师可追加请求"给我 X 的全部点"；默认给端点与身份 |
| 两套 prompt | 分析师 prompt 去掉 3.7k 工具 schema 与 12–51k JSON；子 agent prompt = 签名(≈1.6k)+目录+请求。总量预计下降，completion 从平均 8 次降到分析师 2–3 + 子 agent 1–3 |

## 6. 用 V33 检验

| 题 | 提案下的流程 |
|---|---|
| Q08 | 分析师请求 {MSFT,GOOGL,AMZN}×{capex_intensity, roic}，最近 3 财年，compare=rank latest → 子 agent 写 program，类型检查提示 latest→vector→rank → 返回 6 个 series + 2 个 ranking → 分析师写 "Microsoft spends the most…" → 关系词检查对 rank fact |
| Q14 | 子 agent pick 的日期成 fact（tool 修）→ 分析师拿到带 id 的起点日期 |
| Q11 | 请求"谁超过 8%" → 子 agent：无阈值原语 → boundary fact + 全部权重的 ranking → 分析师照 ranking 列出并说明 desk 不做筛选 |
| Q17 | 请求 top5 新闻 + 十日相对收益 → 子 agent：search_web ×5；window_return 最短 1m → boundary → 分析师说 desk 最短窗口一个月 |
| Q07 | 分析师在目录里看到 sector，只有三家 Technology → 先纠正"五家 tech"这个前提 |
| Q13 | 子 agent 返回 scenario_refit 边界 fact → 分析师引用，不编 id |

## 7. 与现有代码的对应（模块层）

- `agents/meta_agent.py`：分析师 loop；tools=[request_evidence]；出口=纯文本；门=数字+关系词核对。
- 新 `agents/evidence_broker.py`：进程内；共享本轮 tool_session；自己的 llm_session 行；面 = 今天的 FACE_META_AGENT − {respond, think}。
- `services/program_service.py`：`typecheck(program)`；字面量统一；pick 字面量成 fact；方法结果带 window。
- `analytics/skill.py`：PROCEDURES 可带 fills 直接调用。
- `services/claims.py` → 数字与关系词核对器（前文已定）。
- `agents/research_session.py`：后续同形改造。
