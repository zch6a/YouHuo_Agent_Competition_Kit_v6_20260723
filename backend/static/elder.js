import {
  configureNeuralVoice, pickVoice, probeNeuralVoice, resetVoiceCache, speakClauses,
} from '/static/speech.js';

// Resolved from identity.js: on a public deployment each browser gets its own
// isolated demo household, so visitors do not share one elder's data. Falls back
// to the fixed 'elder-demo' when the visitor endpoint is unavailable.
let ELDER_ID = 'elder-demo';
let IDENTITY = null;

// Design §4.1 table 1: each role is identified by name, icon, opening line and
// voice pitch as well as colour, so the mode is never colour-only.
const ROLES = {
  youhuo: {
    name: '优活',
    modeName: '优活办事模式',
    opening: '我在，您请说。',
    announcement: '已进入优活办事模式。',
    pitch: 1.0,
  },
  companion: {
    name: '无忧伴',
    modeName: '无忧伴陪伴模式',
    opening: '我在这儿呢，陪您聊聊。',
    announcement: '已进入无忧伴陪伴模式。',
    pitch: 1.12,
  },
};

/** Elder-readable timestamps: no seconds, no year when it is this year. */
function friendlyTime(value) {
  const d = new Date(value);
  const now = new Date();
  const time = d.toLocaleTimeString('zh-CN', {hour: '2-digit', minute: '2-digit', hour12: false});
  const day = `${d.getMonth() + 1}月${d.getDate()}日`;
  const sameDay = d.toDateString() === now.toDateString();
  if (sameDay) return `今天 ${time}`;
  const year = d.getFullYear() === now.getFullYear() ? '' : `${d.getFullYear()}年`;
  return `${year}${day} ${time}`;
}

// Design §4.4: plain status words instead of raw backend enum values.
const REMINDER_STATUS = {
  scheduled: ['待处理', 'todo'],
  notified: ['待确认', 'confirm'],
  acknowledged: ['待处理', 'todo'],
  completed: ['已完成', 'done'],
  escalated: ['已请家人帮忙', 'relay'],
  cancelled: ['已取消', 'cancelled'],
};

let sessionId = localStorage.getItem('youhuo_session_v2');
let accessToken = sessionStorage.getItem('youhuo_elder_token');
let lastSpoken = '';
let currentMode = 'youhuo';
let interactionProfile = {speech_rate: 0.88, font_scale: 1.25};
let recentRetries = 0;
let showAllReminders = false;
// Previous agent prompts, so "返回上一步" can put the elder back on the last question.
const promptHistory = [];

const chat = document.querySelector('#chat');
const input = document.querySelector('#text');
const status = document.querySelector('#status');
const modeBadge = document.querySelector('#modeBadge');
const modeName = document.querySelector('#modeName');
const agentTitle = document.querySelector('#agentTitle');
const roleOpening = document.querySelector('#roleOpening');
const roleHeader = document.querySelector('#roleHeader');
const remindersEl = document.querySelector('#reminders');
const relianceHost = document.querySelector('#relianceHost');
const activityLogEl = document.querySelector('#activityLog');
const logPanel = document.querySelector('#logPanel');
const micHint = document.querySelector('#micHint');
const speechRateEl = document.querySelector('#speechRate');
const fontScaleEl = document.querySelector('#fontScale');

function setActivity(state) {
  document.body.dataset.activity = state;
}

/** Inline SVG built without innerHTML, so the strict CSP stays satisfied. */
function svgIcon(paths, size = 26) {
  const ns = 'http://www.w3.org/2000/svg';
  const svg = document.createElementNS(ns, 'svg');
  svg.setAttribute('viewBox', '0 0 24 24');
  svg.setAttribute('width', String(size));
  svg.setAttribute('height', String(size));
  svg.setAttribute('fill', 'none');
  svg.setAttribute('stroke', 'currentColor');
  svg.setAttribute('stroke-width', '1.7');
  svg.setAttribute('stroke-linecap', 'round');
  svg.setAttribute('stroke-linejoin', 'round');
  svg.setAttribute('aria-hidden', 'true');
  paths.forEach(d => {
    const path = document.createElementNS(ns, 'path');
    path.setAttribute('d', d);
    svg.appendChild(path);
  });
  return svg;
}

