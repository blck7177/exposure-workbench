# V36 验收记录：A 轮 20 题，与 J 轮对照（2026-09-15）

> 仪器：`scripts/battery_fixture.sh restore backups/battery/battery-2026-09-13.sql.gz`（还原后补跑
> `v36_actor.sql` 与 `v36_analyst_reports.sql`）→ `serve`（:8105，服务工作树代码，face 实测为
> `run · read_filings · search_web · start` 四个）→
> `scripts/conversation_battery.py docs/spikes/v33/questions_v33.json docs/spikes/v36/V36A.json --fixture --concurrency 5 --deny submit_brief`，
> `BATTERY_OWNER_ID=user_3IDBMeAxLTbecvGorzwV7FCeroR`，gpt-5.4-mini，与 J 轮同问题、同快照、同模型。
> 文件：`V36A.json`、`V36A_forensics.txt`（沟通表）、`V36A_schema.md`（每种沟通的真实载荷）、
> `V36A_answers.txt`、`V36A_audit.txt`（每条通过的答案与它引用的每条事实并排）、`V36A_run.log`（原始 log）。
>
> **实测期冻结代码。**开跑前 HEAD `4dcf02f`，树 `85d78a6`；跑完同样是 `4dcf02f` / `85d78a6`，
> `git status --porcelain --untracked-files=no` 为空。本轮遇到的每个问题只记录，没有改任何一行代码。

## 1. 数字

| | G（V34） | H（V35） | I | J | **A（V36）** |
|---|---|---|---|---|---|
| 出答案 / 20 | 4 | 5 | 11 | 9 | **14** |
| 通过答案里含读者可见假陈述的题 | 0/4 | 4/5 | 1/11 | 3/9 | **5/14** |
| 假陈述条数 | 0 | — | 1 | 3 | **8** |
| meta 拒绝 | 32 | 30 | 18 | 22 | 16 |
| 主分析师 completion 中位 / 合计 | — | — | — | 4 | **3 / 59** |
| 主分析师 prompt 峰值 中位 / p90 | — | — | — | 20k / — | **8.2k / 9.4k** |
| 域分析师 completion 合计 | — | — | — | — | 220 |

> 表中 J 的「20k」取自冒烟(`SMOKE_V36.md`)的五题对照;按 `scripts/battery_counters.py`(9/15 起带 V36 列)读全部 20 题,
> `lead_prompt_peak` 中位 / p90 是 J **16.9k / 22.5k**、A **8.2k / 9.2k**(两版的 `meta.prompt_tokens` 都是 `count_prompt` 的峰值)。
> 同一计数器对 A 轮读出:交接拒绝 51 次,首因最多的是 `answered_and_explained` 18 次,其次 `mark_mismatch` 8;报告 verified 21 / refused 13。

**读法：出答案数是 J 轮的 1.6 倍，每条答案含假陈述的比率没有改善**（J 3/9 = 33%，A 5/14 = 36%）。
架构换掉的是「谁把意图翻成 desk 语言」，它买到的是覆盖率；它没有买到、也不该被指望买到的是语义正确性——
两处核对都只查表，指向正确而语义错的句子两边都放行，这一点在设计稿 §6 里写明过，本轮是它的实证。

派单 40 次，14 个域全部被用到；交接覆盖合计 asked 156 / done 111 / not_done 28 / refused 30；
报告落库 34 份。往返载体：`run` 79、`submit` 67、`read_filings` 60、`boundary` 49、`report` 34、
`answer` 30、`delegate` 26、`start` 22、`compile` 7、`search_web` 7。

## 2. 六道没出答案的题，四道死在同一处

| 题 | gate_refusals |
|---|---|
| Q05 / Q06 / Q14 / Q17 | `unverified_quote` ×2 |
| Q07 / Q15 | `superlative_without_rank` ×2 |

**F1（最高价值）：主分析师引用域分析师的话，而那句话不在账本上。**
Q05 两次作答都卡在同一句：分析师引号里写的是
`"The desk holds product and geographic revenue as filing prose, not as computed figures"`——
这是 brief 的 `not_done.why`（或 `caveats`）原文，**给主分析师看了，没有铸成事实**，于是 G4 拒。
这是 ACCEPTANCE_V33 §21 那条「briefing 与 skill 推送展示了却不在账本上」在新边界上的复发：
V36 把展示面从 digest 换成 brief，缺口跟着搬了家。20 题里它一个人吃掉 4 题。

修法方向（未做）：`not_done.why` 与 `caveats` 要么在 `submit` 时铸成 absence fact，
要么强制分析师指向它已经拿到的那条 boundary 事实（`not_done.boundary` 已经有这个字段，只是不强制）。

**F2：`superlative_without_rank` 仍是主分析师第二常见的死因**（Q07 / Q15 各两次）。
本轮全轮重放里它出现 29 次，是所有问题里最多的一类。

