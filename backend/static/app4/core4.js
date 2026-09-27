/* 优活新版 App 两端共用的底子：登录、调接口、图标、标签页、轮播、提示条。
 *
 * 只调**已有**的接口（`/v2/*`、`/api/v1/*`），不另开后端。屏幕上的时间一律用服务器
 * 排好的字段（`time`、`date`），不在这里用设备时钟重算——这个项目为那件事付过代价。 */

export async function login(role) {
  return window.YouHuo.login(role);
}

/** 调接口。401 就重新登录一次再试；失败抛出，由调用方把话说给人听。 */
export async function api(role, path, {method = 'GET', body} = {}) {
  return window.YouHuo.api(path, {method, body: body === undefined ? undefined : JSON.stringify(body)}, role);
}

export function token(role) { return window.YouHuo.token(role); }

/** `<svg class="i"><use href="…#name"></use></svg>`，不走 innerHTML。 */
export function icon(name) {
  const ns = 'http://www.w3.org/2000/svg';
  const svg = document.createElementNS(ns, 'svg');
  svg.setAttribute('class', 'i');
  svg.setAttribute('aria-hidden', 'true');
  const use = document.createElementNS(ns, 'use');
  use.setAttribute('href', `/static/app4/icons.svg#${name}`);
  svg.append(use);
  return svg;
}

/** 小工具：建元素、设文字和类名。 */
export function el(tag, cls = '', text = '') {
  const node = document.createElement(tag);
  if (cls) node.className = cls;
  if (text) node.textContent = text;
  return node;
}

export function avatar(person) {
  const name = String(person.name || '家人');
  const kind = person.role === '社区' || /网格|社区/.test(name) ? 'community'
    : /女儿/.test(name) ? 'daughter' : /儿子/.test(name) ? 'son' : null;
  if (!kind) return el('span','a4-avatar a4-avatar-letter',name.slice(0,1));
  const image = document.createElement('img');
  image.className='a4-avatar'; image.src=`/static/app4/portrait-${kind}.png`;
  image.alt=''; image.width=56; image.height=56;
  return image;
}

let toastTimer = null;
window.addEventListener('hashchange',()=>{clearTimeout(toastTimer);const box=document.getElementById('toast');if(box)box.hidden=true;});
export function toast(text, ms = 3200) {
  const box = document.getElementById('toast');
  if (!box) return;
  const words=document.createElement('span');words.textContent=text;
  const close=document.createElement('button');close.type='button';close.className='notice-dismiss';close.setAttribute('aria-label','关闭提示');
  close.onclick=()=>{clearTimeout(toastTimer);box.hidden=true;};
  box.replaceChildren(words,close);box.classList.add('dismissible-notice');
  box.hidden = false;
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => { box.hidden = true; }, ms);
}

/** 底部标签栏：`[data-tab]` 按钮切 `[data-panel]` 面板，地址栏记 `#面板名`。 */
export function tabs(onShow = () => {}) {
  const buttons = [...document.querySelectorAll('.a4-tabs [data-tab]')];
  const panels = [...document.querySelectorAll('[data-panel]')];
  const show = name => {
    if (!panels.some(p => p.dataset.panel === name)) name = panels[0].dataset.panel;
    panels.forEach(p => { p.hidden = p.dataset.panel !== name; });
    buttons.forEach(b => {
      if (b.dataset.tab === name) b.setAttribute('aria-current', 'page');
      else b.removeAttribute('aria-current');
    });
    const bar = document.querySelector('.a4-tabs');
    if (bar) bar.dataset.active = String([...bar.children].findIndex(b => b.dataset.tab === name));
    window.scrollTo(0, 0);
    onShow(name);
  };
  buttons.forEach(b => b.addEventListener('click', () => {
    history.replaceState(null, '', `#${b.dataset.tab}`);
    show(b.dataset.tab);
  }));
  document.querySelectorAll('[data-goto]').forEach(b => b.addEventListener('click', () => {
    history.replaceState(null, '', `#${b.dataset.goto}`);
    show(b.dataset.goto);
  }));
  show(location.hash.slice(1));
  return show;
}

/** 摘要全部同时可见，不自动切换，避免老人读到一半内容消失。保留初始化接口。 */
export function carousel(root) {
  const dots = root?.querySelector('.a4-dots');
  if (dots) dots.replaceChildren();
  return () => {};
}

/** 一张摘要卡。保留旧调用的 img 参数兼容，画面不再使用装饰性轮播图。 */
export function slide({tag, title, more, img, tone = ''}) {
  const s = el('div', `a4-slide ${tone}`.trim());
  s.dataset.art = tag === '吃药' ? 'medicine' : 'journal';
  const label = el('span', 'tag');
  label.append(icon(tag === '吃药' ? 'pill' : 'calendar'), document.createTextNode(tag));
  s.append(label, el('strong', '', title));
  if (more) s.append(el('span', 'more', more));
  return s;
}

/** 来自接口的计数并排呈现，未记录不等同于没吃药。 */
export function metric({tag, done, total, label, more = '', tone = 'alt'}) {
  const s = el('div', `a4-slide ${tone}`.trim());
  s.dataset.art = tag === '吃药' ? 'medicine' : 'journal';
  const heading = el('span', 'tag');
  heading.append(icon(tag === '吃药' ? 'pill' : 'calendar'), document.createTextNode(tag));
  const count = el('div', 'a4-metric');
  count.append(el('b', '', String(done)), el('span', '', `/ ${total}`));
  s.append(heading, count, el('span', 'a4-metric-label', label));
  if (more) s.append(el('span', 'more', more));
  return s;
}

/** 日报的 `todayWord` 有时自己就以「今天」开头（「今天还没有记录」），
 *  有时不带（「和平常一样」）。实测第一版一律前面补「今天」，屏上出了「今天今天还没有记录」。 */
export function todaySays(word) {
  const w = String(word || '').trim();
  return w.startsWith('今天') ? w : `今天${w}`;
}

/** 服务器日报给的 `day`（"2026-09-26"）→「9月26日 · 星期六」。只用服务器那天，不看设备时钟。 */
export function dayLine(day) {
  const m = /^(\d{4})-(\d{2})-(\d{2})$/.exec(String(day || ''));
  if (!m) return '今天';
  const week = '日一二三四五六'[new Date(Date.UTC(+m[1], +m[2] - 1, +m[3])).getUTCDay()];
  return `${+m[2]}月${+m[3]}日 · 星期${week}`;
}

/** 按时段问好（用服务器日报给的日期，不看设备时区：这里只要上午 / 下午 / 晚上）。 */
export function greeting(hour) {
  if (hour < 5) return '夜深了';
  if (hour < 11) return '早上好';
  if (hour < 13) return '中午好';
  if (hour < 18) return '下午好';
  return '晚上好';
}
