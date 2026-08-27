# Implementation Plan V10 — 收敛批:一种取数、一种算、一条路

> **状态(2026-08-27 起草,待 boss 拍板)**:未开工。本文是 boss「先收敛,不再加功能」指示下的第一批,范围只有一组:**V3 时代的序列原语(`get_fact_series` + 四个 `compute_*`)与 V9 的区间原语并轨**。其余重复(run 切片合并、告警三切法)登记在 §8,本批不动。
> **性质**:减法。工具面 36 → **31**,`period_ladder` 整个模块删除,`calc_service` 的序列装载删除。**不新增任何分析能力**——本批结束时模型能回答的问题集合与现在完全相同,只是每个问题只剩一条路。
> **一句话**:V9 把"取一个窗口"做对了但没做"取一串窗口";V3 有"一串"但窗口是错的枚举。把"一串"建在 V9 的窗口上,然后把 V3 删掉。
> **上游依据**:`docs/IMPLEMENTATION_PLAN_V9.md` §0 诊断与 §"本批不动"里的「quarterly ladder 整体迁移(A6 只做 Q4 parity)」;`tests/test_v9_q4_parity_live.py`(290/290);2026-08-27 工具集正交性分析(topic 日志)。

---

## 0. 诊断:为什么是"并轨"而不是"删 V3"

起草前我说过一句「V3 能做的每件事 V9 都能做」。**对着代码核,这句是错的**,而且错在关键处:

| | V3(`calc_service.load_fact_series` → `period_ladder`) | V9(`fundamentals_service.get_flow` → `interval_algebra`) |
|---|---|---|
| 一次返回 | **N 个期间**的阶梯(`SeriesPoint[]`,含推导 Q4) | **一个**窗口(`Derived`) |
| 窗口来源 | `classify_duration` 折成 {quarterly, annual, instant} 枚举;**H1/9M 被丢弃**(`period_ladder.py:72-85`) | 任意 `[start,end]`,边界图上的带符号路径;H1/9M 是路径的一部分 |
| Q4 | `derive_q4` 特例(FY − Q1−Q2−Q3) | 就是一个窗口(常为 FY − 9M);A6 证明 290/290 逐点相同 |
| 余额(instant) | `period_type=instant` 给一个余额**随时间**的序列 | `get_balance_sheet(at)` 给**一个日期**上的所有余额 |
| 真实使用 | `get_fact_series` 84 次、`compute_change(yoy)` 74 次,`last_n` 4/6/8 占 113 次 —— **问的是"最近几个季度的趋势"** | 0 次(8/27 才上线) |

所以 V9 缺的是**序列维度**,V3 缺的是**正确的窗口**。两者并存的代价不是"多几个工具":同一个"毛利率"有三条路(`compute_ratio` / `evaluate_formula` / `calculate`),前一条会放行后两条拒绝的错误组合(跨时刻相加、包含边重复计入),而它是模型今天实际在走的那条。

**还有一个不在工具面上的消费者**:`services/recipe.py`(issuer 页 Financials tab,经 `readiness_workflow.py:123`)直接调 `cs.change` / `cs.combine`。删 V3 序列装载 = 迁 recipe。

---

## 1. 已定决策

