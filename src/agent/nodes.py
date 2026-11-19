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


OFFICES = sorted({e["office"] for e in _SEED_DATA["employees"] if "office" in e})
DEVICES = sorted({e["device"] for e in _SEED_DATA["employees"] if "device" in e})

# Policy that governs an action, cited when the request itself matched no policy.
POLICY_BY_ACTION = {
    "link_outage": "POL-003",
    "open_ticket": "POL-004",
    "escalate": "POL-005",
}


def _find_known(options: list[str], text: str) -> str | None:
    lowered = text.lower()
    return next((o for o in options if re.search(rf"\b{re.escape(o.lower())}\b", lowered)), None)


def find_office(text: str) -> str | None:
    """Office named in the text. Taken from the message only: the user must confirm it (POL-001)."""
    return _find_known(OFFICES, text)


def find_device(text: str) -> str | None:
    """Device named in the text. Taken from the message only: the user must confirm it (POL-001)."""
    return _find_known(DEVICES, text)


def policy_by_id(doc_id: str):
    """Latest version of a policy by doc_id, querying pgvector with fallback to policy files."""
    if not doc_id:
        return None
    try:
        from src.knowledge.common import pg
        with pg() as conn:
            row = conn.execute(
                """
                WITH latest AS (
                    SELECT doc_id, max(effective_date) AS effective_date
                    FROM policy_chunks WHERE doc_id = %s AND effective_date <= current_date GROUP BY doc_id
                )
                SELECT c.content, c.doc_id, c.effective_date, c.source
                FROM policy_chunks c JOIN latest USING (doc_id, effective_date)
                LIMIT 1;
                """,
                (doc_id,),
            ).fetchone()
            if row:
                from src.knowledge.models import PolicyResult
                return PolicyResult(text=row[0], doc_id=row[1], effective_date=row[2].isoformat(), source=row[3])
    except Exception:
        pass

    # Fallback to local files if database is unreachable
    versions = sorted(DATA_DIR.glob(f"policies/{doc_id}_*.md"))
    if versions:
        path = versions[-1]
        match = re.match(r"---\r?\n(.*?)\r?\n---\r?\n(.*)", path.read_text(encoding="utf-8"), re.S)
        if match:
            lines = (line.split(":", 1) for line in match[1].splitlines() if ":" in line)
            meta = {k.strip(): v.strip().strip('"') for k, v in lines}
            from src.knowledge.models import PolicyResult
            return PolicyResult(
                text=match[2][:800].strip(),
                doc_id=meta.get("doc_id", doc_id),
                effective_date=meta.get("effective_date", ""),
                source=path.name,
            )
    return None


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
    "symptom": "what is happening (the error or symptom)",
    "office": "which office you are working from",
    "device": "which device you are using",
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


def _extract_symptom(
    text: str, application: str | None = None, employee: str | None = None, *context: str | None
) -> str | None:
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
    for known in context:  # office and device are context, not a symptom
        if known:
            cleaned = re.sub(rf"\b{re.escape(known.lower())}\b", " ", cleaned)

    cleaned_words = [
        w for w in re.findall(r"\b[a-z0-9]+\b", cleaned)
        if w not in (
            "on", "in", "from", "at", "the", "a", "an", "for", "with", "to", "and", "system", "app",
            "office", "my", "using", "working", "work",
        )
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

    # 3. Resolve office and device: from the message only, the user must confirm them (POL-001)
    office, device = find_office(text), find_device(text)

    # 4. Resolve symptom: extract observed issue without guessing
    symptom = _extract_symptom(text, application, employee, office, device)

    # 5. Resolve urgency: optional triage field
    urgency = "high" if any(w in lowered for w in ("urgent", "asap", "critical", "emergency", "production down")) else None

    fields = ExtractedFields(
        employee=employee,
        application=application,
        symptom=symptom,
        urgency=urgency,
        office=office,
        device=device,
    )

    # 6. Enforce strict "Ask if Missing" rule:
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


FALLBACK_POLICY_KEYWORDS = [
    ("wi-fi", "POL-016"),
    ("travel", "POL-008"),
    ("cloud storage", "POL-012"),
    ("password", "POL-001"),
    ("reset", "POL-001"),
    ("locked", "POL-001"),
    ("credential", "POL-001"),
    ("vpn", "POL-002"),
    ("license", "POL-004"),
    ("install", "POL-010"),
]


def _offline_fallback_policy(query: str, application: str | None = None):
    text = f"{query} {application or ''}".lower()
    doc_id = next((d for keyword, d in FALLBACK_POLICY_KEYWORDS if keyword in text), None)
    return policy_by_id(doc_id) if doc_id else None


def _offline_fallback_graph(application: str):
    app = next((a for a in _SEED_DATA["applications"] if a["name"] == application), None)
    deps = app["depends_on_services"] if app else []
    services_map = {s["service_id"]: s["name"] for s in _SEED_DATA["services"]}
    open_outages = {o["service_id"] for o in _SEED_DATA.get("outages", []) if o.get("status") == "OPEN"}
    from src.knowledge.models import GraphResult
    return GraphResult(
        application=application,
        found=app is not None,
        dependencies=[services_map[s] for s in deps if s in services_map],
        active_outages=[services_map[s] for s in deps if s in open_outages and s in services_map],
    )


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
    try:
        return {"policy_result": knowledge_retrieve_policy(query, app)}
    except Exception:
        return {"policy_result": _offline_fallback_policy(query, app)}


def check_graph(state: AgentState) -> dict:
    application = state.extracted_fields.application
    if not application:
        return {"graph_result": None}
    try:
        return {"graph_result": knowledge_check_graph(application)}
    except Exception:
        return {"graph_result": _offline_fallback_graph(application)}


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
    # No policy matched the request: cite the policy that governs the chosen action instead.
    policy = state.policy_result or policy_by_id(POLICY_BY_ACTION.get(action_type.value, ""))
    return {"action_proposal": proposal, "policy_result": policy}


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
