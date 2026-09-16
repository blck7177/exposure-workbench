# V37 验收记录：C 轮 20 题（gpt-5.4-mini），同题同码 gpt-5.6-sol 对照（2026-09-16）

> **被测的**：`docs/IMPLEMENTATION_PLAN_V37.md` 的 Phase A–E（25 项），HEAD `b79354f`，树 `3f11872`，离线 2603 passed。
> **过目门**：`docs/spikes/v36/WORDING.md` 仍是「未过目」。本轮按用户 9/16 的指示（"push然后跑 Phase F"）跑的是草稿措辞，run log 已写明。
> **条件（与 A、B 轮相同）**：`scripts/battery_fixture.sh restore backups/battery/battery-2026-09-13.sql.gz` → 补跑 `v36_actor.sql`、`v36_analyst_reports.sql` → `serve`（日志 `/mcp/meta serving 4 tools`）→
> `conversation_battery.py docs/spikes/v33/questions_v33.json … --fixture --concurrency 5 --deny submit_brief`，`BATTERY_OWNER_ID=user_3IDBMeAxLTbecvGorzwV7FCeroR`。
> **sol 对照（用户 9/16 指示："并行用 5.6 sol再跑一次20题，对比和5.4 mini的结果"）**：同码、同题、同快照、同并发、同 deny；独立库 `exposure_battery_sol` 与独立面 `:8106`，C 轮的库原样留着供取证。
> 换模型不改树：`tools/battery_with_model.py` 在导入 battery 之后设 `OPENAI_MODEL`（battery 以 `override=True` 读 `.env`，事先设的环境变量会被覆盖）。
> gpt-5.6-sol 在 `/v1/chat/completions` 上带函数工具时只接受 `reasoning_effort="none"`（否则 400）；探针实测 gpt-5.4-mini 在同一路径上本来就是 0 推理 token，所以两边条件对等。319 次 completion 全部由 `gpt-5.6-sol` 应答（run log 末尾）。
>
> **实测期冻结代码**：两轮开跑前、跑完后 HEAD 与树哈希都是 `b79354f` / `3f11872`，`git status --porcelain --untracked-files=no` 为空，`find src tests scripts -newermt <HEAD 提交时间>` 无输出。遇到的问题只记录，没有改一行代码。
> **第一次尝试中止**：13:44 的 C 轮 20 题在 2–7 秒内全部以 `ExceptionGroup` 失败，根因是 OpenAI 账户余额为零（429 `credit_balance_exhausted`），经过写在 `V37C_run.log`，失败轮文件留作 `V37C_attempt1_no_credits.json`。充值后 14:07 重跑。还原前 fixture 整库备份在 `backups/battery/battery-after-V36B-2026-09-16.sql.gz`，并载入 `exposure_battery_v36b`，用于 B 轮的逐步对照。
>
> **文件**：`V37C*`（mini）与 `V37C_sol*`（sol）各一套：`.json` 轮次、`_forensics.txt` 沟通表与当步账本重放、`_schema.md` 每种载体的真实载荷、`_counters.txt/json`、`_answers.txt`、`_audit.txt`（通过的答案带括号原文，与引用的每条事实并排；序列带点数、点距、起止日）、`_run.log`。
> `tools/` 是本轮用到、此前没进仓库的脚本：A/B 轮 answers/audit 的生成脚本从未提交，`v37c_audit.py` 是重写的，在 B 轮上复现了已提交的 `V36B_answers.txt`，也标出了 B 轮 Q11 那条「在账本、不在事实表」的引用；`v37c_lines.py` 算 V37 §4 的验收线，在 B 轮上复现了计划里的 15/20、1/15、76/142、1/23、28/100、portfolio 类 11、兜底类 4；`answers_of.py` 打出一个 session 每次受门文字的全文与逐条问题；shell 脚本里的 `SP` 指向当时的 session scratchpad。

## 0. 一眼看完

| | B（V36.1） | **C（V37，mini）** | **C（V37，sol）** |
|---|---|---|---|
| 出答案 / 20 | 15 | **13** | **18** |
| 门槛收场 / 轮内崩溃 | 5 / 0 | 6 / **1** | 2 / 0 |
| 通过答案里的假陈述 条 / 题 | 12 / 10（见 §5.3 更正） | **10 / 5** | **5 / 3** |
| 其中「事实本身有问题」 | — | 1 | 2 |

