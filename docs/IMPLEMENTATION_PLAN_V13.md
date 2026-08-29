# Implementation Plan V13 — 上线前 UI 收口:读者层 / 审计层 / 可视化

> **状态(2026-08-29)**:执行中。**S0 ✅** 共享面 + Next 16 笔记 · **S1 ✅** 数据卫生(脚本只跑 dry-run,删/改标签待拍板)· **S2 ✅** 错误面 · **S3a ✅** 证据标签 + 显示名表(**1138 offline** / tsc 绿,基线 1082)· S3b(`meta.verified`)· S4–S8 待做。
> **⚠️ 提交卫生事故**:`58e8e98`(S1)用了 `git add -A`,把**另一个 session 的 6 个文件**卷了进去(`meta_agent.py`、`formula_service.py`、`typed_calculator.py`、`tools/definitions.py`、`test_balance_delta.py`、`test_absence_derived_input.py`——三处不相关的修复)。对方已提醒并要求先不改写、不推送,由 boss 决定怎么拆。我此后全部按路径暂存;`17aa6b8`(S0)与其后各提交经核实只含本批文件。讽刺的是本计划 §7 风险表第一行写的就是"本机有并行 session 在同一工作树"。
> **已对活库做的唯一改动**:`v13_run_errors.sql`(加列、幂等、跑两遍验证)。运行中的四个容器构建自不含这些列的镜像,站点全程 200。**§9 九项待拍板**——执行按 §1 的"建议"默认值走,凡涉及**删数据、改线上、改 LLM 措辞**的三类一律停在拍板前(S1 的删除脚本只跑 `--dry-run`;S7 的 `_SYSTEM` 与日报 prompt 不改;S8 不部署)。
> **执行期偏离(如实记)**:①S0 的"组件目录拆分"并入 S6。②**S2 的 `error_detail` 不上 API**——计划 §S0 写的"字段本身不做权限分支,RLS 决定可见性"是错的:demo 是**公开**组合,它的 run 任何匿名访客都读得到,把供应商原文与内网主机名放在 payload 上等于把本批要堵的洞挪到 JSON 里。改为**根本不服务该字段**(库里写给运维,psql 读),连权限分支都不需要;`WorkflowEventOut` 另加一个 scrubber 把 `payload_summary` 里的 detail 也剥掉。③S1 的删除脚本长出 `--relabel`:dry-run 发现最完整的那个 demo run 恰恰带开发标签,按标签删会把橱窗退回 7 月。④新增一个计划里没有的 code `brief_not_submitted`——research agent 用完预算未提交 brief 不是缺陷,和"run 停了"共用一句话是把两件事说成一件。理由:拆分的原因是 V7 的并行 lane 撞车,而本次是单人顺序执行;先做一次纯搬运提交、再在 S6 原地重写,是两遍改同一批文件。S0 只做真正的共享面(schemas / types / errors 词表)与 Next 16 笔记。**上游**:`dev_note/portfolio-demo/ui-review/`(README §1–§5:25 条暴露项 + 27 产品 / 50 模式研究 + 可视化盘点;报告 artifact `11c69b1e…`;目标 UI mockup v2 artifact `e8ee7ba5…`,`target-ui-mockup.html` + `viz-build/` 取数脚本可对活库重跑)。
> **性质**:**呈现层 + 数据卫生 + 只读端点**。四公理、门、工具语义、预算一律不动;LLM 路径只改**措辞**(全部过目后才提交,§7)。与 8/27「先收敛不加功能」的关系:P0/P1 全部是把**已经算出来、已经存在库里**的东西给读者看;本批唯一的"新东西"是 9 个只读端点和 3 列持久化,没有新的分析能力。
> **一句话**:这个产品按实质站在信任阶梯顶端(每个数字有 fact/calc、期间、申报号、上游图、公式出处),按呈现站在底端(`calc 2b5395` chip、JSON dump、模型版本与原始错误串在读者眼前)。本批把两者对齐,并把差异化(数值门、账本、覆盖度诚实)做成看得见的。
> **判据先写在前面**:线上任一页面的读者层 DOM **零个** `(fact|calc|chunk|src|run|alert|pos|rrun|task|sess)_[0-9a-f]{12}`;任一失败面**零个**传输串 / 供应商原文 / 内网主机名;每张图的每个点能点回一个 id。三条都用 headless Chromium 的 `--dump-dom` 机械验收(S8)。

---

## 0. 诊断:实质与呈现分处阶梯两端

活库实核(2026-08-29,全部数字来自 `exposure-postgres` 与匿名 API,不来自计划文档):

| 面 | 暴露了什么 | 位置 |
|---|---|---|
| chat · brief | 234 条 assistant 回答 **131 条**内嵌 `calc_1a9ea43170dc` 类原始 id;brief 每段结尾 `[fact_…, calc_…]` 原样渲染;`CitedText` 是死代码 | `apps/web/app/issuer/[ticker]/page.tsx:346-350`、`components/Evidence.tsx:152` |
| 错误面 | 打错 ticker → 红条 `API 404: {"detail":{"error":"unknown_ticker"…}}`;研究 run 时间线直出 `ERROR: Error code: 429 - {'error': {'message': 'You exceeded your current quota…`、`http://exposure-mcp:8000/mcp/research could not be reached` | `issuer page:74`、`page.tsx:996`、`PortfolioModal.tsx:84` 用 `e.message`;`workflow/step_context.py:81` 拼 `— ERROR: {exc_val}`;`apps/worker/handlers/issuer_research.py:40` 存 `str(exc)` |
| 管道信息 | `Model: gpt-5.4-mini-2026-03-17`、`⚠ Mock mode — configure OPENAI_API_KEY`、`Run ID` + `Triggered: v8-p-live-acceptance`(demo 20 个 run 里 5 个测试触发、2 个 failed 含测试 ticker `ZZTESTX`)、trace 里模型版本 + token + 原始工具名 + `rejected`、证据抽屉 dump `mapping_version / primitive_version / invoked_by / task_id / char_span`、日报首行 `Portfolio: port_001` | `page.tsx:556-590`、`ChatPanel.tsx:35-71`、`Evidence.tsx:98-130`、`agents/direct_llm_agent.py::_build_user_message` |
| 口径 | 全仓 0 条免责;日报 `Recommended Actions` 写「Consider trimming LLY」而 `_SYSTEM` 规定「Do not give a verdict」 | `prompts/daily_exposure_report.md`、`agents/meta_agent.py:35` |
| 可视化 | 首屏无图;告警行 `13.8% vs limit 12.0%` 旁「76% of limit」(utilization 对 breach 档,句子写 warning 档);覆盖度 5 行 `energy shock holds GLD, HYG, ^VIX flat` 在首屏 | `page.tsx:743-755`、`:298-341` |

