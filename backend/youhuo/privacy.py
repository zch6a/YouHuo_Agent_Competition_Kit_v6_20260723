from __future__ import annotations

import re
from typing import Any

from .models import AuditEvent, ElderActivityEntry, TaskRecord, TaskType, TaskView
from .utils import normalize_text


# 边界是「不紧邻**字母或数字**」，不是「不紧邻数字」。
#
# ## 为什么：`(?<!\d)...(?!\d)` 会把哈希摘要切开
#
# 一个 64 位十六进制摘要里，数字紧邻的往往是十六进制**字母**，而那种守卫
# 只排除相邻的数字。于是 `_BANK_CARD` 会在摘要中间找到一段 13–19 位连续数字
# 并把它换成 `[银行卡号已脱敏]`。实测 20 万个 sha256：**9161 个被改掉，4.58%**。
#
#     3fdba35f04dc8c462986c992bcf875546257113072a909c162f7e470e581e278
#  →  3fdba35f04dc8c462986c992bcf[银行卡号已脱敏]a909c162f7e470e581e278
#
# 这条路是活的：`redact_payload` 会走到 `data.verification.proof_digest`，
# 而 `trust.js` 把它当「回执」渲染。也就是说**大约每 22 张回执有一张印着
# 一个残缺的摘要**——而这个产品「每一步可核验」的全部凭据就是那个摘要。
# 它是间歇的，所以一直没被看见（有 agent 的判据被它红过一次，当噪音）。
#
# 改成 `(?<![0-9A-Za-z])` / `(?![0-9A-Za-z])` 之后，摘要成了一整段字母数字，
# 里面任何子串都不满足两侧边界，于是不再被切。而人写出来的号码两侧是空格、
# 标点或中文，照旧命中——`_ID_CARD` 右边本来就用的是 `(?!\w)`，
# 这一处等于把那个正确写法推广到四条。
_EDGE_L = r"(?<![0-9A-Za-z])"
_EDGE_R = r"(?![0-9A-Za-z])"
_PHONE = re.compile(_EDGE_L + r"1[3-9]\d(?:[ -]?\d){8}" + _EDGE_R)
_ID_CARD = re.compile(_EDGE_L + r"\d{17}[0-9Xx]" + _EDGE_R)
_BANK_CARD = re.compile(_EDGE_L + r"(?:\d[ -]?){13,19}" + _EDGE_R)
_CODE = re.compile(_EDGE_L + r"\d(?:[ -]?\d){3,7}" + _EDGE_R)
_SECRET_KEYS = {
    "password", "passwd", "pwd", "密码", "验证码", "校验码",
    "token", "access_token", "refresh_token", "api_key", "apikey",
    "secret", "client_secret", "identity_token", "face_template_digest",
}


def redact_text(text: str) -> str:
    value = _PHONE.sub("[手机号已脱敏]", text)
    value = _ID_CARD.sub("[身份证号已脱敏]", value)
    value = _BANK_CARD.sub("[银行卡号已脱敏]", value)
    # Only redact standalone verification-like codes when context implies a code.
    if any(word in value for word in ("验证码", "校验码", "短信码")):
        value = _CODE.sub("[验证码已脱敏]", value)
    return value


def redact_payload(value: Any) -> Any:
    if isinstance(value, str):
        return redact_text(value)
    if isinstance(value, dict):
        result: dict[str, Any] = {}
        for key, item in value.items():
            rendered = str(key)
            canonical = normalize_text(rendered).replace("-", "_").replace(" ", "_")
            result[rendered] = "[已隐藏]" if canonical in _SECRET_KEYS else redact_payload(item)
        return result
    if isinstance(value, list):
        return [redact_payload(v) for v in value]
    if isinstance(value, tuple):
        return [redact_payload(v) for v in value]
    return value


# Allow-list of audit events the elder may read, with the plain-language wording
# used on the elder home page. Anything absent here (scheduler ticks, semantic
# frames, per-turn cognitive plans, internal digests) is omitted rather than
# shown with a raw event name.
#: `SAFETY_POLICY_UPDATED` 那一句里要点名的**每一样**设置。
#:
#: 这张表是句子的唯一出处，句子从它拼出来。原先句子是手写的字面量
#: 「改了安全设置：多久没动静提醒、活动范围这些。」——**两样**，
#: 而它上面那条注释（`_ELDER_ACTIVITY_LABELS` 里 `SAFETY_POLICY_UPDATED`
#: 那一行）写的是**三样**：「多久没动静提醒、活动范围、要不要找社区」。
#: 注释和字符串各说一套，而漏掉的那一样恰好是最要紧的那一样。
#:
#: 为什么「要不要找社区」不能漏：`youhuo-location-safety/SKILL.md` 写着
#: 「SOS优先通知绑定家属，**社区联系人仅在老人授权策略开启时加入**」。
#: 实测（女儿一个人 PUT `/v4/safety/policy`，`notify_community: true`）：
#: 库里存下了，她按下求助时 `community_escalation_prepared: true`，
#: 接力名单里出现「社区网格员」。而她那一屏读到的是
#: 「改了安全设置：多久没动静提醒、活动范围这些。」
#: ——**一个外人进了她的紧急联络链，而那句话没提这件事。**
#:
#: 键是 `SafetyPolicyUpdate` 的字段名；判据
#: `test_the_line_about_her_safety_settings_names_all_of_them.py`
#: 要求那个模型的每个字段（除 `elder_id`）都被这张表覆盖到——
#: 加第四样设置时这里不跟着改就会红。
_SAFETY_POLICY_SETTINGS: dict[str, str] = {
    "inactivity_minutes": "多久没动静提醒",
    "home_lat": "活动范围",
    "home_lon": "活动范围",
    "geofence_radius_m": "活动范围",
    "notify_community": "要不要找社区",
}