**mini 这一轮没有过线。**出答案从 15 降到 13，假陈述条数基本没动（12→10），而题数从 10 降到 5，错误集中到了少数几题。
七道没出答案的题里，**五道的首要死因是门的误报**（Q02、Q07、Q10、Q17、Q18），一道是误报加真错（Q06），一道是 **V37/A2 在修复分支上的回归，让本轮直接崩溃**（Q13）。
V37 瞄准的那几类大多成立了：兜底事实、抽屉、推断边、portfolio 错类 id、date_expected、`[rep_…]` 都归零；B 轮的周期词假陈述有三条在 C 轮消失；`book_market_risk` 的 run 干净率从 1/23 升到 7/10。
没成立的是 V1（最高级），它既误拒了 Q07，又漏掉了 Q11、Q15 的排序错；另外新规则与老规则在 V37 更丰富的程序上**长出了一批误报**（§4）。

**同一套代码换 sol：出答案 18，假陈述减半。**mini 答错的 Q11、Q15、Q16 sol 都答对了，三轮都没过的 Q07 第一次通过。
代价是耗时约 3 倍、token 约 1.3 倍，而且 sol 写 Markdown，答案视图不解析，读者会看到原样的 `##`、`**`、`|---|`（§7）。
sol 的两道未答题也都死于门的误报。**两个模型面对的是同一个门**：误报在 mini 上杀了 5 题，在 sol 上杀了 2 题。

## 1. 数字

| | J（V35） | A（V36） | B（V36.1） | C mini | C sol |
|---|---|---|---|---|---|
| 出答案 / 20 | 9 | 14 | 15 | 13 | 18 |
| 假陈述 条 / 题 | 3 / 3 | 8 / 5（同口径 ≥9 / 6） | 12 / 10 | 10 / 5 | 5 / 3 |
| 门拒绝（answer） | 22 | 16 | 15 | 18 ¹ | 10 |
| 主分析师 completion 合计 | — | 59 | 60 | 63 | 65 |
| 域分析师 completion 合计 | — | 220 | 224 | 191 | 254 |
| 主分析师 prompt 峰值中位（`count_prompt`） | 16.9k | 8.2k | 8.3k | 8.9k | 10.0k |
| 域分析师 prompt 峰值中位（provider） | — | — | 14.0k | 15.0k | 14.5k |
| 派单（delegate 步） | — | 26 | 33 | 28 | 50 |
| 交接覆盖 asked / done / not_done / refused | — | 156/111/28/30 | 142/76/48/18 | 135/72/41/22 ¹ | 154/83/51/11 |
| done / asked | — | 0.71 | 0.54 | 0.53 | 0.54 |
| submit / 被退回 | — | 67/51 | 67/48 | 60/47 | 100/61 |
| 报告 verified / refused | — | 21/13 | 19/15 | 13/20 | 39/18 |
| run / 其中 type_errors | — | 79/10 | 100/28 | 69/13 | 168/11 |
| 答案里的图形数中位 | — | — | 2.5 | 1.0 | 10.0 |
| completion / prompt tok / completion tok（全轮） | — | — | 284 / 2.94M / 113k | 254 / 2.85M / 116k | 319 / 3.79M / 171k |
| 每题耗时 中位 / 全轮合计 | — | — | 41.8s / 901s | 39.5s / 958s | 129.1s / 2918s |

¹ Q13 崩在轮内，轮次文件里它的 meta 与步骤为空，基于轮次文件的计数（覆盖、主分析师 prompt 峰值、按域表）不含它的两次派单（8 行）；门拒绝、completion、submit、报告、run 这几行从库里读，含 Q13 的 3 次被拒答案与 2 份被拒报告。

**逐题**（A → B → C mini → C sol）：
```
Q01 ✓✓✓✓  Q02 ✓✓✗✓  Q03 ✓✗✓✓  Q04 ✓✓✓✓  Q05 ✗✓✓✗  Q06 ✗✓✗✓  Q07 ✗✗✗✓  Q08 ✓✗✓✓  Q09 ✓✓✓✓  Q10 ✓✗✗✓
Q11 ✓✓✓✓  Q12 ✓✓✓✓  Q13 ✓✓崩✗  Q14 ✗✓✓✓  Q15 ✗✓✓✓  Q16 ✓✓✓✓  Q17 ✗✓✗✓  Q18 ✓✗✗✓  Q19 ✓✓✓✓  Q20 ✓✓✓✓
```
mini 相对 B：回来 Q03、Q08，丢 Q02、Q06、Q13、Q17。sol：Q07 是 A、B、C 三轮里第一次通过。

## 2. V37 §4 的验收线

