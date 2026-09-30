# S2_mini 实测记录：`codex/simplify-agent-loop-s2` 同题同模型一臂（2026-09-30）

> **被测的**：`codex/simplify-agent-loop-s2` HEAD `f26c7f9`（树 `20d0c69`）= `6a03fe5`（S1 `7bfddf2` + S2）+ 一个只重渲染措辞单的提交（引号差异，模型文字无变化；这是第三次因平台引号差异补这个提交）。离线 3132 passed。S1/S2 改了发给模型的文字（ask 不再收 requirements、submit 改 evidence-v2、STATE 分页视图），**未过目**；按 boss 9/30 指示"跑 20 实例测试"跑在草稿措辞上。
> **条件**：与 V2E2_mini 完全相同（`phase_e.sh S2_mini`：同一 9/13 快照、同四个迁移 + remap、停表、面 :8105、`--deny submit_brief --deny start`、20 题并发 5、X 系列并发 4、全 gpt-5.4-mini）。01:12:22–01:18:18。lead 73 次 completion、analysts 243 次（X 系列另计），全部 `gpt-5.4-mini-2026-03-17`。
> **冻结**：开跑前后 HEAD/树相同、无 tracked 改动、src/tests/scripts 无新于 HEAD 的文件；写库失败 0、traceback 0。
> **文件**：`S2_mini*` 与 `S2_mini_X*` 各一套，同前几轮。

## 0. 一眼看完

| | V2E2_mini（desk-v2-wip e5d4b45 的前身 68a52e1） | **S2_mini（本轮）** |
|---|---|---|
| 出答案 / 20 | 14 | **12** |
| 门耗尽 | 6 | **8** |
| X 系列出答案 / 9 | 9 | **6** |
| 写库失败 | 0 | 0 |
| 分析师任务数；结局 | 48；partial 24 / settled 4 / unsettled 16 / refused 4 | 36；**returned 15 / stopped 21**（stopped：submission_rejected 14、turn_limit 5、no_submission 2） |
| 分析师交回 | brief 行：done 35 / asked 141 | evidence-v2：选出证据 341 行、可用证据 1532 行、接受的 note 36、拒绝的项 37 |
| submit 被拒 / submit | 54 / 79 | 40 / 55 |
| 分析师工具调用被拒 | 107 / 408 | 100 / 383 |
| 主分析师 ask 被拒 | 16 | **2** |
| 主分析师 completion 中位 / open 次数 | 5 / 22 | **3 / 51** |
| 每题 prompt 合计中位 / 用时中位 | 190k / 40s | **158k** / 40s |
| 主分析师 prompt 峰值中位 | 13.0k | 12.3k |
| 答案退回总数 | 35 | 23 |

**没有过线，且"出答案"不是质量读数**（§3 抽查 3 篇答案 3 篇有假陈述）。S2 把交接从"分析师写经检查的 finding 句"换成"分析师交证据行 + 单独检查的 note"，主分析师直接从行写答案：主分析师侧更省（completion 3、ask 几乎不再被拒、prompt 少 17%），但转写负担挪到了它身上——耗尽的死因从 V2E2 的括号/裸 id 变成了 **`mark_mismatch`**（写的数与所指行对不上：8 次耗尽里 8 次有它）。

## 1. 耗尽的 8 + 3

| 题 | 退回序列 | 是什么 |
|---|---|---|
| Q02 | unpointed ×2 | 数在账本上没带括号 |
| Q03、Q04、Q11、Q20 | mark_mismatch ×2 | 写的数与所指行不符：符号丢失（12.3% vs 行 -12.3%）、错位（0.2% vs 行 4.80%）、把计数 "8" 当数字指向行、把段落 "$102,718 million" 改写成 "$102.718 billion" |
| Q08 | ambiguous_point + superlative_without_rank | 序列点没写日期；最高级不指排名行 |
| Q09 | direction_conflict + repeated_answer | 方向说反后原样重发 |
| Q17 | mark_mismatch + change_conflict | 同上 + 变化算错量 |
| X03 | mark_mismatch → 16 次 completion 上限 | 49 次调用、82 秒，主分析师在读分页视图里耗尽回合 |
| X04 | unsourced + mark_mismatch | 账本上没有的数 |
| X06 | mark_mismatch + repeated_answer | 原样重发 |

V2E2 里耗尽的 Q14、Q15、Q16 这次出了答案；V2E2 出答案的 Q02、Q03、Q08、Q09、Q20 这次耗尽——同题同模型的次间波动很大，两轮各只跑了一次，**12 vs 14 不构成方向性判断**。

## 2. 分析师侧：evidence-v2 的实际样子

