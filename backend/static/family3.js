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
/* 发第一个请求之前，先把照护面板那份**样张**收掉。
 *
 * `family-v3.html` 出厂就写着一屏具体的照护事实：
 *
 *     血压 128/76 mmHg · 16:10    体温 36.5°    体重 68.2 kg    心率 72 次/分
 *     缬沙坦 80 mg · 早餐后「已记录」   阿托伐他汀 20 mg · 睡前「待今晚」
 *     步行 3,240 步   饮水 约 1.2 L   午休 32 分钟   今日完成 1 / 2
 *     周一 平静 / 周二 愉快 / 今天 不错   “傍晚想出去走一走。”
 *     安全「今日无异常」   家人联系人「3 人 · 正常」   异常事件「今天 0 条」
 *
 * 成功那一路 `loadCare()` 会把它们全换掉，所以平时看不出来。
 * **出问题那一路不会**：几个 `catch` 只重写脉络那一行摘要
 * （`fillVein('body', '身体', '暂时取不到身体记录', 'watch')`），
 * 面板里那些数字原样留在屏上。于是断网 / 后端 500 / 令牌过期的时候，
 * 子女读到的是「暂时取不到身体记录」这句话，**底下却明明白白写着 128/76**。
 *
 * 一个来看爸爸今天怎么样的人，读到的是一份编出来的体征。
 *
 * 做法照 `family.js` 那一处（它为设计二解决过同一件事，注释在第 102 行）：
 *
 *   * 放在**第一个请求之前**，不补进那几个 catch——补 catch 要求每新增一条
 *     失败路径都有人记得再补一次；放在这里只有一处，忘不掉。
 *   * HTML 一个字不动：那份样张是给设计看的。
 *   * 只清**叶子节点的文字**，不动结构——`loadCare()` 是就地改这些节点的
 *     （`$$('[data-care-page="body"] .body-metric')` 之类），
 *     照 `family.js` 那样整块 `textContent = 词` 会把它要写的格子一起抹掉。
 */
