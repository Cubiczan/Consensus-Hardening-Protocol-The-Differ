"""Tests for the canonical CHP core modules."""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from cme.chp import (  # noqa: E402
    CHPReport,
    CHPOrchestrator,
    ContextCheck,
    DecisionCase,
    DecisionRegistry,
    Dossier,
    FoundationAttack,
    FoundationDisclosure,
    ModelParityCheck,
    Phase,
    RoundRecord,
    SessionStatus,
    ThirdPartyValidation,
    ValidationResult,
    Verdict,
    assess_model_parity,
    apply_third_party_validation,
    build_payload_envelope,
    evaluate_phase_gate,
    evaluate_r0_gate,
    extract_payload_id,
    payload_echo_confirmed,
    validate_payload_envelope,
)
from cme.chp.devil import merge_structural_vulnerabilities  # noqa: E402
from cme.chp.foundation import foundation_verdict, validate_foundation_pair  # noqa: E402
from cme.chp.rounds import next_round  # noqa: E402


# --- Payload tests ---

def test_payload_envelope_roundtrip():
    envelope = build_payload_envelope("hello world", route="RX", payload_id="ABC123")
    rendered = envelope.render()
    assert validate_payload_envelope(rendered)
    assert payload_echo_confirmed("RX", "ABC123", "[RX] [ABC123] CONFIRMED")


def test_payload_invalid():
    assert not validate_payload_envelope("not a payload")
    assert not validate_payload_envelope("BEGIN_PAYLOAD only")


def test_extract_payload_id():
    envelope = build_payload_envelope("body", route="TX", payload_id="XYZ789")
    rendered = envelope.render()
    assert extract_payload_id(rendered) == "XYZ789"
    assert extract_payload_id("invalid") is None


# --- Model parity tests ---

def test_model_parity_none():
    parity = assess_model_parity("gpt-5.4", "claude-4-sonnet")
    assert parity.delta == "NONE"
    assert parity.advisory is None


def test_model_parity_minor():
    parity = assess_model_parity("gpt-5.4", "gpt-4o")
    assert parity.delta == "MINOR"
    assert parity.advisory is not None


def test_model_parity_significant():
    parity = assess_model_parity("gpt-5.5", "haiku")
    assert parity.delta == "SIGNIFICANT"


def test_model_parity_unknown():
    parity = assess_model_parity("unknown-model", "another-unknown")
    assert parity.delta == "MINOR"
    assert parity.advisory is not None


# --- Gate tests ---

def test_r0_gate_all_pass():
    gate = evaluate_r0_gate(solvable=True, scoped=True, valid=True, worth_it=True)
    assert gate.verdict == Verdict.PASS
    assert all(v == "PASS" for v in gate.results.values())


def test_r0_gate_halt_on_fatal():
    gate = evaluate_r0_gate(solvable=True, scoped=False, valid=True, worth_it=True)
    assert gate.verdict == Verdict.HALT
    assert gate.results["Scoped"] == "FATAL"


def test_phase_gate_pass_early():
    assert evaluate_phase_gate(1, SessionStatus.EXPLORING) == Verdict.PASS
    assert evaluate_phase_gate(2, SessionStatus.EXPLORING) == Verdict.PASS


def test_phase_gate_pass_locked():
    assert evaluate_phase_gate(3, SessionStatus.LOCKED) == Verdict.PASS


def test_phase_gate_fail():
    assert evaluate_phase_gate(3, SessionStatus.EXPLORING) == Verdict.PHASE_GATE_FAIL


# --- Foundation tests ---

def test_foundation_verdict_pass():
    attack = FoundationAttack(
        assumption_attacks=["attack1"],
        vulnerability_strike="strike",
        foundation_score=80,
        attack_summary="ok",
    )
    assert foundation_verdict(attack) == Verdict.PASS


def test_foundation_verdict_reframe():
    attack = FoundationAttack(
        assumption_attacks=["attack1"],
        vulnerability_strike="strike",
        foundation_score=50,
        attack_summary="low",
    )
    assert foundation_verdict(attack) == Verdict.REFRAME


def test_validate_foundation_pair():
    disclosure = FoundationDisclosure(
        weakest_assumptions=["assumption1"],
        invalidation_conditions=["condition1"],
        key_vulnerability="vuln",
    )
    attack = FoundationAttack(
        assumption_attacks=["attack1"],
        vulnerability_strike="strike",
        foundation_score=80,
    )
    assert validate_foundation_pair(disclosure, attack) == []


def test_validate_foundation_pair_errors():
    disclosure = FoundationDisclosure()
    attack = FoundationAttack()
    errors = validate_foundation_pair(disclosure, attack)
    assert len(errors) > 0


# --- Devil's advocate tests ---

