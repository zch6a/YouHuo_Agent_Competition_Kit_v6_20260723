/* Register the service worker.
 *
 * A separate file rather than an inline <script> because the app ships
 * `script-src 'self'` — an inline block would be blocked, and loosening the CSP
 * for a three-line registration would be a bad trade.
 *
 * Registration failing is not an error worth showing the **user**: the app works
 * exactly the same without it, only without offline shell caching and without
 * being installable.
 *
 * But it is worth showing a **developer**. The catch here used to be `() => {}`,
 * and that cost this repo real time: three comment lines in `sw.js` were missing
 * their `//`, the whole file was a SyntaxError, and the service worker never
 * installed for several commits. The browser reported
 * `ServiceWorker script evaluation failed` on every page load — and this empty
 * catch ate all of it. Console was silent, `getRegistrations()` returned 0,
 * and nothing in 1786 tests looked at it.
 *
 * `console.warn` costs nothing, never reaches the user, and makes
 * "not installed" distinguishable from "working".
 */
if ('serviceWorker' in navigator) {
  window.addEventListener('load', () => {
    navigator.serviceWorker.register('/sw.js', {scope: '/'}).catch((err) => {
      console.warn('[youhuo] service worker 没能注册：', err);
    });
  });
}
