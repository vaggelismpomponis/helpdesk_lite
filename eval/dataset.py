"""Load the evaluation dataset owned by Knowledge (src/data/eval_dataset.json).

Each entry is converted to the LangSmith example shape ``{"inputs", "outputs", "metadata"}``,
where ``outputs`` holds the expected values the evaluators read. Fields the dataset does not
provide get a default that disables that check (``None`` or an empty list), except for two rules
derived from the data and the project rules:

- ``forbidden_citations``: older versions of every expected policy, read from the policy files.
- ``forbidden_actions``: when the expected action is ``link_outage``, a credential reset is
  forbidden (an outage must be linked, not "fixed" with a reset).

Action names and approval decisions follow docs/ARCHITECTURE_CONTRACTS.md (``ActionType`` and
``ActionStatus``). Older action names still used in the dataset are translated on load.
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

# Dataset action names that differ from the contract's ActionType values.
LEGACY_ACTION_NAMES = {
    "answer_from_policy": "answer_policy",
    "link_to_outage": "link_outage",
    "escalate_to_engineer": "escalate",
}


def contract_action(name: str) -> str:
    """Return the contract ActionType value for a dataset action name."""
    return LEGACY_ACTION_NAMES.get(name, name)


def policy_versions(policies_dir: Path = POLICIES_DIR) -> dict[str, list[str]]:
    """Map each doc_id to all of its effective dates, from the policy front matter."""
    versions: dict[str, list[str]] = {}
    for path in sorted(policies_dir.glob("*.md")):
        fields = dict(_FRONT_MATTER_FIELD.findall(path.read_text(encoding="utf-8")))
        if "doc_id" in fields and "effective_date" in fields:
            versions.setdefault(fields["doc_id"], []).append(fields["effective_date"])
    return versions


def to_example(entry: dict[str, Any], versions: dict[str, list[str]]) -> dict[str, Any]:
    """Convert one dataset entry to ``{"inputs", "outputs", "metadata"}``."""
    expected_action = contract_action(entry["expected_action"])
    requires_approval = entry["requires_approval"]
    approval_decision = entry.get("approval_decision", "approved" if requires_approval else None)

    citation = entry.get("expected_citation")
    expected_citations = [citation] if citation else []
    forbidden_citations = [
        {"doc_id": c["doc_id"], "effective_date": date}
        for c in expected_citations
        for date in versions.get(c["doc_id"], [])
        if date < c["effective_date"]
    ]

    forbidden_actions = [contract_action(a) for a in entry.get("forbidden_actions", [])]
    if expected_action == "link_outage" and "reset_credentials" not in forbidden_actions:
        forbidden_actions.append("reset_credentials")

    return {
        "inputs": {
            "example_id": entry["id"],
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
            "requires_approval": requires_approval,
            "should_execute": requires_approval and approval_decision == "approved",
        },
        "metadata": {"id": entry["id"], "notes": entry.get("notes", "")},
    }


def load_examples(
    path: Path = DATASET_PATH, policies_dir: Path = POLICIES_DIR
) -> list[dict[str, Any]]:
    """Load and convert every entry of the evaluation dataset."""
    entries = json.loads(path.read_text(encoding="utf-8"))
    ids = [entry["id"] for entry in entries]
    if len(set(ids)) != len(ids):
        raise ValueError(f"duplicate example ids: {ids}")
    versions = policy_versions(policies_dir)
    return [to_example(entry, versions) for entry in entries]