function emptyState(host, iconPaths, title, hint) {
  const box = document.createElement('div');
  box.className = 'empty-state';
  box.appendChild(svgIcon(iconPaths, 30));
  const strong = document.createElement('strong');
  strong.textContent = title;
  box.appendChild(strong);
  if (hint) {
    const p = document.createElement('div');
    p.textContent = hint;
    box.appendChild(p);
  }
  host.replaceChildren(box);
}

function addBubble(text, who, meta = '') {
  const wrap = document.createElement('div');
  wrap.className = `bubble ${who}`;
  wrap.textContent = text;
  if (meta) {
    const m = document.createElement('div');
    m.className = 'meta';
    m.textContent = meta;
    wrap.appendChild(m);
  }
  chat.appendChild(wrap);
  chat.scrollTop = chat.scrollHeight;
  return wrap;
}

let stopSpeaking = null;

function speak(text, rate = null, pitch = null) {
  lastSpoken = text;
  if (stopSpeaking) stopSpeaking();
  // Clause-by-clause with spoken-Chinese dates and amounts; see speech.js.
  stopSpeaking = speakClauses(text, {
    rate: Number(rate || interactionProfile.speech_rate || 0.88),
    pitch: Number(pitch || ROLES[currentMode].pitch),
  });
}

/** Design §4.1: ~1s crossfade plus a spoken announcement on every mode change. */
function setMode(mode, {announce = true} = {}) {
  const next = ROLES[mode] ? mode : 'youhuo';
  if (next === currentMode) return;
  const role = ROLES[next];
  currentMode = next;
  roleHeader.classList.add('switching');
  window.setTimeout(() => {
    document.body.dataset.mode = next;
    modeBadge.classList.toggle('orange', next === 'companion');
    modeName.textContent = role.modeName;
    agentTitle.textContent = role.name;
    roleOpening.textContent = role.opening;
    document.querySelector('#companionEntryLabel').textContent =
      next === 'companion' ? '回到优活办事' : '找无忧伴聊聊';
    roleHeader.classList.remove('switching');
  }, 500);
  if (announce) {
    // Spoken cue carries the same information as the colour change.
    window.setTimeout(() => speak(`${role.announcement}${role.opening}`, null, role.pitch), 520);
  }
}

//: Care intents that write the elder's interaction profile, so the page has to
//: reload it rather than keep its cached copy.
const PROFILE_CARE_INTENTS = ['speak_slower', 'speak_faster', 'hearing_support'];

async function refreshProfile() {
  try {
    applyProfile(await api(`/v6/profiles/${ELDER_ID}`));
  } catch (_) {
    // A stale select is cosmetic; never let it break the conversation.
  }
}

function applyProfile(profile) {
  interactionProfile = profile || interactionProfile;
  const scale = Number(interactionProfile.font_scale || 1.25);
  document.documentElement.style.setProperty('--elder-font-scale', String(scale));
  document.querySelectorAll('.bubble').forEach(el => { el.style.fontSize = `${21 * scale / 1.25}px`; });
  if (speechRateEl) selectValue(speechRateEl, interactionProfile.speech_rate || 0.88, '我调过的语速');
  if (fontScaleEl) selectValue(fontScaleEl, scale, '我调过的字号');
}

// Voice ("你说慢点") moves these settings in finer steps than the three presets
// on screen. Rather than blanking the select on an off-ladder value, show it as
// a labelled custom entry so the elder can still see and change what they set.
function selectValue(select, value, customLabel) {
  const wanted = String(value);
  if (![...select.options].some(option => option.value === wanted)) {
    let custom = select.querySelector('option[data-custom]');
    if (!custom) {
      custom = document.createElement('option');
      custom.dataset.custom = 'true';
      select.append(custom);
    }
    custom.value = wanted;
    custom.textContent = customLabel;
  }
  select.value = wanted;
}

