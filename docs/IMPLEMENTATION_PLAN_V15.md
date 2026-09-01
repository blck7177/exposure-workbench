# IMPLEMENTATION_PLAN_V15 — 出口重构:模型读数字、写指向;验证即来源解析

> **状态:草稿,待拍板(§9)。** 依据不是权威(V8 纪律):执行中计划与代码不符时以实测为准并回写。起草 2026-09-01。
> **依据**:V14-C 验收自记("the shape changed, the ratchet did not go away",判据②失败);活库 8/26–9/1 全部会话的出口统计;ROUND4 §4–§5;V14-B 撤回结论;本文 §0 的规则清单。

---

## §0 诊断

**核心对,病灶在出口。** 分析层 + 账本 + 工具在 43+24+24 次会话里零算术错;出口的拒绝率从 39%(8/27,散文)升到 86%(8/31,块),每轮 respond 尝试中位数 1→5,整轮无答案 0→25%,单轮峰值 prompt 9.4k→29.5k tokens。V14-C 消灭了"抄错数字"(0 次),却把棘轮换了单位:一次修五个槽、弄坏两个。

**根因三条**:
1. **出口把"组装"交给模型、把"验证"留给引擎——应当反过来。** 引擎持有本轮全部证据与其句柄,`held_instead_by`/`available` 证明它知道正确答案,却把修复权退回模型。
2. **验证是加性的,修复不是。** 六道门 + 三道块检查叠在一个出口,唯一修复动作是"LLM 整篇重写"。每加一道检查拒绝率单调上升。
3. **验证对象选错了。** 只要门要"从散文里认数字",豁免集就是无穷的:`_EXEMPTION_PATTERNS` 20 条正则各修一起事故;`_COMPATIBLE` 为容忍裸数松绑;`_DERIVATIONS`/`_CALC_RATIO_OPS` 是别处规则的镜像;`answer_blocks` 26 个拒绝码大半是 JSON Schema 能表达的形状。核心不变量约 6 条,外围约 50 条规则/补丁/镜像。同一套不变量在 respond 散文 / respond 块 / submit_brief / report **四份实现**,已分歧(块门漏 `not_alone`)。

## §1 逻辑(一句话)

**模型看全部可引数字(为了判断),写词与指向(不写数);读者看到的每个数字由引擎按指向从账本查出。验证不检查文本,只解析来源;引擎能修的不拒绝。**

## §2 边界(输出文法)

```
answer     := block+
block      := paragraph(run+) | table(columns: text+, rows: run+[]) | assertion
run        := text | slot
text       := 不含 [0-9] 的字符串(唯一例外:日期字面量,§9-①)
slot       := { ref: evidence_id, hint?: label | value }     ← hint 给绑定器,不是输出
assertion  := { kind: trend | absence | action | comparison, ref(s), text }
comparison := { a_ref, b_ref, relation ∈ {gt, lt, near} }     ← 新增,§9-④
```
模型**不产出**:数值、单位、精度、年份、序号、法规引证(随 chunk ref 走)。

## §3 最小正交验证集(从 §2 推导,互不重叠)

| # | 不变量 | 执行 | 取代 |
|---|---|---|---|
| V1 形状 | 符合 §2 文法 | **JSON Schema**(Law B),运行时零规则 | `answer_blocks` 26 个形状码 |
| V2 来源 | 每个 ref ∈ 本轮证据轨迹 | 集合查询 | 保留 `validate_citations` |
| V3 绑定 | 每个 slot 解析为其 ref 持有的恰好一个值;`not_alone` **唯一在此**执行 | **绑定器**(§4) | `resolve_slot` + 三处 not_alone |
| V4 无裸数 | 正文 `\d` 为空(日期除外) | 一条正则 | 20 条豁免、`_COMPATIBLE`、提取器 |
| V5 引述逐字 | 引号内 ≥4 词 ∈ 被引 chunk | 保留 | 保留 |
| V6 断言有据 | kind → 行类型谓词(trend→序列行、absence→缺席行、action→本轮 task) | 一个函数 | 2 条断言检查 + 轨迹 R2 |
| V7 比较成立 | `comparison` 的不等式由引擎对两行求值 | 一个函数 | 无(今天的"一直在涨"/"没有超过 3x"零拒绝) |

