# 精修状态锚点

**这份文件的用途**：会话被额度上限打断之后，恢复的第一件事是读它，然后从第一个未完成项
继续 —— 不重新从头分析。所以它记的是**事实和下一条命令**，不是叙事。

每个 Phase 结束刷新一次，不只在撞上限时写。

---

## 当前位置

| | |
|---|---|
| Phase | **产品架构重构 Phase A 已完成**（Architecture Gate）。B–H 解锁 |
| 已完成的 Phase | −1 恢复现场 · 0 Focus fixture · 1 装齐 skill · 2 Impeccable · 3 Feel Better |
| pytest | **1216 passed / 1 failed** —— 那 1 条是**故意红的**，见下 |
| 浏览器闸门 | browser_js · page_runtime（7 页 119 控件）· contrast 14/14 · focus_geometry 15 组 · **layout_stability 14 组（新）** |
| git HEAD | `d88e6cb R27`（工作区有本轮未提交改动） |
| 子 agent | 0 个在跑。上限 **2**（Lane A 设计 / Lane B 验证） |

## 产品架构重构 · Phase A 完成（Architecture Gate）

计划书在 `~/.claude/plans/imperative-gliding-toucan.md`。本轮不追求更漂亮，
只把七个页面重组成三个产品表面。**Phase A 是硬门**：矩阵能证明 app→app 搬迁之前，
禁止开始 B–H 的 DOM 迁移。

### 为什么 Phase A 不是纸面工作

`test_no_control_was_silently_deleted.py:197-199` 把 `now` 算成**四个 app 页面 id 的
并集**，所以 `missing = before - now - known` 对任何 **app → app** 搬迁恒为空。
那道闸门是为一个方向建的（手机框内 → `/stage`），而本轮搬迁绝大多数走 app→app。
不补这个洞，「禁止 Silent Delete」在本轮**不可执行**。

### 五项交付

| | 内容 |
|---|---|
| **A1** | `build_control_inventory.py` → `ia/11_control_inventory.{json,md}`，从代码生成 |
| **A2** | 判据从「集合成员」升级到「(文件, panel) 相等」；`MUTATION_PROOF_MIGRATION.md` 五个变异体 |
| **A3/A4** | `ia/10_surface_boundaries.md`（Surface ≠ URL，五层模型）+ `ia/09_consumer_app_architecture.md`（两个 Shell 的导航契约） |
| **A5** | `youhuo/surfaces.py` 唯一路由事实源 + `test_surface_registry.py` 12 条 |
| **A6** | `YOUHUO_DEMO_STATE=empty\|normal\|attention` + `seed_demo_scenario()` + DemoClock |

### A1 量出来的四件事

1. **145 个控件，只有 57 个带 `id`。** 矩阵按 id 追踪 ⇒ 另外 88 个搬走没人发现。
   解法不是给 88 个元素硬加 id（那是为让闸门开心去改产品），而是把身份放宽成一组
   **稳定属性**：`id` / `data-section` / `data-text` / `data-run` / `data-jump` /
   `data-sheet-*` / `name` / `href`，加上从最近一个有身份的祖先借
   （评委页七个「看这一拍的证据」文字**完全相同**，靠 `data-beat=03/summary` 才分得开）。
   刻意不用 class（改名就断）、位置（重构必然变）、可见文字（还有一整轮文案要改）。
   覆盖率 **57 → 145 / 145**。
2. **21 个控件靠序号才区分得开** —— `#stageRoles`/`#stageLines`/`#stageSizes` 各五个
   兄弟按钮自己没有任何标识，`/family` 两个 `href=/trust`，`/care` 两个 `href=/`。
   重构时补 `data-*` 钩子，那份名单会自己变空。
3. **运行时 119 vs 静态可按 109，差 10 个是 JS `createElement` 建的**
   （提醒的「我知道了/已完成」、任务卡的「同意/拒绝」）——静态扫描永远看不见它们。
   另有 `/family` −1：一个静态控件运行时够不到。
