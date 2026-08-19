"""`aria-controls` 是一个承诺：声明了就必须真的能控制那个东西。

## 这道门从哪来

`stage.html` 的 `#directorToggle` 写着

    <button id="directorToggle" aria-expanded="false" aria-controls="directorDeck">导演台</button>

而**全仓库没有任何 `.js` 提到它**。三处 `.stage-pick` 的事件委托都限定在
`#stageRoles` / `#stageSizes` / `#stageLines` 上，它却在页头的 `.stage-depth` 里；
严格 CSP（`script-src 'self'`）排除了内联处理器。按下去什么都不发生，
`aria-expanded="false"` 永远是 false。

它不是可有可无的装饰。`stage.html:48` 记着它为什么存在：这一页的两个出口原先都
锁在收起的 `<details id="directorDeck">` 里，`check_exits.py` 五个宽度全报死路
（出口 2 · 一步可用 0 · 首屏 0），而 manifest 是 `display: standalone`——
装成应用之后没有后退键，iOS 上连边缘滑动都没有。页头那个按钮是那次修复的一半，
只是没接上。

## 为什么守这一类，而不是守这一个

`aria-expanded` 是**读屏用户唯一能感知的开合信号**。一个永远是 `false` 的
`aria-expanded` 比没有更糟：它主动告诉用户「这里有东西可以展开」，
然后按下去毫无反应，而视力正常的用户至少还能看见旁边那个 `<details>`。

所以判据是：**任何声明了 `aria-controls` 的控件，都必须有代码在操作它。**

## 判据的边界（这两条是量出来定的，不是拍脑袋）

- 只看**同一页加载的脚本**。一个控件由别的页面的脚本操作是不可能的。
- `<summary>` 自己不算——原生 `<details>` 的展开由浏览器负责，
  它的 `aria-expanded` 也由浏览器维护。这里只查作者写的控件。
"""
from __future__ import annotations

import io
import re
from pathlib import Path

import pytest

STATIC = Path(__file__).resolve().parents[1] / "static"

#: 扫这些页面。跟着 `surfaces.py` 走会把 `app/pages/*` 也带进来，
#: 而那一套有自己的委托约定（`[data-action]` 文档级委托），单独一条门更清楚。
PAGES = ["index.html", "elder.html", "elder-v6.html", "family.html",
         "family-v6.html", "care.html", "trust.html", "judge.html", "stage.html"]


def _read(name: str) -> str:
    return io.open(STATIC / name, encoding="utf-8").read()


def _scripts_of(page: str) -> list[str]:
    """这一页加载的本地脚本的源码。

    只取 `/static/*.js`：外链脚本这个项目没有（严格 CSP 也不允许），
    而 `type="module"` 的 import 链要跟着展开——`elder.js` 靠 import 拉
    `task-space.js` / `task-detail.js`，处理器可能写在那里面。
    """
    html = _read(page)
    seen: list[str] = []
    queue = [m.group(1) for m in
             re.finditer(r'<script[^>]+src="/static/([\w./-]+)"', html)]
    while queue:
        rel = queue.pop(0)
        path = STATIC / rel
        if rel in seen or not path.is_file():
            continue
        seen.append(rel)
        src = io.open(path, encoding="utf-8", errors="replace").read()
        for m in re.finditer(r"""(?:import|from)\s+['"]\./([\w./-]+)['"]""", src):
            queue.append(m.group(1))
    return [io.open(STATIC / rel, encoding="utf-8", errors="replace").read()
            for rel in seen]


def _binds_by_id(script: str, control_id: str) -> bool:
    """这段脚本有没有**给这个 id 绑上处理器**（而不只是提到它）。

    第一版的判据是「id 在脚本里出现过」。变异测试当场证明它太松：
    把 `directorToggle.addEventListener('click', …)` 改成
    `addEventListener('__never__', …)`——处理器彻底废了，而
    `getElementById('directorToggle')` 那一行还在，门照样绿。

    **提到不等于操作。** 现在认三种真正的绑定形态：

        directorToggle.addEventListener(…)                 先存变量再绑
        document.getElementById('x').addEventListener(…)   直接链式
        onclick = / .onclick =                             老写法

    第一种要先把变量名找出来——变量名和 id 不一定同名。
    """
    ident = re.escape(control_id)

    # ① 链式：getElementById('x').addEventListener / querySelector('#x').addEventListener
    if re.search(rf"""(?:getElementById|querySelector)\(\s*['"]#?{ident}['"]\s*\)"""
                 rf"""\s*\.\s*(?:addEventListener|onclick)""", script):
        return True

    # ② 先存变量再绑：找出变量名，再看它有没有被绑
    for m in re.finditer(
            rf"""(?:const|let|var)\s+(\w+)\s*=\s*"""
            rf"""(?:document\.)?(?:getElementById|querySelector|byId)\("""
            rf"""\s*['"]#?{ident}['"]\s*\)""", script):
        var = re.escape(m.group(1))
        if re.search(rf"\b{var}\s*\.\s*(?:addEventListener|onclick\s*=)", script):
            return True

    return False


def _controls_with_aria_controls(html: str) -> list[tuple[str, str, tuple[str, ...]]]:
    """返回 `(元素的 id, 它声称控制的 id)`。

    没有自己 id 的控件跳过——那种只能靠委托绑，本文件的判据够不着它，
    硬报只会制造假红。控件清单那一套（`build_control_inventory.py`）
    覆盖的是那一类。
    """
    out = []
    for m in re.finditer(r"<(button|a|input|div|span)\b([^>]*)>", html):
        attrs = m.group(2)
        controls = re.search(r'aria-controls="([\w\s-]+)"', attrs)
        if not controls:
            continue
        own = re.search(r'\bid="([\w-]+)"', attrs)
        if not own:
            continue
        # 它自己带的 data-* 属性名。判「接没接上」时要一起看：
        # 这个仓库有意用属性委托（`[data-sheet-open]`），那种控件的 id
        # 一次都不会在脚本里出现，而它是真的接通的。
        data_attrs = re.findall(r"\b(data-[\w-]+)", attrs)
        out.append((own.group(1), controls.group(1), tuple(data_attrs)))
    return out


