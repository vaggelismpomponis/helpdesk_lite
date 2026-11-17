"""HelpDesk Lite - Chainlit Application Entrypoint.

Starter skeleton adhering to architecture contracts (docs/ARCHITECTURE_CONTRACTS.md).
Coordinates with Interface role (docs/roles/interface.md).
"""

import chainlit as cl


@cl.on_chat_start
async def on_chat_start():
    """Initialize a new chat session and bind thread_id to session id."""
    # Contract: thread_id must match the Chainlit session identifier
    session_id = cl.context.session.id
    cl.user_session.set("thread_id", session_id)

    await cl.Message(
        content=(
            "**Welcome to HelpDesk Lite!** 🛠️\n\n"
            "I am your agentic IT support assistant. How can I help you today?\n\n"
            "*(Running in skeleton mode — awaiting graph orchestration integration)*"
        )
    ).send()


@cl.on_message
async def on_message(message: cl.Message):
    """Handle incoming user messages and echo back acknowledgment."""
    thread_id = cl.user_session.get("thread_id")
    response = (
        f"**Request received:** {message.content}\n\n"
        f"*(Session thread_id: `{thread_id}`)*\n\n"
        "Your request will be processed according to IT support policies."
    )
    await cl.Message(content=response).send()