4. **我自己的脚本报错了一次**：22 个控件被报成「没人绑」，含 `#mic` `#send`——
   它们用 `querySelector('#mic')`，id 带井号，而我的 needle 只匹配 `'mic'`。
   修完 22 → 1。第二次是 62 个被报成「没人绑」，因为属性委托（`[data-text]`、
   `[data-run]`、`.seg`）不经 id。修完 62 → 1，剩下那个 `#openExtras` 是真的按属性绑的。
   **一份把「我的正则没匹配上」写成「这个控件没人绑」的清单，会让人去修不存在的问题。**

### A6 修掉了两条 Visual Critic 的扣分

- **审计链时间戳**：改前六条挤在 **20 毫秒**内、「家人点了同意」与「他确认了这一笔」
  相隔 8 毫秒。改后 **11:26:04 → 11:28:26**，跨 2 分 22 秒。
  做法是 `append_audit(created_at=…)` 让事件**在产生时**就带间隔，
  **不是**前端把显示值改写好看——`created_at` 本来就参与哈希，所以链照样锁得住。
- **首屏不再是空的**：`normal` 态种 3 条提醒 + 一笔**完整证据链**的已完成缴费。

### A6 顺带暴露的一个真问题（已修）

`normal` 态跑起来之后 `check_page_runtime` **红了**：`/elder` 撞到 144 次上限还不停。
报文猜「有两个按钮在互相召唤」——机制猜对了，主体猜错了：没有人互相召唤，
是 `reminderAction` 每次都重渲染整段，「我知道了/已完成」变成**全新的对象**，
而按过名单是 `WeakSet`（认对象）。空态下没有那些按钮，所以这道闸门一直是绿的
——**又一次「空态掩盖问题」**。

修法是给按过名单加第二把钥匙：**稳定身份**（和 A1 同一套概念）。
刻意不用可见文字当钥匙——三条待办的按钮文字完全相同，那会让第二条的按钮一次都按不到，
把不收敛换成漏测，更糟。修完控件数 **119 → 121**（那两个是以前从没被按过的真控件）。

## Phase B 已开始：那条故意红着的测试**已经变绿**，靠修布局

`test_the_typing_route_is_in_the_first_screen_on_every_viewport` **5 passed**。
断言一个字没改。

### 做法：Orb + 打字入口钉在视口内

- **竖屏与宽屏**：`.elder-panel[data-panel="home"] > .mic-stage` 用
  `position: sticky; bottom: 0` + 不透明底。首页整段可滚，「角色头 / 结论行 / 下一件」
  正常滚走，「今天」列表从钉住的操作区下面经过。
- **横屏（`max-height: 540px`）**：改用 `position: fixed`。理由是实测出来的——
  sticky 相对的是 `.elder-panel` 这个滚动容器，而它自己高 **954px**，
  钉在它的底边等于钉在屏幕外。

### 顺带发现横屏那套布局**本来就是坏的**

`@media (max-height: 540px) and (min-width: 640px)` 把 `.mic-stage` 绝对定位到
`top: 50%` —— 而 50% 是**定位祖先** `.stage` 的一半，实测 `.stage` 在横屏下高 **972px**
（那一档把定高框架解开了，页面恢复正常滚动）。972 的一半是 486，视口只有 390：
麦克风连着打字入口一起落在首屏外。

这条规则一直是坏的，只是**以前首页是空的**、`.stage` 没这么高，所以看起来还行。
——又一次「空态掩盖布局问题」，这一轮第三次。

修法是给它加 `body[data-focus="on"]`：那套两列布局是为了给**对话区**腾横向空间，
而对话区只在 Focus Mode 里存在。首页没有对话区，却同样被命中。

### 两次量错都记下来

1. 第一版 `bottom: 0`，667×375 下打字入口被底部标签栏整个盖住（命中测试落在
   `nav.tabbar.elder-tabs` 上，它是 `fixed; bottom: 0; z-index: 45`）。
   改成 `bottom: calc(var(--tabbar-h) + env(safe-area-inset-bottom))`。
   844 宽没事，因为 ≥761px 标签栏变成顶部横排——**同一个缺陷只在一半视口上显形**。
