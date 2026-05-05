TL;DR:
1. Current branch already contains partial source-material hardening for DOCX/PDF artifact flows.
2. The remaining reproduced gap is text-terminal report composition across JSON boundaries: no source-material boundary is detected, no normalization happens, and no lint warning fires.
3. `ai_builder_source_material.py` remains the best canonical owner for boundary/status semantics because both the normalizer and linter consume its iterator and status function.
4. The first Worker slice should be a narrow TDD change around text-terminal boundaries and material-efficiency metrics, not a new planning abstraction.
5. Verification should start with focused unit tests, then strict Pyright/Ruff on changed files, then optional live eval.

## Dirty Baseline

Current `git status --short` before Scout work:

| Path | Status | Classification | Action |
|---|---:|---|---|
| `scripts/run_codex_review.sh` | modified | pre-existing unrelated work | Do not touch or commit in this tranche unless explicitly authorized. |
| `PRODUCT.md` | untracked | pre-existing unrelated work | Do not touch or commit. |
| `docs/goals/material-efficiency/` | untracked | current goal docs/eval runner | PM may update state/notes; implementation commits must exclude eval outputs and caches. |
| `docs/refactor/flow-ai-builder-material-efficiency-review-handoff.md` | untracked | current goal input | Read-only evidence unless user asks docs refinement. |
| `docs/refactor/goals.md` | untracked | pre-existing docs | Do not touch or commit unless part of docs phase. |
| `docs/refactor/new/` | untracked | current goal inputs | Read-only evidence. |
| `docs/refactor/runtime-hang-and-builder-rootcause.md` | untracked | pre-existing docs | Do not touch or commit. |
| `flow_ai_builder_prd.md` | untracked | pre-existing docs | Do not touch or commit. |
| `flow_ai_builder_review.md` | untracked | pre-existing docs | Do not touch or commit. |
| `utvecklingssamtal.mp3` | untracked | local fixture/media | Never commit. |

Scout commands run:

```bash
git status --short
uv run --directory backend pytest tests/unittests/flows/ai_builder/test_ai_builder_step_transition_policy.py -q
uv run --directory backend pytest tests/unittests/flows/ai_builder/test_ai_builder_create_compiler.py -q -k 'source_underlag or audio_report_section_extractors or direct_audio_docx_bad_shape or targeted_underlag'
uv run --directory backend python - <<'PY'
# constructed text-terminal boundary probe
PY
```

Results:

- `test_ai_builder_step_transition_policy.py`: 17 passed.
- targeted `test_ai_builder_create_compiler.py`: 9 passed, 98 deselected.
- Text-terminal probe reproduced missing boundary: `boundaries []`, `changes []`, final bindings `None`, only JSON-contract warnings.

## Current Source Evidence

| Concept | Evidence | Finding |
|---|---|---|
| Explicit underlag is complete effective input | `backend/src/intric/flows/ai_builder/ai_builder_new_step_compiler.py:104-166` | `compile_input_bindings` documents that `input_bindings.question` replaces implicit `input_source`, so missing material in a binding is a runtime-visible defect. |
| Create drafts are normalized before compile | `backend/src/intric/flows/ai_builder/ai_builder_create_compiler.py:22-40` | `compile_create_draft` calls `normalize_create_draft_mechanics`, so create-mode source-material behavior should be tested through compilation. |
| Create-mode source-material normalization is artifact gated | `backend/src/intric/flows/ai_builder/ai_builder_source_material.py:64-91`, `backend/src/intric/flows/ai_builder/ai_builder_source_material.py:310-315` | Source material refs are only added when a draft/spec returns a DOCX/PDF artifact. |
| Compiled boundary iterator is artifact gated | `backend/src/intric/flows/ai_builder/ai_builder_source_material.py:94-120` | Text-terminal report composers crossing JSON boundaries are invisible to the normalizer and linter. |
| Boundary status owns completion semantics | `backend/src/intric/flows/ai_builder/ai_builder_source_material.py:123-148` | The status function is the shared source of truth for complete/partial/missing underlag. |
| Normalizer consumes the boundary iterator | `backend/src/intric/flows/ai_builder/ai_builder_step_transition_policy.py:174-220` | Behavior changes in the iterator/status automatically reach normalization. |
| Linter consumes the same boundary iterator | `backend/src/intric/flows/ai_builder/ai_builder_validation_quality.py:270-287` | Symmetry already exists if the same iterator/status remains canonical. |
| Apply/preparation paths normalize compiled specs | `backend/src/intric/flows/ai_builder/ai_builder_plan_lifecycle.py:107-112`, `backend/src/intric/flows/ai_builder/ai_builder_compiled_spec_preparation.py:49-56` | Fixes in compiled-spec normalization should protect applied create/edit plans, not only direct compile tests. |
| Targeted text composer rewrite exists | `backend/src/intric/flows/ai_builder/ai_builder_create_dataflow.py:237-365` | This owns create-time field fan-in for final text composers, but it does not own compiled-spec lint/normalize symmetry. |

