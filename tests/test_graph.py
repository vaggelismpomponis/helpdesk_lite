"""Graph skeleton and completion: routing, interrupts, approval, idempotency, and live Knowledge tools."""

import uuid

import pytest
from langgraph.checkpoint.memory import MemorySaver

from src.agent import nodes
from src.agent.graph import (
    build_graph,
    config_for,
    decide,
    get_production_graph,
    pending,
    reply,
    start,
)
from src.agent.models import ActionProposal, ActionStatus, ActionType, AgentState
from src.db.checkpointer import PostgresSaver
from src.db.connection import get_pooled_connection, is_postgres_available

MARIA = "maria.papadopoulou@nimbus.com"  # Finance, Athens
EMP02 = "employee02@nimbus.com"
# Office and device complete an incident request (POL-001: confirm them before acting).
AT_DESK = " I work from the Athens office on my MacBook Pro."

requires_postgres = pytest.mark.skipif(
    not is_postgres_available(),
    reason="Live PostgreSQL database not available at localhost:5432",
)


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


def test_polite_request_is_not_a_policy_question(graph):
    config = new_config()
    start(graph, config, "Can you reset my ERP System password?" + AT_DESK)
    assert pending(graph, config) == "approval"
    assert graph.get_state(config).values["action_proposal"].action_type == ActionType.RESET_CREDENTIALS


def test_outage_links_instead_of_resetting(graph):
    config = new_config()
    result = start(graph, config, "I can't connect to the VPN, please reset my password" + AT_DESK)
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
    assert "which office" in result["clarification_question"]
    assert "which device" in result["clarification_question"]

    result = reply(graph, config, "It is the ERP System." + AT_DESK)
    assert result["extracted_fields"].application == "ERP System"
    assert pending(graph, config) == "approval"
    assert result["action_proposal"].action_type == ActionType.RESET_CREDENTIALS
    assert result["action_proposal"].status == ActionStatus.PENDING


def test_graph_pauses_at_clarification_interrupt(graph):
    """Execution pauses at ask_clarification interrupt node when mandatory fields are missing."""
    config = new_config()
    result = start(graph, config, "Please reset my credentials")
    # Verify paused state and interrupt configuration
    assert pending(graph, config) == "clarification"
    snapshot = graph.get_state(config)
    assert "extract_fields" in snapshot.next
    assert snapshot.values["needs_clarification"] is True
    assert "which office" in snapshot.values["clarification_question"]
    # Check that assistant question is queued
    assert result["messages"][-1]["role"] == "assistant"
    assert result["messages"][-1]["content"] == snapshot.values["clarification_question"]


def test_graph_pauses_at_approval_interrupt(graph):
    """Execution pauses at human_approval interrupt node before executing state-changing actions."""
    config = new_config()
    start(graph, config, "My ERP System password is locked out, please reset it" + AT_DESK)
    assert pending(graph, config) == "approval"
    snapshot = graph.get_state(config)
    assert "human_approval" in snapshot.next
    proposal = snapshot.values["action_proposal"]
    assert proposal.requires_approval is True
    assert proposal.status == ActionStatus.PENDING
    assert proposal.action_id not in nodes.EXECUTED_ACTION_IDS


def test_graph_resumes_cleanly_upon_clarification_reply(graph):
    """Workflow resumes upon user reply, updates state, and advances to subsequent nodes."""
    config = new_config()
    start(graph, config, "Please reset my password")
    assert pending(graph, config) == "clarification"

    # User replies with the missing office and device
    result = reply(graph, config, "The system is ERP System." + AT_DESK)
    assert result["extracted_fields"].application == "ERP System"
    assert result["needs_clarification"] is False
    # Next interrupt reached: human approval
    assert pending(graph, config) == "approval"
    assert result["action_proposal"].action_type == ActionType.RESET_CREDENTIALS


def test_graph_resumes_cleanly_upon_approval_decision(graph):
    """Workflow resumes upon operator decision, executes action, and produces final response."""
    config = new_config()
    start(graph, config, "My ERP System password is locked out, please reset it" + AT_DESK)
    assert pending(graph, config) == "approval"

    result = decide(graph, config, approved=True)
    assert pending(graph, config) is None
    assert result["action_proposal"].status == ActionStatus.EXECUTED
    assert result["action_proposal"].action_id in nodes.EXECUTED_ACTION_IDS
    assert "Action: reset_credentials [executed]" in result["final_response"]


