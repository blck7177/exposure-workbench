# IMPLEMENTATION PLAN V33 — 分析师 + 证据子 agent + 数字/关系词核对

> 依据：`docs/spikes/v33/FINDINGS_V33.md`（20 题实测）、`TRACE_V33.md`（逐步 trace）、`MODEL_IO_ANALYSIS.md`（模型 I/O 层分析）、`MODEL_CONTRACT.md`（模型信息契约）、`AGENT_ARCHITECTURE.md`（架构讨论）。
> 起点：HEAD `99804d6`，`pytest -m "not live"` 基线 2291 passed / 11 skipped / 19s。
> 已定决策：回答是自然语言；对不上的数字退回重写最多两次；关系词要查；分析师不碰 schema，证据子 agent 不写 prose；子 agent 与分析师同 session 同 message。

## 0. 目标与非目标

**目标**：把一个 loop 里争注意力的两份工作拆开，并把类型规则、表达边界、图形身份从"靠拒绝学"变成"输入里就有"。

```
分析师 loop（meta_agent）             证据子 agent（evidence_broker）                核对（answer_check）
 读：角色+一条规则、问题主体的目录、    读：请求项、签名表、目录                          读：分析师的自然语言、本 session ledger
     证据摘要                          做：procedure/构造器 → program；类型报告；           查：数字 ↔ 账本（值/身份/引文/问题）；
 写：request_evidence(items)、             read_filings/search_web/start；返回摘要+边界          关系词 ↔ fact 的 rank/op/as_of/tier；
     自然语言回答（出口=无 tool call）  不写：任何给读者的话                                  [f_id] 消歧；≤2 次
```

**非目标（本轮不做，列入 §6）**：research_session/brief 的同形改造；日报改读 ledger；价格方法的 as-of；held_back 图形上账本；step payload 落盘的 schema 迁移；MCP 面裁剪与容器重建；多轮历史里的 facts 保留。

**不变量**：每次工具调用仍经 registry.invoke（校验/预算/adapter/落 step）；ledger 仍按 session；agent 树深度仍为 2；web 读的 blocks 形状不变（paragraph runs / table / chart）。

## 1. 分阶段

每阶段结束时 `pytest -m "not live"` 全绿；阶段 5 用 V33 的 20 题做验收。

### Phase 0 — 签名表与静态类型检查（tool，不改行为）

文件：`services/program_service.py`，新 `tests/test_v33_typecheck.py`。

- `SIGNATURES`：每个原语的参数类型与返回类型规则，作为数据。类型词汇：`scalar | series | vector | ranking | table | run | number | date | string | labels | trades | subject | subjects | any`。返回类型依参数而定（`fundamentals`：`last_n`→series，`metric` 缺→table，否则 scalar；`method`：subjects 列表→vector，`last_n`→series，yields>1 且无 key→table，否则 scalar；二元算术：任一 vector/ranking→vector，任一 series→series，否则 scalar；`sum/avg/min/max/std`：vector|series→scalar；`abs`：scalar→scalar；`rank`→ranking；`top/select/filter`→vector；`vector`→vector；`yoy/qoq/pct/cagr`→series；`latest/at`→scalar；`window_return`→scalar；`sell/buy`→table；`run`→run；`column`→vector；`figure/pick`→scalar）。
- `typecheck(program) -> list[problem]`：解析后按绑定顺序推断每个节点的静态 kind，**一次收集全部**问题：unknown_primitive / unknown_binding / missing・extra args / 参数类型不符 / 操作数 kind 不符。每条 `{at, reason, expected, got, fix}`，`fix` 是可执行的一句。依赖出错节点的节点标 `blocked`，不重复报。
- `signature_text()`：给子 agent 的 prompt 用，替代 RUN_DESCRIPTION 里的名字表。
- `BOUNDARIES`：价格方法无 as-of；scenario 不重估 beta/stress/vol；无阈值筛选以外的谓词。

验收：对 V33 里失败的 program 形（Q08 vector-of-series、Q11 sub 字面量、Q07 `at:"prev"`、Q13 vector 字面量、Q01 table-of-series）typecheck 各报出预期问题；对 23 个 skill 示例 program 报零问题。

### Phase 1 — 语言完备与身份补全（tool）

文件：`services/program_service.py`、`services/typed_calculator.py`、`tests/test_v33_language.py`。

