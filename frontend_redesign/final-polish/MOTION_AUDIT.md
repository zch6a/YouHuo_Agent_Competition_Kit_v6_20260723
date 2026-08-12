# Phase 4 · 动效审计（Emil Design Engineering）

## 这一轮的完成度：一半

两条 lane 派出去，**Lane B（测量那一半）在跑到一半时撞上会话额度上限而中止**，
没有交回结果。所以这份报告的证据全部来自 Lane A（CSSOM + `getComputedStyle` +
`document.getAnimations()` 实测）与我自己的复验，**缺少的是**：
reduced-motion 下逐条动画时长是否真的塌到 0 的实测、十一态在关掉动效后的
逐态截图像素差、动效可打断性的实测。

这三件事没做 ≠ 通过。已记入 `POLISHING_STATE.md` 与本文件末尾。

Lane A 自己也标了一条边界：**浏览器面板不合成帧，它没有看到任何一帧真实渲染**，
所有结论来自计算值而非画面。凡需要人眼的它都标了置信度。

---

## 已实施（4 条，全部复验过）

### MO-04 · `data-activity` 被 `:hover` 压掉 —— P1，这一轮最重的一条

```
.mic-big:hover:not(:disabled)              (0,3,0)   ← .mic-big + :hover + :disabled
body[data-activity="speaking"] .mic-big    (0,2,1)
```

3 > 2，**hover 全胜**。后果是两个状态的唯一非动效通道在真实使用中不渲染：

- **speaking 的 12px 光晕整个消失，speaking 与 idle 像素相同**。而 speaking 是
  「我在说话，按一下会打断我」——分不清它和 idle，老人就会按下去打断优活自己的话，
  **那恰恰是 `elder.js` 开头那段注释写明要修的缺陷**。
- **pressed 的 scale(.94) + 内阴影在任何一次真实按压中都不出现**，实际看到的是
  `:active` 的 scale(.98)：116px → 113.7px，每边 1.15px。

触屏上躲不掉：没有 hover 的设备有 **sticky hover**——她点过一次麦克风之后
`:hover` 就一直挂着，直到点别处。

**修法**：给两条状态规则加 `:not(:disabled)` → (0,3,1)，压过 hover，不需要 `!important`。

**复验（真实浏览器，强制 `:hover`）**：

| 态 | 12px 光晕 | transform |
|---|---|---|
| idle | — | `1.04`（hover 抬起） |
| **speaking** | **在** | `1.01`（状态规则赢了） |
| **pressed** | — | **`0.94`**（设计的形态赢了） |

**我第一次的复验是废的，必须记下来**：第一版探针用 `Input.dispatchMouseEvent`
把指针移到 `#mic` 中心，然后报告「speaking 与 idle 仍然不同 ✓」。但同一张表里
**idle 悬停时 `transform: none`**——而 `.mic-big:hover` 明写 `scale(1.04)`。
也就是说 hover 根本没造出来，那份"验证"什么都没证明。
实测确认：`dispatchMouseEvent` 让 8 个祖先进了 `:hover`，唯独没有 `#mic`；
`CSS.forcePseudoState(['hover'])` 才管用。**造不出被测状态时，读到的一致
不是"通过"，是"没测"。**

**闸门也要跟着修（未做）**：`check_page_runtime.py::check_voice_orb_states` 是在
**没有指针悬停**的前提下逐个写 `data-activity` 再量的——它量到的是用户永远看不到的
那一版，修完之后也证明不了修好了。Lane A 建议给它加一步 `forcePseudoState`。
**这一条还没做**，进 Phase 6。

### MO-03 / MO-10 · 状态通道用了模式切换的令牌 —— P1

`.mic-dial::before/::after` 的 `border-color` 走 `--mode-fade` = **1000ms**。
而这条边框色**同时是十一态的主要通道**：processing 的单弧、executing 的双弧，
都靠 border-color 只留一边画出来。

后果：老人说完话，`ring-spin` 从第 0 毫秒开始转，而弧要**整整一秒**才从那圈 30%
的淡环里长出来——头一秒她看到的是一个几乎没变化的整圆在转，而整圆旋转在视觉上
等于静止。这个产品最核心的状态信号，被一个为身份 crossfade 定的令牌拖慢 5 倍。

