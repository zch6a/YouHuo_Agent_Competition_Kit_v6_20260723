"""日报的结论只说一遍：`headline` 是整句，`headline_detail` 只有依据。

## 为什么要分成两半

家人端的页头用一句**短的**说结论（`family.js` 的 `VERDICT_SENTENCE`），因为完整
headline 最长 38 字，在 390px 上按 26px 排是四行、吃掉四分之一首屏，而
「需要您确认」必须留在第一屏。然后它紧接着又把整句 headline 原样放在下面一行：

    H1     今天该有的记录还没出现
    紧接着 今天该有的记录还没出现（外出：今天还没有有效记录），建议打个电话问一声。

每个状态都在复述，`unknown` 这一条**逐字**相同，所以看起来最像 bug——而演示数据
正好停在这个状态，也就是评委看到的第一屏。

修法不是在前端截字符串（对一个结构化句子做字符串手术，措辞一变就错），
而是由产出这句话的地方同时给出两半。

## 这份文件守的

  ① 每个状态的 `headline_detail` **不复述**结论那半句
  ② 「没有额外依据」用空字符串表示，前端据此不画那一行——不是画一行空的
  ③ `headline` 一个字没改（推送和 /care 用的是它）
"""

from __future__ import annotations

import pytest

from youhuo.baseline_models import Verdict
from youhuo.baseline_services import BaselineAnalyzer


def _parts(overall, deviations=(), established=True, days=14):
    return BaselineAnalyzer._headline_parts(overall, list(deviations), established, days)


#: 页头那句短结论，逐字抄自 `family.js` 的 `VERDICT_SENTENCE`。
#:
#: 抄一份在这里是有代价的（两处要一起改），但这一条判据要问的正是
#: 「detail 会不会把页头已经说过的话再说一遍」，绕不开它。
VERDICT_SENTENCE = {
    Verdict.TYPICAL: "他今天和平常差不多",
    Verdict.NOTICE: "他今天有一点和平常不同",
    Verdict.MARKED: "他今天和平常不太一样",
    Verdict.UNKNOWN: "今天该有的记录还没出现",
    Verdict.PENDING: "今天还没过完，还不好说",
}


@pytest.mark.parametrize("overall", list(VERDICT_SENTENCE))
def test_the_detail_does_not_repeat_the_conclusion(overall: Verdict) -> None:
    _headline, detail = _parts(overall)
    if not detail:
        return  # 空 = 没有额外依据，前端不画这一行。下一条测它。
    # 页头那句话的**核心短语**不许原样出现在依据里。
    core = VERDICT_SENTENCE[overall].removeprefix("他")
    assert core not in detail, (
        f"{overall} 的 headline_detail 复述了页头那句结论：\n"
        f"  页头：{VERDICT_SENTENCE[overall]}\n"
        f"  依据：{detail}\n"
        "  两行说同一句话，而这一页的第一屏本来就不够用。"
    )


def test_no_extra_evidence_means_empty_not_whitespace() -> None:
    """「结论本身就是全部」要用空字符串说，不能给一行看不见的空白。

    前端按真假决定画不画那一行。给一个空格会让它画出一行空的——屏幕上多一道
    莫名其妙的间距，而没有任何东西解释它。
    """
    for overall in (Verdict.TYPICAL, Verdict.PENDING):
        _headline, detail = _parts(overall)
        assert detail == "", f"{overall} 的 detail 应当是空字符串，得到 {detail!r}"


def test_the_full_headline_is_unchanged() -> None:
    """`headline` 保持原样：推送与 /care 用的是它，这次是加法不是改写。"""
    assert _parts(Verdict.TYPICAL)[0] == "今天和他平常差不多。"
    assert _parts(Verdict.PENDING)[0] == "今天还没过完，还不到下结论的时候。"
    assert _parts(Verdict.UNKNOWN)[0].startswith("今天该有的记录还没出现")
    not_established = _parts(Verdict.UNKNOWN, established=False, days=3)[0]
    assert "已记录 3 天" in not_established


def test_the_unknown_state_keeps_its_advice_in_the_detail() -> None:
    """`unknown` 是重复最严重的那一条，也是新访客第一眼看到的那一条。

    它的依据里必须还留着「建议打个电话问一声」——那是这份日报唯一一句让家人
    **做点什么**的话，不能在拆分里丢掉。
    """
    _headline, detail = _parts(Verdict.UNKNOWN)
    assert detail, "unknown 的依据是空的——那句「建议打个电话问一声」丢了"
    assert "打个电话" in detail, f"依据里没有那句建议：{detail}"
    assert "今天该有的记录还没出现" not in detail, f"依据复述了结论：{detail}"
