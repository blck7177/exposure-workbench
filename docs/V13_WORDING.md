# V13 — wording for review

> **状态**:待过目。本批的产品文案集中在这里,**每一条在代码里都只有一处**(一张表 / 一个常量),所以改一条 = 改一个文件的一行,不需要重跑任何逻辑。
> **为什么单列一份**:V13 的代码改动是呈现层与确定性映射,可以先合并;而这些句子是产品对陌生人说的话,措辞归 boss。计划 §7 的纪律是"代码可以先用占位句合并,守卫只检查有句子"。**我没有用占位句**——占位句会让守卫变成空转、让截图无法验收,所以写的是真句子;它们全部可改,且改动成本是一行。
> 分组顺序 = 落地顺序。S2 已合并,其余随各步追加。

---

## 1. 运行失败的句子(S2 已合并)

`apps/web/lib/errors.ts` 的 `RUN_ERROR_WORDING`。规则:**有 code 且后端存了 message → 显示 message**(后端只在"这句话本来就是写给读者的"时才存);**有 code 无 message → 下表**;**无 code → 通用句,并忽略 message**(V13 之前的行带着供应商原文且没有 code,不回填、也不信任)。

| code | 什么时候 | 句子 |
|---|---|---|
| `inputs_unusable` | run 拒绝了自己的输入(价格陈旧/缺失、无持仓、限额行指向不存在的检查) | This run could not use the data it was given, and stopped before writing anything. |
| `provider_quota` | 模型服务 429 | The model service refused this run — its rate or spend limit was reached. Nothing was written; it is worth trying again later. |
| `provider_unavailable` | 连不上 / 超时 / 5xx | The model service could not be reached, so the run stopped before writing anything. Try again. |
| `provider_refused` | 4xx(非 429)——我方缺陷 | The model service rejected the request. That is a fault on our side, not yours — nothing was written, and it has been logged. |
| `tool_face_unavailable` | 工具容器不可达或拒绝本次 bearer | The analysis service this run needs was unavailable, so it stopped before writing anything. Try again shortly. |
| `ingest_failed` | 取源数据失败 | Fetching the source data failed, so the run stopped before writing anything. Try again. |
| `brief_not_submitted` | research agent 用完预算未提交 brief(**不是缺陷**) | The analyst worked through its whole allowance without reaching a brief it could stand behind, so none was written. A narrower question usually gets there. |
| `lease_expired` | worker 停止上报,被 reaper 结算 | (后端已有句子,`task_service.LEASE_EXPIRED_ERROR`,原样沿用) |
| `run_failed` | 其余,含缺陷 | This run stopped before finishing. Nothing was written, and the failure has been logged. |
| —(无 code) | V13 之前的行 | This run stopped before finishing. Nothing was written. |

**两处值得单独看的**:
- `provider_quota` 说的是"值得晚点再试",而 `provider_refused` 说的是"这是我们的问题,不是你的"——两者都不把供应商的原文给读者(那是一段计费关系,读者不是当事人)。
- `brief_not_submitted` 刻意不说"失败":什么都没坏,是工作没收敛,而"narrower question usually gets there"是读者真能采取的下一步。

**保持不变的**(后端存的、写给读者的原句):
- `Cannot value this portfolio as of 2026-08-26 — newest price older than 10 days for: AAPL (30d old), … Re-run once the data is available, or remove the holdings.`
- `lease expired — the worker holding this task stopped reporting. This task type is not safe to replay, so it was failed rather than requeued; start it again to retry.`

---

## 2. 待追加(随后续步骤)

- **S4**:31 个工具的 `display` 短语(Activity 面板的人话步骤)、指标 / 因子 / 情景 / recipe 行的显示名、告警行文案。
- **S7**:免责一行、`<title>` 与 header 命名、日报 prompt 的改句(停止索取 `recommended_actions`)、`_SYSTEM` 两句(研究委派的措辞、精度指引)。

> `_SYSTEM` 与日报 prompt 属于 **LLM 路径**,按本批纪律**未改动**,只在这里列出建议措辞待拍板;topic 状态框里另有三批 `_SYSTEM` 措辞待过目,建议一并处理。
