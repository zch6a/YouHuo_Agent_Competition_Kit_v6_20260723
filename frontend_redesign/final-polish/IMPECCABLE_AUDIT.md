# Impeccable 审计（第一轮：机械检测器）

工具：`node .claude/skills/impeccable/scripts/detect.mjs --json <targets>`
范围：七个页面的 HTML + 四层 CSS

---

## 先说仪器本身：它第一次跑是残的

第一次运行它自己报了：

```
impeccable detect: DEGRADED - HTML parser modules unavailable
  (htmlparser2, css-select, css-tree, domutils).
Falling back to regex matching. Custom properties, selector matching and computed
contrast are NOT evaluated; findings are an undercount, not a clean bill of health.
```

**6 条**。装上那四个依赖（`npm install --no-save htmlparser2 css-select css-tree domutils`，
13 个包 3.6 MB）之后全强度重跑：**8 条**。

也就是说降级模式漏了 1/4。这个 skill 自己把这件事说清楚了（"an undercount, not a clean
bill of health"），值得记一笔：**它比很多闸门诚实**——它不是安静地少测，而是先声明自己
残了。如果它只是安静地报 6 条，我会当成审计通过。

---

## 八条逐个裁决

| # | 反模式 | 位置 | 裁决 |
|---|---|---|---|
| 1 | side-tab | `pages.css` `.next-item` | **Applicable · 已修** |
| 2 | gradient-text | `pages.css` `.score-ribbon strong` | **Applicable · 已修** |
| 3 | side-tab | `components.css` `.stage::before` | **Applicable · 已修** |
| 4 | side-tab | `components.css` `.reliance-card::before` | **Applicable · 已修** |
| 5 | side-tab | `pages.css` `.receipt-offchain` | **False Positive · 拒绝** |
| 6 | side-tab | `components.css` `.notice` | **Not Applicable · 拒绝** |
| 7 | em-dash-overuse | `stage.html` 16 处 | **Partially Applicable · 推到 Phase 3** |
| 8 | em-dash-overuse | `judge.html` 8 处 | **Partially Applicable · 推到 Phase 3** |

四条采纳、两条拒绝、两条延后。下面是每一条的理由。

---

### 1 · `.next-item` 的 4px 强调色左边 —— 采纳

```css
border-left: 4px solid var(--role-accent);   /* 删了 */
```

老人端首页唯一的卡片，而**这道线是我这一轮自己加的**。检测器的说法是
"the most recognizable tell of AI-generated UIs"，而它说得对：这张卡已经有 28px 等宽
数字的时间、22px 的标题、阴影和 1px 描边——彩色左边只是在同一件事上再喊一遍。
删掉之后它仍然是首页最重的东西，因为那是**内容**给的，不是装饰给的。

### 2 · `.score-ribbon strong` 的渐变文字 —— 采纳，而且它还是个无障碍的洞

原写法把渐变裁进 36px 的分数字形里，计算 `color` 是 `transparent`。而
`check_contrast.py` 里有这么一行：

```js
if (/rgba\(0, 0, 0, 0\)|transparent/.test(cs.color)) continue;
```

**整个对比度审计把这个数字跳过去了。** 所以这一处不只是 AI 签名，它还是一个让自己
逃出无障碍安全网的处理。改成实色 `--youhuo-blue-ink` 之后，它重新进入审计范围。

一个既是签名、又让自己不被检查的处理，没有留下的理由。

### 3 / 4 · 两个伪元素顶边条纹 —— 采纳，两个仪器指向同一处

`.stage::before`（3px）和 `.reliance-card::before`（4px），都是卡片顶边通长的彩色重线。

- Impeccable 判它们属于 side-tab 一族
- 而**之前那次逐像素视觉审查**独立地写过：「卡片顶边有一条通长蓝色横线…眯眼看第一眼
  落在这条线上，而不是落在麦克风按钮上」

两个方法互不相干却指向同一个元素，这比任何一个单独的判断都有力。判据不是"不好看"，
是**它不携带任何信息**：不表示状态、不表示分组、不表示进度，而它抢走了这一屏的第一
落点，那个位置属于麦克风。

**一个过程记录**：我先试过保留规则、只把 `content` 置成 `none`，想留住这个伪元素的
历史。结果检测器读的是声明本身、读不出"它不渲染"，那两条就**永久**留在报告里。
一份长期挂着两条已知误报的报告，下次真出问题时没人会注意到——所以真删，历史写进注释。

### 5 · `.receipt-offchain` 的 3px 中性左边 —— False Positive

```css
border-left: 3px solid var(--line-strong);
border-radius: 0 var(--r-md) var(--r-md) 0;
background: var(--surface-2);
```

这是**引文块**，不是卡片强调条：中性暖灰（`#d3cec3`）、右侧圆角、浅底——引述与旁注
的经典排版形态，任何文字密集的产品里都有。检测器自己的描述写的是"thick **colored**
border"，而中性色不是强调色。

它标记的这一段内容恰好是凭证里最重要的一句（「他说的原话不在链上」），把它降级成
普通段落会让那句话失去归属。**拒绝，不改。**

### 6 · `.notice` 的 4px 警示左边 —— Not Applicable

```css
border-left: 4px solid var(--warn);
background: var(--warn-bg);
```

三条理由：

1. **它不是卡片，是 alert/callout。** 左侧警示条是几十年的既有约定（Bootstrap alerts、
   GitHub 与 MDN 的 callout、各家文档的 admonition）。检测器那条规则的对象是卡片。
2. **它是第二条非颜色通道。** 这个项目有一条硬约束：颜色不能是唯一的区分通道。
   位置 + 粗度让色觉障碍用户也分得出这是一条警示。删掉它会**降低**无障碍水平。
3. 受众是视力在下降的老人，一条警示需要比常规产品更强的可辨识度。

**拒绝，不改。** 这是"skill 也可能给出不适用于老人端的建议"的一个实例。

### 7 / 8 · em-dash 过多 —— 部分适用，推到 Phase 3

`stage.html` 16 处、`judge.html` 8 处。

规则的**字符**依据在中文里不成立：`——` 是规范的中文标点，不是英文散文里那个
"LLM 写作痕迹"。但规则的**理由**成立：过度依赖同一个连接手段，而不是用句子结构说话。
16 处在一页里确实偏多，而且这是**我自己的写作习惯**。

两页都在手机框**外**（读者是评委不是老人），所以不紧急。放进 Phase 3
（Make Interfaces Feel Better 覆盖中文排版）一起处理，那时该用的是句读而不是破折号。

---

## 复跑

```
检测器：4 条
  [em-dash-overuse] stage.html:0   16 em-dashes in body text     → Phase 3
  [em-dash-overuse] judge.html:0    8 em-dashes in body text     → Phase 3
  [side-tab] pages.css:640          .receipt-offchain（中性引文块） → 拒绝
  [side-tab] components.css:254     .notice（警示左边）            → 拒绝
```

剩下的四条**每一条都有裁决记录**。这是这份报告的目标状态：不是 0 条，而是"没有一条
未经裁决"——一份长期挂着未裁决条目的报告会训练人忽略它。

`pytest` 1169 passed（+4 是 `test_release_hygiene` glob 全仓，skill 带进来两个 `.sh`）。

---

## 一处副作用，必须在打包前处理

装 skill 到项目目录带来 **8.2 MB**，其中 `impeccable/node_modules` 占 3.6 MB。
第 26 章要求 ZIP 里无 cache、无 pyc、无密钥、无数据库——`node_modules` 属于同一类。
已记进 `KNOWN_ISSUES.md`，Phase 7 打包时排除。
