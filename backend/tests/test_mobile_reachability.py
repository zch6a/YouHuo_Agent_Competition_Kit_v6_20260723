"""手机上每一页的内容都必须摸得到。

这个文件的存在有一个具体原因。`main.shell { max-height: 100dvh; overflow: hidden }`
是为老人端的"会话一屏"写的——那个屏幕里 stage 是定高的，没有东西需要生长，所以
裁剪是安全的。但这条规则没有限定页面，而 6 个页面共用 `.shell`。在 390x844 实测：

    index 少了 2157px，family 2016，judge 1964，care 1444，trust 1223

也就是说手机上首屏以下的内容**根本不存在**。而它躲过了当时所有的关卡：

* 整页截图会把模拟视口拉到内容高度，100dvh 跟着一起长，所以图上永远看不出裁剪；
* 对比度审计读的是计算样式的颜色，被裁出视野不影响颜色。

所以这里不测样式文本，测**几何**：拿一个真实的手机视口，问每个滚动容器"你装得下
你的内容吗"。这是唯一能抓住这类失败的问法——任何一次 CSS 改动都可能把它带回来。
"""

from __future__ import annotations

import json
import os
import re
import socket
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

from .helpers import read_stylesheet

import pytest

ROOT = Path(__file__).resolve().parents[2]
STATIC = ROOT / "backend" / "static"
PAGES = ["/", "/elder", "/family", "/care", "/trust", "/judge"]

# 允许的余量：亚像素舍入和 1px 边框。超过这个就是真的看不到了。
SLACK_PX = 4


# --- 先用静态检查钉住意图，不需要浏览器 ---------------------------------------


def test_only_the_conversation_screen_opts_into_the_frame():
    """视口裁剪必须是显式 opt-in，且只有老人端会话屏 opt in。

    判断只看规则**自己**的花括号内容。第一版是拿选择器回到全文里 `css.index()`
    再往后看 400 个字符——把 bug 原样放回去时这个测试没抓住，因为 `main.shell`
    的首次出现在文件的另一处。规则文本已经在手里了，就不该再去猜它在哪。
    """
    # 先剥注释。这条断言曾经在**一段注释**上报红：那段注释解释的正是为什么某一处要
    # 解除 `overflow: hidden`，于是它同时含有 "overflow: hidden" 和 "max-height"
    # 两个字样，被当成了一条声明。一个把注释读成声明的检查，既会假红，也会被一段
    # 措辞恰好的注释骗过去。`test_design_rulers.py` 因为同一个原因早就在剥注释了。
    css = re.sub(r"/\*.*?\*/", "", read_stylesheet(), flags=re.S)
    for selector, body in re.findall(r"([^\n{}]*?)\s*\{([^{}]*)\}", css):
        if "overflow: hidden" not in body or "max-height" not in body:
            continue
        sel = selector.strip()
        assert "app-frame" in sel, (
            f"选择器 {sel!r} 同时设了 max-height 和 overflow:hidden，却没有限定到 "
            ".app-frame——这正是把 index/family/care/trust/judge 首屏以下全裁掉的写法"
        )

    framed = [p.name for p in STATIC.glob("*.html") if "app-frame" in p.read_text(encoding="utf-8")]
    assert framed == ["elder.html"], f"只有老人端会话屏该用定高框架，实际：{framed}"


def test_scrolling_pages_clear_the_home_gesture_area():
    css = read_stylesheet()
    assert "main.shell:not(.app-frame)" in css, (
        "滚动页面的底部留白必须排除定高框架，否则框架会把自己顶出裁剪线"
    )


def test_stylesheet_has_no_unclosed_comments():
    """1451 行那次，一个注释块提前 `*/` 了，后面十行正文变成了裸的 CSS。

    浏览器的错误恢复会把它当成选择器前缀一路吃到下一个 `{`，于是紧跟着的那条规则
    被整条丢掉——不报错，不告警，只是静静地不生效。
    """
    css = read_stylesheet()
    stripped = re.sub(r"/\*.*?\*/", "", css, flags=re.S)
    assert "*/" not in stripped, "有多余的 `*/`：某个注释块提前结束了，后面的正文成了裸 CSS"
    assert "/*" not in stripped, "有未闭合的 `/*`"


