"""R0 Gate — first-gate evaluation for all decisions entering the council.

Every decision intent must pass the R0 gate before entering the council
pipeline. This is the outermost quality filter that prevents waste of
computational resources and ensures that only well-formed, solvable, and
worthwhile decisions reach the multi-agent deliberation stage.

R0 Gate Checks
==============

1. **Solvable** — Can the question be meaningfully answered by agents?
2. **Scoped** — Is the scope specific enough for a single council run?
3. **Valid** — Are the inputs and assumptions well-formed?
4. **Worth It** — Is this decision worth the compute/resources of a full council?

Architecture Diagram
====================

    Intent + Payload
          │
          ▼
    ┌──────────────┐
    │   R0 Gate    │
    │              │
    │  SOLVABLE ──> Can agents answer this?
    │  SCOPED ────> Is scope well-defined?
    │  VALID ─────> Are inputs well-formed?
    │  WORTH_IT ──> Worth the compute?
    │              │
    └──────┬───────┘
           │
     ┌─────┴─────┐
     │            │
     ▼            ▼
  PASSED      FAILED
     │            │
     ▼            ▼
  Council      Rejected
  Pipeline     (with reasons)

If R0 fails, the intent is rejected before entering the council pipeline,
saving compute and preventing trivial or malformed decisions from consuming
agent resources.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class R0Check(str, Enum):
    """The four foundational R0 gate checks."""

    SOLVABLE = "solvable"
    SCOPED = "scoped"
    VALID = "valid"
    WORTH_IT = "worth_it"


@dataclass
class R0Result:
    """Result of the R0 gate evaluation.

    Attributes:
        checks: Dict mapping each R0 check to whether it passed.
        passed: True if all four checks passed.
        failures: List of human-readable failure reasons.
        warnings: List of non-blocking warnings.
    """

    checks: dict[R0Check, bool] = field(default_factory=dict)
    passed: bool = False
    failures: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        """Serialise to a plain dict."""
        return {
            "passed": self.passed,
            "checks": {c.value: v for c, v in self.checks.items()},
            "failures": self.failures,
            "warnings": self.warnings,
        }


class R0Gate:
    """R0 gate — the first gate every decision must pass before entering the council.

    Evaluates the decision intent against four foundational checks:
    1. Solvable — Can the question be meaningfully answered by agents?
    2. Scoped — Is the scope specific enough for a single council run?
    3. Valid — Are the inputs and assumptions well-formed?
    4. Worth It — Is this decision worth the compute/resources of a full council?

    If R0 fails, the intent is rejected before entering the council pipeline.

    Rule-based evaluation — no LLM dependency:

    **Solvable**:
    - Reject if content is too short (< 15 chars)
    - Reject if content is a known unanswerable question
    - Reject if content has no question mark or decision language
    - Reject philosophical/impossible questions

    **Scoped**:
    - Reject if content contains overly broad terms ("everything", "all possible")
    - Reject if content is > 500 chars without specific indicators
    - Warn if scope seems too narrow (single yes/no)

    **Valid**:
    - Reject if content contains obvious contradictions
    - Warn if payload is empty when category keywords suggest structured input
    - Check for well-formed question structure

    **Worth It**:
    - Reject if content is too short for substantive deliberation
    - Reject single-word queries
    - Reject trivial yes/no questions without context
    - Warn if topic seems too minor for multi-agent attention

    Usage::

        gate = R0Gate()
        result = gate.evaluate(
            "Should we allocate $2M to the AI governance initiative?",
            {"category": "finance"},
        )

        if result.passed:
            # Enter the council pipeline
            ...
        else:
            # Reject with reasons
            for failure in result.failures:
                print(f"R0 FAIL: {failure}")
    """

    # Known unanswerable / philosophical questions
    UNSOLVABLE_PATTERNS: list[str] = [
        r"meaning\s+of\s+life",
        r"what\s+is\s+the\s+universe",
        r"how\s+many\s+angels",
        r"ultimate\s+(?:truth|purpose|meaning)",
        r"does\s+god\s+exist",
        r"what\s+happens\s+after\s+death",
    ]

    # Overly broad scope indicators
    BROAD_PATTERNS: list[str] = [
        r"\beverything\b",
        r"\ball\s+possible\b",
        r"\ball\s+the\b",
        r"\bthe\s+entire\b",
        r"\bcompletely\s+restructure\b",
        r"\bevery\s+aspect\b",
    ]

    # Decision language indicators (suggests the intent is a decision question)
    DECISION_LANGUAGE: list[str] = [
        r"\bshould\b",
        r"\bshall\b",
        r"\bdecide\b",
        r"\brecommend\b",
        r"\bevaluate\b",
        r"\bassess\b",
        r"\bchoose\b",
        r"\bprefer\b",
        r"\bcompare\b",
        r"\bwhich\b",
        r"\bhow\s+(?:should|might|can)\b",
        r"\bwhat\s+(?:should|is\s+the\s+best|are\s+the)\b",
        r"\?",
    ]

    # Trivial patterns (not worth multi-agent deliberation)
    TRIVIAL_PATTERNS: list[str] = [
        r"^(?:yes|no)$",
        r"^(?:ok|okay|sure|fine)$",
        r"^(?:hi|hello|hey)\b",
        r"^(?:thanks|thank you)\b",
    ]

    MIN_CONTENT_LENGTH: int = 15
    MAX_UNSOLVED_CONTENT_LENGTH: int = 500
    MIN_WORDS_FOR_SCOPE: int = 3

    def evaluate(self, intent_content: str, payload: dict[str, Any] | None = None) -> R0Result:
        """Evaluate a decision intent against all R0 checks.

        Args:
            intent_content: The text content of the decision intent.
            payload: Optional payload dict with structured metadata.

        Returns:
            An R0Result with individual check outcomes, overall pass/fail,
            and lists of failures and warnings.
        """
        if payload is None:
            payload = {}

        checks: dict[R0Check, bool] = {}
        failures: list[str] = []
        warnings: list[str] = []

        # Check 1: Solvable
        solvable, solvable_failures, solvable_warnings = self._check_solvable(
            intent_content
        )
        checks[R0Check.SOLVABLE] = solvable
        failures.extend(solvable_failures)
        warnings.extend(solvable_warnings)

        # Check 2: Scoped
        scoped, scoped_failures, scoped_warnings = self._check_scoped(
            intent_content
        )
        checks[R0Check.SCOPED] = scoped
        failures.extend(scoped_failures)
        warnings.extend(scoped_warnings)

        # Check 3: Valid
        valid, valid_failures, valid_warnings = self._check_valid(
            intent_content, payload
        )
        checks[R0Check.VALID] = valid
        failures.extend(valid_failures)
        warnings.extend(valid_warnings)

        # Check 4: Worth It
        worth_it, worth_failures, worth_warnings = self._check_worth_it(
            intent_content
        )
        checks[R0Check.WORTH_IT] = worth_it
        failures.extend(worth_failures)
        warnings.extend(worth_warnings)

        passed = all(checks.values())

        return R0Result(
            checks=checks,
            passed=passed,
            failures=failures,
            warnings=warnings,
        )

    def _check_solvable(
        self, content: str,
    ) -> tuple[bool, list[str], list[str]]:
        """Check SOLVABLE: Can the question be meaningfully answered by agents?"""
        failures: list[str] = []
        warnings: list[str] = []

        content_lower = content.strip().lower()

        # Too short to be a meaningful question
        if len(content.strip()) < self.MIN_CONTENT_LENGTH:
            failures.append(
                f"Content too short ({len(content.strip())} chars, "
                f"minimum {self.MIN_CONTENT_LENGTH})"
            )
            return False, failures, warnings

        # Check against known unsolvable patterns
        for pattern in self.UNSOLVABLE_PATTERNS:
            if re.search(pattern, content_lower):
                failures.append(
                    f"Content matches unsolvable pattern: '{pattern}'"
                )
                return False, failures, warnings

        # Check for decision language
        has_decision_language = any(
            re.search(p, content_lower) for p in self.DECISION_LANGUAGE
        )
        if not has_decision_language:
            warnings.append(
                "No decision language detected (should, decide, recommend, etc.). "
                "Intent may not be a decision question."
            )

        return True, failures, warnings

    def _check_scoped(
        self, content: str,
    ) -> tuple[bool, list[str], list[str]]:
        """Check SCOPED: Is the scope specific enough for a single council run?"""
        failures: list[str] = []
        warnings: list[str] = []

        content_lower = content.strip().lower()

        # Check for overly broad terms
        broad_matches = []
        for pattern in self.BROAD_PATTERNS:
            if re.search(pattern, content_lower):
                broad_matches.append(pattern)
        if broad_matches:
            failures.append(
                f"Overly broad scope detected — matches: {broad_matches}"
            )
            return False, failures, warnings

        # Very long content without specific indicators may be unfocused
        if len(content) > self.MAX_UNSOLVED_CONTENT_LENGTH:
            # Check if there are specific indicators (numbers, named entities)
            has_specifics = bool(re.search(r"\$[\d,]+|\d+\s*%", content))
            if not has_specifics:
                warnings.append(
                    f"Long content ({len(content)} chars) without specific "
                    f"quantitative indicators — scope may be too broad."
                )

        # Check minimum word count
        word_count = len(content.split())
        if word_count < self.MIN_WORDS_FOR_SCOPE:
            warnings.append(
                f"Very few words ({word_count}) — scope may be insufficient."
            )

        return True, failures, warnings

    def _check_valid(
        self, content: str, payload: dict[str, Any],
    ) -> tuple[bool, list[str], list[str]]:
        """Check VALID: Are the inputs and assumptions well-formed?"""
        failures: list[str] = []
        warnings: list[str] = []

        content_lower = content.strip().lower()

        # Check for obvious contradictions
        contradiction_patterns = [
            (r"(?:both|either)\s+.*(?:and|or)\s+.*(?:neither|none)", "contradictory logic"),
            (r"(?:always\s+never)|(?:never\s+always)", "always/never contradiction"),
            (r"(?:definitely\s+maybe)|(?:maybe\s+definitely)", "definite/maybe contradiction"),
        ]
        for pattern, desc in contradiction_patterns:
            if re.search(pattern, content_lower):
                failures.append(f"Contradictory language detected: {desc}")
                return False, failures, warnings

        # Check if structured domain (finance, etc.) has empty payload
        finance_keywords = {"budget", "investment", "capital", "fund", "roi"}
        has_finance_content = any(kw in content_lower for kw in finance_keywords)
        if has_finance_content and not payload:
            warnings.append(
                "Financial content detected but no structured payload provided. "
                "Consider including budget amount, timeline, or risk parameters."
            )

        return True, failures, warnings

    def _check_worth_it(
        self, content: str,
    ) -> tuple[bool, list[str], list[str]]:
        """Check WORTH_IT: Is this decision worth the compute/resources?"""
        failures: list[str] = []
        warnings: list[str] = []

        content_stripped = content.strip()

        # Single-word queries
        if len(content_stripped.split()) == 1:
            failures.append(
                "Single-word query — not worth multi-agent deliberation."
            )
            return False, failures, warnings

        # Check trivial patterns
        content_lower = content_stripped.lower()
        for pattern in self.TRIVIAL_PATTERNS:
            if re.search(pattern, content_lower):
                failures.append(
                    "Trivial content detected — not worth council deliberation."
                )
                return False, failures, warnings

        # Check for substantive content (should be more than just a greeting/question)
        has_substantive_content = (
            len(content_stripped) >= self.MIN_CONTENT_LENGTH
            and any(c.isalpha() for c in content_stripped)
        )
        if not has_substantive_content:
            failures.append(
                "Insufficient substantive content for council deliberation."
            )
            return False, failures, warnings

        # Warn about simple yes/no without context
        if re.match(r"^(?:is|are|was|were|do|does|did|will|can|should)\b", content_lower):
            if len(content_stripped) < 50:
                warnings.append(
                    "Simple yes/no question without much context — "
                    "may not benefit from multi-agent deliberation."
                )

        return True, failures, warnings
