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
  } catch (error) {
    failed(host, error);
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

async function loadMedications() {
  const host = byId('medBody');
  try {
    const plans = await medications();
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
      // 库存换算成"还能吃几天"。`stock_units` 和 `units_per_dose` 是两个数字，
      // 而一位子女要的是"还剩四天"这一个结论。
      const perDay = plan.units_per_dose * plan.times_local.length;
      const days = perDay > 0 ? Math.floor(plan.stock_units / perDay) : null;
      if (days !== null) {
        card.appendChild(el('p', days <= 3 ? 'notice warning' : 'meta',
          days <= 0 ? '药已经吃完了。' : `按现在的吃法还够 ${days} 天。`));
      }
      host.appendChild(card);
    });
  } catch (error) { failed(host, error); }
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

async function loadHealth() {
  const host = byId('bodyBody');
  try {
    const events = await api(`/v4/health/events/${state.elderId}`, {}, 'family');
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
    host.appendChild(el('p', 'meta', '这里只做整理，不做诊断。看病请以医生的判断为准。'));
  } catch (error) { failed(host, error); }
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
  } catch (error) { failed(host, error); }
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

const CONTACT_WORD = {
  family: '家人', neighbour: '邻居', community: '社区', doctor: '医生', other: '其他',
};

async function loadSafety() {
  const host = byId('safetyBody');
  try {
    const [policy, contacts] = await Promise.all([
      api(`/v4/safety/policy/${state.elderId}`, {}, 'family'),
      api(`/v4/contacts/${state.elderId}`, {}, 'family').catch(() => []),
    ]);
    host.replaceChildren();

    const digest = el('div', 'digest');
    const hours = Math.round((policy.inactivity_minutes || 0) / 60);
    [
      ['多久没动静就找人', hours >= 1 ? `${hours} 小时` : `${policy.inactivity_minutes} 分钟`],
      ['出门多远开始留意', `${policy.geofence_radius_m} 米以外`],
      ['要不要告诉社区', policy.notify_community ? '要' : '不要'],
    ].forEach(([label, value]) => {
      const row = el('div', 'digest-row');
      row.append(el('strong', null, label), el('div', null, value));
      digest.appendChild(row);
    });
    host.appendChild(digest);

    if (contacts.length) {
      host.appendChild(el('h3', 'care-block-head', '出事先找谁'));
      const list = el('ul', 'care-lines');
      contacts.slice(0, 6).forEach((c) => {
        list.appendChild(el('li', null,
          `${c.name}（${CONTACT_WORD[c.contact_role] || c.contact_role}）${c.address_masked}`));
      });
      host.appendChild(list);
    } else {
      host.appendChild(el('p', 'care-empty', '还没有设紧急联系人。'));
    }

    host.appendChild(el('p', 'meta',
      '位置只在需要的时候看一眼，按最小必要留存。定位精度不够时不会自动报警——'
      + '一次误报会让他以后不敢再带手机出门。'));
  } catch (error) { failed(host, error); }
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
window.YouHuo.initSections('today');

bootstrap();
