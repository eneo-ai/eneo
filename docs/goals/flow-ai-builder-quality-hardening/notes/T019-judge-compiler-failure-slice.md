# T019 Judge Receipt: Compiler Failure Slice

## Decision

Split the clean-HEAD `test_ai_builder_create_compiler.py` failures.

Activate T020 for runtime input hint filtering only. Defer the targeted-underlag
auto-binder invocation to the next source slice because Claude identified an
ownership issue: the binder should likely run through the shared dataflow
normalization path, not only `compile_outline_to_create_draft`.

## Claude Review

Session `flow-ai-builder-quality-hardening-t019`:

- Iteration 1: `changes_required`, `GREEN_LIGHT: no`, `MIN_SCORE: 6`.
  Claude accepted the evidence but rejected combining runtime hint filtering
  and targeted-underlag auto-binder wiring.
- Iteration 2: `green`, `GREEN_LIGHT: yes`, `MIN_SCORE: 8` for runtime input
  hint filtering only.

## Worker Scope

Allowed files:

- `backend/src/intric/flows/ai_builder/ai_builder_create_outline.py`
- `backend/tests/unittests/flows/ai_builder/test_ai_builder_create_compiler.py`
- `docs/goals/flow-ai-builder-quality-hardening/state.yaml`
- `docs/goals/flow-ai-builder-quality-hardening/notes/T019-judge-compiler-failure-slice.md`
- `docs/goals/flow-ai-builder-quality-hardening/notes/T020-worker-runtime-input-hint-filtering.md`

## Acceptance

- Server-derived runtime input hints become `form_fields` only when the outline
  references the hint name in `uses_input_fields`.
- Explicit planner-declared `input_fields` remain unconditional and preserve
  existing behavior.
- `NO_EXTRA_RUNTIME_METADATA` and primary-input shadow filtering remain intact.
- Add a partial-hint regression test where one hint is referenced and another is
  not.

## Deferred T021 Candidate

Fix the live quality failure:

```text
Plan still invalid after correction. Quality issues:
1. Beskriv ett semantiskt kompositionssteg som väver in relevanta strukturerade resultat från flera tidigare steg, inte bara det senaste.
```

This is the targeted-underlag auto-binder invocation problem. The next Judge
slice should place the binder at the canonical dataflow normalization boundary,
likely `normalize_create_draft_mechanics(..., aggregation_intent=...)`, with
coverage for outline and non-outline draft paths.