**mockup v2 已证明**:14 个面板全部能从活库画出(825 日价值/回撤、27 条限额、8×8 因子相关、AAPL 5 个申报窗口 / 3 个余额日 / 6 个被引段落),且构建过程抓到两处数字错误——我自己上一版 mockup 把市场因子 −0.99% 当成全部因子解释(真实 −0.72% / 个股 −0.57%),真实 brief 把 6 个月 OCF 写成"季度"(ROUND3 类 D)。这正是数值门要拦的错误类别;**图和数字同源**是本批的硬约束,不是美学偏好。

---

## 1. 决策(已定 = 建议按默认;待拍板见 §9)

| # | 决策 | 依据 |
|---|---|---|
| D1 | **两层披露**:读者层默认;审计层(id、模型、token、工具名、任务号、运维 detail)由登录用户在自己的数据上用「Audit」开关打开。**库里一字不删** | FINRA 2026 要求留存 prompts / responses / model versions;F6 审计是差异化 |
| D2 | **人话映射是数据,不是散落的字符串**:工具 `display`、指标 / 因子 / 情景 / recipe 行的 `display_name`、错误码句子——各一张表,各一条结构守卫「每个可能出现的名字都有一条」。守卫从注册表 / 签名推导,不写清单 | V3-R / MCP 批的纪律:守卫从签名推导;test_faces_strict 同款 |
| D3 | **错误分类在确定性层**:异常类 → 错误码在 worker / step_context 做;UI 只渲染码对应的句子;`message` 给人、`detail` 给运维。**不在 LLM 路径加规则** | no-fallback 哲学;V7-U3 的 `explainApiError` 已是这个形状,只是覆盖不全 |
| D4 | **图只画库里已有的行,且每个点可点回 id**;派生量(滚动波动率、回撤段、相关矩阵)用引擎**自己的函数**算,不在前端复算 | mockup 用 `build_portfolio_returns` 的同一构造复现了 run 的 13.558%;图与 tile 同源 |
| D5 | **读端点不铸新账本行**:能读 run 产物的读 run 产物(限额簿 → 持久化到 `limit_checks`);必须派生的(回撤段、reconcile)按 `(operation, params)` **复用已有 calc 行**,没有才铸 | 25,119 行账本;页面每次打开都铸行会把"每次计算一行"变成"每次刷新一行" |
| D6 | **图表组件自写 SVG,不引图表库** | 最大 825 点;dataviz 纪律(2px 线、tabular 数字、每图 Table 视图)自写更可控;零新依赖。§9 备选 visx |
| D7 | **散文里的 id → 编号引用是显示层变换**:存储文本不变、门不变;FE 把 `[fact_x, calc_y]` 变成上标 [1][2],chip 显示 resolver 给的 `label` | 门要 id;读者要标签;两者不必是同一个字符串 |
| D8 | 日报的"建议"改成**限额事实**:读者层的「Positions outside mandate limits」由 `risk_alerts` 确定性生成;不再向模型索取 `recommended_actions`(prompt 措辞过目);DB 列保留可空 | 两个 agent 一个口径(不给 verdict);Bloomberg 安全模型同一立场 |
| D9 | 免责一行在 composer 下方 + 首次登录确认一次,记在 `users.disclaimer_acknowledged_at`(不用 localStorage) | NN/g:免责靠近决策点、配动作;合规留痕 |
| D10 | 移动端本批只做「不裁切 + best on desktop」,不做响应式 | 收敛指示;桌面工具 |

---

## 2. 现状基线(2026-08-29,全部实读)

**栈**:Next 16.2.9 / React 19.2.4 / Tailwind 4 / Clerk 7(`apps/web/package.json`);**没有**图表库、**没有** FE 单测(验收靠 `tsc` + `next build` + Python 跨语言守卫);`apps/web/AGENTS.md` 警告 Next 16 与训练数据不同,**写 FE 前先读 `node_modules/next/dist/docs/`**。后端 1082 offline / 232 live(8/28);工具 31 个(`tools/*.py`,`Tool` dataclass 字段 name / description / json_schema / fn / tool_class / budget_key,`registry.py:88-95`);证据 7 类(`evidence_resolver_service.py:186-192`)。

### 2.1 mockup 元素 → 现状代码 → 改动类别

