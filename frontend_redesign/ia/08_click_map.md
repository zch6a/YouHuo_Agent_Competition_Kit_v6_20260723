# 点击地图：从一次点击到数据库，再回到屏幕

这份文件回答一个问题：**在任意一个页面上点任意一个东西，会发生什么，代码在哪。**

内容是从源码里机械抽出来的（`<button id>` → JS 处理器 → 它打的接口），不是凭记忆写的
——99 个控件凭记忆必然出错。

最后更新：2026-08-11。

---

## 零、先看一条完整的链条

这是整个产品最重要的那一条：**老人说一句话，钱被交掉，两个人都点过头，链上留下证据。**

```
① 她按下大圆按钮
   elder.html:62            <button id="mic" class="mic-big">
   elder.js:772             mic click → setActivity('pressed')      ← Voice Orb 缩小+内阴影
                            rec.start()                            ← Web Speech API
   elder.js:740             rec.onstart → setActivity('listening')  ← 环贴边+扩散波
   elder.js:745             rec.onresult → input.value = 转写文本 → send()

② 她说「帮我交这个月的水费」（或者直接在 #text 里打字，按 #send，同一条路）
   elder.js:545             send()
                            setActivity('processing')               ← 一段弧在转
   elder.js:431             postChat(text)
   elder.js:415               └ ensureSession() → POST /v2/sessions
                              └ POST /v2/chat  {session_id, text, request_id}

③ 后端
   api.py:374               @app.post("/v2/chat") → engine.handle(actor, payload)
   engine.py:135            handle()
                              ├ semantic_router.py    这句话想干什么（关键词+语义）
                              ├ security.py           SafetyPolicy：这件事允不允许
                              ├ document_guard.py     外来文字只当数据，不当指令
                              ├ services.py           查账单接口 → 68.40 元
                              ├ teach_back.py         高风险 → 要求复述金额
                              ├ orchestration.py      任务规划/校验/委派
                              ├ privacy.py            落盘前脱敏
                              └ database.py           写任务 + 写审计链（逐条哈希相连）
                            返回 {code, task_status, task_id, approval_digest, data, ui, message}

④ 回到屏幕
   elder.js:451             adaptAgentMessage() → POST /v6/interaction/plan
                              （认知负荷治理：四个选项压成一个，要求复述而不是点"是"）
   elder.js:197             addBubble(...)        → #chat 里加一条气泡
   elder.js:221             speak(...)           → setActivity('speaking')  ← orb 光晕
   speech.js:349              speakClauses()     → POST /v6/speech/synthesize（离线神经语音）
                                                   失败逐句回落 window.speechSynthesis
   elder.js:519             showGlassBox()       → GET /v6/tasks/{task_id}/glass-box
   glassbox.js                renderGlassBox()   → #relianceHost 渲染信任卡
   elder.js:602             loadReminders()      → GET /v2/reminders → #reminders + #todayLine
   elder.js:610             settleActivity(activityFor(data))
                              → Voice Orb 落到十一态里的一个（confirming / success / error…）

⑤ 她念「确认支付68.40元」——同一条 ②③④，但这一轮 teach_back 通过
   task_status: awaiting_elder_confirmation → awaiting_family_approval
   拿到 approval_digest

⑥ 女儿在家人端点同意
   family.html              需要您处理 那一栏的按钮
   family.js:               POST /v2/family/approve {task_id, approve, approval_digest}
   api.py:381               → engine.approve()
                              摘要必须和老人确认的**是同一个**，对不上不执行
   engine.py:1009           执行 → 权威状态回报成功 → task_status: completed

⑦ 证据
   trust.js                 GET /v2/audit → 按 entity_id 筛出这一件任务
                            渲染成事务凭证时间轴（#receipt）
   judge.js                 同一条链，第 6 拍展示"两个摘要一致"
```

**这条链上没有一步是模拟的。** `/trust` 打开时真的走一遍，`/judge` 的「从头演一遍」
真的走一遍。

---

## 一、项目树

