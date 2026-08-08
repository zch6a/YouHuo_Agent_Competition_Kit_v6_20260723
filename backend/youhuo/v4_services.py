from __future__ import annotations

import calendar
import hashlib
import json
import math
import re
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from pathlib import Path
from typing import Any, Iterable
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from .security import SafetyPolicy
from .utils import clean_user_text, semantic_hash
from .v4_models import (
    EmotionAnalysis,
    EmotionLabel,
    GeofenceResult,
    InteractionCheckResult,
    InteractionFinding,
    InventoryForecast,
    MedicalDocumentKind,
    MedicalReportAnalysis,
    POIKind,
    POIRecord,
    RoutineCreate,
    RoutineFrequency,
)


class RecurrenceEngine:
    """Deterministic recurrence calculator with explicit timezone handling.

    It intentionally avoids free-form RRULE parsing. The contest prototype supports
    the three routine forms used by the product: daily, selected weekdays, and a
    day-of-month schedule. Invalid days such as the 31st in February are clamped to
    the month's final day and are never silently skipped.
    """

    @staticmethod
    def _tz(name: str) -> ZoneInfo:
        try:
            return ZoneInfo(name)
        except ZoneInfoNotFoundError as exc:
            raise ValueError(f"unknown timezone: {name}") from exc

    @staticmethod
    def _local_datetime(day: date, hhmm: str, timezone: str) -> datetime:
        hour, minute = (int(part) for part in hhmm.split(":"))
        return datetime.combine(day, time(hour, minute), tzinfo=RecurrenceEngine._tz(timezone))

    @classmethod
    def first_due(cls, spec: RoutineCreate) -> datetime:
        local_start = cls._local_datetime(spec.start_date, spec.time_local, spec.timezone)
        if spec.frequency == RoutineFrequency.DAILY:
            return local_start.astimezone(UTC)
        if spec.frequency == RoutineFrequency.WEEKLY:
            for offset in range(0, 14):
                candidate = spec.start_date + timedelta(days=offset)
                if candidate.weekday() in spec.weekdays:
                    return cls._local_datetime(candidate, spec.time_local, spec.timezone).astimezone(UTC)
            raise ValueError("unable to calculate weekly first due")
        day = min(spec.day_of_month or 1, calendar.monthrange(spec.start_date.year, spec.start_date.month)[1])
        candidate = date(spec.start_date.year, spec.start_date.month, day)
        if candidate < spec.start_date:
            year, month = cls._add_months(spec.start_date.year, spec.start_date.month, spec.interval)
            day = min(spec.day_of_month or 1, calendar.monthrange(year, month)[1])
            candidate = date(year, month, day)
        return cls._local_datetime(candidate, spec.time_local, spec.timezone).astimezone(UTC)

    @staticmethod
    def _add_months(year: int, month: int, amount: int) -> tuple[int, int]:
        absolute = year * 12 + (month - 1) + amount
        return absolute // 12, absolute % 12 + 1

    @classmethod
    def next_after(
        cls,
        *,
        current_due_utc: datetime,
        frequency: RoutineFrequency,
        interval: int,
        weekdays: list[int],
        day_of_month: int | None,
        time_local: str,
        timezone: str,
    ) -> datetime:
        tz = cls._tz(timezone)
        current_local = current_due_utc.astimezone(tz)
        if frequency == RoutineFrequency.DAILY:
            candidate = current_local.date() + timedelta(days=interval)
        elif frequency == RoutineFrequency.WEEKLY:
            candidate = current_local.date() + timedelta(days=1)
            max_scan = 7 * max(interval, 1) + 7
            weeks_elapsed = 0
            start_week = current_local.date() - timedelta(days=current_local.weekday())
            for _ in range(max_scan):
                candidate_week = candidate - timedelta(days=candidate.weekday())
                weeks_elapsed = (candidate_week - start_week).days // 7
                if candidate.weekday() in weekdays and weeks_elapsed % interval == 0:
                    break
                candidate += timedelta(days=1)
            else:
                raise ValueError("unable to calculate next weekly due")
        else:
            year, month = cls._add_months(current_local.year, current_local.month, interval)
            last_day = calendar.monthrange(year, month)[1]
            candidate = date(year, month, min(day_of_month or 1, last_day))
        return cls._local_datetime(candidate, time_local, timezone).astimezone(UTC)


