'use strict';

// 身份、登录、401 重放和令牌缓存都在 common.js 里。
//
// 顺带修掉这一页原有的两个差异：它此前无条件写 `Authorization: Bearer ${token}`，
// token 为空串时会发出一个后面什么都没有的头；也没有 401 重放，令牌一过期，六张卡
// 的按钮就开始静默失败。
const {api, byId, pretty} = window.YouHuo;
const state = {saga: null, sagaRole: 'system',
  elderId: 'elder-demo', daughterId: 'daughter-demo', systemId: 'system-demo'};

// 六张卡的输出原先全是 <pre> 里的原始 JSON。这一页讲的恰恰是"系统拒绝了什么、
// 为什么拒绝"，用 JSON 讲等于要求评委现场读一遍后端契约。见 common.js。
function output(id, value) { window.YouHuo.renderResult(id, value); }

async function bootstrap() {
  try {
    const ids = await window.YouHuo.ready();
    state.elderId = ids.elderId;
    state.daughterId = ids.daughterId;
    state.systemId = ids.systemId;
    await Promise.all([
      window.YouHuo.login('elder'), window.YouHuo.login('family'), window.YouHuo.login('system'),
    ]);
    byId('status').textContent = '演示身份已就绪。高风险动作不会由语言模型直接执行。';
  } catch (error) { byId('status').textContent = error.message; }
  // 凭证放在身份之后、并且不阻塞它：身份没建起来时凭证也办不成，但身份的状态行
  // 不该等一次完整缴费才更新。
  renderReceipt().catch(error => receiptFailed(error));
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
    what: '立了一件事，并按账单接口查了金额',
    proof: p => `任务类型 ${TASK_WORD[p.task_type] || p.task_type} · 风险级 ${p.risk} · `
      + `意图来源 ${BASIS_WORD[p.semantic_basis] || p.semantic_basis}`,
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
    proof: () => '任务停在"未成功"，不会报成已完成',
  },
  NOTIFICATION_CREATED: {
    who: '优活',
    what: p => (p.recipient_role === 'elder' ? '回头告诉了他' : '把这件事推给了家人'),
    proof: p => NOTIFY_WORD[p.event_type] || '一条通知',
  },
};
const TASK_WORD = {bill_payment: '缴费', appointment: '挂号', medication: '用药'};
const BASIS_WORD = {keyword_only: '关键词命中', embedding: '语义匹配', hybrid: '关键词加语义'};
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
  const host = byId('receipt');
  if (!host) return;
  // 不假装成功。这一页的全部内容就是"只有真办成了才说办成了"。
  host.replaceChildren(el('p', 'receipt-pending',
    `这一次没能办成，所以这里没有凭证可出：${error.message}`));
}

