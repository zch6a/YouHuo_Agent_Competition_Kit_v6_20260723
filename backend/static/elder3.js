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
  //: `noStop` / `memoryWords` 搬到了 `common.js`：`elder.js`（服务 /elder 与
  //: /elder2）这一轮补上同意这一整块，两边必须用同一句话。名字不变，
  //: 所以这个文件下面的代码一个字都没动。
  const {api, once, errorWords, noStop, memoryWords} = YH;

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

  /* 状态行要落在**当前那一屏**里。
   *
   * 它原先固定插在 `.voice-caption` 后面，而那一处在 `today` 这个 `.workspace`
   * 里；`/elder3` 换页是把四个 workspace **横向平移**。闸门量出来
   * （`test_the_receipt_is_visible_in_every_panel`，1280×800 与 1440×900 都一样）：
   *
   *     ◉今天 y=495 看得见 · ◇记录 / ○家人 / ⌁我的 **看不见**
   *
   * 而 `say()` 是这一页对老人说的每一句「现在怎么了」的唯一出口——在那三页上
   * 按一条记录、按一个动作，她一个字都看不到，只剩语音合成那一路。
   *
   * 今天页那一处**不能动**：`elder3-wiring.css` 里记着它是量过四种改法之后
   * 选定的（状态行和动作行故意排在麦克风下面，「只有这一种在长短两态下都是
   * 零重叠、零遮挡」）。所以只给其余三页另找位置。 */
  function activeWorkspace() {
    return $('.workspace.active') || $('.workspace');
  }

  /* away 态把状态行和动作行装进**同一个盒子**。
   *
   * 上两版是让它们各自绝对定位，然后靠「猜上一行多高」去错开：
   * 先用 `translateY(100%)`（把动作行推到了底栏上），再用 `:has()` 加固定 68px
   * （那是在猜高度）。装进一个盒子之后，两行在盒内**正常流式排列**，
   * 高度多少都不用管。
   *
   * 盒子空着时不该挡东西：盒子 `pointer-events:none`，两行各自 `auto`。 */
  function awayBox(ws) {
    let box = ws.querySelector(':scope > .e3-away');
    if (!box) {
      box = document.createElement('div');
      box.className = 'e3-away';
      ws.appendChild(box);
    }
    return box;
  }

  function statusHost() {
    const ws = activeWorkspace();
    const onToday = !!ws && ws.dataset.workspace === 'today';
    if (onToday) {
      const cap = $('.voice-caption');
      if (cap) return {anchor: cap, mode: 'afterend', away: false};
    }
    return ws ? {anchor: awayBox(ws), mode: 'append', away: true} : null;
  }

  function ensureStatus() {
    const spot = statusHost();
    if (!spot) return statusEl;
    if (!statusEl) {
      statusEl = document.createElement('p');
      statusEl.id = 'e3Status';
      statusEl.setAttribute('role', 'status');
      statusEl.setAttribute('aria-live', 'polite');
    }
    //: `.e3-status-away` 只在不是今天页时挂——它给出一个压在底栏上方的位置。
    statusEl.className = 'e3-status' + (spot.away ? ' e3-status-away' : '');
    const want = spot.mode === 'append' ? spot.anchor : spot.anchor.parentElement;
    if (statusEl.parentElement !== want || !statusEl.isConnected) {
      if (spot.mode === 'append') spot.anchor.appendChild(statusEl);
      else spot.anchor.insertAdjacentElement('afterend', statusEl);
      //: 动作行贴在状态行之后。`offer()` 会复用已有的 `#e3Actions`，
      //: 所以状态行搬家之后要把它带过去，不然按钮留在上一屏里。
      const row = $('#e3Actions');
      if (row) statusEl.insertAdjacentElement('afterend', row);
    }
    return statusEl;
  }

  /* 换页之后，上一屏那一句要收回去。
   *
   * 判据用**位置**不用时序：如果它现在待在一个**不是当前**的 workspace 里，
   * 它就属于一屏她已经离开的界面。和 `/family3` 的 `ensureNotice()` 同一条规则。
   * 不能无条件清——`say()` 常常紧跟在换页之后（比如「☎ 联系家人」），
   * 而观察器回调是任务末尾的微任务，无条件清会把刚写的那句抹掉；
   * 走到这里时它已经在当前那一屏里了。 */
  (() => {
    const spots = $$('.workspace');
    if (!spots.length) return;
    const obs = new MutationObserver(() => {
      if (!statusEl || !statusEl.isConnected) return;
      const ws = statusEl.closest('.workspace');
      const cur = activeWorkspace();
      if (ws && cur && ws !== cur) {
        statusEl.textContent = '';        //: `.e3-status:empty { display:none }`
        const row = $('#e3Actions');
        if (row) row.remove();            //: 动作按钮也不能留在上一屏
      }
    });
    spots.forEach((w) => obs.observe(w, {attributes: true,
                                        attributeFilter: ['class', 'hidden']}));
  })();
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

  /* 屏幕上的「几点」一律是北京时间，不是设备时间。
   *
   * 后端凡是要读出墙上时间的地方都先过 `local_now()`
   * （`youhuo/utils.py`，`LOCAL_TIMEZONE = "Asia/Shanghai"`），所以
   * `/api/v1/agenda` 下发的 `time` 是北京时间的钟点。这一屏的「下一件」卡片和
   * 时间轴用的就是那个字段——那一半本来就是对的。错的是身份岛上那一行「现在」
   * 和最上面那句问候：它们原先走 `new Date().getHours()`，也就是**设备时区**。
   *
   * 实测（真接口 + Node 按 TZ 驱动，后端墙上时间 2026-08-25 19:49）：
   *
   *     设备 Asia/Shanghai     晚上好   2026年08月25日 周二 · 19:49
   *     设备 UTC               中午好   2026年08月25日 周二 · 11:49
   *     设备 America/New_York  早上好   2026年08月25日 周二 · 07:49
   *
   * 而同一屏的「下一件」写着后端给的 14:00。也就是说在一台不是 UTC+8 的设备上，
   * 这一屏一边说「早上好 · 07:49」，一边说「下一件 · 14:00」——两个时间来自
   * 两个时区，而屏幕上没有一处会说这件事。
   */
  const WALL_CLOCK_ZONE = 'Asia/Shanghai';

  /** 一个时刻在**北京时间**里的年月日时分（都是补零后的字符串）。
   *
   * 用 `formatToParts` 而不是拼串：年月日和时分出自同一次格式化，不会出现
   * 「日期来自一个时区、钟点来自另一个」的错位。`hourCycle: 'h23'` 是实测选的
   * ——`hour12: false` 在部分引擎上把午夜给成 `24`。
   */
  function wallClock(value) {
    const bag = {};
    new Intl.DateTimeFormat('en-US', {
      timeZone: WALL_CLOCK_ZONE,
      hourCycle: 'h23',
      year: 'numeric', month: '2-digit', day: '2-digit',
      hour: '2-digit', minute: '2-digit',
    }).formatToParts(value instanceof Date ? value : new Date(value))
      .forEach((part) => { bag[part.type] = part.value; });
    return bag;
  }

  function greeting() {
    const h = Number(wallClock(new Date()).hour);
    if (h < 6) return '夜里好';
    if (h < 11) return '早上好';
    if (h < 13) return '中午好';
    if (h < 18) return '下午好';
    return '晚上好';
  }

  function stamp(d) {
    const at = wallClock(d);
    /* 星期也得按北京时间取，否则跨日的那几个小时里日期和星期会对不上。
     * `weekday: 'narrow'` 在 zh-CN 下正是「日一二三四五六」那一套（实测
     * 2026-08-25 给「二」），和原先那张手写表一个字不差，但它跟着 timeZone 走。 */
    const week = new Intl.DateTimeFormat('zh-CN', {
      timeZone: WALL_CLOCK_ZONE, weekday: 'narrow',
    }).format(d instanceof Date ? d : new Date(d));
    return `${at.year}年${at.month}月${at.day}日 `
         + `周${week} · ${at.hour}:${at.minute}`;
  }

  /* `ask` 为假时只刷新这一屏，**不追问**待确认的用药和记忆。
   *
   * 她刚说完一句话、屏幕上正写着后端的回话（可能是一句风险 4 的
   * 「请您把金额说一遍」），这时候再 `say()` 一个不相干的问句，
   * 等于把她该念的那句话和该按的按钮一起换掉。
   *
   * 第 473 行那段注释在记忆那条路上把同一件事写过一遍：
   * 「回执在屏幕上停不到半秒就被下一个问句整条盖掉…她看不到自己
   * 刚才那一下的结果」，并且引了这一页左边那句「一次只问一件事 ·
   * 不连续追问」。当时只改了记忆那条路，语音这条主路照旧。
   */
  async function loadToday({ask = true} = {}) {
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

    /* 等她点头的事，一次只问一件。
     *
     * 这一页左边那三条承诺里第一条就是「一次只问一件事 · 不连续追问」，
     * 而待确认的药和待确认的记忆共用同一条状态行、同一排动作按钮——
     * 两个都问，后问的那个会把前一个连问题带按钮一起盖掉，
     * 于是屏幕上只剩下第二件事，而第一件**看起来像没有发生过**。
     *
     * 药排在前面：那是身体的事，还带着时间点；记忆是偏好，晚一轮问不损失什么。
     */
    if (!ask) return;
    const asked = await askAboutPendingMedication();
    if (!asked) await askAboutPendingMemory();
  }

  /** 家人加的药，等她点头。
   *
   * 设计一那边渲染成待办列表里的一张卡；这一版的今天页只有三个位置固定的
   * `.story-node`（位置由 CSS 的 n1/n2/n3 决定，动画脚本还持有它们），
   * 塞不进第四条。所以走**状态行 + 动作行**——那正是 `offer()` 的用途，
   * 也是她按完麦克风眼睛所在的位置。
   *
   * 一次只问一件。三份待确认的药摆六个按钮，就不是「问一句」了。
   *
   * @returns 这一轮有没有**真的问出一句**。调用方靠它决定要不要接着问记忆——
   *          两个都问会把状态行和动作行互相盖掉。
   */
  async function askAboutPendingMedication() {
    let data;
    try {
      data = await api('/api/v1/medications/pending');
    } catch (e) {
      // 安静地跳过。这是**额外**的一块，让它的失败盖掉今天的安排不划算。
      return false;
    }
    if (!data.count) return false;

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
    return true;
  }

  /* ---- 优活要记住一件事，得她本人点头 ------------------------------------------
   *
   * 这是这个产品的招牌能力之一，后端四条端点早就跑得通：
   *
   *     GET  /api/v1/memories                    生效的 + 待她点头的
   *     POST /api/v1/memories/{id}/approve       她同意记住
   *     POST /api/v1/memories/{id}/decline       她不同意
   *     POST /api/v1/memories/{id}/forget        撤回一条已经记住的
   *
   * 而**全仓没有任何界面在调它们**，所以这条流程对用户等于不存在：家人提的
   * 那一条永远停在待确认，她看不见、也点不了，而且不报任何错——两边界面都正常。
   * 这和「家属补的药停在待确认」是同一个形状、同一处缺口，只是没人发现第二处。
   *
   * ## 为什么摆在两屏上
   *
   *     今天 —— `pending`：等她决定的事，走状态行 + 动作行，一次只问一件
   *     我的 —— `items`：已经生效的，逐条可以撤回，两步
   *
   * 后端把这两段分开返回（`items` / `pending`），理由写在它自己的注释里：
   * 「它已经记住了」和「它想记住」混在一起看起来是同一件事，而后者还没有
   * 得到同意。所以这里也不合并——等她决定的事属于「今天」，那是她每天会看的
   * 一屏；已经生效的属于「我的」，那是她想起来才去翻的一屏。
   */

  /** 去掉末尾的句读再接着往下说。
   *
   * `purpose` 有时自带句号（「那天她不想被打扰。」），直接拼就成了
   * 「……不想被打扰。。」。这类并排重复这一页已经出过一次
   * （「这一件已经过点了。　已经过点了」），实测截图上看得清清楚楚。
   */
  /* `noStop` 与 `memoryWords` 在 `common.js` 里（见文件头那条 destructure）。 */

  /** 一条记忆摊开成一句她读得懂的话。
   *
   * `scope` 后端给的已经是中文（「只有我看得到」「家人能看到摘要」），
   * 这里**不再自己翻一遍**——同一个值两套说法是这个项目栽过的那件事。
   *
   * 三样都要说，因为「同意」要成立，她得知道自己在同意什么：
   * 记下来谁看得见、记多久、记它干什么。少任何一样，点头就只是点头。
   */
  /** 家人提议要记的一件事，等她点头。
   *
   * 和待确认的药同一个位置、同一个形状（状态行 + 两个写着字的按钮）：
   * 这一版的今天页只有三个位置固定的 `.story-node`，塞不进第四条。
   *
   * @returns 这一轮有没有真的问出一句。
   */
  async function askAboutPendingMemory() {
    let data;
    try {
      data = await api('/api/v1/memories');
    } catch (e) {
      // 安静地跳过，理由同上面那份药：这是**额外**的一块，
      // 让它的失败盖掉今天的安排不划算。
      return false;
    }
    if (!data.pendingCount) return false;

    const one = data.pending[0];
    const rest = data.pendingCount - 1;
    // `data.message` 里已经有件数（「有 2 件事想记下来，等您点头。」），
    // 后面不再补一句「还有 1 件」——同一个数说两遍，实测读起来像是三件事。
    say(`${data.message}这一件是「${one.key}」：${noStop(one.detail)}。`
        + `${memoryWords(one, true)}。`, 'warning');

    const decide = async (approve) => {
      try {
        const said = await api(
          `/api/v1/memories/${encodeURIComponent(one.id)}/${approve ? 'approve' : 'decline'}`,
          {method: 'POST', body: JSON.stringify({})});
        say(said.message, 'good');
        speakOut(said.message);
        /* 下一件**要她自己再点一下**，不自动接上。
         *
         * 第一版这里是 `loadToday()`，照抄待确认用药那一段。实测：她按下
         * 「可以记住」，回执「好，我记住「看电视的音量」了」在屏幕上停不到
         * 半秒就被下一个问句整条盖掉——按钮还是那两个，问的却已经是另一件事。
         * 也就是说她**看不到自己刚才那一下的结果**，而下一句看起来像是
         * 刚才那一下没成功。
         *
         * 这一页左边写着「一次只问一件事 · 不连续追问」。自动接上正是连续追问。
         */
        offer(rest > 0
          ? [{label: `还有 ${rest} 件，接着看`, run: () => askAboutPendingMemory()}]
          : []);
      } catch (e) {
        // 不印 `e.message`：那一层可能是「Failed to fetch」。
        offer([]);
        trouble(e, '这一条');
      }
    };
    offer([
      {label: '可以记住', run: () => decide(true)},
      {label: '不用记', run: () => decide(false)},
    ]);
    return true;
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
   *
   * 第五条 `#e3Memories`（「我答应让优活记住的事」）是这一轮补的，
   * 走 `/api/v1/memories` 与 `…/{id}/forget`。它和 `#e3MyData` 不是一回事：
   * 后者数的是**优活攒了多少条数据**（心情 3 条、身体数据 12 条），
   * 前者列的是**她逐条点过头的长期记忆**，而且每一条都能收回。
   */

  /** 这一格，并且**把上一次的失败色调清掉**。
   *
   * 色调挂在格子上（`data-tone="bad"`），而这五个入口共用同一个格子：
   * 不清的话，一次断网之后，下一次成功摊开的清单会继续印着红边——
   * 一个办成了的事画成没办成，和反过来一样坏。
   * 每条路都从这里拿格子，所以清在这里一处就够，不用五处各记一次。
   */
  function dataOut() {
    const host = $('#e3DataOut');
    if (host) delete host.dataset.tone;
    return host;
  }

  function outText(host, words) {
    host.replaceChildren();
    const p = document.createElement('p');
    p.textContent = words || '';
    host.appendChild(p);
    host.hidden = !words;
  }

  /** 这一格里的「没成」。**换词，也换颜色。**
   *
   * 原先五处都是 `outText(host, errorWords(e, X).text)`：话是对的（走
   * `errorWords`，不会把 `Failed to fetch` 印上屏），但格子的样子一个像素都不变。
   * 实测断网之后点「我答应让优活记住的事」，左边那道竖线仍是墨绿
   * `rgb(73,111,96)`——和「删好了」同一个颜色。状态行那一侧早就分了三色
   * （`say(text, 'bad')`），这一格漏了。
   *
   * 不把色调写进 `outText()`：那个函数也印成功的回执（「删好了。」），
   * 一律染红就成了反过来的谎。
   */
  function outTrouble(host, error, what) {
    outText(host, errorWords(error, what).text);
    host.dataset.tone = 'bad';
    bringIntoView(host);
  }

  /** 把刚摊开的这一格滚到看得见的地方。
   *
   * 「我的数据」这五条住在 `.settings-grid` 里，而那是一个真的会溢出的容器
   * （交付包给它的是 `overflow:hidden`，接线改成 `auto` 才让这一整块够得着，
   * 说明写在 `elder3-wiring.css` 那一节）。她按下入口之后，答案渲染在按钮
   * **下面**——多半已经在这个容器的可视区之外：屏幕上一个像素都不动，
   * 看起来就是「按了没反应」。实测 1440×900：清单摊开后「不再记这条」落在
   * y=901，而视口只有 900。
   *
   * 只滚这一个容器，**不用 `scrollIntoView`**：那个会把每一层可滚的祖先都
   * 滚一遍，包括 `#app`（`position:fixed` + `overflow:hidden`），整版会错位。
   */
  function bringIntoView(host) {
    const box = host.closest('.settings-grid');
    if (!box) return;
    const over = host.getBoundingClientRect().bottom - box.getBoundingClientRect().bottom;
    if (over > 0) box.scrollTop = Math.min(box.scrollTop + over + 8, box.scrollHeight);
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
    } catch (e) { outTrouble(host, e, '今天的情况'); }
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
    } catch (e) { outTrouble(host, e, '心情记录'); }
  }

  async function showMyData() {
    const host = dataOut();
    try {
      const data = await api('/api/v1/privacy/data');
      outCounts(host, data.buckets, data.message || `一共 ${data.total} 条。`);
      /* 「存下来」——后端那句 `message` 一直这么承诺，而在这之前没有任何办法。
       * 实现在 `common.js`，三个界面共用一份；存的是这一屏本身，不是原始记录。
       * 理由写在 `elder.js::loadMyData` 那一处。
       */
      window.YouHuo.appendSaveMyData(host, data, speakOut);
    } catch (e) { outTrouble(host, e, '您的数据'); }
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
          outTrouble(host, e, '删除');
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
    } catch (e) { outTrouble(host, e, '要删的东西'); }
  }

  /** 「我答应让优活记住的事」——已经生效的那些，逐条可以收回。
   *
   * 只列 `items`（生效的）。等她点头的那些**不在这里做决定**：那是「今天」
   * 那一屏的事，混进来就又变成「它已经记住了」和「它想记住」摆在一起。
   * 但要提一句还有几件在等——不提的话这张单子上少了几条而她不知道为什么。
   *
   * @param notice 上一步的回执（收回成功那句）。有的话印在最前面：
   *               只印一句「我不再记着了」而不重列一遍，她看不出单子真的变了。
   */
  async function showMemories(notice) {
    const host = dataOut();
    let data;
    try {
      data = await api('/api/v1/memories');
    } catch (e) {
      outTrouble(host, e, '优活记着的事');
      return;
    }
    host.replaceChildren();
    if (notice) {
      const done = document.createElement('p');
      done.textContent = notice;
      host.appendChild(done);
    }
    const lead = document.createElement('p');
    lead.textContent = data.message || '';
    host.appendChild(lead);

    if (data.pendingCount) {
      /* `data.message` 里已经有件数了（「有 1 件事想记下来，等您点头。」）。
       *
       * 下面这一句只在**列表非空**时才能说「还有 N 件」（在这些之外）。
       * 列表为空时那么写会把同一个数说两遍，而「还有」还暗示存在一份
       * 并不存在的清单——实测屏幕上是：「有 1 件事想记下来，等您点头。
       * 还有 1 件想记的事，在「首页」那一屏等您点头。」
       *
       * `askAboutPendingMemory()` 上那段注释已经把这个坑写过一次
       * （「同一个数说两遍，实测读起来像是三件事」）。 */
      const waiting = document.createElement('p');
      waiting.className = 'meta';
      waiting.textContent = (data.count
        ? `还有 ${data.pendingCount} 件想记的事，`
        : '想记下来的那些，') + '在「今天」那一页等您点头。';
      host.appendChild(waiting);
    }

    (data.items || []).forEach((m) => {
      const row = document.createElement('div');
      row.className = 'e3-memory-row';
      const key = document.createElement('b');
      key.textContent = m.key;
      row.appendChild(key);
      const detail = document.createElement('p');
      detail.textContent = noStop(m.detail);
      row.appendChild(detail);
      const meta = document.createElement('p');
      meta.className = 'meta';
      meta.textContent = memoryWords(m, false);
      row.appendChild(meta);
      const drop = document.createElement('button');
      drop.type = 'button';
      drop.className = 'secondary';
      drop.textContent = '不再记这条';
      // 第一步**不发任何写请求**：它只是把要收回的那一条摊开给她看。
      // 所以这里不用 `once()`——它不往返后端，没有可连点两次的东西。
      drop.addEventListener('click', () => startForget(m));
      row.appendChild(drop);
      host.appendChild(row);
    });
    host.hidden = false;
    bringIntoView(host);
  }

  /** 收回一条已经记住的。**两步**，第二个按钮一开始不存在于 DOM 里。
   *
   * 和「删掉优活记下的这些」同一个规矩（见 `startErase()`）：一个一直摆在
   * 那里的「确认」会让人以为「点两下就没了」，而它在看到要收回的是哪一条
   * 之前根本不该存在——不是 disabled，也不是 hidden，是不存在。
   *
   * 「可撤回」是「同意」成立的前提，所以这一步和点头一样只有她本人做得了：
   * 后端对家人的令牌回 403（「只有老人本人可以决定不再记住这一条。」）。
   * 家人能替她忘掉，等于这份同意从来就不属于她。
   */
  function startForget(item) {
    const host = dataOut();
    host.replaceChildren();

    const lead = document.createElement('p');
    lead.textContent = `要让优活忘掉的是「${item.key}」：${noStop(item.detail)}。`;
    host.appendChild(lead);
    const why = document.createElement('p');
    why.className = 'meta';
    why.textContent = memoryWords(item, false);
    host.appendChild(why);
    const keep = document.createElement('p');
    keep.className = 'meta';
    keep.textContent = '忘掉之后优活不会再用这一条；别的记着的事不动。';
    host.appendChild(keep);

    const confirm = document.createElement('button');
    confirm.type = 'button';
    confirm.className = 'danger';
    confirm.textContent = `确认不再记「${item.key}」`;
    confirm.addEventListener('click', () => once(confirm, async () => {
      try {
        const done = await api(
          `/api/v1/memories/${encodeURIComponent(item.id)}/forget`,
          {method: 'POST', body: '{}'});
        // 重列一遍，回执放最前面。只印那一句的话，她看不出这一条
        // 真的从单子上下去了——「说办好了」和「办好了」是两件事。
        await showMemories(done.message);
        speakOut(done.message);
      } catch (e) {
        outTrouble(host, e, '这一条');
      }
    }));
    host.appendChild(confirm);

    const cancel = document.createElement('button');
    cancel.type = 'button';
    cancel.className = 'secondary';
    cancel.textContent = '还是记着吧';
    cancel.addEventListener('click', () => once(cancel, () => showMemories()));
    host.appendChild(cancel);
    host.hidden = false;
    bringIntoView(host);
  }

  function wireDataTools() {
    // 五个都往返后端，慢网络下连点两次的第二次会拿一个用过的令牌去删一份
    // 已经不存在的数据——后端会正确地拒绝，而屏幕上会闪一句错误，
    // 让人以为第一次没成功。所以一律包在 `once()` 里。
    [['#e3DayReport', showDayReport],
     ['#e3MoodReview', showMoodReview],
     ['#e3MyData', showMyData],
     ['#e3Memories', showMemories],
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
        /* `r.who` 排在钟点后面：「17:00 · 家人 · 服务 · …」。
         * 没有它的时候，她自己改字号和女儿远程改字号在这一屏上是
         * 逐字相同的两行「改了设置」——她分不出哪一行是自己按的。
         * 只有动作人会变的那些事件才有值，别的仍然是三段。 */
        small.textContent = [r.time, r.who, r.kind, r.note]
          .filter(Boolean).join(' · ');
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
      /* 「另有 N 条系统记录」——后端挡掉的那些要在这里露头。
       *
       * `/api/v1/records` 现在不把纯问答和内部管道（语义路由、定时器、
       * 环境采样这些）铺到这一屏上：她问十一句家常，这一屏 18 行里
       * 曾有 9 行写着「办了一件事」，而这一屏只渲染 4 行、时间线只用
       * 最前 3 行——那 3 行全是空话，「再说一遍」念的也是它。
       *
       * 但「挡掉」不能变成一个看不见的差额。后端给了 `machinery`，
       * 这一行是这一屏上唯一说总数的地方，所以并进来。
       * 那些记录一条没少，家人和评委那一侧（/v2/audit）照旧看得到全部。
       */
      const extra = Number(data.machinery) || 0;
      const tail = extra ? ` · 另有 ${extra} 条系统记录` : '';
      /* 这一屏只有 `events.length` 个槽（4 个），后端发来的往往比这多。
       *
       * 上面那句「挡掉不能变成一个看不见的差额」对**前端这一刀**同样成立：
       * 原先只交代了后端挡掉的 `machinery`，没交代这一屏画不下的那几条，
       * 于是她读到「一共 9 条」，眼前只有 4 行，中间 5 条无声无息。
       *
       * **这个数原先是错的。** 原先算 `items.length - events.length`，
       * 理由是「不去猜 `total` 和 `machinery` 的包含关系」。方向对，
       * 结果错：`items.length` 被请求里的 `?limit=20` 卡住，所以这个差额
       * 永远停在 16。两侧标定过（造的记录都确认落库）：
       *
       *     total=9   count=9    说「还有 5 条」   真值 5    对
       *     total=23  count=20   说「还有 16 条」  真值 19   少说 3
       *     total=89  count=20   说「还有 16 条」  真值 85   少说 69
       *
       * 包含关系是查得出来的，去读了生产端：`app_api.py:1801-1803`
       * 先按 kind 过滤（machinery 已被挡在外面）再 `total = len(items)`，
       * `:1822` 的 `machinery` 统的是被挡掉的那些。**两个数不相交，
       * `total` 不含 machinery**，所以拿 `total` 算差额是自洽的。
       *
       * `total` 自己还有个上限（取数窗口 `max(500,(limit+offset)*4)` 之内，
       * 实测 570 行时回 500）——那是后端的另一笔账。这一行只保证屏幕上
       * 那几个数**互相对得上**。
       * `loadFamily()` 早就这么做了（「（还有 N 位没列出来）」）。
       */
      const rendered = Math.min(events.length, (data.items || []).length);
      const unshown = Math.max(0, (Number(data.total) || 0) - rendered);
      const rest = unshown ? ` · 还有 ${unshown} 条没列出来` : '';
      meta.textContent = data.total
        ? `一共 ${data.total} 条 · 刚刚已更新${rest}${tail}`
        : (extra ? `还没有办过事 · 另有 ${extra} 条系统记录` : '还没有记录');
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

    /* `/api/v1/contacts` 回的不只是家人。实测播种态那四条：
     *
     *     儿子        role=家人
     *     女儿        role=家人
     *     优活系统    role=系统      <- 不是人，也联系不了
     *     社区网格员  role=社区      <- 是人，但不是家人
     *
     * 这一行原先写的是 `${data.count} 位家人可以联系`——4。两条都不是家人，
     * 其中一条根本不是人。而下面只有三个 `.family-branch` 槽位，第四条于是
     * **一个字都没显示**，也没有任何地方说少了一位。同一屏上三个数各不相同：
     * 说 4、列 3（含优活系统）、真家人 2。
     *
     * 先把「系统」滤掉：她没法「联系」优活自己，而这一行说的就是「可以联系」。 */
    const people = (data.items || []).filter((c) => c.role !== '系统');
    const kin = people.filter((c) => c.role === '家人');
    const branches = $$('.family-branch', page);
    const shown = people.slice(0, branches.length);
    const missed = people.length - shown.length;

    const meta = $('.identity-meta', page);
    if (meta) {
      //: 数和词必须对上：家人几位就说几位家人，其余的另说一句。
      //: 槽位不够时明说少了几位——静默截断是这个仓库反复修的那个形状。
      const head = kin.length ? `${kin.length} 位家人` : '还没有登记家人';
      const others = people.length - kin.length;
      let line = kin.length
        ? head + (others ? `，另有 ${others} 位可以联系` : '可以联系')
        : (people.length ? `有 ${people.length} 位可以联系` : head);
      if (missed) line += `（还有 ${missed} 位没列出来）`;
      meta.textContent = line;
    }

    /* 号码**只在真有的时候**才当成号码用。
     *
     * 这一段原来的注释写的是「`phone` 后端永远回 null（`actors` 表没有这一列）」
     * ——那句话已经过期了：`actors` 现在有 `phone` 这一列
     * （`Database._migrate`），家人端三那张「守护设置」卡就是它的登记入口，
     * `/api/v1/contacts` 会把登记过的号码原样回出来。
     *
     * 但**没有号码的那几位照旧不给拨号按钮**。原来那句注释后半段仍然成立：
     * 编一个号码出来，她真按下去会拨错人；而摆一个按不通的按钮，
     * 比没有这个按钮更糟。
     *
     * 号码不写进 `small`：这一格是 `position:absolute` 的固定宽度，
     * 多一个 11 位号码会折行、把山水那一层顶开。她点下去就听得到、看得到。 */
    branches.forEach((el, i) => {
      const c = shown[i];
      if (!c) { el.hidden = true; return; }
      el.hidden = false;
      const b = $('b', el), small = $('small', el);
      if (b) b.textContent = c.name;
      if (small) {
        small.textContent = c.primary ? `${c.role} · 优先联系` : c.role;
      }
      if (c.phone) {
        el.dataset.callPhone = c.phone;
        el.dataset.callName = c.name;
      } else {
        delete el.dataset.callPhone;
        delete el.dataset.callName;
      }
    });

    const core = $('.family-core span', page);
    if (core && people.length) {
      //: 从**过滤后**的名单里取，否则「先找谁」可能指向优活系统。
      const first = people.find((c) => c.primary) || people[0];
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
      /* 三态，不是两态。
       *
       * 原先是 `s.saved ? '这是您自己调过的' : '现在是默认设置'`，而 `saved`
       * 的含义是「库里有这一行」——**不是「她调过」**。于是女儿在她的照护页上
       * 改了字号语速之后，她自己这一屏写着「这是您自己调过的」。
       * 一句写死的话在陈述一件它并不知道的事。
       *
       * `savedByFamily` 由后端按交互档案的 `updated_by` 算。 */
      meta.textContent = !s.saved ? '现在是默认设置'
        : s.savedByFamily ? '这是家人替您调的'
        : '这是您自己调过的';
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
  /* 每次都把宿主搬到**当前那一屏**，不是造一次就不管了。
   *
   * 原先第二行是 `if (host) return host;`——一旦在「今天」那一屏造出来，
   * 就永远待在那里。而 `/elder3` 换页是把四个 `.workspace` 横向平移，
   * 非当前的那几个是 `opacity:0; visibility:hidden`。于是：
   *
   *     在「今天」说一句话（宿主在今天那屏造出来）
   *     -> 切到「记录」-> 点某一行的「看看这件事的经过」
   *     -> 卡片画进**今天那一屏**，她在记录页上什么也看不到，
   *        只剩一个「收起来」，收的是看不见的东西。
   *
   * 上面 `ensureStatus()` 正是为同一件事写的，还带着量出来的证据
   * （◉今天 y=495 看得见 · ◇记录 / ○家人 / ⌁我的 看不见）。
   * 那条规则当时没被这个宿主跟上。
   *
   * 判据也没兜住：`check_focus_geometry.py` 那几处盯的是 `#relianceHost`，
   * 而那个 id 只存在于 `elder-v6.html` / `elder.html`——`/elder3` 用的是
   * `#e3Reliance`，不在任何一条可见性判据的取景框里。
   */
  /* 造一次就不搬家——**这是一个已知缺陷，不是有意的设计**。
   *
   * 她在「今天」说过一句话之后（宿主在今天那一屏造出来），切到「记录」再点
   * 某一行的「看看这件事的经过」，卡片会画进**今天那一屏**——一块
   * `visibility:hidden` 的地方，屏幕上只剩一个「收起来」。
   * 上面 `ensureStatus()` 每次都把状态行搬到当前那一屏，这个宿主没跟上那条规则。
   *
   * 改成「每次都搬」试过了，`check_dead_controls` 直接判红：宿主一进
   * `.e3-away` 那个浮层，卡片一打开就压在 `/elder3#records` 的一行记录上，
   * 手指点不着。加 `pointer-events` 也没解决。
   *
   * 真正的修法要给「非今天」的那几屏一个放得下这张卡的位置（这四块 workspace
   * 是绝对定位的美术层），那是一次布局决定。记在 KNOWN_ISSUES 里，别在这儿
   * 用一个把控件盖住的改法换掉它。 */
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
      // 办完一件事，今天那一屏就该跟着变——但**不许追问**：
      // 屏幕上正写着刚才那句话的答复。
      loadToday({ask: false});
      loadRecords();
      return true;
    } catch (e) {
      trouble(e, '这句话');
      /* 返回 false，而不是往外抛。
       *
       * 上面这个 catch 已经把话说给她听了（`trouble()` 会写状态行并念出来），
       * 再抛一次会让调用方把同一件事说第二遍。但**调用方需要知道成没成**：
       * 打字那条路要靠这个决定要不要清空输入框——不然网络一断，她打的那句话
       * 就从输入框里消失、而屏幕上没有任何地方留着它（设计一有聊天气泡，
       * 这一版是状态行式的，没有）。
       *
       * 原有 6 个调用点都不看返回值，所以加这个不影响它们。 */
      return false;
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
      /* 同一条按第二次，也要有反应。
       *
       * `spoken` **就是这个节点自己的文字**，所以第二次是同一个字符串赋两遍：
       * DOM 不变、指纹不变。这一轮已经三次栽在同一个形状上（「存下来」、
       * `showMemories()` 的件数、「同步到他的手机」）。她之所以再按，
       * 正是因为不确定刚才那一下有没有算上。
       *
       * 「再念一遍」既换掉了字符串，也确实成立——这一下真的又念了一遍。
       * `lastSpoken` 仍然存原文：`#repeatLast` 读它，不该带上这个前缀。 */
      if (spoken) {
        /* 判重对着**屏幕**，不对着记住的状态。
         *
         * 三版的账：
         *   一版  按节点身份判         记录里有两个不同节点文字完全相同 → 漏
         *   二版  按 `lastSpoken` 计数  几个同文字节点交替按时，计数和屏幕对不上 → 漏
         *   这一版 按状态行当前显示的字判
         *
         * 二版怎么漏的（巡检诊断档，同一批同文字节点连着三次）：
         *
         *     变了 · ST:'出了一张托付说明卡，服务' -> 'ST:出了一张托付说明卡18:01 · 服务'
         *     变了 · 只有别处变，**ST 没变**   ← say() 写的和屏幕上已有的一模一样
         *     不变 · 判为没反应
         *
         * 中间那一行是关键：记住的 `lastSpoken` 和屏幕上显示的字已经分叉了。
         *
         * 要钉的性质是「她按下去，**屏幕**要变」——那就直接问屏幕现在是什么。
         * 记住的状态只是这个性质的代理，而代理会和事实分叉，这一轮分叉两次。
         *
         * 三句轮换，保证任何一次按下去都和当前显示不同。 */
        const shown = statusEl ? (statusEl.textContent || '') : '';
        const again = `再念一遍：${spoken}`;
        const more = `又念了一遍：${spoken}`;
        say(shown === spoken ? again
            : shown === again ? more
            : shown === more ? again
            : spoken);
        speakOut(spoken);
        lastSpoken = spoken;          //: 存原文——`#repeatLast` 读的是它
      }
      // 记录行还带着这件事的主体号时，多给一个「看看经过」。
      // 念一遍只回答「这条写的是什么」，回答不了「这件事后来怎么样了」——
      // 设计一二点一条记录会摊开整段经过（`task-detail.js`），设计三此前没有。
      if (node.dataset.taskId) {
        const tid = node.dataset.taskId;
        offer([{label: '看看这件事的经过', run: () => showTaskDetail(tid)}]);
      }
      /* 家人那一格上**真有**号码时，多给一个「打给他」。
       *
       * 为什么隔一步而不是点一下就拨：这一格原本的动作是「念给她听」，
       * 点下去直接拨出去会变成手一抖就打扰了在上班的儿子。多一个写着字的
       * 按钮，和这一版待办「问一句再改」是同一条规矩。
       *
       * 那句话只说这一下**真会**发生的事：手机上会跳到拨号界面，电脑上不会，
       * 所以号码一并念出来——跳不出来的时候她还能照着拨。 */
      if (node.dataset.callPhone) {
        const to = node.dataset.callName || '这一位';
        const number = node.dataset.callPhone;
        offer([
          {label: `打给${to}`, run: async () => {
            const line = `这就打给${to}。手机上会跳出拨号界面；`
                       + `要是没跳出来，号码是 ${number}。`;
            say(line, 'good');
            speakOut(line);
            window.location.href = `tel:${number}`;
          }},
          {label: '先不打', run: async () => { offer([]); say('好，先不打。'); }},
        ]);
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
      const go = () => once(row, async () => {
        // 切回「今天」再说：回答会写在状态行上，而状态行在那一屏。
        const dock = $('.dock [data-page="today"]');
        if (dock) dock.dispatchEvent(new PointerEvent('pointerup', {bubbles: true}));
        /* 那 400 ms 要**算在忙里面**。
         *
         * 写成 `setTimeout(() => send(what), 400)` 的话 `once()` 会立刻返回、
         * 立刻把忙状态撤掉——屏幕上闪一下就没了，而真正的等待还没开始。
         * 换成 await 之后，从她点下去到回答出现这一整段（400 ms + 一次往返）
         * 那一行都是「在办」的样子。
         *
         * 这一行是 `<div role="button">`（交付包写成了 div，L1184 补的 role）。
         * `once()` 里 `el.disabled = true` 在 div 上是无操作，所以防重复靠的是
         * `data-in-flight`，看得见靠的是 `components.css` 里那条
         * `[role="button"][aria-busy="true"]`。 */
        await new Promise((r) => setTimeout(r, 400));
        await send(what);
      });
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
        // 忙落在麦克风上：这条路上唯一可见的承诺就是那个球。顺带也挡住了
        // 「上一句还在办就又按一次」——那会开一次新的识别，两句话同时在办。
        rec.onresult = (e) => once(orb, () => send(e.results[0][0].transcript));
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
          /* 空着按下去也要有话。
           *
           * `send()` 第一行是 `if (!what) return;`——空白直接返回，屏幕上一个字
           * 都没有。她还没写字就按「说给优活」：按钮闪一下（`once()` 同步置灰），
           * 然后什么都没有，她无从判断刚才那一下算不算。
           * 巡检报的就是这一条：`没反应 [第二步] button 说给优活`。
           *
           * 第二次说得更具体（给两个例子）：她再按，正是因为第一句没让她知道
           * 该写什么。 */
          let saidEmpty = false;
          box.addEventListener('submit', (e) => {
            e.preventDefault();
            const input = $('#e3Text');
            const text = input.value;
            if (!String(text || '').trim()) {
              say(saidEmpty
                ? '那一格还是空的。光标已经放在那儿了——比如写「交电费」，'
                  + '或者「明天早上八点提醒我吃药」。'
                : '还没写字。想办什么，写一句就行。', 'warning');
              saidEmpty = true;
              if (input) input.focus();
              return;
            }
            saidEmpty = false;
            // 忙在「说给优活」那个按钮上；**送出去了才清空**。
            // 原来是先清空再发送，而 `send()` 自己吃掉所有错误从不外抛——
            // 网络一断，她打的那句话就没了，屏幕上也没有一处留着它。
            once(e.submitter || $('button[type="submit"]', box), async () => {
              if (await send(text)) input.value = '';
            });
          });
        }
        box.hidden = false;
        const input = $('#e3Text');
        if (input) input.focus();
      });
    }

    /* 「☎ 联系家人」补一句真话。
     *
     * 交付包的处理（`page-motion-and-ui.js:66`）是过场 + 对 `#contactFamily`
     * 的一段 `el.animate()`。**已经在家人页上**按它时，产品层面只剩那一下
     * 4 像素的弹跳——对老人来说那不算「说了话」。
     * 巡检报的是 `没反应 #dockContact ☎联系家人`（在家人页上量的）。
     *
     * 顺带一句给下一个人：`el.animate()` 这类反应不进 class/文字指纹，
     * 那支脚本看不见它。所以这一处既是产品上的弱反馈，也是它的盲区。
     *
     * 不改交付包脚本，另加一个 `click` 监听；它那一个绑在 `pointerup` 上，
     * 两边不冲突。 */
    const dockContact = $('#dockContact');
    if (dockContact) {
      let saidHere = false;
      dockContact.addEventListener('click', () => {
        const on = ($('.workspace.active') || {}).dataset;
        const already = on && on.workspace === 'family';
        if (already) {
          /* 这两句只能说这一页**真有**的事。
           *
           * 上一版写的是「点下面任意一位，就能打给他」和「每一位后面都有一个
           * 『打电话』」——量过之后两句都是假的：这一屏只有三条 `.family-branch`
           * （儿子 / 女儿 / 优活系统），每一条里**按钮数为 0**，
           * 整屏文字里也没有「打电话／拨号／呼叫」。
           *
           * `.family-branch` 走的是同一个 click 处理里的 speak 分支
           * （`say(spoken); speakOut(spoken)`）——它做的是**念给她听**。
           *
           * 一处为了修「什么都没说」而新加的文案，本身说了假话，
           * 那比原来什么都不说更糟。 */
          say(saidHere
            ? '还是这一页。点一下哪一位，我念给您听。'
            : '家人就在这一页。', 'good');
          saidHere = true;
          return;
        }
        saidHere = false;
        say('这就带您去家人那一页。', 'good');
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
          /* 这句话里教的说法**必须是真能用的那一句**。
           *
           * 上一版写的是「要现在叫人来，请说『我需要帮忙』」——走真路由验过，
           * 「我需要帮忙」「我要叫人」「快来人」三句都落到闲聊；真能触发安全
           * 告警、立刻通知家人的是「救命」和「我摔倒了」。全 App 最要紧的
           * 一句指令，教的却是一句系统听不懂的话。
           *
           * 不去把「我需要帮忙」加进紧急词：那句话太像开场白
           * （「我需要帮忙……交个水费」），加进去就是误报，而误报会半夜把
           * 家人叫起来。安全那一层的守卫一贯是「宁可少报，不可乱报」。 */
          say(`可以联系的家人：${who}。急事说「救命」，我立刻通知家人。`, 'good');
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

    /* 顶栏那对「优活 | 无忧伴」：**两半都要真的说一句话。**
     *
     * 后端按**每一句话**判定要不要进陪伴（`companion.wants_companion`），
     * 没有一个可以切换的持久状态。所以点它就真的说一句。
     *
     * 在这之前只有「无忧伴」有真接线。交付包的 `page-motion-and-ui.js:115`
     * 给两边都绑了 `setMode()`——它切 `active` 类、弹一条 toast，说
     * 「优活模式 · 继续帮您记事、办事和做必要确认。」，**但一个字都不对后端说**。
     * 于是她切到无忧伴再切回来，屏幕告诉她回到了办事模式，而后端不知道。
     *
     * 交付包那半不摘（它负责视觉状态，是有用的；`elder3.js` 文件头列的三个
     * 「只演不做」里也没有这一对）。这里只补上真接线。
     *
     * `saidCompanion` 是**我们自己置的**状态，不去读
     * `comp.classList.contains('active')`——那是交付包用来画样子的显示状态，
     * 拿显示状态当事实是这个项目反复栽的那件事。
     */
    let saidCompanion = false;
    const comp = $('#modeCompanion');
    if (comp) {
      comp.addEventListener('click', () => once(comp, async () => {
        saidCompanion = true;
        await send('陪我说说话');
      }));
    }
    const you = $('#modeYouhuo');
    if (you) {
      you.addEventListener('click', () => once(you, async () => {
        if (!saidCompanion) {
          // 本来就在办事模式。不白跑一次往返，但按下去要有回话——
          // 一个按了没反应的按钮，和一个骗人的按钮一样糟。
          say('现在就是优活模式，我在帮您办事。', 'good');
          return;
        }
        saidCompanion = false;
        await send('继续办事');
      }));
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
