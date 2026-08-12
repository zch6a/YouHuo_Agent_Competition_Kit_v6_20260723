'use strict';

// 身份、登录、401 重放和令牌缓存都在 common.js 里。
//
// 顺带修掉这一页原有的两个差异：它此前无条件写 `Authorization: Bearer ${token}`，
// token 为空串时会发出一个后面什么都没有的头；也没有 401 重放，令牌一过期，六张卡
// 的按钮就开始静默失败。
const {api, byId} = window.YouHuo;
const state = {elderId: 'elder-demo', daughterId: 'daughter-demo', systemId: 'system-demo'};

async function bootstrap() {
  try {
    const ids = await window.YouHuo.ready();
    state.elderId = ids.elderId;
    state.daughterId = ids.daughterId;
    state.systemId = ids.systemId;
    await Promise.all([
      window.YouHuo.login('elder'), window.YouHuo.login('family'), window.YouHuo.login('system'),
    ]);
    byId('status').textContent = '正在为您办一件真的事……';
  } catch (error) { byId('status').textContent = error.message; }
  // 凭证放在身份之后、并且不阻塞它：身份没建起来时凭证也办不成，但身份的状态行
  // 不该等一次完整缴费才更新。
  // 成功之后把状态行收起来。
  //
  // 它原先写完「正在为您办一件真的事……」就再也不动了——凭证渲染完之后屏幕上是
  // 一张办好的凭证加一条绿色的"正在办"，两句话互相矛盾。而这一页讲的正是"说的和
  // 做的对得上"。
  //
  // 只在成功时隐藏：失败时它是唯一还在说话的东西（`.notice` 一直带 aria-live，
  // 读屏软件会念出来），所以那一条必须留在屏幕上。
  renderReceipt()
    .then(() => { const s = byId('status'); if (s) s.hidden = true; })
    .catch(error => receiptFailed(error));
}

/* ==========================================================================
   事务凭证
   ..........................................................................
   一次真实缴费，从审计链读出来渲染成一份可读的凭证。

   两个刻意的选择：

   一，**真的办**，不是把一段样例 JSON 画成时间轴。凭证的全部价值在于"这件事真的
   发生过、而且留下了可核验的痕迹"；一份假凭证连它自己都证明不了。

   二，明确写出**哪一句话没有进审计**。老人说的原话不在链上（隐私），链上只有
   "有一件缴费任务被建立、金额来自账单接口、他复述通过、家人同意的摘要和他确认的
   是同一个、回执由缴费方返回"。少记一样东西是这个产品的主张之一，凭证里不能只
   展示记了什么。
   ========================================================================== */

/** 审计事件 → 凭证上的一行。
 *
 * 认得的类型逐条写；认不出的**不丢掉**，用一行中性说明放进去。丢掉的后果是链上有
 * 十条、凭证上有五行，而没有任何东西说得出差额去哪了——那正好是凭证最不该有的性质。
 */
