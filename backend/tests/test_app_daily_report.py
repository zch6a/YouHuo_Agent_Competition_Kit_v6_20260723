"""`/api/v1/daily-report` —— 老人自己看得到的「我这几天怎么样」。

## 这一层此前没有入口

`GET /v7/daily-report/{elder}` 和 `GET /v7/baseline/{elder}` 都在，而且
`baseline_api.py` 顶上明确写着老人本人也能看（「一份关于自己的报告不让本人看，
与这个项目'过程透明'的立场相悖」）。缺的只是老人端的入口。

## 这份文件守的四条性质

1. **真的调 v7，不在门面里重算一遍基线。** 那六行胶水里有两处这个项目踩过的坑
   （按老人时区切「今天」、当天没过完时压制还没到点的通道）。抄一份就是第二个
   实现，而「同一件事两套实现」在这个项目里红过三次。
2. **不许把写给子女的第三人称句子搬到老人自己这一屏上。** 底层那几句
   `explanation` 是「比**他**平常晚了 1 小时 40 分」。在这一层改写人称同样不行：
   `其他` 会被改成 `其您`。所以只转述结构化的值。
3. **界面上不出现 `typical` / `marked`。**
4. **看一眼不许改动任何事务。**
"""
from __future__ import annotations

import re
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from youhuo.api import create_app
from youhuo.baseline import Verdict
from youhuo.utils import local_today

V1 = "/api/v1"
APP_API = Path(__file__).resolve().parents[1] / "youhuo" / "app_api.py"

#: v7 的基线通道，中文名由 `baseline_services.CHANNEL_LABELS` 定。
CHANNELS = ("起床", "就寝", "外出", "服药", "说话")


@pytest.fixture()
def client(tmp_path):
    app = create_app(tmp_path / "app_daily.db", demo_mode=True, seed_baseline_history=True)
    with TestClient(app) as c:
        yield c


@pytest.fixture()
def sandbox(client: TestClient) -> dict:
    r = client.post("/v2/auth/visitor")
    assert r.status_code == 200, r.text
    return r.json()


@pytest.fixture()
def elder(sandbox) -> dict[str, str]:
    return {"Authorization": "Bearer " + sandbox["elder_token"]}


def _report(client: TestClient, headers=None, **params) -> dict:
    r = client.get(f"{V1}/daily-report", params=params, headers=headers)
    assert r.status_code == 200, r.text
    return r.json()


def _verdict_words() -> dict[str, str]:
    """`_VERDICT_WORDS` 是 `build_app_router` 里的闭包局部变量，只能从源码里读。"""
    text = APP_API.read_text(encoding="utf-8")
    start = text.index("    _VERDICT_WORDS = {")
    return dict(re.findall(r'"([^"]+)":\s*"([^"]+)"', text[start : text.index("\n    }", start)]))


# ---- 自证 --------------------------------------------------------------------


def test_the_probe_actually_reads_something(client, elder) -> None:
    assert len(_verdict_words()) == 5, "判断词表没解析出来，下面几条是空转的"
    got = _report(client, elder)
    assert len(got["channels"]) == len(CHANNELS), f"只读到 {len(got['channels'])} 个通道"
    assert got["observedDays"] >= 14, f"沙箱里只有 {got['observedDays']} 天作息，基线立不起来"


# ---- ① 真的接到 v7 上 ----------------------------------------------------------


def test_the_facade_reaches_the_real_v7_endpoints(client, elder, sandbox) -> None:
    """门面给的数字，必须和 `/v7` 直接问出来的一样。

    这一条同时钉住「按路径取端点函数」那段：v7 改了路径，`_v7_call` 会 503，
    而不是悄悄少半边内容。
    """
    got = _report(client, elder)
    raw = client.get(f"/v7/daily-report/{sandbox['elder_id']}", headers=elder)
    base = client.get(f"/v7/baseline/{sandbox['elder_id']}", headers=elder)
    assert raw.status_code == 200 and base.status_code == 200

    report, alert = raw.json()["report"], raw.json()["alert"]
    snapshot = base.json()
    assert got["day"] == report["day"]
    assert got["todayWord"] == _verdict_words()[report["overall"]]
    assert got["observedDays"] == snapshot["observed_days"]
    assert got["established"] == snapshot["established"]
    assert got["errands"]["dueToday"] == report["errands"]["due_today"]
    assert got["errands"]["overdue"] == report["errands"]["overdue"]
    assert got["errands"]["waitingFamily"] == report["errands"]["awaiting_family"]
    assert got["errands"]["lines"] == report["errands"]["lines"]
    assert got["privacyNote"] == report["privacy_note"]
    assert got["familyWillSeeBecause"] == (
        (["今天的作息和您平常不一样"] if alert["baseline_deviated"] else [])
        + (["有该办的事快要误了"] if alert["errand_at_risk"] else [])
    )