| 线 | B | C 目标 | C mini | C sol |
|---|---|---|---|---|
| 出答案 | 15 | ≥ 15 | **13 ✗** | 18 ✓ |
| 出答案且派单每行都做完 | 1 / 15 | ≥ 5 | 1 / 13 ✗ | 2 / 18 ✗ |
| 通过答案里的假陈述 | 11 / 9（更正后 12 / 10） | ≤ 3，且周期词 / 主体 / 最高级 / rep 四类为 0 | 10 ✗（周期 1、期次 1、排序 3、rep 0） | 5 ✗（四类皆 0） |
| 交接覆盖 done / asked | 0.54 | ≥ 0.65 | 0.53 ✗ | 0.54 ✗ |
| `book_market_risk` run 干净率 | 1 / 23 | ≥ 1 / 2 | 7 / 10 ✓ | 22 / 29 ✓ |
| run type_errors；portfolio 错类 | 28 / 100；11 | ≤ 12 / 100；0 | 13 / 69 ✗；0 ✓ | 11 / 168 ✓；0 ✓ |
| 门拒绝 `not_on_ledger` 中兜底事实类 | 4 | 0 | 0 ✓ | 0 ✓ |
| 交接首因 `date_expected` | 2（计划记 6，口径不同） | 0 | 0 ✓ | 0 ✓ |
| 域分析师 ≤3 token 空回复紧跟 >9k 读入 | 6（计划记 5） | 0 | 4 ✗ | 0 ✓ |
| 一字不差重发计入 attempts / 预算 | Q03、Q18、Q08 | 0 | 不计入 ✓，但第二次重发让 Q13 崩溃 ✗ | 无样本 |
| 沟通表推断边（工具行） | 152 / 162 | 0 | 0 / 137 ✓ | 0 / 226 ✓ |

两处口径说明：`date_expected` 与空回复两行的 B 值用本轮同一脚本重算，与计划正文不同，已并列写出。沟通表里 `read_report` 行仍显示 `~`，那是取证脚本「谁在说话」的推断把主分析师的行当成了推断，边本身是对的，属于仪器的显示问题。

## 3. 按节点沟通读两轮

### 3.1 载体与往返（20 题合计，取证脚本从库里读，含 Q13）

| 边 | 载体 | B | C mini | C sol |
|---|---|---|---|---|
| meta → sub | delegate | 33 | 28 | 50 |
| sub → tools | run | 100 | 69 | 168 |
| sub → tools | read_filings | 33 | 42 | 44 |
| sub → tools | compile | 10 | 7 | 0 |
| sub → worker | search_web | 6 | 13 | 11 |
| sub → worker | start | 13 | 6 | 3 |
| sub → ledger | boundaries | 48 | 53 | 63 |
| sub → check | submit | 67 | 60 | 100 |
| sub → store | report | 34 | 33 | 57 |
| meta → store | read_report | 4 | 7 | 3 |
| meta → gate | answer | 30 | 31（其中原样重发 2） | 28 |
| 宣布了但没记步的域分析师调用 ² | — | 10 | 24 | 11 |

² 一次 completion 宣布的工具调用数，减去其后记下的调用步数。V37/A2 之后，原样重发的 run 与 submit 在本地直接回原结果，不经 MCP，也不记步；预算用尽的调用、同主体的第二次 start、不合形的 submit 同样不记步。所以这一行是「重发 + 被本地拒绝的调用」的上界，**沟通表的 rep 列看不见域分析师的重发**，这是 I1 的一个缺口。

**两个模型的沟通形状不同。**sol 派单多（每题 2.5 次，mini 1.2 次），会把一个域派两次，run 是 mini 的 2.4 倍；mini 少派、少跑，被退回的比例更高（78% 对 61%）。
两轮的每题主分析师 completion 中位都是 3，差别全在域分析师这一层。

### 3.2 E10 的载荷

两轮的 `V37C*_schema.md` 里，submit 载荷都带 `caveats`（各 14 处），主分析师确实开始把 caveat 写在数字旁边（§6 A1）。`shown` 只在兜底时出现，本轮 mini 有两次兜底（Q09、Q19），Q09 的答案正是用 `shown` 里的图形写的。

### 3.3 重放里的问题（每个受门文字在当步账本上重放）

| 问题 | B（V36.1 代码） | C mini（V37） | C sol（V37） |
|---|---|---|---|
| unsourced_figure | 38 | 44 | 26 |
| mark_mismatch | 34 | 26 | 33 |
| unpointed_figure | 1 | 30 | 3 |
| tier_mismatch | 4 | 20 | 0 |
| measure_mismatch | 3 | 17 | 10 |
| superlative_without_rank | 22 | 13 | 8 |
| subject_mismatch | 1 | 5 | 13 |
| period_mismatch | 0 | 5 | 2 |
| change_conflict / direction_conflict | 1 / 1 | 5 / 0 | 6 / 6 |
| not_on_ledger | 18 | 1 | 0 |
| date_expected | 4 | 1 | 0 |

