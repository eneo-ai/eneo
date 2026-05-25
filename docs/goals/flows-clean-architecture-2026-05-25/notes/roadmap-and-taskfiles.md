# Roadmap And Task Files

## How To Use This Note

Use this as the human-readable roadmap. Use `state.yaml` as the machine board.

The work should remain staged as small, independently reviewable commits. Do not bundle unrelated runtime, schema, frontend, and test cleanup.

## Central Rule

For every Flow runtime concept, there must be exactly one backend entry point that computes the truth. This must be enforced with tests where it can decay:

- published runtime policy comes from the published contract;
- runtime upload validation is a projection of that contract;
- step behavior dispatch goes through one `StepHandler` registry;
- output-format policy goes through one `OutputFormatSpec` registry;
- output rendering libraries live only in leaf renderers/modules;
- public Flow API errors go through one `GeneralError` adapter;
- durable external side effects go through an outbox row, not direct post-commit delivery.

## Reuse Before Inventing

Every Flow change must start from the nearest existing owner. The preferred order is:

1. reuse the existing owner as-is;
2. extend or deepen the existing owner;
3. move/rename logic into the owner;
4. merge duplicate paths into one owner;
5. delete the weaker path;
6. create new code only when the existing owners are insufficient and the reason is documented.

For duplicated or scattered Flow logic, record:

| Concept | Current locations | Behavior differences | Canonical owner | Merge/delete path |
|---|---|---|---|---|

Do not build a second path because it is locally convenient. Reuse must happen through canonical owners and small typed boundaries, not through generic helpers, managers, processors, service locators, plugin systems, event buses, god modules, or one-implementation ports.

If creating a new module, class, or function, document why the existing owners are insufficient. A temporary parallel path must have:

- owner;
- reason;
- migration/deletion trigger;
- test or preflight proving continued need.

Every Worker proposed after T023 must include:

```text
Consolidation effect:
- Reused existing owner:
- Logic moved from:
- Logic deleted:
- Duplicate path removed:
- New code added:
- Why existing owners were insufficient:
- Guard/test preventing duplicate logic from returning:
- Net Flow logic surface area: reduced | preserved | increased
- If increased, why the increase is necessary:
```

Use "logic surface area" qualitatively, not as a strict line-count metric. A typed boundary may add lines, but the Worker must explain whether concepts, paths, branches, fallback behavior, and places-to-debug went down or up.

## Compatibility And Legacy Register

Every Flow compatibility path that remains after a tranche must have:

- path or symbol;
- reason it exists;
- owner;
- persisted-data evidence or caller evidence;
- deletion trigger;
- test that proves either safe deletion or continued need.

| Candidate | Current reason to inspect | Deletion trigger |
|---|---|---|
| `/input-policy/` as separate logic | Possible second runtime policy owner. | Caller search proves no real caller, or callers can use `/run-contract/`. |
| `_build_preseed_steps(... fallback_steps=flow.steps)` | Supports published versions missing `step_id`; leaks draft into runtime. | Preflight proves no published definition steps missing/null `step_id`, or migration backfills them. |
| `_promote_legacy_template_file_to_asset` | May support old `template_file_id` configs. | Preflight proves no draft/published steps use legacy `template_file_id` without `template_asset_id`. |
| Frontend run-contract fallbacks | Hide generated API drift. | Backend contract canonical and generated types updated. |
| `get_step_result_by_order` or order-based runtime helpers | May preserve legacy ARQ/order-based access. | Reference search proves unused, or callers migrate to snapshot step identity. |
| Compatibility tests for deleted behavior | Can preserve compatibility debt. | Delete in the same PR as the removed behavior. |

Deletion rules:

- Dead code means zero references proved by search/AST and no dynamic/persisted-data dependency.
- Legacy-but-live code is not dead. It needs a deletion trigger and, when relevant, a data/caller preflight.
- Runtime compatibility preflight must include both mutable draft rows and immutable published snapshots in `flow_versions.definition_json`; published snapshots are the runtime boundary, so draft-only evidence is insufficient for deleting runtime fallback behavior.
- Tests are deleted only in the same PR as the behavior or compatibility path they protected.
- Any test deletion must identify line-level preservation/deletion boundaries so surviving behavior coverage is not removed accidentally.
- Do not create a standalone "delete useless tests" PR.
- Do not run repo-wide unused-symbol cleanup from this goal.

