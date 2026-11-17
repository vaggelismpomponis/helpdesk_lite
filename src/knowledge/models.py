"""Output contracts of the Knowledge tools (agreed with Workflow)."""
from pydantic import BaseModel


class PolicyResult(BaseModel):
    text: str
    doc_id: str
    effective_date: str  # ISO 8601 (YYYY-MM-DD), per ARCHITECTURE_CONTRACTS
    source: str  # file the chunk came from, shown in the citation


class Outage(BaseModel):
    outage_id: str
    service: str
    title: str
    severity: str
    started_at: str
    summary: str


class GraphResult(BaseModel):
    application: str  # canonical name as stored in the graph
    dependencies: list[str] = []  # service names the application depends on
    active_outages: list[str] = []  # names of dependency services with an open outage (contract)
    # Additions beyond the contract (defaults keep contract consumers working):
    found: bool = True  # False when the application is unknown
    outages: list[Outage] = []  # details, e.g. outage_id for the link_outage action

    @property
    def has_active_outage(self) -> bool:
        return bool(self.active_outages)
