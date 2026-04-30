# Create/Edit Proposal Processing Claude Reconciliation 3

## Plan Review Result

- Claude session: `eneo-flow-batch6-create-edit-proposal`
- Phase: plan
- Iteration: 1
- Verdict: changes required
- Green light: no
- Minimum score: 5
- Artifact: `.codex/artifacts/claude-peer-loop-batch-6-create-edit-proposal-plan-20260430T154633Z.md`

## Accepted Findings

| Finding | Verdict | Reconciliation |
|---|---|---|
| The plan did not explicitly replace the private bound-method identity assertion in `test_ai_builder_proposal_processor.py:1946`. | accepted | Added a test call-site section that replaces callable identity assertions with behavior-level retry-config assertions. |
| Moving `process_edit_arguments` as a free function would require either injecting `processor` into `process_tool_kwargs` or binding it before retry callbacks. | accepted | Chose a typed local binding function for retry configs so the retry `process_tool_kwargs` shape remains unchanged and signature filtering still sees `flow` and `assistant_metadata`. |
| Six direct test calls to `processor._process_edit_arguments(...)` were not enumerated. | accepted | Added the exact direct call sites and the required update to `process_edit_arguments(processor=processor, ...)`. |
| The boundary rule was asymmetric: `_handle_edit_flow` stayed because it used shared retry/event behavior, while `_process_edit_arguments` also reached back into shared processor behavior. | accepted | Added the explicit boundary rule: dispatcher/event streaming/retry orchestration stays in the processor spine; edit-domain composition moves. |
| Cross-module private method reach-back can become technical debt. | accepted with constraint | The plan now limits this to the current processor-owned proposal spine and adds a stop/re-plan rule if the edit module begins needing more processor methods. A broader public-surface cleanup is intentionally deferred. |
| The description-only edit repair prompt is an LLM contract surface without a stable anchor pin. | accepted | Added a prompt-contract artifact/test update to pin stable description-repair prompt substrings without weakening existing anchors. |
| The implementation must verify no hidden call sites remain. | accepted | Ran the requested grep and recorded the direct call sites in the plan. |

## Local Verification Notes

The requested direct-call grep was run:

```bash
git grep -n "processor\._process_edit_arguments\|processor\._attempt_description_repair\|processor\._edit_flow_retry_config\|_extract_description_provenance" -- backend/tests backend/src/intric/flows/ai_builder
```

It found:

- `backend/src/intric/flows/ai_builder/ai_builder_proposal_processor.py:2235`
- `backend/src/intric/flows/ai_builder/ai_builder_proposal_processor.py:2612`
- `backend/tests/unit/test_ai_builder_plan_edit_context.py:561`
- `backend/tests/unittests/flows/ai_builder/test_ai_builder_proposal_processor.py:1334`
- `backend/tests/unittests/flows/ai_builder/test_ai_builder_proposal_processor.py:1421`
- `backend/tests/unittests/flows/ai_builder/test_ai_builder_proposal_processor.py:1518`
- `backend/tests/unittests/flows/ai_builder/test_ai_builder_proposal_processor.py:1616`
- `backend/tests/unittests/flows/ai_builder/test_ai_builder_proposal_processor.py:1716`
- `backend/tests/unittests/flows/ai_builder/test_ai_builder_proposal_processor.py:1946`

## Plan Changes

- Updated `docs/refactor/execution/batch-6-ai-builder-contract-split/plan.md`.
- Updated `docs/refactor/execution/batch-6-ai-builder-contract-split/journal.md`.
- No production source or tests have been changed yet.

## Plan Verification Status

## Plan Verification Result

- Claude session: `eneo-flow-batch6-create-edit-proposal`
- Phase: verification
- Iteration: 2
- Verdict: green
- Green light: yes
- Minimum score: 6
- Artifact: `.codex/artifacts/claude-peer-loop-batch-6-create-edit-proposal-plan-verification-20260430T155127Z.md`

Claude verified that the iteration-1 blockers were resolved:

- retry callbacks use a bound edit callable rather than hidden `processor`
  entries in `process_tool_kwargs`
- direct edit call sites are enumerated
- callable identity assertions are replaced by behavior-level assertions
- dispatch/event/retry orchestration remains in the processor spine
- description-repair prompt anchors are added to the durable prompt contract

