"""设计三（网页端 `/elder3` `/family3`）：每一条都对应一个实测到的缺陷。

## 这一版是**接进来的第三方交付包**，情况和设计一二不同

设计二和设计一共用 `elder.js` / `family.js`——一份逻辑两张皮。设计三不行：
它是另一套 DOM、另一套动画体系，接线只能另写（`elder3.js` / `family3.js`）。
「另写一份」正是这个项目栽过的那件事（字号语速和 SOS 各有两套实现，
两边各自往返都绿，跨子系统才红）。所以下面前两条钉的就是**不许分叉**。

## 交付包里有四个「只演不做」的控件

    #savePref   显示「✓ 已保存」1.5 秒，一个字节都不存
    #voiceOrb   把说明改成「正在听，请慢慢说…」2.1 秒，什么都没听
    states 表   点「待办」把主舞台改成「燃气费…¥86.50」这类编造内容
    STORE       今日待办是纯前端内存数组，加删都不出浏览器

光加自己的监听不够：两个都会跑，于是**我这边失败的时候屏幕上照样先弹出
「已保存」**。所以要 `cloneNode` 把它们的匿名监听整个摘掉。
"""
from __future__ import annotations

import io
import re
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

STATIC = Path(__file__).resolve().parents[1] / "static"
V1 = "/api/v1"


@pytest.fixture()
def client(tmp_path):
    from youhuo.api import create_app

    app = create_app(tmp_path / "v3.db", demo_mode=True, seed_baseline_history=True)
    with TestClient(app) as c:
        yield c


def _elder(client: TestClient) -> dict[str, str]:
    """`/v2/*` 要 Bearer 令牌；`/api/v1` 在演示模式下可以不带。

    浏览器那一侧两条路都带（`common.js` 统一加），所以这里也得带——
    不带的话测的是一条真实前端从不会走的路径。
    """
    r = client.post("/v2/auth/demo", json={"actor_id": "elder-demo"})
    assert r.status_code == 200, r.text
    return {"Authorization": "Bearer " + r.json()["access_token"]}


def _src(name: str) -> str:
    """读一份脚本，**先剥注释**。

    这两个文件的注释里逐字写着 `today_word`、`✓ 已保存`、`page-bloom` 这些
    字样（那是在解释缺陷长什么样）。不剥的话，下面每一条判据都会被
    它自己的说明文档回答成「在」。这个项目已经有三条断言栽在这上面。
    """
    text = io.open(STATIC / name, encoding="utf-8").read()
    text = re.sub(r"/\*.*?\*/", " ", text, flags=re.S)
    return re.sub(r"^\s*//.*$", " ", text, flags=re.M)


def _pairs(text: str, pattern: str) -> dict[str, str]:
    return dict(re.findall(pattern, text))


# ---- ① 字号语速：三处不许分叉 ------------------------------------------------

def test_the_speed_and_font_ladders_are_the_same_everywhere() -> None:
    """慢/舒适/正常 与 较大/大/特大 的取值，设计一和设计三必须一模一样。

    设计一把它们写在 `elder.html` 的两个 `<select>` 里，设计三是分段按钮，
    只能在 JS 里按词映射。两份数字一旦分叉，同一位老人在两套界面上调出来的
    语速就是两个值，而两边**各自往返都是对的**——这正是这个项目
    「两套实现各自都绿、跨子系统才红」那次事故的形状。
    """
    html = io.open(STATIC / "elder.html", encoding="utf-8").read()

    def ladder(select_id: str) -> dict[str, str]:
        block = re.search(rf'<select id="{select_id}">(.*?)</select>', html, re.S)
        assert block, f"elder.html 里找不到 <select id={select_id}>"
        return {word: value for value, word
                in re.findall(r'<option value="([\d.]+)"[^>]*>([^<]+)</option>',
                              block.group(1))}

    js = _src("elder3.js")
    for name, select_id in (("SPEED", "speechRate"), ("FONT", "fontScale")):
        block = re.search(rf"const {name} = \{{(.*?)\}};", js, re.S)
        assert block, f"elder3.js 里找不到 {name}"
        got = {w: v for w, v in re.findall(r"'([^']+)':\s*([\d.]+)", block.group(1))}
        want = ladder(select_id)
        assert {k: float(v) for k, v in got.items()} == {k: float(v) for k, v in want.items()}, (
            f"设计三的 {name} 是 {got}，而 `elder.html#{select_id}` 是 {want}。\n"
            "  同一个词在两套界面上必须是同一个数。")