| mockup v2 元素 | 现状(文件:行) | 差距 | 类别 |
|---|---|---|---|
| 编号引用 + 人话 chip | `Evidence.tsx:27-40` chip = kind + 6 hex;`:152` `CitedText` 死代码;resolver 无 `label` | resolver 加 `label`;FE 变换 | BE-read + FE |
| 按类型的证据卡 + Technical details 折叠 | `Evidence.tsx:98-130` 键值 dump;抽屉 z-50 盖住 chat z-40 | 7 张卡;并排列 | FE |
| 溯源小图 / 包含树 | `calc.upstream` 已回;`analytics/containment.cover()` 只在工具内 | 端点 `containment` | BE-read + FE |
| Activity(人话步骤,折叠) | `ChatPanel.tsx:35-71` 渲染 `tool_name` / `result_summary`;`agent_steps.args` 已存(`trace_service.py:129`,redact + bound) | `Tool.display` 模板 + `StepOut.display` | BE-read + FE |
| Verified 徽章 | `meta` 只有 `prompt_tokens` / `gate` / `gate_refusals`(`meta_agent.py:226-233`);日报 `numbers_checked` 在 `workflow_events.payload_summary` | `meta.verified = {figures, sources}`;若 `numeric_verification.verify()` 已返回逐数匹配则直接落,否则加返回字段(判据不变) | BE-write(小) + FE |
| 数字级 basis 悬停 | 无 | 依赖上一条的逐数匹配 | FE |
| Audit 开关 | 无;模型 / token 已在 `StepOut`(`agent.py:215-230`) | FE 开关 + `audit-only` 渲染 | FE |
| 错误句(研究 run) | `step_context.py:81` `— ERROR: {exc_val}`;`issuer_research.py:40` `str(exc)`;`worker.py:195` `LEASE_EXPIRED_ERROR`(已是人话);`research_runs` 无 code / detail 列 | 错误码 + `error_detail`;`payload_summary.error` | BE-write + 迁移 + FE |
| 错误句(三处 `e.message`) | `issuer page:74`、`page.tsx:996`、`PortfolioModal.tsx:84` | 走 `explainApiError` | FE |
| 限额簿(27 条 meter) | `limit_checks` 只有 `limit_type / fired / alert_id`(`models.py:347-354`);`_check_one` 未触发时返回 None,current 不留(`limits.py:202-251`) | 持久化 current / warning / breach / status | BE-write + 迁移 + BE-read + FE |
| 告警文案含两档 | `page.tsx:743-755` 用 `alert.limit_value`(是被越过那一档) | 从限额簿取两档 | FE |
| 价值 + 回撤 + 回撤段 | `drawdown_service._returns`(`:63-72`)+ `analytics/drawdown.find_episodes`(`:53`);每次调用铸 calc(`:99-107`) | 端点 `history`;D5 复用 | BE-read + FE |
| 当日归因瀑布 | `reconcile_service.reconcile_move`(`:92`,铸 calc `:212`);`factor_attributions` 已存 | 端点 `reconcile`;D5 | BE-read + FE |
| 因子 β + 相关热图 | β 已存;`factor_model._max_vif`(`:194`)算 VIF 不回相关矩阵 | `factor_correlation()` 纯函数 + 端点 | BE-read + FE |
| 压力阶梯 + 档位 | `stress_results`(scenario / description / shocks / loss / held_flat)已存;`stress_loss` 两档在 `risk_limits` | 端点合并 | BE-read + FE |
| VaR 收益分布 / vol sparkline | `build_portfolio_returns` 可复现 run 数字 | 端点 `history` 顺带回 returns 与滚动 vol | BE-read + FE |
| 价格对比 + 申报标记 | `market_data_service.price_points`;`filings.filing_date` | 端点 `price-index` | BE-read + FE |
| 申报窗口阶梯 | `fundamentals_service._flow_facts`(`:49`)给 FlowFact;`period_semantics.describe_periods`(`:58`)给财年历 | 端点 `windows`(含未持窗口) | BE-read + FE |
| 利润率点图 / 债务栈 | `get_flow` / `get_balance_series` 逐指标 | 端点 `panel-series`(批量,同函数) | BE-read + FE |
| 覆盖矩阵 | `calc_service.list_available_metrics`(`:107`,V12 K1 带 kind / windows_filed) | 端点 `coverage`(列由所持申报推导) | BE-read + FE |
| 引用来源图 | `filing_sections` × `filing_chunks` × `issuer_briefs.citations` | 端点 `citation-map` | BE-read + FE |
| 会话列表 | `GET /api/agent/sessions` 已有(`agent.py:250-265`),`SessionSummaryOut` 无标题;FE 未用 | `title` = 首条 user 消息 | BE-read(小)+ FE |
| Runs 托盘 | `GET /api/exposure-runs` 有;`research-runs` **无列表端点**(`research.py` 只有 POST / GET by id) | 加 `GET /api/research-runs` | BE-read + FE |
| 页面感知建议 / 对象 Ask | `ChatPanel.tsx:22-26` 三条静态;chat 无 props | FE 模板(确定性),不用 LLM | FE |
| 「Data as of」顶栏 | `run_reads_service.get_run_freshness`(`:328`)只在工具面 | 端点 `freshness` | BE-read + FE |
| 显示名(指标 / 因子 / 情景 / recipe 行) | 无显示名字段(`semantics.py` 只有 gotcha) | `analytics/display_names.py` | BE + 守卫 |
| 日报 `Portfolio: port_001` | `exposure_workflow.py:917-918` 传 `portfolio_id`;`schemas.py:10-25` `ReportInput` 无名字 | 传 `portfolio_name`;sector / scenario 喂显示名 | BE-write(小) |
| demo 的测试 run | `list_runs`(`exposure_run_service.py:52-61`)不过滤;`triggered_by` 自由串 | owner 脚本清理 + API 收紧 | 数据 + BE |
| 免责 / 命名 | `layout.tsx:20-23` metadata「Exposure Workbench」;无免责 | 文案 + `users` 列 + 端点 | BE-write + FE + 措辞 |
| `_SYSTEM` 两句 | `meta_agent.py:35`「give the user the run id」;无精度指引 | 措辞 | 措辞(过目) |

