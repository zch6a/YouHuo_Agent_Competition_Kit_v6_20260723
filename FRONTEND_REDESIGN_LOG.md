# 前端重构日志

按任务书要求逐条记录。顺序即执行顺序：考古 → 参考 → 信息架构 → 实现 → 审计。

基线见 `frontend_audit/baseline_tests.md`（950 passed / 对比度 12/12 / page_runtime 六页 41 控件）。
问题清单见 `frontend_audit/05_visual_problems.md`。

---

## R1 · 设计系统盘点挖出的四个真实缺陷

| # | 文件 | 原内容 | 新内容 | 原因 | 视觉影响 | 功能风险 | 测试 | 结果 |
|---|---|---|---|---|---|---|---|---|
| 1 | `base.css` | 两条 `.shell` 规则：前一条 `padding-left/right: max(--space-4, env(safe-area-inset-*))`，后一条 `padding` 简写 | 合成一条，`padding-block` + 左右各自取 `max()` | 同等特异性后者胜出，**安全区内边距从未在任何视口生效** | 刘海屏横屏下内容不再压到挖孔 | 无（纯 CSS） | contrast 12/12、page_runtime | 通过 |
| 2 | `components.css` | `button.danger { background: linear-gradient(180deg,#d8434e,#a81f2a); color:#fff }` | 描边填充式：底 `--danger-bg`、字与边框 `--danger` | 写死值绕开 `--danger`，深色模式下是**全站唯一不跟随主题的语义色**，而它是不可逆操作的按钮 | 危险按钮从实心红块变为描边式，深色下正确 | 无 | contrast 12/12（含深色） | 通过 |
| 3 | `pages.css` | `@media(max-width:720px)` 内 5 条声明 | 删除 | 被其后 `@media(max-width:760px)` 全部覆盖，`.chat` 更被 `#chat` 压死——**从未应用过** | 无（本就无效） | 无 | 全套 | 通过 |
| 4 | `tokens.css` | `--role-ink` 只在 `body[data-mode=…]` 定义 | `:root` 补默认值 | `.head-icon` 与 `.tab.is-current` 消费它；任一页漏写 `data-mode` 就静默退化成 `inherit` | 无（补兜底） | 无 | contrast | 通过 |
| 5 | `tokens.css:7` | 注释引用 `backend/tests/test_stylesheet_layers.py` | 改为真实守卫 `test_pwa_shell.py::test_stylesheet_layers_load_in_cascade_order` | **那个文件不存在**——上一轮我自己写错的 | 无 | 无 | — | 通过 |
| 6 | `base.css` / `components.css` | `.bottom-nav`、`.hero-title`、`.mode-youhuo` | 删除 | 三个类在全部 HTML 与 JS 中零引用 | 无 | 无 | 全套 | 通过 |

## R2 · 首页：从项目目录到角色选择

| 项 | 原 | 新 |
|---|---|---|
| 整页高度（390px） | **8574 px**（约 10 屏） | **844 px**（正好一屏，不用滚） |
| 首屏第一句话 | `C4-AI · HARMONYOS AGENT INNOVATION · V6.0` | `优活 / 让日常生活简单一点。` |
| 主 CTA | 「五分钟决赛导览」（视觉权重最高的卡片） | 「我是老人」「我是家人」 |
| 导航卡 | 6 张 | 0 |
| 工程术语 | 9 个横滚芯片 + 一整块「工程证据」 | 0 |
| 底部导航 | 五格，含「评委」 | 无（选择页不需要常驻导航） |

