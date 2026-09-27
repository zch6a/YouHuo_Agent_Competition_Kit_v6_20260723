// Resolved from identity.js; see the note there about per-visitor sandboxes.
let ELDER_ID = 'elder-demo';
let IDENTITY = null;

// Design §4.5: the family view shows "which step is this task on" in plain words,
// not raw backend enum values.
//
//: 措辞**逐字**取 `common.js` 的 `STATUS_WORD_OTHER`（他称那一份）：这一页是家人
//: 在读别人的事。七个键现在一字不差，只有 `executing` 是这一轮改的。
//:
//: 它原先写「正在执行」，而别处六处都说「正在办理」。两句话都没提到人，所以那不是
//: 「自称 / 他称」的称呼差异，是漂移——同一笔钱在办的时候，老人端说「正在办理」、
//: 家人端说「正在执行」，读的人没法判断这是同一件事，也没法判断哪一句更重。
//: 「执行」还是工程行话：这个产品对老人说的是「办」。
//:
//: 不合并成直接调 `YouHuo.statusWord(s, 'other')`：这张表的值是 `[话, 类名]` 两段，
//: 第二段是 `.status-chip` 的样式（todo / confirm / relay / done / cancelled），
//: `common.js` 那一对只有话。改成调用要么丢掉颜色，要么在 common.js 里再加一张
//: 类名表——而那个文件不在这一轮的改动范围里。所以仍是一份副本，靠
//: `test_the_family_surface_speaks_one_language.py` 逐字钉在他称那一份上。
const TASK_STEP = {
  collecting: ['正在收集信息', 'todo'],
  awaiting_elder_confirmation: ['等老人复述确认', 'confirm'],
  awaiting_family_approval: ['等您接力确认', 'relay'],
  executing: ['正在办理', 'todo'],
  completed: ['已完成并核验', 'done'],
  cancelled: ['已取消', 'cancelled'],
  failed: ['未成功，已安全停下', 'relay'],
};

const REMINDER_STEP = {
  scheduled: ['待处理', 'todo'],
  notified: ['待确认', 'confirm'],
  acknowledged: ['老人已知道', 'todo'],
  completed: ['已完成', 'done'],
  escalated: ['超时未完成', 'relay'],
  cancelled: ['已取消', 'cancelled'],
};

const RISK_WORD = {1: '信息查询', 2: '低风险', 3: '敏感操作', 4: '高风险'};

//: 键必须是后端**真的**会发的那些 `event_type`。全仓 grep
//: `event_type="…"`（backend/youhuo 下的每个 .py）数出九个，这张表原先只有八个——
//: 少的那一个是 `emergency_call`（老人按下紧急呼叫时由 app_api.py:1929 发出）。
//:
//: 实测：老人端按一次紧急呼叫，家人收件箱里那一条的标题走兜底，变成
//: 「来自优活的消息」，正文才是「王爷爷按下了紧急呼叫，请尽快联系。」。
//: 一条要人立刻放下手机去看的消息，标题和「优活给您推了点什么」长得一模一样——
//: 而这一格是折叠的，未读时只有标题露在外面。这是这张表最不能漏的那一个。
//:
//: 说法和 `trust.js::NOTIFY_WORD` 对齐（那一页把同一条事件叫「紧急联系」）：
//: 同一件事在两页上两个名字，家属要自己做换算才知道说的是一回事。
//:
//: 改这一段注释时有个坑：**行注释里不许出现 `/` 紧跟 `*` 的字样**。套件里有两处
//: 注释剥除器（`test_design_three…::_src`、`test_family_one_two…::_strip_js_comments`）
//: 先用正则吃掉块注释、再吃行注释，于是行注释里那两个字符会让它从这里一路吃到
//: 下一个块注释的收尾，把整张表连带吞掉。第一版这里写了个 `youhuo` 的 glob，
//: 实测把 `test_the_family_notice_titles_do_not_fork_from_design_one` 打红过一次，
//: 而报错说的是「找不到 NOTICE_TITLE」——看起来像判据坏了。
const NOTICE_TITLE = {
  approval_required: '需要您接力确认',
  additional_approval_required: '还需要另一位家属确认',
  task_rejected: '已按您的意见取消',
  task_completed: '任务已完成',
  family_reminder_created: '待办已同步到老人端',
  reminder_due: '待办到期提醒',
  reminder_advance_notice: '已提前提醒老人',
  reminder_escalated: '超时未完成，请接力',
  emergency_call: '紧急联系',
  elder_feels_unwell: '老人说身体不舒服，请联系确认',
  // 至此这张表覆盖的是**驱动出来**的类型，不是 grep 出来的。 上面那段说明里「全仓 grep 数出九个」的做法漏了三种写法： 位置实参（sos / geofence_exit / urgent_emotion 都是这么发的）、 事件名不是字面量（emergency / suspected_scam 来自 SafetySignal.category）， 以及大写的键。判据 `_backend_event_types()` 已经改成按 AST 数这三种。
  emergency: '可能摔倒了，请尽快联系',
  suspected_scam: '可能碰上诈骗，请尽快联系',
  sos: '老人按了紧急求助',
  urgent_emotion: '说了一句要马上确认的话',
  geofence_exit: '离开了常去的范围',
  inactivity_check: '很久没有动静了',
  medication_inventory: '药快不够了',
  BREAK_GLASS_OPENED: '已开启紧急查看',
};

// Redacted companion digest: Chinese labels for the report's summary keys.
/* 「趋势」那一格搬去了 /care，这里原先的三张表和 `weeklyValue()` 一起走了。
 *
 * 不是简单搬走——那三张表里有两张是**坏的**，而 care.js 里已经有修好的版本：
 *
 *   后端 EmotionLabel 共 7 个值：positive / calm / lonely / low_mood /
 *                                anxious / angry / urgent
 *   这里原来的表：calm / lonely / anxious / sad / happy / angry / distressed
 *                 ↑ 缺 positive / low_mood / urgent
 *                 ↑ 多出后端根本没有的 sad / happy / distressed
 *
 * 于是这一格会把 `positive`、`low_mood`、`urgent` 印成英文码——而 `urgent`
 * （「急着要人帮忙」）恰恰是最要紧的那一个。care.js 的 `EMOTION_WORD` 注释里
 * 记着这次修复，但当时只修了那一个文件，这里留着坏的那份，两页读**同一个端点**
 * 却各有一套词汇。搬迁时用了 care.js 那份，坏的这份不带走。
 */

const tasksEl = document.querySelector('#tasks');
const otherTasksEl = document.querySelector('#otherTasks');
const auditEl = document.querySelector('#audit');
const chainEl = document.querySelector('#chain');
const calendarEl = document.querySelector('#calendar');
const noticesEl = document.querySelector('#notices');
// `#weekly` 的引用一起去掉：那个元素现在住在 care.html。留着它会得到一个
// 永远是 null 的常量，而下一个人读到这一行会以为这一页还有那一格。
const dailyEl = document.querySelector('#dailyReport');
const updatedEl = document.querySelector('#famUpdated');
const verdictEl = document.querySelector('#famVerdict');
const headlineEl = document.querySelector('#famHeadline');

/* 发第一个请求之前，先把设计二那份**样张**收掉。
 *
 * `family-v6.html` 是一张画好的样张：`#audit` 里躺着三条编出来的「记录」
 * （「复诊挂号已确认 · 今天 15:42 · 张敏确认 · 社区医院返回成功」），
 * `#chain` 躺着一句结论，`#tasks` 一张待确认卡，`#calendar` 一排日程，
 * `#notices` 一句「今天没有新的超时提醒」。成功那一路会把它们全换掉，
 * 所以平时看不出来。
 *
 * 出问题那一路不会：六处 `replaceChildren()` 全在 `load()` 的 try 里、
 * await 之后；登录失败时 `load()` 根本不执行。于是断网 / 后端 500 /
 * 令牌过期这三种情形下，子女读到的是**一屏编出来的照护事实**，
 * 而屏幕上唯一说事情不对的只有一条 notice 横幅。
 *
 * 设计一（`family.html`）没有这个毛病：它那几个位置本来就是空的，
 * 或者写着「正在加载……」。**同一份 family.js，两张皮，只有一张会撒谎。**
 *
 * 为什么放在这里而不是补进那两个 catch：第 1084 行记着上一次的教训——
 * 「和 load() 的 catch 一模一样的错，只是我上一轮只改了 load() 那一处」。
 * 补 catch 要求每新增一条失败路径都有人记得再补一次；放在第一个请求之前
 * 只有一处，忘不掉。
 *
 * HTML 一个字没动：那份样张是给设计看的，也被静态判据读着。
 */
const MOCKUP_SLOTS = [
  [tasksEl, '正在读取需要您确认的事……'],
  [otherTasksEl, '正在读取其他事项……'],
  [auditEl, '正在读取记录……'],
  [chainEl, '正在核对这些记录有没有被改过……'],
  [calendarEl, '正在读取这一周的安排……'],
  [noticesEl, '正在读取通知……'],
];
MOCKUP_SLOTS.forEach(([el, word]) => {
  //: `textContent` 一步到位：它同时清掉子元素和文本，不留半份样张。
  if (el) el.textContent = word;
});

//: 只有这一个状态需要子女**动手**，页头那一句结论和「需要您确认」那张卡都以它为准。
//  写成常量而不是两处各抄一遍字符串：两处只要有一处写错，页头就会和它正下方那张卡
//  说出互相矛盾的两句话。
const NEEDS_FAMILY = 'awaiting_family_approval';

