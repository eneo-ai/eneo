# Phase 5 AGENTS.md Additions Proposal

TL;DR:
1. These additions are proposal-only; `AGENTS.md` was not edited.
2. They translate this review into persistent working rules for future Flow and AI Builder work.
3. The additions emphasize canonical homes, deletion gates, runtime lifecycle, generated types, and API contracts.
4. They explicitly distinguish pre-production breaking API changes from persisted row-shape migrations.
5. They should be merged only after team review.

## Proposed Section: Flow Canonical Homes

| Concept | Canonical Home | Notes |
|---|---|---|
| Flow status lifecycle | Backend status enum plus lifecycle projection module | DB constraints, repos, frontend helpers, and generated types must derive or parity-test against it. |
| Published flow definition | Versioned published definition parser/writer | `definition_json` is a serialized snapshot, not the only contract owner. |
| Runtime terminalization | One lifecycle/terminalization command | Completion, failure, cancellation, timeout, dispatch failure, and reconciliation use the same invariant. |
| Flow access policy | `FlowPrincipal` plus typed policy actions | No flow/AI Builder route reads raw `Request.state.api_key_scope_*`. |
| Runtime file mapping | `step_inputs` request schema plus runtime resolver | Top-level `file_ids` is deprecated and should not be reintroduced. |
| Evidence/provenance | Typed evidence/provenance/redaction modules | Arbitrary model output remains free-form behind named boundaries. |
| API schemas | Backend Pydantic/OpenAPI source plus generated TypeScript | Handwritten frontend Flow API types are UI-only or aliases. |
| AI Builder prompt/plan contract | AI Builder prompt contract and concrete API/domain/event models | Prompt behavior is a runtime contract, not incidental text. |
| Frontend workflow state | One owner per workflow | Driver/Service/component mirroring is forbidden. |
| Observability | Lifecycle owner plus typed recorder | No generic observability manager. |

## Proposed Section: Pre-Production Compatibility Policy

Breaking API and schema changes are allowed before production, but compatibility deletion still has two categories:

- Source/API compatibility: break deliberately, update OpenAPI, generated client, docs, examples, and contract tests in the same implementation slice.
- Persisted row-shape compatibility: backfill or prove zero rows before deleting fallback code.

Do not preserve two public request shapes "temporarily" without owner, telemetry/check, and deletion date. Do not delete persisted-shape fallbacks solely because production has not launched.

## Proposed Section: Flow Runtime Rules

- Runtime state belongs in the database, not worker memory.
- Celery tasks receive small typed command payloads.
- Duplicate task starts must be idempotent.
- Terminalization must close run, step results, open attempts, audit/outbox, and observability through one owner.
- Human review must checkpoint, persist next pointer/revision, exit the worker task, and resume through a fresh dispatch.
- Step rerun invalidation must traverse `flow_step_dependencies`; do not invalidate by ordinal order.
- Redispatch is stale queued recovery, not rerun/resume/retry.
- Every new status must update enum/lifecycle projection, DB constraint/migration, API schema, frontend generated types, reconciliation, and tests.

## Proposed Section: Flow API Rules

- Routers are HTTP adapters.
- Leaf routers own endpoint path, operation ID, request model, response model, status codes, error examples, permission action, idempotency, and generated-client impact.
- Aggregator routers should include routers only, not re-export endpoint callables.
- Public list endpoints must expose `has_more` or `total_count` unless explicitly non-paginated.
- Flow-specific OpenAPI issues should be fixed at endpoint/model source, not patched globally.
- Evidence export must choose JSON API, attachment download, or two endpoints and align OpenAPI with runtime behavior.
- Mutating endpoints need an idempotency story or explicit reason they do not.

## Proposed Section: Flow Data Model Rules

- New JSONB fields require owner, parser, schema version, validation boundary, migration strategy, corruption behavior, and tests.
- Do not create first-class tables for run-local facts unless an ADR proves queryability, row-level lifecycle, retention, authorization, audit, or FK integrity needs.
- Principal identity should use canonical `FlowPrincipal` columns; legacy identity fields need migration or historical-only status.
- Permission migrations must map old assignments to new actions without silently expanding review/resume/rerun powers.
- Migration PRs must include preflight/zero-row queries and rollback/recovery notes.

## Proposed Section: Flow Frontend Rules

- Generated OpenAPI types are the source of API truth once PRD-004 lands.
- `resources.d.ts` may export ergonomic aliases but should not manually redefine Flow runtime/API contracts.
- No new `any`, `as any`, `@ts-ignore`, or `@ts-expect-error` in Flow frontend code without a named issue and deletion condition.
- One mutable owner per workflow: AI Builder session, Flow authoring, run launch, run history, evidence, and status presentation.
- Driver/Service splits are allowed only if one side is stateless transport/parser or a pure reducer.
- Do not render pause/rerun/review UI controls until backend lifecycle states and generated types exist.

## Proposed Section: AI Builder Rules

- Treat prompts, knowledge-pack text, plan/spec/envelope models, materialization, repair, and event streams as contracts.
- Preserve active LLM repair behavior unless replacement tests prove it is stale.
- Split AI Builder code by lifecycle responsibility, not by generic helper/service layers.
- The router owns HTTP/SSE adaptation only; planner/proposal/session services own business behavior.
- AI Builder permission checks must use Flow policy and explicit session action rules.

## Proposed Section: Testing Rules

- Add behavior/contract tests before deleting or reshaping public contracts.
- Prefer HTTP/API and DB-backed runtime tests for cross-layer behavior.
- Keep unit tests for pure logic and small state machines.
- Delete tests that only preserve import shim identity or compatibility behavior after replacement contract tests exist.
- Do not add speculative tests for pause/rerun before the lifecycle/data contract exists.
- Frontend journey tests should cover AI Builder apply-to-flow and runtime launch/evidence, but keep E2E minimal.

## Proposed Section: Comment And Readability Rules

- Comments should explain why, not what.
- Compatibility comments must include owner, deletion condition, and expected removal point.
- "Temporary" comments without owner and removal condition are defects.
- Prefer naming/extraction/value objects over comments that compensate for unclear code.
- Do not split large files mechanically; split by lifecycle phase, canonical ownership, or interface depth.

## Human Maintainability PR Checklist

Before opening a PR, answer:

- [ ] Does this change have one clear responsibility?
- [ ] Is the canonical home for each touched concept clear?
- [ ] Did I avoid adding a parallel implementation?
- [ ] Did I avoid `Any` / `dict[str, Any]` in domain/application code?
- [ ] Did I avoid new fake seams or one-implementation interfaces?
- [ ] Did I keep routers thin?
- [ ] Did I keep domain logic out of HTTP/persistence adapters?
- [ ] Did I use typed value objects/schemas at boundaries?
- [ ] Did I avoid comments that restate code?
- [ ] Did I add or update behavior-focused tests?
- [ ] Would a new senior engineer understand this file in week one?
- [ ] If this changes an API, is the OpenAPI/SDK impact clear?
- [ ] If this changes runtime behavior, is idempotency / crash recovery clear?
- [ ] If this changes data shape, is migration / versioning clear?

## ADR Triggers

Write an ADR before:

- changing status lifecycle semantics
- changing terminal audit fail policy
- adding a runtime checkpoint/review state
- adding step rerun semantics
- adding first-class runtime input/artifact tables
- changing generated-client source-of-truth strategy
- changing permission action mapping
- preserving a compatibility path longer than one implementation slice
- introducing a new interface/port with one implementation
