"""按一遍每个控件，报出「点下去什么都不发生」的那些。

## 为什么静态清单不够

`build_control_inventory.py` 已经能回答「这个控件有没有脚本引用它」，
`test_control_inventory_is_the_fact_source` 还要求每个没人引用的都写清理由。
那是静态的一半，它抓不到下面这几种——每一种都真的发生过：

  · 绑上了，但调的接口不存在（`/v2/reminders/{id}/done` 是 404，真名叫 complete）
  · 绑上了，但回执写进了一个默认隐藏的容器（`#chat` 在 `.elder-focus` 里）
  · 绑上了，但只走语音（没有合成时屏幕上一个字都不变）
  · 绑上了，但绑的是**假的**（交付包里「✓ 已保存」显示 1.5 秒，一个字节都不存）

四种在静态扫描里都长得像「已绑定」。所以要真的按下去看。

## 判据

对每个可见控件派发 pointerdown / pointerup / click（这个仓库两种绑法都有，
分区切换绑的是 `pointerup`，只 `.click()` 根本切不动页），然后看两样：

    发出了同源请求？        任一为真 = 它做了事
    页面指纹变了？          指纹 = innerText + 每个元素的 class/hidden

两样都没变，才算「没反应」。

## 三条来之不易的规矩

  1. **每次点击之前恢复现场。** 不恢复的话，一次点击会污染它后面所有读数：
     照护那一屏点到「返回今天」就整个隐藏了，后面 14 个控件全被计成死的。
  2. **列举和恢复等一样长。** 一次实测里列举等 3 秒看到 20 个、恢复等 1.2 秒
     看到 15 个，序号对不上，10 个被整批跳过——而汇总显示「死控件 0」。
  3. **按身份+文字配对，不按序号。** 异步内容条数每次不同，序号会整体错位。

`跳过` 和 `没测到` 都**不是**通过。它们分开计数并单独列出，因为
「少测了」和「通过了」在结果里长得一模一样，而那正是这份脚本要防的事。
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
PORT = int(os.getenv("YOUHUO_SWEEP_PORT", "9041"))
CDP = PORT + 500
BASE = f"http://127.0.0.1:{PORT}"
#: 本机代理会把 127.0.0.1 也劫走，而 urllib 不理 NO_PROXY。
OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))

#: 会真动业务或整页跳走的控件：只看在不在，不点。
#: 它们各自另有专门的判据（P0 那一批、SOS 那一批），而在这里点下去
#: 会改数据或让后面的读数失去意义。
SKIP_WORDS = (
    "紧急", "呼叫", "求助", "帮忙", "SOS", "删除", "清除", "忘掉",
    "确认支付", "立即支付", "执行", "接力", "退出", "换一个人",
    "返回首页", "全屏", "重新开始", "只留手机", "重播", "从头演一遍",
)

#: 每一页的分区机制。`segs` 是切分区的按钮，`scope` 是那一分区里的控件。
#: `None` = 整页一个分区。
SURFACES: list[tuple[str, str | None]] = [
    ("/elder", '.seg[data-section]'),
    ("/elder2", '.seg[data-section]'),
    ("/elder3", '.dock [data-page]'),
    ("/family", '.seg[data-section]'),
    ("/family2", '.seg[data-section]'),
    ("/family3", '[data-app]'),
    ("/care", '.seg[data-section]'),
    ("/trust", None),
    ("/stage", None),
    ("/judge", None),
]

FINGER = r"""
(() => {
  let h = 0;
  const add = (s) => { for (let i = 0; i < s.length; i++)
    { h = ((h << 5) - h + s.charCodeAt(i)) | 0; } };
  add(document.body.innerText || '');
  add(location.pathname + location.search + location.hash);
  document.querySelectorAll('body *').forEach(el => {
    add(el.tagName + '|' + (el.className || '') + '|' + (el.hidden ? '1' : '0'));
  });
  return String(h);
})()
"""

#: 「看得见」= 有盒子 + 没被 CSS 藏 + **在视口里** + 不在 inert 容器里。
#:
#: 后两条是补上去的，各去掉一批假阳性：
#:   在视口里   `#taskDetailClose` 住在一个 `transform: translateY(154px)` 的
#:              对话框里，在 932 高的视口里落在 top=1018——`opacity:1
#:              visibility:visible`，前三条全过，而它根本不在屏幕上。
#:              实测中心点打到的是 `NAV`。
#:   不 inert   `inert` 不影响布局也不影响 opacity，但元素确实点不动。
#:              一个 inert 的按钮「点下去没反应」是**规范规定的**，不是缺陷。
VISIBLE = """
[...document.querySelectorAll('button, summary, [role=button]')].filter(e => {
  const r = e.getBoundingClientRect();
  const s = getComputedStyle(e);
  if (r.width < 2 || r.height < 2) return false;
  if (s.visibility === 'hidden' || s.display === 'none') return false;
  if (parseFloat(s.opacity) < 0.05) return false;
  if (r.bottom <= 0 || r.top >= innerHeight) return false;
  if (r.right <= 0 || r.left >= innerWidth) return false;
  if (e.closest('[inert]')) return false;
  return true;
})
"""


def kill_port(port: int) -> None:
    """把还占着这个端口的服务收干净。

    `Popen.terminate()` 只杀父进程，uvicorn 的工作进程会活下来继续监听。
    实测后果：下一轮连上的是**上一轮的服务和上一轮的数据库**，
    量错了对象和量出坏结果在输出里长得一模一样。
    """
    out = subprocess.run(["netstat", "-ano"], capture_output=True, text=True,
                         encoding="utf-8", errors="replace").stdout or ""
    for line in out.splitlines():
        if f":{port} " in line and "LISTENING" in line:
            subprocess.run(["taskkill", "/PID", line.split()[-1], "/F", "/T"],
                           capture_output=True)
    time.sleep(1.0)


class Tab:
    """一个 CDP 会话。够用就好，不引第三方浏览器驱动。"""

    def __init__(self, ws) -> None:
        self.ws = ws
        self.n = 0
        self.events: list[dict] = []
        self.session = ""

    def send(self, method: str, **params):
        self.n += 1
        self.ws.send(json.dumps({
            "id": self.n, "method": method, "params": params,
            **({"sessionId": self.session} if self.session else {})}))
        while True:
            msg = json.loads(self.ws.recv())
            if msg.get("id") == self.n:
                return msg.get("result", {})
            if "method" in msg:
                self.events.append(msg)

    def drain(self, secs: float) -> None:
        self.ws.settimeout(secs)
        try:
            while True:
                self.events.append(json.loads(self.ws.recv()))
        except Exception:
            pass
        self.ws.settimeout(60)

    def eval(self, expr: str):
        r = self.send("Runtime.evaluate", returnByValue=True, expression=expr)
        if "exceptionDetails" in r:
            return "**JS:" + str(r["exceptionDetails"].get("text"))
        return r.get("result", {}).get("value")

    def controls(self) -> list[list]:
        """回 [身份, 文字, 是不是已经选中]。

        第三项要紧：**点一个已经选中的页签，屏幕不变是对的。**
        不认它的话，每一个分区的自身页签都会被报成死控件——而恢复现场时
        我正是先点了那个页签，所以它必然是选中态。实测这一条造成了 9 个假阳性
        （`.seg 首页`、`.tab 我的`、`.seg 照护`……），把真信号淹在里面。
        """
        raw = self.eval("(() => { const els = " + VISIBLE + r"""
          ; const on = (el) => el.classList.contains('is-current')
              || el.classList.contains('active')
              || el.getAttribute('aria-current') === 'true'
              || el.getAttribute('aria-selected') === 'true'
              || el.getAttribute('aria-pressed') === 'true';
          return JSON.stringify(els.map(el => {
            const label = (el.textContent || el.getAttribute('aria-label') || '')
              .replace(/\s+/g, ' ').trim().slice(0, 26);
            const id = el.id ? '#' + el.id
              : (typeof el.className === 'string' && el.className.trim()
                 ? '.' + el.className.trim().split(/\s+/)[0]
                 : el.tagName.toLowerCase());
            return [id, label, on(el)];
          })); })()""")
        return json.loads(raw) if isinstance(raw, str) and raw.startswith("[") else []

    def poke(self, index: int) -> None:
        self.eval("(() => { const els = " + VISIBLE + f"""
          ; const el = els[{index}];
          if (!el) return;
          const r = el.getBoundingClientRect();
          const o = {{bubbles: true, cancelable: true, composed: true,
                     clientX: r.left + r.width / 2, clientY: r.top + r.height / 2,
                     pointerId: 1, isPrimary: true, pointerType: 'mouse'}};
          el.dispatchEvent(new PointerEvent('pointerdown', o));
          el.dispatchEvent(new PointerEvent('pointerup', o));
          el.click();
        }})()""")

    def requests(self) -> list[str]:
        out = [e["params"]["request"]["url"].replace(BASE, "")
               for e in self.events
               if e.get("method") == "Network.requestWillBeSent"
               and e["params"]["request"]["url"].startswith(BASE)
               and "/static/" not in e["params"]["request"]["url"]]
        self.events.clear()
        return out


def sweep_panel(tab: Tab, restore, settle: float) -> tuple[list[str], list[str], int, int]:
    """回 (没反应, 没测到, 跳过数, 已选中数)。四者分开。

    「没测到」和「已选中」都**不是**「通过」，但也都不是缺陷——分开计数是因为
    把它们混进任何一栏都会说谎：混进「没反应」是诬告，混进「通过」是漏测。

    只在**页面确实偏离基线时**才恢复。无条件恢复的版本每个控件多等 3 秒，
    一整轮要一个多小时——而绝大多数控件点完页面并没有换分区。
    """
    restore()
    time.sleep(settle)
    items = tab.controls()
    baseline = tab.eval(FINGER)
    dead: list[str] = []
    unmeasured: list[str] = []
    skipped = 0
    already_on = 0
    for ident, label, was_on in items:
        if any(w in label for w in SKIP_WORDS):
            skipped += 1
            continue
        if was_on:
            # 已经选中的页签，点它不变是**对的**。
            already_on += 1
            continue
        if tab.eval(FINGER) != baseline:
            restore()
            time.sleep(settle)
        now = tab.controls()
        try:
            i = next(k for k, (a, b, _) in enumerate(now) if a == ident and b == label)
        except StopIteration:
            unmeasured.append(f"{ident} {label}")
            continue
        tab.events.clear()
        before = tab.eval(FINGER)
        tab.poke(i)
        time.sleep(1.4)
        tab.drain(0.3)
        after = tab.eval(FINGER)
        if not tab.requests() and before == after:
            dead.append(f"{ident} {label}")
    return dead, unmeasured, skipped, already_on


def main() -> int:
    import websocket   # 只有跑这支脚本才需要，不进运行时依赖

    tmp = Path(tempfile.mkdtemp(prefix="yh-sweep-"))
    profile = tempfile.mkdtemp(prefix="yh-sweep-chrome-")
    chrome = os.getenv("CHROME") or r"C:\Program Files\Google\Chrome\Application\chrome.exe"
    if not Path(chrome).is_file():
        print("SKIP dead_controls: 找不到 Chrome")
        return 0

    kill_port(PORT)
    env = {**os.environ, "YOUHUO_DEMO_STATE": "attention",
           "PYTHONIOENCODING": "utf-8", "YOUHUO_DB_PATH": str(tmp / "sweep.db")}
    server = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "youhuo.api:app", "--port", str(PORT),
         "--log-level", "error"], cwd=ROOT / "backend", env=env,
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    browser = subprocess.Popen(
        [chrome, "--headless=new", f"--remote-debugging-port={CDP}",
         "--remote-allow-origins=*", "--hide-scrollbars",
         f"--user-data-dir={profile}", "--no-first-run", "about:blank"],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    problems: dict[str, list[str]] = {}
    unmeasured_all: dict[str, list[str]] = {}
    try:
        for _ in range(90):
            try:
                OPENER.open(BASE + "/health", timeout=1)
                break
            except Exception:
                time.sleep(0.5)
        info = json.loads(OPENER.open(
            f"http://127.0.0.1:{CDP}/json/version", timeout=10).read())
        tab = Tab(websocket.create_connection(info["webSocketDebuggerUrl"], timeout=60))
        target = tab.send("Target.createTarget", url="about:blank")["targetId"]
        tab.session = tab.send("Target.attachToTarget",
                               targetId=target, flatten=True)["sessionId"]
        for m in ("Page.enable", "Runtime.enable", "Network.enable"):
            tab.send(m)
        tab.send("Emulation.setDeviceMetricsOverride", width=1440, height=900,
                 deviceScaleFactor=1, mobile=False)

        total_controls = 0
        for page, seg_sel in SURFACES:
            tab.send("Page.navigate", url=BASE + page)
            time.sleep(8.0)
            tab.eval("document.querySelectorAll('details').forEach(d => d.open = true)")
            time.sleep(1.0)
            tab.drain(0.8)
            tab.events.clear()

            keys: list[str | None] = [None]
            if seg_sel:
                raw = tab.eval(
                    f"JSON.stringify([...document.querySelectorAll({seg_sel!r})]"
                    ".map(e => e.dataset.section || e.dataset.page || e.dataset.app)"
                    ".filter(Boolean))")
                found = json.loads(raw or "[]")
                keys = list(dict.fromkeys(found)) or [None]

            for key in keys:
                if key is None:
                    def restore():
                        tab.eval("document.querySelectorAll('details')"
                                 ".forEach(d => d.open = true)")
                else:
                    def restore(k=key, sel=seg_sel):
                        tab.eval(f"""(() => {{
                          const b = [...document.querySelectorAll({sel!r})].find(
                            e => (e.dataset.section || e.dataset.page
                                  || e.dataset.app) === {k!r});
                          if (!b) return;
                          const r = b.getBoundingClientRect();
                          const o = {{bubbles: true, clientX: r.left + 4,
                                     clientY: r.top + 4}};
                          b.dispatchEvent(new PointerEvent('pointerdown', o));
                          b.dispatchEvent(new PointerEvent('pointerup', o));
                          b.click();
                        }})()""")

                dead, unmeasured, skipped, on_now = sweep_panel(tab, restore, settle=3.0)
                where = f"{page}#{key}" if key else page
                count = len(tab.controls())
                total_controls += count
                mark = "  " if not dead else "**"
                print(f"{mark} {where:<22} 控件 {count:>3} · 跳过 {skipped:>2}"
                      f" · 已选中 {on_now:>2} · 没反应 {len(dead)}"
                      f" · 没测到 {len(unmeasured)}")
                for d in dead:
                    print(f"       没反应 {d}")
                for u in unmeasured:
                    print(f"       没测到 {u}")
                if dead:
                    problems[where] = dead
                if unmeasured:
                    unmeasured_all[where] = unmeasured
        print(f"\n共按过 {total_controls} 个可见控件。")
    finally:
        browser.terminate()
        server.terminate()
        kill_port(PORT)
        shutil.rmtree(tmp, ignore_errors=True)
        shutil.rmtree(profile, ignore_errors=True)

    if unmeasured_all:
        print(f"\n没测到（**不是通过**）：{sum(len(v) for v in unmeasured_all.values())} 个")
    if problems:
        print(f"\nFAIL dead_controls: {sum(len(v) for v in problems.values())} 个控件"
              f"点下去什么都不发生")
        for where, items in problems.items():
            print(f"  {where}")
            for it in items:
                print(f"    {it}")
        print("\n  注意：默认就选中的页签点下去不变是**对的**。"
              "报出来之后先从别的状态切回来点一次再判。")
        return 1
    print("\nPASS dead_controls: 每一个按过的控件都做了事")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
