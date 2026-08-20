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
//: v12 → v13：老人端换成 v8 版式，多出 `elder-family-v3.css`（第五层，20KB）。
//:
//: **不升这个字符串的后果不只是离线**。用户在浏览器里点进 /elder 看到的还是
//: 旧版——sw.js 是 stale-while-revalidate（`hit || fetching`），已安装的 worker
//: 先返回 v12 缓存里的那份 `elder.html`，新版要等下一次启动才生效。
//: 我装完 v8 之后忘了这一步，用户打开看到的是旧页面，而服务器上明明是新的。
//: 装任何一次前端包，「改文件」和「让浏览器拿到」是两件事。
//: v13 → v14：家人端设计二上线（/family2），多出四个文件。
//: v14 → v15：老人端设计二上线（/elder2），多出四个文件。
//: 这一页的业务逻辑是 `elder.js`（已在册），它是 `type="module"`——漏缓存
//: 它 import 的任何一个模块都是整页白屏，不是降级。那几个也早就在册了，
//: 这里多的只是这一版自己的版式和两份视觉脚本。
//: v15 → v16：`/elder2` 的验收。两件事都改了缓存里的**内容**而不是清单：
//:   ① `elder-v6.html` 补上了 manifest / apple 全屏那一套和 `register-sw.js`。
//:      v15 是为这一页升的，可这一页当时**从不注册 service worker**——外壳
//:      声明了它，而它自己永远装不上，第一次就直接进 `/elder2` 的人拿不到缓存。
//:   ② `elder-v6.css` 把主要操作从 48/52 抬到 56（设计一那批同名控件量出来是 56），
//:      并给 `.segmented button` 补 `min-width`（「慢」「大」实测 37×48，低于下限）。
//: 清单一条没变，所以「漏文件」那种检查看不出区别——但 stale-while-revalidate
//: 会先把 v15 缓存里的旧 HTML/CSS 返回去，用户看到的还是 37px 那一版。
//: 「改文件」和「让浏览器拿到」是两件事，这个文件上面第 37 行已经为同一件事写过一次。
//: v16 → v17：`isApi()` 漏掉了整个 `/api/v1` 层（50 个端点）。
//: 已安装的 worker 缓存里躺着一批 `/api/v1` 的旧响应，`activate` 只删 key 不等于
//: VERSION 的缓存——不升这个字符串，改了 `isApi()` 也救不回已经装好的那批，
//: 而它们会继续把「上一次的答案」交给老人。详见下面 `isApi()` 上面那段。
//: v17 → v18：设计三（网页端）上线，`/elder3` 与 `/family3`。
//: 这一版**不共用**设计一二的业务脚本——它是另一套 DOM，接线是
//: `elder3.js` / `family3.js`。清单里因此多出两页 HTML、两份接线、两份接线样式，
//: 外加交付包自己的 CSS/JS 与两页共用的 `v3/`（飞鹤动画 2.2 MB + 国风麦克风）。
//: 漏掉 `v3/crane-animation-master.js` 不是"少个动画"：它是 `<script src>`，
//: 离线时取不到就是一次加载失败，后面的接线脚本照跑，但飞鹤那一层不存在。
//: v18 → v19：「家人加的药等老人点头」这条流程两头都接上了，动到的是
//: `elder.js` `elder3.js` `family3.js` `family3-wiring.css` —— **四份全在下面
//: 的预缓存清单里**。不升这个字符串，已经装过这个站点的浏览器会继续拿 v18
//: 缓存里的旧接线：家人端那个加药入口根本不存在，老人端也不会问她要不要吃，
//: 而**页面看起来完全正常**。这个项目已经为同一件事栽过两次（37px 那一版、
//: `/api/v1` 的旧响应），这是第三次写同一条注释。
//: v19 → v20：设计三补齐了「我的数据」四条、玻璃盒、记一次已吃/没吃、
//: 记一次身体数据。动到 `elder-v3.html` `elder3.js` `elder3-wiring.css`
//: `family3.js` `family3-wiring.css`——五份全在下面的清单里。
//: 玻璃盒走的是**动态 `import('/static/glassbox.js')`**，那份也早在清单里，
//: 漏了它不是「少张卡」：弱网下 import 直接 reject，走进 catch 把卡收掉，
//: 屏幕上什么都不会少，只是那张卡再也不出现。
//: v20 → v21：设计三补上最后三条（措辞适配 `/v6/interaction/plan`、
//: 一件事的经过 `/v2/tasks` + `task-detail.js`、优活给家人的消息
//: `/v2/notifications`）。后两条也走动态 `import()`，两份模块都早在清单里。
//: v21 → v22：`judge.js`（失败不再印成绿的、不再印 `Failed to fetch`）和
//: `family3.js`（照护屏那句概括真的换掉）都改了。不升这个字符串，
//: 回访的人第一次打开拿到的还是缓存里的旧脚本——审计页照旧把失败印成绿的，
//: 而我这边看新装的浏览器一切正常。
const VERSION = 'youhuo-shell-v22';

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
  '/static/art-cards-family.css',
  // 老人端 v8 的第五层。漏缓存它，离线时 /elder 会少掉一整层版式规则——
  // 而那一层管的是壳结构、麦克风区和四个面板的排布，缺了不是"样式差一点"，
  // 是回到没有布局的裸文档流。
  '/static/elder-family-v3.css',
  // 家人端设计二（/family2）。四屏合一的壳，和设计一并行。
  // 业务逻辑共用 family.js / care.js，这里只多出它自己的版式和视觉脚本。
  '/family2',
  '/static/family-v6.html',
  '/static/family-v6.css',
  '/static/family-v6-a.js',
  '/static/family-v6-b.js',
  // 老人端设计二（/elder2）。同样只多出它自己的版式和两份视觉脚本——
  // 业务逻辑走的是已经在册的 `elder.js` 那一整条 import 链。
  '/elder2',
  '/static/elder-v6.html',
  '/static/elder-v6.css',
  '/static/elder-v6-a.js',
  '/static/elder-v6-b.js',
  // 老人端 / 家人端**设计三 · 网页端**（/elder3 /family3）。
  //
  // 和设计二不同：这两页不共用 `elder.js` / `family.js`，它们是另一套 DOM，
  // 接线各自一份。交付包自己的 CSS 很大（2.3 MB / 1.6 MB，内联了美术），
  // 但那正是这一版的全部价值，缺了就是一张没有画的纸。
  '/elder3',
  '/static/elder-v3.html',
  '/static/elder3.js',
  '/static/elder3-wiring.css',
  '/static/elder3/app-01.css',
  '/static/elder3/page-motion-and-ui.js',
  '/static/elder3/yoli-mascot.js',
  '/family3',
  '/static/family-v3.html',
  '/static/family3.js',
  '/static/family3-wiring.css',
  '/static/family3/style-01.css',
  '/static/family3/script-01.js',
  '/static/family3/script-02.js',
  '/static/family3/script-03.js',
  '/static/family3/script-04.js',
  '/static/family3/script-05.js',
  '/static/family3/script-06.js',
  '/static/family3/script-07.js',
  '/static/family3/script-08.js',
  '/static/family3/script-09.js',
  '/static/family3/script-11.js',
  '/static/family3/script-12.js',
  // 两页共用。飞鹤动画在两个交付包里字节一致，装一份。
  '/static/v3/crane-animation-master.js',
  '/static/v3/mic-guofeng.png',
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
 *
 * ⚠ 而它**还是又发生了一次**，就在这段注释底下。
 *
 * `/api/v1` 那一层（老人端门面，50 个端点）是后来加的，它以 `/api/` 开头，
 * `^\/(v\d+|…)` 一个都不匹配——于是整层被当成外壳缓存，走
 * stale-while-revalidate（`hit || fetching`：先把上一次的响应交出去）。
 *
 * 实测（同一个访客、四次调用，真实状态 59 → 59 → 0）：
 *
 *     GET /api/v1/privacy/data      →  0     ← 上一次的
 *     POST /privacy/erase/preview   →  59    ← POST 不走缓存，是真的
 *     POST /privacy/erase           →  删掉 59 条，库里核实过：真删了
 *     GET /api/v1/privacy/data      →  59    ← 又是上一次的
 *
 * 屏幕上的效果是：老人删完自己的数据，页面告诉他**一条都没删**。
 * 这正是本文件开头那句「serving a stale copy … would be the one failure this
 * product is built to avoid」，而且发生在最需要信任的那条路径上。
 *
 * 写操作没受影响（下面 `request.method !== 'GET'` 早退），受影响的全是读。
 * 但「读到旧的」在这个产品里不是小问题：日报、用药、亲友、隐私清单都是读。
 *
 * 加 `api`。同时**必须升 VERSION**——已安装的 worker 缓存里躺着一批
 * `/api/v1` 的旧响应，`activate` 只删 key 不等于 VERSION 的缓存，
 * 不升的话改了这个函数也救不回已经装好的那批。这一条上面第 14 行说过一次。
 */
function isApi(url) {
  return /^\/(v\d+|api|health|ping|docs|redoc|openapi)(\/|$|\.)/.test(url.pathname);
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
