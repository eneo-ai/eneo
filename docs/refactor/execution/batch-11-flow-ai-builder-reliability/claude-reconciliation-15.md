# Batch 11.5d Claude Reconciliation - Underlag Dataflow And Runtime Metadata

## TL;DR

1. Claude rejected prompt-wording and LLM-first fixes for the reported audio-to-DOCX failure.
2. The accepted owner is the typed create-draft/compiler path for underlag and the resolved planning-state slot for runtime metadata.
3. Codex implemented `uses_previous_outputs` as a narrow text-output reference, not a broad parallel dataflow system.
4. Claude green-lit the implementation after requiring backend-owned schema hiding, text-output validation, dead-branch deletion, localization, and PDF parity.
5. No accepted Claude blocker remains; live exact-flow smoke is deferred only because the tool path still blocks Docker/local runtime commands.

## Plan Reviews

| Iteration | Artifact | Verdict | Green light | Outcome |
|---:|---|---|---|---|
| 1 | `.codex/artifacts/claude-peer-loop-batch-11-5d-runtime-field-gating-plan-20260503T101054Z.md` | `changes_required` | `no` | Runtime field handling needed to be owned by metadata state, not by another prompt warning. |
| 2 | `.codex/artifacts/claude-peer-loop-batch-11-5d-runtime-field-gating-revised-plan-20260503T101533Z.md` | `green` | `yes` | Approved compiler-gated runtime fields. |
| 3 | `.codex/artifacts/claude-peer-loop-batch-11-5e-swedish-audio-input-architecture-brittleness-20260503T110606Z.md` | `changes_required` | `no` | Input architecture needed source/artifact separation. |
| 4 | `.codex/artifacts/claude-peer-loop-batch-11-5e-long-term-llm-first-flow-ai-builder-architecture-20260503T111809Z.md` | `changes_required` | `no` | LLM-first flow construction was too brittle for this failure class. |
| 5 | `.codex/artifacts/claude-peer-loop-batch-11-5f-flow-ai-builder-underlag-dataflow-plan-20260503T113034Z.md` | `changes_required` | `no` | Source-material dependencies needed a smaller source-scope contract. |
| 6 | `.codex/artifacts/claude-peer-loop-batch-11-5f-revised-source-scope-dataflow-plan-20260503T114010Z.md` | `changes_required` | `no` | Direction was right, but implementation had to stay in skeleton/compiler mechanics. |

## Accepted Findings

| Finding | Resolution |
|---|---|
| More Swedish instructions would create an endless wording loop. | Fixed the deterministic input architecture, runtime metadata state, and compile dataflow instead. |
| `Underlag till text` must own step material. | Source material is emitted as `input_bindings.question` sections, not appended to `assistant_spec.instructions`. |
| Later structured steps need non-adjacent text source material. | Added typed `uses_previous_outputs` refs restricted to earlier text output steps. |
| Runtime fields need a policy owner. | `runtime_metadata_fields` now gates whether outline `input_fields` can survive compilation. |
| The backend already owns audio transcription. | Leading LLM-authored audio transcription steps are dropped or rewritten when the skeleton inserts the transcribe-only prefix. |

## Implementation Review

| Iteration | Artifact | Verdict | Green light | Minimum score | Outcome |
|---:|---|---|---|---:|---|
| 7 | `.codex/artifacts/claude-peer-loop-batch-11-5f-underlag-dataflow-implementation-verification-20260503T115438Z.md` | `green` | `yes` | 7 | Approved with small immediate follow-ups. |
| 8 | `.codex/artifacts/claude-peer-loop-batch-11-5d-underlag-runtime-final-verdict-format-20260503T121823Z.md` | `green` | `yes` | 8 | Confirmed all follow-ups, typed runtime metadata gating, and final parser-readable green light. |

Accepted implementation follow-ups:

| Finding | Resolution |
|---|---|
| `uses_previous_outputs` should not be visible to the LLM-facing outline schema. | Added it to backend-owned outline keys and schema tests. |
| Previous-output refs should validate output type. | Validator/dataflow normalization now accept text producers only. |
| A dead instruction-compiler branch risked a parallel owner. | Removed the branch and kept all source material in input bindings. |
| Source-material label should localize. | Swedish skeleton output uses `Källmaterial`; English uses `Source material`. |
| The text input override needs a reason. | Added one invariant comment where source foundation refs need text input. |
| PDF parity should be covered. | Added PDF regression confirming all-previous fan-in remains the PDF-safe route. |

## Final Shape

| Concept | Canonical owner |
|---|---|
| Runtime source material type | `ai_builder_input_architecture_policy.py` and `PlanningState` slot resolution. |
| Runtime metadata field policy | `ai_builder_runtime_input_fields.py` and `runtime_metadata_fields` resolved slot. |
| Outline form-field survival | `compile_outline_to_create_draft(...)`. |
| Non-adjacent text-source dependencies | `PreviousOutputRef` / `NewStepDraft.uses_previous_outputs`. |
| Underlag binding rendering | `compile_input_bindings(...)`. |
| Audio source foundation refs | `StepSkeletonPlan` in `ai_builder_step_skeleton.py`. |
| Create draft dataflow validation | `ai_builder_create_validator.py` and `ai_builder_create_dataflow.py`. |

## Validation

| Command | Result |
|---|---|
| `uv run pytest tests/unittests/flows/ai_builder -q` | Passed: `1811 passed, 4 skipped`. |
| `uv run pytest tests/integration/flows/ai_builder/benchmark/test_slot_resolver_corpus.py tests/integration/flows/ai_builder/benchmark/test_baseline_benchmark.py -q` | Passed: `69 passed`. |
| `uv run ruff check <11.5d touched source and test files>` | Passed. |
| `uv run pyright <11.5d touched source and test files>` | Passed. |
| `git diff --check -- <11.5d touched paths>` | Passed. |

## Remaining Disagreement Or Deferred Work

No accepted Claude blocker remains. Codex agrees with Claude's restraint: do
not add a broad source-scope abstraction until a second concrete source-material
pattern proves that `uses_previous_outputs` is too narrow.

The only deferred validation is an exact live API smoke of the latest reported
debug-export prompt. The current command path rejects Docker before execution,
so the slice relies on compile regressions plus the AI Builder unit and
benchmark suites until the smoke path is available.

Confidence: high.
