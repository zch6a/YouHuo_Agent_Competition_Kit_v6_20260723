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

# 溢出探针与 shoot_pages 共用一份：那边出图给人看，这边每轮都判。两份会漂。
sys.path.insert(0, str(Path(__file__).resolve().parent))
from shoot_pages import OVERFLOW_PROBE  # noqa: E402

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

#: 会换掉整屏内容的控件，留到最后按。
#:
#: `/family` 的分区按钮排在 DOM 前面，"按第一个没按过的"会先把它们按完，最后停在
#: "我的"那一分区——其余三个分区里的按钮从头到尾没有可见过，而检查照样报"全部
#: 按过"。规则因此是两级的：先把此刻屏幕上的按干净，再换一屏。
DEFER_SELECTORS = ".seg"

#: 单页点击遍历的次数上限。按下一个按钮可能让另一批按钮**出现**——页内分区、
#: 抽屉、条件渲染都会——所以遍历是"按一个再找一次"，没有固定名单。这个上限只是
#: 防止两个按钮互相召唤对方转不出去；正常页面在 20 次以内就找不到新的了。
MAX_PRESSES = 60


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


#: 手机视口。这个产品的主要形态是装到主屏的 PWA，横向溢出只在窄屏上才发生。
PHONE = (390, 844)

#: 无障碍：对比度检查管不到的那几件。
#:
#: `check_contrast.py` 量的是颜色和触控尺寸——那两项达标，不代表一位用读屏或只用
#: 键盘的老人能用。这个受众里视力退化和手部精细动作退化是并发的，所以这几条不是
#: 加分项，是这个产品的及格线。
#:
#: 首次跑出三处真问题：/care 的两个 textarea 没有名字（读屏只会念"编辑框"），
#: 首页那条创新点横滚带有 706px 内容在屏幕外而它不可聚焦——键盘用户滚不到，对他们
#: 来说后面六项创新根本不存在。
A11Y_PROBE = r"""
(() => {
  const out = {缺少无障碍名字: [], 标题层级: [], 只有placeholder: [], 键盘够不到: [], 地标: []};
  const accName = (el) => {
    if (el.getAttribute('aria-label')) return el.getAttribute('aria-label').trim();
    const by = el.getAttribute('aria-labelledby');
    if (by) {
      const t = by.split(/\s+/).map(id => (document.getElementById(id)||{}).textContent||'').join(' ');
      if (t.trim()) return t.trim();
    }
    if (['INPUT','SELECT','TEXTAREA'].includes(el.tagName)) {
      if (el.labels && el.labels.length) return [...el.labels].map(l => l.textContent).join(' ').trim();
      if (el.getAttribute('placeholder')) return 'PLACEHOLDER:' + el.getAttribute('placeholder');
      return el.title || '';
    }
    return (el.innerText || el.textContent || '').trim() || el.title || '';
  };
  const sel = (el) => el.tagName.toLowerCase() + (el.id ? '#' + el.id : '')
    + (typeof el.className === 'string' && el.className.trim()
        ? '.' + el.className.trim().split(/\s+/).slice(0,2).join('.') : '');

  document.querySelectorAll('button, a[href], input, select, textarea, [tabindex]').forEach(el => {
    const r = el.getBoundingClientRect();
    if (r.width < 1 && r.height < 1) return;
    const name = accName(el);
    if (!name) out.缺少无障碍名字.push(sel(el));
    else if (name.startsWith('PLACEHOLDER:')) out.只有placeholder.push(sel(el) + ' → ' + name.slice(12));
  });

  let prev = 0;
  document.querySelectorAll('h1,h2,h3,h4,h5,h6').forEach(h => {
    const lvl = Number(h.tagName[1]);
    if (prev && lvl > prev + 1) {
      out.标题层级.push(h.tagName + ' 跳级（上一个 H' + prev + '）：' + (h.innerText||'').trim().slice(0,16));
    }
    prev = lvl;
  });
  const h1 = document.querySelectorAll('h1').length;
  if (h1 !== 1) out.标题层级.push('h1 有 ' + h1 + ' 个，应当恰好 1 个');

  document.querySelectorAll('*').forEach(el => {
    const ox = getComputedStyle(el).overflowX;
    if (ox !== 'auto' && ox !== 'scroll') return;
    if (el.scrollWidth <= el.clientWidth + 1) return;
    if (el.tabIndex >= 0) return;
    out.键盘够不到.push(sel(el) + ' 可横滚 ' + (el.scrollWidth - el.clientWidth) + 'px 却不可聚焦');
  });

  if (!document.querySelector('main')) out.地标.push('没有 <main>');
  if (!document.documentElement.lang) out.地标.push('<html> 没有 lang');
  return JSON.stringify(out);
})()
"""


