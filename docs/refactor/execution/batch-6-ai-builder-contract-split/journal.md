# Batch 6 - AI Builder Contract Split Journal

## Iteration 1

### Start Gate

- HEAD verified as `546d472c`.
- Latest commit verified as `flows: align frontend flow types with generated schemas`.
- `git diff --cached --name-only` returned no staged files.
- Dirty files at start:
  - `frontend/packages/ui/src/icons/types.d.ts`
  - `scripts/run_codex_review.sh`
  - `PRODUCT.md`
- These dirty files are unrelated to Batch 6 and must remain untouched.

### Docker Status

`docker ps --format '{{.Names}}'` was attempted before planning and was blocked by host execution policy:

```text
CreateProcess { message: "Rejected(\"approval required by policy, but AskForApproval is set to Never\")" }
```

Planned fallback: run local validation commands unless Docker becomes available without requiring approval.

### Scope Decision

Batch 6 is sliced. This session is limited to 6a:

- behavior pins
- prompt-contract documentation
- batch audit docs

No production refactor in `backend/src/intric/flows/ai_builder/*.py` is allowed in 6a.

### Evidence Gathered

- `ai_builder_router.py`
  - create session endpoint and audit metadata: lines 320-369
  - send message SSE wrapper and error/done handling: lines 475-617
  - approve/apply/revise endpoints and audit metadata: lines 931-1134
- `ai_builder_service.py`
  - create session composition: lines 187-232
  - send message delegation: lines 459-500
  - approve/apply/revise service methods: lines 548-626
- `ai_builder_prompts.py`
  - prompt assembly: lines 84-222
  - clarification hints: lines 271-485
- `ai_builder_events.py`
  - event names and payload builders: lines 22-159
- `ai_builder_repair.py`
  - active semantic/parse repair contracts: lines 90-536
- `ai_builder_proposal_repair.py`
  - active proposal repair retry/error behavior: lines 127-584
- `frontend/packages/intric-js/src/types/schema.d.ts`
  - AI Builder routes: lines 4152-4369
  - generated schemas: lines 8730, 10399, 16334, 16349, 16685, 16920, 17162, 17226, 17332
- `frontend/apps/web/src/lib/features/flows/ai-builder/protocol.ts`
  - manual protocol types: lines 4-240

### Plan Status

- Initial `/plan` created at `docs/refactor/execution/batch-6-ai-builder-contract-split/plan.md`.
- Claude peer-loop iteration 1 completed with `GREEN_LIGHT: no` and `VERDICT: changes_required`.
- Accepted findings were reconciled in `docs/refactor/execution/batch-6-ai-builder-contract-split/claude-reconciliation-1.md`.
- Plan revisions made after Claude review:
  - replaced the dense per-file AI Builder inventory with an area-level read-only inventory for 6a
  - added existing test coverage evidence and a bounded 6a coverage delta
  - added `test_ai_builder_router.py` to validation
  - classified JSON text fallback and planner output normalization as active behavior, not deletion candidates
  - added a prompt-contract artifact test-linkage requirement
  - removed pre-created iteration-2 retrospective/reconciliation artifacts
- Next action: run Claude peer-loop iteration 2 against the revised plan before implementation.
- Claude peer-loop iteration 2 completed with `GREEN_LIGHT: yes`, `VERDICT: green`, and `MIN_SCORE: 8`.
- Non-blocking Claude notes were folded into the plan before implementation:
  - named `test_ai_builder_prompt_contract_artifact.py` as the prompt-contract artifact regression test
  - added that test path to pytest, pyright, and ruff validation commands
  - specified that audit metadata strengthening should modify existing router audit tests rather than add duplicate event tests
  - specified exact substring matching for prompt-contract artifact anchors

### Implementation Notes

- Added `docs/refactor/ai-builder-prompt-contract.md` with prompt inputs, planner obligations, repair obligations, and stable test anchors.
- Strengthened route-level AI Builder audit pins in `test_ai_builder_router.py` for create, cancel, approve, and apply metadata.
- Added prompt-contract artifact drift coverage in `test_ai_builder_prompt_contract_artifact.py`.
- Added parse-repair budget and raw JSON instruction pins in `test_ai_builder_repair.py`.
- Validation exposed two stale test expectations in validation-only files before any production code change:
  - `test_ai_builder_edit_apply_regressions.py` still passed `output_mode` into `AddStepPayload`/`NewStepDraft`, but new edit-step output mode is backend-derived.
  - `test_ai_builder_proposal_repair.py` expected a single event dictionary, but `retry_forced_tool_after_text` now returns a tuple of processed events.
- The plan was updated before fixing those test-only contract expectations.

### Validation Results

- `cd backend && uv run pytest tests/unittests/flows/ai_builder/test_ai_builder_router.py tests/unittests/flows/ai_builder/test_ai_builder_prompt_contract_artifact.py tests/unittests/flows/ai_builder/test_ai_builder_prompts.py tests/unittests/flows/ai_builder/test_ai_builder_repair.py -q`
  - Result: pass, 152 passed.
