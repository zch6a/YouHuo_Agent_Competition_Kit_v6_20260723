"""照护页的写操作：接上了没有，以及「承诺了却不存在」不许再回来。

这一页此前是**纯读**的——七个分区、零个写操作。而它同时在两段空态文案里
承诺了界面上根本不存在的能力：

    安全：「您可以添：写名字、什么关系、电话。电话存进去就是打码的」
    身体：「也可以直接添一条，写清哪一天、什么事——您和他都能添」

一段解释「你可以做 X」的文字配一个做不了 X 的界面，比什么都不写更糟：
读的人会去找那个入口，找不到，然后怀疑是自己没看见。

下面的闸门分两层：
  · 静态：care.js 里那三条写路径在不在，有没有按项目约定包 `once()`、
    有没有把语气交给后端
  · 行为：三个端点在**家属身份**下真的能写进去，而且写完读得回来

第二层是必须的。「care.js 里出现了这个字符串」只证明写了，不证明接上了——
这个项目有过一次 109/109 的功能审核通过，而 20 句自然话里 15 句掉进兜底。
"""
from __future__ import annotations

import io
import re
from pathlib import Path

import pytest

STATIC = Path(__file__).resolve().parents[1] / "static"
CARE_JS = STATIC / "care.js"
CARE_HTML = STATIC / "care.html"


def _js() -> str:
    return io.open(CARE_JS, encoding="utf-8").read()


def _strip_comments(src: str) -> str:
    """把注释剥掉再判断。

    这道检查的第一版是直接在全文里搜端点字符串——而这个文件的注释密度很高，
    一条被注释掉的旧路径照样能让它变绿。同类问题
    `test_only_the_conversation_screen_opts_into_the_frame` 里已经栽过一次。
    """
    src = re.sub(r"/\*.*?\*/", "", src, flags=re.S)
    return re.sub(r"^\s*//.*$", "", src, flags=re.M)


# --------------------------------------------------------------------------
# 静态层
# --------------------------------------------------------------------------

WRITE_PATHS = {
    "记一次已吃": "/api/v1/medications/${plan.id}/taken",
    "这次没吃": "/api/v1/medications/${plan.id}/skipped",
    "记一笔身体数据": "/api/v1/health/events",
    "添一位亲友": "/v4/contacts",
}


@pytest.mark.parametrize("what,path", sorted(WRITE_PATHS.items()))
def test_care_actually_calls_the_write_endpoint(what: str, path: str) -> None:
    code = _strip_comments(_js())
    assert path in code, f"「{what}」没有真的打 {path}——照护页这一段又变回只读了"


@pytest.mark.parametrize("path", sorted(set(WRITE_PATHS.values())))
def test_every_write_is_a_post(path: str) -> None:
    """写路径必须带 method: 'POST'。

    `api()` 默认是 GET。少写这一行，请求照样发出去、照样 200——
    发的是那条路径的 GET，而它压根不存在，于是 405 或 404，
    在界面上和「后端挂了」长得一模一样。
    """
    code = _strip_comments(_js())
    idx = code.index(path)
    window = code[idx:idx + 260]
    assert "method: 'POST'" in window or 'method: "POST"' in window, (
        f"{path} 附近没有 method: 'POST'")


def test_every_write_button_is_debounced() -> None:
    """每一条写路径都要在 `once()` 里。

    慢网络下连点两次「记一次已吃」会扣两次库存——而库存是「还够几天」的分母，
    多扣一次，屏幕上就少几天，没有任何地方会报错。

    第一版是「往前 900 字符内找 once(」——那个判据错了，而且是**假红**：
    用药那两条写在 `actionButton(...)` 的实参里，防重复在助手内部，
    词法上并不在调用点之前。判据得认代码真正的两种写法：
      · 交给 `actionButton()`（助手内部包 once）
      · 自己在 `once()` 回调里发请求（两个表单的 submit）
    """
    code = _strip_comments(_js())

    # 助手自己必须包 once——不然下面那条「交给助手就算数」的推理不成立
    helper = code[code.index("function actionButton("):]
    helper = helper[:helper.index("\n}\n") + 3]
    assert "once(" in helper, "actionButton() 内部没有 once()，交给它的写操作全都会被连点"

    for path in sorted(set(WRITE_PATHS.values())):
        idx = code.index(path)
        before = code[max(0, idx - 900):idx]
        ok = "once(" in before or "actionButton(" in before
        assert ok, f"{path} 既不在 once() 里、也不经过 actionButton()，会被连点"


def test_the_tone_comes_from_the_backend() -> None:
    """成功回执的语气由后端给，不由前端一律画绿。

    `POST /api/v1/medications/{id}/taken` 在「今天该吃的都记过了」时返 409，
    在「这一格刚才已经记过」时返 **200 + alreadyRecorded**。后者要是被画成
    绿色的成功框，家属没法把它和真的记上了区分开——family.js 为同一件事
    留过一段注释：「一次取消画成绿色成功框，家属无法把它和真的批准成功区分开」。
    """
    code = _strip_comments(_js())
    # 第一版是 `assert "toneOf" in code`——把一处改成写死的 'good' 之后它照样绿，
    # 因为另一处还在。判据得是「每一个报告后端结果的 notify 都问过 toneOf」。
    reporting = [m for m in re.finditer(r"notify\(([^;]{0,200}?)\);", code, re.S)
                 if "data" in m.group(1)]
    assert reporting, "找不到任何报告后端结果的 notify()"
    hardcoded = [" ".join(m.group(1).split())[:70] for m in reporting
                 if "toneOf" not in m.group(1)]
    assert not hardcoded, (
        "这些 notify() 报的是后端的返回，语气却是写死的：\n  " + "\n  ".join(hardcoded))


