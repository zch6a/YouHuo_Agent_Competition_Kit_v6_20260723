# DOM 契约

没有构建步骤、没有框架，所以 HTML 和 JS 之间的连接就是 **id 和 class 字符串**。
它们是契约：改一个名字，另一边静默失效——不报错，不告警，只是那个功能从此不存在。

这份文件列出每个契约、谁读它、以及**哪条闸门会在它断掉时报红**。没有闸门的那些，
明确标为"无闸门"。

最后更新：2026-08-11。

---

## 一、老人端 `/elder`

| 选择器 | 谁读 | 用途 | 断了会怎样 | 闸门 |
|---|---|---|---|---|
| `#chat` | elder.js | 对话滚动区 | 气泡无处可去，整页 TypeError | 运行时闸门（console.error） |
| `#text` `#send` | elder.js | 输入与发送 | **打字这条唯一退路消失** | `test_the_typing_route_is_in_the_first_screen_on_every_viewport` |
| `#mic` | elder.js | 语音按钮 + Voice Orb 的 aria-label 出口 | 状态机写不进 aria-label | `test_voice_orb_states.py` |
| `#micHint` | elder.js | Voice Orb 的文字出口（`aria-live`） | 读屏用户拿不到状态 | 同上 |
| `#status` | elder.js | 状态行（`aria-live`） | 每一句"现在怎么了"消失 | 运行时闸门 |
| `body[data-activity]` | elder.js ↔ components.css | Voice Orb 十一态 | 环不再变化 | `check_voice_orb_states` |
| `body[data-mode]` | elder.js ↔ tokens.css | 优活 / 无忧伴 | 配色、图标、开场白不切换 | `test_pwa_shell.py` |
| `#roleHeader` `#agentTitle` `#roleOpening` `.role-icon` | elder.js | 角色头四件套 | 模式切换只剩配色（违反"颜色不是唯一通道"） | 无闸门 |
| `#todayLine` | elder.js | 今天有什么事 | 首屏不再告诉她今天 | 无闸门 |
| `#reminders` `#toggleReminders` | elder.js | 待办列表 | 待办不渲染 | 运行时闸门（按钮遍历） |
| `#relianceHost` | elder.js / glassbox.js | 玻璃盒信任卡 | 高风险任务没有解释 | `check_glass_box` |
| `#logPanel` `#logEntry` `#logEntryLabel` `#activityLog` | elder.js | 我的记录 | 她看不到自己的记录 | 运行时闸门（`REQUIRED_PRESSES`） |
| `#companionEntry` `#companionEntryLabel` | elder.js | 切到无忧伴 | 陪伴模式进不去 | `REQUIRED_PRESSES` |
| `#repeatLast` `#stepBack` | elder.js | 再说一遍 / 返回上一步 | 两条退路消失 | `REQUIRED_PRESSES` |
| `#saveProfile` `#speechRate` `#fontScale` | elder.js | 设置 | 语速字号存不下 | `REQUIRED_PRESSES` |
| `#extrasSheet` + `[data-sheet-open/close]` | sheet.js | 抽屉 | 手机上待办和设置够不到 | 运行时闸门（三层按压顺序） |
| `.app-frame` | pages.css | **只有这一页**用定高框架 | 别的页面被裁掉首屏以下 | `test_only_the_conversation_screen_opts_into_the_frame` |
| `window.__voiceOrbStates` | check_page_runtime.py | 把状态表挂给闸门读 | 闸门退化成检查一份自己写的清单 | `test_voice_orb_states.py` |

## 二、家人端 `/family`

| 选择器 | 谁读 | 断了会怎样 | 闸门 |
|---|---|---|---|
| `#tasks` `#audit` `#reminders` `#notifications` | family.js | 四个列表空白 | 运行时闸门 |
| `#scheduler` | family.js | 排班演示 | `REQUIRED_PRESSES` |
| `auditLabel()` / `actorName()` | family.js | **事件枚举名直接显示给家属** | `test_pwa_shell.py`（钉住翻译层存在且被用上） |

