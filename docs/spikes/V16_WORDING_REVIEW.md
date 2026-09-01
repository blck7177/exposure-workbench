# V16 模型可见措辞 — 待 boss 过目清单

（按长期指示：措辞过目与批准意图分开。以下均已实现并测试，wording 可改，改动零成本。）

## 1. meta_agent._SYSTEM 全文重写（6.6k → 2.6k 字符）
- 新定位句："You are the analyst … The analysis is your job … The tools are your
  instruments … What you bring is the judgement about what to compute and what
  it means for the question asked."
- 删除内容：全部工具路径教学（42.6%，已由 Tool.description/describe_* 数据承载，
  audit 证实 R6–R15 全部有重复副本）；领域方法散文（23.4%，共线性→describe_run
  collinear_note、utilisation→list_run_alerts description、drawdown→工具描述、
  总量分项→calculate description + describe_issuer 数据）；防验证失败规则细则
  （拒绝信本身会教）。
- 保留：角色+分析定位、证据纪律的 why（AS OF/窗口/观测数/UNAVAILABLE）、
  不下判词、snapshot 起点+委派不阻塞、blocks/slot 最小说明+一个 JSON 例。
- 位置：src/exposure_workbench/agents/meta_agent.py

## 2. 八个价格工具的 description（price_analytics_service._TOOL_SPECS）
- get_price：close vs adj_close "neither stands in for the other"
- get_rolling_volatility：“A window the history cannot fill is refused with the
  counts, never quietly shortened.”
- get_beta：“Fewer than 60 aligned observations is refused with the counts
  rather than estimated.”
- get_momentum_12_1：skip-month 的理由句（short-term reversal）
- get_distance_from_52w_high：“a high 3 sessions old and one 300 sessions old
  are the same ratio and different facts, so say the date”
- get_adv：shares vs dollars 两个量的用途句

## 3. calculate 的 as_quantity 参数描述（Tier 2 开放）
- “name the result IS — 'market_cap', 'fcf_yield' — so the table calls it that
  and your answer can slot it by the name; omitted, the row is named by its
  lineage (a.divide.b)”

## 4. Tier 1 新公式的 note / authority / 失效条件句（analytics/formulas.py，16 条）
- roe 负权益拒绝句：“a loss divided by negative equity prints as a positive
  return, so the ratio is refused rather than displayed”
- roe note 内 DuPont 方法句：roe = net_margin × asset_turnover × equity_multiplier
- roic/quick_ratio/fcf_margin/capex_intensity/net_debt_to_ebitda/CCC 各自的
  bank 不适用理由句（每条公式自己的句子，不再是全局一句）
- accruals_ratio authority：Sloan (1996), The Accounting Review 71(3)
- 各 note 中"期末值而非平均值"的口径句

## 5. describe_issuer 新字段与顺序
- 公式目录按 FAMILY_ORDER 阅读顺序（cash→earnings→margin→returns→turnover→
  liquidity→coverage→leverage→reinvestment→quality）而非字母序
- 银行 issuer 的不适用公式：computable=false + not_for_this_issuer=true
  （理由句不随目录、留在 evaluate_formula 的拒绝里——V11-T 教训）

## 6. 读者侧 captions（display_names.py，24 条新增）
- 8 个 v4 metric（"Earnings per share, diluted" / "Weighted average shares,
  diluted" / "Share repurchases" …三个股数的措辞刻意保持可听出区别）
- 16 个公式（ROE/ROA/ROIC 保持缩写；"accruals (net income − cash from
  operations)" 带构造式）

## 7. semantics 新条目（analytics/semantics.py）
- 三个股数互为 do_not_combine 的三句 note（weighted 配 flow、outstanding 配
  instant 配市值）
- eps_diluted 的 ASC 260 note（treasury stock method 把期内均价折进摊薄分母）
- dividends_paid 的 preferred/NCI 口径残余差 note（JPM 实际存在 preferred）

## 8. 未收缩项（本批有意不动，登记）
- research_session._SYSTEM（32% 防验证失败记忆项）——收缩待下批，与本清单同流程
- V15-S6 的旧措辞清单仍待过目（describe_run capabilities 等）
