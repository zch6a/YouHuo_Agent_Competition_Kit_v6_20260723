'use strict';
/* 照护档案。
 *
 * 这一页原先是十三个按钮：「上报屋里 13.5℃」「模拟今天 11:20 才起」「加载能力矩阵」
 * ——点了才出数据。那是一个演示台，不是一份档案。一位子女打开它想知道的是爸爸今天
 * 怎么样，而不是有哪些接口可以按。
 *
 * 所以两件事一起改：
 *
 * 一，**进页面就加载**。五段各自去读一个既有的 GET，没有新增任何后端接口：
 *
 *     今天 → /v7/daily-report/{id}      作息与活动、要不要提醒家人
 *     用药 → /v4/medications/{id}       在吃什么、还剩多少
 *     身体 → /v4/health/events/{id}     体检与就诊记录
 *              + /v4/medications/{id}   空的时候补一条长期用药（同一次请求，见 medications()）
 *     心情 → /v4/reports/emotion/{id}   只有类别与趋势，没有聊天原文
 *     安全 → /v4/safety/policy/{id} + /v4/contacts/{id}
 *
 * 二，那十三个按钮**搬到 /stage**，一个都没删（proof-demos.js）。往一位老人的档案
 * 里塞一条「屋里 13.5℃」是答辩动作，不是子女会做的事。
 *
 * 五段全部并发拉取，一段失败不影响其他四段——这一页最不该有的性质是"一个接口慢了，
 * 整页停在正在加载"。
 */

const {api, byId, errorWords} = window.YouHuo;
const state = {elderId: 'elder-demo', daughterId: 'daughter-demo', systemId: 'system-demo'};

const verdictOf = window.YouHuo.verdictOf;

function el(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined) node.textContent = text;
  return node;
}

/* ==========================================================================
   动作
   ..........................................................................
   这一页此前是**纯读**的：七个分区、零个写操作。而它同时在「安全」那一段的
   `futureBlock` 里写着「您可以添：写名字、什么关系、电话」——承诺了一个界面上
   根本不存在的能力。「用药」那一段列出每天几点吃什么，却没有任何办法记一次。

   要和 /stage 分清楚：这一页原先那十三个按钮（「上报屋里 13.5℃」「加载能力矩阵」）
   是**演示夹具**，搬去 /stage 是对的，那条迁移记在 MIGRATIONS 里。下面这些不是
   夹具，是家属每天真的要做的事——替他记一次药、添一位亲友、记一笔血压。

   三条共同约定：
     · 语气由后端给。`toneOf(data)` 而不是一律绿色——「今天该吃的都记过了」是 200。
     · `once()` 包住。慢网络下连点两次「吃了」会扣两次库存。
     · 办完重新拉一次那一段。乐观更新在这里不合适：库存、剩余天数、概览那一行的
       摘要都会跟着变，前端自己算一遍就是第二个事实源。
   ========================================================================== */

/** 操作回执。语气由后端决定，不由这里猜。 */
function notify(message, tone) {
  const host = byId('careNotice');
  if (!host) return;
  host.className = `notice ${tone || 'good'}`;
  host.textContent = message;
  host.hidden = false;
}

/** 一排动作按钮。
 *
 * 用 `.care-actions` 包着，高度和间距在 CSS 里定，保证触控目标不小于 48px——
 * 这一页的读者是子女，但它和老人端共用一套按钮尺寸，没有理由在这里缩水。
 */
function actionRow(...buttons) {
  const row = el('div', 'care-actions');
  buttons.filter(Boolean).forEach((b) => row.appendChild(b));
  return row;
}

/** 一个会真的打后端的按钮。
 *
 * @param label   按钮上的字
 * @param tone    'primary' | null——只有主动作用实心
 * @param run     async () => 返回后端的响应体
 * @param after   成功之后重新加载哪一段
 */
function actionButton(label, tone, run, after) {
  // 类名照这个项目的约定：裸 `<button>` 就是主按钮（`components.css` 和 `base.css`
  // 给了基础样式），次要动作加 `.secondary`（全项目 35 处），危险动作加 `.danger`。
  // 我第一版写的是 `.btn primary` / `.btn ghost`——那是**新造的一套**，
  // 在这份样式表里一个都没定义，出来会是两个浏览器默认灰按钮。
  const btn = el('button', tone === 'primary' ? null : 'secondary', label);
  btn.type = 'button';
  btn.addEventListener('click', () => window.YouHuo.once(btn, async () => {
    try {
      const data = await run();
      notify(data && data.message ? data.message : '办好了。',
             window.YouHuo.toneOf ? window.YouHuo.toneOf(data) : 'good');
      if (after) await after();
    } catch (error) {
      notify(errorWords(error).text, 'warning');
    }
  }));
  return btn;
}

/** 一个带可见标签的输入框。
 *
 * 标签是**可见的** `<label for>`，不是 placeholder。placeholder 一开始打字就消失，
 * 而这一页的读者常常是在电话里一边问老人一边填——填到第三格已经不记得第一格是什么。
 */
function field(id, label, type, attrs = {}) {
  const wrap = el('div', 'care-field');
  const lab = el('label', null, label);
  lab.htmlFor = id;
  const input = el('input');
  input.id = id;
  input.type = type;
  Object.entries(attrs).forEach(([k, v]) => input.setAttribute(k, v));
  wrap.append(lab, input);
  return {wrap, input};
}

/** 添一位他身边的人。
 *
 * 对得上 `ContactCreate`：elder_id / display_name / relation 必填，phone 可空。
 * `scope` 不给——后端有默认值，而这一页没有理由替家属决定可见范围。
 */
