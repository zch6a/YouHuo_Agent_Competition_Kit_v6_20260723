# Runtime Art

V3 不再提供“PNG 套一个 SVG 标签”的假矢量资源。

- 水墨、竹林、亭阁、祥云、鹤、水花：PNG/WebP 才能保留原稿晕染。
- HTML 运行时只引用 `art/png/`。
- `art/webp/` 可用于生产环境压缩。
- 底栏普通线性 glyph 直接在 HTML/JS 中使用真正的 inline SVG。
- `art/reference_raw/` 保存裁切前的原始局部，便于 Claude/Codex 回查。