const CARE_MOCKUP = [
  ['.today-whispers div span', '—'],
  ['.medicine-seal .med-time', '—'],
  ['.medicine-seal strong', '—'],
  ['.medicine-seal small', '—'],
  ['.medicine-seal i', '—'],
  ['.med-summary b', '—'],
  ['.body-core strong', '—'],
  ['.body-metric strong', '—'],
  ['.body-metric small', '—'],
  ['.mood-day span', '—'],
  ['[data-care-page="mood"] blockquote', ''],
  ['.guardian-core small', '—'],
  ['.guard-node span', '—'],
  //: 节律那一圈：`08:42 起床 晚约 40 分钟`、`12:30 午休 32 分钟`……
  //: 三个格子 `loadCare()` 都会填（`text($('time', el), …)` / `b` / `small`），
  //: 所以先清掉是安全的。**这一组是判据改对之后才抓出来的**——
  //: 第一版按行匹配，把它漏了。
  ['.rhythm-node time', '—'],
  ['.rhythm-node b', '—'],
  ['.rhythm-node small', '—'],
  ['.sun-center span', '—'],
  ['.sun-center small', '—'],
];
CARE_MOCKUP.forEach(([sel, word]) => {
  $$(sel).forEach((el) => { el.textContent = word; });
});

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
  /* 提示要落在**当前看得见的那一屏**里。
   *
   * 这一处原先固定插在 `#familyMain .action-band` 前面，那在 `#familyView` 里。
   * 而 `script-01.js:6` 是 `familyView.hidden = care; careView.hidden = !care;`——
   * 照护中心显示时 `#familyView` 整棵子树 `hidden`，写进去的字一个都不出现。
   *
   * 实测三条可达路径，全部是「按下去屏幕上一个字都没有」：
   *
   *     照护气泡按「×」       「这一条是记录，不能删掉…」
   *     照护气泡提交「生成」  「照护记录来自老人自己办的事…」
   *     照护数据加载失败      `trouble()` 那一句
   *
   * 只有换屏时才搬（`noticeHost` 记住上一处）：每次 `say()` 都动 DOM 会把
   * `.f3-notice` 的入场重置掉，连着两句提示就会闪。 */
  let noticeHost = null;
  function ensureNotice() {
    const care = $('#careView');
    const onCare = !!(care && !care.hidden);
    //: 照护那一屏的 `.care-tabs` 是 `position:absolute`，插在它前面不会把它顶下去，
    //: 所以照护态的提示由 `.f3-notice-care` 自己定位（`family3-wiring.css`）。
    const host = onCare
      ? ($('#careTabs') || care)
      : ($('#familyMain .action-band') || $('#familyMain'));
    if (!host) return null;
    if (!notice) {
      notice = document.createElement('p');
      notice.id = 'f3Notice';
      notice.setAttribute('role', 'status');
      notice.setAttribute('aria-live', 'polite');
    }
    notice.className = onCare ? 'f3-notice f3-notice-care' : 'f3-notice';
    if (noticeHost !== host || !notice.isConnected) {
      host.insertAdjacentElement('beforebegin', notice);
      noticeHost = host;
    }
    return notice;
  }
  function say(text, tone) {
    const el = ensureNotice();
    if (!el) return;
    el.textContent = text || '';
    el.dataset.tone = tone || 'good';
  }
  const trouble = (e, what) => say(errorWords(e, what).text, 'bad');

  /* 换屏之后，上一屏那条回执要收回去。
   *
   * 实测：点「无忧伴」→ 照护面上出现那一句；点「家人端」回来 → 它还在，只是
   * 落在了隐藏子树里；再切回照护中心 → **它又露出来**。那一句当时成立，
   * 摆在这里却是「一屏你已经离开的界面上的回执」被当成当前状态。
   *
   * 判据用**位置**而不是时序：如果它最后落在一棵 `hidden` 子树里，就清掉。
   * 不能在这里无条件清——「无忧伴」那个处理是 `click()` → `showYouHuoCarePage()`
   * → `say()` 三步在同一个任务里，而观察器回调是任务末尾的微任务，
   * 无条件清会把刚写上去的那一句抹掉。走到这里时它已经在可见的那一面了。 */
  (() => {
    const views = [document.querySelector('#familyView'),
                   document.querySelector('#careView')].filter(Boolean);
    if (!views.length) return;
    const obs = new MutationObserver(() => {
      if (notice && notice.isConnected && notice.closest('[hidden]')) {
        notice.textContent = '';        //: `.f3-notice:empty { display:none }`
        noticeHost = null;              //: 下一次 say() 重新选宿主
      }
    });
    views.forEach((v) => obs.observe(v, {attributes: true, attributeFilter: ['hidden']}));
  })();

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

  /* ---- 待办 / 我的：右边那两块行区 ----------------------------------------
   *
   * 交付包设计好了、但一直没有建：`history` / `planner` 这两个词在它的 HTML 与
   * JS 里一次都没出现，全仓只有 `family3/style-01.css:113-119` 那 9 行样式。
   * 两屏于是各自空着右边 38%~45%，而 `.mine-stage .center-message{right:45%}`
   * 那条规则就是为了给它让位——**空位是设计出来的，不是没排满**。
   *
   * ## 时间线走 `/api/v1/records`，不走 `/v2/audit`
   *
   * 后端那一层已经把审计码翻成人话了（`app_api.py::_WORDS`，那张表是
   * `SELECT event_type, COUNT(*) ... GROUP BY 1` 查库定的案），而且它**按调用方的
   * 角色换称呼**（`reading_own = ctx.role is ActorRole.ELDER`）：家属令牌读到的是
   * 「老人确认了」，不是「您确认了」。走 `/v2/audit` 拿原始码就要在前端再翻一遍，
   * 那是同一个码的第三套说法——这个仓库一直在收敛的正是这个形状。
   *
   * 它还替我们做了两件事：`_MACHINERY` 里的内部事件不占她的行；被挡掉的条数
   * 原样放在 `machinery` 字段里。所以下面那句「另有 N 条系统记录」不是编的，
   * 是后端明说要摆出来、不做成隐形差额的那个数。
   *
   * ## 为什么「待办」那一块放事务、不放提醒
   *
   * 提醒已经有归宿了：同一屏左边的 `#familyFlow`（「今日待办」）就是提醒，
   * 五条，带 ＋ 号可以加。再列一遍是重复。没有归宿的是**事务**——原先它们被塞进
   * `#mainCopy` 一句话里，用「；」串起最多三条，第四条起在屏幕上不存在。
   */

  /** 清空一块行区并返回它。标题在 `.stage-rows` 外面，所以不会被一起清掉。 */
  function stageRows(host) {
    const box = host ? $('.stage-rows', host) : null;
    if (box) box.textContent = '';
    return box;
  }

  /** 一行：粗体一句 + 淡色一句。两块共用，只有行的 class 不同
   *  （交付包给的是 `.planner .date` 和 `.history .row`）。
   *
   *  用 `createElement` 而不是 `innerHTML`：这几个字段里 `title` / `note` 来自
   *  审计 payload，`kind` 来自后端词表。拼 HTML 的话它们就成了标记。 */
  function stageRow(box, cls, strong, small) {
    if (!box) return null;
    const row = document.createElement('div');
    row.className = cls;
    if (strong) {
      const b = document.createElement('b');
      b.textContent = strong;
      row.appendChild(b);
    }
    if (small) {
      const s = document.createElement('span');
      s.textContent = small;
      row.appendChild(s);
    }
    box.appendChild(row);
    return row;
  }

  /** 「待办」右边：在办的事务，一件一行。
   *
   *  `statusWord()` 的第二个实参**必须**是 `'other'`。这一屏是家人在读老人的事。
   *
   *  漏掉它就落到默认的自称那一份，实测（女儿的令牌读 `/v2/tasks`，两笔在办）：
   *
   *      漏传   缴费（等您复述确认）；缴费（等家人接力）
   *      传了   缴费（等老人复述确认）；缴费（等您接力确认）
   *
   *  两处都反了。第一笔要复述的是她母亲，屏幕却对女儿说「等您复述确认」——
   *  她会去等一件根本轮不到她做的事；第二笔真正要她点头，屏幕却说「等家人接力」，
   *  把唯一需要她动手的那一件说成别人的事。`common.js` 那个函数的注释点名了
   *  这一处（「漏传的那一处会在报告里点名」）。 */
  const PLANNER_ROWS = 8;

  function fillPlanner(undone) {
    const box = stageRows($('#f3Planner'));
    if (!box) return;
    if (!undone.length) {
      stageRow(box, 'date', '', '现在没有在办的事。');
      return;
    }
    undone.slice(0, PLANNER_ROWS).forEach((t) => {
      stageRow(box, 'date', YH.taskWord(t.task_type),
               YH.statusWord(t.status, 'other'));
    });
    const rest = undone.length - PLANNER_ROWS;
    if (rest > 0) {
      stageRow(box, 'date more', '', `还有 ${rest} 件没有列出来。`);
    }
  }

  /** 「我的」右边：可信记录时间线。**只读**——本项目 P0。 */
  const HISTORY_ROWS = 40;

  async function fillHistory() {
    const host = $('#f3History');
    const box = stageRows(host);
    if (!box) return;
    stageRow(box, 'row more', '', '正在读取记录……');
    let data = null;
    try {
      data = await api(`/api/v1/records?limit=${HISTORY_ROWS}`, {}, FAMILY);
    } catch (e) {
      // 两个出口各有各的事：这一行是**这一块的状态**（她切过来就看到），
      // `trouble()` 是这一页的即时回执（一会儿会收回去）。不是同一句话。
      stageRows(host);
      stageRow(box, 'row more', '', '这一段没有读出来。');
      trouble(e, '记录');
      return;
    }
    const items = Array.isArray(data) ? data : (data.items || []);
    stageRows(host);
    if (!items.length) {
      stageRow(box, 'row more', '',
               '还没有记录。确认、提醒和照护的每一步都会记到这里。');
      return;
    }
    items.forEach((r) => {
      // `time` 已经是老人所在时区的钟点（后端 `local_now()` 之后 strftime 的），
      // 前端不再按设备时区算第二遍——那正是这个项目修过的那个缺陷。
      const small = [r.time, r.kind, r.note].filter(Boolean).join(' · ');
      stageRow(box, 'row', r.title, small);
    });
    const rest = Math.max(0, (Number(data.total) || 0) - items.length);
    if (rest > 0) {
      //: 说法照 `family.js:990`（「另有 N 条更早的记录。」），不另起一套。
      stageRow(box, 'row more', '', `另有 ${rest} 条更早的记录。`);
    }
    const machinery = Number(data.machinery) || 0;
    if (machinery > 0) {
      //: 说法照 `elder3.js` 那三处（「另有 N 条系统记录」），不另起一套。
      //: 这一行原先写的是「另有 N 条系统自己的记录，不占这份时间线。」——
      //: 同一个 `machinery` 字段两套说法，而上面那段注释里抄的还是对的那一句。
      stageRow(box, 'row more', '', `另有 ${machinery} 条系统记录。`);
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

    /* 两块行区跟着这一屏切。`today` 两块都收起来：它们的定位规则挂在
     * `.todo-stage` / `.mine-stage` 上，没有那个祖先 class 时它们会掉回常规流，
     * 压住 `.center-message`。 */
    const planner = $('#f3Planner');
    const history = $('#f3History');
    if (planner) planner.hidden = which !== 'todo';
    if (history) history.hidden = which !== 'mine';

    if (which === 'todo') {
      text(title, '待办与提醒');
      const undone = tasks.filter(
        (t) => !['completed', 'cancelled', 'failed'].includes(String(t.status)));
      text(headline, undone.length ? `还有 ${undone.length} 件事在办` : '没有在办的事');
      /* 正文不再复述那张表。原先它把最多三件事用「；」串成一句话，而那正是右边
       * 那块 `.planner` 该干的事——一句话里塞一张列表，第四条起在屏幕上不存在。
       *
       * 现在它说一件列表说不出来的事：这些里有几件**真的要她动手**，
       * 以及去哪儿动手。指的是页签名而不是方位，narrow 布局下也不会变成假话。 */
      text(copy, undone.length
        ? (needYou.length
            ? `其中 ${needYou.length} 件要您点头，到「今天」那一屏确认。`
            : '这些优活会自己办完，不用您操作。')
        : '需要办的事办完了。新的事会自动出现在这里。');
      fillPlanner(undone);
    } else if (which === 'mine') {
      text(title, '我的记录');
      const done = tasks.filter((t) => t.status === 'completed');
      text(headline, done.length ? `最近完成了 ${done.length} 件事` : '还没有办完的事');
      /* 这句话原先是**一句空许诺**：屏幕上从来没有时间线，而右边 45% 一直空着。
       * 现在那块 `.history` 就是它——所以这句话可以留着，它终于是真的了。 */
      text(copy, '确认、提醒和照护记录都会在这里留下清晰的时间线。'
                 + (done.length ? `最近一次是${YH.taskWord(done[0].task_type)}。` : ''));
      await fillHistory();
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
    /* 交付包的渲染器只读 `done`（`flow-item completed|pending`）——`level` 和
     * `needVoice` 它一个字都没读，连它自己那份演示数据里的也没读。而
     * `#careFlow .flow-item.care-normal|care-focus|care-waiting` 三套样式、
     * 以及 `#careFlow .needs-voice .breath-mic{display:grid!important}`
     * 都在它自己的样式表里躺着。
     *
     * 所以类在这里补：**不改交付包的渲染器**，只在它渲染完之后按行贴。
     * 贴之前先清一遍——`F.render()` 会复用节点，上一批的档留着就成了串档。 */
    rows.forEach((r) => {
      if (!r.level && !r.needVoice) return;
      const node = $(`.flow-item[data-id="${CSS.escape(String(r.id))}"]`, flow);
      if (!node) return;
      node.classList.remove('care-normal', 'care-focus', 'care-waiting', 'needs-voice');
      if (r.level) node.classList.add(`care-${r.level}`);
      if (r.needVoice) node.classList.add('needs-voice');
    });
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

  /* 后端 `Verdict` 的五个取值 -> 交付包画了样式的三档。
   *
   * 不是在这里定语气，是**照后端枚举自己的注释**推的（`baseline.py:87`）：
   *
   *     typical  符合他自己的常态                    -> normal
   *     pending  「**预期之内**的不知道，不该影响当天的总体结论」 -> normal
   *     notice   轻度偏离                            -> focus
   *     marked   显著偏离                            -> focus
   *     unknown  「本该有记录却一条都没有……在养老场景里『一整天没有任何活动
   *              记录』恰恰是最该被看见的一种情况」  -> waiting
   *
   * `unknown` 落 waiting 而**不是** normal，就是因为那条注释：它不是「轻于正常」，
   * 是「不知道」。落到 normal 等于把最该被看见的一天画成风平浪静。
   *
   * `notice` 与 `marked` 合档：交付包只画了三档，轻重之分留在 `explanation` 里。
   * 认不出来的取值落 normal——这一条由判据钉住枚举全覆盖，走不到。 */
  const CHANNEL_LEVEL = {
    typical: 'normal',
    pending: 'normal',
    notice: 'focus',
    marked: 'focus',
    unknown: 'waiting',
  };

  /** 照护屏那条「生命节律」气泡流。
   *
   * 原先读 `/api/v1/records`（审计流水），于是这条 kicker 印着 `CARE · RHYTHM`
   * 的流水上写的是「登录了优活」「开始办一件事」。交付包自己那份演示数据是
   * 起床 / 午休 / 血压 / 晚间复测——节律，不是审计。
   *
   * 审计流水这一轮有了归宿（「我的」那一屏的 `.history` 时间线），所以这里换成
   * `/v7/baseline/{elder}` 的逐通道偏离。**是搬走，不是删掉。**
   *
   * `require_elder_access(actor, elder_id)`：绑定了这位老人的家属读得到。
   * `ELDER_ID` 在 `boot()` 里先于本函数赋值（`YH.ready()` 那一行）。 */
  async function loadCareFlow() {
    try {
      const snap = await api(
        `/v7/baseline/${encodeURIComponent(ELDER_ID)}`, {}, FAMILY);
      const rows = (snap.deviations || []).slice(0, 5).map((d) => {
        const verdict = String(d.verdict || '');
        return {
          id: String(d.channel),
          // 今天这个通道读到了什么。`unknown` 的时候后端给的是 null——
          // 那正是这一行要说的事，用一道破折号占住那一格，不写「0」也不留空
          //（空的会把三列网格压掉一列）。
          time: d.observed_text || '—',
          title: d.label,
          /* 常态还没建立的时候不要用 `explanation`：那时它五个通道**几乎一字不差**
           * （实测 `observed_days:0`：「X：只有 0 天的记录，不足 7 天，还不能说
           * 这是他的常态。」——只有开头那个通道名不同）。五行同一句话，
           * 比原先显示审计流水更糟：那个至少是五条不同的字。
           *
           * 「不足 7 天」是整屏共通的一句，`loadCare()` 已经把 `dailyReport`
           * 那句话放进上方的 `.companion-note` 和页头了。这里说这个通道**今天**
           * 的事实，那是只有这一行能说的。 */
          status: (verdict === 'pending' || verdict === 'unknown')
            ? (d.observed_text ? `今天 ${d.observed_text}` : '今天还没有记录')
            : (d.explanation || ''),
          done: verdict === 'typical',
          level: CHANNEL_LEVEL[verdict] || 'normal',
          // 本该有记录而没有：那个呼吸麦克风的 aria-label 就是「等待语音确认」。
          // 它是 `<span>` 不是按钮——是指示，不是承诺点一下能录。
          needVoice: verdict === 'unknown',
        };
      });
      const head = $('#careFlow .flow-head h2');
      if (head) text(head, '生命节律');
      fillFlow('care', rows);
    } catch (e) { trouble(e, '生命节律'); }
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
    if (!dailyReport) {
      /* 取不到就**说取不到**，不能把交付包写死的那一句留在屏幕上。
       *
       * 这个 `if (dailyReport)` 原先没有 else：`/api/v1/daily-report` 一失败，
       * 这一格就一直挂着「今天和平常差不多 / 上午起得稍晚一些，没有需要
       * 立刻处理的异常。」——**后端断了，屏幕上却是一句让人安心的具体断言**。
       * 那比空着糟得多。
       */
      const note = $('.companion-note', view);
      if (note) {
        text($('strong', note), '今天的概括暂时取不到');
        text($('span', note), '这一格等下会自己好；下面的记录不受影响。');
      }
    }
    if (dailyReport) {
      const word = dailyReport.todayWord;
      const careHead = $('.identity-island h1', view);
      text(careHead, word);
      fitOneLine(careHead, 30);
      /* 这一格**两行都要换**。
       *
       * 原先只换了 `strong`，`span` 留着交付包写死的那一句：
       * 「上午起得稍晚一些，没有需要立刻处理的异常。」——一句关于**今天早上**
       * 的具体断言，编的。家人视图那一侧（`loadFamilyView`）两行都换，
       * 这一侧漏了一行，于是同一个组件在两个视图里一个说真话一个说假话。
       *
       * 是驱动出来的：把静态 HTML 里的中文抽出来当候选，页面加载完之后看
       * 屏幕上还剩哪些一字不差。这一句剩着。
       */
      const note = $('.companion-note', view);
      text($('strong', note), word);
      text($('span', note), dailyReport.familyWillSee || dailyReport.message || '');
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
          // 原先写的是「可以在老人端或这里添加」——**两边都不能**。全仓没有任何
          // 界面能建一份用药计划。现在这一屏底下真的有那个入口了，所以这句话
          // 只说「这里」：老人端仍然只能对家人加的药点头或回绝，不能自己加。
          : (plans.length ? '到点会提醒老人' : '可以在下面加一份'));
      }
      // 「2 种长期用药，今日记录完整。」是写死的。实测五脉说 1 种、这一句说 2 种，
      // 同一屏两个数字对不上——而这一句躲过了第一轮驱动，因为它读起来很正常。
      fillDoseActions(plans);
      const medHead = $('[data-care-page="med"] .substage-head p');
      // 卡位只有两个（`.med-a` `.med-b`，位置由 CSS 定死，克隆出来的第三张会叠
      // 在别人身上）。加药入口装上之后第三份药是随手就能有的事，而屏幕上
      // 「一共 3 种」配着两张卡，看起来像是丢了一条记录。**说出来**，不假装。
      const shown = Math.min(plans.length, seals.length);
      text(medHead, plans.length
        ? `${plans.length} 种长期用药`
          + (plans.length > shown ? `，下面列出最近 ${shown} 种。` : '，明细见下。')
        : '还没有登记长期用药。');
    } catch (e) {
      fillVein('med', '在吃什么药', '暂时取不到用药记录', 'watch');
    }

    /* 身体。字段照 `HealthEventRecord`：`kind` / `title` / `event_at` / `payload`。
     * 没有 `metric` / `value` / `unit` / `recorded_at` 这几个名字——
     * 第一版全用的是它们，只是演示库里这张表恰好是空的，所以一个都没露馅。
     * 「128/76 mmHg」那四张卡片是交付包写死的，后端没有这些数。
     *
     * ## 这张表原先和 /care 那一页各说一套，现在统一到 care.js 那一套
     *
     * 两页读的是**同一个端点**（`/v4/health/events/{elder}`），后端只发四个 `kind`，
     * 其中两个此前两页两个说法：`medication` 这里叫「用药」、/care 叫「用药记录」；
     * `note` 这里叫「记录」、/care 叫「记了一笔」。家属在两页之间来回看同一条事件，
     * 要自己判断这是不是同一件事。
     *
     * 取 care.js 那一套，理由是**这一套里的 `note` 有信息量，原先这一套没有**：
     *   · 这一行的兜底就是 `'记录'`（下面 `|| '记录'`）。`note: '记录'` 于是让
     *     「认出来了，这是他自己随手记的一条」和「这个类型我不认识」在屏幕上印出
     *     一模一样的字——翻译层成功和失效长得没有区别，而这恰恰是漏 `HEALTH_WORD`
     *     五个假键那次缺陷之所以能活到今天的形状。
     *   · 这一段的小标题已经是「最近的身体记录」，每一行本来就是一条记录；
     *     再给其中一类贴一个「记录」标签等于什么都没说。「记了一笔」说的是
     *     「这条不是体检也不是就诊，是他自己记的」，那才是这个标签要回答的问题。
     *   · 方向上也该以 /care 为准：那一页是照护中心，四类身体记录在那里是正文
     *     （列表 + `healthDigest()` 里当标题的替补），这里只是「今天」那一屏上的
     *     一个小标签。正文那一套的措辞被真实数据检验过，标签这一套没有。
     * 变量名一起改成 `HEALTH_WORD`：两份副本此前连名字都不一样，
     * 一次 grep 找不齐——那是它们能各自漂走的直接原因。 */
    const HEALTH_WORD = {checkup: '身体数据', visit: '就诊', medication: '用药记录', note: '记了一笔'};
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
        // 兜底不写成 `'记录'`：那和上面 `note` 的说法撞成一个字，认出来和认不出来
        // 在屏幕上就没有区别了。跟 /care 用同一句兜底。
        text($('span', el), HEALTH_WORD[String(r.kind)] || '一条记录');
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
      //: 这两份**存下来**给「守护设置」那张卡用——同样的两个请求不发第二遍。
      guardPolicy = policy;
      guardContacts = contacts;
      const nodes = $$('[data-care-page="safety"] .guard-node');
      /* 每一行多带一个 key。
       *
       * 不能按下标认这四格：`rows` 的条数和顺序跟着 `policy` 里**真有**哪几个
       * 字段走（缺 `inactivity_minutes` 时「紧急联系」就落到第二格）。
       * 按下标点开详情，会给她看另一项的设置。 */
      const rows = [['contacts', '家人联系人',
                     contacts.count ? `${contacts.count} 人 · 正常` : '还没有登记']];
      if (policy) {
        if (policy.inactivity_minutes) {
          rows.push(['inactivity', '久未活动',
                     `超过 ${Math.round(policy.inactivity_minutes / 60)} 小时就提醒`]);
        }
        /* 「家人之后还会找社区」是**说过头了**：量过，按下呼救之后只有一条
         * 通知、发给家人；社区那一位只是进了这次呼救的名单，没有人被联系。
         * 照 `app_api.py:2170` 那句已经写对的话来说——「也在名单上」。 */
        rows.push(['urgent', '紧急联系',
                   policy.notify_community ? '通知家人，社区也在名单上' : '只通知家人']);
        if (policy.geofence_radius_m) {
          rows.push(['fence', '活动范围', `离家超过 ${policy.geofence_radius_m} 米会提醒`]);
        }
      }
      nodes.forEach((el, i) => {
        if (!rows[i]) { el.hidden = true; delete el.dataset.guard; return; }
        el.hidden = false;
        el.dataset.guard = rows[i][0];
        text($('b', el), rows[i][1]);
        text($('span', el), rows[i][2]);
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

    // 固定安排（「今天」那一屏）与就医安排（「身体」那一屏）。
    //
    // 放在 `loadCare()` 里而不是 `boot()` 里：这两块只在照护中心上，
    // 家人端那一屏根本看不到它们，开机就拉等于每次进站都多两趟没人看的请求。
    loadRoutines();
    loadVisits();

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

        /* 同意和拒绝是**一对**，不是一个按钮加一条退路。
         *
         * 这一版原先只有「确认接力」一个按钮，`approve: true` 写死。可上面那句
         * 提示说的是「核对无误再按下面的确认」——核对下来**不对**的时候，
         * 这一屏上没有任何控件可按，只能走开，而那一笔就一直挂着。
         * 设计一（`family.js`）一直有「拒绝」，后端也一直收 `approve: false`
         * （回 200「家属未批准，本次操作已安全取消。」）。少的只是这块屏幕上的控件。
         *
         * 这一版的通知标题表里还留着 `task_rejected: '已按您的意见取消'`——
         * 一个这块屏幕当时产生不出来的结局。
         */
        const yes = document.createElement('button');
        yes.id = 'f3Approve';
        yes.type = 'button';
        yes.className = 'f3-approve';
        yes.textContent = '核对过了，确认接力';
        band.appendChild(yes);

        const no = document.createElement('button');
        no.id = 'f3Decline';
        no.type = 'button';
        no.className = 'f3-decline';
        no.textContent = '核对下来不对，不同意';
        band.appendChild(no);

        /* 这个共用的动作**定义在两个按钮之后**，不是随手排的。
         *
         * `test_viewing_a_payment_is_not_approving_it`（P0）以「查看」处理器里
         * 第一个 `document.createElement` 为界，要求审批调用不出现在它之前——
         * 那是「一次点击既是查看又是付钱」这件事看得见、查得动的近似。
         * 把定义提到按钮前面，行为一点没变，判据却会红。
         *
         * 判据不该为了迁就写法而放松：它一松，它本来要防的那件事就少一层保护。
         * 定义挪到后面没有任何代价——`decide` 只在点击时才执行。
         */
        const decide = (approve, button, reason) => once(button, async () => {
          try {
            const data = await api('/v2/family/approve', {
              method: 'POST',
              body: JSON.stringify({
                task_id: t.id, approve,
                approval_digest: t.approval_digest,
                reason,
              }),
            }, FAMILY);
            // 语气交给后端：拒绝也是 200，画成绿色成功框是错的。
            say(data.message, YH.toneOf(data));
            const other = $('#f3Approve') === button ? $('#f3Decline') : $('#f3Approve');
            button.remove();
            if (other) other.remove();
            await loadStage('today');
            loadFamilyFlow();
            // 这一笔已经动了，收件箱那一格不刷新就还挂着「需要您接力确认」。
            loadNotices();
          } catch (e) { trouble(e, '这一笔'); }
        });

        yes.addEventListener('click', () => decide(true, yes, '家属已核对任务摘要'));
        no.addEventListener('click', () => decide(false, no, '家属拒绝'));
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
          //: 色调跟着后端的 verdict 走。原先写死 'good'——报告说
          //: 「和平常差得比较多」的时候，屏幕上那一条也是好消息的颜色。
          say(dailyReport.message || dailyReport.todayWord,
              dailyReport.todayTone || '');
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
      /* 揭开它的那个「＋」也一样要补——漏了这一条，**这一面根本加不了待办**。
       *
       * 打开编辑器的监听是交付包脚本绑的，闭包里存的是 `strip()` 克隆**之前**
       * 那个节点（`script-06.js:225` 取，`:228` 用），而这里刚把它换掉了。
       * 于是「＋」在给一个已经脱离文档的表单设 `hidden = false`：不报错，
       * 文档里什么都不变。实测点完等 60ms：两张编辑器都还是 `hidden=true`。
       *
       * 扫描没抓到它，是因为 `.clickable` 那套按下去的动效（以及 `strip()` 里
       * 补的 `pressed`）本身就产生 DOM 变化——「有反应」不等于「这一下算上了」。
       *
       * 照护那一侧本来就不该新增（下面 submit 里那个分支），所以那一侧的「＋」
       * 直接把那句话说出来，而不是揭开一张交不上去的表单。 */
      const add = $('.flow-add', flow);
      if (add) add.addEventListener('click', () => {
        if (which !== 'family') {
          say('生命节律是优活按老人每天的记录自己算出来的，这里不新增。', 'warning');
          return;
        }
        fresh.hidden = false;
        const title = $('input[name="title"]', fresh);
        if (title) title.focus();
      });
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
            say('生命节律是优活按老人每天的记录自己算出来的，这里不新增。', 'warning');
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

    /* 「让他记住」：家人提一条要优活长期记住的事。**他点头之后才生效。**
     *
     * 这之前设计三上提不出来：老人端三个界面都能点头、能不点、能逐条收回，
     * 而这一面没有入口——那张「等您点头」的卡片在这一面永远不会出现。
     *
     * 请求形状、三个固定档（`preference` + `family_summary` + 后端默认 180 天）、
     * 那几句话、以及「同一格空着再按一次也要有反应」都在共享层
     * `common.js::wireProposeMemory` 里，两个家人端界面共用一份。
     *
     * `elderId` 传**函数**：`ELDER_ID` 到身份解析完才是真值，这里在模块顶层跑，
     * 冻住它会让这个表单一直往 `elder-demo` 身上提议，后端会正确地回 403。 */
    const memForm = $('#memoryForm');
    const memOpen = $('#familyFlow .flow-remember');
    if (memForm && memOpen) {
      memOpen.addEventListener('click', () => {
        //: 揭开就是回执：表单出现 + 光标落在第一格。这一下是同步的，不用 `once()`。
        memForm.hidden = false;
        const first = $('#memKey', memForm);
        if (first) first.focus();
      });
      const memCancel = $('.mem-cancel', memForm);
      if (memCancel) memCancel.addEventListener('click', () => { memForm.hidden = true; });
      YH.wireProposeMemory({
        form: memForm,
        submit: $('button[type="submit"]', memForm),
        keyInput: $('#memKey', memForm),
        detailInput: $('#memDetail', memForm),
        purposeInput: $('#memPurpose', memForm),
        elderId: () => ELDER_ID,
        notify: say,
        after: () => { memForm.hidden = true; },
      });
    }

    /* 身份区那两对按钮。
     *
     * `script-02.js:104` 的通用波纹把 `.mode button` 也收进去了，于是按下去有涟漪、
     * 功能上什么都不做，连 `.active` 都不换。CDP 扫描把涟漪算成「有反应」，
     * 所以「0 个死控件」没抓到它们。两对的性质不一样，处理也不一样。
     *
     * 照护屏那一对「照护 / 趋势」和真正的七个照护标签里两个重合——它不是死控件，
     * 是**没接上的快捷键**。接到 `script-09.js` 的出口 `window.showYouHuoCarePage`。
     * `.active` 跟着真面板走：在趋势面板上是「趋势」，其余六个面板都是「照护」。 */
    const careModes = $$('#careView .identity-island .mode button');
    if (careModes.length === 2 && typeof window.showYouHuoCarePage === 'function') {
      const [careBtn, trendBtn] = careModes;
      const syncCareMode = () => {
        const on = $('#careTabs [data-care-panel].active');
        const trend = !!on && on.dataset.carePanel === 'trend';
        trendBtn.classList.toggle('active', trend);
        careBtn.classList.toggle('active', !trend);
      };
      careBtn.addEventListener('click', () => {
        window.showYouHuoCarePage('overview');
        syncCareMode();
      });
      trendBtn.addEventListener('click', () => {
        window.showYouHuoCarePage('trend');
        syncCareMode();
      });
      //: `script-09.js` 在**捕获**阶段换 `.active`，所以冒泡到这里时已经是新值。
      $$('#careTabs [data-care-panel]').forEach(
        (t) => t.addEventListener('click', syncCareMode));
      syncCareMode();
    }

    /* 家人屏那一对「优活 / 无忧伴」：只说清，不切换。
     *
     * 家人**不该**能替老人切模式。那个切换在 `companion.py` 里由老人自己开口触发
     * （「找无忧伴聊聊」「陪伴模式」），而 `baseline_models.py:196` 规定日报里
     * 不含陪伴聊天的任何原文。给家人一个能替老人切模式的开关，正是这条边界要防的。
     *
     * 所以这一对不动 `.active`——而「优活」保持 active 是**成立的**：它说的是
     * 「你正在看的这一面是优活」，不是「他现在在优活模式」。后者这一面读不到，
     * 也不该读到。 */
    const famModes = $$('#familyView .identity-island .mode button');
    if (famModes.length === 2) {
      const [youhuoBtn, companionBtn] = famModes;
      youhuoBtn.addEventListener('click', () => {
        const back = $('#appFamily');
        if (back) back.click();
        say('这一屏就是优活这一面：缴费、买药、挂号这些他开口就能办，'
            + '办到哪一步这里都看得到。', 'good');
      });
      companionBtn.addEventListener('click', () => {
        /* 打开照护中心的「心情」——那是家人**能看到**的那一部分陪伴信息。
         *
         * `baseline_models.py:196` 规定日报不含陪伴聊天的任何原文，所以这一面
         * 看得到的是情绪的走向。这一下既是真导航，也把那条隐私边界摆在屏幕上，
         * 而不是只靠一句声明。 */
        const care = $('#appCare');
        if (care) care.click();
        if (typeof window.showYouHuoCarePage === 'function') {
          window.showYouHuoCarePage('mood');
        }
        say('无忧伴陪他说话的那一面在他自己那台手机上，要切过去得他自己开口说'
            + '「找无忧伴聊聊」——家人这里不替他切。他和无忧伴聊的原话也不会到'
            + '这里来，能看到的是心情的走向，已经给您打开了。', 'good');
      });
      /* 下划线要一直说真话。
       *
       * `script-07.js:43` 有一个纯视觉的监听，点哪个就把 `.active` 挪到哪个。
       * 这一对只在家人这一面上看得见，所以「看得见它 → 你在优活这一面」永远为真；
       * `#familyView` 一变回可见就把 active 归到「优活」。用属性观察器兜住全部
       * 路径：顶部切换、`#goCare`、底栏那个「照护」。 */
      const syncFamilyMode = () => {
        const view = $('#familyView');
        if (!view || view.hidden) return;
        youhuoBtn.classList.add('active');
        companionBtn.classList.remove('active');
      };
      const famView = $('#familyView');
      if (famView) {
        new MutationObserver(syncFamilyMode).observe(
          famView, {attributes: true, attributeFilter: ['hidden']});
      }
      syncFamilyMode();
    }

    /* 编辑器开着的时候把气泡抬到底栏之上——不然它的按钮**真人点不到**。
     *
     * `.bubble-flow` 是 `position:absolute; z-index:7`，它自己就是一个层叠上下文，
     * 所以 `.flow-editor` 的 `z-index:10` 只在气泡内部排序，整个气泡连编辑器一起
     * 落在 `.dock`（`z-index:8`）之下；而编辑器 `bottom:-58px` 挂在气泡下沿之外，
     * 正好进了底栏那一条。1280×720 量的三个中心点：
     *
     *     气泡下沿 631   底栏上沿 639   编辑器下沿 676
     *     「生成」-> SPAN.icon    「取消」-> NAV.dock    「提给他」-> BUTTON.clickable
     *
     * 交付包自带的那张一样点不到，这是先前就在的缺陷。四十多轮闸门没看见，
     * 是因为它按控件用 `element.click()` 派事件，而**合成点击不做命中测试**：
     * 一个被完全罩住的按钮照样会触发。
     *
     * 用属性观察器，不在开关那两处各加一行：待办那一张是 `script-06.js` 直接
     * `editor.hidden = false` 打开的，那是交付包的脚本。而且这里必须跑在上面
     * 那个 `strip()` 之后——`cloneNode` 会把原来的编辑器换掉，早了就观察到
     * 一个已经脱离文档的节点上。 */
    $$('.bubble-flow').forEach((flow) => {
      const editors = $$('.flow-editor', flow);
      if (!editors.length) return;
      const sync = () => flow.classList.toggle(
        'flow-editing', editors.some((e) => !e.hidden));
      const obs = new MutationObserver(sync);
      editors.forEach((e) => obs.observe(
        e, {attributes: true, attributeFilter: ['hidden']}));
      sync();
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
        /* 忙落在那个「×」上。
         *
         * 这一处原先**按下去真的什么都没有**：`say()` 只在响应回来之后才写，
         * 中间那一次往返里屏幕上一个像素都不动。而连点两次会送出两次取消，
         * 第二次后端会正确地拒绝（那一条已经取消了），屏幕上闪一句错误——
         * 读起来像是第一次没成功。
         *
         * `once()` 一次解决两件：`data-in-flight` 挡住第二次，`aria-busy`
         * 让那个「×」在办的时候看得出来（`components.css` 里那条）。 */
        /* **先问一句。**
         *
         * 这一处原先按下去直接就发 `cancel`。而这三条待办里有一条是
         * 「下午四点吃降压药」——一次误点，就是老人那天不会被提醒吃降压药，
         * 而这个「×」只有 11 像素见方。
         *
         * 同一屏上就医安排那一格的取消是两步（`visitCancel`），CSS 里还专门
         * 写着「它是这一格唯一撤不回来的动作。关键动作 ≥56px」。
         * 撤掉一条吃药提醒不比取消一次就医轻。照隔壁那一格来。
         *
         * 两个按钮长在气泡里，用 `.f3-fold-act`（48px）——真正要点的那一下
         * 是个写着字的按钮，不是那个 11px 的叉。 */
        if ($('.f3-flow-sure', item)) return;      // 已经问过了，别长第二个
        const what = (($('.flow-title', item) || {}).textContent || '这一条').trim();
        say(`要撤掉的是「${what}」。撤掉之后，到点就不会再提醒他了。`, 'warning');

        const sure = document.createElement('button');
        sure.type = 'button';
        sure.className = 'f3-fold-act f3-flow-sure';
        sure.textContent = '确认撤掉这条提醒';
        const keep = document.createElement('button');
        keep.type = 'button';
        keep.className = 'f3-fold-act f3-flow-keep';
        keep.textContent = '先不撤';
        keep.addEventListener('click', (ev) => {
          ev.stopPropagation();
          sure.remove();
          keep.remove();
          say('这一条留着，没有改动。', 'good');
        });
        sure.addEventListener('click', (ev) => {
          ev.stopPropagation();
          once(sure, async () => {
            try {
              const data = await api(
                `/api/v1/reminders/${encodeURIComponent(id)}/cancel`,
                {method: 'POST', body: JSON.stringify({})}, FAMILY);
              say(data.message || '这一条取消了。', YH.toneOf(data));
              loadFamilyFlow();
            } catch (err) {
              trouble(err, '这一条');
            }
          });
        });
        item.append(sure, keep);
      }, true);
    });

    // 一键联系子女
    $$('.dock .contact').forEach((old) => {
      const btn = strip(old);
      btn.addEventListener('click', () => once(btn, async () => {
        try {
          const data = await api('/api/v1/contacts', {}, FAMILY);
          if (!data.count) { say('还没有登记联系人。', 'warning'); return; }
          /* 这个控件叫「一键联系子女」，列的就该是子女。
           *
           * 原先不加筛选地把四条全列出来，于是屏幕上是
           * 「可以联系：儿子（家人）、女儿（家人）、优活系统（系统）、社区网格员（社区）」——
           * 把「优活系统」说成一个可以联系的人。这个文件里的 `NO_PHONE_WORD`
           * 自己就写着系统「不需要电话」、社区「号码由社区一方维护」，
           * 后端对社区联系人改号也直接 409。一个文件里两处相反的说法。
           *
           * 第二层：这几条**可能一个号码都没有**。那时不能说「可以联系」——
           * 说得像马上打得通，而实际上她还得自己去翻电话本。
           */
          const kin = (data.items || []).filter((c) => c.role === '家人');
          if (!kin.length) { say('还没有登记家人联系人。', 'warning'); return; }
          const withPhone = kin.filter((c) => c.phone);
          if (!withPhone.length) {
            say('登记了 ' + kin.map((c) => c.name).join('、')
              + '，但都还没有留电话号码。', 'warning');
            return;
          }
          say('可以联系：' + withPhone.map((c) => `${c.name} ${c.phone}`).join('、'), 'good');
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

    mountMedicationComposer();
    mountDoseActions();
    mountBodyComposer();
    mountRoutines();
    mountVisits();
    mountNotices();
    mountGuardians();
  }

  /** 优活发给家人的消息。
   *
   * `/v2/notifications` 是家人端一的一整格（`#notices`），设计三**一次都不调**。
   * 缺的不是「一个列表」：`approval_required` / `additional_approval_required` /
   * `reminder_escalated` 这几条正是**要子女动手**的那些——超时没办的待办、
   * 还差一位家属确认的接力。不接，这一版的家人永远不知道有人在等他。
   *
   * 标题表照抄家人端一那一份（`family.js::NOTICE_TITLE`），
   * 兜底也一样不是原始事件码：兜底成枚举名等于这层翻译在遇到没登记过的类型时
   * 自动失效，而那正是它该起作用的时候。
   *
   * **`emergency_call` 是后来补的，两个壳一起补。** 逐字复制的代价就在这里：
   * 后端会发九种 `event_type`（全仓 grep `event_type="…"`），两份表都只写了八个，
   * 漏的是同一个——老人按下紧急呼叫那一条。实测它在这一格里的标题是兜底的
   * 「来自优活的消息」，而未读时这一格只露标题。说法跟 `trust.js::NOTIFY_WORD`
   * 对齐（那一页叫「紧急联系」），三处别再各起一个名字。
   *
   * 想收敛成一份共享定义的话，落点是 `common.js`（这一页和 /family、/care 都加载
   * 它）——但那个文件不在这一轮的改动范围里，所以这里仍是两份，靠
   * `test_the_two_shells_agree_on_notice_titles` 钉住它们不许分叉。
   */
  //: 「这一笔还在等家属点头」的两种说法。任务一旦离开 awaiting_family_approval，
  //: 两条都该显示成已了结——少点一个名字，另一条就会继续催人。
  const SETTLES_WITH_THE_TASK = new Set([
    'approval_required',
    'additional_approval_required',
  ]);

  const NOTICE_TITLE = {
    approval_required: '需要您接力确认',
    additional_approval_required: '还需要另一位家属确认',
    task_rejected: '已按您的意见取消',
    task_completed: '任务已完成',
    family_reminder_created: '待办已同步到老人端',
    reminder_due: '待办到期提醒',
    reminder_advance_notice: '已提前提醒老人',
    reminder_escalated: '超时未完成，请接力',
    emergency_call: '紧急联系',
    elder_feels_unwell: '老人说身体不舒服，请联系确认',
    // 至此这张表覆盖的是**驱动出来**的类型，不是 grep 出来的。 上面那段说明里「全仓 grep 数出九个」的做法漏了三种写法： 位置实参（sos / geofence_exit / urgent_emotion 都是这么发的）、 事件名不是字面量（emergency / suspected_scam 来自 SafetySignal.category）， 以及大写的键。判据 `_backend_event_types()` 已经改成按 AST 数这三种。
    emergency: '可能摔倒了，请尽快联系',
    suspected_scam: '可能碰上诈骗，请尽快联系',
    sos: '老人按了紧急求助',
    urgent_emotion: '说了一句要马上确认的话',
    geofence_exit: '离开了常去的范围',
    inactivity_check: '很久没有动静了',
    medication_inventory: '药快不够了',
    BREAK_GLASS_OPENED: '已开启紧急查看',
  };

  function mountNotices() {
    const host = $('#familyFlow');
    if (!host || $('#f3Notices')) return;
    const box = document.createElement('section');
    box.id = 'f3Notices';
    box.className = 'f3-notices';
    box.hidden = true;
    host.insertAdjacentElement('afterend', box);
    loadNotices();
  }

  /** 读哪一份通知：**`/v2/notifications`，不换成 `/api/v1/notifications`。**
   *
   * 门面层确实有一条等价的（`app_api.py:2914`），而「标记已读」只在门面层上
   * （`POST /api/v1/notifications/{id}/read`）。所以问题是要不要整格搬过去。
   * 实测三件事之后决定不搬：
   *
   *   1. **收件人角色的来源不一样。** `/v2` 按调用者自己的角色取
   *      （家人令牌 → 家人那一批）；`/api/v1` 默认取**老人**那一批，
   *      要家人的得显式写 `?role=家人`。实测家人令牌不带参数调门面那条，
   *      回的是「账单已经由家人确认支付。」——那是发给老人的通知，
   *      而它出现在家人端上**看起来完全正常**。少写一个查询参数就把收件人
   *      换成了另一个人，这种失效方式屏幕上看不出来。
   *   2. **两边是同一批行、同一个 id。** 实测 `/v2` 给 `id: 1`，
   *      `POST /api/v1/notifications/1/read` 回 200，再取 `read` 变 true。
   *      也就是说「已读」这个动作**不需要**换数据源。
   *   3. 门面那份把 `event_type` 改名成 `eventType`。换过去等于把
   *      `NOTICE_TITLE` 的键名在两个壳里改成两个写法，而
   *      `test_the_notice_fallback_is_not_the_raw_event_code` 钉的正是这个名字。
   *
   * 结论：列表继续走 `/v2`，只把**写**那一半接到 `/api/v1` 上。不加第二份。
   */
  async function loadNotices() {
    const box = $('#f3Notices');
    if (!box) return;
    let rows;
    let taskRows = [];
    try {
      // 事务状态是**顺带**取的：取不到就退化成「按通知原样读」，不能让它拖垮这一格。
      [rows, taskRows] = await Promise.all([
        api('/v2/notifications?limit=50', {}, FAMILY),
        api('/v2/tasks?limit=100', {}, FAMILY).catch(() => []),
      ]);
    } catch (e) {
      // 安静地不显示。它是**额外**的一格，让它的失败盖掉今天那一屏不划算。
      box.hidden = true;
      return;
    }
    const items = Array.isArray(rows) ? rows : (rows.items || []);
    /* 「需要您接力确认」这条通知在那一笔办完之后**不会自己变样**：通知表只有
     * `read_at`，没有「已解决」。实测演示态里两条一字不差、都未读，而其中一条的
     * `entity_id` 指着一笔 `status=completed` 的事务——屏幕上却写着「请您核对之后
     * 确认」。两条长得一样，她分不出哪一条还需要动手。
     *
     * 按 `entity_id` 对一遍事务状态。**不删通知、不改库**：它是一条历史记录，
     * 改的只是这一屏怎么读它。 */
    const statusOf = new Map(
      (Array.isArray(taskRows) ? taskRows : (taskRows.items || []))
        .map((t) => [String(t.id), String(t.status)]));
    box.replaceChildren();
    if (!items.length) {
      box.hidden = true;      // 空的时候不占位，而不是留一格「暂无通知」
      return;
    }
    const unread = items.filter((n) => !n.read_at);
    const head = document.createElement('div');
    head.className = 'f3-fold-bar';
    const name = document.createElement('b');
    name.textContent = '优活给您的消息';
    const sum = document.createElement('span');
    sum.className = 'f3-fold-sum';
    /* 摘要说的是**还有几条没读**，不是一共几条。
     * 「一共 6 条」在全部读过之后还是 6 条——那一格于是永远在喊，
     * 而喊的内容和昨天一模一样，家人很快就不再看它。 */
    sum.textContent = unread.length
      ? `${unread.length} 条还没读，一共 ${items.length} 条`
      : `${items.length} 条都读过了`;
    const toggle = document.createElement('button');
    toggle.type = 'button';
    toggle.className = 'f3-fold-toggle';
    head.append(name, sum, toggle);
    box.append(head);

    const list = document.createElement('div');
    list.className = 'f3-fold-body';
    box.append(list);
    const setOpen = (on) => {
      list.hidden = !on;
      toggle.textContent = on ? '收起' : '展开';
      toggle.setAttribute('aria-expanded', on ? 'true' : 'false');
    };
    toggle.addEventListener('click', () => setOpen(list.hidden));
    // 有没读的就摊开。`approval_required` / `reminder_escalated` 这几条
    // 正是**要子女动手**的那些，收起来等于没接。全读过了才收。
    setOpen(unread.length > 0);

    items.slice(0, 6).forEach((n) => {
      const row = document.createElement('div');
      row.className = 'f3-notice-row';
      if (n.read_at) row.dataset.read = '1';
      // 这一条还在等她点头吗。只对「需要接力确认」那一类问这个问题——别的类型
      // （通知、紧急呼叫）本来就不是待办，没有「了结」可言。
      const taskState = statusOf.get(String(n.entity_id || ''));
      // 两条通知都是「这一笔在等家属点头」，了结的时候也得一起了结。
      // 原先只点了 `approval_required` 一个名字，于是一笔已经付掉的账
      // 会并排出现两行、说相反的话：一行「这一件不用您再确认」，
      // 一行「还需要另一位家属确认」，后者还带着活的「知道了」。
      const settled = SETTLES_WITH_THE_TASK.has(n.event_type)
        && !!taskState && taskState !== 'awaiting_family_approval';
      if (settled) row.dataset.settled = '1';
      const title = document.createElement('b');
      title.textContent = settled
        ? '这一件不用您再确认'
        : (NOTICE_TITLE[n.event_type] || '来自优活的消息');
      const body = document.createElement('span');
      body.textContent = n.message || '';
      const when = document.createElement('time');
      when.dateTime = n.created_at || '';
      when.textContent = n.created_at
        ? new Date(n.created_at).toLocaleString('zh-CN', {hour12: false}) : '';
      row.append(title, body, when);
      if (settled) {
        // 说清是**怎么**了结的。只说「不用确认了」会让人以为是被系统吃掉了。
        const how = document.createElement('i');
        how.className = 'f3-notice-settled';
        /* 说法取共享表，**不另写一套**。
         *
         * 这里原先是一张自己的 `SETTLED_WORD`（「这一件已经办好了」之类），
         * 而它的键就是 `TaskStatus` 的取值——于是
         * `test_one_status_has_one_word.py` 把它当成第二张状态词表收了进去，
         * 整套四条红。判据是对的：同一批状态两套说法，将来只会改一份。
         *
         * `'other'` 那个实参是必须的：这一屏是家人在读老人的事。
         * 漏传它的实测后果记在 `fillPlanner` 上面那段注释里。 */
        how.textContent = taskState
          ? `这一件${YH.statusWord(taskState, 'other')}`
          : '这一件已经不在等您了';
        row.append(how);
      }
      if (n.read_at) {
        // 读过的**留在原地**，只是不再给按钮。撤掉整行等于家人一按就找不着了，
        // 而她可能只是想再看一眼刚才那条说了什么。
        const done = document.createElement('i');
        done.className = 'f3-notice-done';
        done.textContent = '已读';
        row.append(done);
      } else {
        const ok = document.createElement('button');
        ok.type = 'button';
        ok.className = 'f3-notice-read';
        ok.textContent = '知道了';
        ok.addEventListener('click', () => once(ok, async () => {
          try {
            await api(`/api/v1/notifications/${encodeURIComponent(n.id)}/read`,
                      {method: 'POST', body: JSON.stringify({})}, FAMILY);
            say('这一条记成读过了。', 'good');
            loadNotices();
          } catch (e) {
            // 同一条按两次会走 404（「没有找到这条通知，或者它已经读过了。」）。
            // 那句话比这里能写的清楚，照原样给出去。
            trouble(e, '这条消息');
          }
        }));
        row.append(ok);
      }
      // 六条之外的先不摆。这一格是「有人在等你」，不是收件箱。
      list.append(row);
    });
    box.hidden = false;
  }

  /** 「记一次已吃 / 这次没吃」。
   *
   * `/care` 那一屏有这两个动作（`care.js` 打 `/api/v1/medications/{id}/taken`
   * 与 `/skipped`），设计三的照护屏**一个都没有**——它只把用药计划列出来看。
   * 于是这一版的家人能看到「在吃什么药」，却记不了「今天这一顿吃没吃」，
   * 而扣库存、余量预警全都挂在这条动作上：不记，「还够吃几天」永远不动。
   *
   * 不塞进 `.medicine-seal` 里：那两张卡的位置由 CSS 的 `med-a` / `med-b` 定死，
   * 往里加按钮会把它们撑出画面。改成卷轴下面一行一条，药名写在动作旁边——
   * 两份药各自一行，不会点错。
   */
  function mountDoseActions() {
    const stage = $('[data-care-page="med"] .medicine-stage');
    if (!stage || $('.f3-dose', stage)) return;
    const box = document.createElement('div');
    box.className = 'f3-dose';
    box.hidden = true;
    stage.append(box);
  }

  function fillDoseActions(plans) {
    const box = $('[data-care-page="med"] .f3-dose');
    if (!box) return;
    // 只给**已经生效**的计划记。待老人确认的那些还没开始吃，
    // 给它们一个「记一次已吃」就是在替她把那一步跳过去。
    const live = (plans || []).filter((p) => p.active !== false);
    box.replaceChildren();
    box.hidden = !live.length;
    if (!live.length) return;

    const head = document.createElement('p');
    head.className = 'f3-dose-head';
    head.textContent = '这一顿吃了没有？记一笔，余量才算得准。';
    box.append(head);

    live.forEach((p) => {
      const row = document.createElement('div');
      row.className = 'f3-dose-row';
      const name = document.createElement('b');
      name.textContent = p.display_name || '这份药';
      const took = document.createElement('button');
      took.type = 'button';
      took.textContent = '记一次已吃';
      const missed = document.createElement('button');
      missed.type = 'button';
      missed.className = 'f3-dose-skip';
      missed.textContent = '这次没吃';
      const hit = (what) => once(what === 'taken' ? took : missed, async () => {
        try {
          const data = await api(
            `/api/v1/medications/${encodeURIComponent(p.id)}/${what === 'taken' ? 'taken' : 'skipped'}`,
            {method: 'POST', body: JSON.stringify({})}, FAMILY);
          say(data.message || '记下了。', YH.toneOf(data));
          loadCare();
        } catch (e) {
          // 同一格重复记会走 409，后端那句话（「今天该吃的都记过了」）
          // 比这里能写的清楚，照原样给出去。
          trouble(e, '这一次用药');
        }
      });
      took.addEventListener('click', () => hit('taken'));
      missed.addEventListener('click', () => hit('skipped'));
      row.append(name, took, missed);
      box.append(row);
    });
  }

  /** 「记一次身体数据」。
   *
   * 身体那一屏此前**只读**：`/v4/health/events` 拉出来列一列，没有任何入口
   * 能新增一条。而它下面那句写着「老人端量过血压、体温之后，这里会出现记录」——
   * 老人端确实能记，但家人陪着量完想替他记一笔时无处可记，`/care` 那一屏是有的。
   */
  function mountBodyComposer() {
    const stage = $('[data-care-page="body"] .body-stage');
    if (!stage || $('.f3-body-add', stage)) return;

    const open = document.createElement('button');
    open.type = 'button';
    open.className = 'f3-body-add';
    open.textContent = '记一次身体数据';

    const form = document.createElement('form');
    form.className = 'f3-body-form';
    form.hidden = true;
    const field = (nm, label, ph) => {
      const wrap = document.createElement('label');
      const span = document.createElement('span');
      span.textContent = label;
      const input = document.createElement('input');
      input.name = nm;
      input.type = 'text';
      input.placeholder = ph;
      input.required = true;
      wrap.append(span, input);
      return wrap;
    };
    const hint = document.createElement('p');
    hint.className = 'f3-body-hint';
    // 值保持字符串：血压是「128/82」，不是一个数。
    hint.textContent = '血压这类写成「128/82」就行，不用拆成两个数。';
    const row = document.createElement('div');
    row.className = 'f3-body-row';
    const submit = document.createElement('button');
    submit.type = 'submit';
    submit.textContent = '记下';
    const cancel = document.createElement('button');
    cancel.type = 'button';
    cancel.className = 'f3-body-cancel';
    cancel.textContent = '先不记';
    row.append(submit, cancel);
    form.append(field('label', '记什么', '例如：血压'),
                field('value', '数值', '例如：128/82'), hint, row);
    stage.append(open, form);

    open.addEventListener('click', () => {
      form.hidden = !form.hidden;
      if (!form.hidden) $('input', form).focus();
    });
    cancel.addEventListener('click', () => { form.hidden = true; });

    form.addEventListener('submit', (e) => {
      e.preventDefault();
      const fd = new FormData(form);
      const label = String(fd.get('label') || '').trim();
      const value = String(fd.get('value') || '').trim();
      if (!label || !value) { say('记什么、多少，两样都要填。', 'warning'); return; }
      once(submit, async () => {
        try {
          const data = await api('/api/v1/health/events', {
            method: 'POST',
            body: JSON.stringify({type: label, value}),
          }, FAMILY);
          form.reset();
          form.hidden = true;
          say(data.message || '记下了。', YH.toneOf(data));
          loadCare();
        } catch (err) {
          // 一分钟内同一项同一个读数会被当成手抖挡下来（409）。
          trouble(err, '这一条记录');
        }
      });
    });
  }

  /* ==========================================================================
     照护中心 · 固定安排 与 就医安排
     ..........................................................................
     两条能力后端都是齐的（`/api/v1/routines*`、`/api/v1/appointments*`），
     而这一版前端**一处都不调**。

     ## 放在照护屏上要先解决一个空间问题

     七个子屏都是 `position:absolute; inset:0` 的**定高**盒子（实测 1440×900 下
     907×738），里面的美术件——节律环、水纹图、药卷轴——也全是绝对定位的，
     整屏没有滚动。往里塞一整张列表只能盖在美术件上。

     所以这两块都是**折叠卡**：默认只有一行摘要，而那一行本身要能回答
     「有没有、有几件」；展开才是要动手的时候。这也正是这一屏上
     「给老人加一份药」「记一次身体数据」的形状——不另起一套。
     ========================================================================== */

  /** 折叠卡的外壳。返回 `{box, sum, body, setOpen}`。 */
  function foldCard(host, cls, title) {
    const box = document.createElement('section');
    box.className = `f3-fold ${cls}`;
    const bar = document.createElement('div');
    bar.className = 'f3-fold-bar';
    const name = document.createElement('b');
    name.textContent = title;
    const sum = document.createElement('span');
    sum.className = 'f3-fold-sum';
    const toggle = document.createElement('button');
    toggle.type = 'button';
    toggle.className = 'f3-fold-toggle';
    toggle.textContent = '展开';
    toggle.setAttribute('aria-expanded', 'false');
    bar.append(name, sum, toggle);
    const body = document.createElement('div');
    body.className = 'f3-fold-body';
    body.hidden = true;
    box.append(bar, body);
    host.append(box);

    const setOpen = (on) => {
      body.hidden = !on;
      toggle.textContent = on ? '收起' : '展开';
      toggle.setAttribute('aria-expanded', on ? 'true' : 'false');
    };
    toggle.addEventListener('click', () => setOpen(body.hidden));
    return {box, sum, body, setOpen};
  }

  /** 表单里的一格。`control` 是已经建好的 input / select。 */
  function fieldRow(word, control) {
    const wrap = document.createElement('label');
    const span = document.createElement('span');
    span.textContent = word;
    wrap.append(span, control);
    return wrap;
  }

  function textInput(name, type, placeholder, required) {
    const el = document.createElement('input');
    el.name = name;
    el.type = type;
    if (placeholder) el.placeholder = placeholder;
    el.required = required !== false;
    return el;
  }

  function pickOne(name, options) {
    const el = document.createElement('select');
    el.name = name;
    options.forEach(([value, word]) => {
      const opt = document.createElement('option');
      opt.value = value;
      opt.textContent = word;
      el.append(opt);
    });
    return el;
  }

  function formButtons(doWord, undoWord) {
    const row = document.createElement('div');
    row.className = 'f3-fold-buttons';
    const submit = document.createElement('button');
    submit.type = 'submit';
    submit.textContent = doWord;
    const cancel = document.createElement('button');
    cancel.type = 'button';
    cancel.className = 'f3-fold-cancel';
    cancel.textContent = undoWord;
    row.append(submit, cancel);
    return {row, submit, cancel};
  }

  /** 「加一件…」按钮 + 收起来的表单，两个一起装。 */
  function composer(host, openWord, form) {
    const open = document.createElement('button');
    open.type = 'button';
    open.className = 'f3-fold-add';
    open.textContent = openWord;
    host.append(open, form);
    open.addEventListener('click', () => {
      form.hidden = !form.hidden;
      if (!form.hidden) {
        const first = $('input, select', form);
        if (first) first.focus();
      }
    });
    return open;
  }

  /* ---- 固定安排（循环例程）------------------------------------------------
   *
   * ## 它和「待办」不是一回事
   *
   * 提醒是一次性的一条，例程是**生成器**：`materialize_routines` 为每一次发生
   * 真的插一条提醒（`source="routine:<id>"`），所以今日安排会自动认它们。
   * 想说「每天早上八点量血压」，这一版此前唯一的办法是一天建一条。
   *
   * ## 建完必须当场排期——这一层已经替我们做了，但要核对
   *
   * `POST /v4/routines/materialize` **只允许家属或系统触发**。不当场排期的例程
   * 会一直停在那儿什么都不发生，而界面上它看起来建好了。实测
   * `POST /api/v1/routines`（每天 08:30）回 `scheduled: 7`——建完顺手把最近
   * 一周排了出来。所以回执必须把 `scheduled` 说出来：它等于 0 的时候
   * **不能**说「排好了」。
   *
   * ## 摘要自己算，不转发后端那句 `message`
   *
   * 实测：建一件例程再把它暂停，`GET /api/v1/routines` 回的是
   * `count: 1` 配 `message: "您还没有固定安排。…"`——那句话只数在跑的那些。
   * 照抄就会在同一屏上同时出现「您还没有固定安排」和一行写着「量血压」的记录。
   * 后端的缺陷记在报告里，这一侧不把它搬上屏幕。
   */

  const ROUTINE_KINDS = ['生活', '用药', '就医', '缴费', '社交'];
  //: 0 是周一。后端的话是「星期几要在 0（周一）到 6（周日）之间」。
  const WEEKDAY_WORDS = ['周一', '周二', '周三', '周四', '周五', '周六', '周日'];

  /* ---- 守护那四格：点开之后真的有东西 ------------------------------------ */

  /** 安全那一屏的四个 `.guard-node`，点下去只有一句旁白：
   *
   *     小优：这是一个安全守护项目。点开后可以继续查看具体设置和状态。
   *
   * 旁白来自交付包（`family3/script-12.js:698`），而**没有任何东西会点开**。
   * 实测那一下除了这句话，屏幕上一个字都不多（空转对照 4.5 秒零变化）。
   *
   * 一句关于「点开之后有什么」的承诺，比什么都不说更糟——她会一直点。
   * 所以这里把那句话变成真的：四格各自对应一块真内容。
   *
   * 数据不重新要：`loadCare()` 已经取过 `/v4/safety/policy` 和
   * `/api/v1/contacts`，那里存进 `guardPolicy` / `guardContacts`。
   * 只有在还没取到时（她先点了这一格）才自己去取一次。
   */
  let guardCard = null;
  let guardPolicy = null;
  let guardContacts = null;
  let guardOpen = null;

  const GUARD_WORDS = {
    contacts: '家人联系人',
    inactivity: '久未活动',
    urgent: '紧急联系',
    fence: '活动范围',
  };

  /** 没有号码时，这一行该说什么。
   *
   * 「还没登记号码」只对**能登记**的那一类成立。实测那一版四行里有两行在
   * 说假话：「优活系统 · 还没登记号码」——优活系统不是一个能打电话的人；
   * 「社区网格员」的号码后端恒为 null（库里存的是打过码的号，拨不出去）。
   * 两句都读起来像家人漏了一件该做的事，而这两件事她做不了、也不该做。
   */
  const NO_PHONE_WORD = {
    系统: '系统 · 不需要电话',
    社区: '社区 · 号码由社区一方维护',
  };

  async function ensureGuardData() {
    if (guardContacts) return;
    const [policy, contacts] = await Promise.all([
      api(`/v4/safety/policy/${encodeURIComponent(ELDER_ID)}`, {}, FAMILY).catch(() => null),
      api('/api/v1/contacts', {}, FAMILY).catch(() => ({items: [], count: 0})),
    ]);
    guardPolicy = policy;
    guardContacts = contacts;
  }

  function guardRow(word, detail) {
    const row = document.createElement('div');
    row.className = 'f3-fold-row';
    const b = document.createElement('b');
    b.textContent = word;
    const span = document.createElement('span');
    span.textContent = detail;
    row.append(b, span);
    return row;
  }

  function mountGuardians() {
    const stage = $('[data-care-page="safety"] .safety-stage');
    if (!stage || $('.f3-guardians', stage)) return;
    guardCard = foldCard(stage, 'f3-guardians', '守护设置');

    const hint = document.createElement('p');
    hint.className = 'f3-fold-hint';
    const rows = document.createElement('div');
    rows.className = 'f3-fold-rows';
    guardCard.body.append(hint, rows);

    /* 登记电话。
     *
     * 后端 `PUT /api/v1/contacts/{id}/phone` 一直在，校验也一直是对的
     * （只有家人能改；老人来是 403，量过）。缺的一直是**调用方**——
     * 前端一个都没有，所以 `phone` 永远是 null。这里是第一个。 */
    const form = document.createElement('form');
    form.className = 'f3-fold-form';
    form.hidden = true;
    const who = pickOne('contact', []);
    //: `required` 给 false：留空再按「登记」是**清掉号码**，那是后端支持的动作。
    const num = textInput('phone', 'tel', '例如 13800001234', false);
    const formHint = document.createElement('p');
    formHint.className = 'f3-fold-hint';
    formHint.textContent = '登记之后，老人点一下这一位，就会多出一个「打给他」的按钮。'
                         + '留空再按「登记」，是把已经登记的号码清掉。';
    const {row: buttons, submit, cancel} = formButtons('登记', '先不改');
    form.append(fieldRow('给谁登记', who), fieldRow('电话号码', num), formHint, buttons);
    const addBtn = composer(guardCard.body, '登记电话', form);
    cancel.addEventListener('click', () => { form.hidden = true; });

    async function openGuardian(key) {
      const word = GUARD_WORDS[key];
      if (!word) return;
      try {
        await ensureGuardData();
      } catch (e) { trouble(e, '安全设置'); return; }

      text(guardCard.sum, word);
      guardCard.setOpen(true);
      rows.replaceChildren();

      const onContacts = key === 'contacts';
      addBtn.hidden = !onContacts;
      if (!onContacts) form.hidden = true;

      if (onContacts) {
        const people = (guardContacts && guardContacts.items) || [];
        hint.textContent = people.length
          ? '紧急的时候，优活按这份名单找人。'
          : '这份名单还是空的——紧急的时候优活找不到人。';
        people.forEach((c) => {
          rows.append(guardRow(
            c.primary ? `${c.name}（优先联系）` : c.name,
            /* 号码只在**真有**的时候说出来。
             * 「社区」那一类的 `phone` 后端恒为 null（库里存的是打过码的号，
             * 拨不出去），所以那一行说的是「由社区一方维护」，
             * 不是「还没登记」——后者读起来像家人漏了一件该做的事。 */
            c.phone ? `${c.role} · ${c.phone}`
                    : (NO_PHONE_WORD[c.role] || `${c.role} · 还没登记号码`)));
        });
        //: 只有 `actors` 表里的家人能登记（社区那一类后端回 409）。
        const kin = people.filter((c) => c.role === '家人');
        who.replaceChildren();
        kin.forEach((c) => {
          const opt = document.createElement('option');
          opt.value = c.id;
          opt.textContent = c.name;
          who.append(opt);
        });
        if (!kin.length) { addBtn.hidden = true; form.hidden = true; }
      } else if (key === 'inactivity') {
        const minutes = guardPolicy && guardPolicy.inactivity_minutes;
        hint.textContent = '这一项由安全策略决定，这一版还不能在这一页改。';
        rows.append(guardRow('多久没动静就提醒',
          minutes ? `超过 ${Math.round(minutes / 60)} 小时（${minutes} 分钟）`
                  : '还没有设置'));
        rows.append(guardRow('提醒谁', '先提醒家人，不会先打扰老人。'));
      } else if (key === 'urgent') {
        const community = !!(guardPolicy && guardPolicy.notify_community);
        hint.textContent = '这一项由安全策略决定，这一版还不能在这一页改。';
        //: 这两行说的是**量到的那件事**：一条通知、发给家人；社区只在名单上。
        rows.append(guardRow('按下呼救之后',
          '优活当场通知家人：老人主动呼救，请立即联系确认。'));
        rows.append(guardRow('社区那一位',
          community ? '也在这次呼救的名单上——优活不会替您打给他。'
                    : '不在这次呼救的名单上。'));
      } else if (key === 'fence') {
        const radius = guardPolicy && guardPolicy.geofence_radius_m;
        hint.textContent = '这一项由安全策略决定，这一版还不能在这一页改。';
        rows.append(guardRow('离家多远会提醒',
          radius ? `超过 ${radius} 米` : '还没有设置'));
        //: 家的坐标**不往屏幕上放**：这一页是可以被别人看到的。
        rows.append(guardRow('家在哪里', '已经登记，这一页不显示具体位置。'));
      }
      guardCard.box.scrollIntoView({block: 'nearest'});
    }
    guardOpen = openGuardian;

    document.addEventListener('click', (e) => {
      const node = e.target.closest('[data-care-page="safety"] .guard-node');
      if (!node) return;
      const key = node.dataset.guard;
      /* 还没打上 key 就说实话。
       *
       * `dataset.guard` 是 `loadCare()` 填这四格时打上的。没有它就说明这一屏
       * 的数据还没到——这时按 `b` 里的字去猜是哪一项，猜错就是给她看另一项的
       * 设置。宁可让她再点一下。 */
      if (!key) { say('安全设置还没取到，等一下再点这一格。', 'warning'); return; }
      openGuardian(key);
    });

    form.addEventListener('submit', (e) => {
      e.preventDefault();
      const id = who.value;
      if (!id) { say('还没有可以登记号码的家人。', 'warning'); return; }
      const phone = num.value.trim();
      once(submit, async () => {
        try {
          const data = await api(
            `/api/v1/contacts/${encodeURIComponent(id)}/phone`,
            {method: 'PUT', body: JSON.stringify({phone: phone || null})}, FAMILY);
          form.hidden = true;
          num.value = '';
          guardContacts = null;          //: 存的那份过期了，下一次重新取
          /* 这句话只能说老人那一端**真会**发生的事。
           *
           * 那边是「点一下这一位 → 出现一个『打给儿子』的按钮 → 再按才拨」，
           * 不是点一下就拨出去。写成「点一下就能打出去」会让她以为老人可能
           * 手一抖就打扰了在上班的儿子——而那正是那一步存在的原因。 */
          say(data.phone
            ? `${data.name}的电话记好了：${data.phone}。`
              + `老人点一下${data.name}，就会出现「打给${data.name}」那个按钮。`
            : `${data.name}的电话已经清掉了，老人那一端不会再有拨出去的按钮。`, 'good');
          await openGuardian('contacts');
          loadCare();                    //: 那四格上的「几人」也要跟着变
        } catch (err) { trouble(err, '这个号码'); }
      });
    });
  }

  let routineCard = null;

  function mountRoutines() {
    const stage = $('[data-care-page="today"] .rhythm-stage');
    if (!stage || $('.f3-routines', stage)) return;
    const card = foldCard(stage, 'f3-routines', '固定安排');
    const rows = document.createElement('div');
    rows.className = 'f3-fold-rows';
    card.body.append(rows);

    const form = document.createElement('form');
    form.className = 'f3-fold-form';
    form.hidden = true;
    const repeat = pickOne('repeat', [['每天', '每天'], ['每周', '每周'], ['每月', '每月']]);
    const weekday = pickOne('weekday', WEEKDAY_WORDS.map((w, i) => [String(i), w]));
    const monthday = pickOne('dayOfMonth',
      Array.from({length: 28}, (unused, i) => [String(i + 1), `${i + 1} 号`]));
    const kind = pickOne('category', ROUTINE_KINDS.map((k) => [k, k]));
    const weekRow = fieldRow('星期几', weekday);
    const monthRow = fieldRow('几号', monthday);
    weekRow.hidden = true;
    monthRow.hidden = true;
    repeat.addEventListener('change', () => {
      weekRow.hidden = repeat.value !== '每周';
      monthRow.hidden = repeat.value !== '每月';
    });
    const hint = document.createElement('p');
    hint.className = 'f3-fold-hint';
    /* 上限 28 号不是随便定的：29–31 号不是每个月都有，排到二月会静默少一次，
     * 而老人只会看到「这个月怎么没提醒我」。后端就是这么挡的，这里说出来。 */
    hint.textContent = '每月只能选到 28 号——29 号之后不是每个月都有，'
                     + '排到二月会静默少一次。';
    const {row: buttons, submit, cancel} = formButtons('加上', '先不加');
    form.append(
      fieldRow('这件事叫什么', textInput('title', 'text', '例如：量血压')),
      fieldRow('几点', textInput('time', 'time')),
      fieldRow('多久一次', repeat), weekRow, monthRow,
      fieldRow('归到哪一类', kind), hint, buttons);

    composer(card.body, '加一件固定安排', form);
    cancel.addEventListener('click', () => { form.hidden = true; });

    form.addEventListener('submit', (e) => {
      e.preventDefault();
      const fd = new FormData(form);
      const title = String(fd.get('title') || '').trim();
      const time = String(fd.get('time') || '').trim();
      if (!title || !time) { say('事项和时间都要填。', 'warning'); return; }
      const payload = {title, time, repeat: repeat.value, category: kind.value};
      if (repeat.value === '每周') payload.weekdays = [Number(weekday.value)];
      if (repeat.value === '每月') payload.dayOfMonth = Number(monthday.value);
      once(submit, async () => {
        try {
          const data = await api('/api/v1/routines', {
            method: 'POST', body: JSON.stringify(payload),
          }, FAMILY);
          form.reset();
          weekRow.hidden = true;
          monthRow.hidden = true;
          form.hidden = true;
          /* 一条都没排上就**不是**好消息。后端那句话这时说的是
           * 「记下了：…。最近一周还没有要排的。」——语气跟着 `scheduled` 走，
           * 不然「好，每天 08:30 提醒您量血压」和「记下了但什么都没排」
           * 在屏幕上是同一种绿色。 */
          say(data.message, data.scheduled ? YH.toneOf(data) : 'warning');
          loadRoutines();
          loadFamilyFlow();     // 排出去的那几条会出现在今日待办里
        } catch (err) { trouble(err, '这件固定安排'); }
      });
    });
    routineCard = {card, rows};
  }

  async function loadRoutines() {
    if (!routineCard) return;
    const {card, rows} = routineCard;
    let data;
    try {
      data = await api('/api/v1/routines', {}, FAMILY);
    } catch (e) {
      card.sum.textContent = errorWords(e, '固定安排').text;
      rows.replaceChildren();
      return;
    }
    const items = data.items || [];
    const running = items.filter((r) => r.active);
    card.sum.textContent = items.length
      ? `${running.length} 件在提醒`
        + (items.length > running.length ? `，${items.length - running.length} 件已暂停` : '')
      : '还没有。像「每天早上八点量血压」这种，可以在这里记下来。';
    rows.replaceChildren();
    items.forEach((r) => {
      const row = document.createElement('div');
      row.className = 'f3-fold-row';
      if (!r.active) row.dataset.paused = '1';
      const head = document.createElement('b');
      head.textContent = `${r.repeatText} ${r.time} · ${r.title}`;
      const meta = document.createElement('span');
      // `category` / `status` 后端给的就是中文（生活 / 进行中 …），不再翻一遍。
      meta.textContent = [r.category, r.status, r.nextText ? `下次 ${r.nextText}` : null]
        .filter(Boolean).join(' · ');
      const act = document.createElement('button');
      act.type = 'button';
      act.className = 'f3-fold-act';
      act.textContent = r.active ? '先不提醒' : '继续提醒';
      act.addEventListener('click', () => once(act, async () => {
        try {
          const done = await api(
            `/api/v1/routines/${encodeURIComponent(r.id)}/${r.active ? 'pause' : 'resume'}`,
            {method: 'POST', body: JSON.stringify({})}, FAMILY);
          // 暂停**不撤**已经排出去的提醒。后端那句话把这件事说清楚了
          // （「已经排出去的那几条还在。」），照原样给出去。
          say(done.message, YH.toneOf(done));
          loadRoutines();
        } catch (e) { trouble(e, '这件固定安排'); }
      }));
      row.append(head, meta, act);
      rows.append(row);
    });
  }

  /* ---- 就医安排 ------------------------------------------------------------
   *
   * 放在「身体」这一屏：那一屏本来就在列 `/v4/health/events` 的就诊与体检记录，
   * 「已经去过的」和「接下来要去的」是同一件事的两头。
   *
   * ## 取消是不可逆的，所以是两步
   *
   * 第二个按钮**一开始不在 DOM 里**，不是 disabled 也不是 hidden——一个看得见的
   * 「确认取消」会让人以为「点两下就没了」。设计三的删除预览是这个规矩
   * （`test_deleting_is_two_steps_and_the_second_button_does_not_exist_yet`），
   * 这里不另立一套。
   *
   * ## 取消必须连提醒一起撤
   *
   * 建安排时后端**同时**建了一条到点提醒（不建的话没有任何东西会叫老人）。
   * 只取消一半，老人到点还是会被提醒去一个已经取消了的门诊。
   * 实测 `POST /api/v1/appointments/{id}/cancel`：那条提醒跟着变
   * `cancelled`，而**没被取消的另一次，它的提醒原样留着**（两个方向都量过）。
   */

  let visitCard = null;

  function mountVisits() {
    const stage = $('[data-care-page="body"] .body-stage');
    if (!stage || $('.f3-visits', stage)) return;
    const card = foldCard(stage, 'f3-visits', '就医安排');
    const rows = document.createElement('div');
    rows.className = 'f3-fold-rows';
    card.body.append(rows);

    const form = document.createElement('form');
    form.className = 'f3-fold-form';
    form.hidden = true;
    const hint = document.createElement('p');
    hint.className = 'f3-fold-hint';
    hint.textContent = '记下之后会同时排一条到点提醒，老人那边也看得到。';
    const {row: buttons, submit, cancel} = formButtons('记下', '先不记');
    form.append(
      fieldRow('去哪家医院', textInput('hospital', 'text', '例如：市第一医院')),
      fieldRow('哪个科', textInput('department', 'text', '例如：心内科', false)),
      fieldRow('哪位医生', textInput('doctor', 'text', '不知道就空着', false)),
      fieldRow('哪一天', textInput('date', 'date')),
      fieldRow('几点', textInput('time', 'time')),
      hint, buttons);

    composer(card.body, '记一次就医安排', form);
    cancel.addEventListener('click', () => { form.hidden = true; });

    form.addEventListener('submit', (e) => {
      e.preventDefault();
      const fd = new FormData(form);
      const hospital = String(fd.get('hospital') || '').trim();
      const date = String(fd.get('date') || '').trim();
      if (!hospital || !date) { say('医院和日期都要填。', 'warning'); return; }
      once(submit, async () => {
        try {
          const data = await api('/api/v1/appointments', {
            method: 'POST',
            body: JSON.stringify({
              hospital, date,
              department: String(fd.get('department') || '').trim(),
              doctor: String(fd.get('doctor') || '').trim(),
              time: String(fd.get('time') || '').trim(),
            }),
          }, FAMILY);
          form.reset();
          form.hidden = true;
          /* `reminderId` 为 null 表示**只记下了安排，到点没有任何东西会叫她**
           * （实测：日期不是 `2026-09-03` 这种写法时就会这样，接口照样回 200）。
           * 后端那句话这时会少掉「到点我会提醒您」，但少一句话不等于说清楚了。 */
          say(data.reminderId ? data.message
                              : `${data.message}这一次没能排上提醒，到点不会有人叫她。`,
              data.reminderId ? YH.toneOf(data) : 'warning');
          loadVisits();
          loadFamilyFlow();
        } catch (err) { trouble(err, '这次就医安排'); }
      });
    });
    visitCard = {card, rows};
  }

  async function loadVisits() {
    if (!visitCard) return;
    const {card, rows} = visitCard;
    let data;
    try {
      data = await api('/api/v1/appointments', {}, FAMILY);
    } catch (e) {
      card.sum.textContent = errorWords(e, '就医安排').text;
      rows.replaceChildren();
      return;
    }
    const items = data.items || [];
    // `status` 后端给的就是中文（已预约 / 已取消 / 已完成）。
    const live = items.filter((v) => v.status === '已预约');
    card.sum.textContent = items.length
      ? `${live.length} 次还没去`
        + (items.length > live.length ? `，另有 ${items.length - live.length} 次已结束` : '')
      : '还没有记过就医安排。';
    rows.replaceChildren();
    items.forEach((v) => {
      const row = document.createElement('div');
      row.className = 'f3-fold-row';
      if (v.status !== '已预约') row.dataset.paused = '1';
      const head = document.createElement('b');
      head.textContent = `${v.date} ${v.time} · ${v.hospital}${v.department || ''}`;
      const meta = document.createElement('span');
      // 「到点会不会提醒」要写出来。
      //
      // 取消范围是单向的：从这张卡取消就医安排会连提醒一起撤（下面那句
      // 二次确认写着这件事），而在**提醒**那一侧单独取消，这一条仍然是
      // 「已预约」。实测过那一屏：一条「第二人民医院 15:00 已预约」，
      // 而「今日安排」是 0 条——没有任何东西会叫她去。
      //
      // 后端现在会给 `reminds`（`AppAppointment.reminds`）。只在「已预约」
      // 而且不提醒时才多说一句：其余情形说了是噪音。
      const note = (v.status === '已预约' && v.reminds === false)
        ? '到点不会提醒' : null;
      meta.textContent = [v.doctor || null, v.status, note].filter(Boolean).join(' · ');
      row.append(head, meta);
      if (v.status === '已预约') row.append(visitCancel(row, v));
      rows.append(row);
    });
  }

  /** 「取消这一次」——只**说清楚要取消的是哪一次**，不取消。
   *
   * 真正的取消是它按下去之后另外长出来的那个按钮。 */
  function visitCancel(row, v) {
    const ask = document.createElement('button');
    ask.type = 'button';
    ask.className = 'f3-fold-act f3-visit-drop';
    ask.textContent = '取消这一次';
    ask.addEventListener('click', () => {
      if ($('.f3-visit-sure', row)) return;      // 已经问过了，别长第二个
      say(`要取消的是 ${v.date} ${v.time} ${v.hospital}${v.department || ''}那一次。`
          + '取消之后，到点那条提醒也会一起撤掉，这一步撤不回来。', 'warning');
      const sure = document.createElement('button');
      sure.type = 'button';
      sure.className = 'f3-fold-act f3-visit-sure';
      sure.textContent = '确认取消，连提醒一起撤';
      const keep = document.createElement('button');
      keep.type = 'button';
      keep.className = 'f3-fold-act f3-visit-keep';
      keep.textContent = '先不取消';
      keep.addEventListener('click', () => {
        sure.remove();
        keep.remove();
        say('这一次留着，没有改动。', 'good');
      });
      sure.addEventListener('click', () => once(sure, async () => {
        try {
          const done = await api(
            `/api/v1/appointments/${encodeURIComponent(v.id)}/cancel`,
            {method: 'POST', body: JSON.stringify({})}, FAMILY);
          say(done.message, YH.toneOf(done));
          loadVisits();
          // 那条到点提醒也没了，今日待办要跟着变——不刷新的话屏幕上它还在。
          loadFamilyFlow();
        } catch (e) {
          // 已经取消过的会走 409（「这一次已经取消过了。」）。
          trouble(e, '这一次就医');
        }
      }));
      row.append(sure, keep);
    });
    return ask;
  }

  /** 「给老人加一份药」。
   *
   * ## 为什么必须有这个入口
   *
   * `create_medication_plan` 对 FAMILY 建的计划是 `active=False`，激活**只允许
   * 老人本人**。老人那一端的入口这一轮补上了（`elder.js` / `elder3.js`），
   * 但**全仓没有任何界面能建一份计划**——`POST /v4/medications` 只有测试在调。
   * 也就是说那条流程的两头，此前一头都没有。
   *
   * 而这一屏的小结里一直写着「可以在老人端或这里添加」：一句两边都不成立的话。
   *
   * ## 表单上那句提示不是装饰
   *
   * 家人按完「加上」，屏幕上如果只说「加好了」，她会以为药已经开始提醒了。
   * 实际上在老人点头之前**什么都不会发生**。所以按钮旁边和回执里各说一次。
   */
  function mountMedicationComposer() {
    const stage = $('[data-care-page="med"] .medicine-stage');
    if (!stage || $('.f3-med-add', stage)) return;

    const open = document.createElement('button');
    open.type = 'button';
    open.className = 'f3-med-add';
    open.textContent = '给老人加一份药';

    const form = document.createElement('form');
    form.className = 'f3-med-form';
    form.hidden = true;
    const field = (name, label, type, placeholder) => {
      const wrap = document.createElement('label');
      const span = document.createElement('span');
      span.textContent = label;
      const input = document.createElement('input');
      input.name = name;
      input.type = type;
      if (placeholder) input.placeholder = placeholder;
      input.required = true;
      wrap.append(span, input);
      return wrap;
    };
    const hint = document.createElement('p');
    hint.className = 'f3-med-hint';
    hint.textContent = '加上之后不会立刻提醒——要等老人自己在他那一端点「开始吃」。';
    const row = document.createElement('div');
    row.className = 'f3-med-row';
    const submit = document.createElement('button');
    submit.type = 'submit';
    submit.textContent = '加上';
    const cancel = document.createElement('button');
    cancel.type = 'button';
    cancel.className = 'f3-med-cancel';
    cancel.textContent = '先不加';
    row.append(submit, cancel);
    /* 「还剩多少」这一栏是**必填**的，不是可有可无的补充。
     *
     * 这一格下面就写着「余量最少的还有 N 份」。原先表单不问余量，
     * 后端 `stock_units` 的默认值又是 `0`（那同时也是「一片都没有了」
     * 这个合法值），于是新加一份药，屏幕上立刻出现
     * 「余量最少的还有 0 份」——一个谁也没提过余量的药，一进来就是缺药告警。
     *
     * 问一句就没有这个问题：屏幕上那个数字从此是家人自己填的。
     * （别的入口直接调 v4 接口建的计划仍然会带默认 0——那一半要等
     * 后端让「不知道」可表示，记在 KNOWN_ISSUES 第 144 条。）
     */
    const stockField = field('stock', '还剩多少（片/袋）', 'number', '例如：30');
    const stockInput = stockField.querySelector('input');
    stockInput.min = '0';
    stockInput.step = '1';

    form.append(
      field('name', '药名', 'text', '例如：钙片'),
      field('dose', '每次吃多少', 'text', '例如：一次一片'),
      field('time', '什么时候吃', 'time'),
      stockField,
      hint, row);

    stage.append(open, form);

    open.addEventListener('click', () => {
      form.hidden = !form.hidden;
      if (!form.hidden) $('input', form).focus();
    });
    cancel.addEventListener('click', () => { form.hidden = true; });

    form.addEventListener('submit', (e) => {
      e.preventDefault();
      const fd = new FormData(form);
      const name = String(fd.get('name') || '').trim();
      const dose = String(fd.get('dose') || '').trim();
      const time = String(fd.get('time') || '').trim();
      const stock = String(fd.get('stock') || '').trim();
      if (!name || !dose || !time) { say('药名、剂量和时间都要填。', 'warning'); return; }
      //: 余量单独校验：空字符串和 0 要分开——`Number('')` 是 0，
      //: 直接送出去就又把「没填」变成了「一片都没有」。
      if (stock === '' || !Number.isFinite(Number(stock)) || Number(stock) < 0) {
        say('还剩多少也要填，下面那一行报的就是它。', 'warning');
        return;
      }
      once(submit, async () => {
        const today = new Date();
        try {
          await api('/v4/medications', {
            method: 'POST',
            body: JSON.stringify({
              elder_id: ELDER_ID,
              display_name: name,
              normalized_name: name,
              dose_text: dose,
              times_local: [time],
              stock_units: Number(stock),
              start_date: `${today.getFullYear()}-${pad(today.getMonth() + 1)}-`
                          + `${pad(today.getDate())}`,
              source: 'family',
            }),
          }, FAMILY);
          form.reset();
          form.hidden = true;
          // 「加好了」三个字单独说是**误导**：在老人点头之前它不提醒任何人。
          say(`${name}加上了，等老人在他那一端点「开始吃」之后才会开始提醒。`, 'warning');
          loadCare();
        } catch (err) { trouble(err, '这份药'); }
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
