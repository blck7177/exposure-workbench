# V8 验收 — 产物读 · 方法工具 · 轨迹判据 · 回撤取证

> 2026-08-27。**1060 offline / 208 live 全绿**(批前 971/202)。
> V8-P(P1–P3)于 2026-08-24 提交,**其 live 验收本次才第一次跑** —— 见 §0。
> 计划:`docs/IMPLEMENTATION_PLAN_V8.md`。上游依据:`dev_note/portfolio-demo/analyst-skills/` 01–11。

---

## 0. 先纠正一处记录失真

V8 计划状态行写着 **「V8-P 已完成并部署」**。commit 属实(`b4064e6`/`96ac20f`,8/24),**部署不属实**:四镜像建于 8/22 23:44,容器内 `attribution_portfolio_return` 与 `def get_flow` 均 0 命中。

**判据是容器里 grep 代码,不是 commit 记录。** commit 与 build 之间隔着一步,而计划文档只记前者。

后果不是零:活库已有 `stress_results`/`limit_checks`/`max_vif` 且 facts 已 v3 重映射,旧代码的 `recipe.cash_to_long_term_debt` 一直在静默取空。8/27 重建后 V8-P 的 live 验收首次通过 —— 27 条 limit_checks(3 fired 对上 3 个 alert)、5 个 evaluated 情景带 `factors_held_flat`、回归元数据非空(750 观测,max_vif 18.0,collinear)。

---

## 1. 落地形态

```
P4 计数     _RUN_COUNTS —— 直接子表的行数,按表自身记录的那一个布尔/枚举切分,无谓词
A  产物读   get_attribution · get_risk_state · list_run_alerts · list_risk_limits · get_run_freshness
B  方法     reconcile_move —— 两个恒等式 + 一条 calc 账
C  判据     _message_ctx → R1 顺序 · R2 委派节制(两条都零成本可出)
D  取证     find_episodes / deepest + get_drawdown_episodes · explain_episode
```

工具面:meta 25 → **33**;research 不变(全部 META_ONLY,研究面是 issuer-scoped 的)。

---

## 2. C4 事故回归(本批的定义性验收)

重放原问句 *"why there is large drawdowns? do some research and explain"*(`sess_dc80caf2c1cd`):

| 判据 | 目标 | 实测 |
|---|---|---|
| 工具调用数 | ≤ 5(原 15) | **5** |
| 顺序 | 归因先于 filings | snapshot → `reconcile_move` → `get_drawdown_episodes` → `explain_episode` → `search_filing_passages` |
| 含因子贡献且过引用门 | 是 | "largest factor contribution was the market factor",引 `calc_899a1d95f4df` |
| 未经 R1 的 issuer 因果句 | 无 | R1 未触发(归因步在前);LLY 那段写成 "describes … as possible drags",非因果断言 |
| 数值门拒绝 | ≤ 1 | **1**(另有 1 次 invalid_citations,属另一道门) |

**门起了作用而不是被绕过**:被拒两次后,模型**删掉了撑不住的数字**(SPY −7.80%、LLY −0.392415)、保留了撑得住的部分 —— 正是拒绝文案给出的第三条路。

---

## 3. 执行期发现(全部已修)

**① `utilization` 不是 `current/limit`。** `_check_one` 的真实契约:`limit_value` = **被越过的那一档**(breach 则 breach_level,否则 warning_level),而 `utilization` = `current/breach_level` **恒定**。计划里的示例文案 "15.8% vs limit 15.0% — utilization is current/limit" **对本代码库是错的**,照抄就把要防的误 attribution 建进了防护本身。实测:LLY 0.1377 越过 warning 0.12,utilisation 0.765 是对 breach 0.18 说的。`reads_as` 改为按 severity 分支。
> 顺带:我第一版的 offline 夹具描述的是**不可能的行**(severity=breach 时 utilization 必然 = current/limit_value = 1.053,不可能是 0.792)。V3 语料那一行其实是 warning 档。

