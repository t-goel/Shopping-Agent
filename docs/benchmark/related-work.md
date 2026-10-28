# Related Work — Shopping-Agent Benchmark

This document surveys prior benchmarks and environments related to our planned shopping-agent benchmark. Our benchmark is independent of any specific agent implementation: it evaluates agents on (1) constraint satisfaction with an explicit hard-constraint vs. soft-preference distinction, (2) product comparison/ranking under declared rules, (3) factual grounding with audit of unsupported claims, (4) adaptation to controlled mid-trial inventory mutations (price/stock), (5) clarification and abstention behavior (clarification, `no_valid_product` outcomes), and (6) resistance to decoys (sponsored-looking results, keyword-stuffed titles, near-miss products that fail exactly one constraint). Selection criteria: primary venues (NeurIPS, ICLR, SIGIR), shopping or adjacent web-agent domains, and benchmarks against which our evaluation dimensions can be meaningfully contrasted.

## 1. WebShop (Yao et al., NeurIPS 2022)

**Citation key: `yao2022webshop`**

WebShop is the most direct predecessor of our work: a simulated e-commerce website environment with 1.18 million real-world Amazon products and 12,087 crowd-sourced natural-language shopping instructions (Yao et al., 2022). An agent searches, navigates product and item pages, selects attributes (e.g., size/color), and purchases one product matching a compositional instruction with both stated attributes and a price limit; reward scores the attribute match of the purchased product to the instruction, weighted together with the correctness of the selected purchase options. Human trajectories (over 1,600) validate the benchmark, and the paper reports that the best trained agent reaches ~29% task success versus ~59% expert human performance, with demonstrations of sim-to-real transfer to amazon.com and ebay.com. WebShop fronts several challenges we share: compositional instructions, query reformulation, and noisy web text.

**What it measures:** end-to-end navigation and purchase success (and near-miss reward), instruction following with implicit attribute and price constraints.

**Limitations vs. our focus:** (i) *Static inventory* — the released environment does not model mid-trial price or stock mutations; an observation, once retrieved, stays valid. Our tasks (`price_change`, `stock_change`) make stale observations and recovery an explicit scored dimension. (ii) *No hard/soft constraint separation* — WebShop folds all requirements into a similarity-style reward for a match/no-match decision; there is no deterministic per-constraint pass–fail ledger and no explicit `no_valid_product` outcome when nothing satisfies the constraints. (iii) *No claim grounding* — the reward concerns the purchased item; it does not audit the agent's verbalized claims for support or contradiction against recorded observations. (iv) *No clarification behavior* — instructions are complete by construction, so the correct move is never to ask. (v) *No decoy structure* — result lists are drawn from real catalog noise rather than engineered sponsored/keyword-stuffed/near-miss placements.

## 2. Mind2Web (Deng et al., NeurIPS 2023, Spotlight)

**Citation key: `deng2023mind2web`**

Mind2Web is the first large-scale dataset for developing and evaluating generalist web agents, with over 2,000 open-ended tasks from 137 real websites across 31 domains — e-commerce among them (Deng et al., 2023). Tasks come with crowdsourced action sequences that form gold action trajectories; evaluation is action-level (whether the agent selects the correct element and action at each step) rather than final-state-level. Its contribution is breadth and realism of interaction patterns rather than any single domain.

**What it measures:** generalist web interaction ability — element selection and action prediction on real sites, including shopping tasks among other domains.

**Limitations vs. our focus:** (i) *Static snapshots* — tasks are captured HTML; there is no live site state at all, hence no stateful inventory, no resettable reproducible shopping environment, and no possibility of mutation tasks. (ii) *Action-level, not outcome-level scoring* — success mid-trajectory does not test whether the agent's final product choice satisfies hard constraints, whether it abstains appropriately, or whether its claims are grounded. (iii) *No task-scoped constraint semantics* — a shopping request's hard constraints, ranking rules, and valid set are exactly our scoring substrate; Mind2Web has no such task-level expected outcomes. (iv) *Domain coverage, not shopping depth* — comparison shopping, constraint tradeoffs, and decoy design are not addressed.

## 3. WebArena (Zhou et al., ICLR 2024)

