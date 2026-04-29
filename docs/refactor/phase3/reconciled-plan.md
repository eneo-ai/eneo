# Phase 3 Reconciled Plan

TL;DR:
1. Claude and Gemini both agree the review found the right weak areas, but the Phase 2 plan still over-trusted its own ordering and under-specified the feature-gap contracts.
2. The largest correction is sequencing: Phase 4 must replace the Phase 2 ROI ranking with a topologically sorted implementation order that separates true shims, public-contract deletions, data migrations, generated-type work, and large AI Builder waves.
3. Pre-production means we should break unshipped contracts, but still prove and migrate persisted local/dev data shapes before deleting row-shape fallbacks.
4. Runtime feature PRDs must specify checkpoint/yield mechanics, DAG-aware invalidation, fail-open/fail-closed behavior, permission migration, and contract tests before any implementation.
5. Overall plan confidence remains medium-high after reconciliation, but the Phase 4 PRDs must be stricter than Phase 2 sketches.

## Inputs

| Input | Role In Reconciliation |
|---|---|
| `docs/refactor/phase2/synthesis.md:45-68` | Original Top 20 ROI list to be re-ranked. |
| `docs/refactor/phase2/synthesis.md:70-100` | Original dependency graph that Claude found too coarse. |
| `docs/refactor/phase2/synthesis.md:102-141` | Original feature-gap sketches that need executable contract detail. |
| `docs/refactor/phase3/claude-review.md:1-68` | Adversarial Claude review, rerun with the requested 25-minute timeout. |
| `docs/refactor/phase3/gemini-review.md:1-39` | Adversarial Gemini review. |
| `docs/refactor/phase1/04-dead-and-legacy.md:27-44` | Deletion inventory that distinguishes true dead code from migration-gated row/API shapes. |
| `docs/refactor/phase1/08-tests.md:3-9` | Test pyramid evidence and baseline test weakness. |
| `docs/refactor/phase1/09-api-maintainer.md:125-161` | Authorization owner split and raw AI Builder scope reads. |
| `docs/refactor/phase1/12-observability-operability.md:87-105` | Audit durability and terminalization policy tension. |

## External Review Verdicts

| Reviewer | Main Attack | Decision | Why |
|---|---|---|---|
| Claude | Phase 2 hides ordering and dependency risk by ranking deletes, generated types, and feature work as independent ROI items (`docs/refactor/phase3/claude-review.md:1-7`, `:50-60`). | Accepted. | The Phase 2 dependency graph is too coarse; it lists `Delete shims/barrels` as one node even though `ai_builder_models.py` is large import churn while `flow_repo.py` is a true shim (`docs/refactor/phase2/synthesis.md:54`, `docs/refactor/phase2/synthesis.md:86-99`). |
| Claude | Feature-gap sketches are prose, not executable contracts (`docs/refactor/phase3/claude-review.md:7`, `:52-58`). | Accepted. | Phase 2 has useful layer tables but lacks JSON examples, pre/post conditions, and failure-mode matrices (`docs/refactor/phase2/synthesis.md:102-141`). |
| Claude | Generated frontend types have a hidden dependency on truthful OpenAPI generation (`docs/refactor/phase3/claude-review.md:34`). | Accepted. | API maintainer evidence shows OpenAPI postprocessing in `backend/src/intric/server/main.py:209-225` and `:313-335` (`docs/refactor/phase1/09-api-maintainer.md:214-217`). |
| Claude | Audit outbox and terminalization policy collide unless fail-open/fail-closed behavior is explicit (`docs/refactor/phase3/claude-review.md:32`). | Accepted. | Observability review already shows terminal audit differs between evidence fail-closed and executor warning-only paths (`docs/refactor/phase1/12-observability-operability.md:51-52`, `:87-105`). |
| Claude | Test inversion should rank earlier because many proposed refactors change cross-layer contracts (`docs/refactor/phase3/claude-review.md:38`). | Accepted with refinement. | Do not write a broad test-first mega-PR. Each wave needs one small contract/characterization test before changing its contract, using the gaps named in `docs/refactor/phase1/08-tests.md:63-72`. |
| Gemini | The plan contradicts pre-production deletion bias by preserving top-level `file_ids` and dual schema shapes (`docs/refactor/phase3/gemini-review.md:7-9`, `:32`). | Accepted with migration distinction. | Source API compatibility should be deleted, but persisted row cleanup still needs a proof/backfill path because Agent D found `file_ids` is a public API and JS client contract today (`docs/refactor/phase1/04-dead-and-legacy.md:82-83`). |
| Gemini | Relational extraction of step inputs/artifacts may be over-engineering (`docs/refactor/phase3/gemini-review.md:10-11`, `:33`). | Accepted. | Phase 2 already had the safer default: version and parse JSON first; add first-class tables only for queryability, audit, or lifecycle transition need (`docs/refactor/phase2/synthesis.md:37`, `:204`). |
| Gemini | Pause/review must yield and rehydrate the Celery worker rather than block it (`docs/refactor/phase3/gemini-review.md:18-19`, `:34`). | Accepted. | Phase 2 said "waiting_for_review" but did not explicitly state worker termination and resume redispatch mechanics (`docs/refactor/phase2/synthesis.md:134-141`). |
| Gemini | Rerun invalidation must use DAG dependencies, not step order (`docs/refactor/phase3/gemini-review.md:21-22`, `:35`). | Accepted. | Existing `flow_step_dependencies` makes ordinal invalidation unsafe; Phase 4 must use transitive dependent step IDs. |
| Gemini | Fix OpenAPI at source, not by isolating more postprocessing (`docs/refactor/phase3/gemini-review.md:24-25`, `:36`). | Accepted with one exception. | Flow-specific upload patches should move to endpoint/schema source. Generic OpenAPI compatibility patches may remain separately owned if not flow-specific (`docs/refactor/phase1/09-api-maintainer.md:214-216`). |
| Gemini | Pagination cannot remain "document current-page count" (`docs/refactor/phase3/gemini-review.md:27-28`). | Accepted. | Phase 4 API PRD must require `has_more` or `total_count`, not documentation-only semantics. |

