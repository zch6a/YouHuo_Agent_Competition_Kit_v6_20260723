"""设计系统的三条标尺：间距落在 4px 网格上、字号走令牌、阴影颜色不写死。

任务书要求"每个值都要能解释"。一次性把 183 处魔数收敛掉不难，难的是让它别腐蚀
回去——下一个人加一条 `padding: 11px` 不会有任何东西报红，而三个月后清单又是一百
多条。所以收敛的同时必须有这三条。

三条都只查这三层（tokens.css 是定义层，本身就该出现字面量）。

**这个文件本身被审计过一轮，找出五条可绕过的路径**，逐条记在下面对应位置：
最后一条声明省掉分号、`calc()` 豁免整个 value、逻辑属性的 `-start/-end` 变体不在
名单里、`--space-*` 改名后整条测试空转、`hsl()`/`oklch()` 写死颜色放行。
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
STATIC = ROOT / "backend" / "static"
LAYERS = ["base.css", "components.css", "pages.css"]

#: 逻辑属性的 `-start` / `-end` 变体必须在名单里。
#:
#: 原名单只有 `padding-inline` 和 `margin-block` 这样的两端简写，于是
#: `padding-inline-start: 11px` 是一条完全合法、完全等效、而这条标尺看不见的绕道。
SPACING_PROPS = {
    "margin", "padding", "gap", "row-gap", "column-gap",
    "margin-top", "margin-bottom", "margin-left", "margin-right",
    "padding-top", "padding-bottom", "padding-left", "padding-right",
    "margin-block", "margin-inline", "padding-block", "padding-inline",
    "margin-block-start", "margin-block-end", "margin-inline-start", "margin-inline-end",
    "padding-block-start", "padding-block-end", "padding-inline-start", "padding-inline-end",
    "inset", "inset-block", "inset-inline", "top", "right", "bottom", "left",
}

#: 只有 --text-xs(13px) 与 --text-sm(15px) 是固定值；--text-base 起全是 clamp()，
#: 所以固定字号的调用点只有这两种能换成令牌而取值不变。其余固定字号不在这条的
#: 管辖范围内——硬套 clamp 令牌会让它们在窄屏变小，而窄屏正是老人的屏幕。
FIXED_SIZE_TOKENS = {"13px": "--text-xs", "15px": "--text-sm"}

#: 流体尺寸的函数。它们内部的两端另外核（`.panel` 的 clamp 两端都在网格上）。
_FLUID = re.compile(r"\b(?:clamp|calc|max|min|minmax|env|var)\([^()]*(?:\([^()]*\)[^()]*)*\)")


def _declarations(name: str):
    """(property, value) 对。

    分号不能是必需的。原正则是 `([-a-zA-Z]+)\\s*:\\s*([^;{}]+);` —— 要求以分号结尾，
    而 CSS 允许块内最后一条声明省掉分号。也就是说 `.x { padding: 11px }` 对这三条
    标尺**全部隐形**：间距、字号、阴影走的都是这个生成器。一条完全合法的 CSS 就能让
    整个文件的三条标尺同时失效。

    现在以 `;` 或 `}` 收尾，两种都认。
    """
    text = (STATIC / name).read_text(encoding="utf-8")
    # 注释里也写像素数（"命中区只有 19px 高"），必须先剥掉。
    text = re.sub(r"/\*.*?\*/", "", text, flags=re.S)
    for match in re.finditer(r"([-a-zA-Z]+)\s*:\s*([^;{}]+)(?=[;}])", text):
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
    - 流体函数（`clamp` / `calc` / `max` / `min` / `env`）里的值另外核；
    - 大于 64px 的值不是间距档位，是页面级尺寸（`calc((100% - 560px) / 2)` 里的
      560px 是正文最大宽度）。

    豁免的范围是**函数内部**，不是整条 value。原写法一见 `calc(` 就 `continue`，于是
    `padding: 11px calc(1rem)` 里那个 11px 直接过关——只要在同一条声明里随便挂一个
    calc，任意魔数都能带进来。现在只把函数体挖掉，剩下的照查。
    """
    offenders = []
    for prop, value in _declarations(layer):
        if prop not in SPACING_PROPS:
            continue
        outside = _FLUID.sub(" ", value)
        for px in re.findall(r"(?<![\w-])(\d+)px", outside):
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