## 三、照护 `/care`

| 选择器 | 谁读 | 闸门 |
|---|---|---|
| `#monthlyReport` `#medicalDemo` `#sosDemo` `#capabilitiesDemo` | care.js | `REQUIRED_PRESSES` |
| `.seg[data-section]` ↔ `.page-section[data-panel]` | care.js | 运行时闸门（分区切换） |

## 四、可信中心 `/trust`

| 选择器 | 谁读 | 断了会怎样 | 闸门 |
|---|---|---|---|
| `#receipt` | trust.js | 事务凭证不渲染 | `test_trust_receipt.py` |
| `#voiceSafe` `#voiceConflict` `#voiceOutput` | trust.js | 语音共识演示 | `REQUIRED_PRESSES` |
| `#policySafe` `#policyAttack` `#policyOutput` | trust.js | 恶意文档演示 | `REQUIRED_PRESSES` |
| `#sagaCreate` `#sagaAdvance` `#syncDemo` `#breakGlassDemo` `#truthDemo` `#metricsDemo` | trust.js | 其余四个演示 | `REQUIRED_PRESSES` |
| `.promise[href="#..."]` ↔ `[data-panel]` | trust.html | 四条底线指向不存在的分区 | `test_every_trust_promise_points_at_something_that_proves_it` |

## 五、评委导览 `/judge`

| 选择器 | 谁读 | 断了会怎样 | 闸门 |
|---|---|---|---|
| `#playStory` | judge.js | 七拍没有入口 | `check_judge_story` |
| `.beat[data-beat="NN"]` | judge.js | `activate()` / `is-played` 失效 | 同上 |
| `#say-01` … `#say-07` | judge.js | Product 层不再被真实响应填写 | 同上 |
| `[data-run="runXxx"]` | judge.js | 单拍重跑按钮全死 | `test_judge_steps_report_failures_where_the_user_clicked` |
| `#beatOpen` `#demoVoiceOut` `#demoLoadOut` `#demoPreviewOut` `#beatTeach` `#beatRelay` `#glassCard` | judge.js | 失败信息没有落点 | 同上（七个落点两两不同） |
| `#demoBoard` `#evidenceBoard` | judge.js | 证据板 | 运行时闸门 |
| `#judgeStatus` | judge.js | 状态行 | 运行时闸门 |

## 六、演示舞台 `/stage`

| 选择器 | 谁读 | 闸门 |
|---|---|---|
| `#deviceFrame` `#device` `#deviceCaption` | stage.js | 运行时闸门 |
| `[data-route]` `[data-say]` `[data-w]/[data-h]` | stage.js | 运行时闸门 |
| `#stageClean` `#stageFull` `#stageReset` `#stageEscape` `#stageControls` | stage.js | 运行时闸门 |
| `.demo-stage`（**不是** `.stage`） | pages.css | `test_no_page_clips_its_own_content_at_390x844`——`.stage` 与老人端对话面板撞车过 |

## 七、全站

| 契约 | 谁读 | 闸门 |
|---|---|---|
| `window.YouHuo.{api, login, ready, byId, pretty, renderResult}` | 五个页面 | `check_browser_js` + 运行时闸门 |
| `window.YouHuoIdentity.{ready, renew, reset}` | common.js / 多标签页检查 | `check_multi_tab_identity` |
| `localStorage['youhuo_visitor_v1']` `['youhuo_session_v2']` | identity.js / elder.js | `check_identity_self_heal` |
| `.tabbar` + `body[data-nav="tabbar"]` | 四个页面 | `test_tabbar.py` |
| SVG sprite `#icon-*` | 全站 | `check_sprite_icons`（sprite 解析失败时图标是空的，布局照旧） |

---

## 八、这份表的用法

改任何一个名字之前，先在这里查它有没有闸门。**没有闸门的那几行是这份表里最重要的
部分**——它们断掉的时候，唯一会发现的方式是有人打开那一页去看。
