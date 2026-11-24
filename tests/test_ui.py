"""Unit tests for the Chainlit Interface (src/app.py)."""

from __future__ import annotations

import sys
import types
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

REPO_ROOT = Path(__file__).resolve().parent.parent


def _install_stub_modules() -> tuple[dict[str, types.ModuleType], list[dict]]:
    """Install lightweight stubs for chainlit and agent modules when running outside Docker venv."""
    sent_messages: list[dict] = []
    session_store: dict[str, object] = {}

    cl_mod = types.ModuleType("chainlit")

    class StubMessage:
        def __init__(self, content: str = "", actions: list | None = None) -> None:
            self.content = content
            self.actions = actions or []
            self.removed_actions = False

        async def send(self):
            sent_messages.append({"content": self.content, "actions": self.actions, "msg": self})
            return self

        async def remove_actions(self):
            self.removed_actions = True
            self.actions = []

    class StubAction:
        def __init__(self, name: str, payload: dict | None = None, label: str = "", value: str = "") -> None:
            self.name = name
            self.payload = payload or {}
            self.value = value
            self.label = label
            self.removed = False

        async def remove(self):
            self.removed = True

    class StubStep:
        def __init__(self, name: str, type: str = "run") -> None:
            self.name = name
            self.type = type
            self.output = ""

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

    class StubUserSession:
        def get(self, key: str, default=None):
            return session_store.get(key, default)

        def set(self, key: str, value: object) -> None:
            session_store[key] = value

    cl_mod.Message = StubMessage
    cl_mod.Action = StubAction
    cl_mod.Step = StubStep
    cl_mod.user_session = StubUserSession()
    cl_mod.context = SimpleNamespace(session=SimpleNamespace(id="sess-123"))
    cl_mod.on_chat_start = lambda fn: fn
    cl_mod.on_message = lambda fn: fn
    cl_mod.action_callback = lambda _name: (lambda fn: fn)
    cl_mod.make_async = lambda fn: (lambda *args, **kwargs: _async_call(fn, *args, **kwargs))

    async def _async_call(fn, *args, **kwargs):
        return fn(*args, **kwargs)

    sys.modules.setdefault("chainlit", cl_mod)
    return {"chainlit": cl_mod}, sent_messages


class TestInterfaceContracts(unittest.TestCase):
    def test_src_app_preserves_docker_and_session_contract(self) -> None:
        content = (REPO_ROOT / "src" / "app.py").read_text(encoding="utf-8")
        self.assertIn("thread_id", content)
        self.assertIn("cl.context.session.id", content)
        self.assertIn("on_chat_start", content)


