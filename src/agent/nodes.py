"""Graph nodes. Each one is small and returns a partial update of AgentState.

Wired to real Knowledge tools (retrieve_policy via pgvector, check_graph via Neo4j).
"""

import json
import logging
import os
from pathlib import Path
import re
import uuid

from langchain_core.prompts import ChatPromptTemplate
from langchain_core.runnables import RunnableConfig

from src.agent.models import (
    STATE_CHANGING_ACTIONS,
    ActionProposal,
    ActionStatus,
    ActionType,
    AgentState,
    ExtractedFields,
    ResponseInterpretation,
)
from src.knowledge.tools import (
    check_graph_tool as knowledge_check_graph,
    retrieve_policy_tool as knowledge_retrieve_policy,
)

logger = logging.getLogger(__name__)

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
    """Device named in the text (including partial names like 'MacBook', 'Windows', 'Linux')."""
    exact = _find_known(DEVICES, text)
    if exact:
        return exact
    lowered = text.lower()
    device_aliases = [
        (r"\b(?:macbook|mac\s+book)\b", "MacBook Pro"),
        (r"\bwindows\b", "Windows Laptop"),
        (r"\b(?:linux|workstation)\b", "Linux Workstation"),
    ]
    for pattern, canonical in device_aliases:
        if canonical in DEVICES and re.search(pattern, lowered):
            return canonical
    return None


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
        email_low = email.strip().lower()
        match = next((e["name"] for e in _SEED_DATA["employees"] if e["email"].lower() == email_low), None)
        if match:
            return match
    if text:
        lowered = text.lower()
        for emp in _SEED_DATA["employees"]:
            email_match = emp["email"].lower()
            name_match = emp["name"].lower()
            emp_id_match = emp.get("employee_id", "").lower()
            local_part = email_match.split("@", 1)[0]
            if (
                email_match in lowered
                or re.search(rf"\b{re.escape(name_match)}\b", lowered)
                or (emp_id_match and re.search(rf"\b{re.escape(emp_id_match)}\b", lowered))
                or (local_part and re.search(rf"\b{re.escape(local_part)}\b", lowered))
            ):
                return emp["name"]

        # Normalize "employee 8" -> "Employee 08"
        num_match = re.search(r"\b(?:employee|emp)[-\s]*(\d{1,2})\b", lowered)
        if num_match:
            target_id = f"EMP-{int(num_match.group(1)):03d}"
            for emp in _SEED_DATA["employees"]:
                if emp.get("employee_id") == target_id:
                    return emp["name"]

        # Match unique first or last name for named employees (excluding generic "Employee NN")
        token_map: dict[str, list[str]] = {}
        for emp in _SEED_DATA["employees"]:
            for part in emp["name"].split():
                p_low = part.lower()
                if p_low != "employee" and not p_low.isdigit() and len(p_low) >= 3:
                    token_map.setdefault(p_low, []).append(emp["name"])
        for token, names in token_map.items():
            if len(names) == 1 and re.search(rf"\b{re.escape(token)}\b", lowered):
                return names[0]
    return None


_NON_NAME_WORDS = {
    "working", "using", "unable", "locked", "stuck", "trying", "having", "getting",
    "connecting", "calling", "writing", "reporting", "experiencing", "running",
    "in", "on", "at", "from", "with", "for", "to", "the", "a", "an", "here", "not",
    "athens", "london", "macbook", "mac", "windows", "linux", "laptop", "workstation",
    "pro", "office", "remote", "abroad", "urgent", "critical",
}


