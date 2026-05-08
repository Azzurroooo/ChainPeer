"""Parses LLM responses, including streaming chunks and tool calls."""

from __future__ import annotations

from typing import Callable

from agent.domain import ParsedToolCall


class MessageStreamParser:
    """Parses OpenAI-compatible message streams and structures."""

    def parse_tool_calls_from_message(self, assistant_message) -> list[ParsedToolCall]:
        """Extract tool calls from a non-streaming assistant message."""
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

    def consume_stream_response(
        self, response, on_content: Callable[[str], None]
    ) -> tuple[str, list[ParsedToolCall]]:
        """Consume a streaming response, reassembling text and tool calls."""
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
