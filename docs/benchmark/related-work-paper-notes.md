# Paper-Ready Notes — Related Work & Intro (Assignment 4, ICLR draft)

Source of truth: `docs/benchmark/related-work.md` (survey + gap table); citations in
`docs/benchmark/references.bib`. Every numeric claim below was verified against the
arXiv abstract pages of the cited papers in Oct 2026 unless explicitly flagged as
*unverified* at the bottom. These notes are implementation-independent: they never
reference our agent, only the benchmark's scoring machinery and task design.

## Part 1 — Related Work (~0.5 page)

Organize as two families, then position the two nearest neighbors.

**Interaction benchmarks.** WebShop (Yao et al., 2022) simulates a single e-commerce
site over 1.18M real Amazon products and 12,087 crowd-sourced instructions; reward
mixes attribute match and purchase-option correctness; best trained agent reaches
~29% success vs. ~59% expert human. Mind2Web (Deng et al., 2023) contributes
breadth — 2,000+ tasks from 137 websites across 31 domains — but scores
*action-level element selection* on captured site snapshots, not outcomes. WebArena
(Zhou et al., 2024) is the first to score *final-state functional correctness*
(812 tasks instantiated from 241 templates, one shopping site among four domains;
best GPT-4 agent 14.41% vs. 78.24% human), demonstrating agentic state changes in a
reproducible environment. WebMall (Peeters et al., 2025; SIGIR 2026) extends
off-line reproducibility to *multi-shop* heterogeneous retrieval: four Common
Crawl-derived shops, 91 tasks, best completion rates below 65% on cheapest-search
and vague-search categories. DeepShop (Lyu et al., ICLR 2026) represents the
online/live-web family: evolved real user queries across five shopping domains,
graded easy/medium/hard, with fine-grained evaluation of attribute, filter, and
sorting compliance.

**Nearest neighbors.** Two works already step onto our dimensions and must be
positioned carefully:

- *τ-bench* (Yao et al., 2024, arXiv preprint) is the closest to **clarification**
  and **state mutation**. It evaluates tool-agent-user conversations by comparing
  the database *end state* against an annotated goal state, and its retail domain
  (115 tasks) requires the agent to ask clarifying questions of a simulated user
  before transacting; it additionally contributes the pass^k reliability metric
  (GPT-4o: <50% serial success, pass^8 < 25% in retail). But its database changes
  are *agent-driven toward a fixed goal*, not evaluator-scheduled adversarial
  mutations; it verifies only that the *final answer* contains required facts, not
  that an agent's free-form justification is supported; and there is no retrieval
  surface, hence no ranking, decoys, or near-misses.
- *DeepShop* (Lyu et al., 2026) is the closest to the **constraint ledger**. Its
  fine-grained evaluation scores compliance with requested attributes, filters, and
  sorting — the same *content* our hard constraints cover. It stops short of a
  deterministic per-constraint pass/fail/unknown record, does not penalize silently
  relaxed hard constraints (water-resistant sold as waterproof), runs on the
  uncontrollable live web (no reset, no evaluator-owned ground truth), and offers
  no abstention outcomes or decoy fixtures.

**Knowledge benchmarks.** Shopping MMLU (Jin et al., NeurIPS 2024 D&B; 57 tasks
across four skill families; basis of Amazon KDD Cup 2024) measures shopping-domain
competence exam-style, with no interaction and nothing to ground claims against.
Cite it as evidence that domain competence and web interaction are separately
measurable capabilities our benchmark treats as subordinate to constraint-satisfying
decision-making.

**Dimension mapping (one table cell per work).**
Hard/soft-ledger: none (DeepShop nearest). Comparison/ranking under declared rules:
WebMall cheapest-search only, as task category, not a scored ranking rule.
Factual grounding: none audited over justification (τ-bench audits final answers
only). Mid-trial inventory mutation: none scheduled by evaluator (τ-bench
agent-driven; DeepShop uncontrolled live web). Clarification/abstention: τ-bench
clarification implicitly via goal state; abstention scored nowhere. Decoy
resistance: nowhere.

## Part 2 — Introduction cues (~0.75 page)

**Motivation arc (suggested 4 beats).**
1. *Deployment gap.* Agents that act on the live web (τ-bench retail pass^8 < 25%;
   WebArena best agent 14.41% vs. 78.24% human; WebMall < 65% on two categories)
   routinely purchase the wrong product or at the wrong price — single-number
   completion rates hide *why*.
