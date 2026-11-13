# Project Update 3 — draft for October 29, 2026

## 1. Progress Summary

This week we moved the shopping agent from accepting only pre-parsed benchmark
requests toward handling ordinary user language. We implemented a
schema-constrained Claude interpretation phase that converts a free-form query
into a validated `ShoppingRequest` and ranking rule before the existing ReAct
tool loop begins. A deterministic parser remains available for local
normalization tests and development. The interpretation contract distinguishes
hard constraints, soft preferences, ranking rules, and clarification questions,
while the existing verification and stale-data recovery logic remains shared.

We also added regression tests for natural-language paraphrases, negated
attributes, missing categories, and invalid empty requests. This is a
conservative first parsing layer rather than a claim of full semantic
understanding: unsupported or underspecified product categories result in an
explicit clarification request instead of a guessed search.

## 2. Current Status

- **Benchmark:** The existing five authored tasks and six-product catalog remain
  functional. The next benchmark milestone is to add distinct store/catalog
  configurations and harder tasks that test distractors, ranking tradeoffs,
  ambiguity, and browser interaction.
- **Agent:** The typed rules baseline, Claude interpretation call, Claude tool
  loop, listing refresh, eligibility verification, cart verification, and claim
  evidence remain available. `runAgent` now interprets free-form input with
  Claude before shopping; inputs such as “least expensive rain shell, medium
  size, below $100” are converted into typed constraints before tool use.
- **Evaluation:** The new parser and contract tests pass (14/14). Existing
  agent, parser, contract, and evaluation tests pass (38/38 when excluding one
  HTTP-client compatibility failure described below). The current pilot
  success results still measure structured benchmark requests; we have not yet
  claimed a parser or LLM interpretation accuracy rate because a
  paraphrase-focused benchmark set has not been authored.

## 3. Challenges and Solutions

The previous live entry point used a few literal regular expressions. It could
miss equivalent requests such as “least expensive,” “rain shell,” “medium
size,” or “below $100,” and it could not safely distinguish “non-waterproof”
from “waterproof.” We addressed this by centralizing parsing, normalizing
supported aliases, handling explicit negation before positive matches, and
using typed constraints rather than passing raw text into search.

The interpretation step is intentionally schema-constrained. When a request
does not identify a product category, Claude is instructed to populate
`clarification_needed` rather than silently searching the wrong category. The
Pydantic contract rejects malformed constraints or invalid ranking values before
the shopping loop can use them.

One full-suite run had 39 passing tests and one pre-existing
`test_public_adapter_and_budget_record_http_errors` failure: the installed
HTTP client raised an exception from a different imported HTTPX module than
the class caught by `CatalogAPI`. Focused parser, contract, and evaluation
behavior passed; the dependency/import mismatch should be resolved before
reporting a clean full-suite result.

## 4. Next Steps

### Agent implementation

- Add a dedicated interpretation benchmark with paraphrases, ambiguous
  requests, conflicting requirements, soft preferences, and unsupported
  attributes. Compare the deterministic parser and Claude interpreter using
  exact constraint matching and clarification accuracy.
- Add retry and error policies for rate limits, temporary network failures,
  malformed tool arguments, and unavailable stores. Record interpretation
  failures separately from shopping-tool failures.
- Extend the typed request contract to cover quantities, colors, brands,
  sellers, shipping constraints, and product variants while preserving the
  distinction between hard constraints and preferences.
- Add multi-query and multi-store search planning so the agent can broaden a
  search when results are empty, narrow it when results are noisy, and
  deduplicate products across sellers.
- Implement Playwright-backed tools behind the existing `ShoppingTools`
  interface and reuse the final listing refresh, ranking, and cart
  verification pipeline.

### Benchmark and evaluation

- Populate multiple store catalogs with overlapping products, misleading
  listings, sponsored results, and changing prices or stock.
- Define an action-efficiency protocol for API and browser trials: success
  remains primary, while tool/click count and wall-clock time are secondary
  budget and efficiency metrics.
- Resolve the HTTP-client compatibility failure, then run clean repeated
  baseline, deterministic-parser, LLM-interpreter, and full-ReAct comparisons.
- Report success rate, constraint satisfaction, clarification accuracy, action
  count, median duration, p95 duration, and failure reason separately rather
  than hiding them in one aggregate score.

## 5. Questions and Help Needed

- **Evaluation design:** Should efficiency be reported as separate action and
  duration metrics, or should the final benchmark also include a weighted
  efficiency score? We currently prefer reporting them separately so a fast
  but incorrect agent cannot hide its failures.
- **Interpretation labels:** Which paraphrase, ambiguity, and conflicting
  constraint cases should receive independent human labels before measuring
  Claude's interpretation accuracy?
- **Browser budget:** What fixed click/action limit and timeout should be used
  for browser trials so API and browser conditions can be compared fairly?
- **Scope:** Should the first browser version support only search-to-cart, or
  should it also include checkout-related information such as shipping and
  delivery estimates?
- **Model comparison:** Should we compare multiple Claude models, or hold the
  model fixed and focus first on parser, prompt, and tool-loop ablations?

## 6. Individual Contributions

- **Ronit:** Implemented the Claude ReAct agent integration and typed shopping
  tools, including search, listing retrieval, cart inspection, cart insertion,
  candidate ranking, claim evidence, and final cart verification. Added a
  schema-constrained LLM interpretation phase that converts free-form language
  into validated hard constraints, soft preferences, ranking rules, and
  clarification questions before the shopping loop. Strengthened stale-data
  handling by refreshing and re-ranking candidates immediately before cart
  insertion, added recoverable tool-error responses, and wrote regression tests
  for malformed model output and request interpretation.
- **Tim:** [Confirm this week's Playwright/browser-use work.]
- **Neel:** [Confirm this week's mock-store/catalog work.]
- **Billy:** [Confirm this week's evaluation-runner, scoring, or reporting work.]
