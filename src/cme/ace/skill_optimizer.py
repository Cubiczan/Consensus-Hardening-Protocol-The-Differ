"""SKILLOPT-style skill optimizer — the core training loop.

Implements the full SKILLOPT optimization cycle (Yang et al., 2026):
  1. Rollout batch on D_train with current skill
  2. Failure/success analysis by optimizer model
  3. Bounded textual edits (learning-rate budget L_t)
  4. Batch merge of proposed edits
  5. Validation gate on held-out D_sel (strict improvement required)
  6. Rejected edits → adversarial memory buffer
  7. Epoch-wise slow/meta update (momentum)

This loop runs on top of CHP's existing ACE subsystem and maps onto
the CHP lock state machine:
  - PROVISIONAL → candidate skill under optimization
  - PROVISIONAL_LOCK → passed D_sel validation gate
  - LOCKED → promoted to champion registry
"""

from __future__ import annotations

import logging
import math
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Optional

from cme.ace.champion_registry import ChampionRegistry
from cme.ace.models import (
    EditOp,
    SessionOutcome,
    SkillDocument,
    SkillEdit,
)
from cme.ace.rejected_edit_buffer import RejectedEditBuffer
from cme.ace.session_splitter import DataSplit, SessionSplitter

logger = logging.getLogger(__name__)


class LearningRateSchedule(str, Enum):
    """Schedules for the textual edit budget L_t."""

    CONSTANT = "constant"
    LINEAR = "linear"
    COSINE = "cosine"
    AUTONOMOUS = "autonomous"


class EditMode(str, Enum):
    """SkillOpt §3.4 — patch mode (localized edits) vs rewrite mode (full rewrite)."""

    PATCH = "patch"
    REWRITE = "rewrite"


@dataclass
class OptimizationStep:
    """Record of a single SKILLOPT optimization step."""

    step_id: int
    epoch: int
    domain: str
    registry_key: str
    edits_proposed: int
    edits_applied: int  # After budget clipping
    edit_budget_l: int
    candidate_score: float
    champion_score: float
    promoted: bool
    rejection_reason: str = ""
    duration_seconds: float = 0.0
    timestamp: float = field(default_factory=time.time)

    def to_dict(self) -> dict[str, Any]:
        return {
            "step_id": self.step_id,
            "epoch": self.epoch,
            "domain": self.domain,
            "registry_key": self.registry_key,
            "edits_proposed": self.edits_proposed,
            "edits_applied": self.edits_applied,
            "edit_budget_l": self.edit_budget_l,
            "candidate_score": self.candidate_score,
            "champion_score": self.champion_score,
            "promoted": self.promoted,
            "rejection_reason": self.rejection_reason,
            "duration_seconds": self.duration_seconds,
        }


@dataclass
class TrainingConfig:
    """Configuration for the SKILLOPT training loop."""

    # Data split ratios
    train_ratio: float = 0.70
    sel_ratio: float = 0.15

    # Edit budget (textual learning rate)
    edit_budget_l_max: int = 4  # Max edits per step (SKILLOPT default: 4)
    edit_budget_l_floor: int = 2  # Minimum edits per step
    lr_schedule: LearningRateSchedule = LearningRateSchedule.COSINE

    # Training loop
    max_epochs: int = 4  # SKILLOPT default: 4
    rollout_batch_size: int = 40
    reflection_minibatch_size: int = 8
    accumulation_batches: int = 1  # §3.2: rollout batches to accumulate before reflecting

    # Edit mode (§3.4)
    edit_mode: EditMode = EditMode.PATCH

    # Validation gate
    strict_validation: bool = True  # Reject ties (SKILLOPT default)

    # Epoch meta-update
    meta_update_tasks: int = 20  # Tasks sampled per epoch for meta-update
    enable_meta_update: bool = True

    # Optimizer
    optimizer_model: str = "gpt-5.5"  # Separate frontier model as optimizer

    # Misc
    seed: int = 42


