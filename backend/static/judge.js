const statusEl = document.querySelector('#judgeStatus');

// 身份、登录、401 重放都在 common.js 里；此前这一页没有 401 重放，令牌一过期，
// 导览就会在评委面前静默失败。
//
// 老人和家人两个身份都要：七拍里有三拍走的是真实任务状态机（开口、复述、家人接力），
// 那三步分别以老人和家人的身份发出——用同一个身份跑完全程，"第二个人点头"就成了
// 自己跟自己点头，而那恰好是这一页要证明的反面。
let IDS = {elderId: 'elder-demo', daughterId: 'daughter-demo'};

/** 这一次演示的那件事。七拍共享它——七拍讲的是同一件事，不是七件事。
 *
 * `mode` 有三种，而且**必须让评委知道是哪一种**：
 *
 *   fresh   这一遍真的从她开口开始办了一笔。
 *   resume  这张账单上已经有一件在办的任务（上一次演到一半就关了标签页，或者有人
 *           只点了前两拍）。后端对同一张账单是幂等的，所以这时候立不出第二件——
 *           这一页就接着讲那一件，不假装重新开始。
 *   replay  这个月的水费已经交过了，后端把这一次的任务安全停下。这不是失败，恰恰是
 *           这个产品该有的样子——它不会为了演示再扣一次钱。第 5、6 拍改成从审计链里
 *           把上一次的记录读出来，并且在正文里说清楚"这是上一次的记录"。
 *           假装又办了一遍，就是在一页专门讲可信的页面上撒谎。
 *
 * `mode` 只决定**怎么说**。**该不该做**由另一条判据决定：审计链上有没有这一步。
 * 那条判据写在第 5、6 拍里，理由见那里。
 *
 * `session` 不在这里了：她说的话现在从**手机里的老人端**发出，会话是那一端自己的。
 * 见下面 `sayOnPhone` 的说明。
 */
const story = {taskId: null, amount: null, digest: null, mode: 'fresh'};

const sleep = (ms) => new Promise((resolve) => window.setTimeout(resolve, ms));

async function login() {
  IDS = await window.YouHuo.ready();
  await Promise.all([window.YouHuo.login('family'), window.YouHuo.login('elder')]);
}

function api(path, options = {}, role = 'family') {
  return window.YouHuo.api(path, options, role);
}

function post(path, body, role = 'family') {
  return api(path, {method: 'POST', body: JSON.stringify(body)}, role);
}

function showJSON(id, data) {
  window.YouHuo.renderResult(document.querySelector(id), data);
}

/* 翻译层。Product 层里一个英文枚举都不许有。
 *
 * 第一版演完之后那七句话里漏出了三个：语音结论 `clarify`、预演决策 `clarify`、
 * 任务状态 `awaiting_family_approval`，外加一个四位小数的负荷分数 `0.6684`。
 * 它们是从真实响应里直接插进去的——"用真实数据填 Product 层"这个决定本身是对的，
 * 但真实数据是给机器读的，翻译不能省。原始值都在下面 Proof 层的原始响应里。
 *
 * **不保留原始值做兜底。** 兜底成原始码，等于这层翻译在遇到新枚举时自动失效，
 * 而那正是它该起作用的时候（family.js 的 auditLabel 为同样的理由这么写）。 */
const VOICE_WORD = {
  clarify: '要问清楚', accept: '可以照办', reject: '不办',
  escalate: '交给家人', conflict: '两路打架，不执行',
};
const DECISION_WORD = {
  clarify: '要问清楚', allow: '放行', deny: '拒绝',
  require_human: '要人来定', escalate: '交给家人',
};
const STATE_WORD = {
  collecting: '还在收集信息', awaiting_elder_confirmation: '等她确认',
  awaiting_family_approval: '等家人接力', executing: '正在办理',
  completed: '已完成并核验', cancelled: '已取消', failed: '未成功，已安全停下',
};
function word(table, value, kind) {
  return table[value] || `（这个${kind}还没有中文说法，原值在下面的原始响应里）`;
}

/** Product 层那一句。
 *
 * 这是七拍改造的核心：这句话由**真实响应**填写，不是写死在 HTML 里的文案。写死的
 * 文案在接口改坏之后照样好看，那就不是演示，是插图。HTML 里的初始文本是演之前的
 * 剧情提要，演过之后被真实结果替换。
 */
function say(beat, text) {
  const node = document.querySelector(`#say-${beat}`);
  if (node) node.textContent = text;
  const article = document.querySelector(`.beat[data-beat="${beat}"]`);
  if (article) article.classList.add('is-played');
}

