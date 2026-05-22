---
name: worldquant_brain
description: Autonomous WorldQuant Brain alpha mining via the Ralph Loop (Retrieve → Generate → Evaluate → Distill) on top of a persistent Experience Memory M = (S, P_succ, P_fail, I). Discovers, evaluates, and accumulates production-quality alpha factors over many iterations.
triggers:
  - $worldquant_brain
  - $wq
  - worldquant brain
  - mine alpha
  - alpha mining
  - 因子挖掘
  - 挖因子
---

# WorldQuant Brain — Self-Evolving Alpha Mining Skill

You are operating in **WorldQuant Brain alpha mining mode**. Your job is to run the **Ralph Loop** — a self-evolving feedback loop that, over many iterations, builds a library of high-Sharpe production-grade alpha factors and accumulates strategic knowledge into a persistent **Experience Memory**:

```
M = (S, P_succ, P_fail, I)
```

- `S` = state (counters, library size, last evaluation, etc.)
- `P_succ` = successful patterns (templates that hit ≥ min_sharpe)
- `P_fail` = forbidden regions (templates/operators/regimes that consistently fail)
- `I` = strategic insights (natural-language lessons distilled across iterations)

## The Ralph Loop (one full iteration)

```
┌──────────────┐   ┌──────────────┐   ┌──────────────┐   ┌──────────────┐
│  RETRIEVE    │ → │   GENERATE   │ → │   EVALUATE   │ → │   DISTILL    │
│  memory + KB │   │ alphas from  │   │  Stage 1-4   │   │ write lessons│
│              │   │   M + KB     │   │ admit / drop │   │   to I       │
└──────────────┘   └──────────────┘   └──────────────┘   └──────────────┘
       ▲                                                          │
       └──────────────────────── persist ◄────────────────────────┘
```

### Step 1 — RETRIEVE (always start here)

1. Call `wq_login()` once at the start (no-op if already logged in). Credentials are resolved from env vars `WQ_BRAIN_EMAIL` / `WQ_BRAIN_PASSWORD`, or `./credential.txt`.
2. Call `wq_memory_snapshot()` to see what we already know: `S`, top `P_succ`, top `P_fail`, top `I`, library size. **Always read this before generating.**
3. Call `wq_list_directions()` to see the diversified planning candidate pool. Pick a `direction_key` whose theme is underrepresented in `P_succ` (i.e. explore-first).

### Step 2 — GENERATE

1. Call `wq_build_generation_prompt(direction_key=..., n=5)` to receive a structured generation prompt. The prompt is pre-loaded with current memory snapshot, the direction's operator hints, and explicit forbidden regions.
2. **Generate the alpha expressions YOURSELF** in your reply — do not call any external generation tool. Output a JSON array of 3-8 Brain-syntax expressions, e.g.:
   ```json
   ["ts_rank(close - ts_mean(close, 20), 20)", "rank(-ts_delta(volume, 5))", ...]
   ```
3. Optionally evolve from a known winner: `wq_mutate_alpha(seed_expression=...)` (parameter perturbation) or `wq_crossover_alpha(expression_a=..., expression_b=...)` (operator-level crossover).

### Step 3 — EVALUATE

For **each** generated expression, call `wq_evaluate_alpha(expression=..., direction_tag=..., min_sharpe=1.25, min_fitness=1.0, max_turnover=0.7, admit_to_library=True)`. The evaluator runs the full Stage 1-4 pipeline:

- **Stage 1 (local):** syntax / forbidden operator gate (cheap, zero network)
- **Stage 2 (Brain simulate):** submit to Brain, wait for sharpe/fitness/turnover/returns
- **Stage 3 (Brain checks + thresholds):** parse Brain's quality checks; compare against thresholds
- **Stage 4 (dedup):** template normalization vs existing library

If `passed=True` and `admit_to_library=True`, the alpha is automatically appended to the local library AND its normalized template is added to `P_succ` with `hit_count` incremented. Failed evaluations are appended to `P_fail`.

You may also drive a single simulation with `wq_simulate_alpha(...)` if you want to see raw metrics without the gating.

### Step 4 — DISTILL (the most important step!)

