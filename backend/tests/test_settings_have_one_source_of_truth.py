"""字号和语速只有一个事实源。

## 为什么这份文件存在

`/api/v1/settings` 曾经在 `memory_items` 里自己存了一份字号语速，
而真正的事实源是 v6 交互档案 `interaction_profiles_v6`。实测出来是这样：

    老人说「说慢一点」 → 它回答「好，我说慢一点。」
                       → 档案 0.88 降到 0.80
                       → 而 `POST /api/v1/speech` 仍然用 1.0 念

**它答应了，然后用原速念。** 反过来拖滑块只动 App 这一份，
下一次「说慢一点」从档案的旧值继续减；`/v6/interaction/plan` 也照旧值排版。

## 为什么此前的测试全绿

那时 settings 的测试是「PUT 一个值，GET 回来还是它」——**在同一个存储里往返**。
v6 那侧的测试也在自己那份里往返。两边各自都对，合起来才错。
所以这份文件里没有一条是单端点往返：每一条都跨两个子系统。
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from youhuo.api import create_app

V1 = "/api/v1"
ELDER = "elder-demo"


@pytest.fixture()
def client(tmp_path):
    app = create_app(tmp_path / "one_truth.db", demo_mode=True, seed_baseline_history=True)
    with TestClient(app) as c:
        yield c


@pytest.fixture()
def elder_headers(client: TestClient) -> dict[str, str]:
    token = client.post("/v2/auth/demo", json={"actor_id": ELDER}).json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


def _profile(client: TestClient, headers: dict[str, str]) -> dict:
    r = client.get(f"/v6/profiles/{ELDER}", headers=headers)
    assert r.status_code == 200, r.text
    return r.json()


def _app_speed(client: TestClient) -> float:
    return client.get(f"{V1}/speech/status").json()["speed"]


def _say(client: TestClient, headers: dict[str, str], text: str) -> dict:
    """走真实的对话入口说一句话。

    直接调 `care_voice.adjust_profile` 会绕开会话、意图分类和档案写回——
    那样测的是我挑出来的那个函数，不是老人说话这条路。
    """
    sid = client.post("/v2/sessions", headers=headers, json={}).json()["session_id"]
    r = client.post("/v2/chat", headers=headers, json={"session_id": sid, "text": text})
    assert r.status_code == 200, r.text
    return r.json()


# ---------------------------------------------------------------- 阳性对照


def test_the_spoken_command_really_does_move_the_profile(client, elder_headers) -> None:
    """先证明「说慢一点」这条路本身是通的。

    没有这一条，下面每一条都可能因为**这句话根本没被听懂**而假绿：
    档案没动、App 也没动，两边一致，判据通过。
    """
    before = _profile(client, elder_headers)["speech_rate"]
    _say(client, elder_headers, "你说慢一点")
    after = _profile(client, elder_headers)["speech_rate"]
    assert after < before, f"「说慢一点」没有改动交互档案（{before} → {after}），下面的判据都不成立"


def test_the_fixture_starts_with_a_profile_that_differs_from_the_old_hardcoded_default(
    client, elder_headers
) -> None:
    """种子档案不是 1.0/1.0。

    旧实现的默认值恰好是 fontScale=1.0、voiceSpeed=1.0。如果种子档案也是这两个数，
    「两边一致」就会在**没有接通**的情况下也成立。
    """
    prof = _profile(client, elder_headers)
    assert (prof["font_scale"], prof["speech_rate"]) != (1.0, 1.0), (
        "种子档案正好等于旧的写死默认值，这组判据分辨不出接没接通"
    )


# ---------------------------------------------------------------- 两个方向都要通


def test_saying_speak_slower_changes_what_the_app_reads_out(client, elder_headers) -> None:
    """老人说「说慢一点」，App 的朗读要真的慢下来。"""
    _say(client, elder_headers, "你说慢一点")
    prof = _profile(client, elder_headers)
    assert _app_speed(client) == pytest.approx(prof["speech_rate"]), (
        "它答应了「我说慢一点」，但合成语音仍按原速——老人听得出来"
    )


def test_the_slider_changes_what_the_adaptive_plan_uses(client, elder_headers) -> None:
    """在设置里调字号，自适应渲染计划要按新字号排版。"""
    client.put(f"{V1}/settings", json={"fontScale": 1.5})
    plan = client.post(
        "/v6/interaction/plan", headers=elder_headers,
        json={"elder_id": ELDER, "message": "帮我交水费"},
    )
    assert plan.status_code == 200, plan.text
    assert plan.json()["font_scale"] == pytest.approx(1.5), (
        "设置里字号已经调大，自适应计划还按旧字号裁版面"
    )


def test_the_slider_and_the_voice_command_continue_from_each_other(client, elder_headers) -> None:
    """拖过滑块之后再说「说慢一点」，要从滑块那个值继续往下。

    两份数据时的表现是：滑块设 0.7，档案还停在 0.88，
    于是这一句把 0.88 减成 0.80——**比刚才还快**。
    """
    client.put(f"{V1}/settings", json={"voiceSpeed": 0.7})
    _say(client, elder_headers, "你说慢一点")
    after = _profile(client, elder_headers)["speech_rate"]
    assert after < 0.7, f"从 0.7 说「慢一点」反而得到 {after}"
    assert _app_speed(client) == pytest.approx(after)


def test_a_fresh_install_shows_the_profile_default_not_a_second_one(client, elder_headers) -> None:
    """一次都没设置过时，App 显示的就是档案里的值。"""
    prof = _profile(client, elder_headers)
    got = client.get(f"{V1}/settings").json()
    assert got["fontScale"] == pytest.approx(prof["font_scale"])
    assert got["voiceSpeed"] == pytest.approx(prof["speech_rate"])
    assert got["saved"] is False, "没设置过却说已保存"


# ---------------------------------------------------------------- 边界与合并


@pytest.mark.parametrize(
    ("field", "sent", "expect"),
    [
        ("voiceSpeed", 9.9, 1.2),   # 档案上限
        ("voiceSpeed", 0.1, 0.6),   # 档案下限
        ("fontScale", 9.9, 1.6),
        ("fontScale", 0.2, 1.0),    # 适老界面不给比常规更小
    ],
)
def test_out_of_range_is_clamped_instead_of_rejected(client, field, sent, expect) -> None:
    """越界的值夹回档案能接受的范围，不能变成 422。

    老人只是把滑块拖到了头。写档案的模型有 `ge`/`le`，
    这一层若不先夹好，拖到头就会得到一个校验错误。
    """
    r = client.put(f"{V1}/settings", json={field: sent})
    assert r.status_code == 200, r.text
    assert r.json()[field] == pytest.approx(expect)


def test_changing_the_font_does_not_reset_the_rest_of_the_profile(client, elder_headers) -> None:
    """只改字号，档案里其它列要原样留着。

    `upsert_profile` 收的是**完整**的 update 模型：只填两个字段，
    verbosity、max_options、hearing_support 会被一起重置成默认值——
    而那三个是「我听不清」那条语音指令刚刚替老人调好的。
    """
    _say(client, elder_headers, "我听不清")
    before = _profile(client, elder_headers)
    assert before["hearing_support"] is True, "「我听不清」没有打开听力辅助，这条判据不成立"
    assert before["max_sentence_chars"] == 24

    client.put(f"{V1}/settings", json={"fontScale": 1.4})
    after = _profile(client, elder_headers)
    assert after["hearing_support"] is True, "调了个字号，把听力辅助关掉了"
    assert after["max_sentence_chars"] == before["max_sentence_chars"]
    assert after["verbosity"] == before["verbosity"]
    assert after["teach_back_high_risk"] == before["teach_back_high_risk"]


def test_the_speaker_choice_stays_out_of_the_shared_profile(client, elder_headers) -> None:
    """发音人只跟这一端有关，不该写进交互档案。

    档案是家庭共享的适老参数，会被家属那一侧看到、被自适应逻辑读到。
    「用哪个 TTS 音色」不属于那个语义。
    """
    client.put(f"{V1}/settings", json={"voiceSpeaker": 2})
    assert client.get(f"{V1}/settings").json()["voiceSpeaker"] == 2
    assert "voiceSpeaker" not in _profile(client, elder_headers)
    assert "speaker" not in _profile(client, elder_headers)


# ---------------------------------------------------------------- 老库还在用


def _poison_pref_row(client: TestClient, extra: dict) -> None:
    """往这位老人的偏好行里塞几个键，模拟另一个版本写下的行。"""
    client.put(f"{V1}/settings", json={"voiceSpeaker": 1})  # 先让偏好行存在
    db = client.app.state.db
    items = [i for i in db.list_memories("fam-demo", ELDER) if i.key == "elder_app_settings"]
    assert items, "偏好行没建起来，这条判据不成立"
    value = dict(items[0].value)
    value.update(extra)
    db.update_memory(items[0].model_copy(update={"value": value}))


def test_a_legacy_preference_row_does_not_shadow_the_profile(client, elder_headers) -> None:
    """老库里旧版写下的 fontScale 不能盖住档案。

    这不是假设：改造之前每个跑过设置页的库里都有这么一行。
    升级后如果仍然优先读它，老人会看到「说慢一点」再一次不生效——
    而且只在**老库**上复现，新装的一切正常。

    护住这件事的是**顺序**：档案的值在读完偏好行之后赋值，所以盖不住。
    """
    _poison_pref_row(client, {"fontScale": 1.0, "voiceSpeed": 1.0})
    _say(client, elder_headers, "你说慢一点")
    prof = _profile(client, elder_headers)
    got = client.get(f"{V1}/settings").json()
    assert got["voiceSpeed"] == pytest.approx(prof["speech_rate"]), "旧偏好行盖住了档案"
    assert got["voiceSpeaker"] == 1, "清理旧键时把本端仍在用的键一起丢了"


def test_an_unknown_key_in_the_preference_row_does_not_break_the_settings_page(client) -> None:
    """偏好行里出现这一版不认识的键时，设置页仍然打得开。

    `AppSettings` 是 `extra="forbid"` 的严格模型。不筛掉未知键的话，
    它会直接进返回字典，然后**整个 `GET /settings` 变成 500**——实测过。
    发生条件很普通：换了版本、或者两个版本轮流跑同一个库。
    表现是老人打开「设置」整页白，而别的页都正常。
    """
    _poison_pref_row(client, {"someKeyFromAnotherVersion": "x"})
    r = client.get(f"{V1}/settings")
    assert r.status_code == 200, f"偏好行里多一个未知键就打不开设置页了：{r.status_code}"
    assert "someKeyFromAnotherVersion" not in r.json()
    assert r.json()["voiceSpeaker"] == 1, "筛未知键时把本端仍在用的键一起筛掉了"
