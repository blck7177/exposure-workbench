# Implementation Plan V2 — 多用户 Portfolio 工作台 + 生产化

> **版本**:2026-07-24
> **读者**:执行实现的 agent(假定没有架构讨论的对话上下文,本文档自足)
> **前置阅读(必读,按序)**:
> 1. [TARGET_ARCHITECTURE.md](TARGET_ARCHITECTURE.md) v3 —— 系统不变量,**任何实现与它冲突时以它为准并停下来问用户**
> 2. [MODULE_NOTES.md](MODULE_NOTES.md) M14 —— 本轮设计定稿(数据三层归属、RLS、universe 表、匿名边界)
> 3. [IMPLEMENTATION_PLAN.md](IMPLEMENTATION_PLAN.md) —— 已完成的 P0-P9 基线(体例与纪律沿用)
> 4. [spikes/P9_COVERAGE.md](spikes/P9_COVERAGE.md) —— 现状基线数字(83 offline 测试、8 issuer、demo 组合 port_001)

**本计划交付**:用户注册/登录(Clerk)→ 创建/上传/克隆自己的 portfolio → 公司层数据共享、chat/组合/分析按用户隔离(Postgres RLS)→ 全美股 ticker 宇宙搜索(U2)→ per-user 预算 + worker 崩溃恢复 → 公网部署。

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
- 明确不做(全计划):组织/团队、用户间共享、组合原地编辑、删除流(最多 `is_active=false`)、agent 写组合的工具(编辑只走 UI)、非美市场、alembic、WebSocket

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
  2. demo 组合 exposure run 10 步全绿(C 起:以 `user_demo_system` 上下文或测试 token 触发)
  3. 匿名 GET `/`、`/issuer/NVDA`、demo latest-brief 全部 200;(C 起追加)匿名 POST 任何写路径 = 401

### 0.5 钉死的实现常量

| 项 | 值 |
|---|---|
| `users.id` | Clerk user id 原文(TEXT PK);系统哨兵 `user_demo_system` |
| PG 会话变量 | `app.user_id`,事务内 `SET LOCAL`;政策读 `current_setting('app.user_id', true)`(missing→NULL→fail-closed) |
| DB 角色 | `exposure` = owner,仅 DDL/migration/seed;**`app_rls`** = api+worker 运行时(LOGIN,GRANT SELECT/INSERT/UPDATE,**无 DELETE**;非 owner 故 RLS 天然生效) |
| 新 env | `DATABASE_URL_APP`(app_rls 连接串)、`APP_DB_PASSWORD`、`NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY`、`CLERK_ISSUER`、`CLERK_AUTHORIZED_PARTIES` |
| 预算(settings,env 可覆盖) | `USER_DAILY_TOOL_CALLS=300` `USER_DAILY_RESEARCH_RUNS=3` `USER_DAILY_EXPOSURE_RUNS=20` `GLOBAL_DAILY_TOOL_CALLS=3000` `TASK_LEASE_SECONDS=1800` |
| CSV 规格 | 列 `ticker,quantity[,cost_basis]`;首行含 "ticker" 视为表头;≤200 行;quantity>0;**整单原子**——任一行错则零写入,返回 `problems:[{row,ticker,reason}]` |
| 新组合默认 | currency=USD,benchmark=SPY,risk_limits = 拷贝 demo(port_001)的限额模板 |
| 快照语义 | 每次上传 as_of_date = `SELECT max(price_date) FROM market_prices`;price=该日 close;market_value=quantity×close |
| universe 源(D) | `https://www.nasdaqtrader.com/dynamic/SymDir/nasdaqlisted.txt` + `.../otherlisted.txt`(\|分隔,剔 `Test Issue=Y` 与尾行)+ `https://www.sec.gov/files/company_tickers.json`(UA=EDGAR_IDENTITY)。实测 ~13k 行 / SEC 10,429 家 |
| 符号映射 | yfinance 侧 `'.'→'-'`(BRK.A→BRK-A),**只在 market-data provider 调用点转换**;库内存上市文件原文 |
| 搜索排序 | ticker 精确 > ticker 前缀 > name ILIKE 子串;limit 10;**typeahead 点击确认,永不自动选** |
| 错误码 | `unauthenticated` `turn_in_flight` `user_budget_exceeded` `ticker_not_supported`(U1) `ticker_not_in_universe`(U2) `no_price_data` `invalid_csv` |
| 验收主角 | 双账号 **A/B**(Clerk 免费两邮箱)+ 匿名 + demo |

### 0.6 数据归属总表(政策的唯一依据)

