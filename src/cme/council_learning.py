"""Council Learning Loop — self-improving cycle for multi-agent deliberations.

The CouncilLearningLoop manages the lifecycle of learning candidates that
are generated from quality gate evaluations. Every council run should
produce learning candidates that, when approved and applied, make the
next deliberation better. This is the closed-loop principle applied to
multi-agent consensus.

Core Principle
==============

The system that produces consensus outputs should itself improve with every
cycle. Learning candidates flow through a well-defined lifecycle:

    QualityGateResult ──> propose_learning() ──> LearningCandidate
                                                      │
                        ┌─────────────────────────────┘
                        │
                        ▼
                 ┌──────────────┐
                 │ PENDING_REVIEW│
                 └──────┬───────┘
                   ┌────┴────┐
                   ▼         ▼
            ┌──────────┐  ┌──────────────┐
            │ APPROVED │  │  REJECTED    │
            └────┬─────┘  └──────────────┘
                 │
                 ▼
          ┌──────────────┐
          │ APPLIED      │────> Next council cycle
          └──────────────┘

Lifecycle States
===============

1. PENDING_REVIEW — Newly proposed, awaiting human or system approval
2. APPROVED — Accepted by an approver, ready for application
3. APPLIED — Changes applied to the next council cycle
4. REJECTED — Rejected with reason
5. NEEDS_REWRITE — Approved but needs refinement before application

Architecture Diagram
====================

    CouncilRun ──> CouncilQualityGate ──> CouncilQualityGateResult
                                                    │
                                                    ▼
                                          CouncilLearningLoop
                                          ├─ propose_learning()
                                          │   └─> list[CouncilLearningCandidate]
                                          ├─ approve_candidate()
                                          ├─ reject_candidate()
                                          ├─ apply_to_next_cycle()
                                          ├─ get_active_learning()
                                          └─ get_cycle_improvement_report()
"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from cme.council_quality_gate import CouncilQualityGateResult
    from cme.spacebase.council import CouncilReport


class LearningStatus(str, Enum):
    """Lifecycle states for a council learning candidate."""

    PENDING_REVIEW = "Pending Review"
    APPROVED = "Approved"
    APPLIED = "Applied to Next Cycle"
    REJECTED = "Rejected"
    NEEDS_REWRITE = "Needs Rewrite"


@dataclass
class CouncilLearningCandidate:
    """A single learning candidate from a council deliberation.

    Attributes:
        candidate_id: Unique identifier for this candidate.
        learning: What should improve in the next cycle.
        trigger: What event triggered this learning candidate.
        dimension: Which quality dimension failed or was weak.
        severity: Severity level — "critical", "warning", or "info".
        status: Current lifecycle status.
        council_id: ID of the council that produced this candidate.
        trace_id: Trace ID of the council run.
        created_at: ISO-ish timestamp when proposed.
        approved_at: ISO-ish timestamp when approved (if applicable).
        applied_at: ISO-ish timestamp when applied (if applicable).
        rationale: Detailed rationale for this learning candidate.
    """

    candidate_id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    learning: str = ""
    trigger: str = ""
    dimension: str = ""
    severity: str = "info"
    status: LearningStatus = LearningStatus.PENDING_REVIEW
    council_id: str = ""
    trace_id: str = ""
    created_at: str = field(
        default_factory=lambda: time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    )
    approved_at: str | None = None
    applied_at: str | None = None
    rationale: str = ""

    def to_dict(self) -> dict[str, Any]:
        """Serialise to a plain dict."""
        return {
            "candidate_id": self.candidate_id,
            "learning": self.learning,
            "trigger": self.trigger,
            "dimension": self.dimension,
            "severity": self.severity,
            "status": self.status.value,
            "council_id": self.council_id,
            "trace_id": self.trace_id,
            "created_at": self.created_at,
            "approved_at": self.approved_at,
            "applied_at": self.applied_at,
            "rationale": self.rationale,
        }


class CouncilLearningLoop:
    """Manages the self-improving loop for council deliberations.

    Every council run should produce learning candidates that, when approved
    and applied, make the next deliberation better. This is the closed-loop
    principle applied to multi-agent consensus.

    Core principle: The system that produces consensus outputs should itself
    improve with every cycle.

    Usage::

        loop = CouncilLearningLoop()

        # After a council run with quality evaluation:
        candidates = loop.propose_learning(quality_result, report)
        for c in candidates:
            print(f"[{c.severity}] {c.learning}")

        # Review and approve:
        loop.approve_candidate(candidates[0].candidate_id, approver="system")
        loop.apply_to_next_cycle(candidates[0].candidate_id)

        # Check status:
        active = loop.get_active_learning()
        report = loop.get_cycle_improvement_report(last_n_cycles=6)
    """

    def __init__(self) -> None:
        self._candidates: dict[str, CouncilLearningCandidate] = {}
        self._history: list[CouncilLearningCandidate] = []

    def propose_learning(
        self,
        quality_result: CouncilQualityGateResult,
        report: CouncilReport,
    ) -> list[CouncilLearningCandidate]:
        """Propose learning candidates from a quality gate result and council report.

        Scans all failed and warning checks in the quality result, then
        generates concrete learning candidates for each. Only checks that
        failed or scored below the improvement threshold generate candidates.

        Args:
            quality_result: The CouncilQualityGateResult from evaluation.
            report: The CouncilReport from the council run.

        Returns:
            A list of CouncilLearningCandidate objects in PENDING_REVIEW state.
        """
        candidates: list[CouncilLearningCandidate] = []

        for check in quality_result.checks:
            # Only propose for failed checks or low-scoring passes
            if not check.passed or check.score < 0.7:
                candidate = CouncilLearningCandidate(
                    learning=self._derive_learning(check, report),
                    trigger=f"Quality gate: {check.dimension.value} "
                            f"score={check.score:.2f}, passed={check.passed}",
                    dimension=check.dimension.value,
                    severity=check.severity,
                    status=LearningStatus.PENDING_REVIEW,
                    council_id=report.root_intent_id,
                    trace_id=report.trace_id,
                    rationale=check.notes,
                )
                candidates.append(candidate)
                self._candidates[candidate.candidate_id] = candidate
                self._history.append(candidate)

        return candidates

    def approve_candidate(
        self,
        candidate_id: str,
        approver: str = "system",
    ) -> CouncilLearningCandidate | None:
        """Approve a pending learning candidate.

        Args:
            candidate_id: The ID of the candidate to approve.
            approver: Name or ID of the approver (defaults to "system").

        Returns:
            The updated candidate, or None if not found.
        """
        candidate = self._candidates.get(candidate_id)
        if candidate is None:
            return None

        if candidate.status != LearningStatus.PENDING_REVIEW:
            return candidate  # Return as-is, already processed

        candidate.status = LearningStatus.APPROVED
        candidate.approved_at = time.strftime(
            "%Y-%m-%dT%H:%M:%SZ", time.gmtime()
        )
        candidate.rationale += f" [Approved by {approver}]"
        return candidate

    def reject_candidate(
        self,
        candidate_id: str,
        reason: str = "",
    ) -> CouncilLearningCandidate | None:
        """Reject a pending learning candidate.

        Args:
            candidate_id: The ID of the candidate to reject.
            reason: Reason for rejection.

        Returns:
            The updated candidate, or None if not found.
        """
        candidate = self._candidates.get(candidate_id)
        if candidate is None:
            return None

        if candidate.status != LearningStatus.PENDING_REVIEW:
            return candidate

        candidate.status = LearningStatus.REJECTED
        candidate.rationale += f" [Rejected: {reason}]" if reason else " [Rejected]"
        return candidate

    def apply_to_next_cycle(
        self,
        candidate_id: str,
    ) -> CouncilLearningCandidate | None:
        """Mark an approved candidate as applied to the next council cycle.

        Args:
            candidate_id: The ID of the approved candidate to apply.

        Returns:
            The updated candidate, or None if not found or not approved.
        """
        candidate = self._candidates.get(candidate_id)
        if candidate is None:
            return None

        if candidate.status != LearningStatus.APPROVED:
            return candidate  # Cannot apply non-approved candidates

        candidate.status = LearningStatus.APPLIED
        candidate.applied_at = time.strftime(
            "%Y-%m-%dT%H:%M:%SZ", time.gmtime()
        )
        return candidate

    def get_active_learning(self) -> list[CouncilLearningCandidate]:
        """Return all currently active (non-terminal) learning candidates.

        Active candidates are those in PENDING_REVIEW, APPROVED, or
        NEEDS_REWRITE status.

        Returns:
            List of active learning candidates.
        """
        active_statuses = {
            LearningStatus.PENDING_REVIEW,
            LearningStatus.APPROVED,
            LearningStatus.NEEDS_REWRITE,
        }
        return [
            c for c in self._candidates.values()
            if c.status in active_statuses
        ]

    def get_pending_review(self) -> list[CouncilLearningCandidate]:
        """Return all candidates awaiting review.

        Returns:
            List of candidates in PENDING_REVIEW status.
        """
        return [
            c for c in self._candidates.values()
            if c.status == LearningStatus.PENDING_REVIEW
        ]

    def get_cycle_improvement_report(self, last_n_cycles: int = 6) -> str:
        """Generate a summary of improvement across recent council cycles.

        Produces a human-readable markdown report showing:
        - Total candidates proposed, approved, rejected, applied
        - Trend of quality scores across cycles
        - Most impactful improvements

        Args:
            last_n_cycles: Number of recent cycles to include.

        Returns:
            Markdown-formatted improvement report string.
        """
        recent = self._history[-last_n_cycles:]

        # Count by status
        total = len(recent)
        approved = sum(1 for c in recent if c.status == LearningStatus.APPROVED)
        applied = sum(1 for c in recent if c.status == LearningStatus.APPLIED)
        rejected = sum(1 for c in recent if c.status == LearningStatus.REJECTED)
        pending = sum(1 for c in recent if c.status == LearningStatus.PENDING_REVIEW)

        # Group by dimension
        by_dimension: dict[str, list[CouncilLearningCandidate]] = {}
        for c in recent:
            by_dimension.setdefault(c.dimension, []).append(c)

        lines = [
            "# Council Learning Loop — Improvement Report",
            "",
            f"**Period**: Last {last_n_cycles} cycles ({total} candidates total)",
            "",
            "## Status Summary",
            "",
            f"| Status | Count |",
            f"|--------|-------|",
            f"| Pending Review | {pending} |",
            f"| Approved | {approved} |",
            f"| Applied | {applied} |",
            f"| Rejected | {rejected} |",
            "",
            "## By Dimension",
            "",
        ]

        for dim, candidates in sorted(by_dimension.items()):
            lines.append(f"### {dim}")
            lines.append(f"Total candidates: {len(candidates)}")
            for c in candidates:
                status_icon = {
                    LearningStatus.PENDING_REVIEW: "⏳",
                    LearningStatus.APPROVED: "✅",
                    LearningStatus.APPLIED: "🚀",
                    LearningStatus.REJECTED: "❌",
                    LearningStatus.NEEDS_REWRITE: "✏️",
                }.get(c.status, "❓")
                lines.append(
                    f"  {status_icon} [{c.severity}] {c.learning[:80]}"
                )
            lines.append("")

        if not recent:
            lines.append("No learning candidates recorded yet.")
            lines.append("")

        return "\n".join(lines)

    def _derive_learning(
        self,
        check: Any,
        report: CouncilReport,
    ) -> str:
        """Derive a concrete learning statement from a failed quality check.

        Uses the dimension name and notes to generate an actionable improvement
        suggestion for the next council cycle.
        """
        dimension = check.dimension.value if hasattr(check.dimension, "value") else str(check.dimension)

        # Map dimensions to concrete improvement suggestions
        learning_map: dict[str, str] = {
            "source_grounding": (
                "Require agents to cite evidence sources explicitly in their posts. "
                "Add a mandatory 'Evidence' section to each agent's output template."
            ),
            "finance_logic": (
                "Enhance financial reasoning by requiring quantitative analysis "
                "and numerical justification in all finance-domain posts."
            ),
            "materiality": (
                "Increase minimum post count or agent diversity requirements to "
                "ensure thorough deliberation coverage."
            ),
            "continuity": (
                "Enforce trace ID consistency and lock state progression validation "
                "before allowing council lock."
            ),
            "open_issues": (
                "Require explicit separation of assumptions from facts in each "
                "agent's post. Add an 'Assumptions' and 'Known Risks' section."
            ),
            "learning_candidates": (
                "Encourage agents to include improvement-oriented language and "
                "actionable recommendations in their output."
            ),
            "human_approval": (
                "Add explicit human review flag to high-value council decisions. "
                "Implement HUMAN_REVIEW gate before LOCKED state for Tier 3 decisions."
            ),
        }

        base = learning_map.get(dimension, f"Improve {dimension} in future council runs.")
        notes_suffix = f" (Note: {check.notes})" if check.notes else ""
        return f"{base}{notes_suffix}"
