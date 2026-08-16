"""每一页在**每一个宽度**下，是不是真的走得出去。

## 为什么要有这个脚本

`test_tabbar.py` 已经有一条叫 `test_every_screen_has_some_way_out` 的判据，
它的 docstring 自己写着它是「被一次真实的死路换来的」。但它查的是 markup 里
有没有 `class="tabbar"` —— `family.html` 有，于是算「有出口」。

**它从不问这个出口在哪个宽度下可见。**

而 `pages.css` 里那条 `.tabbar:not(.elder-tabs) { display: none; }` 让
`/family` 在 ≥761px 下既没有底部导航、也没有 back-link（`family.html` 的
back-link 是 **0 个**；`care.html`、`trust.html` 各 1 个）。manifest 是
`display: standalone`，所以没有浏览器后退键；iOS standalone 连边缘滑动返回
也没有。那一页在平板竖屏上是**关不掉的死路**，而闸门全绿。

同一份 markup 在两个宽度下一个能走一个走不了 —— 这类问题只有在浏览器里
按宽度各量一次才测得到。

## 出口怎么定义

**不用 class 白名单。** 量现状的时候发现 `/elder` 的四个 tab 全是页内
`#hash`，一个都不通向别的路由 —— 也就是说「elder 的出口是 4 个 tab」这句
写在旧判据注释里的话本身是错的。按 class 认出口会把页内切换当成出口。

所以按**行为**认：

  ① 一个 `<a>`，href 解析之后 pathname 和当前页不同 —— 它真的离开这一页
  ② `#leaveApp`（`/elder` 的「退出办事模式」，它是个 button，不是链接）

然后要求它**真的看得见**：`checkVisibility()` 过、包围盒非零、不在
`[inert]` / `[aria-hidden="true"]` 里面、没有被平移到视口外、可聚焦。
只查 `display: none` 是不够的 —— `.sheet-backdrop` 那次教过，
「规则写在哪个 media query 里」决定它生不生效，而 markup 看不出来。

## 两档，因为其中一档是已知未修项

  第一档（红）  这个宽度下**一个可见出口都没有** —— 死路
  第二档（记录）出口存在但要滚到文档底部才看得到

## 变异证明（`MUTATION_PROOF_EXITS`）与一个没查清的事实

四个变异体：样式表藏掉 `/elder` 唯一的出口 → 红；把 `.tabbar` 和 `.segmented`
一起藏掉 → `/family` 红（**只藏 `.tabbar` 是绿的，而绿是对的**：顶部那条
`.segmented` 有 `data-section="mine"`，一次页内点击就到得了装着出口的面板。
⚠ Phase C 要退役 `.segmented`，那一天这条规则就变成真死路）；把出口缩到 6px
→ 红；同一条规则只写在注释里 → 放行。

**没查清的一件事**：往 `pages.css` 末尾追加
`body a[href^="/"] { width: 6px !important }`，其他页面的 `.tab` 确实变成
`6×56`，但 `/` 上那两个 `.role-pick` 尺寸不变（`index.html` 的 `<link>` 是有的，
四层都引了）。原因未定。写在这里而不是当成「首页很健壮」——**它是一个未解事实，
不是一个结论**。

第二档是当前真实状态：宽屏下那条静态导航排在 `<main>` 的最后一个孩子，
于是 `/elder` 的 y=1635（文档 1748）、`/family` y=983（1096）、
`/care` y=1012（1125）。它是 Phase C 要修的东西，这里**如实打印**、不算通过、
也不算失败 —— 把它算成 PASS 就是伪造，算成 FAIL 会让这个闸门从落地那天起
就是红的，没人会再看它。
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.error
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))

from youhuo.surfaces import ROUTES  # noqa: E402  (要先接上 sys.path)
# 本机请求一律绕开系统代理，理由见 localhttp.py（一次真实的
# 「服务未能启动」其实是代理把请求挂死了）。
from localhttp import open_local

#: 四个宽度都有具体理由，不是随手挑的整数。
#:
#:   320×568  在售最小屏（SE 一代）。这个项目已经在 320 下抓到过孤字与 139px 溢出。
#:   390×844  主力手机。
#:   768×1024 平板竖屏，正好压在 `760px` 那条断点的**右边**一格 —— 死路就在这里。
#:   900×1200 出事故的那个实测宽度（`pages.css:2295-2312` 用 18 行记着代价）。
#:   1440×900 笔记本。
VIEWPORTS = ((320, 568), (390, 844), (768, 1024), (900, 1200), (1440, 900))

PORT = 0
DEVTOOLS_PORT = 0
BASE = ""

_ISSUED_PORTS: set[int] = set()


def _free_port() -> int:
    """向系统要一个没发过的端口。

    照抄 `check_contrast.py:_free_port()` 的两条教训：「bind 0、读号、close」
    连调两次会拿到同一个号，所以要记住本进程发过的号；而且**不要保持 socket
    打开来占位** —— 那样 uvicorn 也 bind 不上。
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
            msg = json.loads(self.ws.recv())
            if msg.get("id") == self.n:
                if "error" in msg:
                    raise RuntimeError(f"{method}: {msg['error']}")
                return msg.get("result", {})

    def close(self) -> None:
        try:
            self.ws.close()
        except Exception:  # noqa: BLE001
            pass


