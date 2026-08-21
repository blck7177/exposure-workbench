# Implementation Plan V4 — 收尾批:失败可解释 · 开销有账 · 单一 major · 单一拼写

> **状态(2026-08-20)**:**S1 / S2 / S4 完成**,offline 672 全绿(批前 653);**S3 中止并回滚**——mcp 2.0 删除 lowlevel 装饰器注册 API,需重写 `build_mcp_server`,超出该阶段文件租约,按退路留在 1.28.1。本批**只做修改**:镜像重建、`v4_cost.sql` 重放、栈上 live 验收待 boss 拍板。逐阶段实测见 §6,执行期问题见 §7。
> **版本**:v4(2026-08-20)。与 MCP_PLAN v3 并列而非取代:v3 讲的是 agent 面怎么到达工具,v4 收的是它到达之后剩下的四个洞。
> **性质**:执行方案。四件彼此可独立合并、独立验收的收尾件。
> **一句话**:让系统里最后一处不可解释的失败开口说话;给唯一花钱的动作记账;把测试从旧 major 上解下来;让"meta 面由什么构成"只有一处答案。

---

## 0. 已定决策(2026-08-20,boss 拍板)

| # | 决策 | 内容 |
|---|---|---|
| **D1** | S2 走 **A(结构执法)** | 建 `agents/llm_session.py` 薄包装 + import 法律,而非"两个 loop 各记一行 + 测试盯"。消灭错误类别而非实例:第三个 loop 出生即有账。与本仓库全部先例同向(face 物理裁剪、stdio 门 import 守卫、agents 不得直调 `invoke`) |
| **D2** | face 不可达导致的 turn/run 失败,**配额不退** | V2-H 现行规则(先扣已提交、不退)保持。退款要引入"死在第几次 completion 之后"的分界——face 中途死时钱**已经**花了一部分,分界必然引分支。503 的语义补偿是明确告诉用户这不是他的问题 |
| **D3** | `direct_llm_agent` 对 S2 的 import 法律**显式豁免**,不判死 | 它是 exposure 报告的生产功能,且**自有账本**(写 `daily_reports` 的三列)。豁免必带注释理由,合 P1.2「无静默豁免」先例 |

---

## 1. 现状基线(2026-08-20,全部实读/实测)

| 事实 | 坐标 |
|---|---|
| 传输失败以 `ExceptionGroup` 从 `async with tool_session(...)` 炸出(R4 刻意;`call()` 的 await 被 cancel) | `agents/tool_session.py` docstring + 栈上实测 |
| API 侧无异常处理器 → 用户看 FastAPI 裸 500;turn lease 由 route 的 `finally` 释放,配额已扣不退 | `apps/api/routes/agent.py` |
| worker 侧 `except Exception` 把 `str(exc)` 写进 run:内容是 `unhandled errors in a TaskGroup (1 sub-exception)` | `apps/worker/worker.py:131-137` |
| 两个 loop 把 `usage` 原地丢弃;`agent_steps.prompt_tokens/completion_tokens` 列**已存在**,`record_step` **已接**这两参,零调用方传过 | `meta_agent.py:125` · `research_session.py:83` · `models.py:662-663` · `trace_service.py:102-103` |
| `chat_with_tools` 的 usage dict 只有两个 token 数,**无模型版本**;`response.model` 现成未取 | `llm/client.py:106-109` |
| `issuer_briefs` 三条成本列历史全空(4 行 brief,`count(llm_model)=0`),api/services 零读者 | 2026-08-08 DB 实测 |
| `build_meta_registry()` 生产路径零调用者;`http.py` 内联同一表达式;`build_research_registry` 在 workflow 层 | `agents/meta_agent.py:79-80` · `apps/mcp/http.py:53,74-75` |
| in-memory helper 仅剩 `test_mcp_stdio_live.py` 3 处;pin `mcp>=1.28,<2` 只守测试 | 本日 grep · `pyproject.toml` |
| 迁移按 `vN_*.sql` 手工重放,要求幂等 | `infra/migrations/` · `test_deploy_config.py` |
| UI 逐 step 渲染,按 `step_type` 分 icon;新类型会以通用样式出现 | `apps/web/app/components/ChatPanel.tsx:22-27` |

---

