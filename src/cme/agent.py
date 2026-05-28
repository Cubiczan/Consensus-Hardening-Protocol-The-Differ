"""MeshAgent base class.

A MeshAgent wraps a domain specialization and uses the cognitive mesh
protocol for structured reasoning. Subclasses implement expand and compress.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from cme.context import ContextEngine
from cme.protocol import (
    CognitiveMeshProtocol,
    ConfidenceLevel,
    ExpansionStep,
    ReasoningTrace,
)


@dataclass
class AgentCapability:
    domain: str
    produces: List[str] = field(default_factory=list)
    consumes: List[str] = field(default_factory=list)


@dataclass
class AgentTurnResult:
    agent: str
    trace: ReasoningTrace
    deltas_applied: List[str] = field(default_factory=list)
    outputs: Dict[str, Any] = field(default_factory=dict)
    handoff_notes: List[str] = field(default_factory=list)


class MeshAgent:
    def __init__(
        self,
        name: str,
        capability: AgentCapability,
        *,
        protocol: Optional[CognitiveMeshProtocol] = None,
    ) -> None:
        self.name = name
        self.capability = capability
        self.protocol = protocol or CognitiveMeshProtocol()

    def expand(self, problem: str, context: Dict[str, Any]) -> List[ExpansionStep]:
        raise NotImplementedError

    def compress(
        self,
        problem: str,
        expansion: List[ExpansionStep],
        context: Dict[str, Any],
    ) -> tuple[str, list, ConfidenceLevel, str, Dict[str, Any]]:
        raise NotImplementedError

    def act(
        self,
        problem: str,
        *,
        shared_context: Optional[ContextEngine] = None,
        cycles: int = 1,
    ) -> AgentTurnResult:
        ctx = {}
        if shared_context:
            ctx = shared_context.snapshot_for(self.name, problem, k=6)

        outputs_holder: Dict[str, Any] = {}

        def _compress(p, exp, c):
            rec, steps, conf, wwc, outs = self.compress(p, exp, c)
            outputs_holder.update(outs)
            return rec, steps, conf, wwc

        trace = self.protocol.run(
            problem,
            expansion_fn=self.expand,
            compression_fn=_compress,
            context=ctx,
            cycles=cycles,
        )

        handoff_notes = [
            f"confidence={trace.confidence.value}",
            f"produces={self.capability.produces}",
        ]
        failure = self.protocol.detect_failure_mode(trace)
        if failure:
            handoff_notes.append(f"warning:{failure}")

        return AgentTurnResult(
            agent=self.name,
            trace=trace,
            outputs=outputs_holder,
            handoff_notes=handoff_notes,
        )
