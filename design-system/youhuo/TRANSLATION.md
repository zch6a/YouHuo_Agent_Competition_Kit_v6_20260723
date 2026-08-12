# ui-ux-pro-max 的产出，翻译到这个项目

`MASTER.md` 是 skill 原样写出来的，**没有改**——保留原文才能看出哪些被采纳、哪些被
拒绝。这一份记的是取舍。

> **`pages/desktop-console.md` 不存在，别去找它。** 第二次跑虽然带了 `--page
> "desktop-console"`，但 skill 的 `--persist` 在 `MASTER.md` 已存在时会**整个跳过写入**
> ——包括 page override——除非再加 `--force`。而 `--force` 会用桌面那套的值覆盖 MASTER，
> 那是错的方向。所以桌面那一套的输出只在终端里出现过，我把它记在下面第「桌面那套」一节，
> 没有落成文件。
>
> （这一段是补的：我第一版直接写了「`pages/desktop-console.md` 是 skill 写出来的」，
> 而那个文件根本没生成。一条指向不存在文件的说明比没有说明更糟。）

跑的命令（两次，对应大纲第 52 节要的两套密度）：

```bash
python "C:/Users/27943/.claude/skills/ui-ux-pro-max/scripts/search.py" \
  "senior friendly family care voice first life assistant trust safety consumer mobile healthcare adjacent" \
  --design-system --persist -p "YouHuo" --variance 2 --motion 2 --density 2 \
  --output-dir "F:\优活\YouHuo_Agent_Competition_Kit_v6_20260723"

python "…/search.py" "professional engineering console technical dashboard api monitoring precise dense" \
  --design-system --persist -p "YouHuo" --page "desktop-console" --variance 3 --motion 2 --density 8 …
```

技术栈：这个项目**没有 package.json、没有框架**。skill 明说 "Never assume a stack"，
而它的 22 个 stack 里没有"纯原生 CSS"这一档，最接近的 `html-tailwind` 仍然是 Tailwind。
所以它的代码示例一律要按 `.claude/skills/youhuo-ui-constraints/SKILL.md` 的六张表翻译。

---

## 采纳（直接可用）

### 配色

| 角色 | skill 给的 | 落到 tokens |
|---|---|---|
| Primary | `#0369A1` | `--youhuo-blue-deep`（冷静蓝，和现有主色同族） |
| Accent / Success | `#16A34A` | `--ok`（Muted Green，符合大纲第 39 节） |
| Destructive | `#DC2626` | `--bad`（Restrained Red） |
| Foreground | `#0C4A6E` | `--ink` 的深蓝方向 |

**它自己做了一次对比度调整**，原文注明：
`Accent adjusted from #22C55E for WCAG 3:1`。这条最有说服力——它不是随手给了个绿色。

### 交付前清单

七条和这个项目现有约束**完全一致**，一条不用改：无 emoji 当图标（用 SVG）、
悬停过渡 150–300ms、浅色文字对比 ≥4.5:1、焦点态可见、尊重 `prefers-reduced-motion`、
响应式多断点、可点元素要有指针样式。

唯一要补的：它列的断点是 375/768/1024/1440，**漏了 320**（iPhone SE）。这个项目
明确支持 320×568，而那里 `#chat` 高度实测已经是 0px——最紧的那一档它没有考虑。

---

## 采纳（翻译之后）

### 字体：Atkinson Hyperlegible —— 已落地

这是这次 skill 给出的**最有价值的一条**，我自己想不到：盲人协会（Braille Institute）
为低视力读者专门设计的字体，字形刻意加大 0/O、6/8、1/l 的区分度。
对一个目标用户"视力和记忆力都在下降"的应用，正中靶心。

但它给的引入方式是 Google Fonts 链接，**这个项目禁网络字体**。翻译：

- **自托管**：`backend/static/fonts/AtkinsonHyperlegible-{Regular,Bold}.woff2`
  （各约 23 KB，合计 47 KB，不是最初估的 200 KB），`tokens.css` 里两条 `@font-face`。
  CSP `default-src 'self'` 允许自托管字体——那条约束禁的是向外部域发请求，不是禁字体。
