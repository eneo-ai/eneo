# Batch 11.2c Claude Reconciliation - Slot Resolver Provider Eval Harness

## TL;DR

1. Claude rejected the first 11.2c plan because the gated metric, scoring
   semantics, tenant handling, client construction, and cache behavior were not
   pinned.
2. The revised plan made the per-slot LLM-resolvable score on provider-success
   cases the only gated metric.
3. The plan now extracts shared scoring, requires model and tenant id for live
   mode, uses bare LiteLLM through existing runtime config, and keeps live
   scorecards redacted.
4. Claude plan verification returned `GREEN_LIGHT: yes`, minimum score `8/10`.
5. Claude implementation review also returned green; Codex accepted the
   assertion, cache-status, and prompt-redaction polish.

## Iteration 1

| Item | Value |
|---|---|
| Artifact | `.codex/artifacts/claude-peer-loop-batch-11-2c-slot-resolver-provider-eval-plan-20260503T053808Z.md` |
| Verdict | `changes_required` |
| Green light | `no` |
| Minimum score | `6` |

Accepted findings:

| Finding | Resolution |
|---|---|
| The `>= 0.85` gate metric was ambiguous. | Gated metric is now per-slot LLM-resolvable score on provider-success cases. |
| Deterministic and provider scoring could drift. | Added `slot_resolver_scoring.py` and made the deterministic corpus test use it. |
| Tenant id handling was unspecified. | `ENEO_AI_BUILDER_SLOT_EVAL_TENANT_ID` is required for `--live` and excluded from scorecards. |
| LiteLLM client construction owner was undefined. | Harness uses bare `litellm` with `configure_litellm_runtime(litellm)`, not `TenantModelAdapter`. |
| Process-local classifier cache could skew repeated in-process runs. | Valid live scorecards are fresh CLI process artifacts; provider call count is a sanity counter. |
| Schema and corpus hash were vague. | Scorecard schema version and corpus hash inputs are pinned. |
| Provider failures could distort model accuracy. | Target claim requires zero provider errors and every case reaching provider-success. |
| Redaction list missed API base and tenant id. | Both are excluded; API base is represented only by hash. |
| Validation was too narrow. | Added the full AI Builder unit-test suite to validation. |

## Iteration 2

| Item | Value |
|---|---|
| Artifact | `.codex/artifacts/claude-peer-loop-batch-11-2c-slot-resolver-provider-eval-plan-verification-20260503T054232Z.md` |
| Verdict | `green` |
| Green light | `yes` |
| Minimum score | `8` |

Accepted non-blocking findings:

| Finding | Resolution |
|---|---|
| `.git/info/exclude` is local-only. | Verified repo `.gitignore` already excludes `.codex/*`; no patch needed. |
| Model conservatism should be visible separately from wrong values. | Agreement summaries include unresolved counts by slot name. |
| Schema bump policy needed additive-field convention. | Scorecard includes explicit additive/no-bump and rename/removal/semantic-change bump wording. |

## Iteration 3

| Item | Value |
|---|---|
| Artifact | `.codex/artifacts/claude-peer-loop-batch-11-2c-slot-resolver-provider-eval-implementation-20260503T055655Z.md` |
| Verdict | `green` |
| Green light | `yes` |
| Minimum score | `8` |

Accepted non-blocking findings:

| Finding | Resolution |
|---|---|
| The server-action summary assertion was too weak. | Replaced substring checks with the exact Swedish committed summary. |
| Cache-hit/no-call status was conservative but underexplained. | Added a why-comment: no provider call cannot claim a fresh live target. |
| Prompt-redaction coverage inspected a phrase, not the serialized schema. | Added a per-case assertion that scorecards omit the `prompt` field. |

## Iteration 4

| Item | Value |
|---|---|
| Artifact | `.codex/artifacts/claude-peer-loop-batch-11-2c-slot-resolver-provider-eval-final-verification-20260503T060427Z.md` |
| Verdict | `green` |
| Green light | `yes` |
| Minimum score | `9` |

Result:

No findings remained. Claude confirmed the three implementation-polish items
landed cleanly and that the slice is commit-ready.

## Remaining Disagreements

No blocking disagreement remains.

Claude suggested a dedicated `model_returned_unknown_count`; Codex implemented
the available runtime-level signal as `unresolved_count` because the current
runtime merge intentionally does not persist low-confidence or `unknown` model
slots. Capturing raw classifier diagnostics would require changing the runtime
API or running a parallel classifier path, which would weaken the slice's
single-source-of-truth goal.

## Confidence

High. The final plan review was green, implementation follows the accepted
plan, and remaining live-provider uncertainty is explicit carry-forward rather
than hidden as a passed target.