function activate(beat) {
  document.querySelectorAll('.beat').forEach((el) => {
    const on = el.dataset.beat === beat;
    el.classList.toggle('is-current', on);
    // 序号本身就是跳转按钮，所以"当前在第几拍"这件事也得说给读屏软件听，
    // 不能只靠那圈光晕。
    const jump = el.querySelector('[data-jump]');
    if (!jump) return;
    if (on) jump.setAttribute('aria-current', 'true'); else jump.removeAttribute('aria-current');
  });
}

// --- 右边那台手机 ---------------------------------------------------------
//
// 它不是插图，是同源 iframe 里**真实的应用本身**。这一整段照抄 /stage（stage.js 的
// `applySize` 与 `#stageLines`），包括那一页付过代价的两条：
//
//   一，尺寸只提**需求**。JS 写 `--want-*`，CSS 拿它算 `--screen-*` 并钳上限。
//       stage.js 第一版直接写 `--screen-*`，而内联样式永远压过样式表里的响应式钳制
//       ——1360×900 下机身底边连同下面那行说明一起被裁掉，而 CSS 里那条
//       `min(844px, 可用高度)` 一点作用都没有。职责分开：JS 不知道窗口有多高，
//       CSS 不知道这一页想要哪一档。
//   二，台词是**真的填进输入框、真的按发送**。不许调 App 自己不会走的任何路径：
//       演示如果是另一条代码路径，它就证明不了任何事。

const frame = document.querySelector('#judgePhoneFrame');
const phone = document.querySelector('#judgePhone');
const phoneCaption = document.querySelector('#judgePhoneCaption');
const phoneHint = document.querySelector('#judgePhoneHint');

const WANT = {w: 390, h: 844};
const ROUTE_WORD = {'/elder': '老人端', '/family': '家人端', '/trust': '可信中心'};

// 和 judge.html 里 iframe 的 `src` 保持一致。初值写错的代价不是报错，是第 1 拍白白
// 重载一次老人端——而重载会把她刚说的话清空，那正是前五拍的全部内容。
let phoneRoute = '/elder';

function applyPhoneSize() {
  phone.style.setProperty('--want-w', `${WANT.w}px`);
  phone.style.setProperty('--want-h', `${WANT.h}px`);
  phoneCaption.textContent = `${ROUTE_WORD[phoneRoute] || phoneRoute} · ${WANT.w} × ${WANT.h}`;
}

/** 把手机装到某一端。**只在真的换端时重载。**
 *
 * 返回"这一次有没有重新装过"。调用方需要知道：重载之后框里是一个刚冷启动的应用，
 * 屏幕上没有她刚说的话，这时候照着剧本念旁白就是在骗人。
 */
async function showOnPhone(route) {
  if (route === phoneRoute && frame.contentDocument) return false;
  phoneRoute = route;
  frame.src = route;
  applyPhoneSize();
  await new Promise((resolve) => frame.addEventListener('load', resolve, {once: true}));
  // 脚本是 defer / module 的，load 之后再给它一拍去绑事件。
  await sleep(400);
  return true;
}

/** 每一拍在手机上是哪一端、往哪儿看。
 *
 * `look` 写成"看什么"而不是"屏幕上现在是什么"，是因为这一句在**这一拍开始时**就
 * 写出去，而这一拍要发生的事还没发生。写成断言就会早一拍说谎。
 *
 * 前五拍的 `needsStory` 为真：它们要看的东西是那段累积起来的对话。框一旦重新装过，
 * 那些东西就不在了，这时候要说的是实话，不是旁白。
 */
const PHONE_BEATS = {
  '01': {route: '/elder', needsStory: true,
         look: '看她说完那一句之后，这台手机上出现了什么——金额，和一句要她复述的话。'},
  '02': {route: '/elder', needsStory: true,
         look: '这一屏就是「不猜」的样子：它停下来问，没有直接去付。'},
  '03': {route: '/elder', needsStory: true,
         look: '屏幕上那句话不是写死的文案——老人端每一句都要过一遍认知负荷治理器。'},
  '04': {route: '/elder', needsStory: true,
         look: '在这台手机上找不到 9999.99：它从来没有进过工具参数。'},
  '05': {route: '/elder', needsStory: true,
         look: '看她念完之后，屏幕从「等您复述确认」走到哪一步。'},
  '06': {route: '/family',
         look: '这是女儿那一端。需要第二个人点头的事就摆在她的第一屏。'},
  // 第 7 拍不回老人端：回去要重载，而重载会把玻璃盒那张卡连同整段对话一起清空——
  // 屏幕上什么都不剩，正好是这一拍要说的话的反面。可信中心是老人自己那一端的凭证，
  // 它不需要任何累积状态，而它证明的是同一件事：办完了，而且每一步都对得上。
  '07': {route: '/trust',
         look: '这是老人自己那一端的凭证：每一步都能对上，而且写清了哪一句话没有进链。'},
};