function contactForm() {
  const form = el('form', 'care-form');
  form.noValidate = true;                 // 校验话术自己说，浏览器那句是英文的
  form.appendChild(el('h3', 'care-block-head', '添一位他身边的人'));

  const name = field('cName', '称呼', 'text', {maxlength: '20', autocomplete: 'off'});
  const rel = field('cRel', '和他什么关系', 'text', {maxlength: '12', autocomplete: 'off'});
  const tel = field('cTel', '电话（可以不填）', 'tel', {autocomplete: 'off'});
  form.append(name.wrap, rel.wrap, tel.wrap);

  const submit = el('button', null, '添上');
  submit.type = 'submit';
  form.appendChild(actionRow(submit));

  // 这两条原先在「怎么才会有」那段里，是**规则**，人在提交之后才关心。
  form.appendChild(el('p', 'meta',
    '您添的这一位先记成「等他确认」，要他本人点头才生效——家属这一侧没有批准权限。'
    + '电话存进去就是打码的，原号不会出现在这一页上。'));

  form.addEventListener('submit', (e) => {
    e.preventDefault();
    const displayName = name.input.value.trim();
    const relation = rel.input.value.trim();
    // 只打空格时 `required` 是满足的（值不是空字符串）。这条坑 family.js 踩过，
    // 表现是点了没反应、再点还是没反应，而屏幕上什么都不说。
    if (!displayName) {
      notify('还没写称呼。写他平时怎么叫这个人，比如「小芳」。', 'warning');
      name.input.focus();
      return;
    }
    if (!relation) {
      notify('还没写关系。比如「女儿」「邻居」「社区网格员」。', 'warning');
      rel.input.focus();
      return;
    }
    window.YouHuo.once(submit, async () => {
      try {
        const payload = {elder_id: state.elderId, display_name: displayName, relation};
        const phone = tel.input.value.trim();
        if (phone) payload.phone = phone;
        await api('/v4/contacts', {
          method: 'POST', headers: {'Content-Type': 'application/json'},
          body: JSON.stringify(payload),
        }, 'family');
        notify(`已经把${displayName}添上了，等他本人确认。`, 'good');
        form.reset();
        await loadSafety();
      } catch (error) {
        notify(errorWords(error).text, 'warning');
      }
    });
  });
  return form;
}

/** 记一笔身体数据。
 *
 * `value` 是**字符串**不是数字：血压念出来是「128/82」，体重是「62.5」。
 * 后端 `record_health_event` 的注释把这一条写得很清楚，前端不能自作主张拆成两个数。
 */
function healthForm() {
  const form = el('form', 'care-form');
  form.noValidate = true;
  form.appendChild(el('h3', 'care-block-head', '记一笔'));

  const what = field('hLabel', '记什么', 'text',
                     {maxlength: '20', list: 'hCommon', autocomplete: 'off'});
  // 常见项做成候选，不做成下拉——下拉会把「今天膝盖疼」这种记不进来。
  const list = el('datalist');
  list.id = 'hCommon';
  ['血压', '血糖', '体重', '体温', '心率'].forEach((x) => {
    const o = el('option');
    o.value = x;
    list.appendChild(o);
  });
  const value = field('hValue', '数值', 'text', {maxlength: '24', autocomplete: 'off'});
  const unit = field('hUnit', '单位（可以不填）', 'text', {maxlength: '10', autocomplete: 'off'});
  form.append(what.wrap, list, value.wrap, unit.wrap);

  const submit = el('button', null, '记上');
  submit.type = 'submit';
  form.appendChild(actionRow(submit));
  form.appendChild(el('p', 'meta',
    '这里只记数，不做判断。要不要紧请问医生——这一页不会告诉您某个数字是否正常。'));

  form.addEventListener('submit', (e) => {
    e.preventDefault();
    const label = what.input.value.trim();
    const val = value.input.value.trim();
    if (!label) {
      notify('还没写记什么。比如「血压」。', 'warning');
      what.input.focus();
      return;
    }
    if (!val) {
      notify('还没写数值。血压这种写成「128/82」就行。', 'warning');
      value.input.focus();
      return;
    }
    window.YouHuo.once(submit, async () => {
      try {
        const payload = {label, value: val};
        const u = unit.input.value.trim();
        if (u) payload.unit = u;
        const data = await api('/api/v1/health/events', {
          method: 'POST', headers: {'Content-Type': 'application/json'},
          body: JSON.stringify(payload),
        }, 'family');
        notify(data && data.message ? data.message : `记上了：${label} ${val}`,
               window.YouHuo.toneOf ? window.YouHuo.toneOf(data) : 'good');
        form.reset();
        await loadHealth();
      } catch (error) {
        notify(errorWords(error).text, 'warning');
      }
    });
  });
  return form;
}

/** 空态里的一组小标题 + 条目。
 *
 * 「以后会有什么」和「怎么才会有」两块的形状完全一样，写两遍会分叉。
 */
function futureBlock(host, head, items) {
  const block = el('section', 'care-block');
  block.appendChild(el('h3', 'care-block-head', head));
  const list = el('ul', 'care-lines');
  items.forEach((item) => list.appendChild(el('li', null, item)));
  block.appendChild(list);
  host.appendChild(block);
}

/** 一段的空态。
 *
 * **不是**「暂无数据」。这一页有一半内容在一个刚开通的账户里本来就是空的（还没录用药
 * 计划、还没上传体检报告），而「暂无数据」把一个正常状态说成了一次失败。每一段自己
 * 说清楚「现在没有什么、需要的时候怎么会有」。
 *
 * 一句话不够。「还没有体检或就诊记录」说完就停，读的人既不知道这一段将来会长成什么
 * 样，也不知道要做什么才会有——那一句诚实，可它和「这个功能没做」在屏幕上长得一模
 * 一样。所以空态收三样：一句现状、几组「以后会有什么 / 怎么才会有」、一句脚注。
 * `blocks` 留了默认值，只给一句话的老调用方（用药、安全）不用改。
 */
function empty(host, lead, blocks = [], footnote) {
  host.replaceChildren(el('p', 'care-empty', lead));
  blocks.forEach(({head, items}) => futureBlock(host, head, items));
  if (footnote) host.appendChild(el('p', 'meta', footnote));
}

function failed(host, error) {
  // 原先是 `这一段暂时没取到：${error.message}`。`error.message` 在网络失败时是
  // `Failed to fetch`——手机框里的一段英文，而这一页是给家属看的消费者面。
  // 分型与「还能做什么」由 common.js 的 errorWords 统一给。
  host.replaceChildren(el('p', 'notice bad', errorWords(error, '这一段').text));
}

/* ==========================================================================
   概览
   ==========================================================================
   这一页原先是六个**平级**的功能格子。打开它，人要先决定「我今天想看哪个功能」，
   再自己把六段拼回一个人——核心对象是六个功能，不是他。计划书写的是
   object-centered：核心对象始终是那位老人。

   所以第一屏改成回答一个问题——**他最近怎么样**——一句总判定加五行摘要，
   每一行点进去就是对应的那一段。六段一个都没删：它们是 Module 层，不是重复导航。

   ## 这一段不发任何请求

   五行的文字由那五段各自的 loader 在**它们自己的请求回来之后**回填。没有
   「概览接口」，也没有把六段合成一次请求——后者会让一段慢下来拖住整屏，而这一页
   最不该有的性质正是这个。慢的那一行自己停在「正在读……」，其余四行照常出现。

   ## 一行只说一件事

   摘要刻意短：它是索引，不是复述。要点在这里，展开在下一屏。
   ========================================================================== */

