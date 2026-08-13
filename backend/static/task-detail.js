/** 事务详情：一笔事办完之后，她想回头看的那一屏。
 *
 * ## 它为什么是「压在四个 tab 之上的一层」，而不是跳去 `/trust`
 *
 * `/trust` 按 `surfaces.py` 属于 `consumer / family`——**家属壳的一个 deep link**。
 * 让老人点一行记录跳过去是表面越界：她会拿到家属的导航、家属的语域，
 * 以及一页她不需要的原始记录。
 *
 * 三个参考产品独立给出同一个形状（`frontend_redesign/ia/12_reference_study.md`）：
 * Medito 的详情页 push 到**同一个栈**上、压在 tab 之上，而且实测它的 Pack 详情页
 * 出口在**底部**操作栏；MediMate 的 `Nutrition` 是 `tabBarButton: () => null` 的
 * **隐藏目的地**，注释写着 `navigable via voice`；Folk Care 的现场护理员四个 tab
 * 固定不动、~10 个任务屏压在**栈**里。
 *
 * ## 它读任务，不读审计链
 *
 * 这是 Folk Care 那条「取证与叙事是两个模型」的落地：`/judge` 读审计链，
 * 消费者面读**任务本身**（`/v2/tasks` 的 `TaskView`）。`trust.js` 现在的做法是
 * 拉 200 条审计再客户端过滤，那个窗口会把较早事务的链截断——这一层不重复那个错误。
 *
 * ## 三条硬约束
 *
 * ① **绝不显示 `approval_digest`**：它是哈希。手机框里只放「哪件事、到哪一步」。
 * ② **绝不显示界面枚举值**：`status` 是 `completed` 这种，必须过 `STATUS_WORD`；
 *    翻不出来就说「还在办」，不把英文枚举漏到屏幕上。
 * ③ **出口在底部**。75 岁单手持机的人碰不到左上角，而优活是 `display: standalone`
 *    的 PWA，iOS 下没有系统返回手势——这一层没有底部出口就是死路。
 *
 * 导出的是纯函数（照 `task-space.js` 那个形状），所以它可以在没有浏览器、没有会话、
 * 没有数据库的情况下被直接调用。
 */

//: 任务状态 → 给人看的话。认不出来就说「还在办」，不漏枚举值。
//:
//: 这张表和 `elder.js` 的 `TASK_TYPE_WORD`、`task-space.js` 的 `TASK_WORD`
//: 是同一类东西的第四份。它们要在 Phase C 收敛到一处；现在先各自带着，
//: 但**都不许**兜底成原始枚举。
const STATUS_WORD = {
  completed: '办好了',
  executing: '正在办',
  collecting: '还在问清楚',
  awaiting_elder_confirmation: '等您确认',
  awaiting_family_approval: '等家人点头',
  cancelled: '已经取消',
  failed: '没办成，已经停下',
};

//: 状态 → 语气。和 `common.js` 的 `toneOf` 一个意思，但那个读的是响应的
//: `ui.theme`，这里读的是任务状态，所以不能复用。
const STATUS_TONE = {
  completed: 'good',
  cancelled: 'warning',
  failed: 'bad',
};

const TASK_WORD = {
  bill_payment: '缴费',
  hospital_registration: '挂号',
  reminder: '提醒',
  medication: '用药',
};

function el(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined && text !== null && text !== '') node.textContent = String(text);
  return node;
}

/** `2026-08-13T11:26:04+08:00` →「8 月 13 日 11:26」。
 *
 * 不用 `toLocaleString`：它在不同浏览器/地区设置下给出的形状不一样，而这一行
 * 是给一位老人读的，不该随环境变。认不出格式就返回空串——**宁可不显示这一行，
 * 也不要显示一个 ISO 字符串**。
 */
export function whenWords(iso) {
  const at = new Date(iso);
  if (!iso || Number.isNaN(at.getTime())) return '';
  return `${at.getMonth() + 1} 月 ${at.getDate()} 日 ${
    String(at.getHours()).padStart(2, '0')}:${String(at.getMinutes()).padStart(2, '0')}`;
}

/** `2026-07` →「7 月」。
 *
 * 和 `task-space.js` 的 `monthWords`、后端 `services.py` 的 `_period_words`
 * 是同一条规则的第三份。三份要在 Phase C 收敛；现在先各自带着，
 * 但都不许把 `2026-07` 原样上屏。
 */
export function monthWords(period) {
  const parts = String(period || '').split('-');
  if (parts.length === 2 && /^\d+$/.test(parts[1])) return `${Number(parts[1])} 月`;
  return String(period || '');
}

/** 「68.40」→「¥68.40」。 */
function yuan(value) {
  if (value === undefined || value === null || value === '') return '';
  const n = typeof value === 'number' ? value : Number(String(value).replace(/[^\d.]/g, ''));
  return Number.isFinite(n) ? `¥${n.toFixed(2)}` : '';
}

