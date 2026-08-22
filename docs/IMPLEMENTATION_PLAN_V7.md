# Implementation Plan V7 — 上线批:公网可注册 + 前 10 分钟

> **状态(2026-08-22)**:**待办记录,未拍板**。范围与规模已和 boss 对齐,拍板点见 §0;拍板后本文件升级为执行方案(补验收与阶段依赖)。
> **编号勘误**:本文件曾以 V5 之名提交(`01c5cdd`)并**误覆盖了量化正确性批的 V5 文档**(内容已自 `ac167d6` 全量恢复,见该文件)。V5=量化正确性批、V6=窗口+报告门批(另一 session,2026-08-21),本批顺延为 V7。
> **性质**:两个可并行的批——**D(部署)**把栈放上公网,**U(产品)**把一个陌生人注册后的前 10 分钟做通。代码内核(agent 面、RLS、配额、成本账、失败语义)已完工并在栈上实测,本批不动架构。
> **一句话**:差的全在部署层和"第一次使用"的交互层,不在功能内核。

---

## 0. 拍板点(全部待 boss)

| # | 决策 | 候选与默认倾向 |
|---|---|---|
| **DP1** | Clerk 用 dev 实例先上,还是直接 production 实例 | 倾向 **dev 先上**(零额外工作;水印/用户数上限对朋友级 demo 无碍;升级=换 issuer/keys+重建 web,无返工)。production 实例需 boss 在 dashboard 建实例 + 配 CNAME(~30 分钟) |
| **DP2** | Caddy 块并入 `/etc/caddy/Caddyfile` 由谁执行 | 机器上还服务着 micosai.com 与 noclosedform.com,错一处全站塌。流程含备份 + `caddy validate` 关卡;boss 授权后可由 agent 执行,或 boss 手动 |
| **DP3** | 备份要不要 | 用户数据只有 portfolios/positions(其余可重 ingest)。最小方案 = 每日 `pg_dump` + 保留 7 份(几 MB);不做也可,demo 级 |
| **DP4** | U 批范围照 §2 开工,还是砍/加 | 建议 U 批与 D 批**并行**,在真域名上验收 |

---

## 1. D 批 — 部署(~半天,多数是 boss 手动步骤)

### MUST(不做就没有公网产品)

- **D1(boss)** Cloudflare A 记录:`exposure` → `100.49.167.5`,**grey cloud**(DNS 必须先于 Caddy reload,否则 Caddy 起证书失败在后台重试)。
- **D2** Caddy:`infra/Caddyfile.example` 块并入 `/etc/caddy/Caddyfile`(先备份 → `caddy validate` → reload)。执行者见 DP2。
- **D3** 生产 .env 三值 + **重建 web 镜像**(NEXT_PUBLIC_* 是 build 期内联,改环境变量对运行中的容器无效):`NEXT_PUBLIC_API_URL=`(空=同源)、`CORS_ORIGINS=`(空)、`CLERK_AUTHORIZED_PARTIES=https://exposure.noclosedform.com`。
- **D4(boss)** Clerk dashboard 把 `https://exposure.noclosedform.com` 加进允许 origins。
- **D5** 公网 smoke:真浏览器注册新账号 → chat 一轮(顺带目视 llm_call 行)→ Investigate → 配额头显示。**这是"上线完成"的定义**;顺带盖掉悬着的两项 UI 目视(llm_call 行样式、503 呈现)。

### SHOULD(开放给陌生人之前,当天可补)

- **D6** ingest singleflight:两用户并发 Investigate 同一 ticker 会重复 ingest。方案早已设计(`ingest_lock_service` advisory lock + `run_readiness` 包锁 + `await_ingest` 时间线步),是 harness 收口批里唯一的 doc-code 双重欠账。~半天。**朋友级流量可后置,广发链接前必须有**。
- **D7(boss)** OpenAI dashboard 设月度硬上限(provider 侧第二道护栏,5 分钟)。
- **D8** 磁盘:79% 满、剩 8.1G(镜像构建缓存吃的),`docker builder prune` 一次;否则再建几次镜像就满。
- **D9** 备份(若 DP3 要):每日 `pg_dump` cron + 保留 7 份。
- **D10** worker 扩到 2–3 副本 + 连接预算。1 副本串行处理,冷 ticker research 几分钟,第三个同时 Investigate 的用户要排队;`claim_next_task` 的 `FOR UPDATE SKIP LOCKED` + 服务器时钟租约使多副本按构造安全。每进程池上限 30(`pool_size=10, max_overflow=20`),api+mcp+3 worker = 150 > `max_connections=100`:扩副本同时 `max_connections=200` 或调小 worker 池。
- **D11** 一次 `ANALYZE`:大批量 seed 后统计信息陈旧(`pg_stat_user_tables` 报 `filing_chunks` 0 行,实际 3,078)。

---

## 2. U 批 — 产品交互:陌生人的前 10 分钟(~3 天)

