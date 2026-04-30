# Repair Contract Hardening Claude Reconciliation 2

## Plan Review Result

- Claude session: `eneo-flow-batch6-ai-builder-contract-split`
- Phase: plan
- Iteration: 2
- Verdict: changes required
- Green light: no
- Minimum score: 6
- Artifact: `.codex/artifacts/claude-peer-loop-batch-6-repair-contract-hardening-plan-20260430T131123Z.md`

## Accepted Findings

| Finding | Verdict | Reconciliation |
|---|---|---|
| The plan document was stale at the top and still read like the committed prompt/audit checkpoint was active. | accepted | Rewrote the TL;DR, archived the committed checkpoint under an explicit `Archive` heading, and made the repair-contract plan the active section. |
| The `recoverable_parse` behavior pin was incorrectly conditional on the value-object refactor. | accepted | Made the missing behavior pin mandatory even if no production change proceeds. |
| User approval for continuing after the prompt/audit checkpoint was not recorded. | accepted | Recorded the current prompt's explicit instruction to start the next narrow repair slice from `4cd874c7`. |
| The plan silently narrowed "repair extraction" to local consolidation. | accepted | Added a scope note that the prior inventory found active behavior, not stale compatibility to extract or delete; create/edit split remains open. |
| Value-object transition semantics were not explicit. | accepted | Added a retry-state transition table covering normal retries, the extra recoverable-parse retry, exhausted extra retry, and non-extra failures. |
| Behavior pin coverage needed both positive and negative extra-retry cases. | accepted | Added positive and negative `recoverable_parse` pin requirements plus final event-shape preservation. |
| The committed-text hygiene regex would false-positive on runtime `phase="self_correction"`. | accepted | Removed `slice|phase` from the production/test/doc hygiene regex. |
| The production diff needed a hard size bound. | accepted | Added a 60 net LOC production diff budget and stop/re-plan rule. |
| The plan did not name `MAX_SELF_CORRECTION_RETRIES = 3` explicitly. | accepted | Added the exact constant location in `ai_builder_proposal_processor.py:172`. |
| The value-object justification needed PRD evidence. | accepted | Added the PRD-005 line citation and clarified that the object is a local frozen dataclass, not an interface. |
| The PRD acceptance-criterion crosswalk was incomplete. | accepted | Added which acceptance criteria this slice advances and which remain open. |

## Local Verification Notes

- `git grep -n "recoverable_parse\\|extra_retry_available\\|_EXTRA_RETRY_FAILURE_KINDS" backend/tests` returned no matches, confirming the extra-retry path is unpinned in tests.
- `git grep -nE "^MAX_SELF_CORRECTION_RETRIES" backend/src` located `MAX_SELF_CORRECTION_RETRIES = 3` in `backend/src/intric/flows/ai_builder/ai_builder_proposal_processor.py:172`.
- `git log --since "60 days ago" --oneline -- backend/src/intric/flows/ai_builder/ai_builder_proposal_repair.py` shows prior repair-loop work touched retry behavior, including `2eb681d0 Widen AI Builder self-correction budget to 3 retries (P0.3)`.

## Plan Changes

- Updated `docs/refactor/execution/batch-6-ai-builder-contract-split/plan.md`.
- Updated `docs/refactor/execution/batch-6-ai-builder-contract-split/journal.md`.
- No source or test implementation has started.

## Plan Verification Result

- Claude session: `eneo-flow-batch6-ai-builder-contract-split`
- Phase: verification
- Iteration: 2
- Verdict: green
- Green light: yes
- Minimum score: 8
- Artifact: `.codex/artifacts/claude-peer-loop-batch-6-repair-contract-hardening-plan-verification-20260430T132047Z.md`

Claude reported all seven plan findings resolved:

- stale TL;DR resolved by active repair-only plan and archived prompt/audit checkpoint
- `recoverable_parse` pin is mandatory regardless of production refactor
- user approval is recorded
- retry-state transition table matches current source semantics
- hygiene regex no longer false-positives on runtime `phase="self_correction"`
- `MAX_SELF_CORRECTION_RETRIES = 3` is explicitly pinned
- PRD-005 crosswalk distinguishes this repair hardening from later create/edit separation

The script exited nonzero because `--require-green` did not parse Claude's
markdown-formatted `## GREEN_LIGHT: yes`, but the review body itself contains
`VERDICT: green`, `GREEN_LIGHT: yes`, and "Implementation can begin." The
artifact is preserved under `.codex/artifacts/`.

## Implementation Review Result

- Claude session: `eneo-flow-batch6-ai-builder-contract-split`
- Phase: implementation
- Iteration: 2
- Verdict: changes required
- Green light: no
- Minimum score: 9
- Artifact: `.codex/artifacts/claude-peer-loop-batch-6-repair-contract-hardening-implementation-20260430T133157Z.md`

## Implementation Review Accepted Findings

| Finding | Verdict | Reconciliation |
|---|---|---|
| `retrospective-2.md` claimed `plan.md` was updated to keep `test_ai_builder_proposal_processor.py` in scope, but Claude read the expected-files section as still omitting that file. | accepted | Tightened `plan.md` so `test_ai_builder_proposal_processor.py` appears as an explicit expected test-change file, with a note that validation exposed stale retry-config expectations for nullable edit-context keys. |

Claude found no substantive source/test issue. It explicitly green-lit the
value-object shape, retry-state transition preservation, numeric retry budget
preservation, `recoverable_parse` behavior pins, no fake interface, no event /
audit / logging change, no frontend/router/planner/create-edit scope drift, and
production diff size.

## Implementation Verification Result

- Claude session: `eneo-flow-batch6-ai-builder-contract-split`
- Phase: verification
- Iteration: 2
- Verdict: green
- Green light: yes
- Minimum score: 9
- Artifact: `.codex/artifacts/claude-peer-loop-batch-6-repair-contract-hardening-implementation-verification-20260430T133448Z.md`

Claude verified that the prior documentation finding is resolved and found no
accepted or partial findings. Local verification confirms the negative
failure-kind parametrization now includes `quality` in
`test_ai_builder_proposal_repair.py`, so the executable pin matches the
transition table exactly.
