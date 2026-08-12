"""Screenshot the pages at real device viewports, over CDP.

`chrome --headless --window-size=390,844 --screenshot` does NOT give a 390px
layout: headless resolves its own viewport (measured at 512px here) and then
crops the image to the window size, so the capture looks like a wide layout with
its right edge sliced off. That artifact is indistinguishable from a real overflow
bug, which makes it worse than useless for judging a mobile design.

`Emulation.setDeviceMetricsOverride` is the only reliable way, and this project
already drives Chrome that way for the contrast audit, so the pattern is proven.

    python backend/scripts/shoot_pages.py http://127.0.0.1:8041 F:/优活/shots

**整页截图里的底部固定家具会看起来在切内容。**

`captureBeyondViewport` 把文档整高画出来，而 `position: fixed` 的元素画在**视口**
底边，不是文档底边。于是一条钉底的标签栏会落在真实页底之上（实测 /family：文档
893 CSS px、视口 844，栏压在 844 处，盖住了下面 49px 的内容），看起来像把内容
齐腰切断了。

这一条害过一次：视觉复审据此报了一个 P0「内容被 Tab 栏切断」，而逐项量下来
——滚动容器是 document、预留的 76px 一直生效、滚到底之后最后一张卡到栏顶还有
32px、栏本来就是不透明的——布局完全正确。按那个误诊去加 padding，会重新造出
pages.css 里明确记着"已经删掉过一次"的幽灵空白。

六个带标签栏的页面全部受影响。要判断底部是不是真的被切，看**首屏**那一张
（不带 `-full`），或者直接量 `getBoundingClientRect()`，不要看整页图。
"""

from __future__ import annotations

import base64
import json
import os
import shutil
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

#: 端口在运行时向系统要，不写死——见 `_free_port()` 的说明。
DEVTOOLS_PORT = 0

#: Real devices worth checking, plus the smallest phone still in wide use.
#:
#: The two 鸿蒙 form factors matter for this project specifically: the target
#: platform ships foldables, and the layout switches at 760px — a folded Mate X
#: is just under it and an unfolded one just over, so the fold crosses the
#: breakpoint. Testing only 390 and 1360 never exercises that transition.
VIEWPORTS = {
    "narrow-320": (320, 568, 2),      # 最窄的在售安卓机，也是唯一暴露过折行的一档
    "iphone-se": (375, 667, 2),
    "iphone-14": (390, 844, 3),
    "pixel-7": (412, 915, 3),
    "fold-closed": (344, 882, 3),    # Mate X5 外屏，比 iPhone SE 还窄
    "fold-open": (720, 748, 3),       # Mate X5 内屏展开，仍在 760px 断点之下
    "tablet": (800, 1200, 2),         # MatePad 竖屏，刚过断点
    "tablet-landscape": (1024, 768, 2),   # MatePad 横屏：短而宽，没有别的视口覆盖
    "desktop": (1360, 900, 1),
}

#: 320x568 是唯一在这一档上发现过真缺陷的视口（可信页的分区标签折行、老人端
#: 对话区被固定家具挤到不足 40px），也是最窄的在售安卓机。
#:
#: 任务书列的 360x800 / 393x852 / 430x932 与现有的 375 / 390 / 412 相差几个像素，
#: 加进来只会让每轮多跑一倍时间而带不来新信息，所以**没有**加——这一条是判断，
#: 可以推翻。
#: /stage 是桌面演示舞台：手机框 + 框内真实 App。它排在最后，因为它只在宽视口下
#: 有意义——窄屏上它自己会退成直接用应用本身。
PAGES = ["/elder", "/family", "/care", "/trust", "/judge", "/", "/stage"]