按用户旅程排优先级;全部有具体坐标,不动后端架构。

- **U1(~1 天)Research 等待叙事 + 失败人话上屏**。issuer 页目前只有一个 spinner(`issuer/[ticker]/page.tsx:81`,3s 轮询):热 ticker 25s 尚可,**冷 ticker 要先 EDGAR ingest + embedding,几分钟只有 spinner = 用户必然认为挂了**。叙事数据全都有(`workflow_events` 外层时间线 + `agent_steps` 内层),§9 的"Run 时间线"就是为这一刻设计的,渲染出来。失败侧:`error_message` 已是人话(V4-S1)、API 已返回、web 类型已有(`lib/issuer.ts:29`),**UI 只显示红字 "research failed"(page.tsx:84)——那句人话从没到过用户眼前**,S1 的价值目前只有 psql 看得到。
- **U2(~0.5–1 天)First-run 空态 + chat 示例提问**。新用户登录后是 demo 组合 + "New portfolio" 按钮,无任何引导;"Clone demo" 藏在弹窗里(`PortfolioModal.tsx:202`)。空租户主面板给一句话 + 两动作(Clone demo / 上传 CSV)+ 一条示例提问;ChatPanel 空态给 3 条可点示例(正确的第一问不显然)。
- **U3(~0.5 天)`port_001` 硬编码 + issuer 页错误人话**。`startResearch` 把 `portfolio_id` 硬编码为 demo 组合(`lib/issuer.ts:48`)——签入用户发起的 research 归属错误组合,brief 的 portfolio_implications 按错误语境写。issuer 页错误处理只特判 409(`page.tsx:55`),429 等给用户看原始 JSON;与 ChatPanel 的人话分支抽成共享映射。
- **U4(~0.5 天)`evaluated` 露出**。`payload_summary.evaluated` 前端零露出——**没运行的 check 和通过的 check 在报告里长得一样**;对以"每个失败可解释"为卖点的产品,这是唯一一处 UI 在沉默夸大。未运行标灰。harness observability 线顺带销账。

- **U5(~0.5 天)报告渲染补全**。V6 §4 记录:UI 只渲染 exposure 报告 7 个字段中的 3 个,`markdown_report` 无渲染器——V6-G 刚给它上了 79 数字全过的门,而用户看不到这段被门保护的文字。把门的成果端到用户眼前,与 U4(`evaluated` 露出)同属"诚实性上屏"。

### 记录、不进首批

移动端适配(三栏桌面布局)、chat session 历史列表(现只恢复最近一个)、返回用户首屏竞态(8/3 标记观察)、用户侧成本页(数据与视图已有,做不做是产品选择)。

---

## 3. 数据库 / 用户隔离 / 并行能力审计(2026-08-22,全部实测)

**结论:三块均无上线阻塞项。** 隔离是结构性的(20 张租户表 RLS、`app_rls` 无 bypass、GUC 逐事务注入、MCP 逐请求绑定经跨进程并发实测、成本视图 `security_invoker`);并发模型按构造正确(turn lease / 配额 / 任务领取全是 DB 事务);库 99 MB、默认配置、当前 6 连接。

**故意不隔离、有理由的**:公司级证据表(公共事实);`tasks` 与 `usage_daily`(队列与全局池天然跨租户,worker 以 `app_rls` 不设租户领任务,有 RLS 就看不到 pending 行)——靠路由层 WHERE,代码注释写明 `semantic, not security`。

**上线后三条卫生(不阻塞)**:
1. `agent_sessions` 277/559 行 NULL owner(测试与 V2 前遗留;策略下对所有租户不可见,无泄漏,但成本视图出 NULL 桶)→ 清理 + `owner_id NOT NULL`,先让仍造无主会话的 live 测试改有主。
2. `tasks` / `usage_daily` 的隔离靠纪律:补一条守卫测试——所有触碰这两表的路由必须带 owner 过滤(与 import-graph 守卫同型)。
3. `filing_chunks.embedding` 无向量索引(仅三个 btree),精确扫描;3k 行毫秒级,**过百家公司**再加 HNSW。

**与 D6 的关系**:`research_runs` 按 owner 隔离 → 两用户同时 Investigate 同一 ticker 互不可见 → 两个 run 并行对共享证据表 ingest,而 `filing_chunks` 无 UNIQUE(挂起区"三份 schema 同落")→ 重复 chunk。这是 D6 singleflight 广发前必做的实证。

---

## 4. 与既有 backlog 的关系

本文件只覆盖"到可注册 production"的路。以下照旧躺在 BOARD/topic 页,不因上线改变优先级:S3 重跑(mcp 2.0,租约扩三文件)、research 侧 `llm_session` 栈上验证(1 次配额可顺带并入 D5 smoke)、harness 线(loop / evidence 单一路径)、A1 存在性 vs 正确性、已挂起四件。
