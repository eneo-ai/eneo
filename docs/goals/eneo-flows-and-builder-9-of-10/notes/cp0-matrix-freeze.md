# CP0 — Matrix freeze (analysis, evidence, and the gate inventory)

Executed 2026-08-10 against the clean checkpoint `342dc7ec9fc7` (suite
`ai-builder-api-battle-suite-20260810T110430`, `run_count=465`, 155 cases,
provider-reported token usage, `tracked_clean=true`). No product code
changed. This record owns the EVIDENCE and the GATE INVENTORY. It does not own
verdict semantics: pre-registration completes when CP8 lands, and CP8
blocks CP1–CP7 builder product work and candidate measurement (§3). The
runtime stream (L1a–L5) is unaffected and may proceed in parallel.

CP0 owns evidence and the gate inventory (§3); it does not own or ship
the release contract — **CP8 will own it; this record owns the inventory
CP8 must satisfy.** Packet scripts are
evidence only: if a script's output and this document disagree, that is a
review failure to be resolved explicitly — authority never transfers
silently to an untracked script.

## 0. Evidence packet (clone-local, hashed)

Raw evidence stays local (`.codex` is gitignored); this record is the
tracked conclusion. The packet holds **attribution evidence only** — the
statistics that kept drifting between prose and script were removed with
the release-contract scope (§3); CP8 owns that arithmetic in tracked code.

    container developz_devcontainer-eneo-1
    cd /workspace/.codex/artifacts/cp0-freeze-20260810
    /workspace/backend/.venv/bin/python cp0_archetype_ledger_v2.py  # row ledger
    python3 cp0_allcheck.py            # complete failing-check attribution
    python3 cp0_rows.py                # repair / error / critic-event counts
    python3 cp0_cost.py                # nearest-rank p95, three populations
    python3 cp0_receipt_validation.py  # canonical provider-marker scan
    python3 cp2_terminal_attribution.py
    sha256sum -c SHA256SUMS            # 10/10 OK

    manifest digest (pins the whole inventory):
    38d9ca33ff060ace3ca02b95c0dfb9e077007e50624012632a0f81bf1c45f38e  SHA256SUMS

