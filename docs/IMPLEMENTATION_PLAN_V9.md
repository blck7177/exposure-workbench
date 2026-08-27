# Implementation Plan V9 — 报表分析师批(v2):公理原语 + 公式登记 + 只铺证据

> **状态(2026-08-25)**:**V9-M 数据地基已完成**(`09ec187` 概念拆分、`131305c` 新指标与口径断言;864 offline / 177 live)。V9-F 的第一版草稿(方法工具 + TTM 回落 + 手写债务配方)**作废,未提交**——它是本文 §0 诊断出的病灶样本。本文自 §2 起为改写后的执行计划。
> **性质**:让 agent 以 credit/fundamental analyst 的方式回答报表问题,每句可溯源、判断留给用户。改写后的核心变化:**规则收敛到四条会计公理,方法定义变成有出处的数据,分析交给 intelligence;面板从"方法工具"降级为同一批原语上的便捷查询。**
> **一句话**:给 agent 的不是预制面板,是一台**算不出类型错误的数**的计算器,和一份**有出处的公式表**。
> **上游依据**:`docs/spikes/V9_FORMULA_BASIS.md`(公式出处与语料实测);`dev_note/portfolio-demo/analyst-skills/` 05(生产系统实况)、09、11;2026-08-25 两轮设计讨论(病根诊断 + 三分法)。

---

## 0. 诊断:为什么第一版是错的(改写的理由,不是装饰)

三根轴上同一种病——**表示层丢信息,规则层打补丁**:

| 轴 | 数据里有什么 | 查询层做了什么 | 补丁的样子 |
|---|---|---|---|
| 概念 | 每个 us-gaap 概念是一个确切的量 | ~~多概念折叠成一名~~(**M1 已治**:187 行冲突→0) | ~~按申报时间挑~~ |
| **期间** | 每个事实带真实区间 `[start,end]`;AAPL 现金流有 91/182/273/364 天四种 | `period_ladder` 折叠成 `{quarterly, annual}` 枚举,**H1/9M 事实被分类后丢弃**(`period_ladder.py:72-84,101-140`) | `derive_q4` 特例(:143)、草稿里的 `ttm()`/`ttm_or_fiscal_year()`/basis 道歉串 |
| **包含** | XBRL calculation linkbase 写明什么包含什么 | **ingest 时整个丢弃** | 草稿里 8 条手写 `DEBT_RECIPES`、`_pick_as_of()` |

罪证是 `derive_q4` 自己:`Q4 = 年度 − (Q1+Q2+Q3)` 就是区间减法——**通用规律已在代码里,却被写成特例**;Q2 = H1 − Q1、TTM = FY − 去年H1 + 今年H1 是同一规律的其他实例,却各自要新函数、新回落、新解释。

同一份 AAPL 数据,两种设计的产出:草稿给出 `FY 2025-09-27(TTM unavailable…)`——十个月前的旧年度数加一段道歉;区间代数给出 **TTM 140.222 截至 2026-03-28**(= 111.482 − 53.887 + 82.627)与**被丢弃的 Q2 = 28.702**。**规则更少,分析严格更强**——问题溶解,不是被解决。

**判据(写进每次 review)**:一条规则里出现"最新的 / 优先 / 回落 / 挑哪个",它在编码**发行人行为**,O(发行人×怪癖),不该存在;是**恒等式**,才是结构,O(1)。

---

## 1. 已定决策

沿用:DV1 判断句不输出 · DV2 最小集边界(同业比较第二波) · DV3 不造带行业定义名的指标 · DV4 D&A 三变体不并 · DV5 银行净利息不并 · DV6 bank guard 源=`positions.sector`,未知不拒绝但声明 · DP1 · DP4 · no-fallback。
**撤销**:~~DV7(TTM 优先 / FY 回落须可见)~~——二分法本身溶解;basis 永远写**实际推导出的区间**。