// 页头那一句结论的措辞。键是 /v7/daily-report 的 report.overall。
//
// 为什么不把 report.headline 直接放进 <h1>：那是完整的一段判断，最长的一条
// 「还在熟悉他的生活规律（已记录 0 天）。在攒够之前，不会拿别人的标准来评价他。」
// 38 个字，按 .fam-head h1 在 390px 屏上的 26px 排是四行——页头一个人吃掉四分之一
// 首屏，而「需要您确认」必须留在第一屏。而那一态恰恰是新装用户和评委最先看到的。
// 所以 <h1> 用一句短的，report.headline 原样放在它下面一行（.lead，窄屏 16px），
// 一个字都不丢。
//
// 与 common.js 的 verdictOf 分工：那边给的是「和平常一样」这类形容词短语，用在徽标
// 和分项标题上，单独放进 <h1> 不成句。两张表的键必须一一对应，不许各自增删——否则
// 同一天的结论会在页头和分项里说成两回事。
const VERDICT_SENTENCE = {
  typical: '他今天和平常差不多',
  notice: '他今天有一点和平常不同',
  marked: '他今天和平常不太一样',
  unknown: '今天该有的记录还没出现',
  pending: '今天还没过完，还不好说',
};

// 结论要拼两条互相独立的请求：/v7/daily-report 说「他今天怎么样」，/v2/tasks 说
// 「有几件事在等您点头」。两条各自到达，谁先到都可能，所以两个渲染函数都不直接写
// <h1>，而是各自把知道的那一半存进这里，再一起重画。
//
// 为什么不用日报里现成的 errands.awaiting_family（它数的是同一张表）：那个数和
// 「需要您确认」下面**真正画出来的按钮**不是同一次查询。相差一件的时候，页头会写
// 「今天有一件事要您点头」而它正下方那张卡写「今天不用您操心」——一句自相矛盾的
// 结论比没有结论更糟。两处因此都用同一份 tasks 结果。
const CONCLUSION = {report: null, needYou: null, reportFailed: false};