2. 试过给钉住的那块加一道 `box-shadow: 0 -1px 0` 当分隔线，但 sticky
   **没被钉住的时候那条线照样画**——高视口下它是页面中间一道不表示任何东西的横线，
   而「不携带信息的线」正是这一轮判过两次 AI slop 的那一类。删掉了，不透明底就够。

### 首页顶栏那条演示壳已撤（出口**搬走**，不是删掉）

`elder.html` 的 `.app-bar`（「‹ 返回」+ 写着「优活办事模式」的徽章）整段移除。
两条理由：成熟消费级 App 的根页面没有返回键；而那个徽章和它下面的角色头
**说的是同一件事**（图标 + 名字 + 整套配色都随模式切换），徽章只是用工程话再喊一遍。

**出口没有删，搬进「我的」最后一行**（`#leaveApp`「换一个人用」）——真实 App 的
"退出 / 换账号"就在设置里。

改之前先读了 `test_tabbar.py:156-233`：它的判据是每一页至少有一个
`back-link` / `class="tabbar"` / `<a href="/">`。而 elder 的四个 Tab 是
**页内 `<button>`**、`class="tabbar elder-tabs"` 也不匹配 `'class="tabbar"'`，
所以 elder 唯一的出口本来就是那条 back-link ——**直接删会真的造出死路**，
而那条测试正是被一次真实死路换来的。搬到「我的」之后 `<a href="/">` 仍然在，
性质守住了，位置更像产品。

`#modeBadge` / `#modeName` 两个 id 随之消失，`elder.js:290-291` 改成
`if (modeBadge) …`。**刻意不删那两行**：宽屏与横屏还留着承接位，
而模式切换是核心特性，哪天要把徽章放回某个表面，读它的代码应该还在。

### 顶栏撤掉之后留下的 86px 空洞（已修）

删掉 `.app-bar` 之后，`--stage-reserve` 还是 `98px + var(--tabbar-h)`，而那 98 里的 **86
就是顶栏本身**。实测三个视口全都 `stage.top = 12`（只剩 `main` 的内边距），
于是多留的 86px 表现成**标签栏上方 84px 的空带**，并且把折线推到正好切「今天」
两个字的位置（`.today-block` 的 top 是 691，而面板可视高 690）。

**给一个不存在的元素留位置，比留少了更难发现**：屏幕上只是"下面空了一块"，
没有任何仪器会报错。

改成 `calc(var(--space-3) + var(--tabbar-h))`（用令牌而不是又一个魔数）。
实测：空带 **84px → −2px**，面板可视高 **690 → 776**，
`.today-block` 从"正好在折线上"变成"在折线上方 85px"。

现在折线切的是**第一张提醒卡**而不是一行标题——半张卡说的是「下面还有」，
半行标题说的是「这里坏了」。

### Task Space 已建（§9–13），但字段路径有两处缺口

新模块 `backend/static/task-space.js`，**纯函数**（照 `renderGlassBox` 的形状），
所以它能像 Focus 几何那道闸门一样被直接喂数据、不碰缴费、不依赖数据库。
四态齐全：普通任务 / 歧义 / 等家属 / 完成。

架构约束写在模块头上并**由闸门守住**
（`test_task_space_reads_only_backend_state.py`，7 条）：

> Conversation engine owns state. Task Space owns presentation.

`viewKindOf` 的每个分支只许读 `code` / `task_status` / `data.*`，闸门按源码形状判——
一旦它开始写 `if (localTaskState === …)`，前端就有了第二个状态机，
半年后和后端漂移的表现是「界面说等家人确认，后端已经办完了」，而两边各自都自洽，
没有任何闸门抓得到。认不出的状态回 `null`，调用处退回聊天视图，**不猜**。

**实测确认渲染**（走真实路径：`#typeInstead` → `#text` → `#send` → 真后端）：
`body[data-task-view]="task"`，Task Space 在 top=178 高 224，
聊天区降级到 top=419 高 96（没删，退到下面）。

**两处缺口，是后端给的字段比 §10 要的薄，不是渲染错**：

1. 主体显示「**这件事**」而不是「缴费」——`data.data.task_type` 在这个响应里不存在。
   同一个缺口让状态行也说「正在办这件事」（`elder.js` 那处用的是同一个字段），
   所以它是既有问题，我的模块只是把它显形了。
