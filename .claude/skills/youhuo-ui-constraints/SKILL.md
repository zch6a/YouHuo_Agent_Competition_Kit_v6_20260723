---
name: youhuo-ui-constraints
description: 在优活 Agent 这个仓库里做任何 UI / UX / 视觉 / 样式 / 组件 / 配色 / 字体 / 动效 / 无障碍工作时必须先读。它给出本项目八条硬约束，以及把 ui-ux-pro-max、ui-styling、design-system 这类通用 UI skill 的建议翻译到本项目技术栈的对照表。凡是要写 CSS、改 HTML、加组件、选颜色、定字号、做动效、评审界面，或者要调用任何 UI skill，都先读这一份——通用 skill 的默认答案（Tailwind 类名、shadcn 组件、Google Fonts、44px 触控）在这个项目里是错的。
---

# 优活 · UI 约束与 skill 翻译层

通用 UI skill（`ui-ux-pro-max` / `ui-styling` / `design-system` / `design` / `brand` /
`slides` / `banner-design`）的知识是有用的，但它们的**默认答案假设一个这个项目没有的
技术栈**。照它们说的直接做，会同时破坏严格 CSP、无构建步骤和 48px 触控下限。

这一份的作用是：**先读约束，再取知识，翻译之后落地。**

---

## 一、这个项目是什么

一个适老化语音 Agent 的 Web App，参赛作品，要在**断网**的答辩现场演示。

**目标用户是一位视力和记忆力都在下降的老人。** 所有取舍以此为依据：她按不准小按钮、
读不了灰色小字、记不住四个选项，也不会因为界面漂亮而原谅它办错事。

技术栈：**FastAPI + 原生 HTML/CSS/JS，无构建步骤，无框架，无包管理器。**
7 个页面、4 个 CSS、14 个 JS，全部手写。

---

## 二、八条硬约束（破了就不用改了）

每一条后面都有一次真实事故，出处在
`frontend_redesign/reference/ANTI_PATTERN_LIBRARY.md`。

1. **严格 CSP 不许放宽。** `default-src 'self'; script-src 'self'`。
   无内联脚本（所以无 `onclick=`）、无内联 `<style>`（会被**静默**拦掉）、无 CDN、
   无网络字体。运行时注入样式只能用 constructable stylesheet
   （`new CSSStyleSheet()` + `adoptedStyleSheets`）。
2. **不迁技术栈，不加构建步骤。** 不要 React / Vue / Vite / Tailwind / PostCSS /
   打包器。CSP 能收这么紧正是因为没有打包器——大多数打包器默认注入内联 runtime。
3. **四层 CSS，加载顺序即层叠顺序**：`tokens → base → components → pages`。
   `pages.css` 里全部响应式覆盖**集中在文件最末尾**，因为媒体查询不增加特异性。
4. **DOM 契约（id / class）是契约**，同时被 JS 和 994 项测试消费。改名之前查
   `frontend_redesign/architecture/02_dom_contracts.md`；那张表里**没有闸门的几行最危险**。
5. **触控目标 ≥ 48×48。** 比 Apple 的 44 高，理由是目标用户手抖。
   `min-height` 对行内元素无效——`<a>` / `<summary>` 必须 `inline-flex`（栽过四次）。
6. **动效不能是唯一的区分通道。** 全局 `prefers-reduced-motion` 会把动画掐到 .01ms，
   所以每个状态必须先有一副**静止形态**。同理，颜色也不能是唯一通道。
7. **不用 emoji 当图标。** 全站内联 SVG + `currentColor`。emoji 只出现在真实用户内容里。
8. **界面上不许出现英文枚举值。** 四张翻译表守着这一条，且都**不保留原始码兜底**。

---

## 三、翻译表：skill 的答案 → 这个项目的写法

### 3.1 触控尺寸 —— **skill 的建议比这个项目的标准更松，不要采纳**

实测查询 `search.py "elderly accessibility large touch target low vision" --domain ux`
返回：

> **Do:** Minimum 44x44px touch targets　**Code Example Good:** `min-h-[44px] min-w-[44px]`

两处都要改：

| skill 说 | 这里写 |
|---|---|
| 44×44 | **48×48**，`components.css` 里 `a, button, input, textarea, select { min-height: 48px }` |
| `min-h-[44px]` | `min-height: 48px`（普通 CSS，不是 Tailwind 类名） |
| 间距 `gap-2` | `gap: var(--space-2)` |

### 3.2 Tailwind 类名 → 令牌

skill 的 `Code Example Good` 几乎全是 Tailwind 工具类。**本项目编译不了它们**，
必须翻译成 `tokens.css` 里的令牌：

| Tailwind | 这里 |
|---|---|
| `p-4` `gap-4` `m-4` | `var(--space-4)`（4px 网格，`--space-1`=4 到 `--space-16`=64） |
| `rounded-lg` | `var(--r-lg)`；圆角只有 `--r-md/lg/xl/2xl` 四档 |
| `shadow-md` | `var(--shadow-2)`（**四段式**，不是两段） |
| `text-sm` | `var(--text-sm)`（=15px）；`--text-base` 起是 `clamp()` |
| `dark:` 变体 | `@media (prefers-color-scheme: dark)` 里改**令牌**，不改组件 |
| `font-sans` + Google Font | **系统字体栈**。无网络字体，这是 CSP 约束 |
| `hidden` / `sr-only` | `hidden` 属性 / `inert` + `aria-hidden`（见约束 6 的注意事项） |

**四条纪律**：颜色字面量只允许出现在 `tokens.css`；间距落在 4px 网格上；
13px/15px 字号必须走令牌；阴影颜色不许写死。`test_design_rulers.py` 守着这四条，
写错会直接报红。