- `cd backend && uv run pytest tests/integration/flows/test_ai_builder_session_api_regressions.py tests/integration/flows/ai_builder/test_ai_builder_apply_to_draft.py tests/integration/flows/test_ai_builder_edit_apply_regressions.py -q`
  - First run: failed on stale `AddStepPayload(output_mode=...)` fixture in `test_ai_builder_edit_apply_regressions.py`.
  - After plan update and test-only fix: pass, 39 passed.
- `cd backend && uv run pytest tests/unittests/flows/ai_builder/test_ai_builder_router.py tests/unittests/flows/ai_builder/test_ai_builder_prompt_contract_artifact.py tests/unittests/flows/ai_builder/test_ai_builder_prompts.py tests/unittests/flows/ai_builder/test_ai_builder_knowledge_pack.py tests/unittests/flows/ai_builder/test_ai_builder_repair.py tests/unittests/flows/ai_builder/test_ai_builder_repair_transport.py tests/unittests/flows/ai_builder/test_ai_builder_proposal_repair.py tests/unittests/flows/ai_builder/test_ai_builder_failure_events.py -q`
  - First run: failed on stale `retry_forced_tool_after_text` event-shape assertions in `test_ai_builder_proposal_repair.py`.
  - After plan update and test-only fix: pass, 180 passed.
- `cd backend && uv run pyright tests/integration/flows/test_ai_builder_edit_apply_regressions.py tests/unittests/flows/ai_builder/test_ai_builder_router.py tests/unittests/flows/ai_builder/test_ai_builder_prompt_contract_artifact.py tests/unittests/flows/ai_builder/test_ai_builder_prompts.py tests/unittests/flows/ai_builder/test_ai_builder_repair.py tests/unittests/flows/ai_builder/test_ai_builder_proposal_repair.py`
  - Result: pass, 0 errors.
- `cd backend && uv run ruff check tests/integration/flows/test_ai_builder_edit_apply_regressions.py tests/unittests/flows/ai_builder/test_ai_builder_router.py tests/unittests/flows/ai_builder/test_ai_builder_prompt_contract_artifact.py tests/unittests/flows/ai_builder/test_ai_builder_prompts.py tests/unittests/flows/ai_builder/test_ai_builder_repair.py tests/unittests/flows/ai_builder/test_ai_builder_proposal_repair.py`
  - Result: pass after ruff-sorted imports.
- `cd backend && uv run lint-imports --no-cache`
  - Result: pass, 3 contracts kept.
- `git diff --check -- docs/refactor/ai-builder-prompt-contract.md docs/refactor/execution/batch-6-ai-builder-contract-split backend/tests/integration/flows/test_ai_builder_session_api_regressions.py backend/tests/integration/flows/ai_builder/test_ai_builder_apply_to_draft.py backend/tests/integration/flows/test_ai_builder_edit_apply_regressions.py backend/tests/unittests/flows/ai_builder`
  - Result: pass.
- `git grep -n "AI_BUILDER_SESSION_CREATED\\|AI_BUILDER_PLAN_APPROVED\\|AI_BUILDER_FLOW_APPLIED\\|AI_BUILDER_SESSION_CANCELLED" backend/tests`
  - Result: all four audit action pins live in `test_ai_builder_router.py`.

### Claude Implementation Review

- Claude peer-loop implementation review completed with `GREEN_LIGHT: yes`, `VERDICT: green`, and `MIN_SCORE: 8`.
- Artifact: `.codex/artifacts/claude-peer-loop-batch-6a-ai-builder-contract-pins-implementation-20260430T122331Z.md`.
- Claude cleared the main risk checks:
  - 6a stayed test/docs-only.
  - Existing router audit tests were strengthened instead of duplicating coverage.
  - Parse-repair retry/raw-JSON obligations are pinned.
  - Prompt-contract artifact drift has a code/doc anchor guard.
- Claude partial notes were inspected:
  - The plan/test-path notes were stale against the current `plan.md`; the artifact test, proposal repair test, and edit-apply regression test are now listed in expected files and pyright/ruff validation commands.
  - The `ref=\`` prompt anchor was too brittle, so the artifact drift test now checks the less format-specific `ref=` anchor.
  - Router audit assertions now use `assert_awaited_once()` and `await_args.kwargs` consistently for async audit calls.

### Post-Claude Cleanup Validation

- `cd backend && uv run pytest tests/unittests/flows/ai_builder/test_ai_builder_router.py tests/unittests/flows/ai_builder/test_ai_builder_prompt_contract_artifact.py -q`
  - Result: pass, 60 passed.
- `cd backend && uv run pyright tests/unittests/flows/ai_builder/test_ai_builder_router.py tests/unittests/flows/ai_builder/test_ai_builder_prompt_contract_artifact.py`
  - Result: pass, 0 errors.
- `cd backend && uv run ruff check tests/unittests/flows/ai_builder/test_ai_builder_router.py tests/unittests/flows/ai_builder/test_ai_builder_prompt_contract_artifact.py`
  - Result: pass.
- `git diff --check -- docs/refactor/ai-builder-prompt-contract.md docs/refactor/execution/batch-6-ai-builder-contract-split backend/tests/unittests/flows/ai_builder/test_ai_builder_router.py backend/tests/unittests/flows/ai_builder/test_ai_builder_prompt_contract_artifact.py`
  - Result: pass.
