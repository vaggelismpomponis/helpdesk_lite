"""Mock tools for the graph skeleton. Same signatures as the real Knowledge tools (contract section 4).

They read src/data instead of pgvector and Neo4j, and are replaced by the real tools in step 8.
"""

import json
import re
from pathlib import Path
from typing import Optional

from src.knowledge.models import GraphResult, PolicyResult

DATA_DIR = Path(__file__).resolve().parents[1] / "data"
SEED = json.loads((DATA_DIR / "graph_seed.json").read_text(encoding="utf-8"))
SERVICES = {s["service_id"]: s["name"] for s in SEED["services"]}
OPEN_OUTAGE_SERVICES = {o["service_id"] for o in SEED["outages"] if o["status"] == "OPEN"}

# First keyword found in the query picks the policy.
POLICY_KEYWORDS = [
    ("wi-fi", "POL-016"),
    ("travel", "POL-008"),
    ("cloud storage", "POL-012"),
    ("password", "POL-001"),
    ("reset", "POL-001"),
    ("locked", "POL-001"),
    ("credential", "POL-001"),
    ("vpn", "POL-002"),
    ("license", "POL-004"),  # a license request is a ticket (POL-004), even when it says "install"
    ("install", "POL-010"),
]

# Policy that governs an action, cited when the request itself matched no policy.
POLICY_BY_ACTION = {
    "link_outage": "POL-003",
    "open_ticket": "POL-004",
    "escalate": "POL-005",
}

OFFICES = sorted({e["office"] for e in SEED["employees"]})
DEVICES = sorted({e["device"] for e in SEED["employees"]})


def _front_matter(path: Path) -> dict[str, str]:
    match = re.match(r"---\n(.*?)\n---\n", path.read_text(encoding="utf-8"), re.S)
    fields = dict(line.split(":", 1) for line in match.group(1).splitlines() if ":" in line)
    return {k.strip(): v.strip().strip('"') for k, v in fields.items()}


def _latest_version(doc_id: str) -> Optional[Path]:
    """Latest effective_date wins when a doc_id has several versions."""
    versions = sorted(DATA_DIR.glob(f"policies/{doc_id}_*.md"), key=lambda p: _front_matter(p)["effective_date"])
    return versions[-1] if versions else None


def policy_by_id(doc_id: str) -> Optional[PolicyResult]:
    """Latest version of a policy, looked up by doc_id."""
    path = _latest_version(doc_id)
    if not path:
        return None
    meta = _front_matter(path)
    body = path.read_text(encoding="utf-8").split("---\n", 2)[-1].strip()
    return PolicyResult(text=body[:800], doc_id=meta["doc_id"], effective_date=meta["effective_date"], source=path.name)


def retrieve_policy(query: str, application: Optional[str] = None) -> Optional[PolicyResult]:
    text = f"{query} {application or ''}".lower()
    doc_id = next((d for keyword, d in POLICY_KEYWORDS if keyword in text), None)
    return policy_by_id(doc_id) if doc_id else None


def _find_known(options: list[str], text: str) -> Optional[str]:
    lowered = text.lower()
    return next((o for o in options if re.search(rf"\b{re.escape(o.lower())}\b", lowered)), None)


def find_office(text: str) -> Optional[str]:
    """Office named in the text. Taken from the message only: the user must confirm it (POL-001)."""
    return _find_known(OFFICES, text)


def find_device(text: str) -> Optional[str]:
    """Device named in the text. Taken from the message only: the user must confirm it (POL-001)."""
    return _find_known(DEVICES, text)


def has_no_team(employee: Optional[str]) -> bool:
    """True when a known employee has no team assigned (no owner to route the request to)."""
    record = next((e for e in SEED["employees"] if e["name"] == employee), None)
    return record is not None and not record.get("team_id")


def find_application(text: str) -> Optional[str]:
    """Canonical application name mentioned in the text (mock of entity linking)."""
    lowered = text.lower()
    for app in SEED["applications"]:
        aliases = {app["name"], app["name"].removeprefix("Corporate ")}
        if any(re.search(rf"\b{re.escape(a.lower())}\b", lowered) for a in aliases):
            return app["name"]
    return None


def check_graph(application: str) -> GraphResult:
    app = next((a for a in SEED["applications"] if a["name"] == application), None)
    deps = app["depends_on_services"] if app else []
    return GraphResult(
        application=application,
        dependencies=[SERVICES[s] for s in deps],
        active_outages=[SERVICES[s] for s in deps if s in OPEN_OUTAGE_SERVICES],
    )


def find_employee(email: Optional[str] = None, text: Optional[str] = None) -> Optional[str]:
    if email:
        match = next((e["name"] for e in SEED["employees"] if e["email"] == email), None)
        if match:
            return match
    if text:
        lowered = text.lower()
        for emp in SEED["employees"]:
            email_match = emp["email"].lower()
            name_match = emp["name"].lower()
            if email_match in lowered or re.search(rf"\b{re.escape(name_match)}\b", lowered):
                return emp["name"]
    return None
