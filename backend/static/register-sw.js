/* Register the service worker.
 *
 * A separate file rather than an inline <script> because the app ships
 * `script-src 'self'` — an inline block would be blocked, and loosening the CSP
 * for a three-line registration would be a bad trade.
 *
 * Registration failing is not an error worth showing anyone: the app works
 * exactly the same without it, only without offline shell caching and without
 * being installable.
 */
if ('serviceWorker' in navigator) {
  window.addEventListener('load', () => {
    navigator.serviceWorker.register('/sw.js', {scope: '/'}).catch(() => {});
  });
}
