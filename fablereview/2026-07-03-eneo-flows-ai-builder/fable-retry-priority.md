# Fable Retry Priority

## TL;DR

1. Fable 01-04 completed and contain the first usable findings.
2. Fable 06 v2 later completed and was verified by Codex GPT-5.5 xhigh.
3. Fable 05, 07, 08, and 09 original runs did not produce review content; each saved only the monthly spend-limit message.
4. Do not retry multiple Fable prompts in parallel; run one focused prompt at a time.
5. Under the user's current preference, next priority is legal evidence transparency, then API DX, then dead-code deletion after deterministic inventory.

## What Completed

| Fable | Area | Result | Durable File |
|---|---|---|---|
| 01 | Proposal repair/self-correction boundary | Full review complete | `fable-01-proposal-repair-boundary-review.md` |
| 02 | Compiler/topology/runtime contracts, underlag, RAG | Full review complete | `fable-02-compiler-topology-runtime-contracts-review.md` |
| 03 | Planning state, JSONB, persistence, 50k-user scale | Full review complete | `fable-03-planning-state-jsonb-scale-review.md` |
| 04 | Discovery, attachments, dialog cadence, user questions | Full review complete | `fable-04-discovery-attachments-dialog-review.md` |

## What Failed Due To Limit

| Fable | Area | Result | Retry? |
|---|---|---|---|
| 05 | Public API and consumer DX | No review content; spend-limit message only | Yes, after evidence transparency |
| 06 | Operational runtime reliability | Original prompt was quota-limited; v2 later completed and was Codex-verified | Done for now |
| 07 | Evidence/legal transparency | No review content; spend-limit message only | Yes, priority 1 under current user preference |
| 08 | Dead-code/deletion audit | No review content; spend-limit message only | Later, after deterministic inventory |
| 09 | Security/tenant boundaries | No review content; spend-limit message only | Deferred by current user preference |

## Recommended Next Runs After Reset

| Priority | Prompt | Why |
|---:|---|---|
| 1 | `fable-07-evidence-legal-transparency-v2-prompt.md` | Directly addresses the legal/public-record disclosure concern: exact flow, prompts, model settings, chunks, files, timestamps, errors, outputs, redactions, retention gaps, and missing-data honesty. |
| 2 | `fable-05-flow-api-consumer-dx-prompt.md` | Important before external API usage; should expose the evidence/runtime truth instead of inventing a separate API story. |
| 3 | `fable-08-dead-code-deletion-audit-prompt.md` | Do not spend scarce Fable first. Run deterministic inventory with Codex/rg/knip/vulture/migration checks, then ask Fable to judge deletion risk. |
| Deferred | `fable-09-security-tenant-boundary-prompt.md` | High production value, but deferred by current user preference. |

## Execution Rule For Next Reset

Run one Fable prompt at a time, or at most two if quota is known to be large. The CLI output is effectively final-output buffered; when the spend limit triggers before completion, the review file contains only the limit message, not partial reasoning.

## Immediate Non-Fable Work

Use GPT-5.5/Codex to verify and synthesize Fable 01-04 into an implementation-ready backlog, then add the future Fable 09/07/06 results when quota resets.
