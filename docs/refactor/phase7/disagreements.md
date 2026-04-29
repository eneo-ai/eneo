# Phase 7 Load-Bearing Disagreements

## TL;DR

No unresolved load-bearing disagreement remains after Phase 7 reconciliation.
Claude's concrete attacks were accepted or partially accepted and folded into the PRDs and Phase 7 inventories.
Rejected attacks were rejected because they were speculative, contradicted repository evidence, or would preserve long-term debt.
The remaining items are implementation risks with recommended defaults, not architecture deadlocks.
If new evidence appears during implementation, update this file before changing the chosen design.

## Current Status

No unresolved load-bearing disagreements. Claude's final consolidated review returned `GREEN_LIGHT: YES`; the non-blocking doc fixes from that review were applied.

## Risks Carried Without Disagreement

| Decision | Codex position | Claude position | Trade-off | Recommended default | Evidence that would change the decision |
|---|---|---|---|---|---|
| Persisted/public compatibility readers | Delete/rewrite after behavior pin, count proof, and backfill if rows exist. | Claude agreed source-only and persisted/public readers need different gates. | Slower deletion for data-aware cleanup. | Keep Tier A/Tier B policy. | Count query proving zero rows lets the implementation delete faster; rows with active use require backfill. |
| Runtime file/artifact relational extraction | Relational for file refs, output files, rerun ops, review checkpoints, audit/outbox; JSONB for snapshots/blobs. | Claude agreed after adding attempt scope and output-file projection. | More schema work now, clearer lifecycle/debug later. | Use relational owners for lifecycle facts. | Evidence that these facts are never queried/audited/retried/debugged would reduce table scope. |
| Pause/edit/resume | DB state machine plus thin Celery resume task. | Claude agreed, with terminalization/outbox preconditions. | More DB design before UI, but avoids worker/broker waits. | Implement terminalization/outbox first. | A concrete existing platform human-gate abstraction with equal idempotency/audit semantics could replace this. |
| Flow audit ARQ dependency | Flow lifecycle audit must move to relational outbox; existing non-lifecycle Flow audit callers need inventory/migration/default decision before their owning route/service is refactored. | Claude agreed after final review surfaced the indirect `audit_service.log_async` ARQ path. | Slightly more Batch 3 audit scope, but avoids blessing ARQ as Flow lifecycle runtime. | Lifecycle audit must not depend on ARQ. | A platform audit replacement with the same transactional durability could replace Flow-specific outbox migration. |
