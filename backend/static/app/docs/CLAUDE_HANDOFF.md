# CLAUDE / CODEX HANDOFF

先看：
1. `index.html`
2. `qc/art_asset_atlas.png`
3. `data/art_asset_manifest.json`
4. `docs/ART_QC_REPORT.md`

规则：
- `art/` 是视觉事实源，不用 Lucide/Heroicons 找相似图标替换。
- 山水在 HTML 中是实际 `<img class="scene">` 图层，不是 moodboard。
- 文字、金额、状态、按钮、列表必须 DOM 化。
- 复杂水彩不要自动 trace 成低质量 SVG path；`art/svg/` 是保持原像素的 SVG import wrapper。
- React/Vue 化时将 Card/List/Nav 组件化，将 `scene/art` 保留为装饰资源，将 `YouhuoAPI` 迁移到 service/query 层。

## 全局底栏是冻结 App Shell

不要再改回 4 栏。

全老人端统一：

1. 首页
2. 记录
3. 中央语音按钮
4. 服务
5. 我的

实现入口在 `assets/js/app.js -> mountGlobalNav()`。
视觉在 `assets/css/app.css -> .global-nav`。
中央原稿美术资产为 `art/png/nav_voice_control.png`。

## V3 强制规则

- Runtime 不使用 `art/svg/`。该目录已删除。
- 水墨资产只使用 `art/png` / `art/webp`，不要自动 trace。
- 服务图标必须使用 V3 的完整透明 PNG，不得换图库 icon。
- `service-card` 采用 flex + watercolor wash，不得再用 float。
- 全局底栏中心语音采用**不透明原稿 patch**，禁止改回透明抠图，否则页面 CTA 会穿透。
- `.phone` bottom safe area 固定不小于 188px。