## Corrections To Phase 2

| Phase 2 Claim | Correction | Affected Phase 4 Work |
|---|---|---|
| `Delete shim/barrel import paths` is one medium-risk item (`docs/refactor/phase2/synthesis.md:54`). | Split into three slices: true backend import shims, router callable re-export deletion, and AI Builder star-barrel migration. `ai_builder_models.py` belongs with AI Builder contract cleanup, not low-risk cleanup. | PRD-003 deletion cleanup and PRD-008 AI Builder contract. |
| Generated frontend types can be made canonical after generic API cleanup (`docs/refactor/phase2/synthesis.md:52`). | OpenAPI must be truthful first. Flow-specific multipart/evidence export schema issues block generated-client ownership. | PRD-004 OpenAPI/API consumer contract before PRD-007 frontend ownership. |
| Runtime file mapping can temporarily support both top-level `file_ids` and richer `StepRunInput.files` (`docs/refactor/phase2/synthesis.md:108-115`). | Do not design a long-lived dual shape. Make `step_inputs` canonical, remove top-level `file_ids` as a pre-production breaking API change, and use a migration proof/backfill only for persisted/dev rows and examples. | PRD-005 runtime input contract. |
| Future `flow_run_step_input_files` / `flow_run_artifacts` tables are plausible medium-term work (`docs/refactor/phase2/synthesis.md:108`, `:121`). | Block relational extraction unless an ADR proves queryability, lifecycle transition, retention, authorization, or audit requirements that JSON snapshots cannot satisfy. | ADR backlog and PRD-005/PRD-006. |
| Human review state can be described as `waiting_for_review` terminalizing the active phase (`docs/refactor/phase2/synthesis.md:134-141`). | Add a checkpoint/yield contract: worker persists checkpoint and next step pointer, releases the task, and resume dispatches a new task that rehydrates from persisted state. No worker slot waits for a human. | PRD-010 human review/pause. |
| Step rerun can say "downstream invalidation" generally (`docs/refactor/phase2/synthesis.md:121-128`). | Rerun invalidation must be DAG-derived from `flow_step_dependencies`; response should return `invalidated_step_ids`, not ordinal ranges. | PRD-003 step rerun. |
| Terminalization plus audit outbox can be one item (`docs/refactor/phase2/synthesis.md:50`, `:58`). | Add a fail-open/fail-closed decision table. The default for terminal state is: if outbox insert fails, fail before changing state; if delivery fails after commit, retry from outbox and alert. | PRD-002 terminalization/observability. |
| `FlowRunService` split can be discussed as service decomposition. | Do not split services by nouns if transaction boundaries remain shared. Split by use case/phase only where it changes ownership, transaction boundary, or reviewability. | PRD-002 and PRD-009/010. |
| Concept invariants review is evidence that the plan is sound (`docs/refactor/phase2/synthesis.md:42`). | Treat Phase 1b concept invariants as consolidation, not independent adversarial validation. Claude/Gemini attacks are the adversarial evidence. | Phase 6 README wording. |