2. §10 要的「北京自来水公司」拿不到（payload 里没有 authority），
   而 `data.message` 里带着机器日期格式：「查到 **2026-07** 的水费是 68.40 元」——
   那是给机器读的写法，出现在念给老人听的句子里。

金额是对的（`¥68.40`，从 `slots.amount_cents` 取）。

**下一步先查响应真实形状**再改字段路径，不要照猜的路径写——
这一轮已经四次栽在「读到的值不是决定结果的那个值」上。

### 一个自己被抓的记录

完成态那个对勾第一版写的是字符 `✓`，`test_no_emoji_as_icons` 当场红了，**抓得对**：
「不许 emoji 当图标」是硬约束，而字符对勾的字形、字重、基线全跟着回退字体走，
而它是「办好了」这个结论唯一的视觉标志。改成内联 SVG，线宽 1.8 与 sprite 一致。

另外这条新闸门第一版**命中了我自己的注释**（那句「一处都不读 `task_id`」），
报出来的结论和真实情况正好相反。剥注释之后才对——本轮第四次同一类。

### Phase B 剩下的

- Task Space 的两处字段缺口（见上）
- 记录 → 事务详情的入口（`.log-item` 现在纯文本、无链接、无 task_id）
- 家人 / 我的 两格按 §16 §17 重写

## ⚠ 树上曾经有一条故意红着的测试（已修绿）—— 不要为了绿而改断言

`test_mobile_reachability.py::test_the_typing_route_is_in_the_first_screen_on_every_viewport`

它刚被改成在**有待办**的首页上量（以前量的是空首页，所以一直绿）。实测：

```
iPhone SE 竖 320×568   打字入口不在首屏内，差 139px
iPhone SE 横 667×375   差 306px
iPhone 14 横 844×390   差 275px
iPad 横  1024×768      点不到，盖在上面的是 button.tab.seg
笔记本   1280×800      点不到，盖在上面的是 button.tab.seg
```

**这套首页布局是因为应用是空的才装得下。**「用打字说」是语音失败时唯一的退路
（Firefox 没有 Web Speech、权限被拒、没麦克风、网络差都会失败），够不到等于没有。

留着红是刻意的：把它改回量空首页，就是把这个缺陷重新藏起来——那正是它绿了很久的原因。
修布局让它变绿才算完成。

**演示数据已经补上**（`Database.seed_demo_reminders()`，只在 `YOUHUO_SEED_BASELINE=true`
时调用，pytest 默认不受影响）。上一次我把它放进 `seed_demo()` 里，红了 12 条——
那是**测试也在用**的种子函数，往里塞待办会改掉「取消」按名字找待办、裸「嗯」确认、
访客隔离计数的语义。层选对了之后这 12 条全绿。

## Phase 5 第一轮（已评分，见 `VISUAL_SCORECARD.md`）

重拍 252 张（7 路由 × 9 视口 × 2 配色），带 `MANIFEST.json/.md` 与前端指纹
（`write_shot_manifest.py`——上一轮的审查就是对着改前的批次做的，没有任何东西能看出图过期了）。

**得分**：elder 79/94 · family 73/94 · care 76/90 · trust 80/90 · stage 77/92 ·
judge 79 · 首页 87。**无一达标。** 工程绿了不等于视觉成熟。

**斜杠零由两个互不相干的方法各自指出**：Lane A 用字体光栅化（墨量 9301→9301 证明
`"zero" 0` 无效），Visual Critic 从像素上列成跨页第一条。全站单点修复收益最大。

**本轮已修并看图确认**：
- 深色下演示手机边框翻成亮米白（`color-mix(… var(--ink) …)`，而 `--ink` 是文字色）
  → 改固定近黑。眯眼第一落点从边框回到屏幕。
- `/stage` 顶栏「证明」掉第二行——**我自己引入的回归**：`.segmented` 的
  `flex-wrap: wrap` + 48px 下限在 138.9px 的 `.stage-segs` 上撑破了。该处覆写为不换行。

