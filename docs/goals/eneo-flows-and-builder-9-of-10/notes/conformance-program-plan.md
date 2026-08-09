# AI Builder conformance program — executable plan

Status: adopted 2026-08-06 night after a four-pass peer review
(`.codex/artifacts/codex-peer-loop-flow-122-strategy-review-*`), revised
against that review's plan critique. Head at revision: `98293ae39`.

Execute slices in order. Each slice states its owner, its evidence, what to
change, what must NOT change, and how it is proved. Do not reorder: each
slice makes the next one measurable. A slice that cannot meet its proof
condition stops and reports rather than proceeding.

---

## 0. What the evidence says (read before changing anything)

**The headline metric was wrong.** `outcome_class` (`plan_first_pass`,
`plan_repaired`, …) describes proposal mechanics — whether a plan was
produced and how many repairs it cost. `expectation_verdict` describes
whether the plan satisfies the case. Across five full 122-case runs on
2026-08-06 conformance was 42 / 41 / 42 / 44 / 39 while first-pass moved
64 → 68 → 69 → 66 → 71. **`expectation_verdict` is the primary quality
metric. `outcome_class` is mechanics. Always report both.**

**Single runs are not evidence.** Two runs of *neighbouring builds*
disagreed on 36 of 122 cases. That is observed cross-run disagreement — it
mixes model variance, code changes, and configuration — **not** a measured
same-build noise distribution. It is sufficient to establish that
single-run movements of 2–5 cases prove nothing; it is not sufficient to
define an envelope. Slice 0 measures the real one.

**The dominant quality cluster is one check.**
`expected_leaf_output_fields` fails in 43 unique cases and is the only
failing check in 28. Split by compiled terminal type: **json 15, text 14,
pdf 13, docx 1**.

**A verified ownership gap explains the non-JSON majority.**
`_clear_prose_output_schema_for_non_json_terminal`
(`ai_builder/planning_state_builder.py`) discards cited user-named output
evidence whenever the terminal is not `structured_json`, and
`_merge_model_output_schema_fields` merges classified output fields only
for JSON terminals. Server-derived source-reader requirements add only
`summary` (`ai_builder_create_compiler.py`). So for PDF/DOCX/text
terminals the user's named facts never become a typed obligation that must
cross a step seam — yet the rubric requires them as leaves.

**Cohort inversion corroborates it.** vague 16/25 and
single_missing_dimension 16/24 pass, while foundation 3/39, pdf 1/25,
complete_everyday 3/17, attachment_or_template 0/7 do not. The product is
weakest where the user was most explicit. Cohorts are overlapping and not
outcome-normalized: use them as severity multipliers after attribution,
never as an ordering key.

**No remaining assembly defect among no-plan cases.** All four
`architecture_materialization_failed` cases carry the internal code
`assembly_document_report_citations_unsupported` — the deliberate
fail-closed refusal for the held citations slice. The fifth is the
flagship quality loop.

---

## Decision rule: product defect vs rubric defect

Applies to every `expected_leaf_output_fields` case. Authority is
**representation**, never prompt wording.

1. **Terminal structured JSON** — a leaf requirement is valid when the name
   appears in a declared schema, in cited named-result evidence, or as a
   server-owned result-contract role. If the user enumerated JSON fields
   and planning evidence lost them, that is a planning/classification
   defect.
2. **Terminal text / PDF / DOCX** — require a structured leaf only when the
   value must cross a typed seam: a later step consumes it through
   structured bindings, a review checkpoint targets the structured result,
   a source reader must expose it to later assembly, a template
   placeholder resolves from it, or `ResultContract` owns the obligation.
   Otherwise the user asked for document *content*, not internal JSON
   topology — validate it in executed output or mark the expectation not
   evaluated.
3. **Example- or author-inferred fields** — not required unless the user
   confirmed them or a product policy owns the semantic role.
4. **Backend-owned transformations** — never duplicate their output as a
   leaf. Transcription produces text via `transcribe_only`; the deleted
   transcript-leaf expectation is the precedent.

