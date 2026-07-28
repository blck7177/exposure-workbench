# MCP Boundary Plan — 把 MCP 门接进已有的身份/会话/预算机制

> **版本**:v1(2026-07-28,基于当日代码审计;审计结论见本文 §1)
> **性质**:执行方案。目标 = 缩小 `docs/TARGET_ARCHITECTURE.md` §2/§8 中 MCP 相关 target-only 声明与代码的差距,使 MCP 成为生产可用的第四个入口。
> **范围**:B(边界身份)+ C(关口入参校验)+ D(工具面统一)+ A(HTTP 传输)。**不含 E**(内部 agent 改走 MCP 客户端)——内部 agent 保持进程内 `invoke`,见 §0 非目标。

---

## 已定决策(2026-07-28,boss 拍板)

| # | 决策 | 内容 |
|---|---|---|
| **D1** | 配额**同池** | 外部 MCP 调用与 web 共享同一 user 日配额池。配额单位是"用户动作",动作从哪个门进来都是动作。**推论:配额代码零改动** —— delegation 工具经 `task_service.create_task` 扣当前 user,身份接上即生效 |
| **D2** | stdio = **local-dev 门** | 规范认可 stdio 从环境取凭证(spec 2025-11-25:stdio SHOULD NOT 走 OAuth)。但必须改掉两处:owner-role 自开 engine → 共享 factory(`app_rls`);匿名全局 session → 显式本地身份(env 必填,无默认,fail loud) |
| **D3** | **stateless** HTTP | server 不签发 `Mcp-Session-Id`(SDK `stateless=True`)。会话绑定不依赖协议状态,多副本无 sticky-session 问题 |

派生小决策(实现层,可在 review 时推翻):

- **D4 会话粒度(stateless 下)**:一行 `agent_sessions` per **(owner, kind='mcp', UTC 日)**,partial unique index 保证。日粒度与日配额同节奏;trace 按天聚合可审计。
- **D5 turn lease 不用于 MCP 调用**:turn 是对话概念(V2-E2 防并发聊天 turn);MCP 的每次 `tools/call` 是独立调用,并发正确性由预算扣减的事务性(行级锁)保证。不做每调用互斥。
- **D6 面 = scope**:`mcp:read` → `READ_CORE`(12 工具);`mcp:act` → `FACE_META_AGENT`(16 工具)。scope 不足 → `403 insufficient_scope` + `WWW-Authenticate` 挑战(spec 内建的 step-up 机制)。

---

## 0. 目标与非目标

**目标**:外部 MCP 客户端经 streamable HTTP + OAuth 2.1 连接 `/mcp`,以真实用户身份调用工具;RLS、session 预算、日配额、trace 与 web 路径**同一套机制、同一强度**;16 工具全量面按 scope 开放。

**非目标(显式排除)**:

- E:meta-agent / research worker 改为 MCP 客户端。进程内 `invoke` 不动。
- 每调用级速率限制(预算+配额之外的 QPS 控制)。
- SSE 可恢复流 / 有状态会话(与 D3 冲突)。
- server 侧 Dynamic Client Registration(客户端注册是 Clerk(AS)的事,我们只当 RS)。
- 多 AS 支持。AS = Clerk,一个。

---

## 1. 现状基线(2026-07-28 审计,全部经对抗复核)

| 事实 | 坐标 |
|---|---|
| MCP server 存在,stdio,lowlevel `Server`,12 只读工具 | `apps/mcp/server.py`(129 行) |
| 意图给 meta face,被 `faces.available()` **静默裁剪**成 12 | `server.py:39-40` + `faces.py:41-43` |
| 自开 engine,`DATABASE_URL`(**owner 角色,RLS 不绑定**) | `server.py:43-49` |
| 进程全局单 session,`owner_id=None` | `server.py:65-70` |
| `build_http_app()` 死代码且 schema 坏(FastMCP 推导出 `{"kwargs": string}`) | `server.py:97-115` |
| 未挂载、不在任何镜像、无 compose 服务、全仓无任何 MCP 客户端 | `apps/api/main.py` / `infra/Dockerfile.*` |
| `invoke()` 是唯一关口(全仓 `.fn(` 一处),预算+trace 已强制,但**零入参 schema 校验** | `tools/registry.py:140-195` |
| 身份链完整:Clerk JWT → `require_user` → contextvar → after_begin GUC → RLS(`app_rls`) | `auth_deps.py` / `auth/context.py` / `db/session.py:33-40` |
| worker 从 task 行承接身份 | `apps/worker/worker.py:107-108` |
| 预算三层:turn(max_turns)/ session(tool+external 双预算,先扣后跑)/ user 日配额(enqueue 时扣,池无默认) | `agent_session_service.py` / `usage_service.py` / `task_service.py` |
| SDK 支持 stateless:`StreamableHTTPSessionManager(app, ..., stateless=True)`(venv 实测) | `mcp` 1.28.1 |
| `jsonschema` 4.26.0 已在 venv(需提为显式依赖) | pyproject 待加 |

