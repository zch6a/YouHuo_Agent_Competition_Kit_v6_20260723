/* 家人端设计三（网页端 `/family3`）的接线。
 *
 * 这一页把**家人端**和**照护中心**装在同一个文档里：`#familyView` / `#careView`
 * 顶部切换，照护那边再分七个子面板。所以它一个人对应现有的 `/family` + `/care`
 * 两页，接的也是那两页用的同一批端点。
 *
 * ## 交付包里有三处「只演不做」，必须先摘掉
 *
 *   script-01.js  `states` 是一张写死的表。点「待办」「我的」会把主舞台改成
 *                 「燃气费缴纳…金额 ¥86.50」这类**编造的内容**。
 *   script-06.js  今日待办 / 最近记录是一份纯前端内存 `STORE`：`addItem` 只往
 *                 数组里 push，`removeItem` 只从数组里删，**都不出浏览器**。
 *                 家人在这里加一条提醒，老人端永远看不到。
 *   .primary-action  「查看并确认这件事」没有任何监听，按下去什么都不发生。
 *
 * 前两处已经处理：`script-06.js` 加了一行 `window.YouHuoFlow` 出口（行为没改），
 * `states` 那一批监听在这里用 `cloneNode` 摘掉再接。
 *
 * ## 审批是两步，不是一步
 *
 * 本项目的 P0：**渲染一张回执绝不许创建、推进、批准、执行、重试或改动一笔事务。**
 * 所以「查看并确认这件事」只**读**——把这一笔的摘要和金额摊开；真正的接力确认
 * 是它下面单独长出来的那个按钮。一次点击直接把钱付掉，正是这条约束要防的。
 */
