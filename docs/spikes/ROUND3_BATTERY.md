# 第三轮电池 — 20 道正交问句,和它们照出的一个核心错误

> 2026-08-28。**20 题 n=1**,gpt-5.4-mini,dev 账户 `user_3IDBMeAxLTbecvGorzwV7FCeroR`,
> 162s / 968,400 prompt / 15,937 completion / 177 次工具调用 / 65 次调用被拒 / 16 次门拒绝。
> 问句 `tests/battery/questions_round3.json`,原始轨迹与答案见 session id(每题一条)。
> **每个数字都回 `calc_ledger` / `financial_facts` 核过,引文回 `filing_chunks` 逐字核过。**
>
> **主结果:`containment.cover` 会双重计数。** NVDA 的 `total_debt` 被算成 9.47B,
> 真值 8.47B,带 `calc_id`、可引、过门。19 个 (发行人,日期) 组合受影响。
> 这条**不需要 LLM 即可确定性复现**,并推翻了"凡是带 `calc_id` 的数字,没有一个错"。

---

## 0. 这批问句是怎么来的

三个分析师视角(信用+法证 / 基本面权益 / 量化风控+组合经理)各出 8–10 个候选,共 30 个;
筛到 20 的**唯一判据是:没有两题会因同一个缺陷而失败**。被砍掉的都是与保留题共享根缺陷的:
LLY 净债务/EBIT 与 Q01 共享"存量÷流量窗口错配";NVDA-vs-MSFT TTM 对齐与 Q12 共享财年不同期;
ROE 题与 Q01 共享混合基准;"跌 1.3% 对 VaR 1.4%" 与 Q10 共享同一个尾部测度读取。

筛选前对着库核过每题的可答性,并据此改了三处:
`interest_paid` MSFT **没有**(只有 AAPL/JPM/LLY/NVDA/XOM)、`commercial_paper` AMZN **没有**
(短期到期题因此从 AMZN 改标 NVDA)、`operating_income` LLY 与 XOM **没有**(排名题因此成立)。

---

## 1. 结果

判据是"轨迹 + 答案是否与账本一致",不是"读起来对不对"。

| # | 隔离的失败类 | 结果 |
|---|---|---|
| Q01 lease-adjusted-debt | 租赁负债在包含图之外,相加是合法调整 | **过** — 正确拒绝跨日期合并 |
| Q02 cash-conversion-cycle | 三个 day 公式复合 + ×365 单位类 | **败 ●** — 假缺席,根因在拒绝载荷 |
| Q03 growth-decomp-tax | 增长分解:税前增长 vs 有效税率 | 部分 — 未取 `pretax_income`(它有 43 期) |
| Q04 maturity-stack | 短期债务标签间的包含关系 | **败 ●** — `cover` 双重计数,见 §2 |
| Q05 net-debt-inputs | 公式输入透明度 + 指标词表缺口 | **过** — 组成正确,点名净不掉的证券 |
| Q06 etf-no-fundamentals | 实体级缺席 | 答案对,**轨迹病态**(80 次调用) |
| Q07 cash-vs-accrual-interest | 发行人级标签缺席 | **败 ●** — 权责发生数写成现金数 |
| Q08 period-not-filed | 事实表时间边缘 | **败 ●** — 期间标签伪造 |
| Q09 risk-contribution-absent | 能力缺席 | **败 ●** — 收益贡献冒充风险贡献 |
| Q10 var-reparameterize | 尾部测度不可重标定 | 过(出路贫乏) |
| Q11 screen-partial-coverage | 覆盖不均下的横截面筛选 | 过(缺席处理优秀)/ 期间标签错 |
| Q12 noncoterminous-quarters | 财年不同期 | 部分 — 用 QoQ 冒充增长比较 |
| Q13 useful-life-comparability | 逐字引用 + 可比性断裂 | **过** — 引文逐字命中 |
| Q14 narrative-vs-cashflow | 跨面佐证 | **过** — 并正确回避判断 |
| Q15 stress-scenario-read | 读取压力情景完整定义 | **过** — 算术与"非预测"措辞均对 |
| Q16 warning-not-breach | warning ≠ breach + 标的专属阈值 | **过** — 1 次调用,全对 |
| Q17 drawdown-not-additive | 回撤深度路径依赖、不可加 | **过** — 明说这不是分解 |
| Q18 run-staleness | 陈旧度按交易日计 | 部分败 — 见 §4 类 E |
| Q19 factor-proxy-is-a-holding | 隐藏共同敞口不可识别 | **过** — 共线性与不可识别都说对了 |
| Q20 window-scope-reconciliation | 风险统计量的窗口口径 | **过** — 明说两个都没错 |

**11 过 / 5 严重败 / 4 部分。**

---

## 2. `containment.cover` 双重计数(●,系统缺陷,与模型无关)

