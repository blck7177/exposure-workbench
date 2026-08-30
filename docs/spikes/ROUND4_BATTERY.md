# 第四轮电池 — 出模块的问题与任务：能力能否被发现，工具列表是否太长

> 2026-08-29/30。**16 题 38 次真跑**(28 次 29 工具面 / 10 次最小面),gpt-5.4-mini,dev 账户;
> 189 次工具调用 / 8 次被拒 / 33 次门拒绝 / 278 s。题目 `tests/battery/questions_round4.json`,
> runner `scripts/ablation_battery.py`(三臂消融),另有一份按失败模式去重、逐题 live 预核可达性的
> 14 题设计集 `tests/battery/questions_round4_designed.json`(设计 workflow:5 镜头 × 4 候选 →
> 筛 14,6 个 agent,每题带调用链、失败模式、评分键、最小工具集)。**每个数字都回 `calc_ledger` /
> `financial_facts` 核过。**
>
> **问的是两件事**:① 没写进 module 的能力,agent 能不能自己组合出来?② 还是 29 个工具的列表
> 已经太长?两个假设对同一观测(agent 在新任务上失败)给出竞争解释,所以每题都带**先验可达性**
> (对着库核过的调用链),并用**面宽度消融**把"找不到链"和"组不出链"分开。
>
> **主结果**:① **能**——6 工具面上从 `get_flow`/`get_balance_sheet`/`calculate` 推出完整 DuPont,
> 门重放 11 个数 10 个通过;② **不是**——面缩到 6 反而更差,29 个里 4 个从未被调、3 个占 62%;
> 真正拦住已发现能力的是三件事:门是数↔证据的**棘轮**、具名公式是**磁铁**、**平预算 × 线性定位**。
> 顺带挖出 **5 个确定性缺陷**(不需 LLM 复现)和 **1 个门的结构洞**(真数字搭假句子全过)。
> 其中 3 个缺陷已随 `798f6fd`/`6be718a` 上线,其余 3 个 + 一条卡了 27 天的 run 在本批修(§6)。

---

## 0. 题目怎么来的

ROUND3 的自我批评是:按"分析上互不重复"筛题,结果 5 题塌进 2 类;正交的判据应是**失败时互不重复**。
这轮把判据写进设计 workflow 的提示里:五个镜头(未具名组合 / 跨实体聚合 / 无工具可达 / 任务而非问题 /
跨模态与自我认知)各出 4 个候选,筛选者只按"没有两题会因同一缺陷而失败"留 14 题,且每题**先对着
live 库和真实 schema 核可达性**——写出调用链、数调用次数(预算 15/轮)、给评分键。设计集里 8 题可达、
6 题不可达或部分可达;不可达题的评分键是**拒绝的措辞**(点名缺的是什么,还是拿邻近度量冒充)。

实际跑的 16 题 = 我先导 4 + 针对性探针 3 + 任务 3 + 设计集 4 + 跨模态/时间轴 2。设计集里未跑的 8 题
留作下一轮(§8)。

## 1. 三臂消融

同一题、同一模型、同一门,只改模型**看到**的工具列表。裁面走 bearer 里既有的 `deny` claim
(skip-flag 通道),不改部署:

| 臂 | 面 | 读法 |
|---|---|---|
| **wide** | 生产面,29 工具 | 基线 |
| **narrow** | 只给该题调用链需要的工具(+think/respond) | 是"去掉干扰能买到什么"的**上界**,不是干净测量——只给对的六个工具本身就在提示哪六个对。**narrow 赢是模糊的,narrow 输是决定性的**:去掉一切无关工具仍找不到的链,从来不是搜索问题 |
| trimmed | 与题无关的固定精简面 | 备而未用——前两臂已给出一致结论 |

## 2. 结果

判据是"轨迹 + 答案是否与账本一致"。

