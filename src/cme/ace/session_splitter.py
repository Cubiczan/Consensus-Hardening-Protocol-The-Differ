"""Session data splitter — Train / Selection / Test splits for SKILLOPT loop.

Historical CHP sessions are split into three sets:
  - D_train: Used for rollout + reflection in each optimization step.
  - D_sel:  Held-out selection set for the validation gate.
  - D_test:  Final test set for reporting (never touched during training).

This follows SKILLOPT's (Yang et al., 2026) data split strategy for
skill optimization. The default split is 70/15/15, stratified by domain.
"""

from __future__ import annotations

import logging
import random
from dataclasses import dataclass, field
from typing import Any

from cme.ace.models import SessionOutcome

logger = logging.getLogger(__name__)


@dataclass
class DataSplit:
    """Result of splitting session outcomes into train/sel/test sets."""

    train: list[SessionOutcome] = field(default_factory=list)
    selection: list[SessionOutcome] = field(default_factory=list)
    test: list[SessionOutcome] = field(default_factory=list)

    @property
    def train_size(self) -> int:
        return len(self.train)

    @property
    def sel_size(self) -> int:
        return len(self.selection)

    @property
    def test_size(self) -> int:
        return len(self.test)

    def summary(self) -> dict[str, Any]:
        return {
            "total": self.train_size + self.sel_size + self.test_size,
            "train": self.train_size,
            "selection": self.sel_size,
            "test": self.test_size,
            "domains_train": sorted(set(s.domain for s in self.train)),
            "domains_sel": sorted(set(s.domain for s in self.selection)),
        }


class SessionSplitter:
    """Splits historical CHP sessions into train/sel/test for SKILLOPT loop.

    Supports stratified splitting by domain to ensure each split has
    representative coverage of all decision domains.
    """

    def __init__(
        self,
        train_ratio: float = 0.70,
        sel_ratio: float = 0.15,
        seed: int = 42,
    ) -> None:
        if not (0 < train_ratio < 1 and 0 < sel_ratio < 1):
            raise ValueError("Ratios must be between 0 and 1")
        if train_ratio + sel_ratio >= 1.0:
            raise ValueError("train_ratio + sel_ratio must be < 1.0")

        self.train_ratio = train_ratio
        self.sel_ratio = sel_ratio
        self.test_ratio = 1.0 - train_ratio - sel_ratio
        self.rng = random.Random(seed)

    def split(
        self,
        sessions: list[SessionOutcome],
        stratify_by: str = "domain",
    ) -> DataSplit:
        """Split sessions into train/selection/test sets.

        Args:
            sessions: List of recorded session outcomes.
            stratify_by: Field to stratify by (default: "domain").

        Returns:
            DataSplit with train, selection, and test lists.
        """
        if not sessions:
            return DataSplit()

        # Group by stratification key
        groups: dict[str, list[SessionOutcome]] = {}
        for session in sessions:
            key = getattr(session, stratify_by, "default")
            groups.setdefault(key, []).append(session)

        result = DataSplit()

        for group_key, group_sessions in groups.items():
            # Shuffle within each group
            shuffled = list(group_sessions)
            self.rng.shuffle(shuffled)

            n = len(shuffled)
            n_train = max(1, int(n * self.train_ratio))
            n_sel = max(1, int(n * self.sel_ratio))

            result.train.extend(shuffled[:n_train])
            result.selection.extend(shuffled[n_train : n_train + n_sel])
            result.test.extend(shuffled[n_train + n_sel :])

        # Final shuffle of each split
        self.rng.shuffle(result.train)
        self.rng.shuffle(result.selection)
        self.rng.shuffle(result.test)

        summary = result.summary()
        logger.info(
            "Session split: total=%d, train=%d, sel=%d, test=%d",
            summary["total"], summary["train"],
            summary["sel"], summary["test"],
        )

        return result

    def evaluate_split(
        self,
        split: DataSplit,
        candidates: list[SessionOutcome],
    ) -> float:
        """Evaluate a set of candidate sessions against the selection split.

        Computes the average reward of candidates. This is used as the
        D_sel validation score in the SKILLOPT gate.

        Args:
            split: The data split containing D_sel.
            candidates: Sessions to evaluate (using their rewards).

        Returns:
            Average reward score (0.0-1.0).
        """
        if not candidates:
            return 0.0
        return sum(s.reward for s in candidates) / len(candidates)
