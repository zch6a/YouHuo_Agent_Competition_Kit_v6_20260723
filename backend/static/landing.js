'use strict';
/* 首页：记住上次选的身份，但不许因此把这一页**吞掉**。
 *
 * ## 记住是对的，替人做完决定不是
 *
 * 一位老人不该每次打开都重新回答「你是谁」，所以身份记在 localStorage——跨标签页、
 * 跨浏览器重启。这一条没有变，也不该变。
 *
 * 变的是它后面那一步。上一版在冷启动时直接 `location.replace(目的地)`：选过一次
 * 身份之后，**任何一个新标签页、任何一次浏览器重启**，打开 `/` 都会在第一帧之前
 * 落到 `/elder`。而这一页同时是四套界面的对照入口（`.yh-designs` 那四条，
 * 由 `test_landing_design_entries.py` 钉住）——它们从此在这台设备上等于不存在，
 * 而唯一的逃生口是一个没有任何地方写出来的 `/?stay=1`。
 *
 * 「记住」和「劫持」的分界线在这里：记住的是**答案**，不是**要不要问**。
 *
 * ## 三条备选，为什么是第三条
 *
 *   ① 把记忆从 localStorage 换成 sessionStorage。冷启动确实不跳了——而「冷启动」
 *      正是老人每天早上打开手机的那一次。它把「看不到入口」换成「每次都要重选」，
 *      两条判据里只过一条，另一条从满分掉到零。
 *   ② 只在从站外进入时跳、站内返回不跳。这一条**早就在了**（下面的 VISITED），
 *      而缺陷说的就是站外进入这一路。它一条都不解决。
 *   ③ 跳之前留一个看得见、够得着的出口。老人仍然零点击到达目的地，任何人都能在
 *      它走之前把它留下。两条判据同时成立，所以是这一条。
 *
 * ## HANDOFF_MS 是量出来的，不是拍的
 *
 * 判据：从「留在这一页」按钮**真的能按**（在文档流里、有尺寸、祖先链上的实际
 * 不透明度 ≥ 0.5、命中测试落在它自己身上）那一刻起，人还剩多少时间。CDP、一次性
 * profile、每档三次取最差，`/` 冷启动 390×844：
 *
 *      CPU 档   按钮可按 @        脚本执行起算剩余    第一帧起算剩余
 *      ------   --------------    ----------------    --------------
 *      1x        121 ms            3879 ms             4000 ms
 *      2x        162 ms            3838 ms             4000 ms
 *      4x        346 ms            3654 ms             4000 ms
 *      6x        441 ms            3559 ms             4000 ms
 *      10x       875 ms            3125 ms             4000 ms
 *      20x      2821 ms           **1179 ms**          4000 ms
 *
 * 1/6 那一档是这个仓库量便宜安卓机时一直用的（见 `landing.css` 里 `.yh-choose`
 * 上面那段事故记录）。目标是**最慢的机器上也留够 2 秒**给人读完并按下去。
 *
 * 两侧都量过之后才知道：4000ms 挂在脚本执行上，在 10x 和 20x 之间会掉到 2 秒以下
 * ——而慢机器上的人反应只会更慢，不会更快。所以表改成从**第一帧**开始走（见下面
 * `requestAnimationFrame` 那一段），这 4 秒于是变成「屏幕上的 4 秒」，最右一列在
 * 每一档上都是常数。这样 HANDOFF_MS 就不再是一个跟设备赌运气的数。
 *
 * 为什么不干脆放到 5000：老人这一路的代价就是这几秒。4000 已经在整个测得到的范围
 * 里留够两倍余量，再加一秒买不到任何东西。
 *
 * 倒计时**只在页面可见时走**（`document.hidden` 时那一拍直接跳过）。后台标签页里
 * 计时器照跳的话，中键点开一个 `/` 再切过去，看到的已经是 `/elder`——那正是这次要
 * 修的现象，只是换了个入口。实测：隐藏 6 秒不动，一变可见就继续走完。
 *
 * ## 判据**不能**用 `document.referrer`
 *
 * 第一版就是这么写的（referrer 为空或非本站 = 冷启动），而它从来没有生效过：
 * `api.py` 的 `_SECURITY_HEADERS` 对每一个响应下发 `Referrer-Policy: no-referrer`，
 * 于是 `document.referrer` 恒为空串，「冷启动」恒为真。后果是选过一次身份之后，
 * 六个页面上每一个「返回首页」链接、以及家人端和照护页标签栏里的「首页」，全部会
 * 被立刻弹回去——想从家属端换到老人端只能自己清网站数据。
 *
 * 现在的判据是「这个标签页此前有没有打开过本应用的任何内页」：`common.js` 在被加载
 * 时（也就是内页任意一个打开时）往 sessionStorage 写一个标记。冷启动时那个标记
 * 不存在，会话内返回时它一定存在。sessionStorage 是每标签页独立的，正好是「会话」
 * 这个语义，而且不受任何响应头影响。
 *
 * ## 关于 test_pwa_shell.py
 *
 * 那份文件里唯一提到 landing.js 的地方是
 * `test_every_manifest_shortcut_actually_does_something`：它把
 * elder/family/landing/common 四个脚本拼起来，查 manifest 快捷方式带的每个查询参数
 * 有没有人读。落在 landing.js 头上的**不是**这里的存储键名——那个键（`mode`）在
 * `elder.js:1430`。这个文件只是那堆干草里的一根，所以这次改动不需要动它。
 * 上一版这里的注释写着「两处都由 test_pwa_shell.py 钉住」，那句话是错的。
 */

