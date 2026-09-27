/* 设置页（字号 / 语速 / 高对比）。
 *
 * 三件事都**真的存到后端**（`PUT /api/v1/settings`），进页面先 `GET /settings` 回填。
 * 字号点下去当场把整框的字改大——不是等下次打开才生效，老人看不见的生效等于没生效。
 *
 * 两条容易踩空的地方：
 *
 *   一、**以服务端返回的值为准。** 服务端会把 fontScale 夹在 0.9–1.6、voiceSpeed 夹在
 *       0.6–1.6，传 9.9 回的是 1.6 且不报错。所以点完之后回填的是响应里的值，
 *       不是刚才传出去的那个。前端这边也夹一次，只为了避免乐观渲染那一帧闪成 158px。
 *
 *   二、**放大要落在 app.css 写死 px 的那些元素上。** `.hero` `.btn` `.line` 这些
 *       都是绝对 px，光改 body 字号一个字都不会变。所以页面上每一处正文的行内样式写的是
 *       `calc(Npx * var(--fs,1))`，这里只需要改 `--fs` 这一个变量；同时把根元素的
 *       font-size 也改掉，好让没有写死字号的段落（模态框里的字）跟着走。
 *       `--fs` 设在 `<html>` 上而不是 `.phone` 上：`.modal` 是 `position:fixed`
 *       且挂在 `.phone` 外面，设在 `.phone` 上它就够不着。
 */