**Gap 一句话**:机制全部存在,MCP server 站在机制外面。本计划 = 接线,不是发明。

---

## 2. 目标拓扑

```
外部 MCP client(Claude Code / Inspector / 任意宿主)
   │  每请求 Authorization: Bearer <Clerk access token, aud=MCP_RESOURCE_URL>
   ▼
/mcp  (streamable HTTP,挂在 apps/api,stateless,无 Mcp-Session-Id)
   │ 1. 无 token / 无效 → 401 + WWW-Authenticate(resource_metadata=..., scope=...)
   │ 2. 验签(JWKS)+ aud 校验 + scope 提取        ← auth/mcp_tokens.py(新)
   │ 3. current_user_ctx.set(user_id)              ← 复用,原样
   │ 4. (owner, 'mcp', utc_date) → agent_sessions  ← 日会话行(D4)
   │ 5. scope → face 解析(严格,fail loud)        ← faces.resolve(D6)
   ▼
invoke(registry, db, session_id, name, args)       ← 一行不改;新增入参 schema 校验(B0.2)
   ▼
tool.fn → services → db(get_session_factory,app_rls,GUC 生效)

/.well-known/oauth-protected-resource/mcp          ← RFC 9728,指向 Clerk
stdio 门(local-dev):同一个 Server 对象,共享 factory,MCP_STDIO_USER_ID 必填
```

关键实现事实:**stdio 与 HTTP 共用同一个 lowlevel `Server` 对象**(`StreamableHTTPSessionManager(app=server, stateless=True)`),工具列表/schema 只有一份定义。`build_http_app()` 整体删除 —— 消灭"第二份传输实现"这个错误类别。

---

## 3. 阶段计划

依赖链:**B0 → B1 → B2 → B3 → B4 → B5**。B0 三项彼此独立,可并行;B0 整体无 MCP 依赖,单独有价值,先行合并。

### B0 — 前置修缮(独立价值,今天就该修的实债)

**B0.1 faces 严格解析(消灭:面静默漂移)**

- `faces.py` 新增 `resolve(registry, face) -> list[str]`:face 中任一工具未注册 → **raise**(列出缺的),不裁剪。
- `available()` 仅保留给真实的 build-order 容忍场景;审计当前三个调用点,能换尽换。`server.py:40` 必换 —— 换后 stdio server 启动即暴露 12/16 矛盾,**强制显式选择**:B3 之前 stdio 显式声明 `READ_CORE`(诚实),B3 起换 meta registry + 全量面。
- 测试:`test_faces_strict.py` —— 意图面含未注册工具 → 启动失败,错误信息列出缺项。

**B0.2 invoke 入参 schema 校验(消灭:未经校验的 args 直达 `tool.fn`)**

- `registry.py` `invoke()`:预算扣减前,`jsonschema.validate(args, tool.json_schema)`(Draft 2020-12);失败 → `{"error": "invalid_arguments", "problems": [...]}`,**照常落 trace step**(拒绝也留痕,与预算拒绝同型)。
- 前置动作:先审计现有 16 个 `json_schema` 的严格度(additionalProperties、required 完整性)。发现过松的 → **改 schema 使其如实**,不是放松校验。这是把"入参语义校验"从 target-only 变为 implemented 的那一步,对进程内路径同样生效(今天模型侧无 strict mode,校验本来就该在关口)。
- `jsonschema` 提为 pyproject 显式依赖。
- 测试:三条路径(meta-agent / research session / stdio MCP)各一条坏参用例 → 统一错误形状 + trace 落盘。⚠️ 全量跑既有 75+6 测试,预期若有破裂 = schema 不如实,修 schema。

**B0.3 stdio 门改造(D2;消灭:owner-role 特权连接 + 匿名会话)**

- 删 `_db_url()` / 自开 engine / `_State` 全局;改用 `db/session.get_session_factory()`(`app_rls` 角色,GUC 生效)。
- 身份:`MCP_STDIO_USER_ID` env **必填**,启动时校验 users 表存在该行;未设/不存在 → 启动失败并说明。无 DEMO 回退。
- 会话:进程启动建一行 `agent_sessions(owner=该 user, kind='mcp')`;每次 `call_tool` 前 `current_user_ctx.set(user_id)`。
- 验收:stdio 下调用 `get_issuer_snapshot`,trace 的 session 有 owner;RLS 生效(只见该 user + is_public 行)。