`not_on_ledger` 从 18 到 1，是 T1 的直接效果。`measure_mismatch` 从 3 涨到 17：其中 8 次是「net beta」、4 次「gross exposure」、2 次「pretax income」、2 次「accounts receivable」、1 次「factor contrib」，逐条看全是误报（§4 V-FP7）。`unpointed_figure` 的 30 次里 26 次出在 mini Q11 一题的分析师反复不带括号写数。

### 3.4 按域（C mini / C sol，节选）

| 域 | 派单 | asked / done | completion | run / 干净 / type_errors |
|---|---|---|---|---|
| book_market_risk | 4 / 8 | 14/8 · 17/7 | 21 / 30 | 10/7/0 · 29/22/0 |
| book_limits_and_triggers | 3 / 6 | 13/9 · 18/10 | 19 / 34 | 10/9/0 · 31/23/2 |
| issuer_earnings_quality | 3 / 5 | 13/2 · 18/12 | 18 / 16 | 7/2/5 · 7/7/0 |
| issuer_profitability | 4 / 8 | 17/8 · 20/8 | 18 / 35 | 6/1/1 · 21/11/0 |
| issuer_business_risk_from_filings | 3 / 6 | 13/4 · 15/9 | 23 / 34 | 4/1/2 · 10/2/4 |

B 轮里 `book_market_risk` 7 次派单只做成 6/24 行、23 次 run 只 1 次干净；K1 改完 offers 之后，这个域在两个模型上都能执行了。mini 的 `issuer_earnings_quality` 仍是 5 次 type_errors、13 行只做 2 行（§4 K-a）。

## 4. mini 没出答案的七题

| 题 | 两次答案的拒绝 | 首要死因 | 落在 |
|---|---|---|---|
| Q02 | 第一次 5 条：其中「The book’s beta to USO is 0.33×」是**真的假陈述**，被拦下了，但拦它的是老的按代码比对规则，理由写成「句子点名 USO」，正是靠下面这处误报才拦到；V2 没有触发，因为句中已有「点名的代码」。第二次改对了，仍死于 2 条误报 | 分析师把 XOM 对四个基准的 beta 做成 vector，条目标签 USO/HYG/SPY/TLT 被铸成事实的主体，USO 于是进了「账本上的代码」，老的按代码比对主体的规则把「USO beta」读成点名 USO，同句里 XOM 的 4.61% 与 0.33× 都被判主体不符；另一条是「not dominant」被当成最高级断言 | tool（向量标签当主体）→ validation（否定未处理） |
| Q06 | 「1y window」里的 1 被判来路不明，第一次 3 处、第二次 1 处；主分析师自己心算的差额 $15.54B 对桌子的 $15.55B | 误报 + 真错（LLM 心算）。**修复时模型为躲误报，把「没有一年前的 beta 可比」这句诚实说明删了，换成重复的一句** | validation（窗口简写）+ LLM |
| Q07 | 两次都是 `superlative_without_rank`：「AAPL had the largest weight increase」 | 分析师排过权重变化，AAPL 在那个排序里是 1/3（`f_4c161962471e`）；但它的度量名是 `subtract(issuer_exposures.weight, issuer_exposures.weight)`，句子里没有「subtract」，V1 按「名字里每个词都在句中」把它排除，转而拿权重水平的排序（2/10、3/10）来拒。拒绝信列出的候选也不对，主分析师第二次只把 biggest 换成 largest | validation（V1）← tool（派生量用运算名） |
| Q10 | 两次都是 `period_mismatch`（"year-ends"） | 句子说的正是「这两个读数是季度的，不是财年末」，第二次写得更明确，仍被拒：V4 只看句中出现了年度词，不看同句已经点名了季度 | validation（V4） |
| Q13 | 三次答案 md5 相同，第三次之后本轮以 `ExceptionGroup` 崩溃，读者没有收到任何回复 | **V37/A2 的回归**：修复分支里第二次原样重发时，`break` 只跳出了工具循环，`attempts` 仍为 1，外层循环照常再请求一次模型，而那个 `repair_answer` 调用没有配 tool 消息。用同形请求复现，provider 返回 400 "An assistant message with 'tool_calls' must be followed by tool messages…"。普通回复分支结束的是外层循环，修复分支没有 | agent（代码） |
| Q17 | 第一次 7 条、第二次 5 条，几乎全是日号 | 新闻日期写成「Aug. 31」「Sept. 11」「Sept. 2」，没有年份，日号被当成数字挂在段落事实上报 `mark_mismatch`。V6 只认月日年三段齐全的形，计划 §6 明写两段形不认。**这一次误报挡住了五条假陈述**：分析师程序里写的是 `window: "1y"`，节点却起名 `aapl_ret_10d`，五条事实全是一年期相对收益，主分析师照节点名写成「ten-day relative return 27.0%」，并据此得出「AAPL、JPM、LLY、GOOGL 十日跑赢 SPY」这个反了的结论 | validation（V6）；潜在：LLM（节点名与参数不一致）+ validation（带窗口的标量不查周期） |
| Q18 | 第一次 `unpointed_figure`（真，已改）；第二次 `measure_mismatch` 'factor contrib' + `superlative_without_rank` 'largest' | 分析师给一个失败节点起名 `factor_contrib`，这个名字进了措辞表，任何写「factor contribution」的句子都被要求指向它，交接两次、门一次都因此拒；另一条是「I cannot name the largest and smallest contributing factor」被当成最高级断言 | validation（措辞表收进了模型起的名字；否定未处理） |