- 36 个任务交回 341 行证据（平均 9.5 行/任务），可用证据 1532 行；接受的 note 只有 36 条（平均 1 条/任务），被拒 37 项。stopped 21/36：submission_rejected 14（note 反复被拒直到停止）、turn_limit 5、no_submission 2。`tasks_returned_empty` 0——证据总能交回，这是 S2 的设计收益：V2E2 的 26 个空返任务在 S2 不存在。
- note 被拒的类：`unsourced_figure` 11、`not_on_ledger` 7、`passage_requires_pointer` 6（新规则：段落裸数字要显式指针）、`id_in_prose` 6、`superlative_without_rank` 5、`unpointed_figure` 3。按检查通道：shape（note 块检查）170 条问题、answer 51 条——V2E2 是 finding 230、answer 86。
- 工具调用被拒 100/383：`invalid_params` 19（V2E2 32）、`unknown_name` 19（28）、`not_held` 19（4）、`not_alone` 10、`input_unavailable` 9。期间语法与因子表行名两类没有变——S2 没动工具层（S3 才动）。

## 3. 抽查：3 篇答案 3 篇有假陈述（门都放行了）

| 题 | 写了什么 | 事实 | 为什么门没拦 |
|---|---|---|---|
| Q16 | "The book's net beta to SPY is 0.01× [f_b8d750fbe551], unchanged from 0.01× [f_11907145462f]" | 两行都是 `portfolio.integration.net_beta.rates_up`（对利率上行的净 beta），桌子不持有书级 SPY 净 beta | 句子里的 "SPY" 没有被对到行的度量名 `rates_up`。**V2E2 的 Q16 答案里是同一句话，当时没查出来** |
| X07 | "our position would lose $52.22K [f_04dfd4a0f78f]. That is 4.06% [f_a3537195b26e] of the book" | $52.22K = 仓位市值 × 最深回撤，对；4.06% 是 NVDA 的**权重**，不是损失占书的份额（≈0.8%） | 数字与行一致，句子把权重说成了损失份额——度量词没被检查 |
| Q19 | "AWS was 17% [passage] of Amazon's revenue in the latest filed annual period, after 17% in the prior year and 16% in the year before that [passage]" | 同一段落的 Net Sales Mix 表：2024 = 17%，**2025 = 18%**；段落只有两年，没有 16% | 最新年取错列；"16%" 所指段落里没有——离线只放这一段落该句被拒（unsourced_figure）；实测放行是因为账本上另一段业绩指引写着 "$16.5 billion"，"账本能对上这个数"的检查按数字串 16 在任一段落里出现放行，不看所指行、不看单位（离线加上那段后复现放行） |

X07 的计数器判 `not_carried`（书的市值行没带过去）与此一致。这三处在 V37 的口径里都是"通过答案里的假陈述"；没有做全量审计，65 项独立 oracle 仍不存在。 机制（离线复现）：度量词按度量名的点号尾部比对（`net_beta.rates_up` 只剩 "rates up"，句子里的 "SPY" 无人核对）；段落数字按数字串在账本任一段落里出现放行。

## 4. X 系列

6 答 / 3 耗尽。派单形状全部变成 `in_sequence` 7 段（V2E2 全是 `together`）：S1 去掉 requirements/for 之后主分析师改为先问一族、拿到名字再问另一族——转手读数：carried 2（X01 MSFT、X08-t2）、shotgun 3（X02 issuer×3 → risk、X03、X04）、wrong_name 2（X05 说是 AAPL 拖累最多、X06）、not_carried 1（X07 书市值）。`in_sequence` 回合 lead completion 6、用时 40.6s，对照 `one_family` 2 / 8.9s；没有 `together` 可比，步骤 7 的决策规则仍读不出成本差。

## 5. 判断

- S2 达到了它自己写的目标：证据不再因格式交接失败而丢（空返 0、证据 341 行到主分析师手里、主分析师 ask 被拒 16 → 2、prompt 少 17%）。
- 代价是转写错误从分析师挪到主分析师：`mark_mismatch` 从 2 题变成 8 题的死因；出答案数 14 → 12、X 9 → 6，但次间波动大，不能下方向性结论——同题再跑一臂或换 sol 才能分离。
- 与 V2E2 相同的没变：工具语法（invalid_params、unknown_name 各 19）、段落里的数不可算、交易语法；这些是 S3 的事。
- 门放行的假陈述（Q16 SPY、X07 份额、Q19 年份与 16%）不是 S2 引入的（Q16 同句在 V2E2 里就有），但 S2 让主分析师直接从行写作后，"数字对、度量词错"这一类会更多——需要在 validation 里加度量词对行名的检查、段落数字检查改为整词匹配，或先跑独立 oracle。
- 措辞未过目；产物已提交到本分支。
