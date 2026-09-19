# IMPLEMENTATION_PLAN_V14 — 引用槽出口 + 分析质量层

> **状态：草稿，待拍板。** 本计划是依据不是权威（V8 纪律）：执行中发现计划与代码不符时，以代码实测为准并回写本文档。
> 起草 2026-08-30。依据三份材料：① 真实会话 `sess_16b176ea4c9b` 两个 turn 的逐步轨迹（`/home/ubuntu/exposure-workbench-logs/`）；② R4 电池结论（活页 8/29–30）；③ 两路联网调研（结构化输出生产模式 / 金融分析质量工程，全档待归档 `dev_note/portfolio-demo/analyst-skills/`）。

---

## §0 诊断（为什么是这五批）

**实测症状**（sess_16b176ea4c9b）：

- Turn 1（宏观风险分解）：9 次 LLM 调用中 6 次在与门谈判（1× `invalid_citations` + 4× `unverified_numbers`，四份被拒草稿长度几乎相同）——**数↔证据棘轮**的温和发作；最终答案 32 个数全过门，但满篇 `33.878625%`、`0.5556454228194568` 的账本原精度，7 条 exposure 平铺不排序、不轧差、无 so-what。
- Turn 2（fundamental 逐家分析）：15 次预算 11 次花在线性定位（1 snapshot + 10 describe_issuer）；业务叙事零证据含量（全程未碰 chunk/fact，模型先验）；run 里现成的逐持仓 beta 一次未读——自下而上与自上而下永不见面；引用焦虑漏进正文（"so I'm not citing a made-up id"）。

**类别归因**：

| 错误类别 | 现处置 | V14 处置 |
|---|---|---|
| 抄错/编造数字 | 门事后核对（棘轮成本） | **构造上消灭**（C：无数可写） |
| 趋势/缺席/动作假话（R4 待办④） | 门看不见 | **结构收窄**（C：断言类型化） |
| 漏整合、选错形状、套话 | 无处置 | **算术下沉 + 知识降低**（A+B），被 E 测量 |
| "像不像分析师"残余判断 | 无处置 | 承认不可机械化，**只测量不门控**（E） |

**外部依据**（要点，全档另存）：生产系统中"下游美化 LLM"零例；统治模式 = LLM 只写 spec/引用、数值由引擎解析（Snowflake Cortex Analyst、Databricks Genie/Vega-Lite 函数、Tableau Pulse 的 deterministic facts + 模板叙事；学名 relexicalization）；约束解码保证形状不保证值（数值门仍是必需的另一半）；分析质量业界做在管线结构与方法论资产层，不做在提示词（Anthropic financial-services skills、LandingAI "The LLM is the last step"、Hebbia 检索/输出职责分离、Brightwave judge-revise）；分析质量评测已有原子二元 rubric 范式（DeepResearch Bench II、ICBCBench、PRBench-Finance）。

## §1 目标 / 非目标

**目标**：
1. LLM 输出侧不再携带数值字面量：数值位置 = 账本引用槽，真值由渲染层解析（输入侧不变——模型必须看见数值才能判断）。
2. 表格/图表成为出口的一等公民，且由构造保证有据（图表只能引用账本序列）。
3. 每个渲染出的数字/图表点可点击穿透（复用现有证据列，覆盖率从"门核中的"变成"全部"）。
4. 排序/轧差/整合等算术性专业动作下沉为确定性原语；分析框架进数据（V12 机制）。
5. 分析质量（ranking/netting/触发线/so-what）可回归测量。

**非目标（明确不做）**：
- 推理时 judge-revise 环（LLM 判 LLM 不是机械门，与门哲学冲突；质量压力全部走 B 事前 + E 事后）。
- 下游格式化 LLM node（行业零先例，且制造裸奔生成面）。
- 历史消息迁移（v1 散文消息按其记录的格式渲染——这是记录的事实，不是 fallback）。
- IPV / Brinson / 货币归因（沿用 MODULE_NOTES 插节）。

