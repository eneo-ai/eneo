# Batch 4 Retrospective - Iteration 1

## A. Plan adherence

| Check | Result | Evidence |
|---|---|---|
| Did I implement what the plan said I would implement? | pass | `FlowRunCreateRequest` now has `step_inputs` and no top-level `file_ids` (`backend/src/intric/flows/api/flow_models.py:431-433`); mapping tables exist (`backend/src/intric/database/tables/flow_tables.py:609-758`). |
| Did I stay within the file scope listed in the plan? | pass | Changed files are the planned Flow/API/runtime/client/docs files plus `backend/tests/integration/flows/test_flow_runtime_worker_contract.py`, now added to `plan.md`. |
| If I changed scope, did I update the plan FIRST and re-run /plan, not silently drift? | pass | The only implementation-discovered addition was reserved inline payload key rejection; `plan.md` now records it as part of request/source-of-truth hardening. |
| Did the behavior pins land BEFORE any deletion? | pass | OpenAPI/router/service/client tests were rewritten for removed `file_ids` before validating deletion; see `backend/tests/unit/test_flow_openapi_contract.py:533-543` and `backend/tests/unittests/flows/test_flow_router.py:790-812`. |
| Did I preserve every load-bearing decision from `docs/refactor/phase7/implementation-readiness.md` that applies to this batch? | pass | No dual namespace, no compatibility adapter, no generated-client package rename; `intric-js` wrapper stays scoped to required contract changes. |

## B. Acceptance criteria

| Check | Result | Evidence |
|---|---|---|
| Have I checked every acceptance criterion from the PRD against the actual code, not just intent? | pass | Request schema, runtime resolver, DB projection, idempotency, client wrapper, and evidence tests are cited below. |
| For each criterion: cite the test or file:line that satisfies it. | pass | Schema: `backend/tests/unit/test_flow_openapi_contract.py:533-543`; input projection: `backend/tests/integration/flows/test_flow_step_file_mapping_contract.py:119-236`; result projection: `backend/tests/integration/flows/test_flow_step_file_mapping_contract.py:241-361`; reserved keys: `backend/tests/unittests/flows/test_typed_io_run_service.py:92-119`; client wrapper: `frontend/packages/intric-js/src/endpoints/flows.test.js:220-281`. |
| Are there any criteria I marked `done` based on intent rather than evidence? | pass | All marked criteria have source/test citations and validation outcomes in `journal.md`. |

## C. Behavior pins and validation

| Check | Result | Evidence |
|---|---|---|
| Did every validation command from `implementation-order.md` run? | pass | Operationalized Batch 4 commands ran; see `journal.md` validation section and ignored `validation-1.log`. |
| Did every command pass, OR is the failure a known baseline issue documented in `phase0/baseline.md`? | pass | Batch 4 product/API/client commands passed. One extra full-unit local failure is WeasyPrint missing `libgobject-2.0-0`, previously recorded in Batch 3 journal and classified in this journal; Docker validation is blocked by Codex approval policy. |
| Did the behavior pins added in this batch actually exercise the behavior they claim to pin? | pass | Integration tests assert JSON snapshot equals input projection rows and result file projection rows (`backend/tests/integration/flows/test_flow_step_file_mapping_contract.py:202-236`, `:343-361`); client tests assert pre-request rejection (`frontend/packages/intric-js/src/endpoints/flows.test.js:220-281`). |

## D. Pre-production deletion discipline

| Check | Result | Evidence |
|---|---|---|
| Did I delete every Tier A item the plan said to delete? | pass | `apply_legacy_step_one_adapter` is gone; grep for old top-level execution paths returned no matches. |
| Did I leave every Tier B item alone or follow the proper Tier B protocol? | pass | Historical evidence keys such as `generated_file_ids` remain readable; result projection reads them instead of deleting them (`backend/src/intric/flows/infrastructure/flow_repo.py:626-647`). |
| Did I introduce ANY new compatibility shim, fallback path, "support both old and new" branch, or `legacy_*` named symbol? | pass | Removed shapes reject with `flow_run_top_level_file_ids_not_supported`; runtime resolver now reads only `step_inputs` (`backend/src/intric/flows/runtime/step_input_resolution.py:293-302`). |
| Did I introduce any new `Any`, `dict[str, Any]`, broad `except Exception`, `HTTPException` outside HTTP adapters, `as any`, `@ts-ignore`, or `@ts-expect-error`? | pass | New boundary dict types are HTTP/application payload contracts; the JSON guard catches `JSONDecodeError`/`UnicodeDecodeError`, not broad `Exception` (`backend/src/intric/flows/api/flow_run_execution_router.py:111-122`). |

