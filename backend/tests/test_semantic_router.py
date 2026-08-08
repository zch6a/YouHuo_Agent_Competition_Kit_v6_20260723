"""P0-3: the model advises the semantic layer and never widens authority.

Every test stubs the gateway, so the suite stays offline and deterministic while
still exercising the model-advised branches.
"""

from __future__ import annotations

import pytest

from youhuo import engine as engine_module
from youhuo import semantic_router as router_module
from youhuo.models import ChatRequest, TaskType
from youhuo.semantic_router import SemanticRouter, apply_advisory_slots
from youhuo.v6_models import SemanticFrame


def frame(intent: str, *, slots=None, model_used=True, confidence=0.9) -> SemanticFrame:
    return SemanticFrame(
        intent=intent,
        confidence=confidence,
        slots=slots or {},
        needs_clarification=False,
        clarification_prompt=None,
        parser_source="remote_model_validated" if model_used else "deterministic_fallback",
        model_used=model_used,
        safety_flags=[],
        frame_digest="d" * 64,
    )


@pytest.fixture
def stub_model(monkeypatch):
    """Install a canned gateway reply and pretend a model endpoint is configured."""

    def install(reply: SemanticFrame):
        monkeypatch.setattr(router_module.SemanticGateway, "parse", staticmethod(lambda request: reply))
        monkeypatch.setattr(engine_module, "semantic_model_configured", lambda: True)

    return install


# --------------------------------------------------------------- router units

def test_without_a_model_routing_is_the_deterministic_result():
    decision = SemanticRouter.route(
        "帮我交水费", TaskType.BILL_PAYMENT, elder_id="elder-demo", permit_remote_model=False
    )
    assert decision.task_type == TaskType.BILL_PAYMENT
    assert decision.model_used is False
    assert decision.basis == "keyword_only"
    assert decision.advisory_slots == {}


def test_gateway_offline_fallback_does_not_change_routing(monkeypatch):
    monkeypatch.setattr(
        router_module.SemanticGateway, "parse", staticmethod(lambda request: frame("bill_payment", model_used=False))
    )
    decision = SemanticRouter.route(
        "帮我挂号", TaskType.HOSPITAL_REGISTRATION, elder_id="elder-demo", permit_remote_model=True
    )
    assert decision.task_type == TaskType.HOSPITAL_REGISTRATION
    assert decision.model_used is False
    assert decision.basis == "keyword_only"


def test_model_adds_coverage_the_keywords_missed(monkeypatch):
    monkeypatch.setattr(
        router_module.SemanticGateway,
        "parse",
        staticmethod(lambda request: frame("bill_payment", slots={"bill_type": "水费"})),
    )
    decision = SemanticRouter.route(
        "这个月那张单子我还没弄", None, elder_id="elder-demo", permit_remote_model=True
    )
    assert decision.task_type == TaskType.BILL_PAYMENT
    assert decision.basis == "model_only"
    assert decision.advisory_slots == {"bill_type": "水费"}


def test_disagreement_clarifies_instead_of_picking_one(monkeypatch):
    monkeypatch.setattr(router_module.SemanticGateway, "parse", staticmethod(lambda request: frame("bill_payment")))
    decision = SemanticRouter.route(
        "去医院那个费用", TaskType.HOSPITAL_REGISTRATION, elder_id="elder-demo", permit_remote_model=True
    )
    assert decision.task_type is None
    assert decision.basis == "conflict"
    assert decision.needs_clarification is True
    assert "挂号" in decision.conflict_prompt and "缴费" in decision.conflict_prompt


def test_model_cannot_drop_a_task_the_keywords_found(monkeypatch):
    """A companion reading must not silently cancel a detected errand."""
    monkeypatch.setattr(router_module.SemanticGateway, "parse", staticmethod(lambda request: frame("companion")))
    decision = SemanticRouter.route(
        "帮我交水费", TaskType.BILL_PAYMENT, elder_id="elder-demo", permit_remote_model=True
    )
    assert decision.task_type == TaskType.BILL_PAYMENT
    assert decision.basis == "keyword_floor"
    assert decision.advisory_slots == {}


