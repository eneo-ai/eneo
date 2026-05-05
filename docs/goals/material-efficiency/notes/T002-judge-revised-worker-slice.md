TL;DR:
1. Claude correctly rejected the first Worker proposal as underspecified.
2. The revised slice keeps `ai_builder_source_material.py` as canonical owner but replaces the artifact gate with a primary-source-required boundary predicate instead of blindly widening.
3. Metrics are scoped to test-local helpers only; production metrics are deferred to T005.
4. Worker must explicitly test `INTENTIONAL_PARTIAL`, empty-string question handling, primary text input, and no-JSON-predecessor false positives.
5. Worker may proceed only if Claude iteration 2 accepts this narrowed scope or any remaining disagreement is documented with source evidence.

## Judge Decision Draft

Decision: revise and re-run Claude before activating Worker.

Claude artifact:

- `.codex/artifacts/claude-peer-loop-flow-ai-builder-material-efficiency-t002-judge-critique-iteration-1-20260505T181615Z.md`

Key accepted critique:

- Widening `iter_compiled_source_material_boundaries` by simply deleting the artifact gate at `backend/src/intric/flows/ai_builder/ai_builder_source_material.py:97-98` is too broad.
- `SourceMaterialBindingStatus.INTENTIONAL_PARTIAL` at `backend/src/intric/flows/ai_builder/ai_builder_source_material.py:143-147` may become over-permissive once text-terminal cases are included.
- `_compiled_primary_source_text_step` at `backend/src/intric/flows/ai_builder/ai_builder_source_material.py:354-366` can mis-pick a downstream text renderer when no primary source step exists.
- Metrics should stay test-local in this first slice; production metrics belong to T005.

## Revised Worker Objective

Add red tests and a small production change so source-material boundary detection covers text-terminal report composers only when there is an actual primary source text step. Keep normalizer and linter symmetric through the existing iterator/status functions.

The implementation should:

- Replace the artifact-only gate with a primary-source-required boundary predicate.
- Treat primary runtime text input (`flow_input text -> text`) as a possible source-material step or skip boundaries where no primary source exists.
- Ensure a composer/finalizer that references only the immediate structured output but not the primary source is `NEEDS_COMPLETION`, not silently `INTENTIONAL_PARTIAL`.
- Preserve `COMPLETE` behavior when both immediate structured output and source text are already referenced.
- Keep pure JSON-output flows and ordinary text->text chains untouched.
- Avoid blanket `all_previous_steps`.
- Avoid new production metric modules, `StepMaterialPlan`, `StepBindingPlan`, or any parallel source of truth.

## Allowed Files

- `backend/src/intric/flows/ai_builder/ai_builder_source_material.py`
- `backend/tests/unittests/flows/ai_builder/test_ai_builder_step_transition_policy.py`
- `backend/tests/unittests/flows/ai_builder/test_ai_builder_validator.py`
- `backend/tests/integration/flows/ai_builder/benchmark/test_manual_api_scoring.py`

No production metrics helper is allowed in this slice. If test-local metrics cannot satisfy the goal, stop and return to Judge.

## Required Red Tests

Add or update tests with names that make the behavior explicit:

1. Text-terminal source-material completion:
   - audio/document/text primary source -> JSON -> JSON -> text finalizer.
   - finalizer `input_bindings.question` includes `{{ step_a.output.text }}` and immediate `{{ step_c.output.structured }}`.
   - finalizer stays `previous_step`; no `all_previous_steps`.

2. Linter/normalizer symmetry:
   - unbound text-terminal shape warns with `source_material_boundary_missing_underlag`.
   - normalized shape does not warn.

3. Pure JSON-output negative:
   - source -> JSON -> JSON terminal JSON remains untouched and does not warn.

4. No JSON predecessor negative:
   - source text -> text -> text terminal is not a boundary and does not warn.

5. Complete text-terminal binding:
   - question already references both immediate structured output and source text.
   - status is complete, no normalization, no warning.

6. Immediate-structured-only binding:
   - question references only `{{ step_c.output.structured }}`.
   - status needs completion and the normalizer appends the source text.

7. Empty-string question:
   - `input_bindings={"question": ""}` is treated as missing and normalized.

8. Primary text input:
   - `flow_input text -> text` source can be used as the primary source material, or if the chosen implementation skips it, the test must prove no downstream renderer is mis-picked.

9. Manual scoring parity:
   - `uses_underlag_till_text_correctly` remains true for document/audio artifact cases and now catches the text-terminal missing-source shape.

## Test-Local Metrics

Add test-local pure helpers only if needed for the red golden:

