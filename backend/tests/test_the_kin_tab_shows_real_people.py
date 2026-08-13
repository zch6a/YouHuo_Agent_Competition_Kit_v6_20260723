r"""家人这一屏不许显示一个不在数据里的人名。

## 它修的是什么

`elder.html` 原先写着：

    <p class="kin-name" id="kinName">李晴</p>
    <p class="kin-rel"  id="kinRel">女儿</p>

「李晴」是整个 `backend/` 里**唯一一个人名**，而它不在任何数据里：
`elder.js` 从不写这两个元素，后端 `/v4/contacts/{elder}` 在演示数据下返回空列表
（实测），而全系统的词汇是**角色**——活动记录里的 `who` 就是「家人」。

而且它和产品自己的行为矛盾：身份里有 `daughter_id` **和** `son_id`，
种子场景那条审计记录写着「家人确认了一次，还在等其他家人」——系统承认有两位家人，
而这一屏说有一位叫李晴的。

这一类缺陷在参考产品里也有，而且更严重：Folk Care 的家属照护计划整段是
`// Mock care plan report data`，四个目标、叙事文本、三人护理团队（假邮箱假电话）
全是硬编码（`12_reference_study.md` 第四节，那一条的评语是「模式是对的，
实现是个门面」）。一个讲可信的产品不该在自己的屏幕上编人。

## 三条判据

① 那个名字消失了
② 承载真数据的容器在 HTML 里是**空的**（由 JS 填）
③ 填它的函数**真的会被调到**——「声明了但从不可达」是这个项目反复出现的失效方式，
   而它和「功能正常但没数据」在屏幕上长得一模一样
"""
from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
STATIC = ROOT / "backend" / "static"


def _blank_comments(text: str) -> str:
    """注释抹空但保留换行。

    这里非做不可：上面那段 HTML 注释里**逐字引用了**被删掉的
    `<p class="kin-name" id="kinName">李晴</p>`，用来解释为什么删。
    不去注释的话，第一条断言会命中那句解释，然后永远红着——
    而这个项目已经有过四次「测试匹配到了自己写的注释」。
    """
    text = re.sub(r"<!--.*?-->", lambda m: "\n" * m.group(0).count("\n"), text, flags=re.S)
    text = re.sub(r"/\*.*?\*/", lambda m: "\n" * m.group(0).count("\n"), text, flags=re.S)
    return re.sub(r"//[^\n]*", "", text)


def test_the_invented_name_is_gone_from_every_shipped_file() -> None:
    offenders = []
    for path in sorted(STATIC.rglob("*")):
        if path.suffix.lower() not in (".html", ".js", ".css"):
            continue
        body = _blank_comments(path.read_text(encoding="utf-8"))
        if "李晴" in body:
            line = body[:body.index("李晴")].count("\n") + 1
            offenders.append(f"{path.name}:{line}")
    assert not offenders, (
        f"「李晴」还在这些文件里：{offenders}。"
        "那是产品里唯一一个人名，而它不在任何数据里。"
    )


def test_the_kin_container_ships_empty() -> None:
    """承载真数据的容器在 HTML 里必须是空的。

    带着内容发出去的容器有两种坏法：JS 没跑时它是**假数据**；JS 跑了但接口空时
    它可能被**留在原地**（`replaceChildren()` 漏调），两种情况屏幕上都在说谎。
    """
    html = _blank_comments((STATIC / "elder.html").read_text(encoding="utf-8"))
    host = re.search(r"<div[^>]*id=['\"]kinList['\"][^>]*>(.*?)</div>", html, re.S)
    assert host, "找不到 #kinList——家人那一屏的容器不见了或改名了"
    inner = host.group(1).strip()
    assert not inner, f"#kinList 在 HTML 里不是空的：{inner[:120]!r}"
    assert 'aria-live' in host.group(0), (
        "#kinList 没有 aria-live：内容是异步填进去的，读屏用户不会知道它变了"
    )


def test_the_renderer_is_actually_reachable() -> None:
    """`renderKin()` 必须真的被调到。

    这个项目反复踩的形状：函数写好了、看起来完全正常，而没有任何执行路径通到它——
    屏幕上的结果和「功能正常但没有数据」一模一样。同一个会话里刚踩过一次：
    `loadActivity()` 存在、正确、且从不被 Tab 切换调用，于是「记录」这一屏
    **打开即空**，连空态文案都不出现。
    """
    source = _blank_comments((STATIC / "elder.js").read_text(encoding="utf-8"))
    assert "function renderKin" in source, "renderKin 不见了"
    calls = re.findall(r"\brenderKin\s*\(", source)
    # 一次是定义（`function renderKin(`），其余才是调用。
    assert len(calls) >= 2, (
        "renderKin 只出现了一次——它被定义了但没有任何地方调用它。"
        "一个到不了的渲染器，和没有这个渲染器在屏幕上是一样的。"
    )
    # 而且必须挂在进入这个 Tab 的那条路上。
    enter = re.search(r"function enterTab\([^)]*\)\s*\{(.*?)\n\}", source, re.S)
    assert enter, "找不到 enterTab——Tab 进入的那条路改名了"
    assert "renderKin" in enter.group(1), (
        "renderKin 不在 enterTab 里。那它只会在别的时机跑，"
        "而用户进这一屏的路径是切 Tab / 深链 / 前进后退三条，都走 enterTab。"
    )


def test_the_copy_does_not_assume_exactly_one_family_member() -> None:
    """文案不许假定「只有一位家人」。

    身份里有 `daughter_id` **和** `son_id`，而种子场景的审计记录写着
    「家人确认了一次，还在等其他家人」。原先这一屏的文案是「她可以帮您」
    「联系她」「先问您，再问她。两个人都同意才办」——三处都假定只有一位，
    和系统自己的行为矛盾。
    """
    html = _blank_comments((STATIC / "elder.html").read_text(encoding="utf-8"))
    kin = re.search(r"data-panel=['\"]kin['\"](.*?)</div>\s*<!--|"
                    r"data-panel=['\"]kin['\"](.*?)data-panel=", html, re.S)
    section = (kin.group(1) or kin.group(2)) if kin else html
    for bad in ("联系她", "她可以帮您", "两个人都同意"):
        assert bad not in section, (
            f"家人那一屏还写着「{bad}」——它假定只有一位家人，"
            "而这个家庭有两位（daughter_id 与 son_id），"
            "审计记录里也有「还在等其他家人」。"
        )
