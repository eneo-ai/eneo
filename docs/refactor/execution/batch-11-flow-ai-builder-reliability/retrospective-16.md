# Retrospective 16 — Local Manual API Smoke Harness

## TL;DR

1. The slice turns the 11.5d underlag/runtime-field fix into a repeatable local
   measurement path.
2. Claude rejected the first plan because it created a parallel scripts/YAML
   harness and preserved a literal local API key.
3. The final implementation reuses the existing AI Builder benchmark owner,
   typed reliability corpus, and dataclass scorecard pattern.
4. Deterministic scoring now covers audio and document source-material
   boundaries, legitimate secondary runtime fields, and metadata-only JSON
   losing source underlag.
5. The harness is dry-run safe by default; live API evaluation remains opt-in
   through `ENEO_LOCAL_*` variables and records redacted failure status.

## What Changed

| Area | Change |
|---|---|
| Benchmark owner | Added manual API scenario metadata to `backend/tests/integration/flows/ai_builder/benchmark/cases.py`. |
| Shared eval support | Added `eval_support.py` and moved slot resolver scorecard serialization/redaction to it. |
| Scoring | Added deterministic underlag/runtime-field/chain scoring in `manual_api_scoring.py`; primary upload fields derive from `FlowInputType`, and section/source-grounding checks use schema/template structure. |
| Harness | Added `manual_api_eval.py` with dry-run scorecards, live env gating, OpenAPI operation-id validation, SSE parsing, model provenance, redacted IDs, unsupported-scenario filtering, redacted failure status, and output writing. |
| Tests | Added focused scoring/eval tests plus preserved slot resolver provider eval coverage. |
| Docs | Updated the runbook, plan, PRD wording, `.gitignore`, and manual-eval results storage policy. |

## Claude Reconciliation

| Finding | Resolution |
|---|---|
| Parallel `backend/scripts/manual_eval` path would create future drift. | Reused the existing `benchmark` owner. |
| `prompts.yaml` would duplicate prompt text. | Reused `RELIABILITY_CORPUS_CASES` manual-runbook entries. |
| JSON Schema duplicated dataclass scorecard shape. | Dataclasses are the scorecard contract. |
| Literal local key in docs violated redaction policy. | Removed it and documented `ENEO_LOCAL_API_KEY`. |
| Underlag/runtime-field booleans were subjective. | Added deterministic predicates and bad/good tests. |
| SSE and endpoint drift were underspecified. | Added SSE parser tests and OpenAPI operation-id validation. |
| Implementation review found audio-only and live-path gaps. | Generalized source-material boundaries beyond audio, added per-case secondary runtime fields, live MockTransport coverage, model provenance, and unmeasured `None` scorecard states. |

## Validation

| Command | Result |
|---|---|
| `cd backend && uv run pytest tests/integration/flows/ai_builder/benchmark/test_manual_api_eval.py -q` | Passed: `13 passed`, 16 existing warnings. |
| `cd backend && uv run pytest tests/integration/flows/ai_builder/benchmark/test_manual_api_scoring.py -q` | Passed: `4 passed`, 16 existing warnings. |
| `cd backend && uv run pytest tests/integration/flows/ai_builder/benchmark -q` | Passed: `106 passed`, 16 existing warnings. |
| `cd backend && uv run ruff check tests/integration/flows/ai_builder/benchmark/eval_support.py tests/integration/flows/ai_builder/benchmark/slot_resolver_provider_eval.py tests/integration/flows/ai_builder/benchmark/cases.py tests/integration/flows/ai_builder/benchmark/manual_api_scoring.py tests/integration/flows/ai_builder/benchmark/manual_api_eval.py tests/integration/flows/ai_builder/benchmark/test_manual_api_eval.py tests/integration/flows/ai_builder/benchmark/test_manual_api_scoring.py` | Passed. |
| `cd backend && uv run ruff format --check tests/integration/flows/ai_builder/benchmark/eval_support.py tests/integration/flows/ai_builder/benchmark/slot_resolver_provider_eval.py tests/integration/flows/ai_builder/benchmark/cases.py tests/integration/flows/ai_builder/benchmark/manual_api_scoring.py tests/integration/flows/ai_builder/benchmark/manual_api_eval.py tests/integration/flows/ai_builder/benchmark/test_manual_api_eval.py tests/integration/flows/ai_builder/benchmark/test_manual_api_scoring.py` | Passed. |
| `cd backend && uv run pyright tests/integration/flows/ai_builder/benchmark/eval_support.py tests/integration/flows/ai_builder/benchmark/slot_resolver_provider_eval.py tests/integration/flows/ai_builder/benchmark/cases.py tests/integration/flows/ai_builder/benchmark/manual_api_scoring.py tests/integration/flows/ai_builder/benchmark/manual_api_eval.py tests/integration/flows/ai_builder/benchmark/test_manual_api_eval.py tests/integration/flows/ai_builder/benchmark/test_manual_api_scoring.py` | Passed: `0 errors`. |

## Risks

| Risk | Mitigation |
|---|---|
| Dry-run scorecards can be mistaken for live quality results. | Scorecards carry `live=false` and `openapi_validation_status=skipped_dry_run`; docs say dry-run does not claim quality. |
| Content-changing revision scenarios are not supported by the current `/plans/{plan_id}/revise` API. | Scenarios are represented but marked unsupported until the API grows a real content revision path. |
| SSE parsing can drift as planner events evolve. | Parser records unknown event names and tests terminal `done`, errors, multiline data, and comments. |
| Scorecard version drift can invalidate comparisons. | Runbook now defines `scorecard_schema_version` and `derivation_rules_version` precedence. |
| Fake live transport can diverge from real local API shape. | Live mode validates OpenAPI operation ids; first real local run should promote any API-shape drift into this harness. |

## Carry-Forward

| Item | Owner |
|---|---|
| Run a live local before/after scorecard set once `ENEO_LOCAL_API_KEY` is set outside git. | Manual eval operator |
| Add executed-run evidence/artifact scoring when a slice explicitly validates applied Flow output quality. | Future manual eval execution slice |
| Promote any live failure into the reliability corpus, scorer fixture, or golden test before the related slice commits. | Implementation agent |
