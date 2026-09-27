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
  window.YouHuo.showNotice(host,message,{duration:['bad','warning'].includes(tone)?0:5000});
}

/** 连接状态那一行的**语气**。
 *
 * `#status` 的静态类在 care.html 上是 `notice good care-status`，而 `bootstrap()`
 * 的失败路径原先**只改 textContent**——于是「照护档案暂时看不了：家里网不通」
 * 印在一条绿边绿底的成功框里。这是 judge.html 那个缺陷一字不差的同一个形状
 * （`judge.html:102` 写死 `notice good`，`judge.js` 五处写入只改文字），
 * 那一处这一轮已经修过，这一处当时没人看。
 *
 * **不能整句 `className = 'notice bad'`。** 两版的静态类不一样：`/care` 还带
 * `care-status`（版式：一行字不是一块横幅），`/family2` 带的是 `notice-line`。
 * 整句换掉会把版式一起换掉。所以只摘旧语气、补新语气，并保证 `.notice` 在——
 * `.notice.bad` 的规则挂在它身上，两张样式表里都有。
 */
function statusTone(host, tone) {
  host.classList.remove('good', 'warning', 'bad', 'info');
  host.classList.add('notice');
  if (tone) host.classList.add(tone);
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
  if (document.documentElement.classList.contains('app4-embedded') && !host.closest('details')) {
    let guide = host.querySelector(':scope > .care-guide');
    if (!guide) {
      guide = el('details','workspace-fold care-guide');
      guide.appendChild(el('summary',null,'记录来源与说明')); host.appendChild(guide);
    }
    host = guide;
  }
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
  let guide = host;
  if (blocks.length && document.documentElement.classList.contains('app4-embedded')) {
    guide = el('details', 'workspace-fold');
    guide.appendChild(el('summary', null, '记录说明'));
    host.appendChild(guide);
  }
  blocks.forEach(({head, items}) => futureBlock(guide, head, items));
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

/** 用药计划每次都问后端。
 *
 * 这里原先是一个模块级的 promise 记忆化（`let medicationPlans = null` 配
 * `if (!medicationPlans)`），**永不失效**：首屏那一次的响应会被这一页余下的生命里
 * 每一次重渲染重复使用。省下的是一个请求，代价是这一段变成第二个事实源——而重渲染
 * 恰恰是两个写按钮的 `after` 在做的事（这个文件开头第三条共同约定：「办完重新拉一次
 * 那一段」，理由写的是「前端自己算一遍就是第二个事实源」）。
 *
 * 看得见它的条件就是这个产品设计好的那条流程：用药计划的生命周期跨着两台设备——
 * 家属加（`POST /v4/medications`，进来时 `active=false`），只有老人本人能激活
 * （`POST /api/v1/medications/{id}/approve`；`v4_api.py` 那条规则写着「只有老人本人
 * 可以激活家属补充的用药计划」），他也可以「先不吃」，那会把那一行**删掉**。而 /care
 * 是子女一直开着的一页。实测走一遍（真后端 + 这个文件里的真函数、真按钮）：
 *
 *     后端真相   钙片 在吃｜降压药 在吃｜维生素 D 在吃（老人刚点头）｜鱼油 已删
 *     按下「记一次已吃」之后的屏幕
 *                钙片 在吃｜降压药 在吃｜维生素 D「已停」｜鱼油「已停」
 *                概览那一行：「在吃 2 种：钙片、降压药」
 *
 * 维生素 D 那张卡片上没有「记一次已吃」——他已经在吃了，而这一页不让她记；鱼油那张
 * 卡片对应的行数据库里已经没有。整条旅程里 `/v4/medications/{elder}` 只被问过一次。
 *
 * 它还记住**失败**：首屏读失败时那个被拒的 promise 会一直被交出去，而这一页除了这两个
 * 写按钮的 `after` 之外没有别的重试路径——网络好了也回不来，整段永远停在「取不到」。
 *
 * 「权威状态不缓存」这条规矩这个项目已经写在 service worker 那一层上了
 * （`test_no_authoritative_state_is_cached.py`：stale-while-revalidate 会先把上一次的
 * 响应交出去，于是老人删完自己的数据、页面告诉他一条都没删）。那道门只读 `sw.js`——
 * 同一件事在页内用一个模块级变量做，它一个字都不管。
 *
 * 省下的那个请求本来也几乎不存在：另一个消费者 `longTermMedication()` 只在「身体」
 * 那一段**空**的时候才会被调用（`loadHealth()` 的 `!events.length` 分支），有记录的
 * 账户上这个记忆化一次都没省下过东西。**演示家庭就是这种账户**——实测
 * `GET /v4/health/events/{elder}` 回 3 条（`empty` 和 `normal` 两个 demo state 都是
 * 3 条），于是那一段走的是非空分支，`longTermMedication()` 在演示路径上从不执行，
 * `medications()` 只有一个调用方。而并发读同一个端点两次在这一页是刻意的选择
 * ——「心情」和「趋势」就是，理由写在 `bootstrap()` 的注释里。
 *
 * 那个 `medicationPlans.catch(() => {})` 一起去掉：它存在的唯一理由是记忆化把 promise
 * 的**创建**和**await** 隔开了很久（「身体」要等 `/v4/health/events` 回来才 await 它）。
 * 现在两个消费者各自创建、各自当场 await（`loadMedications()` 在 try 里 await，
 * `longTermMedication()` 写的是 `.catch(() => [])`），没有无人接管的窗口。
 */
function medications() {
  return api(`/v4/medications/${state.elderId}`, {}, 'family');
}

/** 每份还在吃的方子「还能吃几天」的结论，键是计划 id。
 *
 * 天数和「要不要标红」**都由后端算**：阈值只在 `InventoryService` 里有一份
 * （不足 2 天 critical、不足 7 天 warning），响应里的 `whole_days_remaining` /
 * `should_highlight` / `message` 就是它判完的结果。
 *
 * 这一段原先自己用 JS 把库存除一遍（`daysLeft()`），还自己定了个「3 天以内才
 * 标红」。实测同一份计划（11 片、每天 2 片）：后端算出 5.5 天、判 warning、
 * 给家属发了通知，而屏幕上是普通灰字「按现在的吃法还够 5 天。」——家属手机响了，
 * 这边看不出任何异常。两个阈值各自都说得通，问题在于它们是两个。一个屏幕不该重新
 * 推导服务端已经判过的事。
 *
 * **只问还在吃的方子。** 已停的方子没有「现在的吃法」，而这个 GET 在后端判定库存
 * 不足时会给家属发一条补药通知——为一份没人在吃的药催家属去补，是凭空造一件事。
 *
 * 一份问不出来就在那一格记 `null`：一份问不到不该把整段变成一句错误，别的方子
 * 照样该显示。
 */
async function stockOf(plans) {
  const pairs = await Promise.all(
    plans.filter((plan) => plan.active).map((plan) =>
      api(`/v4/medications/${plan.id}/inventory`, {}, 'family')
        .then((forecast) => [plan.id, forecast], () => [plan.id, null])),
  );
  return new Map(pairs);
}

/** 库存那一行：标不标红读 `should_highlight`，说什么读 `message`。
 *
 * 这里一个数字都不算，也没有任何阈值。同一件事判两遍，迟早有一遍是另一个答案，
 * 而两边看起来都很正常——那正是这一行以前的毛病。
 *
 * 后端算不出来（计划里没有服药时间）时 `message` 说的是「算不出来」而不是
 * 「还够」，所以这里不需要再分一支：照印就是诚实的。
 */
function stockLine(forecast) {
  if (!forecast || !forecast.message) return null;
  return el('p', forecast.should_highlight ? 'notice warning' : 'meta', forecast.message);
}

/** 概览那一行：在吃什么、还够多久。
 *
 * 「已停」的计划不算进「在吃」——它们在细节那一段里带着「已停」的药丸列着，
 * 但概览问的是**现在**在吃什么。全都停了也要说出来，那和从来没登记过不是一回事。
 *
 * 多种药时说**最先断的那一份**，不报平均也不报总和：会先断的是剩得最少的那一种。
 * 排序用的是后端给的 `whole_days_remaining`，那句话也照抄后端的 `message`——
 * 这里只在几个已经算好的结论里挑一个，不自己算天数，也不自己定阈值。于是概览那一行
 * 和下面每张卡片说的是同一批结论，两处不可能给出两个不同的天数。
 */
function medicationDigest(plans, stock) {
  if (!plans.length) return '还没有登记在吃的药';
  const active = plans.filter((plan) => plan.active);
  if (!active.length) return `登记过 ${plans.length} 个用药计划，现在都已经停了`;
  const names = active.map((plan) => plan.display_name);
  const head = active.length === 1
    ? names[0]
    : `在吃 ${active.length} 种：${names.join('、')}`;
  const known = active
    .map((plan) => ({plan, forecast: stock.get(plan.id)}))
    .filter((row) => row.forecast
                     && typeof row.forecast.whole_days_remaining === 'number');
  if (!known.length) return head;
  known.sort((a, b) => a.forecast.whole_days_remaining - b.forecast.whole_days_remaining);
  const first = known[0];
  return active.length === 1
    ? `${head}｜${first.forecast.message}`
    : `${head}｜最先断的是${first.plan.display_name}，${first.forecast.message}`;
}

/** 记完一次服药之后要重拉的**两段**。
 *
 * 原先两个写按钮的 `after` 只有 `loadMedications`。而「今天这几次」那张表和
 * 「N 次，还差 M 次」来自 `loadDoses()` 打的 `/api/v1/medications`——
 * `loadDoses()` 全文件只在 `bootstrap()` 里被调用过一次。
 *
 * 后果是屏幕和自己的回执打架：实测写之前 `pendingCount=2 takenCount=1`、
 * 钙片 08:00「待服用」；按下「记一次已吃」→ 200；写之后后端是
 * `pendingCount=1 takenCount=2`、钙片「已服用」，而**那张表要到整页刷新才变**。
 * 家属看到的是「上面说记下了，下面还写着待服用」。
 *
 * 这不是缓存——`loadDoses()` 每次都真的问后端，缺的是这条重渲染路径。
 *
 * 代价说清：按一次多发一个 GET。那两段打的是**两个不同的端点**
 * （`/v4/medications/{elder}` 与 `/api/v1/medications`），省不掉。
 * 用 `Promise.all` 并发，不串起来等——这一页同一端点并发读两次已有先例
 * （「心情」和「趋势」），是刻意的。
 */
async function afterDoseWrite() {
  await Promise.all([loadMedications(), loadDoses()]);
}

async function loadMedications() {
  const host = byId('medBody');
  try {
    const plans = await medications();
    // 库存的结论逐份问后端拿。概览那一行和下面每张卡片读的是**同一批**结论，
    // 所以两处不可能说出两个不同的天数——它们以前各调一次 `daysLeft()`，
    // 那已经是同一个换算写在两处了。
    const stock = await stockOf(plans);
    overviewSay('ovMed', medicationDigest(plans, stock));
    if (!plans.length) {
      empty(host, document.documentElement.classList.contains('app4-embedded') ? '还没有用药计划。可以按医嘱添加。' : '还没有登记在吃的药。等医生开了方子，您或他都可以添上——'
        + '添上之后到点会提醒他，也会盯着还剩多少。');
      return;
    }
    host.replaceChildren();
    plans.forEach((plan) => {
      const card = el('section', 'care-item');
      const title = el('h3', 'care-item-head');
      title.append(
        el('span', null, plan.display_name),
        el('span', `pill ${plan.active ? 'good' : 'cancelled'}`, plan.active ? (document.documentElement.classList.contains('app4-embedded') ? '已启用' : '在吃') : document.documentElement.classList.contains('app4-embedded') ? '未启用' : '已停'),
      );
      card.appendChild(title);
      card.appendChild(el('p', null, `${plan.dose_text}｜每天 ${plan.times_local.join('、')}`));
      // 库存那一行。天数、阈值、话——三样都是后端给的，见 `stockLine`。
      // 已停的方子没有这一行：`stockOf` 不去问它们（理由写在那儿）。
      const stockRow = stockLine(stock.get(plan.id));
      if (stockRow) card.appendChild(stockRow);
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
            afterDoseWrite),
          actionButton('这次没吃', null,
            () => api(`/api/v1/medications/${plan.id}/skipped`,
                      {method: 'POST', headers: {'Content-Type': 'application/json'},
                       body: '{}'}, 'family'),
            afterDoseWrite),
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
//:
//: 这四个说法现在是**唯一**一套：家人端三（`family3.js` 的同名表，「身体」那一段）
//: 读的是同一个端点，此前 `medication` 在那边叫「用药」、`note` 叫「记录」。
//: 为什么以这一套为准写在那边的注释里，主要一条是：那边的兜底本身就是「记录」，
//: 于是 `note: '记录'` 让翻译层认出来和认不出来印出同一个字。
//: 改这里的措辞时那边要一起改——`test_the_same_event_reads_the_same_everywhere`
//: 会红。
const HEALTH_WORD = {
  checkup: '身体数据',
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
  const raw = String(event.event_at || event.created_at || '');
  if (/^\d{4}-\d{2}-\d{2}$/.test(raw)) return raw;
  const date = new Date(raw);
  return Number.isNaN(date.getTime()) ? '日期未知' : ymd(date);
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
        el('span', 'meta', healthDay({event_at: event.event_at, created_at: event.created_at})),
      );
      card.appendChild(title);
      if (event.title) card.appendChild(el('p', null, event.title));
      // Manual health entries store the measurement separately from their title.
      const reading = event.payload?.value;
      if (typeof reading === 'string' || typeof reading === 'number') {
        const unit = typeof event.payload.unit === 'string' ? event.payload.unit : '';
        card.appendChild(el('p', 'care-reading', `${reading}${unit ? ' ' + unit : ''}`));
      }
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
      host.appendChild(el('p', 'care-empty', document.documentElement.classList.contains('app4-embedded') ? '这两周还没有心情记录。' : '这两周没有需要记下来的情绪波动。'));
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
    host.appendChild(el('p', 'meta', document.documentElement.classList.contains('app4-embedded') ? '仅展示汇总，不用于医学诊断。' : report.privacy_guarantee));
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
    if (document.documentElement.classList.contains('app4-embedded')) {
      const summary = report.summary;
      const hero = el('section','journal-week');
      hero.append(el('strong',null,`${summary.event_count} 条记录`),el('p',null,summary.event_count ? (TREND_WORD[summary.trend] || '暂时无法比较') : '记录还不够，暂时无法比较。'));
      host.appendChild(hero);
      const counts = el('div','journal-counts');
      Object.entries(summary.label_counts || {}).forEach(([name,count])=>{
        const row=el('div','journal-count'); const bar=el('meter'); bar.min=0; bar.max=Math.max(summary.event_count,1); bar.value=count;
        bar.setAttribute('aria-label',`${EMOTION_WORD[name] || '其他'} ${count}次`);
        row.append(el('span',null,EMOTION_WORD[name] || '其他'),bar,el('span',null,`${count}次`)); counts.appendChild(row);
      });
      host.appendChild(counts);
      if(summary.safe_suggestions?.length) {
        const note=el('section','journal-suggestion'); note.appendChild(el('h3',null,'可以做的小事'));
        summary.safe_suggestions.forEach(text=>note.appendChild(el('p',null,text))); host.appendChild(note);
      }
      const more=el('details','workspace-fold'); more.appendChild(el('summary',null,'统计与隐私说明'));
      for(const [key,value] of Object.entries(summary)) {
        if(['event_count','trend','label_counts','safe_suggestions'].includes(key)) continue;
        more.appendChild(el('p','meta',`${WEEKLY_LABEL[key] || '其他统计'}：${weeklyValue(key,value)}`));
      }
      if(report.privacy_guarantee) more.appendChild(el('p','meta',report.privacy_guarantee));
      host.appendChild(more); return;
    }
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
        // 称呼和关系相同时不重复印。演示数据里这两位就是这样：这个产品
        // **不编人名**（elder.js 那段注释写着「与其编一个名字，不如说清有几位、
        // 各是什么关系」），所以 display_name 就是「女儿」「儿子」。
        // 照原样拼会印出「儿子（儿子）」。
        const parts = [person.display_name === person.relation
          ? person.display_name
          : `${person.display_name}（${person.relation}）`];
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
        document.documentElement.classList.contains('app4-embedded') ? '还没有亲友档案，可以添加一位。' : '还没有登记他身边的人。上面那三条设置定的是「什么时候该找人」，'
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
      document.documentElement.classList.contains('app4-embedded') ? '仅在必要时使用位置。定位不准时，不自动报警。' : '位置只在需要的时候看一眼，按最小必要留存。定位精度不够时不会自动报警——'
      + '一次误报会让他以后不敢再带手机出门。'));
  } catch (error) {
    failed(host, error);
    overviewSay('ovSafety', errorWords(error, '安全设置').text, true);
  }
}

