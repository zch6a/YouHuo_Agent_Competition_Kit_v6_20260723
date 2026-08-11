# 移动外壳与排版参考

**这份文件是怎么来的**：从 `F:\优活\顶级前端仓库` 里 `framework7` 与
`ionic-framework` 两个仓库的**源码变量文件**逐个量出来的——它们是少数几个用原生
CSS 实现完整移动 App 外壳的成熟方案，和这个项目"无构建步骤"的约束最接近。
每条都带文件与行号。

---

## 一、真实的栏高（不是设计稿上的数字）

| | Framework7 iOS | Framework7 MD | Ionic iOS | Ionic MD |
|---|---|---|---|---|
| 顶栏 | **76px** | **64px** | **44px**（`min-height`） | **56px** |
| 大标题额外高度 | **52px** | **88px** | — | — |
| 底栏 / 标签栏 | 64px / **80px**（带图标） | 56px / **80px** | **50px** | **56px** |
| 二级栏 | 44px | 64px | 无此概念 | 无 |
| 搜索栏 | 44px | 48px | 60px | — |

安全区是**加上去**的，不是含在里面：

```less
/* framework7 navbar.less:26 */
height: calc(var(--f7-navbar-height) + var(--f7-safe-area-top));
/* toolbar.less:58 */
height: calc(var(--f7-toolbar-height) + var(--f7-safe-area-bottom));
```

**对照这个项目**：`--tabbar-h` 目前是 56px，加安全区。落在 Ionic MD（56）和
Framework7 iOS（64）之间，合理。标签文字 13px 也在两家的 10–12px 之上——适老场景
调大是对的，不是偏差。

---

## 二、大标题折叠：两种做法

**Framework7：一个 CSS 变量驱动全部**（`navbar\navbar.less:199-225`）

```less
--f7-navbar-large-collapse-progress: 0;   /* JS 写 0→1，CSS 全部用 calc() 消费 */

.navbar .title-large-text {
  transform: translate3d(0, calc(-1 * var(--progress) * var(--large-title-height)), 0);
}
.navbar-large .title { opacity: var(--progress); }
```

JS 只做一件事：算进度写变量（`navbar.js:329-410`）。小标题从 0.333 进度开始淡入
（`-0.5 + progress * 1.5`），大标题在 0.5 进度就消失（`1 - progress * 2`）——**两段
不重叠**，所以任何时刻只有一个标题在视觉上"负责"。吸附：过半滚到底（100ms），
不过半弹回（200ms）。

**Ionic：sticky + IntersectionObserver + JS 缩放**（`header.utils.ts`）

```js
const scale = clamp(1, 1 + -scrollTop / 500, 1.1);   // 回弹时大标题最多放大 1.1 倍
const fadeDuration = 10;                              // 10px 滚动就把顶栏底色淡入
```

**这个项目该抄哪个**：Framework7 那种"一个变量 + calc()"。它不需要
IntersectionObserver，JS 只写一个数，其余全在 CSS 里——和这个项目四层 CSS 的架构
完全对得上。而且**两段淡入淡出不重叠**这条，直接适用于老人端角色切换那个交叉淡入
（现在 `--mode-fade` 是 1s，JS 在 500ms 换内容）。

---

## 三、字号：px 还是 rem

**Framework7 = 100% px。** 全仓 `font-size: Nrem` 零命中，`em` 只有一处。
根 `--f7-font-size: 14px`，每个组件都是 px 字面量。代价：**完全不响应 iOS Dynamic
Type 和安卓字体缩放**。

**Ionic = 刻意混用**，这才是值得抄的：

```scss
$baselineSize: 16px;
@function dynamic-font($size)      { @return ($size / 16px) * 1rem; }
@function dynamic-font-max($size, $maxScale) { @return min(($size/16px)*1rem, $size * $maxScale); }
```

发出来的是**原生 CSS**，不需要运行时：

```
dynamic-font(26px)            → 1.625rem
dynamic-font-max(34px, 1.8)   → min(2.125rem, 61.2px)     ← 大标题，最多放大到 1.8 倍
dynamic-font-max(17px, 1.2)   → min(1.0625rem, 20.4px)    ← 普通标题，最多 1.2 倍
dynamic-font-clamp(1, 17px, 1.294) → clamp(17px, 1.0625rem, 21.998px)
```

