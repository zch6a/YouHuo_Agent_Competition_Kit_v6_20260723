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
      // 只重放一次。重放本身再 401，就是真的没权限，不该转圈。
      forget(role);
      response = await send(await login(role));
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

  window.YouHuo = {ready, login, api, forget, token, byId, pretty, VERDICT, verdictOf};
})();
