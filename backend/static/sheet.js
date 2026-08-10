/* Bottom sheet for the elder screen.
 *
 * The dismissal rule is taken from Framework7's sheet-class.js, which is the
 * most-copied mobile-web sheet there is:
 *
 *     if ((timeDiff < 300 && diff > 20) || (timeDiff >= 300 && diff > height / 2))
 *
 * A flick under 300ms needs only 20px; a slow drag has to commit past half the
 * sheet. That combination is why a good sheet feels neither sticky nor twitchy,
 * and it happens to be exactly right for this audience: almost no force is
 * needed to dismiss deliberately, while a hesitant, wandering finger cannot
 * dismiss by accident.
 *
 * Written in vanilla JS on purpose. Motion or Swiper would each do this, but the
 * settle is an overdamped curve a CSS transition already expresses, and pointer
 * tracking is the twenty lines below — a ~30KB dependency for that would be paid
 * for by every elder on mobile data, on a free-tier server, for nothing.
 *
 * The sheet is never gesture-only: it opens and closes from a real labelled
 * button. Gesture-only UI fails this audience first.
 */
(function () {
  'use strict';

  const sheet = document.querySelector('#extrasSheet');
  const backdrop = document.querySelector('#sheetBackdrop');
  // 取成真数组：NodeList 有 forEach 但**没有** some/find。我加 `isDrawer()` 时用了
  // `openers.some(...)`，运行时闸门当场报了 TypeError——而如果没有那道闸门，表现会是
  // 抽屉按钮一按就抛异常、什么也不发生，和"按钮是死的"一模一样。
  const openers = [...document.querySelectorAll('[data-sheet-open]')];
  const closers = [...document.querySelectorAll('[data-sheet-close]')];
  if (!sheet || !backdrop) return;

  const FLICK_MS = 300;
  const FLICK_PX = 20;
  let dragging = false;
  let startY = 0;
  let startTime = 0;
  let offset = 0;
  let lastFocus = null;

  /** 现在这东西是抽屉，还是一根常驻侧栏？
   *
   * 断点写在 CSS 里（`@media (min-width: 761px)` 让 `.rail.sheet` 变成
   * `position: static`，并把触发器、把手、背板全部 `display: none`）。JS 不再写第二份
   * 断点，而是问 CSS：触发器还看得见吗？看不见就说明这一刻它是侧栏。
   * 这样改 CSS 的断点不需要同时改 JS——这个项目已经因为"两处各写一份常量"吃过亏
   * （`elder.js` 的 500ms 与 `--mode-fade`）。
   */
  function isDrawer() {
    return openers.some(b => getComputedStyle(b).display !== 'none');
  }

  /** 抽屉打开时把它背后的东西整体 inert。
   *
   * 背板是 `pointer-events: auto`、body 是 `overflow: hidden`，所以它已经是个模态；
   * 但背后的页面从未被隔离。从「保存我的习惯」继续按 Tab，焦点会走进被抽屉完全盖住
   * 的输入框和麦克风——一个只用键盘或开关控制的用户，在往一个他看不见的框里打字。
   */
  function outsideLayers() {
    return [...document.querySelectorAll('main > *, .elder-layout > *')]
      .filter(el => el !== sheet && el !== backdrop && !el.contains(sheet));
  }

  let wantOpen = false;

  function apply() {
    const drawer = isDrawer();
    // 侧栏形态下它永远是"开"的。此前这里无条件按抽屉处理：模块一加载就
    // `setOpen(false)`，于是 ≥761px 时侧栏照样渲染出来、看起来完全正常，而里面
    // 十几个控件全被 `inert` + `aria-hidden` 打死——鼠标点不动、Tab 到不了、读屏
    // 看不到，且**没有任何恢复路径**：唯一调用 setOpen(true) 的触发器在那个宽度下是
    // display:none，把手和背板也是，Escape 又要求 `.is-open`。
    const open = drawer ? wantOpen : true;
    sheet.classList.toggle('is-open', drawer && open);
    backdrop.classList.toggle('is-open', drawer && open);
    sheet.setAttribute('aria-hidden', open ? 'false' : 'true');
    // inert rather than display:none so the panel stays in the layout: the
    // contrast audit measures computed colours of these controls, and hiding
    // them would quietly shrink that safety net instead of failing loudly.
    if (open) sheet.removeAttribute('inert'); else sheet.setAttribute('inert', '');
    openers.forEach(b => b.setAttribute('aria-expanded', open ? 'true' : 'false'));
    document.body.classList.toggle('sheet-open', drawer && open);
    outsideLayers().forEach(el => {
      if (drawer && open) el.setAttribute('inert', ''); else el.removeAttribute('inert');
    });
  }

  function setOpen(open) {
    const drawer = isDrawer();
    wantOpen = open;
    apply();
    if (!drawer) return;                       // 侧栏形态不抢焦点
    if (open) {
      lastFocus = document.activeElement;
      const first = sheet.querySelector('button, a, select, input');
      if (first) first.focus({preventScroll: true});
    } else if (lastFocus) {
      lastFocus.focus({preventScroll: true});
      lastFocus = null;
    }
  }

  function endDrag(commitClose) {
    dragging = false;
    sheet.style.transition = '';
    sheet.style.transform = '';
    if (commitClose) setOpen(false);
  }

  sheet.addEventListener('pointerdown', event => {
    // Only the handle drags. Dragging from anywhere would fight the scrollable
    // list inside, which is the usual reason home-made sheets feel broken.
    if (!event.target.closest('.sheet-handle')) return;
    dragging = true;
    startY = event.clientY;
    startTime = Date.now();
    offset = 0;
    sheet.style.transition = 'none';
    sheet.setPointerCapture?.(event.pointerId);
  });

  sheet.addEventListener('pointermove', event => {
    if (!dragging) return;
    offset = Math.max(0, event.clientY - startY);   // downward only
    sheet.style.transform = `translate3d(0, ${offset}px, 0)`;
  });

  sheet.addEventListener('pointerup', () => {
    if (!dragging) return;
    const elapsed = Date.now() - startTime;
    const flicked = elapsed < FLICK_MS && offset > FLICK_PX;
    const dragged = elapsed >= FLICK_MS && offset > sheet.offsetHeight / 2;
    endDrag(flicked || dragged);
  });
  sheet.addEventListener('pointercancel', () => endDrag(false));

  openers.forEach(b => b.addEventListener('click', () => setOpen(true)));
  closers.forEach(b => b.addEventListener('click', () => setOpen(false)));
  backdrop.addEventListener('click', () => setOpen(false));
  document.addEventListener('keydown', e => {
    if (e.key === 'Escape' && sheet.classList.contains('is-open')) setOpen(false);
  });

  // 跨过断点时重新判定。把窗口从手机宽度拖大（或折叠屏展开、横竖屏切换），
  // 抽屉会变成侧栏——如果不重算，它会带着 inert 一起变过去。
  addEventListener('resize', apply);

  setOpen(false);
})();