def test_the_notice_host_exists_and_is_separate_from_status() -> None:
    """回执有自己的位置，不和连接状态共用一个。

    合成一条的话，一次成功的记药会把连接状态覆盖掉；而下一次网络出问题时，
    人会以为是自己刚才那个操作失败了。
    """
    html = io.open(CARE_HTML, encoding="utf-8").read()
    assert 'id="careNotice"' in html
    assert 'id="status"' in html
    assert html.index('id="status"') < html.index('id="careNotice"')


# --------------------------------------------------------------------------
# 「承诺了却不存在」不许回来
# --------------------------------------------------------------------------

def test_no_promise_without_an_input() -> None:
    """空态文案里说「您可以添」，界面上就必须有地方添。

    这一条守的是这个文件真发生过的缺陷：`futureBlock` 里写着
    「您可以添：写名字、什么关系、电话」，而 /care 上没有任何输入框。

    判据是「出现承诺措辞」→「同一个文件里有 `<input>` 的构造」。故意写得宽：
    它防的是**整类**回归（把入口删掉、只留说明），不是某一句话。
    """
    code = _js()
    promises = re.findall(r"[您你]可以[添记填写][^'\"，。]{0,12}", code)
    if not promises:
        pytest.skip("没有承诺措辞，这条无从谈起")
    stripped = _strip_comments(code)
    # 这个文件建元素走的是自己的 `el()` 助手，不是裸 `createElement`。
    # 第一版只认后者，于是在一个**确实有三个输入框**的文件上报红。
    builds_input = ("el('input'" in stripped or 'el("input"' in stripped
                    or "createElement('input')" in stripped
                    or 'createElement("input")' in stripped)
    assert builds_input, f"文案里承诺了 {promises[:3]}，但 care.js 一个输入框都没建"
    # 光建出来不够——得**挂进页面**才点得到。
    #
    # 第一版查的是 `form.append`，而那一行在 `contactForm()` **内部**：把
    # `host.appendChild(contactForm())` 注释掉之后，表单函数还在、里面的 append
    # 也还在，门照样绿，而页面上一个输入框都没有。要查的是调用点。
    for builder in ("contactForm", "healthForm"):
        called = re.findall(rf"appendChild\(\s*{builder}\(\s*\)\s*\)", stripped)
        assert called, f"{builder}() 定义了但没有任何地方把它挂进页面"


def test_the_add_forms_have_visible_labels() -> None:
    """标签是可见的 `<label for>`，不是 placeholder。

    这一页的读者常常在电话里一边问老人一边填，填到第三格已经不记得第一格是什么。
    placeholder 在打第一个字时就消失了。
    """
    code = _strip_comments(_js())
    assert "lab.htmlFor" in code, "care.js 的表单没有把 <label> 绑到输入框上"
    assert "placeholder" not in code or code.count("lab.htmlFor") >= 1


def test_empty_submit_says_something() -> None:
    """只打空格的提交必须说话。

    `required` 在值是空格时是**满足**的。family.js 为这一条留过注释：
    「屏幕上什么都不发生，反复点也一样」。
    """
    code = _strip_comments(_js())
    # 第一版是 `code.count(".trim()") >= 4`。删掉两处之后剩下的还够数，门照样绿——
    # 一个总量阈值管不住「哪一个字段」。改成逐个必填字段查它自己那一行。
    REQUIRED = {
        "displayName": "添亲友的称呼",
        "relation": "添亲友的关系",
        "label": "记一笔的项目",
    }
    for var, what in REQUIRED.items():
        m = re.search(rf"const {var} = ([^;]+);", code)
        assert m, f"找不到 {var} 的取值（{what}）"
        assert ".trim()" in m.group(1), (
            f"{what} 读进来没有 trim()——只打空格时 required 是满足的，"
            f"于是点了没反应、再点还是没反应，而屏幕上什么都不说")
    assert "还没写称呼" in code and "还没写数值" in code, (
        "空值分支没有给出人话——静默失败是这个项目明确禁止的")


def test_no_inline_style_or_english_enum_in_the_new_markup() -> None:
    """新加的这一段不许带内联 style，也不许把英文枚举印到界面上。

    内联 style 会被严格 CSP（`style-src 'self'`）拦掉；英文枚举是这个项目的
    另一条硬约束（`scheduled` 必须显示成「待进行」）。
    """
    code = _strip_comments(_js())
    assert ".style.cssText" not in code
    assert "setAttribute('style'" not in code
    for enum in ("proposed", "'active'", "skipped'", "'taken'"):
        # 允许出现在 URL 路径里（/skipped、/taken），不允许被塞进 textContent
        for m in re.finditer(re.escape(enum), code):
            around = code[max(0, m.start() - 60):m.start()]
            assert "textContent" not in around.split("\n")[-1], (
                f"{enum} 疑似被直接印到界面上")
