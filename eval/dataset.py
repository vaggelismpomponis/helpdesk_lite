"""Load the evaluation dataset owned by Knowledge (src/data/eval_dataset.json).

Each entry is converted to the LangSmith example shape ``{"inputs", "outputs", "metadata"}``,
where ``outputs`` holds the expected values the evaluators read. Fields the dataset does not
provide get a default that disables that check (``None`` or an empty list), except for two rules
derived from the data and the project rules:

- ``forbidden_citations``: older versions of every expected policy, read from the policy files.
- ``forbidden_actions``: when the expected action is ``link_to_outage``, a credential reset is
  forbidden (an outage must be linked, not "fixed" with a reset).
"""

import json
import re
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = REPO_ROOT / "src" / "data"
DATASET_PATH = DATA_DIR / "eval_dataset.json"
POLICIES_DIR = DATA_DIR / "policies"

_FRONT_MATTER_FIELD = re.compile(r"^(doc_id|effective_date):\s*\"?([^\"\n]+)\"?\s*$", re.M)


def policy_versions(policies_dir: Path = POLICIES_DIR) -> dict[str, list[str]]:
    """Map each doc_id to all of its effective dates, from the policy front matter."""
    versions: dict[str, list[str]] = {}
    for path in sorted(policies_dir.glob("*.md")):
        fields = dict(_FRONT_MATTER_FIELD.findall(path.read_text()))
        if "doc_id" in fields and "effective_date" in fields:
            versions.setdefault(fields["doc_id"], []).append(fields["effective_date"])
    return versions


def to_example(entry: dict[str, Any], versions: dict[str, list[str]]) -> dict[str, Any]:
    """Convert one dataset entry to ``{"inputs", "outputs", "metadata"}``."""
    expected_action = entry["expected_action"]
    requires_approval = entry["requires_approval"]
    approval_decision = entry.get("approval_decision", "approve" if requires_approval else None)

    citation = entry.get("expected_citation")
    expected_citations = [citation] if citation else []
    forbidden_citations = [
        {"doc_id": c["doc_id"], "effective_date": date}
        for c in expected_citations
        for date in versions.get(c["doc_id"], [])
        if date < c["effective_date"]
    ]

    forbidden_actions = list(entry.get("forbidden_actions", []))
    if expected_action == "link_to_outage" and "reset_credentials" not in forbidden_actions:
        forbidden_actions.append("reset_credentials")

    return {
        "inputs": {
            "request": entry["request_text"],
            "sender_email": entry.get("sender_email"),
            "clarification_reply": entry.get("clarification_answer"),
            "approval_decision": approval_decision,
        },
        "outputs": {
            "asks_clarification": entry["requires_clarification"],
            "expected_action": expected_action,
            "forbidden_actions": forbidden_actions,
            "expected_citations": expected_citations,
            "forbidden_citations": forbidden_citations,
            "outage_id": entry.get("outage_id"),
            "escalation_team": entry.get("escalation_team"),
            "requires_approval": requires_approval,
            "should_execute": requires_approval and approval_decision == "approve",
        },
        "metadata": {"id": entry["id"], "notes": entry.get("notes", "")},
    }


def load_examples(
    path: Path = DATASET_PATH, policies_dir: Path = POLICIES_DIR
) -> list[dict[str, Any]]:
    """Load and convert every entry of the evaluation dataset."""
    entries = json.loads(path.read_text())
    ids = [entry["id"] for entry in entries]
    if len(set(ids)) != len(ids):
        raise ValueError(f"duplicate example ids: {ids}")
    versions = policy_versions(policies_dir)
    return [to_example(entry, versions) for entry in entries]