def _find_unrecognized_identity(text: str) -> str | None:
    """Detect when a user provides an email or self-identification name not in the directory."""
    if not text:
        return None
    for email_match in re.findall(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b", text):
        if not find_employee(email=email_match, text=email_match):
            return email_match

    emp_num = re.search(r"\b(?:EMP-\d+|employee\s*\d+)\b", text, re.I)
    if emp_num and not find_employee(text=emp_num.group(0)):
        return emp_num.group(0)

    intro_patterns = (
        r"\b(?:[Mm]y\s+name\s+is|[Tt]his\s+is)\s+([A-Z][a-z]{1,}(?:\s+[A-Z][a-z]{1,})?)\b",
        r"\b(?:[Ii]\s+am|[Ii]'m|[Ii]’m)\s+([A-Z][a-z]{1,}(?:\s+[A-Z][a-z]{1,})?)\b",
    )
    app_words = {
        w.lower()
        for a in _SEED_DATA.get("applications", []) + _SEED_DATA.get("services", [])
        for w in re.findall(r"[A-Za-z]+", a["name"])
    }
    excluded = _NON_NAME_WORDS | app_words
    for pat in intro_patterns:
        for m in re.finditer(pat, text):
            candidate = m.group(1).strip()
            words = candidate.split()
            if any(w.lower() in excluded for w in words):
                continue
            if not find_employee(text=candidate):
                return candidate
    return None


QUESTION_WORDS = (
    "what", "what's", "whats", "how", "how's", "do", "does", "is", "are",
    "can", "which", "when", "where", "who", "why",
)
INFO_PREFIXES = (
    "tell me about", "tell me the", "explain", "describe", "show me the policy",
)
REQUEST_PREFIXES = ("can you", "could you", "would you", "will you", "can i get", "could i get", "please")
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

FOLLOWUP_PATTERNS = (
    r"\bwhy\s+(?:didn't|did\s+not|didn’t|did|wasn't|was\s+not|wasn’t|don't|do\s+not|not)\b",
    r"\bwhich\s+(?:other\s+)?(?:teams?|applications?|apps?|services?|departments?|colleagues?)\b",
    r"\bwhat\s+(?:other\s+)?(?:teams?|applications?|apps?|services?|departments?)\b",
    r"\bwho\s+else\s+is\s+(?:affected|impacted)\b",
    r"\baffected\s+by\s+(?:this|the)\s+outage\b",
    r"\b(?:this|that|the)\s+outage\b",
    r"\bwhich\s+policy\b",
    r"\bwhat\s+policy\b",
    r"\bbase(?:d)?\s+(?:this|that|it)\s+on\b",
    r"\bwhy\s+no\s+reset\b",
    r"\bwhat\s+was\s+the\s+(?:reason|rationale|citation|policy|outage)\b",
)

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


def _last_completed_assistant_index(state: AgentState) -> int:
    """Index of the last assistant message that completed a turn, or -1 if none."""
    last_idx = -1
    for idx, msg in enumerate(state.messages):
        if msg.get("role") != "assistant":
            continue
        if msg.get("turn_complete") or (
            state.final_response and msg.get("content") == state.final_response
        ):
            last_idx = idx
    return last_idx


def _has_completed_turn(state: AgentState) -> bool:
    """True when the thread has already completed at least one turn."""
    return _last_completed_assistant_index(state) >= 0 and state.action_proposal is not None


def _current_turn_user_messages(state: AgentState) -> list[str]:
    """User messages belonging to the current turn (after the last completed turn)."""
    start_idx = _last_completed_assistant_index(state) + 1
    return [
        m["content"]
        for m in state.messages[start_idx:]
        if m.get("role") == "user" and m.get("content")
    ]


def _user_text(state: AgentState) -> str:
    current = _current_turn_user_messages(state)
    if current:
        return "\n".join(current)
    return "\n".join(m["content"] for m in state.messages if m.get("role") == "user")


def is_question(text: str) -> bool:
    """Informational policy or how-to question (even without a trailing '?'), not a polite action request."""
    lowered = text.strip().lower()
    if not lowered:
        return False
    if lowered.startswith(REQUEST_PREFIXES):
        return False
    if any(
        p in lowered
        for p in (
            "i can't", "i cannot", "i can’t", "i locked myself", "my password is locked",
            "stopped working", "stuck in the outbox", "error 500", "please reset my",
            "can you reset", "could you reset",
        )
    ):
        return False
    if lowered.startswith(INFO_PREFIXES):
        return True
    words = re.findall(r"[a-z0-9']+", lowered)
    return bool(words) and words[0] in QUESTION_WORDS


def _is_followup_question(text: str, state: AgentState) -> bool:
    """True if text asks a conversational follow-up question about the already-processed action/outage/policy."""
    lowered = text.strip().lower()
    if not lowered or state.action_proposal is None:
        return False
    if any(
        p in lowered
        for p in (
            "i can't", "i cannot", "i can’t", "i locked myself", "my password is locked",
            "stopped working", "stuck in the outbox", "error 500", "please reset my",
            "can you reset", "could you reset", "i need a ",
        )
    ):
        return False
    return any(re.search(pat, lowered) for pat in FOLLOWUP_PATTERNS)


def is_followup_turn(state: AgentState) -> bool:
    """True when the user is asking a post-action follow-up question in an existing completed thread."""
    if not _has_completed_turn(state):
        return False
    current_msgs = _current_turn_user_messages(state)
    if len(current_msgs) != 1:
        return False
    return _is_followup_question(current_msgs[0], state)


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


KNOWN_APPLICATIONS = sorted(
    {a["name"] for a in _SEED_DATA["applications"]} | {s["name"] for s in _SEED_DATA["services"]}
)
URGENCY_LEVELS = ("low", "medium", "high")

EXTRACTION_PROMPT = ChatPromptTemplate.from_messages([
    (
        "system",
        "You extract triage fields from IT support requests for HelpDesk Lite.\n"
        "Fill a field only when the user states it in the conversation. Never guess or infer a value "
        "that is not written: leave the field null instead, and the assistant will ask the user.\n"
        "- employee: the name or work email the user gives for themselves.\n"
        "- application: the affected application or service, using one of these names: {applications}.\n"
        "- symptom: a short description of the problem the user observes, close to their own words.\n"
        "- urgency: low, medium or high, only if the user expresses urgency or a deadline.\n"
        "- office: one of {offices}, only if the user names it.\n"
        "- device: one of {devices}, only if the user names it.",
    ),
    ("human", "{conversation}"),
])


def _canonical(value: str | None, options: list[str]) -> str | None:
    """Known option that the value names exactly, or uniquely contains or is contained in."""
    if not value or not value.strip():
        return None
    v = value.strip().lower()
    exact = [o for o in options if o.lower() == v]
    if exact:
        return exact[0]
    partial = [o for o in options if o.lower() in v or v in o.lower()]
    return partial[0] if len(partial) == 1 else None


def _grounded(value: str | None, text: str) -> bool:
    """True if at least one meaningful word of the value appears in the user's text."""
    if not value:
        return False
    lowered = text.lower()
    words = [w for w in re.findall(r"[a-z0-9']+", value.lower()) if len(w) > 3]
    return any(re.search(rf"\b{re.escape(w)}\b", lowered) for w in words)


def _llm_extract(text: str) -> ExtractedFields | None:
    """Structured extraction with the LLM; None if the LLM is unavailable or fails."""
    llm = get_llm()
    if llm is None:
        return None
    try:
        chain = EXTRACTION_PROMPT | llm.with_structured_output(ExtractedFields)
        result = chain.invoke({
            "applications": ", ".join(KNOWN_APPLICATIONS),
            "offices": ", ".join(OFFICES),
            "devices": ", ".join(DEVICES),
            "conversation": text,
        })
        return result if isinstance(result, ExtractedFields) else ExtractedFields.model_validate(result)
    except Exception:
        logger.warning("LLM field extraction failed; using rule-based extraction only.", exc_info=True)
        return None


def _merge_llm_fields(fields: ExtractedFields, llm_fields: ExtractedFields | None, text: str) -> ExtractedFields:
    """Fill fields the rules missed with LLM values, keeping only values grounded in known data or the text."""
    if llm_fields is None:
        return fields
    candidates = {
        "employee": find_employee(text=llm_fields.employee) if llm_fields.employee else None,
        "application": (
            find_application(llm_fields.application) or _canonical(llm_fields.application, KNOWN_APPLICATIONS)
            if llm_fields.application
            else None
        ),
        "symptom": llm_fields.symptom.strip() if _grounded(llm_fields.symptom, text) else None,
        "urgency": (llm_fields.urgency or "").strip().lower() or None,
        "office": _canonical(llm_fields.office, OFFICES),
        "device": _canonical(llm_fields.device, DEVICES),
    }
    if candidates["urgency"] not in URGENCY_LEVELS:
        candidates["urgency"] = None
    updates = {k: v for k, v in candidates.items() if v and not getattr(fields, k)}
    if updates:
        logger.info("LLM filled triage fields: %s", ", ".join(sorted(updates)))
    return fields.model_copy(update=updates)


def extract_fields(state: AgentState, config: RunnableConfig) -> dict:
    """Extract fields with rules plus LLM structured output, and enforce the 'ask if missing' rule.

    Rule-based matches against the seed data come first. The LLM only fills fields the rules missed,
    and its values are kept only if they match a known employee, application, office or device, or
    (for the symptom) appear in the user's own words. Without an LLM the rules work alone.
    """
    # Post-action follow-up question: preserve existing state and route directly to respond.
    if is_followup_turn(state):
        return {
            "needs_clarification": False,
            "clarification_question": None,
        }

    is_new_turn_after_completion = _has_completed_turn(state)
    prev_fields = state.extracted_fields if is_new_turn_after_completion else None

    text = _user_text(state)
    lowered = text.lower()

    # 1. Resolve employee: session config takes precedence, fallback to message text
    user_email = config.get("configurable", {}).get("user_email")
    explicit_employee = find_employee(text=text)
    unrecognized_identity = _find_unrecognized_identity(text) if not explicit_employee else None
    employee = find_employee(email=user_email, text=text)

    # 2. Resolve application: match against known applications and aliases (current turn only)
    application = find_application(text)

    # 3. Resolve office and device: from the message only, the user must confirm them (POL-001)
    office, device = find_office(text), find_device(text)

    # Retain known user context (employee, office, device) across turns in the same session,
    # unless the user switched to a different employee or gave an unrecognized identity.
    if prev_fields is not None and not unrecognized_identity:
        same_employee = not explicit_employee or explicit_employee == prev_fields.employee
        if not employee and prev_fields.employee:
            employee = prev_fields.employee
        if same_employee:
            if not office and prev_fields.office:
                office = prev_fields.office
            if not device and prev_fields.device:
                device = prev_fields.device

    # 4. Resolve symptom: extract observed issue without guessing (never carried over from old issues)
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

    # 6. Fill the gaps with LLM structured output, keeping only grounded values
    fields = _merge_llm_fields(fields, _llm_extract(text), text)

    # 7. Enforce strict "Ask if Missing" rule:
    # Policy questions do not need triage fields; incident requests require all mandatory fields.
    if is_question(text):
        missing = []
    else:
        missing = fields.missing_fields()

    if missing:
        prompt_body = f"To help you, please tell me {' and '.join(FIELD_PROMPTS[f] for f in missing)}."
        if "employee" in missing and unrecognized_identity:
            question = (
                f"I could not find '{unrecognized_identity}' in the Nimbus Analytics employee directory. "
                f"{prompt_body}"
            )
        else:
            question = prompt_body
    else:
        question = None

    update: dict = {
        "extracted_fields": fields,
        "needs_clarification": bool(missing),
        "clarification_question": question,
    }
    if is_new_turn_after_completion:
        # Clear previous incident's action/policy/graph state so old ticket details do not bleed in.
        update.update({
            "policy_result": None,
            "graph_result": None,
            "action_proposal": None,
            "final_response": None,
            "thinking": None,
        })
    return update


def ask_clarification(state: AgentState) -> dict:
    """Posts the question. The graph pauses after this node until the user replies."""
    return {"messages": [*state.messages, {"role": "assistant", "content": state.clarification_question}]}


FALLBACK_POLICY_KEYWORDS = [
    ("wi-fi", "POL-016"),
    ("wifi", "POL-016"),
    ("travel", "POL-008"),
    ("abroad", "POL-008"),
    ("cloud storage", "POL-012"),
    ("shared drive", "POL-012"),
    ("password", "POL-001"),
    ("reset", "POL-001"),
    ("locked", "POL-001"),
    ("credential", "POL-001"),
    ("vpn", "POL-002"),
    ("license", "POL-004"),
    ("install", "POL-010"),
    ("software catalog", "POL-010"),
    ("mfa", "POL-006"),
    ("security key", "POL-006"),
    ("laptop provisioning", "POL-009"),
    ("laptop replacement", "POL-009"),
    ("phishing", "POL-011"),
    ("onboarding", "POL-013"),
    ("offboarding", "POL-014"),
    ("contractor", "POL-015"),
    ("production database", "POL-017"),
    ("mdm", "POL-018"),
    ("disaster recovery", "POL-019"),
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
        policy = knowledge_retrieve_policy.invoke({"query": query, "application": app})
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
        return {"graph_result": knowledge_check_graph.invoke({"application": application})}
    except Exception:
        return {"graph_result": _offline_fallback_graph(application)}


def _choose_action(state: AgentState) -> tuple[ActionType, str]:
    """Decision Precedence Matrix (contract section 5); clarification is handled by routing."""
    raw_text = _user_text(state)
    text = raw_text.lower()

    if state.policy_result and is_question(raw_text):
        return ActionType.ANSWER_POLICY, f"Policy {state.policy_result.doc_id} answers the question"

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
        try:
            _do_execute(proposal.action_id)
        except Exception:
            pass

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
            logger.warning("Could not create the Azure OpenAI chat model; trying OpenAI.", exc_info=True)

    openai_key = _clean_env(os.getenv("OPENAI_API_KEY"))
    if openai_key and not openai_key.startswith("your_"):
        try:
            from langchain_openai import ChatOpenAI

            model = _clean_env(os.getenv("LLM_MODEL", "gpt-4o-mini"))
            return ChatOpenAI(model=model, api_key=openai_key, temperature=0.0)
        except Exception:
            logger.warning("Could not create the OpenAI chat model; running without an LLM.", exc_info=True)

    return None


INTERPRETATION_PROMPT = ChatPromptTemplate.from_messages([
    (
        "system",
        "You are HelpDesk Lite, an IT support assistant for Nimbus Analytics. The action below has already "
        "been chosen by the decision rules. Explain it; do not change it.\n"
        "- thinking: 2-3 sentences of technical reasoning linking the user's symptom, outages and policy rules.\n"
        "- explanation: a clear, professional explanation for the user of what was found and why this action "
        "was chosen, answering their question.\n"
        "Use only the facts given. Do not propose a different action, and do not cite any policy other than "
        "the retrieved one.",
    ),
    ("human", "{context}"),
])

POLICY_ID_PATTERN = re.compile(r"\bPOL-\d{3}\b")


def _interpret_results_with_llm(state: AgentState) -> tuple[str | None, str | None]:
    """Use an LLM for thinking and interpretation of retrieved results.

    Returns:
        (thinking, explanation), or (None, None) if the LLM is unavailable, fails, or cites a policy
        other than the retrieved one.
    """
    llm = get_llm()
    if llm is None:
        return None, None

    policy = state.policy_result
    try:
        user_text = _user_text(state)
        fields = state.extracted_fields
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

        chain = INTERPRETATION_PROMPT | llm.with_structured_output(ResponseInterpretation)
        result = chain.invoke({"context": context})
        if not isinstance(result, ResponseInterpretation):
            result = ResponseInterpretation.model_validate(result)
    except Exception:
        logger.warning("LLM interpretation failed; replying with the rule-based response only.", exc_info=True)
        return None, None

    # The decision and its citation come from the rules. Drop LLM text that cites a different policy.
    allowed = {policy.doc_id} if policy else set()
    cited = set(POLICY_ID_PATTERN.findall(f"{result.thinking} {result.explanation}"))
    if cited - allowed:
        logger.warning(
            "LLM interpretation cited %s but the response cites %s; discarding it.",
            ", ".join(sorted(cited - allowed)),
            ", ".join(sorted(allowed)) or "no policy",
        )
        return None, None

    return result.thinking.strip() or None, result.explanation.strip() or None


def _outage_impact_details(state: AgentState) -> tuple[list[str], list[str], str | None]:
    """Return (affected_applications, affected_teams, owner_team_name) for the active outage(s)."""
    active_service_names = set(state.graph_result.active_outages if state.graph_result else [])
    if not active_service_names:
        return [], [], None

    teams_by_id = {t["team_id"]: t["name"] for t in _SEED_DATA.get("teams", [])}
    active_service_ids = {
        s["service_id"]
        for s in _SEED_DATA.get("services", [])
        if s["name"] in active_service_names
    }
    owner_teams = sorted({
        teams_by_id[s["owner_team"]]
        for s in _SEED_DATA.get("services", [])
        if s["service_id"] in active_service_ids and s.get("owner_team") in teams_by_id
    })
    affected_apps = sorted({
        a["name"]
        for a in _SEED_DATA.get("applications", [])
        if set(a.get("depends_on_services", [])) & active_service_ids
    })
    affected_teams = sorted(teams_by_id.values())
    owner_str = ", ".join(owner_teams) if owner_teams else None
    return affected_apps, affected_teams, owner_str


def _build_followup_response(state: AgentState) -> dict:
    """Build a conversational follow-up response from existing state, policy, and service graph."""
    question = _user_text(state).strip()
    lowered = question.lower()
    proposal = state.action_proposal
    policy = state.policy_result
    graph_res = state.graph_result
    fields = state.extracted_fields

    affected_apps, affected_teams, owner_team = _outage_impact_details(state)
    outage_services = ", ".join(graph_res.active_outages) if graph_res and graph_res.active_outages else "None"
    outage_id = (
        proposal.parameters.get("outage_id")
        if proposal and proposal.parameters.get("outage_id")
        else (graph_res.outages[0].outage_id if graph_res and graph_res.outages else None)
    )
    outage_summary = (
        graph_res.outages[0].summary
        if graph_res and graph_res.outages and graph_res.outages[0].summary
        else None
    )

    parts: list[str] = []
    if any(w in lowered for w in ("team", "who else", "department", "colleague", "application", "app", "affected")):
        if graph_res and graph_res.has_active_outage:
            outage_label = f"{outage_services} ({outage_id})" if outage_id else outage_services
            apps_str = ", ".join(affected_apps) if affected_apps else (fields.application if fields else "dependent applications")
            teams_str = ", ".join(affected_teams) if affected_teams else "all company teams"
            owner_clause = f" (owned by the {owner_team} team)" if owner_team else ""
            parts.append(
                f"The active outage on {outage_label}{owner_clause} affects the following dependent applications: "
                f"{apps_str}. Because employees across Nimbus Analytics rely on these shared services, "
                f"all teams ({teams_str}) are impacted."
            )
            if outage_summary:
                parts.append(f"Outage summary: {outage_summary}")
        else:
            app_name = (fields.application if fields and fields.application else "the application")
            parts.append(f"There is no active shared service outage currently recorded for {app_name}.")
    elif "policy" in lowered or "base" in lowered or "cite" in lowered or "citation" in lowered:
        if policy:
            version_note = (
                " This is the latest effective version and supersedes the older 2024-03-15 policy."
                if policy.doc_id == "POL-001" and policy.effective_date == "2026-09-01"
                else ""
            )
            parts.append(
                f"This decision is based on policy {policy.doc_id} ({policy.source}, effective {policy.effective_date})."
                f"{version_note}"
            )
        else:
            parts.append("No specific policy document was required for this step.")
    elif "why" in lowered or "reset" in lowered or "password" in lowered:
        if proposal and proposal.action_type == ActionType.LINK_OUTAGE:
            app_name = (fields.application if fields and fields.application else "the application")
            outage_label = f"{outage_services} ({outage_id})" if outage_id else outage_services
            parts.append(
                f"Your password was not reset because {app_name} depends on {outage_label}, which currently has "
                "an active outage. Resetting an individual password will not fix an upstream infrastructure outage, "
                "so the request was linked to the open outage instead."
            )
        elif proposal:
            rationale_clean = (proposal.rationale or "").strip().rstrip(".")
            parts.append(
                f"The selected action was {proposal.action_type.value} [{proposal.status.value}]: {rationale_clean}."
            )
    else:
        if proposal:
            rationale_clean = (proposal.rationale or "").strip().rstrip(".")
            parts.append(
                f"For your request, the action is {proposal.action_type.value} [{proposal.status.value}]: {rationale_clean}."
            )

    thinking, explanation = _interpret_results_with_llm(state)
    if explanation:
        parts.append(f"\n\n{explanation.strip()}")

    if policy:
        citation_str = f"Source: {policy.doc_id} (effective {policy.effective_date})."
        if citation_str not in " ".join(parts):
            parts.append(f"\n{citation_str}")

    text = re.sub(r"\.\.+", ".", " ".join(parts)).strip()
    update: dict = {
        "final_response": text,
        "messages": [*state.messages, {"role": "assistant", "content": text, "turn_complete": True}],
    }
    if thinking:
        update["thinking"] = thinking
    return update


def respond(state: AgentState) -> dict:
    if is_followup_turn(state):
        return _build_followup_response(state)

    proposal = state.action_proposal
    rationale_clean = (proposal.rationale or "").strip().rstrip(".")
    header = f"Action: {proposal.action_type.value} [{proposal.status.value}]."
    if rationale_clean:
        header = f"{header} {rationale_clean}."
    parts = [header]
    if proposal.action_type == ActionType.LINK_OUTAGE and proposal.status != ActionStatus.REJECTED:
        parts.append("Your request was linked to the open outage; no credential reset is needed.")
    if proposal.status == ActionStatus.REJECTED:
        parts.append("The action was not approved, so nothing was changed.")

    thinking, explanation = _interpret_results_with_llm(state)
    if explanation:
        cleaned_explanation = re.sub(
            r"\s*Source:\s*POL-\d{3}\s*\(effective\s*[^)]+\)\.?",
            "",
            explanation.strip(),
        ).strip()
        if cleaned_explanation:
            parts.append(f"\n\n{cleaned_explanation}")

    if state.policy_result:
        citation_str = f"Source: {state.policy_result.doc_id} (effective {state.policy_result.effective_date})."
        if citation_str not in " ".join(parts):
            parts.append(f"\n{citation_str}")

    text = re.sub(r"\.\.+", ".", " ".join(parts))
    update = {
        "final_response": text,
        "messages": [*state.messages, {"role": "assistant", "content": text, "turn_complete": True}],
    }
    if thinking:
        update["thinking"] = thinking
    return update
