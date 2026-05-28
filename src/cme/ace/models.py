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
    """Types of textual edits the Curator can apply to a skill.

    SkillOpt §3.3 defines 4 atomic edit operations:
      - append: Add new content at the end of a section (creates header if missing)
      - insert_after: Insert content after a specific target line (no new header)
      - replace: Replace content within a section
      - delete: Remove a section's content
    """

    APPEND = "append"
    INSERT_AFTER = "insert_after"
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

    Supports a protected slow-update section (§3.6) delimited by
    SLOW_UPDATE_START / SLOW_UPDATE_END markers that shields meta-update
    content from step-level edits.
    """

    # Slow-update markers (§3.6): protect meta-update content from edits
    SLOW_UPDATE_START = "<!-- SLOW_UPDATE_START -->"
    SLOW_UPDATE_END = "<!-- SLOW_UPDATE_END -->"

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

    @staticmethod
    def _find_protected_ranges(lines: list[str]) -> list[tuple[int, int]]:
        """Return list of (start, end) inclusive ranges for protected sections."""
        ranges: list[tuple[int, int]] = []
        i = 0
        while i < len(lines):
            if SkillDocument.SLOW_UPDATE_START in lines[i]:
                start = i
                i += 1
                while i < len(lines) and SkillDocument.SLOW_UPDATE_END not in lines[i]:
                    i += 1
                end = i if i < len(lines) else len(lines) - 1
                ranges.append((start, end))
            i += 1
        return ranges

    @staticmethod
    def _is_protected(line_idx: int, ranges: list[tuple[int, int]]) -> bool:
        """Check whether a line index falls inside any protected range."""
        for start, end in ranges:
            if start <= line_idx <= end:
                return True
        return False

    def has_protected_section(self) -> bool:
        """Check whether the content contains a slow-update protected section."""
        return (self.SLOW_UPDATE_START in self.content
                and self.SLOW_UPDATE_END in self.content)

    def get_protected_section(self) -> str:
        """Extract content between the slow-update markers.

        Returns the inner content (excluding the markers themselves).
        Returns empty string if no protected section exists.
        """
        try:
            start_marker = self.content.index(self.SLOW_UPDATE_START)
            end_marker = self.content.index(self.SLOW_UPDATE_END)
            inner_start = start_marker + len(self.SLOW_UPDATE_START)
            return self.content[inner_start:end_marker].strip("\n")
        except ValueError:
            return ""

    def set_protected_section(self, content: str) -> str:
        """Replace content between the slow-update markers.

        Returns the new full document content. If no markers exist, returns
        the content unchanged.
        """
        if not self.has_protected_section():
            return self.content
        start_marker = self.SLOW_UPDATE_START
        end_marker = self.SLOW_UPDATE_END
        new_content = f"{start_marker}\n{content}\n{end_marker}"
        # Replace everything from start marker to end marker (inclusive)
        idx_start = self.content.index(start_marker)
        idx_end = self.content.index(end_marker) + len(end_marker)
        return self.content[:idx_start] + new_content + self.content[idx_end:]

    def apply_edits(self, edits: list[SkillEdit]) -> str:
        """Apply a list of edits to this skill's content and return new content.

        This is the textual analog of a gradient step — bounded, structured,
        and reversible. Edits targeting lines inside the protected slow-update
        section (§3.6) are silently skipped.
        """
        lines = self.content.split("\n")
        new_lines = list(lines)

        # Pre-compute protected ranges so edits cannot modify protected content
        protected_ranges = self._find_protected_ranges(new_lines)

        for edit in edits:
            target_lower = edit.target.lower()
            target_idx = -1

            # Find the target section or line
            for i, line in enumerate(new_lines):
                if target_lower in line.lower():
                    target_idx = i
                    break

            if target_idx == -1:
                if edit.op == EditOp.APPEND:
                    # Target not found — append at end as new section
                    new_lines.append("")
                    new_lines.append(f"## {edit.target}")
                    new_lines.append(edit.content)
            elif self._is_protected(target_idx, protected_ranges):
                # Skip edits targeting the protected section (§3.6)
                logger = __import__("logging").getLogger(__name__)
                logger.debug(
                    "Skipping edit on protected section: target=%s op=%s",
                    edit.target, edit.op.value,
                )
                continue
            else:
                if edit.op == EditOp.APPEND:
                    # Insert after the target line (creates new section if needed)
                    insert_pos = target_idx + 1
                    for content_line in edit.content.split("\n"):
                        new_lines.insert(insert_pos, content_line)
                        insert_pos += 1
                elif edit.op == EditOp.INSERT_AFTER:
                    # Insert content after the target line without creating a header
                    insert_pos = target_idx + 1
                    for content_line in edit.content.split("\n"):
                        new_lines.insert(insert_pos, content_line)
                        insert_pos += 1
                elif edit.op == EditOp.DELETE:
                    # Remove lines until next section header or protected marker
                    delete_start = target_idx
                    delete_end = target_idx + 1
                    while delete_end < len(new_lines):
                        line = new_lines[delete_end]
                        if line.startswith("#") or self._is_protected(delete_end, protected_ranges):
                            break
                        delete_end += 1
                    new_lines = new_lines[:delete_start] + new_lines[delete_end:]
                elif edit.op == EditOp.REPLACE:
                    # Replace content between target and next section or protected marker
                    replace_start = target_idx + 1
                    replace_end = replace_start
                    while replace_end < len(new_lines):
                        line = new_lines[replace_end]
                        if line.startswith("#") or self._is_protected(replace_end, protected_ranges):
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