```
F:\优活\YouHuo_Agent_Competition_Kit_v6_20260723\
│
├── backend/
│   ├── youhuo/                        后端（39 个 .py）
│   │   ├── api.py                578行  /v2 /v3 + 七个 HTML 路由 + CSP 响应头
│   │   ├── engine.py            1670行  ★ 对话与任务状态机的中心
│   │   ├── database.py           871行  SQLite WAL + 审计哈希链 + 幂等
│   │   ├── security.py          336行  SafetyPolicy：这件事允不允许
│   │   ├── document_guard.py     218行  外来文字只当数据（"别人写的字不算你的指令"）
│   │   ├── teach_back.py         205行  复述确认（念错就停）
│   │   ├── semantic_router.py    182行  这句话想干什么
│   │   ├── orchestration.py      254行  任务规划 / 校验 / 委派
│   │   ├── privacy.py            205行  落盘前脱敏
│   │   ├── services.py           385行  账单/挂号等外部服务（沙箱）
│   │   ├── care_voice.py         472行  照护类问答的口语化
│   │   ├── companion.py          132行  无忧伴陪伴模式
│   │   ├── speech / tts.py       151行  离线神经语音
│   │   ├── v4_api.py + v4_*      38 条路由  照护平台（月报、体检、用药、SOS、定位）
│   │   ├── v5_api.py + v5_*      20 条路由  可信内核（语音共识、Saga、破窗、能力真值）
│   │   ├── v6_api.py + v6_*      13 条路由  适老交互（负荷治理、玻璃盒、竞赛证据）
│   │   ├── baseline_api.py       4 条路由   个性化基线与生活日报（/v7）
│   │   └── provenance.py          23行  给重型报告盖源码指纹
│   │
│   ├── static/                        前端（无构建步骤）
│   │   ├── tokens.css        11.2KB  ① 只有变量（颜色/间距/阴影/圆角/字号）
│   │   ├── base.css           7.4KB  ② 元素默认 + `.needs-server { display:none }`
│   │   ├── components.css    49.1KB  ③ 可复用组件（含 Voice Orb 十一态）
│   │   ├── pages.css         74.7KB  ④ 页面 + **全部响应式覆盖**（必须最后）
│   │   │
│   │   ├── index.html         4.4KB  /        角色选择
│   │   ├── elder.html        15.8KB  /elder   老人端（唯一带 .app-frame 定高框架）
│   │   ├── family.html        8.3KB  /family  家人端
│   │   ├── care.html         16.1KB  /care    照护中心
│   │   ├── trust.html        12.7KB  /trust   可信中心（顶部事务凭证）
│   │   ├── judge.html        12.7KB  /judge   评委导览（七拍）
│   │   ├── stage.html         5.7KB  /stage   桌面演示舞台（真 iframe）
│   │   │
│   │   ├── common.js         20.7KB  ★ api() / login() / ready() / renderResult()
│   │   ├── identity.js        6.2KB  访客身份 + Web Locks 跨标签页互斥
│   │   ├── elder.js          44.0KB  老人端（Voice Orb 十一态在这里）
│   │   ├── speech.js         16.2KB  分句朗读、日期金额口语化
│   │   ├── glassbox.js        5.1KB  信任卡渲染
│   │   ├── sheet.js           6.6KB  底部抽屉（手势 + inert + 焦点归还）
│   │   ├── family.js         26.0KB  家人端 + auditLabel/actorName 翻译层
│   │   ├── care.js           11.8KB  照护中心
│   │   ├── trust.js          18.0KB  可信中心 + 事务凭证
│   │   ├── judge.js          20.4KB  七拍 + 三张枚举翻译表
│   │   ├── landing.js         2.6KB  首页
│   │   ├── stage.js           6.3KB  舞台（JS 提需求 --want-*，CSS 钳上限）
│   │   ├── register-sw.js     0.6KB  注册 SW（/stage 刻意不注册）
│   │   ├── sw.js              5.6KB  外壳缓存 + API 旁路 /^\/(v\d+|health|…)/
│   │   └── icons/                    6 个 PNG + SVG sprite
│   │
│   ├── scripts/                       闸门
│   │   ├── check_page_runtime.py      真浏览器：7 页 99 控件 + Orb 11 态 + 七拍
│   │   ├── check_contrast.py          14 个页面×模式
│   │   ├── check_browser_js.py        14 个 JS 按真实加载方式
│   │   ├── shoot_pages.py             126 组 / 252 个文件
│   │   ├── make_release.py            按 git ls-files 打包 + MANIFEST
│   │   └── …（基准、海量断言、契约、鸿蒙静态检查）
│   │
│   └── tests/                         48 个文件 / 994 项
│
├── harmonyos/                         鸿蒙 ArkTS 工程（18 个 .ets）
├── frontend_redesign/                 这一轮的文档（14 份，含本文件）
├── competition_materials/             六份参赛材料
├── reports/                           验证产物（含重型报告 + 源码指纹）
├── KNOWN_ISSUES.md                    已知未修（P0/P1 各 0）
└── TEST_REPORT_FRONTEND.md            前端测试报告
```

