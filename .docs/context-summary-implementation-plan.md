# Context Summary Implementation Plan

## Goal

Add a production-ready, low-risk context-summary mechanism for tool calls without slowing down the main streamed user response.

This plan is designed to be directly executable by Codex in this repository.

## Problem Statement

The current session resume strategy is not a true semantic summary. In `summary` mode, tool results are only truncated:

- long strings are cut off
- nested dict/list values are recursively truncated
- no semantic extraction is performed

This causes two problems:

1. resumed conversations may lose the most important facts from prior tool results
2. large tool outputs still consume too much context relative to their value

## Desired Outcome

Keep full raw tool results in persistence, but add a structured semantic summary for selected tool calls.

On resume:

- keep rebuilding assistant `tool_calls` messages as today
- prefer semantic summary as the `tool` message content
- fall back to current truncation behavior when no semantic summary exists

Do not block the main streamed user-visible answer on summary generation.

## Non-Goals

- do not build a full long-term memory system
- do not summarize every normal assistant/user message
- do not replace raw tool persistence
- do not require every tool call to have a semantic summary

## Recommended Strategy

Use an async or deferred post-processing summary step for tool calls.

Do **not** require the main streamed response to also produce a strict schema in the same output stream.

Rationale:

- keeps user-visible streaming fast
- avoids mixing natural-language response with machine-only schema output
- allows robust fallback if summary generation fails
- avoids forcing every model call into strict structured output mode

## High-Level Architecture

### Existing

- `messages.jsonl` stores conversation events
- `tool_calls.jsonl` stores full tool execution records
- resume reconstructs `chat_history` from both

### New

Add semantic tool summaries into `tool_calls.jsonl` records.

Suggested flow:

1. tool executes normally
2. full tool result is persisted as today
3. if tool call qualifies for summarization, enqueue summary generation
4. summary generation runs after the main answer path, or in a deferred/background-safe step
5. generated summary is written back into the corresponding tool call record
6. resume prefers that summary over truncated raw result

## Summary Storage Location

Store semantic summary on the tool-call record, not in `messages.jsonl`.

Reason:

- summary is derived from a tool execution result
- `messages` should remain the event log
- `tool_calls` should remain the execution record plus derived metadata
- resume logic already reconstructs `tool` content from tool-call records

## Proposed Data Model

Extend each `tool_calls.jsonl` record with optional fields:

```json
{
  "summary_for_resume": {
    "status": "success",
    "result_kind": "file_read",
    "summary": "Read chat_cli.py and found the streaming CLI renderer and main loop.",
    "key_points": [
      "Defines ChatCLI",
      "Contains _StreamingRenderer",
      "User input flows into runtime.process_user_turn"
    ],
    "next_step_hint": "Inspect _render_inline if optimizing rendering performance.",
    "details": {
      "file_path": "agent/interfaces/cli/chat_cli.py",
      "topics": ["cli", "streaming renderer"]
    }
  },
  "summary_source": "llm",
  "summary_version": "1",
  "summary_generated_at": "2026-03-31T10:00:00+00:00"
}
```

## Summary Schema

Use one common outer schema for all tools, with tool-specific data inside `details`.

Required fields:

- `status`
- `result_kind`
- `summary`
- `key_points`
- `next_step_hint`
- `details`

### Field Semantics

- `status`: `success` | `partial` | `error`
- `result_kind`: broad category such as `file_read`, `grep_result`, `bash_result`, `web_search`, `web_fetch`, `plan_update`
- `summary`: one short sentence with the main outcome
- `key_points`: 1-5 bullets worth of important facts
- `next_step_hint`: short agent-facing hint for future continuation
- `details`: tool-specific structured metadata

### Tool-Specific `details` Guidance

#### `read_file`

Use:

- `file_path`
- `line_range`
- `symbols`
- `topics`

#### `grep`

Use:

- `pattern`
- `path`
- `match_count`
- `top_matches`

#### `bash`

Use:

- `command`
- `exit_code`
- `stdout_highlights`
- `stderr_highlights`

#### `search_web`

Use:

- `query`
- `result_count`
- `top_sources`
- `top_urls`

#### `fetch_web_page`

Use:

- `url`
- `title`
- `sections`
- `main_topic`

## Trigger Policy

Do not summarize every tool call.

Summarize only when at least one of these is true:

- tool output length exceeds threshold
- tool type is high-value for later continuation
- tool result is likely to be revisited after restart
- user explicitly asks to compress/summarize context

### Recommended First-Pass Trigger Rules

Always eligible:

- `read_file`
- `grep`
- `search_web`
- `fetch_web_page`
- `bash`

Conditional:

- result payload length > 1500 chars
- stdout/stderr length > 1000 chars
- match count or result count > 10

Skip by default:

- tiny tool results
- obviously mechanical plan updates unless they contain meaningful state changes

## Execution Strategy

### Recommended

Generate summaries in a separate post-response step.

Implementation options, in order of recommendation:

1. deferred summary generation immediately after tool execution, but not on the user-visible streaming path
2. on-demand summary generation during persistence finalization
3. lazy summary generation only when resume needs it and none exists yet

### Not Recommended for First Version

Do not require the main streamed answer to return a strict summary schema inline.

Reasons:

- harms streaming simplicity
- increases latency on the critical path
- mixes user-facing and machine-facing outputs
- schema adherence in streamed natural-language output is less reliable

## Implementation Plan