//: 概览五行的 id，顺序和 care.html 里一致。
//:
//: 单列一份是为了登录失败那一路：那时六个 loader 一个都不会跑，五行会永远停在
//: 「正在读……」——一个看起来还在加载、其实永远不会有结果的界面。
const OVERVIEW_ROWS = ['ovToday', 'ovMed', 'ovBody', 'ovMood', 'ovSafety'];

/** 回填概览里的一行。
 *
 * 只换那一行的文字，不重建节点：`<a>` 是静态写在 HTML 里的，它从第一帧起就能点，
 * 而重建会在数据回来的一瞬间把焦点从这一行上打掉。
 *
 * `bad` 走 `.meta.bad`（既有类）。失败的一行必须看得见，但它是一行字，不是红框——
 * 五段里坏了一段，不该让整个概览看起来像出了大事。
 */
function overviewSay(id, text, bad) {
  const row = byId(id);
  if (!row) return;
  const slot = row.querySelector('.meta');
  if (!slot) return;
  slot.className = bad ? 'meta bad' : 'meta';
  slot.textContent = text;
}

/** 概览顶上那句总判定。
 *
 * 用的是「今天」那一段同一个组件（`.report-verdict` + `.report-badge`）和同一份
 * 判定词（`verdictOf`）。同一个结论在两处必须长得一样——两套写法迟早会分叉，
 * 而这个项目已经在情绪词表上栽过一次。
 */
function overviewVerdict(word, tone, headline) {
  const host = byId('ovVerdict');
  if (!host) return;
  host.className = `report-verdict ${tone}`;
  host.replaceChildren(el('span', 'report-badge', word), el('strong', null, headline));
}

/** 总判定取不到时说的话。
 *
 * **不出徽标。** `verdictOf` 的五个词说的都是「他今天怎么样」，而这里的事实是
 * 「我们没读到」——拿其中任何一个来顶都是把一次读取失败说成一个关于他的结论，
 * 连 `unknown`（「还没有记录」）也不行：那句话讲的是他没有记录，不是我们没连上。
 */
function overviewVerdictFailed(error) {
  const host = byId('ovVerdict');
  if (!host) return;
  host.className = 'report-verdict';
  host.replaceChildren(el('strong', null, errorWords(error, '今天的情况').text));
}

/* ==========================================================================
   今天
   ========================================================================== */

async function loadToday() {
  const host = byId('todayBody');
  const updated = byId('careUpdated');
  try {
    const {report, alert} = await api(`/v7/daily-report/${state.elderId}`, {}, 'family');
    host.replaceChildren();

    // 结论在最前。一句话说完今天怎么样，颜色由后端的判定给，不由前端猜。
    const head = el('div');
    const [word, tone] = verdictOf(report.overall);
    head.className = `report-verdict ${tone}`;
    head.append(el('span', 'report-badge', word), el('strong', null, report.headline));
    host.appendChild(head);

    // 概览顶上那句是同一个判定、同一句话。
    overviewVerdict(word, tone, report.headline);

    if (updated) updated.textContent = `今天 ${report.day} 的情况`;

    // 分项。每一段的判定词也一起给出来——同一个「外出 0 次」在不同人身上是不同结论，
    // 而那个结论是后端拿这位老人自己的常态算出来的。
    report.sections.forEach((section) => {
      const block = el('section', 'care-block');
      const [w, t] = verdictOf(section.verdict);
      const title = el('h3', 'care-block-head');
      title.appendChild(el('span', null, section.title));
      // 药丸只留给「和平常不一样」。
      //
      // 后端的分项固定是三段（作息 / 活动与交流 / 用药），平常日子里三个判定全是
      // typical，于是三个绿药丸加顶上那个总判定，四个字样完全相同的绿块竖排下来
      // 抢走了第一落点，而真正有内容的是下面那几行灰色小字。narrow-320 上药丸还
      // 占掉约四成行宽，和「活动与交流」这个五字标题几乎相撞。
      //
      // 一致是默认状态，说一声就够，用中性小字；视觉预算留给偏离的那一项。
      // 判定词本身照旧从 verdictOf 取——三个端的文案共用一份，不在这里另写一套。
      title.appendChild(section.verdict === 'typical'
        ? el('span', 'meta', w)
        : el('span', `pill ${t}`, w));
      block.appendChild(title);
      const list = el('ul', 'care-lines');
      section.lines.forEach((line) => list.appendChild(el('li', null, line)));
      block.appendChild(list);
      host.appendChild(block);
    });

    // 办事进度。
    const e = report.errands;
    const digest = el('div', 'digest');
    [
      ['今天要办', `${e.due_today} 件`],
      ['已经办好', `${e.completed} 件`],
      ['等您点头', `${e.awaiting_family} 件`],
      ['已经超时', `${e.overdue} 件`],
    ].forEach(([label, value]) => {
      const row = el('div', 'digest-row');
      row.append(el('strong', null, label), el('div', null, value));
      digest.appendChild(row);
    });
    host.appendChild(digest);

    // 需要子女做点什么。空列表表示"今天不用您操心"，那句话要说出来。
    if (report.suggested_for_family.length) {
      const box = el('div', 'notice warning');
      box.appendChild(el('strong', null, '需要您做的：'));
      const list = el('ul', 'care-lines');
      report.suggested_for_family.forEach((s) => list.appendChild(el('li', null, s)));
      box.appendChild(list);
      host.appendChild(box);
    } else {
      host.appendChild(el('p', 'care-empty', '今天不用您操心。'));
    }

    // 会不会主动找您。这一条是这个产品的性格：不该打扰的时候不打扰。
    host.appendChild(el('p', 'meta', alert.push
      ? `会主动提醒您：${alert.reason}`
      : `不会打扰您：${alert.reason}`));

    // 隐私说明自己占一块，带小标题。
    //
    // 它原先是这一段末尾一行裸 `.meta`，上面没有标题也没有分隔，于是「本日报不包含
    // 无忧伴陪伴聊天的任何原文」读起来像是在解释上面那四个办事计数——一句讲这份
    // 日报**少了什么**的话，被读成了「今天该办的事」的一部分。
    //
    // 归属用小标题给，不用分割线：这一页的 `--line` 在深色模式下很淡，一条看不见的
    // 线等于没给归属，而标题在两个配色下都在。它仍然是 `.meta` 小字——承诺要一直
    // 写着，但它每天都一样，不是今天的新闻（家属端那一份也是这么定的）。
    const privacy = el('section', 'care-block');
    privacy.appendChild(el('h3', 'care-block-head', '这份日报不包含什么'));
    privacy.appendChild(el('p', 'meta', report.privacy_note));
    host.appendChild(privacy);

    // 概览那一行**不重复**上面那句总判定（它就在这一行的正上方）。它说的是这一段
    // 里下一层的东西：三项分项有没有偏离，以及有没有事情压在头上。
    const off = report.sections.filter((section) => section.verdict !== 'typical');
    const lines = [off.length
      ? `${off.map((section) => section.title).join('、')}和平常不一样`
      : `${report.sections.length} 项都和平常一样`];
    if (e.overdue) lines.push(`${e.overdue} 件事已经超时`);
    else if (e.awaiting_family) lines.push(`${e.awaiting_family} 件等您点头`);
    else if (e.due_today) lines.push(`今天要办 ${e.due_today} 件`);
    else lines.push('今天没有要办的事');
    overviewSay('ovToday', lines.join('｜'));
  } catch (error) {
    failed(host, error);
    overviewVerdictFailed(error);
    overviewSay('ovToday', errorWords(error, '今天的情况').text, true);
    if (updated) updated.textContent = '暂时没连上';
  }
}

