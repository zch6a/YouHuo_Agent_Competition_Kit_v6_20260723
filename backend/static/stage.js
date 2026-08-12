'use strict';
/* 桌面演示舞台。
 *
 * 它做四件事：换 iframe 里的页面、换视口尺寸、把一句台词送进老人端、以及答辩模式。
 * 它**不做**的事：不参与产品逻辑、不碰后端、不往 App 里注入任何 App 自己不会做的
 * 行为。台词是通过真的填写输入框 + 真的点发送送出去的，所以框里发生的事和一位老人
 * 自己打字完全一样——演示不能是另一条代码路径，否则它证明不了任何东西。
 *
 * 同源 iframe，所以可以直接触达 contentDocument。CSP 的 `frame-src 'self'` 与
 * `frame-ancestors 'self'` 只放开了这一件事。
 */

(() => {
  const frame = document.getElementById('deviceFrame');
  const device = document.getElementById('device');
  const caption = document.getElementById('deviceCaption');
  const controls = document.getElementById('stageControls');
  const proof = document.getElementById('stageProof');
  const escape = document.getElementById('stageEscape');
  const hint = document.getElementById('stageHint');
  if (!frame || !device) return;

  //: 答辩模式要一起 inert 掉的两侧。右栏是后来加的，第一版只列了左栏——
  //: 于是「演示恶意文档金额」和「加载聚合指标」在"只留手机"之后仍然在 Tab 顺序里。
  const RAILS = [controls, proof].filter(Boolean);

  const ROLE_WORD = {
    '/elder': '老人端', '/family': '家人端', '/care': '照护',
    '/trust': '可信中心', '/judge': '评委导览',
  };

  let route = '/elder';
  let size = {w: 390, h: 844};

  function say(message) {
    if (!hint) return;
    hint.textContent = message;
  }

  function mark(group, chosen) {
    group.querySelectorAll('.stage-pick').forEach((btn) => {
      const on = btn === chosen;
      btn.classList.toggle('is-current', on);
      if (on) btn.setAttribute('aria-current', 'true'); else btn.removeAttribute('aria-current');
    });
  }

  function applySize() {
    // JS 只提**需求**，上限由 CSS 钳。
    //
    // 第一版这里直接写 `--screen-w` / `--screen-h`，而内联样式永远压过样式表里的
    // 响应式钳制——1360×900 下手机整台 860px 高，机身底边和那行说明一起被裁掉，
    // 而我加在 CSS 里的 `min(844px, 可用高度)` 一点作用都没有。
    // 现在 CSS 拿 `--want-*` 去算 `--screen-*`，两边职责不重叠。
    device.style.setProperty('--want-w', `${size.w}px`);
    device.style.setProperty('--want-h', `${size.h}px`);
    caption.textContent = `${ROLE_WORD[route] || route} · ${size.w} × ${size.h}`;
  }

  // --- 换页 -----------------------------------------------------------------

  document.getElementById('stageRoles').addEventListener('click', (event) => {
    const btn = event.target.closest('.stage-pick');
    if (!btn) return;
    route = btn.dataset.route;
    frame.src = route;
    mark(event.currentTarget, btn);
    applySize();
    say('');
  });

  document.getElementById('stageSizes').addEventListener('click', (event) => {
    const btn = event.target.closest('.stage-pick');
    if (!btn) return;
    size = {w: Number(btn.dataset.w), h: Number(btn.dataset.h)};
    mark(event.currentTarget, btn);
    applySize();
  });

  // --- 送一句台词进去 -------------------------------------------------------

  document.getElementById('stageLines').addEventListener('click', async (event) => {
    const btn = event.target.closest('.stage-pick');
    if (!btn) return;
    const line = btn.dataset.say;

    // 台词只对老人端有意义（那是唯一有对话入口的一端）。先切过去，等它加载完。
    if (route !== '/elder') {
      route = '/elder';
      frame.src = route;
      mark(document.getElementById('stageRoles'),
           document.querySelector('.stage-pick[data-route="/elder"]'));
      applySize();
      await new Promise((resolve) => frame.addEventListener('load', resolve, {once: true}));
      // 脚本是 defer 的，load 之后再给它一拍去绑事件。
      await new Promise((resolve) => setTimeout(resolve, 400));
    }

    const doc = frame.contentDocument;

    // 先按应用**自己的**打字入口，进 Focus Mode。
    //
    // 这三行是一个真缺陷换来的。老人端的对话、输入行和玻璃盒卡全都住在 Focus Mode
    // 里（`body[data-focus="on"]`）；直接填 `#text` 那一轮**真的发生**——任务立起来、
    // 审计链上有记录、气泡也进了 DOM——而屏幕停在「我在，您请说」，因为
    // `.elder-focus` 是 `display: none`。于是这一页会在旁白里说
    // 「已经替您说了：「帮我交这个月的水费」」，而投在大屏上的那台手机什么都没变。
    //
    // 答辩现场那一刻，是这台手机当众否掉了讲解人的话。而三道闸门都是绿的：
    // 点击遍历只问按不按得到，对比度只读计算颜色，截图拍的是没点过的首屏。
    //
    // 按 `#typeInstead` 而不是直接写 `body.dataset.focus`：同一条原则——
    // 演示不能走 App 自己不会走的路径，否则它证明不了任何事。
    const enter = doc && doc.getElementById('typeInstead');
    if (enter && doc.body.dataset.focus !== 'on') {
      enter.click();
      await new Promise((resolve) => setTimeout(resolve, 220));
    }

    const input = doc && doc.getElementById('text');
    const send = doc && doc.getElementById('send');
    if (!input || !send) {
      say('框里的应用还没准备好，等一下再点。');
      return;
    }
    // 说出去之前先确认她**看得见**这件事发生。宁可红，不要报一句假的"已经说了"。
    if (doc.body.dataset.focus !== 'on') {
      say('框里的应用没能进到对话状态，这句话没有发出去。');
      return;
    }
    // 真的填、真的按。不走任何 App 自己不会走的路径。
    input.value = line;
    input.dispatchEvent(new doc.defaultView.Event('input', {bubbles: true}));
    send.click();
    say(`已经替您说了：「${line}」`);
  });

  // --- 答辩模式 -------------------------------------------------------------

  let clean = false;

  function setClean(on) {
    clean = on;
    document.body.classList.toggle('is-clean', on);
    // `inert` 而不是只降透明度：答辩模式下控制条必须真的从可访问树和 Tab 顺序里
    // 消失，否则录屏时一次误触或一次 Tab 就把"场景：诈骗"这种按钮请回画面。
    RAILS.forEach((rail) => {
      if (on) rail.setAttribute('inert', ''); else rail.removeAttribute('inert');
      rail.setAttribute('aria-hidden', on ? 'true' : 'false');
    });
    escape.hidden = !on;
    if (on) escape.focus({preventScroll: true});
    else document.getElementById('stageClean').focus({preventScroll: true});
  }

  document.getElementById('stageClean').addEventListener('click', () => setClean(true));
  escape.addEventListener('click', () => setClean(false));
  addEventListener('keydown', (event) => {
    if (event.key === 'Escape' && clean) setClean(false);
  });

  document.getElementById('stageFull').addEventListener('click', () => {
    // 全屏可能被浏览器策略拒（无用户手势、iframe 沙箱、系统设置）。拒了就说一句，
    // 不要留一个按下去什么都不发生的按钮。
    const target = document.documentElement;
    if (document.fullscreenElement) {
      document.exitFullscreen().catch(() => say('退不出全屏，按 Esc 试试。'));
      return;
    }
    const request = target.requestFullscreen && target.requestFullscreen();
    if (request && request.catch) request.catch(() => say('这个浏览器不让我进全屏。'));
  });

  document.getElementById('stageReset').addEventListener('click', () => {
    // 重新开始 = 让框里的应用真的重新冷启动一次，包括清掉它的会话。
    const doc = frame.contentDocument;
    try {
      doc.defaultView.localStorage.removeItem('youhuo_session_v2');
      doc.defaultView.sessionStorage.clear();
    } catch (_) { /* 存储被禁：重载本身仍然有效 */ }
    frame.src = route;
    say('框里的应用已经重新开始。');
  });

  // --- 四个分区与深度开关 ---------------------------------------------------

  // 页内分区，与 App 那几页同一份实现（common.js）。四条底线的「→」指向的是分区
  // **里面**那篇卡片，靠的是 initSections 里的 resolve()。
  if (window.YouHuo && window.YouHuo.initSections) {
    window.YouHuo.initSections('product');
  }

  const depthButtons = {
    product: document.getElementById('depthProduct'),
    technical: document.getElementById('depthTechnical'),
  };

  /** 产品模式 / 技术模式。
   *
   * 产品模式把「工程」整层收起来：答辩的前八分钟不该有人看见 `/v5/metrics` 的原始
   * 响应，最后两分钟必须能当场打开。
   *
   * 收起来的时候必须处理"当前正停在工程层"这一种情况——否则右栏整个变空白，而
   * 页面不会报任何错。第一版就是这样：CSS 把那一段 display:none 掉，而
   * `initSections` 仍然认为它是当前分区。
   */
  function setDepth(depth) {
    document.body.dataset.depth = depth;
    Object.entries(depthButtons).forEach(([name, btn]) => {
      if (!btn) return;
      const on = name === depth;
      btn.classList.toggle('is-current', on);
      btn.setAttribute('aria-pressed', on ? 'true' : 'false');
    });
    const engineering = document.querySelector('.seg[data-section="engineering"]');
    if (depth === 'product' && engineering && engineering.classList.contains('is-current')) {
      const fallback = document.querySelector('.seg[data-section="product"]');
      if (fallback) fallback.click();
    }
  }

  if (depthButtons.product) {
    depthButtons.product.addEventListener('click', () => setDepth('product'));
  }
  if (depthButtons.technical) {
    depthButtons.technical.addEventListener('click', () => setDepth('technical'));
  }

  applySize();
})();
