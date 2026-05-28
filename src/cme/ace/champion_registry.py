"""Champion registry — versioned best_skill.md per (domain, target_model, harness).

The champion registry is the SKILLOPT analog of a model checkpoint store.
It tracks the best-performing skill document for each domain/model/harness
tuple and only promotes a new champion when a candidate strictly beats the
current best on the held-out validation split D_sel.
"""

from __future__ import annotations

import json
import logging
import time
from pathlib import Path
from typing import Any, Optional

from cme.ace.models import SkillDocument

logger = logging.getLogger(__name__)


class ChampionRegistry:
    """Registry tracking the champion skill for each (domain, model, harness) tuple.

    A candidate skill is only promoted to champion if it strictly outperforms
    the current champion on the held-out validation split. This maps 1:1 onto
    CHP's existing lock progression: PROVISIONAL_LOCK → LOCKED only after
    beating the current champion on D_sel.
    """

    def __init__(self, storage_path: str | Path = "data/champions") -> None:
        self.storage_path = Path(storage_path)
        self._champions: dict[str, SkillDocument] = {}
        self._history: list[dict[str, Any]] = []
        self.storage_path.mkdir(parents=True, exist_ok=True)

    def get_champion(self, registry_key: str) -> Optional[SkillDocument]:
        """Get the current champion for a given key."""
        return self._champions.get(registry_key)

    def try_promote(
        self,
        candidate: SkillDocument,
        validation_score: float,
        current_champion_score: float,
    ) -> bool:
        """Attempt to promote a candidate to champion.

        The candidate must STRICTLY beat the current champion on D_sel.
        Ties are rejected (following SKILLOPT's strict validation gate).

        Args:
            candidate: The candidate skill document.
            validation_score: Candidate's score on D_sel.
            current_champion_score: Current champion's score on D_sel.

        Returns:
            True if promoted, False if rejected.
        """
        key = candidate.registry_key
        current = self._champions.get(key)

        if validation_score <= current_champion_score:
            logger.info(
                "Promotion REJECTED for %s: candidate %.4f <= champion %.4f",
                key, validation_score, current_champion_score,
            )
            self._record_history(
                key=key,
                candidate_id=candidate.skill_id,
                candidate_version=candidate.version,
                candidate_score=validation_score,
                champion_score=current_champion_score,
                promoted=False,
                reason="candidate_score_not_strictly_better",
            )
            return False

        # Demote old champion
        if current is not None:
            current.is_champion = False
            self._save_skill(current)

        # Promote new champion
        candidate.is_champion = True
        candidate.validation_score = validation_score
        candidate.updated_at = time.time()
        self._champions[key] = candidate
        self._save_skill(candidate)

        improvement = validation_score - current_champion_score
        logger.info(
            "Promotion ACCEPTED for %s: v%d (%.4f) beats v%d (%.4f) by +%.4f",
            key, candidate.version, validation_score,
            current.version if current else 0,
            current_champion_score, improvement,
        )
        self._record_history(
            key=key,
            candidate_id=candidate.skill_id,
            candidate_version=candidate.version,
            candidate_score=validation_score,
            champion_score=current_champion_score,
            promoted=True,
            reason=f"improvement_{improvement:.4f}",
        )
        return True

    def register(self, skill: SkillDocument) -> None:
        """Register a skill in the registry (without promotion check)."""
        key = skill.registry_key
        if key not in self._champions:
            # First skill for this key — automatically becomes champion
            skill.is_champion = True
            self._champions[key] = skill
            self._save_skill(skill)
            logger.info("Initial champion registered for %s: v%d", key, skill.version)

    def get_all_champions(self) -> dict[str, SkillDocument]:
        """Return all current champions."""
        return dict(self._champions)

    def get_history(self) -> list[dict[str, Any]]:
        """Return promotion/rejection history."""
        return list(self._history)

    def _save_skill(self, skill: SkillDocument) -> None:
        """Persist skill document to disk."""
        key = skill.registry_key
        safe_key = key.replace("/", "_")
        filepath = self.storage_path / f"{safe_key}_v{skill.version}.md"

        header = (
            f"<!-- SKILLOPT Champion Skill -->\n"
            f"<!-- domain: {skill.domain} -->\n"
            f"<!-- target_model: {skill.target_model} -->\n"
            f"<!-- harness: {skill.harness} -->\n"
            f"<!-- version: {skill.version} -->\n"
            f"<!-- epoch: {skill.epoch} -->\n"
            f"<!-- validation_score: {skill.validation_score:.4f} -->\n"
            f"<!-- is_champion: {skill.is_champion} -->\n"
            f"<!-- created: {time.ctime(skill.created_at)} -->\n"
            f"<!-- updated: {time.ctime(skill.updated_at)} -->\n\n"
        )
        filepath.write_text(header + skill.content, encoding="utf-8")

    def _record_history(self, **kwargs: Any) -> None:
        """Record a promotion/rejection event."""
        self._history.append({
            "timestamp": time.time(),
            **kwargs,
        })

    @classmethod
    def load(cls, storage_path: str | Path = "data/champions") -> ChampionRegistry:
        """Load a registry from disk."""
        registry = cls(storage_path=storage_path)
        registry.storage_path.mkdir(parents=True, exist_ok=True)
        return registry