## 3. 五道通过的题里的八条假陈述

逐条给出：句子、它引用的事实、事实实际是什么。原文与并排见 `V36A_audit.txt`。

### Q02 — 两条

**①「那四个点与一年前完全相同，所以没有同比的收紧或放松」。**
分析师写的是它看到的东西，问题在它看到的东西本身：`cov` 与 `cov_prev`、`fcf_debt` 与 `fcf_debt_prev`、
`ndebt` 与 `ndebt_prev` 是**逐点相同的两条序列**（都是 2022-12-31…2025-12-31 的同四个年度点）。
"一年前的同四个季度"这个窗口 desk 表达不了，`program_builder.unreadable_window` 本来会拒——
但**域分析师这一次是直接写的 program，没走 `compile`**，那道守卫在编译器里，于是被绕过。
角色：tool（守卫的位置）+ V36 新形状（分析师可以直接写 program）。

**②「FCF to debt is 9209.8%, 817.8%, 619.9%, 254.0%」。**
底层值是 92.1 / 8.2 / 6.2 / 2.54，作为 RATIO 显示就是 ×100。
一个 9210% 的 FCF/债务比不是读者能读的数。这是 V17「ratio vs multiple」那一族，
`fcf_to_debt` 的 unit_class 判错。角色：tool（身份）。

### Q11 — 一条

**③「LLY 是最接近警戒线的那个检查，desk 的排序把它排在第一」。**
它引用的事实 `f_b4fd5940f3e1` 自己带着 `rank=2`；`nearest` 节点的第一名是 **MSFT**（room -1.04%），
LLY 是第二（-0.54%）。

**门为什么没拦：那句话里一个数字都没有。**`superlative_without_rank` 只在句子里有已链接的图形时才跑
（`_check_sentence` 的 `if words & SUPERLATIVES and groups`），"desk 的排序把它排在第一"是一句关于排序的
断言、不带数，于是 `groups` 为空，检查不执行。角色：validation。

同题还有一个仪器缺口：`citations` 里的 `f_06d4572abcaf` **在账本上但不在 `facts` 表里**
（它是被 `held_back` 扣下的那批之一）。门读账本所以放行，而证据抽屉读 `facts` 表，所以这条引用点开是空的。
全轮 115 条引用里只有这 1 条，但它是「门接受了、读者打不开」这一类。角色：tool（两个存储的分歧）。

### Q13 — 三条

**④「After the trade, Technology sector concentration is 35.3%」以及后面整段限额。**
这些图形来自 `lc_current` 节点，而那个节点跑在 `run(portfolio="port_001")` ——**卖出前的书**。
情景确实跑过（seq 4/6/12 有 `sell`+`buy`），但限额那一段是另一个域分析师另外跑的基准书。
卖掉一半 NVDA 之后 Technology 不可能还是 35.3%。

**⑤「The book's beta to QQQ is 1.32×」。**引用的事实是 **NVDA** 的 `price.beta`（`place=1 of 10`）。
门的 `subject_mismatch` 要求句子里出现一个 ticker 才比对，这句只说 "the book"，于是不跑。角色：validation（与 ③ 同一个形状）。

**⑥「gross_exposure 现在比 Technology 更接近它的警戒线」。**
gross_exposure 100.0% 对 110.0%（10 个点），Technology 35.3% 对 40.0%（4.7 个点）。反了。
两个 room 都没有被算成事实，所以这是分析师在散文里比的。角色：LLM。

### Q18 — 一条

**⑦「这个 run 的各块加起来是 100.0%，所以缺口是 99.6%」。**
`factor_share` −125.5% 与 `unexplained_share` 225.5% 是**份额**，和为 1 是构造出来的；
`sum_of_position_contributions` 0.38% 是**收益**。份额减收益得到的 99.6% 不是任何意义上的对账缺口——
真正的缺口应当接近 0。这个减法是分析师让 desk 算的，而**单位代数接受了 RATIO − RATIO**。
角色：LLM（选了不该减的两个量）+ tool（代数没拦）。

### Q19 — 一条

**⑧「AMZN 一年的总收益是 -8.12%，SPY 一年的总收益是 0.00%」。**
两条引用都是 `window_return.relative`。SPY 相对自己的相对收益当然是 0，它不是 SPY 的总收益。
同一段后面又写「所以 AMZN 相对 SPY 的一年收益是 -8.12%」——同一个数被同时说成总收益和相对收益，必有一个是假的。
角色：LLM（读法）+ skill（`window_return.relative` 的读法没写进域知识）。

### 清白的九题

Q01、Q03、Q04、Q08、Q09、Q10、Q12、Q16、Q20。其中 Q04 / Q10 / Q12 / Q20 是**诚实的部分答**——
说清了 desk 给不了什么、并引用了 desk 的原话；Q08 的三名对比、Q09 的十二季周期、Q16 的逐名 beta
都完整且每个数都指得回去。

