# 归档脚本（不再运行）

2026-09-19 随程序语言一起归档。这些脚本直接依赖已退役的模块——`services/program_service`（`run(program)`）、
`services/program_builder`（`compile`）、`services/digest`、`analytics/skill` 里的 14 个域与程序、旧的工具面常量——
按原样已无法运行，只作历史保留：

- `program_run.py`、`gold_brief.py`、`gold_from_programs.py`、`v30_replay_method_names.py`：通过 `run` 工具跑程序
- `v30_wording_review.py`、`v36_wording.py`：从旧 prompt 常量生成措辞表（V1 的措辞表由 `scripts/v1_wording.py` 生成）
- `v29_compare.py`、`v26_diagnose.py`：对比或诊断旧 skill 层

现行计划见 `docs/IMPLEMENTATION_PLAN_V1.md`。
