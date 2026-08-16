# 优活老人端 · QC 美术元素 + HTML + Backend Ready

这版不是整块截图拼 UI。

- `art/`：87 个经过 QC 的独立美术元素；
- `pages/`：10 个真实 DOM HTML；
- 山水、竹林、亭台、瀑布、祥云、仙鹤、水花已经实际进入 HTML scene layer；
- 金额、姓名、公司、时间、状态等全部 DOM 化；
- Mock/REST 双模式 API，可直接联调后端；
- `qc/art_asset_atlas.png` 可逐项检查抠图；
- `data/rejected_assets.json` 记录旧版裁歪/带字素材为什么被淘汰。

直接打开 `index.html`。

## v2 全局底栏修正

老人端所有页面统一使用同一个 5 槽 App Shell：

`首页 | 记录 | 中央语音 | 服务 | 我的`

- 中央语音按钮使用 `art/png/nav_voice_control.png`，来自原稿语音页底栏。
- 所有页面由 `mountGlobalNav()` 注入同一份导航，禁止页面自己再复制一套 nav。
- 中央语音从任意页面点击都会进入语音助手；语音页本身显示 listening 状态。
- 交易/确认/凭证等二级页面仍保留底栏，保证老人不会迷路。

## V3：针对实际截图问题的修复

请优先看：

- `qc/service_icons_fixed_v3.png`
- `qc/runtime_asset_atlas_v3.png`
- `docs/CHANGELOG_VISUAL_FIX_V3.md`
- `art/README.md`

这一版已停止使用有问题的 raster-backed SVG，HTML runtime 全部用审核后的 PNG/WebP。
