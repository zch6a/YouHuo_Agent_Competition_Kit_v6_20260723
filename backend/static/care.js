'use strict';

const state = { elderToken: '', familyToken: '',
  // Resolved in bootstrap() from identity.js: on a public deployment each
  // browser owns an isolated demo household, so these are not fixed. The
  // literals below are only the fallback for when identity.js is unavailable,
  // and they match the SHARED household in that file.
  elderId: 'elder-demo', daughterId: 'daughter-demo', systemId: 'system-demo' };
const byId = (id) => document.getElementById(id);

function pretty(value) {
  return JSON.stringify(value, null, 2);
}

async function api(path, options = {}, role = 'elder') {
  const token = role === 'family' ? state.familyToken : state.elderToken;
  const headers = { 'Content-Type': 'application/json', ...(options.headers || {}) };
  if (token) headers.Authorization = `Bearer ${token}`;
  const response = await fetch(path, { ...options, headers });
  const body = await response.json().catch(() => ({ detail: '非JSON响应' }));
  if (!response.ok) throw new Error(body.detail || `HTTP ${response.status}`);
  return body;
}

async function login(actorId) {
  const response = await fetch('/v2/auth/demo', {
    method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ actor_id: actorId })
  });
  if (!response.ok) throw new Error(`演示登录失败：${actorId}`);
  return (await response.json()).access_token;
}

function setOutput(id, value) {
  byId(id).textContent = typeof value === 'string' ? value : pretty(value);
}

async function resolveIdentity() {
  if (!window.YouHuoIdentity) return;
  const identity = await window.YouHuoIdentity.ready();
  state.elderId = identity.elderId;
  state.daughterId = identity.daughterId;
  state.systemId = identity.systemId;
}

async function bootstrap() {
  try {
    await resolveIdentity();
    [state.elderToken, state.familyToken] = await Promise.all(
      [login(state.elderId), login(state.daughterId)]);
    byId('status').textContent = '演示账户已就绪：老人本人负责同意，家属负责建议与高风险接力。';
  } catch (error) {
    byId('status').textContent = `初始化失败：${error.message}`;
  }
}

// 个性化基线（核心创新点 ①）。
//
// 这一块不是又一个 JSON 输出框。它要回答的是设计稿里那个具体问题："老人 A 每天上午
// 散步，老人 B 每天上午在家读书"——所以先把**他自己的**常态一行行摆出来，再说今天。
const CHANNEL_ICON = { wake: '起床', sleep: '就寝', outing: '外出', medication: '服药', conversation: '说话' };
const VERDICT_PILL = { typical: ['和平常一样', 'good'], notice: ['有一点不同', 'warn'],
                       marked: ['和平常不太一样', 'bad'],
                       unknown: ['还没有记录', 'warn'], pending: ['还不好说', ''] };

function renderBaseline(snapshot, care) {
  const host = byId('baselineOutput');
  host.replaceChildren();

  const head = document.createElement('div');
  const [word, tone] = VERDICT_PILL[snapshot.overall] || VERDICT_PILL.unknown;
  head.className = `report-verdict ${tone}`;
  const badge = document.createElement('span');
  badge.className = 'report-badge';
  badge.textContent = word;
  const line = document.createElement('strong');
  line.textContent = snapshot.headline;
  head.append(badge, line);
  host.appendChild(head);

  // 他自己的常态。这张表就是"千人千面"本身——同一个 0 次外出，对散步的老人和
  // 读书的老人是两个结论，因为这一列的数字不一样。
  const table = document.createElement('div');
  table.className = 'digest';
  snapshot.baselines.forEach((b) => {
    const dev = snapshot.deviations.find((d) => d.channel === b.channel);
    const row = document.createElement('div');
    row.className = 'digest-row';
    const label = document.createElement('strong');
    label.textContent = CHANNEL_ICON[b.channel] || b.label;
    const cell = document.createElement('div');
    cell.textContent = b.established
      ? `他平常 ${b.center_text}｜今天 ${dev && dev.observed_text ? dev.observed_text : '还没有记录'}`
      : b.reason;
    row.append(label, cell);
    table.appendChild(row);
  });
  host.appendChild(table);

  if (care) {
    const spoken = document.createElement('p');
    spoken.className = 'notice good';
    spoken.textContent = `会对老人说：「${care.spoken}」`;
    host.appendChild(spoken);
    if (care.light) {
      const light = document.createElement('p');
      light.className = 'meta';
      light.textContent = `灯光建议：亮度 ${care.light.brightness_pct}%`
        + `${care.light.warm ? '、暖光' : ''}${care.light.breathing ? '、慢呼吸' : ''}`
        + `——${care.light.reason}（建议，未驱动任何设备）`;
      host.appendChild(light);
    }
    if (care.suggest_mode) {
      const mode = document.createElement('p');
      mode.className = 'meta';
      mode.textContent = '建议切换到无忧伴陪伴模式主动安抚。';
      host.appendChild(mode);
    }
    care.schedule_hints.forEach((hint) => {
      const item = document.createElement('p');
      item.className = 'meta';
      item.textContent = `日程建议：${hint}`;
      host.appendChild(item);
    });
  }
}

