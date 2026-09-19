# Implementation Plan V2 — 多用户 Portfolio 工作台 + 生产化

> **版本**:2026-07-24
> **读者**:执行实现的 agent(假定没有架构讨论的对话上下文,本文档自足)
> **前置阅读(必读,按序)**:
> 1. [TARGET_ARCHITECTURE.md](TARGET_ARCHITECTURE.md) v3 —— 系统不变量,**任何实现与它冲突时以它为准并停下来问用户**
> 2. [MODULE_NOTES.md](MODULE_NOTES.md) M14 —— 本轮设计定稿(数据三层归属、RLS、universe 表、匿名边界)
> 3. [IMPLEMENTATION_PLAN.md](IMPLEMENTATION_PLAN.md) —— 已完成的 P0-P9 基线(体例与纪律沿用)
> 4. [spikes/P9_COVERAGE.md](spikes/P9_COVERAGE.md) —— 现状基线数字(83 offline 测试、8 issuer、demo 组合 port_001)

**本计划交付**:用户注册/登录(Clerk)→ 创建/上传/克隆自己的 portfolio → 公司层数据共享、chat/组合/分析按用户隔离(Postgres RLS)→ 全美股 ticker 宇宙搜索(U2)→ per-user 日配额 + worker 崩溃恢复 + 价格新鲜度 fail-loud → 公网部署。

---

## 0. 执行者须知

### 0.1 全局规则(继承 V1 三条,新增两条;违反 = 返工)

1. **Fail loud**:无 mock、无静默降级。校验失败 = 整单拒绝 + 逐行理由,禁止"跳过坏行继续"。
2. **Schema 消灭解析**:不变。
3. **正交替代路由**:不变。禁止任何"智能猜 ticker"的模糊自动匹配——歧义消解只能由用户点击完成。
4. **安全归 RLS,语义归谓词**:租户隔离**只信数据库政策**。service/route 里的 owner 过滤只允许作为业务语义(如"我的组合"),必须注释 `# semantic, not security`;任何以安全为目的的应用层 WHERE = 违规。
5. **demo 公共面不许破**:任何阶段结束,匿名访客(无 token)访问 `/`、`/issuer/NVDA`、demo brief 的路径必须完好。demo 数据是产品的一部分。

### 0.2 硬性代码纪律(继承 + 新增)

- import 单向不变:`apps → tools → services → providers/db`;新 provider 只进 `providers/`
- append-only 不变,且扩展到 positions:**重传 = 新 as_of_date 快照,禁止 UPDATE/DELETE 旧持仓行**
- **schema 三份同步**:每个变更同时进 `infra/init.sql`(新库)+ `db/models.py`(镜像)+ `infra/migrations/v2_multiuser.sql`(幂等 ALTER,应用到活库;本项目无 alembic,此文件即迁移真相)
- `app_rls` 运行时角色**不授 DELETE**(append-only 在权限层顺便硬化)
- 前端:`page.tsx` 只加不重构;新 UI 一律组件化(`app/components/`)
- 明确不做(全计划):组织/团队、用户间共享、组合原地编辑、**应用内**删除流(最多 `is_active=false`)、agent 写组合的工具(编辑只走 UI)、非美市场、alembic、WebSocket
  - ★ V2-H 划界:上面禁的是**应用面**的删除流(路由、agent 工具、UI 按钮)——`app_rls` 无 DELETE 授权就是这条规则在权限层的硬化。**运维脚本不在此列**:以 owner 角色执行的 `scripts/delete_user.py` 是删号的唯一形状,它不是产品功能,不经过 API,只由运维手工调用。这不是给禁令开口子,而是承认「用户有权被抹除」与「应用代码不得删行」是两件事

### 0.3 环境前置(用户提供)

```
阶段 A live 验收前:Clerk 应用(免费层)——
  NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY   前端
  CLERK_ISSUER                        如 https://xxxx.clerk.accounts.dev
  CLERK_AUTHORIZED_PARTIES            逗号分隔,先填 http://localhost:3103
阶段 F 前:子域名拍板(默认 exposure.noclosedform.com)+ EC2 Caddy 配置权限
既有 key 不变(OPENAI/TAVILY/EDGAR_IDENTITY)
```

缺 Clerk key 不阻塞编码:离线测试用本地 RS256 密钥对 + 假 JWKS(0.4)。

### 0.4 测试与提交约定

- 单测离线、fixture、确定值;需 DB/网络/key 的标 `@pytest.mark.live`
- auth 离线测法(钉死):测试内生成 RS256 密钥对,monkeypatch JWKS 客户端返回本地公钥,签四类 token(有效/过期/错 iss/错 azp)断言分支
- RLS 测试必须打真 Postgres(标 live):以 `app_rls` 连接 + `SET LOCAL` 切换用户断言可见集
- 每阶段结束:`pytest -m "not live"` 全绿(基线 83)+ 阶段验收全过 + commit(消息 `V2-{阶段}: <摘要>`)
- **回归红线(每阶段三条)**:
  1. `pytest -m "not live"` 全绿
  2. demo 组合 exposure run 11 步全绿(C 起:以 `user_demo_system` 上下文或测试 token 触发)
  3. 匿名 GET `/`、`/issuer/NVDA`、demo latest-brief 全部 200;(C 起追加)匿名 POST 任何写路径 = 401

### 0.5 钉死的实现常量

