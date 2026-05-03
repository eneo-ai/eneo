# Retrospective 17 — Source-Material Boundary Canonicalization

## TL;DR

1. The reported audio-to-DOCX failure was a dataflow issue, not a wording issue.
2. Source-material underlag now has one canonical owner used by create-draft
   normalization, compiled-spec normalization, validation, and scoring.
3. Direct create-draft and already-compiled bad shapes are both normalized
   deterministically without entering the LLM retry loop.
4. Transcript/transcription form fields are filtered as duplicate primary audio
   input, not useful secondary runtime fields.
5. Local validation passed; Docker validation was attempted but the current tool
   environment rejects Docker process creation under the no-approval policy.

## What Changed

| Area | Change |
|---|---|
| Source-material owner | Added `backend/src/intric/flows/ai_builder/ai_builder_source_material.py` for source-boundary detection, source selection, label selection, and question construction. |
| Create path | `normalize_create_draft_mechanics` and `compile_create_draft` now run source-material normalization before compiling specs. |
| Compiled-spec path | `normalize_ai_builder_step_topology` injects missing source-material underlag for document artifact flows crossing JSON boundaries. |
| Skeleton path | Removed the earlier skeleton-local source-material enrichment to avoid an audio-only parallel owner. |
| Validation | Added `source_material_boundary_missing_underlag` as a defensive lint only. |
| Runtime fields | Added transcript/transcription Swedish and English aliases as audio primary-input shadows. |
| Benchmark scoring | Reused production source-material and primary-input predicates. |

## Checklist

| Section | Item | Result | Evidence |
|---|---|---|---|
| A | Implemented planned source-material and runtime-field correction. | pass | Plan section `11.6b`; source owner `ai_builder_source_material.py`; tests in `test_ai_builder_step_transition_policy.py`. |
| A | Stayed within Batch 11 Flow AI Builder scope. | pass | Touched files are under `backend/src/intric/flows/ai_builder`, AI Builder tests, benchmark scoring, and Batch 11 docs. |
| A | Scope changed only to address Claude's accepted owner finding. | pass | `claude-reconciliation-17.md` records the accepted canonical-owner change. |
| A | Behavior pins landed before deletion. | pass | New direct create-draft, compiled-spec, validator, scoring, and primary-input tests cover behavior before the skeleton-local path is removed. |
| A | Preserved applicable implementation-readiness decisions. | pass | No router, persistence, migration, or frontend state changes. |
| B | Checked acceptance criteria against code. | pass | `ai_builder_step_transition_policy.py` completes underlag; `manual_api_scoring.py` reuses the production predicate; primary aliases are in `ai_builder_primary_input_fields.py`. |
| B | Criteria are evidence-backed, not intent-backed. | pass | Validation commands passed with behavior tests named below. |
| C | Validation commands ran. | pass | Ruff, Pyright, changed-file AI Builder tests, adjacent skeleton/materialization tests, and benchmark suite passed. |
| C | Docker fallback documented. | pass | Journal records Docker command rejection and local fallback. |
| C | Behavior pins exercise the claimed behavior. | pass | Tests cover bad direct drafts, compiled bad specs, warnings, scoring, idempotency, source choice, and transcript aliases. |
| D | Deleted planned duplicate owner. | pass | Skeleton-local source-material enrichment was removed. |
| D | Tier B/persisted compatibility not touched. | pass | No migrations, runtime data-model, or persisted API compatibility edits. |
| D | No new compatibility shim or fallback branch. | pass | Source-material normalization is deterministic and validation-only warning is not a retry shim. |
| D | No broad new untyped domain contract. | pass | New source-material boundary is typed with dataclasses and existing Pydantic models. |
| E | Single source of truth improved. | pass | Production normalizer, validator, and benchmark scorer share `ai_builder_source_material.py`. |
| E | New file has a narrow domain concept. | pass | `ai_builder_source_material.py` owns Flow AI Builder source-material boundaries. |
| F | File split is responsibility-based. | pass | The split removes source-material mechanics from `ai_builder_step_skeleton.py`. |
| F | Prohibited generic file names avoided. | pass | New file name is domain-specific. |
| G | Restating comments avoided. | pass | Added only a topology docstring note explaining why JSON-boundary underlag matters. |
| H | Tests protect behavior. | pass | Tests assert runtime-visible bindings and scorer outcomes rather than private call order. |
| H | Internal mocks avoided. | pass | Tests construct draft/spec values and assert normalized specs. |
| I | Boundary discipline preserved. | pass | No ORM, HTTP, or Celery code touched. |
| J | No non-Flow code changed except docs. | pass | Source/test changes are Flow AI Builder and benchmark-scoring scoped. |
| J | Carry-forward risks recorded. | pass | Journal and reconciliation record Docker validation follow-up and live-export fixture policy. |

Final gate: GREEN.

## Validation

| Command | Result |
|---|---|
| `cd backend && uv run ruff check <11.6b touched source and test files>` | Passed. |
| `cd backend && uv run pyright <11.6b touched source and test files>` | Passed: `0 errors, 0 warnings, 0 informations`. |
| `cd backend && uv run pytest tests/unittests/flows/ai_builder/test_ai_builder_create_dataflow.py tests/unittests/flows/ai_builder/test_ai_builder_create_compiler.py tests/unittests/flows/ai_builder/test_ai_builder_step_transition_policy.py tests/unittests/flows/ai_builder/test_ai_builder_validator.py tests/unittests/flows/ai_builder/test_ai_builder_primary_input_fields.py tests/unittests/flows/ai_builder/test_ai_builder_form_field_lifecycle.py tests/unittests/flows/ai_builder/test_ai_builder_runtime_input_fields.py tests/integration/flows/ai_builder/benchmark/test_manual_api_scoring.py -q` | Passed: `211 passed`, existing warnings only. |
| `cd backend && uv run pytest tests/unittests/flows/ai_builder/test_ai_builder_step_skeleton.py tests/unittests/flows/ai_builder/test_ai_builder_proposal_processor.py::test_outline_audio_to_docx_returns_plan_without_self_correction tests/unittests/flows/ai_builder/test_ai_builder_materialization_bridge.py -q` | Passed: `63 passed`, existing warning only. |
| `cd backend && uv run pytest tests/integration/flows/ai_builder/benchmark -q` | Passed: `107 passed`, existing warnings only. |

## Risks

| Risk | Mitigation |
|---|---|
| Docker validation did not run in this tool environment. | Local validation passed; journal records a Docker rerun carry-forward. |
| Future source-material patterns may need richer source selection. | Current owner prefers primary flow-input source material and has tests; add another typed rule only with a concrete second pattern. |
| Long transcripts can increase step prompt size. | Injection is limited to document artifact JSON-boundary steps that demonstrably need source grounding. |

## Carry-Forward

| Item | Owner |
|---|---|
| Re-run the same validation in Docker where Docker commands are not approval-blocked. | Next implementation operator |
| Promote any additional live source-material failure into a draft/spec/scoring fixture before changing prompts. | Batch 11 reliability |
