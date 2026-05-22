"""Composition root for wiring concrete adapters to application services."""

from __future__ import annotations

from agent.application import ContextManager, ToolExecutor, JobService
from agent.application.services.skill_selector import SkillSelector
from agent.application.runtime.async_runtime_facade import AsyncRuntimeFacade
from agent.application.runtime.async_turn_runner import AsyncTurnRunner
from agent.application.runtime.message_stream_parser import MessageStreamParser
from agent.application.ports.async_session_store import AsyncSessionStore
from agent.domain import looks_like_tool_payload
from agent.infrastructure.config import Config
from agent.infrastructure.llm.openai_async_chat_client import AsyncOpenAIChatClient
from agent.infrastructure.persistence import JobStoreJsonl, TaskOutputStoreFile
from agent.infrastructure.persistence.async_jsonl_session_store import AsyncJsonlSessionStore
from agent.infrastructure.plans import PlanContextProvider
from agent.infrastructure.skills import SkillRepository
from agent.infrastructure.tools import DefaultToolRegistry
from agent.interfaces.cli import ChatCLI
from agent.prompts import SYSTEM_PROMPT


def build_basic_agent_dependencies(
    *,
    tools=None,
    debug: bool = False,
    session_dir: str | None = None,
    session_id: str | None = None,
    resume_latest: bool = False,
) -> dict[str, object]:
    model = Config.DEFAULT_MODEL
    async_client = Config.get_async_client()

    session: AsyncSessionStore = AsyncJsonlSessionStore(
        session_dir=session_dir,
        session_id=session_id,
        resume_latest=resume_latest,
        model=model,
        system_prompt=SYSTEM_PROMPT,
    )
    
    store_dir = session._session_dir or getattr(session, "_default_session_root", lambda: "sessions")()
    job_store = JobStoreJsonl(directory=store_dir)
    output_store = TaskOutputStoreFile(directory=store_dir)
    job_service = JobService(job_store=job_store, output_store=output_store)

    tool_registry = DefaultToolRegistry(schemas=tools)
    tool_executor = ToolExecutor(registry=tool_registry, job_service=job_service)
    
    async_chat_client = AsyncOpenAIChatClient(async_client=async_client, model=model)
    plan_context_provider = PlanContextProvider(char_limit=2200)
    skill_repository = SkillRepository()
    skill_selector = SkillSelector(max_active_skills=2)
    
    # Alignment B replaces ToolCallProcessor with AsyncToolCallProcessor
    from agent.application.runtime.async_tool_call_processor import AsyncToolCallProcessor
    async_tool_processor = AsyncToolCallProcessor(tool_executor=tool_executor, job_service=job_service)
    
    stream_parser = MessageStreamParser()
    
    turn_runner = AsyncTurnRunner(
        chat_client=async_chat_client,
        tool_processor=async_tool_processor,
        stream_parser=stream_parser,
        tool_schemas=tool_registry.schemas,
        context_manager=ContextManager(
            skill_repository=skill_repository,
            skill_selector=skill_selector,
            plan_context_provider=plan_context_provider,
        ),
        debug=debug,
    )
    
    runtime = AsyncRuntimeFacade(turn_runner=turn_runner, session_store=session)
    
    cli = ChatCLI(runtime=runtime, session=session, debug=debug)

    return {
        "chat_client": async_chat_client,
        "session": session,
        "tool_registry": tool_registry,
        "runtime": runtime,
        "cli": cli,
        "job_service": job_service,
        "skill_repository": skill_repository,
        "skill_selector": skill_selector,
        "plan_context_provider": plan_context_provider,
    }
