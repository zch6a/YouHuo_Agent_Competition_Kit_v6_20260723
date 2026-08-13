# 表面边界契约

> **Surface describes user intent, not URL.**

七个 URL 保留不变，但它们**不再等于**七个一级产品页面。这一条是这次重构的地基，
写在最前面是因为它最容易被下一个人写回去。

---

## 五层模型

```
Route  →  Surface  →  Shell  →  Module  →  Panel
```

| Route | Surface | Shell | 说明 |
|---|---|---|---|
| `/` | consumer | entry | 门。它可以点名另外两个表面，那是它的职责 |
| `/elder` | consumer | elder | Elder App |
| `/family` | consumer | family | Family App 根 |
| `/care` | consumer | family | Family App 的 Care 模块（deep link） |
| `/trust` | consumer | family | 事务详情里的 Trust Receipt（deep link） |
| `/stage` | presentation | stage | Guided Product Presentation |
| `/judge` | professional | evidence | Audit & Evidence Platform |

举两个完整的例子：

```
/trust  →  consumer      →  family    →  transaction        →  receipt
/judge  →  professional  →  evidence  →  transaction audit  →  timeline
```

**唯一事实源**：`backend/youhuo/surfaces.py` 的 `SURFACES`。
`test_surface_registry.py` 钉住它和 FastAPI 真正注册的路由、以及每一页
`<body data-surface>` 三者一致。

---

## 禁止事项

### ① 不许把 `URL == Surface` 写回测试里

`/family` `/care` `/trust` 是**同一个 Surface、同一个 Shell** 的三个 deep link。
任何按 URL 分组的断言都会在下一次搬迁时给出错误答案。按 `surface_of(page)` 取。

### ② 一个功能只能属于一个主表面

同一件能力可以在三个表面**各有一个视图**（一笔缴费在 Consumer 是凭证、在
Presentation 是一拍、在 Professional 是一条证据链），但它的**主场**只有一个。
判据写在 `11_control_inventory.json` 的 `surface` 列，由清单脚本从页面推导。

### ③ Consumer 侧只允许两个 App Shell

`elder` 与 `family`。`entry` 是门不是 App，可以并存。
第三个 App Shell 出现时 `test_the_consumer_surface_has_exactly_two_app_shells` 会红。

### ④ 手机框里不许有工程词，框外必须有

判据是 **shell**，不是 surface：`index.html` 也是 `consumer`，但它的 shell 是
`entry`，是门。门可以写「演示与可信技术 →」，那不是工程词泄漏，那就是边界本身。
但豁免有结构边界——那些字只许出现在 `.landing-demo` 里，
`test_the_entry_page_only_names_other_surfaces_in_the_doorway` 守这一条。

反向也要成立：框外三页**必须**有那些词，否则说明工程内容被删掉了而不是搬走了。

---

## 为什么保留七个 URL

替代方案是把 Family 合成单文档、Care 与 Receipt 变成它内部的视图。那样更接近原生
App 的心智模型，但代价是：

- **必须重写 `initSections`**。它现在是 `document.querySelectorAll` + **平坦命名空间**
  （`common.js:428-429`），而 `family.html` 与 `care.html` **都有
  `data-panel="today"`**。合进一个 DOM 会同时显示两个面板、两个 seg 同时高亮，
  而且**不报错、截图也看不出来**。
- `resolve()` 的 id 兜底（`common.js:443-445`）会把 Care 内部的深链解析成外层 panel。
- 还要改 `sw.js` 的 SHELL、CSP 逐条检查、以及散在 8 个文件里的路由清单。

所以选「三文档共享壳」：URL 不变，`sw.js`、CSP、路由清单一行不动，
而对用户仍然是同一个 App。代价是壳必须靠契约保证一致，见 `09_consumer_app_architecture.md`。

---

## 三个表面的密度与语域

| | Consumer | Presentation | Professional |
|---|---|---|---|
| 读者 | 老人、家属 | 评委、客户、合作方 | 专业审计者 |
| 密度 | 2–4 | 3–5 | 6–8 |
| 语域 | 生活话 | 讲故事 | 精确、技术 |
| 允许出现 | 只有产品 | 叙事 + 真实 App + 当前含义 | 审计链、安全决策、Authority、API、Runtime |