**删除**:`_DERIVATIONS`(要算就调 `calculate`)、`_COMPATIBLE`、`_CALC_RATIO_OPS`(单位改存账本列)、`not_in_cited_evidence` 的邻近提示(变绑定行为)、轨迹 R1(前移到工具层,§S5)。

## §4 绑定器:验证与修复分离

```
respond(blocks)
  V1 schema 拒绝                          零查询
  V2 来源检查                             一次集合查询
  V3 绑定器,对每个 slot:
       ref 持有值、hint 匹配             → 绑定
       hint 不匹配、别的 ref 持有        → 自动重指,记录 repointed_from(§9-②)
       hint 是 label 短名                → 展成全名
       值 not_alone                      → 换成同 run 的合计(若存在)否则拒绝
       无解                              → 拒绝;信里只剩真问题
  V4–V7 判定
```
**一个绑定器,四个出口共用**:respond 块、`submit_brief`、report 门(轨迹 = run 子表)、散文 v1 只读渲染不迁移。

## §5 输入侧配对规则

1. 工具结果里每个可引值以 `label: value (unit)` 出现——label 就是绑定器认的名字。
2. **读者精度**呈现,账本原精度留在行里。模型看到的 = 读者看到的。
3. **规则禁引的值不进上下文**(共线单系数、不可单引成分):not_alone 从验证前移为投影;方向/位次仍给。W5 已实证(19→0 拒,分析未变差)。
4. **一份资源声明**(表 → 可引列 → 单位 → 显示名)替代 `_RUN_CHILDREN` / `_CALC_RESULT_KEYS` / `display_names` / resolver 四处描述;工具输出、绑定器、渲染器、审计层同读。

## §6 排程(单人约 7 人日;每步 offline 全绿 + 电池增量 → commit;S8 前不 build 镜像)

### S0 · 基线(0.5 天,先做)
- `scripts/rubric_battery.py` 全跑一轮存 `docs/spikes/V15_BASELINE.json`;从 `agent_steps` 抽出口指标快照(拒绝率 / 尝试中位数 / 无答案率 / 峰值 prompt)存同目录。
- **修测量器**:`scripts/eval_faithfulness.py` 对块答案读 `meta.blocks` 的槽,不再重解析渲染文本(今晚 27 条假拒绝的来源)。
- 判据:基线文件在;eval 对块答案零假拒绝。

### S1 · 资源声明 + 账本单位列(1 天)
- `analytics/resources.py`(数据):`{table: {column: (unit_class, display_name, citable)}}`。由它**生成** `_RUN_CHILDREN` / `_RUN_COUNTS` / `display_names.METRIC…` 的等价物;守卫断言四处不再各持清单。
- 迁移 `v15_calc_unit.sql`:`calc_ledger.unit_class`(幂等);写入侧 `calc_service._record` 落单位;**一次性**用 `_CALC_RATIO_OPS` 回填历史行,然后该表退役(镜像消失)。
- 判据:resolver 不再 import `_CALC_RATIO_OPS`;`test_display_names` 改读资源声明。

### S2 · 文法与 schema(0.5 天)
- `respond` v3 JSON Schema 表达 §2 全部形状(closed enums、required、items);`answer_blocks.validate_shape` 只剩 V4 一条正则。`comparison` 断言进 schema。
- 判据:26 个形状码中 ≥20 个由 schema 拒绝(`arg_validation` 路径),`validate_shape` ≤ 30 行。

### S3 · 绑定器(1.5 天,本批核心)
- `services/binder.py`:§4 算法;`not_alone` 唯一实现;`repointed_from` 记录进 `verified.matches`。
- `numeric_verification` 瘦身:删 `_EXEMPTION_PATTERNS`(留日期一条)、`_COMPATIBLE`、`_DERIVATIONS`、`_derived_class`、`extract_numbers` 的度量分类;`verify()` 保留给散文 v1 只读路径。
- 判据:合成夹具上,今天的三类拒绝(`figure_not_held_by_this_ref` 有 `held_instead_by`、`unknown_label` 短名、共线单引有合计)**全部被绑定器自动修复**;`numeric_verification.py` 行数 ≥ 减半。

