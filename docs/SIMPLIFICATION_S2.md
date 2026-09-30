# Agent loop 简化 S2：证据交接与逐项修复

2026-09-29。第二批基于 S1 `7bfddf2`，工作分支 `codex/simplify-agent-loop-s2`。落实 [简化计划](SIMPLIFICATION_PLAN.md) 的 S2，不包括 S3 的工具能力新增和 S4 的真实模型实例验收。

目标是减少“证据已取得，但格式交接失败后全部丢失”的损耗。Runtime 记录证据、已通过事实检查的说明和执行结果；主 agent 继续判断这些材料是否足以回答原问题。

## 当前模型接口

分析师只看到一个 submit 协议 `evidence-v2`：

```json
{
  "evidence": ["f_example0001"],
  "notes": [{"text": "分析说明，可包含与结论一起保留的限定。", "refs": ["f_example0001"]}]
}
```

- `evidence` 必填，最多 256 个已有 ledger 行 id；可交空数组。`notes` 可省略，最多 32 条。证据本身不需要转写成 brief。
- 每条 note 的必填字段只有 `text` 和 `refs`。Runtime 分配 `nte_…` id；同一任务后续提交可用返回的 id 修订，空 text 明确撤回该 note。
- 有效 evidence 累加；note 单独检查。另一项失败或修订失败不会抹掉此前通过的项。失败修订仍会留下诊断，不能被标记为成功提交。
- 旧 `lines/settled/finding/why/boundary` 不再是当前写入协议。历史 schema、解析器和报告读取适配仍保留，旧数据不改写为新语义。

实现位于 `agents/handoff.py`，调用者为 `agents/sub_analyst.py`。主 agent 的 ask 仍只表达分析任务，不填写底层工具 schema。

## 事实检查与可复用状态

`fact_boundary.check_block(text, refs)` 把可唯一定位的 scalar/series 数值生成现有 inline 引用，再交给同一个 `answer_check.check`。第一遍限制在该 note 的 refs 内，第二遍保留整本 ledger 的主体和度量词汇检查。不存在“refs 存在就放行正文”的入口。

保留单位、主体、期间、比较方向、排名、引用和引文等现有确定性检查。同值落在多条证据或多个日期上时返回歧义，要求缩小 refs 或写明确引用；不推断该数属于哪一个主体。Passage 的裸数字不由 block refs 自动赋予量纲，必须用原文引述或现有显式引用路径。该适配器不新增披露表格 quantity 能力。

限定条件与结论写在同一 note，接受、修复、保存时按整条保留。通过检查不代表语义被模型评审或整道题已答完；无可核对数值的判断沿用现有 checker 的能力边界，不宣称程序理解了所有财务含义。

已接受 notes 使用现有 findings 结构，`source=note`，保留原文、生成引用的正文和验证 stamp。新的 follow-up 不自动撤销此前结果。恢复时核对 scope、边界版本、证据指纹，并再次检查正文；存储的展示行不是新的事实来源。未通过 note 的原文仅进入 trace，主 agent、工作状态、报告展示和 follow-up 只收到诊断码。

## 执行结果、证据恢复与 context

| 项目 | S2 行为 |
|---|---|
| 正常提交 | `status=returned`、`stop_reason=submitted`，表示材料已交回 |
| 修复未通过或执行停止 | `status=stopped`，附 `submission_rejected`、`turn_limit`、`no_submission`、`provider_error` 或 `execution_error` |
| 已取得但未 submit 的证据 | 按该任务真实返回的行 id 和 pull 收集为 `available_evidence`，可在 STATE 分页读取 |
| 已通过的 note | 即使另一 note 被拒、后续 provider/tool 异常，也保留 |
| 未做的任务行 | 不再要求逐行制造 absence 或 policy 关闭证明 |
| 真实预算拒绝 | 保留实际调用的预算记录；不把它解释成业务问题无解 |
| ask 回单 | task/report id、执行状态、证据索引与计数、note id；不重复结果正文 |
| STATE | 原问题、scope、已检查说明、证据、操作记录、后台任务回执与预算；沿用 S1 的完整卡片分页与快照 |

证据恢复覆盖循环内 provider/tool 异常和正常预算/轮数结束，不承诺进程被强制杀死后仍完成最终写库。数据库不可用时不能凭空恢复持久化。执行预算、并行设置、lease、模型配置均未调整。

## 报告、页面和测量兼容

`analyst_reports` 沿用现有列，无数据库迁移：`brief.protocol` 与 `input_version.protocol` 标识新报告；`accepted_lines` 保存已检查 note；`brief` 保存证据和执行元数据；`blocks` 只从接受项生成。

页面支持 returned/stopped 报告，在停止后仍可打开已取得的证据、阅读已接受的说明；不会把 returned 展示为用户问题已完成，也不展示拒绝原文。旧报告继续使用历史读法。

答复元数据为 `protocol=simplified-s2`，保持 `completion=null`；`delivery=answered/not_answered` 仍只是是否交付。Delegation 的计数改为 `handoff`：selected/available evidence、accepted notes、rejected items、stop reason。`battery_counters` 分开 S2 与 legacy coverage；S2-only 的 `coverage_done_share=null`，不把取消旧行协议记作零完成率或满完成率。

模型实际读取的 wording 已重新生成到 [WORDING_V1.md](WORDING_V1.md)，完整前后差异可以从本批提交 diff 审阅。

## 验证与剩余工作

- Python 完整离线回归：**3132 passed、10 skipped、279 deselected**，命令为 `python -m pytest -m 'not live' -q --tb=short -p no:cacheprovider`。
- 新协议反例与循环测试覆盖 evidence-only、逐项修复、失败修订保留原文与限定、异常回收、错误 note id 修正、全部证据分页可达、错误数值/主体/单位/期间/方向/排名、同值歧义、引用越界、passage 量纲，以及 scope/指纹/缺失验证 stamp 的恢复拒绝。
- 主/sub 两层循环还验证了 evidence-only 正常提交与取证后未提交两条路径：主 agent 的实际 prompt receipt 收到证据行，能引用它交付经过检查的答案，没有伪造 note 或 completion。
- 前端 **8 个测试文件、86 项通过**；TypeScript `tsc --noEmit --incremental false` 与修改文件的 ESLint 通过。
- Windows 沙箱下默认 Vite 启动会尝试执行 `net use` 并被拒绝，因此前端使用仓库外临时 Vitest 配置：保留 `@` alias 和 Node 环境，`preserveSymlinks=true`、线程池单 worker、native config loader。锁定依赖及仓库配置未改变。Python 使用已有仓库外 Windows 临时目录兼容层。

**尚未运行真实模型 + 数据库的 20 题及 X 系列对照**；这些测试不能证明实际交付质量提升，也不能替代 S0 的独立 oracle、S3 的明确能力补齐或 S4 连续实例验收。下一步需要冻结当前实现，用相同 fixture、模型和预算核对真实输出中的正确事实、遗漏和错误业务边界，再比较修复次数与交付损耗。

本批没有引入 Redis、validation agent、语义运行时门或新的分析控制器，也没有开放 forecast/withheld 限制。最终答案仍使用已有 inline 引用与事实检查，block refs 只简化分析师交接。
