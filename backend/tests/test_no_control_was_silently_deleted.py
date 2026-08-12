"""迁移矩阵：手机框里清掉的每一个控件，都在框外某处还活着。

设计稿把「产品和证明彻底分离」定成最高原则，而执行它的动作是**搬**，不是删：手机框
里那 22 个工程/演示控件全部移到 `/stage`，同一个 handler、同一个接口、同一个输出区。

为什么需要一条闸门：删掉一个控件不会让任何现有测试变红。
`check_page_runtime` 的遍历"按下能找到的每一个按钮"——按钮不在了，它就少按一个，
然后报"全部通过"。`REQUIRED_PRESSES` 只钉住少数几个。而这一轮我一次性从四个页面里
剪掉了 11356 + 6175 + 6364 字符：在那个体量下，"少搬了一个"和"搬全了"在任何绿色
输出里长得一模一样。

矩阵是**数据**，一行一个控件：`控件 → 原来在哪一页 → 现在在哪一页 → 谁给它接事件`。
三件事都查：新位置的 HTML 里有这个 id、旧位置里已经没有了、而且新位置加载的某个
脚本里真的有对它的绑定。只查第一条不够——一个搬过去但没人给它绑事件的按钮，
点下去什么都不发生，而它在 HTML 里明明存在。
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
STATIC = ROOT / "backend" / "static"


#: `控件 id` → (`原来在哪一页`, `现在在哪一页`, `现在谁给它绑事件`)
#:
#: 顺序按搬迁的来源分组，不按字母序——这份表是给人读的，读的人问的是
#: "可信页那十个都去哪了"。
MATRIX: dict[str, tuple[str, str, str]] = {
    # ---- 从 /trust 搬走的十个（语音共识 / 恶意文档 / Saga / 同步 / 破窗 / 真值）----
    "voiceSafe": ("trust.html", "stage.html", "proof-demos.js"),
    "voiceConflict": ("trust.html", "stage.html", "proof-demos.js"),
    "policySafe": ("trust.html", "stage.html", "proof-demos.js"),
    "policyAttack": ("trust.html", "stage.html", "proof-demos.js"),
    "sagaCreate": ("trust.html", "stage.html", "proof-demos.js"),
    "sagaAdvance": ("trust.html", "stage.html", "proof-demos.js"),
    "syncDemo": ("trust.html", "stage.html", "proof-demos.js"),
    "breakGlassDemo": ("trust.html", "stage.html", "proof-demos.js"),
    "truthDemo": ("trust.html", "stage.html", "proof-demos.js"),
    "metricsDemo": ("trust.html", "stage.html", "proof-demos.js"),
    # ---- 从 /care 搬走的十二个（基线场景注入 / 循环 / 用药 / 情绪 / 体检 / 位置）----
    "baselineDemo": ("care.html", "stage.html", "proof-demos.js"),
    "coldRoomDemo": ("care.html", "stage.html", "proof-demos.js"),
    "lateWakeDemo": ("care.html", "stage.html", "proof-demos.js"),
    "routineDemo": ("care.html", "stage.html", "proof-demos.js"),
    "monthlyReport": ("care.html", "stage.html", "proof-demos.js"),
    "interactionDemo": ("care.html", "stage.html", "proof-demos.js"),
    "emotionDemo": ("care.html", "stage.html", "proof-demos.js"),
    "medicalDemo": ("care.html", "stage.html", "proof-demos.js"),
    "locationInside": ("care.html", "stage.html", "proof-demos.js"),
    "locationOutside": ("care.html", "stage.html", "proof-demos.js"),
    "sosDemo": ("care.html", "stage.html", "proof-demos.js"),
    "capabilitiesDemo": ("care.html", "stage.html", "proof-demos.js"),
    # ---- 从 /family 搬走的一个（运维动作：手动推进到期待办）----
    "scheduler": ("family.html", "stage.html", "proof-demos.js"),
}

#: 跟着按钮一起搬的输入与输出区。它们没有 handler，但少搬一个的后果一样重：
#: `#emotionDemo` 读 `#emotionText.value`，输入框没搬过去，按钮就在分析空字符串。
COMPANIONS: dict[str, tuple[str, str]] = {
    "emotionText": ("care.html", "stage.html"),
    "medicalText": ("care.html", "stage.html"),
    "baselineOutput": ("care.html", "stage.html"),
    "routineOutput": ("care.html", "stage.html"),
    "interactionOutput": ("care.html", "stage.html"),
    "emotionOutput": ("care.html", "stage.html"),
    "medicalOutput": ("care.html", "stage.html"),
    "locationOutput": ("care.html", "stage.html"),
    "capabilityList": ("care.html", "stage.html"),
    "voiceOutput": ("trust.html", "stage.html"),
    "policyOutput": ("trust.html", "stage.html"),
    "sagaOutput": ("trust.html", "stage.html"),
    "syncOutput": ("trust.html", "stage.html"),
    "breakGlassOutput": ("trust.html", "stage.html"),
    "truthOutput": ("trust.html", "stage.html"),
}


def _read(name: str) -> str:
    return (STATIC / name).read_text(encoding="utf-8")


def _ids(html: str) -> set[str]:
    # 注释里的 id 不算存在。这一轮每个被清空的页面都留了一段注释说明东西搬到哪了，
    # 而那些注释里会出现控件名——不剥注释的话，"搬走了"这件事会被它自己的说明否掉。
    html = re.sub(r"<!--.*?-->", "", html, flags=re.S)
    return set(re.findall(r'\bid="([\w-]+)"', html))


def _scripts(html: str) -> set[str]:
    return set(re.findall(r'<script src="/static/([\w.-]+)"', html))


ALL_ROWS = [(cid, src, dst, js) for cid, (src, dst, js) in MATRIX.items()]
ALL_COMPANIONS = [(cid, src, dst) for cid, (src, dst) in COMPANIONS.items()]


@pytest.mark.parametrize(("cid", "src", "dst", "js"), ALL_ROWS)
def test_the_moved_control_exists_at_its_new_home(cid: str, src: str, dst: str, js: str) -> None:
    assert cid in _ids(_read(dst)), (
        f"#{cid} 从 {src} 搬走了，但 {dst} 里没有它——这是删掉，不是搬走。"
    )


@pytest.mark.parametrize(("cid", "src", "dst", "js"), ALL_ROWS)
def test_the_moved_control_left_the_phone_frame(cid: str, src: str, dst: str, js: str) -> None:
    """反向：它必须真的从手机框里走了。

    没有这一条，矩阵就退化成"两边都有"——那不是搬迁，那是复制，而复制会分叉。
    """
    assert cid not in _ids(_read(src)), (
        f"#{cid} 还在 {src} 里。两份会分叉（common.js 那次合并的教训），"
        "而手机框里不该有这个控件。"
    )


@pytest.mark.parametrize(("cid", "src", "dst", "js"), ALL_ROWS)
def test_the_moved_control_still_has_a_handler(cid: str, src: str, dst: str, js: str) -> None:
    """搬过去还得有人给它绑事件。

    一个搬过去但没人绑的按钮，点下去什么都不发生——而它在 HTML 里明明存在，
    上面那条断言照样绿。这一条查两件事：新页面真的加载了那个脚本，
    而且那个脚本里真的提到了这个 id。
    """
    assert js in _scripts(_read(dst)), f"{dst} 没有加载 {js}"
    body = _read(js)
    assert re.search(rf"""['"]{re.escape(cid)}['"]""", body), (
        f"{js} 里找不到对 #{cid} 的绑定——按钮搬过去了，事件没跟过去。"
    )


