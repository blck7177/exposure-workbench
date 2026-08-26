# Implementation Plan V8 — Skill 层第一批:产物读 + 方法工具 + 轨迹判据

> **状态(2026-08-24 更新)**:**V8-P(P1–P4 中的 P1/P2/P3)已完成并部署**(`b4064e6`、`96ac20f`)。**A–D 暂停**:boss 拍板优先上线报表类 credit/fundamental 分析(见 `IMPLEMENTATION_PLAN_V9.md`),量化产物读与归因让位。P 批的持久化保留,V9 不依赖它。P4(COUNT 扩展)随 A 批一起暂停。
> **性质**:把确定性层已算好的分析产物接到 agent 面上(产物读),把"解释涨跌"的方法冻结成一次调用(方法工具),并给 respond 门加上轨迹判据。**不动架构、不动 web、不加新 LLM 路径。**
> **一句话**:门早就认识的数字(`_RUN_CHILDREN` 里的因子 beta/贡献、逐持仓贡献),agent 终于读得到;15 步爆预算的问题变成 3 步;事故那类回答从"被劝阻"变成"被机械拒绝"。
> **上游依据**:`dev_note/portfolio-demo/analyst-skills/` 01–11(尤其 07 目录、08 批评 F1–F11、09 结论、11 组合语法)。事故复盘见 `IMPLEMENTATION_PLAN_V7.md` §11(V7-Q2)。

---

## 0. 已定决策(2026-08-23,boss 拍板 + 依调研既定)

| # | 决策 | 内容与理由 |
|---|---|---|
| **DP1** | **组合域账本原语不开**(boss 原话"先不开") | 模型面**没有**自由拼装的组合算术工具。方法工具内部照常落 calc 账(那是确定性代码记录固定方法,不是开放拼装)。跑一段后用真实问题落空率再议 |
| **DP2** | **不做数值型"个股叙事许可位"** | 08 号 note W1/Gabaix:前五大持仓占 66% 的账本上,"\|残差\|>\|最大因子\|才许讲个股"会强制得出"市场干的"且不可证伪。许可只做**顺序判据**(先读归因,再引 issuer 证据),不做量级判据 |
| **DP3** | **老 run 不回填新列** | 与 v5/v6 迁移纪律一致:回归元数据无法事后凭空断言。老 run 的产物读返回 `metadata: null` + 诚实字段("this run did not record it") |
| **DP4** | **轨迹判据的拒绝必须"弃权可达"** | V7-Q2 教训:门的拒绝**不得**要求花费已耗尽的预算才能满足。每条新拒绝都必须能靠**删掉那句话**(零工具成本)走出去,拒绝文案明说这条路 |
| **DP5** | **子行计数是 run 持有的值** | "27 checks evaluated / 3 alerts" 这类计数要能过数值门:`resolve_cited_values` 学会"cited run_ 的子表行数是它持有的 COUNT 值"。小而原则化的扩展,不是豁免 |

---

## 1. 现状基线(2026-08-23,全部实读)

| 事实 | 坐标 |
|---|---|
| `exposure_metrics` 带 `UniqueConstraint("run_id")`,16 个数值列;加列即可,无需新表 | `models.py:213-237` |
| `FactorAttributionResult` 已算 `residual`(=return−alpha−Σ贡献)与 `alpha`,但 workflow 只把 alpha 写进 `workflow_events` payload,**residual 无处持久化** | `factor_model.py:45-50,169-171` · `exposure_workflow.py:241` |
| `FactorAttribution` 行在 `exposure_workflow.py:788` 写入,含 `factor_ticker` | 同左 |
| `stress.py` 已算 `factors_held_flat`(:116)与 `unevaluated`(:86-129),**只进 payload_summary**(:279),行级无 | `analytics/stress.py` |
| `check_limits` 返回 `(alerts, evaluated)`,`evaluated: list[str]` 从不落库 | `analytics/limits.py:230-236` |
| **`_RUN_CHILDREN` 已能解析** `FactorAttribution.{beta,factor_return,contribution,r_squared}` 与 `IssuerExposure.contribution` —— 门认识、agent 读不到 | `numeric_verification.py:444-465` |
| `_CALC_RATIO_OPS` 是 calc 值被判为 RATIO 的白名单;方法工具的新 operation 必须注册,否则被判 MONEY、门拒自己产的比值 | `numeric_verification.py:437` |
| respond 门 = `meta_tools._respond`(:152-218):引用存在性 → 数值核对 → 零引用带数字拒。轨迹判据挂在这里,`responded:True` 之前 | `tools/meta_tools.py` |
| `_respond` 拿得到 `db` 与 `current_session_id()`,**拿不到 message_id**(只在 `invoke()` 的参数里) | `registry.py:163-171` |
| `calc_service._record` 的 `company_ticker: str \| None` 可空,`input_refs` 是字符串列表 → `["run_…"]` 合法 | `calc_service.py:146-155` |
| faces:`FACE_META_AGENT = READ_CORE + META_ONLY_READS + [delegations, respond]`;`resolve()` 严格,漏注册=构建错误 | `faces.py:53-55` |
| 迁移现有 v2…v6(V7 无迁移),三份 schema 同步纪律(init.sql / models.py / migration)+ parity 测试在 | `infra/migrations/` |
| 工具 schema 守卫从函数签名推导(V3 P1.2),新工具自动被盖 | `tests/`(既有) |