#: 去重保序之后拼成一句话。不带主语——`who` 由动作人定，
#: 带了主语「家人」那一行就会写着「您……」。
_SAFETY_POLICY_SENTENCE: str = "改了安全设置：" + "、".join(
    dict.fromkeys(_SAFETY_POLICY_SETTINGS.values())) + "。"


_ELDER_ACTIVITY_LABELS: dict[str, tuple[str, str]] = {
    "TASK_CREATED": ("优活", "task"),
    "ELDER_CONFIRMED": ("您", "task"),
    "TASK_EXECUTED": ("优活", "task"),
    "TASK_FAILED": ("优活", "task"),
    "TASK_CANCELLED": ("您", "task"),
    "FAMILY_APPROVAL_RECORDED": ("家人", "task"),
    "FAMILY_APPROVED_AND_EXECUTED": ("家人", "task"),
    "FAMILY_APPROVED_EXECUTION_FAILED": ("家人", "task"),
    "FAMILY_REJECTED": ("家人", "task"),
    "FAMILY_REMINDER_CREATED": ("家人", "reminder"),
    "REMINDER_ACKNOWLEDGE": ("您", "reminder"),
    "REMINDER_COMPLETE": ("您", "reminder"),
    "REMINDER_CANCELLED": ("您", "reminder"),
    "MODE_SWITCHED": ("您", "mode"),
    #: 暂停是优活替她做的主张，接着办是**她自己**开口要的（「接着办」）。
    "EMOTIONAL_TASK_RESUMED": ("您", "mode"),
    "EMOTIONAL_TASK_PAUSE": ("优活", "safety"),
    "SAFETY_SIGNAL": ("优活", "safety"),
    "SUSPICIOUS_INSTRUCTION_BLOCKED": ("优活", "safety"),
    # RELIANCE_CARD_CREATED and SAFE_ACTION_PREVIEWED are deliberately absent.
    # They fire automatically on every confirmation turn and the card is already
    # on screen, so logging them again crowded out the entries that describe
    # what was actually done. The family audit chain still records them in full.
    "DOCUMENT_ANALYZED": ("优活", "trust"),
    # 交互档案：语速、字号、句子长短这些。**双方都可能改**
    # （家人在 `/v6/profiles` 上也改得动），所以 `who` 由 `_WHO_FROM_ACTOR`
    # 按动作人定，这里写的「家人」只是占位。和 `SAFETY_POLICY_UPDATED` 同款。
    "INTERACTION_PROFILE_UPDATED": ("家人", "profile"),
    # Care *queries* stay out: the log records what was done to the elder, and a
    # read-only question changed nothing. The two profile writes below did.
    "CARE_PROFILE_SPEECH_RATE": ("您", "profile"),
    "CARE_PROFILE_HEARING_SUPPORT": ("您", "profile"),
    "MEMORY_APPROVED": ("您", "privacy"),
    "MEMORY_REJECTED": ("您", "privacy"),
    "MEMORY_REVOKED": ("您", "privacy"),
    # 家属开了紧急访问、读了她的资料。**这一条必须让她看得见。**
    #
    # 实测：家人 `POST /v5/break-glass` + `GET .../view` 真的读到了坐标，
    # 而老人这一侧只有一条收件箱通知——`elder.js` / `elder3.js` 两份加起来
    # 41 个端点，没有一个读收件箱。记录页是她现成的那一屏，放这里。
    "BREAK_GLASS_OPENED": ("家人", "privacy"),
    # 「开了权限」和「真的读了」是两件事，两条都要有。
    "BREAK_GLASS_VIEWED": ("家人", "privacy"),
    # 同一个形状：别人取走了她的就医单据。`/elder3` 那一侧一直看得到
    #（`app_api._WORDS` 里有「有人看了您的就医单据」），`/elder2` 没有。
    "MEDICAL_DOCUMENT_READ": ("家人", "privacy"),
    # 有人调阅了她某件事的说明（`GET /v5/tasks/{id}/explain`）。
    #
    # 原先它只在 `app_api._MACHINERY` 里，理由是「只是打开看了看，没动任何
    # 东西」——而那个理由在上面那一行（就医单据）已经被否过一次。实测家属
    # 调阅一次，审计里有 `TASK_EXPLANATION_VIEWED by=daughter-demo`，
    # 而她的 `/v2/elder/activity` 和 `/api/v1/records` **各 0 行**；
    # 同一趟的对照——家属看她的就医单据——她那一屏当场多出
    # 「家人看了您的一份就医单据。」
    #
    # 回的 `what_i_understood` 里有 `amount_cents：6840`、`bill_id`、
    # `bill_type`，所以这不是空看一眼。
    #
    # **`who` 由动作人定**（进了 `_WHO_FROM_ACTOR`），不像就医单据那一行
    # 写死「家人」：她自己也调得动自己那件事的说明，写死就会让她读到
    # 「家人看了……」——一句没发生的事。所以句子里不带主语。
    "TASK_EXPLANATION_VIEWED": ("家人", "privacy"),
    # 安全设置：多久没动静提醒、活动范围、要不要找社区。
    # **双方都可能改**，所以 `who` 由 `_WHO_FROM_ACTOR` 按动作人定，
    # 这里写的「家人」只是占位（下面那段会覆盖它）。
    "SAFETY_POLICY_UPDATED": ("家人", "privacy"),
    # ---- `/api/v1` 那一层写的事（事件名是点号小写的那一套） ----------------
    #
    # 这些是她在 `/elder3`、`/app`、`/family3` 上真做过的事。实测每一下**只**写
    # 一条 `app.*`，不再另写 `/v2` 那套 `TASK_*`——所以这里加进来不会重复记账。
    #
    # 在此之前这张表里点号事件是 0 条：她按下紧急呼叫、跑完一整笔缴费、
    # 加了提醒、改了设置，`/elder2` 的记录页一行都不多，而 `/elder3` 全都看得到。
    #
    # `who` 一律交给 `_WHO_FROM_ACTOR` 按动作人定：这一层的端点老人和家属
    # 都进得来（同一个 `ctx.actor_id`），写死哪一个都有一半时候在说假话。
    # 下面这个「您」只是占位。
    "app.reminder.created": ("您", "reminder"),
    "app.reminder.completed": ("您", "reminder"),
    "app.reminder.cancelled": ("您", "reminder"),
    "app.reminder.moved": ("您", "reminder"),
    "app.routine.created": ("您", "reminder"),
    "app.routine.paused": ("您", "reminder"),
    "app.routine.resumed": ("您", "reminder"),
    "app.appointment.created": ("您", "task"),
    "app.appointment.cancelled": ("您", "task"),
    "app.medication.decided": ("您", "task"),
    "app.payment.prepared": ("您", "task"),
    "app.payment.teach_back": ("您", "task"),
    "app.payment.awaiting_family": ("您", "task"),
    "app.emergency.requested": ("您", "safety"),
    # 这一条的主语是优活本身（没能通知到），不随动作人变，所以**不**进
    # `_WHO_FROM_ACTOR`。
    "app.emergency.notify_failed": ("优活", "safety"),
    "app.health.recorded": ("您", "profile"),
    "app.contact.phone_set": ("您", "profile"),
    "app.settings.changed": ("您", "profile"),
    "app.memory.decided": ("您", "privacy"),
    "app.memory.forgotten": ("您", "privacy"),
    "app.privacy.erased": ("您", "privacy"),
    # ---- v4 那一层：用药计划 ------------------------------------------
    #
    # 一份用药计划决定她每天几点吃什么、吃多少。实测家人 `POST /v4/medications`
    # 之后，药已经排进她的清单、收件箱也收到了「要您确认」，而这一屏 +0 行。
    #
    # 提出和生效两种**双方都可能做**，所以 `who` 交给 `_WHO_FROM_ACTOR`；
    # 确认那一种只有老人本人能做（`v4_api.py` 里非 ELDER 直接 403），
    # 所以它的「您」是写死的。
    "MEDICATION_PLAN_PROPOSED": ("家人", "task"),
    "MEDICATION_PLAN_ACTIVATED": ("家人", "task"),
    #: 记一次服药。她自己按得动，家人也按得动，所以「谁」由动作人决定。
    "MEDICATION_DOSE_RECORDED": ("您", "task"),
    "MEDICATION_PLAN_DECIDED": ("您", "task"),
    # 她按下紧急求助（`POST /v4/safety/sos`）。
    #
    # `/api/v1` 那条路（`app.emergency.requested`）第 94 条已经补了，
    # 这是 v4 这条——**两个按钮走两条路**，补一条不等于补了另一条。
    #
    # 只有老人本人进得来（`ensure_target(..., family_allowed=False)`），
    # 所以「您」是写死的。
    #: 这一条的「谁」是**优活**：她只是走了路，是系统决定要提醒家人的。
    "GEOFENCE_ALERT_RAISED": ("优活", "safety"),
    "SOS_TRIGGERED": ("您", "safety"),
    # 固定安排的**第二条路**（`POST /v4/routines`）。`/api/v1` 那条写的是
    # `app.routine.created`，这条写 `ROUTINE_CREATED`——两个入口两个事件名。
    # 双方都做得了，所以 `who` 交给 `_WHO_FROM_ACTOR`。
    "ROUTINE_CREATED": ("家人", "reminder"),
    # 把固定安排做掉。`v4_api.complete_occurrence` 对非老人角色直接 403，
    # 所以这一条永远是她自己按的——称呼恒为「您」，不进 `_WHO_FROM_ACTOR`。
    "ROUTINE_OCCURRENCE_COMPLETED": ("您", "reminder"),
    # 身体数据的**第二条路**（`POST /v4/health/events`，家人替她记）。
    # `/api/v1` 那条写 `app.health.recorded`，已经在上面了。
    "HEALTH_EVENT_CREATED": ("家人", "profile"),
    # 有人把她的个人数据整份导出去了（`POST /v5/privacy/export`）。
    # 实体号就是她本人，所以准入本来就认（第 93 条那条规则），缺的只是词。
    # 双方都导得了，所以 `who` 交给 `_WHO_FROM_ACTOR`。
    "PRIVACY_EXPORT_CREATED": ("家人", "privacy"),
    # 删数据的**第二条路**（`POST /v5/privacy/erase`，execute=true）。
    # `/api/v1` 那条写 `app.privacy.erased`，已经在上面了。
    # 实测真删掉了 47 条位置记录。
    "PRIVACY_ERASE_EXECUTED": ("家人", "privacy"),
    # 亲友档案：谁在她的通讯录里，决定了她会接谁的电话、认得谁。
    # 双方都加得了，所以 `who` 交给 `_WHO_FROM_ACTOR`。
    "CONTACT_PROFILE_CREATED": ("家人", "profile"),
    "CONTACT_PROFILE_DECIDED": ("您", "profile"),
    # 破窗的第三步。开了、用了她都看得到（第 88 条补的），**关掉看不到**——
    # 那一屏上那扇门就永远开着。三步齐了才是一件完整的事。
    "BREAK_GLASS_CLOSED": ("家人", "privacy"),
    # 优活把她的心情存了下来（`emotion_events` 里那一行，她可以删）。
    # `app_api._WORDS` 那张表的注释里写着「它必须在她自己的记录上留名——
    # 看不到就等于不知道被记了」。那句话在 `/elder3` 上做到了，这一屏没有。
    # 记录的是优活，不是她，所以 `who` 写死成「优活」。
    "EMOTION_SIGNAL_RECORDED": ("优活", "privacy"),
    # 「让优活记住一件事」的**请求**。她的决定（MEMORY_APPROVED / _REJECTED /
    # _REVOKED）本来就在这张表里，而请求不在——读自己的记录会看到一句
    # 「您同意记住一件事」凭空冒出来，前面没有人问过。
    #: 远程协助：家人提，她决定。**两条都在**——只登记决定的话，
    #: 她的记录上就会出现一个没有问题的回答。
    "ASSISTANCE_REQUESTED": ("家人", "privacy"),
    "ASSISTANCE_DECIDED": ("您", "privacy"),
    "MEMORY_PROPOSED": ("家人", "privacy"),
    # 东西记忆：记的是她的东西放在哪儿。三种状态三个事件名：
    # 家人记的 PROPOSED（等她点头）、她自己记的 ACTIVATED、她的决定 DECIDED。
    "ITEM_MEMORY_PROPOSED": ("家人", "privacy"),
    "ITEM_MEMORY_ACTIVATED": ("您", "privacy"),
    # 只有老人本人能决定（`decide_item` 里非 ELDER 直接 403），所以写死「您」。
    "ITEM_MEMORY_DECIDED": ("您", "privacy"),
    # 有人**往里加**了一份她的就医单据。
    "MEDICAL_DOCUMENT_ANALYZED": ("家人", "trust"),
    # 她说身体不舒服。`care_voice.py` 那一批里「改变了或存下了什么」的
    # 只有三条，另外两条（语速、听力辅助）早就在这张表里，**只漏了这一条**。
    # 只有她本人说得出来，所以「您」写死。
    "CARE_SYMPTOM_ACKNOWLEDGED": ("您", "safety"),
}

