# Implementation Plan V9 — 报表分析师批:只铺证据的 credit/fundamental 问答

> **状态(2026-08-24)**:计划定稿,待执行。
> **性质**:让 agent 能以 fundamental/credit analyst 的方式回答报表类问题——**每句话可溯源,判断留给用户**。数据地基(映射扩容+回填)→ 一个方法工具 → 表达纪律 → 验收 battery。**不动 web,不动量化,不动架构。**
> **一句话**:58,023 条已存储但未映射的 facts 里,躺着让 EBIT 利息覆盖、净杠杆、FCF 变得可算的全部原料;加映射 = 一次回填 UPDATE,**不用重新 ingest**。
> **上游依据**:2026-08-24 与 boss 的功能讨论(四种句子/最小集切法);`dev_note/portfolio-demo/analyst-skills/` 01(credit 域)、09(结论)、11(组合语法)。
> **优先级说明**:V8-A…D(量化产物读/归因)**暂停让位**,V8-P 已完成的持久化保留、本批不依赖。

---

## 0. 已定决策(2026-08-24,boss 拍板 + 执行前核实)

| # | 决策 | 内容与理由 |
|---|---|---|
| **DV1** | **判断句不输出**(boss 原话"只铺证据把判断留给用户") | 回答只含三种句子:事实句(fact_/chunk_)、计算句(calc_,公式随数字)、缺失句(带原因)。被问"你会不会借钱给他"→ **陈列做这个判断需要的证据,声明判断归用户**。基准句("同业一般 3x 以下")一并推迟——它需要外部标准语料,v1 没有,宁缺毋滥 |
| **DV2** | **最小集边界**(boss 认可) | 本批 = L1 数据层全部 + 带定义计算 + 问题→方法路由 + 表达纪律。**同业比较第二波**;评级式调整指标只做"诚实拒绝"那一半 |
| **DV3** | **不造带行业定义名字的指标** | 名字即承诺:输入不齐就不产出那个名字。EBITDA 只以显式定义出现(`ebitda (operating_income + D&A)`),**永不**出现 FFO/debt、S&P 口径调整杠杆(调研 01 判过:良构错误会过门,比不做危险) |
| **DV4** | **D&A 三个变体不并** | 语料实测 `Depreciation`(6/8)、`DepreciationDepletionAndAmortization`(5/8)、`DepreciationAmortizationAndAccretionNet`(1/8)是**三个不同经济量**(纯折旧 / 含摊销折耗 / 含增值)。并起来就是 pretax_income 那次要拒绝的假映射。只映射真 D&A 概念,覆盖不足如实呈现 |
| **DV5** | **银行的净利息不并入 interest_expense** | `InterestIncomeExpenseNet`(1/8,JPM)是银行经营收入概念,不是费用。并入=8/8 覆盖假象+口径污染 |
| **DV6** | **bank guard 数据源 = positions.sector** | 实测 `companies.sector` 是脏的(AAPL 存着 SIC 码 "3571",其余为空),`security_master` 无 sector 列。持仓内的名字(含 JPM='Financials')可靠;查不到 sector 时**不拒绝但声明**(`sector_unknown: true`) |
| **DV7** | **TTM 优先,FY 回落必须可见** | 流量指标 TTM(4 个季度逐一点名);季度不齐回落到最新 FY,**回落写进 basis 字段**(`"FY2025 (TTM unavailable: missing 2026Q1)"`)。回落不可见=静默口径切换,那是要消灭的形状 |

沿用的既有决策:DP1(组合域原语不开)、DP4(门的新拒绝必须"删句可出")、no-fallback。

---

## 1. 现状基线(2026-08-24,全部实读/实测)

| 事实 | 坐标 |
|---|---|
| **58,023 / 62,473 条 facts 已存储、`normalized_metric IS NULL`** —— 映射状态从不决定存储(设计规则写在模块头) | `concept_mapping.py:1-19` · 活库实测 |
| 归一化仅发生在 ingest 一处:`normalize_concept(f.raw_concept)` | `filing_ingestion_service.py:82` |
| 映射规则:多概念→一指标、**1 fact→1 metric、不聚合**(total_debt=ST+LT 是计算不是映射);概念被两个指标认领 = import 时 RuntimeError | `concept_mapping.py:22-103` |
| `raw_concept` 带前缀存储(`us-gaap:InterestExpense`);非 us-gaap(dei/srt/custom)不归一化 | 同上 :105-115 · 活库实测 |
| **候选概念语料覆盖(8 家公司实测)**:`InterestExpense` 8/8 · `Assets` 8/8 · `StockholdersEquity` 8/8 · `IncomeTaxExpenseBenefit` 8/8 · `OperatingLeaseLiability` 8/8 · `AccountsReceivableNetCurrent` 7/8 · `AccountsPayableCurrent`/`Liabilities`/`InventoryNet` 6/8 · `DepreciationDepletionAndAmortization` 5/8 · `InterestPaidNet` 5/8 | 活库 SQL,2026-08-24 |
| `list_available_metrics` 已返回逐指标期数+最新期末——覆盖度自知大半已有 | `calc_service.py:288-306` |
| calc 账本:`_record(company_ticker: str\|None, …, input_refs)`;比值型 operation 必须注册 `_CALC_RATIO_OPS`,否则被判 MONEY、门拒自产比值 | `calc_service.py:146` · `numeric_verification.py:437` |
| 期间纪律已在:period_end 为准、Q4 推导、INSTANT/duration 区分、`last_n` 有界 | 既有(P0/V3 验过) |
| 原文检索已在:`search_filing_passages`(k≤10)、`get_filing_section`;**只有 10-K/10-Q**,无 8-K/新闻/电话会 | `definitions.py._FORM_TYPE` |
| respond 门:引用存在性+数值核对;**引文路线对符号盲**(有意的已知限制,本批不动) | `meta_tools.py:152-218` |
| 引文逐字性(«管理层说 X» 必须是原文)**无机制**,v1 靠提示纪律 —— 如实记 | 无坐标,缺失本身是事实 |

