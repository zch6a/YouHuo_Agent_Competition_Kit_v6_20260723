import {
  configureNeuralVoice, pickVoice, probeNeuralVoice, resetVoiceCache, speakClauses,
} from '/static/speech.js';
import {renderGlassBox} from '/static/glassbox.js';

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

// 存储访问必须包起来——这一行在**模块顶层**，抛了它下面的一切都不执行。
//
// Chrome 勾选"阻止所有网站数据"、无 allow-same-origin 的 sandbox iframe，
// `window.localStorage` 一访问就抛 SecurityError。此前的后果是老人打开这一页看到
// 一张纯静态 HTML：没有开场气泡、麦克风与发送和待办一个监听器都没绑、也没有任何
// 错误提示。全项目只有这个文件没有做这层保护（landing / common / identity 都有）。
function readStore(key) {
  try { return localStorage.getItem(key); } catch (_) { return null; }
}
function writeStore(key, value) {
  try { localStorage.setItem(key, value); } catch (_) { /* 隐私模式：会话不跨刷新存活 */ }
}

let sessionId = readStore('youhuo_session_v2');
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
// 在这里取，不在下面语音那一段取：`setActivity()` 要写它的 aria-label，而那一段在
// 七百行之后——`const` 的暂时性死区会让任何早一步的调用直接把这一页打哑。
const mic = document.querySelector('#mic');
const speechRateEl = document.querySelector('#speechRate');
const fontScaleEl = document.querySelector('#fontScale');

/** Voice Orb 的状态表。**唯一**的定义处。
 *
 * 此前 `setActivity` 只是一行 `dataset.activity = state`，状态名以字符串字面量散在
 * 七个调用点，CSS 只认其中两个。后果不是代码不整齐，是**老人分不清三种完全不同的
 * 处境**：`error` 被折叠进 `idle`（失败了看起来像可以再按），而 agent 正在说话时
 * 没有任何状态（她看到的是 idle，于是按下去打断自己）。
 *
 * 每一态三样东西缺一不可：
 *   - `hint`  麦克风下那行字。这是这个控件的名字，不是装饰。
 *   - `label` 麦克风按钮的 aria-label。读屏用户看不到环，环的全部信息得从这里出。
 *   - CSS 里一条 `body[data-activity="…"]` 规则，且**不能只靠颜色**（见 components.css）。
 *
 * 加了一个任务书没点名的 `speaking`——任务书自己的问题陈述里写着"speaking 不存在"，
 * 那它就是缺陷之一。所以是十一态，不是十态。
 */
const ACTIVITY = {
  idle:       {hint: '按一下，然后慢慢说',        label: '按一下开始说话'},
  pressed:    {hint: '松开手，我就开始听',        label: '正在按下'},
  listening:  {hint: '我在听，您慢慢说',          label: '正在听您说，按一下可以停下'},
  processing: {hint: '让我想一想',                label: '正在理解您说的话，请稍等'},
  clarifying: {hint: '有一处我要问清楚',          label: '我有一处要问清楚，请看上面'},
  confirming: {hint: '请您念一遍再确认',          label: '正在等您确认，请看上面的卡片'},
  executing:  {hint: '正在替您办',                label: '正在替您办，请稍等'},
  speaking:   {hint: '我在说，按一下可以打断我',  label: '我正在说话，按一下打断'},
  success:    {hint: '办好了',                    label: '刚才那件事办好了，按一下可以说下一件'},
  error:      {hint: '没能办成，可以再说一次',    label: '刚才那件事没能办成，按一下再说一次'},
  offline:    {hint: '现在连不上网',              label: '现在连不上网，暂时不能办事'},
};

// 挂给闸门读。`check_page_runtime.py` 的 `check_voice_orb_states` 会逐个把状态写进
// `data-activity`，在关掉动效之后量每一态的静止形态并两两比对。它必须读**这一份**
// 清单——在脚本里另写一份，两份就会各自漂移，而漂移的那天检查照样绿。
window.__voiceOrbStates = ACTIVITY;

/** 切换 Voice Orb 的状态。
 *
 * 只写 `#micHint` 和麦克风的 aria-label，**不碰 `#status`**——状态行上多数时候有一句
 * 比"让我想一想"具体得多的话（哪个任务、差多少钱、为什么停下）。一个自动播报的
 * 状态机去覆盖它，就是用泛化的话盖掉唯一有信息量的那句。
 *
 * `hint` 可以按需覆写：状态相同、处境不同的时候（比如正在听时又按了一下麦克风）。
 */