(() => {
  //: 记住的身份。localStorage：跨标签页、跨重启，这是「不用每次重选」的全部来源。
  const KEY = 'youhuo_role_v1';
  //: 这个标签页打开过内页。由 `common.js` 写入，键名两边必须一致。
  const VISITED = 'youhuo_visited_v1';
  //: 这台设备按过「留在这一页」。localStorage，因为它要挡的正是**跨标签页**的冷启动。
  //:
  //: 为什么它必须能被撤销：一次误按会让老人从此每次都停在选择页。所以点身份卡
  //: （`.role-pick`）时把它清掉——挑一次身份是「下次直接带我去」最明确的表态。
  const STAY = 'youhuo_stay_v1';
  //: 自动打开前留给人的时间，毫秒。取值理由见文件头。
  const HANDOFF_MS = 4000;

  const DESTINATION = {elder: '/elder', family: '/family'};
  const WORD = {elder: '老人', family: '家人'};

  //: 存储访问一律包起来。Chrome 的「阻止所有网站数据」和没有 allow-same-origin 的
  //: sandbox iframe 里，连读 `window.localStorage` 这个属性本身都抛 SecurityError
  //: ——所以属性访问要在 try 里面，不能只包 `getItem`。
  function read(kind, key) {
    try { return window[kind].getItem(key); } catch (_) { return null; }
  }
  function write(kind, key, value) {
    try { window[kind].setItem(key, value); } catch (_) { /* 隐私模式 */ }
  }
  function drop(kind, key) {
    try { window[kind].removeItem(key); } catch (_) { /* 隐私模式 */ }
  }

  const params = new URLSearchParams(location.search);
  const stayParam = params.has('stay');

  const remembered = read('localStorage', KEY);
  const role = remembered && DESTINATION[remembered] ? remembered : null;
  const cameFromThisSite = !!read('sessionStorage', VISITED);
  const stayPinned = !!read('localStorage', STAY);

  //: 点身份卡：记住它，并撤销「留在这一页」。
  //:
  //: 这一段在最前面绑定，和下面那一整块**没有依赖**：不管这次跳不跳、banner 建不
  //: 建得出来，两张卡都必须能记住选择。上一版把它放在跳转判断之后，靠 `return`
  //: 跳过——那时它无所谓（反正立刻就走了），现在不是。
  document.querySelectorAll('.role-pick').forEach((link) => {
    link.addEventListener('click', () => {
      write('localStorage', KEY, link.dataset.role);
      drop('localStorage', STAY);
    });
  });

  if (!role) return;

  //: 「上次您用的是…」这句话仍然由 index.html 里那个 `#landingHint` 承担。
  //: 下面新建的那一条只说**接下来会发生什么**，两个元素各说一件事，不重复。
  const hint = document.getElementById('landingHint');
  if (hint) {
    hint.textContent = `上次您用的是「我是${WORD[role]}」。`;
    hint.hidden = false;
  }

  const main = document.querySelector('.landing-main');
  if (!main) return;

  //: 要不要自动打开。四个否决项各挡一路：
  //:   `?stay=1`          —— 手工逃生口，保留
  //:   已经按过「留在这一页」 —— 这台设备表过态
  //:   本标签页来过内页     —— 站内返回，不能把人弹回去
  const handOff = !stayParam && !stayPinned && !cameFromThisSite;

  //: 复用 `.yh-hint`（landing.css 里那条：`--surface-2` 底 + 一道橙色左边）。
  //: 不新造样式有两个理由：这次改的只有这一个文件（严格 CSP 也不许内联 style），
  //: 而且这一条要和页面本来的语气一致，不该长得像一个弹窗。
  const box = document.createElement('div');
  box.id = 'landingResume';
  box.className = 'yh-hint';
  //: 读屏软件要能知道这里冒出来了一句话。倒计时那一段是 `aria-hidden`——
  //: 一个每秒变一次的活区域会被逐秒念出来，那比不念更糟。
  box.setAttribute('role', 'status');
  box.dataset.handoff = handOff ? 'pending' : 'off';

  const say = document.createElement('span');
  say.id = 'landingResumeSay';
  const tick = document.createElement('span');
  tick.id = 'landingResumeTick';
  tick.setAttribute('aria-hidden', 'true');
  box.append(say, tick);

  //: 按钮行借 `.yh-designs-grid`：宽屏两列、≤520px 自动收成一列，间距和这一页
  //: 别的网格同一档。自己排两个 inline-block 的话，320px 上它们会挤成一行溢出去
  //: ——而「窄屏上够不着」正是这四个入口当初被单独立一条判据守着的那件事。
  const row = document.createElement('div');
  row.className = 'yh-designs-grid';

  const go = document.createElement('button');
  go.id = 'landingGo';
  go.type = 'button';
  go.textContent = handOff ? `现在就进入${WORD[role]}端` : `进入${WORD[role]}端`;
  go.addEventListener('click', () => leave());
  row.appendChild(go);

  let stayBtn = null;
  if (handOff) {
    stayBtn = document.createElement('button');
    stayBtn.id = 'landingStay';
    stayBtn.type = 'button';
    stayBtn.className = 'secondary';
    stayBtn.textContent = '留在这一页';
    stayBtn.addEventListener('click', () => {
      write('localStorage', STAY, '1');
      halt('好，以后打开这一页都会停在这里。');
      stayBtn.remove();
      go.textContent = `进入${WORD[role]}端`;
    });
    row.appendChild(stayBtn);
  }

  box.appendChild(row);
  main.prepend(box);

  if (!handOff) {
    say.textContent = `随时可以回到${WORD[role]}端。`;
    return;
  }

  //: 走人。用 `assign` 而不是 `replace`：`replace` 把 `/` 从历史里抹掉，于是一个
  //: 刚被自动带走的人连「后退」这条所有人都会的路都没有。`assign` 之后按后退回到
  //: `/`，而那时 `common.js` 已经写下 VISITED，这一页会安静地停住。
  function leave() {
    location.assign(DESTINATION[role]);
  }

  let left = Math.round(HANDOFF_MS / 1000);
  let timer = 0;
  let stopped = false;

  function render() {
    say.textContent = `这一页会自动为您打开${WORD[role]}端。`;
    tick.textContent = `（${left} 秒）`;
  }

  //: 停表。`word` 是停下来之后那句话——按钮停和自己停要说不同的话，
  //: 因为前者还额外记住了「以后都停」。
  function halt(word) {
    stopped = true;
    if (timer) { clearInterval(timer); timer = 0; }
    box.dataset.handoff = 'off';
    say.textContent = word;
    tick.textContent = '';
    for (const name of CANCELS) {
      window.removeEventListener(name, onActivity, LISTEN);
    }
  }

  //: 人一开始做事就停表。键盘尤其要收——读屏和纯键盘的人按 Tab 走到这里时，
  //: 倒计时必须先停下来，否则他还没读完这一行页面就换了。
  const CANCELS = ['keydown', 'wheel', 'touchmove', 'pointerdown'];
  const LISTEN = {capture: true, passive: true};
  function onActivity() {
    halt('已经停下了，不会自动打开。');
  }
  for (const name of CANCELS) {
    window.addEventListener(name, onActivity, LISTEN);
  }

  render();
  //: 表从**第一帧**开始走，不是从脚本执行开始。
  //:
  //: 差别在慢机器上是决定性的。实测「留在这一页」按钮从导航开始到真的按得下去：
  //: 正常 CPU 121ms，1/6 CPU 441ms，1/20 CPU **2821ms**（三次取最差）。挂在脚本
  //: 执行上的话，1/20 那一档 4 秒里有 2.8 秒人还看不见东西，出口只剩 1.2 秒——
  //: 而慢机器上的人反应也不会更快。挂在第一帧上，这 4 秒就是**屏幕上的 4 秒**，
  //: 跟机器快慢无关。
  requestAnimationFrame(() => {
    if (stopped) return;
    timer = setInterval(() => {
      //: 页面在后台就不走表。理由见文件头：后台标签页里照跳的话，中键点开一个 `/`
      //: 再切过去，看到的已经是内页——同一个缺陷换了个入口。
      if (document.hidden) return;
      left -= 1;
      if (left > 0) { render(); return; }
      clearInterval(timer);
      timer = 0;
      leave();
    }, 1000);
  });
})();
