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

#### 「我的」里每一行都要说清它的**后果**，不只是名字

来自实测 Medito 的 `RowItemWidget`（`12_reference_study.md` 第二节 ⑦-b）。
它的开关行长这样：

```
Do Not Disturb          ← 粗体标题（名字）
Silence all alerts      ← 小一号、暗一档（后果）
                    [开关]
────────────────────    ← 发丝线，左端与文字对齐，不通栏
```

**一个开关的后果不是自明的。** 「语速」是名字，「优活说话会慢一些」才是后果。
老人端尤其需要这一行——她不该靠拨一次开关再观察来推断它做了什么。

#### 已做完

先更正我自己写错的一处：这一节原先列了三个控件，把「隐私」也算成一个。
核实过——「我的」里**只有两个可调控件**（`#speechRate`、`#fontScale`），
第三块「优活怎么保护您」是一组**只读徽章**，不是控件，不在这条规则里。

| 控件 | 名字 | 后果那一行 |
|---|---|---|
| `#speechRate` | 语速 | 选「慢」的时候，优活会一字一句地说 |
| `#fontScale` | 文字大小 | 屏幕上的字会变大，按钮也跟着变大 |

语速那一句不写成「优活说话会慢一些」：它是三选一（慢 / 舒适 / 正常），
不是一个开关，所以要说**选某一项会怎样**，而不是把一个取值当成整个控件的后果。

结构上文字先包一层 `.tool-text`（名字 + 说明两行），再和控件并排。
必须包这一层，否则 `label` 从两个孩子变三个：flex 会把说明行排到 select 旁边，
而 `.rail` 那条 `grid-template-columns: 76px 1fr` 会把它甩进 76px 的窄格里挤成
一条竖字。那个 76px 是「语速」两个字的宽度，现在改成 `1fr auto`。

**320 宽以下控件掉到文字下面**。并排时 select 占 108px + 12px 间距，文字块只剩
124px，实测两句话都折成三行且**末行只剩一个孤字**（「说」/「大」）。掉下来之后
文字块拿到整幅 238px、两句各一行，select 顺便变成整行宽、触摸目标更大。

那条 `@media (max-width: 360px)` 里**必须把 `.rail .profile-tools label` 再写一遍**：
media query 不增加特异性，而 `.rail` 那条是 (0,2,1)，只写 `.profile-tools label`
的 (0,1,1) 盖不住它——侧栏里会保持并排，而那正是最窄的上下文。
（这个项目在「规则的位置决定它生不生效」上咬过四次，`.tab-icon` 连错两回。）

实测三个视口确认规则落在该落的地方：

| 视口 | 说明行高 | 控件宽 | 布局 |
|---|---|---|---|
| 320×568 | 22px（单行） | 238px | 掉到文字下面 |
| 390×844 | 45px（两行） | 108px | **仍然并排** ← 规则没越界 |
| 900×900 | 22px（单行） | 108px | 并排，未受影响 |

三个视口横向溢出都是 0，select 高度全部 48px（项目触摸地板），
说明行 14px / `--ink-3`（复用 `.meta`，对比度已过零容差闸门）。

闸门 `test_settings_rows_say_what_they_do.py` 四条，其中一条判
**说明不能只是名字的复述**——「语速」配「设置语速」能让「有没有说明」那条变绿，
所以判据是「去掉名字里的字之后还得剩够一句话」。变异证明七项。

分隔线用**缩进**的（左端与文字对齐），不要通栏——通栏的线把列表切开，
缩进的线让它读起来是分组。这一条还没做。

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

#### 三者的关系（来自 MediMate 的结构，不是它的视觉）

MediMate 是一个 voice-first 健康助手，它的底部导航中间那一格叫 `Voice`，
而 `component={EmptyScreen}`，注释是 `// Placeholder — Voice tab never renders
a screen`（`mobile/App.tsx:24-25` `:152-185`）。按下去打开一个挂在
`NavigationContainer` **外面**的 modal（`:199-203`），关掉之后你还在原地。

**Voice 坐在拇指预期的位置，但按下去不导航。它是动作，不是目的地。**

而 `Chat` 是**另一个独立的 tab**（`:187`）。代码规模也说同一件事：
**ChatScreen 是整个 App 最小的屏，120 行**，而 TimelineScreen 268 行、
ProfileScreen 338 行。一个自称 voice-first 的产品里，聊天界面是最不发达的那块。

所以优活三者的关系定成：

