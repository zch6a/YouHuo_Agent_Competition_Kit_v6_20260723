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
import re
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

# 溢出探针与 shoot_pages 共用一份：那边出图给人看，这边每轮都判。两份会漂。
sys.path.insert(0, str(Path(__file__).resolve().parent))
from shoot_pages import OVERFLOW_PROBE  # noqa: E402
# 本机请求一律绕开系统代理，理由见 localhttp.py（一次真实的
# 「服务未能启动」其实是代理把请求挂死了）。
from localhttp import open_local

#: 端口在运行时向系统要，不写死——见 `_free_port()` 的说明。
PORT = 0
DEVTOOLS_PORT = 0
BASE = f"http://127.0.0.1:{PORT}"

PAGES = ["/", "/elder", "/family", "/care", "/trust", "/judge", "/stage"]

#: 只跑其中几页：`YOUHUO_RUNTIME_PAGES=/elder,/family`。
#: 给变异测试用——一个变体跑全套七页要几分钟，而变异要跑很多轮。
#: 平时不设，跑全套；**这个开关只缩小范围，不放宽任何一条判据**。
if os.environ.get("YOUHUO_RUNTIME_PAGES"):
    _want = [p.strip() for p in os.environ["YOUHUO_RUNTIME_PAGES"].split(",") if p.strip()]
    _unknown = [p for p in _want if p not in PAGES]
    if _unknown:
        raise SystemExit(f"YOUHUO_RUNTIME_PAGES 里有不认识的页面：{_unknown}；可选：{PAGES}")
    PAGES = _want

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
#: 会**导航走**的控件，不按——按下去这一页就没了，后面的检查全部落在别的页面上。
#:
#: `.tab` 改成 `a.tab`。原写法按类名跳过所有标签，而那条规则是为家人端和照护端写的
#: ——那两页的标签是 `<a href="/care">`，按下去真的换页。老人端改成四个 Tab 之后，
#: 它的标签是**页内切换的 `<button>`**（`class="tab seg"`），却被同一条规则无条件
#: 跳过：「记录」「家人」「我的」三个分区里的控件一次都没被按到，而遍历安静地结束，
#: 只有 REQUIRED_PRESSES 那条点名把它抓了出来。
#:
#: 判据应该是"它会不会导航走"，而不是"它叫什么类名"。`<a>` 会，`<button>` 不会。
SKIP_SELECTORS = "a, .back-link, a.tab"

#: 会换掉整屏内容的控件，留到最后按。
#:
#: `/family` 的分区按钮排在 DOM 前面，"按第一个没按过的"会先把它们按完，最后停在
#: "我的"那一分区——其余三个分区里的按钮从头到尾没有可见过，而检查照样报"全部
#: 按过"。规则因此是两级的：先把此刻屏幕上的按干净，再换一屏。
#:
#: 抽屉的开合按钮从 SKIP 挪到这里。它们原先在跳过名单上，理由写的是"会导航走"——
#: 但它们不导航，只是开合一个 `<aside>`。后果是老人端抽屉里那**十几个真控件**
#: （`#saveProfile`、`#repeatLast`、`#stepBack`、`#companionEntry`、`#logEntry`、
#: 四个「问问看」、两个 `<select>`…）从头到尾一次都没有被按过：抽屉是关着的，
#: 它们 `offsetParent === null`，遍历直接跳过，而检查照样报"全部按过"。
#: 老人端恰好是这个产品的主界面。
DEFER_SELECTORS = ".seg, summary, [data-sheet-open]"

#: 会把东西**收起来**的控件，全页最后按。
#:
#: 抽屉的关闭按钮在 DOM 里排在抽屉内容之前（它是抽屉顶上那个把手）。和分区按钮、
#: `<summary>` 放在同一档的话，它会先被按到，把抽屉关上——于是里面的 `<summary>`
#: 再也点不开，`#saveProfile` 报"没被按到"。实测就是这样。
#: 所以是三档：先按此刻屏幕上的，再按会**展开**东西的，最后才按会**收起**的。
#:
#: `#focusBack` 也在这一档，而且它是"复位重按"那条规则的主要用户。老人端的 Focus Mode
#: 是一层模态：进去之后四个 Tab 是 `display: none`，唯一出口就是它。而好几个控件
#: （`#mic`、`#typeInstead`、`#nextOpen`、`#kinContact`）都会把界面推进这一层——
#: 于是遍历会反复被关进去，而 `#focusBack` 只能按一次的话就再也出不来，
#: 最后那个 Tab 里的控件永远到不了。
#: `#taskDetailClose` 是这一轮新加的第二层模态（事务详情，`role="dialog"`
#: `aria-modal="true"`，打开时给其余层加 `inert`）。它和 `#focusBack` 是同一个形状：
#: 「记录」分区里每一条 `.log-item` 现在都是一个 `<button>`，按下去就把这一层推上来，
#: 而 `inert` 让底下的 `#saveProfile` 一类控件点不到。不放进这一档的话，遍历会被关在
#: 这一层里，最后报的是「`#saveProfile`、`#repeatLast`、`#companionEntry`、`#logEntry`
#: 没有被按到（抽屉/分区没被真的打开？）」——**那个提示指向错误的原因**，实测就是这样。
CLOSER_SELECTORS = "[data-sheet-close], #focusBack, #taskDetailClose"

#: 点击遍历的次数上限**由页面自己的控件数算出来**，不是一个固定数字。
#:
#: 它守的是"两个按钮互相召唤对方，转不出去"。而真正的互相召唤必须**不断造出新元素**
#: ——已经按过的元素在 WeakSet 里，永远不会被再按一次——所以那种情况下按下去的次数
#: 是无界的，任何上限都会被撞破。上限的绝对值因此只需要"比这一页的真实控件数宽裕"。
#:
#: 原先是写死的 60。这一轮把 22 个演示控件从 `/care` 和 `/trust` 合并到 `/stage`
#: 之后，那一页光静态按钮就有 49 个，每按一个还会生出一个装原始响应的 `<summary>`
#: ——遍历撞上 60 就报"可能有两个按钮在互相召唤"，而实际情况是这一页真的有那么多
#: 控件。把 60 改成 160 能让它变绿，但那是拿一个页面的实际大小去调一个本该跟着页面
#: 大小走的数。
#:
#: `2 × 载入时可见的 button/summary + 80` 的余量足够装下"每个结果卡再长一个折叠区"，
#: 而互相召唤仍然会撞破它。
PRESS_BUDGET_SLACK = 80
PRESS_BUDGET_FACTOR = 2

