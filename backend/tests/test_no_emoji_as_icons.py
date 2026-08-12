r"""界面上不许用 emoji 当图标。

这是这个项目八条硬约束里的第七条，而**它一直没有闸门**——于是它靠人记。人记不住：
`glassbox.js` 里那句 `heading.textContent` 拼了一个 `🔍` 在标题前面，活到了这一轮的
最后，就在老人端最重要的那张卡（玻璃盒依赖校准卡）的标题上。同一轮里另一个 agent 手动删掉了
家人端的一个 `⚠`，而没有任何东西阻止下一个人再加一个。

三个理由，越往后越要紧：

1. **字形由系统决定。** 同一个码位在鸿蒙、iOS、Windows 上是三种画法、三种粗细、
   三种配色。和一套统一描边的内联 SVG 放在一起，emoji 永远是异物——而"图标语言统一"
   正是这一轮 Make Interfaces Feel Better 要守的东西。
2. **读屏软件会念出来。** 「放大镜 这件事我准备这样办」。这张卡是要念给一位视力在
   下降的老人听的。
3. **它通常不携带信息。** 卡片的身份由底色、阴影和标题文字承担。

判据只查**会显示给用户**的地方：HTML 的标签间文字与 `aria-label`/`title`，
以及 JS 里含 emoji 的字符串字面量。注释里怎么写不影响屏幕——而这一轮已经有三条断言
栽在"命中了我自己的注释"上，所以这里从一开始就剥注释。
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
STATIC = ROOT / "backend" / "static"

PAGES = ["index.html", "elder.html", "family.html", "care.html",
         "trust.html", "judge.html", "stage.html"]
SCRIPTS = sorted(p.name for p in STATIC.glob("*.js"))

#: Emoji 与彩色象形符号的码位区间。
#:
#: 刻意**不**包含：
#:   * `→ ← ↑ ↓`（U+2190–21FF 箭头）——它们是排版符号，这个项目用它们做「去处」标记，
#:     字形来自正文字体，不是 emoji；
#:   * `✓ ✗`（U+2713/2717）——同上，而且它们出现在 CSS 注释的表格里；
#:   * `「」『』——…`（中文标点）。
#:
#: 包含的是真正会被系统 emoji 字体接管的那些区间。
_EMOJI = re.compile(
    "["
    "\U0001F300-\U0001FAFF"   # 杂项象形、表情、交通、补充象形
    "\U0001F000-\U0001F0FF"   # 麻将、扑克
    "☀-➿"           # 杂项符号与装饰符（☀ ⚠ ✂ ❤ …）
    "⬀-⯿"           # 杂项符号与箭头里的实心块
    "️"                  # 变体选择符 16：把前一个字符渲染成 emoji
    "⃣"                  # 组合围栏键帽（1️⃣）
    "]"
)


def _visible_html(page: str) -> str:
    source = (STATIC / page).read_text(encoding="utf-8")
    source = re.sub(r"<!--.*?-->", " ", source, flags=re.S)
    source = re.sub(r"<script\b.*?</script>", " ", source, flags=re.S)
    labels = " ".join(re.findall(r'(?:aria-label|title|alt)="([^"]*)"', source))
    between = " ".join(re.findall(r">([^<]+)<", source))
    return between + " " + labels


def _chinese_or_visible_literals(script: str) -> list[str]:
    """JS 里的字符串字面量，剥掉注释。"""
    source = (STATIC / script).read_text(encoding="utf-8")
    source = re.sub(r"/\*.*?\*/", " ", source, flags=re.S)
    source = re.sub(r"^\s*//.*$", " ", source, flags=re.M)
    out: list[str] = []
    for match in re.finditer(r"`([^`]*)`|'([^'\n]*)'|\"([^\"\n]*)\"", source):
        out.append(next(g for g in match.groups() if g is not None))
    return out


@pytest.mark.parametrize("page", PAGES)
def test_no_emoji_in_page_text(page: str) -> None:
    hits = _EMOJI.findall(_visible_html(page))
    assert not hits, (
        f"{page} 的可见文本里有 emoji：{hits[:8]}\n"
        "  硬约束第七条：不用 emoji 当图标。字形由系统决定（三个平台三种画法），"
        "读屏软件会念出来，而且它通常不携带信息。用内联 SVG，或者去掉。"
    )


@pytest.mark.parametrize("script", SCRIPTS)
def test_no_emoji_in_script_strings(script: str) -> None:
    bad = [s[:60] for s in _chinese_or_visible_literals(script) if _EMOJI.search(s)]
    assert not bad, (
        f"{script} 有 {len(bad)} 条会显示给用户的字符串里带 emoji：\n  "
        + "\n  ".join(bad)
        + "\n  注释里不算——这里已经剥过注释了，命中的是真的字面量。"
    )


def test_the_scan_reads_the_text_and_catches_a_planted_emoji() -> None:
    """自证：扫描器读到了东西，而且认得它要找的东西。

    一条永远断言"没有"的检查，在正则写错的那一天会继续绿。这个项目已经栽过一次：
    一个 `${…}` 占位符自带汉字的扫描器，把 42 处泄漏虚报成两倍。
    """
    total = sum(len(_visible_html(p)) for p in PAGES)
    assert total > 4000, f"七个页面一共只读到 {total} 个字符，扫描器大概没在工作"
    assert SCRIPTS, "一个脚本都没找到"

    # 认得出来的：
    assert _EMOJI.search("🔍 这件事我准备这样办")
    assert _EMOJI.search("⚠ 需要您确认")
    assert _EMOJI.search("1️⃣ 第一步")
    # 不该被抓的（排版符号与中文标点，不是 emoji）：
    assert not _EMOJI.search("在电脑上看完整证明 →")
    assert not _EMOJI.search("「今天没有要办的事」")
    assert not _EMOJI.search("68.40 元 · 已办好")