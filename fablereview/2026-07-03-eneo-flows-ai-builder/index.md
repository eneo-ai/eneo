# Fable Review Program Index

## Purpose

This folder tracks scarce Fable review work for Eneo Flows and Flow AI Builder.
Keep raw model output, verified summaries, and implementation-ready follow-up
plans here until a finding is promoted into source changes, project docs, or an
ADR.

Durable repo copy: `fablereview/2026-07-03-eneo-flows-ai-builder/`.
The `.codex/artifacts` copy is the process workspace for running agents; the
`fablereview/` copy is the handoff location that should be preserved.

## Review Standard

- Prefer source-backed findings with `file:line` evidence.
- Treat Fable, Claude, and Codex as reviewers, not authorities.
- Verify high-impact claims locally before implementation.
- Use the Ponytail lens: delete, reuse, merge, or simplify before adding.
- Because Flow and Flow AI Builder are pre-production, do not preserve
  compatibility paths without persisted-data evidence and a deletion trigger.

## Artifact Ledger

| Date | Area | Artifact | Status | Notes |
|---|---|---|---|---|
| 2026-07-02 | Flow runtime semantic dataflow | [`../fable-max-review-20260702/fable-review.md`](../fable-max-review-20260702/fable-review.md) | Raw Fable review complete | Max-effort Fable pass on runtime/input/underlag/JSON/Builder dataflow. |
| 2026-07-02 | Flow runtime semantic dataflow | [`../fable-max-review-20260702/summary.md`](../fable-max-review-20260702/summary.md) | GPT-5.5 verified | Treat findings 1-4 as highest-ROI release blockers; findings 5, 6, 9, 10, 11 as real but lower priority; findings 7, 8, 12 as cleanup/defer. |
| 2026-07-03 | Fable strategy | [`opus-strategy-brief.md`](opus-strategy-brief.md) | Complete | Source-backed brief sent to Opus for Fable split strategy. |
| 2026-07-03 | Fable strategy | [`../ask-claude-fable-ai-builder-review-split-long-20260702T223104Z.md`](../ask-claude-fable-ai-builder-review-split-long-20260702T223104Z.md) | Opus complete | Recommends three sequential sessions: proposal repair boundary, discovery/attachments, data model; Codex adapted this to repair, compiler/runtime contracts, JSONB with discovery as optional fourth. |
| 2026-07-03 | Evidence packet | [`fable-source-evidence-packet.md`](fable-source-evidence-packet.md) | Complete | Source evidence for conversation loop, attachments, repair, underlag/runtime contracts, and JSONB. |
| 2026-07-03 | Runtime/dataflow agent | [`agent-runtime-dataflow-review.md`](agent-runtime-dataflow-review.md) | Complete | GPT-5.5 xhigh subagent review of underlag/RAG/runtime validation contracts. |
| 2026-07-03 | Data model/JSONB agent | [`agent-data-model-jsonb-review.md`](agent-data-model-jsonb-review.md) | Complete | GPT-5.5 xhigh subagent review of JSONB, relational modeling, and 50k-user scale. |
| 2026-07-03 | Maintainability/boundaries agent | [`agent-maintainability-boundaries-review.md`](agent-maintainability-boundaries-review.md) | Complete | GPT-5.5 xhigh subagent review of ownership, duplicate commit spine, slot registry, and deletion candidates. |
| 2026-07-03 | Frontend/dialog agent | [`agent-frontend-dialog-state-review.md`](agent-frontend-dialog-state-review.md) | Complete | GPT-5.5 xhigh subagent review of backend dialog cadence, frontend state, generated contracts, and option rendering. |
| 2026-07-03 | Repair/Fable split agent | [`agent-repair-fable-split-review.md`](agent-repair-fable-split-review.md) | Complete | GPT-5.5 xhigh subagent review of repair/fallback dependence and recommended Fable split. |
| 2026-07-03 | Fable execution plan | [`fable-session-plan.md`](fable-session-plan.md) | Complete enough for execution | User explicitly chose parallel Fable usage over further Opus direction-gating because quota reset was near. |
| 2026-07-03 | Fable 01 proposal repair boundary | [`fable-01-proposal-repair-boundary-prompt.md`](fable-01-proposal-repair-boundary-prompt.md) | Complete | Max-effort Fable prompt for proposal repair boundary. |
| 2026-07-03 | Fable 01 proposal repair boundary | [`fable-01-proposal-repair-boundary-review.md`](fable-01-proposal-repair-boundary-review.md) | Raw Fable complete | Exit code 0; status sidecar: `fable-01-proposal-repair-boundary-review.md.status`. |
| 2026-07-03 | Fable 02 compiler/runtime contracts | [`fable-02-compiler-topology-runtime-contracts-prompt.md`](fable-02-compiler-topology-runtime-contracts-prompt.md) | Complete | Max-effort Fable prompt for compiler/topology/runtime contracts. |
| 2026-07-03 | Fable 02 compiler/runtime contracts | [`fable-02-compiler-topology-runtime-contracts-review.md`](fable-02-compiler-topology-runtime-contracts-review.md) | Raw Fable complete | Exit code 0; status sidecar: `fable-02-compiler-topology-runtime-contracts-review.md.status`. |
| 2026-07-03 | Fable 03 planning-state/JSONB | [`fable-03-planning-state-jsonb-scale-prompt.md`](fable-03-planning-state-jsonb-scale-prompt.md) | Complete | Max-effort Fable prompt for planning state, JSONB, and 50k-user scale. |
| 2026-07-03 | Fable 03 planning-state/JSONB | [`fable-03-planning-state-jsonb-scale-review.md`](fable-03-planning-state-jsonb-scale-review.md) | Raw Fable complete | Exit code 0; status sidecar: `fable-03-planning-state-jsonb-scale-review.md.status`. |
| 2026-07-03 | Fable 04 discovery/attachments/dialog cadence | [`fable-04-discovery-attachments-dialog-prompt.md`](fable-04-discovery-attachments-dialog-prompt.md) | Complete | Max-effort Fable prompt for discovery, attachments, and dialog cadence. |
| 2026-07-03 | Fable 04 discovery/attachments/dialog cadence | [`fable-04-discovery-attachments-dialog-review.md`](fable-04-discovery-attachments-dialog-review.md) | Raw Fable complete | Exit code 0; status sidecar: `fable-04-discovery-attachments-dialog-review.md.status`. |
| 2026-07-03 | Fable 05 API consumer DX | [`fable-05-flow-api-consumer-dx-prompt.md`](fable-05-flow-api-consumer-dx-prompt.md) | Prompt ready | Max-effort Fable prompt for public API, endpoint contracts, generated client, and API maintainer DX. |
| 2026-07-03 | Fable 05 API consumer DX | [`fable-05-flow-api-consumer-dx-review.md`](fable-05-flow-api-consumer-dx-review.md) | Quota-limited | Fable exited code 1 with saved message: monthly spend limit reached. Retry this prompt after reset. Status sidecar: `fable-05-flow-api-consumer-dx-review.md.status`. |
| 2026-07-03 | Fable 06 operational runtime reliability | [`fable-06-operational-runtime-reliability-prompt.md`](fable-06-operational-runtime-reliability-prompt.md) | Prompt ready | Max-effort Fable prompt for runtime lifecycle, idempotency, crash recovery, outbox, retention, and observability. |
| 2026-07-03 | Fable 06 operational runtime reliability | [`fable-06-operational-runtime-reliability-review.md`](fable-06-operational-runtime-reliability-review.md) | Quota-limited | Fable exited code 1 with saved message: monthly spend limit reached. Retry this prompt after reset. Status sidecar: `fable-06-operational-runtime-reliability-review.md.status`. |
| 2026-07-03 | Fable 06 v2 runtime reliability + runtime ownership | [`peer-loop-fable-06-plan-brief.md`](peer-loop-fable-06-plan-brief.md) | Peer-reviewed | Claude peer-loop iteration 1 required narrowing; iteration 2 returned green for the revised prompt under the user's 05-08 framing. |
| 2026-07-03 | Fable 06 v2 runtime reliability + runtime ownership | [`fable-06-operational-runtime-reliability-maintainability-prompt.md`](fable-06-operational-runtime-reliability-maintainability-prompt.md) | Complete | Narrowed max-effort Fable prompt for runtime reliability, crash recovery, leases/attempts/claims, outbox/dead-letter, and runtime-coupled ownership. |
| 2026-07-03 | Fable 06 v2 runtime reliability + runtime ownership | [`fable-06-operational-runtime-reliability-maintainability-review.md`](fable-06-operational-runtime-reliability-maintainability-review.md) | Raw Fable complete | Exit code 0; status sidecar: `fable-06-operational-runtime-reliability-maintainability-review.md.status`. Main confirmed P0: stale-RUNNING reconciliation lacks transaction/commit under `autobegin=False`. |
| 2026-07-03 | Codex verification of Fable 06 v2 | [`codex-verify-fable-06-runtime-prompt.md`](codex-verify-fable-06-runtime-prompt.md) | Complete | GPT-5.5 xhigh verification prompt; explicitly forbids Claude/Fable/peer-loop/subagents and source edits. |
| 2026-07-03 | Codex verification of Fable 06 v2 | [`codex-verify-fable-06-runtime-report.md`](codex-verify-fable-06-runtime-report.md) | Verified | GPT-5.5 xhigh verified Fable's P0 and most high-priority runtime findings; status sidecar: `codex-verify-fable-06-runtime-report.status`. |
| 2026-07-03 | Fable 07 evidence/legal transparency | [`fable-07-evidence-legal-transparency-prompt.md`](fable-07-evidence-legal-transparency-prompt.md) | Prompt ready | Max-effort Fable prompt for legally defensible run evidence, prompt/model/RAG/file provenance, and export manifest gaps. |
| 2026-07-03 | Fable 07 evidence/legal transparency | [`fable-07-evidence-legal-transparency-review.md`](fable-07-evidence-legal-transparency-review.md) | Quota-limited | Fable exited code 1 with saved message: monthly spend limit reached. Retry this prompt after reset. Status sidecar: `fable-07-evidence-legal-transparency-review.md.status`. |
| 2026-07-03 | Fable 07 v2 evidence/legal transparency | [`peer-loop-fable-07-plan-brief.md`](peer-loop-fable-07-plan-brief.md) | Peer-reviewed | Claude peer-loop iteration 1 required trimming; iteration 2 returned green for the revised prompt under the user's 07/05/08 preference. |
| 2026-07-03 | Fable 07 v2 evidence/legal transparency | [`fable-07-evidence-legal-transparency-v2-prompt.md`](fable-07-evidence-legal-transparency-v2-prompt.md) | Complete | Trimmed max-effort Fable prompt for disclosure inventory, evidence/export owner reconciliation, capture traceability, retention/purge honesty, and missing red tests. |
| 2026-07-03 | Fable 07 v2 evidence/legal transparency | [`fable-07-evidence-legal-transparency-v2-review.md`](fable-07-evidence-legal-transparency-v2-review.md) | Raw Fable complete | Exit code 0; status sidecar: `fable-07-evidence-legal-transparency-v2-review.md.status`. Main finding: rerun destroys full superseded evidence while attempts keep only previews. |
| 2026-07-03 | Codex verification of Fable 07 v2 | [`codex-verify-fable-07-evidence-prompt.md`](codex-verify-fable-07-evidence-prompt.md) | Complete | GPT-5.5 xhigh verification prompt; explicitly forbids Claude/Fable/peer-loop/subagents and source edits. |
| 2026-07-03 | Codex verification of Fable 07 v2 | [`codex-verify-fable-07-evidence-report.md`](codex-verify-fable-07-evidence-report.md) | Verified | GPT-5.5 xhigh verified Fable's main legal/disclosure blockers and implementation backlog; status sidecar: `codex-verify-fable-07-evidence-report.status`. |
| 2026-07-03 | Fable 08 dead-code/deletion audit | [`fable-08-dead-code-deletion-audit-prompt.md`](fable-08-dead-code-deletion-audit-prompt.md) | Prompt ready | Max-effort Fable prompt for dead code, compatibility paths, squashable migrations, accidental tests, and Ponytail deletion candidates. |
| 2026-07-03 | Fable 08 dead-code/deletion audit | [`fable-08-dead-code-deletion-audit-review.md`](fable-08-dead-code-deletion-audit-review.md) | Quota-limited | Fable exited code 1 with saved message: monthly spend limit reached. Retry this prompt only after deterministic dead-code/migration inventory. Status sidecar: `fable-08-dead-code-deletion-audit-review.md.status`. |
| 2026-07-03 | Additional target scout | [`agent-additional-fable-targets-review.md`](agent-additional-fable-targets-review.md) | Complete | GPT-5.5 xhigh subagent recommended security/tenant boundaries as the highest-value non-overlapping additional Fable pass. |
| 2026-07-03 | Fable 09 security/tenant boundaries | [`fable-09-security-tenant-boundary-prompt.md`](fable-09-security-tenant-boundary-prompt.md) | Prompt ready | Max-effort Fable prompt for Flow authorization, service/API keys, tenant/space isolation, evidence access, and error confidentiality. |
| 2026-07-03 | Fable 09 security/tenant boundaries | [`fable-09-security-tenant-boundary-review.md`](fable-09-security-tenant-boundary-review.md) | Quota-limited | Fable exited code 1 with saved message: monthly spend limit reached. Retry this prompt after reset. Status sidecar: `fable-09-security-tenant-boundary-review.md.status`. |

