# V33 验收记录：C 轮、D 轮，以及停在哪里（2026-09-13）

> 依据 `docs/IMPLEMENTATION_PLAN_V33.md` Phase 5。仪器：`scripts/battery_fixture.sh`（9/13 快照还原的 `exposure_battery` + :8105 face）、`scripts/conversation_battery.py --fixture --deny submit_brief`、gpt-5.4-mini、并发 5。
> 取证方法与 V33 B 轮一致：每个被拒答案在**当步账本**上重放核对器，每个被拒数字对账本上的全部数值叶子分类（标量值 / 序列点 / 不在账本）。文件：`V33{C,D}.json`、`V33{C,D}_forensics.txt`、`V33{C,D}_answers.txt`、`V33{B,C,D}_counters.json`。
> boss 于 D 轮取证后指示：**停止修改，只记录 + 报告**。本文是那份记录。

## 1. 三轮数字

| | B（旧出口 respond+claims，HEAD 99804d6） | C（分析师+broker+核对器，Phase 0–4 提交态） | D（C + 对 C 的修复） |
|---|---|---|---|
| 出答案 / 门槛收场 | 19 / 1 | 4 / 16 | 5 / 15 |
| 通过答案里读者可见假陈述 | ≥12/19（B 轮 FINDINGS） | 0/4（4 个里 2 个是"desk 没给证据"的空答） | **2/5**（Q18、Q19 渲染层，见 §3.3）；另 2 个空答 |
| 答案被拒次数（respond 或 answer 步） | 42 / 61 次 respond | 35 / 39 次 answer | 30 / 35 次 answer |
| 每轮 request 数（均值） | – | 2.8 | 3.0 |
| program 作者 completion / 其中 type_errors | – | 62 / 25 | 74 / 22 |
| prompt tokens 中位 / p90 | 84k / 295k | 55.9k / 70.7k | 51.6k / 93.2k |
| 每题用时中位 | 17.0s | 20.9s | 23.7s |

结论先说：**新架构在 C/D 两轮都没有通过验收**（出答案数远低于 B），但失败的形状完全不同——B 的失败是"通过了但错"，C/D 的失败是"对了但过不了门 + tool 侧断供"。C 轮 78% 的拒绝是核对器的一个缺口（序列点），D 轮 86% 是它的下一个缺口（同一序列两个 id 视为歧义）；两处都已在代码里修，D 之后那一处**未经实测验证**。

## 2. C 轮：机制与修法（已实施，处于 staged 未提交）

421 个被拒数字的归属：**329 个是账本上序列的点**（digest 把序列显示成 [日期, 值] 点，分析师照写，核对器只对标量 value 解析；分析师按指示把序列 id 写在数字后面时报 `mark_mismatch`）；**50 个是账本上的标量**（ADV 显示为 "$13.27B/day"，分析师写 "$13.27B"，`resolve_number` 的 MONEY 缩放路径不含 MONEY_PER_DAY）；**41 个不在账本**（其中大半是分析师在散文里自己做减法：Q11 的 1.0%/4.0%/$0.43M）。

