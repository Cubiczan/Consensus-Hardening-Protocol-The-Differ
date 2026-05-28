"""Basic import tests for consensus-hardening-protocol-differ.

Validates that core modules can be imported without errors.
"""

def test_import_cme_package():
    """Test that the CME package imports with version."""
    from cme import __version__
    assert __version__ == "0.3.0"


def test_import_chp():
    """Test that the CHP module imports with classes."""
    from cme.chp_locks import CHPGate, CHPResult
    assert CHPGate is not None
    assert CHPResult is not None


def test_chp_gate_enum_values():
    """Test that CHPGate has expected enum values."""
    from cme.chp_locks import CHPGate
    assert CHPGate.MULTIPLE_PERSPECTIVES.value == "multiple_perspectives"
    assert CHPGate.ADVERSARIAL_CHALLENGE.value == "adversarial_challenge"
    assert CHPGate.HUMAN_REVIEW.value == "human_review"


def test_chp_result_initial_state():
    """Test that CHPResult starts in invalid state."""
    from cme.chp_locks import CHPResult
    result = CHPResult()
    assert result.is_valid is False
    assert result.is_locked is False


def test_chp_result_pass_all_gates():
    """Test passing all required gates makes result valid."""
    from cme.chp_locks import CHPGate, CHPResult
    result = CHPResult()
    for gate in CHPGate:
        if gate != CHPGate.HUMAN_REVIEW:
            result.pass_gate(gate)
    assert result.is_valid is True


def test_import_orchestrator():
    """Test that the orchestrator module imports."""
    from cme.orchestrator import TurnResult, Workflow, TurnPhase, TurnStatus
    assert TurnResult is not None
    assert Workflow is not None
    assert TurnPhase is not None
    assert TurnStatus is not None


def test_workflow_add_turn():
    """Test adding a turn to a workflow."""
    from cme.orchestrator import TurnResult, Workflow, TurnPhase, TurnStatus
    wf = Workflow()
    turn = TurnResult(agent="analyst", phase=TurnPhase.EXPANSION, status=TurnStatus.SUCCESS, confidence=0.9)
    wf.add_turn(turn)
    assert len(wf.turns) == 1
    assert wf.confidence == 0.9
    assert wf.lock_state == "LOCKED"


def test_workflow_failed_state():
    """Test that a failed turn sets workflow to FAILED state."""
    from cme.orchestrator import TurnResult, Workflow, TurnPhase, TurnStatus
    wf = Workflow()
    turn = TurnResult(agent="reviewer", phase=TurnPhase.VALIDATION, status=TurnStatus.FAILED)
    wf.add_turn(turn)
    assert wf.lock_state == "FAILED"