#: 每一页必须被按到的控件（按 id 匹配点击遍历记下的标签）。
#:
#: 这不是再数一遍按钮，是钉住那些**只在某个折叠层里才存在**的控件真的被展开过：
#: 老人端抽屉里的保存与记录、家人端和照护页分区里的入口。数字本身证明不了这件事
#: ——58 和 60 都像是对的。
REQUIRED_PRESSES = {
    "/elder": ("#saveProfile", "#repeatLast", "#companionEntry", "#logEntry"),
    # /stage 的四层里，「演示」「证明」「工程」三层默认收起，里面 23 个按钮只有按过
    # `.seg` 之后才可达——而它们此前一个钉子都没有，也就是说这个字典的注释说自己在守
    # 的那件事，对这一页完全没做。
    #
    # 这一整份名单原先分在 `/care`（四个）和 `/trust`（四个）下面。那 22 个控件已经
    # 整体搬到了这一页（proof-demos.js）：`#sosDemo`（模拟老人主动呼救）、
    # `#breakGlassDemo`（限时破窗）、`#scheduler`（推进到期待办）一个都没删，只换了
    # 位置。名单跟着搬，钉的还是同一件事——SKIP_SELECTORS 的注释明确说"真正做事的
    # 按钮一个都不放过，包括 SOS 和限时破窗"。
    #
    # `#depthTechnical` 也在名单里：「工程」那一层在产品模式下是 display:none 的，
    # 不先切到技术模式，遍历根本看不见 `#syncDemo` 和 `#capabilitiesDemo`。
    #
    # 名单是**全部** 23 个搬过来的控件，不是抽样。
    #
    # 起因是一个数字：加上 `[hidden] { display: none !important }` 之后，这一页按到的
    # 控件从 62 掉到 50。那条规则是对的（`.stage-proof .page-section { display: grid }`
    # 原先压过了 `hidden` 属性，四层面板同时显示，遍历因此能一次看到所有面板里的东西），
    # 但"掉了 12 个"这件事我只能靠推理去解释——而推理不是证据。
    #
    # 抽样式的名单本来就答不了这个问题。改成逐个点名之后，覆盖由**名字**保证：
    # 少按了哪一个，闸门直接说出它叫什么，不需要有人去解释一个总数的变化。
    "/stage": (
        # 先切到技术模式，否则「工程」那一层是 display:none 的
        "#depthTechnical",
        # 演示（原 /care 十二个 + 原 /family 一个）
        "#baselineDemo", "#coldRoomDemo", "#lateWakeDemo",
        "#routineDemo", "#monthlyReport", "#interactionDemo",
        "#emotionDemo", "#medicalDemo",
        "#locationInside", "#locationOutside", "#sosDemo",
        "#scheduler",
        # 证明（原 /trust 六个 + 同意记忆三个）
        "#voiceSafe", "#voiceConflict", "#policySafe", "#policyAttack",
        "#breakGlassDemo", "#sagaCreate", "#sagaAdvance",
        "#truthDemo", "#metricsDemo",
        "#memoryPropose", "#memoryApprove", "#memoryList",
        # 工程
        "#syncDemo", "#capabilitiesDemo",
    ),
    # /care 现在**进页面就加载**，五段全是 JS 填的内容，一个按钮都没有；
    # /trust 只剩一份凭证。两页在这里都不再有折叠层里的必按控件——
    # 它们的按钮全在 /stage 上面那份名单里。
}


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
    # 视口在 main() 里 navigate 之前就设成手机了，整页一直保持——这里不再切换。
    # 原先是"临时切到手机、量完就清掉"，于是后面的点击遍历跑在桌面宽度上。
    reply = tab.send("Runtime.evaluate", expression=OVERFLOW_PROBE, returnByValue=True)
    # 探针自己抛了异常，就是这一页的失败，不是"这一页没问题"。
    #
    # `Runtime.evaluate` 抛错时回包里根本没有 `value` 键（只有 `exceptionDetails` 和一个
    # subtype=error 的 result），于是 `.get("value")` 是 None，紧接着的
    # `if not raw: return` 静默返回——横向溢出、无障碍五项、sprite 图标三项一起变成
    # "通过"，而汇总行照样打印"手机视口无横向溢出、无障碍五项通过"。
    # `exceptionDetails` 一直就在回包里，此前从来没人看它。
    if "exceptionDetails" in reply:
        detail = reply["exceptionDetails"]
        text = (detail.get("exception") or {}).get("description") or detail.get("text")
        failures.append(f"{page}  溢出探针自己抛了异常，这一页没有被真的量过：{text}")
        return
    raw = reply["result"].get("value")
    # 无障碍那几条也在手机视口下查：横滚带只在窄屏才真的溢出，桌面宽度下它一条
    # 内容都不隐藏，检查会永远是绿的。
    check_accessibility(tab, page, failures)
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


#: 可见正文里不许出现的 JS 裸值。四个是同一类事故的不同形状。
RAW_VALUE_PROBE = r"""JSON.stringify((() => {
  const BAD = ['undefined', 'NaN', '[object Object]', 'null'];
  const hits = [];
  const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
  for (let n = walker.nextNode(); n; n = walker.nextNode()) {
    const text = (n.nodeValue || '').trim();
    if (!text) continue;
    // 只看**画出来**的：藏起来的分区里没人读得到，而且那里常有占位符。
    const host = n.parentElement;
    if (!host || !host.checkVisibility({checkOpacity: true, checkVisibilityCSS: true})) continue;
    for (const bad of BAD) {
      // 词边界：`nullify`、`undefinedness` 不算。中文前后本来没有空格，
      // 所以判断的是"前后不是英文字母"。
      const re = new RegExp('(^|[^A-Za-z])' + bad.replace(/[[\]]/g, '\\$&') + '([^A-Za-z]|$)');
      if (re.test(text)) {
        hits.push({bad, where: host.tagName.toLowerCase()
          + (host.id ? '#' + host.id : '')
          + (host.className ? '.' + String(host.className).split(/\s+/)[0] : ''),
          text: text.slice(0, 110)});
        break;
      }
    }
  }
  return hits;
})())"""


def check_no_raw_js_values(tab: "CDP", page: str, failures: list[str]) -> None:
    """渲染出来的中文正文里不许出现 `undefined` / `NaN` / `[object Object]` / `null`。

    这条判据是被一次真实的事故换来的：可信中心的凭证正文里印着
    「系统等的是 68.40，听到的是 68.40，第 **undefined** 次通过」。
    原因是 `TEACH_BACK_VERIFIED` 的模板读 `p.attempts`，而演示种子的载荷里没有这个
    字段（真实引擎写，种子漏了）。

    **它躲过了每一道现有闸门**：对比度只读颜色，点击遍历只看有没有抛异常，
    截图闸门看的是尺寸与横向溢出。一个 `undefined` 混在中文里既不报错、
    也不改变布局、在缩略图上也看不出来——而它出现在一整页都在讲
    「这里每一条都可核验」的地方。

    查的是**可见文字**而不是源码：`undefined` 在 JS 源码里是合法关键字。
    """
    raw = tab.send("Runtime.evaluate", expression=RAW_VALUE_PROBE,
                   returnByValue=True)["result"].get("value")
    if not raw:
        return
    for hit in json.loads(raw):
        failures.append(
            f"{page}  正文里印着 JS 裸值 [{hit['bad']}]，在 {hit['where']}：{hit['text']}"
        )


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