Q04 的 `evaluate_formula(total_debt, NVDA)` 产出 `calc_b72d0f3b43db` = **9,470,000,000**。

脱离 LLM 的确定性复现:

```python
avail = {"long_term_debt_total": 8.470e9, "long_term_debt_noncurrent": 7.470e9,
         "current_portion_long_term_debt": 1.0e9, "debt_current_total": 1.0e9}
cover(avail, "debt")
# terms   : ('long_term_debt_total', 'debt_current_total')
# value   : 9,470,000,000          ← 真值 8,470,000,000
```

NVDA 2026-04-26 的事实:`long_term_debt_total` 8.470B = `long_term_debt_noncurrent` 7.470B
+ `current_portion_long_term_debt` 1.000B;而 `debt_current_total` 1.000B = 同一笔 current portion。

`EDGES` 里两条边都在:

```
('long_term_debt_total', 'current_portion_long_term_debt', 85)
('debt_current_total',   'current_portion_long_term_debt', 24)
```

**但两个父节点之间没有边。** `cover` 的 widest-first 取了 `long_term_debt_total` 后,
只把**它的后代**放进 `excluded`;`debt_current_total` 是兄弟父节点、不是后代,于是被取走——
它的孩子 `current_portion_long_term_debt` 已经在第一个父节点里数过一遍了。

排除集只回答"这个候选是不是已取节点的后代",不回答"这个候选的后代是不是已经被覆盖"。

**影响面**(全库扫描,172 个 (发行人,日期) 组合):**19 个中招,全部是 NVDA**,
2021 起至 2026-04-26 每个申报日虚增约 10 亿。连带 `net_debt`、`debt_to_ebitda`、
`debt_to_operating_cash_flow`、`fcf_to_debt` 全错。既有电池的 **T02「should I lend to NVDA」
走的正是这条**。

**43 次会话为什么没抓到**:T01/T13/T14 打的是 AAPL/AMZN/GOOGL,三家都没有 `debt_current_total`
(该指标只有 LLY/NVDA/XOM 有)。测试打在了图的另一半上。

**判据很干净,且是删/加约束而非加规则**:候选节点的后代集若与已覆盖区域相交,就不能取。

---

## 3. 拒绝载荷在陈述一件关于世界的假事(●)

Q02 的答案:"this desk's AAPL coverage does not include accounts receivable, inventory,
or accounts payable over any period."

**假的。** AAPL 三项各 45 期,最新 2026-03-28。

轨迹里的根因:

```
get_flow(AAPL, accounts_receivable, months=12)  ->  error: not_reported
get_flow(AAPL, inventory,           months=12)  ->  error: not_reported
get_flow(AAPL, accounts_payable,    months=12)  ->  error: not_reported
```

应收/存货/应付是**余额**,不是流量。真相是"这个指标不是流量,请用 `get_balance_series`",
而载荷说的是 `not_reported`。**模型转述得很忠实——它转述的是系统给它的假话。**

这是 GAPS 的 G1 / P10,但这个实例比之前任何一个都干净:不是"拒绝里信息不足导致模型自己编",
而是**系统主动断言了一件假事**。修法与 G1 同向:缺席对象必须区分
"该发行人从未申报" / "该指标不是这个类" / "该窗口不可导出",并带上可走通的那个工具名。

---

## 4. 其余失败,按错误类归并

### 类 C — 没有东西把名词绑到数字上(2/20)

- **Q07**:调用的是 `get_flow(MSFT, interest_expense_nonoperating, 12)` —— 权责发生制 P&L 行。
  答案写成 "the cash-based interest paid over the last 12 months was $2.827B"。
  MSFT 根本没有 `interest_paid`,而答案把它说成有。
- **Q09**:`get_attribution` 的**收益贡献**原样重排,标题是 "ranked by risk contribution"。
  run 里没有任何逐仓风险分解。

两条都**过门**,因为数字确实在被引证据里。假的是数字前面那个名词。
这正是 `GAPS.md` §2 G4 表里"数字前的名词 / `fact.normalized_metric` / 无人检查"那一行,
本轮实测 **2/20**。

### 类 D — 没有东西把期间标签绑到产出该数字的窗口上(3/20)

- **Q08**:`get_flow(AAPL, gross_profit, months=3, last_n=2)` 返回的是 12 月季与 3 月季。
  答案标成 "the March quarter" 与 "the June quarter"。**Apple 的 6 月季根本没申报**
  (最新 `period_end` 2026-03-28)。两个标签整体前移了一个季度。
- **Q11**:`evaluate_formula(months=12)` 给的是 TTM,标成 "full-year 2025";
  且 GOOGL 用 2025-07-01..2026-06-30、AMZN 用 2025-04-01..2026-03-31 —— **两个不同窗口排了名**。
