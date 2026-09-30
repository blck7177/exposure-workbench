# S3 实施结果

本次已按 ARCHITECTURE_S3.md 完成核心架构改动，目标分支 `codex/simplify-agent-loop-s2`，产品代码基线 `6a03fe5`。本文记录推送前的实施与离线验收快照；真实模型测试和部署不在此验收结果内。

## 已实现

| 边界 | 行为变化 | 验证 |
|---|---|---|
| Lead → specialist | ask 增加 input_refs；派单前按会话 ledger 验证；runtime 在独立证据块传递真实值、主体、量纲、期间、来源与参数 | 实际首次 prompt、delivery 记录、未知/跨会话 ID 反例 |
| Lead → resources | 原 meta MCP mount 通过 bearer deny 收窄为 list/read/metric/calc；不必为简单取数和计算再派单 | 直接读取、事实门禁、服务端 deny 参数、16 次证据调用上限 |
| 方法加载 | open(handbook:issuer/market/risk) 按需读取方法说明；资源权限仍由 MCP 控制 | 方法章节读取及既有工具权限回归 |
| Ledger → context | 选中证据和检查过的 notes 优先于未选中批量行；输入与 open 共用带元数据的分页读取；rep_ 可读所属会话报告日志 | 完整页遍历、旧选中证据不被新 bulk 淹没、报告会话隔离 |
| submit → state | 拒绝只作用于本次候选；下一次省略坏 note 即可放弃它；已接受内容保留，仍支持按 ID 修改/撤回 | X01 原始提交及部分成功、失败替换测试 |
| 计算与答复 | drawdown×money 检查主体；保留 measure 限定并检查显式 beta benchmark；passage 匹配完整数字/单位与所引句子的来源范围 | X07/Q16/Q19 原始重放与正确反例 |
| 状态与观测 | factual boundary 版本升至 2；旧校验戳不自动复用；报告记录 input_refs；计数器纳入直接调用和显式输入引用 | 旧状态拒绝复用、计数器与全部离线回归 |

保留 PostgreSQL ledger/analysis_state、scope/fingerprint 校验和乐观并发控制。未新增协调服务、运行时语义 reviewer 或数据库迁移；现有前端数据结构继续兼容。

## 验证结果

- 离线全套：**3165 passed，10 skipped，279 deselected**。
- 新增架构与原始 trace 回归合计 33 项，覆盖上述边界。
- `scripts/v1_wording.py --check` 与 `git diff --check` 通过。
- 使用项目现有 Python venv、`PYTHONPATH=src`、`PYTHONUTF8=1`。
- Windows Python 的 mkdir(0700) 会移除本环境 sandbox group 的目录权限；测试 runner 仅在本次新建 scratch 树中沿用 workspace ACL，未修改产品权限或测试断言。
- 原 baseline 离线重放保留；S3 结果另存为 s3-replay-results.json。

## 原始案例结果与边界

- **X07**：新增计算会拒绝 NVDA 市值 × portfolio deepest drawdown；正确 NVDA 输入仍可计算，独立核对为 **$88,280.38496**、book 的 **0.821523856%**。旧会话里已经生成的错误 derived fact 未被迁移或重算，不能把 producer 修复说成旧答案自动修正。
- **Q16**：已录制的 rates_up beta 被写作 SPY beta 的答案，现在被拒绝。该检查针对显式 benchmark，不声称能判断任意自然语言含义。
- **Q19**：16% 不再从 $16.5 billion 获得支持，也不能从同句所引来源之外借数字。年度/表格列绑定仍需结构化表格能力。
- **X01**：原始第二次修正提交不复用旧 note ID 也能返回；已接受的正确 note 保持。

更严格的单位校验也揭示旧 corpus Q05 的 8 处表格值缺少局部美元单位依据，现被拒绝。不是简单放宽规则以维持旧 accepted 数量。两项合成正例补全了其原本要测试的显式美元标识，另外增加了缺单位反例。

## 尚未声称完成

未跑真实 LLM + 数据库的 main 20 turns / X 9 turns，因此没有新的实际交付率或成本改善结论。Q03 的结构化表格数量、通用期间别名/批量能力、all-proceeds scenario 和语义完整性验收仍是计划明确列出的后续能力阶段。本轮没有修改模型、fixture、并行策略或原有 subagent 预算。

直接读取/计算另有 16 次上限；live 比较时必须计入 lead + specialist 的总调用量，不能把减少派单次数当成成本降低。

