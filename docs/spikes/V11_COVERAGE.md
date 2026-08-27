# V11 验收 — 环上的六处,核心不动

> 2026-08-27。**1068 offline / 225 live 全绿**(批前 1039/211)。四镜像重建上线。
> 输入是 `dev_note/portfolio-demo/agent-battery/`(43 次真实会话 + 对抗复核)与其中的 `GAPS.md`。
> **本批不新增任何分析能力**,也不动四条公理——它们在 43 次会话里零算术错。
> **G2(投影契约)经 boss 拍板记为待办,不在本批。**

---

## 1. 做了什么

| 提交 | Gap | 一句话 |
|---|---|---|
| `3aa6b3c` V11-T | G3 | 系统不再与自己矛盾:截断按结构、`days_*` 补账本节点、删两个死模块 |
| `7b50309` V11-U/G | A1 + G7a | `cover` 的两种缺席拆成两个字段;门的拒绝带出算式 |
| `26893cb` V11-A | G1 | 缺席是一等对象:六种拒绝各铸一行可引的 `absence.*` |
| `edfd4da` V11-Q/F/P | G4 | 门长出文本那一半:引号逐字、`N percent`、共线单引 |
| `f88af56` V11-D | G8 | 标签漂移进 live 测试,18 条全部分类 |
| `8785a04` | — | 电池 harness 入库,带 `--repeat` |

## 2. 逐条效果(同一批问句,改前 / 改后)

| 用例 | 改前 | 改后 |
|---|---|---|
| [T02](../../dev_note/portfolio-demo/agent-battery/T02-judgment-lend.md) 借贷 | "**I would not lend to NVDA**";净债换成一个 "so" 推不出的句子 | "I would not give a yes/no lending recommendation… **the lending call is yours**";**净债 −$3.767B 带 `calc_76fbe39c70a9`**,并引用了三条以前被截断掉的 margin |
| [T04](../../dev_note/portfolio-demo/agent-battery/T04-missing-ebitda.md) EBITDA | "not reported as such **in the model**";4 次 respond | "…**not held for MSFT. This is a coverage limitation, not a statement that Microsoft does not disclose the item.**" |
| [T07](../../dev_note/portfolio-demo/agent-battery/T07-metric-selection.md) 收入增长 | "**the last four quarters are not available**"(假的) | 点名 `total_revenues` **并列出那四个季度**(46.743/57.006/68.127/81.615B) |
| [T10](../../dev_note/portfolio-demo/agent-battery/T10-incident-replay.md) 回撤 | 单引 market −0.00989278;"mostly stock-specific" | "**The factor set is collinear, so no single beta is fully determined**";**零个因子系数被单引** |
| [T11](../../dev_note/portfolio-demo/agent-battery/T11-double-count-trap.md) 双重计数 | "**The reported total debt is 82700000000**";"balance sheet flags" | "AAPL's **long-term debt total** is $82.7 billion";假的 flags 句消失 |
| [T12](../../dev_note/portfolio-demo/agent-battery/T12-unavailable-fcf.md) FCF | "**capex is not reported**"(数据其实在库里) | 两个窗口都点名,不再把映射空缺说成发行人空缺 |
| [T18](../../dev_note/portfolio-demo/agent-battery/T18-percent-quote.md) 收入集中度 | **一句承诺,用户什么都没拿到** | "Mounjaro and Zepbound together accounted for **56%**… collectively accounted for **82%**",**零次门拒** |
| [T16](../../dev_note/portfolio-demo/agent-battery/T16-single-factor.md) 单一因子 | 答了 LLY,八个因子零次提及 | 仍先答 LLY,但**明说** "the factor rows are collinear, so no single factor beta is quoted individually" |

`cover` 的两个新字段在实跑里各司其职:AAPL 得到 `no_facts_for_issuer`(它从未申报那两项),**GOOGL 得到 `missing_at_this_date: [long_term_debt_total]`**——那家确实申报总额、只是不在这个日期,是真信号。

## 3. 没有改好的(如实记)

**路由。** 同一问句 24 次重复:

