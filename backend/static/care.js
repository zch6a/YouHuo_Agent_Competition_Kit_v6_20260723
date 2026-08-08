'use strict';

const state = { elderToken: '', familyToken: '',
  // Resolved in bootstrap() from identity.js: on a public deployment each
  // browser owns an isolated demo household, so these are not fixed.
  elderId: state.elderId, daughterId: state.daughterId, systemId: state.systemId };
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