**接口总数 99 条**：v2:14 · v3:9 · v4:38 · v5:20 · v6:13 · v7:4 · health:1。

---

## 二、页面之间怎么走

```
                        ┌─────────────────┐
                        │   /  角色选择    │
                        │  index.html     │
                        └────┬───┬───┬────┘
             我是老人 ────────┘   │   └──── 演示与可信技术 →
                                 │                    │
                          我是家人│                    │  在电脑上演示 →
                                 │                    │           │
   ┌──────────────┐        ┌─────▼──────┐      ┌──────▼─────┐  ┌──▼────────┐
   │ /elder       │        │ /family    │      │ /judge     │  │ /stage    │
   │ 老人端       │        │ 家人端     │      │ 评委导览   │  │ 演示舞台  │
   │ 手机专用     │        │            │      │ 七拍       │  │ 桌面专用  │
   └───┬──────────┘        └──┬──────┬──┘      └──┬───┬─────┘  └──┬────────┘
       │                      │      │            │   │           │
       │ 返回 → /             │      │ 照护档案   │   │ 进入老人端 │ iframe 换 src
       │                      │      ▼            │   └───────────┼──► 五个页面
       │                      │  ┌────────────┐   │               │   任选其一
       │                      │  │ /care      │   │ 可信中心      │
       │                      │  │ 照护中心   │   ▼               │
       │                      │  └─────┬──────┘ ┌────────────┐   │
       │                      │        │        │ /trust     │   │
       │                      │ 可信中心│        │ 可信中心   │   │
       │                      └────────┴───────►└────────────┘   │
       │                                                          │
       └──────────────────────────────────────────────────────────┘

底部标签栏（只在 ≤760px 且 family/care/trust/judge 四页）：首页 · 家人 · 照护
≥761px 标签栏隐藏，改用 .back-link；/elder 没有标签栏，所以 .back-link 永远显示
```

---

## 三、逐页：内容 → 点击 → 代码

### `/` 角色选择 · `index.html` + `landing.js`

| 内容 | |
|---|---|
| H1 | 优活 |
| 正文 | 让生活简单一点。 |

| 点什么 | 发生什么 | 代码 |
|---|---|---|
| 我是老人 | → `/elder` | `index.html` `<a class="role-pick">` |
| 我是家人 | → `/family` | 同上 |
| 演示与可信技术 → | → `/judge` | 底部小字 |
| 在电脑上演示 → | → `/stage` | 底部小字 |

**不打任何接口。** 这一页是分流，零 DOM 契约、零 API、零 id。

---

### `/elder` 老人端 · `elder.html` + `elder.js` / `speech.js` / `glassbox.js` / `sheet.js`

| 内容（自上而下） | |
|---|---|
| 角色头 | 图标 + 「优活」/「无忧伴」+ 开场白 |
| 今天 | `#todayLine`——今天有什么事，没有待办时整行隐藏 |
| 对话 | `#chat`，唯一可滚动区域 |
| 信任卡 | `#relianceHost`，高风险任务时出现 |
| **Voice Orb** | `#mic` + `#micHint`，十一态 |
| 常说的话 | 三个 chip：今天有什么事 / 交水费 / 挂号 |
| 输入行 | `#text` + `#send`——语音失败时唯一的退路 |
| 抽屉 | `#extrasSheet`：我的待办 / 常用 / 我的记录 / 问问看 / 看得清听得懂 |