```
Voice Orb    动作。不占 tab，在首页内容流里。用完归位
Task Space   语音之后 App 的状态。是「这件事本身」，不是聊天记录的替代品
聊天记录      一个可以去看的地方——「记录」下的一条入口，不是主画面
```

优活的 Orb 不在 tab 里，这比 MediMate **更对**：它占了一个导航格却不给屏幕，
无障碍树里因此留下一个可聚焦、却什么都不渲染的 tab。

**另一条要 ADOPT**：MediMate 的 `Nutrition` 是一个 `tabBarButton: () => null`、
宽度 0 的隐藏目的地，注释写着 `navigable via voice, hidden from tab bar`
（`:190-195`）。**语音能到达导航栏里没有的地方**——底部导航最多四五项，
而语音的表达空间没有上限。

推论：老人说「上个月的水费交了没」应当能直接落到那笔事务的详情，
即使「事务详情」不是四个 tab 中的任何一个。这给 `.log-item` 补了一条动机——
**语音要能指向它，它就必须可寻址。**

核实过：`.log-item` 在 `elder.js:867-895` 的 `loadActivity()` 里，
行是由 `entry.who` / `entry.happened_at` / `entry.what` 拼出来的一个纯 `<div>`
（`:871-885`），**没有链接、没有 task_id、没有点击处理**。

#### 那个详情面在哪：**压在四个 tab 之上的一层，不是跳去 `/trust`**

这是计划书没做过的一个决定，而它是 `.log-item` 可寻址的前提。

原计划写的是「记录 → Transaction Detail 入口」，但没说那个 Detail 在哪。
按 `surfaces.py`，`/trust` 是 `consumer / family`——**家属壳的一个 deep link**。
让老人点一行记录跳到家属页面是表面越界：她会拿到家属的导航、家属的语域，
以及一页她不需要的原始记录。

三个参考产品独立给出同一个形状：

| 产品 | 做法 |
|---|---|
| Medito | 详情页 push 到**同一个栈**上、压在 tab 之上；实测 Pack 详情页的出口在**底部**操作栏，不在左上角 |
| MediMate | `Nutrition` 是 `tabBarButton: () => null`、宽度 0 的**隐藏目的地**，注释写着 `navigable via voice, hidden from tab bar` |
| Folk Care | 现场护理员四个 tab 固定不动，~10 个任务屏压在**栈**里——「导航宽度编码角色，任务深度不进导航」 |

所以定成：

```
Elder App
├── 四个 tab（首页 / 记录 / 家人 / 我的）—— 永远四项，不增第五项
└── 事务详情 —— 压在 tab 之上的一层
    ├── 从「记录」点一行进入
    ├── 语音也能直接到达（「上个月的水费交了没」）
    └── 出口在**底部**，拇指可达
```

**出口必须在底部**，这不是风格问题。实测 Medito 的 Pack 详情页把返回放在底部
操作栏，而它的 `MeditoAppBarLarge` 明明有左上角箭头——同一套设计系统两种做法并存，
说明「出口在哪」在它那儿没有规则守着。而**75 岁单手持机的人碰不到左上角**；
再加上优活是 `display: standalone` 的 PWA、iOS 下没有系统返回手势，
这一层没有底部出口就是死路。

**不做成第五个 tab**，也不做成第二个 `body[data-focus]` 那样的态：
Task Space 之所以是态而不是 panel，原因是 Voice Orb 只能有一个 `#mic`（见下）；
而事务详情不含 orb，它是内容，做成一层覆盖就够。

#### 前提已经做完：每一行有了地址

地址本来就在后端手里——`api.py` 的 `entity_belongs_to_elder(event.entity_id)`
拿 `entity_id` 做权限过滤，**然后丢掉**。

已加 `ElderActivityEntry.about_id`（`models.py`），由 `privacy.py` 的
`elder_activity_entries` 填充。实测 6/6 条都带上了主体，全是 `task-*`。

名字不叫 `entity_id`：审计那边叫 `entity_id`，而这个模型是同一份事实的
**叙事投影**——两侧本来就该用不同词汇（Folk Care 的 `AuditEvent` 与
`ActivityFeedItem` 是两张表，同一事件写两条记录）。混用会让人以为它们可以互换。

**它还暴露并修掉了一个缺陷**：去重原先只比 `what` + `who`，而
`_ELDER_ACTIVITY_TEXT` 是每个事件类型一句**固定**的话——两笔不同的事务只要同一
步骤被相邻记录，第二笔就安静消失。验证过：旧判据把
`['task-second', 'task-first']` 折叠成 `['task-second']`，`task-first` 整条不见。
现在 `about_id` 参与比较。`test_elder_log_rows_are_addressable.py` 五条守着，
其中一条守反面——**同一笔事务重试仍要折叠**，否则一次重试会变成三行同样的话，
而去重本来就是为这个存在的。

