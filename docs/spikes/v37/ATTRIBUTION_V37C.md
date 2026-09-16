# C 轮两套 log 的错误归因：五类，逐条对 log（2026-09-16）

> **问题**（用户 9/16）：检查每一个 log，回答每处错误属于哪一类——主分析师分配任务错了；域分析师用错了工具；工具本身的答案错了；工具答案对、最后的回答写错了；validation 把正确的内容误判了。用 log 证明。
> **材料**：`V37C`（gpt-5.4-mini）与 `V37C_sol`（gpt-5.6-sol）两轮共 40 个 session 的 `agent_steps` 全量（库 `exposure_battery`、`exposure_battery_sol`），`tools/` 下的脚本，另两个本次写的只读工具（见 §6）。代码未动。
> **引用格式**：`mini Q08 seq24` 指 mini 轮 Q08 的第 24 步；事实 id 可在对应库的 `facts` 表查到。

## 0. 结论

| 类 | 代号 | 让题目没出答案（决定性） | 让假陈述到了读者面前（源头） |
|---|---|---|---|
| 主分析师派错任务 | A | 0 | 0 |
| 域分析师用错工具 | B | 0 | mini 1 · sol 1 |
| 工具答案错，或工具没把点名要的数交出来 | C | 0 | **mini 7** · sol 2 |
| 工具对，最后写错 | D | mini 1 | mini 3 · sol 2 |
| validation 误判正确内容 | E | **mini 5 · sol 2** | sol 1 |
| 代码崩溃（不在五类里） | — | mini 1 | — |

**没出答案的 9 题，7 题的决定性原因是 E。**剩下两题：mini Q02 是主分析师自己写错（D），mini Q13 是代码崩溃。
**到了读者面前的 17 条假陈述（mini 11、sol 6），9 条源头是 C。**其中 7 条是 mini 在工具没把数交出来之后自己猜的：工具把分析师点名要的「上一期净 beta」「余量排序」扣下，分析师拿不到就断言「两期相同」或凭眼睛排序。

两个最重的系统性原因，都有重放证据（§6）：
1. **C：工具把分析师点名要的数藏起来。**run 工具的上限按事实生成顺序截断，`return` 里点名的标量排在中间表格之后，于是被扣下；digest 又在截尾之前就把所有图形登记成「已显示」，分析师照提示收窄重跑，同样的读数被当作重复吞掉。
2. **E：门的误报。**措辞表收进了模型起的节点名和 `pick` 拆出来的名字；否定句里的最高级；两段式日期、表头日期、引文里的日期；「1y」这类窗口简写；公司名与代码混用；交接第三查不认 `id@日期`。

A 在 mini 上出现 5 次、sol 上 1 次，都没有单独致命，但都让后面的分析师从错的问题出发。B 很常见，多数被工具的拒绝挡住，少数一路走到答案里。

## 1. 判定口径

- **A**：派单的主体、域或问法本身有错，例如把问题要的比较交给不会做的域、用公司全名当主体、漏了问题里的指令。
- **B**：域分析师写的程序或参数与意图不符，例如漏了 `months: 3`、窗口写成 `1y` 却命名成十日、去 10-Q 的 Item 7 找 MD&A、从错的表里取键、用字面量乘数把自己算的数写进账本。
- **C**：工具返回的值、身份或单位本身有问题，或工具算出了却没有交给分析师。
- **D**：交到手里的事实是对的，分析师的 finding 或主分析师的散文写错，例如读反符号、没见到第二个值就说相同、凭眼睛排序、推理错。
- **E**：交接核对或门拒绝了一段本身正确的文字。
- 每处错误先定「决定性」的那一类，同一链条上的其他类记作上游或次因。拒绝一段本来就错的文字不算 E，记作核对拦对了。

## 2. 没出答案的 9 题

