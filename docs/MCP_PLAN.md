# MCP Plan — agent 面落地与常驻化:agent 经常驻 MCP server 消费工具面

> **状态(2026-08-19)**:v2(P1–P5,in-memory 形态)已完成并在运行栈实测(§7);v3 的 **R1–R4 已落地**(2026-08-08:内部身份件 / 构造器拆分 + 常驻 app / infra / 消费者迁移)——生产路径上已无 in-memory transport,两个 loop 都经内部 bearer 连常驻 `exposure-mcp`。**R5(守卫与回归)与 R6(文档)本批同步**;逐阶段 commit 与实测计数见 §8(待填)。遗留见 §8 尾;mcp 2.0 迁移(§7 P5 行)的最大障碍已随 R4 消失,只剩测试 fixture 一处。
> **版本**:v3(2026-08-08)。取代 v2 的 N3/N5 两条决策(v2 全文在 git 历史;其阶段成果 P1–P5 与实测记录 §7 保留,是 v3 的地基而非弃案)。
> **性质**:执行方案。目标 = 在 v2 已建立的「Agent 面 = MCP,唯一;代码面 = fn 直调;两面共穿一个 wrapper」之上,把 MCP server 从**每 turn/run 现造**改为**常驻独立进程**,身份从**构造时绑定**改为**逐请求认证**。
> **一句话**:一个常驻 exposure-mcp 容器装着工具面(tools+DB 在门后);api 的 meta-agent 与 worker 的 research subagent 作为 client,持内部 JWT 逐请求连入;LLM 调用仍在 loop 里,不进 MCP。

---

## 0. 已定决策

### v3(2026-08-08,boss 拍板)

| # | 决策 | 内容 |
|---|---|---|
| **N6** | MCP server **常驻独立进程**(取代 N3) | 新容器 `exposure-mcp`,streamable HTTP,`stateless=True`。容器间走 compose 内网;另发布 **127.0.0.1 一个端口**(`MCP_HOST_PORT`,默认 8104)——live parity 守卫从宿主跑,够不到的面钉不住任何东西,而 loopback 绑定与已发布的 Postgres 同姿态(Docker 只有 0.0.0.0 绑定才穿透 ufw)。agent 调用任何工具必须向它发请求;agent 的 loop 本身不在 MCP 里 |
| **N7** | 身份 = **逐请求内部 JWT,HS256 共享密钥** | 密钥 `MCP_INTERNAL_SECRET`(.env)。claims:`sub`=user_id、`sid`=session_id、`mid`=message_id(可选)、`face`、`exp`。api 每 turn 铸、worker 每 run 铸。中间件是**唯一**解 token 的地方;缺任何 claim / 坏签 / 过期 = 结构化拒绝整个请求;**禁止 token passthrough**(不转发给任何上游) |
| **N8** | token 有效期 = **30min,与 task lease 对齐** | 同 `TASK_LEASE_SECONDS=1800`:token 活得过最长合法 run,死得比僵尸 run 早。验签留 60s 时钟余量 |
| **N9** | face 保持**物理**:每 face 一个挂载点 | `/mcp/meta`、`/mcp/research` 各自用 `build_mcp_server` 构造、进程内常驻。**拒绝**"单端点 + token 选 face"——那是 `faces.available()` 静默裁剪的复活形态。token 的 `face` claim 必须与挂载点一致,双保险 |
| **N10** | 工具执行**搬进 mcp 容器** | tools fn 随 server 走:`exposure-mcp` 需要 `DATABASE_URL_APP`、`TAVILY_API_KEY`、`EDGAR_IDENTITY`、`OPENAI_API_KEY`(检索 embedding 在工具内)与 `./data` 卷。api/worker 各自保留 OPENAI key——**LLM completion 仍在 loop 里,不穿 MCP** |
| **N11** | 生产路径**唯一** | `tool_session` 内部换 `streamablehttp_client`;in-memory helper 降级为**纯测试 fixture**,import 守卫禁止 agents 层再碰。无双轨、无回退 |
| **N12** | **B2 仍封存**(部分取代 N5) | 内部 JWT ≠ 对外 OAuth 边界。B1 于本日以**内部形态**唤醒(boss 拍板:常驻是期望架构,原"真实远程消费者出现"唤醒条件对 B1 作废);B2/B5 唤醒条件不变 |

