"""CHP v1.0 reference implementation — normative behaviour for both profiles.

This module is the tie-breaker. Where a port disagrees with this file, the port
is wrong (or the spec needs an errata). It is deliberately dependency-free and
side-effect-free so it can be vendored anywhere and diffed easily.

Profile A — Deliberation: multi-round adversarial decision hardening.
Profile B — Capital Gate: runtime gate on capital-moving actions.

The two profiles share a state vocabulary but are different protocols. See
../CHP-v1.0.md §2.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Iterable, Mapping, Sequence

CHP_VERSION = "1.0"

# --------------------------------------------------------------------------
# §3 Canonical serialisation
# --------------------------------------------------------------------------


def canonical_json(payload: Mapping[str, Any]) -> str:
    """Serialise a mapping to CHP canonical JSON (spec §3.1).

    Sorted keys, no insignificant whitespace, UTF-8, no NaN/Infinity. Two
    implementations that agree on the field set MUST produce byte-identical
    output — this is what makes cross-language hash comparison possible.
    """
    return json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    )


def content_hash(payload: Mapping[str, Any]) -> str:
    """SHA-256 hex digest over canonical JSON (spec §3.2)."""
    return hashlib.sha256(canonical_json(payload).encode("utf-8")).hexdigest()


def chain_hash(prev_sig: str, entry: Mapping[str, Any]) -> str:
    """Hash-chain link for the signed audit ledger (spec §3.3).

    prev_sig for the first entry is the empty string. Chaining the previous
    signature into the digest is what makes deletion of a middle entry
    detectable.
    """
    return content_hash({"prev_sig": prev_sig, "entry": entry})


# --------------------------------------------------------------------------
# §4 Shared state vocabulary
# --------------------------------------------------------------------------


class State(str, Enum):
    """Canonical CHP states. Wire form is UPPERCASE (spec §4.1)."""

    EXPLORING = "EXPLORING"
    PROVISIONAL = "PROVISIONAL"
    PROVISIONAL_LOCK = "PROVISIONAL_LOCK"
    LOCKED = "LOCKED"
    CONVERGED = "CONVERGED"
    UNRESOLVED = "UNRESOLVED"
    REFRAME_REQUIRED = "REFRAME_REQUIRED"
    REQUIRES_HUMAN_VERIFICATION = "REQUIRES_HUMAN_VERIFICATION"
    HITL_REQUIRED = "HITL_REQUIRED"
    BLOCKED = "BLOCKED"
    HALT = "HALT"


PROFILE_A_STATES = frozenset({
    State.EXPLORING, State.PROVISIONAL, State.PROVISIONAL_LOCK, State.LOCKED,
    State.CONVERGED, State.UNRESOLVED, State.REFRAME_REQUIRED,
    State.REQUIRES_HUMAN_VERIFICATION, State.HALT,
})

PROFILE_B_STATES = frozenset({
    State.EXPLORING, State.PROVISIONAL, State.LOCKED,
    State.HITL_REQUIRED, State.BLOCKED,
})


class Verdict(str, Enum):
    PASS = "PASS"
    FAIL = "FAIL"
    HALT = "HALT"
    REFRAME = "REFRAME"
    ITERATE = "ITERATE"
    CONVERGED = "CONVERGED"
    PHASE_GATE_FAIL = "PHASE_GATE_FAIL"


# --------------------------------------------------------------------------
# §5 Profile A — Deliberation
# --------------------------------------------------------------------------


class Phase(int, Enum):
    FOUNDATION = 0
    SPEC = 1
    IMPLEMENTATION = 2


#: Domain foundation-score floors (spec §5.3). A domain absent from this map
#: uses DEFAULT_FOUNDATION_FLOOR.
FOUNDATION_FLOORS: Mapping[str, int] = {
    "general": 70,
    "ai": 70,
    "agents": 70,
    "blockchain": 85,
    "defi": 85,
    "finance": 100,
    "cfo": 100,
    "capital_allocation": 100,
    "board_decision": 100,
}
DEFAULT_FOUNDATION_FLOOR = 70


def foundation_floor(domain: str) -> int:
    """Resolve the foundation-score floor for a domain (spec §5.3).

    Case-insensitive. Unknown domains fall back to the general floor rather
    than failing open at 0 or closed at 100.
    """
    return FOUNDATION_FLOORS.get((domain or "").strip().lower(), DEFAULT_FOUNDATION_FLOOR)


def evaluate_r0_gate(*, solvable: bool, scoped: bool, valid: bool, worth_it: bool) -> dict[str, Any]:
    """R0 session-entry gate (spec §5.2). All four checks MUST pass."""
    results = {
        "Solvable": "PASS" if solvable else "FATAL",
        "Scoped": "PASS" if scoped else "FATAL",
        "Valid": "PASS" if valid else "FATAL",
        "Worth_it": "PASS" if worth_it else "FATAL",
    }
    verdict = Verdict.PASS if all(v == "PASS" for v in results.values()) else Verdict.HALT
    return {"results": results, "verdict": verdict.value}


def foundation_verdict(foundation_score: int, domain: str = "general") -> str:
    """Domain-aware foundation gate (spec §5.3).

    NOTE: the canonical Python port hardcoded 70 for every domain, so the
    documented finance floor of 100 was never enforced. This function is the
    normative behaviour; see ../DIVERGENCES.md D-A1.
    """
    return Verdict.PASS.value if foundation_score >= foundation_floor(domain) else Verdict.REFRAME.value


def evaluate_phase_gate(round_number: int, phase_one_state: State) -> str:
    """Phase gate: cannot enter IMPLEMENTATION without a locked spec (spec §5.4)."""
    if round_number <= 2:
        return Verdict.PASS.value
    if phase_one_state in (State.PROVISIONAL_LOCK, State.LOCKED, State.CONVERGED):
        return Verdict.PASS.value
    return Verdict.PHASE_GATE_FAIL.value


def next_round(phase: Phase, round_number: int) -> tuple[Phase, int]:
    """Round/phase progression (spec §5.5)."""
    if phase == Phase.FOUNDATION:
        return Phase.SPEC, 1
    if phase == Phase.SPEC and round_number >= 2:
        return Phase.IMPLEMENTATION, 3
    return phase, round_number + 1


MAX_ROUNDS = 5


def force_unresolved(round_number: int) -> bool:
    """Rounds are bounded; no convergence by MAX_ROUNDS is UNRESOLVED (spec §5.6)."""
    return round_number >= MAX_ROUNDS


class ModelTier(str, Enum):
    SMALL = "small"
    MID = "mid"
    HIGH = "high"
    FRONTIER = "frontier"
    UNKNOWN = "unknown"


_TIER_ORDER = (ModelTier.SMALL, ModelTier.MID, ModelTier.HIGH, ModelTier.FRONTIER)

#: Longest-match-first so "claude-4-opus" resolves FRONTIER, not HIGH.
_TIER_TOKENS: Sequence[tuple[str, ModelTier]] = (
    ("opus", ModelTier.FRONTIER), ("frontier", ModelTier.FRONTIER), ("max", ModelTier.FRONTIER),
    ("gpt-5", ModelTier.HIGH), ("claude-4", ModelTier.HIGH), ("claude 4", ModelTier.HIGH),
    ("sonnet", ModelTier.MID), ("gpt-4", ModelTier.MID), ("4o", ModelTier.MID),
    ("haiku", ModelTier.SMALL), ("mini", ModelTier.SMALL), ("small", ModelTier.SMALL),
)


def infer_model_tier(model_name: str) -> ModelTier:
    name = (model_name or "").lower()
    for token, tier in _TIER_TOKENS:
        if token in name:
            return tier
    return ModelTier.UNKNOWN


def assess_model_parity(origin_model: str, partner_model: str) -> dict[str, Any]:
    """Adversary-weight parity check (spec §5.7).

    A SIGNIFICANT delta means the 'adversary' cannot meaningfully challenge the
    proposer, so the adversarial round provides false assurance.
    """
    o, p = infer_model_tier(origin_model), infer_model_tier(partner_model)
    if o == ModelTier.UNKNOWN or p == ModelTier.UNKNOWN:
        delta, advisory = "MINOR", "One or both model tiers are unknown. Treat parity as advisory only."
    else:
        gap = abs(_TIER_ORDER.index(o) - _TIER_ORDER.index(p))
        if gap == 0:
            delta, advisory = "NONE", None
        elif gap == 1:
            delta, advisory = "MINOR", "Slight analytical weight difference. Monitor for dominance bias."
        else:
            delta, advisory = "SIGNIFICANT", "Adversary materially weaker than proposer; challenge is not credible."
    return {"origin": origin_model, "partner": partner_model, "delta": delta, "advisory": advisory}


def accuracy_guard(
    *,
    foundation_score: int,
    domain: str,
    state: State,
    structural_vulnerabilities: Sequence[str] = (),
    blind_spots: Sequence[str] = (),
) -> dict[str, Any]:
    """Fail-closed guard before a clean lock (spec §5.8).

    A LOCKED state with open vulnerabilities is downgraded rather than trusted.
    """
    floor = foundation_floor(domain)
    issues: list[str] = []
    if foundation_score < floor:
        issues.append(f"foundation score {foundation_score} below floor {floor}")
    if structural_vulnerabilities:
        issues.append(f"{len(structural_vulnerabilities)} structural vulnerability(ies) remain open")
    if blind_spots:
        issues.append(f"{len(blind_spots)} blind spot(s) unresolved")
    if issues:
        return {
            "passes": False,
            "reason": "; ".join(issues),
            "required_action": State.REQUIRES_HUMAN_VERIFICATION.value,
        }
    return {"passes": True, "reason": "", "required_action": None}


# §5.9 Payload envelope


def render_payload_envelope(body: str, *, route: str, payload_id: str) -> str:
    return (
        f"BEGIN_PAYLOAD [{route}] [{payload_id}]\n"
        f"{body}\n"
        f"END_PAYLOAD [{route}] [{payload_id}]"
    )


def validate_payload_envelope(rendered: str) -> bool:
    lines = [ln.rstrip() for ln in (rendered or "").strip().splitlines()]
    if len(lines) < 3:
        return False
    first, last = lines[0], lines[-1]
    if not first.startswith("BEGIN_PAYLOAD [") or not last.startswith("END_PAYLOAD ["):
        return False
    return first.replace("BEGIN_PAYLOAD", "", 1).strip() == last.replace("END_PAYLOAD", "", 1).strip()


def payload_echo_confirmed(route: str, payload_id: str, echo: str) -> bool:
    return (echo or "").strip() == f"[{route}] [{payload_id}] CONFIRMED"


# --------------------------------------------------------------------------
# §6 Profile B — Capital Gate
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class GatePolicy:
    """Capital-gate policy (spec §6.2). Defaults are deliberately conservative:
    an unreadable or absent policy file MUST fall back to these, never to
    unlimited."""

    version: str = "1.0"
    max_notional: float = 500.0
    daily_cap: float = 2500.0
    hitl_threshold: float = 250.0
    min_confidence: float = 0.55
    allowed_actions: tuple[str, ...] = ()
    per_asset_limits: Mapping[str, float] = field(default_factory=dict)

    def cap_for(self, asset: str) -> float:
        return float(self.per_asset_limits.get(asset, self.max_notional))


@dataclass(frozen=True)
class ProposedAction:
    action: str
    asset: str
    notional: float
    confidence: float | None = None
    rationale: str = ""


@dataclass(frozen=True)
class Claim:
    rule: str
    passed: bool
    detail: str


def utc_day(ts: datetime | None = None) -> str:
    """Normative daily-cap window key (spec §6.4): the UTC calendar day.

    A rolling window anchored to process start is NOT conformant — it makes the
    budget depend on restart time, so the same action sequence can pass on one
    host and be blocked on another, and an auditor cannot reproduce either.
    """
    return (ts or datetime.now(timezone.utc)).astimezone(timezone.utc).strftime("%Y-%m-%d")


def evaluate_gate(
    action: ProposedAction,
    policy: GatePolicy,
    *,
    committed_today: float = 0.0,
) -> dict[str, Any]:
    """Evaluate a capital-moving action (spec §6.3).

    Ordering is normative: hard violations are collected FIRST and produce
    BLOCKED. Only a fully clean action reaches the HITL threshold test. An
    implementation that checks HITL before the hard rules can route an
    over-cap action to a human for approval, which invites a human to approve
    something the policy forbids.
    """
    claims: list[Claim] = []

    def add(rule: str, passed: bool, detail: str) -> bool:
        claims.append(Claim(rule, passed, detail))
        return passed

    ok = True
    # Sanity before limits: a NaN or negative notional makes every comparison meaningless.
    finite_positive = isinstance(action.notional, (int, float)) and \
        action.notional == action.notional and \
        action.notional not in (float("inf"), float("-inf")) and \
        action.notional > 0
    ok &= add("sane-notional", finite_positive, f"notional={action.notional}")

    if policy.allowed_actions:
        ok &= add("allowed-action", action.action in policy.allowed_actions, f"action {action.action}")

    cap = policy.cap_for(action.asset)
    ok &= add("per-asset-cap", action.notional <= cap,
              f"{action.asset} notional {action.notional} vs cap {cap}")
    ok &= add("max-notional", action.notional <= policy.max_notional,
              f"{action.notional} vs max {policy.max_notional}")

    projected = committed_today + (action.notional if finite_positive else 0.0)
    ok &= add("daily-cap", projected <= policy.daily_cap,
              f"projected {projected} vs daily cap {policy.daily_cap}")

    if action.confidence is not None:
        ok &= add("min-confidence", action.confidence >= policy.min_confidence,
                  f"confidence {action.confidence} vs min {policy.min_confidence}")

    if not ok:
        failed = [c.rule for c in claims if not c.passed]
        return _gate_result(action, State.BLOCKED, claims, allowed=False,
                            requires_human=False, reason=f"blocked: {', '.join(failed)}",
                            committed_delta=0.0)

    # Clean. Threshold test is inclusive: notional == threshold requires a human.
    if action.notional >= policy.hitl_threshold:
        return _gate_result(action, State.HITL_REQUIRED, claims, allowed=False,
                            requires_human=True,
                            reason=f"human approval required: {action.notional} >= HITL threshold {policy.hitl_threshold}",
                            committed_delta=0.0)

    return _gate_result(action, State.LOCKED, claims, allowed=True, requires_human=False,
                        reason="auto-approved under CHP thresholds",
                        committed_delta=action.notional)


def approve_human(
    action: ProposedAction,
    policy: GatePolicy,
    *,
    approver: str,
    committed_today: float = 0.0,
) -> dict[str, Any]:
    """Promote a HITL_REQUIRED action to LOCKED (spec §6.5).

    MUST re-run the full evaluation. A human approval is permission to cross the
    HITL threshold, NOT permission to violate the policy — so an approved action
    that fails any hard rule is BLOCKED, not locked.
    """
    recheck = evaluate_gate(action, policy, committed_today=committed_today)
    if recheck["state"] == State.BLOCKED.value:
        recheck["reason"] = f"approval by {approver} rejected: {recheck['reason']}"
        return recheck
    return _gate_result(action, State.LOCKED, [Claim("human-approval", True, f"approved by {approver}")],
                        allowed=True, requires_human=False,
                        reason=f"human-approved by {approver}",
                        committed_delta=action.notional)


def _gate_result(
    action: ProposedAction,
    state: State,
    claims: Iterable[Claim],
    *,
    allowed: bool,
    requires_human: bool,
    reason: str,
    committed_delta: float,
) -> dict[str, Any]:
    claim_list = [{"rule": c.rule, "passed": c.passed, "detail": c.detail} for c in claims]
    # Hashed field set is normative and excludes wall-clock time and the
    # decision id, so two implementations can compare hashes for the same
    # logical decision. Timestamp is recorded alongside, not inside.
    hashed = {
        "chp_version": CHP_VERSION,
        "profile": "B",
        "action": action.action,
        "asset": action.asset,
        "notional": action.notional,
        "confidence": action.confidence,
        "state": state.value,
        "allowed": allowed,
        "requires_human": requires_human,
        "failed_rules": sorted(c["rule"] for c in claim_list if not c["passed"]),
    }
    return {
        "state": state.value,
        "allowed": allowed,
        "requires_human": requires_human,
        "reason": reason,
        "claims": claim_list,
        "content_hash": content_hash(hashed),
        "committed_delta": committed_delta,
    }