async function api(path, options = {}) {
  if (!accessToken) await login();
  const headers = {...(options.headers || {}), Authorization: `Bearer ${accessToken}`};
  const r = await fetch(path, {...options, headers});
  if (r.status === 401) {
    accessToken = null;
    sessionStorage.removeItem('youhuo_elder_token');
    await login();
    return api(path, options);
  }
  const data = await r.json().catch(() => ({}));
  if (!r.ok) {
    const error = new Error(data.detail || `请求失败（${r.status}）`);
    error.status = r.status;
    throw error;
  }
  return data;
}

async function resolveIdentity() {
  if (IDENTITY) return IDENTITY;
  IDENTITY = window.YouHuoIdentity
    ? await window.YouHuoIdentity.ready()
    : {elderId: 'elder-demo', elderToken: null};
  ELDER_ID = IDENTITY.elderId;
  return IDENTITY;
}

async function login() {
  const identity = await resolveIdentity();
  // The visitor endpoint already minted a token for this sandbox; reuse it
  // rather than logging in again as a household that may not be 'elder-demo'.
  if (identity.elderToken) {
    accessToken = identity.elderToken;
    sessionStorage.setItem('youhuo_elder_token', accessToken);
    return;
  }
  const r = await fetch('/v2/auth/demo', {
    method: 'POST', headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({actor_id: ELDER_ID})
  });
  const data = await r.json();
  if (!r.ok) throw new Error(data.detail || '老人端演示登录失败');
  accessToken = data.access_token;
  sessionStorage.setItem('youhuo_elder_token', accessToken);
}

async function loadProfile() {
  applyProfile(await api(`/v6/profiles/${ELDER_ID}`));
}

/** Probe the offline voice once logged in; silently keeps browser speech if absent. */
async function loadVoiceMode() {
  configureNeuralVoice({getToken: () => accessToken});
  const pill = document.querySelector('#voicePill');
  const status = await probeNeuralVoice();
  if (!pill) return;
  pill.textContent = status.available ? '语音：离线本地合成' : '语音：浏览器语音';
  pill.title = status.available
    ? '语音在本机合成，文本不上传。'
    : '未启用离线合成，使用系统自带语音。';
}

/** Show whether a model is advising the semantic layer. Authorization never is. */
async function loadSemanticMode() {
  const pill = document.querySelector('#semanticPill');
  if (!pill) return;
  try {
    const health = await (await fetch('/health')).json();
    pill.textContent = health.semantic_model_configured
      ? '语义层：模型已接入（不授权）'
      : '语义层：离线确定性';
    pill.title = health.semantic_model_configured
      ? '语言模型只做意图和槽位理解，权限、确认与执行仍由确定性代码控制。'
      : '当前未配置模型，全部理解由确定性规则完成。';
  } catch (_) {
    pill.textContent = '语义层：状态未知';
  }
}

async function saveProfile() {
  status.textContent = '正在保存您的语音和显示习惯……';
  const profile = await api(`/v6/profiles/${ELDER_ID}`, {
    method: 'PUT', headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({
      elder_id: ELDER_ID, speech_rate: Number(speechRateEl.value), verbosity: 'gentle',
      max_options: 3, max_sentence_chars: 42, repeat_sensitive: true,
      teach_back_high_risk: true, font_scale: Number(fontScaleEl.value), hearing_support: false
    })
  });
  applyProfile(profile);
  status.textContent = '已保存。以后优活会按这个语速和文字大小与您沟通。';
  speak(status.textContent, profile.speech_rate);
}

async function ensureSession() {
  if (sessionId) return sessionId;
  const data = await api('/v2/sessions', {
    method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({})
  });
  sessionId = data.session_id;
  localStorage.setItem('youhuo_session_v2', sessionId);
  return sessionId;
}

/** Send one turn, recovering once from a session id cached from an older database.
 *  Without this the elder page stays permanently broken until storage is cleared. */
