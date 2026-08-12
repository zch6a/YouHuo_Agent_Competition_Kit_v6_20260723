"""载入期不许跳。

七个页面里有五个是"先渲染一行占位文字，等接口回来再 `replaceChildren` 整块内容"。
中间没有任何高度预留，下面的东西就被整体顶下去——评委在读一句话，那句话跑了。

实测（1440×900，改之前）：

    /trust    CLS 0.2068     `#receipt` 由 235px 长到 502px，下面两行被顶出视口
    /family   CLS 0.1300     日报区两跳，`nav.segmented` 下移 42px

0.1 是 Google 的「差」阈值，这两个是它的一到两倍——而它们恰好是评委会打开的两页。

**为什么以前从来没被发现**：手机视口上这两处都测出 0.0000。不是它不跳，是位移发生
在首屏折线**以下**，不计入 CLS。这个项目的截图矩阵和点击遍历都以手机为主，
于是一个只在桌面显形的缺陷，在所有既有闸门下都是绿的。

## 判据

`PerformanceObserver({type: 'layout-shift'})`，跳过 `hadRecentInput`（用户自己点出来的
位移不算）。观察器必须在**文档创建时**就装好，用
`Page.addScriptToEvaluateOnNewDocument`——在 `Page.navigate` 之后再注入，早期条目已经
错过了，量出来会是一个漂亮的 0。这条闸门自己就能这样骗自己，所以下面有一条自检。
"""
from __future__ import annotations

import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

import websocket

ROOT = Path(__file__).resolve().parents[2]

#: Google 的门槛：<0.1 好，<0.25 要注意。这里按「好」判——留出余量，
#: 因为演示机比这台机器慢，慢机器上位移只会更明显。
BUDGET = 0.10

#: 桌面必测：这两个缺陷只在桌面显形。手机一起测，防止修桌面把手机弄坏。
VIEWPORTS = [(1440, 900), (390, 844)]
ROUTES = ["/", "/elder", "/family", "/care", "/trust", "/judge", "/stage"]

OBSERVER = """
window.__cls = 0; window.__shifts = [];
new PerformanceObserver((list) => {
  for (const e of list.getEntries()) {
    if (e.hadRecentInput) continue;
    window.__cls += e.value;
    window.__shifts.push({
      v: +e.value.toFixed(4), t: Math.round(e.startTime),
      who: (e.sources || []).map(s => {
        const n = s.node;
        if (!n || !n.tagName) return '?';
        return n.tagName.toLowerCase() + (n.id ? '#' + n.id : '')
          + (n.className && typeof n.className === 'string'
             ? '.' + n.className.trim().split(/\\s+/).join('.') : '');
      }).slice(0, 2),
    });
  }
}).observe({type: 'layout-shift', buffered: true});
"""


def _chrome() -> str:
    for candidate in (
        r"C:\Program Files\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
        "/usr/bin/google-chrome", "/usr/bin/chromium",
    ):
        if Path(candidate).is_file():
            return candidate
    print("SKIP layout_stability: 这台机器上没有 Chrome/Edge")
    raise SystemExit(0)