### B1 — HTTP 传输骨架(A;flag 关闭状态合并)

- `apps/mcp/http.py`(新):`StreamableHTTPSessionManager(app=server, stateless=True, json_response=True)` 包装现有 `Server`,产出 ASGI app。
- `apps/api/main.py`:`MCP_HTTP_ENABLED`(默认 **false**)控制是否 mount 到 `/mcp`。**flag 为 false 时不 mount** —— 匿名端点一秒都不上线(A 不得先于 B)。
- `infra/Dockerfile.api`:COPY 增加 `apps/mcp/`。compose 不加服务(同进程)。
- 删除 `build_http_app()` 全部(死代码 + schema bug 一起走)。
- 验收:flag off → `/mcp` 404 且 metadata 端点 404;本地 flag on(仅测试)→ initialize/tools/list 可达,工具 schema 与 stdio 完全一致(逐字段 diff 测试)。

### B2 — 边界身份(B 核心)

**B2.1 token 验证** — `auth/mcp_tokens.py`(新):

- 复用 clerk.py 的 JWKS 机制;新增校验:`aud == settings.mcp_resource_url`(RFC 8707 audience binding,**必须**,防 token 混用);提取 scope claim。
- `MCP_RESOURCE_URL` 进 settings:`MCP_HTTP_ENABLED=true` 且未设 → 启动失败(canonical URI 必须先于发 token 固定)。
- 依赖 **S1 spike**(见 §4):Clerk access token 的 aud/scope claim 实际形状。

**B2.2 RFC 9728 metadata + 401 挑战** — `apps/api/routes/mcp_meta.py`(新):

- `GET /.well-known/oauth-protected-resource/mcp` → `{resource, authorization_servers: [<Clerk issuer>], scopes_supported: ["mcp:read", "mcp:act"]}`。
- `/mcp` 无 token / 验证失败 → `401` + `WWW-Authenticate: Bearer resource_metadata="...", scope="mcp:read"`。

**B2.3 每请求身份管道** — `apps/mcp/auth.py`(新,ASGI 中间件,包在 mount 外层):

- bearer → B2.1 验证 → `current_user_ctx.set(user_id)` → `user_service.touch`。与 `auth_deps.py` 同构,是它的 MCP 等价物。

**B2.4 日会话行(D4)** — migration + `agent_session_service` 小改:

- partial unique index:`(owner_id, ((created_at AT TIME ZONE 'utc')::date)) WHERE kind='mcp'`。
- `get_or_create_mcp_session(db, owner_id)`:SELECT 当日行,无则 INSERT,冲突(并发首调)则重 SELECT。
- 新 setting `mcp_session_tool_budget`(日尺度,默认值待定,建议 200)。预算耗尽 → 既有 `budget_exhausted` 错误对象原样返给 MCP 客户端。

**B2.5 同池验证(D1)** — 纯测试,无实现:

- live test:同一 user 分别从 web 路径与 MCP 路径 `start_issuer_research` → **同一条日配额行**递减两次;配额耗尽时两个门同样拒绝。

- B2 整体验收:双用户 live test —— user A 经 MCP 只见 A 的 briefs + is_public;伪造 aud 的合法签名 token → 401;无 scope → 403。**flag 仍为 false,staging 环境单独开。**

### B3 — 工具面 = scope(D6 + 补齐四工具)

- stdio/HTTP 共用的 `Server` 改为构造 **meta registry**(`register_meta_tools(build_read_registry())`,16 工具),face 用 `faces.resolve` 严格解析(B0.1 保证不漂移)。
- 每请求按 scope 出面:`tools/list` 只列该 scope 的面;`tools/call` 面外工具 → `403 insufficient_scope` + `scope="mcp:act"` 挑战。**stdio 门给 `mcp:act` 等价全量面**(local-dev,环境凭证即最高信任)。
- 语义确认(实现时验证,不改代码先):`respond` 对 kind='mcp' session 的行为 = 引用校验后把最终答案落 `agent_messages`(外部宿主的"最终结论"审计记录);`start_*` 三工具因 ctx 有 user,`task_service` 记 owner + 扣配额,链路应原样通。
- 验收:`mcp:read` token 调 `start_issuer_research` → 403 挑战;`mcp:act` token → 入队成功,run owner = 该 user;`ensure_company_ready` 幂等语义不变。

### B4 — 观测与文档回写

