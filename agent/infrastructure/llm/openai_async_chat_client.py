"""Asynchronous OpenAI chat-completions adapter."""

from __future__ import annotations

import asyncio
from typing import Any, AsyncIterator
import openai
from tenacity import (
    retry,
    stop_after_attempt,
    wait_exponential,
    retry_if_exception_type,
    RetryCallState,
)

from agent.application.ports.async_chat_client import AsyncChatClient
from agent.application.runtime.cancellation import CancellationToken


class AsyncOpenAIChatClient(AsyncChatClient):
    """Small wrapper around OpenAI async chat.completions API with resilient retries and cancellation support."""

    def __init__(self, async_client: Any, model: str, reasoning_effort: str | None = None):
        self._client = async_client
        self._model = model
        self._reasoning_effort = (reasoning_effort or "").strip() or None
        self._reasoning_effort_disabled = False
        self.on_retry = None  # Callback function: def on_retry(attempt: int, exception: Exception)

    @property
    def model(self) -> str:
        return self._model

    def set_model(self, model: str) -> None:
        clean = str(model or "").strip()
        if not clean:
            raise ValueError("Model name is required.")
        self._model = clean
        self._reasoning_effort_disabled = False

    def _before_sleep_log(self, retry_state: RetryCallState):
        if self.on_retry and retry_state.outcome and retry_state.outcome.failed:
            self.on_retry(retry_state.attempt_number, retry_state.outcome.exception())

    @property
    def _retry_decorator(self):
        return retry(
            retry=retry_if_exception_type((
                openai.RateLimitError,
                openai.APITimeoutError,
                openai.InternalServerError,
                openai.APIConnectionError,
            )),
            wait=wait_exponential(multiplier=1, min=2, max=10),
            stop=stop_after_attempt(5),
            before_sleep=self._before_sleep_log,
            reraise=True,
        )

    async def create(
        self,
        messages: list[dict],
        tools: list[dict] | None = None,
        cancellation_token: CancellationToken | None = None,
    ) -> Any:
        
        @self._retry_decorator
        async def _do_create():
            if cancellation_token and cancellation_token.is_cancelled:
                raise asyncio.CancelledError(cancellation_token.reason)
            
            kwargs = {
                "model": self._model,
                "messages": messages,
                "stream": False,
            }
            if tools:
                kwargs["tools"] = tools
                kwargs["tool_choice"] = "auto"
                
            # For non-streaming create, we await it.
            # To be fully responsive to cancellation mid-flight, we wrap it in a task.
            task = asyncio.create_task(self._create_with_optional_reasoning_effort(kwargs))
            
            if cancellation_token:
                cancel_task = asyncio.create_task(cancellation_token.wait())
                done, pending = await asyncio.wait(
                    [task, cancel_task],
                    return_when=asyncio.FIRST_COMPLETED
                )
                if cancel_task in done:
                    task.cancel()
                    raise asyncio.CancelledError(cancellation_token.reason)
                cancel_task.cancel()
                return task.result()
            else:
                return await task

        return await _do_create()

    async def stream(
        self,
        messages: list[dict],
        tools: list[dict] | None = None,
        cancellation_token: CancellationToken | None = None,
    ) -> AsyncIterator[Any]:
        
        # We need to retry the initial connection, but not the entire stream
        # once it starts yielding chunks.
        
        @self._retry_decorator
        async def _do_connect():
            if cancellation_token and cancellation_token.is_cancelled:
                raise asyncio.CancelledError(cancellation_token.reason)
                
            kwargs = {
                "model": self._model,
                "messages": messages,
                "stream": True,
                "stream_options": {"include_usage": True},
            }
            if tools:
                kwargs["tools"] = tools
                kwargs["tool_choice"] = "auto"
                
            task = asyncio.create_task(self._create_with_optional_reasoning_effort(kwargs))
            
            if cancellation_token:
                cancel_task = asyncio.create_task(cancellation_token.wait())
                done, pending = await asyncio.wait(
                    [task, cancel_task],
                    return_when=asyncio.FIRST_COMPLETED
                )
                if cancel_task in done:
                    task.cancel()
                    raise asyncio.CancelledError(cancellation_token.reason)
                cancel_task.cancel()
                return task.result()
            else:
                return await task

        stream_response = await _do_connect()
        
        # Now consume the stream chunks with cancellation checks
        try:
            async for chunk in stream_response:
                if cancellation_token and cancellation_token.is_cancelled:
                    raise asyncio.CancelledError(cancellation_token.reason)
                yield chunk
        finally:
            await self._close_stream(stream_response)

    async def _close_stream(self, stream_response: Any) -> None:
        close = getattr(stream_response, "aclose", None) or getattr(stream_response, "close", None)
        if not callable(close):
            return
        result = close()
        if asyncio.iscoroutine(result):
            await result

    async def _create_with_optional_reasoning_effort(self, kwargs: dict[str, Any]) -> Any:
        payload = dict(kwargs)
        if self._reasoning_effort and not self._reasoning_effort_disabled:
            payload["reasoning_effort"] = self._reasoning_effort
        try:
            return await self._client.chat.completions.create(**payload)
        except openai.APIStatusError as exc:
            if "reasoning_effort" not in payload or not self._should_retry_without_reasoning_effort(exc):
                raise
            fallback_payload = dict(payload)
            fallback_payload.pop("reasoning_effort", None)
            result = await self._client.chat.completions.create(**fallback_payload)
            self._reasoning_effort_disabled = True
            return result

    def _should_retry_without_reasoning_effort(self, exc: Exception) -> bool:
        text = str(exc).lower()
        return any(
            marker in text
            for marker in (
                "reasoning_effort",
                "request was blocked",
                "blocked",
                "unsupported",
                "unknown",
                "invalid",
                "unrecognized",
                "not support",
                "not supported",
                "extra_forbidden",
            )
        )