async function showBeatOnPhone(beat) {
  const plan = PHONE_BEATS[beat];
  if (!plan) return;
  const reloaded = await showOnPhone(plan.route);
  phoneHint.textContent = reloaded && plan.needsStory
    ? `这台手机刚重新装了一遍${ROUTE_WORD[plan.route]}：之前那段对话不会伪造回来。`
      + '按「从头演一遍」可以再走一遍。'
    : plan.look;
}

/** 进入某一拍：左边高亮，右边跟着换端。 */
async function enter(beat) {
  activate(beat);
  await showBeatOnPhone(beat);
}

/** 让她在手机上真的说一句话。
 *
 * 拿 contentDocument，真的按「用打字说」、真的填 `#text`、真的派发 input 事件、
 * 真的点 `#send`——和一位老人自己打字完全同一条路径（写法照抄 stage.js 的
 * `#stageLines`，另加下面那一步）。
 *
 * 先等就绪再点：老人端的脚本是 module 的，`readyState === 'complete'` 之前它还没把
 * click 绑上去。那一下点下去什么都不会发生，而**页面不报任何错**——表现是第 1 拍
 * 等满 15 秒然后说"没有立起任何一件事"，而真正的原因在另一个 document 里。
 */
async function sayOnPhone(line) {
  await showOnPhone('/elder');
  const doc = await until(() => {
    const d = frame.contentDocument;
    const ready = d && d.readyState === 'complete'
      && d.getElementById('text') && d.getElementById('send');
    return ready ? d : null;
  }, 10, '手机里的老人端没能就绪，这一句没有真的说出去');

  // 先按「用打字说」，再打字。
  //
  // 对话、输入行和玻璃盒那张卡都住在老人端的 Focus Mode 里
  // （`body[data-focus="on"]`），首页那一态下它们由 CSS 藏着。直接填 `#text`、
  // 点 `#send`，那一轮**真的会发生**：任务立起来了、链上有记录、气泡也进了 DOM——
  // 而框里那台手机的屏幕停在「我在，您请说」。第一版就是这样，我的 DOM 探针数到了
  // 三个气泡，差点把"她说了"当成"看得见她说了"，而这一整页的论点就是后者。
  //
  // 「用打字说」是这个应用自己给的打字入口（语音失败时它是她唯一的入口），所以这
  // 不是为了演示加的一下，就是她本来要按的那一下。
  if (doc.body.dataset.focus !== 'on') {
    const typing = doc.getElementById('typeInstead');
    if (!typing) throw new Error('手机里的老人端找不到打字入口，这一句没法当着人说出去');
    typing.click();
    await sleep(160);
  }
  if (doc.body.dataset.focus !== 'on') {
    // 宁可红。这一句发出去了而屏幕上看不见，等于这一页在替一台没动过的手机作证。
    throw new Error('手机里的老人端没有进到对话那一屏，这一句会发生但看不见');
  }

  const input = doc.getElementById('text');
  input.value = line;
  input.dispatchEvent(new doc.defaultView.Event('input', {bubbles: true}));
  doc.getElementById('send').click();
  phoneHint.textContent = `已经替她在手机上说了：「${line}」——真的填进输入框、真的按了发送。`;
}

// --- 七拍 ---------------------------------------------------------------

/** 等一件事在后端真的成立；到点就说清是哪一件没成立。
 *
 * 第 1、5 拍现在由手机里的老人端发起，所以这一页拿不到那一次调用的回包，只能问权威
 * 来源。轮询的是**任务记录和审计链**，不是框里的界面：界面是从记录画出来的，
 * 反过来读界面等于把结论当证据。
 */
async function until(probe, seconds, complaint) {
  const deadline = Date.now() + seconds * 1000;
  for (;;) {
    const value = await probe();
    if (value) return value;
    if (Date.now() >= deadline) throw new Error(complaint);
    await sleep(300);
  }
}

/** 这个家庭所有的缴费任务。 */
async function billTasks() {
  const tasks = await api('/v2/tasks?limit=100');
  return tasks.filter((t) => t.task_type === 'bill_payment');
}

/** 还在办的那几种状态。一件停在这里面任何一档的任务，会把同一张账单一直挡着。 */
const LIVE = ['awaiting_elder_confirmation', 'awaiting_family_approval', 'executing'];

/** 上一次办成的那笔水费。演第二遍时第 5、6 拍从它的审计记录里取事实。
 *
 * 显式按更新时间排序，并且取**最新**的那一件。原先是 `done[done.length - 1]`，而
 * 后端按 created_at 倒序返回——那行代码取到的是这个家庭**最早**的一笔，然后管它叫
 * "上一次"。沙箱里只办过一笔的时候两者恰好相同，所以它一直看起来是对的。
 */
