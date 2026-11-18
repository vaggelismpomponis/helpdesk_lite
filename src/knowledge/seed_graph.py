"""Seed Neo4j from data/graph_seed.json.

Run: python -m src.knowledge.seed_graph   (idempotent: MERGE on ids, properties are overwritten)

Model: (Employee)-[:MEMBER_OF]->(Team) · (Service)-[:OWNED_BY]->(Team)
       (Application)-[:DEPENDS_ON]->(Service)-[:HAS_OUTAGE]->(Outage {status})
"""
import json
from pathlib import Path

from .common import neo4j_driver

SEED = Path(__file__).resolve().parents[1] / "data" / "graph_seed.json"

CONSTRAINTS = [
    f"CREATE CONSTRAINT IF NOT EXISTS FOR (n:{label}) REQUIRE n.{key} IS UNIQUE"
    for label, key in [
        ("Team", "team_id"), ("Employee", "employee_id"), ("Service", "service_id"),
        ("Application", "app_id"), ("Outage", "outage_id"),
    ]
]

STATEMENTS = [
    "UNWIND $teams AS t MERGE (n:Team {team_id: t.team_id}) SET n.name = t.name, n.lead_email = t.lead_email",
    """UNWIND $employees AS e MERGE (n:Employee {employee_id: e.employee_id})
       SET n.name = e.name, n.email = e.email, n.office = e.office, n.device = e.device
       WITH n, e MATCH (t:Team {team_id: e.team_id}) MERGE (n)-[:MEMBER_OF]->(t)""",
    """UNWIND $services AS s MERGE (n:Service {service_id: s.service_id}) SET n.name = s.name
       WITH n, s MATCH (t:Team {team_id: s.owner_team}) MERGE (n)-[:OWNED_BY]->(t)""",
    """UNWIND $applications AS a MERGE (n:Application {app_id: a.app_id})
       SET n.name = a.name, n.criticality = a.criticality
       WITH n, a UNWIND a.depends_on_services AS sid
       MATCH (s:Service {service_id: sid}) MERGE (n)-[:DEPENDS_ON]->(s)""",
    """UNWIND $outages AS o MERGE (n:Outage {outage_id: o.outage_id})
       SET n.title = o.title, n.status = o.status, n.started_at = o.started_at,
           n.severity = o.severity, n.summary = o.summary
       WITH n, o MATCH (s:Service {service_id: o.service_id}) MERGE (s)-[:HAS_OUTAGE]->(n)""",
]


def seed() -> None:
    data = json.loads(SEED.read_text(encoding="utf-8"))
    with neo4j_driver() as driver, driver.session() as session:
        for c in CONSTRAINTS:
            session.run(c).consume()
        for q in STATEMENTS:
            session.run(q, **data).consume()


if __name__ == "__main__":
    seed()
    print("seeded Neo4j")
