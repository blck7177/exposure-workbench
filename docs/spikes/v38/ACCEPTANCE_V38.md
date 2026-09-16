# V38 执行记录与验收（2026-09-16）

> 计划：`docs/IMPLEMENTATION_PLAN_V38.md`（12 条）。起点 HEAD `0986dca`，离线 2603 passed。
> 提交：`02180ef`（计划与工具层分析）→ `aa78c83`（Phase A）→ `855f4f6`（Phase B）→ `297a436`（Phase C）→ 本记录。均未 push。
> 离线：2603 → **2643 passed** / 11 skipped / 314 deselected。
> 未跑 D 轮：它等 A-R1 崩溃修复（本计划不含）和模型拍板；执行脚本 `tools/phase_d.sh` 已备好，比 C 轮多一步 v5 remap。

## 0. 结论

12 条全部落地。验收用两种不花额度的办法。

**离线重放**：把 C 轮 212 次 `run` 记录下的事实和程序，喂给现在的适配器、digest 和最终截断，读入上限按当时每次 completion 的调用数均分。脚本是 `tools/replay_v38.py`，输出见 `REPLAY_V38.txt`。

| 量 | C 轮 mini / sol | V38 mini / sol |
|---|---|---|
| 拒绝没到分析师眼前 | 30 / 52 | **0 / 0** |
| 从未显示、却被当作显示过而吞掉 | 343 / 789 | **0 / 0** |
| 全空结果 | 4 / 17 | **0 / 0** |
| 只剩一条扣下提示的结果 | 4 / 8 | **0 / 0** |
| 点名的数被扣、未点名的却显示 | 12 / 26 | **0 / 0**（未点名的节点只报条数） |
| 点名节点有数没显示 | 115 / 274，多数没说是哪个节点 | 32 / 82，**全部**出在点名内容本身超过读入上限的 run 里（mini 11 次、sol 19 次），都按节点名告知 |
| 类型拒绝（用新规则重查当时的程序） | 13 / 12 | 9 / 10，剩下的**全是真错** |
| 「net beta」措辞误报（用当时账本重查 brief） | 20 / 0 | **0 / 0**（`RECHECK_NET_BETA_V38.txt`） |

**fixture live**：在 `exposure_battery_v38` 上跑，12/12 通过（`LIVE_CHECKS_V38.txt`）。这个库从 D 轮将用的 9/13 快照还原，补了两个 v36 迁移，并按 v5 映射 remap；每个程序都回滚。

| 检查 | C 轮读到的 | V38 |
|---|---|---|
| S1 AAPL 2023-09-30 季度应收天数 | 120.34 | **30.00**（年度仍为 28.10） |
| S2 MSFT 五个财年末覆盖率（`at=`） | 五次都是 2026-03-31 的 55.65× | 31.31 / 41.58 / 46.38 / 37.72 / 52.84，逐一等于年度序列点，`as_of` 等于 `at` |
| S2 JPM ROE `at=2023-12-31` | 0.1796（2026 年的利润除以 2023 年的权益） | **0.1511**，等于年度点 |
| S2 不在期末附近的日期 | 返回最新一期 | 拒绝：「no reported period ends at or within 20 days of 2021-08-15」 |
| S3 XOM 2025-12-31 总债务 | $9.30B（只含短端） | **$43.54B**；`made_of` 写明 `long_term_debt_and_leases_noncurrent (for long_term_debt_noncurrent) + debt_current_total` |
| S3 XOM `fcf_to_debt` FY2021–25 | 843.1%、9209.8%、817.8%、619.9%、254.0% | 75.6%、141.7%、80.5%、73.6%、**54.2%** |
| S3 XOM `debt_to_ebitda` FY2021–25 | 0.08、0.01、0.06、0.07、0.14× | 0.91、0.41、0.57、0.58、**0.65×** |
| S4 `pick` 与表对 `net_beta.equity_down` 的身份 | 主体 `equity_down` / 主体 calc id | 都是（`portfolio.integration.net_beta.equity_down`, `run_e2945c5ebd5a`） |
| S5 因子合计 | 语言页没有这个键 | `portfolio.reconcile.sum_of_factor_contributions` = −0.00471605；与 `pick(factor_attributions.sum_of_contributions)` 相同 |
| T3f 共线拒绝 | 句子停在「their sum, X, is」 | 给出取法 `pick(of=$<the run>, key='factor_attributions.sum_of_contributions')` |
| L2 sol Q13 seq13 的 `book.buy` | 假类型错 | 通过类型检查，碰到真正的数据拒绝 `no_sector` |
| T1 + T2 同一程序的显示 | 两个点名的数被扣 | 显示两个点名的净 beta（主体分别是最新与上一期的 run），两张表各记 48 条不显示；买入被拒的原因显示出来 |