| # | 题 | 隔离的失败类 | wide | narrow |
|---|---|---|---|---|
| P1 | Alphabet ROE 三段分解 | **深度 2 组合**(calc 喂 calc) | 部分:权益乘数算出、资产周转**假称算不了**、ROE 没算,塞进具名度量 | **组出全部三腿 + ROE**,4 次门拒绝**零答案**(§4 棘轮) |
| P2 | 全书按仓位加权 debt/EBITDA | 跨实体 × 预算 | 20 调用 5 拒,12/15 花在 `describe_issuer` | 13 调用,部分答案 |
| P3 | NVDA/AAPL 营收增速相关系数 | **无算子**(`series_stat` 11 个 op 没有 corr) | "数据点不够",并**承诺能算** | "**没有工具能算 Pearson**"——对了 |
| P4 | 你能做什么、不能做什么 | 自我认知 | 0 调用,泛泛 | 同 |
| A | 单独问 Alphabet 资产周转率 | 情境性假缺席的对照 | **0.484x,5 调用,0 拒,2/2 稳定**——同一度量在 P1 里被谎称不可得 | — |
| B | 三家按仓位加权 debt/EBITDA | 装得下预算的跨实体 | 仍失败:AAPL/MSFT 输入缺;且 wide-1 转述了服务端假话 "no total_debt at any date"(§3 A2) | — |
| C | 三家现金合计 | **跨发行人求和** | 2/2 被 `different_instants` 拒,出路指向不可能的"同一日期"(§3 A3) | — |
| T1 | "我之前 kick off 的那个完成了吗"(新会话) | 悬空指代 | 0/2 拒绝,答"已完成" | 1/2 正确追问 |
| T2 | 每天自动查一次杠杆 | 无调度工具 | 2/2 如实拒绝 | 同 |
| T3 | 把 NVDA 数据刷新 | 幂等委派 | 2/2 真入队、如实汇报 | 同 |
| wc-swing | Apple 营运资本一年变了多少 | 类型拒绝是死路还是改道 | 答**流动比率**(磁铁);变化量被拒(§3 A5) | — |
| roic-nopat | MSFT 税后资本回报 | 定义保真 | #1 给 `fcf_to_debt` 称"代理";#2 给 EBIT/营收(利润率)叫错名 | — |
| altman-z | XOM 的 Z-score | 编造加权合成 | 2/2 先问"你指哪种 z"——过 | — |
| lev-screen | 全书谁杠杆超 3x | 横截面筛查的分母 | #1 说"LLY 无申报债务"(实 43.4B,**模型自造**);#2 查了 5/8 只,没说 AAPL/GOOGL 没查 | — |
| X1 | 哪些持仓在申报里提关税、其中谁债务最重 | **跨模态**(文本 + 数字) | **2/2 过**:16–17 调用,8 家逐一检索 + 逐字引文 + 债务比较,#1 还正确排除了 MSFT | — |
| risk-hist | VaR 过去一个月怎么走 | 无 run 枚举 | **2/2 编造趋势**("一直在涨";库里只有一个 run),**0 次门拒绝**(§5) | — |

## 3. 确定性缺陷(均可脱离 LLM 复现)

| # | 缺陷 | 位置 | 状态 |
|---|---|---|---|
| A1 | `cover` 双重计数(ROUND3 已知,本轮首次冒烟仍在线上:NVDA 9.47B vs 8.47B) | `analytics/containment.py` | **本批修**(§6) |
| A2 | 派生输入的缺席被说成全域缺席:`total_debt` 由 cover 派生,事实表 0 行 → `covers.get()` 恒 None → "holds no total_debt for AAPL **at any date**"(实 84.7B);同一载荷 `detail` 却写 "at **this** date"。模型忠实转述 | `services/formula_service.py:227` | **已修** `798f6fd` |
| A3 | 类型计算器对发行人盲:`AAPL cash@03-28 + MSFT cash@03-31` 与 `AAPL@03-28 + AAPL@12-27` 得到**逐字同一**拒绝,出路都指向"同一日期"——两家财年不同,永不可能 | `services/typed_calculator.py` | **本批修** |
| A4 | 二阶组合丢期间:`calc × calc` 的 basis 塌成 `' multiply '`。答案标期间 = 陈述证据没有的东西;不标 = 违反系统提示的规则 | 同上 | **本批修** |
| A5 | `different_instants` 不区分 add/subtract;序列轴放行、标量轴拒 | 同上 | **已修** `798f6fd` |
| V5 | `_check` 对乘除完全不设防(`if op in ("multiply","divide"): return None`,有注释说明是设计):任何无意义乘积拿到可引 `calc_id` | 同上 | 设计决定,待重审 |