def test_merge_structural_vulnerabilities():
    existing = ["vuln1", "vuln2"]
    new_items = ["vuln2", "vuln3"]
    result = merge_structural_vulnerabilities(existing, new_items)
    assert result == ["vuln1", "vuln2", "vuln3"]


def test_merge_empty():
    assert merge_structural_vulnerabilities([], []) == []


# --- Round progression tests ---

def test_next_round_foundation_to_spec():
    phase, rnd = next_round(Phase.FOUNDATION, 0)
    assert phase == Phase.SPEC
    assert rnd == 1


def test_next_round_spec_to_implementation():
    phase, rnd = next_round(Phase.SPEC, 2)
    assert phase == Phase.IMPLEMENTATION
    assert rnd == 3


def test_next_round_spec_continues():
    phase, rnd = next_round(Phase.SPEC, 1)
    assert phase == Phase.SPEC
    assert rnd == 2


# --- Registry tests ---

def test_registry_add_get():
    registry = DecisionRegistry()
    case = DecisionCase(
        decision_id="dec-1",
        title="Test",
        domain="finance",
        created_at="2026-01-01",
        owner="cfo",
    )
    registry.add(case)
    assert registry.get("dec-1") is case
    assert registry.get("nonexistent") is None


def test_registry_find_related():
    registry = DecisionRegistry()
    case1 = DecisionCase(decision_id="d1", title="Fund enterprise tier", domain="finance", created_at="2026-01-01", owner="cfo")
    case2 = DecisionCase(decision_id="d2", title="Hire engineer", domain="engineering", created_at="2026-01-01", owner="cto")
    registry.add(case1)
    registry.add(case2)
    related = registry.find_related("enterprise")
    assert len(related) == 1
    assert related[0].decision_id == "d1"


def test_registry_persistence(tmp_path):
    registry = DecisionRegistry()
    case = DecisionCase(
        decision_id="d-persist",
        title="Persist test",
        domain="test",
        created_at="2026-01-01",
        owner="test",
        dossier=Dossier(core_problem="test problem", goal_state=["goal"]),
    )
    registry.add(case)
    path = tmp_path / "registry.json"
    registry.save(path)
    loaded = DecisionRegistry.load(path)
    assert loaded.get("d-persist") is not None
    assert loaded.get("d-persist").title == "Persist test"


# --- Validator tests ---

def test_third_party_confirm():
    case = DecisionCase(
        decision_id="dec-1",
        title="Test",
        domain="finance",
        created_at="2026-01-01",
        owner="cfo",
        status=SessionStatus.PROVISIONAL_LOCK,
    )
    validation = ThirdPartyValidation(
        validator="fresh_instance",
        item="Spec v1",
        challenge="downside stress",
        result=ValidationResult.CONFIRM,
        rationale="holds up",
    )
    status = apply_third_party_validation(case, validation)
    assert status == SessionStatus.LOCKED
    assert "Spec v1" in case.locked_decisions


def test_third_party_reject():
    case = DecisionCase(
        decision_id="dec-1",
        title="Test",
        domain="finance",
        created_at="2026-01-01",
        owner="cfo",
    )
    validation = ThirdPartyValidation(
        validator="reviewer",
        item="Spec v1",
        challenge="gap found",
        result=ValidationResult.REJECT,
        rationale="missing analysis",
    )
    status = apply_third_party_validation(case, validation)
    assert status == SessionStatus.EXPLORING
    assert any("Spec v1" in f for f in case.flip_criteria)


# --- Orchestrator tests ---

def test_orchestrator_initial_session():
    registry = DecisionRegistry()
    orch = CHPOrchestrator(registry=registry)
    case = DecisionCase(
        decision_id="cap-1",
        title="Fund enterprise tier",
        domain="capital_allocation",
        created_at="2026-01-01T10:00:00Z",
        owner="cfo",
        high_stakes=True,
        dossier=Dossier(
            core_problem="Should we fund the tier?",
            goal_state=["grow"],
            current_state=["cash"],
            constraints=["runway"],
            scope=["decision"],
        ),
    )
    disclosure = FoundationDisclosure(
        weakest_assumptions=["Market growth continues"],
        invalidation_conditions=["Recession hits"],
        key_vulnerability="Revenue concentration",
    )
    attack = FoundationAttack(
        assumption_attacks=["Market may contract"],
        invalidation_exploitation=["Recession risk"],
        vulnerability_strike="Single customer dependency",
        foundation_score=85,
        attack_summary="Moderate risk accepted",
    )
    report = orch.run_initial_session(case=case, foundation_disclosure=disclosure, foundation_attack=attack)
    assert isinstance(report, CHPReport)
    assert report.case.context_check is not None
    assert report.case.model_parity is not None
    assert report.case.foundation_score == 85
    assert "BEGIN_PAYLOAD" in report.initial_packet
    assert report.case.status.value in {"EXPLORING", "REFRAME_REQUIRED", "HALT"}