def check_no_horizontal_overflow(tab: "CDP", page: str, failures: list[str]) -> None:
    """在手机视口下量"有没有内容够不着"。

    探针与 `shoot_pages.py` 共用一份（那边负责出图给人看，这边负责每轮都判）。
    横向溢出在截图上只是"右边被切掉一点"，在手机上是整页能左右晃、正文有一半永远
    够不着；而对比度检查读的是计算色，溢出不改变任何元素的颜色，它会一路绿到底。

    只看 `documentElement.scrollWidth` 不够：`position: fixed` 的元素不计入文档滚动
    尺寸。给底部标签栏加 `min-width: 1200px`，scrollWidth 纹丝不动，而右边两个标签
    已经出界、永远点不到。所以探针逐个元素量右边缘。
    """
    tab.send("Emulation.setDeviceMetricsOverride",
             width=PHONE[0], height=PHONE[1], deviceScaleFactor=1, mobile=True)
    tab.drain(1.2)
    raw = tab.send("Runtime.evaluate", expression=OVERFLOW_PROBE,
                   returnByValue=True)["result"].get("value")
    # 无障碍那几条也在手机视口下查：横滚带只在窄屏才真的溢出，桌面宽度下它一条
    # 内容都不隐藏，检查会永远是绿的。
    check_accessibility(tab, page, failures)
    tab.send("Emulation.clearDeviceMetricsOverride")
    tab.drain(0.6)
    if not raw:
        return
    box = json.loads(raw)
    if box["sw"] > box["vw"]:
        failures.append(
            f"{page}  手机视口下文档横向溢出 {box['sw'] - box['vw']}px"
        )
    for item in box["offscreen"]:
        failures.append(f"{page}  手机视口下元素右边缘出界：{item}")


def check_accessibility(tab: "CDP", page: str, failures: list[str]) -> None:
    """在手机视口下查那几条对比度检查看不见的无障碍问题。

    刻意**不**查"有没有 aria-live 区域"：首页是静态落地页，为它加一个 live region
    只会制造噪音。一条会对正确实现报警的检查，最后一定被人加白名单绕过。
    """
    raw = tab.send("Runtime.evaluate", expression=A11Y_PROBE,
                   returnByValue=True)["result"].get("value")
    if not raw:
        return
    for kind, items in json.loads(raw).items():
        for item in items:
            failures.append(f"{page}  无障碍/{kind}：{item}")


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


def check_glass_box(tab: "CDP", page: str, failures: list[str]) -> None:
    """老人端说一句会产生高风险任务的话，信任卡必须画出来。

    这条单列，是因为 `showGlassBox()` 外面包着 try/catch：渲染函数一旦抛错，它会
    静默清空 relianceHost，页面上什么都不剩，而点击闸门收不到任何异常——玻璃盒是
    这个项目的三项核心创新之一，坏掉却完全无声。

    只在老人端跑。
    """
    if page != "/elder":
        return
    tab.send("Runtime.evaluate", expression=(
        "(() => {const i = document.getElementById('text');"
        " if (!i) return; i.value = '帮我交水费';"
        " document.getElementById('send').click();})()"
    ))
    tab.drain(5.0)
    rows = tab.send("Runtime.evaluate", expression=(
        "document.querySelectorAll('#relianceHost .reliance-row').length"
    ), returnByValue=True)["result"].get("value", 0)
    if not rows:
        failures.append(f"{page}  高风险任务没有带出玻璃盒信任卡（relianceHost 是空的）")


def check_identity_self_heal(tab: "CDP", page: str, failures: list[str]) -> None:
    """把一个服务器不认识的身份种进浏览器，看这一页能不能自己走出来。

    这是公开演示地址上真实会发生的事：访客身份是在**某一个**数据库里开通的，
    存在 localStorage 里。重新部署、重置演示数据、换台机器跑，那个 family_id
    就没了。此前的表现是每次打开都 401，刷新多少次都一样——`reset()` 写好了
    却没人调用，身份 promise 又是记忆化的——除非用户自己去清网站数据。

    这一条必须在浏览器里跑，不能查源码。"common.js 里有 renew 字样"证明不了
    这条路径通：第一版改完之后令牌确实换了，日报却还在报"老人账户不属于当前
    家庭"，因为页面早就把旧身份里的 ELDER_ID 取走了。查字符串会说它已经修好。

    只在一页上跑：这是 common.js 的行为，六页共用同一份，跑六遍只是慢六倍。
    """
    if page != "/family":
        return
    tab.send("Runtime.evaluate", awaitPromise=True, expression=(
        "(async () => {"
        "  localStorage.setItem('youhuo_visitor_identity_v1', JSON.stringify({"
        "    elderId:'elder-vDEAD', daughterId:'daughter-vDEAD', sonId:'son-vDEAD',"
        "    systemId:'system-vDEAD', familyId:'fam-vDEAD',"
        "    elderToken:'bogus', familyToken:'bogus', isolated:true}));"
        "  sessionStorage.clear();"
        "})()"
    ))
    tab.events.clear()
    tab.send("Page.navigate", url=BASE + page)
    tab.drain(SETTLE_SECONDS + 3.0)      # 自愈中间要多走一次整页重载
    healed = tab.send("Runtime.evaluate", returnByValue=True, expression=(
        "(() => {"
        "  const notice = document.querySelector('#familyNotice');"
        "  const shouting = notice && !notice.hidden ? notice.textContent : '';"
        "  const stale = JSON.parse(localStorage.getItem("
        "    'youhuo_visitor_identity_v1') || '{}').familyId === 'fam-vDEAD';"
        "  const metric = (document.querySelector('#mActive') || {}).textContent;"
        # 日报走的是另一条路：它用的是页面在**加载时**从身份里取走的 ELDER_ID。
        # 只换令牌不重载，这一路会单独失败成"老人账户不属于当前家庭"，而上面三个
        # 判据全是绿的——闸门第一版就漏了它。
        "  const daily = (document.querySelector('#dailyReport') || {}).textContent || '';"
        "  return JSON.stringify({shouting, stale, metric, daily});"
        "})()"
    ))["result"].get("value", "{}")
    state = json.loads(healed)
    if state["stale"]:
        failures.append(f"{page}  服务器不认识的身份没有被换掉，这个浏览器再也进不来了")
    if state["shouting"]:
        failures.append(f"{page}  身份换过之后仍在报错：{state['shouting']}")
    if state["metric"] in ("–", "", None):
        failures.append(f"{page}  身份换过之后数据没有回来（进行中仍是「{state['metric']}」）")
    if "失败" in state["daily"] or "不属于" in state["daily"]:
        failures.append(f"{page}  身份换过之后生活日报仍然打不开：{state['daily'][:40]}")


