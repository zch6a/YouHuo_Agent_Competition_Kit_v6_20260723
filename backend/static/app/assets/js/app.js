
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
  "profile.html":"profile",
  // 这七页不加进来的话，`mountGlobalNav` 会落到默认值 "home"——
  // 于是站在「用药提醒」上，底部高亮的是「首页」。那不是少一个高亮，
  // 是**告诉用户他在别的地方**。
  "medication.html":"services",     // 从「服务」和「我的」都能进，归服务
  "schedule.html":"home",           // 今日安排就是首页那两张卡的展开
  "contacts.html":"services",
  "settings.html":"profile",
  "health.html":"services",
  "me.html":"profile",
  "family-approve.html":"home"      // 缴费那条链整条都归首页（账单/复述/成功/凭证同）
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


const ROUTES={
  home:"home.html", listen:"voice-listening.html", recognize:"recognition.html",
  bill:"bill-detail.html", confirm:"voice-confirm.html", success:"payment-success.html",
  records:"records.html", services:"services.html", cert:"certificate.html",
  profile:"profile.html",
  // 下面六个是这一轮新建的。加它们的理由：原先有 20 个控件点下去只弹一句
  // 「还没有做好」——用户要的是「点击需要有反馈或者跳转界面或者进入当前功能」。
  med:"medication.html",        // 用药提醒
  schedule:"schedule.html",     // 今日安排 / 就医安排
  contacts:"contacts.html",     // 紧急联系人
  settings:"settings.html",     // 字号与语音
  approve:"family-approve.html",// 家人点头——闭环原先在界面上点不到
  health:"health.html",         // 健康助手
  me:"me.html",                 // 我的资料
};
//: 「服务」类控件点下去到哪儿。**这是唯一的映射源。**
//:
//: 原先这 19 个控件共用一句 toast「入口已预留，可直接接后端」——不但是工程话，
//: 而且它把「哪个格子该去哪」这件事整个抹掉了：19 个不同的功能，一句一样的话，
//: 谁也说不出少的是什么。写成表之后，缺一条就是表里少一行，是能指着看的。
//:
//: key 用 `data-service` 上那个中文名，因为那正是屏幕上印的字——
//: 屏幕上写「用药提醒」而代码里跳去别处，是这一轮刚修过的一类错误。
const SERVICE_DEST = {
  "用药提醒": "med",
  "紧急联系人": "contacts",
  "就医安排": "schedule",
  "今日事项": "schedule",
  "我的待办": "schedule",
  "复诊详情": "schedule",
  "我的账单": "bill",
  "我的凭证": "cert",
  "健康助手": "health",
  "设置": "settings",
  "字体与语音设置": "settings",
  "设备与安全": "settings",
  "我的资料": "me",
};

function go(n){location.href=ROUTES[n]||n}

// ---- 临时浮层：不预先写在每一页的 HTML 里，用到时才建 -----------------------
// 十个页面各写一遍同样的 `.modal` 只会漂——本项目已经为「同一段 markup 抄三份」
// 付过一次代价（底部导航条目数在页面之间不一致）。
function showSheet(title, lines, actions){
  document.querySelector("#appSheet")?.remove();
  const box = document.createElement("div");
  box.id = "appSheet";
  box.className = "modal show";
  const inner = document.createElement("div");
  inner.className = "modal-box";
  const h = document.createElement("h2"); h.textContent = title;
  inner.appendChild(h);
  for (const line of lines){
    const p = document.createElement("p");
    p.className = "muted";
    p.style.cssText = "margin:9px 0 0;font-size:16px;line-height:1.55";
    p.textContent = line;
    inner.appendChild(p);
  }
  for (const [label, route] of (actions || [])){
    const b = document.createElement("button");
    b.className = "btn secondary";
    b.style.cssText = "width:100%;margin-top:10px";
    b.dataset.action = "nav";
    b.dataset.to = route;
    b.textContent = label;
    inner.appendChild(b);
  }
  const ok = document.createElement("button");
  ok.className = "btn primary";
  ok.style.cssText = "width:100%;margin-top:14px";
  ok.dataset.action = "close-modal";
  ok.textContent = "知道了";
  inner.appendChild(ok);
  box.appendChild(inner);
  document.body.appendChild(box);
}

//: 「常用功能直达」这一格。它印在服务页上，而服务页本身就是功能列表——
//: 跳去它自己毫无意义。所以它做的是「把最常用的四个直接摆出来」，
//: 这正是它标签上写的那件事。
function openQuickMenu(){
  showSheet("常用功能", ["下面这四件是用得最多的。"], [
    ["用药提醒", "med"],
    ["紧急联系人", "contacts"],
    ["我的账单", "bill"],
    ["办理记录", "records"],
  ]);
}