三条规律：
1. **参与缩放的字号用 rem**，基线 16px。
2. **图标跟着父级文字走的用 em**（`--icon-font-size: 1.6em`），源码里专门注释了
   "why we use em here instead of rem"。
3. **刻意不缩放的留 px**——`$tab-button-ios-font-size: 10px`、
   `$searchbar-ios-cancel-button-font-size: 17px`（注释写着"iOS 上这个取消按钮不
   随 Dynamic Type 缩放"）。

**上限（`min()` / `clamp()`）是必需的**，因为两家的**所有**间距和栏高都是 px。
rem 字号在固定高度的栏里放大到某个点就会溢出——上限就是为这个存在的。

**对这个项目的直接结论**：R10 的实测是"46 处固定字号无令牌可用，因为
`--text-base` 起全是 `clamp()`"。Ionic 的做法给出了答案——**固定档与流体档可以共存**，
只要流体档带上限。可以补一组 `--text-fixed-*`（纯 rem，带 `min()` 上限）给正文用，
`clamp()` 那几档留给标题。这是一个真实可执行的下一步，不是"建议考虑"。

---

## 四、字重

两家实际用到的：`400 / 500 / 600 / 700`（Ionic 多一个 `450`，只在一处）。
**没有任何一家把所有标题写成 700。** iOS 顶栏标题 600、大标题 700；
MD 顶栏标题 **400**、大标题 **400**——MD 靠字号（22px vs 16px）而不是字重建立层级。

**这个项目现状**：R10 量到 91 处字号里大量 `font-weight: 800`。800 比两家用过的任何
值都重。这是一条可执行的收敛方向。

---

## 五、返回导航的时长

| | 前进 | 后退 | 缓动 |
|---|---|---|---|
| Framework7 | 400ms | 400ms（侧滑 300ms） | iOS 默认；MD `cubic-bezier(0, 0.8, 0.3, 1)` 且**只用一半时长** |
| Ionic iOS | **540ms** | 540ms | `cubic-bezier(0.32, 0.72, 0, 1)` |
| Ionic MD | 280ms | **200ms** | 前进 `cubic-bezier(0.36,0.66,0.04,1)`，后退 `cubic-bezier(0.47,0,0.745,0.715)` |

位移：iOS 进场 `translate3d(100%,0,0) → 0`，出场 `0 → -20%`（不是 -100%，
那是"下面那一层跟着走一点"的视差）。MD 只有 128px 进 / -24px 出。

**后退比前进快**（Ionic MD 200 vs 280）是一条普遍规律：回到已经看过的东西不需要
时间去理解。

---

## 六、侧滑返回的提交判据

| | 边缘区 | 激活阈值 | 提交条件 |
|---|---|---|---|
| Framework7 | 30px | 0 | 300ms 内位移 > 10px，**或** 位移 > 50% 宽度 |
| Ionic | 50px | 10px | 速度 ≥ 0.2 px/ms，**或** 位移 > 50% 宽度 |

两家都是"快划就认 / 慢划看距离"的二选一。50% 是共识。

---

## 七、这两个仓库里**不要抄**的东西

- **Framework7 完全不支持 OS 字体缩放**（全 px + `text-size-adjust: 100%`）。
- **Ionic 把 `text-size-adjust` 关得比 100% 更死**：`body { text-size-adjust: none }`
  （`structure.scss:80-82`）。安卓的字体大小设置因此被压制，只有 iOS 那条
  `-apple-system-body` 路径还活着。对一个适老产品，这是**反面教材**。
- **Ionic 的抽屉没有焦点陷阱**：全仓搜 `accessibilityViewIsModal` /
  `importantForAccessibility` 零命中，背景内容不被隐藏。这个项目的 `sheet.js` 在
  R12 已经补上了背后整体 `inert`，比它们做得对。
- **swiper 的无障碍播报形同虚设**：四个 `notify()` 调用点**全部**在键盘处理器里，
  拖拽、自动播放、点击分页点都不播报；用真 `<button>` 做导航时更是一次都不播。