**Citation key: `zhou2024webarena`**

WebArena builds a self-hostable, realistic, reproducible web environment with fully functional sites from four domains — including a complete e-commerce shopping site — plus tools (e.g., a map) and knowledge sources, and releases 812 long-horizon tasks evaluated by programmatic checks of *functional correctness of the final state* (Zhou et al., 2024). This is a significant step beyond static snapshots: sites support state-changing actions, and scoring examines end state rather than intermediate actions. Baseline results expose a large gap (best GPT-4-based agent ~14.4% vs. human ~78.2% end-to-end success).

**What it measures:** long-horizon task completion on stateful websites, scored by final-state verifiers across e-commerce, forum, development, and content-management domains.

**Limitations vs. our focus:** (i) *Shopping is one of four domains* — tasks target generic task completion (order management, account operations) rather than comparison shopping under a constraint/ranking rule. (ii) *No mid-trial inventory dynamics* — reproducibility comes from reset to a fixed snapshot; price/stock mutations during a trial are not a designed, scored dimension, and tasks are not structured around recovery from stale observations. (iii) *No claim audit* — final-state checks verify what was *done*, not whether the agent's stated rationale (prices, availability, product facts) was supported. (iv) *No abstention or clarification scoring* — every task has an achievable end state; refusing or asking is always wrong in their protocol, whereas our benchmark scores clarification and `no_valid_product` as first-class outcomes. (v) *No hard-vs-soft constraint ledger or engineered decoys.*

## 4. Shopping MMLU (Jin et al., NeurIPS 2024 Datasets & Benchmarks Track)

**Citation key: `jin2024shoppingmmlu`**

Shopping MMLU is a massive multi-task online shopping benchmark derived from real Amazon data, spanning 57 tasks across four skill families: shopping concept understanding, shopping knowledge reasoning, user behavior alignment, and multi-linguality; it was also the basis of the Amazon KDD Cup 2024 (Jin et al., 2024). It benchmarks LLMs on shopping-domain competence — product attribute semantics, implied knowledge, review understanding — representative of "LLM as general shop assistant."

**What it measures:** shopping-domain knowledge and reasoning in exam-style QA format, at scale (20+ LLMs evaluated).

**Limitations vs. our focus:** (i) *No environment or interaction* — questions are answered against fixed answers, not against a live or resettable store; there are no observations, no sources, and hence nothing to ground claims against. (ii) *Hi-QA, not agentic decision-making* — constraint satisfaction, ranking under declared rules, mutation recovery, clarification, and decoy resistance are simply not present as task types. (iii) *Not an independent task suite under environment control* — the benchmark tests the model directly, not an agent operating through bounded observations of authenticated store state. It is nevertheless valuable to us as the strongest evidence that shopping-specific domain competence is itself a measurable, multi-dimensional capability, separate from web interaction.

## 5. WebMall (Peeters et al., 2025; SIGIR 2026)

**Citation key: `peeters2025webmall`**

WebMall is the first offline *multi-shop* benchmark for web agents: four simulated shops populated with product data extracted from Common Crawl, 91 tasks across 11 task categories including specific product search, cheapest-product price comparison, complementary/substitute-product search, vague-requirement search, and checkout processes (Peeters et al., 2025). It is explicitly designed for exact experimental reproducibility (like WebShop/WebArena-type offline environments) while covering multi-shop heterogeneous retrieval that prior offline benchmarks lacked; validation with eight agent variants shows best completion rates below 65% on the cheapest-search and vague-search categories. Note that WebMall also cites the companion online benchmarks DeepShop and ShoppingComp, which evaluate agents on the live web; our benchmark deliberately takes the offline-reproducible route instead.

**What it measures:** offline multi-shop retrieval and comparison-shopping task completion, including cross-shop price comparison, with reproducible reset.

