# T001 Scout Rebaseline

## TL;DR

- Branch matches the board: `feature/refactor-flows-flowai`.
- The smallest first implementation target is required runtime input enforcement when `step_inputs` is omitted or empty.
- Four P0 candidates remain valid; two are static-confirmed and two still need fresh-session or race red tests before implementation.
- The maintainability board files should be committed separately before source work; unrelated dirty files must remain unstaged.
- Frontend error rendering should be checked after the backend create-run error contract is stable.

## Dirty File Classification

| Class | Files | Decision |
|---|---|---|
| Modified unrelated | `frontend/apps/web/project.inlang/.meta.json`, `frontend/apps/web/project.inlang/README.md` | Preserve unstaged; unrelated generated/inlang changes. |
| Commit board | `docs/goals/flow-runtime-ai-builder-maintainability/goal.md`, `state.yaml`, `notes/T000-codex-source-check.md`, `notes/T000-maintainability-review-findings.md`, `notes/codex-goal-prompt.md`, `notes/T001-scout-rebaseline.md` | Stage for the separate board/docs commit. |
| Preserve as source packets | `docs/refactor/Chatgptanswer.md`, `docs/refactor/flow-ai-builder-production-readiness-review-packet.md`, `docs/refactor/flow-ai-builder-production-readiness-chatgpt-prompt.md`, `docs/refactor/flow-ai-builder-material-efficiency-review-handoff.md`, `docs/goals/flow-runtime-ai-builder-production-readiness/**` | Useful context, but not part of the maintainability board commit unless PM/owner decides to publish all source packets now. |
| Owner decision | `PRODUCT.md`, `RefactorChatgpt/`, `docs/refactor/goals.md`, `docs/refactor/new/**`, `docs/refactor/runtime-hang-and-builder-rootcause.md`, `flow_ai_builder_prd.md`, `flow_ai_builder_review.md`, `.devcontainer/devcontainer-lock.json` | Do not stage in this goal without explicit approval. |
| Ignore | `utvecklingssamtal.mp3` | Local media/input artifact; do not commit. |

## Confirmed P0 Evidence

| P0 | Status | Evidence | Next Proof |
|---|---|---|---|
| Required runtime inputs bypassed when `step_inputs` is omitted | Confirmed static | `backend/src/intric/flows/application/flow_run_service.py:459` validates submitted step inputs only inside `if step_inputs is not None`; `backend/src/intric/flows/flow_run_step_inputs.py:71` already normalizes `None` to `{}`; `backend/src/intric/flows/flow_run_step_inputs.py:196` raises `flow_run_required_step_input_missing` when required files are absent. | Real HTTP red test for omitted and empty `step_inputs`. |
| Review edit bypasses output contract validation | Confirmed static | `backend/src/intric/flows/application/flow_run_service.py:942` forwards edited payload to repository; `backend/src/intric/flows/infrastructure/flow_run_repo.py:537` writes projection; runtime validation exists in `backend/src/intric/flows/runtime/output_runtime.py:96`. | Integration/service test proving invalid edit is rejected and persisted state is unchanged. |
| Executor failure persistence may be lost | Confirmed risk, outcome unproven | `backend/src/intric/flows/runtime/executor.py:1184`, `:1255`, and `:1316` rollback/persist failure without obvious local commit; success commits at `backend/src/intric/flows/runtime/executor.py:1365`. | Fresh-session integration test after executor failure exits. |
| Late provider success may mutate terminal run | Confirmed static | `backend/src/intric/flows/runtime/executor.py:777` checks only cancelled state after provider output; `backend/src/intric/flows/infrastructure/flow_repo.py:585` upserts step result and `:597` replaces result files unconditionally. | Deterministic two-session terminalization/late-success test. |

## Recommended First Worker

Objective: TDD-fix create-run required runtime input enforcement when `step_inputs` is omitted or empty, without changing successful idempotency fingerprint semantics.

Why first: it is API-visible, aligns run-contract with run creation behavior, has an existing HTTP integration harness, and has the smallest blast radius among the P0s.

Allowed files:

- `backend/src/intric/flows/application/flow_run_service.py`
- `backend/src/intric/flows/flow_run_step_inputs.py`
- `backend/tests/integration/flows/test_flow_consumer_api_contract.py`
- `backend/tests/unittests/flows/test_flow_run_service.py`
- `backend/tests/unit/test_flow_openapi_contract.py` only if pinning the documented error contract for the touched POST route

Verification:

```bash
cd backend && uv run pytest tests/integration/flows/test_flow_consumer_api_contract.py -q
cd backend && uv run pytest tests/unittests/flows/test_flow_run_service.py -k 'create_run and step_inputs' -q
cd backend && uv run pytest tests/unit/test_flow_openapi_contract.py -q
cd backend && uv run pyright src/intric/flows/application/flow_run_service.py src/intric/flows/flow_run_step_inputs.py tests/integration/flows/test_flow_consumer_api_contract.py tests/unittests/flows/test_flow_run_service.py tests/unit/test_flow_openapi_contract.py
cd backend && uv run ruff check src/intric/flows/application/flow_run_service.py src/intric/flows/flow_run_step_inputs.py tests/integration/flows/test_flow_consumer_api_contract.py tests/unittests/flows/test_flow_run_service.py tests/unit/test_flow_openapi_contract.py
cd backend && uv run ruff format --check src/intric/flows/application/flow_run_service.py src/intric/flows/flow_run_step_inputs.py tests/integration/flows/test_flow_consumer_api_contract.py tests/unittests/flows/test_flow_run_service.py tests/unit/test_flow_openapi_contract.py
git diff --check
```

Stop if:

- The fix needs idempotency fingerprint behavior changes for successful valid requests.
- The HTTP red test cannot be made meaningful through existing `client` and `admin_token` fixtures.
- Files outside the allowed set are needed.
- Response cannot include stable code, message, and context without broader error-contract work.
- A second P0 starts leaking into the implementation.

## Test Harness Notes

- First slice should extend `backend/tests/integration/flows/test_flow_consumer_api_contract.py`, which already uses `client`, `db_container`, `admin_token`, `_create_space`, and `_create_published_flow`.
- Existing service tests around `backend/tests/unittests/flows/test_flow_run_service.py:1033` can supplement the HTTP proof, but cannot replace it.
- OpenAPI source is generated from `intric.server.main.get_application().openapi()` in `backend/tests/unit/test_flow_openapi_contract.py`; no separate generated-client command was found.

## Maintainability Hotspots

| Hotspot | Evidence | Canonical owner |
|---|---|---|
| Create-run validation split | `backend/src/intric/flows/application/flow_run_service.py:459`; `backend/src/intric/flows/flow_run_step_inputs.py:196` | `FlowRunService.create_run` always invokes the pure `flow_run_step_inputs` validator for the published runtime contract. |
| Review edit output validation gap | `backend/src/intric/flows/application/flow_run_service.py:942`; `backend/src/intric/flows/runtime/output_runtime.py:96` | `FlowRunService.edit_review_checkpoint` validates via the existing output validator before repository persistence. |
| Terminal lifecycle transaction ambiguity | `backend/src/intric/flows/runtime/executor.py:1184`; `backend/src/intric/flows/application/flow_run_terminalization.py` | `FlowRunTerminalizer` and explicit lifecycle repository methods. |
| Unguarded step-result success persistence | `backend/src/intric/flows/infrastructure/flow_repo.py:585` | Repository-owned atomic complete-if-active method with file-row replacement behind the same guard. |
| Broad JSON/review payload contracts | `backend/src/intric/flows/api/flow_models.py:653`; `backend/src/intric/flows/flow_validators_form.py:216` | Versioned published-definition, metadata, and review-payload parsers after P0s. |

## Cleanup Candidates

No `delete_now` candidate was safe enough from Scout evidence alone.

| Candidate | Decision | Required Proof |
|---|---|---|
| Legacy form field string normalization in `flow_validators_form.py` | `delete_after_tests` | Current form schema fixtures/goldens use only new typed values. |
| Legacy `template_file_id` promotion/readiness | `delete_after_tests` | Template asset fixtures and run-contract golden use only `template_asset_id`. |
| HTTP legacy config normalizer | `delete_after_tests` | Authored HTTP configs/migrations prove no old dict shapes remain. |
| Principal `legacy_user_id` projection | `delete_after_fixture_cleanup` | DB/user fixture and migration proof. |
| Legacy review checkpoints before step snapshots | `delete_after_fixture_cleanup` | Migration/fixture proof or explicit public-contract break. |
| Permission broad `Permission.FLOWS` alias | `keep` | Product/roles migration needed before removal. |

## Frontend Follow-Up

If the first backend slice changes the public missing-input error contract, T011 should verify whether the Flow frontend renders `flow_run_required_step_input_missing` clearly. Static evidence found current mapping in `frontend/apps/web/src/lib/features/flows/utils/flowRuntimeErrorMapping.ts` does not include that code, while `FlowRunDialog.svelte` prevents many missing-file submissions before the API call.

## Recommended Docs Commit

Subject: `Add Flow runtime maintainability board`