// 审计事件的类型码是给工程和评委看的：`FAMILY_APPROVED_AND_EXECUTED`、
// `system-vc8693dfcd970`。这一页原先把它们原样印出来给家属看。家属要的是
// "谁，做了什么，什么时候"，不是一条能 grep 的日志。
//
// 有近百种事件码，逐个翻译既写不全也会过期，所以是"认识的说人话，不认识的按
// 前缀归类"。**不保留原始码做兜底**——兜底成原始码，等于这层翻译在遇到新事件
// 时自动失效，而那正是它该起作用的时候。逐条原文在 /trust，那里才是它的地方。
//: 措辞不是在这里发明的，是**取来的**：逐字照 `common.js` 的 `AUDIT_WORD`，
//: 而那一份又逐字照后端 `app_api.py::_WORDS`——那张表已经通过 `GET /app/records`
//: 上屏，而且它自己的注释写着是查库定的案，是唯一一份被真实数据校对过的。
//:
//: 这一轮改了 17 条 + 补了 4 条。改之前 24 个键里 17 个和准则说的是两句话，
//: 举三条最要紧的（同一笔缴费，同一条链）：
//:
//:     FAMILY_APPROVAL_RECORDED  这里「点了同意」   准则「家人已点头」
//:     FAMILY_REJECTED           这里「拒绝了」     准则「家人没有同意」
//:     TEACH_BACK_REJECTED       这里「复述没对上」 准则「复述没对上，停在原地」
//:
//: 「拒绝了」那一条最糟：这一行前面拼的是 `actorName()`（「他」/「家人」/「优活」），
//: 于是屏幕上是「家人拒绝了」——而实际发生的是家属没有点头、这一笔被安全取消，
//: 两件事的分量差得远。`TEACH_BACK_REJECTED` 少的那半句（「停在原地」）也是同一类：
//: 家属读到「他复述没对上」，看不出这笔钱到底走没走。
//:
//: `ELDER_CONFIRMED` 是唯一一条**该**和准则不一样的：`AUDIT_WORD` 说「您确认了」，
//: 而这一页是家人在读别人的事，所以取他称那一份 `AUDIT_WORD_OTHER` 的「老人确认了」。
//: 原先写的是「确认了」，两边都不是——它把「谁确认的」这个唯一要紧的信息删了。
//:
//: 最后四条（`NOTIFICATION_CREATED` 与 `app.payment.` 那三个）原先**根本没有键**。
//: 实测（老人发起一笔电费、念错一次、念对、两位家属点头到办好，再读
//: `/v2/audit?entity_id=` 那一笔）：链上 11 个码，这四个走兜底，屏幕上是
//: 「优活留下一条记录」——一句什么都没说的话，而它占的正是「优活发出了通知」
//: 和「这一笔申请是怎么起来的」两行。
//:
//: 剩下四个键（`REMINDER_CREATED` / `REMINDER_COMPLETE` / `REMINDER_ACKNOWLEDGE` /
//: `PAYMENT_REQUEST_CREATED`）`AUDIT_WORD` 里没有，措辞没有准则可对，原样保留。
const AUDIT_VISIBLE = 8;
//: 后端标了「只是读了一下 / 内部路由」的事件——**不占这 8 行**。
//:
//: 实测（老人开一次会话问四句家常，家人端读前 8 行）：
//:
//:     FAMILY_APPROVED_AND_EXECUTED   有人话
//:     NOTIFICATION_CREATED           有人话
//:     DEMO_LOGIN × 2                 有人话
//:     CARE_QUERY_SCHEDULE            **内部事件**
//:     CARE_QUERY_MEDICATION_LIST     **内部事件**
//:     CARE_QUERY_MEDICATION_STOCK    **内部事件**
//:     CARE_QUERY_HEALTH_RECENT       **内部事件**
//:
//: **8 行里 4 行**。她问了四句家常，家人这一格于是有一半在说
//: 「留下一条记录」——而后端在 `_MACHINERY` 里逐条写明了这些不该给人看。
//:
//: 做法照老人端那一侧：`/api/v1/records` 对同一批事**跳过、只报一个数**
//: （「另有 N 条系统记录」）。这里逐字用同一句，不另起一套说法。
//:
//: 这张表是**生成**的，逐条对应 `app_api._MACHINERY`，由
//: `test_the_family_surface_speaks_one_language.py` 钉住两边一模一样——
//: 镜像表会腐烂，判据不让它腐烂。
//: **减去这一格自己写过句子的那些。**
//:
//: `SESSION_CREATED`（「开始一次对话」）和 `TASK_EXPLANATION_VIEWED` 同时出现在
//: 后端的 `_MACHINERY` 和这一格的 `AUDIT_LABEL` 里——两处旧决定打架：
//: 后端说「内部事件，不该占槽位」，而这一格专门为它们写过一句人话，
//: 今天屏幕上也确实显示着。
//:
//: 这一轮**不替产品拍板**：谁该赢是产品决定。所以规则定成
//: 「滤掉内部事件，**但这一格明确写过句子的除外**」——
//: 当前看得见的行为一行没变，而 27 条噪音走掉了。
//: 判据钉的就是这个等式：AUDIT_INTERNAL == _MACHINERY − AUDIT_LABEL 的键。
const AUDIT_INTERNAL = new Set([
  'AGENT_TURN',
  'CARE_QUERY_CONTACT',
  'CARE_QUERY_HEALTH_RECENT',
  'CARE_QUERY_HELP',
  'CARE_QUERY_MEDICATION_LIST',
  'CARE_QUERY_MEDICATION_STOCK',
  'CARE_QUERY_MEDICATION_TODAY',
  'CARE_QUERY_ORIENTATION',
  'CARE_QUERY_SCHEDULE',
  'CARE_REPEAT',
  'COGNITIVE_LOAD_PLAN_CREATED',
  'COMPANION_THEME_OBSERVED',
  'COMPANION_TOPIC_RESUMED',
  'MEDICATION_INTERACTION_DEMO_CHECK',
  'MODE_SWITCHED',
  'OFFLINE_SYNC_OPERATION',
  'PRIVACY_ERASE_PREVIEWED',
  'PURPOSE_BOUND_POLICY_DECISION',
  'SAFE_ACTION_PREVIEWED',
  'SAGA_ADVANCED',
  'SAGA_CREATED',
  'SCHEDULER_TICK',
  'SEMANTIC_FRAME_PARSED',
  'SEMANTIC_ROUTED',
  'TOOL_DRY_RUN',
  'USER_STUDY_OBSERVATION_ADDED',
  'USER_STUDY_SESSION_CREATED',
  'environment.sample',
]);
const AUDIT_LABEL = {
  SESSION_CREATED: '开始一次对话',
  DEMO_LOGIN: '登录了优活',
  DEMO_SEEDED: '铺好了这个家庭的起始数据',
  TASK_CREATED: '开始办一件事',
  TASK_EXECUTED: '这件事办妥了',
  TASK_CANCELLED: '这件事停下了',
  TASK_EXPLANATION_VIEWED: '有人调阅了这件事的说明',
  TASK_PROOF_GENERATED: '生成了一份完成证明',
  TASK_SLOT_CORRECTED: '更正了其中一项信息',
  ELDER_CONFIRMED: '老人确认了',
  FAMILY_APPROVAL_RECORDED: '家人已点头',
  FAMILY_APPROVED_AND_EXECUTED: '家人同意后已办好',
  FAMILY_APPROVED_EXECUTION_FAILED: '家人同意了，但这件事没办成',
  FAMILY_REJECTED: '家人没有同意',
  FAMILY_REMINDER_CREATED: '家人替老人加了一条提醒',
  REMINDER_CREATED: '添了一件待办',
  REMINDER_COMPLETE: '办好了一件事',
  REMINDER_ACKNOWLEDGE: '老人说知道了',
  REMINDER_CANCELLED: '取消了一条提醒',
  PAYMENT_REQUEST_CREATED: '生成了缴费单',
  SOS_TRIGGERED: '按了紧急求助',
  MEDICATION_DOSE_RECORDED: '记了一次服药',
  TEACH_BACK_VERIFIED: '复述核对通过',
  TEACH_BACK_REJECTED: '复述没对上，停在原地',
  NOTIFICATION_CREATED: '发出一条通知',
  'app.payment.prepared': '发起申请',
  'app.payment.teach_back': '复述确认',
  'app.payment.awaiting_family': '等家人确认',
  //: 下面 18 条原先一条都没有，于是全落到 `auditLabel` 的兜底
  //: 「留下一条记录」——就是这张表上面那段注释说的那句「什么都没说的话」。
  //:
  //: 最难看的是紧急呼叫：老人按了求助，家人在「可信记录」上读到的是
  //: 「张阿姨　·　留下一条记录」。
  //:
  //: 说法逐字取自后端 `app_api._WORDS`，理由和上面那三条一样（见 977 行）：
  //: 同一件事在 `/elder3`、`/family3` 和这里必须是同一个说法，
  //: 手写第二套措辞就是又一张会各自腐烂的表。
  'app.reminder.created': '加了一条提醒',
  'app.reminder.completed': '办好了一件事',
  'app.reminder.cancelled': '取消了一条提醒',
  'app.reminder.moved': '改了提醒的时间',
  'app.routine.created': '加了一件固定安排',
  'app.routine.paused': '暂停了一件固定安排',
  'app.routine.resumed': '恢复了一件固定安排',
  'app.appointment.created': '记下一次就医安排',
  'app.appointment.cancelled': '取消了一次就医安排',
  'app.medication.decided': '确认了一份用药计划',
  'app.emergency.requested': '紧急呼叫',
  'app.emergency.notify_failed': '紧急呼叫没能通知到家人',
  'app.health.recorded': '记了一次身体数据',
  'app.contact.phone_set': '登记了紧急联系电话',
  'app.settings.changed': '改了设置',
  'app.memory.decided': '决定了一条要不要记',
  'app.memory.forgotten': '让优活忘掉一条',
  'app.privacy.erased': '删掉了一批个人数据',
  //: ---- 下面这一批是这一轮补的 ------------------------------------------
  //:
  //: 补之前，后端认定「要说给人听」的 84 类事件里，这一格只叫得出 42 类。
  //: 另外 42 类分两种死法（都是照 `auditLabel()` 自己算出来的）：
  //:
  //:   19 类落到兜底「留下一条记录」——包括「挡下了一句可疑的话」、
  //:      「说了身体不舒服」、「记了一次身体数据」；
  //:   23 类被 `AUDIT_CATEGORY` 的前缀糊成一个类别词，而那个词说的**不是
  //:      同一件事**。最要紧的几条：
  //:
  //:        SAFETY_POLICY_UPDATED  屏上「触发了安全提醒」/ 实际「改了安全设置」
  //:        MEMORY_REJECTED        屏上「动了记忆」    / 实际「没有同意记那一件」
  //:        BREAK_GLASS_VIEWED     屏上「用了紧急查看」 / 实际「有人用紧急权限看了您的资料」
  //:        MEDICAL_DOCUMENT_READ  屏上「看了一份材料」 / 实际「有人看了您的就医单据」
  //:
  //: 前一种是没话说，后一种更糟：它**说了一句不一样的话**，而屏幕上看不出
  //: 这是猜的。有人改了安全设置，家人读到的是「触发了安全提醒」。
  //:
  //: 措辞逐字取自后端：有 `_WORDS_OTHER` 就用它（这一页不能对家人说「您」），
  //: 否则用 `_WORDS`。这一批是**生成**进来的，不是手打的。
  //: 前缀表留着，只当以后新事件的兜底。
  'GEOFENCE_ALERT_RAISED': '离开了常去的范围，已经提醒家人',
  'ASSISTANCE_REQUESTED': '家人请求了一次远程协助',
  'ASSISTANCE_DECIDED': '决定了一次远程协助',
  'BREAK_GLASS_CLOSED': '关闭了紧急查看权限',
  'BREAK_GLASS_OPENED': '开启了紧急查看权限',
  'BREAK_GLASS_VIEWED': '有人用紧急权限看了老人的资料',
  'CARE_PROFILE_HEARING_SUPPORT': '改了听得清一点的设置',
  'CARE_PROFILE_SPEECH_RATE': '改了说话的快慢',
  'CARE_SYMPTOM_ACKNOWLEDGED': '说了身体不舒服',
  'CONTACT_PROFILE_CREATED': '加了一位联系人',
  'CONTACT_PROFILE_DECIDED': '确认了一位联系人',
  'DEVICE_REGISTERED': '接上了一台设备',
  'DOCUMENT_ANALYZED': '看懂了一份材料',
  'EMOTIONAL_TASK_PAUSE': '先陪老人说话，原来那件事先放着',
  'EMOTIONAL_TASK_RESUMED': '回来接着办原来那件事',
  'EMOTION_SIGNAL_RECORDED': '记下了老人的心情',
  'EMOTION_SIGNAL_RECORD_FAILED': '心情没能记下来',
  'FACE_DEMO_TEMPLATE_ENROLLED': '录了一次人脸样本',
  'HEALTH_EVENT_CREATED': '记了一次身体数据',
  'INTERACTION_PROFILE_UPDATED': '改了跟老人说话的方式',
  'ITEM_MEMORY_ACTIVATED': '记住了一件东西放在哪儿',
  'ITEM_MEMORY_DECIDED': '决定了一件东西记不记',
  'ITEM_MEMORY_PROPOSED': '想让优活记一件东西，等老人点头',
  'MEDICAL_DOCUMENT_ANALYZED': '整理了一份就医单据',
  'MEDICAL_DOCUMENT_READ': '有人看了老人的就医单据',
  'MEDICATION_PLAN_ACTIVATED': '一份用药计划开始生效',
  'MEDICATION_PLAN_DECIDED': '确认了一份用药计划',
  'MEDICATION_PLAN_PROPOSED': '加了一份用药计划，等老人点头',
  'MEMORY_APPROVED': '同意记住一件事',
  'MEMORY_PROPOSED': '想让优活记一件事，等老人点头',
  'MEMORY_REJECTED': '没有同意记那一件',
  'MEMORY_REVOKED': '让优活忘掉一条',
  'OFFLINE_SYNC_CONFLICT_RESOLVED': '两处记录不一样，已经对齐',
  'PRIVACY_ERASE_EXECUTED': '删掉了一批个人数据',
  'PRIVACY_EXPORT_CREATED': '导出了一份个人数据',
  'RELIANCE_CARD_CREATED': '出了一张托付说明卡',
  'ROUTINES_MATERIALIZED': '排好了接下来的固定安排',
  'ROUTINE_CREATED': '加了一件固定安排',
  'ROUTINE_OCCURRENCE_COMPLETED': '完成了一件固定安排',
  'SAFETY_POLICY_UPDATED': '改了安全设置',
  'SAFETY_SIGNAL': '优活觉得这件事要当心',
  'UNWELL_SIGNAL': '老人说身体不舒服，已通知家人',
  'SUSPICIOUS_INSTRUCTION_BLOCKED': '挡下了一句可疑的话',
  'TASK_FAILED': '没能办成，已安全停下',
  'VOICE_CONSENSUS_RESOLVED': '有句话没听准，重新对了一遍',
};
const AUDIT_CATEGORY = [
  ['REMINDER_', '动了待办'], ['MEDICATION_', '动了用药'], ['ROUTINE_', '动了日常安排'],
  ['FAMILY_', '做了家人这边的操作'], ['TASK_', '办事时留下一条记录'], ['SAGA_', '办事时留下一条记录'],
  ['SOS_', '触发了安全提醒'], ['SAFETY_', '触发了安全提醒'], ['BREAK_GLASS_', '用了紧急查看'],
  ['PRIVACY_', '动了隐私设置'], ['MEMORY_', '动了记忆'], ['CONTACT_', '动了联系人'],
  ['DEVICE_', '动了设备'], ['DOCUMENT_', '看了一份材料'], ['MEDICAL_', '看了一份材料'],
];
/* 一个事件类型盖住**相反**的结果，结果在 payload 里。
 *
 * 实测（同一次运行里的判别对）：
 *   MEDICATION_DOSE_RECORDED {"status":"skipped"} -> 平表印「记了一次服药」
 *   MEDICATION_DOSE_RECORDED {"status":"taken"}   -> 平表印「记了一次服药」
 * 两种结果一种说法，而家人刚点的那一下是「没吃」。
 *
 * 后端对同一件事有两张按 payload 分支的表（`app_api._OUTCOME_TITLES`、
 * `_DECISION_WORDS`），`privacy._TEXT_BY_OUTCOME` 也有。老人那两屏因此
 * 都说对了；这一屏读的是**同一条**审计记录，却只按类型查一张平表。
 * `app_api.py:1612` 的注释写着「而家人读的是同一份记录」。
 *
 * 下面两张表逐字照后端那两张，**不另编措辞**——三块屏幕说同一件事时
 * 用词必须一致，各写一份迟早分叉。
 */
