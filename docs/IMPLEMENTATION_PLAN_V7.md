# Implementation Plan V7 — 上线批:公网可注册 + 前 10 分钟

> **状态(2026-08-22)**:**B 线(U1–U5)、D0、D6、D9 全部完成并在栈上验收**;747 offline / 118 live 全绿。**A 线卡在 boss 两件**:D1(Cloudflare A 记录)与 D4(Clerk 加 origin);之后 D2/D3/D5 由我接。逐阶段实测见 §8,执行期发现见 §9。
> **编号勘误**:本批曾以 V5 之名提交(`01c5cdd`)并误覆盖了量化正确性批的 V5 文档,已自 `ac167d6` 全量恢复。V5=量化正确性批、V6=窗口+报告门批(另一 session,2026-08-21),本批顺延为 V7。
> **性质**:两条可并行的线——**A 线(部署)**把栈放上公网,**B 线(产品)**把一个陌生人注册后的前 10 分钟做通;外加**今日零风险三件**与**广发前三件**。代码内核(agent 面、RLS、配额、成本账、失败语义、数值正确性)已完工并在栈上实测,本批**不动架构**。
> **一句话**:差的全在部署层和"第一次使用"的交互层,不在功能内核;每一条都有文件坐标,没有一条需要新设计。

---

## 0. 已定决策(2026-08-22,boss 拍板:全按默认)

| # | 决策 | 内容 |
|---|---|---|
| **DP1** | Clerk **dev 实例先上** | 零额外工作;水印/用户数上限对朋友级 demo 无碍;日后升 production 实例 = 换 issuer/keys + 重建 web,无返工 |
| **DP2** | Caddy 块并入**由 agent 执行** | 流程含备份 + `caddy validate` 关卡再 reload;需 sudo——若权限分类器拦下,同样四条命令由 boss 手跑,步骤一字不差 |
| **DP3** | 备份**做** | 每日 `pg_dump` + 保留 7 份,几 MB;用户数据只有 portfolios/positions,其余可重 ingest |
| **DP4** | U 批 **U1–U5 全做** | 与 A 线并行,在真域名上验收 |

---

## 1. 现状基线(2026-08-22,全部实读/实测)

### 1.1 栈与代码

| 事实 | 坐标 |
|---|---|
| 分支 `origin/issuer-intelligence @ 8a6f923`;**717 offline + 118 live = 835 全绿**;四镜像含 V5-Q/V6 代码 | `git log` · `pytest` |
| 五个容器:web(3103)/api(8103)/mcp(8104 loopback)/worker ×1/postgres(5433);全部 loopback,无公网面 | `docker compose ps` |
| 根盘 **79%**,剩 8.1 GB,其中 **4.0 GB 是可回收 build cache**;Postgres 卷在同一块盘 | `df -h` · `docker system df` |
| 机器 RAM 3.8 GB,用 1.9 GB;Postgres `shared_buffers=128MB`、`work_mem=4MB`、`max_connections=100`,当前 6 连接 | `free -m` · `show …` |
| 每进程连接池 `pool_size=10, max_overflow=20` | `db/session.py:51-52` |
| worker:1 副本,`process_one` 串行;`claim_next_task` 用 `FOR UPDATE SKIP LOCKED` + 服务器时钟租约,多副本按构造安全;compose 已去 `container_name` 以支持 `--scale` | `worker.py:87` · `task_service.py:85-116` |
| 宿主 crontab 已有一条(sm-master),可直接追加 | `crontab -l` |
| Caddy 在服务 `noclosedform.com` / `www`;`infra/Caddyfile.example` 是可直接并入的块(改域名即可) | `/etc/caddy/Caddyfile` |

### 1.2 隔离与数据库(本日审计,结论:无阻塞项)

20 张租户表 RLS(`owner_id = current_setting('app.user_id')`,portfolios/issuer_briefs 加 `OR is_public`);`app_rls` 无 bypass;GUC 逐事务注入;MCP 逐请求绑定经跨进程并发实测;成本视图 `security_invoker`。**故意不隔离**:公司级证据表(公共事实)、`tasks` 与 `usage_daily`(队列/全局池天然跨租户,worker 不设租户领任务),靠路由层 WHERE,代码注释 `semantic, not security`。库 99 MB(facts 41 / chunks 30,3,078 chunks,10 家公司);`filing_chunks.embedding` 无向量索引(精确扫描,过百家再加 HNSW);统计信息陈旧(报 0 行,实 13k)。遗留:`agent_sessions` 277/559 NULL owner(对所有租户不可见,卫生债)。

