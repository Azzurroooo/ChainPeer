"""Composition root for wiring concrete adapters to application services."""

from __future__ import annotations

from agent.application import AgentRuntime, ContextManager, ToolExecutor
from agent.application.ports import SessionStore
from agent.domain import looks_like_tool_payload
from agent.infrastructure.config import Config
from agent.infrastructure.llm import OpenAIChatClient
from agent.infrastructure.persistence import JsonlSessionStore
from agent.infrastructure.tools import DefaultToolRegistry
from agent.interfaces.api import AgentAPIService
from agent.interfaces.cli import ChatCLI
from agent.prompts import SYSTEM_PROMPT


def build_basic_agent_dependencies(
    *,
    tools=None,
    debug: bool = False,
    session_dir: str | None = None,
    session_id: str | None = None,
    resume_latest: bool = False,
    resume_mode: str = "summary",
) -> dict[str, object]:
    model = Config.DEFAULT_MODEL
    client = Config.get_client()

    tool_registry = DefaultToolRegistry(schemas=tools)
    tool_executor = ToolExecutor(registry=tool_registry)
    chat_client = OpenAIChatClient(client=client, model=model)
    runtime = AgentRuntime(
        chat_client=chat_client,
        tool_executor=tool_executor,
        tool_schemas=tool_registry.schemas,
        context_manager=ContextManager(),
        debug=debug,
    )
    session: SessionStore = JsonlSessionStore(
        session_dir=session_dir,
        session_id=session_id,
        resume_latest=resume_latest,
        resume_mode=resume_mode,
        model=model,
        system_prompt=SYSTEM_PROMPT,
        looks_like_tool_payload=looks_like_tool_payload,
    )
    cli = ChatCLI(runtime=runtime, session=session, debug=debug)
    api_service = AgentAPIService(runtime=runtime, system_prompt=SYSTEM_PROMPT)

    return {
        "tool_registry": tool_registry,
        "tool_executor": tool_executor,
        "chat_client": chat_client,
        "runtime": runtime,
        "session": session,
        "cli": cli,
        "api_service": api_service,
    }