T024 must classify every T023 finding as:

- `delete_now`: zero-reference or preflight-proven unused behavior.
- `merge_or_consolidate`: duplicated/scattered logic with an approved canonical owner and behavior-preserving test plan.
- `needs_preflight`: data/caller evidence is required before deletion or merge.
- `keep_temporarily`: live compatibility with owner, reason, deletion trigger, and test proving continued need.

T024 must reject creating a new implementation when reuse, merge, move, deepen, or delete is the cleaner path. T025 may delete or consolidate only the exact candidates approved by T024.
When unrelated dirty/untracked files are present, T024 must require clean-checkout verification for T025 so the deletion/consolidation patch is proven in isolation. For symbol deletion, T024 must also require a post-change zero-symbol search and any package export cleanup.

## Domain Model Stance

Use DDD pragmatically:

- Draft Flow is the mutable authoring aggregate: `flows` + `flow_steps`.
- Published Flow Version is the immutable runtime-policy snapshot: `flow_versions.definition_json`.
- Run is mutable lifecycle state pinned to an immutable published version.

The published snapshot is the runtime boundary. Runtime-facing code should parse a typed published contract with a schema version and should not read draft ORM state. Do not normalize into `flow_version_steps` unless a real relational query need appears. The first target is stricter JSON snapshot ownership:

- add or confirm `definition_schema_version`;
- parse through typed Pydantic/domain models;
- require non-null published `step_id`;
- copy published `step_id`, `step_order`, and `assistant_id` into runtime rows where needed;
- delete fallback-to-draft-by-order after preflight.

Repositories own persistence, locks, compare-and-set writes, inserts, and queries. They do not own product decisions or lifecycle policy hidden in SQL branches.

## Score Ladder

Do not treat 9/10 as a reason to keep inventing architecture work. Use this staged ladder:

| Score floor | Required state |
|---:|---|
| 6/10 | Known normal-path bugs fixed; public Flow API errors consistent; tests reviewable enough to proceed. |
| 7/10 | Published runtime contract canonical; frontend generated-contract fallbacks removed; core API journey contract-tested. |
| 8/10 | Webhook delivery durable; step identity stable; runtime file lifecycle explicit; service-key permission matrix coherent. |
| 9/10 | Long-term polish complete: typed public/lifecycle JSONB ownership, mature health/readiness, clean frontend state ownership, and unneeded compatibility paths deleted. |

## Priority Order

### Phase 0: Safe Entry And Reviewability

1. Verify first-slice source evidence.
2. Fix template asset DOCX upload typed boundary if still broken.
3. Fix Flow API scope mismatch error envelope if still divergent.
4. Mechanically split the oversized Flow router tests.
5. Inventory Flow-scoped dead code, duplicate/scattered logic, legacy compatibility paths, obsolete fallbacks, and tests that only protect compatibility behavior.
6. Let Judge approve the first evidence-gated deletion slice.

Why first:

- These are small, high-confidence, easy to verify, and improve reviewer confidence before larger schema/runtime work.
- The inventory keeps deletion and consolidation explicit without turning cleanup into repo-wide architecture busywork.

### Phase 1: Runtime Contract Ownership

7. Decide whether `/input-policy/` can be deleted. Keep it only if a real caller cannot use `/run-contract/`, and then only as a pure projection.
8. Make typed published `FlowVersion.definition_json` / `FlowRunContractService` the single runtime policy owner, including schema-version handling.
9. Remove obsolete frontend generated-contract fallbacks.
10. Add a minimal API consumer journey contract test.

Why next:

- External API consumers must have one contract source before retention, service-key, and frontend cleanup can be made coherent.

### Phase 2: Step Behavior And Output Format Isolation

