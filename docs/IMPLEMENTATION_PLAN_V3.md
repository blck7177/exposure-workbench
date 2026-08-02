# Implementation Plan V3 — Harness 组件补全(Verify / Context / Memory / Evals)

> 定位:production 前的正确性收口。V2 把系统做成了"陌生人可以注册使用";V3 把 agent 的
> 回答做成"金融场景下可以被信任"。框架来自 harness 组件盘点(2026-08-01):
> Verify 是最弱组件、Context 与 Evals 缺失、Memory 写得进读不出。
>
> ★ **本文是 2026-08-02 修订版**。初版从盘点报告写成、未逐行核对代码,六个侦察 agent +
> 一个接缝 agent 在真实代码与**运行中的 Postgres** 上验出 22 处失真,已全部就地改正并标 ★。
> 凡标 ★ 的段落,其结论优先于任何记忆中的初版说法。

---

## 0. 执行者须知

### 0.1 全局规则(继承 V1/V2 全部,重申三条最相关的)

1. **无 fallback**:验证不过 = 结构化拒绝,不降级、不 strip、不静默放行。修一个洞的方式是
   消灭那个错误类别,不是加一条 LLM 提示词。
2. **文档先行**:任何与 TARGET_ARCHITECTURE / MODULE_NOTES / faces.py 既有决策冲突的实现,
   先停下改文档再写代码。
3. **验收 = 实测**:每阶段验收分 offline(`pytest -m "not live"`)与 live(真栈)两栏,
   live 项必须给出实测数字或复现步骤。

### 0.2 硬性代码纪律

- 新验证逻辑进**正交模块**(独立文件、纯函数优先),gate 只做编排。禁止把数字核对内联进
  `_respond`。禁止在 `reserve()` 里写 `if session.kind == "research"` —— 策略必须**由行携带**,
  不由分支判断(见 B2)。
- 新工具必须:schema 带 `required`、注册进 face、结果可被 harvest、有 offline schema 测试 +
  至少一个 live 行为测试。结构守卫优先于逐点测试。
- 改 gate 行为时同步处理旧测试钉子;**注意"反转"与"注释失真"是两回事**(见 ★ 更正 7)。

### 0.3 钉死的实现常量(★ 多处更正)