### v2(2026-08-03,boss 拍板;N3/N5 已被 v3 取代,其余仍然成立)

| # | 决策 | 内容 |
|---|---|---|
| **N1** | MCP = **agent 面**,不是产品入口 | 消费者 = 内部两个 loop(`agents/meta_agent.py` / `agents/research_session.py`)。外部宿主不是本系统的大脑,出范围 |
| **N2** | web 内置 chat **保留**(核心功能) | chat 面板是 meta-agent 的产品外壳;迁移对用户不可见,产品形态零变化 |
| ~~**N3**~~ | ~~E 形态 = in-memory transport,每 turn/run 建对,身份在建对时绑定~~ | 被 **N6/N7** 取代。in-memory 阶段完成了它的历史任务:先让"agent 通路 = MCP 通路"字面成立并全量实测,再动拓扑 |
| **N4** | tools-first;resources / prompts 后置 | 主通道只有 tools,增益层等真实痛点 |
| ~~**N5**~~ | ~~旧 B1/B2/B5 封存~~ | 被 **N12** 取代:B1 以内部形态唤醒;B2/B5 仍封存 |

**从 v1/v2 继承、仍然成立的判断**:配额同池;stdio 凭证从环境取;无 per-call turn lease(并发正确性由预算扣减的事务性保证);状态全部走 server-minted 句柄(`run_id`/`fact_id`/`calc_id` 当普通参数)——spec 2026-07-28 已钦定此形状(protocol session 移除,SEP-2567)。**常驻 + stateless 与该改版方向一致。**

---

## 1. 现状基线(2026-08-08,全部实读/实测)

| 事实 | 坐标 |
|---|---|
| server 每 turn/run 现造;face/session/租户身份是**构造参数** | `tools/mcp_server.py:50-58` |
| `call_tool` handler 内已有**显式身份绑定**(P2 机制,contextvar set)——v3 保留该站,只换来源 | `tools/mcp_server.py:106` |
| 消费者经 `tool_session`(list_tools 一次 + call;transport 错误结构化返回,loop 永不炸) | `agents/tool_session.py:83-100` |
| 消息是真 JSON-RPC(`tools/list`/`tools/call`),parity 测试钉"传输不改记录" | `tests/test_transport_parity_live.py` |
| 双租户并发正确性已实测(构造绑定形态下) | commit `e5a9c42` |
| stdio 调试门:同一构造器,`MCP_STDIO_USER_ID` 显式身份,借 app_rls factory | `apps/mcp/server.py` |
| 工具执行发生在 api/worker **进程内**(server 对象在进程里) | — |
| SDK 1.29.0(pin `mcp>=1.28,<2`);`StreamableHTTPSessionManager` 与 `streamablehttp_client` 实测可用,支持 `stateless=True` | 2026-08-08 实测 |
| 运行栈全链路已验:chat turn(数字验证门拒→重试→过)+ research run(30 工具调用、brief 21 引用) | §7 P5 行 + 本日实测 |

**Gap 一句话**:server 已是"参数化构造、关口在内"的正确形状,缺的只是——让它长命、把"构造时绑定身份"换成"逐请求认证身份",并把消费者从内存流搬到 HTTP。

---

## 2. 目标拓扑(执行后)