| 层 | 表 | RLS |
|---|---|---|
| **共享(公司层)** | companies, filings, filing_documents, filing_sections, filing_chunks, financial_facts, research_sources, **calc_ledger**, market_prices, factor_*, security_master, tasks(系统队列,带 `owner_user_id` 供 worker 设上下文) | 无 |
| **用户主表** | users(本人可见)、portfolios(`owner OR is_public`)、agent_sessions(owner)、research_runs(owner)、issuer_briefs(`owner OR is_public`) | 有,owner 列在此五表 |
| **子表(EXISTS 级联,不加 owner 列)** | positions/risk_limits/schedules → portfolios;exposure_runs → portfolios;metrics/sector_exposures/issuer_exposures/factor_attributions/risk_alerts/daily_reports/workflow_events → exposure_runs;agent_messages/agent_steps/evidence_packs → agent_sessions | 有,`EXISTS(父表)`(父表政策自动级联) |

推论(实现时反复自查):demo 组合 `is_public=true` → 其 runs/alerts/reports 对所有人可见(公共沙盘,诚实);用户组合的一切只有本人可见;`/api/evidence/{run_/alert_}` 跨用户自动 404,零代码。

### 0.7 阶段依赖图

```
A(身份) ─▶ B(组合 U1) ─▶ C(RLS) ─▶ D(Universe U2) ─▶ E(并发+预算) ─▶ F(部署) ─▶ G(终验)
串行执行。D 仅逻辑依赖 B,但与 C 改同一批上传文件,不并行。总预估 ~7 agent 工作日。
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
- [ ] live:登录 → CSV `AAPL,10 / MSFT,5 / TLT,20` → 组合出现,positions 按最新收盘定价;对它 Run Daily Update → 10 步全绿,MV=Σqty×close 非零;重传新 CSV → 新 as_of 快照,旧行仍在;`PLTR,10`(无价格数据)→ 422 指名该行,库零变更
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
- [ ] live:refresh 后 `security_master` >10,000 行且 AAPL/TLT/BRK.A 在;二次 refresh 幂等;search "apple" → AAPL 首位且能看到 APLE 等干扰项(点选消歧的活证据);上传 `RBLX,5` → 自动回填 >200 行价格、组合 run 10 步全绿含 RBLX;`BRK.B,1` → 符号映射生效、定价成功;`ZZZZZZ,1` → `ticker_not_in_universe` 整单拒
- [ ] 回归红线三条

**禁止**:自动触发 readiness/EDGAR 摄取(issuer 研究仍限 `is_investigable` 集,显式按钮);非美证券;pg_trgm(先 ILIKE,不够再说)。

---

## V2-E — 并发硬化 + 预算(1d)

**范围**:worker lease/requeue、per-session 单飞行 turn、per-user 与全局日预算。

**任务**:
1. lease:`tasks.lease_until TIMESTAMPTZ NULL`;`claim_next_task` 在 SKIP LOCKED 基础上 set `lease_until = now() + TASK_LEASE_SECONDS`;轮询循环每轮顺带 `UPDATE tasks SET status='pending', worker_id=NULL, lease_until=NULL WHERE status='running' AND lease_until < now()`(回收即重投,幂等步骤保证 at-least-once 安全)
2. 横扩解锁:compose 去掉 worker 的 `container_name`(允许 `--scale`)
3. 单飞行 turn:`agent_sessions.active_turn BOOL DEFAULT false`;POST messages 入口 `UPDATE ... SET active_turn=true WHERE id=:id AND active_turn=false RETURNING id`,无行 → 409 `{"error":"turn_in_flight"}`;finally 复位(异常也复位)
4. 预算:settings 四常量(0.5);`agent_session_service.reserve` 扩两级检查——owner 当日 agent_steps 计数 ≥ USER_DAILY_TOOL_CALLS → `BudgetExceeded(kind='user_daily')`;全局当日 ≥ GLOBAL_DAILY_TOOL_CALLS → `kind='global_daily'`;research/exposure 触发路由前置当日次数检查(USER_DAILY_RESEARCH_RUNS / USER_DAILY_EXPOSURE_RUNS);错误体 `{"error":"user_budget_exceeded", kind, used, limit}`
5. 视图:`user_cost_today`(session_cost 加 owner 维);ChatPanel 对预算错误 verbatim 展示(UI 不美化失败)

**验收**:
- [ ] 离线:reserve 的 user_daily/global 分支(fixture steps);单飞行 turn 的 409 分支与 finally 复位
- [ ] live:`--scale exposure-worker=2` 起双 worker,连发 5 个 run 无重复处理(task 各被恰好一个 worker 完成);跑长任务途中 `docker kill` 持有 worker,lease(临时调短至 30s)过期后另一 worker 接手完成——**这是 P6 stuck-run 事故的正式解**;USER_DAILY_TOOL_CALLS 临时设 3,chat 第 4 次工具调用得到 user_budget_exceeded 且 trace 记 rejected;双击发消息 → 第二个 409
- [ ] 回归红线三条

**禁止**:Redis/Celery/任何队列中间件;心跳线程(lease 粗粒度足够 MVP)。

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
- worker 的 exposure/readiness/research handler 已幂等(upsert/append-only),lease 重投安全性依赖于此,新 handler 必须保持。