品牌 DNA 三者一致（logo、蓝、暖纸、墨、图标几何、字体哲学、Voice Orb、Trust Receipt、
动效哲学），**密度必须不同**。整个项目一套密度是当前失分的根因之一。

---

---

## 同一个事实，两个**模型**，不是一个视图加过滤器

依据：Folk Care（`12_reference_study.md` 第四节 ⑥）与 MedCore（第五节 ⑨）
在这一点上独立得出同一个做法。

Folk Care 有两个实体，同一个事件写两条记录：

| | 取证 | 叙事 |
|---|---|---|
| 类型 | `AuditEvent`（`packages/core/src/audit/audit-service.ts:9`） | `ActivityFeedItem`（`:230`） |
| 字段 | `eventId` `userId` `eventType` `resource` `resourceId` `action` `result: SUCCESS\|FAILURE` `ipAddress` `userAgent` | `activityType` `title` `description` `summary` `performedByName` `occurredAt` `iconType` `viewedByFamily` |
| 谁能看 | 只有 `audits:view` / `AUDITOR`。**家属门户下没有任何审计路由** | 按接收人物化，自带显示提示 |

MedCore 的 `/status`（公开、244 行、无鉴权、注释「No dashboard chrome」）
与 `/dashboard/observability`（仅超管、792 行、完整外壳、`p95DurationMs`、
慢端点排行）**读同一张维护窗口表**，呈现完全分叉。
它还有一个更精确的先例：患者账单页**自己重算**一个 `OVERDUE` 徽章
（`patient/bills/page.tsx:133-146`），而不是显示员工那边的原始 `daysOverdue`
整数（`dashboard/billing/page.tsx:776-783`）——
**消费者面显示的是结论，不是让人自己算的中间量。**

### 优活现在做的正是被避开的那件事

已核实：`trust.js:223-224` 取 `/v2/audit?limit=200`，然后在浏览器里
`.filter(e => e.entity_id === taskId)`——**消费者凭证是把取证审计日志拉到前端
过滤出来的**。后果不止于词汇：

- 那个 200 条的窗口会让**较早的事务链被截断**，凭证静默丢事件
- `trust.js:187-188` 硬过滤 `task_type === 'bill_payment'`，
  挂号和用药**永远出不了凭证**

**定下来的边界：**

```
/trust   叙事形状   后端在事件产生时同时写出「给人看的那一条」
/judge   取证形状   审计链原样
```

`/trust` 因此**不再需要 `/v2/audit`**。这是 Phase E 的一条硬要求，
它同时解掉「200 条窗口截断」和「凭证词汇是工程词汇」两个问题。

### 什么留在手机上，什么只在 `/judge`

| 留在手机 | 只在 `/judge` |
|---|---|
| 一个带文字标签的结论 | 等宽的实体 ID |
| 用人话说的参与方（她、家人、自来水公司） | 操作者身份与邮箱、IP |
| 人类可读的时间 | 精确时间戳、分组件延迟 |
| 接下来会怎样 | `details` 的**前后载荷** |
| 一个刷新/重看的入口 | 留存与覆盖统计、CSV 导出、按操作者/日期/全文筛选、跨记录跳转 |

已有的那句「在电脑上查看完整技术证明」是两者唯一的接缝，保留。

### 一条必须说清的话：字段分叉**不是**安全边界

MedCore 没有字段剥离层——`apps/api/src/routes/billing.ts:711-733`
按 `role === "PATIENT"` 只收窄**行**，而 `include` 对两类读者**逐字节相同**。
字段的分叉完全活在前端。

对优活也是一样（同一个后端、两套模板），这是可接受的。
**但不许把它描述成一个安全边界，因为它不是。**
真正的边界是鉴权与行范围，那在后端。这份文档现在的写法没有这个错误，保持。

---

## `/stage` 与 `/judge`：内容和它们的角色现在是**反的**

实测（`12_reference_study.md` 第六节 ③）：

