"""Workflow contracts, as signed off in docs/ARCHITECTURE_CONTRACTS.md (sections 2 and 3).

PolicyResult and GraphResult are owned by Knowledge (src/knowledge/models.py) and re-exported here.
"""

from enum import Enum
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field

from src.knowledge.models import GraphResult, PolicyResult

__all__ = [
    "ActionProposal",
    "ActionStatus",
    "ActionType",
    "AgentState",
    "ExtractedFields",
    "GraphResult",
    "PolicyResult",
    "STATE_CHANGING_ACTIONS",
]


class ActionType(str, Enum):
    ANSWER_POLICY = "answer_policy"
    LINK_OUTAGE = "link_outage"
    RESET_CREDENTIALS = "reset_credentials"
    OPEN_TICKET = "open_ticket"
    ESCALATE = "escalate"


STATE_CHANGING_ACTIONS = {ActionType.RESET_CREDENTIALS, ActionType.OPEN_TICKET, ActionType.ESCALATE}


class ActionStatus(str, Enum):
    PENDING = "pending"
    APPROVED = "approved"
    EXECUTED = "executed"
    REJECTED = "rejected"


class ExtractedFields(BaseModel):
    employee: Optional[str] = Field(default=None, description="Name or identifier of the employee")
    application: Optional[str] = Field(default=None, description="Name of the affected application or system")
    symptom: Optional[str] = Field(default=None, description="Observed symptom or error description")
    urgency: Optional[str] = Field(default=None, description="Urgency level (e.g. low, medium, high)")
    office: Optional[str] = Field(default=None, description="Office the employee works from (e.g. Athens)")
    device: Optional[str] = Field(default=None, description="Device the employee uses (e.g. MacBook Pro)")

    def missing_fields(self) -> List[str]:
        """Returns the list of mandatory triage fields that are missing.

        Office and device must be confirmed before acting (POL-001 v2). The application is optional:
        it is used for the outage check when named, but requests such as a new software license do
        not concern a known application.
        """
        required = ("employee", "symptom", "office", "device")
        return [name for name in required if not getattr(self, name)]

    def is_complete(self) -> bool:
        """Returns True only when all mandatory triage fields are present."""
        return len(self.missing_fields()) == 0

    @property
    def has_missing_fields(self) -> bool:
        return not self.is_complete()


class ActionProposal(BaseModel):
    action_id: str = Field(description="Unique UUID for idempotency tracking")
    action_type: ActionType = Field(description="One of the 5 action types")
    parameters: Dict[str, Any] = Field(default_factory=dict, description="Action-specific execution parameters")
    status: ActionStatus = Field(default=ActionStatus.PENDING, description="Current execution lifecycle status")
    requires_approval: bool = Field(default=False, description="True for state-changing actions")
    rationale: str = Field(default="", description="Reasoning for action selection")


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
    thinking: Optional[str] = Field(default=None, description="LLM reasoning and interpretation of results")