const AUDIT_OUTCOME = {
  MEDICATION_DOSE_RECORDED: ['status', {
    taken: '记了一次服药',
    skipped: '记了一次没吃',
    missed: '记了一次漏服',
  }],
};
//: 同意还是没同意，取决于 payload，不取决于事件类型。
//: 回绝被印成「确认了一份用药计划」比漏服那一条更重：她按的是「不同意」。
const AUDIT_DECISION = {
  'app.medication.decided': {true: '确认了一份用药计划', false: '没有同意那份用药计划'},
  'MEDICATION_PLAN_DECIDED': {true: '确认了一份用药计划', false: '没有同意那份用药计划'},
  /* 记忆那一条。**这一批表有三处**（这里、`app_api._DECISION_WORDS`、
   * `privacy._TEXT_BY_OUTCOME`），只改一处等于没改——`privacy.py` 那段
   * 注释就是在讲这件事，而它又发生了一次。
   *
   * 实测：审计 {"approved": true/false, "key": …} 两条，
   * 平表让它们在这一屏上都印「决定了一条要不要记」。
   */
  'app.memory.decided': {true: '同意记下这一条', false: '没有同意记下这一条'},
};
function auditLabel(type, payload) {
  const p = payload || {};
  const outcome = AUDIT_OUTCOME[type];
  if (outcome) {
    //: 认不出的结果**保持原样**落回平表——照后端 `app_api.py:1742`。
    const word = outcome[1][String(p[outcome[0]])];
    if (word) return word;
  }
  const decision = AUDIT_DECISION[type];
  if (decision && typeof p.approved === 'boolean') {
    return decision[String(p.approved)];
  }
  if (AUDIT_LABEL[type]) return AUDIT_LABEL[type];
  const hit = AUDIT_CATEGORY.find(([prefix]) => String(type).startsWith(prefix));
  return hit ? hit[1] : '留下一条记录';
}
//: 执行者 id -> 说给家属听的称呼。**前缀匹配，不是查一张写死 id 的表**：
//: 访客沙箱里的 id 是 `daughter-<后缀>`（`database.py:59` 那两行），
//: 而 `app/assets/js/app.js:163` 那张按 `daughter-demo` 逐字建键的表在沙箱里全落兜底。
//:
//: `fam` 那个分支是**死的**，这一轮才发现。审计里的 actor_id 只有四种形状——
//: `elder-…`、`daughter-…`、`son-…`、`system-…`（最后那个由 identity.js 把
//: `elder-` 换成 `system-` 得到），没有一个以 `fam` 开头；`fam-demo` 是 family_id，
//: 它不是执行者。实测一笔两位家属点头的缴费，链上 `FAMILY_APPROVAL_RECORDED` 的
//: actor_id 是 `daughter-demo`，落到兜底——屏幕上于是写着「优活点了同意」。
//: **点头的是女儿**，而这一页就是给她看的：一个把家属自己的操作记成系统操作的
//: 记录页，而且它看起来完全正常。
//:
//: 「女儿」「儿子」不是这里编的：后端建演示家庭时登记联系人用的就是这两个词
//: （`database.py:370`）。
function actorName(actorId) {
  const id = String(actorId || '');
  if (id.startsWith('elder')) return '他';
  if (id.startsWith('daughter')) return '女儿';
  if (id.startsWith('son')) return '儿子';
  return '优活';
}

// 身份、登录、401 重放和令牌缓存都在 common.js 里。
async function resolveIdentity() {
  if (IDENTITY) return IDENTITY;
  IDENTITY = await window.YouHuo.ready();
  ELDER_ID = IDENTITY.elderId;
  return IDENTITY;
}

async function login() {
  await resolveIdentity();
  await window.YouHuo.login('family');
}

function api(path, options = {}) {
  return window.YouHuo.api(path, options, 'family');
}

function line(parent, text, className = '') {
  const el = document.createElement('div');
  if (className) el.className = className;
  el.textContent = text;
  parent.appendChild(el);
  return el;
}

function chip(status, table) {
  const [word, cls] = table[status] || [status, 'todo'];
  const span = document.createElement('span');
  span.className = `status-chip ${cls}`;
  span.textContent = word;
  return span;
}

/** `<input type="datetime-local">` 要的那种字串：**本地**墙上时间，不带时区。
 *
 * 不能用 `toISOString().slice(0, 16)`。那是 UTC：东八区的 19:30 会显示成 11:30，
 * 于是家属一按「改时间」看到的当前值就是错的，什么都不动直接保存，
 * 这一条提醒被往前挪了八小时——而屏幕上没有任何一处会说出这件事。
 * care.js 的 `ymd()` 为同一个坑留过注释（那次是按 UTC 切日期窗口）。
 */
function localMoment(iso) {
  const when = new Date(iso);
  if (Number.isNaN(when.getTime())) return '';
  const pad = (n) => String(n).padStart(2, '0');
  return `${when.getFullYear()}-${pad(when.getMonth() + 1)}-${pad(when.getDate())}`
    + `T${pad(when.getHours())}:${pad(when.getMinutes())}`;
}

function moment(iso) {
  return new Date(iso).toLocaleString('zh-CN', {hour12: false});
}

//: 已经结束的提醒改不了——`PATCH /api/v1/reminders/{id}` 对 completed / cancelled
//: 回 409「这一条已经结束了，改不了」。前端按同一条规则决定画不画这个按钮：
//: 画一个必然失败的按钮，等于把一条规则藏进错误提示里，人要按下去才知道。
//:
//: 两个键取自 `REMINDER_STEP`（这一页的提醒状态词表，事实源在文件顶上），
//: 不另抄一份字符串——抄一份，改词表的时候这里不会跟着变。
//:
//: **「已经结束」只是后端拒绝改时间的两个理由之一。** 上面那句话是对的，但按它
//: 一个人来决定画不画按钮是不够的。六个状态各打一次 `PATCH`（家人令牌，实测）：
//:
//:     scheduled     200  改好了，… 提醒您…
//:     notified      409  这一条现在改不了。
//:     acknowledged  409  这一条现在改不了。
//:     escalated     409  这一条现在改不了。
//:     completed     409  这一条已经结束了，改不了。可以另外加一条。
//:     cancelled     409  这一条已经结束了，改不了。可以另外加一条。
//:
//: 后两个 409 来自 `app_api.py:2134` 的早退；中间那三个来自更里面一层——
//: `database.py:783` 那句 UPDATE 带着 `AND status='scheduled'`，一条已经提醒出去的
//: 待办，后端一样不让改，只是回的话不一样。于是 `notified` / `acknowledged` /
//: `escalated` 这三个状态此前照样长出一个按下去必然 409 的「改时间」，
//: 而上面那三行注释说的正是不许这样。
//:
//: 所以是**两个常量**，回答两个不同的问题：一条提醒是不是已经结束（`REMINDER_CLOSED`，
//: 用来决定要不要多说一句），和后端到底肯不肯改（`REMINDER_MOVABLE`）。
//: 后者写成**白名单**：后端将来多一个状态，默认是不画按钮，而不是默认画一个会失败的。
//: 反过来写成黑名单的话，新状态会安静地拿到一个坏按钮——那正是这次的形状。
//:
//: `POST /api/v1/reminders/{id}/done` 不受这个白名单管：实测它在六个状态上**全是
//: 200**。这一页没有「办好了」这个控件，但如果哪天要加，别拿这张表去挡它。
const REMINDER_CLOSED = ['completed', 'cancelled'];
const REMINDER_MOVABLE = ['scheduled'];

/** 「改时间」：把一条提醒挪到别的时刻。
 *
 * ## 为什么不是「取消再建一条」
 *
 * 那是这一页此前唯一的办法，两个后果：
 *   · 记录里留下「取消了一条待办」+「添了一件待办」两行，而实际发生的是一件事，
 *     审计链要能说清真正发生了什么；
 *   · 提醒表上有 `elder_id + 标题 + 到点时刻` 的唯一约束，同名同时刻会直接撞上。
 *
 * ## 改时间是可逆的，所以**不**走两步确认
 *
 * 两步留给撤不回来的那些（取消就医、删除）。给一个改错了还能再改一次的动作加
 * 一道确认，只会让真正不可逆的那道确认贬值。
 */
function rescheduleControl(reminder) {
  const box = document.createElement('div');
  const bar = document.createElement('div');
  bar.className = 'care-actions';
  const open = document.createElement('button');
  open.type = 'button';
  open.className = 'secondary';
  open.textContent = '改时间';
  bar.appendChild(open);
  box.appendChild(bar);

  open.addEventListener('click', () => {
    // 已经展开了就不要再长一份表单出来。
    if (box.querySelector('input')) return;

    const field = document.createElement('div');
    field.className = 'care-field';
    const label = document.createElement('label');
    const inputId = `remWhen-${reminder.id}`;
    label.htmlFor = inputId;
    label.textContent = `改到什么时候（现在是 ${moment(reminder.due_at)}）`;
    const input = document.createElement('input');
    input.id = inputId;
    input.type = 'datetime-local';
    input.value = localMoment(reminder.due_at);
    field.append(label, input);

    const row = document.createElement('div');
    row.className = 'care-actions';
    const save = document.createElement('button');
    save.type = 'button';
    save.textContent = '保存新时间';
    const drop = document.createElement('button');
    drop.type = 'button';
    drop.className = 'secondary';
    drop.textContent = '不改了';
    drop.addEventListener('click', () => {
      field.remove();
      row.remove();
      open.hidden = false;
      open.focus();
    });
    row.append(save, drop);

    save.addEventListener('click', () => window.YouHuo.once(save, async () => {
      if (!input.value) {
        notify('还没选新的时间。', 'warning');
        input.focus();
        return;
      }
      const picked = new Date(input.value);
      try {
        const data = await api(`/api/v1/reminders/${encodeURIComponent(reminder.id)}`, {
          method: 'PATCH', headers: {'Content-Type': 'application/json'},
          body: JSON.stringify({at: picked.toISOString()}),
        });
        // 语气跟后端走，**话不跟**。后端那句回执里的时刻是拿 UTC 排的
        //（`due.strftime('%H:%M')`，而 `due` 是 UTC 时刻），在东八区少八小时——
        // 家属挪到 19:30 会读到「改好了，11:30 提醒您」。一句说错时间的成功回执
        // 比没有回执糟：她会以为自己选错了，再改一次，再错一次。
        // 这条缺陷记在报告和 KNOWN_ISSUES 里；这一侧说她**真正选的**那个时刻。
        notify(`改好了，${moment(picked.toISOString())} 提醒他${reminder.title}。`,
               window.YouHuo.toneOf(data));
        load();
      } catch (e) {
        notify(window.YouHuo.errorWords(e, '这一条待办').text, 'warning');
      }
    }));

    open.hidden = true;
    box.append(field, row);
    input.focus();
  });
  return box;
}