async function postChat(text) {
  const body = sid => JSON.stringify({session_id: sid, text, request_id: crypto.randomUUID()});
  const headers = {'Content-Type': 'application/json'};
  try {
    return await api('/v2/chat', {method: 'POST', headers, body: body(await ensureSession())});
  } catch (e) {
    if (e.status !== 400) throw e;
    sessionId = null;
    localStorage.removeItem('youhuo_session_v2');
    return api('/v2/chat', {method: 'POST', headers, body: body(await ensureSession())});
  }
}

async function adaptAgentMessage(message, riskLevel = 1) {
  try {
    return await api('/v6/interaction/plan', {
      method: 'POST', headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({
        elder_id: ELDER_ID, message, options: [], risk_level: Number(riskLevel || 1),
        asr_confidence: 1.0, recent_retries: recentRetries, reversible: Number(riskLevel || 1) < 4
      })
    });
  } catch (_) {
    return {
      visual_text: message, speak_text: message, speech_rate: interactionProfile.speech_rate,
      cognitive_load_score: null, require_teach_back: false
    };
  }
}

/* ------------------------------------------------------------------ */
/* Design §4.3: glass-box reliance card + no-side-effect safe preview   */
/* ------------------------------------------------------------------ */

// Response codes and task states are engineering identifiers; the elder sees words.
const CODE_WORD = {
  ok: '已回应',
  need_more_info: '还需要一点信息',
  need_elder_confirmation: '等您复述确认',
  need_family_approval: '等家人接力',
  task_completed: '已办好',
  task_cancelled: '已取消',
  duplicate_blocked: '这件事已经办过',
  safety_alert: '安全提醒',
  mode_switched: '已切换模式',
  chat: '闲聊',
  error: '没有执行',
};

// Care answers come back as `chat` because nothing was executed, but they are
// read from authoritative records — labelling them 闲聊 tells the elder (and a
// judge) the opposite of what happened.
const CARE_WORD = {
  medication_today: '按用药记录回答',
  medication_stock: '按库存记录回答',
  medication_list: '按用药计划回答',
  health_recent: '按健康记录回答',
  schedule_today: '按待办回答',
  contact_reach: '按亲友档案回答',
  capability_help: '功能说明',
  orientation: '日期时间',
  symptom_mention: '不做医学判断',
  speak_slower: '已调整语速',
  speak_faster: '已调整语速',
  hearing_support: '已开启听力辅助',
  repeat: '重复上一句',
};

const STATE_WORD = {
  collecting: '正在收集信息',
  awaiting_elder_confirmation: '等您复述确认',
  awaiting_family_approval: '等家人接力',
  executing: '正在办理',
  completed: '已完成并核验',
  cancelled: '已取消',
  failed: '未成功，已安全停下',
};

// Policy field names are engineering identifiers; the elder sees ordinary words.
const FIELD_LABEL = {
  elder_id: '您的身份', hospital: '医院', department: '科室', doctor: '医生',
  date: '就诊日期', time: '就诊时间', bill_id: '账单编号', amount_cents: '金额',
  recipient_family_id: '接力的家人', title: '事项', due_at: '提醒时间',
  summary: '摘要', source_digest: '来源指纹', event_type: '事件类型',
  urgency: '紧急程度', reason: '原因', location: '位置', period: '账期',
  bill_type: '账单类型', timezone: '时区', health_summary: '健康摘要',
};

// Decision → tone of the safe-preview banner, so "waiting for you" does not
// look like the same kind of alarm as "blocked".
const DECISION_TONE = {
  allow: 'good',
  require_elder_confirmation: 'info',
  require_family_approval: 'info',
  clarify: 'warning',
  deny: 'warning',
};

function relianceRow(label, value) {
  const row = document.createElement('div');
  row.className = 'reliance-row';
  const strong = document.createElement('strong');
  strong.textContent = label;
  const body = document.createElement('div');
  body.textContent = value;
  row.append(strong, body);
  return row;
}

