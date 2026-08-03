# MCP Plan — agent 面落地:内部 agent 经 in-memory MCP 消费工具面

> **版本**:v2(2026-08-03)。取代并删除 `MCP_BOUNDARY_PLAN.md` v1(内容在 git 历史;其"第四入口/OAuth 产品化"重心与设计目标不符,见 §0 N1)。
> **性质**:执行方案。目标 = 把 MODULE_NOTES §M10「MCP 双轨规则」从声明变为实现:**Agent 面 = MCP,唯一;代码面 = fn 直调;两面共穿一个 wrapper。**
> **一句话**:MCP server 装着工具面(tools+DB 在门后),消费者是**本项目自己写的 meta-agent 与 research subagent**,经 in-memory transport 连入。没有外部宿主,没有远程门,没有第三方。

---

## 0. 已定决策(2026-08-03,boss 拍板)

| # | 决策 | 内容 |
|---|---|---|
| **N1** | MCP = **agent 面**,不是产品入口 | 消费者 = 内部两个 loop(`agents/meta_agent.py` / `agents/research_session.py`)。OpenClaw / Claude Code / 任何外部宿主**不是**本系统的大脑,出范围。sm-master 类比只取其 server 侧模式(自家工具包进 MCP server 由 agent 消费),不取其消费者形态 |
| **N2** | web 内置 chat **保留**(核心功能) | chat 面板是 meta-agent 的产品外壳;E 迁移对用户不可见,产品形态零变化 |
| **N3** | E 形态 = **in-memory transport** | `mcp.shared.memory.create_connected_server_and_client_session`(SDK 1.28.1 实测可用,直接接受现有 lowlevel `Server`)。**每 chat turn / 每 research run 建一对 client-server**,face registry、session_id、message_id、租户身份在建对时绑定。无 HTTP 回环、无子进程 |
| **N4** | tools-first;resources / prompts 后置 | 主通道只有 tools。可@引用的 resources、slash-command prompts 等增益层,等真实痛点出现再议 |
| **N5** | 旧 B1/B2/B5 **封存** | HTTP 传输、OAuth 边界(Clerk/RFC 9728/8707/scope→face)、staging 验收整体封存(§5)。唤醒条件 = 出现真实远程消费或第三方产品目标。**公网部署与 MCP 自此解耦** |

**从 v1 继承、仍然成立的判断**:配额同池(委派经 `task_service.create_task` 扣当前 user,内部路径本来如此,零改动);stdio 凭证从环境取(spec 2025-11-25 规范形);无 per-call turn lease(并发正确性由预算扣减的事务性保证);状态全部走 server-minted 句柄(`run_id`/`fact_id`/`calc_id` 当普通参数)——此形状已被 spec 2026-07-28 改版钦定(protocol session 整体移除,SEP-2567),**无迁移债**。

---

## 1. 现状基线(2026-08-03,全部实测/实读)

| 事实 | 坐标 |
|---|---|
| meta-agent 直接函数调用关口:`invoke(registry, db, session_id, name, args, message_id=…)` | `agents/meta_agent.py:137-138` |
| research subagent 同样直调 invoke;face 裁剪 = skip 语义 | `agents/research_session.py`(loop 内) |
| 工具面实测:read registry **16**,meta registry **20**(meta-only = `ensure_company_ready` / `start_issuer_research` / `start_exposure_run` / `respond`) | `tools/definitions.py:239` / `tools/meta_tools.py:205` |
| `invoke()` 是唯一关口(全仓 `.fn(` 一处),预算+trace 已强制,**零入参 schema 校验** | `tools/registry.py:149` |
| `faces.available()` 静默裁剪(意图 20 → stdio 实拿 16) | `tools/faces.py:41-43` + `apps/mcp/server.py:39-40` |
| stdio server 自开 engine(`DATABASE_URL`,owner 角色,RLS 不绑定)+ 进程全局匿名 session | `apps/mcp/server.py:43-49, 65-70` |
| stdio server 已显式 `per_turn=False`(V3-R6) | `apps/mcp/server.py:67` |
| `build_http_app()` 死代码且 schema 坏(推导成 `{"kwargs": string}`) | `apps/mcp/server.py:97-115` |
| in-memory helper 存在:`create_connected_server_and_client_session(server: Server\|FastMCP, …)` | venv `mcp` 1.28.1 实测 |
| `jsonschema` 4.26.0 已在 venv,未进 pyproject | 待提显式依赖 |

**Gap 一句话**:关口、面、预算、RLS、审计全部存在且在用;缺的只是——agent 的调用没有穿协议层,而 stdio server 站在身份机制外面。本计划 = 给既有关口套上 MCP 外衣并让两个 loop 从外衣走,不发明任何新强制。

---

## 2. 目标拓扑