# --- 再用真实视口测几何 -------------------------------------------------------


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
  const bad = [];
  // Every element that declares itself a scroll container, plus the document.
  const boxes = [document.scrollingElement, ...document.querySelectorAll('*')];
  for (const el of boxes) {
    if (!el) continue;
    const cs = getComputedStyle(el);
    const clips = cs.overflowY === 'hidden' || cs.overflowY === 'clip';
    if (!clips) continue;
    const lost = el.scrollHeight - el.clientHeight;
    if (lost > SLACK) {
      bad.push({
        tag: el.tagName.toLowerCase(),
        cls: (el.className || '').toString().slice(0, 40),
        lost,
      });
    }
  }
  return JSON.stringify(bad);
})()
"""


def test_no_page_clips_its_own_content_at_390x844(tmp_path):
    """真实 390x844 视口下，任何声明了 overflow:hidden 的盒子都不许装不下自己的内容。

    数据库和 Chrome profile 都放 tmp_path：放进 backend/data 会被发布卫生检查当成
    残留产物，而且 Windows 上 SQLite 还握着文件句柄时删不掉。
    """
    chrome = _chrome()
    if not chrome:
        pytest.skip("找不到 Chrome，跳过真实视口测量")
    try:
        import websocket  # type: ignore
    except ImportError:
        pytest.skip("缺少 websocket-client")

    sys.path.insert(0, str(ROOT / "backend" / "scripts"))
    import shoot_pages  # type: ignore

    port = _free_port()
    env = {
        **os.environ,
        "PYTHONPATH": str(ROOT / "backend"),
        "YOUHUO_DEMO_MODE": "true",
        "YOUHUO_DB_PATH": str(tmp_path / "reach_probe.db"),
    }
    server = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "youhuo.api:app", "--host", "127.0.0.1", "--port", str(port)],
        cwd=str(ROOT / "backend"), env=env,
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    cdp_port = _free_port()
    browser_proc = subprocess.Popen(
        [chrome, "--headless=new", "--disable-gpu", "--no-sandbox", "--hide-scrollbars",
         f"--remote-debugging-port={cdp_port}", "--remote-allow-origins=*",
         f"--user-data-dir={tmp_path / 'profile'}", "about:blank"],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    try:
        base = f"http://127.0.0.1:{port}"
        for _ in range(60):
            try:
                urllib.request.urlopen(base + "/health", timeout=2)
                break
            except Exception:
                time.sleep(0.5)
        else:
            pytest.skip("后端没起来")

        ws_url = None
        for _ in range(60):
            try:
                with urllib.request.urlopen(f"http://127.0.0.1:{cdp_port}/json/version", timeout=2) as r:
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
        tab.send("Runtime.enable")
        tab.send("Emulation.setDeviceMetricsOverride",
                 width=390, height=844, deviceScaleFactor=3, mobile=True)

        failures: list[str] = []
        for page in PAGES:
            tab.send("Page.navigate", url=base + page)
            time.sleep(2.2)
            out = tab.send(
                "Runtime.evaluate",
                expression=PROBE.replace("SLACK", str(SLACK_PX)),
                returnByValue=True,
            )
            for box in json.loads(out["result"]["value"]):
                # The conversation list is *meant* to scroll inside the frame; it
                # declares overflow-y:auto, so it never shows up here. Anything
                # that does show up is content a thumb cannot reach.
                failures.append(f"{page} 的 <{box['tag']} class={box['cls']!r}> 裁掉了 {box['lost']}px")
        assert not failures, "手机上这些内容摸不到：\n  " + "\n  ".join(failures)
    finally:
        for proc in (browser_proc, server):
            proc.terminate()
            # Wait: terminate() only signals. On Windows the child still holds
            # the SQLite file and the profile directory, so returning here would
            # leave tmp_path undeletable and fail teardown instead of the test.
            try:
                proc.wait(timeout=15)
            except subprocess.TimeoutExpired:
                proc.kill()


# --- 打字这条退路必须永远在首屏 -----------------------------------------------

#: 判据不是"好看"，是"不滚动就能看见"。
#:
#: 老人端的语音是首选，打字是**唯一的退路**：Web Speech 在 Firefox 上不存在，在
#: 权限被拒、没有麦克风、网络不好的时候都会失败。那些时候输入框是她进入这个产品的
#: 唯一入口。够不到就等于这个功能不存在。
#:
#: 这七个视口不是随手挑的：前三个是原来就过的（证明这条断言不是只在新代码上成立），
#: 后四个是量出来失败的——最糟的一格是**把手机横过来**，输入行在首屏外 522px。
REACH_VIEWPORTS = [
    (390, 844, "iPhone 14 竖"),
    (320, 568, "iPhone SE 竖"),
    (768, 1024, "iPad 竖"),
    (1024, 768, "iPad 横"),
    (1280, 800, "笔记本"),
    (844, 390, "iPhone 14 横"),
    (667, 375, "iPhone SE 横"),
]

REACH_PROBE = r"""
(() => {
  const el = document.querySelector('#text');
  if (!el) return JSON.stringify({missing: true});
  const cs = getComputedStyle(el);
  const r = el.getBoundingClientRect();
  return JSON.stringify({
    top: Math.round(r.top), bottom: Math.round(r.bottom),
    h: Math.round(r.height), w: Math.round(r.width),
    vh: innerHeight,
    // 在屏内但被别的东西盖住也算够不到。取输入框中心点做命中测试。
    hit: (() => {
      const x = Math.round(r.left + r.width / 2);
      const y = Math.round(r.top + r.height / 2);
      if (y < 0 || y >= innerHeight) return 'offscreen';
      const top = document.elementFromPoint(x, y);
      return top === el || el.contains(top) ? 'ok' : (
        top ? `${top.tagName.toLowerCase()}.${(top.className || '').toString().slice(0, 24)}` : 'none');
    })(),
    display: cs.display, visibility: cs.visibility,
  });
})()
"""


def test_the_typing_route_is_in_the_first_screen_on_every_viewport(tmp_path):
    """七个视口下，`#text` 都必须整个在首屏里，而且中心点点得到。

    实测（改之前）：

        1024×768 iPad 横      首屏外 156px
        1280×800 笔记本       首屏外 138px
        844×390  手机横屏     首屏外 522px（麦克风也在外面，首屏上只有页头）

    根因是那一整套定高处理挂在 `max-width: 760px` 下。把手机转 90°，宽度变成 844，
    整套失效——而宽度从来不是这件事的判据：一屏够不够放下家具，问的是高度。

    "整个在首屏"而不是"露出一点"：一个只露出 4px 上边缘的输入框，对一位手抖、
    看不清小字的老人来说和不存在没有区别。
    """
    chrome = _chrome()
    if not chrome:
        pytest.skip("找不到 Chrome，跳过真实视口测量")
    try:
        import websocket  # type: ignore
    except ImportError:
        pytest.skip("缺少 websocket-client")

    sys.path.insert(0, str(ROOT / "backend" / "scripts"))
    import shoot_pages  # type: ignore

    port = _free_port()
    env = {
        **os.environ,
        "PYTHONPATH": str(ROOT / "backend"),
        "YOUHUO_DEMO_MODE": "true",
        "YOUHUO_DB_PATH": str(tmp_path / "reach_fold.db"),
    }
    server = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "youhuo.api:app", "--host", "127.0.0.1", "--port", str(port)],
        cwd=str(ROOT / "backend"), env=env,
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    cdp_port = _free_port()
    browser_proc = subprocess.Popen(
        [chrome, "--headless=new", "--disable-gpu", "--no-sandbox", "--hide-scrollbars",
         f"--remote-debugging-port={cdp_port}", "--remote-allow-origins=*",
         f"--user-data-dir={tmp_path / 'fold-profile'}", "about:blank"],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    try:
        base = f"http://127.0.0.1:{port}"
        for _ in range(60):
            try:
                urllib.request.urlopen(base + "/health", timeout=2)
                break
            except Exception:
                time.sleep(0.5)
        else:
            pytest.skip("后端没起来")

        ws_url = None
        for _ in range(60):
            try:
                with urllib.request.urlopen(f"http://127.0.0.1:{cdp_port}/json/version", timeout=2) as r:
                    ws_url = json.loads(r.read())["webSocketDebuggerUrl"]
                break
            except Exception:
                time.sleep(0.5)
        if not ws_url:
            pytest.skip("CDP 没起来")

        browser = shoot_pages.CDP(ws_url, websocket)
        failures: list[str] = []
        measured = 0
        for width, height, label in REACH_VIEWPORTS:
            target = browser.send("Target.createTarget", url="about:blank")["targetId"]
            with urllib.request.urlopen(f"http://127.0.0.1:{cdp_port}/json/list", timeout=5) as r:
                tabs = json.loads(r.read())
            tab = shoot_pages.CDP(
                next(t["webSocketDebuggerUrl"] for t in tabs if t["id"] == target), websocket
            )
            try:
                tab.send("Page.enable")
                # 在 navigate **之前**设视口，媒体查询才能从加载那一刻就生效。
                tab.send("Emulation.setDeviceMetricsOverride", width=width, height=height,
                         deviceScaleFactor=1, mobile=width < 768)
                tab.send("Page.navigate", url=base + "/elder")
                time.sleep(2.4)
                d = json.loads(tab.send("Runtime.evaluate", expression=REACH_PROBE,
                                        returnByValue=True)["result"]["value"])
            finally:
                tab.close()
                browser.send("Target.closeTarget", targetId=target)

            where = f"{label} {width}×{height}"
            if d.get("missing"):
                failures.append(f"{where}：页面上没有 #text，打字这条退路整个不见了")
                continue
            measured += 1
            if d["display"] == "none" or d["visibility"] == "hidden":
                failures.append(f"{where}：输入框被藏起来了（display={d['display']} "
                                f"visibility={d['visibility']}）")
            elif d["bottom"] > d["vh"]:
                failures.append(f"{where}：输入行在首屏外 {d['bottom'] - d['vh']}px")
            elif d["top"] < 0:
                failures.append(f"{where}：输入行上边缘在首屏之上 {-d['top']}px")
            elif d["hit"] != "ok":
                failures.append(f"{where}：输入框在屏内但点不到，盖在上面的是 {d['hit']}")

        # 量到的数量本身要断言。一个"跑了但一个视口都没量到"的检查和没有这个检查是
        # 一回事，而它在汇总里看起来一模一样地绿。
        assert measured == len(REACH_VIEWPORTS), (
            f"只量到 {measured}/{len(REACH_VIEWPORTS)} 个视口"
        )
        assert not failures, "打字这条退路够不到：\n  " + "\n  ".join(failures)
    finally:
        for proc in (browser_proc, server):
            proc.terminate()
            try:
                proc.wait(timeout=15)
            except subprocess.TimeoutExpired:
                proc.kill()
