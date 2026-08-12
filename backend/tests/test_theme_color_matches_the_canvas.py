"""状态栏的颜色必须就是页面画布的颜色。

装到主屏之后，`theme-color` 决定的是系统状态栏那一条。它和 `--bg` 只要不是同一个值，
接缝就在页面最上沿，横贯整个屏幕宽度——而这恰恰是 `tokens.css` 换暖色那一段注释
花了整段篇幅要消灭的东西。

实际发生的：六个页面的 `theme-color` 一直停在换色**之前**的冷蓝
（`#f4f6fb` / `#0b1020`），而画布早已经是暖白暖黑（`#f7f6f3` / `#0f0e0c`）。
色偏（R−B）：冷蓝 −7 / −21，暖色 +4 / +3——冷暖是反的，不是差一点点。

没有任何闸门看得见它：`<meta>` 不参与渲染，对比度审计不读它，截图也拍不到状态栏。
它只在真机装到桌面之后才显形，而那时候已经在评委手上了。

所以判据钉在**令牌**上，不钉在一个抄下来的十六进制值上：`--bg` 改了，这条会红。
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
STATIC = ROOT / "backend" / "static"
TOKENS = (STATIC / "tokens.css").read_text(encoding="utf-8")

#: 只有**装得上主屏**的页面才有状态栏可谈。
#:
#: 判据是这一页自己有没有 `<link rel="manifest">`，不是一张手写名单——名单会漂。
#: `stage.html` 因此不在内：它刻意不注册 service worker、不引 manifest、不给
#: apple-touch-icon（文件里写着理由——「它是展示环境，不是要装到主屏的应用」），
#: 是评委笔记本上的演示舞台。
#:
#: 第一版这条闸门要求**每个** HTML 都声明 theme-color，于是在 stage.html 上红了。
#: 那不是它坏了，是我这条断言越界了：给一个从不进主屏的页面强加状态栏配色，
#: 是拿闸门去执行一条产品里并不存在的规矩。
INSTALLABLE = sorted(
    p.name for p in STATIC.glob("*.html")
    if 'rel="manifest"' in p.read_text(encoding="utf-8")
)


def _canvas() -> dict[str, str]:
    """tokens.css 里 light / dark 两个 `--bg`。

    light 是 `:root` 里第一个，dark 是 `prefers-color-scheme: dark` 块里那个。
    两个都必须找到——只找到一个就说明这个文件的结构变了，那时候这条闸门在拿
    一个自己都不确定的值当真理，应该响亮地停下而不是放行。
    """
    values = re.findall(r"--bg:\s*(#[0-9a-fA-F]{3,8})\s*;", TOKENS)
    assert len(values) == 2, (
        f"tokens.css 里找到 {len(values)} 个 `--bg`（预期 2：light 与 dark）："
        f"{values}。结构变了，先确认哪个是画布色再改这条闸门。"
    )
    return {"light": values[0].lower(), "dark": values[1].lower()}


@pytest.mark.parametrize("page", INSTALLABLE)
def test_theme_color_is_the_canvas_colour(page: str) -> None:
    html = (STATIC / page).read_text(encoding="utf-8")
    found = dict(re.findall(
        r'<meta\s+name="theme-color"\s+media="\(prefers-color-scheme:\s*(\w+)\)"\s+content="([^"]+)"',
        html,
    ))
    canvas = _canvas()
    for scheme, want in canvas.items():
        got = found.get(scheme, "").lower()
        assert got == want, (
            f"{page} 的 {scheme} theme-color 是 {got or '（缺）'}，而画布 `--bg` 是 {want}。\n"
            "  装到主屏后状态栏和页面之间会有一道横贯屏幕的接缝。"
        )


def test_every_installable_page_declares_both_schemes() -> None:
    """深浅两套都要有，而且这张名单不许是空的。

    少声明一个配色方案，上面那条参数化就少一个断言——而"少测了一个"和"通过"
    在结果里长得一样。名单为空更彻底：整条闸门会跑完、报绿、一个页面都没看。
    """
    assert len(INSTALLABLE) >= 6, (
        f"只认出 {len(INSTALLABLE)} 个可安装页面（{INSTALLABLE}）——"
        "找 `rel=\"manifest\"` 的写法跟 HTML 对不上了，这条闸门正在空转"
    )
    for page in INSTALLABLE:
        html = (STATIC / page).read_text(encoding="utf-8")
        schemes = re.findall(r'name="theme-color"\s+media="\(prefers-color-scheme:\s*(\w+)\)"', html)
        assert sorted(schemes) == ["dark", "light"], (
            f"{page} 的 theme-color 只声明了 {schemes or '（无）'}——深浅两套都要有"
        )
