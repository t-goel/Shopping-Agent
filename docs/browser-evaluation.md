# Browser benchmark

The browser transport keeps the shopping tool interface (`list_stores`, `search`,
`get_listing`, `inspect_cart`, `add_to_cart`) and Claude decision loop. Playwright
performs UI actions and returns compact typed observations read from rendered
listing facts, attributes, reviews, store cards, and the bag. This is a DOM browser
condition with compound shopping tools; it is not a visual-only or individual-click
agent. The adapter supports this repository's storefront, not arbitrary retailers.

## Install and build

From the repository root, with Python 3.12+ and Node 20+:

```sh
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements-browser.txt -r requirements-dev.txt
python -m playwright install chromium
npm --prefix mock-store/storefront ci
npm --prefix mock-store/storefront run build
```

On Windows, activate with `.venv\Scripts\Activate.ps1` and use `python` in place
of `python3`. Chromium installation and context behavior follow the
[Playwright Python documentation](https://playwright.dev/python/docs/library).
Rebuild the storefront after editing its sources. Browser evaluation serves the
built `dist` directory, not the Vite development server.

## Run

No manual server launch is needed. Each isolated worker creates a fresh store,
serves its API and UI on one ephemeral localhost port, launches Chromium, runs
the task, scores final live state, saves artifacts, and stops the browser/server.

Provider-free multi-store baseline (four structured tasks):

```sh
PYTHONPATH=src python -m shopping_agent.cli run --agent rules \
  --transport browser --mode multi-store --repetitions 1 \
  --output results/browser-rules.jsonl
```

Claude requires `ANTHROPIC_API_KEY` in the environment. Model/effort overrides use
`ANTHROPIC_MODEL` and `ANTHROPIC_EFFORT`, just as in API trials:

```sh
PYTHONPATH=src python -m shopping_agent.cli run --agent claude \
  --transport browser --mode multi-store --repetitions 1 \
  --output results/browser-claude-stores.jsonl

PYTHONPATH=src python -m shopping_agent.cli run --agent claude \
  --transport browser --mode flat --repetitions 1 \
  --output results/browser-claude-flat.jsonl
```

Use a new output path for each experiment; existing output is never overwritten.
The older flat structured harness remains available with `--mode flat --tasks
 data/tasks/harness --agent rules`. The rules baseline cannot interpret the flat
natural-language suite; choose Claude for those tasks.

Add `--headed` to watch Chromium. Use `--transport api` for the original API
condition. `--mode` chooses the catalog/suite; `--transport` chooses how the
agent observes and changes it. Third-party models can implement the existing
`Agent.run` protocol and use the same browser adapter through the Python runner.
Only the existing rules and Claude agents are named CLI choices.

## Inspect results

```sh
PYTHONPATH=src python -m shopping_agent.cli report results/browser-claude-stores.jsonl --markdown
PYTHONPATH=src python -m shopping_agent.cli report results/browser-claude-stores.jsonl --json
PYTHONPATH=src python -m shopping_agent.cli audit results/browser-claude-stores.jsonl
python -m playwright show-trace results/browser-claude-stores-artifacts/TRIAL/trace.zip
```

By default, each trial has an artifact directory under `<output-stem>-artifacts`;
`--artifacts-dir PATH` overrides the root. Each directory contains `actions.json`,
`final.png`, and `trace.zip`. The JSONL's `run_metadata.browser_artifacts` provides
the exact path. Low-level action events are streamed to the parent and persisted
as they occur. A hard-killed worker may not finish its screenshot/trace; its
partial action record and timeout result are retained.

`tool_calls` counts logical shopping calls. `browser_action_count` counts
navigation/click/fill/select operations; `browser_actions` also records DOM reads
and operation durations/errors. This makes the work hidden inside compound tools
visible. Reports include transport and median browser actions and reject pooled
API/browser records. Metadata captures the built UI hash, Chromium/Playwright
versions, viewport, and headed/headless setting.

Defaults remain **20 logical tool calls and 60 execution seconds per trial**,
configurable with `--max-calls` and `--timeout`. Browser/server initialization has
its own 60-second worker setup allowance. A separate bounded 15 seconds permits
scoring/artifact saving/cleanup. Execution timing excludes initialization and
teardown. Individual UI waits are bounded at five seconds. There is no extra
hard click cap; the time and logical-call limits apply, with clicks reported
separately. Parent termination also stops the worker's browser process tree.

## What is measured

Browser tools do not make HTTP requests or consume network responses, React
state, catalog files, or private evaluator endpoints. Normal storefront JavaScript
uses its public backend routes. Browser requests to `/internal/*`, API-document
pages, direct API document navigation, and unrelated origins are blocked. When external photo CDNs are blocked or unavailable,
the UI uses a local placeholder; screenshots therefore use offline artwork in this
DOM condition. The model receives no image inputs. The
evaluator alone configures/resets the store and reads its final snapshot.

The existing final-state/listing/cart scorer determines success. Initial page/store loads are ordinary public observations, including catalog
reads during setup. Search visits
result detail pages to populate the existing full-product observation contract;
this and other navigation can trigger additional public observations and scheduled
mutations. Browser and API action sequences therefore differ. Compare conditions
using identical tasks, catalog, seed, repetition count, and limits, while reporting
transport, actions, and timing separately. UI details are equally visible to human
shoppers; no expected answers or task constraints are embedded in the page.

## Verify

```sh
python -m pytest -q -m browser
python -m pytest -q
```

Browser tests require Playwright, Chromium, and a built storefront, otherwise they
skip. They use real Chromium and scripted/provider-free decisions to check both
suite modes, listing identity across stores, cart quantities, price/stock changes,
route isolation, tool limits, timeout records, and cleanup. Scripted model tests
validate the transport and scorer; they are not evidence of live Claude accuracy.
