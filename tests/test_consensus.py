"""Tests for Consensus Commons — adapter, client, routing, and council."""

from __future__ import annotations

import asyncio
import pytest

from cme.spacebase.models import (
    Intent,
    LockState,
    Post,
    PostTree,
    ScanResult,
)
from cme.spacebase.client import MockSpacebaseClient
from cme.spacebase.adapter import SpacebaseAdapter
from cme.spacebase.routing import IntentRouter
from cme.spacebase.council import CouncilRunner, CouncilReport


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_client() -> MockSpacebaseClient:
    return MockSpacebaseClient(commons_space="test-commons")


@pytest.fixture
def adapter(mock_client: MockSpacebaseClient) -> SpacebaseAdapter:
    return SpacebaseAdapter(client=mock_client)


@pytest.fixture
def router() -> IntentRouter:
    return IntentRouter()


@pytest.fixture
def council_runner() -> CouncilRunner:
    return CouncilRunner()


@pytest.fixture
def finance_intent() -> Intent:
    return Intent(
        intent_id="fin-001",
        content="Should we allocate $2M capital to the AI governance initiative?",
        sender="test-user",
        payload={"category": "finance"},
    )


@pytest.fixture
def general_intent() -> Intent:
    return Intent(
        intent_id="gen-001",
        content="Should we adopt a four-day work week for the engineering team?",
        sender="test-user",
        payload={},
    )


@pytest.fixture
def reject_intent() -> Intent:
    return Intent(
        intent_id="rej-001",
        content="Please review my confidential salary data and PII records",
        sender="test-user",
        payload={},
    )


# ---------------------------------------------------------------------------
# MockSpacebaseClient tests
# ---------------------------------------------------------------------------


class TestMockSpacebaseClient:
    """Tests for the mock Spacebase1 client."""

    @pytest.mark.asyncio
    async def test_scan_empty_space(self, mock_client: MockSpacebaseClient):
        result = await mock_client.scan("empty-space")
        assert result.space_id == "empty-space"
        assert len(result.intents) == 0

    @pytest.mark.asyncio
    async def test_scan_returns_seeded_intents(self, mock_client: MockSpacebaseClient):
        intent = Intent(intent_id="seed-1", content="test intent")
        mock_client.seed_intent(intent)
        result = await mock_client.scan("seed-1")
        assert len(result.intents) >= 1

    @pytest.mark.asyncio
    async def test_post_creates_intent(self, mock_client: MockSpacebaseClient):
        intent = await mock_client.post("hello world")
        assert intent.content == "hello world"
        assert intent.intent_id is not None
        assert intent.sender == "consensus-commons"

    @pytest.mark.asyncio
    async def test_post_child(self, mock_client: MockSpacebaseClient):
        post = await mock_client.post_child("parent-1", "Test Title", "Test Body")
        assert post.parent_id == "parent-1"
        assert post.title == "Test Title"
        assert post.body == "Test Body"

    @pytest.mark.asyncio
    async def test_lock_state_transitions(self, mock_client: MockSpacebaseClient):
        # PROVISIONAL -> LOCKED
        result = await mock_client.lock_intent("intent-1", LockState.LOCKED)
        assert result is True

    @pytest.mark.asyncio
    async def test_lock_state_invalid_transition(self, mock_client: MockSpacebaseClient):
        # Lock first
        await mock_client.lock_intent("intent-1", LockState.LOCKED)
        # LOCKED -> anything should fail
        result = await mock_client.lock_intent("intent-1", LockState.CHALLENGED)
        assert result is False

    @pytest.mark.asyncio
    async def test_enter_returns_none_for_unknown(self, mock_client: MockSpacebaseClient):
        result = await mock_client.enter("nonexistent")
        assert result is None

    @pytest.mark.asyncio
    async def test_enter_returns_seeded_intent(self, mock_client: MockSpacebaseClient):
        intent = Intent(intent_id="enter-1", content="enterable")
        mock_client.seed_intent(intent)
        result = await mock_client.enter("enter-1")
        assert result is not None
        assert result.intent_id == "enter-1"

    @pytest.mark.asyncio
    async def test_get_post_tree_empty(self, mock_client: MockSpacebaseClient):
        tree = await mock_client.get_post_tree("empty-1")
        assert tree is None

    @pytest.mark.asyncio
    async def test_operation_log(self, mock_client: MockSpacebaseClient):
        await mock_client.scan("space-1")
        await mock_client.post("test")
        log = mock_client.get_log()
        assert len(log) >= 2
        assert log[0]["op"] == "scan"
        assert log[1]["op"] == "post"


