# Architecture Contracts & Day 1 Alignment Specification

**Project:** HelpDesk Lite  
**Scope:** Architecture Contracts, Pydantic Schemas, Tool Signatures, Action Lifecycle  
**Target Date:** 2026-11-16 (Day 1 Kick-off)  
**Status:** Agreed & Decided (All 5 Roles Aligned)  
**Code Reference:** [`src/agent/schemas.py`](../src/agent/schemas.py), [`src/agent/state.py`](../src/agent/state.py), [`src/agent/tools.py`](../src/agent/tools.py)

---

## 1. Executive Summary & Contracts-First Strategy

To enable 5 team members to develop simultaneously across different branches without waiting on each other and with **zero merge conflicts**, all core interfaces, data structures, and tool signatures are frozen as immutable contracts on Day 1.

```text
+---------------------------------------------------------------------------------+
|                                 Day 1 Contracts                                 |
|                                                                                 |
|  AgentState (Pydantic)  <--->  ExtractedFields  <--->  PolicyResult/GraphResult |
|           |                                                      |              |
|           +-----------------> ActionProposal (5 Actions) <-------+              |
+---------------------------------------------------------------------------------+
       |                              |                            |
       v                              v                            v
  [Interface]                    [Workflow]                   [Knowledge]
 Chainlit UI & Cards          LangGraph Nodes/Edges       Ingestion & Seeding
  (Mock Graph OK)                (Mock Tools OK)           (Mock Returns OK)
```

Each role builds against these contracts using mocks until integration in Phase 4.

---

## 2. Core Pydantic Models & Schemas

### 2.1 Action Types (`ActionType`)

The system supports exactly 5 mutually exclusive action types:

```python
from enum import Enum

class ActionType(str, Enum):
    ANSWER_POLICY = "answer_policy"         # Answer user inquiry based on cited policy
    LINK_OUTAGE = "link_outage"             # Link incident to an active infrastructure outage
    RESET_CREDENTIALS = "reset_credentials" # Trigger account/password reset (State-Changing)
    OPEN_TICKET = "open_ticket"             # Create IT support ticket in Postgres (State-Changing)
    ESCALATE = "escalate"                   # Escalate to Tier-2 human engineer (State-Changing)
```

### 2.2 Action Lifecycle Status (`ActionStatus`)

State-changing actions follow a strict state machine to guarantee human-in-the-loop safety and idempotency:

```python
class ActionStatus(str, Enum):
    PENDING = "pending"       # Action proposed, awaiting human approval
    APPROVED = "approved"     # Approved by human operator
    EXECUTED = "executed"     # Successfully executed; cannot be re-executed
    REJECTED = "rejected"     # Rejected by human operator; abort or alternative action
```

### 2.3 Extracted User Fields (`ExtractedFields`)

Extracted from incoming free-form user IT support requests:

```python
from typing import Optional
from pydantic import BaseModel, Field

class ExtractedFields(BaseModel):
    employee: Optional[str] = Field(default=None, description="Name or identifier of the employee")
    application: Optional[str] = Field(default=None, description="Name of the affected application or system")
    symptom: Optional[str] = Field(default=None, description="Observed symptom or error description")
    urgency: Optional[str] = Field(default=None, description="Urgency level (e.g. low, medium, high)")

    def is_complete(self) -> bool:
        """Returns True only when all mandatory triage fields are present."""
        return all([self.employee, self.application, self.symptom])
```

*Contract Rule:* If `is_complete()` is `False`, the agent **must not guess**. It must transition to `ask_clarification` to prompt the user.

### 2.4 Policy Search Contract (`PolicyResult`)

Returned by the vector store (`PostgreSQL + pgvector`):

```python
class PolicyResult(BaseModel):
    text: str = Field(description="Content chunk of the retrieved policy")
    doc_id: str = Field(description="Unique document ID (e.g. POL-SEC-004)")
    effective_date: str = Field(description="ISO 8601 date (YYYY-MM-DD) of policy version")
    source: str = Field(description="Filename or canonical title")
```

*Contract Rule (Effective Date Precedence):* When documents share the same `doc_id` with overlapping or conflicting rules, the record with the most recent `effective_date` **strictly wins**. Citations in final answers must cite `doc_id` and `effective_date`.

### 2.5 Infrastructure Graph Contract (`GraphResult`)

Returned by the graph database (`Neo4j`):

```python
from typing import List

class GraphResult(BaseModel):
    application: str = Field(description="Queried application name")
    dependencies: List[str] = Field(default_factory=list, description="Dependent backend services")
    active_outages: List[str] = Field(default_factory=list, description="Services with active outages")

    @property
    def has_active_outage(self) -> bool:
        return len(self.active_outages) > 0
```