_ELDER_ACTIVITY_TEXT: dict[str, str] = {
    "TASK_CREATED": "开始为您办理一件事。",
    "ELDER_CONFIRMED": "您复述并确认了这件事。",
    "TASK_EXECUTED": "事情已经办好，并核对过对方系统的状态。",
    "TASK_FAILED": "没有办成，已经安全停下，没有产生实际操作。",
    "TASK_CANCELLED": "您取消了这件事。",
    "FAMILY_APPROVAL_RECORDED": "家人确认了一次，还在等其他家人。",
    "FAMILY_APPROVED_AND_EXECUTED": "家人确认后已经办好。",
    "FAMILY_APPROVED_EXECUTION_FAILED": "家人确认了，但对方系统没有成功，已安全停下。",
    "FAMILY_REJECTED": "家人这次没有同意，已经取消。",
    "FAMILY_REMINDER_CREATED": "家人给您新增了一条待办。",
    "REMINDER_ACKNOWLEDGE": "您回应了一条待办提醒。",
    "REMINDER_COMPLETE": "您把一条待办标记成已完成。",
    "REMINDER_CANCELLED": "您取消了一条待办提醒。",
    "MODE_SWITCHED": "切换了优活办事和无忧伴陪伴模式。",
    #: 和上面那句是**一对**：只写暂停不写恢复，她那一屏上那件事就永远停在
    #: 「已经安全暂停」，看着像没人管了。
    "EMOTIONAL_TASK_RESUMED": "您说接着办，原来的事情继续了。",
    "EMOTIONAL_TASK_PAUSE": "先陪您说说话，原来的事情已经安全暂停。",
    "SAFETY_SIGNAL": "识别到需要注意的情况，进入了安全提示。",
    "SUSPICIOUS_INSTRUCTION_BLOCKED": "拦下了一句想跳过确认的话，没有执行。",
    "DOCUMENT_ANALYZED": "检查了一份上传的单据，只作参考不直接采用。",
    #: 不带主语——`who` 由动作人定的那些都得这样，见下面 `_WHO_FROM_ACTOR`
    #: 上面那段。原句是「更新了**您的**语速和字号习惯。」，配上 who=家人
    #: 就成了「家人 更新了您的语速……」——主语和宾语打架。
    "INTERACTION_PROFILE_UPDATED": "改了说话速度和字号这些习惯。",
    "CARE_PROFILE_SPEECH_RATE": "您让优活调整了说话速度。",
    "CARE_PROFILE_HEARING_SUPPORT": "您打开了听力辅助：句子更短、语速更慢。",
    "MEMORY_APPROVED": "您同意优活记住一条信息。",
    "MEMORY_REJECTED": "您拒绝了一条记忆请求。",
    "MEMORY_REVOKED": "您撤销了一条已记住的信息。",
    "BREAK_GLASS_OPENED": "家人因为紧急情况查看了您的资料。",
    "BREAK_GLASS_VIEWED": "家人用紧急权限读了您的资料。",
    "MEDICAL_DOCUMENT_READ": "家人看了您的一份就医单据。",
    "TASK_EXPLANATION_VIEWED": "调阅了这件事的说明。",
    "SAFETY_POLICY_UPDATED": _SAFETY_POLICY_SENTENCE,
    # `who` 由动作人定的这些，句子里**不带主语**——否则「家人」那一行会写着
    # 「您……」。写法照 `SAFETY_POLICY_UPDATED` 那一句。
    "app.reminder.created": "加了一条提醒。",
    "app.reminder.completed": "把一条提醒办好了。",
    "app.reminder.cancelled": "取消了一条提醒。",
    "app.reminder.moved": "改了一条提醒的时间。",
    "app.routine.created": "加了一件固定安排。",
    "app.routine.paused": "暂停了一件固定安排。",
    "app.routine.resumed": "又恢复了一件固定安排。",
    "app.appointment.created": "记下了一次就医安排。",
    "app.appointment.cancelled": "取消了一次就医安排。",
    "app.medication.decided": "确认了一份用药计划。",
    "app.payment.prepared": "发起了一笔缴费，还没有付。",
    "app.payment.teach_back": "复述核对了这笔缴费的信息。",
    "app.payment.awaiting_family": "这笔缴费在等家人确认。",
    "app.emergency.requested": "发出了一次紧急呼叫。",
    "app.emergency.notify_failed": "紧急呼叫没能通知到家人。",
    "app.health.recorded": "记了一次身体数据。",
    "app.contact.phone_set": "登记了一个紧急联系电话。",
    "app.settings.changed": "改了字号、语速这些设置。",
    "app.memory.decided": "定了一条信息要不要记住。",
    "app.memory.forgotten": "让优活忘掉了一条信息。",
    "app.privacy.erased": "删掉了一批个人数据。",
    #: 前两句不带主语（`who` 由动作人定）；第三句只有她能做，所以写「您」。
    "MEDICATION_PLAN_PROPOSED": "加了一份用药计划，还等着您点头。",
    "MEDICATION_PLAN_ACTIVATED": "一份用药计划开始生效了。",
    #: 兜底那句。三种结果各自的说法在 `_TEXT_BY_OUTCOME` 里。
    "MEDICATION_DOSE_RECORDED": "记了一次用药情况。",
    "MEDICATION_PLAN_DECIDED": "您确认了一份用药计划。",
    #: 接口返回的是「已经建了一条给家人的通知」，不是「家人已经看到了」。
    #: 所以写「已经通知家人」，不写「家人已经收到」。社区那一路返回的是
    #: `prepared`（准备好了，还没发），一个字都不提。
    "GEOFENCE_ALERT_RAISED": "发现您离开了常去的范围，已经提醒家人。",
    "SOS_TRIGGERED": "您按了紧急求助，已经通知家人。",
    #: 和 `app.routine.created` 逐字相同：同一件事，两条路，一个说法。
    "ROUTINE_CREATED": "加了一件固定安排。",
    #: 她把它做掉了。载荷是空的（`v4_api` 那边传 `{}`），所以说不出是**哪一件**——
    #: `/elder3` 上那句同样说不出。这是另一笔账，记在 KNOWN_ISSUES 里。
    "ROUTINE_OCCURRENCE_COMPLETED": "您完成了一件固定安排。",
    #: 和 `app.health.recorded` 逐字相同：同一件事，两条路，一个说法。
    "HEALTH_EVENT_CREATED": "记了一次身体数据。",
    #: 不说导出的是哪几类——那份清单里有心情记录、去过哪儿、就医单据，
    #: 逐类念出来既长又等于在她的记录页上再抄一份目录。
    "PRIVACY_EXPORT_CREATED": "把您的个人数据导出了一份。",
    #: 和 `app.privacy.erased` 逐字相同：同一件事，两条路，一个说法。
    "PRIVACY_ERASE_EXECUTED": "删掉了一批个人数据。",
    #: **不说「等您点头」**：家人加的那一份确实在等她，但她自己加的直接就
    #: 算她同意了（`consented_by` 当场就是她），而这两种情况写的是**同一个
    #: 事件名**。一个事件名一句固定的话，那句话就不能断言一个会变的状态。
    "CONTACT_PROFILE_CREATED": "加了一位亲友。",
    "CONTACT_PROFILE_DECIDED": "您确认了一位亲友。",
    "BREAK_GLASS_CLOSED": "紧急查看权限已经关掉了。",
    #: 不说存了什么（情绪标签、难受程度都在载荷里，不往她那一屏上抄）。
    #: 这一句要做到的只有一件事：让她知道**被记了**。
    "EMOTION_SIGNAL_RECORDED": "记下了您当时的心情。",
    #: 这两句敢说「等您点头」，是因为**验过**：两种事各自都只在待定时
    #: 才写这个事件名（记忆两边提出来都是 `proposed`；东西记忆她自己记的
    #: 走的是 `ACTIVATED`）。亲友档案那次不能说，就是因为它两种状态
    #: 共用一个事件名——见第 110 条。
    #: 主语由上面那张表的第一格给，这里不重复说一遍「家人」。
    "ASSISTANCE_REQUESTED": "想帮您弄一件事，问您同不同意。",
    "ASSISTANCE_DECIDED": "决定了一次远程协助。",
    "MEMORY_PROPOSED": "想让优活记住一件事，等您点头。",
    "ITEM_MEMORY_PROPOSED": "想记下一样东西放在哪儿，等您点头。",
    "ITEM_MEMORY_ACTIVATED": "记住了一样东西放在哪儿。",
    "ITEM_MEMORY_DECIDED": "您定了那样东西记不记。",
    "MEDICAL_DOCUMENT_ANALYZED": "整理了一份您的就医单据。",
    #: 不写是哪儿不舒服。载荷里有 `clinical_advice`，那是给家属那一侧看的；
    #: 她这一屏只需要「这件事被记下了」。也不提「要不要登记」——
    #: `offered_registration` 是**当时**提没提过，事后那一行说了也没用。
    "CARE_SYMPTOM_ACKNOWLEDGED": "您说了身体不舒服。",
}