def test_orchestrator_receive_packet():
    registry = DecisionRegistry()
    orch = CHPOrchestrator(registry=registry)
    case = DecisionCase(
        decision_id="dec-1",
        title="Test",
        domain="finance",
        created_at="2026-01-01T10:00:00Z",
        owner="cfo",
        dossier=Dossier(core_problem="test", goal_state=["g"], current_state=["c"], constraints=["k"], scope=["s"]),
    )
    disclosure = FoundationDisclosure(weakest_assumptions=["a"], invalidation_conditions=["c"], key_vulnerability="v")
    attack = FoundationAttack(assumption_attacks=["a"], vulnerability_strike="s", foundation_score=75)
    orch.run_initial_session(case=case, foundation_disclosure=disclosure, foundation_attack=attack)

    packet = "BEGIN_PAYLOAD [RX] [ABC123]\npartner body\nEND_PAYLOAD [RX] [ABC123]"
    updated = orch.receive_partner_packet(
        decision_id="dec-1",
        partner_packet=packet,
        phase=Phase.SPEC,
        round_number=1,
        payload_echo="[RX] [ABC123] CONFIRMED",
        snapshot_status="PROVISIONAL_LOCK",
    )
    assert updated.current_round == 1
    assert updated.current_phase == Phase.SPEC


def test_orchestrator_full_lifecycle():
    registry = DecisionRegistry()
    orch = CHPOrchestrator(registry=registry)
    case = DecisionCase(
        decision_id="dec-2",
        title="Investment decision",
        domain="capital_allocation",
        created_at="2026-01-01T10:00:00Z",
        owner="cfo",
        high_stakes=True,
        dossier=Dossier(core_problem="Invest?", goal_state=["g"], current_state=["c"], constraints=["k"], scope=["s"]),
    )
    disclosure = FoundationDisclosure(weakest_assumptions=["a1"], invalidation_conditions=["c1"], key_vulnerability="v1")
    attack = FoundationAttack(assumption_attacks=["a1"], vulnerability_strike="s", foundation_score=80)
    report = orch.run_initial_session(case=case, foundation_disclosure=disclosure, foundation_attack=attack)

    packet = "BEGIN_PAYLOAD [RX] [DEF456]\nbody\nEND_PAYLOAD [RX] [DEF456]"
    orch.receive_partner_packet(
        decision_id="dec-2",
        partner_packet=packet,
        phase=Phase.SPEC,
        round_number=1,
        snapshot_status="PROVISIONAL_LOCK",
    )

    final = orch.apply_validation(
        "dec-2",
        ThirdPartyValidation(
            validator="fresh_instance",
            item="Spec v1",
            challenge="stress test",
            result=ValidationResult.CONFIRM,
            rationale="coherent",
        ),
    )
    assert final.status == SessionStatus.LOCKED


# --- Model serialization tests ---

def test_decision_case_roundtrip():
    case = DecisionCase(
        decision_id="d-rt",
        title="Roundtrip test",
        domain="finance",
        created_at="2026-01-01",
        owner="cfo",
        dossier=Dossier(core_problem="test", goal_state=["g"]),
    )
    data = case.to_dict()
    restored = DecisionCase.from_dict(data)
    assert restored.decision_id == case.decision_id
    assert restored.title == case.title
    assert restored.dossier is not None
    assert restored.dossier.core_problem == "test"


def test_round_record_roundtrip():
    record = RoundRecord(
        decision_id="d1",
        phase=Phase.SPEC,
        round_number=2,
        payload_id="P123",
    )
    data = record.to_dict()
    restored = RoundRecord.from_dict(data)
    assert restored.decision_id == "d1"
    assert restored.phase == Phase.SPEC
    assert restored.round_number == 2


# --- Protocol tests ---

def test_protocol_expansion_compression():
    from cme.protocol import CognitiveMeshProtocol, CompressionStep, ConfidenceLevel, ExpansionStep

    proto = CognitiveMeshProtocol()

    def _expand(p, ctx):
        return [
            ExpansionStep(label="Reframe", content="x"),
            ExpansionStep(label="Constraints", content="y"),
        ]

    def _compress(p, exp, ctx):
        return (
            "final recommendation",
            [CompressionStep(label="Integrate", content="z")],
            ConfidenceLevel.HIGH,
            "nothing changes unless Q1 slips",
        )

    trace = proto.run("plan the quarter", expansion_fn=_expand, compression_fn=_compress)
    assert trace.recommendation == "final recommendation"
    assert trace.confidence == ConfidenceLevel.HIGH
    assert "Problem Classification" in trace.render()


def test_hallucination_detection():
    from cme.protocol import detect_hallucination_risk
    assert detect_hallucination_risk("studies show 42% of users prefer X") is not None
    assert detect_hallucination_risk("The team shipped the feature on Tuesday.") is None
