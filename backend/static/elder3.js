/* 老人端设计三（网页端 `/elder3`）的接线。
 *
 * ## 这个文件只做一件事
 *
 * 把设计三那套 DOM 接到**和设计一二完全相同的后端端点**上。它不含业务判断，
 * 不含第二套文案表，不含第二套字号语速映射——这个项目已经因为「两套实现
 * 各自往返都绿、跨子系统才红」栽过一次（字号语速和 SOS 各有两套实现）。
 *
 * ## 交付包里带着四个「假控件」，必须先摘掉
 *
 * `page-motion-and-ui.js` 已经给下面这些绑了监听，而它们**只演不做**：
 *
 *     #savePref   显示「✓ 已保存」1.5 秒，一个字节都不存
 *     #voiceOrb   把说明改成「正在听，请慢慢说…」2.1 秒，什么都没听
 *     .segmented  只切 `active` 类，值不去任何地方
 *     模式切换     只弹一条 toast
 *
 * 光加一个自己的监听是不够的：两个监听都会跑，于是**我这边失败的时候，
 * 屏幕上照样先弹出「✓ 已保存」**。一个说"已保存"却没保存的按钮，
 * 比没有这个按钮更糟。所以对前两个用 `cloneNode` 把匿名监听整个摘掉再接。
 *
 * `.segmented` 和模式切换的那两个监听是**纯视觉**的（切 class、弹 toast），
 * 那正是我想要的，留着；我在旁边加自己的那一份读值。
 *
 * ## 不重建 DOM
 *
 * `.story-node` / `.record-event` 的位置靠 CSS 的 n1/n2/n3、e1..e4 决定，
 * 而 `crane-animation-master.js` 和入场动画持有这些节点。所以**原地改文字、
 * 多的隐藏**，不 replaceChildren。这也对应交付包 README 的第 8 条：
 * 「UI 最终状态必须默认可见，避免再次出现文字/卡片突然消失」。
 */