**② 恒等式 B 的左边,计划写错了。** 计划写 `daily_return`;V8-P1 已确立"当日收益是两个数"。回归是对总收益价拟合的,残差只对 `attribution_portfolio_return` 闭合。实测:按本文写法闭合到 **8.7e-19**,按计划写法差 **2.4e-6**(容差的四十倍),那个差额全部是持仓的分红历史。

**③ 门拒了 `reconcile_move` 自己产的份额,而 `_CALC_RATIO_OPS` 不是原因。** 本账本此前 12 个 operation **全部**只用 `{value}` 或 `{points}`,`_from_calc` 就只读这两种形状,带别的数值键的结果**静默地什么都不携带**。修法 `_CALC_RESULT_KEYS`:per-op、per-key 的单位表(本 op 同时产出一个 share 和一个观测数,单一 op 级单位会让 "750%" 通过 750 观测)。改前先普查了活库,确认无既有行改变含义。

**④ `get_drawdown_episodes` 返回的深度无人可引。** 补 calc 行,并让 `_CALC_RESULT_KEYS` 支持**列表值**(n 个深度同属一个单位)。

**⑤ benchmark 窗口收益恒为 null。** SPY 在 `market_prices` 只有 2025-06-18 起 277 个 session(某次上传回填的),在 `factor_prices` 有 2023-05-08 起 825 个(因子同步维护全历史,因为回归需要)。改为**按 ticker 对本台是什么**选 store。**这个问题从 DB 事实回答而非读 `factor_config.yaml`** —— api 容器没有 `/app/configs` 挂载,工具读 YAML 会在 mcp 容器给出完整答案、在 api 容器给出空答案,正是 V2-H4 那个 bug。

**⑥ `get_run_freshness` 的"最新"是计划顺序。** 只按 `as_of_date` 排序,同一 session 重跑是常态而非边缘。已按 `completed_at` 破平。

---

## 4. 已知限制(如实记,不建半套机制)

- **写下的 `0` 会被库里任何 `0.0` 支持**,所以 "0 limits were breached" 在一个持有"某行业权重未变"的 run 上通过。这是 V3 记过的门的性质(**它核对值,不核对句子把值归给哪个量**)从一条新路到达。P4 让这条路更常被走到,故在此重记。
- **判断禁令仍是提示层的**(V9 已知限制,对新工具同样适用)。`quotable_individually` 不是例外:它陈述的是**估计量的确定性**(VIF 越线),不是数字是不是好消息。
- **回撤深度不可分解** —— 这不是限制而是**数学事实**,写在 `analytics/drawdown` 的模块 docstring 里,由一条遍历模块导出面的测试守着(缺席断言,不是运行时拒绝:存在而拒绝的函数是模型会重试的函数)。
- **两张价格表持有同一种事实**(`market_prices` / `factor_prices`),每个消费者都得知道 ticker 住在哪张。实测:1,927 行重叠上 `close` **完全一致**,`adj_close` 有 38 行 SPY 差 ≤2e-4(两次 ingest 在第四位小数上舍入不同)。统一它需要迁移,是它自己的一批。
- **R1 按 message 计**,首版收紧。若 live 中误伤真实多轮对话,放宽到 session 计并留档 —— **方向只许从紧到松**。

---

## 5. 本批自己新立的两条纪律

**①「计划是依据,不是权威 —— 代码才是。」** 本批四处修正(utilization 语义、恒等式 B 左边、`_CALC_RATIO_OPS` 不是拒绝的原因、V8-P 部署状态)全部是**计划文档说 A 而代码说 B**。计划写于 8/23,V8-P1 的发现在 8/24 —— 一份计划在自己被执行的过程中就会过期。**每条从计划抄进代码的判据,必须先在代码里核对它描述的那个函数。**

**② 一个合成夹具通过,不等于判据成立。** `_alert_row` 的第一版测试描述的是一行**在这个系统里不可能存在**的数据,于是它对真正的错误无话可说。**夹具必须满足它所模拟的那个构造函数的不变量** —— 这条是 V3 「抽取器必须拿真语料建」在测试数据上的同一件事。