# ---- ② 提醒状态词：和 family.js 不许分叉 --------------------------------------

def test_the_reminder_words_match_the_family_page() -> None:
    """提醒的状态词照抄 `family.js` 的 `REMINDER_STEP`。

    这条是从一个实测缺陷来的：第一版拿 `common.js` 的 `statusWord()` 翻提醒，
    而那张表是**任务**状态（awaiting_family_approval / executing / …）。
    提醒是另一套（scheduled / notified / …），一个都对不上，于是三条待办
    在屏幕上全写着「还在办」——认不出来时的兜底文案，而它看起来完全正常。
    """
    fam = _src("family.js")
    block = re.search(r"const REMINDER_STEP = \{(.*?)\n\};", fam, re.S)
    assert block, "family.js 里找不到 REMINDER_STEP"
    want = _pairs(block.group(1), r"(\w+):\s*\['([^']+)'")

    v3 = _src("family3.js")
    block3 = re.search(r"const REMINDER_STEP = \{(.*?)\n  \};", v3, re.S)
    assert block3, "family3.js 里找不到 REMINDER_STEP"
    got = _pairs(block3.group(1), r"(\w+):\s*'([^']+)'")

    assert got == want, (
        f"设计三的提醒状态词是 {got}，而 `family.js` 是 {want}。\n"
        "  同一个状态在两套家人端上必须是同一个说法。")


# ---- ③ 读的字段名必须真的存在 --------------------------------------------------

def test_the_daily_report_fields_it_reads_really_exist() -> None:
    """`family3.js` 从日报里取的每一个字段，`AppDailyReport` 上都要有。

    这一条是这份文件里最要紧的，因为它抓的那个缺陷**在屏幕上完全看不出来**：

    第一版走的是 `/v7/daily-report/{id}`，字段名写成 `today_word` /
    `familyWillSee`——v7 给的是 `headline` / `suggested_for_family`，
    两个名字都不存在。于是每一处都落到我写的 `|| '今天和平常差不多'` 兜底上，
    而那句话读起来和真数据一模一样。截图、点击遍历、控制台、失败请求数，
    没有一样能看出区别：接口 200，页面有字，字还很像。
    """
    from youhuo.app_schemas import AppDailyReport

    known = set(AppDailyReport.model_fields)
    js = _src("family3.js")
    read = set(re.findall(r"\bdailyReport\.(\w+)", js))
    unknown = sorted(read - known)
    assert not unknown, (
        f"`family3.js` 读了 `AppDailyReport` 上没有的字段：{unknown}\n"
        f"  它有的是：{sorted(known)}\n"
        "  读一个不存在的字段拿到的是 undefined，配上一句兜底文案，"
        "屏幕上和真数据长得一模一样。")
    assert read, "一个 `dailyReport.` 都没数到——这条判据在空转"