byId('baselineDemo').addEventListener('click', async () => {
  try {
    const [snapshot, care] = await Promise.all([
      api(`/v7/baseline/${state.elderId}`),
      api(`/v7/care/${state.elderId}`),
    ]);
    renderBaseline(snapshot, care);
  } catch (error) { setOutput('baselineOutput', error.message); }
});

// 环境上报：演示"同样的偏离，屋里冷要说不同的话"。
byId('coldRoomDemo').addEventListener('click', async () => {
  try {
    await api('/v7/environment/samples', {
      method: 'POST', body: JSON.stringify({
        elder_id: state.elderId, temperature_c: 13.5, humidity_pct: 28.0, lux: 40.0,
        occurred_at: new Date().toISOString(), source: 'care-demo',
      })
    });
    const [snapshot, care] = await Promise.all([
      api(`/v7/baseline/${state.elderId}`),
      api(`/v7/care/${state.elderId}`),
    ]);
    renderBaseline(snapshot, care);
  } catch (error) { setOutput('baselineOutput', error.message); }
});

// 让偏离真的发生一次。
//
// 不是把界面切到"异常"配色看看效果——那是假的。这里真的往 /v4/safety/heartbeat 写
// 一条 11:20 的活动记录，然后整条链路（事件流 → 推导观测 → 与他自己的常态比 → 关怀
// 动作）自己得出结论。演示里能看到的东西，和真实运行时是同一条路径。
// 演示用的偏离时刻必须是**已经发生过的**。
//
// 原先写死"今天 11:20"。在 11:20 之前按下这个按钮，那是一条未来的活动记录：后端现在
// 会 422 拒掉（因为一条未来心跳会让无交互预警永久失效），而在加那道校验之前，它会被
// 收下——演示按钮亲手关掉了这位老人的安全告警。
//
// 还没到 11:20 就退到"刚刚"。偏离方向会从"起晚了"变成"起早了"，但那同样是真实的
// 偏离，而且结论仍然由后端拿他自己的常态算出来，不是界面演的。
function pastDeviationMoment() {
  const now = new Date();
  const late = new Date(now.getFullYear(), now.getMonth(), now.getDate(), 11, 20);
  return late < now ? late : new Date(now.getTime() - 2 * 60 * 1000);
}

byId('lateWakeDemo').addEventListener('click', async () => {
  try {
    const late = pastDeviationMoment();
    await api('/v4/safety/heartbeat', {
      method: 'POST', body: JSON.stringify({
        elder_id: state.elderId, kind: 'morning_activity', occurred_at: late.toISOString(),
      })
    });
    const [snapshot, care] = await Promise.all([
      api(`/v7/baseline/${state.elderId}`),
      api(`/v7/care/${state.elderId}`),
    ]);
    renderBaseline(snapshot, care);
  } catch (error) { setOutput('baselineOutput', error.message); }
});

byId('routineDemo').addEventListener('click', async () => {
  try {
    const suffix = String(Date.now()).slice(-6);
    const routine = await api('/v4/routines', {
      method: 'POST', body: JSON.stringify({
        elder_id: state.elderId, title: `每月交水费-${suffix}`, category: 'payment', frequency: 'monthly',
        interval: 1, day_of_month: 25, time_local: '09:00', timezone: 'Asia/Shanghai',
        start_date: '2026-07-25', escalation_after_minutes: 60,
        positive_message: '水费任务完成了，我们做得可真棒！'
      })
    }, 'family');
    const materialized = await api('/v4/routines/materialize', {
      method: 'POST', body: JSON.stringify({ now: '2026-07-22T00:00:00Z', horizon_days: 60 })
    }, 'family');
    setOutput('routineOutput', { routine, materialized });
  } catch (error) { setOutput('routineOutput', error.message); }
});

