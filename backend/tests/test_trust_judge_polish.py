r"""可信中心的凭证与评委页的证据：**不许说出链上没有的话**。

这两页是答辩现场评委真正会看的两页，而它们共有一个失效形状：一段中文模板去读一个
载荷字段，字段不在，于是那句话照说不误——只是把值换成了 `undefined`、空串，
或者一个看起来很无辜的占位符。

## 这一族缺陷各自长什么样

**一、`undefined` 直接上屏。** 已经发生过：凭证正文里印着
「第 **undefined** 次通过」（模板读 `p.attempts`，演示种子没写这个字段）。
它躲过了每一道闸门——对比度只读颜色，点击遍历只看有没有抛异常，截图看的是尺寸与
溢出。`check_page_runtime.py::check_no_raw_js_values` 是那次事故换来的，它守住了
这一种。

**二、占位符替 `undefined` 挨了那一刀，然后句子照说。** 这一次抓到的就是它，而且
上一种的闸门对它是全绿的：

    确认摘要 （无）
    同意的摘要 （无）
    同意的摘要 （无），和他确认的是同一个     ← 断言两个空值相等

`short()` 把缺失的哈希翻成「（无）」，所以屏幕上没有任何一个 JS 裸值。第三行是这一页
的第二条底线（「您确认的和家人同意的必须是同一笔，对不上就停下」）——它此前是一句
**无条件写死的断言**，从不比较，也从不检查两边有没有值。

**三、读一个谁都不写的字段。** `FAMILY_APPROVAL_RECORDED` 上原先读
`p.approval_digest`，而两个生产者都不写它：真实引擎写的是
`{approval_count, required_approvals}`（`engine.py:1100`），演示种子写的是
`{required: true}`（`database.py:419`）。也就是说那一行**永远**渲染成「（无）」，
不是数据缺了，是代码读错了字段。这一类靠"补种子数据"永远修不好。

**四、后端拼好的枚举串原样上屏。** `/v5/tasks/{id}/explain` 的 `summary` 是
`f"{task_type.value} · {status.value}"`，于是评委页「这件事是什么」那一行写着
`bill_payment · completed`，而**紧挨着的下一行** `current_status` 已经被翻成
「办好了」。半边翻译比不翻更难看。

## 判据怎么建

尽量把判据建在**两侧的事实**上，而不是建在字符串上：

  · "谁写这个字段" 从 `backend/youhuo/*.py` 里真实的 `append_audit(...)` 载荷字面量
    数出来（`_producer_index`），再和模板读的字段对账。种子和引擎写的形状不一样，
    所以两边都算作合法的生产者。
  · "渲染一张凭证不写任何东西" 在真实引擎上跑一遍：复刻这一页的请求序列，
    前后数审计链的长度。
  · 只有形状本身（哪一句话必须由一次比较产生）才落在源码上。

每一条静态判据都配一条**变异**：把那个缺陷原样打回去，判据必须红。一条不会红的
判据和没有这条判据是一回事，而它在结果里长得一模一样地绿。
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from youhuo.api import create_app

from .helpers import strip_js_comments

ROOT = Path(__file__).resolve().parents[2]
STATIC = ROOT / "backend" / "static"
YOUHUO = ROOT / "backend" / "youhuo"


def _js(name: str) -> str:
    return (STATIC / name).read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# 取出 `RECEIPT_STEPS`
# ---------------------------------------------------------------------------

def _receipt_steps_block(source: str) -> str:
    """`const RECEIPT_STEPS = { … };` 的内容，注释已剥。

    剥注释是必需的：这份修复要求把「原先读的是 `p.approval_digest`，而没有任何
    生产者写它」写进注释，而不剥注释的判据会在注释里读到那个字段，
    然后报一个已经修好的缺陷。这个项目在这上面栽过至少四次。
    """
    text = strip_js_comments(source)
    block = re.search(r"^const RECEIPT_STEPS = \{\n(.*?)^\};$", text, re.S | re.M)
    assert block, "trust.js 里找不到 `const RECEIPT_STEPS`——凭证的翻译层被改名或删掉了"
    return block.group(1)


def _entries(block: str) -> dict[str, str]:
    """事件类型 → 它那一段的源码（含 who / what / proof）。

    切法是"下一个顶层键开始之前"：顶层键固定缩进两格、全大写。用花括号配对会被
    模板串里的 `${…}` 骗到。
    """
    starts = [(m.group(1), m.start()) for m in re.finditer(r"^  ([A-Z_]+): \{", block, re.M)]
    assert starts, "凭证翻译层一条都没解析出来——行格式变了，这份文件会整体空转"
    out: dict[str, str] = {}
    for i, (name, at) in enumerate(starts):
        end = starts[i + 1][1] if i + 1 < len(starts) else len(block)
        out[name] = block[at:end]
    return out


#: 一个载荷字段的读法：`p.<field>`。回调的形参在这个文件里一律叫 `p`。
_FIELD_READ = re.compile(r"\bp\.([a-z_][a-z0-9_]*)\b")


# ---------------------------------------------------------------------------
# 谁写这些字段
# ---------------------------------------------------------------------------

#: `append_audit(...)` 的载荷是最后一个实参，一个字典字面量。这里不做完整的 Python
#: 解析：从事件类型的字符串字面量往后找**第一个**平衡的 `{…}`，把它里面的 `"键":`
#: 抠出来。载荷里嵌套字典时外层的键照样数得到，那正是需要的粒度。
def _payload_keys_after(text: str, at: int, window: int = 900) -> set[str]:
    chunk = text[at: at + window]
    start = chunk.find("{")
    if start < 0:
        return set()
    depth, end = 0, None
    for i in range(start, len(chunk)):
        if chunk[i] == "{":
            depth += 1
        elif chunk[i] == "}":
            depth -= 1
            if depth == 0:
                end = i
                break
    if end is None:
        return set()
    return set(re.findall(r'"([a-z_][a-z0-9_]*)"\s*:', chunk[start: end + 1]))


def _producer_index() -> dict[str, set[str]]:
    """事件类型 → 后端**真的**会往它载荷里写的字段名。

    两类生产者都要算：`engine.py` / `services.py` / `v5_api.py` 这些真实路径，
    和 `database.py` 里的演示种子。它们写的形状不一样（种子的
    `FAMILY_APPROVED_AND_EXECUTED` 带 `authority`，引擎的带 `proof_digest`），
    而凭证在两种数据上都要说得出人话，所以合法字段是**两者的并集**。
    """
    index: dict[str, set[str]] = {}
    for path in sorted(YOUHUO.glob("*.py")):
        text = path.read_text(encoding="utf-8")
        for hit in re.finditer(r'"([A-Z][A-Z0-9_]{3,})"', text):
            index.setdefault(hit.group(1), set()).update(
                _payload_keys_after(text, hit.end())
            )
    return index


@pytest.fixture(scope="module")
def producers() -> dict[str, set[str]]:
    return _producer_index()


def _unwritten_fields(block: str, index: dict[str, set[str]]) -> list[str]:
    """凭证读了、而没有任何生产者写的那些 `(事件, 字段)`。"""
    bad: list[str] = []
    for event, body in _entries(block).items():
        known = index.get(event)
        if known is None:
            # 后端源码里根本没有这个事件类型 —— 另一条判据管这件事，这里不重复报。
            continue
        for field in sorted(set(_FIELD_READ.findall(body))):
            if field not in known:
                bad.append(f"{event}.{field}")
    return bad


def test_the_producer_index_is_not_empty(producers):
    """先证明这把尺子有刻度。

    `_producer_index` 靠正则从 Python 源码里抠载荷键。它要是因为 `append_audit`
    的写法变了而抠不到东西，返回的是一堆空集合——于是下面那条对账判据对每一个字段
    都"找不到生产者"……不，更糟：`known is None` 会让它整批 `continue`，
    然后**全绿**。安静地少测和通过在结果里长得一模一样。
    """
    for event, fields in (
        ("TEACH_BACK_VERIFIED", {"attempts", "expected", "heard", "outcome"}),
        ("ELDER_CONFIRMED", {"approval_digest", "version", "amount_yuan"}),
        ("FAMILY_APPROVED_AND_EXECUTED", {"approval_digest", "proof_digest", "authority"}),
        ("FAMILY_APPROVAL_RECORDED", {"approval_count", "required_approvals", "required"}),
        ("NOTIFICATION_CREATED", {"recipient_role", "event_type"}),
    ):
        found = producers.get(event, set())
        missing = fields - found
        assert not missing, (
            f"从后端源码里没数到 `{event}` 的这些载荷字段：{sorted(missing)}。"
            f"数到的是 {sorted(found)}。\n"
            "  抠载荷的那段正则跟 `append_audit(...)` 的写法对不上了——"
            "对不上的时候下面那条对账判据会整批空过。"
        )


def test_the_receipt_never_reads_a_field_that_nobody_writes(producers):
    """凭证读的每一个载荷字段，都要有一个生产者真的写它。

    `FAMILY_APPROVAL_RECORDED` 上原先读的 `p.approval_digest` 就是反例：真实引擎在
    那条事件上写 `{approval_count, required_approvals}`，演示种子写 `{required}`，
    **没有一个写 approval_digest**。于是凭证上那一行永远是「同意的摘要 （无）」。

    这类缺陷靠补种子数据修不好，因为种子没有错；错的是这一行读错了字段。
    而它在屏幕上和"这次恰好没有值"长得一模一样——所以判据必须建在生产者那一侧。
    """
    block = _receipt_steps_block(_js("trust.js"))
    bad = _unwritten_fields(block, producers)
    assert not bad, (
        "凭证在读没有人写的载荷字段：\n    " + "\n    ".join(bad) + "\n"
        "  这一行会永远渲染成空值或占位符。要么改成读真的存在的字段，"
        "要么让后端开始写它——但不要让一句话挂在一个不存在的值上。"
    )


def test_the_producer_check_catches_a_field_nobody_writes(producers):
    """变异：把一个没人写的字段读回去，上面那条必须红。

    第一条变异就是**真的发生过的那一行**，一个字都没改。
    """
    block = _receipt_steps_block(_js("trust.js"))
    assert not _unwritten_fields(block, producers), "基线不干净，下面的变异说明不了任何事"

    anchor = "  FAMILY_APPROVAL_RECORDED: {"
    assert anchor in block, "变异锚点找不到了"
    mutations = {
        "同意的摘要（真的上线过的那一行）":
            block.replace(anchor, anchor + "\n    zz: p => `同意的摘要 ${short(p.approval_digest)}`,", 1),
        "一个纯粹不存在的字段":
            block.replace(anchor, anchor + "\n    zz: p => `${p.nobody_ever_writes_this}`,", 1),
    }
    for label, mutated in mutations.items():
        assert mutated != block, f"变异 `{label}` 没打进去"
        assert _unwritten_fields(mutated, producers), f"变异 `{label}` 没有被抓到"


# ---------------------------------------------------------------------------
# 载荷字段不许裸插值
# ---------------------------------------------------------------------------

#: 允许把一个载荷字段包在里面的函数。每一个都要么返回中文兜底、要么返回空串，
#: 总之不会让 `undefined` 走到屏幕上。
_GUARDS = ("value", "short", "Number", "String", "taskWord", "heardPair")
_GUARDED = re.compile(r"\b(?:%s)\(\s*p\.[a-z_][a-z0-9_]*" % "|".join(_GUARDS))
#: 查表加中文兜底：`RISK_WORD[p.risk] || '未标风险'`。表名与兜底都要在。
_TABLE_LOOKUP = re.compile(r"\b[A-Z][A-Z_]*\[\s*p\.[a-z_][a-z0-9_]*\s*\]\s*\|\|\s*'[^']*[一-鿿]")


def _bare_interpolations(block: str) -> list[str]:
    """模板串里**没有被包住**的载荷字段读法。

    只看 `${…}` 里面：`if (p.x)` 这样的判断读同一个字段，但那是判断不是输出。
    这个区分是上一次修完之后又被同一条判据报红的原因，写在这里免得再犯。
    """
    bad: list[str] = []
    for hole in re.finditer(r"\$\{([^{}]*(?:\{[^{}]*\}[^{}]*)*)\}", block):
        expr = hole.group(1)
        if not _FIELD_READ.search(expr):
            continue
        cleaned = _GUARDED.sub("«护»", expr)
        cleaned = _TABLE_LOOKUP.sub("«表»", cleaned)
        if _FIELD_READ.search(cleaned):
            bad.append(" ".join(expr.split())[:110])
    return bad


def test_no_receipt_template_interpolates_a_payload_field_bare(producers):
    """凭证的模板串里不许出现裸的 `${p.某字段}`。

    「第 ${p.attempts} 次通过」就是这么印出「第 undefined 次通过」的。当时的修法
    只修了 `attempts` 一个字段，而同一份模板里 `expected` / `heard` /
    `approval_digest` / `proof_digest` 全是同一种写法——**一个字段一个字段地修，
    下一个漏掉的会以完全一样的方式再咬一次**。所以判据挪到写法这一层。

    包起来的方式有两种，都算数：过一遍 `value()` / `short()` 这类守卫，
    或者查一张带中文兜底的表（`RISK_WORD[p.risk] || '未标风险'`）。
    """
    bad = _bare_interpolations(_receipt_steps_block(_js("trust.js")))
    assert not bad, (
        f"凭证模板里有 {len(bad)} 处裸插值：\n    " + "\n    ".join(bad) + "\n"
        "  载荷里没有这个字段时，这句话会照说不误，只是把值换成 `undefined`。"
    )


def test_the_bare_interpolation_probe_catches_what_actually_shipped():
    """变异：把出过事的那三种写法打回去，判据必须每一种都抓到。"""
    block = _receipt_steps_block(_js("trust.js"))
    assert not _bare_interpolations(block), "基线不干净，下面的变异说明不了任何事"

    anchor = "  TEACH_BACK_REJECTED: {"
    assert anchor in block, "变异锚点找不到了"
    mutations = {
        "第 N 次通过（真的印出 undefined 的那一行）":
            f"\n    zz: p => `第 ${{p.attempts}} 次通过`,",
        "复述金额直接拼":
            f"\n    zz: p => `系统等的是 ${{p.expected}}，听到的是 ${{p.heard}}`,",
        "查表但兜底是原值":
            f"\n    zz: p => `${{BASIS_WORD[p.semantic_basis] || p.semantic_basis}}`,",
    }
    for label, injected in mutations.items():
        mutated = block.replace(anchor, anchor + injected, 1)
        assert mutated != block, f"变异 `{label}` 没打进去"
        assert _bare_interpolations(mutated), f"变异 `{label}` 没有被抓到"


def test_the_probe_does_not_flag_the_guarded_forms():
    """反向：包好的三种写法必须**不**被报。

    一条什么都报的判据会被下一个人放宽或删掉，而那比没有它更糟。
    """
    for safe in (
        "  ZZ: {\n    zz: p => `摘要 ${short(value(p.approval_digest))}`,\n  },",
        "  ZZ: {\n    zz: p => `${RISK_WORD[p.risk] || '未标风险'}`,\n  },",
        "  ZZ: {\n    zz: p => `${taskWord(p.task_type)}`,\n  },",
    ):
        assert not _bare_interpolations(safe), f"这种写法是安全的，却被报了：{safe}"


# ---------------------------------------------------------------------------
# 那句断言必须由一次真的比较产生
# ---------------------------------------------------------------------------

#: 凭证上最要紧的一句话。它就是这一页第二条底线的全部证据。
_MATCH_CLAIM = "和他确认的是同一个"


def _match_claim_is_computed(source: str) -> bool:
    """那句话所在的 `proof` 函数体里，有没有一次真的比较。

    范围取「上一个 `proof:` 到这一条目结束」，而不是"同一条语句"：模板串里的
    `${…}` 会让按花括号找语句边界的做法在自己脚下绊倒。写死的版本长这样——

        proof: p => `同意的摘要 ${short(p.approval_digest)}，和他确认的是同一个`

    整个函数体里一个 `===` 都没有。
    """
    text = strip_js_comments(source)
    at = text.find(_MATCH_CLAIM)
    if at < 0:
        return False
    begin = text.rfind("proof:", 0, at)
    if begin < 0:
        begin = max(0, at - 400)
    end = text.find("\n  },", at)
    return "===" in text[begin: end if end != -1 else at + 400]


def test_the_receipt_compares_the_two_digests_instead_of_promising_they_match():
    """「和他确认的是同一个」必须是**算出来的**，不是写死的。

    这一句是「您确认的和家人同意的必须是同一笔，对不上就停下」这条底线在屏幕上
    唯一的证据。它原先无条件出现，既不比较也不看两边有没有值——演示数据里两边
    都没有摘要，于是屏幕上是：

        同意的摘要 （无），和他确认的是同一个

    一句凭空的保证，印在这一页最要紧的位置上。
    """
    source = _js("trust.js")
    assert _MATCH_CLAIM in source, (
        f"凭证不再说「{_MATCH_CLAIM}」了。这一页的第二条底线因此在屏幕上没有证据——"
        "如果是有意去掉的，这条判据要一起改，并说明那条底线现在由什么来证明。"
    )
    assert _match_claim_is_computed(source), (
        f"「{_MATCH_CLAIM}」不是由一次比较产生的。它得真的把老人那一条的摘要"
        "和家人这一条的摘要拿来比一次；比不了（有一边没有值）就不说这句话。"
    )


def test_the_comparison_probe_catches_an_unconditional_promise():
    """变异：把写死的那一句放回去，上一条必须红。"""
    source = _js("trust.js")
    assert _match_claim_is_computed(source), "基线不干净，这条变异说明不了任何事"
    shipped = (
        "  ZZ: {\n"
        "    proof: p => `同意的摘要 ${short(p.approval_digest)}，和他确认的是同一个`,\n"
        "  },\n"
    )
    assert not _match_claim_is_computed(shipped), (
        "判据认不出一句写死的断言——那正是它要抓的那一种"
    )


def test_the_chain_facts_helper_reads_the_elder_side_from_the_chain():
    """比较的另一头必须来自**链上**，不是来自同一条记录。

    只比 `p.approval_digest === p.approval_digest` 也能让上面那条判据变绿，
    而那是一次恒真的比较。所以这里钉住：老人那一侧是从整条链里找出来的。
    """
    text = strip_js_comments(_js("trust.js"))
    assert "function chainFacts(" in text, "chainFacts 不在了——那句比较的另一头没了来源"
    body = text[text.index("function chainFacts("):]
    body = body[: body.index("\n}\n") + 2]
    assert "ELDER_CONFIRMED" in body, "chainFacts 没有去链上找老人确认的那一条"
    assert "approval_digest" in body, "chainFacts 没有取出摘要"


# ---------------------------------------------------------------------------
# 通知类型：后端会发的，凭证都要认得
# ---------------------------------------------------------------------------

def _notify_word_keys() -> set[str]:
    text = strip_js_comments(_js("trust.js"))
    block = re.search(r"const NOTIFY_WORD = \{(.*?)\n\};", text, re.S)
    assert block, "trust.js 里找不到 NOTIFY_WORD"
    return set(re.findall(r"^\s*([a-z_]+):", block.group(1), re.M))


def test_the_receipt_names_every_notification_the_backend_can_send():
    """后端真的会发的每一种通知，凭证都要有中文说法。

    兜底「一条通知」是诚实的，但它没有信息量：一次风险 4 的缴费要两位家属点头，
    链上因此有两条 `NOTIFICATION_CREATED`，其中
    `additional_approval_required` 此前不在表里——凭证上于是出现两行长得一样的
    「一条通知」，而它们说的是完全不同的两件事。实测走得到，就在演示的默认数据上。

    名单从 `event_type="…"` 数出来，不手写：手写的表会漂，而漂了之后这条判据会
    在结果里和"全都覆盖到了"长得一模一样。
    """
    sent: set[str] = set()
    for path in sorted(YOUHUO.glob("*.py")):
        sent.update(re.findall(
            r'event_type="([a-z_]+)"', path.read_text(encoding="utf-8")))
    assert len(sent) >= 6, (
        f"只从后端数到 {len(sent)} 种通知（{sorted(sent)}）——"
        "`event_type=\"…\"` 的写法变了，这条判据在空转"
    )
    missing = sorted(sent - _notify_word_keys())
    assert not missing, (
        f"这些通知后端会发，而凭证没有说法：{missing}\n"
        "  它们会渲染成一句没有信息量的「一条通知」。"
    )


# ---------------------------------------------------------------------------
# P0：渲染一张凭证不动任何业务事务
# ---------------------------------------------------------------------------

def _token(client: TestClient, actor: str) -> dict[str, str]:
    reply = client.post("/v2/auth/demo", json={"actor_id": actor})
    assert reply.status_code == 200, reply.text
    return {"Authorization": f"Bearer {reply.json()['access_token']}"}


@pytest.fixture()
def demo_client(tmp_path, monkeypatch):
    """**评委真的会看到的那套数据**。

    `create_app` 默认 `YOUHUO_DEMO_STATE=empty`（一整批对话测试依赖"这个家庭一开始
    没有待办"），而这份文件问的全是"演示数据在这两页上渲染成什么样"。所以显式播
    `attention`：一笔已完成缴费 + 一笔停在等家属点头的缴费，正是 `run_demo` 起的
    那一套。

    显式 `monkeypatch.setenv` 而不是靠 `seed_baseline_history=True`：环境变量在
    `create_app` 里**优先于**那个参数，跑测试的人把它设成 `empty` 时，参数版会静默
    退回没有数据——而"没有数据"在这份文件里会让四条判据一起空过。
    """
    monkeypatch.setenv("YOUHUO_DEMO_STATE", "attention")
    app = create_app(tmp_path / "polish.db", demo_mode=True)
    with TestClient(app) as client:
        yield client


def _newest_task(client: TestClient, family: dict[str, str]) -> dict:
    tasks = client.get("/v2/tasks?limit=100", headers=family).json()
    assert tasks, (
        "演示沙箱里一件任务都没有——`YOUHUO_DEMO_STATE=attention` 没有播进去，"
        "这一条会变成空转"
    )
    return max(tasks, key=lambda t: str(t["updated_at"]))


def _chain_state(client: TestClient, family: dict[str, str]) -> tuple[int, list]:
    """这个家庭此刻的样子：链有多长，每一笔事务停在哪一步、更新到什么时候。

    取 `updated_at` 而不是 `version`：`/v2/tasks` 的对外投影里没有 `version`
    （`privacy.py` 只放出 id / status / summary / details / 时间戳）。
    读一个不存在的键会 KeyError 而不是静默相等——那是好事，但用在这里
    只会让判据在**探针自己**的错误上红。
    """
    audit = client.get("/v2/audit?limit=500", headers=family).json()
    tasks = client.get("/v2/tasks?limit=100", headers=family).json()
    return (
        len(audit.get("events", [])),
        sorted((t["id"], t["status"], t["updated_at"]) for t in tasks),
    )


def test_rendering_a_receipt_leaves_the_chain_exactly_as_it_found_it(demo_client):
    """把这一页的请求序列真的发一遍，前后链长和任务状态必须一个字节都不差。

    `test_receipt_is_read_only.py` 从**源码**上钉住"不许有写方法"，这一条从
    **行为**上钉住同一件事：源码判据只认得 `api(…, {method: 'POST'})` 这一种写法，
    一个 `fetch()`、一个带副作用的 GET 都能绕过它。这里数的是结果。

    序列取自 `renderReceipt`：先 `/v2/tasks`，再按 `entity_id` 取那一件的链。
    """
    family = _token(demo_client, "daughter-demo")
    before = _chain_state(demo_client, family)

    # ---- 这一页做的全部事情 ----
    newest = _newest_task(demo_client, family)
    chain = demo_client.get(
        f"/v2/audit?limit=200&entity_id={newest['id']}", headers=family).json()
    assert chain.get("events"), "那一笔在链上一条记录都没有，凭证渲染不出来"

    after = _chain_state(demo_client, family)
    assert after == before, (
        "渲染一张凭证改动了这个家庭的状态。\n"
        f"  之前：{before[0]} 条链、{before[1]}\n"
        f"  之后：{after[0]} 条链、{after[1]}\n"
        "  /trust 是只读页：不许创建、推进、批准、执行、重试或改动任何一笔业务事务。"
    )


def test_the_read_only_probe_can_see_a_write(demo_client):
    """判据自检：这套前后对比真的量得出一次写吗。

    上一条如果因为 `_chain_state` 读错了东西而永远相等，它会安静地一直绿。
    所以拿一次**已知会写**的调用喂给同一把尺子。
    """
    family = _token(demo_client, "daughter-demo")
    before = _chain_state(demo_client, family)
    demo_client.get(
        f"/v5/tasks/{_newest_task(demo_client, family)['id']}/explain", headers=family)
    after = _chain_state(demo_client, family)
    assert after != before, (
        "一次已知会往链上写记录的调用，前后对比量不出来——上一条判据是空转的"
    )


# ---------------------------------------------------------------------------
# 评委页
# ---------------------------------------------------------------------------

def test_the_explain_card_really_answers_with_two_raw_enums(demo_client):
    """先证明这个风险是真的：后端那一行确实是两个英文枚举。

    没有这一条，下面那条前端判据就是在防一个想象出来的问题——而如果后端哪天把
    `summary` 改成一句人话，那条判据的理由也就不成立了，它应该跟着重估，
    而不是继续拦着。
    """
    family = _token(demo_client, "daughter-demo")
    card = demo_client.get(
        f"/v5/tasks/{_newest_task(demo_client, family)['id']}/explain",
        headers=family).json()
    assert re.fullmatch(r"[a-z_]+ · [a-z_]+", card["summary"]), (
        f"`/v5/…/explain` 的 summary 现在是 {card['summary']!r}，"
        "不再是两个英文枚举了。评委页那一层翻译的理由要重估。"
    )


def test_the_workbench_never_shows_the_explain_summary_raw():
    """评委页不许把 `card.summary` 直接摆到「这件事是什么」那一行上。

    它原先就是这么写的，屏幕上是「这件事是什么：bill_payment · completed」，
    而**下一行**的 `current_status` 已经翻成了「办好了」。
    `judge.js` 文件头第二条：枚举一律翻译，认不出就说认不出，不回落到原值。
    """
    text = strip_js_comments(_js("judge.js"))
    bad = re.findall(r"[一-鿿]+\s*:\s*card\.summary\b", text)
    assert not bad, (
        f"评委页把 explain 卡的 summary 原样渲染了：{bad}。"
        "那是后端拼的 `<类型枚举> · <状态枚举>`，不是一句摘要。"
    )
    assert "function taskSummary(" in text, (
        "翻译那一层（`taskSummary`）不在了——`card.summary` 会重新原样上屏"
    )


def test_reading_the_decision_context_really_appends_to_the_chain(demo_client):
    """先证明这个风险是真的：取一次决策上下文，链上真的会多一条，而且排在最后。

    评委页默认摊开「最后一步」。如果这一条不成立，下面那条判据（默认那一步要跳过
    这一页自己写的记录）就是在防一个不存在的问题。
    """
    family = _token(demo_client, "daughter-demo")
    task_id = _newest_task(demo_client, family)["id"]
    demo_client.get(f"/v5/tasks/{task_id}/explain", headers=family)
    chain = demo_client.get(
        f"/v2/audit?limit=200&entity_id={task_id}", headers=family).json()
    events = chain["events"]
    assert events, "链是空的"
    assert events[-1]["event_type"] == "TASK_EXPLANATION_VIEWED", (
        "取决策上下文之后，链上最后一条不是调阅记录了："
        f"{events[-1]['event_type']}。默认摊开哪一步的判据要跟着重估。"
    )


def _judge_const_list(name: str) -> list[str]:
    text = strip_js_comments(_js("judge.js"))
    block = re.search(rf"const {name} = \[(.*?)\];", text, re.S)
    assert block, f"judge.js 里找不到 `const {name}`"
    return re.findall(r"'([A-Z_]+)'", block.group(1))


def test_the_default_step_skips_what_the_page_itself_wrote():
    """默认摊开的那一步，不许是这一页自己刚写下的调阅记录。

    原先是 `state.events[state.events.length - 1]`。第二次打开这一页时链上最后一条
    正是这一页刚写的 `TASK_EXPLANATION_VIEWED`，于是「它现在停在哪儿」的答案变成了
    「有人看过它」。

    而它还看不见：默认档位是「只看关键步骤」，调阅记录不在关键步骤里——右边摊开着
    一条左边列表里根本找不到的记录，时间轴上一条高亮都没有。实测如此。
    """
    text = strip_js_comments(_js("judge.js"))
    assert "function defaultStep(" in text, "defaultStep 不在了"
    body = text[text.index("function defaultStep("):]
    body = body[: body.index("\n}\n") + 2]
    assert "PAGE_OWN_EVENTS" in body, "默认那一步没有排掉这一页自己写的记录"
    assert "visibleEvents(" in body, (
        "默认那一步不是从**当前档位真的显示出来的**那一批里挑的——"
        "挑出一条不在左边列表里的记录，正是这条判据要挡的那种"
    )
    own = _judge_const_list("PAGE_OWN_EVENTS")
    assert "TASK_EXPLANATION_VIEWED" in own, (
        f"`PAGE_OWN_EVENTS` 是 {own}，里面没有这一页真的会写的那一条"
    )
    key = _judge_const_list("KEY_EVENTS")
    assert "TASK_EXPLANATION_VIEWED" not in key, (
        "调阅记录被算成了关键步骤。它不改变这一笔的去向，而且把它算进去只会让"
        "「只看关键步骤」被这一页自己的痕迹淹掉。"
    )


def test_the_address_bar_decides_which_transaction_on_the_first_load():
    """地址栏里的编号必须在**首次载入**时胜出。

    `wantedId()` 的文档一直写着「地址栏里指定的 → 输入框里填的 → 选单选中的」，
    而代码写的是 `typed || picked || fromHash`——地址栏排第三。它因此一次都没生效
    过：`loadTaskList()` 一填选项，浏览器就自动选中第一条，`picked` 永远非空。
    实测把 `/judge#task-seed-await-…` 交给一个全新标签页，打开的是另一笔事务，
    而页面不说任何一句话。

    这一页的主张是「主动权在看的人手里」，而递一个链接过去正是"别人指定"唯一的形式。
    """
    text = strip_js_comments(_js("judge.js"))
    assert "INITIAL_HASH" in text, "地址栏那个编号没有在载入时被读住"
    body = text[text.index("function wantedId("):]
    body = body[: body.index("\n}\n") + 2]
    hash_at = body.find("INITIAL_HASH")
    assert hash_at >= 0, "wantedId 不看地址栏了"
    for later in ("typed", "picked"):
        at = body.find(later)
        assert at < 0 or at > hash_at, (
            f"`{later}` 排在地址栏前面——首次载入时它一定非空，地址栏永远轮不到"
        )


# ---------------------------------------------------------------------------
# 印章不许压在那个折叠控件上
# ---------------------------------------------------------------------------

def test_the_seal_has_a_band_of_its_own():
    """印章要有自己的一条带，不许盖在「看这件事的哈希」上面。

    那个 `<details>` 是 /trust 上**唯一**一个可以点的东西，`pages.css` 专门给它加了
    边框、48px 高和一个 `＋` 展开标记。而印章绝对定位在右下角，正好压在那个标记上。

    三道闸门当时全绿：`pointer-events: none` 让它还点得动（点击遍历过），
    颜色没变（对比度过），也没有溢出（截图过）。屏幕上是一枚章压着一个控件。
    """
    css = (STATIC / "art-cards.css").read_text(encoding="utf-8")

    def number(pattern: str, where: str) -> int:
        hit = re.search(pattern, css)
        assert hit, f"art-cards.css 里找不到{where}"
        return int(hit.group(1))

    size = number(r"--art-seal-size:\s*(\d+)px", "印章尺寸变量")
    inset = number(r"--art-seal-inset:\s*(\d+)px", "印章内缩变量")
    rule = re.search(r"\.art-receipt\[data-art-seal\]\s*\{([^}]*)\}", css, re.S)
    assert rule, (
        "`.art-receipt[data-art-seal]` 没有给印章留出那条带——"
        "章会重新压回「看这件事的哈希」那个控件上，而且没有任何东西会报错。"
    )
    band = re.search(r"padding-bottom:\s*([^;]+);", rule.group(1))
    assert band, "那条规则里没有 `padding-bottom`——留白不是靠它来的？"
    formula = band.group(1)
    assert "--art-seal-size" in formula and "--art-seal-inset" in formula, (
        f"那条带的高度写死成了 {formula!r}。改了章的大小之后它不会跟着变，"
        "而错的方向只有一个：章重新压回控件上。"
    )
    # 变量取不到时整条声明会被丢掉（CSS 不报错），所以每一处引用都要有兜底值。
    for name, fallback in (("--art-seal-size", size), ("--art-seal-inset", inset)):
        for use in re.findall(rf"var\(\s*{name}\s*([^)]*)\)", css):
            assert use.strip().startswith(","), (
                f"`var({name})` 有一处没写兜底值。这个变量定义在 `.art-receipt` 上，"
                "在别的宿主下取不到——CSS 不报错，它把整条声明丢掉。"
            )
        assert fallback  # 变量本身有值，上面那条断言才有意义