**Limitations vs. our focus:** (i) *Static catalog snapshots* — reproducibility derives from fixed pools; mid-trial price/stock mutations and stale-observation recovery are not part of the task design (this is our controlled `price_change`/`stock_change` dimension). (ii) *Completion-rate scoring* — success is per-task completion, without a per-constraint pass/fail ledger separating hard constraints from soft preferences, and without a scored `no_valid_product` outcome. (iii) *No claim-grounding audit* of the agent's justifications. (iv) *No clarification/underspecification dimension* — even the "vague search" category presumes an achievable target rather than scoring the agent's clarifying question. (v) *Fixed task set without versioned, resettable, independently reviewable task definitions with withheld expected outcomes*, which is central to our suite's reusability and to avoiding benchmark-specific instrumentation leaks.

## Comparison Table

| Dimension | WebShop (2022) | Mind2Web (2023) | WebArena (2024) | Shopping MMLU (2024) | WebMall (2025/26) | Ours |
|---|---|---|---|---|---|---|
| Environment type | Simulated single-shop e-commerce site (1.18M Amz. products) | Real-website traffic snapshots (137 sites, 31 domains) | Self-hosted live sites incl. 1 shopping site (4 domains) | None — exam-style QA benchmark | Offline multi-shop environment (4 CC-derived shops) | Resettable mock storefront + API; independent task suite |
| Stateful inventory (price/stock mutations mid-trial) | No (static catalog during episode) | N/A (no live state) | No (reset-to-snapshot reproducibility; mutations not a designed dimension) | N/A (no environment) | No (designed around static, reproducible snapshots) | **Yes — controlled scheduled mutations, scored recovery and stale-observation verdicts** |
| Constraint satisfaction (hard vs. soft, deterministic ledger) | No — similarity-style match reward | No — action-level evaluation | No — final-state task completion | No — task QA accuracy | No — completion-rate scoring | **Yes — deterministic per-constraint pass/fail/unknown ledger; hard constraints may not be silently relaxed** |
| Claim grounding / unsupported-claim audit | No | No | No (verifies actions and final state, not verbalized claims) | No | No | **Yes — every product claim audited against observations (supports / contradicts / unknown)** |
| Abstention & clarification | No (instructions complete) | No | No (all tasks achievable) | No | No | **Yes — `clarification_needed` and `no_valid_product` are scored outcomes** |
| Engineered decoys (sponsored, keyword-stuffed, near-miss) | No (natural catalog noise) | No | No | No | No | **Yes — seeded decoy and near-miss placements in result lists** |
| # Tasks | 12,087 instructions (~500-instruction test split) | 2,000+ tasks | 812 tasks | 57 tasks | 91 tasks (11 categories) | Pilot: 5/10 authored tasks (3 easy / 3 medium / 4 hard target) |
| Open vs. closed world | Closed (fixed Amazon-derived catalog) | Effectively open (real sites at collection time) | Closed but live (self-hosted, reproducible) | Closed (fixed question set + Amazon data) | Closed (Common Crawl-derived snapshot) | Closed by design — evaluator-owned ground truth, versioned examples |

## Gap Statement

Existing related work splits into two families: interaction benchmarks (WebShop, Mind2Web, WebArena, WebMall) that score whether an agent *completes a task on some shopping surface*, and knowledge benchmarks (Shopping MMLU) that score shopping-domain *competence without interaction or observation*. Across both families, the following capabilities our benchmark targets are not measured — and are not measurable with the prior scoring machinery:

1. **Hard vs. soft constraints with a deterministic ledger.** Prior benchmarks collapse requirements into match-style rewards or end-state checks. None reports a per-constraint pass/fail/unknown accounting or scores the specific failure of *silently relaxing* a hard constraint (e.g., returning water-resistant as waterproof).
2. **Unsupported-claim auditing.** No prior shopping benchmark audits the factual claims an agent makes in its justification against stored observations, distinguishing supports/contradicts/unknown; success in the related work may even correlate with unverified justification.
3. **Dynamic inventory as a scored dimension.** All interaction benchmarks are built around reproducible *static* states. Controlled mid-trial price/stock mutations — and the agent's obligation to re-verify rather than act on stale observations — are unique to our task design.
4. **Abstention and clarification.** Task formats that guarantee an achievable answer structurally never reward asking or refusing; our `clarification_needed` and `no_valid_product` outcomes make calibrated abstention measurable.
5. **Decoy resistance.** Sponsored-looking placements, keyword-stuffed titles, and near-miss single-constraint failures are engineered fixtures in our result lists, yielding a direct robustness measure none of the surveyed benchmarks provides.