## 2. 执行期发现,以及它改变了什么(2026-08-20,动手前实测)

计划原文把 S3 估成"换一个测试 fixture,生产路径已在 2.0 仍有的 API 上"。装一个 2.0 到临时 venv 实读后,这句话只对了一半——**函数名还在,契约变了**:

| 发现 | 后果 |
|---|---|
| mcp 2.0 **硬依赖 `httpx2`**(`mcp/client/streamable_http.py` 直接 `import httpx2`,`http_client` 参数标注 `httpx2.AsyncClient`);2.0 环境里根本没有 httpx | `tool_session.py` 自建的 `httpx.AsyncClient` 与 `httpx.Timeout` 必须换库。httpx2 提为**显式依赖**(同 tiktoken/jsonschema 的「declared, not inherited」理由:agent 传输自建 client,用哪个 HTTP 库不能交给别的包的解析器决定) |
| `streamable_http_client` 在 2.0 **yield 两元组** `(read, write)`,1.28 是三元组(第三个是 `get_session_id`,本仓库从未使用) | 生产路径的解包要改。protocol session 已被 spec 2026-07-28 移除,第三个值不再存在——不留占位 |
| `create_client_server_memory_streams()` 2.0 仍在;`StreamableHTTPSessionManager` 除新增 `max_request_body_size` 外无变 | in-memory 对可在测试内本地重写;常驻挂载点零改动 |

**因此调整执行顺序:S3 先于 S1。** S1 要按名字捕获传输异常,而"名字"取决于最终用哪个 HTTP 库;反过来做,S3 会让 S1 的守卫**静默失配**——它要修的那种故障原样复活,且这次连测试都不红。计划 §3 原写"四件彼此独立"在 S1↔S3 这对上是错的,此处更正。

新顺序:**(S3 ‖ S4) → (S1 ‖ S2)**。

---

## 3. 阶段计划

### S1 — 传输失败语义:face 不可达是一种**有名字的**失败(~0.5 天)

**问题**:`ToolSession.call` 的「永不抛出」契约只覆盖**服务端答复的失败**(未知工具、参数被拒、handler 炸掉——结构化回给模型,turn 继续)。传输本身失败会掐掉 stream 的 task group,以 `ExceptionGroup` 从 `async with` 处炸出。这个分野是对的(否则 loop 会烧完 30 次预算收到 30 个 "connection refused"),错的是**没人接**:chat 用户扣了配额换一个裸 500;research 用户烧掉每日 3 次里的 1 次,run 的失败原因写着 task group 内部话。在一个以「每个失败可解释」为卖点的系统里,这是唯一一处失败不可解释的地方,而且**每次重启 mcp 容器都会撞**。

**改**:
1. `tool_session.py` 增域异常 `ToolFaceUnavailable`,带 `.reason`(`connect_error` / `http_401:<reason>` / `timeout`),`__str__` 是人话(含 face 与 URL,**不含 token**)。住在 transport 模块——这是唯一知道「什么算传输失败」的地方。
2. 在 `tool_session` 上下文管理器内(**不是** `call()`,那个契约一字不动)捕 `BaseExceptionGroup`,内省叶子,凡传输失败 → `raise ToolFaceUnavailable(...) from eg`;其余原样再抛(**不吞不明之物**)。开局死与中途死同路,一处收口。
3. `routes/agent.py` `post_message` 加**窄** except → `HTTPException(503, {"error": "tool_face_unavailable", …})`,与既有 413 并列,既有 `finally: release_turn` 天然覆盖。**不落 assistant 消息**——把基础设施故障穿成 agent 回复,等于让一段没过 respond 门的文本到达用户。transcript 里留着未答的用户消息,是事实。
4. worker **零改动**:`except Exception` 已在,`str(ToolFaceUnavailable)` 即人话。

**做完达到**:503 让前端知道该不该让用户重试;run 的 `error_message` 变成人话,Run 时间线可读。
**范围外记录**:`issuer_research` 是非重放型 task,face 恢复后不自动重跑——改重放语义是另一个决定,只记不做。

### S2 — 成本入账(A 型):completion 在它发生的地方留下一行(~1 天)

