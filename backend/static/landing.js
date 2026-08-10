'use strict';
/* 首页：记住上次选的身份。
 *
 * 「记住」不等于「劫持」。自动跳转只在**冷启动**时发生——没有 referrer，或者
 * referrer 不是本站。从站内点回首页（老人端和家属端的返回链接都指向 `/?stay=1`）
 * 永远停在选择页，否则想换身份的人会被一路弹回去，而这恰恰是老人最容易卡住的
 * 那种循环。
 *
 * 冷启动的判据也让自动化检查天然安全：`check_page_runtime` 和 `shoot_pages` 每轮
 * 都用全新 profile，localStorage 是空的，不会触发跳转。
 */

(() => {
  const KEY = 'youhuo_role_v1';
  const DESTINATION = {elder: '/elder', family: '/family'};
  const WORD = {elder: '老人', family: '家人'};

  const params = new URLSearchParams(location.search);
  const stay = params.has('stay');

  let remembered = null;
  try { remembered = localStorage.getItem(KEY); } catch (_) { /* 隐私模式 */ }

  const cameFromThisSite = document.referrer
    && new URL(document.referrer, location.href).origin === location.origin;

  if (remembered && DESTINATION[remembered] && !stay && !cameFromThisSite) {
    location.replace(DESTINATION[remembered]);
    return;
  }

  if (remembered && WORD[remembered]) {
    const hint = document.getElementById('landingHint');
    if (hint) {
      hint.textContent = `上次您用的是「我是${WORD[remembered]}」。`;
      hint.hidden = false;
    }
  }

  document.querySelectorAll('.role-pick').forEach((link) => {
    link.addEventListener('click', () => {
      try { localStorage.setItem(KEY, link.dataset.role); } catch (_) { /* 隐私模式 */ }
    });
  });
})();