| # | 决策 | 理由 |
|---|---|---|
| **DP1** | **序列 = 连续窗口**。一个季度序列是 `[a₀,a₁],[a₁,a₂],…` 各自经 `ia.derive` 得到,锚点来自语料自己的期末日(`_boundary_map`),不是日历 | 一种窗口语义。推导 Q4 不再是特例;一个只报 H1 与 FY 的年份得到 H1 与 H2 两点,而不是被整年丢掉 |
| **DP2** | **不可达的点报"缺"不报"短"** | V9 既定:九个月的数当一年报是这次设计要消灭的静默约定切换。序列里的洞是 `{"end":…, "unreachable": reason}`,不是跳过后把下一个点标错 |
| **DP3** | **旧路径整体删除,不置空、不 feature-flag** | V2-H4 教训:半切换不可见。`period_ladder.py` 删,`calc_service.load_fact_series/series/change/combine/stat` 删,五个工具删 |
| **DP4** | **迁移前先 parity,parity 是"新 ⊇ 旧"不是"新 = 旧"** | 旧路径丢弃 H1/9M-only 年份,新路径会给出旧路径没有的点。断言:凡旧有的点新必有且值相同(A6 容差);新多出的点逐条列举并核对来源 |
| **DP5** | **序列运算的词表是两代的并集,一个工具** | `compute_change` 的 {yoy,qoq,pct,abs} 与 `compute_stat` 的 {cagr,avg,min,max,std,sum,latest} 合成 `series_stat(series_id, op)`。真实使用 yoy 74 / latest 4 / qoq 2 / abs 1,**没有一个 op 可以删** |
| **DP6** | **`calculate` 学会序列,按窗口末日对齐** | 对齐规则沿用 `series_ops.combine_series`(它是唯一定义过"两串怎么对齐"的地方);跨 ticker 允许(它今天已经允许);类型检查不变 |
| **DP7** | **`_SYSTEM` 与工具 description 措辞给 boss 过目**(既有纪律) | 本批删的是模型今天在走的路,提示词必须同步 |

---

## 2. 现状基线(2026-08-27,全部实读)

| 事实 | 坐标 |
|---|---|
| 序列装载:`load_fact_series` 建 ladder,quarterly 时另建 annual 再 `derive_q4`;`last_n` 截尾;上限 40 | `calc_service.py:60-127` |
| `SeriesPoint{period_end, value, input_fact_ids, quality_flags}`;`_series_payload` 写 `points[]` | `series_ops.py:33`,`calc_service.py:173` |
| 门读 calc 的 `points[*].value` 与 `value`;op 名决定单位(`_CALC_RATIO_OPS`);多键结果走 `_CALC_RESULT_KEYS` | `numeric_verification.py:_from_calc`,`:437-`,`:445-` |
| 区间引擎:`FlowFact{fact_id,period_start,period_end,value,filing_date,source_accession}`;`derive(facts,start,end)`;`latest_window(facts,months)`;`_boundary_map`;重述用 `pl.restatement_key`(**A6 抽出共用的**——删 ladder 时这个函数要搬家) | `interval_algebra.py:49-100, 113, 142, 219`;`period_ladder.py:87` |
| `get_flow` 只在 `SUPPORTED_METRICS` 内取 `_flow_facts`;`get_balance_sheet` 一个 `at` | `fundamentals_service.py:65-118, 119-` |
| 类型计算器:`_resolve(ref)` 认 fact_/calc_;`_check` 四条拒绝;`_result_type` 同窗口保留区间 | `typed_calculator.py:73,127,183,209` |
| recipe 调 `cs.change(yoy)` ×4、`cs.combine(divide)` ×4、`cs.combine(sub)` ×2;结果进 calc_ledger `invoked_by="recipe"` | `recipe.py:71-107` |
| Financials 路由按 `operation:params.series.metric` 取每 op 最新一行 | `apps/api/routes/issuers.py:81-96` |
| Web issuer 页对 calc 行**泛型渲染**(不引用具体 op 名) | `apps/web/app/issuer/[ticker]/page.tsx`(grep 无命中) |
| `get_issuer_snapshot` = `_resolve_company` + `cs.list_available_metrics`;`list_available_data` = 后者单独 | `tools/definitions.py:_get_issuer_snapshot / _list_available_data` |
| `compute_ratio` = `compute_combine(op="divide")`,docstring 自认 | `tools/definitions.py:_compute_combine` |
| 五个 V3 工具在 43 处测试引用 / 9 个文件 | `grep -rn` tests/ |
| A6 parity:全语料每个有推导 Q4 的 (issuer, metric) 对,容差=年值的半个 bp | `tests/test_v9_q4_parity_live.py` |
| `get_market_stats` 用 `date.today()`、只查 `market_prices`(V5 修 recipe 时漏了工具);`_benchmark_series` 的选表规则在 `drawdown_service.py` | `tools/definitions.py:_get_market_stats`;`drawdown_service.py:_benchmark_series` |