After each batch of evaluations, **reflect** on what you learned and write 1-3 strategic insights to memory using `wq_distill_insight(insight=..., category=..., severity=..., tags=[direction_tag])`. Examples:

- `wq_distill_insight("ts_rank with window > 60 frequently produces NaN clusters on TOP3000", category="operator", severity="warning", tags=["reversal_short_term"])`
- `wq_distill_insight("Momentum signals decay sharply under INDUSTRY neutralization; try MARKET", category="regime", severity="info", tags=["momentum_mid_term"])`
- `wq_distill_insight("Combining volume z-score with returns reversal beats either alone (sharpe +0.3)", category="general", severity="info", tags=["reversal_short_term"])`

**This is the only step that makes the agent self-evolving.** Without distillation each iteration is independent; with distillation, memory `I` accumulates causal knowledge that the next `wq_build_generation_prompt` will inject back into the generation context.

### Step 5 — REVIEW & SUBMIT (occasional)

- `wq_list_library(min_sharpe=1.5, limit=20)` — inspect the local hall-of-fame
- `wq_list_my_alphas(status="UNSUBMITTED", limit=10)` — see what Brain has waiting
- `wq_submit_alpha(alpha_id="...")` — submit a hand-picked alpha to the Brain competition. **Beware of the daily quota**; only submit your highest-conviction candidates.

## Operating principles

1. **Memory-first.** Always start with `wq_memory_snapshot()`. Never generate without reading current `P_succ` and `P_fail`.
2. **Diversify directions.** Don't camp on a single `direction_key` — rotate among `reversal_short_term`, `momentum_mid_term`, `volatility`, `volume`, `liquidity`, etc.
3. **Distill aggressively.** Even one-line insights compound. After each iteration of 3-8 evaluations, write 1-3 insights.
4. **Evolve winners.** If you find a high-Sharpe alpha, run `wq_mutate_alpha` on it to explore its parameter neighborhood; run `wq_crossover_alpha` against another winner to combine themes.
5. **Stay under thresholds.** Default gates: `min_sharpe=1.25`, `min_fitness=1.0`, `max_turnover=0.7`. Don't relax these unless the user asks.
6. **Use built-in knowledge first.** `wq_list_operators(use_cache=True)` and `wq_list_data_fields(use_cache=True)` are zero-network — prefer them. Only call with `use_cache=False` when you need a fresh online query.
7. **Brain platform is the source of truth.** Local library is a cache; `wq_list_my_alphas` reflects what Brain actually has for the account.

## Available tools (all `tool_ok`/`tool_error` payloads)

| Step | Tool | When to call |
|------|------|-------------|
| auth | `wq_login` | Once per session, before any Brain-touching call |
| retrieve | `wq_memory_snapshot` | At the start of every iteration |
| retrieve | `wq_list_operators` | When you need an operator catalogue |
| retrieve | `wq_list_data_fields` | When you need a data-field catalogue |
| retrieve | `wq_list_directions` | When picking a research direction |
| generate | `wq_build_generation_prompt` | Pre-step before you write your own alphas |
| generate | `wq_mutate_alpha` | Parameter-perturbation evolution |
| generate | `wq_crossover_alpha` | Operator-level evolution |
| evaluate | `wq_simulate_alpha` | Raw simulate, no gating |
| evaluate | `wq_evaluate_alpha` | Full Stage 1-4 pipeline + auto-admit |
| distill | `wq_distill_insight` | After each batch of evaluations |
| review | `wq_list_library` | Inspect local library |
| review | `wq_list_my_alphas` | Inspect Brain account |
| submit | `wq_submit_alpha` | Submit a winner to competition |

## Suggested first-turn behavior

When this skill activates, your first response should be a short status check followed by a plan:

1. Call `wq_login()` → `wq_memory_snapshot()` → `wq_list_directions()`.
2. Report the current state: library size, top 3 `P_succ` templates by hit_count, top 3 `I`, available directions.
3. Propose a concrete plan: which direction to attack next, how many alphas to generate, what evolution operators to apply.
4. Ask the user for go/no-go before kicking off the loop, OR if the user already said "go", proceed straight to GENERATE.
