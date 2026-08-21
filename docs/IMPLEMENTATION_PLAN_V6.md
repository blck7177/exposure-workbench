# Implementation Plan V6 — 两批正交件:窗口够长 · 报告过门

> **状态(2026-08-21)**:**W1–W5 与 G1–G9 全部完成**。offline 717 全绿(批前 702),live 118 全绿,合计 **835**;web typecheck 通过。
> 真实栈实测:`run_96d1614775e7`(port_001 @ 2026-08-20)11 步全通过,风险指标 **824 个观测**(批前 61)、回归 **750 个**(批前 58)、报告 **79 个数字全部过门**。迁移 `v6_report_gate.sql` 已重放。
> **版本**:v6(2026-08-21)。承 V5:V5 修的是算错的数,V6 修的是**算对但不稳的数**,以及**没人检查的那段文字**。
> **性质**:两批彼此正交、可独立合并。boss 指示"先窗口,再 LLM 门,可并行执行"。
> **一句话**:让压力数字的量级值得引用,让唯一裸奔的 LLM 输出面有一道比现有两道更严的门。

---

## 0. 已定决策(2026-08-21,boss 拍板)

| # | 决策 | 内容 |
|---|---|---|
| **D1** | 样本不足 → **不给数** | `min_observations` 30 → 250(约一年共同历史)。不足则因子归因返回空、所有情景进 `unevaluated`,用户看到"未评估"而非一个会摆动 60% 的数。VaR/波动率不受影响(自有更低的下限) |
| **D2** | 报告过不了门 → **不落报告,记明原因** | 零重试。保住 V4 import 豁免的前提「一份报告就是一次 completion」——`daily_reports` 的三个成本列是标量,N 次尝试只会记下最后一次。同时删除 mock 兜底与 JSON 解析兜底 |
| **D3** | 范围限定:**只改窗口长度,不改估计量** | boss 明确「先不继续深入做 quant」。EWMA、GARCH、Kupiec 回测、协方差收缩、因子集改造全部排除,列入 §6 |

---

## 1. 批 W — 窗口:3.3 年,因为数据指到那里

### 1.1 依据(实测,60 次逐日滚动窗口)

| 观测数 | `stress_loss_market` 滚动区间/均值 | 少两个观测的最大摆动 | VaR 尾部观测数 |
|---:|---:|---:|---:|
| **60(批前)** | **61.7%** | **17.7%** | **3** |
| 125 | 25.7% | 5.9% | 6 |
| 250 | 14.0% | 1.5% | 12 |
| 500 | 6.2% | 1.0% | 25 |
| **750** | **3.7%** | **0.7%(0.05pp)** | **37** |

V5 记录的那次 56% 跳变不是异常值 —— 60 个观测的窗口滚动一遍,区间就是 61.7%。

**并且纠正了一个此前的判断**:拉长窗口**救不回单个 beta,而且反向恶化**。max VIF 在任何窗口长度下都不低于 5,且随窗口**上升**(60 obs 时 14.6 → 750 obs 时 18.8),因为 `corr(SPY, QQQ)` 从 0.920 升到 0.948。这是结构性的,不是抽样噪声。「单个 beta 不可引用」这条限制本批动不了。

### 1.2 两把尺子,不是一把

`_LOOKBACK_DAYS` 决定**加载**多少历史,`calc_risk_metrics` 消费其全部(VaR/ES/最大回撤);回归再对其取 `.tail(window_days)`。V5 的配对是 90 日历日产出 61 个观测、`window_days: 60` —— **只多一个余量**,且只抬加载窗口不会移动任何一个 beta。两把必须同时动。

`_LOOKBACK_DAYS = 1200` 而非 1095:三年日历只供给约 756 个观测,对 750 的请求只剩 6 个余量,一次休市或一只持仓缺一根 K 线就会让回归静默缩水。多三个月买到约 10% 的松弛,`tests/test_factor_and_stress.py` 把这对数守住 —— **这条测试在编写时当场抓到了 1095 的余量不足**。

### 1.3 修复清单