(function () {
  "use strict";

  //: 四档字号。都落在服务端的 0.9–1.6 里，所以不会被夹。
  var FONT_OPTIONS = [
    { value: 1.0, word: "标准" },
    { value: 1.2, word: "大一点" },
    { value: 1.4, word: "更大" },
    { value: 1.6, word: "最大" }
  ];
  //: 三档语速。都落在服务端的 0.6–1.6 里。
  var SPEED_OPTIONS = [
    { value: 0.8, word: "慢" },
    { value: 1.0, word: "正常" },
    { value: 1.2, word: "快" }
  ];

  //: 高对比打开时覆盖的调色板变量。这些变量名是 app.css `:root` 里定义的那一批，
  //: 写在 `<html>` 的行内样式上，优先级高于 `:root` 那条规则，所以整框都会跟着变。
  var CONTRAST_VARS = {
    "--ink": "#100d0a",
    "--muted": "#38322b",
    "--line": "rgba(52,36,20,.42)",
    "--card": "#fffdf8",
    "--paper": "#fffdf6",
    "--paper2": "#fffdf6"
  };

  var state = { fontScale: 1, voiceSpeed: 1, highContrast: false, saved: false };
  var busy = false;

  // api-client.js 现在只导出 get/post。它内部的 `request(method, path, body)` 本来就
  // 收 method，PUT 直接走它——这一页不去改那个文件。将来那边补了 `put` 也不会冲突。
  function apiPut(path, body) {
    if (typeof YouhuoAPI.put === "function") return YouhuoAPI.put(path, body);
    return YouhuoAPI.request("PUT", path, body);
  }

  function near(a, b) {
    return Math.abs(Number(a) - Number(b)) < 0.005;
  }

  function wordFor(options, value) {
    for (var i = 0; i < options.length; i++) {
      if (near(options[i].value, value)) return options[i].word;
    }
    return null;
  }

  function clamp(value, low, high, fallback) {
    var n = Number(value);
    if (!isFinite(n)) return fallback;
    return Math.min(Math.max(n, low), high);
  }

  // ---- 把设置真的落到屏幕上 --------------------------------------------------

  function applyFontScale(scale) {
    var root = document.documentElement;
    root.style.setProperty("--fs", String(scale));
    root.style.fontSize = (16 * scale).toFixed(2) + "px";
  }

  function applyContrast(on) {
    var root = document.documentElement;
    for (var key in CONTRAST_VARS) {
      if (!Object.prototype.hasOwnProperty.call(CONTRAST_VARS, key)) continue;
      if (on) root.style.setProperty(key, CONTRAST_VARS[key]);
      else root.style.removeProperty(key);
    }
    // 山水图层压在正文底下，高对比时把它淡掉——它正是让字看不清的那一层。
    // 原来的透明度写在行内 style 里，直接覆盖会把它弄丢，所以先存一份再改。
    var scenes = document.querySelectorAll(".scene");
    for (var i = 0; i < scenes.length; i++) {
      var el = scenes[i];
      if (el.dataset.baseOpacity === undefined) {
        el.dataset.baseOpacity = el.style.opacity || "";
      }
      el.style.opacity = on ? ".1" : el.dataset.baseOpacity;
    }
  }

  function markGroup(groupSelector, attribute, value) {
    var buttons = document.querySelectorAll(groupSelector + " [" + attribute + "]");
    for (var i = 0; i < buttons.length; i++) {
      var btn = buttons[i];
      var on = near(btn.getAttribute(attribute), value);
      btn.classList.toggle("active", on);
      btn.setAttribute("aria-pressed", on ? "true" : "false");
      // `.btn.secondary.active` 本身只换底色。给老人看的选中态还要更硬一点：
      // 边框加粗到 3px（box-sizing 是 border-box，高度不会变），并让那枚对勾露出来。
      btn.style.borderWidth = on ? "3px" : "1px";
      btn.style.borderColor = on ? "#a8712a" : "#c89958";
      var check = btn.querySelector("[data-check]");
      if (check) check.style.visibility = on ? "visible" : "hidden";
    }
  }

  /* 字号预览那一行的样例句。
   *
   * 交付包写死的是**「今天上午八点，吃一次降压药。」**——一句具体的服药指令，
   * 编的，而且从来没有任何 JS 碰过它。老人在设置页看到这一行，没有任何线索
   * 说明它只是个字号样例：它的语气、格式和真提醒一模一样。
   *
   * 这一页所在的壳自己立的规矩就是「后端拿不到的字段一律留空，**绝不显示
   * 写死的假值**」（`app.js:183`）。所以：拿得到她真的下一件事，就用她自己的
   * 那一句——看自己的字变大，比看别人的病更有用；拿不到，就退回一句
   * **不含任何医嘱和数字**的中性样例。
   *
   * 取不到日程不报错：这是预览，不是这一页的主干（主干是字号存不存得下）。
   */
  var NEUTRAL_SAMPLE = "这行字现在这么大，您看着舒服吗。";
  var previewWords = null;

  function fillPreview() {
    var el = document.querySelector("#fontPreview");
    if (el) el.textContent = previewWords || NEUTRAL_SAMPLE;
  }

  function loadPreview() {
    if (!window.YouhuoAPI || typeof YouhuoAPI.get !== "function") return;
    YouhuoAPI.get("/agenda").then(function (agenda) {
      var next = agenda && agenda.next;
      if (next && next.title) {
        // 只用标题，**不拼时刻**。实测拼上之后是
        // 「16:00，下午四点吃降压药。」——两格说同一件事。
        //
        // 这个例子原先写的是「14:00，下午四点吃降压药。」。那时候种子把这条
        // 排在 14:00，而标题说的是十六点——**两个数其实是矛盾的**，
        // 当时只当成了重复。时刻已经改到 16:00（`database.py::seed_reminders`
        // 的偏移 6 -> 8）。这里说的「不要把时刻拼在标题前面」那一条仍然成立。
        // 设计三的「下一件」卡片为同一个毛病改过一次：后一格只在前一格
        // 没说的时候才补。这里更简单：这一行的用处是看字有多大，
        // 她自己那句话就够了，时刻是多余的。
        previewWords = next.title + "。";
        fillPreview();
      }
    }).catch(function () { /* 预览取不到就用中性样例，不打扰她 */ });
  }

  /* 「这台机器上到底能不能念」。
   *
   * 快慢存得下，也真的存进了老人的交互档案。缺的是**有没有东西按它念**：
   * 这套壳里没有任何朗读（`assets/js/speech.js` 里自己写着这件事），
   * 而这台服务上离线的那份声音也没装——`GET /speech/status` 实测回
   * `available: false`，`POST /speech` 当场 503。
   *
   * 所以这里**只读状态，不加按钮**。加一个「试听」按钮的话，它背后那次请求
   * 在这台机器上必然失败；一个必然失败的按钮比没有这个按钮糟得多——
   * 老人按下去没声音，只会以为是自己耳朵的问题，而不会知道是机器上少装了东西。
   *
   * 读不到状态就把这一行整个藏起来。说错「装了」和说错「没装」一样坏，
   * 而这一页上面那句「优活念给您听的时候，用这个快慢」已经替它许过一次愿了。
   */
  function loadVoiceEngine() {
    var el = document.querySelector("#voiceEngineNote");
    if (!el) return;
    if (!window.YouhuoAPI || typeof YouhuoAPI.get !== "function") return;
    YouhuoAPI.get("/speech/status").then(function (st) {
      if (!st || typeof st.available !== "boolean") { el.hidden = true; return; }
      el.textContent = st.available
        ? "这台机器上装了优活自己的声音，念的时候就按这个快慢。"
        : "这台机器上还没有装优活自己的声音，这个快慢现在只是先记下来。";
      el.hidden = false;
    }).catch(function () {
      el.hidden = true;
    });
  }

  function render() {
    applyFontScale(state.fontScale);
    applyContrast(state.highContrast);
    markGroup("#fontScaleGroup", "data-font-scale", state.fontScale);
    markGroup("#voiceSpeedGroup", "data-voice-speed", state.voiceSpeed);

    var fontNow = document.querySelector("#fontNow");
    if (fontNow) {
      var fw = wordFor(FONT_OPTIONS, state.fontScale);
      fontNow.textContent = fw
        ? "现在是「" + fw + "」，看起来是这样"
        : "现在的大小不是上面四块里的任何一块，点一块就换过来";
    }

    fillPreview();

    var speedNow = document.querySelector("#speedNow");
    if (speedNow) {
      var sw = wordFor(SPEED_OPTIONS, state.voiceSpeed);
      speedNow.textContent = sw
        ? "现在是「" + sw + "」。"
        : "现在的快慢不是上面三块里的任何一块，点一块就换过来。";
    }

    var contrastState = document.querySelector("#contrastState");
    if (contrastState) contrastState.textContent = state.highContrast ? "已打开" : "已关闭";
    var toggle = document.querySelector("[data-contrast]");
    if (toggle) {
      toggle.classList.toggle("active", state.highContrast);
      toggle.setAttribute("aria-pressed", state.highContrast ? "true" : "false");
      toggle.style.borderWidth = state.highContrast ? "3px" : "1px";
      toggle.style.borderColor = state.highContrast ? "#a8712a" : "#c89958";
    }

    var hint = document.querySelector("#savedHint");
    if (hint) hint.hidden = state.saved !== false;
  }

  // ---- 读 / 写 ---------------------------------------------------------------

  function adopt(payload) {
    if (!payload || typeof payload !== "object") return;
    if (typeof payload.fontScale === "number") state.fontScale = payload.fontScale;
    if (typeof payload.voiceSpeed === "number") state.voiceSpeed = payload.voiceSpeed;
    if (typeof payload.highContrast === "boolean") state.highContrast = payload.highContrast;
    if (typeof payload.saved === "boolean") state.saved = payload.saved;
    state.fontScale = clamp(state.fontScale, 0.9, 1.6, 1);
    state.voiceSpeed = clamp(state.voiceSpeed, 0.6, 1.6, 1);
  }

  function explain(err) {
    var message = String((err && err.message) || "");
    var at = message.indexOf("{");
    if (at >= 0) {
      try {
        var body = JSON.parse(message.slice(at));
        if (body && body.detail) return String(body.detail);
      } catch (ignored) { /* 不是 JSON 就用下面那句 */ }
    }
    return "没有存上，请再点一次。";
  }

  async function load() {
    try {
      adopt(await YouhuoAPI.get("/settings"));
    } catch (err) {
      console.warn(err);
      toast("设置没有读出来，先按默认的显示。");
    }
    render();
  }

  async function save(patch) {
    if (busy) return null;
    busy = true;
    var before = {
      fontScale: state.fontScale, voiceSpeed: state.voiceSpeed,
      highContrast: state.highContrast, saved: state.saved
    };
    // 先按点的那一下改屏幕，让老人立刻看见；随后再以服务端返回的值为准回填。
    adopt(patch);
    render();
    try {
      var reply = await apiPut("/settings", patch);
      adopt(reply);
      if (!reply || typeof reply.saved !== "boolean") state.saved = true;
      render();
      toast((reply && reply.message) || "设置已经记住了。");
      return reply;
    } catch (err) {
      console.warn(err);
      state.fontScale = before.fontScale;
      state.voiceSpeed = before.voiceSpeed;
      state.highContrast = before.highContrast;
      state.saved = before.saved;
      render();
      toast(explain(err));
      return null;
    } finally {
      busy = false;
    }
  }

  // ---- 交互 ------------------------------------------------------------------

  function goBack() {
    // 直接输网址进来的时候 `history.back()` 什么都不会发生——那就是一个按了没反应的
    // 按钮。有来路才回退，没来路就回「我的」，这一页本来就是从那儿进来的。
    if (document.referrer && history.length > 1) history.back();
    else location.href = "profile.html";
  }

  document.addEventListener("click", function (e) {
    var font = e.target.closest("[data-font-scale]");
    if (font) { save({ fontScale: Number(font.getAttribute("data-font-scale")) }); return; }
    var speed = e.target.closest("[data-voice-speed]");
    if (speed) { save({ voiceSpeed: Number(speed.getAttribute("data-voice-speed")) }); return; }
    var contrast = e.target.closest("[data-contrast]");
    if (contrast) { save({ highContrast: !state.highContrast }); return; }
    var back = e.target.closest("[data-goback]");
    if (back) { goBack(); return; }
  });

  document.addEventListener("DOMContentLoaded", function () {
    // app.js 的 `mountGlobalNav()` 在同一个事件里先跑（它的监听器注册得早），
    // 而 `NAV_PAGE_MAP` 里没有这一页，于是底部会亮「首页」。这一页是从「我的」
    // 进来的，把高亮挪回去——只动 DOM，不碰 app.js。
    var tabs = document.querySelectorAll(".global-nav .nav-tab");
    for (var i = 0; i < tabs.length; i++) {
      tabs[i].classList.toggle("active", tabs[i].getAttribute("data-to") === "profile");
    }
    load();
    loadPreview();
    loadVoiceEngine();
  });

  // 给判据/调试用：不经过界面直接写一个值，看界面回填成什么。
  // 「传 9.9 回来 1.6」这条只能这么验——界面上没有 9.9 这个档。
  window.YouhuoSettingsPage = {
    save: save,
    reload: load,
    snapshot: function () {
      return {
        fontScale: state.fontScale, voiceSpeed: state.voiceSpeed,
        highContrast: state.highContrast, saved: state.saved
      };
    }
  };
})();