### Step 1: Add Summary Fields to Persistence Model

Modify `agent/infrastructure/persistence/jsonl_session_store.py` so tool-call records can include:

- `summary_for_resume`
- `summary_source`
- `summary_version`
- `summary_generated_at`

Add a new persistence method, for example:

```python
def persist_tool_summary(self, call_id: str, summary: dict, source: str = "llm") -> None: ...
```

Implementation note:

- since records are stored as JSONL, updating one tool-call record may require either:
  - rewriting the file
  - or introducing an auxiliary summary sidecar file keyed by `call_id`

Recommended first version:

- add a sidecar file such as `tool_call_summaries.jsonl`
- merge it during resume using `call_id`

This avoids expensive in-place JSONL rewrites.

### Step 2: Add a Summary Generator Service

Create a new application service, for example:

- `agent/application/services/tool_summary_service.py`

Responsibilities:

- decide whether a tool result should be summarized
- prepare compact input for summarization
- call the summarizer client
- validate summary shape
- persist summary

### Step 3: Add a Summarizer Port

Create:

- `agent/application/ports/tool_summarizer.py`

Suggested protocol:

```python
class ToolSummarizer(Protocol):
    def summarize(self, tool_name: str, args: dict, result: str) -> dict: ...
```

### Step 4: Add an Infrastructure Implementation

Create:

- `agent/infrastructure/llm/tool_summary_client.py`

This adapter should:

- use a cheaper model if available
- send strict instructions for concise structured summary
- validate returned JSON
- return parsed dict or raise a controlled error

### Step 5: Add Prompt + Schema

Create a dedicated prompt builder for tool summaries.

Prompt requirements:

- explain that the summary is for future context restoration
- prefer concise factual output
- avoid repeating large raw outputs
- do not invent details not present in the tool result
- keep `key_points` short and high-signal

Schema requirements:

- one stable outer schema for all tools
- `details` is free-form object constrained by tool type guidance

### Step 6: Add Trigger Logic

Integrate summary trigger logic near the tool execution path after tool result persistence.

Possible location:

- after `session.persist_tool_call(...)` inside `agent/application/runtime.py`

But do not block user-visible streaming on summary generation.

Recommended first implementation:

- record tool call normally
- collect summary jobs in memory for the turn
- run summary generation only after the assistant final answer completes

### Step 7: Update Resume Reconstruction

Modify `JsonlSessionStore._build_tool_content()`:

Behavior priority:

1. `resume_mode == "full"` -> return full raw result
2. if `summary_for_resume` exists -> return serialized semantic summary or formatted compact text
3. else if `resume_mode == "summary"` -> current truncation behavior
4. `resume_mode == "none"` -> return empty string

Important:

- continue reconstructing assistant `tool_calls` messages exactly as today
- only replace the reconstructed `tool.content`

### Step 8: Add Manual Compression Command Later

Do not bundle this into the first patch unless easy.

Future direction:

- add a user-level command or tool to force summary generation / context compression

## Recommended Summary Serialization for Resume

Do not dump the entire schema JSON back to the model if avoidable.

Instead, turn it into compact text such as:

```text
Tool summary:
- status: success
- result_kind: file_read
- summary: Read chat_cli.py and identified the streaming renderer and main loop.
- key_points:
  - Defines ChatCLI
  - Contains _StreamingRenderer
  - Uses runtime.process_user_turn for turn execution
- next_step_hint: Inspect _render_inline for rendering optimization.
```

Reason:

- easier for the model to consume than raw JSON
- still deterministic enough for reconstruction

Raw schema should still remain in persistence.

## Failure Handling

If summary generation fails:

- do not fail the user request
- do not retry synchronously on the hot path
- log or persist a lightweight failure marker if useful
- fall back to current truncated resume behavior

## Testing Requirements

Add tests covering:

1. tool summary sidecar or summary persistence success path
2. resume prefers semantic summary when present
3. resume falls back to truncation when summary missing
4. summary generation failure does not break normal tool execution
5. assistant `tool_calls` reconstruction remains unchanged
6. large tool results no longer need full raw replay in default resume flow

## File Targets

Expected files to add or update:

- `agent/application/ports/tool_summarizer.py`
- `agent/application/services/tool_summary_service.py`
- `agent/infrastructure/llm/tool_summary_client.py`
- `agent/infrastructure/persistence/jsonl_session_store.py`
- `agent/application/runtime.py`
- `test/...` corresponding new tests

Optional:

- `agent/domain/...` for summary schema helpers / validation

## Acceptance Criteria

- full raw tool results are still preserved
- semantic summaries are persisted separately
- resumed `chat_history` uses semantic summary when available
- assistant `tool_calls` messages still reconstruct correctly
- main streamed user response does not wait on summary generation
- missing or invalid summary never breaks resume

## Recommended First Patch Scope

Keep the first implementation small:

1. add summary persistence structure
2. add lazy or deferred summary generation hook
3. add resume preference for semantic summary
4. add tests

Do not implement:

- long-term memory
- assistant message summarization
- complex per-tool custom schemas beyond `details`
- cross-session retrieval

## Instruction For Codex

Implement the above in minimal practical steps without breaking current session persistence semantics.

Constraints:

- preserve backward compatibility for old sessions without summaries
- keep raw tool results untouched
- make semantic summaries optional and failure-tolerant
- do not slow the main streamed assistant response path
- prefer high cohesion and low coupling
- add tests for success, fallback, and failure paths