/* ==========================================================================
   照护中心此前一处都碰不到的三条
   ..........................................................................
   后端这三组端点一直是齐的，而这一页（以及加载同一份 care.js 的 `/family2`）
   一条都不调：

       固定安排    GET,POST /api/v1/routines + /{id}/pause|resume
       就医安排    GET,POST /api/v1/appointments + /{id}/cancel
       今天几次药  GET      /api/v1/medications

   前两条是**能力**缺口。这一页能列出在吃什么药、能记一笔血压、能添一位亲友，
   却没有任何办法说「每天早上八点量血压」——想说这句话，此前唯一的走法是一天
   手工加一条提醒；也没有任何办法记下周五的复诊。

   第三条是**读数**缺口，而且它让一个已经存在的按钮变成盲按的：「记一次已吃」
   不带时间点，服务端取的是今天**最早一格还没记的**，可屏幕上从来没有出现过
   「今天有哪几格、哪几格已经记过」。都记过了会回 409，那句「今天降压药该吃的
   都记过了」是家属唯一能拿到的线索——而那时她已经按下去了。

   ## 三块都挂在**已有那一段的旁边**，不挂进那一段里

   `#todayBody` / `#medBody` / `#bodyBody` 的 loader 第一句都是 `replaceChildren()`。
   挂进去的东西会在下一次刷新时连同事件一起消失，而它看起来只是"没了"。
   基准取 `parentElement`：两版标记的外层不一样（`/care` 是 `.page-section`，
   `/family2` 是 `.care-detail`），写死任何一个选择器都会让另一版整块不出现。

   ## 类名一律复用这一页已有的那套积木

   `.care-block` `.care-item` `.care-form` `.care-field` `.care-actions` `.digest`
   ——它们在 `pages.css`（设计一）和 `family-v6.css`（设计二）里**都有规则**，
   触控高度也在那里定死（输入 48px，提交 56px）。新造一套类名的代价是确定的：
   `/family2` 只引一张样式表，新类名在那边一条规则都没有，出来是浏览器默认控件。
   ========================================================================== */