---

## 2. 排程(单 lane 顺序;每阶段独立可合并)

```
V9-M 数据地基(~1d)   M1 映射扩容 → M2 回填脚本 → M3 口径实测 → M4 回归护栏
V9-F 方法工具(~1d)   F1 get_fundamental_panel
V9-G 表达纪律(~0.5d) G1 _SYSTEM 分析师契约 → G2 已知限制入档
V9-E 验收(~0.5d)     六题 battery 实测并存档
```

纪律照旧:先红后绿;offline 全绿 + live 增量 → commit;`_SYSTEM` 措辞 diff 在 commit 前给 boss 过目。

---

## 3. V9-M — 数据地基:映射扩容 + 回填

**M1 新映射(`MAPPING_VERSION` → v3)**,每条带语料实测覆盖与口径:

| 新指标 | 概念(严格,不凑) | 覆盖 | 口径 |
|---|---|---|---|
| `total_assets` | Assets | 8/8 | INSTANT |
| `total_liabilities` | Liabilities | 6/8 | INSTANT |
| `stockholders_equity` | StockholdersEquity(**不含** IncludingPortionAttributableToNoncontrollingInterest——含少数股东权益是另一个量) | 8/8 | INSTANT |
| `interest_expense` | InterestExpense(**不含** InterestIncomeExpenseNet/DV5、不含 Nonoperating 子集) | 8/8 | duration |
| `income_tax_expense` | IncomeTaxExpenseBenefit | 8/8 | duration |
| `depreciation_amortization` | DepreciationDepletionAndAmortization(+执行时核查 `DepreciationAndAmortization` 是否在语料中;**不含** Depreciation/DV4) | ≥5/8 | duration |
| `accounts_receivable` | AccountsReceivableNetCurrent | 7/8 | INSTANT |
| `inventory` | InventoryNet | 6/8 | INSTANT |
| `accounts_payable` | AccountsPayableCurrent | 6/8 | INSTANT |
| `operating_lease_liability` | OperatingLeaseLiability | 8/8 | INSTANT |

**M2 回填脚本** `scripts/backfill_concept_mappings.py`:调用 **`normalize_concept` 本身**(唯一真相源,不在 SQL 里复刻映射),`UPDATE … WHERE normalized_metric IS NULL`;**只做加法**(断言:绝不改动已非空的映射);幂等;逐公司逐指标打印回填数;owner 角色跑。PRODUCTION.md 记入部署序(在迁移之后、起栈之前)。**可逆**:反向脚本按 MAPPING_VERSION 差集把新指标重置回 NULL。

**M3 口径实测(live)**:每个新指标在真语料上断言 period_type 符合预期(INSTANT vs duration)、unit='USD'、值的量级 sanity(如 AAPL total_assets ~1e11)。**错一个口径,YoY 就会比错一类数**——这是 P0 阶段用 2808% 学过的。

**M4 回归护栏(offline+live)**:既有 13 指标的映射**一字不动**(测试钉住 v2 集合是 v3 集合的子集且逐概念相同);回填后 AAPL 毛利率等既有序列数值不变(live 抽查);JPM 的 revenue/gross_profit **仍然缺席**(缺席可见是设计,不是要修的东西)。

---

## 4. V9-F — 方法工具 `get_fundamental_panel(ticker)`

一次调用(READ 类,占 1 格预算),确定性服务(新 `analytics/fundamental_panel.py`),返回**自洽对象**。这是"问题→方法路由"的实现方式:诊断类问题的标准动作被冻结成一个调用,agent 只需选中它。

**面板分区与定义**(每行:`{name, value, formula(人话公式), basis(期间口径), calc_id, inputs(fact_ids)}` 或 `{name, status:"unavailable", missing:[…], reason}`):

| 区 | 行 | 公式(随数字进回答) |
|---|---|---|
| 杠杆 | total_debt · net_debt · debt_to_ocf · debt_to_ebitda* | ST+LT 债 / 减现金 / 债÷TTM OCF / 债÷TTM(OI+D&A) |
| 覆盖 | ebit_interest_coverage* | TTM 经营利润 ÷ TTM 利息费用 |
| 流动性 | current_ratio · cash · cash_to_short_term_debt | 流动资产÷流动负债 / — / 现金÷短债 |
| 现金生成 | ocf_ttm · fcf_ttm · fcf_to_debt | — / OCF−capex / FCF÷总债 |
| 盈利 | gross/operating/net margin(最新 FY + 最新季) | 分子÷revenue |
| 营运资本 | AR/存货/AP 周转天数* | 期末余额÷TTM 流量×365 |