---

## Slice 0 — Measurement integrity (blocks every stochastic claim)

**Owner:** `scripts/ai_builder_battle_compare.py` and the suite summary in
`scripts/ai_builder_api_battle_test.py`.

Already landed (`98293ae39`): instability judged per build rather than from
the union of both; failed checks counted by distinct case id; the first
comparator behavior tests. 31 comparator tests as of `b0de50244`.

Also landed (`3990ee112`, `b0de50244`), with one correction to this plan's
own wording:

- **Product direction is conformance, not mechanics.** Direction was read
  off `outcome_class`, so a case that stopped satisfying its rubric while
  its mechanics held reported as `unchanged` — the exact regression the
  no-regression rule exists to catch. Mechanics are reported beside
  conformance and counted separately. On the 9d4237a → 9216ec6 pair this
  inverts the reading: mechanics improved 17 / regressed 10, conformance
  regressed 13 / improved 8.
- **An unstable build gets no direction.** Promoting one repetition of a
  self-disagreeing build to a verdict is what the modal row did. Unstable
  cases render by default and survive `--only-changed`.
- **Comparability is gated on the identity that changes what a score
  means** — both semantics versions, `requested_model_id`,
  `harness_sha256`, behavior-affecting `run_context` (language,
  auto-confirm, confirmation-message identity), and `base_url`. Missing
  fields fail closed. Declaring a harness edit scoring-neutral is the
  deliberate `--allow-harness-change`, not the default.
- This plan previously said "gate on the full evaluator-identity hash".
  That is wrong and the receipts prove it: `target_sha256` embeds the
  deployed app version, so it and the whole-identity hash differ between
  *every* pair of builds — the exact axis the tool exists to compare.
  Verified on the 9d4237a and 9216ec6 receipts. `cases_sha256`,
  `source_revision`, and `target_sha256` are **reported**, not fatal.
- Rescored cases are **excluded from direction counts**, not merely named.
  Leaving them in is how a rubric correction gets reported as a product
  win.
- Failed checks are aggregated **across repetitions**, once per distinct
  case, instead of read off one representative row.
- Blockers count the public `error_codes` contract as well as the internal
  `failure_codes`. Counting only the internal one printed an empty blocker
  ranking for a run in which 8 cases errored, because a router-level
  refusal carries no internal detail.

Remaining in this slice — **pilot, then power**:

1. **Pilot (in flight).** One frozen build, `--repetitions 3`, single
   identity, all 122 cases. Three repetitions is *not* an envelope; it is
   a pilot whose only job is to estimate each case's stability so the
   repetition budget can be chosen.
2. **Predeclare, from the pilot, before any candidate is measured:**
   - the case-level estimator (proportion of repetitions reaching the
     modal `(outcome_class, expectation_verdict)` state);
   - the interval method and confidence level;
   - the repetition budget implied by the MDE of `5 / cohort_size`;
   - the non-inferiority margin for the no-regression rule.
3. Only then may a claim cite a noise envelope.

**Done when:** the pilot is published *and* the four predeclared
quantities are written down. A pilot alone does not close this slice.

---

## Slice 1a — Deterministic-failure triage (adjudicated 2026-08-07, Pass 6)

The 155×3 frozen-build pilot surfaced failure families that are
**deterministic** (3/3 repetitions). They are cheaper to attribute than
the stochastic rubric cluster, they are user-visible crashes rather than
rubric misses, and they carry different owners and proof conditions — so
they are triaged here, before leaf attribution, and never merged into the
Slice 2 table. Ordering adjudicated by peer Pass 6; attributions below
were verified in source and live receipts the same day.

**Family 1 — commit drift, previously mislabeled "router conflict"
(~7 cases, includes the whole docx-template group).** Mechanism proven
end to end (probe `router-cause-probe3`, 6/6, drift diff on record):

1. Dispatch-time state resolves `docx_output_mode=template_fill_docx`
   from *structural* attachment evidence — placeholders found in the
   uploaded bytes (`_apply_structural_template_docx_mode`,
   `ai_builder_attachment_context.py`), source `attachment_structure`,
   commit-grade. The architecture pin is correct: `template_fill`,
   `document_to_docx_template`.