| 题 | 决定性 | 证据 | 上游 |
|---|---|---|---|
| mini Q02 | **D** | seq36 主分析师写「The book’s beta to USO is 0.33×」，所引 `f_3ed7a65f8e0c` 是 `XOM.beta.USO`；seq38 改成「against a positive USO beta of 0.33×, the book has some oil sensitivity」。去掉向量标签事实后重放 seq38，V2 仍拒这句：「this figure is XOM's own (XOM.beta.USO); the sentence says it is the book's」 | B：`book_market_risk` 分析师把「账簿对 USO 的 beta」算成 XOM 自己的（seq28 `price.beta(XOM, benchmark=USO)`）；E：「not dominant」被当成最高级；C→E：`vector(entries={USO:…})` 把 USO 铸成主体 |
| mini Q06 | **E** | 利润分析师的差额 finding「$12.06B, $16.61B, $15.55B [f_42dbe969c1ac@…]」是对的，seq11、seq14 两次因措辞「pretax income」挨着 `pretax_income.subtract.net_income` 被拒；主分析师拿不到这组数，自己心算写成「$15.54B」，门拦对（seq28 holds $15.55B）；「1y window」的 1 被判来路不明 4 次 | B：价格分析师用 `price.volatility(window_days=252)` 冒充「一年前」（seq4） |
| mini Q07 | **E** | seq30、seq32「AAPL had the largest weight increase」被 V1 拒，拒绝信说「AAPL holds no end place … 2 of 10 on issuer_exposures.weight」；而权重变化排序里 AAPL 是 1/3（`f_4c161962471e`），它的度量名 `subtract(issuer_exposures.weight, …)` 含「subtract」，句子里没有这个词，被 V1 排除 | A：派单主体给的是 `port_001` 而非三只代码；B：现金转换程序 5 次类型错（seq4/7/10/13/15） |
| mini Q10 | **E** | seq35、seq37 两次 `period_mismatch 'year-ends'`，句子是「those readings were quarterly, not fiscal year-end」 | A：把「rates_shock_up 压力情景」派给假设交易域，分析师把 `RATES_SHOCK_UP` 当代码交易（seq23/25/28）；D：覆盖率 37.7247 被写成「37.73」两次（seq12、seq17） |
| mini Q13 | **代码崩溃** | seq29、31、33 三次答案 md5 相同；修复分支第二次重发只跳出工具循环，下一次请求带着没应答的 `repair_answer`，provider 返回 400 | C：买入 TLT 被拒「no_sector: TLT has no sector on this desk」，而 TLT 本来就是持仓；D：分析师与主分析师把只含卖出腿的情景写成「卖出并买入 TLT 之后」；E：seq29–33 的 `change_conflict` 误报恰好挡住了这句 |
| mini Q17 | **E** | seq52、seq54 的「Aug. 31」「Sept. 11」「Sept. 10」「Sept. 2」被当成数字对段落报 `mark_mismatch`；V6 只认三段齐全的日期 | B→D（潜在）：价格分析师写 `window: "1y"`、节点却叫 `aapl_ret_10d`（seq34），五条事实是一年期相对收益，主分析师照节点名写「ten-day relative return 27.0%」 |
| mini Q18 | **E** | seq19 `measure_mismatch 'factor contrib'`（措辞来自分析师给失败节点起的名字 `factor_contrib`）与「I cannot name the largest and smallest contributing factor」被当成最高级 | B：分析师在对账表上找运行级键（seq4「$recon holds no figure 'exposure_metrics.alpha'」）；D：它的报告里有「factor contribution sum −0.47%」「alpha plus residual 0.85%」，两者之和正是组合收益 0.38%，却把对账两行报成做不到 |
| sol Q05 | **E** | seq45 唯一的问题是「March 29, 2025」被判为没有事实带着的日期，而这句引用的段落 `f_727421a3e89f` 原文就是「ended March 28, 2026 and March 29, 2025 (in millions)」，账本上还有 64 个段落含这个日期 | E：seq43 的 12 条是表格数字加了「million」，原文是「$142,263」、单位在表头；C：一段逐字引文对不上，是因为段落抽取把标签和数字粘在一起（`Accessories7,901`）；B：分析师曾试图用 `scale(factor=0.5126…)` 把自算份额塞进程序，工具拒了 |
| sol Q13 | **E** | seq74、seq76 `subject_mismatch`：「It did calculate a half-NVIDIA sale of $218K …, but the visible scenario still shows TLT at $646K」用公司名 NVIDIA、代码 TLT，规则只认代码 | B：买入腿参数不合 schema（seq13），分析师用尽轮数；C：限额分析师三次「computed but withheld from the digest」（seq33/36/39） |

