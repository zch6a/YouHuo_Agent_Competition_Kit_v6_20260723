from __future__ import annotations

import re

from youhuo.models import ChatRequest

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
