const ELDER_ID = 'elder-demo';

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

let accessToken = sessionStorage.getItem('youhuo_family_token');
const tasksEl = document.querySelector('#tasks');
const auditEl = document.querySelector('#audit');
const chainEl = document.querySelector('#chain');
const calendarEl = document.querySelector('#calendar');
const noticesEl = document.querySelector('#notices');
const weeklyEl = document.querySelector('#weekly');

async function login() {
  const r = await fetch('/v2/auth/demo', {
    method: 'POST', headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({actor_id: 'daughter-demo'})
  });
  const data = await r.json();
  if (!r.ok) throw new Error(data.detail || '家属端演示登录失败');
  accessToken = data.access_token;
  sessionStorage.setItem('youhuo_family_token', accessToken);
}

async function api(path, options = {}) {
  if (!accessToken) await login();
  const headers = {...(options.headers || {}), Authorization: `Bearer ${accessToken}`};
  const r = await fetch(path, {...options, headers});
  if (r.status === 401) {
    accessToken = null; sessionStorage.removeItem('youhuo_family_token'); await login(); return api(path, options);
  }
  const data = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(data.detail || `请求失败（${r.status}）`);
  return data;
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

async function approve(taskId, approvalDigest, approveValue) {
  try {
    const data = await api('/v2/family/approve', {
      method: 'POST', headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({
        task_id: taskId, approve: approveValue, approval_digest: approvalDigest,
        reason: approveValue ? '家属已核对任务摘要' : '家属拒绝', request_id: crypto.randomUUID()
      })
    });
    alert(data.message); load();
  } catch (e) { alert(e.message); }
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
    alert(data.message); e.target.reset(); load();
  } catch (err) { alert(err.message); }
}

async function runScheduler() {
  try {
    const data = await api('/v2/demo/scheduler/evaluate', {
      method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({now: new Date().toISOString()})
    });
    alert(`提前提醒 ${data.advance_notified} 条，到期提醒 ${data.notified} 条，升级家属 ${data.escalated} 条`);
    load();
  } catch (e) { alert(e.message); }
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

async function load() {
  try {
    const [tasks, audit, reminders, notices] = await Promise.all([
      api('/v2/tasks?limit=100'), api('/v2/audit?limit=80'), api('/v2/reminders?limit=100'), api('/v2/notifications?limit=50')
    ]);
    tasksEl.replaceChildren();
    tasks.forEach(t => tasksEl.appendChild(fmtTask(t)));
    if (!tasks.length) tasksEl.textContent = '暂无任务';

    chainEl.textContent = audit.chain_valid ? '✓ HMAC审计链校验通过' : '⚠ 审计链校验失败';
    chainEl.classList.toggle('good', audit.chain_valid);
    auditEl.replaceChildren();
    audit.events.slice().reverse().forEach(e => {
      const row = document.createElement('div');
      row.className = 'audit-row';
      const head = document.createElement('div');
      head.className = 'audit-head';
      const type = document.createElement('code');
      type.textContent = e.event_type;
      const when = document.createElement('time');
      when.dateTime = e.created_at;
      when.textContent = new Date(e.created_at).toLocaleString('zh-CN', {hour12: false});
      head.append(type, when);
      const actor = document.createElement('div');
      actor.className = 'meta';
      actor.textContent = `执行者：${e.actor_id}`;
      row.append(head, actor);
      auditEl.appendChild(row);
    });

    renderCalendar(reminders);
    renderMetrics(tasks, reminders, audit.chain_valid);

    noticesEl.replaceChildren();
    notices.forEach(n => {
      const div = document.createElement('div');
      div.className = 'task';
      const title = document.createElement('strong');
      title.textContent = NOTICE_TITLE[n.event_type] || n.event_type;
      div.appendChild(title);
      line(div, n.message);
      line(div, new Date(n.created_at).toLocaleString('zh-CN', {hour12: false}), 'meta');
      noticesEl.appendChild(div);
    });
    if (!notices.length) noticesEl.textContent = '暂无通知';
  } catch (e) { chainEl.textContent = `加载失败：${e.message}`; }
  loadWeekly();
}

document.querySelector('#refresh').addEventListener('click', load);
document.querySelector('#scheduler').addEventListener('click', runScheduler);
document.querySelector('#reminderForm').addEventListener('submit', createReminder);
login().then(load).catch(e => { chainEl.textContent = e.message; });