def test_unknown_sender_is_asked_who_they_are(graph):
    config = new_config(email=None)
    result = start(graph, config, "The ERP System shows error 500")
    assert pending(graph, config) == "clarification"
    assert "who you are" in result["clarification_question"]


def test_extract_fields_missing_office_and_device_identifies_and_asks(graph):
    """Office and device are never guessed from the employee record: the user must confirm them."""
    config = new_config()  # Maria's record says Athens / MacBook Pro, but she did not say so
    result = start(graph, config, "I am unable to login and my password expired")
    assert pending(graph, config) == "clarification"
    fields = result["extracted_fields"]
    assert fields.office is None and fields.device is None
    assert fields.missing_fields() == ["office", "device"]
    assert not fields.is_complete()
    assert fields.has_missing_fields
    assert "which office" in result["clarification_question"]
    assert "which device" in result["clarification_question"]


def test_application_is_optional(graph):
    """A request that names no known application is still complete and gets a ticket."""
    config = new_config()
    result = start(graph, config, "My second monitor stopped working this morning." + AT_DESK)
    assert result["extracted_fields"].application is None
    assert result["extracted_fields"].is_complete()
    assert pending(graph, config) == "approval"
    assert result["action_proposal"].action_type == ActionType.OPEN_TICKET
    assert result["policy_result"].doc_id == "POL-004"  # governing policy of open_ticket


def test_license_request_cites_ticket_policy(graph):
    config = new_config()
    result = start(graph, config, "I need a Docker Desktop license installed." + AT_DESK)
    assert result["action_proposal"].action_type == ActionType.OPEN_TICKET
    assert result["policy_result"].doc_id == "POL-004"


def test_outage_without_matching_policy_cites_outage_policy(graph):
    """When the request matches no policy, the policy governing the action is cited."""
    config = new_config()
    result = start(graph, config, "My outgoing emails in Email & Calendar are stuck in the outbox." + AT_DESK)
    assert result["action_proposal"].action_type == ActionType.LINK_OUTAGE
    assert result["policy_result"].doc_id == "POL-003"
    assert "POL-003" in result["final_response"]


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
    assert fields.missing_fields() == ["symptom", "office", "device"]
    assert not fields.is_complete()
    assert "what is happening" in result["clarification_question"]

    # Replying with the symptom, office and device completes the fields and advances the graph
    result = reply(graph, config, "The application throws a 500 Internal Server Error when saving." + AT_DESK)
    assert result["extracted_fields"].is_complete()
    assert pending(graph, config) == "approval"


def test_extract_fields_multiple_missing_fields_asks_all(graph):
    """Ensure multiple missing fields are all detected and included in the clarification prompt."""
    config = new_config(email=None)
    result = start(graph, config, "Please help, I have an issue with error code 500")
    assert pending(graph, config) == "clarification"
    fields = result["extracted_fields"]
    assert fields.missing_fields() == ["employee", "office", "device"]
    assert not fields.is_complete()
    assert "who you are" in result["clarification_question"]
    assert "which office" in result["clarification_question"]


def test_extract_fields_employee_from_message_text(graph):
    """Ensure employee name mentioned in message text is extracted even without session email."""
    config = new_config(email=None)
    result = start(graph, config, "I am Maria Papadopoulou and ERP System report export fails" + AT_DESK)
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
    start(graph, config, "My ERP System password is locked out, please reset it" + AT_DESK)
    assert pending(graph, config) == "approval"

    result = decide(graph, config, approved=True)
    assert pending(graph, config) is None
    assert result["action_proposal"].status == ActionStatus.EXECUTED
    assert result["action_proposal"].action_id in nodes.EXECUTED_ACTION_IDS


def test_rejected_action_is_not_executed(graph):
    config = new_config()
    start(graph, config, "My ERP System report export fails" + AT_DESK)
    assert graph.get_state(config).values["action_proposal"].action_type == ActionType.OPEN_TICKET

    result = decide(graph, config, approved=False)
    proposal = result["action_proposal"]
    assert proposal.status == ActionStatus.REJECTED
    assert proposal.action_id not in nodes.EXECUTED_ACTION_IDS
    assert "not approved" in result["final_response"]