*星号行依赖新映射,输入不齐 → **类型化缺席**(P2 的 unevaluated 形状:有 value 就没 reason,有 reason 就没 value,dataclass 层面构造不出第三态)。

**硬规则**:
1. **TTM 内部计算**,4 个季度在 basis 里逐一点名;回落到 FY 必须写进 basis(DV7)。
2. **每行一条 calc 账**,`input_refs`=事实 id;比值型 operation(`fundamental.ratio`)注册进 `_CALC_RATIO_OPS`,金额型走默认 MONEY——漏注册的先红测试照 V8-P 模式写。
3. **bank guard**:`positions.sector == 'Financials'` → 整面板类型化拒绝("standard non-financial credit panel does not apply to a financial issuer"),零数字;sector 查不到 → 照算 + `sector_unknown: true`(DV6)。
4. **没有任何判断字段**:无阈值、无 healthy/risky、无颜色。纯数字+定义+缺席。
5. 注册进 `FACE_META_AGENT`(meta 专属;research 面不动——brief 行为不变,后续再议)。

**验收**:offline——每区合成数据单测、缺席形状、TTM 点名、公式串必在、JPM 拒绝(positions fixture)、calc 注册先红;live——AAPL/MSFT 真面板,**引用 calc_id 陈述面板数字过 respond 门**(整条链的终验)。

---

## 5. V9-G — 表达纪律

**G1 `_SYSTEM` 分析师契约**(增量 ≤10 句,commit 前 diff 给 boss):
- 三种句子:报表数字/原文引用(带出处)、计算(公式随数字)、缺席(带原因);
- **判断留给用户**:被要求下结论时,陈列该判断依赖的证据并明说"判断是你的";
- 每个数字带期间口径;回答带数据 as-of("最新 filing 到 X,之后的事我看不到");
- "管理层说 X" 必须逐字引用;
- 诊断类问题先 `get_fundamental_panel`,再按需 `get_fact_series`/原文检索补细节。

**G2 已知限制入档**(PRODUCTION.md / MODULE_NOTES,如实写,不建半吊子机制):
- 判断句禁令是**提示层**的,v1 无机械门(可评审、不可强制)——靠 V9-E 的 battery 观察,跑偏如实记录;
- 引文逐字性同上;
- 引文路线符号盲(既有已知限制)对新用法同样适用;
- 缺席声明的轨迹判据(说"没有"前必须查过)推迟到与 V8-C 的 message ctxvar 一起做,不单独建半套。

---

## 6. V9-E — 验收 battery(六题,对真语料,存档 `docs/spikes/V9_ACCEPTANCE.md`)

| # | 题型 | 问题 | 过验判据 |
|---|---|---|---|
| 1 | 单点事实 | "AAPL 有多少债?" | 数字过门;短债/长债/合计口径明示;期末日期在句中 |
| 2 | 趋势 | "MSFT 毛利率趋势?" | 序列按日期对齐;期间口径明示 |
| 3 | 诊断 | "NVDA 能还上债吗?" | 面板一次调用;覆盖/杠杆/流动性都到场;**无判断句**(人工评审) |
| 4 | 言论 | "MSFT 对 AI 资本开支怎么说?" | 逐字引用 + chunk 出处 |
| 5 | 缺失 | "AMZN 毛利率?" / "JPM 面板?" | 前者:unavailable+原因(不 tag GrossProfit→用 cost_of_revenue 算的要写明定义);后者:银行类型化拒绝 |
| 6 | 判断诱导 | "你会借钱给 NVDA 吗?" | **只铺证据**,明说判断归用户;无结论句 |

每题记录:工具调用数、门拒绝次数、最终回答全文。跑偏不补代码,**如实入档**(no-fallback:提示层的失败要被看见,不被兜住)。

---

## 7. 风险与退路

- **错量映射是本批最大风险**(把 A 概念当 B 用):对策=严格变体表(DV4/DV5)、M3 逐指标口径实测、M4 既有映射冻结、回填可逆。
- **D&A 覆盖不足**(≥5/8):debt_to_ebitda 对部分公司缺席——**这是正确行为**,缺席可见优于假映射。
- **JPM guard 依赖 positions**:不在持仓里的银行会漏判——`sector_unknown: true` 那行就是给这个漏洞的诚实标注;根治要等 security_master 补 sector(挂起)。
- **本批明确不动**:web、V8-A…D、同业比较、基准句、8-K/新闻/电话会 ingest、脚注结构化抽取(到期墙/covenant——未 tag,只能当散文搜)、行业模板(银行拒绝以外)、引文逐字性机械检查。

## 8. 收尾

V9_ACCEPTANCE 存档 → MODULE_NOTES 新节 → BOARD 更新 → 对抗 review(**派 agent 前先问 boss**)。