`--mode-fade: 1s` 本身是规格（design §4.1，配语音播报），**不动它**；
改的是这两条状态通道 → `var(--dur-base)`（200ms）。`.role-halo` 的 `opacity`
同理（手机上它就是「我在听」那条信号），`box-shadow` 保留 1s（那才是换身份时变的）。

### MO-09 · `will-change` 永久提层，而我自己的注释说错了

`.role-halo::before/::after` 是两个 `position: fixed; inset: 0` 的全视口伪元素，
带**永久** `will-change: opacity`——不是"动画期间"，是页面整个生命周期。
而在 ≤760px 上它们的 `animation` 是 `none !important`：层被提出来，为的是一个
永远不会发生的动画。

**顺带纠正我自己**：我今天早些时候把 `#extrasSheet` 的 `will-change` 挪到
`.is-open` 上时，写了一句「全站只有这一处这么写」。**那句话当时就是错的**——
这里是第二处，而且更糟。我漏掉它是因为查 `will-change` 时遍历的是 DOM 元素，
而它挂在**伪元素**上，`getComputedStyle(el)` 根本看不见。注释已更正。

### MO-07 / MO-08 · JS 定时器不跟 reduced-motion 走 —— P2

模式切换是「加 `.switching`(opacity 0) → 500ms → JS 换文字 → 移除 class → 500ms 淡入」。
两个问题：

1. `500` 这个常量存在两份：`elder.js` 里是字面量，`components.css` 里是
   `calc(var(--mode-fade) * .5)`。改一边另一边静默漂移。
   **`sheet.js` 的注释点名了这个坑**（逐字：「这个项目已经因为『两处各写一份常量』
   吃过亏（`elder.js` 的 500ms 与 `--mode-fade`）」），它自己用"问 CSS"躲开了，
   而被点名的那一处一直没修。
2. 更要紧：`prefers-reduced-motion` 下 CSS 把过渡掐到 `.01ms`，而这个定时器
   **没有任何门控**——标题瞬间消失、**硬空白 500ms**、再瞬间出现。
   对开了「减少动态效果」的前庭失调用户，结果**比不做动效更糟**。

改成 `getComputedStyle(roleHeader).transitionDuration` 现读：过渡被掐到 0，
这里自动也是 0。

---

## 采纳诊断但未实施（需要人眼，推到 Phase 5）

### MO-05 · 全屏光晕在 ≥761px 照常脉冲

`halo-fade` 只在 `@media (max-width: 760px)` 里被关掉。而 `pages.css` 自己给出的
关闭理由是「填满周边视野，正是运动敏感所在」——**这条理由在大屏上更成立，不是更不成立**。
实测 1280×860：listening → `halo-fade 1900ms xInfinity`，processing → `3400ms xInfinity`。

**为什么不现在删**：`components.css:517` 明说「屏幕边缘的呼吸光晕」是区分两种模式的
三条通道之一。删掉之后要重跑灰度与色觉检查。Phase 5 连图一起做。

### MO-01 / MO-02 / MO-06 · 触屏几乎没有按压反馈

- 全站只有 **3 条** `:active` 规则，唯一覆盖 anchor 的是 `.tab:active svg`。
  落地页两个入口、老人端唯一出口 `.back-link`、`.button-link` 按下去**什么都不发生**。
  而 `base.css` 主动把 `-webkit-tap-highlight-color` 关成 `transparent`——
  系统自带那一下灰闪被删了、没有东西替上。注释写的理由（「按钮自己定义了按下态」）
  **对 `<a>` 不成立**。
- `button:active` 声明的 `transform: translateY(0)` **与基态完全相同，是空操作**；
  唯一真变化是 `filter: brightness(.96)`，实测自对比 **1.081:1**——远低于非文本 3:1。
  看得见的那一半（`translateY(-1px)` + 阴影）挂在 `:hover` 上，是桌面专属。
- 全站 **0 处** `@media (hover: hover) and (pointer: fine)`，四条会动东西的 hover
  在触屏上变成 sticky hover：点一下，按钮浮起 1px 并**一直保持**。
  旁证：`pages.css` 有两处 `:hover { transform: none }` 补丁——有人已经发现全局
  那条 lift 是错的，但选择了逐个打补丁而不是加门控。

**为什么不现在做**：`transform: scale()` 会让子元素一起缩，`.role-pick` 里有 56px 图标
加两行文字，缩 2% 期间文字会有一帧模糊。Lane A 自己标了「先在 375px 下看一眼」。
Phase 5。

### 其余推后