/** 在某一段旁边挂一小块，只挂一次。返回 `{box, sum, rows}`，挂不上返回 null。 */
function careCard(hostId, cls, title, where) {
  const host = byId(hostId);
  if (!host || !host.parentElement) return null;
  if (host.parentElement.querySelector(`.${cls}`)) return null;
  const box = el('section', `care-block ${cls}`);
  const head = el('h3', 'care-block-head');
  head.appendChild(el('span', null, title));
  const sum = el('span', 'meta', '正在读……');
  head.appendChild(sum);
  box.appendChild(head);
  const rows = el('div');
  box.appendChild(rows);
  host.parentElement.insertBefore(box, where === 'before' ? host : host.nextSibling);
  return {box, sum, rows};
}

/** 「加一件…」按钮 + 一张默认收起来的表单。返回那个开关按钮。
 *
 * 收起来是有理由的：这一页的第一件事是**读**——他今天怎么样。一张永远摊开的
 * 表单会把要读的东西整段推下去，而添一件固定安排是偶尔才做的事。
 */
function composer(host, word, form) {
  const row = actionRow();
  const open = el('button', 'secondary', word);
  open.type = 'button';
  row.appendChild(open);
  host.append(row, form);
  const paint = () => {
    open.textContent = form.hidden ? word : '先不加了';
  };
  open.addEventListener('click', () => {
    form.hidden = !form.hidden;
    paint();
    if (!form.hidden) {
      const first = form.querySelector('input');
      if (first) first.focus();
    }
  });
  // 办成之后要**收回去**，而且开关那个字也得跟着回来。
  // 少了这一步，加完一件之后表单还摊着、按钮还写着「先不加了」——
  // 看起来像是没提交成功，于是人会再按一次。
  return {open, close: () => { form.hidden = true; paint(); }};
}

