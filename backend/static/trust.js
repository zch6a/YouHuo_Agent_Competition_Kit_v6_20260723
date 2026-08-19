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
  } catch (error) {
    // 这里原先是 `= error.message`——**连前缀都没有**，把异常消息整条当成文案。
    // 这一页是手机上的消费者凭证，`Failed to fetch` 出现在这儿等于把浏览器的
    // 内部说法当成产品文案。
    byId('status').textContent = window.YouHuo.errorWords(error, '这份凭证').text;
  }
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

/** 载荷里的一个值，**只有真的在那儿**才返回它。
 *
 * 这一页出过一次「第 undefined 次通过」：模板读 `p.attempts`，种子没写这个字段，
 * 读到 undefined 就原样拼进中文里。那一行的修法当时只修在 `attempts` 上，而同一份
 * 模板里 `expected` / `heard` / `approval_digest` / `proof_digest` 全都是同一种裸插值
 * ——一个字段一个字段地修，下一个漏掉的字段会以完全一样的方式再咬一次。
 *
 * 所以判据挪到值这一层：**先问「这一项在不在链上」，再决定要不要说这一句**。
 * 五种「其实什么都没有」的形状一起挡掉：undefined / null / 空串 / NaN，
 * 以及 `String({})` 得到的 `[object Object]`。
 */
function value(v) {
  if (v === undefined || v === null) return '';
  if (typeof v === 'number' && !Number.isFinite(v)) return '';
  const s = String(v).trim();
  return (s && s !== 'undefined' && s !== 'null' && s !== 'NaN'
    && !/^\[object \w+\]$/.test(s)) ? s : '';
}

/** 「系统等的是 X，听到的是 Y」——**两个值都在才说**。
 *
 * 只有一个值的时候这句话是残的（「系统等的是 68.40，听到的是 」），
 * 而一句残话出现在复述核对这一行上，正好推翻它要证明的那件事。
 */
function heardPair(expected, heard) {
  const a = value(expected);
  const b = value(heard);
  return (a && b) ? `系统等的是 ${a}，听到的是 ${b}` : '';
}

/** 审计事件 → 凭证上的一行。
 *
 * 认得的类型逐条写；认不出的**不丢掉**，用一行中性说明放进去。丢掉的后果是链上有
 * 十条、凭证上有五行，而没有任何东西说得出差额去哪了——那正好是凭证最不该有的性质。
 *
 * `proof(payload, chain)` 的第二个参数是**这一件事的整条链**（见 `chainFacts`）。
 * 加它的理由只有一个：「家人同意的和他确认的是同一个」这句话要成立，得真的把两个
 * 摘要拿来比一次。原先它是无条件写死的一句断言——两边都没有摘要时屏幕上是
 * 「同意的摘要 （无），和他确认的是同一个」，一句凭空的保证印在这一页最要紧的位置。
 */
