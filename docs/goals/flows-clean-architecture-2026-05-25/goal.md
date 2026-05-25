# Flows Clean Architecture

## Objective

Remove the hidden complexity that makes Flows hard to debug, change, and review: competing runtime-policy owners, inconsistent permission paths, mutable draft identity leaking into runtime history, unclear file lifecycle, non-durable side effects, and scattered step/output dispatch.

The long-term quality target remains a defensible 9/10 strict score floor, but this goal must not turn into open-ended architecture activity. Each tranche must raise the score floor by deleting or consolidating a real source of coupling, not by adding ceremony.

This goal is about **Flows proper**, not Flow AI Builder. Touch Flow AI Builder only when a Flow runtime/authoring file directly depends on a shared contract and the task explicitly permits it.

## Goal Kind

`open_ended`

## Current Tranche

Reconfirm current repo reality and implement the first safe verified Flow architecture tranche from the ChatGPT Pro review, Claude review, local schema/architecture reports, and current source evidence.

The expected first tranche is intentionally narrow:

1. Verify the claimed `FlowTemplateAssetService.upload_asset()` typed-boundary bug and Flow scope error-envelope drift against current source.
2. Use a Judge step to choose the first safe Worker task.
3. Implement one small verified slice, likely either:
   - template asset DOCX upload through a typed file-service path; or
   - Flow API scope mismatch returning the documented error envelope.
4. Record a receipt, run targeted checks, and audit whether to continue to the next queued slice.

Do not stop after planning if the first safe Worker task is clear and bounded.

## Score Ladder

Current external-review floor: `5/10`.

Target floor: `9/10`, reached through staged score floors:

| Score floor | What must be true |
|---:|---|
| 6/10 | Known normal-path bugs fixed; public Flow API errors are consistent; tests are reviewable enough to proceed. |
| 7/10 | Published runtime contract is canonical; frontend generated-contract fallbacks are removed; core API journey is contract-tested. |
| 8/10 | Webhook delivery is durable; step identity is stable; runtime file lifecycle is explicit; service-key permission matrix is coherent. |
| 9/10 | Long-term polish is done: public/lifecycle JSONB ownership is typed, health/readiness is mature, frontend state ownership is clean, and unneeded compatibility paths are deleted. |

The ladder is the implementation driver. The dimension list below is audit metadata for final scoring, not a source of new work by itself.

Overall score is the minimum dimension score, not an average.

Dimensions to track:

- Maintainability
- Code Quality
- Clean Architecture
- Separation of Concerns
- Single Source of Truth
- Human Readability
- Human Reviewability
- Data Integrity
- API Consumer DX
- API Maintainer DX
- Runtime Reliability
- Testability

## Non-Negotiable Constraints