#: 量"有没有内容够不着"，而不只是 `documentElement.scrollWidth`。
#:
#: 只看 scrollWidth 会漏掉整整一类：`position: fixed` 的元素不计入文档滚动尺寸。
#: 给底部标签栏加 `min-width: 1200px` 做变异，scrollWidth 纹丝不动仍是 390——而它
#: 右边那两个标签在手机上已经出界、永远点不到。所以这里逐个元素量右边缘。
#:
#: 横向滚动容器里的子元素要排除：首页那条创新点横滚带就是**故意**让内容伸出去的，
#: 露出半个卡片正是"还能往右滑"的提示。判据是祖先链上有没有 overflow-x: auto|scroll。
OVERFLOW_PROBE = """
(() => {
  const inScroller = (el) => {
    for (let p = el.parentElement; p; p = p.parentElement) {
      const ox = getComputedStyle(p).overflowX;
      if (ox === 'auto' || ox === 'scroll') return true;
    }
    return false;
  };
  const name = (el) => {
    const cls = typeof el.className === 'string' && el.className.trim()
      ? '.' + el.className.trim().split(/\\s+/).join('.') : '';
    return el.tagName.toLowerCase() + (el.id ? '#' + el.id : '') + cls;
  };
  const offscreen = [];
  document.querySelectorAll('body *').forEach(el => {
    const r = el.getBoundingClientRect();
    if (r.width < 1 || r.height < 1) return;
    if (r.right <= innerWidth + 1) return;
    if (inScroller(el)) return;
    offscreen.push(name(el) + ' 右边缘 ' + Math.round(r.right) + ' > ' + innerWidth);
  });
  return JSON.stringify({
    vw: innerWidth,
    sw: document.documentElement.scrollWidth,
    sh: document.documentElement.scrollHeight,
    offscreen: offscreen.slice(0, 4),
  });
})()
"""


#: `_free_port()` 已经发出去的端口。见那个函数的说明。
_ISSUED_PORTS: set[int] = set()


def _free_port() -> int:
    """向系统要一个此刻空闲、而且这一进程内没发过的端口。

    这里原先是一个写死的端口号。两份检查同时跑（比如主进程和一个并发的 agent）会
    连到同一个 DevTools 端点上，而失败模式有两种：好的那种是
    `ConnectionResetError: [WinError 10054]`；**坏的那种是它不报错**——一个实例的
    `Runtime.evaluate` 落进另一个实例的标签页，点击遍历因此少按几个控件，然后报一个
    更小的控件数，看起来正好像一次覆盖回退。

    这些脚本自己拉起浏览器、自己连上去，端口号只需要在这一次运行里成立，
    所以没有理由写死它。

    **但"bind 0、读号、close"连调两次会拿到同一个号。** 操作系统完全可以把刚释放的
    临时端口立刻再发一遍——于是 uvicorn 占了它，Chrome 再也 bind 不上，DevTools 起不来。
    第一版就是这样，`check_page_runtime` 改成动态端口之后直接 SKIP 了。
    所以记住这一进程内发过的号，撞上就重取。

    **不要"保持 socket 打开"来占位**——我试过，那样端口对自己也是锁着的：
    uvicorn 随后 bind 同一个号会失败，检查报 `server did not start`。
    一个为了防冲突加的保险，把服务器挡在了门外。去重这一半就够用：
    第一个号被 uvicorn 立刻占住之后，操作系统本来也不会再发它。
    """
    import socket
    for _ in range(50):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.bind(("127.0.0.1", 0))
            port = sock.getsockname()[1]
        if port in _ISSUED_PORTS:
            continue
        _ISSUED_PORTS.add(port)
        return port
    raise RuntimeError("连 50 次都没要到一个没发过的端口")


class CDP:
    def __init__(self, url: str, websocket_mod) -> None:
        self.ws = websocket_mod.create_connection(url, timeout=60)
        self.n = 0

    def send(self, method: str, **params):
        self.n += 1
        self.ws.send(json.dumps({"id": self.n, "method": method, "params": params}))
        while True:
            message = json.loads(self.ws.recv())
            if message.get("id") == self.n:
                if "error" in message:
                    raise RuntimeError(f"{method}: {message['error']}")
                return message.get("result", {})

    def close(self) -> None:
        try:
            self.ws.close()
        except Exception:
            pass


def find_chrome() -> str | None:
    for candidate in (
        r"C:\Program Files\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
        "/usr/bin/google-chrome",
        "/usr/bin/chromium",
    ):
        if Path(candidate).exists():
            return candidate
    return None


