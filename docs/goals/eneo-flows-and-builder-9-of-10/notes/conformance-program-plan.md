# AI Builder conformance program — executable plan

Status: adopted 2026-08-06 night, after a three-pass peer review
(`.codex/artifacts/codex-peer-loop-flow-122-strategy-review-*`) and a
measured noise floor. Head at adoption: `cc5015c3d`.

This plan is written to be executed slice by slice. Each slice states its
owner, its evidence, what to change, what NOT to change, and how it is
verified. Do not reorder slices: each one makes the next one measurable.

---

## 0. What the evidence says (read before changing anything)

**The headline metric was wrong.** `outcome_class` (`plan_first_pass`,
`plan_repaired`, …) describes proposal mechanics — whether a plan was
produced and how many repairs it cost. `expectation_verdict` describes
whether the plan satisfies the case. Across four full 122-case runs on
2026-08-06 conformance was 42 / 41 / 42 / 44 / 39, while first-pass moved
64 → 68 → 69 → 66 → 71. Only ~23 of ~66 first-pass plans satisfy their
rubric. **Always report the outcome × expectation matrix.**

**The noise floor is ~30%.** Two runs of neighbouring builds disagreed on
36 of 122 cases. Every effect chased on 2026-08-06 was 2–5 cases, i.e.
inside the noise. Suite aggregates from a single run cannot support a
product claim. Mechanism evidence (a capture naming the exact rejected
payload, a source-verified data path) still can.

**The dominant quality cluster is one check.**
`expected_leaf_output_fields` fails in 43 unique cases and is the only
failing check in 28. Split by compiled terminal type: **json 15, text 14,
pdf 13, docx 1**.

**A verified ownership gap explains the non-JSON majority.**
`_clear_prose_output_schema_for_non_json_terminal`
(`ai_builder/planning_state_builder.py`) discards the user's explicitly
named output fields as typed evidence whenever the terminal is not
`structured_json`, and `_merge_model_output_schema_fields` merges
classified output fields only for JSON terminals. Server-derived
source-reader requirements currently add only `summary`
(`ai_builder_create_compiler.py`). So for PDF/DOCX/text terminals the
user's named facts never become a typed obligation that must cross the
step seam — yet the rubric still requires them as leaves.

**Cohort inversion corroborates it.** vague 16/25 and
single_missing_dimension 16/24 pass, while foundation 3/39, pdf 1/25,
complete_everyday 3/17, attachment_or_template 0/7 do not. The product is
weakest where the user was most explicit.

**No remaining assembly defect among no-plan cases.** All four
`architecture_materialization_failed` cases carry the internal code
`assembly_document_report_citations_unsupported` — the deliberate
fail-closed refusal for the held citations slice. The fifth no-plan case
is the flagship quality loop.

---

## Decision rule: product defect vs rubric defect

Applies to every `expected_leaf_output_fields` case. Authority is
**representation**, never prompt wording.

1. **Terminal structured JSON** — a leaf requirement is valid when the
   name appears in a declared schema, in cited `prose_field_names`
   evidence, or as a server-owned result-contract role. If the user
   enumerated JSON fields and planning evidence lost them, that is a
   planning/classification defect.
2. **Terminal text / PDF / DOCX** — require a structured leaf only when
   the value must cross a typed seam: a later step consumes it through
   structured bindings, a review checkpoint targets the structured
   result, a source reader must expose it to later assembly, a template
   placeholder resolves from it, or `ResultContract` owns the obligation.
   Otherwise the user asked for document *content*, not internal JSON
   topology — validate it in executed output or mark the expectation not
   evaluated.
3. **Example- or author-inferred fields** — not required unless the user
   confirmed them or a product policy owns the semantic role.
4. **Backend-owned transformations** — never duplicate their output as a
   leaf. The transcription step produces text via `transcribe_only`; the
   transcript-leaf expectation was deleted on that basis and is the
   precedent.

---

## Slice 1 — Leaf attribution table (no product code)

**Owner:** offline analysis over saved receipts. **Blocks every later
slice.**

Build a table with one row per (case, expected leaf group) for all 43
cases, containing:

- case id, compiled terminal output type, cohort;
- expected aliases for the group;
- cited `PlanningState.output_schema_evidence` (source + names) at
  proposal time;