## 4. 两处不是假陈述但读者看得见的缺陷

- **Q20 的回答里出现五次 `[rep_deb9dfe8a3ab]`。**主分析师把报告 id 当成事实括号写进了散文。
  门只认 `f_…`，`rep_…` 不匹配任何模式，于是原样留在用户看到的文字里。
  角色：validation（渲染层不认识这种标记）+ LLM（不该这样用）。
- **Q12 有一整句重复两遍**（"I cannot complete the JPM-versus-Bank of America-versus-Goldman Sachs ranking yet."）。

## 5. 域分析师这一侧的观察

- **`compile` 只用了 7 次，`run` 79 次。**域分析师绝大多数直接写 program。Q02 的 ① 就是这么发生的：
  编译器里的窗口守卫在直接写 program 的路径上不存在。这是 V36 的形状带来的新面，不是旧缺口。
- **`submit` 67 次对 40 次派单**：平均每个分析师提交 1.7 次，即多数被交接核对退回过一次。
  退回是设计内的（第二次 `tool_choice=required`），代价是 completion：域分析师合计 220 次，中位每个 5 次。
- **交接拦下的东西是真的。**refused 30 行、not_done 28 行。Q11 的 8% 上限那一问被如实报成
  "the desk held back the over-cap filter result in the digest" —— digest 扣图这条 §21 老缺口还在，
  但这一轮它**被说出来了**，而不是被分析师用眼睛数出来（J 轮 Q11 就是用眼睛数的）。
- **`start` 被调用 22 次**（本轮没有 `--deny start`，与 J 轮一致）。任务进了 `exposure_battery` 的
  tasks 表，worker 指向的是生产库，所以没有任何一个被执行——与 J 轮同条件。

## 6. 按角色的遗留清单（本轮不改，等拍板）

**validation（三条，都是"检查只在句子里有数字时才跑"的同一个形状）**
- V1 超最高级：句子里没有图形时 `superlative_without_rank` 不执行 → Q11 ③。
- V2 主体：句子里没有 ticker 时 `subject_mismatch` 不执行 → Q13 ⑤。
- V3 `[rep_…]` 这类非事实标记原样留在读者看到的文字里 → Q20。

**tool（四条）**
- T1 **brief 的 `not_done.why` 与 `caveats` 展示给主分析师却不在账本上** → 吃掉 4 题。最高优先。
- T2 `unreadable_window` 只在 `compile` 路径上 → Q02 ①。
- T3 `fcf_to_debt` 的 unit_class → Q02 ②。（§21 的 tool 身份三处仍未动。）
- T4 `held_back` 的事实在账本上、不在 `facts` 表里 → 引用点开是空的（1/115）。

**LLM（三条，门拦不住的语义错）**
- L1 拿了另一个主体的数当本主体的（Q13 ⑤）。
- L2 拿了卖出前的书当卖出后的（Q13 ④）。
- L3 在散文里比大小、算缺口（Q13 ⑥、Q18 ⑦）。

**skill（一条）**
- S1 `window_return.relative` 的读法没写进域知识 → Q19 ⑧。

## 7. 对验收线的结论

计划 §Phase 4 定的四条：

| 验收线 | 结果 |
|---|---|
| 出答案不低于 J 轮的 9 | **过**：14 |
| 假陈述不高于 J 轮的 3 且都可追溯 | **不过**：8 条。可追溯这半边成立——每一条都能指回它引用的那条事实，本文逐条给了 |
| Q04 / Q10 / Q11 / Q15 至少通过一次 | **部分过**：Q04 ✓ Q10 ✓ Q11 ✓，Q15 仍未通过 |
| 每题沟通表能指出每次往返的贡献 | **过**：`V36A_forensics.txt` 逐题给了表与往返计数；`V36A_schema.md` 给了 83 种载体的真实载荷 |

**不建议就此回滚到 `v35-final`。**出答案从 9 到 14、主分析师 prompt 峰值从 20k 到 8.2k、
三轮从未通过的 Q04 / Q10 / Q11 都出了答案，这些是结构换来的。假陈述的条数上升主要来自
Q13 一题贡献三条、Q02 一题贡献两条；按题算是 5/14 对 3/9，比率基本没动。
真正该做的是 §6 的 T1（4 题的直接损失）和 V1/V2（两条检查的执行条件），这两处都不大。

## 8. 一件顺带记录的事

`docs/spikes/v32/`（本次 session 之前就在树上的未跟踪文件）在 Phase 1d 的 `git add -A` 里被一并提交进了
`5271baf`。不是本轮实测造成的，也没有回滚；记在这里以免日后翻 blame 时困惑。
