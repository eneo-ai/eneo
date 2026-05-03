# Batch 11.2c Retrospective - Slot Resolver Provider Eval Harness

## TL;DR

1. Slice 11.2c adds a local provider-eval harness for the frozen slot resolver
   corpus without making live provider calls in normal tests.
2. The deterministic corpus test and provider harness now share one scoring
   owner, including `unknown` match semantics.
3. The gated metric is explicit: per-slot LLM-resolvable score on
   provider-success cases.
4. No live target is claimed in this environment because provider model and
   tenant env vars are not configured.
5. Focused tests, broad AI Builder unit tests, Pyright, Ruff, import contracts,
   diff check, dry-run, live-config guard, and Claude implementation review
   validation passed.

## Scope

Implemented:

- `slot_resolver_scoring.py` for shared per-slot scoring, corpus hashing, and
  keyword/runtime agreement summaries
- `slot_resolver_provider_eval.py` with deterministic dry-run and explicit
  `--live` provider mode
- deterministic tests for score semantics, config validation, redaction,
  fake-provider success, fake-provider error, and scorecard serialization
- reuse of the shared scoring helper in `test_slot_resolver_corpus.py`
- validation cleanup needed by the broadened AI Builder unit-test gate

Not implemented:

- live provider run against the full 80-case corpus
- keyword-prior deletion
- production telemetry changes
- runtime feature flags or model-selection policy changes

## Checklist

| Check | Result | Notes |
|---|---|---|
| Plan adherence | pass | Implemented the green 11.2c harness plan. |
| Claude peer loop | pass | Plan verification and implementation review reached `GREEN_LIGHT: yes`, minimum score `8/10`. |
| Canonical owner respected | pass | Corpus remains in `cases.py`; scoring lives in one benchmark scoring module. |
| Parallel path avoided | pass | Harness calls `build_runtime_planning_state()` rather than creating another runtime resolver. |
| Typed contracts | pass | Scorecards and case entries are dataclasses with explicit schema version and target metric. |
| Comment hygiene | pass | Comments explain scorecard/cache/environment constraints; no session/tooling comments were added to source/tests. |
| Behavior tests | pass | Tests cover scoring, redaction, config guardrails, fake provider paths, and serialized score shape. |
| Broader suite | pass | `tests/unittests/flows/ai_builder` passed with host WeasyPrint-dependent PDF tests skipped. |

## Validation

| Command | Result |
|---|---|
| `cd backend && uv run pytest tests/integration/flows/ai_builder/benchmark/test_slot_resolver_provider_eval.py tests/integration/flows/ai_builder/benchmark/test_slot_resolver_corpus.py tests/unittests/flows/ai_builder/test_ai_builder_server_actions.py::test_server_builds_confirm_requirements_checkpoint_after_commit -q` | Passed: `15 passed`, 16 existing warnings. |
| `cd backend && uv run pytest tests/unittests/flows/ai_builder -q` | Passed: `1735 passed, 4 skipped`, 12 existing warnings. |
| `cd backend && uv run pyright <11.2c touched Python files>` | Passed: `0 errors, 0 warnings, 0 informations`. |
| `cd backend && uv run ruff check <11.2c touched Python files>` | Passed. |
| `cd backend && uv run ruff format --check <11.2c touched Python files>` | Passed: `7 files already formatted`. |
| `cd backend && uv run lint-imports --no-cache` | Passed: 3 contracts kept, 0 broken. |
| `git diff --check -- <11.2c touched paths>` | Passed. |
| Dry-run CLI | Passed; generated ignored local scorecard with `live=false`, `target_claimable=false`, and 80 cases. |
| Live CLI without provider config | Failed as expected with exit code `2` before provider calls. |
| Source/test added-line slop grep | Passed with no matches. |

## Claude Implementation Review

| Item | Result |
|---|---|
| Artifact | `.codex/artifacts/claude-peer-loop-batch-11-2c-slot-resolver-provider-eval-implementation-20260503T055655Z.md` |
| Verdict | `green` |
| Green light | `yes` |
| Minimum score | `8` |

Final verification artifact:

| Item | Result |
|---|---|
| Artifact | `.codex/artifacts/claude-peer-loop-batch-11-2c-slot-resolver-provider-eval-final-verification-20260503T060427Z.md` |
| Verdict | `green` |
| Green light | `yes` |
| Minimum score | `9` |

Accepted polish:

| Finding | Resolution |
|---|---|
| Summary assertion was too weak. | Assert the exact Swedish committed summary. |
| Cache-hit status needed its conservative target-claim reason made explicit. | Added a why-comment in `_provider_status()`. |
| Prompt-redaction coverage was too phrase-specific. | Assert case scorecards have no `prompt` key. |

## Carry-Forward

| Item | Owner slice |
|---|---|
| Run the live provider command with real model and tenant env vars before claiming the `>= 0.85` target. | 11.2 provider eval follow-up |
| Use the keyword/runtime agreement breakdown to decide keyword-prior deletion. | Later 11.2 follow-up |
| Harden cache behavior if the harness is ever called repeatedly in-process rather than as a fresh CLI. | Future eval harness cleanup |

## Risk

The harness is local and opt-in. It cannot prove live resolver accuracy until a
real provider fixture is configured. That is intentional: committing a dry-run
harness is safer than pretending a target was met without provider evidence.

## Confidence

High for the harness and deterministic tests. Medium for live-provider quality
until the configured local model run is executed and a redacted scorecard is
recorded.
