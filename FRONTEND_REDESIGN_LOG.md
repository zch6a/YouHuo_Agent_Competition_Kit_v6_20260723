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

## 尚未完成（诚实清单）

- 老人端首屏的三个「演示…」按钮（`elder.html:66-68`）**尚未删除**
- 家属端仍是 12 张卡 / 11121px，尚未重构
- 照护 / 可信 / 评委三页尚未重构
- 老人端与家属端的页内分区导航尚未实现
- 设计系统的字号、间距、阴影三条标尺尚未收敛（91 处字号仅 5 处用令牌；221 个间距字面量中 137 个非 4 倍数）
- 参考仓库已克隆 5/6（midday 克隆失败），研究报告尚未产出
