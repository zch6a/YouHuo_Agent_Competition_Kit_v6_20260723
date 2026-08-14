/** Task Space：一件事办到哪一步，用**页面**说，不用聊天记录说。
 *
 * ## 为什么不是聊天
 *
 * 优活是 Task Agent，不是聊天机器人。她说完「帮我交这个月水费」之后，屏幕上该出现的
 * 是**这件事本身**——多少钱、给谁、办到哪一步、现在要她做什么——而不是一串气泡让她
 * 自己从对话里把这些拼出来。
 *
 * 聊天记录没有删（不得 silent delete），它退到 Task Space 下面：想回头看说过什么的人
 * 仍然找得到，但它不再是主画面。
 *
 * ## 架构约束：**Conversation engine owns state. Task Space owns presentation.**
 *
 * 这个模块**不判断**任务走到哪一步，它只把后端已经算好的
 * `code` / `task_status` / `data` 翻译成一屏。刻意不写
 * `if (localTaskState === …)`——那会长成第二个前端状态机，而半年之后前后端两个
 * 状态机一定会漂移。所有分支只读后端给的字段。
 *
 * 导出的是纯函数（照 `glassbox.js` 的 `renderGlassBox` 那个形状），所以它可以在
 * 没有浏览器、没有会话、没有数据库的情况下被直接调用——Focus 几何那道确定性闸门
 * 就是靠这一点建起来的。
 */

/** 后端的 `code` / `task_status` → 四种视图之一。
 *
 * 四种视图对应计划书第十至十三节：普通任务 / 歧义 / 等家属 / 完成。
 * 认不出来的一律回 `null`，由调用处退回聊天视图——**不猜**。多一个没见过的状态码
 * 就渲染成一个像模像样但内容是编的页面，比不渲染糟得多。
 */
export function viewKindOf(data) {
  const code = data?.code;
  const status = data?.data?.task_status || data?.task_status;

  if (code === 'need_more_info' || data?.data?.teach_back === 'mismatch') return 'ambiguous';
  if (code === 'need_family_approval' || status === 'awaiting_family_approval') return 'waiting';
  if (code === 'task_completed' || status === 'completed') return 'done';
  if (code === 'need_elder_confirmation' || status === 'awaiting_elder_confirmation') return 'task';
  if (status === 'collecting' || status === 'executing') return 'task';
  return null;
}

//: 任务类型 → 给人看的名字。**已经收敛到 `common.js`**（上面那句「三份要在
//: Phase C 收敛到一处」就是这一步）。
//:
//: 收敛的时候发现它们不只是重复：这三份里写的 `appointment` / `medication`
//: 都不是后端的值，所以挂号任务从来没被认出来过，一直显示「这件事」。

/** 完成态那个对勾。内联 SVG，照 `elder.js` 的 `svgIcon()` 那个写法。
 *
 * `aria-hidden`：它旁边紧跟着「缴费办好了」那一句，读屏软件念一遍就够，
 * 不需要再念一个装饰图形。
 */
function checkMark() {
  const ns = 'http://www.w3.org/2000/svg';
  const svg = document.createElementNS(ns, 'svg');
  svg.setAttribute('class', 'task-done-mark');
  svg.setAttribute('viewBox', '0 0 24 24');
  svg.setAttribute('width', '40');
  svg.setAttribute('height', '40');
  svg.setAttribute('fill', 'none');
  svg.setAttribute('stroke', 'currentColor');
  // 1.8 是这个项目 22–26px 那一档的线宽，和 sprite 里五个 symbol 一致。
  svg.setAttribute('stroke-width', '1.8');
  svg.setAttribute('stroke-linecap', 'round');
  svg.setAttribute('stroke-linejoin', 'round');
  svg.setAttribute('aria-hidden', 'true');
  const path = document.createElementNS(ns, 'path');
  path.setAttribute('d', 'M20 6 9 17l-5-5');
  svg.append(path);
  return svg;
}

function el(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined && text !== null && text !== '') node.textContent = String(text);
  return node;
}

/** `2026-07` →「7 月」。
 *
 * 和后端 `services.py` 的 `_period_words` 是同一条规则，两边都要——后端管它念出来
 * 的那句话，这里管卡片上那一行。认不出格式就原样返回：宁可露出原值，
 * 也不要把一个没预料到的字符串猜成某个月份。
 */
function monthWords(period) {
  const parts = String(period || '').split('-');
  if (parts.length === 2 && /^\d+$/.test(parts[1])) return `${Number(parts[1])} 月`;
  return String(period || '');
}

/** 「68.40」→「¥68.40」。分转元由后端给，这里只负责怎么写。 */
function yuan(value) {
  if (value === undefined || value === null || value === '') return '';
  const number = typeof value === 'number' ? value : Number(String(value).replace(/[^\d.]/g, ''));
  return Number.isFinite(number) ? `¥${number.toFixed(2)}` : '';
}