**这一层本身还没做，`about_id` 只落到了后端。** 前端暂不加那个 `dataset` 属性：
目的地还不存在，造一个点了没反应的控件比暂时不造它更糟。

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

Folk Care 犯过**同一个错**，值得记下来：它的家属侧边栏退化成 1 项
（`FamilyPortalLayout.tsx:18-20`），于是真正的导航搬进了 dashboard 上的四个
`QuickLinkCard`（`FamilyDashboard.tsx:108-134`）——**凭空长出隐藏的第二层导航**。
删掉顶层 `.segmented` 之后，不许让它以「首页上的四个入口卡片」的形式复活。

**导航定义一次。** 四项写成一个 JS 数组，由一个共享函数渲染进三个静态文档。
数组住在 `.js` 文件里，不违反严格 CSP，也不需要构建步骤。
Folk Care 的三套导航（Professional 14 项、Family 1 项、现场 4 项）全都是
声明式数据数组而不是 markup——这就是为什么它三个角色的壳不会互相污染。

### C/D Phase Gate：四个入口的行为必须一致

这一条是 Phase C 与 D 的**前置条件**，不是收尾项。依据在
`12_reference_study.md` 第一节。

Medito 的四个 tab 是 `IndexedStack`（`bottom_navigation_bar_view.dart:149`）——
四个页面同时活着，切 tab 只换显示哪一个，滚动位置和已加载数据全部保留。
**那个 App 实例从头到尾没有被销毁过，这才是「不像一组独立网站」的机械原因。**

优活按现在的计划会得到：

```
今天  → family.html 内切面板    瞬时
待办  → family.html 内切面板    瞬时
照护  → /care 文档加载          白闪、滚动归零、状态丢失
我的  → family.html 内切面板    瞬时
```

**四个入口里三个一致、第四个不一致。** 上面那份 Shell Contract 让三个文档
**长得一样**，它对「白闪、滚动归零、状态丢失」一件都没解决。

不走「四项全部文档内」，因为 `10_surface_boundaries.md:70-78` 已用证据否决
（`initSections` 是平坦命名空间，`family.html` 与 `care.html` **都有**
`data-panel="today"`，合进一个 DOM 会同时显示两个面板且**不报错**）。

所以走第三条路：**把那一次跨文档做成察觉不到**。三个可测判据：

```
① 首屏 HTML 里底部导航的当前项已经正确
   —— 服务端渲染进 class + aria-current，不许靠 JS 加载后补
   判据：禁用 JS 取 HTML，当前项的 aria-current 已在
② 跨文档之后模块与滚动位置被恢复
   —— pagehide 写 sessionStorage，首屏读
   判据：/family 滚到 y>200 → 去 /care → 回 /family，y 差 < 8px
③ 壳从 Service Worker 缓存直出，不等网络
   判据：离线状态下四项互跳，壳的首次绘制 < 200ms
```

判据 ① 现在**已经成立**：`family.html:151` 的 `.tab.is-current` 和
`aria-current="page"` 是写死在 HTML 里的。② 和 ③ 是新工作。
②「跨文档恢复上次位置」直接照抄 Medito——
`bottom_navigation_bar_view.dart:39-41` 把上次的 tab 存进 SharedPreferences
并在启动时恢复，而且刻意**不恢复到设置页**（`saved <= 1 ? saved : 0`）：
设置是你去一趟的地方，不是你待着的地方。优活的「我的」同理。

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

#### 家属读到的**不是**同一份数据渲染得薄一点

这是 Folk Care 最可迁移的一条（`12_reference_study.md` 第四节 ④）。它有两个实体：

| | 专业侧 | 家属侧 |
|---|---|---|
| 实体 | `care_plans` 表 | `CarePlanProgressReport`——**另一个实体** |
| 字段 | `plan_number` `physician_id` `authorization_number` `compliance_status` `version` | `reportPeriodStart/End` `reportType` `goalsAchieved` `goalsAtRisk` |
| 性质 | 运营与法律记录 | **三个叙事字段**：`overallSummary` `concernsNoted` `recommendationsForFamily`（`verticals/family-engagement/src/types/family-engagement.ts:392-394`） |
| 署名 | — | `preparedBy` `preparedByName` `publishedAt`（`:397-399`） |

