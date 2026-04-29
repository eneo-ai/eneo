# Phase 7 Implementation-Readiness Index

## TL;DR

Phase 7 is the final review-and-plan hardening pass before implementation.
It is scoped only to Flow / Flow AI Builder.
It makes deletion, Celery runtime, JSONB/relational modeling, behavior pins, file splitting, and Claude reconciliation executable.
It does not modify source, tests, migrations, generated clients, package files, git, branches, commits, pushes, or PRs.
Use `implementation-readiness.md` as the readiness gate. The durable implementation handoff now lives at `docs/refactor/execution/implementation-bootstrap.md`.

## Documents

| Path | Purpose |
|---|---|
| `implementation-readiness.md` | Stop/go gate, readiness summary, risks, final implementation order. |
| `data-model-scalability-stress-test.md` | JSONB vs relational decisions and scalability edge cases. |
| `dead-tests-cleanup.md` | Test deletion/rewrite/keep inventory for Flow / AI Builder tests. |
| `comment-cleanup.md` | Executable comment classification and cleanup inventory. |
| `edge-cases-and-leakage.md` | Boundary leakage and edge-case audit. |
| `do-not-split.md` | Responsibility-based split candidates and do-not-split list. |
| `claude-reconciliation.md` | Accepted/rejected/partial reconciliation of Claude attacks. |
| `disagreements.md` | Remaining load-bearing disagreements, if any. |
| `claude/README.md` | Claude packet index. |

## Implementation Handoff

| Path | Purpose |
|---|---|
| `../execution/implementation-bootstrap.md` | Handoff brief and ready-to-paste Batch 0 starter prompts. |

## Implementation Gate

The gate is `GO WITH RISKS`.

Implementation may start with Batch 0 only if the implementation agent reads the bootstrap inputs and starts with behavior pins before destructive cleanup.

## Phase 7 Rules

- Celery is the Flow / Flow AI Builder runtime.
- ARQ is not a Flow / Flow AI Builder runtime option.
- Source-only false owners are early deletion candidates.
- Persisted/public readers need behavior pin, count proof, and backfill/rewrite if rows exist.
- JSONB requires a parser/version/corruption plan.
- Relational owners are required for lifecycle, file-reference, rerun, review, and audit/outbox facts.
- Large files split only by domain/lifecycle responsibility, never by size alone.
