"""每个页面在真实浏览器里加载一遍，断言运行时干净。

**为什么需要这个检查。**

`check_browser_js.py` 用的是 `node --check`，只解析、不执行。于是下面这行在它眼里
完全合法：

    const state = { elderToken: '', elderId: state.elderId };

`const` 在自己的初始化器里引用自己是暂时性死区，运行时抛
`ReferenceError: Cannot access 'state' before initialization`。它是脚本的第一条
语句，一抛整个文件不执行——`care.js` 和 `trust.js` 就是这样，两个页面上每一个按钮
都是死的，而 `/care` 正是核心创新①个性化基线的演示页。语法检查一直是绿的。

只解析不执行的检查，挡不住任何一个运行时错误。这个文件补的就是那一段：把页面真的
加载起来，然后问浏览器有没有抛东西。

    python backend/scripts/check_page_runtime.py

判定分三类：
  * 未捕获异常（`Runtime.exceptionThrown`）—— 失败；
  * `console.error` 与浏览器自己的 error 级日志 —— 失败；
  * 同源请求 4xx/5xx 或加载失败 —— 失败。

第三类同样是硬失败：一个 404 的图标或样式表在截图里可能看不出来，但它就是坏的。
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PORT = 8047
DEVTOOLS_PORT = 9337
BASE = f"http://127.0.0.1:{PORT}"

PAGES = ["/", "/elder", "/family", "/care", "/trust", "/judge"]

#: 页面加载后等多久再收网。首屏之后还有 `bootstrap()` 的登录、identity 的 provision
#: 和几个 GET，抛错往往发生在这一段而不是解析期。
SETTLE_SECONDS = 4.0

#: 每次点击后等多久。这些按钮背后是真实 HTTP 往返。
CLICK_SETTLE_SECONDS = 1.6

#: 不点的按钮。
#:
#: 只排除会把页面**导航走**的控件——一旦离开当前页，后面的点击就落在别的文档上，
#: 收集到的错误会张冠李戴。真正做事的按钮一个都不放过，包括 SOS 和限时破窗：
#: 它们是这个产品的安全路径，正因为危险才更需要每轮都真的走一遍。演示库是每次
#: 新建的临时文件，点坏了也只坏它自己。
SKIP_SELECTORS = "a, [data-sheet-open], [data-sheet-close], .back-link, .tab"


class CDP:
    """会把事件留下来的 CDP 连接。

    `shoot_pages.py` 里那个只等自己那条 id 的响应，顺手把事件全丢了——那对截图无所谓，
    对这里是全部内容。
    """

    def __init__(self, url: str, websocket_mod) -> None:
        self.ws = websocket_mod.create_connection(url, timeout=60)
        self.n = 0
        self.events: list[dict] = []

    #: 拆对话框用的固定 id。用一个不会和 self.n 撞上的大数，它的响应就会被读循环
    #: 当成"不是我等的那条"直接跳过，不干扰正在进行的 send。
    DIALOG_ID = 9_000_001

    def _keep_alive(self, message: dict) -> None:
        """记下事件；如果是原生对话框，立刻拆掉。

        `alert()` / `confirm()` 会挂起渲染进程，此后任何 `Runtime.evaluate` 都不会
        再返回——第一版这个检查就是这样卡死在 60 秒超时上的，而原因（family.js 里
        六处 `alert()`）从堆栈里完全看不出来。
        """
        if message.get("method") == "Page.javascriptDialogOpening":
            self.ws.send(json.dumps({
                "id": self.DIALOG_ID, "method": "Page.handleJavaScriptDialog",
                "params": {"accept": True},
            }))
        if "method" in message:
            self.events.append(message)

    def send(self, method: str, **params) -> dict:
        self.n += 1
        self.ws.send(json.dumps({"id": self.n, "method": method, "params": params}))
        while True:
            message = json.loads(self.ws.recv())
            if message.get("id") == self.n:
                if "error" in message:
                    raise RuntimeError(f"{method}: {message['error']}")
                return message.get("result", {})
            self._keep_alive(message)

    def drain(self, seconds: float) -> None:
        """收集这段时间里到达的事件。"""
        deadline = time.monotonic() + seconds
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                break
            self.ws.settimeout(remaining)
            try:
                message = json.loads(self.ws.recv())
            except Exception:
                break
            self._keep_alive(message)
        self.ws.settimeout(60)

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


def describe_exception(params: dict) -> str:
    details = params.get("exceptionDetails", {})
    exception = details.get("exception") or {}
    text = exception.get("description") or exception.get("value") or details.get("text")
    where = ""
    url = details.get("url")
    if url:
        where = f"  @ {url}:{details.get('lineNumber', 0) + 1}"
    return f"{text}{where}"


def describe_console(params: dict) -> str:
    parts = []
    for arg in params.get("args", []):
        parts.append(str(arg.get("value", arg.get("description", arg.get("type", "?")))))
    return " ".join(parts) or "(空 console.error)"


def collect(events: list[dict], page: str) -> list[str]:
    """把一页的事件翻成失败清单。"""
    problems: list[str] = []
    requests: dict[str, str] = {}

    for event in events:
        method = event.get("method")
        params = event.get("params", {})

        if method == "Runtime.exceptionThrown":
            problems.append(f"{page}  未捕获异常：{describe_exception(params)}")

        elif method == "Runtime.consoleAPICalled" and params.get("type") == "error":
            problems.append(f"{page}  console.error：{describe_console(params)}")

        elif method == "Log.entryAdded":
            entry = params.get("entry", {})
            if entry.get("level") == "error":
                url = entry.get("url", "")
                problems.append(f"{page}  浏览器日志：{entry.get('text', '')}  {url}".rstrip())

        elif method == "Network.requestWillBeSent":
            requests[params.get("requestId", "")] = params.get("request", {}).get("url", "")

        elif method == "Network.responseReceived":
            response = params.get("response", {})
            status = response.get("status", 0)
            url = response.get("url", "")
            if status >= 400 and url.startswith(BASE):
                problems.append(f"{page}  HTTP {status}：{url[len(BASE):]}")

        elif method == "Page.javascriptDialogOpening":
            # 原生 alert()/confirm() 在装到主屏的 PWA 里会弹出带域名的系统弹窗，
            # 而且会冻住整页。对这个受众来说这是最糟的一种反馈方式：一位老人的
            # 家属在手机上看到一个"127.0.0.1 显示"的灰框，只能确定出事了。
            problems.append(
                f"{page}  弹出了原生对话框（{params.get('type')}）：{params.get('message', '')}"
            )

        elif method == "Network.loadingFailed":
            url = requests.get(params.get("requestId", ""), "?")
            # 取消的请求不算失败（导航打断、service worker 接管都会走这里）。
            if not params.get("canceled") and url.startswith(BASE):
                problems.append(
                    f"{page}  请求失败：{url[len(BASE):]}  {params.get('errorText', '')}"
                )

    return problems


def check_sprite_icons(tab: "CDP", page: str, failures: list[str]) -> None:
    """标签栏图标引用的是外部 sprite，必须确认它真的画出来了。

    这五个图标此前在五个 HTML 里逐字复制，改成 `<use href="/static/icons/tabs.svg#…">`
    之后，一旦那个文件丢了、改名了或者被 CSP 拦下，页面**不会报错**：`<svg>` 盒子
    还在、宽高还是 24×24、computed color 也照样正确，只是里面什么都没有。截图上是
    一排空白，而对比度检查读的是计算色，它会说一切正常。

    `getBBox()` 是唯一说实话的量：外部引用没解析时它是 0×0。
    （注意别用 `use.instanceRoot`——它在现代 Chrome 里已被移除，一律返回 null，
    拿它判断会把"渲染正常"报成"全是空的"。这个坑刚踩过。）
    """
    raw = tab.send("Runtime.evaluate", expression=(
        "JSON.stringify([...document.querySelectorAll('.tabbar .tab use')].map(u => {"
        "  try { const b = u.getBBox(); return Math.round(b.width); } catch (e) { return 0; }"
        "}))"
    ), returnByValue=True)["result"].get("value", "[]")
    widths = json.loads(raw)
    if not widths:
        return          # 这一页没有标签栏（老人端）
    empty = [i for i, w in enumerate(widths) if not w]
    if empty:
        failures.append(f"{page}  标签栏第 {empty} 个图标是空的：外部 sprite 没有解析")


def press_every_control(tab: "CDP", page: str, failures: list[str]) -> int:
    """把这一页上每个按钮都按一遍，每按一次收一次网。

    只加载页面是不够的。`/care` 和 `/trust` 的按钮曾经**全部是死的**——脚本在第一
    条语句就抛了 ReferenceError——而任何"页面能打开吗"的检查都看不出区别：那两页
    照样渲染出完整的卡片、标题和按钮，只是按下去什么也不会发生。真正区分"活的"和
    "画出来的"，只有按一下。

    逐个按、逐个收网，是为了让报错能指到具体哪个按钮；一次点完再收，只会得到一堆
    不知道属于谁的异常。
    """
    count = tab.send("Runtime.evaluate", expression=(
        "(() => {"
        f"  const skip = new Set(document.querySelectorAll('{SKIP_SELECTORS}'));"
        "   window.__probe = [...document.querySelectorAll('button')]"
        "     .filter(el => !skip.has(el) && !el.disabled && el.offsetParent !== null);"
        "   return window.__probe.length;"
        "})()"
    ), returnByValue=True)["result"].get("value", 0)

    for index in range(int(count)):
        label = tab.send("Runtime.evaluate", expression=(
            f"(window.__probe[{index}].textContent || '').trim().slice(0, 20)"
            f" + '#' + (window.__probe[{index}].id || '{index}')"
        ), returnByValue=True)["result"].get("value", str(index))
        tab.events.clear()
        tab.send("Runtime.evaluate", expression=f"window.__probe[{index}].click()")
        tab.drain(CLICK_SETTLE_SECONDS)
        failures.extend(collect(tab.events, f"{page} 点击「{label}」"))
    return int(count)


def main() -> int:
    try:
        import websocket  # type: ignore
    except ImportError:
        print("SKIP page_runtime: websocket-client not installed")
        return 0
    chrome = find_chrome()
    if not chrome:
        print("SKIP page_runtime: no Chromium browser found")
        return 0

    # 独立的一次性数据库。这个检查会真的按下每一个按钮，包括 SOS、限时破窗和支付
    # 授权——那些写操作不能落进仓库的 data/youhuo.db，否则它会污染后面的检查，也会
    # 让"重跑一次"不再等价。演示播种也一并打开，否则基线那几个按钮无数据可算。
    workdir = tempfile.mkdtemp(prefix="youhuo-page-runtime-")
    env = {
        **os.environ,
        "PYTHONPATH": str(ROOT / "backend"),
        "YOUHUO_DEMO_MODE": "true",
        "YOUHUO_DB_PATH": str(Path(workdir) / "runtime.db"),
        "YOUHUO_SEED_BASELINE": "true",
    }
    server = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "youhuo.api:app", "--host", "127.0.0.1",
         "--port", str(PORT), "--app-dir", "backend", "--log-level", "warning"],
        cwd=ROOT, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )

    # 一次性 profile。这个项目的 service worker 会缓存外壳，持久 profile 会让浏览器
    # 拿上一次构建的 HTML 和 CSS —— `shoot_pages.py` 为此付过代价，这里不重蹈。
    profile = Path(os.environ.get("TEMP", "/tmp")) / "youhuo-page-runtime"
    shutil.rmtree(profile, ignore_errors=True)

    browser_proc = None
    failures: list[str] = []
    clicked = 0
    try:
        for _ in range(80):
            try:
                with urllib.request.urlopen(f"{BASE}/ping", timeout=2):
                    break
            except Exception:
                time.sleep(0.4)
        else:
            print("FAIL page_runtime: server did not start")
            return 1

        browser_proc = subprocess.Popen(
            [chrome, "--headless=new", "--disable-gpu", "--no-sandbox", "--hide-scrollbars",
             f"--remote-debugging-port={DEVTOOLS_PORT}", "--remote-allow-origins=*",
             f"--user-data-dir={profile}", "about:blank"],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        ws_url = None
        for _ in range(80):
            try:
                with urllib.request.urlopen(
                    f"http://127.0.0.1:{DEVTOOLS_PORT}/json/version", timeout=2
                ) as r:
                    ws_url = json.loads(r.read())["webSocketDebuggerUrl"]
                break
            except Exception:
                time.sleep(0.4)
        if not ws_url:
            print("SKIP page_runtime: browser devtools unavailable")
            return 0

        browser = CDP(ws_url, websocket)
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
                # 三个域都要开，而且要在 navigate **之前**：脚本在解析期就抛的那一类
                # 错误发生得比任何一次 drain 都早，晚开就永远收不到。
                tab.send("Runtime.enable")
                tab.send("Log.enable")
                tab.send("Network.enable")
                tab.send("Page.enable")
                tab.send("Page.navigate", url=BASE + page)
                tab.drain(SETTLE_SECONDS)
                failures.extend(collect(tab.events, page))
                check_sprite_icons(tab, page, failures)
                tab.events.clear()
                clicked += press_every_control(tab, page, failures)
            finally:
                tab.close()
                browser.send("Target.closeTarget", targetId=target)
    finally:
        if browser_proc:
            browser_proc.terminate()
        server.terminate()
        shutil.rmtree(workdir, ignore_errors=True)

    if failures:
        print(f"FAIL page_runtime: {len(failures)} 项")
        for item in failures:
            print(f"  {item}")
        return 1
    print(f"OK page_runtime: {len(PAGES)} 个页面加载干净，"
          f"{clicked} 个控件逐个按过，无异常、无 console.error、无失败请求")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