### 1.3 U 批坐标

| 项 | 事实 | 坐标 |
|---|---|---|
| U1 | research run 只有 GET `/research-runs/{id}` 与 `/brief`,**无 events**;exposure run 已返回 `workflow_events: list[WorkflowEventOut]`(`id/step_name/status/message/duration_ms/created_at`),主页面已有 `StepIcon` + reduce 渲染 | `routes/research.py:130,155` · `routes/exposure_runs.py:24-33,132` · `page.tsx:43,213,283` |
| U1 | issuer 页只有 spinner `research {status}…`,3s 轮询;失败只显示红字 `research failed`,而 `error_message` API 已返回、web 类型已有 | `issuer/[ticker]/page.tsx:60-67,81-84` · `lib/issuer.ts:29` |
| U1 | readiness 的步骤消息本身就是叙事:`Resolving … via EDGAR` / `Ingesting 10-K/10-Q for …` / `Extracting XBRL facts …` | `readiness_workflow.py:49-73` |
| U2 | `PortfolioOut` **无** `is_public`/`is_own`,web 无法区分 demo 与自有;"Clone demo" 藏在弹窗;ChatPanel 空态已有一行提示文字(不可点) | `routes/portfolios.py:35-43` · `PortfolioModal.tsx:202` · `ChatPanel.tsx:242-244` |
| U3 | `startResearch` 硬编码 `portfolio_id: "port_001"`;API 侧 `portfolio_id: str \| None = None` 早已可选;workflow 与 research tools **不读** portfolio_id(只存) | `lib/issuer.ts:48` · `routes/research.py:63-67` |
| U3 | issuer 页错误只特判 409,其余原样显示;ChatPanel 已有完整人话分支(401/404/409/413/429/503) | `issuer/[ticker]/page.tsx:55` · `ChatPanel.tsx:150-190` |
| U4 | `limits.py` 返回 `(alerts, evaluated)`;workflow 写 `scenarios_evaluated/unevaluated`、`factors_held_flat` 进 `payload_summary`;**`WorkflowEventOut` 不带 `payload_summary`**,web 零引用 | `limits.py:310-311` · `exposure_workflow.py:279-283` |
| U5 | `daily_reports` 16 列;web 渲染 `executive_summary/key_movements/recommended_actions/llm_model`;**未渲染** `markdown_report`(V6-G 刚给它上门)、`factor_explanation`、`risk_alert_explanation`;web **无 markdown 依赖** | `page.tsx:314-337` · `package.json` |
| D6 | 设计已写死在 MODULE_NOTES:`ingest_lock_service` advisory lock 按 company 加在 `run_readiness` 内,两调用方(`company_readiness` handler、`issuer_research_workflow:64`)共用;等锁期间时间线记 `await_ingest`;run 级守卫按用户。**服务文件不存在** | `MODULE_NOTES.md:378,569` · `readiness_workflow.py:35` |

---

## 2. 排程

```
D0 今日(我,30 min,零风险,不依赖任何拍板)
   D8 清 build cache → D11 ANALYZE → D10 worker ×3 + max_connections=200
        │
        ├── A 线 · 部署(半天)                       ├── B 线 · 产品(~3.5 天,两条 lane 并行)
        │   D3 .env + 重建 web(我)                   │   lane-issuer: U1 → U3   (都改 issuer 页)
        │   D1 DNS(boss,5 min)                      │   lane-main:   U2 → U4 → U5(都改 page.tsx)
        │   D2 Caddy(我/boss)                        │   每条:offline 绿 + tsc → commit → 真域名验收
        │   D4 Clerk origins(boss,5 min)            │
        │   D5 smoke(定义"上线完成")                 │
        │                                             │
        └── 广发前(与 B 线并行,独立 lane):D6 singleflight(0.5d)· D7 OpenAI 上限(boss)· D9 备份(0.2d)
```

**文件租约**(并行执行的冲突边界):lane-issuer 拥有 `issuer/[ticker]/page.tsx`、`lib/issuer.ts`、`routes/research.py`;lane-main 拥有 `page.tsx`、`ChatPanel.tsx`、`PortfolioModal.tsx`、`lib/api.ts`、`routes/portfolios.py`、`routes/exposure_runs.py`、`package.json`;D6 拥有 `services/ingest_lock_service.py`(新)、`readiness_workflow.py`、相关测试。共享件(`lib/errors.ts` 新,U3 建、U2 用)由 lane-issuer 先建。