| 项 | 值 |
|---|---|
| `users.id` | Clerk user id 原文(TEXT PK);系统哨兵 `user_demo_system` |
| PG 会话变量 | `app.user_id`,事务内 `SET LOCAL`;政策读 `current_setting('app.user_id', true)`(missing→NULL→fail-closed) |
| DB 角色 | `exposure` = owner,仅 DDL/migration/seed;**`app_rls`** = api+worker 运行时(LOGIN,GRANT SELECT/INSERT/UPDATE,**无 DELETE**;非 owner 故 RLS 天然生效) |
| 新 env | `DATABASE_URL_APP`(app_rls 连接串)、`APP_DB_PASSWORD`、`NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY`、`CLERK_ISSUER`、`CLERK_AUTHORIZED_PARTIES` |
| 并发(settings,env 可覆盖) | `TASK_LEASE_SECONDS=1800` `TASK_MAX_RETRIES=3` `TURN_LEASE_SECONDS=900`。两把 lease 都靠「取值够宽 + 到期自愈」,**不续期、不心跳** |
| 日配额(settings,env 可覆盖) | 单位 = **用户动作**,不是 token、不是工具调用。per-user:`DAILY_CHAT_TURNS=10` `DAILY_RESEARCH_RUNS=3` `DAILY_READINESS=10` `DAILY_EXPOSURE_RUNS=20` `DAILY_MARKET_SYNCS=10` `DAILY_PORTFOLIO_CREATES=5` `DAILY_POSITION_UPLOADS=10` `DAILY_AGENT_SESSIONS=5`;全局兜底 `GLOBAL_DAILY_*` = `200/30/100/200/50/100/100/100`(**同序**)。后三池 V2-H 追加,理由见 §0.5 扣费点一行。与 §6 的**会话内**预算(40 工具调用 / 5 次 external_search)是两层正交的东西,勿混 |
| 配额口径 | 计数表 `usage_daily(user_id, day, kind, used)` PK`(user_id, day, kind)`,共享层**无 RLS**(同 `tasks`);全局池 = 同表保留行 `user_id = '_global'`;`day` 取 UTC(`utils/dates.today_utc()`),`resets_at` = 次日 UTC 00:00(= 北京时间 08:00);扣费点**共五个,逐一列出**:①`task_service.create_task`(按 `task_type→kind` 映射,无默认值)②`POST /agent/sessions/{id}/messages`(`chat_turn`)③`portfolio_service.create_portfolio`(`portfolio_create`,同时盖住新建与克隆 demo)④`POST /api/portfolios/{id}/upload`(`position_upload`)⑤`POST /api/agent/sessions`(`agent_session`,扣在**路由**不在 service——service 层会踩到 MCP server 的无 owner session 与 research workflow 的重复扣费)。①③⑤与调用方共事务(工作廉价且本地,失败一起回滚是对的);②④是**先提交的门事务**——花销发生在请求内而非 worker 上,共事务会让每次被拒的请求把已花掉的 provider 钱退回去,变成免费重试循环 |
| 价格新鲜度 | `PRICE_STALENESS_DAYS=10`(自然日,约 7 个交易日);判定点**唯一**,在 `exposure_workflow._validate_inputs` |
| CSV 规格 | 列 `ticker,quantity[,cost_basis]`;首行含 "ticker" 视为表头;≤200 行;quantity>0;**整单原子**——任一行错则零写入,返回 `problems:[{row,ticker,reason}]` |
| 新组合默认 | currency=USD,benchmark=SPY,risk_limits = 拷贝 demo(port_001)的限额模板 |
| 快照语义 | 每次上传 as_of_date = `SELECT max(price_date) FROM market_prices`;price=该日 close;market_value=quantity×close |
| universe 源(D) | `https://www.nasdaqtrader.com/dynamic/SymDir/nasdaqlisted.txt` + `.../otherlisted.txt`(\|分隔,剔 `Test Issue=Y` 与尾行)+ `https://www.sec.gov/files/company_tickers.json`(UA=EDGAR_IDENTITY)。实测 ~13k 行 / SEC 10,429 家 |
| 符号映射 | yfinance 侧 `'.'→'-'`(BRK.A→BRK-A),**只在 market-data provider 调用点转换**;库内存上市文件原文 |
| 搜索排序 | ticker 精确 > ticker 前缀 > name ILIKE 子串;limit 10;**typeahead 点击确认,永不自动选** |
| 错误码(附 HTTP 状态) | `unauthenticated`(401) `turn_in_flight`(409) `quota_exceeded`(429) `active_run_exists`(409) `ticker_not_supported`(U1,422) `ticker_not_in_universe`(U2,422) `no_price_data`(422) `invalid_csv`(422)。**注**:与工具面的 `budget_exceeded`(会话内预算,结构化工具结果,非 HTTP)是两回事,勿改名勿混用 |
| 错误体信封 | 一律 `raise HTTPException(status, {"error": ..., ...})`,FastAPI 包成 `{"detail":{...}}` —— 与既有 401/409 一致。**禁止**为此新增本仓第一个 exception handler 或 JSONResponse |
| 验收主角 | 双账号 **A/B**(Clerk 免费两邮箱)+ 匿名 + demo |

### 0.6 数据归属总表(政策的唯一依据)

| 层 | 表 | RLS |
|---|---|---|
| **共享(公司层)** | companies, filings, filing_documents, filing_sections, filing_chunks, financial_facts, research_sources, **calc_ledger**, market_prices, factor_prices, security_master, tasks(系统队列,带 `owner_user_id` 供 worker 设上下文), usage_daily(E:配额计数,带 `user_id` 且含全局保留行 `_global`;**故意不加 RLS**,否则全局兜底池只数得到调用者自己 = fail-open) | 无 |
| **用户主表** | users(本人可见)、portfolios(`owner OR is_public`)、agent_sessions(owner)、research_runs(owner)、issuer_briefs(`owner OR is_public`) | 有,owner 列在此五表 |
| **子表(EXISTS 级联,不加 owner 列)** | positions/risk_limits/schedules → portfolios;exposure_runs → portfolios;metrics/sector_exposures/issuer_exposures/factor_attributions/**factor_residuals**/risk_alerts/daily_reports/workflow_events → exposure_runs;agent_messages/agent_steps/evidence_packs → agent_sessions | 有,`EXISTS(父表)`(父表政策自动级联) |

> ★ 两处此前失真、V2-H 更正:①共享层原写 `factor_*`,该通配把 `factor_residuals` 一并卷进「无 RLS」,而它其实是 `exposure_runs` 的子表——共享的只有 `factor_prices`。②`daily_reports` 的外键是 `run_id REFERENCES exposure_runs(id) ON DELETE CASCADE`(init.sql:221),而它的 RLS 策略键在**反范式化的 `portfolio_id`** 上(init.sql:659),该列不带外键;两者今天一致,只是因为写入方恰好这么填。删号脚本按外键筛,不按策略键筛。

推论(实现时反复自查):demo 组合 `is_public=true` → 其 runs/alerts/reports 对所有人可见(公共沙盘,诚实);用户组合的一切只有本人可见;`/api/evidence/{run_/alert_}` 跨用户自动 404,零代码。

### 0.7 阶段依赖图

```
A(身份) ─▶ B(组合 U1) ─▶ C(RLS) ─▶ D(Universe U2) ─▶ E(并发+配额+新鲜度) ─▶ F(部署) ─▶ G(终验)
串行执行。D 仅逻辑依赖 B,但与 C 改同一批上传文件,不并行。总预估 ~8 agent 工作日(E 因实测新增 E0/E5 由 1d 上调为 2d)。
```

### 0.8 风险与回滚杠杆

- RLS 调错的典型症状是**查询莫名为空**(fail-closed,不泄数据)。排障顺序:确认连接角色是 app_rls 非 owner → 确认事务内 SET LOCAL 已执行 → 单表 `DISABLE ROW LEVEL SECURITY` 二分定位。
- owner 列 A 阶段先 nullable,C 阶段回填后收紧 NOT NULL——中途任何阶段可安全停。
- `.env` 保留 `DATABASE_URL`(exposure 直连)用于本机排障与 seed;运行时容器只用 `DATABASE_URL_APP`。

---

## V2-A — 身份与写门禁(1d)

**范围**:Clerk 集成、users 表、写路径门禁、owner 落列(nullable)。不做 RLS。

**任务**:
1. 依赖:`pyproject.toml` + `pyjwt[crypto]`;web + `@clerk/nextjs`
2. schema(三份同步):`users(id TEXT PK, email TEXT, display_name TEXT, created_at, last_seen_at)`;`agent_sessions.owner_id TEXT NULL`、`research_runs.owner_id TEXT NULL`、`issuer_briefs.owner_id TEXT NULL, is_public BOOL DEFAULT false`、`portfolios.owner_id TEXT NULL, is_public BOOL DEFAULT false`、`tasks.owner_user_id TEXT NULL`
3. `src/exposure_workbench/auth/clerk.py`:`verify_token(token) -> UserClaims{user_id, email?}`——PyJWKClient(缓存,JWKS URL = `CLERK_ISSUER + "/.well-known/jwks.json"`),校验 exp/nbf/iss/azp∈AUTHORIZED_PARTIES;失败抛 `AuthError(reason)`,不吞
4. `apps/api/auth_deps.py`:`optional_user` / `require_user` 两个 dependency;require 失败 → 401 `{"error":"unauthenticated"}`;成功 → upsert users 行(last_seen)+ 写入 contextvar `current_user_ctx`
5. 写门禁接线:grep 全部 POST/PUT 路由列清单(进 commit message),对以下接 `require_user` 并落 owner:`POST /api/agent/sessions`(owner_id)、`POST /api/agent/sessions/{id}/messages`、`POST /api/exposure-runs`、research.py 的触发端点(owner_id 落 research_runs + tasks.owner_user_id)、`POST /api/market-data/sync`。**读路由一律不加门禁**(可见性 C 阶段由 RLS 决定)
6. `GET /api/me`(require)→ `{user_id, email}`
7. web:`layout.tsx` 包 ClerkProvider;Header 右侧 SignInButton/UserButton;`lib/api.ts` 增加模块级 `setAuthTokenGetter(fn)`,fetchJson 有 token 则带 `Authorization: Bearer`;app 内用 Clerk `getToken()` 注册一次。ChatPanel 未登录态显示"登录后可与分析师对话"占位(读侧组件不动)
8. `TARGET_ARCHITECTURE.md` 追加 §13「租户拓扑」一页(三层归属表 + RLS 强制点图),随本阶段提交

