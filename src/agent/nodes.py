"""Graph nodes. Each one is small and returns a partial update of AgentState.

extract_fields and decide_action use mock rules for now; the LLM and the real tools come later.
"""

import uuid

from langchain_core.runnables import RunnableConfig

from src.agent import mocks
from src.agent.models import (
    STATE_CHANGING_ACTIONS,
    ActionProposal,
    ActionStatus,
    ActionType,
    AgentState,
    ExtractedFields,
)

QUESTION_WORDS = ("what", "how", "do", "does", "is", "are", "can", "which", "when", "where", "who")
REQUEST_PREFIXES = ("can you", "could you", "would you", "will you", "can i get", "please")
RESET_WORDS =("reset", "password", "locked out", "credential")
CRITICAL_WORDS = ("critical", "production down", "data breach", "security incident")
CLARIFICATION_QUESTION = "Which application or system is affected?"

# Stand-in for the Postgres action table until step 10 (idempotent execution).
EXECUTED_ACTION_IDS: set[str] = set()


def _user_text(state: AgentState) -> str:
    return "\n".join(m["content"] for m in state.messages if m.get("role") == "user")


def is_question(text: str) -> bool:
    """Information question ("What is...?"), not a polite request ("Can you reset...?")."""
    lowered = text.strip().lower()
    if lowered.startswith(REQUEST_PREFIXES):
        return False
    words = lowered.split()
    return bool(words) and words[0] in QUESTION_WORDS and lowered.endswith("?")


def extract_fields(state: AgentState, config: RunnableConfig) -> dict:
    """Mock extraction: asks for clarification only when a request names no application.

    The full rule (optional fields, ask for any missing one, never guess) is issue #25.
    """
    text = _user_text(state)
    fields = ExtractedFields(
        # The sender comes from the Chainlit session, passed in config["configurable"]["user_email"].
        employee=config.get("configurable", {}).get("user_email"),
        application=mocks.find_application(text),
        symptom=text.strip() or None,
    )
    needs_clarification = fields.application is None and not is_question(text)
    return {
        "extracted_fields": fields,
        "needs_clarification": needs_clarification,
        "clarification_question": CLARIFICATION_QUESTION if needs_clarification else None,
    }


def ask_clarification(state: AgentState) -> dict:
    """Posts the question. The graph pauses after this node until the user replies."""
    return {"messages": [*state.messages, {"role": "assistant", "content": state.clarification_question}]}


def retrieve_policy(state: AgentState) -> dict:
    fields = state.extracted_fields
    return {"policy_result": mocks.retrieve_policy(fields.symptom or "", fields.application)}


def check_graph(state: AgentState) -> dict:
    application = state.extracted_fields.application
    return {"graph_result": mocks.check_graph(application) if application else None}


def _choose_action(state: AgentState) -> tuple[ActionType, str]:
    """Decision Precedence Matrix (contract section 5); clarification is handled by routing."""
    text = _user_text(state).lower()
    if state.graph_result and state.graph_result.has_active_outage:
        return ActionType.LINK_OUTAGE, f"Active outage on {', '.join(state.graph_result.active_outages)}"
    if state.policy_result and is_question(_user_text(state)):
        return ActionType.ANSWER_POLICY, f"Policy {state.policy_result.doc_id} answers the question"
    if any(w in text for w in RESET_WORDS):
        return ActionType.RESET_CREDENTIALS, "Credential reset requested and no outage explains it"
    if any(w in text for w in CRITICAL_WORDS):
        return ActionType.ESCALATE, "Critical incident"
    return ActionType.OPEN_TICKET, "Standard issue requiring investigation"


def decide_action(state: AgentState) -> dict:
    action_type, rationale = _choose_action(state)
    needs_approval = action_type in STATE_CHANGING_ACTIONS
    proposal = ActionProposal(
        action_id=str(uuid.uuid4()),
        action_type=action_type,
        parameters={
            "employee": state.extracted_fields.employee,
            "application": state.extracted_fields.application,
        },
        # Informational actions need no human approval, so they start approved.
        status=ActionStatus.PENDING if needs_approval else ActionStatus.APPROVED,
        requires_approval=needs_approval,
        rationale=rationale,
    )
    return {"action_proposal": proposal}


# langgraph 0.2.45 rejects empty updates, so unchanged nodes return the proposal as is.


def human_approval(state: AgentState) -> dict:
    """Runs after the operator's decision was written into action_proposal.status.

    Anything other than an explicit approval counts as a rejection.
    """
    proposal = state.action_proposal
    if proposal.status != ActionStatus.APPROVED:
        return {"action_proposal": proposal.model_copy(update={"status": ActionStatus.REJECTED})}
    return {"action_proposal": proposal}


def execute_action(state: AgentState) -> dict:
    proposal = state.action_proposal
    # Idempotency: never run an action twice, and never run one that is not approved.
    if proposal.status == ActionStatus.EXECUTED or proposal.action_id in EXECUTED_ACTION_IDS:
        return {"action_proposal": proposal.model_copy(update={"status": ActionStatus.EXECUTED})}
    if proposal.status != ActionStatus.APPROVED:
        return {"action_proposal": proposal}
    EXECUTED_ACTION_IDS.add(proposal.action_id)  # mock side effect (ticket, reset, escalation)
    return {"action_proposal": proposal.model_copy(update={"status": ActionStatus.EXECUTED})}


def respond(state: AgentState) -> dict:
    proposal = state.action_proposal
    parts = [f"Action: {proposal.action_type.value} [{proposal.status.value}]. {proposal.rationale}."]
    if proposal.action_type == ActionType.LINK_OUTAGE:
        parts.append("Your request was linked to the open outage; no credential reset is needed.")
    if proposal.status == ActionStatus.REJECTED:
        parts.append("The action was not approved, so nothing was changed.")
    if state.policy_result:
        parts.append(f"Source: {state.policy_result.doc_id} (effective {state.policy_result.effective_date}).")
    text = " ".join(parts)
    return {"final_response": text, "messages": [*state.messages, {"role": "assistant", "content": text}]}
