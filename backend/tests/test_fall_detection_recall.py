"""跌倒识别的召回与误报：一次审查换来的 56 条用例。

`test_fall_detection.py` 守的是"回忆和担心不惊动家属"，它一直是绿的。这个文件守的是
另一半——**真的摔倒了，能不能被听出来**。

这一半此前基本是坏的：一轮针对性审查跑了 51 句真实老人可能说出的求救，**48 句漏报**；
31 句正常话里 **30 句误报**。两个数字要一起看：漏报是"摔倒了没人知道"，误报是"家属两周
后把通知静音"，而静音之后漏报就变成必然。

漏报的四类成因，每一类都不是边角：

1. **ASR 同音字**。「摔倒」被识别成「摔到」是中文语音识别的头号错误，而原来的模式
   只认「倒」。
2. **假设守卫误杀真实求救**。「小心」「注意」在假设词表里，于是「我不小心摔倒了」
   ——老人报告跌倒**最自然**的说法——被当成了假设。「我摔倒了怕站不起来」同理，
   而这句比裸「我摔倒了」更紧急。
3. **只描述结果的求救**。「我起不来了」「我趴地上了」「我动不了了」里没有「摔」字。
4. **口语说法**。「摔跤」「跟头」「摔得起不来」都不在原模式里。

修法的核心是**位置敏感**：中文里假设和回忆的标记几乎总在动词前（怕摔、万一摔、
去年摔），动词后出现的是后果和请求。整句包含即否决，就必然误杀后者。
"""

from __future__ import annotations

import pytest

from youhuo.security import SafetyPolicy


def is_emergency(text: str) -> bool:
    signal = SafetyPolicy.detect_safety_signal(text)
    return signal is not None and signal.category == "emergency"


# --- 必须听出来 -------------------------------------------------------------

ASR_HOMOPHONES = ["我摔到了", "我刚摔到了，疼得厉害", "我在卫生间滑到了", "我跌到了",
                  "我绊到了，爬不动"]

NATURAL_PHRASING = ["我不小心摔倒了", "我没注意摔倒了", "我一不小心摔了一跤",
                    "我摔倒了别告诉我儿子", "我摔倒了要不要叫救护车",
                    "我摔倒了怕站不起来"]

COLLOQUIAL = ["我摔跤了", "我刚摔跤了", "我跌跤了", "我跌了个大跟头", "我栽了个跟头",
              "我摔得起不来了", "我摔得不轻", "我摔坏了，动不了", "刚摔的，现在还躺着",
              "我从床上摔下来了", "我从凳子上摔下去了", "我滚下楼梯了"]

OUTCOME_ONLY = ["我起不来了", "我在地上起不来了", "我趴地上了", "我躺地上了，动不了",
                "我倒在地上了", "我爬不动了", "我一屁股坐地上了，起不来",
                "地上凉，我起不来", "我下不来床了"]

PLAIN = ["我摔倒了", "我摔倒了起不来", "刚才摔倒了"]


@pytest.mark.parametrize("text", ASR_HOMOPHONES)
def test_asr_homophones_are_heard(text: str):
    """「到」不是错别字，是 ASR 把「倒」听错时最常见的写法。"""
    assert is_emergency(text), text


@pytest.mark.parametrize("text", NATURAL_PHRASING)
def test_the_most_natural_way_to_report_a_fall_is_heard(text: str):
    """「我不小心摔倒了」曾经被当成假设——因为「小心」在假设词表里。"""
    assert is_emergency(text), text


@pytest.mark.parametrize("text", COLLOQUIAL)
def test_colloquial_falls_are_heard(text: str):
    assert is_emergency(text), text


@pytest.mark.parametrize("text", OUTCOME_ONLY)
def test_a_fall_described_only_by_its_outcome_is_heard(text: str):
    """这几句里一个「摔」字都没有，而它们是老人躺在地上时最可能说出的话。"""
    assert is_emergency(text), text


@pytest.mark.parametrize("text", PLAIN)
def test_plain_reports_still_work(text: str):
    assert is_emergency(text), text


# --- 必须保持安静 -----------------------------------------------------------

FEARED = ["我担心万一摔倒了起不来怎么办", "我怕摔倒了起不来", "我怕摔倒", "我梦见我摔倒了"]

REMEMBERED = ["上个月摔倒起不来，是邻居帮的忙", "去年摔倒不能动，现在康复了",
              "去年摔倒住了院，现在好利索了", "我上个月摔倒过"]

IDIOMS = ["他是我的救命恩人", "这是救命钱，不能乱花", "抓住最后一根救命稻草"]

OBJECTS = ["我把碗摔了", "手机摔了一下", "我把杯子摔了个粉碎", "刚才气得我把遥控器摔了"]

TOPIC_NOT_EVENT = ["护士说要防止跌倒", "社区搞了个防跌倒讲座", "医院给我做了跌倒风险评估"]

SOMEONE_ELSE = ["我孙子摔倒了，哭了一会儿", "楼下老王摔倒了，住院了"]

OTHER_FEARS = ["我怕着火，睡前都检查一遍"]


@pytest.mark.parametrize("text", FEARED)
def test_fearing_a_fall_is_not_having_one(text: str):
    assert not is_emergency(text), text


@pytest.mark.parametrize("text", REMEMBERED)
def test_remembering_a_fall_is_not_having_one(text: str):
    assert not is_emergency(text), text


@pytest.mark.parametrize("text", IDIOMS)
def test_救命_inside_an_idiom_is_not_a_cry_for_help(text: str):
    """「救命恩人」「救命钱」「救命稻草」都是成语。"""
    assert not is_emergency(text), text


@pytest.mark.parametrize("text", OBJECTS)
def test_dropping_a_bowl_is_not_falling(text: str):
    assert not is_emergency(text), text


@pytest.mark.parametrize("text", TOPIC_NOT_EVENT)
def test_a_fall_prevention_talk_is_a_topic_not_an_event(text: str):
    """「跌倒风险」「防跌倒讲座」是名词性词组，而且指示词在动词**之后**——

    位置敏感的守卫看不见它们，所以按相邻关系单独判。
    """
    assert not is_emergency(text), text


@pytest.mark.parametrize("text", SOMEONE_ELSE)
def test_someone_elses_fall_does_not_page_this_family(text: str):
    """「我孙子摔倒了」里的「我」是领属不是主语。少了这个区分，一个"我"字

    就能把第三人称守卫整个关掉。
    """
    assert not is_emergency(text), text


@pytest.mark.parametrize("text", OTHER_FEARS)
def test_worrying_about_other_hazards_is_not_an_emergency(text: str):
    """紧急模式原来整句直接匹配，跳过了守卫——「我怕着火」会真的惊动家属。"""
    assert not is_emergency(text), text


# --- 这两条性质本身 ---------------------------------------------------------


def test_a_hypothetical_marker_after_the_verb_does_not_silence_the_report():
    """位置敏感是这次修复的核心，单独钉住它。"""
    assert is_emergency("我摔倒了怕站不起来")      # 怕在动词后 → 是后果
    assert not is_emergency("我怕摔倒了起不来")     # 怕在动词前 → 是担心


def test_first_person_wins_over_a_third_person_mention():
    assert is_emergency("我扶邻居的时候我也摔倒了")
