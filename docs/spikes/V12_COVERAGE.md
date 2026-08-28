# V12 验收 — 知识层:把已经写下的东西交给模型

> 2026-08-28。**1082 offline / 232 live 全绿**(批前 1073/225)。四镜像重建上线,站点 200。
> 计划 `docs/IMPLEMENTATION_PLAN_V12.md`,上游 `dev_note/portfolio-demo/analyst-skills/13-skill-as-knowledge.md`。
> **本批不新增任何分析能力**:没有新工具、没有新公式、没有阈值、没有规则、没有 SKILL.md、没有路由器。

---

## 1. 结果

同一批问句、同一个模型(gpt-5.4-mini)、开关对照,n 如下:

| 题 | V11 基线 | V12 | 判据 |
|---|---|---|---|
| **4 家总债务 ×6 = 24** | **12/24 = 50%** | **24/24 = 100%** | 数值命中真值(cover) |
| ↳ 走 `evaluate_formula` | 9/24 | **24/24** | 轨迹 |
| **"why large drawdowns" ×8** | 2/5 调过 `get_drawdown_episodes` | **8/8** | 轨迹 |
| ↳ 答案点名真实回撤段 | 0 | **7/8** | 文本含 11.95% 或 6.24% |
| ↳ 拉 issuer brief | 4/5 | **2/8** | 轨迹 |
| **NVDA 四季度增长 ×8** | 假 "not available" | **0/8 假缺席**,8/8 用 `total_revenues` | 轨迹 + 文本 |
| **AAPL vs MSFT 杠杆 ×8** | 用绝对净债 | **8/8 评估了比率族度量** | 轨迹 |

**总债务那条是本批的主结果**:V11 里"答对 ⟺ 走了 `evaluate_formula`"是一条完美相关,而路由是抽签(9/24)。V12 没有改路由逻辑、没有加规则——只是让 `long_term_debt_total` 这一行自己说出 *"a component of what the issuer owes, NOT the total … so a total is composed rather than read off a line"*,并附 `do_not_add_to` 与 `for_a_total_call`。**抽签消失了。**

## 2. 做了什么

### S0(既存缺陷,独立于知识层)

- **法规引证进数值门豁免集**。`C&DI 103.02` 曾被抽成数字 `103.02` 并拒绝——一个论点是"定义随数字旅行,因为监管要求如此"的系统,说不出监管的哪一条。`Item 1A` 漏成 `1`,`Rule 17a-4` 漏成 `17`/`4`。封闭模式,锚在称谓词上(同 `confidence_level`),`103.02%` 与 `$103.02` 仍被检查。
- **`source_url` → `authority` 对象** `{cite_as, url}`。模型曾把裸 URL 拼成 `src_https://www.sec.gov/…` 被拒(`sess_6acc3b20069d`),重写后依据退成 "the issuer panel",并**连带删掉了 `interest_expense_nonoperating` 的替代披露整句**。对象而非拼接串:没有扁平的 id 形状可拼;`Evidence.tsx` 已把任何 `url` 键渲染成链接。**只动 `Formula.source_url`**——`Filing.source_url` 是另一对象上的另一字段。
- **两条 note 去掉举例数字**(GOOGL 的 138.753/40.770、AAPL 的 8.31)。`evaluate_formula` 一直在发 note,两天 42 次;转述即被拒,而拒因读起来像模型的错。测试为全部 16 条守住。
- 顺带 `Formula.family`(S3/S4 需要)。

### K0 期间语义(`describe_issuer` 顶层)

财年末**从年度事实的 `period_end` 推**,不读 `fiscal_year` 列——同一条 NVDA 期间在该列下存了 2026 与 2027 两行。实测:AAPL `Sep 27`、MSFT `Jun 30`、NVDA `Jan 25`、其余 `Dec 31`;**只有 NVDA** 被告知它的财季不对齐日历季。

### K1 指标语义(每条指标)

`kind` · `windows_filed`(仅当多于一种长度)· `do_not_add_to` · `superseded_by` · `do_not_combine_with` · `for_a_total_call` · `note`。**全部来自已有数据**:包含图、公式表的具名替代、`concept_mapping` 的注释、申报期间本身。

### K2 / K3

`family` 与 `unit_class` 进公式清单;已验证示例进**系统提示**(见 §3)。

## 3. 量出来才知道的四件

**① `worked_examples` 不该按发行人发。** 六条示例对每家完全相同,却在每次 `describe_issuer` 里重发 1146 字节——与 `authority` 重复 16 次是同一个毛病。它们是"这台设备怎么用",不是发行人知识,**移进系统提示**,替换掉原第 56 段(发行人原语导览)与第 62 段("why moved" 的顺序)。

**② 目录不该重复注册表散文。** `authority` 是**同一个对象在一个载荷里出现 16 次**(1831 字节),`note` 是每家都一样的 2001 字节。两者随 `evaluate_formula` 走——它一直在发。**这是 V11-T 对面板做过的事,应用到另一个清单工具。**

**③ 规则要发,图不必。** `contains` + `contained_by` + `do_not_add_to` 是同一条信息的三种写法。哪一条是更宽的线由 `for_a_total_call` 回答;调用方唯一要照做的是"这两个不能相加"。**结论留下,图留在 `containment.py`。**

**④ note 只在关系成立时发。** 每条 note 警告的都是一个**关系**。JPM 没有 `cash_and_equivalents`,那条"别把两种现金搞混"的告诫就无物可告——而无关领域知识被实测为**降低**答案质量。

四条合起来把载荷从 18,685 压到 **11,664**(NVDA 最坏),八家全部在 12,000 的 cap 之内,**live 断言**。

## 4. 没达标的一条

**验收判据 6 说系统提示会变短,它没有。** 4,918 → 5,071 字符(1,051 → 1,101 tokens),**+153 字符**。六条示例(带各自的"为什么")比被删掉的两段流程文字长。

诚实的记账:示例若留在载荷里是每次 `describe_issuer` 1,146 字节,近两天该工具被调 127 次;放在提示里是每轮一次。**换了个更便宜的位置,不是变小了。** 判据写错了,不是实现没做到。

## 5. 仍未动

- **G2 投影契约**的其余项(删 `definition`、拆 `computable`)——本批只加语义,未动准确性。`describe_issuer` 的 `definition` 仍在。
- **判断禁令 / 引号外的方法句 / 叙事拉力**——`GAPS.md` 右列,不可机械化。
- **LLY capex 映射**——`test_v11_tag_drift_live` 里唯一的 `unmapped_candidate`,需先对语料验证。
- **换模型实验**——Cube 的配对实验说文档效应大于同档模型选择,本批的 50%→100% 支持这个方向;仍可作为分离 G5/G6 的手段,不急。

## 6. 本批记下的

- **并行 session 抢同一棵树**。执行到 S3 时发现另一个 session 正在实现同一份计划,`definitions.py` 里出现了引用我文件里不存在字段的代码,`describe_issuer` 直接抛 `AttributeError`。**判据是 mtime 与我没写过的措辞**,不是猜。停手、存 patch、请示、按指示回退——没有单方面撤销别人的代码。对方那版里"目录不该重复 `authority`"的判断是对的,采纳了(§3②),按天数区间分桶的写法也比我的就近取整好,一并采纳。
- **偏移量在替换后失效**。用 `re.finditer` 收集位置再逐个 `str.replace`,第二次替换起全错。收集一次、整体重建。
- **测试抓到我自己的两处**:`net_income` 的 note 只陈述事实没说后果(D5 的机械判据抓的);载荷超 cap 6 字节。两条都是先红后改。
