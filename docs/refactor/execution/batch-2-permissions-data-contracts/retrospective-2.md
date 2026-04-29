# Batch 2 - Permissions And Data Contracts Retrospective (Iteration 2)

Filled in per `docs/refactor/execution/retrospective-checklist.md`.

## A. Plan adherence

- A1: pass - Iteration 2 kept the Batch 2 implementation intact and only applied Claude-accepted polish to the published-definition error code, read-filter source guard, and audit actor owner.
- A2: pass - Changes remained in the planned Flow / Flow AI Builder source, test, and docs scope; unrelated dirty files were untouched.
- A3: n/a - No new scope was introduced; the second pass tightened already planned ownership pins.
- A4: pass - Behavior pins still precede destructive cleanup: policy pins at `backend/tests/unittests/flows/test_flow_access_policy.py:47`, parser pins at `backend/tests/unittests/flows/test_published_definition_contract.py:33`, and idempotency pins at `backend/tests/unittests/flows/test_flow_run_service.py:448` / `backend/tests/integration/flows/test_flow_run_repository.py:371`.
- A5: pass - Load-bearing Batch 2 decisions remain preserved: no migrations, no Tier B deletion, no namespace/package rename, and Docker limitation documented.

## B. Acceptance criteria

- B1: pass - `backend/src/intric/flows/flow_access_policy.py:17` and `backend/src/intric/flows/flow_access_policy.py:59` remain the typed action and permission-map owner.
- B2: pass - Router raw API-key scope reads remain prohibited by `backend/tests/unittests/flows/test_flow_access_policy.py:154`; validation source guard found only canonical `principal.py` service-key ownership hits.
- B3: pass - `backend/src/intric/flows/published_definition.py:46` and `backend/src/intric/flows/published_definition.py:65` own published-definition write/parse behavior; malformed `flow_id` now has `FLOW_DEFINITION_FLOW_ID_INVALID` at `backend/src/intric/flows/published_definition.py:19`.
- B4: pass - Row-lifetime idempotency semantics remain documented at `docs/refactor/flow-permission-and-data-contracts.md:59` and pinned by unit/integration tests.
- B5: pass - JSONB extraction gate remains documented at `docs/refactor/flow-permission-and-data-contracts.md:70`.
- B6: pass - Future runtime table schemas and constraints remain documented at `docs/refactor/flow-permission-and-data-contracts.md:85`.
- B7: pass - Permission migration behavior remains documented at `docs/refactor/flow-permission-and-data-contracts.md:11` and tested in `backend/tests/unittests/flows/test_flow_access_policy.py:47`, `backend/tests/unittests/flows/test_flow_access_policy.py:70`, and `backend/tests/unittests/flows/test_flow_access_policy.py:86`.

## C. Behavior pins and validation

- C1: pass - Docker commands were attempted and blocked by host policy before execution; local fallback commands from the plan ran again in iteration 2.
- C2: pass - `validation-2.log` records green local validation: pyright `0 errors`, pytest `214 passed`, ruff pass, import-linter `3 kept, 0 broken`, `git diff --check` pass, and source guards pass.
- C3: pass - The added malformed-`flow_id` parser row exercises the new error code at `backend/tests/unittests/flows/test_published_definition_contract.py:97`; source guard scope now matches the read-filter rule at `backend/tests/unittests/flows/test_flow_access_policy.py:171`.

## D. Pre-production deletion discipline

- D1: pass - Removed Tier A source-only pass-throughs and test seams; no Tier B persisted/public compatibility surface was deleted.
- D2: pass - Retained `flow_runs.user_id`, permission aliases, published JSONB, generated-client naming, and public request/response compatibility surfaces.
- D3: pass - No new compatibility shim, fallback path, alias namespace, or `legacy_*` symbol was added.
- D4: pass - New code still avoids broad `Any` / `dict[str, Any]`; the new published parser accepts `Mapping[str, object]`.

## E. Single source of truth

- E1: pass - Permission mapping, principal identity, and published-definition envelope ownership each have one canonical source.
- E2: pass - New files remain domain-specific: Flow access policy and published definition envelope.

## F. File splits and naming

- F1: n/a - No existing file was split.
- F2: pass - No prohibited generic file name was added.
- F3: pass - Every new file has one named domain concept and one reason to change.

## G. Comments and readability

- G1: pass - Iteration 2 removed pass-through code rather than preserving explanatory clutter.
- G2: pass - No new restating comments were added.
- G3: pass - Non-code decisions stay in the durable data-contract doc.

## H. Test quality

- H1: pass - Tests remain behavior/source-ownership pins, not private call assertions.
- H2: pass - Cross-principal idempotency remains DB-backed, and route tests continue to operate at the router boundary.
- H3: pass - Deleted tests only for intentionally removed router wrapper functions.

## I. Boundary discipline

- I1: pass - No ORM model leaked into domain/application code.
- I2: pass - No Pydantic schema leaked into domain logic.
- I3: pass - No new FastAPI `HTTPException` appeared outside HTTP adapter code.
- I4: n/a - No Celery payload shape changed.

## J. Scope and risk

- J1: pass - Work stayed in Flow / Flow AI Builder source/tests/docs and did not touch the known unrelated dirty files.
- J2: n/a - No shared dependency outside the Batch 2 scope changed.
- J3: pass - Carry-forward risks are documented in the journal and Claude reconciliation.

## Final gate

- Total fails: 0
- Gate: GREEN
- Justification: Iteration 2 resolved Claude's accepted/partial findings, validation remains green, and only documented out-of-scope baseline warnings remain.