sol 的两道未答题：**Q05** 第一次把申报表格里的数写成「$142,263 million」，表格原文是「$142,263」、单位在表头「(in millions)」，12 条 `mark_mismatch`；第二次死于「March 29, 2025」被判为没有事实带着的日期，而引用的段落里就有这个日期（标题行写作 March 29, 2025，表头写作 March 29,2025），是 V6 的段落查找没对上。**Q13** 两次都是 `subject_mismatch`：「It did calculate a half-NVIDIA sale of $218K …, but the visible scenario still shows TLT at $646K」，句子用公司名 NVIDIA、用代码 TLT，规则只认代码，于是 NVDA 的 $218K 被判与 TLT 不符。三处都是误报。

## 5. 通过答案里的假陈述

逐条：句子 / 它引用的事实 / 事实实际是什么 / 为什么两道核对都没拦。

### 5.1 mini（10 条，5 题）

**Q08 ①②③**（出自 `sub:book_market_risk` 的 finding，交接放行后主分析师照抄）
- ①「the book’s exposure to the market proxy used for QQQ-style risk is -86.0% [f_1318e759a4f9], so the book is short that proxy」。事实是 `portfolio.integration.net_beta.equity_down`（−0.8599，单位 RATIO 所以显示成百分数）。它不是 QQQ 敞口；对「equity_down」这个风险的净 beta 为负，说明股市下跌时账簿亏钱，也就是做多，不是做空。
- ②「the prior run’s exposure is also -86.0% [f_1318e759a4f9] … unchanged」。这个 id 属于最新一期（节点 `analysis_latest`）；账本上上一期的值是 −0.8574（`f_7f47d55a5c4b`，−85.7%）。
- ③「the book is materially short QQQ-style market exposure」，结论建在 ① 上。
- 为什么没拦：两处核对只查「这个数是不是这个 id 的」，② 的数与 id 对得上；「prior run」这个词指向哪一期，没有规则查。分析师写 ② 时两期都引同一个 id，那两次 run 的结果都有扣下的图形（`held_back`），它没有再取上一期的值就断言两期相同。

**Q09**「For the cycle’s three-year range … low -75.83 [f_9475762f92e8], high -56.36 [f_a948a90e1ab1]」。这两条是 min/max，取自 6 个年度点（2020-09-26…2025-09-27，五年跨度）；两条标量事实**不带窗口**，V4 只查序列点，于是查不到。B 轮这一题的「twelve quarter」已经改对了，这一条是剩下的半截。

**Q11**「The book is ranked by smallest room left to warning as LLY, MSFT, AAPL, JPM, …」。到预警线的余量：MSFT −1.04%（20/20）、LLY −0.54%（19/20）、AAPL −0.20%、JPM +0.19%，前两名写反了。A、B、C 三轮这一题都在同一处出错。句子没有数字，也没说出「issuer concentration」，V1 收窄后的「句子要说全读数的名字」把它放过去了。

**Q15 ①②③**（出自 `sub:book_limits_and_triggers`，它在 caveat 里写明「排序输出第二次没再显示，我按账本上的持仓值和第一次的检查自己排」）
- ①「The ranking from smallest room to warning tier to largest is AAPL [f_…], MSFT [f_…], JPM [f_…], LLY [f_…], …」，引的是各自的当前值；实际顺序是 MSFT、LLY、AAPL、JPM。各家的预警档不同（LLY 是 12%，其余 15%），不能按当前值排。
- ②「AAPL, which is closest to its warning tier」。最近的是 MSFT。
- ③「the names that are slowest to unwind are not the ones closest to issuer concentration limits」。LLY 在两边都排第二（0.0023 天；−0.54%）。
- 为什么没拦：名字后面跟 id、没有数字，最高级规则里的 `groups` 为空，V1 又因句中没有「issuer / concentration」而跳过。

