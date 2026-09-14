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

---

# 续：复审后的减法，E 轮与 F 轮（同日）

boss 复审两批修复后判定：十处规则补丁、三处 fallback，都堆在两个本该删掉的机制上。
执行的是五件减法（提交 `525030d`），E 轮实测后补一次域的修正（`79e9ccc`），F 轮实测。

## 7. 五轮对照

| | B 旧出口 | C | D | E 五件减法 | F 域修正 |
|---|---|---|---|---|---|
| 出答案 / 20 | 19 | 4 | 5 | 2 | 3 |
| 通过的答案里读者可见假陈述 | ≥12 | 0 | 2 | 0 | 0 |
| 答案被拒次数 | 42 | 35 | 30 | 37 | 35 |
| 重放后的问题总数 | — | 421 | 163 | 273 | **163** |
| `run` 的 type_errors | 0 | 25 | 22 | 7 | **2** |
| program 作者 completion | 0 | 62 | 74 | 19 | **9** |
| prompt tokens 中位 | 20.4k | 16.8k | 13.4k | 20.4k | 19.5k |

减法四（请求语法说得出派生、未知名字只丢自己）的效果是确定的：**类型错误 25→2，
作者调用 74→9**，构造器现在编得出来的不再掉给 LLM 去写。出答案数仍然只有 3/20。

## 8. E 轮告诉我的：两处减过头

都不是去掉 fallback，是把域砍掉了大半，已在 `79e9ccc` 改回，作为一个域而不是一串回退：

- **引文的来源不止 passage。** desk 自己的边界原话（absence fact 的 text）与用户的问题，
  都是本轮真实存在、可逐字核对的文字。63 次 `unverified_quote` 里约 50 次是这两类。
- **数字后标 passage 的 id，pinned 分支从不查 passage。** Q19 把 filing 里的分部收入
  逐个标上出处，25 次全被判 `mark_mismatch`。

## 9. F 轮剩下的 163 个问题，按谁的责任

| 类别 | 数量 | 机制 |
|---|---|---|
| 模型自己的错 | 56 | 账本没有的数字 27、散文里写裸 id 23（Q10 一次写了 22 个）、方向说反 6 |
| **门比证据更严** | 54 | `superlative_without_rank` 12：同一段里已经把被排序的读数全列出来了（Q08「MSFT capex intensity 最高 22.9%。Alphabet 22.7%，Amazon 18.4%」）；`change_conflict` 20：句子里只有一个 "from"（「AAPL 距 52 周高点 3.9%」）就触发变化检查；`ambiguous_figure` 22：同主体同 measure 只差日期的两个读数，句子对两者都成立 |
| 引文与标记机制 | 30 | `unverified_quote` 20、`mark_mismatch` 10 |
| tier / measure | 13 | Q11 同值的不同检查项被挑错，tier 挂到别的检查上（未查） |
| tool | 10 | `read_filings` 的 `not_indexed` 8、`section_not_found` 3、`search_web` 的 `company_not_found` 1 |

## 10. 工作树里未提交的第六件减法（**未验证，一个用例冲突**）

同一条原则的第六次应用，改 `services/answer_check.py` 一个文件（+54/−5），**未提交**：

1. 最高级：desk 算出的 rank 之外，**本段里同一 measure 的多个读数**也算依据 —— 被称作
   极值的那个必须真的是极值。事实判，不是词判。
2. 变化：一次变化要么是 `from … to …`，要么有升降动词；单独一个介词不算。
3. 只差日期的歧义：取最新的，其余作为别名跟着，页面照样给读者选择器。

**冲突点（这是要拍板的，不是 bug）**：`test_q08_a_superlative_on_an_unranked_figure_is_refused_and_on_a_ranked_one_passes`
断言「AAPL had the strongest month at 8.76%, above AMZN at -5.83%.」必须被拒，因为没有
rank 节点。第 1 条让它通过 —— 两个读数就在同一句里，AAPL 确实是较大的那个。
**门要的是「排序由 desk 算过」还是「排序对读者可验证」，这两者不能同时成立。**
离线套件在这一处之外全绿（2405 通过 / 1 失败）。未跑 G 轮。

## 11. 补充待拍板（接 §5）

