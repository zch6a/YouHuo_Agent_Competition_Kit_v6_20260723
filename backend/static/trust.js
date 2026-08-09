'use strict';

// 身份、登录、401 重放和令牌缓存都在 common.js 里。
//
// 顺带修掉这一页原有的两个差异：它此前无条件写 `Authorization: Bearer ${token}`，
// token 为空串时会发出一个后面什么都没有的头；也没有 401 重放，令牌一过期，六张卡
// 的按钮就开始静默失败。
const {api, byId, pretty} = window.YouHuo;
const state = {saga: null, sagaRole: 'system',
  elderId: 'elder-demo', daughterId: 'daughter-demo', systemId: 'system-demo'};

function output(id, value) { byId(id).textContent = typeof value === 'string' ? value : pretty(value); }

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

bootstrap();