---

## 2. 排程(单 lane 顺序执行;每阶段独立可合并)

```
V8-P 持久化(0.5–1d)   P1 回归元数据入列 → P2 stress_results 表 → P3 limit_checks 表 → P4 COUNT 扩展
V8-A 产物读(0.5–1d)   A1 get_attribution · A2 get_risk_state · A3 list_run_alerts + list_risk_limits · A4 get_run_freshness
V8-B 方法工具(0.5d)    B1 reconcile_move
V8-C 判据+提示(0.5–1d) C1 message ctxvar → C2 两条轨迹判据 → C3 _SYSTEM 更新 → C4 事故回归验收
V8-D 回撤取证(~1d,可独立后置) D1 episode 检测 → D2 两个工具
```

每步纪律照旧:**先红后绿**(复现/缺失先固化成失败测试);**三份 schema 一起改**并跑 parity;offline 全绿 + live 增量 → commit。

---

## 3. V8-P — 持久化:让已算出的东西变成行

**P1 回归元数据入 `exposure_metrics`**(加列,不加表)
新列:`alpha`、`residual`、`model_r_squared`、`observations`、`regression_window_days`、`max_vif`、`collinear`(bool)、`attribution_date`。
- 写入点:`exposure_workflow.py` 归因步(数据全在 `factor_result` 手里,现在只进 payload)。
- `_RUN_CHILDREN`:`alpha/residual/model_r_squared/max_vif` 进 RATIO 组;`observations/regression_window_days` 是 COUNT——**依赖 P4**,P4 未落地前先不进解析(数字仍可由 A1 的 payload 呈现但答案里引用会被拒,这是诚实的中间态,不是洞)。
- 三份同落:`models.py` + `infra/init.sql` + `infra/migrations/v8_skill_reads.sql`(幂等,`ADD COLUMN IF NOT EXISTS`)。
- 验收:offline 形状测试;live 重跑 demo 书一次 → 新列非空;引用 `run_` 陈述 alpha 过数值门。老 run 新列 NULL,读侧按 DP3 呈现。

**P2 `stress_results` 表**(run 子表)
列:`id/run_id(FK CASCADE)/scenario/description/shocks JSONB/loss_pct/loss_usd/factors_held_flat JSONB/status('evaluated'|'unevaluated')/reason`。
- RLS:与 `issuer_exposures` 同款 tenant 策略(EXISTS run JOIN portfolio),init.sql 与 migration 同落,`test_rls_parity` 盖到。
- `_RUN_CHILDREN` 增 `(StressResult, ("loss_usd",), ("loss_pct",), "scenario")`。
- workflow 压力步写行;**payload_summary 保留不删**(U4 的 UI 在读它;行是给引用门的,俩消费者俩载体,注释写明)。
- 验收:live 重跑后行数 = 情景数;`unevaluated` 的行 `loss_pct IS NULL` 且 `reason` 非空——**未评估不得以 0 出现**是列约束(CHECK:status='unevaluated' ⇒ loss_pct IS NULL)。

**P3 `limit_checks` 表**(run 子表)
列:`run_id/limit_type/fired bool/alert_id nullable`。workflow 限额步把 `evaluated` 落行(fired 者关联 alert_id)。RLS 同 P2。
- 验收:行数 = evaluated 长度;fired 行的 alert_id 指向真 alert。

