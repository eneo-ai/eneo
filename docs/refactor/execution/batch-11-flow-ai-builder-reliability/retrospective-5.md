# Batch 11.1c Retrospective — Architecture Error Surface

## TL;DR

1. Slice 11.1c adds a typed architecture-error surface for create-path Flow AI
   Builder mechanics failures.
2. Create proposals now enforce backend-owned critic invariants before asking
   the model to repair semantic issues.
3. Architecture failures produce one sanitized SSE error event and do not enter
   self-correction.
4. Proposal telemetry can record `architecture` as a first-attempt failure, but
   repair reasons cannot use `architecture`.
5. Focused validation is green; edit-path mechanics remain the next follow-up.

## Scope

Implemented:

- `AIBuilderArchitectureError`
- create-outline skeleton failure wrapping
- architecture/semantic critic invariant classification
- typed critic issue evaluation and architecture enforcement
- semantic-only create-path quality feedback after architecture enforcement
- proposal architecture-error telemetry and sanitized SSE errors
- `MaterializationError` reparenting
- focused behavior tests for direct, repair, forced-tool, and audio-to-DOCX paths

Not implemented:

- edit-path fill/preserve/reject mechanics
- a frontend error-code registry
- manual local API smoke execution
- broader AI Builder suite cleanup for known unrelated/environmental failures

## Checklist

| Check | Result | Notes |
|---|---|---|
| Plan adherence | pass | Implemented the create-path architecture-error slice only. |
| Claude plan loop | pass | Third plan verification reached `GREEN_LIGHT: yes`. |
| Claude implementation loop | pass | Parser-clean final verification reached `GREEN_LIGHT: yes`, minimum score `9/10`. |
| Canonical owner respected | pass | `ai_builder_architecture_errors.py` owns the shared error; critic registry remains the single invariant owner. |
| Parallel path avoided | pass | `render_critic_issues` delegates to `evaluate_critic_invariants`; no second invariant loop was added. |
| Typed contracts | pass | Error codes, log values, critic issue kind, and proposal repair reasons are typed. |
| Comment hygiene | pass | No source comments mention tooling/session details or restate the new control flow. |
| Behavior tests | pass | Architecture bypass, zero repair count, typed critic enforcement, and audio-to-DOCX canary are covered. |
| Broader suite | not run | Focused validation covers touched behavior; broader suite still has known unrelated failures from 11.1a/11.1b. |

## Validation

| Command | Result |
|---|---|
| `cd backend && uv run pytest tests/unittests/flows/ai_builder/test_ai_builder_plan_quality_critic.py tests/unittests/flows/ai_builder/test_ai_builder_proposal_processor.py tests/unittests/flows/ai_builder/test_ai_builder_create_compiler.py tests/unittests/flows/ai_builder/test_ai_builder_materialization_bridge.py tests/unittests/flows/ai_builder/test_ai_builder_proposal_telemetry.py -q` | Passed: `206 passed`, one existing Starlette multipart warning. |
| `cd backend && uv run pyright <11.1c touched source/test files>` | Passed: `0 errors, 0 warnings, 0 informations`. |
| `cd backend && uv run ruff check <11.1c touched source/test files>` | Passed. |
| `cd backend && uv run ruff format --check <11.1c touched source/test files>` | Passed: `13 files already formatted`. |
| `cd backend && uv run lint-imports --no-cache` | Passed: 3 contracts kept, 0 broken. |
| `git diff --check -- <11.1c touched paths>` | Passed. |
| `./scripts/gate-local/anti_slippage.sh --worktree` | Passed: `anti-slippage: worktree clean`. |
| Added-line slop grep | Passed with no matches. |
| Claude final implementation verification | Passed: parser-clean `GREEN_LIGHT: yes`, `MIN_SCORE: 9`. |

## Carry-Forward

| Item | Owner slice |
|---|---|
| Edit-path fill/preserve/reject mechanics. | Next 11.1 follow-up slice |
| Manual/API audio-to-DOCX smoke gate. | 11.1 success gate |
| Broader AI Builder suite known failures. | Separate cleanup unless a follow-up slice touches those surfaces |
| Skeleton module size watchpoint. | Next 11.1 follow-up slice |

## Risk

Architecture critic issues are now hard create-path failures. That is
intentional for backend-owned mechanics such as terminal artifact alignment and
JSON/all-previous runtime incompatibility. The risk is over-classification: if a
future invariant is actually repairable by semantic plan content, it must be
classified as `semantic` and covered by the kind-map test.

The direct user-facing SSE message is intentionally generic. Logs carry the
specific scalar architecture context, while users see a stable message and code.

## Confidence

High for the create-path surface. The focused tests exercise the new failure
contract from the critic, compiler, proposal processor, bridge, and telemetry
angles. The remaining reliability work is edit-path mechanics, not this error
translation slice.
