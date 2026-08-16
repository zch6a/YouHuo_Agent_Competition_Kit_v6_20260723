
const NAV_PAGE_MAP={
  "home.html":"home",
  "voice-listening.html":"voice",
  "recognition.html":"home",
  "bill-detail.html":"home",
  "voice-confirm.html":"home",
  "payment-success.html":"home",
  "records.html":"records",
  "services.html":"services",
  "certificate.html":"home",
  "profile.html":"profile"
};

function currentPageFile(){
  return location.pathname.split("/").pop() || "home.html";
}
function mountGlobalNav(){
  document.querySelectorAll(".nav,.global-nav").forEach(n=>n.remove());
  const page=currentPageFile();
  const active=NAV_PAGE_MAP[page]||"home";
  const voiceAction=page==="voice-listening.html" ? "voice-start" : "nav-voice";
  const voiceClass=active==="voice" ? "nav-voice listening" : "nav-voice";
  const icon={
    home:`<svg viewBox="0 0 24 24"><path d="M3.5 10.6 12 3.4l8.5 7.2v8.2a1.7 1.7 0 0 1-1.7 1.7h-4.2v-6.8H9.4v6.8H5.2a1.7 1.7 0 0 1-1.7-1.7z"/></svg>`,
    records:`<svg viewBox="0 0 24 24"><rect x="5.2" y="4.1" width="13.6" height="16.2" rx="2"/><path d="M9 4V2.5h6V4M8.3 9h7.4M8.3 13h7.4M8.3 17h4.7"/></svg>`,
    services:`<svg viewBox="0 0 24 24"><path d="M12 20.5c-3.6-2.8-7.6-5.2-7.6-8.8a3.8 3.8 0 0 1 6.8-2.4A3.8 3.8 0 0 1 18 11.7c0 3.6-2.4 5.9-6 8.8Z"/><path d="M12 20V10"/></svg>`,
    profile:`<svg viewBox="0 0 24 24"><circle cx="12" cy="7.4" r="3.4"/><path d="M5.2 20.5c.5-4.8 2.8-7.2 6.8-7.2s6.3 2.4 6.8 7.2"/></svg>`
  };
  const html=`
    <nav class="global-nav" aria-label="主导航">
      <button class="nav-tab ${active==="home"?"active":""}" data-action="nav" data-to="home" aria-label="首页">
        ${icon.home}<span>首页</span>
      </button>
      <button class="nav-tab ${active==="records"?"active":""}" data-action="nav" data-to="records" aria-label="记录">
        ${icon.records}<span>记录</span>
      </button>
      <button class="${voiceClass}" data-action="${voiceAction}" aria-label="语音助手">
        <img src="../art/png/nav_voice_control.png" alt="">
      </button>
      <button class="nav-tab ${active==="services"?"active":""}" data-action="nav" data-to="services" aria-label="服务">
        ${icon.services}<span>服务</span>
      </button>
      <button class="nav-tab ${active==="profile"?"active":""}" data-action="nav" data-to="profile" aria-label="我的">
        ${icon.profile}<span>我的</span>
      </button>
      <i class="ios-indicator" aria-hidden="true"></i>
    </nav>`;
  document.querySelector(".phone")?.insertAdjacentHTML("beforeend",html);
}


const ROUTES={home:"home.html",listen:"voice-listening.html",recognize:"recognition.html",bill:"bill-detail.html",confirm:"voice-confirm.html",success:"payment-success.html",records:"records.html",services:"services.html",cert:"certificate.html",profile:"profile.html"};
function go(n){location.href=ROUTES[n]||n}function toast(m){let t=document.querySelector(".toast");if(!t){t=document.createElement("div");t.className="toast";document.body.appendChild(t)}t.textContent=m;t.classList.add("show");setTimeout(()=>t.classList.remove("show"),1800)}
// 后端拿不到的字段一律留空，**绝不显示写死的假值**。
// 原来的写法是 `if(val!==undefined) el.textContent=val`——null 会被写进去，
// 而 HTML 里那些 "68.40"/"李叔" 的兜底文本在请求失败时会原样留在屏幕上。
function bindData(data){
  document.querySelectorAll("[data-bind]").forEach(el=>{
    const val = el.dataset.bind.split(".").reduce((o,k)=>(o==null?undefined:o[k]), data);
    el.textContent = (val === undefined || val === null) ? "" : String(val);
  });
  hideEmptyRows();
}