| ID | 内容 |
|---|---|
| MO-11 | `.tab` 颜色 200ms 过渡，而 3px 帽瞬时——同一状态两条通道错开 |
| MO-12 | 新消息同时跑 `bubble-in` 和 smooth scroll，携带同一条信息；删哪个需要 feel-check |
| MO-13 | `cubic-bezier(.2,.8,.3,1)` 出现 2 次，不在令牌里，与 `--ease-out` 语义重叠（skill：不许自创曲线） |
| MO-14 | 10 处硬编码时长（`.18s`×5、`.2s`×4、`.3s`×1），180/300 都不在 `--dur-*` 阶上 |
| MO-15/16 | `.back-link:hover` 的 `translateX(-2px)`、`.button-link:hover` 的 `translateY(-2px)` —— **答不上"为什么"**，建议删 |
| MO-17 | `.task` 过渡列表里的 `transform .18s`：**全站没有任何规则改它的 transform**，死声明 |
| MO-18 | `body::before` 三个 gradient 令牌全是 `transparent`（画不出像素），却带着 `blur(6px)` 和一条 1s 的透明→透明过渡 |
| MO-19/20 | `bubble-in` 320ms 超 300ms 线；`--dur-slow` 只 1 处消费，`--ease-in-out` 只服务 `halo-fade` |

---

## 判为 False Positive / 有意为之

| 项 | 裁决 |
|---|---|
| **`idle` orb 无限循环动画** | **规范已满足。** `data-activity="idle"` 下 `document.getAnimations()` 返回 `[]`（含伪元素，全局取）。计划书这条硬要求是真的做到了。 |
| `.tab:active svg { scale(.88) }` 幅度超建议 | **有意为之。** 注释说明了取舍（只动图标不动文字，避免"文字在拇指下移位=误触感"），而 0.95 的 24px 图标只变 0.6px，低视力用户看不见。 |
| keyframes 不可打断 | 六个 keyframes 全是**状态驱动的循环**，不是入场动画；状态一变规则不匹配、动画立即消失。sheet 拖拽是 transition + 拖拽期间 `transition: none` + `setPointerCapture` + 单向钳位——**全项目动效质量最高的一处**。 |
| 缺 reduced-motion | 有全局块。它比 skill 建议的更狠（skill 说 gentler not zero，这里是 zero），但项目据此把十一态**先做成静止形态**再叠动效，是有据可查的取舍。唯一例外是 MO-07 的 JS 定时器，已单列并修掉。 |
| `--ease-out` / `--ease-in-out` 曲线本身 | 不是自创：`.22,1,.36,1` 有完整来源论证，`.4,0,.2,1` 是 Material 标准曲线。**不建议换成 skill 的 `.23,1,.32,1`**——两者几乎重合，换了只是把一条有论证的曲线换成一条没论证的。 |
| `transition: all` | **0 处确认。** 计算值里有几处显示 `transition-property: all`，但 `transition-duration: 0s`——那是 CSS **初始值**，不是声明。 |

---

## Voice Orb 十一态：静止形态的人眼判断

Lane A 逐态取伪元素计算值，列出了十一态关掉动效后**真正长什么样**。闸门是绿的
（每两态确实不是同一张图），但人眼层面有两对不够：

1. **idle vs pressed**：环像素级相同，全部差别在 orb——而那份差别正是被 hover 压掉的
   那个（MO-04）。修完之后 pressed 真的是 scale(.94) 了。
   **顺带发现一处文案缺陷**：`pressed` 的提示写的是「松开手，我就开始听」，
   而 handler 挂在 `click` 上——触发时手**已经松开了**。这行字在告诉老人去做一件
   她刚做完的事。（不在动效范围，记入待办。）
2. **idle vs speaking**：环像素级相同，全部差别是那圈 12px 光晕——同上，已修。

做得最好的是 **success / error / offline** 三态：orb 靠 filter 分成提亮/压暗/降饱和
三个方向，环靠 6px 实心盘 / 4px 点线 / 1px 淡虚线，灰度下也成立。

**动效本身的必要性**：`ring-spin`（processing/executing）必要——一段弧在转是通用
spinner，「它在忙」没有同样清楚的静止表达。`ring-out`（listening）说得过去——
向外扩散的波与"声音进来"同构，是这套里唯一形状本身就在解释语义的。
`ring-breathe`（confirming）和 `orb-halo`（speaking）**可疑**：4px 双环与 12px 光晕
这两个静止形态已经承载了全部信息，呼吸只是让它"显得活着"——那属于被排除的理由。
两条都推到 Phase 5，删之前要确认灰度可辨性。