- 新建 `landing.js`：记住上次选择。**只在冷启动时自动跳转**（无 referrer 或外部 referrer）；从站内点回首页永远停在选择页，否则想换身份的人会被一路弹回去。自动化检查每轮用全新 profile，localStorage 为空，天然不触发。
- `index.html` 重写。它是六个页面里唯一零 DOM 契约、零 API、零 id 的页面，所以可以整页替换。
- 删除 `.hero` / `.cards` / `.card` 一族（components.css 65 行）与 `.hero-head` / `.innovation-strip` / `.evidence-grid` / `.role-tile` 等（pages.css 1622 字符）——首页改版后全站引用降到 0。
- `sw.js` 外壳加入 `landing.js`，`VERSION` v2 → v3（不改版本号，已装设备会继续用旧外壳）。

**发现并修掉一个新问题**：首页那行「演示与可信技术 →」是纯文本 `<a>`，命中区 124×19。
`components.css` 的 `min-height: 48px` 对行内元素无效。改 `inline-flex` + `min-height`，
外观不变、可点区域到 48px。这是对比度闸门量出来的，不是看出来的。

## R3 · 导航：评委与可信退出消费者动线

任务书的硬性失败条件之一是"Bottom Navigation 还有评委"。只删那一格不够——可信实验室
同样是工程世界，出现在老人家属的动线上是同一个错误。

| 页面 | 原 | 新 |
|---|---|---|
| `/` | 五格标签栏 | 无（角色选择页） |
| `/elder` | 无 | 无（保持） |
| `/family` `/care` | 五格 | **三格**：首页 / 家人 / 照护，`<body data-nav="tabbar">` |
| `/trust` `/judge` | 五格 | 无标签栏，用本来就有的返回链接回首页 |

返回链接的隐藏规则从 `main.shell:not(.app-frame) .back-link` 收窄到
`body[data-nav="tabbar"] .back-link`。**这一步是必须的**：按旧规则，trust 和 judge 会
既没有标签栏、返回链接又在手机上被藏掉，正好造出一条死路——而
`test_every_screen_has_some_way_out` 当初就是被一条真实死路换来的。现在规则自洽：
只有真的有标签栏的页面才允许藏返回链接，因为只有它们提供了替代出口。

## R4 · 被重构推翻的测试（有意修改，非"顺手改红的"）

| 测试 | 改法 |
|---|---|
| `test_tabbar.py` 的 `PAGES` / `EXPECTED_HREFS` | 从五页五格改为两页三格。这条测试包裹的六条 INVARIANT（恰好一个 current、paint 与 announce 一致、每格有文字 + `aria-hidden` 图标、当前态不只靠颜色、手机独有、高度来自单一令牌）**原样保留** |
| `test_every_screen_has_some_way_out` | 判据从 "没有标签栏 → 必须 app-frame" 改为 "声称有标签栏就必须真的渲染它 / 没标记就不许有标签栏"，与新的隐藏规则一致 |
| `test_landing_page_mentions_trust_innovations` | 迁到 `/trust` 并改名 `test_trust_page_names_the_trust_innovations`。**不是删掉**——它守的"可信主张必须写在产品里"是对的，只是钉错了页面。四个术语已加进可信页头部 |
| 新增 `test_the_landing_page_has_no_tab_bar` | 首页无标签栏、但必须有两个身份入口和演示入口 |
| 新增 `test_the_demo_entry_is_not_in_any_consumer_navigation` | `/judge` 不得出现在任何消费者标签栏里 |
| 新增 `test_landing_page_is_a_role_chooser_not_a_directory` | 首页不得出现 `自主权包络 / 证明式完成 / 同意记忆 / 家庭共识 / OpenAPI / Saga / C4-AI` |

**实测：934 passed, 1 skipped**（基线 950；差额是 `test_tabbar` 参数化从 5 页缩到 2 页，
少了 16 个参数化用例，另新增 3 条）。对比度 12/12，page_runtime 六页 41 控件全过。

---

---

## R6 · 家人端：从 admin dashboard 回到产品页

重构前 `/family` 在 390px 下整页 **11121px**——28 屏，12 张权重相同的白卡，其中 4 张写着"暂无"。
它不是产品页，是把后端有的东西各开一个面板铺出来，让人自己找。最后一张「防篡改操作日志」
把 `system-vc8693dfcd970`、`DEMO_LOGIN`、`SESSION_CREATED` 原样摆给家属看。

