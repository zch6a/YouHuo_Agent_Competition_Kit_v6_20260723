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

import re
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
#:
#: ## 从字面子串换成正则，理由是量出来的
#:
#: 实测（连聊 12 句，主题故意铺开）：**12 句只回出 8 种话，
#: 「嗯，我还在听。」出现 5 次**，而那 5 句里有 4 句是这张表本来就写了
#: 专门措辞的主题：
#:
#:     我昨晚又没睡好        -> OPEN   而 SLEEP 的词是「睡不好」
#:                                     「没睡好」和「睡不好」字序不同
#:     夜里总醒，醒了就想事  -> OPEN   而 SLEEP 只认「半夜醒」，要求紧邻
#:     腿有点酸，走远了就疼  -> OPEN   而 BODY 只认「腿疼」，要求紧邻
#:     今天中午蒸了点馒头    -> OPEN   而 DAILY 那一排没有做饭这一类
#:
#: 后果不止是一句不贴心的话：`_CONTACT_SUGGESTION` 里 SLEEP 和 BODY
#: 那两条（「可以考虑跟家人或医生说一声。要我帮您记个提醒吗？」
#: 「要不要我帮您记一条提醒，下次见医生时提一句？」）**永远发不出去**
#: ——她说「夜里总醒」「腿疼」，没有人问她要不要记下来给医生看。
#: 一条结构上永远空的通道，而它挨着健康。
#:
#: 紧邻的两字词组表达不了「腿**有点**酸」这种插了字的说法，所以换正则
#: ——`security.py` 为同一个理由做过同一件事（那边的话是「模式本身尽量窄，
#: 脏活交给守卫」）。这一层比安全层宽容：认错了最多是一句不太贴的安慰，
#: 不会去叫 120，所以不需要否定守卫。
#:
#: **但顺序仍然是全部安全性所在**：BEREAVEMENT 在最前，所以
#: 「他走了，我心里疼」不会被 BODY 的「疼」抢走。
#:
#: 另外修掉一个**假阳性**：LONELY 原先认裸的「没人」，于是
#: 「他最爱下棋，院里**没人**下得过他」被读成孤单，回了一句
#: 「一个人待着的时候，时间是会变得很长」——她在夸老伴棋好。
#: 收紧成「没人」后面真的跟着「陪/说话/理/管/来/问」那几种。
_THEME_CUES: tuple[tuple[Theme, str], ...] = (
    #: `没了` 是「不在了」同一族的委婉说法，而表里只有后者：
    #: 「她没了以后我就不怎么出门」「他前年就没了」都落到 OPEN。
    #: 它**必须绑人**——「钱没了」「药没了」「牙没了」
    #: 「我的老花镜没了」都不是这件事（四句都量过，都放行）。
    #: `烧纸` 和已有的 `坟`、`忌日` 是同一类具体动作。
    (Theme.BEREAVEMENT,
     r"老伴|走了|去世|不在了|过世|遗像|忌日|坟|烧纸|"
     r"(?:他|她|老伴|老头子|老太太)[^。！？，]{0,3}没了"),
    (Theme.SLEEP,
     r"睡不着|失眠|睡不好|没睡好|睡得?浅|睡不踏实|一夜没睡|睡得不好|"
     r"(?:半夜|夜里|晚上|夜间)[^。！？，]{0,4}(?:总|老|又|经常|常)?醒|"
     r"醒了就睡不着|天没亮就醒"),
    (Theme.LONELY,
     #: `静得慌` 和 `闷得慌` 是同一族（「屋里静得慌」原先落 OPEN）。
     #: **不收 `冷得慌`**——那是冷，不是孤单。
     r"孤独|孤单|一个人在家|没意思|冷清|(?:闷|静)得慌|"
     r"没人(?:陪|说话|理|管|来|问)"),
    #: `闺女` 是「女儿」在北方最常见的说法，而表里只有「女儿」。
    #: 驱动出来的：「闺女昨天打电话了」在挂号那一步拿到
    #: 「我没听出这是哪个科室」——一句家常被当成没答上的科室；
    #: 而同一件事说成「女儿一个月来一次」**本来就**被暂存并记住。
    #: 同一个意思两种说法，两种待遇。
    (Theme.FAMILY, r"孙子|孙女|外孙|儿子|女儿|闺女|孩子|重孙"),
    (Theme.MEMORY, r"以前|那时候|年轻时|小时候|当年|老家"),
    #: 空隙 `[^。！？，]{0,4}` **故意排掉逗号**：跨逗号桥接会让
    #: 「腿不疼，心里酸」也变成身体（那个「酸」是心里酸）。
    #: 所以「胳膊抬不太起来，有点酸」不靠桥接，靠「抬不起来」自己
    #: ——它本身就是一句身体不舒服。判据里那一条就是这么抓出来的。
    (Theme.BODY,
     #: 这一族原先是**紧连的字面量**（`头晕`、`胃口不好`），而下面
     #: `腰|腿|膝盖|…` 那一条早就有容间隔的写法——**同一张表里两套标准**：
     #:
     #:     腰有点疼      -> BODY  （走下面那条容间隔的）
     #:     头有点晕      -> **OPEN**（`头晕` 是紧连字面量）
     #:     我头疼        -> **OPEN**（`头疼` 压根不在表里）
     #:     牙疼          -> **OPEN**（`牙` 压根不在表里）
     #:     我胃口不太好   -> **OPEN**（`胃口不好` 是紧连字面量）
     #:     浑身没劲      -> **OPEN**（表里只有 `没力气`）
     #:
     #: `头晕` 和 `胃口不好` 两个字面量是**并进**下面更宽的写法里，
     #: 不是和它并列——并列的话那两个字面量就没有独立见证了。
     #: 覆盖关系验过：旧写法命中的那几句，新写法全都命中。
     #:
     #: 三处刻意收窄：
     #:   · 写 `胃口不(?:太|怎么|大)?好` 而**不是** `胃口不`
     #:     ——「胃口不错」意思正好相反，那样会归错类；
     #:   · 「没劲」必须绑身体词（浑身/全身/身上/手脚）
     #:     ——「这电视剧没劲」是没意思，不是身体；
     #:   · `牙` 那一条的间隔比别处短，「牙膏用完了」不会命中。
     #:
     #: 量出来的：11 句新阳性全进 BODY，6 句贴边阴性一句都不进，
     #: 整语料 11109 条只有 3 条变（都是该变的），
     #: **红旗那一侧 0 条变化**，新加的每一项都有自己的见证。
     #:
     #: BODY 在 `_NOT_A_SOCIAL_ASIDE` 里，所以这一放宽**不动**任务锁的
     #: 暂存范围——量过：「我牙疼」在挂号那一步仍然不被暂存。
     #: （给 SLEEP 加词就**会**动，那条量过之后没做，见 KNOWN_ISSUES。）
     r"腰疼|腿疼|没力气|累得慌|没胃口|走不动|"
     r"抬不起来|抬不太起来|抬不动|"
     r"头[^。！？，]{0,4}(?:晕|疼|痛)|"
     r"牙[^。！？，]{0,3}(?:疼|痛)|"
     r"胃口不(?:太|怎么|大)?好|胃口不佳|"
     r"(?:浑身|全身|身上|手脚)[^。！？，]{0,3}没(?:劲|力)|"
     #: `(?<!脚)脖子`：**脚脖子是脚踝，不是脖子。** 整套里那条
     #: `test_a_symptom_it_cannot_place_still_gets_an_answer`
     #: 就是这么红的——「我脚脖子疼」被认成身体主题之后，任务锁
     #: 把她照着提示说的症状当题外话暂存了。子串碰撞，和
     #: `_BARE_YES` 上面那段警告的「中」在「中午」里是同一件事。
     r"(?:腿|腰|膝盖|关节|肩膀|(?<!脚)脖子|胳膊)[^。！？，]{0,4}(?:酸|疼|痛|沉|僵|木)"),
    (Theme.DAILY,
     #: `买菜`、`晒被子` 原先是**紧连字面量**，插一个字就进不去：
     #: 「买了点菜」「把被子晒了晒」「被子该晒了」全落到 OPEN。
     #: 两个字面量**并进**下面的容间隔写法（覆盖关系验过：
     #: 「买菜」「晒被子」两句新写法都命中），不是并列。
     #: `被…晒` 和 `晒…被` 两个方向都要——她两种语序都说。
     r"天气|电视|吃饭|散步|下棋|遛弯|"
     r"做饭|蒸|馒头|包子|饺子|收拾屋子|浇花|"
     r"买[^。！？，]{0,3}菜|被[^。！？，]{0,3}晒|晒[^。！？，]{0,3}被"),
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
    """第一个命中的主题赢。顺序见 `_THEME_CUES` 上面那段。"""
    for theme, pattern in _THEME_CUES:
        if re.search(pattern, text):
            return theme
    return Theme.OPEN


def wants_companion(text: str) -> bool:
    return any(phrase in text for phrase in COMPANION_REQUESTS)


#: 办事过程中说了一句哪里疼，**不算题外话**。
#:
#: 要么是提示语**邀请她说的症状回答**——挂号问科室那一句自己写着
#: 「也可以描述哪里不舒服」，`test_a_symptom_it_cannot_place_still_gets_an_answer`
#: 的 docstring 把这条讲得很清楚：「症状是被邀请的回答，不是在说对话本身」；
#: 要么是安全层该看见的东西。两种都不该被任务锁当成闲聊收起来。
#:
#: 这一条是整套抓出来的：把 BODY 的模式加宽（第 300 条）之后，
#: 「我脚脖子疼」从 OPEN 变成 BODY，于是这个函数跟着变真，
#: 她在问科室那一步说的症状被暂存成了题外话。
#: **把主题表加宽，就等于把这里加宽**——这处耦合原先没人写下来。
#:
#: 只有任务锁用这个函数（`engine.py` 的 `_looks_like_chitchat`，三处）；
#: 陪伴那一侧走的是 `classify_theme`，所以排掉 BODY 不影响陪伴措辞。
_NOT_A_SOCIAL_ASIDE: frozenset[Theme] = frozenset({Theme.OPEN, Theme.BODY})


def sounds_like_chitchat(text: str) -> bool:
    """Used by the task lock to park a social aside instead of misreading it."""
    return classify_theme(text) not in _NOT_A_SOCIAL_ASIDE


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
    return f"您刚才提到「{trimmed}」。现在要不要接着聊？说「好啊」我就切到无忧伴。"


def accepts_resume(text: str) -> bool:
    if any(word in text for word in RESUME_DECLINES):
        return False
    return any(word in text for word in RESUME_ACCEPTS)


def declines_resume(text: str) -> bool:
    return any(word in text for word in RESUME_DECLINES)
