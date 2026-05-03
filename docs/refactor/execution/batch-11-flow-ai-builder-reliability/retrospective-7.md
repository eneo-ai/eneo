# Batch 11.2a Retrospective - Swedish Slot Resolver Corpus

## TL;DR

1. Slice 11.2a freezes the Swedish slot resolver corpus before introducing the
   model-backed resolver.
2. The corpus stays under the existing AI Builder benchmark case owner instead
   of creating another fixture owner.
3. Legal expected values are derived from the question catalog, so slot labels
   cannot drift from the follow-up question contract.
4. The current keyword-prior baseline is measured through the real
   planning-state builder at `229/276 = 0.830`; this is not the final 11.2
   resolver target.
5. Focused validation, import boundaries, anti-slippage, and Claude
   verification are green.

## Scope

Implemented:

- `model` slot source and `low` slot confidence support for the future
  resolver output contract
- `legal_slot_values()` from the question catalog as the canonical legal-value
  lookup
- an 80-case Swedish, domain-neutral slot resolver corpus
- coverage tags for audio, document, transcript, text, upload, structured
  extraction, comparison, API-shaped JSON, multi-step, and ambiguous prompts
- corpus integrity tests and keyword-prior baseline measurement through
  `build_planning_state_from_conversation`

Not implemented:

- model-backed resolver calls
- resolver prompt material
- follow-up question behavior for model `unknown` slots
- keyword prior deletion
- resolver telemetry and latency logging

## Checklist

| Check | Result | Notes |
|---|---|---|
| Plan adherence | pass | Implemented the approved 11.2a corpus-first split. |
| Claude plan loop | pass | The revised plan reached `GREEN_LIGHT: yes`. |
| Claude implementation loop | pass | Implementation review reached `GREEN_LIGHT: yes`, minimum score `8/10`. |
| Canonical owner respected | pass | Corpus data stays in `benchmark/cases.py`; legal values come from `question_catalog.py`. |
| Parallel path avoided | pass | No new resolver schema owner or prompt-only projector was added. |
| Typed contracts | pass | Slot source/confidence literals, coverage enum, corpus dataclass, and catalog-derived value checks are typed. |
| Comment hygiene | pass | New source/test comments explain two non-obvious corpus decisions; no tooling or plan comments were added to source. |
| Behavior tests | pass | Tests validate corpus shape, slot vocabulary, legal values, domain neutrality, tag distribution, and baseline scoring. |
| Broader suite | n/a | This slice changes corpus contracts and focused tests only. |

## Validation

| Command | Result |
|---|---|
| `cd backend && uv run pytest tests/unittests/flows/ai_builder/test_planning_state.py tests/unittests/flows/ai_builder/test_question_catalog.py tests/integration/flows/ai_builder/benchmark/test_slot_resolver_corpus.py -q` | Passed: `99 passed`, warnings were existing deprecations or expected serializer warnings from unrelated tests. |
| `cd backend && uv run pyright src/intric/flows/ai_builder/planning_state.py src/intric/flows/ai_builder/question_catalog.py tests/integration/flows/ai_builder/benchmark/cases.py tests/integration/flows/ai_builder/benchmark/test_slot_resolver_corpus.py tests/unittests/flows/ai_builder/test_planning_state.py tests/unittests/flows/ai_builder/test_question_catalog.py` | Passed: `0 errors, 0 warnings, 0 informations`. |
| `cd backend && uv run ruff check src/intric/flows/ai_builder/planning_state.py src/intric/flows/ai_builder/question_catalog.py tests/integration/flows/ai_builder/benchmark/cases.py tests/integration/flows/ai_builder/benchmark/test_slot_resolver_corpus.py tests/unittests/flows/ai_builder/test_planning_state.py tests/unittests/flows/ai_builder/test_question_catalog.py` | Passed. |
| `cd backend && uv run ruff format --check src/intric/flows/ai_builder/planning_state.py src/intric/flows/ai_builder/question_catalog.py tests/integration/flows/ai_builder/benchmark/cases.py tests/integration/flows/ai_builder/benchmark/test_slot_resolver_corpus.py tests/unittests/flows/ai_builder/test_planning_state.py tests/unittests/flows/ai_builder/test_question_catalog.py` | Passed: `6 files already formatted`. |
| `cd backend && uv run lint-imports --no-cache` | Passed: 3 contracts kept, 0 broken. |
| `git diff --check -- <11.2a touched paths>` | Passed. |
| `./scripts/gate-local/anti_slippage.sh --worktree` | Passed: `anti-slippage: worktree clean`. |
| Added-line slop grep for `deprecated`, `legacy`, source-control/session/tooling comments, and TODO/FIXME markers | Passed with no matches. |

## Carry-Forward

| Item | Owner slice |
|---|---|
| Model-backed resolver result model and parser that writes `ResolvedSlot(source="model")`. | 11.2b |
| Follow-up question behavior for ambiguous or low-confidence architecture slots. | 11.2b |
| Resolver accuracy gate of at least 85% on the frozen 80-case corpus. | 11.2b |
| Keyword-prior deletion criterion and disagreement measurement. | 11.2b |
| Resolver telemetry for model, tenant, confidence, capability path, and latency. | 11.2b |
| JSONB round-trip coverage for `source="model"` and `confidence="low"` once the resolver writes persisted state. | 11.2b |

## Risk

`backend/tests/integration/flows/ai_builder/benchmark/cases.py` is now a large
fixture owner. That is acceptable for this slice because the corpus must be
frozen, explicit, and reviewable next to the existing AI Builder benchmark
cases. Future additions should not keep growing this file without checking
whether a narrower typed corpus module has earned a separate responsibility.

The keyword-prior floor is deliberately lower than the observed baseline
(`0.70` floor versus `0.830` observed) because it protects against accidental
drift without turning the pre-model baseline into the target. The 11.2 resolver
quality gate remains at least `0.85` on this corpus.

## Confidence

High for the corpus and contract slice. The corpus labels are catalog-backed,
domain-neutrality and coverage are tested, and the current baseline is measured
through the real planning-state builder. Confidence in final resolver behavior
is intentionally not claimed until 11.2b wires and measures the model-backed
resolver.
