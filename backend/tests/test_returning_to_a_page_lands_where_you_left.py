r"""跨文档回到原处：Phase C/D 的前置判据之一。

## 它解决什么

`/family` `/care` `/trust` 是同一个 App 的三个 deep link，但它们是三个**文档**。
每次跳转都是完整的文档加载：JS 上下文重建、滚动归零。实测过：在 `/family` 滚到
y=204，去 `/care`，回来 y=0。

Medito 靠 `IndexedStack` 让四个 tab 页同时活着，切走再切回什么都没变
（这一条已跑起来实测，见 `frontend_redesign/ia/12_reference_study.md` 第一节）。
七个文档做不到那个，
只能把「回到原处」显式做出来——做法本身也照它抄：
`bottom_navigation_bar_view.dart:39-41` 把上次的 tab 存进 SharedPreferences
并在启动时恢复。

## 三条判据各自挡住一个真实的失效

① **按路径分槽**。第一版是单槽，实测**不恢复**——中间那一页把它覆盖了：
   离开 /family 存 `{path:'/family', y:204}`，离开 /care 又存
   `{path:'/care', y:0}` 盖掉它。而 A → B → A 正是这个功能唯一的使用场景，
   所以单槽在它自己要解决的那条路径上必然失效，且毫无声音。

② **等内容长出来再滚，但要有上限**。这三页的内容是异步取的，`load` 那一刻文档
   只有一屏高，此时 `scrollTo(0, 204)` 会被浏览器夹到 0。没有上限的话，
   一个永远不会长高的页面会让这段代码一直在 rAF 里转。

③ **恢复函数真的被调到**。「定义了但没人调」在这个项目里反复出现，而它和
   「功能正常但没数据」在屏幕上一模一样——同一个会话里 `loadActivity()` 与
   `renderKin()` 各踩过一次。
"""
from __future__ import annotations

import re
from pathlib import Path

COMMON = (Path(__file__).resolve().parents[2]
          / "backend" / "static" / "common.js")


def _source() -> str:
    text = COMMON.read_text(encoding="utf-8")
    # 注释抹空保留换行。这里非做不可：上面那段实现里的注释**逐字写着**
    # 「第一版是单槽」和那两个覆盖用的字面量，不去掉的话判据①会命中解释文字。
    text = re.sub(r"/\*.*?\*/", lambda m: "\n" * m.group(0).count("\n"), text, flags=re.S)
    return re.sub(r"//[^\n]*", "", text)


def test_both_halves_exist() -> None:
    source = _source()
    for name in ("rememberPlace", "restorePlace"):
        assert f"function {name}" in source, f"{name} 不见了"


def test_the_store_is_keyed_by_path_not_a_single_slot() -> None:
    """存的是 `{路径: 位置}` 的映射，不是一份。

    判据：写入时用 `location.pathname` 做**下标**（`places[location.pathname] =`），
    而不是把 pathname 存成一个字段。后者就是单槽——它在 A → B → A 上必然被
    中间那一页覆盖。
    """
    source = _source()
    assert re.search(r"\[\s*location\.pathname\s*\]\s*=", source), (
        "位置不是按路径分槽存的。单槽会被中间那一页覆盖，而 A → B → A "
        "正是这个功能唯一的使用场景——它会在自己要解决的那条路径上失效。"
    )
    # 读取也必须按路径取下标，否则读到的是别人的位置。
    assert re.search(r"readPlaces\(\)\s*\[\s*location\.pathname\s*\]", source), (
        "读取时没有按当前路径取下标"
    )


def test_the_wait_for_content_is_bounded() -> None:
    """等内容长出来要有上限。

    没有上限的话，一个永远不会长高的页面（数据取失败、空态）会让这段代码
    一直在 requestAnimationFrame 里转——一个安静的、永不结束的循环。
    """
    source = _source()
    assert "requestAnimationFrame" in source, (
        "没有逐帧重试：内容是异步长出来的，`load` 那一刻滚不到目标位置"
    )
    assert re.search(r"RESTORE_WINDOW_MS|deadline", source), "重试没有上限"
    assert re.search(r"Date\.now\(\)\s*>\s*deadline", source), (
        "没有真正检查上限——只定义一个常量不算"
    )
    # 放弃的时候不许停在半途：那个位置不属于任何东西。
    assert re.search(r"settled\s*=\s*true", source), "放弃时没有停止标记"


def test_stale_positions_expire() -> None:
    """半小时前的位置不要了。

    没有过期，一个上周留下的 sessionStorage 条目会把用户扔到一个他完全
    不记得的位置。sessionStorage 的生命周期是一个标签页，所以这一条防的是
    「同一个标签页开了很久」。
    """
    source = _source()
    assert "PLACE_TTL_MS" in source, "没有过期时间"
    assert re.search(r"Date\.now\(\)\s*-\s*saved\.t\s*>\s*PLACE_TTL_MS", source), (
        "定义了过期时间但没有拿它比较"
    )


def test_it_is_wired_to_events_that_actually_fire_on_mobile() -> None:
    """`pagehide` + `visibilitychange`，不是 `beforeunload`。

    `beforeunload` 在移动端浏览器里经常不触发，而且它会让页面失去进入
    后退/前进缓存的资格。iOS 上用户直接切走 App 时只有 `visibilitychange`。
    """
    source = _source()
    assert "'pagehide'" in source, "没有监听 pagehide"
    assert "visibilitychange" in source, (
        "没有监听 visibilitychange——iOS 上用户直接切走 App 时只有这一个事件"
    )
    assert "beforeunload" not in source, (
        "用了 beforeunload：它在移动端经常不触发，还会让页面失去 bfcache 资格"
    )


def test_the_restore_is_actually_called() -> None:
    """恢复函数必须真的被调到。

    `common.js` 是**经典脚本、在 `<head>` 里执行**（它自己的注释说的），
    所以此刻 `<body>` 还不存在、量不出文档高度。必须等 DOM 就绪。
    """
    source = _source()
    calls = re.findall(r"\brestorePlace\b", source)
    assert len(calls) >= 3, (
        f"restorePlace 只出现 {len(calls)} 次——它大概被定义了但没有调用路径。"
        "一个到不了的恢复函数，和没有这段代码在屏幕上是一样的。"
    )
    assert re.search(r"DOMContentLoaded['\"]?\s*,\s*restorePlace", source), (
        "没有挂在 DOMContentLoaded 上。common.js 在 <head> 里执行，"
        "那时 <body> 不存在，文档高度量出来没有意义。"
    )
    assert re.search(r"readyState\s*===?\s*['\"]loading['\"]", source), (
        "没有处理「脚本执行时 DOM 已经就绪」那一路——那时 DOMContentLoaded "
        "不会再来一次，恢复永远不发生"
    )


def test_it_turns_off_the_browsers_own_scroll_restoration() -> None:
    """两套恢复机制不能同时开着。

    浏览器自己的滚动恢复只在前进/后退时生效，而点一条 tab 链接是**全新导航**，
    它不管——但在前进/后退时两边会互相打架。
    """
    source = _source()
    assert "scrollRestoration" in source, (
        "没有接管 history.scrollRestoration：前进/后退时浏览器自己那套会和这段代码打架"
    )