## Reproduced Gap

Constructed shape:

1. `step_a`: `flow_input audio -> text`, transcribe-only.
2. `step_b`: `previous_step text -> json`.
3. `step_c`: `previous_step json -> json`.
4. `step_d`: `previous_step json -> text` final report.

Observed:

```text
boundaries []
changes []
final bindings None
warnings [('json_output_no_contract', 'step_b'), ('json_output_no_contract', 'step_c')]
```

Why this matters:

- The text finalizer sees only the immediately previous JSON by implicit chaining.
- The original transcript is not included in `input_bindings.question`.
- Earlier structured outputs are also not explicitly represented unless create-time targeted binding happened earlier.
- The linter gives no source-material warning because the iterator exits before inspecting text-terminal shapes.

Confidence: high for the compiled-spec normalizer/linter gap; medium for create-mode live incidence because create-mode already has additional targeted composer rewrites.

## Canonical Owner Recommendation

Use `backend/src/intric/flows/ai_builder/ai_builder_source_material.py` as the canonical owner for the first slice.

Rationale:

- `CompiledSourceMaterialBoundary` and `SourceMaterialBindingStatus` already define the domain concept at `ai_builder_source_material.py:48-61`.
- The normalizer uses this owner at `ai_builder_step_transition_policy.py:174-220`.
- The linter uses this owner at `ai_builder_validation_quality.py:270-287`.
- Changing only `ai_builder_create_dataflow.py` would miss edit-mode and compiled-spec preparation paths.
- Changing only `ai_builder_new_step_compiler.py` would not lint or repair plans generated by edit/tool schemas or persisted compiled specs.

Do not add `StepMaterialPlan`, `StepBindingPlan`, or a new material planner for this slice. Existing owner boundaries are sufficient for the reproduced failure.

## Candidate Red Tests

First Worker should add tests before production changes:

1. Positive red case in `test_ai_builder_step_transition_policy.py`:
   - text-terminal composer/finalizer after audio source and two JSON steps should receive source text and immediate structured output.
   - assert `normalized.steps[-1].input_bindings["question"]` contains `{{ step_a.output.text }}` and `{{ step_c.output.structured }}`.
   - assert no `all_previous_steps` rewrite is introduced.

2. Linter/normalizer symmetry in `test_ai_builder_validator.py`:
   - same unbound text-terminal shape should warn with `source_material_boundary_missing_underlag`.
   - normalized shape should not warn.

3. Negative no-op case in `test_ai_builder_step_transition_policy.py` or `test_ai_builder_validator.py`:
   - pure JSON-output chain with no text/DOCX/PDF composer remains untouched and does not warn.

4. Material metrics test:
   - helper computes binding byte size, fan-in width, structured field count, whole-output refs, source duplication count, and `all_previous_steps` count for the golden.
   - start as deterministic assertions for the new golden; do not add global limits.

## Metrics Candidate

Prefer a small typed helper near the existing source-material owner or tests first:

| Metric | Deterministic source |
|---|---|
| Binding byte size | `len(question.encode("utf-8"))` |
| Fan-in width | distinct prior step references parsed from `input_bindings.question` |
| Structured field count | parsed step refs whose tail starts with `output.structured.` |
| Whole-output reference count | parsed step refs whose tail is exactly `output.text` or `output.structured` |
| Source duplication count | number of references to primary source text step's `output.text` |
| `all_previous_steps` count | count of steps with `input_source == InputSource.ALL_PREVIOUS_STEPS` |

Avoid substring-only production metrics if a parser is already available. Reuse `template_reference_analyzer.analyze_template`.