2. `commit_turn` (`ai_builder_repo.py:1736`) rebuilds planning state from
   conversation only; `carry_forward_persisted_planner_state` carries
   commits, file roles, and schema evidence but **never resolved slots**.
   The narrower rebuild-side resolver
   (`resolve_docx_mode_from_template_evidence`,
   `planning_state_builder.py:1198`) accepts only a model-classified
   explicit role with `quote:` evidence — structural evidence does not
   qualify — so the rebuilt state derives `pass_through` /
   `document_to_structured_report`.
3. The commit-invariance guard compares the pin against the re-derivation,
   refuses, and the turn is released as `provider_outcome_unknown`.
   Until 2026-08-07 the cause was observable nowhere (81 wedged sessions
   in one dev space, empty diagnostic trail); `83edb5dc3` logs the cause
   at the wrap site and `3b60613b8` puts the pinned-vs-draft diff in the
   error.

   **Owner: the `commit_turn` rebuild.** Two assemblies of the same state
   disagree; the guard is doing its job. Fix direction: the rebuilt state
   must preserve attachment-derived commit-grade slots whose source files
   are still attached, at which point the narrow rebuild-side re-resolver
   is the duplicate path and should be deleted. Do not weaken the guard.
   `easy_preschool_incident_note_json` (JSON, no attachment) is in the
   family's case list — capture its drift diff before assuming the same
   mechanism.

**Family 2 — critic false-kill (part of 21 builder_error cases).** The
critic re-derives output intent from raw conversation text
(`resolve_output_intent`, keyword heuristics in
`ai_builder_framework_policy.py`) instead of reading committed planning
state — a second owner for a concern the classifier already owns, and
the weaker one holds veto power. Reproduced offline with no provider
call: `declared_terminal_everyday_bygglovsremiss_text`, whose prompt says
"Slutresultatet ska vara text — ingen PDF, ingen DOCX-mall", resolves to
`template_fill_docx` through double negation-blindness, and the critic
kills the build (`template_fill_docx_requires_template_fill_step`). The
committed slot for the same session was correct (`generated_docx`, high
confidence). **Owner: critic-context construction** — it should consume
committed state; the duplicate keyword derivation shrinks or dies.

**Family 3 — confirmation loop (3 cases, 3/3).** The harness sends the
standard confirmation and the builder answers with another
`requirements_summary`, three turns, never proposing (verified in the
pilot bundle for `text_terminal_intranatsnyhet_namndbeslut`). Attribution
protocol per Pass 6: record the three summary versions, confirmation
metadata versions, and decision events
(`ai_builder_requirements_state.py:171` accepts a confirmation only when
its version matches the latest summary). Fix the module that regenerates
a new summary unless a matching confirmation is genuinely lost.

**Family 1+2 fixes landed and proven live (2026-08-07 midday).**
`6454652a7` carries attachment-derived slots across the planning-state
rebuild; `1a5e3c3f7` makes committed planning state own the critic's
output intent and folds three private copies of the commit-grade slot
read into one `PlanningState.commit_grade_slot_value`. Proof
(`family-fix-proof`, 12 observations, 4 cases × 3): the
`provider_outcome_unknown` wedge is **gone in 12/12**;
`attachment_docx_template_placeholders_to_fields` reaches
`plan_first_pass`; `medium_decision_letter_template_attachment` 2/3
`plan_repaired`. The two declared-terminal cases still fail but now with
*visible, captured* leaf causes:

- `declared_terminal_everyday_kulturbidrag_docx` —
  `self_correction_quality_failure`: every attempt rejected with
  `final_text_step_must_reference_relevant_structured_outputs` (6
  identical captures in `/tmp/rejected-proposals/quality-rejected-*`).
  A critic-vs-model impasse: the remediation does not lead the model to
  a shape the invariant accepts.
