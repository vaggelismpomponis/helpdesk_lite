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
    ("install", "POL-010"),
    ("license", "POL-004"),
]


def _front_matter(path: Path) -> dict[str, str]:
    match = re.match(r"---\n(.*?)\n---\n", path.read_text(encoding="utf-8"), re.S)
    fields = dict(line.split(":", 1) for line in match.group(1).splitlines() if ":" in line)
    return {k.strip(): v.strip().strip('"') for k, v in fields.items()}


def _latest_version(doc_id: str) -> Optional[Path]:
    """Latest effective_date wins when a doc_id has several versions."""
    versions = sorted(DATA_DIR.glob(f"policies/{doc_id}_*.md"), key=lambda p: _front_matter(p)["effective_date"])
    return versions[-1] if versions else None


def retrieve_policy(query: str, application: Optional[str] = None) -> Optional[PolicyResult]:
    text = f"{query} {application or ''}".lower()
    doc_id = next((d for keyword, d in POLICY_KEYWORDS if keyword in text), None)
    path = _latest_version(doc_id) if doc_id else None
    if not path:
        return None
    meta = _front_matter(path)
    body = path.read_text(encoding="utf-8").split("---\n", 2)[-1].strip()
    return PolicyResult(text=body[:800], doc_id=meta["doc_id"], effective_date=meta["effective_date"], source=path.name)


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
