# ChatGPT Pro Review Packet - Eneo Flows / Flow AI Builder Current 9/10 Path

Date: 2026-07-01

## Five-Line TL;DR

1. This is a compact delta packet after the 2026-06-30 ChatGPT Pro packet, not a second roadmap.
2. The implementation baseline reviewed here is `14a3c5cb docs(ai-builder): record repair fallback branch decisions` on `refactor/flows-clean`; this packet may live in a later docs-only commit.
3. Flows proper has improved, but is still roughly 7.5-8/10; Flow AI Builder is roughly 6/10. Nothing should be described as 9/10 or 9.5/10 yet.
4. C9.5 found no safe real or production-like branch-value dataset for Builder repair/fallback pruning, so no repair/fallback source was pruned and no docs commit was made for C9.5.
5. Please decide the next highest-ROI bounded path to real 9/10 maintainability, not the most optimistic or broadest refactor.

## Reading Order

1. This packet.
2. `review-artifacts/flows-9-10-architecture-roadmap-2026-06-29.md`
3. `review-artifacts/implementation-progress-2026-06-29.md`
4. `review-artifacts/flow-builder-release-governance-packet-2026-06-30.md`
5. `review-artifacts/flow-builder-release-governance-gate0-2026-06-30.md`
6. `review-artifacts/chatgpt-pro-review-packet-2026-06-30.md`
7. `review-artifacts/chatgpt-pro-strategy-integration-2026-06-29.md`

## What Changed Since The 2026-06-30 Packet

| Slice | Commit / result | What changed | What did not change |
|---|---|---|---|
| C9.0 Gate 0 | `4dd0f193 docs(ai-builder): refresh release governance gate 0` | Refreshed Builder lifecycle, retention, audit, JSONB ownership, migration, and file-reference evidence. | No source/test/runtime/API behavior changed. |
| C9.1 Gate 1 | `9b6da3cb docs(ai-builder): refresh release governance gate 1` | Selected `DataRetentionService` as the active abandoned-session retention owner. | No new Builder retention service, lifecycle manager, file cleaner, or MCP/capability path. |
| C9.2 retention | `e43f12ff fix(ai-builder): expire abandoned active sessions` | Old abandoned `chatting` / `awaiting_approval` Builder sessions now expire through existing hierarchical retention while fresh send leases are protected. | Global `Files` rows are still not deleted by Builder retention. |
| C9.3 file posture | `2ea8ea12 docs(ai-builder): record global file retention posture` | Accepted retained Builder-uploaded global `Files` rows for first release after session pins are removed. | This does not claim files are deleted, anonymized, or privacy-complete. |
| C9.4 repair/fallback | `14a3c5cb docs(ai-builder): record repair fallback branch decisions` | Recorded branch-family keep/blocked decisions. No branch is delete-ready from source/test/golden evidence alone. | No repair/fallback branch was pruned. No telemetry/eval framework was added. |
| C9.5 branch-value review | No commit | Searched available local/log/artifact sources for real branch-value data and stopped no-data. | No docs/source/test/runtime/API changes; no branch-value conclusion beyond "no usable dataset found." |

## Honest Current Rating

| Area | Honest current rating | Why it is not 9/10 yet |
|---|---:|---|
| Flows proper | 7.5-8/10 | Runtime/API/schema work has improved, but PG-10b global validation envelope, JSONB corruption policy, generated-client conformance, load/crash proof, and full journey CI evidence still gate 9/10. |
| Flow AI Builder | ~6/10 | Retention/audit/lifecycle/structured-question cleanup improved the base, but the control plane is still large, repair/fallback value is unmeasured, provider-boundary failures and deterministic eval coverage remain incomplete, and broader simplification is not proven. |
| API consumer DX | ~7/10 | Flow-local error cleanup landed, but app-global FastAPI 422 shape, generated-client compatibility, evidence export typed-summary deletion/parity, and documented external journey proof remain open. |
| Data/schema/JSONB | ~7/10 | Some schema hardening landed, but every Flow/Builder JSONB owner still needs explicit corruption behavior, migration policy, validation boundary, and tests before 9/10. |
| Runtime reliability | ~7.5/10 | Several runtime correctness slices landed, but production-like crash/load/queue/starvation/outbox proof and operator-useful observability remain incomplete. |
| Test/release confidence | ~7/10 | Focused unit/integration/browser smoke coverage improved, but CI still needs a full browser -> API -> Celery -> status -> result/evidence/webhook journey plus contract tests. |

## Key Facts ChatGPT Pro Should Not Overread