**验收**:
- [ ] 离线:verify_token 四分支(有效/过期/错 iss/错 azp);require_user 无 token→401
- [ ] live(有 Clerk key):浏览器登录 → `/api/me` 200 且 users 出现该行;匿名 `curl POST /api/agent/sessions` → 401;带 token → 201 且 `owner_id` 已落
- [ ] 登录后 chat 一轮正常(功能同前,多了 owner)
- [ ] 回归红线三条

**禁止**:任何 RLS/政策;会话列表改造(C);自建密码/session 代码。

**用户检查点**:Clerk 三个 env 值;确认登录入口位置(header 右侧)。

---

## V2-B — 用户 Portfolio:创建 / CSV 上传 / 克隆(U1,覆盖集)(1d)

**范围**:组合写路径全套,ticker 限已覆盖集。搜索框与任意 ticker 属 D。

**任务**:
1. `services/portfolio_csv.py`:`parse_csv(text) -> list[PositionRow] | problems`(0.5 规格;错误逐行收集)
2. `services/portfolio_service.py` 扩:
   - `create_portfolio(db, owner_id, name)`(0.5 默认值;risk_limits 拷贝 demo 模板)
   - `upload_positions(db, portfolio_id, rows, as_of=None)`:校验 ticker ∈ `SELECT DISTINCT ticker FROM market_prices`(U1 的"能分析"诚实判据;不在 → `ticker_not_supported`)、quantity>0;**整单原子**;定价按 0.5 快照语义;返回 `{as_of_date, inserted}`
   - `clone_demo(db, owner_id)`:新组合 + 拷贝 demo 最新快照持仓
3. routes(`portfolios.py` 扩,全部 `require_user`):`POST /api/portfolios {name, csv_text}` → 201 或 422{problems};`POST /api/portfolios/{id}/upload {csv_text}` → 新快照(owner 校验此阶段应用层临时判,注释 `# temporary until RLS (V2-C)`);`POST /api/portfolios/clone-demo`;`GET /api/portfolios` 返回 demo + 本人的(登录时;谓词注释 semantic)
4. web:LeftPanel 加 [New Portfolio] → Modal(name + CSV textarea + 文件选择读文本 + problems 逐行 verbatim 展示)+ [Clone demo] 按钮;选中自己组合后 Run Daily Update 直接可用(已参数化)

**验收**:
- [ ] 离线:parse_csv(表头识别/非法行/超 200);upload 原子性(一行坏→零插入)与逐行 reason;clone 行数一致
- [ ] live:登录 → CSV `AAPL,10 / MSFT,5 / TLT,20` → 组合出现,positions 按最新收盘定价;对它 Run Daily Update → 11 步全绿,MV=Σqty×close 非零;重传新 CSV → 新 as_of 快照,旧行仍在;`PLTR,10`(无价格数据)→ 422 指名该行,库零变更
- [ ] 回归红线三条

**禁止**:security_master/任意 ticker(D);组合删除/改名。

---

## V2-C — 租户隔离:Postgres RLS(1.5d,本计划技术核心)

**范围**:app_rls 角色、回填与收紧、全部政策、SET LOCAL 注入(API/agent/worker 三路)、会话列表按用户。

**任务**:
1. 角色(init.sql + migration):`CREATE ROLE app_rls LOGIN PASSWORD :APP_DB_PASSWORD`;GRANT USAGE on schema/sequences,GRANT SELECT/INSERT/UPDATE on 全表(**无 DELETE**);compose 的 api/worker 改用 `DATABASE_URL_APP`
2. 回填与收紧(migration):插入 `user_demo_system`;历史 portfolios/agent_sessions/research_runs/issuer_briefs 的 owner 全部回填为它;demo 组合与现有 3 份 brief `is_public=true`;四个 owner 列 + users 检查后 `SET NOT NULL`
3. 政策(init.sql + migration,按 0.6 总表逐张):
   ```sql
   ALTER TABLE portfolios ENABLE ROW LEVEL SECURITY;
   CREATE POLICY tenant ON portfolios USING (
     owner_id = current_setting('app.user_id', true) OR is_public
   ) WITH CHECK (owner_id = current_setting('app.user_id', true));
   -- 子表模板(级联):
   CREATE POLICY tenant ON positions USING (
     EXISTS (SELECT 1 FROM portfolios p WHERE p.id = positions.portfolio_id)
   ) WITH CHECK (EXISTS (SELECT 1 FROM portfolios p
                         WHERE p.id = positions.portfolio_id
                           AND p.owner_id = current_setting('app.user_id', true)));
   ```
   owner-only 表(agent_sessions/research_runs/users)与二级子表(run children→exposure_runs)同模板推导。**WITH CHECK 必须写**(防越权写入 is_public 行)
4. 注入(单一 choke point):`db/session.py` 加 `tenant_session(factory, user_id)` async contextmanager(begin → `SET LOCAL app.user_id = :u` → yield);三路接线:①`get_db` 读 `current_user_ctx` 有则 SET LOCAL;②`meta_agent.handle_message` 的 db_factory 换 tenant 包装(session 的 owner);③worker 分派处按 `task.owner_user_id`(无则 demo 哨兵)包 tenant_session
5. 语义层:`get_portfolio_snapshot` 每项加 `is_own`(owner==当前用户;注释 semantic);meta prompt 补一句"用户有自有组合时默认以它为对象";`GET /api/agent/sessions`(require)返回本人会话(RLS 自动),ChatPanel 登录后从 API 列会话 + 切换,localStorage 只存"当前选中 id"
6. 匿名路径核验:无用户 → 不 SET LOCAL → current_setting 为 NULL → 只放行 is_public 链

**验收(双用户,live 为主)**:
- [ ] RLS 覆盖断言脚本:`SELECT relname FROM pg_class WHERE relrowsecurity` 与 0.6 清单完全一致
- [ ] 隔离:A 上传组合+run+chat+触发 NVDA research;B 的 `GET /api/portfolios` 只见 demo+自己;B GET A 的 run/session/messages → 404;B `GET /api/evidence/{A 的 run_ 或 alert_}` → 404;B 的 get_portfolio_snapshot 无 A 数据;B 看 NVDA latest-brief 仍是 demo 公开版而非 A 刚产出的私有版
- [ ] 匿名:demo 全读 OK;所有写路径 401
- [ ] SET LOCAL 无泄漏:同一池化连接顺序开两个 tenant_session(A、B),各自可见集正确
- [ ] 写越权:B 携 token 向 A 的组合 upload → WITH CHECK 拒绝(0 行)
- [ ] 回归红线三条(红线 2 改用 demo 哨兵上下文触发)