2. *What real shopping demands beyond current benchmarks.* A faithful shopping
   assistant must hold hard constraints non-negotiable while soft preferences are
   rankable, justify its pick with facts it actually observed, re-verify when the
   store changes mid-trial, ask when the user's intent is genuinely ambiguous, and
   not be fooled by paid or keyword-stuffed placements. Each demand exists in
   production shopping sessions; none is a scored dimension in any surveyed
   benchmark — even its closest partial precursors (τ-bench, DeepShop) cover at
   most one, implicitly.
3. *Two benchmark families, one blind spot.* Interaction benchmarks score whether
   the agent completes a task on *some* shopping surface; knowledge benchmarks
   (Shopping MMLU) score competence *without* interaction. Both families
   structurally cannot measure the five capabilities in beat 2, because their
   scoring machinery keys on completion or correctness, not on constraint ledgers,
   claim audits, mutation recovery, abstention, or decoys.
4. *Our contribution (implementation-independent).* A benchmark whose scores derive
   from evaluator-held expected outcomes over versioned, resettable storefront
   state: a deterministic per-constraint pass/fail/unknown ledger separating hard
   constraints from soft preferences; auditing of every product claim as
   supports/contradicts/unknown against recorded observations; evaluator-scheduled
   mid-trial price/stock mutations that require re-verification; `clarification_needed`
   and `no_valid_product` as first-class scored outcomes; and engineered decoy and
   near-miss fixtures. Any agent — API-tool-calling, browser-operating, or
   hybrid — can be scored; nothing depends on a particular agent implementation.

**Limitations paragraph cues (to preempt skeptical reviewers).**
- *Ground truth is authored, not observed.* Expected outcomes and mutation
  schedules are written by the benchmark authors and held by the evaluator; the
  independence we gain (deterministic, reproducible, reviewable) trades against
  ecological validity relative to live-web evaluation (DeepShop, ShoppingComp),
  which we deliberately assign to complementary future use.
- *Simulated user simulation risk.* Where clarification is scored, the user role is
  a fixed interaction script (τ-bench's LLM simulator shows why this is delicate);
  our clarification outcome is thus a lower-bound estimate of real user ambiguity
  resolution. [Keep the comparison to τ-bench's simulated user — it invites the
  objection, so name it first.]
- *Closed world by design.* Decoys and near-misses are engineered, so decoy
  resistance here is resistance to *our* distributions; we release the fixture
  taxonomy so future suites can vary it.
- *Scale.* Pilot with 10 authored tasks prioritizes dimension coverage over volume;
  WebShop's 12,087 instructions and WebMall's 91 show the axis we are *not*
  competing on. State explicitly that per-constraint metrics, not task count, are
  the contribution.
- *Static policy text vs. drift.* Constraint rankings and policies are versioned
  with the suite; no claim is made about tracking evolving real-world storefronts.

**One-line gap statement (usable verbatim in Intro).**
"No existing benchmark — interaction- or knowledge-based, offline or live,
browser- or tool-mediated — jointly measures constraint-ledger discipline,
justification grounding, recovery from evaluator-injected inventory changes,
calibrated clarification and abstention, and decoy resistance under a single,
implementation-independent scoring protocol; partial coverage exists only for
clarification (τ-bench) and constraint compliance (DeepShop), each with a scoring
machinery too weak to support the other."

## Verification status (transparent footer for the paper author)

Verified directly against arXiv abstract pages: WebShop (2207.01206), Mind2Web
(2306.06070), WebArena (2307.13854), Shopping MMLU (2410.20745), WebMall
(2508.13024), τ-bench (2406.12045), DeepShop (2506.02839).

Unverified / noted for camera-ready:
1. **τ-bench venues** — a NeurIPS 2024 Datasets & Benchmarks submission exists on
   OpenReview (forum `roNSXZpUDN`) with a meta-review visible in search results,
   but the acceptance decision could not be read (OpenReview bot-check blocked the
   forum page). Cited as arXiv preprint; re-check before camera-ready.
2. **τ-bench retail/airline task counts (115/50)** — from the τ²-bench comparison
   table and τ-bench project pages, not from the τ-bench abstract. The community
   τ³ revision ("50+ task fixes") shows the counts are convention-stable but the
   *content* was audited; if we cite per-task counts, cite them to the project
   page, not the paper.
3. **WebArena "812 tasks from 241 templates" and τ-bench clarification
   requirement** — from secondary sources and the paper bodies/common lore, not
   from the abstracts; both are safe but cite the paper full text, not the
   abstract.
4. **DeepShop task count** — the paper does not state a single task count in the
   abstract (difficulty is continuous via evolution steps); "three difficulty
   levels, five domains, two evolution axes" is the safe phrasing, used above.