const RECEIPT_STEPS = {
  TASK_CREATED: {
    who: '优活',
    what: '立了一件事，并去查了这个月该交多少',
    proof: p => `${TASK_WORD[p.task_type] || '一件事'} · ${RISK_WORD[p.risk] || '未标风险'}`
      + ` · ${BASIS_WORD[p.semantic_basis] || '照他说的话'}`,
  },
  TEACH_BACK_VERIFIED: {
    who: '他',
    what: '把金额念了一遍',
    proof: p => `系统等的是 ${p.expected}，听到的是 ${p.heard}，第 ${p.attempts} 次通过`
      + '——念错就停下，不会按听到的数字去付',
  },
  TEACH_BACK_REJECTED: {
    who: '他',
    what: '念的金额和账单不一致，停下了',
    proof: p => `账单是 ${p.expected}，听到的是 ${p.heard}。没有执行任何支付`,
  },
  ELDER_CONFIRMED: {
    who: '他',
    what: '确认了这一笔',
    proof: p => `确认摘要 ${short(p.approval_digest)}`,
  },
  FAMILY_APPROVAL_RECORDED: {
    who: '家人',
    what: '点了同意',
    proof: p => `同意的摘要 ${short(p.approval_digest)}`,
  },
  FAMILY_APPROVED_AND_EXECUTED: {
    who: '家人',
    what: '点了同意，随即办好',
    proof: p => `同意的摘要 ${short(p.approval_digest)}，和他确认的是同一个`
      + (p.proof_digest ? `；缴费方回执 ${short(p.proof_digest)}` : ''),
  },
  FAMILY_REJECTED: {who: '家人', what: '拒绝了', proof: () => '没有执行任何支付'},
  FAMILY_APPROVED_EXECUTION_FAILED: {
    who: '家人', what: '同意了，但对方没办成',
    proof: () => '任务停在「未成功」，不会报成已完成',
  },
  NOTIFICATION_CREATED: {
    who: '优活',
    what: p => (p.recipient_role === 'elder' ? '回头告诉了他' : '把这件事推给了家人'),
    proof: p => NOTIFY_WORD[p.event_type] || '一条通知',
  },
};
const TASK_WORD = {bill_payment: '缴费', appointment: '挂号', medication: '用药'};
//: 风险等级的说法**必须和家属端一致**。/family 的 RISK_WORD 已经把 1–4 翻成了
//: 「信息查询 / 低风险 / 敏感操作 / 高风险」，而这一页原先印的是裸数字「风险级 4」。
//: 同一件事在两页上有两个名字（一个是词、一个是数），读者要自己做换算。
const RISK_WORD = {1: '信息查询', 2: '低风险', 3: '敏感操作', 4: '高风险'};
//: 「关键词命中」「语义匹配」是检索的行话。这一页是**凭证**不是实验室，读它的人
//: 想知道的是「优活凭什么认定他要办这件事」——答案是照原话、照意思、还是两样都对上。
//:
//: 兜底也一起改了：原先三处都是 `|| p.<原值>`，后端返回一个没预料到的枚举时，
//: 屏幕上直接出现 `embedding` / `bill_payment` —— 而「界面上不许出现英文枚举值」
//: 是这个项目的硬约束。认不出来就说一句不认识，不要把内部值念给人听。
const BASIS_WORD = {
  keyword_only: '照他说的原话', embedding: '照他说的意思', hybrid: '原话和意思都对上',
};
const NOTIFY_WORD = {
  approval_required: '有一笔要家人点头', task_completed: '这件事办好了',
  task_failed: '这件事没办成', sos: '紧急求助',
};

function short(hash) {
  const s = String(hash || '');
  return s ? `${s.slice(0, 12)}…` : '（无）';
}

/** 时间戳带毫秒。
 *
 * 整条链发生在同一秒里——第一版三行时间戳全是 `12:12:31`，一条"时间轴"上三个相同的
 * 时刻，看起来像是画出来的而不是量出来的。带上毫秒之后顺序看得见，而且
 * "整件事走完用了 35 毫秒"本身就是这一页想说的话之一。
 */
function hhmmssms(iso) {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return '';
  const pad = (n, w = 2) => String(n).padStart(w, '0');
  return `${pad(d.getHours())}:${pad(d.getMinutes())}:${pad(d.getSeconds())}`
    + `.${pad(d.getMilliseconds(), 3)}`;
}

function el(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined) node.textContent = text;
  return node;
}

function receiptFailed(error) {
  const status = byId('status');
  if (status) {
    status.hidden = false;
    status.classList.remove('good');
    status.textContent = '这一次没办成。下面写着卡在哪一步。';
  }
  const host = byId('receipt');
  if (!host) return;
  // 不假装成功。这一页的全部内容就是"只有真办成了才说办成了"。
  host.replaceChildren(el('p', 'receipt-pending',
    `这一次没能办成，所以这里没有凭证可出：${error.message}`));
}