**家属不该读一份运营记录然后自己推断含义。由专业方撰写并发布一份解释，
署名、注明日期。**

#### 核实之后：优活的 `/care` 已经做到了大半，缺的只有两项

我一开始按计划书写成「`/care` 正是被否决的那种做法——把原始指标渲染得薄一点」。
**读代码之后这句话是错的**，改掉它，否则 Phase D 会去重建一个已经存在的东西。

`care.js:80` 读 `/v7/daily-report/{elderId}`，然后（`:83-165`）渲染的是：

- **结论句在最前**：`report.overall` 判定 + `report.headline`，
  而且判定色**由后端给，不由前端猜**（`:83` 的注释就是这么写的）
- 三个固定分项（作息 / 活动与交流 / 用药），每项带自己的判定词；
  **药丸只留给「和平常不一样」的那一项**，一致的用中性小字（`:99-110`）——
  视觉预算给偏离，这个决定是对的
- 办事进度四个计数：今天要办 / 已经办好 / 等您点头 / 已经超时（`:121-126`）
- **`需要您做的：`** + `report.suggested_for_family`（`:134-140`），
  空列表时明确说出「今天不用您操心。」（`:142`）
- **「这份日报不包含什么」** + `report.privacy_note`（`:160-161`）

逐字段对 Folk Care：

| Folk Care | 优活 `/care` | |
|---|---|---|
| `overallSummary` | `report.headline` + `report.overall` | 已有 |
| `recommendationsForFamily` | `report.suggested_for_family[]` | 已有 |
| `goalsAchieved` / `goalsAtRisk` | `report.errands` 四个计数 | 已有等价物 |
| `reportPeriodStart/End` | `report.day`（单日） | 有，是单日不是区间 |
| `concernsNoted` | 散在 `section.verdict != 'typical'` 里 | **部分有，没有汇总** |
| `preparedBy` / `preparedByName` | — | **缺** |
| `publishedAt` | — | **缺**（`report.day` 是哪一天，不是生成时刻） |

反过来，优活有一样 Folk Care **没有**的东西：**`privacy_note`**。
一份摘要主动声明自己不包含什么——这比 Folk Care 里任何东西都更贴合
「可信」这个主张，保留并且在 `/judge` 上说出来。

**所以 Phase D 在这一块的真实工作只有三件**（不是重写）：

1. 补**署名与生成时刻**。撰写者是 Agent，那就署 Agent 和生成时间。
   这和 DemoClock 是一套东西：**一个结论必须能追到它是什么时候、由谁下的。**
   没有署名的摘要在一个讲可信的产品里是自相矛盾的。
2. 把散在分项里的偏离**汇总成一条「需要注意」**。现在家属要自己扫三个分项
   才知道哪一项不对——Folk Care 把 `concernsNoted` 做成独立字段，
   正是因为「看完不知道要不要担心」是这类页面的默认失败。
3. `report.day` 是单日。周/月小结要不要做是另一个决定，这一轮不动。

下面这个形状是补齐之后的样子，不是从零新建：

```
照护
  爸爸  75 岁
  ┌──────────────────────────────────────────┐
  │ 本周小结            8 月 6 日 – 8 月 12 日 │
  │ 整体平稳。用药一次没漏，活动量和上周接近。   │
  │                                          │
  │ 需要注意            血压有两天偏高（周三、  │
  │                     周五早上），都在 140 上下│
  │ 你可以做什么        周末问一句他那两天是不是 │
  │                     没睡好                │
  │                                          │
  │ 由优活整理 · 8 月 12 日 09:00              │
  └──────────────────────────────────────────┘
  ├── 健康 · 用药 · 活动 · 心情 · 安全 · 趋势   ›
```

三件事是硬要求：

1. **「需要注意什么」和「你可以做什么」是两个显式字段**，不是藏在一段散文里。
   Folk Care 把它们做成 `concernsNoted` 与 `recommendationsForFamily` 两个字段，
   正是因为「家属看完不知道要不要做什么」是这类页面的默认失败。
2. **必须有署名和生成时间。** 优活的撰写者是 Agent 而不是护士，那就署 Agent
   与生成时间。这和 DemoClock 是一套东西：**一个结论必须能追到它是什么时候、
   由谁下的。** 没有署名的摘要在一个讲可信的产品里是自相矛盾的。
