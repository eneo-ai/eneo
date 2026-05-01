# Claude Reconciliation 1 — Evidence / Provenance Contract Foundation Plan

## Iteration 1 Result

- Session: `batch-7a-evidence-provenance`
- Phase: plan
- Verdict: `changes_required`
- Green light: `no`
- Minimum score: 6

Accepted findings:

- Unsupported-format deletion was broader than the router branch. The old error also appeared in startup/OpenAPI tests and generated-client-sensitive schema docs.
- Raw export reason behavior needed a policy. Decision: keep the redacted export default for current callers, but reject raw exports that omit a concrete non-default reason.
- Audit fail-closed behavior needed HTTP integration coverage, not only router unit coverage.
- Current loose manifest keys needed behavior pins before a typed manifest migration.
- Tool-call metadata and artifact JSON scanning needed current caller inventories before later destructive cleanup.

Deferred findings:

- Full generated schema regeneration is deferred to 7A.2. This slice updates only the checked-in generated schema comment for the changed public response example and validates the package.
- Retention tombstone tests are deferred because tombstone storage is a schema/data-model decision for 7A.5.

## Codex Changes After Iteration 1

- Expanded the plan to include `backend/tests/unit/test_server_startup_imports.py` and `frontend/packages/intric-js/src/types/schema.d.ts`.
- Added the raw/redacted export reason policy.
- Added audit fail-closed integration coverage to the implementation plan.
- Added a manifest key-set behavior pin.
- Added current duplicate-owner inventories for `tool_calls_metadata` and JSON artifact scanning.

## Iteration 2 Result

- Session: `batch-7a-evidence-provenance`
- Phase: verification
- Verdict: `green`
- Green light: `yes`
- Minimum score: 8

Claude agreed the revised 7A.1 plan was appropriately narrow and implementation-ready. Remaining risks were accepted as carry-forward work for later 7A slices rather than blockers for this slice.
