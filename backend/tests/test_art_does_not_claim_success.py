"""图片也会替页面说话，而只查文字的判据看不见它。

## 这条判据是被一张图逼出来的

`app/art/png/cert_gold_seal.png` 里**画着**一枚绿徽章，写着「交易成功」，还带对勾。
它原先无条件铺在两个地方：

    certificate.html      —— 状态可能是「等家人确认」
    family-approve.html   —— 家人正在决定同不同意的**那一屏**

于是一笔还没批准的钱，旁边摆着一张图说它成功了。

这和本项目的 P0（「渲染凭证绝不许宣称一笔并未发生的交易」）是同一件事，
只是这一次的断言是**画在图里的**。代码里的状态文案早就改对了
（`CERT_STATE` 会显示「等家人确认」），而图片照样替它说了反话——
所有现有判据全绿，因为它们查的都是**文字**。

发现它的办法也值得记：把 87 张素材拼成一张联络表，看了一眼。
不是搜出来的，是看出来的。

## 为什么不改图

绿徽章在 y147–181，而金环跨 y56–209——裁不掉；抠掉会在环上留个洞。
而且「成功的印章在成功之后出现」本来就是对的做法，不是将就。

## 顺带记下来：这一批素材普遍有界面文字残留

同一张联络表上还能看到（`scene_tree_left` 有「请」、`scene_pavilion_right` 有「听」、
`bill_scene_right` 有「息」、`success_scene_right` 有「已」…）。那些是从带界面文字的
稿子上裁下来的残留，出现在山水背景里，属于观感问题；只有金印那一张是**断言**，
所以只有它被钉在这里。其余的记在 KNOWN_ISSUES。
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
APP = ROOT / "backend" / "static" / "app"

#: 图里画着结论的素材 → 它只允许在哪个状态下出现。
#: 加一张这样的素材，就得在这里写明它什么时候才可以露面。
CLAIMING_ART = {"cert_gold_seal.png": "completed"}

#: 用到那张金印的页面。写死是有意的：glob 出来的空集合会让下面每一条静默通过。
SEAL_PAGES = ["certificate.html", "family-approve.html"]


def test_the_instrument_reads_something() -> None:
    for name in SEAL_PAGES:
        assert (APP / "pages" / name).is_file(), f"{name} 不在了——这条判据失去依据"
    for art in CLAIMING_ART:
        assert (APP / "art" / "png" / art).is_file(), f"{art} 不在了"


@pytest.mark.parametrize("page", SEAL_PAGES)
def test_the_success_seal_starts_hidden(page: str) -> None:
    """markup 里的默认必须是「不露面」。

    默认露面 + JS 去藏，等于在 JS 跑起来之前有一瞬间它是可见的；
    更糟的是 JS 一旦出错，它就永久留在屏幕上宣称成功。
    默认藏起来的失败模式是「少一张装饰图」，那个方向是安全的。
    """
    src = (APP / "pages" / page).read_text(encoding="utf-8")
    tags = [t for t in re.findall(r"<img[^>]*>", src) if "cert_gold_seal.png" in t]
    assert tags, f"{page} 里找不到那张金印——它被换掉了？这条判据要跟着改"
    for tag in tags:
        assert re.search(r"\shidden(\s|>|=)", tag), (
            f"{page} 上那枚写着「交易成功」的金印默认是可见的：\n  {tag[:160]}\n"
            "它必须默认 hidden，由状态决定露不露面。"
        )
        assert 'id="certSuccessSeal"' in tag, (
            f"{page} 上的金印没有 `id=\"certSuccessSeal\"`，没有东西能按状态控制它"
        )


def test_app_js_only_shows_the_seal_when_completed() -> None:
    src = (APP / "assets" / "js" / "app.js").read_text(encoding="utf-8")
    assert "setSuccessSeal" in src, "app.js 里没有控制这枚金印的地方"
    # 必须**明确**和 completed 绑定，而不是随便什么真值。
    assert re.search(r'setSuccessSeal\(\s*cert\.status\s*===\s*"completed"\s*\)', src), (
        "app.js 没有把金印绑到 `cert.status === \"completed\"`。"
        "绑到别的真值上，等于让它在「等家人确认」时也可能露面。"
    )


def test_the_family_page_gates_the_seal_too() -> None:
    """家人确认页走的是自己的脚本，不经过 `renderCert`。

    单独测它，因为这一屏是**最不能出现成功印章**的地方——
    家人正是在这里决定同不同意。
    """
    src = (APP / "assets" / "js" / "page-family-approve.js").read_text(encoding="utf-8")
    assert "setSuccessSeal" in src, (
        "family-approve 的脚本没有控制那枚金印。它默认 hidden 所以不会出错，"
        "但这条判据要的是**明确**按状态控制，而不是靠「碰巧没人显示它」。"
    )
    assert re.search(r"setSuccessSeal\(\s*done\s*\)", src), (
        "没有把金印绑到 `done`（`cert.status === \"completed\"`）"
    )
