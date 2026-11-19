# Knowledge → Quality handoff (10 eval requests)

Source of truth: `src/data/eval_dataset.json` (requests, expected action, expected citation) and
`src/data/graph_seed.json` (graph). `retrieve_policy` must return the **latest effective version**;
`check_graph` reports open outages on the services an application depends on.

| Request | Expected action | Expected citation | Graph expectation (from seed) |
|---|---|---|---|
| EVAL-01 | link_to_outage | `POL-001` 2026-09-01 | Corporate VPN → outages: OUT-2026-01 (text says "VPN") |
| EVAL-02 | answer_from_policy | `POL-016` 2026-01-05 | no application named in text (extracted by Workflow) |
| EVAL-03 | answer_from_policy | `POL-008` 2026-01-10 | no application named in text (extracted by Workflow) |
| EVAL-04 | answer_from_policy | `POL-001` 2026-09-01 | no application named in text (extracted by Workflow) |
| EVAL-05 | answer_from_policy | `POL-001` 2026-09-01 | no application named in text (extracted by Workflow) |
| EVAL-06 | link_to_outage | `POL-003` 2026-08-20 | Email & Calendar → outages: OUT-2026-02 |
| EVAL-07 | reset_credentials | `POL-001` 2026-09-01 | ERP System → outages: none |
| EVAL-08 | reset_credentials | `POL-001` 2026-09-01 | CRM → outages: none |
| EVAL-09 | open_ticket | `POL-004` 2026-05-01 | no application named in text (extracted by Workflow) |
| EVAL-10 | escalate_to_engineer | `POL-012` 2026-02-28 | no application named in text (extracted by Workflow) |

Notes for Quality:
- Open outages: `OUT-2026-01` (Identity Provider SSO, affects Corporate VPN, Finance Portal, GitHub Enterprise), `OUT-2026-02` (SMTP relay, affects Email & Calendar).
- `POL-001` has two versions (2024-03-15 and 2026-09-01); the correct citation is always 2026-09-01.
- Without an embedding key the tools use a lexical fallback (weaker than OpenAI); set `AZURE_OPENAI_API_KEY` for the real evaluation run.
- Tool contract: `docs/ARCHITECTURE_CONTRACTS.md` (on `docs/repo-structure`). Extras beyond it: `GraphResult.found`, `GraphResult.outages` (outage_id, severity, summary).
- Naming mismatch to settle with Workflow/Quality: the dataset uses `link_to_outage`, `answer_from_policy`, `escalate_to_engineer`; the contract enum uses `link_outage`, `answer_policy`, `escalate`.