6. 上面那条：最高级的依据是「desk 算过」还是「读者可验证」。
7. 两次机会是否够：F 轮 35 次拒绝里 34 次是「第二次也没过」，每次列 1–23 个问题。
8. B 轮 19/20 出答案但 ≥12 个含假陈述，C–F 轮 2–5 出答案、0 假陈述。**当前的门把
   正确率换成了可用率**，这个兑换比例是产品决定，不是技术决定。

---

# 续二：V34 四条不变量，G 轮（同日）

提交 `8b73c58`。离线 2415、live 19 全绿；G 轮仪器同前（9/13 快照还原、:8105 face、gpt-5.4-mini、并发 5）。

## 12. 六轮对照

| | B 旧出口 | C | D | E | F | G V34 |
|---|---|---|---|---|---|---|
| 出答案 / 20 | 19 | 4 | 5 | 2 | 3 | **4** |
| 通过的答案里假陈述 | ≥12 | 0 | 2 | 0 | 0 | 0 |
| 答案被拒次数 | 42 | 35 | 30 | 37 | 35 | **34** |
| 重放后问题总数 | — | 421 | 163 | 273 | 163 | **153** |
| `run` type_errors | 0 | 25 | 22 | 7 | 2 | 3 |
| program 作者 completion | 0 | 62 | 74 | 19 | 9 | 9 |
| prompt 中位 | 20.4k | 16.8k | 13.4k | 20.4k | 19.5k | 16.6k |

出答案的四题：Q06、Q12、Q16、Q17。

## 13. 四条不变量各自打中没有

| 理由 | F | G | 判断 |
|---|---|---|---|
| `mark_mismatch` | 10 | **0** | A + 删掉 `[f_…]`：命中，整类消失 |
| `id_in_prose` | 23 | **0** | 同上：模型不再需要写 id，也就不写了 |
| `change_conflict` | 20 | **6** | 「变化要 from…to 或升降动词」命中 |
| `superlative_without_rank` | 12 | **8** | B 部分命中；剩下的 8 处所排的读数不来自同一个向量（Q03 把三个独立标量说成次序） |
| `measure_mismatch` | 6 | 3 | — |
| `unsourced_figure` | 35 | 32 | 模型自己的错，设计内 |
| `unverified_quote` | 20 | 21 | 未动，机制见下 §14.3 |
| **`ambiguous_figure`** | 22 | **51** | **回退**，机制见 §14.1、§14.2 |
| **`tier_mismatch`** | 7 | **24** | **回退**，机制见 §14.2 |

## 14. 三处机制（只记录，未修改）

### 14.1 代词跨句：区分维度在上一句（Q11，4 次）

分析师原文：

> MSFT is the closest issuer concentration to its warning tier. On 2026-09-10 **its** current value was 16.0%, against a warning level of 15.0% (2026-09-10), so it is already 1.0% over warning.

第二句里没有 "MSFT" 这个词，只有 "its"。收窄是按句子的，于是 `15.0%` 在
`issuer_concentration:AAPL` 与 `:AMZN` 之间成为歧义。**注意分析师照抄了带日期的形态**
——不变量 A 起作用了，但这里区分维度是主体不是日期，A 只在「主体与 measure 都相同、
只差日期」时补日期。A 覆盖了三种碰撞形态里的一种。

### 14.2 列举句：一句里十个主体十个图形（Q15，14 次歧义 + 24 次 tier）

> By position value, the largest holdings are MSFT at $1.72M, AAPL at $1.63M, JPM at $1.59M, LLY at $1.35M, GOOGL at $1.33M, HYG at $786K, …

一句话点了十个主体。按主体收窄无从下手（十个都在句子里）；档位检查把句内每个档位事实
与句内每个读数两两配对，4 个档 × 若干读数 = 24 次 `tier_mismatch`（「LLY 的档位挨着
MSFT 的读数」）。**句子是错的判断单位**，列举句里主体与图形是配对的，不是共存的。

### 14.3 摘要里的边界文字不在引文域里（Q15、Q05、Q02 等，占 21 次里的一部分）

分析师引了 `'derive' is not a name this desk holds`。那是 broker 把构造器跳过的 want
写成的 boundary，只存在于 digest，不是账本上的 absence fact，于是不在 `turn_texts` 里。
§8 把引文的域补成「段落 + absence 原话 + 问题」，漏了「digest 里的边界原话」。