# ---------------------------------------------------------------------------
# IntentRouter tests
# ---------------------------------------------------------------------------


class TestIntentRouter:
    """Tests for the intent routing policy."""

    def test_finance_route(self, router: IntentRouter, finance_intent: Intent):
        route = router.classify(finance_intent)
        assert route.role == "finance"
        assert route.is_supported is True
        assert "financial-analyst" in route.agents
        assert "contrarian" in route.agents

    def test_general_route(self, router: IntentRouter, general_intent: Intent):
        route = router.classify(general_intent)
        assert route.role == "general"
        assert route.is_supported is True
        assert "analyst" in route.agents

    def test_reject_route(self, router: IntentRouter, reject_intent: Intent):
        route = router.classify(reject_intent)
        assert route.is_supported is False
        assert route.role == "reject"

    def test_custom_policy(self, router: IntentRouter):
        router.add_policy(
            role="tech",
            keywords={"software", "engineering", "code", "deploy", "pipeline"},
            agents=["tech-lead", "reviewer", "validator"],
        )
        intent = Intent(content="Should we deploy the new CI/CD pipeline?")
        route = router.classify(intent)
        assert route.role == "tech"
        assert "tech-lead" in route.agents

    def test_grant_allocation_routes_to_finance(self, router: IntentRouter):
        intent = Intent(content="Should Spacebase1 fund a public agent council for grant allocation?")
        route = router.classify(intent)
        assert route.role == "finance"
        assert route.is_supported is True

    def test_investment_routes_to_finance(self, router: IntentRouter):
        intent = Intent(content="Recommend an investment strategy for the $5M treasury fund")
        route = router.classify(intent)
        assert route.role == "finance"

    def test_strategy_routes_to_strategy(self, router: IntentRouter):
        intent = Intent(content="What is our strategic roadmap for product market expansion?")
        route = router.classify(intent)
        assert route.role == "strategy"

    def test_unknown_defaults_to_general(self, router: IntentRouter):
        intent = Intent(content="What colour should the new office walls be?")
        route = router.classify(intent)
        assert route.role == "general"
        assert route.is_supported is True


# ---------------------------------------------------------------------------
# SpacebaseAdapter tests
# ---------------------------------------------------------------------------


class TestSpacebaseAdapter:
    """Tests for the adapter layer."""

    @pytest.mark.asyncio
    async def test_scan_intents_empty(self, adapter: SpacebaseAdapter):
        results = await adapter.scan_intents("empty-space")
        assert len(results) == 0

    @pytest.mark.asyncio
    async def test_scan_intents_with_seed(self, adapter: SpacebaseAdapter, finance_intent: Intent):
        adapter.client.seed_intent(finance_intent)
        results = await adapter.scan_intents(finance_intent.intent_id)
        assert len(results) == 1
        assert results[0]["route"].role == "finance"
        assert results[0]["is_new"] is True

    @pytest.mark.asyncio
    async def test_scan_intents_no_duplicates(self, adapter: SpacebaseAdapter, finance_intent: Intent):
        adapter.client.seed_intent(finance_intent)
        results1 = await adapter.scan_intents(finance_intent.intent_id)
        results2 = await adapter.scan_intents(finance_intent.intent_id)
        assert results1[0]["is_new"] is True
        assert results2[0]["is_new"] is False

    @pytest.mark.asyncio
    async def test_enter_space(self, adapter: SpacebaseAdapter):
        tree = await adapter.enter_space("nonexistent")
        assert tree is None

    @pytest.mark.asyncio
    async def test_post_child(self, adapter: SpacebaseAdapter):
        post = await adapter.post_child(
            parent_id="parent-1",
            title="Test Analysis",
            body="This is a test analysis body.",
            agent="analyst",
            confidence=0.85,
            produces=["report"],
            consumes=["data"],
            trace_id="trace-001",
        )
        assert post.agent == "analyst"
        assert post.confidence == 0.85
        assert post.produces == ["report"]
        assert post.consumes == ["data"]
        assert post.trace_id == "trace-001"

    @pytest.mark.asyncio
    async def test_run_council_finance(self, adapter: SpacebaseAdapter, finance_intent: Intent):
        adapter.client.seed_intent(finance_intent)
        report = await adapter.run_council(finance_intent, max_agents=3)
        assert isinstance(report, CouncilReport)
        assert report.root_intent_id == finance_intent.intent_id
        assert len(report.posts) > 0
        assert report.final_state == LockState.LOCKED
        assert report.trace_id != ""

    @pytest.mark.asyncio
    async def test_run_council_unsupported(self, adapter: SpacebaseAdapter, reject_intent: Intent):
        adapter.client.seed_intent(reject_intent)
        report = await adapter.run_council(reject_intent)
        assert report.final_state == LockState.FAILED

    @pytest.mark.asyncio
    async def test_run_council_creates_post_tree(
        self, adapter: SpacebaseAdapter, finance_intent: Intent
    ):
        adapter.client.seed_intent(finance_intent)
        report = await adapter.run_council(finance_intent)
        tree = await adapter.client.get_post_tree(finance_intent.intent_id)
        assert tree is not None
        assert len(tree.children) == len(report.posts)