class EmotionAnalyzer:
    """Small, explainable, offline emotional-signal layer.

    It is deliberately not a clinical diagnosis model. It detects explicit lexical
    cues so the product can pause a task, ask a clarifying question, or trigger the
    already-existing emergency policy. Raw text is never required in family reports.
    """

    _urgent = {"不想活", "活着没意思", "想死", "救命", "胸口痛", "喘不过气", "摔倒起不来", "煤气泄漏"}
    _lonely = {"没人陪", "没人说话", "很孤单", "好孤独", "想孩子", "没人管我", "一个人"}
    _low = {"没意思", "心里难受", "高兴不起来", "不开心", "难过", "想哭", "没精神", "什么都不想做"}
    _anxious = {"担心", "害怕", "紧张", "睡不着", "心慌", "着急", "怎么办"}
    _angry = {"生气", "气死我", "烦死了", "讨厌", "别管我"}
    _positive = {"开心", "高兴", "很好", "真棒", "舒服", "放心", "谢谢", "有精神"}
    _negators = {"不", "没有", "没", "别"}

    @staticmethod
    def _contains(text: str, phrases: Iterable[str]) -> list[str]:
        return [phrase for phrase in phrases if phrase in text]

    @classmethod
    def analyze(cls, text: str) -> EmotionAnalysis:
        normalized = clean_user_text(text, max_length=2000).casefold()
        safety = SafetyPolicy.detect_safety_signal(normalized)
        urgent_hits = cls._contains(normalized, cls._urgent)
        lonely_hits = cls._contains(normalized, cls._lonely)
        low_hits = cls._contains(normalized, cls._low)
        anxious_hits = cls._contains(normalized, cls._anxious)
        angry_hits = cls._contains(normalized, cls._angry)
        positive_hits = cls._contains(normalized, cls._positive)

        categories: list[str] = []
        for name, hits in (
            ("urgent", urgent_hits),
            ("lonely", lonely_hits),
            ("low_mood", low_hits),
            ("anxious", anxious_hits),
            ("angry", angry_hits),
            ("positive", positive_hits),
        ):
            if hits:
                categories.append(name)

        if safety or urgent_hits:
            return EmotionAnalysis(
                label=EmotionLabel.URGENT,
                valence=-1.0,
                arousal=0.95,
                distress=1.0,
                confidence=0.99,
                evidence_categories=categories or ["urgent"],
                should_pause_task=True,
                should_notify_family=True,
                user_message=(
                    safety.message if safety else "我很在意您刚才说的话。先不要一个人处理，我会立即提醒家人联系您。"
                ),
                privacy_safe_note="检测到需要立即人工确认的高风险表达。",
            )

        negative_strength = len(lonely_hits) * 0.22 + len(low_hits) * 0.28 + len(anxious_hits) * 0.2 + len(angry_hits) * 0.18
        positive_strength = len(positive_hits) * 0.22
        distress = min(0.92, negative_strength)
        valence = max(-1.0, min(1.0, positive_strength - negative_strength))
        arousal = min(0.9, 0.18 + len(anxious_hits) * 0.2 + len(angry_hits) * 0.25 + len(low_hits) * 0.08)

        if lonely_hits:
            label = EmotionLabel.LONELY
            message = "我听见您有些孤单。我们可以先聊一会儿，原来的事情我会替您安全保留。"
        elif low_hits:
            label = EmotionLabel.LOW_MOOD
            message = "听起来您现在心情不太好。我们先慢一点，我陪您聊聊，再决定是否继续办事。"
        elif anxious_hits:
            label = EmotionLabel.ANXIOUS
            message = "别着急，我们一次只做一步。我会先把事情暂停在这里，不会丢失。"
        elif angry_hits:
            label = EmotionLabel.ANGRY
            message = "我听见您有些生气。我们先停一下，等您准备好再继续。"
        elif positive_hits:
            label = EmotionLabel.POSITIVE
            distress = 0.0
            valence = max(0.45, valence)
            message = "听到您心情不错，我也很高兴。"
        else:
            label = EmotionLabel.CALM
            distress = 0.05
            valence = 0.0
            arousal = 0.15
            message = "我在听。"

        pause_threshold = 0.30 if label == EmotionLabel.ANGRY else (0.35 if label == EmotionLabel.ANXIOUS else 0.42)
        should_pause = distress >= pause_threshold and label in {
            EmotionLabel.LONELY,
            EmotionLabel.LOW_MOOD,
            EmotionLabel.ANXIOUS,
            EmotionLabel.ANGRY,
        }
        confidence = min(0.96, 0.55 + 0.1 * sum(bool(x) for x in (lonely_hits, low_hits, anxious_hits, angry_hits, positive_hits)))
        safe_note_map = {
            EmotionLabel.LONELY: "本周出现孤独感表达，建议增加温和联系。",
            EmotionLabel.LOW_MOOD: "本周出现低落表达，建议家人以关心方式联系。",
            EmotionLabel.ANXIOUS: "本周出现焦虑或担忧表达，建议协助梳理事务。",
            EmotionLabel.ANGRY: "本周出现烦躁表达，建议避免催促并择时沟通。",
            EmotionLabel.POSITIVE: "本周出现积极情绪表达。",
            EmotionLabel.CALM: "未检测到明显情绪风险信号。",
        }
        return EmotionAnalysis(
            label=label,
            valence=round(valence, 4),
            arousal=round(arousal, 4),
            distress=round(distress, 4),
            confidence=round(confidence, 4),
            evidence_categories=categories,
            should_pause_task=should_pause,
            should_notify_family=False,
            user_message=message,
            privacy_safe_note=safe_note_map[label],
        )