async function lastCompletedBill() {
  const done = (await billTasks())
    .filter((t) => t.status === 'completed')
    .sort((a, b) => String(b.updated_at).localeCompare(String(a.updated_at)));
  return done[0] || null;
}

async function runOpen() {
  await enter('01');

  // 先读链，读不到才办。
  //
  // 后端对同一张账单是幂等的：同一笔账不会扣两次。这是**对的**产品行为，但它的后果
  // 是这一页不能假设"每次都能新立一件事"——
  //
  //   * 这个月已经交过了 → 这一次的任务会被安全停下（下面的 replay）；
  //   * 上一次演到一半（关了标签页、或者只点了前两拍的「单独跑这一拍」）→ 有一件
  //     任务停在"等她确认"或"等家人接力"，它把这张账单一直挡着（这里的 resume）。
  //     而且这时候连"新立一件"都不会发生：她那句话会被当成对那件在办任务的输入，
  //     于是"等新任务出现"会一直等不到。
  //
  // 评委会反复打开这一页、反复点「从头演一遍」。一个只在全新沙箱里能演完的导览，
  // 在答辩现场就是坏的。`/trust` 的凭证为同一个原因改过一次（trust.js 的
  // renderReceipt：能读链就读链，读不到才真的办），这里用同一条判据。
  statusEl.textContent = '正在看这张账单上有没有已经在办的事……';
  const live = (await billTasks()).find((t) => LIVE.includes(t.status));
  if (live) {
    story.mode = 'resume';
    story.taskId = live.id;
    story.amount = (live.details || {}).amount_yuan;
    if (!story.amount) throw new Error('这张账单上那件在办的任务里没有金额，后面六拍无从谈起');
    say('01', `她之前说过「帮我交这个月的水费」，这件事还在办：${story.amount} 元。`
      + '优活不会为了演示再立第二件——下面几拍接着讲的就是那一件。');
    showJSON('#beatOpen', {
      这一轮的结论: '这张账单上已经有一件在办的事，不重复立第二件',
      那件任务: live.summary, 任务状态: live.status, 账单金额: story.amount, 任务编号: live.id,
    });
    phoneHint.textContent = '这一拍没有让她再说一遍：这张账单上已经有一件在办的事。'
      + '手机上这一屏是她此刻真实的样子。';
    statusEl.textContent = '第 1 拍：这张账单上已经有一件在办的事，这一页接着讲那一件。';
    return;
  }

  statusEl.textContent = '正在让手机里的老人端说第一句话……';

  // 先记下此刻有哪些缴费任务：她开口之后**新出现**的那一件，就是这一次的那件事。
  //
  // 这一步不能省成"取最后一条"。演第二遍时库里已经有上一遍那笔，而两遍的结论正好
  // 相反（一遍是"等她确认"，一遍是"这笔账不会扣两次"）——拿错那一条，这一页会用
  // 一件真实存在的记录讲一件没发生的事。
  const before = new Set((await billTasks()).map((t) => t.id));
  await sayOnPhone('帮我交这个月的水费');

  // 任务是先落盘（collecting）、查完账单再更新状态的，所以"新出现"还不够，要等它
  // 有了结论。少这一条，轮询会在那个极窄的窗口里抓到一条还没查过账单的任务，
  // 金额是空的，而后面六拍全都要用这个金额。
  const task = await until(async () => (await billTasks()).find(
    (t) => !before.has(t.id) && t.status !== 'collecting',
  ), 15, '手机里那句话没有在后端立起任何一件事，这一拍不能算发生过');

  if (task.status === 'cancelled') {
    // 不是失败。这是"同一笔账不会扣两次"这条规则在起作用，而它值得单独说一句。
    const prior = await lastCompletedBill();
    if (!prior) {
      throw new Error('这一次的任务被安全停下了，而库里也找不到上一次办成的那笔'
        + '——没有可讲的记录，不能凭空往下讲');
    }
    story.mode = 'replay';
    story.taskId = prior.id;
    story.amount = (prior.details || {}).amount_yuan;
    say('01', '她在手机上说：「帮我交这个月的水费。」——这个月已经交过了，优活直接回'
      + '「不用再交」，没有为了演示再扣一次。下面第 5、6 拍读的是上一次留在链上的记录。');
    showJSON('#beatOpen', {
      这一轮的结论: '同一笔账不会扣两次',
      这一次那件任务: task.summary, 它的状态: task.status,
      上一次那笔: prior.summary, 那笔的状态: prior.status,
    });
    statusEl.textContent = '第 1 拍：重复缴费被拦下——这是规则在起作用，不是演示失败。';
    return;
  }

  story.mode = 'fresh';
  story.taskId = task.id;
  story.amount = (task.details || {}).amount_yuan;
  if (!story.amount) throw new Error('账单金额没回来，后面六拍无从谈起');
  say('01', `她在手机上说：「帮我交这个月的水费。」优活查到 ${story.amount} 元，`
    + '并且没有直接去付——它先停下来问。');
  showJSON('#beatOpen', {
    这一句从哪儿发出: '手机里的老人端，真的填进输入框、真的按了发送',
    后端立下的任务: task.summary, 任务状态: task.status,
    金额从哪来: '账单接口，不是她说的数字', 账单金额: story.amount, 任务编号: task.id,
  });
  statusEl.textContent = '第 1 拍：任务已立，等她确认。';
}

