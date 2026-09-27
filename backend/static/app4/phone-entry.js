/* Desktop presentation only; native Android and embedded feature pages stay intact. */
(() => {
  if (window.top !== window || window.YouhuoNative || innerWidth < 700) return;
  const mode = location.pathname === '/family4' ? 'family' : 'elder';
  const query = new URLSearchParams(location.search);
  query.set('mode', mode);
  location.replace('/phone?' + query.toString() + location.hash);
})();