### 2.2 不动的

四公理(`interval_algebra` / `containment` / `typed_calculator` / `formulas`)、门(`numeric_verification` 判据、`evidence_trail`、`trajectory_gate`)、工具面与预算、`agent_steps` 记录、RLS、配额。任何一处若被本批碰到,就是本批做错了。

---

## 3. 本批的纪律

1. **判据是容器里 grep 代码**,不是 commit(V9 部署失真的教训);FE 改动还要加一条:`NEXT_PUBLIC_*` 在 build 时内联,改 `.env` 不重建等于没改(`docker-compose.yml:224-231`)。
2. **每项修复先有一条会红的测试**(V3-R 纪律);呈现层的修复用 Python 守卫读 TS 源或用 `--dump-dom` 读渲染结果。
3. **措辞与代码分开提交**:`_SYSTEM`、日报 prompt、免责、工具 `display` 短语、错误句——这五组是产品文案,**先过目再进 commit**;代码可以先用占位句合并,守卫只检查"有句子",不检查句子内容。
4. **共享面先行**(V7 的教训):跨 lane 的文件(`schemas.py` / `lib/types.ts` / `errors.ts` / resolver 信封 / `StepOut`)在 S0 一次改完,之后 BE 与 FE 两条 lane 文件无交集。
5. **图的每个数字与 tile / 回答同源**:同一个 run 的同一个量,页面上只有一个来源;发现两处不一致就是 bug,不是"取整差异"。

---

## 4. 排程

单人约 10–11 人日;两条 lane(BE / FE)并行约 7 个工作日。每步:offline 全绿 + live 增量 → commit;S8 之前不 build 镜像。

### S0 · 共享面(0.5 天,单人,先做) ✅

**改动**
- `apps/api/schemas.py`:`WorkflowEventOut` 加 `error: {code, detail} | None`(来自 `payload_summary.error`);新 `EvidenceLabelOut`(`label`, `kind`, `short`)。
- `apps/api/routes/agent.py:215-230` `StepOut` 加 `display: str | None`;`SessionSummaryOut` 加 `title: str | None`。
- `apps/api/routes/research.py:71-84` `ResearchRunOut` 加 `error_code`、`error_detail`(detail 仅 owner 可见——`optional_user` 已设租户,RLS 决定可见性,字段本身不做权限分支)。
- `apps/web/lib/types.ts` / `lib/issuer.ts` 镜像以上;`lib/errors.ts` 词表扩到工作流错误码(S2 定义)。
- `apps/web/app/components/` 建骨架目录:`book/`、`issuer/`、`analyst/`、`evidence/`、`charts/`、`shell/`;`page.tsx`(1126 行)与 issuer page 只拆不改行为。
- **先读** `apps/web/node_modules/next/dist/docs/`(AGENTS.md 要求),把与本批相关的差异(layout / client components / `use(params)`)记进 `apps/web/README.md`。

**判据**:`tsc` + `next build` 绿;offline 全绿;没有任何可见行为变化(截图 diff 零)。

### S1 · 数据卫生与运维(0.5 天,可与任何步并行) ✅(删除/改标签、价格摄入待拍板)

- `scripts/prune_runs.py`(owner 角色,同 `delete_user.py` 形状):删除 `port_001` 上 `triggered_by ∉ {manual, scheduled, seed}` 的 run 及其子表;先 `--dry-run` 列出。**待拍板**(§9-③):删 vs 隐藏。
- `exposure_runs.triggered_by` 收紧:`CreateRunRequest.triggered_by` 改 `Literal["manual"]`(`exposure_runs.py:150`),验收脚本以后写 `seed` / `scheduled` 只能经 service。
- 价格摄入:demo 的价格停在 8/20,`Update exposure` 点了就失败。**待拍板**(§9-④):启用 `scheduled_update`(`schedules` 表 + worker 任务类型已存在,只缺 cron 行)还是上线前手动 `market-data/sync`。本批**不做**排程 UI。
- `GET /api/portfolios/{id}/freshness`(包 `get_run_freshness`)给顶栏「Data as of · N sessions behind · next update」。

**判据**:匿名 `GET /api/exposure-runs?portfolio_id=port_001` 无 failed、无测试触发;`freshness` 回 `sessions_behind`。

### S2 · 错误面(1 天,BE lane 起手) ✅

**错误码表**(确定性层,`exposure_workbench/errors/workflow_codes.py`,数据):

| code | 谁抛 | 给人的句子(FE `errors.ts`,措辞过目) |
|---|---|---|
| `tool_face_unavailable` | `agents/tool_session.ToolFaceUnavailable` | 已有 |
| `provider_unavailable` | OpenAI `APIConnectionError` / `APIStatusError`(5xx) | 「The model service was unavailable, so the run stopped before writing anything. Start it again.」 |
| `provider_quota` | OpenAI `RateLimitError` | 「The model service refused the request (rate or quota). Nothing was written; try again shortly.」 |
| `lease_expired` | `worker.py:195` | 已有句子,改为码 + 句 |
| `ingest_failed` | `filing_ingestion_service` 抛的类 | 「Reading the filings from EDGAR failed at <step>. Nothing was written.」 |
| `run_failed` | 其余 | 「The run stopped before finishing. Nothing was written.」 |