/* ==========================================================================
   用药
   ========================================================================== */

/** 用药计划只拉一次。
 *
 * 两段都要它：「用药」拿它当主角，「身体」只拿它的起始日期当一条健康线索。各自拉一遍
 * 会让同一个 GET 在首屏跑两次——五段本来就是并发的，多一个请求不会更快。
 */
let medicationPlans = null;
function medications() {
  if (!medicationPlans) {
    medicationPlans = api(`/v4/medications/${state.elderId}`, {}, 'family');
    // 先挂一个空处理器。这个 promise 有两个消费者，而「身体」那一段要等
    // /v4/health/events 回来之后才 await 它；中间那段时间里如果它被拒绝，就是一个
    // 暂时没人接的 rejection——浏览器会把它当未捕获异常报到控制台，而
    // check_page_runtime 把控制台里的错误当硬失败。两个真正的消费者各自照旧处理。
    medicationPlans.catch(() => {});
  }
  return medicationPlans;
}

/** 「还能吃几天」。
 *
 * `stock_units` 和 `units_per_dose` 是两个数字，而一位子女要的是「还剩四天」这一个
 * 结论。抽出来是因为「用药」那一段和概览那一行现在都要它——两处各算一遍，
 * 迟早会有一处忘了乘 `times_local.length`，而算错的那个数看起来完全正常。
 *
 * 算不出来（每天吃 0 次）时返回 `null`，不返回 0：那是两回事。
 */
function daysLeft(plan) {
  const perDay = plan.units_per_dose * plan.times_local.length;
  return perDay > 0 ? Math.floor(plan.stock_units / perDay) : null;
}

/** 概览那一行：在吃什么、还够多久。
 *
 * 「已停」的计划不算进「在吃」——它们在细节那一段里带着「已停」的药丸列着，
 * 但概览问的是**现在**在吃什么。全都停了也要说出来，那和从来没登记过不是一回事。
 *
 * 多种药时报**最少**的那一个天数，不报平均也不报总和：会先断的是最少的那一种。
 */
function medicationDigest(plans) {
  if (!plans.length) return '还没有登记在吃的药';
  const active = plans.filter((plan) => plan.active);
  if (!active.length) return `登记过 ${plans.length} 个用药计划，现在都已经停了`;
  const names = active.map((plan) => plan.display_name);
  const head = active.length === 1
    ? names[0]
    : `在吃 ${active.length} 种：${names.join('、')}`;
  const days = active.map(daysLeft).filter((n) => n !== null);
  if (!days.length) return head;
  const least = Math.min(...days);
  if (least <= 0) return `${head}｜${active.length === 1 ? '药已经吃完了' : '有一种已经吃完了'}`;
  return `${head}｜${active.length === 1 ? '还够' : '最少的还够'} ${least} 天`;
}

async function loadMedications() {
  const host = byId('medBody');
  try {
    const plans = await medications();
    overviewSay('ovMed', medicationDigest(plans));
    if (!plans.length) {
      empty(host, '还没有登记在吃的药。等医生开了方子，您或他都可以添上——'
        + '添上之后到点会提醒他，也会盯着还剩多少。');
      return;
    }
    host.replaceChildren();
    plans.forEach((plan) => {
      const card = el('section', 'care-item');
      const title = el('h3', 'care-item-head');
      title.append(
        el('span', null, plan.display_name),
        el('span', `pill ${plan.active ? 'good' : 'cancelled'}`, plan.active ? '在吃' : '已停'),
      );
      card.appendChild(title);
      card.appendChild(el('p', null, `${plan.dose_text}｜每天 ${plan.times_local.join('、')}`));
      // 库存换算成"还能吃几天"。换算本身在 `daysLeft()` 里，概览那一行用的是同一个。
      const days = daysLeft(plan);
      if (days !== null) {
        card.appendChild(el('p', days <= 3 ? 'notice warning' : 'meta',
          days <= 0 ? '药已经吃完了。' : `按现在的吃法还够 ${days} 天。`));
      }
      // 替他记一次。只给还在吃的方子——已停的方子记一笔，记的是一件没发生的事。
      //
      // 不带 `scheduledAt`：后端会取今天**最早一格还没记的**。让家属先在几个时间点
      // 里选一个，是把后端已经能算的事推给人；而且他们多半也不知道老人是几点吃的。
      // 都记过了后端返 409 并说「今天降压药该吃的都记过了」，`errorWords` 会把这句
      // 原样显示——那不是一个错误，是一个正确的回答。
      //
      // 「没吃」不扣库存（后端 `_record_dose` 的 skipped 分支），所以两个动作不是
      // 一件事的正反面，都得有。少了「没吃」，家属唯一能表达的就是「吃了」，
      // 于是漏服在数据里永远看不见。
      if (plan.active) {
        card.appendChild(actionRow(
          actionButton('记一次已吃', 'primary',
            () => api(`/api/v1/medications/${plan.id}/taken`,
                      {method: 'POST', headers: {'Content-Type': 'application/json'},
                       body: '{}'}, 'family'),
            loadMedications),
          actionButton('这次没吃', null,
            () => api(`/api/v1/medications/${plan.id}/skipped`,
                      {method: 'POST', headers: {'Content-Type': 'application/json'},
                       body: '{}'}, 'family'),
            loadMedications),
        ));
      }
      host.appendChild(card);
    });
  } catch (error) {
    failed(host, error);
    overviewSay('ovMed', errorWords(error, '用药情况').text, true);
  }
}