def check_voice_orb_states(tab: "CDP", page: str, failures: list[str]) -> int:
    """Voice Orb 的每一态在**关掉动效之后**是否仍然看得出不同。

    这个检查存在的理由，是它第一次跑就抓到了我自己写的缺陷。第一版十一态里有三态
    完全靠动画区分（listening 靠向外扩散、speaking 靠呼吸、clarifying 靠"虚线不
    转"），而 pages.css 里有一条全局 `prefers-reduced-motion` 规则把所有动画掐到
    .01ms、迭代一次。于是在开了「减少动态效果」的手机上，listening 和 speaking
    都塌回 idle、clarifying 塌回 processing——**屏幕不再告诉她 agent 正在说话**，
    她按下去打断的是 agent 自己的回答。

    前庭失调、偏头痛、晕动症的人开这个开关，而这一页的目标用户正是最可能开它的
    一群。所以这里模拟 reduce 之后再量。

    量的是三个元素的**静止形态指纹**：两道环的线型 / 粗细 / 半径 / 明度，以及 orb
    自身的 box-shadow / filter / transform。指纹相同 ⇒ 画出来一定一样。反过来不
    成立（指纹不同也可能肉眼难辨），所以这是个**下界**检查：它保证不了"好看"，
    只保证"没有两态在这个通道上是同一个东西"。
    """
    # 先把浏览器切到「减少动态效果」。这不只是关动画——万一将来有哪条静态规则也挂在
    # 这个媒体查询下，量的就得是那一套。
    tab.send("Emulation.setEmulatedMedia",
             features=[{"name": "prefers-reduced-motion", "value": "reduce"}])

    # ——并且要在**指针停在麦克风上**的情况下再量一遍。
    #
    # 这条闸门原先只量"没有指针悬停"的那一版，而那一版用户永远看不到。实际发生过：
    #
    #     .mic-big:hover:not(:disabled)              (0,3,0)
    #     body[data-activity="speaking"] .mic-big    (0,2,1)
    #
    # 3 > 2，hover 全胜。于是 speaking 的 12px 光晕——它与 idle 的**唯一**非动效差别
    # ——被抹掉，两态像素相同。而 speaking 是「我在说话，按一下会打断我」：分不清它
    # 和 idle，老人就会按下去打断优活自己的话，正是这一页开头写明要修的那个缺陷。
    # 触屏也躲不掉：sticky hover 让她点过一次麦克风之后 `:hover` 一直挂着。
    #
    # 闸门当时是绿的，因为它量的是一个不会发生的场景。
    #
    # 必须用 `CSS.forcePseudoState`，不能用 `Input.dispatchMouseEvent`——实测后者把
    # **8 个祖先**送进了 `:hover`，唯独没有 `#mic`，于是"量到了一致"其实是"没造出状态"。
    mic_node = 0
    try:
        tab.send("DOM.enable")
        tab.send("CSS.enable")
        root = tab.send("DOM.getDocument")["root"]["nodeId"]
        mic_node = tab.send("DOM.querySelector", nodeId=root, selector="#mic").get("nodeId", 0)
    except Exception as exc:                                    # noqa: BLE001
        failures.append(f"{page}  Voice Orb：拿不到 #mic 的 DOM 节点（{exc}）——"
                        "悬停那一半没测到，这不是通过")

    def sweep() -> dict:
        return tab.send("Runtime.evaluate", returnByValue=True, expression="""
      (() => {
        const mic = document.querySelector('#mic');
        const dial = document.querySelector('.mic-dial');
        if (!mic || !dial) return {skip: '这一页没有 Voice Orb'};
        // 状态名从页面自己的常量来。在这里写死一份，就成了两份会各自漂移的清单。
        const names = Object.keys(window.__voiceOrbStates || {});
        if (!names.length) return {error: 'elder.js 没有把状态表挂出来（window.__voiceOrbStates）'};

        // 过渡也要停掉，量的才是**停稳之后**的样子。
        // 用 constructable stylesheet 而不是插一个 <style>：这一站的 CSP 是
        // `default-src 'self'`，行内 <style> 会被直接拦掉，而且是静默拦掉——那样
        // 这个检查会带着"过渡还在路上"的中间值去比对，得出一堆假红。
        const sheet = new CSSStyleSheet();
        sheet.replaceSync('*,*::before,*::after{transition:none !important;animation:none !important}');
        document.adoptedStyleSheets = [...document.adoptedStyleSheets, sheet];
        const before = document.body.dataset.activity;
        try {
          const shot = () => {
            const ring = w => {
              const s = getComputedStyle(dial, w);
              return [s.borderStyle, s.borderWidth, s.top, s.left, s.opacity, s.borderColor].join('|');
            };
            const o = getComputedStyle(mic);
            return [ring('::before'), ring('::after'),
                    o.boxShadow, o.filter, o.transform, o.opacity].join('##');
          };
          const out = {};
          for (const name of names) {
            document.body.dataset.activity = name;
            dial.getBoundingClientRect();          // 逼一次样式重算
            out[name] = shot();
          }
          return {shots: out};
        } finally {
          document.body.dataset.activity = before;
          document.adoptedStyleSheets = document.adoptedStyleSheets.filter(s => s !== sheet);
        }
      })()
    """)["result"].get("value")

    try:
        passes: dict[str, dict] = {"指针在别处": sweep()}
        if mic_node:
            tab.send("CSS.forcePseudoState", nodeId=mic_node, forcedPseudoClasses=["hover"])
            passes["指针停在麦克风上"] = sweep()
            tab.send("CSS.forcePseudoState", nodeId=mic_node, forcedPseudoClasses=[])
    finally:
        tab.send("Emulation.setEmulatedMedia", features=[])

    states = passes["指针在别处"]
    if not states or states.get("skip"):
        return 0
    if states.get("error"):
        failures.append(f"{page}  Voice Orb：{states['error']}")
        return 0

    counted = 0
    for where, result in passes.items():
        if not result or result.get("skip") or result.get("error"):
            continue
        shots: dict[str, str] = result["shots"]
        counted = max(counted, len(shots))
        if len(shots) < 10:
            failures.append(f"{page}  Voice Orb 只有 {len(shots)} 态，任务书要的是十态起")
        seen: dict[str, str] = {}
        for name, fingerprint in shots.items():
            twin = seen.get(fingerprint)
            if twin:
                failures.append(
                    f"{page}  Voice Orb（{where}）：关掉动效后「{twin}」和「{name}」"
                    f"长得一模一样——这两态里有一个只靠动画区分"
                )
            else:
                seen[fingerprint] = name

    # 悬停那一遍必须真的跑过。少跑一遍和通过在结果里长得一样。
    if len(passes) < 2:
        failures.append(f"{page}  Voice Orb：只量了「指针在别处」这一种情形，"
                        "悬停那一半没造出来——这不是通过")
    return counted


def check_judge_story(tab: "CDP", page: str, failures: list[str]) -> int:
    """舞台页的七拍叙事：演一遍，然后检查 Product 层说的是不是人话。

    这一页最大的设计决定是"Product 层那七句话由**真实响应**填写，不是写死的文案"
    ——写死的文案在接口改坏之后照样好看，那不是演示，是插图。

    代价是真实数据是给机器读的。第一版演完之后那七句里漏出了三个英文枚举
    （语音结论 `clarify`、预演决策 `clarify`、任务状态 `awaiting_family_approval`）
    和一个四位小数的负荷分数 `0.6684`。一位评委看到的于是是半句中文半个标识符。

    所以这条闸门必须在**演过之后**量，静态扫源码看不见它：那些字是运行时从响应里
    拼出来的。它按下「从头演一遍」，等七拍走完，再逐句检查。

    注意：七拍叙事已从 /judge 搬到 /stage，所以这条闸门现在跑在 /stage 上。
    """
    if page != "/stage":
        return 0

    ran = tab.send("Runtime.evaluate", returnByValue=True, expression="""
      (() => {
        const button = document.querySelector('#playStory');
        if (!button) return {error: '舞台页没有「从头演一遍」这个入口'};
        button.click();
        return {ok: true};
      })()
    """)["result"].get("value") or {}
    if ran.get("error"):
        failures.append(f"{page}  七拍：{ran['error']}")
        return 0

    # 七拍各有一次网络往返，外加每拍之间 420ms 的停顿。轮询到演完或超时。
    deadline = time.time() + 30
    state: dict = {}
    while time.time() < deadline:
        time.sleep(1.0)
        state = tab.send("Runtime.evaluate", returnByValue=True, expression="""
          (() => ({
            total: document.querySelectorAll('.beat').length,
            played: document.querySelectorAll('.beat.is-played').length,
            busy: document.querySelector('#playStory').disabled,
            status: document.querySelector('#stageProgress').textContent,
            says: [...document.querySelectorAll('.beat-say')].map(n => n.textContent),
          }))()
        """)["result"]["value"]
        if not state.get("busy"):
            break

    total, played = state.get("total", 0), state.get("played", 0)
    if total < 7:
        failures.append(f"{page}  七拍只有 {total} 拍")
    if played < total:
        failures.append(
            f"{page}  七拍演到第 {played} 拍就停了（{total} 拍）：{state.get('status', '')}"
        )
        return played

    # Product 层不许出现英文。原始枚举、接口路径、哈希都在 Proof 层的原始响应里，
    # 那里是它们该在的地方。
    for index, text in enumerate(state.get("says", []), 1):
        leaked = re.findall(r"[A-Za-z]{2,}", text)
        if leaked:
            failures.append(f"{page}  第 {index} 拍的正文里有英文 {leaked}：{text[:60]}")
        if not text.strip():
            failures.append(f"{page}  第 {index} 拍演完之后正文是空的")
    return played