## 3. 到了读者面前的假陈述

| 轮 | 题 | 句子 | 事实实际是什么 | 源头 | 链条 |
|---|---|---|---|---|---|
| mini | Q01 | 「it is not growing faster than revenue across the same quarterly windows」 | 同段列出的七个窗口里，2025-03-31、2025-06-30、2026-03-31 三个存货增速高于收入 | D | 分析师 finding w4 就这么写，交接放行，主分析师照抄 |
| mini | Q08 | 「exposure to the market proxy used for QQQ-style risk is -86.0%, so the book is short that proxy」 | `net_beta.equity_down` = 各股指因子 beta × −1 之和（`analytics/integration._RISK_SENSE`），−0.86 表示股指下跌时账簿亏钱，即净多头 | D | 主分析师派单时就假定存在「QQQ 代理」（A）；读法说明没交代这个符号约定 |
| mini | Q08 | 「the prior run’s exposure is also -86.0% [f_1318e759a4f9] … unchanged」 | 上一期是 −0.857，id 属于最新一期 | **C** | 重放：seq24 的 `prev_exposure` 被工具上限扣下，上一期表里那一行被 digest 截掉；seq29 再次被截；分析师从没见过 −0.857，却断言相同（D）；核对看不出「prior run」指错了期 |
| mini | Q08 | 「the book is materially short QQQ-style market exposure」 | 同第一条 | D | 结论建在第一条上 |
| mini | Q09 | 「the three-year low of -75.83 … high of -56.36」 | min/max 取自 2020–2025 六个年度点，跨五年 | B | 分析师没加 `months: 3`、在年度序列上取极值（seq4）；两条标量不带窗口（C），V4 查不到；主分析师套用了问题里的「three-year」 |
| mini | Q11 | 「ranked by smallest room left to warning as LLY, MSFT, AAPL, JPM …」 | MSFT −1.04% 第一，LLY −0.54% 第二 | **C** | 重放：排序节点的事实在 seq4、seq7、seq13 三次都被工具上限扣下，seq7 有 76 个、seq13 有 86 个图形被当作已显示吞掉；分析师 caveat 自述「The ranking was inferred from the displayed current and warning figures」（D）；名字加 id、不带数字的排序句 V1 查不到 |
| mini | Q15 | 「The ranking from smallest room to warning tier to largest is AAPL, MSFT, JPM, LLY …」 | MSFT、LLY、AAPL、JPM（各家预警档不同，LLY 是 12%） | **C** | 限额分析师四次运行都有扣下（seq12/15/20/23），它按当前值排序（D） |
| mini | Q15 | 「AAPL, which is closest to its warning tier」 | 最近的是 MSFT | **C** | 同上 |
| mini | Q15 | 「the names that are slowest to unwind are not the ones closest to issuer concentration limits」 | LLY 在两个排序里都是第二 | **C** | 同上 |
| mini | Q16 | 「the latest and prior readings are identical on that metric, so the change is zero」 | −0.8599 对 −0.8574，变化 −0.24% | **C** | 重放：seq4 的 `net_beta_prev` 与 `change_net_beta` 被工具上限扣下，上一期表里那一行被 digest 截掉；seq10 又被截，而且 `pick(key=portfolio.integration.net_beta)` 漏了风险后缀（B） |
| mini | Q16 | 「the book is not riskier now on that net-beta leg; there is no change driver to isolate」 | 建在上一条上 | **C** | 同上 |
| sol | Q02 | 「FCF/debt: 254.0% … still indicating annual free cash flow substantially exceeded debt」 | 同一分析师 seq4 的 `total_debt` 是缺席（「no period grid for total_debt」），`fcf_to_debt` 却有值，分母只含短端 | **C** | S1 当时判为不改留下的口子 |
| sol | Q04 | 「The available evidence does not separately quantify product mix, so it does not support calling the broader margin expansion mix-led」 | 桌子读到的 10-K 原话（`f_e0d56452af88`）：毛利率上升「primarily driven by favorable product mix and improved cost of production, partially offset by lower realized prices」 | **E** | 申报分析师 seq25 的 w1 就是这句；该 brief 只因 w3 的否定句「not twelve quarterly points」被 V4 误拒；修复时分析师删掉了第 1、2 行（seq27 `uncovered_want`，D）；交接取最后一次提交，w1 没到主分析师手里；`read_report` 读到的是 refused、0 字符 |
| sol | Q09 | 季度应收、存货、应付天数与现金周期整张表 | 约放大 4 倍：2023-09-30 应收天数季度版 120.34，年度版 28.10 | **C** | `formulas.py` 的天数公式固定乘 365，分母是 3 个月的收入 |
| sol | Q09 | 「The latest sequential deterioration …」 | 周期从 −215.58 到 −227.86，更负，是改善 | D | 分析师的 brief（seq35）里没有这句，是主分析师写的 |
| sol | Q09 | 「the inventory increase outweighed the payable benefit」 | 存货天数 +14.89，应付天数 +25.41 | D | 同上 |
| sol | Q18 | 「No—the latest-run attribution does not reconcile … gap −0.85%」 | 因子贡献合计 −0.47% + alpha 0.01% + 残差 0.84% = 0.38%，正好对上 | B | seq6 `factor_sum = method(book.reconcile, key=portfolio.reconcile.sum_of_position_contributions)`：节点叫因子合计，取的是持仓合计；工具算术无误，结论建在错的量上（D） |