class MedicalReportInterpreter:
    _glossary = {
        "高密度脂蛋白": "通常被称为“好胆固醇”，但单项结果不能代替医生判断。",
        "低密度脂蛋白": "通常被称为“坏胆固醇”，需要结合整体心血管风险由医生评估。",
        "甘油三酯": "血脂检查的一项，受饮食、代谢等多种因素影响。",
        "空腹血糖": "空腹状态下的血糖值，需要结合复查和医生意见判断。",
        "糖化血红蛋白": "反映过去一段时间平均血糖水平的指标。",
        "收缩压": "血压读数中较高的数值。",
        "舒张压": "血压读数中较低的数值。",
        "窦性心律": "心脏节律由正常起搏点发出的一种描述。",
        "结节": "影像中看到的局部小区域，不等于癌症，需要按报告建议复查。",
        "肝功能": "反映肝脏相关状态的一组化验指标。",
        "肾功能": "反映肾脏过滤和代谢状态的一组指标。",
    }
    _date_patterns = [
        re.compile(r"(?P<y>20\d{2})[年\-/\.](?P<m>\d{1,2})[月\-/\.](?P<d>\d{1,2})日?"),
        re.compile(r"(?P<m>\d{1,2})月(?P<d>\d{1,2})日"),
    ]
    _measure_patterns = [
        ("血压", re.compile(r"(?:血压|BP)\s*[:：]?\s*(\d{2,3})\s*/\s*(\d{2,3})\s*(?:mmHg)?", re.I), "mmHg"),
        ("空腹血糖", re.compile(r"(?:空腹血糖|GLU)\s*[:：]?\s*(\d+(?:\.\d+)?)\s*(mmol/L)?", re.I), "mmol/L"),
        ("糖化血红蛋白", re.compile(r"(?:糖化血红蛋白|HbA1c)\s*[:：]?\s*(\d+(?:\.\d+)?)\s*%?", re.I), "%"),
        ("心率", re.compile(r"(?:心率|HR)\s*[:：]?\s*(\d{2,3})\s*(?:次/分|bpm)?", re.I), "次/分"),
        ("体重", re.compile(r"(?:体重|Weight)\s*[:：]?\s*(\d+(?:\.\d+)?)\s*kg", re.I), "kg"),
    ]

    @classmethod
    def analyze(cls, *, kind: MedicalDocumentKind, text: str, today: date | None = None) -> MedicalReportAnalysis:
        today = today or datetime.now(UTC).date()
        cleaned = clean_user_text(text, max_length=12000)
        dates: list[str] = []
        for pattern in cls._date_patterns:
            for match in pattern.finditer(cleaned):
                groups = match.groupdict()
                year = int(groups.get("y") or today.year)
                month, day = int(groups["m"]), int(groups["d"])
                try:
                    value = date(year, month, day).isoformat()
                except ValueError:
                    continue
                if value not in dates:
                    dates.append(value)

        measurements: list[dict[str, Any]] = []
        for name, pattern, unit in cls._measure_patterns:
            for match in pattern.finditer(cleaned):
                values = [group for group in match.groups() if group and not group.casefold().startswith("mmol")]
                if name == "血压" and len(values) >= 2:
                    measurements.append({"name": name, "value": f"{values[0]}/{values[1]}", "unit": unit})
                elif values:
                    measurements.append({"name": name, "value": values[0], "unit": unit})
                break

        terms = [{"term": term, "plain_language": explanation} for term, explanation in cls._glossary.items() if term in cleaned]
        follow_up_date: str | None = None
        follow_match = re.search(
            r"(?:复查|复诊|随访)[^。；\n]{0,20}?(20\d{2}[年\-/\.]\d{1,2}[月\-/\.]\d{1,2}日?|\d{1,2}月\d{1,2}日)",
            cleaned,
        )
        if follow_match:
            nested = cls.analyze(kind=MedicalDocumentKind.APPOINTMENT_NOTICE, text=follow_match.group(1), today=today)
            follow_up_date = nested.dates[0] if nested.dates else None
        elif any(token in cleaned for token in ("复查", "复诊", "随访")):
            # Reports often place the date before the verb: “建议2026年8月20日复查”。
            reverse_match = re.search(
                r"(20\d{2}[年\-/\.]\d{1,2}[月\-/\.]\d{1,2}日?|\d{1,2}月\d{1,2}日)[^。；\n]{0,12}?(?:复查|复诊|随访)",
                cleaned,
            )
            if reverse_match:
                nested = cls.analyze(kind=MedicalDocumentKind.APPOINTMENT_NOTICE, text=reverse_match.group(1), today=today)
                follow_up_date = nested.dates[0] if nested.dates else None

        caution_flags: list[str] = []
        for token, flag in (
            ("急诊", "报告文字中出现“急诊”，请尽快由医护人员确认。"),
            ("立即就医", "报告文字中出现“立即就医”，请不要仅依赖AI解释。"),
            ("危急值", "报告文字中出现“危急值”，应立即联系医疗机构。"),
            ("恶性", "报告包含高风险医学用语，必须由医生解释。"),
        ):
            if token in cleaned:
                caution_flags.append(flag)

        if terms:
            term_text = "；".join(f"{item['term']}：{item['plain_language']}" for item in terms[:4])
            summary = f"我识别到这些医学词语：{term_text}"
        else:
            summary = "我已经整理了报告中的日期和可识别指标，但没有找到可安全简化的医学术语。"
        if follow_up_date:
            summary += f" 报告中可能提到复查日期 {follow_up_date}，请确认后再加入日历。"
        summary += " 这只是文字整理，不是诊断，最终请以医生解释为准。"

        return MedicalReportAnalysis(
            kind=kind,
            dates=dates,
            measurements=measurements,
            terms=terms,
            follow_up_date=follow_up_date,
            summary_for_elder=summary,
            caution_flags=caution_flags,
            review_required=True,
            source_digest=hashlib.sha256(cleaned.encode("utf-8")).hexdigest(),
        )