| 点什么 | 发生什么 | 接口 |
|---|---|---|
| `#mic` 大圆按钮 | pressed → listening → 转写 → `send()` | Web Speech，无接口 |
| `#send` 发送 | `send()` 整条链（见第零节） | `/v2/sessions` `/v2/chat` `/v6/interaction/plan` `/v6/tasks/{id}/glass-box` `/v2/reminders` |
| 三个 chip | 填进 `#text` 再走 `send()` | 同上 |
| `#openExtras` 待办、常用和设置 | 打开抽屉（`sheet.js`，焦点进入、Esc 关闭并归还） | 无 |
| `#toggleReminders` 查看全部待办 | 全部/只看今天 | `/v2/reminders` |
| 待办上的「完成」/「知道了」 | 改待办状态 | `/v2/reminders/{id}/{action}` |
| `#companionEntry` 找无忧伴聊聊 | 切模式：配色+名字+图标+开场白+**音高**都换 | 无（`setMode`） |
| `#logEntry` 查看我的记录 | 抽屉里展开 `#logPanel` | `/v2/elder/activity` |
| `#repeatLast` 再说一遍 | 重念上一句 | 无（`speak()`） |
| `#stepBack` 返回上一步 | 回到上一个提问，**任务不取消** | 无 |
| `#saveProfile` 保存我的习惯 | 存语速与字号 | `/v6/profiles/{elder_id}` |
| 语速 / 字号下拉 | 立即生效 | 同上 |

**这一页独有的三件事**：`.app-frame` 定高框架（全站只有它）、Voice Orb 十一态、
输入行在七个视口下都必须在首屏。

---

### `/family` 家人端 · `family.html` + `family.js`

| 内容 | |
|---|---|
| H1 | 家里今天 |
| 分区（`.seg`） | 今天 / 待办 / 趋势 / 我的 |
| 今天怎么样 | 三个数字：待您确认 / 进行中 / 今天到期 |
| 需要您处理 | 等她点头的任务，带摘要 |
| 按日期 / 这一周 | 待办与趋势 |
| 给他添一件事 | 家人代建待办 |
| 通知 / 做过的事 | 审计流水（**全部过翻译层**） |

| 点什么 | 发生什么 | 接口 |
|---|---|---|
| 四个 `.seg` | 切分区（不重新请求） | 无 |
| `#refresh` 刷新 | 四个列表一起重取 | `/v2/tasks` `/v2/audit` `/v2/reminders` `/v2/notifications` |
| 任务上的「同意」 | **摘要必须和老人确认的一致** | `/v2/family/approve` |
| 任务上的「拒绝」 | 不执行任何支付 | 同上 |
| 添一件事 | 代建待办 | `/v2/family/reminders` |
| `#scheduler` 立即检查到期待办 | 触发调度评估 | `/v2/demo/scheduler/evaluate` |
| 日报 / 心情 | 生活日报、情绪报告 | `/v7/daily-report/{id}` `/v4/reports/emotion/{id}` |

**翻译层**：`auditLabel()` / `actorName()`（`family.js:89–119`）把
`FAMILY_APPROVED_AND_EXECUTED` 变成「同意后办好了」。**不保留原始码兜底**——兜底成
原始码等于这层翻译遇到新事件时自动失效。

---

### `/care` 照护中心 · `care.html` + `care.js`

| 分区 | 内容 |
|---|---|
| 他今天怎么样 | 个性化基线（千人千面）：常态 vs 今天 |
| 日常与用药 | 日常安排物化、用药相互作用 |
| 心情与身体 | 情绪分析、体检报告解读 |
| 安全 | 定位围栏、SOS |
| 这些能力到哪一步了 | 能力矩阵（**明确区分已实现 / 待真机 / 禁止宣传**） |

