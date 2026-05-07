# Dynamic Context Budget & Independent Compaction Plan

## 🎯 Objective
Migrate the context management system from a "Global Soft Limit" architecture to an **"Independent Priority-based Budgeting"** architecture. 
Currently, a massive tool output can falsely trigger conversation compaction because they share a global soft limit. We will solve this by giving System, Conversation, and Tool Outputs their own strict, independent token budgets.

## 📊 Architecture & Budget Allocation
The obsolete global `soft_limit_tokens` will be completely removed. We will hardcode an "Engineering Sweet Spot" of 32,000 tokens maximum, distributed strictly across three isolated domains.

Update `ContextBudget` (in `context_estimator.py`) with the following default values:
- **`hard_limit_tokens`**: `32000` (Absolute maximum total tokens sent to the model)
- **`system_budget_tokens`**: `2000` (Reserved for system prompts and tool schemas)
- **`conversation_budget_tokens`**: `6000` (Threshold to trigger conversation compaction. Only pure user/assistant messages count towards this!)
- **`tool_budget_tokens`**: `20000` (Threshold to trigger dynamic truncation for tool outputs)

*Note: The ContextEstimator uses `chars / 4` estimation. Keep using this for performance. Multiply token budgets by 4 when calculating character limits.*

## 🛠️ Implementation Steps (Actionable Guide for Trae)

### Step 1: Overhaul ContextEstimator & ContextBudget
**File:** `agent/application/services/context_estimator.py`
1. Remove `soft_limit_tokens` from the `ContextBudget` dataclass entirely.
2. Add `system_budget_tokens=2000`, `conversation_budget_tokens=6000`, and `tool_budget_tokens=20000`.
3. Remove `over_soft_limit` from the `ContextEstimate` dataclass.
4. Add independent tracking to `ContextEstimate`:
   - `conversation_tokens: int`
   - `tool_tokens: int`
   - `system_tokens: int`
5. Update the `estimate_messages` function:
   - Instead of summing all messages together blindly, iterate through the messages and categorize their token usage:
     - `role == "system"` -> `system_tokens`
     - `role == "tool"` or `message.get("tool_calls")` -> `tool_tokens`
     - purely `user`/`assistant` without `tool_calls` -> `conversation_tokens`
   - Return the detailed breakdown in `ContextEstimate`.

### Step 2: Refactor ToolContextPolicy for Dynamic Truncation
**File:** `agent/application/services/tool_context_policy.py`
1. The `render_tool_message` and `_summary_payload` methods currently use hardcoded character limits (e.g., `4000`, `800`, `240`). We must make these dynamic.
2. Add a new parameter `available_chars: int` to `render_tool_message`.
3. **Dynamic Truncation Strategy**:
   - If a Hot tool output exceeds `available_chars`, truncate it to `available_chars`.
   - **Crucial LLM Hint:** When forcefully truncating due to this limit, append: `\n\n...(Output truncated due to context limits. Please use search/grep tools to find specific content)...`
   - *Self-correction:* You may need to update `_apply_tool_context_policy` in `ContextManager` to calculate the total budget and pass the remaining `available_chars` down to each tool message rendering sequentially.

### Step 3: Update ContextManager Orchestration
**File:** `agent/application/services/context_manager.py`
1. **Fix Compaction Trigger:** In `build_messages`, change the trigger condition for `_compact_cold_conversation`.
   - Old: `if initial_estimate.over_soft_limit:`
   - New: `if initial_estimate.conversation_tokens >= budget.conversation_budget_tokens:`
   - This ensures conversation compaction is ONLY triggered when the chat itself is too long, entirely ignoring massive tool outputs.
2. **Pass Tool Budget:** Calculate `allowed_tool_chars = budget.tool_budget_tokens * 4`. When calling `_apply_tool_context_policy`, pass this limit down so the policy can dynamically truncate tool outputs if their sum exceeds the limit.
3. Update the `stats` and `decisions` dictionaries at the end of `build_messages` to reflect the new independent budget keys instead of `over_soft_limit`.

### Step 4: Fix Unit Tests
**File:** `test/test_context_manager_step.py` and other relevant tests.
1. Since `soft_limit_tokens` is removed, update test mocks that initialize `ContextBudget`.
2. Replace `budget = ContextBudget(soft_limit_tokens=10)` with `budget = ContextBudget(conversation_budget_tokens=10)` in your tests to ensure the step-based compaction still works perfectly.

## 🚀 Execution Rules for Trae
- **Understand the Shift:** The biggest change is that `ContextEstimator` must now classify tokens by message type, not just return a global sum.
- **Read First:** Inspect `context_estimator.py`, `tool_context_policy.py`, and `context_manager.py` thoroughly before editing.
- **Fail Fast:** Run `pytest test/test_context_manager_step.py` after your changes. If it breaks, fix it immediately.
- Begin execution immediately upon receiving this document.