**问题**:一次 completion 产 text / tool_calls / usage 三样。前两样被架构**强迫**穿门才能生效(text 过 respond 或 submit_brief 门,tool_calls 过 MCP 与 `invoke()` 并自动落账),`usage` 不需要「生效」,没有门等它,于是被原地丢弃。全系统唯一真正花钱的动作,是唯一没有记录的动作。§9 第 5 条「token 行级落库,session/run 汇总 = SQL 视图」目前是空话:回答不了「这个 run 花了多少钱」,账单涨了无法归因,配额按「动作」计而一个 turn 的真实 token 方差巨大——**配额挡不住成本尾部**。

**改**:
1. **`agents/llm_session.py`(新)**,与 `tool_session` 同构:`llm_session(db_factory, session_id, message_id=None)` → `.chat(messages, tools=None, **kw)` → `(content, tool_calls)`。内部调 `chat_with_tools`,经 `record_step` 落一行 `step_type='llm_call'`(tokens 进**已存在**的两列),**usage 不再返回给 loop**——拿不到,才谈得上「不会丢」。这就是 A 的全部内容。
2. 失败语义(与 invoke 的 trace 同型):record 写库失败 → log error + **仍返回 completion**。钱已花、答案在手,为守一格账本扔掉真实产出是本末倒置。
3. `llm/client.py` 一行:usage dict 增 `"model": response.model`(provider 实际版本串,非配置别名——§9 要的是版本)。llm 层仍零 db。
4. 两个 loop 换动词;`prompt_peak` 照旧(tiktoken 估算管上限,provider 实数管账,两回事)。
5. **import 法律**:`agents/` 下除 `llm_session.py` 与 `direct_llm_agent.py`(D3 豁免,注释写明自有账本)外不得 import `exposure_workbench.llm`。同既有三条 import-graph 守卫机械。
6. **迁移 `infra/migrations/v4_cost.sql`**(幂等):删 `issuer_briefs` 三条化石列(models.py 同步);建三视图 `v_session_cost` / `v_run_cost`(经 `research_runs.agent_session_id` join)/ `v_user_daily_cost`(经 `agent_sessions.owner_id` + UTC 日)。**视图不建表**:账全在行里,看板要薄。
7. UI:`ChatPanel.tsx` 对 `llm_call` 渲染**弱化行**(模型名 + tokens,muted)——审计面该看得见,但不与工具调用抢焦点。既不是动作也不是自述,是第三种颜色。
8. `record_step` 的 step_type 注释补 `'llm_call'`。

**做完达到**:成本面板有数、异常账单可归因到租户/功能/模型版本、未来上 token 配额或告警有地基、§9 第 5 条从声明变实现。
**注意**:llm_call 行会改变「数 steps」的含义,凡数行的既有断言按**本意**修(通常是「数工具调用」,加 step_type 过滤),不许静默放宽。

### S3 — mcp 2.0 迁移:pin 从「防爆」变回版本管理(~0.5 天 → 因 §2 发现上修)

**问题**:R4 之后 pin `mcp>=1.28,<2` 只挡一个东西——测试里 3 处用被 2.0 删掉的 in-memory helper。留在旧 major 上意味着拿不到 2.x 的修复与 spec 2026-07-28 对齐(常驻 + stateless 恰是那次改版钦定的方向),而 8/8 那次「镜像现场解析拉到新 major、容器起不来」提醒过:依赖表面积不动,风险一直躺着。

**改**(含 §2 上修的部分):
1. 装 `mcp>=2,<3`;pyproject 改 pin 并把 `httpx2` 提为显式依赖。
2. `tool_session.py`:httpx → httpx2(AsyncClient 与 Timeout);三元组解包改两元组,**不留占位**;其余(never-raises 契约、mint 一次、URL rstrip、不跟随重定向)一字不动。
3. `tests/mcp_mount.py`:ASGITransport 换 httpx2;新增 `in_memory_pair(server)` fixture = `create_client_server_memory_streams` + `server.run` task + `ClientSession`,即被删 helper 的本地重写——**测试 fixture 本来就是它该在的家**。
4. `test_mcp_stdio_live.py` 3 处改用它,断言一条不动(stdio 门的行为不是变的那部分)。
5. `providers/security_master_provider.py` 的 httpx 是非 MCP 用途,**留在 httpx**。

