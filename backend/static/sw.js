/* Service worker: makes the app installable and survivable on mobile data.
 *
 * Deliberately narrow. It caches the *shell* — HTML, CSS, JS, icons — and
 * never caches an API response. Bills, reminders, medication records and the
 * audit chain are authoritative state; serving a stale copy of any of them
 * would be the one failure this product is built to avoid. An elder who is told
 * "水费已缴" from a cache would be actively misled.
 *
 * Served from / rather than /static/ so its scope covers the whole app.
 */

//: 版本号必须随本文件的缓存策略一起变。
//:
//: 上一版把 /v7/* 当成外壳缓存了下来，那些条目此刻还躺在已安装设备的 v1 缓存里。
//: activate 只删除 key 不等于 VERSION 的缓存——不改这个字符串，被污染的条目就会
//: 一直留着，改了 isApi() 也救不回已经装好的那批。
//: v8 → v9：外壳清单漏了 `task-space.js`（这个会话早些时候加的），现在又要加
//: `task-detail.js`。不升这个字符串，已安装的设备会继续用 v8 那份**缺两个模块**
//: 的清单——而 `elder.js` 是 `type="module"`，一个 import 取不到就是整个模块图
//: 一起失败，离线的老人端不是降级而是白屏。
//: v10 → v11：加了美术卡片层（`art-cards.css` + `art-cards.js`，family/care/trust
//: 三页都引）。不升这个字符串，已安装的设备会继续用 v10 那份缺两个文件的清单——
//: 缺 JS 是整页白屏，缺 CSS 是卡壳图层没有定位规则，SVG 会以原始尺寸铺满全页。
//:
//: ⚠ 上面这三行我第一次写的时候漏了 `//`，只写了 `: v10 → v11…`。
//: 后果不是「注释格式不好看」——**整个文件语法错误，service worker 从此没装上过**。
//: `register-sw.js` 结尾是 `.catch(() => {})`，把 `ServiceWorker script evaluation
//: failed` 完整吃掉，控制台一声不响。浏览器里 `getRegistrations()` 返回 0，
//: 离线外壳没有、PWA 装不上，而这个文件里每一句关于缓存版本的话都成了空话。
//: `node --check backend/static/sw.js` 一秒能查出来，而它此前不在任何门里。
const VERSION = 'youhuo-shell-v12';

//: 外壳 = 六个页面各自的 HTML、CSS、JS 和图标。
//:
//: 上一版只列了 elder 一条路线，family/care/trust/judge/index 及其脚本都不在里面，
//: 断网时那四页直接白屏——而这是一个明确以"移动数据下也能用"为目标的 worker。
const SHELL = [
  '/',
  '/elder',
  '/family',
  '/care',
  '/trust',
  '/judge',
  // 样式表拆成了四层，加载顺序即层叠顺序；漏缓存其中任何一层，离线时的页面都会
  // 少掉一整段规则，而且看起来只是"样式坏了"。
  '/static/tokens.css',
  '/static/base.css',
  '/static/components.css',
  '/static/pages.css',
  // 美术卡片层。CSS 和 JS 都要在：JS 缺了是整页白屏（闸门
  // `test_shell_covers_every_module` 抓的就是这一条），CSS 缺了更隐蔽——
  // 卡壳 `<img>` 还会被插进 DOM，只是没有 `position:absolute`，
  // 于是一张 156KB 的山水图以原始尺寸把整页推开。
  '/static/art-cards.css',
  '/static/art-cards.js',
  '/static/landing.js',
  // 首页这一轮换了新设计，多出两个文件。两个都必须在这里：
  //   landing.css    离线时缺它 = 首页裸奔（它是这一页专属的第五层样式）
  //   landing-new.js `test_shell_covers_every_module` 抓到的就是它
  // 这条清单漏一个文件，在联网时一切正常，只有断网那一次才显形。
  '/static/landing.css',
  '/static/landing-new.js',
  '/static/identity.js',
  '/static/common.js',
  '/static/elder.js',
  '/static/family.js',
  '/static/care.js',
  '/static/trust.js',
  '/static/judge.js',
  '/static/speech.js',
  '/static/glassbox.js',
  '/static/sheet.js',
  // `elder.js` 用 `import` 拉这两个。ES module 的 import 失败不是"少个功能"，
  // 是整个模块图一起不执行——漏缓存它们，离线的老人端会白屏。
  // `test_the_shell_covers_every_module_it_imports` 从此守着这条。
  '/static/task-space.js',
  '/static/task-detail.js',
  '/static/register-sw.js',
  '/stage',
  '/static/stage.js',
  // `/stage` 的证明演示。这一条也是新建的闸门抓出来的——它和上面两个模块一样，
  // 被页面加载却不在外壳里。
  '/static/proof-demos.js',
  // 标签栏图标的外部 sprite。不缓存它，离线时五个标签会变成一排空白——而且不报错。
  '/static/icons/tabs.svg',
  '/static/icons/icon-192.png',
  '/static/icons/apple-touch-icon.png',
  // 六个页面请求的是根路径 `/manifest.webmanifest`（api.py 在根上单独开了一条路由）。
  // 这里原先写的是 `/static/manifest.webmanifest`——它恰好也能被 StaticFiles 取到，
  // 所以 `cache.add` 不报错，安安静静缓存了一个**没有任何人请求过**的 URL。缓存按
  // 完整 URL 索引，于是首次访问后立刻离线冷启，manifest 未命中、fetch 失败，
  // 安装提示、主题色和图标信息一起缺失。
  '/manifest.webmanifest',
  // 512 与两张 maskable 图标此前不在册：离线首装时 Android 只能拿 192 那张放大。
  '/static/icons/icon-512.png',
  '/static/icons/icon-192-maskable.png',
  '/static/icons/icon-512-maskable.png',
];