| # | 新决策(2026-08-25) | 内容 |
|---|---|---|
| **DV8** | **三分法** | ①世界结构→代码(公理,对所有发行人恒真);②方法定义→数据(有出处的公式登记表);③分析→intelligence(写不成失败测试的);④**发行人行为规则不得存在** |
| **DV9** | **带公理的计算器,不是裸计算器** | 证据:PoT 把算术错误消除 88%,但选数错误占 FinQA 错误的 76%;裸计算器会兴高采烈算出 `82.700 + 8.310 = 91.010`。计算器只剜掉"良构的错误"那一块(门抓不住的那块),其余组合全部自由,每次落账本 |
| **DV10** | **面板降级** | `get_fundamental_panel` = 公式登记表在同一批原语上的批量求值,省预算的快捷方式;**无特权通道**,agent 可绕开自由组合 |
| **DV11** | **包含边先播种后验证,不等完整 linkbase ingest** | 债务/权益/租赁三族约 8 条边,是**数据**;每条边由语料数值验证(AAPL:74.404+8.310≈82.700);完整 linkbase 摄取列后续 |
| **DV12** | **容差是参数不是补丁** | 区间边界吸附 ±6 天(52/53 周财年);包含验证相对容差按语料实测定(AAPL 债务差 0.014/82.7=0.017%),写进代码常量并注明测量来源 |
| **DV13** | **草稿处置** | 未提交的 `analytics/fundamental_panel.py` / `services/fundamental_panel_service.py` / `tests/test_v9_panel_algebra.py`:`Amount`/`Missing`/`ratio`/`add` 与 formula/basis 渲染**保留**;`ttm`/`ttm_or_fiscal_year`/`DEBT_RECIPES`/`total_debt`/`_pick_as_of` **删除**,其不变量在 A 段以正向测试重表达 |

---

## 2. 现状基线(实读)

| 事实 | 坐标 |
|---|---|
| 事实表忠实存区间:`period_start`(INSTANT 为 NULL)/`period_end`/`dimensions_hash`/`source_accession`/`value`/`unit`;账本 `params`/`result`/`input_refs` 皆 JSONB,**可承载类型与区间,无需改表** | `models.py:674-682` · 活库 |
| `period_ladder.classify_duration` 识别 QUARTER/HALF/NINE_MONTH/ANNUAL/INSTANT,`build_ladder` 只接受 quarterly/annual/instant,**HALF/9M 被丢弃**;`derive_q4` 是区间减法特例 | `period_ladder.py:72-84,101-140,143-190` |
| ladder 的消费者只有 `calc_service.load_fact_series`(recipe 经它) → 新引擎可**并行存在**,不需先拆旧路 | `calc_service.py:60-127` · grep |
| M1 后每个 metric = 一个量;碰撞探测器(live)守着未拆的 5 个多概念指标;口径断言 56 条 | `test_v9_concept_collisions_live.py` · `test_v9_metric_basis_live.py` |
| 债务部件语料实况:AAPL 有 total/noncurrent/current/CP;GOOGL 的 `long_term_debt_total` 只在 2025-12-31,`noncurrent` 到 2026-06-30(**跨时刻拼会得到总额<部件**);JPM 只有 `short_term_borrowings`;XOM 无 total 只有 current+debt_current | 2026-08-24 SQL |
| 现金流事实:AAPL 只有 Q1 离散 + H1/9M/FY 累计;MSFT 四个离散季 —— **同一行为发行人间不同**,这正是公理而非规则该处理的 | 2026-08-24/25 SQL |
| `_CALC_RATIO_OPS` 白名单决定 calc 值的单位类;新 operation 必须注册 | `numeric_verification.py:437` |
| respond 门:引用存在 + 数值核对;**从不检查组合的经济合法性**——那是 DV9 计算器的职责 | `meta_tools.py:152-218` |

---

## 3. 排程(单 lane;每段独立可合并)

```
V9-A 公理原语(1.5–2d)  A1 区间引擎 → A2 get_flow → A3 get_balance_sheet
                          → A4 包含边表+不重叠合成 → A5 带类型标量计算器 → A6 derive_q4 parity
V9-D 公式登记(0.5d)     D1 registry(数据+出处) → D2 evaluate/list 工具
V9-P 面板降级(0.5d)     P1 get_fundamental_panel = registry 批量求值 + bank guard
V9-G 表达纪律(0.5d)     G1 _SYSTEM 契约 → G2 已知限制入档
V9-E 验收(0.5d)         六题 battery + 三条回归钉(AAPL TTM 140.222 / AAPL 总债 84.697≠91.010 / GOOGL 同刻)
```

纪律:先红后绿;每条新规则过"行为 vs 结构"判据;`_SYSTEM` diff 提交前给 boss。

---

## 4. V9-A — 公理原语(rules 全部住在这里,四条)