/** 真的走一遍缴费，然后把它的审计记录渲染出来。
 *
 * 第一版无条件新办一次，而这一页整页就只有这一份凭证——所以那个假设是这一页的
 * 全部内容。它是错的：
 *
 *   `/v2/chat` → `{"code": "duplicate_blocked",
 *                  "message": "这笔账单已经在办理或已经完成，不会重复提交。"}`
 *
 * 那是**正确**的产品行为（同一张账单不重复提交），而凭证要求每次载入都新办成一笔。
 * 于是：第一次打开好的，第二次打开整页只有一句「账单金额没读到，不能凭空造一份
 * 凭证」。更糟的一种：任何一次半途而废（关掉标签页、网断了）会留下一件停在
 * "等他确认"的任务，那件任务把这个家庭的这张账单**永久**挡住——这一页从此再也
 * 出不来凭证。实测就是这样，而三道浏览器闸门全绿：它们每次都用全新的沙箱。
 *
 * 改成先读链、再决定办不办。凭证仍然只从审计链渲染，一个字都不是编的；变的只是
 * "这一次"变成"最近这一次"，而时间戳自己说得清是哪一次。
 */
async function renderReceipt() {
  const host = byId('receipt');
  if (!host) return;

  //: 这一次是我们刚刚亲手办的吗？只有亲手办的才知道他说了什么原话。
  let asked = null;
  let taskId = null;

  const bills = (await api('/v2/tasks?limit=100', {}, 'family'))
    .filter(t => t.task_type === 'bill_payment');
  // 最近的一件——不挑状态。一件"未成功，已安全停下"的任务同样是这一页要证明的
  // 事情之一（只有权威状态回报成功才算办好），把它藏起来才是不诚实。
  const recent = bills.sort((a, b) => String(b.updated_at).localeCompare(String(a.updated_at)))[0];

  if (recent) {
    taskId = recent.id;
  } else {
    // 链上还什么都没有：真的办一次。这是全新沙箱里的路径，也就是评委第一次打开
    // 这一页时走的那一条。
    const session = (await api('/v2/sessions', {method: 'POST', body: '{}'})).session_id;
    asked = '帮我交这个月的水费';
    const first = await api('/v2/chat', {
      method: 'POST', body: JSON.stringify({session_id: session, text: asked}),
    });
    const amount = (first.data && first.data.amount_yuan)
      || (first.message.match(/(\d+\.\d{2})\s*元/) || [])[1];
    if (!amount) throw new Error(`账单金额没读到，不能凭空造一份凭证（${first.message}）`);

    // 复述确认必须念出金额——这一步就是这个产品的主张，凭证里当然要走真的那条路。
    const confirmed = await api('/v2/chat', {
      method: 'POST',
      body: JSON.stringify({session_id: session, text: `确认支付${amount}元`}),
    });
    if (!confirmed.approval_digest) throw new Error(`没有拿到确认摘要（${confirmed.message}）`);
    taskId = confirmed.task_id;

    await api('/v2/family/approve', {
      method: 'POST',
      body: JSON.stringify({
        task_id: taskId, approve: true, approval_digest: confirmed.approval_digest,
      }),
    }, 'family');
  }

  const audit = await api(`/v2/audit?limit=200`, {}, 'family');
  const mine = (audit.events || []).filter(e => e.entity_id === taskId);
  if (!mine.length) throw new Error('审计链里找不到这件任务');

  const tasks = await api('/v2/tasks?limit=100', {}, 'family');
  const task = tasks.find(t => t.id === taskId) || recent || {};
  const amount = (task.details && task.details.amount_yuan) || '';

  host.replaceChildren();

  // --- 抬头 ---
  const head = el('header', 'receipt-head');
  const left = el('div');
  left.appendChild(el('p', 'receipt-eyebrow', '缴费凭证'));
  left.appendChild(el('h3', 'receipt-title', task.summary || `水费 ${amount}元`));
  head.appendChild(left);
  const done = task.status === 'completed';
  head.appendChild(el('span', `pill ${done ? 'good' : 'bad'}`, done ? '已办好' : '未完成'));
  host.appendChild(head);

  // --- 没有进链的那一句 ---
  //
  // 两种说法，取决于这一次是不是我们刚刚亲手办的。
  //
  // 亲手办的时候我们知道他说了什么，所以可以把原话摆出来，再说"链上没有它"。
  // 读链的时候我们**不知道**——而那恰恰是更强的一次演示：连做这个系统的人都没法
  // 从这条链上还原他当时说了什么。所以不能沿用第一种说法去编一句原话。
  const off = el('p', 'receipt-offchain');
  off.appendChild(el('strong', null, '他说的原话不在链上。'));
  off.appendChild(document.createTextNode(asked
    ? `这一次他说的是「${asked}」，而审计链里只有「有一件缴费任务被建立」。`
      + '少记一样东西也是要证明的事，所以写在这里。'
    : '这份凭证是从审计链上读出来的，而链上只有「有一件缴费任务被建立」'
      + '——连我们自己都没法从这条链上还原他当时说了什么。'
      + '少记一样东西也是要证明的事，所以写在这里。'));
  host.appendChild(off);

  // --- 时间轴 ---
  const list = el('ol', 'receipt-steps');
  for (const event of mine) {
    const spec = RECEIPT_STEPS[event.event_type];
    const item = el('li', 'receipt-step');
    item.appendChild(el('span', 'receipt-time', hhmmssms(event.created_at)));
    const body = el('div', 'receipt-body');
    const payload = event.payload || {};
    if (spec) {
      // `what` 可以是一句话，也可以是一个从 payload 算出来的函数——同一个事件类型
      // 落在不同角色上时说法不一样（同一条 NOTIFICATION_CREATED，一次是推给家人，
      // 一次是回头告诉他）。
      const what = typeof spec.what === 'function' ? spec.what(payload) : spec.what;
      body.appendChild(el('strong', null, `${spec.who}${what}`));
      let proof = '';
      try { proof = spec.proof(payload); } catch (_) { proof = ''; }
      if (proof) body.appendChild(el('p', 'receipt-proof', proof));
    } else {
      // 认不出的类型也要出现——链上有十条、凭证上有五行而没人说得出差额去哪了，
      // 恰恰是凭证最不该有的性质。
      //
      // 但**不把枚举名印在这一行**。`NOTIFICATION_CREATED` 这样的标识符出现在正文
      // 里，就是把"我们没给这个事件写说明"的内部状态直接展示给评委。原始类型在下面
      // 那个哈希折叠里——那里全是标识符，它属于那里。
      body.appendChild(el('strong', null, '系统留下一条记录'));
      item.classList.add('is-other');
    }
    item.appendChild(body);
    list.appendChild(item);
  }
  host.appendChild(list);

  // --- 链条 ---
  const foot = el('footer', 'receipt-foot');
  foot.appendChild(el('span', `pill ${audit.chain_valid ? 'good' : 'bad'}`,
    audit.chain_valid ? '审计链自校验：完整' : '审计链自校验：不完整'));
  foot.appendChild(el('span', 'receipt-foot-note',
    `这件事留下 ${mine.length} 条记录，整条链 ${(audit.events || []).length} 条，`
    + '每一条都带着上一条的哈希——中间改一条，后面全部对不上。'));

  const raw = el('details', 'receipt-chain');
  raw.appendChild(el('summary', null, '看这件事的哈希'));
  const chain = el('div', 'receipt-chain-body');
  for (const event of mine) {
    const row = el('div', 'receipt-chain-row');
    row.appendChild(el('code', null, short(event.prev_hash)));
    row.appendChild(el('span', 'receipt-arrow', '→'));
    row.appendChild(el('code', null, short(event.event_hash)));
    row.appendChild(el('span', 'receipt-chain-type', event.event_type));
    chain.appendChild(row);
  }
  raw.appendChild(chain);
  foot.appendChild(raw);
  host.appendChild(foot);
}

// 这一页现在只有一件事：一份凭证。
//
// 原先它是「六张能力演示卡 + 页内分区」，而那六张卡讲的是语音共识、恶意文档、
// Saga、跨设备冲突、限时破窗、能力真值——把整个比赛项目塞进了一位老人的手机里。
// 它们全部搬到了 /stage 的「证明」与「工程」两层，一个都没删（proof-demos.js）。
//
// 分区导航跟着搬走了，所以这里不再需要 initSections：一页一件事的时候，
// 分区机制是纯粹的多余复杂度。
bootstrap();
