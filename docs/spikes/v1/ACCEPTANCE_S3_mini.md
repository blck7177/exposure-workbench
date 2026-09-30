# S3_mini 实测记录：`codex/simplify-agent-loop-s2` 的 S3 提交，同题同模型一臂（2026-09-30）

> **被测的**：HEAD `aeb268a`（树 `054fbe4`）= `6ca9929`（S3："Bind cross-resource evidence and allow direct lead analysis"）+ 一个只重渲染措辞单的提交（第四次因平台引号差异）。离线 3165 passed。S3 改了发给模型的文字（主分析师多了 list/filings_read/prices_read/book_read/metric/calc 六个直接动词、ask 加 input_refs、STATE 优先展示选中证据），**未过目**；按 boss 9/30 指示"跑实例"跑在草稿措辞上。
> **条件**：与 S2_mini / V2E2_mini 完全相同（`phase_e.sh S3_mini`：9/13 快照、四个迁移 + remap、停表、面 :8105、`--deny submit_brief --deny start`、20 题并发 5、X 并发 4、全 gpt-5.4-mini）。02:57:44–03:02:03。
> **第一次尝试作废**：02:54 的第一次 RESTORE 失败——DROP DATABASE 被两个会话挡住，快照没有还原，6 题跑在 S2_mini 留下的库上。占库的是我 9/29 复测时起的夹具 worker（pid 2136780，脚本里的 worker 代码 a42dad1 已拿掉，进程没停，每秒轮询夹具库握着两条连接，这次赶在 DROP 前重连；S2_mini 那轮它也活着，靠时序 DROP 成功了，且 start 被拒没有任务可领，对读数无影响）。已 kill；那次的 log 与半份 round 文件留作 `S3_mini_run_attempt1_unrestored.log` / `S3_mini_attempt1_unrestored.json`；随后手动还原核实（50 runs、停表）再整轮重跑。本文只读第二次。
> **冻结**：开跑前后 HEAD/树相同、无 tracked 改动；写库失败 0、traceback 0。

## 0. 一眼看完

| | V2E2_mini | S2_mini | **S3_mini** |
|---|---|---|---|
| 出答案 / 20 | 14 | 12 | **9** |
| 门耗尽 | 6 | 8 | **11** |
| X 系列出答案 / 9 | 9 | 6 | **3** |
| 主分析师直接调用（20 题 / X） | — | — | **104 / 31**（被拒 42 / 6） |
| 主分析师 completion 合计；中位；prompt 峰值中位 | 106；5；13.0k | 73；3；12.3k | **141；6；19.4k** |
| 分析师任务；结局 | 48 | 36；returned 15 / stopped 21 | **26；returned 20 / stopped 6** |
| 分析师 completion 合计 | 274 | 243 | **143** |
| 证据交回；note 接受 / 拒 | — | 341；36 / 37 | 207；31 / **5** |
| submit 被拒 / submit | 54 / 79 | 40 / 55 | **17 / 37** |
| 主分析师没有派单的 turn | 0 | 0 | **3 + 4**（Q08、Q16、Q18；X04、X06、X07、X08） |
| 每题 prompt 合计中位 / 用时中位 | 190k / 40s | 158k / 40s | 176k / **29s** |

**没有过线。** S3 的两个目标各自成立了一半：分析师侧确实更省更稳（任务 26、stopped 6、note 被拒 5、submit 被拒 17/37）；但主分析师直接取数把分析师的工作连同分析师的失败一起挪进了主分析师的循环——它自己的 16 次 completion 与工具语法、行名、表结构撞在一起，出答案从 12 掉到 9，X 从 6 掉到 3。同题次间波动仍大，单次不构成方向性结论。

## 1. 11 + 6 次耗尽

| 题 | 退回序列 | 是什么 |
|---|---|---|
| Q03 | 无退回，16 次 completion 全部用在 32 次直接调用（16 次被拒） | 主分析师自己拉数拉到回合上限，一个字没写 |
| Q04、Q07、Q13、Q19 | mark_mismatch ×2 | 写的数与所指行不符（同 S2 的死因） |
| Q05 | mark_mismatch + repeated_answer | 原样重发 |
| Q08、Q17 | superlative_without_rank（+ ambiguous_point） | 最高级不指排名行 |
| Q14 | id_in_prose + superlative | 裸 id |
| Q15 | not_on_ledger + unpointed | 指向不在账本的 id |
| Q20 | unsourced ×2 | 账本上没有的数 |
| X01、X03、X05、X08 t1/t2 | 两次句检退回 | 同上 |
| X04 | 三次退回（无派单，主分析师自己做） | 同上 |