| 常量 | 值 | 依据 |
|---|---|---|
| **匹配判据** ★ | **写法精度的半个 ulp**,不是 rtol | 初版 `rtol=0.005` 同时**太紧又太松**:sector weight `0.04061908` 写成正确的 `4.1%` 相对误差 0.94% 被**误拒**;而 `$82.886B` 的 rtol 开出 ±$414M 窗口,末位篡改被**误accept**。半 ulp 的语义是"真值必须能四舍五入成模型写下的那个数",两头都对 |
| **单位类** ★ | `RATIO / PERCENT / MONEY / COUNT / MULTIPLE`,同类才比,ratio↔percent 由**schema 已知的列语义**换算 | 初版的"百分比双向登记 + `{v, v/1e3, v/1e6, v/1e9, v*100}` 缩放族"是五路"我不知道单位所以什么量级都收",当场违反 §0.1 无 fallback。**实测反例**:`alert_07a618a0b13d` 同一行有 `current_value=0.15840195`、`limit_value=0.15`、`utilization=0.79200974`;缩放族下"AAPL 已用到限额的 15.8%"会被**接受**,而真实 utilization 是 79.2% |
| `ExtractedNumber` ★ | `(span, surface, value, unit_class, atol, key)` | 初版的 `(value, raw, span, unit_hint)` 缺 unit_class —— 而 unit_class 正是上一行那条安全性质本身 |
| 豁免类别 ★ | **9 类**,闭集(见 §A1 表) | 初版 4 类漏了 **ISO 日期**:实测 7 条 live assistant 消息里 **2 条**含 `\d{4}-\d{2}-\d{2}`,"the quarter ended 2026-04-26" 在 4 类表下产出三个伪数字 |
| id 豁免的正则 ★ | **枚举前缀 + `[A-Za-z0-9_]{3,}`**,枚举表含 `rrun_/co_/filing_` 等**非可引用**前缀 | 通用 token 形状 `\b[a-z]{2,10}_[A-Za-z0-9]{4,}\b` 在真 id 上失效:`exposure_runs` 里有 `run_seed_prev_01`、`run_rvprobe1`,前者末尾 `01` 会漏成裸数字。豁免必须覆盖**所有** id 前缀而非六个可引用前缀 —— 实测 `msg_b523a5eb7d70` 是一条合法的零引用回复,唯一的数字在 `rrun_0bef53cb5360` 里 |
| `CONTEXT_SOFT_LIMIT_TOKENS` | `80_000`(settings,env 可覆盖)★ **且必须加进 docker-compose 的 exposure-api environment 块** | 保守值,B0 实测后再议。compose 现在只透传 `TURN_LEASE_SECONDS` 与 `DAILY_*`,连 `SESSION_TOOL_BUDGET` 都没透传 → 不加就无法做 B1 的 live 验收 |
| tokenizer | tiktoken `o200k_base` 显式指定;**计数必须含 `tools` schema** ★ | `encoding_for_model` 不认识 gpt-5.4-mini。tools 走 `chat_with_tools(tools=...)`、**不在 messages 里**,漏算会让 B3 的判读分母是错的 |
| tiktoken 供给 ★ | 显式进 `pyproject`;`Dockerfile.api` 设 `TIKTOKEN_CACHE_DIR` 并构建期预热 | 实测:容器里 `import tiktoken` 可用(langchain-core 传递引入),但 `TIKTOKEN_CACHE_DIR` 未设、无预热指令 → 首次调用**走网络**下载 BPE 到临时 /tmp,容器重启即丢。worker 不需要(`handle_message` 不在 worker 上跑) |
| `TURN_TOOL_BUDGET` | `15`/turn(meta);research **保持终身 40** ★ 且**由行携带策略**,不由 kind 分支 | 实测 live research session 单次 run 内用了 **32 / 26 / 25** 次工具调用且**从不调 `claim_turn`** → 朴素的 per-turn 15 会让每一个 issuer research 在第 15 次调用上死掉 |
| `_ID_PREFIXES`(registry.py:47) | 收缩为 gate 可解析的 6 个:`fact_ chunk_ calc_ src_ alert_ run_` | 消灭 harvestable-but-unciteable 不对称。★ 注意这**只**关闭不对称;真正关闭伪造 id 的是 GATE 排除,**两个洞不是一回事,测试名不许混** |
| `respond_retries` / `submit_brief_retries` | **删除** | 三处声明零处实现。★ 同步点是 **4 处**不是 3:`settings.py:37-38`、`test_p0_schema.py:46-47`、`MODULE_NOTES.md:299`(M9)**和 `:424`(M10)**;`IMPLEMENTATION_PLAN.md:52` 是 V1 历史记录,**不动**,并在 commit message 里写明为什么不动 |
| 检索 golden set | ≥ 24 query(8 issuer × 3 类) | 见 D1 |

### 0.4 ★ 阶段依赖图(修订)

```
S1 计划/文档更正
  └→ S2 单次 schema commit(migration + init.sql + models.py + PRODUCTION.md + 守卫测试)
       ├→ A0-4 + B 的两个新 settings(同一 commit,同改 settings.py/test_p0_schema.py)
       ├→ numeric_verification 抽取器(A1 签名,A0 时段建)→ A0-1 → A0-3 → A0-2
       │      └→ A1 全量 → D2
       ├→ B0 → B1 → B2
       └→ C4 → C2 → C3 → C1 → C5
                                 └→ D1(独立)
```

★ 与初版的关键差异:①新增 S1/S2;②抽取器**在 A0 时段按 A1 的签名一次建成**(否则要写两遍
并制造"两个会互相矛盾的检测器",正是 A0-3 要消灭的错误类别);③C 不再与 A 完全独立 ——
A0-3 必须先于 C,否则 C1/C2 返回的 `rrun_` 是"能取回但永远不能引用"的 id。

### 0.5 拍板点

已确认(2026-08-02):**①A1 全严格**(数字必须先过 `compute_*`);**②B2 改 15/turn**;
**③失败 turn 不退费**。

★ 侦察新提出、需在实现中定的两个(本计划已给出选择,执行时如无异议即按此执行):
- **C1 `read_issuer_brief` 的 face 归属**:定为 **meta-only**。理由:让写 brief 的 research
  agent 去引用上一份 brief 的 id 是循环论证。这不是既有文档里的决策,故不需要改 faces.py。