/** 一个只认几个中文词的输入框：可见标签 + 候选清单。
 *
 * 用候选而不是下拉：`<select>` 在 `family-v6.css` 里**一条规则都没有**，
 * 那一版会出来一个浏览器默认下拉，高度约 20px——远在 48px 的触控下限以下，
 * 而这一页所有输入的 48px 是靠 `.care-field input` 给的。
 * 打错字不会静默走掉：提交前逐个字比对，对不上就说出来。
 */
function pickField(id, label, options, initial) {
  const {wrap, input} = field(id, label, 'text',
                              {list: `${id}List`, autocomplete: 'off', maxlength: '6'});
  const list = el('datalist');
  list.id = `${id}List`;
  options.forEach((word) => {
    const option = el('option');
    option.value = word;
    list.appendChild(option);
  });
  wrap.appendChild(list);
  if (initial) input.value = initial;
  return {wrap, input};
}

/* ---- 固定安排 -------------------------------------------------------------
 *
 * ## 它和「待办」不是一回事
 *
 * 提醒是一次性的一条；例程是**生成器**：`materialize_routines` 为每一次发生
 * 真的插一条提醒，所以家人端那张日历会自动认它们。
 *
 * ## 建完必须当场排期，而回执要把排了几条说出来
 *
 * 服务端建完顺手排最近一周。排了 0 条的时候它自己会改口（「记下了：…。
 * 最近一周还没有要排的。」），语气也必须跟着改——不然「好，每天 08:30 提醒他
 * 量血压」和「记下了但什么都没排」在屏幕上是同一种绿色。
 *
 * ## 摘要自己算，不转发服务端那句 `message`
 *
 * `GET /api/v1/routines` 的 `message` 只数**在跑**的那些：建一件再把它暂停，
 * 回的是 `count: 1` 配「您还没有固定安排。…」。照抄就会在同一屏上同时出现
 * 「您还没有固定安排」和一行写着「量血压」的记录。这条缺陷记在报告里，
 * 这一侧不把它搬上屏幕。
 */

//: 重复方式。三个词就是服务端认的那三个（它自己的映射表里写着 每天/每周/每月），
//: 不另造一套说法——造一套，两边就得各改一次，而漏改的那一边会静默退回「每天」。
const REPEAT_WORDS = ['每天', '每周', '每月'];
const ROUTINE_KINDS = ['生活', '用药', '就医', '缴费', '社交'];