//: 完整审计链。凭证页默认只列四个凭证要素，链本身是这个产品的核心，
//: 但原先「查看完整凭证」点了只弹一句「可接凭证详情接口」。
let _certCache = null;
function showChainSheet(){
  const chain = (_certCache && _certCache.chain) || [];
  if (!chain.length){
    showSheet("完整凭证", ["这一笔还没有可展示的链。"]);
    return;
  }
  const who = {"elder-demo":"老人本人","daughter-demo":"女儿","son-demo":"儿子","system-demo":"优活系统"};
  // 兜底**不许**是 `c.action` 本身。原先就是那么写的，而这一页正是「界面上不许
  // 出现英文枚举」最该成立的地方：实测一笔念错过一次的缴费，完整链上会出现
  // `TEACH_BACK_REJECTED` 与 `TASK_SLOT_CORRECTED` 两行裸码。
  //
  // 兜底那句话也不许等于任何一个正常说法，否则「翻译成功」和「翻译失败」在屏幕上
  // 长得一样——`family3.js` 的 `note: '记录'` 撞上自己的 `|| '记录'` 就是这个形状。
  const lines = chain.map(c =>
    `${chainWord(c.action)}　·　${who[c.by] || c.by}　·　${String(c.digest||"").slice(0,8)}`);
  lines.push(_certCache.chainValid === true
    ? "整条链自校验通过：每一步的摘要都对得上。"
    : "这条链没有通过自校验，请联系家人。");
  showSheet("完整凭证", lines);
}

//: 审计事件 → 人话。词表在 `common.js::AUDIT_WORD`（**自称**那一份：这一页是
//: 老人在读自己的凭证），而那份又被判据钉在后端 `app_api.py::_WORDS` 上。
//:
//: 这里原先是一份**字面副本**，理由写在注释里：「`/app` 的页面不加载 common.js，
//: 而 HTML 不在这一轮的改动范围内」。那个理由已经不成立——`app/pages/` 下那十七页
//: 现在都在 `app.js` 之前加载 `/static/common.js`。
//:
//: （这一段刻意不写 `app/pages` 加通配加 `.html`：那串字符里有一个块注释起始符，
//: 而这个仓库有好几个剥注释的实现是「先剥块注释」——写在**行**注释里的一个起始符
//: 会让它们从这里一路吃到下一个块注释的结尾，把中间的代码整段吞掉。实测这个文件
//: 里下一个结尾符在 `page-family-approve.js` 是 130 行之后。）
//:
//: 为什么副本必须删掉而不是继续用判据钉住：一份被逐字节钉住的副本**仍然是两份**。
//: 「改一处忘另一处」那条路一步没少，只是从"静默不一致"变成"判据会红"——而屏幕上
//: 那句话已经错了一次，判据只是在事后喊。词表收成一份之后，那条路不存在。
//:
//: **不从 common.js 拿兜底那句话**，是它自己写明的设计：共享的是词表，不是兜底。
//: 这一页认不出来时说「留下一条记录」，因为老人的凭证页下面没有「完整记录」那一块，
//: 不能像 `/judge` 那样许一个不存在的去处。
//:
//: 表里那 17 条原先只有 8 条。实测一笔缴费办完之后，链上会出现 `TASK_SLOT_CORRECTED`
//: 与 `TEACH_BACK_REJECTED`（复述念错一次就有）——现在这一层不再需要有人手工补齐，
//: `common.js` 那份是照后端定的案。
function chainWord(action) {
  // 故意**不写** `(window.YouHuo && …) || {}`。common.js 没加载的时候，那个写法会让
  // 整条链的每一行都印「留下一条记录」——一屏看起来正常、内容全错的页面。直接取会
  // 抛 TypeError，被全局点击分发的 catch 接住并弹一句「操作失败」，那是看得见的。
  const words = window.YouHuo.AUDIT_WORD;
  const key = String(action == null ? "" : action);
  // 自有属性才算命中。方括号取值会把原型链算进来：`constructor` / `toString` 这种
  // 键会取到一个函数（真值），于是凭证的完整链上出现一行 `function Object() { … }`。
  // `common.js` 自己的每一处查表都写了这一句，理由同一个。
  if (!Object.prototype.hasOwnProperty.call(words, key)) return "留下一条记录";
  return words[key] || "留下一条记录";
}
function toast(m){let t=document.querySelector(".toast");if(!t){t=document.createElement("div");t.className="toast";document.body.appendChild(t)}t.textContent=m;t.classList.add("show");setTimeout(()=>t.classList.remove("show"),1800)}
// 后端拿不到的字段一律留空，**绝不显示写死的假值**。
// 原来的写法是 `if(val!==undefined) el.textContent=val`——null 会被写进去，
// 而 HTML 里那些 "68.40"/"李叔" 的兜底文本在请求失败时会原样留在屏幕上。
function bindData(data){
  document.querySelectorAll("[data-bind]").forEach(el=>{
    const val = el.dataset.bind.split(".").reduce((o,k)=>(o==null?undefined:o[k]), data);
    el.textContent = (val === undefined || val === null) ? "" : String(val);
  });
  fillGreeting(data);
  hideEmptyRows();
}