### S4 · 四门合一(1 天)
- `submit_brief`、`report_verification.verify_report` 改调绑定器(report 轨迹 = `evidence_ids_for_run`)。
- 判据:守卫断言三处 import 同一个 `binder.resolve`;`not_alone` 在代码库只出现一处执行点。

### S5 · 输入侧 + R1 前移(1 天)
- 工具输出经资源声明加句柄与读者精度(`describe_issuer`、`get_portfolio_analysis`、`get_attribution`、`reconcile_move` 等 run 读);共线时单系数不进载荷(推广 W5)。
- 轨迹 R1 移到工具层:`explain_episode` / `get_portfolio_analysis` 作为组合原因类回答的前置(工具描述 + `trajectory_gate` 删 R1;R2 并入 V6 action)。
- 判据:模型看到的每个数字都能在资源声明里找到句柄;`trajectory_gate.py` 只剩 R2 或删除。

### S6 · 展示惯例前移(0.5 天)
- `analytics/display_conventions.py` + `apps/web/lib/display.ts` 同一套(跨语言双向守卫仿 `lib/errors.ts`);`prose_of` 用它;`AnswerBlocks.display` 读它。
- 判据:存储文本、渲染、审计层、rubric 输入四处显示一致;`1.08663e+07` 在代码库任何输出路径不可能出现(测试)。

### S7 · 删除与文档(0.5 天)
- 删除 §3 列出的全部;`_SYSTEM` 块契约段改写为 §2 文法的自然语言(措辞过目);`TARGET_ARCHITECTURE` 加 Law E:**知识只投在"选哪个",形状交给 schema 与原语**(V14-B 教训)。
- 判据:`grep` 零残留;`_SYSTEM` tokens 不增。

### S8 · 验收与切换(0.5 天)
- 电池全跑(rubric + 出口指标)对照 S0;四镜像重建 → 容器内 grep → smoke_ui → 一次真实排程 run(report 门走绑定器)。
- **切换判据(不达标不切)**:① 已过门答案的槽值与 V14 逐位一致;② 拒绝率 ≤10%、尝试中位数 = 1、无答案 = 0;③ rubric 不低于 S0;④ 峰值 prompt 均值下降 ≥30%。
- **中止判据(先写死)**:S3 后两轮电池尝试中位数 >2 或无答案 >0 且不收敛 → 停,保留 S0/S1/S5/S6(各自独立有价值),出口回 V14-C,再议。

## §7 结构守卫(每条钉住一个消灭)

| 测试 | 钉住 |
|---|---|
| `test_binder.py` | 三类可修拒绝自动修复;无解才拒;`repointed_from` 记录 |
| `test_one_resolver.py` | 四出口 import 同一绑定器;`not_alone` 单执行点(全库 grep) |
| `test_output_grammar.py` | schema 拒绝 §2 外所有形状;正文 `\d` 除日期为空 |
| `test_resources.py` | 四处清单由资源声明生成;新增可引列缺声明即红 |
| `test_display_conventions.py` | py/ts 双向锁;科学计数法零出口 |
| `test_comparison.py` | gt/lt/near 正例负例;跨单位类拒绝 |
| `scripts/rubric_battery.py` | S0 vs S8 对照 |

## §8 本批不动
IPV/Brinson/货币归因;散文 v1 历史迁移;judge-revise 环;联网搜索进 meta 面(独立议题:今天模型对"你可以联网"未声明做不到——属 V6 action 类的反向,"没做的事要说",可在 S5 顺带:无该工具时 `_SYSTEM` 一句)。

## §9 待拍板
1. **日期是否唯一豁免类**(建议是;否则日期走 slot 属性)。
2. **绑定器自动重指是否可接受**——渲染 ref 可能不是模型写的那个,但一定持有该值且有 `repointed_from` 记录。
3. **R1 前移到工具层**,出口不再判轨迹。
4. **`comparison` 断言纳入**(建议是:小、正交、封今天最大一类假话)。
5. **输入侧不给不可引值**(建议是;W5 已实证)。
6. 四门合一顺序:respond 先,brief/report 跟进(建议同批,爆炸半径由 S8 切换判据控制)。
