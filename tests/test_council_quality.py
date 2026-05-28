"""Tests for Council Quality Gate, Learning Loop, R0 Gate, and Foundation Disclosure."""

from __future__ import annotations

import pytest

from cme.spacebase.models import (
    Intent,
    LockState,
    Post,
)
from cme.spacebase.council import CouncilReport
from cme.council_quality_gate import (
    CouncilQualityDimension,
    CouncilQualityGate,
    CouncilQualityGateCheck,
    CouncilQualityGateResult,
)
from cme.council_learning import (
    CouncilLearningCandidate,
    CouncilLearningLoop,
    LearningStatus,
)
from cme.r0_gate import (
    R0Check,
    R0Gate,
    R0Result,
)
from cme.foundation_disclosure import (
    FoundationDisclosure,
    FoundationDisclosureResult,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_post(
    agent: str = "analyst",
    body: str = "Detailed analysis with supporting evidence and data.",
    confidence: float = 0.8,
    lock_state: LockState = LockState.PROVISIONAL,
    trace_id: str = "trace-001",
    produces: list[str] | None = None,
    consumes: list[str] | None = None,
) -> Post:
    return Post(
        intent_id="intent-1",
        title=f"Post by {agent}",
        body=body,
        agent=agent,
        confidence=confidence,
        produces=produces or ["report"],
        consumes=consumes or ["data"],
        lock_state=lock_state,
        trace_id=trace_id,
        parent_intent_id="intent-1",
    )


def _make_report(
    posts: list[Post] | None = None,
    final_state: LockState = LockState.LOCKED,
    trace_id: str = "trace-001",
    agent_contributions: dict[str, list[str]] | None = None,
) -> CouncilReport:
    posts = posts or []
    if agent_contributions is None:
        agent_contributions = {}
        for p in posts:
            agent_contributions.setdefault(p.agent, []).append(p.post_id)
    return CouncilReport(
        root_intent_id="root-1",
        topic="Test council topic",
        trace_id=trace_id,
        posts=posts,
        final_state=final_state,
        agent_contributions=agent_contributions,
    )


def _make_good_report() -> CouncilReport:
    """Create a well-formed council report that should pass quality gate."""
    posts = [
        _make_post(
            agent="financial-analyst",
            body=(
                "FINANCIAL ANALYSIS — Should we allocate $2M capital?\n\n"
                "Based on market data and research findings, the estimated ROI "
                "is 15-25%. Risk factors have been measured and validated. "
                "Recommendation: PROCEED with staged rollout."
            ),
            confidence=0.80,
            lock_state=LockState.PROVISIONAL,
            produces=["capital-flow-model", "risk-assessment"],
            consumes=["market-data", "budget-proposal"],
        ),
        _make_post(
            agent="contrarian",
            body=(
                "ADVERSARIAL CHALLENGE\n\n"
                "Challenge 1: The analyses assume stable patterns not yet validated. "
                "Risk of emergent failure modes exists.\n\n"
                "Challenge 2: Accountability gap — no single responsible party. "
                "This creates legal exposure and potential reputation risk.\n\n"
                "Challenge 3: Cost proportionality concerns — $5K compute for $50K decision."
            ),
            confidence=0.60,
            lock_state=LockState.CHALLENGED,
            produces=["challenge-report"],
            consumes=["analyst-output"],
        ),
        _make_post(
            agent="compliance-validator",
            body=(
                "COMPLIANCE VALIDATION\n\n"
                "Challenge 1 Response: VALID — staged rollout addresses this. "
                "Recommend adding a HUMAN_REVIEW gate before LOCKED state. "
                "VALIDATION RESULT: PASS with conditions.\n\n"
                "Conditions: (1) staged rollout, (2) human review for high-value decisions."
            ),
            confidence=0.90,
            lock_state=LockState.VALIDATED,
            produces=["compliance-report"],
            consumes=["analyst-output", "challenge-output"],
        ),
        _make_post(
            agent="council-summarizer",
            body=(
                "Council Summary\n\n"
                "Consensus reached after adversarial review. Key findings: "
                "multiple analyses confirmed viability, challenges were addressed. "
                "Recommend monitoring and follow-up."
            ),
            confidence=0.92,
            lock_state=LockState.LOCKED,
            produces=["final-report"],
            consumes=["all-agent-outputs"],
        ),
    ]
    return _make_report(posts=posts, final_state=LockState.LOCKED)


# ---------------------------------------------------------------------------
# CouncilQualityGate tests
# ---------------------------------------------------------------------------


class TestCouncilQualityGate:
    """Tests for the CouncilQualityGate 7-dimension evaluation."""

    def test_evaluate_good_report_passes(self):
        report = _make_good_report()
        gate = CouncilQualityGate()
        result = gate.evaluate(report)
        assert result.overall_passed is True
        assert result.total_score > 0.5

    def test_evaluate_empty_report_fails(self):
        report = _make_report(posts=[])
        gate = CouncilQualityGate()
        result = gate.evaluate(report)
        assert result.overall_passed is False

    def test_evaluate_returns_all_seven_dimensions(self):
        report = _make_good_report()
        gate = CouncilQualityGate()
        result = gate.evaluate(report)
        assert len(result.checks) == 7
        dimensions = {c.dimension for c in result.checks}
        assert len(dimensions) == 7
        assert CouncilQualityDimension.SOURCE_GROUNDING in dimensions
        assert CouncilQualityDimension.FINANCE_LOGIC in dimensions
        assert CouncilQualityDimension.MATERIALITY in dimensions
        assert CouncilQualityDimension.CONTINUITY in dimensions
        assert CouncilQualityDimension.OPEN_ISSUES in dimensions
        assert CouncilQualityDimension.LEARNING_CANDIDATES in dimensions
        assert CouncilQualityDimension.HUMAN_APPROVAL in dimensions

    def test_source_grounding_short_bodies_fails(self):
        posts = [_make_post(body="x" * 10) for _ in range(3)]
        report = _make_report(posts=posts)
        gate = CouncilQualityGate()
        result = gate.evaluate(report)
        source_check = next(
            c for c in result.checks
            if c.dimension == CouncilQualityDimension.SOURCE_GROUNDING
        )
        assert source_check.score < 0.5

    def test_source_grounding_long_bodies_scores_high(self):
        posts = [_make_post(body="word " * 500) for _ in range(4)]
        report = _make_report(posts=posts)
        gate = CouncilQualityGate()
        result = gate.evaluate(report)
        source_check = next(
            c for c in result.checks
            if c.dimension == CouncilQualityDimension.SOURCE_GROUNDING
        )
        assert source_check.score > 0.5

    def test_finance_logic_detects_financial_keywords(self):
        posts = [_make_post(body="The ROI is 15%. Capital allocation of $2M is recommended.")]
        report = _make_report(posts=posts)
        gate = CouncilQualityGate()
        result = gate.evaluate(report)
        finance_check = next(
            c for c in result.checks
            if c.dimension == CouncilQualityDimension.FINANCE_LOGIC
        )
        assert finance_check.score > 0.0

    def test_materiality_few_posts_warns(self):
        posts = [_make_post()]
        report = _make_report(posts=posts)
        gate = CouncilQualityGate()
        result = gate.evaluate(report)
        materiality_check = next(
            c for c in result.checks
            if c.dimension == CouncilQualityDimension.MATERIALITY
        )
        assert "only 1 posts" in materiality_check.notes

    def test_continuity_trace_consistency(self):
        posts = [_make_post(trace_id="trace-A"), _make_post(trace_id="trace-B")]
        report = _make_report(posts=posts, trace_id="trace-A")
        gate = CouncilQualityGate()
        result = gate.evaluate(report)
        continuity_check = next(
            c for c in result.checks
            if c.dimension == CouncilQualityDimension.CONTINUITY
        )
        assert "mismatched trace IDs" in continuity_check.notes

    def test_continuity_all_traces_match(self):
        posts = [
            _make_post(trace_id="trace-001"),
            _make_post(trace_id="trace-001"),
        ]
        report = _make_report(posts=posts, trace_id="trace-001")
        gate = CouncilQualityGate()
        result = gate.evaluate(report)
        continuity_check = next(
            c for c in result.checks
            if c.dimension == CouncilQualityDimension.CONTINUITY
        )
        assert continuity_check.score > 0.5

    def test_continuity_empty_traces_flagged(self):
        posts = [_make_post(trace_id=""), _make_post(trace_id="trace-001")]
        report = _make_report(posts=posts)
        gate = CouncilQualityGate()
        result = gate.evaluate(report)
        continuity_check = next(
            c for c in result.checks
            if c.dimension == CouncilQualityDimension.CONTINUITY
        )
        assert "empty trace IDs" in continuity_check.notes

    def test_open_issues_no_adversarial_warns(self):
        posts = [_make_post(agent="analyst"), _make_post(agent="validator")]
        report = _make_report(posts=posts)
        gate = CouncilQualityGate()
        result = gate.evaluate(report)
        open_issues_check = next(
            c for c in result.checks
            if c.dimension == CouncilQualityDimension.OPEN_ISSUES
        )
        assert "no adversarial challenge" in open_issues_check.notes

    def test_open_issues_with_adversarial_passes(self):
        posts = [_make_post(agent="analyst"), _make_post(agent="contrarian", body="Challenge: risk and uncertainty exist.")]
        report = _make_report(posts=posts)
        gate = CouncilQualityGate()
        result = gate.evaluate(report)
        open_issues_check = next(
            c for c in result.checks
            if c.dimension == CouncilQualityDimension.OPEN_ISSUES
        )
        assert open_issues_check.passed is True

    def test_human_approval_auto_locked_warns(self):
        posts = [_make_post(body="The analysis is complete and the decision should proceed immediately.")]
        report = _make_report(posts=posts, final_state=LockState.LOCKED)
        gate = CouncilQualityGate()
        result = gate.evaluate(report)
        human_check = next(
            c for c in result.checks
            if c.dimension == CouncilQualityDimension.HUMAN_APPROVAL
        )
        assert "auto-locked" in human_check.notes

    def test_human_approval_with_review_keywords(self):
        posts = [_make_post(body="This requires human review and regulatory compliance approval.")]
        report = _make_report(posts=posts, final_state=LockState.LOCKED)
        gate = CouncilQualityGate()
        result = gate.evaluate(report)
        human_check = next(
            c for c in result.checks
            if c.dimension == CouncilQualityDimension.HUMAN_APPROVAL
        )
        assert human_check.score > 0.5

    def test_result_has_timestamp_and_council_id(self):
        report = _make_good_report()
        gate = CouncilQualityGate()
        result = gate.evaluate(report)
        assert result.timestamp != ""
        assert result.council_id != ""
        assert result.council_id.startswith("qg-")

    def test_result_has_improvement_candidates(self):
        report = _make_report(posts=[])  # Empty report should produce failures
        gate = CouncilQualityGate()
        result = gate.evaluate(report)
        assert len(result.improvement_candidates) > 0

    def test_scores_are_bounded(self):
        report = _make_good_report()
        gate = CouncilQualityGate()
        result = gate.evaluate(report)
        for check in result.checks:
            assert 0.0 <= check.score <= 1.0
        assert 0.0 <= result.total_score <= 1.0

    def test_final_state_failed_scores_lower(self):
        posts = [_make_post()]
        report = _make_report(posts=posts, final_state=LockState.FAILED)
        gate = CouncilQualityGate()
        result = gate.evaluate(report)
        assert result.overall_passed is False


# ---------------------------------------------------------------------------
# CouncilLearningLoop tests
# ---------------------------------------------------------------------------


class TestCouncilLearningLoop:
    """Tests for the CouncilLearningLoop lifecycle."""

    def test_propose_learning_from_empty_report(self):
        report = _make_report(posts=[])
        gate = CouncilQualityGate()
        quality_result = gate.evaluate(report)
        loop = CouncilLearningLoop()
        candidates = loop.propose_learning(quality_result, report)
        assert len(candidates) > 0

    def test_propose_learning_from_good_report(self):
        report = _make_good_report()
        gate = CouncilQualityGate()
        quality_result = gate.evaluate(report)
        loop = CouncilLearningLoop()
        candidates = loop.propose_learning(quality_result, report)
        # Good report may produce few candidates
        assert isinstance(candidates, list)

    def test_candidates_start_as_pending(self):
        report = _make_report(posts=[])
        gate = CouncilQualityGate()
        quality_result = gate.evaluate(report)
        loop = CouncilLearningLoop()
        candidates = loop.propose_learning(quality_result, report)
        for c in candidates:
            assert c.status == LearningStatus.PENDING_REVIEW

    def test_approve_candidate(self):
        report = _make_report(posts=[])
        gate = CouncilQualityGate()
        quality_result = gate.evaluate(report)
        loop = CouncilLearningLoop()
        candidates = loop.propose_learning(quality_result, report)
        if candidates:
            approved = loop.approve_candidate(candidates[0].candidate_id, "system")
            assert approved is not None
            assert approved.status == LearningStatus.APPROVED
            assert approved.approved_at is not None

    def test_approve_nonexistent_candidate(self):
        loop = CouncilLearningLoop()
        result = loop.approve_candidate("nonexistent-id")
        assert result is None

    def test_approve_already_processed_candidate(self):
        report = _make_report(posts=[])
        gate = CouncilQualityGate()
        quality_result = gate.evaluate(report)
        loop = CouncilLearningLoop()
        candidates = loop.propose_learning(quality_result, report)
        if candidates:
            cid = candidates[0].candidate_id
            loop.approve_candidate(cid)
            # Approve again — should return as-is
            result = loop.approve_candidate(cid)
            assert result.status == LearningStatus.APPROVED

    def test_reject_candidate(self):
        report = _make_report(posts=[])
        gate = CouncilQualityGate()
        quality_result = gate.evaluate(report)
        loop = CouncilLearningLoop()
        candidates = loop.propose_learning(quality_result, report)
        if candidates:
            rejected = loop.reject_candidate(
                candidates[0].candidate_id, "not actionable"
            )
            assert rejected is not None
            assert rejected.status == LearningStatus.REJECTED

    def test_apply_approved_candidate(self):
        report = _make_report(posts=[])
        gate = CouncilQualityGate()
        quality_result = gate.evaluate(report)
        loop = CouncilLearningLoop()
        candidates = loop.propose_learning(quality_result, report)
        if candidates:
            cid = candidates[0].candidate_id
            loop.approve_candidate(cid)
            applied = loop.apply_to_next_cycle(cid)
            assert applied is not None
            assert applied.status == LearningStatus.APPLIED
            assert applied.applied_at is not None

    def test_apply_unapproved_candidate_fails(self):
        report = _make_report(posts=[])
        gate = CouncilQualityGate()
        quality_result = gate.evaluate(report)
        loop = CouncilLearningLoop()
        candidates = loop.propose_learning(quality_result, report)
        if candidates:
            result = loop.apply_to_next_cycle(candidates[0].candidate_id)
            # Should not apply a pending candidate
            assert result.status == LearningStatus.PENDING_REVIEW

    def test_get_active_learning(self):
        report = _make_report(posts=[])
        gate = CouncilQualityGate()
        quality_result = gate.evaluate(report)
        loop = CouncilLearningLoop()
        candidates = loop.propose_learning(quality_result, report)
        active = loop.get_active_learning()
        assert len(active) == len(candidates)

    def test_get_pending_review(self):
        report = _make_report(posts=[])
        gate = CouncilQualityGate()
        quality_result = gate.evaluate(report)
        loop = CouncilLearningLoop()
        candidates = loop.propose_learning(quality_result, report)
        pending = loop.get_pending_review()
        assert len(pending) == len(candidates)

    def test_get_cycle_improvement_report(self):
        loop = CouncilLearningLoop()
        report = loop.get_cycle_improvement_report(last_n_cycles=6)
        assert "# Council Learning Loop" in report
        assert "Status Summary" in report

    def test_candidate_to_dict(self):
        candidate = CouncilLearningCandidate(
            learning="Test learning",
            trigger="Test trigger",
            dimension="source_grounding",
            severity="warning",
        )
        d = candidate.to_dict()
        assert d["learning"] == "Test learning"
        assert d["status"] == "Pending Review"


# ---------------------------------------------------------------------------
# R0 Gate tests
# ---------------------------------------------------------------------------


class TestR0Gate:
    """Tests for the R0 gate first-gate evaluation."""

    def test_good_question_passes(self):
        gate = R0Gate()
        result = gate.evaluate(
            "Should we allocate $2M capital to the AI governance initiative?",
            {"category": "finance"},
        )
        assert result.passed is True

    def test_too_short_fails(self):
        gate = R0Gate()
        result = gate.evaluate("hi")
        assert result.passed is False
        assert any("too short" in f for f in result.failures)

    def test_unsolvable_fails(self):
        gate = R0Gate()
        result = gate.evaluate("What is the meaning of life?")
        assert result.passed is False

    def test_overly_broad_fails(self):
        gate = R0Gate()
        result = gate.evaluate("How should we restructure everything about the company?")
        assert result.passed is False

    def test_single_word_fails_worth_it(self):
        gate = R0Gate()
        result = gate.evaluate("budget")
        assert result.passed is False

    def test_trivial_content_fails(self):
        gate = R0Gate()
        result = gate.evaluate("yes")
        assert result.passed is False

    def test_none_payload_passes(self):
        gate = R0Gate()
        result = gate.evaluate("Should we adopt a four-day work week?", None)
        assert result.passed is True

    def test_empty_payload_passes(self):
        gate = R0Gate()
        result = gate.evaluate("Should we adopt a four-day work week?", {})
        assert result.passed is True

    def test_all_checks_present(self):
        gate = R0Gate()
        result = gate.evaluate("Should we invest in renewable energy infrastructure?")
        assert R0Check.SOLVABLE in result.checks
        assert R0Check.SCOPED in result.checks
        assert R0Check.VALID in result.checks
        assert R0Check.WORTH_IT in result.checks

    def test_result_to_dict(self):
        gate = R0Gate()
        result = gate.evaluate("Should we allocate capital?")
        d = result.to_dict()
        assert "passed" in d
        assert "checks" in d
        assert "failures" in d
        assert "warnings" in d

    def test_contradictory_content_fails(self):
        gate = R0Gate()
        result = gate.evaluate("We should always never proceed with the plan")
        assert result.passed is False

    def test_finance_content_empty_payload_warns(self):
        gate = R0Gate()
        result = gate.evaluate("What is the ROI of this $5M investment?")
        assert any("Financial content" in w for w in result.warnings)


# ---------------------------------------------------------------------------
# Foundation Disclosure tests
# ---------------------------------------------------------------------------


class TestFoundationDisclosure:
    """Tests for the FoundationDisclosure module."""

    def test_generate_from_good_report(self):
        report = _make_good_report()
        disclosure = FoundationDisclosure()
        result = disclosure.generate_disclosure(report)
        assert isinstance(result, FoundationDisclosureResult)
        assert len(result.weakest_assumptions) >= 1
        assert len(result.invalidation_conditions) >= 1
        assert result.key_vulnerability != ""

    def test_generate_from_empty_report(self):
        report = _make_report(posts=[])
        disclosure = FoundationDisclosure()
        result = disclosure.generate_disclosure(report)
        assert isinstance(result, FoundationDisclosureResult)
        assert result.agreement_level == "unknown"
        assert result.challenge_severity == "none"

    def test_no_adversarial_detection(self):
        posts = [_make_post(agent="analyst"), _make_post(agent="validator")]
        report = _make_report(posts=posts)
        disclosure = FoundationDisclosure()
        result = disclosure.generate_disclosure(report)
        assert result.challenge_severity == "none"

    def test_strong_challenge_detection(self):
        posts = [
            _make_post(agent="analyst"),
            _make_post(
                agent="contrarian",
                body=(
                    "ADVERSARIAL CHALLENGE — Multiple risk factors, vulnerability, and failure concerns. "
                    "Critical issues include: failure modes in production, threat vectors from external actors, "
                    "danger of groupthink and echo chambers, weakness in validation logic, "
                    "challenge to the underlying assumptions, and a significant blocker to proceeding. "
                    "These challenges represent a real risk, problem, gap, and threat to the entire outcome. "
                    "The underlying issue creates exposure and the failure condition could be severe."
                ),
                lock_state=LockState.CHALLENGED,
            ),
        ]
        report = _make_report(posts=posts)
        disclosure = FoundationDisclosure()
        result = disclosure.generate_disclosure(report)
        assert result.challenge_severity == "strong"

    def test_assumption_risk_assessment(self):
        disclosure = FoundationDisclosure()
        risk = disclosure.assess_assumption_risk(
            "The market will definitely grow by 20% next year"
        )
        assert risk["risk_level"] == "high"
        assert len(risk["factors"]) > 0

    def test_assumption_risk_low(self):
        disclosure = FoundationDisclosure()
        risk = disclosure.assess_assumption_risk(
            "This analysis is based on publicly available data"
        )
        assert risk["risk_level"] == "low"

    def test_format_for_council_report(self):
        report = _make_good_report()
        disclosure = FoundationDisclosure()
        result = disclosure.generate_disclosure(report)
        md = disclosure.format_for_council_report(result)
        assert "## Foundation Disclosure" in md
        assert "Weakest Assumptions" in md
        assert "Invalidation Conditions" in md
        assert "Key Deliberation Vulnerability" in md

    def test_format_empty_disclosure(self):
        result = FoundationDisclosureResult()
        disclosure = FoundationDisclosure()
        md = disclosure.format_for_council_report(result)
        assert "## Foundation Disclosure" in md

    def test_result_to_dict(self):
        result = FoundationDisclosureResult(
            weakest_assumptions=["assumption1"],
            invalidation_conditions=["condition1"],
            key_vulnerability="vuln1",
        )
        d = result.to_dict()
        assert "weakest_assumptions" in d
        assert "key_vulnerability" in d

    def test_missing_perspectives_finance_without_analyst(self):
        posts = [_make_post(
            agent="analyst",
            body="The budget and investment ROI analysis suggests proceeding.",
        )]
        report = _make_report(posts=posts)
        disclosure = FoundationDisclosure()
        result = disclosure.generate_disclosure(report)
        assert any("financial-analyst" in p for p in result.missing_perspectives)