- derived `ResultContract` role, if any;
- template-placeholder obligation, if any;
- where the name appears in the proposal vs the compiled spec;
- whether any later step consumes it through a typed binding;
- **earliest stage where a valid obligation disappeared**: classification,
  planning state, result contract, proposal, assembly, lowering, or
  evaluator;
- classification per the decision rule above: product defect / rubric
  defect / not-required.

**Source of truth:** saved bundles under
`.codex/artifacts/diag122-*/ai-builder-api-battle-suite-*/`, plus
`builder_sessions.planning_state_jsonb` where the bundle lacks planning
evidence. No provider calls.

**Done when:** every one of the 43 has a stage and a classification, and
the counts per (stage × terminal type) are published in the roadmap.

**Guardrail:** do not fix anything during this slice.

---

## Slice 2 — Correct the invalid expectations found by slice 1

**Owner:** `scripts/ai_builder_api_battle_cases.json`.

For every leaf classified "rubric defect" or "not-required", correct or
remove that expectation, each with a one-line justification citing the
product contract it contradicts (as was done for the transcript leaf).

**Done when:** the corpus contains no expectation that the product's own
canonical topology makes unsatisfiable, and the conformance number is
recomputed offline from saved receipts (no new provider calls).

**Guardrail:** never weaken an expectation merely because the model fails
it. Only representation-authority arguments justify a change.

---

## Slice 3 — Typed cross-step content obligations for non-JSON terminals

**Owner:** `PlanningState` evidence + `ai_builder_result_contract`
projection into `CreateCompileContext`. This is the product fix.

Only proceed if slice 1 shows the non-JSON gap is material (expected: the
majority of 28).

- Stop discarding cited user-named output evidence when the terminal is
  not `structured_json`; retain it as a **content obligation** that is
  distinct from a terminal JSON schema.
- Project those obligations through the existing result-contract path so
  the compiler derives source-reader requirements and cross-step bindings
  from them, exactly as it already does for `summary`.
- The terminal artifact stays PDF/DOCX/text. Never synthesize a fake
  terminal JSON schema to satisfy a rubric.

**Explicitly forbidden:** a second "leaf requirements" store, another
prompt rule, prose parsing of field names, or a new module that
duplicates `ResultContract`.

**Done when:** for a representative case, the user's named facts appear as
typed obligations in the compiled spec's source-reader contract and are
consumed by the composing step, with the terminal type unchanged.

---

## Slice 4 — Deepen the executor, then six executed sentinels

**Owner:** `scripts/ai_builder_api_battle_test.py`
(`_execute_and_collect_runtime_evidence`). Today 5 of 122 cases apply and
1 executes; the executor cannot submit form payloads, handle zero or
multiple upload steps, or resume a review.

Add only: run-contract-derived form payload submission; zero/one/multiple
declared upload steps; one approve-and-resume review action; assertions on
terminal status, delivery kind, and bounded artifact retrieval.

Then establish six executed sentinels: text+form→JSON; document→structured
payload; multi-document→PDF report; audio→document; DOCX template fill;
review checkpoint→resume→delivery.

**Explicitly forbidden:** a second harness or a generic journey DSL.

**Done when:** each sentinel executes end to end and asserts delivery, and
no attachment/template or PDF quality claim is made without one.

---

## Slice 5 — Resume compiler/assembly work

Only after slices 1–4. Rank remaining clusters by unique affected cases ×
user-visible severity × canonical owner, one owner per slice.

---

## Verification protocol (applies to every slice)

1. **Unit gate:** `uv run pytest tests/unittests/flows/ -q` plus
   `pyright --pythonpath .venv/bin/python <changed files>` and
   `ruff check` / `ruff format --check` on the exact changed paths.
   Never format directories.
2. **Mechanism evidence:** for any behavioral change, show the captured
   payload, log line, or compiled spec that proves the mechanism — not a
   suite aggregate.
3. **Stochastic evidence:** any claim about model behavior needs
   `--repetitions 3` (minimum) on a targeted cohort, reported as modal
   outcome plus the unstable set. A single run is never evidence.
4. **Checkpoint:** run the full 122 only to checkpoint, and report the
   **outcome × expectation matrix**, never first-pass alone. Compare with
   `ai_builder_battle_compare.py`, which now retains all repetitions and
   flags unstable cases.
5. **No-regression rule:** a case that was conformance-passing and now
   fails is a blocker unless it is shown to be inside the measured noise
   envelope by repeated measurement.

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
