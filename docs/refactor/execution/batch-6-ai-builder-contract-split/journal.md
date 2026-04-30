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

## Iteration 2

### Start Gate

- HEAD verified as `4cd874c7`.
- Latest commit verified as `flows: pin ai builder prompt and audit contracts`.
- `git diff --cached --name-only` returned no staged files.
- Dirty files at start:
  - `frontend/packages/ui/src/icons/types.d.ts`
  - `scripts/run_codex_review.sh`
  - `PRODUCT.md`
- These dirty files are unrelated and must remain untouched.

### Docker Status

`docker ps --format '{{.Names}}'` was attempted before planning and was blocked
by host execution policy:

```text
CreateProcess { message: "Rejected(\"approval required by policy, but AskForApproval is set to Never\")" }
```

Planned fallback: use local backend validation commands and record that Docker
was unavailable in this thread.

### Scope Decision

This iteration is limited to repair contract hardening. The plan permits one
small local value object in `ai_builder_proposal_repair.py` only if Claude
agrees that it removes a real duplicated primitive retry-state concept without
creating ceremony. Otherwise the acceptable outcome is a documented
no-production-change decision plus retrospective and Claude reconciliation.

Forbidden work remains out of scope: create/edit proposal split, planner-turn
extraction, router/presenter thinning, frontend protocol changes, package
renames, audit behavior changes, logging behavior changes, and any `intric.*`
to `eneo.*` namespace rename.

### Evidence Gathered

- `ai_builder_repair.py`
  - semantic and parse repair retry constants: lines 76-86
  - semantic repair typed outcome: lines 246-286
  - semantic repair helper: lines 289-354
  - parse repair typed outcome and helper: lines 357-470
- `ai_builder_orchestration_pipeline.py`
  - planner repair-loop accounting: lines 253-365
  - parse-repair loop: lines 388-454
- `ai_builder_proposal_repair.py`
  - proposal retry availability and consume helpers: lines 127-148
  - retry loop primitive state: lines 219-221 and 329-342
  - forced tool retry and JSON text fallback: lines 391-581
- Existing repair pins:
  - `test_ai_builder_repair.py:93-307`
  - `test_ai_builder_parse_repair.py:207-391`
  - `test_ai_builder_orchestration_pipeline.py:222-638`
  - `test_ai_builder_proposal_repair.py:162-453`

### Plan Status

- Repair-contract hardening plan appended to `docs/refactor/execution/batch-6-ai-builder-contract-split/plan.md`.
- Claude peer-loop plan review completed with `GREEN_LIGHT: no`, `VERDICT: changes_required`, and `MIN_SCORE: 6`.
- Accepted findings were reconciled in `docs/refactor/execution/batch-6-ai-builder-contract-split/claude-reconciliation-2.md`.
- Plan revisions made after Claude review:
  - archived the committed prompt/audit checkpoint under the active plan
  - recorded the user's explicit approval to continue the next narrow repair slice from `4cd874c7`
  - made the missing `recoverable_parse` extra-retry behavior pin mandatory even if production refactor is skipped
  - added the retry-state transition table and production diff budget
  - narrowed the committed-text hygiene regex to avoid runtime `phase` false positives
  - explicitly pinned `MAX_SELF_CORRECTION_RETRIES = 3`
- Local verification confirmed no existing backend tests match `recoverable_parse`, `extra_retry_available`, or `_EXTRA_RETRY_FAILURE_KINDS`.
- Claude peer-loop verification completed with `VERDICT: green`, `GREEN_LIGHT: yes`, and `MIN_SCORE: 8`.
- Artifact: `.codex/artifacts/claude-peer-loop-batch-6-repair-contract-hardening-plan-verification-20260430T132047Z.md`.
- The wrapper exited nonzero because `--require-green` did not parse Claude's markdown-formatted green-light line, but the review body explicitly green-lit implementation with no findings.
- Next action: add the missing `recoverable_parse` behavior pins before production hardening.

### Implementation

- Added proposal repair behavior pins in `test_ai_builder_proposal_repair.py` before production changes:
  - `recoverable_parse` consumes exactly one extra retry after the normal self-correction budget.
  - `parse` and `validation` do not consume the extra retry slot after the normal budget is exhausted.
  - Final externally visible error event shape remains unchanged.
- Focused pre-refactor pin check:
  - `cd backend && uv run pytest tests/unittests/flows/ai_builder/test_ai_builder_proposal_repair.py -q`
  - Result before source change: pass, 14 passed.