```
web chat 用户                     worker(task 行承接身份)
   │ (产品外壳,零变化)                │
   ▼                                  ▼
meta-agent loop                  research subagent loop
   │ 每 turn 建对                     │ 每 run 建对
   ▼                                  ▼
in-memory MCP client ──────────  in-memory MCP client
   │  tools/list · tools/call         │
   ▼                                  ▼
MCP Server(build_mcp_server(registry, face, session, identity…) 参数化构造)
   │  call_tool → invoke()  ← 一行不改的六站关口
   ▼
invoke():face 严格 → schema 校验 → 预算先扣 → tool.fn → evidence 采收 → trace 落盘
   ▼
services → get_session_factory()(app_rls,SET LOCAL app.user_id)→ Postgres RLS

旁路(不变):recipe / REST wrapper / workflow 代码直调 fn(代码通路,只留台账)
侧门(降级):stdio 入口 = local-dev debug 门,同一构造器,MCP_STDIO_USER_ID 显式身份
```

---

## 3. 阶段计划

依赖链:**P1 → P2 → P3 → P4 → P5**。P1 三项彼此独立可并行;P1 无 MCP 依赖、单独有价值,先行合并。

### P1 — 关口硬化(原 v1 B0 三件,全部保留;与消费拓扑无关的实债)

**P1.1 faces 严格解析**(消灭:面静默漂移)
- `faces.py` 新增 `resolve(registry, face) -> list[str]`:face 中任一工具未注册 → **raise** 并列出缺项,不裁剪。`available()` 仅留给真实 build-order 容忍场景,审计现有调用点能换尽换。
- 测试:意图面含未注册工具 → 启动失败,错误信息列出缺项。

**P1.2 invoke 入参 schema 校验**(消灭:未经校验的 args 直达 `tool.fn`)
- 前置 S2 盘点:遍历 20 个工具 schema 的严格度(`additionalProperties` / `required` / 类型如实性),产出修订清单;过松的**改 schema 使其如实**,不放松校验。
- `invoke()` 预算扣减前 `jsonschema.validate(args, tool.json_schema)`(Draft 2020-12);失败 → `{"error": "invalid_arguments", "problems": [...]}`,照常落 trace step(拒绝也留痕)。`jsonschema` 提为 pyproject 显式依赖。
- 测试:meta / research / stdio 三条路径各一条坏参用例 → 统一错误形状 + trace 落盘。全量跑既有 410+102,预期若有破裂 = schema 不如实,修 schema。
- ⚠️ 排程注意:本项与 harness 收口批(evidence 采收单一路径)同在 `registry.py`,**相邻排程**,一次回归。

**P1.3 stdio 门去特权 + 降级定位**(消灭:owner-role 特权连接 + 匿名会话)
- 删 `_db_url()` / 自开 engine / `_State` 全局;改用 `db/session.get_session_factory()`(`app_rls`,GUC 生效)。
- `MCP_STDIO_USER_ID` env **必填**,启动时校验 users 表存在该行;未设/不存在 → 启动失败并说明。无 DEMO 回退。
- 文档定位:local-dev **debug 门**(人工用 Inspector 之类连上排查),非目标路径,不做验收矩阵。

P1 验收(offline):faces strict / 三路径坏参 / 410+102 全绿。(live):stdio 连上调 `get_issuer_snapshot`,session 有 owner,RLS 只见该 user + is_public。

### P2 — Server 适配层(一份适配代码,两个入口用)

- `apps/mcp/server.py` 重构为参数化构造器:`build_mcp_server(registry, face, *, db_factory, session_id, message_id=None) -> Server`。现在的"硬编码 read registry + 进程全局 session"形状废除;stdio 门与 in-memory 对都调这个构造器。
- face 用 P1.1 的 `faces.resolve` 严格解析;`tools/list` **确定性排序**(spec 2026-07-28 SHOULD,利宿主 prompt cache)。
- server instructions 写证据纪律的 why(与两个 system prompt 同源,不新增行为规则清单)。
- `call_tool` handler:显式设置绑定身份(`current_user_ctx.set`,与 stdio 门同型,**不赌 contextvar 跨任务快照**)→ `invoke()` → 结果按 MCP content 规范返回;`invalid_arguments` / `budget_exhausted` 等结构化错误以 `isError` + 原 payload 透传,信息不降级。
- 删除 `build_http_app()` 全部(死代码 + `{"kwargs": string}` schema bug 一起走)。
- 验收(offline):构造器对 META/RESEARCH 两 face 出面正确(数量以 `faces.resolve` 为准);tools/list 两次调用逐字节一致;registry schema ↔ MCP tool schema 逐字段 diff 测试(吸收 v1 的"非 kwargs 退化形"验收);错误透传形状测试。

### P3 — E 迁移:meta-agent 改走 in-memory client

