# V36 Phase 1 冒烟：五题，第一次跑起来的两个 loop（2026-09-15）

仪器：`scripts/battery_fixture.sh serve`（:8105 over `exposure_battery`，服务工作树代码，本轮前重启过）、
`scripts/conversation_battery.py docs/spikes/v33/questions_v33.json --fixture --concurrency 3 --deny start`、
gpt-5.4-mini、`--only` Q01 / Q11 / Q13 / Q18 / Q20。
文件：`V36_smoke.json`、`V36_smoke_forensics.txt`（沟通表）、`V36_smoke_schema.md`（每种沟通的真实载荷）。
基线对照是 J 轮（`docs/spikes/v33/V33J.json`），同一 fixture、同一模型。

这是 Phase 1 的验收跑，不是一轮实测：五题不能判质量，能判的是**链路是否成立、沟通表是否读得懂**。

## 1. 链路成立

| | J 轮（V35） | 本轮（V36） |
|---|---|---|
| 出答案 / 5 | Q01 ✓ Q13 ✓ Q18 ✓ Q20 ✓ Q11 ✗ | Q01 ✓ Q11 ✓ Q18 ✓ / Q13 ✗ Q20 ✗ |
| 主分析师 completions（中位） | 4 | 3 |
| 主分析师 prompt 峰值（中位） | 20k | 6.2k |
| 域分析师 | — | 10 个（每题 1–3 域） |

**Q11 第一次出了答案。**三轮从没通过的那题，本轮主分析师答了第四问（8% 上限下哪些超标），并且明说前三问没拿到证据：
"I was not given the ordered issuer-concentration warning-room table, so I cannot say which position is closest…"。
那三行在交接处被拒（`coverage 1/4, refused 3`），所以主分析师手里根本没有那些数字可写——
这正是交接核对存在的理由：**错在离它最近的地方停住，而不是两个 loop 之后变成主分析师赔掉的一轮。**

主分析师的 prompt 从 20k 掉到 6.2k：它不再读 digest。取证的上下文留在域分析师那边（单个 8k–18k）。

## 2. 沟通表读得懂（Q11）

```
  seq  from                          →  to        carrier     status     size            schema keys
  1    ctx                           ·  meta      completion  completed  p5349/c221 tok  -
  2    meta                          →  sub       delegate    completed  in 1053         tasks
  3    ctx                           ·  sub:book_limits…      completion completed p6680/c426
  4    ~sub:book_limits…             →  tools     run         completed  in 1688         program    error: type_errors
  …
  13   sub:book_limits…              →  check     submit      rejected   in 5251         brief,report,coverage   coverage 2/4 refused 2
  …
  21   sub:book_limits…              →  check     submit      rejected   in 4606         brief,report,coverage   coverage 1/4 refused 3
  23   meta                          →  gate      answer      completed  in 553          text       accepted
```

全轮往返：`meta → sub` 5、`sub → tools` 32（run 32、read_filings 6、compile 4、search_web 1）、
`sub → check` 16、`meta → gate` 9、`sub → ledger` 24（边界事实）。

`~` 是**推断出来的归属**，值得单说：`tool_call` 行由 registry wrapper 写，它在 MCP 门后面，
bearer 带 session 与 message 而不带 actor，所以它不知道是谁在调。本轮按"最后开口的那个分析师"归属，
串行下精确，并行下（Phase 3）不再精确。正解是把 actor 放进 token，**已记进 Phase 3 的前提**。

## 3. 冒烟查出的两处真缺陷（已修）

- **一行既被答又被解释。**Q20 的 `issuer_profitability` 交了 3 条 finding 和 3 条 not_done，指同样三行，
  coverage 读作 `done 3, not_done 3`——一个数说了两件相反的事。`handoff_check` C1 加
  `answered_and_explained`。
- **一份什么都没settle的 brief 被叫作 verified。**Q18 的 `book_drawdown_and_attribution`：
  5 行全进 not_done，五条都合规，于是 `verdict.ok` 为真，状态写成 "verified"——对核对是真的，
  对工作是假的，而主分析师读的是那个词。状态改为：过了且有 finding→`verified`，过了但一条都没答→`absent`。

两处都加了离线测试（`test_v36_delegation` / `test_v36_sub_analyst` 末节）。

## 4. 留给 Phase 4 的观察（本轮不改）

- **`compile` 只用了 4 次，`run` 32 次。**域分析师多半直接写 program，Q11 头两次 run 直接 type_errors。
  提示词里 compile 是"可以用"而不是"先用"，改不改要有前后对照，属 Phase 4。
- **一个域分析师花 7 次 completion、5 次证据调用，只覆盖 1/4。**预算是够的，效率不是。
- **Q13 用了三个域（hypothetical_trades / limits / market_risk），三个都 partial 或 refused，主分析师收场。**
  多域题是成本最高也最容易全盘落空的形状。
- **Q18 的域分析师把 run 句柄当 portfolio 传**（`no portfolio 'run_…' on this desk`），
  主分析师如实引用了这句拒绝。这是 tool 侧的措辞，也是 §21 里"desk 原话可引用"这条在起作用。
- 沿用的缺口不变：ROSTER 与 BRIEFING 的文字仍不在账本上。

## 5. 树的状态

冒烟期间未改代码；第 3 节两处修复在冒烟之后、离线测试之内完成。
离线 2479 passed / 11 skipped。
