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

The scored suite (`data/tasks/*.json`, suite-v3, 10 easy / 10 medium / 10 hard) is
**Surface B**: agents receive natural-language text only. Constraints, ranking rules,
planted clarification strings, and expected outcomes stay evaluator-held. The rules
baseline is for **Surface A** harness fixtures under `data/tasks/harness/` (structured
request + ranking rule); run it with `--tasks data/tasks/harness`. Surface A 100%
success validates plumbing, not shopping competence. See
[`docs/benchmark/task-design.md`](docs/benchmark/task-design.md) and
[`docs/benchmark/task-suite.md`](docs/benchmark/task-suite.md).
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