1. **typecheck 接入 `run`**：解析后先 typecheck；有问题则返回 `{"error": "type_errors", "problems": [...]}`，**不执行**，不产 absence fact。运行期拒绝（数据缺、方法失败）仍产 absence fact。
2. **字面量成为一等操作数**：`add/sub/mul/div` 一侧是数字时先记一行 `calc.scalar.constant`（值；单位跟随另一侧），再走 `tc.calculate`；`vector` 的 entry 允许数字（同样记常数）。常数因此有 id。
3. **`filter(of, op, level)`**：从 vector/ranking 里选出满足 `> >= < <= == !=` 的条目，level 是数字或 scalar；返回 vector（空→absence "no entry satisfies"）。Q11 "谁超过 8%" 的表达。
4. **方法结果携带自己的参数窗口**：`_facts_of` 把 `params` 里日期型的值（peak/trough/at/start/end）并入 fact 的 `params`，有起止则 `window={start,end}`。Q14 的起点日期由此进入 `identity_tokens`。
5. **同一量同名**：TABLE 分支的三段标签拆分不再受 `":" not in ref` 限制；`sector_exposures.Technology.weight` 在 run 与 scenario 下同为 `measure=sector_exposures.weight, subject=Technology`。
6. **`issuer.panel` 可定型**：`_from_payload` 识别 `lines: {name: {value, calc_id}}` → TABLE。
7. **崩溃变拒绝**：`_dispatch_method`/`_p_fundamentals` 包住服务层 `ValueError` → 该节点 `invalid_params` absence。
8. **pick 字面量可见**：note 里 `"kind": "literal"`；经 4. 落到依赖它的 facts 的 params 上。

### Phase 2 — 核对器（validation）

文件：新 `services/answer_check.py`（复用 `answer.py` 的 tokens_in/rendered/derive_table/fill 与 `ledger.py`）；`tests/test_v33_answer_check.py`。`claims.py`/`gate.py` 不删（submit_brief 仍用）。

- `check(text, ledger, question) -> Verdict`：分段分句；每个数字/日期/表单号 token 按 `resolve_number → resolve_identity → resolve_in_passages(全部 passage，保留护栏) → 问题里的数字` 解析；都不中→`unsourced_figure`（带路由）。
  - **消歧**：值命中多个身份不同的 fact → 用同句主体词（ticker/label）、日期、measure 词收窄；仍多解→`ambiguous_figure` 列候选；数字后紧跟 `[f_…]` 视为指定，须在账本且值相符。
  - **关系词**（同句，确定性）：最高级词旁的 fact 须带 `params.rank`→否则 `superlative_without_rank`；变化词与同句两个 fact：同 measure 同 subject、as_of 有序、方向与值一致，或单个 `op ∈ CHANGE_OPS` 的 fact→否则 `change_conflict`；tier 词旁须有 tier fact 且 subject 与读数一致→`tier_mismatch`；日期词（started/troughed/peaked/on/as of）后须是日期→`date_expected`。
  - `[table: node]`/`[chart: node]`：node 名对账本 facts 的 `params.node`→table 或 chart block；否则 `unknown_node`。`[f_…]` 单独出现须在账本。
- `accepted(...) -> {blocks, text, citations, verified}`：匹配到的数字替换为 `{fact: fill}`（值用 ledger display），标记去掉，表/图成 block。形状与今天一致。
- 拒绝形状 `{error, problems[], detail}`，problems **一次全量**。

验收：对 V33B 通过答案的原文回归——Q08 最高级、Q17 主体错位、Q18 "$1.83"/"factor share 0.85%"、Q15 "4.1% against 15.0%"、Q14 "started on 12.0%" 各被拒；Q20 这类无数字引文答案通过。

### Phase 3 — 分析师 loop 与证据子 agent（agents）

文件：新 `agents/evidence_request.py`（schema）、新 `agents/evidence_broker.py`、新 `services/program_builder.py`、新 `services/briefing.py`、重写 `agents/meta_agent.py`；`tests/test_v33_analyst_loop.py`、`tests/test_v33_broker.py`、`tests/test_v33_builder.py`。

**briefing.for_question(db, text)**：识别问题里的 ticker/port_/run_，组紧凑目录：组合→持仓（ticker/sector/asset_class/weight/market_value）、检查（current/warning/breach/实体）、可用 run；发行人→已 filed 行与覆盖、可计算/不可计算方法（带原因）、filings、价格覆盖；desk→not_held/cannot；加 `BOUNDARIES`。上限 12k 字符。

**evidence_request schema**（分析师唯一工具，进程内）：