byId('monthlyReport').addEventListener('click', async () => {
  try {
    const report = await api('/v4/reports/monthly', {
      method: 'POST', body: JSON.stringify({ elder_id: state.elderId, year: 2026, month: 7 })
    }, 'family');
    setOutput('routineOutput', report);
  } catch (error) { setOutput('routineOutput', error.message); }
});

byId('emotionDemo').addEventListener('click', async () => {
  try {
    const result = await api('/v4/emotions/analyze', {
      method: 'POST', body: JSON.stringify({ elder_id: state.elderId, text: byId('emotionText').value, store_event: true })
    });
    setOutput('emotionOutput', result);
  } catch (error) { setOutput('emotionOutput', error.message); }
});

byId('medicalDemo').addEventListener('click', async () => {
  try {
    const result = await api('/v4/medical-reports/analyze', {
      method: 'POST', body: JSON.stringify({
        elder_id: state.elderId, kind: 'checkup_report', text: byId('medicalText').value,
        source_name: '全景照护中心演示', create_followup_reminder: true
      })
    });
    setOutput('medicalOutput', result);
  } catch (error) { setOutput('medicalOutput', error.message); }
});

byId('interactionDemo').addEventListener('click', async () => {
  try {
    const result = await api('/v4/medications/interactions/check', {
      method: 'POST', body: JSON.stringify({ medication_names: ['华法林', '阿司匹林'] })
    });
    setOutput('interactionOutput', result);
  } catch (error) { setOutput('interactionOutput', error.message); }
});

async function ensurePolicy() {
  return api('/v4/safety/policy', {
    method: 'PUT', body: JSON.stringify({
      elder_id: state.elderId, inactivity_minutes: 720, home_lat: 39.9042, home_lon: 116.3974,
      geofence_radius_m: 1000, notify_community: true
    })
  }, 'family');
}

byId('locationInside').addEventListener('click', async () => {
  try {
    await ensurePolicy();
    const result = await api('/v4/location/ping', {
      method: 'POST', body: JSON.stringify({
        elder_id: state.elderId, latitude: 39.9042, longitude: 116.3974, accuracy_m: 20,
        occurred_at: new Date().toISOString(), source: 'care_hub_demo'
      })
    });
    setOutput('locationOutput', result);
  } catch (error) { setOutput('locationOutput', error.message); }
});

byId('locationOutside').addEventListener('click', async () => {
  try {
    await ensurePolicy();
    const result = await api('/v4/location/ping', {
      method: 'POST', body: JSON.stringify({
        elder_id: state.elderId, latitude: 39.95, longitude: 116.45, accuracy_m: 20,
        occurred_at: new Date().toISOString(), source: 'care_hub_demo'
      })
    });
    setOutput('locationOutput', result);
  } catch (error) { setOutput('locationOutput', error.message); }
});

byId('sosDemo').addEventListener('click', async () => {
  try {
    await ensurePolicy();
    const result = await api('/v4/safety/sos', {
      method: 'POST', body: JSON.stringify({ elder_id: state.elderId, include_community: true })
    });
    setOutput('locationOutput', result);
  } catch (error) { setOutput('locationOutput', error.message); }
});

byId('capabilitiesDemo').addEventListener('click', async () => {
  const container = byId('capabilityList');
  container.replaceChildren();
  try {
    const capabilities = await api('/v4/capabilities');
    for (const item of capabilities) {
      const card = document.createElement('section');
      card.className = 'task capability-card';
      const title = document.createElement('strong');
      title.textContent = `${item.capability} · ${item.state}`;
      const implementation = document.createElement('p');
      implementation.textContent = item.implementation;
      const boundary = document.createElement('p');
      boundary.className = 'meta';
      boundary.textContent = `安全边界：${item.safety_boundary}`;
      card.append(title, implementation, boundary);
      container.append(card);
    }
  } catch (error) {
    container.textContent = error.message;
  }
});

bootstrap();