**做完达到**:产品与测试统一在当前 major;pin 从防爆回到普通版本管理;MCP_PLAN §7 P5 遗留销账。
**退路**:两个 commit 分开(fixture 重写先行、pin 升级殿后),2.0 若有实质行为变更,revert 一个 commit 即回 1.28,差异记入本文件再议。

### S4 — registry 归位:一个问题一处答案(~0.2 天)

**问题**:R4 之后 `build_meta_registry()` 只剩测试在用,而 `http.py` 内联拼了同一表达式;不能让 http.py import 前者——那会把 `llm/client.py` 拖进工具容器,违反 N10。`build_research_registry` 是镜像问题:定义在 workflow 层,把面的定义放进了编排模块。

**影响要说公道**:**今天为零,且漂移是响的不是哑的**——P1.1 的 `faces.resolve` 在容器启动时严格解析,两处真漂移会让 mcp 容器**拒绝启动**,不是静默服务小面。真实代价是发现时点在**部署时**而非 import 期,加上两处拼写本身的维护税。

**改**:新建 `tools/registries.py` 放两个 builder(该模块**不得** import llm 或 workflow,注释写明 N10);删两处原定义(**不留转发 shim**,那是第二处拼写换马甲);迁移全部调用方与测试 import;更新 `test_v2_audit` 的 face 审计坐标。

**做完达到**:漂移这个类别在 import 期就不可能发生,meta/research 恢复对称。

---

## 4. 排程

```
S3 ‖ S4      两组文件无交集;S3 定下 HTTP 库,S1 才有名字可捕
   ↓
S1 ‖ S2      S1 在 S3 落定后的 tool_session 上做;S2 在 S4 搬完后的 meta_agent 上做
```

每阶段:offline 绿 → commit。栈上 live 验收与镜像重建由 boss 拍板后统一做(本批只做修改)。

---

## 5. 风险(如实列)

- **S1 内省 ExceptionGroup 叶子类型**是对传输库异常族的依赖。用显式列举而非猜名字;S3 换库后此处必须重看——这正是把 S3 排在前面的原因。
- **S2 的 llm_call 行改变 steps 流水**,既有断言按本意修,不静默放宽。
- **S3 是 major + HTTP 库双换**,退路见阶段内(两 commit 分离)。
- **S4 零风险**,纯搬家,P1.1 启动守卫兜底。
- **S2 迁移需一次手工 `psql` 重放**(仓库惯例),不动 `docker compose down -v`。

---

## 6. 实测记录(2026-08-20)

> 本批只做**修改**;镜像重建、迁移重放、栈上 live 验收按 boss 指示留待其定。offline 全绿 **672**(批前 653)。

| 阶段 | 结果 | 落地(实读) |
|---|---|---|
| **S4** | 完成 | `tools/registries.py` 持两个 builder(不 import llm / workflow);`meta_agent` 与 `issuer_research_workflow` 的原定义**删除,无转发 shim**;`http.py`、stdio 门与全部测试改从此处 import。全仓 `register_meta_tools(build_read_registry())` 现仅存于 registries.py 自身 |
| **S1** | 完成 | `ToolFaceUnavailable(face_name, url, reason)` 落在 transport 模块;`_leaves()` 递归摊平 ExceptionGroup(group 是形状不是原因),`_transport_reason()` 分两支:`HTTPStatusError`(门答复了且拒绝)与 `TransportError`(没连上)——**httpx 里前者不是后者的子类**,合并会漏掉 401。`call()` 契约一字未动。API 加窄 except → 503 `tool_face_unavailable`,不落 assistant 消息、不退配额(D2) |
| **S2** | 完成 | `agents/llm_session.py`:`.chat()` 只返回 `(content, tool_calls)`——**拿不到 usage,才谈得上不会丢**;记录走独立 db session 独立提交(花销是 provider 一答复就成立的事实,挂在 loop 的事务上会让**最贵的那些行**恰好丢失)。`llm/client.py` 增 `model`(实际版本串)。import 法律经变异测试确认会红,`direct_llm_agent` 显式豁免(D3)。`v4_cost.sql`:删三条化石列 + 三视图,**全部 `security_invoker=true`**(V2-E0:否则视图以 owner 身份跑,app_rls 直接穿透 RLS)。UI 给 llm_call 第三种颜色 |
| **S3** | **中止并回滚**(计划 §3 退路) | mcp 2.0 **删除 lowlevel 装饰器注册 API**:`@server.list_tools()` / `@server.call_tool(validate_input=False)` 改成构造器回调 `Server(name, on_list_tools=…, on_call_tool=…)`,签名亦变(`(ServerRequestContext, params) -> types.ListToolsResult`)。这要求重写 `tools/mcp_server.py` 的 `build_mcp_server`——2.0 下 30 个 offline 失败**全部**停在 `mcp_server.py:104` 同一行。执行者按"不半迁移"停手,`pip freeze` 已与批前基线对齐,树留在 1.28.1 |