```
R1 流量可加   value[a,c] = value[a,b] + value[b,c]      (相邻区间可加减)
R2 存量同刻   余额只与同一时刻的余额组合
R3 覆盖不重叠 求和项在包含图上互不为祖先
R4 同一范围   dimensions_hash = ''(已有)
+ 重述取舍 _pick_latest(已有,正交)
```

**A1 区间引擎** `analytics/interval_algebra.py`(纯函数)
- 模型:同一 (company, metric, scope) 的流量事实 = **边界图**上的带值有向边(`start−1天 → end`);边界按 ±6 天吸附成簇(DV12)。
- **任意目标区间 `[a,b]` 的值 = 从簇 a 到簇 b 的带符号路径**:正向边 +,反向边 −。`Q4 = FY − 9M`、`Q2 = H1 − Q1`、`TTM = FY − 去年H1 + 今年H1` 全是同一算法的实例。取**边数最少**的路径(输入最少 → 误差最少);同一区间多份事实按 `_pick_latest`。
- 接口:`derive(facts, target_start, target_end) -> Amount | Missing`;`latest_window(facts, months=12)`:**最近的、可推导的** N 个月窗口(不是"最新 FY 回落"——不存在回落,只有"可推导的最近窗口",basis 写真实区间)。
- 输出带:值、`fact_ids` 与各自符号、区间、路径描述(人话 formula:`FY2025 − H1'25 + H1'26`)。
- 测试(先红):AAPL 形状五行事实 → TTM=140.222 截至 2026-03-28、Q2=28.702;MSFT 形状四离散季 → 直接四季和;跨缺口不可达 → `Missing` 并点名缺口;三个季度不得被当一年;吸附容差边界(364/371 天财年)。

**A2 `get_flow(ticker, metric, months, ending="latest")`** —— READ 工具,A1 的服务包装;落账本 `derive.interval`(MONEY),`input_refs` = 带符号的 fact_ids(符号进 params)。

**A3 `get_balance_sheet(ticker, at="latest")`** —— R2:返回**一个时刻**的全部 INSTANT 指标;`at="latest"` = 有余额事实的最新期末;该时刻缺席的指标**逐个列出并附其最近出现日期**(GOOGL 的 total 会显示"上次出现 2025-12-31"),**绝不跨时刻代入**。

**A4 包含边表 + 不重叠合成** —— R3:
- `analytics/containment.py`:边表是**数据**(约 8 条:`long_term_debt_total ⊇ {noncurrent, current_portion}`;`debt_current_total ⊇ {current_portion, short_term_borrowings}`;`short_term_borrowings ⊇ {commercial_paper}`;权益族;租赁族 `total ⊇ {current, noncurrent}`)。
- `cover(available_at_instant, family) -> Amount | Missing`:选**反链**(互不为祖先)覆盖族内最多叶子,偏好高节点(项数少);输出 formula = 反链、`uncovered` = 族内无数据的节点(**诚实缺口,不补零**)。取代 8 条手写配方。
- **live 验证边**:每条边在语料里凡父与全部子同刻出现处,`|父 − Σ子| ≤ 容差`(DV12);任何一条边验不过 → 边表红,不上线。
- 测试:AAPL 同刻 → 84.697(`long_term_debt_total + commercial_paper`),**永不** 91.010;只有 noncurrent → `Missing` 点名缺 current;0 值部件算存在。

**A5 带类型标量计算器 `calculate(op, a, b)`**(DV9 的落点)
- `a`/`b` 是 `fact_`/`calc_` id;四则;每个操作数从账本/事实表取回**类型**:`{unit_class, basis: instant(date) | interval(start,end), family_node?}`。
- 拒绝(带类型化原因):两余额相加而时刻不同(R2);两流量相加而区间不相邻/重叠(R1);两余额相加而在包含图上为祖先-后代(R3);单位类不可组合(既有 `_COMPATIBLE`)。**比值跨 basis 允许**(存量/流量是合法的比率),结果 basis 写两者。
- 落账本 `calc.scalar.<op>`;比值注册 `_CALC_RATIO_OPS`;结果类型写进 `params`,让下一次 `calculate` 能读回——**类型随 id 传递**,这就是整个"类型系统"。
- 测试:每条拒绝一测;合法组合一测;类型经两跳仍正确。

