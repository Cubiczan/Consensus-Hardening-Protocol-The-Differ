"""Skill data structures for SKILLOPT-style optimization.

A skill is a portable markdown document of procedures, heuristics, tool
policies, and output rules. Skills are the *external state* of a frozen
LLM agent — analogous to weights in a neural network, but editable in
natural language via the SKILLOPT training loop.
"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class EditOp(str, Enum):
    """Types of textual edits the Curator can apply to a skill."""

    APPEND = "append"
    DELETE = "delete"
    REPLACE = "replace"


@dataclass
class SkillEdit:
    """A single proposed edit to a skill document.

    Bounded by the textual learning-rate budget L_t — the Curator can
    only propose up to L_t edits per optimization step.
    """

    op: EditOp
    target: str  # Section heading or line identifier
    content: str  # Content to append/delete/replace
    rationale: str = ""  # Why this edit is proposed
    utility_score: float = 0.5  # Expected improvement (0-1)
    edit_id: str = field(default_factory=lambda: uuid.uuid4().hex[:8])
    timestamp: float = field(default_factory=time.time)

    def to_dict(self) -> dict[str, Any]:
        return {
            "edit_id": self.edit_id,
            "op": self.op.value,
            "target": self.target,
            "content": self.content,
            "rationale": self.rationale,
            "utility_score": self.utility_score,
            "timestamp": self.timestamp,
        }


@dataclass
class SkillDocument:
    """A skill document — the external state of a frozen LLM agent.

    Skills are versioned markdown files (~300-2000 tokens) containing
    procedures, heuristics, tool policies, and output rules. The SKILLOPT
    loop optimizes this document through bounded edits gated by validation.
    """

    skill_id: str = ""
    domain: str = ""  # e.g. "finance", "critmin", "security"
    target_model: str = ""  # e.g. "gpt-5.5", "claude-4-opus"
    harness: str = ""  # e.g. "codex", "claude-code", "direct-chat"
    version: int = 1
    content: str = ""  # Full markdown content
    is_champion: bool = False  # Whether this is the current best
    epoch: int = 0  # Which training epoch produced this version
    validation_score: float = 0.0  # Score on D_sel (held-out selection split)
    metadata: dict[str, Any] = field(default_factory=dict)
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)

    @property
    def registry_key(self) -> str:
        """Unique key for the champion registry: (domain, target_model, harness)."""
        return f"{self.domain}/{self.target_model}/{self.harness}"

    def apply_edits(self, edits: list[SkillEdit]) -> str:
        """Apply a list of edits to this skill's content and return new content.

        This is the textual analog of a gradient step — bounded, structured,
        and reversible.
        """
        lines = self.content.split("\n")
        new_lines = list(lines)

        for edit in edits:
            target_lower = edit.target.lower()
            target_idx = -1

            # Find the target section or line
            for i, line in enumerate(new_lines):
                if target_lower in line.lower():
                    target_idx = i
                    break

            if target_idx == -1 and edit.op == EditOp.APPEND:
                # Target not found — append at end as new section
                new_lines.append("")
                new_lines.append(f"## {edit.target}")
                new_lines.append(edit.content)
            elif target_idx != -1:
                if edit.op == EditOp.APPEND:
                    # Insert after the target line
                    insert_pos = target_idx + 1
                    for content_line in edit.content.split("\n"):
                        new_lines.insert(insert_pos, content_line)
                        insert_pos += 1
                elif edit.op == EditOp.DELETE:
                    # Remove lines until next section header
                    delete_start = target_idx
                    delete_end = target_idx + 1
                    while delete_end < len(new_lines):
                        if new_lines[delete_end].startswith("#"):
                            break
                        delete_end += 1
                    new_lines = new_lines[:delete_start] + new_lines[delete_end:]
                elif edit.op == EditOp.REPLACE:
                    # Replace content between target and next section
                    replace_start = target_idx + 1
                    replace_end = replace_start
                    while replace_end < len(new_lines):
                        if new_lines[replace_end].startswith("#"):
                            break
                        replace_end += 1
                    replacement = [edit.content] if isinstance(edit.content, str) else edit.content.split("\n")
                    new_lines = new_lines[:replace_start] + replacement + new_lines[replace_end:]

        return "\n".join(new_lines)

    def to_dict(self) -> dict[str, Any]:
        return {
            "skill_id": self.skill_id,
            "domain": self.domain,
            "target_model": self.target_model,
            "harness": self.harness,
            "version": self.version,
            "is_champion": self.is_champion,
            "epoch": self.epoch,
            "validation_score": self.validation_score,
            "registry_key": self.registry_key,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "metadata": self.metadata,
        }


@dataclass
class SessionOutcome:
    """Recorded outcome of a single council session used for training.

    These are the "samples" in D_train, D_sel, D_test splits.
    """

    session_id: str
    domain: str
    topic: str
    skill_version: int
    reward: float  # 0.0-1.0 outcome score
    turns_count: int
    lock_state: str  # PROVISIONAL, CHALLENGED, VALIDATED, LOCKED, FAILED
    trace_id: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)
    timestamp: float = field(default_factory=time.time)

    def to_dict(self) -> dict[str, Any]:
        return {
            "session_id": self.session_id,
            "domain": self.domain,
            "topic": self.topic,
            "skill_version": self.skill_version,
            "reward": self.reward,
            "turns_count": self.turns_count,
            "lock_state": self.lock_state,
            "trace_id": self.trace_id,
            "timestamp": self.timestamp,
        }