/** 真的走一遍缴费，然后把它的审计记录渲染出来。 */
async function renderReceipt() {
  const host = byId('receipt');
  if (!host) return;

  const session = (await api('/v2/sessions', {method: 'POST', body: '{}'})).session_id;
  const asked = '帮我交这个月的水费';
  const first = await api('/v2/chat', {
    method: 'POST', body: JSON.stringify({session_id: session, text: asked}),
  });
  const amount = (first.data && first.data.amount_yuan)
    || (first.message.match(/(\d+\.\d{2})\s*元/) || [])[1];
  if (!amount) throw new Error('账单金额没读到，不能凭空造一份凭证');

  // 复述确认必须念出金额——这一步就是这个产品的主张，凭证里当然要走真的那条路。
  const confirmed = await api('/v2/chat', {
    method: 'POST',
    body: JSON.stringify({session_id: session, text: `确认支付${amount}元`}),
  });
  if (!confirmed.approval_digest) throw new Error('没有拿到确认摘要');
  const taskId = confirmed.task_id;

  await api('/v2/family/approve', {
    method: 'POST',
    body: JSON.stringify({
      task_id: taskId, approve: true, approval_digest: confirmed.approval_digest,
    }),
  }, 'family');

  const audit = await api(`/v2/audit?limit=200`, {}, 'family');
  const mine = (audit.events || []).filter(e => e.entity_id === taskId);
  if (!mine.length) throw new Error('审计链里找不到这件任务');

  const tasks = await api('/v2/tasks?limit=100', {}, 'family');
  const task = tasks.find(t => t.id === taskId) || {};

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
  const off = el('p', 'receipt-offchain');
  off.appendChild(el('strong', null, '他说的原话不在链上。'));
  off.appendChild(document.createTextNode(
    `这一次他说的是「${asked}」，而审计链里只有"有一件缴费任务被建立"。`
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

byId('voiceSafe').addEventListener('click', async () => {
  try {
    output('voiceOutput', await api('/v5/voice/resolve', { method: 'POST', body: JSON.stringify({
      elder_id: state.elderId, side_effect_possible: true,
      candidates: [
        { text: '帮我交水费', confidence: 0.96, engine: 'HarmonyASR' },
        { text: '帮我缴水费', confidence: 0.93, engine: 'BackupASR' }
      ]
    }) }));
  } catch (error) { output('voiceOutput', error.message); }
});

byId('voiceConflict').addEventListener('click', async () => {
  try {
    output('voiceOutput', await api('/v5/voice/resolve', { method: 'POST', body: JSON.stringify({
      elder_id: state.elderId, side_effect_possible: true,
      candidates: [
        { text: '确认办理缴费', confidence: 0.92, engine: 'HarmonyASR' },
        { text: '取消不要缴费', confidence: 0.91, engine: 'BackupASR' }
      ]
    }) }));
  } catch (error) { output('voiceOutput', error.message); }
});

function paymentPolicyPayload(untrusted) {
  return {
    elder_id: state.elderId, goal: '帮我交本月水费', action: 'create_payment_request',
    arguments: { bill_id: 'bill-water-2026-07', amount_cents: untrusted ? 999999 : 6840, elder_id: state.elderId },
    facts: [
      { name: 'bill_id', value: 'bill-water-2026-07', origin: 'trusted_tool', purpose: 'bill_payment', trusted_for_control: true },
      { name: 'amount_cents', value: untrusted ? 999999 : 6840, origin: untrusted ? 'untrusted_document' : 'trusted_tool', purpose: 'bill_payment', trusted_for_control: !untrusted },
      { name: 'elder_id', value: state.elderId, origin: 'system', sensitivity: 3, purpose: 'bill_payment', trusted_for_control: true }
    ],
    user_confirmed: true, family_approvals: 1, reversible: true
  };
}

byId('policySafe').addEventListener('click', async () => {
  try { output('policyOutput', await api('/v5/actions/authorize', { method: 'POST', body: JSON.stringify(paymentPolicyPayload(false)) })); }
  catch (error) { output('policyOutput', error.message); }
});
byId('policyAttack').addEventListener('click', async () => {
  try { output('policyOutput', await api('/v5/actions/authorize', { method: 'POST', body: JSON.stringify(paymentPolicyPayload(true)) })); }
  catch (error) { output('policyOutput', error.message); }
});

byId('sagaCreate').addEventListener('click', async () => {
  try {
    state.saga = await api('/v5/sagas', { method: 'POST', body: JSON.stringify({
      elder_id: state.elderId, kind: 'bill_payment', goal: '交本月水费', context: { bill_type: '水费' },
      request_id: `trust-lab-${Date.now()}`
    }) });
    state.sagaRole = 'system';
    output('sagaOutput', state.saga);
  } catch (error) { output('sagaOutput', error.message); }
});

byId('sagaAdvance').addEventListener('click', async () => {
  if (!state.saga) { output('sagaOutput', '请先创建Saga。'); return; }
  try {
    const step = state.saga.steps[state.saga.current_step_index];
    let role = 'system';
    if (step.name === 'elder_confirm') role = 'elder';
    if (step.name === 'family_approval') role = 'family';
    const outputs = {
      locate_bill: { bill_id: 'bill-water-2026-07', amount_cents: 6840 }, elder_confirm: { confirmed: true },
      family_approval: { approved: true }, generate_payment_request: { request_id: 'demo-payment-request' },
      observe_authoritative_payment_state: { paid: true, receipt: 'demo-receipt' }, verify_final_state: { verified: true }
    };
    state.saga = await api(`/v5/sagas/${state.saga.id}/advance`, { method: 'POST', body: JSON.stringify({
      outcome: 'success', output: outputs[step.name] || {}, expected_version: state.saga.version,
      idempotency_key: `${state.saga.id}-${state.saga.version}`
    }) }, role);
    output('sagaOutput', state.saga);
  } catch (error) { output('sagaOutput', error.message); }
});

async function register(role, actorId, deviceId) {
  try {
    await api('/v4/devices', { method: 'POST', body: JSON.stringify({
      actor_id: actorId, device_id: deviceId, platform: 'HarmonyOS', brand: 'Demo', device_name: deviceId, push_capable: true
    }) }, role);
  } catch (error) {
    if (!String(error.message).includes('UNIQUE')) throw error;
  }
}

byId('syncDemo').addEventListener('click', async () => {
  try {
    const suffix = String(Date.now());
    await register('elder', state.elderId, `elder-${suffix}`);
    await register('family', state.daughterId, `family-${suffix}`);
    const first = await api('/v5/sync/operations', { method: 'POST', body: JSON.stringify({
      operation_id: `op-a-${suffix}`, device_id: `elder-${suffix}`, entity_type: 'health_profile', entity_id: state.elderId,
      field_name: 'preferred_hospital', value: '人民医院', base_version: 0, lamport_clock: 1, sensitivity: 'high',
      occurred_at: new Date().toISOString()
    }) });
    const second = await api('/v5/sync/operations', { method: 'POST', body: JSON.stringify({
      operation_id: `op-b-${suffix}`, device_id: `family-${suffix}`, entity_type: 'health_profile', entity_id: state.elderId,
      field_name: 'preferred_hospital', value: '协和医院', base_version: 0, lamport_clock: 2, sensitivity: 'high',
      occurred_at: new Date().toISOString()
    }) }, 'family');
    output('syncOutput', { first, second });
  } catch (error) { output('syncOutput', error.message); }
});

byId('breakGlassDemo').addEventListener('click', async () => {
  try {
    const record = await api('/v5/break-glass', { method: 'POST', body: JSON.stringify({
      elder_id: state.elderId, reason: '老人主动呼救后电话中断，需要确认最近位置',
      scopes: ['location', 'emergency_contacts', 'active_tasks'], duration_minutes: 10
    }) }, 'family');
    const view = await api(`/v5/break-glass/${record.id}/view`, {}, 'family');
    output('breakGlassOutput', { record, view });
  } catch (error) { output('breakGlassOutput', error.message); }
});

byId('truthDemo').addEventListener('click', async () => {
  try { output('truthOutput', await api('/v5/capability-truth')); }
  catch (error) { output('truthOutput', error.message); }
});
byId('metricsDemo').addEventListener('click', async () => {
  try { output('truthOutput', await api('/v5/metrics', {}, 'family')); }
  catch (error) { output('truthOutput', error.message); }
});

// 页内分区，与家人端、照护页同一份实现（common.js）。这一页原先是六张卡各带一两个
// 按钮并排铺开，标题用的是工程名字；现在每一段回答一个具体的疑问。
//
// 页头四条底线里的「看一次 →」是普通 hash 链接，落到 initSections 装的 hashchange
// 上——"主张"和"验证它的那一段"因此共用同一套机制，不需要第二份代码。
window.YouHuo.initSections('hear');

bootstrap();