3. **没有数据时说没有，不要生成一份读起来像真的摘要。**
   Folk Care 这一条的实现是个门面——`CarePlanPage.tsx:24-121` 硬编码了四个目标、
   叙事文本和三人护理团队（假邮箱假电话），标着 `// Mock care plan report data`。
   **模式是对的，实现是编的。** 优活的 `empty` 数据态必须走真的空态。

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

## 四、状态、错误与出口

两个 Shell 共享这一整节。依据在 `12_reference_study.md` 第二节。

### ① 每个数据区块走一次穷尽的三态分支

Medito 每个屏顶部是一次穷尽分支（`home_view.dart:99`）：

```dart
home.when(loading: …, error: …, data: …)
```

**解决的问题**：空态 / 加载 / 错误散在页面各处的 `if` 里，一定会漏一个。
这里三态是一次穷尽的分支，类型系统不允许少写。

优活是纯 JS，没有类型系统兜底，所以靠**调用约定加闸门**：
每个取数落点必须经过一个 `renderState(host, {loading, error, empty, data})`，
闸门断言每个 `await api(...)` 的渲染落点都走它。
`task-space.js` 的 `viewKindOf` 已经是这个形状（认不出回 `null`，
由调用处退回聊天视图，**不猜**），把它推广开。

**「空态掩盖布局问题」在这个项目里出过三次以上**——三态里最容易被跳过的
恰恰是空态，而它是唯一一个「什么都不做就会得到」的状态。

### ② 加载超过 3 秒，降级成一个提议

Medito 的注释把设计意图写清楚了（`home_view.dart:229-232`）：

> If loading drags on … a subtle "Go to Downloads" escape hatch fades in so
> downloaded sessions stay reachable. A normal load resolves before the button
> ever appears.

实现是 3 秒后 `setState` 显示按钮、`AnimatedOpacity` 500ms 淡入（`:246-248`）。

**解决的问题**：转圈本身不携带信息。转到第 20 秒时用户只剩下杀掉 App 这一个选择。

优活的落点是 `/care` `/family` 的数据区块与家属端的审批流：3 秒后露出
「先看看昨天的记录」这类仍然走得通的路。老人端首页不适用，
因为打字入口本来就是常驻的（那是语音失败唯一的退路）。

### ③ 错误至少分四型，每型给不同的可走动作

Medito 分了七型，每型一句自己的话（`medito_error_widget.dart:36-51`），
而且**动作按型分叉**（`:133`）：认证类给「重试 + 重新登录」，
其余给「重试 + 去已下载内容」。**错误页不是死路，它把你送到仍然能用的那部分。**

`:26` `:74-78` 的 `isScaffold` 开关让同一个组件既能整屏、又能内嵌在已有页面里——
**一个区块失败不掀掉整个壳。**

优活现在是一条通用兜底文案。最少分这四型，每型配一个仍然走得通的动作：

| 型 | 老人端说什么 | 还能做什么 |
|---|---|---|
| 没有网 | 家里网不通 | 我先用之前记下的说给您听 |
| 超时 | 这次等太久了 | 再试一次 / 打字告诉我 |
| 这条记录不存在 | 没有找到这份凭证 | 回到记录 |
| 服务器出错 | 我这边出了问题 | 再试一次 / 找家人 |

老人看不懂「加载失败」，但看得懂「家里网不通」。
**这一条不是文案润色，是四条不同的出路。**

#### 而现状比「一条通用兜底」更糟：它把原始异常给她看

核实到两处：

```javascript
// elder.js:863   待办列表
catch (e) { remindersEl.textContent = `待办加载失败：${e.message}`; }
// elder.js:894   记录列表
catch (e) { activityLogEl.textContent = `记录加载失败：${e.message}`; }
```

`e.message` 是**原始异常信息**——`Failed to fetch`、`Unexpected token < in JSON at
position 0`、`HTTP 500` 之类，直接进了一位老人读的那一行字。

这同时暴露了一个闸门的洞：`test_app_surface_speaks_no_engineering.py` 扫的是
**静态文件里的字面量**，而 `${e.message}` 是一个模板——它运行时装进来什么，
静态扫描无从得知。**消费者面不许有工程词这条规则，在运行时是没有闸门的。**

修法不是把 `e.message` 删掉（那会让排查变瞎），而是分型：
按型给她看那四句话，把 `e.message` 留给 `console.error` 和审计。

#### 已做完（`common.js` 的 `errorWords`）

`window.YouHuo.errorWords(error, subject)` → `{kind, say, then, text}`。
五型：`offline` / `notfound` / `server` / `unknown`，外加 `backend`
（后端在 `data.detail` 里写好了中文，原样放行——**不是所有 `e.message` 都该拦**）。

