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
from pathlib import Path

import websocket
# 本机请求一律绕开系统代理，理由见 localhttp.py（一次真实的
# 「服务未能启动」其实是代理把请求挂死了）。
from localhttp import open_local

ROOT = Path(__file__).resolve().parents[2]

#: Google 的门槛：<0.1 好，<0.25 要注意。这里按「好」判——留出余量，
#: 因为演示机比这台机器慢，慢机器上位移只会更明显。
BUDGET = 0.10

#: 每一格量几次，取最坏的那一次。
#:
#: 单次采样这道闸门**同时会漏和会误报**，2026-08-14 实测到同一份代码在连续几次
#: 运行里给出不同判决：
#:
#:     /family 390×844   一次 0.2613（源是 1370ms 的 nav.segmented），另外三次 0.0000
#:     /care   1440×900  同一条位移的时间戳在两次运行里是 524ms 和 327ms
#:
#: 那一天 `/care` 那条 **0.3687 的真回归**（我删掉一条 CSS 规则造成的）差一点被当成
#: 抖动放过；而干净的代码也报过一次红，逼人去查一个不存在的缺陷。
#:
#: **不靠调阈值解决**——调高会漏真回归，调低会更常误报，那只是选择要哪一种错。
#: 位移由异步内容的到达时机决定，同一份代码的分布本来就有尾巴，所以判据取三次里
#: 最坏的一次：任何一次超预算都算超。
#:
#: **它不保证抓到罕见的尖峰，这一点要说清楚。** 那条 0.2613 在后来的三次采样里
#: 一次都没再现（`/family 390×844` 三次全 0.0000）。三次只是把抓到尾部事件的机会
#: 提高，不是把它变成必然。真正让这件事可管理的是下面那行**把每次采样都印出来**：
#: 一格里出现 0.0000 与 0.09 并存时，人看得见「这一格快要不稳」，
#: 而只印一个最大值会把那件事藏起来。
#:
#: **怎么读那三个数**（变异证明时才发现这一点，写下来给下一个人）：
#:
#:     [0.3687 0.3687 0.3687]   三次一样 → 确定性回归，代码真的坏了
#:     [0.0000 0.2613 0.0000]   只有一次高 → 抖动，先重跑，别急着改布局
#:     [0.0505 0.0648 0.0505]   小幅摆动 → 这一格靠近边界了，值得留意
#:
#: 一个最大值分不出前两种，而它们该做的事完全相反。
#:
#: 代价是这道闸门的时间乘以三（实测 312s）。那是买「结论可信」的价钱，
#: 而一道结论不可信的闸门在做大改动时比没有闸门更糟：它会让人相信一个错的答案。
RUNS = 3

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
            open_local(f"{base}/health", timeout=1)
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
                with open_local(
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
                label = f"{route} {width}×{height}"

                # 同一格量 RUNS 次，取**最坏**的那一次。见 `RUNS` 的说明。
                samples: list[float] = []
                worst_data: dict | None = None
                for _ in range(RUNS):
                    # 每一轮都重新导航：CLS 是**载入期**指标，
                    # 不重新载入就只是把同一个数读第二遍。
                    call("Page.navigate", session, url="about:blank")
                    time.sleep(0.3)
                    call("Page.navigate", session, url=f"{base}{route}")
                    time.sleep(7)
                    raw = call("Runtime.evaluate", session, returnByValue=True, expression=(
                        "JSON.stringify({cls: +window.__cls.toFixed(4),"
                        " shifts: window.__shifts, ready: document.readyState})"
                    ))["result"]["value"]
                    data = json.loads(raw)
                    samples.append(data["cls"])
                    if worst_data is None or data["cls"] > worst_data["cls"]:
                        worst_data = data

                measured += 1
                score = max(samples)
                spread = f"[{' '.join(f'{s:.4f}' for s in samples)}]"
                if score > BUDGET:
                    worst = sorted(worst_data["shifts"], key=lambda s: -s["v"])[:2]
                    detail = "；".join(
                        f"{s['v']} @{s['t']}ms {'/'.join(s['who'])}" for s in worst)
                    failures.append(
                        f"{label} CLS {score:.4f} > {BUDGET}  {spread}  —  {detail}")
                else:
                    # 每一次的采样值都印出来，**让抖动本身可见**。
                    # 一格里出现 0.0000 与 0.09 并存，是「这一格快要不稳」的预警，
                    # 而只印一个最大值会把那件事藏起来。
                    jitter = "" if max(samples) - min(samples) < 0.01 else "  ← 抖"
                    print(f"  ok {label}  CLS {score:.4f} {spread}{jitter}")
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
