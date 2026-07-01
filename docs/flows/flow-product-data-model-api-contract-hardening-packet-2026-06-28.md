# Flow Product Data Model And API Contract Hardening Packet

Date: 2026-06-28

## TL;DR

Gate 0 shows Flow already uses relational tables for identity, lifecycle, tenancy, files, review, rerun, audit, and delivery state.
Gate 1 shows JSONB should mostly stay because it holds typed dynamic payloads, sparse authored config, immutable snapshots, or auditable diagnostics.
The implementation lane is Builder plan status cleanup: remove the impossible `rejected` plan status from Python, DB constraints, OpenAPI, and the generated TypeScript schema.
The adjacent cleanup is JSONB ownership hardening for Builder session state, replacing deferred registry entries with existing typed owners.
No Flow runtime behavior, review rejection behavior, endpoint shape, or frontend UI behavior should change in this batch.

## Scope

The full Gate 0/1/2 audit lives in `docs/flows/flow-data-model-production-readiness-gate0.md`.

This packet records the implementation decision and stop condition for the source slice.

## Gate Summaries

| Gate | Result | Source |
|---|---|---|
| Gate 0 ERD/ownership inventory | Relational modeling is already correct for identities, ownership, lifecycle, files, review, rerun, audit, and outboxes | `docs/flows/flow-data-model-production-readiness-gate0.md` |
| Gate 1 JSONB decision matrix | No broad relationalization justified; two Builder session registry rows are stale because typed owners already exist | `docs/flows/flow-data-model-production-readiness-gate0.md` |
| Gate 2 API consumer journey | Core runtime journey is coherent; enum changes are public and require generated client/schema validation | `docs/flows/flow-data-model-production-readiness-gate0.md` |

## Chosen Lane

Lane B: Builder status cleanup, plus tightly related JSONB ownership hardening.

### Problem

`PlanStatus.REJECTED` and `ck_builder_plans_status` allow `rejected`, but the Builder plan lifecycle only writes proposed, approved, applied, and superseded states. Review checkpoint rejection is a separate Flow runtime concept and must not leak into the AI Builder plan lifecycle.

### Why

The Builder plan status enum is public through OpenAPI and the generated TypeScript client. Carrying an impossible value adds consumer branching, test ambiguity, and a future compatibility burden before the feature has shipped.

### Current Owner

| Concept | Current owner |
|---|---|
| Builder plan domain status | `backend/src/intric/flows/ai_builder/ai_builder_domain_models.py:39` |
| Builder plan DB check | `backend/src/intric/database/tables/flow_tables.py:2058` |
| Builder plan proposal JSONB owner | `backend/src/intric/flows/infrastructure/flow_jsonb_ownership.py:484` |
| Builder session conversation JSONB | `backend/src/intric/flows/ai_builder/ai_builder_domain_models.py:81` and `backend/src/intric/flows/ai_builder/ai_builder_repo.py:473` |
| Builder session planning state JSONB | `backend/src/intric/flows/ai_builder/planning_state.py:1` and `backend/src/intric/flows/ai_builder/ai_builder_repo.py:961` |

### Proposed Canonical Owner

Keep ownership where it already belongs:

- `PlanStatus` remains the canonical Python status contract.
- `BUILDER_PLAN_STATUS_VALUES` remains the canonical DB check source in SQLAlchemy metadata.
- `ConversationMessage` owns individual persisted conversation entries.
- `PlanningState` owns the persisted planning-state snapshot and embedded schema versions.
- `FlowBuilderProposal` owns immutable plan proposal snapshots.

## What Will Change

| Area | Change |
|---|---|
| Domain enum | Delete `PlanStatus.REJECTED` |
| DB metadata | Delete `"rejected"` from `BUILDER_PLAN_STATUS_VALUES` |
| Migration | No new migration; remove `rejected` from the original unreleased AI Builder table-creation migration |
| JSONB registry | Replace deferred Builder session rows with typed owners and explicit fail-on-session-load corruption behavior |
| Tests | Add enum/check sync coverage and JSONB positive owner assertions |
| Generated client | Regenerate `frontend/packages/intric-js/src/types/schema.d.ts` if OpenAPI changes |
| Docs | Regenerate generated Flow data schema docs after registry change |

## What Will Not Change

| Non-goal | Reason |
|---|---|
| Flow runtime review rejection | It is a real runtime checkpoint decision owned by review services |
| Run/review/rerun API endpoints | Gate 2 did not prove endpoint shape is the highest-risk issue for this batch |
| JSONB table shapes | Gate 1 did not prove hidden identity or queryability that requires relationalization |
| AI Builder UX | The cleanup removes an impossible persisted state only |
| Frontend UI behavior | The only expected frontend change is generated API type drift |
| MCP/capability descriptors | Explicitly outside the prompt scope |

## Migration Plan

No new migration is added for this cleanup.

Flows and Flow AI Builder are unreleased. The cleanest pre-production shape is to edit `202603121400_add_ai_builder_tables.py` so `builder_plans` is never created with the impossible `rejected` status in the first place. Adding a new migration that removes a status introduced only by an unreleased earlier migration would preserve extra code and review burden without protecting production data.

Development databases that already applied the old branch migration should reset/replay migrations, or manually recreate `ck_builder_plans_status` from the current SQLAlchemy metadata. That is an intentional pre-production cleanup policy, not a compatibility promise.

No downgrade path is needed because no new migration revision exists for this cleanup.

The original migration carries a pre-production reset/replay note so future branch users do not mistake the edited revision for a production-safe compatibility path.

## Registry Semantics

`owner_module` means the module defining the typed model/envelope, not necessarily the repository that writes the column. This batch applies that meaning consistently across the Builder JSONB rows:

- `builder_sessions.conversation` -> `intric.flows.ai_builder.ai_builder_domain_models.ConversationMessage`
- `builder_sessions.planning_state_jsonb` -> `intric.flows.ai_builder.planning_state.PlanningState`
- `builder_plans.proposal_json` -> `intric.flows.ai_builder.ai_builder_domain_models.FlowBuilderProposal`

## API And Generated Client Impact

`PlanStatus` is OpenAPI-visible through AI Builder plan response/request models. Removing `rejected` is an intentional public contract cleanup for unreleased Flow AI Builder behavior. The generated TypeScript schema must be regenerated and committed.

## Validation Plan

Run at minimum:

```bash
cd backend && uv run pytest tests/unittests/flows/test_flow_jsonb_ownership.py tests/unittests/flows/ai_builder/test_ai_builder_models.py tests/unittests/flows/test_flow_enums.py
cd backend && uv run pytest tests/unittests/flows/test_flow_docs_site_contract.py::test_flow_developer_docs_data_schema_is_generated_from_backend_metadata
cd backend && uv run alembic heads
cd backend && uv run ruff check src/intric/flows/ai_builder/ai_builder_domain_models.py src/intric/flows/infrastructure/flow_jsonb_ownership.py src/intric/database/tables/flow_tables.py tests/unittests/flows/test_flow_jsonb_ownership.py tests/unittests/flows/ai_builder/test_ai_builder_models.py tests/unittests/flows/test_flow_enums.py alembic/versions/202603121400_add_ai_builder_tables.py
cd backend && uv run pyright src/intric/flows/ai_builder/ai_builder_domain_models.py src/intric/flows/infrastructure/flow_jsonb_ownership.py tests/unittests/flows/test_flow_jsonb_ownership.py tests/unittests/flows/ai_builder/test_ai_builder_models.py tests/unittests/flows/test_flow_enums.py
PYTHONPATH=scripts python3 -c "from pathlib import Path; from pre_push_check import run_schema_drift_check; run_schema_drift_check(Path.cwd())"
```

Broader validation remains recommended before PR merge:

```bash
cd backend && uv run pytest tests/unittests/flows
cd backend && uv run pytest tests/integration/flows
cd backend && uv run lint-imports --no-cache
cd backend && uv run pyright
```

## Validation Results

| Command | Result |
|---|---|
| `cd backend && uv run pytest tests/unittests/flows/test_flow_jsonb_ownership.py tests/unittests/flows/ai_builder/test_ai_builder_models.py tests/unittests/flows/test_flow_enums.py` | passed, 37 tests |
| `make docs:regen` | passed; regenerated Flow docs-site pages |
| `cd backend && uv run pytest tests/unittests/flows/test_flow_docs_site_contract.py::test_flow_developer_docs_data_schema_is_generated_from_backend_metadata` | passed |
| `PYTHONPATH=scripts python3 -c "from pathlib import Path; from pre_push_check import run_schema_drift_check; run_schema_drift_check(Path.cwd())"` | passed |
| `cd backend && uv run alembic heads` | passed; single head `202606281530_builder_state` |
| `cd backend && uv run ruff check src/intric/flows/ai_builder/ai_builder_domain_models.py src/intric/flows/infrastructure/flow_jsonb_ownership.py src/intric/database/tables/flow_tables.py tests/unittests/flows/test_flow_jsonb_ownership.py tests/unittests/flows/ai_builder/test_ai_builder_models.py tests/unittests/flows/test_flow_enums.py alembic/versions/202603121400_add_ai_builder_tables.py` | passed |
| `cd backend && uv run pyright src/intric/flows/ai_builder/ai_builder_domain_models.py src/intric/flows/infrastructure/flow_jsonb_ownership.py tests/unittests/flows/test_flow_jsonb_ownership.py tests/unittests/flows/ai_builder/test_ai_builder_models.py tests/unittests/flows/test_flow_enums.py` | passed |
| `cd backend && uv run pyright` | passed |
| `cd backend && uv run lint-imports --no-cache` | passed |
| `cd backend && uv run pytest tests/unittests/flows` | failed in pre-existing PDF renderer tests: 4,561 passed, 10 failed because WeasyPrint cannot load native `libgobject-2.0-0` in this local environment |
| `cd backend && uv run ruff check src/intric/flows src/intric/database/tables/flow_tables.py tests/unittests/flows tests/integration/flows` | failed on pre-existing import order in `tests/unittests/flows/test_docx_template_runtime.py`, which this batch did not touch |
| `cd backend && uv run pytest tests/integration/flows` | failed with 249 passed, 6 failed; failures are in audit outbox, runtime worker, and webhook delivery paths unrelated to Builder plan status/schema ownership |

The failing integration tests were rerun directly and still failed. The observed failure signatures are completion model fixture uniqueness and authored HTTP output-config expectations, not the Builder plan status or JSONB ownership lane.

## Remaining Production-Readiness Gaps

| Gap | Recommended next goal |
|---|---|
| One golden API consumer journey test | Add an integration test that covers inspect, upload, run, poll, review, evidence/artifacts, and rerun |
| SDK examples | Add generated-client examples after the golden API journey is stable |
| Retention/FK purge audit | Review retention purge behavior against runtime files/results/evidence |

## Review Check

Claude peer-loop iteration 1 returned `GREEN_LIGHT: no` because the original plan needed stronger fences: an enum/check sync test, consistent JSONB `owner_module` semantics, accurate fail-on-session-load registry metadata, and migration strategy clarity.

The implemented slice addresses those points and then adopts the cleaner pre-production migration strategy: no new migration, no compatibility remap, and the original AI Builder table migration no longer creates the unused status. The follow-up Claude verification that was started against the temporary migration approach was interrupted after this no-migration correction made that review context obsolete.