## §2 批次总览与依赖

```
V14-A 整合原语        （不动出口，独立可上线）
V14-B 框架注册表      （依赖 A 的原语名字；不动出口）
V14-C 出口块化        （最大一刀：respond v2 + 门反转 + 断言类型化；依赖 A 提供可引的排序/轧差行）
V14-D 渲染与惯例层    （与 C 同批联调，前后端一个契约两侧）
V14-E rubric 电池     （伴随全程：A/B 上线前先建基线，C/D 切换以电池重放为验收门）
```

建议顺序：**E(基线) → A → B → [C+D] → E(回归)**。R4 待办①②③（containment 双重计数、calc×calc 期间、发行人维度）是独立正确性修复，先行不冲突；待办④被 C 吸收。

---

## §3 V14-A 整合原语

**改什么**：

- `analytics/` 新增纯函数：压力表排序（按损失量级，含告警状态）、beta 加权敞口、**净利率暴露**（TLT 久期多头 / JPM 净息差 / HYG 利差的双向轧差，净方向与各腿分列）、集中度对 limit 的距离（复用 `limits.py` 的检查逻辑，不 import 默认值——纪律沿用）、**因子×持仓整合矩阵**（run 的逐持仓 beta × 权重 × 该发行人可算公式集，join 自现存行，不新算）。
- `services/` 新增读服务把上述拼成一次全集返回；每个数字照常铸 `calc_ledger` 行（排序/轧差是计算，进账本，因此**可被引用槽指到**——这是 C 依赖 A 的原因）。
- `tools/definitions.py` 或 `meta_tools.py` 新增一个 meta 面工具 `get_portfolio_analysis`（命名待定）：全集返回、禁 top_k、随 `faces.py` 登记。**不**塞进 `get_portfolio_snapshot`（snapshot 是入口定位，矩阵是分析读；混合会让首调载荷失控）。

**不变量（测试钉住）**：轧差恒等式（各腿之和 = 净额，容差沿 A6）；排序与 `stress_results` 行逐位一致；矩阵里每个数带既存 run 子表行的 id，本工具不产生新数值来源；载荷上限比照 `describe_issuer` 的 12KB 推导法（实测后定数）。

**验收**：offline 单测 + live 对真库（demo 簿 + 用户簿各一）；turn 2 型问题重放——定位调用次数从 11 降到 ≤3（1 snapshot + 1 analysis + 余量），省出的预算实际花在证据读上（电池观察项，不作硬判据）。

**明确不做**：不改预算数值（15/turn 不动——A 的目的是改变预算的*花法*，不是加预算）。

## §4 V14-B 分析框架注册表

**改什么**：

- `analytics/frames.py`：仿 `formulas.py` 的注册表。每条 frame = 问题族名 + **一份完整回答包含什么与为什么**（必备证据输入：如排序压力表、整合矩阵、limit 距离、相关申报节；输出形状：论点 → 按量级排序的驱动 → 抵消项 → 监控触发线 → so-what；反模式：如"利率暴露不轧差会把对冲当敞口"）。措辞纪律 = V12 的"事实+后果"，**不是 SOP**。
- 挂载：`get_portfolio_snapshot` / `get_portfolio_analysis` 返回值携带组合类 frame，`describe_issuer` 携带单名类 frame（V12 机制原样复用，不建 SKILL 文件、不建路由器）。
- `agents/meta_agent.py` `_SYSTEM`：增补 2–3 条"专业形状"已验证示例（含展示精度惯例：写 ~33.9% 而非 33.878625%——门的半 ulp 容差本就允许，模型只是不知道；C 上线后此条自动失效并删除）。**系统提示措辞照惯例单独过目后才提交。**