**改动**
- `workflow/step_context.py:79-81`:失败时 `msg = f"{self.message} — stopped"`,`payload["error"] = {"code": classify(exc_val), "detail": str(exc_val)[:2000]}`。`classify` 是异常类 → 码的映射(数据),放 `errors/workflow_codes.py`。**不改** rollback 行为(那是登记在案的另一项)。
- `apps/worker/handlers/issuer_research.py:40`:`update_status(..., error_code=classify(exc), error_message=<码的句子>, error_detail=str(exc))`;`research_run_service.update_status` 签名加两参。
- 迁移 `infra/migrations/v13_run_errors.sql`:`research_runs.error_code`、`error_detail`(幂等 `ADD COLUMN IF NOT EXISTS`;老行 NULL = "未分类",UI 显示通用句)。`exposure_runs.error_message` 已是人话(价格陈旧句),只加 `error_code` 列,默认 `run_failed`。
- FE:`issuer page:74`、`page.tsx:996`、`PortfolioModal.tsx:84` 改走 `explainApiError`;`RunTimeline` 失败行渲染 `error.code` 的句子,`detail` 只在 Audit 层。
- 守卫:`tests/test_error_vocabulary.py` 扩到工作流码(现有三条守的是 HTTP 码:`:49/:61/:82`);新增 `test_workflow_error_codes.py`:①`classify` 对每个已知异常类返回表内的码;②`errors.ts` 对表内每个码有句子;③`step_context` 失败路径的 `message` 不含 `ERROR:`(`test_step_payload.py` 加一条参数化)。

**判据**:活库那三条真实失败(429 原文、`exposure-mcp:8000`、`max_tokens`)回放后 UI 各是一句人话;`--dump-dom` 的 `/issuer/FOOBAR` 不含 `API 404`。

### S3 · 证据标签、编号引用、证据卡(1.5 天,BE 0.5 / FE 1) — BE ✅ / FE 归入 S6

**BE**
- `evidence_resolver_service.py:36-181` 每类多回 `label`(同一函数内,不新增查询):fact「Gross profit · Q2 FY2026 · 10-Q」(指标显示名 + 窗口标签 + form);calc:recipe label / 公式名 + 窗口(`params` 里有);chunk「10-Q · Part I, Item 2 · MD&A」;src「publisher · title」;alert:`message`;run「Exposure run · Aug 20, 2026」;pos「AAPL · 5,000 sh」。窗口标签复用 `period_semantics`(财年 / 财季从 `period_end` 推,同 V12 K0)。
- `GET /api/evidence/labels?ids=…`(批量,给一条回答的 17 个引用一次取标签)。
- `containment` 端点:`GET /api/issuers/{t}/containment?formula=total_debt` → `cover()` 的取用节点 + 该发行人 present 指标间的包含边 + 被拒配对(`typed_calculator` 的拒绝理由是现成字符串)。
- `meta.verified`:`respond` 过门后写 `{"figures": n, "sources": len(citations), "matches": [...]}`;若 `numeric_verification.verify()`(`:952`)现在不返回逐数匹配,加一个返回字段(**判据一行不改**,`test_numeric_verification.py` 全绿是前置)。

**FE**
- `evidence/Cite.tsx`:把文本里 `[id, id]` / 裸 `id` 变换成上标编号;编号顺序 = 该消息 `citations` 数组顺序;悬停显示 label;点击开证据栏。**存储文本不变**。
- `evidence/cards/*.tsx` 7 张卡(Fact / Calc / Passage / Source / Run / Alert / Position),每张:标题 = label,主值,期间 / 申报 / 链接,「Technical details」`<details>`(id、版本、provider、span),Audit 开时默认展开。Passage 卡高亮被引数字与引句(`meta.verified.matches` 给位置;没有时不高亮,不猜)。
- 证据栏改为 grid 第三列(`216 / 1fr / 340 / 368`),**不遮** chat;<1500px 时收起左栏(mockup 已验证)。
- 数字级 basis:`<Fig>` 组件,`data-basis` 来自 `meta.verified.matches` 与 resolver label;没有匹配的数字不加虚线(诚实)。

**守卫**:`test_evidence_labels.py`:①对 `_RESOLVERS` 的每个前缀(从 `evidence_resolver_service._RESOLVERS` 推导,不写清单)resolver 返回非空 `label`;②label 不含任何 id 前缀。FE:`scripts/smoke_ui.py --check ids`:`--dump-dom` 读者层零 id(S8 的机械验收之一)。

### S4 · 读者层 / 审计层(1.5 天,BE 0.5 / FE 1)

**BE**
- `tools/registry.py:88-95` `Tool` 加 `display: str`(模板,如 `"Evaluating {name} for {ticker}"`、`"Searching filings for “{query}”"`);31 个工具各一句(**措辞过目**);`StepOut.display` 由 `display.format(**args)` 生成(args 已 redact + bound,`trace_service.py:129`),缺 key 时回落到工具描述的第一句——这不是 fallback 降级,是显示模板的定义(守卫要求每个工具都有模板)。`rejected` 步骤 display =「Look-up refused: budget」/「Look-up refused: invalid arguments」。
- `analytics/display_names.py`(数据):`METRIC`(39 个规范指标)、`FACTOR`(8)、`SCENARIO`(5,或直接用 `stress_results.description`)、`RECIPE_ROW`(16)、`LIMIT`(`LIMIT_SPECS` 的 8 类)。REST 响应凡带这些名字的地方加 `label`(snapshot.available_metrics、financials.calcs、factor_attributions、stress、alerts)。
- `ReportInput`(`schemas.py:10-25`)加 `portfolio_name`;`_build_user_message` 用名字、sector / scenario 用显示名(确定性预格式化);`[WARNING]` 重复由 FE 去掉方括号标签(报告文本本身不改——它已过门)。
- 会话标题:`list_agent_sessions` 一条子查询取首条 user 消息前 80 字。