def main() -> int:
    # 见 `_free_port()`。这个脚本连的是外部服务器（命令行给的 base），
    # 所以只有 DevTools 端口需要取。
    global DEVTOOLS_PORT
    DEVTOOLS_PORT = _free_port()
    base = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8041"
    out_dir = Path(sys.argv[2] if len(sys.argv) > 2 else "shots")
    args = sys.argv[3:]
    # `dark` / `light` 作为一个可选的位置参数混在设备名里，用完就从设备列表里摘掉。
    scheme = next((a for a in args if a in ("dark", "light")), None)
    only = [a for a in args if a not in ("dark", "light")] or None
    out_dir.mkdir(parents=True, exist_ok=True)

    try:
        import websocket  # type: ignore
    except ImportError:
        print("需要 websocket-client：pip install websocket-client")
        return 1
    chrome = find_chrome()
    if not chrome:
        print("找不到 Chrome / Edge")
        return 1

    # A fresh profile every run, and this is not optional.
    #
    # The app registers a service worker that caches the shell — that is the
    # point of it. With a persistent --user-data-dir the worker survives between
    # runs and serves the *previous* build's HTML and CSS, so the tool renders a
    # version of the app that no longer exists. It has produced confidently
    # wrong readings more than once: a set of freshly injected icons that
    # "weren't rendering" (they were, in a file the browser refused to fetch),
    # and before that a whole round of judging stale styles. A screenshot tool
    # that can show you yesterday's build is not a measurement, it is a rumour.
    profile = Path(os.environ.get("TEMP", "/tmp")) / "youhuo-shots"
    shutil.rmtree(profile, ignore_errors=True)

    proc = subprocess.Popen(
        [chrome, "--headless=new", "--disable-gpu", "--no-sandbox", "--hide-scrollbars",
         f"--remote-debugging-port={DEVTOOLS_PORT}", "--remote-allow-origins=*",
         f"--user-data-dir={profile}", "about:blank"],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    try:
        ws_url = None
        for _ in range(60):
            try:
                with urllib.request.urlopen(
                    f"http://127.0.0.1:{DEVTOOLS_PORT}/json/version", timeout=2
                ) as r:
                    ws_url = json.loads(r.read())["webSocketDebuggerUrl"]
                break
            except Exception:
                time.sleep(0.5)
        if not ws_url:
            print("devtools 没起来")
            return 1

        browser = CDP(ws_url, websocket)
        written = []
        # 每一组拍**两张**（首屏 + 全页），所以要分开数。
        #
        # 汇总行原先印 `len(written)`——也就是组数——而磁盘上是它的两倍。一个自己
        # 少报一半的仪器，你没法拿它的输出去比较两次运行："这次 108 张"和"上次
        # 216 个文件"看起来像两件不同的事，实际是同一件。
        files: list[Path] = []
        overflow: list[str] = []
        # 不指定模式就明暗都扫。
        #
        # 深色此前要单独跑一次，也就是说"全尺寸截图"这件事默认只出了一半——而
        # 对比度审计读的是计算色，12/12 通过只说明色值达标，不说明看起来是对的：
        # 一个背景没跟着换、或者一处写死的白底，色值检查全都发现不了。
        schemes = [scheme] if scheme else ["light", "dark"]
        for mode in schemes:
          for device, (width, height, dsf) in VIEWPORTS.items():
            if only and device not in only:
                continue
            for page in PAGES:
                target = browser.send("Target.createTarget", url="about:blank")["targetId"]
                with urllib.request.urlopen(
                    f"http://127.0.0.1:{DEVTOOLS_PORT}/json/list", timeout=5
                ) as r:
                    tabs = json.loads(r.read())
                tab = CDP(
                    next(t["webSocketDebuggerUrl"] for t in tabs if t["id"] == target), websocket
                )
                try:
                    tab.send("Page.enable")
                    tab.send("Runtime.enable")
                    # 深色模式必须能真的看一眼。对比度审计读的是计算出来的颜色，
                    # 12/12 通过只说明色值达标，不说明看起来是对的——一个背景没
                    # 跟着换、或者一处写死的白底，色值检查全都发现不了。
                    tab.send("Emulation.setEmulatedMedia", features=[
                        {"name": "prefers-color-scheme", "value": mode}
                    ])
                    # mobile=True so `width=device-width` and the safe-area /
                    # touch media queries behave as they do on a real handset.
                    tab.send("Emulation.setDeviceMetricsOverride", width=width, height=height,
                             deviceScaleFactor=dsf, mobile=device != "desktop")
                    tab.send("Page.navigate", url=base + page)
                    time.sleep(3.0)          # settle fonts, layout and first paint
                    # 先确认拍到的是我们的页面。
                    #
                    # 服务没起的时候这个脚本会拍下 42 张 Chrome 的
                    # ERR_CONNECTION_REFUSED 错误页，然后报告"42 张截图，无横向溢出"
                    # ——错误页当然不溢出，上面什么都没有。溢出探针量的是"这一页有没有
                    # 超宽"，不是"这一页是不是这个应用"，于是它一路绿到底，而目录里
                    # 躺着 42 张看起来像成功的图。
                    #
                    # 判据是"我们的设计令牌真的生效了"，不是"有没有某个 id"——六个
                    # 页面的骨架不一样（只有两页有 `main#main`），拿骨架当判据会把三个
                    # 好页面判成加载失败。令牌解析得出来，说明四层 CSS 真的挂上了。
                    ok = tab.send("Runtime.evaluate", returnByValue=True, expression=(
                        "document.title.includes('优活') && !!getComputedStyle("
                        "document.documentElement).getPropertyValue('--ink').trim()"
                    ))["result"].get("value")
                    if not ok:
                        title = tab.send("Runtime.evaluate", returnByValue=True,
                                         expression="document.title")["result"].get("value")
                        overflow.append(
                            f"{device}{page} 加载的不是优活页面（标题「{title}」）"
                            f"——{base} 上有服务在跑吗？"
                        )
                        continue
                    measured = tab.send("Runtime.evaluate", expression=OVERFLOW_PROBE,
                                        returnByValue=True)["result"]["value"]
                    # 量到了就要判。
                    #
                    # 这几个数以前只是打印出来，需要有人自己去看——于是没人看。横向
                    # 溢出在截图上是"右边被切掉一点"，在手机上是整页能左右晃、正文有
                    # 一半永远够不着；而对比度检查读的是计算色，溢出不改变任何一个
                    # 元素的颜色，它会一路绿到底。这正是这个项目里"仪器测的不是你
                    # 关心的那件事"的原型案例。
                    box = json.loads(measured)
                    if box["sw"] > box["vw"]:
                        overflow.append(
                            f"{device}{page} 文档横向溢出 {box['sw'] - box['vw']}px"
                            f"（视口 {box['vw']}，内容 {box['sw']}）"
                        )
                    for item in box["offscreen"]:
                        overflow.append(f"{device}{page} 元素右边缘出界：{item}")
                    stem = f"{device}{page.replace('/', '-') or '-home'}-{mode}"
                    # The first screen alone, which is what decides whether the
                    # app screen is complete without scrolling. Judging that from
                    # a 2400px full-page capture is impossible.
                    #
                    # This comes FIRST, and the metrics are re-asserted before
                    # it, both deliberately. captureBeyondViewport=True expands
                    # the viewport internally to the content height and does not
                    # reliably restore it, so a first-screen capture taken after
                    # it is the top 844px of a 2288px-tall viewport. Everything
                    # position:fixed then sits at the *bottom of that*, i.e. off
                    # the crop entirely — the bottom tab bar was invisible in
                    # every first-screen shot while being laid out correctly
                    # (measured: fixed, bottom 0, rect 787-844). A screenshot
                    # tool that silently drops fixed furniture is worse than no
                    # tool, because it is the pinned bars and sheets that decide
                    # whether a screen reads as an app.
                    first = tab.send(
                        "Page.captureScreenshot", format="png", captureBeyondViewport=False
                    )
                    files.append(out_dir / f"{stem}.png")
                    files[-1].write_bytes(base64.b64decode(first["data"]))
                    # ...then the whole layout, whose expansion no longer matters.
                    tab.send("Emulation.setDeviceMetricsOverride", width=width, height=height,
                             deviceScaleFactor=dsf, mobile=device != "desktop")
                    full = tab.send(
                        "Page.captureScreenshot", format="png", captureBeyondViewport=True
                    )
                    files.append(out_dir / f"{stem}-full.png")
                    files[-1].write_bytes(base64.b64decode(full["data"]))
                    written.append(f"{stem}  {measured}")
                finally:
                    tab.close()
                    browser.send("Target.closeTarget", targetId=target)
        print("\n".join(written))
        if overflow:
            print(f"\nFAIL shoot_pages: {len(overflow)} 处横向溢出")
            for item in overflow:
                print(f"  {item}")
            return 1
        # 报告磁盘上真的有什么，不是"我打算写什么"。
        #
        # `write_bytes` 不抛异常只说明调用返回了。一张 0 字节的 PNG 在文件列表里
        # 和一张好图长得一样，而它正是"服务没起、拍到错误页"那一类失败的样子——
        # 这个脚本的注释里已经记着一次 42 张 ERR_CONNECTION_REFUSED 被报成成功。
        empty = [f.name for f in files if not f.exists() or f.stat().st_size == 0]
        if empty:
            print(f"\nFAIL shoot_pages: {len(empty)} 个文件是空的或没落盘：{empty[:6]}")
            return 1
        print(f"\nOK shoot_pages: {len(written)} 组 × 2（首屏 + 全页）= "
              f"{len(files)} 个文件，共 {sum(f.stat().st_size for f in files) // 1024} KiB，"
              f"无横向溢出")
        return 0
    finally:
        proc.terminate()


if __name__ == "__main__":
    raise SystemExit(main())
