"""照护页的翻译表必须和后端的枚举对得上，而且不能靠演示数据来发现对不上。

写这个文件的直接原因：`/v4/health/events` 和 `/v4/reports/emotion` 在演示家庭里都返回
空，于是 care.js 里渲染这两类记录的代码**从来没有跑过一次真实数据**。四个错就那样活着：

  * `HEALTH_WORD` 的五个键（checkup_report / clinic_visit / hospitalization /
    vaccination / measurement）后端一个都不存在，真枚举只有 checkup / visit /
    medication / note——零命中，每条记录都印成兜底的「一条记录」；
  * `event.occurred_at`（真名 `event_at`）、`event.summary`（真名 `title`）、
    `event.source_name`（真名 `source`）三个字段名是猜的，所以标题永远不显示，
    日期永远退回入库时间；
  * `TREND_WORD` 少了 `distress_increasing` / `distress_decreasing`——后端的趋势一共
    只有三个值，那张表认得一个，另外两个走 `|| s.trend` 兜底，把「他这两周更紧张了」
    印成一串英文；
  * `EMOTION_WORD` 少了 `positive` / `low_mood` / `urgent`，还多写了后端没有的
    `sad` / `happy` / `neutral`。

界面上不许出现英文枚举值，而上面后两条正是在最需要被看见的那一刻（情绪在变差）违反它。
所以断言不写死一份枚举副本，而是**从后端的模型和源码里读**：后端加一个类型、改一个
趋势名，这里就红，而不是等到某个真实家庭第一次录进一条记录才在屏幕上露出来。
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from youhuo.v4_models import EmotionLabel, HealthEventKind, HealthEventRecord

ROOT = Path(__file__).resolve().parents[2]
CARE_JS = ROOT / "backend" / "static" / "care.js"
V4_STORE = ROOT / "backend" / "youhuo" / "v4_store.py"


def _source() -> str:
    return CARE_JS.read_text(encoding="utf-8")


def _table(name: str) -> dict[str, str]:
    """把 care.js 里一张 `const NAME = {...}` 字面量读成字典。

    只认单引号的键值——这个文件通篇是单引号，故意不去支持更多写法：一张读不出来的表
    应该让测试报错，而不是被当成空表悄悄通过。
    """
    match = re.search(rf"const {name} = \{{(.*?)\n\}};", _source(), re.S)
    assert match, f"care.js 里找不到 {name} 这张表"
    return dict(re.findall(r"(\w+):\s*'([^']*)'", match.group(1)))


def _body(start: str, end: str) -> str:
    text = _source()
    head = text.index(start)
    return text[head:text.index(end, head)]


# --------------------------------------------------------------------------
# 翻译表对得上后端枚举
# --------------------------------------------------------------------------


def test_health_kind_table_covers_every_kind_the_backend_can_emit() -> None:
    table = _table("HEALTH_WORD")
    missing = sorted({kind.value for kind in HealthEventKind} - table.keys())
    assert not missing, (
        f"HEALTH_WORD 漏了后端会发出的类型：{missing}。"
        "漏掉的走兜底，屏幕上是一句没有信息的「一条记录」。"
    )


def test_health_kind_table_has_no_key_the_backend_never_sends() -> None:
    """多写的键比漏写的更难发现：它永远不命中，看起来却像已经支持了。"""
    table = _table("HEALTH_WORD")
    real = {kind.value for kind in HealthEventKind}
    stale = sorted(table.keys() - real)
    assert not stale, f"HEALTH_WORD 里这些键后端不存在，永远不会命中：{stale}"


def test_emotion_label_table_covers_every_label_the_backend_can_emit() -> None:
    table = _table("EMOTION_WORD")
    missing = sorted({label.value for label in EmotionLabel} - table.keys())
    assert not missing, (
        f"EMOTION_WORD 漏了后端会发出的情绪类别：{missing}。"
        "漏掉的会以英文原样印到屏幕上——界面上不许出现英文枚举值。"
    )


def test_emotion_label_table_has_no_key_the_backend_never_sends() -> None:
    table = _table("EMOTION_WORD")
    real = {label.value for label in EmotionLabel}
    stale = sorted(table.keys() - real)
    assert not stale, f"EMOTION_WORD 里这些键后端不存在，永远不会命中：{stale}"


def _trends_the_store_can_emit() -> set[str]:
    """从 `generate_emotion_report` 的源码里读出它会写出的 trend 值。

    不在这里抄一份常量：抄一份就意味着后端改名之后两边都还是绿的，而那正是这一整个
    文件要防的事。趋势是一个裸字符串（`summary` 是 `dict[str, Any]`，没有枚举），
    所以只能读源码。
    """
    source = V4_STORE.read_text(encoding="utf-8")
    body = source[source.index("def generate_emotion_report"):]
    body = body[: body.index("\n    def ", 1)]
    found = set(re.findall(r"""\btrend = ["']([a-z_]+)["']""", body))
    assert len(found) >= 3, f"没能从 v4_store 里读出趋势取值（只读到 {found}）"
    return found


def test_trend_table_covers_every_trend_the_backend_can_emit() -> None:
    table = _table("TREND_WORD")
    missing = sorted(_trends_the_store_can_emit() - table.keys())
    assert not missing, (
        f"TREND_WORD 漏了后端会发出的趋势：{missing}。"
        "这两个恰恰是情绪在变化时才出现的值，漏掉等于在最要紧的那一刻印英文。"
    )


# --------------------------------------------------------------------------
# 读的字段名真的存在
# --------------------------------------------------------------------------


def test_health_section_only_reads_fields_that_exist_on_the_record() -> None:
    body = _body("async function loadHealth()", "\n/* ====")
    read = set(re.findall(r"\bevent\.(\w+)\b", body))
    real = set(HealthEventRecord.model_fields)
    assert read, "没在 loadHealth 里找到任何 event.<字段> 的读取，断言大概没在工作"
    unknown = sorted(read - real)
    assert not unknown, (
        f"loadHealth 读了 HealthEventRecord 上不存在的字段：{unknown}。"
        "这类错不会报异常，只会让那一行永远不显示——而演示家庭是空的，没人会发现。"
    )


@pytest.mark.parametrize("field", ["title", "event_at", "kind"])
def test_health_section_actually_renders_the_load_bearing_fields(field: str) -> None:
    """光是「字段名合法」不够：漏读 `title` 的那一版也完全合法。"""
    body = _body("async function loadHealth()", "\n/* ====")
    assert f"event.{field}" in body, f"loadHealth 没有用到 event.{field}，这条记录会没有内容"


# --------------------------------------------------------------------------
# 段级判定：一致的时候不出药丸
# --------------------------------------------------------------------------


def test_a_section_that_matches_the_baseline_gets_no_pill() -> None:
    """三个「和平常一样」的绿药丸抢走了第一落点，视觉预算要留给偏离项。

    钉的是性质而不是文案：`typical` 走中性小字，别的判定才拿药丸。
    """
    loop = _body("report.sections.forEach", "host.appendChild(block);")
    assert re.search(
        r"section\.verdict === 'typical'\s*\?\s*el\('span', 'meta'", loop
    ), "分项判定又变成无条件出药丸了：一致是默认状态，不该占一个绿块"
    assert "pill" in loop, "偏离项还是要有药丸，不能连异常都一起变成小字"


def test_the_overall_verdict_keeps_its_badge() -> None:
    """顶部那个总判定保留——把它一起降级会让这一页没有结论。"""
    head = _body("const [word, tone] = verdictOf(report.overall)", "host.appendChild(head);")
    assert "report-badge" in head, "总判定的徽标不见了，这一页就没有第一落点了"


# --------------------------------------------------------------------------
# 隐私说明有自己的归属
# --------------------------------------------------------------------------


def test_the_privacy_note_is_not_a_bare_line_after_the_errand_counts() -> None:
    """它原先是段末一行裸 `.meta`，读起来像在解释上面那四个办事计数。"""
    source = _source()
    assert not re.search(
        r"host\.appendChild\(el\('p', 'meta', report\.privacy_note\)\)", source
    ), "隐私说明又变回一行裸 .meta 了，它会被读成「今天该办的事」的一部分"


def test_the_privacy_note_sits_under_a_heading_of_its_own() -> None:
    block = _body("const privacy = el(", "host.appendChild(privacy);")
    assert "care-block-head" in block, "隐私说明没有小标题，归属还是不明"
    assert "report.privacy_note" in block, "这一块里没有隐私说明本身"


# --------------------------------------------------------------------------
# 空态说清「以后会有什么 / 怎么才会有」
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "loader",
    ["async function loadHealth()", "async function loadMood()"],
)
def test_the_two_empty_sections_say_what_will_be_here_and_how(loader: str) -> None:
    """这两段在演示家庭里恒为空，所以空态就是所有人看到的正文。

    一句「还没有记录」诚实，但和「这个功能没做」在屏幕上没有区别。
    """
    body = _body(loader, "\n/* ====")
    for heading in ("这一段以后会有什么", "怎么才会有"):
        assert heading in body, f"{loader} 的空态没有写「{heading}」"


def _copy_only() -> str:
    """去掉注释，只留会被渲染出去的字面量。

    第一版直接扫整个文件，结果被 `empty()` 那段**解释为什么不许写「暂无数据」**的注释
    绊倒了——一条把自己的理由当成违规的断言。注释是给改代码的人看的，不是屏幕上的字。
    """
    source = re.sub(r"/\*.*?\*/", "", _source(), flags=re.S)
    return re.sub(r"^\s*//.*$", "", source, flags=re.M)


def test_no_section_falls_back_to_no_data_at_all() -> None:
    copy = _copy_only()
    assert "care-empty" in copy, "连空态的类名都没读到，这条断言大概没在工作"
    for phrase in ("暂无数据", "暂无记录", "没有数据"):
        assert phrase not in copy, (
            f"又出现了「{phrase}」。一个刚开通的账户里这几段本来就是空的，"
            "把正常状态说成一次失败是这一页最早的毛病。"
        )