**FE**
- Audit 开关(顶栏 + `.app.audit`);`audit-only` 元素:Run ID / task / triggered_by、模型版本 / token、原始工具名与 `result_summary`、`error.detail`、证据卡 Technical details 展开、审计条(`/api/me/usage` + `agent_steps` 聚合——后者需要一个小端点 `GET /api/me/audit-summary`,只读)。
- 删除读者层的:`Model:` 行(`page.tsx:585`)、Mock 警告(`:588`,改为 `confidence_flags.mock_mode` 时整卡显示「This report was not produced by the model」——但 V4-S1 后已无 mock 路径,守卫断言该分支不可达则删)、Run Details 卡(`:556-583` → 折叠的 run rail 一行 + Audit)。
- Activity:`analyst/Activity.tsx`,答后保留、折叠、`N steps · T s`;Audit 开时每步下一行原始工具名与 token。
- 告警行文案:「LLY is 13.8% of the book — above the 12% warning tier; breach tier is 18%」两档来自 S5 的限额簿端点;删 `entity_type · alert_type` 行。
- 覆盖度一行 + 展开;Pipeline 完成即折叠「Completed in 19 s · 11 steps · 27 checks · N figures checked」。
- 页面感知建议:`analyst/Suggestions.tsx` 按视图生成(组合:active alerts / top weights;发行人:`available_metrics` 里可算的公式);告警行、持仓行「Ask」把对象带进 composer。全部是模板,不调模型。
- `rrun_…` 提及 → 链接卡(chat 文本里检测 `rrun_[0-9a-f]{12}`,渲染「Research on NVDA · running · open」);配合 S7 的 `_SYSTEM` 改句。

**守卫**:`test_tool_display.py`:每个注册工具 `display` 非空且 `format` 用 schema 的 required 字段能成功(从 `json_schema` 推导,不写清单);`test_display_names.py`:`METRIC` 覆盖 `concept_mapping` 的全部规范指标、`RECIPE_ROW` 覆盖 `recipe.run_standard_recipe` 的全部 label、`FACTOR` 覆盖 `factor_config.yaml`、`LIMIT` 覆盖 `LIMIT_SPECS`(全部从源推导);缺一个就红。

### S5 · 图表只读端点(2 天,BE lane)

全部 `GET`、`optional_user`、走现有 service;**不新建分析**。

| 端点 | 复用 | 返回 | 备注 |
|---|---|---|---|
| `GET /api/portfolios/{id}/history?span=3y` | `drawdown_service._returns` + `analytics/drawdown.find_episodes` + `risk_metrics` 的滚动 std | `dates, value, drawdown, episodes[], vol30[], returns[]`;`valuation_assumption` 原句照回 | value = 固定数量 × adj_close(与 `build_portfolio_returns` 同构,`market_data_service.py:173`);D5:回撤段 calc 按 `(operation, params)` 复用,不每次铸行——需要 `calc_service.find_recorded(operation, params)`(新,只读) |
| `GET /api/exposure-runs/{id}/reconcile` | `reconcile_service.reconcile_move`(`:92`) | 两恒等式 + shares | D5 同上(`:212` 现在每次铸行) |
| `GET /api/exposure-runs/{id}/limit-book` | 新持久化列 | 27 条 `{key, label, group, current, warning, breach, status, alert_id}` | 见迁移 |
| `GET /api/exposure-runs/{id}/factor-correlation` | 新纯函数 `factor_model.factor_correlation(df)` | 8×8 + 窗口 + `max_vif` | 窗口 = 该 run 的 `regression_window_days` / `attribution_date`(`exposure_metrics` 已存) |
| `GET /api/exposure-runs/{id}/stress` | `stress_results` + `risk_limits` 两档 | 5 条 + shocks + held_flat + tiers | 已存,只是拼 |
| `GET /api/issuers/{t}/price-index?benchmark=SPY&span=1y` | `market_data_service.price_points` ×2 + `filings` | 两序列指数化 + 申报标记 | 基准选表规则已在 `price_points`(V8 ⑤) |
| `GET /api/issuers/{t}/windows?metric=revenue` | `fundamentals_service._flow_facts` + `period_semantics.describe_periods` | 已持窗口 `{start,end,months,value,form,filed,fact_id}` + 未持窗口(按财年历列出的季度槽) | 未持窗口是**推导**(财年历 × 已持窗口的补集),不是数据;响应里标 `held: false` |
| `GET /api/issuers/{t}/panel-series?metrics=…` | `get_flow` / `get_balance_series` 逐指标(同一函数,批量) | 每指标的点序列,每点带 `fact_id` / `calc_id` | 利润率点 = 两 fact 相除 → 用 `typed_calculator` 铸 calc(D5 复用) |
| `GET /api/issuers/{t}/coverage` | `list_available_metrics` + facts 存在性 | 列(由所持申报推导:FY / 季 / 半年 / 余额日)× 行(指标)矩阵 | `interest_expense` 一行的 `superseded_by` 来自 V12 K1 |
| `GET /api/issuers/{t}/citation-map` | `filing_sections` × `filing_chunks` 计数 × 最新 brief `citations` | 每节 `{form, item, title, chunks, cited}` | 一条 SQL |
| `GET /api/research-runs?limit=` | `research_run_service` 新 `list_runs`(RLS 作用域) | 摘要 | Runs 托盘 |

**迁移** `infra/migrations/v13_limit_checks_values.sql`:`limit_checks` 加 `current_value NUMERIC`、`warning_level NUMERIC`、`breach_level NUMERIC`、`status TEXT`(`ok|warning|breach`);**不回填**(老 run 的行 NULL,读端点按 V8-P 的约定回「this run did not record it」)。写入侧:`analytics/limits.check_limits`(`:253-333`)返回值加 `checks: list[CheckRecord]`(每个被评估的 `(type, entity)` 一条,含 current 与两档——`_check_one` 今天算了又丢),`exposure_workflow` 在写 `LimitCheck` 行时带上(`models.py:347-354`)。`test_limit_checks.py` 加断言:`checks` 的键集 = `evaluated`(V8-P3 的 `check_key` 一致性)。