@pytest.fixture()
def busy_today(client: TestClient, sandbox, elder) -> dict[str, str]:
    """给今天造出真实的活动记录。

    **没有这一步，「今天」那一栏整列都是 null**，于是 `row["today"] ==
    dev["observed_text"]` 变成五次 `None == None`——一条把这一栏写死成 null 的改动
    照样全绿。这不是假设：这条判据的第一版就是这样，变异测试当场证明它是空转的。

    外出发三条而不是一条：`_withhold_if_premature` 会在一天没过完时压制**偏少**的
    那一侧（常态 2 次，只发 1 次会被压回 None，判据又空转了）。
    """
    now = datetime.now(UTC)
    for i in range(3):
        r = client.post(
            "/v4/location/ping",
            json={
                "elder_id": sandbox["elder_id"],
                "latitude": 31.20 + i * 0.01,
                "longitude": 121.40,
                "occurred_at": (now - timedelta(minutes=30 * i)).isoformat(),
            },
            headers=elder,
        )
        assert r.status_code == 200, r.text
    assert client.post(f"{V1}/voice/sessions", json={}, headers=elder).status_code == 200
    return elder


def test_every_channel_carries_the_backends_own_numbers(client, busy_today, sandbox) -> None:
    """「平常几点 / 今天几点」两栏都要来自 `/v7/baseline`，不是这一层算的。"""
    got = {c["name"]: c for c in _report(client, busy_today)["channels"]}
    assert set(got) == set(CHANNELS), f"通道对不上：{sorted(got)}"
    snapshot = client.get(f"/v7/baseline/{sandbox['elder_id']}", headers=busy_today).json()
    usual = {b["label"]: b["center_text"] for b in snapshot["baselines"]}
    words = _verdict_words()
    for dev in snapshot["deviations"]:
        row = got[dev["label"]]
        assert row["today"] == dev["observed_text"]
        assert row["usual"] == (usual[dev["label"]] or dev["center_text"])
        assert row["word"] == words[dev["verdict"]]
    # 两栏都要真的有值，否则上面那一圈比较是 None == None。
    assert sum(1 for r in got.values() if r["usual"]) >= 3, f"常态几乎全空：{got}"
    assert sum(1 for r in got.values() if r["today"]) >= 2, f"「今天」整列是空的：{got}"


# ---- ② 不许把子女侧的句子搬过来 --------------------------------------------------


def test_the_elder_screen_never_shows_the_family_facing_sentences(client, elder, sandbox) -> None:
    """底层那几句 `explanation` / `reason` 是写给子女的第三人称。

    「比**他**平常晚了 1 小时 40 分」出现在老人自己这一屏上，人称就错了。
    先确认底层这一版**确实**在说「他」，否则这条判据什么都没验。
    """
    raw = client.get(f"/v7/daily-report/{sandbox['elder_id']}", headers=elder).text
    assert "他" in raw, "底层这一版没有第三人称句子了，这条判据失去依据——先修判据"

    body = client.get(f"{V1}/daily-report", headers=elder).text
    assert "他平常" not in body, "写给子女的「比他平常……」被搬到了老人自己这一屏上"
    assert "他今天" not in body
    assert "其您" not in body, "有人拿字符串替换改人称——`其他` 会被改成 `其您`"


def test_the_headline_does_not_say_the_same_word_twice(client, elder) -> None:
    """判断词自带主语（「今天还没有记录」），前面再拼一个「今天」就是「今天今天」。

    五个取值里有两个这样，另外三个拼起来完全通顺——只看一眼演示数据发现不了。
    """
    words = _verdict_words()
    assert "今天还没有记录" in words.values(), "判断词改了，这条判据的依据变了"
    for day in (None, local_today(datetime.now(UTC)) - timedelta(days=1)):
        got = _report(client, elder, **({"day": day.isoformat()} if day else {}))
        assert "今天今天" not in got["message"], f"文案把「今天」说了两遍：{got['message']}"
        assert got["message"].startswith(got["todayWord"]) or not got["established"]


