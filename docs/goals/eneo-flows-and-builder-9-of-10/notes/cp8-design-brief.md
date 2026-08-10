# CP8 design brief — frozen definitions for the release instrument

CP8 was SPLIT into three slices by concern. An implementer must not
invent the definitions below; they are frozen and peer-adjudicated.
Execution order and dependencies are owned by `master-program.md`;
this file owns the CP8 slice DEFINITIONS only.

## CP8a — Separate instrument from product — LANDED `0228f0e1d`

Harness exit depends ONLY on acquisition validity, evaluated over EVERY
SELECTED OBSERVATION (not only `required` cases): receipt completeness,
identity, evidence integrity, provider disposition, and two
non-configurable exact-zero invariants keyed on `observation_status` —
`execution_failure_observation_count == 0` and
`invalid_evidence_observation_count == 0`.

Deleted: both configurable corpus thresholds and `ReleaseThresholds`.
`max_required_quality_failures` counted PRODUCT expectation failures
and is gone outright; its count survives only as a non-authoritative
diagnostic. Renamed `ReleaseGate` → `AcquisitionContract` (corpus key
`acquisition_contract`) so CP8b owns the words "release gate"; the
cases-file schema version advanced to 7 for that shape change.

An `error_terminated` observation (journey outcome `builder_error` /
`provider_outcome_unknown`) is a scoreable PRODUCT outcome, never an
acquisition fault — it deliberately has no provenance to validate.

## CP8b — The release-gate evaluator (the 14 rows) — NEXT SLICE

Depends on CP8a. Three owners, no new path:

1. `scripts/ai_builder_release_gate.py` (NEW, pure domain): the 14 row
   specifications and ALL verdict arithmetic. No I/O, no CLI.
2. `scripts/ai_builder_receipt.py` (NEW, shared): the receipt loader
   and acquisition validation, used by BOTH harness and comparator —
   this is what makes the comparator loader fail-closed instead of
   silently skipping malformed rows
   (`ai_builder_battle_compare.py:54-76`).
3. `scripts/ai_builder_battle_compare.py`: a `release-verdict` mode —
   CLI, rendering, exit codes only.

### Frozen definitions (do not invent alternatives)

- N = 5 repetitions; a receipt with any other repetition count for a
  manifest case is INVALID, not scored.
- Populations: eligible = `outcome_class` not
  `clarification_stop_intended`; behaviour = all; supported = committed
  to a matrix row.
- Point estimate is ATTEMPT-level (successes/attempts); repetition
  disagreement is NEVER resolved by voting.
- Interval: Wilson on n = distinct cases in that population, with
  `centre = (p + z^2/2n)/(1 + z^2/n)` and
  `margin = z*sqrt(p(1-p)/n + z^2/4n^2)/(1 + z^2/n)`, z = 1.96, clamped
  to [0,1]. `>=` rows test the LOWER bound, `<=` rows the UPPER —
  direction-aware, because testing the lower bound on a `<=` metric
  false-passes.
- Verdicts: PASS when point estimate AND the relevant bound both meet
  the threshold; INCONCLUSIVE when only the point does; FAIL otherwise.
  Release requires zero FAIL and zero INCONCLUSIVE among GATING rows.
  Row 5 is NON-GATING under the user's TRAJECTORY decision but is
  computed identically; the trajectory COMPLETION verdict is a separate
  reported outcome (row 5 PASS AND conformance-instability within its
  ceiling).
- Instability rows are DISTINCT: mixed-accepted ceiling
  `floor(0.03 x eligible cases)`; mixed-first-pass ceiling
  `floor(0.10 x eligible cases)`. Both derive from the receipt
  manifest — never from a prose constant.
- Row 11 classification is canonical, not ad hoc: semantic vs
  architecture is read from the invariant registry
  (`ai_builder_critic_invariants.py`) at import time, never a hardcoded
  id list. Count occurrences over supported observations in
  `failure_summary.failure_codes` plus every
  `journey.plan_outcome.attempt_failure_ladder[*].failure_codes`;
  architecture ids are reported separately, never inside row 11.
- Repair numerator: `journey.plan_outcome.repair_attempts` only.
- Cost rows: nearest-rank p95 = `sorted[ceil(0.95n)-1]`.
- Missing data is fail-closed; every ceiling derives from the manifest.
- Row 14 (machine-verifiable, revision-bound): the gate asserts that
  every supported matrix row has >= 1 manifest case, that no
  observation is committed to a row outside the matrix, AND that the
  receipt's source revision matches the revision recorded in the
  matrix-state file the `json_to_text_summary` REMOVAL slice writes.
  The source-side invariant (branch absent, tuple rejects) is a PRODUCT
  test in that removal slice — the gate never reads source.
- Built-in `--feasibility`: computes every gate under a PERFECT run for
  the receipt's manifest and FAILS if any gate is unpassable (the
  broken-gate rule — a gate needing more cases than exist is a plan
  defect, not a product failure).

### Tests (proportional)

Perfect run -> GO exit 0; adverse clustering (all-pass / all-fail split)
-> row 1 INCONCLUSIVE, exit non-zero; provider marker -> invalid,
nothing scored; repair budget boundary (met -> PASS, one over -> FAIL);
malformed row -> invalid (the fail-closed regression); row 14 violation
-> FAIL; feasibility audit rejects an unpassable gate.

## CP8c — Operator slot re-measurement (last, separable)

`replacements.json` beside the receipt:
`{case_id, repetition, reason, original_bundle_sha256,
replacement_bundle_sha256}`.

Overlay order: replacements are applied AFTER load and BEFORE
validation, replacing exactly one observation each. A replacement must
match case contract hash, source revision, model identity AND
repetition index; duplicates for one slot are invalid; the set is
capped at 5% of observations; the gate reports the count and FAILS
above the cap.

Tests: valid overlay merged and counted; mismatched revision rejected;
over-cap fails.
