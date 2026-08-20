"""设计三这一版，该有的能力真的有——而且和设计一二**读同一批字段**。

## 这一轮补的是什么

把两边各自打出去的端点求差集，缺口是具体的，不是「代码量少」这种印象：

    老人端三 缺   /api/v1/daily-report          我今天怎么样
                  /api/v1/emotions/review        这两周的心情
                  /api/v1/privacy/data           优活替我记了些什么
                  /api/v1/privacy/erase{,/preview}  两步删除
                  /v6/tasks/{id}/glass-box       玻璃盒（三项核心创新之一）
    家人端三 缺   /api/v1/medications/{id}/taken|skipped   记一次已吃 / 这次没吃
                  /api/v1/health/events (POST)   记一次身体数据

前四条是这个产品对隐私那几句承诺的兑现处；玻璃盒是「她说的那件事到底要动
什么」的唯一出口；后两条是余量预警和身体趋势的**数据来源**——不记，
「还够吃几天」永远不动。

## 为什么判据要落在字段名上

这个项目栽过两次：`family3.js` 第一版把日报字段写成 `today_word`（真名
`headline`），把用药字段写成 `p.name` / `p.dosage` / `p.times`（真名
`display_name` / `dose_text` / `times_local`）。**两次都是接口 200、页面有字、
字还很像**——落到兜底文案上，截图和点击遍历都看不出来。

所以这里逐个字段去问后端的响应模型：读一个不存在的字段拿到 undefined，
而 undefined 配一句兜底就是一段假数据。
"""
from __future__ import annotations

import io
import re
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

STATIC = Path(__file__).resolve().parents[1] / "static"


@pytest.fixture()
def client(tmp_path):
    from youhuo.api import create_app

    app = create_app(tmp_path / "d3.db", demo_mode=True, seed_baseline_history=True)
    with TestClient(app) as c:
        yield c


def _elder(client: TestClient) -> dict[str, str]:
    r = client.post("/v2/auth/demo", json={"actor_id": "elder-demo"})
    assert r.status_code == 200, r.text
    return {"Authorization": "Bearer " + r.json()["access_token"]}


def _src(name: str) -> str:
    """读一份接线，**先剥注释**——注释里逐字写着这些字段名和端点。"""
    text = io.open(STATIC / name, encoding="utf-8").read()
    text = re.sub(r"/\*.*?\*/", " ", text, flags=re.S)
    return re.sub(r"^\s*//.*$", " ", text, flags=re.M)


# ---- ① 四条数据入口：端点在、控件在、字段名对 --------------------------------

@pytest.mark.parametrize("path", [
    "/api/v1/daily-report",
    "/api/v1/emotions/review?days=14",
    "/api/v1/privacy/data",
    "/api/v1/privacy/erase/preview",
    # 玻璃盒那条路径中间夹着模板变量（`/v6/tasks/${…}/glass-box`），
    # 所以只对前缀。动作名由 `test_the_glass_box_uses_the_same_renderer…` 单独钉。
    "/v6/tasks/",
])
def test_the_elder_wiring_calls_it(path: str) -> None:
    js = _src("elder3.js")
    assert path.split("?")[0] in js, (
        f"`elder3.js` 里找不到 {path}——设计三这一端还是缺这条能力")


@pytest.mark.parametrize("control,label", [
    ("e3DayReport", "我今天怎么样"),
    ("e3MoodReview", "看看这两周的心情"),
    ("e3MyData", "优活替我记了些什么"),
    ("e3EraseStart", "删掉优活记下的这些"),
])
def test_the_control_exists_and_is_bound(control: str, label: str) -> None:
    """光有端点不算通——屏幕上得有一个她能按的东西。"""
    html = io.open(STATIC / "elder-v3.html", encoding="utf-8").read()
    assert f'id="{control}"' in html, f"`elder-v3.html` 里没有 #{control}"
    assert label in html, f"#{control} 上没有「{label}」这句话"
    assert f"'#{control}'" in _src("elder3.js"), (
        f"#{control} 在 HTML 里但 `elder3.js` 不绑它——那是一个按下去没反应的按钮")


