"""Graph skeleton: routing, interrupts, approval and idempotency with mock nodes."""

import uuid

import pytest
from langgraph.checkpoint.memory import MemorySaver

from src.agent import nodes
from src.agent.graph import build_graph, config_for, decide, pending, reply, start
from src.agent.models import ActionProposal, ActionStatus, ActionType, AgentState

MARIA = "maria.papadopoulou@nimbus.com"  # Finance, Athens
EMP02 = "employee02@nimbus.com"


@pytest.fixture
def graph():
    return build_graph()


def new_config(email=MARIA):
    return config_for(str(uuid.uuid4()), email)


def test_policy_question_is_answered_with_latest_citation(graph):
    config = new_config(EMP02)
    result = start(graph, config, "What is the Wi-Fi policy for visitors?")
    assert pending(graph, config) is None
    assert result["action_proposal"].action_type == ActionType.ANSWER_POLICY
    assert result["policy_result"].doc_id == "POL-016"
    assert "POL-016 (effective 2026-01-05)" in result["final_response"]


def test_outage_links_instead_of_resetting(graph):
    config = new_config()
    result = start(graph, config, "I can't connect to the VPN, please reset my password")
    proposal = result["action_proposal"]
    assert proposal.action_type == ActionType.LINK_OUTAGE
    assert not proposal.requires_approval
    assert "Identity Provider (SSO)" in result["graph_result"].active_outages
    # Latest version of the reset policy, not v1.
    assert result["policy_result"].effective_date == "2026-09-01"


def test_missing_fields_ask_and_resume_with_reply(graph):
    config = new_config()
    result = start(graph, config, "Please reset my password")
    assert pending(graph, config) == "clarification"
    assert result["messages"][-1]["role"] == "assistant"
    assert "application" in result["clarification_question"]

    result = reply(graph, config, "It is the ERP System")
    assert result["extracted_fields"].application == "ERP System"
    assert pending(graph, config) == "approval"
    assert result["action_proposal"].action_type == ActionType.RESET_CREDENTIALS
    assert result["action_proposal"].status == ActionStatus.PENDING


def test_unknown_sender_is_asked_who_they_are(graph):
    config = new_config(email=None)
    result = start(graph, config, "The ERP System shows error 500")
    assert pending(graph, config) == "clarification"
    assert "who you are" in result["clarification_question"]


def test_extract_fields_missing_application_identifies_and_asks(graph):
    """Ensure missing application is accurately identified, never guessed, and pauses for clarification."""
    config = new_config()
    result = start(graph, config, "I am unable to login and my password expired")
    assert pending(graph, config) == "clarification"
    fields = result["extracted_fields"]
    assert fields.application is None
    assert "application" in fields.missing_fields()
    assert not fields.is_complete()
    assert fields.has_missing_fields
    assert "application or system" in result["clarification_question"]


def test_extract_fields_missing_employee_identifies_and_asks(graph):
    """Ensure missing employee identity is accurately identified, never guessed, and pauses for clarification."""
    config = new_config(email=None)
    result = start(graph, config, "The ERP System report export fails with error 500")
    assert pending(graph, config) == "clarification"
    fields = result["extracted_fields"]
    assert fields.employee is None
    assert "employee" in fields.missing_fields()
    assert not fields.is_complete()
    assert "who you are" in result["clarification_question"]


def test_extract_fields_missing_symptom_identifies_and_asks(graph):
    """Ensure intro/app without an observed symptom is accurately identified and prompts for the symptom."""
    config = new_config(email=None)
    result = start(graph, config, "Hello, I am Maria Papadopoulou on ERP System")
    assert pending(graph, config) == "clarification"
    fields = result["extracted_fields"]
    assert fields.employee == "Maria Papadopoulou"
    assert fields.application == "ERP System"
    assert fields.symptom is None
    assert fields.missing_fields() == ["symptom"]
    assert not fields.is_complete()
    assert "what is happening" in result["clarification_question"]

    # Replying with the symptom completes the fields and advances the graph
    result = reply(graph, config, "The application throws a 500 Internal Server Error when saving")
    assert result["extracted_fields"].is_complete()
    assert pending(graph, config) == "approval"