/** 这一屏说的是哪件事，一句话。
 *
 * 金额**不进**这一句：它在下面单独一行大字。两处都写就成了
 * 「2026-07水费 68.40元 / ¥68.40」——同一个数字连着出现两次。
 */
function subjectWords(task, details) {
  const type = String(task.task_type || '');
  if (type === 'bill_payment') {
    const month = monthWords(details.period);
    const kind = details.bill_type || '生活账单';
    return `${month}${month ? '的' : ''}${kind}`;
  }
  if (type === 'hospital_registration') {
    return [details.hospital, details.department].filter(Boolean).join(' · ')
      || '挂号';
  }
  if (type === 'reminder') return details.title || '提醒';
  // 认不出来的类型：用类型词，再不行说「这件事」。**不回退到 `summary`**——
  // 那里面可能带着 `2026-07` 这种原始值，而这一层的定义之一就是不给她看那些。
  return TASK_WORD[type] || '这件事';
}

/** `TaskView` → 这一屏要用的字段。
 *
 * 一处都不读 `approval_digest`。那不是「忘了读」，是这一层的定义之一。
 */
export function taskDetailViewModel(task) {
  if (!task) return null;
  const details = task.details || {};
  const result = task.result || {};
  const status = String(task.status || '');

  const subject = subjectWords(task, details);
  const rows = [];
  const push = (label, value) => { if (value) rows.push({label, value}); };

  push('什么时候', whenWords(task.created_at));
  if (task.updated_at && task.updated_at !== task.created_at) {
    push('最后一次变化', whenWords(task.updated_at));
  }
  // 缴费
  push('给了谁', details.authority || result.authority);
  // 「哪个月」只在标题里没有它的时候才单独列一行。标题是「7 月的水费」，
  // 再来一行「哪个月 7 月」是同一个信息说两遍——实测截图里就是这样。
  const month = monthWords(details.period);
  if (month && !subject.includes(month)) push('哪个月', month);
  push('最晚什么时候交', details.due_date);
  // 挂号
  push('哪家医院', details.hospital);
  push('哪个科', details.department);
  push('哪位大夫', details.doctor);
  push('哪一天', details.appointment_date);
  push('几点', details.appointment_time);
  // 提醒
  push('要做什么', details.title);
  // 机构那边怎么回的
  push('对方怎么说', result.message || result.note);
  push('对方的单号', result.receipt_no || result.order_no);

  return {
    // 主体：自己拼，**不用** `task.summary`。
    //
    // 实测 `summary` 是「2026-07水费 68.40元」——后端 `privacy.py:179` 直接拼了
    // 原始 `period`，于是屏幕上给一位老人看的是 `2026-07`；而金额也在里面，
    // 和下面那行大字重复了一遍。
    //
    // 不改后端那一行，因为 `summary` 还有别的读者（家属端、`/stage`），
    // 动它要连那些一起看；这一层自己拼，把「哪个月」翻成人话、金额只出现一次。
    subject,
    amount: yuan(details.amount_yuan),
    statusWord: STATUS_WORD[status] || '还在办',
    statusTone: STATUS_TONE[status] || 'neutral',
    rows,
  };
}

/**
 * 渲染一屏事务详情。
 *
 * @param {HTMLElement} host 容器（会被整段替换）
 * @param {object|null} view `taskDetailViewModel()` 的结果
 * @returns {boolean} 有没有真的渲染出东西
 */
export function renderTaskDetail(host, view) {
  if (!host) return false;
  if (!view) {
    // 没有数据就说没有，不编一屏看起来像真的详情。
    host.replaceChildren(el('p', 'notice warning', '没有找到这件事的记录。'));
    return false;
  }

  const frag = document.createDocumentFragment();

  // 主体抬头：这一屏说的是哪件事、多少钱、到哪一步。
  // 形状来自 MedCore 的 patient detail header（身份 + 标识符 + 风险在同一行），
  // 但**去掉标识符那一格**——那是给专业面的。
  const head = el('header', 'detail-head');
  head.append(el('h3', 'detail-subject', view.subject));
  if (view.amount) head.append(el('p', 'detail-amount', view.amount));
  // 状态不只靠颜色：文字和颜色同时给。两个成熟项目（MedCore、Medito）
  // 独立得出同一条结论，实测过。
  head.append(el('p', `detail-status ${view.statusTone}`, view.statusWord));
  frag.append(head);

  if (view.rows.length) {
    const list = el('dl', 'detail-rows');
    view.rows.forEach(row => {
      list.append(el('dt', null, row.label));
      list.append(el('dd', null, row.value));
    });
    frag.append(list);
  }

  host.replaceChildren(frag);
  return true;
}
