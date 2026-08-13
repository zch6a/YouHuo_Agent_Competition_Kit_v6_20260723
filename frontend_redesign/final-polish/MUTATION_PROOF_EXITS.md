# 变异证明：宽度感知的出口闸门

对象：`backend/scripts/check_exits.py`
日期：2026-08-14
方法：改 `backend/static/pages.css` 的字节 → 跑闸门 → 按字节还原（脚本里有
`assert CSS.read_bytes() == ORIGINAL`，还原失败就报）。

## 为什么需要这个闸门

`test_tabbar.py` 已有一条 `test_every_screen_has_some_way_out`，它的 docstring
自己写着它是「被一次真实的死路换来的」。但它查的是 **markup 里有没有**
`class="tabbar"` —— `family.html` 有，于是算「有出口」。

**它从不问这个出口在哪个宽度下可见。**

同一份 markup 在两个宽度下一个能走一个走不了，只有在浏览器里按宽度各量一次
才测得到。新闸门跑 7 条路由 × 5 个宽度（320×568 / 390×844 / 768×1024 /
900×1200 / 1440×900），每一格断言至少有一个**真的可用**的出口：
`checkVisibility()` 过、包围盒 ≥8px、不在 `[inert]` / `[aria-hidden]` 里、
没被平移出视口、可聚焦。

出口按**行为**认，不按 class：href 解析后 pathname 与当前页不同的锚点，加上
`#leaveApp`。量现状时发现 `/elder` 的四个 tab 全是页内 `#hash`，一个都不通向
别的路由 —— 旧判据注释里「elder 的出口是 4 个 tab」那句话本身是错的。

## 变异体

| | 变异 | 结果 | 期望 |
|---|---|---|---|
| 对照 | 未变异 | 绿 | 绿 |
| ① | 恢复 `.tabbar:not(.elder-tabs){display:none}`（真实事故那一条） | 绿 | **绿** |
| ② | `.elder-panel .fam-link { display: none }` | 红 `/elder` × 5 个宽度 | 红 |
| ③ | 出口缩到 6px（带 `!important`） | 红 `/stage` × 5 个宽度 | 红 |
| ④ | 同一条隐藏规则**只写在注释里** | 绿 | 绿 |
| ⑤ | `.tabbar:not(.elder-tabs), .segmented` 一起藏掉 | 红 `/family` `/care` × 5 | 红 |

### ① 为什么期望是绿，而这不是让步

单藏 `.tabbar` 之后 `/family` 的三个出口都落在 `mine` 面板里，而顶部那条
`.segmented` 还在、它有 `data-section="mine"` —— 一次页内点击就到得了。所以
**今天**它不是硬死路。当年那份事故报告只查了 `.tabbar` 和 `back-link`，漏掉了
`mine` 面板里的两个 `fam-link`。

⚠ **Phase C 要退役这条 `.segmented`。那一天这条规则就变成真死路** —— 接住它的
是变异体 ⑤，而 ⑤ 现在是红的。

### ⑤ 抓到了闸门自己的一个缺陷

第一版的「两步可达」只问「这一页有没有可见的页内切换控件」，不问那个控件
**能不能切到装着出口的那个面板**。于是 ⑤ 被误判成「两步可达」而放行。
加强后配对 `data-section`（切换器）↔ `data-panel`（面板）—— 这两个名字不一样，
是既有约定，猜成 `data-panel-target` 会一个都匹配不上。

「有一个开关」和「有一个能开这扇门的开关」不是一回事。

### 两个变异体一开始是我自己写错的

- 原 ②：`.elder-panel[data-panel="me"]{display:none}` → 绿，**而绿是对的**。
  那个面板本来就带 `[hidden]` 属性，追加 `display:none` 没改变判据看的
  `byAttr`，我造的根本不是我以为的条件。
- 原 ③：只缩 `.role-pick`（两个），而 `/` 还有 `/judge` `/stage` 两个裸链接，
  剩两个可用出口 → 绿是对的。改成 `body a[href^="/"]`（0,1,2）又输给首页那些
  两个类的选择器（0,2,0）。**期望本身错了，不是闸门漏了。**

变异体自己要先成立。一个挂在不存在的锚点上的变异体会安静地变成一个绿，而那个
绿看起来和「闸门抓住了」一模一样 —— 所以脚本开头有锚点自检（`.segmented` /
`.fam-link` / index 的出口链接必须存在），第一版的锚点正则用了 `\n` 而
`pages.css` 是 CRLF，它 assert 出来了。

## 一个没查清的事实

加了 `!important` 之后，其他页面的 `.tab` 确实变成 `6×56`，但 `/` 上那两个
`.role-pick` 尺寸不变（`index.html` 的四个 `<link>` 都在）。原因未定。
记在这里和闸门的 docstring 里，**不写成「首页很健壮」** —— 它是一个未解事实，
不是一个结论。

## 闸门当前的两档 KNOWN（不算通过，也不算失败）

    5 处出口要先切一次页内分区才露出来      /elder × 5 个宽度（出口在「我的」里）
    5 处出口在首屏之外                      /stage × 4，/family @ 1440

第二档是 Phase C 要修的东西：宽屏下那条静态导航排在 `<main>` 的最后一个孩子，
`/elder` y=1635（文档 1748）、`/family` y=1008（1129）、`/care` y=1012（1125）。

把它算成 PASS 是伪造；算成 FAIL 会让这个闸门从落地那天起就是红的，没人会再看它。
所以如实打印。