- **C3 `get_portfolio_positions` 的 face 归属**:定为 **meta-only**。`faces.py:31-33` 已白纸黑字
  记着"research face 保持 issuer-scoped,加组合权重会改变 brief 生成、需要单独验证" ——
  初版把 C3 放进 research face 直接违反 §0.1 规则 2。维持既有决策,faces.py 注释不动。

---

## S1 — 计划与文档更正(本次提交)

本文件即 S1 的产物。同时修正三处**已经在说谎**的既有文档(与 A0-4 合并提交):

- `MODULE_NOTES.md:299`(M9)、`:424`(M10):retry 预算"2 次重投 / 1 次重试"从未实现。
- `MODULE_NOTES.md:424` 第二句 `citations=[] 合法(非事实性回复)` —— A0-1 之后只有
  **不含数字的**回复才合法。
- `MCP_BOUNDARY_PLAN.md:21` "READ_CORE(12 工具)":`faces.READ_CORE` 实际是 **11** 个,
  12 是 `build_read_registry()` 的大小(READ_CORE + `get_portfolio_snapshot`)。C 的四个新工具
  会再次改变这两个数字,收尾时一并更新。
- `MODULE_NOTES.md:525` "check_limits 死参数已在 V2-H 关闭" —— 失真句,V2 known limit 仍在。

## S2 — 单次 schema commit(三处同步 + 第四处)

三个阶段各自都要加列;合成**一个** migration 避免三次 DDL、两次重复加同一列。

`infra/migrations/v3_harness.sql`(新文件)+ `infra/init.sql` + `db/models.py` 三处同步,
★ **外加第四处:`docs/PRODUCTION.md`** —— 初版完全没提。新增列:

| 表 | 列 | 用途 |
|---|---|---|
| `agent_messages` | `meta JSONB DEFAULT '{}'` | A0-2 的 gate 失败标记。★ **不能复用 `role`**:`meta_agent.py:62` 把 `m.role` 原样喂进 OpenAI messages 数组,写一个非法 role 会直接破坏下一轮请求 |
| `agent_sessions` | `last_prompt_tokens INT` | B0 计量 |
| `agent_sessions` | `turn_tools_used INT NOT NULL DEFAULT 0` | B2 per-turn 预算 |
| `agent_sessions` | `turn_tool_budget INT` | B2 **行携带策略**:meta=15,research=NULL(=用终身 `tool_budget`) |
| `issuer_briefs` | `block_citations JSONB` | C1 按 block 返回引用。现表只有一个**扁平** `citations` 列(`models.py:648`),且 `research_tools.py:88` 的 `sorted(set(...))` 把 block 归属**销毁**了 |

★ **同 migration 内必须带 backfill**(不能拆成后续脚本):
`UPDATE agent_sessions SET turn_tool_budget=15 WHERE kind='meta'`。实测 `tool_budget` 现状分布
meta `0×9 / 1×9 / 2×1 / 40×22`、research `40×11`、**零 NULL**;B2 把
`session.tool_budget or settings.session_tool_budget`(`agent_session_service.py:151`)改成
`is not None` 之后,那 9 行 `tool_budget=0` 会从"实际 40"变成"真的 0",backfill 是扫掉它们的地方。

★ **部署顺序更正**:`PRODUCTION.md:203-208` 现在把 `docker compose build/up` 排在 schema 步骤
**之前** —— 对任何加列的 migration 都是错的。本次一并改正,并加一条守卫测试:
`infra/migrations/` 下每个文件都必须在 PRODUCTION.md 里被点名。

★ 已核实**不受影响**:`tests/test_rls_parity.py` 只从 migration 里抽 `workflow_events` 策略与
`ALTER VIEW ... security_invoker` 两类行,一个纯 ALTER 的 V3 文件对它不可见。

---

## V3-A — Verify 组件

### A0-0 抽取器(`services/numeric_verification.py`,在 A0 时段建成 A1 的签名)

纯函数、零 DB 依赖。A0 落 `extract_numbers` / `raw_forms` / 9 类豁免表;A1 追加
`resolve_cited_values` / `verify` / `_VALUE_SOURCES`。

```python
@dataclass(frozen=True)
class ExtractedNumber:
    span: tuple[int, int]      # 原文字符区间
    surface: str               # 逐字原文,如 "$94.9B"
    value: float               # 规范化量级
    unit_class: str            # RATIO | PERCENT | MONEY | COUNT | MULTIPLE
    atol: float                # 写法精度的半个 ulp —— 判据随数字走,不是全局常量
    key: str                   # 去重键
```