**禁止**:service 层任何以安全为目的的 owner WHERE;给 app_rls 授 DELETE;FORCE ROW LEVEL SECURITY(不需要——运行时角色非 owner)。

**用户检查点**:请用户以两个真实账号亲测一遍隔离;RLS 生效前后 `.env` 角色切换说明。

---

## V2-D — Security Master 宇宙 + 搜索 + 任意 ticker(U2)(1d)

**范围**:全美股目录表、typeahead 搜索、上传校验升级为宇宙成员 + 价格回填。

**任务**:
1. `providers/security_master_provider.py`:三个 fetch(0.5 的源与清洗规则),返回 `SecurityRowDTO{ticker,name,exchange,is_etf,cik?}`;任何源不可达/解析失败 → 抛错(fail loud),**不写半截**
2. schema:`security_master(ticker TEXT PK, name, exchange, is_etf BOOL, cik TEXT NULL, status TEXT DEFAULT 'active', source TEXT, fetched_at)`(共享层,无 RLS)
3. `services/security_master_service.py`:`refresh(db)`(全量 upsert;本次缺席的旧行标 `delisted`,不删)+ `search(db, q, limit=10)`(0.5 排序;返回附 `has_prices`(EXISTS market_prices)与 `has_cik`)
4. `scripts/refresh_security_master.py`;seed 尾部追加调用
5. 上传/加仓校验升级(替换 B 的 U1 判据):ticker ∉ security_master(active) → `ticker_not_in_universe`;∈ 但无价格行 → 调 `market_data_ingestion` 回填 1 年日线(yfinance 符号按 0.5 映射),仍无行 → `no_price_data` 拒该行(整单原子不变);新 equity 的 sector 于回填时从 yfinance info 取一次,None → `"Unclassified"`;is_etf → asset_class='etf'
6. route:`GET /api/securities/search?q=`(公开读)
7. web:Portfolio Modal 加持仓搜索框——300ms debounce → search API → 下拉 `TICKER — Name (Exchange) [价格✓|ETF|研究✓]` → **点击**加入持仓表格行(数量输入);CSV 通道保留(仍精确 ticker,批量不做名称解析)

**验收**:
- [ ] 离线:两个上市文件的 fixture 解析(含 Test Issue 剔除、BRK.A 点号保留、尾行剔除);`no_price_data` 拒绝路径(mock ingestion 返回 0 行)
- [ ] live:refresh 后 `security_master` >10,000 行且 AAPL/TLT/BRK.A 在;二次 refresh 幂等;search "apple" → AAPL 首位且能看到 APLE 等干扰项(点选消歧的活证据);上传 `RBLX,5` → 自动回填 >200 行价格、组合 run 11 步全绿含 RBLX;`BRK.B,1` → 符号映射生效、定价成功;`ZZZZZZ,1` → `ticker_not_in_universe` 整单拒
- [ ] 回归红线三条

**禁止**:自动触发 readiness/EDGAR 摄取(issuer 研究仍限 `is_investigable` 集,显式按钮);非美证券;pg_trgm(先 ILIKE,不够再说)。

---

## V2-E — 并发硬化 + 日配额 + 价格新鲜度(2d)

**范围**:worker lease/requeue/重试上限、per-session 单飞行 turn、per-user 与全局日配额、run 前价格新鲜度(消灭 $0 静默估值)。产品目标是「个人主页上的展示产品,但达到生产使用标准」:每个登录用户有自己的组合、每天可发起有限次 agent 动作、这些历史与分析都留在他自己的租户里。

**前置认定(实测得出,勿再推翻;推翻了原 V2-E 的两条前提)**

- ❶ **handler 并非都幂等** —— 接缝备忘曾断言「exposure/readiness/research handler 已幂等,lease 重投安全性依赖于此」,**此断言为假**。`exposure_workflow._persist_outputs` 是裸 `db.add` INSERT,打在 `exposure_metrics UNIQUE(run_id)`、`daily_reports UNIQUE(run_id)`、`sector_exposures UNIQUE(run_id,sector)`、`issuer_exposures UNIQUE(run_id,ticker)`、`factor_attributions UNIQUE(run_id,factor_name)` 上 → 第二次必 IntegrityError(`risk_alerts` 无唯一键,则静默重复);`issuer_research_workflow` 模块 docstring 自己写着 "deliberately NOT idempotent",`issuer_briefs UNIQUE(research_run_id)` 会在 agent 烧完整轮 LLM 预算**之后**才炸。真正幂等的只有 `company_readiness` 与 `market_data_sync`(全链 `ON CONFLICT DO UPDATE` + 索引短路)。
- ❷ **标 run failed 与回收 task 不对称** —— 以 `app_rls` 且**未设 tenant** 实测:`UPDATE exposure_runs SET status='failed'` 抛 RLS 错并**中止整个事务**(USING 靠 `p.is_public` 放行,WITH CHECK 却要求 `p.owner_id = current_setting(...)` 而它是 NULL);`UPDATE research_runs ...` 则**静默 0 行**。设了 tenant 后两者都成功。而 `tasks` **无 RLS**,reaper 的回收 UPDATE 无 tenant 也能跨租户批量执行(实测 UPDATE 命中全表)。
- ❸ **卡死 run 的代价不对称** —— `research_run_service.create_run` 有 `ActiveRunExists` 守卫(pending/running 即拒),一个卡死的 research run 让该用户对该公司**永久 409**,run 清理是**承重**的;`exposure_runs` 无此守卫,卡死只是 UI 上一直转,属观感。
- ❹ **$0 静默估值 bug 已复现** —— `calc_exposure` 左连接后 `merged["price"].fillna(0.0)`(`analytics/exposure.py:61`),窗口内无价的持仓 → price 0 / mv 0 / weight 0,run 照常绿。`_validate_inputs` 只挡「整个 DataFrame 为空」,而 `get_prices_df` 本就按持仓 ticker 过滤,**只要有一只票有价,partial miss 永远静默**。实测:AAPL 100 股 @200 + 无价的 STALE 200 股 → 报 MV \$20,000(真值 \$31,000),扇区权重 Tech 100% / Energy 0%。连带三处塌陷:`calc_pnl` 反而回退到 positions 存的旧价(`pnl.py:67-70`)→ 同一个 run 的分子分母来自两个宇宙;`build_portfolio_returns` 丢掉无价 ticker 再把幸存者归一到 100% → VaR/波动来自残缺组合;被低估的 `total_mv` 抬高所有幸存权重 → 直接喂给集中度限额检查。且 `calc_exposure`/`calc_pnl`/`ExposureWorkflow` 目前**零测试覆盖**。
- ❺ **两个既有缺陷必须先修**,否则 E1/E3 建在坏地基上,见 E0。
- ❻ **与上游文档的已知冲突,待回写**:`TARGET_ARCHITECTURE.md` §13.4 与 `MODULE_NOTES.md` M14 都写着「per-user 日上限**进 ToolRegistry wrapper**(session 预算加一维);cost views 按 user 聚合即可」。本节改为**按用户动作计数的 usage_daily 表 + 两个扣费点**,理由:wrapper 只看得见工具调用,而 research/exposure/readiness 各有 REST 与 agent 委派**两条平行入口**,wrapper 拦不住路由面;且按 `agent_steps` 数当日用量要 join `agent_sessions` 再对无索引的 `created_at` 做范围扫描,落在每次工具调用的热路径上。按 §0「以 TARGET_ARCHITECTURE 为准」的规矩,**E 开工前需用户拍板并回写 §13.4 与 M14**,否则实现者应停下来问。

