"""老人调大的字号，**每一页都要跟着**。

## 为什么需要这条

设置页能把「最大」存进后端，也能当场把自己那一屏放大。但那之前
`app.css` 里 `--fs` 出现 **0 次**——其余十六页一个字都不会变大。
交付它的 agent 自己写清楚了：「字号只在我这两页生效」。

**一个只在设置页生效的字号设置，比没有这个设置更糟。** 老人在那一页看到字变大了，
以为调好了，回到首页发现还是原样——他会以为是自己没按对。

改法是把所有写死的 `font-size:Npx` 换成 `calc(Npx * var(--fs, 1))`，
共 72 处（app.css 17 + 十七个页面内联 55）。`--fs` 由 `app.js` 的 `hydrate()`
读 `GET /settings` 后设在 `<html>` 上。

## 这条判据守的是「以后新写的也得跟着」

72 处是一次性的机械转换；真正的风险是**明天谁再加一处写死的 `font-size:18px`**——
那一处从此不跟随，而且屏幕上看不出来（除非有人恰好把字号调到最大再去看那一页）。

验证过转换是无损的：`--fs=1` 时 `calc(19px * 1) === 19px`，九个页面逐像素比对，
五页完全一致，另外四页的差异逐个裁图确认是**别的**故意改动
（底部导航高亮、记录条数、设置页的「存过没存过」状态），没有一处是字号。
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
APP = ROOT / "backend" / "static" / "app"
CSS = APP / "assets" / "css" / "app.css"
PAGES = sorted((APP / "pages").glob("*.html"))

#: 写死的 `font-size: 18px`。已经写成 `calc(...)` 的不会命中。
_HARD_PX = re.compile(r"font-size\s*:\s*\d+(?:\.\d+)?px")
#: 跟随字号的写法。
_SCALED = re.compile(r"font-size\s*:\s*calc\([^)]*var\(\s*--fs")


def test_the_instrument_reads_something() -> None:
    """先证明这条判据看得见字号。

    正则写错、或者文件路径变了，下面两条会**全部通过**——而通过的原因是
    一处字号都没读到。这个项目为这个形状付过多次代价。
    """
    assert CSS.is_file(), f"{CSS} 不在——这条判据失去依据"
    assert len(PAGES) >= 15, f"只找到 {len(PAGES)} 个页面"
    scaled = len(_SCALED.findall(CSS.read_text(encoding="utf-8")))
    assert scaled >= 10, f"app.css 里只读到 {scaled} 处跟随字号，正则大概没匹配上"
    total = sum(len(_SCALED.findall(p.read_text(encoding="utf-8"))) for p in PAGES)
    assert total >= 30, f"十七个页面里只读到 {total} 处跟随字号"


def test_app_css_has_no_hardcoded_font_size() -> None:
    src = CSS.read_text(encoding="utf-8")
    hard = _HARD_PX.findall(src)
    assert not hard, (
        f"app.css 里还有 {len(hard)} 处写死的字号：{hard[:8]}\n"
        "老人把字号调到最大时，这些字不会跟着变。"
        "写成 `calc(Npx * var(--fs, 1))`。"
    )


@pytest.mark.parametrize("page", PAGES, ids=lambda p: p.name)
def test_this_page_has_no_hardcoded_font_size(page: Path) -> None:
    hard = _HARD_PX.findall(page.read_text(encoding="utf-8"))
    assert not hard, (
        f"{page.name} 的内联样式里还有 {len(hard)} 处写死的字号：{hard[:8]}\n"
        "写成 `calc(Npx * var(--fs, 1))`——否则这一页在最大档下不跟随。"
    )


def test_app_js_actually_applies_the_saved_scale() -> None:
    """光把 CSS 写成 calc 不够：得有人去读那个偏好并设 `--fs`。

    两件事分开测，因为它们会**分别**失效：CSS 全改成 calc 而没人设 `--fs`，
    则一切照旧（`var(--fs, 1)` 兜底成 1），屏幕上完全看不出来。
    """
    src = (APP / "assets" / "js" / "app.js").read_text(encoding="utf-8")
    assert '"/settings"' in src, "app.js 没有去读 `/settings`，存下来的偏好没人用"
    assert '--fs' in src, "app.js 没有设 `--fs`"
    assert "documentElement" in src, (
        "`--fs` 必须设在 `<html>` 上：`.modal` 是 position:fixed 且挂在 `.phone` "
        "外面，设在 `.phone` 上它够不着"
    )
