/* 今日安排页的全部逻辑。
 *
 * 两个数据源，都是真的：
 *
 *   GET /api/v1/agenda                  顶上那张「接下来」——下一件要办的事
 *   GET /api/v1/reminders[?kind=用药]   下面那张全表，筛选就是把 kind 传给它
 *
 * 筛选**走服务端**，不是把同一份数据在本地藏几行。理由：`kind` 是后端从标题认出来的
 * （`app_api.py::_kind_of`），认法哪天改了，界面上要立刻跟着变；本地过滤会让前端
 * 长出第二套分类规则，而两套规则一定会分叉。
 *
 * 其余三条约定和 `page-medication.js` 一样：状态不在前端翻译、动作按钮一律用
 * `data-do`（`data-action` 是 app.js 的命名空间）、写操作之后重新拉一遍而不是本地改字。
 */
(function () {
  "use strict";

  /** 筛选按钮上那四个词。「全部」不带 kind 参数，其余三个原样传给后端。 */
  var ALL = "全部";

  /** 每一类用哪张图。四张都在 `../art/png/` 里，改名之前先确认文件还在。 */
  var ART = {
    "用药": "../art/png/home_schedule_pill.png",
    "就医": "../art/png/home_schedule_pressure.png",
    "健康": "../art/png/service_health.png",
    "其他": "../art/png/home_schedule_people.png"
  };
  var FALLBACK_ART = ART["其他"];

  /** 状态 → [字色, 底色, 描边色]。和用药页同一套，改一处要改两处。 */
  var TONE = {
    "待进行": ["#8a5a12", "rgba(255,248,235,.96)", "rgba(180,133,63,.48)"],
    "已完成": ["#1c7742", "rgba(235,249,240,.96)", "rgba(52,143,93,.45)"],
    "已取消": ["#6b645e", "rgba(243,241,237,.96)", "rgba(120,112,102,.38)"]
  };
  var OVERDUE_INK = "#b23021";

  var listBox = null;
  var summaryLine = null;
  var nextBox = null;

  var currentKind = ALL;
  var busy = false;
  var flashId = null;

  function say(message) {
    if (message && typeof toast === "function") toast(message);
  }

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

  /** 后端回了 `detail` = 这一支是设计好的，照实说一句就完了，不往 console 里写。
   *  详见 `page-medication.js` 里同名函数的说明。 */
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

  // ---- 顶上那张「接下来」 ---------------------------------------------------

  /** 还没办的里面，下一件该做的是哪一件。
   *
   * **刻意不用 `GET /agenda` 的 `next`。** 那个接口判「办完了」只看
   * COMPLETED / ACKNOWLEDGED（`app_api.py::agenda`），**取消掉的一条它照样算待进行**。
   * 实测：在这一页把「吃钙片」取消掉，下面那张卡当场变成「已取消」，而顶上
   * 仍然写着「07:30 吃钙片」——同一屏的两半互相打脸，而且上半屏是错的。
   * （首页那张「接下来」走的就是 /agenda，同一个毛病；但那是 `app.js` 和
   * `app_api.py` 的事，不在这个文件的范围里，只在这里记一笔。）
   *
   * 挑法照抄后端那条规则：先取还没到点的第一件；都过点了就取最早的那一件，
   * 并标出来它已经过点。只有一处不同——不限「今天」。这一页本来就管全部安排，
   * 而卡上带着日期，不会看混。
   */
  function pickNext(items) {
    var pending = [];
    for (var i = 0; i < items.length; i++) {
      if (items[i].status === "待进行") pending.push(items[i]);
    }
    pending.sort(function (a, b) { return String(a.at) < String(b.at) ? -1 : 1; });
    for (var j = 0; j < pending.length; j++) {
      if (pending[j].overdue !== true) return pending[j];
    }
    return pending.length ? pending[0] : null;
  }

  function renderNext(next) {
    if (!nextBox) return;
    nextBox.textContent = "";

    if (!next) {
      var quiet = make("p", "font-size:17px;margin:0");
      quiet.className = "muted";
      quiet.textContent = "没有要办的事了，安心休息。";
      nextBox.appendChild(quiet);
      return;
    }

    var late = next.overdue === true;
    var head = make("div", "display:flex;align-items:center;gap:10px;flex-wrap:wrap");
    head.appendChild(make(
      "b",
      "font-size:25px;letter-spacing:-.02em;color:" + (late ? OVERDUE_INK : "#8a5a12"),
      (next.date ? next.date + "　" : "") + (next.time || "")
    ));
    if (late) {
      head.appendChild(chip("已经过点了",
        [OVERDUE_INK, "rgba(255,240,237,.96)", "rgba(178,48,33,.4)"]));
    }
    nextBox.appendChild(head);
    nextBox.appendChild(make(
      "b", "display:block;font-size:21px;line-height:1.32;margin-top:7px", next.title || ""));
    var kindLine = make("small", "display:block;font-size:13px;margin-top:6px", next.kind || "");
    kindLine.className = "muted";
    nextBox.appendChild(kindLine);
  }

  // ---- 下面那张全表 ---------------------------------------------------------

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
    art.src = ART[item.kind] || FALLBACK_ART;
    art.alt = "";
    head.appendChild(art);

    var mid = make("div", "flex:1;min-width:0");
    var top = make("div", "display:flex;align-items:center;justify-content:space-between;gap:10px");
    top.appendChild(make(
      "b",
      "font-size:19px;letter-spacing:-.01em;color:" + (late ? OVERDUE_INK : "#8a5a12"),
      (item.date ? item.date + "　" : "") + (item.time || "")
    ));
    top.appendChild(chip(item.status, tone));
    mid.appendChild(top);

    mid.appendChild(make(
      "b",
      "display:block;font-size:19px;line-height:1.32;margin-top:6px;color:" +
        (pending ? "#2a1f17" : "#6b645e"),
      item.title || ""
    ));

    var kindLine = make("small", "display:block;font-size:13px;margin-top:6px");
    kindLine.className = "muted";
    kindLine.textContent = item.kind || "";
    mid.appendChild(kindLine);

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
      var done = make("button", "flex:1;height:56px;font-size:18px", "办好了");
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
      var tail = make("p", "font-size:15px;margin:12px 0 0");
      tail.className = "muted";
      tail.textContent = item.status === "已完成"
        ? "这一件已经办好了。"
        : "这一件已经取消了，不会再提醒您。";
      box.appendChild(tail);
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
      art.src = currentKind === ALL ? FALLBACK_ART : (ART[currentKind] || FALLBACK_ART);
      art.alt = "";
      empty.appendChild(art);
      var line = make("p", "font-size:17px;margin:12px 0 0");
      line.className = "muted";
      line.textContent = currentKind === ALL
        ? "还没有任何安排。"
        : "「" + currentKind + "」这一类还没有安排。";
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
      var head = currentKind === ALL ? "全部安排" : "「" + currentKind + "」";
      var words = items.length
        ? head + "共 " + items.length + " 件，还有 " + waiting + " 件没办。"
        : head + "现在是空的。";
      if (late) words += "其中 " + late + " 件已经过点了。";
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

  /** 全表永远要拉一次：「接下来」说的是**所有**安排里的下一件，
   *  不能因为现在筛着「就医」就变成「就医里的下一件」——那张卡会随着筛选跳来跳去，
   *  而它回答的问题（「我现在该干嘛」）和筛选无关。
   *  筛着某一类时再多拉一次带 `kind` 的，让分类始终由后端说了算。 */
  function reload() {
    var filtered = currentKind === ALL
      ? null
      : "/reminders?kind=" + encodeURIComponent(currentKind);
    return Promise.all([
      YouhuoAPI.get("/reminders"),
      filtered ? YouhuoAPI.get(filtered) : null
    ]).then(function (both) {
      var everything = both[0];
      render(both[1] || everything);
      renderNext(pickNext((everything && everything.items) || []));
    }).catch(function (err) {
      console.error(err);
      showTrouble("这会儿没能取到安排，请稍后再看一次。");
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
        trouble(err, "这一件没能改成，请再试一次。");
      })
      .then(function () { busy = false; });
  }

  function pickKind(button) {
    var kind = button.dataset.kind || ALL;
    document.querySelectorAll('[data-do="filter"]').forEach(function (b) {
      b.classList.remove("active");
      b.setAttribute("aria-pressed", "false");
    });
    button.classList.add("active");
    button.setAttribute("aria-pressed", "true");
    currentKind = kind;
    if (summaryLine) summaryLine.textContent = "正在换一类看…";
    reload();
  }

  /** 返回箭头的落点。没有上一页时自己落到「我的」，有上一页时一个字都不做，
   *  让 `app.js` 的 `history.back()` 回去。
   *
   *  **判据不能用 `document.referrer`**（站点下发 `Referrer-Policy: no-referrer`，
   *  它恒为空串，按它判会把每一次返回都弹到「我的」）；拦在捕获阶段是为了不和
   *  `app.js` 抢跳转。两处的完整理由都写在 `page-medication.js` 的同名函数上。 */
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

    if (what === "filter") { pickKind(hit); return; }
    if (what === "done") { act("/reminders/" + hit.dataset.id + "/done", hit.dataset.id); return; }
    if (what === "cancel") { act("/reminders/" + hit.dataset.id + "/cancel", hit.dataset.id); return; }
    if (what === "reload") { say("正在重新取一次…"); reload(); return; }
    if (what === "medication") { location.href = "medication.html"; return; }
  }

  function start() {
    listBox = document.querySelector("#schedList");
    if (!listBox) return;
    summaryLine = document.querySelector("#schedSummary");
    nextBox = document.querySelector("#schedNext");
    document.addEventListener("click", onBackCapture, true);
    document.addEventListener("click", onClick);
    reload();
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", start);
  } else {
    start();
  }
})();
