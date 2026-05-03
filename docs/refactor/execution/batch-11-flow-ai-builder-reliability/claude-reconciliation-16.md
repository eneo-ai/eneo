# Claude Reconciliation 16 — Local Manual API Smoke Harness

## TL;DR

1. Claude blocked the first 11.6 plan because it created a parallel manual-eval
   harness and duplicated prompt/scorecard ownership.
2. The revised plan moved the harness into the existing AI Builder benchmark
   owner and removed the committed local API key.
3. Claude green-lit the revised plan with clarification-level follow-ups.
4. Claude's implementation review caught audio-only underlag scoring,
   runtime-field false positives, missing live model provenance, and an
   untested live HTTP path.
5. Final validation passed on benchmark tests, Ruff, format, Pyright, and an
   exact Claude green-light confirmation.

## Iterations

| Iteration | Artifact | Verdict | Green light | Minimum score | Notes |
|---:|---|---|---|---:|---|
| 1 | `.codex/artifacts/claude-peer-loop-batch-11-6-manual-api-smoke-harness-plan-20260503T123145Z.md` | `changes_required` | `no` | 4 | Rejected `backend/scripts/manual_eval`, `prompts.yaml`, JSON Schema scorecard duplication, literal API key, subjective underlag/runtime booleans, and undeclared SSE/OpenAPI ownership. |
| 2 | `.codex/artifacts/claude-peer-loop-batch-11-6-manual-api-smoke-harness-revised-plan-20260503T123747Z.md` | `green` | `yes` | 7 | Approved benchmark-owner plan; asked for fixture provenance, SSE parser ownership, operation-id enumeration, version precedence, and result storage policy. |
| 3 | `.codex/artifacts/claude-peer-loop-batch-11-6-manual-api-smoke-harness-implementation-review-20260503T125738Z.md` | `changes_required` | `no` | 5 | Blocked audio-only underlag scoring, all-optional-field rejection, missing live model identity, hand-maintained keyword checks, empty-scorecard false failures, and untested live HTTP mode. |
| 4 | `.codex/artifacts/claude-peer-loop-batch-11-6-manual-api-smoke-harness-final-implementation-20260503T131550Z.md` | `green` | `yes` | 8 | Verified all critical implementation findings were structurally fixed; script parser missed the Markdown-bold header. |
| 5 | `.codex/artifacts/claude-peer-loop-batch-11-6-manual-api-smoke-harness-final-green-confirmation-20260503T131704Z.md` | `green` | `yes` | 8 | Exact output-contract confirmation passed with `GREEN_LIGHT: yes`. |
| 6 | `.codex/artifacts/claude-peer-loop-batch-11-6-manual-api-smoke-harness-post-green-cleanup-20260503T132425Z.md` | `green` | `yes` | 8 | Verified post-green cleanup for exact case-id validation, provider-disambiguated model matching, and redacted live failure status. |

## Accepted Findings

| Claude finding | Codex resolution |
|---|---|
| Do not create a parallel scripts/YAML harness. | Harness lives in `backend/tests/integration/flows/ai_builder/benchmark/`. |
| Six prompt text values need one owner. | The harness references existing `RELIABILITY_CORPUS_CASES` manual-runbook entries. |
| JSON Schema duplicates dataclass scorecard state. | Frozen dataclasses and `scorecard_schema_version` own scorecard shape. |
| Literal local API key should not be committed. | Removed the key from current docs and documented `ENEO_LOCAL_API_KEY`. |
| The reported underlag failure needed a deterministic scorer test. | Added bad/good plan-shape tests for transcript underlag and runtime fields. |
| SSE parsing was non-trivial and ownerless. | Added parser in `manual_api_eval.py` and tests for multiline data, comments, error, and done events. |
| Endpoint snapshot could drift. | Added OpenAPI `operationId` validation lists for AI Builder and optional executed-run endpoints. |
| Scorecard and derivation versions needed precedence. | Runbook and plan now define comparison invalidation rules. |
| Underlag scoring remained audio-specific. | Generalized JSON-to-text source-material boundary scoring to any prior text-producing step. |
| Legitimate optional runtime fields would fail forever. | Added `expected_secondary_runtime_field_names` to the typed reliability corpus case. |
| Live mode lacked model provenance and HTTP-path tests. | Fetches `SessionModelsResponse`, records redacted model id/name/provider, and covers the API path with `httpx.MockTransport`. |
| Unsupported revise/edit scenarios polluted default output. | Filters unsupported scenarios by default and adds `--include-unsupported`. |
| Empty scorecards asserted false typed failures. | Uses `None` for unmeasured derived fields and gates typed checks accordingly. |
| Case-id drift and failure observability needed tightening. | Added exact `MANUAL_API_EVAL_CASE_IDS` validation and redacted `live_call_error` class names. |

## Disagreements

No material disagreements. Claude preferred a captured live envelope for the bad
fixture. No committed full envelope exists for the user's debug export, so Codex
used a minimal synthesized `PlannerPlanEnvelope.spec` fixture and documented its
provenance against the 11.5d journal failure modes.

## Validation Evidence

| Command | Result |
|---|---|
| `uv run pytest tests/integration/flows/ai_builder/benchmark/test_manual_api_eval.py -q` | Passed: `13 passed`, 16 existing warnings. |
| `uv run pytest tests/integration/flows/ai_builder/benchmark/test_manual_api_scoring.py -q` | Passed: `4 passed`, 16 existing warnings. |
| `uv run pytest tests/integration/flows/ai_builder/benchmark -q` | Passed: `106 passed`, 16 existing warnings. |
| `uv run ruff check <11.6 touched benchmark files>` | Passed. |
| `uv run ruff format --check <11.6 touched benchmark files>` | Passed. |
| `uv run pyright <11.6 touched benchmark files>` | Passed: `0 errors`. |