/** 一条通知。读过的说读过，没读过的给一个真的能标记的按钮。
 *
 * 这一格此前只印，不收：`/v2/notifications` 一路只涨，红点永远下不去，而
 * 「标成已读」这条路后端一直是通的（`POST /api/v1/notifications/{id}/read`，
 * 写的是同一张 `notifications` 表的 `read_at`）。
 */
function noticeCard(n) {
  const div = document.createElement('div');
  div.className = 'task';
  const title = document.createElement('strong');
  // 兜底不能是原始事件码：那等于这层翻译在遇到没登记过的类型时自动失效，
  // 而那正是它该起作用的时候。下面 n.message 本来就是给人读的一句话。
  title.textContent = NOTICE_TITLE[n.event_type] || '来自优活的消息';
  div.appendChild(title);
  line(div, n.message);
  line(div, moment(n.created_at), 'meta');

  if (n.read_at) {
    // 读过的那些也留在列表里，但要看得出来已经处理过——直接抹掉一条通知，
    // 等于让家属无从确认自己刚才那一下有没有生效。
    line(div, `已读 ${moment(n.read_at)}`, 'meta');
    return div;
  }
  const row = document.createElement('div');
  row.className = 'care-actions';
  const mark = document.createElement('button');
  mark.type = 'button';
  mark.className = 'secondary';
  mark.textContent = '标为已读';
  mark.addEventListener('click', () => window.YouHuo.once(mark, async () => {
    try {
      await api(`/api/v1/notifications/${encodeURIComponent(n.id)}/read`, {method: 'POST'});
      notify('这一条标成已读了。', 'good');
      load();
    } catch (e) {
      // 已经读过的会走 404（「没有找到这条通知，或者它已经读过了」）——
      // 那句话是后端用中文写的，errorWords 会原样给出来。
      notify(window.YouHuo.errorWords(e, '这一条通知').text, 'warning');
    }
  }));
  row.appendChild(mark);
  div.appendChild(row);
  return div;
}

function fmtTask(t) {
  const div = document.createElement('div');
  div.className = 'task';
  const title = document.createElement('strong');
  title.textContent = t.summary || t.task_type;
  div.appendChild(title);
  const step = document.createElement('div');
  step.append('进行到：', chip(t.status, TASK_STEP));
  div.appendChild(step);
  line(div, `风险：${RISK_WORD[t.risk_level] || t.risk_level}`);
  // 这里原先还印一行 `t.id`——屏幕上是 `task-26c5984eb900464daa1d`。那是工程标识，
  // 和这一页上面已经译掉的 event_type / actor_id 是同一类东西：家属要的是"哪件事、
  // 到哪一步"，不是一个能 grep 的主键。逐条原始记录在可信中心，那里才是它的地方。
  if (t.status === NEEDS_FAMILY && t.approval_digest) {
    const yes = document.createElement('button'); yes.textContent = '核对后确认接力';
    const no = document.createElement('button'); no.textContent = '拒绝'; no.className = 'danger';
    // 把按钮本身传进去，approve() 才能在飞行期间禁用它。不传的话双击就是两次独立审批。
    yes.onclick = () => approve(t.id, t.approval_digest, true, yes);
    no.onclick = () => approve(t.id, t.approval_digest, false, no);
    div.append(yes, document.createTextNode(' '), no);
  }
  return div;
}

/** 操作结果条：把消息说在页面里，而不是弹一个系统对话框。
 *
 * 这里原先用 `alert()`（六处）。三个问题，从轻到重：装到主屏的 PWA 里它会显示成
 * 一个带 "127.0.0.1 显示" 字样的系统灰框，对家属来说读不出是哪一步出了事；它会
 * **冻住整页**，在自动化里表现为浏览器再也不回应任何指令；而且它不进无障碍的
 * live region，读屏用户什么也听不到。
 */
function notify(message, tone) {
  const host = document.querySelector('#familyNotice');
  if (!host) return;
  host.className = `notice ${tone || 'good'}`;
  window.YouHuo.showNotice(host,message,{duration:['bad','warning'].includes(tone)?0:5000});
}

/** 收回提示条。
 *
 * 这个函数原先不存在：`#familyNotice` 只有显示路径。地铁上信号断了打出
 * "没能取到最新情况"，出站后按刷新、四个分区全刷上新数据，而那条错误还挂在标题
 * 正下方——它带 aria-live，读屏已经念过一次，然后没有任何路径把它收回。
 */
function clearNotice() {
  const host = document.querySelector('#familyNotice');
  if (!host) return;
  /* **只收回失败提示。**
   *
   * 上面那段写的理由是「地铁上断网打出的『没能取到最新情况』要在
   * 出站刷新成功之后收回」——那是对的。但 `load()` **也被成功的写操作调用**
   * （`createReminder()` 写完回执就刷一次，提议记忆也是），
   * 于是它把刚写上去的**成功回执**一起抹掉。
   *
   * 实测（`/family2#todo`，填好一条提醒按下去）：
   *
   *     POST /v2/family/reminders        发出去了
   *     load() 的五个请求            都回来了
   *     控制台                        无错
   *     #familyNotice                   **空、hidden**
   *
   * 也就是说：家人添一条提醒，成功了，而屏幕上一个字都没有。
   * 回执活不过一次往返。这一页的主要写动作就是它。
   *
   * 成功回执不是 `load()` 该收回的东西：下一句 `notify()` 会盖掉它。
   */
  if (!/(?:^|\s)(?:bad|warning)(?:\s|$)/.test(host.className)) return;
  host.hidden = true;
  host.textContent = '';
}

async function approve(taskId, approvalDigest, approveValue, trigger) {
  await window.YouHuo.once(trigger, async () => {
    try {
      const data = await api('/v2/family/approve', {
        method: 'POST', headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({
          task_id: taskId, approve: approveValue, approval_digest: approvalDigest,
          reason: approveValue ? '家属已核对任务摘要' : '家属拒绝', request_id: crypto.randomUUID()
        })
      });
      // 语气由后端的 code / ui.theme 决定，不是一律绿色。"任务已处理或当前不需要家属
      // 审批""家属未批准，本次操作已安全取消"都是 HTTP 200——一次取消画成绿色成功框，
      // 家属无法把它和真的批准成功区分开。
      notify(data.message, window.YouHuo.toneOf(data));
      load();
    } catch (e) { notify(window.YouHuo.errorWords(e).text, 'warning'); }
  });
}

/* 上一次因为哪一格空着被挡回来的。**用来让「再按一次」也有反应。**
 *
 * 实测（`/family#todo`，表单空着连按两次）：
 *
 *     第一次   指纹 +29 · 1 个请求 · 「事项还没填。…」
 *     第二次   指纹 **0** · **0** 个请求 · 同一句话
 *
 * 同一个串赋两遍，DOM 不动。表单没变、答案也没变，所以「屏幕不变」在字面上是
 * 对的——但她之所以再按，正是因为不确定刚才那一下有没有算上。
 * CDP 巡检据此把它报成死控件，**而它没报错**。
 *
 * 记的是「哪一格」而不是一个计数：填好一格再空另一格时，第二句不该指着一格
 * 她刚填好的。
 */
let lastBlockedBy = null;

async function createReminder(e) {
  e.preventDefault();
  const titleField = document.querySelector('#reminderTitle');
  const title = titleField.value.trim();
  const dueLocal = document.querySelector('#reminderDue').value;
  const escalation = Number(document.querySelector('#escalation').value || 30);
  // 只输入空格时 `required` 是满足的（值不是空字符串），于是原先直接 return——
  // 屏幕上什么都不发生，反复点也一样。现在说出来，并把焦点送回去。
  //
  // 再按一次也要有反应：第二句多说了一件**真的发生了**的事——光标已经在那一格。
  if (!title) {
    const again = lastBlockedBy === 'title';
    lastBlockedBy = 'title';
    notify(again
      ? '「事项」那一格还是空的。光标已经放在那儿了，写一句话就行。'
      : '事项还没填。写一句他看得懂的话，比如「复诊前准备病历」。', 'warning');
    titleField.focus();
    return;
  }
  if (!dueLocal) {
    const again = lastBlockedBy === 'due';
    lastBlockedBy = 'due';
    notify(again
      ? '「时间」那一格还是空的。光标已经放在那儿了，选一个时间就行。'
      : '时间还没选。', 'warning');
    document.querySelector('#reminderDue').focus();
    return;
  }
  lastBlockedBy = null;
  await window.YouHuo.once(e.submitter || e.target.querySelector('[type="submit"]'), async () => {
    try {
      const dueAt = new Date(dueLocal).toISOString();
      const data = await api('/v2/family/reminders', {
        method: 'POST', headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({elder_id: ELDER_ID, title, due_at: dueAt,
          escalation_after_minutes: escalation, request_id: crypto.randomUUID()})
      });
      const tone = window.YouHuo.toneOf(data);
      notify(data.message, tone);
      // 只有真的添上了才清空表单。"同一时间的同一提醒已经存在"是 200，原先照样
      // reset()，把家属重试所需要的输入一起清掉——屏幕上剩一句绿色的"已经存在"和
      // 一个空表单。
      if (tone === 'good') e.target.reset();
      load();
    } catch (err) { notify(window.YouHuo.errorWords(err).text, 'warning'); }
  });
}