/** 「星期几」按服务端的规矩：0 是周一。
 *
 * `Date.getDay()` 里 0 是**周日**——差一位。直接把 `getDay()` 递过去，
 * 「每周五」会被排成「每周六」，而两边都不会报错，只是提醒晚一天。
 */
function backendWeekday(when) {
  return (when.getDay() + 6) % 7;
}

let routineCard = null;

function mountRoutines() {
  const card = careCard('todayBody', 'care-routines', '固定安排', 'after');
  if (!card) return;

  const form = el('form', 'care-form');
  form.hidden = true;
  form.noValidate = true;                 // 校验话术自己说，浏览器那句是英文的
  form.appendChild(el('h3', 'care-block-head', '加一件固定安排'));
  const what = field('rTitle', '这件事叫什么', 'text',
                     {maxlength: '24', autocomplete: 'off'});
  const when = field('rTime', '几点', 'time');
  const repeat = pickField('rRepeat', '多久一次（每天 / 每周 / 每月）',
                           REPEAT_WORDS, '每天');
  const from = field('rFrom', '从哪一天算起（选了每周或每月才用得上）', 'date');
  const kind = pickField('rKind', '归到哪一类（生活 / 用药 / 就医 / 缴费 / 社交）',
                         ROUTINE_KINDS, '生活');
  form.append(what.wrap, when.wrap, repeat.wrap, from.wrap, kind.wrap);

  const submit = el('button', null, '加上');
  submit.type = 'submit';
  form.appendChild(actionRow(submit));
  form.appendChild(el('p', 'meta',
    '到点提醒的是他，不是您——这一条加上之后会直接排到他那一端。'
    + '每月只能选到 28 号：29 号之后不是每个月都有，排到二月会静默少一次，'
    + '而他只会看到「这个月怎么没提醒我」。'));

  const fold = composer(card.box, '加一件固定安排', form);

  form.addEventListener('submit', (e) => {
    e.preventDefault();
    const title = what.input.value.trim();
    const time = when.input.value.trim();
    const how = repeat.input.value.trim();
    if (!title) {
      notify('还没写这件事叫什么。比如「量血压」。', 'warning');
      what.input.focus();
      return;
    }
    if (!time) {
      notify('还没选几点。', 'warning');
      when.input.focus();
      return;
    }
    if (!REPEAT_WORDS.includes(how)) {
      notify('多久一次只能是「每天」「每周」或者「每月」。', 'warning');
      repeat.input.focus();
      return;
    }
    const payload = {title, time, repeat: how};
    if (ROUTINE_KINDS.includes(kind.input.value.trim())) {
      payload.category = kind.input.value.trim();
    }
    if (how !== '每天') {
      // 星期几和几号都从这一天推出来，不再让人填第二遍：
      // 「每周五」和「9 月 5 日是周五」是同一件事，让人分两处说，
      // 两处对不上的时候没有任何东西会发现。
      if (!from.input.value) {
        notify(`选了「${how}」就要说清从哪一天算起。`, 'warning');
        from.input.focus();
        return;
      }
      const day = new Date(`${from.input.value}T00:00:00`);
      if (Number.isNaN(day.getTime())) {
        notify('这个日期看不懂，请重新选一次。', 'warning');
        from.input.focus();
        return;
      }
      if (how === '每周') payload.weekdays = [backendWeekday(day)];
      else {
        if (day.getDate() > 28) {
          notify('每月只能排到 28 号。29 号之后不是每个月都有，'
                 + '排到二月会少一次，而他只会看到这个月没被提醒。', 'warning');
          from.input.focus();
          return;
        }
        payload.dayOfMonth = day.getDate();
      }
    }
    window.YouHuo.once(submit, async () => {
      try {
        const data = await api('/api/v1/routines', {
          method: 'POST', headers: {'Content-Type': 'application/json'},
          body: JSON.stringify(payload),
        }, 'family');
        form.reset();
        repeat.input.value = '每天';
        kind.input.value = '生活';
        fold.close();
        // 语气跟服务端走，**话不跟**。
        //
        // `/api/v1` 是**老人端**的门面，它写的每一句都是对他说的第二人称：
        // 这一条回的是「好，每天08:30提醒您量血压」。同一句话摆到家人端上，
        // 说的就变成「会提醒**您**（女儿）」——而到点被叫的是他。
        // 一句主语错了的成功回执，比没有回执糟：她会以为自己该在早上八点半守着。
        //
        // 一条都没排上也**不是**好消息，所以 `scheduled` 决定语气，也决定这句话
        // 说什么——不然「排了七次」和「一次都没排」在屏幕上是同一种绿色。
        notify(data.scheduled
          ? `记下了「${title}」，最近一周已经给他排了 ${data.scheduled} 次提醒。`
          : `记下了「${title}」，不过最近一周没有要排的，这几天他那边不会有提醒。`,
          data.scheduled ? window.YouHuo.toneOf(data) : 'warning');
        await loadRoutines();
      } catch (error) {
        notify(errorWords(error, '这件固定安排').text, 'warning');
      }
    });
  });
  routineCard = card;
}

