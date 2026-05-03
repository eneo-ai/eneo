# Batch 11.0b Retrospective — Proposal Reliability Measurement

## TL;DR

1. Slice 11.0b adds proposal measurement hooks without changing proposal
   behavior.
2. `ProposalTurnTelemetry` now records first-attempt outcome and repair reasons
   for create, edit, and missing-tool forced retry paths.
3. `ai_builder_telemetry.py` remains the single owner of the persisted
   `planner_telemetry` dict shape.
4. Claude implementation review found and cleared an eager success-recording
   blocker before commit.
5. Deterministic baselines are recorded; live LLM first-attempt pass rate remains
   a manual-eval-runbook responsibility.
6. The slice is ready to feed 11.1 skeleton materialization.

## Scope

Implemented:

- proposal turn telemetry extraction and rename
- optional proposal fields on canonical planner telemetry
- typed internal and sanitized proposal failure taxonomies
- structured nested proposal log payloads
- create/edit/missing-tool proposal measurement recording
- focused unit tests and deterministic baseline documentation

Not implemented:

- live LLM manual scorecards
- public API telemetry fields
- frontend/generated-client changes
- proposal behavior, compiler, validator, or repair behavior changes
- skeleton materialization

## Checklist

| Check | Result | Notes |
|---|---|---|
| Plan adherence | pass | Implemented 11.0b measurement only. |
| Claude plan loop | pass | Iteration 3 reached `GREEN_LIGHT: yes`, minimum score `9`. |
| Claude implementation loop | pass | Iteration 4 found the eager success-recording blocker; iteration 5 reached `GREEN_LIGHT: yes`, minimum score `8.5`. |
| Canonical owner respected | pass | `build_planner_telemetry` owns telemetry dict fields. |
| No parallel compatibility path | pass | Renamed `ProposalUsageTracker` without alias. |
| Typed contracts | pass | `ToolProcessingFailureKind`, `ProposalFailureKind`, and typed repair callback added. |
| Comment hygiene | pass | New comments/docstrings explain log/taxonomy decisions rather than control flow. |
| Behavior unchanged | pass | Tests cover existing repair and proposal paths. |
| Baseline recorded | pass | Journal records deterministic counts and deferred live LLM rate. |

## Validation

| Command | Result |
|---|---|
| `cd backend && uv run pytest tests/unittests/flows/ai_builder/test_ai_builder_proposal_telemetry.py tests/unittests/flows/ai_builder/test_ai_builder_proposal_processor.py tests/unittests/flows/ai_builder/test_ai_builder_proposal_repair.py -q` | Passed: `58 passed`; pre-existing `python_multipart` warning only. |
| `cd backend && uv run pytest tests/integration/flows/ai_builder/benchmark/test_reliability_corpus.py tests/integration/flows/ai_builder/benchmark/test_baseline_benchmark.py -q` | Passed: `75 passed`; pre-existing deprecation warnings only. |
| `cd backend && uv run pytest tests/integration/flows/ai_builder -q` | Passed: `79 passed, 20 deselected`; pre-existing deprecation warnings only. |
| `cd backend && uv run pyright src/intric/flows/ai_builder/ai_builder_telemetry.py src/intric/flows/ai_builder/ai_builder_proposal_telemetry.py src/intric/flows/ai_builder/ai_builder_proposal_processor.py src/intric/flows/ai_builder/ai_builder_proposal_repair.py src/intric/flows/ai_builder/ai_builder_edit_proposal.py tests/unittests/flows/ai_builder/test_ai_builder_proposal_telemetry.py tests/unittests/flows/ai_builder/test_ai_builder_proposal_processor.py` | Passed: `0 errors, 0 warnings, 0 informations`. |
| `cd backend && uv run ruff check src/intric/flows/ai_builder/ai_builder_telemetry.py src/intric/flows/ai_builder/ai_builder_proposal_telemetry.py src/intric/flows/ai_builder/ai_builder_proposal_processor.py src/intric/flows/ai_builder/ai_builder_proposal_repair.py src/intric/flows/ai_builder/ai_builder_edit_proposal.py tests/unittests/flows/ai_builder/test_ai_builder_proposal_telemetry.py tests/unittests/flows/ai_builder/test_ai_builder_proposal_processor.py` | Passed. |
| `cd backend && uv run ruff format --check src/intric/flows/ai_builder/ai_builder_telemetry.py src/intric/flows/ai_builder/ai_builder_proposal_telemetry.py src/intric/flows/ai_builder/ai_builder_proposal_processor.py src/intric/flows/ai_builder/ai_builder_proposal_repair.py src/intric/flows/ai_builder/ai_builder_edit_proposal.py tests/unittests/flows/ai_builder/test_ai_builder_proposal_telemetry.py tests/unittests/flows/ai_builder/test_ai_builder_proposal_processor.py` | Passed: `7 files already formatted`. |
| `cd backend && uv run lint-imports --no-cache` | Passed: 3 contracts kept, 0 broken. |
| `git diff --check -- <11.0b touched paths>` | Passed. |
| `cd backend && uv run python -m tests.integration.flows.ai_builder.benchmark.runner --diff` | Expected nonzero drift snapshot: 0 added, 0 removed, 10 changed cases. |

## Carry-Forward

| Item | Owner slice |
|---|---|
| Live LLM first-attempt success rate | Manual eval runbook before/after behavior slices |
| Skeleton materialization from committed architecture | 11.1 |
| Swedish typed slot resolver evals | 11.2 |
| Form-field and resource validation parity | 11.3 |
| Golden coverage matrix | 11.4 |
| Provider-aware structured outputs | 11.5 |

## Risk

The deterministic baseline proves telemetry hooks and static corpus integrity,
not real model quality. 11.1 must not treat these numbers as the live LLM pass
rate; the manual API runbook owns that surface.
