"""Tests for the SKILLOPT-style ACE skill optimization loop."""

import os
import tempfile
import unittest

from cme.ace.models import EditOp, SessionOutcome, SkillDocument, SkillEdit
from cme.ace.champion_registry import ChampionRegistry
from cme.ace.session_splitter import SessionSplitter, DataSplit
from cme.ace.rejected_edit_buffer import RejectedEditBuffer, RejectedEdit
from cme.ace.skill_optimizer import (
    LearningRateSchedule,
    SkillOptimizer,
    TrainingConfig,
    TrainingReport,
)
from cme.chp_locks import SKILLOPTLockState, SKILLOPT_TRANSITIONS


def _make_session(
    session_id: str = "s1",
    domain: str = "finance",
    reward: float = 0.8,
    lock_state: str = "LOCKED",
) -> SessionOutcome:
    return SessionOutcome(
        session_id=session_id,
        domain=domain,
        topic=f"Test topic for {session_id}",
        skill_version=1,
        reward=reward,
        turns_count=4,
        lock_state=lock_state,
    )


def _make_skill(
    domain: str = "finance",
    model: str = "gpt-5.5",
    harness: str = "direct-chat",
    version: int = 1,
    content: str = "",
) -> SkillDocument:
    if not content:
        content = (
            f"# {domain.capitalize()} Skill v{version}\n\n"
            "## Procedures\n"
            "- Step 1: Analyze the request\n"
            "- Step 2: Check constraints\n"
            "- Step 3: Generate response\n\n"
            "## Constraints\n"
            "- Always validate outputs\n"
            "- Never exceed scope\n"
        )
    return SkillDocument(
        skill_id=f"skill_{domain}_{version}",
        domain=domain,
        target_model=model,
        harness=harness,
        version=version,
        content=content,
    )


class TestSkillDocument(unittest.TestCase):
    def test_registry_key(self):
        skill = _make_skill(domain="finance", model="gpt-5.5", harness="codex")
        self.assertEqual(skill.registry_key, "finance/gpt-5.5/codex")

    def test_apply_append_edit(self):
        skill = _make_skill(content="# Rules\n- Rule A\n")
        edit = SkillEdit(op=EditOp.APPEND, target="Rules", content="- Rule B\n")
        new_content = skill.apply_edits([edit])
        self.assertIn("Rule B", new_content)
        self.assertIn("Rule A", new_content)

    def test_apply_delete_edit(self):
        skill = _make_skill(content="# Section\nLine to delete\nAnother line\n## Next\n")
        edit = SkillEdit(op=EditOp.DELETE, target="Section", content="")
        new_content = skill.apply_edits([edit])
        self.assertNotIn("Line to delete", new_content)
        self.assertIn("## Next", new_content)

    def test_apply_replace_edit(self):
        skill = _make_skill(content="# Section\nOld content\n## Next\n")
        edit = SkillEdit(op=EditOp.REPLACE, target="Section", content="New content\n")
        new_content = skill.apply_edits([edit])
        self.assertIn("New content", new_content)
        self.assertNotIn("Old content", new_content)

    def test_to_dict(self):
        skill = _make_skill()
        d = skill.to_dict()
        self.assertEqual(d["domain"], "finance")
        self.assertEqual(d["version"], 1)
        self.assertIn("registry_key", d)


class TestSessionSplitter(unittest.TestCase):
    def test_split_sessions(self):
        sessions = [_make_session(f"s{i}", domain="finance") for i in range(100)]
        sessions.extend(_make_session(f"m{i}", domain="critmin") for i in range(50))
        splitter = SessionSplitter(train_ratio=0.70, sel_ratio=0.15, seed=42)
        split = splitter.split(sessions)

        total = split.train_size + split.sel_size + split.test_size
        self.assertEqual(total, 150)
        self.assertGreater(split.train_size, split.sel_size)
        self.assertGreater(split.sel_size, split.test_size)

    def test_empty_sessions(self):
        splitter = SessionSplitter()
        split = splitter.split([])
        self.assertEqual(split.train_size, 0)
        self.assertEqual(split.sel_size, 0)
        self.assertEqual(split.test_size, 0)

    def test_stratified_domains(self):
        sessions = [_make_session(f"f{i}", domain="finance") for i in range(20)]
        sessions.extend(_make_session(f"c{i}", domain="critmin") for i in range(20))
        splitter = SessionSplitter(train_ratio=0.70, sel_ratio=0.15)
        split = splitter.split(sessions)

        train_domains = set(s.domain for s in split.train)
        self.assertIn("finance", train_domains)
        self.assertIn("critmin", train_domains)

    def test_invalid_ratios(self):
        with self.assertRaises(ValueError):
            SessionSplitter(train_ratio=1.5, sel_ratio=0.15)
        with self.assertRaises(ValueError):
            SessionSplitter(train_ratio=0.5, sel_ratio=0.6)