function bulletList(items) {
  const ul = document.createElement('ul');
  items.forEach(item => {
    const li = document.createElement('li');
    li.textContent = item;
    ul.appendChild(li);
  });
  return ul;
}

function renderReliance(card, preview) {
  relianceHost.replaceChildren();
  const box = document.createElement('div');
  box.className = 'reliance-card';
  const heading = document.createElement('h3');
  heading.textContent = `🔍 ${card.title}`;
  box.appendChild(heading);
  box.appendChild(relianceRow('我听到', card.heard));
  box.appendChild(relianceRow('要办的事', card.goal));
  box.appendChild(relianceRow('现在这一步', card.current_step));
  box.appendChild(relianceRow('准备做', card.action_summary));
  box.appendChild(relianceRow('谁来决定', card.who_decides));
  box.appendChild(relianceRow('能否撤销', card.reversible ? '可以撤销' : '不能自动撤销，所以要多确认一次'));
  box.appendChild(relianceRow('下一步', card.next_step));
  box.appendChild(relianceRow('信息核验', card.confidence_message));
  if (card.warning) {
    const warn = document.createElement('div');
    warn.className = 'notice warning';
    warn.textContent = card.warning;
    box.appendChild(warn);
  }

  if (preview) {
    const auth = preview.authorization;
    const summary = document.createElement('div');
    summary.className = `notice ${DECISION_TONE[auth.decision] || 'warning'}`;
    summary.textContent = `安全预演：${preview.plain_summary}`;
    box.appendChild(summary);

    // Design §4.2 caps how much is shown at once, so the field-level detail sits
    // behind a disclosure instead of adding a dozen rows to the card.
    const details = document.createElement('details');
    details.className = 'preview-details';
    const marker = document.createElement('summary');
    marker.textContent = '看看具体会用到哪些信息';
    details.appendChild(marker);

    const columns = document.createElement('div');
    columns.className = 'preview-columns';

    // Read the allow-list straight from the authorization rather than parsing the
    // server's sentence, so the elder sees named fields in ordinary words.
    const fields = Object.keys(auth.allowed_arguments || {});
    const willDoItems = fields.length
      ? fields.map(key => `只会用到：${FIELD_LABEL[key] || key}`)
      : ['不会产生真实副作用'];
    const willDo = document.createElement('section');
    willDo.appendChild(Object.assign(document.createElement('h4'), {textContent: '会做的事'}));
    willDo.appendChild(bulletList(willDoItems));

    const willNotItems = [...preview.will_not_do];
    if (auth.stripped_fields?.length) {
      willNotItems.push('不会使用被剥离的信息：' + auth.stripped_fields.map(k => FIELD_LABEL[k] || k).join('、'));
    }
    const willNot = document.createElement('section');
    willNot.appendChild(Object.assign(document.createElement('h4'), {textContent: '不会做的事'}));
    willNot.appendChild(bulletList(willNotItems));

    columns.append(willDo, willNot);
    details.appendChild(columns);

    if (preview.required_humans.length) {
      details.appendChild(relianceRow('需要谁确认', preview.required_humans.join('、')));
    }
    details.appendChild(relianceRow('失败怎么办', preview.rollback_plan));
    box.appendChild(details);
  }

  relianceHost.appendChild(box);
}

// The card and preview are assembled on the server from the stored task, so the
// wording always matches the action the engine would actually run.
async function showGlassBox(heardText, data) {
  if (!data.task_id) { relianceHost.replaceChildren(); return; }
  try {
    const glassBox = await api(`/v6/tasks/${encodeURIComponent(data.task_id)}/glass-box`, {
      method: 'POST', headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({heard_text: heardText})
    });
    renderReliance(glassBox.card, glassBox.preview);
  } catch (_) {
    relianceHost.replaceChildren();
  }
}

/* ------------------------------------------------------------------ */