## E. Single source of truth

| Check | Result | Evidence |
|---|---|---|
| Did I introduce duplicate logic for any concept the plan named as having a canonical home? | pass | Normalization remains in `flow_run_step_inputs.py`; persistence projections live with run creation/result persistence owners (`backend/src/intric/flows/application/flow_run_service.py:391-417`, `backend/src/intric/flows/infrastructure/flow_run_repo.py:125-146`, `backend/src/intric/flows/infrastructure/flow_repo.py:578-647`). |
| If I added a new utility/helper file, can I name the domain concept it represents? | n/a | No new helper/utility file was added. |

## F. File splits and naming

| Check | Result | Evidence |
|---|---|---|
| If I split a file, did I split by responsibility, not LOC? | n/a | No file split. |
| Did I avoid prohibited file names? | pass | New files are a migration and a domain contract test, not `utils`/`helpers`/`common`. |
| Does every new file represent one named domain concept? | pass | `test_flow_step_file_mapping_contract.py` covers per-step file mapping; migration adds `flow_run_step_input_files` and `flow_run_step_result_files`. |

## G. Comments and readability

| Check | Result | Evidence |
|---|---|---|
| Did I delete comments that restate code instead of explaining intent? | pass | Deleted obsolete test wording around top-level `file_ids`; no new explanatory comments needed. |
| Did I avoid adding "what" comments where better naming or extraction would do? | pass | New names are explicit: `_reject_removed_top_level_file_ids`, `_reject_reserved_input_payload_keys`, `StepInputFileProjection`. |
| If I added a non-trivial comment, does it explain a non-obvious invariant, trade-off, or constraint? | n/a | No non-trivial source comments added. |

## H. Test quality

| Check | Result | Evidence |
|---|---|---|
| Are the tests I added behavior tests, not implementation tests? | pass | Tests assert API/schema rejection, persisted projection rows, and client request behavior, not private calls. |
| Did I avoid mocking internal collaborators just to isolate implementation? | pass | Integration projection tests use DB repositories; unit tests use existing service/router seams. |
| If I deleted tests, did I delete them because they protected code being intentionally removed, not because they were inconvenient? | pass | The duplicate old-shape service test was removed with the service `file_ids` input path; new tests pin rejection and canonical step input behavior. |

## I. Boundary discipline

| Check | Result | Evidence |
|---|---|---|
| Did I keep ORM models out of domain/application logic? | pass | ORM projection rows are written in repositories; service passes typed projection data (`backend/src/intric/flows/application/flow_run_service.py:404-417`, `backend/src/intric/flows/infrastructure/flow_run_repo.py:125-146`). |
| Did I keep Pydantic schemas out of domain logic? | pass | Pydantic request schema remains in API models; domain/runtime code uses runtime models and value objects. |
| Did I keep `HTTPException` out of domain code? | pass | New rejection uses `BadRequestException`; HTTP translation remains at adapter boundary. |
| Did I keep Celery payloads as typed commands with IDs, not mutable state blobs? | pass | No Celery payload shape changed; executor only passes `attempt_no` into result persistence. |

## J. Scope and risk

| Check | Result | Evidence |
|---|---|---|
| Did I touch any code outside Flow / Flow AI Builder? | pass | Only Flow backend, `intric-js` Flow endpoint/schema, and batch docs changed; unrelated dirty files remain untouched. |
| If yes, was it a shared dependency directly required by this batch, and did I document why? | n/a | No unrelated shared dependency changed. |
| Are there carry-forward risks I should record in the journal for the next batch? | pass | Docker blockage, local WeasyPrint dependency, and Batch 5 generated-client migration ownership are recorded in `journal.md`. |

## Final Gate

- Fail count: 0.
- Gate: GREEN for iteration 1.
- Stop condition status: not complete, because the loop requires iteration counter `>= 2` and Claude implementation review has not run yet.