## 1. 各条的实际形状，以及与计划不同的地方

- **L1**：按计划实现。回放清掉 mini 4 次、sol 2 次类型拒绝。计划估 mini 能清 5 次，但 Q07 seq13 展开后暴露出一个被藏住的真错（对标量用 `latest`），现在如实报出。
- **L2**：按计划实现。另外，占位值改为落在 schema 的界内和枚举里：`weight` 两端开区间，原来的占位 1 本身会被拒；`months` 是枚举，原来的占位 1 不在枚举里。
- **S4**：按计划实现，并多做一步：calc 行表格的主体改取该行的 base，也就是分析或对账所读的那个 run，这样两个门给出的身份完全相同。分析类事实的主体因此从 calc id 变成 run id；run 节点在 `nodes` 里带着自己的 id。
- **S5**：按计划实现。守卫测试先红，只揪出 reconcile 这一处。
- **T3d / T3e / T3f**：按计划实现。
  - 两个门共用 `arg_validation.problems_text` 和 `schema_hint`。
  - 类型报告的边界文字上限提到 1500 字。
  - T3f 保留了合计的数值，因为 v1 的数字核验靠它说明「该引哪个数」。
- **T1**：按计划实现，另加两点。
  - registry 在一个数都不显示时，照样记录全部事实：`return` 只点名 run 节点的程序就会这样。
  - 表达式展开出来的中间节点，没被点名就不显示；digest 截尾提示也改成按节点计数。
- **T2**：按计划实现。写测试时发现 `dumps_capped` 的一处边界缺陷，一并修了：
  - 清空最大的非保留容器后仍放不下时，原来会整段按字节截，所有容器全丢；
  - 现在先清空全部非保留容器，再从保留容器的尾部裁；
  - 长列表的丢弃声明写成区间，避免声明本身就放不下。
- **T3a**：`made_of` 从公式结果一路带出。
  - 覆盖公式结果本身、嵌套公式、序列（取最新一个有组成信息的点，并写明日期 `at`），以及事实的 params、digest、兜底 `shown`。
  - **没做**：方法对多个主体求值得到的向量，条目上不带各自的 `made_of`。
- **T3b / T3c**：按计划实现。表达式内联挑出的日期（被展开的字面量节点）也会显示。
- **T4**：按计划实现，但 `repeated` 改成按节点分组，每组最多列 12 个 `shown_as`。逐条列出时，一张 300 行的表重取一次就要占满读入。
  - V37/T5 的「一次 completion 共享读入上限」测试原来能过，是因为第二、三个结果被 T4 的缺陷吞成了空的。
  - 该测试的预算改到每个结果 4000 字下限不起作用的位置，测试本意不变。
- **K5**：三处文字改为与 `_RISK_SENSE` 一致，测试把文字和代码钉在一起。`WORDING.md` 新增 B5 一节。
- **S1**：按计划实现（12→365、9→274、6→182、3→91）。公式表达式写「× days in the window」，导入期校验随之改。
- **S2（与计划不同）**：窗口改为**以 `at` 为终点**，按 20 天容差对齐到最近的报告期边界；找不到对应边界就拒绝。计划原写的是「不晚于 `at` 的最近一个窗口」，没有采用，原因有二：
  - 余额一侧按 `at` 当日取数，流量窗口也应以同一天为终点；
  - 「不晚于 `at` 的最近一个窗口」在某个标签停报之后，会把旧标签的最后一年当成当年静默返回。
