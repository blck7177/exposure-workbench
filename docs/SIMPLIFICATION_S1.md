# Agent loop 简化 S1：实施与验证

2026-09-29，基于 `origin/desk-v2-wip@e5d4b45003c593ea42730110a837a010c2a7f725`，工作分支 `codex/simplify-agent-loop-s1`。用户已批准 [简化计划](SIMPLIFICATION_PLAN.md)，本批实现其中 S1；S0 只完成基线口径冻结，独立 oracle 和完整实例评分仍待完成。

目标是让主 agent 根据原问题与证据迭代：判断已有发现是否足够、还要问什么、哪些限制应向用户说明。Runtime 记录执行与事实检查结果，不再签发“用户问题已完成”的语义结论。

## 已实施的接口

| 位置 | 行为 |
|---|---|
| `agents/delegation.py` | `ask` 只收 `tasks`；每个任务保留 `analyst`、`subjects`、自然语言 `lines`，可选 `context` 和 `follow_up_of`。移除 requirements、逐字 anchor 和 for 映射。保留基本类型、角色和数量约束。 |
| `agents/meta_agent.py` | 删除 `unaddressed` 覆盖阻断和自动追加的 “Still open” 尾句。事实检查与两次句子修复机制继续运行。 |
| `delegation.for_lead` | ask 仅返回 task id、brief 状态、已接受 finding 数、报告 id 和已建资源收据。发现正文、证据和 caveat 由 STATE 工作视图承载。 |
| `services/analysis_state.py` | 工作视图提供原问题、scope、已检查 findings 及证据、caveats、任务说明与结果、实际工具失败、未交付证据提示和预算。工具拒绝显示为 `tool_result`，不再把原因族投影成问题已关闭。 |
| `meta_agent._open`、`agents/delivery.py` | `open(ast_…_viewN, offset)` 读取本 turn 的快照分页。记录实际进入 prompt 的行与页范围；仅出现 id 不算读过整行或整段系列。 |

新派单示例：

```json
{"tasks": [{"analyst": "issuer", "subjects": ["XOM"], "lines": ["比较最近四季的杠杆与偿债能力，并结合 10-K 解释压力来源。"]}]}
```

新答复元数据：

```json
{"protocol": "simplified-s1", "delivery": "answered", "completion": null}
```

`delivery=answered` 只表示已交付经过事实检查的答案；若未交付则为 `not_answered`。它不表示回答覆盖了全部原始要求。旧 gate 错误诊断仍保留。消费者不能将 `completion=null` 自动解释为 completed 或 partial。

## 状态与交付约束

- 继续复用 PostgreSQL 中现有 `analysis_state`、ledger、analyst_reports 与 trace，不增加 Redis、控制 agent 或数据库迁移。历史 requirements/completion 字段和解释函数仍可读取；新循环不声明 requirements，也不以历史完成状态控制回答。
- 新任务的 `follow_up_of` 不携带 requirement 映射，因此不会批量撤销此前已通过的发现。历史映射逻辑只为旧记录兼容保留。
- 保留 task 的 `asked` 作为工作指令，不将委派中的文字或数字升级为事实来源。STATE 明确标识这个信任边界。
- 只把 handoff 已通过的 finding、caveat、why 和 follow_up 放进工作视图；被拒原文不进入收据或状态。caveat 的引用一同进入 finding 的证据指纹，跨 turn 继承时重新检查 caveat。
- 一页最多 40 个完整条目，24,000 字符为软上限。finding 和 caveat 不切开；单条超过软上限时完整返回并标记 `oversized_card`。这仍可能消耗较多 context，不能理解为无限容量保证。
- 页游标对应不可变的 turn 内快照；读取后 delivery gap 变化或新任务完成，不会使旧游标跳过条目。范围为 `[start, end)`，与已有行/系列分页一致。快照不新建持久化存储，也不允许打开其他会话状态。

角色、工具面、模型选择、分析师调用预算、lease、事实检查规则没有改变。语义 reviewer 仍只用于离线测量。

## 冻结的历史基线与口径纠正

来源为仓库已提交的 `V2E2_mini.json`、`V2E2_mini_X.json` 和 `acceptance_matrix.draft.json`。文件 SHA-256、逐 case 读数与汇总见 [SIMPLIFICATION_S1_BASELINE.json](spikes/v1/SIMPLIFICATION_S1_BASELINE.json)。这些是旧版本的描述性读数。

| 范围 | turn 数 | 模型声明要求 | covered | boundary | unresolved |
|---|---:|---:|---:|---:|---:|
| 全部主测试 | 20 | 75 | 13 | 12 | 50 |
| 有答案的主测试 | 14 | 48 | 12 | 7 | 29 |
| X 系列 | 9 | 27 | 16 | 4 | 7 |

`ACCEPTANCE_V2E2_mini.md` §5 把“全部 20 题的 75 项、13/12”与“14 篇答案的 29 unresolved”混用了。这里固定两个分母，原报告保留作为历史记录。旧主测试为 14 answered / 6 exhausted；X 为 9 answered，但报告已指出 X06 主体错误与 X07 损失口径错误，所以 answered/completed 都不是质量验收。

独立目标仍为原始 20 题 / 65 项交付要求，加 X 系列的跨资源传递。现有矩阵只是规划草稿；不能把固定其哈希称为已完成独立数值 oracle 或边界预标注。S1 也不能再用“被门退回次数变少”证明质量提升。

## 验证及下一次实例运行

离线命令：

本批结果：**3097 passed、10 skipped、279 deselected**；`live` 用例未执行。措辞生成与一致性检查、Git whitespace 检查均通过。

```sh
python -m pytest -m 'not live' -q --tb=short -p no:cacheprovider
python scripts/v1_wording.py --check
git diff --check
```

新增/迁移回归覆盖：自然语言派单与追问、错误派单恢复、事实修复不再被覆盖规则拦截、工具拒绝不构成完成证书、被拒文字隔离、caveat 保留和复核、超过 40 条的可恢复分页、快照游标、实际 context 交付记录，以及原有错误数字继续被拒。

本批未运行真实模型 + 数据库的 20 题电池，尚不能断言实例质量改善。下一次运行须冻结提交、模型和数据快照，沿用 V2E2 的停表及 `--deny submit_brief --deny start` 夹具条件，同时按原始要求检查：正确交付、错误交付、可接受边界、不合理边界、静默遗漏、未作答。重点复查 Q05/Q09 已有结果能否进入答案、伞形问题能否综合回答，以及 X06/X07 依赖和口径传递。

S2 的 evidence-first submit、块级 refs、分析师部分交回，及 S3 的期间/表行名/批量算术/全部所得/段落数量能力均未混入本批。旧两态 brief 的书写与引用负担仍然存在；先比较 S1，再以独立提交推进这些包。