**守卫**:`test_v13_read_endpoints.py`(offline,合成夹具满足构造函数不变量——V8 纪律):①每个端点 200 且每个数值点带 id;②`history` 的最后一个 `vol30` 与同日 run 的 `rolling_vol_30d` 相等(半个 ulp);③`limit-book` 的 27 条键 = `evaluated`;④两个铸 calc 的端点连续调用两次账本行数不变(D5)。live:对 `port_001` / `run_95ebe31c5e51` / AAPL 各跑一次,数字与 `viz-build/chart_data.json` 逐位一致(那是从活库独立算的)。

### S6 · 图表组件与页面重组(3 天,FE lane;S5 的端点逐个就绪即可接)

- `charts/` 自写 SVG(D6):`LineChart`(十字线 + tooltip + 事件带)、`Sparkline`、`Histogram`、`Waterfall`、`Meters`、`DivergingBars`、`Heatmap`、`Ladder`(窗口)、`DotPlot`、`StackedBars`、`CoverageGrid`(HTML 表)、`CiteMap`;共享 `useTooltip`、`scale/ticks`、`Legend`、`TableView`(每张图的 Table 切换——既是无障碍也是审计层)。调色板 = mockup 已过 dataviz 验证的那组(`#3987e5 / #d95926 / #199e70`,深色面 `#11161D`);状态色沿用产品 token;**单轴、不环图、不双轴**。
- `book/`:`Titlebar`、`SinceLastRun`、`Kpis`(含 sparkline / 分布)、`ValueDrawdown`、`Waterfall + LimitBook` 行、`Warnings`、`Holdings`(Ask)、`Betas + Correlation` 行、`Stress`、`Briefing`(Verified 徽章 + 「Positions outside mandate limits」由 alerts 生成)、`RunRail`(折叠)。
- `issuer/`:`Header`(覆盖句 + 近档位 chip)、`ResearchCard`(预期时长按 readiness:就绪 1–2 min / 首次摄入 6–10 min——数字来自 `workflow_events.duration_ms` 的历史中位数,端点 `freshness` 顺带回)、tabs:Overview(price-index、debt & cash、margins、coverage、brief 摘录)/ Financials(ladder + 表带 basis)/ Filings(cite-map + 章节)/ Brief(mix 行 + 编号引用)/ Sources。
- `shell/`:`Topbar`(字标、Data as of、Runs 托盘、Audit、配额)、`Rail`(Books / Threads / Briefs)、`AnalystDock`(常驻右栏,`ChatPanel` 改造:会话列表、Activity、Verified、页面感知建议、免责行);chat 状态提到 layout 级 provider,两页共享。
- 移动端:`<900px` 单栏可滚 + 一条「best on desktop」(D10)。

**判据**:mockup v2 的 7 张截图状态在真实数据上逐一复现(书首屏 / 分析行 / 压力 / 发行人概览 / 窗口 + 包含树 / 引用图 / Table 视图);`tsc` + `next build` 绿;bundle 内 `localhost:8103` 零次(V7 那条)。

### S7 · 免责、命名、口径(0.5 天 + 过目)

- 免责一行(composer 下)+ 首次登录确认:`users.disclaimer_acknowledged_at`(迁移 `v13_users_ack.sql`),`POST /api/me/acknowledge-disclaimer`(**进 POST 配额白名单**——`tests/test_v2_audit.py:195` 「写路由必达配额或上白名单」的守卫会红,这是预期),`GET /api/me` 回该字段。
- `layout.tsx:20-23` 与首页 header 统一为 desk-for-one;meta description 去掉「LLM reporting」。
- 日报:prompt 不再索取 `recommended_actions`(`prompts/daily_exposure_report.md` 改句,`report_verification.py:80` 的必填集去掉该字段,`_REQUIRED_FIELDS` 同步);读者层显示 alerts 生成的限额事实。
- `_SYSTEM`(`meta_agent.py:35`)两句:「give the user the run id to follow」→「tell the user the brief is being prepared and will appear on the issuer page」;加「write figures at the precision an analyst would say them; the check accepts correctly rounded values」(`numeric_verification.py:31-39` 的半 ulp 判据已支持)。
- **以上五组文案 + S4 的 31 句工具 display + S2 的 6 句错误句,一起列成一份 `docs/V13_WORDING.md` 过目**;过目前代码用占位句合并(守卫只查非空)。

### S8 · 验收与部署(0.5 天)

1. offline 全绿(基线 1082 + 本批新增)、live 全绿(232 + 新增)。
2. 迁移三份(`v13_run_errors` / `v13_limit_checks_values` / `v13_users_ack`)幂等,**先于** `up -d`(PRODUCTION.md 的顺序)。
3. `docker compose build` **四镜像**(web / api / worker / mcp——`Tool.display` 在 `tools/`,mcp 也装了注册表)→ `up -d` → **容器里 grep**:api `grep -c "def factor_correlation"`、worker `grep -c "error_code"`、web bundle `grep -c "localhost:8103"` = 0。
4. `scripts/smoke_ui.py`(headless Chromium,已在本机 `~/.cache/ms-playwright`):对 `/`、`/issuer/AAPL`、`/issuer/FOOBAR` `--dump-dom`,断言:读者层零 id;无 `API 4xx` / `Error code:` / `exposure-mcp` 字样;Audit 开后 id 出现(证明是开关不是删除)。
5. 匿名读 200 / 匿名写 401;dev 账户跑一轮真实 turn,`meta.verified` 落库。
6. 截图七张进 `dev_note/portfolio-demo/ui-review/screenshots/live_*`,与 mockup 并排。

