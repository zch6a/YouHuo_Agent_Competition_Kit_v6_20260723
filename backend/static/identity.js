/* Who this browser is, for a login-free public deployment.
 *
 * The pages used to hardcode `elder-demo` / `daughter-demo`. That is fine on a
 * laptop but wrong on a public URL: every visitor lands in the same family, so
 * two people looking at once see each other's reminders and can overwrite each
 * other's tasks. `POST /v2/auth/visitor` seeds a fresh household per browser;
 * family isolation is enforced on family_id server-side, so the sandbox is real.
 *
 * Loaded as a classic script (not a module) because care.js, trust.js and
 * judge.js are classic scripts too. Classic scripts run before deferred modules,
 * so elder.js can still `await YouHuoIdentity.ready()`.
 */
(function () {
  'use strict';

  const STORAGE_KEY = 'youhuo_visitor_identity_v1';

  // Falls back to the original fixed household when the visitor endpoint is not
  // available — demo mode off, or an older server. The app then behaves exactly
  // as it did before this file existed rather than failing to load.
  const SHARED = Object.freeze({
    elderId: 'elder-demo',
    daughterId: 'daughter-demo',
    sonId: 'son-demo',
    systemId: 'system-demo',
    familyId: 'fam-demo',
    elderToken: null,
    familyToken: null,
    isolated: false,
  });

  function readCached() {
    try {
      const raw = localStorage.getItem(STORAGE_KEY);
      if (!raw) return null;
      const parsed = JSON.parse(raw);
      return parsed && parsed.elderId ? parsed : null;
    } catch (_) {
      return null;
    }
  }

  async function provision() {
    // 跨标签页只允许一个在开通。
    //
    // 第 75 行的注释写着"memoised so five concurrent callers do not seed five
    // households"，但那个 memo 是 **document 级**的。两个标签页同时冷启动（干净
    // profile 下同时打开 /elder 和 /family，或者恢复上次的双标签会话，或者"装到主屏的
    // PWA + 浏览器标签"并存），各自 readCached() 得到 null、各自 POST /v2/auth/visitor，
    // 服务端跑两遍 seed_demo，得到**两个不同的 family_id**。localStorage 后写覆盖先写，
    // 而两个标签页的内存常量与 sessionStorage 令牌各自指向自己那一个。
    //
    // 后果不是"多了一个家庭"这么轻：女儿在家属端批准的高风险动作写进家庭 B，老人端在
    // 家庭 A，`require_family_approval` 的接力永远等不到——表现是"点了批准，老人端
    // 没反应"，而家属端的待办列表恒为空。换库之后 renew() 走同一条路，N 个标签页就
    // 开 N 个新家庭，且每个 reset() 都作废上一个标签页刚建好的那个。
    //
    // Web Locks 在这个应用支持的所有浏览器上都有；没有它的环境退回"临界区前后各查
    // 一次缓存"，仍能收窄窗口。
    if (navigator.locks?.request) {
      return navigator.locks.request('youhuo-visitor-provision', () => provisionOnce());
    }
    return provisionOnce();
  }

  async function provisionOnce() {
    const cached = readCached();
    if (cached) return cached;
    let response;
    try {
      response = await fetch('/v2/auth/visitor', {method: 'POST'});
    } catch (_) {
      return SHARED;               // offline or blocked: stay usable
    }
    if (!response.ok) return SHARED;
    // 拿到锁之前另一个标签页可能已经写好了（无 Web Locks 的降级路径）。
    // 那就用它的，把自己刚开的这一个丢掉——两个标签页在同一个家庭里，比各自正确
    // 但互相看不见重要得多。
    const raced = readCached();
    if (raced) return raced;
    const data = await response.json();
    const identity = {
      elderId: data.elder_id,
      daughterId: data.daughter_id,
      sonId: data.son_id,
      // The visitor endpoint does not mint a system token; that actor exists for
      // audit attribution only, and pages that need it derive the id.
      systemId: data.elder_id.replace(/^elder-/, 'system-'),
      familyId: data.family_id,
      elderToken: data.elder_token,
      familyToken: data.family_token,
      isolated: true,
    };
    try {
      localStorage.setItem(STORAGE_KEY, JSON.stringify(identity));
    } catch (_) {
      // Private browsing: the sandbox simply will not survive a reload.
    }
    return identity;
  }

  // Started eagerly so the first page render is not waiting on a round trip,
  // and memoised so five concurrent callers do not seed five households.
  let pending = provision();

  window.YouHuoIdentity = {
    ready: () => pending,
    /** Drop this browser's sandbox; the next load gets a brand new one. */
    reset() {
      try {
        localStorage.removeItem(STORAGE_KEY);
      } catch (_) { /* nothing to clear */ }
    },
    /** 服务器已经不认识这个身份了——扔掉，当场重开一个。
     *
     * 缓存的访客家庭是在**某一个**数据库里开通的。库换掉之后（重新部署、重置
     * 演示数据、换台机器跑），那个 family_id 就不存在了，登录每次都 401，而这里
     * 原先没有任何出路：`reset()` 写好了却没有人调用，`pending` 又是记忆化的，
     * 同一次加载里再问还是那个死身份。回访的人只会看到"访问令牌无效或已过期"，
     * 刷新多少次都一样，除非自己去清网站数据——不会有人这么做。
     *
     * 承重的是 `reset()`；重新开通这一步在"换完就整页重载"的路径下是冗余的
     * （变异测过：只留 reset 也能自愈）。留着是因为这个方法不该假设调用方一定
     * 会重载。
     */
    renew() {
      this.reset();
      // 会话也属于旧家庭，一并扔掉。
      //
      // 漏掉这一步的后果是"应用打得开、待办看得见、但一说话就报系统暂时不可用"：
      // `youhuo_session_v2` 还指着换掉之前的那个 family_id，`/v2/chat` 于是抛
      // AuthorizationError（403）。R12 修了身份这一半，这一半漏了。
      try { localStorage.removeItem('youhuo_session_v2'); } catch (_) { /* 隐私模式 */ }
      pending = provision();
      return pending;
    },
  };
})();
