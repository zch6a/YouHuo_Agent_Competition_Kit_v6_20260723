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
const WEEKLY_LABEL = {
  event_count: '记录到的情绪信号',
  label_counts: '情绪类别分布',
  average_distress: '平均压力指数',
  trend: '与上一周期相比',
  safe_suggestions: '可以做的小事',
  raw_text_included: '是否包含聊天原文',
  diagnosis_provided: '是否给出医学诊断',
};

const WEEKLY_TREND = {
  distress_increasing: '压力上升，建议多陪伴',
  distress_decreasing: '压力下降',
  stable_or_insufficient: '平稳或样本不足',
};

const EMOTION_LABEL = {
  calm: '平静', lonely: '孤单', anxious: '焦虑', sad: '低落',
  happy: '开心', angry: '生气', distressed: '明显不适',
};

function weeklyValue(key, value) {
  if (key === 'trend') return WEEKLY_TREND[value] || value;
  if (typeof value === 'boolean') return value ? '是' : '否';
  if (Array.isArray(value)) return value.length ? value.join('；') : '暂无';
  if (value && typeof value === 'object') {
    const parts = Object.entries(value).map(([k, v]) => `${EMOTION_LABEL[k] || k} ${v}次`);
    return parts.length ? parts.join('，') : '本周期没有记录';
  }
  return String(value);
}

const tasksEl = document.querySelector('#tasks');
const auditEl = document.querySelector('#audit');
const chainEl = document.querySelector('#chain');
const calendarEl = document.querySelector('#calendar');
const noticesEl = document.querySelector('#notices');
const weeklyEl = document.querySelector('#weekly');
const dailyEl = document.querySelector('#dailyReport');
const updatedEl = document.querySelector('#famUpdated');

