# Batch 9 Claude Reconciliation 7

TL;DR:
1. Claude returned green for Slice 9.4 after reviewing the review API, repository CAS commands, terminalizer cancellation, and runtime resume tests.
2. The implementation adds typed active/edit/approve/reject/resume endpoints under flow runs.
3. Resume replay short-circuits before outbox insert and worker dispatch when the same `Idempotency-Key` is reused.
4. The only Claude finding was a cosmetic duplicate principal fallback in terminalization, which was fixed before validation.
5. Docker validation is still blocked before execution by the active host policy; local backend validation passed.

## Review Artifact

| Iteration | Artifact | Verdict | Green light | Minimum score |
|---|---|---:|---:|---:|
| 3 | `.codex/artifacts/claude-peer-loop-batch-9-slice-9-4-review-api-resume-implementation-20260502T181025Z.md` | `green` | `yes` | `8` |

## Accepted Changes

| Finding | Resolution |
|---|---|
| Terminalizer derived a fallback `FlowPrincipal` once for active-checkpoint cancellation and again for terminal audit actor fields. | Added `_principal_or_none_from_run` and reused it for both call sites. |
| The implementation should prove reject does not double-write a checkpoint cancellation row. | Added `test_reject_review_checkpoint_does_not_add_cancelled_checkpoint_outbox`, which pins checkpoint outbox actions to `[opened, rejected]` and verifies terminal source `REVIEW_REJECTED`. |
| Runtime resume should prove edited payload propagation, not only status transitions. | Added `test_edit_approve_resume_uses_edited_payload_for_downstream_steps`, which pauses, edits, approves, resumes, completes, and asserts downstream `previous_step` input used the edited text. |
| Last-step review resume should terminalize without another model call when no downstream steps remain. | Added `test_resume_last_step_review_terminalizes_completed_run`, which verifies an empty `next_step_ids_json`, edited final output, `resumed` checkpoint state, and exactly one model call. |

## Accepted Trade-Offs

| Concern | Decision |
|---|---|
| Reject orchestration calls the repository checkpoint transition and then the terminalizer in the service method. | Accepted because both use the same session transaction while keeping checkpoint lifecycle and run lifecycle ownership separate. |
| Active checkpoint GET uses run-content visibility rather than a dedicated review-view permission. | Accepted for Slice 9.4 and documented in the endpoint description; the plan intentionally avoids a second service-key visibility model. |
| FastAPI body validation owns `422` for invalid request shapes. | Accepted; OpenAPI tests pin response presence and schema shape for the new endpoints. |

## Validation

| Command | Result |
|---|---|
| `uv run ruff format ...` on Slice 9.4 source/test files from `backend/` | Passed, unchanged after final pass |
| `uv run ruff check ...` on Slice 9.4 source/test files from `backend/` | Passed |
| `uv run pyright ...` on Slice 9.4 source/test files from `backend/` | Passed, `0 errors` |
| `uv run pytest tests/unittests/flows/test_flow_access_policy.py tests/unit/test_flow_openapi_contract.py tests/unittests/flows/test_flow_run_service.py -q` from `backend/` | Passed, `174 passed`, `18` existing warnings |
| `uv run pytest tests/integration/flows/test_flow_run_review_checkpoint_repository.py tests/integration/flows/test_flow_review_pause_worker_contract.py -q` from `backend/` | Passed, `17 passed`, `16` existing warnings |
| `uv run pytest tests/integration/flows/test_flow_run_review_checkpoint_repository.py::test_awaiting_review_run_cancels_active_checkpoint_by_terminalizer tests/integration/flows/test_flow_run_review_checkpoint_repository.py::test_reject_review_checkpoint_does_not_add_cancelled_checkpoint_outbox -q` from `backend/` after the terminalizer cleanup | Passed, `2 passed`, `16` existing warnings |
| `docker exec -w /workspace/backend eneo-41ae93-eneo-1 .venv/bin/pytest tests/integration/flows/test_flow_run_review_checkpoint_repository.py tests/integration/flows/test_flow_review_pause_worker_contract.py -q` | Blocked before execution by host policy: `Rejected("approval required by policy, but AskForApproval is set to Never")` |

## Forward Debt

| Owner slice | Debt | Acceptance note |
|---|---|---|
| Slice 9.5 | Add evidence/export lineage for original reviewed payload, edited current payload, and resumed checkpoint state. | The runtime projection now updates step results on edit; evidence must expose the original-vs-current distinction without reading attempt output as current truth. |
| Frontend slice | Wire generated API types and UI state for active checkpoint read, edit, approve, reject, and resume. | Do not add manual duplicate frontend types. |

## Implementation Gate

Slice 9.4 is implementation-ready after local validation, targeted runtime coverage, and Claude green light.
