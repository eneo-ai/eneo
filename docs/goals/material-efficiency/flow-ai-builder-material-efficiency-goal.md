# Flow AI Builder Material Efficiency and Binding Quality

## Objective

Improve Flow AI Builder output quality and maintainability by making material routing explicit, efficient, testable, and easy to review.

The goal is not only to make generated flows valid. The goal is to make generated flows *smart*: they should use targeted `input_bindings.question`, `uses_previous_fields`, `uses_previous_outputs`, `uses_form_fields`, JSON input/output contracts, form fields/inmatningsfält, and input/output types in a way that minimizes context bloat and preserves all required material.

A working-but-dumb flow is a defect.

## Goal Kind

`open_ended`

## Current Tranche

This tranche focuses on material efficiency and binding quality after the first production-hardening PRD work.

The first safe implementation slice should prove, with a deterministic red test, whether a compiled report composer/finalizer can still lose the original transcript/source material or earlier structured JSON section outputs when crossing JSON boundaries.

The current leading hypothesis is that `ai_builder_source_material.py` is the canonical owner because `CompiledSourceMaterialBoundary` and `SourceMaterialBindingStatus` already feed both normalization and linting. Do not assume this is true. Scout/Judge must verify it against current code and tests before Worker changes implementation.

This tranche should continue through successive safe verified slices until one of these is true:

1. The known source-material/binding-efficiency failure is reproduced and fixed with tests.
2. Evidence proves the leading hypothesis is wrong and the board records the new canonical owner.
3. A blocker prevents further local non-destructive work.

## Non-Negotiable Constraints

- Stay on the current branch.
- Commit only at clean verified phase boundaries.
- Do not push, rebase, create PRs, switch branches, or rewrite unrelated history.
- Do not commit local eval outputs, curl logs, scorecards, temporary scripts, API keys, screenshots, `.env` files, caches, or unrelated dirty files.
- Do not implement a broad new material-planning abstraction unless a red test proves existing canonical owners cannot be extended.
- Do not introduce `StepMaterialPlan`, `StepBindingPlan`, or another parallel source of truth before proving existing owners cannot carry the responsibility.
- Do not use `all_previous_steps` as a band-aid for lost source material.
- Do not change model-tier policy as a proxy for missing material routing.
- Do not mix source-material routing, form-field lifecycle redesign, and debug export schema changes into one unreviewable PR.
- Keep scenarios domain-neutral and avoid municipality-only vocabulary blocked by the golden coverage matrix.
- Use TDD: red test first, implementation second, verification third.
- Keep strict Pyright/type checking green or document pre-existing unrelated failures with evidence.
- Prefer typed pure helpers, canonical owners, and symmetrical normalizer/linter behavior.
- Comments must explain concise invariants and boundary behavior, not restate obvious code.

## Material Routing Principles

- `input_bindings.question` is the material the model actually sees. If it is present, it is complete; it does not automatically augment implicit `input_source`.
- Instructions control behavior, style, output format, and constraints. Values that affect final content should usually be routed through underlag/bindings.
- Form fields/inmatningsfält that affect content should be declared once at flow scope and consumed explicitly by the relevant steps.
- Structured JSON underlag scales by referenced fields. Text-body underlag scales by body size and number of sources.
- `all_previous_steps` is valid for true compare/aggregate intent, but it is a poor default for source loss or sectioned report composition.
- A flow is efficient only if the effective material can be inspected and bounded.

## Required Metrics For This Tranche

At least in deterministic tests, add or compute:

- Binding byte size: `len(input_bindings.question.encode("utf-8"))`.
- Fan-in width: number of distinct prior steps referenced by a composer/finalizer.
- Structured field count: number of `output.structured.*` references.
- Whole-output reference count: whole `output.text` / whole `output.structured` references.
- Source duplication count: number of downstream references to primary source text.
- `all_previous_steps` count.

Start with diagnostics and per-golden assertions. Do not invent global limits until enough behavior is measured.

## Evaluation Requirement

