"""`strip_js_comments` 自己是对的吗。

好几条判据现在的形状是「某个路径不许出现在剥掉注释的源码里」。如果这个剥注释函数
多吃了一口代码，那些判据会**安静地变绿**——被删掉的正是它们要找的东西。
一个把代码吃掉的剥注释器，比不剥注释更危险：后者会误报，前者会漏报。

所以这一份钉住三件事：注释真的被剥掉、代码一个字符不少、行号不偏。
"""

from __future__ import annotations

from .helpers import strip_js_comments


def test_it_removes_both_comment_shapes() -> None:
    source = "a();  // 说明 /v2/chat\n/* 多行\n   注释 /v2/family/approve */\nb();\n"
    out = strip_js_comments(source)
    assert "/v2/chat" not in out, "行注释没被剥掉"
    assert "/v2/family/approve" not in out, "块注释没被剥掉"
    assert "a();" in out and "b();" in out, "代码被一起吃掉了"


def test_it_keeps_the_line_count() -> None:
    """行号要还能用。

    这个项目为同一件事付过一次代价：一个直接删行的剥注释器让报错行号整体偏了
    两百多行，找了很久才发现错的是工具不是代码。
    """
    source = "one();\n// 注释\n/* 块\n   注释 */\ntwo();\n"
    assert strip_js_comments(source).count("\n") == source.count("\n")


def test_a_url_in_a_string_is_not_a_comment() -> None:
    """`'https://x'` 里的 `//` 不是注释开头。

    把它当注释会从中间截断这一行，后面的代码连同它一起消失——而判据只会看到
    「那个路径不在了」，报绿。
    """
    source = "const u = 'https://example.com/v2/chat';\nkeep();\n"
    out = strip_js_comments(source)
    assert "https://example.com/v2/chat" in out, "字符串里的 URL 被当成注释截掉了"
    assert "keep();" in out


def test_the_real_file_still_contains_its_code() -> None:
    """拿真文件跑一遍：剥完之后那些**应该在**的东西必须还在。

    只测构造的小样例证明不了它在 500 行的真文件上不出事。
    """
    from pathlib import Path

    static = Path(__file__).resolve().parents[2] / "backend" / "static"
    out = strip_js_comments((static / "trust.js").read_text(encoding="utf-8"))
    for needed in ("async function renderReceipt()", "/v2/tasks", "/v2/audit",
                   "RECEIPT_STEPS", "还没有可以出示的凭证"):
        assert needed in out, f"剥注释之后 {needed!r} 不见了——它吃掉了代码"