## Accepted Design Rules

### 1. Pre-Production Compatibility Policy

| Contract Type | Default | Example | Validation Before Delete |
|---|---|---|---|
| Import-only shim with zero production use | Delete in the first deletion wave. | `flow_repo.py`, `flow_version_repo.py` from `docs/refactor/phase2/synthesis.md:162-164`. | `rg` zero imports, pyright, route/import smoke tests. |
| Test-only behavior shim | Delete or rewrite tests to canonical owner. | `flow_dispatch.py` test-only alias from `docs/refactor/phase1/04-dead-and-legacy.md:61-62`. | Tests import canonical path or behavior contract. |
| Public API request field | Break now, but update OpenAPI, JS client, docs, examples, and contract tests together. | Top-level run `file_ids` at `docs/refactor/phase1/04-dead-and-legacy.md:82-83`. | API contract tests and generated-client wrapper tests pass. |
| Persisted local/dev row shape | Backfill or prove zero rows before deleting fallback. | `template_file_id`, legacy form field types, mirrored input-template cleanup at `docs/refactor/phase1/04-dead-and-legacy.md:82-86`. | DB count query, migration test, fallback source removed. |
| External provider/LLM repair path | Keep if it protects active boundary behavior with typed failure modes and tests. | AI Builder proposal repair loops at `docs/refactor/phase1/04-dead-and-legacy.md:103-106`. | Failure taxonomy, telemetry, behavior tests. |

### 2. JSONB And Relational Extraction Policy

| Decision | Rule |
|---|---|
| Default | Keep JSONB snapshots when the access pattern is run-local or step-local and the shape can be versioned and parsed. |
| Required before table extraction | An ADR must show at least one of: cross-run query need, row-level lifecycle state, row-level retention, row-level authorization, row-level audit, or FK integrity that JSONB cannot provide cleanly. |
| Short-term owner | Versioned Pydantic/dataclass parser for owned payload envelopes, not a generic `dict[str, Any]` bag. |
| Explicit non-goal | Do not type arbitrary user/LLM output as if the platform owns its schema. Type the envelope and provenance; preserve free-form output behind a named JSON value boundary. |

### 3. Runtime Long-Running Operation Policy

| Operation | Required Mechanic | Failure Policy |
|---|---|---|
| Create run | Idempotency key fingerprint uses normalized canonical request. | Same key and same fingerprint returns existing run; same key and different fingerprint returns conflict. TTL behavior must be documented. |
| Terminalization | One idempotent command updates run, step results, attempts, audit outbox, and observability. | If outbox insert fails, do not change terminal state. If outbox delivery later fails, keep terminal state and alert/retry. |
| Human review pause | Worker persists checkpoint, next-step pointer, editable payload, and review revision, then exits. | Resume validates expected revision and dispatches a fresh task. Worker slots never wait on humans. |
| Step rerun | Rerun command computes transitive downstream dependencies from the DAG. | Response names `invalidated_step_ids`; stale downstream evidence is invalidated or superseded according to a declared policy. |
| Redispatch | Operational stale-queued recovery only. | Do not reuse redispatch semantics for rerun, resume, or user retry. |

### 4. API And Frontend Contract Policy

| Area | Rule |
|---|---|
| OpenAPI | Fix flow-specific schema bugs at endpoint/schema source. A named global OpenAPI compatibility module may exist only for genuinely global generator gaps. |
| Generated types | Generated `schema.d.ts` becomes canonical only after OpenAPI source issues are resolved and tested. |
| Pagination | New/refactored list endpoints must expose `has_more` or `total_count`; documenting page-count-only `count` is insufficient. |
| Authorization | No flow/AI Builder router may read raw `Request.state.api_key_scope_*`; route code must use `FlowPrincipal` plus typed policy action helpers. |
| Frontend state | Exactly one owner per workflow state. A Driver/Service split is allowed only if one side is stateless transport/parser or pure reducers, not a mirrored state owner. |

