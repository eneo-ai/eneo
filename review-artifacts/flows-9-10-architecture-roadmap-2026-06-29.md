# Eneo Flows 9/10 Architecture Roadmap

Date: 2026-06-29

## TL;DR

1. Keep the current PG implementation track focused on verified ship-safe fixes, but require each slice to leave architecture handoff data so the later 9/10 track does not need another broad rediscovery pass.
2. Duplication is the main architecture enemy. The roadmap is scoped to Flows and Flow AI Builder only, and every follow-up should first ask which existing owner can be reused, merged into, moved to, or deleted.
3. Do not mix "fix the validated findings" with "rewrite toward ideal architecture." PG should delete, merge, move, reuse, and harden owners only where the finding already proves the boundary.
4. After PG completes, run a no-code post-PG scorecard and ownership map before any broad refactor. That is the decision point for 9/10 work.
5. Flows proper can plausibly reach 9/10 after PG plus focused runtime, API contract, data/schema, frontend-state, and test-confidence tracks. Flow AI Builder needs a separate structural simplification track; PG alone only gets it to roughly 6/10.

## Inputs Read

- `review-artifacts/ultracode-independent-review-2026-06-29/index.md`
- `review-artifacts/ultracode-independent-review-2026-06-29/_gate/scorecard.md`
- `review-artifacts/ultracode-independent-review-2026-06-29/roadmap-to-9-and-10.md`
- `review-artifacts/ultracode-independent-review-2026-06-29/deletion-and-simplification-backlog.md`
- `review-artifacts/ultracode-independent-review-2026-06-29/open-questions.md`
- `review-artifacts/implementation-progress-2026-06-29.md`
- ChatGPT Pro strategic roadmap review output supplied on 2026-06-29
- `review-artifacts/chatgpt-pro-current-status-digest-2026-06-29.md`
- `docs/engineering/maintainability-standards.md`
- `docs/engineering/comment-and-readability-standard.md`
- `docs/engineering/api-design-standard.md`
- `docs/engineering/testing-standard.md`
- `docs/engineering/frontend-state-standard.md`

CRG was used as a reducer after the graph became available for this root. `get_minimal_context` reported 31,576 nodes / 281,929 edges across 3,772 files. `find_large_functions(kind=File, file_path_pattern=backend/src/intric/flows, min_lines=800)` confirmed the main size pressure points, including `backend/src/intric/flows/runtime/executor.py:1` at 2,223 lines, `backend/src/intric/flows/api/flow_models.py:1` at 2,091 lines, and the Builder control-plane modules `ai_builder_critic_invariants.py:1`, `ai_builder_step_skeleton.py:1`, `ai_builder_framework_policy.py:1`, `ai_builder_repo.py:1`, and `ai_builder_router.py:1` above 1,300 lines. CRG is not a proof source by itself: every delete or merge must be re-verified at execution time with fresh `rg` source evidence, and CRG caller/importer checks are an optional second reducer when available.

## Current Reality

| Area | Current review score | After validated PG/finding fixes | Can PG alone reach 9? | Honest target after architecture track |
|---|---:|---:|---|---|
| Flows proper | ~6/10 | ~8/10 | No | 9/10 is plausible if E2E/runtime/data/API gaps are closed with evidence. |
| Flow AI Builder | ~3/10 | ~6/10 | No | 8/10 is plausible after structural simplification; 9/10 requires a serious Builder-specific control-plane/eval track. |
| API consumer DX | ~6/10 | ~8/10 | No | 9/10 after one error envelope, typed evidence export, generated-client conformance, and documented journeys. |
| Data/schema/JSONB | ~6/10 | ~8/10 | No | 9/10 after every JSONB owner, corruption behavior, migration policy, constraints, and indexes are explicit and tested. |
| Runtime reliability | ~6/10 | ~8/10 | No | 9/10 after crash/load/queue/terminalization behavior is proven, not reasoned about. |
| Test/release confidence | ~4/10 | ~7/10 | No | 9/10 after CI proves browser -> API -> Celery -> status -> result -> webhook, plus crash and contract tests. |

## Operating Strategy

The smart path is two-track, not one giant refactor:

| Track | Owner | Purpose | Allowed during PG | Forbidden during PG |
|---|---|---|---|---|
| Ship-safe PG track | Current implementation agent | Fix validated release blockers and high-confidence cleanup with tight slices. | Delete zero-caller code, merge duplicated owners, move logic to existing canonical owners, add behavior tests for the finding. | Broad module rewrites, new architecture layers, speculative interfaces, Builder redesign, source-shape cleanup unrelated to the slice. |
| 9/10 architecture track | Follow-up architecture goal after PG | Re-score the smaller system, then execute focused deepening work. | Not applicable; record candidates only. | Starting before PG evidence is complete, or treating PG status as proof of 9/10. |

The PG track should improve architecture where it directly follows from the finding. Examples: deleting the decorative step-handler registry is architecture work; adding an abstract "runtime architecture service" would not be. The 9/10 track starts when the system is smaller, safer, and evidence-rich enough for senior-level design decisions.

## Gate 0: Builder Ship / No-Ship Decision