# ---- ③ 不出现英文枚举 -----------------------------------------------------------


def test_every_verdict_the_backend_can_produce_has_a_chinese_word() -> None:
    table = _verdict_words()
    missing = sorted(v.value for v in Verdict if v.value not in table)
    assert not missing, f"这些判断没有中文说法，会落到兜底的「说不准」：{missing}"
    assert all(re.search(r"[一-龥]", w) for w in table.values())


def test_no_english_enum_reaches_the_screen(client, elder) -> None:
    got = _report(client, elder)
    shown = " ".join(
        [got["todayWord"], got["familyWillSee"], got["message"], got["privacyNote"]]
        + [c["word"] for c in got["channels"]]
        + got["familyWillSeeBecause"]
        + got["errands"]["lines"]
    )
    leaked = [t for t in [v.value for v in Verdict] + ["push", "digest", "none"] if t in shown]
    assert not leaked, f"这些内部枚举漏到屏幕上了：{leaked}"


def test_the_elder_is_told_whether_the_family_will_be_disturbed(client, elder) -> None:
    """老人有权知道系统替他跟家人说了什么。这一栏不许是空的，也不许是 `digest`。"""
    got = _report(client, elder)
    assert got["familyWillSee"], "没有说家人那边会怎么样"
    assert re.search(r"[一-龥]", got["familyWillSee"])
    assert "家人" in got["familyWillSee"]
    assert got["familyWillSee"] != "家人那边这次没有给出处理方式。", (
        "落到了兜底文案——说明 alert.channel 有一个取值没有中文说法"
    )


# ---- ④ 看一眼不许改动任何事务 ----------------------------------------------------


def test_reading_the_report_changes_nothing(client, elder) -> None:
    audit = client.get(f"{V1}/records", params={"limit": 1}, headers=elder).json()["total"]
    tasks = client.get("/v2/tasks", headers=elder).text
    first = _report(client, elder)
    second = _report(client, elder)
    assert client.get(f"{V1}/records", params={"limit": 1}, headers=elder).json()["total"] == audit
    assert client.get("/v2/tasks", headers=elder).text == tasks
    assert first == second, "读两遍结果不一样，说明读这一屏改动了什么"


# ---- ⑤ 日期边界由 v7 那一侧把关 ---------------------------------------------------


def test_a_future_day_is_refused_in_chinese(client, elder) -> None:
    """`_validated_day` 那道闸门要真的生效——它挡的是 500，不是 400。"""
    tomorrow = (local_today(datetime.now(UTC)) + timedelta(days=1)).isoformat()
    r = client.get(f"{V1}/daily-report", params={"day": tomorrow}, headers=elder)
    assert r.status_code == 400, f"未来的日期被放行了：{r.status_code} {r.text[:200]}"
    assert "未来" in r.json()["detail"]


def test_a_day_far_in_the_past_is_refused_not_crashed(client, elder) -> None:
    r = client.get(f"{V1}/daily-report", params={"day": "0001-01-01"}, headers=elder)
    assert r.status_code == 400, f"应当是 400 而不是 {r.status_code}：{r.text[:200]}"


def test_yesterday_is_a_different_day(client, elder) -> None:
    """`day=` 要真的进到查询里，而不是一个被忽略的参数。

    直接调 v7 的函数时 FastAPI 不在链路上，`Query(default=None)` 的默认值是那个
    **Query 对象本身**——漏传 `day=` 会拿它去和 date 比大小。这一条钉住它传到了。
    """
    yesterday = (local_today(datetime.now(UTC)) - timedelta(days=1)).isoformat()
    assert _report(client, elder, day=yesterday)["day"] == yesterday
    assert _report(client, elder)["day"] == local_today(datetime.now(UTC)).isoformat()


def test_the_family_may_read_the_elders_report(client, sandbox) -> None:
    """这一层是老人端的门面：家人拿令牌进来，看的仍然是老人的日报。"""
    fam = {"Authorization": "Bearer " + sandbox["family_token"]}
    assert _report(client, fam)["observedDays"] == _report(
        client, {"Authorization": "Bearer " + sandbox["elder_token"]}
    )["observedDays"]