- Stay on `feature/refactor-flows-flowai` unless the user explicitly says otherwise.
- Preserve unrelated dirty files and untracked local files.
- Do not stage, commit, push, reset, clean, or revert without explicit user request.
- Do not broaden into Flow AI Builder product behavior.
- Do not add fake interfaces, generic adapters, or future-flexibility layers.
- Do not hide typing failures with `Any`, `dict[str, Any]`, `as any`, `@ts-ignore`, pyright ignores, or broad fallback paths.
- Prefer deletion, merging, renaming, moving, and typed ownership over adding parallel paths.
- Before adding or preserving Flow logic, search for the existing owner and decide whether to reuse, extend, move, merge, delete, or create. Creating a second implementation requires a Judge-approved reason and deletion/migration path.
- Behavior changes must have behavior-focused tests.
- Mechanical test splits must not change assertions or semantics.
- Migration tasks require preflight checks for current internal data.
- Public API/Swagger/OpenAPI/generated-client-visible changes must update contract tests and generated client usage in the same tranche.
- Runtime side effects must be durable before delivery; do not patch webhook reliability with retry loops around direct delivery.
- Retention and service-key identity are architecture decisions. Do not implement them from assumptions; use Judge/product-decision tasks first.
- For every Flow runtime concept, one backend entry point must compute the truth. Documentation alone is not enough; add guard tests where a rule can decay.
- Runtime-facing code must not read mutable draft `flow.steps` after the published-contract refactor.
- Delete `/input-policy/` unless a real caller cannot use `/run-contract/`; if retained, it must be a pure projection of the published runtime contract.
- Keep step behavior and output format as separate axes. Step handlers own behavior. Output format specs own prompt instructions, native JSON-mode preference, validation/rendering requirements, and renderer selection. Output renderers are leaf adapters for byte rendering only.
- Do not create a plugin SDK, generic workflow engine, event bus, or one-implementation storage/delivery port.
- Do not normalize published steps into `flow_version_steps` unless a real relational query need appears. First make the JSON snapshot stricter: schema version, typed parser, non-null published step ids, and runtime rows copied from the snapshot.
- Repositories must not hide product decisions in SQL branches. Application/runtime services own lifecycle decisions; repositories own persistence, locks, compare-and-set writes, and queries.
- Dead Flow code, legacy compatibility paths, and obsolete tests must be deleted when evidence shows they are no longer needed.
- Duplicate or scattered Flow logic must be inventoried with all locations, behavior differences, the proposed canonical owner, and the merge/delete path. Do not leave "same but slightly different" logic in place for flexibility.
- Reuse must happen through canonical owners and small typed boundaries, not through generic helpers, managers, processors, service locators, plugin systems, event buses, god modules, or one-implementation ports.
- If a temporary parallel Flow path remains, document its owner, reason, migration/deletion trigger, and the test or preflight proving continued need.
- Every remaining Flow compatibility path must have a documented reason, owner, persisted-data evidence or caller evidence, and deletion trigger.
- Runtime compatibility preflight must include immutable published snapshots in `flow_versions.definition_json` whenever runtime behavior can depend on a published version; draft rows alone are not enough deletion evidence.
- Tests that only protect removed compatibility behavior must be removed in the same PR as the code path they protected.
- Test deletion must include line-level preservation/deletion boundaries so coverage for surviving behavior is not accidentally removed.
- When unrelated dirty/untracked files are present, deletion/consolidation Workers must verify in a clean checkout with only their own patch applied.
- Do not run repo-wide dead-code cleanup from this goal. Cleanup scope is Flows proper plus directly coupled Flow contract/frontend generated-type usage.

## Source Material

Primary local files:

- `FLOWS_FULL_DATA_SCHEMA_AND_PERMISSIONS_MAP_2026-05-25.md`
- `FLOWS_ARCHITECTURE_REVIEW_2026-05-25.md`
- `flows-clean-architecture-2026-05-25/00-master-goal.md`
- `flows-clean-architecture-2026-05-25/01-data-schema-and-ownership.md`
- `flows-clean-architecture-2026-05-25/02-runtime-reliability.md`
- `flows-clean-architecture-2026-05-25/03-api-contract-and-dx.md`
- `flows-clean-architecture-2026-05-25/04-frontend-state-and-generated-types.md`
- `flows-clean-architecture-2026-05-25/05-test-strategy.md`
- `flows-clean-architecture-2026-05-25/06-commit-roadmap.md`

Goal notes:

- `docs/goals/flows-clean-architecture-2026-05-25/notes/source-material-index.md`
- `docs/goals/flows-clean-architecture-2026-05-25/notes/roadmap-and-taskfiles.md`
- `docs/goals/flows-clean-architecture-2026-05-25/notes/step-handler-and-renderer-architecture.md`
- `docs/goals/flows-clean-architecture-2026-05-25/notes/new-codex-session-prompt.md`
- `docs/goals/flows-clean-architecture-2026-05-25/notes/peer-review-prompt-for-claude-chatgpt.md`

Engineering standards to read before non-trivial implementation:

- `AGENTS.md`
- `docs/engineering/maintainability-standards.md`
- `docs/engineering/comment-and-readability-standard.md`
- `docs/engineering/api-design-standard.md`
- `docs/engineering/testing-standard.md`
- `docs/engineering/frontend-state-standard.md`

## One Way In Rule

For each runtime concept, there must be one backend entry point that computes the truth. This is the central architecture rule for this goal.