// 一整行都没数据的时候，把这一行藏起来——否则会留下「☀️ 　 · 」这种
// 只剩标点的残行。标记在 HTML 上，不靠猜。
// 单独一个函数：清空字段的地方（识别页）也要重跑这一遍，
// 否则清掉的是文字，剩下的 `¥` 和 `••••` 还留在屏幕上。
function hideEmptyRows(){
  document.querySelectorAll("[data-hide-when-empty]").forEach(box=>{
    const bound = [...box.querySelectorAll("[data-bind]")];
    const empty = bound.length > 0 && bound.every(b => !(b.textContent||"").trim());
    box.hidden = empty;
  });
}

// 「今日安排」按真实提醒渲染。原稿这里是三条写死的行。
const AGENDA_ICON = {
  药: "home_schedule_pill", 血压: "home_schedule_pressure",
  活动: "home_schedule_people", 复诊: "home_schedule_pressure",
};
function iconFor(title){
  for (const k in AGENDA_ICON) if ((title||"").includes(k)) return AGENDA_ICON[k];
  return "home_schedule_people";
}
function renderAgenda(agenda){
  const list = document.querySelector("#todayList");
  if (!list) return;
  const items = (agenda && agenda.today) || [];
  list.innerHTML = "";
  if (!items.length){
    const p = document.createElement("p");
    p.className = "muted";
    p.style.padding = "14px 0";
    p.textContent = "今天没有安排。";
    list.appendChild(p);
  } else {
    for (const it of items){
      const line = document.createElement("div");
      line.className = "line";
      const left = document.createElement("span");
      left.className = "row";
      const img = document.createElement("img");
      img.src = "../art/png/" + iconFor(it.title) + ".png";
      img.alt = "";
      img.style.cssText = "width:32px;height:32px;object-fit:contain;margin-right:11px";
      left.appendChild(img);
      left.appendChild(document.createTextNode(it.time + "\u3000" + it.title));
      const right = document.createElement("b");
      right.style.color = it.done ? "#289957" : "#df7d1e";
      right.textContent = it.status;
      line.appendChild(left); line.appendChild(right);
      list.appendChild(line);
    }
  }
  // 「接下来」没有下一件时，给一句话，而不是留三行空白
  const none = document.querySelector("#agendaNextEmpty");
  if (none) none.hidden = !!(agenda && agenda.next);
  // 没有下一件事的时候，那个按钮也要跟着撤下。
  // 否则屏幕上是「今天没有要办的事」，下面挂着一个查看详情——详情是哪一件？
  const detail = document.querySelector("#homeFollowupDetail");
  if (detail) detail.hidden = !(agenda && agenda.next);
}
// ---- 识别结果页 --------------------------------------------------------------
// 跳一次页面，上一步的响应就没了。所以 `suggest-water` 把「说了什么」和
// 「引擎怎么回的」存进 sessionStorage，这里读回来——这两处原先是写死在
// HTML 里的一句「帮我交这个月的水费」，无论老人说什么都显示它。
function renderRecognition(){
  const heard = (sessionStorage.getItem("youhuo_heard") || "").trim();
  const reply = (sessionStorage.getItem("youhuo_reply") || "").trim();
  const said  = document.querySelector("#heardText");
  const echo  = document.querySelector("#engineReply");
  const claim = document.querySelector("#recogClaim");
  if (said) said.textContent = heard;
  if (echo) echo.textContent = reply;
  if (heard) return;

  // 一句话都没听到过。这一页不能顶着「我已理解您的需求」，更不能把
  // `/bills/water/current` 取来的当前账单当成「识别出来的结果」摆上去——
  // 那是凭空编一次理解，和凭证页写死「交易成功」是同一类错误。
  if (claim) claim.textContent = "还没有听到您说话";
  if (echo)  echo.textContent  = "请回到上一步，按住话筒说一句您要办的事。";
  const bill = document.querySelector("#recogBill");
  if (bill) bill.hidden = true;
  const box = said && said.closest(".card");
  if (box) box.hidden = true;
  document.querySelectorAll('[data-bind^="bill."]').forEach(el=>{ el.textContent = ""; });
  hideEmptyRows();
}

