# IMPLEMENTATION_PLAN_V15 — 桌面

> **状态:S0–S7 全部完成并上线(2026-09-01)。** 验收与切换判据的实测见 `docs/spikes/V15_COVERAGE.md`:①④ 达标,②③⑤ 未达但中止判据未触发(尝试中位 5→2、拒绝 79%→50%、无答案 0、rubric 15→21/33)。执行中实测纠正了计划三处(豁免类七项而非一项;trail 本就是 session 作用域;`portfolio.window_return` 单位)——见 MODULE_NOTES M19。§7 的拍板项按建议执行。

---

## §1 目标

系统只靠一条不变量支撑可信性:**读者看到的每个数字是账本某一行的值;模型不产生数字,只产生指向。** V3–V13 把它做成"事后核对",V14 把数改成槽但保留了按值反查,本批把它做成**结构**:

- 模型可以指的东西,在一个对象里(**桌面**),带名字、单位、知识;
- 出口只能写桌面上的名字,每种论断有自己的证据谓词;
- 门只回答"指向是否成立",不反推、不教学。

## §2 诊断

**发行人半边是按"量"建的,组合半边是按"表"建的;电池里的失败全在组合半边。**

| 环节 | 发行人半边(V9–V12,已成功) | 组合半边(今天) |
|---|---|---|
| 量的身份 | 一个 `calc_id` = 一个值 | 一个 `run_id` = 235 个值;身份 = (子表, 行标签, 列),只在门内部拼出 |
| 清单 | `describe_issuer` | 没有;`get_portfolio_snapshot` 框定问题,不列出 run 里有什么 |
| 生产者 | 具名:`evaluate_formula(name)` | 表形:`get_attribution` = 一张子表,模型得懂库的布局 |
| 知识 | 挂在指标上 | `reads_as` 一句、`quotable_individually` 一个 flag |

Law C(不写路由器)的推论是**没有路由器就必须有清单**;V12 证明这条路在有清单的半边走得通(总债务 50%→100%,不改循环不加规则)。组合半边没有清单,于是三件上游没交付的事落到模型头上——给量起名、记库的布局、心算引擎已有的量——补位的产物就是电池里的错;门则在替上游做两件它做不好的事——从值反推身份、教模型改。

三个症状(实测见附录):
1. **身份不随值交付** → 标签歧义、指错 ref、按值解析把 TLT 权重当成预警线交给读者(门接受)。
2. **模型看到的集合 ≠ 门核对的集合**(上下文由 `dumps_capped` 建,trail 由"长得像 id"的收割器建)→ 191 个外来 id、缺席行进不了 trail。
3. **出口文法论断类型不全** → 靠原文支撑的段落无处引,模型把 chunk id 写进正文,引号核对在块出口不可达。

## §3 架构

### 桌面(Table)

```
table := { quantities: [(ref, name, unit, value, flags)],   flags: not_alone | not_a_forecast | …
           passages:   [(id, text, citation)],               chunk_ | src_
           rows:       [(id, kind)] }                        kind: series | absence | task
```

**一个构造器,三个出口同源**:送进模型上下文的载荷、门解析的全集、`agent_steps` 落盘的记录。桌面上没有的不可引,桌面上有的一定可引,没有第三态。

### A. 输入边界:book 侧配齐 issuer 侧的四件套

| issuer 侧已有 | book 侧对等物 |
|---|---|
| `describe_issuer` | `describe_run`:run 里有哪些量、唯一全名、按"回答什么"分组(mandate/headroom、stress、净敞口、归因、集中度);哪些**没有**;共线不能单引;**face 能力声明**(不能联网搜索,研究 run 可以) |
| `evaluate_formula(name)` | `read(names, run_id)`:按名批量取。模型声明需要什么,系统一次上桌——planning 以结构存在 |
| 指标 `note/do_not_add_to` | 量的 `flags` + `reads_as`,挂在量上,不在提示里 |

工具结果的可引部分改为**声明**(`quantities / passages / rows`),证据资格由工具声明,不由收割器推断;`quantities_of` 是唯一拼名点(`resources` 给列名与单位,`display_names` 给行标签)。共线单系数不进桌面——`not_alone` 从验证前移为投影。

### B. 出口边界:论断类型 × 证据谓词

