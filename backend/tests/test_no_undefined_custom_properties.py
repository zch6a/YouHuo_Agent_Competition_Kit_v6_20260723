"""每一个被 `var()` 引用的自定义属性，都必须真的被声明过。

起因是一个拼错的令牌名。照护页那些列表小圆点要和第一行文字的中线对齐：

    top: calc(var(--lh-normal) * .5em);

而 `--lh-normal` **不存在**——全站只有 `--lh-tight` / `--lh-snug` / `--lh-base` /
`--lh-loose`。CSS 对未声明的自定义属性的处理是：整条声明在计算值阶段变成
**invalid at computed-value time**，也就是这条 `top` 直接失效、退回 `auto`。
圆点因此浮在文字行上方半行高。

没有任何仪器会报这件事：
  * 对比度闸门读的是计算颜色，位置不参与；
  * 溢出探针只量横向；
  * 点击遍历只问"按不按得到"，一个错位的装饰点不影响可点性；
  * 而 CSS 本身**不报错**——它安静地丢掉那一条。

最后是一个人在 320px 的截图上看出来的。这条闸门把那次观察变成一次静态检查。

它同时挡住另一类更隐蔽的：某个令牌**在深色块里声明、在浅色块里引用**。那种情况下
浅色模式安静退化，而深色模式是对的——看一眼浅色截图往往看不出是令牌的问题。
"""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
STATIC = ROOT / "backend" / "static"

#: 四层按加载顺序。声明可以出现在被引用之后（层叠与继承和源码顺序无关），
#: 所以判据是"全站声明的集合" vs "全站引用的集合"，不逐文件比。
LAYERS = ("tokens.css", "base.css", "components.css", "pages.css")

#: `var(--x)` 里带兜底值的不算问题：`var(--stage-top-h, 0px)` 明确说了"没有就用 0"。
#: 这正是 `/judge` 复用桌面机身时的写法。
_VAR_WITH_FALLBACK = re.compile(r"var\(\s*(--[\w-]+)\s*,")
_VAR_PLAIN = re.compile(r"var\(\s*(--[\w-]+)\s*\)")
_DECLARED = re.compile(r"(--[\w-]+)\s*:")


def _strip_comments(text: str) -> str:
    return re.sub(r"/\*.*?\*/", " ", text, flags=re.S)


def _all_css() -> dict[str, str]:
    return {name: _strip_comments((STATIC / name).read_text(encoding="utf-8"))
            for name in LAYERS}


def test_every_var_reference_resolves() -> None:
    sheets = _all_css()
    declared: set[str] = set()
    for body in sheets.values():
        declared |= set(_DECLARED.findall(body))

    problems: list[str] = []
    for name, body in sheets.items():
        for line_no, line in enumerate(body.splitlines(), 1):
            for used in _VAR_PLAIN.findall(line):
                if used not in declared:
                    problems.append(f"{name}:{line_no}  var({used})  ← 没有任何地方声明它")
    assert not problems, (
        f"有 {len(problems)} 处引用了不存在的自定义属性：\n  " + "\n  ".join(problems)
        + "\n  CSS 不会报错——它把整条声明**丢掉**（invalid at computed-value time），"
        "所以这类拼写错误只能靠看截图或这条断言发现。"
    )


def test_fallbacks_are_only_used_where_the_token_is_genuinely_optional() -> None:
    """带兜底的引用是允许的，但兜底不该用来掩盖拼写错误。

    判据：`var(--x, …)` 里的 `--x` 如果**根本没被声明过**，那这个兜底就不是
    "这个令牌在某些页面上不适用"，而是"这个名字是错的"——只不过后果被兜底藏起来了，
    比不带兜底更难发现。
    """
    sheets = _all_css()
    declared: set[str] = set()
    for body in sheets.values():
        declared |= set(_DECLARED.findall(body))

    problems: list[str] = []
    for name, body in sheets.items():
        for line_no, line in enumerate(body.splitlines(), 1):
            for used in _VAR_WITH_FALLBACK.findall(line):
                if used not in declared:
                    problems.append(f"{name}:{line_no}  var({used}, …)")
    assert not problems, (
        "这些带兜底的引用指向一个从未声明过的名字——兜底把拼写错误藏起来了：\n  "
        + "\n  ".join(problems)
    )


def test_the_scan_actually_found_the_tokens() -> None:
    """扫描器必须真的读到了令牌。

    一个"跑了但一条都没读到"的检查和没有这个检查是一回事，而它在结果里一样地绿。
    这个项目已经因此栽过一次（`${…}` 占位符自带汉字的那个扫描器）。
    """
    sheets = _all_css()
    declared: set[str] = set()
    used: set[str] = set()
    for body in sheets.values():
        declared |= set(_DECLARED.findall(body))
        used |= set(_VAR_PLAIN.findall(body)) | set(_VAR_WITH_FALLBACK.findall(body))
    assert len(declared) > 60, f"只读到 {len(declared)} 个声明，扫描器大概没在工作"
    assert len(used) > 60, f"只读到 {len(used)} 处引用，扫描器大概没在工作"
    # 自证：认得出一个种进去的错名字。
    assert not _VAR_PLAIN.findall("var(--lh-normal, 1.7)"), "带兜底的不该被 PLAIN 抓到"
    assert _VAR_PLAIN.findall("calc(var(--lh-normal) * .5em)"), "不带兜底的必须被抓到"


def test_no_token_is_declared_only_inside_dark_mode() -> None:
    """令牌不能只在深色块里声明。

    只在 `@media (prefers-color-scheme: dark)` 里声明、在外面引用的令牌，
    浅色模式下整条声明会安静失效——而深色模式是对的。这一种比纯拼写错误更难查：
    看浅色截图看不出是令牌的问题，看深色截图什么问题都没有。
    """
    sheets = _all_css()
    outside: set[str] = set()
    inside: set[str] = set()
    for body in sheets.values():
        # 按 `@media (prefers-color-scheme: dark) {` 切开，用花括号配平找到它的范围。
        for match in re.finditer(r"@media\s*\([^)]*prefers-color-scheme:\s*dark[^)]*\)\s*\{", body):
            depth, i = 1, match.end()
            while i < len(body) and depth:
                if body[i] == "{":
                    depth += 1
                elif body[i] == "}":
                    depth -= 1
                i += 1
            inside |= set(_DECLARED.findall(body[match.end():i]))
            body = body[:match.start()] + " " * (i - match.start()) + body[i:]
        outside |= set(_DECLARED.findall(body))

    only_dark = sorted(inside - outside)
    assert not only_dark, (
        f"这些令牌只在深色块里声明过：{only_dark}\n"
        "  浅色模式下引用它们的声明会安静失效。每个令牌都要有一个浅色（默认）值。"
    )