# T003 Worker Receipt: Text-Terminal Source-Material Routing

## Result

Done. The source-material boundary owner now covers text-terminal report composers as well as DOCX/PDF artifact composers when a flow has a primary source text step and crosses a JSON boundary.

## Problem Reproduced

Before the production change, a flow shaped like:

- `step_a`: flow input audio/text -> text
- `step_b`: previous text -> JSON
- `step_c`: previous JSON -> JSON
- `step_d`: previous JSON -> text report

did not produce a compiled source-material boundary. The final text report could receive only `{{ step_c.output.structured }}` or no explicit `question` binding at all, losing access to the original transcript/source material.

Red evidence:

- `uv run --directory backend pytest tests/unittests/flows/ai_builder/test_ai_builder_step_transition_policy.py -q -k 'text_report or pure_json_chain or json_predecessor or primary_source or empty_source_material'`
  - Initial result: 3 failed, 3 passed.
  - Failing cases proved missing text-terminal normalization, empty question completion, and text flow input source handling.
- `uv run --directory backend pytest tests/unittests/flows/ai_builder/test_ai_builder_validator.py -q -k source_material_boundary`
  - Initial result: 1 failed, 5 passed.
  - Failing case proved the linter did not warn for missing underlag in a text-terminal boundary.
- `uv run --directory backend pytest tests/integration/flows/ai_builder/benchmark/test_manual_api_scoring.py -q -k text_terminal_missing_source_material`
  - Initial result: failed because deterministic scoring did not classify the text-terminal missing-source case.
- `uv run --directory backend pytest tests/unittests/flows/ai_builder/test_ai_builder_create_compiler.py -q -k 'text_report_keeps_source or direct_audio_docx_bad_shape or audio_report_section_extractors_keep_transcript'`
  - Initial result: 1 failed, 2 passed.
  - Failing case proved the create-draft compiler path also needed the same owner-level source-material rule for text-terminal reports.

## Production Change

Canonical owner retained:

- `backend/src/intric/flows/ai_builder/ai_builder_source_material.py`

Changes:

- Replaced document-artifact-only compiled boundary gating with material-report gating:
  - DOCX/PDF output remains covered.
  - Text-terminal output is covered only when the flow crosses from JSON after a primary source text step.
  - Pure JSON chains and text-only chains remain untouched.
- Extended create-draft source-material normalization with the same text-terminal material-report rule.
- Made `CompiledSourceMaterialBoundary` carry the resolved `primary_source_step`, avoiding fallback behavior and avoiding a parallel planner abstraction.
- Removed the now-unused `prior_text_steps` boundary field after resolving the primary source step at boundary discovery time.
- Preserved audio/document/file source preference over plain text flow input when multiple text-producing source steps exist.
- Kept `SourceMaterialBindingStatus` semantics explicit:
  - `COMPLETE`: immediate structured output plus primary source text.
  - `INTENTIONAL_PARTIAL`: primary source only or a specific structured subfield.
  - `NEEDS_COMPLETION`: missing, empty, or whole immediate structured output without source.

No `all_previous_steps` fallback was introduced.

## Tests Added

- Normalizer red/green coverage in `test_ai_builder_step_transition_policy.py`:
  - text-terminal completion
  - whole structured-only incomplete case
  - complete question idempotence
  - source-only intentional partial
  - empty question completion
  - no JSON predecessor negative case
  - pure JSON chain negative case
  - text flow-input primary source case
  - per-golden material-efficiency assertions for fan-in width, whole-output refs, source duplication count, and all-previous count
- Linter symmetry coverage in `test_ai_builder_validator.py`:
  - warning for missing text-terminal underlag
  - no warning for complete underlag
  - no warning for text chains without JSON predecessor
  - no warning for pure JSON chains
- Create compiler preflight/golden in `test_ai_builder_create_compiler.py`:
  - audio -> JSON -> JSON -> text report keeps both structured underlag and transcript source
- Deterministic scoring coverage in `test_manual_api_scoring.py`:
  - text-terminal missing source material fails `uses_underlag_till_text_correctly`

## Verification

Final green commands:

- `uv run --directory backend pytest tests/unittests/flows/ai_builder/test_ai_builder_step_transition_policy.py tests/unittests/flows/ai_builder/test_ai_builder_validator.py tests/unittests/flows/ai_builder/test_ai_builder_create_compiler.py tests/integration/flows/ai_builder/benchmark/test_manual_api_scoring.py -q`
  - `210 passed, 16 warnings`
- `uv run --directory backend ruff check src/intric/flows/ai_builder/ai_builder_source_material.py src/intric/flows/ai_builder/ai_builder_step_transition_policy.py src/intric/flows/ai_builder/ai_builder_validation_quality.py src/intric/flows/ai_builder/ai_builder_create_dataflow.py tests/unittests/flows/ai_builder/test_ai_builder_step_transition_policy.py tests/unittests/flows/ai_builder/test_ai_builder_validator.py tests/unittests/flows/ai_builder/test_ai_builder_create_compiler.py tests/integration/flows/ai_builder/benchmark/manual_api_scoring.py tests/integration/flows/ai_builder/benchmark/test_manual_api_scoring.py`
  - `All checks passed`
- `uv run --directory backend ruff format --check src/intric/flows/ai_builder/ai_builder_source_material.py src/intric/flows/ai_builder/ai_builder_step_transition_policy.py src/intric/flows/ai_builder/ai_builder_validation_quality.py src/intric/flows/ai_builder/ai_builder_create_dataflow.py tests/unittests/flows/ai_builder/test_ai_builder_step_transition_policy.py tests/unittests/flows/ai_builder/test_ai_builder_validator.py tests/unittests/flows/ai_builder/test_ai_builder_create_compiler.py tests/integration/flows/ai_builder/benchmark/manual_api_scoring.py tests/integration/flows/ai_builder/benchmark/test_manual_api_scoring.py`
  - `9 files already formatted`
- `uv run --directory backend pyright src/intric/flows/ai_builder/ai_builder_source_material.py src/intric/flows/ai_builder/ai_builder_step_transition_policy.py src/intric/flows/ai_builder/ai_builder_validation_quality.py src/intric/flows/ai_builder/ai_builder_create_dataflow.py tests/unittests/flows/ai_builder/test_ai_builder_step_transition_policy.py tests/unittests/flows/ai_builder/test_ai_builder_validator.py tests/unittests/flows/ai_builder/test_ai_builder_create_compiler.py tests/integration/flows/ai_builder/benchmark/test_manual_api_scoring.py`
  - `0 errors, 0 warnings, 0 informations`
- `git diff --check`
  - clean

## Self-Review

- Is this phase production-ready? Yes, pending T004 commit-gate review.
- Would you merge this phase? Yes, if Judge/Claude agrees after reviewing the final diff.
- Could this have been cleaner or smarter? The cleaner option was to keep source-material routing in the existing canonical owner and avoid a new material planner. That is what this slice does.
- Did we improve maintainability, architecture, and output quality? Yes. The boundary semantics are shared by normalizer, linter, create compiler, and deterministic scoring, with targeted tests for both positive and negative cases.
- Did we add AI slop comments, vague names, speculative abstractions, or type debt? No new abstraction was added. One enum docstring explains the non-obvious status contract.
- What remains intentionally out of scope? Form-field lifecycle improvements, automatic live-eval scoring, edit-path probes, and HTTP authoring capability probes remain queued follow-up slices.