async function loadRoutines() {
  if (!routineCard) return;
  const {sum, rows} = routineCard;
  let data;
  try {
    data = await api('/api/v1/routines', {}, 'family');
  } catch (error) {
    sum.className = 'meta bad';
    sum.textContent = errorWords(error, '固定安排').text;
    rows.replaceChildren();
    return;
  }
  const items = data.items || [];
  const running = items.filter((r) => r.active);
  sum.className = 'meta';
  sum.textContent = items.length
    ? `${running.length} 件在提醒`
      + (items.length > running.length ? `，${items.length - running.length} 件已暂停` : '')
    : '还没有';
  rows.replaceChildren();
  if (!items.length) {
    rows.appendChild(el('p', 'care-empty',
      '还没有固定安排。像「每天早上八点量血压」这种，记在这里之后，'
      + '每一次该发生的时候都会自动排一条提醒给他，不用一天添一遍。'));
    return;
  }
  items.forEach((r) => {
    const item = el('section', 'care-item');
    const head = el('h3', 'care-item-head');
    head.append(
      el('span', null, `${r.repeatText} ${r.time} · ${r.title}`),
      // `status` 服务端给的就是中文（进行中 / 已暂停），不再翻一遍——
      // 翻第二遍就是第二份词表，两份迟早分叉。
      el('span', `pill ${r.active ? 'good' : 'cancelled'}`, r.status),
    );
    item.appendChild(head);
    item.appendChild(el('p', 'meta',
      [r.category, r.nextText ? `下次 ${r.nextText}` : '最近一周没有要排的']
        .filter(Boolean).join('｜')));
    // 不走 `actionButton()`：那个助手把服务端的 `message` 原样印出来，而这一条
    // 回的是「好，X 继续按原来的安排提醒您」——老人端门面的第二人称。
    // 语气仍然由服务端给（`toneOf`），只有主语换成对的那一个。
    const act = el('button', r.active ? 'secondary' : null, r.active ? '先不提醒' : '继续提醒');
    act.type = 'button';
    act.addEventListener('click', () => window.YouHuo.once(act, async () => {
      try {
        const data = await api(
          `/api/v1/routines/${encodeURIComponent(r.id)}/${r.active ? 'pause' : 'resume'}`,
          {method: 'POST', headers: {'Content-Type': 'application/json'}, body: '{}'}, 'family');
        notify(r.active
          ? `${r.title}先不提醒了。已经排出去的那几条还在他的待办里。`
          : `${r.title}继续按原来的安排提醒他。`, window.YouHuo.toneOf(data));
        await loadRoutines();
      } catch (error) {
        notify(errorWords(error, '这件固定安排').text, 'warning');
      }
    }));
    item.appendChild(actionRow(act));
    rows.appendChild(item);
  });
  // 暂停**不撤**已经排出去的提醒。服务端那句回执把这件事说了，但只有按过的人看得到；
  // 列表下面常驻一行，是因为「暂停了为什么今天还提醒」这个问题会在按完很久之后才被问。
  rows.appendChild(el('p', 'meta',
    '先不提醒只是停下以后的那些。已经排出去的提醒还在他的待办里，'
    + '要撤那几条，得到家人端的待办里一条一条改。'));
}

/* ---- 就医安排 -------------------------------------------------------------
 *
 * 放在「身体」这一段：那一段本来就在列体检与就诊记录，「已经去过的」和
 * 「接下来要去的」是同一件事的两头。
 *
 * ## 取消是撤不回来的，所以是两步
 *
 * 第二个按钮**一开始不在 DOM 里**——不是 disabled，也不是 hidden。
 * 一个看得见的「确认取消」会让人以为「点两下就没了」，而这两下之间那一句
 * 「要取消的是哪一次」才是这道确认的全部内容。
 *
 * ## 取消必须连提醒一起撤
 *
 * 记一次就医的时候服务端**同时**建了一条到点提醒（不建的话没有任何东西会叫他）。
 * 只取消一半，他到点还是会被叫去一个已经取消了的门诊——那比不提醒更糟。
 */

let visitCard = null;

function mountVisits() {
  const card = careCard('bodyBody', 'care-visits', '就医安排', 'after');
  if (!card) return;

  const form = el('form', 'care-form');
  form.hidden = true;
  form.noValidate = true;
  form.appendChild(el('h3', 'care-block-head', '记一次就医安排'));
  const hospital = field('vHospital', '去哪家医院', 'text',
                         {maxlength: '24', autocomplete: 'off'});
  const dept = field('vDept', '哪个科（可以不填）', 'text',
                     {maxlength: '16', autocomplete: 'off'});
  const doctor = field('vDoctor', '哪位医生（可以不填）', 'text',
                       {maxlength: '16', autocomplete: 'off'});
  const day = field('vDate', '哪一天', 'date');
  const at = field('vTime', '几点（不填就按上午九点）', 'time');
  form.append(hospital.wrap, dept.wrap, doctor.wrap, day.wrap, at.wrap);

  const submit = el('button', null, '记下');
  submit.type = 'submit';
  form.appendChild(actionRow(submit));
  form.appendChild(el('p', 'meta',
    '记下之后会同时排一条到点提醒，他那一端也看得到。'));

  const fold = composer(card.box, '记一次就医安排', form);

  form.addEventListener('submit', (e) => {
    e.preventDefault();
    const where = hospital.input.value.trim();
    const date = day.input.value.trim();
    if (!where) {
      notify('还没写去哪家医院。', 'warning');
      hospital.input.focus();
      return;
    }
    if (!date) {
      notify('还没选哪一天。', 'warning');
      day.input.focus();
      return;
    }
    // 时刻先读出来。`form.reset()` 之后再去读输入框拿到的是空串，
    // 于是回执会写成「去市第一医院  」——一句缺了时间的成功回执。
    const clock = at.input.value.trim() || '09:00';
    window.YouHuo.once(submit, async () => {
      try {
        const data = await api('/api/v1/appointments', {
          method: 'POST', headers: {'Content-Type': 'application/json'},
          body: JSON.stringify({
            hospital: where, date,
            department: dept.input.value.trim(),
            doctor: doctor.input.value.trim(),
            time: at.input.value.trim(),
          }),
        }, 'family');
        form.reset();
        fold.close();
        // `reminderId` 是 null 表示**只记下了安排，到点没有任何东西会叫他**。
        // 服务端这时只是少掉「到点我会提醒您」那半句，而少一句话不等于说清楚了：
        // 一条只记在册子上的复诊，和一条会响的复诊，对老人是两件事。
        //
        // 成功那一支也不照抄它的原话，理由和固定安排那一处一样：`/api/v1` 是
        // 老人端门面，「到点我会提醒您」里的「您」是他，印在家人端上就成了她。
        notify(data.reminderId
          ? `记好了，${date} ${clock} 去${where}。到点会提醒他。`
          : `记好了，${date} 去${where}。这一次没能排上提醒，到点不会有人叫他。`,
          data.reminderId ? window.YouHuo.toneOf(data) : 'warning');
        await loadVisits();
      } catch (error) {
        notify(errorWords(error, '这次就医安排').text, 'warning');
      }
    });
  });
  visitCard = card;
}