def test_the_medication_fields_it_reads_really_exist() -> None:
    """用药计划的字段名同上，对的是 `MedicationPlanCreate`。

    第一版写的是 `p.name` / `p.dosage` / `p.times`——真名是
    `display_name` / `dose_text` / `times_local`，三个全错。后果是每一片药的
    名字和剂量都是空字符串，而卡片还在，看起来像「这条记录本来就没内容」。
    """
    from youhuo.v4_models import MedicationPlanCreate

    known = set(MedicationPlanCreate.model_fields) | {"id", "active", "family_id",
                                                      "created_at", "updated_at"}
    js = _src("family3.js")
    block = re.search(r"const seals = .*?const sum = ", js, re.S)
    assert block, "family3.js 里找不到填用药卡片那一段"
    read = set(re.findall(r"\bp\.(\w+)", block.group(0)))
    unknown = sorted(read - known)
    assert not unknown, (
        f"用药那一段读了计划上没有的字段：{unknown}\n  它有的是：{sorted(known)}")
    assert read, "一个 `p.` 都没数到——这条判据在空转"


# ---- ④ 交付包的假控件必须被摘掉 ------------------------------------------------

def test_the_fake_save_button_is_disarmed() -> None:
    """「保存我的习惯」不许还挂着交付包那个「假装保存」的监听。

    `page-motion-and-ui.js:117` 给它绑了「显示 ✓ 已保存 1.5 秒」，一个字节都不存。
    只加自己的监听不够——两个都会跑，于是**保存失败的时候屏幕上照样先弹出
    「已保存」**。一个说"已保存"却没保存的按钮，比没有这个按钮更糟。
    """
    js = _src("elder3.js")
    assert re.search(r"stripListeners\(\s*\$\('#savePref'\)\s*\)", js), (
        "`#savePref` 没有被 `stripListeners` 摘掉——交付包那个假保存还在。")
    assert re.search(r"stripListeners\(\s*\$\('#voiceOrb'\)\s*\)", js), (
        "`#voiceOrb` 没有被摘掉——交付包那个「假装在听」还在。")
    # 摘掉之后，成功文案只许出现在 await 成功之后。
    assert "'✓ 已保存'" not in js and '"✓ 已保存"' not in js, (
        "「✓ 已保存」还在。勾号是图标位置上的字符，这个项目不许拿字符当系统图标。")


def test_the_family_page_disarms_its_fabricated_states_table() -> None:
    """`script-01.js` 那张写死的 `states` 表必须被摘掉。

    点「待办」会把主舞台改成「燃气费缴纳…金额 ¥86.50」——一笔**编出来的**
    支付，出现在家人端最显眼的位置上。
    """
    js = _src("family3.js")
    assert re.search(r"\$\$\('\[data-family\]'\)\.forEach\(\(old\) => \{\s*const btn = strip\(old\)",
                     js), (
        "`[data-family]` 那三个按钮没有被 `strip()` 摘掉，"
        "交付包那张编造的 `states` 表还会覆盖主舞台。")


# ---- ⑤ 审批是两步 --------------------------------------------------------------

def test_viewing_a_payment_is_not_approving_it() -> None:
    """「查看并确认这件事」只读；真正的确认是它下面另外长出来的那个按钮。

    本项目 P0：**渲染一张回执绝不许创建、推进、批准、执行、重试或改动一笔事务。**
    一次点击既是查看又是付钱，正是这条约束要防的。
    """
    js = _src("family3.js")
    assert "/v2/family/approve" in js, "family3.js 里没有审批调用——这条判据在空转"

    # 取「查看」那个处理器的函数体，再把它切成**造出第二个按钮之前**和之后两段。
    #
    # 第一版判的是「`f3Approve` 在文件里比审批调用先出现」。变异测试证明它松：
    # `loadStage()` 里有一句 `const step2 = $('#f3Approve'); step2.remove();`，
    # 位置更靠前，于是「在查看处理器里直接付钱」这个变异照样绿。
    # 判据挂在整份文件的先后上，就会被一处完全无关的提及满足。
    handler = re.search(r"primary\.addEventListener\('click'.*?\n    \}", js, re.S)
    assert handler, "找不到「查看并确认这件事」的处理器"
    body = handler.group(0)
    made_button = body.find("document.createElement")
    assert made_button > 0, "「查看」里没有造第二个按钮——两步确认不存在了"

    before = body[:made_button]
    assert "/v2/family/approve" not in before, (
        "点「查看并确认这件事」的时候就调了 `/v2/family/approve`——"
        "一次点击既是查看又是付钱。本项目 P0：渲染回执绝不许推进事务。")
    assert "/v2/family/approve" in body[made_button:], (
        "第二个按钮上没有审批调用——那这两步里没有一步真的能确认。")