**Q16 ①②**（出自 `sub:book_market_risk`，与 Q08 同一个误读）
- ①「the latest and prior readings are identical on that metric, so the change is zero」。−0.8599 对 −0.8574，变化 −0.24%。
- ②「the book is not riskier now on that net-beta leg; there is no change driver to isolate」，建在 ① 上。
- 为什么没拦：「相同 / 未变」这种比较只挂了一个事实，没有规则要求它挂两个。

### 5.2 sol（5 条，3 题）

- **Q02**「FCF/debt: 254.0% [f_e7782f831f53] … still indicating annual free cash flow substantially exceeded debt」。数与事实一致，但 `fcf_to_debt` 对 XOM 的分母只有短端债务（S1 的结论：该发行人没有长期债务科目，cover 因此显示「完整」）。对 Exxon 的真实债务而言这句话是错的。**来源是事实本身**，S1 当时判为不改，留下了这个口子。
- **Q09 表格**：季度的应收、存货、应付天数与现金周期（`f_7b93abd89182` 等）约为同日年度值的 4 倍：2023-09-30 应收天数季度版 120.34，年度版 28.10；2025-09-27 为 141.69 对 34.89。天数方法在季度序列上仍用 365 天去除一个季度的流量。表里的水平值，以及「比三年低点高 84.63、比高点低 18.15」都放大了约 4 倍；相对位置不受影响。**来源是事实本身**。
- **Q09**「The latest sequential deterioration …」。周期从 −215.58 变到 −227.86，更负，对现金是改善；答案自己把最不利的一端（−209.71）叫作高点，离开它就是改善。
- **Q09**「the inventory increase outweighed the payable benefit」。存货天数 +14.89，应付天数 +25.41，应收天数 −1.76，应付的作用更大。
- **Q18**「No—the latest-run attribution does not reconcile … gap −0.85%」。答案把**持仓贡献之和** 0.38% 加上 alpha 0.01% 与残差 0.84%，得 1.22%，再与组合收益 0.38% 相减。桌子的**因子贡献之和**是 −0.47%，同一答案里还原样引用了它（"their sum, -0.00471605"），而 −0.47% + 0.85% = 0.38%，正好对上。答案的 caveat 说出了标签不符，结论却仍建在错的那个和上。

### 5.3 对 B 轮审计的一处更正

B 轮 Q17「over the last ten trading days versus SPY: AAPL 8.76% …」引用的 `window_return.relative`，窗口是 2026-08-11…2026-09-10，一个月，不是十个交易日。B 轮审计没有计入，按同一口径 B 为 12 条 / 10 题。价格方法的窗口只收 1m / 3m / 6m / 1y / 3y 或 `window_days`；sol 这一轮用 `window_days` 取到了真正的十个交易日（2026-08-27…2026-09-10）。

## 6. 25 项修法的实测读数

| 修法 | 读数（mini / sol） | 判 |
|---|---|---|
| A1 caveat 挨着数字 | Q01「应计比率只有年度序列」、Q09「年度点，不是十二个季度」、Q12「季度序列，只是部分替代」都写在数字旁；B 轮 Q04、Q12 的周期词假陈述消失 | 成立 |
| A2 重发不算第二次机会 | 主分析师的重发不计次 ✓；**修复分支的第二次重发让 Q13 崩溃** ✗；域分析师的重发本地应答、不记步，仪器数不到 | 部分成立，含一处回归 |
| A3 标签与字段测试 | 实测里没有能单独归因的读数 | 无法单独判 |
| M1 actor 随 MCP 调用 | 推断边 0/137、0/226 | 成立 |
| T1 兜底事实上账 | mini 两次兜底（Q09、Q19），`not_on_ledger` 兜底类 0，两题都出了答案 | 成立 |
| T2 用尽轮数交出 `shown` | Q09 的答案就是用 `shown` 里的图形写的 | 成立 |
| T3 拒绝信只说面上的动词 | 拒绝事实里 `describe(` 0 次；净 beta 两个模型都经 `book.analysis` 取到 | 成立（route 提示本身没有样本） |
| T4 `run` 收三种 id | portfolio 错类 0（B 11）；两次 run 直接用了 run_/calc_ id | 成立 |
| T5 读入上限、spacing/span、引用规则进 system | 空回复 12→8（其中读入 >9k 的 6→4）；域分析师 prompt 峰值中位 14.0k→15.0k，没有下降 | 部分成立 |
| T6 扣下的图形进事实表 | 引用了却不在事实表：0（B 2） | 成立 |
| T7 按公式命名 | sol Q08 同时出现 `capex_intensity` 与 `capex.divide.revenue`，同一组数仍有两个身份 | 部分成立 |
| S1 | sol Q02「FCF 远超债务」，见 §5.2 | 未解决，有了新读数 |
| K1 offers 对齐 | `book_market_risk` done/asked 6/24→8/14，run 干净 1/23→7/10（sol 22/29） | 成立 |
| K2 三条示例程序 | 净 beta ✓；跨发行人现金转换：mini 5 次 type_errors（「对比前十二个月」的写法程序里没有），sol ✓；卖出再买入：mini Q13 情景跑通后崩溃，sol Q13 死于误报 | 部分成立 |
| K3 读法下发 | Q15 按 20% 参与率算天数，两个模型都对（B 轮 ⑨ 消失） | 成立 |
| K4 三句 | Q19 两个模型都不再把增速读成份额 | 成立 |
| V1 无数字的最高级 | 误拒 Q07；漏掉 Q11、Q15 的排序错 | **不成立** |
| V2 book 词对代码主体 | 两轮都没有触发。mini Q02 的「The book’s beta to USO」是被老规则借 V-FP1 的误报拦下的；V2 要求句中没有点名代码，而那本账上 USO 被当成了代码 | 无样本，且有一处盲区 |
| V3 `[rep_…]` | 读者文字里 0 次 | 成立 |
| V4 周期词对点距 | 交接处 period_mismatch mini 2、sol 2；误拒 Q10；漏掉 min/max 标量（Q09） | 部分成立 |
| V5 段落数字的查法 | mini Q03 回购授权原文引用通过，这一题回来了 | 成立 |
| V6 拼写日期 | 交接首因 date_expected 0；误拒两段式日期（mini Q17）与表头日期（sol Q05） | 部分成立 |
| I1 按域表与重发标记 | 按域表已用上；重发标记看不见域分析师的重发 | 部分成立 |

