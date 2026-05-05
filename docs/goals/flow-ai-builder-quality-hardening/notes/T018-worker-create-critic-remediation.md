# T018 Worker Receipt: Create Critic Remediation

## Change

Added create-mode formatting for semantic critic issues. The create repair turn now receives semantic outline guidance instead of instructions to author backend-owned mechanics such as step input wiring or template selectors.

## Invariant Classification

| Semantic invariant id | create-mode handling | reason |
|---|---|---|
| `runtime_metadata_requires_form_fields` | mapped | create mode should describe user-facing runtime inputs without internal field vocabulary |
| `sectioned_form_intake_requires_form_fields` | mapped | create mode should describe section/rubric inputs semantically |
| `rich_workflow_requires_form_fields` | mapped | create mode should add named runtime inputs and consuming steps semantically |
| `rich_workflow_requires_json_contract_step` | mapped | create mode exposes `output_fields`, not raw `output_contract` mechanics |
| `rich_workflow_requires_multiple_steps` | mapped | short generic step-splitting guidance |
| `structured_extraction_requires_json_contract_step` | mapped | create mode should describe structured extraction and named fields |
| `explicit_json_contract_request_without_step` | mapped | create mode should describe reusable structured information semantically |
| `field_reuse_requires_input_bindings` | mapped | create mode should describe field reuse intent, not bindings |
| `prefer_targeted_underlag_over_all_previous_steps` | mapped | create mode should describe targeted synthesis/composition intent |
| `final_text_step_must_reference_relevant_structured_outputs` | mapped | create mode should describe multi-prior structured composition intent |
| `form_fields_declared_must_be_referenced` | mapped | create mode should tie each declared runtime input to a semantic step |
| `mcp_selection_requires_semantic_support` | pass-through | existing remediation is already semantic and does not ask for backend mechanics |

## Tests

- `test_format_create_critic_feedback_translates_mechanics_to_semantics`
- `test_create_critic_feedback_covers_every_semantic_invariant`
- `test_create_critic_feedback_remediations_do_not_leak_backend_mechanics`
- `test_format_create_critic_feedback_passes_through_explicit_allowlist`
- `test_format_create_critic_feedback_rejects_unregistered_semantic_issue`
- `test_format_create_critic_feedback_rejects_architecture_issue`
- `test_create_contextual_quality_feedback_uses_semantic_remediation`
- `test_edit_contextual_quality_feedback_keeps_mechanics_remediation`
- `test_create_contextual_quality_feedback_still_enforces_architecture`

## Validation

- Red check: focused tests failed before implementation because the create critic formatter/constants did not exist and processor create feedback still returned raw mechanics.
- `cd backend && uv run pytest -n 4 -q tests/unittests/flows/ai_builder/test_ai_builder_create_feedback.py tests/unittests/flows/ai_builder/test_ai_builder_proposal_processor.py tests/unittests/flows/ai_builder/test_ai_builder_plan_quality_critic.py::TestPreferTargetedUnderlagInvariant tests/unittests/flows/ai_builder/test_ai_builder_plan_quality_critic.py::TestFinalTextStepReferencesRelevantStructuredOutputs` — passed, 83 tests.
- `cd backend && uv run pyright src/intric/flows/ai_builder/ai_builder_create_feedback.py src/intric/flows/ai_builder/ai_builder_proposal_processor.py tests/unittests/flows/ai_builder/test_ai_builder_create_feedback.py tests/unittests/flows/ai_builder/test_ai_builder_proposal_processor.py` — passed, 0 errors.
- `cd backend && uv run ruff check src/intric/flows/ai_builder/ai_builder_create_feedback.py src/intric/flows/ai_builder/ai_builder_proposal_processor.py tests/unittests/flows/ai_builder/test_ai_builder_create_feedback.py tests/unittests/flows/ai_builder/test_ai_builder_proposal_processor.py` — passed.
- `cd backend && uv run ruff format --check src/intric/flows/ai_builder/ai_builder_create_feedback.py src/intric/flows/ai_builder/ai_builder_proposal_processor.py tests/unittests/flows/ai_builder/test_ai_builder_create_feedback.py tests/unittests/flows/ai_builder/test_ai_builder_proposal_processor.py` — passed after formatting one test file.
- `cd backend && uv run lint-imports --no-cache` — passed, 3 contracts kept.
- Specialty-vocabulary guard on added source/test lines — passed, no new matches.
- `git diff --check` over touched paths — passed.
- Claude implementation review iteration 1 returned `GREEN_LIGHT: yes`, `MIN_SCORE: 8`; accepted cheap findings for a precondition comment and direct passthrough/unmapped tests before iteration 2.
- Claude implementation review iteration 2 returned `GREEN_LIGHT: yes`, `MIN_SCORE: 9`.
- Broad sweep `cd backend && uv run pytest -n 4 -q tests/unittests/flows/ai_builder` failed in 10 existing `test_ai_builder_create_compiler.py` cases. Those failures are outside the touched T018 surface and the failing file does not reference `ai_builder_create_feedback`, `format_create_critic_feedback`, `AIBuilderProposalProcessor`, or `_format_create_contextual_quality_feedback`. They remain broad-suite drift, not a T018 product regression.
- Detached clean-HEAD worktree verification reproduced the same 10 `test_ai_builder_create_compiler.py` failures at `e8a034bd`, before the T018 diff. A first clean-worktree attempt could not build a fresh venv because `pg_config` was unavailable for `psycopg2-binary`; rerunning with the existing backend venv and copied local `.env` reproduced the same failures.

## Self-Review

- Correctness: create-mode repair guidance no longer tells the planner to author hidden mechanics; edit/general critic feedback remains raw.
- Maintainability: create-specific wording lives with the create feedback owner; closed coverage test prevents silent drift when semantic invariants are added.
- Architecture: processor still owns architecture enforcement and invariant evaluation; the formatter only formats already-evaluated issues.
- Type safety: uses the existing frozen `CriticIssue` dataclass; no `Any`, casts, or ignores.
- Scope: intentionally avoids changing critic invariant definitions, create schema, prompts, runtime behavior, or unrelated dirty files.
- Token cost: replacement strings are shorter and more generic than the raw mechanics-heavy remediations they replace.

## Carry-Forward

Converting critic invariant ids to a closed enum or literal type would make coverage stronger at type-check time, but that is larger than this slice because many tests compare string ids directly.