---

## 3. D0 — 今日零风险三件(我,~30 min)

- **D8** `docker builder prune -af`:回收 ~4 GB。验收:`df -h` 可用 ≥ 12 GB。
- **D11** `ANALYZE` 全库(owner 角色一条命令)。验收:`pg_stat_user_tables.n_live_tup` 与 `count(*)` 一致。
- **D10** compose:`exposure-worker` 默认 `deploy.replicas: 3`(或 `--scale`,写进 PRODUCTION.md 的 `up` 命令);postgres `command: ["postgres", "-c", "max_connections=200", "-c", "shared_buffers=256MB"]`(RAM 3.8 GB,256MB 安全)。改 `max_connections` 需重建 postgres 容器(秒级停机,**数据卷不动**)。验收:`show max_connections` = 200;三个 worker 日志各自 `Worker started`;`test_deploy_config` 绿。连接预算:api 30 + mcp 30 + worker 3×30 = 120 < 200。

---

## 4. A 线 — 部署(半天)

| # | 谁 | 动作 | 验收 |
|---|---|---|---|
| **D3** | 我 | `.env`:`NEXT_PUBLIC_API_URL=`(空=同源)、`CORS_ORIGINS=`(空)、`CLERK_AUTHORIZED_PARTIES=http://localhost:3103,https://exposure.noclosedform.com`(逗号列表,`clerk_authorized_parties_list` 已支持——**两个都留**,否则本机 3103 的登录立刻被 `bad_azp` 拒);`docker compose build exposure-web && up -d exposure-web exposure-api` | `test_deploy_config` 绿;本机 3103 登录仍可用 |
| **D1** | **boss** | Cloudflare:A 记录 `exposure` → `100.49.167.5`,**grey cloud**(DNS-only) | `dig +short exposure.noclosedform.com` = 该 IP。**必须先于 D2**:Caddy 对不解析的名字会在后台反复申证失败 |
| **D2** | 我(DP2) | `sudo cp /etc/caddy/Caddyfile /etc/caddy/Caddyfile.bak.$(date +%F)` → 把 `infra/Caddyfile.example` 的块(域名改 `exposure.noclosedform.com`)追加到文件末尾 → `sudo caddy validate --config /etc/caddy/Caddyfile` → 仅在 validate 通过后 `sudo systemctl reload caddy` | `curl -sI https://exposure.noclosedform.com/api/health` 200;`noclosedform.com` 仍 200(**不能伤及同机其他站**) |
| **D4** | **boss** | Clerk dashboard(dev 实例)→ 允许 origins 加 `https://exposure.noclosedform.com` | 该域名上 Sign in 弹窗能完成登录 |
| **D5** | 双方 | **上线完成的定义**:真浏览器在该域名注册新账号 → chat 问一句带数字的话 → Investigate 一个 ticker 跑完 research → 配额头显示。顺带盖三项悬案:**research 侧 `llm_session` 栈上验证**(`llm_cost_by_research_run` 该 run 非零)、llm_call 行样式、503 呈现(可选:停 mcp 再发一条) | 全部人眼 + psql 核对 |

---

## 5. B 线 — 产品:陌生人的前 10 分钟(~3.5 天)

### lane-issuer

**U1(~1 天)Research 等待叙事 + 失败人话上屏**
- API:`WorkflowEventOut` 从 `routes/exposure_runs.py` 抽到 `apps/api/schemas.py`(两路由共用,不复制);`ResearchRunOut` 增 `workflow_events: list[WorkflowEventOut]`,GET `/research-runs/{id}` 按 `run_id` 读 `workflow_events`(同 exposure 的读法)。
- Web:`lib/issuer.ts` 的 `ResearchRun` 增 `workflow_events`;把 `page.tsx:213-283` 的 reduce + `StepIcon` 抽成 `components/RunTimeline.tsx`,主页与 issuer 页共用;issuer 页 header 下方在 run 活跃/刚结束时渲染时间线(`resolve_company → ingest_filings → extract_facts → … → agent_session → finalize`,每步带 message——冷 ticker 用户看到的是"正在 ingest 第几份 10-K",不是 spinner);`failed` 时渲染 `error_message` 替换裸红字。3s 轮询不变。
- 验收(offline):`ResearchRunOut` 形状测试;`RunTimeline` 两处 import 同一组件(grep 守卫:reduce 逻辑全仓一处)。(live):冷 ticker 真 run 全程可见每步;停 mcp 的失败 run 页面显示那句人话。