A1/A2/A4 同一个根:**派生量是二等公民**——有 id,没有原始量的元数据(覆盖、期间、包含安全性)。A3/A5 同一个根:类型模型少两个维度(主体、op)。

## 4. 已发现的能力为什么落不了地:棘轮

P1-narrow 的轨迹(`sess_e064b00bb6b8`)是整轮最有价值的一条:

```
seq 10  calculate(net_income ÷ revenue)        → 净利率
seq 12  calculate(revenue ÷ total_assets)      → 资产周转   ← wide 臂谎称算不了的那条腿
seq 14  calculate(净利率 × 资产周转)
seq 16  respond → invalid_citations
seq 24  respond → unverified_numbers   拒 1/11:权益乘数 1.44x 还没算,门点名 divide(total_assets, equity)
seq 26  照做 ✓
seq 30  respond → unverified_numbers   拒 2/11:权益乘数过了,净利率的引用丢了 → 32.81% 反被拒
```

门离线重放:seq 24 的回答 **11 个数 10 个通过**,且分析上完全正确(净利率 32.81%、资产周转 43.69%、
权益乘数 1.44x、乘积 14.34%)。门每轮只拒第一个不合处、只点名一个修法;模型修好它、丢掉另一个已通过
的引用。K 个数每轮修一丢一,16 轮不收敛。**能力被发现了,数进了账本,就是出不来。**

## 5. 门的结构洞:验证单位是数,意义单位是句

`risk-hist` 两次都以"**Yes** — 组合的 VaR 过去一个月一直在涨"开头。port_001 只有一个完成 run
(2026-08-20),不存在任何 VaR 序列,也没有工具能枚举 run。句子里的数(1.39%、750 obs)全真、全可引;
"一直在涨"没有数字——**0 次门拒绝,2/2 稳定**,还顺势承诺"可以拉出逐日序列"。

同一个盲区:LLY "在本库没有申报债务"(模型自造,实 43.4B);T1 "你之前 kick off 的已完成"(全新会话);
lev-screen 报"没有持仓超过 3x"却没说 AAPL/GOOGL 没查。33 次门拒绝没有一次错拒;5 类严重失败没有一次
被拒——都不是"数不在证据里"。这比 GAPS.md 右列的"判决/方法句"更具体、也更可修:**关于缺席、趋势、
自身动作的断言是有限可枚举的类别**,且原语已在(V11 的 `absence_id`、序列 `calc_id`、本轮 `task_id`)。

## 6. 修了什么

**第一批**(`798f6fd` + `6be718a`,随 V13 上线,上线后真实面复核):A5 —— 跨日期 subtract 定型为
`(earlier + 1d, later)` 区间,与申报流量窗口惯例一致,ΔWC 和同期 OCF 在 R1 下相遇(wc-swing 2/2 =
**35.370B**,账本行带区间基准);A2 —— 派生缺席按生产者作用域措辞,`_total_debt` 拒绝带日期与"分量最后
见于何时"(B 题不再说 "at any date");K4 —— 证据池耗尽后面收窄到 `think`/`respond`,名字表与
`registry.BUDGET_FREE_CLASSES` 由测试钉死。

**本批**(A 批):

