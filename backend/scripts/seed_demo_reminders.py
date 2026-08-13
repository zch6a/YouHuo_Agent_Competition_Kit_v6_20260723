"""给演示家庭建几条真提醒——**走真实接口**，不往表里塞行。

为什么需要：`Database.seed_demo()` 只种家庭、成员和三张账单，**一条提醒都没有**。
于是老人端首页第一屏写的是「今天没有要办的事。」——这个产品最重要的一屏，
在评委面前是空的。而它不是缺陷，是演示数据的缺口。

为什么不直接 INSERT：`KNOWN_ISSUES.md` 记着上一次的教训——合成回填写进
`activity_events_v4`（一张运营表，无交互预警取它的 `MAX(occurred_at)`），
让演示数据悄悄改掉了真实功能的输入。这里改走女儿在家属端真会走的那条路
（`POST /v2/family/reminders`），所以产生的审计链、通知、升级计时全都是真的，
和演示当天现场加一条提醒没有区别。

用法：
    python backend/scripts/seed_demo_reminders.py [基址]
"""
from __future__ import annotations

import json
import sys
import urllib.error
import urllib.request
import uuid
from datetime import datetime, timedelta, timezone
# 本机请求一律绕开系统代理，理由见 localhttp.py（一次真实的
# 「服务未能启动」其实是代理把请求挂死了）。
from localhttp import open_local

BASE = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8041"

#: 三条，覆盖三种状态读起来的样子：今天稍后、今天更晚、明天。
#: 内容照着一位真实老人的一天写，不写「测试提醒 1」。
PLAN = [
    ("复诊前准备病历", 3),
    ("下午四点吃降压药", 6),
    ("明天上午去社区量血压", 27),
]


def post(path: str, payload: dict, token: str | None = None) -> dict:
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    request = urllib.request.Request(
        f"{BASE}{path}", data=json.dumps(payload).encode("utf-8"),
        headers=headers, method="POST")
    with open_local(request, timeout=10) as response:
        return json.loads(response.read() or b"{}")


def main() -> int:
    try:
        with open_local(f"{BASE}/v2/identity/visitor", timeout=10) as response:
            ids = json.loads(response.read())
    except Exception as exc:                                     # noqa: BLE001
        print(f"FAIL seed_reminders: 取不到演示身份（{exc}）——服务器起了吗？")
        return 1

    elder_id = ids.get("elderId") or ids.get("elder_id")
    daughter_id = ids.get("daughterId") or ids.get("daughter_id")
    if not (elder_id and daughter_id):
        print(f"FAIL seed_reminders: 身份端点没给出 elder/daughter：{sorted(ids)}")
        return 1

    token = post("/v2/auth/demo", {"actor_id": daughter_id}).get("access_token")
    if not token:
        print("FAIL seed_reminders: 女儿这一侧没拿到令牌")
        return 1

    now = datetime.now(timezone.utc)
    made = 0
    for title, hours in PLAN:
        try:
            post("/v2/family/reminders", {
                "elder_id": elder_id,
                "title": title,
                "due_at": (now + timedelta(hours=hours)).isoformat(),
                "escalation_after_minutes": 60,
                "request_id": str(uuid.uuid4()),
            }, token)
            made += 1
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", "replace")[:160]
            print(f"  「{title}」失败 HTTP {exc.code}：{body}")

    if made != len(PLAN):
        print(f"FAIL seed_reminders: 只建成 {made}/{len(PLAN)} 条")
        return 1
    print(f"PASS seed_reminders: 建了 {made} 条真提醒（走 /v2/family/reminders，"
          "审计链与升级计时都是真的）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
