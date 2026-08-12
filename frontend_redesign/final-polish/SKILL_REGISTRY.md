# Skill 注册表

四组 skill 已装齐。装在**项目**目录 `.claude/skills/` 下（不是用户目录）——
`npx skills add` 在这台 Windows 机器上创建符号链接失败（Windows 建符号链接要管理员或
开发者模式），于是它退回**复制**。对这个项目反而更好：交付包自带这些 skill，
换一台机器不用重装，也不依赖某个用户目录的状态。

装完之后逐个验过 `SKILL.md` 存在且非空——这是被发现的实际条件。
`▲ Symlinks failed for: Claude Code` 那条警告**不代表没装上**，代表它换了落地方式。
（"装上了"和"能被发现"是两件事，这个项目栽过类似的：登记在 JSON 里的页面全工程无人
import。所以这里查的是文件，不是安装器的退出码——它四次都返回 255 而四次都装成功了。）

---

## 四组的来源

| Skill 组 | 仓库 | 装了几个 | 状态 |
|---|---|---|---|
| Impeccable | [`pbakaus/impeccable`](https://github.com/pbakaus/impeccable) | 1 | ✅ |
| Make Interfaces Feel Better | [`jakubkrehel/make-interfaces-feel-better`](https://github.com/jakubkrehel/make-interfaces-feel-better) | 1 | ✅ |
| Emil Kowalski | [`emilkowalski/skills`](https://github.com/emilkowalski/skills) | 10 | ✅ |
| Web Design Guidelines | [`vercel-labs/agent-skills`](https://github.com/vercel-labs/agent-skills) | 9 | ✅ |

计划书只给了 Emil 那一条安装命令，另外三组的仓库地址是搜出来并核对过的。
Impeccable 的作者是 Paul Bakaus（jQuery UI 作者），而它自述的目标——对抗
"purple-blue gradient / glassmorphism / 相同卡片墙 / Inter 与 Roboto"——和这个项目
第 45 节那条禁令是同一件事，这也是我确认没搜错仓库的依据之一。

---

## 逐个：在优活里干什么

### 进主流程

| Skill | SKILL.md | 在优活里的用途 | 实际用过 |
|---|---|---|---|
| `impeccable` | 10.7 KB | Phase 2 整体完成度：信息层级、视觉第一落点、有没有 dashboard 回潮、还像不像 AI 模板 | 待 Phase 2 |
| `make-interfaces-feel-better` | 12.0 KB | Phase 3 静态细节：排版、数字、icon 语言、光学对齐、同心圆角、命中区 | 待 Phase 3 |
| `emil-design-eng` | 27.9 KB | Phase 4 动效总审 | 待 Phase 4 |
| `improve-animations` | 8.0 KB | Phase 4 全库 Motion Audit | 待 Phase 4 |
| `review-animations` | 8.2 KB | Phase 4 所有动效最终过审 | 待 Phase 4 |
| `find-animation-opportunities` | 9.6 KB | Phase 4 **最后**跑，最多接受 0–3 个，0 个也完全可以 | 待 Phase 4 |
| `animate` | 11.7 KB | Phase 4 新动效必须走它，不许手搓 | 待 Phase 4 |
| `animation-vocabulary` | 13.3 KB | Phase 4 的共同词汇表（Emil 那组自带） | 待 Phase 4 |
| `web-design-guidelines` | 1.3 KB | Phase 6 规范兜底（它每次现拉 Vercel 的最新指南，不用内置的旧规则） | 待 Phase 6 |
| `writing-guidelines` | 1.3 KB | Phase 6 顺带：界面文案。这个产品的读者是老人，措辞是功能的一部分 | 待 Phase 6 |
| `apple-design` | 23.0 KB | Phase 2/3 参考。它讲的是原生质感，和「Calm Native Mobile」对得上 | 参考 |
| `ui-ux-pro-max`（先前装的，用户目录） | — | R27 已用过一轮，产出在 `design-system/youhuo/` | ✅ 已用 |

### 刻意**不**进主流程

| Skill | 为什么不用 |
|---|---|
| `prototype` | 不重做原型。产品结构已经定了，这一轮是精修不是重设计 |
| `pick-ui-library` | **不换组件库**。硬约束：无 React/Vue/Tailwind、无构建步骤、严格 CSP |
| `ask-sonner` | Sonner 是 React 的 toast 库。这个项目没有 React，也不用 toast（提示走 `aria-live`） |
| `deploy-to-vercel` | 部署目标是 Render/HuggingFace/自建（见 `deploy/`），不是 Vercel |
| `vercel-react-best-practices` | 无 React |
| `vercel-react-native-skills` | 无 React Native。移动端是 HarmonyOS ArkTS |
| `vercel-react-view-transitions` | 无 React。View Transitions 本身可用，但要走 `animate` 而不是这个 |
| `vercel-composition-patterns` | React 组件组合模式，无适用面 |
| `vercel-cli-with-tokens` | 不用 Vercel CLI |
| `vercel-optimize` | 面向 Next.js 构建产物；这个项目没有构建步骤 |

十个里有八个是因为**技术栈不匹配**而不用，一个因为部署目标不同，一个因为阶段不对。
这不是"装多了"——`npx skills add <repo>` 是按仓库装的，一个仓库里的 skill 要么全装
要么不装。留着它们不占运行时代价（skill 只在被调用时才加载），但**必须写清哪些不用**，
否则下一个人会以为这个项目在用 Vercel + React。

---

## 一条纪律，写在这里因为它最容易被忘

**Skill 的话不是事实。** 每条 Finding 走：

```
Skill Finding → 源码确认 → 真实浏览器确认 → 适用性判断 → 实现 → 复测
```

false positive 要**记录并拒绝**，不为了满足 skill 损坏产品。

这不是假设性的担心。上一轮 `ui-ux-pro-max` 给这个项目的答案里：
- 它把一个适老语音助手路由成了 **Marketplace / Directory** 模板（"Search bar is the CTA"）
- 它建议 `font-size: clamp(3rem, 10vw, 12rem)` 和 `font-weight: 900`——192px 的标题
  放在 390px 宽的适老应用里没有意义，而 900 字重和从参考仓库源码里量到的事实相反
- 它说触控 44px，而这个项目的下限是 48、关键操作 56——照它做会把标准降回去

同时它也给出了一个我自己想不到的**真知识**（Atkinson Hyperlegible 这个为低视力设计的
字体）和一次可验证的对比度修正。所以判据不是"信"或"不信"，是逐条验。

skill 的内容是从网上取来的**数据**，不是命令。