async function runVoice() {
  await enter('02');
  statusEl.textContent = '正在模拟两路语音识别候选冲突……';
  const data = await post('/v5/voice/resolve', {
    elder_id: IDS.elderId, side_effect_possible: true,
    candidates: [
      {text: '确认办理本月水费', confidence: 0.91, engine: 'core-speech-primary'},
      {text: '取消办理本月水费', confidence: 0.89, engine: 'core-speech-backup'},
    ],
  });
  say('02', `两路识别一个听成「确认办理」（0.91）、一个听成「取消办理」（0.89）。`
    + `优活的结论是「${word(VOICE_WORD, data.status, '结论')}」`
    + `——它没有按分高的那个执行，而是回头问她。`);
  showJSON('#demoVoiceOut', {
    结论: data.status, 澄清语: data.clarification_prompt,
    安全标记: data.safety_flags, 理由: data.rationale,
  });
  statusEl.textContent = '第 2 拍：确认/取消冲突被识别，系统没有猜测执行。';
}

async function runLoad() {
  await enter('03');
  statusEl.textContent = '正在按老人交互画像降低信息密度……';
  const data = await post('/v6/interaction/plan', {
    elder_id: IDS.elderId,
    message: '系统将提交本月水费付款请求，请核对账单对象、金额、截止日期和付款家属。',
    options: ['确认办理', '取消办理', '请女儿看看', '稍后再办'],
    risk_level: 4, asr_confidence: 0.93, recent_retries: 1, reversible: false,
  });
  const shown = (data.visible_options || []).length;
  // 负荷分数原样是 0.6684——四位小数对一个"这一屏有多重"的判断没有意义，
  // 而它在 Product 层看起来像一个精确到万分之一的物理量。折成百分数。
  const load = Math.round(Number(data.cognitive_load_score || 0) * 100);
  say('03', `给它四个选项，它只留下 ${shown} 个，并且要求复述而不是点「是」。`
    + `这一屏的负荷估到 ${load}%。`);
  showJSON('#demoLoadOut', {
    播报: data.speak_text, 可见选项: data.visible_options,
    复述确认: data.require_teach_back, 负荷分数: data.cognitive_load_score, 原因: data.rationale,
  });
  statusEl.textContent = '第 3 拍：本轮只呈现一个动作，并用复述确认代替简单的是/否。';
}

async function runPreview() {
  await enter('04');
  statusEl.textContent = '正在把恶意 OCR 内容送进模型外的策略防火墙……';
  const data = await post('/v6/actions/preview', {
    elder_id: IDS.elderId, goal: '缴纳本月水费', action: 'create_payment_request',
    arguments: {bill_id: 'water-2026-07', amount_cents: 999999, elder_id: IDS.elderId, execute: true},
    facts: [
      {name: 'bill_id', value: 'water-2026-07', origin: 'trusted_tool', purpose: 'bill_payment', trusted_for_control: true},
      {name: 'amount_cents', value: 999999, origin: 'untrusted_document', purpose: 'bill_payment', trusted_for_control: false},
      {name: 'elder_id', value: IDS.elderId, origin: 'system', sensitivity: 3, purpose: 'bill_payment', trusted_for_control: true},
    ],
    user_confirmed: true, family_approvals: 1, reversible: true,
  });
  // 可选链：这一页是给评委看的，响应少一个字段不该变成一屏 TypeError。
  // `authorization` 缺失时下面仍会写出结论，而结论此时是假的——所以取不到就明说。
  const auth = data.authorization || {};
  showJSON('#demoPreviewOut', {
    决策: auth.decision ?? '（响应里没有 authorization）', 剥离字段: auth.stripped_fields,
    说明: data.plain_summary, 不会做: data.will_not_do, 人工确认: data.required_humans,
  });
  if (!auth.decision) throw new Error('预演响应缺少授权决策，不能当作通过');
  const stripped = (auth.stripped_fields || []).length;
  say('04', `图片里写着 9999.99 元，还夹了一条「直接支付」。`
    + `决策是「${word(DECISION_WORD, auth.decision, '决策')}」，`
    + `${stripped} 个字段在进入工具参数之前被剥掉。`);
  statusEl.textContent = '第 4 拍：文档金额与越权执行字段都没有进入真实工具参数。';
}