| Concept | Canonical owner |
|---|---|
| Published runtime policy | `FlowRunContractService` / published definition |
| Runtime upload validation | Projection of the published runtime contract |
| Run creation | `FlowRunService.create_run()` using the published contract |
| Run lifecycle transitions | Terminalizer/lifecycle service, not ad hoc repository or executor branches |
| Review checkpoint transitions | One review service/state transition path |
| Rerun transitions | One rerun service with database compare-and-set behavior |
| Step behavior execution | `StepHandler` registry keyed by `output_mode` |
| Output format policy | `OutputFormatSpec` registry keyed by `output_type`; renderers are leaf adapters only |
| Webhook delivery | Flow outbound delivery outbox service |
| Evidence | `FlowRunEvidenceService` |
| Error shape | One Flow API error adapter returning `GeneralError` |
| Frontend Flow state | `FlowEditor` store/controller and generated API types |

## Reuse And Consolidation Gate

Before adding, preserving, moving, or deleting Flow logic, answer from current source evidence:

1. What existing owner already has this responsibility?
2. Can the current owner be reused as-is?
3. Can the current owner be extended or deepened with a small typed boundary?
4. Can scattered logic be moved or renamed into the owner?
5. Can duplicate paths be merged into one owner?
6. Can the weaker path be deleted?
7. If new code is still necessary, why are the existing owners insufficient?

The goal is not to create more clean-looking files that copy behavior. A Worker must reduce the number of Flow concepts, paths, branches, fallback behaviors, or places-to-debug, or explicitly justify why a temporary increase is necessary.

Every proposed Worker after T023 must include this consolidation effect:

| Field | Required answer |
|---|---|
| Reused existing owner | Existing module/service/model/contract reused or deepened. |
| Logic moved from | Old location of moved behavior, if any. |
| Logic deleted | Old branch/helper/fallback/test behavior removed, if any. |
| Duplicate path removed | Parallel path that no longer exists. |
| New code added | New module/class/function and why the owner could not absorb it directly. |
| Why existing owners were insufficient | Concrete source evidence, not preference. |
| Guard/test preventing duplicate logic from returning | Behavior test, contract test, AST/import guard, or explicit preflight. |
| Net Flow logic surface area | `reduced`, `preserved`, or `increased`; if increased, explain why. |

Use "logic surface area" qualitatively. A clean typed boundary may add lines, but it should reduce duplicated concepts, paths, branches, fallback behavior, or debugging locations.

Peer review and self review for every non-trivial task must explicitly answer:

- What existing owner did this reuse or deepen?
- What duplicate logic disappeared?
- What old path was deleted?
- What new code was added, and why were existing owners insufficient?
- What prevents this duplicate from returning?
- Is this simpler for a maintainer, or just split into more files?

## Domain Model Stance

Use DDD where it protects real invariants. Do not add DDD ceremony where it creates shallow modules or one-implementation ports.

The load-bearing aggregate split is:

| Layer | Mutable? | Owner | Rule |
|---|---|---|---|
| Draft Flow | Yes | `flows` + `flow_steps` | Authoring state only. `FlowSteps.id` is identity; `step_order` is order. |
| Published Flow Version | No | `flow_versions.definition_json` | Immutable runtime policy snapshot. It should carry `definition_schema_version` and parse through typed models. |
| Run | Lifecycle mutable, definition immutable | `flow_runs`, step results/attempts, checkpoints, files | Pinned to a published version. Runtime rows preserve published step identity and never depend on mutable draft rows for historical meaning. |

The smarter-than-strict-DDD rule for Flows is: **the published snapshot is the runtime boundary**. Runtime-facing code speaks the typed published contract, not draft ORM state.

## Debuggability And Traceability

Every production-facing runtime path should make diagnosis straightforward:

| Layer | Required traceability |
|---|---|
| API error | Stable `code`, `intric_error_code` where applicable, `context`, request/trace id, and no message-string matching. |
| Run creation | `run_id`, `trace_id`, `published_flow_version`, status, and runtime paths. |
| Worker/runtime logs | `run_id`, `trace_id`, `flow_id`, `flow_version`, `step_id`, `step_order`, `attempt_no`. |
| Step result/attempt | Published `step_id`, `step_order`, `attempt_no`, status, and error code. |
| Webhook delivery | Delivery id, run id, step id, idempotency key, status, and attempt count. |
| Evidence | Reconstructable from run + published version + result/attempt/file state. |