class TestChampionRegistry(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.registry = ChampionRegistry(storage_path=self.tmpdir)

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_initial_registration(self):
        skill = _make_skill()
        self.registry.register(skill)
        champion = self.registry.get_champion(skill.registry_key)
        self.assertIsNotNone(champion)
        self.assertTrue(champion.is_champion)

    def test_promotion_accepted(self):
        champ = _make_skill(version=1)
        champ.validation_score = 0.80
        self.registry.register(champ)

        candidate = _make_skill(version=2)
        result = self.registry.try_promote(candidate, 0.85, 0.80)
        self.assertTrue(result)

        new_champ = self.registry.get_champion(champ.registry_key)
        self.assertIsNotNone(new_champ)
        self.assertEqual(new_champ.version, 2)
        self.assertTrue(new_champ.is_champion)

    def test_promotion_rejected_equal_score(self):
        champ = _make_skill(version=1)
        champ.validation_score = 0.80
        self.registry.register(champ)

        candidate = _make_skill(version=2)
        result = self.registry.try_promote(candidate, 0.80, 0.80)
        # Strict gate: ties are rejected
        self.assertFalse(result)

    def test_promotion_rejected_lower_score(self):
        champ = _make_skill(version=1)
        champ.validation_score = 0.85
        self.registry.register(champ)

        candidate = _make_skill(version=2)
        result = self.registry.try_promote(candidate, 0.80, 0.85)
        self.assertFalse(result)

    def test_history(self):
        champ = _make_skill()
        self.registry.register(champ)
        candidate = _make_skill(version=2)
        self.registry.try_promote(candidate, 0.75, 0.80)
        history = self.registry.get_history()
        self.assertEqual(len(history), 1)
        self.assertFalse(history[0]["promoted"])


class TestRejectedEditBuffer(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.buffer = RejectedEditBuffer(
            max_size=50,
            storage_path=os.path.join(self.tmpdir, "rejected.jsonl"),
        )

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_add_and_retrieve(self):
        edit = SkillEdit(op=EditOp.REPLACE, target="Constraints", content="New constraints")
        rejected = RejectedEdit(
            edit=edit,
            rejection_reason="score_not_better",
            candidate_score=0.70,
            champion_score=0.80,
            domain="finance",
        )
        self.buffer.add(rejected)

        domain_edits = self.buffer.get_context_for_domain("finance")
        self.assertEqual(len(domain_edits), 1)
        self.assertEqual(domain_edits[0].edit.op, EditOp.REPLACE)

    def test_add_rejected_edits_batch(self):
        edits = [
            SkillEdit(op=EditOp.APPEND, target="Rules", content="Rule X"),
            SkillEdit(op=EditOp.DELETE, target="Old", content=""),
        ]
        self.buffer.add_rejected_edits(
            edits, "failed_gate", 0.65, 0.80, domain="critmin"
        )
        self.assertEqual(len(self.buffer.get_all()), 2)

    def test_max_size_eviction(self):
        small_buffer = RejectedEditBuffer(max_size=5)
        for i in range(10):
            edit = SkillEdit(op=EditOp.APPEND, target=f"Section_{i}", content=f"Content {i}")
            rejected = RejectedEdit(
                edit=edit, rejection_reason="test", candidate_score=0.5,
                champion_score=0.8, domain="finance",
            )
            small_buffer.add(rejected)
        self.assertLessEqual(len(small_buffer.get_all()), 5)

    def test_format_for_optimizer(self):
        edit = SkillEdit(op=EditOp.REPLACE, target="Rules", content="X", rationale="bad idea")
        rejected = RejectedEdit(
            edit=edit, rejection_reason="score_gap", candidate_score=0.60,
            champion_score=0.85, domain="finance",
        )
        self.buffer.add(rejected)
        context = self.buffer.format_for_optimizer("finance")
        self.assertIn("Previously Rejected Edits", context)
        self.assertIn("REPLACE", context)

    def test_persistence(self):
        edit = SkillEdit(op=EditOp.APPEND, target="Test", content="data")
        rejected = RejectedEdit(
            edit=edit, rejection_reason="test", candidate_score=0.5,
            champion_score=0.8, domain="security",
        )
        self.buffer.add(rejected)

        # Reload
        new_buffer = RejectedEditBuffer(
            storage_path=self.buffer.storage_path,
        )
        self.assertEqual(len(new_buffer.get_all()), 1)


class TestSkillOptimizer(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_edit_budget_cosine(self):
        config = TrainingConfig(
            lr_schedule=LearningRateSchedule.COSINE,
            edit_budget_l_max=4,
            edit_budget_l_floor=2,
        )
        optimizer = SkillOptimizer(config=config)

        # Early step: budget should be close to max
        budget_early = optimizer.compute_edit_budget(0, 100)
        self.assertGreaterEqual(budget_early, 3)

        # Late step: budget should be close to floor
        budget_late = optimizer.compute_edit_budget(99, 100)
        self.assertLessEqual(budget_late, 3)

    def test_edit_budget_constant(self):
        config = TrainingConfig(
            lr_schedule=LearningRateSchedule.CONSTANT,
            edit_budget_l_max=6,
        )
        optimizer = SkillOptimizer(config=config)

        for step in range(10):
            budget = optimizer.compute_edit_budget(step, 20)
            self.assertEqual(budget, 6)

    def test_merge_edits_clips_to_budget(self):
        config = TrainingConfig(edit_budget_l_max=3)
        optimizer = SkillOptimizer(config=config)

        edits = [
            SkillEdit(op=EditOp.APPEND, target=f"Section_{i}", utility_score=0.9 - i * 0.1)
            for i in range(10)
        ]
        merged = optimizer.merge_edits(edits, budget=3)
        self.assertEqual(len(merged), 3)
        # Should be top 3 by utility
        self.assertEqual(merged[0].target, "Section_0")

    def test_merge_edits_deduplicates(self):
        config = TrainingConfig(edit_budget_l_max=10)
        optimizer = SkillOptimizer(config=config)

        edits = [
            SkillEdit(op=EditOp.APPEND, target="Rules", content="A"),
            SkillEdit(op=EditOp.APPEND, target="Rules", content="B"),
        ]
        merged = optimizer.merge_edits(edits, budget=10)
        self.assertEqual(len(merged), 1)

    def test_training_run_produces_report(self):
        config = TrainingConfig(
            max_epochs=2,
            rollout_batch_size=5,
            strict_validation=True,
        )
        registry = ChampionRegistry(storage_path=os.path.join(self.tmpdir, "champions"))
        buffer = RejectedEditBuffer(storage_path=os.path.join(self.tmpdir, "rejected.jsonl"))

        skill = _make_skill(version=1)
        sessions = []
        for i in range(30):
            sessions.append(_make_session(
                f"s{i}", domain="finance",
                reward=0.5 + (i % 10) * 0.04,
            ))

        optimizer = SkillOptimizer(
            config=config,
            champion_registry=registry,
            rejected_buffer=buffer,
        )
        report = optimizer.train(skill, sessions)

        self.assertIsInstance(report, TrainingReport)
        self.assertEqual(report.domain, "finance")
        self.assertEqual(report.total_epochs, 2)
        self.assertGreaterEqual(report.total_steps, 0)

    def test_training_report_markdown(self):
        report = TrainingReport(
            domain="finance",
            registry_key="finance/gpt-5.5/direct-chat",
            total_epochs=4,
            total_steps=12,
            promotions=3,
            rejections=9,
            final_champion_score=0.87,
            initial_champion_score=0.65,
            improvement=0.22,
        )
        md = report.to_markdown()
        self.assertIn("# SKILLOPT Training Report", md)
        self.assertIn("| 4 |", md)
        self.assertIn("+0.2200", md)


class TestSKILLOPTLockStates(unittest.TestCase):
    def test_exploring_to_locked_path(self):
        """Verify the valid path from EXPLORING to LOCKED."""
        path = [
            SKILLOPTLockState.EXPLORING,
            SKILLOPTLockState.PROVISIONAL,
            SKILLOPTLockState.VALIDATION_GATE,
            SKILLOPTLockState.PROVISIONAL_LOCK,
            SKILLOPTLockState.CHALLENGED,
            SKILLOPTLockState.VALIDATED,
            SKILLOPTLockState.LOCKED,
        ]
        for i in range(len(path) - 1):
            allowed = SKILLOPT_TRANSITIONS.get(path[i], [])
            self.assertIn(path[i + 1], allowed,
                          f"Transition {path[i].value} → {path[i+1].value} not allowed")

    def test_locked_is_terminal(self):
        self.assertEqual(SKILLOPT_TRANSITIONS[SKILLOPTLockState.LOCKED], [])
        self.assertEqual(SKILLOPT_TRANSITIONS[SKILLOPTLockState.FAILED], [])

    def test_validation_gate_can_loop_back(self):
        """If validation fails, candidate goes back to PROVISIONAL for more training."""
        allowed = SKILLOPT_TRANSITIONS[SKILLOPTLockState.VALIDATION_GATE]
        self.assertIn(SKILLOPTLockState.PROVISIONAL, allowed)
        self.assertIn(SKILLOPTLockState.PROVISIONAL_LOCK, allowed)


if __name__ == "__main__":
    unittest.main()
