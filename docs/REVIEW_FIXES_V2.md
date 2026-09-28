# V2 审阅修复记录（2026-09-28）

基线：`desk-v2-wip@afcce47e369a6e493614e91f78a254908c6f21e5`。本次按“修复发现的问题并推送”的授权修复实现，不改变三位分析师的分工，不引入 Redis，不改 lease、续期或任务写入 fencing；语义 reviewer 仍只在离线评测中使用。

## 修复与约束

| 问题 | 现在的行为 | 主要回归 |
|---|---|---|
| 同主体旧结论跨 book/run/日期/期间进入 STATE 或 PRIOR | 保存请求范围、数据快照、事实内容指纹及边界版本；恢复时重新通过同一事实检查。未带校验信息的历史记录不自动恢复为可信分析文字 | 同主体更换 book、run、as_of、期间、用户请求、事实值；旧记录、失效文字均拒绝恢复；范围完全一致可恢复 |
| 执行失败被算作“已完成但有边界”；成功行掩盖失败行 | 派发前登记每个任务行；缺失、拒绝及执行失败保留 unresolved。仅 data_missing / method_unsupported / policy_boundary 可以关闭要求；冲突阻止完成。回复须触及每个映射的结果 | 同一 R1 的一行成功、另一行失败/缺失/拒绝；合法政策边界；同期间证据冲突 |
| requirements 可完全省略 | 首次 ask 必须声明非空 requirements，task 必须关联；后续 ask 沿用原声明。问候或直接查看既有记录仍不强迫派发任务 | 缺失/null/空声明、合法首轮、后续复用；问候与跨 turn open |
| 最终 partial 被持久化或视图重新算成 completed | 持久化和投影优先使用最终 completion；没产生可发布回复也不能完成 | 收集证据已 covered，但最终回复遗漏时，输出、存储、重载视图均保持 partial |
| CAS 冲突后借新版本覆盖旧内容 | StaleState 向调用方传播，停止该次写入；不拿新版本覆盖陈旧内容 | 一次 save、零 load/commit、不改变旧版本；原有 CAS rowcount 测试仍保留 |
| battery 二次截断整段 args JSON | 导出完整已存 args/result，并保留 task_id、evidence_refs | 写入 10,000 字符拒绝稿后完整导出并解析 JSON；查询不再包含第二层截断 |

任务修复通过显式 `follow_up_of` 替代前一任务中它所服务的 requirements；同一前任务中其他 requirements 的失败不会消失。仅开一个无关联的新任务不会自动抹除旧失败。

状态恢复采取保守范围：标准化空白后的用户请求也属于范围。问题改写、追问或快照变化时，不自动继承上一轮的分析文字；历史原始事实仍在 ledger，可通过 `open` 重新读取。这里没有加入语义日期解析器，也没有通过扩大文字信任来实现记忆。旧记录无需数据库迁移，但不会自动获得新版信任标记。

`open` 在新 turn 已有 ledger 行时即可使用。每个 completion 的交付记录扫描实际组装的 prompt，覆盖 STATE/PRIOR；实际事实行、仅出现的引用 id、分页区间分别记录。STATE 同时显示 lead completion 已用预算和上限，任务记录保留自身 cost。存在某个 id 不代表收到了完整序列。

## 验证

完整离线套件：`python -m pytest -p no:cacheprovider -m "not live" -q --tb=short`：**3085 passed、10 skipped、279 deselected**。其中 `tests/test_v2_review_regressions.py` 覆盖本次修复的状态恢复、逐行完成、显式修复、CAS、最终 partial、实际交付与跨 turn open；测试使用真实状态/协议/校验代码，LLM、工具面和 DB transport 按用例替换。

本机为 Windows / Python 3.12，使用 UTF-8 模式及纯 Python SQLAlchemy。临时目录兼容设置只在工作环境，未进入产品仓库。另修复了两项旧测试的平台假设（路径分隔符、外部 grep）及 MCP mount 测试未设置固定测试密钥的问题。更新后的措辞单由 `scripts/v1_wording.py` 生成，包含首次 ask 的要求声明拒绝提示；生成器的 Python AST 引号表示差异不改变模型收到的语句。

## 尚未验收的部分

- 没有运行真实模型、冻结数据库的 E 轮或连续三轮 20 题 battery，也没有据此宣称实例问题全部解决。
- 原始规划矩阵已交付到 `docs/spikes/v1/acceptance_matrix.draft.json`，20 题、65 项要求；保留其原始 desk-v1 版本和基线说明。它不是 gold，也不是已执行评分。P0b 仍需补齐最终 schema、逐项原文 anchor/constraints/prelabel、独立数值 oracle 和评分脚本。
- CAS 采取停止冲突写入的策略，没有实现自动重放、跨进程任务恢复或状态合并；这些能力仍需故障注入实测。
- 要求是否覆盖了用户原话的全部语义、回答是否充分解释证据，仍需独立实例评测；确定性引用检查不证明语义充分。
- `propose` 的主循环入口、离线 reviewer 的标注语料与证据完备性、P4 剩余能力项及 P6 对照实验，未在本次扩展。

下一步应在冻结候选提交和 fixture 后，先建立独立 oracle，再运行实例 battery，按原始 65 项要求评估；执行失败不能靠改名成边界来通过验收。