Low-severity Claude notes folded into the plan before implementation:

- explicitly allow processor top-level imports from the edit module because the
  reverse import is `TYPE_CHECKING`-only
- map description-repair prompt anchors to
  `ai_builder_edit_proposal.py` in the artifact test
- add a real description-repair contract paragraph, not only anchor bullets
- use a tiny typed binding function instead of `functools.partial` after local
  signature verification showed keyword-bound partials keep `processor` visible
- choose to keep `_extract_description_provenance` private in the new module

Implementation can begin.

## Implementation Review Result

- Claude session: `eneo-flow-batch6-create-edit-proposal`
- Phase: implementation
- Iteration: 3
- Verdict: changes required
- Green light: no
- Minimum score: 6
- Artifact: `.codex/artifacts/claude-peer-loop-batch-6-create-edit-proposal-implementation-20260430T160915Z.md`

## Implementation Review Accepted Findings

| Finding | Verdict | Reconciliation |
|---|---|---|
| `terminal_output_type` derivation was hoisted from edit processing into multiple processor callers. | accepted | Moved derivation back inside `process_edit_arguments` and removed duplicated caller plumbing from `_handle_edit_flow`, `_submission_retry_config`, and retry config construction. |
| The manual bind wrapper duplicates the edit processor signature. | accepted with constraint | Kept the typed wrapper because keyword-bound `functools.partial` kept `processor` visible to `inspect.signature`; reduced drift by removing the extra `terminal_output_type` parameter. |
| Tests would not catch missing terminal output derivation if callers forgot to pass it. | accepted | Derivation now lives inside `process_edit_arguments`, so every direct and retry path exercises the same owner. |
| `target_step_ref` lost readability parentheses during the move. | accepted | Restored the explicit parentheses. |
| `attempt_description_repair` and `_extract_description_provenance` lost useful one-line docstrings. | accepted | Restored concise invariant/provenance docstrings. |

## Post-Review Fix Verification

- `cd backend && uv run ruff check src/intric/flows/ai_builder/ai_builder_edit_proposal.py src/intric/flows/ai_builder/ai_builder_proposal_processor.py tests/unittests/flows/ai_builder/test_ai_builder_proposal_processor.py tests/unit/test_ai_builder_plan_edit_context.py tests/unittests/flows/ai_builder/test_ai_builder_prompt_contract_artifact.py`
  - Result: pass.
- `cd backend && uv run pyright src/intric/flows/ai_builder/ai_builder_edit_proposal.py src/intric/flows/ai_builder/ai_builder_proposal_processor.py tests/unittests/flows/ai_builder/test_ai_builder_proposal_processor.py tests/unit/test_ai_builder_plan_edit_context.py tests/unittests/flows/ai_builder/test_ai_builder_prompt_contract_artifact.py`
  - Result: pass, 0 errors.
- `cd backend && uv run pytest tests/unittests/flows/ai_builder/test_ai_builder_proposal_processor.py tests/unit/test_ai_builder_plan_edit_context.py tests/unittests/flows/ai_builder/test_ai_builder_prompt_contract_artifact.py -q`
  - Result: pass, 52 passed.

Implementation verification is pending after the full validation rerun.

## Implementation Verification Result

- Claude session: `eneo-flow-batch6-create-edit-proposal`
- Phase: verification
- Iteration: 4
- Verdict: green
- Green light: yes
- Minimum score: 7
- Artifact: `.codex/artifacts/claude-peer-loop-batch-6-create-edit-proposal-final-verification-20260430T161735Z.md`

The wrapper exited nonzero because it did not parse Claude's markdown-formatted
green-light line, but the review body explicitly reports:

- `VERDICT: green`
- `GREEN_LIGHT: yes`
- `MIN_SCORE: 7`

Claude verified:

- terminal-output derivation is owned by `process_edit_arguments`
- duplicated caller plumbing is removed
- the typed retry callback binding is justified by local signature evidence
- processor-spine public methods are intentional
- prompt-contract anchors remain pinned
- no router, planner, frontend, SSE, audit, or retry-budget scope drift was
  introduced
- no accepted or partial findings remain
