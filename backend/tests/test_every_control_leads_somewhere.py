"""山水版老人端：**点下去必须有去处**。

这条判据编码的是一句产品要求的原话——「每个界面确保所有功能都能使用，
点击需要有反馈或者跳转界面或者进入当前功能」。

为什么需要它，而不是靠人点一遍：

这一轮之前，`app/pages/` 上有 **20 个控件**点下去只弹同一句
「入口已预留，可直接接后端」。它们在任何测试里都是绿的——控件存在、
有 `data-action`、有处理分支、不报错。**「有处理分支」和「这个功能能用」
是两件事**，而当时所有判据都只看得见前者。

更糟的一条：`services.html` 那六张卡带着 `disabled` 属性。`disabled` 的
按钮**根本不派发 click**，所以就算处理分支写对了也永远不会触发——
点下去屏幕上什么都不会发生，连那句占位提示都没有。这一条只有在浏览器里
真的按一下才看得见，而 79 条页面判据一条都没有覆盖它。

四件事：

  ① 每个 `data-action` 都要有人接（`app.js` 或对应的 `page-*.js`）
  ② 每个 `data-service` 都要有去处（`SERVICE_DEST` 里有，或有专门分支）
  ③ `ROUTES` 里每个目标文件都得真的存在——跳到一个 404 比不跳更糟
  ④ 可点控件不许带 `disabled`，页面上不许再留占位文案
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
APP = ROOT / "backend" / "static" / "app"
PAGES = sorted((APP / "pages").glob("*.html"))
APP_JS = (APP / "assets" / "js" / "app.js").read_text(encoding="utf-8")

#: `data-service` 之外，这几个名字由 `app.js` 里的专门分支接管，不走映射表。
#: 写死在这里而不是从 JS 里抠，是为了「加一个特例」这件事必须显式改判据。
_SPECIAL_SERVICES = {"帮助与客服", "常用服务", "全部记录"}

#: 由 `page-*.js` 而不是 `app.js` 接管的动作。同上，加一个要显式写。
_PAGE_LOCAL_ACTIONS: set[str] = set()


def _page_scripts(page: Path) -> list[Path]:
    """这一页加载了哪些本地 js。"""
    src = page.read_text(encoding="utf-8")
    out = []
    for ref in re.findall(r'<script\s+src="([^"]+\.js)"', src):
        target = (page.parent / ref).resolve()
        if target.is_file():
            out.append(target)
    return out


def _handled_actions(page: Path) -> set[str]:
    """这一页能接住哪些 `data-action`。"""
    handled: set[str] = set()
    for js in _page_scripts(page):
        text = js.read_text(encoding="utf-8")
        handled |= set(re.findall(r'a\s*===\s*"([\w-]+)"', text))
        handled |= set(re.findall(r'dataset\.action\s*===\s*"([\w-]+)"', text))
        # 页面脚本自己绑的：`[data-action="x"]` 选择器
        handled |= set(re.findall(r'\[data-action=["\']?([\w-]+)["\']?\]', text))
    return handled


def _enclosing_tag(src: str, pos: int) -> str:
    """`pos` 这个属性写在哪个标签里。取它左边最近的 `<` 到右边最近的 `>`。"""
    start = src.rfind("<", 0, pos)
    end = src.find(">", pos)
    return src[start : end + 1] if start >= 0 and end > start else ""


def _js_mentions_id(js: str, el_id: str) -> bool:
    """这段脚本有没有提到这个 id。

    只认 `#id` 是不够的：`getElementById("faApprove")` 里 id 是**裸引号字符串**，
    没有井号。第一版因此把两个真的绑好了的按钮判成「点下去什么都不会发生」——
    判据把一种取元素的写法当成了唯一的写法，这已经是同一天里的第二次。
    要判的是「有没有东西引用它」，那就把三种引用形式都算上。
    """
    return f"#{el_id}" in js or f'"{el_id}"' in js or f"'{el_id}'" in js


def _service_dest_keys() -> set[str]:
    block = re.search(r"const SERVICE_DEST\s*=\s*\{(.*?)\n\};", APP_JS, re.S)
    assert block, "app.js 里找不到 SERVICE_DEST——这条判据失去依据，先修判据"
    return set(re.findall(r'"([^"]+)"\s*:', block.group(1)))


def _routes() -> dict[str, str]:
    block = re.search(r"const ROUTES\s*=\s*\{(.*?)\n\};", APP_JS, re.S)
    assert block, "app.js 里找不到 ROUTES——这条判据失去依据，先修判据"
    return dict(re.findall(r'(\w+)\s*:\s*"([^"]+\.html)"', block.group(1)))


def test_the_instrument_actually_reads_something() -> None:
    """先证明这条判据看得见东西。

    十个页面全空、映射表读成空集，下面三条会**全部通过**——
    而通过的原因是什么都没读到。本项目为这个形状付过多次代价。
    """
    assert len(PAGES) >= 10, f"只找到 {len(PAGES)} 个页面，页面目录大概没读对"
    assert len(_service_dest_keys()) >= 10, "SERVICE_DEST 读出来太少，正则大概没匹配上"
    assert len(_routes()) >= 10, "ROUTES 读出来太少"
    all_actions = set()
    for page in PAGES:
        all_actions |= set(re.findall(r'data-action="([\w-]+)"', page.read_text(encoding="utf-8")))
    assert len(all_actions) >= 10, f"只读到 {len(all_actions)} 种动作"


@pytest.mark.parametrize("page", PAGES, ids=lambda p: p.name)
def test_every_action_on_this_page_has_a_handler(page: Path) -> None:
    used = set(re.findall(r'data-action="([\w-]+)"', page.read_text(encoding="utf-8")))
    handled = _handled_actions(page) | _PAGE_LOCAL_ACTIONS
    orphan = sorted(used - handled)
    assert not orphan, (
        f"{page.name} 上这些动作没有人接：{orphan}。\n"
        "点下去不会有任何事发生——而「有 data-action」在别的判据里看起来完全正常。"
    )


@pytest.mark.parametrize("page", PAGES, ids=lambda p: p.name)
def test_every_button_is_bound_to_something(page: Path) -> None:
    """每个按钮都得被什么东西绑住。

    第一版只认 `data-action`，还顺手断言「这一页至少要有一个」。那假设是错的：
    新页面用**页面脚本绑自己的 `data-*`**（`[data-do=...]` / `[data-check]`），
    一个 `data-action` 都没有，于是被判成「这一页是死的」——而它们其实是活的。
    判据把一种实现方式当成了唯一的正确写法。

    要守的性质不是「用哪套属性」，是**这个按钮点下去有没有人管**。所以四选一：
    `data-action` 有人接、或它的某个 `data-*` / `id` / class 出现在这一页
    自己的脚本选择器里。四条都不沾的按钮，才是真的死的。
    """
    src = page.read_text(encoding="utf-8")
    js = "\n".join(p.read_text(encoding="utf-8") for p in _page_scripts(page))
    handled = _handled_actions(page) | _PAGE_LOCAL_ACTIONS

    dead = []
    for tag in re.findall(r"<button[^>]*>", src):
        action = re.search(r'data-action="([\w-]+)"', tag)
        if action and action.group(1) in handled:
            continue
        data_keys = re.findall(r"\sdata-([\w-]+)=", tag)
        if any(f"[data-{k}" in js for k in data_keys):
            continue
        el_id = re.search(r'\sid="([^"]+)"', tag)
        if el_id and _js_mentions_id(js, el_id.group(1)):
            continue
        classes = (re.search(r'\sclass="([^"]*)"', tag) or re.match("", "")).group(1).split() \
            if re.search(r'\sclass="([^"]*)"', tag) else []
        if any(f".{c}" in js for c in classes):
            continue
        dead.append(tag)

    assert not dead, (
        f"{page.name} 上有 {len(dead)} 个按钮没有任何东西绑它，点下去什么都不会发生：\n  "
        + "\n  ".join(t[:150] for t in dead)
    )


@pytest.mark.parametrize("page", PAGES, ids=lambda p: p.name)
def test_every_service_control_leads_somewhere(page: Path) -> None:
    """只看 `data-action="service"` 的那些。

    第一版按「标签上有没有 `data-service`」取，于是把 `services.html` 上三张
    **早就通了**的卡（`data-action="nav" data-to="records" data-service="我的记录"`）
    也算成没有去处——它们的 `data-service` 只是给清单当名字用的。
    要判的是「这个格子归谁处理」，那取决于 `data-action`，不是有没有别的属性。
    """
    names = {
        m.group(1)
        for m in re.finditer(r'data-service="([^"]+)"', page.read_text(encoding="utf-8"))
        for tag in [_enclosing_tag(page.read_text(encoding="utf-8"), m.start())]
        if 'data-action="service"' in tag
    }
    known = _service_dest_keys() | _SPECIAL_SERVICES
    missing = sorted(names - known)
    assert not missing, (
        f"{page.name} 上这些格子没有去处：{missing}。\n"
        "它们会掉进 SERVICE_DEST 的兜底分支，屏幕上只弹一句「还没有接上」。"
    )


def test_every_route_points_at_a_file_that_exists() -> None:
    broken = {k: v for k, v in _routes().items() if not (APP / "pages" / v).is_file()}
    assert not broken, (
        f"这些路由指向不存在的页面：{broken}。\n"
        "跳到一个 404 比原地不动更糟——用户以为自己按错了。"
    )


@pytest.mark.parametrize("page", PAGES, ids=lambda p: p.name)
def test_no_clickable_control_is_disabled(page: Path) -> None:
    """带 `data-action` 却又 `disabled`：处理分支写得再对也永远不触发。

    实测发生过：`services.html` 六张卡同时有 `data-action="service"` 和 `disabled`。
    """
    src = page.read_text(encoding="utf-8")
    bad = [
        tag for tag in re.findall(r"<button[^>]*>", src)
        if "data-action=" in tag and re.search(r"\sdisabled(\s|>|=)", tag)
    ]
    assert not bad, (
        f"{page.name} 上有 {len(bad)} 个按钮既带 data-action 又 disabled，"
        f"点下去不会派发 click：\n  " + "\n  ".join(t[:150] for t in bad)
    )


@pytest.mark.parametrize("page", PAGES, ids=lambda p: p.name)
def test_no_placeholder_copy_left_on_screen(page: Path) -> None:
    """屏幕上不许再写「还没有做好」。

    这些字曾经是**诚实**的：那 20 个控件当时确实没有去处，标出来比装作能用好。
    现在它们都接上了，同一句话就变成了假话——比原来更糟，因为它劝用户别去点
    一个其实能用的功能。
    """
    src = page.read_text(encoding="utf-8")
    for phrase in ("还没有做好", "入口已预留", "可直接接后端", "敬请期待", "功能开发中"):
        assert phrase not in src, (
            f"{page.name} 里还留着占位文案「{phrase}」。"
            "要么把功能接上，要么这句话是假的。"
        )
