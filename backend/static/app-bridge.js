/* 优活安卓 App 外壳的网页一侧。
 *
 * 在普通浏览器里**什么都不做**（没有 `window.YouhuoNative` 就直接返回）。
 * 在 App 里（android/src/com/youhuo/app/NativeBridge.java 注入 `YouhuoNative`），
 * 补上安卓网页视图缺的三样，而且补成浏览器原本的样子，页面一个字不用改：
 *
 *   1. `speechSynthesis` / `SpeechSynthesisUtterance`
 *      —— 用手机自带的朗读引擎。平时念话走的是服务器那条好听的声音（speech.js），
 *         这一条是它连不上时的兜底；安卓网页视图自己的这两个是空壳，不补就没声音。
 *   2. `SpeechRecognition` / `webkitSpeechRecognition`
 *      —— 用手机的语音识别。网页视图没有这个接口，不补的话麦克风按钮会说
 *         「这个浏览器不支持语音」。手机上没装识别服务（有些国产机）就不补，
 *         页面照旧退回打字——那句话在那种手机上是真话。
 *   3. `a[download]` 的「存一份」
 *      —— 网页视图不接这种下载，交给外壳写进手机的「下载」。
 *
 * 必须在页面其它脚本**之前**加载（放在 <head> 里，不加 defer）：elder.js 在加载时
 * 就判断有没有语音识别。
 *
 * 行为对齐 Chrome：`cancel()` 会让正在念的那句报 `interrupted`、排队的报 `canceled`
 * （异步报）——这个项目的朗读代码是照着 Chrome 写的，对齐它最不容易出岔子。
 */