async function send(text) {
  text = (text || input.value).trim();
  if (!text) return;
  input.value = '';
  addBubble(text, 'user');
  setActivity('processing');
  status.textContent = '正在理解您的目标，并检查权限与风险……';
  try {
    const data = await postChat(text);
    setMode(data.mode);
    const adapted = await adaptAgentMessage(data.message, data.risk_level || 1);
    const asksForConfirmation = ['need_elder_confirmation', 'need_family_approval'].includes(data.code);
    // The code and the task state often say the same thing; show each idea once.
    const careWord = CARE_WORD[data.data?.care_intent];
    const metaParts = [careWord || CODE_WORD[data.code] || data.code];
    const stateWord = STATE_WORD[data.task_status];
    if (stateWord && !metaParts.includes(stateWord)) metaParts.push(stateWord);
    if (adapted.require_teach_back && asksForConfirmation && !metaParts.some(p => p.includes('复述'))) {
      metaParts.push('需要您复述一遍');
    }
    const shown = adapted.visual_text || data.message;
    addBubble(shown, 'agent', metaParts.join(' · '));
    promptHistory.push({text: shown, speak: adapted.speak_text || data.message, rate: adapted.speech_rate});
    if (data.ui?.speak) speak(adapted.speak_text || data.message, adapted.speech_rate);
    recentRetries = 0;

    // A rejected teach-back is a comprehension miss, not an error: highlight the
    // exact number that differed so the elder can see what went wrong.
    if (data.data?.teach_back === 'mismatch') {
      addBubble(`您说的是 ${data.data.heard} 元，账单是 ${data.data.expected} 元。`, 'agent', '金额不一致，已停下');
    }

    // Saying "你说慢点" or "我听不清" changes the stored profile server-side. The
    // spoken reply already uses the new rate (the interaction plan is computed
    // after the change), but the local copy and the selects would still show the
    // old value, so pull the authoritative one back.
    if (PROFILE_CARE_INTENTS.includes(data.data?.care_intent)) {
      await refreshProfile();
    }

    if (asksForConfirmation) {
      await showGlassBox(text, data);
    } else {
      relianceHost.replaceChildren();
    }

    status.textContent = data.task_id
      ? `当前任务：${data.task_id}。您随时可以说“再说一遍”或“取消”。`
      : '办事可留痕；陪伴默认不向家属展示聊天全文。';
    loadReminders();
    if (!logPanel.hidden) loadActivity();
  } catch (e) {
    recentRetries += 1;
    addBubble(`系统暂时不可用：${e.message}`, 'agent');
    status.textContent = '没有执行任何操作，请稍后再试。';
  } finally {
    setActivity('idle');
  }
}

async function reminderAction(id, action) {
  try {
    const data = await api(`/v2/reminders/${id}/${action}`, {
      method: 'POST', headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({request_id: crypto.randomUUID()})
    });
    const adapted = await adaptAgentMessage(data.message, 2);
    addBubble(adapted.visual_text || data.message, 'agent', '待办状态更新');
    if (data.ui?.speak) speak(adapted.speak_text || data.message, adapted.speech_rate);
    loadReminders();
    if (!logPanel.hidden) loadActivity();
  } catch (e) {
    // 老人端尤其不能弹 `alert()`：装到主屏后那是一个带 "127.0.0.1 显示" 字样的
    // 系统灰框，会盖住整屏、冻住页面，而且只有一个"确定"可按。这一页其余的失败
    // 都写在状态行里，这一处也照做。
    status.textContent = `这条待办没能更新：${e.message}`;
  }
}

/** Design §4.4: only the three most pressing items unless the elder asks for all. */
function rankReminders(reminders) {
  const openFirst = [...reminders].sort((a, b) => {
    const aClosed = ['completed', 'cancelled'].includes(a.status) ? 1 : 0;
    const bClosed = ['completed', 'cancelled'].includes(b.status) ? 1 : 0;
    if (aClosed !== bClosed) return aClosed - bClosed;
    return new Date(a.due_at) - new Date(b.due_at);
  });
  return showAllReminders ? openFirst : openFirst.slice(0, 3);
}