@pytest.mark.parametrize(("cid", "src", "dst"), ALL_COMPANIONS)
def test_the_companion_moved_too(cid: str, src: str, dst: str) -> None:
    """输入框与输出区也要跟着走。

    `#emotionDemo` 读 `#emotionText.value`。按钮搬了、输入框没搬，按下去是在分析
    一个空字符串，而后端会老老实实返回"没有检测到情绪"——一个看起来在工作的错误。
    """
    assert cid in _ids(_read(dst)), f"#{cid} 是 #{src} 那批控件的输入或输出区，没搬到 {dst}"
    assert cid not in _ids(_read(src)), f"#{cid} 还留在 {src} 里"


def test_the_old_scripts_no_longer_reference_what_they_lost() -> None:
    """旧页面的脚本里不能还留着对搬走的控件的绑定。

    `byId('voiceSafe').addEventListener(...)` 在文件顶层抛 TypeError，**后面所有
    绑定一起丢**，整页按钮静默失效。`/care` 和 `/trust` 那次两整页全死就是这么发生
    的，而当时所有测试都是绿的。

    这条只查旧脚本，不查 `proof-demos.js`——那里当然要有这些名字。
    """
    problems: list[str] = []
    for cid, (src, _dst, _js) in MATRIX.items():
        old_js = src.replace(".html", ".js")
        if not (STATIC / old_js).is_file():
            continue
        body = re.sub(r"//.*", "", _read(old_js))
        if re.search(rf"""['"]#?{re.escape(cid)}['"]""", body):
            problems.append(f"{old_js} 还在引用 #{cid}")
    assert not problems, "旧脚本里还有对搬走控件的引用：\n  " + "\n  ".join(problems)