**S3 补测(离树探针,已证明 2.0 可行,故是有界重写而非架构再议)**:用 2.0 的新回调形状建 server,穿**真实** `bearer_identity` 门 + `StreamableHTTPSessionManager(stateless=True)` + `httpx2.ASGITransport` + 两元组 client + `ClientSession` 全通;`create_client_server_memory_streams` 亦通;**且门上绑的 contextvar 在 2.0 的调度下仍到达 list_tools 与 call_tool 两个 handler**(R5 存在的那条命题在 2.0 下依然成立)。

**2.0 破坏面清单(实测)**:①装饰器 API 删除(`mcp_server.py:104,125`);②Pydantic 字段改名 `Tool.inputSchema→input_schema`、`CallToolResult.isError→is_error`——**按 camelCase 别名构造仍可用,坏的是属性读**(读点:`tool_session.py:68`、`test_mcp_stdio_live.py:128,186,210,211`、`test_mcp_server_build.py:108,110`、`test_mcp_face_scope.py:55`);③`create_connected_server_and_client_session` 删除;④`streamable_http_client` 三元组→两元组;⑤硬依赖 httpx2(Timeout / ASGITransport 拼写与 httpx 一致,`_TIMEOUT` 可原样移植)。**不受影响**:`StreamableHTTPSessionManager`(仅增 `max_request_body_size`)、`stdio_server`、`Server.run`、`ClientSession`。另注:`validate_input` 在 2.0 lowlevel 源码中**不存在**,`mcp_server.py` 那段"单一强制点"的论证必须对 2.0 自己的校验行为重新验证,不能照搬。

**S3 重跑所需(待拍板)**:文件租约需扩至 `src/exposure_workbench/tools/mcp_server.py` + `tests/test_mcp_server_build.py` + `tests/test_mcp_face_scope.py`。加上这三个,迁移是机械的。

---

## 7. 本批收口的执行期问题(不静默)

1. **并发编辑撞车两次**,均已收口:S4 删 builder 时漏掉两个 test importer(S3 与 S1 各自补了自己那个);S2 的 `llm_session` 落地于 S1 读文件与跑测试之间,导致 S1 一次 5 红全是 `meta_agent` 不再持有 `llm_client`——**本批任何一次红都应先重跑再归因**。
2. **`http_401:<reason>` 无法按计划实现,实际为 `http_401`**(实测,非推断):SDK 在 `client.stream(...)` 内部 `raise_for_status()`,组被检视时 response 已关闭且 body 未读,`.text`/`.json()` 抛 `ResponseNotRead`,补 `aread()` 同样失败。拒绝理由并未丢失——`apps/mcp/middleware.py` 在**看得见 token 的那一侧**已带 face 与 path 记了日志。
3. **S2 报告"未做"的一条已由 boss 补完**:`StepOut` 未送 token 两列、web 的 `AgentStep` 类型在 `issuer.ts` 而非 `types.ts`。已补齐 API schema、web 类型与 ChatPanel 渲染(`N in / M out`,tabular-nums)。
4. **S4 报告的三处遗留 inline meta face 已由 boss 补完**:`apps/mcp/server.py:135`(生产重复)与 `test_mcp_server_build.py:41,104`。补时一度把 `build_read_registry` 的 import 一并删掉,而该文件第三处**故意**单用它证明"read registry 满足不了 meta face"——测试立即变红,已恢复。
5. **`issuer_research_workflow.py:23` 的 `Company` import 未被使用**(先于本批存在),记录不动。