def test_the_day_report_fields_it_reads_really_exist(client: TestClient) -> None:
    """日报那一段读的字段，响应里都要有。"""
    from youhuo.app_schemas import AppDailyReport

    body = client.get("/api/v1/daily-report", headers=_elder(client))
    assert body.status_code == 200, body.text
    known = set(AppDailyReport.model_fields)
    js = _src("elder3.js")
    block = re.search(r"async function showDayReport\(\).*?\n  \}", js, re.S)
    assert block, "elder3.js 里找不到 showDayReport"
    read = set(re.findall(r"\bdata\.(\w+)", block.group(0)))
    assert read, "一个 `data.` 都没数到——这条判据在空转"
    assert not (read - known), (
        f"读了 `AppDailyReport` 上没有的字段：{sorted(read - known)}\n"
        f"  它有的是：{sorted(known)}")
    # 通道里那四个键也核一遍：屏幕上一整列都靠它们。
    chan = (body.json().get("channels") or [{}])[0]
    for key in ("name", "today", "usual", "word"):
        assert key in chan, f"通道里没有 `{key}`，而接线在读它"


def test_the_mood_fields_it_reads_really_exist(client: TestClient) -> None:
    body = client.get("/api/v1/emotions/review?days=14", headers=_elder(client))
    assert body.status_code == 200, body.text
    known = set(body.json())
    js = _src("elder3.js")
    block = re.search(r"async function showMoodReview\(\).*?\n  \}", js, re.S)
    assert block, "elder3.js 里找不到 showMoodReview"
    read = set(re.findall(r"\bdata\.(\w+)", block.group(0)))
    assert read, "一个 `data.` 都没数到——这条判据在空转"
    assert not (read - known), (
        f"心情那一段读了响应里没有的字段：{sorted(read - known)}\n"
        f"  响应里有的是：{sorted(known)}")
    #: 「聊天不会记在这里」那句承诺必须跟着显示——这一块正是最容易让人
    #: 怀疑那句话的地方。
    #:
    #: 判的是**分支条件**本身，不是「文件里提到过这个字段」。变异测过：
    #: 把 `if (data.privacyNote)` 改成 `if (false)`，只查提及的那一版**没有变红**
    #: ——字段名在分支体里还出现着（`note.textContent = data.privacyNote`）。
    #: 「提到一个字段」和「真的把它印出来」是两件事。
    assert re.search(r"if\s*\(\s*data\.privacyNote\s*\)", block.group(0)), (
        "隐私那句承诺不是由 `data.privacyNote` 决定的——它要么没印，要么被写死了")


def test_the_erase_preview_fields_it_reads_really_exist(client: TestClient) -> None:
    """两步删除。`confirmToken` 是驼峰，写成下划线后端读不到会走 400。"""
    body = client.post("/api/v1/privacy/erase/preview",
                       headers=_elder(client), json={})
    assert body.status_code == 200, body.text
    known = set(body.json())
    js = _src("elder3.js")
    block = re.search(r"async function startErase\(\).*?\n  \}", js, re.S)
    assert block, "elder3.js 里找不到 startErase"
    read = set(re.findall(r"\bpreview\.(\w+)", block.group(0)))
    assert read, "一个 `preview.` 都没数到——这条判据在空转"
    assert not (read - known), (
        f"删除预览读了响应里没有的字段：{sorted(read - known)}\n"
        f"  响应里有的是：{sorted(known)}")
    assert "confirmToken" in read, "没把 confirmToken 带回去，确认那一步会 400"