(function () {
  'use strict';
  var N = window.YouhuoNative;
  if (!N || window.__youhuoBridge) return;

  var seq = 0;
  function nextId(prefix) { seq += 1; return prefix + seq; }
  function later(fn) { window.setTimeout(fn, 0); }

  var bridge = window.__youhuoBridge = {
    utterances: {},
    recognizers: {},
    ttsReady: function () {},
    ttsEvent: function () {},
    asrEvent: function () {}
  };

  // 页面可以据此知道自己在 App 里（例如不再提示「添加到桌面」）。
  document.documentElement.setAttribute('data-shell', 'app');
  // Keep native background reminders in the same account and mode as this
  // top-level page. Embedded care pages must not switch the native role.
  if (window.top === window && typeof N.syncSession !== 'undefined') {
    document.addEventListener('DOMContentLoaded', function () {
      var role = location.pathname.indexOf('/family') === 0 ? 'family' : 'elder';
      if (window.YouHuo && window.YouHuo.login) {
        window.YouHuo.login(role).then(function () {
          var token = window.YouHuo.token(role);
          if (token) N.syncSession(role, token);
        }).catch(function () {});
      }
    });
  }

  /* ---------------------------------------------------------------- 事件小工具 */
  function Emitter() { this._listeners = {}; }
  Emitter.prototype.addEventListener = function (type, fn) {
    (this._listeners[type] = this._listeners[type] || []).push(fn);
  };
  Emitter.prototype.removeEventListener = function (type, fn) {
    var list = this._listeners[type];
    if (!list) return;
    var i = list.indexOf(fn);
    if (i >= 0) list.splice(i, 1);
  };
  Emitter.prototype._emit = function (type, extra) {
    var event = {type: type, target: this, currentTarget: this, timeStamp: Date.now()};
    if (extra) for (var key in extra) event[key] = extra[key];
    var handlers = [];
    if (typeof this['on' + type] === 'function') handlers.push(this['on' + type]);
    handlers = handlers.concat((this._listeners[type] || []).slice());
    for (var i = 0; i < handlers.length; i += 1) {
      try { handlers[i].call(this, event); } catch (err) { later(function () { throw err; }); }
    }
  };

  /* ---------------------------------------------------------------- 1. 朗读 */
  function Utterance(text) {
    Emitter.call(this);
    this.text = text == null ? '' : String(text);
    this.lang = 'zh-CN';
    this.rate = 1;
    this.pitch = 1;
    this.volume = 1;
    this.voice = null;
    this.onstart = null; this.onend = null; this.onerror = null;
    this.onpause = null; this.onresume = null; this.onboundary = null; this.onmark = null;
  }
  Utterance.prototype = Object.create(Emitter.prototype);
  Utterance.prototype.constructor = Utterance;

  var VOICE = {name: '手机自带的声音', lang: 'zh-CN', voiceURI: 'youhuo-native',
               localService: true, default: true};
  var queue = [];
  var synth = new Emitter();
  synth.speaking = false;
  synth.pending = false;
  synth.paused = false;
  synth.onvoiceschanged = null;
  function refreshFlags() {
    synth.speaking = queue.length > 0;
    synth.pending = queue.length > 1;
  }
  synth.getVoices = function () { return [VOICE]; };
  synth.speak = function (utterance) {
    if (!utterance) return;
    var id = nextId('u');
    bridge.utterances[id] = utterance;
    queue.push(id);
    refreshFlags();
    try {
      N.speak(id, String(utterance.text || ''), Number(utterance.rate) || 1, Number(utterance.pitch) || 1);
    } catch (err) {
      bridge.ttsEvent(id, 'error');
    }
  };
  synth.cancel = function () {
    var dropped = queue.splice(0);
    refreshFlags();
    try { N.stopSpeaking(); } catch (err) { /* 引擎已经没了，就当停了 */ }
    dropped.forEach(function (id, index) {
      var utterance = bridge.utterances[id];
      delete bridge.utterances[id];
      if (utterance) {
        later(function () {
          utterance._emit('error', {error: index === 0 ? 'interrupted' : 'canceled', utterance: utterance});
        });
      }
    });
  };
  synth.pause = function () {};
  synth.resume = function () {};

  bridge.ttsEvent = function (id, type) {
    var utterance = bridge.utterances[id];
    if (!utterance) return;                    // 已经被 cancel 掉的那几句，引擎晚到的消息不理
    if (type === 'start') {
      utterance._emit('start', {utterance: utterance, charIndex: 0, elapsedTime: 0});
      return;
    }
    delete bridge.utterances[id];
    var i = queue.indexOf(id);
    if (i >= 0) queue.splice(i, 1);
    refreshFlags();
    if (type === 'end') utterance._emit('end', {utterance: utterance, charIndex: 0, elapsedTime: 0});
    else utterance._emit('error', {error: 'synthesis-failed', utterance: utterance});
  };
  bridge.ttsReady = function () { synth._emit('voiceschanged'); };

  var ttsOk = false;
  try { ttsOk = Boolean(N.ttsAvailable()); } catch (err) { ttsOk = false; }
  if (ttsOk) {
    try {
      Object.defineProperty(window, 'speechSynthesis', {value: synth, configurable: true, writable: true});
    } catch (err) {
      window.speechSynthesis = synth;
    }
    window.SpeechSynthesisUtterance = Utterance;
  }

  /* ---------------------------------------------------------------- 2. 听写 */
  function Recognition() {
    Emitter.call(this);
    this.lang = 'zh-CN';
    this.continuous = false;
    this.interimResults = false;
    this.maxAlternatives = 1;
    this.onstart = null; this.onend = null; this.onerror = null; this.onresult = null;
    this.onnomatch = null; this.onaudiostart = null; this.onaudioend = null;
    this.onspeechstart = null; this.onspeechend = null; this.onsoundstart = null; this.onsoundend = null;
    this._id = null;
  }
  Recognition.prototype = Object.create(Emitter.prototype);
  Recognition.prototype.constructor = Recognition;
  Recognition.prototype.start = function () {
    if (this._id) {
      // 和浏览器一样：已经在听的时候再 start 是个错误，调用方（elder.js）会接住。
      throw new DOMException('recognition has already started', 'InvalidStateError');
    }
    var id = nextId('r');
    this._id = id;
    bridge.recognizers[id] = this;
    try {
      N.startListening(id, String(this.lang || 'zh-CN'));
    } catch (err) {
      bridge.asrEvent(id, 'error', 'service-not-allowed');
      bridge.asrEvent(id, 'end', null);
    }
  };
  Recognition.prototype.stop = function () { if (this._id) N.stopListening(); };
  Recognition.prototype.abort = function () { if (this._id) N.abortListening(); };

  function resultList(alternatives, max) {
    var picked = (alternatives || []).slice(0, Math.max(1, max | 0)).map(function (alt) {
      return {transcript: String(alt.transcript || ''), confidence: Number(alt.confidence) || 0};
    });
    picked.isFinal = true;
    picked.item = function (i) { return this[i]; };
    var results = [picked];
    results.item = function (i) { return this[i]; };
    return results;
  }

  bridge.asrEvent = function (id, type, payload) {
    var recognition = bridge.recognizers[id];
    if (!recognition) return;
    if (type === 'start') {
      recognition._emit('start');
      recognition._emit('audiostart');
    } else if (type === 'result') {
      recognition._emit('result', {results: resultList(payload, recognition.maxAlternatives), resultIndex: 0});
    } else if (type === 'error') {
      recognition._emit('error', {error: String(payload || 'network'), message: ''});
    } else if (type === 'end') {
      delete bridge.recognizers[id];
      recognition._id = null;
      recognition._emit('end');
    }
  };

  var asrOk = false;
  try { asrOk = Boolean(N.asrAvailable()); } catch (err) { asrOk = false; }
  if (asrOk) {
    window.SpeechRecognition = Recognition;
    window.webkitSpeechRecognition = Recognition;
  } else {
    // 手机上没有识别服务时，**把网页视图自带的那个也拿掉**。
    // 模拟器上实测（安卓 14 网页视图 113）：`webkitSpeechRecognition` 是一个函数，
    // 但它背后什么都没有——页面以为能听，按下麦克风只会报错。拿掉之后 elder.js
    // 一加载就走「这个浏览器不支持语音，请在下面打字」，那句话在这种手机上是真话。
    ['SpeechRecognition', 'webkitSpeechRecognition'].forEach(function (name) {
      try {
        Object.defineProperty(window, name, {value: undefined, configurable: true, writable: true});
      } catch (err) {
        window[name] = undefined;
      }
    });
  }

  /* ---------------------------------------------------------------- 3. 存一份 */
  if (typeof N.saveText !== 'undefined') {
    document.addEventListener('click', function (event) {
      var link = event.target && event.target.closest ? event.target.closest('a[download]') : null;
      if (!link || !/^blob:/.test(link.href)) return;
      // 同步读：页面下一拍就会收回这个地址（common.js 的 saveTextFile）。
      // **读到了才接手**：读不到就不拦，绝不存一个空文件再说「存好了」。
      var text = null;
      try {
        var xhr = new XMLHttpRequest();
        xhr.open('GET', link.href, false);
        xhr.send();
        if (xhr.status === 200 || xhr.status === 0) text = xhr.responseText;
      } catch (err) {
        text = null;
      }
      if (text == null) return;
      event.preventDefault();
      N.saveText(link.getAttribute('download') || '优活.txt', text);
    }, true);
  }
}());