**这批图的限制（必须记住）**：拍摄时演示数据为空，所以 elder 首屏是「今天没有要办的事」、
family 是 0/0/0、judge 右侧手机是空的。**这几页"内容相关"的扣分量的是我的环境，
不是产品设计**；排版/层级/图标/颜色/一致性的结论不受影响。

**下一步的顺序不能反**：先补演示数据 → 再修布局 → 然后才重拍重评。
因为补数据当场暴露了 `test_the_typing_route_is_in_the_first_screen` 变红
——**现在这套首页布局是因为应用是空的才装得下**（见 `KNOWN_ISSUES.md` 两条 P1）。

## Phase 4 结果（Lane A 审计 + Lane B 重派补测，已完成）

Lane A（审计）交回 20 条，Lane B（测量）**在跑到一半时撞上会话额度上限中止，
没有交回任何结果**。详见 `MOTION_AUDIT.md`。

**已实施 4 条并复验**：

- **MO-04（P1，本轮最重）**：`.mic-big:hover:not(:disabled)` (0,3,0) 压过
  `body[data-activity="speaking"] .mic-big` (0,2,1)。后果是 **speaking 的 12px 光晕
  被 hover 抹掉，speaking 与 idle 像素相同**——而 speaking 是「我在说话，按一下会打断我」，
  分不清它和 idle，老人就会按下去打断优活自己的话，**那正是 `elder.js` 开头写明要修的缺陷**。
  触屏靠 sticky hover 同样中招。加 `:not(:disabled)` → (0,3,1)。
- **MO-03/MO-10（P1）**：十一态的主要通道（`.mic-dial` 的 `border-color`）走
  `--mode-fade`=1000ms，弧要一秒才成形，而 `ring-spin` 从第 0 毫秒就转——头一秒是
  「一个几乎没变化的整圆在转」＝视觉上静止。改 `--dur-base`。`--mode-fade` 本身是规格，不动。
- **MO-09**：`.role-halo::before/::after` 两个全视口伪元素带**永久** `will-change`，
  而手机上它们 `animation: none !important`。挪到真跑动画的状态规则上。
- **MO-07/08**：模式切换的 `500` 在 JS 里是字面量、CSS 里是 `calc(var(--mode-fade)*.5)`；
  且 reduced-motion 下 CSS 掐到 `.01ms` 而定时器没门控 → **硬空白 500ms**，比不做动效更糟。
  改成从 `getComputedStyle` 现读。

**MO-04 的第一次复验是废的，记下来**：探针用 `Input.dispatchMouseEvent` 移到 `#mic`
中心后报「仍然不同 ✓」，但同一张表里 **idle 悬停时 `transform: none`**——而
`.mic-big:hover` 明写 `scale(1.04)`，说明 hover 根本没造出来。实测：
`dispatchMouseEvent` 让 8 个祖先进了 `:hover`，唯独没有 `#mic`；
`CSS.forcePseudoState(['hover'])` 才管用。**造不出被测状态时，读到的"一致"不是通过，是没测。**

**Phase 4 没做的四件事**（进 Phase 6 Browser QA，不是通过）：
① reduced-motion 下逐条动画时长是否真塌到 0 的实测；② 十一态关掉动效后的逐态截图像素差；
③ 动效可打断性实测；④ 给 `check_voice_orb_states` 加 `forcePseudoState`
——不加的话 MO-04 这类回归下次照样静默通过。

## Phase 3 结果（已完成）

两条 lane 各报 20 条，逐条裁决写在 `FEEL_BETTER_AUDIT.md`。
**17 条采纳并实施，1 条判 FalsePositive 并附实测反证，11 条推到 Phase 5**
（都是"必须连图看"的视觉判断：数字字体、surface 阶梯、图标语义与线宽、`.panel` 三重层级）。

### 这一轮的主轴：三条「声明了，但从来没画出来」

`<use>` 影子树里，`<symbol>` 自身的表现属性**赢过**从宿主继承下来的值。同一个机制，
三处后果：当前 Tab 加粗从未生效（墨量 2698 = 2698）；`"zero" 0` 关不掉斜杠零
（墨量 9301 = 9301）；对比度审计读到的 `fill: black` 不参与绘制（误报）。

