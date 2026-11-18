"""Mock tools with the final signatures, for the Workflow skeleton (no databases needed)."""
from .models import GraphResult, Outage, PolicyResult


def retrieve_policy(query: str, application: str | None = None) -> PolicyResult | None:
    return PolicyResult(
        text="Every credential reset requires explicit human engineer approval.",
        doc_id="POL-001", effective_date="2026-09-01", source="POL-001_password_reset_v2.md",
    )


def check_graph(application: str) -> GraphResult:
    return GraphResult(
        application=application, dependencies=["Identity Provider (SSO)"],
        active_outages=["Identity Provider (SSO)"],
        outages=[Outage(
            outage_id="OUT-2026-01", service="Identity Provider (SSO)",
            title="Identity Provider (SSO) Token Validation Degradation", severity="critical",
            started_at="2026-11-13T14:30:00Z", summary="Intermittent SSO authentication failures.",
        )],
    )
