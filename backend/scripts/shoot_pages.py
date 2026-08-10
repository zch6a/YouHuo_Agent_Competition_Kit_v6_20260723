"""Screenshot the pages at real device viewports, over CDP.

`chrome --headless --window-size=390,844 --screenshot` does NOT give a 390px
layout: headless resolves its own viewport (measured at 512px here) and then
crops the image to the window size, so the capture looks like a wide layout with
its right edge sliced off. That artifact is indistinguishable from a real overflow
bug, which makes it worse than useless for judging a mobile design.

`Emulation.setDeviceMetricsOverride` is the only reliable way, and this project
already drives Chrome that way for the contrast audit, so the pattern is proven.

    python backend/scripts/shoot_pages.py http://127.0.0.1:8041 F:/优活/shots
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

DEVTOOLS_PORT = 9333

#: Real devices worth checking, plus the smallest phone still in wide use.
#:
#: The two 鸿蒙 form factors matter for this project specifically: the target
#: platform ships foldables, and the layout switches at 760px — a folded Mate X
#: is just under it and an unfolded one just over, so the fold crosses the
#: breakpoint. Testing only 390 and 1360 never exercises that transition.
VIEWPORTS = {
    "iphone-se": (375, 667, 2),
    "iphone-14": (390, 844, 3),
    "pixel-7": (412, 915, 3),
    "fold-closed": (344, 882, 3),    # Mate X5 外屏，比 iPhone SE 还窄
    "fold-open": (720, 748, 3),       # Mate X5 内屏展开，仍在 760px 断点之下
    "tablet": (800, 1200, 2),         # MatePad 竖屏，刚过断点
    "desktop": (1360, 900, 1),
}
PAGES = ["/elder", "/family", "/care", "/trust", "/judge", "/"]

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
        overflow: list[str] = []
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
                    if scheme:
                        tab.send("Emulation.setEmulatedMedia", features=[
                            {"name": "prefers-color-scheme", "value": scheme}
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
                    stem = f"{device}{page.replace('/', '-') or '-home'}"
                    if scheme:
                        stem = f"{stem}-{scheme}"
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
                    (out_dir / f"{stem}.png").write_bytes(base64.b64decode(first["data"]))
                    # ...then the whole layout, whose expansion no longer matters.
                    tab.send("Emulation.setDeviceMetricsOverride", width=width, height=height,
                             deviceScaleFactor=dsf, mobile=device != "desktop")
                    full = tab.send(
                        "Page.captureScreenshot", format="png", captureBeyondViewport=True
                    )
                    (out_dir / f"{stem}-full.png").write_bytes(base64.b64decode(full["data"]))
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
        print(f"\nOK shoot_pages: {len(written)} 张截图，无横向溢出")
        return 0
    finally:
        proc.terminate()


if __name__ == "__main__":
    raise SystemExit(main())
