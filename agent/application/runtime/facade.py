"""Core runtime orchestration for conversation and tool execution."""

from __future__ import annotations

from typing import Callable

from agent.application.ports import ChatClient, SessionStore
from agent.application.services import ContextManager
from agent.domain.events import RuntimeEvent

from .message_stream_parser import MessageStreamParser
from .tool_call_processor import ToolCallProcessor
from .turn_runner import TurnRunner


class AgentRuntime:
    """Facade for the runtime execution engine."""

    def __init__(
        self,
        chat_client: ChatClient,
        tool_executor,
        tool_schemas: list[dict],
        context_manager: ContextManager | None = None,
        debug: bool = False,
    ):
        self._chat_client = chat_client
        self._tool_executor = tool_executor
        self._tool_schemas = tool_schemas
        self._context_manager = context_manager or ContextManager()
        self._debug = debug
        
        # Initialize the split components
        self._stream_parser = MessageStreamParser()
        self._tool_processor = ToolCallProcessor(self._tool_executor)
        self._turn_runner = TurnRunner(
            chat_client=self._chat_client,
            tool_processor=self._tool_processor,
            stream_parser=self._stream_parser,
            tool_schemas=self._tool_schemas,
            context_manager=self._context_manager,
            debug=self._debug,
        )

    def run_query(self, system_prompt: str, query: str) -> str:
        """Delegates to TurnRunner to run a stateless query."""
        return self._turn_runner.run_query(system_prompt, query)

    def process_user_turn(
        self,
        session: SessionStore,
        on_content: Callable[[str], None],
        on_debug: Callable[[str], None] | None = None,
        on_assistant_message_complete: Callable[[], None] | None = None,
        on_event: Callable[[RuntimeEvent], None] | None = None,
    ) -> None:
        """Delegates to TurnRunner to process a conversation turn."""
        self._turn_runner.process_user_turn(
            session=session,
            on_content=on_content,
            on_debug=on_debug,
            on_assistant_message_complete=on_assistant_message_complete,
            on_event=on_event,
        )