| 点什么 | 接口 |
|---|---|
| `#baselineDemo` 看他自己的常态与今天 | `/v7/baseline/{id}` `/v7/care/{id}` |
| `#coldRoomDemo` 上报「屋里 13.5℃」 | `/v7/environment/samples` → 关怀语变化 |
| `#lateWakeDemo` 模拟「今天 11:20 才起」 | `/v7/baseline/{id}` → 偏离 |
| `#routineDemo` 创建并物化"每月交水费" | `/v4/routines` `/v4/routines/materialize` |
| `#monthlyReport` 本月隐私月报 | `/v4/reports/monthly` |
| `#interactionDemo` 华法林 + 阿司匹林 | `/v4/medications/interactions/check` |
| `#emotionDemo` 分析并生成隐私信号 | `/v4/emotions/analyze` |
| `#medicalDemo` 安全解读并归档 | `/v4/medical-reports/analyze` |
| `#locationInside` / `#locationOutside` | `/v4/location/ping` |
| `#sosDemo` 模拟老人主动呼救 | `/v4/safety/sos` |
| `#capabilitiesDemo` 加载能力矩阵 | `/v4/capabilities` |

---

### `/trust` 可信中心 · `trust.html` + `trust.js`

**顺序是这一页的设计**：主张 → 四条底线（可点，跳到证明它的分区）→ **事务凭证** →
五个分区。

| 内容 | |
|---|---|
| 主张 | 优活替你办事，但不替你做决定。 |
| 四条底线 | 自主权包络 / 家庭共识 / 证明式完成 / 同意记忆（各自 `→` 跳到对应分区） |
| **`#receipt` 事务凭证** | 打开页面时**真办一次水费**，从审计链渲染成时间轴 |
| 分区 | 听不清 / 文档 / 中断 / 紧急 / 进度 |

凭证自己就是一条链（`trust.js` `renderReceipt()`）：

```
POST /v2/sessions → POST /v2/chat（帮我交这个月的水费）
                  → POST /v2/chat（确认支付68.40元）  ← 真的走复述
                  → POST /v2/family/approve
                  → GET /v2/audit  按 entity_id 筛出这一件
                  → GET /v2/tasks  取抬头
渲染：抬头 → 「他说的原话不在链上」→ 六条时间轴（带毫秒）→ 链条自校验 + 哈希折叠
办不成就说办不成，不画漂亮时间轴。
```

| 点什么 | 接口 |
|---|---|
| 四条底线 | 页内锚点（`test_every_trust_promise_points_at_something_that_proves_it` 钉住不许指向不存在的分区） |
| 五个 `.seg` | 切分区 |
| `#voiceSafe` / `#voiceConflict` | `/v5/voice/resolve` |
| `#policySafe` / `#policyAttack` | `/v5/actions/authorize` |
| `#sagaCreate` / `#sagaAdvance` | `/v5/sagas` `/v5/sagas/{id}` |
| `#syncDemo` 生成高敏感冲突 | `/v5/sync/operations` |
| `#breakGlassDemo` 开启10分钟最小访问 | `/v5/break-glass` |
| `#truthDemo` / `#metricsDemo` | `/v5/capability-truth` `/v5/metrics` |

---

### `/judge` 评委导览 · `judge.html` + `judge.js`

七拍跟着**同一件事**走。每拍两层：Product 层（默认可见，由真实响应填写）+
Proof 层（`<details>`：机制名、接口、原始响应、单独重跑）。

| 拍 | 标题 | 接口 | 落点 |
|---|---|---|---|
| 01 | 她开口 | `/v2/sessions` `/v2/chat` | `#beatOpen` |
| 02 | 听不清，就不猜 | `/v5/voice/resolve` | `#demoVoiceOut` |
| 03 | 一次只问一件事 | `/v6/interaction/plan` | `#demoLoadOut` |
| 04 | 账单图片说 9999.99 | `/v6/actions/preview` | `#demoPreviewOut` |
| 05 | 她得把金额念一遍 | `/v2/chat`（复述） | `#beatTeach` |
| 06 | 第二个人点头 | `/v2/family/approve` + `/v2/audit` | `#beatRelay` |
| 07 | 办好了，说得清为什么 | `/v6/reliance/card` | `#glassCard` |