class MedicationKnowledgeBase:
    """A deliberately small, auditable demonstration rule set.

    It is not a comprehensive clinical interaction database. The project uses it to
    demonstrate normalized medication records, evidence-labelled findings and a hard
    requirement for pharmacist review. Production must connect to a licensed and
    region-appropriate source.
    """

    def __init__(self, path: str | Path | None = None) -> None:
        # Ships inside the package, not in data/. This is read-only reference
        # data, while data/ holds the mutable database and is a mounted volume in
        # every container deployment — a volume at /app/data shadowed this file,
        # so the image crash-looped on startup before create_app() finished.
        default = Path(__file__).resolve().parent / "reference" / "medication_interactions_demo.json"
        self.path = Path(path) if path else default
        if not self.path.is_file():
            raise FileNotFoundError(
                f"用药参考数据缺失：{self.path}。它随包发布，请确认打包时包含 "
                "backend/youhuo/reference/ 目录。"
            )
        payload = json.loads(self.path.read_text(encoding="utf-8"))
        self.aliases: dict[str, str] = {k.casefold(): v.casefold() for k, v in payload["aliases"].items()}
        self.rules = payload["rules"]

    def normalize(self, name: str) -> str:
        cleaned = clean_user_text(name, max_length=120).casefold().replace(" ", "")
        return self.aliases.get(cleaned, cleaned)

    def check(self, names: list[str]) -> InteractionCheckResult:
        normalized = sorted(set(self.normalize(name) for name in names))
        findings: list[InteractionFinding] = []
        for rule in self.rules:
            pair = {rule["a"].casefold(), rule["b"].casefold()}
            if pair.issubset(set(normalized)):
                findings.append(
                    InteractionFinding(
                        medication_a=rule["a"],
                        medication_b=rule["b"],
                        severity=rule["severity"],
                        message=rule["message"],
                        source=rule["source"],
                        evidence_level=rule["evidence_level"],
                    )
                )
        return InteractionCheckResult(
            normalized_medications=normalized,
            findings=findings,
            database_scope="仅比赛演示用的有限规则集；药名标准化结构参考RxNorm思想，不覆盖全部药品或相互作用。",
            requires_pharmacist_review=True,
            warning="任何结果都不能替代医生或药师判断；未发现规则也不代表一定安全。",
        )


