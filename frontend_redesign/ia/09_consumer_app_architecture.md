# Consumer App 架构与导航契约

消费者侧只有**两个 App Shell**。不是四个页面各一套壳。

```
Consumer
├── Elder App        /elder
└── Family App       /family · /care · /trust   ← 三个文档，一套壳
```

`/` 是门（`entry` shell），不是 App。

---

## 一、Elder App 导航（固定四项）

```
首页    记录    家人    我的
```

只有这一套，不许再出现第五项，也不许某个视口下少一项。

| 格 | panel | 回答什么 |
|---|---|---|
| 首页 | `home` | 今天怎么样 · 下一件是什么 · 怎么让优活帮我 |
| 记录 | `log` | 办过的事（每条可进事务详情） |
| 家人 | `kin` | 谁能帮我、怎么找她 |
| 我的 | `me` | 字号、语速、隐私（普通 App 设置） |

### 首页信息顺序

```
上午好，李叔
今天一切正常
        ↓
下一件  14:00  心内科复诊
        ↓
      Voice Orb        ← sticky，与打字入口一起钉在视口内
   按一下，慢慢说
        ↓
今天  08:00 已服药 / 14:00 复诊 / 20:00 测血压    ← 在 sticky 下方滚动
```

**Orb 不等于整个 App。** 它是生活里的主操作入口，所以位置在「生活状态 → 下一件」
之后、「今天」之前——不是首屏唯一的东西。

**根页面不许有「返回」**，也不需要反复解释「这里是优活办事模式」。用户已经在优活里面。

### 打字退路的硬合同（B Phase Gate）

```
sticky.top                >= header.bottom
typeInstead.bottom        <= viewport.safeBottom
scrollContent.last.bottom >= sticky.top + required_overlap_clearance
没有内容被永久遮住
```

三个数据状态 × 四个视口全量量：
`empty|normal|attention` × `320×568 / 667×375 / 390×844 / 430×932`。

**为什么这条必须是硬合同**：一旦首页真的有待办，
`test_the_typing_route_is_in_the_first_screen_on_every_viewport` 就红了
（实测 320×568 差 139px、667×375 差 306px、两个宽屏被 `button.tab.seg` 盖住）。
现在这套布局**是因为应用是空的才装得下**，而打字是语音失败时唯一的退路
（Firefox 没有 Web Speech、权限被拒、没麦克风、网络差都会失败）。

### Task Space（原 Focus Mode）

> **Conversation engine owns state. Task Space owns presentation.**

Task Space 按后端已有的 `task_status` / `code` / `ui` / `message` 渲染不同视图，
**不许另写 `if localTaskState === …`** 形成第二个前端状态机——否则半年后前后端
状态机会漂移。

四个视图：普通任务 / 歧义 / 等家属 / 完成。聊天记录不是主画面。

它仍然是**态**（`body[data-focus]`）而不是第五个 panel，原因写在三个地方
（`elder.html:116-127`、`elder.js:1021-1033`、`pages.css:302-312`）：
**Voice Orb 只能有一个 `#mic`**，做成并列分区就要复制一个 orb，两个 orb 的状态机
会立刻分叉。

---

## 二、Family App 导航（固定四项）

```
今天    待办    照护    我的
```

**「趋势」退出一级导航**，它住在 照护 里。

| 格 | 回答什么 |
|---|---|
| 今天 | 爸爸今天怎么样 · 有没有需要我拍板的 |
| 待办 | 待我确认 / 进行中 / 已完成 |
| 照护 | 他的照护档案（`/care`） |
| 我的 | 做过的事、凭证入口 |

### 必须消失的双层导航

现在 `/family` 与 `/care` 各有**两层**：顶部 `.segmented` + 底部 `.tabbar`（3 个跨页
`<a href>`）。重构后只剩**一条**底部导航，四项，**页内切换**。

### 照护（`/care`）

object-centered，不是 feature-centered。核心对象始终是「爸爸 / 李叔」：

```
照护
  爸爸  75 岁  今天整体正常
  ├── 健康    血压 128/78  稳定        ›
  ├── 用药    早间已服 · 晚间 20:00     ›
  ├── 活动    今天 2860 步  和平时接近   ›
  ├── 心情    本周总体平稳              ›
  ├── 安全    暂无异常                 ›
  └── 趋势                            ›
```

五个 Segmented Control 退役，改 Overview + Detail。

### 事务详情与 Trust Receipt（`/trust`）

先给凭证，后讲原则。四条原则挪到凭证之后。

**P0 契约**：渲染凭证**绝不允许**创建、推进、批准、执行、重试或修改任何业务事务。
Read UI 必须是 Read。没有数据就说「没有找到这份凭证」。

---

## 三、Shell Contract（不是「看起来一样」）

`/family` `/care` `/trust` 三个文档必须出现同一组结构钩子：

```
[data-shell="family"]
  [data-app-header]
  [data-app-main]
  [data-app-bottom-nav]      ← 永远四项：今天 / 待办 / 照护 / 我的
  [data-app-safe-bottom]
```

Elder 同理，`[data-shell="elder"]`，四项为 首页 / 记录 / 家人 / 我的。

这样浏览器看到的是「同一个 App 的不同 deep link」，而不是「三个网页用了同一套颜色」。
`.family-app`（`family.html:38`）在四层 CSS 里**零命中**，是死类名，回收成 shell 钩子。

两个 Shell 必须共享：顶部安全区 · 页面标题语法 · 底部导航 · Sheet · Modal ·
事务详情 · 空态 / 错误态 / 加载态 · 排版 · 图标族 · 动效语言。

---

## 四、重构时的两个已知陷阱

### `pages.css` 的 `.tabbar:not(.elder-tabs){display:none}` 会失效

Family 变成页内 tab 之后，「是不是 `.elder-tabs`」不再等于「是不是页内导航」，
宽屏下 Family 的 tab 会**整条消失**。判据必须换成「跨页 vs 页内」。

**这个坑出过一次**：`pages.css:2295-2312` 用 18 行记着代价——
800×1200 与 1360×900 下四个 tab 命中 0 个、`[data-section]` 可见控件 0 个，
连手写 `location.hash='#me'` 都打不开，而受影响的页面里有语速与字号两个无障碍控件。

### `data-nav="tabbar"` 一个属性绑三条规则

`pages.css:1789` 底部让位内边距、`:2271`/`:2282` 藏 back-link、`:2319` 宽屏恢复。
`trust.html` 现在**没有**这个属性，加上会第一次继承到 76px 的幽灵空白——
而 `pages.css:1785-1788` 的注释正是为了去掉那段空白才把判据从 `:not(.app-frame)`
改成 `data-nav` 的。