async function hydrate(){
  try{
    // agenda 只有首页要，其他页拿不到也不该报错——所以用 allSettled。
    const [profile, bill, agenda] = await Promise.allSettled([
      YouhuoAPI.get("/profile"),
      YouhuoAPI.get("/bills/water/current"),
      YouhuoAPI.get("/agenda"),
    ]);
    const v = r => (r.status === "fulfilled" ? r.value : null);
    bindData({profile: v(profile), bill: v(bill), agenda: v(agenda)});
    renderAgenda(v(agenda));

    // 识别结果页。放在 bindData 之后：它要覆盖掉刚被填进去的那张账单。
    if (document.querySelector("#heardText")) renderRecognition();

    // 记录页
    if (document.querySelector("#recordList")){
      _recordCache = await YouhuoAPI.get("/records");
      renderRecords("全部");
    }
    // 「我的」页的健康概览
    if (document.querySelector("#healthMetrics")){
      renderHealth(await YouhuoAPI.get("/health-summary"));
    }
    // 凭证页：事务号来自刚才那一笔，没有就说没有
    if (document.querySelector("#certElements")){
      const pid = sessionStorage.getItem("youhuo_payment_id");
      if (pid){
        renderCert(await YouhuoAPI.get(`/payments/${pid}/certificate`));
      } else {
        // 没有凭证：把金额、单位、状态全部清空。
        // 否则页面会拿着 `/bills/water/current` 的当前未付账单，
        // 配上写死的「交易成功」，凭空展示一张不存在的回执。
        document.querySelectorAll('[data-bind="bill.amount"],[data-bind="bill.company"],[data-bind="bill.paidAt"]')
          .forEach(el => { el.textContent = ""; });
        document.querySelectorAll("[data-cert-status]").forEach(el => {
          el.textContent = "还没有这一笔";
          el.style.color = "#8a8580";
        });
        const ok = document.querySelector("#certChainState");
        if (ok) ok.textContent = "还没有可展示的凭证，先办一笔事。";
      }
    }
  }catch(e){ console.warn(e) }
}document.addEventListener("DOMContentLoaded",()=>{mountGlobalNav();hydrate();});
document.addEventListener("click",async e=>{const el=e.target.closest("[data-action]");if(!el)return;const a=el.dataset.action;try{
if(a==="nav"){go(el.dataset.to);return}if(a==="back"){history.back();return}
if(a==="nav-voice"){await YouhuoAPI.post("/voice/sessions",{channel:"elder",entry:"global-nav"});go("listen");return}
if(a==="voice-start"){
  // 这一次开的会话**没有话**（没有语音识别，前端拿不到老人说了什么），
  // 所以引擎不可能理解任何东西。原来这里直接跳「识别结果」，那一页于是
  // 顶着「我已理解您的需求」+ 一张水费账单——而用户一个字都没说过。
  // 落到「正在听」：那是这一刻真实的状态。
  el.classList.add("pulse"); toast("正在听您说话…");
  await YouhuoAPI.post("/voice/sessions",{channel:"elder"});
  setTimeout(()=>go("listen"),650); return;
}
if(a==="suggest-water"){
  // 卡片上写的那句**就是**说出去的话，读它本身，不在这里另存一份。
  // 原来这里写死「帮我交这个月的水费」，而卡片上印的是「帮我找这个月的水费」——
  // 屏幕上那句和真正发给引擎的那句不是同一句，谁也不会发现。
  const said = (el.textContent || "").trim();
  const r = await YouhuoAPI.post("/voice/sessions",{utterance:said});
  // 存下来给识别页读——否则跳转一次，引擎的回复就没了。
  sessionStorage.setItem("youhuo_heard", said);
  const reply = r && r.understood && r.understood.reply;
  if (reply) sessionStorage.setItem("youhuo_reply", reply);
  else sessionStorage.removeItem("youhuo_reply");
  go("recognize"); return;
}
if(a==="recognition-continue"){go("bill");return}if(a==="repeat"){go("listen");return}
if(a==="bill-next"){
  // 记住 prepare 真正返回的事务号。
  // 原来这里丢掉了返回值，后面两步写死 "pay-demo-68"——对着 mock 能跑，
  // 一接真后端就是 404：真实事务号是服务端生成的。
  const r = await YouhuoAPI.post("/payments/prepare",{billId:"water-current"});
  if (r && r.id) sessionStorage.setItem("youhuo_payment_id", r.id);
  if (r && r.prompt) sessionStorage.setItem("youhuo_teach_prompt", r.prompt);
  go("confirm"); return;
}
if(a==="teach-back"){
  const pid = sessionStorage.getItem("youhuo_payment_id");
  if (!pid){ toast("这一笔还没有开始，请从账单进入"); return; }
  el.classList.add("pulse"); toast("正在核验复述内容…");
  // 复述内容取屏幕上真正要念的那一句，而不是写死一个金额——
  // 写死的话，无论账单是多少，前端都会「念对」。
  const said = (document.querySelector("[data-teach-text]")?.textContent || "").trim()
            || sessionStorage.getItem("youhuo_teach_prompt") || "";
  const r = await YouhuoAPI.post(`/payments/${pid}/teach-back`, {text: said});
  if (r.matched === false){
    toast(r.message || "没有听清，请再说一遍");
    el.classList.remove("pulse");
    return;
  }
  const done = await YouhuoAPI.post(`/payments/${pid}/execute`, {});
  if (done && done.message) toast(done.message);
  setTimeout(()=>go("success"), 700);
  return;
}
if(a==="cancel-payment"){go("bill");return}if(a==="help"){document.querySelector("#helpModal")?.classList.add("show");return}if(a==="close-modal"){el.closest(".modal")?.classList.remove("show");return}
if(a==="open-cert"){go("cert");return}if(a==="home"){go("home");return}
if(a==="records-filter"){
  document.querySelectorAll("[data-action=records-filter]").forEach(x=>x.classList.remove("active"));
  el.classList.add("active");
  // 真的筛，不是弹一个 toast 假装筛了。
  renderRecords(el.dataset.kind || el.textContent.trim());
  return;
}
if(a==="service"){toast(el.dataset.service+"：这一项还没有做好");return}if(a==="cert-detail"){toast(el.dataset.label+"：这一项的详情还没有做好");return}
if(a==="emergency"){document.querySelector("#sosModal")?.classList.add("show");return}if(a==="emergency-confirm"){await YouhuoAPI.post("/emergency/call",{source:"elder-app"});el.closest(".modal")?.classList.remove("show");toast("正在联系紧急联系人");return}
}catch(err){console.error(err);toast("操作失败，请稍后重试")}});

