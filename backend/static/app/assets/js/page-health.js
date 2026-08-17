// 健康助手页。
//
// 这一页最重要的一条是**不编数字**。
//
// `GET /health-summary` 的实情（起服务实际请求过，不是照文档猜的）：
//
//     {"overall": null, "metrics": [], "recorded": 0, "note": "还没有记到身体数据。"}
//
// 后端只有一张健康**事件**表，没有体征快照，完全没有睡眠这一项；演示数据里
// 一条身体数据都没种，所以 `metrics` 就是空的。这一页于是显示「还没有记到」，
// 而不是「心率 72 / 血压 120/78 / 睡眠 7.5 小时」——那四个数字是这个产品最不该
// 出现的东西（`app.js` 的注释里记着上一轮就是被这四个数字坑的）。
//
// 下半屏是 `GET /reminders?kind=健康` 的真实待办，每条能点「办好了」，
// 走 `POST /reminders/{id}/done` 真的改状态。

(function () {
  "use strict";

  function $(id) { return document.getElementById(id); }

  function set(id, s) {
    var el = $(id);
    if (el) el.textContent = (s == null ? "" : String(s));
  }

  // 标题 → 图标。与 app.js 的 `iconFor` 同一套思路：认得出来就给对应的图，
  // 认不出来给一个中性的，不硬塞。
  var TODO_ICON = [
    ["血压", "home_schedule_pressure"],
    ["血糖", "home_schedule_pressure"],
    ["体重", "home_schedule_pressure"],
    ["药",   "home_schedule_pill"],
    ["胶囊", "home_schedule_pill"],
    ["钙片", "home_schedule_pill"]
  ];
  function iconFor(title) {
    var t = String(title || "");
    for (var i = 0; i < TODO_ICON.length; i++) {
      if (t.indexOf(TODO_ICON[i][0]) >= 0) return TODO_ICON[i][1];
    }
    return "home_schedule_people";
  }

  function emptyLine(box, words) {
    var p = document.createElement("p");
    p.className = "muted";
    p.style.cssText = "margin:0;padding:22px 0;font-size:16px;line-height:1.55";
    p.textContent = words;
    box.appendChild(p);
  }

  // ---- 上半屏：身体数据 -----------------------------------------------------

  function renderSummary(sum) {
    var box = $("hsMetrics");
    if (!box) return;
    box.innerHTML = "";

    var metrics = (sum && sum.metrics) || [];
    var recorded = (sum && typeof sum.recorded === "number") ? sum.recorded : null;

    // 「一共记到几条」是后端真的数出来的，可以说。
    if (recorded === null) {
      set("hsSource", "");
    } else if (recorded > 0) {
      set("hsSource", "一共记到 " + recorded + " 条");
    } else {
      set("hsSource", "一条都还没有记到");
    }

    if (metrics.length) {
      var grid = document.createElement("div");
      grid.style.cssText = "display:flex;flex-wrap:wrap;gap:14px 18px";
      for (var i = 0; i < metrics.length; i++) {
        var m = metrics[i] || {};
        var cell = document.createElement("div");
        cell.style.cssText = "flex:1 1 40%;min-width:112px";

        var label = document.createElement("small");
        label.className = "muted";
        label.style.cssText = "display:block;font-size:13px";
        label.textContent = m.label || "这一项";

        var value = document.createElement("b");
        value.style.cssText = "display:block;font-size:23px;margin-top:5px;line-height:1.2";
        if (m.value == null || m.value === "") {
          // 取不到就说取不到。摆一个数字比少一格糟得多。
          value.textContent = "还没有记到";
          value.style.fontSize = "17px";
          value.style.color = "var(--muted)";
        } else {
          value.textContent = String(m.value) + (m.unit ? " " + m.unit : "");
        }
        cell.appendChild(label);
        cell.appendChild(value);

        if (m.at) {
          var at = document.createElement("small");
          at.className = "muted";
          at.style.cssText = "display:block;margin-top:4px;font-size:13px";
          at.textContent = stamp(m.at);
          cell.appendChild(at);
        }
        grid.appendChild(cell);
      }
      box.appendChild(grid);
    }

    // `overall` 后端目前永远是 null（它没有下这个结论的依据）。
    // 真给了才显示，没给就一个字都不写——不许自己判一句「今日健康 良好」。
    var note = (sum && sum.note) || "";
    if (!metrics.length && !note) note = "还没有记到身体数据。";
    if (sum && sum.overall) {
      note = String(sum.overall) + (note ? "　" + note : "");
    }
    set("hsNote", note);
    var noteEl = $("hsNote");
    if (noteEl) noteEl.style.display = note ? "block" : "none";
  }

  function pad(n) { return (n < 10 ? "0" : "") + n; }

  function stamp(iso) {
    if (!iso) return "";
    var d = new Date(iso);
    if (isNaN(d.getTime())) return String(iso).slice(0, 16).replace("T", " ");
    return pad(d.getMonth() + 1) + "月" + pad(d.getDate()) + "日 " +
           pad(d.getHours()) + ":" + pad(d.getMinutes());
  }

  // ---- 下半屏：健康待办 -----------------------------------------------------

  function metaOf(item) {
    var bits = [];
    if (item.date) bits.push(item.date);
    if (item.time) bits.push(item.time);
    var when = bits.join(" ");
    // `status` 后端已经翻成中文了（「待进行」/「已完成」/「已取消」），直接用。
    var s = item.status || "";
    if (item.overdue && !item.done && !item.cancelled) s = s + " · 已经过点了";
    return when ? when + "　" + s : s;
  }

  function renderTodoRow(item) {
    // 标题一行、按钮另起一行。
    //
    // 第一版是「图标 + 文字 + 按钮」横排一行，量出来文字只剩 **128px**：
    // 「明天上午去社区量血压」折成两行，「08月18日 11:00　待进行」也折成两行。
    // 一位视力在下降的老人对着一段被挤成两行的标题，比多滚半屏糟得多。
    // 竖排之后标题拿到 246px，实测一行放得下。
    var row = document.createElement("div");
    row.style.cssText = "padding:13px 0;border-bottom:1px solid var(--line)";

    var top = document.createElement("div");
    top.style.cssText = "display:flex;align-items:flex-start;gap:12px";

    var img = document.createElement("img");
    img.src = "../art/png/" + iconFor(item.title) + ".png";
    img.alt = "";
    img.style.cssText = "width:44px;height:44px;object-fit:contain;flex:0 0 44px";

    var mid = document.createElement("div");
    mid.style.cssText = "flex:1;min-width:0";
    var title = document.createElement("b");
    title.style.cssText = "display:block;font-size:18px;line-height:1.35";
    title.textContent = item.title || "一件健康上的事";
    var meta = document.createElement("small");
    meta.className = "muted";
    meta.style.cssText = "display:block;margin-top:6px;font-size:13px;line-height:1.4";
    meta.textContent = metaOf(item);
    mid.appendChild(title);
    mid.appendChild(meta);

    top.appendChild(img);
    top.appendChild(mid);
    row.appendChild(top);

    var right = document.createElement("div");
    right.style.cssText = "display:flex;justify-content:flex-end;margin-top:11px";
    row.appendChild(right);

    function showDone() {
      right.innerHTML = "";
      var chip = document.createElement("span");
      // 尺寸跟按钮对齐（52×148），这样「办好了 → 已办好」不会让整行的高度跳一下。
      chip.style.cssText = "display:inline-flex;align-items:center;justify-content:center;" +
        "gap:7px;min-height:52px;min-width:148px;box-sizing:border-box;" +
        "font-size:18px;font-weight:760;color:#146b3a;background:#e3f4e8;" +
        "border-radius:15px;padding:0 18px;white-space:nowrap";
      var tick = document.createElement("img");
      tick.src = "../art/png/success_check.png";
      tick.alt = "";
      tick.style.cssText = "width:22px;height:22px;object-fit:contain";
      chip.appendChild(tick);
      chip.appendChild(document.createTextNode("已办好"));
      right.appendChild(chip);
    }

    function showCancelled() {
      right.innerHTML = "";
      var chip = document.createElement("span");
      chip.style.cssText = "display:inline-flex;align-items:center;justify-content:center;" +
        "min-height:52px;min-width:148px;box-sizing:border-box;" +
        "font-size:18px;font-weight:760;color:#585350;background:#efece7;" +
        "border-radius:15px;padding:0 18px;white-space:nowrap";
      chip.textContent = "已取消";
      right.appendChild(chip);
    }

    if (item.done) {
      showDone();
    } else if (item.cancelled) {
      showCancelled();
    } else {
      var btn = document.createElement("button");
      btn.className = "btn secondary";
      btn.type = "button";
      btn.style.cssText = "height:52px;min-width:148px;font-size:18px;" +
        "border-radius:15px;padding:0 18px";
      btn.textContent = "办好了";
      btn.addEventListener("click", function () {
        btn.disabled = true;
        btn.textContent = "记着…";
        window.YouhuoAPI.post("/reminders/" + encodeURIComponent(item.id) + "/done", {})
          .then(function (res) {
            if (typeof window.toast === "function" && res && res.message) {
              window.toast(res.message);
            }
            // 状态取服务端说的那一个（后端已经是中文），不是前端自己写死「已完成」。
            item.done = true;
            item.status = (res && res.status) || item.status;
            meta.textContent = metaOf(item);
            showDone();
          })
          .catch(function (err) {
            console.warn(err);
            btn.disabled = false;
            btn.textContent = "办好了";
            if (typeof window.toast === "function") {
              window.toast("这一条没能记上，请再点一次");
            }
          });
      });
      right.appendChild(btn);
    }

    return row;
  }

  function renderTodo(data) {
    var box = $("hsTodo");
    if (!box) return;
    box.innerHTML = "";
    var items = (data && data.items) || [];
    if (!items.length) {
      emptyLine(box, "今天没有健康上的待办。有需要办的事，跟优活说一声就行。");
      return;
    }
    for (var i = 0; i < items.length; i++) {
      box.appendChild(renderTodoRow(items[i]));
    }
    if (box.lastChild) box.lastChild.style.borderBottom = "0";
  }

  // ---- 装配。两个请求都是 GET；这一页在加载时不发任何 POST。 ----------------

  function init() {
    window.YouhuoAPI.get("/health-summary")
      .then(renderSummary)
      .catch(function (err) {
        console.warn(err);
        set("hsSource", "");
        set("hsNote", "暂时取不到身体数据，请稍后再看一次。");
        var noteEl = $("hsNote");
        if (noteEl) noteEl.style.display = "block";
      });

    window.YouhuoAPI.get("/reminders?kind=" + encodeURIComponent("健康"))
      .then(renderTodo)
      .catch(function (err) {
        console.warn(err);
        var box = $("hsTodo");
        if (box) {
          box.innerHTML = "";
          emptyLine(box, "暂时取不到今天的健康待办，请稍后再看一次。");
        }
      });
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();
