# Claude Reconciliation 8 — Slice 9.5 Evidence Lineage

TL;DR:
1. Claude correctly identified the raw resume idempotency key as a P0 export-leak risk.
2. The implementation uses one checkpoint dump helper and excludes the raw key from raw and redacted evidence.
3. The export schema now moves to `flow-evidence-export.v5` with a typed manifest `review_checkpoint_summary`, so the version bump has a real contract change.
4. Reviewer identity remains in evidence because evidence access is tenant/run-authorized and the existing public checkpoint API already exposes those IDs.
5. Frontend generated type updates remain in Slice 9.6 per the existing batch split.

## Claude Findings Applied

| Finding | Codex decision | Evidence |
|---|---|---|
| Raw `resume_idempotency_key` could leak through `model_dump`. | Applied. Added one checkpoint export dump helper that excludes the raw field and emits `resume_key_present` instead. | `backend/src/intric/flows/flow_run_evidence_bundle.py` |
| `review_checkpoints` needed all raw/redacted bundle plumbing. | Applied. Added the section to raw bundle, redacted bundle, redaction aggregation, service fetch, and repository query. | `backend/src/intric/flows/flow_run_evidence_bundle.py`; `backend/src/intric/flows/application/flow_run_service.py`; `backend/src/intric/flows/infrastructure/flow_run_repo.py` |
| A v5 bump should change typed manifest shape. | Applied. Added typed `EvidenceReviewCheckpointSummary` and `EvidenceExportManifest.review_checkpoint_summary`. | `backend/src/intric/flows/flow_run_evidence_export_manifest.py`; `backend/src/intric/flows/flow_run_export_json.py` |
| Review lineage must pin attempt output, checkpoint original/current payload, and step-result projection. | Applied. Unit and integration tests assert original model output and current reviewed output stay separate. | `backend/tests/unittests/flows/test_flow_run_evidence.py`; `backend/tests/integration/flows/test_flow_evidence_api_contracts.py` |
| Repository order should not sort by checkpoint revision. | Applied. The evidence query orders by `step_order`, `attempt_no`, and `id`. | `backend/src/intric/flows/infrastructure/flow_run_repo.py` |
| Untested checkpoint tombstone scan added without a producer. | Applied after verification review. Removed the speculative branch. | `backend/src/intric/flows/flow_run_export_json.py` |
| Multiple active checkpoints should not silently pick the first ID. | Applied after verification review. Added typed `active_checkpoint_conflict`; `active_checkpoint_id` is set only when exactly one active checkpoint exists. | `backend/src/intric/flows/flow_run_evidence_export_manifest.py`; `backend/src/intric/flows/flow_run_export_json.py`; `backend/tests/unittests/flows/test_flow_run_evidence.py` |
| Manifest v5 should require review checkpoint summary. | Applied after verification review. Added a missing-field assertion for `review_checkpoint_summary`. | `backend/tests/unittests/flows/test_flow_run_evidence.py` |
| Repository checkpoint order should be tested with multiple rows. | Applied after verification review. Added an integration test that inserts later rows first, then asserts evidence-list order by step and attempt. | `backend/tests/integration/flows/test_flow_run_review_checkpoint_repository.py` |
| Reviewer identity exposure should be explained where a future maintainer will see it. | Applied after verification review. Added a narrow API-model comment that explains why reviewer IDs are intentionally exposed in tenant/run-authorized evidence. | `backend/src/intric/flows/api/flow_models.py` |

## Disagreements Or Deferred Items

| Claude suggestion | Decision | Reason |
|---|---|---|
| Update frontend generated `intric-js` types in the same commit as the v5 backend contract. | Deferred to Slice 9.6. | Batch 9 already reserves frontend generated types and review UI state for Slice 9.6, and the current worktree contains unrelated frontend changes that must not be mixed into Slice 9.5. |
| Fold `active_checkpoint_id` and `active_checkpoint_conflict` into a discriminated field. | Deferred to a future evidence schema bump. | The current v5 pair is explicit and tested; changing it again inside the same slice would add consumer churn for a non-blocking invariant improvement. |

## Validation

- `uv run ruff check ...` on Slice 9.5 touched backend files passed.
- `uv run ruff format --check ...` on Slice 9.5 touched backend files passed.
- `uv run pyright ...` on Slice 9.5 touched backend files passed with 0 errors.
- `uv run pytest tests/unittests/flows/test_flow_run_evidence.py tests/unittests/flows/test_flow_run_service.py::test_export_evidence_json_hashes_returned_bundle_and_manifest_by_detail tests/unit/test_flow_openapi_contract.py::test_openapi_flow_evidence_export_documents_json_attachment tests/unittests/flows/test_flow_router.py::test_flow_run_evidence_export_alias_returns_json_attachment -q` passed.
- `uv run pytest tests/integration/flows/test_flow_evidence_api_contracts.py tests/integration/flows/test_flow_run_review_checkpoint_repository.py::test_resume_review_checkpoint_requeues_run_and_replays_idempotently -q` passed.
- `uv run pytest tests/unittests/flows/test_flow_run_evidence.py tests/unittests/flows/test_flow_run_service.py tests/unit/test_flow_openapi_contract.py tests/unittests/flows/test_flow_router.py -q` passed.
- `uv run pytest tests/integration/flows/test_flow_evidence_api_contracts.py tests/integration/flows/test_flow_run_review_checkpoint_repository.py -q` passed.
- Final Claude verification passed with green light, artifact `.codex/artifacts/claude-peer-loop-review-evidence-lineage-verification-2-20260502T185328Z.md`.

## Carry-Forward

- Slice 9.6 must regenerate/update frontend API types from the v5 OpenAPI contract and the existing review checkpoint endpoints.
- The generated frontend package still contains `flow-evidence-export.v4` literals until Slice 9.6.
