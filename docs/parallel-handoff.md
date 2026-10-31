# Parallel work and shared interface

The deterministic pilot is implemented. Keep catalog/tasks, browser adapters, and LLM work in separate branches/PRs; this contribution owns shared contracts, API tools, verifier, rules baseline, and evaluation infrastructure.

## Teammate 1: LLM agent

Implement `Agent.run(AgentInput, ShoppingTools) -> AgentOutput` from `shopping_agent.interfaces`. Inputs contain the structured request and ranking rule. Outputs carry selected IDs, response text, claims, evidence, and termination reason. The runner owns scoring, task expectations, store reset, and measurements.

The current parsed request also supplies `clarification_needed`, including the exact question. The clarification pilot evaluates instruction routing, not ambiguity discovery. For comparative runs, choose and document one common input policy before testing: omit this directive when measuring model ambiguity detection, or supply identical parsed assistance to every condition and exclude discovery from the measured capability. Do not compare a raw-text model against this assisted baseline as if inputs were equivalent. Do not return success scores or pass an entire `TaskDefinition` to the agent.

The public shopping tools are:

- `search(SearchInput) -> SearchResult` (`SearchInput.store_id` required for stores-v1)
- `get_listing(product_id=…, store_id=…, listing_id=…) -> ProductObservation`
- `add_to_cart(CartSelection) -> CartObservation` (prefer `listing_id` / store+product on stores-v1)
- `inspect_cart() -> CartObservation`
- `list_stores() -> list[StoreRecord]` (stores-v1; 404 on single-store)

Use fake implementations of this protocol to start independently. `BudgetedTools` wraps the implementation and counts attempted calls, including failed HTTP requests. Verification is local computation, not an additional network call. Expose an allowlist to your model; keep private reset/state access out of it. No full agent framework is required or used.

The runner currently names the built-in condition `rules`, has no model measurement adapter, and the CLI selects only that condition. When connecting an LLM agent, extend condition selection/name/model/prompt metadata and capture actual token/cost measurements. Do not label LLM runs as rules or report unknown usage as zero. `isolated_trial(..., agent=...)` already accepts a picklable agent for integration. Keep provider objects/HTTP clients initialized inside the spawned worker.

## Teammate 2: benchmark

Own `data/tasks` and the mock catalog. Add five original tasks to reach 10, with a final 3 easy / 3 medium / 4 hard split. Current split is 1 easy / 2 medium / 2 hard. Include highest-rating tradeoffs, ties, and mutation recovery with valid replacements. Broaden beyond jackets and avoid tasks differing only in superficial wording.

The authoring loader validates references and declared expected sets. Independently review task goals and constraints; do not use the baseline's output to decide the answer. Existing test-only replacement catalogs demonstrate recovery without consuming your task ownership. Update any existing tests that explicitly enumerate the five tasks when expanding the suite.

The pilot uses category-wide search limited to 50 results and fails on a possibly truncated result set. It re-reads all results and revalidates the chosen item before cart addition. Large catalogs, missing category constraints, category changes, and arbitrary late events may need additional search/replanning support. Keep tasks within the documented interface or propose contract changes first.

## Teammate 3: browser and update

For Update 2, prioritize the six-section update plus a small Playwright smoke test of the existing storefront; expand browser adapters afterward. Implement the same logical tools using visible page information. No private API/product-state shortcuts in browser-only trials. A full browser scorer/runner mode still needs integration; the current CLI runs API trials only.

Collect everyone's verified contribution statements and replace the pending entries in `project-update-2.md`. Include actual results from `docs/pilot`, not hypothetical LLM/browser results.

## Integration order

1. Review shared interfaces and additive contract changes in this branch.
2. Integrate the tested deterministic pipeline.
3. Independently develop LLM work, catalog/tasks, and browser adapters.
4. Connect each adapter to the runner and evaluate under the same limits/seed/task order.

## Evaluation-plan revisions before comparative experiments

Define validated/inconclusive/negative precedence and the missing 5–15 percentage-point region before examining comparative results. Resolve the document's three-repeat vs five-repeat consistency procedures. Use agreement on selected IDs, including explicit no-match/clarification outcomes, rather than variance of arbitrary product-ID encodings.

Define claim units, supported/contradicted/unknown labels, denominators, paraphrase review, and an anchored human scoring rubric. Independently annotate explanation text; verifier-produced evidence alone is not an unsupported-claim audit. Predefine paired statistical analysis at the task level, avoiding treatment of repeated trials on the same task as independent tasks. Document failure accounting and stopping budgets. Tomorrow's five-task results are exploratory and support no comparative significance claim.
