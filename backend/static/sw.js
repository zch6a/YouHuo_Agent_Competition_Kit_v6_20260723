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

const VERSION = 'youhuo-shell-v1';

const SHELL = [
  '/elder',
  '/static/style.css',
  '/static/identity.js',
  '/static/elder.js',
  '/static/speech.js',
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

/** Anything that reads or writes real state must always go to the network. */
function isApi(url) {
  return /^\/(v2|v4|v5|v6|health|ping|docs|openapi)/.test(url.pathname);
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