| # | 修复 | 落点 |
|---|---|---|
| **W1** | `_LOOKBACK_DAYS` 90 → 1200 | `exposure_workflow.py` |
| **W2** | `window_days` 60 → 750,`min_observations` 30 → 250 | `configs/factor_config.yaml` |
| **W3** | 步骤 3 新增 **adj_close 覆盖校验**(持仓面与因子面),与陈旧/缺失同一条 raise | `exposure_workflow.py` |
| **W4** | 风险步骤记录 `observations` 与 `lookback_days` | `exposure_workflow.py` |
| **W5** | UI 三个 KPI 的硬编码阈值 → 改由**告警**取色 | `apps/web/app/page.tsx` |

**W3 是 V5 留下的坑,由本批的窗口拉长触发**:V5 的 D3 决定 `factor_prices.adj_close` 不回填,于是 295 行里只有 62 行有值;而步骤 3 只校验价格新鲜度、不校验 adj_close 覆盖。面板会静默缩到 61 个观测,run 却报告一个三年窗口 —— 正是「没跑的检查看起来像跑过了」。

**W5 发现的比预期严重**:VaR、波动率、最大回撤三个 KPI **各自硬编码了阈值**(0.035/0.025、0.25/0.18、0.1),是 `limit_defaults` 的陈旧副本,构成**第四份阈值来源**且活在前端 —— 一个改了自家限额的用户,看到的颜色算自别人的默认值。窗口拉长会让回撤那个永远标红(三年期回撤 17.66%)。改为从 `run.risk_alerts` 取色:限额引擎判过什么,页面就显示什么。

**`alertHighlight` 必须收 value**:没有告警可能是「没越界」,也可能是**该检查根本没跑**(观测不足时 `var_95_1d` 为 null)。后者显示绿色又是同一种病,所以 value 为 null 一律中性。

**最大回撤改变了含义**,如实记录:从「近三个月最差回撤」变成「近三年最差回撤」,同一账本 6.24% → 17.66%。它不在八条限额内(不会误触发告警),但它可被 chat agent 引用、且写进报告时没有周期限定。本批的处理是:去掉那个假装判过它的高亮,副标题改为「Worst fall from a peak, over the whole loaded window」,并把 `observations`/`lookback_days` 写进步骤事件。

---

## 2. 批 G — 报告过门:证据集就是它自己那次 run

### 2.1 批前实测

**19 份已持久化的报告中,9 份是伪造的 mock 文本**,已作为报告呈给用户。而 mock 自称「LLM API key not configured」—— 对这 9 份**没有一份**是真的:key 配好了,调用也成功了,是模型返回了解析器不认的东西,被裸 `except Exception` 报成了缺 key。

四条分支都返回**形状与真报告完全相同**的东西,调用方无从分辨。

### 2.2 关键设计:这道门不要引用

`respond` 与 `submit_brief` 要引用,是因为 agent 面对语料库、必须声明它选了什么。**报告没有可选项**:它描述的恰好是一次 run,合法可引用的全集就是那次 run 自己的确定性行。所以证据集由**代码装配**,从不问模型。

这不是取巧,正是这道门能比另外两道**更严**的原因:brief 的门只能问「这个数字是否出现在你引用的东西里」(对语料库的存在性检查),这道门问的是「这个数字是否是本次 run 某一行的值」。同时它绕开了一个真障碍 —— 现成的引用门要读 `agent_steps` 的证据轨迹,而报告路径没有 session,轨迹为空,每条引用都会被判 `not_in_evidence_trail`。

### 2.3 修复清单

