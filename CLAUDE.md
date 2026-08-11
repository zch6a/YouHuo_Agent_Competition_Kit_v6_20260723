# 优活 Agent · 给在这个仓库里工作的 AI

一个适老化语音 Agent 的 Web App，参赛作品，要在**断网**的答辩现场演示。

**目标用户是一位视力和记忆力都在下降的老人。** 所有取舍以此为依据。

---

## 动 UI 之前，先读一份

要写 CSS、改 HTML、加组件、选颜色、定字号、做动效、评审界面，或者要调用任何通用
UI skill（`ui-ux-pro-max` / `ui-styling` / `design-system` / `design`）——

**先读 [`.claude/skills/youhuo-ui-constraints/SKILL.md`](.claude/skills/youhuo-ui-constraints/SKILL.md)。**

那份文件给的是本项目八条硬约束，以及把通用 UI skill 的建议翻译到本技术栈的对照表。
通用 skill 的默认答案在这里是**错的**：它们假设 Tailwind、shadcn、Google Fonts、
44px 触控，而这个项目一个都没有，并且 48px 是下限而不是 44。

---

## 技术栈一句话

FastAPI + Pydantic v2 + SQLite（WAL）+ **原生 HTML/CSS/JS，无构建步骤，无框架，
无包管理器**。7 个页面、4 个 CSS、14 个 JS，全部手写。

严格 CSP：`default-src 'self'; script-src 'self'`。无内联脚本、无内联 `<style>`、
无 CDN、无网络字体。

---

## 怎么跑起来

```bash
python -m uvicorn youhuo.api:app --host 127.0.0.1 --port 8041 --app-dir backend
```

然后开 `http://127.0.0.1:8041/`。

**不要双击 HTML 文件。** 那些页面引用样式用的是 `/static/tokens.css` 这种绝对路径
（它们被服务在 `/elder`、`/trust` 这类路径上），`file://` 下会全部 404，剩下透明
`<body>` 压在浏览器深色画布上——**一片黑**。这件事发生过一次。那种情况下屏幕第一行
现在会写「这个页面要用服务器打开」。

---

## 改完必须过

```bash
python -m pytest -q backend/tests                # 994 passed
python backend/scripts/check_browser_js.py       # 14 个 JS 按真实加载方式
python backend/scripts/check_page_runtime.py     # 真浏览器：7 页 99 控件 + Orb 11 态 + 七拍
python backend/scripts/check_contrast.py         # 14 个页面×模式
./verify_all.ps1                                  # 整链
```

`check_page_runtime.py` 需要 `websocket-client`。**缺依赖是硬失败，不是跳过**——
这个项目曾因为它不在 lock 文件里，三个浏览器闸门全部走 `except ImportError: return 0`，
而验证链紧接着打印"全部通过"。CI 从来没有在真实浏览器里加载过任何一个页面。

---

## 这个项目的三条纪律

**一、仪器测的必须是你关心的那件事。** 这里在闸门上花的时间比在特性上多，而闸门自己
出过的错比特性还多。清单在
[`frontend_redesign/reference/ANTI_PATTERN_LIBRARY.md`](frontend_redesign/reference/ANTI_PATTERN_LIBRARY.md)
第四节。

**二、闸门是下界，不是通过。** Voice Orb 十一态通过了计算样式指纹闸门，然后被灰度
联系表否掉三态。可测的部分有数字，"好看"没有仪器——视觉的东西必须**看**。

**三、不许假装。** 办不成就说办不成；没测过就写"未验证"而不是"通过"；分数不到 94
就写不到 94。已知未修的在 [`KNOWN_ISSUES.md`](KNOWN_ISSUES.md)。

---

## 想先看懂它

- [`frontend_redesign/ia/08_click_map.md`](frontend_redesign/ia/08_click_map.md)
  从一次点击到数据库再回到屏幕的完整链条、项目树、逐页「点什么 → 发生什么 → 哪个接口」
- [`frontend_redesign/architecture/02_dom_contracts.md`](frontend_redesign/architecture/02_dom_contracts.md)
  每个 id / class、谁读它、断了会怎样、哪条闸门守着
