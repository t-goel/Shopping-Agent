# Table 1: natural-language suite by condition

| Condition | Successful / trials | Success rate | Median calls | Median seconds | p95 seconds | Trials with claim evidence |
|---|---:|---:|---:|---:|---:|---:|
| Single-prompt LLM | 0/30 | 0.0% | 3.0 | 0.0084 | 0.0110 | 0/30 |
| Vanilla ReAct | 3/30 | 10.0% | 9.0 | 0.0177 | 0.0230 | 0/30 |
| Proposed agent (no-verifier ablation) | 30/30 | 100.0% | 9.0 | 0.0183 | 0.0227 | 0/30 |
| Proposed agent (with verification gate) | 30/30 | 100.0% | 11.0 | 0.0203 | 0.0258 | 21/30 |

## Protocol

- Tasks: 10 natural-language tasks
- Seeds: 1, 2, 3 (3 per task)
- Trials per condition: 30
- Limits: 20 tool calls, 60.0 seconds per trial
- Source SHA-256: `2fa18b9b1523bdfa6afafa66ca5d98c7eb584a438da40ac7007089a41ae439c3`
- Note: Offline deterministic model surrogates; no Anthropic API key was used. A live provider-backed run uses --agent claude and is reported separately.