## Reconciled Execution Order

This order supersedes the Phase 2 "Top 20" as implementation guidance. Phase 6 converts it into the canonical executable batch table in `docs/refactor/implementation-order.md`; use that file for scheduling implementation work.

| Wave | Slice | Why This Comes Here | Blocks / Unblocks |
|---:|---|---|---|
| 0 | Characterization tests and route/schema pins | Before changing contracts, pin current route paths, operation IDs, evidence export behavior, upload schema, status lifecycle projections, and one runtime API-plus-worker happy path. | Unblocks safe deletion and OpenAPI repair. |
| 1 | True deletion cleanup | Delete import-only shims, router callable re-exports, stale frontend aliases, and tests that only preserve those paths. | Reduces false owners before deeper work. |
| 2 | OpenAPI source truth and API consumer basics | Fix multipart upload schema at route/model source, align evidence export response, add `has_more`/`total_count`, add missing `flows.published` client method. | Unblocks generated frontend type ownership. |
| 3 | Status lifecycle and terminalization foundation | Add canonical lifecycle projection and terminalization command with explicit audit/outbox policy. | Required before review/rerun states and observability. |
| 4 | Access policy and permission migration | Replace raw AI Builder scope reads with `FlowPrincipal`/typed actions; define migration from existing permissions to granular actions. | Required before pause/resume/review/rerun permissions. |
| 5 | Published definition and runtime input contracts | Version/parse published definitions; make `step_inputs` the only run file mapping request shape; delete top-level `file_ids` source contract. | Required before generated TS, rerun, pause/review. |
| 6 | Generated frontend contract ownership | Replace manual flow runtime types with generated aliases and narrow UI-only types after OpenAPI is truthful. | Unblocks frontend workflow ownership refactors. |
| 7 | Runtime observability and runbooks | Add recorder/metrics/runbooks on the lifecycle path, not as a generic manager. | Makes runtime incidents supportable before feature expansion. |
| 8 | AI Builder backend and prompt contracts | Split proposal/planner ownership only after generated schema and prompt-as-contract audit are specified. | Avoids refactoring code while prompt contracts remain invisible. |
| 9 | Frontend authoring/runtime ownership | Remove Driver/Service mirroring, route direct mutations, and run-launch component orchestration using generated types. | Prepares UI for new runtime features without fake states. |
| 10 | Step rerun | Implement DAG-aware rerun only after lifecycle, evidence/provenance, idempotency, permissions, and tests exist. | Feature work. |
| 11 | Human review pause/edit/resume | Highest-risk feature: checkpoint/yield, audit, permission, evidence, API, frontend, and recovery all move together. | Feature work; do last. |

## Feature-Gap Contract Requirements

Each Phase 4 feature PRD must include the following before implementation.

| Feature | Required Contract Detail |
|---|---|
| Per-step file mapping | Canonical JSON request example using `step_inputs`; rejection example for top-level `file_ids`; idempotency fingerprint fields; file ownership validation; runtime resolver pre/post conditions; generated-client type impact. |
| Step rerun | Endpoint JSON request and response; DAG invalidation algorithm; `invalidated_step_ids` response; preconditions for run/step status; attempt numbering; idempotency scope; audit events; evidence supersession rules; permission matrix. |
| Human review pause/edit/resume | Definition-level checkpoint config; persisted checkpoint schema; worker-yield sequence; resume redispatch sequence; stale edit conflict; original vs edited evidence semantics; audit fail policy; permission matrix; frontend state owner. |
| Runtime terminalization | State transition table; failure categories; audit outbox fail-open/fail-closed table; duplicate terminalization behavior; open-attempt closure; task timeout/reconciler behavior. |
| Generated types | Source OpenAPI corrections; generated schema diff; wrapper type aliases; deleted manual types; frontend typecheck scope; rollback if generated schema exposes an invalid public name. |

## Do Not Do Additions