class InventoryService:
    @staticmethod
    def forecast(*, plan_id: str, stock_units: float, units_per_dose: float, doses_per_day: int, today: date) -> InventoryForecast:
        units_per_day = units_per_dose * doses_per_day
        if units_per_day <= 0:
            return InventoryForecast(
                plan_id=plan_id,
                stock_units=stock_units,
                units_per_day=0,
                days_remaining=None,
                estimated_depletion_date=None,
                alert_level="unknown",
            )
        days = stock_units / units_per_day
        depletion = today + timedelta(days=max(0, math.floor(days)))
        if days < 2:
            alert = "critical"
        elif days < 7:
            alert = "warning"
        else:
            alert = "normal"
        return InventoryForecast(
            plan_id=plan_id,
            stock_units=round(stock_units, 3),
            units_per_day=round(units_per_day, 3),
            days_remaining=round(days, 2),
            estimated_depletion_date=depletion,
            alert_level=alert,
        )


class LocationSafety:
    @staticmethod
    def haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
        radius = 6_371_000.0
        phi1, phi2 = math.radians(lat1), math.radians(lat2)
        d_phi = math.radians(lat2 - lat1)
        d_lambda = math.radians(lon2 - lon1)
        a = math.sin(d_phi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(d_lambda / 2) ** 2
        return radius * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))

    @classmethod
    def evaluate_geofence(
        cls,
        *,
        latitude: float,
        longitude: float,
        accuracy_m: float,
        home_lat: float | None,
        home_lon: float | None,
        radius_m: int,
    ) -> GeofenceResult:
        if home_lat is None or home_lon is None:
            return GeofenceResult(
                inside_home_area=None,
                distance_from_home_m=None,
                alert_created=False,
                accuracy_warning=accuracy_m > 200,
                message="尚未设置家庭活动范围，已仅记录本次位置。",
            )
        distance = cls.haversine_m(latitude, longitude, home_lat, home_lon)
        accuracy_warning = accuracy_m > max(200, radius_m * 0.5)
        outside = distance > radius_m + accuracy_m
        ambiguous = abs(distance - radius_m) <= accuracy_m
        if ambiguous:
            message = "当前位置接近活动范围边界，定位精度不足，暂不自动报警。"
            alert = False
            inside: bool | None = None
        elif outside:
            message = "检测到设备超出已授权的日常活动范围，已生成家属核实提醒。"
            alert = True
            inside = False
        else:
            message = "当前位置在已授权的日常活动范围内。"
            alert = False
            inside = True
        return GeofenceResult(
            inside_home_area=inside,
            distance_from_home_m=round(distance, 2),
            alert_created=alert,
            accuracy_warning=accuracy_warning,
            message=message,
        )


