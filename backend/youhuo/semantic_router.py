"""Routes an elder utterance to a task domain, with the model as an advisor only.

Design position (see docs/29_V6_RESEARCH_GROUNDING.md and the v5 audit report):
the language model may improve *understanding*, but it must never widen
authority. This module therefore keeps three hard rules:

1. The deterministic keyword classifier always runs and is the floor. When no
   model is configured, when the circuit breaker is open, or when the call
   fails, routing is bit-for-bit identical to the offline behaviour.
2. The model may add coverage the keywords miss, but it may never *remove* a
   task the keywords found, and it may never resolve a disagreement on its own.
   Conflicting readings produce a clarification question, never a guess.
3. Slots the model extracts are advisory. They only fill gaps the deterministic
   extractor left empty, they are recorded by name so the glass-box card can
   show them as unverified, and control-bearing fields such as the payable
   amount can never come from the model.

The model does not choose risk levels, confirmations, approvals or tools. Those
stay in SafetyPolicy, PurposeBoundPolicy and the task state machine.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .models import TaskType
from .v6_models import SemanticParseRequest
from .v6_services import SemanticGateway

#: Model intent -> task domain. Intents absent here (companion, emergency,
#: scam_risk, cancel, confirm, unknown) never open a task by themselves.
_INTENT_TO_TASK: dict[str, TaskType] = {
    "hospital_registration": TaskType.HOSPITAL_REGISTRATION,
    "bill_payment": TaskType.BILL_PAYMENT,
    "reminder": TaskType.REMINDER,
    "form_assistance": TaskType.FORM_ASSISTANCE,
}

#: Model slot name -> engine slot name, per task domain. `amount_cents` and
#: `period` are deliberately absent: a payable amount must come from the
#: authoritative billing tool, never from a language model.
_SLOT_MAP: dict[TaskType, dict[str, str]] = {
    TaskType.HOSPITAL_REGISTRATION: {
        "hospital": "hospital",
        "department": "department",
        "doctor": "doctor",
        "date": "appointment_date",
        "time": "appointment_time",
    },
    TaskType.BILL_PAYMENT: {"bill_type": "bill_type"},
    TaskType.REMINDER: {"title": "title"},
    TaskType.FORM_ASSISTANCE: {},
}

_TASK_LABEL: dict[TaskType, str] = {
    TaskType.HOSPITAL_REGISTRATION: "挂号",
    TaskType.BILL_PAYMENT: "缴费",
    TaskType.REMINDER: "设置提醒",
    TaskType.FORM_ASSISTANCE: "帮您填写",
}


@dataclass(frozen=True)
class RoutingDecision:
    """What the router concluded, and how it got there."""

    task_type: TaskType | None
    #: keyword_only | keyword_floor | agreement | model_only | conflict
    basis: str
    model_used: bool
    parser_source: str
    confidence: float
    conflict_prompt: str | None = None
    advisory_slots: dict[str, Any] = field(default_factory=dict)
    frame_digest: str | None = None

    @property
    def needs_clarification(self) -> bool:
        return self.conflict_prompt is not None

    def audit_payload(self) -> dict[str, Any]:
        return {
            "basis": self.basis,
            "model_used": self.model_used,
            "parser_source": self.parser_source,
            "confidence": self.confidence,
            "task_type": self.task_type.value if self.task_type else None,
            "advisory_fields": sorted(self.advisory_slots),
            "frame_digest": self.frame_digest,
        }


class SemanticRouter:
    """Combines the deterministic classifier with the constrained model gateway."""

    @staticmethod
    def _clarification(keyword_type: TaskType, model_type: TaskType) -> str:
        return (
            f"我不太确定您是想{_TASK_LABEL[keyword_type]}还是{_TASK_LABEL[model_type]}。"
            f"请您说一句“我要{_TASK_LABEL[keyword_type]}”或“我要{_TASK_LABEL[model_type]}”。"
        )

    @classmethod
    def route(
        cls,
        text: str,
        keyword_type: TaskType | None,
        *,
        elder_id: str,
        permit_remote_model: bool,
    ) -> RoutingDecision:
        if not permit_remote_model:
            return RoutingDecision(
                task_type=keyword_type,
                basis="keyword_only",
                model_used=False,
                parser_source="deterministic_keyword",
                confidence=1.0 if keyword_type else 0.0,
            )

        frame = SemanticGateway.parse(
            SemanticParseRequest(elder_id=elder_id, text=text, permit_remote_model=True)
        )
        if not frame.model_used:
            # Gateway fell back offline: keep the deterministic result untouched.
            return RoutingDecision(
                task_type=keyword_type,
                basis="keyword_only",
                model_used=False,
                parser_source=frame.parser_source,
                confidence=1.0 if keyword_type else 0.0,
                frame_digest=frame.frame_digest,
            )

        model_type = _INTENT_TO_TASK.get(frame.intent)
        advisory = cls._advisory_slots(model_type, frame.slots)

        if keyword_type is not None and model_type is not None and keyword_type != model_type:
            # Two defensible readings. Ask rather than pick one.
            return RoutingDecision(
                task_type=None,
                basis="conflict",
                model_used=True,
                parser_source=frame.parser_source,
                confidence=frame.confidence,
                conflict_prompt=cls._clarification(keyword_type, model_type),
                frame_digest=frame.frame_digest,
            )

        if keyword_type is not None:
            basis = "agreement" if model_type == keyword_type else "keyword_floor"
            return RoutingDecision(
                task_type=keyword_type,
                basis=basis,
                model_used=True,
                parser_source=frame.parser_source,
                confidence=frame.confidence,
                advisory_slots=advisory if basis == "agreement" else {},
                frame_digest=frame.frame_digest,
            )

        if model_type is not None:
            # Coverage the keywords missed. The task still enters the normal
            # collecting -> confirm -> execute chain, so nothing is skipped.
            return RoutingDecision(
                task_type=model_type,
                basis="model_only",
                model_used=True,
                parser_source=frame.parser_source,
                confidence=frame.confidence,
                advisory_slots=advisory,
                frame_digest=frame.frame_digest,
            )

        return RoutingDecision(
            task_type=None,
            basis="keyword_only",
            model_used=True,
            parser_source=frame.parser_source,
            confidence=frame.confidence,
            frame_digest=frame.frame_digest,
        )

    @staticmethod
    def _advisory_slots(task_type: TaskType | None, model_slots: dict[str, Any]) -> dict[str, Any]:
        if task_type is None:
            return {}
        mapping = _SLOT_MAP.get(task_type, {})
        advisory: dict[str, Any] = {}
        for model_name, engine_name in mapping.items():
            value = model_slots.get(model_name)
            if isinstance(value, str) and value.strip():
                advisory[engine_name] = value.strip()[:120]
        return advisory


def apply_advisory_slots(slots: dict[str, Any], advisory: dict[str, Any]) -> list[str]:
    """Fill only the gaps the deterministic extractor left, and say which ones.

    Returns the engine slot names that came from the model, so the reliance card
    can present them as "仅供参考" rather than as verified facts.
    """
    filled: list[str] = []
    for name, value in advisory.items():
        if slots.get(name):
            continue  # deterministic extraction always wins
        slots[name] = value
        filled.append(name)
    return sorted(filled)
