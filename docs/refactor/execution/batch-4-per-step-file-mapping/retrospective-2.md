# Batch 4 Retrospective - Iteration 2

## A. Plan adherence

| Check | Result | Evidence |
|---|---|---|
| Did I implement what the plan said I would implement? | pass | `FlowRunCreateRequest` exposes `step_inputs` and rejects removed top-level `file_ids` (`backend/src/intric/flows/api/flow_models.py:416-445`); projection tables exist (`backend/src/intric/database/tables/flow_tables.py:610-750`). |
| Did I stay within the file scope listed in the plan? | pass | `plan.md` now lists the added evidence/export/output-payload and model-test files before Iteration 2 validation. |
| If I changed scope, did I update the plan FIRST and re-run /plan, not silently drift? | pass | Claude Iteration 1 findings were reconciled in `claude-reconciliation-1.md`; `plan.md` was updated before Iteration 2 validation to include request-model validation, output-alias removal, and the added tests. |
| Did the behavior pins land BEFORE any deletion? | pass | Removed-shape API pin posts a real body before relying on deletion (`backend/tests/integration/flows/test_flow_consumer_api_contract.py:217-234`); OpenAPI/client pins were updated before old request source paths were removed. |
| Did I preserve every load-bearing decision from `docs/refactor/phase7/implementation-readiness.md` that applies to this batch? | pass | No compatibility adapter, no generated-client package rename, no `intric.*` to `eneo.*` namespace migration, and no Batch 5 frontend type migration beyond the narrow `intric-js` wrapper/schema patch. |

## B. Acceptance criteria

| Check | Result | Evidence |
|---|---|---|
| Have I checked every acceptance criterion from the PRD against the actual code, not just against intent? | pass | Request schema, canonical step inputs, mapping projections, idempotency/client behavior, and evidence/runtime behavior are pinned by source/test lines below. |
| For each criterion: cite the test or file:line that satisfies it. | pass | Schema/rejection: `backend/src/intric/flows/api/flow_models.py:416-445`, `backend/tests/integration/flows/test_flow_consumer_api_contract.py:217-234`; input projection: `backend/tests/integration/flows/test_flow_step_file_mapping_contract.py:119-236`; result projection: `backend/tests/integration/flows/test_flow_step_file_mapping_contract.py:241-362`; client wrapper: `frontend/packages/intric-js/src/endpoints/flows.test.js:219-281`; output alias removal: `backend/src/intric/flows/runtime/step_execution_runtime.py:274-286`. |
| Are there any criteria I marked `done` based on intent rather than evidence? | pass | No. Iteration 2 evidence cites source/test locations and validation outcomes in `journal.md`; the PRD literal `legacy` error-code wording is explicitly classified as overridden by the user's in-loop clarification. |

## C. Behavior pins and validation

| Check | Result | Evidence |
|---|---|---|
| Did every validation command from `implementation-order.md` run? | pass | Operationalized Batch 4 commands ran locally in `validation-2.log`; Docker commands remain blocked before execution by host approval policy and are recorded as environment-blocked in `journal.md`. |
| Did every command pass, OR is the failure a known baseline issue documented in `phase0/baseline.md`? | pass | Product/API/client commands passed. The full unit slice still has the known local WeasyPrint `libgobject-2.0-0` environment failure; `phase0/baseline.md:157` classifies environmental command failures separately and Batch 3/4 journals record this exact native-library gap. The same unit slice with the renderer case deselected passed: `292 passed, 2 deselected, 20 warnings`. |
| Did the behavior pins added in this batch actually exercise the behavior they claim to pin? | pass | The removed-shape test goes through HTTP/FastAPI body parsing (`backend/tests/integration/flows/test_flow_consumer_api_contract.py:224-234`); projection tests assert persisted DB rows, not mocks (`backend/tests/integration/flows/test_flow_step_file_mapping_contract.py:202-236`, `:343-362`). |

## D. Pre-production deletion discipline

| Check | Result | Evidence |
|---|---|---|
| Did I delete every Tier A item the plan said to delete? | pass | `apply_legacy_step_one_adapter` and route/service top-level `file_ids` forwarding are gone; removed-shape grep has only the intentional negative model test match. |
| Did I leave every Tier B item alone (or follow the proper Tier B protocol with proof)? | pass | Runtime input evidence still exposes step-scoped `runtime_input.file_ids`; generated output evidence uses `generated_file_ids` and declared artifacts, while the unshipped output alias `file_ids` was removed per user clarification. |
| Did I introduce ANY new compatibility shim, fallback path, "support both old and new" branch, or `legacy_*` named symbol? | pass | Removed top-level request shape rejects at the request model (`backend/src/intric/flows/api/flow_models.py:437-445`); runtime stripping reads the centralized reserved-key set and no longer adapts old request files (`backend/src/intric/flows/runtime/step_input_resolution.py:506-513`). |
| Did I introduce any new `Any`, `dict[str, Any]`, `except Exception`, `HTTPException` outside HTTP adapters, `as any`, `@ts-ignore`, or `@ts-expect-error`? | pass | New `dict[str, Any]` usage stays at HTTP/JSON boundaries already present in Flow models; the validator is typed as `object` and Pyright passes. No broad exception or TS ignore was added. |