- **Q12**:用 QoQ 冒充"增长比较",拿 GOOGL 的 4–6 月季对 MSFT 的 1–3 月季,
  先宣布 "Alphabet grew revenue faster",末尾才补一句两家期末不同。

三道题从三个不同的分析入口进来,**全部撞在同一个没有守卫的面上**。
每个数字都真、都可引,错的只是它被叫做哪一段时间。

### 类 E — 陈旧度按"已摄入交易日"计,不对表(Q18)

`get_run_freshness` 返回 "0 market sessions behind",因为 `market_prices` 本身也停在 2026-08-20。
用户说"感觉一周没刷了"是对的(距今 8 天),系统答"是最新的"。

两个日期被刻意分开是对的,但**两个都来自库内**;没有任何一处把最新已摄入交易日与挂钟对比。
**摄入中断在这个口径下永远不可见。**

顺带:模型第一次调用把 `portfolio_id` 填成了字面量 `"__NEED_FROM_SNAPSHOT__"`,报错后才重取。

### 类 F — 无望搜索没有成本上限(Q06)

答案本身对(TLT/HYG 无基本面)。但走了 **80 次调用**:`describe_issuer` 10 次,
预算 15 次耗尽后又硬打 **65 次 `evaluate_formula`,全部 `turn_tool budget exhausted: 15/15`**。

本轮 65 次被拒调用**全部来自这一题**。门拒绝了,循环不停。
三次调用可达的结论花了八十次。

---

## 5. 门的记账:16 次拒绝,0 次拦住严重错误

本轮数值门触发 16 次,且每次都起了作用——模型重取证据、重写引用。V11-Q 的逐字检查器同样在工作:
Q13/Q14 的四条引文**全部逐字命中被引 chunk**(`chunk_9e02ee2b3065`、`chunk_a574950dbc31`、
`chunk_af4fa99641df`)。

**但五个严重失败(Q02 / Q04 / Q07 / Q08 / Q09)全部过门。** 因为没有一个是"数不在证据里":

| 题 | 错在哪 | 门看的是 |
|---|---|---|
| Q02 | 缺席陈述为假 | 数 ∈ 证据(该句没有数) |
| Q04 | 算子自己算错 | 数 ∈ 证据(它**在**证据里,证据本身错) |
| Q07 | 名词错 | 数 ∈ 证据 ✓ |
| Q08 | 期间标签错 | 数 ∈ 证据 ✓ |
| Q09 | 名词错 | 数 ∈ 证据 ✓ |

**门在它被设计的那一维上是满分,而这批失败一个都不在那一维上。**
Q04 尤其值得记:门校验"数 ∈ 被引证据"是对的,可当**证据本身**是错的时候,门只会更快地放行。

---

## 6. 我自己那套正交性论证,对了一半(如实记)

20 题在**分析轴**上确实互不重复。但在**失败类**上没有:
Q07/Q09 同落类 C,Q08/Q11/Q12 同落类 D —— **5 道题塌进 2 个类**。

设计时我按"分析上互不重复"筛,而正交的判据应该是"失败时互不重复"。这两者不是一回事,
本轮才把差别量出来。

不过这个塌缩本身是结果:五个独立的分析入口指向两个没有守卫的面,
比五个分散的缺陷更有说服力,也更能定位该造哪个模块。

---

## 7. 本批记下的

- **`MCP_URL` 是宿主机跑电池的必要条件**。`scripts/agent_battery.py` 的 docstring 写了
  "MCP_URL reachable from the host",但 `.env` 没有这一项,`settings.mcp_url` 默认
  `http://exposure-mcp:8000` 是 compose 网内地址。第一次 20 题**全部 0 调用失败**,
  未消耗任何 token。正确跑法:`MCP_URL=http://127.0.0.1:8104`。应进 `.env.example`。
- **`2026-08-20` 当天有 4 个 completed run**,其中只有 `run_95ebe31c5e51` 带 5 条 `stress_results`,
  其余为 0。"最新的 run"在这份数据里本身歧义;模型每次都选中了带数据的那个,但那是运气不是设计。
- **判分脚本**:轨迹审计单(每题工具序列+参数+错误+门拒绝+引用+全文)是逐条回账本的前提,
  单看 runner 那一行摘要抓不到任何一条本轮的失败。

---

## 8. 未做、已登记

- `cover` 的修复本身(判据已定,措辞待过目)
- 类 C(名词-数字绑定)与类 D(期间标签-窗口绑定)两个检查器
- 类 E 的挂钟对比
- 类 F 的循环终止(预算耗尽后应停,而不是继续被拒 65 次)
- LLY capex 映射(与本轮无关,仍在)
- 本轮为 **n=1**。按「提示层改动 n≥8 才算数」的纪律,以上凡涉及模型行为的结论
  (类 C / D / F、Q03、Q12)**都还不算定论**;唯 §2 的 `cover` 与 §3 的 `not_reported`
  是确定性的,与 n 无关。
