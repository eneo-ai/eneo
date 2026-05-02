# Claude Reconciliation 14 — Evidence Rerun Lineage

## Claude Verdict

- Plan review artifact: `.codex/artifacts/claude-peer-loop-batch-8-evidence-rerun-lineage-plan-20260502T141717Z.md`
- Plan verdict: changes required
- Implementation review artifact: `.codex/artifacts/claude-peer-loop-batch-8-slice-8-9-evidence-rerun-lineage-implementation-20260502T145607Z.md`
- Implementation verdict: changes required
- Final verification artifact: `.codex/artifacts/claude-peer-loop-claude-peer-loop-20260502T150946Z.md`
- Final verification verdict: green content, but the peer-loop parser rejected Claude's Markdown-prefixed header format.
- Parser-clean verification artifact: `.codex/artifacts/claude-peer-loop-claude-peer-loop-20260502T151334Z.md`
- Parser-clean verification verdict: green
- Green light: yes
- Minimum score: 9

## Accepted Changes

| Claude point | Codex action | Evidence |
|---|---|---|
| Rerun rows need the same raw/redacted structural coverage as the existing evidence sections. | `EvidenceBundle` and `RedactedEvidenceBundle` now carry `rerun_operations` and `rerun_invalidated_steps`, and the redactor walks both sections through the same path-aware redaction pipeline. | `backend/src/intric/flows/flow_run_evidence_bundle.py` |
| The evidence endpoint should use typed public contracts instead of exposing ad hoc dict bags. | Added `FlowRunRerunOperationPublic` and `FlowRunRerunInvalidatedStepPublic`; `FlowRunEvidenceResponse` now includes both arrays and generated frontend types were refreshed. | `backend/src/intric/flows/api/flow_models.py`, `frontend/packages/intric-js/src/types/schema.d.ts` |
| Repository reads must be tenant-scoped and deterministic. | Added tenant-filtered list methods ordered by persisted operation and invalidation fields, with integration tests for empty results, ordering, and tenant isolation. | `backend/src/intric/flows/infrastructure/flow_run_repo.py`, `backend/tests/integration/flows/test_flow_run_rerun_repository.py` |
| The hashed export bundle must not change on repeated exports of unchanged evidence. | `debug_export.generated_at` now derives from persisted evidence timestamps, including rerun operation and invalidated-step rows; tests assert repeated raw content hashes are stable. | `backend/src/intric/flows/flow_run_evidence.py`, `backend/tests/integration/flows/test_flow_evidence_api_contracts.py`, `backend/tests/unittests/flows/test_flow_run_evidence.py` |
| OpenAPI should pin the full dependency-source enum instead of a single example value. | The OpenAPI contract test now asserts the schema enum equals all `RerunDependencyKind` values. | `backend/tests/unit/test_flow_openapi_contract.py` |
| `request_fingerprint` exposure should be intentional. | The public API field now carries the support/audit correlation rationale, and the plan and journal record why evidence exposes it. | `backend/src/intric/flows/api/flow_models.py`, `frontend/packages/intric-js/src/types/schema.d.ts`, `docs/refactor/execution/batch-8-step-rerun/plan.md`, `docs/refactor/execution/batch-8-step-rerun/journal.md` |
| The generated-schema wording cleanup should be recorded. | The journal now lists the `ai_builder_domain_models.py` docstring cleanup as part of the slice scope. | `backend/src/intric/flows/ai_builder/ai_builder_domain_models.py`, `docs/refactor/execution/batch-8-step-rerun/journal.md` |

## Deferred Points

No findings.

## Verification

- `docker exec -w /workspace/backend eneo-41ae93-eneo-1 .venv/bin/ruff format src/intric/flows/flow_run_evidence.py src/intric/flows/flow_run_evidence_bundle.py tests/unittests/flows/test_flow_run_evidence.py tests/integration/flows/test_flow_evidence_api_contracts.py tests/unit/test_flow_openapi_contract.py` — passed
- `docker exec -w /workspace/backend eneo-41ae93-eneo-1 .venv/bin/pytest tests/integration/flows/test_flow_evidence_api_contracts.py -k 'rerun or evidence_export_returns_redacted_json_attachment' tests/integration/flows/test_flow_run_rerun_repository.py -k 'evidence or list_rerun' tests/unit/test_flow_openapi_contract.py -k 'evidence or export_schema' tests/unittests/flows/test_flow_models.py tests/unittests/flows/test_flow_run_evidence.py::test_build_debug_export_uses_latest_evidence_timestamp -q` — passed, 15 tests, 56 deselected
- `docker exec -w /workspace/backend eneo-41ae93-eneo-1 .venv/bin/ruff check src/intric/flows/ai_builder/ai_builder_domain_models.py src/intric/flows/api/flow_models.py src/intric/flows/application/flow_run_service.py src/intric/flows/flow_run_evidence.py src/intric/flows/flow_run_evidence_bundle.py src/intric/flows/flow_run_evidence_export_manifest.py src/intric/flows/flow_run_export_json.py src/intric/flows/infrastructure/flow_run_repo.py tests/integration/flows/test_flow_evidence_api_contracts.py tests/integration/flows/test_flow_run_rerun_repository.py tests/unit/test_flow_openapi_contract.py tests/unittests/flows/test_flow_models.py tests/unittests/flows/test_flow_router.py tests/unittests/flows/test_flow_run_evidence.py tests/unittests/flows/test_flow_run_service.py` — passed
- `bash backend/scripts/run_pyright_in_devcontainer.sh` — passed, 0 errors
- `bun run check` in `frontend/packages/intric-js` — passed
- `git diff --check` — passed
- Diff-only forbidden flow wording grep over the intended slice — no matches
- `rg -n "flow-evidence-export\\.v3" backend/src/intric/flows backend/tests frontend/packages/intric-js/src/types docs/refactor/execution/batch-8-step-rerun` — only the plan line documenting the intentional v3 to v4 schema bump matched

## Decision

Slice 8.9 is ready to commit. The evidence bundle/export path is now the single public owner for rerun operation and invalidated-step evidence, with deterministic hashing, generated client types, behavior-focused tests, and API-field documentation for the public request fingerprint.
