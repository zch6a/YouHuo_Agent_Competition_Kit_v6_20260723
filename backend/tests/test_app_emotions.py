"""`/api/v1/emotions/review` —— 老人自己看得到的心情回顾。

## 这一层此前没有入口

`POST /v4/emotions/analyze` 一直在记，`GET /v4/reports/emotion/{elder}` 一直能出
汇总，而这份汇总只有家属端 `/care` 在读。老人自己看不到关于自己心情的任何东西。

## 两条硬性质

**① 不许把聊天原文漏出来。** `/v4/reports/emotion` 是**汇总**——类别计数、趋势、
几句建议，连原文的 sha256 都不在里面。「他和无忧伴聊过的话不会出现在这里」是写在
界面上的承诺，门面层不许把它破掉。

**② 不许替产品把结论编出来。** KNOWN_ISSUES 记着：上一个 agent 做情绪时，
它自己写的测试报「情绪趋势是编造出来的上升」，那批改动整段回退
（`v4_store.seed_demo_content` 的注释里也记着同一件事）。所以这里钉的是
「趋势是**转述**的」——门面给出的那句话必须由底层算出来的那个值决定，
不是这一层看着计数自己判的。

## 数据从哪儿来

`create_app(..., seed_baseline_history=True)` **不种** `emotion_events`——那张表
只在 `/v2/auth/visitor` 那条路上种。沙箱里的序列是刻意**稳定**的（七天里六天平静、
一天孤单），趋势应当报 `stable_or_insufficient`：演示数据可以有内容，
但不能是一个「情绪逐日改善」的故事。
"""
from __future__ import annotations

import hashlib
import re
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from youhuo.api import create_app
from youhuo.utils import local_today
from youhuo.v4_models import EmotionLabel

V1 = "/api/v1"
APP_API = Path(__file__).resolve().parents[1] / "youhuo" / "app_api.py"
V4_STORE = Path(__file__).resolve().parents[1] / "youhuo" / "v4_store.py"


@pytest.fixture()
def client(tmp_path):
    app = create_app(tmp_path / "app_emotions.db", demo_mode=True, seed_baseline_history=True)
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


def _review(client: TestClient, headers, **params) -> dict:
    r = client.get(f"{V1}/emotions/review", params=params, headers=headers)
    assert r.status_code == 200, r.text
    return r.json()


def _table(name: str) -> dict[str, str]:
    """从 `app_api.py` 源码里读一张翻译表。

    不导入模块：这两张表是 `build_app_router` 里的闭包局部变量，导入拿不到，
    而 import 这个模块要连库、要 seed 演示数据。
    """
    text = APP_API.read_text(encoding="utf-8")
    start = text.index(f"    {name} = {{")
    body = text[start : text.index("\n    }", start)]
    return dict(re.findall(r'"([^"]+)":\s*"([^"]+)"', body))


# ---- 自证：这些判据真的读到了东西 ---------------------------------------------


def test_the_probes_actually_read_something(client, elder) -> None:
    """解析失败返回空 dict、沙箱里一条记录都没有——两种情况都会让下面全绿。"""
    assert len(_table("_MOOD_WORDS")) >= 5, "情绪翻译表没解析出来，下面几条是空转的"
    assert len(_table("_TREND_WORDS")) == 3, "趋势翻译表没解析出来"
    assert _review(client, elder)["count"] >= 5, "沙箱里没有心情记录，断言会空转"


# ---- ① 枚举一个都不许漏 --------------------------------------------------------


def test_every_mood_the_backend_can_report_has_a_chinese_word() -> None:
    """漏掉一个标签不会报错：那一类会显示成兜底的「说不上来」。"""
    table = _table("_MOOD_WORDS")
    missing = sorted(label.value for label in EmotionLabel if label.value not in table)
    assert not missing, f"这些情绪没有中文说法，会落到兜底文案：{missing}"
    assert all(re.search(r"[一-龥]", w) for w in table.values())


def test_every_trend_the_backend_writes_has_a_chinese_word() -> None:
    """后端会写的每一个趋势取值，翻译表里都要有。

    取值从 `v4_store.py` 源码里读，不在这里手抄一份——抄的那一份会在后端加了
    第四个取值的时候静默过时，而屏幕上只会多出一句「暂时说不上来」。
    """
    written = set(re.findall(r'trend = "([a-z_]+)"', V4_STORE.read_text(encoding="utf-8")))
    assert len(written) == 3, f"从 v4_store 里读到 {len(written)} 个趋势取值，解析大概不对：{written}"
    missing = sorted(written - set(_table("_TREND_WORDS")))
    assert not missing, f"这些趋势没有中文说法：{missing}"


def test_no_english_enum_reaches_the_screen(client, elder) -> None:
    got = _review(client, elder)
    body = " ".join(
        [got["trend"], got["message"], got["privacyNote"]]
        + [m["name"] for m in got["moods"]]
        + list(got["suggestions"])
    )
    leaked = [
        token
        for token in [label.value for label in EmotionLabel]
        + ["distress_increasing", "distress_decreasing", "stable_or_insufficient", "distress"]
        if token in body
    ]
    assert not leaked, f"这些内部枚举漏到屏幕上了：{leaked}"