def _free_port() -> int:
    """绑到 0 拿一个空闲端口，**立刻放开**。

    握着不放是这个项目踩过的坑：为了防重复而按住 socket，结果 uvicorn 绑不上，
    报成「server did not start」。
    """
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def main() -> int:
    chrome = _chrome()
    port = _free_port()
    # 数据库和浏览器 profile **都不许落在仓库里**。
    #
    # 第一版把 profile 写进 `ROOT/.cache/cls-profile`、又没给 `YOUHUO_DB_PATH`，
    # 于是这道闸门自己往被检查的仓库里拉了 6 个 `.db` 和一个 `data/youhuo.db`，
    # 当场被 `check_artifacts_v6` 的 `leaked_artifacts` 抓住——一个检查代码干不干净的
    # 工具，把仓库弄脏了。`check_focus_geometry.py` 早就是这么写的，照它来。
    workdir = Path(tempfile.mkdtemp(prefix="youhuo-cls-"))
    env = {**os.environ, "PYTHONPATH": str(ROOT / "backend"),
           "YOUHUO_DB_PATH": str(workdir / "cls.db")}
    server = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "youhuo.api:app", "--host", "127.0.0.1",
         "--port", str(port), "--app-dir", "backend"],
        cwd=ROOT, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    base = f"http://127.0.0.1:{port}"
    for _ in range(60):
        try:
            urllib.request.urlopen(f"{base}/health", timeout=1)
            break
        except Exception:
            time.sleep(0.5)
    else:
        server.terminate()
        shutil.rmtree(workdir, ignore_errors=True)
        print("FAIL layout_stability: 服务器没起来")
        return 1

    cdp_port = _free_port()
    profile = workdir / "profile"
    browser = subprocess.Popen(
        [chrome, "--headless=new", f"--remote-debugging-port={cdp_port}",
         "--remote-allow-origins=*", f"--user-data-dir={profile}",
         "--no-first-run", "--no-default-browser-check", "about:blank"],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    failures: list[str] = []
    measured = 0
    try:
        ws_url = None
        for _ in range(40):
            try:
                with urllib.request.urlopen(
                        f"http://127.0.0.1:{cdp_port}/json/version", timeout=2) as response:
                    ws_url = json.loads(response.read())["webSocketDebuggerUrl"]
                break
            except Exception:
                time.sleep(0.4)
        if not ws_url:
            # 第 18.3 节：Chrome 在、DevTools 连不上，必须是 FAIL 不是 SKIP。
            print("FAIL layout_stability: Chrome 在，但 DevTools 连不上")
            return 1

        ws = websocket.create_connection(ws_url, timeout=90)
        counter = [0]

        def call(method: str, session: str | None = None, **params):
            counter[0] += 1
            message = {"id": counter[0], "method": method, "params": params}
            if session:
                message["sessionId"] = session
            ws.send(json.dumps(message))
            while True:
                got = json.loads(ws.recv())
                if got.get("id") == counter[0]:
                    if "error" in got:
                        raise RuntimeError(got["error"])
                    return got.get("result", {})

        target = call("Target.createTarget", url="about:blank")["targetId"]
        session = call("Target.attachToTarget", targetId=target, flatten=True)["sessionId"]
        call("Runtime.enable", session)
        call("Page.enable", session)
        call("Page.addScriptToEvaluateOnNewDocument", session, source=OBSERVER)

        for route in ROUTES:
            for width, height in VIEWPORTS:
                call("Emulation.setDeviceMetricsOverride", session, width=width, height=height,
                     deviceScaleFactor=1, mobile=width < 761)
                call("Page.navigate", session, url=f"{base}{route}")
                time.sleep(7)
                raw = call("Runtime.evaluate", session, returnByValue=True, expression=(
                    "JSON.stringify({cls: +window.__cls.toFixed(4),"
                    " shifts: window.__shifts, ready: document.readyState})"
                ))["result"]["value"]
                data = json.loads(raw)
                measured += 1
                score = data["cls"]
                label = f"{route} {width}×{height}"
                if score > BUDGET:
                    worst = sorted(data["shifts"], key=lambda s: -s["v"])[:2]
                    detail = "；".join(
                        f"{s['v']} @{s['t']}ms {'/'.join(s['who'])}" for s in worst)
                    failures.append(f"{label} CLS {score:.4f} > {BUDGET}  —  {detail}")
                else:
                    print(f"  ok {label}  CLS {score:.4f}")
    finally:
        browser.terminate()
        server.terminate()
        time.sleep(0.5)   # 让两个进程先放开 profile 里的句柄，否则 Windows 上删不掉
        shutil.rmtree(workdir, ignore_errors=True)

    if measured != len(ROUTES) * len(VIEWPORTS):
        print(f"FAIL layout_stability: 只量到 {measured} 组，预期 "
              f"{len(ROUTES) * len(VIEWPORTS)} 组——没造出被测状态，这不是通过")
        return 1
    if failures:
        print(f"FAIL layout_stability: {len(failures)} 组超出预算")
        for line in failures:
            print(f"  {line}")
        return 1
    print(f"PASS layout_stability: {measured} 组（7 路由 × 2 视口）载入期 CLS 全部 < {BUDGET}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
