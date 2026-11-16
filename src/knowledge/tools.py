"""Tools called by the Workflow nodes: retrieve_policy and check_graph."""
from .common import embed, neo4j_driver, pg, vec
from .models import GraphResult, Outage, PolicyResult

# Latest version per doc_id wins (never a future-dated one), THEN rank by similarity,
# so an outdated version can never outrank the current one.
POLICY_SQL = """
WITH latest AS (
    SELECT doc_id, max(effective_date) AS effective_date
    FROM policy_chunks WHERE effective_date <= current_date GROUP BY doc_id
)
SELECT c.content, c.doc_id, c.effective_date, c.source
FROM policy_chunks c JOIN latest USING (doc_id, effective_date)
ORDER BY c.embedding <=> %s::vector LIMIT 1
"""

# Open outages on the services the application depends on. Parameterised: no string building.
GRAPH_CYPHER = """
MATCH (a:Application) WHERE toLower(a.name) CONTAINS toLower($name)
WITH a ORDER BY CASE WHEN toLower(a.name) = toLower($name) THEN 0 ELSE 1 END, a.name LIMIT 1
OPTIONAL MATCH (a)-[:DEPENDS_ON]->(s:Service)
OPTIONAL MATCH (s)-[:HAS_OUTAGE]->(o:Outage {status: 'OPEN'})
RETURN a.name AS application, collect(DISTINCT s.name) AS dependencies,
       collect(DISTINCT CASE WHEN o IS NULL THEN NULL ELSE {
           outage_id: o.outage_id, service: s.name, title: o.title,
           severity: o.severity, started_at: o.started_at, summary: o.summary} END) AS outages
"""


def retrieve_policy(query: str) -> PolicyResult | None:
    """Best-matching chunk of the current version of each policy; None if nothing is indexed."""
    with pg() as conn:
        row = conn.execute(POLICY_SQL, (vec(embed([query])[0]),)).fetchone()
    return PolicyResult(text=row[0], doc_id=row[1], effective_date=row[2], source=row[3]) if row else None


def check_graph(application: str) -> GraphResult:
    """Dependencies and active outages of an application; found=False if it is unknown."""
    name = application.strip()
    if not name:
        return GraphResult(application=application, found=False)
    with neo4j_driver() as driver:
        records, _, _ = driver.execute_query(GRAPH_CYPHER, name=name)
    if not records:
        return GraphResult(application=name, found=False)
    r = records[0]
    return GraphResult(
        application=r["application"],
        found=True,
        dependencies=r["dependencies"],
        active_outages=[Outage(**o) for o in r["outages"]],
    )
