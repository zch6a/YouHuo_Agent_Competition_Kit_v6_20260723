/* 紧急联系人页。
 *
 * 名单来自 `GET /api/v1/contacts`，一位都不写死。
 *
 * **这个接口不返回电话号码。** 后端的 `actors` 表只有 id / family_id / role /
 * display_name，`phone` 永远是 `null`。所以这一页不画号码，也不画「138****8888」
 * 这种看起来像真的的东西——老人会真的按下去，然后拨错人。没有就说没有，
 * 并且告诉他这件事该找谁补。
 *
 * 「紧急呼叫」是真的：`POST /api/v1/emergency/call` 会写一条审计。因为它是真的，
 * 所以先弹一次确认，再把服务端回的那句话原样 toast 出来，并在页面上留下一条状态，
 * 而不是弹一下就消失——老人多半来不及看完 toast。
 *
 * 字号 / 高对比跟着 `GET /api/v1/settings` 走：在设置页调大的字，走到这一页还是大的。
 * 做法和 page-settings.js 一样——改 `<html>` 上的 `--fs`，页面里每一处正文的
 * 行内样式写的是 `calc(Npx * var(--fs,1))`（app.css 里那些绝对 px 不这样盖不住）。
 */

(function () {
  "use strict";

  //: 角色 → 用哪张已有的美术图。后端的 role 只会是「家人」「系统」「本人」三个中文值。
  //: 认不出来的按家人画，宁可画错一张图，也不要一个 404 的空位。
  var ROLE_ART = { "家人": "record_family", "系统": "brand_mark", "本人": "avatar" };

  var CONTRAST_VARS = {
    "--ink": "#100d0a",
    "--muted": "#38322b",
    "--line": "rgba(52,36,20,.42)",
    "--card": "#fffdf8",
    "--paper": "#fffdf6",
    "--paper2": "#fffdf6"
  };

  var busy = false;

  function fs(px) {
    return "calc(" + px + "px * var(--fs,1))";
  }

  function artFor(role) {
    var name = ROLE_ART[role] || "record_family";
    return "../art/png/" + name + ".png";
  }

  // ---- 字号 / 高对比：和设置页同一套 -----------------------------------------

  function applyDisplaySettings(payload) {
    var root = document.documentElement;
    var scale = Number(payload && payload.fontScale);
    if (!isFinite(scale)) scale = 1;
    scale = Math.min(Math.max(scale, 0.9), 1.6);
    root.style.setProperty("--fs", String(scale));
    root.style.fontSize = (16 * scale).toFixed(2) + "px";

    var on = !!(payload && payload.highContrast);
    for (var key in CONTRAST_VARS) {
      if (!Object.prototype.hasOwnProperty.call(CONTRAST_VARS, key)) continue;
      if (on) root.style.setProperty(key, CONTRAST_VARS[key]);
      else root.style.removeProperty(key);
    }
    var scenes = document.querySelectorAll(".scene");
    for (var i = 0; i < scenes.length; i++) {
      var el = scenes[i];
      if (el.dataset.baseOpacity === undefined) {
        el.dataset.baseOpacity = el.style.opacity || "";
      }
      el.style.opacity = on ? ".1" : el.dataset.baseOpacity;
    }
  }

  // ---- 名单 ------------------------------------------------------------------

  // 「还没有留电话」这枚标记。字号跟着 --fs 走（最大档 20.8px，整枚 145px 宽），
  // 所以它和称呼是真的在抢那一行的宽度——量出来最大档只剩 13px 余量。
  // `margin-left:auto` 是**兜底**：万一哪一家的称呼长到挤不下，它折行之后仍然贴右边，
  // 看起来是「换了一行」而不是「掉到图标底下去了」。
  function noPhoneFlag() {
    var flag = document.createElement("span");
    flag.className = "service-flag";
    flag.style.cssText = "font-size:" + fs(13) + ";flex:0 0 auto;margin-left:auto";
    flag.textContent = "还没有留电话";
    return flag;
  }

  function firstBadge() {
    var badge = document.createElement("span");
    badge.style.cssText =
      "padding:5px 11px;border-radius:10px;background:#fdefd8;color:#82500e;" +
      "border:1px solid #dcb076;font-weight:700;line-height:1.2;white-space:nowrap;" +
      "font-size:" + fs(13);
    badge.textContent = "第一个联系";
    return badge;
  }

  function portrait(role, size) {
    var img = document.createElement("img");
    img.src = artFor(role);
    img.alt = "";
    img.style.cssText =
      "width:" + size + "px;height:" + size + "px;object-fit:contain;flex:0 0 " + size + "px";
    return img;
  }

  function renderPrimary(person) {
    var box = document.querySelector("#primaryBox");
    var title = document.querySelector("#primaryTitle");
    if (!box || !title) return;
    box.innerHTML = "";
    if (!person) { box.hidden = true; title.hidden = true; return; }

    var head = document.createElement("div");
    head.className = "row";
    head.style.gap = "13px";
    head.appendChild(portrait(person.role, 64));

    var copy = document.createElement("div");
    copy.style.cssText = "min-width:0;flex:1";
    var nameRow = document.createElement("div");
    nameRow.className = "row";
    nameRow.style.cssText = "gap:9px;flex-wrap:wrap;row-gap:6px";
    var name = document.createElement("b");
    name.style.fontSize = fs(25);
    name.textContent = person.name || "这一位还没有称呼";
    nameRow.appendChild(name);
    nameRow.appendChild(firstBadge());
    copy.appendChild(nameRow);
    var role = document.createElement("div");
    role.className = "muted";
    role.style.cssText = "margin-top:6px;font-size:" + fs(15);
    role.textContent = person.role || "";
    copy.appendChild(role);
    head.appendChild(copy);
    box.appendChild(head);

    var phoneLine = document.createElement("div");
    phoneLine.className = "line";
    phoneLine.style.cssText =
      "border-bottom:0;min-height:56px;margin-top:8px;flex-wrap:wrap;row-gap:8px;font-size:" + fs(17);
    var label = document.createElement("span");
    label.className = "muted";
    label.textContent = "电话";
    phoneLine.appendChild(label);
    phoneLine.appendChild(noPhoneFlag());
    box.appendChild(phoneLine);

    var why = document.createElement("p");
    why.className = "muted";
    why.style.cssText = "margin:2px 0 0;font-size:" + fs(15);
    why.textContent = "急事的时候，优活先联系这一位。";
    box.appendChild(why);

    box.hidden = false;
    title.hidden = false;
  }

  function renderOthers(people) {
    var box = document.querySelector("#otherBox");
    var title = document.querySelector("#otherTitle");
    if (!box || !title) return;
    box.innerHTML = "";
    if (!people.length) { box.hidden = true; title.hidden = true; return; }

    for (var i = 0; i < people.length; i++) {
      var person = people[i];
      var line = document.createElement("div");
      line.className = "line";
      line.style.cssText =
        "min-height:66px;gap:10px;flex-wrap:wrap;row-gap:6px;font-size:" + fs(17);
      if (i === people.length - 1) line.style.borderBottom = "0";

      var left = document.createElement("span");
      left.className = "row";
      left.style.cssText = "gap:10px;min-width:0";
      left.appendChild(portrait(person.role, 40));

      var copy = document.createElement("span");
      copy.className = "line-copy";
      // `.line-copy` 自带 12px 的右内边距。在这一行它是纯浪费：右边紧接着就是
      // 「还没有留电话」，而最大档下整行只差 3px 就放不下——量出来就是这 12px 的事。
      copy.style.paddingRight = "0";
      var name = document.createElement("b");
      name.style.fontSize = fs(19);
      name.textContent = person.name || "这一位还没有称呼";
      var role = document.createElement("small");
      role.className = "muted";
      role.style.fontSize = fs(13);
      role.textContent = person.role || "";
      copy.appendChild(name);
      copy.appendChild(role);
      left.appendChild(copy);

      line.appendChild(left);
      line.appendChild(noPhoneFlag());
      box.appendChild(line);
    }
    box.hidden = false;
    title.hidden = false;
  }

  function renderContacts(payload) {
    var items = (payload && payload.items) || [];
    var primary = null;
    var others = [];
    for (var i = 0; i < items.length; i++) {
      if (items[i] && items[i].primary && !primary) primary = items[i];
      else others.push(items[i]);
    }
    renderPrimary(primary);
    renderOthers(others);

    var empty = document.querySelector("#contactsEmpty");
    if (empty) empty.hidden = items.length > 0;
    // 名单为空的时候，上面两块都藏了；那句空话要顶到原本第一块卡片的位置，
    // 否则它会贴在副标题底下，和山水图层叠在一起。
    if (empty && items.length === 0) empty.style.marginTop = "108px";

    // 山水那一段留白（108px）挂在**第一块真正露出来的**标题上。
    // 写死在「主要联系人」那一块行不通：没有主要联系人时它是藏着的，
    // 「其他联系人」就会紧贴副标题，正好压在山水图层上。
    var primaryTitle = document.querySelector("#primaryTitle");
    var otherTitle = document.querySelector("#otherTitle");
    if (primaryTitle && !primaryTitle.hidden) {
      primaryTitle.style.marginTop = "108px";
      if (otherTitle) otherTitle.style.marginTop = "20px";
    } else if (otherTitle && !otherTitle.hidden) {
      otherTitle.style.marginTop = "108px";
    }
  }

  // ---- 紧急呼叫 --------------------------------------------------------------

  function openModal(id) {
    var modal = document.querySelector("#" + id);
    if (modal) modal.classList.add("show");
  }

  function closeModals() {
    var modals = document.querySelectorAll(".modal.show");
    for (var i = 0; i < modals.length; i++) modals[i].classList.remove("show");
  }

  function stamp() {
    var now = new Date();
    return now.getHours() + "点" + ("0" + now.getMinutes()).slice(-2) + "分";
  }

  async function callEmergency(button) {
    if (busy) return;
    busy = true;
    var label = button.textContent;
    button.disabled = true;
    button.textContent = "正在联系…";
    try {
      var reply = await YouhuoAPI.post("/emergency/call", { source: "elder-app" });
      closeModals();
      toast((reply && reply.message) || "已记录这次呼叫。");
      var state = document.querySelector("#sosState");
      if (state) {
        // toast 一秒八就没了，老人多半来不及看完。页面上留一条，看多久都行。
        state.textContent = stamp() + "，已经记下这次呼叫，优活正在按上面的顺序联系。";
        state.hidden = false;
      }
    } catch (err) {
      console.warn(err);
      toast("没有呼出去，请再按一次，或者直接给家人打电话。");
    } finally {
      button.disabled = false;
      button.textContent = label;
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
    var opener = e.target.closest("[data-open]");
    if (opener) { openModal(opener.getAttribute("data-open")); return; }
    var closer = e.target.closest("[data-close]");
    if (closer) { closeModals(); return; }
    var sos = e.target.closest("[data-sos]");
    if (sos && sos.getAttribute("data-sos") === "confirm") { callEmergency(sos); return; }
    var back = e.target.closest("[data-goback]");
    if (back) { goBack(); return; }
  });

  document.addEventListener("DOMContentLoaded", async function () {
    // app.js 的 `mountGlobalNav()` 在同一个事件里先跑，而 `NAV_PAGE_MAP` 里没有这一页，
    // 底部会亮「首页」。这一页是从「我的」进来的，把高亮挪回去——只动 DOM，不碰 app.js。
    var tabs = document.querySelectorAll(".global-nav .nav-tab");
    for (var i = 0; i < tabs.length; i++) {
      tabs[i].classList.toggle("active", tabs[i].getAttribute("data-to") === "profile");
    }

    try {
      applyDisplaySettings(await YouhuoAPI.get("/settings"));
    } catch (err) {
      console.warn(err);   // 设置读不到就按默认字号显示，这一页的正事不受影响
    }
    try {
      renderContacts(await YouhuoAPI.get("/contacts"));
    } catch (err) {
      console.warn(err);
      renderContacts(null);
      toast("联系人没有读出来，请稍后再看。");
    }
  });
})();