| 角色 | 问题（C 轮实例） | 修法 |
|---|---|---|
| validation | 序列点不可解析（Q01 32 处、Q09 96 处…） | `Ledger.resolve_point`；`[f_series]` 标在点后合法；渲染用 `fill_point`（点在自己日期上） |
| validation | "/day" 显示格式对不上（Q15 20 处） | `_value_hits` 对 MONEY_PER_DAY 走缩放路径；显示比对去掉 "/day" |
| validation | `unit_conflict` 把"比较"当"变化"（Q15 10 处 "$X against Y%"） | 只在 from→to / 升降词的变化句里报 |
| validation | 引号引 desk 的边界原文被 `unverified_quote`（30 处） | 引文可对 absence fact 文本与问题原文 |
| tool | 作者把方法名写成原语（16/39 个类型问题），修法文案指错门 | `unknown_primitive` 按名字给出 `{fn:'method', name, subject}`；工具名指回 filings:/news: |
| tool | 作者把方法名当 filed 行（Q04 → desk 说"LLY 无 gross_margin filed facts"，分析师原话告知用户） | 静态 `metric_is_a_method`、运行期 `not_a_filed_line`，归 SPELLING 类 |
| tool | `figure(run=$after)` 对 scenario 表报错无路径 | 修法文案指向 `pick(of=$after, key=…)` |
| tool/broker | 一项里混着方法与 `filings:` 整项进作者（Q04） | 按 want 类别拆项，各走各门，结果合并 |
| tool/broker | book 项只给 ticker，编成 `run(portfolio="AMZN")`（Q01） | 构造器读 briefing 的 held_in 找组合 |
| tool/broker | 已就绪的 JPM 还去 `start`（Q12） | prepare 跳过 on-desk / preparing，回 note |
| tool/broker | 构造器成功时 `ask` 被丢（Q11 "room to warning"） | 编译出的 program 只有读取时，把 `ask` 交给作者补派生节点（可拒答） |
| LLM | 散文里做减法；引号引非引文 | 系统提示加两句规则 |
| tool | `at` 在 flow 上被静默丢弃（Phase 1 探针发现） | 拒绝并给窗口写法 |

## 3. D 轮：机制

### 3.1 模型当时看到的（运行代码 = §2 修法）
`ambiguous_figure` 240 次，222 个被拒数字是账本上的序列点——**同一序列被取两次（两个 id、同主体同 measure 同点）**，点消歧按 fact id 分组未把它们当别名（标量路径早有 `_group_key` 别名分组，点路径没有）。这是 §2 序列点修法的直接后果，一轮就暴露。

### 3.2 用当前代码（含别名修法 p09）重放 D 的被拒答案后剩下的
| 理由 | 次数 | 机制 | 角色 |
|---|---|---|---|
| `ambiguous_figure` | 23 | 多为裸小整数（"1"、"5"、"7"）撞上多个 fact | validation（见 3.3 裸整数） |
| `unsourced_figure` | 16（11 个不在账本） | 分析师引用的 filing 数字未加引号、自己算的数 | LLM（设计内拒绝） |
| `superlative_without_rank` | 15 | Q15 请求了 `compare: rank`，rank 节点的 fact 被 `run` 的 fact 上限（`facts.cap`）截掉未上账本 → 最高级找不到 rank fact | **tool**（§6 遗留"held_back 上账本"直接命中） |
| `measure_mismatch` | 15 | `two_word_measures` 同一短语对应多个 measure 互相覆盖；分母短语（"of operating cash flow"）被当作独立图形 | validation |
| `unverified_quote` | 13 | 引 digest 里被截成 "…" 的边界文本、引 briefing 的 methods_not_computable 原因、引问题的改写 | validation/LLM |
| `direction_conflict` 6、`change_conflict` 3、`unit_conflict` 3、`mark_mismatch` 5、`tier_mismatch` 1 | | 待逐条看，未查 | – |

### 3.3 D 轮通过答案里的读者可见错误（新架构第一次放过假陈述）
- **Q18**："1y window return" 渲染成 "**1.07%**y window return"；"over 2026-02-20 to 2026-03-27" 渲染成 "over **2.34% to 2.34%**"。
- **Q19**："1-year relative return" 渲染成 "**$251.89 (2026-09-10)**-year"；"$575B in 2023, $638B in 2024" 渲染成 "$575B in **$717B (2025-12-31)**, …"。

机制（validation/渲染）：① 裸整数 "1" 走了百分比路径匹到 0.0107（`_plausible_pct` 允许整数写法）；② 年份/日期按**身份**匹到 fact（as_of、window、points 的日期）后，`accepted()` 把身份链接也渲染成 fact 的显示值——身份匹配本应保留原文。这两处与 B 轮 Q01 "the chart below" 是同一族：**渲染层用 fact 显示值替换了不是该值的文字**。