def test_deleting_is_two_steps_and_the_second_button_does_not_exist_yet() -> None:
    """第二个按钮**一开始不在 DOM 里**，不是 disabled 也不是 hidden。

    一个看得见的「确认删除」会让人以为「点两下就没了」；它在看到清单之前
    根本不该存在。设计一二是这个规矩，设计三不许自己另立一套。
    """
    html = io.open(STATIC / "elder-v3.html", encoding="utf-8").read()
    assert "确认删掉" not in html, (
        "「确认删掉」写死在 HTML 里了——那一步的按钮必须是看到清单之后才长出来的")
    js = _src("elder3.js")
    block = re.search(r"async function startErase\(\).*?\n  \}", js, re.S)
    assert "createElement('button')" in block.group(0), (
        "startErase 里没有动态建按钮——第二步不该预先存在")
    assert "先不删" in block.group(0), "只给了确认，没给「先不删」"


# ---- ② 玻璃盒 ----------------------------------------------------------------

def test_the_glass_box_uses_the_same_renderer_not_a_second_one() -> None:
    """设计三**不许**自己画一张玻璃盒。

    同一张卡两套画法，正是这个项目栽过的那件事（字号语速和 SOS 各有两套实现，
    两边各自往返都绿，跨子系统才红）。所以这里要求它去 import
    `glassbox.js` 那一个渲染函数。
    """
    js = _src("elder3.js")
    assert "glass-box" in js, "`elder3.js` 不调 `/v6/tasks/{id}/glass-box`"
    assert "import('/static/glassbox.js')" in js, (
        "没有复用 `glassbox.js` 的渲染函数——设计三在自己画一张卡")
    assert "renderGlassBox" in js
    #: 没有任务就要把上一张收掉，否则她说完下一句还看着上一件事的卡。
    assert re.search(r"task_id\)\s*\{[^}]*hidden = true", js, re.S), (
        "没有任务时没把上一张卡收掉")


def test_the_glass_box_script_is_precached() -> None:
    """动态 `import()` 的东西也要进 service worker 清单。

    漏掉它不是「少张卡」：离线或弱网时 `import()` 直接 reject，
    走进 catch 把卡收掉——**屏幕上什么都不会少，只是那张卡再也不出现**。
    """
    #: 必须**先剥注释**。`sw.js` 的版本说明里逐字写着
    #: `import('/static/glassbox.js')`——不剥的话这条判据会被它自己的
    #: 说明文档回答成「在清单里」。变异测过：把清单里那一行删掉，
    #: 不剥注释的那一版**没有变红**。这个项目已经有三条断言栽在这上面。
    #: **只剥行注释**。`/\*.*?\*/` 那一版在这个文件上会把从头到 `isApi()`
    #: 的一整段吃掉（里面有正则字面量和 URL，非贪婪匹配照样跨过去），
    #: 于是清单本身被删了，判据红在一个假的理由上。
    #: 版本说明用的是 `//:`，剥行注释就够。
    sw = io.open(STATIC / "sw.js", encoding="utf-8").read()
    sw = re.sub(r"^\s*//.*$", " ", sw, flags=re.M)
    assert "'/static/glassbox.js'" in sw, "`glassbox.js` 不在预缓存清单里"


# ---- ③ 家人端三：记一次已吃 / 记一次身体数据 ----------------------------------

@pytest.mark.parametrize("path", [
    "/api/v1/medications/",
    "/api/v1/health/events",
])
def test_the_family_wiring_calls_it(path: str) -> None:
    assert path in _src("family3.js"), (
        f"`family3.js` 里找不到 {path}——家人端三还是缺这条能力")


def test_only_active_plans_get_a_dose_button() -> None:
    """待老人确认的那些不给「记一次已吃」。

    给它一个记录按钮，等于替她把「要不要开始吃」那一步跳过去——
    而那一步是这条流程存在的全部理由。
    """
    js = _src("family3.js")
    block = re.search(r"function fillDoseActions\(plans\).*?\n  \}", js, re.S)
    assert block, "family3.js 里找不到 fillDoseActions"
    assert "active !== false" in block.group(0), (
        "没有滤掉未生效的计划——待确认的药也会长出「记一次已吃」")