- Replaced the local proposal repair retry primitive bundle
  (`attempts_remaining`, `extra_retry_available`, `retry_count`) with a private
  frozen `_ProposalRepairRetryState` in `ai_builder_proposal_repair.py`.
- No numeric retry budgets changed:
  - `MAX_ORCHESTRATOR_REPAIR_RETRIES = 3`
  - `MAX_PARSE_REPAIR_RETRIES = 1`
  - `MAX_SELF_CORRECTION_RETRIES = 3`
- No symbols moved, no new protocol/interface/adapter was introduced, and no
  router, planner, create/edit, frontend, audit, logging, or SSE behavior was
  changed.
- Production source diff stayed within the plan budget:
  - `backend/src/intric/flows/ai_builder/ai_builder_proposal_repair.py`: 49 insertions, 46 deletions, net +3.

### Validation

- `docker ps --format '{{.Names}}'`
  - Result: blocked by host execution policy with `approval required by policy, but AskForApproval is set to Never`.
  - Local fallback validation used.
- `cd backend && uv run pytest tests/unittests/flows/ai_builder/test_ai_builder_proposal_repair.py -q`
  - Result after source change: pass, 14 passed.
- `cd backend && uv run pytest tests/integration/flows/test_ai_builder_session_api_regressions.py tests/integration/flows/ai_builder/test_ai_builder_apply_to_draft.py tests/integration/flows/test_ai_builder_edit_apply_regressions.py -q`
  - Result: pass, 39 passed.
- `cd backend && uv run pytest tests/unittests/flows/ai_builder/test_ai_builder_prompt_contract_artifact.py tests/unittests/flows/ai_builder/test_ai_builder_repair.py tests/unittests/flows/ai_builder/test_ai_builder_parse_repair.py tests/unittests/flows/ai_builder/test_ai_builder_orchestration_pipeline.py tests/unittests/flows/ai_builder/test_ai_builder_proposal_repair.py tests/unittests/flows/ai_builder/test_ai_builder_proposal_processor.py tests/unittests/flows/ai_builder/test_ai_builder_router.py tests/unittests/flows/ai_builder/test_ai_builder_failure_events.py -q`
  - First run failed on two stale `test_ai_builder_proposal_processor.py`
    retry-config expectations that omitted already-current nullable edit-context
    keys.
  - Test expectations were updated to pin the current typed retry-config shape.
  - Rerun result: pass, 161 passed.
- `cd backend && uv run pyright src/intric/flows/ai_builder/ai_builder_proposal_repair.py tests/unittests/flows/ai_builder/test_ai_builder_proposal_repair.py tests/unittests/flows/ai_builder/test_ai_builder_proposal_processor.py tests/unittests/flows/ai_builder/test_ai_builder_prompt_contract_artifact.py tests/unittests/flows/ai_builder/test_ai_builder_repair.py tests/unittests/flows/ai_builder/test_ai_builder_parse_repair.py tests/unittests/flows/ai_builder/test_ai_builder_orchestration_pipeline.py`
  - Result: pass, 0 errors.
- `cd backend && uv run ruff check src/intric/flows/ai_builder/ai_builder_proposal_repair.py tests/unittests/flows/ai_builder/test_ai_builder_proposal_repair.py tests/unittests/flows/ai_builder/test_ai_builder_proposal_processor.py tests/unittests/flows/ai_builder/test_ai_builder_prompt_contract_artifact.py tests/unittests/flows/ai_builder/test_ai_builder_repair.py tests/unittests/flows/ai_builder/test_ai_builder_parse_repair.py tests/unittests/flows/ai_builder/test_ai_builder_orchestration_pipeline.py`
  - Result: pass.
- `cd backend && uv run lint-imports --no-cache`
  - Result: pass, 3 contracts kept.
- `git diff --check -- docs/refactor/ai-builder-prompt-contract.md docs/refactor/execution/batch-6-ai-builder-contract-split backend/src/intric/flows/ai_builder/ai_builder_proposal_repair.py backend/tests/unittests/flows/ai_builder/test_ai_builder_proposal_repair.py backend/tests/unittests/flows/ai_builder/test_ai_builder_proposal_processor.py`
  - Result: pass.
- `rg -n "6b|6c|Batch 6|repair extraction" backend/src/intric/flows/ai_builder/ai_builder_proposal_repair.py backend/tests/unittests/flows/ai_builder/test_ai_builder_proposal_repair.py backend/tests/unittests/flows/ai_builder/test_ai_builder_proposal_processor.py docs/refactor/ai-builder-prompt-contract.md`
  - Result: no matches.