**另记一处来源违规（值对）**：sol Q19 seq21 写的是 `aws_2023 = mul(total_2023, 0.157896)`，份额是分析师在桌子外面算好、再用字面量乘数写进账本的，门看到的是一条「桌子算出的」15.8%。数值与 10-K 表一致，但这条路径能让任何心算结果被当作桌子的数。归 B，工具允许单边字面量乘数算 C。mini Q19 seq13 则把名叫 `aws_sales` 的节点取成了总收入，算出占比 100%，主分析师没有采用。

## 4. 请求了、桌子也做得到，却没交付的项

| 轮 | 题 | 项 | 类 | 证据 |
|---|---|---|---|---|
| mini | Q01 | 季度应计比率 | B | seq4 没加 `months: 3`；sol seq4 加了就是季度 |
| mini | Q01 | 应收是否快于收入 | E | seq6、seq8 因「accounts receivable」挨着 `accounts_receivable.pct` 被拒；被拒那句本身也有错（D） |
| mini | Q01 | 到档余量 | C | seq23 余量被 digest 截掉；seq28、seq30 收窄重跑，65、63 个图形全部被当作已显示吞掉，读入只有 196、159 字符 |
| mini | Q03 | 最新的回购授权 | B | 只查了 10-K（seq8、seq10），给出 1 月的 585 亿；7 月 10-Q 是 993 亿（sol seq13–16），答案带了日期 |
| mini、sol | Q04、Q20 | 毛利率、营业利润率 | C | `gross_margin` 只认 `gross_profit`，Lilly 报了收入和营业成本（sol Q04 seq7 取到了），公式没有「收入减营业成本」这条路；拒绝原话还让分析师去「call describe」，这个动词不在它的面上 |
| mini | Q05 | 产品与地区收入表 | E | 10-K 段落里就是「iPhone$209,586」、表头「(dollars in millions)」，分析师写「$209,586 million」被判来路不明（seq12、seq16） |
| mini | Q07 | 现金转换排序与变化 | B | 五次类型错；拒绝信「latest takes a series: add last_n」把分析师引向错的写法（C），K2 没有取前一期标量的示例 |
| mini | Q08 | 三家各年资本开支强度与 ROIC | B、D | seq11 已拿到各年序列；seq13 排序程序引用了上一个程序的绑定；seq17 的 caveat 承认有序列，仍把五行全报做不到 |
| mini | Q09 | 十二个季度、10-K 措辞对比 | B | 没加 `months: 3`；`read_filings` 两次同时传 query 和 item（seq9、seq14），用尽轮数 |
| mini | Q10 | 各财年末债务、覆盖率、压力情景的说法 | A、B、D | 压力情景派错域；净债务只取到两个季度点，而 sol 用 `at()` 取到了财年末；覆盖率 37.73 两次写错 |
| mini | Q12 | 启动两家银行的准备 | A | 派单用公司全名，也没有「开始准备」这一行 |
| mini | Q13 | 买入 TLT 的一腿 | C | `no_sector: TLT has no sector on this desk` |
| mini | Q14 | 市场与个股拆分、前三大拖累 | E | seq16、seq18 的 `change_conflict`（一句里两个份额）与 V1（「最大拖累」对应排序末端）；被拒两行本身也有问题：拆分用的是最新单日运行、前三按收益率而非贡献（D） |
| mini | Q14 | 窗口内的申报 | B | 10-Q 的 Item 7 查了四次 `section_not_found`（seq6–14），MD&A 在 Item 2 |
| mini | Q18 | 对账与缺口 | D | 见 §2 |
| mini | Q19 | AWS 占比 | B | seq13 取成总收入；seq17 对流量用 `at` |
| mini | Q19 | AMZN 对账簿的贡献 | C | seq28 digest 扣下 |
| sol | Q10 | 账簿利率敏感度 | E | seq32、seq34「latest 0.86% … below 0.89% in the prior run」方向写对，检查把两期 calc 配反，判为相反 |
| sol | Q12 | 摩根大通自己的 ROE 与权益乘数 | A、D | 派单只问比较；分析师 seq11 手里有年度标量，没报 |
| sol | Q14 | 峰谷日期、拆分、前三 | B、C | 程序请求不存在的节点（seq4/8/24/25/29）；峰谷以字面量返回、不是事实，分析师也没用解释事实的窗口 |
| sol | Q17 | 新闻时点与收益窗口对比 | C | 搜索额度 5/5 用尽（seq35–44） |