def check_multi_tab_identity(browser: "CDP", ws_host: str, websocket, failures: list[str]) -> None:
    """两个标签页同时冷启动，必须落在同一个家庭。

    `provision()` 的记忆化是 **document 级**的：两个标签页各自 `readCached()` 得到
    null、各自 POST /v2/auth/visitor，服务端跑两遍 seed_demo，得到两个不同的
    `family_id`。localStorage 后写覆盖先写，而两个标签页的内存常量和 sessionStorage
    令牌各自指向自己那一个。

    后果不是"多了一个家庭"这么轻：女儿在家属端批准的高风险动作写进家庭 B，老人端
    在家庭 A，`require_family_approval` 的接力永远等不到——表现是"点了批准，老人端
    没反应"，而家属端的待办列表恒为空。

    这条**必须跑起来**。静态断言只能查"代码里有没有 navigator.locks"，而变异测过：
    把 `if (navigator.locks?.request)` 改成 `if (false)`，那个子串断言照样绿——
    `navigator.locks` 在那个文件里出现两次。
    """
    tabs = []
    try:
        for _ in range(2):
            target = browser.send("Target.createTarget", url="about:blank")["targetId"]
            with open_local(f"{ws_host}/json/list", timeout=5) as reply:
                listing = json.loads(reply.read())
            tab = CDP(
                next(t["webSocketDebuggerUrl"] for t in listing if t["id"] == target), websocket
            )
            tab.send("Page.enable")
            tabs.append((target, tab))

        # 必须是**真的**冷启动。
        #
        # 这个检查跑在 /elder 之后，浏览器 profile 里已经有一份开通好的身份了——
        # 不清掉的话两个标签页都直接读缓存、必然一致，这条检查就是空过的。
        # 先在其中一个标签页里打开同源页面并清空存储，再让两个一起冷启动。
        first = tabs[0][1]
        first.send("Page.navigate", url=f"{BASE}/ping")
        first.drain(1.0)
        first.send("Runtime.evaluate", expression=(
            "try { localStorage.clear(); sessionStorage.clear(); } catch (e) {}"
        ))

        # 尽可能同时导航，让两次开通真的重叠。
        for _, tab in tabs:
            tab.send("Page.navigate", url=f"{BASE}/elder")
        for _, tab in tabs:
            tab.drain(SETTLE_SECONDS)
        # 读**这个 document 内存里**的身份，不是 localStorage。
        #
        # 两个标签页同源，localStorage 是同一份——后写覆盖先写，所以从存储里读永远
        # 一致，这个检查就永远绿。第一版就是这么写的，变异（把锁禁掉）没被抓到。
        # 真正分叉的是每个标签页自己 await 到的那个 identity：家属端用它拼请求，
        # 老人端用它拼另一个，两者不同就是那条"点了批准老人端没反应"的根因。
        families = [
            tab.send("Runtime.evaluate", returnByValue=True, awaitPromise=True, expression=(
                "window.YouHuoIdentity.ready().then(id => id.familyId || null)"
            ))["result"].get("value")
            for _, tab in tabs
        ]
        if None in families:
            failures.append(f"多标签页身份：有标签页没有开通到身份（{families}）")
        elif families[0] != families[1]:
            failures.append(
                f"多标签页身份：两个标签页落在**不同**家庭（{families}）"
                "——家属端的批准会写进另一个家庭，老人端永远等不到"
            )
    finally:
        for target, tab in tabs:
            tab.close()
            browser.send("Target.closeTarget", targetId=target)


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
    # 按过名单要有**两把**钥匙：元素本身，以及元素的稳定身份。
    #
    # 只用 WeakSet（元素身份）在有数据的页面上不收敛。实测：老人端种上三条待办之后，
    # 遍历撞到 144 次上限还没停（载入时 32 个控件），报文写的是
    # 「可能有两个按钮在互相召唤，不断造出新元素」——而它猜对了机制、猜错了主体：
    # 没有人在互相召唤，是 `reminderAction` 每次都 `loadReminders()` 重渲染整段，
    # 于是「我知道了 / 已完成」这些按钮变成**全新的对象**。WeakSet 认对象，
    # 新对象自然不在名单里，于是同一个按钮被反复按。
    #
    # 空态下这件事看不见（没有待办就没有那些按钮），所以这道闸门一直是绿的——
    # 又一次「空态掩盖问题」。
    #
    # 第二把钥匙用**稳定身份**：id / data-* / 祖先借用，和
    # `build_control_inventory.py` 的 `_KEY_ATTRS` 同一套概念。刻意不用可见文字：
    # 三条待办的按钮文字完全相同（都是「我知道了」），拿文字当钥匙会让第二条待办的
    # 按钮一次都按不到——那是把不收敛换成了漏测，更糟。
    tab.send("Runtime.evaluate", expression="""
      window.__pressed = new WeakSet();
      window.__pressedKeys = new Set();
      window.__keyOf = (el) => {
        for (const a of ['id', 'data-section', 'data-text', 'data-run', 'data-jump',
                         'data-sheet-open', 'data-sheet-close', 'name']) {
          if (el.getAttribute(a)) return a + '=' + el.getAttribute(a);
          if (el.hasAttribute(a)) return a;
        }
        // 自己没身份就从最近一个有身份的祖先借，再带上「它是这个容器里第几个同类」。
        // 序号在这里是安全的：同一次遍历里 DOM 顺序稳定，而重渲染出来的第 N 个
        // 就是上一次那第 N 个的替身——那正是我们要认出来的东西。
        for (let p = el.parentElement; p; p = p.parentElement) {
          const own = p.getAttribute('id') || p.getAttribute('data-panel')
                   || p.getAttribute('data-beat');
          if (own) {
            const kin = [...p.querySelectorAll(el.tagName)];
            return own + '/' + el.tagName + '[' + kin.indexOf(el) + ']';
          }
        }
        return '';
      };
    """)
    # 上限按这一页自己的控件数算。见 PRESS_BUDGET_SLACK 那里的说明。
    at_load = tab.send("Runtime.evaluate", expression=(
        "document.querySelectorAll('button, summary').length"
    ), returnByValue=True)["result"].get("value") or 0
    budget = PRESS_BUDGET_FACTOR * int(at_load) + PRESS_BUDGET_SLACK
    seen: list[str] = []
    pressed = 0
    #: 复位按钮的重按次数上限。它不是待测功能，只是让遍历能走出模态，所以要有个头
    #: ——否则一个"关了又自己打开"的抽屉能把这个循环钉死在这里。
    #:
    #: 数的是**连续**多少次复位、中间一次真正的进展都没有，不是全页复位的总次数。
    #: 原先是"总次数 > 4"，而这一轮「记录」分区里每一条 `.log-item` 都变成了一个会
    #: 推起事务详情层的 `<button>`：N 条记录就要 N 次开-关循环，于是一个完全健康的
    #: 页面撞上 4 就报「可能有个模态关不掉」。那是拿一个页面的实际内容条数去调一个
    #: 本该跟着行为走的数——这个文件刚为同一件事把写死的 60 改成按控件数算的公式。
    #:
    #: 而「关不掉 / 关掉又自己开了」这句话说的本来就是**连续**：真出那种毛病时，
    #: 两次复位之间永远夹不进一次普通按压。所以这个计数器一有进展就归零。
    reopens = 0
    while pressed < budget:
        label = tab.send("Runtime.evaluate", expression=(
            "(() => {"
            f"  const skip = new Set(document.querySelectorAll('{SKIP_SELECTORS}'));"
            f"  const defer = new Set(document.querySelectorAll('{DEFER_SELECTORS}'));"
            f"  const closer = new Set(document.querySelectorAll('{CLOSER_SELECTORS}'));"
            # 判据是「用户此刻按得到吗」，不是「它在文档里吗」。
            #
            # 原先是 `offsetParent !== null`，那只对 display:none 和 position:fixed
            # 为假。老人端的底部抽屉是 transform 移出屏幕的，关着的时候里面十几个
            # 按钮的 offsetParent 照样不是 null——于是遍历一直在按用户按不到的东西，
            # 而"抽屉开合按钮在不在跳过名单里"对结果毫无影响（变异测出来的：把它们
            # 放回跳过名单，那四个只在抽屉里的控件照样报被按过）。
            #
            # 现在的做法就是用户的做法：滚到它跟前，在它中心点做一次命中测试。移出
            # 屏幕的抽屉滚不过去，命中测试落空，正确地被排除；屏外下方的正常内容滚
            # 一下就到，照常入选。
            "   const usable = b => {"
            "     if (skip.has(b) || b.disabled || window.__pressed.has(b)) return false;"
            # 关闭类允许重按（见下面那段注释），所以它们不查身份名单——
            # 否则「把界面复位」这件事只能做一次，两层模态的页面永远走不完。
            "     if (!closer.has(b) && window.__pressedKeys.has(window.__keyOf(b)))"
            "       return false;"
            "     const s = getComputedStyle(b);"
            "     if (s.visibility === 'hidden' || parseFloat(s.opacity) < 0.05) return false;"
            "     b.scrollIntoView({block: 'center', inline: 'center', behavior: 'instant'});"
            "     const r = b.getBoundingClientRect();"
            "     if (r.width < 1 || r.height < 1) return false;"
            "     const x = r.left + r.width / 2, y = r.top + r.height / 2;"
            "     if (x < 0 || y < 0 || x > innerWidth || y > innerHeight) return false;"
            "     const hit = document.elementFromPoint(x, y);"
            "     return !!hit && (hit === b || b.contains(hit) || hit.contains(b));"
            "   };"
            # `<summary>` 也要点。它不是 `<button>`，此前完全不在遍历范围里——于是
            # 每一个 `<details>` 背后的东西都没被按过：老人端收起来的设置、家人端
            # 生活日报的分项、每个结果卡里那份「原始响应」。折叠一段内容因此等于
            # 让它退出检查，而这正是我这几轮反复用来给页面减负的手法。
            "   const all = [...document.querySelectorAll('button, summary')];"
            "   let el = all.find(b => !defer.has(b) && !closer.has(b) && usable(b))"
            "        || all.find(b => defer.has(b) && usable(b))"
            "        || all.find(b => closer.has(b) && usable(b));"
            # 三层都空了，再给关闭类一次机会——**即使它已经按过**。
            #
            # 关闭类控件的职责不是"一个待测的功能"，是"把界面复位，让遍历能继续"。
            # 它只能按一次的话，两层模态的页面就永远走不完。老人端实测就是这样：
            # 按下麦克风进入 Focus Mode，里面的控件按完之后唯一的出口 `#focusBack`
            # 已经在按过名单里，而 Focus Mode 下四个 Tab 是 `display: none`——
            # 「记录」「家人」「我的」三个分区一次都没到过，而遍历安静地结束了，
            # 只有 REQUIRED_PRESSES 那条点名把它抓出来。
            #
            # 复位按钮可以重按，但要防死循环：只在没有新东西可按时才走这一条，
            # 而且由 Python 那边数次数、超过就停。
            "   let reopened = false;"
            "   if (!el) {"
            "     el = all.find(b => closer.has(b) && !skip.has(b) && !b.disabled && (() => {"
            "       const s = getComputedStyle(b);"
            "       if (s.visibility === 'hidden' || parseFloat(s.opacity) < 0.05) return false;"
            "       b.scrollIntoView({block: 'center', inline: 'center', behavior: 'instant'});"
            "       const r = b.getBoundingClientRect();"
            "       if (r.width < 1 || r.height < 1) return false;"
            "       const x = r.left + r.width / 2, y = r.top + r.height / 2;"
            "       if (x < 0 || y < 0 || x > innerWidth || y > innerHeight) return false;"
            "       const hit = document.elementFromPoint(x, y);"
            "       return !!hit && (hit === b || b.contains(hit) || hit.contains(b));"
            "     })());"
            "     reopened = !!el;"
            "   }"
            "   if (!el) return null;"
            "   window.__pressed.add(el);"
            "   const k = window.__keyOf(el); if (k) window.__pressedKeys.add(k);"
            "   window.__next = el;"
            "   return (reopened ? '复位:' : '')"
            "     + (el.textContent || '').trim().slice(0, 20) + '#' + (el.id || '?');"
            "})()"
        ), returnByValue=True)["result"].get("value")
        if not label:
            break
        if label.startswith("复位:"):
            reopens += 1
            if reopens > 4:
                failures.append(
                    f"{page}  连着按了 {reopens} 次复位、中间一次别的控件都没按到"
                    "——可能有个模态关不掉，或者关掉之后又自己开了"
                )
                break
        else:
            reopens = 0
        tab.events.clear()
        tab.send("Runtime.evaluate", expression="window.__next.click()")
        tab.drain(CLICK_SETTLE_SECONDS)
        failures.extend(collect(tab.events, f"{page} 点击「{label}」"))
        seen.append(label)
        pressed += 1
    else:
        failures.append(
            f"{page}  点击遍历到达 {budget} 次上限还没停（载入时有 {at_load} 个控件）"
            "——可能有两个按钮在互相召唤，不断造出新元素"
        )

    # 抽屉背后那一层必须真的被按到。
    #
    # 抽屉的开合按钮曾经在跳过名单上（理由写的是"会导航走"，但它们不导航），于是
    # 老人端抽屉里那十几个真控件从来没被按过：抽屉关着，它们 offsetParent 是 null，
    # 遍历直接跳过，而检查照样报"全部按过"。数字本身看不出这件事——58 和 60 都像是
    # 对的。所以这里点名要求几个只存在于抽屉里的 id 出现在按过的名单上。
    required = REQUIRED_PRESSES.get(page, ())
    missing = [want for want in required if not any(want in label for label in seen)]
    if missing:
        failures.append(f"{page}  这些控件没有被按到（抽屉/分区没被真的打开？）：{missing}")
    return pressed



