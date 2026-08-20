"""屏幕不许把失败讲成成功。

两处都是驱动出来的，两处都长得完全正常：

## ① 审计页的状态行写死了 `class="notice good"`

`judge.html:102` 上是 `notice good`，而 `judge.js` 的五处写入**只改
`textContent`**。于是：

    boot() 失败              错误消息                   印成绿的
    run() 里任何一步失败      错误消息                   印成绿的
    整条家庭链自校验没通过    「……自校验：没通过。」     印成绿的

这是**审计页**——它存在的全部意义就是「不对的时候要看得出来」。
一句「没通过」配一条绿边，比不显示更糟：它把一个失败讲成了一个成功。

## ② 家人端三照护屏那句概括从来没被换掉

`loadCare()` 里 `.companion-note` 只换了 `strong`，`span` 留着交付包写死的
「上午起得稍晚一些，没有需要立刻处理的异常。」——一句关于**今天早上**的
具体断言，编的。家人视图那一侧两行都换，照护这一侧漏了一行，
同一个组件在两个视图里一个说真话一个说假话。

而且 `if (dailyReport)` 原先没有 else：日报一取不到，这一格就一直挂着
「今天和平常差不多 / 上午起得稍晚一些，没有需要立刻处理的异常。」——
**后端断了，屏幕上却是一句让人安心的具体断言**。

## 怎么找到的

把静态 HTML 里的中文抽出来当候选，页面加载完（真身份、真请求）之后
再看屏幕上还剩哪些**一字不差**。剩下的里面，带数字/单位/时间特征的
几乎一定是编的。②就是这么剩出来的。
"""
from __future__ import annotations

import io
import re
from pathlib import Path

STATIC = Path(__file__).resolve().parents[1] / "static"

#: 交付包写死的那一句。它出现在 HTML 里是**对的**（那是初始态），
#: 判据管的是「接线有没有把它换掉」。
FABRICATED = "上午起得稍晚一些，没有需要立刻处理的异常。"


def _src(name: str) -> str:
    return io.open(STATIC / name, encoding="utf-8").read()


def _strip_comments(js: str) -> str:
    js = re.sub(r"/\*.*?\*/", " ", js, flags=re.S)
    return re.sub(r"^\s*//.*$", " ", js, flags=re.M)


def _function_body(js: str, header: str) -> str:
    """从 `header` 起按花括号配对取出整个函数体。

    为什么不用「锚点往前数 500 字」：变异一旦让那一段变短，取景框就整体
    往前滑，滑到**另一个函数**里去。实测「照护屏那句概括又不换了」这个变体
    就是这么逃掉的——窗口滑进了 `loadHeader()`，那里的 `span` 写入让判据照样绿。
    """
    at = js.find(header)
    assert at >= 0, f"找不到 `{header}`"
    start = js.index("{", at)
    depth = 0
    for i in range(start, len(js)):
        if js[i] == "{":
            depth += 1
        elif js[i] == "}":
            depth -= 1
            if depth == 0:
                return js[start:i + 1]
    raise AssertionError(f"`{header}` 的花括号没配上")


# ---- ① 审计页 ---------------------------------------------------------------

def test_the_audit_status_line_does_not_start_out_green() -> None:
    html = _src("judge.html")
    line = re.search(r'<p class="([^"]*)"[^>]*id="judgeStatus"', html)
    assert line, "judge.html 里找不到 #judgeStatus"
    classes = line.group(1).split()
    assert "good" in classes or "info" in classes or "warning" in classes, \
        "这一行连一个语气类都没有，样式会掉"
    assert "good" not in classes, (
        "审计页的状态行开局就是绿的。它下一句可能是启动失败的错误消息，"
        "而颜色不会跟着换——一个失败会被印成成功。")


def test_every_status_write_sets_the_tone_too() -> None:
    js = _strip_comments(_src("judge.js"))
    #: `setStatus` 自己那一行是唯一允许直写的地方。
    body = re.search(r"function setStatus\(text, tone\) \{.*?\n\}", js, re.S)
    assert body, "judge.js 里找不到 setStatus"
    rest = js.replace(body.group(0), "")
    stray = re.findall(r"statusEl\.textContent\s*=", rest)
    assert not stray, (
        f"还有 {len(stray)} 处直接改 `statusEl.textContent`——"
        "文字换了颜色没换，就是把上一次的语气留给了这一次的内容")
    assert re.search(r"classList\.remove\(([^)]*)'good'", body.group(0)), \
        "setStatus 没有把旧语气摘掉，类会越叠越多"


def test_a_broken_chain_is_not_reported_in_green() -> None:
    js = _strip_comments(_src("judge.js"))
    call = re.search(r"setStatus\(\s*`这一笔在链上.*?\);", js, re.S)
    assert call, "找不到写自校验结果那一处"
    assert "state.chainValid ? 'good' : 'bad'" in call.group(0), (
        "链没通过的时候语气不是 `bad`——"
        "这一页存在的全部意义就是不对的时候要看得出来")