**不变量（测试钉住）**：frame 零数字阈值、零发行人名、零工具调用顺序指令（防 SOP 化；断言扫描仿 `formulas.py` 的零阈值测试）；frame 只在其必备输入对该上下文存在时随载荷发出（V12 "note 只在关系成立时发"的纪律）。

**验收**：开关对照（V12 范式）：同题各 n≥8，测量回答是否含排序/轧差/触发线/so-what 四要素（由 E 的 rubric 判）；载荷增量实测并记录。

**明确不做**：不按问题分类路由 frame——frame 作为知识随上下文到达，适用性由模型判断（Law C；FinAgent 教训：强制规则文本在不匹配场景 −21%）。

## §5 V14-C 出口块化（respond v2）

**契约**（`tools/meta_tools.py` `_respond` 换代，`research_tools._submit_brief`、`report_verification` 随后同契约，见 §5.4）：

- 回答 = 块列表。块类型封闭：
  - `paragraph`：结构化 runs 列表——文本 run 与槽 run 交错（**不用带内标记语法，schema 消灭解析**，Law B）。槽 run = `{ref: <账本 id>, hint?: <展示提示，封闭枚举>}`。
  - `metric_table`：行×列，每格 = 槽或豁免类字面量；列头/行头为文本。
  - `chart`：kind ∈ 封闭枚举（bar / line / waterfall），系列只能是序列类 calc_id 或槽列表；无自由数组。
  - 断言块（吸收 R4 待办④）：`trend`（必携序列 calc_id）、`absence`（必携 absence_id）、`action`（必携本轮 task_id）。
- 文本 run 内数字字面量非法，豁免集沿用 `numeric_verification._exempt_spans` 的封闭清单（日期、表单号、法规引证、年份、序号…），逐字引号规则不变。

**门反转**（`services/numeric_verification.py`）：

- `resolve_cited_values` / `_from_*` 族从"核对器的取证侧"转正为**槽解析器**：每个槽 ref 必须经 evidence trail（收割规则不变）且可解析、单位类与 hint 相容；`EvidenceValue.not_alone`（共线单引）改在槽级拒绝。
- 文本 run 只跑豁免类字面量扫描 + 引号逐字。`unverified_numbers` 拒绝码退役（保留在错误码表标记 retired，`tests/test_workflow_error_codes.py` 双向锁随之更新）。
- `trajectory_gate` 不动。

**存储与 API**（`db/models.py`、`apps/api/routes/agent.py`）：

- `agent_messages` 增 `format` 标记（v1=散文 / v2=blocks），blocks 落 `meta` 或新列（实现时定，倾向新列——blocks 是内容不是元数据）；v1 历史消息不迁移。
- 会话读接口原样返回 blocks；`/api/evidence/{id}` 解析器零改动（穿透复用它）。

**§5.4 三出口推进顺序**：respond 先行（本批）；`submit_brief` 与报告门在 respond 稳定一个电池周期后同契约跟进（独立小批，控制爆炸半径——brief/报告流量低、已有逐块引用基础，改动小）。

**不变量（测试钉住）**：块词汇表封闭（未知块类型 = schema 拒绝，非忽略）；图表系列 id 必须在 trail 内（与槽同规则）；断言块三条各配正例/负例；v1/v2 消息各有渲染快照测试。

**验收（切换门槛，不达标不切）**：分支上全电池重放（E 基线题集），判据——① 正确性不回退：过门答案的槽解析后数值与 v1 基线逐位一致（parity 思路沿 V10）；② 棘轮消失：门拒绝次数中位数显著下降（turn 1 型题 5 次 → 预期 ≤1）；③ **模型能力风险实测**：`gpt-5.4-mini` 作者化槽的失败率——若首两轮电池失败率 >20% 且加示例后不收敛，**中止本批回滚设计再议**（中止判据先写死，不半迁移——S3 纪律）。schema token 增量实测记录（预算 `context_budget` 计量含工具 schema，涨幅入账）。

