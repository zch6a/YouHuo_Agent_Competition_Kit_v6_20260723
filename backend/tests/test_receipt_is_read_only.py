"""渲染一张凭证，永远不许改动一笔业务事务。

## 这条契约是被什么换来的

`trust.js` 的 `renderReceipt()` 里有一个分支：链上找不到 `bill_payment` 时，
它会**真的走一遍完整缴费**——建会话、说「帮我交这个月的水费」、复述确认金额、
再调 `/v2/family/approve`。而它自己的注释写着触发条件：

    「这是全新沙箱里的路径，也就是评委第一次打开这一页时走的那一条。」

也就是说：打开一张只读的凭证，会凭空发起一笔缴费。

`visitor_sandbox()` 现在会给每位访客种一笔已完成缴费，所以线上演示里通常走不到
那个分支——但那只是**掩盖**它：那段种子挂在 `seed_history` 开关上，开关关掉
（真实部署的默认值）访客就没有账单，这一页立刻又会去办一笔。
「平时到不了」不是「不会发生」。

## 判据

Read UI 必须是 Read。这一页允许的只有 GET：`/v2/tasks`、`/v2/audit`。
任何写方法（POST/PUT/PATCH/DELETE）都不许出现在这个文件里。

判据写在**源码**上而不是浏览器里，是故意的：浏览器里要造出「链上没有账单」
那个状态，得先有一个全新沙箱，而三道浏览器闸门每次都用全新沙箱——它们全绿，
这个缺陷照样活着。源码判据不依赖任何状态。
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
STATIC = ROOT / "backend" / "static"

#: 只读表面：渲染这些页面不许写任何东西。
READ_ONLY_PAGES = ["trust.js"]

#: `api(...)` 调用里出现的写方法。
#:
#: 正则只匹配**调用语法**（`api('…', {… method: 'POST' …})`），不匹配注释里提到的
#: 路径——这个文件的注释里就有 `/v2/chat` 的例子，按字符串搜会误报。
_CALL = re.compile(
    r"""api\(\s*[`'"]([^`'"]+)[`'"]\s*,\s*\{(?P<opts>[^{}]*(?:\{[^{}]*\}[^{}]*)*)\}""",
    re.S,
)
_METHOD = re.compile(r"""method\s*:\s*['"](\w+)['"]""")

WRITE_METHODS = {"POST", "PUT", "PATCH", "DELETE"}


@pytest.mark.parametrize("page", READ_ONLY_PAGES)
def test_rendering_a_receipt_never_writes(page: str) -> None:
    source = (STATIC / page).read_text(encoding="utf-8")
    offenders = []
    for match in _CALL.finditer(source):
        method = _METHOD.search(match.group("opts"))
        if method and method.group(1).upper() in WRITE_METHODS:
            line = source[: match.start()].count("\n") + 1
            offenders.append(f"{page}:{line} {method.group(1)} {match.group(1)}")
    assert not offenders, (
        "渲染一张凭证不许创建、推进、批准、执行、重试或改动任何一笔业务事务。\n"
        "  这些写调用还在：\n    " + "\n    ".join(offenders) + "\n"
        "  没有数据就说「没有找到这份凭证」，不是「那我现在帮你办一笔出来」。"
    )


@pytest.mark.parametrize("page", READ_ONLY_PAGES)
def test_the_probe_can_actually_see_a_write_call(page: str) -> None:
    """判据自检：这条正则真的认得出一个写调用吗。

    上一条如果因为正则写错而永远匹配到 0 个，它会安静地一直绿——和这个文件
    根本不存在没有区别。所以拿一段**已知含写调用**的文本喂给同一条正则。
    """
    sample = """
      const r = await api('/v2/family/approve', {
        method: 'POST',
        body: JSON.stringify({task_id: taskId}),
      }, 'family');
    """
    found = [
        _METHOD.search(m.group("opts")).group(1)
        for m in _CALL.finditer(sample)
        if _METHOD.search(m.group("opts"))
    ]
    assert found == ["POST"], f"正则认不出写调用，上一条判据是空转的：{found}"
