from __future__ import annotations

import re
from pathlib import Path

from youhuo.models import ChatRequest

STATIC = Path(__file__).resolve().parents[2] / "backend" / "static"

#: 样式表的四层，加载顺序即层叠顺序。pages 必须最后——媒体查询不增加特异性，
#: 响应式覆写写在被它覆写的组件之前就会静默输掉层叠。
STYLESHEET_LAYERS = ("tokens.css", "base.css", "components.css", "pages.css")


def read_stylesheet() -> str:
    """按加载顺序拼出整张样式表。

    `style.css` 拆成四层之前，这些断言直接读那一个文件。拆分只改了文件边界，没有
    改任何一条声明，所以断言的对象仍然应该是"整张样式表"，而不是某一层。
    """
    return "".join(
        (STATIC / name).read_text(encoding="utf-8") for name in STYLESHEET_LAYERS
    )

#: A bare "确认办理" no longer settles a bill: payment confirmation is gated on a
#: verified teach-back of the amount (see youhuo/teach_back.py). Tests that use
#: payment as a vehicle for something else should confirm through these helpers
#: so the phrasing stays in one place.
CONFIRM = "确认办理"


def chat(engine, actor, session, text: str, request_id: str | None = None):
    return engine.handle(actor, ChatRequest(session_id=session.session_id, text=text, request_id=request_id))


def amount_from(message: str) -> str:
    """Pull the yuan figure the agent just read out, e.g. '68.40'."""
    match = re.search(r"(\d+\.\d{2})\s*元", message)
    assert match, f"没有在提示中找到金额：{message}"
    return match.group(1)


def teach_back_for(message: str) -> str:
    """The phrase an elder must say to confirm the amount they were told."""
    return f"确认支付{amount_from(message)}元"


def confirm_bill(engine, actor, session, prompt_message: str, request_id: str | None = None):
    """Confirm a bill by restating its amount, as the product now requires."""
    return chat(engine, actor, session, teach_back_for(prompt_message), request_id)

def strip_js_comments(source: str) -> str:
    """把 JS 里的注释抹成空格，**保留行数**。

    为什么必需：这个文件里好几条判据是「某个路径不许出现在这段代码里」。而写清楚
    「这里原先有一段 /v2/family/approve，删了，理由是……」正是这个项目要求的注释
    风格——于是判据会在**注释**里读到那个路径，报一个不存在的缺陷。
    实测撞到过：写完 P0 的修复注释之后，两条静态判据立刻红了。

    保留行数是为了让报错里的行号还能用（`_blank_comments` 那次教训：直接删行会让
    行号整体偏移 200 多行）。

    `//` 只在**不是** `://` 的时候才算注释开头，否则 `'https://x'` 这类字符串会被
    从中间截断。这个近似对本项目够用：真正的 JS 词法分析要跟踪字符串与正则字面量，
    而这里只需要「别把代码当注释扔掉」。下面 `test_strip_js_comments_keeps_code`
    钉住这一点。
    """
    out = []
    i, n = 0, len(source)
    while i < n:
        two = source[i:i + 2]
        if two == "/*":
            end = source.find("*/", i + 2)
            end = n if end == -1 else end + 2
            out.append("".join("\n" if c == "\n" else " " for c in source[i:end]))
            i = end
        elif two == "//" and not (i > 0 and source[i - 1] == ":"):
            end = source.find("\n", i)
            end = n if end == -1 else end
            out.append(" " * (end - i))
            i = end
        else:
            out.append(source[i])
            i += 1
    return "".join(out)
