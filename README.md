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
python eval.py run --tasks data/tasks/harness --output results/rules.jsonl
python eval.py report results/rules.jsonl
python -m pytest -q
```

PowerShell equivalent:

```powershell
py eval.py run --tasks data/tasks/harness --output results/rules.jsonl
py eval.py report results/rules.jsonl
py -m pytest -q
```

`eval.py` bootstraps `src/` for a checkout. After `py -m pip install -e .`, you can also use `shopping-agent` or `py -m shopping_agent`.

Defaults: three repetitions, seeded shuffled task order (`498`), twenty public tool calls,
60 seconds per worker trial. `--tasks`, `--catalog`, `--repetitions`, `--seed`,
`--max-calls`, and `--timeout` are configurable. Choose a new output path for each run;
existing records are never silently overwritten. The CLI runs the existing FastAPI
routes in-process inside isolated workers, so no storefront/server launch or model
key is required. Run from this checkout; the mock-store application is not bundled
in a standalone wheel.

The baseline receives supplied structured requests and ranking rules, not expected
answers. It does not evaluate language parsing, an LLM, or browser navigation.
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

See [parallel handoff](docs/parallel-handoff.md), [Update 2 draft](docs/project-update-2.md),
and [reviewed pilot records](docs/pilot/rules-2026-10-12-reviewed.jsonl).

A visually checked [Update 2 PDF draft](output/pdf/project-update-2-draft.pdf) is included.
It remains a draft until the team supplies all four names and actual contribution statements.
The original pilot records are retained alongside the rerun after the reviewer fixes.

## Update 3 evaluation

The default `data/tasks` directory now contains natural-language tasks; the rules agent
requires `--tasks data/tasks/harness`. The runner rejects incompatible input conditions
and missing Claude credentials before writing trial records. Use `--agent claude` for
the NL suite with `ANTHROPIC_API_KEY` configured in the environment.

Reports include per-task outcomes and observable failure categories. Add `--markdown`
to `report` for a table suitable for the project update. Reports reject mixed agent,
model, prompt, or input-surface conditions. Model tokens are summed only when all trials
have complete provider measurements; dollar cost remains unavailable unless supplied.

See [implementation and writing plan](docs/project-update-3-plan.md) and
[Billy's verified update text](docs/project-update-3-billy.md).