#: 这几种事**双方都可能做**，`who` 必须看是谁做的。
#:
#: `_ELDER_ACTIVITY_LABELS` 把 `who` 写死在事件类型上——`TASK_CANCELLED` 永远
#: 是「您」，`FAMILY_*` 永远是「家人」。那对每种事只有一个可能的动作人的情形
#: 是对的；而安全设置**老人自己也能改**（实测她 `PUT` 也是 200），
#: 写死哪一个都有一半时候在说假话。
#:
#: `app.*` 那一整套同理：`/api/v1` 的端点老人和家属走的是同一个
#: `ctx.actor_id`，谁登录谁就是动作人。
#:
#: 例外是 `app.emergency.notify_failed`——那一条的主语是优活自己
#: （没能通知到家人），和谁按的按钮无关，所以它不在这里。
_WHO_FROM_ACTOR: frozenset[str] = frozenset({
    "SAFETY_POLICY_UPDATED",
    #: 她自己也调得动自己那件事的说明，所以主语按动作人来。
    "TASK_EXPLANATION_VIEWED",
    #: 和上面那条是一对：家人在 `/v6/profiles` 上改得动她的语速和字号。
    #: 此前它写死「您」，于是家人改完，她自己那一屏说是她改的。
    "INTERACTION_PROFILE_UPDATED",
    "app.reminder.created",
    "app.reminder.completed",
    "app.reminder.cancelled",
    "app.reminder.moved",
    "app.routine.created",
    "app.routine.paused",
    "app.routine.resumed",
    "app.appointment.created",
    "app.appointment.cancelled",
    "app.medication.decided",
    "app.payment.prepared",
    "app.payment.teach_back",
    "app.payment.awaiting_family",
    "app.emergency.requested",
    "app.health.recorded",
    "app.contact.phone_set",
    "app.settings.changed",
    "app.memory.decided",
    "app.memory.forgotten",
    "app.privacy.erased",
    #: 加一份药，老人自己和家属都做得了（`create_medication` 两边都放行）。
    "MEDICATION_PLAN_PROPOSED",
    "MEDICATION_PLAN_ACTIVATED",
    #: 记一次服药：`/api/v1/medications/{id}/taken|skipped` 两边都进得来，
    #: 写死哪一个都有一半时候在说假话。
    "MEDICATION_DOSE_RECORDED",
    #: 下面两个是 v4 那一侧的入口，双方都进得来，所以称呼也得看是谁做的。
    #: （它们各自对应 `app.routine.created` / `app.health.recorded`，
    #: 那两个在上面的点号那一批里。）
    "ROUTINE_CREATED",
    "HEALTH_EVENT_CREATED",
    #: 导出个人数据：老人自己和家属都做得了，称呼看动作人。
    "PRIVACY_EXPORT_CREATED",
    #: 这三种双方都做得了：提议记一件事、记一样东西、加一份就医单据。
    "MEMORY_PROPOSED",
    "ITEM_MEMORY_PROPOSED",
    "MEDICAL_DOCUMENT_ANALYZED",
    #: 删数据的第二条路，同 `app.privacy.erased`。
    "PRIVACY_ERASE_EXECUTED",
    #: 亲友档案：老人自己和家属都加得了。
    "CONTACT_PROFILE_CREATED",
})


