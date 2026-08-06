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
the union of both; compared state is `(outcome_class, expectation_verdict)`;
failed checks counted by distinct case id; six comparator behavior tests.

Also landed (`3990ee112`), with one correction to this plan's own wording:

- **Comparability is gated on the identity that changes what a score
  means** — both semantics versions and `requested_model_id`. This plan
  previously said "gate on the full evaluator-identity hash". That is
  wrong and the receipts prove it: `target_sha256` embeds the deployed app
  version, so it and the whole-identity hash differ between *every* pair
  of builds — the exact axis the tool exists to compare. Verified on the
  9d4237a and 9216ec6 receipts, whose identity hashes differ while
  harness, corpus, model, and both semantics versions match. Harness,
  corpus, revision, and target hashes are **reported**, so an undeclared
  instrument change stays visible; per-case contract changes are named as
  rescored cases rather than blocking the other 121.
- Failed checks are aggregated **across repetitions**, once per distinct
  case, instead of read off one representative row.
- Blockers now count the public `error_codes` contract as well as the
  internal `failure_codes`. Counting only the internal one printed an
  empty blocker ranking for a run in which 8 cases errored, because a
  router-level refusal carries no internal detail.

Remaining in this slice:

- Measure the real envelope: run one **frozen build** three times under
  identical identity and publish per-case state stability. Until that
  exists, no claim may cite a "noise floor".

**Done when:** a same-build repeated baseline is published.

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

One row per (case, expected leaf group) for all 43 cases:

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

**Done when:** every row carries a stage and a classification, counts per
(stage × terminal type) are published, and the largest determined cluster
names exactly one implementation owner.

**Guardrail:** fix nothing during this slice.

---

## Slice 3 — Correct the invalid expectations found by Slice 2

**Owner:** `scripts/ai_builder_api_battle_cases.json`.

For every leaf classified rubric-defect or not-required, correct or remove
that expectation with a one-line justification citing the product contract
it contradicts. Then recompute conformance offline from the frozen packet —
no new provider calls.

**Guardrail:** never weaken an expectation because the model fails it. Only
representation-authority arguments justify a change.

---

## Slice 4 — Minimal runtime proof for the seam Slice 5 will change

**Owner:** `scripts/ai_builder_api_battle_test.py`
(`_execute_and_collect_runtime_evidence`), or an equivalent runtime
integration test.

Establish **one** document → non-JSON journey that executes today and
proves a structured producer's values reach document composition. Run it
before and after Slice 5.

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

If no supported producer→consumer seam exists, preserve the prose
obligation or fail explicitly. Never synthesize topology.

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

Six sentinels: text+form→JSON; document→structured payload;
multi-document→PDF report; audio→document; DOCX template fill; review
checkpoint→resume→delivery.

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
3. **Checkpoint:** run the full 122 only to checkpoint, and report the
   outcome × expectation matrix, never first-pass alone.
4. **No-regression rule:** a case that was conformance-passing and now
   fails is a blocker unless repeated measurement of both builds shows the
   change is within the declared non-inferiority margin. Finite noisy
   samples cannot prove literal zero regression; the margin must be stated
   before the run, not chosen afterwards.

---

## Standing guardrails

- Citations slice stays held behind its strict-xfail red test and the
  fail-closed refusal; do not implement it here.
- Structured-field depth cap stays at 3; raising it is a product decision.
- Prefer deleting a rule to adding one; every prompt sentence is paid on
  every proposal.
- One canonical owner per concern. Before adding a path, check whether an
  existing owner can be deepened, moved, or deleted instead.
- Never stage the user's protected working files (`.devcontainer/`,
  `goal.md`, `notes/handoff.md`, `notes/hermes-*`, `state.yaml`,
  `frontend/package.json`, `SolReview/`).
- Secrets (`ENEO_API_KEY`, `ENEO_SPACE_ID`) never enter the repository.