(function () {
  'use strict';

  const YH = window.YouHuo;
  if (!YH) return;
  const {api, once, errorWords} = YH;

  const $ = (sel, root) => (root || document).querySelector(sel);
  const $$ = (sel, root) => [...(root || document).querySelectorAll(sel)];
  const FAMILY = 'family';           // 这一页所有请求都以家人身份发出

  let ELDER_ID = 'elder-demo';
  let notice = null;

  /* 提醒的状态词。**照抄 `family.js` 的 `REMINDER_STEP`**，一个字不改。
   *
   * 不能用 `common.js` 的 `statusWord()`：那张表是**任务**状态
   * （awaiting_family_approval / executing / …），提醒是另一套
   * （scheduled / notified / acknowledged / …）。第一版拿它翻提醒，
   * 于是三条待办在屏幕上全写着「还在办」——认不出来时的兜底文案，
   * 而它看起来完全像一个正常的状态。实测截图上三条一模一样。
   *
   * `test_family_design3.py` 有一道判据钉住这张表和 `family.js` 不许分叉。 */
  const REMINDER_STEP = {
    scheduled: '待处理',
    notified: '待确认',
    acknowledged: '老人已知道',
    completed: '已完成',
    escalated: '超时未完成',
    cancelled: '已取消',
  };
  const reminderWord = (s) => REMINDER_STEP[String(s || '')] || '待处理';

  /* ---- 说话的地方 ----------------------------------------------------------
   *
   * 这一页原先没有任何位置能报「刚才那一下成了没有」。放在主舞台的动作条上面，
   * 那是按钮所在的位置。 */
  function ensureNotice() {
    if (notice && notice.isConnected) return notice;
    const host = $('#familyMain .action-band') || $('#familyMain');
    if (!host) return null;
    notice = document.createElement('p');
    notice.id = 'f3Notice';
    notice.className = 'f3-notice';
    notice.setAttribute('role', 'status');
    notice.setAttribute('aria-live', 'polite');
    host.insertAdjacentElement('beforebegin', notice);
    return notice;
  }
  function say(text, tone) {
    const el = ensureNotice();
    if (!el) return;
    el.textContent = text || '';
    el.dataset.tone = tone || 'good';
  }
  const trouble = (e, what) => say(errorWords(e, what).text, 'bad');

  const text = (el, value) => { if (el) el.textContent = value; };
  const pad = (n) => String(n).padStart(2, '0');

  /** 把一行标题收进一行——**只在真的会换行时收，能放下就一个像素不动**。
   *
   * 为什么需要它：`.identity-island` 是 `position:absolute; height:23vh` 的
   * 固定高度盒子，而 `.companion-note` 固定在 `top:31vh`。标题排到第二行，
   * 岛内跟在它后面的「优活 / 无忧伴」就溢出到陪伴区上面。
   *
   * 实测 1440×900（量的是 boundingRect 相交）：
   *     交付包原样  叠压 无        它的占位标题「今天整体平稳」是 6 个字
   *     接线之后    叠压 mode×note  真数据「今天还没有记录」是 7 个字
   * 内容宽度 292px ÷（46px + .06em 字距）= 正好 6 个字。
   *
   * 三条路里选了这条：截断真数据是撒谎；整体调小字号会把短词也一起缩掉
   * （这一版的标题就是靠这个字号立住的）；只在溢出时按比例收，短词照旧 46px。
   * 下限 30px：再小就不是这一版的标题了，那时宁可让它换行，也不要一行蚂蚁字。
   */
  function fitOneLine(el, floorPx) {
    if (!el) return;
    el.style.removeProperty('font-size');
    const line = parseFloat(getComputedStyle(el).lineHeight) || 0;
    if (!line || el.scrollHeight <= line + 2) return;      // 本来就放得下
    const base = parseFloat(getComputedStyle(el).fontSize) || 46;
    for (let size = base - 2; size >= (floorPx || 30); size -= 2) {
      el.style.setProperty('font-size', size + 'px', 'important');
      if (el.scrollHeight <= line + 2) return;
    }
  }

  function stamp(d) {
    const week = '日一二三四五六'[d.getDay()];
    return `${d.getFullYear()}年${pad(d.getMonth() + 1)}月${pad(d.getDate())}日 `
         + `周${week} · ${pad(d.getHours())}:${pad(d.getMinutes())}`;
  }
  function greeting() {
    const h = new Date().getHours();
    if (h < 6) return '夜里好';
    if (h < 11) return '早上好';
    if (h < 13) return '中午好';
    if (h < 18) return '下午好';
    return '晚上好';
  }
  const hhmm = (iso) => {
    if (!iso) return '';
    const d = new Date(iso);
    return Number.isNaN(d.getTime()) ? '' : `${pad(d.getHours())}:${pad(d.getMinutes())}`;
  };

  /** 摘掉交付包绑在这个元素上的匿名监听，返回替换后的新节点。 */
  function strip(el) {
    if (!el) return null;
    const fresh = el.cloneNode(true);
    el.replaceWith(fresh);
    // `script-01.js` 给每个 `.clickable` 绑了按下去的动效，克隆之后要补回来，
    // 否则这些按钮会比旁边的少一点反馈。
    if (fresh.classList.contains('clickable')) {
      fresh.addEventListener('pointerdown', () => {
        fresh.classList.remove('pressed');
        void fresh.offsetWidth;
        fresh.classList.add('pressed');
      });
      fresh.addEventListener('animationend', () => fresh.classList.remove('pressed'));
    }
    return fresh;
  }

  /* ---- 家人端 · 头部与今日结论 ------------------------------------------- */

  let dailyReport = null;

  async function loadHeader() {
    const view = $('#familyView');
    text($('.identity-island p', view), stamp(new Date()));
    // 「最后更新 17:25」是写死的。这一页每次读数据都会动，让它说实话。
    text($('#familyMain .mini'),
         `最后更新 ${pad(new Date().getHours())}:${pad(new Date().getMinutes())}`);

    try {
      const me = await api('/api/v1/profile', {}, FAMILY);
      text($('.identity-island .hello', view), `${greeting()} · ${me.name}`);
    } catch (e) { trouble(e, '老人的档案'); }

    /* 日报走 `/api/v1/daily-report`，**不是** `/v7/daily-report/{id}`。
     *
     * 第一版用的是 v7 那个，字段名写成了 `today_word` / `familyWillSee`
     * ——v7 给的是 `headline` / `suggested_for_family`，**这两个名字都不存在**。
     * 于是每一处都落到我写的 `|| '今天和平常差不多'` 兜底上，而那句话读起来
     * 和真数据一模一样：屏幕上看不出任何异样，实际上一个字都不是后端给的。
     *
     * 门面这一份的字段本来就是中文语义（`todayWord` / `channels` / `errands`），
     * 而且 `_elder_of(ctx)` 会把家人令牌解析到她的老人身上——实测可用。 */
    try {
      dailyReport = await api('/api/v1/daily-report', {}, FAMILY);
      const head = $('.identity-island h1', view);
      text(head, dailyReport.todayWord);
      fitOneLine(head, 30);
      /* 陪伴区那两行**必须短**。
       *
       * 第一版把 `message` 放进 strong、把 `errands.lines` 三条拼进 span，
       * 实测（1440×900，量的是 boundingRect 的相交）：
       *
       *     交付包原样   叠压 无
       *     接线之后     叠压 mode × note、note × flow
       *
       * 也就是说这一处叠压是**我压出来的**，不是这一版本来就有的
       * （1280×800 那一档才是它自己的问题，原样和接线后一模一样）。
       * 那三条待办在主舞台和照护面板里都有地方放，这里只留一句。 */
      const note = $('.companion-note', view);
      text($('strong', note), dailyReport.todayWord);
      text($('span', note), dailyReport.familyWillSee || dailyReport.message);
    } catch (e) {
      // 日报取不到不该让整页停住：它是一句概括，不是这一页的主干。
      // 但**必须说出来**，不能留一句读起来像真的的兜底。
      text($('.identity-island h1', view), '今天的概括暂时取不到');
      text($('.companion-note span', view), errorWords(e, '今天的概括').text);
    }
  }

  /* ---- 家人端 · 主舞台三态（今天 / 待办 / 我的） -------------------------- */

  let pendingTask = null;      // 正在等家人点头的那一笔
  let pendingFacts = null;     // 它的金额与收款方（来自凭证，只读）

  /* 金额从**凭证**取，不从 `/v2/tasks` 取。
   *
   * `/v2/tasks` 给家人的那一份把 `slots` 整个抹成 null（实测），所以第一版
   * 屏幕上写的是「缴费已经核对到最后一步。确认后系统才会继续执行。」——
   * 金额那一句凭空消失了，而她要确认的恰恰是金额。
   *
   * `GET /payments/{id}/certificate` 是**只读**的（本项目 P0：渲染回执不许
   * 推进任何事务），它给 `amount` 和 `company`，正是要核对的两样。 */
  async function factsOf(task) {
    if (!task) return null;
    try {
      return await api(`/api/v1/payments/${encodeURIComponent(task.id)}/certificate`,
                       {}, FAMILY);
    } catch (e) {
      return null;      // 取不到就少说一句，不编一个金额
    }
  }

  async function loadStage(which) {
    const title = $('#stageTitle');
    const headline = $('#mainHeadline');
    const copy = $('#mainCopy');
    const band = $('#familyMain .action-band');
    let tasks = [];
    try {
      tasks = await api('/v2/tasks?limit=100', {}, FAMILY);
    } catch (e) { trouble(e, '这个家的事务'); return; }
    if (!Array.isArray(tasks)) tasks = tasks.items || [];

    const needYou = tasks.filter((t) => t.status === 'awaiting_family_approval');
    pendingTask = needYou[0] || null;

    if (which === 'todo') {
      text(title, '待办与提醒');
      const undone = tasks.filter(
        (t) => !['completed', 'cancelled', 'failed'].includes(String(t.status)));
      text(headline, undone.length ? `还有 ${undone.length} 件事在办` : '没有在办的事');
      text(copy, undone.length
        ? undone.slice(0, 3).map((t) => `${YH.taskWord(t.task_type)}（${YH.statusWord(t.status)}）`).join('；')
        : '需要办的事办完了。新的事会自动出现在这里。');
    } else if (which === 'mine') {
      text(title, '我的记录');
      const done = tasks.filter((t) => t.status === 'completed');
      text(headline, done.length ? `最近完成了 ${done.length} 件事` : '还没有办完的事');
      text(copy, '确认、提醒和照护记录都会在这里留下清晰的时间线。'
                 + (done.length ? `最近一次是${YH.taskWord(done[0].task_type)}。` : ''));
    } else {
      text(title, '今天最重要的事');
      if (pendingTask) {
        text(headline, '有一件事需要您确认');
        pendingFacts = await factsOf(pendingTask);
        const yuan = pendingFacts && pendingFacts.amount;
        const who = pendingFacts && pendingFacts.company;
        text(copy, `${YH.taskWord(pendingTask.task_type)}已经核对到最后一步。`
                   + (yuan ? `金额 ¥${yuan}` : '')
                   + (who ? `，收款方${who}` : '')
                   + (yuan || who ? '，' : '')
                   + '确认后系统才会继续执行。');
      } else {
        text(headline, '今天不用您操心');
        text(copy, '没有要您点头的事。有需要确认的，会主动出现在这里。');
      }
    }
    // 有没有那一笔，决定「查看并确认」这个按钮该不该在。
    const primary = $('.primary-action', band);
    if (primary) primary.hidden = which !== 'today' || !pendingTask;
    const step2 = $('#f3Approve');
    if (step2) step2.remove();
  }

  /* ---- 家人端 · 待办气泡（走交付包自己的渲染与动画） ---------------------- */

  function flowByName(name) {
    return (window.YouHuoFlow && window.YouHuoFlow.flows || [])
      .find((f) => f.dataset.flow === name) || null;
  }

  /** 把真数据塞进交付包的 STORE，再调它自己的 render / playFlow。 */
  function fillFlow(name, rows) {
    const F = window.YouHuoFlow;
    const flow = flowByName(name);
    if (!F || !flow) return;
    const arr = F.store[name];
    arr.length = 0;
    rows.forEach((r) => arr.push(r));
    F.render(flow, {reveal: true});
    F.playFlow(flow);
  }

  async function loadFamilyFlow() {
    try {
      const data = await api('/v2/reminders?limit=50', {}, FAMILY);
      const items = Array.isArray(data) ? data : (data.items || []);
      fillFlow('family', items.slice(0, 5).map((r) => ({
        id: String(r.id),
        time: hhmm(r.due_at || r.at),
        title: r.title,
        status: reminderWord(r.status),
        done: ['completed', 'acknowledged'].includes(String(r.status)),
      })));
    } catch (e) { trouble(e, '待办'); }
  }

  async function loadCareFlow() {
    try {
      const data = await api('/api/v1/records?limit=20', {}, FAMILY);
      fillFlow('care', data.items.slice(0, 5).map((r) => ({
        id: String(r.id),
        time: r.time || '',
        title: r.title,
        status: [r.kind, r.note].filter(Boolean).join(' · ') || '已记录',
        done: true,
        level: 'normal',
      })));
    } catch (e) { trouble(e, '最近记录'); }
  }

  /* ---- 照护中心 ----------------------------------------------------------- */

  function fillVein(which, strongText, smallText, tone) {
    const node = $(`[data-vein-node="${which}"]`);
    if (!node) return;
    text($('strong', node), strongText);
    text($('small', node), smallText);
    const seed = $('.status-seed', node);
    if (seed) seed.className = `status-seed ${tone || 'stable'}`;
  }

  async function loadCare() {
    const view = $('#careView');
    // 只写时刻，不写完整日期：完整日期在家人端那一侧已经有了，
    // 这里再写一遍会把这一行挤成两行，把下面的「照护 / 趋势」压进陪伴区。
    const now = new Date();
    text($('.identity-island p', view),
         `${pad(now.getHours())}:${pad(now.getMinutes())} 更新 · 先看整体，再看细节`);
    /* 「照护中心 · 张爷爷」里的名字删掉。
     *
     * 后端**没有任何端点返回老人的姓名**（`/api/v1/profile` 给的是调用者本人，
     * 这一页的调用者是女儿；identity 里只有 id）。这个项目已经为同一件事
     * 做过一次决定：`elder-v6-b.js:11` 和 `family-v6-b.js:649` 都记着
     * 「这个产品不编人名」，当时删的也是「张爷爷」。 */
    text($('.identity-island .hello', view), '照护中心');

    // 生活节律 / 今天
    if (dailyReport) {
      const word = dailyReport.todayWord;
      const careHead = $('.identity-island h1', view);
      text(careHead, word);
      fitOneLine(careHead, 30);
      const note = $('.companion-note', view);
      text($('strong', note), word);
      fillVein('today', '今天', word, dailyReport.established === false ? 'watch' : 'stable');
      const head = $('[data-care-page="today"] .substage-head');
      text($('h2', head), `今天，${word}`);
      /* 每一条通道都要说清「平常是什么样、今天是什么样」。
       * 第一版拿 `c.label` 取名字——**这个字段不存在**（真名是 `name`），
       * 于是 filter 之后是空数组，屏幕上落到「今天的节律还在记录中。」，
       * 而后端明明给了五条。 */
      const channels = dailyReport.channels || [];
      text($('p', head), channels.length
        ? channels.map((c) => c.today
            ? `${c.name} ${c.today}（${c.word}）`
            : `${c.name}${c.word}`).join(' · ')
        : '今天的节律还在记录中。');

      // 时钟上那四个点也换成真的通道。
      const rhythm = $$('[data-care-page="today"] .rhythm-node');
      rhythm.forEach((el, i) => {
        const c = channels[i];
        if (!c) { el.hidden = true; return; }
        el.hidden = false;
        text($('time', el), c.today || '—');
        text($('b', el), c.name);
        text($('small', el), c.usual ? `平常 ${c.usual}` : c.word);
      });
      const sun = $('[data-care-page="today"] .sun-center');
      if (sun) {
        text($('span', sun), `${pad(new Date().getHours())}:${pad(new Date().getMinutes())}`);
        text($('small', sun), word);
      }
      // 「步行 3,240 步 / 饮水 1.2 L」是**编出来的三个数**：后端没有任何一处
      // 记步数和饮水量。摆着不动比空着更糟——它会被当成真的读。
      const whispers = $('[data-care-page="today"] .today-whispers');
      if (whispers) {
        const rows = (dailyReport.errands && dailyReport.errands) || {};
        whispers.replaceChildren();
        [['今天该办', `${rows.dueToday || 0} 件`],
         ['已经办好', `${rows.done || 0} 件`],
         ['等您确认', `${rows.waitingFamily || 0} 件`]].forEach(([k, v]) => {
          const box = document.createElement('div');
          const b = document.createElement('strong');
          b.textContent = k;
          const s = document.createElement('span');
          s.textContent = v;
          box.append(b, s);
          whispers.appendChild(box);
        });
      }
    }

    // 用药
    try {
      const meds = await api(`/v4/medications/${encodeURIComponent(ELDER_ID)}`, {}, FAMILY);
      const plans = Array.isArray(meds) ? meds : (meds.items || meds.plans || []);
      fillVein('med', '在吃什么药',
               plans.length ? `${plans.length} 种药，记录见「用药」` : '还没有登记用药',
               plans.length ? 'stable' : 'watch');
      /* 字段名照 `/v4/medications` 真实返回来：`display_name` / `dose_text` /
       * `times_local` / `stock_units` / `active`。第一版写的是
       * `p.name` / `p.dosage` / `p.times`——**三个都不存在**，于是每一片药
       * 的名字和剂量都是空字符串，而卡片还在，看起来像是"这条记录本来就没内容"。 */
      const seals = $$('[data-care-page="med"] .medicine-seal');
      seals.forEach((el, i) => {
        const p = plans[i];
        if (!p) { el.hidden = true; return; }
        el.hidden = false;
        const times = p.times_local || [];
        text($('.med-time', el), times[0] || '按需');
        text($('strong', el), p.display_name || '');
        text($('small', el), [p.dose_text, times.length > 1 ? `每天 ${times.length} 次` : null]
          .filter(Boolean).join(' · '));
        text($('i', el), p.active === false ? '等老人确认' : '已登记');
      });
      const sum = $('[data-care-page="med"] .med-summary');
      if (sum) {
        text($('b', sum), plans.length ? `一共 ${plans.length} 种长期用药` : '还没有登记用药');
        const stock = plans.filter((p) => typeof p.stock_units === 'number');
        text($('span', sum), stock.length
          ? `余量最少的还有 ${Math.min(...stock.map((p) => p.stock_units))} 份`
          : (plans.length ? '到点会提醒老人' : '可以在老人端或这里添加'));
      }
      // 「2 种长期用药，今日记录完整。」是写死的。实测五脉说 1 种、这一句说 2 种，
      // 同一屏两个数字对不上——而这一句躲过了第一轮驱动，因为它读起来很正常。
      const medHead = $('[data-care-page="med"] .substage-head p');
      text(medHead, plans.length
        ? `${plans.length} 种长期用药，明细见下。`
        : '还没有登记长期用药。');
    } catch (e) {
      fillVein('med', '在吃什么药', '暂时取不到用药记录', 'watch');
    }

    /* 身体。字段照 `HealthEventRecord`：`kind` / `title` / `event_at` / `payload`。
     * 没有 `metric` / `value` / `unit` / `recorded_at` 这几个名字——
     * 第一版全用的是它们，只是演示库里这张表恰好是空的，所以一个都没露馅。
     * 「128/76 mmHg」那四张卡片是交付包写死的，后端没有这些数。 */
    const KIND_WORD = {checkup: '体检', visit: '就诊', medication: '用药', note: '记录'};
    try {
      const raw = await api(`/v4/health/events/${encodeURIComponent(ELDER_ID)}`, {}, FAMILY);
      const rows = Array.isArray(raw) ? raw : (raw.items || raw.events || []);
      fillVein('body', '身体',
               rows.length ? `最近一次 ${hhmm(rows[0].event_at) || '刚刚'}`
                           : '还没有记到身体数据',
               rows.length ? 'stable' : 'watch');
      const metrics = $$('[data-care-page="body"] .body-metric');
      metrics.forEach((el, i) => {
        const r = rows[i];
        if (!r) { el.hidden = true; return; }
        el.hidden = false;
        text($('span', el), KIND_WORD[String(r.kind)] || '记录');
        text($('strong', el), r.title || '');
        text($('small', el), hhmm(r.event_at) || '');
      });
      const core = $('[data-care-page="body"] .body-core');
      if (core) {
        text($('small', core), '身体记录');
        text($('strong', core), rows.length ? `${rows.length} 条` : '还没有');
        text($('span', core), rows.length ? '最近的在右边' : '等待第一条记录');
      }
      const bodyHead = $('[data-care-page="body"] .substage-head');
      text($('h2', bodyHead), rows.length ? '最近的身体记录' : '还没有身体记录');
      text($('p', bodyHead), rows.length
        ? '这里只列记录本身，不做判断，也不代替医生。'
        : '老人端量过血压、体温之后，这里会出现记录。');
    } catch (e) {
      fillVein('body', '身体', '暂时取不到身体记录', 'watch');
    }

    // 心情
    try {
      const mood = await api('/api/v1/emotions/review?days=14', {}, FAMILY);
      fillVein('mood', '心情', mood.count ? mood.trend : '记录还不够多', 'stable');
      const head = $('[data-care-page="mood"] .substage-head');
      text($('h2', head), mood.count ? mood.trend : '还没有足够的心情记录');
      text($('p', head), mood.count
        ? `来自最近 ${mood.days} 天的 ${mood.count} 条记录整理。`
        : '这里只整理趋势，不保存和无忧伴聊天的原文。');
      /* `moods` 是**类别计数** `[{name, count}]`，不是每天一条。
       * 第一版把它当成 `{date,label}` 摆进「周一/周二/周三/今天」四个格子——
       * 那是把统计口径读错了：屏幕上会写着「周一 · 平静」，而后端说的是
       * 「平静这一类出现了 N 次」。日期是编的。 */
      const days = $$('[data-care-page="mood"] .mood-day');
      days.forEach((el, i) => {
        const m = (mood.moods || [])[i];
        if (!m) { el.hidden = true; return; }
        el.hidden = false;
        text($('b', el), m.name);
        text($('span', el), `${m.count} 次`);
      });
      const heart = $('[data-care-page="mood"] .flower-heart');
      if (heart) {
        const top = (mood.moods || []).slice().sort((a, b) => b.count - a.count)[0];
        text(heart, top ? top.name : '还没有');
      }
      // 「傍晚想出去走一走。」是**编的一句原文**。心情这一页明确写着不保存聊天原文，
      // 摆一句引言等于自己打自己的脸。取不到就撤掉，不留占位。
      const quote = $('[data-care-page="mood"] blockquote');
      if (quote) quote.hidden = true;
    } catch (e) {
      fillVein('mood', '心情', '暂时取不到心情趋势', 'watch');
    }

    // 安全
    try {
      const [policy, contacts] = await Promise.all([
        api(`/v4/safety/policy/${encodeURIComponent(ELDER_ID)}`, {}, FAMILY).catch(() => null),
        api('/api/v1/contacts', {}, FAMILY).catch(() => ({items: [], count: 0})),
      ]);
      fillVein('safety', '安全',
               contacts.count ? `联系人 ${contacts.count} 人 · 设置正常` : '还没有登记联系人',
               contacts.count ? 'stable' : 'watch');
      /* 每一格都必须对得上 `/v4/safety/policy` 真的有的字段：
       * `inactivity_minutes` / `geofence_radius_m` / `notify_community`。
       *
       * 第一版有一行读 `policy.medication_reminder`——**这个字段不存在**，
       * `undefined === false` 是假，于是它永远显示「已开启」。
       * 一个恒为真的安全指示灯，比没有这一格危险得多。
       * 第四行「异常事件 今天 0 条」也是编的：这一层没有异常事件的数据源。 */
      const nodes = $$('[data-care-page="safety"] .guard-node');
      const rows = [['家人联系人', contacts.count ? `${contacts.count} 人 · 正常` : '还没有登记']];
      if (policy) {
        if (policy.inactivity_minutes) {
          rows.push(['久未活动', `超过 ${Math.round(policy.inactivity_minutes / 60)} 小时就提醒`]);
        }
        rows.push(['紧急联系', policy.notify_community ? '家人之后还会找社区' : '只找家人']);
        if (policy.geofence_radius_m) {
          rows.push(['活动范围', `离家超过 ${policy.geofence_radius_m} 米会提醒`]);
        }
      }
      nodes.forEach((el, i) => {
        if (!rows[i]) { el.hidden = true; return; }
        el.hidden = false;
        text($('b', el), rows[i][0]);
        text($('span', el), rows[i][1]);
      });
      const safeHead = $('[data-care-page="safety"] .substage-head p');
      text(safeHead, policy
        ? `联系人 ${contacts.count} 位，久未活动与活动范围都已设置。`
        : '安全设置暂时取不到。');
      const gcore = $('[data-care-page="safety"] .guardian-core');
      if (gcore) {
        text($('strong', gcore), contacts.count ? '安全' : '待设置');
        text($('small', gcore), contacts.count ? `${contacts.count} 位联系人在册` : '还没有联系人');
      }
    } catch (e) {
      fillVein('safety', '安全', '暂时取不到安全设置', 'watch');
    }

    // 趋势：来自日报的 established / observedDays / channels
    if (dailyReport) {
      const days = dailyReport.observedDays;
      const sum = $('[data-care-page="trend"] .trend-summary');
      if (sum) {
        text($('strong', sum), dailyReport.established ? '总体：已建立基线' : '总体：还在学习');
        text($('span', sum), days ? `已经观察 ${days} 天` : '记录还不够多');
      }
      const head = $('[data-care-page="trend"] .substage-head p');
      text(head, days ? `看最近 ${days} 天，不被某一次数字带着走。`
                      : '记录够多之后，这里才会给出趋势。');
      // 三个标签换成真的通道，别留「起居 趋于稳定」这类没有来源的判断。
      const labels = $$('[data-care-page="trend"] .trend-label');
      const chans = dailyReport.channels || [];
      labels.forEach((el, i) => {
        const c = chans[i];
        if (!c) { el.hidden = true; return; }
        el.hidden = false;
        text($('b', el), c.name);
        text($('span', el), c.word);
      });
    }

    // 整体判断那一段
    const verdict = $('.care-verdict-core');
    if (verdict && dailyReport) {
      text($('h3', verdict), dailyReport.message || dailyReport.todayWord);
      text($('p', verdict), dailyReport.privacyNote
        || '把生活节律、身体、用药、心情与安全放在一起看；这里只整理趋势，不替代医生判断。');
    }
  }

  /* ---- 接线 --------------------------------------------------------------- */

  function wire() {
    // 主舞台三态：摘掉那张写死的 `states` 表。
    $$('[data-family]').forEach((old) => {
      const btn = strip(old);
      btn.addEventListener('click', () => {
        /* 照护那一屏的底栏也有这三个键（安装时补的 `data-family`——
         * 交付包里它们连一个属性都没有，是死键）。从照护点「待办」，
         * 得先切回家人端，否则改的是一屏看不见的东西。 */
        if ($('#careView') && !$('#careView').hidden) {
          const back = $('[data-app="family"]');
          if (back) back.click();
        }
        $$('[data-family]').forEach((x) => x.classList.remove('active'));
        btn.classList.add('active');
        const main = $('#familyMain');
        main.classList.remove('todo-stage', 'mine-stage');
        if (btn.dataset.family === 'todo') main.classList.add('todo-stage');
        if (btn.dataset.family === 'mine') main.classList.add('mine-stage');
        loadStage(btn.dataset.family);
      });
    });

    /* 「查看并确认这件事」：**只读**。
     * 摊开这一笔的金额、摘要和它已经走过的步骤，然后**另外长出**一个确认按钮。
     * 一次点击直接把钱付掉，正是本项目 P0 要防的那件事。 */
    const primary = strip($('.primary-action'));
    if (primary) {
      primary.addEventListener('click', () => once(primary, async () => {
        if (!pendingTask) { say('现在没有要您确认的事。', 'warning'); return; }
        const t = pendingTask;
        const facts = pendingFacts || await factsOf(t);
        const yuan = facts && facts.amount;
        const who = facts && facts.company;
        say([
          `${YH.taskWord(t.task_type)}`,
          yuan ? `金额 ¥${yuan}` : null,
          who ? `收款方 ${who}` : null,
          t.approval_digest ? `核对码 ${String(t.approval_digest).slice(0, 8)}…` : null,
        ].filter(Boolean).join(' · ') + '。核对无误再按下面的确认。', 'warning');

        if ($('#f3Approve')) return;
        if (!t.approval_digest) {
          say('这一笔暂时取不到核对码，先不要确认。刷新一下再看。', 'bad');
          return;
        }
        const band = $('#familyMain .action-band');
        const yes = document.createElement('button');
        yes.id = 'f3Approve';
        yes.type = 'button';
        yes.className = 'f3-approve';
        yes.textContent = '核对过了，确认接力';
        band.appendChild(yes);
        yes.addEventListener('click', () => once(yes, async () => {
          try {
            const data = await api('/v2/family/approve', {
              method: 'POST',
              body: JSON.stringify({
                task_id: t.id, approve: true,
                approval_digest: t.approval_digest,
                reason: '家属已核对任务摘要',
              }),
            }, FAMILY);
            say(data.message, YH.toneOf(data));
            yes.remove();
            await loadStage('today');
            loadFamilyFlow();
          } catch (e) { trouble(e, '这一笔'); }
        }));
      }));
    }

    // 「今天怎么样」
    const secondary = strip($('.secondary-action'));
    if (secondary) {
      secondary.addEventListener('click', () => once(secondary, async () => {
        try {
          // 和 `loadHeader()` 走**同一个**端点。这里原先还留着 v7 那条
          // 和 `today_word` 那个不存在的字段名——`test_design_three_is_wired`
          // 的字段对账把它抓出来了，而屏幕上它一直显示着我写的那句兜底。
          dailyReport = await api('/api/v1/daily-report', {}, FAMILY);
          say(dailyReport.message || dailyReport.todayWord, 'good');
          loadHeader();
        } catch (e) { trouble(e, '今天的情况'); }
      }));
    }

    /* 建一条提醒：交付包那个 submit 只往内存数组里 push。摘掉，改成真的建。 */
    $$('.bubble-flow').forEach((flow) => {
      const editor = $('.flow-editor', flow);
      if (!editor) return;
      const fresh = strip(editor);
      const which = flow.dataset.flow;
      // 「取消」的监听跟着一起被摘了，补回来。
      const cancel = $('.flow-cancel', fresh);
      if (cancel) cancel.addEventListener('click', () => { fresh.hidden = true; });
      fresh.addEventListener('submit', (e) => {
        e.preventDefault();
        const fd = new FormData(fresh);
        const time = String(fd.get('time') || '').trim();
        const title = String(fd.get('title') || '').trim();
        if (!title || !time) { say('时间和事项都要填。', 'warning'); return; }
        const submit = $('button[type="submit"]', fresh);
        once(submit, async () => {
          // 只有家人端那一侧是"给老人加一件事"；照护那一侧的气泡是**记录**，
          // 记录不是家人能凭空造出来的，所以那边不给建。
          if (which !== 'family') {
            say('照护记录来自老人自己办的事和身体数据，这里不新增。', 'warning');
            return;
          }
          const now = new Date();
          const [hh, mm] = time.split(':');
          const due = new Date(now.getFullYear(), now.getMonth(), now.getDate(),
                               Number(hh), Number(mm));
          if (due <= now) due.setDate(due.getDate() + 1);   // 已经过点就顺延到明天
          try {
            const data = await api('/v2/family/reminders', {
              method: 'POST',
              body: JSON.stringify({
                elder_id: ELDER_ID, title,
                due_at: due.toISOString(),
                escalation_after_minutes: 30,
              }),
            }, FAMILY);
            fresh.hidden = true;
            say(data.message || '加好了，老人那边会看到。', YH.toneOf(data));
            loadFamilyFlow();
          } catch (err) { trouble(err, '这条待办'); }
        });
      });
    });

    /* 删一条提醒：交付包只从内存数组里删。在捕获阶段拦下来，先问后端。 */
    $$('.bubble-flow').forEach((flow) => {
      flow.addEventListener('click', (e) => {
        const btn = e.target.closest('.flow-delete');
        if (!btn) return;
        const item = btn.closest('.flow-item');
        const id = item && item.dataset.id;
        if (flow.dataset.flow !== 'family' || !id) {
          e.stopPropagation();
          e.preventDefault();
          say('这一条是记录，不能删掉。记录删掉了，凭证就对不上了。', 'warning');
          return;
        }
        e.stopPropagation();
        e.preventDefault();
        // 取消在 **`/api/v1`** 上，不在 `/v2`——`/v2/reminders/{id}/` 只有
        // `acknowledge` 和 `complete` 两个动作。第一版写的是 `/v2/.../cancel`，
        // 点「×」会 404，而气泡照样从屏幕上消失（交付包那个纯前端删除先跑了）。
        api(`/api/v1/reminders/${encodeURIComponent(id)}/cancel`,
            {method: 'POST', body: JSON.stringify({})}, FAMILY)
          .then((data) => {
            say(data.message || '这一条取消了。', YH.toneOf(data));
            loadFamilyFlow();
          })
          .catch((err) => trouble(err, '这一条'));
      }, true);
    });

    // 一键联系子女
    $$('.dock .contact').forEach((old) => {
      const btn = strip(old);
      btn.addEventListener('click', () => once(btn, async () => {
        try {
          const data = await api('/api/v1/contacts', {}, FAMILY);
          if (!data.count) { say('还没有登记联系人。', 'warning'); return; }
          say('可以联系：' + data.items.map((c) => `${c.name}（${c.role}）`).join('、'), 'good');
        } catch (e) { trouble(e, '联系人'); }
      }));
    });

    // 照护七个页签：切到哪个读哪个（概览的五脉一次读完，不重复请求）。
    $$('#careTabs [data-care-panel]').forEach((tab) => {
      tab.addEventListener('click', () => {
        if (tab.dataset.carePanel === 'overview') return;   // 五脉在 loadCare 里已经填过
      });
    });

    /* 切到照护中心之后整屏是空的——**这是交付包的缺陷，不是数据没到**。
     *
     * 实测（点「照护中心」后每秒量一次，量的是 opacity 不是 boundingRect）：
     *
     *     +1s  看得见 53 段字 · 淡掉 92 段
     *     +6s  看得见 56 段字 · 淡掉 89 段     ← 不再变化，anim=none
     *     家人端那一屏对照：看得见 37 · 淡掉 3
     *
     * 停在 opacity:0 的包括身份区的 `.hello` / `h1` / `p` 和陪伴区两段。
     * 成因：`style-01.css:1852` 把这些元素的初始态设成 `opacity:0`，只有
     * `.workspace.page-bloom` 才给它们动画；而 `page-bloom` 是
     * `script-07.js` 在**过场动画播完**时加的，顶部这个切换只是 `hidden`
     * 开关，从不播过场——于是 `#careView` 永远拿不到这个类。
     *
     * 用它自己的机制补：remove → 强制回流 → add，和 `bloomWorkspace()`
     * 一模一样（那个函数在 IIFE 里，外面够不着）。 */
    function bloom(view) {
      if (!view) return;
      view.classList.remove('page-bloom');
      void view.offsetWidth;
      view.classList.add('page-bloom');
    }

    $$('[data-app]').forEach((btn) => {
      btn.addEventListener('click', () => {
        if (btn.dataset.app === 'care') { bloom($('#careView')); loadCare(); }
        else { bloom($('#familyView')); loadStage('today'); }
      });
    });
    const goCare = $('#goCare');
    if (goCare) goCare.addEventListener('click', () => { bloom($('#careView')); loadCare(); });
    const backFamily = $('#backFamily');
    if (backFamily) {
      backFamily.addEventListener('click', () => { bloom($('#familyView')); loadStage('today'); });
    }

    // 五脉节点点一下就跳到对应的子面板——交付包只给了 hover 提示，没有跳转。
    $$('[data-vein-node]').forEach((node) => {
      node.addEventListener('click', () => {
        const go = window.showYouHuoCarePage;
        if (go) go(node.dataset.veinNode);
      });
    });
  }

  async function boot() {
    const ids = await YH.ready();
    ELDER_ID = ids.elderId || ELDER_ID;
    wire();
    await loadHeader();
    await loadStage('today');
    loadFamilyFlow();
    loadCareFlow();
  }

  boot().catch((e) => say(errorWords(e, '优活').text, 'bad'));
})();