def test_nothing_runs_before_approval(graph):
    config = new_config()
    start(graph, config, "My ERP System report export fails" + AT_DESK)
    proposal = graph.get_state(config).values["action_proposal"]
    assert proposal.status == ActionStatus.PENDING
    assert proposal.action_id not in nodes.EXECUTED_ACTION_IDS


def test_resume_after_restart_uses_checkpoint():
    """A new graph instance on the same checkpointer resumes the paused thread (restart)."""
    saver = MemorySaver()
    config = new_config()
    start(build_graph(saver), config, "My ERP System report export fails" + AT_DESK)

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


@requires_postgres
def test_graph_persists_durably_in_postgres_checkpoints_table():
    """State persists durably in PostgreSQL checkpoints & checkpoint_blobs tables ✋."""
    saver = PostgresSaver()
    graph = build_graph(saver)
    config = new_config()
    thread_id = config["configurable"]["thread_id"]

    start(graph, config, "Please reset my password")
    assert pending(graph, config) == "clarification"

    # Query Postgres database directly to confirm durable persistence
    with get_pooled_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT COUNT(*) FROM checkpoints WHERE thread_id = %s;",
                (thread_id,),
            )
            checkpoint_count = cur.fetchone()[0]
            assert checkpoint_count > 0, "Checkpoints must be recorded in Postgres checkpoints table"

            cur.execute(
                "SELECT COUNT(*) FROM checkpoint_blobs WHERE thread_id = %s;",
                (thread_id,),
            )
            blob_count = cur.fetchone()[0]
            assert blob_count > 0, "Channel blobs must be recorded in Postgres checkpoint_blobs table"


@requires_postgres
def test_graph_resumes_across_process_restart_with_postgres():
    """Graph resumes seamlessly across simulated process restarts using persistent PostgresSaver."""
    config = new_config()
    thread_id = config["configurable"]["thread_id"]

    # --- Process 1: Start workflow, interrupt at clarification ---
    g1 = build_graph(use_postgres=True)
    start(g1, config, "Please reset my password")
    assert pending(g1, config) == "clarification"
    del g1  # Simulate process termination

    # --- Process 2: Restart, reload state from Postgres, resume with user reply ---
    g2 = build_graph(use_postgres=True)
    assert pending(g2, config) == "clarification"
    res2 = reply(g2, config, "It is the ERP System." + AT_DESK)
    assert pending(g2, config) == "approval"
    assert res2["extracted_fields"].application == "ERP System"
    assert res2["action_proposal"].action_type == ActionType.RESET_CREDENTIALS
    del g2  # Simulate second process termination

    # --- Process 3: Restart again, reload state from Postgres, resume with operator approval ---
    g3 = build_graph(use_postgres=True)
    assert pending(g3, config) == "approval"
    res3 = decide(g3, config, approved=True)
    assert pending(g3, config) is None
    assert res3["action_proposal"].status == ActionStatus.EXECUTED
    assert "Action: reset_credentials [executed]" in res3["final_response"]


def test_build_graph_use_postgres_factory():
    """build_graph with use_postgres=True and get_production_graph initialize cleanly."""
    prod_graph = get_production_graph()
    assert prod_graph is not None

    pg_graph = build_graph(use_postgres=True)
    assert pg_graph is not None


# ==============================================================================
# Step 8 / Issue #28: Live Knowledge Tools Integration & Mocks Decommissioning
# ==============================================================================


def test_mocks_completely_decommissioned_from_nodes():
    """Verify that nodes module does not import or depend on src.agent.mocks."""
    assert "mocks" not in nodes.__dict__, "src.agent.nodes must not import or contain 'mocks'"
    import inspect
    source = inspect.getsource(nodes)
    assert "import mocks" not in source, "src.agent.nodes must not import mocks"
    assert "from src.agent import mocks" not in source, "src.agent.nodes must not import mocks from src.agent"