```json
{"items": [{
  "subjects": ["MSFT","GOOGL"],
  "want": ["capex_intensity","roic"],        // 方法/度量/表.列（目录里的名字）；或 "filings:<query|item N>", "news:<query>", "prepare", "book", "scenario:sell NVDA 0.5"
  "window": "last 3 fiscal years",           // 可选：12m | 1y | at 2025-06-30 | last_n 8 | vs prev run | 自然语言
  "compare": "rank",                         // 可选：rank | change | versus | share_of:<name> | filter:>0.08
  "ask": "…"                                 // 可选自由文本，构造器不覆盖时给 program 作者
}]}
```

**program_builder.build(item, catalogue) -> program | NotExpressible**：确定性地把标准形编成 program（多主体成 vector；`last_n`→series 再 `latest`；rank/change/versus/share_of/filter；book→run+column/pick；scenario→sell/buy；vs prev run→which='prev'+sub）；名字经 `name_table.route`；不可表达→`NotExpressible(reason, nearest)`。

**evidence_broker.fulfil(items, ...)**：`prepare`→start；`filings:`→read_filings；`news:`→search_web；其余→builder；不可表达且有 `ask`→program 作者 LLM（system=一句角色+`signature_text()`+`BOUNDARIES`；user=item+目录节选；最多 3 次：写→`type_errors`→改）。摘要每项：facts（id/subject/measure/display/unit/as_of/window/rank/op）、series（id/subject/measure/n/首末点）、boundaries（class/text/来源 fact id）。**摘要里每个值都来自 facts 块。** 共享 `tools_session`；自己的 `llm_session`；request/digest 各落一条 step。

**meta_agent.handle_message 重写**：messages=新 `_SYSTEM` + briefing + 历史 + 问题；tools=[request_evidence]；有 tool call→broker→摘要；无 tool call→`answer_check.check(content)`→通过完成；拒绝→problems 作为 user 消息追加，第二次拒绝→`_GATE_EXHAUSTED_TEXT`。空 content 无 tool call→"Write the answer, or request the evidence you still need."。meta 保留 prompt_tokens/pushed/verified/blocks/format/gate/gate_refusals。答案尝试落 `step_type='answer'`。

**faces**：本阶段不改 FACE_META_AGENT。

### Phase 4 — 目录修正（tool/skill）

`issuers_prepared` 只列 `_is_ready` 的，已登记未就绪另列 `issuers_preparing`；`describe(ticker, expand='methods')` 空结果修复；briefing 的持仓带 sector。

### Phase 5 — 验收与仪器

重启 fixture face、还原 9/13 快照、跑 20 题→`docs/spikes/v33/V33C.json`；`battery_counters.py`/`conversation_battery.py` 改读 `step_type in ('answer','respond')`，新增 request 数、type_errors 数、broker completion 数；对照 V33B。

## 2. 角色边界

| 角色 | 给它的 | 拿走的 |
|---|---|---|
| LLM 分析师 | 目录、摘要、边界；自然语言出口 | program、claims、id、渲染 |
| LLM program 作者（子 agent 内） | 签名表、边界表、类型报告 | 业务判断、给读者的话 |
| tool | 签名/typecheck/常数/filter/身份补全/同名 | 崩溃、无路径的拒绝 |
| skill | procedure 仍以示例 program 存在，builder 读它 | 无 |
| validation | 数字 + 关系词 + 消歧 + 一次全量 | 11 种 relation 的散文约束 |

## 3. 风险

builder 覆盖面（先用 20 题标定）；消歧误拒（设计内的两次机会之一）；关系词漏判（词表小是有意的）；research 路径不动（claims/gate/submit_brief/repeats 保留）；`test_v28_roles` D1 与 `test_meta_agent_gate`/`test_v31_agent_gap` 的 respond 用例随设计改写。

## 4. 与既有文档

MODULE_NOTES M10 "respond 也是工具" 与 research_session "探索者即写作者" 在落地后失效，Phase 5 后回写；PROGRAM_LANGUAGE.md 增补 filter/常数/typecheck/literal；ARCHITECTURE_AS_BUILT.md agent 一节随 Phase 3 更新。

## 5. 执行

Phase 0→1→2→3→4→5，每阶段后全量离线测试；提交按阶段一次；本轮不 push。

## 6. 后续

research_session/brief 同形改造；日报改读 ledger；价格方法 as-of；held_back 上账本；`agent_steps.payload` 迁移；面裁剪与 exposure-mcp 重建；多轮 facts 保留。
