"""Focus Mode 那一屏的几何约束，用**确定性** fixture 验。

    python backend/scripts/check_focus_geometry.py

## 为什么需要一个新的闸门

`check_page_runtime.py` 里已经有一道 `check_focus_mode_after_speaking`：它在老人端真的
说一句话，然后量对话区高度和输入行位置。那道检查抓到过一个真实 P0（对话区被挤到 0、
输入行被顶到视口外 300 多像素），但它**不确定**：

它依赖玻璃盒卡出现，而卡是否出现取决于后端对这张账单的幂等判断。同一张账单第二次提交
会得到 `duplicate_blocked`，于是没有 `task_id`、`showGlassBox` 直接清空、卡高度为 0
——一列东西装得下，闸门绿。CDP 实测两种结果：

    卡不在  relianceHost 高   0   → 整列 388px，装得下，绿
    卡在    relianceHost 高 222   → 才是被测状态

所以那道闸门**是否测到东西，取决于数据库当前历史和测试执行顺序**。我为它写的两次变异
都没红，就是因为两次都恰好落在"卡不在"那一边。一个只在某些运行里测到被测状态的闸门，
它的绿说明不了任何事。

## 这道闸门怎么做到确定

`glassbox.js` 的 `renderGlassBox(host, card, preview)` 是 **export 的纯函数**——它只吃
数据，不发请求、不看数据库。所以被测状态可以**构造**出来：往那个函数里塞三组尺寸已知
的 card，就得到三个确定的布局，完全不碰缴费。

三个 Case：

    A  Focus Mode + 没有卡          （最松，也是刷新之后最常见的一屏）
    B  Focus Mode + 正常一张卡
    C  Focus Mode + 合理最大内容     长医院名、长任务标题、warning 全在

C 不是"极端到不可能"，它是这个产品真实会出现的一屏：三甲医院的全名 + 一条完整的高风险
提示。合理最大装得下，中间那些自然也装得下。

## 判据（每个 Case 逐条）

    1. 对话区高度 ≥ 80px               她必须看得见自己刚说的话（约两行 17px 正文）
    2. 输入行上下边都在容器内           她必须够得到输入框和发送键
    3. 输入框、发送键、返回键三个都可命中
    4. 各块高度之和 ≤ 容器高度          通式：没有任何一块被 overflow: hidden 吃掉
    5. 无横向溢出
    6. 用户那条消息可见                 不只是"在 DOM 里"
    7. 助手那条回复可见

第 4 条是前三条的通式。只有前三条的话，下一个被挤出去的块（比如状态行）会安静消失。

**不许用 `scrollIntoView` 之后的命中测试当判据。** 脚本能滚 `overflow: hidden` 的容器，
手指不能——那正是点击遍历在这个 P0 上全绿的原因：它对 `#send` 滚一下再命中测试，通过了，
而真实用户的拇指永远到不了 y=1159。所以这里量的是**元素此刻在不在容器的可视矩形内**。
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

ROOT = Path(__file__).resolve().parents[2]

#: 手机矩阵。Focus Mode 的亏空是**竖向**的，所以矩阵按高度铺开，最矮的排第一。
#: 320×568 是这个项目声明支持的最小视口，而它此前量到 `#chat` 已经是 0px——
#: 也就是说最紧的那一档历史上真的坏过。
VIEWPORTS = [
    ("iPhone SE 竖", 320, 568),
    ("Android 小屏", 360, 800),
    ("iPhone 13 mini", 375, 812),
    ("iPhone 14 竖", 390, 844),
    ("Pixel 7", 412, 915),
]

#: 对话区的下限。约两行 17px 正文加行距——比这更少，屏幕上只剩半句话。
MIN_CHAT_HEIGHT = 80


def _free_port() -> int:
    """向系统要一个空闲端口。写死端口会让并发跑的两份检查互相打断，而更坏的失败
    模式是它不报错——一个实例的命令落进另一个实例的标签页。"""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


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


#: 三组构造出来的玻璃盒数据。
#:
#: 字段名照 `glassbox.js` 的 `renderGlassBox` 逐个对——它读 `card.title` / `heard` /
#: `goal` / `current_step` / `action_summary` / `who_decides` / `reversible` /
#: `next_step` / `confidence_message` / `warning`。写错一个字段名，那一行就是空的，
#: 于是 Case C 会比真实情况矮——一个**偏松**的 fixture 比没有 fixture 更糟，
#: 因为它会让人以为量过了。
FIXTURES = r"""
const CARDS = {
  A: null,
  B: {
    title: '这件事我准备这样办',
    heard: '帮我交这个月的水费',
    goal: '2026-07 水费缴费',
    current_step: '等待您复述确认',
    action_summary: '向水务公司提交一笔 68.40 元的缴费',
    who_decides: '您确认后，由绑定家属完成最终接力',
    reversible: false,
    next_step: '请把金额念一遍',
    confidence_message: '金额来自账单接口，不是我听来的',
    warning: null,
  },
  C: {
    title: '这件事我准备这样办',
    heard: '帮我把下个月心内科的复诊挂到市第一人民医院去，上次那个大夫',
    goal: '北京市第一人民医院心血管内科门诊复诊预约（2026-09）',
    current_step: '等待您复述确认',
    action_summary: '向北京市第一人民医院心血管内科提交一次门诊复诊预约，'
      + '并把上次的接诊医师作为首选',
    who_decides: '您确认后，由绑定家属完成最终接力；家属拒绝则不会提交',
    reversible: false,
    next_step: '请把医院名字和科室念一遍',
    confidence_message: '医院与科室来自您上次的就诊记录，不是我猜的',
    warning: '这一次不能自动撤销：预约提交之后要打电话取消，所以要多确认一次。',
  },
};

