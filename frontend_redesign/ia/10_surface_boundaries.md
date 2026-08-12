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

## 消费者侧不该知道另外两个表面存在

正常路径下不得出现「评委」「答辩」「演示模式」「技术证明」「开发模式」。

唯一例外是 Trust Receipt 末尾那一句「在电脑上查看完整技术证明」——
那是用户主动往下挖，而且它的落点在 Professional，不在手机里继续展开
`digest` / `hash` / raw JSON。