## Verification Commands

Targeted deterministic commands:

```bash
uv run --directory backend pytest tests/unittests/flows/ai_builder/test_ai_builder_step_transition_policy.py -q
uv run --directory backend pytest tests/unittests/flows/ai_builder/test_ai_builder_validator.py -q -k source_material
uv run --directory backend pytest tests/unittests/flows/ai_builder/test_ai_builder_create_compiler.py -q -k 'source_underlag or audio_report_section_extractors or direct_audio_docx_bad_shape or targeted_underlag'
uv run --directory backend pytest tests/integration/flows/ai_builder/benchmark/test_manual_api_scoring.py -q
```

Type/lint/format candidates:

```bash
uv run --directory backend pyright src/intric/flows/ai_builder/ai_builder_source_material.py src/intric/flows/ai_builder/ai_builder_step_transition_policy.py src/intric/flows/ai_builder/ai_builder_validation_quality.py
uv run --directory backend ruff check src/intric/flows/ai_builder/ai_builder_source_material.py src/intric/flows/ai_builder/ai_builder_step_transition_policy.py src/intric/flows/ai_builder/ai_builder_validation_quality.py tests/unittests/flows/ai_builder/test_ai_builder_step_transition_policy.py tests/unittests/flows/ai_builder/test_ai_builder_validator.py
uv run --directory backend ruff format --check src/intric/flows/ai_builder/ai_builder_source_material.py src/intric/flows/ai_builder/ai_builder_step_transition_policy.py src/intric/flows/ai_builder/ai_builder_validation_quality.py tests/unittests/flows/ai_builder/test_ai_builder_step_transition_policy.py tests/unittests/flows/ai_builder/test_ai_builder_validator.py
```

Live eval after deterministic green and API available:

```bash
export ENEO_LOCAL_API_BASE=http://localhost:8123
export ENEO_LOCAL_API_KEY="<shell only>"
export ENEO_LIVE_EVAL_DIR=/tmp/material-efficiency-live-eval/$(date +%Y%m%d-%H%M%S)
mkdir -p "$ENEO_LIVE_EVAL_DIR"
python docs/goals/material-efficiency/run_flow_ai_builder_live_eval.py --smoke
python docs/goals/material-efficiency/run_flow_ai_builder_live_eval.py --all --runs 3 --apply
```

## Recommended First Worker Slice

Objective:

Add a deterministic red golden for text-terminal source-material loss across JSON boundaries, implement the smallest `ai_builder_source_material.py` boundary/status change to make normalizer and linter symmetric for text/DOCX/PDF report composers, and add per-golden material-efficiency metrics.

Allowed files:

- `backend/src/intric/flows/ai_builder/ai_builder_source_material.py`
- `backend/tests/unittests/flows/ai_builder/test_ai_builder_step_transition_policy.py`
- `backend/tests/unittests/flows/ai_builder/test_ai_builder_validator.py`
- optional only if metrics require shared production helper: `backend/src/intric/flows/ai_builder/ai_builder_validation_quality.py`

Verify:

- `uv run --directory backend pytest tests/unittests/flows/ai_builder/test_ai_builder_step_transition_policy.py -q`
- `uv run --directory backend pytest tests/unittests/flows/ai_builder/test_ai_builder_validator.py -q -k source_material`
- `uv run --directory backend pytest tests/integration/flows/ai_builder/benchmark/test_manual_api_scoring.py -q`
- `uv run --directory backend pyright src/intric/flows/ai_builder/ai_builder_source_material.py`
- `uv run --directory backend ruff check src/intric/flows/ai_builder/ai_builder_source_material.py tests/unittests/flows/ai_builder/test_ai_builder_step_transition_policy.py tests/unittests/flows/ai_builder/test_ai_builder_validator.py`
- `uv run --directory backend ruff format --check src/intric/flows/ai_builder/ai_builder_source_material.py tests/unittests/flows/ai_builder/test_ai_builder_step_transition_policy.py tests/unittests/flows/ai_builder/test_ai_builder_validator.py`

Stop if:

- The red test cannot fail before production changes.
- Fix requires blanket `all_previous_steps`.
- Fix requires a new material-planning abstraction.
- Text-terminal normalization creates false positives for pure JSON-output flows.
- Normalizer and linter cannot use the same boundary/status semantics.
