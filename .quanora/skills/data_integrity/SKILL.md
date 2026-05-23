---
name: data_integrity
description: Strict data-integrity protocol for quantitative work. Forbids any fabrication of numerical data; requires source citation; defines the escalation playbook when a real data source fails. Activate explicitly with $data_integrity when starting any quant data workflow, or when you suspect the agent is about to invent numbers.
triggers:
  - $data_integrity
  - $no_fake_data
  - 数据完整性
  - 真实数据
  - 不要编造
  - 不要伪造
---

# Data Integrity Protocol (Quant Mode)

You are operating on **quantitative data**, where a wrong number is worse than no number. The system prompt already contains a `<data_integrity_mandate>` with the absolute rules. This skill **adds detailed playbooks** for the three situations you will hit most often.

## Rule recap (binding)

1. **Never fabricate data.** No `random.*`, `np.random.*`, `faker`, plausible-looking hand-typed numbers, or "let's assume" scripts to substitute for failed real sources.
2. **Always report data-source failures** with: which tool, why, what was needed, 2-3 remediation options. Then WAIT.
3. **Always cite provenance** when presenting numbers: tool/URL/file + time window + row count + filters.
4. **Label `[EXAMPLE — synthetic]` explicitly** when the user requested an illustrative number.

## Playbook A — User asks you to "pull/fetch/download data X from source Y"

Required sequence:

1. **Confirm the source.** Repeat back to the user what you understand the data source to be (URL, file path, API endpoint, ticker + date range, WQ Brain region+universe+delay, etc.). Get a yes before proceeding on anything ambiguous.
2. **Probe with a minimal call first.** Use the smallest viable request (e.g. `fetch_web_page` on the index page; `wq_list_data_fields(use_cache=True)`; `read_file` head 50 lines). Verify shape before bulk-pulling.
3. **On success:** report `{source, time window, row count, columns, sample row}` to the user BEFORE doing analysis. Use this template:
   ```
   ✅ Data acquired
     source       : <tool/URL/path>
     window       : <YYYY-MM-DD..YYYY-MM-DD>  (or N/A if cross-sectional)
     rows         : <n>
     columns      : <list>
     sample       : <first row, raw>
   ```
4. **On failure:** STOP. Do not proceed. Use Playbook C.

## Playbook B — Writing a data-loading or backtest script

Forbidden inside any script you write:

- `import random` / `from random import ...` for producing **data values**
- `numpy.random.normal/randn/randint/uniform/seed` etc. **to generate market/price/return/factor data**
- Hand-typed numeric lists/dicts that look like prices, returns, or factor values
- `pd.DataFrame({"close": [100, 101, 102, ...]})` style fabrication
- "Just for now, let's mock the API response with {...}"
- `# TODO: replace with real data` followed by fake data that *runs*

Allowed (but must be flagged):

- Random number generators for **bootstrap resampling, permutation tests, train/test shuffling, simulation of stochastic processes** — these are statistical methods, not data fabrication. Label clearly: `# statistical method, not data fabrication`.
- A small `assert` / smoke-test that needs 2-3 dummy rows — label `# fixture for test only`.

Before running any script that produces numerical output, **read back the data-loading section** and verify it touches a real source (file, network, DB, WQ Brain). If you cannot, refuse to run it.

## Playbook C — A real data source failed

The runtime fires a **⚠ DATA INTEGRITY WARNING** event when a real data-sourcing tool returns an error payload. When you see this (in tool history or via the CLI banner), your **only** acceptable next action is to stop and report. Use this template:

```
❌ Data unavailable — cannot proceed safely
  what was needed : <e.g. AAPL daily close, 2020-01-01..2024-12-31>
  what was tried  : <tool + args>
  why it failed   : <exact error message>
  what NOT to do  : I will not fabricate substitute data, because the
                    downstream sharpe/PnL/recommendation would be a silent lie.
  options:
    1. Retry — sometimes transient (especially WQ Brain / web fetches).
    2. Switch source — e.g. Yahoo → Stooq, Brain → local CSV.
    3. Narrow scope — fewer tickers / shorter window / cached subset.
    4. Provide credentials — if it's an auth failure (WQ_BRAIN_EMAIL, API key, etc.).
    5. Pause — you provide the file/CSV/sample, I resume.

  Which option would you like?
```

**Do not proceed past this message without an explicit user choice.** If the user says "just make something up so we can move on," explain that you cannot, and that the right next step is option 5 (they provide a sample) or option 2 (switch source). Offer to keep waiting; do not capitulate.

## Specific source playbooks

### Web pages / APIs (`search_web` + `fetch_web_page`)
- A `fetch_web_page` returning 0 chars, 4xx/5xx, or paywall HTML = failure. Report.
- If the URL needs auth, do not invent a workaround — report.

### Local files (`read_file`, `read_pdf`)
- "File not found" → ask the user for the correct path; list candidate paths via `list_files`.
- "Permission denied" → ask the user to fix permissions.
- "Corrupt PDF" → suggest `force_ocr=True` once, then escalate.

### WorldQuant Brain (`wq_*`)
- `wq_login` fails → check `WQ_BRAIN_EMAIL/PASSWORD` env, ask user. **Do not proceed to evaluation steps.**
- `wq_simulate_alpha` returns `tool_error` → report to user; do NOT continue evaluating sibling alphas as if they passed.
- `wq_evaluate_alpha` failure means the metrics are not real → never write that alpha to memory, never report a sharpe.
- Brain rate-limit → back off, report ETA; do NOT pretend a simulation completed.

### Shell downloads (`bash` with `curl`/`wget`)
- Non-zero exit code → report exit code + stderr.
- Zero-byte output file → report; do not pretend the data is there.
- HTML returned when expecting JSON/CSV → report (often a soft-fail login page).

## Self-check before presenting any numeric result

Ask yourself:
- [ ] Can I cite the source tool, the exact arguments, and the timestamp?
- [ ] Did the source tool return `ok` (not `error`) in this turn's tool history?
- [ ] Is the row count consistent with what the user asked for (no silent truncation)?
- [ ] Is any number in my output **not** traceable to a real tool result?

If any answer is "no", revise the output before sending. If you cannot fix it, escalate to Playbook C.
