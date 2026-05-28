"""Cognitive Mesh Protocol.

Structured expansion/compression reasoning with grounding checks.
Each agent invocation produces a ReasoningTrace that captures the breathing
cycle, grounding verdicts, and final recommendation.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Callable, List, Optional


class ProblemType(str, Enum):
    STRATEGIC = "strategic"
    ANALYTICAL = "analytical"
    CREATIVE = "creative"
    TECHNICAL = "technical"


class ConfidenceLevel(str, Enum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


@dataclass
class ExpansionStep:
    label: str
    content: str
    uncertainty_flags: List[str] = field(default_factory=list)


@dataclass
class CompressionStep:
    label: str
    content: str


@dataclass
class GroundingCheck:
    claim: str
    source: str
    confidence: ConfidenceLevel
    risk_flag: Optional[str] = None


@dataclass
class ReasoningTrace:
    problem: str
    problem_type: ProblemType
    classification_rationale: str
    expansion: List[ExpansionStep] = field(default_factory=list)
    compression: List[CompressionStep] = field(default_factory=list)
    grounding: List[GroundingCheck] = field(default_factory=list)
    recommendation: str = ""
    confidence: ConfidenceLevel = ConfidenceLevel.MEDIUM
    what_would_change: str = ""
    cycle_count: int = 1

    def render(self) -> str:
        lines = [
            "## Problem Classification",
            f"{self.problem_type.value.title()} — {self.classification_rationale}",
            "",
            "## Reasoning Process",
        ]
        lines.append(f"### Expansion Cycle (count={self.cycle_count})")
        for i, step in enumerate(self.expansion, 1):
            lines.append(f"{i}. **{step.label}** — {step.content}")
            for flag in step.uncertainty_flags:
                lines.append(f"   - WARNING: {flag}")
        lines.append("")
        lines.append("### Compression Cycle")
        for i, step in enumerate(self.compression, 1):
            lines.append(f"{i}. **{step.label}** — {step.content}")
        lines.append("")
        lines.append("## Grounding Check")
        for g in self.grounding:
            risk = f" [RISK: {g.risk_flag}]" if g.risk_flag else ""
            lines.append(f"- {g.claim} :: source={g.source} confidence={g.confidence.value}{risk}")
        lines.append("")
        lines.append("## Final Recommendation")
        lines.append(f"{self.recommendation}")
        lines.append(f"Confidence: **{self.confidence.value}**")
        lines.append("")
        lines.append("## What Would Change This")
        lines.append(self.what_would_change or "—")
        return "\n".join(lines)


_RISK_PATTERNS = (
    "studies show",
    "research indicates",
    "it is well known",
    "industry standard is",
)


def detect_hallucination_risk(text: str) -> Optional[str]:
    import re
    lower = text.lower()
    for pat in _RISK_PATTERNS:
        if pat in lower:
            return f"unsourced authority phrase: '{pat}'"
    if re.search(r"\b(\d{2,3})%\b", text) and "estimated" not in lower and "assume" not in lower:
        return "specific percentage without stated source"
    return None


class CognitiveMeshProtocol:
    """Orchestrates the expansion/compression cycle for a single reasoning pass."""

    def __init__(self) -> None:
        self._failure_patterns = _RISK_PATTERNS

    def run(
        self,
        problem: str,
        *,
        expansion_fn: Callable,
        compression_fn: Callable,
        context: dict | None = None,
        cycles: int = 1,
    ) -> ReasoningTrace:
        problem_type = self._classify(problem)
        expansion = expansion_fn(problem, context or {})

        if isinstance(expansion, tuple):
            rec, comp, conf, wwc = compression_fn(problem, expansion, context or {})
        else:
            rec, comp, conf, wwc = compression_fn(problem, expansion, context or {})

        grounding = self._check_grounding(rec, comp)
        return ReasoningTrace(
            problem=problem,
            problem_type=problem_type,
            classification_rationale=self._classification_rationale(problem, problem_type),
            expansion=expansion if not isinstance(expansion, tuple) else expansion,
            compression=comp,
            grounding=grounding,
            recommendation=rec,
            confidence=conf,
            what_would_change=wwc,
            cycle_count=cycles,
        )

    def _classify(self, problem: str) -> ProblemType:
        lower = problem.lower()
        if any(w in lower for w in ("plan", "roadmap", "strategy", "direction", "vision")):
            return ProblemType.STRATEGIC
        if any(w in lower for w in ("calculate", "compute", "measure", "how much", "how many")):
            return ProblemType.ANALYTICAL
        if any(w in lower for w in ("design", "create", "build", "prototype")):
            return ProblemType.CREATIVE
        return ProblemType.TECHNICAL

    def _classification_rationale(self, problem: str, ptype: ProblemType) -> str:
        return f"Problem classified as {ptype.value} based on keyword analysis of the input."

    def _check_grounding(self, recommendation: str, compression: list) -> List[GroundingCheck]:
        checks: List[GroundingCheck] = []
        risk = detect_hallucination_risk(recommendation)
        if risk:
            checks.append(GroundingCheck(
                claim=recommendation[:100],
                source="heuristic",
                confidence=ConfidenceLevel.LOW,
                risk_flag=risk,
            ))
        if not checks:
            checks.append(GroundingCheck(
                claim="No grounding issues detected",
                source="heuristic",
                confidence=ConfidenceLevel.HIGH,
            ))
        return checks

    def detect_failure_mode(self, trace: ReasoningTrace) -> Optional[str]:
        if trace.confidence == ConfidenceLevel.LOW:
            return "LOW_CONFIDENCE"
        for g in trace.grounding:
            if g.risk_flag:
                return g.risk_flag
        return None