// 「立即检查到期待办」搬到了 /stage 的「场景注入」。它是运维动作——现在还没有
// 后台定时器，所以要手动催一下推进提前提醒与超时升级——而不是一位子女会按的按钮。
// handler 与接口一字未改，只换了位置（proof-demos.js）。

/** 「需要您确认」和「其他正在办的事」分成两处画。
 *
 * `#tasks` 原先铺的是**全部**任务：已取消的、已完成的、正在执行的，和真正在等家属
 * 点头的，混在一起按创建时间排。这一页只有最后那一类需要子女动手，而要认出它得逐张
 * 卡去读「进行到：等您接力确认」那半行小字。
 *
 * 现在 `#tasks` 只放那一类，位置提到结论正下方；其余的收进 `#otherTasks`。
 * 返回在等的件数，页头那句结论要用它——不另数一遍，避免两处对不上。
 */
function renderTasks(tasks) {
  const waiting = tasks.filter(t => t.status === NEEDS_FAMILY);
  const rest = tasks.filter(t => t.status !== NEEDS_FAMILY);

  tasksEl.replaceChildren();
  if (waiting.length) {
    waiting.forEach(t => tasksEl.appendChild(fmtTask(t)));
  } else {
    // 0 件的时候说一句话，不留一个空盒子。
    //
    // 空白说不清那是"今天没事"还是"没加载出来"，而这两件事对子女的意义完全相反。
    // 这句话原先说在日报最底下的「需要您做的」里——那是第三屏，而这里是第一屏。
    line(tasksEl, '今天不用您操心，没有要您点头的事。', 'notice good');
  }

  if (otherTasksEl) {
    otherTasksEl.replaceChildren();
    if (rest.length) rest.forEach(t => otherTasksEl.appendChild(fmtTask(t)));
    else line(otherTasksEl, '暂时没有别的事在办。', 'meta');
  }
  return waiting.length;
}

/** Overview strip: what actually needs the family's attention right now. */
function renderMetrics(tasks, reminders, chainValid) {
  const openStates = ['collecting', 'awaiting_elder_confirmation', NEEDS_FAMILY, 'executing'];
  const needYou = tasks.filter(t => t.status === NEEDS_FAMILY).length;
  const active = tasks.filter(t => openStates.includes(t.status)).length;
  const today = new Date().toDateString();
  const dueToday = reminders.filter(r =>
    new Date(r.due_at).toDateString() === today && !['completed', 'cancelled'].includes(r.status)
  ).length;

  const set = (id, value, cls) => {
    const el = document.querySelector(id);
    if (!el) return;
    el.textContent = value;
    el.parentElement.className = `metric${cls ? ' ' + cls : ''}`;
  };
  set('#mNeedYou', needYou, needYou > 0 ? 'alert' : '');
  set('#mActive', active);
  set('#mToday', dueToday);
  set('#mChain', chainValid ? '完好' : '异常', chainValid ? 'good' : 'bad');
}

/** Design §4.5: reminders grouped into a day-by-day calendar rather than a flat list. */
function renderCalendar(reminders) {
  calendarEl.replaceChildren();
  if (!reminders.length) { calendarEl.textContent = '暂无待办'; return; }
  const WEEKDAYS = ['周日', '周一', '周二', '周三', '周四', '周五', '周六'];
  const todayKey = new Date().toDateString();
  const byDay = new Map();
  [...reminders]
    .sort((a, b) => new Date(a.due_at) - new Date(b.due_at))
    .forEach(r => {
      const due = new Date(r.due_at);
      const key = due.toDateString();
      if (!byDay.has(key)) byDay.set(key, {due, items: []});
      byDay.get(key).items.push({reminder: r, due});
    });
  byDay.forEach(({due: dayDate, items: entries}, key) => {
    const day = document.createElement('div');
    day.className = 'calendar-day' + (key === todayKey ? ' today' : '');
    const heading = document.createElement('h3');
    const label = `${dayDate.getMonth() + 1}月${dayDate.getDate()}日 ${WEEKDAYS[dayDate.getDay()]}`;
    heading.textContent = key === todayKey ? `${label} · 今天` : label;
    day.appendChild(heading);
    entries.forEach(({reminder, due}) => {
      const row = document.createElement('div');
      row.className = 'calendar-entry';
      const time = document.createElement('time');
      time.dateTime = reminder.due_at;
      time.textContent = due.toLocaleTimeString('zh-CN', {hour: '2-digit', minute: '2-digit', hour12: false});
      const label = document.createElement('div');
      const what = document.createElement('div');
      what.textContent = reminder.title;
      label.appendChild(what);
      // 「改时间」挂在**中间那一格里**，不是作为条目的第四个孩子。
      // `.calendar-entry` 两份样式表里都是三列网格（时刻 / 内容 / 状态），
      // 第四个孩子会掉到下一行的第一列——那一列宽 48px（v6）或 62px（设计一），
      // 一个 48px 的按钮塞进去会顶开整张日历。实测过。
      //
      // 三条分支，不是「画 / 不画」两条：
      //   · 后端真的会改的（只有 scheduled）→ 给按钮；
      //   · 已经结束的 → 什么都不给。右边那枚药丸（「已完成」/「已取消」）
      //     已经说清这件事过去了，再补一句「改不了」是多余的；
      //   · 剩下那三个（待确认 / 老人已知道 / 超时未完成）→ 不给按钮，但**说一句**。
      //     光是把按钮撤掉，同一张日历上有的条目有按钮有的没有，看起来像界面坏了；
      //     留着按钮，就是把一条规则藏进 409 里等她按下去才知道。两样都不做，
      //     直接把规则写在它该在的地方。
      //
      // 这一句不写「先取消再加一条」：这一页**没有**取消提醒的控件（全文只打
      // 一条 `PATCH`），指一个不存在的入口和画一个必然失败的按钮是同一种错。
      if (REMINDER_MOVABLE.includes(reminder.status)) {
        label.appendChild(rescheduleControl(reminder));
      } else if (!REMINDER_CLOSED.includes(reminder.status)) {
        line(label, '这一条已经提醒出去了，时间改不了。', 'meta');
      }
      row.append(time, label, chip(reminder.status, REMINDER_STEP));
      day.appendChild(row);
    });
    calendarEl.appendChild(day);
  });
}

/* `loadWeekly()` 整体搬到 care.js（那里叫同一个名字，读同一个端点）。
 * 那段关于「按本地日期切、不是 UTC」的注释一起带过去了——它记着一个真实缺陷，
 * 留在这里没有代码配它，搬过去才有人看得见。 */

// 生活日报（设计稿 核心创新点 ②）。
//
// 与既有的情绪周报刻意不同：周报是"这一周发生了什么"，日报是"今天和他自己的常态
// 比，怎么样"。所以这里先画结论，再画分项——一份把结论埋在第四行的日报，子女读两
// 次就不会再读第三次了。
// 五个判定词的表在 common.js 里（care.js 曾有一份键与文案完全相同的副本）。
// pending 与 unknown 的区别是这个功能的要害，那个说明也在那边。
const verdictOf = window.YouHuo.verdictOf;

/** 页头那一句结论。
 *
 * 「先画结论」上一轮只做到了这一块内部：结论是 #dailyReport 的第一行，而 #dailyReport
 * 本身是页面上的第四件东西（标题 → 分区按钮 → 小标题 → 它）。现在结论是 <h1>。
 *
 * 两个数据源各自到达，所以这个函数会被调用两次以上，每次都从 CONCLUSION 里取当前
 * 知道的全部，重画一遍。**两半都还没到就什么都不写**：HTML 里那句占位留在原处，
 * 总比先写一句"他今天和平常差不多"然后再改口要好。
 */