#: 这几种事是**别人对她做的**，实体又不是任务/提醒，但载荷里点了她的名。
#:
#: `elder_activity_entries` 的归属判断只认 `task*` / `rem*`；别的 id 解析成
#: `None`，然后「动作不是她做的」就被丢掉。破窗访问正好两条都占：
#: id 是 `breakglass-…`，动作是家属做的——于是她那一屏永远看不到。
#:
#: 口子开得很窄：**必须**是这张表里的事件类型，**并且**载荷里的 `elder_id`
#: 就是她。不是把那道归属判断放开。
_ABOUT_HER_EVEN_IF_ANOTHER_ACTED: frozenset[str] = frozenset({
    "BREAK_GLASS_OPENED",
    "BREAK_GLASS_VIEWED",
    "MEDICAL_DOCUMENT_READ",
    #: 固定安排：实体号是 `routine-…`，解析不出来。而这是一件**每天到点就会
    #: 打断她**的事，别人给她建的、暂停的，她自己那一屏必须看得到。
    "app.routine.created",
    "app.routine.paused",
    "app.routine.resumed",
    #: 字号、语速这些是一家共用一份的（按 `family_id` 存的交互档案）。
    #: 家人一改，她屏幕上的字就跟着变——所以她那一屏必须留下这一行。
    "app.settings.changed",
    #: 用药计划：实体号是 `medplan-…`，解析不出来。家属补一份药进来，
    #: 她自己那一屏必须看得到——这份计划管的是她每天吃什么。
    "MEDICATION_PLAN_PROPOSED",
    "MEDICATION_PLAN_ACTIVATED",
    #: 亲友档案：实体号是 `person-…`，同样解析不出来。谁在她的通讯录里，
    #: 决定了她会接谁的电话、认得谁。
    "CONTACT_PROFILE_CREATED",
    #: 破窗关闭：和上面 OPENED / VIEWED 一样是 `breakglass-…`，
    #: 而且同样是家属做的。三步缺一步，她那一屏上的门就关不上。
    "BREAK_GLASS_CLOSED",
    #: 「让优活记住一件事/一样东西」的请求，和往里加一份就医单据。
    #: 实体号分别是 `memory-…` / `item-…` / `medicaldoc-…`，都解析不出来。
    "MEMORY_PROPOSED",
    "ITEM_MEMORY_PROPOSED",
    "MEDICAL_DOCUMENT_ANALYZED",
    #: v4 那一侧的两个入口。它们的实体号（`routine-…` / `health-…`）归属
    #: 判断都解析不出来，家属替她做的那一条会被「动作不是她做的」丢掉，
    #: 所以要靠载荷里的 `elder_id` 放行。
    "ROUTINE_CREATED",
    "HEALTH_EVENT_CREATED",
    #: `/api/v1` 那一侧的同一批事。
    #:
    #: 这里原先写着一句**假话**：「各自的另一条路（`app.routine.created` /
    #: `app.health.recorded`）实体号形状相同，只是它们的载荷早就带着
    #: `elder_id` 了。」——对 `app.routine.created` 成立，对
    #: `app.health.recorded` **不成立**：它写的是
    #: `payload={"label": label, "kind": kind}`，而且它压根不在这张表里。
    #: 于是紧跟着那句「一件事两条路，两条都得登记」自己被违反了：
    #: 登记的是 v4 那一条，`/api/v1` 这一条没登记。
    #:
    #: 实测（家人替她做，她自己读 `/v2/elder/activity`）：
    #:
    #:     家人替她记一次血压   -> 她那一屏 **一行都没有**
    #:     家人替她约一次就医   -> **一行都没有**
    #:     家人取消那次就医     -> **一行都没有**
    #:     同样三件事她自己做   -> 三行全在（「您 记了一次身体数据。」…）
    #:
    #: 而 `/family2` 的照护页走的正是这三条路（`care.js` 的血压、就医、取消）。
    "app.health.recorded",
    "app.appointment.created",
    "app.appointment.cancelled",
    #: 家人替她请求远程协助。实体号是 `assist-…`，解析不出归属，
    #: 动作人又是家属——不放行的话这一条永远到不了她那一屏。
    "ASSISTANCE_REQUESTED",
    #: 家人也替她记得了服药，实体号 `medplan-…` 解析不出归属。
    "MEDICATION_DOSE_RECORDED",
})


