// 两种角色共用应用外壳；业务子页面复用原业务模块及其确认流程。
const elder = document.body.classList.contains('a4-elder');
const mode = elder ? 'elder' : 'family';
export const features = elder ? {
  habits: ['字号与语速', 'me'], privacy: ['我的资料与记忆', 'me'],
  history: ['办事记录与详情', 'log'], reminders: ['提醒与待确认', 'home'],
  assistant: ['办事与陪伴', 'home'],
} : {
  reminders: ['提醒与记忆', 'todo'], history: ['办事记录', 'mine'],
  med: ['用药管理', 'medBody'], body: ['身体记录', 'bodyBody'],
  mood: ['心情记录', 'moodBody'], safety: ['安全与联系人', 'safetyBody'],
  trend: ['一周趋势', 'weekly'], today: ['今天的作息', 'todayBody'],
};
features.trust = ['可信记录', ''];
try {
  if (new URLSearchParams(location.search).has('launch')) {
    const saved = localStorage.getItem('youhuo.app.mode');
    if (saved === 'family' && elder) location.replace('/family4');
  }
  localStorage.setItem('youhuo.app.mode', mode);
} catch (_) {}

const overlay = document.createElement('section');
overlay.className = 'a4-workspace'; overlay.hidden = true;
overlay.setAttribute('role','dialog'); overlay.setAttribute('aria-modal','true');
overlay.setAttribute('aria-labelledby','workspaceTitle');
overlay.innerHTML = '<header><button type="button" aria-label="返回">‹ 返回</button><h2 id="workspaceTitle"></h2></header><p class="a4-workspace-loading" role="status">正在打开…</p><div class="a4-workspace-content"></div>';
document.body.append(overlay);
const back = overlay.querySelector('button'), title = overlay.querySelector('h2');
const content = overlay.querySelector('.a4-workspace-content');
let opener = null, timer = null;
let afterBack = null;
function dismiss() {
  if (overlay.hidden) return;
  clearTimeout(timer); overlay.hidden = true; content.replaceChildren();
  document.querySelector('.a4-app').inert = false;
  document.querySelector('.a4-tabs').inert = false;
  document.body.classList.remove('a4-workspace-open');
  opener?.focus({preventScroll:true});
  window.dispatchEvent(new Event('app4:refresh'));
}
function close(after) {
  const callback = typeof after === 'function' ? after : null;
  if (overlay.hidden) { callback?.(); return; }
  dismiss();
  if (history.state?.app4Workspace) {
    afterBack = callback;
    history.back();
  } else callback?.();
}
window.addEventListener('popstate', () => {
  dismiss();
  const callback = afterBack; afterBack = null; callback?.();
});
back.addEventListener('click', close);
window.addEventListener('app4:close-workspace', event => close(event.detail?.after));
document.addEventListener('keydown', e => {
  if (overlay.hidden) return;
  if (e.key === 'Escape') close();
  // The embedded document owns its form focus; wrapping applies to shell controls.
  if (e.key === 'Tab' && e.shiftKey && document.activeElement === back) {
    const frame = content.querySelector('iframe');
    if (frame) { e.preventDefault(); frame.focus(); }
  }
});
function openFeature(key, trigger) {
  if (trigger?.closest('.a4-pet-hub')) {
    window.dispatchEvent(new CustomEvent('app4:pet-feature', {detail:{key}}));
    return;
  }
  const feature = features[key];
  if (!feature) return;
  document.getElementById('sheetClose')?.click();
  if (overlay.hidden) {
    opener = trigger || document.activeElement;
    history.pushState({app4Workspace:key}, '', location.href);
  } else history.replaceState({app4Workspace:key}, '', location.href);
  title.textContent = feature[0]; overlay.hidden = false;
  document.body.classList.add('a4-workspace-open');
  document.querySelector('.a4-app').inert = true;
  document.querySelector('.a4-tabs').inert = true;
  const loading = overlay.querySelector('[role="status"]');
  loading.hidden = false; loading.textContent = '正在打开…';
  const frame = document.createElement('iframe');
  frame.title = feature[0]; frame.allow = 'microphone';
  frame.setAttribute('aria-busy', 'true');
  frame.src = key === 'trust' ? '/static/app4/trust-workspace.html' : `/static/app4/${mode}-workspace.html?view=${key}#${feature[1]}`;
  content.replaceChildren(frame); back.focus();
  clearTimeout(timer);
  timer = setTimeout(() => { loading.textContent = '打开较慢，可以返回后再试。'; }, 12000);
}
document.querySelectorAll('[data-feature]').forEach(button => {
  button.addEventListener('click', () => openFeature(button.dataset.feature, button));
});
window.addEventListener('message', event => {
  const frame = content.querySelector('iframe');
  if (event.origin !== location.origin || event.source !== frame?.contentWindow) return;
  if (event.data?.type === 'app4:ready') {
    frame.removeAttribute('aria-busy');
    overlay.querySelector('[role="status"]').hidden = true;
    clearTimeout(timer);
  }
  if (event.data?.type === 'app4:close') close();
  if (event.data?.type === 'app4:trust') openFeature('trust');
});