@pytest.mark.parametrize("page", PAGES)
def test_every_aria_controls_button_is_actually_wired(page: str) -> None:
    if not (STATIC / page).is_file():
        pytest.skip(f"{page} 不存在")
    html = _read(page)
    pairs = _controls_with_aria_controls(html)
    if not pairs:
        pytest.skip(f"{page} 没有声明 aria-controls 的控件")

    scripts = _scripts_of(page)
    dead = []
    for own_id, target_id, data_attrs in pairs:
        # 「有代码在操作它」有**两种**正当形态，都要认：
        #
        #   ① 脚本里直接出现它的 id
        #   ② 脚本用它自带的 `data-*` 属性做选择器委托
        #
        # 第二种不是理论上的可能性，是这个仓库有意的写法：`#openExtras` 由
        # `sheet.js:30` 的 `[data-sheet-open]` 绑，`aria-expanded` 在 `:82` 统一维护，
        # 而它的 id **一次都没在脚本里出现过**。
        #
        # 这道门的第一版只认第一种，于是把一个真接通的控件报成死控件。
        # 我差点去加白名单——那是错的：白名单让门失去发现同类的能力，
        # 而这里要修的是判据本身。
        by_id = any(_binds_by_id(s, own_id) for s in scripts)
        by_attr = any(re.search(rf"\[{re.escape(attr)}[\]=]", s)
                      for attr in data_attrs for s in scripts)
        if not (by_id or by_attr):
            dead.append(f"#{own_id}（声称控制 #{target_id}）")

    assert not dead, (
        f"{page} 里这些控件声明了 aria-controls 却没有任何脚本操作它们：\n  "
        + "\n  ".join(dead)
        + "\n\n  `aria-expanded` 是读屏用户唯一能感知的开合信号。一个永远不变的"
          "\n  `aria-expanded` 比没有更糟——它主动说「这里能展开」，然后按下去"
          "\n  毫无反应，而视力正常的用户至少还看得见旁边那个容器。"
          "\n  要么接上，要么把 aria-controls / aria-expanded 一起去掉。"
    )


@pytest.mark.parametrize("page", PAGES)
def test_aria_controls_points_at_something_that_exists(page: str) -> None:
    """指向的目标必须真的在这一页上。

    和上一条分开：一个**接上了但指错了**的控件，上一条是绿的——脚本提到了它的
    id，判据满足。而读屏软件会去找那个不存在的目标，得到的是一句空话。
    """
    if not (STATIC / page).is_file():
        pytest.skip(f"{page} 不存在")
    html = _read(page)
    ids = set(re.findall(r'\bid="([\w-]+)"', html))
    missing = [f"#{own}  →  #{one}"
               for own, target, _ in _controls_with_aria_controls(html)
               for one in target.split()
               if one not in ids]
    assert not missing, (
        f"{page} 的 aria-controls 指向了这一页上不存在的元素：\n  "
        + "\n  ".join(missing))


def test_the_director_toggle_keeps_the_details_as_the_single_source() -> None:
    """导演台开关不许自己记一个布尔。

    `<summary>` 是原生控件：用户点它、按空格、或者浏览器的页内查找命中里面的
    文字，都会改 `<details>.open` 而**不经过那个按钮**。按钮如果维护自己的状态，
    第二次点就反了——实测过这条路径（点 summary 展开 → 再点按钮，
    正确行为是收起）。

    判据落在实现上：按钮的处理器必须读 `directorDeck.open`，
    并且要监听 `<details>` 的 `toggle` 事件把 `aria-expanded` 同步回来。
    """
    src = io.open(STATIC / "stage.js", encoding="utf-8").read()
    # 先剥注释再判断。这个文件的注释密度很高，而上面那段解释本身就含有
    # `directorDeck.open` 这些字样——不剥的话，一段措辞恰当的注释就能让门变绿。
    src = re.sub(r"/\*.*?\*/", "", src, flags=re.S)
    src = re.sub(r"^\s*//.*$", "", src, flags=re.M)
    # 判据落在**赋给 aria-expanded 的那个值**上，不是「文件里出现过
    # directorDeck.open」。
    #
    # 第一版就是后者，变异测试证明它太松：`directorDeck.open = !directorDeck.open`
    # 这一行本身就含有那个字符串，所以哪怕把 `sync` 里的读改成一个自己的布尔，
    # 门照样绿——而那正是这道门要防的缺陷。
    #
    # 一个断言如果被它要防的缺陷满足，它守的就不是它声称的那件事。
    assert re.search(
        r"""setAttribute\(\s*['"]aria-expanded['"]\s*,\s*directorDeck\.open\b""", src), (
        "`aria-expanded` 的值不是从 `directorDeck.open` 推出来的——"
        "按钮多半在自己记状态。<summary> 是原生控件，用户点它、按空格、"
        "或者浏览器页内查找命中里面的文字都会改 open 而不经过按钮，"
        "两边立刻分叉。")
    assert re.search(r"""directorDeck\.addEventListener\(\s*['"]toggle['"]""", src), (
        "没有监听 <details> 的 toggle 事件：用户从 <summary> 展开时，"
        "按钮的 aria-expanded 不会跟上，读屏用户听到的是错的")