# ---- ⑥ 「知道了」不是「办完了」 -------------------------------------------------

def _sometime_today() -> str:
    """今天的一个**确定**时刻，完整 ISO。

    ## 为什么不能写 `{"time": "23:30"}`

    `HH:MM` 走的是「已经过点就顺延到明天」那条规则——对老人是对的
    （9 点设「8 点吃药」显然是指明天），但它让判据**跟着墙上时钟走**。
    实测 23:44 跑这两条：23:30 被解析成 `2026-08-21T15:30Z`，
    于是「新建的提醒不在今天的安排里」，判据红，而代码一个字没动过。

        判据里写死的      time=23:30  落在 2026-08-21T15:30+00:00  在今天: False
        现在往后 5 分钟   time=23:49  落在 2026-08-20T15:49+00:00  在今天: True

    也就是说这两条判据**每天 23:30 到零点之间必红**。竞赛前一晚有人跑一遍
    看到红，是最坏的时机。

    完整 ISO 不走那条顺延规则（实测「一小时前」的 ISO 原样保留），
    而今天的过点条目照样在 `/agenda` 的 `today` 里（种子里 11:00、14:00
    那两条 23:44 时仍在）。所以固定取今天 09:00：和当前时刻无关。
    """
    from datetime import datetime, time as dtime
    from zoneinfo import ZoneInfo

    cn = ZoneInfo("Asia/Shanghai")
    return datetime.combine(datetime.now(cn).date(), dtime(9, 0),
                            tzinfo=cn).isoformat()


def test_acknowledging_a_reminder_is_not_completing_it(client: TestClient) -> None:
    """老人按「我知道了」之后，日程上那一行**不许**写成「已完成」。

    这一条抓的是真发生过的事：设计三的待办气泡接上之后，按「我知道了」，
    气泡当场从「待进行」跳到「已完成」——系统替她宣称她把药吃了，
    而她只是说了句知道。她第二天回头看记录，看到的是一件没做的事被记成做了。

    成因在门面层：`/api/v1/agenda` 原先是
    `done = status in {COMPLETED, ACKNOWLEDGED}` 然后
    `"已完成" if done else "待进行"`——两个状态合成一个词。
    而设计一那边 `elder.js` 的 `REMINDER_STATUS` 里 acknowledged 是「知道了」、
    语气 `todo`。**同一条提醒，两个子系统说法相反。**

    `done` 也要跟着分开：它决定「接下来」挑哪一件，而按过「知道了」的那件药
    还是没吃，它就该继续待在「接下来」里。
    """
    made = client.post(f"{V1}/reminders",
                       json={"title": "吃钙片", "at": _sometime_today()})
    assert made.status_code == 200, made.text
    rid = made.json()["item"]["id"]

    def row():
        items = client.get(f"{V1}/agenda").json()["today"]
        hit = [x for x in items if x["id"] == rid]
        assert hit, f"新建的提醒不在今天的安排里：{items}"
        return hit[0]

    assert row()["status"] == "待进行", row()
    assert row()["done"] is False

    head = _elder(client)
    ack = client.post(f"/v2/reminders/{rid}/acknowledge", json={}, headers=head)
    assert ack.status_code == 200, ack.text

    after = row()
    assert after["status"] == "知道了", (
        f"按过「我知道了」之后，日程上写的是 {after['status']!r}。"
        "「知道了」和「已完成」不是一回事——后者是在替她宣称一件她没做的事。")
    assert after["done"] is False, (
        "「知道了」被算成了 done。那会把这件事从「接下来」里拿掉——"
        "而按过「知道了」的那件药还是没吃。")

    done = client.post(f"/v2/reminders/{rid}/complete", json={}, headers=head)
    assert done.status_code == 200, done.text
    assert row()["status"] == "已完成" and row()["done"] is True, row()