`raw_forms()` **按 span 去重**(A1 未定义此函数,但 A0-1 的 `numbers_found` 需要它)。

★ 9 类豁免(闭集):①独立年份 1900–2100 ②**ISO 完整日期** ③id token(枚举前缀 +
`[A-Za-z0-9_]{3,}`)④期间标签 Q1–Q4 / FY24 / H1 ⑤表单号 10-K/10-Q/8-K ⑥列表序号
⑦字母数字型号 ⑧时长基数词 ⑨SEC accession 号。第 2、3 类是实测补的,其余四类未能独立复现
其语料统计但成本极低、方向无疑。

### A0-1 关零引用口(`meta_tools.py:152-161`)

空 `citations` 且文本含实质数字 → `{"error":"citations_required","numbers_found":[...]}`;
真无数字的回复(问候、澄清反问)仍可零引用。`db` 在该分支上不被触碰,故可用 `db=None` 做
offline 测试。同步改 `respond` 的 **tool description**(模型的契约不能撒谎),
**`json_schema` 的 `required: ["text"]` 保持不变** —— 把 citations 设成 schema 必填会连
无数字回复一起堵死。

★ 更正:初版说"反转 `test_meta_tools.py:30-34`"是自相矛盾的 —— 该测试断言的
`schema["required"] == ["text"]` **正是本计划要保持为真的**。真正要做的是改掉第 33 行那句
已经失真的行尾注释,并**新增**一个 gate 语义层的兄弟测试。

### A0-2 关 ungated fallback ★(初版只点了一条路径,实际有两条)

- `meta_agent.py:96`:最后一轮无 tool_call 时把模型原文当答案。
- `meta_agent.py:118`:循环结束仍无合法 respond 时落 `"(no response produced)"` ——
  **这条更常见**(轮次耗在工具上、或每次 respond 都被拒)。

两条必须**收敛到同一个失败消息与同一个 marker**(`agent_messages.meta`,S2 已加列)。
配额路径**只验证不修改**:`chat_turn` 在 `agent.py:116` 于 `handle_message` 之前扣并提交,
返回 200 正是"扣费保留 + 失败留在历史里"的实现方式,符合拍板点 3。
波及面:`MessageOut`、`get_agent_session` 的投影(`agent.py:190`)、`lib/issuer.ts:31,50`、
ChatPanel 的气泡变体。

### A0-3 trail 卫生 ★(两个**不同**的洞,不许混为一谈)

1. **不对称**:`_ID_PREFIXES` 收缩为 6 —— 关闭"能 harvest 却不能引用"。
2. **伪造 id 回流**:`tool_class == GATE` 的结果一律不 harvest —— 关闭 gate 自己的报错把
   `problems[].id` 喂回 trail。

★ 两者都**不**关闭另外两条摄入路径:显式 `{type,id}` dict 分支(`registry.py:109-110`)与
`calc_id/fact_id/chunk_id` 键分支(`:112-115`)。实测证据:畸形 id `alertb41eec529430`
今天就在 trail 里,走的是 dict 分支;`risk_alerts` **35 行里有 10 行**的 id 不带下划线
(V1 遗留)。这条写进 V3_COVERAGE 作为已知残留,不在本期扩大范围。

同 commit 必须反转两个测试(前缀元组一缩它们立刻变红):
`test_tool_registry.py:33`(`('company','co_nvda') in kinds`)、
`test_portfolio_snapshot.py:74`(`('research_run','rrun_2') in kinds`)。
★ commit message 里**不要**写"prose 里提到的 id 也会被 harvest" —— 侦察实测该说法为假。

### A0-4 删死配置

见 §0.3 末行(4 处同步,`IMPLEMENTATION_PLAN.md:52` 不动)。与 B 的两个新 settings
**合并为一个 commit**:两者都改 `settings.py:34-38` 与 `test_p0_schema.py:44-47`,分开做必冲突。

### A1 — 数字↔证据确定性核对

**值来源** ★(初版此处最错):