| # | 修复 | 落点 |
|---|---|---|
| **G1** | 新建报告门:抽取全部数字 → 与本次 run 的行核对 → 不通过则不落库 | `services/report_verification.py`(新) |
| **G2** | 删除 mock 兜底、JSON 解析兜底、裸 except;四条分支改为 `ReportUnavailable(reason)`;六个字段全部必填非空 | `agents/direct_llm_agent.py` |
| **G3** | 删除 `_generate_report` 的内层吞异常(两层嵌套只剩一层,且原因进步骤 message) | `exposure_workflow.py` |
| **G4** | 持久化 `issuer_exposures.contribution` | `v6_report_gate.sql` · models · `_persist_outputs` |
| **G5** | `_RUN_CHILDREN` 增 `RiskAlert`;`IssuerExposure` 增 `contribution` | `numeric_verification.py` |
| **G6** | 两处豁免空缺:`30d` 式简写周期、`95% VaR` 式置信水平 | `numeric_verification.py` |
| **G7** | `new_id("report")` → `new_id("report_")`(此前所有 report id 都畸形) | `exposure_workflow.py` |
| **G8** | 关闭两条证据注入旁路,统一走 `_looks_like_id` | `tools/registry.py` |
| **G9** | 非字符串引用**拒绝**而非静默丢弃 | `tools/meta_tools.py` |

**G4 的理由**:每只持仓的贡献率是「top contributors」那句话的构成要素,`analytics/pnl.py` 一直在算,而 `issuer_exposures` 从来没有列存它 —— 于是那句话唯一的数字,恰好是唯一无从核对的数字。

**G8 抓了个现行**:`list_alerts` 返回 `{"id", "type"}` 形状,走 `{type,id}` 分支绕过前缀检查,把 `alertb41eec529430` 塞进了轨迹,`ref_type` 是告警**类型**而非证据类型。全库 1131 条 evidence_refs 里仅此 1 条畸形、涉及 1 个 session(共 533 个)、0 份 brief —— **收紧是零迁移改动**,读路径今天就已正确拒绝它。

---

## 3. 执行期发现:门第一次就拦下了报告,而它是对的

首次真实运行,门报:`1 of 68 numbers ... $141,973 (nearest: exposure_metrics.daily_pnl)`。

存储值是 **-141,972.82**,报告写的是「a loss of $141,973」——**符号藏在「loss」这个词里**。`numeric_verification` 明确拒绝猜符号(V3-R 决定:符号反转是这个领域代价最高的错误,而「把符号写在动词里」的说法必须被拒绝而非猜测)。

这不是门的缺陷,是**提示词没有把门的规则告诉模型**。修的是提示词,不是门:

> **Copy figures exactly as supplied, including the minus sign.** Do not put the direction in a word and drop the sign from the number: write "P&L of -$141,973", never "a loss of $141,973".

外加一条「不得自行计算」。改后实测:**79 个数字,0 个未通过**。

放松符号规则本来是更省事的一条路,而它会把这道门存在的理由删掉。

---

## 4. 本批**不做**、但已确认存在的问题(如实)

| 问题 | 为什么这次不做 |
|---|---|
| 单个 beta 仍不可引用(max VIF 18.0,且随窗口上升) | 需要收缩估计或缩减因子集,均改变页面数字的含义,属 D3 排除范围 |
| 情景未冲击的因子仍按 0 处理 | V5 §4.2 的遗留。需要因子协方差推导条件移动 |
| 报告的**定性**断言零覆盖 | 这道门检数字,不读句子。方向词、因果、归因一律不检 |
| 数字与句子的**语义绑定**仍未检查 | 报告里两个真实数字互换位置仍会通过。与 brief 门同一限制 |
| `positions.quantity` 不做拆股调整 | V5 遗留,需要公司行动数据 |
| 短历史持仓会缩小面板 | 实测:港口 + 半年期 IPO → 350 个观测(-53%),仍远高于 250 下限;DB 里五只 20 行的 ticker 无任何组合持有,且步骤 1 会在同一次 run 内回补 |
| `markdown_report` 无渲染器 | UI 只渲染 7 个字段中的 3 个。门已覆盖该字段,但用户看不到它 |

---

## 5. 下一批候选(待拍板)

1. **E2E live 测试层**:三条主线(chat / exposure run / research run)至今零自动化端到端覆盖;数值已稳,现在钉桩不会固化会变的数字
2. **因子集**:缩减或正交化 / Ledoit-Wolf 收缩,让单个 beta 可引用
3. **情景完整性**:未冲击因子由协方差矩阵推条件移动
4. **基本面深度**:杠杆类仅有 `current_ratio` 与 `cash_to_long_term_debt`
5. **`asset_class` 全程被存储且从未被使用**;TLT/HYG 无久期、无 look-through