- **只给拉丁文与数字**：`unicode-range: U+0000-00FF, …`。这不是优化而是**必须**——
  这个字体没有汉字，不限区间的话浏览器会为每个汉字先来这里找字形，
  找不到再回退，而回退期间那些字不可见（FOIT）。一个为了让金额更清楚而加的字体，
  会让整页中文先闪一次白。
- 字体栈里排在**最前**（`"Atkinson Hyperlegible", "HarmonyOS Sans SC", …`）；
  因为有 `unicode-range`，汉字连请求都不会触发它。
- 闸门：`test_no_ai_slop_visuals.py::test_the_latin_font_is_range_limited`
  查四件事——有 `unicode-range`、有 `font-display`、区间不含汉字、
  文件真的在包里且是 `wOF2` 签名。变异测试：把区间改成 `U+4E00-9FFF` 会红。

### 动效

取时长与缓动：**300–400ms / `power1.out`**（≈ `cubic-bezier(.25,.46,.45,.94)`）。
**丢掉 GSAP**——它给的是 `gsap.from(...scrollTrigger...)`，而这个项目无第三方库、无 CDN。

---

## 拒绝（连同理由，免得下次又采纳）

### Pattern: Marketplace / Directory —— 完全跑偏

它给的是：「Search bar is the CTA」「Navbar 'List your item'」
「CTA (Become a host/seller)」「Sections: Hero (Search focused) → Categories →
Featured Listings → Trust/Safety → CTA」。

这是电商市场的模板。查询词里有 "consumer mobile"、"family care"、"healthcare
adjacent"，它挑中了 marketplace。**一次真实的误路由**，不是我提示写坏了。

第二次跑（桌面）给的 `Real-Time / Operations Landing` 方向对，可用作参考。

### Style: Exaggerated Minimalism —— 数值荒谬

它给：`font-size: clamp(3rem 10vw 12rem)`、`font-weight: 900`、
`letter-spacing: -0.05em`，`Best For: Fashion, architecture, luxury brands, editorial`。

- **12rem = 192px 的标题**放在 390px 宽的适老应用里没有意义
- **900 字重**和从参考仓库源码里量到的事实相反：两家主流框架的实际字重是
  400/500/600/700，**没有任何一家把所有标题写成 700**，MD 顶栏标题是 400
- `letter-spacing: -0.05em` 收紧字距，对低视力读者是反向的

只留一条：**negative space / massive whitespace**。那和大纲第 41 节
「优先留白、排版、divider，一屏 ≤3 张显著卡」是同一件事。

### 桌面那套把品牌色也换了

`pages/desktop-console.md` 给的 `Primary #0F172A`、`Background #020617`。
密度方向（8/10 Dense）对，深底方向也对，但**大纲第 52 节要求两套系统的颜色、字体、
图标、品牌保持同一家族**。所以只取密度与 `Border #334155` 这类中性层，
Primary 仍用 `#0369A1`。

**落地形态**：`tokens.css` 里一层 `[data-surface="platform"]`，里面**只有**
`--space-*`、`--text-*`、`--lh-*`、`--r-*` 四族。
`test_no_ai_slop_visuals.py::test_the_two_design_systems_share_the_brand` 用一条
白名单正则挡住其它任何令牌——往那一层里加一句 `--role-accent: …` 就红。

这条闸门存在的理由正是这一节记的这件事：「两套设计系统」最省力的做法就是复制一份
全量令牌再改颜色，而那样手机框里和框外会看起来像两个产品。

### `cursor-pointer`、`min-h-[44px]` 等 Tailwind 类名

翻译成普通 CSS。触控那一条尤其：它说 44px，**这个项目的下限是 48px，关键操作 56px**。
照它做会把标准降回去。

---

## 一句话

八个输出区里：**两个直接可用，两个翻译后可用，三个必须拒绝，一个（字体引入方式）
需要决定。** 它最大的价值不是给出方案，而是给出了一个我不知道的事实
（Atkinson Hyperlegible）和一次可验证的对比度修正。

它最大的风险是**默认答案看起来很专业**——`Exaggerated Minimalism` 配 `font-weight: 900`
读起来像一个设计师的判断，而它对这个产品是错的。这就是适配层存在的理由。