def press_every_control(tab: "CDP", page: str, failures: list[str]) -> int:
    """把这一页上每个按钮都按一遍，每按一次收一次网。

    只加载页面是不够的。`/care` 和 `/trust` 的按钮曾经**全部是死的**——脚本在第一
    条语句就抛了 ReferenceError——而任何"页面能打开吗"的检查都看不出区别：那两页
    照样渲染出完整的卡片、标题和按钮，只是按下去什么也不会发生。真正区分"活的"和
    "画出来的"，只有按一下。

    逐个按、逐个收网，是为了让报错能指到具体哪个按钮；一次点完再收，只会得到一堆
    不知道属于谁的异常。

    **每按一个就重新找一次**，不是开局快照一份名单按到底。`/family` 的四个页内
    分区里有三个默认 `hidden`，开局快照只看得见"今天"那一屏的按钮——而检查照样
    会报"全部按过"。分轮快照也不够：一轮结束时只有最后点开的那个分区是展开的，
    中途短暂露过面的按钮（比如"待办"里的表单提交）依旧一次都没被按到。
    实测就是这样——分轮拿到 47，一次性拿到 46，而正确答案是 48。

    每次只问"还有哪个可见的没按过"，按掉它，再问一次。多花几十次 Runtime.evaluate，
    相比每次点击 1.6 秒的收网时间可以忽略，换来的是这个数字不再是假的。
    """
    tab.send("Runtime.evaluate", expression="window.__pressed = new WeakSet();")
    pressed = 0
    while pressed < MAX_PRESSES:
        label = tab.send("Runtime.evaluate", expression=(
            "(() => {"
            f"  const skip = new Set(document.querySelectorAll('{SKIP_SELECTORS}'));"
            f"  const defer = new Set(document.querySelectorAll('{DEFER_SELECTORS}'));"
            "   const ready = [...document.querySelectorAll('button')]"
            "     .filter(b => !skip.has(b) && !b.disabled && b.offsetParent !== null"
            "               && !window.__pressed.has(b));"
            "   const el = ready.find(b => !defer.has(b)) || ready.find(b => defer.has(b));"
            "   if (!el) return null;"
            "   window.__pressed.add(el);"
            "   window.__next = el;"
            "   return (el.textContent || '').trim().slice(0, 20) + '#' + (el.id || '?');"
            "})()"
        ), returnByValue=True)["result"].get("value")
        if not label:
            break
        tab.events.clear()
        tab.send("Runtime.evaluate", expression="window.__next.click()")
        tab.drain(CLICK_SETTLE_SECONDS)
        failures.extend(collect(tab.events, f"{page} 点击「{label}」"))
        pressed += 1
    else:
        failures.append(f"{page}  点击遍历到达 {MAX_PRESSES} 次上限还没停——可能有两个按钮在互相召唤")
    return pressed


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
                check_no_horizontal_overflow(tab, page, failures)
                tab.events.clear()
                check_glass_box(tab, page, failures)
                failures.extend(collect(tab.events, f"{page} 玻璃盒"))
                tab.events.clear()
                clicked += press_every_control(tab, page, failures)
                check_identity_self_heal(tab, page, failures)
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
    print(f"OK page_runtime: {len(PAGES)} 个页面加载干净，{clicked} 个控件逐个按过，"
          f"手机视口无横向溢出、无障碍五项通过，无异常、无 console.error、无失败请求")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