| 论断 | 形态 | 谓词 |
|---|---|---|
| 数值 | slot `{ref, name}`,**无 value** | name ∈ 桌面该 ref 的量 |
| 原文支撑 | run/段落级 `cites: [chunk_/src_]` | id ∈ passages;引号内 ≥4 词 ∈ 这些原文 |
| 趋势 | `series_ref` | kind = series |
| 缺席 | `absence_ref` | kind = absence |
| 排序/比较 | `metric_table` | 每格同数值规则 |
| 动作 | `task_ref` | kind = task |
| 无论断散文 | 纯文本 | 无数字(日期唯一豁免) |

其余形状 JSON Schema 直接拒(Law B)。brief 六节用同一套块。

### C. 验证边界:只解析

| 不变量 | 执行 |
|---|---|
| V1 形状 | JSON Schema |
| V2 来源:ref ∈ 桌面 | 集合查询 |
| V3 解析:name ∈ 该 ref 的量;`not_alone` 唯一在此 | 字典查找 |
| V4 无裸数(日期除外) | 一条正则 |
| V5 引述逐字 | 对 `cites` 的原文 |
| V6 断言有据 | kind 谓词 |

### D. 作用域

本轮桌面 = 本轮工具声明 ∪ 上一轮桌面。跨会话 id 永远不上桌。

### 整体删除(DP3,不置空、不 flag)

`extract_evidence_refs` 的 id 形状遍历、`_harvestable`、`collect_trail` + 存在性查询、门时 `_RUN_CHILDREN` 扇出、`_COMPATIBLE`、`_DERIVATIONS`、`held_instead_by`、按值解析槽、`slot.value`、19 条豁免正则、26 个运行时形状码、轨迹 R1/R2(R1 进 rubric,R2 由 `task_ref` 谓词取代)、未注册的散文 `_respond`。

## §4 交付物与排程(约 8 人日;每步 offline 全绿 → commit;S7 前不 build 镜像)

| 步 | 交付物 | 判据 |
|---|---|---|
| **S0 ✅** | 基线 `docs/spikes/V15_BASELINE*.json`;faithfulness eval 按块测 | — |
| **S1 ✅** | `analytics/resources.py` 一处声明 44 列/7 资源;`calc_ledger.unit_class` | — |
| **S2a ✅ 声明形状 + 构造器** | 工具结果 `quantities/passages/rows` 三键(schema 钉住);`services/quantities.py` 唯一拼名;`services/table.py` 每轮一个构造器,三出口同源,按整个量截断并声明。**第一条红测试**:经 `respond` 引一个由 `get_flow` 直接拒绝铸出的 `absence_id`(今天必红) | 名字 235/235 唯一(3 个重复消解或具名豁免);桌面 ≤4k tokens;收割器与 `collect_trail` 删除;`test_v11_absence_live` 改为穿门 |
| **S2b ✅ `describe_run` + `read_quantities`** | 清单按"回答什么"分组;缺什么;共线;face 能力声明;`read(names, run_id)` 批量取 | mandate 分组里档位/实测/`room_to_*` 并列;book 级问句重放定位调用 ≤2 次;`read_required_inputs` 由 `agent_steps` 机械判定 |
| **S3 ✅ 出口文法** | `respond` v3 schema = §3-B 全部论断类型;`slot.value` 删;`cites`/`task_ref` 新增;`validate_shape` 只剩 V4;系统提示删 `{"ref","value"}` 示例与"给 value 让账本命名" | 26 形状码 ≥20 个由 schema 拒;拒绝只剩 `unknown_name / not_on_table / digits_in_text / quote_not_in_cited`;"Evidence ids:" 型文本重放为零 |
| **S4 ✅ 解析器** | `services/resolver.py`:V2/V3/V6 对桌面做集合/字典查询;`numeric_verification` 瘦到 V4 + V5;`verify()` 仅留 v1 散文历史只读 | `numeric_verification.py` 行数减半以上;123 个标签歧义在合成夹具归零;附录的 TLT 例重放中被 `unknown_name` 拒 |
| **S5 ✅ 四门合一 + 跨轮** | `submit_brief` = 六节 × 块,同一桌面同一解析器;Brief tab 用 `AnswerBlocks`;四份节名列表收敛为一份;上一轮桌面继承;日报按 §7-⑥ | `not_alone` 全库单执行点;brief 的引号核对首次生效;11 例跨轮失败重放归零 |
| **S6 ✅ 展示惯例前移** | `analytics/display_conventions.py` + `apps/web/lib/display.ts` 双向守卫;`prose_of` 用它;`AnswerBlocks` 字符串 run 走 `planAnnotations` | 存储/渲染/审计/rubric 四处一致;科学计数法零出口 |
| **S7 ✅ 验收与切换**(结果见 V15_COVERAGE.md) | 电池全跑对照 S0;四镜像重建 → 容器内 grep → smoke_ui | ① 无据之数 = 0(构造保证,电池核实);② `read_required_inputs` ≥ S0 且线性定位归零;③ 拒绝率 ≤10%、尝试中位 1、无答案 0(结果);④ rubric ≥15/33;⑤ 峰值 prompt 降 ≥30% |