def test_an_error_message_is_painted_bad() -> None:
    js = _strip_comments(_src("judge.js"))
    calls = re.findall(r"setStatus\(([^;]*?),\s*'bad'\)", js, re.S)
    assert len(calls) >= 2, (
        f"只有 {len(calls)} 处错误路径配了 `bad` 语气；"
        "`boot()` 和 `report()` 两条都要")


def test_the_audit_page_never_shows_a_raw_browser_exception() -> None:
    """实测（掐掉 `/v2/audit` 再刷新）屏幕上是**「Failed to fetch」**——
    原始浏览器异常，英文，印在审计页上。

    这个仓库为这件事准备了 `errorWords`：它按 `.status` 分型，说得清是
    「连不上」「服务器拒绝了」还是「这台服务上没开」。规矩本身也写死在
    项目里：界面上不许出现英文枚举值。
    """
    js = _strip_comments(_src("judge.js"))
    raw = re.findall(r"setStatus\(\s*error\.message", js)
    assert not raw, f"{len(raw)} 处把原始异常消息直接印上屏幕了"
    body = _function_body(js, "function report(error, outSelector)")
    assert "errorWords(" in body, "`report()` 没有过 errorWords 这一层"
    assert "error.message" not in body, \
        "`report()` 里还有一处直接用 `error.message`（输出区那一处也要换）"
    boot = re.search(r"boot\(\)\.catch\(\(error\) => \{.*?\}\);", js, re.S)
    assert boot and "errorWords(" in boot.group(0), \
        "`boot()` 的失败路径没有过 errorWords"


# ---- ② 家人端三照护屏那句概括 -------------------------------------------------

def test_the_delivery_packages_sentence_is_still_the_initial_state() -> None:
    """判据本身要有靶子。这一句从 HTML 里消失了，下面两条就成了空转。"""
    assert FABRICATED in _src("family-v3.html"), (
        f"交付包那句「{FABRICATED}」不在 HTML 里了——下面两条判据在空转，"
        "要么改判据，要么这次改动本身就不需要了")


def test_the_care_summary_replaces_both_lines() -> None:
    js = _strip_comments(_src("family3.js"))
    care = _function_body(js, "async function loadCare()")
    assert "fillVein('today'" in care, "取错函数了"

    #: 只看**日报取到了**那一支。整个 `loadCare()` 一起看是不够的：
    #: 取不到的那一支自己也写 `span`，于是成功路径把这一行删掉之后，
    #: 判据被兜底那一行满足，照样绿。实测这个变体就是这么逃掉的。
    ok_branch = _function_body(care, "if (dailyReport)")
    assert "$('.companion-note', view)" in ok_branch, \
        "日报取到的那一支根本没碰这一格，判据的取景框不对"
    assert "text($('strong', note)" in ok_branch, "标题那一行没换"
    assert "text($('span', note)" in ok_branch, (
        f"正文那一行没换——交付包写死的「{FABRICATED}」会留在屏幕上。"
        "家人视图那一侧两行都换了，这一侧漏了一行。")


def test_a_missing_daily_report_does_not_leave_a_reassuring_sentence() -> None:
    js = _strip_comments(_src("family3.js"))
    fallback = re.search(r"if \(!dailyReport\) \{.*?\n    \}", js, re.S)
    assert fallback, (
        "`if (dailyReport)` 没有 else 分支——日报一取不到，这一格就一直挂着"
        f"「今天和平常差不多 / {FABRICATED}」。"
        "后端断了而屏幕上是一句让人安心的具体断言，比空着糟得多。")
    body = fallback.group(0)
    assert "companion-note" in body, "兜底没有写到那一格上"
    assert FABRICATED not in body

    #: 两行**各查各的**。只查「整段里有没有『取不到』」是不够的：
    #: 实测把 `span` 换成「今天一切正常。」之后，`strong` 里那句
    #: 「今天的概括暂时取不到」仍然让判据绿——而屏幕上那句让人安心的
    #: 具体断言正是这条判据要挡的东西。
    lines = dict(re.findall(
        r"text\(\$\('(strong|span)', note\), '([^']*)'\)", body))
    assert set(lines) == {"strong", "span"}, \
        f"兜底没有把两行都写掉，只写了 {sorted(lines)}"
    #: 「一切正常 / 差不多 / 没事 / 平稳」这一类是**关于老人今天状态**的断言。
    #: 后端断了的时候，我们对那件事一无所知。
    calm = re.compile(r"正常|差不多|没事|平稳|一切都好|没有异常")
    for where, words in lines.items():
        assert not calm.search(words), (
            f"取不到日报的时候，{where} 那一行说的是「{words}」——"
            "后端断了，我们对她今天怎么样一无所知，不能替她宣称没事")
    assert any("取不到" in w or "暂时" in w for w in lines.values()), \
        "兜底没说清是取不到，而不是真的没事"


def test_no_wiring_file_reprints_the_fabricated_sentence() -> None:
    """接线里不许出现这句话——那等于把编的内容从 HTML 搬进了 JS。

    注释里出现是可以的（这一轮的说明里就引了它），所以先把注释剥掉。
    第一版没剥，判据被我自己写的那段注释咬红了。
    """
    for name in ("family3.js", "family.js", "care.js"):
        assert FABRICATED not in _strip_comments(_src(name)), \
            f"{name} 里印了这句编出来的话"
