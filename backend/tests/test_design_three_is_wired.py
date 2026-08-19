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

STATIC = Path(__file__).resolve().parents[1] / "static"


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


# ---- ⑥ 切到照护必须让它显形 ----------------------------------------------------

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