const RECEIPT_STEPS = {
  TASK_CREATED: {
    who: '优活',
    // 「并去查了这个月该交多少」只对缴费成立。这一页已经不再按 `bill_payment`
    // 过滤（挂号和提醒同样出凭证），写死就会给一次挂号配上一句查账单。
    what: p => (p.task_type === 'bill_payment'
      ? '立了一件事，并去查了这个月该交多少'
      : '立了一件事'),
    proof: p => `${taskWord(p.task_type)} · ${RISK_WORD[p.risk] || '未标风险'}`
      // 兜底原先是 `|| '照他说的话'`——那不是兜底，那是**换一个说法照样下结论**：
      // 认不出 basis 时它会说「照他说的原话」，而 `engine.py:472`
      // （老人接受「顺便帮您办」时走的那条）压根不写 `semantic_basis`。
      + ` · ${BASIS_WORD[p.semantic_basis] || '没记下凭什么听懂的'}`,
  },
  TEACH_BACK_VERIFIED: {
    who: '他',
    what: '把金额念了一遍',
    // 念了几遍这一句，**只有在真的知道遍数时才说**。
    //
    // 原先是 `第 ${p.attempts} 次通过`，而演示种子的载荷里没有 `attempts`
    // （`database.py:373` 只写了 expected 与 heard；真实引擎 `engine.py:1302`
    // 是写的）。于是可信中心的凭证正文里印着「第 **undefined** 次通过」——
    // 一个裸露的 JS 值，出现在一整页都在讲「这里的每一条都可核验」的地方。
    //
    // 兜底不许编数字（写死「第 1 次」就是把不知道的事说成知道），也不许把
    // undefined 漏出去。不知道就不说这一句：少说一句是诚实的，说错一句不是。
    proof: p => {
      const times = Number(p.attempts);
      const howMany = Number.isFinite(times) && times > 0
        ? (times === 1 ? '，一次就念对了' : `，念到第 ${times} 遍才对上`)
        : '';
      const pair = heardPair(p.expected, p.heard);
      return (pair ? `${pair}${howMany}` : `复述对上了${howMany}`)
        + '——念错就停下，不会按听到的数字去付';
    },
  },
  TEACH_BACK_REJECTED: {
    who: '他',
    what: '念的金额和账单不一致，停下了',
    proof: p => {
      const a = value(p.expected);
      const b = value(p.heard);
      return (a && b ? `账单是 ${a}，听到的是 ${b}。` : '') + '没有执行任何支付';
    },
  },
  ELDER_CONFIRMED: {
    who: '他',
    what: '确认了这一笔',
    // 摘要在链上就摆出来（`engine.py:913` 写的就是它），不在就说这一条上有的那件事。
    // 原先无条件 `确认摘要 ${short(p.approval_digest)}`，而 `short()` 把缺失翻成
    // 「（无）」——屏幕上是「确认摘要 （无）」，一行只剩标签的证据。
    proof: p => {
      const digest = value(p.approval_digest);
      if (digest) return `确认摘要 ${short(digest)}——家人点头时要对上的就是它`;
      const amount = value(p.amount_yuan);
      return amount ? `他确认的是 ${amount} 元这一笔` : '';
    },
  },
  FAMILY_APPROVAL_RECORDED: {
    who: '家人',
    // **这一条从来不是「家人点了同意」。** 两种载荷都不是：
    //   · 真实引擎（`engine.py:1100`）在**票数还不够**时才写它，
    //     载荷是 `{approval_count, required_approvals}`；
    //   · 演示种子（`database.py:419`）写的是 `{required: true}`，位置在
    //     「推给家人」**之前**，意思是「记下：这一笔要家人点头」。
    // 写死成「点了同意」的后果在种子上一眼就看得见：时间轴依次是「家人点了同意」→
    // 「优活把这件事推给了家人」→「家人点了同意，随即办好」——同意、再被问、再同意。
    what: p => (Number.isFinite(Number(p.approval_count))
      ? '点了同意，还在等其他家人'
      : '还没点头，这一笔停在这里等他们'),
    // 同样地：这条事件的载荷里**没有** `approval_digest`，两种写法都没有。
    // 原先读它，于是永远渲染成「同意的摘要 （无）」——不是种子缺字段，是这一行
    // 读错了字段。
    proof: p => {
      const got = Number(p.approval_count);
      const need = Number(p.required_approvals);
      if (Number.isFinite(got) && Number.isFinite(need) && need > got) {
        return `已经有 ${got} 位点头，要 ${need} 位才动手`;
      }
      return p.required === true ? '在他们点头之前，什么都不会做' : '';
    },
  },
  FAMILY_APPROVED_AND_EXECUTED: {
    who: '家人',
    what: '点了同意，随即办好',
    // 「和他确认的是同一个」是这一页的第二条底线（「您确认的和家人同意的必须是同一笔，
    // 对不上就停下」）。所以它要么**被真的比过一次**，要么就不说。
    proof: (p, chain) => {
      const bits = [];
      const ours = value(p.approval_digest);
      const his = chain.elderDigest;
      if (ours && his) {
        bits.push(ours === his
          ? `同意的摘要 ${short(ours)}，和他确认的是同一个`
          : `同意的摘要 ${short(ours)}，和他确认的 ${short(his)} 对不上`);
      } else if (ours) {
        bits.push(`同意的摘要 ${short(ours)}`);
      }
      const receipt = value(p.proof_digest);
      const from = value(p.authority);
      // 回执有摘要才叫回执。原先是 `p.proof_digest ? … : ''`——没有就整句消失，
      // 而这一页写着「对方没回执就是没办成」，那一句于是无声地失去了它的证据。
      if (receipt) bits.push(`${from || '对方'}给的回执 ${short(receipt)}`);
      else {
        const rest = [from && `对方是${from}`,
                      value(p.amount_yuan) && `金额 ${value(p.amount_yuan)} 元`]
          .filter(Boolean).join('、');
        if (rest) bits.push(rest);
      }
      return bits.join('；');
    },
  },
  FAMILY_REJECTED: {who: '家人', what: '拒绝了', proof: () => '没有执行任何支付'},
  FAMILY_APPROVED_EXECUTION_FAILED: {
    who: '家人', what: '同意了，但对方没办成',
    proof: () => '任务停在「未成功」，不会报成已完成',
  },
  // 这一笔**没有**经家人接力时走的那条路（`engine.py:995`，低风险直接办）。
  // 少了它，一件不需要家人点头的事在凭证上就只剩「系统留下一条记录」——
  // 也就是这一页最想说的那句话（只有拿到回执才算办好）在那条路径上没有证据。
  TASK_EXECUTED: {
    who: '优活',
    what: '把这件事办了，并核对了对方的状态',
    proof: p => {
      const receipt = value(p.proof_digest);
      const ok = p.verification_accepted === true;
      return [receipt && `回执 ${short(receipt)}`,
              ok ? '对方系统的状态核对通过' : ''].filter(Boolean).join('；')
        || '对方回报的状态已经核对过';
    },
  },
  TASK_FAILED: {
    who: '优活',
    what: '没能办成，已经安全停下',
    proof: () => '任务停在「未成功」，不会报成已完成',
  },
  TASK_CANCELLED: {who: '他', what: '取消了这件事', proof: () => '没有继续执行'},
  // 这一条**真的会出现在凭证上**：`/judge` 每读一次「决策上下文」就往这一笔的链上
  // 写一条（`v5_api.py:327`），而 `/judge` 正是评委看完之后点「可信中心」的来处。
  // 实测：从 /judge 看过那一笔再打开 /trust，凭证末尾是两行
  // 「系统留下一条记录」——两条没有任何说明的记录，出现在一张讲"每一条都可核验"
  // 的凭证上。兜底分支本身没错，但一个**已知会发生**的类型不该落到兜底里。
  TASK_EXPLANATION_VIEWED: {
    who: '优活',
    what: '记下了：有人调阅过这件事的说明',
    proof: () => '查过的人也要留痕，这条规矩对我们自己也一样',
  },
  NOTIFICATION_CREATED: {
    who: '优活',
    // 三分支，不是二分支：原先 `=== 'elder' ? … : '把这件事推给了家人'`，
    // 于是任何一个不是 elder 的收件人（社区、系统）都被说成「推给了家人」。
    what: p => {
      const to = String(p.recipient_role || '');
      if (to === 'elder') return '回头告诉了他';
      if (to === 'family') return '把这件事推给了家人';
      return '发出了一条通知';
    },
    proof: p => NOTIFY_WORD[p.event_type] || '一条通知',
  },
};
//: 任务类型的说法从 `common.js` 拿，不在这里再写一份。
//:
//: 这里原先是 `{bill_payment: '缴费', appointment: '挂号', medication: '用药'}`
//: ——`appointment` 和 `medication` **不是后端的值**（`TaskType` 是
//: hospital_registration / bill_payment / reminder / form_assistance），
//: 所以那两个键永远命中不了，而真实的挂号任务在这张凭证上退成「一件事」。
//: 同样的表在 elder.js / task-space.js / task-detail.js 各有一份，都带着同一个错。
const taskWord = window.YouHuo.taskWord;
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
//: 通知类型的说法。键是 `NotificationService.send(event_type=…)` 真的会传的那些
//: 值（`services.py` / `v3_services.py` 里逐个 grep 得到九个），不是猜的。
//:
//: 原先只有四个，其中 `task_failed` / `sos` **没有任何一处产生它们**，而真的会走到
//: 屏幕上的 `additional_approval_required`（风险 4 的缴费要两位家属点头，这是演示里
//: 走得到的一条路）不在表里——实测那一行渲染成一句没有信息量的「一条通知」。
//: 兜底是诚实的，但一张凭证上出现两条一模一样的「一条通知」，读的人会以为链坏了。
//: 两个不存在的键留着无害，删掉它们才要先确认后端真的不会再产生——所以只加不删，
//: 并在这里写明哪两个当前没有产生者。
const NOTIFY_WORD = {
  approval_required: '有一笔要家人点头',
  additional_approval_required: '还差一位家人点头',
  task_completed: '这件事办好了',
  task_rejected: '家人没同意，这件事停了',
  family_reminder_created: '家人建了一条提醒',
  reminder_advance_notice: '提前提醒了一声',
  reminder_due: '到点了，提醒了他',
  reminder_escalated: '一直没回应，找了家人',
  emergency_call: '紧急联系',
  // 下面两个当前后端不产生（全仓 grep 无 `event_type="task_failed"` / `"sos"`），
  // 留着是因为它们是这一页想说的两件事，将来接上就直接有说法。
  task_failed: '这件事没办成', sos: '紧急求助',
};