第一条是无障碍承诺的一半：`pages.css` 注释宣称当前 Tab 有两条非颜色通道，实际只有一条。
守它的测试 `re.search` 的是**选择器字符串在不在**，而同一个函数的 docstring 上面三行
正好写着「选择器存在不等于指示条存在」。

修完实测：手机 **+18.6%** 墨、宽屏 **+31.6%**。

**我自己在这条上连错两次**：`.tab-icon` 第一版写进 `@media (min-width: 761px)`
（只有宽屏生效，而审计恰好在宽屏量所以绿了），第二版又落进 `@media (max-width: 760px)`
——正好是反的另一半。最后写了 `scratchpad/css_scope.py`（数括号判作用域）才确认。
**这个文件已经在"规则的位置决定它生效不生效"上咬过三次。**

### 新增三道闸门（都先红后绿 + 变异自证）

| 闸门 | 变异结果 |
|---|---|
| `test_theme_color_matches_the_canvas.py` | 先红 6 页 × 2 档 → 修 → 绿；判据钉在 `--bg` 令牌上，不钉抄下来的十六进制 |
| `test_report_punctuation.py` | 内含「把真的显示过的那两句原样拼回去」，必须红 |
| `backend/scripts/check_layout_stability.py` | 撤掉高度预留 → `/trust` **0.3807**、`/family` **0.1665**，红 |

CLS 那两条（`/trust` 0.2068 → **0.0187**，`/family` 0.1300 → **0.0505**）在**手机视口上
测出来是 0.0000** —— 不是它不跳，是位移发生在首屏折线以下、不计入。这个项目的
截图矩阵和点击遍历都以手机为主，所以一个只在桌面显形的 P1，在所有既有闸门下都是绿的。

### 「app 面不许有工程词」那道闸门自己有两个洞

1. 脚本清单是**手写**的，漏了 `common.js`（四个 app 页面全部加载，装着 `FIELD_LABEL`
   六十多条翻译和一句 `'原始响应'`）、`identity.js`、`sheet.js`。
   改成从 HTML 的 `<script src>` 推 + 跟着 ES `import` 走一层。**补上后第一次运行
   就在四个页面上各抓到 3 处。**
2. 禁用词名单是**从观测到的基线倒推**的，只挡得住已经犯过的错。屏幕上写着
   「语义层：离线确定性」而闸门报 0。

真泄漏顺带修掉：`common.js` 的 `演示登录失败：${role}` 会经 `addBubble` 念给老人听，
整句是「系统暂时不可用：演示登录失败：elder」。

### 引号：前端 47:8，后端 39:0，方向相反

她的气泡由前端渲染、优活的回话由后端返回，**同一个聊天窗口里两套引号**。
统一到 `「」`：13 个文件 106 个字符，全部行为测试照旧通过。

## Phase 0 / 1 / 2 结果（已完成）

- **Phase 0**：`check_focus_geometry.py`，5 视口 × 3 Case = 15 组，三路变异全红。
  抓到一个真缺陷：iPhone SE Case A 上输入行从一开始就够不到。
  我在这道闸门上错了四次，四次都是仪器的错（13 条失败里 12 条是假警报）。
- **Phase 1**：四组共 21 个 skill 装进项目 `.claude/skills/`，见 `SKILL_REGISTRY.md`。
- **Phase 2**：Impeccable 八条逐条裁决（4 采纳 / 2 拒绝 / 2 延后），见 `IMPECCABLE_AUDIT.md`。
  检测器第一次跑是**残的**（缺四个解析依赖，自报 DEGRADED），装齐后从 6 条变 8 条。

## 三个 P0（本轮早些时候，已修已验）

| | 现象 | 验证 |
|---|---|---|
| A-01 | 语音说完话屏幕不动——她在等确认 126.50 元的付款，屏上写「今天没有要办的事」 | `setFocus(true)` 提到 `send()` 咽喉处 |
| A-02 | 「用打字说」点下去命中「已完成」 | 建两条真提醒后做命中测试，三个探针全命中自己 |
| A-03 | 宽屏三个分区没有入口（含「我的」——语速与字号两个无障碍控件所在页） | `.tabbar:not(.elder-tabs)` |

