"""中文正文里不许混西文直引号。

视觉审查在截图上挑出来的：可信页凭证里是 `"有一件缴费任务被建立"`（ASCII 直引号），
而**同一段**后面用的是全角 `「今天没出门」`；评委页全篇是对的 `「」`。一段文字里两种
引号并存，是"文案没过排版"最典型的痕迹——设计稿第 45 节把这一类归进 AI slop，
理由不是审美：一位见过很多作品的评委扫一眼就知道这段字是生成的。

为什么会漏：直引号在代码里到处都是（JS 字符串、HTML 属性、CSS 选择器），所以不能
按字符扫全文。判据必须是"**中文正文里**的直引号"——也就是引号紧挨着汉字的那些。

这条闸门只管手机框里那四页 + 桌面三页的**可见文案**，不管代码和注释。
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
STATIC = ROOT / "backend" / "static"

PAGES = ["index.html", "elder.html", "family.html", "care.html",
         "trust.html", "judge.html", "stage.html"]
SCRIPTS = ["landing.js", "elder.js", "family.js", "care.js",
           "trust.js", "judge.js", "stage.js", "proof-demos.js", "common.js"]

#: 一个直引号（`"` 或 `'`），**紧贴着**汉字。
#:
#: 两侧都查：`说"你好"` 和 `"你好"说` 都要抓到。只查一侧会漏掉半数——
#: 一对引号里总有一侧贴着汉字、另一侧贴着标点或空格。
_STRAIGHT_NEXT_TO_HANZI = re.compile(r'(?:[一-鿿]["\']|["\'][一-鿿])')


def _visible_html(page: str) -> str:
    """标签之间的文字，加上 aria-label / title。"""
    source = (STATIC / page).read_text(encoding="utf-8")
    source = re.sub(r"<!--.*?-->", " ", source, flags=re.S)
    source = re.sub(r"<script\b.*?</script>", " ", source, flags=re.S)
    source = re.sub(r"<svg\b.*?</svg>", " ", source, flags=re.S)
    labels = " ".join(re.findall(r'(?:aria-label|title)="([^"]*)"', source))
    between = " ".join(re.findall(r">([^<]+)<", source))
    return between + " " + labels


def _chinese_literals(script: str) -> list[str]:
    """JS 里含汉字的字符串字面量。

    模板串里的 `${…}` 换成一个**不含汉字**的占位符：这个项目踩过一次，
    当时的占位符自己带汉字，于是把每一处插值都变成了误报。
    """
    source = (STATIC / script).read_text(encoding="utf-8")
    source = re.sub(r"/\*.*?\*/", " ", source, flags=re.S)
    source = re.sub(r"^\s*//.*$", " ", source, flags=re.M)
    out: list[str] = []
    for match in re.finditer(r"`([^`]*)`|'([^'\n]*)'|\"([^\"\n]*)\"", source):
        text = next(g for g in match.groups() if g is not None)
        if not re.search(r"[一-鿿]", text):
            continue
        out.append(re.sub(r"\$\{[^}]*\}", "@@", text))
    return out


@pytest.mark.parametrize("page", PAGES)
def test_no_straight_quotes_in_chinese_copy_html(page: str) -> None:
    hits = _STRAIGHT_NEXT_TO_HANZI.findall(_visible_html(page))
    assert not hits, (
        f"{page} 的可见文案里有 {len(hits)} 处西文直引号贴着汉字：{hits[:6]}\n"
        "  中文正文用 「」 或 『』。直引号混在中文里是「文案没过排版」的痕迹，"
        "而同一段里两种引号并存更明显。"
    )


@pytest.mark.parametrize("script", SCRIPTS)
def test_no_straight_quotes_in_chinese_copy_js(script: str) -> None:
    bad: list[str] = []
    for literal in _chinese_literals(script):
        if _STRAIGHT_NEXT_TO_HANZI.search(literal):
            bad.append(literal[:70])
    assert not bad, (
        f"{script} 有 {len(bad)} 条中文文案里混了西文直引号：\n  "
        + "\n  ".join(bad)
        + "\n  用 「」。注意：只有**会显示给用户**的字符串要改，"
        "注释里怎么写都不影响屏幕。"
    )


def test_the_scan_actually_reads_the_copy() -> None:
    """扫描器必须真的读到了文案。

    一个"跑了但一个字都没读到"的检查，和没有这个检查是一回事——而它在结果里
    看起来一模一样地绿。这个项目已经因此栽过一次：一条 `${…}` 占位符自己带汉字的
    扫描器，把 42 处泄漏虚报成了 26 处的两倍。

    判据是每一页都必须能从自己的 `<h1>` 里读到字，而且总量要够。
    """
    for page in PAGES:
        text = _visible_html(page)
        source = (STATIC / page).read_text(encoding="utf-8")
        h1 = re.search(r"<h1[^>]*>([^<]+)</h1>", source)
        if h1:
            assert h1.group(1).strip() in text, f"{page} 的 h1 没被扫描器读到"
    total = sum(len(_chinese_literals(s)) for s in SCRIPTS)
    assert total > 200, f"九个脚本一共只读到 {total} 条中文文案，扫描器大概没在工作"


def test_the_scan_catches_a_planted_straight_quote() -> None:
    """自证：扫描器认得它要找的东西。

    上面三条都在断言"没有"。一条永远断言"没有"的检查，在正则写错的那一天会
    继续绿——所以这里种一个进去，当场验它抓得到。
    """
    assert _STRAIGHT_NEXT_TO_HANZI.search('审计链里只有"有一件缴费任务被建立"')
    assert _STRAIGHT_NEXT_TO_HANZI.search("他说'好'")
    # 而这些不该被抓到：
    assert not _STRAIGHT_NEXT_TO_HANZI.search("「有一件缴费任务被建立」")
    assert not _STRAIGHT_NEXT_TO_HANZI.search('class="promise" 中文在别处')
    assert not _STRAIGHT_NEXT_TO_HANZI.search("const x = 'bill_payment';")