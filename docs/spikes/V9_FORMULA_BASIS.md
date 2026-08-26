# V9 公式依据 — 每个计算的权威出处与本库实测

> 2026-08-24。写在 V9-M 动工之前:**面板里每一行的定义都必须有出处**,而不是凭常识写。
> 三条结论直接推翻了 `IMPLEMENTATION_PLAN_V9.md` §4 面板表的初稿。

---

## 1. EBIT / EBITDA 必须从**净利润**起算,不是经营利润

**出处**:SEC Division of Corporation Finance, *Non-GAAP Financial Measures* C&DI,Question **103.01** 与 **103.02**
<https://www.sec.gov/corpfin/non-gaap-financial-measures>(2026-08-24 实取,需声明 User-Agent)

> **103.01** … Exchange Act Release No. 47226 describes EBIT as "earnings before interest and taxes" and EBITDA as "earnings before interest, taxes, depreciation and amortization." … **Answer: "Earnings" means net income as presented in the statement of operations under GAAP. Measures that are calculated differently than those described as EBIT and EBITDA … should not be characterized as "EBIT" or "EBITDA" and their titles should be distinguished from "EBIT" or "EBITDA," such as "Adjusted EBITDA."**

> **103.02** … **Operating income would not be considered the most directly comparable GAAP financial measure because EBIT and EBITDA make adjustments for items that are not included in operating income.**

**因此**:

```
EBIT    = net_income + interest_expense + income_tax_expense
EBITDA  = EBIT + depreciation_amortization
```

计划初稿写的 `ebitda = operating_income + D&A` 与 `EBIT 覆盖 = 经营利润 ÷ 利息`——**按 SEC 口径都是错名**。若要用经营利润路线,名字必须改成别的(且我们不做:DV3 不造带行业定义名字的指标)。

**本库实测覆盖(8 家,`dimensions_hash=''`)**:`net_income` 8/8 · `InterestExpense` 8/8 · `IncomeTaxExpenseBenefit` 8/8 · `DepreciationDepletionAndAmortization` **5/8**(GOOGL/JPM/MSFT 无)。
→ **EBIT 8/8 可算,EBITDA 5/8 可算**。改用正确定义反而**提高**了 EBIT 的覆盖。

---

## 2. Free cash flow:公式随数字,是 SEC 明说的要求

**出处**:同上 C&DI,Question **102.07**

> Some companies present a measure of "free cash flow," which is typically calculated as **cash flows from operating activities as presented in the statement of cash flows under GAAP, less capital expenditures**. … However, companies should be aware that **this measure does not have a uniform definition and its title does not describe how it is calculated. Accordingly, a clear description of how this measure is calculated** … [is required]

**因此**:`FCF = operating_cash_flow − capex`,**且公式必须与数字同行**。这不是我们的洁癖——它是监管对这个名字的明确要求,也顺带给面板"每行带 formula"这条设计一个权威背书。

---

## 3. 债务概念是**嵌套部件**,不是同义词 —— 现行映射据此是错的

**出处一(定义)**:US-GAAP 分类标准中 `LongTermDebtCurrent` = 长期债务的当期到期部分(current maturities),`LongTermDebtNoncurrent` = 不在未来 12 个月内到期的部分。PwC Viewpoint 12.3 *Balance sheet classification — term debt*:

> "Long term obligations are those scheduled to mature beyond one year (or the operating cycle, if applicable) from the date of an entity's balance sheet."

<https://viewpoint.pwc.com/dt/us/en/pwc/accounting_guides/financial_statement_/financial_statement___18_US/chapter_12_debt_US/123_balance_sheet_cl_US.html>

**出处二(本库算术,决定性)**:AAPL 2026-03-28,`dimensions_hash=''`,单位十亿美元

```
LongTermDebtNoncurrent   74.404
LongTermDebtCurrent    +  8.310
                       = 82.714
LongTermDebt             82.700     ← 两者之和(差 0.014 = 折价/发行成本口径)
CommercialPaper           1.997     ← 另一笔短债,不属于 term debt
```

**`LongTermDebt` 是含当期部分的总额。**

**因此现行映射有真缺陷**:`long_term_debt` 同时接受 `LongTermDebt` 与 `LongTermDebtNoncurrent`,`short_term_debt` 同时接受 `LongTermDebtCurrent`/`DebtCurrent`/`ShortTermBorrowings`——这些是**互相嵌套的部件**,不是"发行人对同一经济量的不同标法"。`period_ladder._pick_latest` 只解决重述、不解决口径,于是按申报时间**静默二选一**。

**实测影响面(24 个 (公司,指标) 对碰撞,8 个指标)**,数值分歧最大者:

| 公司 | 指标 | 分歧期数 | 最大相对差 |
|---|---|---|---|
| AMZN | short_term_debt | 17/17 | **17,596%** |
| XOM | short_term_debt | 5/5 | 250% |
| MSFT | long_term_debt | 21/21 | 28.1% |
| AAPL | long_term_debt | 19/19 | 17.4% |
| AMZN | cash_and_equivalents | 21/21 | 6.4% |