- `handle_message` 每 turn:`build_mcp_server(meta_registry, FACE_META_AGENT, db_factory=…, session_id=…, message_id=…)` → `create_connected_server_and_client_session(server)` 建对;`tools` 改从 `client.list_tools()` 取(→ OpenAI tools 参数的映射函数,带保真测试);`meta_agent.py:137-138` 的 `invoke(...)` 改 `client.call_tool(name, args)`;respond 判定、`_GATE_EXHAUSTED_TEXT` 收敛点、prompt_peak 记账全部不变。
- 异常路径:对的生命周期跟 turn,`finally` 关闭;in-memory 无网络断连类错误。
- 验收(offline):loop 相关单测改造后全绿。**parity(本阶段核心验收)**:同一问句 before/after 两跑 → `agent_steps` 逐字段一致(工具名 / args 摘要 / evidence_refs / 预算扣减序列),仅时间戳异。(live):web chat 一轮带引用全程通过,Agent Monitor 穿透正常;**双用户交替**(A/B 轮流发消息)→ RLS 隔离与身份绑定无串扰。

### P4 — E 迁移:research subagent 同法

- `run_research_session` 每 run 建对;face 裁剪(skip 语义)不变——建对时传裁剪后的 face,能力仍是"物理不存在"而非 in-loop if。
- 验收(live):完整 issuer research 跑通,brief 六块引用全过 submit 门,终身 40 预算扣减正常;worker 进程内建对(身份来自 task 行)与 API 进程内行为一致。

### P5 — 收尾

- 全量回归 410+102 + 新增测试全绿;parity 测试进常驻回归(防两轨漂移的持续证明)。
- 文档回写:本文件状态标注、README 的 MCP 段、`TARGET_ARCHITECTURE.md` §2/§8 残留的"外部宿主(OpenClaw / Claude Code)"字样清理(**wording 全部先过 boss 再落**)。
- MODULE_NOTES §M10 已于 2026-08-03 同步(先于实现,文档先行)。

---

## 4. 风险与退路

- **contextvar 跨任务边界**:不依赖"建对时快照恰好带上身份"——P2 在 `call_tool` handler 里**显式 set 绑定身份**,与 stdio 门同型;双用户交替 live 测试钉死。此为本计划唯一真正的新技术点。
- **每 turn 建对的开销**:task spawn + initialize 握手,进程内量级微小。若实测可感 → 退路:per-session 复用对 + 每 call 重绑 message_id(构造器结构已预留)。**先测后优化,不预付复杂度。**
- **schema 映射保真**:`registry.json_schema` → MCP tool → OpenAI tools 参数,两跳都有逐字段 diff 测试;任何一跳退化(如 `kwargs` 形)= 测试红。
- **P1.2 引发既有用例破裂**:预期内,按"schema 不如实则修 schema"处理;确需自由形状的工具(当前认知:无)才允许显式豁免 + 注释理由,无静默豁免。
- **协议版本**:SDK 1.28.1 = spec 2025-11-25 系;本计划全部特性(tools、in-memory、stdio)不触碰 2026-07-28 移除的能力(protocol session / handshake 依赖),升级 SDK 时无结构性迁移。

---

## 5. 封存件(原 v1 B1/B2/B5,设计见 git 历史)

| 件 | 一句话 | 唤醒条件 |
|---|---|---|
| B1 HTTP 传输 | `StreamableHTTPSessionManager(stateless=True)` 挂 `/mcp`,flag 默认关,flag off 不 mount | 出现真实远程消费者 |
| B2 OAuth 边界 | Clerk AS + RFC 9728 metadata + RFC 8707 aud 绑定 + scope→face(read=读面 / act=全量面)+ (owner,'mcp',UTC日) 日会话 | 同上;若第三方成为产品目标则全套唤醒 |
| B5 staging 验收 | 负例矩阵 + 真宿主 E2E | 随 B1/B2 |

唤醒时注意:①spec 已到 2026-07-28(protocol session 移除、DCR 弃用改 CIMD),v1 设计按 2025-11-25 写成,需重校;②唤醒的那一刻起,公网部署重新成为其验收前置——在那之前两者无耦合。

---

## 6. 工作量粗估

```
P1(S2 + 三件硬化)      ~1.5 天   ← 与 harness 收口批相邻排程(同在 registry.py)
P2(Server 适配层)       ~0.5 天
P3(meta-agent 迁移)     ~1 天
P4(research 迁移)       ~0.5 天
P5(回归 + 文档)         ~0.5 天
                          合计 ~4 天(harness 收口批另属 harness 线,~1 天)
```

每阶段独立可合并、独立验收;任一阶段停下,系统都比之前更诚实(P1 后:无静默裁剪、无未校验入参、无特权 stdio;P2 后:无死代码传输、面构造单一来源;P3/P4 后:agent 通路 = MCP 通路,字面成立)。
