# Billy's implementation and writing plan

## Completed implementation

- Preserve agent, model, and prompt identity for successful, failed, and forcibly stopped trials.
- Record source, task, and catalog hashes, input surface, budgets, and dependency versions.
- Capture provider-reported input/output token usage across the Claude tool loop. Keep incomplete usage and unavailable dollar costs null.
- Reject rules-on-natural-language runs and missing Claude credentials before creating trial output.
- Produce per-task and per-difficulty summaries plus observable failure categories; reject pooled agent/model/prompt/input conditions.
- Add a Markdown report option without changing the default JSON output.
- Verify the new behavior with regression tests and rerun the structured pilot.

## Writing plan

1. Progress Summary: describe the evaluator changes above, not the original creation of the runner.
2. Current Status: report the test count and structured-pilot results from preserved evidence. Report the completed 30-trial live NL evaluation separately from the structured pilot.
3. Challenges and Solutions: explain incorrect timeout attribution and the invalid comparison between structured inputs and natural-language tasks; describe the implemented fixes.
4. Next Steps: Billy runs 10 NL tasks three times on Ronit's agreed agent commit, saves per-task results, and inspects failed traces. Ronit confirms the interpretation/reliability changes and provides their commit. Tim owns browser integration; Neel owns benchmark content.
5. Questions/Help: confirm the updated agent commit for the next comparison; the live API connection has been verified. Define browser action and time budgets before browser comparisons.
6. Individual Contributions: use the completed-work sentence in project-update-3-billy.md. Add live evaluation claims only after the run.

## Reproducing the completed live experiment

Requires ANTHROPIC_API_KEY in the process environment. Never put credentials in logs or the repository.

```powershell
$env:PYTHONPATH = 'src'
.venv/Scripts/python.exe -m shopping_agent.cli run --agent claude --tasks data/tasks --repetitions 3 --seed 498 --max-calls 20 --timeout 60 --output results/claude-update-3.jsonl
.venv/Scripts/python.exe -m shopping_agent.cli report results/claude-update-3.jsonl --markdown
```

Use a new output filename for each run. A completed evaluation may contain genuine agent failures; do not tune benchmark answers or disclose evaluator constraints to improve the score. Inspect up to three representative failures and separate observed outcomes from inferred causes. Retain all errors/timeouts in the denominator.

The existing main-branch agent does not contain the draft's claimed schema-constrained interpretation stage. This contribution instruments the evaluator and existing agent; it does not claim to implement Ronit's separate work. Simulated HTTP tests verify integration, not model quality.

## Group draft corrections

- Complete the unfinished reliability sentence using Ronit's verified implementation.
- Resolve the conflict between claiming LLM interpretation is finished and listing regex replacement as future work.
- Replace the unsourced 90%+ claim with versioned measured results; the structured pilot is not a score on the new NL suite.
- Explain progress percentages against milestones instead of repeating old values.
- Keep the final submission's six required sections, with one actual contribution sentence per person.

The local `.env` is ignored by Git. `scripts/run-update3.ps1` loads it without displaying the key and runs a three-repetition experiment with a fresh output filename. The rules variant was executed successfully as a script smoke test.
