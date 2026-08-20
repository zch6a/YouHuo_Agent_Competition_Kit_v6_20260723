import {
  configureNeuralVoice, pickVoice, probeNeuralVoice, resetVoiceCache, speakClauses,
} from '/static/speech.js';
import {renderGlassBox} from '/static/glassbox.js';
import {renderTaskSpace, taskViewModel} from '/static/task-space.js';
import {renderTaskDetail, taskDetailViewModel} from '/static/task-detail.js';

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
  // `acknowledged` 原先也写「待处理」，和 `scheduled` 一个字不差。
  //
  // 后果不是"用词不够精确"：老人按下「我知道了」之后，后端状态从 scheduled
  // 变成 acknowledged，而这张卡上**没有任何东西变化**——连"她已经看见过这件事"
  // 都读不出来。加上回执也看不见（见 `reminderAction`），整个动作在屏幕上
  // 是完全静默的。
  //
  // 「知道了」而不是「已确认」：她按的按钮就写着「我知道了」，
  // 状态词跟着她按的那个词走，不另起一套说法。
  acknowledged: ['知道了', 'todo'],
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
// 顶栏那条演示壳（返回 + 「优活办事模式」徽章）已经从根页面撤掉，所以这两个可能是
// null。**不要把它们删掉**：宽屏与横屏的布局里还留着承接位，而且模式切换是这个产品
// 的一个核心特性——哪天要把徽章放回某个表面，读它的代码应该还在。
// 现在的做法是"有就写，没有就跳过"，而不是假设它一定在。
const modeBadge = document.querySelector('#modeBadge');
const modeName = document.querySelector('#modeName');
const agentTitle = document.querySelector('#agentTitle');
const roleOpening = document.querySelector('#roleOpening');
const roleHeader = document.querySelector('#roleHeader');
const remindersEl = document.querySelector('#reminders');
const relianceHost = document.querySelector('#relianceHost');
const taskSpaceHost = document.querySelector('#taskSpace');
const activityLogEl = document.querySelector('#activityLog');
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
  // 「松开手，我就开始听」是错的：设置 `pressed` 的只有一处，在 `click` 处理器里
  // （elder.js 里没有 pointerdown / mousedown / touchstart），而 `click` 触发时
  // **手已经松开了**。这行字在告诉她去做一件刚做完的事——对一位正在学怎么用它的
  // 老人，那是"我做错了吗"的来源。
  pressed:    {hint: '按到了，我这就开始听',      label: '已按下，正在开始听'},
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
  // 时长从 CSS 问，不写字面量。
  //
  // 两件事：
  // ① 这里原先是硬编码的 `500`，而 CSS 那边是 `calc(var(--mode-fade) * .5)`。
  //    同一个常量两份，改一边另一边静默漂移。`sheet.js` 的注释**点名了这个坑**
  //    （「这个项目已经因为『两处各写一份常量』吃过亏（elder.js 的 500ms 与
  //    --mode-fade）」），它自己用"问 CSS"躲开了，而被点名的这一处一直没修。
  // ② 更要紧：`prefers-reduced-motion` 下 `pages.css` 把过渡掐到 `.01ms`，
  //    而这个定时器**没有任何门控**——于是标题瞬间消失、**硬空白 500ms**、再瞬间
  //    出现。对开了「减少动态效果」的前庭失调用户，结果比不做动效更糟。
  //    问 CSS 就自动跟着走：过渡被掐到 0，这里也就是 0。
  const fade = Math.round(parseFloat(getComputedStyle(roleHeader).transitionDuration) * 1000) || 0;
  window.setTimeout(() => {
    document.body.dataset.mode = next;
    // 顶栏徽章已从根页面撤掉，所以这两行要能在它不存在时安静地不做事。
    // 模式仍然是看得出来的：角色头换图标、换名字（优活 / 无忧伴）、整套配色跟着切，
    // 而 `speak()` 还会把 `role.announcement` 念出来——徽章原先只是把同一件事
    // 用工程话（「优活办事模式」）再喊一遍。
    if (modeBadge) modeBadge.classList.toggle('orange', next === 'companion');
    if (modeName) modeName.textContent = role.modeName;
    agentTitle.textContent = role.name;
    roleOpening.textContent = role.opening;
    document.querySelector('#companionEntryLabel').textContent =
      next === 'companion' ? '回到优活办事' : '找无忧伴聊聊';
    roleHeader.classList.remove('switching');
  }, fade);
  if (announce) {
    // Spoken cue carries the same information as the colour change.
    window.setTimeout(() => speak(`${role.announcement}${role.opening}`, null, role.pitch), fade + 20);
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
  // 这两个 pill 所在的那一段，标题是「优活怎么保护您」，旁边三个兄弟是
  // 「一次只问一件事」「要紧的事请您念一遍」「不会自动扣钱」——全是**对她的承诺**。
  // 原先这两条写的是「语音：离线本地合成」和「语义层：离线确定性」，是**对我的描述**。
  // HTML 里的占位符（「正在检查念得清不清…」）其实早就是产品话了，是 JS 把它盖掉的：
  // 有人修了模板没修脚本，而屏幕上活着的是脚本那一版。
  //
  // 事实一个字没改，只是换成她这一侧的说法。工程说法在 /judge 与 /trust 有完整版本
  // （那是手机框**外**，读者是评委）——这里是换地方，不是删掉。
  pill.textContent = status.available ? '说话不出这台手机' : '用手机自带的声音念';
  pill.title = status.available
    ? '念给您听的声音在这台手机上生成，您说的话不会传出去。'
    : '用手机自带的声音念给您听。';
}

