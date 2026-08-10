'use strict';
/* 全站共用的身份、请求与小工具层。
 *
 * 在这个文件之前，五个页面各写了一份 `api()` / `login()` / `resolveIdentity()`，
 * 而且**已经分叉**：
 *
 *   - 401 自动重登重放：只有 elder 和 family 有；care / trust / judge 没有，
 *     令牌一过期，那三页的按钮就开始静默失败；
 *   - `error.status`：只有 elder 挂了状态码，而 `postChat` 靠它区分 400 去重建
 *     会话——另外四页把状态码丢了；
 *   - 空令牌：trust 无条件写 `Authorization: Bearer `（后面什么都没有），
 *     care 有 `if (token)` 判空；
 *   - 演示身份兜底 `'elder-demo'` 硬编码了四份。
 *
 * 这不是洁癖问题。同一段代码抄五遍，就会有五个版本各自正确、各自不同；`/care` 和
 * `/trust` 那个让两整页全死的 TDZ 笔误，正是这样在两个文件里同时存在的。
 *
 * 刻意写成经典脚本（不是 ES module）：五个页面里有的用 `defer`、有的是
 * `type="module"`、family 干脆裸挂在 </main> 后面。经典脚本在这三种情况下都先执行，
 * 而 `window.YouHuo` 对模块和非模块一样可见。严格 CSP 下无内联、无构建步骤。
 */

