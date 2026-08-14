// Resolved from identity.js; see the note there about per-visitor sandboxes.
let ELDER_ID = 'elder-demo';
let IDENTITY = null;

// Design §4.5: the family view shows "which step is this task on" in plain words,
// not raw backend enum values.
const TASK_STEP = {
  collecting: ['正在收集信息', 'todo'],
  awaiting_elder_confirmation: ['等老人复述确认', 'confirm'],
  awaiting_family_approval: ['等您接力确认', 'relay'],
  executing: ['正在执行', 'todo'],
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

const NOTICE_TITLE = {
  approval_required: '需要您接力确认',
  additional_approval_required: '还需要另一位家属确认',
  task_rejected: '已按您的意见取消',
  task_completed: '任务已完成',
  family_reminder_created: '待办已同步到老人端',
  reminder_due: '待办到期提醒',
  reminder_advance_notice: '已提前提醒老人',
  reminder_escalated: '超时未完成，请接力',
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
const AUDIT_VISIBLE = 8;
const AUDIT_LABEL = {
  SESSION_CREATED: '登录了', DEMO_LOGIN: '登录了', DEMO_SEEDED: '开通了这个家庭的账户',
  TASK_CREATED: '开始办一件事', TASK_EXECUTED: '办完了一件事', TASK_CANCELLED: '取消了一件事',
  TASK_EXPLANATION_VIEWED: '看了办事经过', TASK_PROOF_GENERATED: '生成了回执',
  TASK_SLOT_CORRECTED: '更正了信息', ELDER_CONFIRMED: '确认了',
  FAMILY_APPROVAL_RECORDED: '点了同意', FAMILY_APPROVED_AND_EXECUTED: '同意后办好了',
  FAMILY_APPROVED_EXECUTION_FAILED: '同意了但没办成', FAMILY_REJECTED: '拒绝了',
  FAMILY_REMINDER_CREATED: '添了一件待办', REMINDER_CREATED: '添了一件待办',
  REMINDER_COMPLETE: '完成了一件待办', REMINDER_ACKNOWLEDGE: '知道了这件待办',
  REMINDER_CANCELLED: '取消了一件待办', PAYMENT_REQUEST_CREATED: '生成了缴费单',
  SOS_TRIGGERED: '按了紧急求助', MEDICATION_DOSE_RECORDED: '记了一次吃药',
  TEACH_BACK_VERIFIED: '复述确认通过', TEACH_BACK_REJECTED: '复述没对上',
};
const AUDIT_CATEGORY = [
  ['REMINDER_', '动了待办'], ['MEDICATION_', '动了用药'], ['ROUTINE_', '动了日常安排'],
  ['FAMILY_', '做了家人这边的操作'], ['TASK_', '办事时留下一条记录'], ['SAGA_', '办事时留下一条记录'],
  ['SOS_', '触发了安全提醒'], ['SAFETY_', '触发了安全提醒'], ['BREAK_GLASS_', '用了紧急查看'],
  ['PRIVACY_', '动了隐私设置'], ['MEMORY_', '动了记忆'], ['CONTACT_', '动了联系人'],
  ['DEVICE_', '动了设备'], ['DOCUMENT_', '看了一份材料'], ['MEDICAL_', '看了一份材料'],
];
function auditLabel(type) {
  if (AUDIT_LABEL[type]) return AUDIT_LABEL[type];
  const hit = AUDIT_CATEGORY.find(([prefix]) => String(type).startsWith(prefix));
  return hit ? hit[1] : '留下一条记录';
}
function actorName(actorId) {
  const id = String(actorId || '');
  if (id.startsWith('elder')) return '他';
  if (id.startsWith('fam')) return '家人';
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
  host.textContent = message;
  host.hidden = false;
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

async function createReminder(e) {
  e.preventDefault();
  const titleField = document.querySelector('#reminderTitle');
  const title = titleField.value.trim();
  const dueLocal = document.querySelector('#reminderDue').value;
  const escalation = Number(document.querySelector('#escalation').value || 30);
  // 只输入空格时 `required` 是满足的（值不是空字符串），于是原先直接 return——
  // 屏幕上什么都不发生，反复点也一样。现在说出来，并把焦点送回去。
  if (!title) {
    notify('事项还没填。写一句他看得懂的话，比如「复诊前准备病历」。', 'warning');
    titleField.focus();
    return;
  }
  if (!dueLocal) {
    notify('时间还没选。', 'warning');
    document.querySelector('#reminderDue').focus();
    return;
  }
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
      label.textContent = reminder.title;
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

async function load() {
  try {
    const [tasks, audit, reminders, notices] = await Promise.all([
      api('/v2/tasks?limit=100'), api('/v2/audit?limit=80'), api('/v2/reminders?limit=100'), api('/v2/notifications?limit=50')
    ]);
    // 「需要您确认」和页头那句结论用的是同一份 tasks，同一个计数。
    CONCLUSION.needYou = renderTasks(tasks);
    renderConclusion();

    chainEl.textContent = audit.chain_valid
      ? `这 ${audit.events.length} 条记录从头到尾没有被改过。`
      : '记录对不上了，请到可信中心看详情。';
    chainEl.classList.toggle('good', audit.chain_valid);
    chainEl.classList.toggle('bad', !audit.chain_valid);
    auditEl.replaceChildren();
    audit.events.slice().reverse().slice(0, AUDIT_VISIBLE).forEach(e => {
      const row = document.createElement('div');
      row.className = 'audit-row';
      const what = document.createElement('span');
      what.className = 'audit-what';
      what.textContent = `${actorName(e.actor_id)}${auditLabel(e.event_type)}`;
      const when = document.createElement('time');
      when.dateTime = e.created_at;
      when.textContent = new Date(e.created_at).toLocaleString('zh-CN', {hour12: false, dateStyle: undefined, timeStyle: undefined});
      row.append(what, when);
      auditEl.appendChild(row);
    });
    if (audit.events.length > AUDIT_VISIBLE) {
      line(auditEl, `另有 ${audit.events.length - AUDIT_VISIBLE} 条更早的记录。`, 'meta');
    }
    updatedEl.textContent = `最后更新 ${new Date().toLocaleTimeString('zh-CN', {hour: '2-digit', minute: '2-digit', hour12: false})}`;
    // 这一轮成功了，就把上一轮的失败提示收回。否则地铁上断网打出的"没能取到最新
    // 情况"会在出站刷新成功之后继续挂在标题正下方——它带 aria-live，读屏已经念过
    // 一次，而原先没有任何路径把它收回。
    clearNotice();

    renderCalendar(reminders);
    renderMetrics(tasks, reminders, audit.chain_valid);

    noticesEl.replaceChildren();
    notices.forEach(n => {
      const div = document.createElement('div');
      div.className = 'task';
      const title = document.createElement('strong');
      // 兜底不能是原始事件码：那等于这层翻译在遇到没登记过的类型时自动失效，
      // 而那正是它该起作用的时候。下面 n.message 本来就是给人读的一句话。
      title.textContent = NOTICE_TITLE[n.event_type] || '来自优活的消息';
      div.appendChild(title);
      line(div, n.message);
      line(div, new Date(n.created_at).toLocaleString('zh-CN', {hour12: false}), 'meta');
      noticesEl.appendChild(div);
    });
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
  loadDailyReport();
}

// 页内分区的实现在 common.js，照护页用的是同一套。
window.YouHuo.initSections('today');

document.querySelector('#refresh').addEventListener('click',
  () => window.YouHuo.once('#refresh', load));
document.querySelector('#reminderForm').addEventListener('submit', createReminder);

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
login().then(load).catch(e => {
  notify(`没能登录：${e.message}`, 'bad');
  updatedEl.textContent = '暂时没连上';
  dailyEl.textContent = '登录失败，暂时取不到今天的情况。';
  CONCLUSION.reportFailed = true;
  renderConclusion();
});
