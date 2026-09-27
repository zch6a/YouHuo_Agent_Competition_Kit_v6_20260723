/* 新版家人端（/family4）的接线。确认付款走 `/v2/family/approve`，和旧版同一个端点。 */
import {api, el, toast, tabs, carousel, metric, todaySays, dayLine, avatar} from '/static/app4/core4.js';

const ROLE = 'family';
const $ = id => document.getElementById(id);

function row({when, what, sub, pill, tone}) {
  const r = el('div', 'a4-row');
  if (when) r.append(el('span', 'when', when));
  const w = el('div', 'what', what);
  if (sub) w.append(el('small', '', sub));
  r.append(w);
  if (pill) r.append(el('span', `a4-pill ${tone || ''}`.trim(), pill));
  return r;
}
function fill(box, nodes, empty) {
  $(box).replaceChildren(...(nodes.length ? nodes : [el('p', 'a4-empty', empty)]));
}

const TASK_WORD = {bill_payment: '缴费', appointment: '挂号', registration: '挂号'};
//: 键是全部 `TaskStatus`，字和 `common.js` 的 `STATUS_WORD_OTHER`（他称：家人读老人的事）逐字相同。
//: 第一版自己起了一套短说法（「办完了」「没办成」），`test_one_status_has_one_word` 判它漂移。
const STATUS_WORD = {
  collecting: ['正在收集信息', ''],
  awaiting_elder_confirmation: ['等老人复述确认', ''],
  awaiting_family_approval: ['等您接力确认', 'late'],
  executing: ['正在办理', ''],
  completed: ['已完成并核验', 'ok'],
  cancelled: ['已取消', ''],
  failed: ['未成功，已安全停下', 'late'],
};

// 同一笔不许点两次：按下后两个按钮都变灰，直到服务器回话。
const inFlight = new Set();
async function decide(task, approve, buttons) {
  if (inFlight.has(task.id)) return;
  inFlight.add(task.id);
  buttons.forEach(b => { b.disabled = true; });
  try {
    const data = await api(ROLE, '/v2/family/approve', {
      method: 'POST',
      body: {task_id: task.id, approve, approval_digest: task.approval_digest,
             reason: approve ? '家属已核对任务摘要' : '家属拒绝', request_id: crypto.randomUUID()},
    });
    toast(data.message || (approve ? '已经确认' : '已经回绝'));
  } catch (e) {
    toast(`没办成：${e.message}`);
  } finally {
    inFlight.delete(task.id);
    refresh();
  }
}

function approvalCard(task) {
  const box = el('div');
  box.append(row({what: `老人想${TASK_WORD[task.task_type] || '办一件事'}`, sub: task.summary, pill: '等您点头', tone: 'late'}));
  const actions = el('div', 'a4-actions');
  const yes = el('button', 'a4-btn', '确认，替他办');
  const no = el('button', 'a4-btn danger', '先不办');
  yes.type = no.type = 'button';
  yes.addEventListener('click', () => decide(task, true, [yes, no]));
  no.addEventListener('click', () => decide(task, false, [yes, no]));
  actions.append(yes, no);
  box.append(actions);
  return box;
}