**A-04 是 A-01 的失败路径版本，本轮修掉**：`rec.onerror` 的六句话
（「让家人帮您在手机设置里打开麦克风权限」等）全写进 `#status`，而 `#status` 在
`.elder-focus` 里，`pages.css:304` 是 `display: none`。她点「不允许」之后**屏幕上什么都没变**。
`input.focus()` 同理落空。顺利的时候她不需要提示，卡住的时候才需要。

## 未做 / 已知

- **`setStatus` 还有 5 处写进不可见元素**：`saveProfile` 两处、`reminderAction`、
  启动失败的 `.catch`、`rec.onstart`。`#status` 是这一页唯一的状态通道，而它默认不可见。
  A-04 只修了错误路径。**这是一个结构问题，不是五个 bug**——留给 Phase 4/6。
- **演示数据**：照护页「身体」「心情」两段是空态 → `KNOWN_ISSUES.md`。
- **A-01（数字字体）/ B-17（`.panel` 三重层级）/ B-08 B-09（深色 surface 阶梯反向）/
  A-06（Tab 图标语义撞车）/ A-08（描边 6 个值）** —— 全部推到 Phase 5，
  理由一致：必须连对照图一起看，不能只跑闸门。
- `.claude/skills` 8.2 MB（含 3.6 MB `node_modules`）打包时排除。

## 下一条命令

**先补 Phase 4 缺的那一半**（Lane B 的四件事，见上），再进 Phase 5。
恢复会话后第一件事是跑基线确认树还是绿的：

```bash
.venv\Scripts\python.exe -m pytest -q backend/tests
```

五道浏览器闸门（`check_browser_js` / `check_page_runtime` / `check_contrast` /
`check_focus_geometry` / `check_layout_stability`）**全部已接进 `verify_all.ps1` 与 `.sh`**
——本轮之前后两道只在手敲时跑过，谁跑一遍验证栈都不会知道它们没被检查。

Phase 5：旧截图全部作废（上一轮的审查就是对着改前的批次做的），重拍并写 manifest，
然后 Visual Critic **只看截图不看源码**。门槛：老人端与家属端首页 ≥94、Care/Trust ≥90、
Stage ≥92。**实现 agent 不得给自己打分。**

Phase 5 要连图一起裁决的积压（Phase 3 与 4 推过来的，共 13 条）：
数字字体（`"zero" 0` 是死的）、`.panel` 三重层级、深色 surface 阶梯反向、
Tab 图标语义撞车、描边 6 个值、全屏光晕 ≥761px、触屏按压反馈、`ring-breathe` 与
`orb-halo` 是否该删。

## 变异状态

| 闸门 | 变异证明 |
|---|---|
| 迁移矩阵（控件没被静默删除） | ✅ 四路全红 |
| 反 AI-slop 视觉 | ✅ 七路全红（阈值 60° 是估的、变异测出来是空的，实测 39.1° 后改 20°） |
| 中文排版（西文直引号） | ✅ 自证 + 抓到 6 处真实占位 |
| 未定义自定义属性 | ✅ 抓到 3 处 `--lh-normal` |
| 运行时标识符泄漏 | ✅ 三路全红 |
| 凭证刷新存活 | ✅ 两路全红 |
| Focus 几何（确定性） | ✅ 三路全红，见 `MUTATION_PROOF_FOCUS.md` |
| **app 面工程词** | ✅ **三路全红**（含「同一句话搬进共享文件」——那正是原先的盲区） |
| **日报标点** | ✅ 把真的显示过的两句拼回去，两条断言都红 |
| **载入期 CLS** | ✅ 撤掉预留 → 0.3807 / 0.1665，红 |

`check_page_runtime` 里那道**依赖真实缴费**的 `check_focus_mode_after_speaking` 仍然留着，
但几何判据的权威在新闸门。第 8.5 条要给它补一条前置断言（reliance 高度为 0 时报
"没造出被测状态"而不是静默通过）—— **还没做**，进 Phase 7 的 Mutation Suite 一起收。
