# Neo4j graph model

```mermaid
flowchart LR
    E[Employee] -- MEMBER_OF --> T[Team]
    S[Service] -- OWNED_BY --> T
    A[Application] -- DEPENDS_ON --> S
    S -- HAS_OUTAGE --> O["Outage (status OPEN/RESOLVED)"]
```

Keys: `employee_id`, `team_id`, `service_id`, `app_id`, `outage_id` (unique constraints).
Seeded by `python -m src.knowledge.seed_graph` (MERGE, idempotent). `check_graph` follows
`Application -DEPENDS_ON-> Service -HAS_OUTAGE-> Outage {status: 'OPEN'}`.