function renderConclusion() {
  if (!verdictEl) return;
  const {report, needYou, reportFailed} = CONCLUSION;
  let sentence = null;
  let tone = '';
  if (needYou > 0) {
    // 在等她点头的事排在最前面。
    //
    // "他今天和平常一样"这句话是真的，但今天有一笔缴费卡在等她确认的时候，那句话
    // 不是这一页的结论——结论是那件事。这也是页头和它正下方那张卡必须用同一个数的
    // 原因（见 CONCLUSION 上面那段）。
    sentence = needYou === 1 ? '今天有一件事要您点头' : `今天有 ${needYou} 件事要您点头`;
    // 颜色取两件事里更重的那一个，不是固定的 warn。
    //
    // 有事等她点头**而且**他今天明显偏离常态，是这个产品定义的唯一一种"真的该打扰
    // 子女"的形状（后端 FallbackAlerting 就是按这两个条件同时成立才推送的）。那一天
    // 画成琥珀色，等于把最重的一天和"有张水费单要确认"画成同一个颜色。
    tone = report && verdictOf(report.overall)[1] === 'bad' ? 'bad' : 'warn';
  } else if (report) {
    // 自有属性才算命中。`VERDICT_SENTENCE['constructor']` 会返回一个函数（真值），
    // 于是这一行会把一段函数源码写进 <h1>。common.js 的 verdictOf 里修过同一个坑。
    // 兜底走 verdictOf，它永远不会吐出英文枚举值——**不保留原始码兜底**是这一页
    // 四张翻译表共同的立场。
    sentence = (Object.prototype.hasOwnProperty.call(VERDICT_SENTENCE, report.overall)
      && VERDICT_SENTENCE[report.overall]) || `他今天${verdictOf(report.overall)[0]}`;
    tone = verdictOf(report.overall)[1];
  } else if (reportFailed) {
    // 取不到就说取不到。占位句留在那里等于让页面永远显示"正在看今天的情况"。
    sentence = '暂时取不到今天的情况';
    tone = 'bad';
  }
  if (sentence) {
    verdictEl.textContent = sentence;
    verdictEl.className = `fam-verdict ${tone}`.trim();
  }
  // 结论下面一行放**依据**，不是再说一遍结论。
  //
  // 这里原先放的是整句 `report.headline`，而 <h1> 已经用一句短的说了结论
  // （短句是有意的：完整 headline 最长 38 字，390px 上按 26px 排是四行、吃掉
  // 四分之一首屏，而「需要您确认」必须留在第一屏）。后果是屏幕上同一句话说两遍：
  //
  //     H1     今天该有的记录还没出现
  //     紧接着 今天该有的记录还没出现（外出：今天还没有有效记录），建议打个电话问一声。
  //
  // 每个状态都在复述，`unknown` 那一条**逐字**相同，而演示数据正好停在那个状态。
  //
  // 修法不在这里截字符串——那是对一个结构化句子做字符串手术，措辞一变就错。
  // 后端这一轮开始同时给 `headline_detail`（只有依据的那半句），这里取它。
  // 老响应没有这个字段时退回整句：不能因为字段缺失就让这一行消失。
  if (!headlineEl) return;
  const detail = report
    && (report.headline_detail !== undefined ? report.headline_detail : report.headline);
  if (detail) {
    headlineEl.textContent = detail;
    headlineEl.hidden = false;
  } else {
    // 空字符串是**有意义的**：结论本身就是全部（「今天和他平常差不多。」），
    // 没有额外的依据可说，那就不画这一行，而不是画一行空的。
    headlineEl.hidden = true;
  }
}

function renderDailyReport(envelope) {
  const {report, alert} = envelope;
  dailyEl.replaceChildren();

  // 1. 结论不在这一块里了。
  //
  //    它原先是这里的第一行（`.report-verdict` 徽标 + headline），而这一块本身排在
  //    标题、四个分区按钮和一个小标题之后——"结论在最前"只做到了这一块内部，页面上
  //    它是第四件东西。现在结论是 <h1>，由 renderConclusion() 写。
  //
  //    徽标随之取消，不是漏了：徽标里那个词（「和平常一样」）和 <h1> 那句话
  //    （「他今天和平常差不多」）说的是同一件事，两处都印等于把结论说两遍。
  CONCLUSION.report = report;
  CONCLUSION.reportFailed = false;
  renderConclusion();

  // 2. 要不要现在打扰您，以及为什么不。把"没有推送"的理由也写出来，
  //    是因为沉默本身需要解释——否则子女无法判断是"今天没事"还是"App 坏了"。
  const alertRow = document.createElement('p');
  alertRow.className = `meta ${alert.push ? 'bad' : ''}`;
  // 这句话前面原先有一个 ⚠。那是 emoji，而这个项目八条硬约束的第七条是"不用 emoji
  // 当图标"（全站内联 SVG + currentColor，emoji 只出现在真实用户内容里）。而且它是
  // 这一行唯一的非文字通道，读屏软件会把它念成"警告"或者整个跳过，两种都不是这句话
  // 想说的。`.meta.bad` 的红字加上"已推送提醒"四个字已经把它说清了。
  alertRow.textContent = (alert.push ? '已推送提醒：' : '未打扰您：') + alert.reason;
  dailyEl.appendChild(alertRow);

  // 3. 分项：最多两条留在流里，其余收进「查看全部」。
  //
  //    这几项原先全部平铺，于是在"还不好说"那一态下，同一句"只有 N 天的记录，
  //    不足 7 天，还不能说这是他的常态"会连着出现五遍，把首屏整个吃掉，"需要
  //    您处理"被挤到两屏以下。而那一态恰恰是新装用户和评委最先看到的。
  //
  //    上一轮的办法是整段塞进一个 `<details>`、有事才自动展开。那修掉了刷屏，但也
  //    让"有事"的那一态从"看得见"变成"展开着的一整段"——三个分项六行字，六行里真正
  //    要紧的那一行没有任何优先权。
  //
  //    现在按严重程度排：最靠前的两条直接可读，其余（包括那五遍重复）收进「查看
  //    全部」。两条是这一屏能给分项的全部预算——结论在页头，要动手的在它正下方，
  //    分项是第三位；而分项永远是三段（作息、活动与交流、用药），不封顶就等于让
  //    第三位的东西铺满一屏。
  const RANK = {bad: 0, warn: 1, '': 2, good: 3};
  const insights = [];
  report.sections.forEach(section => {
    const [sword, stone] = verdictOf(section.verdict);
    section.lines.forEach(text => insights.push({title: section.title, word: sword, tone: stone, text}));
  });
  // sort 在现代引擎里是稳定的，所以同一档之内保持后端给的顺序（作息、活动、用药）。
  insights.sort((a, b) => (RANK[a.tone] === undefined ? 9 : RANK[a.tone])
    - (RANK[b.tone] === undefined ? 9 : RANK[b.tone]));

  /** 把几条洞察画成按分项分组的块。同一个分项连着的几条并到一个标题下。 */
  const paintInsights = (host, items) => {
    let block = null;
    let title = null;
    items.forEach(item => {
      if (item.title !== title) {
        block = document.createElement('div');
        block.className = 'report-section';
        const heading = document.createElement('h3');
        heading.textContent = item.title;
        const tag = document.createElement('span');
        tag.className = `pill ${item.tone}`.trim();
        tag.textContent = item.word;
        heading.appendChild(tag);
        block.appendChild(heading);
        host.appendChild(block);
        title = item.title;
      }
      line(block, item.text);
    });
  };

  const INSIGHT_VISIBLE = 2;
  paintInsights(dailyEl, insights.slice(0, INSIGHT_VISIBLE));
  const rest = insights.slice(INSIGHT_VISIBLE);
  if (rest.length) {
    const more = document.createElement('details');
    more.className = 'report-more';
    // 不再自动展开。排序已经把最严重的两条放到了外面，"值得替家属打开"的东西
    // 现在本来就不在这个 `<details>` 里——自动展开只会把刚收起来的那几行放回去。
    const summary = document.createElement('summary');
    summary.textContent = `查看全部（另有 ${rest.length} 条）`;
    more.appendChild(summary);
    paintInsights(more, rest);
    dailyEl.appendChild(more);
  }

  // 4. 今天该办的事。
  const errands = report.errands;
  const errandBlock = document.createElement('div');
  errandBlock.className = 'report-section';
  const errandTitle = document.createElement('h3');
  errandTitle.textContent = '今天该办的事';
  errandBlock.appendChild(errandTitle);
  line(errandBlock, `到期 ${errands.due_today} 项，已完成 ${errands.completed} 项，`
    + `等您确认 ${errands.awaiting_family} 项，超期 ${errands.overdue} 项。`, 'meta');
  errands.lines.forEach(text => line(errandBlock, text));
  dailyEl.appendChild(errandBlock);

  // 5. 建议。
  //
  //    标题从「需要您做的」改成「给您的建议」：真正需要她动手的那件事现在在页头正
  //    下方的「需要您确认」里，两个标题都写"需要您…"会让人以为要在这里再点一次。
  //    这里是建议（"方便的话晚上跟他聊两句"），不是任务。
  //
  //    空的时候不再画。原先空着也画一句绿色的「今天不用您操心。」，理由是"空着也要
  //    说出来——那是一个结论，不是没有结论"。那个理由仍然成立，但那句话现在说在
  //    「需要您确认」那张卡里：第一屏、结论正下方，是子女真会看到的位置，而这里是
  //    第三屏。同一句话配两个绿框，等于两遍都不算数。
  if (report.suggested_for_family.length) {
    const advice = document.createElement('div');
    advice.className = 'report-section';
    const adviceTitle = document.createElement('h3');
    adviceTitle.textContent = '给您的建议';
    advice.appendChild(adviceTitle);
    report.suggested_for_family.forEach(text => line(advice, text));
    dailyEl.appendChild(advice);
  }

  if (report.environment_note) line(dailyEl, report.environment_note, 'meta');
  // 隐私声明是一条每天都一样的脚注，原先用 `.notice good` 渲染成一整块绿框，
  // 和"今天不用您操心"抢同一级视觉权重。承诺要一直写着，但它不是今天的新闻。
  line(dailyEl, report.privacy_note, 'meta');
}

async function loadDailyReport() {
  try {
    renderDailyReport(await api(`/v7/daily-report/${ELDER_ID}`));
  } catch (e) {
    // 页头那句结论也要跟着改口。少了这三行，请求失败时 <h1> 会永远停在 HTML 里那句
    // 占位「正在看今天的情况」——一个永远在加载、什么都不说的页面。这一页为登录失败
    // 修过同一个毛病，那次漏的是 #dailyReport，这次漏的会是 <h1>。
    CONCLUSION.report = null;
    CONCLUSION.reportFailed = true;
    renderConclusion();
    dailyEl.replaceChildren();
    dailyEl.textContent = window.YouHuo.errorWords(e, '今天的情况').text;
  }
}