sol 把年度期当作 TTM 的三处（Q02、Q03、Q07 的变化）都在答案里写明了端点，记 B，不计错话。

## 5. 只耗了成本的拒绝

以下拒绝后来被绕过去了，没有改变结果，但每次都多花一次 completion 或一次派单。

- **交接第三查不认 `id@日期`（E）**：sol 7 份 brief 共 36 次（Q02、Q03、Q09、Q10、Q19、Q20 等），正文检查接受同样的写法；分析师改用 `at()` 标量绕开。
- **措辞表误报（E）**：「net beta」「pretax income」「gross exposure」「reconciled total」「total revenues」「capex intensity」等，mini 重放 17 次，sol 10 次。
- **两个水平量写在一句里被当成变化（E）**：mini Q13、Q14，sol Q07、Q08。
- **搜索结果的发布日期、引文里的日期（E）**：sol Q03、Q17。
- **分析师转写舍入错（D，核对拦对）**：sol Q07「85.5%」对 85.6%，sol Q08 ROIC 三次，mini/sol Q10「37.73」对 37.72。
- **工具扣下后多派一轮（C）**：sol Q11、Q15、Q16 都靠主分析师再派单、分析师改写成很小的程序才拿到。sol 能拿到，是因为被工具上限扣下的事实从没进过 digest，不会被当作已显示；mini 每次都连两整张表一起要。