**任务**:

**E0 — 前置修复(先做,各自独立可验证)**
1. **`company_readiness` 中毒任务**:`workflow_events` 的 RLS WITH CHECK 只认 `exposure_runs` / `research_runs` 两个父,而 readiness 用 `run_id = task.id`(`task_` 前缀)→ 以 `app_rls` 身份写第一条 step 就被拒。实测活库 **0 条 `task_` 前缀事件、0 个成功的 readiness task —— 这个 task type 经 worker 从未成功过一次**(V2-C 引入,至今未被发现,因为没人从 UI 触发过)。修:`workflow_events` 上的 `tenant` 是一条 `FOR ALL` 策略,**USING 与 WITH CHECK 两套表达式都只认那两个父,必须各加同一个第三分支**(init.sql + migration 同步):
   ```sql
   OR EXISTS (SELECT 1 FROM tasks t WHERE t.id = workflow_events.run_id
              AND t.owner_user_id = current_setting('app.user_id', true))
   ```
   (`tasks` 无 RLS,EXISTS 是普通查表。)**只补 WITH CHECK 不够**,USING 分支同样是写路径的必要条件:`log_event` 走 `db.add` + `flush`,SERIAL 主键让 SQLAlchemy 发出 `INSERT ... RETURNING id, created_at`,而 Postgres 对 `INSERT ... RETURNING` 会把 SELECT(即 USING)也套在新行上。实测:只补 WITH CHECK 时裸 `INSERT` = `INSERT 0 1`,带 `RETURNING` = `ERROR: new row violates row-level security policy` —— **报错文本读起来完全像 WITH CHECK 失败,会把实现者带回已经改过的那半边打转**。两边都补后 INSERT…RETURNING 通过,且时间线能被 `app_rls` 读到(否则验收里的「事件落库」只能以 owner 角色验)。**不修则 readiness 池毫无意义,且会在 E1 里每次都吃满 `TASK_MAX_RETRIES`。**
2. **cost 视图越权**:`session_cost` / `research_run_cost` 建在 owner 名下且未设 `security_invoker`。实测以 `app_rls` 无 tenant 查 `agent_sessions` 得 0 行,查 `session_cost` 得**全库 20 行(跨租户)**。目前无任何代码查这两个视图,故尚未被利用。修:两处都加 `WITH (security_invoker = true)`(PG16 支持),init.sql + migration 同步。
3. **`user_service.touch` 的行锁横跨整个 turn(E2 的前置,不修则 409 不可达)**:`require_user` 调 `touch`,它在**请求作用域的 `db`** 上 `UPDATE users SET last_seen_at=...` 后 `flush`,而 `get_db` 要等路由返回才 commit —— 这把 users 行的排他锁一直持有到 turn 结束。同一用户的第二个请求会阻塞在 auth 依赖里,**根本走不到 E2 的 turn 认领**,表现是「先卡住、等第一个 turn 跑完再返回 200」,而不是 409。修:把 users 的 upsert 挪进它自己的短事务(`get_session_factory()` 开 → upsert → 立刻 commit),与 E2 任务 4 是同一条纪律;contextvar 必须在该 session 第一次查询**之前**设好,`after_begin` 才会发 `set_config`。注意「`last_seen_at` 超过 N 分钟才写」只是缓解:写的那一次仍然持锁整个 turn,不能让 409 变确定。

**E1 — worker lease + requeue + 重试上限**
1. schema 三份同步:`tasks.lease_until TIMESTAMPTZ NULL`。`retry_count` **已存在**(`NOT NULL DEFAULT 0`,至今零写入,且已在 `TaskOut` 与前端 `Task` 类型里),不新增列——注意 reaper 是它的第一个写入者,`/tasks` 视图上会首次出现非 0 值,这是预期而非意外。
2. `claim_next_task` 在现有 `FOR UPDATE SKIP LOCKED` 之上 set `lease_until = now() + TASK_LEASE_SECONDS`,**用服务器时间**(多副本时钟不齐会既误抢又误放)。
3. **可重投集是白名单**(依据 ❶):
   - `company_readiness` / `market_data_sync` → 过期即回 `pending`,`retry_count + 1`;达 `TASK_MAX_RETRIES` → `failed`
   - `exposure_update` / `issuer_research` → **不重投**,task 直接 `failed`(`error_message` 写明 lease 过期),并把关联 run 一并标 `failed`
   - 理由:`app_rls` 无 DELETE 权限,半截 run 在应用层清不掉;把没跑完的 run 标红让用户显式重跑,比伪装成功或炸在第二次写入诚实。这条**同时解开** ❸ 的 research 永久 409 死锁。
4. reaper 落点在 `run_worker` 的 while 体(**不是 `process_one`** —— 它空队列时提前 return,忙队列时又无间隔空转),每轮一次,**分两段事务**(依据 ❷):
   - 第一段,无 tenant、可批量:`UPDATE tasks ... WHERE status='running' AND lease_until < now() RETURNING id, type, payload, owner_user_id, retry_count`
   - 第二段,逐条:先把 `current_user_ctx` 设成 `task.owner_user_id or user_demo_system`(必须在该 session 第一次查询**之前**,`after_begin` 监听器才会发 `set_config`),再开事务标 run failed
   - **必须分开**:一条 `exposure_runs` 的 RLS 错会中止整段事务,混在一起 = reaper 每轮全灭的自伤式永久停摆
   - run 的存在性要判:readiness 的 `run_id` 就是 task.id(无 run 行),`market_data_sync` 压根没有 run_id
5. compose:删 `container_name: exposure-worker` 解锁 `--scale`(实测 `--dry-run` 报的正是这条);**同时给 worker 加 `restart: unless-stopped`** —— 实测四个服务的 RestartPolicy 全是 `no`,单 worker 部署崩了没人拉起,而 reaper 就住在 worker 里,等于没有恢复。`WORKER_ID = socket.gethostname()` 在 compose 下是 12 位容器 ID,各副本天然不同,无需改代码。
6. 改写本文档末尾接缝备忘的「handler 已幂等」那条,换成本任务 3 的白名单事实。

**E2 — per-session 单飞行 turn(lease 版,替换原 BOOL 设计)**
1. schema 三份同步:`agent_sessions.turn_started_at TIMESTAMPTZ NULL`。
2. 认领:`UPDATE agent_sessions SET turn_started_at = now() WHERE id = :id AND (turn_started_at IS NULL OR turn_started_at < now() - make_interval(secs => :lease)) RETURNING id`,全程服务器时间。
3. **状态码顺序钉死**:401(`require_user`)→ 404(保留现有 `get_session` 预检)→ 认领 0 行 → 409 `{"error":"turn_in_flight"}`。**不写 403**:实测非 owner 的 UPDATE 与 SELECT 都返回 0 行(FOR ALL 策略),存在性本身不可见——这正是 §0.6 的「跨用户自动 404,零代码」。预检必须保留:去掉它,404 与 409 就并成一个不可分辨的 0 行。
4. **认领与释放各自一个独立短事务**(`get_session_factory()` 新开、立刻 commit),**绝不用请求作用域的 `db`**:
   - 用请求 `db` 认领而不提交 = **自死锁**:`get_db` 直到路由返回才 commit,行级排他锁横跨整个 turn;而 `reserve` 每次工具调用都从**另一条连接**对同一行做条件 UPDATE,会阻塞在这把锁上,而这把锁又在等 `handle_message` 完成。Postgres **不会**报死锁(一侧等的是应用逻辑),表现为请求永久挂起。
   - 用请求 `db` 释放 = 异常路径上白写:`get_db` 的 except 分支 `rollback()` 会把释放丢掉,而那正是 finally 存在的理由。