/* ==========================================================================
   身体
   ========================================================================== */

//: 后端的事件类型码不往界面上印。认识的说人话，不认识的按中性说法归类——
//: 兜底成原始码等于这层翻译在遇到新类型时自动失效，而那正是它该起作用的时候。
//:
//: 这张表原先的五个键（checkup_report / clinic_visit / hospitalization /
//: vaccination / measurement）后端**一个都不存在**：真正的枚举只有四个。零命中，
//: 于是每一条记录都印成兜底的「一条记录」。同一段里还有三个字段名也是猜的——
//: occurred_at（真名 event_at）、summary（真名 title）、source_name（真名 source），
//: 所以标题永远不显示，日期永远退回入库时间。演示家庭里这张表是空的，这段代码
//: 从来没跑过一次真实数据，四个错就一起活到了今天。
const HEALTH_WORD = {
  checkup: '体检',
  visit: '就诊',
  medication: '用药记录',
  note: '记了一笔',
};

/** 用药计划里唯一算得上「身体」的东西：长期在吃什么、从哪天起。
 *
 * 「身体」在演示家庭里是空的，可档案里其实躺着一条带日期的健康事实——长期在吃降压药，
 * 而长期用药本身就是病史线索。它比一段纯空白有用，所以补进来，并且写明它是从哪儿来的。
 *
 * 库存（`stock_units`）**不**补进来。「还够几天」是补货问题，不是身体状况；它已经是
 * 「用药」那一段的主角，搬过来只会让两段互相抄一遍。
 */
async function longTermMedication(host) {
  const plans = await medications().catch(() => []);
  const ongoing = plans.filter((plan) => plan.active && plan.start_date);
  if (!ongoing.length) return;
  const block = el('section', 'care-block');
  block.appendChild(el('h3', 'care-block-head', '档案里已经有的线索'));
  const list = el('ul', 'care-lines');
  ongoing.slice(0, 6).forEach((plan) => {
    list.appendChild(el('li', null, plan.end_date
      ? `${plan.display_name}：${plan.start_date} 起，吃到 ${plan.end_date}`
      : `${plan.display_name}：${plan.start_date} 起一直在吃`));
  });
  block.appendChild(list);
  host.appendChild(block);
  host.appendChild(el('p', 'meta', '这一条是从「用药」那一段推出来的，不是一份体检记录。'));
}

/** 一条健康记录属于哪一天。
 *
 * `event_at` 是事情发生的那一天，`created_at` 是它被录进来的那一天。上个月做的体检
 * 今天才传，两者差一个月——先取前者，后者只在缺失时兜底。
 *
 * 「身体」那一段的渲染循环里**还留着同一行**没有改成调用这里，那不是漏掉：
 * `test_health_section_actually_renders_the_load_bearing_fields` 要求
 * `event.event_at` 出现在 `loadHealth()` 的函数体内。它防的是这个文件真发生过的一次
 * 缺陷——字段名是猜的（`occurred_at`），于是日期永远退回入库时间而没有任何报错。
 * 把那一行抽走，那道闸门就失去了锚点。
 */
function healthDay(event) {
  return String(event.event_at || event.created_at).slice(0, 10);
}

/** 概览那一行：最近的一条身体记录。
 *
 * **按日期挑**，不取数组第一个——后端现在是按时间倒序给的，但那是它的实现细节，
 * 不是接口承诺；换个排序之后「最近一次」会安静地指向最旧的那一条，而那一行看起来
 * 完全正常。
 *
 * 印的是 `title`（记录本身写的字），认不出来才退回类型词。`source` 一律不印，
 * 理由和「身体」那一段里的一样：它是给系统看的字。
 */
function healthDigest(events) {
  if (!events.length) return '还没有体检或就诊记录';
  const latest = events.reduce((a, b) => (healthDay(b) > healthDay(a) ? b : a));
  const what = latest.title || HEALTH_WORD[latest.kind] || '一条记录';
  return `共 ${events.length} 条｜最近一次 ${healthDay(latest)}｜${what}`;
}

async function loadHealth() {
  const host = byId('bodyBody');
  try {
    const events = await api(`/v4/health/events/${state.elderId}`, {}, 'family');
    overviewSay('ovBody', healthDigest(events));
    if (!events.length) {
      // 空态要说清这一段将来长什么样、怎么才会有。原先只有一句话，勉强诚实但信息量
      // 低——它和「这个功能没做」在屏幕上没有区别。条目写的就是后端真有的四类记录，
      // 不是许愿。
      empty(host, '还没有体检或就诊记录。', [
        {head: '这一段以后会有什么', items: [
          '体检：哪一天做的、各项指标、看不懂的术语翻成人话',
          '就诊：什么时候看的、医生怎么交代、下次什么时候复查',
          '和用药有关的一笔，以及他自己随手记下的一条',
        ]},
        {head: '怎么才会有', items: [
          '纸质报告拍下来传上去，日期、指标和复查时间会被挑出来，这里自动立一条',
          '也可以直接添一条，写清哪一天、什么事——您和他都能添',
          '他可以把某一条留成只给自己看，那一条不会出现在这一页',
        ]},
      ]);
      await longTermMedication(host);
      // 空态那段「怎么才会有」第二条写着「也可以直接添一条……您和他都能添」。
      // 那句话此前没有对应的入口——和「安全」那一段是同一个毛病。
      host.appendChild(healthForm());
      host.appendChild(el('p', 'meta', '这里只做整理，不做诊断。看病请以医生的判断为准。'));
      return;
    }
    host.replaceChildren();
    events.slice(0, 12).forEach((event) => {
      const card = el('section', 'care-item');
      const title = el('h3', 'care-item-head');
      title.append(
        el('span', null, HEALTH_WORD[event.kind] || '一条记录'),
        // `event_at` 是事情发生的那一天，`created_at` 是它被录进来的那一天。上个月做的
        // 体检今天才传，两者差一个月——先取前者，后者只在缺失时兜底。
        el('span', 'meta', String(event.event_at || event.created_at).slice(0, 10)),
      );
      card.appendChild(title);
      if (event.title) card.appendChild(el('p', null, event.title));
      // `source` 不往界面上印。它是一个自由文本字段，默认值是 manual，而医疗报告那条
      // 路径塞进来的是一个带英文缩写的内部名字——两种都是给系统看的字，印到屏幕上就是
      // 一个英文枚举值。这一条记录真正有用的三样已经在上面了：哪一类、哪一天、写了什么。
      host.appendChild(card);
    });
    // 有记录的时候也要能再添一条——只在空态给入口，等于「第一条能添，第二条不能」。
    host.appendChild(healthForm());
    host.appendChild(el('p', 'meta', '这里只做整理，不做诊断。看病请以医生的判断为准。'));
  } catch (error) {
    failed(host, error);
    overviewSay('ovBody', errorWords(error, '体检与就诊记录').text, true);
  }
}