**对 V9 是阻塞级**:`total_debt = 短债 + 长债` 在 AAPL 上会算成 82.700 + 8.310 = 91.010,**把当期部分重复计入 8.31B**,而每个输入都有真 `fact_` id、每步算术都有真 `calc_` id ——**良构的错误,门放行**。

---

## 4. Net debt:没有统一定义,只能报"总债 − 现金"并写明

评级机构的 net debt 是**带折价的调整概念**(S&P 只净掉"surplus cash",并对不同资产给不同折价),需要我们没有的输入。按 DV3(不造带行业定义名字的指标):

```
net_debt = total_debt − cash_and_equivalents     ← 公式随数字,且明说不是评级机构口径
```

S&P *Corporate Methodology: Ratios And Adjustments* 仅在第三方镜像可得(<https://www.maalot.co.il/Publications/MT20190402125127.PDF>),本档**不据以实现任何指标**,仅记录"我们没有做它"这件事的对象。

---

## 5. 其余比率(口径无争议,但基数有)

| 行 | 公式 | 口径注记 |
|---|---|---|
| current_ratio | current_assets ÷ current_liabilities | INSTANT ÷ INSTANT,同一期末 |
| cash_to_short_term_debt | cash_and_equivalents ÷ short_term_debt | 同上 |
| debt_to_ocf | total_debt ÷ TTM operating_cash_flow | **INSTANT ÷ duration**:分子期末、分母 TTM,两者必须同时写明 |
| fcf_to_debt | (TTM ocf − TTM capex) ÷ total_debt | 同上,方向相反 |
| 毛利/经营/净利率 | 各自 ÷ revenue | 同期同口径 |
| 周转天数 | 期末余额 ÷ TTM 流量 × 365 | **用期末余额而非平均余额**——平均需要两个期末,会把缺失面积扩大一倍;选择写进 formula 串,读者自明 |

**存量÷流量的比率必须同时携带两个口径**(期末日期 + TTM 窗口),这是本库 P0 阶段用 2808% 那次学到的同一条纪律的延伸。

---

## 6. 由本档产生的、对 V9 计划的修订

1. **面板的 EBIT/EBITDA 改为净利起算**(§1)——覆盖从"operating_income 有洞"变成 EBIT 8/8。
2. **FCF 行必带公式串**(§2),并在 MODULE_NOTES 里记下这是 SEC 要求而非风格选择。
3. **V9-M4 的"既有 13 指标映射一字不动"必须撤销**(§3):现行债务映射把部件当同义词,是 V9 面板的阻塞级缺陷。修法与影响面见计划 §3 修订版。**这是一次对已记录决策的推翻,需 boss 追认。**
4. **net_debt 保留但降级为"带公式的朴素定义"**(§4),永不叫 adjusted/agency net debt。


---

## 7. 实测记录(V9-M 执行期)

**M1 拆分**:187 行冲突 → 0。1,506 行按 v3 改名。既有序列实测未变(AAPL revenue/gross_profit、MSFT operating_income 逐点相同)。
代价如实记:NVDA 2022 年换标法,拆分后合同收入 3 期 / 总收入 43 期;旧的连续 46 期是"按申报时间挑"拼出来的,而**前段合同收入、后段总收入的序列不是有效趋势**。

**M1b 新指标**:18 个概念回填 3,815 行,**全部是 `None →`**(零改动既有映射),零新碰撞。

**M3 口径**:56 条断言全绿——19 个余额型全部 `period_start IS NULL`,9 个流量型全部有 `period_start`,全部单一单位 USD。

### 执行期发现,直接改变面板设计

**① EBIT 必须与 operating_income 并列呈现。**
实测 GOOGL 2026-06-30 单季:

| | $bn |
|---|---|
| total_revenues | 119.796 |
| operating_income | 40.770 |
| **pretax_income** | **138.753** |
| income_tax_expense | 26.560 |
| net_income | 112.193 |

内部自洽(`138.753 − 26.560 = 112.193`,分毫不差),但税前利润**远超**经营利润——该季约 $98B 来自非经营项。按 SEC 定义算出的 `EBIT = NI + 利息 + 税 = 138.847` **数字正确、几乎全部非经营**。
这正是 C&DI 103.02 说"operating income 不是可比 GAAP 指标"的另一面:两者都要在场,读者才不会误读。**面板并列二者,不做判断**——符合"只铺证据"。

**② 银行的 EBIT 无意义,bank guard 是必需的。**
实测 JPM 单季:利息费用 **24.356B** > 净利 **16.494B**。对银行,利息是核心经营成本,加回去得到的"EBIT"不是任何东西。DV6 的整面板拒绝据此坐实。

**③ D&A 的缺口按预期落在 GOOGL/JPM/MSFT**,三家返回 `UnknownMetric`(类型化拒绝),EBITDA 因此 5/8——**缺席可见,不是补零**。
