# 重构前基线（实测，非估计）

重构开始之前跑一遍，作为"没有回归"的比较基准。日期 2026-08-10。

| 检查 | 结果 |
|---|---|
| `pytest backend/tests` | **950 passed, 1 skipped**（skip 是 `run_demo.ps1` 纯 ASCII 不需要 BOM） |
| `check_page_runtime.py` | 6 页加载干净 · 41 个控件逐个按过 · 手机视口无横向溢出 · 无障碍五项通过 · 无异常/无 console.error/无失败请求 |
| `check_contrast.py` | 12 个页面/模式全部满足 WCAG AA 与触控尺寸 |
| `check_browser_js.py` | 12 个文件解析通过 · 29 项朗读文本断言通过 |
| `verify_heavy` | 1,000,000 v5 断言 · 400 Saga 场景 · 5,000 并发请求 · 全部通过 |

## 前端资源基线

| 页面 | HTML | JS | CSS | 合计 |
|---|---|---|---|---|
| index | 11.4 KB | 0.6 | 89.1 | 101.1 KB |
| elder | 12.4 KB | 63.8 | 89.1 | 165.3 KB |
| family | 10.1 KB | 31.5 | 89.1 | 130.6 KB |
| care | 13.8 KB | 26.0 | 89.1 | 128.9 KB |
| trust | 8.5 KB | 22.0 | 89.1 | 119.5 KB |
| judge | 10.7 KB | 21.6 | 89.1 | 121.4 KB |

无网络字体、无框架、无大图。**性能不是需要解决的问题，是需要保持的状态。**

## 页面高度（390px 宽，重构前）

| 页面 | 整页高度 | 折算屏数 |
|---|---|---|
| index | 8574 px | 约 10 屏 |
| family | **11121 px** | **约 13 屏** |
| care | 2713 px | 3.2 屏 |
| judge | 2683 px | 3.2 屏 |
| trust | 2004 px | 2.4 屏 |
| elder | 一屏内（app-frame 钳位） | 1 |

## 截图

`frontend_audit/screenshots/before/` — 168 张，7 视口 × 明暗两模式 × 6 页 × （首屏 + 整页）。