/** 把 Focus Mode 摆到指定的被测状态，然后量它。
 *
 * 走应用**自己的**路径进 Focus Mode（按 `#typeInstead`），不直接写
 * `body.dataset.focus`——那样量到的是一个用户到不了的状态。
 */
window.__focusProbe = async (caseName) => {
  const app = document.body;
  const enter = document.getElementById('typeInstead');
  if (!enter) return {fail: '首页上没有打字入口，进不了 Focus Mode'};
  if (app.dataset.focus !== 'on') {
    enter.click();
    await new Promise(r => setTimeout(r, 300));
  }
  if (app.dataset.focus !== 'on') return {fail: '按了打字入口也没进 Focus Mode'};

  const chat = document.getElementById('chat');
  const host = document.getElementById('relianceHost');
  const composer = document.querySelector('.composer');
  const stage = document.querySelector('.elder-layout .stage');
  const focus = document.querySelector('.elder-focus');
  if (!chat || !host || !composer || !stage || !focus) {
    return {fail: 'Focus Mode 的结构变了：chat/relianceHost/composer/stage/focus 缺一个'};
  }

  // 两条气泡，构造的，不发请求。它们是判据 6 和 7 的对象。
  chat.replaceChildren();
  for (const [text, who] of [['帮我交这个月的水费', 'user'], ['查到 2026-07 的水费是 68.40 元。', 'agent']]) {
    const b = document.createElement('div');
    b.className = 'bubble ' + who;
    b.textContent = text;
    b.dataset.probe = who;
    chat.appendChild(b);
  }

  const card = CARDS[caseName];
  if (card === null) {
    host.replaceChildren();
  } else {
    const mod = await import('/static/glassbox.js');
    // preview 传 null：`renderGlassBox` 对它做真值判断，null 就是"没有预览"。
    // 这一支本身也是真实状态（不是每件事都有可预览的请求体）。
    mod.renderGlassBox(host, card, null);
  }
  // 布局落定。两帧足够——这一屏没有过渡动画参与高度。
  await new Promise(r => requestAnimationFrame(() => requestAnimationFrame(r)));

  // 滚到底，因为**应用就是这么做的**：`elder.js` 的 `addBubble` 最后一行是
  // `chat.scrollTop = chat.scrollHeight`。
  //
  // 这一句我写错了三遍，三次错法不同，而三次都是**探针**的错、不是产品的错：
  //
  //   一版：根本没滚 → 报「最新那条在 DOM 里但看不见」，五个视口全中。
  //   二版：滚在 `renderGlassBox` 之前 → 卡渲染出来之后 `#chat` 变矮、滚动位置被
  //         重新钳过，又退回顶部附近，报「只露出 3px」。
  //   三版：位置对了但只等一帧 → `#chat` 在 components.css:573 带
  //         `scroll-behavior: smooth`，赋值是一次**动画**；一帧之后 scrollTop 还是
  //         0（实测 0 或 3），而该到的位置是 scrollHeight − clientHeight = 103。
  //
  // 所以滚完要等动画走完再量。用户经历的正是这个：他等一下，就看到最新那条。
  chat.scrollTop = chat.scrollHeight;
  await new Promise(r => setTimeout(r, 450));

  const box = (el) => {
    const r = el.getBoundingClientRect();
    return {top: Math.round(r.top), bottom: Math.round(r.bottom),
            left: Math.round(r.left), right: Math.round(r.right),
            h: Math.round(r.height), w: Math.round(r.width)};
  };

  // 「够得到」= 此刻就在容器的可视矩形里，而且那个点上命中测试落在它自己身上。
  // **不滚动**：脚本能滚 overflow:hidden 的容器，手指不能。
  const sr = stage.getBoundingClientRect();
  const reachable = (el) => {
    if (!el) return {missing: true};
    const r = el.getBoundingClientRect();
    const cx = r.left + r.width / 2, cy = r.top + r.height / 2;
    const inside = r.top >= sr.top - 1 && r.bottom <= sr.bottom + 1;
    const hit = document.elementFromPoint(cx, cy);
    return {
      inside,
      hit: !!hit && (hit === el || el.contains(hit) || hit.contains(el)),
      box: box(el),
    };
  };

  const kids = [...focus.children]
    .filter(el => getComputedStyle(el).display !== 'none')
    .map(el => ({
      what: el.tagName + (el.id ? '#' + el.id : '.' + String(el.className).split(' ')[0]),
      h: Math.round(el.getBoundingClientRect().height),
    }));

  const visible = (sel) => {
    const el = chat.querySelector(sel);
    if (!el) return {missing: true};
    const r = el.getBoundingClientRect();
    const cr = chat.getBoundingClientRect();
    // 在滚动区里可见 = 和滚动区的可视矩形有真实交集（不是只差一两像素的边缘）。
    const overlap = Math.min(r.bottom, cr.bottom) - Math.max(r.top, cr.top);
    return {overlap: Math.round(overlap), h: Math.round(r.height)};
  };

  return {
    case: caseName,
    stage: box(stage),
    focus: box(focus),
    chat: box(chat),
    chatScrollH: chat.scrollHeight,
    chatScrollTop: Math.round(chat.scrollTop),
    chatClientH: chat.clientHeight,
    chatOverflowY: getComputedStyle(chat).overflowY,
    reliance: box(host),
    relianceKids: host.children.length,
    composer: box(composer),
    kids,
    kidsSum: kids.reduce((a, k) => a + k.h, 0),
    input: reachable(document.getElementById('text')),
    send: reachable(document.getElementById('send')),
    back: reachable(document.getElementById('focusBack')),
    userBubble: visible('[data-probe="user"]'),
    agentBubble: visible('[data-probe="agent"]'),
    docScrollW: document.documentElement.scrollWidth,
    innerW: window.innerWidth,
  };
};
"""


class CDP:
    def __init__(self, url: str, websocket_mod) -> None:
        self.ws = websocket_mod.create_connection(url, timeout=60)
        self.n = 0

    def send(self, method: str, **params) -> dict:
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


def judge(label: str, result: dict, failures: list[str]) -> None:
    """一个 Case 的七条判据。"""
    if result.get("fail"):
        failures.append(f"{label}：{result['fail']}")
        return

    where = f"{label} Case {result['case']}"
    kids = result["kids"]

    # 1 · 她看得见自己刚说的话
    if result["chat"]["h"] < MIN_CHAT_HEIGHT:
        failures.append(
            f"{where}：对话区只有 {result['chat']['h']}px（内容 {result['chatScrollH']}px），"
            f"低于 {MIN_CHAT_HEIGHT}px——她看不见自己刚说的话。各块 {kids}"
        )

    # 2 · 输入行整块在容器内
    st, sb = result["stage"]["top"], result["stage"]["bottom"]
    ct, cb = result["composer"]["top"], result["composer"]["bottom"]
    if cb > sb + 1 or ct < st - 1:
        failures.append(
            f"{where}：输入行在 {ct}–{cb}，而容器是 {st}–{sb}"
            f"（超出 {max(cb - sb, st - ct)}px）——她够不到输入框和发送键。各块 {kids}"
        )

    # 3 · 三个关键控件此刻就够得到（不滚动）
    for name, key in (("输入框", "input"), ("发送键", "send"), ("返回键", "back")):
        probe = result[key]
        if probe.get("missing"):
            failures.append(f"{where}：{name}不在这一屏上")
        elif not probe["inside"]:
            failures.append(f"{where}：{name}在容器外（{probe['box']['top']}–"
                            f"{probe['box']['bottom']}，容器 {st}–{sb}）")
        elif not probe["hit"]:
            failures.append(f"{where}：{name}被别的东西盖住了（{probe['box']}）")

    # 4 · 通式：没有任何一块被裁掉
    if result["kidsSum"] > result["focus"]["h"] + 2:
        failures.append(
            f"{where}：各块高度之和 {result['kidsSum']} > 容器 {result['focus']['h']}"
            f"——有东西被 overflow: hidden 吃掉了：{kids}"
        )

    # 5 · 无横向溢出
    if result["docScrollW"] > result["innerW"] + 1:
        failures.append(f"{where}：横向溢出 {result['docScrollW'] - result['innerW']}px")

    # 6 / 7 · 两条消息都真的看得见
    # 判的是「她正在读的那条」真的看得见，而不是"两条同时可见"。
    #
    # 聊天界面滚到底之后，最新那条在视野里、更早的靠上滚——这是每一个聊天产品的
    # 真实状态。而"两条同时可见"在 96px 的对话区里根本不可能（单条气泡就 108px），
    # 拿它当判据会逼出一个错误的设计。
    #
    # 她自己那条仍然要在：它必须在滚动区里够得着（`scrollHeight` 装得下它），
    # 而不是被 `replaceChildren` 之类的东西弄丢了。
    latest = result["agentBubble"]
    if latest.get("missing"):
        failures.append(f"{where}：优活回的那条消息不在对话区里")
    elif latest["overlap"] < 24:
        failures.append(
            f"{where}：滚到底之后，优活回的那条只露出 {latest['overlap']}px"
            f"（自身高 {latest['h']}px，对话区 {result['chat']['h']}px，"
            f"scrollTop={result['chatScrollTop']} scrollH={result['chatScrollH']} "
            f"clientH={result['chatClientH']} overflowY={result['chatOverflowY']}）"
            "——她读不到刚问出来的那个答案"
        )
    if result["userBubble"].get("missing"):
        failures.append(f"{where}：她自己说的那条消息从对话区里消失了")

    # Case B/C 必须真的造出了卡——否则这一轮什么都没测到。
    if result["case"] in ("B", "C") and result["relianceKids"] == 0:
        failures.append(
            f"{where}：玻璃盒卡没渲染出来（relianceHost 是空的）。"
            "这一轮没有造出被测状态，不能算通过。"
        )


def main() -> int:
    chrome = find_chrome()
    if not chrome:
        print("SKIP focus_geometry: 这台机器上没有 Chrome")
        return 0
    try:
        import websocket  # noqa: PLC0415
    except ImportError:
        print("SKIP focus_geometry: 缺 websocket-client")
        return 0

    port, devtools = _free_port(), _free_port()
    base = f"http://127.0.0.1:{port}"
    profile = Path(tempfile.gettempdir()) / "youhuo-focus-geometry"
    shutil.rmtree(profile, ignore_errors=True)

    env = {**os.environ, "PYTHONPATH": str(ROOT / "backend"),
           "YOUHUO_DB_PATH": str(Path(tempfile.mkdtemp()) / "focus.db"),
           "YOUHUO_SEED_BASELINE": "true"}
    server = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "youhuo.api:app", "--host", "127.0.0.1",
         "--port", str(port), "--app-dir", "backend", "--log-level", "warning"],
        cwd=ROOT, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    browser = None
    failures: list[str] = []
    measured = 0
    try:
        for _ in range(80):
            try:
                with urllib.request.urlopen(f"{base}/ping", timeout=2):
                    break
            except Exception:
                time.sleep(0.4)
        else:
            print("FAIL focus_geometry: 服务器没起来")
            return 1

        browser = subprocess.Popen(
            [chrome, "--headless=new", "--disable-gpu", "--no-sandbox", "--hide-scrollbars",
             f"--remote-debugging-port={devtools}", "--remote-allow-origins=*",
             f"--user-data-dir={profile}", "about:blank"],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        ws_url = None
        for _ in range(80):
            try:
                with urllib.request.urlopen(
                    f"http://127.0.0.1:{devtools}/json/version", timeout=2
                ) as r:
                    ws_url = json.loads(r.read())["webSocketDebuggerUrl"]
                break
            except Exception:
                time.sleep(0.4)
        if not ws_url:
            # 失败，不是跳过：Chrome 在，只是 DevTools 没起来——那是故障。
            print(f"FAIL focus_geometry: Chrome 在但 DevTools 没起来（端口 {devtools}）")
            return 1

        root = CDP(ws_url, websocket)
        for label, width, height in VIEWPORTS:
            target = root.send("Target.createTarget", url="about:blank")["targetId"]
            session = root.send(
                "Target.attachToTarget", targetId=target, flatten=True
            )["sessionId"]

            def tab(method: str, **params) -> dict:
                root.n += 1
                root.ws.send(json.dumps({
                    "id": root.n, "method": method, "params": params, "sessionId": session,
                }))
                while True:
                    message = json.loads(root.ws.recv())
                    if message.get("id") == root.n:
                        if "error" in message:
                            raise RuntimeError(f"{method}: {message['error']}")
                        return message.get("result", {})

            tab("Runtime.enable")
            tab("Page.enable")
            tab("Emulation.setDeviceMetricsOverride",
                width=width, height=height, deviceScaleFactor=1, mobile=True)
            tab("Page.navigate", url=f"{base}/elder")
            time.sleep(4.5)
            tab("Runtime.evaluate", expression=FIXTURES)

            for case in ("A", "B", "C"):
                out = tab("Runtime.evaluate",
                          expression=f"window.__focusProbe({case!r})",
                          awaitPromise=True, returnByValue=True)["result"].get("value")
                if not isinstance(out, dict):
                    failures.append(f"{label} Case {case}：探针没有返回结果（{out!r}）")
                    continue
                judge(f"{label} {width}×{height}", out, failures)
                measured += 1
                # 下一个 Case 从干净的一屏开始。
                tab("Page.navigate", url=f"{base}/elder")
                time.sleep(3.0)
                tab("Runtime.evaluate", expression=FIXTURES)

            root.send("Target.closeTarget", targetId=target)
        root.close()
    finally:
        if browser:
            browser.terminate()
        server.terminate()
        shutil.rmtree(profile, ignore_errors=True)

    # 量到的组数必须印出来。一个"跑了但一组都没量到"的检查，和没有这个检查是一回事，
    # 而它在结果里看起来一模一样地绿。
    expected = len(VIEWPORTS) * 3
    if measured < expected:
        print(f"FAIL focus_geometry: 只量到 {measured} 组，应该是 {expected} 组")
        for item in failures:
            print(f"  {item}")
        return 1
    if failures:
        print(f"FAIL focus_geometry: {len(failures)} 项")
        for item in failures:
            print(f"  {item}")
        return 1
    print(f"OK focus_geometry: {len(VIEWPORTS)} 个视口 × 3 个 Case（无卡/正常卡/最大卡）"
          f"= {measured} 组，七条几何约束全过；"
          "对话区可见、输入行与发送键够得到、没有块被裁掉")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
