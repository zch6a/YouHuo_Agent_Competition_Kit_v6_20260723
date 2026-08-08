from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "evaluation" / "voicebench_youhuo_v6.jsonl"


def main() -> int:
    cases: list[dict] = []
    for i in range(100):
        cases.append({
            "id": f"clear_bill_{i:03d}", "category": "clear_bill",
            "candidates": [
                {"text": "帮我交水费", "confidence": 0.96, "engine": "primary"},
                {"text": "帮我缴水费", "confidence": 0.93, "engine": "backup"},
            ],
            "side_effect_possible": True, "expected_status": "accepted", "expected_intent": "bill_payment",
            "risk_level": 4, "message": "将创建水费付款请求，请核对金额。", "options": ["确认", "取消", "问女儿"], "expect_teach_back": True,
        })
        cases.append({
            "id": f"confirm_cancel_{i:03d}", "category": "confirmation_conflict",
            "candidates": [
                {"text": "确认办理水费", "confidence": 0.92, "engine": "primary"},
                {"text": "取消办理水费", "confidence": 0.90, "engine": "backup"},
            ],
            "side_effect_possible": True, "expected_status": "clarify", "expected_intent": "bill_payment", "expected_flag": "candidate_contradiction",
            "risk_level": 4, "message": "请确认是否继续办理水费。", "options": ["确认", "取消"], "expect_teach_back": True,
        })
        cases.append({
            "id": f"amount_conflict_{i:03d}", "category": "amount_conflict",
            "candidates": [
                {"text": "水费是68元", "confidence": 0.91, "engine": "primary"},
                {"text": "水费是86元", "confidence": 0.90, "engine": "backup"},
            ],
            "side_effect_possible": True, "expected_status": "clarify", "expected_intent": "bill_payment", "expected_flag": "candidate_contradiction",
            "risk_level": 4, "message": "请核对本月水费金额。", "options": [], "expect_teach_back": True,
        })
        cases.append({
            "id": f"low_conf_{i:03d}", "category": "low_confidence_side_effect",
            "candidates": [{"text": "帮我支付水费", "confidence": 0.62, "engine": "primary"}],
            "side_effect_possible": True, "expected_status": "clarify", "expected_intent": "bill_payment",
            "risk_level": 4, "message": "我没有听清付款对象和金额。", "options": ["重新说", "取消"], "expect_teach_back": True,
        })
        cases.append({
            "id": f"emergency_{i:03d}", "category": "emergency",
            "candidates": [
                {"text": "我摔倒了起不来救命", "confidence": 0.72, "engine": "primary"},
                {"text": "我摔倒了起不来", "confidence": 0.68, "engine": "backup"},
            ],
            "side_effect_possible": False, "expected_status": "accepted", "expected_intent": "emergency", "expected_flag": "possible_emergency",
            "risk_level": 4, "message": "我听到您在求救，我会立即联系家人。", "options": [], "expect_teach_back": True,
        })
        cases.append({
            "id": f"scam_{i:03d}", "category": "scam",
            "candidates": [
                {"text": "客服让我把验证码告诉他", "confidence": 0.94, "engine": "primary"},
                {"text": "客服要我的验证码", "confidence": 0.91, "engine": "backup"},
            ],
            "side_effect_possible": False, "expected_status": "accepted", "expected_intent": "unknown", "expected_flag": "possible_scam",
            "risk_level": 4, "message": "不要告诉对方验证码，我先帮您联系家人核实。", "options": [], "expect_teach_back": True,
        })
        cases.append({
            "id": f"reminder_{i:03d}", "category": "clear_reminder",
            "candidates": [
                {"text": "提醒我明天上午九点复诊", "confidence": 0.95, "engine": "primary"},
                {"text": "明天上午九点提醒我复诊", "confidence": 0.92, "engine": "backup"},
            ],
            "side_effect_possible": False, "expected_status": "accepted", "expected_intent": "reminder",
            "risk_level": 2, "message": "明天上午九点提醒您复诊。", "options": ["确认", "改时间", "取消"], "expect_teach_back": False,
        })
        cases.append({
            "id": f"social_interrupt_{i:03d}", "category": "social_interrupt",
            "candidates": [
                {"text": "帮我挂骨科号对了孙子昨天来电话了", "confidence": 0.95, "engine": "primary"},
                {"text": "挂骨科号孙子昨天来电话", "confidence": 0.90, "engine": "backup"},
            ],
            "side_effect_possible": False, "expected_status": "accepted", "expected_intent": "hospital_registration",
            "risk_level": 3, "message": "我先帮您完成挂号，孙子来电话的事情稍后接着聊。", "options": ["继续挂号", "先暂停"], "expect_teach_back": True,
        })
    OUT.write_text("\n".join(json.dumps(case, ensure_ascii=False, sort_keys=True) for case in cases) + "\n", encoding="utf-8")
    print(json.dumps({"output": str(OUT), "cases": len(cases)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
