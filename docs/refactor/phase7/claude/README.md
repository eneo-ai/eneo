# Phase 7 Claude Packet Reviews

## TL;DR

Claude was used as an adversarial reviewer, not as source of truth.
Responses are preserved verbatim in this directory.
Codex verified attacks against repository evidence before updating the plan.
Inventory packets 6 and 7 were single-round by design.
Load-bearing packet disagreements are reconciled in `../claude-reconciliation.md`.

## Packet Index

| Packet | File | Purpose |
|---|---|---|
| 1 | `01-pre-production-deletion-policy.md` | Deletion policy and kill-list approach. |
| 2 | `02-dead-test-cleanup.md` | Dead test cleanup approach. |
| 3 | `03-runtime-io-data-model.md` | Runtime input/output data model, file mapping, top-level `file_ids`, rerun lifecycle. |
| 4 | `04-celery-lifecycle-terminalization.md` | Celery lifecycle, pause/edit/resume, terminalization, audit/outbox. |
| 5 | `05-typed-flow-policy-actions.md` | Typed Flow policy actions and enforcement point. |
| 6 | `06-jsonb-relational-inventory.md` | JSONB vs relational modeling decisions. |
| 7 | `07-behavior-pins.md` | Behavior pins before destructive cleanup. |
| 8 | `08-final-green-light.md` | Final consolidated Phase 7 green-light review. |

## Review Rule

Claude attacks changed the plan only when they identified concrete repository evidence, a missing evidence check, a specific failure mode, or a concrete maintainability/reliability improvement. Speculative attacks are recorded but do not bend the plan.