def test_recording_a_dose_really_moves_the_stock(client: TestClient) -> None:
    """记一次已吃必须真的扣库存。不扣的话「还够吃几天」永远不动。"""
    headers = _elder(client)
    made = client.post("/v4/medications", headers=headers, json={
        "elder_id": "elder-demo", "display_name": "判据钙片",
        "normalized_name": "判据钙片", "dose_text": "一次一片",
        "times_local": ["08:30"], "start_date": "2026-08-20",
        "stock_units": 30, "units_per_dose": 1,
    })
    assert made.status_code == 200, made.text
    plan_id = made.json()["id"]

    before = client.get("/api/v1/medications", headers=headers).json()
    took = client.post(f"/api/v1/medications/{plan_id}/taken",
                       headers=headers, json={})
    assert took.status_code == 200, took.text
    after = client.get("/api/v1/medications", headers=headers).json()

    def stock(payload):
        for p in payload.get("plans", []):
            if p["id"] == plan_id:
                return p["stockUnits"]
        return None

    assert stock(before) is not None, "刚建的计划不在清单里——这条判据在空转"
    assert stock(after) < stock(before), (
        f"记了一次却没扣库存：{stock(before)} → {stock(after)}")


def test_skipping_a_dose_does_not_move_the_stock(client: TestClient) -> None:
    """「这次没吃」**不扣**库存——药还在。两个动作不许做同一件事。"""
    headers = _elder(client)
    made = client.post("/v4/medications", headers=headers, json={
        "elder_id": "elder-demo", "display_name": "判据维D",
        "normalized_name": "判据维D", "dose_text": "一次两粒",
        "times_local": ["20:00"], "start_date": "2026-08-20",
        "stock_units": 30, "units_per_dose": 2,
    })
    plan_id = made.json()["id"]

    def stock():
        for p in client.get("/api/v1/medications", headers=headers).json()["plans"]:
            if p["id"] == plan_id:
                return p["stockUnits"]
        return None

    before = stock()
    r = client.post(f"/api/v1/medications/{plan_id}/skipped", headers=headers, json={})
    assert r.status_code == 200, r.text
    assert stock() == before, f"「没吃」把库存也扣了：{before} → {stock()}"


# ---- ④ 措辞适配 / 一件事的经过 / 优活给家人的消息 --------------------------------

def test_the_agent_message_goes_through_the_interaction_plan() -> None:
    """每一句 agent 的话都要过一遍 `/v6/interaction/plan`。

    由后端按风险等级、最近重试次数、这件事可不可逆，决定屏幕上写什么、
    念出来念什么、用多快的语速。设计三此前一次都没调过——高风险那句话
    和闲聊用同一个语速、同一种措辞。
    """
    js = _src("elder3.js")
    assert "/v6/interaction/plan" in js, "`elder3.js` 不调交互计划"
    block = re.search(r"async function send\(text\).*?\n  \}", js, re.S)
    assert block, "elder3.js 里找不到 send()"
    body = block.group(0)
    assert "adapt(" in body, "`send()` 没有过这一层加工"
    for field in ("visual_text", "speak_text"):
        assert field in body, f"没有用 `{field}`——加工完了不用等于没加工"
    #: 只影响这一句。改掉她存的语速设置，等于一次高风险对话之后
    #: 整个应用都慢下来了，而她从没改过那个设置。
    assert re.search(r"speechRate = was", body), (
        "临时语速没有还回去——一次高风险对话会把她存的设置改掉")