顺带一处契约理解问题：分析师把 `derive` 当成了 `want` 里的一个名字，而它是同级字段。

## 15. 现在的账（接 §11）

- 已提交：`8b73c58`（V34 四条不变量）、`d2fd786`、`79e9ccc`、`525030d` 以及此前四个 Phase 提交，**共 10 个，未 push**。
- 工作树干净（除 `docs/spikes/v32/` 一直未跟踪）。
- fixture face 在 :8105 跑 G 轮代码，`exposure_battery` 是 G 轮 20 个 session。
- 六轮的取证文件齐全：`V33{B,C,D,E,F,G}.json` + `_forensics.txt` + `_answers.txt`。

**待拍板不变**（§5、§11）：门把正确率换可用率的兑换比例；两次机会是否够；无数字的空答是否该过门。新增一条：**A 的覆盖面**——它现在只在「同主体同 measure 差日期」时补区分维度，而 G 轮的两处回退说明碰撞的主要形态是「同值不同主体」，而分析师用代词和列举句写它们。

---

# 续三：V35 图形带指针，H 轮（2026-09-14）

提交 `c651acb`。boss 于 9/14 对 §14 三处机制的方案拍板"开始执行修改"。方案先把工作还给角色，再改代码；三处机制是同一条裂缝的三个侧面：一个数字"是谁的"没有角色拥有——tool 在 digest 里按主体加日期定身份并承诺"这个写法唯一"（`HOW_TO_CITE`、`_SYSTEM` 的 "Never write an id"），账本按随机 id 记且同一读数记六遍（Q11 的 session：读作 15.0% 的 warning_level 事实 80 条，20 个主体日期组，MSFT 与 AAPL 展示为同一个字符串 `15.0% (2026-09-10)`），门按"写出精度下相等的值 + 句内的词"重建身份（`_pin` 三段收窄，"passing when it names none"）。

## 16. 三处边界改动（已提交，`c651acb`）

**1. 账本即展示（tool）。** builder 跳过的 want、整项不可编译、工具的拒绝、预算耗尽——每一条边界都由 broker 铸成 ABSENCE 事实（`Broker._boundary`），随 digest 步记入 `evidence_refs` 与 facts 表；digest 里的 `boundaries[].fact` 就是它的 id。门的引文域改为"账本上所有 text"，不再枚举来源（§8 补过一次仍漏一类）。每个展示值末尾带它的 id：`"value": "16.0% [f_2592baab170e]"`，序列的点同样；"照它显示的写"就是"带指针地写"。不变量 A 保留重复合并，删掉往值里塞日期的那半——G 轮证明要区分的碰撞是"同值不同主体"，日期后缀分不开。

**2. 指向由作者给出，门只核指向与转写（LLM 抄，validation 核）。** 门对每个图形三查：id 在账本上（`not_on_ledger`），该事实在写出精度下持有这个值（`mark_mismatch`，拒绝信里说明它实际持有什么），序列点在多个日期上时句中要有日期（`ambiguous_point`）。裸数字只剩三条出路：事实的身份字段（日期、年份、窗口）、用户问题里的数、引文域里的段落陈述的数；否则 `unpointed_figure`，附它被展示时的 id 列表。删除 `_pin`、`_primary`、`ambiguous_figure`；删除档位与读数的句内两两配对，档位词只对自己指向的档位查种类；关系检查（主体、最高级、变化、方向、档位词、measure 短语）只在指向的图形上跑。渲染剥掉括号、保留链接。指针无条件：F 轮"两个 id 持同一值时才写 [id]"的条件规则让模型持有 validation 的规则（23 次 id_in_prose、10 次 mark_mismatch）；`{cN}` 的失败是手工编号的第二张表，与从展示行抄一个 id 不同类。

**3. 修复是工具（agent 层）。** G 轮 18 次第二机会：1 次走标签协议、4 次逐字重发、13 次整篇重写，"still allowed"的整篇重写是每个模型都走的路。现在判决在身时，回合按构造是工具调用（`tool_choice="required"`，`llm/client.py` 透传）：`repair_answer(replacements=[{tag,text}])` 或 `request_evidence`；判决在身时的散文回复提醒一次，再来一次即 `malformed_repair` 结束回合。删除文本标签解析与整篇重写回落。

