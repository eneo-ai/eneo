# Retrospective 1 — Evidence / Provenance Contract Foundation

## A. Plan adherence

- [x] pass — Implemented the revised 7A.1 plan: raw reason validation, unsupported-format deletion, OpenAPI/generated-schema retargeting, manifest pin, and audit fail-closed export pin (`journal.md`, Implementation Summary).
- [x] pass — Stayed within planned files plus the generated schema doc path added before implementation (`plan.md`, Planned Source/Test Changes).
- [x] pass — Scope changed after Claude plan critique, and the plan was updated before source/test edits (`journal.md`, Claude Plan Review 1).
- [x] pass — Behavior pins landed with the deletion: OpenAPI query/schema pins, raw reason rejection, audit fail-closed export integration, and manifest key-set pin (`test_flow_openapi_contract.py`, `test_flow_router.py`, `test_flow_evidence_api_contracts.py`, `test_flow_run_evidence.py`).
- [x] pass — Preserved load-bearing implementation-readiness decisions: no new evidence ledger, no migration, no compatibility shim, no frontend rewrite, and no package/namespace rename (`plan.md`, Non-Goals).

## B. Acceptance criteria

- [x] pass — Owner inventory exists with canonical owners and later-slice deletion conditions (`plan.md`, Canonical Evidence Owner Inventory and Caller Inventory).
- [x] pass — Unreachable unsupported-format compatibility was deleted and all live contract references were retargeted (`flow_run_evidence_router.py`, `test_server_startup_imports.py`, `schema.d.ts`).
- [x] pass — Raw export now requires an explicit non-default reason and redacted default remains pinned (`test_flow_router.py::test_flow_run_evidence_export_alias_rejects_raw_invalid_reason`, `test_flow_run_evidence_export_alias_returns_json_attachment`).
- [x] pass — Evidence export audit fail-closed behavior is pinned at unit and integration levels (`test_flow_router.py::test_flow_run_evidence_export_alias_fails_closed_when_audit_write_fails`, `test_flow_evidence_api_contracts.py::test_flow_run_evidence_export_fails_closed_when_audit_logging_is_unavailable`).
- [x] pass — Current manifest key set is pinned before typed manifest migration (`test_flow_run_evidence.py::test_render_evidence_json_export_adds_manifest_and_summary`).
- [x] pass — No acceptance criterion was marked done based only on intent; each item above has code/test evidence.

## C. Behavior pins and validation

- [x] pass — Inserted Batch 7A has no `implementation-order.md` row; the exact plan-listed validation commands were run and summarized in `journal.md`.
- [x] pass — All validation commands passed. Existing deprecation warnings are baseline/environment warnings, not product regressions.
- [x] pass — The added pins exercise public behavior: OpenAPI schema, router response/audit behavior, integration export fail-closed behavior, and export manifest shape.

## D. Pre-production deletion discipline

- [x] pass — Deleted the only Tier A item in this slice: the direct custom unsupported-format branch/test and its live OpenAPI/generated-schema references.
- [x] pass — Left Tier B/public/persisted surfaces alone: `tool_calls_metadata`, result JSON artifact scanning, frontend evidence readers, and retention cleanup stay documented for later slices.
- [x] pass — Introduced no compatibility shim, dual path, or fallback branch.
- [x] pass — Introduced no new `Any`, untyped domain JSON bag, broad `except Exception`, domain `HTTPException`, `as any`, `@ts-ignore`, or `@ts-expect-error`.

## E. Single source of truth

- [x] pass — Did not introduce duplicate evidence logic; duplicated existing owners are inventoried with 7A.4/7A.6 deletion conditions.
- [x] n/a — Added no utility/helper file.

## F. File splits and naming

- [x] n/a — No file split.
- [x] pass — Added no prohibited helper/common/shared/manager file.
- [x] n/a — Added no new source file.

## G. Comments and readability

- [x] n/a — Deleted no comments in this slice.
- [x] pass — Added no production comments; used named constants for the raw reason error instead of comments.
- [x] n/a — Added no non-trivial comments.

## H. Test quality

- [x] pass — Added behavior tests for public API/OpenAPI, audit metadata, fail-closed integration behavior, and export manifest shape.
- [x] pass — Did not mock internals beyond existing router/container seam style; the integration audit test exercises the HTTP path with a failing audit service override.
- [x] pass — Deleted the unsupported-format test because it preserved a deleted direct-function branch that the public FastAPI contract already rejects.

## I. Boundary discipline

- [x] pass — Kept ORM models out of domain/application logic.
- [x] pass — Kept Pydantic schemas out of domain logic.
- [x] pass — Kept HTTP error handling in the router adapter.
- [x] n/a — No Celery payload changes.

## J. Scope and risk

- [x] pass — Touched Flow backend evidence API/tests, generated `intric-js` schema docs for that API surface, and batch execution docs only.
- [x] pass — Generated schema comment update was directly required by the OpenAPI 400 response contract change and validated with package check/lint.
- [x] pass — Carry-forward risks are recorded in `journal.md`: typed manifest, provenance schema versioning, tool-call/RAG normalization, retention tombstones, artifact/file ownership, frontend evidence view-model alignment.

## Final gate

- Fail count: 0
- Gate: GREEN
