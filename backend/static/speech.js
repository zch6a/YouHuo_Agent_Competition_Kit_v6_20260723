/* Speech layer for the elder client.
 *
 * The robotic feel of the demo came mostly from the *text*, not the engine:
 * a synthesiser handed "2026-08-09 14:00" or "126.50元" reads it as digit soup
 * that an older listener cannot parse. This module does three things, all with
 * zero dependencies so the offline, no-API-key guarantee still holds:
 *
 *   1. Rewrites dates, times and amounts into how a person would say them.
 *   2. Picks the most natural installed zh-CN voice instead of the default.
 *   3. Speaks clause by clause with real pauses instead of one flat run.
 *
 * The same normalisation is what a HarmonyOS Core Speech or sherpa-onnx
 * backend would need, so none of it is throwaway.
 */

const DIGITS = ['零', '一', '二', '三', '四', '五', '六', '七', '八', '九'];

/** 0-99 the way it is spoken: 20 -> 二十, 15 -> 十五, 42 -> 四十二. */
function smallNumber(value) {
  const n = Number(value);
  if (!Number.isFinite(n) || n < 0) return String(value);
  if (n < 10) return DIGITS[n];
  if (n < 20) return n === 10 ? '十' : `十${DIGITS[n % 10]}`;
  const tens = Math.floor(n / 10);
  const ones = n % 10;
  if (n < 100) return `${DIGITS[tens]}十${ones ? DIGITS[ones] : ''}`;
  const hundreds = Math.floor(n / 100);
  const rest = n % 100;
  if (n < 1000) {
    if (!rest) return `${DIGITS[hundreds]}百`;
    if (rest < 10) return `${DIGITS[hundreds]}百零${DIGITS[rest]}`;
    return `${DIGITS[hundreds]}百${smallNumber(rest)}`;
  }
  // 千位以上继续读成中文，不退回裸数字。
  //
  // 这里原先是 `return String(n)`，于是 1200.00元 念成"1200块"——而这个模块存在的
  // 全部理由就是不让裸数字进合成器。失守的偏偏是最大的金额。更糟的是 7 位以上会被
  // 后面那条"号码逐位念"的规则接手：1000000.00元 变成"一零零零零零零块"。
  const thousands = Math.floor(n / 1000);
  const under = n % 1000;
  if (n < 10000) {
    const head = `${smallNumber(thousands)}千`;
    if (!under) return head;
    // 零在中文数字里是位缺失的标记："一千零五" 不等于 "一千五"（后者是 1500）。
    return under < 100 ? `${head}零${smallNumber(under)}` : `${head}${smallNumber(under)}`;
  }
  const wan = Math.floor(n / 10000);
  const belowWan = n % 10000;
  if (n < 100000000) {
    const head = `${smallNumber(wan)}万`;
    if (!belowWan) return head;
    return belowWan < 1000 ? `${head}零${smallNumber(belowWan)}` : `${head}${smallNumber(belowWan)}`;
  }
  return String(n);
}

/** Years are read digit by digit: 2026 -> 二零二六.
 *  Uses 零 rather than the typographic 〇, which is out of vocabulary for the
 *  offline neural voice and would be dropped silently. */
function yearDigits(year) {
  return String(year).split('').map(d => DIGITS[Number(d)]).join('');
}

/** Elderly-friendly clock: period word plus a 12-hour reading. */
function spokenTime(hour, minute) {
  const h = Number(hour);
  const m = Number(minute);
  let period;
  if (h < 6) period = '凌晨';
  else if (h < 12) period = '上午';
  else if (h < 13) period = '中午';
  else if (h < 18) period = '下午';
  else period = '晚上';
  let hour12 = h % 12;
  if (hour12 === 0) hour12 = 12;
  // 2点 is spoken 两点, never 二点.
  const hourWord = hour12 === 2 ? '两' : smallNumber(hour12);
  if (m === 0) return `${period}${hourWord}点`;
  if (m === 30) return `${period}${hourWord}点半`;
  return `${period}${hourWord}点${smallNumber(m)}分`;
}

