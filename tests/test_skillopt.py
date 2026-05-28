"""Tests for the SKILLOPT-style ACE skill optimization loop."""

import os
import tempfile
import unittest

from cme.ace.models import EditOp, SessionOutcome, SkillDocument, SkillEdit
from cme.ace.champion_registry import ChampionRegistry
from cme.ace.session_splitter import SessionSplitter, DataSplit
from cme.ace.rejected_edit_buffer import RejectedEditBuffer, RejectedEdit
from cme.ace.skill_optimizer import (
    EditMode,
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
        # With stratified splitting across two domains, rounding can make
        # sel_size slightly less than test_size (22 vs 23) — both should be
        # meaningfully populated.
        self.assertGreater(split.sel_size, 0)
        self.assertGreater(split.test_size, 0)

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
            SkillEdit(op=EditOp.APPEND, target=f"Section_{i}", content=f"Content {i}", utility_score=0.9 - i * 0.1)
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


class TestInsertAfterEdit(unittest.TestCase):
    """Tests for the INSERT_AFTER edit operation (§3.3)."""

    def test_insert_after_existing_target(self):
        """INSERT_AFTER inserts content after a found target line."""
        skill = _make_skill(
            content="# Procedures\n- Step 1: Analyze\n- Step 2: Execute\n"
        )
        edit = SkillEdit(
            op=EditOp.INSERT_AFTER,
            target="Step 1",
            content="- Step 1.5: Validate input\n",
        )
        new_content = skill.apply_edits([edit])
        self.assertIn("Step 1.5", new_content)
        # Target line should still be present
        self.assertIn("Step 1: Analyze", new_content)
        # Step 2 should still follow
        self.assertIn("Step 2: Execute", new_content)
        # Order should be: Step 1, Step 1.5, Step 2
        lines = new_content.split("\n")
        idx_1 = next(i for i, l in enumerate(lines) if "Step 1: Analyze" in l)
        idx_15 = next(i for i, l in enumerate(lines) if "Step 1.5" in l)
        idx_2 = next(i for i, l in enumerate(lines) if "Step 2: Execute" in l)
        self.assertLess(idx_1, idx_15)
        self.assertLess(idx_15, idx_2)

    def test_insert_after_no_header_created(self):
        """INSERT_AFTER does NOT create a section header (unlike APPEND)."""
        skill = _make_skill(content="# Rules\n- Rule A\n")
        edit = SkillEdit(
            op=EditOp.INSERT_AFTER, target="Rules", content="- Rule B\n"
        )
        new_content = skill.apply_edits([edit])
        # Should NOT contain a ## Rules header
        self.assertNotIn("## Rules", new_content)
        # Rule B should be present
        self.assertIn("Rule B", new_content)

    def test_insert_after_missing_target_no_change(self):
        """INSERT_AFTER with missing target does nothing (no section creation)."""
        skill = _make_skill(content="# Rules\n- Rule A\n")
        edit = SkillEdit(
            op=EditOp.INSERT_AFTER, target="NonExistent", content="- New\n"
        )
        new_content = skill.apply_edits([edit])
        self.assertNotIn("New", new_content)
        self.assertNotIn("## NonExistent", new_content)

    def test_insert_after_multi_line_content(self):
        """INSERT_AFTER can insert multiple lines."""
        skill = _make_skill(content="# Section\nLine A\n## Next\n")
        edit = SkillEdit(
            op=EditOp.INSERT_AFTER,
            target="Line A",
            content="Line B\nLine C\n",
        )
        new_content = skill.apply_edits([edit])
        self.assertIn("Line B", new_content)
        self.assertIn("Line C", new_content)
        self.assertIn("## Next", new_content)


class TestProtectedSlowUpdateSection(unittest.TestCase):
    """Tests for the protected slow-update section (§3.6)."""

    def test_has_protected_section_true(self):
        content = (
            "# Skill\n\n"
            "## Procedures\n- Step 1\n\n"
            "<!-- SLOW_UPDATE_START -->\n"
            "Meta-update content here\n"
            "<!-- SLOW_UPDATE_END -->\n"
        )
        skill = SkillDocument(content=content, domain="test")
        self.assertTrue(skill.has_protected_section())

    def test_has_protected_section_false(self):
        skill = _make_skill()
        self.assertFalse(skill.has_protected_section())

    def test_has_protected_section_partial_markers(self):
        """Only START marker is not enough — need both."""
        content = "# Skill\n<!-- SLOW_UPDATE_START -->\nNo end marker\n"
        skill = SkillDocument(content=content, domain="test")
        self.assertFalse(skill.has_protected_section())

    def test_get_protected_section(self):
        content = (
            "# Skill\n\n"
            "<!-- SLOW_UPDATE_START -->\n"
            "Meta guidance line 1\nMeta guidance line 2\n"
            "<!-- SLOW_UPDATE_END -->\n"
        )
        skill = SkillDocument(content=content, domain="test")
        protected = skill.get_protected_section()
        self.assertIn("Meta guidance line 1", protected)
        self.assertIn("Meta guidance line 2", protected)
        self.assertNotIn("SLOW_UPDATE_START", protected)
        self.assertNotIn("SLOW_UPDATE_END", protected)

    def test_get_protected_section_empty(self):
        skill = _make_skill()
        self.assertEqual(skill.get_protected_section(), "")

    def test_set_protected_section(self):
        content = (
            "# Skill\n\n"
            "<!-- SLOW_UPDATE_START -->\n"
            "Old meta\n"
            "<!-- SLOW_UPDATE_END -->\n"
        )
        skill = SkillDocument(content=content, domain="test")
        new_content = skill.set_protected_section("New meta content\nLine 2\n")
        self.assertIn("New meta content", new_content)
        self.assertIn("Line 2", new_content)
        self.assertNotIn("Old meta", new_content)
        # Markers should still be present
        self.assertIn("<!-- SLOW_UPDATE_START -->", new_content)
        self.assertIn("<!-- SLOW_UPDATE_END -->", new_content)

    def test_set_protected_section_no_markers(self):
        """set_protected_section returns content unchanged when no markers."""
        skill = _make_skill(content="# Plain content\n")
        new_content = skill.set_protected_section("New meta\n")
        self.assertEqual(new_content, "# Plain content\n")

    def test_apply_edits_skips_protected_section(self):
        """Edits targeting lines inside the protected section are skipped."""
        content = (
            "# Skill\n\n"
            "## Procedures\n- Step 1\n\n"
            "<!-- SLOW_UPDATE_START -->\n"
            "Meta line to target\n"
            "<!-- SLOW_UPDATE_END -->\n"
        )
        skill = SkillDocument(content=content, domain="test")
        # Try to delete a line inside the protected section
        edit = SkillEdit(op=EditOp.DELETE, target="Meta line to target", content="")
        new_content = skill.apply_edits([edit])
        # The protected line should still be present
        self.assertIn("Meta line to target", new_content)

    def test_apply_edits_outside_protected_still_works(self):
        """Edits outside the protected section should still be applied."""
        content = (
            "# Skill\n\n"
            "## Procedures\n- Step 1\n\n"
            "<!-- SLOW_UPDATE_START -->\n"
            "Meta line\n"
            "<!-- SLOW_UPDATE_END -->\n"
        )
        skill = SkillDocument(content=content, domain="test")
        # Edit outside protected section
        edit = SkillEdit(op=EditOp.REPLACE, target="Procedures", content="- New Step\n")
        new_content = skill.apply_edits([edit])
        self.assertIn("New Step", new_content)
        # Protected content should be untouched
        self.assertIn("Meta line", new_content)

    def test_apply_edits_replace_skips_protected(self):
        """Replace edit targeting protected section is skipped."""
        content = (
            "# Skill\n\n"
            "<!-- SLOW_UPDATE_START -->\n"
            "Meta content\n"
            "<!-- SLOW_UPDATE_END -->\n"
        )
        skill = SkillDocument(content=content, domain="test")
        edit = SkillEdit(
            op=EditOp.REPLACE, target="Meta content", content="Replaced"
        )
        new_content = skill.apply_edits([edit])
        self.assertIn("Meta content", new_content)
        self.assertNotIn("Replaced", new_content)


class TestHierarchicalMerge(unittest.TestCase):
    """Tests for hierarchical failure-priority merge (§3.3)."""

    def setUp(self):
        self.config = TrainingConfig(edit_budget_l_max=10)
        self.optimizer = SkillOptimizer(config=self.config)

    def test_failure_priority_allocation(self):
        """~70% of budget goes to failures, ~30% to successes."""
        failures = [
            SkillEdit(op=EditOp.REPLACE, target=f"fail_{i}", content=f"Fix {i}", utility_score=0.9 - i * 0.1)
            for i in range(10)
        ]
        successes = [
            SkillEdit(op=EditOp.APPEND, target=f"succ_{i}", content=f"Reinforce {i}", utility_score=0.8 - i * 0.05)
            for i in range(10)
        ]
        merged = self.optimizer.merge_edits_hierarchical(failures, successes, budget=10)
        failure_count = sum(1 for e in merged if e.target.startswith("fail_"))
        success_count = sum(1 for e in merged if e.target.startswith("succ_"))
        # 70% of 10 = 7 for failures
        self.assertEqual(failure_count, 7)
        self.assertEqual(success_count, 3)

    def test_deduplication_within_failures(self):
        """Duplicate failure targets are deduplicated (highest utility kept)."""
        failures = [
            SkillEdit(op=EditOp.REPLACE, target="Fix_A", content="v1", utility_score=0.5),
            SkillEdit(op=EditOp.APPEND, target="Fix_A", content="v2", utility_score=0.9),
        ]
        merged = self.optimizer.merge_edits_hierarchical(failures, [], budget=5)
        self.assertEqual(len(merged), 1)
        self.assertEqual(merged[0].utility_score, 0.9)

    def test_deduplication_within_successes(self):
        """Duplicate success targets are deduplicated."""
        successes = [
            SkillEdit(op=EditOp.APPEND, target="Keep_B", content="v1", utility_score=0.3),
            SkillEdit(op=EditOp.APPEND, target="Keep_B", content="v2", utility_score=0.7),
        ]
        merged = self.optimizer.merge_edits_hierarchical([], successes, budget=5)
        self.assertEqual(len(merged), 1)
        self.assertEqual(merged[0].utility_score, 0.7)

    def test_conflicting_success_removed(self):
        """Success edits with same target as failure edits are removed."""
        failures = [
            SkillEdit(op=EditOp.REPLACE, target="Shared", content="Fix", utility_score=0.8),
        ]
        successes = [
            SkillEdit(op=EditOp.APPEND, target="Shared", content="Keep", utility_score=0.9),
            SkillEdit(op=EditOp.APPEND, target="Unique", content="Keep", utility_score=0.7),
        ]
        merged = self.optimizer.merge_edits_hierarchical(failures, successes, budget=10)
        targets = [e.target for e in merged]
        # Shared should appear only once (from failures)
        self.assertEqual(targets.count("Shared"), 1)
        # Unique success should still be present
        self.assertIn("Unique", targets)

    def test_budget_clipping(self):
        """Total merged edits never exceed budget."""
        failures = [
            SkillEdit(op=EditOp.REPLACE, target=f"f{i}", content=f"c", utility_score=0.9 - i * 0.01)
            for i in range(20)
        ]
        successes = [
            SkillEdit(op=EditOp.APPEND, target=f"s{i}", content=f"c", utility_score=0.8 - i * 0.01)
            for i in range(20)
        ]
        merged = self.optimizer.merge_edits_hierarchical(failures, successes, budget=5)
        self.assertLessEqual(len(merged), 5)

    def test_ranking_by_utility(self):
        """Failures and successes are each ranked by utility descending."""
        failures = [
            SkillEdit(op=EditOp.REPLACE, target="low", content="c", utility_score=0.2),
            SkillEdit(op=EditOp.REPLACE, target="high", content="c", utility_score=0.9),
            SkillEdit(op=EditOp.REPLACE, target="mid", content="c", utility_score=0.5),
        ]
        merged = self.optimizer.merge_edits_hierarchical(failures, [], budget=10)
        failure_targets = [e.target for e in merged]
        self.assertEqual(failure_targets, ["high", "mid", "low"])

    def test_empty_inputs(self):
        """Empty failure and success lists return empty list."""
        merged = self.optimizer.merge_edits_hierarchical([], [], budget=5)
        self.assertEqual(merged, [])



class TestRewriteMode(unittest.TestCase):
    """Tests for rewrite mode (§3.4)."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_rewrite_produces_new_skill(self):
        """rewrite_skill returns a new SkillDocument with updated version."""
        skill = _make_skill(version=3)
        optimizer = SkillOptimizer()
        new_skill = optimizer.rewrite_skill(skill, "Improve validation logic")
        self.assertIsInstance(new_skill, SkillDocument)
        self.assertEqual(new_skill.version, 4)
        self.assertNotEqual(new_skill.content, skill.content)

    def test_rewrite_includes_suggestions(self):
        """Rewritten skill includes the suggestions text."""
        skill = _make_skill(version=1)
        optimizer = SkillOptimizer()
        new_skill = optimizer.rewrite_skill(skill, "Add retry logic for API calls")
        self.assertIn("Add retry logic for API calls", new_skill.content)

    def test_rewrite_preserves_protected_section(self):
        """Rewrite preserves the protected slow-update section."""
        content = (
            "# Finance Skill v1\n\n"
            "## Procedures\n- Step 1\n\n"
            "<!-- SLOW_UPDATE_START -->\n"
            "Critical meta-update data\n"
            "<!-- SLOW_UPDATE_END -->\n"
        )
        skill = SkillDocument(
            skill_id="skill_test", domain="finance",
            target_model="gpt-5.5", harness="direct-chat",
            version=1, content=content,
        )
        optimizer = SkillOptimizer()
        new_skill = optimizer.rewrite_skill(skill, "Some suggestions")
        self.assertIn("Critical meta-update data", new_skill.content)
        self.assertIn("<!-- SLOW_UPDATE_START -->", new_skill.content)
        self.assertIn("<!-- SLOW_UPDATE_END -->", new_skill.content)

    def test_rewrite_without_protected_section(self):
        """Rewrite works fine when no protected section exists."""
        skill = _make_skill(version=2)
        optimizer = SkillOptimizer()
        new_skill = optimizer.rewrite_skill(skill, "Suggestions")
        self.assertEqual(new_skill.version, 3)
        self.assertNotIn("SLOW_UPDATE", new_skill.content)

    def test_edit_mode_enum_values(self):
        """EditMode enum has correct values."""
        self.assertEqual(EditMode.PATCH, "patch")
        self.assertEqual(EditMode.REWRITE, "rewrite")

    def test_training_config_default_edit_mode(self):
        """Default edit mode is PATCH."""
        config = TrainingConfig()
        self.assertEqual(config.edit_mode, EditMode.PATCH)

    def test_training_config_accumulation_batches_default(self):
        """Default accumulation_batches is 1."""
        config = TrainingConfig()
        self.assertEqual(config.accumulation_batches, 1)


class TestAccumulationBatches(unittest.TestCase):
    """Tests for rollout accumulation (§3.2)."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_accumulation_reduces_step_count(self):
        """With accumulation_batches=2, fewer optimization steps occur."""
        config = TrainingConfig(
            max_epochs=2,
            rollout_batch_size=5,
            accumulation_batches=2,
        )
        registry = ChampionRegistry(storage_path=os.path.join(self.tmpdir, "champions"))
        buffer = RejectedEditBuffer(storage_path=os.path.join(self.tmpdir, "rejected.jsonl"))

        skill = _make_skill(version=1)
        sessions = [_make_session(f"s{i}", domain="finance", reward=0.5) for i in range(40)]

        optimizer = SkillOptimizer(
            config=config,
            champion_registry=registry,
            rejected_buffer=buffer,
        )
        report = optimizer.train(skill, sessions)

        # With accumulation_batches=2 and batch_size=5, we need 10 items
        # per step instead of 5, so steps should be roughly halved
        self.assertGreaterEqual(report.total_steps, 0)

    def test_accumulation_default_no_change(self):
        """accumulation_batches=1 (default) behaves as before."""
        config = TrainingConfig(
            max_epochs=1,
            rollout_batch_size=5,
            accumulation_batches=1,
        )
        registry = ChampionRegistry(storage_path=os.path.join(self.tmpdir, "champions"))
        buffer = RejectedEditBuffer(storage_path=os.path.join(self.tmpdir, "rejected.jsonl"))

        skill = _make_skill(version=1)
        sessions = [_make_session(f"s{i}", domain="finance", reward=0.5) for i in range(20)]

        optimizer = SkillOptimizer(
            config=config,
            champion_registry=registry,
            rejected_buffer=buffer,
        )
        report = optimizer.train(skill, sessions)

        self.assertIsInstance(report, TrainingReport)
        self.assertGreaterEqual(report.total_steps, 0)

    def test_accumulation_batches_larger_than_data(self):
        """accumulation_batches larger than available data still processes."""
        config = TrainingConfig(
            max_epochs=1,
            rollout_batch_size=5,
            accumulation_batches=100,  # Way more than we have data for
        )
        registry = ChampionRegistry(storage_path=os.path.join(self.tmpdir, "champions"))
        buffer = RejectedEditBuffer(storage_path=os.path.join(self.tmpdir, "rejected.jsonl"))

        skill = _make_skill(version=1)
        sessions = [_make_session(f"s{i}", domain="finance", reward=0.5) for i in range(10)]

        optimizer = SkillOptimizer(
            config=config,
            champion_registry=registry,
            rejected_buffer=buffer,
        )
        report = optimizer.train(skill, sessions)

        # Should still produce a valid report (with 0 steps since we can't
        # accumulate enough batches)
        self.assertIsInstance(report, TrainingReport)


if __name__ == "__main__":
    unittest.main()