11. Map current `output_mode` dispatch and all `output_type` concerns: prompt instructions, native JSON-mode decisions, validation/rendering requirements, and byte rendering.
12. Approve the minimal `StepExecutionResult`, `OutputFormatSpec`, `OutputRenderer`, and `StepHandler` design from source evidence.
13. Introduce `StepExecutionResult` or extend existing `StepExecutionOutput`, then add output format specs for concrete current output types.
14. Introduce leaf output renderers only for concrete artifact formats.
15. Introduce step handlers for concrete current step behaviors.
16. Add AST/import/enum-based guard tests so executor/runtime cannot reintroduce scattered behavior/format branching or duplicate DOCX/PDF rendering paths.

Why this phase:

- This directly supports future DOCX/PDF/template-fill changes. A DOCX format-policy change should live in `DocxOutputFormatSpec`; low-level DOCX byte rendering should live in `DocxOutputRenderer`/`docx_template_runtime.py`, not in scattered executor/runtime branches.
- It also prepares webhook outbox work by giving handlers a concrete `WebhookDeliveryIntent` instead of rediscovering delivery behavior in the executor.
- T017 must map duplicate/scattered output behavior and identify which code should be moved behind owners instead of copied.
- T018 must reject designs that copy current runtime logic into new files instead of moving/reusing it behind the approved owner.
- T019 must move existing `output_type` policy into `OutputFormatSpec`, not duplicate prompt, JSON-mode, validation, or rendering logic.
- T020 must move existing `output_mode` behavior into `StepHandler`s, not copy executor logic.
- T021 guard tests must prevent duplicate runtime dispatch from returning.

### Phase 3: Product/Data Decisions Before Migration

17. Decide service-key identity model:
   - exact API-key row ownership; or
   - stable service-principal/service-account ownership with API keys as credentials.
18. Decide runtime input file retention:
   - clear content and keep rows/metadata;
   - delete rows with tombstones;
   - or document indefinite retention.
19. Decide review/rerun service-key capability:
   - review/resume allowed or human-only;
   - rerun human-only initially or supported end to end.
20. Write one permission matrix covering human owner, space admin/owner, tenant admin, and service key before implementing permission/schema changes.

Why this phase:

- These decisions affect schema, audit, evidence, retention, API docs, and external consumer expectations. Do not implement from assumptions.
- In `state.yaml`, the product/data decision task and its implementation tasks must remain blocked with `blocked_reason: needs_human_product_decision` until the owner provides the decision inputs.

### Phase 4: Runtime Identity And Persistence

21. Make draft step persistence id-owned.
22. Make runtime step identity snapshot-owned and independent of mutable authoring rows.
23. Enforce published-version pointer and resolve `files.user_id` FK drift.
24. Add only measured/useful indexes, starting with stale queued run recovery if proven.

Why this phase:

- Runtime history, evidence, review, rerun, and retention must remain explainable after draft edits, unpublish, republish, or soft delete.

### Phase 5: Runtime Reliability

25. Add durable outbound webhook delivery state.
26. Replace direct post-commit webhook delivery with outbox enqueue and worker delivery.
27. Add retry/dead-letter behavior.
28. Version Celery payloads and terminalize corrupt queued runs.
29. Split DB health from runtime readiness if deployment uses Flow health operationally.

Why this phase:

- This removes the commit-then-side-effect crash window and turns runtime failures into observable durable state.

### Phase 6: API And Frontend DX

30. Harden API consumer runtime paths and examples.
31. Add a service-key consumer journey contract test.
32. Clean Flow frontend state ownership: form schema, step list, run dialog, generated types.
33. Consolidate step-chain compatibility into one backend-owned descriptor if still a recurring drift risk.

Why this phase:

- Once backend runtime contracts and identity are stable, frontend and API docs can safely converge.

## Commit Plan