Inputs: `clean_planning_states.jsonl` (1019 states, DB export),
`SUITE_IDENTITY.json` (467 files, a local integrity record of the consumed
corpus — not independently verifiable off this machine; CP8 verifies
corpus identity through the tooling's receipt contract). Source revision
`342dc7ec9fc7efcd3312c7436253e8ab26250f4b`.

**Ownership:** `master-program.md` owns execution; this record owns
evidence and the gate inventory; CP8 owns the executable release gate and
its statistics. Packet scripts are evidence only — a disagreement with
this document is a review failure, never a silent transfer of authority.

## 1. The archetype partition already exists in source

`_primary_pattern_id` (`ai_builder_architecture_derivation.py:186`) is an
ordered early-return cascade — **mutually exclusive by construction**. The
ledger confirms it: 0 of 465 observations matched more than one row. Row
identity = primary pattern id; `form_field_runtime_inputs` is an orthogonal
MODIFIER, never a row.

Row source of record = `journey.architecture.chosen_patterns` (the
architecture actually committed during the attempt). Re-derivation from the
final persisted snapshot disagreed on 34/465 (7.3%) and must never be the
row of record.

### Frozen matrix v1 — **11 source rows** (9 measured + 2 unmeasured)

| row id | n | first-pass | repair rate (of accepted) | builder errors |
|---|---|---|---|---|
| `document_to_structured_report` | 155 | 67.1% | 26.2% | 11 |
| `document_to_pdf_report` | 92 | 83.7% | 11.5% | 4 |
| `extract_structured_fields` | 48 | 91.7% | 6.4% | 0 |
| `audio_to_artifact_report` | 26 | 80.8% | 12.5% | 1 |
| `summarize_text` | 24 | 75.0% | 0.0% | 4 |
| `json_to_structured_payload` | 24 | 41.7% | 58.3% | 0 |
| `document_to_docx_template` | 20 | 35.0% | 50.0% | 6 |
| `text_to_artifact_report` | 3 | 100% | 0.0% | 0 |
| `json_to_artifact_report` | 2 | 100% | 0.0% | 0 |
| `json_to_text_summary` | **0 — UNMEASURED** | — | — | — |
| `audio_transcription` | **0 — UNMEASURED** | — | — | — |

The two unmeasured branches are real cascade outcomes with no corpus
coverage. They are frozen as rows and flagged: **no slice may claim to
cover them, and no release verdict may generalize to them.** Adding cases
for them is a corpus decision (§6).

## 2. Buckets and metric populations (corrected)

The previous draft called every no-commit observation "FALLBACK". That was
wrong twice over:

- **There is no free semantic fallback in create.** Verified:
  `ai_builder_proposal_submission.py:422` raises
  `architecture_materialization_failed` when
  `planning_state.architecture_commit is None`. A create proposal cannot be
  submitted without a committed architecture. The program's standing claim
  (from the Pass 31 verdict) that "the free semantic proposal path remains
  for genuinely novel shapes" is **false for create mode** and is deleted,
  not weakened. If such a path is wanted it must be designed deliberately.
- Calling no-commit "fallback" also made coverage circular (an attempt was
  "supported" only once it succeeded).

Corrected taxonomy — every one of the 465 observations lands in exactly one
bucket:

| bucket | n | meaning |
|---|---|---|
| committed to a matrix row | 394 | architecture committed; row assigned |
| UNCOMMITTED — intended clarification stop | 51 | correct behavior; the case contract expects a question |
| UNCOMMITTED — pre-commit failure | 20 | 19 stalls + 1 builder error; never reached commit |

- **Architecture-commit rate = 394/414 = 95.2%** of eligible attempts.
  This is NOT "supported-shape coverage" — it is the rate at which eligible
  attempts reach a commitment. Renamed accordingly.
- **Plan-production metrics** use the **414 eligible** attempts (465 − 51
  intended stops). Exclusion is legitimate: the harness requires an explicit
  case contract and a relevant question for that classification
  (`ai_builder_api_battle_test.py:5570`).
- **Overall behavior metrics** use **all 465**, because excluding intended
  stops wholesale hid a real defect: **3 of the 51 fail
  `first_question_relevance`, all three repetitions of
  `interview_input_crisis_overview`** — a stable clarification-quality
  failure. Intended stops therefore carry their own contract (§3).

## 3. What release must gate — an inventory, not a frozen statistic

**Scope correction.** Earlier revisions of this record tried to freeze a
complete statistical release contract — estimator, intervals, verdict
semantics, corpus arithmetic. That was the wrong artifact for the job:
CP0 is analysis, and a statistical contract cannot be made
self-consistent in prose. Eleven review rounds demonstrated the failure
mode directly: each restatement drifted from the scripts that computed
it. **The statistical design is CP8's**, to be implemented once in the
tracked battle tooling (`backend/scripts/ai_builder_battle_compare.py`,
which already owns fail-closed receipt identity) with unit tests, one
arithmetic module, and no duplicated constants.

**Pre-registration completes when CP8 lands, not here.** CP8 is therefore
a HARD BARRIER: it is the first slice after the two user decisions, and
no behaviour-changing slice (CP1–CP7) and no candidate measurement may
run before it. Otherwise verdict semantics could still be chosen after
seeing product results, which is exactly what pre-registration exists to
prevent.

What CP0 freezes is the inventory below: WHAT must be gated, on WHICH
population, in WHICH direction, and WHY. Thresholds that are exact
counts are stated as product requirements and carry no statistical
method. Thresholds expressed as proportions are stated as targets, and
their interval method, verdict semantics and feasibility are CP8's to
specify and test.

| # | must be gated | population | direction | current | kind |
|---|---|---|---|---|---|
| 1 | accepted (plan produced) | eligible attempts | ≥ target 95% | 360/414 = 86.96% | proportion (CP8) |
| 2 | first-pass | eligible attempts | ≥ target 90% | 286/414 = 69.08% | proportion (CP8) |
| 3 | total repair attempts | eligible attempts | ≤ floor(0.05 × eligible) | 86 vs 20 at N=3 | **exact count** |
| 4 | product-attributable builder errors | eligible attempts | = 0 | 27 | **exact count** |
| 5 | expectation conformance | all observations | ≥ target 90% | 170/465 = 36.56% | proportion — **PENDING** (§6a) |
| 6 | stable product deaths | eligible cases | = 0 | 3 | **exact count** |
| 7 | stable non-acceptance (stall/limit) | eligible cases | = 0 | 5 | **exact count** |
| 8 | case instability: mixed accepted | eligible cases | ≤ 3 | 25 | **exact count** |
| 9 | case instability: mixed first-pass | eligible cases | ≤ 14 | 48 | **exact count** |
| 10 | clarification-question relevance | intended stops | = 0 failures | 3 | **exact count** |
| 11 | normal-path semantic critic firing events | committed supported-row attempts | = 0 | 23 events (4 IDs) | **exact count** |
| 12 | cost p95, eligible | eligible attempts | ≤8 calls / ≤39,000 tok / ≤50 s | 7 / 34,884 / 42.2 s | **exact (nearest-rank)** |
| 13 | cost p95, accepted | accepted attempts | ≤8 calls / ≤38,000 tok / ≤48 s | 7 / 34,032 / 40.8 s | **exact (nearest-rank)** |
| 14 | unmeasured branches resolved | matrix | = 0 unresolved | 2 | **exact count** |

Eleven of the fourteen are exact counts or exact percentiles: they need
no statistics at all, because a release run is a **census of its own
receipt**, not a sample of a population. Only rows 1, 2 and 5 are
proportions, and only they need CP8's interval design.

### Findings CP8 must honour (established here, with evidence)

1. **Audit best-case feasibility before freezing any threshold.** A gate
   a perfect product cannot pass is a broken gate, not a high bar. This
   is not hypothetical: expressing row 4 as `≤1% of attempts` is
   infeasible on this corpus — a flawless run still fails, and the
   proportion form would need a far larger corpus. Row 4 is therefore an
   exact zero count, which is both stricter and passable.
2. **Repetitions buy instability detection, not precision.** Outcomes
   are strongly clustered by case, so a release run's resolution is
   governed by the number of CASES, not attempts. N=5 is chosen for
   detection power (67% chance of catching a 20%-flaky case versus 49%
   at N=3).
3. **Any interval must be cluster-aware and must not be able to
   false-pass adverse clustering.** Worked counterexample for CP8's test
   suite: 136 of 138 cases succeeding in all five repetitions and 2
   failing in all five is 98.55% of attempts; a per-attempt or
   baseline-clustering treatment passes a 95% gate, while treating cases
   as the independent unit does not.
4. **Provider failures are not product failures.** Detect them by the
   canonical `error_details[*].details.provider_disposition` marker, never
   by error code — product paths also emit `planner_upstream_error`. A
   marked receipt must not be scored. CP8 must define bounded slot-level
   re-measurement (re-take only marked case/repetition slots, preserving
   manifest, revision, model and concurrency, under an explicit cap),
   because discarding an entire ~14M-token run for one provider fault is
   not viable when such faults occur 3–5 times per pass. It must never
   be an automatic product retry.
5. **Conformance consistency is not covered by rows 6–9**, which govern
   acceptance and first-pass only. Worked counterexample: every case
   first-passes while 31 of 155 fail conformance in one repetition of
   five — 744/775 = 96.00% of attempts, every listed row passing, yet
   20% of cases conformance-unstable. If §6a makes conformance a gate,
   CP8 must also gate its consistency.
6. **One arithmetic owner, no duplicated constants.** Every drift found
   in review came from a number restated in two places. The same rule
   applies to attribution: provider classification is owned solely by the
   canonical marker scan (`cp0_receipt_validation.py`), never by error-code
   substrings.

**The N=3 baseline is descriptive, never a gating receipt.** Applying
finding 4 to it (`cp0_receipt_validation.py`) finds 2 provider-marked
observations — `complex_meeting_audio_policy_pdf` r2 and
`attachment_pdf_report_granskat_beslutsunderlag` r3 — so under the rule
above it would be invalid for gating. That is expected: these numbers are
attribution evidence. The first gating receipt is the N=5 release run.

**Death taxonomy.** 3 stable product deaths (every repetition
`builder_error`): `declared_terminal_everyday_bygglovsremiss_text` and
`declared_terminal_everyday_enskilt_avlopp_text` → **CP2**;
`file_role_discrimination_runtime_input_sample_protokoll`, whose three
captures all terminate with `runtime_metadata_requires_form_fields`
→ **CP3** (`ai_builder_critic_invariants.py:375`). Separately, 5 stable
non-acceptance non-death cases (stall / interaction limit / unconfirmed).

## 4. Invariant disposition — all 31 assigned, none left unowned

Registry `CRITIC_INVARIANTS` (`ai_builder_critic_invariants.py:1823`).
Channel asymmetry (verified): in CREATE, architecture invariants are
HARD-FATAL (`enforce_architecture_critic_invariants` raises, not
model-repairable); semantic ones become repair feedback. In EDIT,
architecture is only feedback except the two `edit_topology` ones.

- **8 unreachable in create** (gated by `_is_create_context`, or by a helper
  that returns False when `flow is None`) → out of scope for create
  excellence, retained for edit: `pdf_terminal_output_alignment`,
  `docx_terminal_output_alignment`,
  `non_terminal_step_document_conversion_forbidden`,
  `non_terminal_step_template_fill_forbidden`,
  `standalone_audio_requires_transcription_step`,
  `json_input_rejects_all_previous_steps_source`,
  `multi_document_compare_requires_all_previous_steps`,
  `mixed_audio_doc_rejects_file_degradation`.
- **5 fire in 465 observations** — every one now has an owner:
  - `runtime_metadata_requires_form_fields` (4 terminal + 3 repair) → CP3
  - `rich_workflow_requires_form_fields` (3 + 2) → CP3
  - `named_result_obligations_must_survive` (2 + 6) → CP5 (demote to
    compiler postcondition)
  - `rich_workflow_requires_multiple_steps` (1 + 2) → **CP4 attribution**
    (it fires alongside JSON emission defects; attribute before deciding)
  - `checkpoint_intent_mismatch` (1, hard-fatal architecture) →
    **checkpoint/compiler attribution slice** (NOT CP2: its sole
    observation is a DOCX-template case, and the canonical projection
    lives in `ai_builder_create_compiler.py:370` while the critic
    compares compiled spec against checkpoint intents at
    `ai_builder_critic_invariants.py:175`)
- **18 never fired** → retained as postconditions. One checkpoint is not
  grounds to delete conservative guards; retention costs nothing because
  "zero normal-path hits" is a firing metric, not a registry count.

## 5. Tolerance-path dispositions

| path | ruling | rationale |
|---|---|---|
| `_CREATE_INTENT_ROOT_IGNORED_KEYS` (`ai_builder_proposal_intent.py:77`) | **REJECT** | The effective ignored set is **27 keys**, not 2 (it unions the step-only and backend-owned sets), so an entire misplaced step emitted at root vanishes with no log. Create-only; the strict hook has exactly one seam, `:325`, before `_normalize_create_intent_arguments`. |
| backend-owned step-key stripping (16 keys, `:505`) | **REJECT (14) / RE-SCOPE (2)** | 14 keys are backend-owned and unadvertised → reject. `uses_previous_fields`/`uses_previous_outputs` are declared on the shared `SemanticStepIntent` and legitimate in EDIT → they must be absent from the CREATE materialized schema rather than stripped. Same for `output_type`, silently accepted though the create schema omits it. |
| retired-key tolerance test (`test_ai_builder_tools.py:116`) | **DELETE with its owner** | Asserts the tolerance itself. The output side already rejects `reasoning`; only the input side tolerates it. |
| JSON-path array-index leniency (`ai_builder_json_schema_paths.py:13`) | **REJECT — own slice, CP6, release-critical** | Not a compat shim: a live authoring/runtime divergence. Runtime REJECTS what authoring accepts (`variable_resolver.py:373`), so the builder can ship a template that fails at execution. Highest blast radius (create + edit + scoped revision + assembly topology). |
| FCM one-bump deprecation promise (`flow_capability_manifest.py:12`) | **DELETE the sentence** | Documentation only: no field, no table, no branch, no test; `FCM_VERSION` is write-only. Rides the next slice touching that file. |

## 6. Two decisions this freeze cannot make alone

### 6a. Conformance: an optimistic projection, and a scope question

**Retraction.** The previous draft claimed 88.8% was a ceiling and that
≥90% was unreachable. That was wrong — it enumerated only hand-picked
families and left a long tail unattributed. The complete attribution
(`cp0_allcheck.py`, in the packet) covers **all 56 check families** across
the 295 non-pass observations.

**What the table below is, precisely.** It is an *optimistic
current-ledger projection*: it removes failure labels from the existing
observations and recounts. It does NOT generate a plan or re-evaluate
behavior, so it assumes no new failure appears when a fix lands. That
assumption is known to be generous — e.g. the 15 observations whose sole
failure is `plan_created` are stalls with no plan at all, and actually
producing a plan could expose topology, field or contract failures that
are currently unevaluable. The greedy order is also not a
minimum-family proof. **Actual scope is determined by live slice reruns,
not by this projection.**

Greedy cumulative projection, fixing whole check families in order of
marginal value ("solo" = observations whose ONLY failure is that check):

| # | check family fixed | obs | solo | cumulative conformance |
|---|---|---|---|---|
| 1 | `expected_leaf_output_fields` | 130 | 81 | 54.0% |
| 2 | `forbidden_question_event_ids` | 35 | 23 | 58.9% |
| 3 | `first_question_relevance` | 25 | 20 | 64.1% |
| 4 | `classifier_file_role` | 38 | 10 | 68.4% |
| 5 | `plan_created` | 53 | 15 | 72.5% |
| 6 | `live_model_provenance_complete` | 29 | 0 | 77.2% |
| 7 | `min_source_ref_steps` | 33 | 3 | 80.4% |
| 8 | `min_steps` | 16 | 0 | 83.0% |
| 9–13 | contract-schema, review-policy target, `expected_form_fields`, `question_relevance_complete`, `min_form_field_count` | — | — | 89.5% |
| 14 | `terminal_output_type` | 3 | 0 | **90.1%** |
| … | 11 further checks (26 selected in total) | — | — | 94.0% |

So under the optimistic counterfactual **~14 check families are needed to
cross 90%** and 26 to reach 94%; the tail is long and thin. Real scope
will be larger wherever a fix makes previously unevaluable checks apply.

Correction to an earlier figure in this record's own history:
`classifier_file_role` affects **38 observations** (10 solo), not the 87
first reported — that count double-counted per-file-index checks within
the same observation. All counts in this section are generated by `cp0_allcheck.py`; a disagreement between
that output and this prose is a review failure, not a silent override.

Ownership reality check: of the top five families, the program currently
owns `expected_leaf_output_fields` (CP5), `classifier_file_role` (CP1),
and part of `plan_created` (CP2/CP3). **The question family
(`forbidden_question_event_ids` 23 solo + `first_question_relevance` 20
solo = 43 solo-flips, second-largest lever overall) has no owner**, and
neither do provenance, source-ref counts, or step-count checks.

**The user decision is therefore scope, not feasibility:** under the
optimistic projection ≥90% conformance requires the program to grow from
its current slices to roughly fourteen attributed families, and more in
practice. Options: (1) commit to that scope;
(2) re-scope the release to the reachable metrics (zero stable product
deaths, instability bars, accepted/first-pass, cost) and track
conformance as a trajectory; (3) split functional and conformance gates.

### 6b. Two supported branches would ship without any release evidence

`json_to_text_summary` and `audio_transcription` are live cascade
outcomes (`ai_builder_architecture_derivation.py:196,203`) with zero
corpus coverage. Because create has no fallback, a request landing on
them today compiles through an untested path. "Do not generalize" is not
sufficient. **Release policy (frozen): the release is BLOCKED until either
(a) the corpus covers both branches, or (b) they are explicitly removed
from the supported matrix and made to reject.** This is a user decision on
which route to take, not on whether the gap matters.

### 6c. Corpus size — a known measurement limit, not a blocker

Outcomes are strongly clustered by case, so the corpus's resolution is
governed by its ~138 eligible cases rather than by repetition count. Two
consequences, recorded for CP8 and for any future threshold decision:

- Expressing a rare-event gate as a small attempt-proportion (for example
  `builder errors ≤1%`) is not achievable at this corpus size — which is
  why row 4 is an exact zero count instead.
- Tightening confidence on the proportion rows (1, 2, 5) requires more
  CASES, not more repetitions. Adding repetitions buys instability
  detection only.

Neither blocks release. CP8 must compute the exact figures with its own
arithmetic module rather than inheriting numbers from this prose — every
drift found in review came from a restated constant.

## 7. Cost baselines and frozen limits (nearest-rank p95, both populations)

**Percentile definition (frozen): nearest-rank**, `p95 = sorted(x)[ceil(0.95n)-1]`,
implemented by the packet's `cp0_cost.py`, which is the arithmetic owner and
reproduces this table exactly. (The earlier draft used floor-rank and was
off by one; the previous linear-interpolation extractor was deleted.)

| population | n | rank | p95 calls | p95 tokens | p95 latency |
|---|---|---|---|---|---|
| eligible | 414 | 394 | 7 | 34,884 | 42.205 s |
| accepted | 360 | 342 | 7 | 34,032 | 40.782 s |
| failed eligible (subset) | 54 | 52 | 6 | 34,884 | **48.890 s** |

Frozen limits, with headroom above the measured p95:

| metric | eligible limit | accepted limit |
|---|---|---|
| provider calls / attempt | **≤8** | **≤8** |
| total tokens / attempt | **≤39,000** | **≤38,000** |
| planning latency / attempt | **≤50 s** | **≤48 s** |

The failed-eligible subset is the slowest at 48.9 s p95 — which is why the
eligible limit is 50 s and why accepted-only limits would have left failure
cost unbounded. Context: `MAX_PROPOSAL_PROVIDER_CALLS = 4`
(`ai_builder_proposal_tool_contracts.py:89`) is a per-turn budget; an attempt
spans multiple turns. Repairs: 84.1% of attempts used zero, 13.3% one,
2.6% two.

Not available (recorded so nobody assumes otherwise): monetary cost,
cache-read/write split, reasoning-token counts, per-call attribution
(classifier cost folds into attempt totals), and flow-execution runtime cost
(`execute_flow:false` in this suite).

## 8. Repair drivers — the planned slices are correct but not sufficient

86 repair-triggering failures across 74 repaired attempts:

| kind | n | breakdown |
|---|---|---|
| validation | 38 | `flow_step_invalid` 22, `assembly_plan_invariant_failed` 7, `unknown_form_field_refs_open` 5, `unplaced_form_fields` 1, `duplicate_step_name` 1, `invalid_structured_underlag_projection` 1, `invalid_output_contract_schema` 1 |
| parse | 36 | no failure codes attached — raw tool arguments failed to validate |
| quality | 12 | `named_result_obligations_must_survive` 6, `runtime_metadata_requires_form_fields` 3, `rich_workflow_requires_multiple_steps` 2, `rich_workflow_requires_form_fields` 2 |

CP3 owns ~11, CP5 owns 6 — **~17 of 86 (20%)**. The dominant drivers:

- **Parse failures (36).** `json_to_structured_payload`'s 58.3% repair rate
  is 15/15 parse. Both CP3 and CP5 tighten the raw proposal-argument seam,
  so **both are gated on parse-failure attribution first**. The instrument
  already exists but is env-gated off: set
  `ENEO_AI_BUILDER_REJECTED_PROPOSAL_CAPTURE_DIR`
  (`ai_builder_proposal_capture.py:22`) and re-run the 24-observation JSON
  cohort — cheap and decisive, no new tooling.
- **`flow_step_invalid` (22).** Heterogeneous by ruling and dominant in
  fact; needs a decomposition slice before the repair tax can be claimed.

Terminal (non-repair) failure codes: `terminal_output_type_mismatch` 6,
`flow_step_invalid` 5, `runtime_metadata_requires_form_fields` 4,
`rich_workflow_requires_form_fields` 3,
`named_result_obligations_must_survive` 2, then singletons.

### CP2 step 1 is already complete and confirms dual ownership 6/6

All 6 `terminal_output_type_mismatch` observations are 2 cases × 3 reps,
all deterministic `builder_error` with no plan persisted:

| case | compile side (committed) | conversation side | outcome |
|---|---|---|---|
| `declared_terminal_everyday_bygglovsremiss_text` ×3 | TEXT | **DOCX** | builder_error |
| `declared_terminal_everyday_enskilt_avlopp_text` ×3 | TEXT | **JSON** | builder_error |

The user declared a text terminal; the committed architecture agrees
(TEXT); the second conversation-derived opinion disagrees and the alignment
guard converts that disagreement into a deterministic death. Deleting the
create-path re-derivation converts 2 of the 3 stable product-death cases into plans. CP2 may proceed to design gate.