/** 「取消这一次」——它自己**不取消**，只说清楚要取消的是哪一次。
 *
 * 真正那一下是它按下去之后另外长出来的按钮，在此之前那个按钮不在 DOM 里。
 */
function visitCancel(item, visit) {
  const ask = el('button', 'danger', '取消这一次');
  ask.type = 'button';
  ask.addEventListener('click', () => {
    if (item.querySelector('.care-actions + .care-actions')) return;   // 已经问过了
    notify(`要取消的是 ${visit.date} ${visit.time} ${visit.hospital}${visit.department || ''}`
           + '那一次。取消之后到点那条提醒也会一起撤掉，这一步撤不回来。', 'warning');
    const row = actionRow();
    const sure = el('button', 'danger', '确认取消，连提醒一起撤');
    sure.type = 'button';
    const keep = el('button', 'secondary', '先不取消');
    keep.type = 'button';
    keep.addEventListener('click', () => {
      row.remove();
      ask.hidden = false;
      ask.focus();
      notify('这一次留着，没有改动。', 'good');
    });
    sure.addEventListener('click', () => window.YouHuo.once(sure, async () => {
      try {
        const data = await api(`/api/v1/appointments/${encodeURIComponent(visit.id)}/cancel`,
                               {method: 'POST',
                                headers: {'Content-Type': 'application/json'}, body: '{}'},
                               'family');
        notify(data.message, window.YouHuo.toneOf(data));
        await loadVisits();
      } catch (error) {
        // 已经取消过的走 409（「这一次已经取消过了。」）。
        notify(errorWords(error, '这一次就医').text, 'warning');
      }
    }));
    row.append(sure, keep);
    ask.hidden = true;
    item.appendChild(row);
    sure.focus();
  });
  return ask;
}

async function loadVisits() {
  if (!visitCard) return;
  const {sum, rows} = visitCard;
  let data;
  try {
    data = await api('/api/v1/appointments', {}, 'family');
  } catch (error) {
    sum.className = 'meta bad';
    sum.textContent = errorWords(error, '就医安排').text;
    rows.replaceChildren();
    return;
  }
  const items = data.items || [];
  // `status` 服务端给的就是中文（已预约 / 已取消 / 已完成）。
  const live = items.filter((v) => v.status === '已预约');
  sum.className = 'meta';
  sum.textContent = items.length
    ? `${live.length} 次还没去`
      + (items.length > live.length ? `，另有 ${items.length - live.length} 次已结束` : '')
    : '还没有';
  rows.replaceChildren();
  if (!items.length) {
    rows.appendChild(el('p', 'care-empty',
      document.documentElement.classList.contains('app4-embedded') ? '还没有就医安排。添加后，到点提醒本人。' : '还没有记过就医安排。记一次之后，到点会有一条提醒直接发给他，'
      + '不用您那天再打一个电话去催。'));
    return;
  }
  items.forEach((v) => {
    const item = el('section', 'care-item');
    const head = el('h3', 'care-item-head');
    head.append(
      el('span', null, `${v.date} ${v.time} · ${v.hospital}${v.department || ''}`),
      el('span', `pill ${v.status === '已预约' ? 'good' : 'cancelled'}`, v.status),
    );
    item.appendChild(head);
    if (v.doctor) item.appendChild(el('p', 'meta', v.doctor));
    if (v.status === '已预约') item.appendChild(actionRow(visitCancel(item, v)));
    rows.appendChild(item);
  });
}

/* ---- 今天该吃的那几次 -----------------------------------------------------
 *
 * 这一块补的是「记一次已吃」那个按钮**看不见的另一半**。
 *
 * 服务端不带时间点时取的是今天最早一格还没记的，所以家属按下去之前应该先看到
 * 今天有哪几格、哪几格已经记过。少了这一块，那个按钮是盲按的，而唯一的反馈是
 * 一句 409。
 *
 * **不转发服务端那句 `summary`。** 那一层是老人端的门面，它写的是
 * 「您现在没有登记在册的用药计划。要登记的话，可以让家人在家属端添加。」——
 * 把这句话摆在家属端上，是让她去找一个她已经在看着的界面。计数
 * （`plannedCount` / `takenCount` / `pendingCount`）是数据，这一侧自己组句。
 */

let doseCard = null;

function mountDoses() {
  doseCard = careCard('medBody', 'care-doses', '今天这几次', 'before');
}

async function loadDoses() {
  if (!doseCard) return;
  const {sum, rows} = doseCard;
  let data;
  try {
    data = await api('/api/v1/medications', {}, 'family');
  } catch (error) {
    sum.className = 'meta bad';
    sum.textContent = errorWords(error, '今天的服药记录').text;
    rows.replaceChildren();
    return;
  }
  const doses = data.doses || [];
  sum.className = 'meta';
  sum.textContent = doses.length
    ? `${doses.length} 次，还差 ${data.pendingCount} 次`
    : '今天没有要吃的';
  rows.replaceChildren();
  if (!doses.length) {
    rows.appendChild(el('p', 'care-empty',
      document.documentElement.classList.contains('app4-embedded') ? '今天没有待服用的药。新计划需本人确认。' : '今天没有要吃的药。下面列的是他登记在册的用药计划——'
      + '还没有他本人确认过的计划不会排到今天来。'));
    return;
  }
  const table = el('div', 'digest');
  doses.forEach((dose) => {
    const row = el('div', 'digest-row');
    row.append(el('strong', null, dose.time),
               el('div', null, `${dose.name}｜${dose.status}`));
    table.appendChild(row);
  });
  rows.appendChild(table);
  // 「查不到」不等于「没吃」。这一句是这一段的立场，不是免责声明：
  // 一份把「没有记录」读成「他没吃」的界面，会让家属打一个不该打的电话。
  rows.appendChild(el('p', 'meta',
    '这里只看得到记录。他吃了但没记，这一格照样是「待服用」——'
    + '下面每一份还在吃的药都可以替他补记一次。'));
  if (data.stockWarning) rows.appendChild(el('p', 'notice warning', data.stockWarning));
}

