"""Graph nodes. Each one is small and returns a partial update of AgentState.

Wired to real Knowledge tools (retrieve_policy via pgvector, check_graph via Neo4j).
"""

import json
import os
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

# Policy that governs an action, cited unless the request names a policy topic (see _citation_for).
POLICY_BY_ACTION = {
    "reset_credentials": "POL-001",
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
        aliases = {srv["name"]}
        if "sso" in srv["name"].lower():
            aliases.update({"sso", "identity provider"})
        if "smtp" in srv["name"].lower():
            aliases.update({"smtp", "smtp relay"})
        if any(re.search(rf"\b{re.escape(a.lower())}\b", lowered) for a in aliases):
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

# In-memory execution cache for fast local lookup and fallback alongside PostgreSQL audit_log.
EXECUTED_ACTION_IDS: set[str] = set()


def _is_action_already_executed(action_id: str) -> bool:
    """Check if action has already been executed in memory or in PostgreSQL audit_log."""
    if action_id in EXECUTED_ACTION_IDS:
        return True
    try:
        from src.db.idempotency import is_action_executed

        return is_action_executed(action_id)
    except Exception:
        return False


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


def topic_policy_id(text: str) -> str | None:
    """doc_id of the policy whose topic the text names explicitly, if any."""
    lowered = text.lower()
    return next((d for keyword, d in FALLBACK_POLICY_KEYWORDS if keyword in lowered), None)


def _offline_fallback_policy(query: str, application: str | None = None):
    doc_id = topic_policy_id(f"{query} {application or ''}")
    return policy_by_id(doc_id) if doc_id else None


def _offline_fallback_graph(application: str):
    from src.knowledge.models import GraphResult, Outage

    services_map = {s["service_id"]: s["name"] for s in _SEED_DATA["services"]}
    open_outages = {o["service_id"] for o in _SEED_DATA.get("outages", []) if o.get("status") == "OPEN"}

    app = next((a for a in _SEED_DATA["applications"] if a["name"].lower() == application.lower()), None)
    if app:
        deps = app.get("depends_on_services", [])
        active = [services_map[s] for s in deps if s in open_outages and s in services_map]
        outages = [
            Outage(
                outage_id=o["outage_id"],
                service=services_map.get(o["service_id"], o["service_id"]),
                title=o.get("title", ""),
                severity=o.get("severity", ""),
                started_at=o.get("started_at", ""),
                summary=o.get("summary", ""),
            )
            for o in _SEED_DATA.get("outages", [])
            if o.get("status") == "OPEN" and o.get("service_id") in deps
        ]
        return GraphResult(
            application=app["name"],
            found=True,
            dependencies=[services_map[s] for s in deps if s in services_map],
            active_outages=sorted(active),
            outages=outages,
        )

    # Direct backend service match
    srv = next(
        (s for s in _SEED_DATA["services"] if s["name"].lower() == application.lower() or application.lower() in s["name"].lower()),
        None,
    )
    if srv:
        is_open = srv["service_id"] in open_outages
        direct_outages = [srv["name"]] if is_open else []
        outages = [
            Outage(
                outage_id=o["outage_id"],
                service=srv["name"],
                title=o.get("title", ""),
                severity=o.get("severity", ""),
                started_at=o.get("started_at", ""),
                summary=o.get("summary", ""),
            )
            for o in _SEED_DATA.get("outages", [])
            if o.get("status") == "OPEN" and o.get("service_id") == srv["service_id"]
        ]
        return GraphResult(
            application=srv["name"],
            found=True,
            dependencies=[srv["name"]],
            active_outages=direct_outages,
            outages=outages,
        )

    return GraphResult(application=application, found=False)


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
        policy = knowledge_retrieve_policy(query, app)
        if policy is None:
            policy = _offline_fallback_policy(query, app)
        return {"policy_result": policy}
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

    # 1. Outage check: Strict rule: if a dependent service has an active outage,
    # the assistant MUST propose link_outage (NEVER credential reset).
    if state.graph_result and state.graph_result.has_active_outage:
        outages_str = ", ".join(state.graph_result.active_outages)
        app_name = state.extracted_fields.application or state.graph_result.application or "the affected application"
        if any(w in text for w in RESET_WORDS):
            rationale = (
                f"Active outage on dependent service ({outages_str}) affecting {app_name}. "
                "Credential reset is inhibited; proposing link to outage instead."
            )
        else:
            rationale = f"Active outage on {outages_str}"
        return ActionType.LINK_OUTAGE, rationale

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

    parameters = {
        "employee": state.extracted_fields.employee if state.extracted_fields else None,
        "application": state.extracted_fields.application if state.extracted_fields else None,
    }
    if state.extracted_fields:
        if state.extracted_fields.symptom:
            parameters["symptom"] = state.extracted_fields.symptom
        if state.extracted_fields.urgency:
            parameters["urgency"] = state.extracted_fields.urgency
        if state.extracted_fields.office:
            parameters["office"] = state.extracted_fields.office
        if state.extracted_fields.device:
            parameters["device"] = state.extracted_fields.device

    if action_type == ActionType.LINK_OUTAGE and state.graph_result:
        parameters["active_outages"] = state.graph_result.active_outages
        if state.graph_result.outages:
            parameters["outage_id"] = state.graph_result.outages[0].outage_id
        elif state.graph_result.active_outages:
            parameters["outage_service"] = state.graph_result.active_outages[0]

    proposal = ActionProposal(
        action_id=str(uuid.uuid4()),
        action_type=action_type,
        parameters=parameters,
        # Informational actions need no human approval, so they start approved.
        status=ActionStatus.PENDING if needs_approval else ActionStatus.APPROVED,
        requires_approval=needs_approval,
        rationale=rationale,
    )

    # Persist action proposal into PostgreSQL audit_log (idempotency & audit tracking)
    thread_id = state.thread_id or "unknown_thread"
    try:
        from src.db.idempotency import record_action

        record_action(
            action_id=proposal.action_id,
            thread_id=thread_id,
            action_type=proposal.action_type.value,
            employee=parameters.get("employee"),
            application=parameters.get("application"),
            status=proposal.status.value,
            parameters=proposal.parameters,
            rationale=proposal.rationale,
        )
    except Exception:
        pass

    # Attach tracing metadata to active LangSmith run tree if present
    try:
        from langsmith.run_helpers import get_current_run_tree

        rt = get_current_run_tree()
        if rt:
            rt.add_metadata({"thread_id": thread_id, "action_id": proposal.action_id})
    except Exception:
        pass

    return {"action_proposal": proposal, "policy_result": _citation_for(action_type, state)}


def _citation_for(action_type: ActionType, state: AgentState):
    """Policy cited for the chosen action (contract section 5, citation rule).

    Policy answers cite the semantic match. Actions with a governing policy cite the
    policy the request names explicitly, otherwise the governing one: the nearest semantic match is
    not evidence for them, since with real embeddings an unrelated policy can rank first.
    """
    governing = POLICY_BY_ACTION.get(action_type.value)
    if governing is None:
        return state.policy_result
    doc_id = topic_policy_id(_user_text(state)) or governing
    if state.policy_result and state.policy_result.doc_id == doc_id:
        return state.policy_result
    return policy_by_id(doc_id) or state.policy_result


# langgraph 0.2.45 rejects empty updates, so unchanged nodes return the proposal as is.


def human_approval(state: AgentState) -> dict:
    """Runs after the operator's decision was written into action_proposal.status.

    Anything other than an explicit approval counts as a rejection.
    Updates the action lifecycle status atomically in PostgreSQL audit_log.
    """
    proposal = state.action_proposal
    new_status = ActionStatus.APPROVED if proposal.status == ActionStatus.APPROVED else ActionStatus.REJECTED
    updated_proposal = proposal if proposal.status == new_status else proposal.model_copy(update={"status": new_status})

    thread_id = state.thread_id or "unknown_thread"
    try:
        from src.db.idempotency import record_action

        record_action(
            action_id=updated_proposal.action_id,
            thread_id=thread_id,
            action_type=updated_proposal.action_type.value,
            employee=updated_proposal.parameters.get("employee"),
            application=updated_proposal.parameters.get("application"),
            status=updated_proposal.status.value,
            parameters=updated_proposal.parameters,
            rationale=updated_proposal.rationale,
        )
    except Exception:
        pass

    return {"action_proposal": updated_proposal}


def execute_action(state: AgentState) -> dict:
    proposal = state.action_proposal
    # Idempotency pre-execution guard: never run an action twice across container restarts or replays.
    if proposal.status == ActionStatus.EXECUTED or _is_action_already_executed(proposal.action_id):
        EXECUTED_ACTION_IDS.add(proposal.action_id)
        return {"action_proposal": proposal.model_copy(update={"status": ActionStatus.EXECUTED})}

    if proposal.status != ActionStatus.APPROVED:
        return {"action_proposal": proposal}

    def _do_execute(action_id: str):
        if proposal.action_type == ActionType.OPEN_TICKET:
            from src.db.idempotency import create_ticket_idempotent

            emp = (
                (state.extracted_fields and state.extracted_fields.employee)
                or proposal.parameters.get("employee")
                or "Unknown"
            )
            app = (
                (state.extracted_fields and state.extracted_fields.application)
                or proposal.parameters.get("application")
                or "General IT"
            )
            sym = (
                (state.extracted_fields and state.extracted_fields.symptom)
                or proposal.parameters.get("symptom")
                or "Unspecified issue"
            )
            urg = (
                (state.extracted_fields and state.extracted_fields.urgency)
                or proposal.parameters.get("urgency")
                or "medium"
            )
            details = {
                "parameters": proposal.parameters,
                "rationale": proposal.rationale,
            }
            create_ticket_idempotent(
                action_id=action_id,
                employee=emp,
                application=app,
                symptom=sym,
                urgency=urg,
                details=details,
            )

    try:
        from src.db.idempotency import execute_idempotent, record_action

        thread_id = state.thread_id or "unknown_thread"
        # Ensure action proposal is registered in audit_log as approved prior to atomic execution
        record_action(
            action_id=proposal.action_id,
            thread_id=thread_id,
            action_type=proposal.action_type.value,
            employee=proposal.parameters.get("employee"),
            application=proposal.parameters.get("application"),
            status=ActionStatus.APPROVED.value,
            parameters=proposal.parameters,
            rationale=proposal.rationale,
        )
        execute_idempotent(proposal.action_id, _do_execute)
    except Exception:
        # Fallback if database is offline / unreachable
        _do_execute(proposal.action_id)

    EXECUTED_ACTION_IDS.add(proposal.action_id)
    try:
        from langsmith.run_helpers import get_current_run_tree

        rt = get_current_run_tree()
        if rt:
            rt.add_metadata({
                "thread_id": state.thread_id or "unknown_thread",
                "action_id": proposal.action_id,
                "action_status": ActionStatus.EXECUTED.value,
            })
    except Exception:
        pass
    return {"action_proposal": proposal.model_copy(update={"status": ActionStatus.EXECUTED})}


def _clean_env(val: str | None) -> str:
    if not val:
        return ""
    return val.strip().strip('"').strip("'")


def get_llm():
    """Return an AzureChatOpenAI or ChatOpenAI instance, or None if offline/keys missing."""
    offline_mode = (
        os.getenv("OFFLINE_MODE", "false").lower() in ("true", "1")
        or os.getenv("LLM_PROVIDER") == "offline"
    )
    if offline_mode:
        return None

    azure_key = _clean_env(os.getenv("AZURE_OPENAI_API_KEY"))
    azure_endpoint = _clean_env(os.getenv("AZURE_OPENAI_ENDPOINT"))
    if azure_key and not azure_key.startswith("your_") and azure_endpoint and not azure_endpoint.startswith("https://your-"):
        try:
            from langchain_openai import AzureChatOpenAI

            deployment = _clean_env(os.getenv("AZURE_OPENAI_DEPLOYMENT_NAME", "gpt-4.1-mini"))
            api_version = _clean_env(os.getenv("OPENAI_API_VERSION", "2024-10-21"))
            return AzureChatOpenAI(
                azure_deployment=deployment,
                openai_api_version=api_version,
                azure_endpoint=azure_endpoint,
                api_key=azure_key,
                temperature=0.0,
            )
        except Exception:
            pass

    openai_key = _clean_env(os.getenv("OPENAI_API_KEY"))
    if openai_key and not openai_key.startswith("your_"):
        try:
            from langchain_openai import ChatOpenAI

            model = _clean_env(os.getenv("LLM_MODEL", "gpt-4o-mini"))
            return ChatOpenAI(model=model, api_key=openai_key, temperature=0.0)
        except Exception:
            pass

    return None


def _interpret_results_with_llm(state: AgentState) -> tuple[str | None, str | None]:
    """Use an LLM for thinking and interpretation of retrieved results.

    Returns:
        (thinking, explanation) or (None, None) if LLM is unavailable.
    """
    llm = get_llm()
    if llm is None:
        return None, None

    try:
        from langchain_core.messages import HumanMessage, SystemMessage

        user_text = _user_text(state)
        fields = state.extracted_fields
        policy = state.policy_result
        graph_res = state.graph_result
        proposal = state.action_proposal

        fields_str = (
            f"Employee: {fields.employee or 'Unknown'}, "
            f"Application: {fields.application or 'Unknown'}, "
            f"Symptom: {fields.symptom or 'Unspecified'}, "
            f"Office: {fields.office or 'Unknown'}, "
            f"Device: {fields.device or 'Unknown'}"
            if fields
            else "None"
        )

        graph_str = "No graph data."
        if graph_res:
            deps = ", ".join(graph_res.dependencies) if graph_res.dependencies else "None"
            outages = ", ".join(graph_res.active_outages) if graph_res.active_outages else "None"
            graph_str = f"Application: {graph_res.application}, Dependencies: {deps}, Active Outages: {outages}"

        policy_str = "No policy cited."
        if policy:
            policy_str = (
                f"Doc ID: {policy.doc_id}, Effective Date: {policy.effective_date}, Source: {policy.source}\n"
                f"Content Excerpt: {policy.text[:500]}"
            )

        action_str = "No action proposed."
        if proposal:
            action_str = (
                f"Action Type: {proposal.action_type.value}, "
                f"Status: {proposal.status.value}, "
                f"Rationale: {proposal.rationale}"
            )

        context = (
            f"User Request: {user_text}\n\n"
            f"Extracted Triage Fields: {fields_str}\n\n"
            f"Knowledge Graph (Dependencies & Outages): {graph_str}\n\n"
            f"Retrieved Policy: {policy_str}\n\n"
            f"Selected Action & Lifecycle: {action_str}"
        )

        system_prompt = (
            "You are HelpDesk Lite, an agentic IT support assistant for Nimbus Analytics. "
            "Your role is to interpret the retrieved knowledge (service graph outages, policy documents) "
            "and provide clear reasoning ('thinking') and an explanation for the user.\n\n"
            "Format your output strictly with these two section headers:\n"
            "THINKING:\n"
            "<2-3 sentences of technical reasoning connecting user symptoms, outages, and policy rules>\n\n"
            "EXPLANATION:\n"
            "<Clear, professional explanation for the user explaining what was found, why this action was chosen, and answering their question>"
        )

        response = llm.invoke([
            SystemMessage(content=system_prompt),
            HumanMessage(content=context),
        ])
        content = response.content if hasattr(response, "content") else str(response)
        text = str(content).strip()

        thinking = None
        explanation = None

        if "THINKING:" in text and "EXPLANATION:" in text:
            parts = text.split("EXPLANATION:", 1)
            thinking = parts[0].replace("THINKING:", "").strip()
            explanation = parts[1].strip()
        else:
            explanation = text

        return thinking, explanation
    except Exception:
        return None, None


def respond(state: AgentState) -> dict:
    proposal = state.action_proposal
    parts = [f"Action: {proposal.action_type.value} [{proposal.status.value}]. {proposal.rationale}."]
    if proposal.action_type == ActionType.LINK_OUTAGE:
        parts.append("Your request was linked to the open outage; no credential reset is needed.")
    if proposal.status == ActionStatus.REJECTED:
        parts.append("The action was not approved, so nothing was changed.")

    thinking, explanation = _interpret_results_with_llm(state)
    if explanation:
        parts.append(f"\n\n{explanation}")

    if state.policy_result:
        citation_str = f"Source: {state.policy_result.doc_id} (effective {state.policy_result.effective_date})."
        if citation_str not in " ".join(parts):
            parts.append(f"\n{citation_str}")

    text = " ".join(parts)
    update = {
        "final_response": text,
        "messages": [*state.messages, {"role": "assistant", "content": text}],
    }
    if thinking:
        update["thinking"] = thinking
    return update