- **parity live test**(把 P9_COVERAGE 那句无凭据的话变成真测试):同一工具、同参,web meta-agent 路径 vs MCP HTTP 路径 → `agent_steps` 形状逐字段一致(工具名/args 摘要/evidence_refs/预算扣减),仅 session kind 不同。`tests/test_mcp_parity_live.py`。
- Agent Monitor:kind='mcp' 会话可见可穿透(预计零改动,验证即可;不通则最小改)。
- token 计费说明:MCP 调用无 server 侧 LLM token(模型在宿主侧),token 列恒 0 —— 在 Observability 文档注明,防止误读成"漏记"。
- 文档回写(**wording 全部待 boss 过目后落**,此处只列清单):
  1. `TARGET_ARCHITECTURE.md` §2/§8:MCP 定位从"所有 LLM 调用的必经面"改为"第四入口(外部宿主),与内部进程内通路同关口";§0 骨架句同步。或出 v4 delta 附录。
  2. `faces.py:9` 注释("same tools, same enforcement")—— B3 后变为真,注释补"经 scope 出面"限定。
  3. `docs/spikes/P9_COVERAGE.md:39-40`:改为指向 B4 parity test 的真实证据,或删。

### B5 — 端到端验收(staging 开 flag)

负例矩阵 + 真宿主:

| 用例 | 预期 |
|---|---|
| MCP Inspector / Claude Code 经 OAuth 全流程连上,list/call | 通,工具 schema 正确(非 `kwargs` 退化形) |
| 过期 token / 错 aud / 非 Clerk 签发 | 401 + 挑战头 |
| `mcp:read` 调写工具 | 403 insufficient_scope,step-up 后成功 |
| session 日预算耗尽 | `budget_exhausted`,次日新行恢复 |
| 日配额耗尽(web 侧用光) | MCP 侧 delegation 同样拒绝(D1 同池的直接证据) |
| 双用户隔离 | A 不见 B 的 briefs/runs/facts(RLS) |
| 两副本并发(若 staging 有) | stateless 无亲和性要求,任意路由均通 |
| stdio 门回归 | B0.3 行为不回退 |

B5 全绿 = `MCP_HTTP_ENABLED` 可在生产置 true。

---

## 4. Spikes(先于对应阶段,各 ≤ 半天)

| # | 问题 | 阻塞 | 做法 |
|---|---|---|---|
| **S1** | Clerk access token 的 claim 形状:aud 是否可设为自定义 resource URL、scope 放在哪个 claim(`scp`/`scope`/自定义)、自定义 scope(`mcp:read`/`mcp:act`)在 Clerk OAuth application 里怎么声明 | B2.1 | Clerk dashboard 建 OAuth app + 真发一枚 token 解码看。Clerk 官方有 MCP 指南与 `mcp-tools`(JS),Python 侧手工验;若 aud 不可自定义 → 退路:`azp`/自定义 claim 校验,记入决策 |
| **S2** | 现有 16 个 tool json_schema 的严格度盘点(additionalProperties / required / 类型如实性) | B0.2 | 脚本遍历 + 对每个工具构造一好一坏两参;产出 schema 修订清单 |
| **S3** | `StreamableHTTPSessionManager` stateless 模式与 FastAPI mount 的组合行为:middleware 顺序、lifespan(`manager.run()` 需要 task group)、`json_response` 取值 | B1 | 最小 demo:mount + 一个工具,Inspector 连通;确认 401 能在 manager 之前由外层中间件返回 |

---

## 5. 风险与回退

- **S1 不成立(Clerk 无法发带自定义 aud 的 token)**:退路为"Clerk session JWT + 显式 `resource` claim 校验"或引入轻量 AS 代理;都属 B2.1 局部,不动其余阶段。此风险最大,故 S1 排第一。
- **B0.2 引发既有用例破裂**:预期内,按"schema 不如实则修 schema"处理;若某工具参数确需自由形状(无),才允许该工具显式豁免并注释理由 —— 无静默豁免。
- **flag 纪律**:任何阶段合并后 `MCP_HTTP_ENABLED` 生产保持 false,直到 B5 全绿。单向门:开启后发现问题 → 关 flag 即完全回退,无数据迁移负担(新增仅 index 与 setting)。
- **不做的事再确认一次**:E 不做;内部 agent 性能与事务边界因此零变化。

---

## 6. 执行顺序与工作量粗估

```
S2 → B0.1 + B0.2 + B0.3   (并行,合计 ~1.5 天)
S3 → B1                    (~0.5 天)
S1 → B2                    (~1.5 天,S1 半天在内)
B3                         (~0.5 天)
B4                         (~0.5 天 + 文档 wording 审阅一轮)
B5                         (~0.5 天,staging)
                            合计 ~5 人天
```

每阶段独立可合并、独立验收;任一阶段停下,系统都比之前更诚实(B0 后:无静默裁剪、无未校验入参、无特权 stdio;B2 后:无匿名外部会话)。