def find_chrome() -> str | None:
    for candidate in (
        r"C:\Program Files\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
        "google-chrome", "chromium", "chromium-browser",
    ):
        if os.path.isabs(candidate):
            if os.path.exists(candidate):
                return candidate
        elif shutil.which(candidate):
            return shutil.which(candidate)
    return None


#: 在页面里跑。返回这一页所有「出口候选」及其可见性事实。
#:
#: `liveness` 那一项是必须的：上一轮有一次运行时检查在**服务器已经死了**的
#: 情况下报出「0 个 console error、导出全是 undefined」，我差点去找一个不存在
#: 的 bug —— 每一次导航都落在 Chrome 的错误页上，而错误页确实没有报错。
#: 所以先证明「这是优活的页面」，再谈量到了什么。
PROBE = r"""
(async () => {
  // 等**页面真的准备好**，不是等一个固定的 1200ms。
  //
  // 原写法是 `setTimeout(r, 1200)`。机器空闲时够用，一旦被别的活儿压着就不够：
  // 本轮在一次 pytest 跑了 208 秒（平时 120 秒）的负载下，这道闸门报了
  // 「1 个 路由×宽度 走不出去」，而同一份代码单独连跑三次全绿。
  // 出口有一部分是页面脚本渲染出来的（`defer`，还要等接口回来），1200ms 没到
  // 就去数，数到的是「还没画出来」，报出来的却是「这一页走不出去」——
  // 一个偶发的红，比一直红更糟：它教人把红当噪音，重跑一次就过去了。
  //
  // 改成轮询到出口出现为止，最多等 8 秒。快的时候比原来还快（不用干等 1200ms），
  // 慢的时候才多等，而且**等不到照样报红**——这不是把判据放宽，是把「没准备好」
  // 和「真的没有出口」分开。
  const deadline = Date.now() + 8000;
  const settled = () => document.readyState === 'complete';
  const anyExit = () => [...document.querySelectorAll('a[href]')].some(a => {
    try { return new URL(a.href, location.href).pathname.replace(/\/$/, '')
                 !== (location.pathname.replace(/\/$/, '') || '/'); }
    catch (_) { return false; }
  });
  while (Date.now() < deadline && !(settled() && anyExit())) {
    await new Promise(r => setTimeout(r, 100));
  }
  // 脚本跑完之后再给一拍，让它把渲染出来的节点插进去。
  await new Promise(r => setTimeout(r, 250));

  const here = location.pathname.replace(/\/$/, '') || '/';
  const liveness = !!document.querySelector('link[href*="/static/tokens.css"]');

  const hidden = el => {
    // `inert` 与 `aria-hidden` 都不改 computed style，但都让元素点不到、
    // 读不到。事务详情那个 overlay 就是靠这两个属性关掉的。
    for (let n = el; n; n = n.parentElement) {
      if (n.hasAttribute('inert')) return 'inert';
      if (n.getAttribute('aria-hidden') === 'true') return 'aria-hidden';
    }
    return null;
  };

  // **按元素去重，不按选择器。** 第一版把 `#leaveApp` 单独加了一条，结果
  // `/elder` 报「候选 2、可用 0」而那两条的 class 和文字**完全一样**——
  // 因为 `id="leaveApp"` 就在那个 `a.fam-link` 上，一个元素被数了两遍。
  // 「候选 2」这个数字本身是假的，而它看起来完全正常。
  const cands = new Map();
  const add = (el, kind, to) => { if (el && !cands.has(el)) cands.set(el, {kind, to}); };
  document.querySelectorAll('a[href]').forEach(a => {
    let path;
    try { path = new URL(a.href, location.href).pathname.replace(/\/$/, '') || '/'; }
    catch (e) { return; }
    if (path === here) return;              // 页内 hash 不是出口
    add(a, 'link', path);
  });
  add(document.getElementById('leaveApp'), 'leaveApp', '(退出办事模式)');

  const vh = window.innerHeight, vw = window.innerWidth;

  // 祖先链上**第一个**不画的元素才是原因。「display: none」是结论，
  // 而三种可能的原因处置完全不同：被 media query 藏了（真死路）、
  // 在一个 `hidden` 的面板里（两步可达）、或者根本就是别的东西压着它。
  const blame = el => {
    for (let n = el; n && n !== document.documentElement; n = n.parentElement) {
      // 关着的 `<details>` **不靠 display:none 藏内容**——它的祖先链上
      // `getComputedStyle` 一路都是 block，所以下面那个循环找不到任何罪魁，
      // 报出来是「不画，但说不出为什么」。实测撞到过：`/stage` 的两个出口都在
      // 一个收起的 `<details id="directorDeck">` 里，闸门只能说死路，说不出
      // 死在哪儿——一个指不出原因的失败，人只能靠猜。
      if (n.tagName === 'DETAILS' && !n.open) {
        return {
          tag: 'details', id: n.id || '',
          cls: (n.className || '').toString().slice(0, 34),
          panel: '',
          // `<details>` 是**用户可以自己打开**的，和 `[hidden]` 分区同一档：
          // 一步到不了，但两步到得了——前提是它的 `<summary>` 或触发按钮可见。
          byAttr: true,
          display: 'details-closed', vis: 'visible', op: '1',
        };
      }
      const cs = getComputedStyle(n);
      if (cs.display === 'none' || cs.visibility === 'hidden' || +cs.opacity === 0) {
        return {
          tag: n.tagName.toLowerCase(), id: n.id || '',
          cls: (n.className || '').toString().slice(0, 34),
          panel: n.getAttribute('data-panel') || '',
          // `[hidden]` 属性 = 页内分区切换（`initSections` 就是这样开合面板的）；
          // 没有 `[hidden]` 而仍然不画 = 样式表把它藏了，那是另一回事。
          byAttr: n.hasAttribute('hidden'),
          display: cs.display, vis: cs.visibility, op: cs.opacity,
        };
      }
    }
    return null;
  };

  // 哪些页内分区**真的切得过去**：一个可见的切换控件，它指着那个分区。
  //
  // 第一版只数「这一页有没有可见的切换控件」，不问它指哪儿。变异证明立刻抓到：
  // 把 `.tabbar` 整条藏掉之后，`/family` 的三个出口全在 `mine` 面板里，而闸门
  // 因为「页面上还有别的可见 .tab」就判成两步可达 —— 那正是要防的那次事故。
  // 「有一个开关」和「有一个能开这扇门的开关」不是一回事。
  //
  // 配对靠 `data-section`（切换器）对 `data-panel`（面板）。这两个名字不一样，
  // 是这个项目的既有约定，猜成 `data-panel-target` 会一个都匹配不上。
  // 可见的 `<summary>` / `aria-controls` 触发器，能打开哪些收起的 `<details>`。
  //
  // 和下面的分区切换器是同一件事的另一种形态：一个人点得到它，就够得着里面的东西。
  const openableDetails = new Set();
  document.querySelectorAll('details:not([open])').forEach(d => {
    const summary = d.querySelector('summary');
    const trigger = d.id
      ? document.querySelector(`[aria-controls="${d.id}"]`) : null;
    for (const t of [summary, trigger]) {
      if (!t) continue;
      if (!t.checkVisibility({checkOpacity: true, checkVisibilityCSS: true})) continue;
      const r = t.getBoundingClientRect();
      if (r.height >= 8 && r.width >= 8) { openableDetails.add(d); break; }
    }
  });

  const reachable = new Set();
  document.querySelectorAll('[data-section], [role="tab"], a[href^="#"]').forEach(el => {
    if (!el.checkVisibility({checkOpacity: true, checkVisibilityCSS: true})) return;
    const r = el.getBoundingClientRect();
    if (r.height < 8 || r.width < 8) return;
    const target = el.getAttribute('data-section')
      || el.getAttribute('aria-controls')
      || (el.getAttribute('href') || '').replace(/^#/, '');
    if (target) reachable.add(target);
  });

  const rows = [...cands.entries()].map(([el, {kind, to}]) => {
    const r = el.getBoundingClientRect();
    const block = hidden(el);
    const paints = typeof el.checkVisibility === 'function'
      ? el.checkVisibility({checkOpacity: true, checkVisibilityCSS: true})
      : getComputedStyle(el).display !== 'none';
    // 被平移到视口外（`transform: translateX(-200%)` 那类藏法）也不算可见。
    const onscreen = r.right > 0 && r.left < vw && r.bottom > 0;
    const sized = r.width >= 8 && r.height >= 8;
    const focusable = el.tabIndex >= 0 && !el.disabled;
    // 「不用滚就看得见」：包围盒和当前视口有交集。
    const firstScreen = r.top < vh && r.bottom > 0;
    const culprit = paints ? null : blame(el);
    return {
      kind, to,
      label: (el.textContent || '').trim().slice(0, 12) || el.getAttribute('aria-label') || '',
      cls: (el.className || '').toString(),
      y: Math.round(r.top + window.scrollY), h: Math.round(r.height), w: Math.round(r.width),
      bottom: Math.round(r.bottom + window.scrollY),
      block, paints, onscreen, sized, focusable, firstScreen, culprit,
      usable: !block && paints && onscreen && sized && focusable,
      // 只差一次页内操作。两条路各有各的条件，缺一不可：
      //
      //   分区：`byAttr`（样式表藏起来的东西点不出来）**并且**确实有一个可见
      //         控件指着装它的那个分区
      //   details：这个收起的 `<details>` 有一个**可见的** summary 或
      //            `aria-controls` 触发器
      //
      // 两边都要求「那个开关真的看得见」。「有一个开关」和「有一个能开这扇门的
      // 开关」不是一回事——变异证明抓到过第一版把前者当成后者。
      twoStep: !paints && (
        (!!culprit && culprit.byAttr && !!culprit.panel && reachable.has(culprit.panel))
        || [...openableDetails].some(d => d.contains(el))
      ),
    };
  });
  // 文档高度取三者最大。第一版只用 `documentElement.scrollHeight`，于是
  // `/stage` 报出「出口在 y=2692 / 文档 2425」——元素在文档底部之外，
  // 这个数不可能对。荒谬的输出是 bug 唯一可靠的信号，所以别再印那个数。
  const docH = Math.max(document.documentElement.scrollHeight,
                        document.body.scrollHeight,
                        ...rows.map(r => r.bottom), 1);
  return JSON.stringify({liveness, here, docH, vh,
                         reachable: [...reachable], rows});
})()
"""