---

## 5. 结构守卫(本批新增,每条钉住一个修复)

| 测试 | 钉住什么 | 推导来源(不写清单) |
|---|---|---|
| `test_workflow_error_codes.py` | 异常类 → 码;每个码有 FE 句子;失败 message 不含 `ERROR:` | `workflow_codes.CLASSIFY` 的键集;`errors.ts` 正则 |
| `test_error_vocabulary.py`(扩) | UI 解释的码 ⊆ 后端抛的码,反向也列出工作流码 | 现有 |
| `test_evidence_labels.py` | 每类证据有 label 且不含 id 前缀 | `evidence_resolver_service._RESOLVERS` |
| `test_tool_display.py` | 每个工具有 display 且能用 schema required 字段 format | `ToolRegistry.tools` + `json_schema.required` |
| `test_display_names.py` | 指标 / recipe 行 / 因子 / 限额类全覆盖 | `concept_mapping`、`recipe`、`factor_config.yaml`、`LIMIT_SPECS` |
| `test_limit_checks.py`(扩) | `checks` 键集 = `evaluated`;持久化列非空 | 现有夹具 |
| `test_v13_read_endpoints.py` | 每点带 id;vol30 与 run 相等;两次调用账本不增 | 合成夹具 |
| `test_v2_audit.py`(`:195` 起,写路由必达配额或上白名单) | `acknowledge-disclaimer` 进白名单 | 现有 |
| `scripts/smoke_ui.py` | 读者层零 id;失败面零传输串;Audit 开关生效 | 渲染结果 |

---

## 6. 验收(定义性判据)

1. 读者层零 id、失败面零传输串(S8-4 机械验收)。
2. mockup v2 的 14 个面板在真实数据上全部可交互,每张图有 Table 视图,每个点可点回证据卡。
3. 图上任一数字 = tile / 回答 / run 产物里的同一个数(S5 守卫②)。
4. 三条真实失败(429 原文 / 内网主机名 / `max_tokens`)回放后各是一句人话 + 下一步。
5. 过门回答带「✓ N figures checked · M sources」,拒答琥珀色且不带引用。
6. demo 公开列表无测试 run、无 failed;顶栏「Data as of」与 `get_run_freshness` 一致。
7. 免责一行在场,首次登录确认落库;日报读者层无「Consider trimming」类句子。
8. 四镜像容器内 grep 通过;offline / live 全绿;bundle 无 localhost。

---

## 7. 风险与退路

| 风险 | 表现 | 退路 |
|---|---|---|
| `Tool.display` 改了 `Tool` dataclass,mcp 容器忘了重建 | api 有 display、mcp 面没有,`test_registry_enforcement_live` 红 | S8-3 明写四镜像;live 断言两面 `display` 一致 |
| 读端点铸行(D5 未做好) | 账本每次刷新长一行 | S5 守卫④;上线前对账 `calc_ledger` 行数 |
| `limit_checks` 新列在老 run 上 NULL | 限额簿对老 run 显示"未记录" | 按 V8-P 约定,不回填;demo 重跑一次即有 |
| 逐数匹配(`meta.verified.matches`)改到 `verify()` 内部 | 判据漂移 | 只加返回字段;`test_numeric_verification*` 全绿是合并前置;改动 diff 不得触及 `_EXEMPTION_PATTERNS` 与容差 |
| Next 16 约定与训练数据不同 | layout 级 provider / `use(params)` 写错 | S0 先读 `node_modules/next/dist/docs/`,把差异记进 README |
| 文案过目拖住代码合并 | 分支长期不合 | 纪律 3:占位句先合并,守卫只查非空 |
| 两条 lane 撞同一文件 | 本机有并行 session 在同一工作树(V7 事故) | S0 共享面先行;新建文件前先看是否存在 |

---

## 8. 本批不动、登记待议

- 排程 UI / 晨报送达(表已有,P2)、brief / 日报导出(P2)、观察名单 / thesis monitor(P2)、真正的响应式(P2)、回答「保存到组合」(P2)。
- 匿名聊天(仍需登录;shop-window 不变)。
- `step_context.step` 失败路径不 rollback(已挂起,本批只改它的 message,不改事务行为)。
- 标签漂移时间线、重述对比(数据已有,独立小批)。
- 引文路线符号盲、判断禁令仍是提示层(既有 ★遗留)。

---

## 9. 待拍板(boss)

1. **图表实现**:自写 SVG(D6,零依赖)vs 引 visx。
2. **首次免责确认的存储**:`users` 列(D9,留痕)vs 仅 localStorage。
3. **demo 上的测试 run**:owner 脚本删除(建议;`app_rls` 无 DELETE,只能 owner 做)vs 列表过滤隐藏。
4. **价格摄入**:启用 `scheduled_update`(cron 行)vs 上线前手动 sync;本批不做排程 UI。
5. **文案过目方式**:一份 `V13_WORDING.md` 一次过(建议)vs 分五组随各步过。
6. **Audit 层的可见范围**:任何登录用户看自己数据的审计信息(建议)vs 仅 dev 白名单。
7. **`recommended_actions`**:停止索取(D8,建议)vs 保留但只进 Audit 层。
8. **是否要 FE 单测**(vitest,一个新 dev 依赖)守 `Cite` 变换与 `explainApiError`;不加则靠 `smoke_ui.py` 的渲染断言。
9. **S5 的 `find_recorded`**:按 `(operation, params)` 复用 calc 行(D5,建议)vs 接受读端点铸行。