// 首页的问候语。HTML 里原先写死「上午好，」——实测凌晨零点半打开，
// 它照样说「上午好」。这一行是这一页最上面、字最大的一句话。
//
// 措辞照 `elder3.js::greeting()` 那五档来，不另起一套说法：同一个产品
// 在两个壳里对同一个时刻说两种话，是这个项目栽过的那件事。
function greetingWord(d){
  const h = (d || new Date()).getHours();
  if (h < 6)  return "夜里好";
  if (h < 11) return "早上好";
  if (h < 13) return "中午好";
  if (h < 18) return "下午好";
  return "晚上好";
}
function fillGreeting(data){
  const el = document.querySelector("#homeGreeting");
  if (!el) return;
  // 名字取不到就**不加逗号**，否则屏幕上是「早上好，」孤零零一个逗号收尾。
  // 这和 `hideEmptyRows()` 守的是同一件事：拿不到就别留标点残渣。
  const name = data && data.profile && data.profile.name;
  el.textContent = greetingWord() + (name ? "，" : "");
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
/* 成功页的标题按**真实状态**写，不写死。
 *
 * `paid` 才说办好了；`awaiting_family` 是「已提交，等家人点头」，
 * 那时一分钱都还没动。状态取不到就退回中性的说法，不许猜成成功。 */
const PAY_TITLE = {
  paid:            ["已经付好了", "这一笔已经完成"],
  awaiting_family: ["已提交，等家人点头", "家里第二个人确认之后才会真的付"],
};
function renderPaymentResult(){
  const head = document.querySelector("#payTitle");
  if (!head) return;
  let status = "";
  try{ status = (sessionStorage.getItem("youhuo_pay_status") || "").trim(); }catch(_){}
  const pair = PAY_TITLE[status];
  const sub  = document.querySelector("#paySub");
  if (pair){
    head.textContent = pair[0];
    if (sub) sub.textContent = pair[1];
  } else {
    //: 不知道就说不知道——比说成「支付成功」安全。
    head.textContent = "这一笔已经提交";
    if (sub) sub.textContent = "具体进展看下面的状态";
  }
  head.dataset.payStatus = status || "unknown";
}

function renderRecognition(){
  const heard = (sessionStorage.getItem("youhuo_heard") || "").trim();
  const reply = (sessionStorage.getItem("youhuo_reply") || "").trim();
  const said  = document.querySelector("#heardText");
  const echo  = document.querySelector("#engineReply");
  const claim = document.querySelector("#recogClaim");
  if (said) said.textContent = heard;
  if (echo) echo.textContent = reply;
  if (heard) {
    /* 听到了话——但**听懂了吗**？
     *
     * 原先这里直接 return，于是静态的「我已理解您的需求」原样留下，
     * `#recogBill` 也不收起。实测「我想吃红烧肉」「今天天气怎么样」
     * 「阿巴阿巴阿巴」全部回 `code:"chat" / taskType:null`，
     * 而屏幕上是「我已理解您的需求」＋一张 68.40 的水费单＋「继续办理 ›」。
     * 同一屏上还自相矛盾：紧挨着就写着「我在听。您可以说「帮我挂号」…」。
     *
     * 下面那一支（一句话都没听到）当初修对了，理由是「那是凭空编一次理解」；
     * 这一支是同一个理由。
     */
    const kind = (sessionStorage.getItem("youhuo_task_type") || "").trim();
    const bill = document.querySelector("#recogBill");
    if (!kind) {
      if (claim) claim.textContent = "没有听懂您说的事";
      //: 引擎那句回话本身就写着该怎么说（「您可以说「帮我挂号」…」），留着它。
      if (bill) bill.hidden = true;
      hideEmptyRows();
      return;
    }
    //: 听懂了，但不是缴费——给「帮我挂号」摆一张水费单是另一种编造。
    if (kind !== "bill_payment" && bill) bill.hidden = true;
    return;
  }

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

// ---- 账单：库里躺着三张，这套壳此前只认得水费 --------------------------------
//
// `SERVICE_DEST["我的账单"]` 指向账单页，而那一页从头到尾只画
// `/bills/water/current` 那一张。另外两张（电费、燃气费）在界面上**不存在**——
// 不是显示成 0，是根本没有位置放它们。老人问「除了水费还有什么要交」，
// 这个 App 答不上来。
//
// 挑中哪一张记在 sessionStorage 里，而不是只改账单页那一屏：复述页、成功页、
// 凭证页各是一份**独立文档**，只改一页的话，她在这里挑了电费，下一屏复述的
// 仍然是水费的金额——那正是这套壳最不能犯的那类错（回执不许宣称一笔并未
// 发生的交易）。整条链都读同一个分组，所以换要在装填之前换。
const BILL_PICK_KEY = "youhuo_bill_id";

//: 账单类型 → 用哪张已有的美术图。**只有水费有对得上的那一张**：
//: `bill_water_badge` 是一滴水。给电费配一滴水比不配图更糟，所以其余一律用
//: 那张通用的账单图（`suggest_bill_art`，一张带 ¥ 的收据）。
const BILL_ART = {"水费": "bill_water_badge"};
function billArt(type){
  return BILL_ART[String(type || "").replace(/支付$/, "")] || "suggest_bill_art";
}

// `2026-07-28` → `7月28日`。原样印一个 ISO 日期，对一位老人等于没说。
// 认不出来的原样返回，不猜：宁可难看，也不要把一个日期显示成另一个日期。
function billDay(iso){
  const m = /^(\d{4})-(\d{2})-(\d{2})$/.exec(String(iso || ""));
  return m ? `${Number(m[2])}月${Number(m[3])}日` : (iso || "");
}

//: `/bills` 与 `/bills/{id}` 回的形状（`AppBill`）和老端点
//: `/bills/water/current`（`AppWaterBill`）**不一样**，而且不能合并：
//: 前者有 paid / period / dueDate，没有 accountTail；后者反过来。
//: 页面上那些 `data-bind="bill.*"` 是按后者写的，所以挑中一张之后要翻成
//: 后者的形状——缺的那一项**留空**，不补一个看起来合理的值。
function billAsBound(row){
  if (!row) return null;
  const type = String(row.type || "");
  return {
    id: row.id,
    // 页面标题上印的是「水费支付」，而这个接口回的是「水费」。
    type: type ? (/支付$/.test(type) ? type : type + "支付") : "",
    amount: row.amount,
    company: row.company,
    month: row.month,
    // 这张单子的缴费账户后端没有给。留 null，`bindData` 会写空串，
    // 那一行随后被 `hideEmptyRows()` 收起来——比印一个「•••• ????」强。
    accountTail: null,
    paidAt: row.paidAt,
    dueDate: row.dueDate,
    status: row.status,
    paid: row.paid,
  };
}

// 她挑过别的账单就换成那一张，没挑过就是当前这张水费。
async function pickedBillOr(current){
  const picked = sessionStorage.getItem(BILL_PICK_KEY);
  if (!picked || (current && picked === current.id)) return current;
  try{
    return billAsBound(await YouhuoAPI.get("/bills/" + encodeURIComponent(picked)));
  }catch(e){
    // 这张单子取不到了（付掉了、换了一个月、id 过期）。不能顶着它继续走，
    // 更不能把上一张的金额摆出来冒充它——把挑选清掉，退回当前这张水费。
    console.warn(e);
    sessionStorage.removeItem(BILL_PICK_KEY);
    return current;
  }
}

// 账单页顶上那张卡：标题、图、缴费期限、现在什么状态。
// 这四处此前分别是写死的「水费支付」、写死的水滴图，以及**根本没有**。
function applyBillHead(bill){
  const badge = document.querySelector("#billBadge");
  if (badge){
    // 每一页自己的水费图**都不一样**（账单页是水滴徽章，复述页和成功页是另一枚，
    // 识别页又是第三枚）。第一次进来先把这一页原本那张记下来，
    // 换回水费时才还得回去——统一成同一张会把三页的美术抹平。
    if (badge.dataset.baseArt === undefined){
      badge.dataset.baseArt = badge.getAttribute("src") || "";
    }
    const type = String((bill && bill.type) || "");
    badge.src = (!type || /^水费/.test(type))
      ? badge.dataset.baseArt
      : "../art/png/" + billArt(type) + ".png";
  }
  const put = (rowSel, valSel, text) => {
    const row = document.querySelector(rowSel);
    const val = document.querySelector(valSel);
    if (!row || !val) return;
    val.textContent = text || "";
    row.hidden = !text;
  };
  put("#billDueRow", "#billDue", bill && bill.dueDate ? billDay(bill.dueDate) : "");
  put("#billStateRow", "#billState", (bill && bill.status) || "");
}

// 「这个月要缴的」——把这个家庭的账单全部摆出来，一张都不藏。
function renderBillRows(items, activeId){
  const list = document.querySelector("#billList");
  list.innerHTML = "";
  for (const it of items){
    const row = document.createElement("button");
    row.className = "line";
    // 和 `renderCert` 里那一排同一个写法：`.line` 管排版、分隔线和字号，
    // 这里只把按钮自带的边框、底色和居中去掉。
    row.style.cssText = "width:100%;border:0;border-bottom:1px solid var(--line);" +
      "background:none;text-align:left;gap:10px;font-family:inherit;color:inherit";
    row.dataset.action = "pick-bill";
    row.dataset.billId = it.id;

    const left = document.createElement("span");
    left.className = "row";
    const art = document.createElement("img");
    art.src = "../art/png/" + billArt(it.type) + ".png";
    art.alt = "";
    art.style.cssText = "width:38px;height:38px;object-fit:contain;margin-right:10px";
    left.appendChild(art);
    const copy = document.createElement("span");
    copy.className = "line-copy";
    const name = document.createElement("b");
    name.textContent = it.type || "";
    const meta = document.createElement("small");
    meta.className = "muted";
    // 只写后端真的给了的那几项。到期日没有就不写「到期」两个字。
    meta.textContent = [it.month, it.dueDate ? billDay(it.dueDate) + "到期" : ""]
      .filter(Boolean).join("　");
    copy.appendChild(name); copy.appendChild(meta);
    left.appendChild(copy);

    const right = document.createElement("span");
    right.className = "line-copy";
    const money = document.createElement("b");
    money.textContent = it.amount ? "¥" + it.amount : "";
    const state = document.createElement("small");
    state.className = "muted";
    state.textContent = it.status || "";
    right.appendChild(money); right.appendChild(state);

    row.appendChild(left); row.appendChild(right);

    if (it.id === activeId){
      row.setAttribute("aria-current", "true");
      const flag = document.createElement("span");
      flag.className = "service-flag";
      flag.textContent = "现在办这一张";
      right.appendChild(flag);
    }
    // 已经缴清的按不动：后端会回 409「这一张已经交过了」，
    // 一个按下去只会弹错误的按钮，不如一开始就说明白它按不了。
    if (it.paid) row.disabled = true;
    list.appendChild(row);
  }
}

async function renderBillList(shown){
  const list = document.querySelector("#billList");
  if (!list) return;
  const note = document.querySelector("#billListNote");
  const say = text => { if (note){ note.textContent = text; note.hidden = !text; } };
  let data = null;
  try{
    data = await YouhuoAPI.get("/bills");
  }catch(e){
    console.warn(e);
    // 读不出来就说读不出来。空列表和「这家没有账单」在屏幕上长得一模一样。
    say("这会儿没能把账单读出来，请稍后再看。");
    return;
  }
  const items = (data && data.items) || [];
  if (!items.length){
    say("这个月没有要缴的账单。");
    return;
  }
  say("");
  renderBillRows(items, (shown && shown.id) || null);
  const unpaid = Number(data.unpaidCount || 0);
  const total = document.querySelector("#billTotal");
  if (total){
    total.textContent = unpaid
      ? `还有 ${unpaid} 张没缴，一共 ${data.unpaidTotal} 元。`
      : "这个月的都缴清了。";
  }
}

// ---- 老人自己的字号与高对比，**每一页都要跟着** ----------------------------
//
// 设置页能把偏好存进后端，但那之前它**只在设置页自己生效**：`app.css` 里
// `--fs` 出现 0 次，别的十六页一个字都不会变大。一个只在设置页生效的字号设置，
// 比没有这个设置更糟——它让老人以为自己调过了。
//
// 变量设在 `<html>` 上而不是 `.phone` 上：`.modal` 是 position:fixed 且挂在
// `.phone` 外面，设在 `.phone` 上它够不着。
//
// 这一批变量名和 `page-settings.js` 里那份是同一套。两处写同样的值是重复，
// 但另一份归设置页所有；真正的事实源是后端 `GET /settings`，两边都读它。
const CONTRAST_VARS = {
  "--ink": "#100d0a",
  "--muted": "#38322b",
  "--line": "rgba(52,36,20,.42)",
  "--card": "#fffdf8",
  "--paper": "#fffdf6",
  "--paper2": "#fffdf6",
};

function applyPrefs(prefs){
  if (!prefs) return;
  const root = document.documentElement;
  const scale = Number(prefs.fontScale);
  // 服务端已经夹过范围（0.9–1.6）。这里只挡住 NaN——读不到就当没设过，
  // 而不是把整屏字号设成 NaN。
  if (Number.isFinite(scale) && scale > 0) root.style.setProperty("--fs", String(scale));
  for (const [key, value] of Object.entries(CONTRAST_VARS)){
    if (prefs.highContrast) root.style.setProperty(key, value);
    else root.style.removeProperty(key);
  }
}

async function hydrate(){
  try{
    // 语音进来的这一趟是一次**全新的**请求，上一次在账单页挑的那张不算数。
    // 不清掉的话：她上次挑了电费，这次说「帮我交这个月的水费」，
    // 识别页却摆着电费的金额——而她一个字都没提过电费。
    if (document.querySelector("#heardText")) sessionStorage.removeItem(BILL_PICK_KEY);

    // agenda 只有首页要，其他页拿不到也不该报错——所以用 allSettled。
    const [profile, bill, agenda, prefs] = await Promise.allSettled([
      YouhuoAPI.get("/profile"),
      YouhuoAPI.get("/bills/water/current"),
      YouhuoAPI.get("/agenda"),
      YouhuoAPI.get("/settings"),
    ]);
    const v = r => (r.status === "fulfilled" ? r.value : null);
    // 偏好先应用：晚一步应用会让整屏字号在眼前跳一下。
    applyPrefs(v(prefs));

    // 她挑过别的账单就换成那一张。**必须在 bindData 之前换**：复述页、成功页
    // 各是一份独立文档，它们身上没有那张列表，只有这个分组——换晚了，
    // 下一屏念的就是另一笔钱的金额。
    const shownBill = await pickedBillOr(v(bill));

    bindData({profile: v(profile), bill: shownBill, agenda: v(agenda)});
    renderAgenda(v(agenda));
    applyBillHead(shownBill);
    // 账单页：把这个家庭的账单**全部**列出来，不再只有水费那一件事可办。
    if (document.querySelector("#billList")) await renderBillList(shownBill);

    // 识别结果页。放在 bindData 之后：它要覆盖掉刚被填进去的那张账单。
    if (document.querySelector("#heardText")) renderRecognition();
  renderPaymentResult();

    // 记录页
    if (document.querySelector("#recordList")){
      //: 取数搬进 `renderRecords` 了（它现在按类别问服务端）。
      await renderRecords("全部");
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
        //
        // `bill.type` 也要清。它原先是写死的「水费支付」，这一轮改成了绑定值——
        // 不清的话，这一页会在「还没有这一笔」旁边顶着一行「电费支付」，
        // 说的是一笔她根本没办过的交易。
        document.querySelectorAll('[data-bind="bill.amount"],[data-bind="bill.company"],[data-bind="bill.paidAt"],[data-bind="bill.type"]')
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
  // 「正在听」那一页加载了 `speech.js`，那里有**真的**语音识别——交给它。
  // 它自己会处理权限被拒、没听到声音、重复按这些情况，并把结果送去识别页。
  if (window.YouhuoSpeech){ YouhuoSpeech.start(); return; }

  // 别的页面上的话筒（首页那个）：先落到「正在听」，识别在那一页开始。
  // **不在这里自动开始识别**：跳转之后没有用户手势，浏览器的麦克风权限
  // 多半会当场拒掉，于是老人第一次用就看到一句「我没有拿到麦克风的许可」——
  // 而他其实什么都没做错。让他在那一页按一下那个 170px 的大话筒，
  // 手势是真的，权限框也才有意义。
  //
  // 原来这里更糟：直接跳「识别结果」，那一页于是顶着「我已理解您的需求」
  // 加一张水费账单，而用户一个字都没说过。
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
  /* `taskType` 也要存。原先只存 `reply`，而 `understood.code` /
   * `taskType` / `taskId` 在整个 `/static/app/` 里一次都没被读过——
   * 于是引擎明说没听懂（`code:"chat"`、`taskType:null`）时，
   * 识别页照样顶着静态的「我已理解您的需求」，底下摆一张可直接付的水费单。 */
  const kind = r && r.understood && r.understood.taskType;
  if (kind) sessionStorage.setItem("youhuo_task_type", String(kind));
  else sessionStorage.removeItem("youhuo_task_type");
  go("recognize"); return;
}
if(a==="recognition-continue"){go("bill");return}if(a==="repeat"){go("listen");return}
if(a==="pick-bill"){
  // 换一张来办。**整页重新装填**，不是只改那一排的高亮：金额、缴费单位、
  // 月份、标题、缴费期限全都要跟着换，漏掉任何一处，屏幕上就有两张账单
  // 的字混在一起。
  const id = el.dataset.billId || "";
  if (!id) return;
  sessionStorage.setItem(BILL_PICK_KEY, id);
  await hydrate();
  return;
}
if(a==="bill-next"){
  // 记住 prepare 真正返回的事务号。
  // 原来这里丢掉了返回值，后面两步写死 "pay-demo-68"——对着 mock 能跑，
  // 一接真后端就是 404：真实事务号是服务端生成的。
  //
  // 账单 id 取她**真的挑中**的那一张。原来这里写死 "water-current"，
  // 于是「我的账单」上点电费，办出来的是水费。
  const picked = sessionStorage.getItem(BILL_PICK_KEY);
  const r = await YouhuoAPI.post("/payments/prepare",{billId: picked || "water-current"});
  if (r && r.id) sessionStorage.setItem("youhuo_payment_id", r.id);
  if (r && r.prompt) sessionStorage.setItem("youhuo_teach_prompt", r.prompt);
  go("confirm"); return;
}
if(a==="teach-back"){
  const pid = sessionStorage.getItem("youhuo_payment_id");
  if (!pid){ toast("这一笔还没有开始，请从账单进入"); return; }
  /* 复述内容**只能来自她自己**。
   *
   * 原先这里是：
   *   const said = (document.querySelector("[data-teach-text]")?.textContent||"").trim()
   *             || sessionStorage.getItem("youhuo_teach_prompt") || "";
   *
   * `[data-teach-text]` 在**整个 static 树里没有任何元素带它**（实测），
   * 于是永远落到兜底——把 `prepare` 回的那句提示当成她说的话。
   * 而那句提示是「这是电费，126.50元。…例如「确认支付126.50元」。」，
   * **必然含正确金额**。实测：把它原样回传 ->
   *   {"matched":true,"outcome":"verified","expected":"126.50","heard":"126.50"}
   * 老人一个字都没说，这一笔就过了复述核验，execute 照走。
   *
   * 空对照证明校验器本身是好的：「确认支付8元」-> mismatch，「」-> not_restated。
   * 所以毛病不在校验器，在**调用方把答案喂给了它**。
   *
   * 上面那句旧注释预见到了这个失败模式，却把选择器指向了一个不存在的元素。
   * 补上属性也不算修好：屏幕上那句话同样恒等于账单金额。
   *
   * 现在只读她打进去的那一格。**一个拿不到输入的安全检查要 fail-closed**：
   * 空的就不发请求，如实说一句。
   */
  const field = document.querySelector("#teachSay");
  const said = (field?.value || "").trim();
  if (!said){
    el.classList.remove("pulse");
    toast("请把上面那个数说一遍，或者打在下面那一格里");
    field?.focus();
    return;
  }
  el.classList.add("pulse"); toast("正在核验复述内容…");
  const r = await YouhuoAPI.post(`/payments/${pid}/teach-back`, {text: said});
  if (r.matched === false){
    toast(r.message || "没有听清，请再说一遍");
    el.classList.remove("pulse");
    return;
  }
  const done = await YouhuoAPI.post(`/payments/${pid}/execute`, {});
  if (done && done.message) toast(done.message);
  /* 把**真实结果**带到下一屏去。
   *
   * `execute` 回来常常是 `awaiting_family`——「已提交，等家里第二个人点头
   * 之后才会真的付。」，账单这时仍然 `paid:false / 待缴纳`。而下一屏原先
   * 无条件写着「支付成功 / 已为您完成本次电费」，那一行没有 id、没有绑定、
   * 谁也不读它。**一笔一分钱都没动的缴费，屏幕上说办成了。**
   *
   * 后端把契约写在 `app_api.py`：拿到 `awaiting_family` 就该照实显示。
   * 这个文件第 344 行也写着同一条：回执不许宣称一笔并未发生的交易。
   *
   * 存 sessionStorage 是这一套壳既有的做法（`youhuo_heard` / `youhuo_reply` /
   * `youhuo_bill_id`）——跳一次页面上一步的响应就没了。 */
  try{
    sessionStorage.setItem("youhuo_pay_status", String((done && done.status) || ""));
    sessionStorage.setItem("youhuo_pay_message", String((done && done.message) || ""));
  }catch(_){}
  setTimeout(()=>go("success"), 700);
  return;
}
if(a==="cancel-payment"){go("bill");return}if(a==="help"){document.querySelector("#helpModal")?.classList.add("show");return}if(a==="close-modal"){el.closest(".modal")?.classList.remove("show");return}
if(a==="open-cert"){go("cert");return}if(a==="home"){go("home");return}
if(a==="records-filter"){
  document.querySelectorAll("[data-action=records-filter]").forEach(x=>x.classList.remove("active"));
  el.classList.add("active");
  // 真的筛，不是弹一个 toast 假装筛了。
  await renderRecords(el.dataset.kind || el.textContent.trim());
  return;
}
if(a==="service"){
  const name = (el.dataset.service || "").trim();
  const dest = SERVICE_DEST[name];
  if (dest){ go(dest); return; }
  if (name === "帮助与客服"){ document.querySelector("#helpModal")?.classList.add("show"); return; }
  if (name === "常用服务"){ openQuickMenu(); return; }
  if (name === "全部记录"){
    // 「查看全部记录」就在记录页上——它要做的是把筛选清掉，不是跳去别处。
    document.querySelectorAll("[data-action=records-filter]").forEach(x=>x.classList.remove("active"));
    document.querySelector("[data-action=records-filter]")?.classList.add("active");
    await renderRecords("全部");
    document.querySelector("#recordList")?.scrollIntoView({behavior:"smooth", block:"start"});
    //: 原先无条件说「已经显示全部记录」，而同一份响应里 hasMore 是 true。
    //: 现在按真实情况说。
    const more = _recordCache && _recordCache.hasMore;
    const seen = ((_recordCache && _recordCache.items) || []).length;
    const all = Number(_recordCache && _recordCache.total) || seen;
    toast(more ? `一共 ${all} 条，先列出最近 ${seen} 条` : "已经显示全部记录");
    return;
  }
  // 走到这里说明 SERVICE_DEST 少了一条。说出缺的是哪一个，
  // 别再回到那句谁也定位不了的「还没有做好」。
  console.warn("SERVICE_DEST 里没有这一项：", name);
  toast(name + "：这一项还没有接上，我记下了");
  return;
}
if(a==="cert-detail"){
  const label = el.dataset.label || "这一项";
  if (label === "完整凭证"){ showChainSheet(); return; }
  const value = (el.querySelector("span:last-child")?.textContent || "").replace("　›","").trim();
  showSheet(label, value && value !== "还没有采集"
    ? [value, "这一条写在审计链上，任何一方都改不动。"]
    : ["这一条还没有采集到。",
       "凭证上只写真的采到的东西——没采到就空着，不补一个看起来合理的值。"]);
  return;
}
if(a==="emergency"){document.querySelector("#sosModal")?.classList.add("show");return}if(a==="emergency-confirm"){/* 把服务端回的那句话原样说出来。原先是写死的「正在联系紧急联系人」，响应体一个字段都不读——而那句话按情况差很多（都是 200/ok:true）：第一次「已经记下这次呼叫，正在联系女儿。」；一分钟内第二次「刚才那次呼叫已经发出去了…**要是很急，请直接拨打 120。**」且 notified 为空；没登记家人时也会说「请直接拨打 120」。写法照同一个端点的另一个调用点（`page-contacts.js:304`）——一件事两条路，原先只有一条说真话。 */const reply=await YouhuoAPI.post("/emergency/call",{source:"elder-app"});el.closest(".modal")?.classList.remove("show");toast((reply&&reply.message)||"已记录这次呼叫。");return}
}catch(err){console.error(err);toast("操作失败，请稍后重试")}});

// ---- 记录页：真实审计流水 ----------------------------------------------------
let _recordCache = null;
/* 按类别**问服务端**，不在客户端筛。
 *
 * 原先是取一次不带参数的 `/records`（回 `count=80` 而 `total=109`），
 * 然后在那 80 条里筛。实测：办一笔电费再灌 95 条健康记录之后，
 * 第一页 80 条**全是**健康，筛「支付」筛出 0 条，屏幕说
 * 「这一类还没有记录。」——而服务端 `?type=支付` 说 total=7，
 * 里面就有那笔正等家人点头的 ¥126.50。
 *
 * 后端那段 docstring 写着「**分页在筛选之后做**。反过来会得到一个
 * 随类别变化的、看起来像 bug 的结果」——客户端筛选把它原样搬了回来。
 */
async function renderRecords(kind){
  const box = document.querySelector("#recordList");
  if (!box) return;
  const q = (!kind || kind === "全部")
    ? "" : "?type=" + encodeURIComponent(kind);
  let data;
  try { data = await YouhuoAPI.get("/records" + q); }
  catch (err) {
    console.error(err);
    box.innerHTML = "";
    const p = document.createElement("p");
    p.className = "muted"; p.style.padding = "24px 0"; p.style.textAlign = "center";
    //: 读不出来和没有记录是两件事，别说成同一句。
    p.textContent = "这会儿没能把记录读出来，请稍后再看。";
    box.appendChild(p); return;
  }
  _recordCache = data;
  const items = data.items || [];
  box.innerHTML = "";
  if (!items.length){
    const p = document.createElement("p");
    p.className = "muted"; p.style.padding = "24px 0"; p.style.textAlign = "center";
    //: 现在这句话是真的：服务端按这个类别筛完之后确实没有。
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
  /* 画不下的那些要说出来。**一个知道自己截断了的接口，
   * 配一个不问的前端**——`total` / `hasMore` / `machinery` 三个字段
   * 原先在整个 `/static/app/` 里读它们的地方是 0 处。
   * 同一件事在老人端三修过（KNOWN_ISSUES 第 162 条）。 */
  const total = Number(data.total) || items.length;
  const note = document.createElement("p");
  note.className = "muted";
  note.style.padding = "14px 0";
  note.style.textAlign = "center";
  const parts = [];
  if (total > items.length){
    parts.push(`一共 ${total} 条，先列出最近 ${items.length} 条。`);
  }
  const extra = Number(data.machinery) || 0;
  //: 后端挡掉的那些也摆出来——它那段注释写着「她那一屏会写
  //: 「另有 N 条系统记录」」，而在这个壳上一直没有那一屏。
  if (extra) parts.push(`另有 ${extra} 条系统记录。`);
  if (parts.length){
    note.textContent = parts.join("");
    box.appendChild(note);
  }
}

// ---- 凭证页：真实审计链 ------------------------------------------------------
const CERT_LABEL = {voiceTeachBack:"语音复述凭证", location:"位置凭证",
                    device:"设备凭证", time:"时间凭证"};
// 状态 → 颜色。**只有真的付掉了才敢说这一笔完成了。**
//
// 说法（「已完成并核验」那一串）**不在这里**：它在 `common.js::STATUS_WORD`，
// 这一页读的是自称那一份——凭证页上是老人在读自己的事。
//
// 留在这里的只有颜色，而这是有理由的、不是拆一半：颜色不是措辞。这一页的三档色
// 是量过对比度的，而家人确认页那一套（`page-family-approve.js`）为了浅底又是另一
// 组值。两页说同一句话、上不同的色，那不是漂移。
//
// 原先这张表是 `["已完成并核验", "#2b9955"]` 这种「话 + 色」二元组，七个键里有四个
// 和别处不一样，其中 `completed` 说的是「交易成功」——同一笔钱在老人端记录里叫
// 「办好了」、在家人端叫「已完成并核验」。上一轮把措辞统一了，但办法是在这里留一份
// 字面副本、用判据钉住它和 `common.js` 逐字相同。副本现在删掉了：`/app` 的十七页
// 都加载 `common.js`（`test_the_app_shell_shares_one_vocabulary.py` 钉住这件事），
// 说法只剩一份，「改一处忘另一处」这条路没有了。
const CERT_TONE = {
  completed:                 "#2b9955",
  executing:                 "#df7d1e",
  awaiting_family_approval:  "#df7d1e",
  awaiting_elder_confirmation:"#df7d1e",
  collecting:                "#df7d1e",
  cancelled:                 "#8a8580",
  failed:                    "#c0392b",
};
//: 那枚金印**只在真的办好之后才露面**。
//:
//: `cert_gold_seal.png` 里烤着一枚绿徽章，白纸黑字写着「交易成功」（还带对勾）。
//: 它原先无条件铺在凭证页和**家人确认页**上——后者正是家人还在决定同不同意的
//: 那一屏。于是一笔没批准的钱，旁边摆着一张图说它成功了。
//:
//: 这和刚修过的那条 P0 是同一件事，只是这次断言是**画在图里的**：
//: 代码里的状态文案改对了，图片照样替它说了反话。所以判据不能只看文字。
//:
//: 为什么不改图：绿徽章在 y147–181，而金环跨 y56–209——裁不掉，抠掉会在环上留洞。
//: 而且「成功的印章在成功之后出现」本来就是对的，不是将就。
function setSuccessSeal(on){
  const seal = document.querySelector("#certSuccessSeal");
  if (seal) seal.hidden = !on;
}
window.setSuccessSeal = setSuccessSeal;

function renderCert(cert){
  const box = document.querySelector("#certElements");
  if (!box || !cert) return;
  // 留着给「查看完整凭证」用——那一格要展示整条链，而链只在这一次响应里。
  _certCache = cert;
  setSuccessSeal(cert.status === "completed");

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
  /* **无条件**覆盖页面上的每一格。`if (cert.x)` 那种写法一旦为空，
   * 留下的就是 `hydrate()` 从**当前账单**绑上去的字。实测：
   * 一笔停在 awaiting_family_approval、`cert.paidAt` 是 null 的电费，
   * 页面上是「水费支付 / ¥126.50 / 示例供电公司 / 完成时间 …00:31」
   * ——标题和完成时间都是**别人那一笔**的。
   *
   * 上面那句注释说「这一页的每一个字都来自这一笔凭证自己」，
   * 而原先只覆盖了两格。
   */
  put('[data-bind="bill.amount"]', cert.amount);
  put('[data-bind="bill.company"]', cert.company);
  put('[data-bind="bill.type"]', cert.type || "这一笔的凭证");
  //: 没办完就说没办完，不摆一个时刻。`cert.paidAt` 在没完成时是 null
  //: （后端刻意的：「不拿「现在」冒充「办好的时候」」）。
  put('[data-bind="bill.paidAt"]', cert.paidAt || "还没办完");

  // 说法从共享词表取（自称：这一页是老人在读自己的凭证）。认不出来时 `statusWord()`
  // 自己回「还在办」，那句兜底也只在 `common.js` 里有一份。颜色是这一页自己的。
  const word = window.YouHuo.statusWord(cert.status);
  const color = CERT_TONE[String(cert.status)] || "#df7d1e";
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