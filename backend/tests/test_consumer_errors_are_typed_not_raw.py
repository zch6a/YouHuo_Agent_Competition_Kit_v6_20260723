r"""消费者面不许把异常消息当文案。

## 为什么这道闸门是必需的

`test_app_surface_speaks_no_engineering.py` 扫的是**静态字面量**。而
`` `待办加载失败：${e.message}` `` 是一个模板——它运行时装进来什么，静态扫描无从
得知。于是那条「消费者面不许有工程词」的规则，在**运行时**是没有闸门的。

实测泄漏 8 处：`elder.js` 三处、`care.js` 两处（含 `failed()` 助手）、
`trust.js` 一处（**连前缀都没有**，把异常消息整条当文案）、`family.js` 两处。
网络失败时 `e.message` 是 `Failed to fetch`，而 `common.js:41` 的注释早就写着
这些消息「会被各页 catch 之后原样写到屏幕上（**老人端还会念出来**）」——
当时的对策只洗了我们自己撰写的那一半，平台抛的那一半漏着。

## 判据为什么按 catch 绑定的变量名来

`data.message` 是**后端写的中文**，到处在用且完全正当
（`addBubble(adapted.visual_text || data.message, …)`）。只有 catch 语句绑定的
那个变量的 `.message` 才是异常消息。所以这里做花括号配对，只在 catch 块**内部**
找那个变量——按 `\.message` 一把抓会得到几十个假阳性，然后这道闸门会被放宽或删掉。
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
STATIC = ROOT / "backend" / "static"

#: 消费者面的脚本。判据是 surface，不是文件名——`surfaces.py` 是那份事实源，
#: 这里按它列出的 consumer 路由所加载的脚本，外加它们共用的那几个。
#:
#: `proof-demos.js` / `stage.js` / `judge.js` **不在**这份名单里：那是
#: presentation 与 professional 面，工程词在那里是内容而不是泄漏。
CONSUMER_SCRIPTS = [
    "common.js", "identity.js", "elder.js", "family.js", "care.js",
    "trust.js", "landing.js", "task-space.js", "glassbox.js",
]

CATCH = re.compile(r"\bcatch\s*\(\s*([A-Za-z_$][\w$]*)\s*\)\s*\{")


def _blank_comments(source: str) -> str:
    r"""把注释内容抹成空白，**但保留每一个换行**。

    去注释这一步是踩过坑换来的：本项目有过至少四次「测试匹配到了我自己写的那条
    注释」，包括一条**解释这个缺陷**的注释。

    而「保留换行」是这一版加的。第一版直接删掉注释行，于是报出来的行号是
    *去注释后*那份文本里的行号——第一次跑就把 `elder.js` 的泄漏点报成第 644 行，
    而那一行是空行，真正的泄漏在别处。一个指错位置的闸门，会让人去改一段没问题的
    代码，然后以为闸门坏了。
    """
    source = re.sub(r"/\*.*?\*/",
                    lambda m: "\n" * m.group(0).count("\n"), source, flags=re.S)
    return re.sub(r"//[^\n]*", "", source)


def _catch_bodies(source: str) -> list[tuple[str, int, int]]:
    """所有 catch 块 → `(绑定的变量名, 块体起始偏移, 块体结束偏移)`。

    返回偏移而不是切片：报行号要用原文里的绝对位置。上一版返回切片、再用
    `source.index(body)` 找回位置，那个 `index` 会命中**第一个**内容相同的块，
    于是两个长得一样的 catch 块会互相顶替行号。
    """
    out: list[tuple[str, int, int]] = []
    for m in CATCH.finditer(source):
        name = m.group(1)
        depth = 0
        start = m.end() - 1          # 指向那个 `{`
        for i in range(start, len(source)):
            ch = source[i]
            if ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    out.append((name, start + 1, i))
                    break
    return out


@pytest.mark.parametrize("script", CONSUMER_SCRIPTS)
def test_no_consumer_script_puts_an_exception_message_on_screen(script: str) -> None:
    path = STATIC / script
    if not path.exists():
        pytest.fail(
            f"{script} 不在了。它要么被改名、要么被删——"
            "两种情况都得回来更新这份名单，而不是让这条测试静默跳过。"
        )
    source = _blank_comments(path.read_text(encoding="utf-8"))
    offenders = []
    for name, begin, end in _catch_bodies(source):
        for hit in re.finditer(rf"\b{re.escape(name)}\.message\b",
                               source[begin:end]):
            line = source[:begin + hit.start()].count("\n") + 1
            offenders.append(f"第 {line} 行 `{name}.message`")
    assert not offenders, (
        f"{script} 把异常消息放到了消费者面上：{offenders}。\n"
        "网络失败时它是 `Failed to fetch`，而老人端会把状态行念出来。\n"
        "改用 `window.YouHuo.errorWords(error, '这件事')`——它分四型，"
        "每型带一条仍然走得通的路。"
    )


def test_error_words_covers_four_types_and_every_type_offers_a_way_out() -> None:
    """四型齐全，而且每型都给出接下来能做什么。

    「一个错误提示最要紧的不是解释原因，是给出路」——这一条来自参考产品研究
    （`frontend_redesign/ia/12_reference_study.md` 第二节 ③，Medito 的
    `medito_error_widget.dart:36-51` `:133` 七型各配不同动作）。
    少了 `then`，这个函数就退化成一个更礼貌的「加载失败」。
    """
    source = (STATIC / "common.js").read_text(encoding="utf-8")
    block = re.search(r"const ERROR_WORDS = \{(.*?)\n  \};", source, re.S)
    assert block, "common.js 里找不到 ERROR_WORDS——它是这四型的唯一定义处"
    body = block.group(1)

    for kind in ("offline", "notfound", "server", "unknown"):
        assert re.search(rf"\b{kind}\s*:", body), f"ERROR_WORDS 少了 `{kind}` 这一型"

    entries = re.findall(r"(\w+)\s*:\s*\{([^}]*)\}", body)
    assert len(entries) >= 4, f"只解析出 {len(entries)} 型"
    for kind, fields in entries:
        assert "say:" in fields, f"`{kind}` 没有 say（说清发生了什么）"
        assert "then:" in fields, f"`{kind}` 没有 then（接下来能做什么）"
        words = re.findall(r"'([^']*)'", fields)
        assert len(words) == 2 and all(w.strip() for w in words), \
            f"`{kind}` 的两句话有空的：{words}"
        for w in words:
            assert not re.search(r"[A-Za-z]", w), (
                f"`{kind}` 的文案里有英文：{w!r}。这些字会显示给老人，"
                "而老人端还会念出来。"
            )


def test_the_generic_fallback_with_a_status_code_never_reaches_the_consumer() -> None:
    """`请求失败（403）` 这种兜底文案里有状态码，那是工程词。

    它由 `api()` 在后端没给 `detail` 时生成（`common.js` 的
    `new Error(data.detail || \\`请求失败（${response.status}）\\`)`），
    所以它**会**成为 `error.message`。`errorWords` 必须把它认出来并换掉，
    否则消费者面照样看到一个 HTTP 状态码。
    """
    source = (STATIC / "common.js").read_text(encoding="utf-8")
    assert re.search(r"请求失败（\\d\+）|请求失败（\\d\{", source) or \
        "请求失败（\\d+）" in source, (
        "errorWords 里没有针对 `请求失败（NNN）` 兜底文案的判别。"
        "少了它，后端不给 detail 的 4xx 会把状态码带到消费者面上。"
    )
    # 判别必须发生在 backend 那一支里——那是唯一会把 error.message 原样上屏的路径。
    backend_branch = re.search(r"if \(kind === 'backend'\) \{(.*?)\n    \}",
                               source, re.S)
    assert backend_branch, "找不到 errorWords 的 backend 分支"
    assert "请求失败" in backend_branch.group(1), (
        "对兜底文案的判别不在 backend 分支里——那条分支正是把 detail 原样上屏的地方"
    )