Before any more Builder-conditional PG work is scoped, the Flow AI Builder owner must decide whether Builder ships in the first production cut.

The canonical owner for this and the other policy gates is the [Decision Register](#decision-register). Track sections may mention the consequences, but if wording drifts the Decision Register wins.

| Decision | Consequence | What the PG agent should do |
|---|---|---|
| Builder ships | PG-16 through PG-19 and PG-D1 through PG-D3 stay in the before-production gate. | Fix Builder correctness and security ownership before treating Flow AI Builder as releasable. |
| Builder does not ship | Builder PG slices move to the follow-up Builder architecture track. | Gate the feature off at the backend router/configuration plane, keep only shared-contract fixes required by Flows proper, and preserve maximum deletion/refactor freedom. |
| Decision missing | Do not start Builder-conditional PG work. | Record the blocker in the progress ledger and continue Flows-proper PG slices that do not depend on Builder. |

This is the most important scoping decision. It changes the gate from roughly the full PG set to a smaller Flows-proper release gate and decides whether C8 is a release-hardening track or a deeper pre-ship redesign track. The answer must be "ships" or "does not ship"; "maybe" is not actionable. If Builder ships, Builder P1 correctness/eval work is release-blocking. If Builder does not ship, a backend route/settings gate is required before claiming release readiness; frontend navigation hiding is not enough.

## Quality Ladder

Scores should only move when evidence changes. Use this ladder after PG and after each architecture sprint:

| Level | Meaning | Required evidence |
|---|---|---|
| 6/10 | Understandable design with known release or ownership gaps. | Findings are documented, but duplicate owners, missing E2E proof, or policy decisions remain. |
| 7/10 | Locally safe and mostly typed. | P1/P2 correctness issues fixed, obvious dead code removed, focused tests pass, but whole-system proof is incomplete. |
| 8/10 | Ship-ready with follow-up. | Runtime/API/data risks have behavior or contract tests; duplicate paths are mostly removed or deliberately staged. |
| 9/10 | Senior-maintainable. | One owner per important concept, no known fake seams or dead compatibility paths, generated contracts are authoritative, E2E/runtime/data failure modes are proven. |
| 10/10 | Exemplar. | 9/10 plus staging/load/crash/eval evidence, complete operability, and no known unresolved architecture policy decisions. |

The post-PG goal is not to relabel everything 9/10. It is to identify which dimension is the floor and run the smallest evidence-backed track that raises that floor.

## Duplication-First Architecture Rule

For the 9/10 track, "architecture cleanup" means removing duplicate ownership inside Flows and Flow AI Builder. It does not mean inventing new framework layers. A deduplication slice must choose one of these actions:

1. **Reuse** an existing owner directly.
2. **Merge** weaker duplicate behavior into the existing owner.
3. **Move** behavior to the owner that already has the data, lifecycle, or contract.
4. **Delete** the weaker path when it has no real caller, no shipped value, or only preserves never-shipped compatibility.
5. **Create** only when all existing owners are demonstrably insufficient, and the new module is deeper than the implementation it hides.

Do not create a third "shared" helper merely because two paths are duplicated. That usually leaves three concepts: old path A, old path B, and a new wrapper. The right result is one owner and fewer concepts.

### Verified Duplication Map To Carry Forward

These are not all immediate edits. They are the known duplicate-logic categories the post-PG architecture scorecard must revisit and either close or deliberately defer.

| Concept | Duplicate evidence | What genuinely differs | Likely canonical owner | Preferred action | When to act |
|---|---|---|---|---|---|
| Executor failure persistence tail | `backend/src/intric/flows/runtime/executor.py:1593-1622` and `backend/src/intric/flows/runtime/executor.py:1655-1682` both finish the attempt, persist the failed step result, terminalize the run as `EXECUTOR_FAILED`, and commit. | The typed path narrows requested model/provider values before persistence; the generic path does not. A shared applier must receive already-normalized inputs or preserve that guard. | Existing executor failure handling. Keep distinct typed/generic error-plan builders if they carry real domain meaning. | Merge the common persistence tail behind one private applier after runtime correctness tests protect terminalization order. Do not add `Any`, casts, or weaker types at the new seam. | After PG-5/PG-6/PG-8. |
| Stale queued redispatch | Beat path in `backend/src/intric/flows/runtime/tasks.py:607-676`; manual path in `backend/src/intric/flows/application/flow_run_service.py:704-750`; router exposes manual redispatch at `backend/src/intric/flows/api/flow_run_execution_router.py:1492-1532`. | Both already use the same dispatch-request builder. The real divergence is policy: beat swallows/logs and continues; manual redispatch must be API-visible and audit-visible. | Existing run service or a narrower existing dispatch routine, chosen by transaction ownership. Do not create a new generic queue manager. | Merge claim/build/dispatch semantics while preserving the caller policy boundary and testing both policies separately. | After PG runtime fixes. |
| Builder telemetry field set | Dict owners at `backend/src/intric/flows/ai_builder/ai_builder_telemetry.py:179` and `backend/src/intric/flows/ai_builder/ai_builder_telemetry.py:218`; Pydantic owner at `backend/src/intric/flows/ai_builder/ai_builder_telemetry_models.py:6`; router validates with the model at `backend/src/intric/flows/ai_builder/ai_builder_router.py:222` and `backend/src/intric/flows/ai_builder/ai_builder_router.py:352`. | No meaningful difference should remain; current drift risk is exactly the defect. | `SessionTelemetrySummary`. | Merge defaults/sanitization into model-driven behavior so the field set is declared once. | PG-18 if Builder ships; otherwise early Builder architecture track. |
| Builder slot-to-question id mapping | Local duplicate map at `backend/src/intric/flows/ai_builder/ai_builder_server_decision_dispatch.py:67` and resolver at `:338-339`; catalog owner exists at `backend/src/intric/flows/ai_builder/question_catalog.py:820` and is already reused by discovery modules. | Local map has no independent behavior; it is a weaker duplicate. | `question_catalog.legacy_question_id_for_slot`. | Reuse catalog owner and delete local map/resolver. | Small Builder cleanup after PG deletion batch or Builder track. |
| Builder frontend/backend error enums | Frontend manual sets at `frontend/apps/web/src/lib/features/flows/ai-builder/aiBuilderError.ts:16` and `:27`; generated backend enums in `frontend/packages/intric-js/src/types/schema.d.ts:8593` and `:8659`. | Frontend may need explicit local-only `network` and `client` categories; server categories/phases should come from generated types. | Generated OpenAPI client types, with explicit frontend-only local extensions for `network` and `client`. | Reuse generated enums; keep local-only categories as named superset. | Builder/frontend state track. |
| Webhook delivery state | JSON payload writers at `backend/src/intric/flows/runtime/step_execution_runtime.py:505` and `backend/src/intric/flows/runtime/step_result_builder.py:128-130`; export scrub at `backend/src/intric/flows/flow_run_export_json.py:1087`; relational delivery state is the intended owner per PG-11. | JSON mirror is stale-prone and leaks error-string shape into output payloads; relational delivery state is the durable owner. | `flow_run_webhook_deliveries` relational state and delivery repository/export projection. | Delete JSON mirror after confirming no frontend/manual consumer reads the flags. | PG-11. |
| Template asset/file dual identity | Authoring writes both keys at `backend/src/intric/flows/application/flow_service.py:912-913`; runtime requires `template_file_id` at `backend/src/intric/flows/runtime/template_fill_runtime.py:293-298` and cross-checks optional `template_asset_id` at `:350-369`; asset service owner starts at `backend/src/intric/flows/flow_template_asset_service.py:23`. | `template_file_id` is still runtime load-bearing, so this is staged duplication, not a direct delete. | `FlowTemplateAssetService` and asset-backed runtime resolution. | Stage migration: asset-first runtime resolution, backfill, then delete `template_file_id` fallback. | PG-D4 / authoring track. |
| Template asset presentation capability flags | Domain flags at `backend/src/intric/flows/domain/flow.py:127-130`; service projection mutates them at `backend/src/intric/flows/flow_template_asset_service.py:137-150`. | Capability flags are API presentation derived from actor access, not persisted asset identity. | API/readiness projection, not domain entity. | Move presentation flags out of domain while preserving API response shape. | PG-15. |
| Evidence export summary | Legacy open dict in `backend/src/intric/flows/api/flow_models.py:2076`; typed summary at `backend/src/intric/flows/api/flow_models.py:2077`; builder emits both in `backend/src/intric/flows/flow_run_export_json.py:137-159`; generated open dict leaks to `frontend/packages/intric-js/src/types/schema.d.ts:15846-15850`. | Legacy summary still carries fields that must reach typed parity before deletion. | `EvidenceExportSummary` plus versioned export contract. | Expand typed parity, deprecate open dict, then delete legacy `summary`. | PG-D4 / API contract track. |

The post-PG scorecard should add new rows only with source evidence. It should not infer duplication from similar names alone.

## Required PG Handoff Delta

Do not create a second progress ledger. Extend each existing slice entry in `review-artifacts/implementation-progress-2026-06-29.md` with only the architecture delta fields that the current ledger does not already capture.

| Field | What to record | Why it matters later |
|---|---|---|
| Canonical owner before | The module/type/function that owned the concept before the slice, including any duplicate owners. | Prevents re-discovery and exposes pre-existing confusion. |
| Canonical owner after | The single owner after the slice, or "unchanged" with a reason. | Lets the post-PG scorecard verify ownership actually improved. |
| Duplicate paths remaining | Any known duplicate left deliberately out of scope. | Seeds the 9/10 backlog without broadening the slice. |
| 9/10 follow-up candidate | One sentence only, with finding id or "new candidate." | Keeps the current agent from solving future-scope work inline. |
| Decision or measurement needed | Product/ops/security/load/eval decision required before acting. | Prevents guessing on medium-confidence or policy-gated items. |
| What not to preserve | Dead behavior, legacy shape, fake seam, or compatibility path intentionally not carried forward. | Reinforces delete-first architecture discipline. |

Use the existing fields for behavior changed, complexity deleted or owner clarified, validation commands, remaining risk, and contract/runtime impact. The point is one progress source of truth, not a parallel architecture report.

## Phase A: Finish PG Without Expanding Scope

After Gate 0 is answered, PG should continue in the existing order unless a verifier proves a dependency changed:

1. Finish PG-3 and PG-4 deletion-first cleanup.
2. Complete the runtime correctness cluster: PG-5, PG-6, PG-7, PG-8.
3. Complete the external contract/data cleanup cluster: PG-10, PG-11, PG-12, PG-13, PG-15, and PG-D4 staging decisions.
4. If Builder ships, complete PG-16 through PG-19 and PG-D1 through PG-D3. If Builder does not ship, gate it off and move those slices to the Builder architecture track.
5. Run PG-9 after PG-2 has made the E2E stack capable of executing a real Flow run.

Current sequencing guardrails after PG-10a:

- Do not start Builder-conditional slices until Gate 0 is answered.
- If Builder ships, run Builder correctness work before capability descriptors, MCP adapters, or broad Builder architecture experiments.
- If Builder does not ship, implement or record the backend feature gate before spending more PG time on Builder internals.
- Treat PG-10b as a separate API-contract decision before claiming API consumer DX is 9/10: app-global FastAPI 422 standardization affects generated clients and non-Flow endpoints.
- Decide the pre-launch migration policy before schema/migration cleanup that would otherwise preserve false reversible-downgrade confidence.
- Do not start capability-descriptor/MCP work, broad `FlowService` splits, whole-scale JSONB relationalization, or Builder proposal-family collapse until the current PG evidence and relevant owner decisions justify them.

PG acceptance criteria:

- Validated P0/P1 findings are fixed or explicitly gated off by product decision.
- All direct deletes have fresh source and `rg` evidence at execution time; CRG caller/importer checks are useful when available but never replace source proof.
- Staged migrations have a concrete sunset trigger, deletion check, or follow-up slice. Dual paths are not allowed to survive as permanent architecture.
- Public API or generated-client-visible changes include contract validation.
- Runtime changes include behavior tests for the real failure mode.
- Migration/schema changes include preflight and rollback/recovery notes.
- Progress ledger includes the architecture delta fields above without duplicating existing ledger sections.
- No broad architecture rewrite was hidden inside a PG slice.
- Docs or coverage guards are not enough to claim release confidence; release confidence requires behavior/API/runtime proof through the real journey.

## Phase B: Post-PG No-Code Re-Score

After PG finishes, run a dedicated no-code architecture review and save it as:

`review-artifacts/post-pg-architecture-scorecard-YYYY-MM-DD.md`

Required core output:

| Section | Required content |
|---|---|
| Five-line TL;DR | New honest score for Flows proper and Builder, including what still blocks 9/10 and 10/10. |
| Canonical ownership map | Flow runtime, Flow API contract, evidence export, template assets, JSONB, frontend state, Builder plan/session lifecycle, Builder telemetry, Builder provider boundary. |
| Duplication map | Location A, Location B, difference, canonical owner, delete/merge path. |
| Delete list | Remaining dead code, fake seams, compatibility paths, dead tests, implementation-pin tests, comments/docstrings with phase history. |

Supplemental sections should be generated only when they change a decision or work item:

| Supplemental section | Use when |
|---|---|
| Interface audit | A slice proposes a protocol, adapter, service split, or other seam. One adapter is suspicious unless it is an external/cross-process seam. |
| Change-path analysis | A common future change still touches many unrelated files, such as adding a step type, status, API field, permission, JSONB envelope, template asset behavior, Builder provider, or Builder question slot. |
| Architecture invariant ledger | An invariant can be enforced by a test, generated contract, linter, or short durable doc. |
| Test confidence map | A dimension is blocked by test confidence, dead tests, E2E gaps, load/crash gaps, or implementation-coupled tests. |
| 9/10 work items | Always included as the final ranked backlog, but only after the ownership map, duplication map, and delete list are complete. |

This review should use CRG for context reduction and direct file reads for every concrete claim. It should not modify source code.

## Phase C: 9/10 Architecture Tracks

### C1. Runtime Contract And Operability

Goal: Flows runtime becomes reliable under retries, crashes, terminalization, queue pressure, and real worker execution.

Work items:

- Make terminalization invariants explicit in one runtime owner.
- Prove coroutine cancellation and secondary-terminalization behavior with DB-backed tests.
- PG-5 must wait for the submitted executor coroutine to finish cancellation/unwind on the event-loop thread before terminalizing the run as failed. A mocked `future.cancel()` test is not sufficient; the test must use a real asyncio task that would write after cancellation if the race remains.
- Decide queue separation only after saturation evidence.
- Add a saturation/load smoke before queue split decisions: long `flows.execute` work must not starve recovery, reconciliation, audit, or webhook delivery work beyond their intended intervals.
- Keep going past the PG-9 browser smoke: release confidence needs a CI-green golden runtime journey proving browser/API dispatch, Celery execution, status polling, result/evidence or artifact retrieval, and where feasible webhook delivery.
- Ensure every runtime transition has persisted state, transaction owner, retry behavior, crash behavior, and audit event.
- Consolidate duplicate failure-persistence and redispatch paths after correctness fixes land.
- Delete or wire `intric.observability.failure_events` into real terminal failure/dead-letter paths. Tests-only logging contracts are dead architecture unless operators can actually rely on them.
- Emit operator-useful structured logs on terminal dead-letter transitions for audit/webhook delivery, with sanitized tenant/run/outbox/action/reason identifiers.

9/10 acceptance:

- Browser/API/Celery/status/result/webhook journey passes in CI.
- Crash/timeout tests prove no post-terminalization writes.
- Saturation/load smoke answers whether recovery/delivery needs its own queue.
- Dead-letter transitions have push observability, not only pull-based gauges or tests-only contracts.
- Runtime state transitions are documented as invariants, not scattered comments.
- A new senior engineer can identify the owner for dispatch, claim, terminalize, retry, and reconcile in week one.

### C2. API Contract And Consumer DX

Goal: External developers can use Eneo Flows without reading backend source.

Work items:

- Single `GeneralError` contract, including validation errors. PG-10b must be an explicit app-global decision with generated-client and non-Flow endpoint impact reviewed; without that decision, API consumer DX cannot honestly be called 9/10.
- Evidence export typed summary parity, versioned deprecation of legacy open dict, then deletion.
- Treat typed evidence summary parity as a release/API contract track, not a docs nicety; evidence export is compliance-sensitive and generated-client-visible.
- Generated-client conformance tests for required flows: authenticate, list, inspect, upload/map files, start, poll, get outputs/artifacts, pause/edit/resume/rerun, handle errors.
- Add one golden API consumer journey receipt that ties docs, OpenAPI, generated client types, runtime rows, idempotency/error behavior, and evidence/artifact retrieval together.
- Operation ID, tag, error, permission, and generated-client registry coverage.
- Accurate examples generated from or tested against real gates.
- Documentation drift tests must check bidirectional parity where the doc claims a catalog: docs cannot mention unknown codes, and cataloged public codes cannot silently disappear from the guide unless explicitly allowlisted.

9/10 acceptance:

- No hidden second error shape for Flow APIs.
- Generated TypeScript types are the frontend source of truth.
- Docs coverage and endpoint mention checks are necessary but not sufficient for API readiness.
- API guide and docs cannot drift from OpenAPI/contract tests.
- API maintainer playbook covers adding an endpoint, schema, permission, error, test, and generated client update.

### C3. Authorization And Access Ownership

Goal: Flow and Builder authorization become reviewable through one obvious owner per route family, with route coverage tests preventing silent default drift.

Work items:

- Resolve AI Builder creator ownership: approve/apply/revise must use the same creator rule as read/send/cancel, either through lifecycle ownership or a deliberately retained router precheck.
- If Builder does not ship, gate the `ai_builder_router` at backend router/settings inclusion, not only in frontend navigation.
- Make the Flow runtime route registry the authorization review index if it earns that role; otherwise keep route-local declarations and delete the misleading central string override.
- Add route coverage tests for permission level, `FlowApiAction`, service-key allowance, and run access kind for every runtime endpoint.
- Decide and test tenant-admin raw evidence export behavior: documented carve-out or route through the same class-3 + trace gate.
- Ensure audit events are emitted at the lifecycle owner, not scattered across HTTP adapters unless the router is the real boundary.

9/10 acceptance:

- A reviewer can answer "who may call this endpoint and why?" without reading multiple unrelated files.
- Handler renames cannot silently change authorization behavior.
- Builder lifecycle operations have one creator gate owner.
- Security policy exceptions are documented and tested.

### C4. Data Model, Schema, And JSONB

Goal: Data model quality is architecture quality; hidden schemas are owned, typed, versioned, and recoverable.

Work items:

- Add ordinal constraints, missing FK indexes, and metadata tightening.
- Decide pre-launch migration policy: forward-only/reset-replay versus real reversible downgrades.
- Every JSONB column has owner, typed parser/schema, version, validation boundary, migration strategy, corruption behavior, and test.
- Do not relationalize JSONB by default. Move a JSONB value to relational columns only when it has independent identity, lifecycle, foreign keys, query/index needs, retention/audit needs, or authorization semantics.
- `FlowRun.error_json` must read through the named parser/corruption policy instead of relying on direct domain-model validation. A drifted historical row should either degrade according to the policy or fail before write; it should not become an unclassified page-level 500.
- Expand JSONB registry coverage across flow-scoped tables, not only the obvious module.
- Delete redundant indexes only after proving leftmost-prefix coverage and excluding partial/index-specific cases.

9/10 acceptance:

- Unknown JSONB shape cannot silently become product behavior.
- Corrupted legacy rows degrade or fail according to a named policy, with tests.
- Migration policy is explicit; downgrade behavior does not fabricate false safety.
- Dynamic JSONB remains acceptable when it has a typed owner and corruption policy; relational schema is reserved for values that need relational behavior.
- Query plans for known deletion/list paths use intended indexes.

### C5. Authoring, Templates, Assets, And FlowService

Goal: Template and authoring ownership becomes clear before splitting large services.

Work items:

- Keep direct `template_file_id` deletion staged: asset-first runtime resolution, backfill, then fallback deletion. The staged path must include a sunset trigger or migration check that proves when the legacy key can be removed.
- Move template capability flags out of domain and project them at API/readiness boundaries.
- Add template asset delete/storage reclamation only in `FlowTemplateAssetService` / repository / purge owner.
- Move template config resolution out of `FlowService` only after dual-key cleanup; otherwise the move creates pass-through code.
- Delete or ship dead API-shaped template inspection; do not leave it half-wired.

9/10 acceptance:

- `FlowTemplateAssetService` is the clear owner for template assets, storage lifecycle, pinning, and deletion.
- `FlowService` owns draft/publish orchestration, not template storage mechanics.
- Published DOCX flows remain safe through the staged migration.
- No unreleased compatibility path survives without owner and deletion trigger.

### C6. Frontend State And Editor Maintainability

Goal: The frontend has one owner for server state, transient UI state, and derived values.

Work items:

- Generated API types own backend statuses/categories/phases; frontend-only `network` and `client` remain explicit local extensions.
- Editor navigation/resync bug gets a deliberate state-owner decision.
- Autosave status derives from unsaved/rejected state instead of showing green after rejection.
- Flow/Builder frontend localization should not keep growing hand-rolled dictionaries. Migrate repeated Flow locale dictionaries to the project i18n owner after runtime/API gates, or before ship if the affected UI is release-facing.
- Reusable primitives are created only when there are at least two real consumers with matching behavior. Candidate concepts include status pill, step status, uploader, evidence/artifact viewer, error banner, and phase indicator, but each candidate needs source evidence before extraction.
- Components stop orchestrating domain behavior that belongs in drivers/services.

9/10 acceptance:

- No duplicated server enums or manual backend type copies in Flow/Builder UI.
- Route changes cannot keep stale editor resource identity.
- `$effect` is not used to compensate for unclear ownership.
- UI tests protect state behavior, not incidental markup.
- Localized Flow/Builder UI text comes from the project i18n owner, not parallel per-feature dictionaries that can drift.

### C7. Tests, Docs, And Dead Weight

Goal: Tests prove behavior and contracts; dead tests and source-shape pins do not block clean refactors.

Work items:

- Prune AST/source-shape guards after behavior coverage replaces them.
- Move cross-stack docs-contract checks out of unit tier where they block normal backend test runs; frontend/docs-generation and CI-file assertions belong in contract/integration tiers, not fast backend unit tests.
- Delete tests for removed behavior.
- Add only E2E tests for critical journeys; keep them deterministic and narrow.
- Generated docs or tests must own API guide fidelity.
- Native PDF/DOCX renderer tests must declare their execution contract clearly. Host missing-library failures such as absent WeasyPrint/Pango/GObject dependencies should not be misread as dead renderer coverage; run or mark them through the devcontainer/native-renderer environment.

9/10 acceptance:

- Test suite is smaller where behavior was deleted.
- The remaining suite fails on real bad behavior.
- No tests exist mainly to preserve historical branch structure, line counts, or implementation call order.
- Backend unit tests remain source-local and fast; cross-stack docs/front-end checks run in the tier that owns those dependencies.

### C8. Flow AI Builder Structural Simplification

Goal: Builder becomes a deliberately scoped control plane, not a pile of repair paths, planner surfaces, and test pins.

First decision:

- If Builder is not shipping, gate it off and optimize for deletion/rewrite freedom.
- If Builder is shipping, fix PG correctness bugs first, then simplify behind tests and telemetry.

Architecture work items:

- Define one plan/session lifecycle owner. Router should adapt HTTP, not own lifecycle transitions.
- Make `PlanningState` honest: either derived snapshot or persisted source of truth. The current "single source" language must match reality before deeper refactors.
- If Builder ships, structured-question answer ingestion for architecture-driving slots is release-blocking; silent answer drops create wrong plans and answer loops.
- Make provider response normalization fail typed. Missing provider fields are provider errors, not empty strings routed into repair.
- Add a truncation-specific proposal output error before repair. A provider response ending with `finish_reason == "length"` and unparseable arguments should not burn the repair loop with the same max-output budget.
- Make Builder intent routing explicit before repair. For each edit/revise category, the existing lifecycle or classifier owner should apply a typed revision when supported, return a typed clarification/notice when unsupported or ambiguous, or produce an edit-aware terminal error that attributes the failure to the specific scoped edit rule that fired. Recognized edit intent should not fall through to undifferentiated `self_correction_quality_failure`; create-side reliability belongs to the provider-normalization, clarification-routing behavior, and repair-bounding work items.
- Make telemetry model the single field-set owner; failed-turn cost must be persisted before repair-prune decisions.
- Persist or emit one terminal failed proposal-turn outcome with repair attempts, LLM calls, token usage, final failure kind, and request/session identifiers before deciding whether expensive repair branches earn their keep.
- Resolve dead Builder audit vocabulary: `AI_BUILDER_PLAN_REJECTED` appears to be dead after rejected-plan status removal, while `AI_BUILDER_PLAN_PROPOSED` is still declared but not emitted. Delete the dead action or wire a real lifecycle emission before treating Builder audit coverage as complete.
- Delete or bound repair/fallback branches only after telemetry answers whether they save real proposals. PG-17 should log enough token and repair metadata to prevent truncation and repair cost from becoming invisible again.
- Collapse duplicate question/slot mappings into the catalog owner.
- Before promising deterministic create/edit eval coverage, verify whether a mock-LLM materializer seam exists. If it does, add materializer tests before splitting giant modules. If it does not, first create the smallest real seam needed for testability or lower the claim.
- If Builder ships, deterministic goldens must pass through materialization, not only preflight/critic fences.
- Decide Builder session/plan retention if Builder ships; stored conversations and plans are user data and must have deletion/count consistency tests.
- Split large Builder files by lifecycle concept only after deletion removes dead paths; do not split by line count.

9/10 acceptance:

- Proposal creation, edit, repair, provider normalization, telemetry, and lifecycle each have one canonical owner.
- Every fallback path has an owner, cap, typed terminal error, telemetry, and deletion decision.
- Provider truncation and malformed tool-call responses fail at the provider boundary instead of entering generic repair.
- Failed proposal turns leave enough telemetry to decide which repair paths to delete.
- Supported and intentionally unsupported edit/revise categories are enumerated and covered by pure-function tests; create/edit repair-fallthrough cases are covered by deterministic evals without live-model luck, or the roadmap explicitly names the missing mock-LLM seam as a blocker.
- Materialization regressions are caught by deterministic tests if Builder ships; otherwise the missing seam is a named blocker.
- No half-wired helper is left because it "might be useful."

## Decision Register

These decisions are the single source of truth for roadmap-level policy gates. Track sections should reference these rows instead of inventing parallel policy text. If a decision is still undecided, follow the `While undecided` column and continue only work that does not depend on that answer.

| Decision | Owner | Blocks | Required input | While undecided |
|---|---|---|---|---|
| Does Flow AI Builder ship in the first production cut? | Product / Flow AI Builder owner | Builder PG slices and C8 scope | Release intent and feature flag/gating plan. | Do not start Builder-conditional PG work; continue only Flows-proper slices. |
| Global FastAPI 422 / `GeneralError` contract | API / generated-client owner | C2 API consumer DX and PG-10b | Decide whether main-app `RequestValidationError` becomes `GeneralError`, including generated-client and non-Flow endpoint compatibility. | Do not claim API consumer DX is 9/10 or touch global validation behavior; continue Flow-local contract cleanup. |
| Migration policy for pre-launch Flow/Builder tables | Platform / data owner; user-delegated Codex + Claude decision on 2026-06-30 for this roadmap run | C4 schema cleanup | Use real reversible downgrades when the migration only adds structural, data-preserving DDL such as constraints or indexes; use reset/replay or explicit non-reversibility for lossy migrations; never fabricate deleted or invalid historical state in a downgrade. | Resolved for delegated roadmap execution. Future lossy migrations must name their reset/replay or non-reversible contract before implementation. |
| JSONB corruption behavior | Flow runtime/data owner | C4 JSONB 9/10 score | Degrade-on-read, reject-before-write, or documented hard failure per envelope. | Do not add broad repair/fallback code; record affected JSONB owners and prove write-time validation where possible. |
| Evidence export typed summary strategy | Flow API / compliance owner | C2 API consumer DX and PG-D4 | Expand typed parity and version-deprecate/delete legacy open `summary`, or explicitly accept the generated-client weakness. | Do not delete the legacy open `summary`; close typed parity gaps and mark generated-client weakness. |
| Proposal repair pruning | Flow AI Builder owner | C8 repair simplification | Failed-turn telemetry showing whether fallback branches save real proposals. | Do not remove fallback branches; add bounded telemetry or deterministic proof first. |
| Builder provider truncation behavior | Flow AI Builder provider-boundary owner | C8 release readiness if Builder ships | `finish_reason == "length"` should produce a typed truncation error before repair, unless a measured exception is deliberately retained. | Do not route truncation into generic repair as a new pattern; classify the gap and keep dependent simplification blocked. |
| Builder session/plan retention | Product / privacy owner | C8 if Builder ships | Retention/deletion policy for stored Builder conversations, plans, and telemetry. | Do not add new stored Builder payloads beyond the current contract without deletion/count accounting. |
| Builder audit vocabulary | Flow AI Builder lifecycle/audit owner | C8 audit coverage and dead-code cleanup | Decide whether `AI_BUILDER_PLAN_PROPOSED` is emitted by a real lifecycle transition and whether `AI_BUILDER_PLAN_REJECTED` should be deleted as dead vocabulary. | Do not claim Builder audit coverage complete; keep this as a small delete-or-wire slice. |
| Tenant-admin raw evidence export carve-out | Security/compliance owner | C3 authorization score | Product/security decision plus test either documenting or removing the carve-out. | Do not broaden raw evidence export; preserve existing behavior only with tests and an explicit unresolved decision. |
| Run-history status filtering contract | Flow API / product owner | C2 API consumer DX | Add a server status filter or reword `filter_order` as display ordering only. | Do not document server filtering as supported; keep API examples honest about display ordering. |
| Signed URL expiry bounds | Files / Flow API owner | C2 API consumer DX | Decide global bounds or Flow-side clamp after enumerating all `SignedURLRequest` consumers. | Do not add Flow-only clamp without consumer inventory; keep existing global behavior. |
| Template inspection dead API-shaped method | Product / Flows owner | C5 FlowService cleanup | Delete as dead code or ship through tested endpoint. | Do not preserve the method as "maybe public"; require caller evidence before retaining. |
| Runtime queue separation | Runtime/deploy owner | C1 operability | Saturation test showing whether recovery/delivery starves behind execute work. | Do not split queues speculatively; add/load-run proof first. |
| Observability failure event contract | Runtime/ops owner | C1 operability and dead-code cleanup | Delete the tests-only contract or wire it into terminal failure/dead-letter paths with operator-useful fields. | Do not keep tests-only vocabulary as architecture; classify it as delete-or-wire. |
| Builder backend feature gate | Product / backend API owner | Gate 0 and C3 | If Builder does not ship, route registration must be disabled server-side, not only hidden in the frontend. | Do not call Builder non-shipping while routes remain mounted; continue only shared Flow contract work. |

## Phase D: 10/10 Evidence Gate

10/10 is not just "all known findings fixed." It requires proof:

- Production-like E2E and worker execution are green in CI.
- Crash, timeout, retry, duplicate start, queue saturation, and outbox/reconciliation behaviors are tested.
- Public contracts are versioned, generated, documented, and conformance-tested.
- JSONB and migrations have documented policy and tests.
- Builder has deterministic evals and telemetry for model-dependent repair paths.
- Observability lets operators diagnose terminal failures without reading code.
- There are no known duplicate owners, dead compatibility paths, dead tests, or fake seams.

Honest target: Flows proper can reach 9/10 pre-production with disciplined execution. A credible 10/10 likely needs staging/load evidence and some production-like usage feedback. Flow AI Builder should not be called 9/10 until the control plane is smaller, deterministic evals exist, and repair/fallback paths are measured or deleted.

## Prompt Addendum For The Current PG Agent

Use this addendum with the current PG implementation agent:

```text
Continue the PG roadmap exactly as scoped. Do not broaden into the full 9/10 architecture track yet.

For every remaining PG slice, add these "Architecture delta" lines to the existing `review-artifacts/implementation-progress-2026-06-29.md` slice entry:
- canonical owner before;
- canonical owner after;
- duplicate paths remaining;
- one 9/10 follow-up candidate, if any;
- decision or measurement needed;
- what not to preserve.

Do not duplicate the existing progress-ledger fields for behavior changed, complexity deleted or owner clarified, validation commands, remaining risk, or contract/runtime impact.

Within PG, architecture improvements are allowed only when they directly implement the verified finding:
- delete dead code;
- merge duplicate owners;
- move logic into an existing canonical owner;
- reuse generated/typed contracts;
- add behavior tests that prove the failure mode.

Do not start a broad Builder redesign, broad FlowService split, new abstraction layer, new interface, generic helper, or source-shape cleanup unless the current PG finding explicitly requires it. If you discover such work, record it as a 9/10 follow-up candidate and keep the slice reviewable.

If the next slice is Builder-conditional, stop first for the Builder ship/no-ship decision. If the decision is missing, continue only Flows-proper PG work that does not depend on Builder.

If Builder is marked non-shipping, do not rely on frontend hiding alone. Record or implement the backend router/settings gate required to keep Builder endpoints out of the mounted API surface.

For any staged migration or dual-path compatibility cleanup, record the sunset trigger or deletion check in the same slice. Do not leave "staged" as an indefinite state.

When PG completes, stop and produce a post-PG readiness summary. The next goal will be a no-code architecture re-score and then focused 9/10 implementation tracks.
```

## Stop Rules

- Stop PG expansion if a slice requires a product policy decision, load measurement, migration policy, or generated-client compatibility decision not already made.
- Stop any deletion if fresh source search finds a non-test caller. Use CRG as a reducer when available, but do not rely on stale CRG artifacts or fail a deletion only because CRG is unavailable.
- Stop any facade or registry deletion unless the slice also shows the production call site that uses the underlying owner directly. Zero callers alone is not enough if deletion would orphan real functionality.
- Stop any interface extraction where there is only one adapter and no external/cross-process seam.
- Stop any Builder simplification that removes fallback behavior before telemetry or a deterministic test proves it is dead or harmful.
- Stop any capability-descriptor, MCP, or adapter work that does not delete a named duplicate owner or adapt to a real external boundary. Do not use MCP/capability work to hide unresolved Builder internals.
- Stop any service split that only moves code without reducing caller knowledge or improving the interface.
- Stop any plan that adds a config flag instead of making the required launch/product/API/security decision.
- Stop any staged migration plan that lacks a sunset trigger, migration check, or explicit deletion follow-up.
- Stop any "Builder off" plan that leaves Builder routes mounted server-side.
