"""OpenAI chat-completions adapter."""

from __future__ import annotations

from typing import Any
import openai
from tenacity import (
    retry,
    stop_after_attempt,
    wait_exponential,
    retry_if_exception_type,
    RetryCallState,
)

class OpenAIChatClient:
    """Small wrapper around OpenAI chat.completions API with resilient retries."""

    def __init__(self, client: Any, model: str):
        self._client = client
        self._model = model
        self.on_retry = None  # Callback function: def on_retry(attempt: int, exception: Exception)

    def _before_sleep_log(self, retry_state: RetryCallState):
        if self.on_retry and retry_state.outcome and retry_state.outcome.failed:
            self.on_retry(retry_state.attempt_number, retry_state.outcome.exception())

    @retry(
        retry=retry_if_exception_type((
            openai.RateLimitError,
            openai.APITimeoutError,
            openai.InternalServerError,
            openai.APIConnectionError,
        )),
        wait=wait_exponential(multiplier=1, min=2, max=10),
        stop=stop_after_attempt(5),
        reraise=True,
    )
    def _create_with_retry(self, messages: list[dict], tools: list[dict], stream: bool):
        # We need to inject the before_sleep hook dynamically if it's set
        return self._client.chat.completions.create(
            model=self._model,
            messages=messages,
            tools=tools,
            tool_choice="auto",
            stream=stream,
        )
        
    def create(self, messages: list[dict], tools: list[dict], stream: bool):
        # Apply the before_sleep hook dynamically to the wrapped function
        self._create_with_retry.retry.before_sleep = self._before_sleep_log
        return self._create_with_retry(messages, tools, stream)