### 信息架构

一级只回答三件事，其余降到页内分区（**不加路由**：六条路由、service worker 外壳、
manifest 的 start_url 全部不动，切换零往返，地铁上也能翻）。

| 分区 | 内容 |
|---|---|
| 今天（默认） | 今天怎么样（生活日报）· 待您确认/进行中/今天到期 · 需要您处理 |
| 待办 | 按日期 · 给他添一件事 · 通知 |
| 趋势 | 这一周（已脱敏） |
| 我的 | 做过的事 · 照护档案 / 可信中心 · 立即检查到期待办 |

当前分区写进 URL hash，刷新之后还在原地。

**刻意不用 `.panel`**：四个分区里如果每段还各自套一张卡，只是把 12 张卡叠成 4 组卡。
分段之间用标题和间距分隔，卡片留给真正要被当作一个对象来点、来处理的东西。

### 逐条改动

| 位置 | 原 | 新 | 为什么 |
|---|---|---|---|
| `family.html` topbar | `YOUHUO FAMILY CONSOLE · V6.0` + 「家属协同台」 | 「家里今天」+ 最后更新时间 | 用户看到的第一句话不该是版本号 |
| `family.js` 审计行 | `<code>FAMILY_APPROVED_AND_EXECUTED</code>` / `执行者：system-vc86…` | 「优活办完了一件事」+ 时间 | 家属要的是"谁做了什么"，不是一条能 grep 的日志 |
| `family.js` 通知兜底 | `NOTICE_TITLE[t] \|\| t` | `\|\| '来自优活的消息'` | 兜底成原始码，等于这层翻译在遇到新类型时自动失效，而那正是它该起作用的时候 |
| `family.js` `load()` 的 catch | 写进 `#chain` | 走 `#familyNotice` | 那个 catch 罩着四个并发请求加一次登录，原先统一写进"记录完好"的位置；分区改版后 `#chain` 默认折叠，再写那里等于整条失败无人可见 |
| `family.js` 生活日报分项 | 五项全部平铺 | `<details>`，有 warn/bad 才自动展开 | 「还不好说」那一态下同一句"只有 N 天的记录，不足 7 天"会连出现五遍，把首屏吃光——而那正是新装用户和评委最先看到的一态 |
| `family.js` 隐私声明 | `.notice good` 绿框 | `.meta` | 承诺要一直写着，但它是每天一样的脚注，不是今天的新闻，不该和"今天不用您操心"抢同一级 |
| `#scheduler` 标签 | 「演示提醒调度」 | 「立即检查到期待办」 | 它做的确实是这件事；正式环境每分钟自动做一次，这里手动催一次 |
| `components.css` `.audit-row` | 左边框 + 渐变底 + 等宽字体事件码 | 一行一条，分隔线 | 渐变和等宽字都在告诉家属"这是日志"，而它应该读起来像记录 |

`#audit` / `#chain` / `#mChain` 三个契约保留，只是搬进「我的」并改成家人看得懂的话。
逐条原始记录、校验算法和证明过程留在 `/trust`——那才是它的地方。

### 顺带修掉的一个真缺陷：换库之后回访用户永久变砖

审计家人端时发现整页 401，刷新多少次都一样。原因不是令牌过期，是**身份本身**服务器不认了：
访客家庭是在某一个数据库里开通的，存在 localStorage。重新部署、重置演示数据、换台机器跑，
那个 family_id 就没了。`identity.js` 写好了 `reset()` **却从来没有人调用**，`pending` 又是
记忆化的，同一次加载里再问还是那个死身份。出路只有用户自己去清网站数据——不会有人这么做。

也就是说：**这个项目每一次重新部署，都会把所有回访过的浏览器永久挡在门外**，包括提前打开过
演示地址的评委。