**U3(~0.5 天)`port_001` 硬编码 + issuer 页错误人话**
- 主页两处 Investigate 链接(`page.tsx:596,615`)改为 `/issuer/${ticker}?portfolio=${selectedPortfolioId}`;issuer 页读 query,`startResearch(tk, portfolio)`,无 query 则**不传**(API 已可选)。硬编码删除。
- 新建 `lib/errors.ts`:`explainApiError(e): { notice: string; dropSession?: boolean }`,把 `ChatPanel.tsx:150-190` 的分支**搬过去**(ChatPanel 改为调用它——不留两份);issuer 页 `runResearch` 的 catch 用它(409 活跃 run、429 配额带数字与重置时间、503 tool face、401 请登录)。
- 验收(offline):`explainApiError` 每个分支一测;grep 守卫:`port_001` 在 `apps/web` 零出现。

### lane-main

**U2(~0.5–1 天)First-run 空态 + chat 示例提问**
- API:`PortfolioOut` 增 `is_public: bool`(列已存在,RLS 已保证只返回自有 + 公共)。
- Web:`LeftPanel` 当**已登录且无自有组合**(全部 `is_public`)时渲染 first-run 卡:一句话("Your desk is empty. Start from the demo book or bring your own.")+ 两个动作(**Clone demo**——直接调 `cloneDemoPortfolio`,不再藏弹窗;**Upload CSV**——开现有弹窗)+ 一条示例提问(点击打开 ChatPanel 并预填)。ChatPanel 空态的提示文字改为 **3 个可点 chip**(如 "What's my largest exposure?" / "Why did NVDA move this week?" / "Give me a brief on MSFT")。
- 验收(offline):`is_public` 形状测试;tsc。(live):新账号登录 → 看到卡 → Clone demo → 组合出现 → chip 发问得到带引用回复。

**U4(~0.5 天)`evaluated` 露出**
- API:`WorkflowEventOut` 增 `payload_summary: dict`(列已有)。
- Web:`MiddlePanel` 告警区下方一条 muted 行:`N checks evaluated · skipped: …`(来自 `check_limits` 步的 `evaluated`),以及压力步的 `scenarios_unevaluated` 与各情景 `factors_held_flat`——**没跑的和跑了通过的从此长得不一样**。
- 验收(offline):形状测试;(live)真 run 页面可见。

**U5(~0.5 天)报告渲染补全**
- 加 `react-markdown`(默认不渲染原始 HTML,无需额外 sanitize);报告区新增 `markdown_report`(折叠区,默认展开)、`factor_explanation`、`risk_alert_explanation`。`confidence_flags` 已有的 mock 标志保留。
- 验收:tsc;真 run 的 79 数字过门的那份报告完整可见。

---

## 6. 广发前三件(朋友级流量可后置;发公开链接前必做)

**D6(~0.5 天)ingest singleflight** —— 按 MODULE_NOTES 既定设计实现,不再设计:
- `services/ingest_lock_service.py`:`async with ingest_lock(company_id)`——在**独立连接**上 `pg_advisory_lock(hashtext(company_id))`(readiness 每步自行 commit,事务级锁跨不过去,故用会话级锁 + 专用连接,`finally` 解锁);先 `pg_try_advisory_lock`,拿不到则进入等待路径。
- `run_readiness`:把 `ingest_filings / extract_facts / …` 整段包进锁;等待时经 `step(db, run_id, "await_ingest", f"Another run is ingesting {ticker}; waiting")` 在时间线上**显式记一步**(设计已论证其信息泄露可接受);拿到锁后**重查 `_is_ready`**,已就绪则跳过 ingest。两个调用方(`company_readiness` handler、`issuer_research_workflow`)零改动——锁在它们共用的函数里。
- 验收(offline):锁键派生、try/wait 分支各一测;(live):两个用户并发 Investigate 同一冷 ticker → `filings`/`filing_chunks` 行数与单跑一致,后到的 run 时间线有 `await_ingest` 一步,两人各得自己的 brief。
- 顺带关掉挂起区"filing_chunks UNIQUE 三份 schema 同落"的**必要性**(串行化使重复不可能),约束本身仍作 belt 记在挂起区。