5. 释放放 `finally`,并接住这些逃逸路径:`chat_with_tools` 缺 key 抛 RuntimeError、OpenAI 网络异常直穿、`reserve` 的 `ValueError("unknown session")` **不在** `invoke` 的捕获范围内(它只捕 `BudgetExceeded`)。
6. `TURN_LEASE_SECONDS=900` 的取值理由:**宁可让死的 turn 多卡一会儿,也不能让活的 turn 被抢**(`max_turns=16` 轮 LLM 的合法长 turn 必须安全);进程崩了最坏卡该 session 15 分钟后自愈。
7. 前端:ChatPanel 已用 `busy` 挡住同标签页双击(输入框与按钮都 disabled),所以 409 的现实来源有两个:**过期 lease**(上一个 turn 崩了留下的),以及**第二个标签页/设备**(`localStorage` 的 `ew_agent_session` 跨标签页共享)——后者**以 E0-3 落地为前提**,否则第二个请求会先卡在 auth 的行锁上。409 到达时**撤回乐观追加的用户气泡**:服务端此时没有落 user message,不撤就与库不一致,下次刷新会凭空消失。

**E3 — 日配额(usage_daily + 五池)**
1. schema 三份同步 + **两条额外义务**(V2-D 踩过):`usage_daily` 建在 `GRANT ... ON ALL TABLES` 之后 → 必须补 `GRANT SELECT, INSERT, UPDATE ON usage_daily TO app_rls;`;归属写进 §0.6。
   表:`usage_daily(user_id TEXT NOT NULL, day DATE NOT NULL, kind TEXT NOT NULL, used INT NOT NULL DEFAULT 0, PRIMARY KEY (user_id, day, kind))`,**共享层,不加 RLS**(同 `tasks`)。理由:全局兜底池必须跨租户计数,任何 `user_id = current_setting(...)` 的策略都会让它只数到调用者自己 = **fail-open 的假兜底**;放共享层后,全局池就是同表的保留行 `user_id = '_global'`,一个原语覆盖两级。读路由按 user 过滤须带 `# semantic, not security` 注释(与 `apps/api/routes/tasks.py:43` 同款)。
2. 唯一原语 `services/usage_service.charge(db, user_id, kind, limit)`,形状照抄 `agent_session_service.reserve`:
   ```sql
   INSERT INTO usage_daily (user_id, day, kind, used) VALUES (:u, :d, :k, 1)
   ON CONFLICT (user_id, day, kind) DO UPDATE SET used = usage_daily.used + 1
   WHERE usage_daily.used < :limit
   RETURNING used
   ```
   0 行 → 抛 `QuotaExceeded(kind, scope, used, limit, resets_at)` 且不改状态。`day` 用已有的 `utils/dates.today_utc()`。`user_id` 为 None → **抛错,不静默放行**。
3. 每个动作扣两次:先 user 池、再全局池,**同一事务**;任一超限 → 抛错 → 回滚 → 两个计数都没动(因此**不需要任何退款/补偿逻辑**)。
4. 扣费点(V2-E 落成两个;V2-H 追加三个,见 §0.5 表):
   - `task_service.create_task`:`{exposure_update: exposure_run, issuer_research: research_run, company_readiness: readiness, market_data_sync: market_sync}`,**无默认值** —— 将来新增 task type 忘配额 = KeyError fail loud。这一个点同时盖住 REST 路由(4 处)与 meta-agent 委派工具(3 处)**两条面**;它们是平行实现、不共享代码,分开写必漏一条。`owner_user_id is None`(系统路径)→ 不扣;worker 侧零处调用 `create_task`,不存在「扣到 demo 哨兵头上」的路径。
   - `POST /agent/sessions/{id}/messages`:扣 `chat_turn`。**chat_turn 不可改扣在 session 创建上** —— 一个 session 能发无限条消息,且 `issuer_research` 会另建一个 `kind='research'` 的 session(每个 research run 都会白扣一次 chat)。
   - ★ V2-H 追加(此条原文写「扣费点只有两个」,现更正):上一句否定的是「把 chat_turn 的扣费点搬到 session 创建」,**不是**「session 创建不该有自己的池」。`POST /api/agent/sessions` 此前无配额也无上限,登录后一个循环即可无限建行;现按 `agent_session` 单独计一池(5/天),**扣在路由层**——扣进 `agent_session_service.create_session` 会打到 MCP server 的无 owner session(`usage_service.charge` 对 None 抛错)并让 `issuer_research_workflow` 在已于 enqueue 扣过之后再扣一次。附:`agent_sessions.ended_at` 全仓从未被写入,所以「同时开着 N 个」这类上限今天实现不了(会把用户永久锁死),日配额是唯一可行形状。
5. chat 扣费与 E2 的 turn 认领**放同一个短事务**并一起 commit(在 LLM 循环开始之前):超配额 → 回滚 → lease 一并释放,「拒绝路径手工释放」这个特例因此消失。循环开始之后失败**不退款**(LLM 已经花掉了),此语义明确写进 `docs/PRODUCTION.md`。
6. 委派工具侧必须**自己**接住 `QuotaExceeded` 并转成结构化 dict(house style,同 `company_not_found` / `active_run_exists`):`registry.invoke` 的兜底 `except Exception` 会把任何异常压成 `{"error":"tool_error","detail":str(exc)}`,`kind/used/limit/resets_at` 全丢。
7. 顺带修一个既有缺陷:research 两条路径都是先 `create_task` 再 `create_run`,`ActiveRunExists` 在后面抛 → agent 路径已 commit 出一个无 `run_id` 的**孤儿 task**(worker 捡起来必失败)。改成**先 `get_active_run` 预检、再 `create_task`**,让 `create_task` 成为最后一步,配额才不会被一个注定失败的请求吃掉。
8. **已知豁口,明确接受不补**:`issuer_research` 在数据未就绪时会在 worker 内联调 `run_readiness()`(无 task、无路由、无扣费),所以 research 配额隐含吃掉同一条摄取管线。research 池(3/天)本就是更紧的约束,不再叠一层。

**E4 — 配额可见面**
1. `GET /api/me/usage`(`require_user`,落在既有 `apps/api/routes/me.py`,`/api` 前缀已挂,`main.py` 不用动):返回 `{day, resets_at, pools:[{kind, used, limit, remaining}]}`。**直查 `usage_daily`,禁止建视图** —— E0-2 刚修掉的越权就是视图默认绕过 RLS 造成的,再造一个 `user_cost_today` 等于把洞重开一次。(原计划任务 5 的 `user_cost_today` 视图**作废**。)
2. ChatPanel 头部加配额徽章(`Analyst` 与 `[New]` 之间);turn 结束后刷新,**必须带 ignore 闭包守卫**(`page.tsx:707`/`724`、`PortfolioModal.tsx:48` 三处同款先例),未登录不发请求,失败落 null 不抛(`apiFetch` 对 401 也会 throw,且 `Auth.tsx` 注册 token getter 无 `isLoaded` 门,首帧可能匿名发出)。
3. 失败展示**分两类规则,不要一刀切**:`quota_exceeded` **原文透传**(§0.1「UI 不美化失败」——用户要看的是账);`turn_in_flight` 换成一句人话(并发信号,不是账)。解析复用 `PortfolioModal.tsx:12-23` 的 `extractProblems` 同款做法(从 `Error.message` 里切 JSON),不要发明第二套。