## 6. 两处工具缺陷的证据

本次写了两个只读工具：`digest.py` 把一个 session 摊平成可引用的步骤；`replay_digest.py` 按记录顺序对事实重放 `F.cap` 与 `digest.render`，并在调用之间带着 `seen`，得到分析师当时读到了什么。重放出的字符数与记录的读入接近，例如 mini Q08 seq24 为 15090 对 15361。

**缺陷一：`return` 点名的标量被工具上限扣下。**`fact_adapters.adapt` 用 `F.cap` 保留前 N 条事实，中间节点（两整张 48 行的分析表）排在前面，`return` 里的标量排在最后。

```
mini Q08 seq24  made 98, tool kept 65   f_fbc675fce29e (prev_exposure): held by tool cap
                                        f_d45f1123866b (prior table row): cut by digest fit
mini Q16 seq4   made 129, tool kept 75  f_c02b2f8d7c44 (net_beta_prev), f_5cd2f5e8d2e0 (change): held by tool cap
mini Q11 seq4/7/13                      ranking facts: held by tool cap in all three calls
```

所以扣下提示里「run the same program again with `return` naming only the nodes you need」做不到它说的事：中间节点的事实仍然排在前面。

**缺陷二：digest 在截尾之前登记「已显示」。**`digest.render` 先 `tell_apart(items, seen)` 再 `fit`，被 `fit` 剪掉的图形也记进了 `seen`；下一次调用里相同的读数被合并掉，分析师看不到。

```
synthetic: call 1 shows 13 of 120, holds back 107; call 2 asks for two held-back rows → figures left: []
mini Q01 seq23  room figures f_4309…, f_a189…: cut by digest fit
mini Q01 seq28  digest shows 0 figures (93 chars), 65 swallowed as seen   (recorded read: 196 chars)
mini Q01 seq30  digest shows 0 figures (93 chars), 63 swallowed as seen   (recorded read: 159 chars)
```

其余 C 类：天数公式固定 ×365（sol Q09）；`gross_margin` 没有收入减营业成本的路径（Q04、Q20）；`fcf_to_debt` 在总债务缺席时仍出值（sol Q02）；情景买入要求行业，而现有持仓 TLT 没有行业（mini Q13）；向量条目标签被铸成主体（mini Q02）；`pick` 把带点号的键拆成度量加主体（Q08、Q16 的措辞误报）；净 beta 的单位类是 RATIO；段落切块丢了句首或把标签和数字粘在一起；`mul`/`scale` 接受单边字面量（sol Q19）。

## 7. 按归因的修法方向

- **C 两处缺陷先修**：`return` 点名的节点优先进入工具上限；digest 只把真正显示了的图形记进 `seen`。这两处解释了 mini 17 条错话里的 7 条，也解释了 sol 多派的三轮。
- **A2 修复分支的崩溃**：一处代码。
- **E 的八类误报**：都是查表规则的细化，用这两轮所有受门文字建回归语料，已知真拒绝不许丢。
- **D 里可以变成查表的**：「相同 / 未变」要求挂两个事实；期次词对着事实所属的 run；名字加 id 的排序句也要对排序查。
- **B 里可以交给 skill 的**：季度用 `months: 3`；10-Q 的 MD&A 在 Item 2；「十个交易日」用 `window_days`；`net_beta.<risk>` 的符号含义；取前一期标量的写法。字面量乘数这条路需要在工具上关掉。
- **A**：主分析师派单时用 BRIEFING 里的代码；压力情景归 `book_market_risk`；问题里的指令（「开始准备」）要落成一行。
