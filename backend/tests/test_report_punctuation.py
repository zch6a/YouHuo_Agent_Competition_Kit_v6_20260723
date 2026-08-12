"""家属端日报那一句话的标点，不许连排、不许一句两个冒号。

这一条守的是**拼装**，不是措辞。日报的结论句是「模板 + 片段」拼出来的，而片段
（`ChannelDeviation.explanation`）本身是一句**完整的话**：`起床：比他平常晚了 …。`
把一句完整的话嵌进另一句话里，标点必然撞车。实际渲染出来的（家属端第一屏、
`#famHeadline`，子女点开这一页第一眼读到的那行）：

    今天该有的记录还没出现（外出：今天还没有有效记录。），建议打个电话问一声。
                                             ~~~~  「。），」三个标点连排

    今天和他平常不太一样：起床：比他平常晚了 1 小时 40 分钟（平常 06:08 前后）。
                    ~~          ~~          一句话里两个冒号，读起来像嵌套坏了

两条都不是错字，是**结构**问题：谁负责句末标点、谁负责 label，没有定下来。所以修法
是给片段两种嵌入形态（`.parenthetical` / `.inline`），judge 由调用处挑；而这条闸门
钉的是结果——不管以后谁改措辞，拼出来的句子标点必须是干净的。

为什么以前看不见：日报文案是**运行时**从数据拼的，源码里 grep 不到那句话；截图审查
拍的是空态或 TYPICAL 分支（「今天和他平常差不多。」——恰好是唯一不拼片段的分支）。
"""
from __future__ import annotations

import re

import pytest

from youhuo.baseline import Channel, ChannelDeviation, Verdict
from youhuo.baseline_services import BaselineAnalyzer

#: 中文里不该连排的标点组合。句末标点后面直接跟另一个标点，就是拼装漏了 strip。
FORBIDDEN_PAIRS = ["。）", "。，", "。。", "，，", "：：", "。；", "；。", "，。", "、。"]


def _deviation(channel: Channel, verdict: Verdict, explanation: str) -> ChannelDeviation:
    return ChannelDeviation(
        channel=channel, verdict=verdict, observed=1.0, center=1.0,
        delta_minutes=100.0, sigma=3.2, explanation=explanation,
    )


#: 每个分支一个用例。片段用**真实形态**（`{label}：…。`），因为那正是缺陷的来源；
#: 换成一个手写的干净片段，这条闸门就测不到任何东西了。
CASES = {
    "UNKNOWN·该有记录却没有": (
        Verdict.UNKNOWN,
        [_deviation(Channel.OUTING, Verdict.UNKNOWN, "外出：今天还没有有效记录。")],
    ),
    "MARKED·时刻偏离": (
        Verdict.MARKED,
        [_deviation(Channel.WAKE, Verdict.MARKED,
                    "起床：比他平常晚了 1 小时 40 分钟（平常 06:08 前后）。")],
    ),
    "NOTICE·次数偏离": (
        Verdict.NOTICE,
        [_deviation(Channel.OUTING, Verdict.NOTICE,
                    "外出：比他平常多了 100 次（平常 368 次）。")],
    ),
    "TYPICAL": (Verdict.TYPICAL, []),
    "PENDING": (Verdict.PENDING, []),
}


@pytest.mark.parametrize("name", list(CASES))
def test_the_headline_has_no_stacked_punctuation(name: str) -> None:
    overall, deviations = CASES[name]
    line = BaselineAnalyzer._headline(overall, deviations, established=True, observed_days=30)

    hits = [pair for pair in FORBIDDEN_PAIRS if pair in line]
    assert not hits, f"{name} 拼出来的结论句有连排标点 {hits}：\n  {line}"


@pytest.mark.parametrize("name", list(CASES))
def test_no_sentence_carries_two_colons(name: str) -> None:
    """一句话里两个「：」——读者会以为是嵌套，而这里没有嵌套，只有拼漏。"""
    overall, deviations = CASES[name]
    line = BaselineAnalyzer._headline(overall, deviations, established=True, observed_days=30)

    for sentence in filter(None, (s.strip() for s in line.split("。"))):
        assert sentence.count("：") <= 1, (
            f"{name} 的这一句里有 {sentence.count('：')} 个冒号：\n  {sentence}\n  整句：{line}"
        )


def test_the_gate_catches_the_two_sentences_that_actually_shipped() -> None:
    """变异：按**修之前**的写法拼一遍，两条断言必须都红。

    上面那两条都在断言"没有"。一条永远断言"没有"的检查，在拼装方式改回去的那天
    会继续绿——所以这里把真的显示过的那两句原样拼出来，当场验它抓得到。

    这两个字符串不是我编的：它们是 `.explanation`（完整句）直接嵌进模板的结果，
    也就是这次修复之前 `#famHeadline` 上真正渲染出来的字。
    """
    outing = CASES["UNKNOWN·该有记录却没有"][1][0]
    wake = CASES["MARKED·时刻偏离"][1][0]

    shipped_unknown = f"今天该有的记录还没出现（{outing.explanation}），建议打个电话问一声。"
    shipped_marked = f"今天和他平常不太一样：{wake.explanation}"

    assert any(p in shipped_unknown for p in FORBIDDEN_PAIRS), (
        f"连排标点的检查没抓到它自己要找的东西：{shipped_unknown}"
    )
    two_colon = [s for s in shipped_marked.split("。") if s.count("：") >= 2]
    assert two_colon, f"双冒号的检查没抓到它自己要找的东西：{shipped_marked}"

    # 而修好之后的版本必须干净——否则上面两条是靠"两边都脏"蒙对的。
    fixed_unknown = f"今天该有的记录还没出现（{outing.parenthetical}），建议打个电话问一声。"
    fixed_marked = f"今天和他平常不太一样：{wake.inline}"
    assert not any(p in fixed_unknown for p in FORBIDDEN_PAIRS), fixed_unknown
    assert all(s.count("：") <= 1 for s in fixed_marked.split("。")), fixed_marked


def test_numbers_are_spaced_off_the_chinese() -> None:
    """阿拉伯数字与汉字之间一律留半角空格——三个分支曾经是三套写法。

    `_describe` 同一个函数里：`（06:08 前后）` 有空格、`了1 小时 40 分钟（平常06:08前后）`
    时有时无、`了 100 次（平常 368 次）` 有。同一句话里三种约定，读者看不出规律，
    只看得出没校对过。
    """
    from youhuo.baseline import ChannelBaseline

    from youhuo.baseline import _describe

    def described(is_time: bool, delta: float, verdict: Verdict) -> str:
        base = ChannelBaseline(
            channel=Channel.WAKE if is_time else Channel.OUTING,
            established=True, days=30, center=368.0, spread=30.0, reason="",
        )
        return _describe(base, "起床" if is_time else "外出", delta, verdict)

    lines = [
        described(True, 100.0, Verdict.MARKED),
        described(True, 0.0, Verdict.TYPICAL),
        described(False, 100.0, Verdict.MARKED),
    ]
    for line in lines:
        # 汉字紧贴阿拉伯数字（两个方向都查）。冒号两侧的 `06:08` 是一个整体，不算。
        stuck = re.findall(r"[一-鿿]\d|\d[一-鿿]", line.replace("：", " "))
        # `06:08` 里的数字挨着的是数字，不会命中；`1 小时` 有空格，也不会。
        assert not stuck, f"数字紧贴汉字 {stuck}：\n  {line}"