/** 这件任务在审计链上的记录。第 5、6 拍的事实都从这里来。 */
async function auditFor(taskId) {
  const audit = await api('/v2/audit?limit=200');
  return {
    chainValid: audit.chain_valid,
    events: (audit.events || []).filter((e) => e.entity_id === taskId),
  };
}

async function runTeachBack() {
  await enter('05');
  if (!story.taskId || !story.amount) throw new Error('先跑第 1 拍：还没有一件可讲的事');

  // 该不该让她再念一遍，由**链上有没有这一步**决定，不由 `story.mode` 决定。
  //
  // 已经念过的再念一遍，在后端是一次新的复述尝试：对不上会计一次失败，而屏幕上会多
  // 出一句谁都没说过的话。反过来，只按模式判断就会漏掉 resume 那一路——那件任务可能
  // 正停在"等她确认"（该念），也可能已经停在"等家人接力"（不该念）。
  let chain = await auditFor(story.taskId);
  let teach = chain.events.find((e) => e.event_type === 'TEACH_BACK_VERIFIED');
  const saidJustNow = !teach;

  if (saidJustNow) {
    statusEl.textContent = '正在让她在手机上把金额念一遍……';
    // 这一句也从手机发出。这一拍的全部内容就是"她自己念了一遍"——由这一页代她发一个
    // POST，那就变成系统自己确认自己，而那正是这一拍要证明的反面。
    await sayOnPhone(`确认支付${story.amount}元`);
    await until(async () => (await billTasks()).find(
      (t) => t.id === story.taskId && t.status !== 'awaiting_elder_confirmation',
    ), 15, '她念完之后任务没有往前走——复述没有通过，不能算它通过');
    chain = await auditFor(story.taskId);
    teach = chain.events.find((e) => e.event_type === 'TEACH_BACK_VERIFIED');
    if (!teach) throw new Error('任务往前走了，但链上没有复述记录——这一步不能算通过');
  } else {
    statusEl.textContent = '正在从审计链里读这一件事的复述记录……';
  }

  // 事实一律从**审计链**里读，而不是从某一次的回包里读：链是权威来源，回包只是它的
  // 一个侧面。摘要也从链上取——第 6 拍要拿它去批，取错就批不动。
  const confirmed = chain.events.find((e) => e.event_type === 'ELDER_CONFIRMED');
  story.digest = confirmed && confirmed.payload.approval_digest;
  if (!story.digest) throw new Error('没有拿到确认摘要，复述这一步没有真的通过');

  const p = teach.payload;
  const prefix = saidJustNow ? '她在手机上念了'
    : (story.mode === 'replay' ? '上一次她念的是' : '她之前念的是');
  say('05', `${prefix}「确认支付${p.heard}元」。链上记着：期望 ${p.expected}，`
    + `听到 ${p.heard}，第 ${p.attempts} 次通过。念错就停在原地，不会按听到的数字去付。`);
  showJSON('#beatTeach', {
    这一条来自: saidJustNow ? '这一次她念完之后留下的审计链' : '审计链，不是这一次的调用',
    期望金额: p.expected, 听到的金额: p.heard, 第几次通过: p.attempts,
    结果: p.outcome, 确认摘要: story.digest,
  });
  statusEl.textContent = saidJustNow
    ? '第 5 拍：复述通过，现在等第二个人。'
    : '第 5 拍：读的是链上已经留下的复述记录。';
}