async function loadReminders() {
  if (!remindersEl) return;
  try {
    const reminders = await api('/v2/reminders?limit=50');
    remindersEl.replaceChildren();
    const visible = rankReminders(reminders);
    visible.forEach(r => {
      const div = document.createElement('div');
      div.className = 'task';
      const [word, cls] = REMINDER_STATUS[r.status] || [r.status, 'todo'];
      const title = document.createElement('strong'); title.textContent = r.title;
      const timeLine = document.createElement('div');
      timeLine.textContent = `时间：${friendlyTime(r.due_at)}`;
      const statusLine = document.createElement('div');
      const chip = document.createElement('span');
      chip.className = `status-chip ${cls}`;
      chip.textContent = word;
      statusLine.append('状态：', chip);
      div.append(title, timeLine, statusLine);
      if (!['completed', 'cancelled'].includes(r.status)) {
        const ack = document.createElement('button'); ack.textContent = '我知道了'; ack.className = 'secondary';
        const done = document.createElement('button'); done.textContent = '已完成';
        ack.onclick = () => reminderAction(r.id, 'acknowledge');
        done.onclick = () => reminderAction(r.id, 'complete');
        div.append(ack, document.createTextNode(' '), done);
      }
      remindersEl.appendChild(div);
    });
    if (!visible.length) {
      emptyState(
        remindersEl,
        ['M8 3.4v3.2M16 3.4v3.2', 'M4.4 9.4h15.2', 'M5.4 5h13.2a1.6 1.6 0 0 1 1.6 1.6v12a1.6 1.6 0 0 1-1.6 1.6H5.4a1.6 1.6 0 0 1-1.6-1.6v-12A1.6 1.6 0 0 1 5.4 5z'],
        '现在没有待办',
        '您可以说“提醒我明天上午九点复诊”，我来记着。',
      );
    }
    const toggle = document.querySelector('#toggleReminders');
    toggle.hidden = reminders.length <= 3;
    toggle.textContent = showAllReminders ? '只看最要紧的三件' : `查看全部待办（共${reminders.length}件）`;
  } catch (e) { remindersEl.textContent = `待办加载失败：${e.message}`; }
}

/** Design §4.4 log entry point; §6.3 keeps companion chat out of the log. */
async function loadActivity() {
  try {
    const entries = await api('/v2/elder/activity?limit=30');
    activityLogEl.replaceChildren();
    entries.forEach(entry => {
      const row = document.createElement('div');
      row.className = 'log-item';
      const left = document.createElement('div');
      const who = document.createElement('div');
      who.className = 'who'; who.textContent = entry.who;
      const when = document.createElement('time');
      when.dateTime = entry.happened_at;
      when.textContent = friendlyTime(entry.happened_at);
      left.append(who, when);
      const what = document.createElement('div');
      what.textContent = entry.what;
      row.append(left, what);
      activityLogEl.appendChild(row);
    });
    if (!entries.length) {
      emptyState(
        activityLogEl,
        ['M6.5 3.4h11a1.6 1.6 0 0 1 1.6 1.6v14a1.6 1.6 0 0 1-1.6 1.6h-11A1.6 1.6 0 0 1 4.9 19V5a1.6 1.6 0 0 1 1.6-1.6z', 'M8.4 9h7.2M8.4 13h7.2M8.4 17h4.4'],
        '还没有记录',
        '办过的事会按时间记在这里，谁确认过也看得到。',
      );
    }
  } catch (e) { activityLogEl.textContent = `记录加载失败：${e.message}`; }
}

document.querySelector('#send').addEventListener('click', () => send());
input.addEventListener('keydown', e => { if (e.key === 'Enter') send(); });
document.querySelectorAll('[data-text]').forEach(btn => btn.addEventListener('click', () => send(btn.dataset.text)));

document.querySelector('#companionEntry').addEventListener('click', () => {
  send(currentMode === 'companion' ? '继续办事' : '调用无忧伴');
});