/* ========================================================================== */

function mountMedicationComposer() {
  if (!document.documentElement.classList.contains('app4-embedded') || byId('addMedication')) return;
  const note = el('details','workspace-fold workspace-add');
  note.appendChild(el('summary',null,'添加用药计划'));
  const form = el('form','care-form'); form.id = 'addMedication'; form.noValidate = true;
  const name = field('medName','药品名称','text',{maxlength:'120',required:''});
  const dose = field('medDose','医嘱用量','text',{placeholder:'按处方填写，如每次1片',maxlength:'120',required:''});
  const times = field('medTimes','每天服用时间','text',{placeholder:'如 08:00，20:00',required:''});
  const start = field('medStart','开始日期','date',{required:''});
  const count = field('medUnits','每次消耗数量（片、袋或支）','number',{min:'0.01',max:'1000',step:'any',required:''});
  const stock = field('medStock','当前剩余数量（同一单位）','number',{min:'0',max:'100000',step:'any',required:''});
  const end = field('medEnd','结束日期（选填）','date');
  form.append(name.wrap,dose.wrap,times.wrap,start.wrap,count.wrap,stock.wrap,end.wrap);
  form.appendChild(el('p','meta','请照医嘱填写。提交后由老人核对确认，才启用提醒。'));
  const status = el('p','notice'); status.hidden = true; status.setAttribute('role','status');
  const submit = el('button','contact-primary','提交给老人确认'); submit.type='submit';
  form.append(status,submit); note.appendChild(form); byId('medBody').before(note);
  form.addEventListener('submit', event => {
    event.preventDefault();
    const schedules=[...new Set(times.input.value.trim().split(/[，,、\s]+/).filter(Boolean))];
    const units=Number(count.input.value), remaining=Number(stock.input.value);
    const error = !name.input.value.trim() || !dose.input.value.trim() ? '请填写药品名称和医嘱用量。'
      : !schedules.length || schedules.length>8 || schedules.some(t=>!/^([01]\d|2[0-3]):[0-5]\d$/.test(t)) ? '时间请写成08:00，每天最多8次，用逗号分开。'
      : !start.input.value || (end.input.value && end.input.value<start.input.value) ? '请检查开始和结束日期。'
      : !count.input.value || !stock.input.value || !Number.isFinite(units) || units<=0 || units>1000 || !Number.isFinite(remaining) || remaining<0 || remaining>100000 ? '请检查每次消耗数量和当前剩余数量。' : '';
    if(error){ status.hidden=false; status.className='notice warning'; status.textContent=error; return; }
    window.YouHuo.once(submit,async()=>{
      try {
        await api('/v4/medications',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({
          elder_id:state.elderId,display_name:name.input.value.trim(),normalized_name:name.input.value.trim(),
          dose_text:dose.input.value.trim(),times_local:schedules,start_date:start.input.value,
          end_date:end.input.value || null,units_per_dose:units,stock_units:remaining,
        })},'family');
        form.reset(); status.hidden=false; status.className='notice good'; status.textContent='已提交，等待老人核对确认。';
        await loadMedications();
      } catch(error) { status.hidden=false; status.className='notice warning'; status.textContent=errorWords(error).text; }
    });
  });
}

async function bootstrap() {
  const appView = document.documentElement.classList.contains('app4-embedded') ? new URLSearchParams(location.search).get('view') : null;
  if (appView && ['reminders','history'].includes(appView)) return;
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
    // 颜色也要跟着换。这一行原先只换字：静态类是 `notice good`，于是这句
    // 「照护档案暂时看不了」印在一条绿色成功框里——一次失败被讲成了一次成功。
    statusTone(status, 'bad');
    return;
  }
  // 三块新的先**挂**再**读**，而且挂在登录之后。
  //
  // 挂在登录之前也能画出壳，但那一刻按下「加一件固定安排」会打一个没有令牌的
  // 请求——401，屏幕上是一句「这一步没成」，而真正的原因是页面还没登录完。
  // 挂和读分开则是另一回事：`loadRoutines()` 每次办完事都会再跑一遍，
  // 它不该每次都重建一遍表单（重建会把正在输入的字和焦点一起打掉）。
  mountRoutines();
  mountVisits();
  mountDoses();
  mountMedicationComposer();

  // 九段并发。一段失败只让那一段说话，其余照常显示——这一页最不该有的性质
  // 就是"一个接口慢了，整页停在正在加载"。
  //
  // 第六段是「趋势」，从 /family 搬来。它和「心情」读同一个端点（不同窗口），
  // 并发发两个请求是刻意的：合成一次会让两格互相拖累，而这一页的原则正是
  // 一段一段独立。后三段是这一轮补上的固定安排、就医安排和今天的服药记录。
  const loaders = {med:[loadMedications,loadDoses], body:[loadHealth,loadVisits],
    mood:[loadMood], safety:[loadSafety], trend:[loadWeekly], today:[loadToday,loadRoutines]};
  const selected = loaders[appView] || [loadToday,loadMedications,loadHealth,loadMood,loadSafety,loadWeekly,loadRoutines,loadVisits,loadDoses];
  await Promise.all(selected.map(load => load()));
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

bootstrap().finally(() => { document.documentElement.dataset.businessReadyCare = 'true'; document.dispatchEvent(new CustomEvent('app4:business-ready', {detail:'care'})); });