---

## 3. 目标词表(issuer 数字面)

```
定位   describe_issuer(ticker)                     ← get_issuer_snapshot + list_available_data + list_formulas(可算的那些)
取     get_flow(ticker, metric, months?, start?, end?, last_n?)   ← + get_fact_series(quarterly/annual)
       get_balance_sheet(ticker, at?)              (不变)
       get_balance_series(ticker, metric, last_n?) ← get_fact_series(instant)
算     calculate(op, a, b)                          ← + compute_ratio + compute_combine(序列对齐)
       series_stat(series_id, op)                   ← compute_change + compute_stat
       evaluate_formula(ticker, name, months?, at?) (不变)
       get_fundamental_panel(ticker, months?, at?)  (不变)
```

8 个,替换 13 个(`get_issuer_snapshot list_available_data get_fact_series compute_change compute_ratio compute_combine compute_stat get_flow get_balance_sheet calculate list_formulas evaluate_formula get_fundamental_panel`)。面:meta 34 → **29**,research 20 → **15**。

**`last_n` 的语义**:`get_flow(months=3, last_n=8)` = 以最近可推导的季末为终点,向前 8 个连续 3 个月窗口。`months=12, last_n=5` = 5 个连续年度窗口。默认 `last_n=1` 保持今天 `get_flow` 的行为不变。

**成本对照**(会话预算 15/轮):"最近 8 季 yoy 趋势" 旧 = 1 次(`compute_change`),新 = 2 次(`get_flow` + `series_stat`)。"毛利率 8 季" 旧 = 1(`compute_ratio`),新 = 3(两次 `get_flow` + `calculate`)或 1(`evaluate_formula(gross_margin)` 只给最新窗口)。**多出的调用换来的是**:每个点带 `basis`、每个组合过类型检查、Q4 不再是特例。可接受;若 live 中真实问句撞预算,记录后再议(不预先加参数)。

---

## 4. 排程(单 lane;每步 offline 全绿 + live 增量 → commit)

```
S1 序列引擎 + parity(0.5d)   ia.consecutive_windows → 先红 parity test(新 ⊇ 旧,全语料)→ 绿
S2 新工具面(0.5d)            get_flow(last_n) · get_balance_series · series_stat · calculate 序列对齐 · describe_issuer
S3 recipe 迁移(0.3d)         recipe → 新原语;Financials 路由 key;issuer 页行数 parity
S4 删除(0.3d)                period_ladder.py · calc_service 序列路径 · 五工具 + 两定位工具 · 43 处测试改写
S5 提示 + 文档 + 终验(0.4d)  _SYSTEM(过目)· M18 · TARGET_ARCHITECTURE §M3 表 · V10_COVERAGE
旁支(与 S2 并)              get_market_stats 用服务端日期 + 选表规则搬进 market_data_service
```

约 2 天。

---

## 5. 各步

### S1 序列引擎

`interval_algebra.consecutive_windows(facts, months, last_n, end=None) -> list[Window]`
- 锚点 = `_boundary_map(facts)` 的键(语料自己的期末日),从 `end`(默认最新可达期末)向前按 `months` 找最近锚点(`_snap`,沿用既有容差),得到 `last_n+1` 个锚点,相邻两两 `derive`。
- 每个元素是 `Derived` 或 `Unreachable`(DP2)。序列本身不做任何"填"。
- **先红**:`tests/test_v10_series_parity_live.py` —— 对全语料每个 `(issuer, metric)` 对,旧 `load_fact_series(quarterly, 40)` 的每个点在新 `consecutive_windows(months=3, last_n=40)` 中**按 period_end 必须存在且值在 A6 容差内**;annual 同理(months=12)。新多出的点**逐条打印**(期望全部是 H1/9M-only 年份)并在 coverage 里列举。函数不存在 → 红。
- 也把 `restatement_key` 从 `period_ladder` 搬进 `interval_algebra`(它是 A6 抽出共用的,ladder 删掉后它得有家)。

### S2 新工具面