### Claude Implementation Review And Follow-Up

- Claude peer-loop implementation review returned `VERDICT: changes_required`,
  `GREEN_LIGHT: no`, and `MIN_SCORE: 9`.
- Artifact: `.codex/artifacts/claude-peer-loop-batch-6-repair-contract-hardening-implementation-20260430T133157Z.md`.
- Claude found no source/test issue. It confirmed:
  - production diff is net +3 lines
  - `_ProposalRepairRetryState` is not a fake interface
  - retry-state transitions, temperature bumping, retry-feedback ordinals, and numeric budgets are preserved
  - `recoverable_parse` behavior pins cover the positive extra retry and paired negative cases
  - no event, audit, logging, frontend, router, planner, or create/edit scope drift occurred
- Accepted finding:
  - `plan.md` needed to classify `test_ai_builder_proposal_processor.py` as an expected test-change file, not just as a validation file.
- Follow-up changes:
  - Updated `plan.md` expected files to list `test_ai_builder_proposal_processor.py`.
  - Extended the non-extra retry negative test to include `quality` so the executable pin matches the transition table.
- Focused verification after follow-up:
  - `cd backend && uv run pytest tests/unittests/flows/ai_builder/test_ai_builder_proposal_repair.py tests/unittests/flows/ai_builder/test_ai_builder_proposal_processor.py -q`
  - Result: pass, 48 passed.
- Broader unit verification after follow-up:
  - `cd backend && uv run pytest tests/unittests/flows/ai_builder/test_ai_builder_prompt_contract_artifact.py tests/unittests/flows/ai_builder/test_ai_builder_repair.py tests/unittests/flows/ai_builder/test_ai_builder_parse_repair.py tests/unittests/flows/ai_builder/test_ai_builder_orchestration_pipeline.py tests/unittests/flows/ai_builder/test_ai_builder_proposal_repair.py tests/unittests/flows/ai_builder/test_ai_builder_proposal_processor.py tests/unittests/flows/ai_builder/test_ai_builder_router.py tests/unittests/flows/ai_builder/test_ai_builder_failure_events.py -q`
  - Result: pass, 162 passed.
- Static checks after follow-up:
  - `cd backend && uv run pyright src/intric/flows/ai_builder/ai_builder_proposal_repair.py tests/unittests/flows/ai_builder/test_ai_builder_proposal_repair.py tests/unittests/flows/ai_builder/test_ai_builder_proposal_processor.py tests/unittests/flows/ai_builder/test_ai_builder_prompt_contract_artifact.py tests/unittests/flows/ai_builder/test_ai_builder_repair.py tests/unittests/flows/ai_builder/test_ai_builder_parse_repair.py tests/unittests/flows/ai_builder/test_ai_builder_orchestration_pipeline.py`
  - Result: pass, 0 errors.
  - `cd backend && uv run ruff check src/intric/flows/ai_builder/ai_builder_proposal_repair.py tests/unittests/flows/ai_builder/test_ai_builder_proposal_repair.py tests/unittests/flows/ai_builder/test_ai_builder_proposal_processor.py tests/unittests/flows/ai_builder/test_ai_builder_prompt_contract_artifact.py tests/unittests/flows/ai_builder/test_ai_builder_repair.py tests/unittests/flows/ai_builder/test_ai_builder_parse_repair.py tests/unittests/flows/ai_builder/test_ai_builder_orchestration_pipeline.py`
  - Result: pass.
  - `git diff --check -- docs/refactor/ai-builder-prompt-contract.md docs/refactor/execution/batch-6-ai-builder-contract-split backend/src/intric/flows/ai_builder/ai_builder_proposal_repair.py backend/tests/unittests/flows/ai_builder/test_ai_builder_proposal_repair.py backend/tests/unittests/flows/ai_builder/test_ai_builder_proposal_processor.py`
  - Result: pass.
  - `rg -n "6b|6c|Batch 6|repair extraction" backend/src/intric/flows/ai_builder/ai_builder_proposal_repair.py backend/tests/unittests/flows/ai_builder/test_ai_builder_proposal_repair.py backend/tests/unittests/flows/ai_builder/test_ai_builder_proposal_processor.py docs/refactor/ai-builder-prompt-contract.md`
  - Result: no matches.
- Claude verification rerun after the documentation fix returned
  `VERDICT: green`, `GREEN_LIGHT: yes`, and `MIN_SCORE: 9`.
- Artifact: `.codex/artifacts/claude-peer-loop-batch-6-repair-contract-hardening-implementation-verification-20260430T133448Z.md`.