function spokenDate(year, month, day, today = new Date()) {
  const sameYear = Number(year) === today.getFullYear();
  const head = sameYear ? '' : `${yearDigits(year)}年`;
  return `${head}${smallNumber(Number(month))}月${smallNumber(Number(day))}日`;
}

/** 126.50元 -> 一百二十六块五毛; 68.00元 -> 六十八块. */
function spokenMoney(amount) {
  const raw = String(amount).trim();
  // 负号不能丢。
  //
  // 原先的 money 正则和这个函数都不处理符号位，于是 "-68.40 元" 念成"六十八块四毛"
  // ——老人听到的是一个正数。退款、冲正、余额为负都会走到这里，而这个模块的存在
  // 就是为了让钱这件事听清楚。
  const negative = raw.startsWith('-') || raw.startsWith('−');
  const [yuanPart, centPart = ''] = raw.replace(/^[-−]/, '').split('.');
  const yuan = Number(yuanPart);
  const cents = Number((centPart + '00').slice(0, 2));
  const jiao = Math.floor(cents / 10);
  const fen = cents % 10;
  // 不足一块就不说"零块"：中文里 0.50 元就是"五毛"，"零块五毛"没人这么讲。
  let out = yuan === 0 && cents ? '' : `${smallNumber(yuan)}块`;
  // 角为 0 而分不为 0 时"零"不能省：9.05 念成"九块五分"会被听成九块五（= 9.50）。
  // 而这正好落在复述确认链上——老人重复她听到的数，后端判 mismatch，然后应用把
  // 自己说错的账算在她头上（"您说的是 9.5 元，账单是 9.05 元"）。
  if (jiao) out += `${smallNumber(jiao)}毛`;
  else if (fen) out += '零';
  if (fen) out += `${smallNumber(fen)}分`;
  return negative ? `负${out}` : out;
}

/** Digit by digit, the way phone numbers and ids are said: 1111 -> 一一一一. */
function spokenDigitRun(digits) {
  return String(digits).split('').map(d => DIGITS[Number(d)] ?? d).join('');
}

/** Units a synthesiser either spells out letter by letter or skips entirely. */
const UNITS = [
  [/(\d+(?:\.\d+)?)\s*mmHg/gi, (_, n) => `${n}毫米汞柱`],
  [/(\d+(?:\.\d+)?)\s*(?:℃|°C)/gi, (_, n) => `${n}摄氏度`],
  [/(\d+(?:\.\d+)?)\s*kg\b/gi, (_, n) => `${n}千克`],
  [/(\d+(?:\.\d+)?)\s*ml\b/gi, (_, n) => `${n}毫升`],
  [/(\d+(?:\.\d+)?)\s*mg\b/gi, (_, n) => `${n}毫克`],
  [/(\d+(?:\.\d+)?)\s*m\b/g, (_, n) => `${n}米`],
];

/* Decorative pairs carry no meaning aloud. Some engines announce them
   ("引号"), others break prosody around them; either way the elder hears
   punctuation instead of the thing being quoted. The characters stay in the
   *visible* bubble — only the spoken copy is stripped. */
