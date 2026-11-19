# Shopping agent

## Run the mock store on Windows

Requirements: Python 3.12 or newer and Node.js 20 or newer. Install the Python packages once from PowerShell:

```powershell
py -m pip install -r requirements.txt
```

Then start both the API and storefront with one command:

```powershell
py run.py
```

The launcher installs the frontend's npm packages on first run, starts both local servers, and opens the storefront in your default browser. Press `Ctrl+C` in the terminal to stop them. You do not need to install `uv`, run the servers separately, or pass host/port flags.

For tests, install the development dependencies once with `py -m pip install -r requirements-dev.txt`, then run `py -m pytest`.

The mock store is synthetic and local-only. It does not make purchases or handle payments. See [mock-store/README.md](mock-store/README.md) for task examples and store behavior.

## Deterministic evaluation pilot

From the repository root, install `requirements-dev.txt`, then run:

```sh
PYTHONPATH=src python -m shopping_agent.cli run --output results/rules.jsonl
PYTHONPATH=src python -m shopping_agent.cli report results/rules.jsonl
python -m pytest -q
```

PowerShell equivalent:

```powershell
$env:PYTHONPATH = "src"
py -m shopping_agent.cli run --output results/rules.jsonl
py -m shopping_agent.cli report results/rules.jsonl
py -m pytest -q
```

Defaults: three repetitions, seeded shuffled task order (`498`), twenty public tool calls,
60 seconds per worker trial. `--tasks`, `--catalog`, `--repetitions`, `--seed`,
`--max-calls`, and `--timeout` are configurable. Choose a new output path for each run;
existing records are never silently overwritten. The CLI runs the existing FastAPI
routes in-process inside isolated workers, so no storefront/server launch or model
key is required. Run from this checkout; the mock-store application is not bundled
in a standalone wheel.

The baseline receives supplied structured requests and ranking rules, not expected
answers. The live Claude entry point first uses a schema-constrained Claude
interpretation call to convert free-form language into a validated
`ShoppingRequest`, then runs the shopping/tool-use loop. Parser accuracy is not
measured by the current structured-request pilot. The pilot does not evaluate
browser navigation.
The clarification task supplies `request.clarification_needed`, including the exact
question. Its successful trials measure routing a supplied clarification instruction,
not discovering ambiguity. Expected outcome objects are hidden, but this parsed input
is assistance. Before LLM comparisons, either remove that directive from model inputs
and evaluate ambiguity detection separately, or give all conditions identical parsed
assistance and explicitly exclude ambiguity discovery from the comparison.
Scoring uses final live store state and cart contents. Failures remain in the success
rate denominator. Constraint satisfaction is averaged over trials expecting a product
with at least one hard constraint; empty no-match/clarification selections are not
awarded fictitious constraint satisfaction. p95 uses nearest rank. Duration measures
agent execution, excluding worker startup and scoring; a separate process deadline
bounds worker setup/execution and a 60-second startup allowance bounds initialization.
A forcibly stopped worker has no final-state snapshot and is always unsuccessful.
Human ratings, claim-audit rates, and model measurements remain null when unavailable.

### Metrics vocabulary

The terminal summary, `report` JSON, markdown report, condition comparison, and
`audit` all read one module, `src/shopping_agent/eval/metrics.py`, so an outcome
never appears under two names:

- Failure categories come from `FailureCategory`: `unrecoverable_failure`,
  `timeout`, `max_tool_calls_exceeded`, `clarification_mismatch`,
  `unexpected_clarification`, `incorrect_abstention`, `abstention_mismatch`,
  `hard_constraint_violation`, `selection_or_cart_mismatch`. Each failed trial
  gets exactly one, and the terminal `FAIL` line and `common_failure_issue` use
  the same label as the JSON summary.
- `unsupported_claim_rate` is computed only from the claims the agent declares
  in its final decision, checked against the final catalog state. It is null when
  the run declares nothing checkable.
- `prose_claim_contradiction_rate` is a separate advisory reading of the
  explanation text. Windowed matching can attach a nearby figure to the wrong
  product, so it is reported next to the structured rate and never replaces it.
- `tool_calls_by_purpose` splits recorded tool calls into `agent` exploration and
  `verification` gate work (the final listing refresh, the empty-cart check, and
  the purchase it verifies). Every call is charged once against the trial budget.
  Records written before calls were labelled report their calls as `unspecified`
  rather than guessing a purpose.

Trial diagnostics record how the deterministic gate reached its verdict:
`gate_input_source` (`live_refresh` when the gate re-read the live listing,
`observation_cache` when an abstention was judged against observations only,
`none` when nothing was checked), `corrected_constraints` (values the gate
coerced to the listed type, with the raw declaration kept in
`raw_constraints`), and `false_abstention_candidate` (whether an observed listing
already satisfied the request when the agent abstained). Each is evidence for
triage; none of them changes scoring.

On a catalog where several stores list the same product ID, a bare `product_id`
identifies more than one listing. The gate refuses such a pick instead of silently
taking whichever variant it saw last: it asks for the `listing_id`, records the
candidates under `ambiguous_product_id`, and leaves both variants visible to the
next turn. The same reasoning keys the run's observation cache by listing identity,
so one store's price cannot be verified against another store's row.

### Baseline comparison on the natural-language suite

The ten natural-language tasks can be run under four conditions with three
seeds each (30 trials per condition). `single_prompt`, `react`, `no_verifier`,
and `full` are deterministic offline surrogates; `claude` is the live
provider-backed agent and needs `ANTHROPIC_API_KEY`. `--seeds` accepts a
comma-separated list and overrides `--seed`/`--repetitions` for a run.

```sh
PYTHONPATH=src python -m shopping_agent.cli compare \
  --output-dir results/comparison-update4 --mode flat --seeds 1,2,3 \
  --conditions single_prompt,react,no_verifier,full
```

The command writes per-condition JSONL, `comparison.json`, `comparison.csv`,
and `table1.md`. The executed comparison and its caveats are in
[NL suite comparison](docs/pilot/nl-comparison-update-4.md). Conditions are
never pooled in a single report: each has its own model/prompt identity.

See [parallel handoff](docs/parallel-handoff.md), [Update 2 draft](docs/project-update-2.md),
and [reviewed pilot records](docs/pilot/rules-2026-10-12-reviewed.jsonl).

A visually checked [Update 2 PDF draft](output/pdf/project-update-2-draft.pdf) is included.
It remains a draft until the team supplies all four names and actual contribution statements.
The original pilot records are retained alongside the rerun after the reviewer fixes.
