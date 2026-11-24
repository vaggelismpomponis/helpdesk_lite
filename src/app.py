"""HelpDesk Lite - Chainlit Application Entrypoint.

Implements the Interface role deliverables (docs/roles/interface.md) against the
agreed contracts (docs/ARCHITECTURE_CONTRACTS.md) and LangGraph workflow
(src/agent/graph.py):
- 1:1 binding of Chainlit session id (`cl.context.session.id`) to LangGraph `thread_id`
  (plus `/resume <thread_id>`)
- Per-node progress steps via `cl.Step` (`extract_fields`, `retrieve_policy`,
  `check_graph`, `decide_action`, `human_approval`, `execute_action`, `respond`)
- Clarification interrupt handling and resumption
- Approval cards displaying `action_id`, `action_type`, `parameters`, `rationale`,
  and Approve/Reject buttons
- Double-click prevention and idempotent action handling
- Policy citations (`source`, `doc_id`, `effective_date`) in final responses
- Graceful error handling when tools or graph execution fail
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Optional

import chainlit as cl

from src.agent.graph import config_for, get_production_graph, pending
from src.agent.models import ActionProposal, ActionStatus, GraphResult, PolicyResult

logger = logging.getLogger(__name__)

graph = get_production_graph()

NODE_STEP_NAMES: dict[str, str] = {
    "extract_fields": "1. Extract Fields",
    "ask_clarification": "Clarification Requested",
    "retrieve_policy": "2. Retrieve Policy",
    "check_graph": "3. Check Service Graph",
    "decide_action": "4. Decide Action",
    "human_approval": "5. Human Approval",
    "execute_action": "6. Execute Action",
    "respond": "7. Final Response",
}

_action_locks: dict[str, asyncio.Lock] = {}
_handled_actions: set[str] = set()


def _get_lock(key: str) -> asyncio.Lock:
    if key not in _action_locks:
        _action_locks[key] = asyncio.Lock()
    return _action_locks[key]


def format_step_output(node_name: str, node_output: dict[str, Any]) -> str:
    """Format a LangGraph node update into a readable Chainlit step output."""
    if not isinstance(node_output, dict):
        return str(node_output)

    if node_name == "extract_fields":
        fields = node_output.get("extracted_fields")
        needs_clarification = node_output.get("needs_clarification", False)
        if fields is None:
            return "No fields extracted."
        lines = [
            f"- **Employee:** `{fields.employee or 'Missing'}`",
            f"- **Application:** `{fields.application or 'Missing'}`",
            f"- **Symptom:** `{fields.symptom or 'Missing'}`",
            f"- **Urgency:** `{fields.urgency or 'normal'}`",
            f"- **Needs Clarification:** `{needs_clarification}`",
        ]
        if node_output.get("clarification_question"):
            lines.append(f"- **Question:** {node_output['clarification_question']}")
        return "\n".join(lines)

    if node_name == "retrieve_policy":
        policy: Optional[PolicyResult] = node_output.get("policy_result")
        if policy is None:
            return "No matching policy found."
        preview = policy.text[:300] + ("..." if len(policy.text) > 300 else "")
        return (
            f"- **Document ID:** `{policy.doc_id}`\n"
            f"- **Effective Date:** `{policy.effective_date}`\n"
            f"- **Source:** `{policy.source}`\n"
            f"- **Excerpt:** {preview}"
        )

    if node_name == "check_graph":
        graph_res: Optional[GraphResult] = node_output.get("graph_result")
        if graph_res is None:
            return "No application specified for service graph lookup."
        deps = ", ".join(graph_res.dependencies) if graph_res.dependencies else "None"
        outages = ", ".join(graph_res.active_outages) if graph_res.active_outages else "None"
        return (
            f"- **Application:** `{graph_res.application}`\n"
            f"- **Dependencies:** {deps}\n"
            f"- **Active Outages:** {outages}"
        )

    if node_name == "decide_action":
        proposal: Optional[ActionProposal] = node_output.get("action_proposal")
        if proposal is None:
            return "No action proposed."
        return (
            f"- **Action ID:** `{proposal.action_id}`\n"
            f"- **Action Type:** `{proposal.action_type.value}`\n"
            f"- **Requires Approval:** `{proposal.requires_approval}`\n"
            f"- **Status:** `{proposal.status.value}`\n"
            f"- **Parameters:** `{proposal.parameters}`\n"
            f"- **Rationale:** {proposal.rationale}"
        )

    if node_name in ("human_approval", "execute_action"):
        proposal = node_output.get("action_proposal")
        if proposal is None:
            return str(node_output)
        return f"- **Action ID:** `{proposal.action_id}`\n- **Status:** `{proposal.status.value}`"

    if node_name == "respond":
        thinking = node_output.get("thinking")
        final_resp = node_output.get("final_response") or "Response generated."
        if thinking:
            return f"💭 **Thinking / Interpretation:**\n{thinking}\n\n**Response:**\n{final_resp}"
        return final_resp

    if node_name == "ask_clarification":
        msgs = node_output.get("messages") or []
        return msgs[-1].get("content", "") if msgs else "Clarification requested."

    return str(node_output)


def format_approval_card(
    proposal: ActionProposal,
    thread_id: str,
    policy_result: Optional[PolicyResult] = None,
    graph_result: Optional[GraphResult] = None,
) -> str:
    """Build the markdown approval card containing action_id, action, parameters, and context."""
    params_lines = (
        "\n".join(f"  - **{k}:** `{v}`" for k, v in proposal.parameters.items())
        if proposal.parameters
        else "  - *(none)*"
    )
    lines = [
        "⚠️ **Approval Required for State-Changing Action**",
        "",
        f"- **Action ID:** `{proposal.action_id}`",
        f"- **Action:** `{proposal.action_type.value}`",
        f"- **Status:** `{proposal.status.value}`",
        f"- **Thread ID:** `{thread_id}`",
        f"- **Rationale:** {proposal.rationale}",
        "- **Parameters:**",
        params_lines,
    ]
    if policy_result is not None:
        lines.append(
            f"- **Policy Citation:** `{policy_result.doc_id}` ({policy_result.source}, "
            f"effective `{policy_result.effective_date}`)"
        )
    if graph_result is not None and graph_result.active_outages:
        lines.append(f"- **Active Outages:** `{', '.join(graph_result.active_outages)}`")
    lines.extend(["", "Please approve or reject this action:"])
    return "\n".join(lines)


def build_approval_actions(action_id: str, thread_id: str) -> list[cl.Action]:
    """Create Approve and Reject buttons bound to action_id and thread_id."""
    import json

    approve_data = json.dumps({"decision": "approve", "action_id": action_id, "thread_id": thread_id})
    reject_data = json.dumps({"decision": "reject", "action_id": action_id, "thread_id": thread_id})
    return [
        cl.Action(
            name="approve_action",
            value=approve_data,
            label="✅ Approve",
        ),
        cl.Action(
            name="reject_action",
            value=reject_data,
            label="❌ Reject",
        ),
    ]


def format_final_response(state_values: dict[str, Any], prefix: str = "") -> str:
    """Format the final assistant response with policy citations (source, doc_id, effective_date)."""
    import re

    base_text = (state_values.get("final_response") or "Your request has been processed.").strip()
    policy: Optional[PolicyResult] = state_values.get("policy_result")
    if policy is not None:
        # Remove trailing inline "Source: POL-XXX (effective YYYY-MM-DD)." from respond node
        # so the rich Policy Citation line below does not duplicate it.
        base_text = re.sub(
            r"\s*Source:\s*"
            + re.escape(policy.doc_id)
            + r"\s*\(effective\s*"
            + re.escape(policy.effective_date)
            + r"\)\.?\s*$",
            "",
            base_text,
        ).strip()

    base_text = re.sub(r"\.\.+", ".", base_text)
    lines = [f"{prefix}{base_text}" if prefix else base_text]

    if policy is not None:
        lines.append(
            f"\n**Policy Citation:** {policy.source} (`{policy.doc_id}`, effective `{policy.effective_date}`)"
        )

    proposal: Optional[ActionProposal] = state_values.get("action_proposal")
    if proposal is not None:
        lines.append(f"**Action ID:** `{proposal.action_id}` (`{proposal.status.value}`)")

    return "\n".join(lines)


async def _send_approval_card(state_values: dict[str, Any], thread_id: str) -> None:
    """Send the approval card and store its message reference for button removal on click."""
    proposal: Optional[ActionProposal] = state_values.get("action_proposal")
    if proposal is None:
        await cl.Message(content="⚠️ Approval is required, but no action proposal was found.").send()
        return

    card_text = format_approval_card(
        proposal=proposal,
        thread_id=thread_id,
        policy_result=state_values.get("policy_result"),
        graph_result=state_values.get("graph_result"),
    )
    actions = build_approval_actions(proposal.action_id, thread_id)
    msg = cl.Message(content=card_text, actions=actions)
    await msg.send()
    cl.user_session.set(f"approval_msg:{proposal.action_id}", msg)


async def _stream_graph_with_steps(inputs: Optional[dict[str, Any]], config: dict[str, Any]) -> None:
    """Stream LangGraph updates and emit a Chainlit Step for each executed node."""
    async for event in graph.astream(inputs, config=config, stream_mode="updates"):
        for node_name, node_output in event.items():
            step_title = NODE_STEP_NAMES.get(node_name, node_name)
            async with cl.Step(name=step_title, type="run") as step:
                step.output = format_step_output(node_name, node_output)


async def _restore_or_greet(thread_id: str, *, is_manual_resume: bool = False) -> None:
    """Inspect checkpoint for thread_id and either restore paused state or greet the user."""
    config = config_for(
        thread_id,
        user_email=cl.user_session.get("user_email"),
        tags=["chainlit"],
        metadata={"source": "chainlit"},
    )
    try:
        state = await cl.make_async(graph.get_state)(config)
    except Exception as exc:
        logger.exception("Failed to read graph state for thread %s", thread_id)
        if is_manual_resume:
            await cl.Message(
                content=f"❌ Could not load session `{thread_id}` from checkpoint store: {exc}"
            ).send()
            return
        state = None

    if state and state.values and state.values.get("messages"):
        last_msg = state.values["messages"][-1]
        await cl.Message(
            content=(
                f"🔄 **Session restored from database checkpoint!**\n\n"
                f"Resuming conversation for thread `{thread_id}`:\n\n"
                f"{last_msg.get('content', '')}"
            )
        ).send()

        wait_reason = await cl.make_async(pending)(graph, config)
        if wait_reason == "approval":
            await _send_approval_card(state.values, thread_id)
        elif wait_reason == "clarification":
            question = state.values.get("clarification_question") or "Could you please clarify your request?"
            await cl.Message(content=question).send()
    elif is_manual_resume:
        await cl.Message(content=f"ℹ️ No saved checkpoint found for thread `{thread_id}`.").send()
    else:
        await cl.Message(
            content=(
                "**Welcome to HelpDesk Lite!** 🛠️\n\n"
                f"Active thread: `{thread_id}`\n"
                "I am your agentic IT support assistant. How can I help you today?\n"
                "*(Tip: after a restart, use `/resume <thread_id>` to restore a previous session.)*"
            )
        ).send()


@cl.on_chat_start
async def on_chat_start() -> None:
    """Initialize a chat session, bind thread_id to session id, and resume from checkpoint if restarting."""
    session_id = cl.context.session.id
    cl.user_session.set("thread_id", session_id)
    await _restore_or_greet(session_id, is_manual_resume=False)


@cl.on_message
async def on_message(message: cl.Message) -> None:
    """Handle incoming user messages, route through LangGraph with progress steps, and handle interrupts."""
    text = message.content.strip()

    if text.startswith("/resume "):
        target_thread_id = text.split(maxsplit=1)[1].strip()
        if not target_thread_id:
            await cl.Message(content="Usage: `/resume <thread_id>`").send()
            return
        cl.user_session.set("thread_id", target_thread_id)
        await _restore_or_greet(target_thread_id, is_manual_resume=True)
        return

    thread_id = cl.user_session.get("thread_id") or cl.context.session.id
    cl.user_session.set("thread_id", thread_id)
    config = config_for(
        thread_id,
        user_email=cl.user_session.get("user_email"),
        tags=["chainlit"],
        metadata={"source": "chainlit"},
    )

    try:
        wait_reason = await cl.make_async(pending)(graph, config)
        if wait_reason == "approval":
            state = await cl.make_async(graph.get_state)(config)
            await cl.Message(
                content="⏳ An action is currently awaiting your **Approve** or **Reject** decision."
            ).send()
            await _send_approval_card(state.values, thread_id)
            return

        if wait_reason == "clarification":
            state = await cl.make_async(graph.get_state)(config)
            messages = state.values.get("messages", [])
            await cl.make_async(graph.update_state)(
                config,
                {"messages": [*messages, {"role": "user", "content": message.content}]},
            )
            await _stream_graph_with_steps(None, config)
        else:
            state = await cl.make_async(graph.get_state)(config)
            prev_messages = (state.values.get("messages") if state and state.values else None) or []
            inputs = {
                "thread_id": thread_id,
                "messages": [*prev_messages, {"role": "user", "content": message.content}],
            }
            await _stream_graph_with_steps(inputs, config)

        state = await cl.make_async(graph.get_state)(config)
        wait_reason = await cl.make_async(pending)(graph, config)

        if wait_reason == "clarification":
            question = state.values.get("clarification_question") or "Could you please clarify your request?"
            await cl.Message(content=question).send()
        elif wait_reason == "approval":
            await _send_approval_card(state.values, thread_id)
        else:
            await cl.Message(content=format_final_response(state.values)).send()
    except Exception as exc:
        logger.exception("Error processing message for thread %s", thread_id)
        await cl.Message(
            content=(
                "❌ **Something went wrong while processing your request.**\n\n"
                f"Details: `{exc}`\n"
                "Please try again or contact support if the issue persists."
            )
        ).send()


async def _handle_approval_decision(action: cl.Action, approved: bool) -> None:
    """Process Approve/Reject button clicks with double-click protection and error handling."""
    payload = getattr(action, "payload", None)
    if not payload and hasattr(action, "value") and action.value:
        try:
            import json

            payload = json.loads(action.value) if isinstance(action.value, str) else action.value
        except Exception:
            payload = {"action_id": str(action.value)}
    payload = payload or {}
    action_id = payload.get("action_id", "")
    thread_id = payload.get("thread_id")
    if not thread_id:
        try:
            thread_id = cl.user_session.get("thread_id") or cl.context.session.id
        except Exception:
            thread_id = "default_thread"

    lock = _get_lock(action_id or thread_id)

    async with lock:
        approval_msg = None
        if action_id:
            try:
                approval_msg = cl.user_session.get(f"approval_msg:{action_id}")
            except Exception:
                approval_msg = None

        if approval_msg is not None:
            try:
                await approval_msg.remove_actions()
            except Exception:
                pass
        try:
            await action.remove()
        except Exception:
            pass

        user_email = None
        try:
            user_email = cl.user_session.get("user_email")
        except Exception:
            pass

        config = config_for(
            thread_id,
            user_email=user_email,
            action_id=action_id or None,
            tags=["chainlit", "approval"],
            metadata={"source": "chainlit", "action_id": action_id} if action_id else {"source": "chainlit"},
        )

        try:
            wait_reason = await cl.make_async(pending)(graph, config)
            if (action_id and action_id in _handled_actions) or wait_reason != "approval":
                await cl.Message(content="ℹ️ This action has already been processed.").send()
                return

            state = await cl.make_async(graph.get_state)(config)
            proposal: Optional[ActionProposal] = state.values.get("action_proposal")
            if proposal is None:
                await cl.Message(content="⚠️ No pending action proposal found.").send()
                return
            if action_id and proposal.action_id != action_id:
                await cl.Message(content="ℹ️ This approval card is no longer active.").send()
                return

            if action_id:
                _handled_actions.add(action_id)

            new_status = ActionStatus.APPROVED if approved else ActionStatus.REJECTED
            await cl.make_async(graph.update_state)(
                config,
                {"action_proposal": proposal.model_copy(update={"status": new_status})},
            )
            await _stream_graph_with_steps(None, config)

            updated_state = await cl.make_async(graph.get_state)(config)
            prefix = "✅ " if approved else "❌ "
            await cl.Message(content=format_final_response(updated_state.values, prefix=prefix)).send()
        except Exception as exc:
            if action_id:
                _handled_actions.discard(action_id)
            logger.exception("Error handling approval decision for thread %s", thread_id)
            await cl.Message(
                content=(
                    "❌ **Failed to execute action decision.**\n\n"
                    f"Details: `{exc}`"
                )
            ).send()


@cl.action_callback("approve_action")
async def on_approve(action: cl.Action) -> None:
    """Handle operator approval."""
    await _handle_approval_decision(action, approved=True)


@cl.action_callback("reject_action")
async def on_reject(action: cl.Action) -> None:
    """Handle operator rejection."""
    await _handle_approval_decision(action, approved=False)