---

## 补测（Lane B 重派，三件事全部量完）

### ① reduced-motion 是真的生效 —— 这一次不是「声明了没生效」

自证先行：两轮 `matchMedia(...).matches` = False / True，两轮 `#mic:hover` 都 = False（无指针污染）。

7 条 `iterations: Infinity` 的循环动画，在 reduce 下**全部实测为 `0.01ms / 1 次`**；
十一态在 t+1.2s 时 `document.getAnimations()` **一律返回 0 条**
（关闭时 listening 2、confirming 2、processing/executing/speaking 各 1）。

三个量化前提，缺一个就会漏报成 0，值得记下来：
- `halo-fade` 在 390px 上**根本不存在**（`@media (max-width:760px)` 里
  `animation: none !important`），那两行是在 1440×900 重测的；
- `bubble-in` 在默认视图里进不了 `getAnimations()`（`.chat` 的 `offsetParent` 是 false），
  要先进 Focus Mode；
- 六个 keyframes 里五个挂在伪元素上，必须用 `document.getAnimations()` 全局取。

**唯一漏网的：`animation-delay` 没被覆盖。** `ring-out` 挂在 `.mic-dial::after` 上的
`.6s` 延迟在 reduce 下实测**仍是 600ms**——那条已被压成 0.01ms 的动画在 t+600ms 才发生。
视觉上几乎看不出，但这个块声称的是"动效关掉了"，而它没有完全关掉。**已补
`animation-delay: 0ms` 与 `transition-delay: 0ms`。**

### ② 十一态画面级两两差异：55 对，没有一对像素相同

reduce 开启、截图时刻运行中动画数为 0（画面确已停稳）、`#mic:hover` = False。
窗口 196×196（`#mic` 116 + 外扩 40），完整覆盖 156px 的环。

| 最接近的三对 | 差异像素 | 最大通道差 |
|---|---|---|
| processing vs executing | **3.04%** | 158 |
| idle vs processing | 5.78% | 150 |
| processing vs clarifying | 6.34% | 152 |

外扩到 296×296 交叉检查，排序完全一致。
这是**画面层面的上界补充**：它证实 `check_voice_orb_states` 的指纹下界没有放过任何一对。

### ③ 可打断性：三处都不会错乱，但原因各不相同

| 场景 | 结果 |
|---|---|
| 麦克风连点（第二下落在动画 53% 处） | `ring-out` 572 个采样点 **0 次回跳**，不重启 |
| 抽屉开→立刻关（96% 行程处打断） | 从 17.36px **平滑反向**到 484.45px，单帧最大位移与打开首帧同量级，`inert` 与焦点都正确恢复 |
| Tab 五连点（0/30/60/91/121ms） | 413 帧里「可见面板≠1 / `is-current`≠1 / `aria-current` 不一致」= **0 帧** |

但三处的原因不一样，第一条值得记：**麦克风是"设计上不重启"**——第二下走
`activity === 'listening'` 分支，`setActivity` 写回**同一个**值，不触发样式重算，
所以 CSS 动画天然不重启。代价是第二下**画面上零反馈，只有一行文字变**。

Lane B 还诚实地报了一次**自己没造出被测状态**：headless 没有麦克风，
`rec.onerror` 在 t=86.8ms 就把状态推到 `error`，而计划的第二次点击在 t=94.5ms
——它落在 `error` 上，不是落在动画中途。重做的办法是只补浏览器缺的那个 API
（`SpeechRecognition` 测试替身，按规范派发事件），页面自己的状态机一行不改。

顺带量到一个负面数字（无麦克风分支，**未修，也不作为结论**）：`error` 态下连点第二下，
3 秒内 activity / micHint / transform 三项全部零变化——因为 `setActivity('pressed')`
与 catch 里的 `setActivity('idle')` 在**同一个 task** 内先后执行，浏览器从未为 `pressed`
计算过样式。

### ④ `check_voice_orb_states` 加悬停维度 —— **已做**

见 `POLISHING_STATE.md`。变异（摘掉 `:not(:disabled)`）点名「idle 与 pressed」
「idle 与 speaking」，**且只在悬停那一遍**——旧的那一维仍然是绿的，这正是它需要被加的证据。