(() => {
  //: identity.js 不可用时的兜底家庭，与该文件里的 SHARED 保持一致。
  const FALLBACK = Object.freeze({
    elderId: 'elder-demo', daughterId: 'daughter-demo', sonId: 'son-demo',
    systemId: 'system-demo', familyId: 'fam-demo',
    elderToken: null, familyToken: null, isolated: false,
  });

  //: 角色 -> [identity 里的 actor 字段, identity 里可能已预铸的令牌字段]
  //:
  //: 访客端点在建沙箱时就已经发过令牌了；有就直接用，不要再以一个可能不属于本沙箱
  //: 的固定 actor 重新登录一次。
  const ROLES = {
    elder: ['elderId', 'elderToken'],
    family: ['daughterId', 'familyToken'],
    system: ['systemId', null],
  };

  let identityPromise = null;
  const tokens = new Map();

  /** 本浏览器所属的演示家庭。只解析一次。 */
  function ready() {
    if (!identityPromise) {
      identityPromise = window.YouHuoIdentity
        ? window.YouHuoIdentity.ready().catch(() => FALLBACK)
        : Promise.resolve(FALLBACK);
    }
    return identityPromise;
  }

  function cacheKey(role) {
    return `youhuo_token_${role}`;
  }

  // 一个标签页只换一次身份。换完要重载，而重载之后如果还是 401，那就是服务器
  // 真的有问题——再换一次只会变成刷新循环，把一个"加载失败"变成一个打不开的页面。
  const RENEW_FLAG = 'youhuo_identity_renewed';
  function renewedThisSession() {
    try { return !!sessionStorage.getItem(RENEW_FLAG); } catch (_) { return false; }
  }
  function markRenewed() {
    try { sessionStorage.setItem(RENEW_FLAG, '1'); } catch (_) { /* 隐私模式 */ }
  }

  function cachedToken(role) {
    if (tokens.has(role)) return tokens.get(role);
    const stored = sessionStorage.getItem(cacheKey(role));
    if (stored) tokens.set(role, stored);
    return stored || null;
  }

  function remember(role, token) {
    tokens.set(role, token);
    try { sessionStorage.setItem(cacheKey(role), token); } catch (_) { /* 隐私模式 */ }
  }

  function forget(role) {
    tokens.delete(role);
    try { sessionStorage.removeItem(cacheKey(role)); } catch (_) { /* 隐私模式 */ }
  }

  async function login(role) {
    const spec = ROLES[role];
    if (!spec) throw new Error(`未知身份：${role}`);
    const [actorField, tokenField] = spec;
    const ids = await ready();

    if (tokenField && ids[tokenField]) {
      remember(role, ids[tokenField]);
      return ids[tokenField];
    }
    const response = await fetch('/v2/auth/demo', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({actor_id: ids[actorField]}),
    });
    const data = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(data.detail || `演示登录失败：${role}`);
    remember(role, data.access_token);
    return data.access_token;
  }

  /** 带鉴权的请求。401 自动重登并重放一次；错误对象带 `status`。 */
  async function api(path, options = {}, role = 'elder') {
    const send = async (bearer) => {
      const headers = {...(options.headers || {})};
      // body 在而没写 Content-Type 时补上。少一处调用方要记的事。
      if (options.body && !headers['Content-Type']) {
        headers['Content-Type'] = 'application/json';
      }
      if (bearer) headers.Authorization = `Bearer ${bearer}`;
      return fetch(path, {...options, headers});
    };

    let response = await send(cachedToken(role) || await login(role));
    if (response.status === 401) {
      // 第一次 401：令牌过期了。丢掉重登一次。
      forget(role);
      response = await send(await login(role));
    }
    if (response.status === 401 && window.YouHuoIdentity && window.YouHuoIdentity.renew
        && !renewedThisSession()) {
      // 还是 401：不是令牌过期，是**身份本身**服务器不认了——这个浏览器缓存的
      // 访客家庭是在换掉之前的那一个库里开通的。换个身份再来一次，只来这一次。
      //
      // 不加这一步，任何一次重新部署或重置演示数据，都会把每一个回访的人永久挡在
      // 门外：`identityPromise` 和 identity.js 的 `pending` 都是记忆化的，同一次
      // 加载里再问也还是那个死身份，刷新多少次都一样。写好的 `reset()` 从来没有
      // 人调用过。
      markRenewed();
      forget(role);
      identityPromise = null;
      await window.YouHuoIdentity.renew();
      // 整页重来，不是只换个令牌接着跑。
      //
      // 每个页面在加载时就从身份里取走了一批常量——`ELDER_ID`、`FAMILY_ID`、
      // 各处拼好的 URL。换身份只换令牌的话，那些常量还指着上一个家庭，请求能
      // 通过鉴权却拿不到东西："老人账户不属于当前家庭"。实测就是这样。
      // 这条路径一个浏览器一辈子最多走一次，重载是最省事也最不会漏的做法。
      location.reload();
      await new Promise(() => {});   // 重载途中别让调用方继续往下跑
    }
    const data = await response.json().catch(() => ({}));
    if (!response.ok) {
      const error = new Error(data.detail || `请求失败（${response.status}）`);
      error.status = response.status;
      throw error;
    }
    return data;
  }

  const byId = (id) => document.getElementById(id);
  const pretty = (value) => JSON.stringify(value, null, 2);

  //: 五个判定词在老人端、家属端和照护端各写过一份，键相同、文案有分叉。
  //:
  //: `pending` 与 `unknown` 不是一回事，这个区别是这个功能的要害：pending 是
  //: "今天还没过完"，unknown 是"本该有记录却一条都没有"。后者在养老场景里必须被
  //: 看见，所以给它警示色；前者是中性的。合并成一份，免得哪天只改了其中一处。
  const VERDICT = Object.freeze({
    typical: ['和平常一样', 'good'],
    notice: ['有一点不同', 'warn'],
    marked: ['和平常不太一样', 'bad'],
    unknown: ['还没有记录', 'warn'],
    pending: ['还不好说', ''],
  });

  function verdictOf(name) {
    return VERDICT[name] || VERDICT.unknown;
  }

  /** 当前令牌，没有就返回 null。给需要自己拼请求的地方用（例如离线语音的音频流）。 */
  function token(role = 'elder') {
    return cachedToken(role);
  }

  // --- 结果渲染 ------------------------------------------------------------
  //
  // 可信实验室六张卡的输出曾经**全是** `<pre>` 里的原始 JSON，照护中心七张里有六张
  // 也是。评委点开按钮，看到的是一屏 `{"decision": "clarify", "stripped_fields": [...]}`。
  // 那些字段本身就是这个项目最想讲的东西——"系统拒绝了什么、为什么拒绝"——但用
  // JSON 讲出来，等于要求评委现场读一遍后端契约。
  //
  // 原始 JSON 不删，收进可展开区：证据要留着，只是不该是第一眼看到的东西。

  //: 后端字段名 -> 中文标签。查不到就原样显示键名——宁可露出 `foo_bar`，也不要
  //: 悄悄把一个没预料到的字段藏起来。
  const FIELD_LABEL = {
    decision: '判定', reasons: '理由', stripped_fields: '被剥离的字段',
    status: '状态', message: '说明', semantic_intent: '语义意图',
    intent: '意图', mode: '交互模式', headline: '结论',
    task_id: '任务号', risk_level: '风险等级', requires_family_approval: '需家属确认',
    requires_elder_confirmation: '需老人复述确认', reversible: '可撤销',
    approved: '已批准', verdict: '判定', overall: '总体判定',
    speak_text: '播报', visible_options: '本轮可见选项', require_teach_back: '需要复述确认',
    name: '名称', purpose: '用途', authorization: '授权决定',
    candidates: '候选', confidence: '置信度', engine: '识别引擎',
    advance_notified: '提前提醒', notified: '到期提醒', escalated: '升级家属',
    inside_home_area: '在安全范围内', alert_created: '已产生告警',
    family_notified: '已通知家属', community_escalation_prepared: '已准备社区升级',
    steps: '步骤', current_step_index: '当前步骤', version: '版本',
    implemented_and_tested: '已实现并测试', not_implemented: '尚未实现',
    privacy_guarantee: '隐私承诺', privacy_note: '隐私说明',
    allowed_arguments: '允许通过的参数', required_confirmations: '还需要什么',
    policy_version: '策略版本', decision_digest: '决定摘要', purpose_bound: '目的绑定',
    elder_id: '老人', bill_id: '账单号', amount_cents: '金额（分）',
    expires_at: '有效期至', scopes: '授权范围', granted: '已授权',
    conflict: '冲突', resolution: '处理方式', winner: '采用',
  };

  //: 值本身就是结论的字段，用色块显示而不是一行小字。
  const TONE_BY_VALUE = {
    allow: 'good', clarify: 'warn', deny: 'bad', blocked: 'bad',
    ok: 'good', success: 'good', failed: 'bad', error: 'bad',
    typical: 'good', notice: 'warn', marked: 'bad', unknown: 'warn', pending: '',
  };

  function labelFor(key) {
    return FIELD_LABEL[key] || key;
  }

  function scalarText(value) {
    if (value === null || value === undefined) return '—';
    if (typeof value === 'boolean') return value ? '是' : '否';
    return String(value);
  }

  function valueNode(value) {
    if (Array.isArray(value)) {
      if (!value.length) return document.createTextNode('（无）');
      if (value.every((item) => item === null || typeof item !== 'object')) {
        const list = document.createElement('ul');
        list.className = 'result-list';
        value.forEach((item) => {
          const li = document.createElement('li');
          li.textContent = scalarText(item);
          list.appendChild(li);
        });
        return list;
      }
      const wrap = document.createElement('div');
      value.forEach((item) => wrap.appendChild(objectNode(item)));
      return wrap;
    }
    if (value && typeof value === 'object') return objectNode(value);

    const tone = TONE_BY_VALUE[String(value)];
    if (tone !== undefined) {
      const pill = document.createElement('span');
      pill.className = `pill ${tone}`;
      pill.textContent = scalarText(value);
      return pill;
    }
    return document.createTextNode(scalarText(value));
  }

  function objectNode(value) {
    const box = document.createElement('div');
    box.className = 'result-group';
    Object.entries(value).forEach(([key, item]) => {
      const row = document.createElement('div');
      row.className = 'result-row';
      const label = document.createElement('strong');
      label.textContent = labelFor(key);
      const cell = document.createElement('div');
      cell.appendChild(valueNode(item));
      row.append(label, cell);
      box.appendChild(row);
    });
    return box;
  }

  /** 把一个响应渲染进容器：先结构化，再折叠一份原始 JSON。 */
  function renderResult(host, value) {
    const el = typeof host === 'string' ? byId(host) : host;
    if (!el) return;
    el.replaceChildren();
    if (typeof value === 'string') {
      el.textContent = value;
      return;
    }
    el.appendChild(valueNode(value));

    const raw = document.createElement('details');
    raw.className = 'result-raw';
    const summary = document.createElement('summary');
    summary.textContent = '原始响应';
    const body = document.createElement('pre');
    body.textContent = pretty(value);
    raw.append(summary, body);
    el.appendChild(raw);
  }

  window.YouHuo = {
    ready, login, api, forget, token,
    byId, pretty, VERDICT, verdictOf, renderResult,
  };
})();