```
┌──────────┐   ┌─────────────────┐        ┌─────────────────────────────┐
│ 浏览器    │──▶│ exposure-api     │        │ exposure-mcp(新容器,常驻)   │
└──────────┘   │  meta-agent loop │        │  streamable HTTP, stateless  │
               │  (LLM 调用在此)   │        │                              │
               │                  │ Bearer │  中间件:验内部 JWT →         │
               │  每 turn 铸 token │──────▶│  绑 user/session/message ctx │
               └────────┬─────────┘ HTTP   │       │                      │
                        │ 入队        JSON-RPC     ▼                      │
               ┌────────▼─────────┐        │  /mcp/meta   (20 工具,物理) │
               │ exposure-worker   │        │  /mcp/research(研究面,物理) │
               │  research loop    │ Bearer │       │                      │
               │  (LLM 调用在此)   │──────▶│       ▼                      │
               │  每 run 铸 token  │ HTTP   │  invoke() 六站关口(不动)    │
               └──────────────────┘        │       ▼                      │
                                           │  tools fn → services         │
                                           │  (工具执行在本容器)           │
                                           └──────────┬──────────────────┘
                                                      ▼
                                    Postgres(app_rls + SET LOCAL → RLS)

旁路(不变):recipe / REST wrapper / workflow 代码直调 fn(代码通路,只留台账)
侧门(不变):stdio 调试门 = 同一构造器,进程内,MCP_STDIO_USER_ID 显式身份
封存(不变):B2 对外 OAuth——内部 JWT ≠ 对外边界,唤醒条件依旧
```

**构造器拆分**:`build_mcp_server(registry, face, db_factory)` 变长命(去掉 per-session 参数);请求上下文(user/session/message)由中间件逐请求写入 contextvar,`call_tool` handler 的显式绑定站保留原样、只换来源。stdio 门的"请求上下文"= 启动时环境变量一次设定,行为不变。

---

## 3. 阶段计划(R1 → R6;R1–R3 纯新增不切流量,R4 才切)

### R1 — 内部身份件(~0.5 天)

- `auth/internal_token.py`:`mint(user_id, session_id, face, message_id=None)` / `verify(token) -> Claims`。HS256,`MCP_INTERNAL_SECRET`,`exp` = 30min,验签 60s leeway。
- HTTP 中间件:`Authorization: Bearer` → verify → 写请求级 contextvar(user/session/message/face)。中间件是唯一解 token 处。
- 验收(offline):坏签 / 过期 / 缺 claim / face 与挂载点不匹配 → 全部结构化拒绝,负例矩阵逐条测。(live,R4 后补):**双租户并发 HTTP 实测**,同 P5 形状。

### R2 — 构造器拆分 + 常驻 app(~1 天)

- `tools/mcp_server.py`:`build_mcp_server(registry, face, db_factory)`;handler 从请求 contextvar 取身份与 session。确定性排序、`validate_input=False`、错误透传形状全保持。
- `apps/mcp/http.py` 新入口:Starlette + `StreamableHTTPSessionManager(stateless=True)`,`/mcp/meta` 与 `/mcp/research` 各挂一个构造出的 server。
- stdio 门(`apps/mcp/server.py`)改走新构造器签名,行为不变。
- 验收(offline):两挂载点 tools/list 面正确且逐字节确定;registry schema ↔ MCP tool schema 逐字段 diff 保持;stdio 门回归绿。

### R3 — infra(~0.5 天)

- `infra/Dockerfile.mcp` + compose service:容器间内网 + 宿主 loopback 端口(R5 的 live 守卫前置;test_deploy_config 钉死 127.0.0.1 绑定),env 按 N10,`./data` 卷,healthcheck(`/mcp/meta` 握手或专用 `/healthz`),`depends_on: postgres healthy`;api/worker `depends_on: exposure-mcp`。
- 验收:栈起;容器内无 token 调用 = 拒;宿主机 curl 不可达(端口未发布)。

### R4 — 消费者迁移(~1 天)

- `agents/tool_session.py` 内部:`create_connected_server_and_client_session` → `streamablehttp_client(MCP_URL_<FACE>, headers=Bearer)` + `ClientSession`;对 loop 的接口(tools 列表 + `call`)不变。
- `handle_message` 每 turn 铸 token;`run_research_session` 每 run 铸(身份仍来自 task 行)。
- 生产路径删 in-memory;helper 移为测试 fixture。
- 验收(live):栈上真 chat turn + 真 issuer research run,行为与 2026-08-08 实测逐项一致(数字验证门、submit 门、预算、RLS)。

