"""Coordinates the turn lifecycle, linking LLM, parser, and tools."""

from __future__ import annotations

from typing import Callable
import openai
from tenacity import RetryError

from agent.application.ports import ChatClient, SessionStore
from agent.application.services import ContextManager
from agent.domain import ParsedToolCall
from agent.domain.events import RuntimeEvent

from .message_stream_parser import MessageStreamParser
from .tool_call_processor import ToolCallProcessor


class TurnRunner:
    """Manages the execution of a single conversational turn."""

    def __init__(
        self,
        chat_client: ChatClient,
        tool_processor: ToolCallProcessor,
        stream_parser: MessageStreamParser,
        tool_schemas: list[dict],
        context_manager: ContextManager,
        debug: bool = False,
    ):
        self._chat_client = chat_client
        self._tool_processor = tool_processor
        self._stream_parser = stream_parser
        self._tool_schemas = tool_schemas
        self._context_manager = context_manager
        self._debug = debug

    def run_query(self, system_prompt: str, query: str) -> str:
        """Run a single stateless query loop."""
        messages = [{"role": "system", "content": system_prompt}, {"role": "user", "content": query}]
        while True:
            resp = self._chat_client.create(messages=messages, tools=self._tool_schemas, stream=False)
            msg = resp.choices[0].message
            messages.append(msg)

            if msg.content and not msg.tool_calls:
                return msg.content

            if not msg.tool_calls:
                return ""

            for call in self._stream_parser.parse_tool_calls_from_message(msg):
                tool_result = self._tool_processor.execute_parsed_tool_call(call)
                messages.append({"role": "tool", "tool_call_id": call.call_id, "content": tool_result})

    def process_user_turn(
        self,
        session: SessionStore,
        on_content: Callable[[str], None],
        on_debug: Callable[[str], None] | None = None,
        on_assistant_message_complete: Callable[[], None] | None = None,
        on_event: Callable[[RuntimeEvent], None] | None = None,
    ) -> None:
        """Run the main conversation loop for a user turn."""
        while True:
            context = self._context_manager.build_messages(session=session)
            if self._debug and on_debug:
                on_debug(
                    f"Context Estimate: tokens={context.stats.get('estimated_input_tokens')} "
                    f"chars={context.stats.get('estimated_chars')} "
                    f"conversation_over={context.decisions.get('over_conversation_budget')} "
                    f"tool_over={context.decisions.get('over_tool_budget')} "
                    f"hard={context.decisions.get('over_hard_limit')}"
                )
                
            try:
                if self._debug:
                    response = self._chat_client.create(messages=context.messages, tools=self._tool_schemas, stream=False)
                    assistant_msg = response.choices[0].message
                    if on_debug:
                        on_debug(str(assistant_msg))
                    self._persist_assistant_content(session, assistant_msg.content or "")
                    self._notify_assistant_message_complete(assistant_msg.content or "", on_assistant_message_complete)
                    tool_calls = self._stream_parser.parse_tool_calls_from_message(assistant_msg)
                else:
                    response = self._chat_client.create(messages=context.messages, tools=self._tool_schemas, stream=True)
                    content_text, tool_calls = self._stream_parser.consume_stream_response(response, on_content)
                    self._persist_assistant_content(session, content_text)
                    self._notify_assistant_message_complete(content_text, on_assistant_message_complete)
            except openai.BadRequestError as e:
                if "context_length_exceeded" in str(e) or "maximum context length" in str(e).lower():
                    if on_debug:
                        on_debug("⚠️ ContextLengthExceeded caught! Falling back to Context Manager Rescue...")
                    old_hard_limit = self._context_manager._estimator.budget.hard_limit_tokens
                    self._context_manager._estimator.budget.hard_limit_tokens = int(old_hard_limit * 0.8)
                    continue
                raise
            except RetryError as e:
                error_msg = f"\n\n[APIUnavailableError: The AI provider is currently unreachable after multiple retries. Please check your network or try again later. Error: {e.last_attempt.exception()}]"
                on_content(error_msg)
                break

            if not tool_calls:
                break
            self._persist_assistant_tool_calls(session, tool_calls)
            self._tool_processor.execute_tool_calls(session, tool_calls, on_debug=on_debug, on_event=on_event)

    def _persist_assistant_content(self, session: SessionStore, content_text: str) -> None:
        if not content_text or not content_text.strip():
            return
        session.persist_message("assistant", content_text)

    def _notify_assistant_message_complete(
        self,
        content_text: str,
        on_assistant_message_complete: Callable[[], None] | None,
    ) -> None:
        if not on_assistant_message_complete or not content_text or not content_text.strip():
            return
        on_assistant_message_complete()

    def _persist_assistant_tool_calls(self, session: SessionStore, tool_calls: list[ParsedToolCall]) -> None:
        session.persist_message(
            "assistant",
            "",
            meta={"tool_calls": [{"id": item.call_id, "name": item.name} for item in tool_calls]},
        )