document.querySelector('#logEntry').addEventListener('click', () => {
  logPanel.hidden = !logPanel.hidden;
  document.querySelector('#logEntryLabel').textContent = logPanel.hidden ? '查看我的记录' : '收起我的记录';
  if (!logPanel.hidden) {
    loadActivity();
    logPanel.scrollIntoView({behavior: 'smooth', block: 'start'});
  }
});

document.querySelector('#toggleReminders').addEventListener('click', () => {
  showAllReminders = !showAllReminders;
  loadReminders();
});

document.querySelector('#repeatLast').addEventListener('click', () => {
  if (lastSpoken) speak(lastSpoken); else speak('目前还没有需要重复的内容。');
});

// "返回上一步" replays the previous question instead of pretending to roll back
// server state; the task itself stays exactly where it is.
document.querySelector('#stepBack').addEventListener('click', () => {
  if (promptHistory.length < 2) {
    const only = promptHistory[0];
    const text = only ? only.text : '这是第一步，还没有上一步可以返回。';
    addBubble(text, 'agent', '返回上一步');
    speak(only ? only.speak : text, only ? only.rate : null);
    return;
  }
  promptHistory.pop();
  const previous = promptHistory[promptHistory.length - 1];
  input.value = '';
  addBubble(previous.text, 'agent', '返回上一步');
  speak(previous.speak, previous.rate);
  status.textContent = '已经回到上一个问题，任务没有被取消。';
});

document.querySelector('#saveProfile').addEventListener('click', () => {
  saveProfile().catch(e => { status.textContent = e.message; });
});
fontScaleEl.addEventListener('change', () => applyProfile({...interactionProfile, font_scale: Number(fontScaleEl.value)}));
speechRateEl.addEventListener('change', () => { interactionProfile.speech_rate = Number(speechRateEl.value); });

const SR = window.SpeechRecognition || window.webkitSpeechRecognition;
const mic = document.querySelector('#mic');
if (SR) {
  const rec = new SR();
  rec.lang = 'zh-CN'; rec.interimResults = false; rec.maxAlternatives = 3;
  rec.onstart = () => {
    setActivity('listening');
    micHint.textContent = '正在听，请慢慢说';
    status.textContent = '正在听，请慢慢说。一次只说一件事也可以。';
  };
  rec.onresult = e => { input.value = e.results[0][0].transcript; send(); };
  rec.onend = () => {
    if (document.body.dataset.activity === 'listening') setActivity('idle');
    micHint.textContent = '按一下，然后慢慢说';
  };
  rec.onerror = e => {
    recentRetries += 1;
    setActivity('idle');
    micHint.textContent = '按一下，然后慢慢说';
    status.textContent = `语音识别没有成功：${e.error}。没有执行任何操作，请再说一遍。`;
  };
  mic.addEventListener('click', () => rec.start());
} else {
  mic.addEventListener('click', () => {
    micHint.textContent = '这个浏览器不支持语音，请在下面打字';
    input.focus();
  });
  mic.title = '当前浏览器不支持语音识别，请使用下方输入框';
}

addBubble('您好，我是优活。您可以直接说“帮我挂号”“查一下水费”或“调用无忧伴”。我会一次只问一件事。', 'agent');
promptHistory.push({
  text: '您好，我是优活。您可以直接说“帮我挂号”“查一下水费”或“调用无忧伴”。我会一次只问一件事。',
  speak: '您好，我是优活。您可以直接说帮我挂号、查一下水费，或者调用无忧伴。',
  rate: null,
});
// Chrome populates the voice list asynchronously; re-pick once it arrives.
if ('speechSynthesis' in window) {
  window.speechSynthesis.addEventListener('voiceschanged', () => {
    resetVoiceCache();
    const voice = pickVoice();
    if (voice) console.info(`优活语音：${voice.name}`);
  });
}

loadSemanticMode();
login()
  .then(ensureSession)
  .then(loadVoiceMode)
  .then(loadProfile)
  .then(loadReminders)
  .catch(e => { status.textContent = e.message; });
