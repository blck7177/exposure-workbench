# Implementation Plan V5 — 量化正确性批:一种价格、一次回归、一条传导路径

> **状态(2026-08-21)**:**Q1–Q8 全部完成**。offline 697 全绿(批前 672),live 118 全绿,合计 **815**。
> 真实栈实测两次(`run_596da8f1382c`、`run_7acab5fa14e6`,port_001 @ 2026-08-20,yfinance 实时价),
> 11 步全通过。迁移 `v5_price_convention.sql` 已在本地库重放。
> **版本**:v5(2026-08-21)。与 V4 正交:V4 收的是 agent 面到达工具之后的洞,V5 收的是
> 确定性 analytics 层**算错的数**。
> **性质**:缺陷修复方案 + 实测记录。不是模型升级 —— 升级(收缩估计、肥尾、久期、FX)在 §6 列为待拍板。
> **一句话**:这批修的不是"不够专业",是**八处会给出错误数字的地方**;其中最严重的一处,
> 让 −10% 股灾在一个 80% 股票的账本上报出盈利,并且让一条风险限额永远不响。

---

## 0. 执行期决策(2026-08-21,**待 boss 追认**)

boss 拍板的是"先修 P0 正确性 bug,开工"。以下四条是修复过程中无法回避的取舍,均已实施,列此备查——
每一条都不是新增能力,而是"修这个 bug 只能这么修"。

| # | 决策 | 内容与理由 |
|---|---|---|
| **D1** | **收益一律用 `adj_close`,市值一律用 `close`** | 两列并行返回,每个消费者点名自己要哪一个。只返回 `close` 不是简化,是**替所有消费者一次性选了约定**,而对全部"收益类"消费者都选错了。注:`MODULE_NOTES.md:177`(M4)早就写着"收益计算用 adj_close" —— **规则写下来了,代码没照做**,这是本批最便宜也最尴尬的一处 |
| **D2** | **压力情景只声明因子冲击,经 beta 传导** | 原按名字匹配 sector 标签与持仓 ticker,匹配不上贡献 0。改 beta 传导后,`sector_shocks` 必须删除:同一冲击若能经两条命名路径抵达答案,就会抵达两次(TLT 既是因子又是持仓,原来两条都走)。**代价**:失去表达"行业特异性冲击"的能力,那需要残差风险模型,本系统没有,不假装有 |
| **D3** | **`factor_prices` 的 `adj_close` 不回填 `close`** | 迁移只加列、留 NULL。回填等于在数据里断言"未复权的历史是复权过的" —— 正是本批要消灭的静默约定。读路径按 ticker 点名报错,步骤 1 下次 run 自动重灌,一次 run 自愈 |
| **D4** | **因子价格缺失/陈旧 = 与持仓价格同一条 raise** | 原来缺因子被 `if t in df.columns` 静默丢掉,留下一个更小的模型,报告自己时的置信度和完整模型一样。风险:某个 yfinance 符号(如 `^VIX`)长期抽风会拦下所有 run。取舍理由:那是**配置决定**(从 factor_config 移除),不该是静默降级 |

---

## 1. 现状基线(2026-08-21,全部实读/实测)

| 事实 | 坐标 |
|---|---|
| 组合收益序列建在**未复权 `close`** 上,而 calc ledger 的价格序列用 `adj_close` —— 一个系统两套约定 | `market_data_service.py:141`(旧) vs `calc_service.py:120` |
| 权重 = **今天数量 × 最后一根收盘价**,再回溯套用到整段历史 | `market_data_service.py:131-138`(旧) |
| `pivot.ffill().dropna()` 制造零收益日 | `market_data_service.py:109`(旧) |
| 八个**单变量** `polyfit` 的 beta 直接相加当"已解释"; `r_squared` 来自另一个多元拟合 | `factor_model.py:80,107,115-124`(旧) |
| 压力测试按名字匹配 sector/ticker,未匹配者贡献 0;sector 与 ticker 同名会**加两次** | `stress.py:48-61`(旧) |
| `factor_prices` 只由 `scripts/seed_demo_db.py:153` 写过,无人刷新、无人检验;实测比持仓价旧 4 天 | 2026-08-21 DB 实测:factor max `2026-07-23` vs market max `2026-07-27` |
| recipe 的收益窗口用 `date.today()`,与 ledger 的可重放目标冲突 | `recipe.py:97`(旧) |
| `load_fact_series` 不过滤 `dimensions_hash`,分部/地区维度事实可与合并口径进同一期桶;`filing_date` 未 select,复述选择退化为 accession 字符串排序 | `calc_service.py:69-88`(旧) · `period_ladder.py:87-98` |
| `factor_model.py` 与 `stress.py` **测试覆盖为零** | 批前 `tests/` 全文 grep |
| 全库 `market_prices.adj_close` 无一 NULL(10,296 行),故"收益必须有复权价"可以硬失败 | 2026-08-21 DB 实测 |
| demo 组合 90 天窗口的价格面板**完全矩形**(62 天 × 10 ticker),故删 `ffill` 在该数据上零代价 | 2026-08-21 DB 实测 |