**E5 — 价格新鲜度(消灭 $0 静默估值,依据 ❹)**
1. 新增 step 0 `sync_prices`,**放在 workflow 里而不是 handler 里**(handler 不写 `workflow_events`,放 workflow 才会出现在 UI 时间线上):对本组合持仓 ticker 调 `market_data_ingestion_service.ingest_market_prices`,**窗口用 run 自己的 `[as_of - 90d, as_of]`,不是 `date.today()`** —— `POST /exposure-runs` 接受任意 `as_of`,用 today 会去同步一段工作流根本不查的区间,等于没修。实测成本:冷启 1.52s + 0.07~0.09s/ticker,10 只 ≈ 2.4s 冷 / 1s 热,内联可接受。
   - **持仓取法必须与 `_load_inputs` 一致**:先 `get_positions(db, portfolio_id, as_of_date)`,空则 `get_positions_latest(db, portfolio_id)`。`get_positions` 对 `as_of_date` 是**精确等值**过滤,而按 §0.5 快照语义持仓日期 = `max(price_date)`、run 的 `as_of` 默认是 `date.today()`,两者**正常情况下就不相等**(实测活库:port_001 持仓 as_of `2026-07-23`,最近三个 run as_of `2026-07-24` → 精确取法返回 0 行)。只写 `get_positions(as_of)` 会拿到空 ticker 列表,step 0 变成**永远绿的空转**。实现上在 step 0 加载一次并传给 step 1 复用(`_load_inputs` 增加 `positions` 入参),保证两步 ticker 集合同源且只读一次库。
   - `ingest_market_prices` 默认 `commit=True` 且**遇第一个零 bar 的 ticker 就抛**(用户只看得到第一个坏 ticker)。本步改为记录不可得的 ticker 并继续,把「哪些票没价」的判决**统一交给 step 2**(单一判定点)。
   - 坑:`_StepContext.__aexit__` 无条件 `log_event` + `commit`,而本步是**第一个在自己失败点之前就做 DML 的 step**,DB 异常会被 `PendingRollbackError` 掩盖成假死因。步内 DML 必须自己接住、回滚干净再抛。
2. `_validate_inputs` 升级为**唯一 fail-loud 判定点**:窗口内无任何价格行的 ticker、以及最新价距 `as_of` 超过 `PRICE_STALENESS_DAYS` 的 ticker,**列出全部名单**(不是第一个)后抛错,run 显式变红。
3. **拆掉两处静默兜底**:`calc_exposure` 的 `fillna(0.0)` 与 `calc_pnl` 的 `row.get("price")` 回退。到这一步价格已由 step 2 保证齐全,继续保留只会掩盖将来的新缺口。
4. 步数 10 → 11,同步六处「10 步」写法:本文档 §0.4 红线 2(:55)、:146、:207,`IMPLEMENTATION_PLAN.md` :44/:104/:283(计划里写的 :142/:203 已漂移,实际在 :146/:207);并修 `docs/WORKFLOW_CONTRACT.md` 表的两个既有错误(第 2 行早就宣称检查 stale data 而代码从没做过;表里 `persist_outputs`/`generate_report` 顺序与代码相反)。前端不受影响(时间线由返回事件动态推导,无硬编码步数)。
5. 补测试:`calc_exposure`/`calc_pnl`/`ExposureWorkflow` 目前零覆盖。写纯离线单测(无 DB 无网络):两只票的 `positions_df` + 只含一只的 `prices_df` → 断言**抛错**,而不是 `portfolio_market_value == 幸存者市值`。

**验收**:
- [ ] 离线:reaper 三分支(白名单类型回 pending / 非幂等类型直接 failed / `retry_count` 达上限 failed);`charge` 三分支(未超、恰好用尽、并发抢最后一个单位得 0 行)+ 映射表无默认值(未知 task_type 抛错);turn lease 的认领/过期认领/409;`_validate_inputs` 缺价与过期两类各自抛错且列出**全部** ticker 名单
- [ ] live:`--scale exposure-worker=2` 连发 5 个 run,每个 task 恰好一个 worker 完成(`worker_id` 互不重复、无重复 metrics 行)
- [ ] live:`TASK_LEASE_SECONDS` 临调 30s,跑 readiness 途中 `docker kill` 持有 worker → 另一 worker 接手完成且 `retry_count=1`(**这是 P6 stuck-run 事故的正式解**);同样手法对 `issuer_research` → task 与 run 双双 failed 且 `error_message` 写明 lease 过期,该用户对该 ticker **能立刻重新发起**(证明 ❸ 的死锁解除)
- [ ] live:`DAILY_CHAT_TURNS` 临调 2 → 第 3 条消息 429 且 body 原文出现在聊天面板,`usage_daily` 中 `(user, day, chat_turn)` = 2 且 `_global` 行同步 = 2;`DAILY_RESEARCH_RUNS` 临调 1 → 第 2 次 research 走 REST 得 429、走 agent 委派得**结构化 `quota_exceeded`(不是 `tool_error`)**
- [ ] live:两个标签页同时发消息 → 第二个**立刻** 409(**卡住再返回 200 = 不通过**,那是 E0-3 未落地的症状);另用 `TURN_LEASE_SECONDS` 临调 30s + 杀 API 容器,验过期 lease 自愈后同一 session 可继续发言
- [ ] live(E0):以真实用户跑通一次 `company_readiness`,事件落库、task completed —— **这是该 task type 第一次成功**
- [ ] live(E5 缺价 → 红):以 owner 身份直接向 demo 组合最新快照 INSERT 一条 yfinance 取不到 bar 的持仓(合成/已退市符号,如 `ZZTEST`;**必须走 owner DML** —— V2-D 的上传通道会先用 `ticker_not_in_universe` / `no_price_data` 挡住它)→ step 0 记录该 ticker 不可得并继续 → step `validate_inputs` 抛错、run 红且 `error_message` 只点名它;删掉该持仓行后重跑 → 绿
- [ ] live(E5 过期 → 红):`POST /exposure-runs` 传一个超出最新可得 bar 且距其 > `PRICE_STALENESS_DAYS` 的未来 `as_of`(如 today+30d)→ run 红且 `error_message` **列出全部** ticker 名单(证明「列全部而不是第一个」)
- [ ] live(E5 step 0 回填 → 绿):以 owner 角色删掉 demo 组合某只票近 90 天价格 → **不手工恢复,直接重跑** → 时间线出现 `sync_prices` 事件(message 带同步 ticker 数,须 = 持仓只数且非 0)、该 ticker 在 `[as_of-90d, as_of]` 的行数复原(实测 AAPL = 62 行)、run 绿、MV = Σ qty×close 与持仓一致
  > ⚠ 这三条**不可合并**:step 0 会在 step 2 之前把删掉的价格从 yfinance 原样抓回来,所以「删价格」只能证明 step 0 生效,**永远产不出红 run**;红分支必须用 step 0 修不好的东西(provider 无 bar / 未来 as_of)触发。
- [ ] 回归红线三条(红线 2 的「10 步」自本阶段起读作「11 步」,六处写法已同步)

**禁止**:Redis/Celery/任何队列中间件;**任何形式的心跳/续租线程**(两把 lease 都靠「取值够宽 + 到期自愈」);为 429 新增本仓第一个 exception handler;把配额算成 token 或工具调用数;退款/补偿逻辑;给 `app_rls` 授 DELETE;新建任何未设 `security_invoker` 的视图。

