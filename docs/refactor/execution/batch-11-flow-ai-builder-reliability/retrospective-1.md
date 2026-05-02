# Retrospective 1 — Reliability Corpus

## TL;DR

1. Slice 11.0a adds the first Batch 11 reliability gate without changing AI Builder behavior.
2. The reliability corpus lives in the existing AI Builder benchmark case owner instead of a parallel JSON fixture.
3. The reported Swedish audio-to-DOCX failure is pinned by content and an explicit `audio -> text / transcribe_only` step.
4. The corpus validates against Flow enums, FCM tuple legality, chain legality, canonical slot names, and behavioral-risk coverage.
5. Validation passed and Claude implementation review returned `GREEN_LIGHT: yes` with minimum score `8`.

## Outcome

Implemented the reliability corpus with:

- frozen case/value-object dataclasses in `backend/tests/integration/flows/ai_builder/benchmark/cases.py`
- closed `CorpusSource`, `DomainCoupling`, and `BehavioralRisk` enums
- seven Swedish reliability cases: one reported failure plus six manual-runbook prompts
- FCM-backed integrity tests in `backend/tests/integration/flows/ai_builder/benchmark/test_reliability_corpus.py`
- Batch 11 plan, journal, PRD, manual-runbook, and implementation-order docs aligned to the reliability-corpus owner

## Checklist

| Section | Result | Evidence |
|---|---|---|
| A. Plan adherence | pass | 11.0a implemented only reliability corpus data/tests/docs after Claude plan green. |
| B. Acceptance criteria | pass | `test_reliability_corpus.py` checks count, IDs, slots, FCM tuples/chains, reported failure, enum coverage, behavioral risks, and domain coupling. |
| C. Behavior pins and validation | pass | Focused benchmark/corpus tests passed: `75 passed`. Pyright, Ruff, import-linter, diff-check, and anti-slippage passed. |
| D. Pre-production deletion discipline | pass | No compatibility, deprecated, legacy, fallback, or dual-path behavior added. No `Any`, `dict[str, Any]`, broad `except`, HTTP, Celery, or runtime changes. |
| E. Single source of truth | pass | Prompt reliability data was added to the existing AI Builder benchmark case owner instead of `tests/data` JSON. |
| F. File splits and naming | pass | One new test file named for the reliability corpus; no generic helper/common/shared modules. |
| G. Comments and readability | pass | New docstrings explain corpus ownership and drift prevention; no restating code comments were added. |
| H. Test quality | pass | Tests protect corpus behavior and FCM legality; no mocks or private-call assertions. |
| I. Boundary discipline | pass | No ORM, HTTP, Celery, or Pydantic domain-boundary changes. |
| J. Scope and risk | pass | Touched only AI Builder benchmark tests/docs plus the Batch 11 implementation-order entry. |

Final gate: GREEN, 0 fails.

## Validation

| Command | Result |
|---|---|
| `cd backend && uv run pytest tests/integration/flows/ai_builder/benchmark/test_reliability_corpus.py tests/integration/flows/ai_builder/benchmark/test_baseline_benchmark.py -q` | Passed: `75 passed`; unrelated deprecation warnings only. |
| `cd backend && uv run pytest tests/integration/flows/ai_builder -q` | Passed: `79 passed, 20 deselected`; unrelated deprecation warnings only. |
| `cd backend && uv run pyright tests/integration/flows/ai_builder/benchmark/cases.py tests/integration/flows/ai_builder/benchmark/test_reliability_corpus.py` | Passed. |
| `cd backend && uv run ruff check tests/integration/flows/ai_builder/benchmark/cases.py tests/integration/flows/ai_builder/benchmark/test_reliability_corpus.py` | Passed. |
| `cd backend && uv run ruff format --check tests/integration/flows/ai_builder/benchmark/cases.py tests/integration/flows/ai_builder/benchmark/test_reliability_corpus.py` | Passed. |
| `cd backend && uv run lint-imports --no-cache` | Passed: 3 contracts kept, 0 broken. |
| `git diff --check -- backend/tests/integration/flows/ai_builder/benchmark/cases.py backend/tests/integration/flows/ai_builder/benchmark/test_reliability_corpus.py docs/refactor/execution/batch-11-flow-ai-builder-reliability docs/refactor/prd/PRD-011-flow-ai-builder-reliability.md docs/refactor/implementation-order.md` | Passed. |
| `./scripts/gate-local/anti_slippage.sh --worktree` | Passed. |

## Carry Forward

| Item | Owner | Next action |
|---|---|---|
| First-attempt compile/repair measurements | 11.0b | Add measurement hooks and write baseline numbers before 11.1 behavior changes. |
| Slot-value vocabulary | 11.2 | Replace or validate free-form `ExpectedSlot.value` strings against the typed resolver vocabulary once it exists. |
| Swedish resolver corpus owner | 11.2 | Reuse the benchmark case owner decision unless a better canonical owner is justified. |
| Manual smoke-suite failures | All Batch 11 slices | Promote new manual failures into the reliability corpus, resolver corpus, or goldens in the same slice. |

## Confidence

High. The slice is data/test-only, the corpus is tied to canonical Flow contracts, and validation passed locally.

## Claude Loop

| Iteration | Artifact | Verdict |
|---|---|---|
| Plan review | `.codex/artifacts/claude-peer-loop-batch-11-production-failure-corpus-plan-20260502T232903Z.md` | `changes_required`, `GREEN_LIGHT: no` |
| Plan verification | `.codex/artifacts/claude-peer-loop-batch-11-reliability-corpus-plan-verification-20260502T233406Z.md` | `green`, `GREEN_LIGHT: yes` |
| Implementation review | `.codex/artifacts/claude-peer-loop-batch-11-reliability-corpus-implementation-20260502T234807Z.md` | `green`, `GREEN_LIGHT: yes` |