### R5 — 守卫与回归(~1 天)

- parity 测试升级:直调 invoke vs HTTP 全链路,`agent_steps` 逐字段一致。
- face 物理性负例:对 `/mcp/research` 调 meta-only 工具 = 未知工具(物理不存在,非 403)。
- 双租户并发 HTTP 实测(R1 验收的 live 半)。
- import 规则更新:agents 层不得 import in-memory helper;`llm/` 仍不触库。
- 每 call 延迟实测钉数(预期 1–3ms/call,量级依据:30 call/run)。
- 全量回归 offline+live 绿;新守卫经变异测试。

### R6 — 文档(~0.5 天,wording 先过 boss 再落)

- `TARGET_ARCHITECTURE.md` §2/§8:in-memory 拓扑 → 常驻拓扑;§3 目录列表补 `apps/mcp/http.py`。
- README MCP 段;MODULE_NOTES §M10 同步;本文件状态标注 + §7 追加 R 行。

---

## 4. 风险与退路

- **新 SPOF**:mcp 容器挂 = 所有 agent 转不动。缓解:restart policy + healthcheck;`tool_session.call` 的结构化错误契约保证 loop 不炸只降级;`stateless=True` 使将来多副本平凡。
- **换掉的保证**:v2 的"构造时绑定 → 物理上不可能弄错租户"换成"中间件必须正确"。这是常驻化的**真实价格**,用三层补偿:中间件唯一解 token 处 + 负例矩阵 + 双租户并发实测。
- **token 生命期**:30min 与 task lease 同长;同机部署时钟偏差可忽略,仍留 60s。密钥轮换(双密钥验证窗口)**后置**,不进本计划。
- **延迟**:进程内 → loopback HTTP。R5 实测钉数,超预期再议(先测后优化,不预付复杂度)。
- **mcp 2.0 迁移面**:R4 删掉生产路径的 in-memory 后,2.0 的 breaking(helper 被删)只剩测试 fixture 一处。建议 R6 后紧随做 2.0 迁移,带验收。
- **成本洞正交**:usage 不穿 MCP(LLM 调用在 loop 里),常驻化不改变成本入账讨论(A/B)的任何前提;那是另一个待拍板件。

---

## 5. 封存件

| 件 | 状态 | 一句话 |
|---|---|---|
| B1 HTTP 传输 | **2026-08-08 以内部形态唤醒**(N6) | 常驻 streamable HTTP 落地于 R2/R3;对外形态仍随 B2 |
| B2 OAuth 边界 | 封存 | Clerk AS + RFC 9728 + RFC 8707 + scope→face。唤醒条件不变:真实第三方消费者/产品目标。唤醒时按 spec 2026-07-28 重校(DCR→CIMD 等);公网部署是其验收前置 |
| B5 staging 验收 | 封存 | 真宿主 E2E 随 B2;内部负例矩阵已被 R1/R5 吸收 |

---

## 6. 工作量粗估

```
R1(内部身份件)          ~0.5 天
R2(构造器拆分+常驻 app) ~1 天
R3(infra)               ~0.5 天
R4(消费者迁移)          ~1 天
R5(守卫与回归)          ~1 天
R6(文档)                ~0.5 天
                          合计 ~4.5 天
```

R1–R3 纯新增,任一阶段停下系统不劣于现状;R4 起切流量,R4 完成即可栈上验收。

---

## 7. 实测记录(2026-08-03 P1–P4;2026-08-08 P5)