- C9.5 no-data means no usable local/staging/production-like branch-value artifact was found. It does not prove repair/fallback branches have no product value.
- C9.4 already records the durable repair/fallback decision: keep or block pruning until real branch-value data exists.
- C9.3 accepts retained Builder-uploaded global `Files` rows for first release only. It does not solve file/blob privacy or deletion generally.
- Flow AI Builder remains native Eneo authoring. Do not recommend rebuilding it as an internal MCP client.
- Capability/MCP work is future external-adapter work only after canonical Eneo command/services are clean; it is not a cleanup shortcut.
- Flows and Flow AI Builder are pre-production, so dead unreleased compatibility and tests for removed behavior should be deleted when evidence proves safety.

## Open Decisions For ChatGPT Pro

Please answer as decisions, not discussion.

1. With no real Builder branch-value artifacts found, should first release accept the current repair/fallback branches, require a controlled live-eval/staging run before release, or defer Builder release?
2. Is the C9.3 retained global `Files` row posture acceptable for first release? If not, what exact owner, candidate-id source, reference guard, and tests should drive cleanup?
3. What is the next highest-ROI bounded slice: PG-10b global `GeneralError`/422 contract, post-PG no-code scorecard, Builder no-data release acceptance, JSONB/corruption policy, runtime/load proof, or something else?
4. What exact evidence would raise Flows proper from 7.5-8/10 to 9/10 across API, data/schema, runtime, tests, generated-client DX, and operability?
5. Is Flow AI Builder realistically on a pre-production path to 8/10 or 9/10, and what should be deleted, merged, measured, or explicitly deferred before any broad redesign?
6. Should PG-10b standardize app-global FastAPI 422 errors to `GeneralError` before production, and what generated-client/non-Flow compatibility checks are required first?
7. Which Flow/Builder JSONB owners must get typed schema/version/corruption behavior before production, and which should remain JSONB rather than relationalized?
8. Which tests now protect old behavior, implementation shape, or removed compatibility and should be deleted or replaced?
9. Which remaining fake seams, pass-through modules, or duplicate owners should be deleted before any large-file splitting?
10. What should be the first "stop and re-score" point before claiming the system is 9/10?

## Recommended Next Five Bounded Slices To Challenge

These are not instructions to execute blindly. Please reorder, reject, or replace them.

| Rank | Candidate slice | Owner | Acceptance criteria | Stop condition |
|---|---|---|---|---|
| 1 | Post-C9 ChatGPT Pro decision integration | Roadmap/docs only | Integrate your decisions into the roadmap decision register without source changes. | If decisions are ambiguous or too broad. |
| 2 | PG-10b app-global validation error contract | API/generated-client owner | Decide and implement `RequestValidationError` -> `GeneralError` only with generated-client/non-Flow impact tests. | If generated-client or non-Flow API compatibility cannot be assessed. |
| 3 | Builder repair/fallback release posture | Flow AI Builder owner | Either accept current branches for first release with explicit risk, or name a concrete data source/live-eval run. | If no product decision and no data source exist. |
| 4 | JSONB corruption behavior scorecard | Flow runtime/data owner | Inventory the highest-risk Flow/Builder JSONB owners and choose reject-before-write, degrade-on-read, or hard-fail policy per owner. | If the slice drifts into broad JSONB relationalization. |
| 5 | Runtime/load/operator proof | Runtime/deploy owner | Add or specify the smallest production-like proof for crash/load/queue/dead-letter behavior. | If it becomes speculative queue splitting or observability framework work. |

## What Not To Do

- Do not start MCP/capability implementation to hide unresolved Builder internals.
- Do not add broad telemetry/eval frameworks solely because C9.5 found no branch-value data.
- Do not prune Builder repair/fallback branches from unit/static evidence alone.
- Do not add `AIBuilderRetentionService`, generic lifecycle manager, command bus, event-sourcing layer, generic file cleaner, or one-implementation interface.
- Do not split large Builder files by line count before deleting/merging named duplicate owners.
- Do not claim API consumer DX is 9/10 until app-global validation errors, generated-client contracts, evidence export shape, and external journey docs/tests are settled.
- Do not claim runtime is 9/10 without crash/load/queue/dead-letter/operator proof.
- Do not preserve unreleased Flow/Builder compatibility paths or tests after the behavior is deleted.

## Requested Output From ChatGPT Pro

1. Five-line executive verdict.
2. Updated scorecard for Flows proper and Flow AI Builder across maintainability, clean architecture, API consumer DX, data/schema, runtime, tests, and release readiness.
3. Top 10 release blockers ranked by severity and confidence.
4. Top 10 delete/simplify/merge/move opportunities, with functionality that must be preserved.
5. Clear answers to the open decisions above.
6. Recommended next five implementation slices with scope, owner, acceptance criteria, tests, and stop conditions.
7. What not to do because it would create fake architecture or technical debt.
8. Likely false positives or overstatements in this roadmap.
9. Whether the current path can honestly reach 9/10 before production, and what evidence would make that credible.
