/* 新版老人端（/elder4）的接线。数据全走已有端点，对话走 `/v2/chat`。 */
import {api, token, icon, el, toast, tabs, carousel, slide, metric, todaySays, dayLine, avatar} from '/static/app4/core4.js';
import {configureNeuralVoice, probeNeuralVoice, speakClauses, warmNeuralVoice} from '/static/speech.js';

const ROLE = 'elder';
const $ = id => document.getElementById(id);

// ---------------------------------------------------------------- 朗读
let stopSpeaking = null;
let speechRate = 0.88;
let voiceLabel = '手机自带的声音';
configureNeuralVoice({
  getToken: () => token(ROLE),
  onStatus: s => {
    voiceLabel = s && s.available ? '晓晓的声音' : '手机自带的声音';
    $('voiceState').textContent = voiceLabel;
  },
});
function say(text) {
  if (!text) return;
  if (stopSpeaking) stopSpeaking();
  try { stopSpeaking = speakClauses(text, {rate:speechRate}); } catch (_) { stopSpeaking = null; }
}

// ---------------------------------------------------------------- 对话
const SESSION_KEY = 'a4.session.elder';
let sessionId = sessionStorage.getItem(SESSION_KEY);
let sessionPending = null;
async function ensureSession() {
  if (sessionId) return sessionId;
  // 只合并**同时在飞**的那一次（她连点两个宫格时别开两个会话），落地就清掉——不是记忆化。
  if (sessionPending) return sessionPending;
  sessionPending = (async () => {
    const d = await api(ROLE, '/v2/sessions', {method: 'POST', body: {}});
    sessionId = d.session_id;
    sessionStorage.setItem(SESSION_KEY, sessionId);
    return sessionId;
  })();
  try {
    return await sessionPending;
  } finally {
    sessionPending = null;
  }
}
async function postChat(text) {
  const send = async () => api(ROLE, '/v2/chat', {
    method: 'POST', body: {session_id: await ensureSession(), text, request_id: crypto.randomUUID()},
  });
  try {
    return await send();
  } catch (e) {
    // 会话来自旧库或别的家庭：重开一次会话再试（旧版踩过这个坑）。
    // 网络失败可能发生在操作已经完成后，不能擅自开新会话再办一遍。
    if (!['会话不存在，请先创建会话。', '会话不属于当前账户。'].includes(e.message)) throw e;
    sessionId = null; sessionStorage.removeItem(SESSION_KEY);
    return send();
  }
}

function bubble(text, who, extra = '') {
  const b = el('div', `a4-msg ${who} ${extra}`.trim(), text);
  $('msgs').append(b);
  $('msgs').scrollTop = $('msgs').scrollHeight;
  return b;
}

/** 回复里若在等她确认金额，给两个大按钮，省得她说不清。 */
function followUps(reply) {
  const out = [];
  const amount = reply && reply.data && (reply.data.amount_yuan || reply.data.expected);
  if (reply && reply.code === 'need_elder_confirmation' && amount) {
    out.push([`确认支付${amount}元`, `确认支付${amount}元`], ['不办了', '取消任务']);
  }
  return out;
}