- **S3（与计划不同）**：替代成员的使用条件改为「正主**当日**未报、替代当日有报」，不再限于「从未申报」。
  - 原因：KO 在 2024 年改报租赁含在内的标签，GOOGL 在 2023 年从该标签改走；按原条件，这两家的洞补不上。
  - 证据：三个库里，两对标签同日并存分别 4 次和 6 次，替代值从不更窄，其中 3 次和 5 次在 0.5% 内相等。live 测试会重新数这几个数。
  - 其余配套：
    - 语义表和显示名补上两个新 metric；
    - `remap_concepts.py` 加 `--db`；
    - 新增仪器 `scripts/unmapped_family_concepts.py`，以及对应的 live 守卫。
  - 仪器里已知未读的债务标签是 5 条，每条写了理由：KO `OtherShortTermBorrowings`、LLY `NotesPayable`、`OtherNotesPayable`、`OtherLongTermDebt`、XOM `ShortTermBankLoansAndNotesPayable`。计划里写的「三条」不准：JPM 那条和 KO、LLY 的授信额度都不是债务余额，已按名称规则排除。
- **计划文字的更正**：「net beta 误报 ×27」不对。实际是 mini 6 份 brief 里共 20 条，sol 为 0。归因文档 §5 里「sol 10 次」是所有措辞误报的合计，不是这一类。

## 2. 没做、没跑、待定

- **D 轮未跑**：前置条件是 A-R1 修复（topic next ①）、模型拍板、额度探针。`tools/phase_d.sh` 已按 C 轮流程备好，多一步 v5 remap 和未读标签清单。
  - 注意：D 轮会覆盖 `exposure_battery`，也就是 C 轮 mini 的记录库，本记录的重放要读它。备份在 `backups/battery/battery-after-V37C-2026-09-16.sql.gz`，以后重放前先把备份还原到别的库。
- **措辞待过目**：`WORDING.md` 里的 B4（digest 读法新增 6 句）、A3（`shown` 一句）、B5（净 beta 符号三处）。
- **计划 §5 待拍板**：
  1. 原语 `fundamentals(at=)` 对流量仍然拒绝，没有改；
  2. 含租赁的长期债务按推荐做法作为替代成员实现（未入家族），改起来只动 `SUBSTITUTES`；
  3. 季度的存量除以流量比率仍不年化；
  4. 字面量按「显示 + 引用规则」实现。
- **跑了与没跑的 live 测试**：
  - 第一批 25 条通过，其中 `test_calc_ledger_live` 和 `test_v9_typed_calculator_live` 会向生产库 `exposure_workbench` 提交 calc 行，运行前没有先查。结果是 23:02 UTC 写入了 20 行 `calc_ledger`（`invoked_by` 为 agent / test，都是只追加的计算审计行，不涉及组合、运行和用户数据），没有删除，是否清理待定。
  - 之后只跑连金标准快照或会回滚的测试：18 条通过，1 条失败。失败的是 `test_symmetry` 调用的 `definitions._describe_run`，这个函数在 V23（dacef3d）就已删除，与 V38 无关。
  - 其余会往生产库提交的 panel / fundamentals 类 live 测试没有跑。
- **生产库未 remap**：随部署放行一起跑（`remap_concepts.py --apply`，先备份）。
- **已知剩余**：
  - 向量条目的 `made_of`；
  - KO 的 `short_term_borrowings` 在 2022 年以后接续到哪个标签；
  - 计划 §7 所列各项。

## 3. 复现

```bash
SP=docs/spikes/v38/tools
.venv/bin/python $SP/replay_v38.py exposure_battery docs/spikes/v37/V37C.json mini /tmp/r38
.venv/bin/python $SP/replay_v38.py exposure_battery_sol docs/spikes/v37/V37C_sol.json sol /tmp/r38
.venv/bin/python $SP/recheck_net_beta.py exposure_battery docs/spikes/v37/V37C.json mini
.venv/bin/python $SP/live_checks.py --db exposure_battery_v38      # 9/13 快照 + v36 迁移 + remap --apply --db
.venv/bin/python scripts/unmapped_family_concepts.py --db exposure_battery_v38
```
