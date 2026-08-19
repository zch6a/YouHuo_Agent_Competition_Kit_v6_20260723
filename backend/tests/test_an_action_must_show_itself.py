"""按下去之后，屏幕上必须有东西变。

## 这道门从哪来

老人端首页的「我知道了」按下去，实测：

    请求   POST /v2/reminders/{id}/acknowledge   发出，200
    #status   空的                                回执没写进去
    卡片      状态：待处理  →  状态：待处理          一个字没动

后端记下了，屏幕上**完全静默**。她会再按一次，再一次。

两个独立成因，缺一不可地凑成了这个结果：

  ① 回执走 `addBubble()`，写的是 `#chat`——而 `#chat` 住在 `.elder-focus` 里，
     Focus Mode 关着的时候 `display: none`。实测盒子 [0,0]。
  ② `REMINDER_STATUS` 里 `acknowledged` 和 `scheduled` 都写「待处理」，
     所以卡片上那一行前后一模一样。

①是 `elder.js` 里 `send()` 顶上那段注释记录的**同一个缺陷的另一半**：
那次从「语音说完看不到确认卡」倒查，给 `send()` 补了 `setFocus(true)`；
而按待办按钮的人根本不在对话里，那条路径没被一起检查。

## 判据

这两条都可以静态判，而且判的是**不变量**不是实现细节：

  · 一个在 Focus Mode **之外**触发的动作，回执不许写进 Focus Mode 里的容器
  · 一次状态迁移的前后两个词不许相同——相同就等于「什么都没发生」
"""
from __future__ import annotations

import io
import re
from pathlib import Path

STATIC = Path(__file__).resolve().parents[1] / "static"


def _elder_js() -> str:
    src = io.open(STATIC / "elder.js", encoding="utf-8").read()
    # 先剥注释：这个文件注释密度极高，而上面那几段解释里就含有
    # `addBubble`、`待处理` 这些字样。不剥的话，一段措辞恰当的注释能让门变绿。
    src = re.sub(r"/\*.*?\*/", "", src, flags=re.S)
    return re.sub(r"^\s*//.*$", "", src, flags=re.M)


def _body_of(src: str, func: str) -> str:
    """取一个函数的函数体（按花括号配对，不靠缩进）。"""
    m = re.search(rf"(?:async\s+)?function\s+{re.escape(func)}\s*\([^)]*\)\s*\{{", src)
    assert m, f"elder.js 里找不到 {func}()"
    i, depth = m.end(), 1
    while i < len(src) and depth:
        if src[i] == "{":
            depth += 1
        elif src[i] == "}":
            depth -= 1
        i += 1
    return src[m.end():i]


def test_a_reminder_action_reports_where_the_elder_is_looking() -> None:
    """待办动作的回执不许写进 Focus Mode 里的容器。

    `addBubble()` 写 `#chat`，`#chat` 在 `.elder-focus` 里，默认 display:none。
    她按的是首页待办卡上的按钮——那一刻 Focus Mode 是关着的，
    写进去等于没写（实测盒子 [0,0]）。

    也**不许**靠 `setFocus(true)` 绕过：为了让回执可见而把整屏切成对话视图，
    是用一个更大的意外换一个小的。她在勾一件事，不是在对话。
    """
    body = _body_of(_elder_js(), "reminderAction")
    assert "addBubble(" not in body, (
        "`reminderAction` 用 `addBubble()` 报回执，而它写的 `#chat` 住在 "
        "`.elder-focus` 里、Focus Mode 关着时 display:none——"
        "老人按下按钮后屏幕上一个字都不会变。用 `setStatus()`。")
    assert "setFocus(true)" not in body, (
        "不要用 `setFocus(true)` 让回执可见。她在勾一件事，不是在对话；"
        "把整屏切成对话视图是用一个更大的意外换一个小的。")
    # 只看 **try** 那一段。
    #
    # 第一版查的是「函数体里有没有 setStatus」，变异测试证明它松：
    # `catch` 分支本来就调 `setStatus`（那里的注释写着「这一页其余的失败
    # 都写在状态行里，这一处也照做」），所以把成功路径的回执整个删掉，
    # 门照样绿——而"成功了不说话、失败了才说话"正是要防的那件事。
    success_path = body.split("} catch")[0]
    assert "setStatus(" in success_path, (
        "`reminderAction` 成功之后没有把回执写进状态行。"
        "`#status` 空的时候自己 display:none，一有文字就出现——"
        "它是 Focus Mode 之外唯一能说话的地方。"
        "（`catch` 里有 `setStatus` 不算：那只保证失败时会说话。）")


def test_a_status_change_changes_the_word_on_screen() -> None:
    """状态迁移前后的词不许相同。

    `acknowledged` 原先和 `scheduled` 都写「待处理」。后果不是用词不精确：
    老人按下「我知道了」，后端状态变了，而卡片上那一行**一个字没动**——
    连「她已经看见过这件事」都读不出来。

    这里只钉真实存在的迁移对，不是要求所有词两两不同：
    `completed` 和 `cancelled` 用不同词是自然的，而
    `scheduled → acknowledged`（按「我知道了」）和
    `scheduled → completed`（按「已完成」）是屏幕上真的会发生的两次跳转。
    """
    src = _elder_js()
    m = re.search(r"const REMINDER_STATUS = \{(.*?)\n\};", src, re.S)
    assert m, "elder.js 里找不到 REMINDER_STATUS"
    words = dict(re.findall(r"(\w+):\s*\['([^']+)'", m.group(1)))

    for src_state, dst_state, action in (
            ("scheduled", "acknowledged", "我知道了"),
            ("scheduled", "completed", "已完成"),
            ("notified", "acknowledged", "我知道了"),
    ):
        a, b = words.get(src_state), words.get(dst_state)
        assert a and b, f"REMINDER_STATUS 缺 {src_state} 或 {dst_state}"
        assert a != b, (
            f"按「{action}」会把状态从 {src_state} 变成 {dst_state}，"
            f"而两边在屏幕上都写「{a}」——那一下按完，卡片上一个字都不会变。")


def test_no_status_word_is_a_raw_enum() -> None:
    """状态词一个英文都不许有。

    这是项目的硬约束（`scheduled` 必须显示成「待进行」这类）。放在这里
    是因为上面那条如果被"随便改一个词就行"的方式满足，最省事的改法
    恰恰是塞一个英文标识符进去。
    """
    src = _elder_js()
    m = re.search(r"const REMINDER_STATUS = \{(.*?)\n\};", src, re.S)
    assert m
    for key, word in re.findall(r"(\w+):\s*\['([^']+)'", m.group(1)):
        assert not re.search(r"[A-Za-z]", word), (
            f"状态 `{key}` 在屏幕上显示成 {word!r}——界面上不许出现英文枚举值")