# ---------------------------------------------------------------------------
# CouncilRunner tests
# ---------------------------------------------------------------------------


class TestCouncilRunner:
    """Tests for the council runner."""

    @pytest.mark.asyncio
    async def test_council_produces_multiple_posts(
        self, council_runner: CouncilRunner, adapter: SpacebaseAdapter, finance_intent: Intent
    ):
        adapter.client.seed_intent(finance_intent)
        route = adapter.router.classify(finance_intent)
        report = await council_runner.run(
            adapter=adapter,
            intent=finance_intent,
            route=route,
            trace_id="test-trace",
        )
        assert len(report.posts) >= 3  # at least analyst, contrarian, validator, summary

    @pytest.mark.asyncio
    async def test_council_includes_adversarial(
        self, council_runner: CouncilRunner, adapter: SpacebaseAdapter, finance_intent: Intent
    ):
        adapter.client.seed_intent(finance_intent)
        route = adapter.router.classify(finance_intent)
        report = await council_runner.run(
            adapter=adapter,
            intent=finance_intent,
            route=route,
            trace_id="test-trace",
        )
        agents = {p.agent for p in report.posts}
        assert "contrarian" in agents

    @pytest.mark.asyncio
    async def test_council_includes_validator(
        self, council_runner: CouncilRunner, adapter: SpacebaseAdapter, finance_intent: Intent
    ):
        adapter.client.seed_intent(finance_intent)
        route = adapter.router.classify(finance_intent)
        report = await council_runner.run(
            adapter=adapter,
            intent=finance_intent,
            route=route,
            trace_id="test-trace",
        )
        agents = {p.agent for p in report.posts}
        assert "compliance-validator" in agents

    @pytest.mark.asyncio
    async def test_council_final_state_locked(
        self, council_runner: CouncilRunner, adapter: SpacebaseAdapter, finance_intent: Intent
    ):
        adapter.client.seed_intent(finance_intent)
        route = adapter.router.classify(finance_intent)
        report = await council_runner.run(
            adapter=adapter,
            intent=finance_intent,
            route=route,
            trace_id="test-trace",
        )
        assert report.final_state == LockState.LOCKED

    @pytest.mark.asyncio
    async def test_council_report_to_markdown(
        self, council_runner: CouncilRunner, adapter: SpacebaseAdapter, finance_intent: Intent
    ):
        adapter.client.seed_intent(finance_intent)
        route = adapter.router.classify(finance_intent)
        report = await council_runner.run(
            adapter=adapter,
            intent=finance_intent,
            route=route,
            trace_id="test-trace",
        )
        md = report.to_markdown()
        assert "Council Report" in md
        assert finance_intent.intent_id in md
        assert report.trace_id in md

    @pytest.mark.asyncio
    async def test_council_trace_id_consistency(
        self, council_runner: CouncilRunner, adapter: SpacebaseAdapter, finance_intent: Intent
    ):
        adapter.client.seed_intent(finance_intent)
        route = adapter.router.classify(finance_intent)
        trace_id = "consistency-test-123"
        report = await council_runner.run(
            adapter=adapter,
            intent=finance_intent,
            route=route,
            trace_id=trace_id,
        )
        for post in report.posts:
            assert post.trace_id == trace_id

    @pytest.mark.asyncio
    async def test_council_max_agents(
        self, council_runner: CouncilRunner, adapter: SpacebaseAdapter, finance_intent: Intent
    ):
        adapter.client.seed_intent(finance_intent)
        route = adapter.router.classify(finance_intent)
        report = await council_runner.run(
            adapter=adapter,
            intent=finance_intent,
            route=route,
            trace_id="max-test",
            max_agents=2,
        )
        # Even with max_agents=2, we should have contrarian + validator + summary
        assert len(report.posts) >= 3


