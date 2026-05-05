# T022 Worker: Targeted Underlag Fan-In

## Objective

Invoke the existing targeted-underlag auto-binder at the create outline compilation boundary so generated audio/document composer drafts include explicit structured fan-in before quality validation.

## Red Evidence

Before implementation, this command failed with seven failures:

```bash
cd backend && uv run pytest -q tests/unittests/flows/ai_builder/test_ai_builder_create_compiler.py \
  -k 'audio_docx_four_phase_body_step_fans_in_prior_work or audio_artifact_final_body_step_fans_in_prior_structured_work or audio_pdf_protocol_step_auto_authors_targeted_underlag or audio_document_without_pattern_still_creates_transcript_source or audio_docx_body_step_auto_authors_targeted_refs_when_json_predecessor'
```

All failures showed the same defect: the body/composer step remained `all_previous_steps` or otherwise lacked explicit targeted structured refs.

## Implementation

- Imported `auto_bind_targeted_underlag_for_text_composer` into `ai_builder_create_outline.py`.
- Applied it once in `compile_outline_to_create_draft` after skeleton composition, orphan form-field attachment, and dropped-primary-input logging.
- Passed `context.aggregation_intent` when available and defaulted to `linear` only when no compile context exists.
- Did not change prompts, repair behavior, runtime execution, frontend code, materialization, compiler signatures, or the generic normalizer.

## Validation

Completed so far:

```bash
cd backend && uv run pytest -q tests/unittests/flows/ai_builder/test_ai_builder_create_compiler.py \
  -k 'audio_docx_four_phase_body_step_fans_in_prior_work or audio_artifact_final_body_step_fans_in_prior_structured_work or audio_pdf_protocol_step_auto_authors_targeted_underlag or audio_document_without_pattern_still_creates_transcript_source or audio_docx_body_step_auto_authors_targeted_refs_when_json_predecessor'
# 7 passed, 99 deselected

cd backend && uv run pytest -n 4 -q tests/unittests/flows/ai_builder/test_ai_builder_create_compiler.py
# 106 passed

cd backend && uv run pytest -q tests/unittests/flows/ai_builder/test_ai_builder_plan_quality_critic.py::TestPreferTargetedUnderlagInvariant tests/unittests/flows/ai_builder/test_ai_builder_plan_quality_critic.py::TestFinalTextStepReferencesRelevantStructuredOutputs
# 27 passed

cd backend && uv run pyright src/intric/flows/ai_builder/ai_builder_create_outline.py tests/unittests/flows/ai_builder/test_ai_builder_create_compiler.py
# 0 errors, 0 warnings, 0 informations

cd backend && uv run ruff check src/intric/flows/ai_builder/ai_builder_create_outline.py tests/unittests/flows/ai_builder/test_ai_builder_create_compiler.py
# All checks passed

cd backend && uv run ruff format --check src/intric/flows/ai_builder/ai_builder_create_outline.py tests/unittests/flows/ai_builder/test_ai_builder_create_compiler.py
# 2 files already formatted

cd backend && uv run lint-imports --no-cache
# Contracts: 3 kept, 0 broken

git diff --check -- backend/src/intric/flows/ai_builder/ai_builder_create_outline.py backend/tests/unittests/flows/ai_builder/test_ai_builder_create_compiler.py docs/goals/flow-ai-builder-quality-hardening
# passed
```

## Self-Review

- Correctness: the change fixes the reported source class without asking the LLM to author backend-owned mechanics.
- Maintainability: the existing dataflow helper remains the canonical owner of the binding logic; the outline compiler only invokes it at the boundary where the bad draft is produced.
- Clean architecture: no runtime, frontend, repair, or materialization behavior changed.
- Type contracts: no new casts, ignores, `Any`, or stringly payloads.
- Complexity: one bounded pass over at most the outline step count.
- Risk: bridge/materialization may need a similar explicit invocation if future evidence shows that path emits the same bad shape; this was intentionally deferred to avoid speculative signature churn.

## Claude Implementation Review

Claude commit-gate review returned `GREEN_LIGHT: yes` with `MIN_SCORE: 9`.

## Production Readiness

This phase is production-ready and mergeable as a narrow source slice. Staging must stay limited to the source file plus goal receipts; unrelated dirty files remain untouched.