# ---- ② 趋势是转述的，不是编的 --------------------------------------------------


def test_the_trend_is_transcribed_from_the_backend_not_invented(client, elder, sandbox) -> None:
    """门面给的那句话，必须由底层算出来的那个取值决定。

    对照的是**同一个窗口**下 `/v4/reports/emotion` 的原始 `summary.trend`。
    这一层要是自己看着计数判一个趋势出来，两边就会各说各的。
    """
    days = 14
    end = local_today(datetime.now(UTC))
    start = end - timedelta(days=days - 1)
    raw = client.get(
        f"/v4/reports/emotion/{sandbox['elder_id']}",
        params={"period_start": start.isoformat(), "period_end": end.isoformat()},
        headers=elder,
    )
    assert raw.status_code == 200, raw.text
    backend_trend = raw.json()["summary"]["trend"]

    got = _review(client, elder, days=days)
    assert got["fromDate"] == start.isoformat() and got["toDate"] == end.isoformat()
    assert got["trend"] == _table("_TREND_WORDS")[backend_trend], (
        f"底层说 {backend_trend}，门面说「{got['trend']}」——这一层在自己下结论"
    )


def test_the_seeded_week_is_not_told_as_an_improvement_story(client, elder) -> None:
    """沙箱那七天是**稳定**的：六天平静、一天孤单。

    这一条钉的是上一次事故本身。一个「情绪逐日好转」的曲线正是这个产品最不该
    伪造的东西，而它在屏幕上和真实好转长得一模一样。
    """
    got = _review(client, elder)
    assert "差不多" in got["trend"], f"稳定的一周被说成了别的：「{got['trend']}」"
    for made_up in ("好转", "越来越", "持续改善", "紧张一些", "松快一些"):
        assert made_up not in got["trend"] + got["message"], f"文案里有编出来的结论：{made_up}"


def test_an_empty_window_claims_nothing(tmp_path) -> None:
    """一条记录都没有的时候，不许说「好」也不许说「不好」。"""
    app = create_app(tmp_path / "empty.db", demo_mode=True, seed_baseline_history=False)
    with TestClient(app) as c:
        got = _review(c, None)
    assert got["count"] == 0
    assert got["moods"] == []
    assert "还没有记下心情" in got["message"]
    assert "没有记录不等于不好" in got["message"], "空态替老人下了结论"


# ---- ③ 原文一个字都不许出来 ----------------------------------------------------


def test_the_review_never_carries_chat_text_or_its_fingerprint(client, elder, sandbox) -> None:
    """**这一条是这份文件里最重要的。**

    「他和无忧伴聊过的话不会出现在这里」是写在界面上的承诺。原文不能出现，
    原文的 sha256 也不能——一个能拿去比对的指纹同样是原文的一部分。
    """
    secret = "我昨天在菜市场跟老张吵了一架心里堵得慌"
    posted = client.post(
        "/v4/emotions/analyze",
        json={"elder_id": sandbox["elder_id"], "text": secret, "store_event": True},
        headers=elder,
    )
    assert posted.status_code == 200, posted.text

    body = client.get(f"{V1}/emotions/review", headers=elder).text
    assert secret not in body, "聊天原文漏进了心情回顾"
    assert "老张" not in body and "菜市场" not in body, "原文的片段漏了出来"
    assert hashlib.sha256(secret.encode("utf-8")).hexdigest() not in body, (
        "原文的指纹漏了出来——它同样能拿去比对"
    )
    assert "无忧伴" in body, "界面上应当写着那句承诺，而它不见了"


# ---- ④ 看一眼不许改动业务 ------------------------------------------------------


def test_reading_the_review_changes_no_transaction(client, elder) -> None:
    """底层会把这份汇总缓存进 `privacy_reports`（`/v4` 那一侧本来就是这样），
    但**业务事务**一笔都不许动，审计链也不许多一条。
    """
    audit = client.get(f"{V1}/records", params={"limit": 1}, headers=elder).json()["total"]
    tasks = client.get("/v2/tasks", headers=elder).text
    _review(client, elder)
    _review(client, elder, days=7)
    assert client.get(f"{V1}/records", params={"limit": 1}, headers=elder).json()["total"] == audit
    assert client.get("/v2/tasks", headers=elder).text == tasks


# ---- ⑤ 窗口有边界 --------------------------------------------------------------


@pytest.mark.parametrize("days", [0, 32, 400])
def test_an_impossible_window_is_refused(client, elder, days) -> None:
    """底层最多接受 32 天，再宽就是 422。这一层不许把一个必然失败的请求转下去。"""
    assert client.get(f"{V1}/emotions/review", params={"days": days}, headers=elder).status_code == 422


def test_a_shorter_window_really_is_shorter(client, elder) -> None:
    """`days` 要真的进到查询里去，而不是一个被忽略的参数。"""
    wide, narrow = _review(client, elder, days=31), _review(client, elder, days=1)
    assert wide["days"] == 31 and narrow["days"] == 1
    assert narrow["fromDate"] == narrow["toDate"]
    assert wide["count"] >= narrow["count"], "窄窗口反而记得更多，说明 days 没有进查询"