def elder_activity_event_types() -> tuple[str, ...]:
    """她那一屏**可能**显示的事件类型。

    给 SQL 过滤用。让调用方直接读 `_ELDER_ACTIVITY_LABELS` 也行，但那样
    「投影认哪些事件」就有了两个出处，改一处忘一处的时候没人会红。
    """
    return tuple(_ELDER_ACTIVITY_LABELS)


#: 同一个事件、不同结果，说法不能是同一句。
#:
#: `_ELDER_ACTIVITY_TEXT` 是**一个事件一句话**的静态表。对结果写在 payload 里的
#: 事件，它天生说不出区别——而「她同意了」和「她回绝了」是相反的两件事。
#:
#: 实测（她同意一份药、回绝另一份）：
#:
#:     /elder3   同意 -> 确认了一份用药计划     回绝 -> 没有同意那份用药计划
#:     /elder2   同意 -> 确认了一份用药计划。   回绝 -> **确认了一份用药计划。**
#:
#: `/elder3` 那一半在第 123.2 条修过（`app_api._DECISION_WORDS`），
#: **而这一半没修**——同一个缺陷在另一块屏幕上原样活着。
#: 这个仓库最常见的失败就是「一件事两条路、只修一条」，我在写那条记录的时候
#: 自己又踩了一次。
#:
#: 形状统一成 `(payload 里的键, {取值的字符串: 说法})`：`approved` 是布尔、
#: `status` 是字符串，用 `str()` 拉平成同一种查法。取不到的取值退回原来那句
#: ——宁可说得笼统，不能说反。
_TEXT_BY_OUTCOME: dict[str, tuple[str, dict[str, str]]] = {
    "app.medication.decided": ("approved", {
        "True": "确认了一份用药计划。",
        "False": "没有同意那份用药计划。",
    }),
    "MEDICATION_PLAN_DECIDED": ("approved", {
        "True": "您确认了一份用药计划。",
        "False": "您没有同意那份用药计划。",
    }),
    #: 吃了 / 没吃 / 漏服。第 135 条在 `/elder3` 那一侧修过同一件事，
    #: 当时这一侧因为「话术表不能按 payload 分支」而没修——机制现在有了。
    "MEDICATION_DOSE_RECORDED": ("status", {
        "taken": "记了一次服药。",
        "skipped": "记了一次没吃。",
        "missed": "记了一次漏服。",
    }),
    #: 记忆的同意/回绝。上面那段注释写的正是这个坑，而它又发生了一次：
    #: 这一批表有**三**处（这里、`app_api._DECISION_WORDS`、
    #: `family.js` 的 `AUDIT_DECISION`），只改一处就等于没改。
    #:
    #: 实测（她同意一条、回绝另一条）：
    #:     审计   {"approved": true,  "key": "不想被打扰的日子"}
    #:            {"approved": false, "key": "爱喝的茶"}
    #:     /elder3 两条都是「决定了一条要不要记」
    #:     /elder2 两条都是「定了一条信息要不要记住。」
    #:
    #: 而端点自己的回话是分得清的（「好，我记住…了」/「好，…我不记。」）。
    "app.memory.decided": ("approved", {
        "True": "同意记下这一条。",
        "False": "没有同意记下这一条。",
    }),
}