async function refresh() {
  const [report, meds, rems, news, tasks, profile, contacts] = await Promise.allSettled([
    api(ROLE, '/api/v1/daily-report'), api(ROLE, '/api/v1/medications'),
    api(ROLE, '/api/v1/reminders'), api(ROLE, '/api/v1/notifications?role=family'),
    api(ROLE, '/v2/tasks?limit=100'), api(ROLE, '/api/v1/profile'), api(ROLE, '/api/v1/contacts'),
  ]).then(rs => rs.map(r => (r.status === 'fulfilled' ? r.value : null)));

  // `/api/v1/profile` 回的是**登录的人自己**（家人端登录的是女儿）。第一版拿它当老人的名字，
  // 屏上出了「女儿今天还没有记录」。看的人是女儿，就照旧版家人端叫「爸爸」。
  const name = '爸爸';
  $('who').textContent = '优活';

  if (tasks) {
    const waiting = tasks.filter(t => t.status === 'awaiting_family_approval');
    fill('approveHome', waiting.slice(0, 2).map(approvalCard), '现在没有要您确认的事');
    fill('approveAll', waiting.map(approvalCard), '现在没有要您确认的事');
    fill('doneList', tasks.filter(t => t.status !== 'awaiting_family_approval').map(t => {
      const [word, tone] = STATUS_WORD[t.status] || ['进行中', ''];
      return row({what: t.summary, sub: TASK_WORD[t.task_type] || '', pill: word, tone});
    }), '还没有办过的事');
    $('badge').hidden = !waiting.length;
    $('badge').textContent = String(waiting.length);

  }

  const slides = [];
  if (report) {
    $('heroDate').textContent = dayLine(report.day);
    $('heroLine').textContent = `${todaySays(report.todayWord)}${report.errands.overdue ? `，有${report.errands.overdue}件事过了点` : ''}`;
    // 「爸爸今天怎么样」已经在上面 hero 里说了，轮播不再重复一遍。
    const e = report.errands;
    slides.push(metric({tag: '该办的事', done: e.done, total: e.dueToday,
                       label: '已办完 / 今天安排',
                       more: e.overdue ? `有${e.overdue}件过了点` : '', tone: e.overdue ? 'warm' : ''}));
    fill('errands', (e.lines || []).map(l => row({what: l})), '今天没有要办的事');
    fill('channels', report.channels.map(c => row({
      what: c.name, sub: c.usual ? `平时 ${c.usual}` : '', when: c.today || '',
      pill: c.word, tone: c.word === '和平常一样' ? 'ok' : '',
    })), '还没攒够几天的记录');
  }
  if (meds) {
    slides.push(metric({tag: '吃药', done: meds.takenCount, total: meds.plannedCount,
                       label: '已记服用 / 今天计划', more: meds.stockWarning || '', tone: 'alt'}));
    const rows = meds.doses.map(d => row({when: d.time, what: d.name, sub: d.doseText, pill: d.status, tone: d.pending ? '' : 'ok'}));
    meds.plans.forEach(p => rows.push(row({what: `${p.name}还够${p.daysRemaining}天`, sub: `${p.depletionDate}前要续`, pill: p.stockLabel, tone: p.alertLevel === 'normal' ? 'ok' : 'late'})));
    fill('meds', rows, '没有吃药计划');
  }
  if (slides.length) { $('slides').replaceChildren(...slides); rebuildDots(); }

  if (rems) {
    fill('reminders', rems.items.map(it => row({
      when: it.time, what: it.title, sub: `${it.date} · ${it.kind}`,
      pill: it.done ? '办完了' : it.overdue ? '过点了' : it.status, tone: it.done ? 'ok' : it.overdue ? 'late' : '',
    })), '还没有提醒');
  }
  if (news) {
    const rows = news.items.map(n => row({what: n.title, sub: n.time}));
    fill('newsHome', rows.slice(0, 3), '还没有消息');
    fill('newsAll', news.items.map(n => row({what: n.title, sub: n.time})), '还没有消息');
  }
  if (contacts) {
    fill('people', contacts.items.filter(c => c.role !== '系统').map(c => {
      const item=row({what:c.name,sub:c.primary ? '最先联系的人' : c.role});
      item.prepend(avatar(c)); return item;
    }), '还没有家人');
  }
  return news;
}

let seen = null;
async function poll() {
  try {
    const news = await api(ROLE, '/api/v1/notifications?role=family');
    if (seen) {
      const fresh = news.items.filter(n => !seen.has(n.id));
      if (fresh.length) { toast(fresh[0].title); refresh(); }
    }
    seen = new Set(news.items.map(n => n.id));
  } catch (_) { /* 下次再看 */ }
}

let rebuildDots = () => {};
tabs();
rebuildDots = carousel(document.querySelector('.a4-banner')) || (() => {});
refresh().then(news => { if (news) seen = new Set(news.items.map(n => n.id)); })
  .catch(e => toast(`没连上：${e.message}`));
// 家人等的是「老人刚提了一笔」，比老人端看得勤一点。
setInterval(poll, 20_000);

window.addEventListener("app4:refresh", () => refresh().catch(e => toast(e.message)));
