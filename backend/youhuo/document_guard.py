from __future__ import annotations

import hashlib
import re
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

    @staticmethod
    def _detect_kind(text: str) -> DocumentKind:
        if any(k in text for k in ("应缴", "账单", "水费", "电费", "燃气费")):
            return DocumentKind.BILL
        if any(k in text for k in ("预约", "挂号", "科室", "就诊")):
            return DocumentKind.APPOINTMENT
        if any(k in text for k in ("用法用量", "每次", "每日", "药品")):
            return DocumentKind.MEDICATION
        return DocumentKind.OTHER

    @classmethod
    def analyze(cls, request: DocumentAnalysisRequest) -> DocumentAnalysis:
        text = request.ocr_text
        warnings: list[str] = []
        if SafetyPolicy.contains_prompt_injection(text):
            warnings.append("文档中含有疑似提示注入或越权指令，已按不可信数据处理")
        kind = cls._detect_kind(text) if request.kind == DocumentKind.AUTO else request.kind
        fields: dict[str, Any] = {}
        if kind == DocumentKind.BILL:
            for bill_type in ("水费", "电费", "燃气费"):
                if bill_type in text:
                    fields["bill_type"] = bill_type
                    break
            amount = re.search(r"(?:应缴|金额|合计)\s*[:：]?\s*[¥￥]?\s*(\d+(?:\.\d{1,2})?)\s*元?", text)
            if amount:
                fields["amount_yuan"] = float(amount.group(1))
            period = re.search(r"(20\d{2})[-年/.](\d{1,2})(?:月)?", text)
            if period:
                fields["period"] = f"{int(period.group(1)):04d}-{int(period.group(2)):02d}"
        elif kind == DocumentKind.APPOINTMENT:
            date = re.search(r"(20\d{2})[-年/.](\d{1,2})[-月/.](\d{1,2})日?", text)
            time = re.search(r"\b([01]?\d|2[0-3])[:：]([0-5]\d)\b", text)
            dept = re.search(r"(?:科室|门诊)\s*[:：]?\s*([\u4e00-\u9fff]{2,12})", text)
            doctor = re.search(r"(?:医生|医师)\s*[:：]?\s*([\u4e00-\u9fff]{2,6})", text)
            if date:
                fields["appointment_date"] = f"{int(date.group(1)):04d}-{int(date.group(2)):02d}-{int(date.group(3)):02d}"
            if time:
                fields["appointment_time"] = f"{int(time.group(1)):02d}:{int(time.group(2)):02d}"
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
            and kind != DocumentKind.MEDICATION
            and not SafetyPolicy.contains_prompt_injection(text)
        )
        return DocumentAnalysis(
            kind=kind,
            fields=fields,
            warnings=warnings,
            safe_for_autofill=safe,
            source_digest=hashlib.sha256(text.encode("utf-8")).hexdigest(),
            human_review_required=not safe or kind == DocumentKind.MEDICATION,
        )
