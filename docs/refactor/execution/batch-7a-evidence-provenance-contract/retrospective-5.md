# Batch 7A.4 Retrospective — Evidence Single-Source Normalization

## A. Plan adherence

- pass — Implemented the 7A.4 plan in `plan.md`: tool-call evidence moved to attempt provenance for runtime/export, RAG state is explicit, and the public read field is deprecated.
- pass — Stayed within the planned files: Flow evidence/runtime/API source, focused tests, and batch docs.
- pass — Scope changed before implementation after Claude plan review: `FlowRunStepPublic.tool_calls_metadata` deprecation and OpenAPI pin were added to `plan.md` before source edits.
- pass — Behavior pins landed with the source change: RAG state precedence in `backend/tests/unittests/flows/test_flow_run_evidence.py:745`, old-row tool-call export behavior in `backend/tests/unittests/flows/test_flow_run_evidence.py:883`, and runtime no-result-copy behavior in `backend/tests/unittests/flows/test_flow_runtime_builders.py:139`.
- pass — Preserved applicable readiness decisions: no new evidence ledger, no migrations, no compatibility shim, and no frontend or Batch 8/9 work.

## B. Acceptance criteria

- pass — Tool-call evidence source is attempt provenance for evidence exports: runtime result write is `None` in `backend/src/intric/flows/runtime/step_result_builder.py:94`, bundle result dumps omit the duplicate in `backend/src/intric/flows/flow_run_evidence_bundle.py:180`, and tests preserve attempt `llm.tool_calls` in `backend/tests/unittests/flows/test_flow_run_evidence.py:910`.
- pass — RAG truthfulness states are explicit in `backend/src/intric/flows/flow_run_export_json.py:333` and `backend/src/intric/flows/flow_run_export_json.py:348`; tests cover `not_tracked`, `tracked_no_sources`, `tracked_with_sources`, `partial_corrupt`, mixed source precedence, and all-corrupt precedence in `backend/tests/unittests/flows/test_flow_run_evidence.py:745`.
- pass — Public/persisted compatibility surface is not deleted silently: `backend/src/intric/flows/api/flow_models.py:536` marks it deprecated, and `backend/tests/unit/test_flow_openapi_contract.py:392` pins the OpenAPI signal.
- pass — No criterion was marked done by intent only; every implemented behavior has a source and test citation above.

## C. Behavior pins and validation

- pass — Focused validation ran and passed: 80 backend tests, pyright 0 errors, ruff check, ruff format check, lint-imports, anti-slippage grep, and `git diff --check`.
- pass — Docker validation was attempted but blocked by local Codex approval policy before execution; local/testcontainers validation passed.
- pass — Added behavior pins exercise externally observable export/API/runtime state, not private helper calls.

## D. Pre-production deletion discipline

- n/a — No Tier A file deletion was planned for this slice.
- pass — Tier B persisted/public field remains present and is deprecated instead of deleted.
- pass — No compatibility shim, fallback path, or `legacy_*` symbol was introduced.
- pass — No new broad `Any`, untyped compatibility branch, `except Exception`, HTTP exception outside adapters, TypeScript ignore, or frontend `any` was introduced. Existing `dict[str, Any]` patterns remain in the evidence export owner.

## E. Single source of truth

- pass — Tool-call evidence export now has one owner: `FlowStepAttempts.provenance_json.llm.tool_calls`; result-level tool calls are not written for new runtime results and are omitted from evidence bundles.
- n/a — No new utility/helper file was added.

## F. File splits and naming

- n/a — No file split.
- pass — No prohibited generic files were added.
- n/a — No new file was added.

## G. Comments and readability

- pass — No comments were added to production source.
- pass — Naming carries the new behavior: `derive_rag_usage_tracking()` and `untracked_rag_summary()` describe the export responsibility.
- n/a — No non-trivial comment was added.

## H. Test quality

- pass — Tests assert behavior: export bundle shape, RAG state precedence, runtime result state, and OpenAPI deprecation.
- pass — No internal collaborator mocks were added.
- n/a — No tests were deleted.

## I. Boundary discipline

- pass — ORM models did not move into domain/application logic.
- pass — Pydantic API schema change stayed in the API model boundary.
- pass — No `HTTPException` was introduced.
- n/a — No Celery payload change.

## J. Scope and risk

- pass — Source changes stayed within Flow evidence/runtime/API owners.
- n/a — No unrelated shared dependency was changed.
- pass — Carry-forward risks are recorded in `journal.md`: public/persisted tool-call field deletion trigger, retention tombstones, artifact/file ownership, and frontend evidence alignment.

## Final gate

GREEN — 0 fails.
