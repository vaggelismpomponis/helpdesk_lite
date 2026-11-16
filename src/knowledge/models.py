"""Output contracts of the Knowledge tools (agreed with Workflow)."""
from datetime import date

from pydantic import BaseModel


class PolicyResult(BaseModel):
    text: str
    doc_id: str
    effective_date: date
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
    found: bool
    dependencies: list[str] = []  # service names the application depends on
    active_outages: list[Outage] = []  # open outages on those services