分型的钩子本来就在：`api()` 对 HTTP 失败抛的 Error 带 `.status`，
而 `fetch` 自己失败时抛的 `TypeError` 没有。另外接了 `navigator.onLine`——
`elder.js` 的 `send()` 里早就有 `navigator.onLine === false ? 'offline'` 这一行
用来决定屏幕停在哪一态，**判断做过一次，只是没用在说给她听的那句话上**。

改了 **9 处**（手工排查只找到 8 处，第 9 处是闸门抓出来的）：
`elder.js` 四处（含主聊天路径 `send()` 的 catch，原文案是「系统暂时不可用」——
她自己家里断网时说的是我们坏了）、`family.js` 三处、`care.js` 两处
（含 `failed()` 助手）、`trust.js` 一处（**原先连前缀都没有**）。

闸门：`test_consumer_errors_are_typed_not_raw.py`，11 条。
判据按 **catch 绑定的变量名**做花括号配对——`data.message` 是后端写的人话、
到处在用且完全正当，按 `\.message` 一把抓会得到几十个假阳性，
然后这道闸门会被放宽或删掉。变异证明 12 项：四个必须抓到的（重新泄漏 / 少一型 /
丢掉 `then` / 文案里混英文）、两个必须放行的（`data.message` 在 catch 外、在 catch 内）。

运行时实测（走 CDP，四个页面 0 控制台错误）：

| 输入 | kind | 屏幕上的话 |
|---|---|---|
| `TypeError: Failed to fetch` | offline | 待办暂时看不了：家里网不通。等一下我再试试 |
| 404 | notfound | 待办暂时看不了：没有找到这一条。回到记录看看 |
| 503 | server | 待办暂时看不了：我这边出了点问题。过一会儿再试 |
| 409 + `detail` | backend | 这笔已经由家人处理过了 |
| `请求失败（403）` | unknown | 待办这一步没成。再试一次 ← **状态码被换掉** |

**`/` 不在这套里，而且是对的**：`landing.js` 40 行、不加载 `common.js`、
不发任何请求，三个 `catch (_)` 都是隐私模式下的存储守卫。
门厅不取数据，就不需要错误词汇。

### ④ 详情面必须有出口，且出口跟着来路变

Medito 的 `MeditoAppBarSmall` 声明了 `hasBackButton`、`hasCloseButton`、
`closePressed` 三个参数，而 build 里是 `leading: null,
automaticallyImplyLeading: false`（`medito_app_bar_small.dart:31-32`）——
**三个参数全是死的，这个头部根本不渲染返回按钮**，详情页完全依赖系统手势。

**优活不能照抄，因为优活是 PWA。**
`manifest.webmanifest:10-11` 是 `"display": "standalone"` /
`display_override: ["standalone","minimal-ui"]`。独立模式下没有浏览器返回键，
**iOS 的独立 PWA 也没有边缘返回手势**——照抄的结果是用户进了详情页出不来。

所以：

- `/elder` 是 `start_url`，**根页面不该有返回**——删掉那个应用栏是对的
- **每一个详情面**（事务详情、Care Detail、Trust Receipt）**必须自带返回或关闭**，
  且必须能用键盘到达
- **出口的目标与文案跟着来路变。** MedCore 用 `?from=` 驱动
  「返回队列」/「返回住院」/「返回预约」/「返回患者列表」
  （`dashboard/patients/[id]/page.tsx:381-391`）。
  便宜，而且**它让详情页感觉是嵌在一条工作流里，而不是浮在空中**。
  优活对应：从「记录」进事务详情，返回写「返回记录」；
  从家属端待办进去，写「返回待办」。

闸门判据：`display: standalone` + 存在详情面 ⇒ 该详情面必有可键盘到达的出口。

### ⑤ 系统色由壳统一声明，不是每页各自声明

Medito 在壳这一层用 `AnnotatedRegion<SystemUiOverlayStyle>` 一次设定状态栏与
系统导航栏的颜色，取 `theme.scaffoldBackgroundColor`
（`bottom_navigation_bar_view.dart:74-83`）。

优活对应 `theme-color`。之前那道「每个 HTML 都要声明 theme-color」的断言
过界了（`stage.html` 故意没有 manifest/SW），已收窄到 `rel="manifest"` 的页面。
方向对：**壳拥有系统色。**

---

## 五、重构时的两个已知陷阱

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
