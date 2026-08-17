// 家人确认页 —— 闭环的最后一步。
//
// 后端一直有 `POST /payments/{id}/family-approve`，但界面上没有任何按钮调它，
// 于是「老人发起 → 复述 → 等家人点头 → 家人同意 → 办好 → 凭证」这条链在屏幕上
// 是断的，演示只能靠脚本在旁边补一刀。这一页就是那一刀。
//
// 视角是**家人**：女儿在自己手机上收到通知，打开看这一笔，决定点不点头。
//
// 两条硬约束写在这里，改这个文件的人先读：
//
//   一、**渲染凭证不许推进事务。** 页面加载只发 GET /payments/{id}/certificate。
//       只有用户真的按下「同意并办理」那一刻才允许发 POST。不许在 load 里
//       「顺便」调一次 family-approve——那等于替家人点头。
//   二、**界面上不许出现英文枚举。** `awaiting_family_approval`、`elder-demo`、
//       `app.payment.teach_back` 全部要翻。三张表都**不保留原始码兜底**：
//       认不出来的说「还在办」「家里人」「办了一件事」，而不是把 id 漏到屏幕上。

(function () {
  "use strict";

  var PID_KEY = "youhuo_payment_id";

  // ---- 三张翻译表 -----------------------------------------------------------

  // 事务状态 → 给人看的说法 + [字色, 底色]。
  // 颜色都是量过对比度的：#8a4b0f/#fdf0e0 = 6.0:1，#146b3a/#e3f4e8 = 5.8:1，
  // 都过 AA 正文 4.5:1。（app.js 里那套 #df7d1e 落在浅底上只有 2.8:1，没有照抄。）
  var STATUS = {
    awaiting_family_approval:    ["等家人确认", "#8a4b0f", "#fdf0e0"],
    awaiting_elder_confirmation: ["等老人确认", "#8a4b0f", "#fdf0e0"],
    collecting:                  ["还在准备",   "#8a4b0f", "#fdf0e0"],
    executing:                   ["正在办理",   "#8a4b0f", "#fdf0e0"],
    completed:                   ["已办好",     "#146b3a", "#e3f4e8"],
    cancelled:                   ["已取消",     "#585350", "#efece7"],
    failed:                      ["没有办成",   "#9c2318", "#fbe7e4"]
  };
  function statusOf(code) {
    return STATUS[code] || ["还在办", "#8a4b0f", "#fdf0e0"];
  }

  // 审计事件 → 人话 + 图标。取值与 app_api.py 的 `_WORDS` 对齐（那张表是查库定的）。
  var STEP = {
    "app.payment.prepared":         ["发起申请",         "record_request"],
    "app.payment.teach_back":       ["复述确认",         "record_confirm"],
    "app.payment.awaiting_family":  ["等家人确认",       "record_family"],
    "app.emergency.requested":      ["紧急呼叫",         "record_family"],
    "TASK_CREATED":                 ["开始办一件事",     "record_request"],
    "ELDER_CONFIRMED":              ["老人确认了",       "record_confirm"],
    "TEACH_BACK_VERIFIED":          ["复述核对通过",     "record_confirm"],
    "APPROVAL_REQUIRED":            ["等家人点头",       "record_family"],
    "FAMILY_APPROVAL_RECORDED":     ["家人已点头",       "record_family"],
    "FAMILY_APPROVED_AND_EXECUTED": ["家人同意后已办好", "record_water"],
    "TASK_REJECTED":                ["这件事被拒绝了",   "record_confirm"],
    "NOTIFICATION_CREATED":         ["发出一条通知",     "record_request"]
  };
  function stepOf(action) {
    return STEP[action] || ["办了一件事", "record_request"];
  }

  // 审计里的 actor_id → 称呼。
  var ACTOR = {
    "elder-demo": "老人",
    "daughter-demo": "女儿",
    "son-demo": "儿子",
    "system-demo": "系统"
  };
  function actorOf(id) {
    if (!id) return "系统";
    return ACTOR[id] || "家里人";
  }

  // ---- 小工具 ---------------------------------------------------------------

  function $(id) { return document.getElementById(id); }
  function show(id, on) { var el = $(id); if (el) el.hidden = !on; }
  function text(id, s) { var el = $(id); if (el) el.textContent = (s == null ? "" : String(s)); }

  function pad(n) { return (n < 10 ? "0" : "") + n; }

  // ISO 串 → 「08月17日 08:30」。
  // 后端存的是 UTC 并带着 `+00:00`，所以交给 Date 换算成本地时刻——那才是这件事
  // 真正发生的钟点。解析不了就退回原串的日期部分，不编一个时间出来。
  function when(iso) {
    if (!iso) return "";
    var d = new Date(iso);
    if (isNaN(d.getTime())) return String(iso).slice(0, 16).replace("T", " ");
    return pad(d.getMonth() + 1) + "月" + pad(d.getDate()) + "日 " +
           pad(d.getHours()) + ":" + pad(d.getMinutes());
  }

  // 摘要只取前 8 位。后端给的是 12 位十六进制加一个省略号，先把非十六进制字符去掉。
  function digest8(raw) {
    var hex = String(raw == null ? "" : raw).replace(/[^0-9a-fA-F]/g, "");
    return hex ? hex.slice(0, 8) : "";
  }

  // api-client.js 抛的是 `new Error("HTTP 409 " + 响应体)`，响应体是
  // `{"detail":"这一笔还没有走到等家人确认这一步。"}`。
  // 那句话是**守卫在说话**，要原样显示给用户——不是「操作失败」。
  function guardDetail(err) {
    var msg = (err && err.message) || "";
    var m = msg.match(/^HTTP\s+(\d{3})\s*([\s\S]*)$/);
    if (!m) return { code: 0, detail: "" };
    var detail = "";
    try {
      var body = JSON.parse(m[2]);
      if (body && typeof body.detail === "string") detail = body.detail;
    } catch (e) { /* 不是 JSON 就当没有 detail，绝不把原始响应体甩到屏幕上 */ }
    return { code: parseInt(m[1], 10), detail: detail };
  }

  function notice(kind, main, hint) {
    var icon = $("faNoticeIcon");
    if (icon) {
      icon.src = "../art/png/" +
        (kind === "done" ? "success_check" : "bill_safety_shield") + ".png";
    }
    text("faNoticeText", main);
    var t = $("faNoticeText");
    if (t) t.style.color = kind === "done" ? "#146b3a" : "#8a4b0f";
    text("faNoticeHint", hint || "");
    // 这一行带着内联 `display:block`，**作者样式压得过 UA 的 `[hidden]{display:none}`**——
    // 用 `hidden` 属性藏它是藏不掉的（这个项目在 `.row` / `.line` 上栽过同一件事）。
    var h = $("faNoticeHint");
    if (h) h.style.display = hint ? "block" : "none";
    show("faNotice", true);
  }

  // ---- 渲染 -----------------------------------------------------------------

  var current = null;   // 最近一次拿到的凭证，供按钮判断用

  function renderChain(chain, chainValid) {
    var box = $("faChain");
    if (!box) return;
    box.innerHTML = "";
    var steps = (chain || []).slice().reverse();   // 后端给的是倒序，凭证按时间正着读
    for (var i = 0; i < steps.length; i++) {
      var c = steps[i] || {};
      var pair = stepOf(c.action);
      var row = document.createElement("div");
      row.style.cssText = "display:flex;align-items:center;gap:11px;min-height:64px;" +
        "padding:9px 0;border-bottom:1px solid var(--line)";

      var img = document.createElement("img");
      img.src = "../art/png/" + pair[1] + ".png";
      img.alt = "";
      img.style.cssText = "width:38px;height:38px;object-fit:contain;flex:0 0 38px";

      var mid = document.createElement("div");
      mid.style.cssText = "flex:1;min-width:0";
      var name = document.createElement("b");
      name.style.cssText = "display:block;font-size:17px;line-height:1.3";
      name.textContent = pair[0];
      var meta = document.createElement("small");
      meta.className = "muted";
      meta.style.cssText = "display:block;margin-top:4px;font-size:13px";
      var stamp = when(c.at);
      meta.textContent = actorOf(c.by) + (stamp ? "　" + stamp : "");
      mid.appendChild(name);
      mid.appendChild(meta);

      var seal = document.createElement("span");
      seal.style.cssText = "flex:0 0 auto;font-size:13px;color:#7a5a2e;" +
        "font-family:ui-monospace,SFMono-Regular,Menlo,Consolas,monospace;" +
        "letter-spacing:.04em;background:rgba(255,251,243,.92);" +
        "border:1px solid rgba(150,116,72,.42);border-radius:9px;padding:4px 8px";
      var d8 = digest8(c.digest);
      if (d8) {
        seal.textContent = d8;
      } else {
        seal.textContent = "没有摘要";
        seal.style.fontFamily = "inherit";
        seal.style.color = "var(--muted)";
      }

      row.appendChild(img);
      row.appendChild(mid);
      row.appendChild(seal);
      box.appendChild(row);
    }
    if (box.lastChild) box.lastChild.style.borderBottom = "0";
    text("faChainNote", chainValid
      ? "这一笔共 " + steps.length + " 步，整条链重新算过一遍，没有被动过。"
      : "整条链校验没有通过，先别点头，请联系家里其他人。");
    show("faChainTitle", steps.length > 0);
    show("faChainCard", steps.length > 0);
  }

  function render(cert) {
    current = cert;
    var pair = statusOf(cert.status);

    // 两条分支都把字号和颜色写回去。只在「取不到」那一条里改样式的话，
    // 第二次渲染（点完同意会再取一次）拿到金额时，字还留在上一次的灰色小号上。
    var amountEl = $("faAmount");
    if (amountEl) {
      if (cert.amount) {
        amountEl.textContent = "¥" + cert.amount;
        amountEl.style.fontSize = "";
        amountEl.style.color = "";
      } else {
        amountEl.textContent = "金额没有取到";
        amountEl.style.fontSize = "19px";
        amountEl.style.color = "var(--muted)";
      }
    }

    var chip = $("faStatus");
    if (chip) {
      chip.textContent = pair[0];
      chip.style.color = pair[1];
      chip.style.background = pair[2];
    }

    text("faCompany", cert.company || "还没有取到");
    text("faPid", cert.id || "");

    // 发起人不是编的：审计链最早的那一条是谁写的，谁就是发起人。
    var chain = cert.chain || [];
    text("faInitiator", chain.length ? actorOf(chain[chain.length - 1].by) : "还没有记录");

    show("faEmpty", false);
    show("faBill", true);
    renderChain(chain, cert.chainValid);

    var waiting = cert.status === "awaiting_family_approval";
    var done = cert.status === "completed";

    text("faLead", waiting ? "这一笔在等您点头"
                : done     ? "这一笔已经办好了"
                           : "这一笔还没有走到您这一步");

    show("faApprove", waiting);
    show("faApproveHint", waiting);
    show("faLater", waiting);
    show("faCert", done);
  }

  function renderEmpty() {
    current = null;
    text("faLead", "");
    show("faEmpty", true);
    show("faBill", false);
    show("faChainTitle", false);
    show("faChainCard", false);
    show("faNotice", false);
    show("faApprove", false);
    show("faApproveHint", false);
    show("faLater", false);
    show("faCert", false);
  }

  // ---- 取数：**只读**。这里一个 POST 都不许有。 ------------------------------

  function load() {
    var pid = sessionStorage.getItem(PID_KEY);
    if (!pid) { renderEmpty(); return Promise.resolve(); }
    return window.YouhuoAPI.get("/payments/" + encodeURIComponent(pid) + "/certificate")
      .then(function (cert) {
        if (cert && cert.id) { render(cert); } else { renderEmpty(); }
      })
      .catch(function (err) {
        console.warn(err);
        var g = guardDetail(err);
        if (g.code === 404) {
          // 事务号还在 sessionStorage 里，但库里没有这件事（换了数据库、清了演示数据）。
          // 这不该显示成一张空凭证。
          renderEmpty();
          return;
        }
        renderEmpty();
        notice("guard", g.detail || "暂时取不到这一笔的信息。",
               "请稍后再打开一次；这期间这笔钱不会被扣。");
      });
  }

  // ---- 唯一允许发 POST 的地方：用户按下「同意并办理」 ------------------------

  function approve() {
    var pid = sessionStorage.getItem(PID_KEY);
    if (!pid) { renderEmpty(); return; }
    var btn = $("faApprove");
    if (btn) { btn.disabled = true; btn.textContent = "正在办理…"; }

    window.YouhuoAPI.post("/payments/" + encodeURIComponent(pid) + "/family-approve", {})
      .then(function (res) {
        var who = (res && res.approvedBy) || "";
        if (typeof window.toast === "function") {
          window.toast((res && res.message) || "已确认，这一笔办好了。");
        }
        notice("done",
               who ? who + "已确认，这一笔办好了。" : "已确认，这一笔办好了。",
               who ? "凭证上「是谁点的头」写的就是" + who + "，不是老人自己。" : "");
        // 重新取一次凭证：状态、审计链都要是**服务端说的**，不是前端自己改的。
        return load();
      })
      .catch(function (err) {
        console.warn(err);
        var g = guardDetail(err);
        if (g.code === 409 && g.detail) {
          // 守卫在说话。原样显示它那句，不要说成「操作失败」。
          notice("guard", g.detail,
                 "这不是出错——要先由老人把金额复述对，才轮到您点头。");
        } else if (g.detail) {
          notice("guard", g.detail, "");
        } else {
          notice("guard", "这一笔现在没能确认。",
                 "钱没有动。请稍后再试一次，或联系家里其他人。");
        }
        return load();
      })
      .then(function () {
        if (btn) { btn.disabled = false; btn.textContent = "同意并办理"; }
      });
  }

  function later() {
    if (typeof window.toast === "function") {
      window.toast("先不办，这一笔仍旧等着您");
    }
    notice("guard", "先不办。",
           "这一笔还等着您，钱没有动，您随时可以回来点头。");
    var btn = $("faLater");
    if (btn) btn.disabled = true;
    // 1.6 秒再走。这一段是给人**读**的：目标用户视力和记忆力都在下降，
    // 一句话闪一下就跳页，等于没有反馈。
    setTimeout(function () {
      if (window.history.length > 1) { window.history.back(); }
      else if (typeof window.go === "function") { window.go("home"); }
    }, 1600);
  }

  // ---- 装配 -----------------------------------------------------------------
  //
  // 按钮走自己的监听，**不用 `data-action`**：app.js 的全局分发器只认它自己那串
  // if 链，塞一个它不认得的 action 进去，按下会静默地什么都不发生。

  function init() {
    var approveBtn = $("faApprove");
    if (approveBtn) approveBtn.addEventListener("click", approve);
    var laterBtn = $("faLater");
    if (laterBtn) laterBtn.addEventListener("click", later);
    load();
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();
