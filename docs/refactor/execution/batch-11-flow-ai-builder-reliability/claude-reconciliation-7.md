# Batch 11.2a Claude Reconciliation - Swedish Slot Resolver Corpus

## TL;DR

1. Claude rejected the first plan because it introduced a parallel resolver
   contract and measured a prompt-only keyword projector.
2. The accepted plan evolves `ResolvedSlot` in place, derives legal values from
   the existing question catalog, and measures the baseline through
   `build_planning_state_from_conversation`.
3. The corpus is frozen under the existing benchmark case owner with
   domain-neutrality and coverage-distribution tests.
4. Implementation verification reached `GREEN_LIGHT: yes`, minimum score
   `8/10`.
5. Non-blocking findings were resolved with two intent comments and journal
   carry-forward notes, not source behavior changes.

## Iteration 1

| Item | Value |
|---|---|
| Artifact | `.codex/artifacts/claude-peer-loop-batch-11-2a-swedish-slot-resolver-plan-20260503T040339Z.md` |
| Verdict | `changes_required` |
| Green light | `no` |
| Minimum score | `5` |

Accepted findings:

| Finding | Resolution |
|---|---|
| A new `SlotResolverDecision` contract would duplicate `ResolvedSlot`. | Evolved `planning_state.py` by adding `source="model"` and `confidence="low"`. |
| A prompt-only keyword projector would measure the wrong path. | The baseline test calls `build_planning_state_from_conversation`. |
| A separate resolver taxonomy would create a third label owner. | Expected slot names stay tied to `KNOWN_REQUIREMENT_SLOT_NAMES`, and values are derived from `QUESTION_CATALOG`. |
| Corpus prompts needed domain-neutrality enforcement. | Added a denylist test for municipal-domain terms that should not leak into this corpus. |
| Audit/log fields were speculative before a model call exists. | Deferred telemetry fields to 11.2b. |

Rejected findings:

| Finding | Reason |
|---|---|
| None. | All blocking findings improved the plan and were accepted. |

## Iteration 2

| Item | Value |
|---|---|
| Artifact | `.codex/artifacts/claude-peer-loop-batch-11-2a-swedish-slot-resolver-plan-verification-20260503T040804Z.md` |
| Verdict | `green` |
| Green light | `yes` |
| Minimum score | `8` |

Accepted non-blocking findings:

| Finding | Resolution |
|---|---|
| Keep 11.2a as a corpus and existing-contract slice. | Model resolver wiring, telemetry, and follow-up behavior stay in 11.2b. |
| Derive legal slot values from the question catalog instead of duplicating enum lists. | Added `legal_slot_values()` and unit tests. |
| The corpus should have per-tag minimum coverage, not only total count. | Added `MINIMUM_CASES_PER_COVERAGE_TAG` and full-tag coverage tests. |
| The baseline must not claim the final 85% resolver target. | Recorded exact observed baseline separately from the final target. |

## Iteration 3

| Item | Value |
|---|---|
| Artifact | `.codex/artifacts/claude-peer-loop-batch-11-2a-swedish-slot-resolver-implementation-20260503T042153Z.md` |
| Verdict | `green` |
| Green light | `yes` |
| Minimum score | `8` |

Accepted findings:

| Finding | Resolution |
|---|---|
| The baseline has a wide cushion and needs the exact observed score recorded. | Journal and retrospective record `229/276 = 0.830` with a `0.70` floor. |
| Unknown-slot scoring needed to explain omitted keyword-prior slots. | Added a short test comment explaining that the current path omits unresolved slots while the future resolver may emit `unknown`. |
| The `HTTP_API` tag could be confused with FCM `http_post`. | Added a short enum comment clarifying that this tag means API-shaped JSON output. |
| JSONB round-trip coverage is missing for `source="model"` and `confidence="low"`. | Deferred to 11.2b, where the resolver writes persisted state. |
| Helper defaulting `ui_language="sv"` is acceptable for this slice. | Kept the helper narrow because this is a Swedish corpus. |

## Remaining Disagreements

No blocking disagreement remains.

The corpus increases `benchmark/cases.py` substantially. Claude accepted this
as data-only and reviewable in the current owner. The carry-forward note is that
future corpus growth should re-evaluate whether a domain-specific corpus module
has earned a separate responsibility.

## Confidence

High. The final peer review was green, the accepted findings were implemented
or explicitly deferred to 11.2b, and the validation suite passed after the
implementation comments were tightened.