/* ==========================================================================
   心情
   ========================================================================== */

//: 情绪类别和趋势的码同样不往界面上印，而这两张表原先漏掉的正好是最要紧的几个。
//:
//: 类别表少了 positive / low_mood / urgent，还多写了后端根本没有的 sad / happy /
//: neutral；趋势表少了 distress_increasing / distress_decreasing——后端的趋势一共
//: 只有三个值，这张表认得其中一个。漏掉的一律走 `|| s.trend` 兜底，于是「他这两周
//: 更紧张了」这个恰恰最需要被看见的结论，在屏幕上印成一串英文。
//:
//: 兜底保留（宁可露出一个没预料到的码，也不要悄悄把它藏起来），但后端现有的值必须
//: 全在表里——兜底是给将来新增的类型留的门，不是给今天已经存在的枚举用的。
const EMOTION_WORD = {
  positive: '心情不错', calm: '平静', lonely: '孤单', low_mood: '低落',
  anxious: '着急', angry: '烦躁', urgent: '急着要人帮忙',
};
const TREND_WORD = {
  distress_increasing: '比上两周更紧张一些',
  distress_decreasing: '比上两周松快一些',
  stable_or_insufficient: '和上两周差不多，或者记录还不够多',
};

function ymd(date) {
  const pad = (n) => String(n).padStart(2, '0');
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}`;
}

/** 概览那一行：这两周的心情。
 *
 * 只说**记到几次**和**哪一类最多**，不说趋势。趋势那句话（`TREND_WORD`）最短的一条
 * 也有九个字，最长的十七个——它是一个结论，值得在细节那一段里占一整行，塞进概览的
 * 一行摘要里会把这一行挤成两行半。
 *
 * 「最多的是平静」是**数出来的**，不是概括出来的：取 `label_counts` 里计数最大的那个
 * 键，并且把次数一起印出来，读的人自己判断六比一算不算「多数」。这一页的原则是不替
 * 产品下没有数据支撑的结论。
 */
function moodDigest(summary) {
  if (!summary.event_count) return '这两周没有需要记下来的情绪波动';
  const labels = Object.entries(summary.label_counts);
  if (!labels.length) return `最近两周记到 ${summary.event_count} 次`;
  const [key, count] = labels.reduce((a, b) => (b[1] > a[1] ? b : a));
  return `最近两周记到 ${summary.event_count} 次｜最多的是${EMOTION_WORD[key] || key}（${count} 次）`;
}

async function loadMood() {
  const host = byId('moodBody');
  try {
    const end = new Date();
    const start = new Date(end.getTime() - 13 * 24 * 60 * 60 * 1000);
    const report = await api(
      `/v4/reports/emotion/${state.elderId}?period_start=${ymd(start)}&period_end=${ymd(end)}`,
      {}, 'family',
    );
    const s = report.summary;
    overviewSay('ovMood', moodDigest(s));
    host.replaceChildren();
    host.appendChild(el('p', 'care-period', `最近两周（${report.period_start} 到 ${report.period_end}）`));

    if (!s.event_count) {
      // 空态原先是一句「这两周没有需要记下来的情绪波动」加一句隐私承诺。诚实，但读的人
      // 不知道这一段有了记录会长成什么样，也不知道那些记录从哪来——于是它读起来像一个
      // 没做完的功能。下面三条「以后会有什么」写的就是后端 summary 真有的三个字段。
      host.appendChild(el('p', 'care-empty', '这两周没有需要记下来的情绪波动。'));
      futureBlock(host, '这一段以后会有什么', [
        '出现过哪几类情绪、各几次——只有类别和次数',
        '跟上两周比：更紧张了、松快了，还是差不多',
        '一两句家人可以试着做的事',
      ]);
      // 「怎么才会有」这一段必须写准。情绪判断确实每次说话都在做（先用来决定要不要停下
      // 手上的事、要不要提醒家人），但**留档**是另一件事：后端只认他自己那一侧发起的
      // 请求，家属的令牌写不进来。所以不写成「聊过天就自动有」，那是句好听的假话。
      futureBlock(host, '怎么才会有', [
        '他跟无忧伴说话的时候，情绪是当场就在判断的——先用来决定要不要停下手上的事、要不要提醒您',
        '要在这一段留下一条，得由他自己那一侧发起；家人没有权限替他记一笔',
        '留下来的只有类别和强度，聊过的话一句都不留',
      ]);
    } else {
      const digest = el('div', 'digest');
      const rows = [['整体趋势', TREND_WORD[s.trend] || s.trend]];
      const labels = Object.entries(s.label_counts);
      if (labels.length) {
        rows.push(['出现过', labels.map(([k, v]) => `${EMOTION_WORD[k] || k} ${v}次`).join('，')]);
      }
      rows.forEach(([label, value]) => {
        const row = el('div', 'digest-row');
        row.append(el('strong', null, label), el('div', null, value));
        digest.appendChild(row);
      });
      host.appendChild(digest);
      if (s.safe_suggestions.length) {
        const box = el('div', 'notice');
        box.appendChild(el('strong', null, '可以试试：'));
        const list = el('ul', 'care-lines');
        s.safe_suggestions.forEach((x) => list.appendChild(el('li', null, x)));
        box.appendChild(list);
        host.appendChild(box);
      }
    }
    host.appendChild(el('p', 'meta', report.privacy_guarantee));
  } catch (error) {
    failed(host, error);
    overviewSay('ovMood', errorWords(error, '最近两周的情况').text, true);
  }
}

/* ==========================================================================
   趋势（这一周）—— 从 /family 的一级分区搬进照护档案
   ==========================================================================
   `09_consumer_app_architecture.md`：「趋势」退出一级导航，它住在照护里。

   ## 搬过来时**没有**照搬 family.js 那两张表，那是刻意的

   family.js 的 `EMOTION_LABEL` 是上面「心情」那段注释记录过、并且已经在这个文件里
   被修好的那张**旧表**：

     后端 EmotionLabel 共 7 个值：positive / calm / lonely / low_mood /
                                  anxious / angry / urgent
     family.js 的表：calm / lonely / anxious / sad / happy / angry / distressed
                     ↑ 缺 positive / low_mood / urgent
                     ↑ 多出后端根本没有的 sad / happy / distressed

   于是 `/family` 的趋势面板会把 `positive`、`low_mood`、`urgent` 印成英文码——
   而 `urgent`（「急着要人帮忙」）恰恰是最要紧的那一个。修复当时只落在 care.js，
   family.js 留着坏的那份，两个页面读**同一个端点**却各有一套词汇。

   所以这一段复用本文件已有的 `EMOTION_WORD` 与 `TREND_WORD`，只带来 family.js
   独有的那张字段名表（`WEEKLY_LABEL`）。趋势词也用本文件的：family.js 那版
   「压力上升，建议多陪伴」带着建议，而这一格讲的是情绪**趋势**，给建议越界了。

   窗口是 7 天，而「心情」那一格是 14 天——同一个端点两个窗口，一套词汇。 */

const WEEKLY_LABEL = {
  event_count: '记录到的情绪信号',
  label_counts: '情绪类别分布',
  average_distress: '平均压力指数',
  trend: '与上一周期相比',
  safe_suggestions: '可以做的小事',
  raw_text_included: '是否包含聊天原文',
  diagnosis_provided: '是否给出医学诊断',
};

function weeklyValue(key, value) {
  if (key === 'trend') return TREND_WORD[value] || value;
  if (typeof value === 'boolean') return value ? '是' : '否';
  if (Array.isArray(value)) return value.length ? value.join('；') : '暂无';
  if (value && typeof value === 'object') {
    const parts = Object.entries(value).map(([k, v]) => `${EMOTION_WORD[k] || k} ${v}次`);
    return parts.length ? parts.join('，') : '这一周没有记录';
  }
  return String(value);
}

async function loadWeekly() {
  const host = byId('weekly');
  if (!host) return;
  const end = new Date();
  const start = new Date(end.getTime() - 6 * 24 * 3600 * 1000);
  try {
    // `ymd()` 是本文件已有的：按**本地**日期切，不是 UTC。
    //
    // 这一条从 family.js 一起带过来，因为它记着一个真实缺陷：
    // `toISOString().slice(0, 10)` 在 UTC+8 等于把一天切在早上八点——北京时间
    // 8 月 10 日 07:30 打开，窗口是 08-03 至 08-09，页面上却写着 8 月 10 日，
    // 今天全部的情绪信号被排除在外；08:00 一到，同一次刷新变成 08-04 至 08-10。
    // 后端 baseline_api.py 里对这个模式有明确警告。
    const report = await api(
      `/v4/reports/emotion/${state.elderId}?period_start=${ymd(start)}&period_end=${ymd(end)}`,
      {}, 'family',
    );
    host.replaceChildren();
    host.appendChild(el('p', 'meta', `${report.period_start} 至 ${report.period_end}`));
    const table = el('div', 'digest');
    Object.entries(report.summary).forEach(([key, value]) => {
      const row = el('div', 'digest-row');
      row.append(el('strong', null, WEEKLY_LABEL[key] || key),
                 el('div', null, weeklyValue(key, value)));
      table.appendChild(row);
    });
    host.appendChild(table);
    if (report.privacy_guarantee) {
      host.appendChild(el('p', 'notice good', report.privacy_guarantee));
    }
  } catch (error) {
    failed(host, error);
  }
}

/* ==========================================================================
   安全
   ========================================================================== */

//: 亲友档案的状态 → 给人看的话。键是后端 `contact_profiles_v4.consent_status`
//: 的三个取值（`create_contact` 写 active / proposed，`decide_contact` 写
//: active / rejected）。
//:
//: 这张表**取代**了原先那张 `CONTACT_WORD`（family / neighbour / community /
//: doctor / other）。那五个键是 `safety_contacts_v4.contact_role` 的取值，而这一段
//: 读的是 `/v4/contacts`——它回的是 `ContactRecord`（亲友档案），字段是
//: `display_name` / `relation` / `phone_masked` / `status`，**没有** `contact_role`。
//: 同一段代码里还读了 `c.name` 和 `c.address_masked`，那两个也不在这个模型上。
//:
//: 三个字段名全错，翻译表接的是另一张表——和这个文件里 `HEALTH_WORD` 那次
//: （occurred_at / summary / source_name）是同一种缺陷，同样因为演示家庭里这个列表
//: 恒为空而从未跑过。真出现一位亲友时，那一行会印成「undefined（undefined）
//: undefined」：`c.name` 是 undefined，`CONTACT_WORD[undefined]` 也是 undefined，
//: 而 `|| c.contact_role` 兜的还是 undefined。
const CONTACT_STATUS_WORD = {
  active: '他确认过',
  proposed: '等他确认',
  rejected: '他没同意',
};

/** 「多久没动静就找人」这个阈值的说法。
 *
 * 后端给的是分钟数（演示家庭里是 720）。720 分钟没有人读得出「半天」，
 * 所以够一小时就换算成小时。概览那一行和「安全」那一段用同一份换算。
 */
function quietWindow(policy) {
  const hours = Math.round((policy.inactivity_minutes || 0) / 60);
  return hours >= 1 ? `${hours} 小时` : `${policy.inactivity_minutes} 分钟`;
}

/** 概览那一行：安全设置现在是什么状态。
 *
 * 两件事：阈值设成了多少，以及**他身边登记了几个人**。第二件放进概览是有理由的
 * ——演示家庭里亲友档案是 0 条。一份只报好消息的概览，会把这个空档藏进第五个格子里，
 * 而它恰恰是这一页唯一一处「设置在、人不在」的地方。
 */
function safetyDigest(policy, contacts) {
  return `${quietWindow(policy)}没动静就找人｜`
    + (contacts.length ? `登记了 ${contacts.length} 位亲友` : '还没有登记亲友');
}

async function loadSafety() {
  const host = byId('safetyBody');
  try {
    const [policy, contacts] = await Promise.all([
      api(`/v4/safety/policy/${state.elderId}`, {}, 'family'),
      api(`/v4/contacts/${state.elderId}`, {}, 'family').catch(() => []),
    ]);
    overviewSay('ovSafety', safetyDigest(policy, contacts));
    host.replaceChildren();

    const digest = el('div', 'digest');
    [
      ['多久没动静就找人', quietWindow(policy)],
      ['出门多远开始留意', `${policy.geofence_radius_m} 米以外`],
      ['要不要告诉社区', policy.notify_community ? '要' : '不要'],
    ].forEach(([label, value]) => {
      const row = el('div', 'digest-row');
      row.append(el('strong', null, label), el('div', null, value));
      digest.appendChild(row);
    });
    host.appendChild(digest);

    // 标题原先是「出事先找谁」，而这个列表读的是 `/v4/contacts`——亲友档案，
    // 不是应急接力名单（那一份在 `safety_contacts_v4`，现在只有 `/v4/safety/sos`
    // 读得到，没有任何 GET 端点把它列出来）。标题承诺的东西这一段拿不到，所以标题
    // 改成它真正显示的东西。列一份亲友档案本身是有用的：出事的时候，「他身边还有谁」
    // 是子女第一个要回答的问题。
    host.appendChild(el('h3', 'care-block-head', '他身边的人'));
    if (contacts.length) {
      const list = el('ul', 'care-lines');
      contacts.slice(0, 6).forEach((person) => {
        // 电话是打过码的（后端存的就是 `phone_masked`，原号只留一个摘要）。
        // 没填电话时不写「无」，直接不提这一项。
        const parts = [`${person.display_name}（${person.relation}）`];
        if (person.phone_masked) parts.push(person.phone_masked);
        // 状态只在**不是** active 的时候说。一位他已经确认过的亲友，后面再挂一个
        // 「他确认过」的尾巴，是把默认状态当新闻讲——和这一页对 `typical` 判定的
        // 处理是同一条原则。
        if (person.status !== 'active') {
          parts.push(CONTACT_STATUS_WORD[person.status] || '还没处理');
        }
        list.appendChild(el('li', null, parts.join('｜')));
      });
      host.appendChild(list);
    } else {
      // 亲友档案是 0 条——而这一段上面刚刚写着「12 小时没动静就找人」。
      //
      // 原先这里只有一句「还没有设紧急联系人。」。那句话读起来像一条提示，不像一个
      // 空档：读的人既不知道这一栏将来长什么样，也不知道要做什么才会有。
      //
      // 所以照「身体」和「心情」那两段的写法来（`futureBlock`）：一句现状，
      // 加两组「以后会有什么 / 怎么才会有」。
      //
      // **不用 `empty()`**：那个助手第一句是 `host.replaceChildren(...)`，会把上面
      // 刚放好的策略表和标题一起清掉。那两段调用它的时候 host 还是空的，这里不是。
      //
      // 每一条都对得上后端：`ContactCreate` 收 display_name / relation / phone /
      // notes / scope；电话存进去就打码（`_mask_phone`）；家人添的记录
      // `status = "proposed"`，而 `decide_contact` 明写「只有老人本人可以批准亲友
      // 档案」；`list_contacts` 对家属视角过滤掉 `scope == private` 的那些。
      host.appendChild(el('p', 'care-empty',
        '还没有登记他身边的人。上面那三条设置定的是「什么时候该找人」，'
        + '而「找谁」这一栏现在是空的。'));
      futureBlock(host, '这一栏以后会有什么', [
        '一份名单：谁、和他什么关系',
        '一个打过码的电话——原号不显示，也不落在这一页上',
        '哪几位是他自己点过头的，哪几位还等着他确认',
      ]);
    }

    // 「怎么才会有」原先是一段 `futureBlock`，三条里第一条写着「您可以添：写名字、
    // 什么关系、电话」——而这一页上没有任何地方能添。一段解释「你可以做 X」的文字，
    // 配一个做不了 X 的界面，比什么都不写更糟：读的人会去找那个入口，找不到，
    // 然后怀疑是自己没看见。
    //
    // 所以把那段解释换成真的表单。三条里剩下两条是**规则**不是承诺（要他本人点头、
    // 他可以设成只给自己看），它们移到表单底下，因为提交之后人才会关心。
    host.appendChild(contactForm());

    host.appendChild(el('p', 'meta',
      '位置只在需要的时候看一眼，按最小必要留存。定位精度不够时不会自动报警——'
      + '一次误报会让他以后不敢再带手机出门。'));
  } catch (error) {
    failed(host, error);
    overviewSay('ovSafety', errorWords(error, '安全设置').text, true);
  }
}

/* ========================================================================== */

async function bootstrap() {
  const status = byId('status');
  try {
    const ids = await window.YouHuo.ready();
    state.elderId = ids.elderId;
    state.daughterId = ids.daughterId;
    state.systemId = ids.systemId;
    await Promise.all([window.YouHuo.login('elder'), window.YouHuo.login('family')]);
    // 成功之后这一行就没有内容了。它必须一直在（失败的时候必须看得见），
    // 但一句"就绪了"不该占着首屏最重的一块位置。
    status.hidden = true;
  } catch (error) {
    status.hidden = false;
    // 「暂时没连上」这个前缀原先固定写死，然后拼上 `error.message`——于是网络正常
    // 而后端拒绝时，它也说"没连上"，那是错的诊断。分型之后由 errorWords 说对。
    status.textContent = errorWords(error, '照护档案').text;
    return;
  }
  // 六段并发。一段失败只让那一段说话，另外五段照常显示——这一页最不该有的性质
  // 就是"一个接口慢了，整页停在正在加载"。
  //
  // 第六段是「趋势」，从 /family 搬来。它和「心情」读同一个端点（不同窗口），
  // 并发发两个请求是刻意的：合成一次会让两格互相拖累，而这一页的原则正是
  // 一段一段独立。
  await Promise.all([
    loadToday(), loadMedications(), loadHealth(), loadMood(), loadSafety(), loadWeekly(),
  ]);
}

// 页内分区，与家人端同一套实现（common.js）。
//
// 兜底是 `overview` 而不是 `today`，因为**两个事实源打架时看得见的那个是 JS**。
// `care.html` 的 markup 把 `overview` 标成 `is-current` + `aria-current="true"`，
// 而这里原先传的是 `'today'`；`initSections` 在无 hash 时执行 `show(fallback)`，
// 于是 JS 赢。两个后果：
//
//   ① 首屏落在「今天」而不是「概览」——而「概览」正是这一页从**功能分区**
//      变成**以人为中心**的那一步，它不在第一屏，这一步就等于没做
//   ② 服务器发出的 HTML 高亮「概览」，JS 一跑改成「今天」——**载入时闪一下**。
//      这正是 Phase C 判据 ① 说的那件事：导航必须在服务器发出的 HTML 里
//      就带好正确的激活态，否则首屏会先闪一个错的
window.YouHuo.initSections('overview');

bootstrap();