**顺带：derive 语法。** 一行可命名、后一行可用该名（`adv20 = price.adv * 0.2`；`days = issuer_exposures.market_value / adv20`），Q11 的 `room = a - b` 不再被当左操作数，Q15 的"20% of ADV"可表达；两个运算符一行的拒绝信说怎么写；工具描述说明 derive 是 want 旁的字段、book 列与逐票方法要在同一 item 里派生。

**测试。** `tests/test_v33_answer_check.py` 全部改写为带指针的句子，新增两条性质：账本持有的裸数字在任何句形下都不被接受；指向的图形通过与否只取决于它的事实，与句中其他词无关。§14.1 与 §14.2 的原句作为用例直接通过。broker 新增"边界是事实"两例；meta agent 新增工具修复、判决在身时整篇回复不被读、修复仍失败即用尽三例；builder 新增命名/串接/两运算符三例；`test_v31_agent_gap` 两个钉住整篇重发行为的用例改为新契约。离线套件全绿。

**仪器。** `scripts/v35_forensics.py`：每个 answer 步在当步账本上重放核对器，问题按理由计数，首次作答单列；`scripts/v35_round_summary.py`：六轮表的口径（出答案、拒绝、type_errors、作者 completion、prompt 中位、第二次作答是否逐字相同）。用它重数 B–G：

| 轮 | 出答案 | 拒绝（meta.gate_refusals） | run type_errors | 作者 completion | requests | prompt 中位 | 第二次作答 |
|---|---|---|---|---|---|---|---|
| B 旧出口 | 19/20 | 7 | 0 | 0 | 0 | 20.3k | — |
| C | 4/20 | 32 | 25 | 62 | 56 | 15.7k | 19 改写 |
| D | 5/20 | 30 | 22 | 74 | 60 | 13.4k | 15 改写 |
| E | 2/20 | 36 | 7 | 19 | 67 | 19.4k | 19 改写 |
| F | 3/20 | 34 | 2 | 9 | 61 | 18.3k | 18 改写 |
| G | 4/20 | 32 | 3 | 9 | 55 | 16.3k | 14 改写 + **4 逐字重发** |

（§12 的"答案被拒次数"是取证文件里 ANSWER rejected 的行数，与此处 meta 计数差 1–2，口径不同；本表之后各轮统一用此脚本。）

## 17. H 轮（`c651acb`，2026-09-14）

仪器同 G：9/13 快照还原的 `exposure_battery`、:8105 face 跑新代码、gpt-5.4-mini、并发 5、`--deny submit_brief`；运行前后树 `895b169f` 未动。文件：`V33H.json`、`V33H_forensics.txt`（当步账本重放）、`V33H_answers.txt`、`V33H_counters.json`、`run_v33H.log`。

| | G V34 | **H V35** |
|---|---|---|
| 出答案 / 20 | 4 | **5**（Q02、Q07、Q12、Q16、Q17） |
| meta 拒绝 | 32 | 30 |
| 重放问题总数 / 首次作答 | 153 / — | **103 / 58** |
| `ambiguous_figure` | 51 | **0** |
| `tier_mismatch` | 24 | **0** |
| `unverified_quote` | 21 | 26 |
| `unsourced_figure` | 32 | 19 |
| 新类 `id_in_prose` / `mark_mismatch`(首错) / `ambiguous_point` / `not_on_ledger` | — | 18 / 7 / 7 / 3 |
| 第二次作答 | 14 改写 + 4 逐字重发 | 17 次全部经 `repair_answer`，1 次未改句（Q15） |
| 通过答案里读者可见假陈述 | 0 / 4 | **4 / 5**（Q02 1、Q16 2、Q17 1；Q07、Q12 干净） |

**命中。** §14.1 的 Q11 原句"its current value was 16.0% [f_…] against a warning level of 15.0% [f_…]"两个图形都过；§14.2 的列举句档位不再报；§14.3：Q07、Q12 逐字引用桌子的边界原话通过。修复工具：Q16 的 0.95→0.96×、Q17 的 27.1%→27.0% 一次修好；再没有整篇重发。`mark_mismatch` 全部是真错：Q03 把自己算的份额指向金额序列 16 处、Q09 用 97 代替 97.36、Q04/Q20 用 26.2% 代替 26.3%（存 0.26250，显示 26.3%）、Q10 37.73 指错事实。

