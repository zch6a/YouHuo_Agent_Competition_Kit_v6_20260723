# 状态与数据流

没有状态管理库。这份文件说清楚状态住在哪、谁写它、以及**两处状态互相矛盾时会怎样**。

最后更新：2026-08-11。

---

## 一、状态住在四个地方

| 层 | 例子 | 生命周期 | 谁写 |
|---|---|---|---|
| 后端 | 任务状态机、审计链、待办、画像 | 持久 | 只有后端 |
| `localStorage` | `youhuo_visitor_v1`（身份）、`youhuo_session_v2`（会话） | 跨刷新 | identity.js / elder.js |
| 模块变量 | `story`（评委页七拍）、`interactionProfile`、`promptHistory` | 一次页面加载 | 各页面 JS |
| DOM 属性 | `body[data-activity]`、`body[data-mode]`、`.beat.is-played` | 一次页面加载 | 各页面 JS |

**权威只有一个：后端。** 前端的三层都是它的投影。凡是"前端算出来的结论"和
"后端回报的状态"打架，一律以后端为准——事务凭证和评委页第 6 拍都从 `/v2/audit`
读摘要，而不是从刚才那次调用的回包里读，就是这条规则。

---

## 二、老人端的一轮

```
她开口 / 打字
   │
   ├─ setActivity('pressed') ──► Voice Orb 缩小 + 内阴影
   ├─ rec.onstart ────────────► 'listening'（环贴边 + 扩散波）
   ├─ rec.onresult → send()
   │
   ├─ setActivity('processing') ──► 一段弧在转
   ├─ POST /v2/chat
   │     ├─ 401 → 重登一次重发（common.js）
   │     └─ 400 / 403 → 这个会话不是我们的，重建一个再发一次
   │
   ├─ speak() ──► setActivity('speaking')（orb 光晕）
   │                └─ 看门狗：文本长度 × 500ms + 6s，上限 90s
   │
   ├─ finally: settleActivity(activityFor(data))
   │     └─ 正在说话就先寄存到 pendingSettle，说完再落
   │
   └─ onDone → setActivity(pendingSettle || 'idle')
```

三处并发保护：

| 保护 | 防什么 |
|---|---|
| `turnInFlight` | 两轮同时在办时，第二轮会抹掉第一轮挂起的支付确认卡 |
| `sessionPending` 记忆化 | 并发的两次 `ensureSession()` 各建一个会话 |
| Web Locks `youhuo-visitor-provision` | 三个标签页冷启动各开通一个家庭 |

一处互斥：`mic` 点击时先 `stopSpeaking()`。此前 agent 还在念的时候按麦克风，
识别器会把扬声器里 agent 自己的 TTS 转写下来，再当成老人这一轮发出去。

---

## 三、Voice Orb 的状态机

十一态，`elder.js` 的 `ACTIVITY` 常量一处定义。

```
                      ┌──────────────── offline ◄─── window 'offline'
                      │
  idle ──按下──► pressed ──rec.onstart──► listening
   ▲                                          │
   │                                     onresult
   │                                          ▼
   │                                     processing
   │                                          │
   │                                    POST /v2/chat
   │                                          ▼
   │            ┌──────────┬─────────────┬────┴─────┬──────────┐
   │       clarifying  confirming    executing   success     error
   │            └──────────┴─────────────┴──────────┴──────────┘
   │                                 │
   │                             speak() 期间一律 speaking
   └─────────────────────────────────┘
                （说完落到寄存的那一态；没有就回 idle）
```

`activityFor(data)` 先看 `task_status`（任务真实走到的位置），取不到再看 `code`。

**为什么不用一个 finite state machine 库**：这台机器只有十一个状态、一个变量、
一处写入点，而它的复杂度全在"哪一种后端回包落到哪一态"上——那是一张查找表，
不是状态转移图。

---

## 四、评委页七拍的共享状态

```js
const story = {session, taskId, amount, digest, mode};
```

`mode` 有两种，而且**必须让评委知道是哪一种**：

- `fresh` — 这一遍真的办了一笔。
- `replay` — 这个月的水费已经交过，后端回 `duplicate_blocked`。第 5、6 拍改从审计链
  里读上一次的记录，正文里写明"这是上一次的"。

第二种不是失败，是"同一笔账不会扣两次"这条规则在起作用。假装又办了一遍，就是在
一页专门讲可信的页面上撒谎。

演出期间整排按钮禁用：两场演出会争同一个 `story`，第二场的第 6 拍会拿第一场的摘要
去批第二场的任务。

---

## 五、存储访问一律包起来

```js
function readStore(key) { try { return localStorage.getItem(key); } catch (_) { return null; } }
```

Chrome 勾选"阻止所有网站数据"、无 `allow-same-origin` 的 sandbox iframe，
`window.localStorage` **一访问就抛** `SecurityError`。这行代码曾经在 `elder.js` 的
**模块顶层**裸写，抛了它下面的一切都不执行——老人打开这一页看到一张纯静态 HTML：
没有开场气泡、麦克风与发送和待办一个监听器都没绑、也没有任何错误提示。

全项目其他四个文件都有这层保护，只有这一个没有。

---

## 六、身份自愈

服务器不认识的身份（换库、换部署）必须被自动换掉，而不是把这个浏览器永久变砖：

```
API 回 404 / 身份不存在
   → identity.renew()
       ├─ reset()：清 youhuo_visitor_v1
       ├─ 清 youhuo_session_v2 ◄── R18 补的那一半
       └─ provision() 重新开通
   → 重发原请求
```

漏掉会话那一半的表现是"应用打得开、待办看得见、但一说话就报系统暂时不可用"，
刷新多少次都一样。

`check_identity_self_heal` 会写一个假身份进 `localStorage`，然后确认页面不再报错、
数据回来了、生活日报打得开。