self.addEventListener('install', event => {
  event.waitUntil(
    // Individually, so one missing file cannot fail the whole install.
    caches.open(VERSION).then(cache => Promise.all(
      SHELL.map(url => cache.add(url).catch(() => {})),
    )).then(() => self.skipWaiting()),
  );
});

self.addEventListener('activate', event => {
  event.waitUntil(
    caches.keys()
      .then(keys => Promise.all(keys.filter(k => k !== VERSION).map(k => caches.delete(k))))
      .then(() => self.clients.claim()),
  );
});

/** Anything that reads or writes real state must always go to the network.
 *
 * Version-agnostic on purpose. This used to list v2/v4/v5/v6 by hand, and when
 * /v7/* was added — 生活基线、生活日报、关怀动作、环境采样, i.e. the entire
 * personalised-baseline surface — it fell through to the shell cache. That is
 * precisely the "stale copy of authoritative state" failure the comment at the
 * top of this file says must never happen: a family member could have been
 * shown yesterday's 日报 and told nothing was unusual. Matching /v\d+/ means a
 * future version cannot reintroduce the bug by being forgotten here.
 */
function isApi(url) {
  return /^\/(v\d+|health|ping|docs|redoc|openapi)(\/|$|\.)/.test(url.pathname);
}

self.addEventListener('fetch', event => {
  const {request} = event;
  if (request.method !== 'GET') return;

  const url = new URL(request.url);
  if (url.origin !== self.location.origin) return;
  if (isApi(url)) return;                       // never cached, never intercepted

  event.respondWith(
    // `ignoreSearch` 不是可选的。
    //
    // `caches.match` 默认把 query 算进匹配，而外壳里存的是 `/elder`。manifest 的
    // 快捷方式指向 `/elder?mode=companion`——装好 PWA 之后长按图标选「找无忧伴聊聊」，
    // 离线时缓存未命中、fetch 抛错、`.catch(() => hit)` 得到 undefined，
    // `respondWith(undefined)` 让这次导航直接失败，连浏览器自带的离线页都拿不到。
    // 主图标（start_url 是 `/elder`）正常，只有快捷方式是死的。
    //
    // API 请求在上面第 101 行就早退了，不会走到这里，所以忽略 query 不会让带参数的
    // 权威状态请求命中一份陈旧副本。
    caches.match(request, {ignoreSearch: true}).then(hit => {
      // Stale-while-revalidate for the shell: instant paint, fresh next launch.
      const fetching = fetch(request)
        .then(response => {
          if (response && response.ok) {
            const copy = response.clone();
            caches.open(VERSION).then(cache => cache.put(request, copy)).catch(() => {});
          }
          return response;
        })
        .catch(() => hit);
      return hit || fetching;
    }),
  );
});