function short(hash) {
  const s = String(hash || '');
  return s ? `${s.slice(0, 12)}…` : '（无）';
}

/** 站在整条链上才看得见的那几件事。
 *
 * 现在只有一件：**老人确认时的那个摘要**。家人同意那一行要用它来回答这一页的
 * 第二条底线——「您确认的和家人同意的必须是同一笔」。那句话此前是写死的断言，
 * 不比、也不看两边有没有值；改成真的比一次，就必须让那一行看得见另一条记录。
 *
 * 取**最后一条** `ELDER_CONFIRMED`：一笔任务被改过参数之后老人会再确认一次，
 * 而家人点头对上的是最新那一个（`engine.py:894` 改参数时先把 digest 清成 null
 * 再重算）。取第一条会在"改了金额再确认"这条路径上报出一个假的不一致。
 */
function chainFacts(events) {
  let elderDigest = '';
  for (const event of events) {
    if (event.event_type !== 'ELDER_CONFIRMED') continue;
    const found = value((event.payload || {}).approval_digest);
    if (found) elderDigest = found;
  }
  return {elderDigest};
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

/** 出错时给人看的那一句。
 *
 * 这一行原先是 `${error.message}` 直接上屏。`/trust` 是**消费者面**，而
 * `error.message` 在断网时是 `Failed to fetch`——浏览器的内部说法，印在一位老人
 * 家属的手机上。同一类泄漏在这个项目里被 `test_consumer_errors_are_typed_not_raw`
 * 抓过八处，唯独漏了这一处：那条闸门按 **`catch (x) {` 绑定的变量名**找
 * `x.message`，而这里走的是 `.catch(error => receiptFailed(error))` 加一个具名
 * 函数的形参——形状不同，闸门看不见。
 *
 * 我们自己抛的消息（「审计链里找不到这件任务」）是中文，那种要原样留住：它比
 * 四型兜底具体得多。判据就是「这句话里有没有中文」。
 */
function receiptWords(error) {
  const raw = String((error && error.message) || '').trim();
  if (/[一-鿿]/.test(raw)) return raw;
  return window.YouHuo.errorWords(error, '这份凭证').text;
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
    `这一次没能办成，所以这里没有凭证可出：${receiptWords(error)}`));
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

  // `asked`（「这一次是我们刚刚亲手办的吗」）连同它下面那条写路径一起删了：
  // 这一页只读，永远不是「刚刚亲手办的」。
  let taskId = null;

  const tasks = await api('/v2/tasks?limit=100', {}, 'family');

  // 想看**哪一件**：URL 说了算，没说就取最近的一件。
  //
  // 这一页原先没有任何按 id 进来的入口（无 URL 参数、无 body 属性），所以从家人端
  // 的一条任务点不进它对应的那张凭证——「看这一次的经过」只能看最近那一次。
  // 用 hash 而不是 query：`?task=` 会让 service worker 的 `start_url` 与缓存键
  // 多出一个维度，而 hash 不参与请求。
  const wanted = (location.hash.match(/(?:^|[#&])task=([\w:-]+)/) || [])[1];

  // **不再按 `task_type === 'bill_payment'` 硬过滤。**
  //
  // 那条过滤让挂号和用药永远出不了凭证——而这一页要证明的「每一步都留下记录」
  // 对它们同样成立，甚至更需要：一次挂号的经过比一次缴费更难自己回想。
  // 过滤改成「链上真的有这件事」，那才是能不能出凭证的真实条件。
  const byRecent = [...tasks].sort(
    (a, b) => String(b.updated_at).localeCompare(String(a.updated_at)));
  // 最近的一件——不挑状态。一件"未成功，已安全停下"的任务同样是这一页要证明的
  // 事情之一（只有权威状态回报成功才算办好），把它藏起来才是不诚实。
  const recent = (wanted && tasks.find(t => t.id === wanted)) || byRecent[0];

  if (!recent) {
    // 没有就说没有。
    //
    // 这里原先是一整段「那我现在帮你办一笔出来」：建会话、说「帮我交这个月的水费」、
    // 复述确认金额、再调 `/v2/family/approve`——**打开一张只读的凭证会凭空发起一笔
    // 缴费**。那段代码自己的注释写着触发条件是「评委第一次打开这一页时走的那一条」。
    //
    // 它平时到不了，因为 `visitor_sandbox()` 会给每位访客种一笔已完成缴费；但那段
    // 种子挂在 `seed_history` 开关上，关掉（真实部署的默认值）就又能到。
    // 「平时到不了」不是「不会发生」。
    //
    // Read UI 必须是 Read。`test_receipt_is_read_only.py` 现在钉住这一点：
    // 这个文件里不许出现任何写方法。
    // 两个 class 都是这个项目已有的：`.receipt-pending`（pages.css:962）和
    // `.section-note`（pages.css:236）。**不新造 class 名**——一个没有样式的
    // class 不报错也不显形，只是让这段字继承默认样式，看起来像"忘了写样式"。
    host.replaceChildren(
      el('p', 'receipt-pending', '还没有可以出示的凭证。'),
      el('p', 'section-note',
        '优活替他办完一件事之后，这里会出现那一次的完整经过：他说了什么、'
        + '金额是多少、家人什么时候点的头、对方什么时候给的回执。'),
    );
    return;
  }
  taskId = recent.id;

  // 只要这一件事的链，让**服务端**去筛。
  //
  // 原先是 `/v2/audit?limit=200` 再在客户端按 `entity_id` 过滤。那两件事不一样：
  // 一个家庭用久了，第 201 条之前的事务就再也拼不出完整的链——而页面上看不出来，
  // 它会渲染出一份**少了前几步**的凭证，而凭证的全部价值就是「每一步都在」。
  // `entity_id` 这个参数是这一轮加的（`api.py::list_audit`），limit 因此作用在
  // 这一件事的事件上，不是整个家庭的流水上。
  const audit = await api(
    `/v2/audit?limit=200&entity_id=${encodeURIComponent(taskId)}`, {}, 'family');
  const mine = audit.events || [];
  if (!mine.length) throw new Error('审计链里找不到这件任务');

  const task = recent;
  const amount = (task.details && task.details.amount_yuan) || '';

  host.replaceChildren();

  // --- 抬头 ---
  //
  // 抬头两行原先写死成「缴费凭证」和「水费 ${amount}元」。那在只认 bill_payment
  // 的时候还说得过去；现在挂号和提醒也能出凭证，写死就会给一次挂号盖上「缴费凭证」
  // 的头、再印一个空的金额。
  //
  // 所以这两行按类型算：眉题是「<类型>凭证」，主值是**这一类事最要紧的那个数**
  // ——缴费是金额，挂号是「医院 · 科室」，提醒是它的标题。取不到就不硬凑一个，
  // 退回 `summary`（后端给的整句），再不行才是类型词。
  const head = el('header', 'receipt-head');
  const left = el('div');
  const typeWord = window.YouHuo.taskWord(task.task_type);
  const details = task.details || {};
  const primary = amount
    ? `${details.bill_type || typeWord} ${amount}元`
    : ([details.hospital, details.department].filter(Boolean).join(' · ')
       || details.title
       || task.summary
       || typeWord);
  left.appendChild(el('p', 'receipt-eyebrow', `${typeWord}凭证`));
  left.appendChild(el('h3', 'receipt-title', primary));
  head.appendChild(left);
  const done = task.status === 'completed';
  head.appendChild(el('span', `pill ${done ? 'good' : 'bad'}`, done ? '已办好' : '未完成'));
  host.appendChild(head);

  // 印章由**这一笔的真实状态**决定，不写在 HTML 里。
  //
  // 写死在 markup 上的话，「正在读这件事的记录……」那一屏上就已经盖着章了，
  // 未完成的那一笔也会盖着章——在一整页都在讲「这里的每一条都可核验」的地方，
  // 一枚盖错的印章比没有印章糟得多。
  //
  // 每次重绘都要显式取反：只在 done 时设、不在 !done 时删的话，
  // 一笔办好的凭证之后切到一笔未完成的，章会留在上面。
  if (done) host.dataset.artSeal = 'true';
  else {
    delete host.dataset.artSeal;
    host.querySelector(':scope > .art-seal')?.remove();
  }

  // --- 没有进链的那一句 ---
  //
  // 这里原先有两种说法，靠 `asked` 分支：亲手办的那一次知道他说了什么，可以把原话
  // 摆出来。而「亲手办」就是上面被删掉的那条写路径——它一走，`asked` 恒为 null，
  // 那一半永远到不了。删一半留一半是回归的温床（下一个人会照着那半段以为这里
  // 还有两种状态），所以连它一起收掉。
  //
  // 留下的这一种本来就是更强的一次演示：**连做这个系统的人都没法从这条链上还原
  // 他当时说了什么。**
  const off = el('p', 'receipt-offchain');
  off.appendChild(el('strong', null, '他说的原话不在链上。'));
  // 「一件**缴费**任务」原先写死在这里。这一页已经不再按 `bill_payment` 过滤，
  // 所以一次挂号的凭证上会出现「链上只有『有一件缴费任务被建立』」——同一种写死，
  // 这个文件在抬头那两行上已经修过一次（见 `receipt-head` 上面那段）。
  off.appendChild(document.createTextNode(
    `这份凭证是从审计链上读出来的，而链上只有「有一件${typeWord}任务被建立」`
    + '——连我们自己都没法从这条链上还原他当时说了什么。'
    + '少记一样东西也是要证明的事，所以写在这里。'));
  host.appendChild(off);

  // --- 时间轴 ---
  //
  // 先把**整条链上的事实**算出来，再逐行渲染。有些话只有站在整条链上才说得出口：
  // 「家人同意的和他确认的是同一个」要拿两条记录比一次，而一行只看得见自己那一条。
  const facts = chainFacts(mine);
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
      try {
        proof = spec.proof(payload, facts) || '';
      } catch (error) {
        // **不静默吞掉。** 原先是 `catch (_) { proof = ''; }`——一条算不出说明的
        // 记录和一条本来就没有说明的记录在屏幕上长得一模一样，而这一页的全部主张
        // 是「链上每一条都在这儿、都能核」。`care.js` 的 `.catch(() => [])` 是同一
        // 种写法，它把服务端 500 显示成了「还没有登记」。
        console.error('凭证这一步的说明算不出来：', event.event_type, error);
        proof = '这一步的说明没能算出来。它的原始记录在下面的哈希里。';
      }
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