let busy = false;
function agentState(state) {
  window.dispatchEvent(new CustomEvent('app4:agent-state', {detail:{state}}));
}
const toolLabels = {schedule_today:'今日安排', medication_today:'服药记录', medication_list:'用药清单', medication_stock:'药品余量', health_recent:'身体记录', family_contacts:'家人联系人', today_date:'当前日期', unpaid_bills:'待缴账单', start_errand:'办理流程'};
async function ask(text) {
  text = String(text || '').trim();
  if (!text || busy) return;
  openSheet();
  busy = true;
  agentState('thinking');
  bubble(text, 'me');
  const wait = bubble('我在想', 'bot');
  $('hint').textContent = '';
  try {
    const reply = await postChat(text);
    wait.textContent = reply.message || '我没听明白，您换个说法再说一次';
    const buttons = followUps(reply);
    const awaiting = /confirm|approval/.test(reply.code || '') || buttons.length > 0;
    agentState(awaiting ? 'confirmation' : 'result');
    const used = reply.data?.agent?.tools || [];
    const labels = [...new Set(used.map(name => toolLabels[name]).filter(Boolean))];
    if (labels.length) {
      const receipt = el('details', 'a4-agent-receipt');
      receipt.append(el('summary', '', '查看处理依据'), el('small', '', `本次使用：${labels.join('、')}`));
      wait.append(receipt);
    }
    if (buttons.length) {
      const row = el('div', 'actions');
      for (const [label, phrase] of buttons) {
        const b = el('button', '', label);
        b.type = 'button';
        b.addEventListener('click', () => ask(phrase));
        row.append(b);
      }
      wait.append(row);
    }
    if (reply.ui && reply.ui.speak === false) { /* 服务器说这句不用念 */ } else say(reply.message);
    refresh();
  } catch (e) {
    agentState('error');
    wait.classList.add('warn');
    wait.textContent = '暂时没收到回复。请先查看办事记录，避免重复提交。';
  } finally {
    busy = false;
  }
}

function openSheet() {
  if (!$('sheet').hidden) return;
  $('sheet').hidden = false;
  if (!$('msgs').children.length) bubble('您说，我听着。想办的事、想问的事都行。', 'bot');
  warmNeuralVoice();
}
function closeSheet() {
  $('sheet').hidden = true;
  stopListening();
  if (stopSpeaking) stopSpeaking();
}

// ---------------------------------------------------------------- 听写
const Recognition = window.SpeechRecognition || window.webkitSpeechRecognition;
let recognizer = null;
function stopListening() {
  if (!busy) agentState('idle');
  document.body.dataset.listening = 'off';
  if (recognizer) { try { recognizer.stop(); } catch (_) { /* 已停 */ } recognizer = null; }
}
function listen() {
  openSheet();
  if (!Recognition) {
    $('hint').textContent = '这台设备听不了说话，请在下面打字';
    $('say').focus();
    return;
  }
  if (recognizer) { stopListening(); return; }
  if (stopSpeaking) stopSpeaking();
  warmNeuralVoice();
  recognizer = new Recognition();
  recognizer.lang = 'zh-CN';
  recognizer.interimResults = true;
  recognizer.maxAlternatives = 1;
  document.body.dataset.listening = 'on';
  agentState('listening');
  $('hint').textContent = '我在听，您说完停一下就好';
  let finalText = '';
  recognizer.onresult = ev => {
    let live = '';
    for (const r of ev.results) { if (r.isFinal) finalText = r[0].transcript; else live += r[0].transcript; }
    $('hint').textContent = finalText || live || '我在听';
  };
  recognizer.onerror = ev => {
    $('hint').textContent = ev.error === 'not-allowed' ? '没拿到话筒的许可，请在下面打字' : '没听清，您再按一下说';
  };
  recognizer.onend = () => {
    document.body.dataset.listening = 'off';
    recognizer = null;
    if (!finalText && !busy) agentState('idle');
    if (finalText) ask(finalText);
  };
  try { recognizer.start(); } catch (_) { stopListening(); }
}

// ---------------------------------------------------------------- 页面数据
function row({when, what, sub, pill, tone}) {
  const r = el('div', 'a4-row');
  if (when) r.append(el('span', 'when', when));
  const w = el('div', 'what', what);
  if (sub) w.append(el('small', '', sub));
  r.append(w);
  if (pill) r.append(el('span', `a4-pill ${tone || ''}`.trim(), pill));
  return r;
}
function fill(box, rows, empty) {
  $(box).replaceChildren(...(rows.length ? rows : [el('p', 'a4-empty', empty)]));
}
function reminderRow(it) {
  const late = it.overdue && !it.done;
  return row({
    when: it.time, what: it.title, sub: `${it.date} · ${it.kind}`,
    pill: it.done ? '办完了' : late ? '过点了' : it.status, tone: it.done ? 'ok' : late ? 'late' : '',
  });
}