class DemoPOICatalog:
    _base = [
        ("社区卫生服务中心", POIKind.HOSPITAL, 39.9050, 116.3970),
        ("仁和药店", POIKind.PHARMACY, 39.9072, 116.3995),
        ("便民菜市场", POIKind.MARKET, 39.9028, 116.3958),
        ("市第一医院", POIKind.HOSPITAL, 39.9120, 116.4050),
        ("安心大药房", POIKind.PHARMACY, 39.8998, 116.3915),
    ]

    @classmethod
    def nearby(cls, *, latitude: float, longitude: float, kind: POIKind, limit: int = 5) -> list[POIRecord]:
        rows: list[POIRecord] = []
        for name, item_kind, lat, lon in cls._base:
            if item_kind != kind:
                continue
            distance = LocationSafety.haversine_m(latitude, longitude, lat, lon)
            rows.append(
                POIRecord(
                    name=name,
                    kind=kind,
                    latitude=lat,
                    longitude=lon,
                    distance_m=round(distance, 1),
                    navigation_instruction=f"已为您准备前往{name}的导航请求，正式版将调用华为地图或导航服务。",
                )
            )
        return sorted(rows, key=lambda item: item.distance_m)[:limit]


@dataclass(frozen=True)
class AttentionDecision:
    deliver_now: bool
    channel: str
    reason: str


class FamilyAttentionBudget:
    """Avoids flooding family members with low-value notifications."""

    _immediate = {"sos", "urgent_emotion", "geofence_exit", "medication_critical", "inactivity_critical"}

    @classmethod
    def decide(cls, event_type: str, *, unread_low_priority: int = 0) -> AttentionDecision:
        if event_type in cls._immediate:
            return AttentionDecision(True, "push", "高风险事件必须立即通知。")
        if unread_low_priority >= 5:
            return AttentionDecision(False, "digest", "低优先级提醒已聚合，避免家属通知疲劳。")
        return AttentionDecision(True, "in_app", "普通事务通过应用内通知送达。")


class FaceTemplateService:
    """Privacy-preserving demo template based on exact image digest.

    This is intentionally not marketed as biometric recognition. An optional
    InsightFace adapter can replace it after explicit consent, model licensing review,
    liveness detection and device-side security validation.
    """

    ENGINE_NAME = "exact-image-digest-demo"

    @staticmethod
    def template(image_bytes: bytes) -> str:
        return hashlib.sha256(image_bytes).hexdigest()