// ---- 记录页：真实审计流水 ----------------------------------------------------
let _recordCache = null;
function renderRecords(kind){
  const box = document.querySelector("#recordList");
  if (!box || !_recordCache) return;
  const items = (_recordCache.items || []).filter(
    it => !kind || kind === "全部" || it.kind === kind);
  box.innerHTML = "";
  if (!items.length){
    const p = document.createElement("p");
    p.className = "muted"; p.style.padding = "24px 0"; p.style.textAlign = "center";
    p.textContent = "这一类还没有记录。";
    box.appendChild(p); return;
  }
  for (const it of items){
    const row = document.createElement("div");
    row.className = "row";
    row.style.cssText = "min-height:96px;gap:12px;border-bottom:1px solid var(--line)";
    const img = document.createElement("img");
    img.src = "../art/png/" + (it.icon || "record_request") + ".png"; img.alt = "";
    img.style.cssText = "width:56px;height:56px;object-fit:contain";
    const mid = document.createElement("div"); mid.style.flex = "1";
    const t = document.createElement("b"); t.style.fontSize = "19px"; t.textContent = it.title;
    mid.appendChild(t);
    if (it.note){
      const n = document.createElement("div");
      n.className = "muted"; n.style.marginTop = "6px"; n.textContent = it.note;
      mid.appendChild(n);
    }
    const right = document.createElement("div");
    right.style.textAlign = "right"; right.textContent = it.time;
    row.appendChild(img); row.appendChild(mid); row.appendChild(right);
    box.appendChild(row);
  }
}

// ---- 凭证页：真实审计链 ------------------------------------------------------
const CERT_LABEL = {voiceTeachBack:"语音复述凭证", location:"位置凭证",
                    device:"设备凭证", time:"时间凭证"};
