# ChatGPT Pro Strategy Integration

Date: 2026-06-29

## TL;DR

1. ChatGPT Pro's review was accepted as strategic roadmap guidance, not source-level verification.
2. The roadmap is the canonical plan; the Decision Register is the single source of truth for policy gates.
3. The integration added missing release gates for Builder, PG-10b/API DX, runtime/load proof, migration/JSONB policy, and Builder reliability.
4. The missed Builder audit-vocabulary cleanup is now tracked as a delete-or-wire decision.
5. No source code was changed from this review; implementation remains in PG slices or later architecture tracks.

## Canonical Ownership

Use this file only as a trace map from ChatGPT Pro's recommendations to the roadmap. If a row here conflicts with the roadmap, update `review-artifacts/flows-9-10-architecture-roadmap-2026-06-29.md`; do not treat this ledger as a second roadmap.

| Owner | Responsibility |
|---|---|
| Roadmap | Sequencing, tracks, acceptance criteria, stop rules, and post-PG scoring. |
| Decision Register inside the roadmap | Builder ship/no-ship, PG-10b, migration policy, JSONB corruption behavior, evidence export strategy, Builder retention, audit vocabulary, security/API/runtime policy gates, and what to do while each is undecided. |
| Current status digest | Short current-state input for outside reviewers. |
| This file | Traceability only: what ChatGPT Pro raised and where it landed. |

## Integrated Trace Map

| ChatGPT Pro item | Roadmap result |
|---|---|
| Builder ship/no-ship must be the first gate. | Accepted in Gate 0 and the Decision Register. Builder-conditional PG work stops until the answer is yes/no; if no, backend routes/settings must be gated. |
| Flows proper can reach 9/10 conditionally, but not 10/10 without staging/load/crash/eval evidence. | Accepted in Current Reality, Quality Ladder, and Phase D. 10/10 requires production-like evidence, not only fixed findings. |
| Flow AI Builder cannot reach 9/10 from PG alone. | Accepted in Current Reality and C8. Builder needs a dedicated control-plane/eval/telemetry simplification track if it ships. |
| API DX needs global 422/`GeneralError`, typed evidence export, generated-client conformance, and documented journeys. | Accepted in C2 and the Decision Register. PG-10b remains a separate app-global decision before claiming API DX 9/10. |
| Data/schema quality needs migration policy, JSONB corruption behavior, schema/version owners, constraints, and index evidence. | Accepted in C4 and the Decision Register. JSONB must have typed owners and corruption behavior before 9/10 claims. |
| Do not relationalize every JSONB field by default. | Accepted in C4. Relationalization now requires identity, lifecycle, FK, query/index, retention/audit, or authorization semantics. |
| Runtime robustness needs crash/timeout/cancel/queue/starvation/load proof. | Accepted in C1, Phase D, and the Decision Register. Queue separation waits for saturation proof rather than speculation. |
| Runtime needs operator-useful dead-letter observability. | Accepted in C1 and the observability failure-event Decision Register row. |
| Whole-product E2E must prove browser -> API -> Celery -> status -> result/evidence and, where feasible, webhook. | Accepted in C1, C2, C7, and Phase D. PG-9 smoke is useful but not enough for full release confidence. |
| Unit tests and docs coverage are insufficient release proof. | Accepted in Phase A, C2, C7, and Phase D. Docs/catalog checks remain necessary but cannot substitute for contract/runtime journeys. |
| Capability descriptors, MCP, broad `FlowService` splits, and proposal-family collapse should wait. | Accepted in Phase A and Stop Rules. They need evidence, a real external boundary, or named duplicate-owner deletion. |
| Source-shape AST guards and implementation-call-order tests should not accumulate. | Accepted in C7 and Stop Rules. Cross-stack/docs assertions move to contract/integration tiers where they own those dependencies. |
| Builder structured-question answer drops are release-blocking if Builder ships. | Accepted in C8. Architecture-driving structured answers must be ingested or fail explicitly. |
| Builder truncation should produce a typed provider-boundary error before repair. | Accepted in C8 and the Decision Register. `finish_reason == "length"` cannot silently burn the generic repair loop. |
| Builder failed proposal turns need terminal telemetry before repair pruning. | Accepted in C8 and the Decision Register. Repair attempts, LLM calls, token usage, final failure kind, and request/session ids must be available before deleting or preserving fallback branches. |
| Builder materialization needs deterministic eval coverage if Builder ships. | Accepted in C8. Goldens must pass through materialization, not only preflight/critic fences. |
| Builder sessions/plans need retention/deletion policy if Builder ships. | Accepted in C8 and the Decision Register. Stored conversations, plans, and telemetry are user data. |
| Builder edit/revise intent should not fall into undifferentiated self-correction failure. | Accepted in C8. Recognized edits must route to typed revision, clarification/notice, or edit-aware terminal error. |
| Dead Builder audit vocabulary should be deleted or wired. | Accepted in C8 and the Decision Register. `AI_BUILDER_PLAN_REJECTED` is tracked as likely dead; `AI_BUILDER_PLAN_PROPOSED` must either be emitted by a real lifecycle transition or deleted. |
| Webhook JSON mirror should be deleted after safety checks. | Already carried in the duplication map and PG-11 staging. Relational delivery state is the intended owner. |
| Raw evidence export, run-history filtering, signed URL expiry, evidence summary, migration policy, JSONB corruption, tenant-admin carve-out, and Builder feature-gate questions need explicit decisions. | Accepted in the Decision Register with `While undecided` behavior. |
| Frontend Flow/Builder i18n should consolidate instead of carrying feature-local dictionaries. | Accepted in C6. Release-facing localized strings should come from the project i18n owner. |
| Re-score after current work rather than assuming PG gives 9/10. | Accepted in Operating Strategy, Quality Ladder, Phase B, and Phase D. |

## Deliberate Non-Changes

| Area | Reason |
|---|---|
| Source implementation | ChatGPT Pro's review was strategic and narrative-based; it did not provide source-level implementation instructions. |
| Per-step Space hydration | Already completed by PG-7 according to the status digest; no duplicate roadmap work added. |
| Capability descriptors / MCP | Deferred until a real external boundary or named duplicate-owner deletion justifies the concept. |
| Mass JSONB relationalization | Rejected as a default strategy; C4 now defines when relational migration is worth doing. |
| Builder proposal-family collapse | Deferred until telemetry and deterministic eval/materialization proof distinguish real concepts from repair-path debt. |
| Carried high-severity claims | The roadmap records them as execution-time verification work, not as unverified proof against HEAD. Each implementation slice must re-check source evidence before editing. |

## Next Use

Use this file when checking whether ChatGPT Pro's review was integrated without omission. Use the roadmap itself when prompting implementation agents.