*Contract Rule (Outage Precedence):* If `has_active_outage` is `True` for any dependency of the target application, `decide_action` must propose `ActionType.LINK_OUTAGE`. It must **never** propose `ActionType.RESET_CREDENTIALS` when a dependency outage explains the symptom.

### 2.6 Action Proposal (`ActionProposal`)

Encapsulates the action awaiting execution or human approval:

```python
from typing import Any, Dict

class ActionProposal(BaseModel):
    action_id: str = Field(description="Unique UUID for idempotency tracking")
    action_type: ActionType = Field(description="One of the 5 action types")
    parameters: Dict[str, Any] = Field(default_factory=dict, description="Action-specific execution parameters")
    status: ActionStatus = Field(default=ActionStatus.PENDING, description="Current execution lifecycle status")
    requires_approval: bool = Field(default=False, description="True for state-changing actions")
    rationale: str = Field(default="", description="Reasoning for action selection")
```

---

## 3. Persistent Agent State (`AgentState`)

Managed by LangGraph with `PostgresSaver`:

```python
class AgentState(BaseModel):
    thread_id: str = Field(default="", description="Unique session ID linked 1:1 with Chainlit session")
    messages: List[Dict[str, Any]] = Field(default_factory=list, description="Conversation history messages")
    extracted_fields: Optional[ExtractedFields] = Field(default=None, description="Extracted entity fields")
    needs_clarification: bool = Field(default=False, description="Flag indicating missing essential fields")
    clarification_question: Optional[str] = Field(default=None, description="Clarification question to user")
    policy_result: Optional[PolicyResult] = Field(default=None, description="Retrieved policy document chunk")
    graph_result: Optional[GraphResult] = Field(default=None, description="Dependency and outage status")
    action_proposal: Optional[ActionProposal] = Field(default=None, description="Proposed action & status")
    final_response: Optional[str] = Field(default=None, description="Final assistant message with citations")
```

### Session Mapping & Restart Safety
- `thread_id` must match the Chainlit session identifier.
- When an interrupt occurs (e.g. `ask_clarification` or `human_approval`), the complete state is checkpointed in PostgreSQL.
- If the application container restarts, reloading the Chainlit session resumes execution seamlessly from the checkpoint.
- Idempotency guard: Before `execute_action` runs, it checks whether `action_id` in Postgres is already `ActionStatus.EXECUTED`. If yes, it skips re-execution to prevent duplicate account resets or tickets.

---

## 4. Tool Signatures

Tools invoked by LangGraph nodes:

```python
def retrieve_policy(query: str, application: Optional[str] = None) -> PolicyResult:
    """Retrieve policy document chunk with semantic search and latest effective date resolution.
    
    Args:
        query: Search query string (symptom or policy topic).
        application: Optional application name filter.
        
    Returns:
        PolicyResult with chunk text, doc_id, effective_date, and source.
    """
    ...

def check_graph(application: str) -> GraphResult:
    """Check Neo4j for service dependencies and active outages for a given application.
    
    Args:
        application: Name of the application to inspect.
        
    Returns:
        GraphResult with application name, dependencies, and active outages.
    """
    ...
```

---

## 5. Decision Precedence Matrix

| Condition | Proposed Action | Requires Approval | Next Node |
|---|---|---|---|
| `not extracted_fields.is_complete()` | Clarification prompt | No | `ask_clarification` (Interrupt) |
| `graph_result.has_active_outage == True` | `ActionType.LINK_OUTAGE` | No | `final_response` |
| Known policy matches query | `ActionType.ANSWER_POLICY` | No | `final_response` |
| Policy mandates password/credential reset | `ActionType.RESET_CREDENTIALS` | **Yes** | `human_approval` (Interrupt) |
| Standard issue requiring investigation | `ActionType.OPEN_TICKET` | **Yes** | `human_approval` (Interrupt) |
| Critical incident or VIP employee | `ActionType.ESCALATE` | **Yes** | `human_approval` (Interrupt) |

---

## 6. Team Sign-off Matrix (Day 1 Contracts)

| Role | Representative | Focus Area | Status | Date |
|---|---|---|---|---|
| **Platform** | @vaggelismpomponis | Schema persistence & Docker/DB alignment | **Signed-off** | 2026-11-16 |
| **Workflow** | All members | State schema, nodes, edges & interrupts | **Signed-off** | 2026-11-16 |
| **Interface** | @AlexZarkalis | UI payload, approval cards & `thread_id` | **Signed-off** | 2026-11-16 |
| **Knowledge** | @stef-fot | `PolicyResult`, `GraphResult` tool contracts | **Signed-off** | 2026-11-16 |
| **Quality** | @VickyMil-ai | Evaluator contracts & 10 test scenarios | **Signed-off** | 2026-11-16 |