def test_only_a_real_task_gets_the_detail_action() -> None:
    """「看看这件事的经过」只许出现在**真的是一件事**的记录行上。

    实测：`/api/v1/records` 的 `entityId` 对「登录了优活」这类事件给的是
    **一个人**（`elder-vc9b…`），不是任务。四行里三行是这样，而它们照样长出了
    这个动作，点下去得到「没有找到这件事的记录。」——一个走到死胡同的动作。

    设计一二没有这个问题：它读的 `/v2/elder/activity` 由后端把非任务事件的
    `about_id` 置空了。这里的修法是拿 `/v2/tasks` 的 id 集合对一遍——
    **按查得到，不按前缀猜**。前缀判断在换一种 id 形状之后会安静地失效。
    """
    js = _src("elder3.js")
    block = re.search(r"async function loadRecords\(\).*?\n  \}", js, re.S)
    assert block, "elder3.js 里找不到 loadRecords"
    body = block.group(0)
    assert "/v2/tasks" in body, "没有去问哪些主体号真的是任务"
    assert "taskIds.has(" in body, (
        "没有用任务 id 集合过滤——非任务的行会长出一个走到死胡同的动作")
    assert not re.search(r"startsWith\(\s*['\"]task-", body), (
        "在用 id 前缀猜——换一种 id 形状之后这条判断会安静地失效")


def test_the_task_detail_uses_the_same_renderer() -> None:
    js = _src("elder3.js")
    assert "import('/static/task-detail.js')" in js, (
        "设计三在自己画一份经过——同一件事两套说法")
    assert "taskDetailViewModel" in js and "renderTaskDetail" in js


def test_the_task_detail_script_is_precached() -> None:
    sw = io.open(STATIC / "sw.js", encoding="utf-8").read()
    sw = re.sub(r"^\s*//.*$", " ", sw, flags=re.M)
    assert "'/static/task-detail.js'" in sw, "`task-detail.js` 不在预缓存清单里"


def test_the_family_notice_titles_do_not_fork_from_design_one() -> None:
    """通知标题表两处必须一致。

    同一个事件码在两个壳里译成两句话，是这个项目栽过的那件事
    （字号语速和 SOS 各有两套实现，两边各自往返都绿，跨子系统才红）。
    """
    def table(name: str) -> dict[str, str]:
        js = _src(name)
        block = re.search(r"NOTICE_TITLE = \{(.*?)\}", js, re.S)
        assert block, f"{name} 里找不到 NOTICE_TITLE"
        return dict(re.findall(r"(\w+):\s*'([^']+)'", block.group(1)))

    one, three = table("family.js"), table("family3.js")
    assert one, "家人端一那张表是空的——这条判据在空转"
    assert three == one, (
        "两个壳的通知标题对不上：\n"
        f"  只在家人端一：{sorted(set(one) - set(three))}\n"
        f"  只在家人端三：{sorted(set(three) - set(one))}\n"
        f"  同键不同译：{sorted(k for k in set(one) & set(three) if one[k] != three[k])}")


def test_the_notice_fallback_is_not_the_raw_event_code() -> None:
    """兜底成枚举名，等于这层翻译在遇到没登记过的类型时自动失效——
    而那正是它该起作用的时候。界面上也不许出现英文枚举值。"""
    js = _src("family3.js")
    assert re.search(r"NOTICE_TITLE\[n\.event_type\]\s*\|\|\s*'[^']*[一-鿿]",
                     js), "通知标题的兜底不是一句中文"
    assert not re.search(r"NOTICE_TITLE\[n\.event_type\]\s*\|\|\s*n\.event_type", js), (
        "兜底直接印原始事件码了")


def test_the_family_notifications_endpoint_answers(client: TestClient) -> None:
    r = client.post("/v2/auth/demo", json={"actor_id": "daughter-demo"})
    token = {"Authorization": "Bearer " + r.json()["access_token"]}
    got = client.get("/v2/notifications?limit=50", headers=token)
    assert got.status_code == 200, got.text


def test_recording_a_body_reading_keeps_it_a_string(client: TestClient) -> None:
    """血压是「128/82」，不是一个数。拆成两个数字字段就记不了它。"""
    headers = _elder(client)
    r = client.post("/api/v1/health/events", headers=headers,
                    json={"type": "血压", "value": "128/82"})
    assert r.status_code == 200, r.text
    listed = client.get("/v4/health/events/elder-demo", headers=headers)
    assert listed.status_code == 200, listed.text
    blob = listed.text
    assert "128/82" in blob, "记进去的读数在列表里找不到"