| 前缀 | 值从哪来 |
|---|---|
| `calc_` | CalcLedger |
| `fact_` | FinancialFact |
| `run_` | ★ **ExposureRun 自己一个数值列都没有**(`models.py:151-163` 全是 id/状态/时间)。值在子表:`exposure_metrics`(组合市值等)、`issuer_exposures` / `sector_exposures`(权重)、`factor_attributions` |
| `alert_` | RiskAlert(`current_value` / `limit_value` / `utilization`,注意三者同行、量级不同) |
| `chunk_` / `src_` | ★ 初版**完全漏了这两个**,而它们在 §0.3 的六个可引用前缀里。走**引文路线**:数字必须逐字出现在被引段落文本中(`verify(numbers, values, quoted_keys)`) |

`_VALUE_SOURCES` 必须是**模块级 dict(数据),不是 if 链** —— D 的对称性测试要断言
`set(trail._RESOLVERS) <= set(_VALUE_SOURCES)`。

★ `resolve_cited_values` 返回 `tuple[list[EvidenceValue], set[str]]`,不是 `set[float]`:
裸 float 集合承载不了 `nearest.label`(给模型的收敛信号),也分不开结构化路线与引文路线。

★ **`calc_service.series()` 必须与 A1 同期落地,不能推后**:`get_fact_series` 的
派生 Q4 点(`Q4 = 年度 − Q1 − Q2 − Q3`)在任何表里都没有对应行,只携带四个输入 fact_ id,
而那四个值和 Q4 本身是**不同的数** → 结构性误拒类别。若确要推后,必须写进 V3_COVERAGE 作为
已知残留,**不得**靠放宽容差掩盖。

接入 `_respond` 与 `_submit_brief`(后者按 block 用该 block 自己的 citations)。
错误载荷带 `nearest` 候选值。

**验收**:offline 分四组(A 抽取 / B 豁免 / C 值解析 / D verify);live 用 D2 回放集测
false-rejection ≤ 2/20,超标回到拍板点 1 用数据复议。

---

## V3-B — Context 组件

**B0 计量**:`meta_agent.py:84` 之后计数,★ **必须把 `tools` 一起算进去**。
★ 落点更正:`agent_steps` **没有 meta 列**,且唯一看似能用的 `prompt_tokens` 被
`session_cost` 视图(`init.sql:584`)求和 —— 往那里写"turn 开始时的估算"会让成本视图报出
**编造的 provider 用量**。故 per-turn 数字写进 `agent_messages.meta`(S2 已加列,与 A0-2
共用,**必须合并写**),session 级写 `agent_sessions.last_prompt_tokens`。

**B1 溢出结构化拒绝**:检查插在 `agent.py:114`(409 之后)与 `:116`(扣费之前)之间,
返回 413 `{"error":"session_context_exhausted"}`,**不扣配额**。
★ **绝对不要调 `release_turn`**:检查在 `async with factory() as gate_db, gate_db.begin():`
里,抛异常即回滚 `claim_turn` 的 UPDATE —— **那就是释放**,和现有 429 完全同一个机制
(路由自己的注释 `agent.py:101-104` 写着)。显式 `release_turn` 会另开一个连接
(`agent_session_service.py:124-125`)去等 `gate_db` 还握着的行锁,产生
`agent_session_service.py:96-100` 记载的那种**测不出来的死等**,而且它吞掉所有异常 ——
症状会是静默挂起而不是报错。
★ 顺序测试用**源码索引比较法**(`test_v2_audit.py:119-138` 的既有技法):仓库里
**没有任何 HTTP 测试脚手架**(TestClient / ASGITransport / httpx.AsyncClient 零命中),
初版说的"复用 test_charge_points_live.py 做 offline mock 版"做不出来。
状态序更新为 401 → 404 → 409 → **413** → 429。

**B2 per-turn 预算**:`turn_tools_used=0` 加进 `_CLAIM_TURN_SQL` 的 SET(同一条语句,fence 不变);
★ 策略**由行携带**:`create_session` 给 meta 写 `turn_tool_budget=15`、research 写 NULL;
`reserve()` 用 `is not None` 判断走哪套,**不写 kind 分支**(§0.2)。
★ 同时必须重新定义 `tool_budget` 的 NULL 语义:现在 `session.tool_budget or settings.…`
让存进去的 `0` 等于 40。
★ **MCP 是退步不是改善,如实写进 V3_COVERAGE**:初版声称"MCP 全局 session 顺带被救活"已被
证伪 —— `claim_turn` 全仓只有一个调用者(`agent.py:112`),MCP 在 `server.py:67` 建一个
进程级 session 并在 `:92/:109` 复用,**从不 claim turn**,故 `turn_tools_used` 永不清零,
会在 **15** 次而不是 40 次上耗尽。诚实的权宜:MCP 维持终身语义,等 MCP_BOUNDARY_PLAN 给它
自己的 face。

