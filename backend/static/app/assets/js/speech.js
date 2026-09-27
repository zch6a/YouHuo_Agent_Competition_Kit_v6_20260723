// 真的听老人说话。
//
// 在这之前，「正在听」那一页是**演的**：按话筒不会开麦克风，四张建议卡片
// 点一下就把预设句子当成「老人说的话」发出去。屏幕上写着「正在听…」，
// 而没有任何东西在听。
//
// 这一份用浏览器的 Web Speech API 做真识别。几条设计是从 `elder.js:1099-1200`
// 那一版搬过来的——那些是踩出来的，不是想出来的：
//
//   · 错误枚举是英文标识符，**不能直接给老人看**，更不能配一句「请再说一遍」：
//     权限被拒时再说一百遍也不会成功，而页面从不告诉她要去哪里开。
//   · 正在听的时候再按一下，按规范 `start()` 抛 `InvalidStateError`——
//     而老人重复按恰恰是最常见的操作。不挡住的话，第二下屏幕上什么都不变。
//   · 说话和听必须互斥：不停朗读就开麦，识别器会把手机扬声器里 App 自己的
//     声音转写下来，再当成老人这一轮发出去。
//
// **它需要安全上下文**（https 或 localhost），且目前只有 Chromium 系与 Safari 有。
// 拿不到就退回打字——那条路必须一直在，不是"降级方案"而是**并列的入口**。
(function () {
  "use strict";

  var SR = window.SpeechRecognition || window.webkitSpeechRecognition;

  //: 引擎的错误码 → 一句老人读得懂、而且**说得出下一步**的话。
  //: 权限那两条刻意不写「再说一遍」：那是唯一一件重说没用的事。
  var TROUBLE = {
    "not-allowed": "我没有拿到麦克风的许可。您可以在下面打字，或者请家人帮您在手机设置里打开麦克风权限。",
    "service-not-allowed": "这台手机暂时不让我用语音。您可以在下面打字。",
    "audio-capture": "我找不到麦克风。您可以在下面打字。",
    "no-speech": "我没有听到声音。请离手机近一点，再按一下慢慢说。",
    "network": "网络不太好，语音没送出去。您可以在下面打字，或者等一会儿再试。",
    "aborted": "刚才那次听被打断了。您可以再按一下。",
  };

  var rec = null;
  var listening = false;
  var sending = false;
  var finalText = "";

  function el(id) { return document.getElementById(id); }

  function setStatus(text) {
    var node = el("voiceStatus");
    if (node) node.textContent = text;
  }

  function setHeard(text, isFinal) {
    var node = el("voiceHeard");
    if (!node) return;
    node.textContent = text || "";
    // 还没说完的字用浅一点的颜色——让人看得出「这是我正在听到的」，
    // 而不是「这是我认定你说了的」。
    node.style.color = isFinal ? "var(--ink)" : "var(--muted)";
    var box = el("voiceHeardBox");
    if (box) box.hidden = !text;
  }

  function setOrbState(on) {
    listening = on;
    document.body.dataset.listening = on ? "yes" : "no";
    var orb = document.querySelector("[data-action='voice-start'] img");
    if (orb) orb.classList.toggle("pulse", on);
  }

  function showTyping(focus) {
    var box = el("voiceTypeBox");
    if (box) box.hidden = false;
    if (focus) {
      var input = el("voiceInput");
      if (input) input.focus();
    }
  }

  // ---- 把话送出去 ---------------------------------------------------------
  // 和点建议卡片走的是**同一条路**：存进 sessionStorage 再跳识别页。
  // 那一页读 `youhuo_heard` / `youhuo_reply`，没有话就不敢说「我已理解您的需求」。
  async function submit(text) {
    var said = String(text || "").trim();
    if (!said || sending) return;
    sending = true;
    setStatus("正在理解您说的话…");
    try {
      sessionStorage.setItem("youhuo_heard", said);
      var r = await YouhuoAPI.post("/voice/sessions", { utterance: said });
      var reply = r && r.understood && r.understood.reply;
      if (reply) sessionStorage.setItem("youhuo_reply", reply);
      else sessionStorage.removeItem("youhuo_reply");
      go("recognize");
    } catch (e) {
      sending = false;
      console.warn(e);
      setStatus("刚才没送出去，请再说一遍，或者在下面打字。");
      showTyping(false);
    }
  }

  // ---- 识别器 -------------------------------------------------------------
  function build() {
    var r = new SR();
    r.lang = "zh-CN";
    // 开着中间结果：老人边说边能看见字出来，才知道机器真的在听。
    // `elder.js` 那版关着——那一版的话是直接进对话流的，这一版要**当场显形**。
    r.interimResults = true;
    r.maxAlternatives = 3;
    r.continuous = false;

    r.onstart = function () {
      finalText = "";
      setOrbState(true);
      setStatus("正在听，请慢慢说。一次只说一件事也可以。");
      setHeard("", false);
    };

    r.onresult = function (e) {
      var interim = "";
      for (var i = e.resultIndex; i < e.results.length; i++) {
        var chunk = e.results[i][0].transcript;
        if (e.results[i].isFinal) finalText += chunk;
        else interim += chunk;
      }
      setHeard(finalText + interim, !interim);
    };

    r.onend = function () {
      setOrbState(false);
      if (sending) return;
      if (finalText.trim()) {
        submit(finalText);
      } else {
        // 听完了但一个字都没有。这不是错误，但也**不能装作没发生**。
        setStatus("没有听到您说话。再按一下话筒，或者在下面打字。");
        showTyping(false);
      }
    };

    r.onerror = function (e) {
      setOrbState(false);
      setStatus(TROUBLE[e.error] || "语音没能用起来。您可以在下面打字，我一样能办。");
      // 权限类的错误：重说没用，直接把打字这条路摆到她面前并聚焦。
      var permission = e.error === "not-allowed"
        || e.error === "service-not-allowed"
        || e.error === "audio-capture";
      showTyping(permission);
    };
    return r;
  }

  function start() {
    if (!SR) {
      setStatus("这台设备上用不了语音。您可以在下面打字，我一样能办。");
      showTyping(true);
      return;
    }
    if (listening) {
      // 正在听的时候再按一下：按规范 `start()` 会抛 InvalidStateError。
      // 不挡住的话屏幕上什么都不变，老人得不到「第二下没用」的任何反馈。
      setStatus("我正在听，您说吧。");
      return;
    }
    // 说话和听互斥。这套壳目前没有朗读，但 `speechSynthesis` 是浏览器全局的——
    // 别的页面留下的朗读会被麦克风收进去，再当成她这一轮说的话。
    if (window.speechSynthesis && window.speechSynthesis.speaking) {
      window.speechSynthesis.cancel();
    }
    if (!rec) rec = build();
    try {
      rec.start();
    } catch (err) {
      setOrbState(false);
      setStatus("这一次没能开始听。请再按一下，或者在下面打字。");
      showTyping(false);
    }
  }

  function stop() {
    if (rec && listening) {
      try { rec.stop(); } catch (e) { /* 已经停了 */ }
    }
  }

  // 暴露给 `app.js` 的 `voice-start` 分支。挂在 window 上而不是靠事件，
  // 是为了让 `app.js` 能明确判断「这一页有没有真识别」——
  // 没有这个对象时它走老路（跳到「正在听」页），有就交给这里。
  window.YouhuoSpeech = {
    available: function () { return !!SR; },
    start: start,
    stop: stop,
    submit: submit,
    listening: function () { return listening; },
  };

  document.addEventListener("DOMContentLoaded", function () {
    if (!el("voiceStatus")) return;   // 不是「正在听」那一页

    if (!SR) {
      // 没有识别能力时**不许**让屏幕继续写「正在听…」。
      setStatus("这台设备上用不了语音，您可以在下面打字，或者点下面的常用句子。");
      showTyping(false);
    } else {
      setStatus("按住下面的话筒，说一句您要办的事。");
    }

    var send = el("voiceSend");
    var input = el("voiceInput");
    if (send) send.addEventListener("click", function () { submit(input && input.value); });
    if (input) {
      input.addEventListener("keydown", function (e) {
        // 中文输入法合成期间照样派发 keydown（`isComposing === true`）。
        // 不挡的话，老人用拼音打「jiaoshuifei」按回车选字，送出去的是还没上屏的拼音串。
        if (e.isComposing || e.keyCode === 229) return;
        if (e.key === "Enter") submit(input.value);
      });
    }
  });
})();