@dataclass
class TrainingReport:
    """Summary report of a completed training run."""

    domain: str
    registry_key: str
    total_epochs: int
    total_steps: int
    promotions: int
    rejections: int
    final_champion_score: float
    initial_champion_score: float
    improvement: float
    steps: list[OptimizationStep] = field(default_factory=list)

    def to_markdown(self) -> str:
        lines = [
            f"# SKILLOPT Training Report — {self.domain}",
            "",
            f"| Metric | Value |",
            f"|--------|-------|",
            f"| Domain | {self.domain} |",
            f"| Registry Key | `{self.registry_key}` |",
            f"| Epochs | {self.total_epochs} |",
            f"| Steps | {self.total_steps} |",
            f"| Promotions | {self.promotions} |",
            f"| Rejections | {self.rejections} |",
            f"| Initial Score | {self.initial_champion_score:.4f} |",
            f"| Final Score | {self.final_champion_score:.4f} |",
            f"| Improvement | {'+' if self.improvement >= 0 else ''}{self.improvement:.4f} |",
            "",
        ]
        if self.steps:
            lines.append("## Step History")
            lines.append("")
            lines.append("| Step | Epoch | Edits | Budget | Candidate | Champion | Promoted |")
            lines.append("|------|-------|-------|--------|-----------|----------|----------|")
            for s in self.steps:
                lines.append(
                    f"| {s.step_id} | {s.epoch} | {s.edits_applied}/{s.edits_proposed} "
                    f"| {s.edit_budget_l} | {s.candidate_score:.4f} "
                    f"| {s.champion_score:.4f} | {'YES' if s.promoted else 'NO'} |"
                )
        return "\n".join(lines)