def test_agreement_carries_advisory_slots(monkeypatch):
    monkeypatch.setattr(
        router_module.SemanticGateway,
        "parse",
        staticmethod(
            lambda request: frame(
                "hospital_registration", slots={"hospital": "人民医院", "department": "心内科", "time": "上午9点"}
            )
        ),
    )
    decision = SemanticRouter.route(
        "帮我挂号", TaskType.HOSPITAL_REGISTRATION, elder_id="elder-demo", permit_remote_model=True
    )
    assert decision.basis == "agreement"
    assert decision.advisory_slots == {
        "hospital": "人民医院", "department": "心内科", "appointment_time": "上午9点"
    }


def test_payable_amount_can_never_come_from_the_model(monkeypatch):
    monkeypatch.setattr(
        router_module.SemanticGateway,
        "parse",
        staticmethod(lambda request: frame("bill_payment", slots={"amount_cents": 999999, "period": "2099-01"})),
    )
    decision = SemanticRouter.route("交水费", None, elder_id="elder-demo", permit_remote_model=True)
    assert decision.task_type == TaskType.BILL_PAYMENT
    assert decision.advisory_slots == {}


def test_advisory_slots_never_overwrite_deterministic_extraction():
    slots = {"hospital": "第一医院"}
    filled = apply_advisory_slots(slots, {"hospital": "人民医院", "department": "骨科"})
    assert slots["hospital"] == "第一医院"
    assert slots["department"] == "骨科"
    assert filled == ["department"]


# --------------------------------------------------------------- engine wiring

def test_conflict_reaches_the_elder_as_a_question(env, stub_model):
    db, engine, elder, family, session = env
    stub_model(frame("bill_payment"))
    response = engine.handle(
        elder, ChatRequest(session_id=session.session_id, text="去医院那个费用", request_id="conflict-1")
    )
    assert response.code.value == "need_more_info"
    assert "挂号" in response.message and "缴费" in response.message
    assert db.get_session(session.session_id).active_task_id is None


def test_model_only_task_still_walks_the_full_confirmation_chain(env, stub_model):
    db, engine, elder, family, session = env
    stub_model(frame("bill_payment", slots={"bill_type": "水费"}))
    response = engine.handle(
        elder, ChatRequest(session_id=session.session_id, text="这个月那张单子还没弄", request_id="model-1")
    )
    assert response.task_id is not None
    task = db.get_task(response.task_id)
    assert task.task_type == TaskType.BILL_PAYMENT
    # The model opened the task but did not skip confirmation.
    assert task.status.value in {"collecting", "awaiting_elder_confirmation"}
    assert response.code.value != "task_completed"


def test_model_supplied_fields_are_recorded_as_advisory(env, stub_model):
    db, engine, elder, family, session = env
    stub_model(frame("hospital_registration", slots={"hospital": "人民医院"}))
    response = engine.handle(
        elder, ChatRequest(session_id=session.session_id, text="我想找个大夫看看", request_id="model-2")
    )
    task = db.get_task(response.task_id)
    assert task.slots["hospital"] == "人民医院"
    assert task.slots["advisory_fields"] == ["hospital"]


def test_routing_decision_is_audited(env, stub_model):
    db, engine, elder, family, session = env
    stub_model(frame("bill_payment", slots={"bill_type": "水费"}))
    engine.handle(
        elder, ChatRequest(session_id=session.session_id, text="那张单子还没弄", request_id="model-3")
    )
    events = [e for e in db.list_audit("fam-demo", limit=100) if e.event_type == "SEMANTIC_ROUTED"]
    assert events, "a model-advised turn must leave an audit record"
    payload = events[-1].payload
    assert payload["basis"] == "model_only"
    assert payload["model_used"] is True
    assert payload["parser_source"] == "remote_model_validated"


def test_glass_box_marks_model_supplied_hospital_as_unverified(env, stub_model):
    from youhuo.v6_services import TaskGlassBoxService

    db, engine, elder, family, session = env
    stub_model(frame("hospital_registration", slots={"hospital": "人民医院"}))
    response = engine.handle(
        elder, ChatRequest(session_id=session.session_id, text="我想找个大夫看看", request_id="model-4")
    )
    task = db.get_task(response.task_id)
    box = TaskGlassBoxService.build(task, "我想找个大夫看看", family_approvals=0)
    hospital_source = box.card.data_sources[0]
    assert hospital_source["trusted"] is False
    assert hospital_source["verified"] is False
    assert "待核验" in hospital_source["source"]
    assert box.card.warning is not None
