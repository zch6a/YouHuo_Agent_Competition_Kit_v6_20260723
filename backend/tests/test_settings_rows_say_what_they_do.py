r"""「我的」里每个可调控件都要说清它会造成什么，不只写名字。

## 依据

来自参考产品研究（`frontend_redesign/ia/12_reference_study.md` 第二节 ⑦-b）。
把 Medito 的 `RowItemWidget` 渲染出来实测，它的开关行是：

    Do Not Disturb          ← 粗体标题（名字）
    Silence all alerts      ← 小一号、暗一档（后果）
                        [开关]

**一个控件的后果不是自明的。** 「Do Not Disturb」是名字，
「Silence all alerts」才是它会做什么。优活的「语速」同理——她不该靠拨一次
再观察来推断它做了什么，尤其因为这一页的读者是一位老人。

## 判据为什么不是「有没有 .meta」

有 `.meta` 但内容是「设置语速」等于没说。所以要求那句话**不能只是名字的复述**：
去掉名字里的字之后必须还剩下东西。这一条挡住的是「为了过闸门而写一句废话」。
"""
from __future__ import annotations

import re
from html.parser import HTMLParser
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
ELDER_HTML = ROOT / "backend" / "static" / "elder.html"


class ToolRows(HTMLParser):
    """收 `.profile-tools` 里的每个 `<label>`：名字、说明、里面的控件 id。"""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.rows: list[dict] = []
        self._in_tools = 0
        self._depth = 0
        self._row: dict | None = None
        self._collect: str | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        d = {k: (v or "") for k, v in attrs}
        classes = d.get("class", "").split()
        if "profile-tools" in classes:
            self._in_tools = 1
            self._depth = 0
            return
        if not self._in_tools:
            return
        self._depth += 1
        if tag == "label":
            self._row = {"name": "", "why": "", "controls": []}
        elif self._row is not None:
            if "tool-name" in classes:
                self._collect = "name"
            elif "meta" in classes:
                self._collect = "why"
            if tag in ("select", "input", "button") and d.get("id"):
                self._row["controls"].append(d["id"])

    def handle_endtag(self, tag: str) -> None:
        if not self._in_tools:
            return
        if tag in ("span", "label"):
            self._collect = None
        if tag == "label" and self._row is not None:
            self.rows.append(self._row)
            self._row = None
        self._depth -= 1
        if self._depth < 0:
            self._in_tools = 0

    def handle_data(self, data: str) -> None:
        if self._in_tools and self._row is not None and self._collect:
            self._row[self._collect] += data.strip()


def _rows() -> list[dict]:
    parser = ToolRows()
    parser.feed(ELDER_HTML.read_text(encoding="utf-8"))
    return parser.rows


def test_the_parser_actually_found_the_settings_rows() -> None:
    """先证明这个解析器抓到了东西。

    一个"跑了但一行都没找到"的检查，和没有这个检查是一回事，而它在结果里
    看起来一模一样地绿。「我的」里现在有语速和文字大小两个可调控件。
    """
    rows = _rows()
    assert len(rows) >= 2, (
        f"只解析出 {len(rows)} 行设置：{rows}。"
        "要么 `.profile-tools` 的结构变了，要么控件被搬走了——"
        "两种情况都得回来改这条测试，而不是让它静默地什么都不测。"
    )
    with_control = [r for r in rows if r["controls"]]
    assert len(with_control) >= 2, f"这些行里没有可调控件：{rows}"


def test_every_adjustable_row_says_what_it_does() -> None:
    for row in _rows():
        if not row["controls"]:
            continue          # 纯展示的行不在这条规则里
        assert row["name"], f"这一行没有名字：{row}"
        assert row["why"], (
            f"控件 {row['controls']} 只有名字「{row['name']}」，没说它会造成什么。"
            "她不该靠拨一次再观察来推断这个控件做了什么。"
        )


def test_the_explanation_is_not_just_the_name_again() -> None:
    """说明不能是名字的复述。

    「语速」配「设置语速」等于没说，而它能让上一条测试变绿。
    判据：把名字里出现过的字去掉，剩下的内容还要够写成一句话。
    """
    for row in _rows():
        if not row["controls"] or not row["why"]:
            continue
        name_chars = set(row["name"])
        remainder = [c for c in row["why"] if c not in name_chars and not c.isspace()]
        assert len(remainder) >= 6, (
            f"「{row['name']}」的说明是「{row['why']}」——去掉名字里的字之后"
            f"只剩 {len(remainder)} 个字符，这句话没有新增信息。"
        )


def test_no_english_in_the_explanations() -> None:
    """这一页的读者是一位老人，而老人端还会把内容念出来。"""
    for row in _rows():
        if not row["why"]:
            continue
        english = re.findall(r"[A-Za-z]{2,}", row["why"])
        assert not english, (
            f"「{row['name']}」的说明里有英文 {english}：{row['why']}"
        )