## Verified Runtime Findings To Carry Forward

| Priority | Finding | Carry-forward implication for AI Builder review |
|---|---|---|
| P0/P1 | RAG retrieval uses the full composed `prepared.step_input.text` as the semantic query. | Ask Fable whether Builder should produce an explicit retrieval/query contract instead of relying on runtime composed prompt text. |
| P1 | File/audio/document `flow_input` can compile to `{{ step_input.text }}` while runs/reruns can reach runtime without files. | Ask Fable to inspect Builder's primary input, attachment, and runtime-input requirements as one contract. |
| P1 | Manual/UI binding validation is weaker than Builder validation. | Ask Fable where the canonical validation owner should live so Builder and manual authoring cannot drift. |
| P1 | Builder accepts array item field paths runtime interpolation rejects. | Ask Fable to review JSON path semantics and whether Builder should force runtime-valid concrete paths. |
| P2 | `INTENTIONAL_PARTIAL` underlag can silently preserve too-narrow source material. | Ask Fable to inspect source-material completion and question/dialog behavior for missing-detail risk. |
| P2 | Whole-plan edits can leave stale literal `step_N` aliases. | Ask Fable to inspect edit architecture and whether step lineage has one canonical owner. |
| P2 | `STEP_INPUT_KEY_SHAPES` drifted from runtime metadata. | Ask Fable to review static variable contracts versus runtime metadata production. |
| P2 | Structured refs into contract-less JSON steps are not fenced strongly enough. | Ask Fable to review output contract generation and downstream field reference policy. |

## Current Question For Fable

What is the cleanest long-term Flow AI Builder architecture if we were designing
from the current learnings, while keeping the implementation path reviewable?

The review should answer:

- How should the conversation loop decide whether to ask another question,
  summarize, or propose a plan?
- Which module should own user intent, attachment/file semantics, source
  material, runtime input, JSON output contracts, and step reference lineage?
- What Builder modules are shallow, duplicated, or only exist because the
  current design accreted guardrails?
- What can be deleted because Flow AI Builder is not yet production and does
  not need legacy compatibility?
- Which data model / JSONB contracts create future technical debt?
- What small implementation slices should be done first tomorrow?
