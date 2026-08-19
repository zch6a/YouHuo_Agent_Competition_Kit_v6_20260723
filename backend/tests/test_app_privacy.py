"""`/api/v1/privacy/*` —— 老人自己导出、自己删除。

## 这一层此前没有入口

`POST /v5/privacy/export` 和 `POST /v5/privacy/erase` 从 v5 起就在，而老人端
一个按钮都没有：他既拿不到自己的数据，也删不掉自己的数据。补的是入口，
不是第二套删除逻辑——真正动手的仍然是 `V5FeatureStore.privacy_erase`。

## 这份文件守的四条性质

1. **导出是读。** 它不许写审计、不许改任何一笔事务。这个项目为这条付过代价：
   `trust.js` 的凭证页曾经在渲染时真的发起一笔缴费。
2. **一个 POST 抹不掉数据。** 删除必须先看一眼、再确认，而且确认的是**您看到的
   那一份**——中间数据变了，令牌就对不上。
3. **回执要说还剩什么。** 只说「已删除」是在给一个做不到的承诺（审计链删不掉）。
4. **界面上不出现 `emotion_events`。** 类别名一律中文。

## 数据从哪儿来

`create_app(..., seed_baseline_history=True)` **不种**情绪/身体/亲友三张表——
那三张只在 `/v2/auth/visitor` 那条路上种（`v4_store.seed_demo_content`）。
所以这里走访客沙箱：一户新家庭，七天心情、若干身体记录、两位亲友，
而且和别的测试完全隔离（删掉的东西不会影响任何人）。
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from youhuo.api import create_app
from youhuo.v5_models import PrivacyCategory

V1 = "/api/v1"


@pytest.fixture()
def app(tmp_path):
    return create_app(tmp_path / "app_privacy.db", demo_mode=True, seed_baseline_history=True)


@pytest.fixture()
def client(app):
    with TestClient(app) as c:
        yield c


@pytest.fixture()
def sandbox(client: TestClient) -> dict[str, str]:
    """一户新家庭，情绪/身体/亲友三张表都有内容。"""
    r = client.post("/v2/auth/visitor")
    assert r.status_code == 200, r.text
    return r.json()


@pytest.fixture()
def elder(sandbox) -> dict[str, str]:
    return {"Authorization": "Bearer " + sandbox["elder_token"]}


@pytest.fixture()
def family(sandbox) -> dict[str, str]:
    return {"Authorization": "Bearer " + sandbox["family_token"]}


def _export(client: TestClient, headers) -> dict:
    r = client.get(f"{V1}/privacy/data", headers=headers)
    assert r.status_code == 200, r.text
    return r.json()


def _audit_total(client: TestClient, headers) -> int:
    r = client.get(f"{V1}/records", params={"limit": 1}, headers=headers)
    assert r.status_code == 200, r.text
    return r.json()["total"]


def _tasks(client: TestClient, headers) -> str:
    r = client.get("/v2/tasks", headers=headers)
    assert r.status_code == 200, r.text
    return r.text


# ---- 自证：这套判据真的看得见东西 -------------------------------------------


def test_the_sandbox_actually_has_something_to_delete(client, elder) -> None:
    """先证明这份夹具读到了数据。

    一户空家庭会让下面每一条「删完之后少了 N 条」轻松通过，而通过的原因是
    根本没有数据。这个项目为「空态掩盖缺陷」红过不止一次。
    """
    got = _export(client, elder)
    assert got["total"] >= 3, f"沙箱里只有 {got['total']} 条，下面的断言会是空转的：{got['buckets']}"
    assert [b for b in got["buckets"] if b["count"]], "没有任何一类有内容"


# ---- 类别翻译 ----------------------------------------------------------------


def test_every_category_the_backend_can_delete_has_a_chinese_name(client, elder) -> None:
    """`PrivacyCategory` 里每一类都要有中文说法。

    漏掉一类的后果不是报错：它在请求里会被判成「不认识」而 400，可它在 `/v5`
    那一侧是真能删的——于是老人端永远删不掉那一类，而屏幕上看起来一切正常。
    """
    names = {b["name"] for b in _export(client, elder)["buckets"]}
    assert len(names) == len(list(PrivacyCategory)), (
        f"后端有 {len(list(PrivacyCategory))} 类可删数据，这一层只给出 {len(names)} 个名字：{sorted(names)}"
    )


def test_no_english_category_key_reaches_the_screen(client, elder) -> None:
    """界面上不许出现 `emotion_events` 这种键。

    只扫要显示的那几处（类别名、说明、文案）。`records` 里是**存着的数据本身**，
    列名是数据的一部分，不是界面文案——把它一起扫会逼着这条判据被放宽。
    """
    got = _export(client, elder)
    shown = " ".join(
        [b["name"] for b in got["buckets"]] + [got["note"], got["message"]]
    )
    leaked = [c.value for c in PrivacyCategory if c.value in shown]
    assert not leaked, f"这些内部键漏到界面文案上了：{leaked}"


# ---- ① 导出是读 --------------------------------------------------------------


def test_exporting_my_data_writes_nothing(client, elder) -> None:
    """**P0：渲染一张回执不许改动任何东西。**

    导出是老人在自己屏幕上看一眼自己的东西。它不许写审计、不许建事务、
    不许推进任何一笔在飞的事。
    """
    audit_before, tasks_before = _audit_total(client, elder), _tasks(client, elder)
    first = _export(client, elder)
    second = _export(client, elder)
    assert _audit_total(client, elder) == audit_before, "导出往审计链里写了东西"
    assert _tasks(client, elder) == tasks_before, "导出改动了事务"
    # 同一份数据导两次，回执摘要必须一样——不一样说明中间有东西被改了。
    assert first["digest"] == second["digest"], "两次导出的摘要不同，说明导出本身在改数据"
    assert first["total"] == second["total"]


def test_the_export_actually_hands_back_the_rows(client, elder) -> None:
    """一份不含数据的「导出」不是导出。"""
    got = _export(client, elder)
    assert got["total"] == sum(b["count"] for b in got["buckets"])
    rows = sum(len(v) for v in got["records"].values())
    assert rows == got["total"], f"说有 {got['total']} 条，实际给了 {rows} 条"
    # 键是中文，和 buckets 对得上。
    assert set(got["records"]) == {b["name"] for b in got["buckets"]}
    assert got["digest"] and got["note"] and got["message"]


# ---- ② 一个 POST 抹不掉数据 --------------------------------------------------


def test_a_bare_post_cannot_erase_anything(client, elder) -> None:
    """**没有确认令牌就不许删。** 这是这份文件里最重要的一条。"""
    before = _export(client, elder)["total"]
    r = client.post(f"{V1}/privacy/erase", json={}, headers=elder)
    assert r.status_code == 400, f"一个裸 POST 就被放行了：{r.status_code} {r.text[:200]}"
    assert _export(client, elder)["total"] == before, "被拒绝的请求还是删掉了数据"


def test_a_made_up_token_cannot_erase_anything(client, elder) -> None:
    before = _export(client, elder)["total"]
    r = client.post(
        f"{V1}/privacy/erase", json={"confirmToken": "0" * 32}, headers=elder
    )
    assert r.status_code == 409, r.text
    assert _export(client, elder)["total"] == before


def test_the_preview_deletes_nothing(client, elder) -> None:
    before = _export(client, elder)["total"]
    r = client.post(f"{V1}/privacy/erase/preview", json={}, headers=elder)
    assert r.status_code == 200, r.text
    preview = r.json()
    assert preview["total"] == before
    assert preview["confirmToken"]
    assert "还没有删" in preview["message"]
    assert _export(client, elder)["total"] == before, "「先看一眼」把数据删了"


def test_confirming_what_you_were_shown_deletes_exactly_that(client, elder) -> None:
    preview = client.post(
        f"{V1}/privacy/erase/preview", json={"categories": ["心情记录"]}, headers=elder
    ).json()
    assert preview["total"] > 0, f"这一类本来就是空的，下面的断言是空转的：{preview}"
    before = _export(client, elder)["total"]

    r = client.post(
        f"{V1}/privacy/erase",
        json={"categories": ["心情记录"], "confirmToken": preview["confirmToken"]},
        headers=elder,
    )
    assert r.status_code == 200, r.text
    done = r.json()
    assert done["total"] == preview["total"], "删掉的条数和预览说的不一样"
    after = _export(client, elder)
    assert after["total"] == before - preview["total"]
    # 真的没了，不是只在回执上说没了。
    assert {b["name"]: b["count"] for b in after["buckets"]}["心情记录"] == 0


def test_a_token_from_a_stale_preview_is_refused(client, elder, sandbox) -> None:
    """看完预览之后数据变了，旧令牌就不作数。

    这才是令牌真正要防的那件事：回执上写着「删掉 7 条」，实际删了 9 条，
    而两边都不会报错。
    """
    preview = client.post(
        f"{V1}/privacy/erase/preview", json={"categories": ["心情记录"]}, headers=elder
    ).json()

    added = client.post(
        "/v4/emotions/analyze",
        json={"elder_id": sandbox["elder_id"], "text": "今天有点想孩子了", "store_event": True},
        headers=elder,
    )
    assert added.status_code == 200, added.text
    before = _export(client, elder)["total"]

    r = client.post(
        f"{V1}/privacy/erase",
        json={"categories": ["心情记录"], "confirmToken": preview["confirmToken"]},
        headers=elder,
    )
    assert r.status_code == 409, f"过期的令牌被放行了：{r.status_code} {r.text[:200]}"
    assert "再看一遍" in r.json()["detail"]
    assert _export(client, elder)["total"] == before, "被拒绝的确认还是删掉了数据"


def test_an_unknown_category_is_refused_instead_of_quietly_ignored(client, elder) -> None:
    """拼错的类别不许被静默忽略——那等于按用户没要求的范围去删。"""
    r = client.post(
        f"{V1}/privacy/erase/preview", json={"categories": ["心情纪录"]}, headers=elder
    )
    assert r.status_code == 400, r.text
    assert "可以选" in r.json()["detail"]


# ---- ③ 回执要说还剩什么 -------------------------------------------------------


def test_the_receipt_says_what_was_kept_not_only_what_went(client, elder) -> None:
    preview = client.post(
        f"{V1}/privacy/erase/preview", json={"categories": ["身体数据"]}, headers=elder
    ).json()
    assert preview["total"] > 0, f"这一类本来就是空的：{preview}"
    assert preview["preserved"], "预览没有说哪些东西删不掉"

    done = client.post(
        f"{V1}/privacy/erase",
        json={"categories": ["身体数据"], "confirmToken": preview["confirmToken"]},
        headers=elder,
    ).json()
    assert done["preserved"], "回执没有说还剩什么"
    for kept in done["preserved"]:
        assert kept in done["message"], f"回执文案里没提到保留的「{kept}」"
    assert "身体数据" in done["message"], "回执文案没说删掉的是哪一类"


def test_erasing_nothing_is_a_conflict_not_a_green_tick(client, elder) -> None:
    """「本来就没有可删的」不是一次成功的删除。

    回 200 的话界面会画一个绿勾，而老人会以为自己刚刚抹掉了什么。
    """
    preview = client.post(
        f"{V1}/privacy/erase/preview", json={"categories": ["心情记录"]}, headers=elder
    ).json()
    client.post(
        f"{V1}/privacy/erase",
        json={"categories": ["心情记录"], "confirmToken": preview["confirmToken"]},
        headers=elder,
    )
    again = client.post(
        f"{V1}/privacy/erase/preview", json={"categories": ["心情记录"]}, headers=elder
    ).json()
    assert again["total"] == 0
    r = client.post(
        f"{V1}/privacy/erase",
        json={"categories": ["心情记录"], "confirmToken": again["confirmToken"]},
        headers=elder,
    )
    assert r.status_code == 409, f"删了个空也报成功：{r.status_code} {r.text[:200]}"


def test_a_real_erase_leaves_a_named_trace_in_the_records_page(client, elder) -> None:
    """删除是不可逆的，记录页上必须留名，而且不能是兜底的「办了一件事」。"""
    preview = client.post(
        f"{V1}/privacy/erase/preview", json={"categories": ["亲友档案"]}, headers=elder
    ).json()
    assert preview["total"] > 0, f"这一类本来就是空的：{preview}"
    before = _audit_total(client, elder)
    client.post(
        f"{V1}/privacy/erase",
        json={"categories": ["亲友档案"], "confirmToken": preview["confirmToken"]},
        headers=elder,
    )
    assert _audit_total(client, elder) == before + 1, "删除没有留下审计"
    titles = [i["title"] for i in client.get(f"{V1}/records", headers=elder).json()["items"]]
    assert "删掉了一批个人数据" in titles, f"记录页上没有这一条，只有：{titles[:8]}"


# ---- ④ 只有本人 --------------------------------------------------------------


@pytest.mark.parametrize(
    "method,path,body",
    [
        ("get", f"{V1}/privacy/data", None),
        ("post", f"{V1}/privacy/erase/preview", {}),
        ("post", f"{V1}/privacy/erase", {"confirmToken": "x"}),
    ],
)
def test_the_family_cannot_export_or_erase_the_elders_data(
    client, family, method, path, body
) -> None:
    """这一层别的端点允许家人拿令牌进来看老人的数据。这三个不行。

    不是这一层立的规矩：`v5_store.privacy_erase` 里写着「只有老人本人可以执行
    个人数据删除」。在这里先拦一道，是为了给一句人话而不是一个 500。
    """
    r = client.request(method.upper(), path, json=body, headers=family)
    assert r.status_code == 403, f"{method.upper()} {path} 放行了家人：{r.status_code}"
    assert "本人" in r.json()["detail"]