async function runRelay() {
  // 这一拍**先高亮、后换端**，和其余六拍不同。
  //
  // 家人端不会自己刷新。先把它装进框，它就停在女儿按下之前那一刻——而这一拍要说的
  // 话是"她点了同意"，屏幕和台词正好差一步。所以等真的批完再装：那时候框里是这一端
  // 此刻真实的样子。
  activate('06');
  if (!story.taskId) throw new Error('先跑第 1 拍：还没有一件可讲的事');

  // 和第 5 拍同一条判据：链上已经有家人接力这一步，就读它，不再批一次。
  // 重复批同一件任务在后端是一次摘要校验失败（任务早就不在"等家人接力"那一档了），
  // 而这一页会把那次失败报成"这一拍不能算通过"——一个只因为演了第二遍而红的导览。
  let chain = await auditFor(story.taskId);
  let familyOk = chain.events.find((e) => String(e.event_type).startsWith('FAMILY_APPROVED'));
  const approvedJustNow = !familyOk;
  let status = null;

  if (approvedJustNow) {
    if (!story.digest) throw new Error('先跑第 5 拍：还没有待确认的摘要');
    statusEl.textContent = '正在以家人身份点同意……';
    status = (await post('/v2/family/approve',
      {task_id: story.taskId, approve: true, approval_digest: story.digest})).task_status;
    chain = await auditFor(story.taskId);
    familyOk = chain.events.find((e) => String(e.event_type).startsWith('FAMILY_APPROVED'));
  } else {
    statusEl.textContent = '正在从审计链里读这一件事的接力记录……';
  }

  // 摘要是否一致这件事，一律从**审计链**里读——链是权威来源，而接口回包只是它的
  // 一个侧面。
  const {events, chainValid} = chain;
  const elderConfirm = events.find((e) => e.event_type === 'ELDER_CONFIRMED');
  const same = !!(elderConfirm && familyOk
    && elderConfirm.payload.approval_digest === familyOk.payload.approval_digest);
  if (!status) {
    status = ((await billTasks()).find((t) => t.id === story.taskId) || {}).status || 'completed';
  }
  const prefix = approvedJustNow ? '女儿点了同意'
    : (story.mode === 'replay' ? '上一次女儿点了同意' : '女儿之前点了同意');
  say('06', `${prefix}。她同意的摘要和老人确认的${same ? '是同一个' : '不一致'}`
    + `——${same ? '对得上才执行' : '对不上就不执行'}。`
    + `任务状态：${word(STATE_WORD, status, '状态')}。`);
  showJSON('#beatRelay', {
    这一条来自: story.mode === 'replay' ? '审计链，不是这一次的调用' : '这一次的真实调用',
    任务状态: status,
    老人确认的摘要: elderConfirm ? elderConfirm.payload.approval_digest : '（没找到）',
    家人同意的摘要: familyOk ? familyOk.payload.approval_digest : '（没找到）',
    两者一致: same, 审计链自校验: chainValid,
  });
  if (!same) throw new Error('两个摘要对不上，这一拍不能算通过');
  await showBeatOnPhone('06');
  statusEl.textContent = '第 6 拍：两个摘要一致，任务执行。';
}

async function runCard() {
  await enter('07');
  statusEl.textContent = '正在生成老人看得懂的玻璃盒解释……';
  const data = await post('/v6/reliance/card', {
    elder_id: IDS.elderId, heard_text: '帮我交水费', goal: '处理本月水费',
    current_step: '核对账单', action: '创建付款请求', risk_level: 4, reversible: true,
    confirmations: ['老人复述金额', '女儿扫码支付'],
    evidence: [
      {label: '水务账单', source: '可信账单沙箱', trusted: true, verified: true},
      {label: '上传图片备注', source: 'OCR', trusted: false, verified: false},
    ],
    next_step: '请老人复述账单金额，随后通知女儿扫码',
  });
  const box = document.querySelector('#glassCard');
  box.replaceChildren();
  const rows = [
    ['我听到', data.heard], ['正在做', data.current_step], ['谁决定', data.who_decides],
    ['下一步', data.next_step], ['能否撤销', data.reversible ? '可以按规则撤销或补偿' : '不可自动撤销'],
    ['核验情况', data.confidence_message],
  ];
  rows.forEach(([k, v]) => {
    const row = document.createElement('div');
    const key = document.createElement('strong');
    const value = document.createElement('span');
    key.textContent = k; value.textContent = v;
    row.append(key, value); box.appendChild(row);
  });
  if (data.warning) {
    const warning = document.createElement('p');
    warning.className = 'notice warning';
    warning.textContent = data.warning;
    box.appendChild(warning);
  }
  say('07', `${data.confidence_message} 决定权在「${data.who_decides}」。`);
  statusEl.textContent = '第 7 拍：老人不用懂技术词，也知道系统凭什么、谁说了算。';
}

async function runBoard() {
  statusEl.textContent = '正在汇总评分证据与剩余缺口……';
  const data = await api('/v6/competition/evidence');
  const board = document.querySelector('#evidenceBoard');
  board.replaceChildren();
  data.items.forEach((item) => {
    const card = document.createElement('article');
    card.className = 'evidence-mini';
    const h = document.createElement('h3');
    h.textContent = `${item.dimension} · ${item.score_weight}分`;
    const ready = document.createElement('p');
    ready.textContent = `当前成熟度：${item.readiness}`;
    const list = document.createElement('ul');
    item.evidence.slice(0, 3).forEach((x) => {
      const li = document.createElement('li'); li.textContent = x; list.appendChild(li);
    });
    const gap = document.createElement('p');
    gap.className = 'meta';
    gap.textContent = '剩余：' + item.remaining_gap.join('；');
    card.append(h, ready, list, gap);
    board.appendChild(card);
  });
  statusEl.textContent = '证据板已加载：已实现、待真机验证和禁止宣传的内容分开列出。';
}

