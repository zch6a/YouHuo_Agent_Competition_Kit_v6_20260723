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
const VERSION = 'youhuo-shell-v2';

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
  '/static/identity.js',
  '/static/common.js',
  '/static/elder.js',
  '/static/family.js',
  '/static/care.js',
  '/static/trust.js',
  '/static/judge.js',
  '/static/speech.js',
  '/static/sheet.js',
  '/static/register-sw.js',
  // 标签栏图标的外部 sprite。不缓存它，离线时五个标签会变成一排空白——而且不报错。
  '/static/icons/tabs.svg',
  '/static/icons/icon-192.png',
  '/static/icons/apple-touch-icon.png',
  '/static/manifest.webmanifest',
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
    caches.match(request).then(hit => {
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
