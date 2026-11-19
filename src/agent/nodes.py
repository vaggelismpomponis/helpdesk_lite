"""Graph nodes. Each one is small and returns a partial update of AgentState.

Wired to real Knowledge tools (retrieve_policy via pgvector, check_graph via Neo4j).
"""

import json
from pathlib import Path
import re
import uuid

from langchain_core.runnables import RunnableConfig

from src.agent.models import (
    STATE_CHANGING_ACTIONS,
    ActionProposal,
    ActionStatus,
    ActionType,
    AgentState,
    ExtractedFields,
)
from src.knowledge.tools import (
    check_graph as knowledge_check_graph,
    retrieve_policy as knowledge_retrieve_policy,
)

DATA_DIR = Path(__file__).resolve().parents[1] / "data"
_GRAPH_SEED_PATH = DATA_DIR / "graph_seed.json"
_SEED_DATA = (
    json.loads(_GRAPH_SEED_PATH.read_text(encoding="utf-8"))
    if _GRAPH_SEED_PATH.exists()
    else {"applications": [], "services": [], "employees": []}
)


def find_application(text: str) -> str | None:
    """Canonical application name mentioned in the text."""
    lowered = text.lower()
    for app in _SEED_DATA["applications"]:
        aliases = {app["name"], app["name"].removeprefix("Corporate ")}
        if any(re.search(rf"\b{re.escape(a.lower())}\b", lowered) for a in aliases):
            return app["name"]
    for srv in _SEED_DATA["services"]:
        if re.search(rf"\b{re.escape(srv['name'].lower())}\b", lowered):
            return srv["name"]
    if "docker desktop" in lowered or "docker" in lowered:
        return "Docker Desktop"
    return None


def find_employee(email: str | None = None, text: str | None = None) -> str | None:
    """Resolve employee identity from session email or message text."""
    if email:
        match = next((e["name"] for e in _SEED_DATA["employees"] if e["email"] == email), None)
        if match:
            return match
    if text:
        lowered = text.lower()
        for emp in _SEED_DATA["employees"]:
            email_match = emp["email"].lower()
            name_match = emp["name"].lower()
            if email_match in lowered or re.search(rf"\b{re.escape(name_match)}\b", lowered):
                return emp["name"]
    return None

QUESTION_WORDS = ("what", "how", "do", "does", "is", "are", "can", "which", "when", "where", "who")
REQUEST_PREFIXES = ("can you", "could you", "would you", "will you", "can i get", "please")
RESET_WORDS = ("reset", "password", "locked out", "credential")
CRITICAL_WORDS = ("critical", "production down", "data breach", "security incident")
CLARIFICATION_QUESTION = "Which application or system is affected?"
FIELD_PROMPTS = {
    "employee": "who you are (name or work email)",
    "application": "which application or system is affected",
    "symptom": "what is happening (the error or symptom)",
}

SYMPTOM_INDICATORS = (
    "error", "fail", "stuck", "broken", "crash", "down", "slow", "locked",
    "lockout", "freeze", "reset", "credential", "password", "access",
    "license", "install", "connect", "lost", "help", "export", "outbox",
    "500", "403", "404", "cannot", "can't", "unable", "won't", "doesn't work",
    "issue", "problem", "bug", "trouble", "incident", "offline", "outage"
)

GREETING_PATTERNS = [
    r"\b(?:hello|hi|hey|good\s+(?:morning|afternoon|evening))\b",
    r"\bmy\s+name\s+is\b",
    r"\bi\s+am\b",
    r"\bi'm\b",
    r"\bthis\s+is\b",
]

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


def _extract_symptom(text: str, application: str | None = None, employee: str | None = None) -> str | None:
    """Extract observed symptom or error description without guessing or hallucinating."""
    raw = text.strip()
    if not raw:
        return None
    lowered = raw.lower()
    if any(re.search(rf"\b{re.escape(kw)}\b", lowered) for kw in SYMPTOM_INDICATORS):
        return raw

    # Check if text only contains identity/greetings and application without describing a symptom
    cleaned = lowered
    for pat in GREETING_PATTERNS:
        cleaned = re.sub(pat, " ", cleaned)
    if employee:
        cleaned = re.sub(rf"\b{re.escape(employee.lower())}\b", " ", cleaned)
    if application:
        cleaned = re.sub(rf"\b{re.escape(application.lower())}\b", " ", cleaned)

    cleaned_words = [
        w for w in re.findall(r"\b[a-z0-9]+\b", cleaned)
        if w not in ("on", "in", "from", "at", "the", "a", "an", "for", "with", "to", "and", "system", "app")
    ]
    if len(cleaned_words) < 3:
        return None
    return raw


def extract_fields(state: AgentState, config: RunnableConfig) -> dict:
    """Extract fields using Pydantic schema and enforce 'ask if missing' rule."""
    text = _user_text(state)
    lowered = text.lower()

    # 1. Resolve employee: session config takes precedence, fallback to message text
    user_email = config.get("configurable", {}).get("user_email")
    employee = find_employee(email=user_email, text=text)

    # 2. Resolve application: match against known applications and aliases
    application = find_application(text)

    # 3. Resolve symptom: extract observed issue without guessing
    symptom = _extract_symptom(text, application=application, employee=employee)

    # 4. Resolve urgency: optional triage field
    urgency = "high" if any(w in lowered for w in ("urgent", "asap", "critical", "emergency", "production down")) else None

    # Construct Pydantic model with optional fields
    fields = ExtractedFields(
        employee=employee,
        application=application,
        symptom=symptom,
        urgency=urgency,
    )

    # 5. Enforce strict "Ask if Missing" rule:
    # Policy questions do not need triage fields; incident requests require all mandatory fields.
    if is_question(text):
        missing = []
    else:
        missing = fields.missing_fields()

    question = f"To help you, please tell me {' and '.join(FIELD_PROMPTS[f] for f in missing)}." if missing else None
    return {
        "extracted_fields": fields,
        "needs_clarification": bool(missing),
        "clarification_question": question,
    }


def ask_clarification(state: AgentState) -> dict:
    """Posts the question. The graph pauses after this node until the user replies."""
    return {"messages": [*state.messages, {"role": "assistant", "content": state.clarification_question}]}


def retrieve_policy(state: AgentState) -> dict:
    fields = state.extracted_fields
    text = _user_text(state)
    query = fields.symptom or text
    if not query.strip():
        return {"policy_result": None}

    # Avoid prepending application when the query is about credentials/passwords,
    # so semantic search returns the credential reset policy instead of app docs.
    app = (
        None
        if any(w in query.lower() for w in ("password", "credential", "reset", "lockout", "locked"))
        else fields.application
    )
    return {"policy_result": knowledge_retrieve_policy(query, app)}


def check_graph(state: AgentState) -> dict:
    application = state.extracted_fields.application
    return {"graph_result": knowledge_check_graph(application) if application else None}


def _choose_action(state: AgentState) -> tuple[ActionType, str]:
    """Decision Precedence Matrix (contract section 5); clarification is handled by routing."""
    text = _user_text(state).lower()
    if state.graph_result and state.graph_result.has_active_outage:
        return ActionType.LINK_OUTAGE, f"Active outage on {', '.join(state.graph_result.active_outages)}"
    if state.policy_result and is_question(_user_text(state)):
        return ActionType.ANSWER_POLICY, f"Policy {state.policy_result.doc_id} answers the question"
    if any(w in text for w in RESET_WORDS):
        return ActionType.RESET_CREDENTIALS, "Credential reset requested and no outage explains it"
    if any(w in text for w in CRITICAL_WORDS) or "no assigned team" in text or "escalate" in text:
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
