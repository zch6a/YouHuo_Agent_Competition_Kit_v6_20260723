"""两个播种点必须给出**同一个**演示。

## 为什么需要这道门

这个项目有两条播种路径，一条都少不了：

    create_app 启动时      给固定的 `-demo` 家庭播（测试、脚本、`/stage` 用它）
    POST /v2/auth/visitor  给每一位访客播一个自己的家庭（浏览器走这条）

`api.py:478` 那段注释记着一次事故：「我第一版只改了 create_app，结果是库里
确实多了一行，而浏览器里 `/v2/tasks` 还是只有 1 条。两个播种点，改一个等于没改。」

同一件事又发生了一次，方向反了——`v4_store.seed_demo_content()` 只加在了
访客那一侧。实测：

                   elder-demo   访客沙箱
        身体数据          0          3
        心情回顾          0          7

后果不是「少一批数据」，是**同一句话在两个地方的真假不同**：拿脚本对
`elder-demo` 量，「照护页的身体和心情是空的」为真；在浏览器里看，为假。
这个项目里没有比「量到的和用户看到的不是一回事」更贵的一类错。

## 判据

不逐条列「该有哪些」——那是一张要人手维护的名单，而名单会漏。
判的是**两边相等**：任何一边多播或少播，都当场红。
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from youhuo.api import create_app

V1 = "/api/v1"

#: 「这一格有几条」。key 是接口，value 是要比的那个计数字段。
#:
#: `records` 不在里面：访客家庭比 `-demo` 多一条它自己创建时的审计，
#: 那个差是**对的**。这里比的是演示历史，不是审计流水。
COUNTS = {
    "/agenda": "count",
    "/reminders": "count",
    "/contacts": "count",
    "/medications": "plannedCount",
    "/appointments": "count",
    "/health-summary": "recorded",
    "/emotions/review?days=14": "count",
    "/memories": "count",
    "/routines": "count",
    "/notifications": "count",
    "/bills": "count",
}


@pytest.fixture()
def client(tmp_path, monkeypatch):
    # `attention` 才是演示时真正用的那一档，两条路径的差异也在这一档最全。
    monkeypatch.setenv("YOUHUO_DEMO_STATE", "attention")
    app = create_app(tmp_path / "seed.db", demo_mode=True)
    with TestClient(app) as c:
        yield c


def _counts(client: TestClient, token: str) -> dict[str, object]:
    head = {"Authorization": "Bearer " + token}
    out: dict[str, object] = {}
    for path, key in COUNTS.items():
        r = client.get(V1 + path, headers=head)
        assert r.status_code == 200, f"{path} → {r.status_code} {r.text[:120]}"
        out[path] = r.json().get(key)
    return out


def test_the_demo_family_and_a_visitor_see_the_same_demo(client: TestClient) -> None:
    demo = client.post("/v2/auth/demo", json={"actor_id": "elder-demo"})
    assert demo.status_code == 200, demo.text
    visitor = client.post("/v2/auth/visitor", json={})
    assert visitor.status_code == 200, visitor.text

    a = _counts(client, demo.json()["access_token"])
    b = _counts(client, visitor.json()["elder_token"])

    diff = {k: (a[k], b[k]) for k in COUNTS if a[k] != b[k]}
    assert not diff, (
        "这些格子在两条播种路径下不一样（左 = `-demo`，右 = 访客沙箱）：\n  "
        + "\n  ".join(f"{k:<28} {x} ≠ {y}" for k, (x, y) in diff.items())
        + "\n  两个播种点，改一个等于没改：脚本对 `-demo` 量出来的结论，"
          "在浏览器里是另一回事。")


def test_the_demo_is_not_simply_empty(client: TestClient) -> None:
    """两边都空也能让上面那条绿。所以要有东西。

    这一条不是凑数：`seed_baseline_history=False` 时这一整批全是 0，
    而「两个 0 相等」正是这道门最容易被满足的方式。
    """
    demo = client.post("/v2/auth/demo", json={"actor_id": "elder-demo"})
    got = _counts(client, demo.json()["access_token"])
    filled = {k: v for k, v in got.items() if isinstance(v, int) and v > 0}
    assert len(filled) >= 7, (
        f"`attention` 演示态下只有 {len(filled)} 格有数据：{got}\n"
        "  这一档本该是最全的那一档；只有几格有东西，说明播种漏了。")


def test_health_and_mood_are_seeded_on_both_paths(client: TestClient) -> None:
    """身体与心情单独钉一次——它们就是这次漏掉的那两格。

    上面那条比的是「两边相等」，而两边同时变空它照样绿。这两格是照护中心
    七屏里的两屏，空了就是两块白板。
    """
    for who, token in (
        ("elder-demo",
         client.post("/v2/auth/demo", json={"actor_id": "elder-demo"}).json()["access_token"]),
        ("访客沙箱",
         client.post("/v2/auth/visitor", json={}).json()["elder_token"]),
    ):
        head = {"Authorization": "Bearer " + token}
        body = client.get(f"{V1}/health-summary", headers=head).json()
        mood = client.get(f"{V1}/emotions/review?days=14", headers=head).json()
        assert body["recorded"] > 0, f"{who} 的身体记录是空的：{body}"
        assert mood["count"] > 0, f"{who} 的心情记录是空的：{mood}"
