#!/usr/bin/env python3
"""Generate the CHP golden vectors from the reference implementation.

    python3 spec/conformance/generate_vectors.py

Every expected value in spec/golden-vectors/ is produced by chp_reference.py —
none are hand-written, so the vectors cannot drift from the reference.
Re-run after any intentional reference change, and review the diff.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from chp_reference import (  # noqa: E402
    CHP_VERSION,
    GatePolicy,
    Phase,
    ProposedAction,
    State,
    accuracy_guard,
    approve_human,
    assess_model_parity,
    chain_hash,
    canonical_json,
    content_hash,
    evaluate_gate,
    evaluate_phase_gate,
    evaluate_r0_gate,
    foundation_floor,
    foundation_verdict,
    next_round,
    payload_echo_confirmed,
    render_payload_envelope,
    validate_payload_envelope,
)

OUT = Path(__file__).resolve().parent.parent / "golden-vectors"


def canon_vectors() -> dict:
    cases = [
        {"name": "key-order-independence-a", "input": {"b": 1, "a": 2}},
        {"name": "key-order-independence-b", "input": {"a": 2, "b": 1}},
        {"name": "nested-sorting", "input": {"z": {"y": 1, "x": [3, 2, 1]}, "a": None}},
        {"name": "unicode-preserved", "input": {"note": "café ✓", "n": 1}},
        {"name": "float-and-bool", "input": {"f": 0.55, "t": True, "n": None}},
        {"name": "empty-object", "input": {}},
    ]
    return {
        "spec": f"CHP v{CHP_VERSION} §3.1–3.2",
        "note": (
            "key-order-independence-a and -b MUST produce identical canonical "
            "form and hash. This is the property that makes cross-language "
            "verification possible."
        ),
        "vectors": [
            {**c, "canonical": canonical_json(c["input"]), "sha256": content_hash(c["input"])}
            for c in cases
        ],
    }


def ledger_vectors() -> dict:
    entries = [
        {"seq": 1, "event": "decision.locked", "decision_id": "d-001"},
        {"seq": 2, "event": "decision.locked", "decision_id": "d-002"},
        {"seq": 3, "event": "decision.blocked", "decision_id": "d-003"},
    ]
    chain, prev = [], ""
    for e in entries:
        sig = chain_hash(prev, e)
        chain.append({"entry": e, "prev_sig": prev, "sig": sig})
        prev = sig
    return {
        "spec": f"CHP v{CHP_VERSION} §3.3",
        "note": (
            "Removing or editing any entry MUST break every subsequent sig. "
            "Verifiers recompute the whole chain from prev_sig=''."
        ),
        "chain": chain,
        "final_sig": prev,
    }


def profile_a_vectors() -> dict:
    r0 = [
        {"name": "all-pass", "input": {"solvable": True, "scoped": True, "valid": True, "worth_it": True}},
        {"name": "unscoped-halts", "input": {"solvable": True, "scoped": False, "valid": True, "worth_it": True}},
        {"name": "not-worth-it-halts", "input": {"solvable": True, "scoped": True, "valid": True, "worth_it": False}},
        {"name": "all-fail", "input": {"solvable": False, "scoped": False, "valid": False, "worth_it": False}},
    ]
    floors = [
        {"domain": d, "floor": foundation_floor(d)}
        for d in ("general", "ai", "blockchain", "defi", "finance", "cfo", "capital_allocation", "totally-unknown", "")
    ]
    fverdict = [
        {"name": "general-70-passes", "score": 70, "domain": "general"},
        {"name": "general-69-reframes", "score": 69, "domain": "general"},
        {"name": "blockchain-84-reframes", "score": 84, "domain": "blockchain"},
        {"name": "blockchain-85-passes", "score": 85, "domain": "blockchain"},
        {"name": "finance-99-reframes", "score": 99, "domain": "finance"},
        {"name": "finance-100-passes", "score": 100, "domain": "finance"},
        {"name": "finance-70-reframes-regression", "score": 70, "domain": "finance"},
    ]
    phase = [
        {"name": "early-round-always-passes", "round": 1, "state": State.EXPLORING.value},
        {"name": "round-3-unlocked-fails", "round": 3, "state": State.EXPLORING.value},
        {"name": "round-3-provisional-lock-passes", "round": 3, "state": State.PROVISIONAL_LOCK.value},
        {"name": "round-3-locked-passes", "round": 3, "state": State.LOCKED.value},
    ]
    progression = [
        {"name": "foundation-to-spec", "phase": Phase.FOUNDATION.value, "round": 0},
        {"name": "spec-round-1-iterates", "phase": Phase.SPEC.value, "round": 1},
        {"name": "spec-round-2-to-implementation", "phase": Phase.SPEC.value, "round": 2},
        {"name": "implementation-iterates", "phase": Phase.IMPLEMENTATION.value, "round": 3},
    ]
    parity = [
        {"name": "identical-tier", "origin": "claude-opus-4", "partner": "claude-opus-4"},
        {"name": "adjacent-tier", "origin": "claude-sonnet-4", "partner": "gpt-5"},
        {"name": "significant-gap", "origin": "claude-opus-4", "partner": "claude-haiku-4-5"},
        {"name": "unknown-partner", "origin": "claude-opus-4", "partner": "some-local-llm"},
    ]
    guard = [
        {"name": "clean-finance-lock", "foundation_score": 100, "domain": "finance",
         "state": State.LOCKED.value, "structural_vulnerabilities": [], "blind_spots": []},
        {"name": "finance-below-floor", "foundation_score": 85, "domain": "finance",
         "state": State.PROVISIONAL.value, "structural_vulnerabilities": [], "blind_spots": []},
        {"name": "locked-with-open-vulnerability", "foundation_score": 100, "domain": "finance",
         "state": State.LOCKED.value, "structural_vulnerabilities": ["oracle can be stale"], "blind_spots": []},
        {"name": "general-clean", "foundation_score": 70, "domain": "general",
         "state": State.PROVISIONAL.value, "structural_vulnerabilities": [], "blind_spots": []},
    ]
    env_id, env_route = "AB12CD", "RX"
    envelope = render_payload_envelope("CORE_PROBLEM: example", route=env_route, payload_id=env_id)
    return {
        "spec": f"CHP v{CHP_VERSION} §5",
        "r0_gate": [{**c, "expected": evaluate_r0_gate(**c["input"])} for c in r0],
        "foundation_floors": floors,
        "foundation_verdict": [
            {**c, "expected": foundation_verdict(c["score"], c["domain"])} for c in fverdict
        ],
        "phase_gate": [
            {**c, "expected": evaluate_phase_gate(c["round"], State(c["state"]))} for c in phase
        ],
        "round_progression": [
            {**c, "expected": {"phase": next_round(Phase(c["phase"]), c["round"])[0].value,
                               "round": next_round(Phase(c["phase"]), c["round"])[1]}}
            for c in progression
        ],
        "model_parity": [
            {**c, "expected": assess_model_parity(c["origin"], c["partner"])} for c in parity
        ],
        "accuracy_guard": [
            {**c, "expected": accuracy_guard(
                foundation_score=c["foundation_score"], domain=c["domain"], state=State(c["state"]),
                structural_vulnerabilities=c["structural_vulnerabilities"], blind_spots=c["blind_spots"])}
            for c in guard
        ],
        "payload_envelope": {
            "route": env_route,
            "payload_id": env_id,
            "rendered": envelope,
            "valid": validate_payload_envelope(envelope),
            "tampered_footer_valid": validate_payload_envelope(
                envelope.replace(f"END_PAYLOAD [{env_route}] [{env_id}]", "END_PAYLOAD [RX] [ZZZZZZ]")),
            "echo_confirmed": payload_echo_confirmed(env_route, env_id, f"[{env_route}] [{env_id}] CONFIRMED"),
            "echo_wrong_id": payload_echo_confirmed(env_route, env_id, "[RX] [ZZZZZZ] CONFIRMED"),
        },
    }


def profile_b_vectors() -> dict:
    policy = GatePolicy(
        version="test-1",
        max_notional=500.0,
        daily_cap=2500.0,
        hitl_threshold=250.0,
        min_confidence=0.55,
        allowed_actions=("LONG", "SHORT"),
        per_asset_limits={"CAKE": 100.0},
    )
    cases = [
        {"name": "clean-auto-lock",
         "action": {"action": "LONG", "asset": "ETH", "notional": 100.0, "confidence": 0.8}, "committed_today": 0.0},
        {"name": "at-hitl-threshold-requires-human",
         "action": {"action": "LONG", "asset": "ETH", "notional": 250.0, "confidence": 0.9}, "committed_today": 0.0},
        {"name": "just-below-threshold-locks",
         "action": {"action": "LONG", "asset": "ETH", "notional": 249.99, "confidence": 0.9}, "committed_today": 0.0},
        {"name": "over-max-notional-blocked",
         "action": {"action": "LONG", "asset": "ETH", "notional": 501.0, "confidence": 0.9}, "committed_today": 0.0},
        {"name": "per-asset-cap-beats-global",
         "action": {"action": "LONG", "asset": "CAKE", "notional": 150.0, "confidence": 0.9}, "committed_today": 0.0},
        {"name": "daily-cap-exhausted",
         "action": {"action": "LONG", "asset": "ETH", "notional": 100.0, "confidence": 0.9}, "committed_today": 2450.0},
        {"name": "low-confidence-blocked",
         "action": {"action": "LONG", "asset": "ETH", "notional": 100.0, "confidence": 0.10}, "committed_today": 0.0},
        {"name": "disallowed-action-blocked",
         "action": {"action": "HOLD", "asset": "ETH", "notional": 100.0, "confidence": 0.9}, "committed_today": 0.0},
        {"name": "zero-notional-blocked",
         "action": {"action": "LONG", "asset": "ETH", "notional": 0.0, "confidence": 0.9}, "committed_today": 0.0},
        {"name": "negative-notional-blocked",
         "action": {"action": "LONG", "asset": "ETH", "notional": -50.0, "confidence": 0.9}, "committed_today": 0.0},
        {"name": "no-confidence-supplied-skips-check",
         "action": {"action": "LONG", "asset": "ETH", "notional": 100.0, "confidence": None}, "committed_today": 0.0},
    ]
    evaluated = [
        {**c, "expected": evaluate_gate(ProposedAction(**c["action"]), policy,
                                        committed_today=c["committed_today"])}
        for c in cases
    ]

    approvals = [
        {"name": "approve-hitl-action-locks",
         "action": {"action": "LONG", "asset": "ETH", "notional": 300.0, "confidence": 0.9},
         "committed_today": 0.0, "approver": "cfo@example.com"},
        {"name": "approval-cannot-bypass-max-notional",
         "action": {"action": "LONG", "asset": "ETH", "notional": 900.0, "confidence": 0.9},
         "committed_today": 0.0, "approver": "cfo@example.com"},
        {"name": "approval-cannot-bypass-low-confidence",
         "action": {"action": "LONG", "asset": "ETH", "notional": 300.0, "confidence": 0.1},
         "committed_today": 0.0, "approver": "cfo@example.com"},
        {"name": "approval-cannot-bypass-daily-cap",
         "action": {"action": "LONG", "asset": "ETH", "notional": 300.0, "confidence": 0.9},
         "committed_today": 2400.0, "approver": "cfo@example.com"},
    ]
    approved = [
        {**c, "expected": approve_human(ProposedAction(**c["action"]), policy,
                                        approver=c["approver"], committed_today=c["committed_today"])}
        for c in approvals
    ]

    return {
        "spec": f"CHP v{CHP_VERSION} §6",
        "policy": {
            "version": policy.version,
            "max_notional": policy.max_notional,
            "daily_cap": policy.daily_cap,
            "hitl_threshold": policy.hitl_threshold,
            "min_confidence": policy.min_confidence,
            "allowed_actions": list(policy.allowed_actions),
            "per_asset_limits": dict(policy.per_asset_limits),
        },
        "notes": [
            "HITL threshold is inclusive (>=): notional == threshold requires a human.",
            "Hard-rule violations outrank the HITL test: an over-cap action is BLOCKED, never sent for approval.",
            "committed_delta is what the caller adds to the daily total; BLOCKED and HITL_REQUIRED contribute 0.",
            "Daily window is the UTC calendar day, not a rolling window from process start.",
        ],
        "evaluate": evaluated,
        "approve_human": approved,
    }


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    written = {
        "canonicalization.json": canon_vectors(),
        "audit-ledger.json": ledger_vectors(),
        "profile-a-deliberation.json": profile_a_vectors(),
        "profile-b-capital-gate.json": profile_b_vectors(),
    }
    for name, payload in written.items():
        path = OUT / name
        path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        print(f"wrote {path.relative_to(OUT.parent.parent)}")


if __name__ == "__main__":
    main()