## 7. 两个模型：同一套代码、同一道门

| | mini | sol |
|---|---|---|
| 出答案 | 13 | 18 |
| 假陈述 | 10 / 5 题 | 5 / 3 题 |
| 答对了 mini 答错的 | — | Q11（MSFT 最近，余量 −1.04%，单名涨 30.9% 触及违约档）、Q15（重叠是部分的，LLY 与 JPM 两边都靠前）、Q16（−86.0% 对 −85.7%，变化 −0.24%） |
| 死于门误报的题 | 5（外加 Q06 半题） | 2 |
| 每题耗时中位 | 39.5s | 129.1s |
| 全轮 token（prompt / completion） | 2.85M / 116k | 3.79M / 171k |
| 派单 / run | 28 / 69 | 50 / 168 |
| run type_errors | 18.8% | 6.5% |
| ≤3 token 空回复 | 8 | 0 |
| 答案形状 | 散文，图形数中位 1 | Markdown 标题、粗体、表格，图形数中位 10 |

几点读法：

- **sol 的错更少，但不是没有，而且错的类型不同。**mini 的错主要是读错桌子给的东西（净 beta 的符号、哪一期、排序），sol 的这类错在本轮一条没有；sol 剩下的三条是自己的推理错（周期方向、存货与应付的比较、对账用错了和），另外两条源自事实本身。
- **门的误报与模型强弱无关，但模型越弱越难绕过去。**sol 的两道未答题也都死于误报，只是它在别的题上写法不同，没踩到 mini 踩的那几处。误报是 validation 的问题，换模型只是换了一个踩中的概率。
- **sol 的 Markdown 读者看不到效果。**答案视图（`AnswerBlocks` / `AnswerText`）不解析 Markdown，sol Q01 被切成 45 个段落块，`**…**` 与表格竖线原样显示。主分析师的提示词写的是「Your reply is plain prose」，sol 没有遵守，门也不管形状。选 sol 之前要先定：渲染 Markdown，还是在门上拒它。
- **时间与花费。**同并发下 sol 全轮约 11 分钟，mini 约 3.5 分钟；token 多约 1.3 倍。按 token 计的价格不在仓库里，本文不折算金额。
- **读者可见的内部文字两个模型都有。**原始的类型报错与工具调用串被当作「桌子的原话」引给读者：mini Q07、Q14，sol Q06、Q10、Q18。mini Q14 还有一句话重复了两遍。

## 8. 按角色与七层的遗留清单

### validation：误报（杀题的那一类，最优先）
- **V-FP1** 向量条目标签被当成主体，USO 等基准代码进了「账本上的代码」→ 主体规则误拒（mini Q02）。根在 tool，见 T-c。
- **V-FP2** 否定句里的最高级：「not dominant」「cannot name the largest」（mini Q02、Q18）。
- **V-FP3** 窗口简写「1y」的数字（mini Q06）。V4 已有「计数对跨度」的面，可以把 `\d+[dwmy]` 纳入同一查表。
- **V-FP4** V4 的对比句：同句既点名季度又点名年度，并明说「不是」（mini Q10）。
- **V-FP5** V6 不认的两段式日期（mini Q17）与段落表头日期（sol Q05）。
- **V-FP6** V1 找错排序：派生量用运算名命名，句子不会说「subtract」（mini Q07）。
- **V-FP7** 措辞表收进了模型起的节点名（`factor_contrib`）和 pick 拆出来的名字（`portfolio.integration.net_beta`），以及运算谱系名（`pretax_income.subtract.net_income`）；本轮重放 17 次。
- **V-FP8** 句中公司名与代码混用时只认代码（sol Q13）；表格数字带表头单位（sol Q05）；段落里写着的日期没查到（sol Q05）。

