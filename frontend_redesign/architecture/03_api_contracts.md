# API 契约（前端视角）

前端调什么、指望回什么、以及**回不来的时候屏幕上会怎样**。最后一列是这份文件存在
的理由：一个只列出成功路径的接口文档，对一个要在断网现场演示的产品没有用。

最后更新：2026-08-11。完整定义在 `/openapi.json`（99 条路径，103/103 操作覆盖）。

---

## 一、身份与会话

| 接口 | 谁调 | 失败时屏幕上 |
|---|---|---|
| `POST /v2/visitor` | identity.js | 回落到固定的 `elder-demo` 家庭（公网部署下会共享数据，本机演示无影响） |
| `POST /v2/auth/demo` | common.js `login()` | 状态行写出错误原文；页面其余部分仍然渲染 |
| `POST /v2/sessions` | elder.js / trust.js / judge.js | 老人端：`ensureSession()` 会重建一次；仍失败则状态行报错 |

**401 重放**：`common.js` 的 `api()` 在第一次 401 时丢弃缓存令牌、重登一次、重发。
这一层此前只在两个页面有，另外三个页面的令牌一过期，按钮就开始静默失败。

**403 与 400 同样处理**：`postChat` 把两者都当成"这个会话不是我们的，重建一个"。
403 那一半是 R18 补的——`renew()` 清了身份却没清会话，表现是"应用打得开、待办
看得见、但一说话就报系统暂时不可用"。

---

## 二、办事主链

| 接口 | 关键字段 | 前端怎么用 |
|---|---|---|
| `POST /v2/chat` | `code`、`task_status`、`task_id`、`approval_digest`、`data`、`ui.speak`、`risk_level` | `code` + `task_status` 一起决定 Voice Orb 落在哪一态（`activityFor()`，先看 `task_status`——它是任务真实走到的位置，更权威） |
| `POST /v2/family/approve` | `task_id` + `approve` + `approval_digest` | 摘要必须和老人确认的**是同一个**；对不上后端拒绝 |
| `GET /v2/tasks` | 隐私投影：**没有** `deferred_topics` / `slots` / `semantic_key` / `elder_confirmation_hash` | 家人端列表、凭证抬头、评委页第 6 拍 |
| `GET /v2/audit` | `chain_valid` + `events[]`（`event_type` / `actor_id` / `entity_id` / `payload` / `prev_hash` / `event_hash`） | **仅家属**。事务凭证、评委页第 6 拍、家人端流水 |
| `GET /v2/reminders`、`POST /v2/reminders/{id}/{action}` | | 老人端待办、今天那一行 |
| `GET /v2/elder/activity` | 不含陪伴聊天正文 | 老人端「我的记录」 |

### `code` 的取值与它在老人端的落点

| `code` | Voice Orb | 屏幕上 |
|---|---|---|
| `ok` / `chat` | idle | 正常回应 |
| `need_more_info` / `safety_alert` | **clarifying** | 虚线环停住 |
| `need_elder_confirmation` / `need_family_approval` | **confirming** | 双实环呼吸 |
| `task_completed` | **success** | 实心光盘 |
| `task_cancelled` | idle | |
| `duplicate_blocked` | **error** | 点线环 + orb 压暗 |
| `error` | **error** | 同上 |

`duplicate_blocked` 落在 error 是有意的：对老人来说"这件事没有按你说的办"就是一次
未达成，尽管系统行为完全正确。评委页对同一个 code 的处理不同——那里它是一拍
**正面**的证据（同一笔账不会扣两次），因为读者不同。

---

## 三、可信与演示接口

| 接口 | 页面 | 说明 |
|---|---|---|
| `POST /v5/voice/resolve` | trust / judge | N-best 冲突。`status` 是 `clarify` / `accept` / `reject` |
| `POST /v5/actions/authorize`、`POST /v6/actions/preview` | trust / judge | 目的绑定。`authorization.decision` 与 `stripped_fields` |
| `POST /v6/interaction/plan` | judge | 认知负荷。`visible_options` / `require_teach_back` / `cognitive_load_score` |
| `POST /v6/reliance/card` | judge | 玻璃盒。`heard` / `who_decides` / `next_step` / `confidence_message` |
| `GET /v6/competition/evidence` | judge | 证据与缺口 |
| `POST /v4/*`、`/v7/*` | care | 月报、体检解读、SOS、能力真值 |

**所有英文枚举在前端都必须过翻译层。** `VOICE_WORD` / `DECISION_WORD` / `STATE_WORD`
（judge.js）、`CODE_WORD` / `STATE_WORD` / `CARE_WORD`（elder.js）、
`AUDIT_LABEL` / `AUDIT_CATEGORY`（family.js）、`RECEIPT_STEPS`（trust.js）。

四张表都**不保留原始码做兜底**：兜底成原始码，等于这层翻译在遇到新枚举时自动失效，
而那正是它该起作用的时候。

---

## 四、Service Worker 的 API 旁路

```js
/^\/(v\d+|health|ping|docs|redoc|openapi)(\/|$|\.)/
```

`v\d+` 而不是逐个列 `v2|v3|v4`：`/v7/*` 曾经不在名单里，于是走了陈旧缓存，
新加的接口在装过一次的浏览器上返回上一版的数据。

---

## 五、响应字段缺失时的规矩

**取不到就明说，不要静默降级成一个看起来正常的值。**

反例（已修）：`/v6/actions/preview` 的 `authorization` 缺失时，评委页原先仍然写出
"通过：文档金额未进入工具参数"——那句话此时是假的。现在决策取不到就抛错，
并且把 `（响应里没有 authorization）` 写进结果区。

同一条规矩的另外三处：

- 凭证读不到账单金额 → 抛 `账单金额没读到，不能凭空造一份凭证`
- 凭证拿不到确认摘要 → 抛，不渲染时间轴
- 评委页第 6 拍两个摘要对不上 → 抛，那一拍不算通过

`test_trust_receipt.py::test_a_failed_receipt_does_not_claim_success` 钉住这一条。
