/* 用药提醒页的全部逻辑。
 *
 * 数据只有一个来源：`GET /api/v1/reminders?kind=用药`。页面上不写任何一条假条目，
 * 也不写任何一个假数字——取不到就说取不到，取到空表就说「还没有用药提醒」。
 *
 * 三条约定，改这个文件的人先看一眼：
 *
 *   1. **状态不在前端翻译。** 后端回的 `status` 已经是「待进行 / 已完成 / 已取消」，
 *      这里只决定怎么上色。前端一旦自己拼一套说法，两边就会慢慢对不上。
 *   2. **动作按钮全部用 `data-do`，不用 `data-action`。** `data-action` 是
 *      `assets/js/app.js` 那个全局分发器的命名空间，它只认自己那十几个分支；
 *      在这里写一个它不认识的 `data-action`，按下去会静默地什么都不发生
 *      （`test_app_pages_are_covered.py` 有一条判据专门盯这件事）。
 *   3. **办完 / 取消之后重新拉一遍列表，不在本地改那个字。** 本地改看起来一样，
 *      但服务端要是没改成，屏幕会显示一个并不存在的「已完成」。
 */
(function () {
  "use strict";

  /** 这一页只看这一类。后端认得的四个中文值之一，别的值它回空表而不是 500。 */
  var KIND = "用药";

  /** 状态 → [字色, 底色, 描边色]。#8a5a12 / #1c7742 落在 #fffdf8 上都过 AA。 */
  var TONE = {
    "待进行": ["#8a5a12", "rgba(255,248,235,.96)", "rgba(180,133,63,.48)"],
    "已完成": ["#1c7742", "rgba(235,249,240,.96)", "rgba(52,143,93,.45)"],
    "已取消": ["#6b645e", "rgba(243,241,237,.96)", "rgba(120,112,102,.38)"]
  };
  var OVERDUE_INK = "#b23021";
  var PILL = "../art/png/home_schedule_pill.png";

  var listBox = null;
  var summaryLine = null;
  var formBox = null;
  var toggleBtn = null;
  var titleInput = null;
  var timeInput = null;

  /** 同一时刻只允许一个写操作在飞。连点两下「已经吃了」会得到一次 404。 */
  var busy = false;
  /** 刚被改动过的那一条。重画之后给它一圈高亮，让「哪一条变了」看得见。 */
  var flashId = null;

  function say(message) {
    if (message && typeof toast === "function") toast(message);
  }

  /** 从 api-client 抛出的 `Error("HTTP 400 {\"detail\":\"…\"}")` 里取出后端那句人话。 */
  function detailOf(err) {
    var text = String((err && err.message) || "");
    var at = text.indexOf("{");
    if (at < 0) return "";
    try {
      var body = JSON.parse(text.slice(at));
      return body && body.detail ? String(body.detail) : "";
    } catch (ignored) {
      return "";
    }
  }

  /** 把失败交代给用户，**并且只在真出意外时才写 console**。
   *
   * 后端回了 `detail`（「还没有说要提醒什么。」这种）说明这一支是设计好的：
   * 老人少填了一个字，界面照实说一句就完了。把它也 `console.error` 出去，
   * 控制台就再也分不出「产品在正常工作」和「有东西坏了」——而「控制台干净」
   * 正是这一页唯一能自动判的健康指标。
   */
  function trouble(err, fallback) {
    var detail = detailOf(err);
    if (!detail) console.error(err);
    say(detail || fallback);
  }

  function make(tag, css, text) {
    var node = document.createElement(tag);
    if (css) node.style.cssText = css;
    if (text !== undefined && text !== null) node.textContent = text;
    return node;
  }

  function chip(word, tone) {
    var node = make("span", "", word);
    node.className = "service-flag";
    node.style.color = tone[0];
    node.style.background = tone[1];
    node.style.borderColor = tone[2];
    return node;
  }

  /** 一条提醒 = 一张卡。待进行的带两个按钮，办完或取消的带一句话。 */
  function cardFor(item) {
    var tone = TONE[item.status] || TONE["待进行"];
    var pending = item.status === "待进行";
    var late = pending && item.overdue === true;

    var box = make("article", "margin-top:11px;padding:15px 15px 16px");
    box.className = "card soft";
    box.dataset.id = item.id;
    if (!pending) box.style.background = "rgba(246,243,237,.93)";

    var head = make("div", "display:flex;align-items:flex-start;gap:12px");
    var art = make("img", "width:52px;height:52px;object-fit:contain;flex:0 0 52px");
    art.className = "icon";
    art.src = PILL;
    art.alt = "";
    head.appendChild(art);

    var mid = make("div", "flex:1;min-width:0");
    var top = make("div", "display:flex;align-items:center;justify-content:space-between;gap:10px");
    var clock = make(
      "b",
      "font-size:19px;letter-spacing:-.01em;color:" + (late ? OVERDUE_INK : "#8a5a12"),
      item.time || ""
    );
    top.appendChild(clock);
    top.appendChild(chip(item.status, tone));
    mid.appendChild(top);

    mid.appendChild(make(
      "b",
      "display:block;font-size:19px;line-height:1.32;margin-top:6px;color:" +
        (pending ? "#2a1f17" : "#6b645e"),
      item.title || ""
    ));

    var meta = make("small", "display:block;font-size:13px;margin-top:6px");
    meta.className = "muted";
    meta.textContent = item.date || "";
    mid.appendChild(meta);

    if (late) {
      mid.appendChild(make(
        "b",
        "display:block;font-size:15px;margin-top:6px;color:" + OVERDUE_INK,
        "已经过点了"
      ));
    }
    head.appendChild(mid);
    box.appendChild(head);

    if (pending) {
      var row = make("div", "display:flex;gap:10px;margin-top:13px");
      var done = make("button", "flex:1;height:56px;font-size:18px", "已经吃了");
      done.className = "btn primary";
      done.dataset.do = "done";
      done.dataset.id = item.id;
      var drop = make("button", "flex:1;height:56px;font-size:18px", "取消");
      drop.className = "btn secondary";
      drop.dataset.do = "cancel";
      drop.dataset.id = item.id;
      row.appendChild(done);
      row.appendChild(drop);
      box.appendChild(row);
    } else {
      var note = make("p", "font-size:15px;margin:12px 0 0");
      note.className = "muted";
      note.textContent = item.status === "已完成"
        ? "这一条已经记成办好了。"
        : "这一条已经取消了，不会再提醒您。";
      box.appendChild(note);
    }
    return box;
  }

  function render(payload) {
    var items = (payload && payload.items) || [];
    listBox.textContent = "";

    if (!items.length) {
      var empty = make("section", "margin-top:12px;padding:26px 20px;text-align:center");
      empty.className = "card soft";
      var art = make("img", "width:62px;height:62px;object-fit:contain;opacity:.9");
      art.src = PILL;
      art.alt = "";
      empty.appendChild(art);
      var line = make("p", "font-size:17px;margin:12px 0 0", "还没有用药提醒，可以加一条。");
      line.className = "muted";
      empty.appendChild(line);
      listBox.appendChild(empty);
    } else {
      for (var i = 0; i < items.length; i++) listBox.appendChild(cardFor(items[i]));
    }

    if (summaryLine) {
      var waiting = 0;
      var late = 0;
      for (var j = 0; j < items.length; j++) {
        if (items[j].status === "待进行") waiting += 1;
        if (items[j].overdue === true && items[j].status === "待进行") late += 1;
      }
      var words = items.length
        ? "共 " + items.length + " 条，还有 " + waiting + " 条没吃。"
        : "这里会列出所有和吃药有关的提醒。";
      if (late) words += "其中 " + late + " 条已经过点了。";
      summaryLine.textContent = words;
    }

    if (flashId) {
      var hit = listBox.querySelector('[data-id="' + flashId + '"]');
      if (hit) {
        hit.style.outline = "3px solid #4b78ff";
        hit.style.outlineOffset = "2px";
        setTimeout(function () {
          hit.style.outline = "";
          hit.style.outlineOffset = "";
        }, 2400);
      }
      flashId = null;
    }
  }

  function showTrouble(message) {
    listBox.textContent = "";
    var box = make("section", "margin-top:12px;padding:24px 20px");
    box.className = "card soft";
    var line = make("p", "font-size:17px;margin:0", message);
    line.className = "muted";
    box.appendChild(line);
    var again = make("button", "width:100%;height:56px;margin-top:14px;font-size:18px", "再试一次");
    again.className = "btn secondary";
    again.dataset.do = "reload";
    box.appendChild(again);
    listBox.appendChild(box);
    if (summaryLine) summaryLine.textContent = "";
  }

  function reload() {
    return YouhuoAPI.get("/reminders?kind=" + encodeURIComponent(KIND))
      .then(render)
      .catch(function (err) {
        console.error(err);
        showTrouble("这会儿没能取到用药提醒，请稍后再看一次。");
      });
  }

  function act(path, id) {
    if (busy) return;
    busy = true;
    YouhuoAPI.post(path, {})
      .then(function (result) {
        flashId = id;
        say((result && result.message) || "已经记下了。");
        return reload();
      })
      .catch(function (err) {
        trouble(err, "这一条没能改成，请再试一次。");
      })
      .then(function () { busy = false; });
  }

  function openForm(open) {
    if (!formBox || !toggleBtn) return;
    formBox.hidden = !open;
    toggleBtn.textContent = open ? "收起表单" : "加一条提醒";
    if (open && titleInput) titleInput.focus();
  }

  function submit() {
    if (busy) return;
    busy = true;
    var body = { title: (titleInput && titleInput.value) || "" };
    var when = (timeInput && timeInput.value) || "";
    if (when) body.time = when;
    YouhuoAPI.post("/reminders", body)
      .then(function (result) {
        flashId = result && result.item ? result.item.id : null;
        say((result && result.message) || "记好了。");
        if (titleInput) titleInput.value = "";
        if (timeInput) timeInput.value = "";
        document.querySelectorAll('[data-do="pick"]').forEach(function (b) {
          b.classList.remove("active");
        });
        openForm(false);
        return reload();
      })
      .catch(function (err) {
        trouble(err, "这一条没能存下来，请再试一次。");
        if (titleInput) titleInput.focus();
      })
      .then(function () { busy = false; });
  }

  /** 返回箭头的落点。
   *
   * `data-action="back"` 由 `app.js` 接住，它调的是 `history.back()`——从别的页面
   * 走过来时这是对的。但这一页也可能是**直接打开**的（桌面图标、书签、别人发的
   * 链接），那时前面一页都没有，`history.back()` 静默地什么都不做，箭头就成了
   * 一个「按下去没反应」的控件。
   *
   * **判据不能用 `document.referrer`。** 这台服务器对每一个响应都下发
   * `Referrer-Policy: no-referrer`（`youhuo/api.py` 的 `_SECURITY_HEADERS`），
   * 所以 `document.referrer` 恒为空串——按它判会得出「哪一次都不是从站内来的」，
   * 于是**每一次**返回都被弹到「我的」，从别的页面走过来的那次也一样。
   * 这个坑站里已经踩过两回，`static/landing.js` 和 `static/common.js` 顶上都记着。
   * 实测这一版也踩了一次：从「今日安排」跳过来再按返回，落到了「我的」。
   *
   * 所以只用 `history.length`——它不撒谎：小于等于 1 就是真的没有上一页。
   *
   * 拦在**捕获阶段**：`app.js` 的监听器挂在 document 的冒泡阶段，捕获阶段
   * `stopPropagation()` 之后整条路径就断了，它不会再跑——所以不存在
   * 「两个跳转同时发出去，谁赢看运气」。有上一页时这里一个字都不做，
   * 老老实实让 `history.back()` 回到那一页。
   */
  function onBackCapture(event) {
    var back = event.target.closest('[data-action="back"]');
    if (!back || window.history.length > 1) return;
    event.stopPropagation();
    location.href = "profile.html";
  }

  function onClick(event) {
    var hit = event.target.closest("[data-do]");
    if (!hit) return;
    var what = hit.dataset.do;

    if (what === "done") { act("/reminders/" + hit.dataset.id + "/done", hit.dataset.id); return; }
    if (what === "cancel") { act("/reminders/" + hit.dataset.id + "/cancel", hit.dataset.id); return; }
    if (what === "toggle") { openForm(formBox.hidden); return; }
    if (what === "close") { openForm(false); say("好的，这一条先不加。"); return; }
    if (what === "save") { submit(); return; }
    if (what === "reload") { say("正在重新取一次…"); reload(); return; }
    if (what === "all") { location.href = "schedule.html"; return; }
    if (what === "pick") {
      document.querySelectorAll('[data-do="pick"]').forEach(function (b) {
        b.classList.remove("active");
      });
      hit.classList.add("active");
      if (timeInput) timeInput.value = hit.dataset.time || "";
      say("提醒时间选好了：" + (hit.dataset.time || ""));
      return;
    }
  }

  function start() {
    listBox = document.querySelector("#medList");
    if (!listBox) return;
    summaryLine = document.querySelector("#medSummary");
    formBox = document.querySelector("#medForm");
    toggleBtn = document.querySelector("#medAddToggle");
    titleInput = document.querySelector("#medTitle");
    timeInput = document.querySelector("#medTime");
    document.addEventListener("click", onBackCapture, true);
    document.addEventListener("click", onClick);
    // 输入框里按回车 = 按「存下来」。老人用外接键盘时这是最短的一条路。
    if (titleInput) {
      titleInput.addEventListener("keydown", function (e) {
        if (e.key === "Enter") { e.preventDefault(); submit(); }
      });
    }
    reload();
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", start);
  } else {
    start();
  }
})();