## 2. 主分析师直接取数的样子

- 20 题里主分析师直接调用 104 次（分析师 257 次），被拒 42：`unknown_name` 11（`book_read(issuer_exposures, column="beta_to_spy")` 这类——表里没有这一列）、`invalid_params` 5、schema 拒 5（把 `last_n` 写进 `period` 里：`{"fy": "latest", "last_n": 5}`）、`not_alone` 5、`not_prepared` 4、`series_not_derivable` 4、`input_unavailable` 4。分析师三轮 25–28% 的调用被拒率原样出现在主分析师身上。
- 7 个 turn 主分析师完全没派单（Q08、Q16、Q18；X04、X06、X07、X08）：其中 Q16 它按名字读 `issuer_exposures.beta_to_spy` 被拒后写"桌子不持有逐名 beta"——**错**：`metric(price.beta)` 有（S2 的风险分析师就拿到了 AAPL 0.68×…）。主分析师拿到了工具没拿到手册章节（handbook 只能 open 按需读，它没读），于是把自己不会问的说成桌子没有。
- Q10 用了 15 次直接调用、16 次 completion 才出答案；Q03 用完 16 次没出。直接路径的 16 次证据预算与 16 次 completion 上限现在互相挤。

## 3. S3 针对上轮三处假陈述的检查

| 上轮的错 | 这轮 |
|---|---|
| Q16 "net beta to SPY" 指 rates_up 行 | 没再出现，但原因是主分析师这次根本没拿到 beta（见 §2 的假阴性），不是检查拦住 |
| X07 "4.06% of the book" 是权重 | 损失金额对了（$88.28K，S3 文档预期 $88,280）；**份额仍错**："That is 20.2% of the book's market value" 所指行是损失 ÷ NVDA 仓位市值（= 回撤率本身），不是 ÷ 书的市值（应 ≈0.82%）。新检查判了 drawdown × money 的主体，没判"占书的份额"这个度量 |
| Q19 16% 靠 "$16.5 billion" 对上 | 段落单位检查拦住了——这题耗尽（mark_mismatch ×2），读者什么也没拿到 |

抽查的第三篇 Q11（四轮第一次出答案）："AAPL is the closest to its issuer-concentration warning tier … already -0.20% above warning" ——AAPL 15.2% 已经越过 15% 预警档，"最接近预警档"按题意应是尚未越过的 JPM 14.8%；"-0.20% above" 符号也反了。数字全部对行，读法错。

## 4. X 系列

3 答 / 6 耗尽。形状：no_ask 4（主分析师自己做）、in_sequence 2、together 2、one_family 1；转手：carried 0、up_front 2、shotgun 2、not_carried 1、`upstream_never_asked` 3（跨族的上游那一半没人问）。X06 这次名字对了（MSFT），X07 金额对了份额错，X02 出答案。跨族转手这一读数在 S3 上比 S2 更差：主分析师能自己读，就不再把上游交给分析师。

## 5. 判断

- 分析师侧：evidence-v2 + 拒绝只作用于本次候选，确实把交接损耗压下去了（stopped 21 → 6、note 拒 37 → 5）。这是 S2/S3 里站得住的部分。
- 主分析师直接取数是把 specialist 的资源工作挪给了不带 specialist 知识的角色：工具语法的失败率原样转移（42/104）、回合预算被拉数吃掉（Q03）、不知道有什么度量就说桌子没有（Q16）。按角色边界说，这是 intelligence 越界到 tool/skill 的地面，而且没带 skill 一起去。
- 架构读数里的核心问题原样在：耗尽的死因仍是转写文法（mark_mismatch、unsourced、superlative），门放行的仍是读法错（X07 份额、Q11 最接近）。数由桌子写、门查度量词与行元数据这一步，S3 没做。
- 测量本身：单次跑；9 vs 12 vs 14 的差在次间波动范围内；要 pass^k 才能比较。措辞未过目；产物已提交到本分支。
