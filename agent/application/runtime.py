"""Core runtime orchestration for conversation and tool execution."""

from __future__ import annotations

from typing import Callable

from agent.application.ports import ChatClient, SessionStore
from agent.domain import ParsedToolCall, parse_tool_args, tool_error


class AgentRuntime:
    """Runs chat-completions loops and executes tool calls."""

    def __init__(
        self,
        chat_client: ChatClient,
        tool_executor,
        tool_schemas: list[dict],
        debug: bool = False,
    ):
        self._chat_client = chat_client
        self._tool_executor = tool_executor
        self._tool_schemas = tool_schemas
        self._debug = debug

    def run_query(self, system_prompt: str, query: str) -> str:
        messages = [{"role": "system", "content": system_prompt}, {"role": "user", "content": query}]
        while True:
            resp = self._chat_client.create(messages=messages, tools=self._tool_schemas, stream=False)
            msg = resp.choices[0].message
            messages.append(msg)

            if msg.content and not msg.tool_calls:
                return msg.content

            if not msg.tool_calls:
                return ""

            for call in self._parse_tool_calls_from_message(msg):
                tool_result = self._execute_parsed_tool_call(call)
                messages.append({"role": "tool", "tool_call_id": call.call_id, "content": tool_result})

    def process_user_turn(
        self,
        chat_history: list[dict],
        session: SessionStore,
        on_content: Callable[[str], None],
        on_debug: Callable[[str], None] | None = None,
    ) -> None:
        while True:
            if self._debug:
                response = self._chat_client.create(messages=chat_history, tools=self._tool_schemas, stream=False)
                assistant_msg = response.choices[0].message
                if on_debug:
                    on_debug(str(assistant_msg))
                self._persist_assistant_content(chat_history, session, assistant_msg.content or "")
                tool_calls = self._parse_tool_calls_from_message(assistant_msg)
            else:
                response = self._chat_client.create(messages=chat_history, tools=self._tool_schemas, stream=True)
                content_text, tool_calls = self._consume_stream_response(response, on_content)
                self._persist_assistant_content(chat_history, session, content_text)

            if not tool_calls:
                break
            self._persist_assistant_tool_calls(chat_history, session, tool_calls)
            self._execute_tool_calls(chat_history, session, tool_calls, on_debug=on_debug)

    def _persist_assistant_content(
        self,
        chat_history: list[dict],
        session: SessionStore,
        content_text: str,
    ) -> None:
        if not content_text:
            return
        chat_history.append({"role": "assistant", "content": content_text})
        session.persist_message("assistant", content_text)

    def _persist_assistant_tool_calls(
        self,
        chat_history: list[dict],
        session: SessionStore,
        tool_calls: list[ParsedToolCall],
    ) -> None:
        assistant_tool_msg = {
            "role": "assistant",
            "tool_calls": [
                {
                    "id": item.call_id,
                    "type": "function",
                    "function": {"name": item.name, "arguments": item.raw_args},
                }
                for item in tool_calls
            ],
        }
        chat_history.append(assistant_tool_msg)
        session.persist_message(
            "assistant",
            "",
            meta={"tool_calls": [{"id": item.call_id, "name": item.name} for item in tool_calls]},
        )

    def _execute_tool_calls(
        self,
        chat_history: list[dict],
        session: SessionStore,
        tool_calls: list[ParsedToolCall],
        on_debug: Callable[[str], None] | None = None,
    ) -> None:
        for call in tool_calls:
            if on_debug:
                on_debug(f"Tool Call: {call.name}({call.raw_args})")

            parsed_args, parse_error = parse_tool_args(call.raw_args)
            ts_start = session.now_iso()
            if parse_error:
                tool_result = tool_error(
                    call.name,
                    f"Invalid tool arguments JSON: {parse_error}",
                    "ToolArgsJSONError",
                    meta={"raw_args": call.raw_args[:2000]},
                )
            else:
                tool_result = self._tool_executor.execute(call.name, parsed_args, raw_args=call.raw_args)
            ts_end = session.now_iso()

            session.persist_tool_call(
                call.call_id,
                call.name,
                parsed_args,
                call.raw_args,
                ts_start,
                ts_end,
                tool_result,
            )
            chat_history.append({"role": "tool", "tool_call_id": call.call_id, "content": tool_result})
            session.persist_message("tool", "", tool_call_id=call.call_id, tool_name=call.name)
            if on_debug:
                on_debug(f"Tool Result: {tool_result}")

    def _execute_parsed_tool_call(self, call: ParsedToolCall) -> str:
        parsed_args, parse_error = parse_tool_args(call.raw_args)
        if parse_error:
            return tool_error(
                call.name,
                f"Invalid tool arguments JSON: {parse_error}",
                "ToolArgsJSONError",
                meta={"raw_args": call.raw_args[:2000]},
            )
        return self._tool_executor.execute(call.name, parsed_args, raw_args=call.raw_args)

    def _parse_tool_calls_from_message(self, assistant_message) -> list[ParsedToolCall]:
        calls: list[ParsedToolCall] = []
        if not assistant_message.tool_calls:
            return calls
        for item in assistant_message.tool_calls:
            calls.append(
                ParsedToolCall(
                    call_id=item.id,
                    name=item.function.name,
                    raw_args=item.function.arguments or "",
                )
            )
        return calls

    def _consume_stream_response(self, response, on_content: Callable[[str], None]) -> tuple[str, list[ParsedToolCall]]:
        text_parts: list[str] = []
        merged_tool_calls: list[dict] = []
        for chunk in response:
            delta = chunk.choices[0].delta
            if delta.content:
                on_content(delta.content)
                text_parts.append(delta.content)
            if delta.tool_calls:
                for item in delta.tool_calls:
                    index = item.index
                    while len(merged_tool_calls) <= index:
                        merged_tool_calls.append({"id": "", "name": "", "arguments": ""})
                    if item.id:
                        merged_tool_calls[index]["id"] = item.id
                    if item.function:
                        if item.function.name:
                            merged_tool_calls[index]["name"] = item.function.name
                        if item.function.arguments:
                            merged_tool_calls[index]["arguments"] += item.function.arguments
        calls = [
            ParsedToolCall(call_id=item["id"], name=item["name"], raw_args=item["arguments"])
            for item in merged_tool_calls
            if item["id"] and item["name"]
        ]
        return "".join(text_parts), calls