const APP_SUBVIEW = document.documentElement.classList.contains('app4-embedded') ? new URLSearchParams(location.search).get('view') : null;
const APP_CARE_VIEWS = new Set(['med','body','mood','safety','trend','today']);
function renderAuditRecords(audit) {
    chainEl.textContent = audit.chain_valid
      ? `这 ${audit.events.length} 条记录从头到尾没有被改过。`
      : '记录对不上了，请到可信中心看详情。';
    chainEl.classList.toggle('good', audit.chain_valid);
    chainEl.classList.toggle('bad', !audit.chain_valid);
    auditEl.replaceChildren();
    //: 先把内部事件滤掉，再取前 8 条。**顺序不能反**——先截后滤的话，
    //: 一屏家常就能把真事全挤出这 8 行，而屏幕上看不出少了东西。
    const AUDIT_APP_SESSION = new Set(['DEMO_LOGIN','SESSION_CREATED']);
    const meaningful = audit.events.slice().reverse()
      .filter(e => !AUDIT_INTERNAL.has(e.event_type) && !(document.documentElement.classList.contains('app4-embedded') && AUDIT_APP_SESSION.has(e.event_type)));
    const internalCount = audit.events.length - meaningful.length;
    if (!meaningful.length && document.documentElement.classList.contains('app4-embedded')) line(auditEl, '还没有办事记录。', 'meta');
    meaningful.slice(0, AUDIT_VISIBLE).forEach(e => {
      const row = document.createElement('div');
      row.className = 'audit-row';
      const what = document.createElement('span');
      what.className = 'audit-what';
      // 「谁」和「做了什么」中间要有间隔，**不能直接拼**。
      //
      // `AUDIT_LABEL` 这一轮的说法逐字取自后端那张表，而那张表是给 `/app/records`
      // 写的——那里每一条**自己就是一整句**，前面不带执行者。直接拼会得到
      // 「他这件事办妥了」「优活家人已点头」这种句子：前者不通，后者把主语说了两遍。
      // 分隔符照 `app/assets/js/app.js:171` 的凭证完整链（说法 · 谁 · 摘要），
      // 三个壳于是读起来是一套。
      //: payload 一起传下去。整条事件本来就在手上，只是没往下给——
      //: 于是「没吃」和「吃了」在这一行上是同一句话。
      what.textContent = `${actorName(e.actor_id)}　·　${auditLabel(e.event_type, e.payload)}`;
      const when = document.createElement('time');
      when.dateTime = e.created_at;
      when.textContent = new Date(e.created_at).toLocaleString('zh-CN', {hour12: false, dateStyle: undefined, timeStyle: undefined});
      row.append(what, when);
      auditEl.appendChild(row);
    });
    if (meaningful.length > AUDIT_VISIBLE) {
      line(auditEl, `另有 ${meaningful.length - AUDIT_VISIBLE} 条更早的记录。`, 'meta');
    }
    //: 滤掉的那些**报个数**，不做成看不见的差额——说法逐字同老人端那一侧。
    if (internalCount > 0) {
      line(auditEl, `另有 ${internalCount} 条系统记录。`, 'meta');
    }
}
async function loadAppSubview() {
  if (APP_SUBVIEW === 'history') {
    renderAuditRecords(await api('/v2/audit?limit=80'));
  } else {
    const [tasks,reminders,notices] = await Promise.all([
      api('/v2/tasks?limit=100'),api('/v2/reminders?limit=100'),api('/v2/notifications?limit=50')]);
    renderTasks(tasks); renderCalendar(reminders);
    noticesEl.replaceChildren(); notices.forEach(n=>noticesEl.appendChild(noticeCard(n)));
    if (!notices.length) noticesEl.textContent='暂无通知';
  }
  clearNotice();
}

async function load() {
  try {
    if (APP_SUBVIEW && !APP_CARE_VIEWS.has(APP_SUBVIEW)) { await loadAppSubview(); return; }
    const [tasks, audit, reminders, notices] = await Promise.all([
      api('/v2/tasks?limit=100'), api('/v2/audit?limit=80'), api('/v2/reminders?limit=100'), api('/v2/notifications?limit=50')
    ]);
    // 「需要您确认」和页头那句结论用的是同一份 tasks，同一个计数。
    CONCLUSION.needYou = renderTasks(tasks);
    renderConclusion();

    renderAuditRecords(audit);
    updatedEl.textContent = `最后更新 ${new Date().toLocaleTimeString('zh-CN', {hour: '2-digit', minute: '2-digit', hour12: false})}`;
    // 这一轮成功了，就把上一轮的失败提示收回。否则地铁上断网打出的"没能取到最新
    // 情况"会在出站刷新成功之后继续挂在标题正下方——它带 aria-live，读屏已经念过
    // 一次，而原先没有任何路径把它收回。
    clearNotice();

    renderCalendar(reminders);
    renderMetrics(tasks, reminders, audit.chain_valid);

    noticesEl.replaceChildren();
    notices.forEach(n => noticesEl.appendChild(noticeCard(n)));
    if (!notices.length) noticesEl.textContent = '暂无通知';
  } catch (e) {
    // 这条 catch 罩着四个并发请求加一次登录。它原先写进 #chain——那是"记录完好"
    // 的位置，日历加载失败会显示成记录出了问题。分区改版之后 #chain 默认还是折叠
    // 的，再写那里就等于整条失败无人可见。写进 #familyNotice：它一直在屏幕上，
    // 而且带 aria-live。
    notify(window.YouHuo.errorWords(e, '最新情况').text, 'bad');
    // 这一行原先固定写「暂时没连上」，而它罩着的四个请求也可能是后端拒绝或
    // 500——那时说"没连上"是错的诊断。分型之后由 errorWords 说对。
    updatedEl.textContent = window.YouHuo.errorWords(e).say;
    // 这一轮不知道有几件事在等她点头，就必须说"不知道"，不能留着上一轮的数字：
    // 页头照旧写着"今天有一件事要您点头"，而底下那张卡这一轮根本没画出来。
    // 不知道的时候由紧接着的 loadDailyReport() 收尾——它成功就写日报的结论，
    // 它也失败就写「暂时取不到今天的情况」。
    CONCLUSION.needYou = null;
  }
  // `loadWeekly()` 不在这里了——「趋势」那一格搬去了 /care，由那一页的
  // 六段并发里加载。
  if (!APP_SUBVIEW) loadDailyReport();
}

// 页内分区的实现在 common.js，照护页用的是同一套。
window.YouHuo.initSections('today');

document.querySelector('#refresh').addEventListener('click',
  () => window.YouHuo.once('#refresh', load));
document.querySelector('#reminderForm').addEventListener('submit', createReminder);

/* 「让优活记住一件事」。
 *
 * 在这一条之前 `/v3/memories/propose` **全仓零个前端消费者**：老人端三个界面
 * 都能点头、能不点、能逐条收回了（这一轮补的），而没有任何界面能提出一条——
 * 那张「等您点头」的卡片于是在产品里永远不会出现，要看见它得直接打 API。
 *
 * 接线的实体在 `common.js`（两个界面共用一份：请求形状、三个固定档、
 * 那几句话、以及「再按一次也要有反应」）。这一页只交元素和 `notify`。
 *
 * `elderId` 传**函数**：`ELDER_ID` 到身份解析完（第 241 行）才是真值，
 * 而这里在模块顶层跑。冻住它会让这个表单一直往 `elder-demo` 身上提议。
 */
window.YouHuo.wireProposeMemory({
  form: document.querySelector('#memoryForm'),
  submit: document.querySelector('#memoryForm [type="submit"]'),
  keyInput: document.querySelector('#memKey'),
  detailInput: document.querySelector('#memDetail'),
  purposeInput: document.querySelector('#memPurpose'),
  elderId: () => ELDER_ID,
  notify,
  //: 提完刷新一次：待办那一屏的「等他点头」条数会跟着变。
  after: load,
});

// 登录失败也必须写在看得见的地方。
//
// 这里原先是 `.catch(e => { chainEl.textContent = e.message; })`——和 load() 的 catch
// 一模一样的错，只是我上一轮只改了 load() 那一处。后果更重：登录失败时 load() 从不
// 执行，于是 #famUpdated 永久停在"正在加载……"、#dailyReport 永久停在"正在生成……"、
// 任务/日历/通知全空，而唯一那句错误在 #chain 里，#chain 在默认折叠的「我的」分区里。
// 子女看到的是一个永远转圈、什么都不说的页面。
// 现在 <h1> 也在这条路径上：登录失败时 load() 从不执行，renderConclusion() 也就
// 从来没人调用，页头会永久停在 HTML 里那句占位。这正是上面那段说的同一个毛病，
// 只是换了一个元素——所以这一次连它一起写。
// 这里原先是 `notify(\`没能登录：${e.message}\`, 'bad')`——把平台抛的异常消息
// 原样印到家属面上。`fetch` 自己失败时那句话是 `Failed to fetch`，屏幕上出现的
// 整句是「没能登录：Failed to fetch」：一句英文，而这个项目的硬约束是界面上
// 不许出现英文。common.js 的 `errorWords` 就是这道闸门的落点，它按 `.status`
// 分四型、每型带一条仍然走得通的路。
// `test_consumer_errors_are_typed_not_raw` 认的是 `catch (e) {` 这种写法，
// 而这里是 `.catch(e => …)`——所以它一直是绿的，这一处是它看不见的地方。
(APP_CARE_VIEWS.has(APP_SUBVIEW) ? Promise.resolve() : login().then(load)).catch(e => {
  notify(window.YouHuo.errorWords(e, '这一侧的账户').text, 'bad');
  updatedEl.textContent = window.YouHuo.errorWords(e).say;
  dailyEl.textContent = '登录失败，暂时取不到今天的情况。';
  CONCLUSION.reportFailed = true;
  renderConclusion();
}).finally(() => { document.documentElement.dataset.businessReadyFamily = 'true'; document.dispatchEvent(new CustomEvent('app4:business-ready', {detail:'family'})); });
