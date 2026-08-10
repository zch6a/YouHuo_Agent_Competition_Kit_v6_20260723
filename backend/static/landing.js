'use strict';
/* 首页：记住上次选的身份。
 *
 * 「记住」不等于「劫持」。自动跳转只在**冷启动**时发生；从站内点回首页永远停在
 * 选择页，否则想换身份的人会被一路弹回去，而这恰恰是老人最容易卡住的那种循环。
 *
 * 判据**不能**用 `document.referrer`。
 *
 * 第一版就是这么写的（referrer 为空或非本站 = 冷启动），而它从来没有生效过：
 * `api.py` 的 `_SECURITY_HEADERS` 对每一个响应下发 `Referrer-Policy: no-referrer`，
 * 于是 `document.referrer` 恒为空串，"冷启动"恒为真。后果是选过一次身份之后，
 * 六个页面上每一个「返回首页」链接、以及家人端和照护页标签栏里的「首页」，全部会
 * 被立刻弹回去——想从家属端换到老人端只能自己清网站数据。注释里还写着站内链接
 * 指向 `/?stay=1`，而全站没有任何一处 `?stay=1`。
 *
 * 现在的判据是"这个标签页此前有没有打开过本应用的任何内页"：`common.js` 在被加载
 * 时（也就是五个内页任意一个打开时）往 sessionStorage 写一个标记。冷启动时那个标记
 * 不存在，会话内返回时它一定存在。sessionStorage 是每标签页独立的，正好是"会话"
 * 这个语义，而且不受任何响应头影响。
 *
 * 自动化检查天然安全：每轮全新 profile，localStorage 为空，不会触发跳转。
 */

(() => {
  const KEY = 'youhuo_role_v1';
  //: 与 common.js 里写入的键必须一致。两处都由 test_pwa_shell.py 钉住。
  const VISITED = 'youhuo_visited_v1';
  const DESTINATION = {elder: '/elder', family: '/family'};
  const WORD = {elder: '老人', family: '家人'};

  const params = new URLSearchParams(location.search);
  const stay = params.has('stay');

  let remembered = null;
  try { remembered = localStorage.getItem(KEY); } catch (_) { /* 隐私模式 */ }

  let cameFromThisSite = false;
  try { cameFromThisSite = !!sessionStorage.getItem(VISITED); } catch (_) { /* 隐私模式 */ }

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