### 3.3 shadcn/ui 组件 → 本项目已有的组件

**不要 `npx shadcn@latest add`。** 没有 npm 依赖，没有 React。对照 `components.css`：

| shadcn | 这里 |
|---|---|
| `<Button>` | `<button>` + `.secondary` / `.danger` |
| `<Card>` | `.panel`（手机上老人端刻意**不是**卡片——三层同心圆角吃掉 41% 宽度） |
| `<Dialog>` / `<Sheet>` | `.rail.sheet` + `sheet.js`（手势 + `inert` + 焦点归还） |
| `<Tabs>` | `.segmented` + `.seg[data-section]` ↔ `.page-section[data-panel]` |
| `<Accordion>` | 原生 `<details>` / `<summary>` |
| `<Badge>` | `.pill` / `.badge` |
| `<Toast>` | `#status` / `.notice`（带 `aria-live`） |

### 3.4 动效 —— 取原则，不取库

skill 有 16 个 GSAP motion preset。**不要引入 GSAP**（无 CDN、无包管理器）。可取的是
时长与缓动，落到纯 CSS：

| 用途 | 时长 | 缓动 |
|---|---|---|
| 悬停 / 按下 | 180–200ms | `cubic-bezier(.2,.8,.3,1)` |
| 抽屉进出 | 350ms | `cubic-bezier(0.22, 1, 0.36, 1)` |
| 模式淡入淡出 | `var(--mode-fade)` | ease |

弹簧能不能写成 `cubic-bezier()` 只看阻尼比：**ζ ≥ 1（不过冲）才行**，过冲的要用
`linear()`（纯 CSS，无需库）。

### 3.5 配色 —— 可以取，但要落进令牌并过对比度

192 个 palette 可以查，但选定之后必须：

1. 写进 `tokens.css`，明暗两套；
2. 跑 `python backend/scripts/check_contrast.py`——14 个页面×模式组合，
   正文 4.5:1、大字 3:1、**非文本 3:1**（WCAG 1.4.11）、触控 48px；
3. 确认**颜色不是唯一通道**（约束 6）。

### 3.6 字体 —— 727 KB 的 google-fonts.csv 在这里只能当参考

**无网络字体。** 74 个字体配对里可迁移的是**配对原则**（衬线/无衬线的搭配关系、
字重层级），不是字体本身。skill 自带的 `ui-styling/canvas-fonts/*.ttf` 只能用于
**生成图片**（海报、mockup），**不能进页面**。

参考实现里量到的一条：两家主流框架的实际字重是 400/500/600/700，
**没有任何一家把所有标题写成 700**——MD 顶栏标题是 400，靠字号建立层级。

---

## 四、在这台机器上怎么调用这些 skill

装在用户级 `C:\Users\27943\.claude\skills\`，七个：`ui-ux-pro-max`、`ui-styling`、
`design-system`、`design`、`brand`、`slides`、`banner-design`。

**四个实测出来的坑**（驱动过一次，不是读文档得出的）：

1. **`python3` 在这台机器上不存在**，只有 `python`（`F:\Miniconda3\python.exe`）；
   `py` 也不存在。`design` 的 SKILL.md 写的是 `python3`。
2. **`~` 不会被 PowerShell 展开。** `python3 ~/.claude/skills/...` 双重失败。
   用绝对路径：`C:\Users\27943\.claude\skills\...`。
3. **`${CLAUDE_PLUGIN_ROOT}` 未设。** 按普通 skill（非 plugin）安装时它是空的，
   文档里的命令会解析成 `C:\.claude\skills\...` —— 文件不存在。
   已把 `ui-ux-pro-max/SKILL.md` 里 11 处改成真实路径。
4. **`.cjs` 脚本用相对路径**，必须先 `cd` 到 skill 目录再 `node scripts/xxx.cjs`。

核心查询（**实测可用**）：

```bash
python "C:\Users\27943\.claude\skills\ui-ux-pro-max\scripts\search.py" "<查询词>" --domain ux
```

`--domain` 取值**小写**：`style` `color` `chart` `landing` `product` `ux`
`typography` `icons` `gsap` `react` `web` `google-fonts`。

`--stack` 里最接近本项目的是 `html-tailwind`——**但它仍然是 Tailwind**，
拿到结果按第三节翻译。没有"纯原生 CSS"这个 stack。

### 部分不可用的两个 skill

`banner-design` 与 `design` 的部分流程引用了 **没有安装** 的 sibling skill：
`ai-artist`、`ai-multimodal`、`frontend-design`。它们在 skill 列表里看起来正常，
但那几条路径是断的。需要它们时先确认依赖装了没有——**"注册了"不等于"能跑"**。

---

## 五、改完必须过

```bash
python -m pytest -q backend/tests                # 994 passed
python backend/scripts/check_browser_js.py       # 14 个 JS 按真实加载方式
python backend/scripts/check_page_runtime.py     # 真浏览器：7 页 99 控件 + Orb 11 态 + 七拍
python backend/scripts/check_contrast.py         # 14 个页面×模式
```

**闸门是下界，不是通过。** Voice Orb 十一态通过了指纹闸门，然后被灰度联系表否掉三态
——`processing`/`executing`/`clarifying` 肉眼几乎一样，`pressed` 的环被 orb 整个挡住。
视觉的东西必须**看**，不能只读数字。

---

## 六、一句话

skill 的知识可以用，**skill 的默认答案不能直接用**。它假设的是一个有 npm、有打包器、
有 Tailwind、有 Google Fonts 的项目，而这个项目一个都没有——而且那不是欠账，是为了在
断网现场跑起来、并把 CSP 收到 `script-src 'self'` 而付的代价。