// 审计事件的类型码是给工程和评委看的：`FAMILY_APPROVED_AND_EXECUTED`、
// `system-vc8693dfcd970`。这一页原先把它们原样印出来给家属看。家属要的是
// "谁，做了什么，什么时候"，不是一条能 grep 的日志。
//
// 有近百种事件码，逐个翻译既写不全也会过期，所以是"认识的说人话，不认识的按
// 前缀归类"。**不保留原始码做兜底**——兜底成原始码，等于这层翻译在遇到新事件
// 时自动失效，而那正是它该起作用的时候。逐条原文在 /trust，那里才是它的地方。
const AUDIT_VISIBLE = 8;
const AUDIT_LABEL = {
  SESSION_CREATED: '登录了', DEMO_LOGIN: '登录了', DEMO_SEEDED: '准备了演示数据',
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
  line(div, t.id, 'meta');
  if (t.status === 'awaiting_family_approval' && t.approval_digest) {
    const yes = document.createElement('button'); yes.textContent = '核对后确认接力';
    const no = document.createElement('button'); no.textContent = '拒绝'; no.className = 'danger';
    yes.onclick = () => approve(t.id, t.approval_digest, true);
    no.onclick = () => approve(t.id, t.approval_digest, false);
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

async function approve(taskId, approvalDigest, approveValue) {
  try {
    const data = await api('/v2/family/approve', {
      method: 'POST', headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({
        task_id: taskId, approve: approveValue, approval_digest: approvalDigest,
        reason: approveValue ? '家属已核对任务摘要' : '家属拒绝', request_id: crypto.randomUUID()
      })
    });
    notify(data.message); load();
  } catch (e) { notify(e.message, 'warning'); }
}

async function createReminder(e) {
  e.preventDefault();
  const title = document.querySelector('#reminderTitle').value.trim();
  const dueLocal = document.querySelector('#reminderDue').value;
  const escalation = Number(document.querySelector('#escalation').value || 30);
  if (!title || !dueLocal) return;
  try {
    const dueAt = new Date(dueLocal).toISOString();
    const data = await api('/v2/family/reminders', {
      method: 'POST', headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({elder_id: ELDER_ID, title, due_at: dueAt,
        escalation_after_minutes: escalation, request_id: crypto.randomUUID()})
    });
    notify(data.message); e.target.reset(); load();
  } catch (err) { notify(err.message, 'warning'); }
}

async function runScheduler() {
  try {
    const data = await api('/v2/demo/scheduler/evaluate', {
      method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({now: new Date().toISOString()})
    });
    notify(`提前提醒 ${data.advance_notified} 条，到期提醒 ${data.notified} 条，`
      + `升级家属 ${data.escalated} 条`);
    load();
  } catch (e) { notify(e.message, 'warning'); }
}

/** Overview strip: what actually needs the family's attention right now. */
function renderMetrics(tasks, reminders, chainValid) {
  const openStates = ['collecting', 'awaiting_elder_confirmation', 'awaiting_family_approval', 'executing'];
  const needYou = tasks.filter(t => t.status === 'awaiting_family_approval').length;
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

/** Design §4.5: only a redacted companion digest reaches the family. */
async function loadWeekly() {
  const end = new Date();
  const start = new Date(end.getTime() - 6 * 24 * 3600 * 1000);
  const iso = d => d.toISOString().slice(0, 10);
  try {
    const report = await api(
      `/v4/reports/emotion/${ELDER_ID}?period_start=${iso(start)}&period_end=${iso(end)}`
    );
    weeklyEl.replaceChildren();
    line(weeklyEl, `${report.period_start} 至 ${report.period_end}`, 'meta');
    const table = document.createElement('div');
    table.className = 'digest';
    Object.entries(report.summary).forEach(([key, value]) => {
      const row = document.createElement('div');
      row.className = 'digest-row';
      const label = document.createElement('strong');
      label.textContent = WEEKLY_LABEL[key] || key;
      const cell = document.createElement('div');
      cell.textContent = weeklyValue(key, value);
      row.append(label, cell);
      table.appendChild(row);
    });
    weeklyEl.appendChild(table);
    line(weeklyEl, report.privacy_guarantee, 'notice good');
  } catch (e) { weeklyEl.textContent = `周报加载失败：${e.message}`; }
}

// 生活日报（设计稿 核心创新点 ②）。
//
// 与既有的情绪周报刻意不同：周报是"这一周发生了什么"，日报是"今天和他自己的常态
// 比，怎么样"。所以这里先画结论，再画分项——一份把结论埋在第四行的日报，子女读两
// 次就不会再读第三次了。
// 五个判定词的表在 common.js 里（care.js 曾有一份键与文案完全相同的副本）。
// pending 与 unknown 的区别是这个功能的要害，那个说明也在那边。
const verdictOf = window.YouHuo.verdictOf;

function renderDailyReport(envelope) {
  const {report, alert} = envelope;
  dailyEl.replaceChildren();

  // 1. 结论。一句话，最大字号，带颜色。
  const [word, tone] = verdictOf(report.overall);
  const verdict = document.createElement('div');
  verdict.className = `report-verdict ${tone}`;
  const badge = document.createElement('span');
  badge.className = 'report-badge';
  badge.textContent = word;
  const headline = document.createElement('strong');
  headline.textContent = report.headline;
  verdict.append(badge, headline);
  dailyEl.appendChild(verdict);

  // 2. 要不要现在打扰您，以及为什么不。把"没有推送"的理由也写出来，
  //    是因为沉默本身需要解释——否则子女无法判断是"今天没事"还是"App 坏了"。
  const alertRow = document.createElement('p');
  alertRow.className = `meta ${alert.push ? 'bad' : ''}`;
  alertRow.textContent = (alert.push ? '⚠ 已推送提醒：' : '未打扰您：') + alert.reason;
  dailyEl.appendChild(alertRow);

  // 3. 分项，每一项都带他自己的常态——但默认收起来。
  //
  //    这几项原先全部平铺，于是在"还不好说"那一态下，同一句"只有 N 天的记录，
  //    不足 7 天，还不能说这是他的常态"会连着出现五遍，把首屏整个吃掉，"需要
  //    您处理"被挤到两屏以下。而那一态恰恰是新装用户和评委最先看到的。
  //
  //    有事的时候自动展开，没事的时候收起来：一句话的结论已经在上面了，细节
  //    是给想追问的人准备的，不是给每个人都读一遍的。
  const shown = report.sections.filter(section => section.lines.length);
  if (shown.length) {
    // 只有 warn / bad 才值得替家属打开。`pending`（还不好说）和 `typical`
    // （和平常一样）都不是，尤其 pending——那正是刷屏的那一态。
    const worth = shown.some(section => ['warn', 'bad'].includes(verdictOf(section.verdict)[1]));
    const more = document.createElement('details');
    more.className = 'report-more';
    more.open = worth;
    const summary = document.createElement('summary');
    summary.textContent = worth ? '有几项想让您看一眼' : '作息、活动、用药的细节';
    more.appendChild(summary);
    shown.forEach(section => {
      const block = document.createElement('div');
      block.className = 'report-section';
      const title = document.createElement('h3');
      const [sword, stone] = verdictOf(section.verdict);
      title.textContent = section.title;
      const tag = document.createElement('span');
      tag.className = `pill ${stone}`;
      tag.textContent = sword;
      title.appendChild(tag);
      block.appendChild(title);
      section.lines.forEach(text => line(block, text));
      more.appendChild(block);
    });
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

  // 5. 建议。空着也要说出来——"今天不用您操心"是一个结论，不是没有结论。
  const advice = document.createElement('div');
  advice.className = 'report-section';
  const adviceTitle = document.createElement('h3');
  adviceTitle.textContent = '需要您做的';
  advice.appendChild(adviceTitle);
  if (report.suggested_for_family.length) {
    report.suggested_for_family.forEach(text => line(advice, text));
  } else {
    line(advice, '今天不用您操心。', 'notice good');
  }
  dailyEl.appendChild(advice);

  if (report.environment_note) line(dailyEl, report.environment_note, 'meta');
  // 隐私声明是一条每天都一样的脚注，原先用 `.notice good` 渲染成一整块绿框，
  // 和"今天不用您操心"抢同一级视觉权重。承诺要一直写着，但它不是今天的新闻。
  line(dailyEl, report.privacy_note, 'meta');
}

async function loadDailyReport() {
  try {
    renderDailyReport(await api(`/v7/daily-report/${ELDER_ID}`));
  } catch (e) {
    dailyEl.replaceChildren();
    dailyEl.textContent = `生活日报加载失败：${e.message}`;
  }
}

async function load() {
  try {
    const [tasks, audit, reminders, notices] = await Promise.all([
      api('/v2/tasks?limit=100'), api('/v2/audit?limit=80'), api('/v2/reminders?limit=100'), api('/v2/notifications?limit=50')
    ]);
    tasksEl.replaceChildren();
    tasks.forEach(t => tasksEl.appendChild(fmtTask(t)));
    if (!tasks.length) tasksEl.textContent = '暂无任务';

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
    notify(`没能取到最新情况：${e.message}`, 'bad');
    updatedEl.textContent = '暂时没连上';
  }
  loadWeekly();
  loadDailyReport();
}

// 页内分区。刻意不换路由：六条路由、service worker 外壳清单、manifest 的
// start_url 全部不动，而且切换没有网络往返——这一页在地铁上也要能翻。
// 当前分区写进 hash，刷新之后还在原地；家属点开一条通知回来时不会被扔回"今天"。
const segs = [...document.querySelectorAll('.seg')];
const panels = [...document.querySelectorAll('[data-panel]')];
function showSection(name, pushHash) {
  const target = panels.some(p => p.dataset.panel === name) ? name : 'today';
  panels.forEach(p => { p.hidden = p.dataset.panel !== target; });
  segs.forEach(s => {
    const on = s.dataset.section === target;
    s.classList.toggle('is-current', on);
    if (on) s.setAttribute('aria-current', 'true'); else s.removeAttribute('aria-current');
  });
  if (pushHash) history.replaceState(null, '', `#${target}`);
}
segs.forEach(s => s.addEventListener('click', () => showSection(s.dataset.section, true)));
window.addEventListener('hashchange', () => showSection(location.hash.slice(1), false));
showSection(location.hash.slice(1) || 'today', false);

document.querySelector('#refresh').addEventListener('click', load);
document.querySelector('#scheduler').addEventListener('click', runScheduler);
document.querySelector('#reminderForm').addEventListener('submit', createReminder);
login().then(load).catch(e => { chainEl.textContent = e.message; });