| 点什么 | 发生什么 |
|---|---|
| `#playStory` 从头演一遍 | 01→07 顺序跑，每拍间隔 420ms；整排按钮禁用（两场演出会争同一个 `story` 对象） |
| 每拍的「单独跑这一拍」 | `[data-run="runXxx"]` → 对应处理器 |
| `#demoBoard` 加载证据与缺口 | `/v6/competition/evidence` |

**第二次按「从头演一遍」**：后端回 `duplicate_blocked`（同一笔账不会扣两次）。
第 1 拍如实说"没有为了演示再扣一次"，第 5、6 拍改从审计链读上一次的记录，
并在正文里写明"这是上一次的"。

**三张枚举翻译表**（`judge.js:49–64`）：`VOICE_WORD` / `DECISION_WORD` / `STATE_WORD`。
`check_judge_story` 演完之后逐句断言 Product 层**不含英文**。

---

### `/stage` 桌面演示舞台 · `stage.html` + `stage.js`

框里是**真 iframe**，不是 `transform: scale()`——App 必须在 390px 视口里真的跑起来，
媒体查询、`env(safe-area-inset-*)`、`100dvh`、抽屉的 `position: fixed` 全依赖真实视口宽度。

| 点什么 | 发生什么 |
|---|---|
| 看哪一端（5 个） | `[data-route]` → 换 iframe `src`：`/elder` `/family` `/care` `/trust` `/judge` |
| 演示台词（5 个） | `[data-say]` → 填进 iframe 里老人端的 `#text`，点 `#send`——**走应用自己那条路** |
| 视口（3 个） | `[data-w]/[data-h]`：390×844 / 320×568 / 412×915。JS 只提 `--want-*`，上限由 CSS 钳 |
| `#stageClean` 答辩模式 | 控制区整体 `inert` + `aria-hidden`，**留一个出口**（`#stageEscape` + Esc） |
| `#stageFull` 全屏 | Fullscreen API |
| `#stageReset` 重新开始 | 重载 iframe |

这一页**刻意不注册 service worker**：会缓存自己的舞台在反复改版时只会给出昨天的样子。

---

## 四、全站共用的三条链

### 身份

```
common.js ready()
  → identity.js provisionOnce()
      navigator.locks.request('youhuo-visitor-provision')   ← 跨标签页互斥
        → POST /v2/visitor  拿到独立演示家庭
        → localStorage['youhuo_visitor_v1']
  失败 → 回落固定的 elder-demo
服务器不认识这个身份 → renew()：清身份 **并清会话** → 重新开通 → 重发原请求
```

### 请求

```
common.js api(path, options, role)
  → 缓存令牌 或 login(role) → POST /v2/auth/demo
  → fetch
  → 401 → 丢令牌、重登一次、重发
elder.js postChat 另加：400/403 → 这个会话不是我们的，重建一个再发一次
```

### 离线

```
register-sw.js → sw.js
  外壳：7 个 HTML + 4 个 CSS + 14 个 JS + 图标 + manifest（stale-while-revalidate）
  API 旁路：/^\/(v\d+|health|ping|docs|redoc|openapi)(\/|$|\.)/
           ← `v\d+` 而不是逐个列，因为 /v7/* 曾经不在名单里、走了陈旧缓存
```

---

## 五、两个必须知道的边界

**一、必须用服务器打开。** 七个页面引用样式用的是 `/static/...` 绝对路径（它们被服务
在 `/elder`、`/trust` 这种路径上，相对路径会算错）。双击 HTML 用 `file://` 打开时，
四个 CSS 和全部 JS 一次性 404，剩下透明 body 压在浏览器画布上 = **一片黑**。

现在那种情况下屏幕第一行会写「这个页面要用服务器打开」——靠 `base.css` 里一条
`.needs-server { display: none }`：CSS 在就看不见，CSS 不在就它最显眼。

**二、`/elder` 只在手机视口下是完整的。** 它是全站唯一带 `.app-frame` 的页面。
≤540px 高（手机横屏）时麦克风移到左侧固定栏、对话区压到 16dvh。

正确的打开方式：

```bash
start http://127.0.0.1:8041/
```