```
调了 evaluate_formula  →  答对  9/9
没调                   →  答对  2/15
                                    AAPL 1/6   NVDA 0/6   AMZN 5/6   GOOGL 5/6
                          合计 11/24 = 46%(改前 12/22 = 55%,差值在这个样本量的噪声内)
```

**完全符合预期:G5 的结构收窄属于 G2,本批不做。** 余额表照样把 `long_term_debt_total` 平级铺出来,模型照样把它当总额。

一个没预期的副作用,是好的:**派生提示把余额表路径救回来两次**。门拒绝 82.7 之后回传"这个数 = X + Y,调 `calculate`",模型于是真的去算了——AAPL-3 得到 84.697、GOOGL-5 得到 100.164,都没走公式路径。它救不了加错分项的那次(AAPL-5 的 84.711 = 8.31 + 74.404 + 1.997,用孩子而非申报总额起算)。

**范围绑定。** [T10](../../dev_note/portfolio-demo/agent-battery/T10-incident-replay.md) 依旧没调 `get_drawdown_episodes`,依旧用一天回答"large drawdowns"。G6,本批不做。

**未机械化的判断仍在摇摆。** [T17](../../dev_note/portfolio-demo/agent-battery/T17-market-or-company.md) 这次写 "company-specific moves **a bit larger**",而它自己下一句就是 "factor model explains **55.6%** … alpha plus residual **44.4%**"——**与上一轮相反**。共线那条机械规则守住了(它老老实实只引了合计 −0.7179%),份额大小这条没有门,于是又翻了一次。G2 的 `larger_share` 字段正是为这个。

**一处新的表面瑕疵**:[T11](../../dev_note/portfolio-demo/agent-battery/T11-double-count-trap.md) 的散文里出现 `[calc_overlapping_quantities?]`——一个长得像 id 的字符串。`citations` 数组是干净的(两个真实 fact),所以门没有被绕过;但用户会看到两种括号。记下,未修。

## 4. 判断力测试的门槛动了,分类在测试里

`test_eval_faithfulness_live` 的 chat 门槛 1 → **9**,八条新增全是一类:`not_quotable_individually`,同一个 run 上的因子系数被单独引用(market 七次,growth 与 small_cap 各一次)。**那批回答正是这个检查器的取样来源**——豁免催生规则的语料会让棘轮变装饰。测试同时断言**种类**,所以第九条不同类的拒绝没法躲在八条同类填满的计数里。

## 5. 本批记下的

- **一次通过不是验收。** `--repeat` 是本批唯一一个改变结论的工具:同一问句 22 次答对 12,而任何单次运行都会把其中一个判决记成事实。
- **切一块代码时,数它中间夹着什么**(V10 §7 的那条,又中一次):`services/fundamental_panel_service.py` 无人 import 且引用 V10 已删的 `DEBT_RECIPES`,调用即崩;`analytics/fundamental_panel.py` 同为孤儿。
- **门的副作用是双向的。** 拒绝带出路之后,余额表路径**多出**了 `calculate` 调用——门第一次把模型推向计算而不是推向措辞。
- **测试抓到我自己的两处**:`scale` 丢掉 mixed basis(`_resolve` 读回比率时把它渲染成 "unspecified");新的 absence statement 把 GOOGL 面板推回 6557 字节。两条都是先红后修。
- **一行改不了 `uncovered`。** 看上去是 `for m in members` → `for m in present`,但那会让 JPM 的信号永远为空——那个字段本来就服务两个不同的事实,得拆成两个。

## 6. 待办(未做,已登记)

- **G2 投影契约**(boss 拍板记为待办):`describe_issuer` 删 `definition` / 拆 `computable` / 加 `superseded_by`;`get_balance_sheet` 加 `contains`;`_resolve_company` 删 `id`;`evaluate_formula` 加 `window_bound_by`;单日归因加 `scope`;`reconcile_move` 加 `larger_share`
- **G6 范围绑定** 与 **G5 路由**:先做换模型实验(改 settings 一行,跑 24 次重复),用结果决定 skill 层要多重
- **LLY capex 映射**:`test_v11_tag_drift_live` 已把它记为唯一的 `unmapped_candidate`;补映射前要像包含边那样先对语料验证