/** 把后端响应折成这一屏要用的字段。
 *
 * 一处都不读 `task_id`：那串东西给数据库看，不给她看，而且读屏软件会念出来。
 * 这一条有闸门守着（`test_the_app_surface_never_renders_a_raw_identifier`）。
 */
export function taskViewModel(data) {
  const payload = data?.data || {};
  const slots = payload.slots || {};
  return {
    kind: viewKindOf(data),
    // 主体优先用**账单种类**（「水费」），因为那才是她说的那件事；
    // 拿不到就退到任务类型（「缴费」）；两个都没有才说「这件事」。
    //
    // 字段路径是**量出来的**，不是猜的：实测 `/v2/chat` 的 `data` 里原先只有
    // `amount_yuan` / `due_date` / `teach_back_required`，所以第一版按
    // `data.data.task_type` 取永远是空，屏幕上一直显示「这件事」。
    // 那三个字段本来就在 `task.slots` 里，只是没被带进响应——已在 `engine.py` 补上。
    subject: payload.bill_type || window.YouHuo.taskWord(payload.task_type),
    amount: yuan(payload.amount_yuan ?? slots.amount_yuan
      ?? (slots.amount_cents != null ? slots.amount_cents / 100 : null)),
    authority: payload.authority || slots.authority || '',
    period: monthWords(payload.period || slots.period),
    // 这一屏要她做什么。后端的 `message` 已经是给人看的话，直接用。
    ask: data?.message || '',
    heard: payload.heard || '',
    expected: payload.expected || '',
    // 等家属那一态：谁在等、什么时候通知的。
    approver: payload.approver_name || payload.family_name || '家人',
  };
}

/**
 * 渲染一屏 Task Space。
 *
 * @param {HTMLElement} host 容器（会被整段替换）
 * @param {object} view `taskViewModel()` 的结果
 * @returns {boolean} 有没有真的渲染出东西。`false` = 调用处应该退回聊天视图。
 */
export function renderTaskSpace(host, view) {
  if (!host) return false;
  if (!view || !view.kind) {
    host.replaceChildren();
    return false;
  }

  const card = el('article', `task-space task-space-${view.kind}`);

  if (view.kind === 'ambiguous') {
    // 第十一节：不堆历史气泡。只说没听清什么、请她再说一次。
    card.append(el('h2', 'task-headline', view.ask || '我没有听清'));
    if (view.heard && view.expected) {
      const diff = el('p', 'task-diff');
      diff.append(el('span', 'task-diff-heard', `您说的是 ${view.heard} 元`));
      diff.append(el('span', 'task-diff-sep', '·'));
      diff.append(el('span', 'task-diff-expected', `账单是 ${view.expected} 元`));
      card.append(diff);
    }
    card.append(el('p', 'task-note', '请再说一次。您也可以打字输入。'));
    host.replaceChildren(card);
    return true;
  }

  if (view.kind === 'waiting') {
    // 第十二节：这是一个 **App State**，不是一条聊天消息。
    card.append(el('p', 'task-label', '金额已经确认'));
    if (view.amount) card.append(el('p', 'task-amount', view.amount));
    card.append(el('h2', 'task-headline', `正在等${view.approver}确认`));
    card.append(el('p', 'task-note', '她刚刚收到通知。办好了我会告诉您。'));
    host.replaceChildren(card);
    return true;
  }

  if (view.kind === 'done') {
    // 第十三节：一个对勾、办成了什么、去哪里看凭证。
    //
    // 对勾必须是 SVG，不能是 `✓` 那个字符。第一版写的就是字符，
    // 而「不许 emoji 当图标」是这个项目的硬约束——闸门当场抓到了它，
    // 抓得对：字符对勾的字形、字重、基线都不受控，跟着回退字体走，
    // 而这一屏是「办好了」这个结论唯一的视觉标志。
    card.append(checkMark());
    card.append(el('h2', 'task-headline', `${view.subject}办好了`));
    if (view.amount) card.append(el('p', 'task-amount', view.amount));
    if (view.authority) card.append(el('p', 'task-where', view.authority));
    host.replaceChildren(card);
    return true;
  }

  // 第十节：普通任务。这是我查到的账单，请把金额念一遍。
  card.append(el('p', 'task-label', view.subject));
  if (view.amount) card.append(el('p', 'task-amount', view.amount));
  const where = [view.authority, view.period].filter(Boolean).join(' · ');
  if (where) card.append(el('p', 'task-where', where));
  if (view.ask) card.append(el('p', 'task-ask', view.ask));
  host.replaceChildren(card);
  return true;
}