def elder_activity_entries(
    events: list[AuditEvent],
    *,
    entity_belongs_to_elder,
    elder_id: str,
) -> list[ElderActivityEntry]:
    """Project audit events into an elder-readable log, newest first.

    `entity_belongs_to_elder(entity_id)` resolves whether a task/reminder id is
    the elder's own; it returns None when the id is not an ownable entity, in
    which case the event is kept only if the elder is the actor.
    """
    entries: list[ElderActivityEntry] = []
    for event in events:
        label = _ELDER_ACTIVITY_LABELS.get(event.event_type)
        if label is None:
            continue
        owned = entity_belongs_to_elder(event.entity_id)
        if owned is False:
            continue
        if owned is None and event.actor_id != elder_id:
            named_her = (
                event.event_type in _ABOUT_HER_EVEN_IF_ANOTHER_ACTED
                and str((event.payload or {}).get("elder_id") or "") == elder_id
            )
            if not named_her:
                continue
        who, kind = label
        if event.event_type in _WHO_FROM_ACTOR:
            who = "您" if event.actor_id == elder_id else "家人"
        #: 结果写在 payload 里的那几个事件，按结果取词。见 `_TEXT_BY_OUTCOME`。
        what = _ELDER_ACTIVITY_TEXT[event.event_type]
        outcome = _TEXT_BY_OUTCOME.get(event.event_type)
        if outcome is not None:
            field, table = outcome
            what = table.get(str((event.payload or {}).get(field)), what)
        entries.append(
            ElderActivityEntry(
                id=event.id,
                happened_at=event.created_at,
                who=who,
                what=what,
                kind=kind,
                about_id=event.entity_id,
            )
        )
    entries.sort(key=lambda item: item.id, reverse=True)
    # Collapse runs of the same line: a retried turn should read as one event,
    # not as the same sentence repeated down the page.
    #
    # `about_id` 也要参与比较。少了它，**两笔不同的事务**只要产生同一句话就会被
    # 合并成一行——`_ELDER_ACTIVITY_TEXT` 是每个事件类型一句固定的话，所以连着
    # 办两次缴费，第二笔会安静地消失。原先这个字段还没有，所以看不出来；
    # 现在它在了，这一行就该修。
    #
    # `None` 参与比较是对的：两条都取不到主体时，它们确实无法区分，
    # 折叠成一条比显示两条一样的话更好。
    deduped: list[ElderActivityEntry] = []
    for entry in entries:
        if (deduped and deduped[-1].what == entry.what
                and deduped[-1].who == entry.who
                and deduped[-1].about_id == entry.about_id):
            continue
        deduped.append(entry)
    return deduped


