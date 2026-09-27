import {
  configureNeuralVoice, pickVoice, probeNeuralVoice, resetVoiceCache, speakClauses, warmNeuralVoice,
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

/** 这一页的「几点」一律是北京时间，不是设备时间。
 *
 * 后端有一条明确的规矩：凡是要读出墙上时间的地方都先过 `local_now()`
 * （`youhuo/utils.py`，`LOCAL_TIMEZONE = "Asia/Shanghai"`）。所以同一条提醒，
 * `/api/v1/agenda` 下发的 `time` 是**北京时间**的钟点。
 *
 * 而这一页原先拿 `due_at` 自己算：`toLocaleTimeString` 不带 timeZone、
 * `getHours()` / `getMonth()` 全是设备本地。在 UTC+8 的机器上两边一致，
 * 所以这个缺陷在开发机上完全看不出来。
 *
 * 实测（真接口 + Node 按 TZ 驱动，due_at=2026-08-25T03:00:00Z，
 * 后端 /api/v1/agenda 同一条给的是 11:00）：
 *
 *     设备 Asia/Shanghai     friendlyTime 今天 11:00   isToday true   ← 一致
 *     设备 UTC               friendlyTime 今天 03:00   isToday true
 *     设备 America/New_York  friendlyTime 8月24日 23:00 isToday false
 *
 * 最后那一行不只是「时刻显示错了八小时」：`isToday` 判成昨天，这一条从
 * 「今天有 N 件事」和「接下来」里**整条消失**；而同一次实测里，明天那条
 * （2026-08-26T03:00:00Z）反过来被判成今天，写着「今天 23:00」。
 * 也就是说按日筛出来的那一列，装的是别的一天的事。
 */
const WALL_CLOCK_ZONE = 'Asia/Shanghai';

/** 一个时刻在**北京时间**里的年 / 月 / 日，以及 `HH:MM`。
 *
 * 用 `formatToParts` 而不是拼字符串：这样年月日和时分出自**同一次**格式化，
 * 不会出现「日期取自一个时区、钟点取自另一个」的错位。
 * `hourCycle: 'h23'` 是实测选的——`hour12: false` 在部分引擎上午夜给 `24`。
 */
function wallClock(value) {
  const bag = {};
  new Intl.DateTimeFormat('en-US', {
    timeZone: WALL_CLOCK_ZONE,
    hourCycle: 'h23',
    year: 'numeric', month: '2-digit', day: '2-digit',
    hour: '2-digit', minute: '2-digit',
  }).formatToParts(value instanceof Date ? value : new Date(value))
    .forEach(part => { bag[part.type] = part.value; });
  return {
    year: Number(bag.year),
    month: Number(bag.month),
    day: Number(bag.day),
    hhmm: `${bag.hour}:${bag.minute}`,
  };
}

/** Elder-readable timestamps: no seconds, no year when it is this year. */
function friendlyTime(value) {
  const at = wallClock(value);
  const now = wallClock(new Date());
  const sameDay = at.year === now.year && at.month === now.month && at.day === now.day;
  if (sameDay) return `今天 ${at.hhmm}`;
  const year = at.year === now.year ? '' : `${at.year}年`;
  return `${year}${at.month}月${at.day}日 ${at.hhmm}`;
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
  window.YouHuo.showNotice(status,text,{duration:/^正在/.test(text)?0:8000});
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

/* 主动提醒念出来（`/elder2` 的小优收到新提醒时发 `youhuo:announce`，见 elder-v6-b.js）。
 *
 * 原先提醒只画在气泡里：服务器定时器到点发了「该吃降压药了」，屏幕上冒一个气泡，
 * 八秒后消失——而她那时候多半没在看手机。主动服务要**说出来**才算送到。
 *
 * 只在空闲时念：她正在说（listening）、优活正在想（processing）或正在说（speaking），
 * 都不插嘴——插嘴会打断她自己的那一轮，气泡照样在，不会丢。 */
document.addEventListener('youhuo:announce', (event) => {
  const text = String(event?.detail?.text || '').trim();
  if (!text) return;
  if (document.body.dataset.activity !== 'idle') return;
  speak(text);
});

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
  /* 档位还要写一份到 `body` 上。
   *
   * 媒体查询读不到 CSS 变量，而**特大档必须配套压缩布局**：字号放大 44% 之后，
   * 「用打字说」会被挤出第一屏——实测 360×640 上它在 y597..653，而底栏上沿
   * 在 568，等于掉到底栏后面去了。语音失败时它是唯一的退路，掉出去等于没有
   * （这一页已经为同一件事立过两条 `@media(max-height:...)` 的规矩）。
   * 压缩规则见 `elder-v6.css` 的 `body[data-font-tier="huge"]`。 */
  document.body.dataset.fontTier = (scale >= 1.6) ? 'huge' : 'normal';
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

/** 「念得清不清」这一枚 pill 的两种落法。
 *
 * 抽出来是因为它有**两个**调用点，而第二个是这一轮驱动出来的：
 * HTML 里的初值是「正在检查念得清不清…」——一句关于**正在发生什么**的断言。
 * 它只有在 `loadVoiceMode()` 跑完之后才会被换掉，而 `loadVoiceMode()` 排在
 * 启动链 `login → ensureSession → loadVoiceMode → …` 的第三位：前面任何一步
 * 失败，它就永远不会执行。
 *
 * 实测（CDP，`Network.setBlockedURLs` 拦掉所有接口 + 绕过 service worker，
 * 两页各三轮，结果一致）：屏幕上写着「正在检查念得清不清…」，20 秒后一个字
 * 没变，而检查早在第一秒就停了。这是答辩现场**最可能**出现的那一屏
 * （断网演示），而它在那一屏上说的是假话——旁边那三枚兄弟 pill 全是承诺，
 * 这一枚看起来像"还在跑"。
 *
 * 启动链断掉时的真话是哪一句？就是 `available === false` 这一支：接口都够不着，
 * 神经语音当然也够不着，念给她听的只会是这台手机自带的声音。所以启动链的
 * `.catch` 直接落这一支，而不是另写一句"检查失败了"——同一件事只有一个说法。
 *
 * 隔壁 `#semanticPill` 不需要这一手：`loadSemanticMode()` 自己带 try/catch，
 * 而且它**不在**启动链里，单独调用（实测断网时它落在「这项暂时查不到」）。
 */
/* 参数是 `probeNeuralVoice()` 的返回值本身（`{available}`），不是一个裸布尔。
   两个理由，第二个是硬的：
   ① 调用方读起来就是"探针说了什么"，启动链断掉时传 `{available: false}`
      的含义正是"探到的结果只可能是这个"；
   ② `test_app_surface_speaks_no_engineering.test_the_widened_vocabulary_catches_
      what_actually_shipped` 把下面这一行**逐字**当作变异锚点——它拿真的显示过的
      那句「语音：离线本地合成」替换进来，验证那道闸门抓得住。抽函数的时候我把
      `status.available` 改成了 `available`，那条闸门当场红在"锚点找不到了"上。
      锚点写死是它有意为之（那一行就是当年泄漏的原文），所以这里迁就它，
      不去改它。 */
function paintVoicePill(status) {
  const pill = document.querySelector('#voicePill');
  if (!pill) return;
  // 这一段的标题是「优活怎么保护您」，旁边三个兄弟是「一次只问一件事」
  // 「要紧的事请您念一遍」「不会自动扣钱」——全是**对她的承诺**。
  // 原先这两条写的是「语音：离线本地合成」和「语义层：离线确定性」，是**对我的描述**。
  // HTML 里的占位符其实早就是产品话了，是 JS 把它盖掉的：有人修了模板没修脚本，
  // 而屏幕上活着的是脚本那一版。
  //
  // 事实一个字没改，只是换成她这一侧的说法。工程说法在 /judge 与 /trust 有完整版本
  // （那是手机框**外**，读者是评委）——这里是换地方，不是删掉。
  //
  // 声音来自云端（晓晓）时，「说话不出这台手机」就是假话了：要念的那句话确实发出去了。
  // 所以这一支先落，说清楚发出去的是什么、没发出去的是什么。`where` 见 `/v6/speech/voice`。
  if (status.available && status.where === 'cloud') {
    pill.textContent = '用更像真人的声音念';
    pill.title = '念给您听的话会交给外面的语音服务变成声音；您自己说的话不经过它。';
    return;
  }
  pill.textContent = status.available ? '说话不出这台手机' : '用手机自带的声音念';
  pill.title = status.available
    ? '念给您听的声音在这台手机上生成，您说的话不会传出去。'
    : '用手机自带的声音念给您听。';
}

/** Probe the offline voice once logged in; silently keeps browser speech if absent. */
async function loadVoiceMode() {
  // 每次现取，而不是闭包捕获一个当时的值：401 重放换了令牌之后，捕获的那个就是
  // 过期的，而音频流失败只会表现成"这句没读出来"。
  // `onStatus`：服务器冷启动时第一探可能还没连上好声音，之后说话时会顺手再探，
  // 探到了这枚标签跟着换（见 speech.js 的 `REPROBE_MS`）。
  configureNeuralVoice({getToken: () => window.YouHuo.token('elder'), onStatus: paintVoicePill});
  await probeNeuralVoice();
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
  /* **只送这一屏真的有的那两个控件。**
   *
   * 原先这里把另外六个字段也写死送了出去（`max_options: 3`、
   * `max_sentence_chars: 42`、`repeat_sensitive: true`、
   * `teach_back_high_risk: true`、`hearing_support: false`、`verbosity: 'gentle'`），
   * 而 `PUT /v6/profiles` 那时是整行覆盖。实测：
   *
   *     她说「我听不清」 -> hearing_support=true, max_sentence_chars=24
   *     她按「保存我的习惯」 -> hearing_support=FALSE, max_sentence_chars=42
   *     屏幕上说：已保存。以后优活会按这个语速和文字大小与您沟通。
   *
   * 一句话盖住两种结果：「按你设的存好了」和「顺手把你刚要来的听力辅助关了」。
   * 一位老人开口说自己听不清，产品照做，然后她保存偏好，产品把它收了回去。
   *
   * 这一屏没有的控件就不该出现在这个载荷里——写死一个值等于替她做主。
   * 服务端已改成按送来的字段合并（`v6_store.upsert_profile`），
   * 没送的保持不变。
   */
  const profile = await api(`/v6/profiles/${ELDER_ID}`, {
    method: 'PUT', headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({
      elder_id: ELDER_ID,
      speech_rate: Number(speechRateEl.value),
      font_scale: Number(fontScaleEl.value)
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
    /* 「存下来」。
     *
     * 后端那句 `message` 一直在说「这份是您自己的，可以存下来，也可以给家人看」，
     * 卡片副标题也印着同一句，而在这之前**屏幕上没有任何存的办法**——
     * 全仓 `backend/static` 里一处 `Blob(` / `createObjectURL` / `download` 都没有。
     * 对一位老人那句话是「我该怎么存」，而答案是没有办法。
     *
     * 存的是「这份」——也就是 `renderCounts` 刚画的那一屏（类别名 + 条数），
     * 不是 58 行原始记录：那些行的字段名是 30 个英文、取值还有 `calm` / `checkup`
     * 这类英文枚举，倒进一个她要给家人看的文件里就是把工程输出当成她的数据。
     *
     * 实现在 `common.js`（三个界面共用一份），文件内容与屏幕逐行一致由判据钉住。
     */
    //: 这一层的朗读函数叫 `speak`，不是 `speakOut`（那是 `elder3.js` 的名字）。
    //: 第一版两处都写了 `speakOut`，这一处抛 ReferenceError，而下面那个 catch
    //: 把它说成「您的数据暂时看不了」——请求其实是 200。
    window.YouHuo.appendSaveMyData(host, data, speak);
  } catch (e) {
    /* 给她的话不变，但**真实错误要留下来**。
     *
     * 这一段原先只画那句「您的数据暂时看不了」。于是我在上面加的一行
     * 抛了 ReferenceError 时，屏幕说的是后端故障，而请求是 200——
     * 一个客户端 bug 被说成服务不可用，她按「再试一次」永远不会好。
     * 这个文件里 `console.error` 原先出现 0 次，所以这类错谁也看不到。
     */
    console.error('loadMyData', e);
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
//: **那个后端缺口已经补上了（2026-09-15 复测）。下面这段留着是为了记住它。**
//:
//: 当时的实测是：引擎只在**缴费**分支往响应的 `data` 里放 `task_type`，
//: 挂号走完四轮 `data` 里始终只有 `current_slots` 与 `missing`，所以这一行
//: 拿到的是 undefined——表再正确也没用，真正的修法在后端。
//:
//: 后来有一轮把它补在了 `_response()` 里（`engine.py:2115-2135`，
//: 那段注释自己写着「补在 `_response()` 而不是补那两个分支」，理由是
//: 「缺口本来就是一个分支记得、别的分支忘了造成的」）。逐轮复测：
//:
//:     挂号 8/8 轮   data.task_type = 'hospital_registration'
//:     提醒 前 5 轮  data.task_type = 'reminder'（第 6 轮是纯闲聊、没有任务）
//:     缴费 2/2 轮   data.task_type = 'bill_payment'
//:
//: 所以这一行现在真的能显示「正在办：挂号」。判据
//: `test_every_task_type_reaches_the_status_line.py` 钉住它——**一段说
//: 「这里还坏着」的注释本身会过期，而它过期时的方向是最坏的：
//: 它会让下一个人去修一个已经好了的东西，或者不再相信一块能用的界面。**
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
    /* 「需要您复述一遍」只在**她自己那一步**才成立，所以另开一个更窄的判断。
     *
     * 用 `asksForConfirmation` 的那一版把 `need_family_approval` 也算进来了，
     * 而那个码的意思正是「她已经复述确认过，现在等家人」。实测她说完
     * 「确认支付126.50元」之后 caption 是「等家人接力 · 需要您复述一遍」，
     * 而同一屏顶部写着「金额已经确认 正在等家人确认」、依赖卡写着
     * 「现在这一步：等家人接力」——三处里只有这一处在要求她重做。
     *
     * 而且下面那道去重守卫（第一段带「复述」就不追加）意味着
     * `need_elder_confirmation` 时这句话本来就会被挡掉（`CODE_WORD` 给的是
     * 「等您复述确认」）。也就是说旧条件**唯一能触发的场合正是它说假话的场合**。
     *
     * 不删这一支：万一第一段换成不带「复述」的 `CARE_WORD`，它仍然有用。
     * `asksForConfirmation` 本身不动——它还管依赖卡，那里两个码都该进。 */
    const asksHerToRepeat = data.code === 'need_elder_confirmation';
    // The code and the task state often say the same thing; show each idea once.
    const careWord = CARE_WORD[data.data?.care_intent];
    const metaParts = [careWord || CODE_WORD[data.code] || data.code];
    const stateWord = STATE_WORD[data.task_status];
    if (stateWord && !metaParts.includes(stateWord)) metaParts.push(stateWord);
    if (adapted.require_teach_back && asksHerToRepeat && !metaParts.some(p => p.includes('复述'))) {
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
 * `/v2/reminders` 现在有 `since` / `until` 了，而她不带窗口调用时服务端
 * 默认给一个下界（本地昨天零点，见 `api.py::list_reminders`），所以这一页
 * 本来就装着她今天和以后的事。**这里仍然要按日筛**：这一行的职责是
 * 「今天怎么样」，而「今天有 N 件事」的 N 必须是今天的件数，不是这一页的件数
 * ——页里还装着明天和昨天漏掉的那条。
 *
 * 「哪一天」按**北京时间**算（见 `wallClock`），不按设备时区。原先是
 * `new Date(iso).getDate()`，实测在一台 America/New_York 的设备上，今天那条
 * 被判成昨天、明天那条被判成今天——这一列于是装着别的一天的事。
 */
function isToday(iso) {
  const at = wallClock(iso);
  const now = wallClock(new Date());
  return at.year === now.year
    && at.month === now.month
    && at.day === now.day;
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

/* ---- 长期记忆的同意 ------------------------------------------------------
 *
 * 这一整块在 `/elder` 与 `/elder2` 上原先**不存在**。四条端点早就跑得通
 * （`/api/v1/memories` 的取、批、拒、忘），而全仓只有 `elder3.js` 一个消费者——
 * 于是家人提议要长期记住的那一条**永远停在待确认**：她看不见、也点不了，
 * 两边界面都正常，不报任何错。`test_elder3_memory_consent.py` 的文件头把这个
 * 缺陷的原貌记着，而那一轮只修了设计三。
 *
 * 形状照抄下面那个「待确认的药」：同一个位置、同一个「等您点头」的色、
 * 同一对写着字的按钮。这一页只有一个「等您决定」的地方，不另起一套。
 */
async function pendingMemories() {
  try {
    return await api('/api/v1/memories');
  } catch (e) {
    // 取不到就安静地当成没有，理由同 `pendingMedications()`：它是**额外**的一块，
    // 让它的失败挡住整屏待办是不划算的。
    return {pendingCount: 0, pending: [], items: [], count: 0, message: ''};
  }
}

function renderPendingMemories(data) {
  if (!remindersEl || !data.pendingCount) return;

  const decide = async (one, approve) => {
    try {
      const said = await api(
        `/api/v1/memories/${encodeURIComponent(one.id)}/${approve ? 'approve' : 'decline'}`,
        {method: 'POST', body: JSON.stringify({})});
      // 回执写状态行，理由同 `renderPendingMedications`：`#chat` 在 Focus Mode 里，
      // 而她按这个按钮时 Focus Mode 是关着的。
      setStatus(said.message);
      speak(said.message);
      loadReminders();
    } catch (e) {
      setStatus(window.YouHuo.errorWords(e, '这一条').text);
    }
  };

  /* 全部列出来，不像设计三那样一次只问一件。
   *
   * 设计三那一屏只有三个位置固定的 `.story-node` 和一条状态行，塞不进第二问，
   * 所以它一次问一件、下一件要她自己再点一下
   * （`test_only_one_question_is_asked_per_load` 钉着）。这一版的待办区是
   * **一张列表**，上面那些待确认的药也是全部列出来的——列表不是追问，
   * 她可以自己挑先看哪一条。 */
  data.pending.forEach((one) => {
    const div = document.createElement('div');
    div.className = 'task';
    const title = document.createElement('strong');
    title.textContent = one.key;
    const who = document.createElement('div');
    who.textContent = '家里人想让优活记住的';
    const what = document.createElement('div');
    what.textContent = window.YouHuo.noStop(one.detail);
    /* 要她点头就得说清三样：谁看得见、记多久、记它干什么。
     * 少任何一样，点头就只是点头，而屏幕上照样是一句通顺的话。
     * 这句用 `common.js` 的 `memoryWords()`——和设计三同一份，不另写一套。 */
    const terms = document.createElement('div');
    terms.textContent = window.YouHuo.memoryWords(one, true);
    const statusLine = document.createElement('div');
    const chip = document.createElement('span');
    // 和待确认的药同一档色：两边对「等一个人点头」用同一种视觉。
    chip.className = 'status-chip confirm';
    chip.textContent = '等您点头';
    statusLine.append('状态：', chip);
    div.append(title, who, what, terms, statusLine);

    const yes = document.createElement('button');
    yes.textContent = '可以记住';
    const no = document.createElement('button');
    no.textContent = '不用记';
    no.className = 'secondary';
    // 包在 `once()` 里：这一下要往返后端，而慢网络下连点两次的第二次会拿一条
    // 已经处理过的提议去决定，后端会正确地拒绝，但屏幕上会闪一句错误，
    // 让人以为第一次没成功。
    yes.addEventListener('click', () => window.YouHuo.once(yes, () => decide(one, true)));
    no.addEventListener('click', () => window.YouHuo.once(no, () => decide(one, false)));
    div.append(yes, no);
    remindersEl.appendChild(div);
  });
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

/** 「查看全部」收起来。数据没到、或者根本没到过，屏幕上就不该有这句话。 */
function hideReminderToggle() {
  const toggle = document.querySelector('#toggleReminders');
  if (toggle) toggle.hidden = true;
}

async function loadReminders() {
  if (!remindersEl) return;
  try {
    // 两个一起取。待确认的药是**另一条流程**（家人加、她点头），
    // 和 `/v2/reminders` 没有先后依赖，串行只是白等一个往返。
    // 三个一起取。待确认的药和待确认的记忆都是**另一条流程**（家人提、她点头），
    // 和 `/v2/reminders` 没有先后依赖，串行只是白等两个往返。
    const [reminders, pending, memories] = await Promise.all([
      api('/v2/reminders?limit=50'),
      pendingMedications(),
      pendingMemories(),
    ]);
    renderTodayLine(reminders, pending.count);
    renderNextItem(reminders);
    renderTodayBlock(reminders, pending.count);
    remindersEl.replaceChildren();
    // 先放这两块，所以它们排在待办上面：这是**等她决定**的事，待办只是到点提醒。
    renderPendingMedications(pending);
    renderPendingMemories(memories);
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
        // 两个都要各自忙：她按「我知道了」的时候，「已完成」不该也跟着灰掉，
        // 而她按下的那一个必须立刻有反应。
        ack.onclick = () => window.YouHuo.once(ack, () => reminderAction(r.id, 'acknowledge'));
        done.onclick = () => window.YouHuo.once(done, () => reminderAction(r.id, 'complete'));
        div.append(ack, document.createTextNode(' '), done);
      }
      remindersEl.appendChild(div);
    });
    /* `!pending.count` 和 `!memories.pendingCount` 这两半都是必须的：
     * `emptyState` 会 replaceChildren，少一个「现在没有待办」就会把刚放上去的
     * 待确认卡片整个抹掉——而屏幕上同时说着「没有待办」和摆着一张
     * 要她点头的卡，本身也是自相矛盾。
     *
     * 第二半是补上去的：这一轮把长期记忆同意补到这两页之后，
     * 家人提的那一条确实渲染出来了，然后被这一句抹掉。
     * **当时 193 条判据全绿**，而屏幕上那张卡不存在；
     * 是在真浏览器里点开 `/elder2` 才看见的。
     * 上面那段注释已经把这个坑写清楚了，而我还是走进去了——
     * 所以现在有一条判据盯它（`test_the_empty_state_never_eats_a_pending_card`）。 */
    if (!visible.length && !pending.count && !memories.pendingCount) {
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
    // 「查看全部」得跟着一起收起来。
    // ......................................................................
    // 这个按钮的文字由上面那一行按**真实条数**写；在那之前，屏幕上是 HTML 里
    // 那句静态的「查看全部」——一句关于"下面还有更多"的断言，而此刻一条都没有。
    // 取数失败时这一行永远到不了，于是那句断言就留在屏幕上：`#reminders` 里写着
    // 「待办暂时看不了：家里网不通」，紧挨着一个「查看全部」。
    //
    // 实测（CDP 拦掉全部接口 + 绕过 service worker，三轮一致）：`/elder` 上它
    // `hidden=false`、盒子非零、文字是「查看全部」。`/elder2` 不会——那一页的
    // HTML 给它带了 `hidden`。两张皮在"没有数据时屏幕上说什么"这一条上不是同一个
    // 产品，而这一份逻辑是两页共用的，所以修在这里。
    hideReminderToggle();
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
    /* 哪些主体号**真的**打得开详情。
     *
     * 白名单里带主体号的不止任务：提醒是 `rem-…`、记忆是记忆号、
     * 紧急访问是 `breakglass-…`。而 `openTaskDetail()` 只在 `/v2/tasks`
     * 里找，找不到就渲染「没有找到这件事的记录。」——**而那条记录就在
     * 她正看着的这一屏上**，那句话读起来像系统把它弄丢了。
     *
     * `/elder3` 那一侧早就是这么挡的（`elder3.js:921` 先 `taskIds.has()`
     * 再决定这一行能不能点），它的注释引的还是下面这段话。照它来。
     *
     * 取不到清单就一个都不做成按钮：宁可少一个入口，不要一个说假话的入口。 */
    let taskIds = new Set();
    try {
      const tasks = await api('/v2/tasks?limit=100');
      taskIds = new Set((tasks || []).map(item => item.id));
    } catch (_) { /* 断网：下面一律按不可点处理 */ }
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
      const clickable = !!entry.about_id && taskIds.has(entry.about_id);
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

/* 主动作要有即时反馈，也要防重复。
 *
 * `once()` 同步设 `disabled` + `aria-busy="true"`，`components.css` 里
 * `button[aria-busy="true"]` 那条让它呼吸起来（`cursor: progress` + opacity 脉冲，
 * 与 `:disabled` 的「按不了」分得开）。在这之前，从按下到回话到达之间，
 * 屏幕上没有任何变化——她不知道有没有按上。
 *
 * 防重复不是附带的：连按两下会送出两条一样的话，聊天记录里出现两条她的气泡。
 */
const sendBtn = document.querySelector('#send');
sendBtn.addEventListener('click', () => window.YouHuo.once(sendBtn, () => send()));
// 她开始打字了：趁她打字的工夫让服务器把念话那条连接开好（见 speech.js `warmNeuralVoice`）。
input.addEventListener('focus', () => warmNeuralVoice());
input.addEventListener('keydown', e => {
  // `isComposing` 不是可选的。
  //
  // 中文输入法在合成期间照样派发 keydown（`key === 'Enter'`、`isComposing === true`）。
  // 老人用拼音打 "guahao" 后按 Enter 选字，此前会直接 send()——`input.value` 里是还没
  // 上屏的拼音串，于是「挂号」没打出去，取而代之是一次垃圾对话，而 send() 还会清空
  // 输入框、把输入法的合成状态一起打断。
  // Firefox 上这条是**唯一**的输入通道（没有 SpeechRecognition），所以这不是边角。
  if (e.isComposing || e.keyCode === 229) return;
  // 回车没有按钮可按，所以忙状态落在 `#send` 上——那是这条路上唯一可见的承诺。
  // 顺带也挡住了「按住回车不放」连发。
  if (e.key === 'Enter') window.YouHuo.once(sendBtn, () => send());
});
/* 忙在**她按的那一个**上，不是统一落在 `#send`。
 * 这四个是「今天吃药了吗」「药还够吃吗」「今天有什么事」「上次的血压」——
 * 让 `#send` 变忙而她按的那个毫无变化，正是这一条要修的毛病。 */
document.querySelectorAll('[data-text]').forEach(btn => btn.addEventListener(
  'click', () => window.YouHuo.once(btn, () => send(btn.dataset.text))));

document.querySelector('#companionEntry').addEventListener('click', () => {
  // 这两句会**当成她自己说的话**上屏：`send()` 里就是 `addBubble(text, 'user')`。
  // 所以按钮送出去的不能是触发词，得是一句她真会说的话——原先送的是「调用无忧伴」，
  // 于是聊天记录里出现一条她的气泡写着「调用」，一个编程动词。
  //
  // 「找无忧伴聊聊」照样命中：companion.py 的 COMPANION_REQUESTS 里有「找无忧伴」，
  // 匹配是 `any(phrase in text …)` 的子串匹配。「继续办事」同理（engine.py:1418）。
  window.YouHuo.once(document.querySelector('#companionEntry'),
    () => send(currentMode === 'companion' ? '继续办事' : '找无忧伴聊聊'));
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

/* 「更多提醒」这一下要往返一次后端再重渲染。
 *
 * 依据就在上面十行：`#logEntryLabel` 是**手写**的忙状态（先写「正在读取…」，
 * `.finally()` 里还原）。也就是说这一类读操作在这个文件里本来就被当成需要反馈的，
 * 只有这个开关漏了。这里用 `once()` 而不是再手写一份，是为了不再多一套说法。 */
const toggleReminders = document.querySelector('#toggleReminders');
toggleReminders.addEventListener('click', () => window.YouHuo.once(
  toggleReminders, () => {
    showAllReminders = !showAllReminders;
    return loadReminders();
  }));

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
  //: 这里原先是 `setStatus(e.message)`。
  //:
  //: `e` 在这条路上有两种来源：后端写的中文 detail，和 `fetch` 自己抛的
  //: `TypeError: Failed to fetch`。第二种没有 `.status`，洗不掉，而它会原样
  //: 落进状态行——`#status` 带 `role="status" aria-live="polite"`，读屏会把
  //: 「Failed to fetch」念给一位老人听。
  //:
  //: 实测（CDP `Network.setBlockedURLs` 只拦 v6 档案那条路，通配两端各加一个
  //: 星号，也就是 `v6/profiles` 这一段；按下「保存我的习惯」）：
  //: `/elder` 与 `/elder2` 的 `#status` 都是 `'Failed to fetch'`，一字不差。
  //:
  //: 这里原先把那个通配串**原样**写在行注释里。星号紧贴斜杠，于是这一行凑出了
  //: 块注释的开记号和闭记号各一个——凡是「先用正则把块注释整段剥掉」的判据，
  //: 扫到这一行就从这里开始当块注释吃，一直吃到文件后面下一个闭记号为止，
  //: 中间几百行代码在它眼里根本不存在。那种判据不会报错，它会**报绿**。
  //: 判据在 `test_the_clock_on_screen_comes_from_the_server.py`。
  //:
  //: `test_consumer_errors_are_typed_not_raw.py` 看不到这一处：它的判据是
  //: `\bcatch\s*\(\s*(名字)\s*\)\s*\{`，只认 **catch 语句**。而这里是
  //: `.catch(e => …)` ——一个方法调用加箭头函数，`catch(e` 后面跟的是 `=>`
  //: 不是 `)`，正则不匹配。全仓这个形状只有两处，都在这个文件里，
  //: 都是这一轮量出来的。新判据在
  //: `test_elder_one_two_says_only_true_things.py`。
  //:
  //: 用 `say` / `then` 自己拼而不是 `text`：`errorWords(e, subject).text` 的
  //: 模板是「{主语}暂时**看不了**：…」，而这一步是"保存"，不是"看"。
  // 「保存我的习惯」要有即时反馈，也要防连点：这一步往返一次后端，
  // 而在这之前按下去到 `#status` 出现之间，那个按钮毫无变化。
  window.YouHuo.once(document.querySelector('#saveProfile'), saveProfile).catch(e => {
    const words = window.YouHuo.errorWords(e);
    setStatus(`没能保存：${words.say}。${words.then}`);
  });
});

/** 已经记住的那些，一条一条摊开，每条都能收回。
 *
 * `/elder3` 上这一屏叫「我答应让优活记住的事」，而 `/elder` 与 `/elder2` 上
 * 原先没有它——她只能一次删掉全部（`#eraseStart`），不能收回其中一条。
 * 「可撤回」是「同意」成立的前提，所以这一屏和点头一样只有她本人做得了：
 * 后端对家人的令牌回 403。
 *
 * @param notice 上一步的回执，放在最前面。只印那一句的话，她看不出这一条
 *               真的从单子上下去了——「说办好了」和「办好了」是两件事。
 */
async function loadMemories(notice) {
  const host = document.querySelector('#memoriesBody');
  if (!host) return;
  try {
    const data = await api('/api/v1/memories');
    host.replaceChildren();
    if (notice) {
      const done = document.createElement('p');
      done.textContent = notice;
      host.appendChild(done);
    }
    const lead = document.createElement('p');
    lead.textContent = data.message || '';
    host.appendChild(lead);

    if (data.pendingCount) {
      /* `data.message` 里已经有件数了（「有 1 件事想记下来，等您点头。」）。
       *
       * 下面这一句只在**列表非空**时才能说「还有 N 件」（在这些之外）。
       * 列表为空时那么写会把同一个数说两遍，而「还有」还暗示存在一份
       * 并不存在的清单——实测屏幕上是：「有 1 件事想记下来，等您点头。
       * 还有 1 件想记的事，在「首页」那一屏等您点头。」
       *
       * `askAboutPendingMemory()` 上那段注释已经把这个坑写过一次
       * （「同一个数说两遍，实测读起来像是三件事」）。 */
      const waiting = document.createElement('p');
      waiting.className = 'meta';
      waiting.textContent = (data.count
        ? `还有 ${data.pendingCount} 件想记的事，`
        : '想记下来的那些，') + '在「首页」那一屏等您点头。';
      host.appendChild(waiting);
    }

    (data.items || []).forEach((m) => {
      const row = document.createElement('div');
      row.className = 'task';
      const key = document.createElement('strong');
      key.textContent = m.key;
      row.appendChild(key);
      const detail = document.createElement('div');
      detail.textContent = window.YouHuo.noStop(m.detail);
      row.appendChild(detail);
      const meta = document.createElement('div');
      meta.textContent = window.YouHuo.memoryWords(m, false);
      row.appendChild(meta);
      const drop = document.createElement('button');
      drop.type = 'button';
      drop.className = 'secondary';
      drop.textContent = '不再记这条';
      // 第一步**不发任何写请求**：它只是把要收回的那一条摊开给她看。
      // 所以这里不用 `once()`——它不往返后端，没有可连点两次的东西。
      drop.addEventListener('click', () => startForget(m));
      row.appendChild(drop);
      host.appendChild(row);
    });
    host.hidden = false;
  } catch (e) {
    host.replaceChildren();
    const p = document.createElement('p');
    p.textContent = window.YouHuo.errorWords(e, '优活记着的事').text;
    host.appendChild(p);
    host.hidden = false;
  }
}

/** 收回一条已经记住的。**两步**，第二个按钮一开始不存在于 DOM 里。
 *
 * 和「删掉优活记下的这些」同一个规矩：一个一直摆在那里的「确认」会让人以为
 * 「点两下就没了」，而它在看到要收回的是哪一条之前根本不该存在——
 * 不是 disabled，也不是 hidden，是不存在。
 */
function startForget(item) {
  const host = document.querySelector('#memoriesBody');
  if (!host) return;
  host.replaceChildren();

  const lead = document.createElement('p');
  lead.textContent = `要让优活忘掉的是「${item.key}」：`
    + `${window.YouHuo.noStop(item.detail)}。`;
  host.appendChild(lead);
  const why = document.createElement('p');
  why.className = 'meta';
  why.textContent = window.YouHuo.memoryWords(item, false);
  host.appendChild(why);
  const keep = document.createElement('p');
  keep.className = 'meta';
  keep.textContent = '忘掉之后优活不会再用这一条；别的记着的事不动。';
  host.appendChild(keep);

  const confirm = document.createElement('button');
  confirm.type = 'button';
  confirm.className = 'danger';
  confirm.textContent = `确认不再记「${item.key}」`;
  confirm.addEventListener('click', () => window.YouHuo.once(confirm, async () => {
    try {
      const done = await api(
        `/api/v1/memories/${encodeURIComponent(item.id)}/forget`,
        {method: 'POST', body: '{}'});
      // 重列一遍，回执放最前面：她要看见这一条真的从单子上下去了。
      await loadMemories(done.message);
      speak(done.message);
    } catch (e) {
      const p = document.createElement('p');
      p.textContent = window.YouHuo.errorWords(e, '这一条').text;
      host.appendChild(p);
    }
  }));
  host.appendChild(confirm);

  const cancel = document.createElement('button');
  cancel.type = 'button';
  cancel.className = 'secondary';
  cancel.textContent = '还是记着吧';
  cancel.addEventListener('click', () => window.YouHuo.once(cancel, () => loadMemories()));
  host.appendChild(cancel);
  host.hidden = false;
}

// 「我的数据」那五个。全部包在 `once()` 里：这几个都要往返一次后端，
// 而慢网络下连点两次「删掉」是不可接受的——第二次会拿一个已经用过的令牌
// 去删一份已经不存在的数据，后端会正确地拒绝，但屏幕上会闪一句错误，
// 让人以为第一次没成功。
[['#moodReview', loadMoodReview],
 ['#dayReport', loadDayReport],
 ['#myData', loadMyData],
 ['#memories', loadMemories],
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
  // 语音这条也没有按钮，同回车：忙落在 `#send` 上。
  rec.onresult = e => {
    input.value = e.results[0][0].transcript;
    window.YouHuo.once(sendBtn, () => send());
  };
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
    // 她开口要说几秒：趁这几秒让服务器把念话那条连接开好，回答出来第一句不用再等握手。
    warmNeuralVoice();
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
  // 听不了语音的时候，**一进来就说**，而不是等她按了麦克风才说。
  //
  // 原先只在点击时写这句，空闲态的提示仍是「按一下，然后慢慢说」——在安卓模拟器上实测：
  // 她照着按，才被告知「这个浏览器不支持语音」。而在 App 里（`data-shell="app"`，
  // 见 app-bridge.js）说「浏览器」不对，那是一个 App。所以把**空闲态本身**改掉：
  // 之后每一次回到空闲（说完一句、办完一件），提示都还是这一句，不会被刷回去。
  const inApp = document.documentElement.dataset.shell === 'app';
  const noEars = inApp ? '这台手机听不了语音，请点下面打字' : '这个浏览器听不了语音，请点下面打字';
  ACTIVITY.idle.hint = noEars;
  ACTIVITY.idle.label = inApp ? '这台手机听不了语音，请用下面的打字' : '这个浏览器听不了语音，请用下面的打字';
  if (!document.body.dataset.activity || document.body.dataset.activity === 'idle') setActivity('idle');
  mic.addEventListener('click', () => {
    setMicHint(noEars);
    // 按了麦克风就是想说话：直接带她去能打字的地方。`/elder2` 的输入框在对话那一屏里，
    // 首页上看不见，光 `focus()` 什么也不会发生——走「用打字说」同一条路进去。
    const typeInstead = document.querySelector('#typeInstead');
    if (typeInstead) typeInstead.click();
    else input.focus();
  });
  mic.title = ACTIVITY.idle.label;
}

/* 装饰环把麦克风整个盖住了——把落在环上的点击交回给它。
   ..........................................................................
   `components.css` 的 `.mic-dial::before / ::after` 是两圈同心环
   （Voice Orb 十一态就画在它们的 border 上），`position: absolute`、
   `inset: 12px` 与 `inset: 0`。`::after` 是 `.mic-dial` 的**最后一个子节点**，
   而 `#mic` 是 `position: relative; z-index: auto`——同一个层叠上下文里按树序
   绘制，于是环画在按钮**上面**；两个伪元素都没有 `pointer-events: none`。

   实测（CDP，390×844 与 1280×900，各三轮，读数完全一致）：
     · 在 `#mic` 的盒子里取 15 个点，`elementFromPoint` **15 个全部**返回
       `div.mic-dial`；
     · 在正中心派发一次真实的 mousePressed/mouseReleased，`#mic` 上的
       click 处理器**一次都没跑**，`document.body.dataset.activity` 停在
       `idle`，`#micHint` 一个字没变。
   也就是说 `/elder` 上语音这条主路径**手指点不着**，而这一页没有第二个
   麦克风入口（设计二那个 `#focusMic` 是转交给这一个的，`/elder` 没有）。

   为什么此前没有任何闸门抓到：`check_page_runtime` / `check_dead_controls` /
   `test_elder_design2` 全都用 `element.click()` 派发合成事件，而合成事件
   **不做命中测试**——按钮被盖住和没被盖住，在它们眼里一模一样。

   设计二不受影响：`elder-v6.css` 给 `.mic-big` 写了 `z-index: 2`，同一支探针
   15 个点里 11 个命中按钮本身，真实点击也进得去。

   **真正的修法是一行 CSS**：给那两个伪元素加 `pointer-events: none`。
   `components.css` 是四层全局样式之一，不在这一轮可改的文件里，所以先在这里
   把点击转回去，并记进 KNOWN_ISSUES。`.mic-dial` 除了托住那两圈环没有别的
   职责，落在它上面的点击只可能是冲着中间那个按钮去的；附带效果是命中区从
   156px 扩到整圈 180px，对一位手抖的老人是好事。

   `event.target === ring` 挡住递归：`mic.click()` 派发的那次 click 冒泡回来时
   target 是 `#mic`，不是 `.mic-dial`。这一段对设计二是空操作（那一页的容器叫
   `.mic-orbit`，而且它本来就不需要）。 */
const micRing = mic && mic.closest('.mic-dial');
if (micRing) {
  micRing.addEventListener('click', event => {
    if (event.target === micRing) mic.click();
  });
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
  //: 钟点走 `wallClock`（北京时间），不走设备时区。
  //:
  //: 这里原先是 `pad(at.getHours())`。实测同一条提醒
  //: （due_at=2026-08-25T03:00:00Z，后端 /api/v1/agenda 给的是 11:00）：
  //: 一台 America/New_York 的设备上这张卡写 23:00，而山水版那一屏的同一条
  //: 写 11:00——同一个产品对同一件事说了两个时间。
  document.querySelector('#nextTime').textContent = wallClock(next.due_at).hhmm;
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
/* 这两个和上面那六处是同一件事：让**她按的那个控件**自己有反应。
 *
 * 要说实话：`send()` 在 await 之前已经同步做了四件看得见的事
 * （`setFocus(true)`、`addBubble()`、`setActivity('processing')`、`setStatus()`），
 * 重复提交也有 `turnInFlight` 挡着。所以这两处**不是**「按下去毫无反应」。
 * `once()` 在这里补的是另一半：状态行可能在屏幕下方、可能不在她的视野里，
 * 而她的手指就在这个按钮上。 */
const nextOpen = document.querySelector('#nextOpen');
nextOpen.addEventListener('click', () => window.YouHuo.once(nextOpen, () => {
  const title = document.querySelector('#nextTitle').textContent.trim();
  setFocus(true);
  return send(title ? `说说${title}这件事` : '我今天有什么事');
}));

const kinContact = document.querySelector('#kinContact');
kinContact.addEventListener('click', () => window.YouHuo.once(kinContact, () => {
  setFocus(true);
  return send('帮我联系家人');
}));

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
    /* **只留 `active`。** 原先写的是 `!== 'proposed'`，而状态一共三种
     * （`v4_store.py:849/924`：`"active" if approve else "rejected"`），
     * 挡了一种、漏了一种。实测：
     *
     *   家人提议「王先生 / 邻居 / *******1111」 -> proposed
     *   她 decide {approve:false}              -> rejected
     *   /v4/contacts/{elder} 如实回三条，屏幕上于是有三位——
     *   含她刚回绝的那一位，还带着电话。
     *
     * 这一屏的标题是「谁能帮您」，副标题写着「会先问您本人」。
     * 问了，她说不，然后他还在上面。
     *
     * 写成白名单而不是再挡一个 `rejected`：以后多一种状态也不会漏进来。
     * `ContactRecord.status` 是必填 `str`，不存在「老行没有 status
     * 被白名单误杀」；取不到接口时走的还是下面那条 fallback。
     *
     * 对照：老人端三读的 `/api/v1/contacts` 本来就不含被回绝的那一条。
     */
    const approved = (contacts || []).filter(c => c.status === 'active');
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
//:
//: 这是她见到的**第一句话**，也是三处能力目录里最要紧的一处。原先只举了
//: 挂号和缴费两种，提醒和填表两条线在开场时**根本没露过面**——而提醒是
//: 整个 App 判据最多的一条线。四种任务现在各有一个例子。
//:
//: **两份都要改。** `text` 上屏，`speak` 念出来；念的那一份没有引号，
//: 所以按「说『X』」取词的判据结构上看不见它。判据改成拿上屏那份里的
//: 每一个说法去比对念的那一份，两边不许少东西。
const GREETING = {
  youhuo: {
    text: '您好，我是优活。您可以直接说「帮我挂号」「查一下水费」「提醒我吃药」「帮我填表」，或者说「找无忧伴聊聊」。我会一次只问一件事。',
    speak: '您好，我是优活。您可以直接说帮我挂号、查一下水费、提醒我吃药、帮我填表，或者找无忧伴聊聊。',
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

// 屏幕上不许有"还没到过的状态"。
// ..........................................................................
// `#toggleReminders` 的静态文字是「查看全部」——一句"下面还有更多"的断言，
// 而此刻一条待办都还没取回来。`loadReminders()` 成功时会按真实条数改写它，
// 失败时（见那个 catch）也会收起来；这一行管的是**两者都还没发生**的那一段。
// `elder.js` 是 module（defer），HTML 解析完才执行，所以这一行之前那句话
// 确实已经画在屏幕上了。
hideReminderToggle();

async function startElderPage() {
  const appView = document.documentElement.classList.contains('app4-embedded') ? new URLSearchParams(location.search).get('view') : null;
  if (appView && ['habits','privacy'].includes(appView)) {
    await login();
    await loadProfile();
    if (appView === 'privacy') { loadSemanticMode(); loadVoiceMode().catch(() => paintVoicePill({available:false})); }
    return;
  }
  loadSemanticMode();
  await login();
  await ensureSession();
  await Promise.all([loadVoiceMode(),loadProfile(),loadReminders()]);
}
startElderPage()
  //: 这里原先是 `setStatus(e.message)`，和 `#saveProfile` 那一处同一个形状，
  //: 同一个原因（`.catch(e => …)` 不是 catch 语句，那道闸门看不见它）。
  //:
  //: 这一条更要紧：它是**启动链**。实测（CDP 拦掉全部接口 + 绕过 service
  //: worker，两页各三轮）——一位老人在断网的答辩现场打开这一页，
  //: `#status` 上写的第一句话就是「Failed to fetch」。
  //:
  //: 第二件事：链子断在第二步（`ensureSession`）时，第三步 `loadVoiceMode`
  //: 永远不会跑，于是「优活怎么保护您」里那枚 pill 永远停在
  //: 「正在检查念得清不清…」——实测 20 秒后一字未变。所以这里补一句
  //: `paintVoicePill(false)`：接口都够不着，念给她听的只会是这台手机自带的
  //: 声音，那正是这个函数 `false` 那一支说的话。
  .catch(e => {
    const words = window.YouHuo.errorWords(e);
    setStatus(`${words.say}。${words.then}`);
    paintVoicePill({available: false});
  }).finally(() => { document.documentElement.dataset.businessReadyElder = 'true'; document.dispatchEvent(new CustomEvent('app4:business-ready', {detail:'elder'})); });
