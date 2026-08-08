"""无忧伴 companion mode: continuity without a transcript.

Design §4.1 makes 无忧伴 a co-equal role, and §6.2 permits "必要短期上下文"
while forbidding storage of the conversation itself. Both constraints are load
bearing here.

Before this, the whole secondary mode was four hardcoded branches: an elder who
said "我想我老伴了", then "他走了三年了", then "我今天一个人在家很没意思" got the
identical line "我在听。您可以慢慢说，不着急。" three times. For a bereavement
disclosure that is worse than saying nothing.

What this module does and does not do:

- It classifies a turn into a small set of themes and picks a follow-on line
  that acknowledges what was raised. That is a deterministic conversational
  scaffold, not empathy and not therapy.
- It keeps only a theme label and a turn count per session. The elder's words
  are never stored, never audited, and never reach the family view.
- It never gives medical or psychological advice. Sustained distress leads to
  one gentle, declinable suggestion to contact a trusted person; the elder is
  always the one who decides.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum


class Theme(StrEnum):
    FAMILY = "family"          # 想念子女、孙辈
    BEREAVEMENT = "bereavement"  # 丧偶、故人
    LONELY = "lonely"          # 独处、没意思
    SLEEP = "sleep"            # 睡不着
    MEMORY = "memory"          # 回忆过去
    BODY = "body"              # 身体不舒服的闲聊表达
    DAILY = "daily"            # 天气、电视、吃饭
    OPEN = "open"              # 未归类


#: Ordered: the first match wins, so heavier themes are checked before lighter
#: ones. "老伴走了" must read as bereavement, not as a family anecdote.
_THEME_CUES: tuple[tuple[Theme, tuple[str, ...]], ...] = (
    (Theme.BEREAVEMENT, ("老伴", "走了", "去世", "不在了", "过世", "遗像", "忌日", "坟")),
    (Theme.SLEEP, ("睡不着", "失眠", "半夜醒", "睡不好", "睡得浅")),
    (Theme.LONELY, ("孤独", "孤单", "没人", "一个人在家", "没意思", "冷清", "闷得慌", "没人说话")),
    (Theme.FAMILY, ("孙子", "孙女", "外孙", "儿子", "女儿", "孩子", "重孙")),
    (Theme.MEMORY, ("以前", "那时候", "年轻时", "小时候", "当年", "老家")),
    (Theme.BODY, ("腰疼", "腿疼", "没力气", "累得慌", "胃口不好", "头晕")),
    (Theme.DAILY, ("天气", "电视", "吃饭", "散步", "买菜", "下棋", "遛弯")),
)

#: Phrases that clearly ask for company rather than an errand.
COMPANION_REQUESTS: tuple[str, ...] = (
    "调用无忧伴", "进入无忧伴", "找无忧伴", "切换陪伴", "陪伴模式",
    "陪我聊", "陪我说说话", "陪我说话", "想找个人说说话", "想找人聊聊",
    "跟你聊聊", "和你聊聊", "说说话", "聊聊天", "唠唠嗑", "说会儿话",
)

#: Accepting a "要继续聊吗" offer.
RESUME_ACCEPTS: tuple[str, ...] = (
    "好啊", "好的", "好", "聊吧", "继续聊", "接着聊", "想聊", "说说吧", "行啊", "可以啊",
)
RESUME_DECLINES: tuple[str, ...] = (
    "不用了", "不聊了", "算了", "改天", "下次", "不想说", "先不聊",
)


def classify_theme(text: str) -> Theme:
    for theme, cues in _THEME_CUES:
        if any(cue in text for cue in cues):
            return theme
    return Theme.OPEN


def wants_companion(text: str) -> bool:
    return any(phrase in text for phrase in COMPANION_REQUESTS)


def sounds_like_chitchat(text: str) -> bool:
    """Used by the task lock to park a social aside instead of misreading it."""
    return classify_theme(text) is not Theme.OPEN


@dataclass
class CompanionContext:
    """Session-scoped, in-memory only. Holds labels, never utterances."""

    turns: int = 0
    theme_counts: dict[str, int] = field(default_factory=dict)
    last_theme: Theme | None = None
    suggested_contact: bool = False

    def observe(self, theme: Theme) -> None:
        self.turns += 1
        self.theme_counts[theme.value] = self.theme_counts.get(theme.value, 0) + 1
        self.last_theme = theme

    def seen(self, theme: Theme) -> int:
        return self.theme_counts.get(theme.value, 0)

    def snapshot(self) -> dict[str, object]:
        """Safe to log: counts and labels only."""
        return {"turns": self.turns, "themes": dict(self.theme_counts),
                "suggested_contact": self.suggested_contact}


#: First reply on a theme, then a follow-on that shows the thread was kept.
_OPENING: dict[Theme, str] = {
    Theme.BEREAVEMENT: "谢谢您愿意跟我说这些。这样的想念不会因为时间就淡掉，您想聊多久都可以。",
    Theme.FAMILY: "听得出您很惦记他们。最近一次联系是什么时候？",
    Theme.LONELY: "一个人待着的时候，时间是会变得很长。我陪着您，慢慢说就行。",
    Theme.SLEEP: "睡不好确实难受。我们先聊点轻松的，等您想休息了再说。",
    Theme.MEMORY: "这些事听着就有意思。您愿意多讲讲当时的情形吗？",
    Theme.BODY: "身体不舒服的时候人特别容易烦。这些我记不了病，也不敢替医生判断，但我可以一直陪您说话。",
    Theme.DAILY: "这些日常听着挺踏实的。今天还打算做点什么？",
    Theme.OPEN: "我在听，您慢慢说，不着急。",
}

_FOLLOW_ON: dict[Theme, str] = {
    Theme.BEREAVEMENT: "您刚才提到的这些，我一直记着在听。想说什么都可以，不用怕说重复。",
    Theme.FAMILY: "您提了好几次家里人，看得出这件事一直放在心上。",
    Theme.LONELY: "这份冷清您已经说了好几回了。要不要我们找件小事做做，或者继续这样聊着？",
    Theme.SLEEP: "睡不好像是持续了一阵子了。",
    Theme.MEMORY: "您记得的细节真清楚，后来呢？",
    Theme.BODY: "这个不舒服您提到不止一次了。",
    Theme.DAILY: "嗯，您接着说。",
    Theme.OPEN: "嗯，我还在听。",
}

#: Only ever a suggestion, never an instruction, and offered at most once.
_CONTACT_SUGGESTION = {
    Theme.BEREAVEMENT: "如果哪天特别难熬，想不想让我提醒女儿给您打个电话？您说不用也完全可以。",
    Theme.LONELY: "要不要我帮您给家人留个话，让他们有空时联系您？您说不用我就不发。",
    Theme.SLEEP: "如果这种情况一直持续，可以考虑跟家人或医生说一声。要我帮您记个提醒吗？",
    Theme.BODY: "要不要我帮您记一条提醒，下次见医生时提一句？",
}


def compose_reply(text: str, context: CompanionContext) -> tuple[str, Theme, bool]:
    """Return (reply, theme, offered_contact).

    The reply follows on when the theme has come up before, so the elder is not
    answered with the same sentence twice.
    """
    theme = classify_theme(text)
    seen_before = context.seen(theme) > 0
    context.observe(theme)

    reply = (_FOLLOW_ON if seen_before else _OPENING)[theme]

    # One gentle, declinable suggestion when a heavy theme keeps recurring.
    offered = False
    suggestion = _CONTACT_SUGGESTION.get(theme)
    if suggestion and not context.suggested_contact and context.seen(theme) >= 2:
        reply = f"{reply} {suggestion}"
        context.suggested_contact = True
        offered = True
    return reply, theme, offered


def resume_offer(topic: str) -> str:
    """Design §5.2: offer to pick the parked topic back up, and mean it."""
    trimmed = topic.strip()[:40]
    return f"您刚才提到“{trimmed}”。现在要不要接着聊？说“好啊”我就切到无忧伴。"


def accepts_resume(text: str) -> bool:
    if any(word in text for word in RESUME_DECLINES):
        return False
    return any(word in text for word in RESUME_ACCEPTS)


def declines_resume(text: str) -> bool:
    return any(word in text for word in RESUME_DECLINES)
