# Batch 2 - Permissions And Data Contracts Retrospective (Iteration 1)

Filled in per `docs/refactor/execution/retrospective-checklist.md`.

## A. Plan adherence

- A1: pass - Implemented the planned typed policy, AI Builder authorization helper, published-definition owner, idempotency pins, and data-contract docs from `plan.md`.
- A2: pass - Changes stayed in the listed Flow / Flow AI Builder source, test, and docs files; unrelated `PRODUCT.md`, frontend icon types, and `scripts/run_codex_review.sh` remained untouched.
- A3: n/a - No scope change required a plan rewrite; deleting source-only AI Builder router wrapper tests followed the plan's Tier A test-seam cleanup direction.
- A4: pass - Behavior pins landed before deletion: policy tests at `backend/tests/unittests/flows/test_flow_access_policy.py:47`, parser tests at `backend/tests/unittests/flows/test_published_definition_contract.py:33`, and idempotency tests at `backend/tests/unittests/flows/test_flow_run_service.py:448` / `backend/tests/integration/flows/test_flow_run_repository.py:371`.
- A5: pass - Preserved readiness decisions: Tier B persisted/public surfaces are documented in `docs/refactor/flow-permission-and-data-contracts.md:25` and `docs/refactor/flow-permission-and-data-contracts.md:36`, with no migrations or namespace/package renames.

## B. Acceptance criteria

- B1: pass - One policy module owns typed Flow actions and permission mapping at `backend/src/intric/flows/flow_access_policy.py:17` and `backend/src/intric/flows/flow_access_policy.py:59`; source guard test is `backend/tests/unittests/flows/test_flow_access_policy.py:125`.
- B2: pass - Flow routers no longer read `Request.state.api_key_scope_*`; guard test is `backend/tests/unittests/flows/test_flow_access_policy.py:154`, and the validation `rg` found only the canonical `FlowPrincipal` owner.
- B3: pass - Published definition parser/writer owns versioned envelopes at `backend/src/intric/flows/published_definition.py:46` and `backend/src/intric/flows/published_definition.py:65`; parser round-trip tests start at `backend/tests/unittests/flows/test_published_definition_contract.py:33`.
- B4: pass - Idempotency retention is documented as row-lifetime semantics in `docs/refactor/flow-permission-and-data-contracts.md:59`, with no-row create behavior pinned in `backend/tests/unittests/flows/test_flow_run_service.py:448` and cross-principal DB isolation pinned in `backend/tests/integration/flows/test_flow_run_repository.py:371`.
- B5: pass - JSONB extraction gate exists before runtime-table implementation at `docs/refactor/flow-permission-and-data-contracts.md:70`.
- B6: pass - Future runtime table schemas and constraints are documented before implementation in `docs/refactor/flow-permission-and-data-contracts.md:85`.
- B7: pass - Permission migration mapping and legacy/future non-grants are documented in `docs/refactor/flow-permission-and-data-contracts.md:11` and tested in `backend/tests/unittests/flows/test_flow_access_policy.py:47`, `backend/tests/unittests/flows/test_flow_access_policy.py:70`, and `backend/tests/unittests/flows/test_flow_access_policy.py:86`.

## C. Behavior pins and validation

- C1: pass - Docker validation commands were attempted but rejected by host policy before execution; the plan's local fallback ran, and `validation-1.log` captures the local command outputs.
- C2: pass - Local validation passed: `git diff --check`, source guards, pyright, pytest (`213 passed`), ruff, and import-linter all passed; Docker rejection is an environment/tooling issue, not a product regression.
- C3: pass - The tests exercise behavior: policy matrix/fail-closed checks (`test_flow_access_policy.py:47`), schema parser behavior (`test_published_definition_contract.py:33`), and DB-backed idempotency isolation (`test_flow_run_repository.py:371`).

## D. Pre-production deletion discipline

- D1: pass - Deleted source-only AI Builder router wrapper/test seams and service-key route re-exports only after pins and source guards were in place.
- D2: pass - Tier B surfaces were left intact: `flow_runs.user_id`, permission aliases, published JSONB, old public/persisted request shapes, and generated-client naming are documented as retained surfaces.
- D3: pass - No new compatibility namespace, shim module, dual import path, or `legacy_*` symbol was added; `flow_permissions.py` remains the existing adapter over the new policy owner.
- D4: pass - New policy/parser code avoids broad `Any` / `dict[str, Any]`; the published parser accepts `Mapping[str, object]`, and existing legacy `Any` in large touched modules was not expanded.

## E. Single source of truth

- E1: pass - Permission mapping moved to `flow_access_policy.py`; published envelope parsing moved to `published_definition.py`; principal identity remains in `principal.py`.
- E2: pass - New files have named domain responsibilities: `flow_access_policy.py` owns Flow access policy, and `published_definition.py` owns the published definition envelope.

## F. File splits and naming

- F1: n/a - No existing file was split by LOC; new files were introduced for named domain concepts.
- F2: pass - No prohibited `utils`, `helpers`, `common`, `shared`, `manager`, or `misc` file was added.
- F3: pass - `flow_access_policy.py` and `published_definition.py` each have one clear reason to change.

## G. Comments and readability

- G1: pass - Removed router test-compat helper plumbing rather than preserving comments or fake anchors for private helpers.
- G2: pass - Added names and types rather than explanatory "what" comments; no new restating comments were introduced.
- G3: pass - The durable decision context is in `docs/refactor/flow-permission-and-data-contracts.md` rather than incidental source comments.

## H. Test quality

- H1: pass - Added behavior-focused policy, parser, service, and repository tests rather than private-call assertions.
- H2: pass - Test fakes remain at route/service/repository boundaries; the new cross-principal idempotency pin uses the real integration repository/database path.
- H3: pass - Deleted tests only for source-only router wrapper functions that were intentionally removed; existing endpoint behavior tests remain.

## I. Boundary discipline

- I1: pass - No ORM model was introduced into domain/application logic; the repository integration test uses table insertion only to create a service-key fixture row.
- I2: pass - No Pydantic schema was introduced into domain logic.
- I3: pass - No FastAPI `HTTPException` was introduced outside HTTP adapter code.
- I4: n/a - No Celery payload shape changed in this batch.

## J. Scope and risk

- J1: pass - Product code changes were limited to Flow / Flow AI Builder backend code and docs; known unrelated dirty files remained untouched.
- J2: n/a - No shared dependency outside the Flow / Flow AI Builder scope was modified.
- J3: pass - Carry-forward risks are recorded in the journal, including the retained `_resolve_litellm_params` router seam and later runtime table implementation risk.

## Final gate

- Total fails: 0
- Gate: GREEN
- Justification: Batch 2 acceptance criteria are pinned by tests and docs, local validation is green, and the only Docker gap is a host tool-policy block already anticipated by the plan.