#: Focus Mode 里说完一句话之后，那一屏必须还能用。
#:
#: 这道检查是一个 P0 换来的。原先所有检查都在**空**的 Focus Mode 上做——一进去就量，
#: 那时玻璃盒卡还不存在，一列东西正好装得下。而缺陷只在"说了一句、卡出现之后"显形：
#:
#:     .elder-focus 638      #focusBack 48
#:     #chat          0      ← scrollHeight 383，3 条气泡，全被裁掉
#:     #relianceHost 893     ← 一张卡比整个视口还高，且 min-height: auto 拒绝收缩
#:     .composer    222      ← top 1159，在 844 的视口之外
#:
#: 她既看不见刚说的话，也够不到输入框和发送键。而点击遍历是绿的：它对 `#send` 做
#: `scrollIntoView` 之后命中测试通过——**脚本能滚 `overflow: hidden` 的容器，手指不能**。
FOCUS_AFTER_SPEAKING = r"""
(async () => {
  const enter = document.getElementById('typeInstead');
  if (!enter) return {skip: '这一页没有打字入口'};
  if (document.body.dataset.focus !== 'on') {
    enter.click();
    await new Promise(r => setTimeout(r, 300));
  }
  if (document.body.dataset.focus !== 'on') return {fail: '按了打字入口也没进 Focus Mode'};

  const text = document.getElementById('text');
  const send = document.getElementById('send');
  if (!text || !send) return {fail: 'Focus Mode 里没有输入框或发送键'};
  text.value = '帮我交这个月的水费';
  text.dispatchEvent(new Event('input', {bubbles: true}));
  send.click();
  // 一次真实往返，加上玻璃盒卡自己那一次请求。
  await new Promise(r => setTimeout(r, 9000));

  const stage = document.querySelector('.elder-layout .stage');
  const focus = document.querySelector('.elder-focus');
  const chat = document.getElementById('chat');
  const composer = document.querySelector('.composer');
  if (!stage || !focus || !chat || !composer) return {fail: 'Focus Mode 的结构变了'};

  const sr = stage.getBoundingClientRect();
  const cr = composer.getBoundingClientRect();
  const kids = [...focus.children].map(el => ({
    what: el.tagName + (el.id ? '#' + el.id : '.' + String(el.className).split(' ')[0]),
    h: Math.round(el.getBoundingClientRect().height),
  }));
  return {
    focus: document.body.dataset.focus,
    bubbles: chat.children.length,
    // 卡到底出没出现。Python 那边靠它判断"这一轮有没有造出被测状态"——
    // 没有这个数，卡不出现时下面每条断言都会轻松通过，而它们其实什么都没量到。
    relianceKids: (document.getElementById('relianceHost') || {children: []}).children.length,
    chatH: Math.round(chat.getBoundingClientRect().height),
    chatScrollH: chat.scrollHeight,
    composerBottom: Math.round(cr.bottom),
    composerTop: Math.round(cr.top),
    stageBottom: Math.round(sr.bottom),
    focusH: Math.round(focus.getBoundingClientRect().height),
    kidsSum: kids.reduce((a, k) => a + k.h, 0),
    kids,
  };
})()
"""


