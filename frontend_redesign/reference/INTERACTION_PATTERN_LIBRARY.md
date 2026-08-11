# 交互模式参考：动效、手势、抽屉

**这份文件是怎么来的**：从 `F:\优活\顶级前端仓库` 里四个仓库的**源码**逐行量出来的
——`rn-bottom-sheet`（gorhom）、`motion`（Framer Motion）、`swiper`、`lenis`。
每条都带文件与行号。没有一条来自记忆或二手文章。

**这个项目能用什么**：无构建步骤、原生 CSS/JS、严格 CSP（无内联样式，但
`element.style.setProperty()` 与 `element.animate()` 不受 `style-src` 约束）。
所以下面的结论都翻译成了 `cubic-bezier()` / `linear()` 字符串或几行原生 JS。

---

## 一、弹簧曲线怎么翻译成 CSS

判据只有一条：**阻尼比 ζ ≥ 1（不过冲）的弹簧才能写成 `cubic-bezier()`**。
CSS 的 bezier 端点被钉在 0 和 1，做不出"冲过去再回来"。过冲的弹簧要用 `linear()`。

| 来源 | CSS 写法 | 最大误差 | 说明 |
|---|---|---|---|
| rn-bottom-sheet iOS 抽屉（`500/1000/3`） | `350ms cubic-bezier(0.22, 1, 0.36, 1)` | — | ζ=4.56 严重过阻尼。数学上 99% 要 2280ms，但 349ms 就走完 50%，剩下的一秒多在挪另外 50% 且**看不见**。截到可感知的那一段、把尾巴收陡，才是诚实的翻译 |
| rn-bottom-sheet Android（`250ms Easing.out(Easing.exp)`） | `250ms cubic-bezier(0.15, 1, 0.316, 0.997)` | 0.003 | 精确拟合 `1 − 2^(−10t)` |
| motion 默认补间 | `300ms cubic-bezier(0.25, 0.1, 0.35, 1)` | 0 | 本来就是 bezier，直接用 |
| motion 布局补间 | `450ms cubic-bezier(0.4, 0, 0.1, 1)` | 0 | 本来就是 bezier |
| lenis 默认缓动 | `cubic-bezier(0.15, 1, 0.317, 0.998)` | 0.004 | 同一条指数曲线 |
| motion transform 默认弹簧（`500/25`） | **不能**用 bezier，ζ=0.559，峰值 1.120 | — | 要 `linear()` |
| motion 物理默认（`100/10`） | **不能**，ζ=0.500，峰值 1.163 | — | 要 `linear()` |

`linear()` 是纯 CSS，不需要任何库（Chrome 113+ / Safari 17.4+ / Firefox 112+）。
生成方法就 16 行：每 10ms 采样一次弹簧，保留四位小数。

**时长锚点**（源码里的默认值，没有任何一个仓库写了"按元素大小选时长"的指南）：
250ms 抽屉移动 · 300ms 非 transform 补间与轮播 · 450ms 布局重排 ·
约 230ms transform 弹簧的视觉时长。位移越大时长越长，但**尾巴要更平**——
iOS 那条弹簧就是这么干的（6ms 快根 + 494ms 慢根）。

---

## 二、`prefers-reduced-motion`：最值得抄的一条

motion 的做法是**按属性分类**（`render\utils\keys-position.ts`）：

```
positionalKeys = width, height, top, left, right, bottom,
                 x, y, z, translateX/Y/Z, scale, scaleX/Y, rotate, rotateX/Y/Z, skew…
```

减弱动效时**只杀这些**——`opacity`、颜色、`filter` 照常动。

```css
@media (prefers-reduced-motion: reduce) {
  /* 杀掉位移/尺寸/缩放，保留透明度与颜色 */
  .sheet { transition-property: opacity; }
}
```

**不要一刀切全关**。rn-bottom-sheet 在 `animate.ts:32-35` 留了一行注释加一行注释掉的
代码：他们照做 reduce-motion 之后**抽屉根本不出现了**。减弱不等于取消——终态必须
仍然是可见的。

四个仓库的实际支持情况，供判断可信度：

| 仓库 | 支持 | 备注 |
|---|---|---|
| lenis | ✅ 默认开 | 但它是**降级不是关闭**：仍 `preventDefault`、rAF 仍跑，`lerp=1` 实际每帧仍留 37% 误差 |
| rn-bottom-sheet | ✅ 有 | 只用于防一个状态错位，不是真的减弱 |
| motion | ⚠️ 默认**关** | 要显式 `reducedMotion="user"` |
| swiper | ❌ 完全没有 | 全仓 313 个文件零匹配 |

---

## 三、手势：什么时候算"划过去了"

三种判据，各有代价：

**swiper（时长分档 + 距离比例，无速度）** `onTouchEnd.ts`
```
时长 > 300ms  → 看距离：走过 50% 才翻页，否则弹回
时长 ≤ 300ms  → 距离**完全不看**，一律翻一页
```

**rn-bottom-sheet（速度投影 + 最近吸附点）** `utilities\snapPoint.ts`
```js
const point = value + 0.2 * velocity;   // 投影 200ms 之后会到哪
// 然后选离 point 最近的吸附点
```
没有阈值这个概念——"关闭"只是把关闭位置也放进候选数组。

**Ionic 侧滑返回** `swipe-back.ts`
```
边缘 50px 内起手 · 移动 10px 才激活 · 速度 ≥ 0.2 px/ms **或** 位移 > 50% 宽度 → 提交
剩余距离按 min(距离/速度, 540ms) 补完
```

**这个项目该用哪个**：抽屉只有开/关两态，速度投影是过度设计。swiper 那套"快划就认、
慢划看距离"更适合——而且它不需要采样速度。

---

## 四、两个细节，直接可抄

**1. 阈值要"重锚"，不能只做门槛**（swiper `onTouchMove.ts:346-362`）

越过 5px 阈值的**第一帧**要把起点重设到当前位置然后 `return`，不要移动。否则手指刚
过阈值，元素就"跳"了 5px。这是"抓起来就跳一下"和"跟手"之间的全部区别。

**2. 越界阻尼是次线性曲线，不是硬夹**

| 来源 | 公式 | 100px 手指位移 → |
|---|---|---|
| rn-bottom-sheet | `√(1 + 越界) × 2.5` | 25px |
| swiper | `越界 ** 0.85` | 50px |

两者都必须在 `pointermove` 里用 JS 算并直接写 `transform`——那是直接操纵，不是过渡，
所以不违反"不引入动画库"。

---

## 五、这个项目做不到的事（不要承诺）

1. **速度感知的落位**。CSS 过渡永远从零速度开始。可以用 JS 算出速度去**选**不同的
   时长或目标，但做不到"以手指离开时的速度继续"。
2. **飞行中被打断还保住速度**。抓住一个正在回落的抽屉再甩出去，CSS 会跳到当前值、
   从零速度重来，肉眼看得见断点。
3. **目标会变的真弹簧**。`linear()` 烘的是固定距离的固定曲线。
4. **嵌套 FLIP 加圆角/阴影的缩放补偿**。单元素 FLIP 用 WAAPI 可以；motion 那套
   深度排序投影树不行。

---

## 六、一条 CSP 提醒

`element.animate()` 和 `el.style.transform = …` **不受** `style-src` 约束（那管的是
`<style>` 标签、`style=""` 属性和样式表）。但如果为了存放生成的 `linear()` 字符串去用
`CSSStyleSheet.insertRule` 或注入 `<style>`，就需要 nonce——motion 专门为此留了
`nonce` 配置项。**优先用 `el.style.setProperty()` 写自定义属性**，那条路是干净的。
