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
  const [yuanPart, centPart = ''] = String(amount).split('.');
  const yuan = Number(yuanPart);
  const cents = Number((centPart + '00').slice(0, 2));
  const jiao = Math.floor(cents / 10);
  const fen = cents % 10;
  let out = `${smallNumber(yuan)}块`;
  if (jiao) out += `${smallNumber(jiao)}毛`;
  if (fen) out += `${smallNumber(fen)}分`;
  return out;
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
  out = out.replace(/(\d+(?:\.\d{1,2})?)\s*元/g, (_, amount) => spokenMoney(amount));
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
let authTokenProvider = () => null;

/** The elder client supplies its bearer token; synthesis is an authorised call. */
export function configureNeuralVoice({getToken}) {
  authTokenProvider = getToken || (() => null);
}

export async function probeNeuralVoice() {
  try {
    const token = authTokenProvider();
    const response = await fetch('/v6/speech/voice', {
      headers: token ? {Authorization: `Bearer ${token}`} : {},
    });
    if (!response.ok) throw new Error(String(response.status));
    const status = await response.json();
    neuralAvailable = Boolean(status.available);
    return status;
  } catch (_) {
    neuralAvailable = false;
    return {available: false};
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
      const audio = new Audio(url);
      state.audio = audio;
      // A rejected play() means autoplay policy or no output device.
      await new Promise((resolve, reject) => {
        audio.onended = resolve;
        audio.onerror = () => reject(new Error('audio decode failed'));
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
function playBrowser(clauses, {rate, pitch}, state) {
  if (!('speechSynthesis' in window)) return;
  const synth = window.speechSynthesis;
  synth.cancel();
  const voice = pickVoice();
  const speakFrom = index => {
    if (state.cancelled || index >= clauses.length) return;
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
export function speakClauses(text, {rate = 0.88, pitch = 1.0, today = new Date()} = {}) {
  const clauses = splitClauses(speakableText(text, today));
  const state = {cancelled: false, timer: null, audio: null};
  if (!clauses.length) return () => {};

  const cancel = () => {
    state.cancelled = true;
    if (state.timer) window.clearTimeout(state.timer);
    if (state.audio) { state.audio.pause(); state.audio = null; }
    if ('speechSynthesis' in window) window.speechSynthesis.cancel();
  };
  cancel.__isCancel = true;

  if ('speechSynthesis' in window) window.speechSynthesis.cancel();

  if (neuralAvailable) {
    // Speed maps the profile's browser rate onto the model's speed factor.
    playNeural(clauses, Math.max(0.5, Math.min(2.0, rate)), state).catch(error => {
      if (state.cancelled) return;
      // Resume from the clause that failed so nothing is spoken twice.
      const from = Number.isInteger(error?.clauseIndex) ? error.clauseIndex : 0;
      console.warn(`离线语音在第${from + 1}句失败，回落到浏览器语音：`, error?.message || error);
      playBrowser(clauses.slice(from), {rate, pitch}, state);
    });
  } else {
    playBrowser(clauses, {rate, pitch}, state);
  }

  return cancel;
}