#: 家人加的药，摆到老人眼前之后**她真的看得见**。
#:
#: 这一条不是"渲染函数被调到了"，是"那张卡在屏幕上有像素、按钮有 48px"。
#: 两者差得很远：第一版接线渲染完全正确，而 `#reminders` 住在
#: `section.today-block` 里，那一块由 `renderTodayBlock()` 按**待办条数**收放。
#: 一户「今天没有待办、家人刚加了一份药」的人家——也就是这条流程最典型的样子——
#: 整块 `display: none`。卡片在 DOM 里、`textContent` 读得到、脚本点得着，
#: 屏幕上一个像素都没有。实测 430×932 和 1280×900 两个视口都是 `[0, 0]`。
#:
#: 所以判据必须落在几何上，不能落在"节点存在"上。
#: 第一步：**把被测场景造出来**，再以家人身份加一份药。
#:
#: 「造出来」这三个字是这道检查最要紧的部分。缺陷只在**今天没有待办**时出现：
#: `renderTodayBlock()` 按未完成待办的条数收放整块，一条都没有就 `display: none`，
#: 而待确认的药正渲染在那一块里面。只要这户人家碰巧还有一条没办完的事，
#: 整块是展开的，卡片看得见，**判据全绿而缺陷原封不动**。
#:
#: 变异测过：把修好的那一行改回原样（`block.hidden = open.length === 0`），
#: 这道检查**没有变红**——因为跑的时候那户人家有待办。一道在缺陷面前不变红的
#: 检查，和没有这道检查是一回事。所以这里先把待办清空，再断言真的清空了。
#:
#: 身份先换一户：`localStorage.clear()` + 重载会新开一个访客家庭，
#: 于是下面取消待办这种破坏性动作落在一户用完就扔的人家身上，
#: 不动这一轮其他检查看的那一户。
PENDING_MED_SETUP = r"""
(async () => {
  const YH = window.YouHuo;
  if (!YH || !YH.api) return {skip: '这一页没有 window.YouHuo'};
  if (!document.querySelector('#reminders')) return {skip: '这一页没有 #reminders'};
  const ids = await YH.ready();

  // ① 把今天清空——这就是被测场景。
  let open;
  try {
    const list = await YH.api('/v2/reminders?limit=50');
    open = list.filter(r => !['completed', 'cancelled'].includes(r.status));
    for (const r of open) {
      await YH.api(`/api/v1/reminders/${encodeURIComponent(r.id)}/cancel`,
                   {method: 'POST', body: JSON.stringify({})});
    }
    const again = await YH.api('/v2/reminders?limit=50');
    const left = again.filter(r => !['completed', 'cancelled'].includes(r.status));
    if (left.length) {
      return {fail: `没造出被测场景：清完还剩 ${left.length} 条没办完的事`};
    }
  } catch (e) { return {fail: '清不掉今天的待办：' + (e && e.message)}; }

  // ② 家人加一份药。
  const NAME = '闸门用钙片';
  let plan;
  try {
    plan = await YH.api('/v4/medications', {method: 'POST', body: JSON.stringify({
      elder_id: ids.elderId, display_name: NAME, normalized_name: NAME,
      dose_text: '一次一片', times_local: ['08:30'],
      start_date: new Date().toISOString().slice(0, 10), source: 'gate',
    })}, 'family');
  } catch (e) { return {fail: '家人加不上这份药：' + (e && e.message)}; }
  if (!plan || !plan.id) return {fail: '加完没拿到计划号'};
  // 家人建的计划必须是「未激活」——否则这条流程从根上就不成立，
  // 而下面量到的"看得见"会是一个毫无意义的绿。
  if (plan.active) return {fail: '家人建的计划直接就是激活的，这条流程不成立'};
  return {planId: plan.id, cancelled: open.length};
})()
"""

#: 第二步：重载之后量。判据落在**几何**上，不是"节点存在"。
#: 两者差得很远：第一版接线渲染完全正确，而 `#reminders` 住在
#: `section.today-block` 里，那一块由 `renderTodayBlock()` 按**待办条数**收放。
#: 一户「今天没有待办、家人刚加了一份药」的人家——也就是这条流程最典型的样子——
#: 整块 `display: none`。卡片在 DOM 里、`textContent` 读得到、脚本点得着，
#: 屏幕上一个像素都没有。实测 430×932 和 1280×900 两个视口都是 `[0, 0]`。
PENDING_MED_MEASURE = r"""
(() => {
  const NAME = '闸门用钙片';
  // Focus Mode 开着时 CSS 会把「今天」整块藏起来（那是对的：她在对话）。
  if (document.body.dataset.focus === 'on') return {skip: 'Focus Mode 开着'};
  const host = document.querySelector('#reminders');
  if (!host) return {skip: '这一页没有 #reminders'};
  const card = [...host.children].find(c => c.textContent.includes(NAME));
  if (!card) return {fail: '重载之后老人端首屏没有这张卡'};
  const r = card.getBoundingClientRect();
  const out = {
    cardH: Math.round(r.height), cardTop: Math.round(r.top),
    isFirst: card === host.firstElementChild,
    chip: (card.querySelector('.status-chip') || {}).textContent || '',
    todayLine: (document.querySelector('#todayLine') || {}).textContent || '',
    buttons: [...card.querySelectorAll('button')].map(b => ({
      t: b.textContent, h: Math.round(b.getBoundingClientRect().height)})),
  };
  for (let el = card; el && el !== document.documentElement; el = el.parentElement) {
    const cs = getComputedStyle(el);
    if (cs.display === 'none' || cs.visibility === 'hidden'
        || Number(cs.opacity) < 0.05 || el.hasAttribute('hidden')) {
      out.hiddenBy = el.tagName + (el.id ? '#' + el.id : '')
        + (typeof el.className === 'string' && el.className
           ? '.' + el.className.trim().split(/\s+/)[0] : '');
      break;
    }
  }
  return out;
})()
"""

#: 第三步：现场恢复。回绝会把计划删掉，库回到进来时的样子——不恢复的话，
#: 后面每一道检查看到的都是一屏多出来的卡（这个项目的巡检就栽过：
#: 一次没恢复的点击污染了它后面 14 个读数）。
PENDING_MED_RESTORE = r"""
(async () => {
  try {
    const r = await window.YouHuo.api('/api/v1/medications/pending');
    for (const it of (r.items || [])) {
      if (it.name !== '闸门用钙片') continue;
      await window.YouHuo.api(
        `/api/v1/medications/${encodeURIComponent(it.id)}/decline`,
        {method: 'POST', body: JSON.stringify({})});
    }
    const after = await window.YouHuo.api('/api/v1/medications/pending');
    return (after.items || []).some(i => i.name === '闸门用钙片')
      ? '撤不掉，还在待确认里' : null;
  } catch (e) { return '没能撤掉：' + (e && e.message); }
})()
"""


#: 访客身份存在这个键里（`identity.js` 的 `STORAGE_KEY`）。
#: 换成别的键名，下面那段"换一户再换回来"会静默变成"换一户就不回来了"——
#: 恢复不了的话它不报错，只是后面的点击遍历少按一批控件，而汇总里看不出来。
IDENTITY_KEY = "youhuo_visitor_identity_v1"