def test_the_three_reminder_words_are_all_different(client: TestClient) -> None:
    """三个状态在屏幕上必须是三个不同的词。

    单独一条，因为上面那条可以被「把「知道了」也改成「待进行」」满足——
    那样她按完之后屏幕上一个字都不动，正是这一整轮在修的另一件事。
    """
    # 同上：不写 `HH:MM`，它会跟着墙上时钟走。见 `_sometime_today()`。
    made = client.post(f"{V1}/reminders",
                       json={"title": "量血压", "at": _sometime_today()})
    rid = made.json()["item"]["id"]

    def word():
        items = client.get(f"{V1}/agenda").json()["today"]
        return next(x["status"] for x in items if x["id"] == rid)

    head = _elder(client)
    seen = [word()]
    assert client.post(f"/v2/reminders/{rid}/acknowledge", json={},
                       headers=head).status_code == 200
    seen.append(word())
    assert client.post(f"/v2/reminders/{rid}/complete", json={},
                       headers=head).status_code == 200
    seen.append(word())
    assert len(set(seen)) == 3, (
        f"三次状态迁移在屏幕上只有 {len(set(seen))} 种说法：{seen}。"
        "相同就等于「什么都没发生」。")


# `test_every_endpoint_the_wiring_calls_really_exists` 挪到了
# `test_every_wired_endpoint_exists.py`。挪的原因有两个：
#
#   · 它只扫 `elder3.js` / `family3.js`。同样的错在 `elder.js`（设计一二共用，
#     全仓最大的一份接线）里一样会发生，而它不在范围内。新的那份扫 `static/*.js`
#     全部，不列文件名——按文件名手工维护的范围是这个项目栽过的坑。
#   · 它的抽取器用一条 ``[^`\'"]+`` 通吃三种引号，遇到模板字面量里合法的单引号
#     （``${approve ? 'approve' : 'decline'}``）会在第一个 `\'` 处截断，
#     把半截路径拿去比对，然后把一个**完全正确**的写法报成缺陷。


def test_tapping_a_reminder_bubble_does_not_change_it(client: TestClient) -> None:
    """点一颗待办气泡本身**不许**发出任何写请求。

    这一版的待办是一整块椭圆气泡。点一下就把事情标记掉，手一抖就改了记录，
    而她看不出刚才发生过什么。所以气泡只负责问一句，两个动作各是一个按钮。
    静态判：气泡那个处理器里不许出现提醒接口，它只许调 `offer(...)`。
    """
    js = _src("elder3.js")
    handler = re.search(r"document\.addEventListener\('click'.*?\n    \}\);", js, re.S)
    assert handler, "找不到气泡那个委托处理器"
    body = handler.group(0)
    assert "offer([" in body, "点气泡之后没有给出可选的动作。"

    # 每一次 `reminderAction(` 都必须在回调里（前面紧挨着 `=> `）。
    #
    # 第一版查的是「处理器里有没有 `/v2/reminders/`」。变异测试证明它松：
    # 真正的写操作走的是 `reminderAction()` 这个辅助函数，URL 在别处，
    # 于是把「点一下直接标记完成」放回去，门照样绿——而那正是要防的那件事。
    hits = [m.start() for m in re.finditer(r"\breminderAction\(", body)]
    assert hits, "处理器里一次 `reminderAction` 都没有——这条判据在空转"
    直接调 = [h for h in hits if not body[max(0, h - 4):h].rstrip().endswith("=>")]
    assert not 直接调, (
        "点气泡就直接调了 `reminderAction`——一下把状态改掉。\n"
        "  它只许出现在 `offer([...])` 的回调里：她得看见两个写着字的按钮，"
        "再自己选一个。一整块椭圆手一抖就改了记录，而她看不出发生过什么。")