**用户检查点**:五个池的默认值(10/3/10/20/10)在公开链接前定稿;**E5 是行为变更** —— 过期持仓从「静默估 \$0 照常出报告」变成「显式红 run」,用户需确认接受(这正是 V2-D review 留下的遗留项的正式解)。

---

## V2-F — 部署 + PRODUCTION.md(1d)

**范围**:同源化、Caddy 子域、生产 Clerk、文档。

**任务**:
1. 同源化:`lib/api.ts` 的 base 改为 `process.env.NEXT_PUBLIC_API_URL ?? ""`(空 = 相对路径 `/api/...`);compose 本地开发仍显式传 `http://localhost:8103`(行为不变),生产 build 传空
2. `infra/Caddyfile.example`:`exposure.<domain>` 站点——`handle /api/*` → 反代 `127.0.0.1:8103`,其余 → `127.0.0.1:3103`;启用压缩与访问日志
3. CORS 收紧:FastAPI allow_origins 改 env 列表(生产同源后仅留本地开发口)
4. Clerk 生产:AUTHORIZED_PARTIES 加 `https://exposure.<domain>`;文档记录生产实例切换步骤
5. `docs/PRODUCTION.md` 五节:身份 / 租户隔离 / 并发 / 预算 / 审计——每节固定三段式「强制点在哪 · 消灭了哪类错误 · 如何验证」;README Quick Start 增登录与多用户段
6. 部署脚本化:`scripts/deploy_notes.md` 或 Makefile target(build → up → migration 应用 → 冒烟 curl 清单)

**验收**:
- [ ] 外网(手机/另一台机器)匿名浏览 demo → 注册登录 → clone demo → 上传自己组合 → run → chat 全链路成功
- [ ] 生产页面源码 grep 无 `localhost:8103`
- [ ] 匿名写路径 401、跨用户 404 在公网复测一遍
- [ ] 回归红线三条(本地 compose 行为不变)

**用户检查点**:域名/DNS/Clerk 生产实例;**是否公开链接由用户拍板**——公开前 E 的预算必须已验证。

---

## V2-G — 终验与文档收口(0.5d)

**任务与验收(合一)**:
- [ ] grep 审计:全部写路由 require_user 覆盖清单;service 层无未标注 semantic 的 owner 过滤;providers import 单向;RLS 表清单与 0.6 逐一对齐(脚本断言)
- [ ] `tests/test_tenancy_live.py`:C 的双用户隔离全套固化为可重放脚本
- [ ] `docs/spikes/V2_COVERAGE.md`:终验数字(用户数/组合数/RLS 表数/lease 接管演示/预算命中记录),体例仿 P9_COVERAGE
- [ ] MODULE_NOTES M14 状态更新 + dev_note 活页 + BOARD(用户 wrapup 流程)
- [ ] 全量:`pytest -m "not live"` ≥ 基线 + 新增;`pytest -m live` 全绿(需 keys+DB)

---

## 附:与既有系统的接缝备忘(执行时勿反复求证)

- `_session_ctx`(tools/registry.py)与本计划的 `current_user_ctx` 是**两个平行 contextvar**:前者管 calc 台账 invoked_by,后者管租户;不要合并。
- evidence 前缀三清单(registry `_ID_PREFIXES` / trail `_RESOLVERS` / resolver `_RESOLVERS`)已含 `run_`/`alert_` 且有 parity 测试(tests/test_portfolio_snapshot.py)——新表不引入新引用前缀,无需动。
- 上一轮已修:alert id 统一 `alert_` 前缀(exposure_workflow 用 `new_alert_id()`);listRuns 返回 `ExposureRunSummary`(前端类型区分列表/详情)——V2 改动 page.tsx 时保持该区分。
- ~~worker 的 exposure/readiness/research handler 已幂等(upsert/append-only),lease 重投安全性依赖于此~~ —— **此条已被 V2-E 前置认定 ❶ 实测推翻**。真实情况:仅 `company_readiness` / `market_data_sync` 幂等可重投;`exposure_update`(裸 INSERT 打 5 个 `UNIQUE(run_id…)`)与 `issuer_research`(`issuer_briefs UNIQUE(research_run_id)`,且模块 docstring 自陈 "deliberately NOT idempotent")**不可重投**,lease 过期一律标 failed。新 handler 必须在这两类里明确站队,并写进本备忘。
  - **E1 落地后,这条分类不再靠文档记忆**:白名单是 `task_service.REQUEUEABLE_TYPES`,「失败后要不要顺带标 run」是 `worker._RUN_FAILERS`,两者由 `tests/test_task_lease.py` 守——新增 task type 若两边都不写,`test_every_dispatchable_type_has_a_lease_expiry_policy` 直接红。
  - **实现期又查出两处计划未列的非幂等写入(都在 issuer_research 内,不改结论只补账)**:①`evidence_packs` 无任何唯一键(`models.py` 无 `__table_args__`),重投静默重复 pack;②phase 2 每次都 `sess.create_session` 新建一行 `agent_sessions`,重投会把上一轮的 session 变成孤儿。这两条进一步确认 `issuer_research` 只能 fail、不能 requeue。
  - **readiness 的「幂等」有一处代价**:`standard_recipe` 走 `calc_service` 的 `db.add(CalcLedger(...))`,`calc_ledger` 无唯一键、按设计 append-only,所以重投不报错但会多出台账行。可接受(台账本就是 append-only 的审计流水),但 requeue 不是零成本,`TASK_MAX_RETRIES` 的存在理由之一即此。
- **RLS 表上的 ORM 写入一律是 `INSERT … RETURNING`**(`flush()` 要回填 SERIAL 主键 / server_default),而 Postgres 对 `INSERT … RETURNING` 会把 SELECT 策略(USING)也套在新行上 —— 所以带 RLS 的表**USING 与 WITH CHECK 必须同时覆盖写入行**,只补一边会得到一条读起来像 WITH CHECK 失败的错。E1/E3 的 `RETURNING` 之所以无碍,只因 `tasks` / `usage_daily` 在共享层无 RLS。
- ~~**`check_limits(db_limits=...)` 是死参数**~~(E5 实现期发现,**V2-H4 已关闭**——见 MODULE_NOTES §M16):`analytics/limits.py` 声明并在 docstring 里提了它,函数体里**一次都没用**;而 `_load_inputs` 每次 run 都专门查一次库把它建出来,`portfolio_service._copy_risk_limits` 还会把 demo 的限额模板拷进每个新建组合。实际生效的**只有** `configs/risk_limits.yaml` 的全局默认值。后果有二:①用户组合的自定义限额目前完全无效;②任何断言「因为该组合的 DB 限额而触发告警」的测试必然失败。修它不属于 E5 范围,但**在公开链接前应决定**:要么接上,要么把这条路径连同拷贝逻辑一起删掉——留着一个假装可配置的界面比没有更糟。
- 两个 step 是**非致命**的:`compare_previous_run`(吞异常且不进 `steps_completed`)与 `generate_report`(失败只记 warning、`report_id=None`)。所以「11 步全绿」不能当字面断言用——一个成功的 run 时间线上可以出现红步骤,`steps_completed` 也可以只有 9 或 10 项。
- 任何 lease 重投都会**重复整条 `workflow_events` 时间线**(该表无唯一键,`step_context` 每步进出各写 1 行)。UI 按 `step_name` 去重(后写覆盖先写)故观感无碍,但读取原始事件做统计时须知。
