# Natural-language suite: baseline comparison (Update 4)

The previous table showed only the proposed agent on the ten natural-language
tasks, with one trial per task and no comparison conditions. This update runs
three seeds per task for four conditions, giving **30 trials per condition and
120 trials total**. Table 1 is generated from the saved trial records by
`python -m shopping_agent.cli compare`; the machine-readable originals are in
[`nl-comparison-update4/`](nl-comparison-update4/).

## Table 1

| Condition | Successful / trials | Success rate | Median calls | Median seconds | p95 seconds | Trials with claim evidence |
|---|---:|---:|---:|---:|---:|---:|
| Single-prompt LLM | 0/30 | 0.0% | 3.0 | 0.0084 | 0.0110 | 0/30 |
| Vanilla ReAct | 3/30 | 10.0% | 9.0 | 0.0177 | 0.0230 | 0/30 |
| Proposed agent (no-verifier ablation) | 30/30 | 100.0% | 9.0 | 0.0183 | 0.0227 | 0/30 |
| Proposed agent (with verification gate) | 30/30 | 100.0% | 11.0 | 0.0203 | 0.0258 | 21/30 |

Success is graded from final live store state and cart contents, never from the
agent's own report. Failures, abstentions, and clarifications stay in the
denominator. "Trials with claim evidence" counts trials whose record contains
at least one structured evidence item produced by the deterministic verifier.

## Conditions

- **Single-prompt LLM** makes one model call over a single `search` snapshot and
  takes the first result in sponsored-first order. It has no constraint
  interpretation, no ambiguity detection, and no verification gate.
- **Vanilla ReAct** runs a plain tool loop: broad search, a few listing
  inspections, then it carts the cheapest (or highest-rated) observed item.
  It does not apply the typed hard-constraint checks. Its three successes are
  the clarification task.
- **No-verifier ablation** uses the proposed pipeline's interpretation and
  ranking, but the deterministic verification gate is removed: no final
  listing refresh, eligibility re-check, cart-price/stock verification, or
  claim evidence.
- **Proposed agent (with verification gate)** adds that final refresh,
  eligibility re-check, cart verification, and claim evidence. Comparing it
  with the ablation isolates the cost and coverage of the deterministic checks.

## What this comparison shows

The baseline gap is large: a single prompt and a plain ReAct loop solve none of
the product tasks, while constraint-aware conditions solve all ten. Removing
the final verification gate did **not** change success on this suite: the
scheduled mutations apply at the first public observation, so both conditions
see the changed price/stock in their ordinary search results. The gate's
measurable effect here is two extra tool calls per completed trial and claim
evidence on all 21 completed trials, versus none in the ablation. This is a
result about this ten-task suite, not a general claim that verification never
affects correctness.

## What ran and what was blocked

- **Executed:** all 120 offline trials, four conditions × ten tasks × seeds
  `1,2,3`, in-process against the mock FastAPI store with a 20-tool-call limit
  and 60-second trial deadline. No key, network call, or browser was used.
- **Offline model:** the conditions use deterministic, reproducible model
  surrogates (`offline-surrogate-v1`) that read only the shopper's original
  text and public catalog observations. They never read expected outcomes.
- **Blocked:** no `ANTHROPIC_API_KEY` is available in this environment, so a
  live provider run of these conditions was not executed. The existing live
  Claude result is preserved separately in
  [`claude-update-3.jsonl`](claude-update-3.jsonl) and
  [`claude-report-update-3.md`](claude-report-update-3.md); it uses the same
  ten tasks and three repetitions but is a different model/provider and is not
  pooled with the offline table. With a key configured, run the proposed
  condition live with `--agent claude` under the same seeds and budgets.

## Reproduce

From the repository root:

```sh
PYTHONPATH=src:mock-store python -m shopping_agent.cli compare \
  --output-dir results/comparison-update4 \
  --mode flat --seeds 1,2,3 \
  --conditions single_prompt,react,no_verifier,full \
  --max-calls 20 --timeout 60
```

PowerShell:

```powershell
$env:PYTHONPATH = "src;mock-store"
py -m shopping_agent.cli compare --output-dir results/comparison-update4 `
  --mode flat --seeds 1,2,3 `
  --conditions single_prompt,react,no_verifier,full `
  --max-calls 20 --timeout 60
```

The command refuses to overwrite an existing output directory. It writes one
JSONL file per condition, `comparison.json`, `comparison.csv`, and `table1.md`.
Each trial records its seed, task order, model/prompt identity, source hash,
task and catalog hashes, full tool trace, final state, and outcome.

## Caveats

- Ten tasks with three seeds each are exploratory. The 30 trials per condition
  are repeated trials of the same ten tasks, not 30 independent tasks; no
  significance claim is made.
- The offline surrogates measure harness behavior, baselines, and the effect of
  deterministic checks. They are not a measurement of any commercial LLM's
  shopping ability, latency, or token cost.
- Median and p95 durations are local in-process API timings, excluding worker
  startup and scoring. They are not browser or provider latency.