/** Show whether a model is advising the semantic layer. Authorization never is. */
async function loadSemanticMode() {
  const pill = document.querySelector('#semanticPill');
  if (!pill) return;
  try {
    const health = await (await fetch('/health')).json();
    // 「听得懂话，做不了主」是这件事对她的全部含义：模型只做意图与槽位理解，
    // 而要不要办、办什么、花多少钱，仍然由确定性代码决定。
    pill.textContent = health.semantic_model_configured ? '听得懂话，做不了主' : '不上网也听得懂';
    pill.title = health.semantic_model_configured
      ? '听懂您的话可以借助外部帮助；但要不要办、办成什么样，只由优活固定的规矩决定。'
      : '不联网也能听懂您说的话。';
  } catch (_) {
    pill.textContent = '这项暂时查不到';
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

/* ==========================================================================
   我的数据：心情回顾、今天怎么样、优活记了什么、删掉
   ..........................................................................
   这三块能力后端早就有（`/api/v1/emotions/review`、`/daily-report`、
   `/privacy/data` + `/privacy/erase`），但在这之前**没有任何页面在调**。
   做完了没有入口，等于没做。

   四条共同约定：

   ① **后端的 `message` 原样显示。** 这一层的每个端点都返回一句写好的中文，
      而且语气是它定的——「今天该吃的都记过了」是 409 不是成功。前端再写一遍
      文案就是第二个事实源，两边迟早分叉。

   ② **不碰 `records`。** `/privacy/data` 的 `records` 里是原始记录：
      `label: "calm"`、`source: "companion"`、`valence`、`text_digest`。
      那是导出文件该有的内容，**不是界面该显示的**——界面上不许出现英文枚举值。
      屏幕上只放 `buckets` 那个中文摘要。

   ③ **不用 `innerHTML`。** 严格 CSP 之外，这些字符串里有后端拼进来的数量和
      名称；用 DOM API 建，注入这条路从一开始就不存在。

   ④ **删除两步走，第二个按钮一开始不存在。** 见 `renderErasePreview`。
   ========================================================================== */

/** 把一块结果显示出来。空文本 = 收起来，而不是留一块空白。 */
function showOut(host, text) {
  host.textContent = text || '';
  host.hidden = !text;
}

/** 「名称 数量」一行一条。只接受后端给的中文名。 */
function renderCounts(host, rows, lead) {
  host.replaceChildren();
  if (lead) {
    const p = document.createElement('p');
    p.className = 'meta';
    p.textContent = lead;
    host.appendChild(p);
  }
  const list = document.createElement('ul');
  list.className = 'care-lines';
  // 数量为 0 的不印。「就医单据 0 条」对老人没有信息量，
  // 只是让这张单子长一倍——而她要回答的问题是「优活都记了我什么」。
  rows.filter(r => Number(r.count) > 0).forEach((r) => {
    const li = document.createElement('li');
    li.textContent = `${r.name}　${r.count} 条`;
    list.appendChild(li);
  });
  host.appendChild(list);
  host.hidden = false;
}

async function loadMoodReview() {
  const host = document.querySelector('#moodReviewBody');
  try {
    const data = await api('/api/v1/emotions/review?days=14');
    host.replaceChildren();
    const line = document.createElement('p');
    line.textContent = data.message || '';
    host.appendChild(line);
    // 建议是后端按真实记录给的，不是这里编的。没有就不印这一段。
    (data.suggestions || []).forEach((s) => {
      const p = document.createElement('p');
      p.className = 'meta';
      p.textContent = s;
      host.appendChild(p);
    });
    // 这句承诺必须跟着显示：这一页别处写着「和无忧伴聊天的内容不会记在这里」，
    // 而这一块正是最容易让人怀疑那句话的地方。
    if (data.privacyNote) {
      const note = document.createElement('p');
      note.className = 'meta';
      note.textContent = data.privacyNote;
      host.appendChild(note);
    }
    host.hidden = false;
    speak(data.message);
  } catch (e) {
    showOut(host, window.YouHuo.errorWords(e, '心情记录').text);
  }
}

async function loadDayReport() {
  const host = document.querySelector('#dayReportBody');
  try {
    const data = await api('/api/v1/daily-report');
    host.replaceChildren();
    const line = document.createElement('p');
    line.textContent = data.message || '';
    host.appendChild(line);
    // 五个通道逐条说，但**只说有结论的**。`word` 是「现在还说不准」的那几条
    // 照样印——那不是缺数据，是一个诚实的回答（比如晚上还没到，就寝当然说不准）。
    const list = document.createElement('ul');
    list.className = 'care-lines';
    (data.channels || []).forEach((c) => {
      const li = document.createElement('li');
      li.textContent = c.today
        ? `${c.name}　${c.today}（平常 ${c.usual || '还没算出来'}）　${c.word}`
        : `${c.name}　${c.word}`;
      list.appendChild(li);
    });
    host.appendChild(list);
    host.hidden = false;
    speak(data.message);
  } catch (e) {
    showOut(host, window.YouHuo.errorWords(e, '今天的情况').text);
  }
}

async function loadMyData() {
  const host = document.querySelector('#myDataBody');
  try {
    const data = await api('/api/v1/privacy/data');
    renderCounts(host, data.buckets || [], data.message
      || `一共 ${data.total} 条。`);
  } catch (e) {
    host.replaceChildren();
    showOut(host, window.YouHuo.errorWords(e, '您的数据').text);
  }
}

/** 删除第一步：告诉她要删什么，然后**才**给出第二个按钮。
 *
 * 第二步的按钮**一开始不存在于 DOM 里**，不是 disabled 也不是 hidden。
 * 一个看得见的「确认删除」按钮会让人以为「点两下就没了」；而它在看到清单之前
 * 根本不该存在。
 *
 * `confirmToken` 由后端绑定条数算出，确认时它会重新数一遍再比对。这保证的不是
 * 防伪造（只有本人进得来、算法就在源码里），而是**她确认的对象和她看到的
 * 那一份是同一份**——回执写「删掉 7 条」实际删了 9 条，两边都不报错。
 */
async function startErase() {
  const host = document.querySelector('#eraseBody');
  try {
    const preview = await api('/api/v1/privacy/erase/preview', {
      method: 'POST', headers: {'Content-Type': 'application/json'}, body: '{}'
    });
    renderCounts(host, preview.willDelete || [], preview.message);

    const keep = document.createElement('p');
    keep.className = 'meta';
    keep.textContent = '这些会留下来：' + (preview.preserved || []).join('、');
    host.appendChild(keep);

    const confirm = document.createElement('button');
    confirm.type = 'button';
    confirm.className = 'danger block';
    confirm.textContent = `确认删掉这 ${preview.total} 条`;
    confirm.addEventListener('click', () => window.YouHuo.once(confirm, async () => {
      try {
        const done = await api('/api/v1/privacy/erase', {
          method: 'POST', headers: {'Content-Type': 'application/json'},
          // `confirmToken` 是驼峰，和 preview 返回的字段名一致。
          // 我第一版写了下划线，后端读不到就走 400
          // 「删除要先看一眼、再确认」——**它是对的**：从服务端看，
          // 一个没带令牌的删除请求和一个跳过预览直接来的请求没有区别。
          body: JSON.stringify({confirmToken: preview.confirmToken})
        });
        host.replaceChildren();
        showOut(host, done.message || '删好了。');
        speak(done.message);
      } catch (e) {
        // 令牌过期（条数在这中间变了）走 409，后端那句话说得比这里清楚。
        const p = document.createElement('p');
        p.className = 'notice warning';
        p.textContent = window.YouHuo.errorWords(e, '删除').text;
        host.appendChild(p);
      }
    }));
    host.appendChild(confirm);

    const cancel = document.createElement('button');
    cancel.type = 'button';
    cancel.className = 'secondary block';
    cancel.textContent = '先不删';
    cancel.addEventListener('click', () => {
      host.replaceChildren();
      host.hidden = true;
    });
    host.appendChild(cancel);
    speak(preview.message);
  } catch (e) {
    host.replaceChildren();
    showOut(host, window.YouHuo.errorWords(e, '删除').text);
  }
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

//: 任务类型 → 一位老人听得懂的说法，现在从 `common.js` 拿（`window.YouHuo.TASK_WORD`）。
//:
//: 这里原先有一张自己的表，写的是 `{bill_payment, appointment, medication}`——
//: 而后端 `TaskType` 是 hospital_registration / bill_payment / reminder /
//: form_assistance。`appointment` 与 `medication` **不是后端的值**，两个键永远
//: 命中不了。同一张表在 task-space.js / task-detail.js / trust.js 各有一份，
//: 都带着同一个错，三处注释还各自写着「要在 Phase C 收敛到一处」。
//:
//: ⚠ **但这一处的「正在办这件事」并没有因为收敛而修好，别读成已经修好了。**
//: 实测（打接口，不是猜）：引擎只在**缴费**分支往响应的 `data` 里放 `task_type`
//: （`engine.py:769`）。挂号走完整整四轮，`data` 里始终只有 `current_slots` 与
//: `missing`，`task_type` 一次都没出现。所以这一行拿到的是 undefined，
//: 表再正确也没用——真正的修法在后端。记在 KNOWN_ISSUES 里。
//:
//: 收敛真正修好的是读 `/v2/tasks`（TaskView）的那两处：老人端记录的详情层
//: （task-detail.js）和可信中心的凭证（trust.js）——那里 `task_type` 是全的。
//:
//: 兜底仍然是「这件事」，不是原始值：兜底成枚举名等于这层翻译在遇到新类型时
//: 自动失效，而那正是它该起作用的时候。

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

  // 说话之前先把 Focus Mode 打开。**这一行是一个 P0 的修复。**
  //
  // 对话区 `#chat`、状态行 `#status`、玻璃盒确认卡 `#relianceHost` 全都住在
  // `.elder-focus` 里，而它默认是 `display: none`。`#typeInstead`、`#nextOpen`、
  // `#kinContact` 三个入口都记得调 `setFocus(true)`，唯独**语音**这条没有——
  // 而语音是这个产品的主路径。
  //
  // 实测（390×844，按 `rec.onresult` 原样复现）：她说「帮我交这个月的电费」之后，
  // `#chat` 涨到 5 条气泡、`#relianceHost` 写进 1181 个字符的确认卡（126.50 元、
  // 风险等级 4、等待她复述确认），而三者的渲染高度**全是 0**。屏幕上依然写着
  // 「今天没有要办的事。」——系统正在等她口头确认一笔付款，而她看不到任何东西。
  // 唯一的通道是朗读。
  //
  // 附带损伤：`addBubble` 末尾那句 `chat.scrollTop = chat.scrollHeight` 作用在隐藏
  // 元素上是空操作，所以她事后手动进 Focus Mode，对话也永久停在开场白——连回头
  // 找答案都做不到。
  //
  // 修在 `send()` 顶上，而不是在语音回调里：这里是所有调用方的咽喉，补一处就覆盖
  // 全部入口，下一个新入口也不会再漏。
  //
  // 另一件要记的事：`stage.js` 和 `judge.js` **各自**为这条路径打过 workaround
  // （先点一下 `#typeInstead` 再填字）。也就是说这条路径的不可见性早就被发现了两次，
  // 而两次补丁都打在演示脚手架上，没有一次打进产品自己。
  setFocus(true);

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

    // Task Space：这件事办到哪一步，用**页面**说。
    //
    // 计划书第九至十三节：优活是 Task Agent，不是聊天机器人。她说完
    // 「帮我交这个月水费」之后，屏幕上该出现的是这件事本身——多少钱、给谁、
    // 办到哪一步、现在要她做什么——而不是一串气泡让她自己从对话里拼出来。
    //
    // 状态全部来自后端（`code` / `task_status` / `data`），这个模块只负责怎么显示。
    // 认不出的状态它回 `null`，那时 `body.dataset.taskView` 不写，
    // CSS 把聊天区放回来——**不猜**。多一个没见过的状态码就渲染一个内容是编的页面，
    // 比不渲染糟得多：她会照着假页面去做决定。
    //
    // 聊天记录没有删（不得 silent delete），它退到 Task Space 下面。
    const taskView = taskViewModel(data);
    if (renderTaskSpace(taskSpaceHost, taskView)) {
      document.body.dataset.taskView = taskView.kind;
    } else {
      delete document.body.dataset.taskView;
    }

    if (asksForConfirmation) {
      await showGlassBox(text, data);
    } else {
      relianceHost.replaceChildren();
    }

    // 状态行说"我在办什么"，不说任务 ID。
    //
    // 原文是 `当前任务：${data.task_id}。`——屏幕上出现的是
    // 「当前任务：task-cf917fee2790476500fb。您随时可以说"再说一遍"或"取消"。」
    // 那串十六进制是给数据库看的，而这一行的读者是一位视力在下降的老人；更糟的是
    // 这一行会被读屏软件念出来，念一串哈希是这个产品最不该做的事。
    //
    // 它想说的其实是"我还在办这件事，你可以打断我"。说成「正在办：缴费」就够了，
    // 而任务类型是后端已经给出来的。
    //
    // 这个缺陷先在 /family 被视觉审查抓到（那边把任务 ID 印在卡片上），
    // 顺着同一条规则建的运行时标识符闸门把这里也点了出来——同一个错，受众更差。
    // `taskWord()` 认不出时给的是「这件事」，而这一行下面本来就有「这件事」那个
    // 分支，所以这里要的是「认出来了吗」——拿原始值查表，不是拿兜底后的字。
    const type = data.data?.task_type;
    const doing = type && window.YouHuo.TASK_WORD[type];
    setStatus(data.task_id
      ? `正在办${doing ? '：' + doing : '这件事'}。您随时可以说「再说一遍」或「取消」。`
      : '办事可留痕；陪伴默认不向家属展示聊天全文。');
    loadReminders();
    if (document.body.dataset.tab === 'log') loadActivity();
    settled = activityFor(data);
  } catch (e) {
    recentRetries += 1;
    // 原先是 `系统暂时不可用：${e.message}`。两个毛病：
    //
    //   ① `e.message` 在断网时是 `Failed to fetch`——一句英文，而这一句会被念出来。
    //   ② 「系统暂时不可用」是**错的诊断**。她自己家里断网时，说的是我们坏了。
    //      而下面第三行已经在用 `navigator.onLine` 区分这两种情形了——判断做过，
    //      只是没用在说给她听的那句话上。
    const words = window.YouHuo.errorWords(e);
    addBubble(`${words.say}。${words.then}`, 'agent');
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
    // 回执写**状态行**，不写对话气泡。
    // ......................................................................
    // `addBubble` 写的是 `#chat`，而 `#chat` 住在 `.elder-focus` 里、
    // 默认 `display: none`。实测（430×932，Focus Mode 关着）：
    //
    //     #chat          盒子 [0,0]   被 div.elder-focus 藏着
    //     #relianceHost  盒子 [0,0]   同上
    //     #status        空的时候自己 display:none，一有文字就出现
    //
    // 所以老人按「我知道了」的实际体验是：请求发出去了、后端记下了，
    // 而**屏幕上一个字都没变**。她会再按一次，再一次。
    //
    // 这和 `send()` 顶上那段注释记的是**同一个缺陷的另一半**：当时发现
    // 语音那条路径没调 `setFocus(true)`，补上了；`reminderAction` 有同样的
    // 毛病却没被一起修——因为那次是从"语音说完看不到确认卡"倒查的，
    // 而按待办按钮的人根本不在对话里。
    //
    // 这里**不补 `setFocus(true)`**：她在勾一件事，不是在对话。
    // 为了让回执可见而把整屏切成对话视图，是用一个更大的意外换一个小的。
    setStatus(adapted.visual_text || data.message);
    if (data.ui?.speak) speak(adapted.speak_text || data.message, adapted.speech_rate);
    loadReminders();
    if (document.body.dataset.tab === 'log') loadActivity();
  } catch (e) {
    // 老人端尤其不能弹 `alert()`：装到主屏后那是一个带 "127.0.0.1 显示" 字样的
    // 系统灰框，会盖住整屏、冻住页面，而且只有一个"确定"可按。这一页其余的失败
    // 都写在状态行里，这一处也照做。
    //
    // 状态行只容得下一句，所以取 `say` 而不是拼好的 `text`——但**这一行会被念出来**，
    // 所以它同样不能是 `e.message`（那可能是 `Failed to fetch`）。
    const words = window.YouHuo.errorWords(e);
    setStatus(`这条待办没能更新：${words.say}`);
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

function renderTodayLine(reminders, pendingCount = 0) {
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
  //: 一件都没有、但下面摆着一张要她点头的卡片时，这一行不能说「没有事」。
  //: 这一屏的设计意图是「一次只说一件事」，而它的反面不是"多说一句"，
  //: 是**同一屏上两处互相打架**——上面写着没有事，下面问她要不要开始吃药。
  line.textContent = pendingCount
    ? '今天没有要办的事，只有一件要您点个头。'
    : '今天没有要办的事。';
  line.hidden = false;
}

/** 家人加的药，等她点头。
 *
 * ## 这条流程此前是断的
 *
 * `create_medication_plan` 对 FAMILY 角色建的计划是 `active=False`，
 * 而激活**只允许老人本人**做（`v4_api.py:342`）。也就是说这条流程按设计
 * 必须在老人这一端完成——而老人这一端**没有入口**：女儿在家属端加了一份钙片，
 * 它就永远停在待确认，老人看不见、也点不了同意，**两边界面都不报任何错**。
 *
 * `/api/v1/medications/pending|approve|decline` 三个端点是上一轮补的，
 * 补完之后全仓**没有任何前端调它们**——端点齐了，流程还是断的。这里接上。
 *
 * ## 为什么摆在「今天」的最上面
 *
 * 它不是「我的数据」，是一件**等她决定**的事。放进设置页等于埋掉。
 * 卡片用和待办一样的 `.task` 形状：同一类东西在同一个位置长同一个样子，
 * 她不需要学第二套。
 */
async function pendingMedications() {
  try {
    return await api('/api/v1/medications/pending');
  } catch (e) {
    // 取不到就安静地当成没有。它是**额外**的一块，
    // 让它的失败挡住整屏待办是不划算的——待办本身有自己的错误分支。
    return {count: 0, items: []};
  }
}

function renderPendingMedications(data) {
  if (!remindersEl || !data.count) return;

  const decide = async (plan, approve) => {
    try {
      const said = await api(
        `/api/v1/medications/${encodeURIComponent(plan.id)}/${approve ? 'approve' : 'decline'}`,
        {method: 'POST', body: JSON.stringify({})});
      // 回执写状态行。理由同 `reminderAction`：`#chat` 在 Focus Mode 里，
      // 而她按这个按钮时 Focus Mode 是关着的。
      setStatus(said.message);
      speak(said.message);
      loadReminders();
    } catch (e) {
      setStatus(window.YouHuo.errorWords(e, '这份药').text);
    }
  };

  // 在待办之前 append，所以它们整体排在最上面。
  data.items.forEach(plan => {
    const div = document.createElement('div');
    div.className = 'task';
    const title = document.createElement('strong');
    title.textContent = plan.name;
    const who = document.createElement('div');
    who.textContent = '家里人给您加的';
    const how = document.createElement('div');
    how.textContent = [plan.doseText, (plan.times || []).join('、')]
      .filter(Boolean).join(' · ');
    const statusLine = document.createElement('div');
    const chip = document.createElement('span');
    // 用 `confirm` 这一档：家人端的 `notified` 也是这个色，
    // 两边对「等一个人点头」用同一种视觉，不另起一套。
    chip.className = 'status-chip confirm';
    chip.textContent = '等您点头';
    statusLine.append('状态：', chip);
    div.append(title, who, how, statusLine);

    const yes = document.createElement('button');
    yes.textContent = '开始吃';
    const no = document.createElement('button');
    no.textContent = '先不吃';
    no.className = 'secondary';
    // 包在 `once()` 里：这一下要往返后端，而慢网络下连点两次的第二次
    // 会拿一个已经处理过的计划去决定，后端会正确地拒绝，
    // 但屏幕上会闪一句错误，让人以为第一次没成功。
    yes.addEventListener('click', () => window.YouHuo.once(yes, () => decide(plan, true)));
    no.addEventListener('click', () => window.YouHuo.once(no, () => decide(plan, false)));
    div.append(yes, document.createTextNode(' '), no);

    remindersEl.appendChild(div);
  });
}

async function loadReminders() {
  if (!remindersEl) return;
  try {
    // 两个一起取。待确认的药是**另一条流程**（家人加、她点头），
    // 和 `/v2/reminders` 没有先后依赖，串行只是白等一个往返。
    const [reminders, pending] = await Promise.all([
      api('/v2/reminders?limit=50'),
      pendingMedications(),
    ]);
    renderTodayLine(reminders, pending.count);
    renderNextItem(reminders);
    renderTodayBlock(reminders, pending.count);
    remindersEl.replaceChildren();
    // 先放它，所以它排在待办上面：这是**等她决定**的事，待办只是到点提醒。
    renderPendingMedications(pending);
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
    // `!pending.count` 这一半是必须的：`emptyState` 会 replaceChildren，
    // 没有它的话「现在没有待办」会把刚放上去的待确认卡片整个抹掉——
    // 而屏幕上同时说着「没有待办」和摆着一张要她点头的卡，本身也是自相矛盾。
    if (!visible.length && !pending.count) {
      emptyState(
        remindersEl,
        ['M8 3.4v3.2M16 3.4v3.2', 'M4.4 9.4h15.2', 'M5.4 5h13.2a1.6 1.6 0 0 1 1.6 1.6v12a1.6 1.6 0 0 1-1.6 1.6H5.4a1.6 1.6 0 0 1-1.6-1.6v-12A1.6 1.6 0 0 1 5.4 5z'],
        '现在没有待办',
        '您可以说「提醒我明天上午九点复诊」，我来记着。',
      );
    }
    const toggle = document.querySelector('#toggleReminders');
    toggle.hidden = reminders.length <= 3;
    toggle.textContent = showAllReminders ? '只看最要紧的三件' : `查看全部待办（共${reminders.length}件）`;
  } catch (e) {
    // 原先是 `待办加载失败：${e.message}`——`e.message` 可能是
    // `Failed to fetch`，而这一行会被念给老人听。见 common.js 的 errorWords。
    //: 这里原先是 `window.YouHuo.window.YouHuo.errorWords(...)`——
    //: `window.YouHuo.window` 是 undefined，再取 `.YouHuo` 当场 TypeError。
    //: 也就是说**后端一断，这段处理自己先崩**，她屏幕上一个字都不会出现。
    //: 看形状是某次批量加 `window.YouHuo.` 前缀时，在已经有前缀的行上又替了一次。
    //: 全仓三处，全在 catch 里（待办 / 记录 / 事件经过）——它们只在请求失败时
    //: 执行，所以语法检查、截图、点击遍历一个都看不见。判据见
    //: `test_the_error_path_can_run.py`。
    remindersEl.textContent = window.YouHuo.errorWords(e, '待办').text;
  }
}

/** Design §4.4 log entry point; §6.3 keeps companion chat out of the log. */
async function loadActivity() {
  try {
    const entries = await api('/v2/elder/activity?limit=30');
    activityLogEl.replaceChildren();
    entries.forEach(entry => {
      // 有主体的行是**真按钮**，没有的仍是 div。
      //
      // 为什么不是一律做成按钮：allow-list 里有些事件不挂在任务上（`about_id`
      // 为 null），那种行按下去无处可去。一个看起来能按、按了没反应的控件
      // 比一行纯文字糟——它让人以为是坏的。
      //
      // `<button>` 而不是给 div 加 click：键盘能到、读屏报得出角色、
      // 焦点环免费。这一页的读者里有只用键盘和开关控制的人。
      const clickable = !!entry.about_id;
      const row = document.createElement(clickable ? 'button' : 'div');
      row.className = 'log-item';
      if (clickable) {
        row.type = 'button';
        // id 只进 dataset，**永远不渲染成文字**。它是
        // `task-2a2728fe86f54c06b52e` 这种东西，手机框里只放「哪件事、到哪一步」。
        row.dataset.about = entry.about_id;
        row.setAttribute('aria-label', `${entry.what} ${entry.who}，看这件事的经过`);
      }
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
  } catch (e) {
    activityLogEl.textContent = window.YouHuo.errorWords(e, '记录').text;
  }
}

/* ==========================================================================
   事务详情：压在四个 Tab 之上的一层
   ==========================================================================
   四个行为照抄 `sheet.js`（这一页最精细的无障碍代码）：背后整体 `inert`、
   焦点存取、Escape、真按钮做出口。**没有**照抄它的甩动关闭——一笔事务的记录
   是用来读的，而 sheet.js 自己的注释写着「Gesture-only UI fails this audience
   first」，所以出口就是底部那个按钮。

   也没有复用 sheet.js 本体：那个抽屉在 ≥761px 会变成常驻侧栏（`isDrawer()`），
   而详情层在任何宽度下都是模态。共用一个模块就得给那个双形态再加开关。
   两份实现之间由 `test_both_overlays_behave_the_same` 钉住不许漂移。 */

const detailLayer = document.querySelector('#taskDetail');
const detailBackdrop = document.querySelector('#detailBackdrop');
const detailBody = document.querySelector('#taskDetailBody');
let detailLastFocus = null;

/** 详情层背后要被隔离的那些层。
 *
 * 和 `sheet.js:60-63` 同一个理由：背板拦得住鼠标，拦不住 Tab。
 * 少了这一步，键盘用户会 Tab 进一个被完全盖住的输入框和麦克风。
 */
function detailOutsideLayers() {
  return [...document.querySelectorAll('main > *, .elder-layout > *')]
    .filter(el => el !== detailLayer && el !== detailBackdrop && !el.contains(detailLayer));
}

function setDetailOpen(open) {
  if (!detailLayer || !detailBackdrop) return;
  detailLayer.classList.toggle('is-open', open);
  detailBackdrop.classList.toggle('is-open', open);
  detailLayer.setAttribute('aria-hidden', open ? 'false' : 'true');
  if (open) detailLayer.removeAttribute('inert');
  else detailLayer.setAttribute('inert', '');
  document.body.classList.toggle('detail-open', open);
  detailOutsideLayers().forEach(el => {
    if (open) el.setAttribute('inert', ''); else el.removeAttribute('inert');
  });
  if (open) {
    detailLastFocus = document.activeElement;
    // 焦点送到出口上，不是送到第一段文字上：她按开这一层通常是想看一眼就走，
    // 而键盘用户按一下空格就能出来。
    document.querySelector('#taskDetailClose')?.focus({preventScroll: true});
  } else if (detailLastFocus) {
    detailLastFocus.focus({preventScroll: true});
    detailLastFocus = null;
  }
}

/** 按主体 id 打开详情。
 *
 * 读的是 `/v2/tasks`（`TaskView`），**不是 `/v2/audit`**。这是那条
 * 「取证与叙事是两个模型」的落地：审计链留给 `/judge`，消费者面读任务本身。
 * 服务端已按 `actor.actor_id` 把列表收窄到她自己的任务，所以在客户端按 id 找是安全的。
 */
async function openTaskDetail(aboutId) {
  if (!aboutId || !detailBody) return;
  renderTaskDetail(detailBody, null);   // 先清空，避免闪出上一笔的内容
  setDetailOpen(true);
  try {
    const tasks = await api('/v2/tasks?limit=100');
    const task = (tasks || []).find(item => item.id === aboutId);
    renderTaskDetail(detailBody, taskDetailViewModel(task));
  } catch (e) {
    detailBody.replaceChildren();
    detailBody.textContent = window.YouHuo.errorWords(e, '这件事的经过').text;
  }
}

if (activityLogEl) {
  // 事件委托：行是每次 loadActivity() 重新造的，逐行绑会随着刷新累积监听器。
  activityLogEl.addEventListener('click', event => {
    const row = event.target.closest('.log-item[data-about]');
    if (row) openTaskDetail(row.dataset.about);
  });
}
document.querySelector('#taskDetailClose')?.addEventListener('click', () => setDetailOpen(false));
detailBackdrop?.addEventListener('click', () => setDetailOpen(false));
document.addEventListener('keydown', event => {
  if (event.key === 'Escape' && detailLayer?.classList.contains('is-open')) {
    setDetailOpen(false);
  }
});
// 初始状态：关。`inert` 已经写在 HTML 里，这一行让 class 和它对齐。
setDetailOpen(false);

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
  // 这两句会**当成她自己说的话**上屏：`send()` 里就是 `addBubble(text, 'user')`。
  // 所以按钮送出去的不能是触发词，得是一句她真会说的话——原先送的是「调用无忧伴」，
  // 于是聊天记录里出现一条她的气泡写着「调用」，一个编程动词。
  //
  // 「找无忧伴聊聊」照样命中：companion.py 的 COMPANION_REQUESTS 里有「找无忧伴」，
  // 匹配是 `any(phrase in text …)` 的子串匹配。「继续办事」同理（engine.py:1418）。
  send(currentMode === 'companion' ? '继续办事' : '找无忧伴聊聊');
});

// 「我的记录」从折叠面板变成了「记录」Tab 里常驻的一段，所以这个按钮的职责从
// 展开/收起变成了刷新。
//
// 原来还带一次 `scrollIntoView`——那是为了对付"面板排在定高框架里定高子元素后面、
// 只露 70px 且滚不到"的老问题。现在它在自己的 Tab 里，从第一行就看得见。
document.querySelector('#logEntry').addEventListener('click', () => {
  const label = document.querySelector('#logEntryLabel');
  label.textContent = '正在读取…';
  loadActivity().finally(() => { label.textContent = '刷新我的记录'; });
});

document.querySelector('#toggleReminders').addEventListener('click', () => {
  showAllReminders = !showAllReminders;
  loadReminders();
});

//: 「再说一遍」原先**只念，不写屏**。
//:
//: 没有语音合成的时候（浏览器没装中文音色、设备静音、页面还没拿到用户手势
//: 因而 speechSynthesis 被拦），按下去屏幕上一个字都不动。而这个按钮叫
//: 「再说一遍」，它存在的全部理由就是**给听不清、看不清的人再来一次**——
//: 恰恰是最不该只走声音那一条通道的地方。
//:
//: 巡检（把每个控件都点一遍、看有没有请求或界面变化）抓到的就是它：
//: /elder 记录页 15 个控件里，只有这一个点下去什么都没发生。
//:
//: 这和 `reminderAction` 那次是同一个缺陷（见 `test_an_action_must_show_itself`）：
//: 回执只走了一条她可能收不到的通道。两条都走：写进状态行，同时念。
document.querySelector('#repeatLast').addEventListener('click', () => {
  const words = lastSpoken || '目前还没有需要重复的内容。';
  setStatus(words);
  speak(words);
});

// "返回上一步" replays the previous question instead of pretending to roll back
// server state; the task itself stays exactly where it is.
document.querySelector('#stepBack').addEventListener('click', () => {
  if (promptHistory.length < 2) {
    const only = promptHistory[0];
    const text = only ? only.text : '这是第一步，还没有上一步可以返回。';
    //: 这一支原先只有 `addBubble` + `speak`，**没有 `setStatus`**。
    //: `addBubble` 写的 `#chat` 住在 `.elder-focus` 里，Focus Mode 关着时
    //: display:none——而她在记录页按这个按钮时，Focus Mode 正是关着的。
    //: 于是「还没有上一步可以返回」这句话，屏幕上一个字都不会出现。
    //: 下面那一支（真的回到上一步）本来就写状态行，两支不该只有一支说话。
    setStatus(text);
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

// 「我的数据」那四个。全部包在 `once()` 里：这几个都要往返一次后端，
// 而慢网络下连点两次「删掉」是不可接受的——第二次会拿一个已经用过的令牌
// 去删一份已经不存在的数据，后端会正确地拒绝，但屏幕上会闪一句错误，
// 让人以为第一次没成功。
[['#moodReview', loadMoodReview],
 ['#dayReport', loadDayReport],
 ['#myData', loadMyData],
 ['#eraseStart', startErase]].forEach(([sel, run]) => {
  const btn = document.querySelector(sel);
  if (btn) btn.addEventListener('click', () => window.YouHuo.once(btn, run));
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
    // 上面那六句话，此前**一句都不会出现在屏幕上**。
    //
    // `setStatus` 写的是 `#status`，而 `#status` 在 `.elder-focus` 里面，而
    // `pages.css:304` 是 `.elder-focus { display: none }`。进 Focus Mode 的唯一入口
    // 在 `send()` 里——语音失败时 `send()` 从来没被调用过（`onresult` 才调它）。
    // 所以真实经过是：她按下麦克风，系统弹权限框，她点了"不允许"，然后**屏幕上
    // 什么都没变**。那句唯一能告诉她「去手机设置里打开麦克风权限」的话，
    // 被写进了一个 display:none 的元素里。`input.focus()` 同理——`#text` 也在里面，
    // 对一个不显示的输入框调 focus() 什么都不会发生。
    //
    // 这是 A-01 的同一个缺陷第二次出现，而 A-01 修的是成功路径。失败路径更要紧：
    // 顺利的时候她不需要提示，卡住的时候才需要。
    //
    // Focus Mode 恰好满足这六句话的全部前提：`#status` 显形（她读得到），composer
    // 显形（「在下面打字」这句话从此为真，`input.focus()` 也真的落到输入框上），
    // 而麦克风**不在**被 Focus Mode 藏起来的那一组里（`pages.css:310-314` 藏的是
    // roleHeader / todayLine / nextItem / today-block / elder-tabs），所以
    // 「再按一下慢慢说」也仍然可做。`#focusBack` 给她回去的路。
    setFocus(true);
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

/* ==========================================================================
   四个 Tab 与 Focus Mode
   ..........................................................................
   这一屏原先塞着九样东西：角色头、今天、对话、信任卡、麦克风、三个快捷、输入行、
   抽屉入口、状态行。一位老人打开它，第一眼要在九样里找出"我现在该干什么"。

   现在首页只回答三个问题——今天有没有事、下一件是什么、怎么让优活帮我——对话与
   输入行进 Focus Mode。

   Focus Mode 是首页的一个**态**（`body[data-focus]`），不是第五个 Tab。理由是
   Voice Orb 只能有一个 `#mic`，而按下它之后 orb 仍然在场；做成并列分区就得复制一个
   orb，两个 orb 的状态机会立刻分叉。
   ========================================================================== */

/** 进/出 Focus Mode。
 *
 * 不碰 Voice Orb 的状态——那由 `setActivity` 独占管理。这里只管"屏幕上还剩哪些东西"。
 */
function setFocus(on, {focusInput = false} = {}) {
  document.body.dataset.focus = on ? 'on' : 'off';
  if (on && focusInput) input.focus();
  if (!on) {
    // 退出时清空输入框。留着上一次没发出去的半句话，下次进来会让人以为它已经发过了。
    input.value = '';
    mic.focus({preventScroll: true});
  }
}

document.querySelector('#typeInstead').addEventListener('click', () => {
  setFocus(true, {focusInput: true});
});
document.querySelector('#focusBack').addEventListener('click', () => setFocus(false));

// Esc 退出。键盘用户在 Focus Mode 里必须有一条不用找按钮的出路。
document.addEventListener('keydown', event => {
  if (event.key === 'Escape' && document.body.dataset.focus === 'on') setFocus(false);
});

/** 「下一件」。首页只显示一件最要紧的事，不显示今日全部。
 *
 * 一位老人不需要在首屏做排序——她需要知道下一步。由 `loadReminders()` 调用。
 */
/** 「今天」那一块的显隐。
 *
 * 没有待办时收起来。原先它会显示一个「现在没有待办」的空状态，而上面那一行
 * `#todayLine` 已经写着「今天没有要办的事。」——一屏内容里有两处在说同一件事，
 * 而这一屏的全部设计意图就是"一次只说一件事"。
 */
function renderTodayBlock(reminders, pendingCount = 0) {
  const block = document.querySelector('.today-block');
  if (!block) return;
  const open = (reminders || []).filter(
    item => !['completed', 'cancelled'].includes(item.status));
  //: `pendingCount` 这一半是驱动出来的，不是想出来的。
  //:
  //: 待确认的药渲染进 `#reminders`，而 `#reminders` 就住在这一块里面。
  //: 没有这一半时，一户「今天没有待办、但家人刚加了一份药」的人家——
  //: 也就是**这条流程最典型的样子**——整块 `display:none`，那张卡片
  //: 在 DOM 里、按钮也能被脚本点着，屏幕上什么都没有。
  //:
  //: 实测（430×932 和 1280×900 两个视口都是）：
  //:     DIV#reminders        display=grid   box=[0, 0]
  //:     SECTION.today-block  display=none   ← 这里
  //: 我在同一次改动里已经想到了 `emptyState` 会 replaceChildren 那一处，
  //: 却漏了这一处：**两处都是「没有待办」的判断，而它们不在同一个函数里**。
  block.hidden = open.length === 0 && !pendingCount;
}

function renderNextItem(reminders) {
  const card = document.querySelector('#nextItem');
  if (!card) return;
  const open = (reminders || [])
    .filter(item => !['completed', 'cancelled'].includes(item.status))
    .filter(item => isToday(item.due_at))
    .sort((a, b) => new Date(a.due_at) - new Date(b.due_at));
  const next = open[0];
  // `data-ready` 是内容的**盖章**，不是显隐开关。
  //
  // 这张卡原先只靠 `hidden` 属性控制，而这个函数要等 `/v2/reminders` 回来才跑——
  // 首屏渲染发生在那之前，于是有一瞬间卡是露着的，而里面只有一个孤零零的「查看」
  // 按钮。截图抓到的就是那一瞬间。
  // 现在 CSS 兜底：没盖章就不显示（`.next-item:not([data-ready])`）。显隐和内容
  // 由同一件事决定，不再是两个地方各说一半。
  if (!next) {
    card.removeAttribute('data-ready');
    card.hidden = true;
    return;
  }
  const at = new Date(next.due_at);
  const pad = value => String(value).padStart(2, '0');
  document.querySelector('#nextTime').textContent = `${pad(at.getHours())}:${pad(at.getMinutes())}`;
  document.querySelector('#nextTitle').textContent = next.title || '一件要办的事';
  const where = next.location || next.note || '';
  const whereEl = document.querySelector('#nextWhere');
  whereEl.textContent = where;
  whereEl.hidden = !where;
  card.dataset.ready = 'true';
  card.hidden = false;
}

// 「查看」把这件事说出口，走的是和语音一模一样的那条路——这一页只有一个入口，
// 不给老人第二套心智模型。
document.querySelector('#nextOpen').addEventListener('click', () => {
  const title = document.querySelector('#nextTitle').textContent.trim();
  setFocus(true);
  send(title ? `说说${title}这件事` : '我今天有什么事');
});

document.querySelector('#kinContact').addEventListener('click', () => {
  setFocus(true);
  send('帮我联系家人');
});

// Tab 切换。`initSections` 在 common.js 里，家人端和照护页用的是同一套约定。
// 切 Tab 一律退出 Focus Mode：她已经离开那件事了，屏幕不该还停在对话上。
window.YouHuo.initSections('home');

/* ==========================================================================
   家人：谁能帮我、怎么找她
   ==========================================================================
   原先这一屏写死「李晴 / 女儿」——产品里唯一一个人名，而它不在任何数据里。
   现在读真数据；读不到就只说角色，**不编名字**。 */

//: 身份里的家庭成员字段 → 说给人听的关系词。
//:
//: 为什么从身份的字段名推：`/v4/contacts/{elder}` 在演示数据下是空的（实测），
//: 而身份里的 `daughter_id` / `son_id` 是这个家庭**真实存在**的行动者——
//: 种子场景那条「家人确认了一次，还在等其他家人」正是它们两个。
//: 与其编一个名字，不如说清有几位、各是什么关系。
const KIN_RELATION = {daughterId: '女儿', sonId: '儿子'};

async function renderKin() {
  const host = document.querySelector('#kinList');
  if (!host) return;
  const ids = await resolveIdentity();

  /** 家庭里真实存在的那几位，按关系。 */
  const fallback = Object.entries(KIN_RELATION)
    .filter(([key]) => ids && ids[key])
    .map(([, relation]) => ({relation, name: ''}));

  let people = fallback;
  try {
    // 真数据优先：家属那一侧添过、老人批准过的亲友档案。
    const contacts = await api(`/v4/contacts/${encodeURIComponent(ELDER_ID)}`);
    const approved = (contacts || []).filter(c => c.status !== 'proposed');
    if (approved.length) {
      // 称呼和关系相同就不算「有名字」。这个产品**不编人名**（见上面
      // KIN_RELATION 那段注释），所以演示数据里 display_name 就是「女儿」
      // 「儿子」——照原样传下去，下面会把它同时放进主位和次位，
      // 屏幕上是「儿子 / 儿子」两行。
      //
      // 顺带把电话带上：`phone_masked` 是打过码的（后端存的就是掩码，
      // 原号只留摘要）。这一屏此前只有关系词，而「出事找谁」这个问题
      // 需要的是「找谁 + 怎么找」。
      people = approved.map(c => ({
        relation: c.relation || '家人',
        name: (c.display_name && c.display_name !== c.relation) ? c.display_name : '',
        phone: c.phone_masked || '',
      }));
    }
  } catch (_) {
    // 取不到就用 fallback。这一屏的价值是「谁能帮我」，那一条不依赖这个接口。
  }

  host.replaceChildren();
  if (!people.length) {
    // 连行动者都没有：说实话。不写「李晴」。
    const empty = document.createElement('p');
    empty.className = 'kin-rel';
    empty.textContent = '还没有家人和您连在一起。';
    host.appendChild(empty);
    return;
  }
  people.forEach(person => {
    const row = document.createElement('div');
    row.className = 'kin-person';
    // 有名字就把名字放主位、关系放次位；没名字就只有关系，**不留一个空的主位**。
    if (person.name) {
      const name = document.createElement('p');
      name.className = 'kin-name';
      name.textContent = person.name;
      row.appendChild(name);
    }
    const rel = document.createElement('p');
    rel.className = person.name ? 'kin-rel' : 'kin-name';
    rel.textContent = person.relation;
    row.appendChild(rel);
    // 打过码的电话。「出事找谁」这个问题要的是「找谁 + 怎么找」，
    // 这一屏此前只回答了前半句。原号不显示、也不落在这一页上——
    // 后端存的就是掩码，前端拿不到完整号码。
    if (person.phone) {
      const tel = document.createElement('p');
      tel.className = 'kin-rel';
      tel.textContent = person.phone;
      row.appendChild(tel);
    }
    host.appendChild(row);
  });
}

/** 这个 Tab 需要什么数据，就在进去的时候取。
 *
 * 修一个一直都在的缺陷：`loadActivity()` 原先只有三个调用点——`send()` 与
 * `reminderAction()` 里带 `if (dataset.tab === 'log')` 的两处，加上「刷新我的记录」
 * 那个按钮。而 Tab 切换处理器**只设 `dataset.tab`，从不取数**。
 *
 * 于是「记录」这一页是**打开即空**：不是空态，是一个白框——`emptyState()` 也没跑，
 * 因为 `loadActivity()` 根本没被调用。深链到 `/elder#log` 更糟：`dataset.tab`
 * 连值都没有，之后任何一次对话轮次也不会顺带加载它。
 *
 * 唯一能看到内容的办法是按那个叫「**刷新**我的记录」的按钮——而「刷新」这个词
 * 暗示屏幕上本来有东西。实测就是这样：走到 `#log`，0 条记录、0 条控制台错误。
 */
function enterTab(name) {
  document.body.dataset.tab = name;
  if (name === 'log') loadActivity();
  if (name === 'kin') renderKin();
}

document.querySelectorAll('.elder-tabs .seg').forEach(tab => {
  tab.addEventListener('click', () => {
    setFocus(false);
    enterTab(tab.dataset.section);
  });
});

// 首屏与刷新：当前是哪个 Tab 由 `initSections` 按 hash 定，所以从**它的结果**读，
// 不自己再解析一遍 hash（两处各写一份判据必然漂移，这个项目为此吃过亏）。
const initialPanel = document.querySelector('.elder-panel[data-panel]:not([hidden])');
enterTab(initialPanel?.dataset.panel || 'home');

// 浏览器前进/后退也会换 Tab。`initSections` 自己监听 hashchange 换面板，
// 但它不知道哪个面板需要取数。
addEventListener('hashchange', () => {
  const shown = document.querySelector('.elder-panel[data-panel]:not([hidden])');
  if (shown) enterTab(shown.dataset.panel);
});

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
    text: '您好，我是优活。您可以直接说「帮我挂号」「查一下水费」或「找无忧伴聊聊」。我会一次只问一件事。',
    speak: '您好，我是优活。您可以直接说帮我挂号、查一下水费，或者找无忧伴聊聊。',
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