// 状态 → 给人看的说法。**只有真的付掉了才敢说「交易成功」。**
const CERT_STATE = {
  completed:                 ["交易成功",       "#2b9955"],
  executing:                 ["正在办理",       "#df7d1e"],
  awaiting_family_approval:  ["等家人点头",     "#df7d1e"],
  awaiting_elder_confirmation:["等您确认",      "#df7d1e"],
  collecting:                ["还在准备",       "#df7d1e"],
  cancelled:                 ["已取消",         "#8a8580"],
  failed:                    ["没有办成",       "#c0392b"],
};
function renderCert(cert){
  const box = document.querySelector("#certElements");
  if (!box || !cert) return;

  // 这一页的每一个字都来自这一笔凭证自己。
  //
  // 原来金额和单位是 hydrate() 从 `/bills/water/current`（当前**未付**账单）
  // 绑上去的，和这张凭证毫无关系；而「✓ 交易成功」是写死的静态徽章。
  // 两者叠在一起的后果：一笔还在等家人点头的钱，页面上写着「交易成功」。
  // 那是这个产品最不能犯的错——回执不许宣称一笔并未发生的交易。
  const put = (sel, text) => {
    const el = document.querySelector(sel);
    if (el) el.textContent = text == null ? "" : String(text);
  };
  if (cert.amount) put('[data-bind="bill.amount"]', cert.amount);
  if (cert.company) put('[data-bind="bill.company"]', cert.company);

  const [word, color] = CERT_STATE[cert.status] || ["还在办", "#df7d1e"];
  document.querySelectorAll("[data-cert-status]").forEach(el => {
    el.textContent = word;
    el.style.color = color;
  });

  box.innerHTML = "";
  const el = cert.elements || {};
  for (const key of ["voiceTeachBack","location","device","time"]){
    const btn = document.createElement("button");
    btn.className = "line";
    btn.style.cssText = "width:100%;border:0;border-bottom:1px solid var(--line);background:none;text-align:left";
    btn.dataset.action = "cert-detail";
    btn.dataset.label = CERT_LABEL[key];
    const name = document.createElement("span"); name.textContent = CERT_LABEL[key];
    const val = document.createElement("span");
    if (el[key]){
      val.textContent = el[key] + "　›";
    } else {
      // 没有就说没有。摆一个「北京·朝阳区」比少一行糟得多——
      // 这一页的全部价值就是「上面每一条都能查」。
      val.textContent = "还没有采集";
      val.className = "muted";
    }
    btn.appendChild(name); btn.appendChild(val);
    box.appendChild(btn);
  }
  const ok = document.querySelector("#certChainState");
  if (ok){
    ok.textContent = cert.chainValid
      ? `这一笔共 ${(cert.chain||[]).length} 步，整条链校验通过。`
      : "整条链校验没通过，请联系家人。";
  }
}

// ---- 「我的」页：健康概览 -----------------------------------------------------
//
// 原稿这里是四个编出来的数字（今日健康 良好 / 心率 72 / 血压 120/78 / 睡眠 7.5 小时）。
// 后端的实情是一张健康事件表——记了什么才有什么，而且完全没有睡眠这一项。
// 所以这里渲染的是「记到了什么」，一条没有就说一条没有。
function renderHealth(sum){
  const box = document.querySelector("#healthMetrics");
  const note = document.querySelector("#healthNote");
  if (!box) return;
  box.innerHTML = "";
  const metrics = (sum && sum.metrics) || [];
  for (const m of metrics){
    const cell = document.createElement("div");
    cell.style.cssText = "flex:1;min-width:88px";
    const label = document.createElement("small");
    label.className = "muted"; label.textContent = m.label || "";
    const value = document.createElement("b");
    value.style.cssText = "display:block;font-size:22px;margin-top:4px";
    value.textContent = (m.value == null ? "还没有" : String(m.value)) +
                        (m.value != null && m.unit ? " " + m.unit : "");
    cell.appendChild(label); cell.appendChild(value);
    box.appendChild(cell);
  }
  box.style.display = metrics.length ? "flex" : "none";
  box.style.gap = "12px";
  if (note){
    note.textContent = (sum && sum.note) || "";
    note.hidden = !note.textContent;
  }
}