'use strict';
/* 从手机框里搬出来的工程与演示控件，全部落在这一页（/stage）。
 *
 * 它们原先住在 `/trust`（十个）和 `/care`（十二个）里，也就是**手机框内**。设计稿
 * 第 26 节给的判据是：把手机框单独截图，任何普通人都该觉得"这就是一个能下载使用的
 * App"。而「演示恶意文档金额」「加载聚合指标」「创建缴费Saga」这些按钮出现在一位
 * 78 岁用户的手机里，是把整个比赛项目塞进了产品里。
 *
 * 所以搬。**一个都没删**：同一个 handler、同一个接口、同一个输出区，只换了位置。
 * `test_no_control_was_silently_deleted.py` 把这份对应关系写成数据，删掉一个就红。
 *
 * 为什么不是「复制一份到桌面」：两份会分叉。`common.js` 那次合并的教训就是同一段
 * 代码抄五遍会有五个各自正确、各自不同的版本，而 `/care` 和 `/trust` 那个让两整页
 * 全死的 TDZ 笔误正是这样同时存在于两个文件里的。
 */

(() => {
  const {api, byId} = window.YouHuo;

  // 三个角色的 id。`bootstrap()` 之前先给上兜底值，因为这一页的按钮在身份就绪之前
  // 就可以被按（`check_page_runtime` 的遍历不等任何人）。
  const state = {
    saga: null,
    elderId: 'elder-demo', daughterId: 'daughter-demo', systemId: 'system-demo',
  };

  function output(id, value) { window.YouHuo.renderResult(id, value); }

  /** 取控件；**取不到就吼**。
   *
   * 上一版这里是裸的 `byId(x).addEventListener(...)`：控件被改名或漏搬时抛
   * TypeError，而那个错误发生在文件顶层——它会把后面所有绑定一起带走，整页按钮
   * 静默失效。`/care` 和 `/trust` 那次两整页全死就是这么发生的。
   *
   * 但也不能默默跳过：一个"搬丢了的按钮"和"本来就不该有的按钮"在静默版本里长得
   * 一模一样。`console.error` 是这里唯一正确的响应——`check_page_runtime` 把
   * console 错误当失败，所以搬丢一个控件会在闸门上响亮地红，而不是变成一页死按钮。
   */
  function on(id, event, handler) {
    const node = byId(id);
    if (!node) {
      console.error(`[proof-demos] 控件 #${id} 不在这一页上——它是从手机框里搬过来的，`
        + '要么改名了，要么搬丢了。迁移矩阵在 test_no_control_was_silently_deleted.py。');
      return;
    }
    node.addEventListener(event, handler);
  }

  async function bootstrap() {
    const status = byId('proofStatus');
    try {
      const ids = await window.YouHuo.ready();
      state.elderId = ids.elderId;
      state.daughterId = ids.daughterId;
      state.systemId = ids.systemId;
      await Promise.all([
        window.YouHuo.login('elder'), window.YouHuo.login('family'), window.YouHuo.login('system'),
      ]);
      // 成功就收起来。一块绿色的"已就绪"占着右栏最上面那格，而它说的只是"就绪了"
      // ——这个项目已经在照护页和家人端各修过一次同样的事。失败时它必须看得见，
      // 所以是 hidden 而不是删掉。
      if (status) status.hidden = true;
    } catch (error) {
      if (status) {
        status.hidden = false;
        status.classList.remove('good');
        status.textContent = `没能建立演示身份：${error.message}——下面的按钮会失败。`;
      }
    }
  }

  /* ======================================================================
     证明 · 语音共识
     ====================================================================== */

  on('voiceSafe', 'click', async () => {
    try {
      output('voiceOutput', await api('/v5/voice/resolve', {method: 'POST', body: JSON.stringify({
        elder_id: state.elderId, side_effect_possible: true,
        candidates: [
          {text: '帮我交水费', confidence: 0.96, engine: 'HarmonyASR'},
          {text: '帮我缴水费', confidence: 0.93, engine: 'BackupASR'},
        ],
      })}));
    } catch (error) { output('voiceOutput', error.message); }
  });

  on('voiceConflict', 'click', async () => {
    try {
      output('voiceOutput', await api('/v5/voice/resolve', {method: 'POST', body: JSON.stringify({
        elder_id: state.elderId, side_effect_possible: true,
        candidates: [
          {text: '确认办理缴费', confidence: 0.92, engine: 'HarmonyASR'},
          {text: '取消不要缴费', confidence: 0.91, engine: 'BackupASR'},
        ],
      })}));
    } catch (error) { output('voiceOutput', error.message); }
  });

  /* ======================================================================
     证明 · 目的绑定策略防火墙
     ====================================================================== */

  function paymentPolicyPayload(untrusted) {
    return {
      elder_id: state.elderId, goal: '帮我交本月水费', action: 'create_payment_request',
      arguments: {
        bill_id: 'bill-water-2026-07', amount_cents: untrusted ? 999999 : 6840,
        elder_id: state.elderId,
      },
      facts: [
        {name: 'bill_id', value: 'bill-water-2026-07', origin: 'trusted_tool',
         purpose: 'bill_payment', trusted_for_control: true},
        {name: 'amount_cents', value: untrusted ? 999999 : 6840,
         origin: untrusted ? 'untrusted_document' : 'trusted_tool',
         purpose: 'bill_payment', trusted_for_control: !untrusted},
        {name: 'elder_id', value: state.elderId, origin: 'system', sensitivity: 3,
         purpose: 'bill_payment', trusted_for_control: true},
      ],
      user_confirmed: true, family_approvals: 1, reversible: true,
    };
  }

  on('policySafe', 'click', async () => {
    try {
      output('policyOutput', await api('/v5/actions/authorize',
        {method: 'POST', body: JSON.stringify(paymentPolicyPayload(false))}));
    } catch (error) { output('policyOutput', error.message); }
  });

  on('policyAttack', 'click', async () => {
    try {
      output('policyOutput', await api('/v5/actions/authorize',
        {method: 'POST', body: JSON.stringify(paymentPolicyPayload(true))}));
    } catch (error) { output('policyOutput', error.message); }
  });

  /* ======================================================================
     证明 · 限时紧急破窗
     ====================================================================== */

  on('breakGlassDemo', 'click', async () => {
    try {
      const record = await api('/v5/break-glass', {method: 'POST', body: JSON.stringify({
        elder_id: state.elderId, reason: '老人主动呼救后电话中断，需要确认最近位置',
        scopes: ['location', 'emergency_contacts', 'active_tasks'], duration_minutes: 10,
      })}, 'family');
      const view = await api(`/v5/break-glass/${record.id}/view`, {}, 'family');
      output('breakGlassOutput', {record, view});
    } catch (error) { output('breakGlassOutput', error.message); }
  });

  /* ======================================================================
     证明 · 同意记忆
     ..........................................................................
     四条底线里唯一原先没有任何按钮的一条。「记什么、记多久，由老人本人批准」写在
     可信页的页头上，而这一页只有另外三条能当场按一次——一条按不动的底线和一句
     宣传没有区别。

     三个都是既有接口，没有新增后端：propose（家人或老人）→ decide（**只有老人**）
     → 列表。刻意让「老人本人批准」这一步用老人的令牌、提议用家人的令牌，因为这条
     底线的全部内容就是这两个角色不能互换。
     ====================================================================== */

  //: 每次提议换一个 key，否则第二次按下去撞唯一约束，看起来像坏了。
  let memoryId = null;

  on('memoryPropose', 'click', async () => {
    try {
      const item = await api('/v3/memories/propose', {method: 'POST', body: JSON.stringify({
        elder_id: state.elderId, key: `favourite_tea_${Date.now().toString(36)}`,
        value: '龙井', sensitivity: 'preference', scope: 'family_summary',
        purpose: '陪聊时能接上话', ttl_days: 180,
      })}, 'family');
      memoryId = item.id;
      output('memoryOutput', item);
    } catch (error) { output('memoryOutput', error.message); }
  });

  on('memoryApprove', 'click', async () => {
    if (!memoryId) { output('memoryOutput', '先让女儿提议一件事，才有东西可批准。'); return; }
    try {
      output('memoryOutput', await api('/v3/memories/decide', {
        method: 'POST', body: JSON.stringify({memory_id: memoryId, approve: true}),
      }, 'elder'));
    } catch (error) { output('memoryOutput', error.message); }
  });

  on('memoryList', 'click', async () => {
    try { output('memoryOutput', await api(`/v3/memories/${state.elderId}`, {}, 'elder')); }
    catch (error) { output('memoryOutput', error.message); }
  });

  /* ======================================================================
     证明 · 可恢复任务 Saga（家庭共识）
     ====================================================================== */

  on('sagaCreate', 'click', async () => {
    try {
      state.saga = await api('/v5/sagas', {method: 'POST', body: JSON.stringify({
        elder_id: state.elderId, kind: 'bill_payment', goal: '交本月水费',
        context: {bill_type: '水费'}, request_id: `trust-lab-${Date.now()}`,
      })});
      output('sagaOutput', state.saga);
    } catch (error) { output('sagaOutput', error.message); }
  });

  on('sagaAdvance', 'click', async () => {
    if (!state.saga) { output('sagaOutput', '请先创建Saga。'); return; }
    try {
      const step = state.saga.steps[state.saga.current_step_index];
      let role = 'system';
      if (step.name === 'elder_confirm') role = 'elder';
      if (step.name === 'family_approval') role = 'family';
      const outputs = {
        locate_bill: {bill_id: 'bill-water-2026-07', amount_cents: 6840},
        elder_confirm: {confirmed: true},
        family_approval: {approved: true},
        generate_payment_request: {request_id: 'demo-payment-request'},
        observe_authoritative_payment_state: {paid: true, receipt: 'demo-receipt'},
        verify_final_state: {verified: true},
      };
      state.saga = await api(`/v5/sagas/${state.saga.id}/advance`, {
        method: 'POST', body: JSON.stringify({
          outcome: 'success', output: outputs[step.name] || {},
          expected_version: state.saga.version,
          idempotency_key: `${state.saga.id}-${state.saga.version}`,
        }),
      }, role);
      output('sagaOutput', state.saga);
    } catch (error) { output('sagaOutput', error.message); }
  });

  /* ======================================================================
     工程 · 跨设备离线冲突
     ====================================================================== */

  async function register(role, actorId, deviceId) {
    try {
      await api('/v4/devices', {method: 'POST', body: JSON.stringify({
        actor_id: actorId, device_id: deviceId, platform: 'HarmonyOS', brand: 'Demo',
        device_name: deviceId, push_capable: true,
      })}, role);
    } catch (error) {
      if (!String(error.message).includes('UNIQUE')) throw error;
    }
  }

  on('syncDemo', 'click', async () => {
    try {
      const suffix = String(Date.now());
      await register('elder', state.elderId, `elder-${suffix}`);
      await register('family', state.daughterId, `family-${suffix}`);
      const first = await api('/v5/sync/operations', {method: 'POST', body: JSON.stringify({
        operation_id: `op-a-${suffix}`, device_id: `elder-${suffix}`,
        entity_type: 'health_profile', entity_id: state.elderId,
        field_name: 'preferred_hospital', value: '人民医院', base_version: 0,
        lamport_clock: 1, sensitivity: 'high', occurred_at: new Date().toISOString(),
      })});
      const second = await api('/v5/sync/operations', {method: 'POST', body: JSON.stringify({
        operation_id: `op-b-${suffix}`, device_id: `family-${suffix}`,
        entity_type: 'health_profile', entity_id: state.elderId,
        field_name: 'preferred_hospital', value: '协和医院', base_version: 0,
        lamport_clock: 2, sensitivity: 'high', occurred_at: new Date().toISOString(),
      })}, 'family');
      output('syncOutput', {first, second});
    } catch (error) { output('syncOutput', error.message); }
  });

  /* ======================================================================
     工程 · 能力真值与运行指标
     ====================================================================== */

  on('truthDemo', 'click', async () => {
    try { output('truthOutput', await api('/v5/capability-truth')); }
    catch (error) { output('truthOutput', error.message); }
  });

  on('metricsDemo', 'click', async () => {
    try { output('truthOutput', await api('/v5/metrics', {}, 'family')); }
    catch (error) { output('truthOutput', error.message); }
  });

  on('capabilitiesDemo', 'click', async () => {
    const container = byId('capabilityList');
    if (!container) return;
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

  /* ======================================================================
     演示 · 个性化基线（核心创新点 ①）的场景注入
     ..........................................................................
     这三个按钮不是"把界面切到异常配色看看效果"。它们真的往环境采样和活动心跳写一条
     记录，然后整条链路（事件流 → 推导观测 → 与他自己的常态比 → 关怀动作）自己得出
     结论。演示里看到的东西和真实运行时是同一条路径。

     它们必须留在**桌面**：往老人的照护档案里塞一条「屋里 13.5℃」是答辩动作，
     不是一位子女会做的事。照护页现在进页面就自动读真实数据，不需要按钮。
     ====================================================================== */

  const CHANNEL_WORD = {
    wake: '起床', sleep: '就寝', outing: '外出', medication: '服药', conversation: '说话',
  };
  const verdictOf = window.YouHuo.verdictOf;

  function renderBaseline(snapshot, care) {
    const host = byId('baselineOutput');
    if (!host) return;
    host.replaceChildren();

    const head = document.createElement('div');
    const [word, tone] = verdictOf(snapshot.overall);
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
      label.textContent = CHANNEL_WORD[b.channel] || b.label;
      const cell = document.createElement('div');
      cell.textContent = b.established
        ? `他平常 ${b.center_text}｜今天 ${dev && dev.observed_text ? dev.observed_text : '还没有记录'}`
        : b.reason;
      row.append(label, cell);
      table.appendChild(row);
    });
    host.appendChild(table);

    if (!care) return;
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

  async function showBaseline() {
    const [snapshot, care] = await Promise.all([
      api(`/v7/baseline/${state.elderId}`),
      api(`/v7/care/${state.elderId}`),
    ]);
    renderBaseline(snapshot, care);
  }

  on('baselineDemo', 'click', async () => {
    try { await showBaseline(); }
    catch (error) { output('baselineOutput', error.message); }
  });

  on('coldRoomDemo', 'click', async () => {
    try {
      await api('/v7/environment/samples', {method: 'POST', body: JSON.stringify({
        elder_id: state.elderId, temperature_c: 13.5, humidity_pct: 28.0, lux: 40.0,
        occurred_at: new Date().toISOString(), source: 'care-demo',
      })});
      await showBaseline();
    } catch (error) { output('baselineOutput', error.message); }
  });

  /** 让偏离真的发生一次，而且这个时刻必须是**已经发生过的**。
   *
   * 原先写死"今天 11:20"。在 11:20 之前按下这个按钮，那是一条未来的活动记录：后端
   * 现在会 422 拒掉（一条未来心跳会让无交互预警永久失效），而在加那道校验之前，它
   * 会被收下——演示按钮亲手关掉了这位老人的安全告警。
   *
   * 还没到 11:20 就退到"刚刚"。偏离方向会从"起晚了"变成"起早了"，但那同样是真实的
   * 偏离，而且结论仍然由后端拿他自己的常态算出来，不是界面演的。
   */
  function pastDeviationMoment() {
    const now = new Date();
    const late = new Date(now.getFullYear(), now.getMonth(), now.getDate(), 11, 20);
    return late < now ? late : new Date(now.getTime() - 2 * 60 * 1000);
  }

  on('lateWakeDemo', 'click', async () => {
    try {
      await api('/v4/safety/heartbeat', {method: 'POST', body: JSON.stringify({
        elder_id: state.elderId, kind: 'morning_activity',
        occurred_at: pastDeviationMoment().toISOString(),
      })});
      await showBaseline();
    } catch (error) { output('baselineOutput', error.message); }
  });

  /* ======================================================================
     演示 · 循环事务、用药、情绪、体检、位置
     ====================================================================== */

  on('routineDemo', 'click', async () => {
    try {
      const suffix = String(Date.now()).slice(-6);
      const routine = await api('/v4/routines', {method: 'POST', body: JSON.stringify({
        elder_id: state.elderId, title: `每月交水费-${suffix}`, category: 'payment',
        frequency: 'monthly', interval: 1, day_of_month: 25, time_local: '09:00',
        timezone: 'Asia/Shanghai', start_date: '2026-07-25', escalation_after_minutes: 60,
        positive_message: '水费任务完成了，我们做得可真棒！',
      })}, 'family');
      const materialized = await api('/v4/routines/materialize', {
        method: 'POST', body: JSON.stringify({now: '2026-07-22T00:00:00Z', horizon_days: 60}),
      }, 'family');
      output('routineOutput', {routine, materialized});
    } catch (error) { output('routineOutput', error.message); }
  });

  on('monthlyReport', 'click', async () => {
    try {
      output('routineOutput', await api('/v4/reports/monthly', {
        method: 'POST', body: JSON.stringify({
          elder_id: state.elderId, year: new Date().getFullYear(),
          month: new Date().getMonth() + 1,
        }),
      }, 'family'));
    } catch (error) { output('routineOutput', error.message); }
  });

  on('interactionDemo', 'click', async () => {
    try {
      output('interactionOutput', await api('/v4/medications/interactions/check', {
        method: 'POST', body: JSON.stringify({medication_names: ['华法林', '阿司匹林']}),
      }));
    } catch (error) { output('interactionOutput', error.message); }
  });

  on('emotionDemo', 'click', async () => {
    try {
      const text = byId('emotionText');
      output('emotionOutput', await api('/v4/emotions/analyze', {
        method: 'POST', body: JSON.stringify({
          elder_id: state.elderId, text: text ? text.value : '我一个人很孤单，没人陪',
          store_event: true,
        }),
      }));
    } catch (error) { output('emotionOutput', error.message); }
  });

  on('medicalDemo', 'click', async () => {
    try {
      const text = byId('medicalText');
      output('medicalOutput', await api('/v4/medical-reports/analyze', {
        method: 'POST', body: JSON.stringify({
          elder_id: state.elderId, kind: 'checkup_report',
          text: text ? text.value : '', source_name: '全景照护中心演示',
          create_followup_reminder: true,
        }),
      }));
    } catch (error) { output('medicalOutput', error.message); }
  });

  async function ensurePolicy() {
    return api('/v4/safety/policy', {method: 'PUT', body: JSON.stringify({
      elder_id: state.elderId, inactivity_minutes: 720, home_lat: 39.9042,
      home_lon: 116.3974, geofence_radius_m: 1000, notify_community: true,
    })}, 'family');
  }

  async function ping(latitude, longitude) {
    await ensurePolicy();
    return api('/v4/location/ping', {method: 'POST', body: JSON.stringify({
      elder_id: state.elderId, latitude, longitude, accuracy_m: 20,
      occurred_at: new Date().toISOString(), source: 'care_hub_demo',
    })});
  }

  on('locationInside', 'click', async () => {
    try { output('locationOutput', await ping(39.9042, 116.3974)); }
    catch (error) { output('locationOutput', error.message); }
  });

  on('locationOutside', 'click', async () => {
    try { output('locationOutput', await ping(39.95, 116.45)); }
    catch (error) { output('locationOutput', error.message); }
  });

  on('sosDemo', 'click', async () => {
    try {
      await ensurePolicy();
      output('locationOutput', await api('/v4/safety/sos', {
        method: 'POST', body: JSON.stringify({elder_id: state.elderId, include_community: true}),
      }));
    } catch (error) { output('locationOutput', error.message); }
  });

  /* ======================================================================
     演示 · 到期待办推进（原在家人端「其他」里）
     ..........................................................................
     现在还没有后台定时器，提前提醒和超时升级要靠这一步推进。它是运维动作，不是
     一位子女会按的按钮——所以它属于桌面。
     ====================================================================== */

  on('scheduler', 'click', async () => {
    try {
      const data = await api('/v2/demo/scheduler/evaluate', {
        method: 'POST', body: JSON.stringify({now: new Date().toISOString()}),
      }, 'family');
      // 家人端原先只播一句汇总。这里两样都给：一句人话 + 折叠的原始响应，因为这
      // 一页的读者要的正是"它到底回了什么"。
      output('schedulerOutput', data);
      const said = byId('schedulerSaid');
      if (said) {
        said.textContent = `提前提醒 ${data.advance_notified} 条，到期提醒 ${data.notified} 条，`
          + `升级家属 ${data.escalated} 条`;
      }
    } catch (error) { output('schedulerOutput', error.message); }
  });

  bootstrap();
})();