## §6 V14-D 渲染与展示惯例层

**改什么**：

- `apps/web/app/components/analyst/AnswerText.tsx` → blocks 渲染器（按 `format` 分支；v1 走现路径）。`Verified.tsx` 的 hover 依据从 gate 配对表改为槽自身（歧义消失）。
- 图表块复用 `charts/` 现有 ChartCard 组件族；表格块复用现有 Table 视图习惯（含 Table/Chart 切换）。
- **展示惯例服务**（新，倾向 `analytics/display_conventions.py` + 前端镜像常量，跨语言守卫仿 `lib/errors.ts` 的双向锁测试）：每单位类的展示精度、千分位、符号、缩写规则——惯例作为数据只有一个家。渲染显示惯例值，hover 显示账本原值 + 来源。
- 点击穿透：槽/表格格/图表点 → 现有证据列（`evidence/Column.tsx` 钻取栈零改动，只是入口变多）。图表点级 ref 来自序列 calc 的 points（已存在）。

**验收**：两主题（light/dark）渲染快照；每种块类型的穿透 live 冒烟（点到 calc → Built from → fact → filing）；audit 层照常显示原始 id。**SEC inline XBRL viewer 深链**作为独立 spike 验证可行性，不进本批验收。

## §7 V14-E rubric 电池

**改什么**：

- `tests/battery/` 新增 rubric 题集：每题附**原子二元判据**（排序正确？轧差出现且方向对？触发线量化？so-what 可操作？必备输入被实际读取？）——判据写法仿 DeepResearch Bench II（可判 True/False，不打印象分）。
- `scripts/agent_battery.py` 扩展：结构判据代码判（如"是否调了 get_portfolio_analysis"读 `agent_steps`），语义判据离线 LLM-judge 判（**只在评测，永不进 serving path**；judge 模型与成本走 D7 的 OpenAI 上限治理，先估后跑）。
- 出题纪律沿 R3 自我更正：按"失败时互不重复"筛题，不按"分析上互不重复"。
- CI 策略：rubric 分数入库基线，回退超阈值即红（阈值待首轮基线后定，不拍脑袋）。

**验收**：A/B 上线前后各一轮全跑，得到 V12 式的前后对照数；C 切换以本电池为门槛（§5）。

## §8 部署纪律

每批沿用：offline+live 全绿 → 四镜像重建 → **容器内 grep 验证部署物**（commit ≠ 上线，V9 教训）→ 站点冒烟 → 活页记录。C+D 为跨 api/mcp/web 三容器的契约变更，切换窗口内一次性重建三者，不允许前后端版本错配运行。

## §9 风险与对策

| 风险 | 对策 |
|---|---|
| mini 模型作者化槽失败率高 | E 先建基线、分支电池实测、§5 中止判据写死；V12 式已验证示例是第一杠杆 |
| blocks schema token 涨幅挤预算 | `context_budget` 实测入账；hint 枚举保持最小 |
| frame 滑向 SOP | §4 断言测试钉零顺序指令/零阈值；措辞过目纪律 |
| 并行 session 撞车 | 本批文件租约制（V4 教训）；`docs/` 与 `analytics/frames.py` 为新文件，创建前先查存在性（V7 教训） |
| judge 成本失控 | 离线专用、D7 上限、每轮先估 token 再跑 |

## §10 待拍板

1. 五批顺序与 R4 待办①②③的先后（本计划建议：R4 ①②③ → E 基线 → A → B → C+D → E 回归）。
2. `get_portfolio_analysis` 命名与"新工具 vs 扩展 snapshot"（本计划推荐新工具，理由 §3）。
3. blocks 落库形态（新列 vs meta）与 `format` 版本策略。
4. §5 中止判据的具体数值（失败率阈值、电池轮数）。
5. E 的 judge 模型选择与预算额度。
6. `_SYSTEM` 增补示例措辞（照惯例单独过目）。