**B3 锚定摘要**:条件项,由 B0 数据决定(< soft limit 60% 则本期关闭)。

---

## V3-C — Memory 组件

顺序 **C4 → C2 → C3 → C1 → C5**(C2 最危险故早做,C1 依赖 S2 的列)。

- **C4 `compute_combine`**:六行,把 `op` 透传进本就通用的 `calc_service.combine`。
  `TARGET_ARCHITECTURE:180` 自 M3 起就把它当已交付写着。
- **C2 `get_task_status`** ★ 全 C 最危险的一行:`Task.owner_user_id == current_user_id()`
  在**无登录用户时渲染成 `IS NULL`**,会匹配上无主的 seed task。None 必须在查询**之前**
  变成结构化拒绝。owner 过滤旁六行内必须带 `semantic, not security` 标签,否则
  `test_v2_audit.py:141-156` 直接失败。
- **C3 `get_portfolio_positions`**:在 `portfolio_service` 加**兄弟函数**(不是把 `_snapshot_one`
  改宽)。★ 与 A1 强耦合:每个 market_value / weight 必须来自该 run 的 `issuer_exposures`,
  **绝不能取 `positions.price/market_value`**,否则回答里的数字没有可引用 id、被 A1 拒 ——
  一个 memory 功能会变成 D2 回放里的误拒制造机。
  ★ 验收改写:初版的"问第 11 大持仓"**无法满足** —— `port_001` 恰好 10 个持仓而
  `_TOP_ISSUERS = 10`,没有任何东西被截断。改为"问 `get_portfolio_snapshot` 不携带的字段
  (quantity / asset_class)",那才是 C3 真正关闭的缺口。
- **C1 `read_issuer_brief`**(meta-only,见 §0.5):返回扁平 `citations`(始终有)+
  `block_citations`(S2 新列,V3 之后写的 brief 才有,老 brief 为 null —— 如实报告两个不同的
  事实,不是 fallback)。★ `brief_id` **只能作为普通字符串字段返回**,绝不可写成
  `{"type":"brief","id":...}`:那会被 `registry.py:109-110` 收进 trail,产出一个能过 trail 检查、
  却在 `_exists_in_db` 上以误导性的 `unresolved_in_db` 失败的引用。
- **C5 face 守卫**:pairs 表 + `KNOWN_TRIMMED` **按相等断言**(不是子集)以便自动过期。
  ★ 实测三个生产配对里**恰好一个**失败:`FACE_META_AGENT` × `build_read_registry`
  (`apps/mcp/server.py:39-40`),缺 `{ensure_company_ready, respond, start_exposure_run,
  start_issuer_research}`。另需交叉引用 `test_tool_registry.py:62-68` —— 它正面断言了
  C5 声称有害的那个裁剪行为。

---

## V3-D — Evals 组件

**D1 检索 golden set**:★ 先落 chunker 常量的**钉死测试**再标注数据 ——
每个 `char_start/char_end` 都是 `section_chunker.py:21-24` 四个常量的函数,常量一改
24 条标注静默失效。锚点用 `(accession, item_code, char_start, char_end)` + 指纹,
**明令禁止用 `chunk_id`**(重新 ingest 会变)。
★ 交付物是**一个 live-marked pytest**,不是 CI 门:仓库里没有 `.github`、没有任何 CI 配置。

**D2 faithfulness 回放**:★ 走 **service 层 + `app_rls` + `current_user_ctx`**,
**绝不能用 owner 角色**(`exposure` 带 `rolbypassrls`,agent 会看见全部 7 个 portfolio
包括探针账本)。★ 免费加一项:对**现存 3 份 public brief** 做 A1 重验 —— 它测的是
"A1 会拒掉多少 pre-A1 的 brief 文本",这比两份**按构造已经过了新 gate** 的新 brief
更适合当拍板点 1 的复议输入。

**D3** 用实测的 false-rejection 清单复议拍板点 1,并收口每个阶段欠 V3_COVERAGE 的诚实条目:
A1 的不可约边界(**它是存在性检查,不是正确性检查**)、B1 的"永远看不到第一轮、现实中几乎
不会触发"、B2 的 MCP 退步、C 的四个新工具额外消耗 turn 预算。