**P4 COUNT 扩展(DP5)**
`resolve_cited_values(db, ids)` 对 `run_` 增发 COUNT 值:每个子表的行数(alerts、stress evaluated/unevaluated、limit_checks fired/not-fired、issuer_exposures)。实现处与 `_RUN_CHILDREN` 同文件,机制对齐既有 COUNT 类(quality_flags 的 `_numbers_in` 已有 COUNT 前例)。
- 先红:live 测试——回答"you have 3 alerts"引用 `run_`,当前被拒;P4 后通过,且行数不符时仍拒。
- **边界写死**:只数直接子表,不做任意聚合——这不是组合算术的后门(DP1),枚举写在代码里。

---

## 4. V8-A — 产物读(四个,全部 READ 类、META_ONLY_READS)

**A1 `get_attribution(run_id)`**
返回:因子行**全集**(beta/factor_return/contribution/r_squared/**factor_ticker**)+ 逐持仓 contribution **全集** + `daily_return/daily_pnl/as_of` + P1 元数据(或 `metadata: null`)。
- **schema 里没有 top_k / limit 参数**,并有一条测试断言这个"没有"(top-k 正是让答案只点两个名字的东西)。
- 每个 beta 以结构出现:`{factor_name, factor_ticker, beta, quotable_individually}`——`quotable_individually = not collinear`,把 `factor_model.py` docstring 里"和可引、单个不可引"的论证变成返回字段。
- 验收:offline 形状+守卫;live 引用 `run_` 陈述 MSFT contribution 过门;`collinear=true` 的 run 上单 beta 结构可见但标记为不可单独引用。

**A2 `get_risk_state(run_id)`**
返回:`exposure_metrics` 全 16+新列(尾部指标包成 `{value, measure, confidence, horizon_days, observations, lookback_days}` 结构,payload **造不出裸 VaR**)+ P2 的全部情景(含 `factors_held_flat`、unevaluated 原样)+ 该 run 告警(带 `limit_value/utilization`)+ 字面 `not_a_forecast: true`。

**A3 `list_run_alerts(run_id)` + `list_risk_limits(portfolio_id)`**
薄读。alert 整单元返回(current/limit/utilization 同行),并附**预格式化 utilization 句**(`"AAPL concentration: 15.8% vs limit 15.0% — 79.2% would be wrong, utilization is current/limit"` 之类由代码拼好)——V3 语料里 0.158/0.15/0.792 同行三值、门无法辨句义的已知陷阱,防在生成侧。

**A4 `get_run_freshness(portfolio_id)`**
返回:最新完成 run 的 `as_of` / 最新市场 session 日 / 落后 session 数 / 是否有 run 在途。零新计算(`positions_with_weights` 已示范过两日期分离的诚实口径)。

**A 批公共验收**:新工具全部进 `FACE_META_AGENT`(resolve 严格,漏了构建即红);签名推导守卫自动覆盖;`pytest -m live` 对着真 run 全绿。

---

## 5. V8-B — 方法工具 `reconcile_move(run_id)`

一次调用,内部完成(全部可测,删任何一步有测试红):
1. 取因子与持仓贡献**全集**(复用 A1 的服务层,不复制查询);
2. **恒等式 A**(精确):Σ issuer contribution vs `daily_return`,容差=写法精度半 ulp 族(V3 判据);**不成立 ⇒ `reconciles:false` 且份额字段在返回 dataclass 里不存在**(不是 null,是构造不出——数据缺陷不是叙事素材);
3. **恒等式 B**(命名残差):`unexplained = daily_return − Σ factor_contribution`,字段名**必须**是 `alpha_plus_residual`(测试断言字面名;禁止叫 specific_return——本系统无个股特异收益,08 号 note 判过);
4. 落**一条** calc 账:operation `portfolio.reconcile`,`input_refs=["run_…"]`,**注册进 `_CALC_RATIO_OPS`**(漏注册=门拒自己产的比值并归罪模型,基线里已点名);
5. 返回:两个恒等式结果、`largest_factor`、`largest_issuer_contribution`、窗口与观测数——**不含任何"许可位"**(DP2)。

系统性 vs 个股的**措辞**判断留给 prompt(C3);数字与命名全部在这。

---

## 6. V8-C — 轨迹判据 + 提示 + 事故回归

**C1 message ctxvar**:`registry.invoke()` 已接 `message_id`,增设 `_message_ctx`(与 `_session_ctx` 同款),`_respond` 由此取到本 message 的 steps 范围。

**C2 两条轨迹判据**(挂在 `_respond`,`responded:True` 之前;**每条拒绝按 DP4 自带零成本出路**):
- **R1 顺序**:本 message 内若答案引用了任何 `chunk_/src_`(issuer T 的),则必须存在**更早完成**的步,其结果含 T 的 contribution(get_attribution / reconcile_move / snapshot 均可满足)。拒绝文案:"drop the filing-based claim for T, or read T's contribution first"——删句即出,零工具成本。
- **R2 委派节制**:本 message 内 `start_issuer_research` 完成步 >2 时,respond 文案必须列出全部已入队 run id(已入队是事实,不追溯拒绝;这条防的是"入队了 6 个然后只字不提")。
- 两条都是 `agent_steps` 上的 SQL,各带正反测试(违规被拒/合规通过/**预算耗尽时仍可经删句退出**——最后这条是 V7-Q2 的镜像测试,必须有)。

**C3 `_SYSTEM` 更新**(≤6 句增量):"为什么涨跌"类问题先 `get_attribution`/`reconcile_move` 再考虑 issuer;Item 1A 是长期披露不是当日原因;数字随窗口与观测数一起说。措辞 diff 在 review 时给 boss 过目(既有纪律)。

**C4 事故回归验收(本批的定义性验收)**:live 重放原问题 *"why there is large drawdowns? do some research and explain"*——
- 工具调用 ≤ 5(原 15);
- 回答含市场因子贡献且引用过门;
- 无未经 R1 的 issuer 因果句;
- 数值门零拒绝重试或 ≤1 次;
- 若模型仍措辞跑偏,记录原文进 plan §实测——**提示层的失败如实记,不用代码补**(no-fallback)。

---

## 7. V8-D — 回撤取证(可独立后置,不阻塞 P/A/B/C)

**D1 `analytics/drawdown.py`**:episode 检测(峰日/谷日/深度/恢复日或 none),输入复用 `build_portfolio_returns`(现在算完即弃);SPY 同窗收益走既有 `window_return` calc。
**D2 工具**:`get_drawdown_episodes(portfolio_id, span)` + `explain_episode(portfolio_id, peak, trough)`。
**硬约束(从 08/09 号 note 判定,写进代码不写进提示)**:
- **不提供**回撤深度的加性分解(路径依赖、窗口内生——数学上不存在);
- episode 解释 = 固定窗口累计收益 + 同窗基准 + 逐持仓窗口贡献(定量重估两端),`fixed_quantities` caveat 是返回结构必带字段;
- **禁止**逐日因子贡献跨期相加(滚动 beta 上数学非法)——explain_episode 根本不返回该形状。
验收:构造已知路径的单测(峰谷正确、深度不可分解的断言=API 里没有那个字段);live 对 demo 书 3 年窗口跑一次,episode 与 `max_drawdown=17.66%` 对得上。

---

## 8. 风险与退路

- **P 批动活库 schema**:全部幂等 ADD/CREATE IF NOT EXISTS;迁移先于新代码(PRODUCTION.md 既定顺序:postgres 单独起→migrate→其余);任何失败回滚=不部署新镜像,老代码不读新列。
- **R1 可能误伤多轮对话**(上一轮读过 contribution、这一轮引用):判据按 message 计,首版收紧;若 live 验收中误伤真实对话,放宽到 session 计并记录理由——**方向只许从紧到松且必须留档**。
- **C2 新拒绝的死锁风险**:DP4 镜像测试强制"删句可出";review 时专项对抗这条。
- **`_CALC_RATIO_OPS` 漏注册**:P/B 各有一条"门拒自产值"的先红测试盯着。
- **本批不动的**(明确出范围):web/UI、`what_if` 假想 run、组合级能力地图、`assumption_/limitation_` 可引用对象、检索类 skill(需 8-K/新闻数据,L0 未到)、异步 join——最后两条是架构级待议,记在 BOARD 不混进本批。

## 9. 收尾

全批完成后:`docs/spikes/V8_COVERAGE.md`(数字口径同 V2/V3)、MODULE_NOTES 新节、BOARD 更新。对抗式 review 照惯例做,**派 agent 前先问 boss**(既定纪律)。