# ---- ⑦ 切到照护必须让它显形 ----------------------------------------------------

def test_switching_to_care_makes_it_visible() -> None:
    """切到照护中心必须补 `page-bloom`，否则整屏是空的。

    实测（点「照护中心」后每秒量一次 opacity，不是量 boundingRect）：

        +1s  看得见 53 段字 · 淡掉 92 段
        +6s  看得见 56 段字 · 淡掉 89 段   ← 不再变化，anim=none
        家人端那一屏对照：看得见 37 · 淡掉 3

    `style-01.css:1852` 把身份区那几行的初始态设成 `opacity:0`，只有
    `.workspace.page-bloom` 才给动画；而 `page-bloom` 是 `script-07.js` 在
    **过场动画播完**时加的，顶部这个切换只是 `hidden` 开关，从不播过场。
    """
    js = _src("family3.js")
    assert "page-bloom" in js, (
        "`family3.js` 里没有 `page-bloom`——切到照护中心会是一屏看不见的字。")

    # **每一条通往照护的路都要补**，不是有一条补了就行。
    #
    # 第一版只查「文件里有没有 `bloom($('#careView'))`」。变异测试证明它松：
    # 把顶部切换那条删掉，`#goCare` 那条还在，正则照样命中，门全绿——
    # 而顶部切换恰恰是主要入口。
    ways = {
        "顶部「照护中心」": r"dataset\.app === 'care'\) \{ bloom\(\$\('#careView'\)\)",
        "底栏「照护」": r"goCare\.addEventListener\('click', \(\) => \{ bloom\(\$\('#careView'\)\)",
    }
    missing = [name for name, pat in ways.items() if not re.search(pat, js)]
    assert not missing, (
        f"这些进照护的路没有补 `page-bloom`：{missing}。\n"
        "  走这条路进去，整屏的字停在 opacity:0——实测淡掉 89 段。")


# ---- ⑧ 交付包里那些没有钩子的控件 ----------------------------------------------

def test_the_care_dock_is_not_three_dead_buttons() -> None:
    """照护那一屏底栏的「待办」「我的」必须有 `data-family`。

    交付包里它们**连一个属性都没有**——没有 id、没有 data、没有 class 钩子，
    而家人端那一屏同样两个键是有的。实测（把每个控件都点一遍、看有没有请求
    或界面变化）：点下去什么都不发生。
    """
    html = io.open(STATIC / "family-v3.html", encoding="utf-8").read()
    dock = html[html.rindex('<nav class="dock">'):]
    for word, slot in (("待办", "todo"), ("我的", "mine")):
        assert re.search(rf'data-family="{slot}"[^>]*>(?:(?!</button>).)*{word}', dock, re.S) \
            or re.search(rf'{word}(?:(?!<button).)*?</button>', dock, re.S) and f'data-family="{slot}"' in dock, (
            f"照护底栏的「{word}」没有 `data-family=\"{slot}\"`——它是个死键。")


def test_the_service_rows_can_be_reached_by_keyboard() -> None:
    """「常用服务」那四行必须能用键盘到达。

    交付包里它们是 `<div class="service-row">`：看起来能点、实际不能，
    读屏和键盘也完全够不着。接线把它们接成了「说这句话」，
    那就得同时给 role 和 tabindex，否则只有鼠标用户用得上。
    """
    js = _src("elder3.js")
    block = re.search(r"\$\$\('\.service-row'\)\.forEach.*?\n    \}\);", js, re.S)
    assert block, "elder3.js 里没有接「常用服务」那四行"
    body = block.group(0)
    for need in ("'role', 'button'", "'tabindex', '0'", "keydown"):
        assert need in body, f"「常用服务」缺了 {need}——键盘用户够不着。"
