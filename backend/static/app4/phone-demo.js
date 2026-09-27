(() => {
  const params = new URLSearchParams(location.search);
  let mode = params.get('mode') === 'family' ? 'family' : 'elder';
  try { if (params.has('launch')) mode = localStorage.getItem('youhuo.app.mode') === 'family' ? 'family' : 'elder'; } catch (_) {}
  const initialPath = '/' + mode + '4' + location.hash;
  if (innerWidth < 700) { location.replace(initialPath); return; }
  const screen = document.getElementById('appScreen');
  const space = document.querySelector('.device-space');
  const device = document.querySelector('.device');
  function fit() {
    const stage = document.querySelector('.demo-stage');
    // Keep a true mobile viewport. Scale the complete device, including its content.
    const scale = Math.min(1, Math.max(.2, (stage.clientHeight - 48) / 844), Math.max(.2, (innerWidth - 48) / 414));
    space.style.width = 414 * scale + 'px'; space.style.height = 844 * scale + 'px';
    device.style.transform = `scale(${scale})`;
  }
  function reflect(next) {
    mode = next;
    document.querySelectorAll('[data-mode]').forEach(b => b.setAttribute('aria-pressed', String(b.dataset.mode === mode)));
    const query = new URLSearchParams(location.search); query.delete('launch'); query.set('mode',mode);
    history.replaceState(null,'','/phone?' + query.toString());
  }
  document.querySelectorAll('[data-mode]').forEach(button => button.addEventListener('click', () => {
    if (button.dataset.mode === mode) return;
    reflect(button.dataset.mode); screen.src = '/' + mode + '4';
  }));
  screen.addEventListener('load', () => {
    try { const path = screen.contentWindow.location.pathname; if (path === '/family4' || path === '/elder4') reflect(path === '/family4' ? 'family' : 'elder'); } catch (_) {}
  });
  function time() { document.getElementById('phoneTime').textContent = new Date().toLocaleTimeString('zh-CN',{hour:'2-digit',minute:'2-digit',hour12:false}); }
  fit(); time(); reflect(mode); screen.src = initialPath;
  addEventListener('resize',fit); setInterval(time,60000);
})();
