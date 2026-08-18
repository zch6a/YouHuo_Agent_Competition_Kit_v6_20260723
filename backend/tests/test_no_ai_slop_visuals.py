"""四种"一看就知道是 AI 做的"的视觉处理，样式表里一处都不许有。

设计稿第 45 节点名禁止：purple→blue 渐变、aurora、背景 mesh、pink/purple glow。
理由不是审美偏好——那四样已经成了 AI 生成界面的签名。一位见过一百个作品的评委扫一眼
就知道这个界面是谁做的，而这个项目最不想说的话恰恰是"这是生成出来的"。

改之前这个前端**四样全有**：六处蓝→紫渐变（一个 `--role-accent-2` 令牌驱动）、
三团铺在整页背后的 radial mesh、一圈紫色的呼吸光晕、一块冷白画布。

判据只查样式表，因为严格 CSP 下颜色只能来自样式表（无内联 style、无 CDN）。
渐变本身**不禁**：一个物体从上到下有明暗是真的。禁的是"跨色相"——
所以判据是"渐变的两端色相差多少"，不是"有没有渐变"。
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
STATIC = ROOT / "backend" / "static"
LAYERS = ("tokens.css", "base.css", "components.css", "pages.css")

#: 一看就是 AI 的那几个词。它们出现在**值**里就是问题；出现在注释里是在解释为什么
#: 不用它们（这一轮每一处都留了说明），所以先剥注释。
BANNED_WORDS = ("aurora", "violet", "fuchsia", "magenta")


def _css(name: str) -> str:
    return (STATIC / name).read_text(encoding="utf-8")


def _strip_comments(text: str) -> str:
    return re.sub(r"/\*.*?\*/", "", text, flags=re.S)


#: 十六进制 → 近似色相角。够用就行：这里要区分的是"蓝和紫"，不是"两个蓝"。
def _hue(hex_colour: str) -> float | None:
    h = hex_colour.lstrip("#")
    if len(h) == 3:
        h = "".join(c * 2 for c in h)
    if len(h) != 6:
        return None
    r, g, b = (int(h[i:i + 2], 16) / 255 for i in (0, 2, 4))
    mx, mn = max(r, g, b), min(r, g, b)
    if mx == mn:
        return None  # 灰，没有色相
    d = mx - mn
    if mx == r:
        deg = ((g - b) / d) % 6
    elif mx == g:
        deg = (b - r) / d + 2
    else:
        deg = (r - g) / d + 4
    return deg * 60


@pytest.mark.parametrize("layer", LAYERS)
def test_no_ai_slop_colour_words(layer: str) -> None:
    body = _strip_comments(_css(layer)).lower()
    found = [w for w in BANNED_WORDS if w in body]
    assert not found, (
        f"{layer} 的样式值里出现了 {found}。设计稿第 45 节点名禁止 aurora 与紫/洋红系"
        "——它们是 AI 生成界面的签名。"
    )


@pytest.mark.parametrize("layer", LAYERS)
def test_the_background_mesh_paints_nothing(layer: str) -> None:
    """三团铺满整页的 radial mesh 必须是透明的。

    这里判的是**令牌的值**，不是"有没有 radial-gradient"：`base.css` 里那三条
    `radial-gradient(... var(--bg-mesh-N) ...)` 结构保留着（删掉它们会让浅色/深色
    两套背景规则各自变形），但三个令牌都是 `transparent`，所以什么都不画。

    直接删令牌是错的：那三条 radial-gradient 仍然引用它们，未定义的自定义属性
    在 `background` 里的行为是让整条声明失效，而不是"透明"——那会连带把
    `--bg` 的底色一起弄没，整页变成浏览器默认白。
    """
    body = _strip_comments(_css(layer))
    for n in (1, 2, 3):
        for match in re.finditer(rf"--bg-mesh-{n}\s*:\s*([^;]+);", body):
            value = match.group(1).strip()
            assert value == "transparent", (
                f"{layer} 的 --bg-mesh-{n} 是 {value!r}，不是 transparent。"
                "背景 mesh 已经退场（设计稿第 45 节）。"
            )


#: 渐变两端允许的最大色相差。
#:
#: 第一版写的是 60°，而**变异测试证明那道闸门是空的**：把 `#4A90D9 → #7B61D9`
#: （正是被删掉的那个蓝→紫）放回品牌标，16 条断言全绿。
#:
#: 原因是我在 docstring 里写了"那六处是 43°"——那个数字是估的，没量过。真实值：
#:
#:     #4A90D9 蓝      212.0°
#:     #7B61D9 紫      251.1°   → 差 39.1°，低于我自己设的 60°
#:
#: 而现在全站最大的一处是评委页抬头 #14224a → #1e4681 → #10233f，差 7.6°；
#: 暖色那一族 orange #F5A623(36.9°) → yellow #FFD466(43.1°) 差 6.2°。
#:
#: 20° 把两边干净地分开：允许的最大值是 7.6，要挡的最小值是 39.1。
#: 教训是"阈值必须从量出来的两侧算，不能从记忆里估一个中间数"。
MAX_HUE_SPREAD_DEG = 20


@pytest.mark.parametrize("layer", LAYERS)
def test_gradients_stay_within_one_hue(layer: str) -> None:
    """渐变两端的色相差不许超过 MAX_HUE_SPREAD_DEG。

    渐变**不禁**：一个物体从上到下有明暗是真的。禁的是跨色相的霓虹——
    真正的分界线在"同一个颜色的深浅"和"两个颜色"之间。阈值怎么定的见上面那段。
    """
    body = _strip_comments(_css(layer))
    # 只看写死的十六进制。令牌之间的组合由上面那条词表挡（紫色令牌已经不存在了），
    # 而 color-mix(... #000) / (... #fff) 是纯明度操作，不改色相。
    problems: list[str] = []
    for grad in re.finditer(r"(linear|radial)-gradient\(([^;]*?)\)\s*[,;]", body, re.S):
        text = grad.group(2)
        hexes = re.findall(r"#[0-9a-fA-F]{3,8}\b", text)
        hues = [h for h in (_hue(x) for x in hexes) if h is not None]
        if len(hues) < 2:
            continue
        spread = max(hues) - min(hues)
        # 跨过 0°/360° 的一对（红与洋红）算最短弧。
        spread = min(spread, 360 - spread)
        if spread > MAX_HUE_SPREAD_DEG:
            problems.append(f"{spread:.1f}° 跨度：{hexes}")
    assert not problems, (
        f"{layer} 有跨色相渐变：{problems}\n"
        "  渐变可以有（明暗是真的），跨色相的霓虹不行——那是 AI 界面的签名。"
    )


def test_the_canvas_is_warm_not_cool() -> None:
    """画布是暖中性白，不是蓝味的白。

    `#f4f6fb` 的蓝分量比红分量高 7 —— 肉眼看是"冷白"，让整页显得像一个工具。
    设计稿第 42 节要 Warm Ivory：红 ≥ 蓝。

    这条是"看得出来但量不出来"那一类里少数**能**量出来的：一个通道差而已。
    """
    tokens = _strip_comments(_css("tokens.css"))
    light = tokens[: tokens.index("@media (prefers-color-scheme: dark)")]
    match = re.search(r"(?<!-)--bg\s*:\s*(#[0-9a-fA-F]{6})\s*;", light)
    assert match, "浅色模式的 --bg 不是一个六位十六进制了"
    h = match.group(1).lstrip("#")
    r, b = int(h[0:2], 16), int(h[4:6], 16)
    assert r >= b, f"画布 #{h} 偏冷（红 {r} < 蓝 {b}）——设计稿要暖中性白"


def test_the_two_design_systems_share_the_brand() -> None:
    """桌面那一档只改密度，不改品牌。

    "两套设计系统"最容易做成两套**品牌**——那样手机框里和框外看起来像两个产品，
    而它们是同一个产品的两面。所以 `[data-surface="platform"]` 这一层里
    只允许出现间距、字阶、行高、圆角；颜色、字体、阴影、动效一个都不许覆写。
    """
    tokens = _strip_comments(_css("tokens.css"))
    start = tokens.index('[data-surface="platform"] {')
    block = tokens[start:tokens.index("}", start)]
    declared = re.findall(r"(--[\w-]+)\s*:", block)
    assert declared, "platform 那一档是空的"
    allowed = re.compile(r"^--(space|text|lh|r)-")
    strays = sorted({d for d in declared if not allowed.match(d)})
    assert not strays, (
        f"platform 那一档覆写了品牌令牌：{strays}。"
        "这一层只该动密度（间距/字阶/行高/圆角）——两面必须是同一个产品。"
    )


def test_the_key_action_tap_tier_is_actually_used() -> None:
    """`--tap-key` 必须真的有人消费。

    一个没人用的令牌和没有这个令牌是一样的，而它在样式表里的存在会让下一个人
    以为这件事已经做过了。这条查两件事：声明了，而且被引用了。
    """
    tokens = _strip_comments(_css("tokens.css"))
    assert re.search(r"--tap-key\s*:\s*56px", tokens), "--tap-key 没有声明成 56px"
    users = [
        layer for layer in LAYERS
        if layer != "tokens.css" and "var(--tap-key)" in _strip_comments(_css(layer))
    ]
    assert users, "没有任何一层消费 --tap-key —— 关键操作那一档只声明了没落地"


def test_the_latin_font_is_range_limited() -> None:
    """自托管的拉丁字体必须限定 unicode-range。

    一款没有汉字的拉丁字体，不限区间的话浏览器会为**每一个汉字**先来它里面
    找字形，找不到再回退——而回退期间那些字是不可见的（FOIT）。也就是说：
    一个为了让数字更清楚而加的字体，会让整页中文先闪一次白。

    ## 这条判据现在是条件句

    它原来第一行是 `assert faces`——**要求必须有自托管字体**，比它自己的
    标题（「自托管的拉丁字体*必须限定* unicode-range」）更强。
    那是「当时恰好有一个」留下的痕迹，不是它要守的性质。

    Atkinson Hyperlegible 拿掉了，原因量过：它只覆盖拉丁与数字，汉字落到
    系统栈，于是「11:00 复诊前准备病历」里数字和汉字是**两套字形、两个重心**。
    中文字体自己的数字和汉字是一起设计的，宽度、基线、笔画都对得上。

    **代价要说清楚**：Atkinson 是为低视力设计的，`0/O`、`1/l/I`、`6/9`
    在它里面互相区分得比系统字体好。换回系统数字之后这一点弱了。
    要补回来得找一款**带汉字**的高辨识度字体，那是另一件事。

    守的性质没变：**有**自托管拉丁字体的话，它必须限区间、必须有
    font-display、必须不覆盖汉字区、文件必须在包里。
    """
    tokens = _strip_comments(_css("tokens.css"))
    faces = re.findall(r"@font-face\s*\{(.*?)\}", tokens, re.S)
    for face in faces:
        assert "unicode-range" in face, f"这个 @font-face 没有 unicode-range：{face[:90]}"
        assert "font-display" in face, f"这个 @font-face 没有 font-display：{face[:90]}"
        # 汉字区间（U+4E00 起）绝不能落在里面。
        assert not re.search(r"U\+4E00|U\+3000|U\+9F", face, re.I), (
            "unicode-range 覆盖到了汉字区间，而这个字体没有汉字"
        )
        # 文件必须真的在包里。
        src = re.search(r'url\("(/static/fonts/[^"]+)"\)', face)
        assert src, f"这个 @font-face 的 src 不是自托管路径：{face[:90]}"
        path = ROOT / "backend" / src.group(1).lstrip("/")
        assert path.is_file(), f"字体文件不在包里：{src.group(1)}"
        assert path.read_bytes()[:4] == b"wOF2", f"{path.name} 不是 woff2"