const DECORATIVE = /[“”「」『』‘’"＂〈〉《》（）()【】\[\]]/g;

/**
 * Rewrite machine-formatted values into speakable Chinese.
 * Order matters: the most specific patterns run first so a datetime is not
 * half-consumed by the date rule, and the bare-digit rule runs last so it
 * cannot eat a year, a clock time or an amount.
 */
export function speakableText(text, today = new Date()) {
  if (!text) return '';
  let out = String(text);

  // 2026-08-09 14:00 (with optional seconds)
  out = out.replace(
    /(\d{4})-(\d{1,2})-(\d{1,2})[ T](\d{1,2}):(\d{2})(?::\d{2})?/g,
    (_, y, mo, d, h, mi) => `${spokenDate(y, mo, d, today)}${spokenTime(h, mi)}`,
  );
  // 2026-08-09
  out = out.replace(/(\d{4})-(\d{1,2})-(\d{1,2})/g, (_, y, mo, d) => spokenDate(y, mo, d, today));
  // 2026-08 (a billing period)
  out = out.replace(/(\d{4})-(\d{1,2})(?!\d)/g, (_, y, mo) => `${yearDigits(y)}年${smallNumber(Number(mo))}月`);
  // 14:00 on its own
  out = out.replace(/(?<!\d)(\d{1,2}):(\d{2})(?::\d{2})?(?!\d)/g, (_, h, mi) => spokenTime(h, mi));
  // 126.50元 / 68元
  // 符号位要一起吃进来，否则 spokenMoney 拿到的是去掉负号的数，"-68.40 元" 念成正数。
  out = out.replace(/([-−]?\d+(?:\.\d{1,2})?)\s*元/g, (_, amount) => spokenMoney(amount));
  // 35% -> 百分之三十五
  out = out.replace(/(\d+(?:\.\d+)?)\s*%/g, (_, n) => `百分之${n}`);
  for (const [pattern, replacer] of UNITS) out = out.replace(pattern, replacer);

  // Phone-shaped values. "尾号1111" is what the backend now says, and a bare run
  // of seven or more digits is an id or a number, never a quantity. Three-digit
  // values such as a blood pressure of 148 are deliberately left alone: those
  // *are* quantities and "一百四十八" is the correct reading.
  out = out.replace(/(尾号)\s*(\d{2,})/g, (_, head, digits) => `${head}${spokenDigitRun(digits)}`);
  out = out.replace(/(?<![\d.])(\d{7,})(?![\d.])/g, (_, digits) => spokenDigitRun(digits));

  // An ellipsis should be heard as a beat, not as dots.
  out = out.replace(/[.]{3,}|…+/g, '，');

  return out.replace(DECORATIVE, '');
}

/** Voices worth preferring, best first; matched loosely against voice names. */
const PREFERRED_VOICES = [
  'xiaoxiao', 'xiaoyi', 'yunxi', 'yunyang', 'huihui',   // Microsoft neural / desktop
  'tingting', 'meijia', 'sinji',                        // Apple
  'chinese (china)', 'zh-cn',                           // Chrome/Android generic
];

let cachedVoice = null;

/** Pick the most natural installed zh-CN voice rather than the browser default. */
export function pickVoice() {
  if (!('speechSynthesis' in window)) return null;
  if (cachedVoice) return cachedVoice;
  const voices = window.speechSynthesis.getVoices().filter(v => /^zh([-_]CN)?/i.test(v.lang));
  if (!voices.length) return null;
  const score = voice => {
    const name = `${voice.name} ${voice.voiceURI}`.toLowerCase();
    const rank = PREFERRED_VOICES.findIndex(hint => name.includes(hint));
    // Cloud "natural" voices sound markedly better when they are available.
    const natural = /natural|neural|online|premium|enhanced/.test(name) ? -100 : 0;
    return (rank === -1 ? PREFERRED_VOICES.length : rank) + natural;
  };
  cachedVoice = voices.slice().sort((a, b) => score(a) - score(b))[0];
  return cachedVoice;
}

export function resetVoiceCache() {
  cachedVoice = null;
}

/** Split into clauses so the delivery breathes instead of running flat. */
export function splitClauses(text) {
  return String(text)
    .split(/(?<=[。！？!?；;])|(?<=[，,、：:])/)
    .map(part => part.trim())
    .filter(Boolean);
}

/** 给服务器那条好听的声音用：**按句子切，不按逗号切**。
 *
 * 逗号那一刀是给手机自带声音用的——它一口气念长句会平、还会卡住不报结束。
 * 而把逗号切出来的小段逐个送去服务器念，每一小段都会被念成「一句话说完了」的降调，
 * 听起来一顿一顿的，正是这次要换掉的那种「不像人」。整句送过去，句中的停顿和语调
 * 由声音自己处理。只有超过 60 字的长句才在逗号处再切（一次送太长，第一声要等太久）。 */
export const SENTENCE_MAX_CHARS = 60;
export function splitSentences(text) {
  const out = [];
  for (const piece of String(text).split(/(?<=[。！？!?；;])/)) {
    const sentence = piece.trim();
    if (!sentence) continue;
    if (sentence.length <= SENTENCE_MAX_CHARS) { out.push(sentence); continue; }
    let buf = '';
    for (const part of sentence.split(/(?<=[，,、：:])/)) {
      if (buf && (buf + part).length > SENTENCE_MAX_CHARS) { out.push(buf.trim()); buf = ''; }
      buf += part;
    }
    if (buf.trim()) out.push(buf.trim());
  }
  return out;
}

/** Pause after a clause, in milliseconds, based on how it ended.
 *
 * An enumeration comma (、) separates items in one breath and wants a shorter
 * gap than a sentence comma, or a read-back list of dose times sounds like four
 * unrelated sentences. */
function pauseAfter(clause) {
  if (/[。！？!?]$/.test(clause)) return 320;
  if (/[；;]$/.test(clause)) return 240;
  if (/、$/.test(clause)) return 90;
  return 140;
}

/* ---------------------------------------------------------------- neural voice */

/** null until probed; then true/false. The probe never blocks the first turn. */
let neuralAvailable = null;
let lastProbeAt = 0;
let authTokenProvider = () => null;
let statusListener = null;

/** 没探到好声音时，隔多久再探一次（只在要说话时顺手探，不另起定时器）。
 *
 * 公网那台服务器会冷启动：第一个打开页面的人把它叫醒，页面那一探可能赶在服务器
 * 自己连上声音服务之前，于是整段对话都用手机自带的声音。所以「不可用」不是定论，
 * 过一会儿再问一次；探到了，下一句就换成好听的那个。 */
const REPROBE_MS = 20_000;

/** The elder client supplies its bearer token; synthesis is an authorised call.
 * `onStatus` 每探一次都会被叫一次，页面据此刷新那枚「怎么念给您听」的小标签。 */
export function configureNeuralVoice({getToken, onStatus = null}) {
  authTokenProvider = getToken || (() => null);
  statusListener = onStatus;
}

export async function probeNeuralVoice() {
  lastProbeAt = Date.now();
  let status;
  try {
    const token = authTokenProvider();
    const response = await fetch('/v6/speech/voice', {
      headers: token ? {Authorization: `Bearer ${token}`} : {},
    });
    if (!response.ok) throw new Error(String(response.status));
    status = await response.json();
    neuralAvailable = Boolean(status.available);
  } catch (_) {
    neuralAvailable = false;
    status = {available: false};
  }
  if (statusListener) {
    try { statusListener(status); } catch (_) { /* 标签刷新失败不影响念 */ }
  }
  return status;
}

/** 她按下麦克风、或开始打字时叫一下：服务器趁她说话的工夫把念话那条连接开好。
 *
 * 只在好声音可用时叫；20 秒内只叫一次（服务器那边 30 秒内的连接都还能用）。
 * 失败无所谓——念的时候服务器照常新开。 */
let lastWarmAt = 0;
export function warmNeuralVoice() {
  if (!neuralAvailable || Date.now() - lastWarmAt < 20_000) return;
  lastWarmAt = Date.now();
  const token = authTokenProvider();
  fetch('/v6/speech/warm', {
    method: 'POST',
    headers: token ? {Authorization: `Bearer ${token}`} : {},
  }).catch(() => {});
}

/* 同一个播放器反复用，并在她第一次点屏幕时「解锁」它。
 *
 * iPhone 的规矩是：一个播放器第一次出声必须发生在手指点击的那一刻。而回答是
 * 点完之后隔一两秒才从服务器回来的——每句 `new Audio()` 都是一个没解锁过的新播放器，
 * 于是在 iPhone 上好听的那条每句都失败、退回手机自带的声音。
 * 解锁用一小段现做的静音（在页面里拼出来的，不是去外面取的，页面的安全规矩允许）。 */
let sharedAudio = null;
let audioUnlocked = false;

function audioElement() {
  if (!sharedAudio) sharedAudio = new Audio();
  return sharedAudio;
}

function silentClipUrl() {
  const samples = 800;                       // 8kHz 下 0.1 秒
  const buffer = new ArrayBuffer(44 + samples);
  const view = new DataView(buffer);
  const tag = (offset, text) => {
    for (let i = 0; i < text.length; i += 1) view.setUint8(offset + i, text.charCodeAt(i));
  };
  tag(0, 'RIFF'); view.setUint32(4, 36 + samples, true); tag(8, 'WAVE');
  tag(12, 'fmt '); view.setUint32(16, 16, true); view.setUint16(20, 1, true);
  view.setUint16(22, 1, true); view.setUint32(24, 8000, true); view.setUint32(28, 8000, true);
  view.setUint16(32, 1, true); view.setUint16(34, 8, true);
  tag(36, 'data'); view.setUint32(40, samples, true);
  new Uint8Array(buffer, 44).fill(128);      // 8 位无符号 PCM 的静音是 128
  return URL.createObjectURL(new Blob([buffer], {type: 'audio/wav'}));
}

function unlockAudioOnce() {
  if (audioUnlocked) return;
  audioUnlocked = true;
  const audio = audioElement();
  if (!audio.paused) return;                 // 已经在念了，说明早就能出声
  const url = silentClipUrl();
  audio.src = url;
  audio.play().then(() => URL.revokeObjectURL(url)).catch(() => {
    URL.revokeObjectURL(url);
    audioUnlocked = false;                   // 这一下没解开，下一次点击再试
  });
}

if (typeof window !== 'undefined' && window.addEventListener) {
  for (const type of ['pointerdown', 'touchend', 'keydown']) {
    window.addEventListener(type, unlockAudioOnce, {capture: true, passive: true});
  }
}

const audioCache = new Map();

async function fetchClauseAudio(clause, speed) {
  const key = `${speed.toFixed(2)}|${clause}`;
  if (audioCache.has(key)) return audioCache.get(key);
  const token = authTokenProvider();
  const response = await fetch('/v6/speech/synthesize', {
    method: 'POST',
    headers: {'Content-Type': 'application/json', ...(token ? {Authorization: `Bearer ${token}`} : {})},
    body: JSON.stringify({text: clause, speed}),
  });
  if (!response.ok) throw new Error(`tts ${response.status}`);
  const url = URL.createObjectURL(await response.blob());
  audioCache.set(key, url);
  // The demo repeats the same prompts constantly; keep the cache small anyway.
  if (audioCache.size > 60) {
    const oldest = audioCache.keys().next().value;
    URL.revokeObjectURL(audioCache.get(oldest));
    audioCache.delete(oldest);
  }
  return url;
}

/** Raised when the neural voice fails partway, so only the rest is re-spoken. */
class NeuralVoiceFailure extends Error {
  constructor(clauseIndex, cause) {
    super(cause?.message || 'neural voice failed');
    this.clauseIndex = clauseIndex;
  }
}

/** Play clauses through the offline neural voice, prefetching the next one. */
async function playNeural(clauses, speed, state) {
  let pending = fetchClauseAudio(clauses[0], speed);
  for (let i = 0; i < clauses.length; i += 1) {
    if (state.cancelled) return;
    let url;
    try {
      url = await pending;
    } catch (error) {
      // Resume from this clause rather than restarting the whole sentence.
      throw new NeuralVoiceFailure(i, error);
    }
    if (state.cancelled) return;
    // Start fetching the following clause while this one plays. Failures are
    // deferred to the iteration that awaits them, so the index stays correct.
    pending = i + 1 < clauses.length ? fetchClauseAudio(clauses[i + 1], speed) : null;
    if (pending) pending.catch(() => {});
    try {
      const audio = audioElement();
      state.audio = audio;
      // A rejected play() means autoplay policy or no output device.
      await new Promise((resolve, reject) => {
        audio.onended = resolve;
        audio.onerror = () => reject(new Error('audio decode failed'));
        audio.src = url;
        audio.play().catch(reject);
      });
    } catch (error) {
      throw new NeuralVoiceFailure(i, error);
    }
    if (state.cancelled) return;
    await new Promise(resolve => {
      state.timer = window.setTimeout(resolve, pauseAfter(clauses[i]));
    });
  }
}

/** Browser speech synthesis: always available, used when the neural voice is not. */
function playBrowser(clauses, {rate, pitch}, state, onFinish = null) {
  if (!('speechSynthesis' in window)) { if (onFinish) onFinish(); return; }
  const synth = window.speechSynthesis;
  synth.cancel();
  const voice = pickVoice();
  const speakFrom = index => {
    if (state.cancelled) return;
    if (index >= clauses.length) { if (onFinish) onFinish(); return; }
    const utterance = new SpeechSynthesisUtterance(clauses[index]);
    utterance.lang = 'zh-CN';
    utterance.rate = rate;
    utterance.pitch = pitch;
    if (voice) utterance.voice = voice;
    utterance.onend = () => {
      if (state.cancelled) return;
      state.timer = window.setTimeout(() => speakFrom(index + 1), pauseAfter(clauses[index]));
    };
    // If the engine errors on one clause, keep going rather than going silent.
    utterance.onerror = utterance.onend;
    synth.speak(utterance);
  };
  speakFrom(0);
}

/**
 * Speak text one clause at a time, preferring the offline neural voice and
 * falling back to the browser on any failure.
 * Returns a cancel function so a new turn can interrupt the previous one.
 */
export function speakClauses(text, {rate = 0.88, pitch = 1.0, today = new Date(), onDone = null} = {}) {
  const spoken = speakableText(text, today);
  const clauses = splitClauses(spoken);
  const state = {cancelled: false, timer: null, audio: null, finished: false};
  // 这一句照旧用手机的声音；顺手问一下服务器现在有没有好听的，下一句就能换过去。
  if (neuralAvailable === false && Date.now() - lastProbeAt > REPROBE_MS) {
    probeNeuralVoice();
  }

  /** 报一次「说完了」，且**只报一次**。
   *
   * 两条播放路径可能先后各走一遍——离线神经语音在第 N 句失败时会回落到浏览器合成
   * 把剩下的说完——但对调用方来说这仍然只是一次朗读。被 cancel 掉的不算说完：
   * 打断的那一方自己知道接下来要进什么状态，这里不该替它决定。 */
  const finish = () => {
    if (state.cancelled || state.finished) return;
    state.finished = true;
    if (onDone) onDone();
  };

  if (!clauses.length) { finish(); return () => {}; }

  const cancel = () => {
    state.cancelled = true;
    if (state.timer) window.clearTimeout(state.timer);
    if (state.audio) { state.audio.pause(); state.audio = null; }
    if ('speechSynthesis' in window) window.speechSynthesis.cancel();
  };
  cancel.__isCancel = true;

  if ('speechSynthesis' in window) window.speechSynthesis.cancel();

  if (neuralAvailable) {
    // 整句送去服务器念（见 `splitSentences`）；手机自带的声音仍按逗号切。
    const sentences = splitSentences(spoken);
    // Speed maps the profile's browser rate onto the model's speed factor.
    playNeural(sentences, Math.max(0.5, Math.min(2.0, rate)), state).then(finish).catch(error => {
      if (state.cancelled) return;
      // Resume from the sentence that failed so nothing is spoken twice.
      const from = Number.isInteger(error?.clauseIndex) ? error.clauseIndex : 0;
      console.warn(`好听的声音在第${from + 1}句失败，改用手机自带的声音：`, error?.message || error);
      playBrowser(splitClauses(sentences.slice(from).join('')), {rate, pitch}, state, finish);
    });
  } else {
    playBrowser(clauses, {rate, pitch}, state, finish);
  }

  return cancel;
}
