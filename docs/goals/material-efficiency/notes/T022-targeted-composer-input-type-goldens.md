# T022 Targeted Composer Input-Type Goldens

## TL;DR

Two compiler golden expectations still treated targeted document body composers as `json` consumers.
Current dataflow mechanics already normalize explicit `uses_previous_fields` / `uses_previous_outputs` composer prompts to text input material.
The source owner did not need a code change; the stale test expectations were aligned with the existing canonical behavior.
The previously failing compiler subset now passes.
The full local AI Builder unit suite now passes with `-n 4`.

## Problem

After T021, the full AI Builder unit suite exposed four failures in two parametrized compiler tests. The failures all had the same shape: the draft composer step emitted `input_type == "text"` while the golden still expected `input_type == "json"`.

## Canonical Owner

The canonical behavior is in `backend/src/intric/flows/ai_builder/ai_builder_create_dataflow.py`.

`normalize_create_draft_mechanics` treats explicit `uses_previous_fields` / `uses_previous_outputs` as text prompt material even when the referenced upstream outputs are structured JSON. The compiler test expectations should describe that behavior rather than reintroducing the old JSON input assumption.

## Change

- Updated `backend/tests/unittests/flows/ai_builder/test_ai_builder_create_compiler.py` so the audio artifact report body composer expects `input_type == "text"`.
- Updated the audio document final topology expectation so the body composer row is `("previous_step", "text", "text")`.
- No production source change was needed for this task.

## Verification

Previously failing subset:

```bash
uv run --directory backend pytest -n 4 tests/unittests/flows/ai_builder/test_ai_builder_create_compiler.py -q -k 'audio_artifact_final_body_step_fans_in_prior_structured_work or audio_document_without_pattern_still_creates_transcript_source'
```

Result: `4 passed in 9.88s`.

Full AI Builder unit suite:

```bash
uv run --directory backend pytest -n 4 tests/unittests/flows/ai_builder -q
```

Result: `2014 passed, 4 skipped, 42 warnings in 52.86s`.

## Acceptance

- The targeted composer input-type goldens match the current canonical mechanics.
- The full AI Builder unit suite is green with the required `-n 4`.
- No prompt-specific or flow-specific production code was added.

Confidence: high.