| 阶段 | commit | 关键实测 |
|---|---|---|
| P1.1 | `754c550` | `faces.available()` 删除;`resolve()` 缺项即 raise。旧的 `KNOWN_TRIMMED`(stdio 静默掉 4 个 delegation/gate 工具)随之消失 |
| P1.2a | `fda6aa9` | 校验进关口、先于预算。**全量 439/108 保持绿**——说明当时的 schema 太松,拒不动任何东西 |
| P1.2b | `0bd13d4` | S2 审计(22 工具 / 6 agent)+ 对抗 critic 抓出:**校验合并后已有 7 条 live regression**(`respond{citations:null}` 最致命,它是会话唯一出口);`form_type` enum 少了 `10-K/A`;`redact_args` 对非 dict 抛 AttributeError,违反 invoke 的"永不抛出"契约。守卫改为**从函数标注推导**(annotation 而非 default) |
| P1.2c | `ffc662a` | 22 个 schema 全部 `additionalProperties: false`;`_field()` 先修好 `additionalProperties`/嵌套 required 的字段归属(否则未知参数全落 `field:""` 且排在最前);args 存储上界移进 trace_service(schema 关键字堵不住拒绝路径) |
| P1.2d | `840aa14` | `last_n`/`k` 补下界。原先 `last_n=-20` 在 12 点序列上返回**空序列 + 可引用的 calc_id**;float-integer 残留(Draft 2020-12 认 12.0 为整数)由工具层 coercion 收口 |
| P1.3 | `8c36ccc` | stdio 门去 owner-engine、`MCP_STDIO_USER_ID` 必填、face 扩至全量 20;import-graph 守卫经变异测试 |
| P2 | `d6ad3e1` | `build_mcp_server()` 参数化;`validate_input=False`(SDK 默认自校验会抢在关口前、且不留 trace);确定性排序;删 `build_http_app()` |
| P3 | `4170c16` | meta-agent 每 turn 建 in-memory 对。**parity live test**:同调用两条路径的 payload 与 `agent_steps` 逐字段一致(`calc_` 因台账 append-only 每次新铸而归一,其余前缀必须精确相等)。顺带关闭一个**先于本计划存在的洞**:dispatch 原先打在完整 registry 上,face 只是"告诉模型有什么" |
| P4 | `d7dbd7a` | research subagent 每 run 建对。live:24/40 预算、12 种工具、65 条证据、brief 21 条已验证引用 |
| P5 | `6f0da2b` | 运行栈重建撞出 **mcp 2.0.0 删除 `create_connected_server_and_client_session`**(镜像按 `mcp>=1.2` 现场解析拉到 2.0;venv=1.28.1)→ 钉 `mcp>=1.28,<2`,重建后容器落 1.29.0。api/worker 两容器内 MCP 通路实测:20 工具全量 face、`get_fact_series` 真实 ledgered calc(铸 calc_id、引 6 条 fact refs)、未知参数结构化拒绝、trace 三行落盘,两容器逐项一致。LLM 层未在栈上验:OpenAI 额度耗尽(对已建、tools 已列,失败点在 provider 调用之上无 MCP 成分)。**遗留:mcp 2.0 迁移**——helper 被删非搬家,升级是带验收的迁移,非依赖 bump。后补:额度恢复后栈上全链路验通(chat turn 数字验证门拒→重试→过;research run 1m33s、30 工具调用、brief 六块 21 引用) |

**新增守卫(全部经变异测试或真语料确认)**:面严格解析 · schema 诚实性(null/required/additionalProperties/窗口下界,全部由函数签名推导)· 每个注册 schema 是合法 Draft 2020-12 schema · 传输 parity · agents 层不得绕过 transport 直调 `invoke` · 完整单向 import 规则(原先只盖 providers)。

**范围外撞出、未做**:`search_filing_passages.query` 无 `minLength`(空串会走到 embedding);`citations` 元素无前缀 `pattern`(门已按 trail+DB 校验,加 pattern 等于把门的知识复制到第二处);`issuer_briefs` 成本三列为化石列、agent 路径 LLM 开销全系统无账(2026-08-08 发现,修法 A/B 待拍板,与本计划正交)。均记录于此,不静默。

---

## 8. R 阶段落地记录(commit 与实测待填)