**新露出的，按角色。**
- validation 过严四处，都是同一条"句子/括号语法比作者的自然写法窄"：(1) 引号内的尾标点——分析师写 `"…call describe."`，账本原话无句号，26 次 unverified_quote 里至少 9 次是这一类（Q04、Q18、Q06 的 "not for a financial issuer."）；(2) 括号跟在引文或名词后的引用写法 `“…” [f_passage]`、`Item 7 passage [f_…]` 被判 id_in_prose，首次作答 11 处里 8 处；(3) 序列同值多日期：Q01 一句里把两个日期都写了，句级找日期仍歧义，7 次 ambiguous_point；(4) "above/below" 被当变化动词，"16.0% against a warning level of 15.0% … above warning" 报 change_conflict（Q11 两次）。
- tool 两处未入账文字：digest 超限时 `_fit` 写的 held_back 提示与 `_absorb` 的 held_back 行（Q14、Q15 引用被拒）。一处静默：窗口文字未识别的部分被丢弃，"same 4 quarters a year earlier" 解析成 last 4 quarters，Q02 得到同一序列两次并写下"a year earlier … it was the same sequence"，门无从看见，是本轮四条假陈述之一。derive 带括号 `mv / (adv * 0.2)` 被拒（Q15）。
- tool 身份：book.analysis 事实的 subject 是 calc id，两个 run 的 `net_beta.rates_up` 不算"同主体两日期"，Q16 "net beta to equities up from 0.89% to 0.86%" 标签与方向都错却通过（measure 短语只取最后一段 rates_up，看不见 net_beta）。
- LLM：Q17 "MSFT is further below"比较词错误（-8.41% 不是最远）；Q15 抄丢一位 id（f_facabd3706e）且修复时未改；Q11 仍自己做减法（1.0、4.0）而没用 derive。

## 18. H 轮之后的收口（I 轮前，同日）

H 轮露出的都是 §16 设计没收干净的地方，不是新设计；按角色各归其位后一并改：

- **validation：括号语法放宽到作者的自然写法，判断仍是查表。** 图形与括号之间允许单位词（`4.0 percentage points [f_…]`，然后照常核值——Q11 那句现在是 `mark_mismatch: f_… holds 20.0%`，说得出错在哪）；序列的括号带日期 `[f_…@2025-12-31]`，digest 就这样展示，同值多日期不再靠句子找；跟在引文或名词后的括号是**引用**（`“…” [f_passage]`、`Item 7 passage [f_…]`），只查 id 在账本上，入 refs，渲染剥掉；裸 id 仍是 `id_in_prose`。引号内的尾标点与 digest 里 JSON 转义的换行、千分位逗号都归一化后再比（账本存 passage 时早已去掉逗号，引文却保留，是 V33E 起就存在的 Q19 缺陷）。"above/below/higher/lower" 不再算变化动词，只在同 measure 跨主体比较里定方向。`10-K`、`DEF 14A` 这类表格名不是数字。拒绝信点名：`not_on_ledger`/`mark_mismatch` 列出账本上持有该值的 id，`superlative_without_rank` 列出同一读数带 place 的事实 id（Q11 "largest … 16.0% [f_current]" 现在会被告知 `[f_ranked]`）。
- **tool：digest 里最后两处不入账的文字铸成事实**（`_fit` 的超限提示、`_absorb` 的 held_back），digest 里再没有账本之外的字。**窗口不再静默截取**：`unreadable_window` 把识别不了的词说出来（"same 4 quarters a year earlier" → 边界："has words the desk does not read (same earlier); it reads: …"），Q02 那类"同一序列两次"的假陈述从源头拒绝；`ended/through YYYY-MM-DD` 读作 `at`。**derive 是表达式**：名字、数字、`+ - * /`、括号，每个运算一条 binding，外层带行名，内层不返回（`days = issuer_exposures.market_value / (price.adv * 0.2)`）。
- 未改、记录：book.analysis 事实的 subject 是 calc id（Q16 两个 run 的同一 measure 不算同主体两日期，方向检查失效；measure 短语只取最后一段）；比较级（"further below"）无检查；这两条是事实身份与关系词的设计题，不在本轮。