---

## 2. 修复清单

| # | 修复 | 落点 |
|---|---|---|
| **Q1** | 价格约定统一:`get_prices_df` / `get_factor_prices_df` 同时返回 `close` 与 `adj_close`;收益消费者点名 `adj_close` | `market_data_service.py` · `pnl.py` |
| **Q2** | 消除 look-ahead:固定数量重估值,`return_t = V_t / V_{t-1} − 1`,等价于按**昨日**权重加权 | `market_data_service.build_portfolio_returns` |
| **Q3** | 删 `ffill`;并丢弃跨越 >5 日历日的收益(多日移动不得挂一日标签) | `market_data_service.total_return_panel` |
| **Q4** | 因子模型改**单次多元 OLS**;betas 为偏系数,contributions 加总即拟合值,residual 是回归自己的;per-factor `r_squared` 明确标注为"该因子单独" | `factor_model.py`(重写) |
| **Q5** | 压力测试改 **beta 传导**;情景只声明 `factor_shocks`;不可传导的情景进 `unevaluated` 而非报 0 损失 | `stress.py`(重写) · `configs/stress_scenarios.yaml` |
| **Q6** | 步骤 1 新增 `_sync_factor_prices`;步骤 3 用**同一条 raise**judge 因子面板的缺失与陈旧 | `exposure_workflow.py` |
| **Q7** | recipe 的 `as_of` 提为**必填参数**(无默认——默认就是把时钟藏低一层) | `recipe.py` · `readiness_workflow.py` |
| **Q8** | `load_fact_series` 只取合并口径(`dimensions_hash = ''`),并 outer join `filings` 取回 `filing_date` | `calc_service.py` |
| **附** | `factor_prices.adj_close` 迁移 + ingest 写入,`daily_return` 改由复权序列算 | `v5_price_convention.sql` · `market_data_ingestion_service.py` |
| **附** | 删 `factor_config.yaml` 中无读者的 `method` / `ewm_halflife_days`;`min_observations` / `include_intercept` 改为**真的被读** | `configs/factor_config.yaml` |

---

## 3. 实测记录(2026-08-21,port_001 @ 2026-08-20,真实 yfinance 价)

### 3.1 压力测试:修复前后同一账本、同一天

旧代码取自 `git show HEAD:analytics/stress.py`,喂以本次 run 实际持久化的权重。

| 情景 | 修复前 | 修复后 | 说明 |
|---|---:|---:|---|
| `market_downside` (−10% 股市) | **−0.182%**(赚 $19,749) | **+3.985%**(亏 $432k) | **本批的头号 bug**。旧代码只匹配上 TLT(权重 6.07%,冲击 +3%),八只个股一个都没匹配上 |
| `credit_spread_widening` | +0.654% | **+6.873%** | 越过 `stress_loss` 的 warning 档(6%),**触发了一条此前永不可能响的告警** |
| `rates_shock_up` | +0.207% | +3.118% | |
| `tech_selloff` | +2.154% | +0.298% | 唯一变小的:旧值靠 Technology/Comm/Cons-Disc 三个 sector 名直接命中权重,与 QQQ 冲击**重复计数** |
| `energy_shock` | +0.368% | (已评估) | |

告警对比:修复后该 run 产生 3 条告警,其中 `stress_loss:credit_spread_widening` 是新的。
修复前该 check 的最大输入是 2.154%,低于 6% warning 档 —— 即**这条限额自上线以来从未有过触发的可能**。

### 3.2 因子回归诊断(新增,写进 `workflow_events.payload_summary`)

```
{"alpha": -0.0000418, "max_vif": 10.55, "collinear": true,
 "r_squared": 0.661, "observations": 58, "attribution_date": "2026-08-20"}
```

### 3.3 独立验证:多元 beta 之和 vs 单变量市场 beta

不信任新数就得能证伪它。独立脚本量得:

* 组合对 SPY 的**单变量** beta = **0.53**
* 本次 run 八个**多元**偏 beta 之和 = **0.54**

两者一致,说明多元拟合并未扭曲聚合暴露 —— 而 `market_downside` 对 SPY/QQQ/IWM 的冲击大小相近
(−10/−12/−11%),其传导量正是这个和。**结论:3.985% 这个数可信,尽管构成它的单个 beta 不可信。**

---

### 3.4 上线实测(2026-08-21):部署路径 + 一个新证据

镜像重建、容器重启后,经**真实 worker 路径**(task 队列 → handler → workflow)跑通一次
`run_v5deploy0001`,11 步全绿。configs 在 worker 是 volume 挂载(`./configs:/app/configs`),
api 容器不挂 —— 它不跑 workflow,这是对的。

顺带得到一个**比本批任何一处修复都更该看的数字**:

| run | 观测数 | max VIF | `stress_loss_market` |
|---|---:|---:|---:|
| `run_7acab5fa14e6` | 58 | 10.55 | **3.985%** |
| `run_v5deploy0001` | 60 | 12.14 | **6.231%** |
| 重跑一次(同数据) | 60 | 12.14 | **6.231%** |

同一账本、同一 `as_of`,**多两个观测,头号压力数字从 3.99% 变成 6.23%(+56%)**。
第三行证明代码本身是确定性的 —— 差异全部来自面板数据(早前那次因子面板少两天,后续重灌补齐)。

这不是缺陷,是**估计量的方差**:58 个观测、8 个高度共线的因子,betas 本就不稳,而
压力传导直接建在 betas 上。它把 §6 第 1 条(回看窗口)从"应该做"变成"**必须先做**":
在样本量修好之前,压力数字的**符号**可信(股灾是亏损),**量级**不可引用。

---

## 4. 执行期发现,以及它改变了什么

### 4.1 诊断阈值选错了一次(实测纠正,非推断)

初版用**设计矩阵条件数**、阈值 30 做共线性标志。真实数据上条件数 **9.06** → 标志不响;
而同一次拟合的 beta 是 SPY **+1.39** 对 QQQ **−0.67**,VIF 分别为 **10.55 / 7.84**。

条件数回答的是关于矩阵的问题,而页面上要打的是**每个系数**的问号。改为 **max VIF,阈值 5**,
在真实数据上正确触发。这条写进 `factor_model.py` 的注释,连同实测数字。

因子相关矩阵(58 obs)对此的解释:SPY–QQQ **0.92**,SPY–IWM 0.79,SPY–HYG 0.80。

### 4.2 我自己的修复留下了一个同形状的隐含假设

beta 传导修好了"冲击抵达不了账本"。但情景只冲击 8 个因子中的一部分,**其余被隐式按 0 处理** ——
这与"名字匹配不上就贡献 0"是同一种病:一个断言(「股灾中信用不动」)伪装成一处沉默。

实测:`market_downside` 让 **HYG 保持不动**,而该账本对 HYG 的 beta 是 1.29(第二大)。

未擅自编造情景数字(那是建模判断,不是 bug 修复)。改为**记录**:每个情景把 `factors_held_flat`
写进步骤事件,与 `evaluated` / `inert_overrides` 同一机制。让假设可见,不让它可见地消失。

```
"market_downside": {"factors_held_flat": ["HYG", "USO", "^VIX"]}
```

### 4.3 旧测试把 bug 编码成了预期值

`test_return_series_is_weighted_across_the_whole_book` 断言的 **+1.0%** 正是 look-ahead 产物:
两只等额持仓一涨 10% 一跌 10%,真实收益 **0.0%**。测试改写并改名,把这个数字留在注释里当反例。

`factor_model.py` 与 `stress.py` 此前零覆盖 —— 这正是两个 bug 得以存活的原因。新增
`tests/test_factor_and_stress.py`(14 例),含一条**跨配置一致性**检查:任何情景冲击的因子
必须在 `factor_config.yaml` 里存在(两份配置分开编辑,此前无物核对)。

---

## 5. 本批**不做**、但已确认存在的问题(如实)

| 问题 | 为什么这次不做 |
|---|---|
| `positions.quantity` 不做拆股调整 | 拆股日市值仍按拆股前股数算。这是**持仓数据**问题(需要公司行动数据),不是价格约定问题。P&L 已不再报假亏,市值仍会错 |
| 情景未冲击的因子按 0 处理 | 见 §4.2。要修需要因子协方差矩阵推导条件移动,是建模工作 |
| 单个 beta 不可信(VIF 10.55) | 需要收缩估计 / 因子正交化 / 缩减因子集,均改变页面上数字的含义,应由 boss 拍板 |
| 回看窗口仍是 90 日历日(≈58 obs),95% 尾部仅 ~3 个观测 | P1。修完正确性再谈样本量 |
| `factor_prices.daily_return` 有存储值,读路径仍另行计算 | 两处答案同一问题的味道。已让两者口径一致(都用复权),但列的去留是另一次迁移 |

---

## 6. 下一批候选(P1,待拍板)

1. **样本量(已升为最高优先,依据 §3.4)**:回看窗口 90 日历日 → 2–3 年复权收益;
   波动率改 EWMA;VaR 加 Kupiec 回测。实测:多两个观测让头号压力数字动了 56%
2. **因子集**:缩减或正交化,让单个 beta 可引用;或引入 Ledoit-Wolf 收缩
3. **情景完整性**:未冲击因子由协方差矩阵推条件移动,消灭 §4.2 的隐含 0
4. **基本面深度**:杠杆类目前只有 `current_ratio` 与 `cash_to_long_term_debt`;缺 total debt / EBITDA / 利息覆盖
5. **工具面**:`asset_class` 全程被存储且从未被使用;TLT/HYG 无久期、无 look-through
