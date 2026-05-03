# Claude Reconciliation 17 — Source-Material Boundary Canonicalization

## TL;DR

1. Claude rejected the first source-material plan because it kept an audio-only,
   skeleton-local owner.
2. The accepted design moved source-material boundary logic into a narrow
   canonical owner shared by create-draft normalization, compiled-spec
   normalization, validation, and deterministic scoring.
3. The quality warning remains defensive and is not in the retry loop.
4. Runtime transcript/transcription fields are treated as primary audio-input
   shadows, not secondary `Inmatningsfält`.
5. Post-green refinements removed source-picker drift and added idempotency,
   label, and scoring-regression coverage.

## Iterations

| Iteration | Artifact | Verdict | Green light | Minimum score | Notes |
|---:|---|---|---|---:|---|
| 1 | `.codex/artifacts/claude-peer-loop-ai-builder-source-material-runtime-fields-plan-20260503T133745Z.md` | `changes_required` | `no` | n/a | Asked Codex to identify the bypass path, avoid duplicate source-material detectors, keep the warning out of the quality retry loop, and move enrichment into draft/spec normalization. |
| 2 | `.codex/artifacts/claude-peer-loop-ai-builder-source-material-runtime-fields-verification-20260503T135932Z.md` | `green` | `yes` | 7 | Verified the long-term deterministic fix and identified non-blocking refinements. |

## Accepted Findings

| Claude finding | Codex resolution |
|---|---|
| Skeleton-only enrichment fixed one path but left direct create-draft and compiled-spec paths exposed. | Added `ai_builder_source_material.py`, called it from create-draft mechanics, and completed compiled-spec source-material boundaries in topology normalization. |
| A validation warning in the retry loop could become another prompt-repair loop. | Added `source_material_boundary_missing_underlag` only as a defensive lint; it is not part of `QUALITY_RETRY_WARNING_CODES`. |
| Manual scoring duplicated source-material boundary rules. | Scoring now imports `iter_compiled_source_material_boundaries`, `source_material_binding_is_complete`, and the primary-input shadow predicate from production owners. |
| Two source pickers could drift. | Draft and compiled selection now both prefer the primary material flow-input text step. |
| Swedish label token `text` was too broad. | Removed it and added an English `Source material` regression. |
| Idempotency and ordering coverage was weak. | Added tests for idempotent normalization and preserving existing question tails after injected source-material sections. |

## Disagreements

No material disagreements. Claude's remaining refinements were accepted and
implemented before the commit boundary.

## Validation Evidence

| Command | Result |
|---|---|
| `cd backend && uv run ruff check <11.6b touched source and test files>` | Passed. |
| `cd backend && uv run pyright <11.6b touched source and test files>` | Passed: `0 errors, 0 warnings, 0 informations`. |
| `cd backend && uv run pytest tests/unittests/flows/ai_builder/test_ai_builder_create_dataflow.py tests/unittests/flows/ai_builder/test_ai_builder_create_compiler.py tests/unittests/flows/ai_builder/test_ai_builder_step_transition_policy.py tests/unittests/flows/ai_builder/test_ai_builder_validator.py tests/unittests/flows/ai_builder/test_ai_builder_primary_input_fields.py tests/unittests/flows/ai_builder/test_ai_builder_form_field_lifecycle.py tests/unittests/flows/ai_builder/test_ai_builder_runtime_input_fields.py tests/integration/flows/ai_builder/benchmark/test_manual_api_scoring.py -q` | Passed: `211 passed`, existing warnings only. |
| `cd backend && uv run pytest tests/unittests/flows/ai_builder/test_ai_builder_step_skeleton.py tests/unittests/flows/ai_builder/test_ai_builder_proposal_processor.py::test_outline_audio_to_docx_returns_plan_without_self_correction tests/unittests/flows/ai_builder/test_ai_builder_materialization_bridge.py -q` | Passed: `63 passed`, existing warning only. |
| `cd backend && uv run pytest tests/integration/flows/ai_builder/benchmark -q` | Passed: `107 passed`, existing warnings only. |

## Carry-Forward

| Item | Owner |
|---|---|
| Docker validation could not run because Docker process creation was approval-blocked in this tool environment. Re-run it where Docker is allowed. | Next implementation operator |
| Additional live bad-shape exports should become source-material boundary fixtures before changing prompts. | Batch 11 reliability |