### 3.4 tool 侧
- **digest 超容量整项丢失**：`dumps_capped(28k)` 对顶层 `items` 丢整条 item，96 图形的 `book` 项 + 30 图形项就越界；Q11/Q16/Q07 分析师写"证据被截断"作为答案（被接受为无数字空答）。
- **`run` 的 fact 上限**把 rank 节点 fact 截掉（`services/facts.cap`，`FACTS_PER_RESULT`/`FACTS_CHAR_LIMIT`）；V33 分析师根本看不到 facts 块，这个上限现在只在伤害账本完整性。
- **program 作者没有 skill 示例**：Q14 `book.explain_episode` 写了 7 种错法，skill 里就有那段示例 program（分析师 prompt 有、作者没有）。
- 作者把 filed 行写成方法（`method operating_cash_flow`），修法文案没指回 `fundamentals`。
- `read_filings(item="7")` 在最新为 10-Q 的发行人上 `section_not_found` ×6，边界只带原始 detail。
- `book` 默认展开五列（含 warning/breach），叠 `vs prev run` 变 180 图形。

## 4. D 之后已写、**未提交、未实测**的修改（工作树 unstaged）
- p09：序列点按 (主体, measure, 日期) 分组为"读数"（别名），`measure_mismatch` 把序列点算进句内图形。
- p10：裸整数不走百分比路径；身份链接渲染保留原文；`two_word_measures` 短语 → measure 集合、允许作为分母/操作数出现；去掉标记后多余空格；digest 自截（丢最大 figures 列表的尾行并记 `held_back`，再截 passage 文本，绝不丢整项）；作者收到 skill 示例 program；`unknown_method` 对 filed 行指回 fundamentals；`BOOK_DEFAULT` 减为三列。
- 测试：新增 8 个用例，其中 **2 个失败**（`test_an_identity_link_keeps_the_words_as_written`：我写的句子把 HYG 与 AMZN 混在一句触发 `subject_mismatch`，是用例问题；`test_a_bare_integer_is_not_a_percentage`：未查）。离线套件在 p10 前为 2393 通过。
- **未做**：`facts.cap` 上限（rank fact 被截）；E 轮。

## 5. 待拍板
1. §2 的修法（staged）与 §4 的修法（unstaged）是否提交；是否跑 E 轮验证 §3 的修法。
2. `facts.cap` 对 `run` 的上限：V33 下分析师不读 facts 块，上限只截账本——建议按工具放开（§6 "held_back 上账本"提前）。
3. `ask` 路由：现在"编译只读 + 有 ask → 作者补派生"是启发式；是否改成 request 语法里给派生一个字段（`derive: "warning - current"`）。
4. 身份匹配是否还应产生链接（年份/日期匹到 fact 后只作引用不改字），以及裸整数的匹配边界。
5. 分析师把"证据被截断 / desk 没给证据"写成答案被接受（无数字即通过）——门槛该不该要求答案至少引一个 fact 或一个边界 fact。

## 6. 当前状态（2026-09-13 收尾时）
- 分支 `issuer-intelligence`，HEAD `b6937c1`（6 个新提交：Phase 0+1 / 2 / 3 / 4 / 文档+仪器 / §4 文档回写），未 push。
- **staged 未提交**：§2 的全部修法 + 对应测试 + C 轮工件（`V33C*`、`V33B_counters.json`）+ `scripts/battery_counters.py`。原因：提交命令里 `git add` 碰到被 .gitignore 忽略的 `run_v33C.log` 而中断，之后的 `git commit` 未执行。
- **unstaged**：§4 的修法与测试。**untracked**：`V33D*` 四个文件、`docs/spikes/v32/`。
- fixture face 仍在 :8105 运行，加载的是 D 轮代码（§2 修法，不含 §4）；`exposure_battery` 里是 D 轮 20 个 session（未还原）。
- 中间提交逐个单独跑离线套件均绿（2330/2349/2370/2375）；HEAD 态 2375；含 §2 修法 2392；含 §4 修法 2393 + 2 个新用例失败。