| Do Not | Reason |
|---|---|
| Do not treat `ai_builder_models.py` star-barrel deletion as a small cleanup. | It is import churn tied to AI Builder contract ownership. |
| Do not add `files` beside `file_ids` in `StepRunInput` without deleting the old request shape in the same planned migration. | Dual public request shapes would become the next compatibility burden. |
| Do not add `flow_run_artifacts` or `flow_run_step_inputs` tables without an ADR proving row-level needs. | Typed JSON snapshots may be simpler and sufficient. |
| Do not block a Celery worker while a human reviews output. | Human review must checkpoint, yield, and rehydrate. |
| Do not invalidate rerun downstream steps by ordinal order. | The flow is a dependency graph; invalidation must traverse dependencies. |
| Do not hide flow-specific OpenAPI fixes in a compatibility patch module. | Fix endpoint signatures/models where the schema originates. |
| Do not default-grant new pause/resume/review permissions from legacy manage/run roles without a migration decision. | Permission expansion is a security behavior change. |
| Do not split `FlowRunService` into multiple services unless transaction boundaries or true owners change. | Same session and same transaction across three services is shallower, not cleaner. |
| Do not call Phase 1b concept-invariants agreement independent validation. | It is useful consolidation; Claude/Gemini are the adversarial validation. |

## Remaining Disagreements

| Topic | Decision | Confidence |
|---|---|---|
| Immediate deletion of top-level `file_ids` | We accept Gemini's pre-production deletion stance for source/API contract. We keep Agent D's requirement to update OpenAPI, `intric-js`, idempotency, examples, and tests together, and to handle persisted/dev row fallout deliberately. | High |
| Whether Service or route owns AI Builder frontend state | Reopened. Phase 4 should require one owner and forbid mirroring. It may choose Service-as-state-owner or route `$state` owner after inspecting Svelte ergonomics, but Driver must stop owning parallel mutable state. | Medium |
| Whether terminal audit should fail terminalization if outbox insert fails | Default is fail before state change for terminal audit. This is stricter than fail-open runtime side-effect audit. If product/platform rejects this, it needs an ADR because compliance/support trade-off changes. | Medium-high |
| Prompt-as-contract audit | Claude could not fully inspect Agent A, but the concern is valid enough to add a Phase 4 PRD section. AI Builder prompts and knowledge-pack text are runtime contracts and need a review owner before code-only refactors. | Medium |

## Acceptance Criteria For Phase 4

- [ ] `docs/refactor/phase4/refactor-plan.md` uses the reconciled execution order, not the raw Phase 2 Top 20 ordering.
- [ ] Every PRD contains problem, goals, non-goals, users, current-state evidence, proposed future state, requirements, design, alternatives, acceptance criteria, implementation checklist, tests, risks, rollback/recovery, dependencies, and open questions.
- [ ] Runtime PRDs include pre/post conditions and fail-open/fail-closed tables for audit, idempotency, checkpointing, and generated-type gates.
- [ ] API PRDs require OpenAPI source fixes before generated frontend type migration.
- [ ] Feature PRDs include JSON request/response examples and state transition tables.
- [ ] Data-model PRDs require ADR proof before new relational tables for run-local artifacts or step inputs.
- [ ] Permission work includes migration mapping from existing `FLOWS_MANAGE` / flow aliases to granular actions.
- [ ] Test work creates small behavior/contract tests before deleting or reshaping public contracts.

## Risk Register After Reconciliation

| Risk | Severity | Mitigation |
|---|---:|---|
| Plan becomes a giant refactor because every slice depends on every other slice. | High | Phase 4 must enforce waves and per-wave acceptance tests. |
| Generated frontend type migration fails because OpenAPI remains patched globally. | High | Fix endpoint/schema source first and pin generated schema behavior. |
| Runtime feature work starts before terminalization and status lifecycle are canonical. | High | Phase 4 marks rerun and human review as blocked by lifecycle/terminalization PRDs. |
| Deletion work removes persisted-shape fallback without DB proof. | Medium-high | Require zero-row queries or migrations for row-shape fallbacks. |
| Compatibility work preserves dual public API shapes too long. | Medium-high | No indefinite dual request shapes; every compatibility path needs deletion criteria and owner. |
| Audit outbox policy causes terminalization failures during audit outage. | Medium | Make this explicit, test it, alert on it, and ADR if product chooses fail-open instead. |
| Permission migration accidentally expands access. | High | Map old roles to new actions explicitly and test denial cases. |

## Confidence

Medium-high. The major reviewer attacks were valid and are now reflected in ordering, PRD requirements, and design rules. Remaining uncertainty is concentrated in exact frontend state ownership, terminal audit fail policy, and whether future artifact/input access patterns justify relational tables.