async function medicationConsent(identity) {
  const box=el('section','a4-med-consent');
  $('medCard').append(box);
  try {
    const plans=await api(ROLE,`/v4/medications/${identity.elderId}`);
    for (const plan of plans.filter(item=>!item.active)) {
      const card=el('section','a4-consent-note');
      card.append(el('strong','','请核对家人添加的用药计划'),el('p','',plan.display_name),
        el('p','',`${plan.dose_text} · 每天 ${plan.times_local.join('、')}`),
        el('p','',`${plan.start_date}起${plan.end_date ? '，至'+plan.end_date : ''}`));
      const actions=el('div','a4-actions');
      for(const [label,approve] of [['核对无误，启用',true],['暂不启用',false]]) {
        const button=el('button',approve?'a4-btn':'a4-btn ghost',label); button.type='button';
        button.addEventListener('click',()=>window.YouHuo.once(button,async()=>{
          actions.querySelectorAll('button').forEach(b=>{b.disabled=true;});
          try { await api(ROLE,'/v4/medications/decide',{method:'POST',body:{record_id:plan.id,approve}}); await refresh(); toast(approve?'用药计划已启用':'这条计划未启用'); }
          catch(error){ toast(window.YouHuo.errorWords(error).text); actions.querySelectorAll('button').forEach(b=>{b.disabled=false;}); }
        })); actions.append(button);
      }
      card.append(actions); box.append(card);
    }
  } catch(error) { box.append(el('p','a4-note',window.YouHuo.errorWords(error,'待确认的用药计划').text)); }
}

async function refresh() {
  const identity = await window.YouHuo.ready();
  api(ROLE, `/v6/profiles/${identity.elderId}`).then(preferences => {
    speechRate = Number(preferences.speech_rate) || 0.88;
    const scale = Number(preferences.font_scale) || 1.25;
    document.body.dataset.fontTier = scale >= 1.6 ? 'huge' : scale < 1.2 ? 'compact' : 'normal';
  }).catch(() => {});
  const [report, meds, rems, contacts, profile, inbox] = await Promise.allSettled([
    api(ROLE, '/api/v1/daily-report'), api(ROLE, '/api/v1/medications'),
    api(ROLE, '/api/v1/reminders'), api(ROLE, '/api/v1/contacts'),
    api(ROLE, '/api/v1/profile'), api(ROLE, '/api/v1/notifications'),
  ]).then(rs => rs.map(r => (r.status === 'fulfilled' ? r.value : null)));

  if (profile) {
    $('hello').textContent = '优活';
    $('heroName').textContent = `${profile.name}，您好`;
    $('meName').textContent = profile.name;
  }

  // 轮播：三页，都来自服务器
  const slides = [];
  if (rems && rems.items.length) {
    const next = rems.items.find(it => !it.done && !it.cancelled) || rems.items[0];
    slides.push(slide({tag: next.overdue ? '过点了' : '下一件事', title: next.title,
                       more: `${next.date} ${next.time}`, tone: next.overdue ? '' : 'warm',
                       img: '/static/app4/art-sun.svg'}));
  }
  if (meds) slides.push(metric({tag: '吃药', done: meds.takenCount, total: meds.plannedCount,
                                label: '已记服用 / 今天计划', more: meds.stockWarning || '', tone: 'alt'}));
  if (report) slides.push(slide({tag: '今天', title: todaySays(report.todayWord),
                                 more: (report.errands.lines || [])[0] || '', img: '/static/app4/art-home.svg'}));
  if (slides.length) { $('slides').replaceChildren(...slides); rebuildDots(); }

  if (rems) {
    const today = rems.items.filter(it => it.date === (rems.items[0] || {}).date);
    fill('todayList', today.slice(0, 4).map(reminderRow), '今天没有要办的事');
    fill('allReminders', rems.items.map(reminderRow), '还没有提醒');
  } else {
    fill('todayList', [], '暂时没看到安排，稍后再看');
  }

  if (meds) {
    const rows = meds.doses.map(d => row({when: d.time, what: d.name, sub: d.doseText,
                                         pill: d.status, tone: d.pending ? '' : 'ok'}));
    rows.push(el('p', 'a4-note', meds.stockWarning || meds.summary));
    fill('medCard', rows, '今天没有要吃的药');
    await medicationConsent(identity);
  }

  if (report) {
    $('heroDate').textContent = dayLine(report.day);
    $('dayWord').textContent = `${todaySays(report.todayWord)}。${(report.errands.lines || []).join('')}`;
    $('familySees').textContent = report.familyWillSee || '家人只看到您让他们看的';
  }

  if (contacts) {
    const people = contacts.items.filter(c => c.role === '家人' || c.role === '社区');
    const chips = people.map(c => {
      const b = el('button', 'a4-chip');
      b.type = 'button';
      b.append(avatar(c), document.createTextNode(`找${c.name}`));
      b.addEventListener('click', () => ask(`给${c.name}打电话`));
      return b;
    });
    $('familyChips').replaceChildren(...chips);
    fill('contactList', people.map(c => {
      const r = row({what: c.name, sub: c.primary ? '最先联系的人' : c.role});
      r.prepend(avatar(c));
      const b = el('button', 'a4-btn a4-call');
      b.append(icon('phone'),el('span','','拨打'));
      b.setAttribute('aria-label',`给${c.name}打电话`);
      b.type = 'button';
      b.addEventListener('click', () => ask(`给${c.name}打电话`));
      r.append(b);
      return r;
    }), '还没有家人');
  }

  if (inbox) fill('inbox', inbox.items.map(n => row({what: n.title, sub: n.time})), '还没有消息');
  return inbox;
}

