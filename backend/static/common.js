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

  //: 角色 -> 说给人听的说法。`login()` 抛出的 Error 会被各页 catch 之后原样写到
  //: 屏幕上（老人端还会念出来），所以那条消息里不能出现 'elder' / 'family'。
  const ROLE_WORD = {elder: '您这边', family: '家人那边', system: '系统'};

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

  // 这个标签页打开过内页了。首页据此判断"冷启动 vs 会话内返回"。
  //
  // 判据原先是 `document.referrer`，而站点自己下发 `Referrer-Policy: no-referrer`，
  // referrer 恒为空——"冷启动"恒为真，于是每一个「返回首页」都会被立刻弹回去。
  // 这一行是那条判据的真正来源；`landing.js` 读它。
  try { sessionStorage.setItem('youhuo_visited_v1', '1'); } catch (_) { /* 隐私模式 */ }

  function cachedToken(role) {
    if (tokens.has(role)) return tokens.get(role);
    // 这一行原先没有 try/catch，是本文件里唯一裸调的存储访问。
    // 存储被禁时（Chrome"阻止所有网站数据"、无 allow-same-origin 的 sandbox iframe）
    // 它在第一次请求就抛 SecurityError，五个页面全部停在"初始化失败"——而
    // identity.js 本来写好了退回共享演示家庭的降级路径，被这一行绕过。
    let stored = null;
    try { stored = sessionStorage.getItem(cacheKey(role)); } catch (_) { /* 隐私模式 */ }
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
    if (!spec) {
      // 原样抛 `未知身份：${role}` 会把内部枚举写到屏幕上。这是一条纯粹的编码错误
      // 路径（调用方传了 ROLES 里没有的角色），排查需要的原值进 console，
      // 给人看的那句不带它。
      console.error('login() 收到未知角色：', role);
      throw new Error('这一侧的身份认不出来');
    }
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
    // 这一句会走到屏幕上。elder.js 的 catch 是 `addBubble(\`系统暂时不可用：${e.message}\`)`，
    // 所以老人当时读到（并被念出来）的整句是「系统暂时不可用：演示登录失败：elder」——
    // 一个工程词加一个英文枚举，而这两样都是这个项目的硬约束明令禁止的。
    // `role` 是 'elder' | 'family'，直接拼进文案就是把内部枚举念给她听。
    if (!response.ok) throw new Error(data.detail || `${ROLE_WORD[role] || '这一侧'}没能登录`);
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
    // `unknown` 从 `warn` 换成它自己的 `unknown` 色调。
    //
    // 上面那段话说的没错：本该有记录却一条都没有，在养老场景里必须被看见。所以它
    // **不能**降成中性。但它和 `notice` 共用琥珀之后，照护页那一屏上会出现三个字样
    // 完全相同的琥珀块，而三段里只有一段真的偏离——"我们不知道"被画成了"出事了"。
    //
    // 一位子女扫一眼看到三块琥珀，得到的结论是"今天有三件事不对"，而事实是
    // "有两件事我们没数据"。第三种色调把这两件事分开：琥珀从此只表示"和他平常不一样"，
    // 而"还没有记录"用一个看得见、但不喊的处理。
    unknown: ['还没有记录', 'unknown'],
    pending: ['还不好说', ''],
  });

  function verdictOf(name) {
    // 自有属性才算命中。`VERDICT['constructor']` 会返回 `Object`（真值），于是调用方
    // 的 `const [word, tone] = verdictOf(...)` 抛 "is not iterable"，而不是老老实实
    // 落到 `VERDICT.unknown`。
    return (Object.prototype.hasOwnProperty.call(VERDICT, name) && VERDICT[name])
      || VERDICT.unknown;
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
  //
  // 这张表被**四个 app 页面全部加载**，所以它的措辞在手机框里面。
  // 五条原先是照后端字段名直译的（「语义意图」「被剥离的字段」「允许通过的参数」
  // 「置信度」「识别引擎」），已改成说值是什么、而不是说字段叫什么。
  // 评委那一侧一个字节都没少：原始键名照旧在同一张卡下面的「完整记录」里逐字保留，
  // 这张表只决定结构化卡片上那一行怎么念。
  const FIELD_LABEL = {
    decision: '判定', reasons: '理由', stripped_fields: '被去掉的内容',
    status: '状态', message: '说明', semantic_intent: '听出来要办什么',
    intent: '意图', mode: '交互模式', headline: '结论',
    task_id: '任务号', risk_level: '风险等级', requires_family_approval: '需家属确认',
    requires_elder_confirmation: '需老人复述确认', reversible: '可撤销',
    approved: '已批准', verdict: '判定', overall: '总体判定',
    speak_text: '播报', visible_options: '本轮可见选项', require_teach_back: '需要复述确认',
    name: '名称', purpose: '用途', authorization: '授权决定',
    candidates: '候选', confidence: '有多确定', engine: '用哪个来识别',
    advance_notified: '提前提醒', notified: '到期提醒', escalated: '升级家属',
    inside_home_area: '在安全范围内', alert_created: '已产生告警',
    family_notified: '已通知家属', community_escalation_prepared: '已准备社区升级',
    steps: '步骤', current_step_index: '当前步骤', version: '版本',
    implemented_and_tested: '已做好并核验', not_implemented: '尚未实现',
    privacy_guarantee: '隐私承诺', privacy_note: '隐私说明',
    allowed_arguments: '允许通过的内容', required_confirmations: '还需要什么',
    policy_version: '策略版本', decision_digest: '决定摘要', purpose_bound: '目的绑定',
    elder_id: '老人', bill_id: '账单号', amount_cents: '金额（分）',
    expires_at: '有效期至', scopes: '授权范围', granted: '已授权',
    conflict: '冲突', resolution: '处理方式', winner: '采用',
  };

  //: 值本身就是结论的字段，用色块显示而不是一行小字。
  const TONE_BY_VALUE = {
    allow: 'good', clarify: 'warn', deny: 'bad', blocked: 'bad',
    ok: 'good', success: 'good', failed: 'bad', error: 'bad',
    typical: 'good', notice: 'warn', marked: 'bad', unknown: 'unknown', pending: '',
  };

  function labelFor(key) {
    // 自有属性才算命中。否则 `__proto__` 这个键名会取到 `Object.prototype`，
    // 标签渲染成 `[object Object]`——而这一层的契约恰恰是"查不到就原样露出键名"。
    return (Object.prototype.hasOwnProperty.call(FIELD_LABEL, key) && FIELD_LABEL[key]) || key;
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
      // 递归回 valueNode，而不是对每个元素无条件调 objectNode。
      //
      // 上一句"是否全是标量"是对**整个数组**做的一次判定，混合数组因此掉到这里，
      // 然后每个元素——包括 null、字符串、嵌套数组——都被当成对象喂给
      // `Object.entries`。实测三种结果：null 抛 TypeError 而 renderResult 已经先
      // replaceChildren() 了，那张卡片就此永久空白；字符串被逐字拆成一行一个字，
      // 标签是 0/1/2…；数组套数组渲染成下标键行。入口是敞开的——
      // `SyncConflictRecord.current_value/incoming_value` 是 `Any`。
      value.forEach((item) => wrap.appendChild(valueNode(item)));
      return wrap;
    }
    if (value && typeof value === 'object') return objectNode(value);

    // `Object.prototype` 的成员不算命中。
    //
    // 方括号取值会把原型链算进来：取值恰好等于 `constructor` / `toString` /
    // `valueOf` 时 `tone !== undefined` 为真，于是一个普通文本被渲染成判定色块，
    // className 还被拆成 `pill function Object() { [native code] }` 这样六个垃圾类名。
    // 实测如此。`Object.freeze` 只冻结自有属性，挡不住这一层。
    const tone = Object.prototype.hasOwnProperty.call(TONE_BY_VALUE, String(value))
      ? TONE_BY_VALUE[String(value)] : undefined;
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
    const entries = Object.entries(value);
    // 空对象要说自己是空的。
    //
    // 原先渲染出一个空的 `.result-group`——字段名下面什么都没有。可信页点「创建
    // Saga」必然撞上：六个步骤各有 `input_data` 和 `output_data` 两个 `{}`，
    // 于是十二行标签下面是十二块空白。空数组有「（无）」，空对象什么也没有。
    if (!entries.length) {
      box.appendChild(document.createTextNode('（无）'));
      return box;
    }
    entries.forEach(([key, item]) => {
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
    // 「原始响应」是说给写接口的人听的。这个 `<details>` 在 /care 和 /trust 上也渲染，
    // 那是手机框**里**。内容一个字节都不动——只是标题改成人话。证据要留着（不得
    // silent delete），但它的名字不该要求读者先懂 HTTP。
    summary.textContent = '完整记录';
    const body = document.createElement('pre');
    body.textContent = pretty(value);
    raw.append(summary, body);
    el.appendChild(raw);
  }

  // --- 飞行中禁用 ------------------------------------------------------------
  //
  // 全站**没有任何一个按钮**在自己那次请求飞行期间被禁用过。手机上 300ms 内的连点是
  // 常态而不是边缘情况，而这些按钮背后是不可逆的东西：
  //
  //   * 家人端「核对后确认接力」——两次点击各带一个新的 `crypto.randomUUID()`，
  //     后端按 (scope, request_id, fingerprint) 去重，UUID 不同就是两次独立审批。
  //     第二次返回 200 + "这位家属已经确认过本次任务，请等待其他家属…"，而界面显示的
  //     是**后返回的那一个** —— 家属在一次已经批准并执行完的付款上，看到"还在等其他人"。
  //   * 可信页「开启10分钟最小访问」（破窗）——两条独立授权、两个各自 10 分钟的窗口，
  //     界面只显示后一条，第一条仍然生效且**没有任何入口能看到或撤销**。
  //   * 照护页「模拟老人主动呼救」——两条 SOS 告警、两次家属通知、两次社区升级准备。
  //
  // 这个项目自己的运行时闸门结构上测不出这一类：它对每个控件只按一次，还会跳过
  // `disabled` 的按钮。所以补了 `check_double_click`，那边真的连点两次数请求。
  async function once(trigger, run) {
    const el = typeof trigger === 'string' ? document.querySelector(trigger) : trigger;
    if (!el) return run();
    if (el.dataset.inFlight === '1') return undefined;
    el.dataset.inFlight = '1';
    el.disabled = true;
    el.setAttribute('aria-busy', 'true');
    try {
      return await run();
    } finally {
      delete el.dataset.inFlight;
      el.disabled = false;
      el.removeAttribute('aria-busy');
    }
  }

  //: HTTP 200 不等于"办成了"。
  //:
  //: 后端对业务失败的约定是 200 + `code` + `ui.theme`：任务已被别人处理、家属未批准
  //: 因此安全取消、同一时间的同一提醒已存在——全是 200。调用方只取 `message` 的话，
  //: 一次取消会显示成一个绿色的成功框，而用户无法把它和真的成功区分开。
  const THEME_TONE = {warning: 'warning', warn: 'warning', danger: 'bad', error: 'bad'};
  function toneOf(data) {
    const theme = ((data || {}).ui || {}).theme;
    if (theme && THEME_TONE[theme]) return THEME_TONE[theme];
    const code = (data || {}).code;
    if (code && code !== 'OK' && code !== 'SUCCESS') return 'warning';
    return 'good';
  }

  //: 平台抛的错，和后端写的错，不是一回事。
  //:
  //: 这个文件第 41 行已经记着一条事实：`login()` 抛的 Error「会被各页 catch 之后
  //: 原样写到屏幕上（老人端还会念出来）」。当时的对策是把**我们自己撰写**的那些
  //: 消息洗干净。但错误有两个来源，只治了一个：
  //:
  //:   后端写的   `api()` 对 HTTP 失败抛 `new Error(data.detail || …)` 并带 `.status`。
  //:             `detail` 是后端用中文写给人看的，直接上屏没问题。
  //:   平台抛的   `fetch` 自己失败时抛 `TypeError: Failed to fetch`，**没有 `.status`**。
  //:             源头在浏览器里，洗不掉。而它会被写进状态行，然后**被念给老人听**。
  //:
  //: 实测有 7 处把 `${e.message}` 直接拼进消费者面的文案：`elder.js` 三处
  //: （`:759` `:863` `:894`）、`care.js:461`、`trust.js:21`（连前缀都没有）、
  //: `family.js` 两处（`:428` `:632`）。
  //:
  //: `test_app_surface_speaks_no_engineering.py` 扫的是**静态字面量**，而
  //: `${e.message}` 是个模板——它运行时装进来什么，静态扫描无从得知。所以
  //: 「消费者面不许有工程词」这条规则在运行时是没有闸门的，这个函数就是那道闸门
  //: 的落点：只要所有 catch 都经过它，运行时也就守住了。
  //:
  //: 四型各配**一条仍然走得通的路**。一个错误提示最要紧的不是解释原因，是给出路——
  //: 老人看不懂「加载失败」，但看得懂「家里网不通」，更要紧的是知道接下来能干什么。
  const ERROR_WORDS = {
    offline: {say: '家里网不通', then: '等一下我再试试'},
    notfound: {say: '没有找到这一条', then: '回到记录看看'},
    server: {say: '我这边出了点问题', then: '过一会儿再试'},
    unknown: {say: '这一步没成', then: '再试一次'},
  };

  /** 错误 → 四型之一，或 `backend`（后端写好了人话，用它自己的）。 */
  function errorKind(error) {
    const status = error && error.status;
    if (typeof status === 'number') {
      if (status === 404) return 'notfound';
      if (status >= 500) return 'server';
      return 'backend';
    }
    // 浏览器自己知道没网的时候，那是比异常形状更硬的信号：一个 TypeError 也可能
    // 是别的原因，而 `onLine === false` 是确定的。
    //
    // `elder.js` 的 send() 里本来就有 `navigator.onLine === false ? 'offline'`
    // 这一行，用来决定屏幕停在哪一态——但同一处的**文案**却写死成
    // 「系统暂时不可用」，也就是说这个判断已经做过一次，只是没用在说给人听的那句话上。
    if (typeof navigator !== 'undefined' && navigator.onLine === false) {
      return 'offline';
    }
    // `fetch` 失败在所有主流浏览器里都是 TypeError；超时被 AbortController 掐断
    // 时是 AbortError。两者对用户是同一件事：这一趟没出去。
    const name = (error && error.name) || '';
    if (name === 'TypeError' || name === 'AbortError') return 'offline';
    return 'unknown';
  }

  /** 给人看的一句话。
   *
   * @param error   catch 到的那个东西
   * @param subject 这次没成的是哪件事（「待办」「记录」「这份凭证」），可省
   * @returns `{kind, say, then, text}`——`text` 是拼好的默认说法，
   *          `say` / `then` 给需要自己拼的地方（比如状态行只容得下一句）。
   */
  function errorWords(error, subject) {
    const kind = errorKind(error);
    if (kind === 'backend') {
      const detail = String((error && error.message) || '').trim();
      // 兜底文案是 `请求失败（403）`，里面有状态码——那是工程词，不给消费者看。
      if (detail && !/请求失败（\d+）/.test(detail)) {
        return {kind, say: detail, then: '', text: detail};
      }
      const w = ERROR_WORDS.unknown;
      return {kind: 'unknown', say: w.say, then: w.then,
              text: subject ? `${subject}${w.say}。${w.then}` : `${w.say}。${w.then}`};
    }
    const w = ERROR_WORDS[kind];
    return {
      kind, say: w.say, then: w.then,
      text: subject ? `${subject}暂时看不了：${w.say}。${w.then}`
                    : `${w.say}。${w.then}`,
    };
  }

  //: 跨文档回到原处。
  //:
  //: `/family` `/care` `/trust` 是同一个 App 的三个 deep link，但它们是三个**文档**。
  //: 每次跳转都是一次完整的文档加载：JS 上下文重建、滚动归零。实测：在 /family
  //: 滚到 y=204，去 /care，回来 y=0。
  //:
  //: 这一条是 Phase C/D 的前置判据之一（`09_consumer_app_architecture.md`）。
  //: Medito 靠 `IndexedStack` 让四个 tab 页同时活着，切走再切回什么都没变；
  //: 七个文档做不到那个，只能把「回到原处」这件事显式地做出来。做法本身也照它抄——
  //: `bottom_navigation_bar_view.dart:39-41` 把上次的 tab 存进 SharedPreferences
  //: 并在启动时恢复。
  //:
  //: **难点不在存，在恢复的时机。** 这三页的内容是异步取的，`load` 那一刻文档还
  //: 只有一屏高，此时 `scrollTo(0, 204)` 会被浏览器夹到 0——朴素实现就死在这里，
  //: 而且它失败得很安静（看起来就是"没恢复"，和没写这段代码一样）。所以要等到
  //: 文档真的够高了再滚，并且有个上限，不能无限等一个永远不会长高的页面。
  const PLACE_KEY = 'youhuo_place_v1';
  const PLACE_TTL_MS = 30 * 60 * 1000;   // 半小时之前的位置就不要了
  const RESTORE_WINDOW_MS = 2500;        // 最多等内容 2.5 秒

  //: 按**路径**分槽，不是一个槽。
  //:
  //: 第一版是单槽（`{path, y}` 一份），实测不恢复。原因是中间那一页把它覆盖了：
  //: 离开 /family 存 `{path:'/family', y:204}`，离开 /care 又存
  //: `{path:'/care', y:0}` 盖掉它——回到 /family 时读出来的 path 是 /care，
  //: 不匹配，于是什么都不做。
  //:
  //: 而这正是这个功能唯一的使用场景：**A → B → A**。单槽在它自己要解决的那条
  //: 路径上必然失效，而且失效得毫无声音（看起来就是"没恢复"）。
  function readPlaces() {
    try {
      const raw = JSON.parse(sessionStorage.getItem(PLACE_KEY) || '{}');
      return (raw && typeof raw === 'object' && !Array.isArray(raw)) ? raw : {};
    } catch (_) { return {}; }
  }

  function rememberPlace() {
    try {
      const places = readPlaces();
      places[location.pathname] = {
        hash: location.hash,
        y: Math.round(window.scrollY || 0),
        t: Date.now(),
      };
      // 只留最近的几页，别让它无限长。七条路由，留八个够了。
      const keys = Object.keys(places)
        .sort((a, b) => (places[b].t || 0) - (places[a].t || 0))
        .slice(8);
      keys.forEach(k => delete places[k]);
      sessionStorage.setItem(PLACE_KEY, JSON.stringify(places));
    } catch (_) { /* 隐私模式 */ }
  }

  function restorePlace() {
    const saved = readPlaces()[location.pathname];
    if (!saved || !saved.y || Date.now() - saved.t > PLACE_TTL_MS) return;

    // 浏览器自己的滚动恢复只在前进/后退时生效；点一条 tab 链接是**全新导航**，
    // 它不管。关掉它是为了两边不互相打架。
    try { history.scrollRestoration = 'manual'; } catch (_) { /* 老浏览器 */ }

    const target = saved.y;
    const deadline = Date.now() + RESTORE_WINDOW_MS;
    let settled = false;

    const tryScroll = () => {
      if (settled) return;
      const reachable = document.documentElement.scrollHeight - window.innerHeight;
      if (reachable >= target) {
        window.scrollTo(0, target);
        // 真的到了才算完。夹住的时候不算——留着下一帧再试。
        if (Math.abs((window.scrollY || 0) - target) <= 2) {
          settled = true;
          observer?.disconnect();
          return;
        }
      }
      if (Date.now() > deadline) {
        // 等不到就放弃，**不要**滚到一个半途的位置：停在顶部是可理解的，
        // 停在内容中间一个不属于任何东西的地方不是。
        settled = true;
        observer?.disconnect();
        return;
      }
      requestAnimationFrame(tryScroll);
    };

    // 内容是异步长出来的，所以既监听尺寸变化也逐帧重试：
    // ResizeObserver 抓「一次性长高一大块」，rAF 抓「一点一点长」。
    let observer = null;
    if (typeof ResizeObserver === 'function') {
      observer = new ResizeObserver(tryScroll);
      observer.observe(document.documentElement);
    }
    requestAnimationFrame(tryScroll);
  }

  // `pagehide` 而不是 `beforeunload`：后者在移动端浏览器里经常不触发，而且它会
  // 让页面失去进入后退/前进缓存的资格。`visibilitychange` 补 iOS 那一路——
  // 用户直接切走 App 时只会有这一个事件。
  addEventListener('pagehide', rememberPlace);
  addEventListener('visibilitychange', () => {
    if (document.visibilityState === 'hidden') rememberPlace();
  });

  // 这个文件按注释是**经典脚本、在 `<head>` 里执行**，所以此刻 `<body>` 还不存在，
  // `document.documentElement.scrollHeight` 量出来没有意义。等 DOM 就绪再开始。
  //
  // 「定义了但没人调」是这个项目反复出现的失效方式，而它和「功能正常但没数据」
  // 在屏幕上一模一样——同一个会话里 `loadActivity()` 和 `renderKin()` 各踩过一次。
  // 所以这一行不能省，而且下面那道闸门会核对它真的存在。
  if (document.readyState === 'loading') {
    addEventListener('DOMContentLoaded', restorePlace, {once: true});
  } else {
    restorePlace();
  }

  // --- 页内分区 --------------------------------------------------------------
  //
  // 一页装了太多东西的时候，答案是把它切成几段、一次只显示一段，而不是加一个路由。
  // 不加路由是有意的：六条路由、service worker 的外壳清单、manifest 的 start_url
  // 全都不用动，切换也没有网络往返——这个应用要在地铁上能翻。
  //
  // 放在 common.js 而不是各页自己写一份：家人端和照护页用的是同一套 DOM 约定
  // （`.seg[data-section]` 配 `[data-panel]`），而 `check_page_runtime` 的点击遍历
  // 认的也是 `.seg` 这个类——它靠这个类知道"这个按钮会换掉整屏，留到最后再按"。
  // 第二个页面另起一套类名，那道规则就会漏掉它，而检查照样报绿。
  function initSections(fallback) {
    const segs = [...document.querySelectorAll('.seg')];
    const panels = [...document.querySelectorAll('[data-panel]')];
    if (!segs.length || !panels.length) return;
    const first = fallback || panels[0].dataset.panel;

    /** hash → 该显示哪个分区。
     *
     * hash 可以是分区名，**也可以是某个分区里面一个元素的 id**。桌面舞台上那四条
     * 底线的「→」就是后一种：它们指向具体那篇证明它的卡片，而不是整段分区。
     *
     * 原先只认分区名，别的一律退回第一段——于是点一条底线的效果是"跳回产品介绍"，
     * 而且不报错、不在截图里露馅。这一页整个论点就是"每一条都能当场验证"。
     */
    function resolve(name) {
      if (panels.some(p => p.dataset.panel === name)) return name;
      const node = name && document.getElementById(name);
      const host = node && node.closest('[data-panel]');
      return host ? host.dataset.panel : first;
    }

    function show(name, writeHash) {
      const target = resolve(name);
      panels.forEach(p => { p.hidden = p.dataset.panel !== target; });
      segs.forEach(s => {
        const on = s.dataset.section === target;
        s.classList.toggle('is-current', on);
        if (on) s.setAttribute('aria-current', 'true'); else s.removeAttribute('aria-current');
      });
      if (writeHash) history.replaceState(null, '', `#${target}`);
    }

    segs.forEach(s => s.addEventListener('click', () => show(s.dataset.section, true)));
    // 当前分区写进 hash：刷新之后还在原地，从一条通知点回来也不会被扔回第一屏。
    window.addEventListener('hashchange', () => show(location.hash.slice(1), false));
    show(location.hash.slice(1) || first, false);
  }

  window.YouHuo = {
    ready, login, api, forget, token,
    byId, pretty, VERDICT, verdictOf, renderResult, initSections, once, toneOf,
    errorKind, errorWords,
  };
})();
