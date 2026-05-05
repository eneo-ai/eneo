# T017 Judge Receipt: Create Critic Remediation Slice

## Decision

Activate a Worker slice that translates semantic critic issues into create-mode outline guidance before they reach the planner repair turn.

## Accepted Plan Review Requirements

Claude plan review returned `GREEN_LIGHT: yes` after the plan added:

- closed coverage for every semantic critic invariant id;
- a required processor boundary test;
- explicit rejection of adding `create_remediation` to `CriticInvariant` for this slice;
- a guard against specialty vocabulary in new create-mode remediation text.

## Ownership Decision

The create-specific translation belongs in `ai_builder_create_feedback.py`, next to `format_create_validation_feedback`. The rejected alternative was adding a `create_remediation` field to each `CriticInvariant`. That may become worthwhile if more planner modes need distinct wording, but it would make the generic critic registry own one caller's repair vocabulary in this slice.

## Worker Scope

Allowed files:

- `backend/src/intric/flows/ai_builder/ai_builder_create_feedback.py`
- `backend/src/intric/flows/ai_builder/ai_builder_proposal_processor.py`
- `backend/tests/unittests/flows/ai_builder/test_ai_builder_create_feedback.py`
- `backend/tests/unittests/flows/ai_builder/test_ai_builder_proposal_processor.py`
- `docs/goals/flow-ai-builder-quality-hardening/state.yaml`
- `docs/goals/flow-ai-builder-quality-hardening/notes/T017-judge-create-critic-remediation.md`
- `docs/goals/flow-ai-builder-quality-hardening/notes/T018-worker-create-critic-remediation.md`

## Validation Required

- red check for new create critic feedback tests before implementation;
- focused AI Builder create-feedback/proposal-processor/critic tests;
- strict pyright on touched source/tests;
- ruff check and format check on touched source/tests;
- `lint-imports`;
- specialty-vocabulary grep over touched source/tests;
- `git diff --check` over touched paths.

## Stop Conditions

- Need to edit `ai_builder_critic_invariants.py`.
- Need to weaken edit-mode or compiled-spec remediation strings.
- Need broad prompt, schema, runtime, or unrelated dirty files.
- Coverage cannot close over all semantic invariant ids.
- Processor boundary test cannot be made deterministic.
- Claude implementation review blocks the commit.
