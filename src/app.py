"""HelpDesk Lite - Chainlit Application Entrypoint.

Adheres to architecture contracts (docs/ARCHITECTURE_CONTRACTS.md) and
coordinates with Interface & Workflow roles.
Wires the conversation thread directly into LangGraph compiled with PostgresSaver
for persistent checkpoints across container restarts.
"""

from __future__ import annotations

import chainlit as cl

from src.agent.graph import (
    build_graph,
    config_for,
    decide,
    get_production_graph,
    pending,
    reply,
    start,
)
from src.agent.models import ActionStatus

graph = get_production_graph()


@cl.on_chat_start
async def on_chat_start():
    """Initialize a chat session, bind thread_id to session id, and resume from checkpoint if restarting."""
    session_id = cl.context.session.id
    cl.user_session.set("thread_id", session_id)
    config = config_for(session_id)

    # Check for existing checkpoint (e.g. following container restart)
    try:
        state = graph.get_state(config)
    except Exception:
        state = None

    if state and state.values and state.values.get("messages"):
        last_msg = state.values["messages"][-1]
        await cl.Message(
            content=(
                f"🔄 **Session restored from database checkpoint!**\n\n"
                f"Resuming conversation for thread `{session_id}`:\n\n"
                f"{last_msg.get('content', '')}"
            )
        ).send()

        # Check if an approval or clarification is currently pending
        wait_reason = pending(graph, config)
        if wait_reason == "approval":
            proposal = state.values.get("action_proposal")
            actions = [
                cl.Action(name="approve_action", payload={"value": "approve"}, label="✅ Approve"),
                cl.Action(name="reject_action", payload={"value": "reject"}, label="❌ Reject"),
            ]
            await cl.Message(
                content=f"⚠️ **Pending Approval Required:** `{proposal.action_type.value}` — {proposal.rationale}",
                actions=actions,
            ).send()
    else:
        await cl.Message(
            content=(
                "**Welcome to HelpDesk Lite!** 🛠️\n\n"
                "I am your agentic IT support assistant. How can I help you today?"
            )
        ).send()


@cl.on_message
async def on_message(message: cl.Message):
    """Handle incoming user messages, route through LangGraph, and persist state in PostgreSQL."""
    thread_id = cl.user_session.get("thread_id")
    config = config_for(thread_id, user_email=cl.user_session.get("user_email"))

    wait_reason = pending(graph, config)
    if wait_reason == "clarification":
        result = reply(graph, config, message.content)
    else:
        result = start(graph, config, message.content)

    # Check if graph paused for clarification or approval
    wait_reason = pending(graph, config)
    if wait_reason == "clarification":
        question = result.get("clarification_question") or "Could you please clarify your request?"
        await cl.Message(content=question).send()
    elif wait_reason == "approval":
        proposal = result["action_proposal"]
        actions = [
            cl.Action(name="approve_action", payload={"value": "approve"}, label="✅ Approve"),
            cl.Action(name="reject_action", payload={"value": "reject"}, label="❌ Reject"),
        ]
        await cl.Message(
            content=(
                f"⚠️ **Approval Required for State-Changing Action**\n\n"
                f"- **Action:** `{proposal.action_type.value}`\n"
                f"- **Rationale:** {proposal.rationale}\n"
                f"- **Target Application:** `{proposal.parameters.get('application', 'N/A')}`\n"
                f"- **Employee:** `{proposal.parameters.get('employee', 'N/A')}`\n\n"
                "Please approve or reject this request:"
            ),
            actions=actions,
        ).send()
    else:
        final_text = result.get("final_response") or "Your request has been processed."
        await cl.Message(content=final_text).send()


@cl.action_callback("approve_action")
async def on_approve(action: cl.Action):
    """Handle operator approval."""
    thread_id = cl.user_session.get("thread_id")
    config = config_for(thread_id)
    result = decide(graph, config, approved=True)
    final_text = result.get("final_response") or "Action approved and executed."
    await cl.Message(content=f"✅ {final_text}").send()


@cl.action_callback("reject_action")
async def on_reject(action: cl.Action):
    """Handle operator rejection."""
    thread_id = cl.user_session.get("thread_id")
    config = config_for(thread_id)
    result = decide(graph, config, approved=False)
    final_text = result.get("final_response") or "Action was rejected."
    await cl.Message(content=f"❌ {final_text}").send()
