Paste-ready bullets for the validation section of the paper draft (section 5
in the ICLR template). Keep wording agent-independent; cite `validation.md`
and `validation-results.json` for the numbers behind each bullet.

## Preliminary validation of the task suite

- **Achievability.** We validate the 15-task suite with a deterministic
  structured-rules baseline (search the category, filter on observable
  attributes, rank by the declared rule, re-verify before committing), run
  through the same evaluator path as any agent: fresh store reset per trial,
  tool-call budget of 20, scorer applied to the live store snapshot. The
  baseline solves **15/15 tasks across 45/45 trials** (3 repetitions per
  task), using at most **11 tool calls** per trial, so the suite is solvable
  by a competent tool-calling agent at a budget comfortably below the cap.
- **Ground-truth validity, not self-assertion.** Expected outcomes are
  re-derived from catalog ground truth plus scheduled mutations by the
  authoring loader, and any task file declaring an expected set that
  disagrees with the recomputation is rejected at load time. A tamper probe
  that redirected a task's expected answer to a sponsored decoy was rejected
  (`expected products [decoy], computed [correct product]`), so the suite's
  ground truth is checked by construction rather than by reviewer trust.
- **Version pinning.** Every task pins the catalog revision it was authored
  against (`catalog-v2`), and the loader rejects stale-version binds, which
  keeps expected sets meaningful if the fixture catalogue evolves.
- **Trap diagnostics.** The pilot traces confirm each decoy fires as
  designed: the sponsored-first keyword-stuffed shoe appears before any valid
  candidate in search results (a top-result-following agent fails three
  grounds at once: size, waterproof attribute, and ranking); the
  highest-rated bag in its category also fails the hard waterproof
  constraint (a soft-preference-out-voting agent selects a non-waterproof
  product); and a mid-trial price drop is visible only on re-reading a
  second time, where a single-snapshot agent carts the stale winner and
  fails the scorer's live-price consistency check.
- **Difficulty-calibration sanity checks.** The suite's 3 easy / 8 medium /
  4 hard mix is asserted by the loader and tests; the baseline's observed
  call counts are flat across difficulty (medians 8–9.5 calls from easy to
  hard), showing that difficulty in this suite arises from decision
  structure rather than from more work, and that hardness is not
  addressable by simply spending a larger tool-call budget.
- **Deterministic repeatability.** The rules baseline's three repetitions are
  exactly identical per task (same selections, same call counts), with the
  only run-to-run variation in wall-clock time; all raw per-trial records,
  including timing, tool traces, and source-code snapshot hashes, are
  retained in the results file so the validation itself is reproducible.

## Caveats to state in the paper

- The suite is single-merchant and closed-world; decoy resistance is
  defined over a documented fixture taxonomy rather than live-web hosts.
- Clarification is scored as an anchored question, not a simulated dialogue.
- No human inter-annotator reliability has been run yet; difficulty labels
  are grounded by loader recomputation and the baseline probe, not IRR.
- The `unsupported_claim_rate` metric is not exercised in these pilot runs
  and remains null in the report until a claims-emitting agent is evaluated.
