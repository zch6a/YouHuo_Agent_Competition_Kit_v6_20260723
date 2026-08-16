"use strict";
/* landing-new.js — IntersectionObserver 入场 + 磁贴涟漪
 *
 * 与 landing.js 互补：landing.js 处理身份记忆和跳转，这个文件只做动效。
 * 不动 landingHint / role-pick 的 DOM 契约。
 */

(() => {
  // 入场动画：用 IntersectionObserver 触发一次性 CSS 动画
  // 不用 JS 动画，避免破坏 prefers-reduced-motion 和 CSS-only 策略
  const observer = new IntersectionObserver((entries) => {
    for (const entry of entries) {
      if (entry.isIntersecting) {
        entry.target.classList.add("yh-in-view");
        observer.unobserve(entry.target);
      }
    }
  }, { threshold: 0.1 });

  // 标记所有需要入场动画的元素
  // `.yh-grid`（八张能力卡那一节）已按任务 D 删除，选择器里一并去掉——
  // 留着不会报错，只会让下一个读它的人以为页面上还有这一节。
  document.querySelectorAll(".landing-main, .yh-hero, .yh-choose, .yh-foot").forEach((el) => {
    observer.observe(el);
  });

  // 这里原先给每张磁贴绑了 Enter/Space → `tile.click()`。
  //
  // 用 CDP 真按下去过：click 事件确实发出，然后 URL 没变、DOM 没变、没有任何提示层。
  // 磁贴是 <li>，既没有 href 也没有任何 click 监听——这个处理器把键盘事件吃掉
  // （preventDefault）之后转发给一个没有人接的 click。它唯一的实际效果是让八张
  // 磁贴留在 Tab 序列里，给键盘用户八个什么都不做的停靠点。
  //
  // 磁贴现在是静态清单（说明常显，见 landing.css 里那段），没有可绑的行为了。
})();