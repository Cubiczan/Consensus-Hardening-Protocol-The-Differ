"""Rejected-edit buffer — adversarial memory from failed validation gates.

When a candidate skill fails the D_sel validation gate, the proposed edits
are retained as negative feedback. This buffer is fed back into the Reflector
so it actively avoids repeating past mistakes — turning SKILLOPT's
"negative samples" into CHP's adversarial signal via the TriangulationRunner.

Reference: SKILLOPT §3.5 — rejected-edit buffer as negative feedback
  for future reflection calls.
"""

from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from cme.ace.models import EditOp, SkillDocument, SkillEdit

logger = logging.getLogger(__name__)


@dataclass
class RejectedEdit:
    """A rejected edit with context for adversarial memory.

    Stores the edit, the reason for rejection, and the session context
    so the optimizer can learn from past failures.
    """

    edit: SkillEdit
    rejection_reason: str
    candidate_score: float
    champion_score: float
    domain: str = ""
    skill_version: int = 0
    epoch: int = 0
    timestamp: float = field(default_factory=time.time)
    times_referenced: int = 0  # How many times this was used to avoid repeat

    def to_dict(self) -> dict[str, Any]:
        return {
            "edit": self.edit.to_dict(),
            "rejection_reason": self.rejection_reason,
            "candidate_score": self.candidate_score,
            "champion_score": self.champion_score,
            "domain": self.domain,
            "skill_version": self.skill_version,
            "epoch": self.epoch,
            "timestamp": self.timestamp,
            "times_referenced": self.times_referenced,
        }


class RejectedEditBuffer:
    """Buffer of rejected edits serving as adversarial memory.

    The buffer feeds into the Reflector/optimizer model to prevent
    repeated failed edit patterns. This is CHP's adaptation of SKILLOPT's
    rejected-edit buffer, integrated with the existing TriangulationRunner
    adversary.
    """

    def __init__(self, max_size: int = 1000, storage_path: str | Path = "data/rejected_edits.jsonl") -> None:
        self.max_size = max_size
        self.storage_path = Path(storage_path)
        self._buffer: list[RejectedEdit] = []
        self._load()

    def add(self, rejected: RejectedEdit) -> None:
        """Add a rejected edit to the buffer."""
        self._buffer.append(rejected)
        if len(self._buffer) > self.max_size:
            # Evict oldest, least-referenced entries
            self._buffer.sort(key=lambda r: (r.times_referenced, r.timestamp))
            self._buffer = self._buffer[-self.max_size :]
        self._save()
        logger.debug(
            "Rejected edit added: %s (%s) — buffer size: %d",
            rejected.edit.op.value, rejected.edit.target,
            len(self._buffer),
        )

    def add_rejected_edits(
        self,
        edits: list[SkillEdit],
        rejection_reason: str,
        candidate_score: float,
        champion_score: float,
        domain: str = "",
        skill_version: int = 0,
        epoch: int = 0,
    ) -> None:
        """Add multiple rejected edits at once (from a failed validation gate)."""
        for edit in edits:
            rejected = RejectedEdit(
                edit=edit,
                rejection_reason=rejection_reason,
                candidate_score=candidate_score,
                champion_score=champion_score,
                domain=domain,
                skill_version=skill_version,
                epoch=epoch,
            )
            self.add(rejected)

    def get_context_for_domain(self, domain: str, limit: int = 20) -> list[RejectedEdit]:
        """Get rejected edits relevant to a specific domain.

        Returns the most recent rejected edits for the given domain,
        sorted by timestamp (most recent first). Used by the optimizer
        to avoid repeating past mistakes.
        """
        domain_edits = [r for r in self._buffer if r.domain == domain]
        # Mark as referenced
        for r in domain_edits[:limit]:
            r.times_referenced += 1
        return sorted(domain_edits, key=lambda r: r.timestamp, reverse=True)[:limit]

    def get_all(self) -> list[RejectedEdit]:
        """Return all rejected edits."""
        return list(self._buffer)

    def get_summary(self) -> dict[str, Any]:
        """Get summary statistics of the rejected edit buffer."""
        if not self._buffer:
            return {"total": 0, "domains": {}, "op_counts": {}}

        domains: dict[str, int] = {}
        op_counts: dict[str, int] = {}
        for r in self._buffer:
            domains[r.domain] = domains.get(r.domain, 0) + 1
            op_counts[r.edit.op.value] = op_counts.get(r.edit.op.value, 0) + 1

        return {
            "total": len(self._buffer),
            "domains": domains,
            "op_counts": op_counts,
            "avg_score_gap": (
                sum(r.champion_score - r.candidate_score for r in self._buffer)
                / len(self._buffer)
                if self._buffer else 0.0
            ),
        }

    def format_for_optimizer(self, domain: str, limit: int = 20) -> str:
        """Format rejected edits as context for the optimizer prompt.

        This produces a natural-language summary that the Reflector/
        optimizer model receives to avoid repeating failed patterns.
        """
        rejections = self.get_context_for_domain(domain, limit)
        if not rejections:
            return ""

        lines = [
            "## Previously Rejected Edits (AVOID repeating these patterns)",
            "",
        ]
        for i, r in enumerate(rejections, 1):
            lines.append(
                f"{i}. [{r.edit.op.value.upper()}] '{r.edit.target}' "
                f"(score gap: {r.candidate_score:.3f} vs {r.champion_score:.3f}) "
                f"— {r.rejection_reason}"
            )
            if r.edit.rationale:
                lines.append(f"   Rationale was: {r.edit.rationale}")
        lines.append("")
        return "\n".join(lines)

    def _save(self) -> None:
        """Persist buffer to JSONL file."""
        self.storage_path.parent.mkdir(parents=True, exist_ok=True)
        with open(self.storage_path, "w", encoding="utf-8") as f:
            for r in self._buffer:
                f.write(json.dumps(r.to_dict()) + "\n")

    def _load(self) -> None:
        """Load buffer from JSONL file."""
        if not self.storage_path.exists():
            return
        try:
            with open(self.storage_path, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    data = json.loads(line)
                    edit_data = data.pop("edit", {})
                    edit = SkillEdit(
                        op=EditOp(edit_data.get("op", "append")),
                        target=edit_data.get("target", ""),
                        content=edit_data.get("content", ""),
                        rationale=edit_data.get("rationale", ""),
                        utility_score=edit_data.get("utility_score", 0.5),
                        edit_id=edit_data.get("edit_id", ""),
                        timestamp=edit_data.get("timestamp", 0),
                    )
                    rejected = RejectedEdit(
                        edit=edit,
                        rejection_reason=data.get("rejection_reason", ""),
                        candidate_score=data.get("candidate_score", 0),
                        champion_score=data.get("champion_score", 0),
                        domain=data.get("domain", ""),
                        skill_version=data.get("skill_version", 0),
                        epoch=data.get("epoch", 0),
                        timestamp=data.get("timestamp", 0),
                        times_referenced=data.get("times_referenced", 0),
                    )
                    self._buffer.append(rejected)
            logger.info("Loaded %d rejected edits from %s", len(self._buffer), self.storage_path)
        except Exception as e:
            logger.warning("Failed to load rejected edits: %s", e)