**D7(boss,5 min)** OpenAI dashboard 月度硬上限。依据:实测 chat turn ≈ $0.004,research ≈ $0.15–0.30(待 D5 钉数);正常日 ≈ $3–10,**对抗日天花板 ~$200**(配额按动作计,挡不住 token 尾部)。
**D9(~0.2 天)** 宿主 crontab 追加:`0 3 * * * docker exec exposure-postgres pg_dump -U exposure exposure_workbench | gzip > /home/ubuntu/backups/ew-$(date +\%F).sql.gz && find /home/ubuntu/backups -name 'ew-*.sql.gz' -mtime +7 -delete`。验收:手跑一次,文件可 `gunzip -t`;注明备份与库同盘(demo 级,异地副本留待之后)。

---

## 7. 风险与退路

- **D2 动的是同机三个站共用的 Caddyfile**:备份 + validate 关卡是硬规矩;任何失败 `cp` 回备份并 reload,秒级恢复。
- **D3 改 `CLERK_AUTHORIZED_PARTIES`**:忘留 localhost 会让本机登录当场 `bad_azp`;列表两个都留,D3 验收项明写。
- **D10 重建 postgres 容器**:秒级停机,数据卷不动;若 `shared_buffers=256MB` 起不来(内存不足)退回 128MB,只改 `max_connections`。
- **U 批两条 lane 的文件租约**必须守——V4 批的教训(并行 agent 在共享工作树撞车两次)。
- **D6 的会话级 advisory lock 若进程死在锁内**:连接随进程关闭,锁自动释放;无需 reaper。
- **不做的**(本批明确不碰):mcp 2.0 迁移(S3)、量化升级(V5/V6 候选)、卫生三条(NULL-owner、tasks/usage 守卫、HNSW)——全部上线后。

---

## 8. 实测记录(2026-08-22)

> **B 线与广发前件全部完成**;A 线待 boss 的 D1(DNS)与 D4(Clerk origins)。
> **747 offline / 118 live 全绿**(批前 717/118),tsc 干净,`next build` 干净,四镜像已重建、栈已在新代码上。

