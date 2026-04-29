# Batch 1 — API Source Truth Retrospective (Iteration 1)

Filled in per `docs/refactor/execution/retrospective-checklist.md`.

## A. Plan adherence

- A1: pass — Implemented the planned API source-truth work: Flow pagination ownership, upload OpenAPI postprocessor deletion, evidence export documentation/validation, `intric-js` wrapper pins, and maintainer playbook (`docs/refactor/execution/batch-1-api-source-truth/journal.md`).
- A2: pass — Source/test changes stayed within Flow API, shared pagination model, server OpenAPI postprocessing, `intric-js` Flow wrapper/generated schema, and Batch 1 docs; unrelated dirty files remain unstaged/unmodified.
- A3: pass — Scope changes from Claude's plan critique were recorded before implementation in `docs/refactor/execution/batch-1-api-source-truth/plan.md` and the journal.
- A4: pass — Behavior pins were added or rewritten before source-truth cleanup: OpenAPI pagination/upload/evidence pins in `backend/tests/unit/test_flow_openapi_contract.py:390`, API runtime consumer pin in `backend/tests/integration/flows/test_flow_consumer_api_contract.py:106`, and wrapper pins in `frontend/packages/intric-js/src/endpoints/flows.test.js:43`.
- A5: pass — Load-bearing decisions were preserved: no generated package rename, no Python namespace rename, no Tier B deletion, no compatibility aliases, and current idempotency retention semantics are documented instead of migrated.

## B. Acceptance criteria

- B1: pass — Upload OpenAPI source of truth is route-owned; the Flow upload postprocessor is absent from `backend/src/intric/server/main.py`, and upload schema pins assert `upload_file` binary shape at `backend/tests/unit/test_flow_openapi_contract.py:609`.
- B2: pass — Evidence export is explicitly documented and validated by the route at `backend/src/intric/flows/api/flow_run_evidence_router.py:137` and `backend/src/intric/flows/api/flow_run_evidence_router.py:258`, with OpenAPI coverage at `backend/tests/unit/test_flow_openapi_contract.py:685`.
- B3: pass — Pagination now uses `OffsetPaginatedResponse[T]` at `backend/src/intric/main/models.py:137`, Flow list over-fetch at `backend/src/intric/flows/api/flow_authoring_router.py:224`, run-list over-fetch at `backend/src/intric/flows/api/flow_run_execution_router.py:258`, and OpenAPI pins at `backend/tests/unit/test_flow_openapi_contract.py:390`.
- B4: pass — Start-run/poll/result consumer behavior is covered by the API contract at `backend/tests/integration/flows/test_flow_consumer_api_contract.py:106`.
- B5: pass — Generated-client-sensitive schema was updated narrowly in `frontend/packages/intric-js/src/types/schema.d.ts:15547`, `frontend/packages/intric-js/src/types/schema.d.ts:31937`, `frontend/packages/intric-js/src/types/schema.d.ts:33583`, and `frontend/packages/intric-js/src/types/schema.d.ts:34042`.
- B6: pass — The generated-client/package naming decision remains deferred to Batch 5 in the plan and journal.

## C. Behavior pins and validation

- C1: pass — Implementation-order validation ran locally after Docker was blocked by host tool policy; Docker fallback is recorded in the journal.
- C2: pass — Local validation passed: backend tests `116 passed`, pyright `0 errors`, frontend Flow wrapper tests `13 passed`, diff checks clean.
- C3: pass — New/updated pins exercise behavior, not identities: API integration creates a published flow, starts/replays/conflicts runs, lists with `has_more`, polls, and reads step output (`backend/tests/integration/flows/test_flow_consumer_api_contract.py:117`).

## D. Pre-production deletion discipline

- D1: n/a — No Tier A API source files were planned for deletion beyond removing the Flow upload OpenAPI postprocessor block.
- D2: pass — Tier B public/persisted surfaces remain: top-level `file_ids`, old form field types, HTTP config converters, historical evidence keys, `_alias` operation IDs, and AI Builder tag postprocessing.
- D3: pass — No new compatibility shim, fallback branch, dual namespace, or `legacy_*` symbol was introduced.
- D4: pass — New `dict` use is limited to HTTP/test/docs schema dictionaries; no new domain/application `Any` contract, broad `except Exception`, domain `HTTPException`, `as any`, or TypeScript ignore was added.

## E. Single source of truth

- E1: pass — Ownership moved toward router/schema owners: upload/evidence/pagination contracts are expressed in routers/models and pinned by OpenAPI tests, not server-level Flow-specific postprocessing.
- E2: n/a — No new utility/helper file was added.

## F. File splits and naming

- F1: n/a — No source file split was performed.
- F2: pass — No prohibited generic file name was added.
- F3: pass — New files are named by purpose: `test_flow_consumer_api_contract.py`, `api-maintainer-playbook.md`, and Batch 1 execution artifacts.

## G. Comments and readability

- G1: pass — No restating production comments were added.
- G2: pass — New production text is route/OpenAPI description or maintainer documentation, not explanatory comments over obvious code.
- G3: pass — The maintainer playbook documents non-obvious public-contract constraints around pagination, evidence attachments, and idempotency (`docs/refactor/api-maintainer-playbook.md:34`).

## H. Test quality

- H1: pass — Added tests protect API/OpenAPI/runtime/wrapper behavior rather than private callable identity.
- H2: pass — The new API consumer contract uses real API calls and DB state setup; unit router fakes are limited to direct router tests already in that file.
- H3: n/a — No tests were deleted.

## I. Boundary discipline

- I1: pass — ORM access in the new integration test is test setup only (`backend/tests/integration/flows/test_flow_consumer_api_contract.py:82`); no ORM model was introduced into domain/application logic.
- I2: pass — Pydantic schema validation was added at the HTTP adapter boundary before returning a raw evidence export `Response` (`backend/src/intric/flows/api/flow_run_evidence_router.py:258`).
- I3: pass — No `HTTPException` was added outside HTTP adapter code.
- I4: n/a — Celery payloads were not changed in this batch.

## J. Scope and risk

- J1: pass — Shared `backend/src/intric/main/models.py` changed only to add a reusable pagination contract directly required by Flow API source truth.
- J2: pass — `frontend/packages/intric-js` changes are limited to the Flow wrapper/tests/generated schema directly affected by PRD-004.
- J3: pass — Carry-forward risks are recorded in `docs/refactor/execution/batch-1-api-source-truth/journal.md`.

## Final gate

- Total fails: 0
- Gate: GREEN
- Justification: Batch 1 stayed inside PRD-004 scope, local validation is green, Tier B surfaces were retained, and Docker unavailability is isolated as a host tooling limitation rather than a product regression.
