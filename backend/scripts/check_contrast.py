"""WCAG AA contrast audit of every shipped page, in light and dark mode.

This product is built for older adults with reduced vision and its own design
brief calls for high contrast, so a failing ratio is a product defect, not a
style preference. Ratios are measured from computed styles in a real browser -
`color-mix()` and CSS variables cannot be checked by reading the stylesheet.

Requires Chrome; skips cleanly when it is not installed.
"""

from __future__ import annotations

import base64
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.error
from pathlib import Path
# 本机请求一律绕开系统代理，理由见 localhttp.py（一次真实的
# 「服务未能启动」其实是代理把请求挂死了）。
from localhttp import open_local

ROOT = Path(__file__).resolve().parents[2]
#: /stage 也要查：它是答辩时投在大屏上的那一页，控制条的对比度和触控尺寸和产品
#: 页面一样要达标——把它排除掉就等于说"演示环境不用无障碍"。
PAGES = ["/", "/elder", "/family", "/care", "/trust", "/judge", "/stage"]
#: 两个端口都在运行时向系统要，不写死——见 `_free_port()` 的说明。
PORT = 0
BASE = f"http://127.0.0.1:{PORT}"
DEVTOOLS_PORT = 0

AUDIT_JS = r"""
(async () => {
  await new Promise(r => setTimeout(r, 1500));
  const cvs = document.createElement('canvas'); cvs.width = cvs.height = 1;
  const ctx = cvs.getContext('2d', {willReadFrequently: true});
  const toRGB = css => { ctx.fillStyle = '#000'; ctx.fillStyle = css; ctx.fillRect(0,0,1,1);
    const d = ctx.getImageData(0,0,1,1).data; return [d[0],d[1],d[2]]; };
  const srgb = c => { c/=255; return c<=0.03928 ? c/12.92 : Math.pow((c+0.055)/1.055,2.4); };
  const lum = ([r,g,b]) => 0.2126*srgb(r)+0.7152*srgb(g)+0.0722*srgb(b);
  const ratio = (a,b) => { const l1=lum(a),l2=lum(b); return (Math.max(l1,l2)+0.05)/(Math.min(l1,l2)+0.05); };
  // Returns null when the backdrop is a gradient/image: its effective colour
  // varies across the element, so a single ratio would be meaningless. Those
  // combinations are checked by eye instead of being reported as false alarms.
  const alphaOf = css => { const m = css.match(/rgba?\(([^)]+)\)/); if (!m) return 1;
    const parts = m[1].split(',').map(s => parseFloat(s)); return parts.length > 3 ? parts[3] : 1; };
  // Walks ancestors compositing translucent layers. Returns null when a
  // gradient/image is in the stack: the backdrop varies across the element, so
  // one ratio would be meaningless rather than merely wrong.
  const bgOf = el => { let n = el; let acc = null;
    while (n && n !== document.documentElement) {
      const cs = getComputedStyle(n);
      if (cs.backgroundImage && cs.backgroundImage !== 'none') return null;
      const c = cs.backgroundColor; const a = alphaOf(c);
      if (c && a > 0) {
        const rgb = toRGB(c.replace(/rgba?\(([^)]+)\)/, (_, p) => {
          const v = p.split(',').map(s => parseFloat(s)); return `rgb(${v[0]},${v[1]},${v[2]})`; }));
        acc = acc === null ? {rgb, a} : acc;
        if (a >= 1) return acc.a >= 1 ? acc.rgb
          : acc.rgb.map((v, i) => Math.round(v * acc.a + rgb[i] * (1 - acc.a)));
      }
      n = n.parentElement;
    }
    const page = toRGB(getComputedStyle(document.body).backgroundColor || '#fff');
    if (acc === null) return page;
    return acc.a >= 1 ? acc.rgb : acc.rgb.map((v, i) => Math.round(v * acc.a + page[i] * (1 - acc.a)));
  };
  // Accessible name: a wrapping or associated <label> counts, same as AT sees it.
  const accessibleName = el => {
    const own = (el.getAttribute('aria-label') || el.getAttribute('title')
                 || el.getAttribute('placeholder') || el.innerText || '').trim();
    if (own) return own;
    const byId = el.id && document.querySelector(`label[for="${CSS.escape(el.id)}"]`);
    if (byId && byId.innerText.trim()) return byId.innerText.trim();
    const wrapping = el.closest('label');
    return wrapping ? wrapping.innerText.trim() : '';
  };
  const problems = [];
  for (const el of document.querySelectorAll('body *')) {
    const cs = getComputedStyle(el);
    if (cs.display === 'none' || cs.visibility === 'hidden' || !el.offsetParent) continue;
    const text = [...el.childNodes].filter(n => n.nodeType === 3).map(n => n.textContent.trim()).join('');
    if (!text) continue;
    // Gradient-clipped headings paint their own fill; colour is transparent.
    if (/rgba\(0, 0, 0, 0\)|transparent/.test(cs.color)) continue;
    if (cs.webkitTextFillColor && /rgba\(0, 0, 0, 0\)/.test(cs.webkitTextFillColor)) continue;
    const bg = bgOf(el);
    if (bg === null) continue;
    const size = parseFloat(cs.fontSize), bold = parseInt(cs.fontWeight) >= 700;
    const need = (size >= 24 || (size >= 18.66 && bold)) ? 3.0 : 4.5;
    const r = ratio(toRGB(cs.color), bg);
    if (r < need) problems.push({text: text.slice(0, 20), cls: el.className.toString().slice(0, 30),
                                 size: Math.round(size), ratio: Math.round(r * 100) / 100, need});
  }
  // --- 非文字对比度（WCAG 1.4.11，3:1）---------------------------------
  //
  // 这一段是被一个真实缺陷换来的：深色模式下卡片图标的墨色是 #2F6FB5——浅色模式
  // 的值，从没为深色重定义过——在深色表面上只有 1.7–3.3:1，肉眼几乎看不见。
  // 而它**通过了全部 12 项检查**，因为上面那段只测文字。一个只测文字的对比度
  // 审计，对一个到处是图标的界面来说，是一张有洞的安全网。
  const icons = [];
  for (const svg of document.querySelectorAll('svg')) {
    const box = svg.getBoundingClientRect();
    if (box.width < 10 || box.height < 10) continue;      // 装饰性细线不算
    const cs = getComputedStyle(svg);
    if (cs.display === 'none' || cs.visibility === 'hidden') continue;

    //: 墨色要从**真正画出东西的那些形状**上取，不能取根 `<svg>` 自己的。
    //:
    //: 上一版读的是根节点的 `cs.stroke || cs.fill`。可插画的颜色全在子元素上，
    //: 根节点两个属性都是 SVG 初始值——`stroke: none`、`fill: rgb(0,0,0)`——
    //: 于是每一张插画都被当成"纯黑"来量。报出来的 `ink=rgb(0, 0, 0)` 是一个
    //: **从来没有被画到屏幕上的颜色**。着陆页那次它恰好也判红了（真实墨色
    //: #3b2f22 同样是近黑），结论对，路径错；换一张浅色插画就会反过来漏报。
    const shapes = svg.querySelectorAll('path,circle,rect,line,polygon,polyline,ellipse');
    const inks = new Set();
    for (const sh of (shapes.length ? shapes : [svg])) {
      const scs = getComputedStyle(sh);
      const v = (scs.stroke && scs.stroke !== 'none') ? scs.stroke : scs.fill;
      if (v && !/rgba\(0, 0, 0, 0\)|transparent|none/.test(v)) inks.add(v);
    }
    if (!inks.size) continue;
    //: 半透明的装饰水印不在这条判据的范围内，明确跳过而不是碰巧算及格。
    //: `.yh-stamp` 是 opacity 0.16 的印章，本来就该若隐若现；而下面按不透明
    //: 色值算出来的比值（4.97）与它实际的观感（约 1.1）根本不是一回事——
    //: 让它"通过"等于让这条判据在这里说了一句它并不知道的话。
    if (parseFloat(cs.opacity) < 0.3) continue;
    const bg = bgOf(svg.parentElement || svg);
    if (bg === null) continue;
    //: 取**最好**的那一笔，不是最差的。
    //:
    //: 判据问的是"这个图形认不认得出来"，而一个「奶油填充 + 墨色描边」的形状
    //: 在白底上靠描边、在深底上靠填充，总有一笔立得住。要求每一笔都单独对抗
    //: 页面底色，会把所有双色插画一律判红——那不是无障碍问题，是度量选错了。
    //: 对单色图标（这段最初要防的那种）最好与最差相同，原有的防护一点没减。
    let best = null;
    for (const v of inks) {
      const r = ratio(toRGB(v), bg);
      if (best === null || r > best.r) best = {r, v};
    }
    if (best.r < 3.0) {
      //: SVG 元素的 `className` 是 SVGAnimatedString，`.toString()` 出来是
      //: "[object SVGAnimatedString]"——那条告警**没法据以定位元素**。
      const host = svg.closest('[class]');
      const name = host
        ? (host.getAttribute('class') || host.tagName.toLowerCase())
        : svg.tagName.toLowerCase();
      icons.push({
        cls: name.slice(0, 34),
        ink: best.v, ratio: Math.round(best.r * 100) / 100,
      });
    }
  }

  const targets = [];
  for (const el of document.querySelectorAll('button, a, select, input')) {
    const b = el.getBoundingClientRect();
    if (b.width && b.height && (b.width < 40 || b.height < 40)) {
      targets.push({el: el.tagName + (el.id ? '#' + el.id : ''), w: Math.round(b.width), h: Math.round(b.height)});
    }
    if (!accessibleName(el)) targets.push({el: el.tagName + (el.id ? '#' + el.id : ''), unlabeled: true});
  }
  return JSON.stringify({contrast: problems, icons, targets});
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
            msg = json.loads(self.ws.recv())
            if msg.get("id") == self.n:
                if "error" in msg:
                    raise RuntimeError(f"{method}: {msg['error']}")
                return msg.get("result", {})


def find_chrome() -> str | None:
    for candidate in (
        r"C:\Program Files\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
        "google-chrome", "chromium", "chromium-browser",
    ):
        found = shutil.which(candidate) if not os.path.isabs(candidate) else (candidate if os.path.exists(candidate) else None)
        if found:
            return found
    return None


def main() -> int:
    # 见 `_free_port()`：端口不写死，否则并发跑的两份会互相打断。
    global PORT, DEVTOOLS_PORT, BASE
    PORT = _free_port()
    DEVTOOLS_PORT = _free_port()
    BASE = f"http://127.0.0.1:{PORT}"
    try:
        import websocket  # type: ignore
    except ImportError:
        # 与 check_page_runtime 同一个理由：这个跳过分支让 CI 上整层运行时验证消失，
        # 而验证链照样打印 PASS。依赖已声明，缺了就报红。
        print("FAIL contrast_v6: websocket-client 没装。它在 requirements 里——"
              "装上它，不要跳过对比度验证。")
        return 1
    chrome = find_chrome()
    if not chrome:
        print("SKIP contrast_v6: no Chromium browser found")
        return 0

    #: 数据库不许落在被检查的仓库里。
    #:
    #: 这里原先只设了 PYTHONPATH 和 YOUHUO_DEMO_MODE。uvicorn 以 `cwd=ROOT` 启动，
    #: 数据库路径是相对的，于是每跑一次对比度闸门就在 `ROOT/data/` 里生成一个
    #: 运行时数据库**和一把新的 HMAC 审计链密钥**——`check_artifacts_v6` 的
    #: `leaked_artifacts` 当场就能抓到它们。一个检查发布干不干净的工具链，自己
    #: 把发布弄脏了；而这个仓库的远端是公开的，有过审计密钥进公开仓库的前科。
    #:
    #: `check_layout_stability.py` 和 `check_focus_geometry.py` 早就为同一件事
    #: 付过代价并改成了临时目录（见前者第 132 行的注释），这一个当时没跟上。
    workdir = Path(tempfile.mkdtemp(prefix="youhuo-contrast-"))
    env = {**os.environ, "PYTHONPATH": str(ROOT / "backend"), "YOUHUO_DEMO_MODE": "true",
           "YOUHUO_DB_PATH": str(workdir / "contrast.db")}
    server = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "youhuo.api:app", "--host", "127.0.0.1",
         "--port", str(PORT), "--app-dir", "backend", "--log-level", "warning"],
        cwd=ROOT, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    browser_proc = None
    failures: list[str] = []
    try:
        for _ in range(80):
            try:
                with open_local(f"{BASE}/ping", timeout=2):
                    break
            except Exception:
                time.sleep(0.4)
        else:
            print("FAIL contrast_v6: server did not start")
            return 1

        # 每轮一个全新 profile，这一条不是可选项。
        #
        # 这个应用注册了 service worker 来缓存外壳，那正是它的用途。用持久
        # --user-data-dir，那个 worker 会跨轮存活并供应**上一次构建**的 HTML。
        # 样式表从一个 style.css 拆成四层的那一轮，它就骗过了这个检查：缓存里的旧
        # HTML 仍然引着已经删掉的 style.css，于是页面一条样式都没加载，报出来是
        # 满屏"对比度 1<4.5"——看起来像配色崩了，实际是在量一个不存在的版本。
        # shoot_pages.py 早就为同一件事付过代价，这里当时没跟上。
        profile = Path(os.environ.get("TEMP", "/tmp")) / "youhuo-contrast"
        shutil.rmtree(profile, ignore_errors=True)
        browser_proc = subprocess.Popen(
            [chrome, "--headless=new", "--disable-gpu", "--no-sandbox", "--hide-scrollbars",
             f"--remote-debugging-port={DEVTOOLS_PORT}", "--remote-allow-origins=*",
             f"--user-data-dir={profile}", "about:blank"],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        ws_url = None
        for _ in range(80):
            try:
                with open_local(f"http://127.0.0.1:{DEVTOOLS_PORT}/json/version", timeout=2) as r:
                    ws_url = json.loads(r.read())["webSocketDebuggerUrl"]
                break
            except Exception:
                time.sleep(0.4)
        if not ws_url:
            print("SKIP contrast_v6: browser devtools unavailable")
            return 0

        browser = CDP(ws_url, websocket)
        for dark in (False, True):
            mode = "dark" if dark else "light"
            for page in PAGES:
                target = browser.send("Target.createTarget", url="about:blank")["targetId"]
                with open_local(f"http://127.0.0.1:{DEVTOOLS_PORT}/json/list", timeout=5) as r:
                    pages = json.loads(r.read())
                tab = CDP(next(p["webSocketDebuggerUrl"] for p in pages if p["id"] == target), websocket)
                tab.send("Page.enable")
                tab.send("Runtime.enable")
                tab.send("Emulation.setDeviceMetricsOverride", width=1360, height=900,
                         deviceScaleFactor=1, mobile=False)
                if dark:
                    tab.send("Emulation.setEmulatedMedia",
                             features=[{"name": "prefers-color-scheme", "value": "dark"}])
                tab.send("Page.navigate", url=BASE + page)
                time.sleep(2.5)
                # 查之前先把所有折叠层展开。
                #
                # 收起来的 `<details>` 里，内容对渲染和对读屏都是不存在的，于是标签
                # 探针把里面的控件报成"无标签"——那是在评判用户此刻碰不到的元素。
                # 但**跳过**它们是更糟的答案：那等于"折叠一段内容"就能让它退出无障碍
                # 检查，而给页面减负正是这一轮反复用的手法（老人端的设置、家人端日报
                # 的分项、每个结果卡里的原始响应）。所以是展开，不是跳过。
                tab.send("Runtime.evaluate", expression=(
                    "document.querySelectorAll('details').forEach(d => d.open = true);"
                    # 分区也要展开，理由和 `<details>` 完全一样。
                    #
                    # 上面那段注释说得对，但只做了一半：`[data-panel]` 分区靠 `hidden`
                    # 切换，而探针的第一道过滤是 `!el.offsetParent` —— 于是**六页 261 个
                    # 有文本的元素里有 122 个从来没被量过**（family 51、care 36、
                    # trust 26），90 个交互元素里有 34 个因为 0×0 而豁免了触控下限。
                    # /care 与 /trust 的全部内容都住在非默认分区里，也就是说这两页的
                    # 对比度基本没被审计过。一行 `.page-section[hidden] .section-note
                    # { color: #c9c9c9 }`（白底 1.6:1）可以让 12/12 照样通过。
                    "document.querySelectorAll('[data-panel][hidden]')"
                    "  .forEach(s => s.hidden = false);"
                ))
                time.sleep(0.4)
                result = tab.send("Runtime.evaluate", expression=AUDIT_JS,
                                  awaitPromise=True, returnByValue=True)
                payload = json.loads(result["result"]["value"])
                bad = payload["contrast"]
                icons = payload.get("icons", [])
                targets = payload["targets"]
                label = f"{page} [{mode}]"
                if bad or icons or targets:
                    for item in bad:
                        failures.append(f"{label} 对比度 {item['ratio']}<{item['need']} “{item['text']}” .{item['cls']}")
                    for item in icons:
                        failures.append(
                            f"{label} 图标对比度 {item['ratio']}<3.0 ink={item['ink']} .{item['cls']}"
                        )
                    for item in targets:
                        failures.append(f"{label} 触控/标签 {item}")
                else:
                    print(f"  ok {label}")
                browser.send("Target.closeTarget", targetId=target)
    finally:
        for proc in (browser_proc, server):
            if proc:
                proc.terminate()
                try:
                    proc.wait(timeout=10)
                except Exception:
                    proc.kill()
        #: 进程先停、再删目录：SQLite 的 WAL/SHM 只有在服务器退出后才放开句柄，
        #: 顺序反过来在 Windows 上会留下删不掉的残留文件。
        shutil.rmtree(workdir, ignore_errors=True)

    if failures:
        print(f"\nFAIL contrast_v6: {len(failures)} 项无障碍问题")
        for item in failures[:40]:
            print(f"  {item}")
        return 1
    print(f"PASS contrast_v6: {len(PAGES) * 2} 个页面/模式全部满足 WCAG AA 与触控尺寸")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