- `get_flow` 加 `last_n?`(schema `{"type":["integer","null"],"minimum":1,"maximum":40}`,V3 那条 `_LAST_N` 的教训原样继承:0/负数都要拒)。`last_n>1` 时返回 `{"calc_id", "points":[{"start","end","value","terms","derivation"} | {"end","unreachable"}], "basis"}`,ledger op `flow.series`。**`points[*].value` 形状与旧 `series` 一致**,`_from_calc` 不用改;`flow.series` 进 `_CALC_RATIO_OPS`?——不,它是 MONEY(跟 `derive.interval` 一样);只有比值 op 进。
- `get_balance_series(ticker, metric, last_n?)`:instant 事实按 `period_end` 排序取最近 `last_n`,**不推导、不对齐、不填**;每点带 fact_id;ledger op `balance.series`。
- `series_stat(series_id, op)`:op ∈ {yoy, qoq, pct, abs, cagr, avg, min, max, std, sum, latest}。前四个返回序列(`change.*` op 名沿用,已在 `_CALC_RATIO_OPS`),后七个返回标量(`stat.*`)。实现直接复用 `series_ops.compute_change/compute_stat`(它们吃 `SeriesPoint[]`,不认识 ladder);输入序列从 calc 行的 `points` 重建。**yoy 的"上一年同期"用窗口 end 回退 12 个月 `_snap`**——不用列表位置(P9 的 2808% 教训)。
- `calculate`:`_resolve` 认得 `flow.series`/`balance.series`/`change.*` 的 calc 行为"序列型";两个序列按 end 对齐(`combine_series` 规则);序列 × 标量广播;结果 op 名 `calc.series.<op>`,单位规则同标量。`_check` 四条拒绝对序列**逐点**适用(任何一点被拒整体拒,说明是哪一点)。
- `describe_issuer(ticker)`:`_resolve_company` + `list_available_metrics` + `FORMULAS` 里**输入齐全**的那些名字(不齐的列出缺什么)。`list_formulas` 的无 ticker 形态并入:`describe_issuer` 不带 ticker 时只返回公式表——不,一个工具一种形状;`list_formulas` 保留但**移出 READ_CORE 进 panel 的 description 里提及**?——决定:**删**,公式表进 `describe_issuer` 的 `formulas` 字段(每家都一样的 16 条,每次多几百 token,换掉一个工具)。
- 守卫:签名推导守卫自动盖;`_CALC_RESULT_KEYS`/`_CALC_RATIO_OPS` 新 op 名各加一条"门收自产值"的 live 断言(V8-B 那个坑)。

### S3 recipe 迁移

- `recipe.py` 的 `q(metric)`/`bal(metric)` 改为 `get_flow(months=3,last_n=…)`/`get_balance_series`,`cs.change(yoy)` → `series_stat(yoy)`,`cs.combine` → `calculate`。RECIPE_VERSION → v2。
- `issuers.py:93` 的 key 改成从新 params 取 metric(`params.metric` / `params.a.metric`)。
- **验收**:对 8 家 issuer 跑一次 readiness,Financials 路由返回的 `(operation, metric)` 集合与迁移前**逐项对照**,差异列举(期望:`cash_to_long_term_debt` 这类 V9 已改名的行按新名出现)。

### S4 删除

- `period_ladder.py` 整个删(先 grep 确认 `restatement_key` 已搬、`classify_duration` 无其他消费者)。
- `calc_service`:`SeriesSpec`、`load_fact_series`、`series`、`change`、`combine`、`stat`、`MAX_SERIES_POINTS` 删;`window_return`、`_record`、`list_available_metrics`、`load_price_series` 留。
- `definitions.py`:七个工具注册与 fn 删;`_spec`、`_LAST_N` 删(教训搬进新 schema 的注释)。
- `faces.py`:READ_CORE 更新。**`resolve()` 严格,漏改 = 构建即红**。
- 43 处测试:按语义改写到新工具(不是删测试——每条测试守的性质要有新家),数字进 commit message。
- `test_v2_audit`/AST 守卫/`test_faces_strict` 自动盖新面。

### S5 提示与文档