### validation：漏报
- **V-FN1** 用「名字 + id」而不写数字表达的排序（mini Q11、Q15）。
- **V-FN2** 「相同 / 未变 / identical」这类比较只挂了一个事实（mini Q08、Q16）。
- **V-FN3** 「prior / previous / latest run」这类期次词，对着事实所属的 run 查（mini Q08）。
- **V-FN4** 派生标量（min / max）的周期（mini Q09），根在 T-g。
- **V-FN5** 带窗口的标量的周期词，即 V4 第二版（mini Q17 潜在五条、B 轮 Q17 一条）。

### agent（代码）
- **A-R1（最高优先，回归）** `meta_agent` 修复分支第二次原样重发时要么结束外层循环，要么先补一条 tool 消息再结束；现在是让 provider 400、本轮崩溃（mini Q13）。离线测试没有抓到它，因为脚本化 LLM 不校验消息结构。

### tool
- **T-a** 天数方法在季度序列上用 365 天去除季度流量，放大约 4 倍（sol Q09）。
- **T-b** `pick` 把带点号的键拆成「度量 + 主体」（`portfolio.integration.net_beta` / `equity_down`），制造出 V-FP7 的措辞。
- **T-c** 向量条目标签被铸成事实主体（mini Q02）。
- **T-d** 净 beta 的单位类是 RATIO，读者看到「−86.0%」「0.86%」（mini Q08、Q16）。
- **T-e** `fcf_to_debt` 的短端分母让「FCF 远超债务」成立于事实、错于现实（sol Q02）。
- **T-f** 段落切块从半句开始，丢了主语里的日期与金额（sol Q10 的商业票据）。
- **T-g** 派生 min / max 不带窗口（mini Q09）。
- **T-h** 域分析师的重发与本地拒绝不记步（仪器看不见）。

### skill
- **K-a** 「对比前十二个月」的跨发行人写法不在 K2 的程序里：前一期 TTM 需要 `fundamentals(…, at=<日期>)` 或 `at(of, period)`，拒绝信也没指过去（mini Q07 五次 type_errors）。
- **K-b** `book.analysis` 的读法没说 `net_beta.equity_down` 的符号含义（mini Q08 读成做空）。
- **K-c** 「十个交易日」要用 `window_days`（mini Q17 写成 1y）；10-Q 的 MD&A 是 Item 2，不是 Item 7（mini Q14 三次 `section_not_found`）。

### LLM
- mini：只看到一个 id 就断言两期相同（Q08、Q16）；排序结果被扣下后凭眼排序（Q15）；节点名写十日、参数写一年（Q17）；心算差额（Q06）；为躲误报删掉诚实说明（Q06）。
- sol：现金周期方向与分量比较（Q09）；对账用错了和（Q18）；不遵守「plain prose」。

### user report
- 原始报错串与工具调用串出现在读者文字里（两个模型都有）；重复句（mini Q14）；sol 的 Markdown 原样显示。

## 9. 结论与下一步

**mini 这一轮不过线，不回滚。**V37 的查表类与协议类修法在它们瞄准的题上成立（§6），代价是一处回归，以及新老规则在更丰富的程序上长出的一批误报。这些误报现在是 mini 最大的死因，五题。
**sol 在同一套代码上出答案 18，假陈述 5，mini 的三类读错在 sol 上没有出现。**

按价值排的下一步：
1. **A-R1**：一处代码，消灭轮内崩溃。
2. **误报八类（V-FP1…8）**：都是查表的细化，不需要模型多知道任何东西。用本轮 mini 与 sol 的全部受门文字建回归语料，做法同 `tests/data/v36b_accepted.json.gz`：每改一条，已知真拒绝不许丢，已知误报必须消失。
3. **漏报五类（V-FN1…5）**：其中 V-FN1、V-FN2 在 mini 上对应六条假陈述。
4. **tool 身份**：T-a、T-b、T-c、T-d 四处；T-e 需要重新拍板 S1。
5. **需要拍板的一项**：主分析师与域分析师用哪个模型。sol 的质量更高，耗时约 3 倍、token 约 1.3 倍，而且要先决定 Markdown 是渲染还是在门上拒。