| 项 | 改动 | live 复核 |
|---|---|---|
| A1 `cover` | 候选后代集 ∩ 已覆盖区域 ≠ ∅ 则**设为 `overlapping_not_added`**,不加、不算缺失;其未覆盖部分经自身后代到达(单独申报则加,否则点名缺失) | 174 个 (发行人,日期) 组合扫描,**20 个改变 = NVDA 16 + LLY 4**,全部是 `LTD_total + debt_current_total` 双计当期部分的形状。ROUND3 说 19 个全 NVDA,漏了 LLY 是因为它没单独申报 `current_portion`;图判据不依赖那条事实。NVDA 2026-04-26 → **8.470B** |
| A4 期间 | 每个派生量携带 `leaves`(全部叶子 instants/intervals),`basis` 字符串嵌套两侧表达式;返回值多一个 `periods` | GOOGL DuPont 深度 2:`periods = {instants:[2026-06-30], intervals:[[2025-07-01,2026-06-30]]}`,乘积与 NI/equity 直算**完全相等** |
| A3 主体 | `Typed` 加 `issuers`(事实 → 发行人 ticker;计算 → 并集;旧行为空 = 未知,**按共享处理**);双重计数三规则只在共享发行人时触发;跨发行人不同期的和带 `cross_issuer` 与两侧叶子;stock/flow 判定改读叶子;**同发行人再加进一个跨期混合金额 → 保守拒绝** `mixed_basis_operand` | AAPL+MSFT+NVDA 现金 = **100.120B**,三个日期都在;再加 AAPL → 拒;AAPL@03-28 + AAPL@12-27 → 仍 `different_instants` |
| rrun | `update_status` 对不可见 run **raise `RunNotVisible`** 而非静默返回;handler 记录"失败且失败无法落账"后 raise **原异常** | `rrun_5b247ec1db21`(owner NULL,早于租户制)由表 owner 标 failed,原因写入 `error_detail` |

**LLY 的残差**:2024-12-31 两个合法反链 `{LTD_total, CP}` = 33.812B 与 `{noncurrent, debt_current_total}`
= 33.644B 差 0.168B——发行人的行在图的边下不完全对齐(`debt_current_total` 可能含图未建模的分量)。
widest-first 按设计取前者;这是包含图保真度的问题,不在本批。

## 7. 一处更正:K4 的动机描述

`798f6fd` 的 message 与当时的代码注释说 `sess_1c71b5fb7f79` 的 65 次被拒"各约 12k token 的 LLM 往返"。
逐轮结构实测:

```
turn 3   一条 assistant 消息并行发 69 个工具调用 → 4 通过,65 被拒
turn 4   prompt 34,048 tokens(比新会话多 ~5.7k,是 65 条拒绝载荷)→ respond
turn 5   respond
```

**单批次现象,不是多轮空转**。K4 的收窄作用于下一轮的工具列表,对同批剩余调用无效;全库 102 个撞过
预算的会话 `read_calls_in_later_turns` **全部为 0**——K4 守的情形从未被观测到。新会话 65→4 是模型这次
批次小,不是修复所致。K4 保留(循环此前对预算没有任何界),注释已改为实测机制。真正消掉那 65 次的是
**批内短路**(池耗尽后同批剩余调用不发 MCP / 折叠拒绝载荷),取舍是 registry 要求拒绝留痕——待拍板。

## 8. 仍开着的

- **门的三类断言校验**(§5):缺席须引 `absence_id`、趋势须引序列 `calc_id`、动作须引本轮 `task_id`。唯一能拦住 risk-hist 那类答案的东西;改的是门的契约,应按 V12 的方式先写计划。
- **棘轮**(§4):门跨尝试累积已通过的引用,或一次列出全部问题。
- **平预算 × 线性定位**:10 持仓 12/15 花在 `describe_issuer`;批量定位或按证据计预算。
- **具名公式磁铁**(wc-swing、roic ×2):模型行为,被 16 个具名公式 + `computable` 标记放大;narrow 去掉 `evaluate_formula` 立刻解锁手工组合。无直接修法,靠断言校验让错标名字不再静默。
- **无能力清单**(P3):面只声明给服务器不声明给模型;wide 把"没有算子"说成"数据不够"。
- V5 乘除不设防的设计决定;LLY 0.17B 反链残差;设计集里未跑的 8 题;n=2 的置信度。

## 9. 复现

```bash
# 三臂 runner(容器须跑当前代码;host 连 127.0.0.1:8104)
MCP_URL=http://127.0.0.1:8104 BATTERY_OWNER_ID=<dev user id> \
  .venv/bin/python scripts/ablation_battery.py tests/battery/questions_round4.json out.json --arm wide --repeat 2
# narrow 臂用每题的 minimal_tools 作为面
  ... --arm narrow

# 确定性复现(不需 LLM)
.venv/bin/python -m pytest tests/test_v9_containment.py tests/test_typed_calculator_issuers.py \
  tests/test_balance_delta.py tests/test_absence_derived_input.py tests/test_research_run_failure_recorded.py
```
