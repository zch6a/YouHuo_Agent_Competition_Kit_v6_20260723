from __future__ import annotations

import hashlib
import math
import re
from datetime import date
from decimal import Decimal, InvalidOperation
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator

from .security import SafetyPolicy
from .utils import clean_user_text


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class DocumentKind(StrEnum):
    AUTO = "auto"
    BILL = "bill"
    APPOINTMENT = "appointment"
    MEDICATION = "medication"
    OTHER = "other"


class DocumentAnalysisRequest(StrictModel):
    ocr_text: str = Field(min_length=1, max_length=5000)
    kind: DocumentKind = DocumentKind.AUTO

    @field_validator("ocr_text")
    @classmethod
    def normalize(cls, value: str) -> str:
        return clean_user_text(value, max_length=5000)


class DocumentAnalysis(StrictModel):
    kind: DocumentKind
    fields: dict[str, Any]
    warnings: list[str]
    safe_for_autofill: bool
    source_digest: str
    human_review_required: bool


class DocumentGuard:
    """Treat OCR/VLM output as untrusted data and extract only allowlisted fields."""

    _MEDICATION_MARKERS = ("用法用量", "每次", "每日", "药品", "药品单", "处方", "剂量", "服用")
    _AMOUNT_TOKEN = re.compile(
        r"(?:应缴|金额|合计)\s*[:：]?\s*[¥￥]?\s*"
        r"(?P<amount>\d[\d,]*(?:\.\d+)?)"
        r"(?=\s*元?(?:\s|$|[，。；;]))"
    )

    @classmethod
    def _contains_medication_content(cls, text: str) -> bool:
        return any(marker in text for marker in cls._MEDICATION_MARKERS)

    @classmethod
    def _detect_kind(cls, text: str) -> DocumentKind:
        # Medication content has the highest safety precedence.  A mixed document
        # such as "药品单……账单" must never be downgraded to a bill merely because
        # the bill keywords happen to be checked first.
        if cls._contains_medication_content(text):
            return DocumentKind.MEDICATION
        if any(k in text for k in ("应缴", "账单", "水费", "电费", "燃气费")):
            return DocumentKind.BILL
        if any(k in text for k in ("预约", "挂号", "科室", "就诊")):
            return DocumentKind.APPOINTMENT
        return DocumentKind.OTHER

    @staticmethod
    def _parse_amount_token(token: str) -> Decimal | None:
        if "," in token:
            if re.fullmatch(r"\d{1,3}(?:,\d{3})+(?:\.\d{1,2})?", token) is None:
                return None
        elif re.fullmatch(r"\d+(?:\.\d{1,2})?", token) is None:
            return None
        try:
            amount = Decimal(token.replace(",", ""))
        except InvalidOperation:
            return None
        if not amount.is_finite() or amount < 0:
            return None
        return amount

    @classmethod
    def _extract_amount_yuan(cls, text: str) -> tuple[float | None, str | None]:
        """Return one unambiguous, fully validated bill amount.

        A document can contain multiple amount-like labels (old balance, current
        amount, subtotal).  Selecting the first one is unsafe: OCR order is not a
        trust signal.  Repeated identical values are harmless corroboration, while
        malformed or conflicting values force human review.
        """
        matches = list(cls._AMOUNT_TOKEN.finditer(text))
        if not matches:
            return None, None
        parsed: list[Decimal] = []
        for match in matches:
            token = match.group("amount")
            amount = cls._parse_amount_token(token)
            if amount is None:
                return None, "检测到账单金额格式异常，未自动填充金额，请人工核对"
            parsed.append(amount)
        unique = set(parsed)
        if len(unique) != 1:
            return None, "检测到多个不一致的账单金额，未猜测选择，请人工核对"
        amount_float = float(parsed[0])
        # `Decimal` itself can represent hundreds of digits, while the public
        # response currently exposes amount_yuan as a JSON number.  Converting an
        # OCR token such as 400 nines used to produce +Infinity and still mark the
        # bill safe.  Also reject values whose cents cannot survive the float
        # round-trip instead of silently changing a financial amount.
        if not math.isfinite(amount_float) or Decimal(str(amount_float)) != parsed[0]:
            return None, "账单金额超出可安全表示范围，未自动填充金额，请人工核对"
        return amount_float, None

    @staticmethod
    def _extract_unique_bill_period(text: str) -> tuple[str | None, str | None]:
        matches = list(re.finditer(r"(?<!\d)(20\d{2})[-年/.](\d{1,2})(?:月)?(?!\d)", text))
        if not matches:
            return None, None
        values: set[str] = set()
        for match in matches:
            month = int(match.group(2))
            if not 1 <= month <= 12:
                return None, "检测到无效账期月份，未自动填充账期，请人工核对"
            values.add(f"{int(match.group(1)):04d}-{month:02d}")
        if len(values) != 1:
            return None, "检测到多个不一致的账期，未猜测选择，请人工核对"
        return next(iter(values)), None

    @staticmethod
    def _extract_unique_appointment_date(text: str) -> tuple[str | None, str | None]:
        matches = list(re.finditer(r"(?<!\d)(20\d{2})[-年/.](\d{1,2})[-月/.](\d{1,2})日?(?!\d)", text))
        if not matches:
            return None, None
        values: set[str] = set()
        for match in matches:
            try:
                value = date(int(match.group(1)), int(match.group(2)), int(match.group(3))).isoformat()
            except ValueError:
                return None, "检测到无效预约日期，未自动填充日期，请人工核对"
            values.add(value)
        if len(values) != 1:
            return None, "检测到多个不一致的预约日期，未猜测选择，请人工核对"
        return next(iter(values)), None

    @staticmethod
    def _extract_unique_appointment_time(text: str) -> tuple[str | None, str | None]:
        matches = list(re.finditer(r"(?<!\d)([01]?\d|2[0-3])[:：]([0-5]\d)(?!\d)", text))
        if not matches:
            return None, None
        values = {f"{int(match.group(1)):02d}:{int(match.group(2)):02d}" for match in matches}
        if len(values) != 1:
            return None, "检测到多个不一致的预约时间，未猜测选择，请人工核对"
        return next(iter(values)), None

    @classmethod
    def analyze(cls, request: DocumentAnalysisRequest) -> DocumentAnalysis:
        text = request.ocr_text
        warnings: list[str] = []
        if SafetyPolicy.contains_prompt_injection(text):
            warnings.append("文档中含有疑似提示注入或越权指令，已按不可信数据处理")
        medication_content = cls._contains_medication_content(text)
        kind = cls._detect_kind(text) if request.kind == DocumentKind.AUTO else request.kind
        if medication_content and kind != DocumentKind.MEDICATION:
            warnings.append("检测到药品相关内容，即使文档被指定为其他类型也必须人工复核")
        fields: dict[str, Any] = {}
        extraction_issue = False
        if kind == DocumentKind.BILL:
            for bill_type in ("水费", "电费", "燃气费"):
                if bill_type in text:
                    fields["bill_type"] = bill_type
                    break
            amount, amount_warning = cls._extract_amount_yuan(text)
            if amount is not None:
                fields["amount_yuan"] = amount
            if amount_warning:
                warnings.append(amount_warning)
                extraction_issue = True
            period, period_warning = cls._extract_unique_bill_period(text)
            if period:
                fields["period"] = period
            if period_warning:
                warnings.append(period_warning)
                extraction_issue = True
        elif kind == DocumentKind.APPOINTMENT:
            appointment_date, date_warning = cls._extract_unique_appointment_date(text)
            appointment_time, time_warning = cls._extract_unique_appointment_time(text)
            dept = re.search(r"(?:科室|门诊)\s*[:：]?\s*([\u4e00-\u9fff]{2,12}?)(?=\s*(?:医生|医师|20\d{2}|[，,。；;]|$))", text)
            doctor = re.search(r"(?:医生|医师)\s*[:：]?\s*([\u4e00-\u9fff]{2,6})", text)
            if appointment_date:
                fields["appointment_date"] = appointment_date
            if appointment_time:
                fields["appointment_time"] = appointment_time
            if date_warning:
                warnings.append(date_warning)
            if time_warning:
                warnings.append(time_warning)
            if dept:
                fields["department"] = dept.group(1)
            if doctor:
                fields["doctor"] = doctor.group(1)
        elif kind == DocumentKind.MEDICATION:
            dose = re.search(r"每次\s*([\d.]+)\s*(片|粒|毫升|ml|袋)", text, flags=re.I)
            freq = re.search(r"每日\s*([一二两三四五六七八九十\d]+)\s*次", text)
            if dose:
                fields["dose"] = dose.group(1) + dose.group(2)
            if freq:
                fields["frequency"] = freq.group(1) + "次/日"
            warnings.append("药品信息只做朗读和提醒，不提供诊断或自行调整剂量")
        if not fields:
            warnings.append("未提取到足够结构化字段，请人工核对")
        required_by_kind = {
            DocumentKind.BILL: {"bill_type", "amount_yuan"},
            DocumentKind.APPOINTMENT: {"appointment_date", "appointment_time"},
            DocumentKind.MEDICATION: {"dose", "frequency"},
            DocumentKind.OTHER: set(),
            DocumentKind.AUTO: set(),
        }
        required = required_by_kind[kind]
        safe = (
            bool(required)
            and required.issubset(fields)
            and not extraction_issue
            and kind != DocumentKind.MEDICATION
            and not medication_content
            and not SafetyPolicy.contains_prompt_injection(text)
        )
        return DocumentAnalysis(
            kind=kind,
            fields=fields,
            warnings=warnings,
            safe_for_autofill=safe,
            source_digest=hashlib.sha256(text.encode("utf-8")).hexdigest(),
            human_review_required=not safe or medication_content or kind == DocumentKind.MEDICATION,
        )