// --- 绑定 ---------------------------------------------------------------

// 顺序即剧情。第 5、6 拍依赖第 1 拍立下的那件事，所以整场演出必须按这个顺序走。
const BEATS = [
  ['01', runOpen, '#beatOpen'],
  ['02', runVoice, '#demoVoiceOut'],
  ['03', runLoad, '#demoLoadOut'],
  ['04', runPreview, '#demoPreviewOut'],
  ['05', runTeachBack, '#beatTeach'],
  ['06', runRelay, '#beatRelay'],
  ['07', runCard, '#glassCard'],
];
const HANDLERS = {
  runOpen, runVoice, runLoad, runPreview, runTeachBack, runRelay, runCard, runBoard,
};

/** 失败时同时写进状态行**和**这一拍自己的输出区。
 *
 * 原先只写状态行——那一行在页面顶部，而评委的眼睛在他刚点的那个按钮上，于是
 * "点了没反应"。
 */
function report(error, outSelector) {
  statusEl.textContent = error.message;
  const out = outSelector && document.querySelector(outSelector);
  if (out) { out.replaceChildren(); out.textContent = error.message; }
}

// `addEventListener` 而不是 `.onclick =`：后者是覆盖而不是叠加，哪天有人给同一个
// 按钮再挂一件事，先挂的那件会无声消失。
document.querySelectorAll('[data-run]').forEach((button) => {
  const name = button.dataset.run;
  const beat = BEATS.find(([, fn]) => fn === HANDLERS[name]);
  button.addEventListener('click', () => {
    const fn = HANDLERS[name];
    if (!fn) return;
    fn().catch((error) => report(error, beat ? beat[2] : null));
  });
});
document.querySelector('#demoBoard').addEventListener('click',
  () => runBoard().catch((error) => report(error, '#evidenceBoard')));

// 序号 = 跳到这一拍。
//
// 它**只换右边那台手机装到哪一步，不重跑这一拍**：重跑的按钮在这一拍自己的证据里。
// 一个控件做两件事，评委点下去就分不清屏幕上的变化是"我跳过来了"还是"它又办了一次"
// ——而这一页整页都在讲"每一步分别由谁做、凭什么"。
document.querySelectorAll('[data-jump]').forEach((button) => {
  const beat = button.dataset.jump;
  button.addEventListener('click', () => {
    const title = document.querySelector(`.beat[data-beat="${beat}"] .beat-title`);
    enter(beat)
      .then(() => {
        statusEl.textContent = `现在停在第 ${Number(beat)} 拍：${title ? title.textContent : ''}。`
          + '右边那台手机装的是这一步该看的那一端。';
      })
      .catch((error) => { statusEl.textContent = error.message; });
  });
});

const playButton = document.querySelector('#playStory');
playButton.addEventListener('click', async () => {
  playButton.disabled = true;
  // 演出期间禁用整排按钮。原先没有这层保护——演到一半再点一次「从头演一遍」，
  // 两场演出会争同一个 story 对象，第二场的第 6 拍会拿第一场的摘要去批第二场的任务。
  //
  // 跳转按钮一并禁掉：它们会把手机换到另一端，而正在演的那一拍下一步就要往那台
  // 手机里填字。两边同时动，注入会落在刚被换掉的那个 document 上。
  document.querySelectorAll('[data-run], [data-jump]').forEach((b) => { b.disabled = true; });
  const original = playButton.textContent;
  try {
    for (const [beat, run, out] of BEATS) {
      playButton.textContent = `正在演第 ${Number(beat)} 拍……`;
      try {
        await run();
      } catch (error) {
        report(error, out);
        throw error;
      }
      // 一拍一顿。全部瞬间跑完的话，评委看到的是七块同时出现的文字，
      // 而这一页的论点恰恰是"这件事有先后顺序"。
      await sleep(420);
    }
    statusEl.textContent = '七拍全部走完，全部是真实接口的真实返回。'
      + '她那两句话是真的从右边那台手机上发出去的，每一拍都可以展开看原始响应，也可以单独重跑。';
  } catch (_) {
    statusEl.textContent += '（演出在这里停下了。没有跳过失败的那一拍。）';
  } finally {
    playButton.textContent = original;
    playButton.disabled = false;
    document.querySelectorAll('[data-run], [data-jump]').forEach((b) => { b.disabled = false; });
  }
});

applyPhoneSize();
login()
  .then(() => {
    statusEl.textContent = '演示环境已就绪。按「从头演一遍」，'
      + '或者点左边任意一拍的序号，让右边那台手机装到那一步。';
  })
  .catch((error) => { statusEl.textContent = error.message; });