> 「落地」列是 2026-08-19 对源码的实读结果,不是计划复述;commit 与实测两列由 boss 填。

| 阶段 | commit | 落地(实读) | 实测记录 |
|---|---|---|---|
| R1 | | `auth/internal_token.py`:`mint()`/`verify(token, *, expected_face)`,HS256,claims `sub`/`sid`/`mid`/`face`/`deny`/`iat`/`exp`,ttl 1800s,验签 60s leeway,`require_secret()` 缺密钥即 raise;`apps/mcp/middleware.py`:纯 ASGI `bearer_identity(app, *, expected_face)`(不是 `BaseHTTPMiddleware`,否则 contextvar 落在别的 task 里);`tools/mcp_request.py`:逐请求 claims contextvar,未绑即 `NoMcpRequestBound`;`faces.FACE_NAME_META/RESEARCH`;settings 增 `mcp_url` / `mcp_internal_secret` / `mcp_token_ttl_seconds` | |
| R2 | | `build_mcp_server(registry, face, *, db_factory, face_name)`——`session_id`/`user_id`/`message_id` 三参删除,handler 改读 claims;`_served(deny)` 一处算 scoped registry,list_tools 与 call_tool 同读它;server 名为 `exposure-workbench-<face>`。新增 `apps/mcp/http.py`:`MOUNTS` 表、每挂载点一个 `StreamableHTTPSessionManager(stateless=True)`、`AsyncExitStack` lifespan、免凭证 `GET /healthz`、`Route`(不是 `Mount`,避免 `/mcp/meta` 307 到带斜杠)。stdio 门改绑 `InternalClaims`,不铸 token | |
| R3 | | `infra/Dockerfile.mcp`(CMD = `uvicorn apps.mcp.http:app`)+ compose service `exposure-mcp`:**无 `ports`**、env 按 N10、`./data` 与 `./configs` 卷、healthcheck 用 `python -c urlopen /healthz`、`depends_on: postgres healthy`;api 与 worker 加 `MCP_URL`/`MCP_INTERNAL_SECRET` 并 `depends_on: exposure-mcp healthy`;`.env.example` 增 MCP 段 | |
| R4 | | `tool_session(face_name, *, session_id, user_id, message_id=None, deny=())`:铸 token → `httpx.AsyncClient(Authorization: Bearer)` → `streamable_http_client(f"{mcp_url}/mcp/{face_name}")` → `ClientSession`;`create_connected_server_and_client_session` 与 `build_mcp_server` 在 agents 层不再出现。`handle_message` 去掉 `registry` 参数;`run_research_session(session_id, ticker, deny=(), max_turns=30)` 去掉 `db_factory`/`registry`/`face`;`issuer_research_workflow` 的 skip flag 由裁 face 改为 `deny=("search_external_research",)`,本地裁剪那三行删除 | |
| R5 | | 新守卫:internal token 负例矩阵(37)· 中间件 401/绑定(9)· **双租户并发穿真 `StreamableHTTPSessionManager(stateless=True)`,在工具 handler 里用 `asyncio.Barrier(2)` 卡住两个请求再各读 claims**(5)· face 物理性与 deny 只削不加(11)· ttl ≥ task lease · agents 层不得 import in-memory helper · compose 端口与 MCP 环境变量。`tests/mcp_mount.py` 用 `httpx.ASGITransport` 组装与容器同构的挂载点(只少一个 socket)。live parity 4 处调用点迁到常驻签名,session 改为有主(常驻后无主 session 写不进 RLS)| **653 offline / 118 live 全绿**(基线 577/116)。**每 call 传输开销实测 8.87 ms 中位**(direct invoke 4.94 → 经面 13.81,api 容器内 12 次取中位)——**是 §3 预估 1–3ms 的三倍**,原因是 stateless 每请求重建传输与 task group。按 30 call/run 计约 +0.27s,而实测 run 全长 25.8s,故不优化,只钉数;若将来出现每 turn 上百 call 的形态,这里是第一处该看的 |
| R6 | | `TARGET_ARCHITECTURE.md` §2 总图重画 + §3 目录 + §8 双轨规则 + §9.2;`MODULE_NOTES.md` M10;`README.md` MCP 段与 stdio 行;本文件状态行与本表 | |