- `binding_byte_size(question: str) -> int`
- `fan_in_width(question: str, known_steps: Sequence[StepSpec]) -> int`
- `structured_field_reference_count(...) -> int`
- `whole_output_reference_count(...) -> int`
- `source_duplication_count(...) -> int`
- `all_previous_steps_count(spec: FlowDraftSpecCore) -> int`

Reuse `template_reference_analyzer.analyze_template` rather than substring-only parsing. Do not add production metric symbols in this slice.

## Verify

```bash
uv run --directory backend pytest tests/unittests/flows/ai_builder/test_ai_builder_step_transition_policy.py -q
uv run --directory backend pytest tests/unittests/flows/ai_builder/test_ai_builder_validator.py -q -k source_material
uv run --directory backend pytest tests/integration/flows/ai_builder/benchmark/test_manual_api_scoring.py -q
uv run --directory backend pyright src/intric/flows/ai_builder/ai_builder_source_material.py src/intric/flows/ai_builder/ai_builder_step_transition_policy.py src/intric/flows/ai_builder/ai_builder_validation_quality.py
uv run --directory backend ruff check src/intric/flows/ai_builder/ai_builder_source_material.py tests/unittests/flows/ai_builder/test_ai_builder_step_transition_policy.py tests/unittests/flows/ai_builder/test_ai_builder_validator.py tests/integration/flows/ai_builder/benchmark/test_manual_api_scoring.py
uv run --directory backend ruff format --check src/intric/flows/ai_builder/ai_builder_source_material.py tests/unittests/flows/ai_builder/test_ai_builder_step_transition_policy.py tests/unittests/flows/ai_builder/test_ai_builder_validator.py tests/integration/flows/ai_builder/benchmark/test_manual_api_scoring.py
```

## Stop If

- The first test cannot fail before production changes.
- The fix needs `all_previous_steps`.
- The fix needs a new production material-planning abstraction.
- Boundaries are emitted for pure JSON terminal flows or no-JSON-predecessor text chains.
- `INTENTIONAL_PARTIAL` cannot be made safe without broad behavior changes.
- Pyright requires weakening types or adding ignores.

## Iteration 2 Addendum

Claude iteration 2 accepted the owner and narrowed predicate direction but blocked on
contract clarity and existing DOCX/PDF golden blast radius.

Accepted decisions before Worker activation:

- Keep `SourceMaterialBindingStatus` as three states for this slice.
- Define `COMPLETE` as: the question references both the immediate structured predecessor and the primary source text step.
- Define `NEEDS_COMPLETION` as: the question is missing, empty, references only the immediate structured predecessor, or otherwise lacks the primary source text when a primary source boundary exists.
- Define `INTENTIONAL_PARTIAL` narrowly as: the question references the primary source text but intentionally omits the immediate structured predecessor. This preserves a meaningful third state for cases that bypass the JSON extraction and read from source directly.
- Change `_compiled_primary_source_text_step` to return `StepSpec | None`; skip boundaries when no primary source step exists instead of falling back to an arbitrary prior text renderer.
- Split compiled primary source input types from create-draft primary source input types if `InputType.TEXT` support is needed, so adding text-input source support does not silently widen create-draft DOCX/PDF behavior.
- Add `backend/tests/unittests/flows/ai_builder/test_ai_builder_create_compiler.py` to allowed files only for integration coverage or explicit golden updates if tightening status changes existing DOCX/PDF outcomes.

Pre-flight evidence:

```bash
uv run --directory backend pytest tests/unittests/flows/ai_builder/test_ai_builder_create_compiler.py -q -k 'source_underlag or audio_report_section_extractors or direct_audio_docx_bad_shape or targeted_underlag'
# 9 passed, 98 deselected
```

`SourceMaterialBindingStatus` import audit:

- Production consumers are `ai_builder_step_transition_policy.py` and `ai_builder_validation_quality.py`.
- Benchmark scoring consumes only `SourceMaterialBindingStatus.COMPLETE`.
- No caller currently relies on `INTENTIONAL_PARTIAL` specifically outside `ai_builder_source_material.py`.

Additional Worker requirements:

- Add an idempotence test for `source_material_question_for_boundary`: applying completion to an already-completed question must not duplicate source or structured sections.
- Add a create-time-to-compile-time interaction test, preferably in `test_ai_builder_create_compiler.py`, proving a representative targeted-underlag composer classifies complete and does not get double-rewritten.
- Add one domain-neutral English label assertion for the newly covered text-terminal path.
- Add `ai_builder_step_transition_policy.py` and `ai_builder_validation_quality.py` to ruff check/format commands even if not edited, because their behavior changes through the shared iterator.
