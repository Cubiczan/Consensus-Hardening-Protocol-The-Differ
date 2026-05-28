"""Council Quality Gate — 7-dimension evaluation of council deliberation outputs.

The CouncilQualityGate evaluates a completed CouncilReport through seven
independent quality dimensions, producing a CouncilQualityGateResult that
determines whether the deliberation meets the bar for a LOCKED conclusion.

Quality Dimensions
=================

1. SOURCE_GROUNDING — Are claims grounded in evidence/data?
2. FINANCE_LOGIC — Does the reasoning make CFO/logic sense?
3. MATERIALITY — Focus on what matters most
4. CONTINUITY — Prior decisions and memory checked
5. OPEN_ISSUES — Assumptions separated from facts
6. LEARNING_CANDIDATES — System improvement signals identified
7. HUMAN_APPROVAL — Which items need human sign-off

Evaluation Strategy
==================

All evaluation is rule-based (no LLM dependency). The gate analyses:

* Number of agents involved (more = better diversity)
* Adversarial challenge presence (required for quality)
* Lock state progression (EXPLORING -> PROVISIONAL -> ... -> LOCKED = good)
* Post body length and structure (longer, structured posts = better)
* Trace ID consistency across all posts
* Metadata completeness on every post
* Agent diversity (unique agent names, not duplicates)
* Validation agent presence (validator or compliance-validator)

Architecture Diagram
====================

    CouncilReport ─────────────────────────────────────────────────┐
    │                                                              │
    ├─ posts[]          ──> body length, trace consistency,       │
    │                         metadata completeness, agent names   │
    ├─ final_state     ──> LOCKED (good) / FAILED (bad)          │
    ├─ agent_contributions ──> diversity of agents                │
    └─ trace_id        ──> consistency check                      │
                                                                 │
    ┌────────────────────────────────────────────────────────────┘
    │
    ▼
    CouncilQualityGate.evaluate(report)
    │
    ├─ SOURCE_GROUNDING:  checks body lengths, evidence keywords
    ├─ FINANCE_LOGIC:    checks for financial reasoning patterns
    ├─ MATERIALITY:      checks post count, focus indicators
    ├─ CONTINUITY:       checks trace ID consistency
    ├─ OPEN_ISSUES:      checks for assumption language in posts
    ├─ LEARNING_CANDIDATES: identifies improvement signals
    ├─ HUMAN_APPROVAL:   identifies items needing human review
    │
    ▼
    CouncilQualityGateResult
    ├─ overall_passed: bool
    ├─ total_score: float (0.0 - 1.0)
    ├─ checks: list[CouncilQualityGateCheck]
    ├─ improvement_candidates: list[str]
    ├─ timestamp: str
    └─ council_id: str
"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from cme.spacebase.council import CouncilReport


class CouncilQualityDimension(str, Enum):
    """The seven quality dimensions for council deliberation evaluation."""

    SOURCE_GROUNDING = "source_grounding"
    FINANCE_LOGIC = "finance_logic"
    MATERIALITY = "materiality"
    CONTINUITY = "continuity"
    OPEN_ISSUES = "open_issues"
    LEARNING_CANDIDATES = "learning_candidates"
    HUMAN_APPROVAL = "human_approval"


@dataclass
class CouncilQualityGateCheck:
    """Result of a single quality dimension check.

    Attributes:
        dimension: The quality dimension being evaluated.
        passed: Whether this dimension passed the quality threshold.
        score: Normalized score from 0.0 (worst) to 1.0 (best).
        notes: Human-readable explanation of the check result.
        severity: Severity level — "critical", "warning", or "info".
    """

    dimension: CouncilQualityDimension
    passed: bool
    score: float
    notes: str
    severity: str = "info"


@dataclass
class CouncilQualityGateResult:
    """Aggregate result of all quality gate checks.

    Attributes:
        overall_passed: True if all critical checks passed.
        total_score: Weighted average of all dimension scores.
        checks: Individual check results for each dimension.
        improvement_candidates: List of identified improvement opportunities.
        timestamp: ISO-ish timestamp of when the evaluation was performed.
        council_id: Unique identifier for this evaluation.
    """

    overall_passed: bool
    total_score: float
    checks: list[CouncilQualityGateCheck] = field(default_factory=list)
    improvement_candidates: list[str] = field(default_factory=list)
    timestamp: str = ""
    council_id: str = ""


class CouncilQualityGate:
    """Evaluates council deliberation quality through 7 dimensions.

    Rule-based evaluation using:
    - Number of agents involved (more = better diversity)
    - Adversarial challenge presence
    - Lock state progression (EXPLORING -> PROVISIONAL -> ... -> LOCKED = good)
    - Post body length and structure
    - Trace ID consistency
    - Metadata completeness

    Usage::

        gate = CouncilQualityGate()
        result = gate.evaluate(report)

        if result.overall_passed:
            print(f"Quality score: {result.total_score:.1%}")
        else:
            for check in result.checks:
                if not check.passed:
                    print(f"FAIL: {check.dimension.value} — {check.notes}")
    """

    # Thresholds for pass/fail
    MIN_AGENT_DIVERSITY: int = 3  # At least 3 unique agents
    MIN_POST_COUNT: int = 3  # At least 3 posts
    MIN_BODY_LENGTH: int = 50  # Minimum average body length
    MIN_EVIDENCE_KEYWORDS: int = 2  # Minimum evidence-related keywords
    CRITICAL_SCORE_THRESHOLD: float = 0.4  # Below this = critical fail
    WARNING_SCORE_THRESHOLD: float = 0.6  # Below this = warning

    # Keywords that indicate evidence grounding
    EVIDENCE_KEYWORDS: set[str] = {
        "data", "evidence", "analysis", "study", "research", "survey",
        "report", "statistic", "finding", "metric", "benchmark", "result",
        "empirical", "observed", "measured", "validated", "verified",
        "source", "reference", "citation", "according to", "based on",
    }

    # Keywords that indicate financial reasoning
    FINANCE_KEYWORDS: set[str] = {
        "roi", "npv", "irr", "cash flow", "capital", "revenue",
        "cost", "budget", "investment", "return", "financial",
        "fiscal", "expenditure", "profit", "loss", "margin",
        "allocation", "funding", "valuation", "yield",
    }

    # Keywords that indicate assumptions or open issues
    ASSUMPTION_KEYWORDS: set[str] = {
        "assume", "assumption", "uncertain", "unknown", "tbd",
        "to be determined", "pending", "if", "could", "might",
        "may", "perhaps", "possibly", "estimate", "approximate",
        "projection", "forecast", "risk", "uncertainty",
    }

    # Keywords that indicate human review is needed
    HUMAN_REVIEW_KEYWORDS: set[str] = {
        "human review", "manual review", "sign-off", "approval",
        "human approver", "regulatory", "legal", "compliance",
        "high-value", "high value", "material", "sensitive",
        "critical decision", "executive", "board",
    }

    def evaluate(self, report: CouncilReport) -> CouncilQualityGateResult:
        """Evaluate a council report through all 7 quality dimensions.

        Args:
            report: A completed CouncilReport from a council run.

        Returns:
            A CouncilQualityGateResult with per-dimension checks,
            an overall pass/fail, and a total quality score.
        """
        checks: list[CouncilQualityGateCheck] = []
        improvement_candidates: list[str] = []

        # Evaluate each dimension
        checks.append(self._check_source_grounding(report))
        checks.append(self._check_finance_logic(report))
        checks.append(self._check_materiality(report))
        checks.append(self._check_continuity(report))
        checks.append(self._check_open_issues(report))
        checks.append(self._check_learning_candidates(report))
        checks.append(self._check_human_approval(report))

        # Gather improvement candidates from failed/warning checks
        for check in checks:
            if not check.passed:
                improvement_candidates.append(
                    f"[{check.dimension.value}] {check.notes}"
                )

        # Determine overall pass: all non-info-severity checks must pass
        overall_passed = all(
            c.passed for c in checks
            if c.severity in ("critical", "warning")
        )

        # Compute total score (weighted average)
        if checks:
            weights = {
                CouncilQualityDimension.SOURCE_GROUNDING: 0.20,
                CouncilQualityDimension.FINANCE_LOGIC: 0.15,
                CouncilQualityDimension.MATERIALITY: 0.15,
                CouncilQualityDimension.CONTINUITY: 0.15,
                CouncilQualityDimension.OPEN_ISSUES: 0.10,
                CouncilQualityDimension.LEARNING_CANDIDATES: 0.10,
                CouncilQualityDimension.HUMAN_APPROVAL: 0.15,
            }
            total_score = sum(
                c.score * weights.get(c.dimension, 1.0 / len(checks))
                for c in checks
            )
        else:
            total_score = 0.0

        return CouncilQualityGateResult(
            overall_passed=overall_passed,
            total_score=total_score,
            checks=checks,
            improvement_candidates=improvement_candidates,
            timestamp=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            council_id=f"qg-{uuid.uuid4().hex[:8]}",
        )

    def _check_source_grounding(self, report: CouncilReport) -> CouncilQualityGateCheck:
        """Check SOURCE_GROUNDING: Are claims grounded in evidence/data?

        Evaluates:
        - Body lengths (longer bodies suggest more evidence)
        - Presence of evidence-related keywords
        - Number of unique produces/consumes artifacts
        """
        if not report.posts:
            return CouncilQualityGateCheck(
                dimension=CouncilQualityDimension.SOURCE_GROUNDING,
                passed=False,
                score=0.0,
                notes="No posts to evaluate — no evidence grounding possible.",
                severity="critical",
            )

        # Check body lengths
        avg_body_len = sum(len(p.body) for p in report.posts) / len(report.posts)
        body_score = min(1.0, avg_body_len / 500.0)

        # Check evidence keywords
        all_body = " ".join(p.body.lower() for p in report.posts)
        evidence_count = sum(1 for kw in self.EVIDENCE_KEYWORDS if kw in all_body)
        evidence_score = min(1.0, evidence_count / (self.MIN_EVIDENCE_KEYWORDS * 4))

        # Check metadata (produces/consumes)
        meta_score = 0.0
        posts_with_meta = sum(
            1 for p in report.posts if p.produces or p.consumes
        )
        meta_score = min(1.0, posts_with_meta / max(len(report.posts), 1))

        # Weighted combination
        score = 0.4 * body_score + 0.4 * evidence_score + 0.2 * meta_score
        passed = score >= self.WARNING_SCORE_THRESHOLD
        severity = "warning" if not passed and score >= self.CRITICAL_SCORE_THRESHOLD else (
            "critical" if not passed else "info"
        )

        notes_parts = []
        if avg_body_len < self.MIN_BODY_LENGTH:
            notes_parts.append(f"average body length ({avg_body_len:.0f} chars) below threshold ({self.MIN_BODY_LENGTH})")
        if evidence_count < self.MIN_EVIDENCE_KEYWORDS:
            notes_parts.append(f"only {evidence_count} evidence keywords found (min {self.MIN_EVIDENCE_KEYWORDS})")
        if not notes_parts:
            notes_parts.append(f"adequate evidence grounding (avg {avg_body_len:.0f} chars, {evidence_count} evidence keywords)")

        return CouncilQualityGateCheck(
            dimension=CouncilQualityDimension.SOURCE_GROUNDING,
            passed=passed,
            score=score,
            notes="; ".join(notes_parts),
            severity=severity,
        )

    def _check_finance_logic(self, report: CouncilReport) -> CouncilQualityGateCheck:
        """Check FINANCE_LOGIC: Does the reasoning make CFO/logic sense?

        Evaluates:
        - Presence of financial reasoning keywords
        - Whether the deliberation shows quantitative reasoning
        - Number structure (percentages, dollar amounts, etc.)
        """
        all_body = " ".join(p.body.lower() for p in report.posts)
        finance_count = sum(1 for kw in self.FINANCE_KEYWORDS if kw in all_body)

        # Check for quantitative patterns (numbers, percentages)
        import re
        numbers = re.findall(r"\d+(?:\.\d+)?%?", all_body)
        number_score = min(1.0, len(numbers) / 5.0)

        finance_score = min(1.0, finance_count / 8.0)
        score = 0.6 * finance_score + 0.4 * number_score
        passed = score >= self.WARNING_SCORE_THRESHOLD

        severity = "info"  # Finance logic is informational for non-finance topics
        notes_parts = []
        if finance_count > 0:
            notes_parts.append(f"{finance_count} financial reasoning keywords detected")
        if numbers:
            notes_parts.append(f"{len(numbers)} quantitative data points found")
        if not notes_parts:
            notes_parts.append("no financial or quantitative reasoning detected")

        return CouncilQualityGateCheck(
            dimension=CouncilQualityDimension.FINANCE_LOGIC,
            passed=passed,
            score=score,
            notes="; ".join(notes_parts),
            severity=severity,
        )

    def _check_materiality(self, report: CouncilReport) -> CouncilQualityGateCheck:
        """Check MATERIALITY: Focus on what matters most.

        Evaluates:
        - Number of posts (more posts = more thorough)
        - Agent diversity (more unique agents = better perspective coverage)
        - Whether the deliberation reached a conclusion
        """
        post_score = min(1.0, len(report.posts) / 6.0)
        unique_agents = len(report.agent_contributions)
        agent_score = min(1.0, unique_agents / 4.0)
        conclusion_score = 1.0 if report.final_state in (
            "LOCKED", "VALIDATED"
        ) else 0.3

        score = 0.3 * post_score + 0.4 * agent_score + 0.3 * conclusion_score
        passed = score >= self.WARNING_SCORE_THRESHOLD
        severity = "warning" if not passed else "info"

        notes_parts = []
        if len(report.posts) < self.MIN_POST_COUNT:
            notes_parts.append(f"only {len(report.posts)} posts (min {self.MIN_POST_COUNT})")
        if unique_agents < self.MIN_AGENT_DIVERSITY:
            notes_parts.append(f"only {unique_agents} unique agents (min {self.MIN_AGENT_DIVERSITY})")
        if not notes_parts:
            notes_parts.append(f"adequate materiality: {len(report.posts)} posts, {unique_agents} agents")

        return CouncilQualityGateCheck(
            dimension=CouncilQualityDimension.MATERIALITY,
            passed=passed,
            score=score,
            notes="; ".join(notes_parts),
            severity=severity,
        )

    def _check_continuity(self, report: CouncilReport) -> CouncilQualityGateCheck:
        """Check CONTINUITY: Prior decisions and memory checked.

        Evaluates:
        - Trace ID consistency across all posts
        - Whether the report-level trace_id matches all post trace_ids
        - Lock state progression coherence
        """
        if not report.posts:
            return CouncilQualityGateCheck(
                dimension=CouncilQualityDimension.CONTINUITY,
                passed=False,
                score=0.0,
                notes="No posts to evaluate — continuity cannot be verified.",
                severity="critical",
            )

        # Check trace ID consistency
        report_trace = report.trace_id
        mismatched_traces = [
            p.post_id for p in report.posts
            if p.trace_id and p.trace_id != report_trace
        ]
        empty_traces = [
            p.post_id for p in report.posts if not p.trace_id
        ]

        trace_score = 1.0
        if mismatched_traces:
            trace_score -= 0.5 * (len(mismatched_traces) / len(report.posts))
        if empty_traces:
            trace_score -= 0.3 * (len(empty_traces) / len(report.posts))
        trace_score = max(0.0, trace_score)

        # Check lock state progression (presence of key states)
        states_seen = {p.lock_state.value for p in report.posts}
        progression_score = 0.0
        ideal_progression = {"PROVISIONAL", "CHALLENGED", "VALIDATED", "LOCKED"}
        for state in ideal_progression:
            if state in states_seen:
                progression_score += 0.25

        score = 0.5 * trace_score + 0.5 * progression_score
        passed = score >= self.WARNING_SCORE_THRESHOLD
        severity = "critical" if not passed and trace_score < 0.5 else (
            "warning" if not passed else "info"
        )

        notes_parts = []
        if mismatched_traces:
            notes_parts.append(f"{len(mismatched_traces)} posts have mismatched trace IDs")
        if empty_traces:
            notes_parts.append(f"{len(empty_traces)} posts have empty trace IDs")
        if progression_score < 1.0:
            notes_parts.append(f"incomplete lock progression; states seen: {states_seen}")
        if not notes_parts:
            notes_parts.append("trace IDs consistent; lock progression complete")

        return CouncilQualityGateCheck(
            dimension=CouncilQualityDimension.CONTINUITY,
            passed=passed,
            score=score,
            notes="; ".join(notes_parts),
            severity=severity,
        )

    def _check_open_issues(self, report: CouncilReport) -> CouncilQualityGateCheck:
        """Check OPEN_ISSUES: Assumptions separated from facts.

        Evaluates:
        - Presence of assumption language in posts
        - Whether agents explicitly flag uncertainties
        - Whether the adversarial challenge identifies risks
        """
        all_body = " ".join(p.body.lower() for p in report.posts)
        assumption_count = sum(1 for kw in self.ASSUMPTION_KEYWORDS if kw in all_body)
        assumption_score = min(1.0, assumption_count / 6.0)

        # Check if the adversarial post exists and raises challenges
        has_adversarial = any(
            p.agent == "contrarian" for p in report.posts
        )
        adversarial_score = 0.8 if has_adversarial else 0.2

        # Check if assumptions are explicitly separated from facts
        has_explicit_assumptions = any(
            "assumption" in p.body.lower() or "risk" in p.body.lower()
            or "uncertain" in p.body.lower()
            for p in report.posts
        )
        separation_score = 0.7 if has_explicit_assumptions else 0.3

        score = 0.3 * assumption_score + 0.4 * adversarial_score + 0.3 * separation_score
        passed = score >= self.WARNING_SCORE_THRESHOLD
        severity = "warning" if not passed else "info"

        notes_parts = []
        if assumption_count == 0:
            notes_parts.append("no assumption language detected in any post")
        if not has_adversarial:
            notes_parts.append("no adversarial challenge post found")
        if not has_explicit_assumptions:
            notes_parts.append("assumptions not explicitly separated from facts")
        if not notes_parts:
            notes_parts.append(f"{assumption_count} assumption indicators; adversarial challenge present")

        return CouncilQualityGateCheck(
            dimension=CouncilQualityDimension.OPEN_ISSUES,
            passed=passed,
            score=score,
            notes="; ".join(notes_parts),
            severity=severity,
        )

    def _check_learning_candidates(self, report: CouncilReport) -> CouncilQualityGateCheck:
        """Check LEARNING_CANDIDATES: System improvement signals identified.

        Evaluates:
        - Whether posts contain improvement-oriented language
        - Whether the deliberation surfaced actionable feedback
        - Whether there are signals for the next council cycle
        """
        improvement_keywords = {
            "improve", "improvement", "recommend", "suggestion",
            "should consider", "next step", "follow-up", "action item",
            "iteration", "feedback", "monitor", "review", "address",
            "condition", "roadmap", "track", "milestone",
        }

        all_body = " ".join(p.body.lower() for p in report.posts)
        improvement_count = sum(1 for kw in improvement_keywords if kw in all_body)
        improvement_score = min(1.0, improvement_count / 5.0)

        # Check for explicit conditions or caveats in posts
        has_conditions = any(
            "condition" in p.body.lower() or "recommend" in p.body.lower()
            for p in report.posts
        )
        condition_score = 0.8 if has_conditions else 0.3

        score = 0.6 * improvement_score + 0.4 * condition_score
        passed = score >= self.WARNING_SCORE_THRESHOLD
        severity = "info"  # Learning candidates are informational

        notes_parts = []
        if improvement_count == 0:
            notes_parts.append("no improvement-oriented language detected")
        if not has_conditions:
            notes_parts.append("no explicit conditions or recommendations found")
        if not notes_parts:
            notes_parts.append(f"{improvement_count} improvement signals detected")

        return CouncilQualityGateCheck(
            dimension=CouncilQualityDimension.LEARNING_CANDIDATES,
            passed=passed,
            score=score,
            notes="; ".join(notes_parts),
            severity=severity,
        )

    def _check_human_approval(self, report: CouncilReport) -> CouncilQualityGateCheck:
        """Check HUMAN_APPROVAL: Which items need human sign-off.

        Evaluates:
        - Whether posts contain human review keywords
        - Whether high-value decisions are flagged for human approval
        - Whether the final state indicates automation or human involvement
        """
        all_body = " ".join(p.body.lower() for p in report.posts)
        human_review_count = sum(
            1 for kw in self.HUMAN_REVIEW_KEYWORDS if kw in all_body
        )
        human_review_score = min(1.0, human_review_count / 3.0)

        # Check if the report has human review metadata
        has_human_flags = any(
            "human" in p.body.lower() or "review" in p.body.lower()
            for p in report.posts
        )
        flag_score = 0.7 if has_human_flags else 0.3

        # LOCKED without human review = needs attention
        auto_locked = report.final_state == "LOCKED" and human_review_count == 0
        auto_score = 0.4 if auto_locked else 1.0

        score = 0.4 * human_review_score + 0.3 * flag_score + 0.3 * auto_score
        passed = score >= self.WARNING_SCORE_THRESHOLD
        severity = "warning" if auto_locked else "info"

        notes_parts = []
        if human_review_count == 0:
            notes_parts.append("no human review keywords detected")
        if auto_locked:
            notes_parts.append("council auto-locked without explicit human review flag")
        if not notes_parts:
            notes_parts.append(f"{human_review_count} human review indicators present")

        return CouncilQualityGateCheck(
            dimension=CouncilQualityDimension.HUMAN_APPROVAL,
            passed=passed,
            score=score,
            notes="; ".join(notes_parts),
            severity=severity,
        )
