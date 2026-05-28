"""Consensus Hardening Protocol — lock state machine and validation checks.

The CHP ensures that decision rooms in Consensus Commons cannot reach a
LOCKED state without passing through adversarial review and validation.
It mirrors the cognitive mesh engine's consensus validation layer.

SKILLOPT Integration (v0.2.0):
  The ACE subsystem's playbook evolution is governed by a SKILLOPT-style
  training loop. Every candidate delta is bounded by a per-epoch edit
  budget, evaluated on a held-out validation split (D_sel), and promoted
  to LOCKED only after strictly beating the current champion. Rejected
  deltas are retained as adversarial memory for the TriangulationRunner.

  The SKILLOPT validation gate maps onto CHP's existing lock progression:
    PROVISIONAL      → candidate skill under optimization
    PROVISIONAL_LOCK → passed D_sel validation gate
    LOCKED           → promoted to champion registry

  Reference:
    Yang et al., "SkillOpt: Executive Strategy for Self-Evolving Agent Skills",
    Microsoft / SJTU / Tongji / Fudan, May 2026. arXiv:2605.23904
"""

from __future__ import annotations

from enum import Enum
from typing import Any


class CHPGate(str, Enum):
    """Individual validation gates in the consensus hardening protocol."""

    MULTIPLE_PERSPECTIVES = "multiple_perspectives"
    ADVERSARIAL_CHALLENGE = "adversarial_challenge"
    CHALLENGE_ADDRESSED = "challenge_addressed"
    EVIDENCE_PROVIDED = "evidence_provided"
    NO_FALLACIES = "no_fallacies"
    TRACE_CONSISTENCY = "trace_consistency"
    METADATA_COMPLETE = "metadata_complete"
    HUMAN_REVIEW = "human_review"  # optional, for high-value decisions


class CHPResult:
    """Result of running the CHP validation checks."""

    def __init__(self) -> None:
        self.gates: dict[CHPGate, bool] = {}
        self.failures: list[str] = []
        self.warnings: list[str] = []

    def pass_gate(self, gate: CHPGate) -> None:
        self.gates[gate] = True

    def fail_gate(self, gate: CHPGate, reason: str) -> None:
        self.gates[gate] = False
        self.failures.append(f"{gate.value}: {reason}")

    def warn(self, message: str) -> None:
        self.warnings.append(message)

    @property
    def is_valid(self) -> bool:
        """All required gates passed (warnings are non-blocking)."""
        required = {g for g in CHPGate if g != CHPGate.HUMAN_REVIEW}
        return all(self.gates.get(g, False) for g in required)

    @property
    def is_locked(self) -> bool:
        """Valid and no warnings (strict mode)."""
        return self.is_valid and len(self.warnings) == 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "is_valid": self.is_valid,
            "is_locked": self.is_locked,
            "gates": {g.value: v for g, v in self.gates.items()},
            "failures": self.failures,
            "warnings": self.warnings,
        }


# ---------------------------------------------------------------------------
# SKILLOPT Lock State Extensions
# ---------------------------------------------------------------------------

class SKILLOPTLockState(str, Enum):
    """Extended lock states for the SKILLOPT training loop.

    These states integrate with CHP's existing PROVISIONAL / CHALLENGED /
    VALIDATED / LOCKED progression by adding SKILLOPT-specific gates.
    """

    EXPLORING = "EXPLORING"           # Initial rollout on D_train
    PROVISIONAL = "PROVISIONAL"       # Candidate skill under optimization
    VALIDATION_GATE = "VALIDATION_GATE"  # Being evaluated on D_sel
    PROVISIONAL_LOCK = "PROVISIONAL_LOCK"  # Passed D_sel (not yet champion)
    CHALLENGED = "CHALLENGED"         # Adversarial review (existing CHP)
    VALIDATED = "VALIDATED"           # All CHP gates passed
    LOCKED = "LOCKED"                 # Champion — promoted to registry
    FAILED = "FAILED"                 # Validation failed; candidate rejected


# Mapping between SKILLOPT states and CHP gates
SKILLOPT_CHP_GATE_MAP: dict[SKILLOPTLockState, list[CHPGate]] = {
    SKILLOPTLockState.EXPLORING: [CHPGate.MULTIPLE_PERSPECTIVES],
    SKILLOPTLockState.PROVISIONAL: [
        CHPGate.MULTIPLE_PERSPECTIVES,
        CHPGate.EVIDENCE_PROVIDED,
    ],
    SKILLOPTLockState.VALIDATION_GATE: [
        CHPGate.MULTIPLE_PERSPECTIVES,
        CHPGate.EVIDENCE_PROVIDED,
        CHPGate.METADATA_COMPLETE,
    ],
    SKILLOPTLockState.PROVISIONAL_LOCK: [
        CHPGate.MULTIPLE_PERSPECTIVES,
        CHPGate.ADVERSARIAL_CHALLENGE,
        CHPGate.CHALLENGE_ADDRESSED,
        CHPGate.EVIDENCE_PROVIDED,
        CHPGate.METADATA_COMPLETE,
    ],
    SKILLOPTLockState.VALIDATED: [
        CHPGate.MULTIPLE_PERSPECTIVES,
        CHPGate.ADVERSARIAL_CHALLENGE,
        CHPGate.CHALLENGE_ADDRESSED,
        CHPGate.EVIDENCE_PROVIDED,
        CHPGate.NO_FALLACIES,
        CHPGate.TRACE_CONSISTENCY,
        CHPGate.METADATA_COMPLETE,
    ],
    SKILLOPTLockState.LOCKED: list(CHPGate),  # All gates required
}

# Allowed state transitions for SKILLOPT lock progression
SKILLOPT_TRANSITIONS: dict[SKILLOPTLockState, list[SKILLOPTLockState]] = {
    SKILLOPTLockState.EXPLORING: [SKILLOPTLockState.PROVISIONAL, SKILLOPTLockState.FAILED],
    SKILLOPTLockState.PROVISIONAL: [SKILLOPTLockState.VALIDATION_GATE, SKILLOPTLockState.FAILED],
    SKILLOPTLockState.VALIDATION_GATE: [
        SKILLOPTLockState.PROVISIONAL_LOCK,   # Passed D_sel
        SKILLOPTLockState.PROVISIONAL,        # Failed D_sel, continue training
        SKILLOPTLockState.FAILED,             # Irrecoverable
    ],
    SKILLOPTLockState.PROVISIONAL_LOCK: [
        SKILLOPTLockState.CHALLENGED,         # Adversarial review
        SKILLOPTLockState.LOCKED,             # Skip to locked (if no adversary)
    ],
    SKILLOPTLockState.CHALLENGED: [
        SKILLOPTLockState.VALIDATED,          # Challenge addressed
        SKILLOPTLockState.PROVISIONAL,        # Challenge upheld, back to training
    ],
    SKILLOPTLockState.VALIDATED: [SKILLOPTLockState.LOCKED],
    SKILLOPTLockState.LOCKED: [],  # Terminal state
    SKILLOPTLockState.FAILED: [],  # Terminal state
}