- `declared_terminal_everyday_bygglovsremiss_text` —
  `self_correction_invalid_plan`: `steps.1.output_fields[1]` rejected
  ("must be a field object with name, field_type, and description; no
  output_fields were accepted") — captured in
  `/tmp/rejected-proposals/rejected-proposal-*`. Owner candidate: the
  structured-field normalizer / output_fields admission path.

**Full-checkpoint verification (2026-08-07, `checkpoint-8a08a80-155x3`,
DEV-8a08a80d949c, equal 3-rep design vs the pilot).** Conformance per
repetition 47/47/50 → **52/52/60** (mean +6.7 against same-build wobble
≤3). Family conversions at suite scale: provider_outcome_unknown 22→6
observations, requirements_unconfirmed 21→2, interaction_limit 21→2,
plans produced 290→330. builder_error rose 35→50 — journeys that died at
turn one now reach the downstream guards. The comparator's formal
per-case verdict is `no_measurable_change` because 100 cases were
unstable in at least one build and unstable cases get no direction;
the aggregate movement is the evidence.

**Post-checkpoint blocker ranking (by distinct case):**
`architecture_materialization_failed` 13 — of which **10 are the held
citations-slice fail-closed refusal** ("citation sidecar cannot be
preserved"), now the program's top mechanical blocker. The new corpus
tripled its exposure. This is a product decision, not a bug: either the
citations slice gets implemented, or planning must stop promising
citation sidecars the lowering refuses — refusal after planning is a
dead build the user paid for. **Escalated to the roadmap owner; do not
implement the citations slice under this plan's authority.** Remaining:
self_correction_invalid_plan 9, self_correction_quality_failure 8,
critic impasse 6 (auto-binder investigation), residual
provider_outcome_unknown 4 (third wrap site instrumented `dd4b9074e`,
attribution in progress).

**Repair-economics ranking (787 rejection captures from the checkpoint,
by rejection count):** invalid-plan side — `assembly_plan_invariant_failed`
206, per-source documents[] shape 49, `unknown_form_field_refs_open` 30,
`unplaced_form_fields` 22; quality side —
`final_text_step_must_reference_relevant_structured_outputs` 103,
`runtime_metadata_requires_form_fields` 60,
`prose_output_field_names_must_survive` 31,
`rich_workflow_requires_form_fields` 27. These eight checks own nearly
all repair spend; the "no repairs" goal routes through making first-pass
proposals satisfy them — via derived state and compiler ownership, never
by teaching the prompt case-specific vocabulary.

**Critic false-kill family closed (2026-08-09 night, Passes 8–11, gate
GREEN MIN_SCORE 9).** The 103-rejection
`final_text_step_must_reference_relevant_structured_outputs` impasse was
re-attributed before fixing: the previously proposed "count source_refs
in suppression" was disproven by an offline repro at HEAD (the
suppression already lowers source_refs; implementing it again would
have added a duplicate counting path). The real defect was
composer-local crediting: 93 of 107 captures across 25 sessions had
every JSON prior explicitly consumed on the composer's dependency
chain. Landed, each peer-gated: `0567baa79` (ancestry-aware crediting),
`1595e3833` (any question binding replaces the implicit edge — matches
`step_input_resolution` replacement semantics), `eda4865ee` (one shared
consumption calculation for template and non-template terminals; the
unconditional immediate-predecessor credit deleted). Companion commits:
`febe279fc` (citations downgrade warning localized, plain language),
`5cb0cc631` + `9c040516d` (depth cap 3→4, publish-gate + runtime proof,
full tool-schema cost 7088→11844 bytes recorded). Live probe at
`0567baa79`: kulturbidrag (3/3-dead) → zero family captures, 2/3
first-pass, 1 conformance pass; cyber incident 0/3 → 2/3 first-pass.
Newly surfaced, attributed, not yet fixed:
`assembly_document_report_model_ref_conflict` (merge refusal classified
non-repairable → paid death; design gate pending) and the
`rich_workflow_requires_form_fields` residual (guidance pipeline
verified end-to-end; owner lead = server-side hint materialization).
The 14 genuinely under-bound JSON-input composer cases are deferred to
a compiler-owned fan-in slice with its own design gate. Frozen
evidence: `/workspace/.codex/artifacts/evidence-freeze-20260809/`
(799 hashed captures + classifier + probe receipts).

**Checkpoint `checkpoint-eda4865-155x3` (2026-08-09 23:00, 155×3 c=6,
DEV-eda4865ee071 verified, compared vs `checkpoint-8a08a80-155x3` at
margin 5).** Formal verdict `no_measurable_change` — 101 cases unstable
in at least one build get no direction; the aggregate movement is the
evidence: plans produced 330→349, builder_error 50→30, mechanics
improved 26 / regressed 18, pass observations 164→162 (flat). Reading:
tonight's slices converted mechanical deaths into plans, and
conformance is now gated by the rubric-level clusters —
`expected_leaf_output_fields` 58 distinct cases (Slice 2/5 territory),
review-policy checks, and question-relevance checks. The citations
fail-closed family has **zero mentions in 465 observations**. The
residual `architecture_materialization_failed` (10 distinct cases in
the blocker ranking) decomposes to
`assembly_document_report_model_ref_conflict` (8 obs / 6 cases,
kulturbidrag deterministic 3/3 — design gate pending) and
`template_placeholder_unresolved` (2 cases). Receipts:
`/workspace/.codex/artifacts/checkpoint-eda4865-155x3/`.

**Instability posture (Pass 6):** the pilot's 68/155 joint-state
instability is a diagnostic, not a stabilization target — 23/155 (~15%)
flip pass↔fail; much of the rest alternates first-pass vs repaired. No
generic "reduce randomness" slice. Deterministic behavior tests own
correctness; repeated targeted cohorts own incidence.

**Harness gap noted:** `force_new` is passed on every session creation
but absent from `run_context` identity; add it when the harness is next
touched.

---

## Slice 1 — Freeze the evidence packet

**Owner:** analysis inputs.

Pin the exact receipt directories, their sha256, and their evaluator
identity; snapshot any `builder_sessions.planning_state_jsonb` rows the
attribution needs, because that table is mutable and sessions are
overwritten by later runs. No wildcards over `.codex/artifacts/`.

**Done when:** a manifest lists every input file with its hash, and the
attribution can be re-run from it alone.

---

## Slice 2 — Leaf attribution table (analysis only, no product code)

**Owner:** offline analysis over the frozen packet.

**Scope updated 2026-08-07 (Pass 6):** the corpus is 155 cases with 86
authored leaf expectations; 54 failed in at least one pilot observation.
One row per **(case, repetition, expected leaf group)** — one row per
case cannot name a single disappearance stage when repetitions take
different paths. Publish case-level aggregates from the rows. Each row
additionally records: observation outcome and evaluability; authoring
attachment vs runtime-only input vs runtime sample; file-role provenance,
confidence, extraction coverage, and content hash; terminal type/mode at
classification, planning, proposal, and compiled stages; leaf authority
(explicit name, declared schema, placeholder, result-contract role, or
author inference); failed/evaluated repetition count.

Original row description (grain superseded above):

- case id, compiled terminal output type, cohort;
- expected aliases for the group;
- cited named-result evidence at proposal time (source + names), or
  `unavailable` when the snapshot lacks it;
- derived `ResultContract` role, if any;
- template-placeholder obligation, if any;
- where the name appears in the proposal vs the compiled spec;
- whether any later step consumes it through a typed binding;
- **earliest stage where a valid obligation disappeared**: classification,
  planning state, result contract, proposal, assembly, lowering, or
  evaluator — or `undetermined` when evidence is unavailable;
- classification per the decision rule: product defect / rubric defect /
  not-required / undetermined.

`undetermined` is a legitimate outcome; never guess a stage to fill a row.

Decision-rule additions (Pass 6): runtime-only uploads cannot establish
template or schema obligations at authoring time; dependent DOCX/PDF mode
slots must be absent when the declared terminal makes them irrelevant.

**Done when:** every row carries a stage and a classification, counts per
(stage × terminal type) are published, and the largest determined cluster
names exactly one implementation owner.

**Guardrail:** fix nothing during this slice.

---

## Slice 3 — Correct the invalid expectations found by Slice 2

**Owner:** `scripts/ai_builder_api_battle_cases.json`.

For every leaf classified rubric-defect or not-required, correct or remove
that expectation. The justification citing the product contract it
contradicts belongs in the **Slice 2 attribution artifact**, keyed by case
id — not in the cases JSON, which owns expectations, not commentary. Then
recompute conformance offline from the frozen packet — no new provider
calls.

Every case edited here must appear in the comparator's `rescored_cases`,
which excludes it from product direction counts. If a corrected case does
not show up there, the case-contract hash did not change and the edit did
not take.

**Guardrail:** never weaken an expectation because the model fails it. Only
representation-authority arguments justify a change.

---

## Slice 4 — Minimal runtime proof for the seam Slice 5 will change

**Owner:** `scripts/ai_builder_api_battle_test.py`
(`_execute_and_collect_runtime_evidence`). This is the *sole* owner — the
earlier "or an equivalent runtime integration test" is withdrawn, because
it let the choice of proof mechanism be invented at execution time.

Establish **one** document → non-JSON journey that executes today and
proves a structured producer's values reach document composition. Run it
before and after Slice 5.

**The sentinel case is `six_file_document_report_release_gate`** — the
only case in the corpus carrying `expected_runtime_evidence`, six
`reference_material` files, terminal `pdf`. Do not substitute another case
without recording why.

**Rationale:** Slice 5 changes cross-step runtime behavior, and compiled
shape alone cannot prove that. Today 5 of 122 cases apply and 1 executes.

---

## Slice 5 — Typed cross-step content obligations for non-JSON terminals

**Owner:** `PlanningState` evidence + the `ai_builder_result_contract`
projection into `CreateCompileContext`. This is the product fix. Proceed
only if Slice 2 shows the non-JSON gap is material.

**Shape — replace, do not supplement.** Replace the `prose_field_names`
*schema* representation with one neutral, bounded, cited **named-result
evidence** value inside `planning_state.py`. It carries identity and
provenance, not schema shape. Because the product is prerelease, delete the
obsolete path rather than adding compatibility reads. Do not create a
module.

`ResultContract` remains the sole computed projection:
- terminal JSON → derive the open field-name contract;
- non-JSON → expose content obligations only where a value must cross an
  existing typed seam;
- declared schemas remain the sole owner of type, nesting, validation, and
  requiredness;
- template placeholders keep their existing owner.

**Required invariant (state it in code and test it):**

> A content obligation may originate only from bounded, cited, explicit
> user-named-result evidence. It carries identity and provenance, not
> schema shape. It may materialize only as a scalar content capture on an
> already-required structured producer with a declared downstream consumer.
> It cannot create a JSON step, choose nesting or requiredness, alter the
> terminal type or schema, or originate from inferred examples or uncited
> prompt interpretation.

**When no supported producer→consumer seam exists** — one behavior, not a
choice: retain the cited evidence *without materializing* it. Failing is
reserved for the single case where an already-declared downstream typed
consumer cannot be satisfied. Never synthesize topology, and never treat
"no seam" as a reason to fail the build.

Reuse the existing scalar materialization in
`ai_builder_source_reader_contracts.py` and its limits rather than
inventing field types.

**Lifecycle cases that must be covered:** terminal changes (JSON → PDF →
JSON), explicit clear/removal, declared-schema precedence, folded-name
collisions, maximum field and evidence counts, persisted schema-version
behavior.

**Done when:** the Slice 4 runtime sentinel passes before and after; a
representative case shows the user's named facts as typed obligations
consumed by the composing step; the terminal type is unchanged; and the
invariant has direct tests.

---

## Slice 6 — Complete the executor and the sentinel matrix

**Owner:** the existing executor. Add only: run-contract-derived form
payload submission; zero/one/multiple declared upload steps; one
approve-and-resume review action; assertions on terminal status, delivery
kind, and bounded artifact retrieval.

Six sentinels, named by case id so the shapes are not re-derived at
execution time:

| Journey | Case id |
| --- | --- |
| text + form → JSON | `advanced_explicit_e_service_submission` |
| document → structured payload | `attachment_example_report_infers_disposition` |
| multi-document → PDF report | `six_file_document_report_release_gate` |
| audio → document | `medium_audio_to_protocol_pdf_with_metadata` |
| DOCX template fill | `attachment_docx_template_placeholders_to_fields` |
| review checkpoint → resume → delivery | `advanced_sundsvall_tjansteskrivelse_runtime_sources_docx` |

Each sentinel must declare, before it is written: its fixture file ids,
the payload source for form submission (the run contract, never a literal),
the review action taken, and the terminal assertions. A sentinel that
cannot state all four is not ready to be written.

**Explicitly forbidden:** a second harness or a generic journey DSL.

---

## Slice 7 — Stop and reslice

Not an implementation slice. After Slice 6, re-run attribution and rank
remaining clusters by unique affected cases × user-visible severity ×
canonical owner, then write the next plan. A multi-agent run must not treat
this as authorization for open-ended compiler work.

---

## Verification protocol

**Deterministic proof is primary.** For any behavioral change, the proof is
a unit/integration test, a captured payload, a compiled spec, or a runtime
sentinel. Stochastic suite runs measure *incidence*, never correctness.

1. **Unit gate:** `uv run pytest tests/unittests/flows/ -q`, plus
   `pyright --pythonpath .venv/bin/python <changed files>` and
   `ruff check` / `ruff format --check` on the exact changed paths. Never
   format directories.
2. **Stochastic measurement**, when incidence matters:
   - predeclare the mechanism-targeted cohort plus adjacent negative
     controls;
   - use **equal repetitions** for baseline and candidate under identical
     evaluator identity, interleaved where possible;
   - primary metric is `expectation_verdict`; `outcome_class` is secondary;
   - before running, state the minimum detectable effect as
     `5 / cohort_size` and choose repetitions so the reported interval can
     resolve it;
   - three repetitions is **exploratory only**;
   - set a bounded maximum repetition cost; if the interval stays wider
     than the MDE, report **inconclusive** — never promote a modal result
     to proof.
3. **Checkpoint:** run the full pinned corpus (manifest identity, not a
   stale count) only to checkpoint, and report the outcome × expectation
   matrix, never first-pass alone.
4. **No-regression rule:** a case that was conformance-passing and now
   fails is a blocker unless repeated measurement of both builds shows the
   change is within the declared non-inferiority margin. Finite noisy
   samples cannot prove literal zero regression; the margin must be stated
   before the run, not chosen afterwards.

---

## Standing guardrails

- Citations slice stays held; the sidecar itself is not implemented. The
  fail-closed refusal was replaced by adjudicated design (Pass 7,
  2026-08-09): document-report lowering admits the request by clearing
  citation flags and emitting one capability warning through the
  validation-diagnostics path; the late fatal helper is deleted once
  unreachable.
- Structured-field depth cap: raise to 4 only after a deterministic
  runtime proof (compile → publish → structured output → downstream
  consumption of the captured depth-4 array/object shape, plus a depth-5
  rejection). Flattening is rejected — dots collide with binding-path
  syntax. Record the tool-schema byte-cost delta when the constant moves
  (measured 4124 → 8880 bytes for the structured-field fragment).
- Prefer deleting a rule to adding one; every prompt sentence is paid on
  every proposal.
- One canonical owner per concern. Before adding a path, check whether an
  existing owner can be deepened, moved, or deleted instead.
- Never stage the user's protected working files (`.devcontainer/`,
  `goal.md`, `notes/handoff.md`, `notes/hermes-*`, `state.yaml`,
  `frontend/package.json`, `SolReview/`).
- Secrets (`ENEO_API_KEY`, `ENEO_SPACE_ID`) never enter the repository.
