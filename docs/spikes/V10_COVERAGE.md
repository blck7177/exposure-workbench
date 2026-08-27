# V10 验收 — 收敛批:一种取数、一种算、一条路

> 2026-08-27。**1039 offline / 211 live 全绿**(批前 1095/211;offline 差额 = 随 `period_ladder`/`combine_series` 退役的两文件测试)。四镜像重建上线,站点 200,bundle 内 `localhost:8103` 零次。
> 计划 `docs/IMPLEMENTATION_PLAN_V10.md`(§0 诊断),笔记 MODULE_NOTES §M18。**本批不新增任何分析能力**。

---

## 1. 面:36 → 31

| | 删 | 增 | 净 |
|---|---|---|---|
| 定位 | `get_issuer_snapshot` `list_available_data` `list_formulas` | `describe_issuer` | −2 |
| 取 | `get_fact_series` | `get_flow(last_n)`(扩) `get_balance_series` | 0 |
| 算 | `compute_change` `compute_ratio` `compute_combine` `compute_stat` | `series_stat`;`calculate` 升到序列 | −3 |
| **合计** | 8 | 3 | **−5**(meta 34→31,research 20→17) |

计划写的是 29/15:它从 V8 前的面数起算,漏了 V8-A…D 加的 5 个 meta-only。

产品代码删除:`analytics/period_ladder.py`(整个)、`calc_service` 的 `SeriesSpec/load_fact_series/series/change/combine/stat/MAX_SERIES_POINTS`、`series_ops.combine_series`。`grep -rn "period_ladder\|load_fact_series\|compute_ratio" src apps` 为空。

## 2. parity(DP4:新 ⊇ 旧)

`tests/test_v10_series_parity_live.py`,全语料每个有 flow 事实的 (issuer, metric):

| 序列 | 旧 ladder 点 | 新序列复现 | 新多出 |
|---|---|---|---|
| 季度(months=3) | 1439 | **1439/1439** | 252 个窗口,19 组 (issuer, metric),**全部是 2 项推导**——AAPL/GOOGL/JPM/LLY/NVDA/XOM 的 capex、operating_cash_flow、D&A、interest_paid,即累计申报者的 H1−Q1、9M−H1 |
| 年度(months=12) | 484 | **484/484** | 0 |

容差 = A6 的(年值的半个 bp)。A6 自己的 290/290 继续绿(ladder 冻结为 `tests/legacy_ladder.py`,只有这两个 parity 测试 import 它)。

**parity 逼出的两条设计**(第一版都不对):
- 序列**有相位**,相位是发行人的:从 `latest_window` 的 end 起步,AAPL 年度序列是一串 6 月 TTM,484 点缺 420。`_series_end` 取该长度原生报告期的期末对齐。
- 缺边界**走法不停**:NVDA FY2023 capex 只有 9M+FY,第一版停在 2022-10,FY2022 四个已申报季度永远够不着。现在留 Unreachable 槽继续走、再对齐。

## 3. recipe(Financials tab)

8 家 issuer 实跑 v2。v1 基线只有 AAPL/NVDA 两家有(其余六家从未跑过 v1 recipe)。

**AAPL 两代共有 77 点逐点相同**;v2 更多:ocf yoy 8 vs 5、fcf 12 vs 6。

| issuer | v2 行 | 可用 | 不可用原因 |
|---|---|---|---|
| AAPL / MSFT | 16 | 16 | — |
| AMZN / GOOGL | 17 | 16 | 不报 `gross_profit` |
| XOM | 17 | 12 | 不报 operating_income / gross_profit / cost_of_revenue / long_term_debt_noncurrent |
| NVDA | 17 | 12 | `revenue` 无 3 月窗口(见下) |
| LLY | 17 | 10 | `revenue` 不报(报 total_revenues);**fcf `misaligned_series`**——capex 事实止于 2022-09,与 ocf 零重叠,**正确的拒绝**(v1 会给空序列带 calc_id) |
| JPM | 17 | 8 | 银行:无 revenue/capex/current_assets 等 |

**既存、非本批**:NVDA `revenue` 的 v1 行是 7/24 的,早于 V9-M1 把 NVDA 2022 后收入拆到 `total_revenues`——今天 v1 路径同样取不到。recipe 硬编码 `revenue` 而 V9 公式表有具名替代。待议。

## 4. 问题集合不变(§6.2):真实问句在新面上重放

经真实 chat loop(`sess_*`,dev 账户),全部过门:

| 问句 | 工具 | 调用 | 回答要点 |
|---|---|---|---|
| What was NVDA revenue last quarter? | describe → get_flow ×2 | 3 | $81.615B,2026-01-26..2026-04-26 |
| NVDA revenue growth over the last 4 quarters | describe → get_flow ×2 → series_stat | 4 | 选了 `revenue`(止于 2022)而非 `total_revenues`,答案如实写明窗口——见 §6 |
| AAPL gross margin trend over the last 2 years | describe → get_flow ×2 → series_stat → calculate → series_stat | 6 | 46.2% → 46.9%(两个财年),margin = 序列相除 |
| MSFT cash and long-term debt | describe → get_balance_series ×2 | 3 | 两条余额线各 6 个日期 |
| demo 组合市值与最大权重 | get_portfolio_snapshot | 1 | $10,845,260;MSFT 15.53% |
| max drawdown + 最负因子 | snapshot → reconcile_move | 2 | 17.66%;SPY −0.99%;共线只引和 |

旧面上这类问句 1–2 次调用;新面 1–6 次,在计划写明的"旧 + 2"内(margin 序列那条是"两次 get_flow + 一次 calculate"的预期成本)。

## 5. 旁支

`market_data_service.price_points` 是选价格表规则的唯一家(从 DB 判 ticker 是否为因子,**不读 YAML**——api 容器无 `/app/configs`);`window_return` 与 `explain_episode` 都经它。`get_market_stats` 改用服务端日期。实测 SPY 1y = 20.83%(经 factor_prices),台账 end = 2026-08-20。

## 6. 已知限制 / 观察(如实记)

- **模型选指标仍靠提示层**:`describe_issuer` 把 `revenue`(3 期,latest 2022-01-30)与 `total_revenues`(43 期,latest 2026-04-26)并列,模型问增长时仍选了前者。V9 的具名替代知识只在公式表里,不在指标清单上——把"这个指标被哪个替代/被谁替代"作为数据放进 `describe_issuer` 是候选,**本批不做**(那是新信息,不是收敛)。
- **序列成本**:趋势类问句从 1 次变 2–3 次调用,15/轮预算未撞上;若撞上,记录、不加"一次给全"参数。
- **两张价格表仍是两张**:本批只统一读法,不迁表。
- **run 三切片合并、`list_alerts` 跨组合混淆**:登记在 V10 §8,未动。

## 7. 本批记下的

- **切一块代码时,数它中间夹着什么**:从 `SeriesSpec` 切到 `load_price_series` 把 `_company_id` 一起切走,offline 全绿(没有测试碰库),live 第一条 NameError。
- **计划的数字从"现在的代码"起算,不从"写计划时记得的代码"**:29 vs 31。
- **一个假设从「都能做」到「一次一个窗口」只隔一次 grep**——写计划前核代码,写代码前核计划。