## E. Single source of truth

| Check | Result | Evidence |
|---|---|---|
| Did I introduce duplicate logic for any concept the plan named as having a canonical home? | pass | Reserved orchestration keys are centralized in `FLOW_RUN_ORCHESTRATION_INPUT_KEYS` (`backend/src/intric/flows/flow_run_step_inputs.py:18-20`) and reused by service/runtime (`backend/src/intric/flows/runtime/step_input_resolution.py:506-513`). |
| If I added a new utility/helper file, can I name the domain concept it represents? | n/a | No new helper/utility file was added. |

## F. File splits and naming

| Check | Result | Evidence |
|---|---|---|
| If I split a file, did I split by responsibility, not LOC? | n/a | No file split. |
| Did I avoid prohibited file names (`utils`, `helpers`, `common`, `shared`, `manager`, `misc`)? | pass | New files are a migration and a per-step file-mapping contract test. |
| Does every new file represent one named domain concept? | pass | `test_flow_step_file_mapping_contract.py` covers the per-step file mapping contract; migration `20260430_flow_step_file_mappings.py` adds the two mapping projections. |

## G. Comments and readability

| Check | Result | Evidence |
|---|---|---|
| Did I delete comments that restate code instead of explaining intent? | pass | Obsolete old-shape test expectations were removed/replaced; no restating comments were added. |
| Did I avoid adding "what" comments where better naming or extraction would do? | pass | The only new source comment explains the non-obvious artifact-source precedence, not line mechanics. |
| If I added a non-trivial comment, does it explain a non-obvious invariant, trade-off, or constraint? | pass | The comment at `backend/src/intric/flows/infrastructure/flow_repo.py:643-646` explains why `declared_artifact` wins when a file appears in both generated and declared outputs. |

## H. Test quality

| Check | Result | Evidence |
|---|---|---|
| Are the tests I added behavior tests, not implementation tests? | pass | Tests assert HTTP error shape, DB projection rows, OpenAPI/client behavior, and output payload shape. |
| Did I avoid mocking internal collaborators just to isolate implementation? | pass | The key new pins use integration DB/API paths (`backend/tests/integration/flows/test_flow_step_file_mapping_contract.py`, `backend/tests/integration/flows/test_flow_consumer_api_contract.py`). |
| If I deleted tests, did I delete them because they protected code being intentionally removed, not because they were inconvenient? | pass | Old top-level request-shape assertions were removed or rewritten because the source contract was intentionally removed and replaced by negative-contract pins. |

## I. Boundary discipline

| Check | Result | Evidence |
|---|---|---|
| Did I keep ORM models out of domain/application logic? | pass | ORM projection writes stay in repositories; service passes typed projection data through `StepInputFileProjection`. |
| Did I keep Pydantic schemas out of domain logic? | pass | `FlowRunCreateRequest` remains an API schema; runtime/application code uses Flow domain/runtime contracts. |
| Did I keep `HTTPException` out of domain code? | pass | Removed-shape rejection uses project `BadRequestException`; no `HTTPException` was added. |
| Did I keep Celery payloads as typed commands with IDs, not mutable state blobs? | pass | No Celery command payload shape changed; executor only passes `attempt_no` to result persistence. |

## J. Scope and risk

| Check | Result | Evidence |
|---|---|---|
| Did I touch any code outside Flow / Flow AI Builder? | pass | Changes are Flow backend, Flow `intric-js` wrapper/schema/tests, migration, and batch docs. Known unrelated dirty files remain untouched. |
| If yes, was it a shared dependency directly required by this batch, and did I document why? | n/a | No unrelated shared dependency changed. |
| Are there carry-forward risks I should record in the journal for the next batch? | pass | Docker blockage, local WeasyPrint dependency, PRD literal error-code drift from the user's no-legacy clarification, and Batch 5 generated-client migration ownership are recorded in `journal.md`. |

## Final Gate

- Fail count: 0.
- Gate: GREEN for iteration 2.
- Stop condition status: not complete until Claude implementation review Iteration 2 returns no accepted or partial findings.