(function () {
  'use strict';

  const YH = window.YouHuo;
  if (!YH) return;                       // common.js 没加载就什么都不做，别抛异常
  const {api, once, errorWords} = YH;

  const $ = (sel, root) => (root || document).querySelector(sel);
  const $$ = (sel, root) => [...(root || document).querySelectorAll(sel)];
  const ws = (name) => $(`.workspace[data-workspace="${name}"]`);

  /* 语速 / 字号的取值**必须和 `elder.html` 的 `#speechRate` `#fontScale` 一致**。
   * 那两个 select 的 option 就是这六个数。设计三用的是分段按钮，词一样，
   * 所以这里按词映射；`test_elder_design3.py` 有一道判据钉住三处不许分叉。 */
  const SPEED = {'慢': 0.72, '舒适': 0.88, '正常': 1.0};
  const FONT = {'较大': 1.1, '大': 1.25, '特大': 1.5};
  const nearest = (table, value) => {
    let best = null, gap = Infinity;
    for (const [word, v] of Object.entries(table)) {
      const d = Math.abs(Number(value) - v);
      if (d < gap) { gap = d; best = word; }
    }
    return best;
  };

  /* ---- 状态行 -------------------------------------------------------------
   *
   * 这一页原先没有任何地方能说「刚才那一下怎么样了」。加一条，放在麦克风说明
   * 下面——那是她按完按钮眼睛所在的位置。空的时候自己不占位。 */
  let statusEl = null;
  function ensureStatus() {
    if (statusEl) return statusEl;
    const host = $('.voice-caption');
    if (!host) return null;
    statusEl = document.createElement('p');
    statusEl.id = 'e3Status';
    statusEl.className = 'e3-status';
    statusEl.setAttribute('role', 'status');
    statusEl.setAttribute('aria-live', 'polite');
    host.insertAdjacentElement('afterend', statusEl);
    return statusEl;
  }
  function say(text, tone) {
    const el = ensureStatus();
    if (!el) return;
    el.textContent = text || '';
    el.dataset.tone = tone || 'good';
  }
  const trouble = (e, what) => say(errorWords(e, what).text, 'bad');

  /** 在状态行下面摆几个动作按钮。空数组 = 收掉。
   *
   * 为什么要「问一句再做」：这一版的待办是一个整块的椭圆气泡，
   * 点一下就把一件事标成办好了，手一抖就改了记录，而她看不出刚才发生过什么。
   * 设计一那边是两个写着字的按钮，这里照它来——只是按钮长在状态行下面。
   */
  function offer(actions) {
    let row = $('#e3Actions');
    if (!actions || !actions.length) { if (row) row.remove(); return; }
    if (!row) {
      row = document.createElement('div');
      row.id = 'e3Actions';
      row.className = 'e3-actions';
      const host = ensureStatus();
      if (!host) return;
      host.insertAdjacentElement('afterend', row);
    }
    row.replaceChildren();
    actions.forEach(({label, run}) => {
      const b = document.createElement('button');
      b.type = 'button';
      b.textContent = label;
      b.addEventListener('click', () => once(b, run));
      row.appendChild(b);
    });
  }

  /* 念出来。用浏览器自带的合成，语速取她自己存的那个值。 */
  let speechRate = 0.88;
  function speakOut(text) {
    if (!text || !window.speechSynthesis) return;
    try {
      const u = new SpeechSynthesisUtterance(String(text));
      u.lang = 'zh-CN';
      u.rate = speechRate;
      window.speechSynthesis.cancel();
      window.speechSynthesis.speak(u);
    } catch (_) { /* 合成不可用不影响办事 */ }
  }

  /* ---- 今天 --------------------------------------------------------------- */

  function greeting() {
    const h = new Date().getHours();
    if (h < 6) return '夜里好';
    if (h < 11) return '早上好';
    if (h < 13) return '中午好';
    if (h < 18) return '下午好';
    return '晚上好';
  }

  function stamp(d) {
    const pad = (n) => String(n).padStart(2, '0');
    const week = '日一二三四五六'[d.getDay()];
    return `${d.getFullYear()}年${pad(d.getMonth() + 1)}月${pad(d.getDate())}日 `
         + `周${week} · ${pad(d.getHours())}:${pad(d.getMinutes())}`;
  }

  async function loadToday() {
    const page = ws('today');
    if (!page) return;
    const island = $('.identity-island', page);
    const meta = $('.identity-meta', island);
    if (meta) meta.textContent = stamp(new Date());

    try {
      const me = await api('/api/v1/profile');
      const h1 = $('h1', island);
      if (h1) h1.textContent = `${greeting()} · ${me.name}`;
    } catch (e) { trouble(e, '您的档案'); }

    let agenda = null;
    try {
      agenda = await api('/api/v1/agenda');
    } catch (e) {
      trouble(e, '今天的安排');
      return;
    }

    // 一句话说清今天。没有事就说没有事，不留占位文案。
    const lead = $('.identity-island p', page);
    if (lead) {
      lead.textContent = agenda.next
        ? `今天有 ${agenda.count} 件事。下一件是${agenda.next.title}，别着急，一件一件来。`
        : (agenda.count
            ? `今天有 ${agenda.count} 件事，都已经过去了。`
            : '今天没有要办的事。想起什么，随时按麦克风告诉我。');
    }

    // 「下一件」卡片
    const nextCard = $('.next-card', page);
    if (nextCard) {
      if (agenda.next) {
        const label = $('.label', nextCard);
        const strong = $('strong', nextCard);
        const metas = $$('.meta span', nextCard);
        if (label) label.textContent = `下一件 · ${agenda.next.time}`;
        if (strong) strong.textContent = agenda.next.title;
        /* 两格不许说同一件事。
         *
         * 第一版是 `note` + （过点了 ? '已经过点了' : '到点提醒'），而后端给的
         * `note` 本身就是「这一件已经过点了。」——屏幕上于是并排印着
         * 「这一件已经过点了。　已经过点了」。实测截图上看得清清楚楚。
         * 后一格只在**前一格没说**的时候才补。 */
        const note = agenda.next.note || '';
        const overdue = !!agenda.next.overdue;
        if (metas[0]) {
          metas[0].textContent = note;
          metas[0].hidden = !note;
        }
        if (metas[1]) {
          const extra = overdue ? (note ? '' : '已经过点了') : '到点提醒';
          metas[1].textContent = extra;
          metas[1].hidden = !extra;
        }
        nextCard.hidden = false;
      } else {
        // 藏起来，而不是留着一张写着别人事情的卡片。
        nextCard.hidden = true;
      }
    }

    /* 状态词用**后端给的那个**（`it.status`），不在这里另写一套。
     *
     * 第一版写的是 `it.done ? '已完成' : '还没办'`——两个词，而后端有三个状态
     * （待进行 / 知道了 / 已完成）。实测：按「我知道了」之后气泡上写的是
     * 「已完成」，也就是屏幕替她宣称药已经吃了。 */
    fillTimeline(page, agenda.today.map((it) => ({
      t: it.time, n: it.title, s: it.status,
      done: it.done, id: it.id,
    })), '今天没有要办的事');

    askAboutPendingMedication();
  }

  /** 家人加的药，等她点头。
   *
   * 设计一那边渲染成待办列表里的一张卡；这一版的今天页只有三个位置固定的
   * `.story-node`（位置由 CSS 的 n1/n2/n3 决定，动画脚本还持有它们），
   * 塞不进第四条。所以走**状态行 + 动作行**——那正是 `offer()` 的用途，
   * 也是她按完麦克风眼睛所在的位置。
   *
   * 一次只问一件。三份待确认的药摆六个按钮，就不是「问一句」了。
   */
  async function askAboutPendingMedication() {
    let data;
    try {
      data = await api('/api/v1/medications/pending');
    } catch (e) {
      // 安静地跳过。这是**额外**的一块，让它的失败盖掉今天的安排不划算。
      return;
    }
    if (!data.count) return;

    const plan = data.items[0];
    const more = data.count > 1 ? `（还有 ${data.count - 1} 份，一件一件来）` : '';
    say(`${data.message}${more}`, 'warning');

    const decide = async (approve) => {
      try {
        const said = await api(
          `/api/v1/medications/${encodeURIComponent(plan.id)}/${approve ? 'approve' : 'decline'}`,
          {method: 'POST', body: JSON.stringify({})});
        say(said.message, 'good');
        speakOut(said.message);
        offer([]);
        loadToday();          // 还有下一份的话，它会自己接着问
      } catch (e) {
        trouble(e, '这份药');
        offer([]);
      }
    };
    offer([
      {label: '开始吃', run: () => decide(true)},
      {label: '先不吃', run: () => decide(false)},
    ]);
  }

  /* 三个 story-node 原地改文字，多的隐藏。位置靠 CSS 的 n1/n2/n3，不能重建。 */
  function fillTimeline(page, rows, emptyWord) {
    const nodes = $$('.left-story .story-node', page);
    nodes.forEach((node, i) => {
      const row = rows[i];
      if (!row) { node.hidden = true; return; }
      node.hidden = false;
      const t = $('.t', node), n = $('.n', node), s = $('.s', node);
      if (t) t.textContent = row.t || '';
      if (n) n.textContent = row.n || '';
      if (s) s.textContent = row.s || '';
      node.classList.toggle('done', !!row.done);
      node.classList.toggle('pending', !row.done);
      if (row.id) node.dataset.reminderId = row.id;
      // 每一条都要能做点什么。这几个是 `<button>`——按下去什么都不发生的按钮，
      // 是一句永远为假的承诺（实测：今天那一屏点遍所有控件，只有它是死的）。
      node.dataset.act = row.act || (row.id ? 'reminder' : 'speak');
      node.dataset.speak = [row.n, row.s].filter(Boolean).join('，');
    });
    const head = $('.left-story .story-head b', page);
    if (head && !rows.length && emptyWord) head.textContent = emptyWord;
  }

  /* ---- 「我的数据」四条 -------------------------------------------------------
   *
   * 设计一二的「我的」屏有这四项，设计三的交付包里**一项都没有**：
   * 端点齐全（`/api/v1/daily-report`、`/api/v1/emotions/review`、
   * `/api/v1/privacy/data`、`/api/v1/privacy/erase{,/preview}`），
   * 而 `elder3.js` 一处都不调。也就是说这一版的老人**看不到优活替她记了什么，
   * 也删不掉**——那正是这个产品对隐私那几句承诺的兑现处。
   *
   * 端点和读的字段都照 `elder.js` **一字不差**地来。这个项目已经因为
   * 「两套实现各自往返都绿、跨子系统才红」栽过一次（字号语速和 SOS），
   * 所以 `test_design_three_has_the_data_tools.py` 钉住两处不许分叉。
   */

  function dataOut() {
    return $('#e3DataOut');
  }

  function outText(host, words) {
    host.replaceChildren();
    const p = document.createElement('p');
    p.textContent = words || '';
    host.appendChild(p);
    host.hidden = !words;
  }

  /** 「名称 数量」一行一条。只印后端给的中文名。 */
  function outCounts(host, rows, lead) {
    host.replaceChildren();
    if (lead) {
      const p = document.createElement('p');
      p.textContent = lead;
      host.appendChild(p);
    }
    const list = document.createElement('ul');
    // 数量为 0 的不印。「就医单据 0 条」对老人没有信息量，
    // 只是让这张单子长一倍——而她要回答的问题是「优活都记了我什么」。
    (rows || []).filter((r) => Number(r.count) > 0).forEach((r) => {
      const li = document.createElement('li');
      li.textContent = `${r.name}　${r.count} 条`;
      list.appendChild(li);
    });
    host.appendChild(list);
    host.hidden = false;
  }

  async function showDayReport() {
    const host = dataOut();
    try {
      const data = await api('/api/v1/daily-report');
      host.replaceChildren();
      const line = document.createElement('p');
      line.textContent = data.message || '';
      host.appendChild(line);
      // 五个通道逐条说，但**只说有结论的**。`word` 是「现在还说不准」的那几条
      // 照样印——那不是缺数据，是一个诚实的回答。
      const list = document.createElement('ul');
      (data.channels || []).forEach((c) => {
        const li = document.createElement('li');
        li.textContent = c.today
          ? `${c.name}　${c.today}（平常 ${c.usual || '还没算出来'}）　${c.word}`
          : `${c.name}　${c.word}`;
        list.appendChild(li);
      });
      host.appendChild(list);
      host.hidden = false;
      speakOut(data.message);
    } catch (e) { outText(host, errorWords(e, '今天的情况').text); }
  }

  async function showMoodReview() {
    const host = dataOut();
    try {
      const data = await api('/api/v1/emotions/review?days=14');
      host.replaceChildren();
      const line = document.createElement('p');
      line.textContent = data.message || '';
      host.appendChild(line);
      // 建议是后端按真实记录给的，不是这里编的。没有就不印这一段。
      (data.suggestions || []).forEach((s) => {
        const p = document.createElement('p');
        p.className = 'meta';
        p.textContent = s;
        host.appendChild(p);
      });
      // 这句承诺必须跟着显示：这一页别处写着「和无忧伴聊天的内容不会记在这里」，
      // 而这一块正是最容易让人怀疑那句话的地方。
      if (data.privacyNote) {
        const note = document.createElement('p');
        note.className = 'meta';
        note.textContent = data.privacyNote;
        host.appendChild(note);
      }
      host.hidden = false;
      speakOut(data.message);
    } catch (e) { outText(host, errorWords(e, '心情记录').text); }
  }

  async function showMyData() {
    const host = dataOut();
    try {
      const data = await api('/api/v1/privacy/data');
      outCounts(host, data.buckets, data.message || `一共 ${data.total} 条。`);
    } catch (e) { outText(host, errorWords(e, '您的数据').text); }
  }

  /** 删除第一步：告诉她要删什么，然后**才**给出第二个按钮。
   *
   * 第二步的按钮**一开始不存在于 DOM 里**，不是 disabled 也不是 hidden。
   * 一个看得见的「确认删除」按钮会让人以为「点两下就没了」；而它在看到清单
   * 之前根本不该存在。这一条和设计一二是同一个规矩。
   *
   * `confirmToken` 是驼峰，和 preview 返回的字段名一致；写成下划线后端读不到，
   * 会正确地走 400。它保证的不是防伪造，而是**她确认的对象和她看到的那一份
   * 是同一份**——回执写「删掉 7 条」实际删了 9 条，两边都不报错。
   */
  async function startErase() {
    const host = dataOut();
    try {
      const preview = await api('/api/v1/privacy/erase/preview',
                                {method: 'POST', body: '{}'});
      outCounts(host, preview.willDelete, preview.message);

      const keep = document.createElement('p');
      keep.className = 'meta';
      keep.textContent = '这些会留下来：' + (preview.preserved || []).join('、');
      host.appendChild(keep);

      const confirm = document.createElement('button');
      confirm.type = 'button';
      confirm.className = 'danger';
      confirm.textContent = `确认删掉这 ${preview.total} 条`;
      confirm.addEventListener('click', () => once(confirm, async () => {
        try {
          const done = await api('/api/v1/privacy/erase', {
            method: 'POST',
            body: JSON.stringify({confirmToken: preview.confirmToken}),
          });
          outText(host, done.message || '删好了。');
          speakOut(done.message);
        } catch (e) {
          // 令牌过期（条数在这中间变了）走 409，后端那句话说得比这里清楚。
          outText(host, errorWords(e, '删除').text);
        }
      }));
      host.appendChild(confirm);

      const cancel = document.createElement('button');
      cancel.type = 'button';
      cancel.className = 'secondary';
      cancel.textContent = '先不删';
      cancel.addEventListener('click', () => {
        host.replaceChildren();
        host.hidden = true;
      });
      host.appendChild(cancel);
    } catch (e) { outText(host, errorWords(e, '要删的东西').text); }
  }

  function wireDataTools() {
    // 四个都往返后端，慢网络下连点两次的第二次会拿一个用过的令牌去删一份
    // 已经不存在的数据——后端会正确地拒绝，而屏幕上会闪一句错误，
    // 让人以为第一次没成功。所以一律包在 `once()` 里。
    [['#e3DayReport', showDayReport],
     ['#e3MoodReview', showMoodReview],
     ['#e3MyData', showMyData],
     ['#e3EraseStart', startErase]].forEach(([sel, run]) => {
      const btn = $(sel);
      if (btn) btn.addEventListener('click', () => once(btn, run));
    });
  }

  /* ---- 记录 --------------------------------------------------------------- */

  let lastSpoken = '';

  async function loadRecords() {
    const page = ws('records');
    if (!page) return;
    let data;
    let taskIds = new Set();
    try {
      // 两个一起取。第二个决定哪些行**真的**有经过可看——见下面 `entityId` 那一段。
      const [records, tasks] = await Promise.all([
        api('/api/v1/records?limit=20'),
        api('/v2/tasks?limit=100').catch(() => []),
      ]);
      data = records;
      taskIds = new Set((tasks || []).map((t) => t.id));
    } catch (e) { trouble(e, '办事记录'); return; }

    const events = $$('.record-event', page);
    events.forEach((el, i) => {
      const r = data.items[i];
      if (!r) { el.hidden = true; return; }
      el.hidden = false;
      const b = $('b', el), small = $('small', el);
      if (b) b.textContent = r.title;
      if (small) {
        small.textContent = [r.time, r.kind, r.note].filter(Boolean).join(' · ');
      }
      /* 只有**真的是一件事**的行才挂主体号。
       *
       * 主体号是 `entityId`，不是 `id`（`id` 是这一行审计记录自己的号）。
       * 但光有 `entityId` 不够：审计里「登录了优活」这类事件的 entity 是
       * **一个人**（`elder-vc9b…` / `daughter-vc9b…`），不是任务。实测四行里
       * 三行是这样，而它们照样长出了「看看这件事的经过」，点下去得到
       * 「没有找到这件事的记录。」——一个走到死胡同的动作。
       *
       * 设计一二没有这个问题，因为它读的 `/v2/elder/activity` 由**后端**
       * 把非任务事件的 `about_id` 置空了；`/api/v1/records` 给的是原始 entity。
       * 所以这里拿 `/v2/tasks` 的 id 集合对一遍：**按查得到，不按前缀猜**。
       *
       * `elder.js:1225` 那句话说的就是这件事：「一个看起来能按、按了没反应的
       * 控件比一行纯文字糟——它让人以为是坏的。」
       */
      if (r.entityId && taskIds.has(r.entityId)) el.dataset.taskId = r.entityId;
      else delete el.dataset.taskId;
    });

    fillTimeline(page, data.items.slice(0, 3).map((r) => ({
      t: r.time || '', n: r.title, s: r.note || r.kind, done: true,
    })), '还没有办过事');

    const meta = $('.identity-meta', page);
    if (meta) {
      meta.textContent = data.total
        ? `一共 ${data.total} 条 · 刚刚已更新`
        : '还没有记录';
    }
    if (data.items[0]) lastSpoken = `${data.items[0].title}。${data.items[0].note || ''}`;
  }

  /* ---- 家人 --------------------------------------------------------------- */

  async function loadFamily() {
    const page = ws('family');
    if (!page) return;
    let data;
    try {
      data = await api('/api/v1/contacts');
    } catch (e) { trouble(e, '家人联系方式'); return; }

    const meta = $('.identity-meta', page);
    if (meta) {
      meta.textContent = data.count
        ? `${data.count} 位家人可以联系`
        : '还没有登记家人';
    }

    // 三条分支换成真的联系人。`phone` 后端永远回 null（`actors` 表没有这一列），
    // 所以这里**不显示号码**——写一个编出来的号码，她真按下去会拨错人。
    const branches = $$('.family-branch', page);
    branches.forEach((el, i) => {
      const c = data.items[i];
      if (!c) { el.hidden = true; return; }
      el.hidden = false;
      const b = $('b', el), small = $('small', el);
      if (b) b.textContent = c.name;
      if (small) {
        small.textContent = c.primary ? `${c.role} · 优先联系` : c.role;
      }
    });

    const core = $('.family-core span', page);
    if (core && data.items.length) {
      const first = data.items.find((c) => c.primary) || data.items[0];
      core.textContent = `重要的事，先找${first.name}`;
    }
  }

  /* ---- 我的 --------------------------------------------------------------- */

  function markSegment(seg, word) {
    $$('.seg-btn', seg).forEach((b) => {
      b.classList.toggle('active', b.textContent.trim() === word);
    });
  }

  async function loadSettings() {
    const page = ws('mine');
    if (!page) return;
    let s;
    try {
      s = await api('/api/v1/settings');
    } catch (e) { trouble(e, '您的设置'); return; }
    speechRate = Number(s.voiceSpeed) || 0.88;
    const speed = $('.segmented[data-seg="speed"]', page);
    const font = $('.segmented[data-seg="font"]', page);
    if (speed) markSegment(speed, nearest(SPEED, s.voiceSpeed));
    if (font) markSegment(font, nearest(FONT, s.fontScale));
    applyFont(Number(s.fontScale) || 1.25);

    const meta = $('.identity-meta', page);
    if (meta) {
      meta.textContent = s.saved ? '这是您自己调过的' : '现在是默认设置';
    }
  }

  /* 字号真的作用在屏幕上。只调根字号，版式跟着 rem 走；
   * 不动 `--` 之外的任何东西，免得和这一页自己的动画打架。 */
  function applyFont(scale) {
    document.documentElement.style.setProperty('--e3-font-scale', String(scale));
  }

  function readSegments() {
    const page = ws('mine');
    const pick = (sel, table, fallback) => {
      const seg = $(sel, page);
      const on = seg && $('.seg-btn.active', seg);
      const word = on ? on.textContent.trim() : '';
      return table[word] !== undefined ? table[word] : fallback;
    };
    return {
      voiceSpeed: pick('.segmented[data-seg="speed"]', SPEED, 0.88),
      fontScale: pick('.segmented[data-seg="font"]', FONT, 1.25),
    };
  }

  /* ---- 说话 ---------------------------------------------------------------
   *
   * 会话与对话走的是和设计一完全相同的两个端点。 */
  let sessionId = null;
  async function ensureSession() {
    if (sessionId) return sessionId;
    const s = await api('/v2/sessions', {method: 'POST', body: JSON.stringify({})});
    sessionId = s.session_id;
    return sessionId;
  }

  /* ---- 玻璃盒：她说的那件事，到底要动什么 --------------------------------------
   *
   * 这是这个项目三项核心创新之一，而设计三**整个没有**。此前她说「帮我交水费」，
   * 屏幕上只有一句回话；要办的是哪一笔、多少钱、谁来决定、能不能撤销、
   * 会用到她哪些信息——一个字都没有。设计一二那一屏有一整张卡（`glassbox.js`），
   * 走的是 `POST /v6/tasks/{id}/glass-box`，而这一版一次都没调过。
   *
   * 「先复述金额再执行」那一步不用另接：她复述的那句话仍然走 `send()` →
   * `/v2/chat`，后端自己判。缺的从来只是**把这张卡摆出来**。
   *
   * 用动态 `import()`：`glassbox.js` 是 ES 模块，而这份接线是 IIFE，
   * 顶层 `import` 用不了。渲染函数**不重写一份**——同一张卡两套画法，
   * 正是这个项目栽过的那件事。
   */
  function ensureReliance() {
    let host = $('#e3Reliance');
    if (host) return host;
    const anchor = $('#e3Actions') || ensureStatus();
    if (!anchor) return null;
    host = document.createElement('div');
    host.id = 'e3Reliance';
    host.className = 'e3-reliance';
    host.hidden = true;
    anchor.insertAdjacentElement('afterend', host);
    return host;
  }

  async function showGlassBox(heard, data) {
    const host = ensureReliance();
    if (!host) return;
    // 没有任务就把上一张收掉。留着的话，她说完下一句还看着上一件事的卡。
    if (!data || !data.task_id) {
      host.replaceChildren();
      host.hidden = true;
      return;
    }
    try {
      const box = await api(
        `/v6/tasks/${encodeURIComponent(data.task_id)}/glass-box`,
        {method: 'POST', body: JSON.stringify({heard_text: heard})});
      const {renderGlassBox} = await import('/static/glassbox.js');
      renderGlassBox(host, box.card, box.preview);
      host.hidden = false;
    } catch (_) {
      // 取不到就不摆。**空着**比摆一张半张的卡好：这张卡的全部价值在于
      // 它说的每一行都是真的。
      host.replaceChildren();
      host.hidden = true;
    }
  }

  /** 让这一句按她的档案说出来。
   *
   * 设计一二每收到一句 agent 的话都过一遍 `/v6/interaction/plan`：由后端按
   * 风险等级、她最近重试了几次、这件事可不可逆，决定**屏幕上写什么、
   * 念出来念什么、用多快的语速**。设计三此前一次都没调过，
   * 于是高风险那句话和闲聊用同一个语速、同一种措辞。
   *
   * 取不到就原样说。这一层是**加工**，不是通路：它失败不该让她听不到回话。
   */
  async function adapt(message, riskLevel) {
    try {
      const ids = await YH.ready();
      return await api('/v6/interaction/plan', {
        method: 'POST',
        body: JSON.stringify({
          elder_id: ids.elderId, message, options: [],
          risk_level: Number(riskLevel || 1), asr_confidence: 1.0,
          recent_retries: 0, reversible: Number(riskLevel || 1) < 4,
        }),
      });
    } catch (_) {
      return {visual_text: message, speak_text: message, speech_rate: speechRate};
    }
  }

  async function send(text) {
    const what = String(text || '').trim();
    if (!what) return;
    say('让我想一想……', 'good');
    try {
      const data = await api('/v2/chat', {
        method: 'POST',
        body: JSON.stringify({session_id: await ensureSession(), text: what}),
      });
      // 高风险的那几句要慢下来、要换说法——由后端决定，不在这里另写一套。
      const plan = await adapt(data.message, (data.ui && data.ui.risk_level) || 1);
      say(plan.visual_text || data.message, YH.toneOf(data));
      lastSpoken = plan.visual_text || data.message;
      if (data.ui && data.ui.speak) {
        const was = speechRate;
        if (plan.speech_rate) speechRate = Number(plan.speech_rate);
        speakOut(plan.speak_text || data.message);
        speechRate = was;      // 只影响这一句，不改她存的设置
      }
      showGlassBox(what, data);
      // 办完一件事，今天那一屏就该跟着变。
      loadToday();
      loadRecords();
    } catch (e) {
      trouble(e, '这句话');
    }
  }

  /* ---- 接线 --------------------------------------------------------------- */

  /** 把交付包绑在这个元素上的匿名监听整个摘掉，返回替换后的新节点。 */
  function stripListeners(el) {
    if (!el) return null;
    const fresh = el.cloneNode(true);
    el.replaceWith(fresh);
    return fresh;
  }

  /** 摊开一件事的经过。
   *
   * 读的是 `/v2/tasks`（`TaskView`），**不是 `/v2/audit`**——这是那条
   * 「取证与叙事是两个模型」的落地：审计链留给 `/judge`，消费者面读任务本身。
   * 服务端已按调用者把列表收窄到她自己的任务，所以在客户端按 id 找是安全的。
   *
   * 视图模型和渲染都用 `task-detail.js` 那一份，不另写：同一件事两套说法，
   * 是这个项目栽过的那件事。
   */
  async function showTaskDetail(taskId) {
    const host = ensureReliance();
    if (!host) return;
    try {
      const tasks = await api('/v2/tasks?limit=100');
      const task = (tasks || []).find((t) => t.id === taskId);
      const {renderTaskDetail, taskDetailViewModel} =
        await import('/static/task-detail.js');
      renderTaskDetail(host, task ? taskDetailViewModel(task) : null);
      host.hidden = false;
      offer([{label: '收起来', run: async () => {
        host.replaceChildren();
        host.hidden = true;
        offer([]);
      }}]);
    } catch (e) {
      host.replaceChildren();
      host.hidden = true;
      trouble(e, '这件事的经过');
    }
  }

  /* 待办气泡：先问，再做。
   *
   * 用 `/v2/reminders/{id}/{action}`，和设计一走的是同一条路
   * （`elder.js::reminderAction`），状态词也用同一批。
   */
  async function reminderAction(id, action, word) {
    try {
      const data = await api(`/v2/reminders/${encodeURIComponent(id)}/${action}`,
                             {method: 'POST', body: JSON.stringify({})});
      offer([]);
      say(data.message || `好，记下了：${word}。`, YH.toneOf(data));
      speakOut(data.message || word);
      await loadToday();
      loadRecords();
    } catch (e) {
      offer([]);
      trouble(e, '这一条');
    }
  }

  function wire() {
    /* 左边那条时间轴上的每一颗气泡。
     *
     * 待办：问一句再改。一整块椭圆点一下就把事情标成办好了，手一抖就改了记录，
     * 而她看不出刚才发生过什么——所以两个动作各是一个写着字的按钮。
     * 记录：念给她听。这一版最常见的困难是看不清，「再说一遍」也是为此存在的。
     */
    document.addEventListener('click', (e) => {
      const node = e.target.closest('.story-node, .record-event, .family-branch');
      if (!node) return;
      const id = node.dataset.reminderId;
      const spoken = node.dataset.speak
        || (node.textContent || '').replace(/\s+/g, ' ').trim();
      if (node.dataset.act === 'reminder' && id) {
        const title = ($('.n', node) || {}).textContent || '这一条';
        say(`${title} —— 要记一下吗？`, 'warning');
        offer([
          // 动作名是 `complete` 不是 `done`——`/v2/reminders/{id}/done` 是 404。
          // 第一版写的就是 `done`，而「点气泡」那一层的扫描只点到第一步，
          // 看不到第二步会 404：一个按钮点下去报错，而巡检说这一屏没有死控件。
          {label: '我知道了', run: () => reminderAction(id, 'acknowledge', title)},
          {label: '已经办好了', run: () => reminderAction(id, 'complete', title)},
          {label: '先不改', run: async () => { offer([]); say('好，先不改。'); }},
        ]);
        return;
      }
      offer([]);
      if (spoken) { say(spoken); speakOut(spoken); lastSpoken = spoken; }
      // 记录行还带着这件事的主体号时，多给一个「看看经过」。
      // 念一遍只回答「这条写的是什么」，回答不了「这件事后来怎么样了」——
      // 设计一二点一条记录会摊开整段经过（`task-detail.js`），设计三此前没有。
      if (node.dataset.taskId) {
        const tid = node.dataset.taskId;
        offer([{label: '看看这件事的经过', run: () => showTaskDetail(tid)}]);
      }
    });

    // 常用说法：按钮上写什么就说什么，不另建一张映射表。
    $$('.quick-chip').forEach((chip) => {
      chip.addEventListener('click', () => once(chip, () => send(chip.textContent.trim())));
    });

    /* 「我的 · 常用服务」那四行。
     *
     * 它们写的本来就是**一句可以说出口的话**（「今天吃药了吗」「药还够吃吗」
     * 「上次的血压」「找无忧伴聊聊」），所以直接当成她说了这句话送进对话——
     * 不另建一张「这一行对应哪个接口」的映射表。那张表一旦存在，
     * 屏幕上的字和它真的会做的事就有了两个来源。
     *
     * 交付包里它们是 `<div class="service-row">`，不是按钮：看起来能点、
     * 实际不能，连键盘也够不着。补上 role 与 tabindex。
     */
    $$('.service-row').forEach((row) => {
      const what = ($('b', row) || {}).textContent || '';
      if (!what) return;
      row.setAttribute('role', 'button');
      row.setAttribute('tabindex', '0');
      const go = () => {
        // 切回「今天」再说：回答会写在状态行上，而状态行在那一屏。
        const dock = $('.dock [data-page="today"]');
        if (dock) dock.dispatchEvent(new PointerEvent('pointerup', {bubbles: true}));
        setTimeout(() => send(what), 400);
      };
      row.addEventListener('click', go);
      row.addEventListener('keydown', (e) => {
        if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); go(); }
      });
    });

    // 麦克风。交付包那个「假装在听」的监听先摘掉。
    const orb = stripListeners($('#voiceOrb'));
    const SR = window.SpeechRecognition || window.webkitSpeechRecognition;
    const caption = $('.voice-caption b');
    const capWord = caption ? caption.textContent : '';
    if (orb) {
      if (SR) {
        const rec = new SR();
        rec.lang = 'zh-CN';
        rec.interimResults = false;
        rec.maxAlternatives = 3;
        let listening = false;
        rec.onstart = () => {
          listening = true;
          if (caption) caption.textContent = '正在听，请慢慢说…';
          say('正在听，请慢慢说。一次只说一件事也可以。', 'good');
        };
        rec.onresult = (e) => send(e.results[0][0].transcript);
        rec.onend = () => {
          listening = false;
          if (caption) caption.textContent = capWord;
        };
        /* 这六句话照抄 `elder.js` 的 `RECOGNITION_TROUBLE`，不另写一份：
         * Web Speech 的错误枚举是英文标识符，不能给老人看，而「请再说一遍」
         * 在权限被拒时说一百遍也不会成功。 */
        const TROUBLE = {
          'not-allowed': '我没有拿到麦克风的许可。您可以用打字说，或者让家人帮您在设置里打开麦克风权限。',
          'service-not-allowed': '这台电脑暂时不让我用语音。您可以用打字说。',
          'audio-capture': '我找不到麦克风。您可以用打字说。',
          'no-speech': '我没有听到声音。请离麦克风近一点，再按一下慢慢说。',
          'network': '网络不太好，语音没送出去。您可以用打字说，或者等一会儿再试。',
          'aborted': '刚才那次听被打断了。您可以再按一下。',
        };
        rec.onerror = (e) => {
          if (caption) caption.textContent = capWord;
          say(TROUBLE[e.error] || '语音没能用起来。您可以用打字说，我一样能办。', 'bad');
        };
        orb.addEventListener('click', () => {
          // 正在听的时候再按一下，`start()` 会抛 InvalidStateError——
          // 而重复按恰恰是最常见的操作。停下来当作「说完了」。
          if (listening) { try { rec.stop(); } catch (_) {} return; }
          try { rec.start(); } catch (_) { say('刚才那一下没接上，请再按一次。', 'warning'); }
        });
      } else {
        // 没有语音识别（Firefox 就没有）。按下去要说清楚，不能假装在听。
        orb.addEventListener('click', () => {
          say('这个浏览器不支持语音输入。请按下面的「用打字说」，我一样能办。', 'warning');
          const k = $('#keyboardEntry');
          if (k) k.focus();
        });
      }
    }

    // 打字说
    const keyboard = $('#keyboardEntry');
    if (keyboard) {
      keyboard.addEventListener('click', () => {
        let box = $('#e3Composer');
        if (!box) {
          box = document.createElement('form');
          box.id = 'e3Composer';
          box.className = 'e3-composer';
          box.innerHTML = '<input id="e3Text" type="text" autocomplete="off" '
            + 'placeholder="想办什么，写一句就行" aria-label="打字告诉优活">'
            + '<button type="submit">说给优活</button>';
          keyboard.insertAdjacentElement('afterend', box);
          box.addEventListener('submit', (e) => {
            e.preventDefault();
            const input = $('#e3Text');
            const text = input.value;
            input.value = '';
            send(text);
          });
        }
        box.hidden = false;
        const input = $('#e3Text');
        if (input) input.focus();
      });
    }

    // 记录页那三个工具
    const repeat = $('#repeatLast');
    if (repeat) {
      repeat.addEventListener('click', () => {
        if (!lastSpoken) { say('还没有可以再念一遍的事。', 'warning'); return; }
        say(lastSpoken, 'good');
        speakOut(lastSpoken);
      });
    }
    const back = $('#stepBack');
    if (back) {
      /* 「返回上一步」在这一页没有对应的后端动作——它不是撤销一笔事务
       * （那要走 `/v2/chat` 说「取消任务」，而且只对**正在办**的那一件有效）。
       * 所以这里做它字面的意思：回到上一个看过的分区。
       * 不把它接成「取消任务」：一个写着「返回上一步」的按钮撤掉一笔缴费，
       * 是这一整轮在修的那类缺陷。 */
      back.addEventListener('click', () => {
        const prev = history.state && history.state.e3prev;
        const target = prev || 'today';
        const dock = $(`.dock [data-page="${target}"]`);
        if (dock) dock.dispatchEvent(new PointerEvent('pointerup', {bubbles: true}));
        say(`回到「${target === 'today' ? '今天' : '上一页'}」。`, 'good');
      });
    }
    const refresh = $('#refreshRecords');
    if (refresh) {
      refresh.addEventListener('click', () => once(refresh, async () => {
        await loadRecords();
        say('记录已经重新读过了。', 'good');
      }));
    }

    // 家人：联系家人 = 把联系人念出来，**不是**紧急呼叫。
    // 一个写着「联系家人」的按钮触发 SOS，是把破坏性动作挂在别的标签下面。
    const contact = $('#contactFamily');
    if (contact) {
      contact.addEventListener('click', () => once(contact, async () => {
        try {
          const data = await api('/api/v1/contacts');
          if (!data.count) { say('还没有登记家人。让家人在家人端加一下。', 'warning'); return; }
          const who = data.items.map((c) => `${c.name}（${c.role}）`).join('、');
          say(`可以联系的家人：${who}。要现在叫人来，请说「我需要帮忙」。`, 'good');
          speakOut(`可以联系的家人有${who}`);
        } catch (e) { trouble(e, '家人联系方式'); }
      }));
    }

    // 我的：保存。交付包那个「假装保存」的监听先摘掉。
    const save = stripListeners($('#savePref'));
    if (save) {
      const word = save.textContent;
      save.addEventListener('click', () => once(save, async () => {
        const body = readSegments();
        try {
          const saved = await api('/api/v1/settings',
                                  {method: 'PUT', body: JSON.stringify(body)});
          // 以**返回值**为准，不是以我传出去的值为准：服务端会夹范围。
          speechRate = Number(saved.voiceSpeed) || 0.88;
          applyFont(Number(saved.fontScale) || 1.25);
          markSegment($('.segmented[data-seg="speed"]', ws('mine')),
                      nearest(SPEED, saved.voiceSpeed));
          markSegment($('.segmented[data-seg="font"]', ws('mine')),
                      nearest(FONT, saved.fontScale));
          // 交付包那句是「✓ 已保存」。勾号是**图标位置上的字符**，
          // 这个项目不许拿字符当系统图标（`test_no_emoji_as_icons` 守的就是它）。
          save.textContent = '已经保存';
          setTimeout(() => { save.textContent = word; }, 1500);
          say('记住了。下次打开还是这样。', 'good');
          speakOut('记住了');
        } catch (e) {
          // 失败时**不许**出现「已保存」。
          trouble(e, '这次设置');
        }
      }));
    }

    wireDataTools();

    // 字号选一下就立刻看得到，不用等保存——但保存前不写库。
    const fontSeg = $('.segmented[data-seg="font"]', ws('mine'));
    if (fontSeg) {
      fontSeg.addEventListener('click', () => {
        applyFont(readSegments().fontScale);
      });
    }

    // 无忧伴：后端按**每一句话**判定要不要进陪伴（`companion.wants_companion`），
    // 没有一个可以切换的持久状态。所以点它就真的说一句进入陪伴的话。
    const comp = $('#modeCompanion');
    if (comp) {
      comp.addEventListener('click', () => send('陪我说说话'));
    }

    // 记住上一个分区，给「返回上一步」用。
    $$('.dock [data-page]').forEach((btn) => {
      btn.addEventListener('pointerdown', () => {
        const now = $('.workspace.active');
        history.replaceState({e3prev: now ? now.dataset.workspace : 'today'}, '');
      });
    });

    // 切到哪一页就读哪一页的数据。
    const LOADERS = {today: loadToday, records: loadRecords,
                     family: loadFamily, mine: loadSettings};
    $$('.dock [data-page]').forEach((btn) => {
      btn.addEventListener('pointerup', () => {
        const fn = LOADERS[btn.dataset.page];
        if (fn) setTimeout(fn, 260);   // 让切页动效先起来，再填数据
      });
    });
  }

  async function boot() {
    wire();
    // 设置先读：字号语速要在别的内容画上去之前生效。
    await loadSettings();
    await loadToday();
    loadRecords();
    loadFamily();
  }

  boot().catch((e) => {
    // 这一条罩着登录。登录失败的时候屏幕上必须有话，否则整页是一片默认文案，
    // 看起来像是「数据就是长这样」。
    say(errorWords(e, '优活').text, 'bad');
  });
})();