**中止判据(先写死)**:S4 后两轮电池尝试中位数 >2 或无答案 >0 且不收敛 → 停,保留 S0/S1/S2a,出口回 V14-C。

## §5 结构守卫

| 测试 | 钉住 |
|---|---|
| `test_table.py` | 上下文/门/落盘三出口出自同一构造器;桌面外不可引,桌面内必可引 |
| `test_quantities.py` | 一个 run 的量名唯一;每个量有单位;没有第二个拼名点;`room_to_*` 在 mandate 分组 |
| `test_symmetry.py` | 每个 face 上每个可引量都有唯一名、单位、知识挂点(与 `test_resources` 同形) |
| `test_output_grammar.py` | schema 拒绝 §3-B 外所有形状;`slot.value` 不存在;每种论断有且只有一个谓词 |
| `test_one_resolver.py` | 四出口同一解析器;`not_alone` 单执行点 |
| `test_display_conventions.py` | py/ts 双向锁;科学计数法零出口 |
| `scripts/rubric_battery.py` | S0 vs S7 对照;结构项由 `agent_steps` 机械判 |

## §6 明确不做

- planner agent:planning = `describe_run` + `read`,一次声明式取数。
- 并行分析(按持仓扇出再汇总):要求子会话产物是块且桌面并入父桌面;顺序是桌面 → 批量读 → 循环并发 tool_calls → 扇出,本批只到第一步。
- LLM judge;resolver 里任何按值回退;按问题类的路线;提示里的"label 怎么写"规则;收割器例外。
- 跨会话引用继承(触及租户与审计语义,另立)。

## §7 待拍板

1. 日期是否唯一豁免类(建议是)。
2. `slot.value` 取消(建议是;A 让名字唾手可得是前提,两者不可拆)。
3. 跨轮桌面继承(建议是)。
4. S3 一并补齐论断类型(建议是;否则 S5 的 brief 无文法可迁,V5 继续不可达)。
5. `describe_run` 独立工具还是挂进 snapshot(建议独立:snapshot 每次对话都调,清单只在组合分析时需要——V14-A 的同一理由)。
6. 日报块化还是定位为只读 v1 路径(建议本批只读 v1:证据集由服务端装配、无循环,与 `verify()` 的历史只读定位相符)。
7. 轨迹 R1 退出门进 rubric(建议是)。

---

## 附录:实测依据

**被证否的三条路(不要再提)**:绑定器按值重指——同值多标签 45%;引擎按值反推补算——等价推导中位 24 条、唯一 1%;规范量归并——结构性重复只占歧义 30%,余为真实数值巧合。共同死因:值不携带意图。

**可行性**:一次回答可引 id 中位 5、最大 19;一个 run 235 个量,232 唯一;全部量带名字 + 读者精度 3.5k tokens(今天峰值 22k);`room_to_*` 已是 `portfolio.integration` 输出键;定位工具首调率 100%;有按问题组织的读时 2 次读即对(9/1 第 3 轮)。

**196 次引用失败分解**:145 次"id 不存在"里 164/191 真实存在、189/191 与本会话不沾边;442 个坏槽里 276 无据(85% 是 `档位−实测`,`room_to_*` 231/238 次不在证据里)、123 标签歧义(唯一全名不在模型眼前)。

**9/1 `sess_ce2808bf2ad1`**:第 2 轮一条消息 20 个并行定位、6 个被预算拒、7 次 respond、情景分析全是散文门零检查;第 3 轮有 `get_portfolio_analysis`,2 次读即对;第 4 轮 `{value: 0.06}` 被门解析为 `issuer_exposures.TLT.weight = 0.06073614` 并**接受**(读者看到 "0.06073614 warning level",hover 显示 TLT weight),`0.08` 解析为 `credit_spread_widening` 而非 `market_downside` 的档位;同一轮靠两段 10-K 原文支撑的段落无处引,模型写 `Evidence ids: chunk_… and chunk_…` 进正文,不进 citations、不核对、不可点。