def task_view(task: TaskRecord) -> TaskView:
    """Create an allow-listed client view without companion/deferred content."""
    slots = task.slots
    details: dict[str, Any] = {}
    if task.task_type == TaskType.BILL_PAYMENT:
        details = {
            "bill_type": slots.get("bill_type"),
            "period": slots.get("period"),
            "amount_yuan": f"{int(slots.get('amount_cents', 0)) / 100:.2f}" if slots.get("amount_cents") is not None else None,
            "due_date": slots.get("due_date"),
        }
        summary = (
            f"{details.get('period') or ''}{details.get('bill_type') or '生活账单'} "
            f"{details.get('amount_yuan') or '--'}元"
        ).strip()
    elif task.task_type == TaskType.HOSPITAL_REGISTRATION:
        details = {
            "hospital": slots.get("hospital"),
            "department": slots.get("department"),
            "doctor": slots.get("doctor"),
            "appointment_date": slots.get("appointment_date"),
            "appointment_time": slots.get("appointment_time"),
        }
        summary = " ".join(str(v) for v in details.values() if v) or "医院挂号"
    elif task.task_type == TaskType.REMINDER:
        details = {
            "title": slots.get("title"),
            "due_date": slots.get("due_date"),
            "due_time": slots.get("due_time"),
        }
        summary = f"{details.get('due_date') or ''} {details.get('due_time') or ''} {details.get('title') or '待办提醒'}".strip()
    else:
        details = {
            "goal": redact_text(str(slots.get("form_goal", "逐项语音辅助填写"))),
            "requires_identity_guidance": bool(slots.get("face_verification")),
            "contains_sensitive_form": bool(slots.get("sensitive_form")),
        }
        summary = "逐项语音辅助填写"
    details = {key: redact_payload(value) for key, value in details.items() if value is not None}
    public_result = redact_payload(task.result)
    # Never expose arbitrary free-form/internal result fields to clients.
    if task.task_type == TaskType.BILL_PAYMENT:
        allowed_result = {k: public_result[k] for k in ("bill_id",) if isinstance(public_result, dict) and k in public_result}
    elif task.task_type == TaskType.HOSPITAL_REGISTRATION:
        allowed_result = {
            k: public_result[k]
            for k in ("appointment_id", "calendar_reminder_id", "calendar_status")
            if isinstance(public_result, dict) and k in public_result
        }
    elif task.task_type == TaskType.REMINDER:
        allowed_result = {k: public_result[k] for k in ("reminder_id", "due_at") if isinstance(public_result, dict) and k in public_result}
    else:
        allowed_result = {k: public_result[k] for k in ("guidance", "identity_bypass") if isinstance(public_result, dict) and k in public_result}
    return TaskView(
        id=task.id,
        elder_id=task.elder_id,
        task_type=task.task_type,
        status=task.status,
        risk_level=task.risk_level,
        summary=summary,
        approval_digest=task.approval_digest if task.status.value == "awaiting_family_approval" else None,
        details=details,
        result=allowed_result,
        created_at=task.created_at,
        updated_at=task.updated_at,
    )