If localhost/API is available, run deterministic regression tests first, then live smoke tests and live AI Builder evaluations. Live eval is not the primary regression fence; it is a qualitative signal used to find new failure modes that should later become deterministic goldens.

Use environment variables for API credentials. Do not paste or commit API keys, curl logs, signed URLs, SSE dumps, uploaded test files, generated artifacts, or raw scorecards.

```bash
export ENEO_LOCAL_API_BASE=http://localhost:8123
export ENEO_LOCAL_API_KEY="<paste local key in shell only>"
export ENEO_LIVE_EVAL_DIR=/tmp/material-efficiency-live-eval/$(date +%Y%m%d-%H%M%S)
mkdir -p "$ENEO_LIVE_EVAL_DIR"
```

Use the local runner as the primary live-eval entry point:

```bash
python docs/goals/material-efficiency/run_flow_ai_builder_live_eval.py --smoke
python docs/goals/material-efficiency/run_flow_ai_builder_live_eval.py --all --runs 3 --apply
python docs/goals/material-efficiency/run_flow_ai_builder_live_eval.py --all --include-supplemental --runs 3 --apply
```

The runner reads the canonical space list from `docs/goals/material-efficiency/flow-ai-builder-material-efficiency-state.yaml`, stores raw API responses under `/tmp/material-efficiency-live-eval/...` by default, and keeps API credentials in process memory only. Manual curl is still useful for debugging a failed endpoint, but the runner should be the repeatable path used for baseline and after-change comparisons.

Run V1-V5 and C1-C5 from `docs/goals/material-efficiency/flow-ai-builder-material-efficiency-codex-prompt.txt` across the five spaces listed in `checks.live_eval.spaces` in `docs/goals/material-efficiency/flow-ai-builder-material-efficiency-state.yaml`, round-robin.

Run the supplemental edit-path, HTTP, and restraint probes when API and fixtures allow. If any live probe is skipped, record the exact blocker.

Known HTTP caveat: Flow runtime supports `http_get` / `http_post`, but the AI Builder-facing enum exposes only pass-through, transcribe-only, and template-fill output modes (`backend/src/intric/flows/enums.py:74`) and the create materializer rejects `http_post` (`backend/src/intric/flows/ai_builder/ai_builder_materialization_bridge.py:122`). Treat HTTP probes as capability-discovery checks unless that authoring path is verified or implemented.

Minimum live smoke commands:

```bash
curl -sS -X GET \
  "$ENEO_LOCAL_API_BASE/api/v1/flows/ai-builder/sessions" \
  -H "accept: application/json" \
  -H "X-API-Key: $ENEO_LOCAL_API_KEY" \
  | tee "$ENEO_LIVE_EVAL_DIR/sessions.json" | jq .

SPACE_ID=2b4a43a7-b543-46f0-8d55-913e5b7ebb14
curl -sS -X GET \
  "$ENEO_LOCAL_API_BASE/api/v1/flows/?space_id=$SPACE_ID&limit=50&offset=0" \
  -H "accept: application/json" \
  -H "X-API-Key: $ENEO_LOCAL_API_KEY" \
  | tee "$ENEO_LIVE_EVAL_DIR/flows-$SPACE_ID.json" | jq .
```

Live evaluation must exercise the full create path where safe:

1. Create an AI Builder session: `POST /api/v1/flows/ai-builder/sessions`.
2. Send the case prompt: `POST /api/v1/flows/ai-builder/sessions/{session_id}/messages`.
3. Inspect session/plans: `GET /api/v1/flows/ai-builder/sessions/{session_id}`, `GET /api/v1/flows/ai-builder/sessions/{session_id}/plans`, `GET /api/v1/flows/ai-builder/plans/{plan_id}`.
4. Approve and apply only safe plans: `POST /api/v1/flows/ai-builder/plans/{plan_id}/approve`, `POST /api/v1/flows/ai-builder/plans/{plan_id}/apply`.
5. Inspect created flows: `GET /api/v1/flows/{id}/`, `GET /api/v1/flows/{id}/graph/`, `GET /api/v1/flows/{id}/run-contract/`, `GET /api/v1/flows/{id}/input-policy/`.
6. Inspect template surfaces for template-fill cases: `GET /api/v1/flows/{id}/template-files/`, `POST /api/v1/flows/{id}/template-files/`, `GET /api/v1/flows/{id}/template-inspect/`, `POST /api/v1/flows/{id}/template-files/{file_id}/signed-url/`.
7. Publish and run only when the run contract can be satisfied with local fixtures: `POST /api/v1/flows/{id}/publish/`, `POST /api/v1/flows/{id}/files/`, `POST /api/v1/flows/{id}/steps/{step_id}/runtime-files/`, `POST /api/v1/flows/{id}/runs/`.
8. Debug output quality: `GET /api/v1/flows/{id}/runs/{run_id}/`, `GET /api/v1/flows/{id}/runs/{run_id}/steps/`, `GET /api/v1/flows/{id}/runs/{run_id}/evidence/`, `GET /api/v1/flows/{id}/runs/{run_id}/evidence/export?format=json&detail=redacted&reason=material_efficiency_eval`.

The live eval summary must compare quality and efficiency, not only whether a plan was created. For each case, score:

- clarification restraint
- minimal viable topology
- source preservation
- targeted material routing
- form-field lifecycle
- terminal mode fit
- context efficiency
- output usefulness

Record the baseline score, after-change score, binding byte size, fan-in width, structured field count, whole-output reference count, source duplication count, and `all_previous_steps` count. A result is better only if it improves score and/or reduces unnecessary material cost without losing required evidence.

Run each case 3 times when API time allows. Report median score per axis and flag a case as flaky when any axis differs by 2 points across runs. If only one run is possible, label the result as single-run smoke rather than a stable baseline. Keep redacted cross-run baseline summaries under `/tmp/material-efficiency-live-eval/baselines/<commit-or-label>/summary.json` unless a reviewer explicitly requests a sanitized repo artifact.

The live runner emits raw per-run records, manual score fields, and median/flake rollups after scores are filled. It does not compute binding/fan-in metrics automatically; use the saved plan/flow JSON plus deterministic tests for material-efficiency metrics.

## Stop Rule

Stop only when a Judge/PM audit proves the current tranche outcome is complete or all remaining local non-destructive work is blocked.

Do not stop after planning, discovery, or Judge selection if a safe Worker task can be activated.

Do not stop after one verified Worker slice if there are safe local follow-up slices that materially improve output quality, token efficiency, or maintainability.

If credentials, local services, owner input, destructive operations, or production access block one slice, mark that exact slice blocked with a receipt and continue any other safe local work.

## Canonical Board

Machine truth lives at:

`docs/goals/material-efficiency/flow-ai-builder-material-efficiency-state.yaml`

If this charter and `docs/goals/material-efficiency/flow-ai-builder-material-efficiency-state.yaml` disagree, the state file wins for task status, active task, receipts, verification freshness, and completion truth.

## Run Command

```text
/goal Follow docs/goals/material-efficiency/flow-ai-builder-material-efficiency-goal.md through successive safe verified implementation phases on the current branch. Commit after each completed verified phase, but do not push. Do not stop after planning unless blocked. Focus on material efficiency, source-material routing, structured fan-in coverage, form-field material usage, and measurable context cost. Use Claude peer loop before Worker activation and before each commit gate.
```

## PM Loop

On every `/goal` continuation:

1. Read this charter.
2. Read `docs/goals/material-efficiency/flow-ai-builder-material-efficiency-state.yaml`.
3. Work only on the active board task.
4. Assign Scout, Judge, Worker, or PM according to the task.
5. Write a compact task receipt.
6. Update the board.
7. Run Claude peer loop before activating a risky Worker and before commit gates.
8. Treat a slice audit as a checkpoint, not completion, unless it proves the tranche outcome is complete.
9. Finish only with a Judge/PM audit receipt mapping receipts and verification back to the material-efficiency outcome.
