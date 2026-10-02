# 测试轮次记录

2026-10-02 清理。V2–V38 各轮的记录已删除：本目录根下的 `V2_`…`V24_`、`M2`、`P9`、`R20`、`ROUND3/4` 等文件（下面三份除外），`v26`、`v29`、`v30`、`v32`、`v36`、`v38` 整个目录，`v33`、`v37` 里除下面几份输入以外的部分；`tests/battery/` 同时删除。它们测的是已退役的架构，没有测试或运行脚本再读它们。要看原文：`git show 152375f:<路径>`，例如 `git show 152375f:docs/spikes/v30/V24_B1.json`。

留下的：

- `v1/`：V1 计划之后的各轮（`V2E_mini`、`V2E2_mini`、`S2_mini`、`S3_mini`），跑轮次的 `tools/phase_e.sh`，跨族题 `questions_cross_family.json`
- `v33/questions_v33.json`：二十题，`phase_e.sh` 和 `tests/test_v1_cross_family.py` 读
- `v37/V37C.json`：`tests/test_v1_cross_family.py` 读
- `v37/tools/`：`phase_e.sh` 调用的 `credit_probe.py`、`v37c_audit.py`，换模型跑一轮用的 `battery_with_model.py`
- `V3_RETRIEVAL_BASELINE.json`：`scripts/eval_retrieval.py` 与检索的 live 测试读
- `V9_FORMULA_BASIS.md`、`M2_PARSE_EVAL.md`、`M2_PARSE_EVAL.json`：现行代码注明的依据（公式出处；申报解析的选型）
- `agent_context_tools/`：2026-10-02 的分析（`docs/AGENT_CONTEXT_TOOLS_2026-10-02.md`）所依据的离线验证与两次实跑

`scripts/` 里还有一批专门处理旧轮次的脚本，用法示例仍指向上面删掉的文件；它们留待单独清理。