#: 字阶里根本没有的字号，比"该走令牌却写了字面值"更糟。
#:
#: 上面那条只认 13px 和 15px 两个确切值——因为它是为"这两级最常用、散着写"那个具体
#: 问题建的。于是 **12px 和 14px 从它中间穿过去了**：字阶只有 --text-xs 13 和
#: --text-sm 15，中间没有一档，而实际渲染里这两个尺寸到处都是（`.metric-label` 12、
#: `.meta` / `.trust-pill` / `.status-chip` / `.profile-tools label` 14）。
#: 12px 比整个字阶的下限还小，而 tokens.css 顶上写着这套字阶
#: 「deliberately starting high: this product is read by people with presbyopia」。
#:
#: 一条只认两个值的规则，等于给"随手写一个 14px"发了通行证。这里改成反过来问：
#: 你写的这个 px 字号，在字阶里存在吗？不存在就得说明理由。
_SCALE_PX = {13, 15}          # --text-xs / --text-sm 的确切值
_ALLOWED_BIG_PX = {16, 17, 18, 19, 22, 26, 28, 30, 32, 34, 36, 58}
#: ↑ 16 以上是排版尺度（标题、数字、麦克风图标），它们本来就不在 --text-* 阶梯上，
#:   由各自的版式决定。这条判据管的是**下限**：不许出现小于 --text-sm 又不是
#:   --text-xs 的字号，因为那正是"绕开字阶把字调小"的形状。


@pytest.mark.parametrize("layer", LAYERS)
def test_no_font_size_falls_below_the_scale(layer):
    """不许出现字阶里没有的小字号。

    通过条件：写死的 px 字号要么 ≥ 16（版式尺度，另有其理），要么正好是 13/15
    （那两个由上面那条判据逼着走令牌）。落在中间或更小的——12、14——一律拦下。
    """
    offenders = []
    for prop, value in _declarations(layer):
        if prop != "font-size":
            continue
        m = re.fullmatch(r"(\d+(?:\.\d+)?)px", value.strip())
        if not m:
            continue
        px = float(m.group(1))
        if px >= 16 or px in _SCALE_PX:
            continue
        offenders.append(f"{prop}: {value}")
    assert not offenders, (
        f"{layer} 有小于 --text-sm(15px) 又不在字阶上的字号：{offenders}。"
        "字阶只有 --text-xs(13，仅限元数据) 和 --text-sm(15)，中间没有一档；"
        "tokens.css 说明这套字阶是为老花眼刻意起高的。要更小就得先在字阶里加一档。"
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
    `--shadow-1/2/3`，而且它们的颜色都由 `color-mix` 从主题令牌算出来。

    颜色函数不止 rgb 和 hex。原写法只认 `#hex` 与 `rgb()/rgba()`，于是
    `box-shadow: 0 10px 24px hsl(224 65% 26% / .28)` 是同一个缺陷的合法写法，而这条
    标尺是为它换来的。现在 hsl / hwb / lab / lch / oklab / oklch / color 一并查。
    """
    offenders = []
    for prop, value in _declarations(layer):
        if prop != "box-shadow":
            continue
        stripped = re.sub(r"rgba?\(\s*255\s*,?\s*255\s*,?\s*255\s*[,/]?[^)]*\)", "", value)
        hardcoded = (
            re.search(r"#[0-9a-fA-F]{3,8}\b", stripped)
            or re.search(r"\brgba?\(", stripped)
            or re.search(r"\b(?:hsla?|hwb|lab|lch|oklab|oklch|color)\(", stripped)
        )
        if hardcoded:
            offenders.append(f"{prop}: {value}")
    assert not offenders, f"{layer} 有阴影写死了颜色：{offenders}"


def test_the_grid_and_the_tokens_agree():
    """令牌本身也得在网格上——否则用令牌反而把魔数藏得更深。

    这条原先可以整条空转：把 `--space-*` 全部改名 `--sp-*` 并设成 11px，
    `re.findall` 返回空列表，for 体一次都不执行，测试通过。断言"至少找到几个"是
    这一类测试的必需项——一条只在有数据时才成立的检查，等于没有检查。
    """
    tokens = (STATIC / "tokens.css").read_text(encoding="utf-8")
    tokens = re.sub(r"/\*.*?\*/", "", tokens, flags=re.S)
    found = re.findall(r"(--space-[\w-]+)\s*:\s*([^;}]+)(?=[;}])", tokens)
    assert len(found) >= 8, f"间距令牌只找到 {len(found)} 个——它们被改名了吗？"
    offenders = []
    for name, value in found:
        px = re.fullmatch(r"(\d+)px", value.strip())
        assert px, f"{name} 不是一个 px 值：{value}"
        if int(px.group(1)) % 4:
            offenders.append(f"{name}: {value}")
    assert not offenders, f"间距令牌自己不在 4px 网格上：{offenders}"

    # 三层里必须真的有间距声明可查，否则上面三条参数化测试全是空转。
    # 一个把 CSS 挪走或改名的重构会让它们静默变成"通过"。
    total = sum(
        1 for layer in LAYERS for prop, _ in _declarations(layer) if prop in SPACING_PROPS
    )
    assert total >= 100, f"三层里只解析出 {total} 条间距声明——解析器还认得这些文件吗？"