function setActivity(state, hint = null) {
  const spec = ACTIVITY[state];
  if (!spec) return;                    // 打错状态名不该把这一页弄哑。
  document.body.dataset.activity = state;
  setMicHint(hint || spec.hint);
  if (mic) mic.setAttribute('aria-label', spec.label);
}

/** 状态行。这一页对老人说的每一句"现在怎么了"都从这里出去。
 *
 * 原先 12 处直接写 `status.textContent`，麦克风提示又另有 4 处写 `#micHint`。两处
 * 后果：一是同一时刻两条提示可能互相矛盾（状态行说"正在听"，micHint 还停在上一次的
 * 错误），二是想给状态加一条无障碍播报或一个自动清除，得改十六个地方。
 *
 * `#status` 已经带 aria-live，收敛到一个入口之后，读屏用户听到的顺序才是确定的。
 */
function setStatus(text) {
  status.textContent = text;
}

/** 麦克风下方那行提示。与状态行分开是有意的：它只描述录音本身。 */
function setMicHint(text) {
  if (micHint) micHint.textContent = text;
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

/** 这一轮说完话之后该停在哪一态。
 *
 * `send()` 的 finally 比朗读早得多——它发起 `speak()` 就走了。如果 finally 直接写
 * `success`，那么整段朗读期间屏幕上写的是"办好了"，而老人这时候按麦克风会打断
 * agent 自己的话。所以结论先寄存在这里，等 `onDone` 再落。 */
let pendingSettle = null;
let speakWatchdog = null;

function speak(text, rate = null, pitch = null) {
  lastSpoken = text;
  if (stopSpeaking) stopSpeaking();
  setActivity('speaking');

  const finished = () => {
    window.clearTimeout(speakWatchdog);
    // 只有还停在 speaking 才动。中途她按了麦克风（listening）、或下一轮已经开始想了
    // （processing），那些都比"我说完了"更新，不该被回退覆盖。
    if (document.body.dataset.activity !== 'speaking') return;
    const next = pendingSettle || 'idle';
    pendingSettle = null;
    setActivity(next);
  };

  // 看门狗。Chrome 的 speechSynthesis 会在长文本上静默停住而**不触发 onend**（长期
  // 存在的已知问题），神经语音那条也可能卡在一次永不 resolve 的 play() 上。真发生
  // 时屏幕会一直写着"我在说，按一下可以打断我"——而这一整轮改动的全部意义，就是让
  // 屏幕不要对老人说假话。
  //
  // 中文语音在 rate≈0.88 下大约每秒四个字，给两倍余量再加 6 秒，上限 90 秒。
  const budget = Math.min(90_000, 6_000 + text.length * 500);
  window.clearTimeout(speakWatchdog);
  speakWatchdog = window.setTimeout(finished, budget);

  // Clause-by-clause with spoken-Chinese dates and amounts; see speech.js.
  stopSpeaking = speakClauses(text, {
    rate: Number(rate || interactionProfile.speech_rate || 0.88),
    pitch: Number(pitch || ROLES[currentMode].pitch),
    onDone: finished,
  });
}

/** 一轮结束时落到 `state`——正在说话就先寄存，说完再落。 */
function settleActivity(state) {
  if (document.body.dataset.activity === 'speaking') { pendingSettle = state; return; }
  pendingSettle = null;
  setActivity(state);
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
  // 只设这一个变量。
  //
  // 这里原先还逐个给已有气泡写内联 `style.fontSize = 21 * scale / 1.25`，和 CSS 里
  // 的 `calc(20px * var(--elder-font-scale) / 1.25)` 两套并存——内联优先级更高，
  // 基数还差 1px。结果是：调整字号**之前**就在屏幕上的气泡按 21 算，之后新增的按
  // 20 算，同一屏里两种字号，而且只有老人自己会看出来"字大小不一样"。
  //
  // CSS 变量本来就会让所有气泡（包括后来才添加的）一起跟着变，那套内联从来都是多余
  // 的，只是多余得刚好不一致。
  document.documentElement.style.setProperty('--elder-font-scale', String(scale));
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

// 身份、登录、401 重放和令牌缓存都在 common.js 里。它是经典脚本，在这个模块之前
// 执行，`window.YouHuo` 对模块一样可见。
//
// 这一页原来那份 `api()` 是五份里唯一把 `status` 挂到 Error 上的——`postChat` 靠它
// 区分 400 去重建会话。共用实现保留了这个行为，另外四页现在也一并有了。
function api(path, options = {}) {
  return window.YouHuo.api(path, options, 'elder');
}

async function resolveIdentity() {
  if (IDENTITY) return IDENTITY;
  IDENTITY = await window.YouHuo.ready();
  ELDER_ID = IDENTITY.elderId;
  return IDENTITY;
}

async function login() {
  await resolveIdentity();
  await window.YouHuo.login('elder');
}

async function loadProfile() {
  applyProfile(await api(`/v6/profiles/${ELDER_ID}`));
}

/** Probe the offline voice once logged in; silently keeps browser speech if absent. */
async function loadVoiceMode() {
  // 每次现取，而不是闭包捕获一个当时的值：401 重放换了令牌之后，捕获的那个就是
  // 过期的，而音频流失败只会表现成"这句没读出来"。
  configureNeuralVoice({getToken: () => window.YouHuo.token('elder')});
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
  setStatus('正在保存您的语音和显示习惯……');
  const profile = await api(`/v6/profiles/${ELDER_ID}`, {
    method: 'PUT', headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({
      elder_id: ELDER_ID, speech_rate: Number(speechRateEl.value), verbosity: 'gentle',
      max_options: 3, max_sentence_chars: 42, repeat_sensitive: true,
      teach_back_high_risk: true, font_scale: Number(fontScaleEl.value), hearing_support: false
    })
  });
  applyProfile(profile);
  setStatus('已保存。以后优活会按这个语速和文字大小与您沟通。');
  speak(status.textContent, profile.speech_rate);
}

// 建会话要记忆化，否则首次使用时的两次点击会建出两个会话。
//
// 原先是"跨 await 检查再赋值一个普通变量"：全新浏览器里快速点「挂号」再点「交水费」，
// 两个 postChat 都在 sessionId 还是 null 时进来，各发一个 POST /v2/sessions，后写的
// localStorage 胜出。第一轮落在会话 A，之后所有轮次落在会话 B——在 A 里开始的多轮
// 挂号流程再也接不上，老人回答追问，服务器那边没有对应的任务。
let sessionPending = null;

async function ensureSession() {
  if (sessionId) return sessionId;
  if (sessionPending) return sessionPending;
  sessionPending = (async () => {
    const data = await api('/v2/sessions', {
      method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({})
    });
    sessionId = data.session_id;
    writeStore('youhuo_session_v2', sessionId);
    return sessionId;
  })();
  try {
    return await sessionPending;
  } finally {
    sessionPending = null;
  }
}

/** Send one turn, recovering once from a session id cached from an older database.
 *  Without this the elder page stays permanently broken until storage is cleared. */
async function postChat(text) {
  const body = sid => JSON.stringify({session_id: sid, text, request_id: crypto.randomUUID()});
  const headers = {'Content-Type': 'application/json'};
  try {
    return await api('/v2/chat', {method: 'POST', headers, body: body(await ensureSession())});
  } catch (e) {
    // 403 和 400 都要重建会话。
    //
    // 403 是 `AuthorizationError`：这个 session_id 存在，但**不属于当前家庭**。
    // 换身份之后就是这个形态——R12 修了身份那一半（换库之后重新开通 + 整页重载），
    // 却漏了会话这一半：`youhuo_session_v2` 还留在 localStorage 里指着旧家庭，
    // 于是老人每说一句话都是 403，而这条路径只从 400 恢复。表现是"应用打得开、
    // 待办看得见、但一说话就报系统暂时不可用"，刷新多少次都一样。
    if (e.status !== 400 && e.status !== 403) throw e;
    sessionId = null;
    try { localStorage.removeItem('youhuo_session_v2'); } catch (_) { /* 隐私模式 */ }
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


// The card and preview are assembled on the server from the stored task, so the
// wording always matches the action the engine would actually run.
async function showGlassBox(heardText, data) {
  if (!data.task_id) { relianceHost.replaceChildren(); return; }
  try {
    const glassBox = await api(`/v6/tasks/${encodeURIComponent(data.task_id)}/glass-box`, {
      method: 'POST', headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({heard_text: heardText})
    });
    renderGlassBox(relianceHost, glassBox.card, glassBox.preview);
  } catch (_) {
    relianceHost.replaceChildren();
  }
}

/* ------------------------------------------------------------------ */

// 一次只办一件事——这一页把这句话印在界面上，代码也必须做到。
//
// 此前两轮对话可以并发：点「交水费」再点「今天有什么事」，两个 POST /v2/chat 一起飞。
// 如果缴费那轮先回来且需要确认，玻璃盒会把金额确认卡渲染进 #relianceHost；随后第二轮
// 回来走 else 分支执行 `relianceHost.replaceChildren()`——**老人正在被要求确认一笔付款，
// 确认卡凭空消失**，状态行显示的是另一轮的文案。气泡和「返回上一步」的历史也按完成
// 顺序而不是发送顺序排，于是回放的是错的那一句。
//
// 清空输入框那一招只覆盖打字路径，传参进来的（快捷按钮、语音、无忧伴入口）不受它约束。
let turnInFlight = false;

async function send(text) {
  text = (text || input.value).trim();
  if (!text) return;
  if (turnInFlight) {
    setStatus('上一句还在办，我一次只做一件事。稍等一下。');
    return;
  }
  turnInFlight = true;
  input.value = '';
  addBubble(text, 'user');
  setActivity('processing');
  setStatus('正在理解您的目标，并检查权限与风险……');
  let settled = 'idle';
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

    setStatus(data.task_id
      ? `当前任务：${data.task_id}。您随时可以说“再说一遍”或“取消”。`
      : '办事可留痕；陪伴默认不向家属展示聊天全文。');
    loadReminders();
    if (!logPanel.hidden) loadActivity();
    settled = activityFor(data);
  } catch (e) {
    recentRetries += 1;
    addBubble(`系统暂时不可用：${e.message}`, 'agent');
    setStatus('没有执行任何操作，请稍后再试。');
    settled = navigator.onLine === false ? 'offline' : 'error';
  } finally {
    turnInFlight = false;
    // 这一轮**结束在哪种处境**，屏幕上就停在哪一态。原先无论办成、办砸、还是正在
    // 等家人接力，都一律回 idle——十分之九的信息在这一行里丢掉了。
    settleActivity(settled);
  }
}

/** 一轮回复落在哪一态。
 *
 * 后端的 `code` 与 `task_status` 说的是同一件事的两个侧面，`task_status` 更靠后、
 * 更权威（它是任务真实走到的位置），所以先看它。
 */
function activityFor(data) {
  const byState = {
    collecting: 'clarifying',
    awaiting_elder_confirmation: 'confirming',
    awaiting_family_approval: 'confirming',
    executing: 'executing',
    completed: 'success',
    cancelled: 'idle',
    failed: 'error',
  }[data.task_status];
  if (byState) return byState;
  return {
    need_more_info: 'clarifying',
    need_elder_confirmation: 'confirming',
    need_family_approval: 'confirming',
    task_completed: 'success',
    task_cancelled: 'idle',
    duplicate_blocked: 'error',
    safety_alert: 'clarifying',
    error: 'error',
  }[data.code] || 'idle';
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
    setStatus(`这条待办没能更新：${e.message}`);
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

/** 首屏那一行「今天」。
 *
 * 这一屏此前不告诉老人今天有什么事——那句话藏在底部抽屉里，要点开才看得到。而
 * "今天有几件事、下一件是什么"恰恰是她打开这个应用最先想知道的东西，所以它排在
 * 麦克风之前。
 *
 * 只说未完成的。已完成的待办出现在"今天还有 3 件事"里，会让人白紧张一次。
 *
 * 而"今天"必须真的是今天。这一行原先拿的是**全部**未完成待办的条数——三条待办
 * （今天 16:00 复诊、8 月 19 日体检、9 月 4 日缴水费）会渲染成"今天有 3 件事"，
 * 实际今天只有一件。把今天那条办掉之后更荒唐：变成"今天有 2 件事 · 下一件 8月19日
 * 09:00 体检"——标题说今天，紧接着自己报了一个九天后的日期。
 * `/v2/reminders` 没有按日筛选的参数，所以在这里按本地日期筛。
 */
function isToday(iso) {
  const at = new Date(iso);
  const now = new Date();
  return at.getFullYear() === now.getFullYear()
    && at.getMonth() === now.getMonth()
    && at.getDate() === now.getDate();
}

function renderTodayLine(reminders) {
  const line = document.getElementById('todayLine');
  if (!line) return;
  const open = reminders
    .filter(r => !['completed', 'cancelled'].includes(r.status))
    .sort((a, b) => new Date(a.due_at) - new Date(b.due_at));
  const today = open.filter(r => isToday(r.due_at));
  if (today.length) {
    const next = today[0];
    line.textContent = `今天有 ${today.length} 件事 · 下一件 ${friendlyTime(next.due_at)} ${next.title}`;
    line.hidden = false;
    return;
  }
  // 今天没事，但后面还有。说"今天没有要办的事"就完事，会让她以为什么都不用管了；
  // 所以顺带把下一件是哪天说出来——这一行的职责是"今天怎么样"，不是"永远没事"。
  if (open.length) {
    const next = open[0];
    line.textContent = `今天没有要办的事 · 下一件 ${friendlyTime(next.due_at)} ${next.title}`;
    line.hidden = false;
    return;
  }
  line.textContent = '今天没有要办的事。';
  line.hidden = false;
}

async function loadReminders() {
  if (!remindersEl) return;
  try {
    const reminders = await api('/v2/reminders?limit=50');
    renderTodayLine(reminders);
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
input.addEventListener('keydown', e => {
  // `isComposing` 不是可选的。
  //
  // 中文输入法在合成期间照样派发 keydown（`key === 'Enter'`、`isComposing === true`）。
  // 老人用拼音打 "guahao" 后按 Enter 选字，此前会直接 send()——`input.value` 里是还没
  // 上屏的拼音串，于是「挂号」没打出去，取而代之是一次垃圾对话，而 send() 还会清空
  // 输入框、把输入法的合成状态一起打断。
  // Firefox 上这条是**唯一**的输入通道（没有 SpeechRecognition），所以这不是边角。
  if (e.isComposing || e.keyCode === 229) return;
  if (e.key === 'Enter') send();
});
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
  setStatus('已经回到上一个问题，任务没有被取消。');
});

document.querySelector('#saveProfile').addEventListener('click', () => {
  saveProfile().catch(e => { setStatus(e.message); });
});
fontScaleEl.addEventListener('change', () => applyProfile({...interactionProfile, font_scale: Number(fontScaleEl.value)}));
speechRateEl.addEventListener('change', () => { interactionProfile.speech_rate = Number(speechRateEl.value); });

const SR = window.SpeechRecognition || window.webkitSpeechRecognition;
if (SR) {
  const rec = new SR();
  rec.lang = 'zh-CN'; rec.interimResults = false; rec.maxAlternatives = 3;
  rec.onstart = () => {
    setActivity('listening');
    setStatus('正在听，请慢慢说。一次只说一件事也可以。');
  };
  rec.onresult = e => { input.value = e.results[0][0].transcript; send(); };
  rec.onend = () => {
    // 只有还停在 listening 才回 idle：onresult 已经把状态推到 processing 了，
    // 这里再写一次 idle 会把"让我想一想"抹掉一瞬间。
    if (document.body.dataset.activity === 'listening') setActivity('idle');
  };
  //: Web Speech 的错误枚举是英文标识符，不能直接给老人看，尤其不能配一句
  //: "请再说一遍"——权限被拒时再说一百遍也不会成功，而页面从不告诉她要去哪里开。
  //: 这一页为了不让引擎标识符出现在老人眼前，已经写了四张这样的表。
  const RECOGNITION_TROUBLE = {
    'not-allowed': '我没有拿到麦克风的许可。您可以在下面打字，或者让家人帮您在手机设置里打开麦克风权限。',
    'service-not-allowed': '这台手机暂时不让我用语音。您可以在下面打字。',
    'audio-capture': '我找不到麦克风。您可以在下面打字。',
    'no-speech': '我没有听到声音。请离手机近一点，再按一下慢慢说。',
    'network': '网络不太好，语音没送出去。您可以在下面打字，或者等一会儿再试。',
    'aborted': '刚才那次听被打断了。您可以再按一下。',
  };

  rec.onerror = e => {
    recentRetries += 1;
    // 此前这里写 idle——听失败和"可以开始了"在屏幕上长得一模一样。
    setActivity(e.error === 'network' && !navigator.onLine ? 'offline' : 'error');
    setStatus(RECOGNITION_TROUBLE[e.error]
      || '语音没能用起来。您可以在下面打字，我一样能办。');
    if (e.error === 'not-allowed' || e.error === 'service-not-allowed'
        || e.error === 'audio-capture') input.focus();
  };

  mic.addEventListener('click', () => {
    // 正在听的时候再按一下，按规范 `start()` 会抛 InvalidStateError——而老人重复按
    // 恰恰是最常见的操作。此前这个未捕获异常让屏幕上什么都不变：状态行不动、
    // 呼吸圈不动，她得不到"第二下没用"的任何反馈。
    if (document.body.dataset.activity === 'listening') {
      setActivity('listening', '我正在听，您说吧');
      return;
    }
    setActivity('pressed');
    // 说话和听必须互斥。
    //
    // 此前 agent 还在念的时候按麦克风，`rec.start()` 会成功——识别器于是把手机
    // 扬声器里 agent 自己的 TTS 转写下来，再当成老人这一轮发出去。`speak()` 里没有
    // 任何东西停 `rec`，`rec.onstart` 里也没有调 `stopSpeaking`。
    if (stopSpeaking) stopSpeaking();   // 开屏问候还没说、她就按了，这里会是 null。
    try {
      rec.start();
    } catch (_) {
      // 状态机和引擎不同步（上一次 onend 还没到）。不抛给用户，让她再按一次。
      setActivity('idle', '再按一下试试');
    }
  });
} else {
  mic.addEventListener('click', () => {
    setMicHint('这个浏览器不支持语音，请在下面打字');
    input.focus();
  });
  mic.title = '当前浏览器不支持语音识别，请使用下方输入框';
}

// 断网。这一页做的每一件事都要过后端——缴费、挂号、查用药——所以断网不是"某个请求
// 失败了"，是"现在什么都办不了"。此前它只会表现为一次次点下去、一次次报
// 「系统暂时不可用」，屏幕上没有任何东西说明为什么。
window.addEventListener('offline', () => setActivity('offline'));
window.addEventListener('online', () => {
  if (document.body.dataset.activity === 'offline') setActivity('idle');
});
if (navigator.onLine === false) setActivity('offline');

// manifest 的快捷方式承诺的事，这里要真的做到。
//
// `manifest.webmanifest` 里有一条「找无忧伴聊聊」指向 `/elder?mode=companion`——长按
// 主屏图标就能直接进陪伴模式。而**全站没有任何地方读这个参数**（grep 过
// searchParams / location.search，唯一命中在 landing.js，读的是别的键）：点它落到普通
// 首页，和主图标毫无区别。快捷方式承诺了一个不存在的功能。
//
// `setMode()` 本来就在，只差有人调用它。不播报：用户是主动选的这条路，不需要再被告知
// 一次自己刚做的选择。
{
  const wanted = new URLSearchParams(location.search).get('mode');
  if (wanted && ROLES[wanted]) setMode(wanted, {announce: false});
}

//: 开场那一句气泡按模式走。从「找无忧伴聊聊」进来的人要听到无忧伴说话，而不是优活
//: 报一遍办事菜单——那正是她刚刚选择**不要**的东西。
const GREETING = {
  youhuo: {
    text: '您好，我是优活。您可以直接说“帮我挂号”“查一下水费”或“调用无忧伴”。我会一次只问一件事。',
    speak: '您好，我是优活。您可以直接说帮我挂号、查一下水费，或者调用无忧伴。',
  },
  companion: {
    text: '我在这儿呢。想聊什么都行，不着急，慢慢说。',
    speak: '我在这儿呢。想聊什么都行，不着急，慢慢说。',
  },
};

const greeting = GREETING[currentMode] || GREETING.youhuo;
addBubble(greeting.text, 'agent');
promptHistory.push({text: greeting.text, speak: greeting.speak, rate: null});
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
  .catch(e => { setStatus(e.message); });