class HealthFHIRExporter:
    @staticmethod
    def bundle(*, elder_id: str, health_events: list[dict[str, Any]], medication_plans: list[dict[str, Any]]) -> dict[str, Any]:
        entries: list[dict[str, Any]] = []
        for event in health_events:
            resource_type = "Observation" if event.get("kind") == "checkup" else "Encounter"
            entries.append(
                {
                    "resource": {
                        "resourceType": resource_type,
                        "id": event["id"],
                        "status": "final" if resource_type == "Observation" else "finished",
                        "subject": {"reference": f"Patient/{elder_id}"},
                        "effectiveDateTime": event["event_at"],
                        "code": {"text": event["title"]},
                        "extension": [{"url": "https://youhuo.example/scope", "valueString": event.get("scope", "family_summary")}],
                    }
                }
            )
        for plan in medication_plans:
            entries.append(
                {
                    "resource": {
                        "resourceType": "MedicationStatement",
                        "id": plan["id"],
                        "status": "active" if plan.get("active") else "stopped",
                        "subject": {"reference": f"Patient/{elder_id}"},
                        "medicationCodeableConcept": {"text": plan["display_name"]},
                        "dosage": [{"text": plan["dose_text"], "timing": {"repeat": {"timeOfDay": plan["times_local"]}}}],
                    }
                }
            )
        return {
            "resourceType": "Bundle",
            "type": "collection",
            "timestamp": datetime.now(UTC).isoformat(),
            "entry": entries,
            "meta": {"tag": [{"system": "https://youhuo.example", "code": "prototype-not-clinical"}]},
        }


class CapabilityMatrix:
    @staticmethod
    def all() -> list[dict[str, str | None]]:
        return [
            {
                "capability": "voice_web_demo",
                "state": "implemented",
                "implementation": "浏览器语音识别与语音播报",
                "production_dependency": "HarmonyOS系统级ASR/TTS与唤醒词能力",
                "safety_boundary": "识别结果在执行前仍经过确定性确认。",
            },
            {
                "capability": "hospital_and_bill_workflows",
                "state": "implemented_sandbox",
                "implementation": "挂号、缴费、确认、家属审批与完成证明",
                "production_dependency": "医院、公共事业和支付机构正式沙箱或API",
                "safety_boundary": "支付不自动扣款；身份认证只能引导本人完成。",
            },
            {
                "capability": "recurring_routines_reports",
                "state": "implemented",
                "implementation": "日/周/月循环任务、月报和提醒物化",
                "production_dependency": "Push Kit用于真机推送",
                "safety_boundary": "重复物化幂等，过期任务不自动执行高风险操作。",
            },
            {
                "capability": "emotion_privacy_reports",
                "state": "implemented_nonclinical",
                "implementation": "可解释词典信号、任务暂停与无隐私周报",
                "production_dependency": "真实用户共创与方言评测",
                "safety_boundary": "不诊断心理疾病；高风险表达转人工。",
            },
            {
                "capability": "medication_management",
                "state": "implemented_demo",
                "implementation": "计划、服药记录、库存预测和有限相互作用规则",
                "production_dependency": "合法授权的区域药品知识库和药师审核",
                "safety_boundary": "未发现规则不代表安全，始终要求医生或药师复核。",
            },
            {
                "capability": "face_contact_memory",
                "state": "safe_demo_only",
                "implementation": "只保存精确图片摘要的演示匹配",
                "production_dependency": "端侧人脸模型、活体检测、许可与生物信息合规",
                "safety_boundary": "不得宣传为真实人脸识别，不能用于身份认证。",
            },
            {
                "capability": "location_geofence_navigation",
                "state": "implemented_adapter_demo",
                "implementation": "位置事件、精度感知围栏和POI目录",
                "production_dependency": "Huawei Location Kit、Map Kit、Navi Kit",
                "safety_boundary": "边界精度不足不自动报警，位置最小化留存。",
            },
            {
                "capability": "health_record_export",
                "state": "implemented_prototype",
                "implementation": "健康时间线、报告术语简化与FHIR风格Bundle导出",
                "production_dependency": "医疗机构数据授权和FHIR一致性验证",
                "safety_boundary": "仅整理和解释术语，不给诊断或治疗建议。",
            },
        ]