| | `data-beat` 拍数 | id 数 | 标题里是什么 | 实际是什么 |
|---|---|---|---|---|
| `/stage` | **0** | 69 | 看哪一端 · 演示台词 · 视口 · 舞台 · 场景注入 | **一个导演控制台** |
| `/judge` | **7**（01–07） | 22 | 她开口 · 听不清就不猜 · 一次只问一件事 … | **一段有引导的叙事** |

两页相似度 9.1%、同名 id 0 个，所以**不是**两份拷贝——是内容长错了地方。

上面五层模型那张表的 `Route → Surface` 映射**没有错**，错的是内容的落点：

```
七拍叙事      /judge  →  /stage 的 Presentation View        （搬，不删）
导演控制台     /stage  →  /stage 的 Director Controls（默认收起）
事务工作台     新建     →  /judge                          （Timeline / Evidence / Decision Context）
```

满足「不得 Silent Delete」：七拍不是被删掉，是搬到它该在的表面。

另外两条实测更正，Phase F/G 按这个走：

- **KPI 行不存在。** 在整个 `backend/static` 里搜 `1217` / `KPI` /
  `PWA Ready` / `Runtime Healthy`：**零命中**，早就整个移除了。
  计划书说要把它挪到 System 页，没有东西要挪。
- **可见的比赛词汇总共 6 处**：`/stage` 评委×2 答辩×2，`/judge` 评委×1 评分×1。
  五个消费者面**零命中**。源码里 `judge` 有几百处命中，但那些是类名、id 和注释。
  缺的不是工作量，是**闸门**：现有闸门管「消费者面不许有工程词」，
  没有闸门管「任何产品面不许有比赛词」。

---

## 三个表面允许共享什么 CSS

MedCore 的依赖图就是它的设计文档（实测）：

| App | `@medcore/db` | `@medcore/shared` |
|---|---|---|
| `apps/api` | 有 | 有 |
| `apps/web` | 无 | 有 |
| `apps/mobile`（患者端） | **无** | **无**（28 个依赖里零命中） |

而且是刻意的：`apps/mobile/app/ai/triage.tsx:26` 写着
"The mobile workspace intentionally does NOT depend on `@medcore/shared`"。
**消费者 App 除了 HTTP 契约什么都不共享。**

**解决的问题**：消费者面一旦和专业面共用一套组件库，它就会不可避免地朝专业面的
样子漂移。只共享线上契约，让「分开」成为默认，而不是靠纪律维持。

**而 MedCore 自己破了这条规则，这是最有用的部分。**
`apps/web/src/app/patient/_components/PatientLayoutShell.tsx:87-97`
给除三条路由之外的**每一条患者路由**套上了 `<DashboardLayout>`，
于是患者看到**员工的侧边栏**，过滤成 11 项、**其中 5 项指回 `/dashboard/*`**。
这不是设计决定，是疏忽——而它证明这件事**会因为疏忽而发生**。

优活的规则：

```
tokens.css        三个表面共享（颜色、间距、字阶的原语）
base.css          三个表面共享（重置、可访问性基线）
components.css    ⚠ 卡片 / 表格 / 徽章 / 抬头的类**不许**跨表面共用
pages.css         按表面分节，互不引用
```

品牌 DNA 靠 `tokens.css` 保证一致；**密度靠 `components.css` 分开**。
整个项目一套密度是当前失分的根因之一，而共用组件类正是它的来源。

反过来，MedCore **守住**的那一层值得抄：`patient/manifest.ts` 是**自己的**
manifest（`scope: /patient`、主题色与根不同），`public/sw.js:4` 给 SW 划了
scope，注释说它「不拦截员工 dashboard 的请求」。
**优活要检查 `sw.js` 的 scope 有没有把 `/judge` 的请求也管起来**——
优活只有一个 manifest（`start_url: /elder`），而 `/judge` 属于另一个表面。

---

## 消费者侧不该知道另外两个表面存在

正常路径下不得出现「评委」「答辩」「演示模式」「技术证明」「开发模式」。

唯一例外是 Trust Receipt 末尾那一句「在电脑上查看完整技术证明」——
那是用户主动往下挖，而且它的落点在 Professional，不在手机里继续展开
`digest` / `hash` / raw JSON。