Together, these give a benchmark that is independent of any particular agent implementation (scores derive from evaluator-held expected outcomes over versioned, resettable store state) and reusable across API and browser evaluation conditions — a combination not present in the surveyed environments.

## Citation Keys and Metadata

| Key | Authors | Year | Venue | Title |
|---|---|---|---|---|
| `yao2022webshop` | Yao, S.; Chen, H.; Yang, J.; Narasimhan, K. | 2022 | NeurIPS 35 | WebShop: Towards Scalable Real-World Web Interaction with Grounded Language Agents |
| `deng2023mind2web` | Deng, X.; Gu, Y.; Zheng, B.; Chen, S.; Stevens, S.; Wang, B.; Sun, H.; Su, Y. | 2023 | NeurIPS 36 (Spotlight) | Mind2Web: Towards a Generalist Agent for the Web |
| `zhou2024webarena` | Zhou, S.; Xu, F. F.; Zhu, H.; Zhou, X.; Lo, R.; Sridhar, A.; Cheng, X.; Ou, T.; Bisk, Y.; Fried, D.; Alon, U.; Neubig, G. | 2024 | ICLR 2024 | WebArena: A Realistic Web Environment for Building Autonomous Agents |
| `jin2024shoppingmmlu` | Jin, Y.; Li, Z.; Zhang, C.; Cao, T.; Gao, Y.; Jayarao, P.; Li, M.; Liu, X.; Sarkhel, R.; Tang, X.; Wang, H.; Wang, Z.; Xu, W.; Yang, J.; Yin, Q.; Li, X.; Nigam, P.; Xu, Y.; Chen, K.; Yang, Q.; Jiang, M.; Yin, B. | 2024 | NeurIPS 37 Datasets & Benchmarks Track | Shopping MMLU: A Massive Multi-Task Online Shopping Benchmark for Large Language Models |
| `peeters2025webmall` | Peeters, R.; Steiner, A.; Schwarz, L.; Caspary, J. Y.; Bizer, C. | 2025 | arXiv:2508.13024; accepted SIGIR 2026 | WebMall — A Multi-Shop Benchmark for Evaluating Web Agents |

APA-style references:

- Yao, S., Chen, H., Yang, J., & Narasimhan, K. (2022). WebShop: Towards scalable real-world web interaction with grounded language agents. In *Advances in Neural Information Processing Systems 35* (NeurIPS 2022). https://arxiv.org/abs/2207.01206
- Deng, X., Gu, Y., Zheng, B., Chen, S., Stevens, S., Wang, B., Sun, H., & Su, Y. (2023). Mind2Web: Towards a generalist agent for the web. In *Advances in Neural Information Processing Systems 36* (NeurIPS 2023). https://arxiv.org/abs/2306.06070
- Zhou, S., Xu, F. F., Zhu, H., Zhou, X., Lo, R., Sridhar, A., Cheng, X., Ou, T., Bisk, Y., Fried, D., Alon, U., & Neubig, G. (2024). WebArena: A realistic web environment for building autonomous agents. *ICLR 2024*. https://arxiv.org/abs/2307.13854
- Jin, Y., Li, Z., Zhang, C., Cao, T., Gao, Y., Jayarao, P., Li, M., Liu, X., Sarkhel, R., Tang, X., Wang, H., Wang, Z., Xu, W., Yang, J., Yin, Q., Li, X., Nigam, P., Xu, Y., Chen, K., Yang, Q., Jiang, M., & Yin, B. (2024). Shopping MMLU: A massive multi-task online shopping benchmark for large language models. In *Advances in Neural Information Processing Systems 37 — Datasets and Benchmarks Track* (NeurIPS 2024). https://arxiv.org/abs/2410.20745
- Peeters, R., Steiner, A., Schwarz, L., Caspary, J. Y., & Bizer, C. (2025). WebMall — A multi-shop benchmark for evaluating web agents. *arXiv preprint arXiv:2508.13024* (accepted to SIGIR 2026). https://arxiv.org/abs/2508.13024