# ---------------------------------------------------------------------------
# Model tests
# ---------------------------------------------------------------------------


class TestModels:
    """Tests for data models."""

    def test_intent_creation(self):
        intent = Intent(content="test")
        assert intent.intent_id is not None
        assert intent.content == "test"

    def test_intent_to_itp_body(self):
        intent = Intent(content="test", payload={"key": "value"})
        body = intent.to_itp_body()
        assert body["content"] == "test"
        assert body["payload"]["key"] == "value"

    def test_post_creation(self):
        post = Post(
            intent_id="i1",
            title="Test",
            body="Body",
            agent="analyst",
            confidence=0.8,
            lock_state=LockState.PROVISIONAL,
        )
        assert post.agent == "analyst"
        assert post.lock_state == LockState.PROVISIONAL

    def test_post_to_payload(self):
        post = Post(
            intent_id="i1",
            title="Test",
            body="Body",
            agent="analyst",
            produces=["report"],
        )
        payload = post.to_payload()
        assert payload["agent"] == "analyst"
        assert payload["produces"] == ["report"]

    def test_post_tree_flatten(self):
        root_post = Post(post_id="root", intent_id="root", title="Root", body="")
        child1 = Post(post_id="c1", parent_id="root", intent_id="root", title="C1", body="")
        child2 = Post(post_id="c2", parent_id="root", intent_id="root", title="C2", body="")
        tree = PostTree(
            post=root_post,
            children=[
                PostTree(post=child1),
                PostTree(post=child2),
            ],
        )
        flat = tree.flatten()
        assert len(flat) == 3

    def test_post_tree_to_markdown(self):
        root_post = Post(post_id="root", intent_id="root", title="Root", body="", agent="system")
        child = Post(
            post_id="c1", parent_id="root", intent_id="root",
            title="Analysis", body="Detailed analysis here", agent="analyst",
            confidence=0.85, trace_id="t1", lock_state=LockState.PROVISIONAL,
        )
        tree = PostTree(post=root_post, children=[PostTree(post=child)])
        md = tree.to_markdown()
        assert "[analyst]" in md
        assert "PROVISIONAL" in md
        assert "t1" in md

    def test_lock_state_values(self):
        assert LockState.PROVISIONAL.value == "PROVISIONAL"
        assert LockState.LOCKED.value == "LOCKED"
        assert LockState.FAILED.value == "FAILED"


# ---------------------------------------------------------------------------
# Integration tests
# ---------------------------------------------------------------------------


class TestIntegration:
    """End-to-end integration tests."""

    @pytest.mark.asyncio
    async def test_full_council_lifecycle(self):
        """Test the full lifecycle: seed intent -> scan -> run council -> lock."""
        client = MockSpacebaseClient()
        root = Intent(
            intent_id="lifecycle-root",
            content="Should we invest in renewable energy infrastructure?",
            sender="test-user",
        )
        client.seed_intent(root)

        adapter = SpacebaseAdapter(client=client)

        # Scan
        results = await adapter.scan_intents("lifecycle-root")
        assert len(results) == 1
        assert results[0]["route"].is_supported

        # Run council
        report = await adapter.run_council(root)
        assert report.final_state == LockState.LOCKED
        assert len(report.posts) >= 3

        # Verify tree
        tree = await client.get_post_tree(root.intent_id)
        assert tree is not None
        assert len(tree.children) == len(report.posts)

        # Verify no duplicates on re-run
        results2 = await adapter.scan_intents("lifecycle-root")
        assert results2[0]["is_new"] is False

    @pytest.mark.asyncio
    async def test_failed_validation_leaves_provisional(self):
        """Test that a rejected intent leaves the room in FAILED state."""
        client = MockSpacebaseClient()
        reject = Intent(
            intent_id="reject-root",
            content="Please analyze my confidential employee salary records",
            sender="test-user",
        )
        client.seed_intent(reject)

        adapter = SpacebaseAdapter(client=client)
        report = await adapter.run_council(reject)
        assert report.final_state == LockState.FAILED