**执行中记录下来的事(不静默)**:

1. **R4 用的传输函数是 `streamable_http_client`,不是 §3 R4 行写的 `streamablehttp_client`**。后者在装机版本(mcp 1.28.1)已 deprecated,每次调用发一条 DeprecationWarning,并在 mcp 2.0 里被删除;前者在 `>=1.28,<2` 整段区间与 2.0 里都存在。代价是 header 挂在本模块自建的 `httpx.AsyncClient` 上(因此有了 `_TIMEOUT` 常量)。结果是**生产路径已经在 2.0 的 API 上**,§7 P5 那条遗留只剩测试 fixture 挡路。
2. **§4 的错误契约缓解需要更正**。`tool_session.call` 的结构化返回覆盖"服务端答复的一切"(未知工具、拒绝的参数、炸掉的 handler),**不覆盖传输本身**:401 或连不上会掐掉流的 task group,`call()` 里那个 await 收到的是 `CancelledError`,真因以 `ExceptionGroup` 出现在 `async with tool_session(...)` 处(R4 实测,非推断)。所以 mcp 容器挂掉时 loop 是**炸**而不是降级,且这个异常当前会经 `apps/api/routes/agent.py` 变成浏览器看到的 500。要不要一个可读的失败面、放在哪(两个 loop 的 `async with` 处收一个窄口,而不是把 `call()` 的 except 放宽),是待拍板件。
3. **`build_meta_registry()` 生产路径已无调用者**(它在 `agents/meta_agent.py`,现在只剩测试引用),meta face 的 registry 因此在两处拼写——`apps/mcp/http.py` 内联的是 `register_meta_tools(build_read_registry())`。不能让 http.py 直接 import 它:那会把 `llm/client.py` 拖进工具容器,与 N10 冲突。搬到 tools 层还是连测试一起删,待拍板。
4. ~~`pyproject.toml` 的 pin 注释仍称 in-memory helper 是"两个 agent loop 的传输"~~ → **已改**:cap 现在守的是测试套件而不是产品(生产路径已在 2.0 仍有的 API 上),升级要连 offline mount 测试一起重写。

4b. **`mint` 与 `verify` 对全空白 `mid` 判断不一致**(mint 拒、verify 放行,该字符串会一路到 `record_step` 成为解析不到的 message_id)→ **已改**:verify 也 `.strip()`。本仓库任何调用方都触不到它(token 只由 mint 产出),这恰恰是它能长期不被发现的原因。

4c. **测试侧一度有两套机制指向同一件事**:一个 `tests/conftest.py` 写 `os.environ["MCP_URL"]`,与 parity 模块里的 autouse fixture 并存(并行执行期两边同时在改这个文件的产物)。保留 fixture、删掉 conftest——fixture 直接设 settings 对象,不依赖"谁先 import 缓存了单例"这种顺序运气。
5. ~~**"空 `MCP_INTERNAL_SECRET` 三个容器都起不来"只对 mcp 容器成立**~~ → **已收口**:api 的 lifespan 与 worker 的 `run_worker()` 各加一次 `require_secret()`,文档措辞因此成真。放启动期而非第一次 `mint()`,是因为后者发生在配额已扣已提交之后,用户拿到的是 500 而部署看起来健康;放 lifespan 而非 import 期,是因为 offline 套件会 import api app,不该为工具面的密钥而收集失败。
6. **§3/§6 的"R1–R3 纯新增不切流量"对 R2 不字面成立**:R2 改了构造器签名,`tool_session` 在 R2 落地到 R4 落地之间是坏的。两阶段同批落所以没有真实窗口,但下次拆阶段时,改签名的那一阶段和迁调用方的那一阶段必须绑在一起。