**A6 `derive_q4` parity** —— 用 A1 重实现 `derive_q4`,对全语料所有 (company, metric) 断言与旧实现**逐点相同**;通过后旧特例退役。这是"通用规律确实包含特例"的证明,也是 ladder 迁到引擎的第一步(后续 V10 可把 quarterly ladder 整个改为引擎推导,H1/9M 从此进入所有序列工具)。

---

## 5. V9-D — 公式登记表(方法定义是数据)

**D1** `analytics/formulas.py`:`name → {expression, inputs, unit_class, source_url, source_quote, note}`。首批(全部有出处,见 `V9_FORMULA_BASIS.md`):
`ebit = net_income + interest_expense + income_tax_expense`(SEC C&DI 103.01)· `ebitda = ebit + depreciation_amortization`(同)· `free_cash_flow = operating_cash_flow − capex`(102.07)· `net_debt = total_debt − cash_and_equivalents`(注明**非**评级机构口径)· `ebit_interest_coverage` · `debt_to_ebitda` · `debt_to_ocf` · `fcf_to_debt` · `current_ratio` · 三个 margin(分母=该发行人报的收入,**名字随之**)· 三个周转天数(期末余额,注明)。
守卫:每条 formula 必有 `source_url`;表达式只引用 `SUPPORTED_METRICS` 或其他 formula(import 时校验);**不含任何阈值字段**(DV1)。

**D2 工具**:`list_formulas()`(agent 的方法地图)与 `evaluate_formula(ticker, name, ending="latest")`(经 A2/A3/A4/A5 求值,每个中间量各自落账本;bank guard 在此)。agent 也可完全不用登记表、自己声明公式经 A5 组合——**两条路同一原语**。

---

## 6. V9-P — 面板降级

`get_fundamental_panel(ticker)` = 对登记表全部 formula 调 `evaluate_formula`,一次返回;bank guard(DV6);`judgement: none`;每行 = `Amount`(value/formula/basis/calc_id/fact_ids)或 `Missing`(missing/reason/uncovered)。**它没有任何自己的计算逻辑**——测试断言其每一行的 calc_id 都能由 D2 单独重现。

---

## 7. V9-G — 表达纪律(承原计划)

**G1 `_SYSTEM`**:三种句子(事实/计算/缺失,各带出处或公式或原因);判断归用户;每个数带 basis(payload 已自带);as-of 与"filing 之后我看不到";逐字引用;诊断类先 `get_fundamental_panel`,深挖用 `get_flow`/`get_balance_sheet`/`calculate` 自由组合。
**G2 已知限制入档**:判断禁令与引文逐字性为提示层(v1 无机械门);引文路线符号盲(既有);包含边表只覆盖三族(族外的相加不受 R3 保护——**如实写**);完整 linkbase 摄取与 ladder 迁移列后续。

---

## 8. V9-E — 验收

六题 battery(原计划 §6 不变)+ **三条回归钉**(live,先红):
1. AAPL `get_flow(operating_cash_flow, 12)` = **140.222** 截至 2026-03-28,formula 含 `FY − H1 + H1`;
2. AAPL 总债 = **84.697**,任何路径下不得出现 91.010;
3. GOOGL `get_balance_sheet(latest)`:`long_term_debt_total` 列为缺席并标"上次出现 2025-12-31",**不得**与 2026-06-30 的 noncurrent 相加。

---

## 9. 风险与退路

- **区间引擎的边界吸附**:52/53 周财年与日历年混在一个发行人(重述、财年变更)会造出伪相邻——路径搜索限制"边界簇内跨度 ≤ 6 天"且**同一路径不得含两条同区间的边**;异常路径返回 `Missing` 并附路径,不猜。
- **包含边表是捷径**(DV11):族外概念相加不受 R3 保护;G2 如实写,V10 摄取 linkbase 后收口。
- **A5 的类型传播依赖账本 `params`**:老 calc 行无类型 → `calculate` 对其**拒绝并说明**(不是默认放行)。
- **本批不动**:web、V8-A…D、同业比较、基准句、8-K/新闻、quarterly ladder 整体迁移(A6 只做 Q4 parity)。

## 10. 收尾

`docs/spikes/V9_ACCEPTANCE.md` · MODULE_NOTES 新节(三分法 + 四公理写成模块契约)· BOARD · 对抗 review(派 agent 前先问 boss)。
