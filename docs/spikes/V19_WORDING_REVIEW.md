# V19 模型/用户可见措辞 — 待 boss 过目清单

（按长期指示：措辞过目与批准意图分开。以下均已实现并测试，wording 可改，改动零成本。）

## 1. `respond` 的 metric_table 说明（tools/meta_tools.py）
- "`metric_table` (rows of slots, one row per thing compared and one column per
  measure — the header and each row's label are derived from the slots' names,
  so a cell is never text; use it whenever you compare or rank)"

## 2. 表格拒绝句 `TABLE_RULE`（services/answer_blocks.py；schema 描述与 validate_shape 共用）
- "a table cell is a slot {ref, name} and nothing else. The header comes from
  the slots' names and each row's label from the issuer or period the slots are
  about — neither is written by you. One row per thing compared, one column per
  measure; words go in the title or a paragraph"
- （第一版写的是 "write the entity … in the slot's name"，live 第三轮看到模型照办去写
  `MSFT.net_income` 这种不存在的名字，改成现在这句。）

## 3. `submit_brief` 的 metric_table 说明（tools/research_tools.py）
- "`metric_table` (rows of slots only — the header and each row's label are
  derived from the slots' names)"

## 4. research_session 系统提示一句（agents/research_session.py）
- "a comparison or ranking is a `metric_table` of slots — its labels are
  derived from the slots' names, so a cell is never text."

## 5. `search_external_research` 描述（tools/research_tools.py，两面共用）
- "Search the web for what the filings cannot hold: news, guidance, an event
  after the last report, industry or regulatory developments — and anything the
  user asks you to look up. Each result is a src_ id on the table; a sentence
  resting on one names it in the block's cites. reason states why the filed
  evidence is insufficient."

## 6. meta_agent `_SYSTEM` 新增一句（agents/meta_agent.py）
- "What the filings cannot hold — news, guidance, an event after the last
  report, or anything the user asks you to look up — is
  search_external_research: its results are src_ ids on the table, and a
  sentence resting on one names it in cites."

## 7. `_FACE_CAPABILITIES`（tools/definitions.py，随 describe_run 返回）
- can 新增："search the web (search_external_research) for what the filings
  cannot hold — news, guidance, events after the last report — each result a
  src_ id a sentence can cite"
- can 改写："start background work: a readiness pass, an exposure run, an issuer
  research run (whose brief is read with read_issuer_brief)"
- cannot 删除："search the web from this face — …"

## 8. 搜索工具的两条拒绝句（tools/research_tools.py）
- `company_not_found`："not a listed symbol in this desk's universe"
- `not_investigable`：沿用 company_service 异常自身的句子（"Ticker 'TLT' is not
  investigable (an ETF files no 10-K or 10-Q)"）

## 9. UI（用户可见）
- 证据抽屉 fact 卡："Filing" 行改为 "10-K · filed 2026-01-30 · 0000320193-26-…"，
  新增 "Source → Open at SEC ↗"
- run 卡新增 "Holdings" 行，每个持仓一个按钮 "MSFT · 5,000 units →"
- trend 块上方一行序列自述："operating cash flow $7.59B (2022-12-31) ↑ $16.81B
  (2025-12-31)"，可点开序列
- 表格：行标签列 + 派生表头；对不齐的列在数字下方以小字写全名

## 10. `search_external_research` 两个参数说明（live 第一轮后加）
- `query`："what to look for; the issuer's name is added by the tool, so do not
  repeat it"
- `days`："restrict to news published within this many days (the past week is
  7); omit for no time restriction"

## 11. `evaluate_formula` 对已申报指标的拒绝补充句（services/formula_service.py）
- "net_income is a filed metric, not a formula: read it with
  get_flow(metric='net_income', months=…) for a flow over a window, or
  get_balance_sheet for a balance at a date"

---

# V20 措辞（同一清单续）

## 12. 页面 ⓘ 方法说明（analytics/methods.py，英文，逐句由代码常量写成）
- market_value / day_pnl / value_path / drawdown / volatility / attribution /
  factor_correlation / concentration 八句，原文见文件。
## 13. `withheld` 一句话（随 get_risk_state、run 端点下发）
- "Some measures this run computed are withheld pending validation and are not
  published anywhere on this desk: expected_shortfall_95, stress_loss_credit, …,
  stress_results. Say so if asked; do not estimate them from other figures."
## 14. 三个工具描述删去 stress 承诺
- `get_risk_state`："…exposure, volatility and drawdown metrics, and how many limit
  checks ran versus fired. Measures the desk computes but withholds pending
  validation are named in `withheld`, not given as numbers…"
- `get_portfolio_analysis`：删 "every stress scenario ranked by the size of the loss,"
- `describe_run`：分组列表删 "stress"
## 15. UI：VaR 95% tile 与顶部 chip、"If the market broke" 面板、共线时的 "Factor betas" 面板不再出现；ⓘ 按钮 aria-label "How this is computed"
