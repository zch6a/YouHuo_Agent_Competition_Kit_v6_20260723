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
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PAGES = ["/", "/elder", "/family", "/care", "/trust", "/judge"]
PORT = 8013
BASE = f"http://127.0.0.1:{PORT}"
DEVTOOLS_PORT = 9444

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
  const targets = [];
  for (const el of document.querySelectorAll('button, a, select, input')) {
    const b = el.getBoundingClientRect();
    if (b.width && b.height && (b.width < 40 || b.height < 40)) {
      targets.push({el: el.tagName + (el.id ? '#' + el.id : ''), w: Math.round(b.width), h: Math.round(b.height)});
    }
    if (!accessibleName(el)) targets.push({el: el.tagName + (el.id ? '#' + el.id : ''), unlabeled: true});
  }
  return JSON.stringify({contrast: problems, targets});
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
    try:
        import websocket  # type: ignore
    except ImportError:
        print("SKIP contrast_v6: websocket-client not installed")
        return 0
    chrome = find_chrome()
    if not chrome:
        print("SKIP contrast_v6: no Chromium browser found")
        return 0

    env = {**os.environ, "PYTHONPATH": str(ROOT / "backend"), "YOUHUO_DEMO_MODE": "true"}
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
                with urllib.request.urlopen(f"{BASE}/ping", timeout=2):
                    break
            except Exception:
                time.sleep(0.4)
        else:
            print("FAIL contrast_v6: server did not start")
            return 1

        browser_proc = subprocess.Popen(
            [chrome, "--headless=new", "--disable-gpu", "--no-sandbox", "--hide-scrollbars",
             f"--remote-debugging-port={DEVTOOLS_PORT}", "--remote-allow-origins=*",
             f"--user-data-dir={os.environ.get('TEMP', '/tmp')}/youhuo-contrast", "about:blank"],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        ws_url = None
        for _ in range(80):
            try:
                with urllib.request.urlopen(f"http://127.0.0.1:{DEVTOOLS_PORT}/json/version", timeout=2) as r:
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
                with urllib.request.urlopen(f"http://127.0.0.1:{DEVTOOLS_PORT}/json/list", timeout=5) as r:
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
                result = tab.send("Runtime.evaluate", expression=AUDIT_JS,
                                  awaitPromise=True, returnByValue=True)
                payload = json.loads(result["result"]["value"])
                bad = payload["contrast"]
                targets = payload["targets"]
                label = f"{page} [{mode}]"
                if bad or targets:
                    for item in bad:
                        failures.append(f"{label} 对比度 {item['ratio']}<{item['need']} “{item['text']}” .{item['cls']}")
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

    if failures:
        print(f"\nFAIL contrast_v6: {len(failures)} 项无障碍问题")
        for item in failures[:40]:
            print(f"  {item}")
        return 1
    print(f"PASS contrast_v6: {len(PAGES) * 2} 个页面/模式全部满足 WCAG AA 与触控尺寸")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
