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
VIEWPORTS = {
    "iphone-se": (375, 667, 2),
    "iphone-14": (390, 844, 3),
    "pixel-7": (412, 915, 3),
    "desktop": (1360, 900, 1),
}
PAGES = ["/elder", "/family", "/care", "/trust", "/judge", "/"]


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
    only = sys.argv[3:] or None
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
                    # mobile=True so `width=device-width` and the safe-area /
                    # touch media queries behave as they do on a real handset.
                    tab.send("Emulation.setDeviceMetricsOverride", width=width, height=height,
                             deviceScaleFactor=dsf, mobile=device != "desktop")
                    tab.send("Page.navigate", url=base + page)
                    time.sleep(3.0)          # settle fonts, layout and first paint
                    measured = tab.send("Runtime.evaluate", expression=(
                        "JSON.stringify({vw:innerWidth,"
                        "sw:document.documentElement.scrollWidth,"
                        "sh:document.documentElement.scrollHeight})"
                    ), returnByValue=True)["result"]["value"]
                    stem = f"{device}{page.replace('/', '-') or '-home'}"
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
        return 0
    finally:
        proc.terminate()


if __name__ == "__main__":
    raise SystemExit(main())