def main() -> int:
    global PORT, DEVTOOLS_PORT, BASE
    PORT = _free_port()
    DEVTOOLS_PORT = _free_port()
    BASE = f"http://127.0.0.1:{PORT}"

    try:
        import websocket  # type: ignore
    except ImportError:
        # 和 check_contrast / check_page_runtime 同一个理由：跳过分支会让整层
        # 验证消失而链条照样打印 PASS。依赖已声明，缺了就报红。
        print("FAIL exits_v6: websocket-client 没装。它在 requirements 里——"
              "装上它，不要跳过出口验证。")
        return 1
    chrome = find_chrome()
    if not chrome:
        print("SKIP exits_v6: 没找到 Chromium 系浏览器")
        return 0

    # 数据库落到临时目录：这个脚本自己起服务器，落在仓库里就是一次
    # `check_artifacts_v6` 抓过的 .db 泄漏。
    db_dir = Path(tempfile.mkdtemp(prefix="youhuo-exits-db-"))
    env = {
        **os.environ,
        "PYTHONPATH": str(ROOT / "backend"),
        "YOUHUO_DEMO_MODE": "true",
        "YOUHUO_DB_PATH": str(db_dir / "youhuo.db"),
        # 用 `normal` 而不是 pytest 默认的 `empty`：空态的文档更短，出口更容易
        # 落在首屏里。「空态掩盖布局问题」这条在这个项目里已经付过一次代价。
        "YOUHUO_DEMO_STATE": os.environ.get("YOUHUO_DEMO_STATE", "normal"),
    }
    server = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "youhuo.api:app", "--host", "127.0.0.1",
         "--port", str(PORT), "--app-dir", "backend", "--log-level", "warning"],
        cwd=ROOT, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )

    browser = None
    cdp = None
    dead_ends: list[str] = []
    below_fold: list[str] = []
    two_step: list[str] = []
    problems: list[str] = []
    try:
        for _ in range(80):
            try:
                open_local(f"{BASE}/ping", timeout=2).read()
                break
            except Exception:  # noqa: BLE001
                time.sleep(0.25)
        else:
            print(f"FAIL exits_v6: 服务器没起来（{BASE}）")
            return 1

        # 全新 profile。持久 profile 里那个 service worker 会跨轮存活并供应
        # **上一次构建**的 HTML —— check_contrast.py 用注释记着这一课：
        # 四层 CSS 那一轮它就是这样量了一个不存在的版本。
        profile = Path(tempfile.mkdtemp(prefix="youhuo-exits-"))
        browser = subprocess.Popen(
            [chrome, "--headless=new", "--disable-gpu", "--no-sandbox", "--hide-scrollbars",
             "--no-first-run", "--no-default-browser-check", "--disable-extensions",
             "--force-device-scale-factor=1",
             f"--remote-debugging-port={DEVTOOLS_PORT}", "--remote-allow-origins=*",
             f"--user-data-dir={profile}", "about:blank"],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        ws_url = None
        for _ in range(80):
            try:
                with open_local(
                        f"http://127.0.0.1:{DEVTOOLS_PORT}/json/version", timeout=1) as resp:
                    ws_url = json.loads(resp.read())["webSocketDebuggerUrl"]
                break
            except Exception:  # noqa: BLE001
                time.sleep(0.25)
        if not ws_url:
            print("FAIL exits_v6: DevTools 没起来")
            return 1

        cdp = CDP(ws_url, websocket)
        target = cdp.send("Target.createTarget", url="about:blank")["targetId"]
        session = cdp.send("Target.attachToTarget", targetId=target, flatten=True)["sessionId"]

        def sess(method: str, **params):
            self_n = cdp.n + 1
            cdp.n = self_n
            cdp.ws.send(json.dumps(
                {"id": self_n, "method": method, "params": params, "sessionId": session}))
            while True:
                msg = json.loads(cdp.ws.recv())
                if msg.get("id") == self_n:
                    if "error" in msg:
                        raise RuntimeError(f"{method}: {msg['error']}")
                    return msg.get("result", {})

        for domain in ("Page", "Runtime"):
            sess(f"{domain}.enable")

        for width, height in VIEWPORTS:
            sess("Emulation.setDeviceMetricsOverride",
                 width=width, height=height, deviceScaleFactor=1, mobile=width < 761)
            print("=" * 76)
            print(f"{width}×{height}")
            print("=" * 76)
            for route in ROUTES:
                sess("Page.navigate", url=BASE + route)
                raw = sess("Runtime.evaluate", expression=PROBE,
                           awaitPromise=True, returnByValue=True)["result"].get("value")
                if not raw:
                    problems.append(f"{route} @ {width}: 探针没有返回值")
                    print(f"  ✗ {route:<9} 探针没有返回值")
                    continue
                info = json.loads(raw)
                if not info["liveness"]:
                    # 这一条是防「量了一个错误页还报得头头是道」。
                    problems.append(f"{route} @ {width}: 这不是优活的页面（tokens.css 没加载）")
                    print(f"  ✗ {route:<9} 这不是优活的页面 —— 别信下面的数字")
                    continue

                usable = [r for r in info["rows"] if r["usable"]]
                first = [r for r in usable if r["firstScreen"]]
                two = [r for r in info["rows"] if r["twoStep"]]
                tag = f"{route} @ {width}×{height}"
                if not usable and not two:
                    dead_ends.append(tag)
                    mark, note = "✗✗", "死路：一个出口都到不了"
                elif not usable:
                    # 出口在一个 `[hidden]` 面板里，而页内切换控件是可见的。
                    # 点一下「我的」就走得出去——不是死路，但也不是一步可达。
                    two_step.append(tag)
                    mark, note = "·", (f"出口要先切一次页内分区（藏在 "
                                       f"{two[0]['culprit']['panel'] or two[0]['culprit']['cls']} 里）")
                elif not first:
                    below_fold.append(tag)
                    lo = min(r["y"] for r in usable)
                    mark, note = "·", f"出口要滚下去才看得到（最高的在 y={lo} / 文档 {info['docH']}）"
                else:
                    mark, note = "✓", ""
                print(f"  {mark} {route:<9} 出口 {len(info['rows'])} · 一步可用 {len(usable)}"
                      f" · 首屏 {len(first)} · 两步 {len(two)}   {note}")
                for r in info["rows"]:
                    if r["usable"]:
                        continue
                    why = ("被 " + r["block"]) if r["block"] else \
                          ("不画" if not r["paints"] else
                           "被移出视口" if not r["onscreen"] else
                           f"太小 {r['w']}×{r['h']}" if not r["sized"] else
                           "不可聚焦")
                    print(f"        － {r['to']:<12}{r['label'][:10]:<11}{why}"
                          f"   [{r['cls'][:26]}]")
                    c = r["culprit"]
                    if c:
                        # 「不画」不可行动；祖先链上第一个不画的那个才是。
                        kind = "页内分区（[hidden]）" if c["byAttr"] else "样式表藏的"
                        print(f"             ↑ <{c['tag']} id={c['id'] or '-'}"
                              f" class={c['cls'] or '-'} data-panel={c['panel'] or '-'}>"
                              f" {c['display']}/{c['vis']}/{c['op']} — {kind}")
            print()
    finally:
        if cdp:
            cdp.close()
        for proc in (browser, server):
            if proc:
                proc.terminate()
                try:
                    proc.wait(timeout=10)
                except Exception:  # noqa: BLE001
                    proc.kill()
        shutil.rmtree(db_dir, ignore_errors=True)

    print("=" * 76)
    if two_step:
        print(f"KNOWN exits_v6: {len(two_step)} 处出口要先切一次页内分区才露出来")
        for tag in two_step:
            print(f"        {tag}")
    if below_fold:
        # 如实打印，不算通过也不算失败 —— 见模块 docstring 的「两档」。
        print(f"KNOWN exits_v6: {len(below_fold)} 处出口在首屏之外（Phase C 要修的"
              f"「静态导航排在 main 最后一个孩子」）")
        for tag in below_fold:
            print(f"        {tag}")
    if problems:
        for line in problems:
            print(f"FAIL exits_v6: {line}")
    if dead_ends:
        print(f"FAIL exits_v6: {len(dead_ends)} 个 路由×宽度 走不出去")
        for tag in dead_ends:
            print(f"        {tag}")
        print("        manifest 是 display: standalone —— 没有浏览器后退键，"
              "iOS standalone 连边缘滑动返回都没有。")
    if not dead_ends and not problems:
        print(f"PASS exits_v6: {len(ROUTES)} 条路由 × {len(VIEWPORTS)} 个宽度，"
              f"每一格都至少有一个真的可用的出口")
    print("=" * 76)
    return 1 if (dead_ends or problems) else 0


if __name__ == "__main__":
    raise SystemExit(main())