class SkillOptimizer:
    """SKILLOPT-style skill optimizer for CHP's ACE subsystem.

    The optimizer treats the skill document as the external state of a
    frozen LLM agent and applies bounded, gated textual edits through
    a disciplined training loop with validation, momentum, and adversarial
    memory.

    Maps onto CHP's existing lock state machine:
      PROVISIONAL  → candidate skill being optimized
      PROVISIONAL_LOCK → passed D_sel validation gate
      LOCKED       → promoted to champion registry
    """

    def __init__(
        self,
        config: TrainingConfig | None = None,
        champion_registry: ChampionRegistry | None = None,
        rejected_buffer: RejectedEditBuffer | None = None,
        rollout_fn: Callable | None = None,
        reflect_fn: Callable | None = None,
        evaluate_fn: Callable | None = None,
    ) -> None:
        self.config = config or TrainingConfig()
        self.registry = champion_registry or ChampionRegistry()
        self.rejected_buffer = rejected_buffer or RejectedEditBuffer()
        self.splitter = SessionSplitter(
            train_ratio=self.config.train_ratio,
            sel_ratio=self.config.sel_ratio,
            seed=self.config.seed,
        )

        # Pluggable functions for production use
        self._rollout_fn = rollout_fn
        self._reflect_fn = reflect_fn
        self._evaluate_fn = evaluate_fn

        self._step_counter = 0
        self._current_step: Optional[OptimizationStep] = None

    def compute_edit_budget(self, step: int, total_steps: int) -> int:
        """Compute the textual learning-rate budget L_t for a given step.

        Follows SKILLOPT's schedule options:
          - CONSTANT: always L_max
          - LINEAR: linear decay from L_max to L_floor
          - COSINE: cosine decay from L_max to L_floor (default)
          - AUTONOMOUS: optimizer decides (placeholder)
        """
        L_max = self.config.edit_budget_l_max
        L_floor = self.config.edit_budget_l_floor

        if self.config.lr_schedule == LearningRateSchedule.CONSTANT:
            return L_max
        elif self.config.lr_schedule == LearningRateSchedule.LINEAR:
            progress = step / max(total_steps, 1)
            return max(L_floor, int(L_max - (L_max - L_floor) * progress))
        elif self.config.lr_schedule == LearningRateSchedule.COSINE:
            progress = step / max(total_steps, 1)
            return max(
                L_floor,
                int(L_floor + (L_max - L_floor) * 0.5 * (1 + math.cos(math.pi * progress))),
            )
        else:  # AUTONOMOUS
            return L_max  # Fallback

    def propose_edits(
        self,
        skill: SkillDocument,
        train_outcomes: list[SessionOutcome],
        domain: str,
    ) -> list[SkillEdit]:
        """Propose edits based on training rollout outcomes.

        In production, this calls the optimizer model (frontier LLM) to
        analyze failures/successes and propose structured edits. The edits
        are then clipped to the edit budget L_t.

        For now, returns a placeholder that the production optimizer will
        replace with actual LLM-generated edits.
        """
        if self._reflect_fn:
            return self._reflect_fn(skill, train_outcomes, domain)

        # Placeholder: in production, this calls the optimizer model
        # to analyze failures and propose edits
        return []

    def merge_edits(self, edits: list[SkillEdit], budget: int) -> list[SkillEdit]:
        """Merge and clip edits to the textual learning-rate budget.

        Follows SKILLOPT's batch merge: deduplicate, rank by utility,
        and clip to top L_t edits.
        """
        # Deduplicate by (op, target)
        seen: set[tuple[str, str]] = set()
        unique_edits: list[SkillEdit] = []
        for edit in edits:
            key = (edit.op.value, edit.target)
            if key not in seen:
                seen.add(key)
                unique_edits.append(edit)

        # Rank by utility score (descending)
        unique_edits.sort(key=lambda e: e.utility_score, reverse=True)

        # Clip to budget
        clipped = unique_edits[:budget]
        logger.info(
            "Edit merge: %d proposed → %d unique → %d clipped to budget L=%d",
            len(edits), len(unique_edits), len(clipped), budget,
        )
        return clipped

    def merge_edits_hierarchical(
        self,
        failure_edits: list[SkillEdit],
        success_edits: list[SkillEdit],
        budget: int,
    ) -> list[SkillEdit]:
        """Hierarchical failure-priority merge (§3.3).

        Analyzes failure and success edits separately, deduplicates each
        group, removes success edits that conflict with failure edits (same
        target), then allocates ~70% of budget to failure edits and ~30% to
        success edits (failure takes priority).

        Args:
            failure_edits: Edits derived from failure-case analysis.
            success_edits: Edits derived from success-case reinforcement.
            budget: Total edit budget L_t.

        Returns:
            Combined list of SkillEdit clipped to budget.
        """
        # Deduplicate failure edits by target (keep highest utility)
        failure_seen: dict[str, SkillEdit] = {}
        for edit in failure_edits:
            if edit.target not in failure_seen or edit.utility_score > failure_seen[edit.target].utility_score:
                failure_seen[edit.target] = edit
        deduped_failures = list(failure_seen.values())

        # Deduplicate success edits by target (keep highest utility)
        success_seen: dict[str, SkillEdit] = {}
        for edit in success_edits:
            if edit.target not in success_seen or edit.utility_score > success_seen[edit.target].utility_score:
                success_seen[edit.target] = edit

        # Remove success edits that conflict with failure edits (same target)
        filtered_successes = [
            edit for edit in success_seen.values()
            if edit.target not in failure_seen
        ]

        # Rank each group by utility (descending)
        deduped_failures.sort(key=lambda e: e.utility_score, reverse=True)
        filtered_successes.sort(key=lambda e: e.utility_score, reverse=True)

        # Allocate ~70% budget to failures, ~30% to successes
        failure_budget = max(1, int(budget * 0.7))
        success_budget = max(1, budget - failure_budget)

        selected_failures = deduped_failures[:failure_budget]
        selected_successes = filtered_successes[:success_budget]

        merged = selected_failures + selected_successes
        logger.info(
            "Hierarchical merge: %d failures → %d, %d successes → %d, "
            "budget=%d (failure=%d, success=%d), final=%d",
            len(failure_edits), len(selected_failures),
            len(success_edits), len(selected_successes),
            budget, failure_budget, success_budget, len(merged),
        )
        return merged

    def rewrite_skill(
        self,
        skill: SkillDocument,
        suggestions: str,
    ) -> SkillDocument:
        """Rewrite mode (§3.4): generate a complete new skill from suggestions.

        Instead of applying localized patches, the optimizer model generates
        a full replacement of the skill document based on the accumulated
        suggestions text. The protected slow-update section (§3.6) is
        preserved across rewrites.

        Args:
            skill: Current skill document to rewrite.
            suggestions: Accumulated improvement suggestions from reflection.

        Returns:
            New SkillDocument with rewritten content.
        """
        # Preserve the protected section if present
        protected = ""
        if skill.has_protected_section():
            protected = skill.get_protected_section()

        # In production, this calls the optimizer model (frontier LLM)
        # to generate a full skill rewrite. For now, prepend the suggestions
        # as a new section and keep existing content as a base.
        new_sections = [
            f"# {skill.domain.capitalize()} Skill v{skill.version + 1}",
            "",
            "## Improvement Notes",
            suggestions,
            "",
            "## Procedures",
        ]

        # Extract existing procedure content (everything after ## Procedures)
        lines = skill.content.split("\n")
        proc_idx = -1
        for i, line in enumerate(lines):
            if "## Procedures" in line:
                proc_idx = i
                break
        if proc_idx >= 0:
            new_sections.extend(lines[proc_idx + 1:])
        else:
            new_sections.extend(lines)

        new_content = "\n".join(new_sections)

        # Re-attach the protected section at the end
        if protected:
            new_content += f"\n\n{SkillDocument.SLOW_UPDATE_START}\n{protected}\n{SkillDocument.SLOW_UPDATE_END}\n"

        new_skill = SkillDocument(
            skill_id=uuid_hex(),
            domain=skill.domain,
            target_model=skill.target_model,
            harness=skill.harness,
            version=skill.version + 1,
            content=new_content,
            epoch=skill.epoch,
        )
        logger.info(
            "Rewrite mode: generated new skill v%d from %d chars of suggestions",
            new_skill.version, len(suggestions),
        )
        return new_skill

    def validate_candidate(
        self,
        candidate: SkillDocument,
        split: DataSplit,
    ) -> float:
        """Evaluate candidate skill on D_sel (held-out selection split).

        Returns the validation score. The validation gate accepts the
        candidate only if this score strictly exceeds the champion's score.
        """
        if self._evaluate_fn:
            return self._evaluate_fn(candidate, split.selection)

        # Placeholder: compute average reward on selection split
        # In production, this runs the candidate skill on D_sel sessions
        sel_scores = [s.reward for s in split.selection]
        return sum(sel_scores) / len(sel_scores) if sel_scores else 0.0

    def run_meta_update(
        self,
        prev_skill: SkillDocument,
        curr_skill: SkillDocument,
        split: DataSplit,
        epoch: int,
    ) -> str:
        """Run epoch-wise slow/meta update (momentum analog).

        Compares the previous epoch's last skill with the current epoch's
        last skill on shared tasks. Produces a concise longitudinal
        guidance block that preserves long-horizon regularities.

        Returns a markdown guidance block to prepend to the optimizer's
        meta skill (not shipped with the target model).
        """
        if not self.config.enable_meta_update:
            return ""

        # Sample tasks for comparison
        sample_tasks = split.train[: self.config.meta_update_tasks]

        guidance_lines = [
            f"<!-- SKILLOPT Meta Update — Epoch {epoch} → {epoch + 1} -->",
            "",
            f"Previous skill version: {prev_skill.version} "
            f"(score: {prev_skill.validation_score:.4f})",
            f"Current skill version: {curr_skill.version} "
            f"(score: {curr_skill.validation_score:.4f})",
            "",
            "## Longitudinal Guidance",
            "",
        ]

        # In production, this compares actual rollout performance
        # and identifies stable vs. volatile patterns
        improvement = curr_skill.validation_score - prev_skill.validation_score
        if improvement > 0:
            guidance_lines.append(
                f"- Positive trajectory: +{improvement:.4f} improvement. "
                f"Preserve current edit direction."
            )
        else:
            guidance_lines.append(
                f"- Negative/flat trajectory: {improvement:.4f}. "
                f"Consider reducing edit aggressiveness."
            )

        guidance_lines.extend([
            "",
            f"Sampled {len(sample_tasks)} tasks for comparison.",
        ])

        return "\n".join(guidance_lines)

    def train(
        self,
        skill: SkillDocument,
        sessions: list[SessionOutcome],
    ) -> TrainingReport:
        """Run the full SKILLOPT training loop.

        Args:
            skill: Initial skill document to optimize.
            sessions: Historical session outcomes for train/sel/test split.

        Returns:
            TrainingReport with full step history and final metrics.
        """
        start_time = time.time()
        report = TrainingReport(
            domain=skill.domain,
            registry_key=skill.registry_key,
            total_epochs=self.config.max_epochs,
            total_steps=0,
            promotions=0,
            rejections=0,
            final_champion_score=0.0,
            initial_champion_score=0.0,
            improvement=0.0,
        )

        # Split data
        split = self.splitter.split(sessions)
        if split.train_size == 0:
            logger.warning("No training data — returning empty report")
            return report

        # Register initial skill as starting champion
        self.registry.register(skill)
        champion = self.registry.get_champion(skill.registry_key)
        if champion:
            report.initial_champion_score = champion.validation_score

        total_steps = self.config.max_epochs * max(
            1, split.train_size // self.config.rollout_batch_size
        )
        prev_skill = SkillDocument(
            skill_id=skill.skill_id,
            domain=skill.domain,
            target_model=skill.target_model,
            harness=skill.harness,
            version=skill.version,
            content=skill.content,
            validation_score=skill.validation_score,
        )

        for epoch in range(self.config.max_epochs):
            logger.info("=== Epoch %d/%d ===", epoch + 1, self.config.max_epochs)

            # Rollout batch on D_train with accumulation support (§3.2)
            batch_start = 0
            step_in_epoch = 0
            accum_batches: list[SessionOutcome] = []
            suggestions = ""

            while batch_start < split.train_size:
                batch = split.train[
                    batch_start : batch_start + self.config.rollout_batch_size
                ]
                if not batch:
                    break

                # Accumulate batches before reflecting (§3.2)
                accum_batches.extend(batch)
                batch_start += self.config.rollout_batch_size

                if len(accum_batches) < self.config.accumulation_batches * self.config.rollout_batch_size:
                    # Not enough accumulated yet
                    continue

                step_start = time.time()
                self._step_counter += 1
                step_in_epoch += 1

                # Compute edit budget for this step
                budget = self.compute_edit_budget(
                    self._step_counter, total_steps
                )

                # Get current champion
                current = self.registry.get_champion(skill.registry_key)
                if current is None:
                    break

                # Propose edits (forward pass: rollout + reflection)
                proposed = self.propose_edits(current, accum_batches, skill.domain)

                # Merge and clip to budget (bounded update)
                applied = self.merge_edits(proposed, budget)

                if (
                    self.config.edit_mode == EditMode.REWRITE
                    and proposed
                    and suggestions
                ):
                    # Rewrite mode (§3.4): full skill rewrite from suggestions
                    candidate = self.rewrite_skill(current, suggestions)
                    applied = []  # No individual edits to track in rewrite
                else:
                    # Patch mode (default): apply localized edits
                    candidate_content = current.apply_edits(applied)
                    candidate = SkillDocument(
                        skill_id=uuid_hex(),
                        domain=skill.domain,
                        target_model=skill.target_model,
                        harness=skill.harness,
                        version=current.version + 1,
                        content=candidate_content,
                        epoch=epoch,
                    )

                # Validation gate on D_sel
                candidate_score = self.validate_candidate(candidate, split)
                champion_score = current.validation_score

                # Strict improvement check
                promoted = False
                rejection_reason = ""
                if not self.config.strict_validation:
                    promoted = candidate_score >= champion_score
                else:
                    promoted = candidate_score > champion_score

                if promoted:
                    self.registry.try_promote(candidate, candidate_score, champion_score)
                    report.promotions += 1
                else:
                    rejection_reason = (
                        "candidate_score_not_strictly_better"
                        if self.config.strict_validation
                        else "candidate_score_below_threshold"
                    )
                    # Add rejected edits to adversarial buffer
                    self.rejected_buffer.add_rejected_edits(
                        edits=applied,
                        rejection_reason=rejection_reason,
                        candidate_score=candidate_score,
                        champion_score=champion_score,
                        domain=skill.domain,
                        skill_version=candidate.version,
                        epoch=epoch,
                    )
                    report.rejections += 1

                step_record = OptimizationStep(
                    step_id=self._step_counter,
                    epoch=epoch + 1,
                    domain=skill.domain,
                    registry_key=skill.registry_key,
                    edits_proposed=len(proposed),
                    edits_applied=len(applied),
                    edit_budget_l=budget,
                    candidate_score=candidate_score,
                    champion_score=champion_score,
                    promoted=promoted,
                    rejection_reason=rejection_reason,
                    duration_seconds=time.time() - step_start,
                )
                report.steps.append(step_record)
                report.total_steps += 1

                # Collect suggestions for potential rewrite mode
                for edit in proposed:
                    if edit.rationale:
                        suggestions += f"- [{edit.target}] {edit.rationale}\n"

                # Reset accumulation
                accum_batches = []

            # Epoch-wise meta update (momentum)
            current = self.registry.get_champion(skill.registry_key)
            if current and self.config.enable_meta_update:
                meta_guidance = self.run_meta_update(
                    prev_skill, current, split, epoch
                )
                logger.info("Epoch %d meta update: %s", epoch + 1, meta_guidance[:100])
                prev_skill = SkillDocument(
                    skill_id=current.skill_id,
                    domain=current.domain,
                    target_model=current.target_model,
                    harness=current.harness,
                    version=current.version,
                    content=current.content,
                    validation_score=current.validation_score,
                    epoch=epoch,
                )

        # Final report
        final_champion = self.registry.get_champion(skill.registry_key)
        if final_champion:
            report.final_champion_score = final_champion.validation_score
        report.improvement = (
            report.final_champion_score - report.initial_champion_score
        )
        report.total_epochs = self.config.max_epochs

        logger.info(
            "Training complete: %s — %d steps, %d promotions, %d rejections, "
            "improvement: %+.4f (%.2fs)",
            skill.registry_key, report.total_steps,
            report.promotions, report.rejections,
            report.improvement, time.time() - start_time,
        )

        return report


def uuid_hex() -> str:
    """Generate a short hex ID."""
    import uuid
    return uuid.uuid4().hex[:12]