def test_extract_fields_multiple_missing_fields_asks_all(graph):
    """Ensure multiple missing fields are all detected and included in the clarification prompt."""
    config = new_config(email=None)
    result = start(graph, config, "Please help, I have an issue with error code 500")
    assert pending(graph, config) == "clarification"
    fields = result["extracted_fields"]
    assert "employee" in fields.missing_fields()
    assert "application" in fields.missing_fields()
    assert not fields.is_complete()
    assert "who you are" in result["clarification_question"]
    assert "application or system" in result["clarification_question"]


def test_extract_fields_employee_from_message_text(graph):
    """Ensure employee name mentioned in message text is extracted even without session email."""
    config = new_config(email=None)
    result = start(graph, config, "I am Maria Papadopoulou and ERP System report export fails")
    fields = result["extracted_fields"]
    assert fields.employee == "Maria Papadopoulou"
    assert fields.application == "ERP System"
    assert fields.is_complete()
    assert pending(graph, config) == "approval"


def test_extract_fields_urgency_detection(graph):
    """Ensure urgency is extracted as high when critical/urgent keywords appear, else None."""
    config = new_config()
    urgent_result = start(graph, config, "URGENT: ERP System is completely down with error 500")
    assert urgent_result["extracted_fields"].urgency == "high"

    config2 = new_config()
    normal_result = start(graph, config2, "The ERP System report export has an error")
    assert normal_result["extracted_fields"].urgency is None


def test_approved_action_executes_once(graph):
    config = new_config()
    start(graph, config, "My ERP System password is locked out, please reset it")
    assert pending(graph, config) == "approval"

    result = decide(graph, config, approved=True)
    assert pending(graph, config) is None
    assert result["action_proposal"].status == ActionStatus.EXECUTED
    assert result["action_proposal"].action_id in nodes.EXECUTED_ACTION_IDS


def test_rejected_action_is_not_executed(graph):
    config = new_config()
    start(graph, config, "My ERP System report export fails")
    assert graph.get_state(config).values["action_proposal"].action_type == ActionType.OPEN_TICKET

    result = decide(graph, config, approved=False)
    proposal = result["action_proposal"]
    assert proposal.status == ActionStatus.REJECTED
    assert proposal.action_id not in nodes.EXECUTED_ACTION_IDS
    assert "not approved" in result["final_response"]


def test_nothing_runs_before_approval(graph):
    config = new_config()
    start(graph, config, "My ERP System report export fails")
    proposal = graph.get_state(config).values["action_proposal"]
    assert proposal.status == ActionStatus.PENDING
    assert proposal.action_id not in nodes.EXECUTED_ACTION_IDS


def test_resume_after_restart_uses_checkpoint():
    """A new graph instance on the same checkpointer resumes the paused thread (restart)."""
    saver = MemorySaver()
    config = new_config()
    start(build_graph(saver), config, "My ERP System report export fails")

    restarted = build_graph(saver)
    assert pending(restarted, config) == "approval"
    result = decide(restarted, config, approved=True)
    assert result["action_proposal"].status == ActionStatus.EXECUTED


def test_execute_action_is_idempotent():
    proposal = ActionProposal(
        action_id=str(uuid.uuid4()),
        action_type=ActionType.OPEN_TICKET,
        status=ActionStatus.APPROVED,
        requires_approval=True,
    )
    first = nodes.execute_action(AgentState(action_proposal=proposal))["action_proposal"]
    # Same action_id arriving again (e.g. replay after a crash) must not run a second time.
    size = len(nodes.EXECUTED_ACTION_IDS)
    second = nodes.execute_action(AgentState(action_proposal=proposal))["action_proposal"]
    assert first.status == second.status == ActionStatus.EXECUTED
    assert len(nodes.EXECUTED_ACTION_IDS) == size