#: 恢复的是**整个 localStorage 快照**，不是身份那一个键。
#:
#: 只还身份键是我写的第一版，实测让 `/v2/chat` 变成 403：`youhuo_session_v2`
#: 也住在 localStorage 里，清空之后第二户往里写了自己的会话号，而我只把身份
#: 换了回来——于是身份说甲家、会话号指着乙家。`elder.js:669` 的注释逐字写着
#: 这个形态（「换身份之后就是这个形态……漏了会话这一半」），而它**已经修好了**：
#: `postChat` 收到 403 会丢掉旧会话重来。所以屏幕上一切正常，
#: 只有这道检查的请求收集器看见了那一发 403。
#:
#: 也就是说：那一发 403 是我的仪器自己造出来的，不是产品缺陷。
#: 修法不是给它开豁免，是让"换回去"真的换得干净。
SNAPSHOT_LOCAL = "JSON.stringify(Object.entries(localStorage))"


def check_pending_medication_is_visible(tab: "CDP", page: str, failures: list[str]) -> None:
    """「家人加的药等老人点头」——那张卡她真的看得见。见 PENDING_MED_MEASURE。"""
    if page != "/elder":
        return
    # 换一户用完就扔的人家。下一步要取消它**全部**待办，那是破坏性的——
    # 落在这一轮其他检查看的那一户身上，后面每一条读数都不可信。
    #
    # 换完要换回来。不换回来的话这一页后面的点击遍历跑在一户"今天什么都没有"
    # 的人家上：待办卡一张都不剩，那几个「我知道了」「已完成」按钮根本不存在，
    # **少按一批控件而汇总里只是数字小了一点**——这正是这个项目栽过的那种
    # "没测到被记成通过"。
    snapshot = tab.send("Runtime.evaluate", returnByValue=True, expression=(
        f"try {{ {SNAPSHOT_LOCAL} }} catch (e) {{ null }}"
    ))["result"].get("value")
    identity = None
    for key, value in json.loads(snapshot or "[]"):
        if key == IDENTITY_KEY:
            identity = value
    if not identity:
        failures.append(
            f"{page} 待确认用药：读不到访客身份（`{IDENTITY_KEY}` 不在 localStorage 里）——"
            "这一页应该已经开通过一户人家了")
        return

    tab.send("Runtime.evaluate", expression=(
        "try { localStorage.clear(); sessionStorage.clear(); } catch (e) {}"))
    tab.send("Page.navigate", url=BASE + page)
    tab.drain(SETTLE_SECONDS)

    def put_the_family_back() -> None:
        tab.send("Runtime.evaluate", expression=(
            "try { localStorage.clear(); sessionStorage.clear();"
            "  for (const [k, v] of JSON.parse(%s)) localStorage.setItem(k, v);"
            "} catch (e) {}" % json.dumps(snapshot)))
        tab.send("Page.navigate", url=BASE + page)
        tab.drain(SETTLE_SECONDS)
        back = tab.send("Runtime.evaluate", returnByValue=True, awaitPromise=True,
                        expression="window.YouHuoIdentity.ready().then(i => i.familyId)"
                        )["result"].get("value")
        want = json.loads(identity).get("familyId")
        if back != want:
            failures.append(
                f"{page} 待确认用药：换回原来那户人家失败（现在是 {back}，本该是 {want}）"
                "——后面的检查跑在别人家里，读数不可信")

    added = tab.send(
        "Runtime.evaluate", expression=PENDING_MED_SETUP,
        awaitPromise=True, returnByValue=True,
    )["result"].get("value") or {}
    if added.get("skip") or added.get("fail"):
        failures.append(
            f"{page} 待确认用药：{added.get('skip') or added.get('fail')}"
            + ("——这一页应该测得到" if added.get("skip") else ""))
        put_the_family_back()
        return

    tab.send("Page.navigate", url=BASE + page)
    tab.drain(SETTLE_SECONDS)
    try:
        result = tab.send(
            "Runtime.evaluate", expression=PENDING_MED_MEASURE, returnByValue=True,
        )["result"].get("value") or {}
    finally:
        left = tab.send(
            "Runtime.evaluate", expression=PENDING_MED_RESTORE,
            awaitPromise=True, returnByValue=True,
        )["result"].get("value")
        if left:
            failures.append(f"{page} 待确认用药：{left}（现场没恢复，后面的检查不可信）")
        put_the_family_back()
    #: 「没测到」不是通过。这一页应该测得到，跳过了就是别的东西坏了。
    if result.get("skip"):
        failures.append(f"{page} 待确认用药检查跳过了：{result['skip']}——这一页应该测得到")
        return
    if result.get("fail"):
        failures.append(f"{page} 待确认用药：{result['fail']}")
        return
    if result.get("hiddenBy"):
        failures.append(
            f"{page} 待确认用药：卡片被 {result['hiddenBy']} 藏起来了——"
            "节点在、脚本点得着，屏幕上没有")
        return
    if result.get("cardH", 0) < 40:
        failures.append(
            f"{page} 待确认用药：卡片高 {result.get('cardH')}px（top={result.get('cardTop')}）"
            "——不足以显示一张待办卡")
    if not result.get("isFirst"):
        failures.append(f"{page} 待确认用药：它没排在待办最上面——等她决定的事应该先说")
    if result.get("chip") != "等您点头":
        failures.append(
            f"{page} 待确认用药：状态词是「{result.get('chip')}」，应该是「等您点头」")
    words = [b["t"] for b in result.get("buttons", [])]
    if words != ["开始吃", "先不吃"]:
        failures.append(f"{page} 待确认用药：两个动作应该是「开始吃 / 先不吃」，实际是 {words}")
    short = [b for b in result.get("buttons", []) if b["h"] < 48]
    if short:
        failures.append(f"{page} 待确认用药：触控目标不足 48px：{short}")
    #: 「今天没有要办的事」配着一张要她点头的卡，是同一屏上两处互相打架。
    line = result.get("todayLine") or ""
    if line == "今天没有要办的事。":
        failures.append(
            f"{page} 待确认用药：「今天」那一行还写着「{line}」，"
            "而下面正摆着一张要她点头的卡")


def check_focus_mode_after_speaking(tab: "CDP", page: str, failures: list[str]) -> None:
    """说完一句话之后，她还看得见、还够得到。见 FOCUS_AFTER_SPEAKING 的说明。"""
    if page != "/elder":
        return
    result = tab.send(
        "Runtime.evaluate", expression=FOCUS_AFTER_SPEAKING,
        awaitPromise=True, returnByValue=True,
    )["result"].get("value") or {}
    if result.get("skip"):
        failures.append(f"{page} Focus Mode 检查跳过了：{result['skip']}——这一页应该有打字入口")
        return
    if result.get("fail"):
        failures.append(f"{page} Focus Mode：{result['fail']}")
        return
    if not result.get("bubbles"):
        failures.append(f"{page} Focus Mode：说了一句话之后对话区里一条气泡都没有")
        return

    # **没造出被测状态时要说出来，不能静默通过。**
    #
    # 这道检查真正要量的是"玻璃盒卡出现之后那一列还装不装得下"。而卡是否出现取决于
    # 后端对这张账单的幂等判断：同一张账单第二次提交返回 `duplicate_blocked`，于是
    # 没有 `task_id`、`showGlassBox` 直接清空、卡高度为 0——一列东西轻松装得下，
    # 下面每一条断言都过，检查报绿。
    #
    # CDP 实测两种结果：卡不在时 relianceHost 高 0，卡在时 222。也就是说这道检查
    # **是否测到东西，取决于数据库当前历史和执行顺序**。我为它写的两次变异都没红，
    # 两次都是恰好落在"卡不在"那一边。
    #
    # 几何判据的权威已经搬到 `check_focus_geometry.py`（构造三组 card 直接调
    # `renderGlassBox`，5 视口 × 3 Case，三路变异全红）。这一道留着，是因为它测的是
    # "**真的**说一句话"这条端到端路径——那是另一件事，仍然值得每轮跑。
    #
    # 但它必须诚实：跑不到被测场景时要说"没造出来"，而不是把"什么都没测到"记成通过。
    if not result.get("relianceKids"):
        failures.append(
            f"{page} Focus Mode：说完话之后玻璃盒卡没有出现（relianceHost 是空的），"
            "这一轮没有造出被测状态——多半是这张账单已经被 duplicate_blocked。"
            "几何判据看 check_focus_geometry.py（那一道是确定性的）；"
            "这一条报红是为了不把「什么都没测到」记成通过。"
        )
        return

    #: 她必须看得见自己刚说的那句话。80px ≈ 两行 17px 正文加行距，比这更少就只剩半句。
    if result["chatH"] < 80:
        failures.append(
            f"{page} Focus Mode 说完一句话之后对话区只有 {result['chatH']}px"
            f"（里面有 {result['bubbles']} 条气泡、内容 {result['chatScrollH']}px）"
            "——她看不见自己刚说的话"
        )
    #: 输入行必须整块在容器内。`.stage` 是 overflow: hidden，掉出去就够不到。
    if result["composerBottom"] > result["stageBottom"] + 1:
        failures.append(
            f"{page} Focus Mode 的输入行底边在 {result['composerBottom']}，"
            f"而容器底边是 {result['stageBottom']}——超出 "
            f"{result['composerBottom'] - result['stageBottom']}px，她够不到发送键。"
            f"各块高度：{result['kids']}"
        )
    #: 通式：没有任何一块被裁掉。只查上面两条的话，下一个被挤出去的块会安静消失。
    if result["kidsSum"] > result["focusH"] + 2:
        failures.append(
            f"{page} Focus Mode 里各块高度之和 {result['kidsSum']} > 容器 {result['focusH']}"
            f"——有东西被 overflow: hidden 吃掉了：{result['kids']}"
        )


