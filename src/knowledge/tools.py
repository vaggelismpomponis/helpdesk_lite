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
SELECT c.content, c.doc_id, c.effective_date, c.source, (c.embedding <=> %s::vector) AS dist
FROM policy_chunks c JOIN latest USING (doc_id, effective_date)
ORDER BY dist LIMIT 1
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

SERVICE_CYPHER = """
MATCH (s:Service) WHERE toLower(s.name) CONTAINS toLower($name)
WITH s ORDER BY CASE WHEN toLower(s.name) = toLower($name) THEN 0 ELSE 1 END, s.name LIMIT 1
OPTIONAL MATCH (s)-[:HAS_OUTAGE]->(o:Outage {status: 'OPEN'})
RETURN s.name AS application, [s.name] AS dependencies,
       collect(DISTINCT CASE WHEN o IS NULL THEN NULL ELSE {
           outage_id: o.outage_id, service: s.name, title: o.title,
           severity: o.severity, started_at: o.started_at, summary: o.summary} END) AS outages
"""


def retrieve_policy(query: str, application: str | None = None, max_distance: float = 0.74) -> PolicyResult | None:
    """Best-matching chunk of the current version of each policy; None if nothing is indexed or matches.

    `application` only sharpens the query text (policies are not tagged per application).
    """
    if application:
        query = f"{application}: {query}"
    v = vec(embed([query])[0])
    with pg() as conn:
        row = conn.execute(POLICY_SQL, (v,)).fetchone()
    if not row or (len(row) > 4 and row[4] is not None and row[4] > max_distance):
        return None
    return PolicyResult(text=row[0], doc_id=row[1], effective_date=row[2].isoformat(), source=row[3])


def check_graph(application: str) -> GraphResult:
    """Dependencies and active outages of an application or direct service; found=False if unknown."""
    name = application.strip()
    if not name:
        return GraphResult(application=application, found=False)
    with neo4j_driver() as driver:
        records, _, _ = driver.execute_query(GRAPH_CYPHER, name=name)
        if not records:
            records, _, _ = driver.execute_query(SERVICE_CYPHER, name=name)
    if not records:
        return GraphResult(application=name, found=False)
    r = records[0]
    return GraphResult(
        application=r["application"],
        found=True,
        dependencies=r["dependencies"],
        active_outages=sorted({o["service"] for o in r["outages"]}),
        outages=[Outage(**o) for o in r["outages"]],
    )
