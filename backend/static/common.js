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
    /* 语气由后端的 `code` 给，不是一律画绿。
     *
     * 这一处原先是 `code !== 'OK' && code !== 'SUCCESS'`——**两个比较都恒为真**：
     * `ResponseCode` 的取值是小写的（`models.py:60`：`ok` / `task_completed` /
     * `need_more_info` / `duplicate_blocked` / `safety_alert` / `error` …），
     * 而这里比的是大写 `'OK'`；`'SUCCESS'` 根本不在那个枚举里。
     * 于是**凡是带 `code` 的响应都落到 warning**，连 `code: "ok"` 也是。
     *
     * 实测（`/family3` 按「＋」真建一条提醒）：后端 `code = "task_completed"`，
     * 屏幕上「已经设置提醒：…」配的是**琥珀色警告条**。一次成功的写操作
     * 看起来像出了点事。影响这一层的全部 26 处调用：`/care`、`/family`、
     * `/family2`、`/family3`、`/elder3`、任务详情页。
     *
     * 这张表**留在函数内部**：`test_the_screen_is_new_after_the_write.py:356`
     * 把 `THEME_TONE` 和这个函数分别抠出来 `new Function` 起来跑，
     * 放外面的常量在那个 eval 里是 ReferenceError（`THEME_TONE` 它抠了，
     * 所以那一个留在外面不动）。
     */
    const CODE_TONE = {
      //: 办成了 / 只是在说话——绿色。
      ok: 'good',
      task_completed: 'good',
      chat: 'good',
      mode_switched: 'good',
      //: 还缺一步，要人接着做——琥珀。
      need_more_info: 'warning',
      need_elder_confirmation: 'warning',
      need_family_approval: 'warning',
      duplicate_blocked: 'warning',
      task_cancelled: 'warning',
      //: 出事了 / 报错——红。
      safety_alert: 'bad',
      error: 'bad',
    };
    const theme = ((data || {}).ui || {}).theme;
    if (theme && THEME_TONE[theme]) return THEME_TONE[theme];
    const code = (data || {}).code;
    if (!code) return 'good';
    //: 认不出来的 code 按 warning——和这一处原来的保守取向一致：
    //: 宁可让一次成功看起来像「要留意一下」，也不要让一次没办成看起来像办成了。
    return CODE_TONE[String(code).toLowerCase()] || 'warning';
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
      const apply = () => {
        panels.forEach(p => { p.hidden = p.dataset.panel !== target; });
        segs.forEach(s => {
          const on = s.dataset.section === target;
          s.classList.toggle('is-current', on);
          if (on) s.setAttribute('aria-current', 'true'); else s.removeAttribute('aria-current');
        });
      };

      //: 换分区要**看起来像翻了一页**，而不是原地闪一下。
      //:
      //: 这里原先只是 `p.hidden = …`：DOM 换了，屏幕上瞬间替换，没有任何位移或
      //: 淡入。人眼不把"瞬间替换"读成导航，只读成"这一堆东西本来就在那儿"——
      //: 于是一个真的在切页的应用，看起来像一张什么都堆着的长页面。
      //:
      //: 用 View Transitions：动画跑在合成器上、零依赖、不需要打包步骤，也不违反
      //: 严格 CSP（它是 CSS + 一个 DOM API，没有内联样式和脚本）。
      //: 标签栏和页头在 CSS 里各自领了 `view-transition-name`，所以它们**不参与**
      //: 这次淡入淡出——真机上切标签时，底下那条栏是不动的，动的只有内容。
      //:
      //: 两道退让：浏览器不支持时照常直接换；用户开了「减少动态效果」时也直接换
      //: （`check_page_runtime` 正是用 `prefers-reduced-motion: reduce` 在量这一页，
      //: 它必须量到最终状态，而不是过渡中间的某一帧）。
      const instant = !document.startViewTransition
        || document.documentElement.classList.contains('app4-embedded')
        || window.matchMedia('(prefers-reduced-motion: reduce)').matches;
      if (instant) {
        apply();
      } else {
        //: 转场的 `ready` / `finished` 是 Promise，**被打断时会拒绝**。
        //:
        //: 连着点两个分区，后一次会中止前一次；页面被隐藏也会中止
        //: （`InvalidStateError: Transition was aborted because of invalid state`）。
        //: 没人接这个拒绝，它就是一条未捕获异常——`check_page_runtime` 的「无异常」
        //: 当场判红，而这一条在答辩现场就是控制台里一串红字。
        //:
        //: 中止对我们不是错误：`apply()` 照常执行，DOM 该换的还是换了，
        //: 只是没播完那 200ms。所以这里明确把拒绝吃掉，而不是让它冒泡。
        const t = document.startViewTransition(apply);
        if (t) {
          for (const p of [t.ready, t.finished, t.updateCallbackDone]) {
            if (p && typeof p.catch === 'function') p.catch(() => {});
          }
        }
      }

      if (writeHash) history.replaceState(null, '', `#${target}`);
    }

    segs.forEach(s => s.addEventListener('click', () => show(s.dataset.section, true)));
    // 当前分区写进 hash：刷新之后还在原地，从一条通知点回来也不会被扔回第一屏。
    window.addEventListener('hashchange', () => show(location.hash.slice(1), false));
    show(location.hash.slice(1) || first, false);
  }

  /* ==========================================================================
     任务词汇：一处定义，四个地方用
     ..........................................................................
     这三张表原先在 `elder.js`、`task-space.js`、`task-detail.js`、`trust.js` 里
     各有一份，而那三处的注释各自写着「这是第三份 / 第四份，要在 Phase C 收敛」。
     收敛的理由不是整洁，是**它们已经漂了**：

         后端 TaskType（models.py）  hospital_registration / bill_payment
                                     / reminder / form_assistance
         三份前端表里写的             appointment / bill_payment / medication

     `appointment` 和 `medication` **不是后端的值**（`engine.py:769` 放进聊天响应
     `data.task_type` 的就是 `TaskType` 枚举本身），所以那两个键永远命中不了；
     而三个真实类型里有三个不在表里。实测后果：一件挂号任务在老人端的状态行是
     「正在办**这件事**」而不是「正在办：**挂号**」——表声称它处理挂号，靠的是
     一个不会触发的键。

     没有英文泄漏（兜底都是中文），所以它躲过了「界面不许出现枚举值」那道闸门。
     这类分叉这个项目栽过一次：`family.js` 的 `EMOTION_LABEL` 缺三个值、多三个
     后端没有的值，把最要紧的 `urgent` 印成了英文。

     放在 `common.js` 而不是新开一个模块：四个调用点里 `trust.js` / `task-space.js`
     是普通脚本、不是 ES module，改成 module 会牵动 SW SHELL 与 CSP；而 common.js
     每一页都加载、本来就是共享词汇层（`verdictOf`、`toneOf`、`errorWords` 都在这里）。

     `test_task_words_cover_the_real_enums.py` 拿 `models.py` 核对这三张表，
     并禁止任何页面再私藏一份。
     ========================================================================== */

  //: 任务类型 → 给人看的名字。键必须是 `TaskType` 的值。
  const TASK_WORD = {
    bill_payment: '缴费',
    hospital_registration: '挂号',
    reminder: '提醒',
    form_assistance: '帮您填表',
  };

  /* ==========================================================================
     一个状态，一句话——分**自称**和**他称**两份，不是六份
     ..........................................................................
     实测（不是读代码，是把六份表并排列出来）：同一个 `TaskStatus`，七个键全都在，
     分歧纯在措辞。

         状态          common.js  task-detail  app.js    page-family  elder.js  family.js
         executing     正在办      正在办      正在办理  正在办理     正在办理  正在执行
         completed     办好了      办好了      交易成功  已办好       已完成并核验 已完成并核验
         collecting    还在问清楚  还在问清楚  还在准备  还在准备     正在收集信息 正在收集信息

     六份表里没有一个键是六处一致的。而 `completed` 这一行最要紧：同一笔钱办好之后，
     老人端说「办好了」、凭证页说「交易成功」、家人端说「已完成并核验」——读的人
     没法判断这是同一件事，也没法判断「交易成功」是不是比「已完成」更强的一句话。

     ## 为什么是两份，不是一份

     状态的措辞里有**一个**真的和读者有关的维度：这件事是不是他自己的。同一个
     `awaiting_elder_confirmation`，老人在读自己的事时该说「等您复述确认」，
     家人和评委在读别人的事时该说「等老人复述确认」。合成一份会让其中一边说错话。

     所以标准说法是一对：`STATUS_WORD`（自称）与 `STATUS_WORD_OTHER`（他称）。
     两份**只允许在提到人的那几个键上不一样**——判据就是照这个建的：
     两份对同一个键给出不同的话时，其中至少一份必须出现「您」或「老人」，
     否则那不是称呼差异，那是漂移。`executing` 的「正在办理 / 正在执行」正是这么
     被抓出来的：两边都没提人，所以它没有理由不一样。

     ## 措辞取哪一份

     取 `elder.js` / `family.js` 那一对——它们是唯一成对设计过的两份（七个键里
     恰好只有两个提到人的键不同），而且覆盖着最大的两个壳。`executing` 统一成
     「正在办理」：这个产品对老人说的是「办」，「执行」是工程行话。

     ## /app 那两份字面副本已经收掉了

     这段原先写着「`app/pages/*.html` 不加载 common.js，所以那两份副本留着，
     由判据钉住」。**那句话现在是假的**：17 个页面各加了一行
     `<script src="/static/common.js">`（放在自己的脚本之前），
     `app/assets/js/app.js` 的 `CHAIN_WORDS`(17 条) 与 `CERT_STATE`(7 条)、
     `page-family-approve.js` 的 `STATUS`(7 条) 与 `STEP`(18 条) 都删了，
     改成读这一层。留下来的是**配色和图标**（`STATUS_COLOR` / `STEP_ICON`），
     那不是说法，不该收进词表。

     顺带补上了三十几个码：字面副本只有 17～18 条，这一层的审计表有六十多条，
     副本时代 `SCHEDULER_TICK` 那类落到兜底「留下一条记录」，现在有话说。

     取值刻意写成直接取 `window.YouHuo.AUDIT_WORD`，**不写
     `(window.YouHuo && …) || {}`**：那个写法会在这一层没加载时让整条链
     印出 17 行「留下一条记录」，看起来完全正常；直接取会抛 TypeError，
     被全局 catch 弹成「操作失败」——看得见。

     一段说明「为什么这里还有副本」的注释，在副本消失之后会让下一个人
     以为副本还在。那比没有注释糟。
     ========================================================================== */

  //: 任务状态 → 给人看的话（**自称**：他在读自己的事）。键必须是 `TaskStatus` 的值。
  const STATUS_WORD = {
    collecting: '正在收集信息',
    awaiting_elder_confirmation: '等您复述确认',
    awaiting_family_approval: '等家人接力',
    executing: '正在办理',
    completed: '已完成并核验',
    cancelled: '已取消',
    failed: '未成功，已安全停下',
  };

  //: 同一批状态的**他称**说法：家人、评委在读别人的事。
  //:
  //: 和上面那份逐键比对，只有提到人的两个键不同。判据不许出现第三种差异。
  const STATUS_WORD_OTHER = {
    collecting: '正在收集信息',
    awaiting_elder_confirmation: '等老人复述确认',
    awaiting_family_approval: '等您接力确认',
    executing: '正在办理',
    completed: '已完成并核验',
    cancelled: '已取消',
    failed: '未成功，已安全停下',
  };

  //: 状态 → 语气。只列需要着色的那几个，其余保持中性——这是有意的，
  //: 不是漏了：给每一个状态都上色等于没有颜色。
  const STATUS_TONE = {
    completed: 'good',
    failed: 'bad',
    cancelled: 'warning',
  };

  /** 任务类型的中文说法。认不出**不许**回落到原始枚举值。
   *
   * 兜底成「这件事」而不是把 `form_assistance` 印出去：这一层翻译存在的全部理由
   * 就是遇到没见过的类型时也不漏内部词，而那正是它最容易失效的时候。
   */
  function taskWord(type) {
    return TASK_WORD[String(type || '')] || '这件事';
  }

  /** 任务状态的中文说法。同上，认不出说「还在办」。
   *
   * `audience` 是 `'self'`（默认，他在读自己的事）或 `'other'`（家人、评委在读
   * 别人的事）。**默认值不是随手选的**：`/judge` 与设计三的家人端此前都在调
   * 无参的这一个，于是屏幕上对家人说「等您确认」——而要确认的人不是她。
   * 那两处的调用点要显式传 `'other'`；漏传的那一处会在报告里点名。
   *
   * 兜底「还在办」不许等于任何一个正常说法：否则「翻译成功」和「翻译失败」
   * 在屏幕上长得一样。这个形状这个仓库刚栽过一次——`family3.js` 的
   * `note: '记录'` 和它自己的 `|| '记录'` 撞了，一条没登记的记录和一条
   * 登记成「记录」的记录再也分不开。判据里有一条专门盯它。
   */
  function statusWord(status, audience) {
    const table = audience === 'other' ? STATUS_WORD_OTHER : STATUS_WORD;
    return table[String(status || '')] || '还在办';
  }

  /* ==========================================================================
     审计事件码 → 一句人话。五份表，同一个码没有一处措辞相同
     ..........................................................................
     实测把五份并排列出来（`judge.js` 31 条、`family.js` 24 条、
     `page-family-approve.js` 12 条、`app/assets/js/app.js` 8 条，外加 `trust.js`
     那份三段式的凭证叙述）：

         TASK_CREATED                  开始办一件事 / 开始办一件事 / 开始办一件事 / 立下这件事
         ELDER_CONFIRMED               您确认了 / 老人确认了 / 确认了 / 老人确认
         TEACH_BACK_VERIFIED           复述核对通过 / 复述核对通过 / 复述确认通过 / 她复述通过
         FAMILY_APPROVAL_RECORDED      家人已点头 / 家人已点头 / 点了同意 / 家人点头，已记下
         FAMILY_APPROVED_AND_EXECUTED  家人同意后已办好 / 同上 / 同意后办好了 / 家人点头，随即执行

     ## 措辞不是这里发明的，是后端已经有的

     `app_api.py` 里那张 `_WORDS`（40 条）就是这个词表，而且它已经上屏：
     `GET /app/records` 是后端翻好之后才发给前端的。它自己的注释写着这张表是
     `SELECT event_type, COUNT(*) FROM audit_events GROUP BY 1` 查库定的案——
     也就是说它是唯一一份被真实数据校对过的。

     所以这里的措辞**逐字照 `_WORDS`**，判据也是照它对的（不是照这里写的一份清单
     对——那样就又多了一份会过期的表）。`_WORDS` 没有的码才在这里补，补的那些
     判据管不到措辞，只管「不许和别处不一致」。

     ## 同样是自称 / 他称一对，而且只有一个键需要分

     `_WORDS` 是给老人自己的记录页写的，通篇只有一处说「您」：`ELDER_CONFIRMED`
     的「您确认了」。所以他称那份只需要覆盖这一个键。判据要求这个覆盖集**恰好**
     等于「自称说法里出现「您」的那些键」——多一条是无理由的漂移，少一条是
     对家人说了「您确认了」。
     ========================================================================== */

  //: 审计事件码 → 一句人话（**自称**）。前 20 条逐字来自 `app_api.py::_WORDS`。
  const AUDIT_WORD = {
    TASK_CREATED: '开始办一件事',
    ELDER_CONFIRMED: '您确认了',
    TEACH_BACK_VERIFIED: '复述核对通过',
    FAMILY_APPROVAL_RECORDED: '家人已点头',
    FAMILY_APPROVED_AND_EXECUTED: '家人同意后已办好',
    NOTIFICATION_CREATED: '发出一条通知',
    //: 这一条曾经是**两边不一样**的：后端 `_WORDS` 写的是「演示数据已就绪」，
    //: 而「演示」在 `test_app_surface_speaks_no_engineering` 的禁用词表里，
    //: 逐字照抄会让那道闸门在八个页面上同时变红（一处词，八个参数化）。
    //: 于是「和后端逐字一致」那条判据留了一个推出来的例外：后端那句话本身
    //: 含有消费面禁用词时，这里可以改写。
    //:
    //: **那个冲突后来是从源头修掉的**，不是靠这个例外一直绕着走——绕不干净：
    //: 后端那句话经 `/api/v1/records` 直接下发到两个消费面（老人自己的记录页、
    //: 家人端三「我的」的时间线），而它不经过任何静态文件，静态那道判据
    //: 一个字节也看不到它。实测在家人端三的时间线上读到过这一行：
    //:
    //:     演示数据已就绪     21:44 · 服务
    //:
    //: 所以后端那一条也换成了下面这句，两边现在一字不差。看得见它的判据是
    //: `test_app_records_speak_chinese` 里的
    //: `test_no_banned_consumer_word_is_translated_onto_the_screen`——
    //: 它查后端那几张**运行时**词表，不查 HTML。
    DEMO_SEEDED: '铺好了这个家庭的起始数据',
    DEMO_LOGIN: '登录了优活',
    MEDICATION_DOSE_RECORDED: '记了一次服药',
    MEDICATION_PLAN_DECIDED: '确认了一份用药计划',
    //: 下面三条逐字照后端 `_WORDS`。主语去掉了——这几个事件的动作人会变
    //: （`privacy._WHO_FROM_ACTOR` 里都有），写死「家人」会把她自己
    //: 提的那一条说成家人提的。他称版在下面 `AUDIT_WORD_OTHER` 里，
    //: 而那张表必须正好是这边含「您」的那一组，所以三条都得在这里。
    MEMORY_PROPOSED: '想让优活记一件事，等您点头',
    ITEM_MEMORY_PROPOSED: '想让优活记一件东西，等您点头',
    MEDICATION_PLAN_PROPOSED: '加了一份用药计划，等您点头',
    MEMORY_APPROVED: '同意记住一件事',
    MEMORY_REJECTED: '没有同意记那一件',
    MEMORY_REVOKED: '让优活忘掉一条',
    ROUTINES_MATERIALIZED: '排好了接下来的固定安排',
    ROUTINE_OCCURRENCE_COMPLETED: '完成了一件固定安排',
    'app.payment.prepared': '发起申请',
    'app.payment.teach_back': '复述确认',
    'app.payment.awaiting_family': '等家人确认',
    'app.emergency.requested': '紧急呼叫',
    'app.reminder.created': '加了一条提醒',
    'app.reminder.completed': '办好了一件事',
    'app.reminder.cancelled': '取消了一条提醒',
    'app.reminder.moved': '改了提醒的时间',
    'app.settings.changed': '改了设置',
    'app.appointment.created': '记下一次就医安排',
    'app.appointment.cancelled': '取消了一次就医安排',
    'app.emergency.notify_failed': '紧急呼叫没能通知到家人',
    'app.contact.phone_set': '登记了紧急联系电话',
    'app.health.recorded': '记了一次身体数据',
    'app.medication.decided': '确认了一份用药计划',
    'app.memory.decided': '决定了一条要不要记',
    'app.memory.forgotten': '让优活忘掉一条',
    'app.privacy.erased': '删掉了一批个人数据',
    'app.routine.created': '加了一件固定安排',
    'app.routine.paused': '暂停了一件固定安排',
    'app.routine.resumed': '恢复了一件固定安排',
    //: 下面这些 `_WORDS` 里没有，但审计链上真的会出现（评委页原先各写一份）。
    //: 措辞在这里定案，别处不许再起一套。
    SESSION_CREATED: '开始一次对话',
    TASK_SLOT_CORRECTED: '更正了其中一项信息',
    TEACH_BACK_REJECTED: '复述没对上，停在原地',
    FAMILY_REJECTED: '家人没有同意',
    FAMILY_APPROVED_EXECUTION_FAILED: '家人同意了，但这件事没办成',
    FAMILY_REMINDER_CREATED: '家人替您加了一条提醒',
    TASK_EXECUTED: '这件事办妥了',
    TASK_FAILED: '没能办成，已安全停下',
    TASK_CANCELLED: '这件事停下了',
    TASK_EXPLANATION_VIEWED: '有人调阅了这件事的说明',
    TASK_PROOF_GENERATED: '生成了一份完成证明',
    REMINDER_CANCELLED: '取消了一条提醒',
    SOS_TRIGGERED: '按了紧急求助',
    SAFETY_SIGNAL: '优活觉得这件事要当心',
    SEMANTIC_ROUTED: '听出要办的是哪件事',
    MODE_SWITCHED: '换了交互模式',
    EMOTIONAL_TASK_PAUSE: '先陪您说话，原来那件事先放着',
    EMOTIONAL_TASK_RESUMED: '回来接着办原来那件事',
    SUSPICIOUS_INSTRUCTION_BLOCKED: '挡下了一句可疑的话',
    VOICE_CONSENSUS_RESOLVED: '有句话没听准，重新对了一遍',
    SCHEDULER_TICK: '定时巡检走了一遍',
    PURPOSE_BOUND_POLICY_DECISION: '按目的绑定判定该不该放行',
    SAFE_ACTION_PREVIEWED: '执行前先预演一遍',
    RELIANCE_CARD_CREATED: '出了一张托付说明卡',
    COGNITIVE_LOAD_PLAN_CREATED: '把这一屏的信息量压低',
  };

  //: 他称的**差集**，不是又一份全表：只列自称说法里说「您」的那些键。
  //: 判据钉住「这个集合恰好等于自称里带「您」的键集」——所以它不会悄悄长大。
  const AUDIT_WORD_OTHER = {
    //: 这三条跟着「去掉写死的主语」那一改一起加。自称版说「等您点头」，
    //: 家属读别人的事时说「等老人点头」——称呼照 `_WORDS_OTHER` 的约定。
    MEMORY_PROPOSED: '想让优活记一件事，等老人点头',
    ITEM_MEMORY_PROPOSED: '想让优活记一件东西，等老人点头',
    MEDICATION_PLAN_PROPOSED: '加了一份用药计划，等老人点头',
    ELDER_CONFIRMED: '老人确认了',
    //: 这两条的自称版说「您」，而说的是老人。家属屏读同一张表时
    //: 不能对女儿说「您」——做那件事的人不是她。
    EMOTIONAL_TASK_PAUSE: '先陪老人说话，原来那件事先放着',
    FAMILY_REMINDER_CREATED: '家人替老人加了一条提醒',
  };

  //: **这里刻意不配一个 `auditWord()` 取值函数。**
  //:
  //: 写过一个，然后删了：没有调用者。共享的是**词表**，不是兜底那句话——每一页
  //: 认不出来时该说什么不一样，而那不是漂移，是各自的正当选择：
  //:
  //:   `/judge`  「（这个步骤还没有中文说法，原值在下面的完整记录里）」
  //:             ——评委页下面真的有那份完整记录，这句话在指路。
  //:   `/app`    「留下一条记录」
  //:             ——老人的凭证页没有「原始记录」那一块，不能许一个不存在的去处。
  //:
  //: 所以取值各页自己做（`judge.js` 的 `word(表, 值, 类别, 退回表)`），
  //: 这一层只提供两张表。一个没人调的导出函数比没有更糟：它看起来像已经统一了，
  //: 而实际统一没有发生——这个仓库管这叫「declared is not reachable」。


  //: 「存下来」——把「优活替我记了些什么」那一屏存成一份文件。
  //:
  //: 为什么在这一层：三个老人端界面都渲染这一屏（`elder.js` 服务设计一和设计二，
  //: `elder3.js` 服务设计三），而后端那句 `message` 对三个都说「可以存下来」。
  //: 各写一份就是这一轮一直在收敛的那个形状。
  //:
  //: **文件里写的必须等于屏幕上看到的。** `renderCounts()` 只印条数 > 0 的行，
  //: 所以这里用同一条过滤。一份和屏幕不一致的「存下来」，比不能存更糟——
  //: 她会拿着它去对，而对不上。判据钉的就是这一条。
  function myDataText(data) {
    const rows = (data.buckets || []).filter((b) => Number(b.count) > 0);
    //: 时间直接切后端给的串。它已经是本地钟点带偏移
    //: （`local_now(generated).isoformat()`），前端再用设备时区算一遍
    //: 就是这个项目修过的那个缺陷。也因此这里不需要第四个 `Asia/Shanghai` 常量。
    const when = String(data.generatedAt || '');
    const day = when.slice(0, 10);
    const clock = when.slice(11, 16);
    const out = ['优活替您存着的东西', ''];
    if (day) out.push(clock ? `导出时间：${day} ${clock}` : `导出时间：${day}`);
    out.push(`一共 ${Number(data.total) || 0} 条`);
    out.push('');
    rows.forEach((b) => out.push(`${b.name}　${b.count} 条`));
    if (!rows.length) out.push('这几类里现在没有替您存着的记录。');
    out.push('');
    if (data.digest) {
      //: 后端给的摘要是**截断**的（12 位 + 省略号，为了能念出来）。
      //: 管它叫「核验摘要」等于请人拿它去核验然后失败。
      out.push(`摘要开头：${data.digest}`);
      out.push('（只有开头几位，用来对照，不能用它核验。）');
    }
    if (data.note) out.push(String(data.note));
    out.push('');
    out.push('这一份是那一屏的原样留存，不含逐条记录。');
    return out.join('\n');
  }

  //: 存成文件。`a[download]` + blob：CSP 是
  //: `default-src 'self'; script-src 'self'`，而 `a[download]` 不走取回指令，
  //: 没有 `download-src` 这种东西——所以它过得去。**但这是推理，不是测量**，
  //: 所以判据里有一条真在浏览器里点它、看文件名和内容。
  function saveTextFile(filename, text) {
    const blob = new Blob([text], {type: 'text/plain;charset=utf-8'});
    const url = URL.createObjectURL(blob);
    const link = document.createElement('a');
    link.href = url;
    link.download = filename;
    //: 不给它任何类名，也不设 `hidden`。
    //:
    //: 第一版写了 `link.className = 'visually-hidden'`——而全仓四份样式表里
    //: **根本没有这个类**（`base.css` / `components.css` 都查过）。那是一句
    //: 指向不存在的东西的代码：它不会报错，只会让人以为位置有人管。
    //: 而 `hidden` 又有另一头的风险：部分内核对不可见元素的 `click()` 不触发下载。
    //:
    //: 真正的答案是两者都不需要——挂上、点、摘掉全在同一个同步块里，
    //: 中间没有一次绘制，所以它从来不会被看见。
    document.body.appendChild(link);
    link.click();
    link.remove();
    //: 立刻 revoke 会让部分内核的下载拿到空文件；下一帧再放。
    setTimeout(() => URL.revokeObjectURL(url), 0);
    return filename;
  }

  //: 给两个调用方共用的一颗按钮。挂在清单**下面**，不是标题旁边——
  //: 她读完「都记了我什么」才会想到「那我存一份」。
  //:
  //: 形状照这一层里既有的那个：一句 `p.meta` + 一颗 `button`。
  //: 第一版用的是 `.service-entry`，那是**首页那一排服务卡**的类
  //: （`min-height:96px`），塞进 `.data-out` 面板里是卡中卡；而这个面板本来就有
  //: `.data-out button{width:100%;min-height:56px}` 和 `.data-out button.secondary`
  //: 两条规则，专门为这个位置写的——`startErase` 用的就是它。
  //: 关键动作 ≥56px 由那条既有规则保证，不用我再声明一遍。
  function appendSaveMyData(host, data, speak) {
    //: 一条都没有的时候不出这颗按钮。
    //:
    //: 后端在 `total == 0` 那一支说的是「这几类里，优活现在没有替您存任何记录。」
    //: ——**它没有承诺「可以存下来」**（那句话只在有记录时才说）。所以那时摆一颗
    //: 「存下来」，是为一个没有做出的承诺加一个控件，存出来的还是一个空文件。
    //: 这是打开真页面才看见的：新库上那一屏正是 0 条。
    if (!(Number(data.total) > 0)) return null;
    const hint = document.createElement('p');
    hint.className = 'meta';
    hint.textContent = '存成一个文件，可以给家人看。';
    const button = document.createElement('button');
    button.type = 'button';
    button.className = 'secondary';
    button.dataset.do = 'save-my-data';
    button.textContent = '存下来';
    /* 每一次按都要有**各自**的回执。
     *
     * 原来两次按下去写的是同一个串（`已经存成「${name}」。`），DOM 不变、
     * 指纹不变、也没有请求——CDP 巡检据此把它报成死控件，而**它没报错**：
     * 她按了一下不确定成没成、再按一下，屏幕纹丝不动。而第二次是真的又存了
     * 一个文件（浏览器自动加 `(1)` 后缀）。做了事却什么都不说。
     *
     * 所以这里钉的是「随次数变化」这个性质，不是某一句文案。
     */
    let saved = 0;
    button.addEventListener('click', () => {
      const name = `优活-我的数据-${String(data.generatedAt || '').slice(0, 10)}.txt`;
      try {
        saveTextFile(name, myDataText(data));
      } catch (err) {
        /* 存不下的时候要说。
         *
         * 原来这一句是裸调：`saveTextFile()` 一抛，下面那行回执就不执行，
         * 屏幕上什么都不变——和「点下去什么都不发生」长得一模一样。
         * 不提「下载」这个词的失败原因：她要的是下一步能做什么。 */
        hint.textContent = '这台设备没能存下这个文件。您可以让家人帮您截一张图。';
        if (typeof speak === 'function') speak('这台设备没能存下这个文件。');
        return;
      }
      saved += 1;
      hint.textContent = saved === 1
        ? `已经存成「${name}」。`
        : `又存了一份，一共存了 ${saved} 次，都在您的下载里。`;
      if (typeof speak === 'function') {
        speak(saved === 1 ? '存好了，在您的下载里。' : '又存了一份，都在您的下载里。');
      }
    });
    host.append(hint, button);
    return button;
  }

  /* 一条长期记忆要她点头时，屏幕上说的那句话。**两个老人端界面共用这一份。**
   *
   * 三样缺一不可：谁看得见（`scope`）、记多久（`daysLeft`）、记它干什么（`purpose`）。
   * 少任何一样，点头就只是点头，而屏幕上照样是一句通顺的话——
   * 没有截图、点击遍历或控制台能看出区别。
   *
   * 后端给的 `scope` / `sensitivity` **已经是中文**，这里不再翻一遍：
   * 同一个值两套说法是这个项目栽过的那件事（字号语速和 SOS 各有两份实现）。
   *
   * 放在共享层而不是各写一份：`elder3.js` 早就有它，而 `elder.js`
   * （服务 `/elder` 与 `/elder2`）这一轮才补上同意这一整块。
   * 复制一份就是让「记多久」在两个界面上有两种算法。 */
  const noStop = (s) => String(s == null ? '' : s).replace(/[。．.，,、；;：:]+$/, '');

  function memoryWords(m, pending) {
    const bits = [m.scope];
    if (typeof m.daysLeft === 'number') {
      bits.push(pending ? `记住的话，${m.daysLeft} 天后自己忘掉`
                        : `还会记 ${m.daysLeft} 天`);
    }
    if (m.purpose) bits.push(`为的是${noStop(m.purpose)}`);
    return bits.join(' · ');
  }

  /* 家人提议让优活长期记住一件事。**她本人点头之后才生效。**
   *
   * 在这一条之前 `/v3/memories/propose` 全仓**零个前端消费者**：
   * 老人端三个界面都能点头、能不点、能逐条收回了，而没有任何界面能提出一条。
   * 那张「等您点头」的卡片于是在产品里永远不会出现——要看见它得直接打 API。
   *
   * 三个枚举用固定的最温和档，不做成下拉：
   *
   *     sensitivity: 'preference'    最轻的一档
   *     scope: 'family_summary'      家人只看得到「有这一条」，看不到内容
   *     ttl_days                     用后端默认（180 天），屏幕上说清
   *
   * 一是这三个枚举的中文说法**在后端**（读模型回的 `scope` 就是中文），
   * 前端再摆一套下拉就是同一个值两套说法。二是界面上根本不提供
   * `sensitive` / `family_shared` 这些组合——最重的那几种不该由「家人随手一提」产生。
   *
   * @param elderId  这一条要记在谁身上。后端会核它属不属于当前家庭（不属于回 403）。
   */
  async function proposeMemory(elderId, {key, detail, purpose}) {
    return api('/v3/memories/propose', {
      method: 'POST',
      body: JSON.stringify({
        elder_id: elderId,
        key,
        //: `value` 后端收 `Any`。装一句人话，不装工程结构：
        //: 她那一侧读的是 `noStop(m.detail)`，倒一个嵌套对象进去，
        //: 屏幕上就会出现花括号。
        value: {说明: detail},
        sensitivity: 'preference',
        scope: 'family_summary',
        purpose,
      }),
    }, 'family');
  }

  /* 把一个「让优活记住一件事」的表单接上去。**两个界面共用这一份。**
   *
   * 只吃元素，不吃 id：`/family` 与 `/family2` 用 id，而山水版那一套用 `name`。
   * 把选择器写死在这里，将来第三个界面接它时就得改这里。
   *
   * `notify(话, 语气)` 由调用方给——每个界面把回执写在自己那一处。
   *
   * `elderId` **可以传一个函数**，而且在这个项目里必须这么传：
   * `family.js:2` 是 `let ELDER_ID = 'elder-demo'`，到第 241 行身份解析完才
   * 被换成真的那个。接线发生在模块顶层，那时候读到的还是占位值——
   * 冻住它的话，这个表单会一直往 `elder-demo` 身上提议，
   * 而后端会正确地回 403「老人账户不属于当前家庭」。
   * 所以下面在**提交那一刻**才解析。
   */
  function wireProposeMemory(opts) {
    const {form, submit, keyInput, detailInput, purposeInput, elderId,
           notify, after} = opts;
    if (!form || !keyInput || !detailInput || !purposeInput) return false;

    /* 反复按同一下也要有反应。
     *
     * 这一轮已经三次栽在「同一句话赋两遍 → DOM 不动、指纹不动、请求 0」：
     * 「存下来」按第二次、`showMemories()` 在列表为空时把件数说两遍、
     * 「同步到他的手机」表单空着连按两次。她之所以再按，正是因为不确定
     * 刚才那一下有没有算上。
     *
     * 记的是「哪一格」而不是一个计数：填好一格再空另一格时，
     * 第二句不该指着一格她刚填好的。
     */
    let lastBlockedBy = null;

    const MISSING = {
      key: ['要让优活记住的是什么？写一个短名字，比如「看电视的音量」。',
            '「是什么」那一格还是空的。光标已经放在那儿了，写一个短名字就行。'],
      detail: ['具体是什么？写一句他看得懂的话，比如「晚上九点之后把声音调小」。',
               '「具体内容」那一格还是空的。光标已经放在那儿了，写一句话就行。'],
      purpose: ['记它是为了什么？这一句会原样给他看，比如「提醒时不影响邻居」。',
                '「为什么」那一格还是空的。光标已经放在那儿了，写一句话就行。'],
    };

    form.addEventListener('submit', (e) => {
      e.preventDefault();
      const key = (keyInput.value || '').trim();
      const detail = (detailInput.value || '').trim();
      const purpose = (purposeInput.value || '').trim();

      for (const [name, field, value] of [['key', keyInput, key],
                                          ['detail', detailInput, detail],
                                          ['purpose', purposeInput, purpose]]) {
        if (value) continue;
        const again = lastBlockedBy === name;
        lastBlockedBy = name;
        notify(MISSING[name][again ? 1 : 0], 'warning');
        field.focus();
        return;
      }
      lastBlockedBy = null;

      once(submit || form.querySelector('[type="submit"]'), async () => {
        try {
          //: 在**这一刻**解析，不在接线时（见上面那段说明）。
          const eid = typeof elderId === 'function' ? elderId() : elderId;
          const item = await proposeMemory(eid, {key, detail, purpose});
          /* 回执里**不能**说「记住了」。
           *
           * 后端把它存成 `status = "proposed"`，要她本人点头才变 active
           * （`/v3/memories/decide` 对家人的令牌回 403）。
           * 一句「已经记住了」会让家人以为这件事办完了——而她那一侧
           * 还摆着一张等她点头的卡。这一页的全部主张是「说到做到」。
           */
          notify(`记下了，在等他点头：「${item.key || key}」。`
                 + '他在自己那一页会看到这一条，同意了优活才会用；'
                 + '半年之后它自己忘掉。', 'good');
          form.reset();
          if (typeof after === 'function') after(item);
        } catch (err) {
          notify(errorWords(err, '这一条').text, 'warning');
        }
      });
    });
    return true;
  }

  // One timer per notice. Replacing a message cancels the previous dismissal.
  const noticeTimers=new WeakMap(), activeNotices=new Set();
  function dismissNotice(host){clearTimeout(noticeTimers.get(host));host.hidden=true;activeNotices.delete(host);}
  function showNotice(host,message,{duration=5000}={}){
    if(!host)return;
    clearTimeout(noticeTimers.get(host));
    const text=document.createElement('span');text.textContent=message;
    const close=document.createElement('button');close.type='button';close.className='notice-dismiss';close.setAttribute('aria-label','关闭提示');
    close.onclick=()=>dismissNotice(host);
    host.replaceChildren(text,close);host.hidden=false;host.classList.add('dismissible-notice');activeNotices.add(host);
    if(duration>0)noticeTimers.set(host,setTimeout(()=>dismissNotice(host),Math.max(duration,Math.min(12000,message.length*100))));
  }
  window.addEventListener('hashchange',()=>{for(const host of activeNotices)dismissNotice(host);});
  window.addEventListener('pagehide',()=>{for(const host of activeNotices)dismissNotice(host);});

  window.YouHuo = {
    ready, login, api, forget, token, showNotice, dismissNotice,
    byId, pretty, VERDICT, verdictOf, renderResult, initSections, once, toneOf,
    errorKind, errorWords,
    TASK_WORD, STATUS_WORD, STATUS_WORD_OTHER, STATUS_TONE, taskWord, statusWord,
    AUDIT_WORD, AUDIT_WORD_OTHER,
    myDataText, saveTextFile, appendSaveMyData,
    noStop, memoryWords, proposeMemory, wireProposeMemory,
  };
})();