- `_SYSTEM` 第四段(REPORTED FINANCIALS)改写:去掉 `compute_*`/`get_fact_series` 的隐含依赖,加"趋势用 `get_flow(last_n)` + `series_stat`"。**diff 给 boss**。
- `MODULE_NOTES` M3 节标注"由 M18 取代"、新 M18;`TARGET_ARCHITECTURE` §M3 表(`:203-204`)改词表;`MCP_PLAN` 工具计数;README 工具面数字。
- `docs/spikes/V10_COVERAGE.md`:parity 数字(旧点数 / 新点数 / 新多出的点及来源)、Financials 行数对照、面 36→31、测试数。

### 旁支(与 S2 并行,独立 commit)

`get_market_stats`:`date.today()` → `market_data_service.latest_session_date`(V5 已给 recipe 修过的同一件事);选表规则从 `drawdown_service._benchmark_series` 搬到 `market_data_service.price_points(db, ticker, start, end)`,`explain_episode` 与 `cs.window_return` 都改调它。这样"两张价格表"的规则**只在一处**——不是统一表(那是迁移),是统一读法。

---

## 6. 验收(本批的定义性判据)

1. **parity**:旧 quarterly/annual 序列的每个点在新序列中存在且值相同(A6 容差),全语料零例外;新多出的点全部可解释为 H1/9M-only 年份。
2. **问题集合不变**:V9_ACCEPTANCE 六题 + V8 C4 问句 + 下面三句**真实用户问过的**(`agent_messages` 里取)在新面上 live 重放,每句工具调用 ≤ 旧 + 2,回答过全部门:
   - "NVDA 最近 4 个季度的收入增长"(`get_fact_series`+`compute_change` 的典型)
   - "AAPL 的毛利率趋势"(`compute_ratio` 的典型)
   - "MSFT 现金和长期债务"(`period_type=instant` 的典型)
3. **零路径残留**:`grep -rn "period_ladder\|load_fact_series\|compute_ratio" src apps` 为空;`resolve()` 两个面通过;工具面 31。
4. **Financials tab**:8 家 issuer 行数与迁移前对照表在 coverage 里。
5. **1060 offline / 208 live 不减**(改写后数字进 commit)。

---

## 7. 风险与退路

- **parity 找到真差异**(旧 ladder 某点新引擎给不出):不放宽容差、不跳过——那是引擎或 ladder 之一错了,与 A6 同款处置(A6 第一次跑 7/290 不一致,根因是重述取舍,修在共用处)。
- **预算**:新面上典型趋势问句从 1 次变 2–3 次。15/轮的预算不动;若 live 重放撞上,记录原句进 coverage,**不加"一次给全"的便利参数**(那是 V9-F 第一版被叫停的形状)。
- **`calculate` 序列对齐的语义**:两串窗口末日不重合(一家 3/31 一家 3/28)靠 `_snap` 容差;容差之外报 `misaligned` 拒绝并列出两边的日期,**不做最近邻**。
- **删 `period_ladder` 时 `restatement_key` 的搬家**:A6 parity 测试直接 import `pl.restatement_key`,S1 就得改它——先搬再删,parity 一直绿。
- **recipe 是 UI 的数据源**:S3 先在本机栈验 Financials tab 再 commit;迁移期间旧 calc 行仍在 ledger(append-only),路由按最新一行取,不会出现空 tab。

## 8. 本批不动、登记待议

- **run 三切片合并**(`get_attribution`/`get_risk_state`/`list_run_alerts` → `get_run`):我 8/27 按 V8 计划写的,"分开省 payload"在 10 持仓上不成立。独立小批。
- **告警三切法**:`list_alerts(ticker)` 跨 run 跨组合取 20 条,多用户下把 demo 与用户书混在一起。要么按"可见组合的最新 run"限定,要么删掉让模型走 `get_portfolio_snapshot().alerts`。独立小批。
- **两张价格表统一**:本批只统一读法(旁支),不迁表。
- **五个多概念指标拆分**、**包含边三族**、**8-K/新闻 ingest**、**同业**:V9 遗留,不属收敛。