@requires_postgres
def test_live_retrieve_policy_and_check_graph_state_transitions(graph):
    """Validate live pgvector and Neo4j queries execute in graph state transitions."""
    config = new_config()
    # Live outage on Corporate VPN -> Identity Provider (SSO)
    result = start(graph, config, "I cannot connect to Corporate VPN, please reset my password" + AT_DESK)
    assert result["graph_result"] is not None
    assert result["graph_result"].found is True
    assert "Identity Provider (SSO)" in result["graph_result"].active_outages
    assert result["graph_result"].has_active_outage is True

    # Real policy retrieval from pgvector (citations with doc_id, effective_date, source)
    assert result["policy_result"] is not None
    assert result["policy_result"].doc_id in ("POL-001", "POL-002")
    assert result["policy_result"].effective_date is not None
    assert result["policy_result"].source.endswith(".md")

    # Action proposal decided based on live tools
    proposal = result["action_proposal"]
    assert proposal.action_type == ActionType.LINK_OUTAGE
    assert proposal.requires_approval is False


# ==============================================================================
# Step 9 / Issue #29: Decision Rules (Active Outage -> Link to Outage)
# ==============================================================================


def test_decision_rules_active_outage_inhibits_credential_reset(graph):
    """Enforce strict rule: active outage on dependent service MUST propose link_outage (NEVER reset_credentials)."""
    config = new_config()
    result = start(graph, config, "Corporate VPN credentials not working, please reset my password" + AT_DESK)
    proposal = result["action_proposal"]

    # Acceptance criteria: active outage triggers link to outage
    assert proposal.action_type == ActionType.LINK_OUTAGE
    # Acceptance criteria: credential reset is strictly inhibited
    assert proposal.action_type != ActionType.RESET_CREDENTIALS
    assert not proposal.requires_approval
    assert proposal.status == ActionStatus.APPROVED
    assert "inhibited" in proposal.rationale.lower()
    assert "Identity Provider (SSO)" in proposal.rationale
    assert "Identity Provider (SSO)" in result["graph_result"].active_outages
    assert "link_outage" in result["final_response"]


def test_decision_rules_multiple_applications_in_dependency_tree(graph):
    """Evaluate service dependency tree across different applications sharing degraded service."""
    # Finance Portal depends on SRV-01 (Identity Provider (SSO) with OPEN outage)
    config1 = new_config()
    res1 = start(graph, config1, "Finance Portal login failed, please reset my password" + AT_DESK)
    assert res1["action_proposal"].action_type == ActionType.LINK_OUTAGE
    assert res1["action_proposal"].action_type != ActionType.RESET_CREDENTIALS

    # GitHub Enterprise also depends on SRV-01 (Identity Provider (SSO))
    config2 = new_config()
    res2 = start(graph, config2, "GitHub Enterprise account locked out, need password reset" + AT_DESK)
    assert res2["action_proposal"].action_type == ActionType.LINK_OUTAGE
    assert res2["action_proposal"].action_type != ActionType.RESET_CREDENTIALS


def test_decision_rules_healthy_service_allows_credential_reset(graph):
    """When dependent services are operational (no outages), credential reset proceeds normally with approval."""
    # ERP System depends on SRV-03 (PostgreSQL) and SRV-07 (API Gateway), neither has an active outage
    config = new_config()
    result = start(graph, config, "My ERP System password expired, please reset my credentials" + AT_DESK)
    proposal = result["action_proposal"]

    assert proposal.action_type == ActionType.RESET_CREDENTIALS
    assert proposal.requires_approval is True
    assert proposal.status == ActionStatus.PENDING
    assert pending(graph, config) == "approval"


def test_decision_rules_direct_service_outage(graph):
    """Direct mention of degraded service triggers link to outage."""
    config = new_config()
    result = start(graph, config, "Identity Provider (SSO) is broken, please reset my password" + AT_DESK)
    proposal = result["action_proposal"]

    assert proposal.action_type == ActionType.LINK_OUTAGE
    assert proposal.requires_approval is False


def test_decision_rules_outage_proposal_parameters(graph):
    """ActionProposal parameters contain outage tracking metadata."""
    config = new_config()
    result = start(graph, config, "I cannot connect to Corporate VPN, reset my password" + AT_DESK)
    params = result["action_proposal"].parameters

    assert "Identity Provider (SSO)" in params.get("active_outages", [])
    assert params.get("outage_id") == "OUT-2026-01"


