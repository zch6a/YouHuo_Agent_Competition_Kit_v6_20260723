/* 优活 · 美术卡片层的挂载
   ============================================================================

   把 `data-art-shell` / `data-art-scene` / `data-art-seal` 变成真实 DOM 图层。

   ## 为什么是声明式的，不是选择器表

   交接包里的 `r7-art.js` 有一张 13 条的「CSS 选择器 → SVG 文件」硬编码表
   （`['.task', 'card_112.svg']` 这种）。它的失败方式是：页面结构一改，
   选择器对不上，**一张图都挂不上，而页面看起来完全正常**——
   这正是交接包 09 号文档列的第一条反例「素材复制进项目但看不见」。
   实测过：这个仓库的 `family.html` / `care.html` 里，那 13 个选择器
   只有 1 个还存在。

   所以挂载点写在 HTML 上。挂不上就是 HTML 里没写，改 HTML 的人看得见它。

   ## 它不改内容，只加图层

   每个挂载都是 `prepend` 一个 `aria-hidden` 的 `<img>`。不动既有节点、
   不改文本、不拦事件。业务 JS 往这些容器里 `innerHTML = ...` 的时候
   会把图层冲掉——所以有 MutationObserver 补挂。
   -------------------------------------------------------------------------- */
(() => {
  'use strict';

  const ART = '/static/art/';

  /* 场景意象的形状分类。决定它贴在卡片的哪一侧、占多大。
     取自各 SVG 的 viewBox 长宽比，不是拍脑袋：
       tall  高>宽    鹤 148×248、扇 170×286
       wide  宽>高    远山 237×91、锦鲤 246×207、卷轴 324×237、玉兰 458×278
       mark  近方形   莲 151×111、松 108×107、牡丹 186×189、月窗 239×240 */
  const SCENES = {
    bamboo              : ['scene/bamboo.svg', 'wide'],
    'bamboo-screen'     : ['scene/bamboo-screen.svg', 'tall'],
    'banner-tall'       : ['scene/banner-tall.svg', 'tall'],
    chrysanth           : ['scene/chrysanth.svg', 'mark'],
    cloud               : ['scene/cloud.svg', 'mark'],
    'cloud-stream'      : ['scene/cloud-stream.svg', 'mark'],
    crane               : ['scene/crane.svg', 'mark'],
    'g5-03'             : ['scene/g5-03.svg', 'wide'],
    'g5-04'             : ['scene/g5-04.svg', 'wide'],
    'g5-06'             : ['scene/g5-06.svg', 'wide'],
    'g7-06'             : ['scene/g7-06.svg', 'wide'],
    'g8-01'             : ['scene/g8-01.svg', 'tall'],
    'g8-02'             : ['scene/g8-02.svg', 'wide'],
    'g8-03'             : ['scene/g8-03.svg', 'wide'],
    'g8-04'             : ['scene/g8-04.svg', 'wide'],
    'jade-badge'        : ['scene/jade-badge.svg', 'wide'],
    koi                 : ['scene/koi.svg', 'tall'],
    'landscape-wide'    : ['scene/landscape-wide.svg', 'wide'],
    lotus               : ['scene/lotus.svg', 'mark'],
    'lotus-flourish'    : ['scene/lotus-flourish.svg', 'mark'],
    'lotus-vintage'     : ['scene/lotus-vintage.svg', 'mark'],
    maple               : ['scene/maple.svg', 'tall'],
    pavilion            : ['scene/pavilion.svg', 'mark'],
    peony               : ['scene/peony.svg', 'mark'],
    pine                : ['scene/pine.svg', 'tall'],
    'pine-crane'        : ['scene/pine-crane.svg', 'wide'],
    'plum-bar'          : ['scene/plum-bar.svg', 'wide'],
    'plum-drop'         : ['scene/plum-drop.svg', 'tall'],
    'portrait-scene'    : ['scene/portrait-scene.svg', 'tall'],
    'scroll-desk'       : ['scene/scroll-desk.svg', 'tall']
  };

  const SHELLS = {
    hero:     'shell/hero.svg',
    'wide-a': 'shell/wide-a.svg',
    'wide-b': 'shell/wide-b.svg'
  };

  function layer(src, className) {
    const img = document.createElement('img');
    img.className = className;
    img.src = ART + src;
    img.alt = '';                       // 装饰性图像：空 alt，不是没有 alt
    img.setAttribute('aria-hidden', 'true');
    img.setAttribute('role', 'presentation');
    img.decoding = 'async';
    // **必须 lazy。** 这些素材单张 2–7 MB，而挂载点里有相当一部分在
    // `hidden` 的分区里（老人端「记录」「家人」两格、家人端「我的」那一段）。
    // 不设 lazy 的话它们在首屏就全下：实测 `/elder` 一进来拉 10.09 MB，
    // 其中 6.96 MB 是两个还没打开的分区的。
    // 这个 worker 自己的注释写着目标是「移动数据下也能用」。
    img.loading = 'lazy';
    img.draggable = false;
    return img;
  }

  function mountShell(el) {
    const key = el.dataset.artShell;
    const src = SHELLS[key];
    // 写错名字要能看见。静默跳过的话，卡片变成一个没有边框的裸文本块，
    // 而那看起来像「这一版就是这么设计的」。
    if (!src) { console.warn('[art-cards] 未知卡壳：', key, el); return; }
    if (el.querySelector(':scope > .art-shell')) return;
    el.classList.add('art-card');
    el.prepend(layer(src, 'art-shell'));
  }

  function mountScene(el) {
    const key = el.dataset.artScene;
    const entry = SCENES[key];
    if (!entry) { console.warn('[art-cards] 未知意象：', key, el); return; }
    if (el.querySelector(':scope > .art-scene')) return;
    let [src, shape] = entry;
    // `mark` 形状渲成 44–56px 的小圆章，而源图是 1254×1254、单张 1–5.6 MB
    // 的「真矢量高清」。一张 5.6 MB 的画去画 44px，是三个数量级的浪费。
    //
    // 实测：`/care` 拉 18.28 MB 只为画六个圆章，`profile.html` 10.4 MB 画四个，
    // 而且图标会晚一拍才出现。
    //
    // 出了一份 128px 的 PNG（显示尺寸的 2.9 倍，视网膜够用），共 191 KB。
    // 矢量原件留着——`tall`/`wide` 那些大尺寸用途仍然用它。
    // 三种形状全部走小图。显示尺寸和源图尺寸差三个数量级：
    //   mark  显示 44–56px，源图 1254² 单张 1–5.6 MB
    //   wide  显示约 100px，源图 1900–2200px 宽
    //   tall  显示约 130px，源图 941×1672
    //
    // 实测：`/care` 拉 **18.28 MB** 只为画六个 44px 的圆章，`/elder` 10.09 MB，
    // 而且图标会晚一拍才出现。出小图之后 care 是 0.13 MB。
    //
    // 矢量原件留在 `art/scene/`——要改显示尺寸就重渲一遍，母版还在。
    src = 'icon/' + src.replace(/^scene\//, '').replace(/\.svg$/, '.png');
    el.classList.add('art-scene-host');
    // 形状同时写到宿主上：CSS 靠它给内容让出位置（padding-right 之类）。
    // 只给图层写的话，文字会压在画上。
    el.dataset.shapeHint = shape;
    const img = layer(src, 'art-scene');
    img.dataset.shape = shape;
    el.prepend(img);
  }

  /* 卡内景：`data-art-inlay="pine-crane"` → 设 `--art-inlay-src`。
     **不能写成内联 `style`**——这个仓库有严格 CSP，而且
     `test_no_inline_script_or_style_survives` 钉住这条。我第一版就是内联的，
     那道门当场红了两页。它是对的：内联样式一旦允许，CSP 的 `style-src 'self'`
     就得放宽，而放宽是不可逆的。 */
  function mountInlay(el) {
    const key = el.dataset.artInlay;
    const entry = SCENES[key];
    if (!entry) { console.warn('[art-cards] 未知卡内景：', key, el); return; }
    const png = 'icon/' + entry[0].replace(/^scene\//, '').replace(/\.svg$/, '.png');
    el.classList.add('art-inlay');
    el.style.setProperty('--art-inlay-src', `url(${ART}${png})`);
  }

  function mountSeal(el) {
    if (el.querySelector(':scope > .art-seal')) return;
    el.append(layer('ui/status-seal.svg', 'art-seal'));
  }

  const MOUNTS = [
    ['[data-art-shell]', mountShell],
    ['[data-art-scene]', mountScene],
    ['[data-art-inlay]', mountInlay],
    ['[data-art-seal="true"]', mountSeal]
  ];

  function scan(root) {
    if (!root || root.nodeType !== 1 && root !== document) return;
    for (const [selector, fn] of MOUNTS) {
      if (root !== document && root.matches?.(selector)) fn(root);
      root.querySelectorAll?.(selector).forEach(fn);
    }
  }

  function boot() {
    document.documentElement.classList.add('art-cards-ready');
    scan(document);

    // 业务 JS 重绘时会把图层冲掉。补挂。
    //
    // **要扫的是 `r.target`，不只是 `r.addedNodes`。** 第一版只扫新增节点，
    // 实测两处都没挂上：
    //
    //   · `care.js` 对 `#ovVerdict` 调 `replaceChildren(...)`——宿主本身没被
    //     重新插入，只是孩子换了。新增的是那些孩子，而带 `data-art-shell` 的
    //     是它们的**父节点**，`scan(child)` 既不 matches 也不 querySelectorAll
    //     到它。结果：主卡的卡壳和鹤一张都没有，而页面完全正常。
    //   · `trust.js` 在初次扫描之后才设 `dataset.artSeal`——那是**属性**变更，
    //     childList 根本看不见。一笔「已办好」的凭证上没有印章。
    //
    // 所以：childList 时连宿主一起扫，再单独订阅那三个属性。
    const observer = new MutationObserver((records) => {
      for (const r of records) {
        if (r.type === 'attributes') { scan(r.target); continue; }
        if (r.target && r.target.nodeType === 1) scan(r.target);
        r.addedNodes.forEach((n) => { if (n.nodeType === 1) scan(n); });
      }
    });
    observer.observe(document.body, {
      childList: true,
      subtree: true,
      attributes: true,
      attributeFilter: ['data-art-shell', 'data-art-scene', 'data-art-seal']
    });
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', boot, { once: true });
  } else {
    boot();
  }
})();