| # | Commit | Board task | Notes |
|---:|---|---|---|
| 1 | `fix(flows): persist DOCX template assets through typed file service` | `T003` | Remove `cast(Any)` missing method path. Add focused route/service tests. |
| 2 | `fix(flows-api): return GeneralError for Flow scope mismatches` | `T004` | Align OpenAPI examples and wire response. |
| 3 | `test(flows): split router tests by API surface` | `T005` | Mechanical split only. No assertion changes. |
| 4 | `docs(flows): inventory legacy compatibility, duplicate logic, and dead code` | `T023` | Read-only Scout receipt; no deletion. |
| 5 | `refactor(flows): delete or consolidate first evidence-gated legacy slice` | `T025` | Only after `T024` approves candidates and allowed files. Include consolidation effect. |
| 6 | `refactor(flows): derive runtime input policy from published contract` | `T007` | After `T006` decides delete vs projection for `/input-policy/`; deepen the published contract owner, do not create a second policy path. |
| 7 | `refactor(flows-ui): remove generated contract fallbacks` | `T008` | Generated API types become source of truth; remove fallback/mirror logic, do not create another frontend contract shape. |
| 8 | `test(flows-api): cover core runtime consumer journey` | `T022` | Minimal contract journey before product/data migrations. |
| 9 | `refactor(flows-runtime): centralize output format policy` | `T019` | Behavior-preserving; text/json/docx/pdf prompt instructions, native JSON-mode, and renderer selection move behind `OutputFormatSpec`. |
| 10 | `refactor(flows-runtime): execute steps through handlers` | `T020` | Behavior-preserving; executor stops owning step-mode branches. |
| 11 | `test(flows): enforce runtime architecture guards` | `T021` | AST/import/enum-based guards: no draft-state runtime reads, no raw HTTPException paths, no duplicate output dispatch. |
| 12 | `refactor(flows): sync draft steps by id` | `T012` | Requires preflight and red tests. |
| 13 | `migration(flows): enforce published pointer and file lifecycle constraints` | `T014` | Include migration preflight and DB tests. |
| 14 | `feat(flows-runtime): add outbound webhook delivery outbox` | `T013` | Table/repo/service first; behavior switch after. Consume `WebhookDeliveryIntent` if handler seam has landed. |
| 15 | `refactor(flows-runtime): enqueue webhook delivery instead of direct send` | `T013` | Crash-window tests required. |
| 16 | `feat(flows-runtime): deliver webhook outbox with retry and dead-letter` | `T013` | Retry/dead-letter tests required. |
| 17 | `refactor(flows-runtime): version Celery payloads and terminalize corrupt queued runs` | follow-up Worker | Keep separate from webhook outbox. |
| 18 | `refactor(flows-ui): make Flow editor state intent-driven` | `T016` | Component tests required. |
| 19 | `refactor(flows): generate step compatibility descriptor` | later Worker | Defer until core runtime reliability is stable. |

## Do Not Combine

- Do not combine test splitting with semantic fixes.
- Do not combine webhook outbox with step identity.
- Do not combine DB migrations with frontend cleanup.
- Do not combine service-key product decisions with task payload parser cleanup.
- Do not combine Flow AI Builder cleanup with Flows runtime work.
- Do not combine retention model changes with unrelated API wording.
- Do not combine the handler/renderer seam with webhook outbox behavior changes.
- Do not combine the StepExecutionResult/output-format work with broad step identity schema changes.
- Do not combine dead-code inventory with deletion.
- Do not combine deletion of legacy code with unrelated semantic refactors.
- Do not combine consolidation with unrelated new abstractions.
- Do not delete tests unless the behavior they protected is removed in the same PR.

## Required Red Tests Or Guards

Add failing/guard tests before risky changes:

- Template asset upload should fail before the typed-boundary fix if the missing method path is still real.
- Scope mismatch API test should assert real wire `GeneralError` body.
- Dead/legacy inventory records zero-reference evidence or data/caller preflight requirements before deletion.
- Duplicate/scattered logic inventory records current locations, behavior differences, canonical owner, and merge/delete path before consolidation.
- Compatibility register entries include path/symbol, reason, owner, evidence, deletion trigger, and test plan.
- Publish v1, edit draft v2, assert runtime contract/input/upload/graph remain v1.
- Published contract parser rejects unsupported `definition_schema_version` and corrupt runtime snapshot shapes with explicit errors.
- Minimal API consumer journey test: inspect contract, discover runtime paths, upload required files where needed, create run with `expected_flow_version` and idempotency key, poll/fetch status/result shape, and assert stable error codes.
- Runtime architecture guard: runtime-facing code does not read mutable draft `flow.steps` after the contract refactor.
- Runtime architecture guard: Flow runtime/application code does not raise raw FastAPI `HTTPException`.
- Runtime architecture guard: generic executor/runtime code does not branch directly on `output_mode` after handler refactor.
- Runtime architecture guard: generic executor/runtime code does not branch directly on `output_type` after output format spec refactor; prompt instructions, native JSON-mode, validation/rendering requirements, and renderer selection live in format specs.
- Registry totality guard: every supported runtime `output_mode` has a handler and every supported `output_type` has an output format spec. Only artifact-producing formats need renderers.
- Renderer locality guard: DOCX/PDF rendering imports live only in renderer/format leaf modules and explicitly allowlisted template validation modules.
- Step reorder preserves ids; replace creates a new id.
- Run/evidence remains explainable after draft edit/unpublish/soft delete.
- Runtime input retention clears or preserves file content according to policy and evidence shows a machine-readable state.
- Service-key rotation behavior matches the chosen ownership model.
- Service-key review/rerun policy matrix is coherent.
- Webhook step success and outbound pending row persist transactionally.
- Duplicate webhook delivery uses deterministic idempotency and dead-letters visibly.

## Idempotency Note

Do not add an idempotency unique-index migration from review comments alone. Current source inspection shows partial unique indexes for user and service-key idempotency in `backend/src/intric/database/tables/flow_tables.py` and `backend/alembic/versions/20260411_flow_run_identity_and_idempotency.py`.

Worth testing later:

- same idempotency key plus same fingerprint returns the same run;
- same idempotency key plus different fingerprint returns `flow_run_idempotency_conflict`;
- concurrent duplicate create-run requests do not double-start;
- chosen service-key identity semantics do not accidentally change idempotency scope.

## Validation Command Menu

Use the narrowest meaningful check first, then broaden only when needed.

Backend examples:

```bash
cd backend && uv run pytest tests/unittests/flows/test_flow_template_asset_compatibility.py tests/unittests/flows/test_docx_template_runtime.py -q
cd backend && uv run pytest tests/unittests/flows/test_flow_router.py -q
cd backend && uv run pytest tests/integration/flows/test_flow_consumer_api_contract.py -q
cd backend && uv run pytest tests/integration/flows/test_flow_runtime_worker_contract.py tests/integration/flows/test_flow_terminalization_contract.py -q
cd backend && uv run ruff check <touched files>
cd backend && uv run ruff format --check <touched files>
cd backend && PYTHONDONTWRITEBYTECODE=1 uv run pyright <touched src paths>
git diff --check
```

Frontend examples:

```bash
cd frontend/apps/web && ../../node_modules/.bin/vitest run src/lib/features/flows/flowRunContract.test.ts
cd frontend/apps/web && ../../node_modules/.bin/vitest run src/lib/features/flows
cd frontend/apps/web && ../../node_modules/.bin/eslint <touched files>
cd frontend/apps/web && ../../node_modules/.bin/prettier --check <touched files>
cd frontend/apps/web && bun run check
```

Migration/schema examples:

```bash
cd backend && uv run pytest tests/integration/flows/test_flow_repository.py tests/integration/flows/test_flow_run_repository.py -q
docker exec eneo-41ae93-db-1 psql -U postgres -d postgres -c "<preflight query>"
```

## Review Gates

Use Claude peer review for non-trivial architecture, schema, runtime reliability, API contract, permission, service-key, retention, or frontend state changes.

Use Antigravity only tactically for high-impact decisions or when Claude/Codex disagree. Do not use it as routine background automation.

The default Flow refactor peer-review command from repo instructions is:

```bash
/Users/ccimen/.agents/skills/claude-peer-loop/scripts/claude_peer_loop.py
```

For Flow/Flow AI Builder gates in this checkout family, the local convention is:

```bash
/Users/ccimen/.agents/skills/claude-peer-loop/scripts/claude_peer_loop.py --model claude-opus-4-7 --effort xhigh --timeout-seconds 1200
```

Do not mark a non-trivial tranche complete without either peer review or an explicit receipt explaining why peer review was skipped and what local evidence replaced it.