// 新消息：一分钟看一次，新来的念一句。
let seen = null;
async function poll() {
  try {
    const inbox = await api(ROLE, '/api/v1/notifications');
    const ids = new Set(inbox.items.map(n => n.id));
    if (seen) {
      const fresh = inbox.items.filter(n => !seen.has(n.id));
      if (fresh.length) { toast(fresh[0].title); say(fresh[0].title); refresh(); }
    }
    seen = ids;
  } catch (_) { /* 下一分钟再看 */ }
}

// ---------------------------------------------------------------- 接线
let rebuildDots = () => {};
function wire() {
  tabs();
  rebuildDots = carousel(document.querySelector('.a4-banner')) || (() => {});
  document.querySelectorAll('[data-say]').forEach(b => b.addEventListener('click', () => ask(b.dataset.say)));
  document.querySelectorAll('[data-open-chat]').forEach(b => b.addEventListener('click', () => { openSheet(); $('say').focus(); }));
  $('talkFab').addEventListener('click', listen);
  $('talkBtn').addEventListener('click', listen);
  $('sheetClose').addEventListener('click', closeSheet);
  $('compose').addEventListener('submit', ev => {
    ev.preventDefault();
    const text = $('say').value;
    $('say').value = '';
    ask(text);
  });
  $('say').addEventListener('input', warmNeuralVoice, {once: true});
  $('voiceTest').addEventListener('click', () => say('您好，我是优活，有事您就跟我说。'));
  document.addEventListener('keydown', ev => { if (ev.key === 'Escape' && !$('sheet').hidden) closeSheet(); });
}

wire();
window.addEventListener('app4:pet-chat', event => {
  if (event.detail?.voice) listen();
  else { openSheet(); $('say').focus(); }
});
refresh().then(inbox => { if (inbox) seen = new Set(inbox.items.map(n => n.id)); })
  .catch(e => toast(`没连上：${e.message}`));
probeNeuralVoice();
setInterval(poll, 60_000);

window.addEventListener("app4:refresh", () => refresh().catch(e => toast(e.message)));