修法：第二次 401 之后换一个身份，然后**整页重载**。只换令牌不够——页面在加载时就把
`ELDER_ID` 之类常量从旧身份里取走了，换令牌之后请求能过鉴权却拿不到东西（实测报
"老人账户不属于当前家庭"）。一个标签页只换一次，避免服务器真出问题时变成刷新循环。

### 三个仪器同一轮里被发现在撒谎

**1. `press_every_control` 只按得到第一屏。** 它开局快照一份可见按钮名单按到底。三个分区默认
`hidden`，名单里根本没有它们——而检查照样报"全部按过"。改成分轮快照仍然不够：一轮结束时只有
最后点开的分区是展开的。三种策略给出三个数：**46 / 47 / 48**，只有最后一种（每按一个重新找
一次，且会换屏的控件留到最后按）真的把每个按钮都按到了。

**2. `shoot_pages.py` 在服务没起的时候拍下 42 张 Chrome 错误页，然后报告"42 张截图，无横向
溢出"。** 错误页当然不溢出——上面什么都没有。溢出探针量的是"这一页有没有超宽"，不是"这一页
是不是这个应用"。补了一道判据：我们的设计令牌能不能解析出来（不是查某个 id——六页骨架不同，
只有两页有 `main#main`，拿骨架当判据会把三个好页面判成加载失败）。

**3. 我自己的变异脚本把一条 JS 注释写进了 Python 源码**，于是每次都以 SyntaxError 退出，
四条变异全部"红"——一条都没真的测过。修掉之后重测：3 红 1 绿，而那条绿的
（"renew 不重新开通"）本来就不是缺陷，`reset()` + 整页重载已经足够自愈。

### 新增闸门（每一条都先红后绿）

| 闸门 | 守什么 | 变异 |
|---|---|---|
| `check_identity_self_heal`（浏览器内） | 种一个服务器不认识的身份，页面必须自己走出来 | 3/4 红，第 4 条经查不是缺陷 |
| `test_the_family_page_never_prints_a_raw_event_code` | 原始事件码不进家人端 | 红 |
| `test_every_family_section_button_has_a_panel_to_show` | 四个按钮四块内容，恰好一块默认展开 | 红 ×2 |
| `test_a_failed_family_load_lands_somewhere_visible` | 加载失败不能写进折叠区 | 红 |
| `test_no_demo_scaffolding…` / `test_no_engineering_vocabulary…` | 参数化加上 family.html | 红 |

`check_identity_self_heal` **必须在浏览器里跑**。"common.js 里有 renew 字样"证明不了这条路径通：
第一版改完之后令牌确实换了，日报却还在报"老人账户不属于当前家庭"。查字符串会说它已经修好。

同样，`test_a_failed_family_load_lands_somewhere_visible` 第一版用正则在整份文件里找
"第一个 `catch (e)`"——命中的是 `approve()` 的那个，测试永远绿。变异测出来之后改成先定位
`load()` 再找。

---

## 尚未完成（诚实清单）

- 照护 / 可信 / 评委三页尚未重构
- **老人端**的页内分区导航（首页 / 记录 / 家人 / 我的）尚未实现——家人端的四个分区已经做了，
  老人端还没有；它的抽屉目前承担了这个角色
- 家人端「今天」分区里，`待您确认 / 进行中 / 今天到期` 三张数字卡在全 0 时仍占掉大半屏。
  数字为 0 时应该收成一行字，还没做
- 生活日报在"还不好说"那一态下的正文仍是后端拼的长句（"还在熟悉他的生活规律（已记录 0 天）"）。
  收起分项之后不再刷屏，但那一句本身还可以更短
- 参考仓库已克隆 5/6（midday 克隆失败），研究报告尚未产出
- 设计系统的字号、间距、阴影三条标尺尚未收敛（91 处字号仅 5 处用令牌；221 个间距字面量中 137 个非 4 倍数）
