"""双击 HTML 打开时，屏幕上必须有一句话，而不是一片黑。

这一条是被实际撞出来的。编辑器把 `judge.html` 用 `file://` 打进了预览面板，屏幕上
一片黑，而当时所有闸门都是绿的——它们**全部通过 HTTP 加载页面**，没有一条走过
`file://`。用户看到的是黑屏，仪器看到的是 200。

根因不是 bug，是路径：七个页面引用样式和脚本用的是 `/static/...` 绝对路径（它们被
服务在 `/elder`、`/trust` 这样的路径上，相对路径会算错）。`file://` 下这些绝对路径
解析到磁盘根，四个 CSS 和全部 JS 一次性 404，剩下一张裸 HTML——在深色渲染下就是黑底。

修法不是改成相对路径（那会让服务路径下的页面拿不到样式），是让**失败自己说话**：
一段平时被 `base.css` 藏起来的提示。CSS 在 → 看不见；CSS 不在 → 它是屏幕上唯一
的东西。

评委解开交付包双击一下，会走到同一条路。
"""
from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
STATIC = ROOT / "backend" / "static"
PAGES = ["index.html", "elder.html", "family.html", "care.html",
         "trust.html", "judge.html", "stage.html"]


# --- 静态：七个页面都有，且 CSS 里确实藏着它 ---------------------------------


@pytest.mark.parametrize("page", PAGES)
def test_every_page_carries_the_fallback(page):
    html = (STATIC / page).read_text(encoding="utf-8")
    assert 'class="needs-server"' in html, f"{page} 没有那段提示，file:// 下会是一片黑"
    # 它必须排在正文最前面。排在后面时，裸 HTML 下用户要先滚过整页才看得到。
    body = html.index("<body")
    banner = html.index('class="needs-server"')
    main = html.index("<main")
    assert body < banner < main, f"{page} 的提示不在 <body> 之后、<main> 之前"


def test_the_fallback_is_hidden_by_css_and_only_by_css():
    """藏它的必须是 CSS，不能是 `hidden` 属性或行内样式。

    用 `hidden` 藏，`file://` 下它照样是隐藏的——那这段提示就永远不会出现，而它存在
    的唯一理由就是在那一刻出现。
    """
    base = (STATIC / "base.css").read_text(encoding="utf-8")
    assert ".needs-server { display: none; }" in base, "base.css 里没有藏它的规则"
    for page in PAGES:
        html = (STATIC / page).read_text(encoding="utf-8")
        start = html.index('class="needs-server"')
        tag = html[html.rindex("<p", 0, start):html.index(">", start) + 1]
        assert "hidden" not in tag, f"{page} 用 hidden 藏了它，那它永远不会出现"
        assert "style=" not in tag, f"{page} 用行内样式藏了它"


# --- 运行时：真的用 file:// 打开一次 -----------------------------------------


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


def _chrome() -> str | None:
    sys.path.insert(0, str(ROOT / "backend" / "scripts"))
    try:
        import shoot_pages  # type: ignore

        return shoot_pages.find_chrome()
    except Exception:
        return None


PROBE = r"""
(() => {
  const el = document.querySelector('.needs-server');
  if (!el) return JSON.stringify({missing: true});
  const cs = getComputedStyle(el);
  const r = el.getBoundingClientRect();
  return JSON.stringify({
    display: cs.display,
    visible: cs.display !== 'none' && cs.visibility !== 'hidden' && r.height > 0,
    text: (el.textContent || '').replace(/\s+/g, ' ').trim().slice(0, 40),
    top: Math.round(r.top),
    // 加载失败的 <link> **仍然**出现在 document.styleSheets 里，只是 cssRules
    // 取不到。数张数会以为 CSS 加载成功了——第一版的前提断言就这么写错的。
    // 真正的判据是"有没有拿到规则"。
    rules: [...document.styleSheets].reduce((n, s) => {
      try { return n + s.cssRules.length; } catch (e) { return n; }
    }, 0),
    bodyBg: getComputedStyle(document.body).backgroundColor,
  });
})()
"""


def test_opening_the_file_directly_shows_an_explanation(tmp_path):
    """用 `file://` 打开 elder.html：样式表一个都加载不上，而提示必须可见。

    这条是这个文件里唯一不能被静态断言替代的：`display: none` 有没有生效，取决于
    那四个 `/static/*.css` 在 `file://` 下到底拿不拿得到——那是浏览器的事，不是
    源码里读得出来的事。
    """
    chrome = _chrome()
    if not chrome:
        pytest.skip("找不到 Chrome")
    try:
        import websocket  # type: ignore
    except ImportError:
        pytest.skip("缺少 websocket-client")

    sys.path.insert(0, str(ROOT / "backend" / "scripts"))
    import shoot_pages  # type: ignore

    cdp_port = _free_port()
    browser_proc = subprocess.Popen(
        [chrome, "--headless=new", "--disable-gpu", "--no-sandbox", "--hide-scrollbars",
         f"--remote-debugging-port={cdp_port}", "--remote-allow-origins=*",
         f"--user-data-dir={tmp_path / 'profile'}", "about:blank"],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    try:
        ws_url = None
        for _ in range(60):
            try:
                with urllib.request.urlopen(
                    f"http://127.0.0.1:{cdp_port}/json/version", timeout=2
                ) as r:
                    ws_url = json.loads(r.read())["webSocketDebuggerUrl"]
                break
            except Exception:
                time.sleep(0.5)
        if not ws_url:
            pytest.skip("CDP 没起来")

        browser = shoot_pages.CDP(ws_url, websocket)
        target = browser.send("Target.createTarget", url="about:blank")["targetId"]
        with urllib.request.urlopen(f"http://127.0.0.1:{cdp_port}/json/list", timeout=5) as r:
            tabs = json.loads(r.read())
        tab = shoot_pages.CDP(
            next(t["webSocketDebuggerUrl"] for t in tabs if t["id"] == target), websocket
        )
        tab.send("Page.enable")
        tab.send("Emulation.setDeviceMetricsOverride",
                 width=1280, height=800, deviceScaleFactor=1, mobile=False)
        tab.send("Page.navigate", url=(STATIC / "elder.html").as_uri())
        time.sleep(2.0)
        d = json.loads(tab.send("Runtime.evaluate", expression=PROBE,
                                returnByValue=True)["result"]["value"])
    finally:
        browser_proc.terminate()
        try:
            browser_proc.wait(timeout=15)
        except subprocess.TimeoutExpired:
            browser_proc.kill()

    assert not d.get("missing"), "file:// 下页面里没有那段提示"
    # 前提：一条 CSS 规则都没拿到。拿到了这条测试就没在测它想测的东西。
    assert d["rules"] == 0, (
        f"file:// 下居然拿到了 {d['rules']} 条 CSS 规则——这条测试的前提不成立了，"
        "要么样式改成了相对路径（那就该改这条测试），要么它在测别的东西"
    )
    # 实测的黑屏成因：body 背景是透明的，压在浏览器的深色画布上。
    assert d["bodyBg"] in ("rgba(0, 0, 0, 0)", "transparent"), (
        f"body 背景是 {d['bodyBg']}，不再是「透明压在画布上」那个情形了"
    )
    assert d["visible"], f"提示没显示出来（display={d['display']}），用户看到的还是一片黑"
    assert "服务器" in d["text"], f"提示的内容不对：{d['text']}"
    assert d["top"] < 200, f"提示在视口 {d['top']}px 处，第一屏看不到它"