def main() -> int:
    # 端口在这里才定下来。写死的端口会让两份同时跑的检查连到同一个 DevTools
    # 端点上，而那种污染的失败模式是「控件数变小」，看起来像覆盖回退。
    global PORT, DEVTOOLS_PORT, BASE
    PORT = _free_port()
    DEVTOOLS_PORT = _free_port()
    BASE = f"http://127.0.0.1:{PORT}"
    try:
        import websocket  # type: ignore
    except ImportError:
        # 缺依赖是**硬失败**，不是跳过。
        #
        # `websocket-client` 此前不在 requirements.lock.txt 里（那里只有 uvicorn 的
        # `websockets`），而 CI 只装 lock 文件。后果：CI 上这个检查、对比度检查、
        # 截图检查全部走到这一行 `return 0`，验证链紧接着打印 PASS，最后打印
        # "ALL V6 DETERMINISTIC VERIFICATION STAGES PASSED"——**CI 从来没有在真实
        # 浏览器里加载过任何一个页面**。把 care.js 第一行改回那个让两整页按钮全死的
        # TDZ 缺陷，CI 照样全绿。
        #
        # 依赖现在声明了，所以 import 失败意味着环境坏了，而不是"这台机器没装调试
        # 工具所以我们跳过运行时验证"。宁可红。
        print("FAIL page_runtime: websocket-client 没装。它在 requirements 里——"
              "装上它，不要跳过运行时验证。")
        return 1
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
    #: 每页按了多少。总数掉了的时候，只有这份分页明细能说出是哪一页掉的
    #: ——而「哪一页」决定了那是修正还是新缺陷。
    per_page: dict[str, int] = {}
    orb_states = 0
    beats = 0
    try:
        for _ in range(80):
            try:
                with open_local(f"{BASE}/ping", timeout=2):
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
                with open_local(
                    f"http://127.0.0.1:{DEVTOOLS_PORT}/json/version", timeout=2
                ) as r:
                    ws_url = json.loads(r.read())["webSocketDebuggerUrl"]
                break
            except Exception:
                time.sleep(0.4)
        if not ws_url:
            # **失败，不是跳过。**
            #
            # 上面那处 `if not chrome` 的 SKIP 是诚实的：一台没装 Chrome 的机器
            # 确实跑不了这个检查。而走到这里意味着 Chrome **在**，只是 DevTools 没起来
            # ——那是一个真的故障（端口被占、profile 被锁、上一次的进程没退干净）。
            #
            # 它原先打印 SKIP 然后 `return 0`，也就是在整条验证栈里留下一个永远绿的
            # 格子。这个项目的规则是"禁止伪造 PASS"：跑不起来的检查必须响亮地红。
            print(f"FAIL page_runtime: Chrome 在（{chrome}）但 DevTools 没起来"
                  f"——端口 {DEVTOOLS_PORT} 上没有 /json/version。"
                  "常见原因：上一次的 headless 进程没退干净，或者 profile 被锁。")
            return 1

        browser = CDP(ws_url, websocket)
        for page in PAGES:
            target = browser.send("Target.createTarget", url="about:blank")["targetId"]
            with open_local(
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
                # 整页都在手机视口下跑，而不是只在溢出探针那一小段里临时切一下。
                #
                # 此前 `press_every_control` 跑在 headless 默认的桌面宽度上——一个
                # 手机适老应用，被按的是一个没人会拿到的布局。差别不是理论上的：
                # 老人端的 `.rail.sheet` 在宽屏是常驻侧栏、在手机才是抽屉，标签栏在
                # 桌面宽度是 `display: none`。也就是说"每个按钮都按过"说的是另一套
                # 界面。在 navigate **之前**设置，媒体查询才能从加载那一刻就生效。
                tab.send("Emulation.setDeviceMetricsOverride",
                         width=PHONE[0], height=PHONE[1], deviceScaleFactor=1, mobile=True)
                tab.send("Page.navigate", url=BASE + page)
                tab.drain(SETTLE_SECONDS)
                failures.extend(collect(tab.events, page))
                check_no_raw_js_values(tab, page, failures)
                check_sprite_icons(tab, page, failures)
                check_no_horizontal_overflow(tab, page, failures)
                # **必须在点击遍历之前**：遍历会把界面按到各种状态（包括开 Focus
                # Mode，而那会用 CSS 把「今天」整块藏起来），这道检查要的是首屏。
                tab.events.clear()
                if not os.environ.get("YOUHUO_SKIP_PENDING_MED"):
                    check_pending_medication_is_visible(tab, page, failures)
                    failures.extend(collect(tab.events, f"{page} 待确认用药"))
                tab.events.clear()
                check_glass_box(tab, page, failures)
                failures.extend(collect(tab.events, f"{page} 玻璃盒"))
                tab.events.clear()
                per_page[page] = press_every_control(tab, page, failures)
                clicked += per_page[page]
                # 说完一句话之后那一屏还能不能用。**必须在点击遍历之后**：
                # 遍历会把界面按到各种状态，而这道检查要的是"她真的说了一句"之后的
                # 那一屏，不是一个空的 Focus Mode。
                tab.events.clear()
                check_focus_mode_after_speaking(tab, page, failures)
                failures.extend(collect(tab.events, f"{page} 说完一句话之后"))
                orb_states += check_voice_orb_states(tab, page, failures)
                beats += check_judge_story(tab, page, failures)
                check_identity_self_heal(tab, page, failures)
                if page == "/elder":
                    # 放在 /elder 之后、用同一个浏览器：此时 localStorage 已经有身份了，
                    # 所以这个检查自己会先清掉它，模拟真正的冷启动。
                    check_multi_tab_identity(
                        browser, f"http://127.0.0.1:{DEVTOOLS_PORT}", websocket, failures
                    )
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
    # 态数必须印出来。一个"检查跑了但什么都没量到"的检查，和没有这个检查是一回事，
    # 而它在汇总行里看起来一模一样地绿。
    if orb_states < 10:
        print(f"FAIL page_runtime: Voice Orb 只量到 {orb_states} 态——检查没真的跑起来")
        return 1
    if beats < 7:
        print(f"FAIL page_runtime: 评委页七拍只演了 {beats} 拍——检查没真的跑起来")
        return 1
    print("  按到的控件（按页）：" + "、".join(
        f"{page} {count}" for page, count in per_page.items()))
    print(f"OK page_runtime: {len(PAGES)} 个页面加载干净，{clicked} 个控件逐个按过，"
          f"Voice Orb {orb_states} 态在关掉动效后两两可辨，评委页 {beats} 拍演完且全中文，"
          f"手机视口无横向溢出、无障碍五项通过，无异常、无 console.error、无失败请求")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
