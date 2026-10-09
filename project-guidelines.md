# CS498 Understanding and Using AI Agents - Fall 2026 Final Project Overview

## Project Overview

In this course, you will design, implement, and evaluate an AI agent system. Your project will culminate in two separate papers: one documenting your benchmark design and another documenting your agent implementation.

## Key Requirements

- Design and implement an AI agent for a specific task domain
- Implement your own agent.
- Do not use existing full agent implementations or frameworks (e.g., LangGraph) as your solution. Standard libraries/APIs are fine, but the agent logic and orchestration must be your own.
- Create a custom benchmark (per team):
  - The benchmark must be independent of your agent, so others could use it to evaluate their own agents.
  - From scratch: Create 10 original benchmark tasks (3-credit) or 20 original tasks (4-credit).
  - Task instances must be created by your team. You may not copy, scrape, sample, lightly modify, or rephrase task instances from an existing benchmark, dataset, website, or naturally occurring task collection. For example, simply taking existing prediction-market questions, GitHub issues/SWE-bench tasks, trivia/QA questions, or similar public task sets is not allowed.
  - You may reuse benchmark infrastructure, an environment, or a general task format. If you substantially build on an existing benchmark framework, you must create 20 (3-credit) / 40 (4-credit) new tasks and explain in the benchmark paper which framework you used and what is meaningfully different about your benchmark.
  - Note that benchmark construction is an explicit goal of the project. If we think students are being lazy we will take off considerable points.
- Mixed-credit teams follow the 4-credit requirement.
- No coding/programming agents - choose a different domain
- Write two separate papers:
  - Benchmark paper (3-4 pages): Document your task suite design
  - Agent paper (3-4 pages): Document your agent implementation and evaluation
- Present your findings to the class

## Timeline Summary

| Assignment | Due Date | Week | Points |
| --- | --- | --- | ---: |
| Project Proposal | September 17 (Thu) | Week 4 | 20 |
| Project Update 1 | September 24 (Thu) | Week 5 | 5 |
| Evaluation Plan | October 1 (Thu) | Week 6 | 20 |
| Project Update 2 | October 13 (Tue) | Week 8 | 5 |
| Draft Benchmark Paper | October 27 (Tue) | Week 10 | 15 |
| Project Update 3 | October 29 (Thu) | Week 10 | 5 |
| Draft Agent Paper | November 12 (Thu) | Week 12 | 15 |
| Fall Break | November 21-29 | - | - |
| Final Presentations | November 19, December 1 and 3 (live); December 8 (online recording) | Weeks 13-15 | 25 |
| Final Benchmark Paper | December 8 (Tue) | Week 15 | 40 |
| Final Agent Paper | December 8 (Tue) | Week 15 | 40 |
| Total |  |  | 190 |

## Project Ideas (Examples)

- Flight-disruption recovery agent: Given an existing itinerary and simulated flight/hotel search and booking APIs, recover from cancellations or delays while satisfying constraints on arrival time, cost, preferred airlines, and existing reservations. Success is measured from the final itinerary, constraint violations, and total cost.
- IT troubleshooting agent: Given a simulated computer or network environment with diagnostic and configuration tools, identify and repair a fault such as broken DNS, routing, permissions, or service configuration. The agent must gather evidence, test hypotheses, and modify the system. Success is determined directly from whether the target functionality is restored without breaking unrelated components.
- Warehouse fulfillment agent: Given customer orders, inventories across warehouses, shipping options, deadlines, and transfer/purchase tools, fulfill the orders while minimizing cost and lateness. Inventory and availability can change as the agent acts. Success is measured from the final fulfillment state, deadlines met, constraint violations, and total cost.

A good project should define a stateful environment in which the agent must observe information, make multiple decisions or tool calls, and change or navigate the environment toward an objectively checkable goal. A task that is essentially a single LLM prompt and response is not sufficient.

## Assignment Files

- 01_project_proposal - Project Proposal assignment
- 02_project_updates - Project Updates assignment (3 total)
- 03_evaluation_plan - Evaluation Plan assignment
- 04_draft_benchmark_paper - Draft Benchmark Paper assignment
- 05_draft_agent_paper - Draft Agent Paper assignment
- 06_final_benchmark_paper - Final Benchmark Paper assignment
- 07_final_agent_paper - Final Agent Paper assignment
- 08_final_presentation - Final Presentation assignment

All assignment documents can be found at:
https://drive.google.com/drive/folders/1mWHDE9fdIEBysbQX7vfT-CHPmPMy3ARs?usp=drive_link

