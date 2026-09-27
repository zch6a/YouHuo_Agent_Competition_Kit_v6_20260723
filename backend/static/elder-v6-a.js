/* 老人端设计二的外壳适配层。
 *
 * 这一份**一个 fetch 都没有**。业务逻辑全在 `elder.js` 里，两套皮共用那一份。
 * 这里只做三件 `elder.js` 不该知道的事：
 *
 *   ① 顶栏时钟与问候语。原包在这两处印着写死的「周二 · 17:25 / 26℃ · 微风」，
 *      而这个产品没有天气。屏幕上一句与事实无关的话，比一个工程词严重。
 *   ② Focus Mode 里那个圈**转交**给首页那一个 `#mic`，不自己建第二个状态机。
 *   ③ 「我的」那两项：屏幕上是按钮组，值挂在旁边一个 `hidden` 的 `<select>` 上。
 *
 * 分区切换、Focus Mode 的开合、待办与记录的渲染都**不在这里**：那些
 * `common.js` 的 `initSections` 和 `elder.js` 已经做了。包自带的 `script-01.js`
 * 各写了一份，两份并存就是这个项目栽过的那个形状（两边各自往返都绿，跨子系统才红），
 * 所以那一份整个没有搬过来。
 */
(function () {
  'use strict';

  // ── ① 顶栏时钟与问候 ───────────────────────────────────────────────────
  var WEEK = ['周日', '周一', '周二', '周三', '周四', '周五', '周六'];
  var dayEl = document.getElementById('clockDay');
  var timeEl = document.getElementById('clockTime');
  var helloEl = document.getElementById('helloLine');

  function pad(n) { return n < 10 ? '0' + n : String(n); }

  function greeting(hour) {
    if (hour < 5) return '夜深了';
    if (hour < 11) return '早上好';
    if (hour < 13) return '中午好';
    if (hour < 18) return '下午好';
    return '晚上好';
  }

  function paintClock() {
    var now = new Date();
    if (dayEl) dayEl.textContent = (now.getMonth() + 1) + '月' + now.getDate() + '日 · ' + WEEK[now.getDay()];
    if (timeEl) timeEl.textContent = pad(now.getHours()) + ':' + pad(now.getMinutes());
    if (helloEl) helloEl.textContent = greeting(now.getHours());
  }
  paintClock();
  window.setInterval(paintClock, 20000);

  // ── ② Focus Mode 那个圈 ────────────────────────────────────────────────
  //
  // 它不是第二个麦克风，它把点击原样交给 `#mic`。
  // `elder.js` 的注释写着：Voice Orb 只能有一个，两个 orb 的状态机会立刻分叉。
  // 而设计二的对话屏是围着一个圈画的，圈没了这一屏就散了。
  // 一个识别器、一份状态、两处呈现——环的形态由 `body[data-activity]` 在 CSS 里
  // 统一驱动，读屏用的那句话从 `#mic` 镜像过来（`setActivity()` 只写它那一个）。
  var mic = document.getElementById('mic');
  var focusMic = document.getElementById('focusMic');
  if (mic && focusMic) {
    focusMic.addEventListener('click', function () { mic.click(); });
    var mirrorLabel = function () {
      var label = mic.getAttribute('aria-label');
      if (label) focusMic.setAttribute('aria-label', label);
    };
    mirrorLabel();
    if (window.MutationObserver) {
      new MutationObserver(mirrorLabel).observe(mic, {
        attributes: true, attributeFilter: ['aria-label'],
      });
    }
  }

  // ── ③ 「我的」那两项：按钮组 ↔ 隐藏的 select ───────────────────────────
  //
  // 这是设计一与设计二**唯一一处真正的结构冲突**。`elder.js` 读的是
  // `#speechRate.value` / `#fontScale.value`，而设计二的控件是三个按钮。
  //
  // 施工图推荐让 `elder.js` 同时认两种形态。这一轮拿不到那个文件，所以走第三条：
  // 按钮组是屏幕上的控件，`<select>` 只当值的载体，两边在这里双向同步。
  // `elder.js` 一个字不用改，设计二的观感也保住了——而且下一套设计再来，
  // 加的仍然是它自己那一层适配，不用回去动共用逻辑。
  //
  // 反向那一半（服务端存的值写回按钮组）没有事件可听：`select.value = x` 是
  // 静默的，不派发 `change`。所以在**这两个实例上**把 `value` 的 setter 包一层。
  // 只包实例、不动原型，作用域就是这一页的这两个控件。
  var NATIVE_VALUE = Object.getOwnPropertyDescriptor(HTMLSelectElement.prototype, 'value');

  Array.prototype.forEach.call(
    document.querySelectorAll('.segmented[data-mirrors]'),
    function (group) {
      var select = document.getElementById(group.getAttribute('data-mirrors'));
      if (!select) return;
      var buttons = Array.prototype.slice.call(group.querySelectorAll('button[data-value]'));

      // 语音（「你说慢点」）能把语速调到三档之外，那时 `elder.js` 会往 select 里
      // 补一个 option、文字写成「我调过的语速」。按钮组要照实显示那一档，
      // 而不是三个按钮全部不高亮——那看起来像这一项没有设置过。
      function customChip() {
        var chip = group.querySelector('button[data-custom]');
        if (!chip) {
          chip = document.createElement('button');
          chip.type = 'button';
          chip.setAttribute('data-custom', 'true');
          group.appendChild(chip);
        }
        return chip;
      }

      function paint() {
        var now = String(select.value);
        var matched = false;
        buttons.forEach(function (button) {
          var on = button.getAttribute('data-value') === now;
          if (on) matched = true;
          button.classList.toggle('active', on);
          button.setAttribute('aria-pressed', on ? 'true' : 'false');
        });
        var chip = group.querySelector('button[data-custom]');
        var option = select.selectedOptions && select.selectedOptions[0];
        if (!matched && option) {
          chip = customChip();
          chip.setAttribute('data-value', now);
          chip.textContent = option.textContent;
          chip.hidden = false;
          chip.classList.add('active');
          chip.setAttribute('aria-pressed', 'true');
        } else if (chip) {
          chip.hidden = true;
          chip.classList.remove('active');
          chip.setAttribute('aria-pressed', 'false');
        }
      }

      group.addEventListener('click', function (event) {
        var button = event.target.closest('button[data-value]');
        if (!button || !group.contains(button)) return;
        select.value = button.getAttribute('data-value');
        // `elder.js` 监听的是 `change`：字号那一条当场重画整页，
        // 语速那一条记进它的本地副本，两者都要靠这一下。
        select.dispatchEvent(new Event('change', {bubbles: true}));
        paint();
      });

      select.addEventListener('change', paint);

      if (NATIVE_VALUE && NATIVE_VALUE.set) {
        try {
          Object.defineProperty(select, 'value', {
            configurable: true,
            enumerable: false,
            get: function () { return NATIVE_VALUE.get.call(this); },
            set: function (next) { NATIVE_VALUE.set.call(this, next); paint(); },
          });
        } catch (_) {
          // 拦不住就算了：点按那条路仍然通，只是服务端存的值不会回写到高亮上。
        }
      }

      paint();
    }
  );
})();