测试：answer_check +9、broker +2、builder 3 条改写（两运算符一行现在可表达，加窗口与表达式用例）。

## 19. I 轮（`678531b`，树 `9b081a7`，2026-09-14）

仪器同 H。文件：`V33I.json`、`V33I_forensics.txt`、`V33I_answers.txt`、`V33I_counters.json`、`run_v33I.log`。

| | H | **I** |
|---|---|---|
| 出答案 / 20 | 5 | **11**（Q02、Q05、Q06、Q07、Q08、Q09、Q12、Q13、Q14、Q16、Q17） |
| meta 拒绝 | 30 | **18** |
| 重放问题总数 / 首次作答 | 103 / 58 | **68 / 45** |
| `ambiguous_point` | 7 | **0** |
| `id_in_prose` | 18 | 6（全是 Q11 自造的 `[derived from f_a and f_b]`） |
| `unverified_quote` | 26 | **6** |
| `unsourced_figure` | 19 | 5 |
| `mark_mismatch`（重放） | — | 31 / 首次 17，其中 11 次是**指向 passage 的数字**（Q04 "$65,179 [f_passage]"、Q19 九个分部数字），其余是真错 |
| 第二次作答 | 17 经工具 | 16 经工具，3 次未改句 |
| 通过答案里读者可见假陈述 | 4 / 5 | **1 / 11**（Q16） |

**命中。** 单位词括号、引文后引用、尾标点、序列日期括号、above/below 全部按预期消失；Q02 的窗口边界起作用——分析师这次写的是"A year earlier, the same quarters were not returned as an aligned series"；Q07 引用了 digest 的超限提示原话并通过；Q05、Q12、Q14 逐字引用边界。修复工具：Q06 丢符号 3.18%→-3.18%、Q08 29.6%→29.7%、Q16、Q17 各一次修好。

**通过答案里的假陈述与可追溯缺口。** Q16 "Each holding's one-year beta is the same versus SPY and QQQ"：第二次请求要 QQQ，builder 把基准静默默认成 SPY，事实的 params 不带 benchmark，十个数字与 SPY 完全相同——与 Q02 的窗口同类（tool 静默默认），这是本轮唯一一条 tool 造成的假陈述。Q06 "JPM looks a bit less risky than a year ago"：没有一年前的读数，判断句无图形，D 标为 judgement，不是门的失职但读者看不出无依据。Q09 "-227.86" 与 "-75.83 / -67.83 / -71.07" 都是桌子算的 cash_conversion_cycle（季度 3 个月窗口 vs 年度窗口，量级不同），写法忠实、语义可疑，是 skill/tool 的口径问题。Q07 "trailing twelve months" 无法核：`divide(vector(ocf), vector(ni))` 的事实 as_of 为 n/a、无 window，H 轮同题同名同标签的数字不同（AAPL 97.0% vs 114.4%）——派生向量丢了窗口身份。

**没过的九题按原因。** Q04、Q19：指向 passage 的数字被判 mark_mismatch（契约缺一条：passage 里陈述的数字可以指向 passage，查表即可）。Q03 两次：三段轨迹句"went from … to …, then down to …, then back up"被方向检查按前两个图形判反。Q11：derive 编出了 40 条 room 事实，但 digest 超限扣下 163 个图形，模型没看见 room，就自己减出 1.0%/4.0% 并造了 `[derived from …]` 写法——R1 的工作单位问题以另一种形态出现（一次请求 5 列 × 20 行 + 派生）。Q15：引用了 skill 推送文字当"桌子说的"（不在账本，拒绝正确）；Q18：把 quality_flags 的计数写成百分比；Q20：26.2% 代替 26.3% 又一次；Q10：37.73 代替 37.72×，"net debt"短语旁的图形是 commercial_paper；Q01：一句里同时讲 DSO 与持仓权重，measure 短语检查报错。

## 20. J 轮前（validation 两处）

指向 passage 的数字：`resolve_in_passages(tok, [fid])` 查那一段，陈述了就链接到 passage，没陈述就 `mark_mismatch: is a passage and does not state this figure`。变化与方向只在**恰好两个图形**的句子上判：三个以上是轨迹，哪个方向词指哪一段不是门能判的。