class TestInterfaceFormattingAndHandlers(unittest.IsolatedAsyncioTestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls._need_stubs = True
        _, cls.sent_messages = _install_stub_modules()
        # Stub pydantic/langgraph dependencies if not installed in host python
        if "src.agent.models" not in sys.modules:
            models_mod = types.ModuleType("src.agent.models")

            class ActionStatus:
                PENDING = SimpleNamespace(value="pending")
                APPROVED = SimpleNamespace(value="approved")
                EXECUTED = SimpleNamespace(value="executed")
                REJECTED = SimpleNamespace(value="rejected")

            class ActionType:
                RESET_CREDENTIALS = SimpleNamespace(value="reset_credentials")
                LINK_OUTAGE = SimpleNamespace(value="link_outage")

            class ActionProposal:
                def __init__(self, **kwargs):
                    self.__dict__.update(kwargs)

                def model_copy(self, update: dict):
                    data = dict(self.__dict__)
                    data.update(update)
                    return ActionProposal(**data)

            class PolicyResult:
                def __init__(self, **kwargs):
                    self.__dict__.update(kwargs)

            class GraphResult:
                def __init__(self, **kwargs):
                    self.__dict__.update(kwargs)

            models_mod.ActionStatus = ActionStatus
            models_mod.ActionType = ActionType
            models_mod.ActionProposal = ActionProposal
            models_mod.PolicyResult = PolicyResult
            models_mod.GraphResult = GraphResult
            sys.modules["src.agent.models"] = models_mod

        if "src.agent.graph" not in sys.modules:
            graph_mod = types.ModuleType("src.agent.graph")
            graph_mod.config_for = lambda tid, user_email=None, **kw: {
                "configurable": {"thread_id": tid, "user_email": user_email},
                "metadata": {"thread_id": tid, **kw.get("metadata", {})},
                "tags": kw.get("tags", []),
            }
            graph_mod.get_production_graph = lambda: MagicMock()
            graph_mod.pending = lambda g, c: None
            sys.modules["src.agent.graph"] = graph_mod

    def setUp(self) -> None:
        import src.app as ui_app

        self.ui_app = ui_app
        if hasattr(self, "sent_messages"):
            self.sent_messages.clear()
        ui_app._handled_actions.clear()

    def test_format_approval_card_includes_action_id_and_parameters(self) -> None:
        from src.agent.models import ActionProposal, ActionStatus, ActionType, GraphResult, PolicyResult

        proposal = ActionProposal(
            action_id="act-uuid-001",
            action_type=ActionType.RESET_CREDENTIALS,
            parameters={"employee": "Maria Papadopoulou", "application": "ERP System"},
            status=ActionStatus.PENDING,
            requires_approval=True,
            rationale="Credential reset requested",
        )
        policy = PolicyResult(
            text="Reset policy",
            doc_id="POL-001",
            effective_date="2026-09-01",
            source="POL-001_password_reset_v2.md",
        )
        graph_res = GraphResult(
            application="ERP System",
            dependencies=["Identity Provider (SSO)"],
            active_outages=[],
        )

        card = self.ui_app.format_approval_card(proposal, "sess-123", policy, graph_res)
        self.assertIn("act-uuid-001", card)
        self.assertIn("reset_credentials", card)
        self.assertIn("Maria Papadopoulou", card)
        self.assertIn("ERP System", card)
        self.assertIn("POL-001", card)
        self.assertIn("2026-09-01", card)

    def test_format_final_response_includes_source_doc_id_and_effective_date(self) -> None:
        from src.agent.models import ActionProposal, ActionStatus, ActionType, PolicyResult

        state_values = {
            "final_response": (
                "Action: reset_credentials [executed]. Credential reset requested.\n"
                "Source: POL-001 (effective 2026-09-01)."
            ),
            "policy_result": PolicyResult(
                text="Policy text",
                doc_id="POL-001",
                effective_date="2026-09-01",
                source="POL-001_password_reset_v2.md",
            ),
            "action_proposal": ActionProposal(
                action_id="act-uuid-002",
                action_type=ActionType.RESET_CREDENTIALS,
                parameters={},
                status=ActionStatus.EXECUTED,
                requires_approval=True,
                rationale="Done",
            ),
        }
        formatted = self.ui_app.format_final_response(state_values, prefix="✅ ")
        self.assertIn("POL-001_password_reset_v2.md", formatted)
        self.assertIn("POL-001", formatted)
        self.assertIn("2026-09-01", formatted)
        self.assertIn("act-uuid-002", formatted)
        self.assertNotIn("Source: POL-001", formatted)
        self.assertNotIn("..", formatted)

    def test_format_step_output_all_nodes(self) -> None:
        from src.agent.models import PolicyResult

        out_policy = self.ui_app.format_step_output(
            "retrieve_policy",
            {
                "policy_result": PolicyResult(
                    text="Visitor Wi-Fi expires after 24h.",
                    doc_id="POL-016",
                    effective_date="2026-01-05",
                    source="POL-016_guest_wi-fi_usage_policy.md",
                )
            },
        )
        self.assertIn("POL-016", out_policy)
        self.assertIn("2026-01-05", out_policy)

        out_missing = self.ui_app.format_step_output("retrieve_policy", {"policy_result": None})
        self.assertIn("No matching policy found", out_missing)

        out_respond_thinking = self.ui_app.format_step_output(
            "respond",
            {"thinking": "SSO outage causes VPN failure.", "final_response": "Action: link_outage."}
        )
        self.assertIn("Thinking / Interpretation:", out_respond_thinking)
        self.assertIn("SSO outage causes VPN failure.", out_respond_thinking)

    async def test_double_click_prevention(self) -> None:
        import chainlit as cl
        from src.agent.models import ActionProposal, ActionStatus, ActionType

        proposal = ActionProposal(
            action_id="act-double-click",
            action_type=ActionType.RESET_CREDENTIALS,
            parameters={"employee": "Maria", "application": "ERP System"},
            status=ActionStatus.PENDING,
            requires_approval=True,
            rationale="Reset",
        )

        mock_graph = MagicMock()
        mock_graph.get_state.side_effect = [
            SimpleNamespace(values={"action_proposal": proposal}),
            SimpleNamespace(
                values={
                    "action_proposal": proposal.model_copy(update={"status": ActionStatus.EXECUTED}),
                    "final_response": "Executed once.",
                }
            ),
        ]

        async def _fake_astream(*_args, **_kwargs):
            yield {"human_approval": {"action_proposal": proposal}}
            yield {"execute_action": {"action_proposal": proposal}}

        mock_graph.astream = _fake_astream
        self.ui_app.graph = mock_graph
        self.ui_app.pending = MagicMock(return_value="approval")

        import json

        action = cl.Action(
            name="approve_action",
            value=json.dumps({"decision": "approve", "action_id": "act-double-click", "thread_id": "sess-123"}),
            label="Approve",
        )
        await self.ui_app.on_approve(action)
        await self.ui_app.on_approve(action)

        # update_state should only be called once despite two clicks
        self.assertEqual(mock_graph.update_state.call_count, 1)
        self.assertTrue(action.removed)


if __name__ == "__main__":
    unittest.main()