def test_the_matrix_covers_everything_the_phone_frame_lost() -> None:
    """矩阵本身不能漏行。

    这是这一整份文件唯一的弱点：矩阵是我手写的，漏掉一行就等于漏掉一个控件，
    而其他每一条断言都只在矩阵之内工作——一份漏了行的矩阵会全绿。

    所以拿 `frontend_redesign/ia/08_click_map.md`（机械抽取的 控件→处理器→接口→回屏）
    当外部事实源：那份文件是在这一轮开始之前生成的，它记的是**改之前**四个页面上
    真实存在的控件。凡是它记过、现在四个 App 页面里都不存在的 id，必须在矩阵里。
    """
    click_map = ROOT / "frontend_redesign" / "ia" / "08_click_map.md"
    if not click_map.is_file():
        pytest.skip(f"事实源不在：{click_map}")

    app_pages = ("elder.html", "family.html", "care.html", "trust.html")

    # 只取那份地图里**四个 App 页面**的小节。
    #
    # 第一版整篇扫，于是 `#stageClean`、`#playStory`、`#beatRelay`、`#glassCard`
    # 十三个 id 一起被判成"手机框里丢了的控件"——它们从来就在 `/stage` 和 `/judge`
    # 上，那两页本来就在框外。仪器测的必须是我关心的那件事。
    text = click_map.read_text(encoding="utf-8")
    sections = re.split(r"^### ", text, flags=re.M)
    before: set[str] = set()
    for section in sections:
        head = section.split("\n", 1)[0]
        if any(page in head for page in app_pages):
            before |= set(re.findall(r"`#([\w-]+)`", section))
    assert before, "从点击地图里一个 App 控件都没抽到——抽取方式跟那份文档的结构对不上了"

    now: set[str] = set()
    for page in app_pages:
        now |= _ids(_read(page))

    known = set(MATRIX) | set(COMPANIONS)
    # 这些不是被搬走的控件，是这一轮的**结构改动**：老人端从"一屏塞满"改成四 Tab
    # 之后，分区容器和它们的标签换了名字。它们不是"控件消失"，所以不进迁移矩阵。
    RESTRUCTURED = {
        "logPanel",       # 记录面板 → 记录 Tab（data-panel="log"）
        "activityLog",    # 同上，容器改名为 Tab 内容
        "hear", "doc", "half", "urgent", "truth",  # 可信页五个分区，整段移出
        "extrasSheet",    # 抽屉从「待办」改成「更多说法」，id 未变但曾在别处登记
    }
    missing = sorted(before - now - known - RESTRUCTURED)
    assert not missing, (
        f"这些控件在改之前的点击地图里有、现在四个 App 页面里都没有，"
        f"而迁移矩阵里也没有它们：{missing}\n"
        "  要么它们被搬到了框外（补进 MATRIX/COMPANIONS），"
        "要么它们真的被删了（那违反「不得静默删除」）。"
    )