## Success Criteria

The goal is not complete until a Judge/PM audit verifies the strict score floor is at least 9/10. Do not chase 9/10 before the 7/8 foundations are complete. The following must be true:

- No known P0/P1 correctness bug remains on normal Flow authoring/runtime paths.
- Published runtime contract is the only owner of runtime input/upload/review/output policy.
- Published runtime contract has a typed internal model, a schema version, and corruption/version behavior.
- Runtime contract ownership is enforced by guard tests: runtime modules do not read mutable draft state after the refactor.
- Flow API error translation is enforced by guard tests: runtime/application paths do not raise raw FastAPI `HTTPException`.
- Step behavior and output-format dispatch are centralized: step handlers are keyed by `output_mode`, output format specs are keyed by `output_type`, and executor/runtime code does not reintroduce scattered string branches.
- DOCX/PDF/output format policy has one reusable truth per format. Prompt instructions, native JSON-mode preference, validation/rendering requirements, and renderer selection live in the format spec; low-level byte rendering lives in renderer/leaf modules.
- Reusable Flow logic has one canonical owner. Duplicate/scattered implementations are merged/deleted, or temporarily registered with a reason, owner, evidence, and deletion trigger.
- Runtime input files, generated artifacts, transcripts, source files, and debug evidence have explicit retention behavior.
- Service-key ownership and rotation semantics are explicit, tested, and reflected in run/file/review/evidence behavior.
- Review/rerun/cancel/service-key permissions are coherent across API action policy, run access policy, DB constraints, docs, and tests.
- Webhook/output delivery is durable with pending/delivering/delivered/retry/dead-letter state.
- Draft step identity is id-owned; `step_order` is order only.
- Runtime rows copy published `step_id`, `step_order`, and `assistant_id` where needed and are explainable from immutable published version snapshots, not mutable draft state.
- Core DB invariants are enforced where they protect normal single-tenant correctness, especially published pointer and file lifecycle constraints.
- API consumer journey is contract-tested: authenticate, inspect contract, upload files, create run, poll, fetch result/artifact/evidence, handle review/cancel/errors.
- Frontend Flow state has one owner per concept and uses generated API types as the contract source.
- Tests are reviewable and behavior-focused; large router tests are split before semantic churn.
- Confirmed dead Flow code is deleted, not left behind.
- Every remaining Flow legacy/compatibility path has an owner, reason, persisted-data or caller evidence, and deletion trigger.
- Tests for removed Flow compatibility behavior are deleted in the same PR as the removed behavior; tests for live behavior are behavior-focused rather than implementation-wiring snapshots.

## Stop Rule

Stop only when:

- the current tranche audit passes and the next required task needs owner input;
- all safe local work is blocked;
- continuing requires credentials, destructive operations, a branch operation, or product strategy not encoded in the board;
- peer review and source evidence disagree and the disagreement cannot be resolved locally.

Do not stop just because a plan exists. If a safe Worker task is active or can be activated by Judge, execute it and verify it.

## Canonical Board

Machine truth lives at:

`docs/goals/flows-clean-architecture-2026-05-25/state.yaml`

If this charter and `state.yaml` disagree, `state.yaml` wins for task status, active task, receipts, verification freshness, and completion truth.

## Run Command

```text
/goal Follow docs/goals/flows-clean-architecture-2026-05-25/goal.md through the first safe verified implementation slice. Do not stop after planning unless blocked.
```

## PM Loop

On every `/goal` continuation:

1. Read this charter.
2. Read `state.yaml`.
3. Re-check `git status --short --branch`.
4. Read the source material index and only the notes relevant to the active task.
5. Work only on the active board task.
6. Use Scout for read-only evidence, Judge for decisions, Worker for bounded implementation, and PM for board maintenance.
7. Write a compact task receipt in `state.yaml`; use `notes/` only for long receipts.
8. Run targeted verification before marking Worker tasks done.
9. Activate the next safe task unless a stop rule applies.
10. Finish only with a Judge/PM audit receipt that maps receipts and verification back to the 9/10 objective.