| 阶段 | commit | 落地与实测 |
|---|---|---|
| **D0** | `2e4650e`^ | 盘 79%→**71%**(回收 4.0 GB build cache);`ANALYZE` 后统计回真(`filing_chunks` 报 0 → 3,078);postgres `max_connections=200` / `shared_buffers=256MB`,**worker 3 副本**各自起来。连接预算:api 30 + mcp 30 + 3×30 = 120 < 200。重建 postgres 容器后 118 live 复跑全绿 |
| **prep** | `09deca6` | 共享面重构,零行为变化:`WorkflowEventOut` 抽进 `apps/api/schemas.py` **并带上 `payload_summary`**(U4 的数据自此在 wire 上);`RunTimeline` 组件从 page.tsx 抽出;`explainApiError` 从 ChatPanel 抽出。**做在两条 lane 之前**,因为这三处各自横跨两条 lane 的文件——V4 批并行撞车两次的教训 |
| **D6** | `2e4650e` | 会话级 advisory lock + 专用连接(readiness 每步自提交,事务级锁跨不过去);步骤 2–6 在锁内,步骤 1(产出 key)与步骤 7(append-only 台账)在外;等待期间 `await_ingest` 步**开着**。5 条守卫,含一条读源码钉住锁的边界。**比计划更小**:`index_filing` 已有 `is_indexed` 短路,串行化后逐步幂等自然生效,不需要再查一次 `_is_ready`——而且 `_is_ready` 在 `issuer_research_workflow`,反向 import 会循环 |
| **D9** | `c4fee16` | `scripts/backup_db.sh` + cron 03:30 UTC,实跑通过(**27 MB**,`gzip -t` 通过);写 `.partial` 再改名、成功后才裁剪。**计划里"几 MB"是我估错的**,按实测改注释:7 份 ≈190 MB 对 12 GB 可用。PRODUCTION.md 新增恢复命令,并写明**与库同盘**(挡得住误迁移/误删,挡不住掉盘) |
| **U1** | `f92b4d9` | research run 返回 `workflow_events`(**手写查询非关系加载**:`workflow_events.run_id` 对三种父多态,库里无 FK——lane 读了 init.sql 与 delete_user.py 才确认)。栈上实测:completed run 6 事件、failed run 4 事件且 `error_message` 到位(`the research tool face at ... could not be reached (connect_error)`)。判断:run 一存在面板即出现(空态"Queued…");结束后**不自动隐藏**(定时器会跟注意力赛跑,失败时这是唯一写原因的地方);排序 `created_at, id`(同秒的 running/completed 反了会让完成的步永远转圈) |
| **U3** | `f92b4d9` | `port_001` 从 `apps/web` 彻底消失,portfolio 从 URL 取。**顺带修了我 prep 造成的回归**:共享件带走了 chat 的 404 措辞,于是打错 ticker 会说"你的对话已过期"并丢掉无关 session。根因是三个拒绝仍是散文,共享件只能按状态码猜——现已带码(`unknown_session`/`unknown_ticker`/`not_investigable`),并加**跨语言守卫**(UI 解释的每个码必须真有人抛;这是该故障沉默的那一半:两边各自自洽,分支永不触发)。又修了 3s 轮询无 catch——U1 之后冻住的时间线读起来像"run 挂了"而非"页面失联" |
| **U2** | `a2b292a` | `PortfolioOut` 增 `is_public`(web 此前根本分不清 demo 与自有)。栈上实测:probe 用户 `[('port_001','US Growth & Income', True)]` → first-run 卡判定为 **True**。卡在列表**上方**不替换列表(浏览 demo 是新账号唯一能做的另一件事);匿名橱窗字节不变。chat 三条建议**填入不发送**——建议里的 ticker 是占位符,误点会花掉可数日配额里的一次 |
| **U4** | `a2b292a` | 栈上实测 payload 键真实存在:`check_limits: ['evaluated','inert_overrides']`、`calculate_risk: [...,'scenarios_evaluated','scenarios_unevaluated']`。放在告警摘要**正下方的无框弱化文字**,不是第四张卡——旁注只有贴着它所限定的断言才读得出是旁注;装进框里会与告警争同一眼而输,正如它作为无人渲染的列输掉一样。跑了却没记的 run 渲染"This run did not record what it evaluated",而不是留白 |
| **U5** | `a2b292a` | `markdown_report` 上屏(V6-G 的门刚护住 79 个数字,而没有 UI 渲染它),折叠,**开关上带着门的判词**(`numbers_checked`)。react-markdown 10.1.0 默认转义原始 HTML 且未传插件,不需额外 sanitizer |

^ D0 的 compose 改动与 D6 在同一批推送。

---

## 9. 执行期发现(不静默)

1. **`next build` 在 Next 16 / Turbopack 下不跑 eslint**——我在两条 lane 的验收指令里写的"未使用的 import 只有 build 才看得出"是**错的**,只有 `npx eslint` 抓得到。已实测确认;lane-main 据此清掉 6 个 warning。
2. **6 个 lint error 先于本批存在**(stash 对照:改动前 12 problems/6 errors,改动后 6/6):`ChatPanel.tsx:108` 与 `PortfolioModal.tsx:41` 的 `react-hooks/set-state-in-effect`,`lib/issuer.ts` 的 4 个 `no-explicit-any`。**临部署不动**:`CalcRow.result` 有真实消费者(`r.result?.value`/`?.points`),改 `unknown` 会连锁;两个 set-state 是行为重构。记入上线后卫生。
3. **D3 推迟到 D2 割接时**:`NEXT_PUBLIC_API_URL=`(空=同源)是 build 期内联,提前翻掉会让 `localhost:3103` 去调自己不存在的 `/api`,毁掉 B 线正在用的验证环境,而 DNS 在 boss 手上。
4. **计划里的两处坐标是错的**:Investigate 链接在 page.tsx **562/581**(计划写 596/615);`WorkflowEvent.run_id` 在 `models.py:417` 声明了库里没有的外键(P0 去掉的,挂起区已登记,只记不动)。
5. **U1 的冷 ticker 路径尚未在栈上验**:现有 run 都是热 ticker,时间线只有 3 步(readiness_precheck/agent_session/finalize)。真正要它的是冷 ticker 的 6 步 ingest 叙事——那需要一次真冷 run,并入 D5 smoke。
6. **lane-main 未做计划里 U2 的第三个元素**(示例提问打开 chat 并预填):它判断那要跨组件预填管线,而 chip 集已经住在面板里。同意,记录。
