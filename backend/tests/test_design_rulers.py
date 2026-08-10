"""设计系统的三条标尺：间距落在 4px 网格上、字号走令牌、阴影颜色不写死。

任务书要求"每个值都要能解释"。一次性把 183 处魔数收敛掉不难，难的是让它别腐蚀
回去——下一个人加一条 `padding: 11px` 不会有任何东西报红，而三个月后清单又是一百
多条。所以收敛的同时必须有这三条。

三条都只查这三层（tokens.css 是定义层，本身就该出现字面量）。
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
STATIC = ROOT / "backend" / "static"
LAYERS = ["base.css", "components.css", "pages.css"]

SPACING_PROPS = {
    "margin", "padding", "gap", "row-gap", "column-gap",
    "margin-top", "margin-bottom", "margin-left", "margin-right",
    "padding-top", "padding-bottom", "padding-left", "padding-right",
    "margin-block", "margin-inline", "padding-block", "padding-inline",
}

#: 只有 --text-xs(13px) 与 --text-sm(15px) 是固定值；--text-base 起全是 clamp()，
#: 所以固定字号的调用点只有这两种能换成令牌而取值不变。其余固定字号不在这条的
#: 管辖范围内——硬套 clamp 令牌会让它们在窄屏变小，而窄屏正是老人的屏幕。
FIXED_SIZE_TOKENS = {"13px": "--text-xs", "15px": "--text-sm"}


def _declarations(name: str):
    text = (STATIC / name).read_text(encoding="utf-8")
    # 注释里也写像素数（"命中区只有 19px 高"），必须先剥掉。
    text = re.sub(r"/\*.*?\*/", "", text, flags=re.S)
    for match in re.finditer(r"([-a-zA-Z]+)\s*:\s*([^;{}]+);", text):
        prop, value = match.group(1).strip(), match.group(2).strip()
        if prop.startswith("--"):
            continue
        yield prop, value


@pytest.mark.parametrize("layer", LAYERS)
def test_spacing_sits_on_the_four_pixel_grid(layer):
    """间距的每一个 px 字面量都是 4 的倍数。

    收敛前：194 个字面量，其中 118 个不是 4 的倍数，取值散布在
    2/3/5/6/7/9/10/11/13/14/15/17/18/22/26 之间。那不是节奏，是一百多个各自拍脑袋
    定下来又互相不知道的数。

    两类豁免，都是有理由的：
    - `clamp()` / `calc()` / `max()` / `min()` / `env()` 里的值是流体尺寸，两端另外
      核（`.panel` 的 `clamp(16px, 2.4vw, 28px)` 两端都在网格上）；
    - 大于 64px 的值不是间距档位，是页面级尺寸（`calc((100% - 560px) / 2)` 里的
      560px 是正文最大宽度）。
    """
    offenders = []
    for prop, value in _declarations(layer):
        if prop not in SPACING_PROPS:
            continue
        if re.search(r"(clamp|calc|max|min|env)\(", value):
            continue
        for px in re.findall(r"(?<![\w-])(\d+)px", value):
            n = int(px)
            if n <= 64 and n % 4:
                offenders.append(f"{prop}: {value}")
    assert not offenders, f"{layer} 有 {len(offenders)} 处间距不在 4px 网格上：{offenders[:8]}"


@pytest.mark.parametrize("layer", LAYERS)
def test_the_two_fixed_type_sizes_go_through_tokens(layer):
    """13px 和 15px 必须写成令牌。

    这两个是全站最常用的两级字号（收敛前 15px 出现 23 次、13px 出现 9 次），而它们
    恰好是 `--text-sm` / `--text-xs` 的确切值。散着写的后果不是"不好看"，是想调小字号
    时得改 32 个地方，改漏一个就出现两级只差 1px 的字。
    """
    offenders = [
        f"{prop}: {value}" for prop, value in _declarations(layer)
        if prop == "font-size" and value in FIXED_SIZE_TOKENS
    ]
    assert not offenders, (
        f"{layer} 有固定字号没走令牌：{offenders}"
        f"（应改为 {', '.join(f'{k} → var({v})' for k, v in FIXED_SIZE_TOKENS.items())}）"
    )


@pytest.mark.parametrize("layer", LAYERS)
def test_no_shadow_hardcodes_a_colour(layer):
    """阴影的颜色必须从令牌派生，不能写死。

    `.step-index` 曾经是 `box-shadow: 0 10px 24px rgba(23, 53, 111, .28)`，而正上方
    一行的渐变里写着同一个颜色的十六进制 `#17356f`——同一个颜色手抄了两遍，两处都
    绕开令牌。深色模式下这块本该几乎没有投影（背景已经是深的），结果压着一团比背景
    更深的蓝。

    白色高光（`rgba(255,255,255,...) inset`）是豁免的：它不是投影，是让表面读起来
    "凸起"而不是"画上去"的那道受光边，两种模式下都要是白的。

    另外 12 处 box-shadow 字面量是**聚焦环和光晕**，不是高程，本来就不该套
    `--shadow-1/2/3`，而且它们的颜色都由 `color-mix` 从主题令牌算出来。上一轮把环、
    光晕和高程混在一起数成"14 个阴影无深色取值"，只有 `.step-index` 那一处是真的。
    """
    offenders = []
    for prop, value in _declarations(layer):
        if prop != "box-shadow":
            continue
        stripped = re.sub(r"rgba\(\s*255\s*,\s*255\s*,\s*255\s*,[^)]*\)", "", value)
        if re.search(r"#[0-9a-fA-F]{3,8}\b", stripped) or re.search(r"\brgba?\(", stripped):
            offenders.append(f"{prop}: {value}")
    assert not offenders, f"{layer} 有阴影写死了颜色：{offenders}"


def test_the_grid_and_the_tokens_agree():
    """令牌本身也得在网格上——否则用令牌反而把魔数藏得更深。"""
    tokens = (STATIC / "tokens.css").read_text(encoding="utf-8")
    tokens = re.sub(r"/\*.*?\*/", "", tokens, flags=re.S)
    offenders = []
    for name, value in re.findall(r"(--space-[\w-]+)\s*:\s*([^;]+);", tokens):
        px = re.fullmatch(r"(\d+)px", value.strip())
        assert px, f"{name} 不是一个 px 值：{value}"
        if int(px.group(1)) % 4:
            offenders.append(f"{name}: {value}")
    assert not offenders, f"间距令牌自己不在 4px 网格上：{offenders}"
