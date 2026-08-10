# Eneo Flows + Flow AI Builder — Master Program (living document)

Status: EXECUTION PHASE, program **v10.2** (peer-adjudicated
iterations 74–77, session `flow-122-strategy`; promoted 2026-08-10
after the sole remaining finding was a one-clause self-contradiction).
LANDED: CP0 (evidence), CP8a (instrument/product separation,
`0228f0e1d`), L1c (`355ad6f68`), L1a (`8df804213`). All three user
decisions stand (2026-08-10 ~19:38: TRAJECTORY / SPLIT / BALANCED).

v10.2 REPLACED v9.8 after three source-verified audits — structural
debt, a systematic dual-ownership inventory, and runtime-slice drift —
established that the program owned the measured failure FAMILIES but
not the structural DISEASES behind them. What changed: an adopted END
STATE, a dual-ownership ledger with load-bearing statuses, five new
slices, an evidence-ranked order, and a god-module doctrine under which
no standalone split slice exists.

This file owns execution and is the SOLE execution-order owner;
`cp0-matrix-freeze.md` owns evidence and the gate inventory.

## Mission

Production-excellent Flow AI Builder and Flows runtime (9/10): no
errors, near-zero repairs on supported archetypes, plans that satisfy
what the user actually asked, bounded resources, provable recovery,
clean single-owner architecture. Evidence-first: no fix without an
attributed mechanism; no claim without receipts; the battle suite
over the FINAL FROZEN CORPUS (3 repetitions, margin 5, rescored-case
discipline) is the instrument. Population is always derived from the
frozen manifest, never restated as a prose constant.

## Where we are (2026-08-10; product-code baseline `2e0a4dced` — this
## document evolves past it, see git log for the doc HEAD)

- Three checkpoints: deaths 50→30→27; architecture kills 13→10→2;
  provider wedges 22→6→2; conformance 149→162→170 of 465 (formally
  no_measurable_change; 81/155 cases unstable run-to-run).
- Repair tax: ~21% of accepted plans repaired. Cross-tab of repair
  wrappers: form-field family 7 obs, terminal_output_type_mismatch 6,
  flow_step_invalid 5, singletons after that.
- Shape coverage (clean checkpoint r01): json-terminal 36%,
  document-report 22%, text-terminal 14%, template-fill 3% — ~90% of
  plan-producing usage is server-recognizable.
- Slice 5 commit 1 landed: NamedResultEvidence (typed, cited, bounded)
  replaced the fake prose schema end-to-end; six hardening rounds.
- Runtime: full celery topology works (execute + maintenance + beat);
  crash recovery proven through the scheduled path; one-record-per-
  source enforced; connection budget bounded and logged; production
  compose network P0 fixed.

## THE ARCHITECTURE VERDICT (peer pass 31, max effort — adopted)

The system is NOT misdesigned; it is mid-migration. Create mode
already separates semantic intent from mechanics; the repair tax comes
from semantic decisions still model-owned. Therefore:

- **Never build a second skeleton compiler.** Deepen
  `CreateCompileContext` + `ai_builder_assembly`. `Pattern` stays
  selection metadata, never executable topology.
- **Transfer ownership one typed decision at a time**: each transfer
  moves a decision from proposal-time (model) to compile-time
  (server), then DELETES its prompt text and create-repair path.
- **Metrics of record** (not raw invariant count): supported create
  archetypes reach ZERO normal-path semantic critic hits; repair
  attempts and provider calls per accepted proposal fall
  monotonically; model-authored mechanical fields never increase;
  edit guards and compiler postconditions stay until their owner
  makes them unreachable.
- Honest ceiling without the transfers: conformance plateaus ~45–55%,
  leaf instability 20–30%.
- CORRECTED BY CP0 (2026-08-10): there is NO free semantic proposal
  path in create. `ai_builder_proposal_submission.py:422` raises
  `architecture_materialization_failed` when no architecture is
  committed. This bullet previously claimed such a fallback existed;
  it never did. Any such path must be designed deliberately, not
  assumed.

## THE END STATE (adjudicated iteration 74 — ADOPTED)

The existing hybrid compiler, made STRICTER. The stronger form — "the
model never proposes structure; assembly emits the whole skeleton" —
was proposed and REJECTED with reason: it would replace useful semantic
decomposition with a second pattern-driven compiler, recreating dual
ownership one level up.

- The MODEL owns: semantic work units, instructions, names, field
  design. This is permanent, not transitional.
- `CreateCompileContext` + `ai_builder_assembly` own: physical
  topology, step kinds and order, wiring, runtime inputs, output modes,
  checkpoints, fixed transformations.
- `Pattern` stays selection metadata, never executable topology.
- The server PREVENTS the model from proposing runtime mechanics.
  SURFACE CLOSURE means schema omission AND parser rejection — a closed
  surface that silently strips is not closed
  (`ai_builder_proposal_intent.py` owned-key stripping).
- CP3 and CP5 keep their planned shape under this end state.

## Dual-ownership ledger (audit 2026-08-10; statuses are load-bearing)

TRUE = two independent derivations with reachable disagreement.
SELF_CHECK = one canonical derivation verified twice (KEEP IT).
LAYERED = pure function of the owner. HAZARD = parallel
implementations, no comparison guard, drift risk only. UNPROVEN =
claimed but no reachable counterexample yet; a receipt precedes any
code.

Program completion resolves every TRUE row. This is a BOUNDED AUDIT
ARTIFACT re-checked per slice, not a permanent grep gate.

| # | Fact | Status | Owner |
|---|---|---|---|
| D1 | Terminal output type (create) | TRUE | CP2 (exit check covers the 2nd caller `ai_builder_scoped_plan_revision.py:151`) |
| D2 | Proposal tool schema built at two sites | TRUE | CP3 |
| D3 | Mixed audio+doc re-inference on create | TRUE | CP-D3 |
| D4 | Terminal step `output_type` still emit-able | TRUE | CP3 |
| D5 | Form-field placement A/B exclusion divergence | UNPROVEN | receipt task |
| D6 | Commit re-derivation at persist | SELF_CHECK — keep `CommitDriftError` | CP-D6 (receipt-gated) |
| D7 | Classifier slot vs merged slot re-ask | UNPROVEN | receipt task |
| D8 | Runtime-metadata request re-derived | TRUE | CP3 |
| D9 | Edit terminal type: two derivations, opposite precedence | TRUE | CP-EDIT |
| D10 | `CreateCompileContext` built 4–5× with different args | TRUE | CP3 (materializer) |
| D11 | `confirmed_form_field_incompatible` implemented twice | HAZARD | split-when-touched |
| D12 | Rate-limit vocabulary | HAZARD | ruling below; binds L2 |

## Done ledger (checkmarks; update when a slice lands + gates)

- [x] Deterministic death families closed (commit-drift, critic
      intent, confirmation loop, evidence churn, lint_warnings,
      citations degrade, critic false-kill/ancestry, model-ref
      degrade) — deaths 50→27 across three checkpoints
- [x] Slice 1 frozen evidence packet + Slice 2 leaf attribution
      (unique grain, stability separated)
- [x] Slice 3 rubric corrections (11 deletions + 30 receipt-verified
      aliases; 25-case rescored discipline proven in comparator)
- [x] Slice 5 commit 1: NamedResultEvidence representation (six
      hardening rounds; schema v17/v20)
- [x] Depth cap 3→4 with publish-gate + runtime proof
- [x] Document-report assembly split (4 concerns, AST-verified)
- [x] Production compose network P0 + isolation note
- [x] Crash recovery proven through the scheduled path (`6559ef503`)
- [x] One-record-per-source runtime contract (`0b45457bd`)
- [x] Database connection budget bounded + logged (`2e0a4dced`)
- [x] Measurement instrument hardened (sentinel checks executable +
      case-gated; comparator case-local waiver; frozen baselines)
- [x] Architecture verdict adopted (Pass 31) + shape-coverage and
      repair cross-tab evidence
- [x] Program convergence — GREEN at 9, iteration 38 (2026-08-10)
- [x] User sign-off — approved 2026-08-10 (start held; launch on
      explicit go)
- [x] CP0 matrix freeze — evidence + gate inventory (`35d3ee251`)
- [x] Step 0.8 audio_transcription corpus freeze (`905d6f4ca`)
- [x] L1c connection-envelope self-consistency (`355ad6f68`; gate
      receipt `l1c-connection-envelope-20260810T185321Z`, green 8)
- [x] L1a celery queue-name ownership via per-service role
      (`8df804213`; gate receipt
      `l1a-queue-name-ownership-20260810T194013Z`, green 8)
- [x] CP8a instrument/product separation (`0228f0e1d`; gate receipt
      `flows-builder-9-10-program-20260810T203713Z`, green 9)
- [x] Three structural audits + v10.2 program revision (adopted end
      state, dual-ownership ledger, god-module doctrine; iterations
      74–77)

## The Ranked Program (v10.2 — execution phase; slice bodies carry
## their originating iteration tags)

### Gate inventory — owned by `cp0-matrix-freeze.md` §3
CP8 will own the release contract; this section points at the inventory
CP8 must satisfy.
It lives there and is authoritative. Do not restate its numbers here.

THREE user decisions BLOCK product work (two in
`cp0-matrix-freeze.md` §6, one from CP9a):
(a) conformance scope — whether ≥90% expectation conformance is a
release gate (currently PENDING in the registry) or a tracked
trajectory; (b) the two unmeasured supported branches
(`json_to_text_summary`, `audio_transcription`) — cover with cases or
remove from the matrix and make them reject; (c) question policy —
ask about optional runtime metadata on open prompts, or assume none
with a visible overridable assumption (evidence packet from CP9a).
The NUMBERED EXECUTION ORDER below is the SOLE lifecycle owner; every
other mention of sequencing is a pointer to it.
Corpus expansion (§6c) is OPTIONAL and blocks nothing, except that a
small attempt-proportion form of the builder-error gate would
not be achievable at this corpus size — which is why that gate is an
   exact zero count instead.

Feasibility rule established by CP0 and binding on every future gate:
a gate that a PERFECT product could not pass on the actual corpus is a
broken gate, not a high bar. Audit best-case feasibility before freezing
any threshold.

### Critical path (builder stream; each slice design-gated → worker →
### commit-gated → cohort probe)
- [x] CP0 Matrix freeze — analysis DONE 2026-08-10 (evidence + gate
    inventory; not a frozen statistical contract). Evidence, dispositions, corrected taxonomy and the
    gate INVENTORY live in `cp0-matrix-freeze.md`;
    clone-local hashed evidence packet
    `.codex/artifacts/cp0-freeze-20260810/` (manifest and digest live
    in the evidence owner; verify there, not here). THREE user decisions block product work; the numbered execution
    order is the sole lifecycle owner; then CP8, and only then
    builder product work.
- [ ] CP8 Release-gate implementation — **FIRST slice after the user
    decisions, and a HARD BARRIER before ALL builder product work and
    any candidate measurement** (otherwise verdict semantics could be chosen after
    seeing product results). Implement the
    §3 gate inventory inside `backend/scripts/ai_builder_battle_compare.py`
    (which already owns fail-closed receipt identity), with
    the six findings in `cp0-matrix-freeze.md` §3 — best-case
    feasibility audit of every threshold, cluster-aware intervals that
    cannot false-pass adverse clustering, provider detection by the
    canonical marker with bounded slot-level re-measurement, one
    arithmetic module with no duplicated constants, and contract tests
    pinning the worked counterexamples.
- [ ] CP1 File-role flip closure (TRIMMED, iteration 33). The margin
    regression IS the task-14 case (same mechanism, confirmed).
    Deepen the EXISTING merge owner `_model_file_role_can_replace`
    (`planning_state_builder.py:1006`) — verified: it checks source
    and heuristic confidence but never the existing role's evidence
    LEVEL, so an inferred re-classification can replace an
    explicit-quote-backed role. Fix: monotonic precedence from
    existing evidence level + citation identity — same-evidence flips
    rejected, genuinely later explicit corrections accepted,
    conflicting evidence becomes explicit ambiguity. NO role-history
    store. The extra question round is attributed inside this same
    case study.
- [ ] CP2 Terminal ownership consolidation (premise CORRECTED in
    iteration 32, source-verified): the mismatch is SERVER-vs-SERVER
    dual ownership — compile derives the terminal from
    `architecture_commit` (`ai_builder_create_compiler.py:710`) while
    create preparation re-derives it from conversation text
    (`ai_builder_create_proposal.py:190` →
    `terminal_output_type_for_conversation`,
    `ai_builder_proposal_policy.py:259`) and a guard compares the two
    (`ai_builder_compiled_spec_preparation.py:70`). Ninth
    dual-ownership family. Step 1: attribution table with BOTH
    derivations per observation (re-derive offline from persisted
    planning state + conversation). Step 2 if confirmed (AMENDED,
    iteration 33): keep the postcondition but feed it
    `CreateCompileContext.final_output_type` — same-owner self-check,
    not dual ownership; delete only the conversation re-derivation on
    the create path and the model-repair ownership (a create mismatch
    becomes a compiler defect, never model-repairable feedback);
    conversation derivation survives only for edit semantics.
    Exit check: no create caller still invokes
    `terminal_output_type_for_conversation`. `flow_step_invalid`
    stays a separate heterogeneous family (`flow_validators.py:227`).
- [ ] CP2b Parse-failure attribution (GATES CP3 AND CP5, added by CP0):
    parse failures are the single largest repair driver (36 of 86) and
    `json_to_structured_payload` is 15/15 parse. Both CP3 and CP5
    tighten the same raw-argument seam, so neither may implement
    before this is attributed. Instrument already exists, env-gated
    off: set `ENEO_AI_BUILDER_REJECTED_PROPOSAL_CAPTURE_DIR`
    (`ai_builder_proposal_capture.py:22`) and re-run the 24-obs JSON
    cohort.
- [ ] CP3 Runtime-input-field contract (AMENDED, iteration 33).
    `FlowInputFieldIntent` stays the field VALUE schema, but verified
    it carries no citations/confidence
    (`ai_builder_proposal_intent.py:80`) and the classifier exposes
    only boolean form intake
    (`ai_builder_slot_classification_contract.py:162`) — so the
    classifier ships a bounded CITED DELTA ENVELOPE (update/clear +
    per-field citations + confidence; the same transport pattern as
    ClassifiedNamedResultDelta), a transport contract around the
    existing value type, never a second owner. Durable owner stays
    conversation metadata; `PlanningState.input_fields` stays the
    derived view; placement defaults to the archetype's one
    deterministic consumer; semantic purpose only for evidence-backed
    multi-consumer cases; never leak physical `PlannedStepRole`
    upstream. HARD DEPENDENCY (iterations 34+35): before CP3
    removes fields, pull forward ONE archetype-aware proposal-schema
    materializer with the CORRECT carrier lifecycle (verified:
    budgeting finishes before `ProposalTurnContext` exists, and
    `ProposalPrepared` carries no schema today) — materialize once
    during preparation, store the schema on `ProposalPrepared`
    (`ai_builder_planner_request_preparation.py:171`), pass it into
    submission, and set it on `ProposalTurnContext` for the initial
    and repair calls; DELETE `_active_submission_tool_schemas`
    (`ai_builder_proposal_submission.py:164`). The SAME schema (same
    hash) serves THREE consumers — token budgeting, provider
    submission (initial AND repair), and SERVER-SIDE validation of
    the raw tool arguments BEFORE normalization (iteration 37: today
    the parser normalizes first, silently dropping retired root keys
    via `_CREATE_INTENT_ROOT_IGNORED_KEYS`
    (`ai_builder_proposal_intent.py:77`) and stripping backend-owned
    step keys (`:505`) — a closed surface that still strips is not
    closed; a supported-row payload carrying an excluded field must
    FAIL). CP3 and CP5 both consume this one schema; neither invents
    its own adaptation. Then
    delete the prompt's mechanical form-field block, the create
    repair mapping, and create-mode responsibility of the four
    form-field invariants (edit guards stay), and remove
    `input_fields`/`uses_form_fields` AND the retired create
    `review_mode` from that archetype's proposal schema (surface
    closure; the review-policy transfer itself already shipped —
    CheckpointIntent + compiler stripping, typed intent wins).
- [ ] CP4 JSON partial-emission diagnosis: why OSE captures some
    user-named fields and misses others (4 JSON cases). Diagnosis
    first; bounded fix gated on attributed mechanism.
- [ ] CP5 Named-result completion, redesigned (AMENDED, iteration 33):
    named evidence owns PRESENCE, never design. Verified blockers the
    design gate must resolve BEFORE code: the current invariant
    accepts an obligated name at ANY depth
    (`ai_builder_critic_invariants.py:854` via
    `schema_property_names_at_any_depth`), so naive top-level
    `required` keys would silently choose nesting; and the proposal
    tool schema is built independently at TWO sites — token budgeting
    (`ai_builder_planner_request_preparation.py:463`) and submission
    (`ai_builder_proposal_submission.py:171`) — with obligations
    reaching neither. Design gate decides: top-level placement as a
    canonical product rule OR a bounded per-name design map with a
    defined compiler projection; then EXTEND the CP3-owned schema
    materializer (no second materialization site); then one
    provider strict-tool
    probe with a nested obligated field. No recursive schema DSL.
    NO ESCAPE HATCH (iteration 34): if the provider cannot express
    the contract, the design gate picks one of two closed outcomes —
    declared top-level placement as the canonical product rule, or
    classifying that shape as OUT of the supported matrix (there is no
    free fallback in create — CP0 §2), with the branch made to reject
    explicitly. The critic may
    survive only as a compiler POSTCONDITION (defect detector), never
    as a normal repair owner on a supported archetype.
- [ ] CP6 Authoring must REJECT unindexed array paths
    (RELEASE-CRITICAL, direction FROZEN in v9.1 — "parity" alone could
    be satisfied by weakening the runtime, which is the wrong
    architecture): the runtime's numeric-index requirement
    (`variable_resolver.py:374`) is the correct semantic; authoring's
    lenient default (`ai_builder_json_schema_paths.py:9`) and its
    backwards-compat mode are deleted under the prerelease no-compat
    ruling, and a behaviour test proves an invalid path cannot be
    published. Scheduled immediately after CP8.
- [ ] CP-D3 Mixed-audio create re-inference — DELETION, not
    synchronization. The three mixed-audio invariants are labelled EDIT
    guardrails (`ai_builder_critic_invariants.py:1743` region) yet
    create runs them as fatal architecture checks
    (`ai_builder_proposal_policy.py:219`), re-deriving input intent
    from conversation text (`ai_builder_plan_quality_critic.py:162`)
    despite having already materialized `CreateCompileContext`.
    FORBIDDEN fix: passing `explicit_question_ids` to align the two
    derivations — that synchronizes dual ownership instead of removing
    it. Correct fix: gate all three OUT of create, retain for edit, let
    compiler/assembly postconditions protect create topology. Tests:
    create non-firing AND edit rejection at the public policy
    interfaces. Any residual create need is owner-fed from the compile
    context, never text re-inference. Closes a post-payment death path.
- [ ] CP-ADMIT Architecture-commit admissibility — DESIGN GATE FIRST,
    producing a per-code dependency table for every member of
    `_NON_MODEL_REPAIRABLE_ARCHITECTURE_FAILURE_CODES`
    (`ai_builder_create_proposal.py:66`). Only predicates decidable
    from planning-state/server inputs BEFORE the provider call move to
    commit or discovery time; `_architecture_hints_are_supported`
    (`ai_builder_assembly/create.py:967`) is that predicate today and
    is server-decidable, but runs one LLM call too late. VERIFIED
    counter-example: the `flow_input_schema` codes run against the
    COMPILED spec (`ai_builder_create_compiler.py:419` region) and stay
    as compiler postconditions. Extracts ONLY the gates seam.
    `assembly_document_report_review_mode_conflict` becomes a USER
    QUESTION, not an error. No blanket "kills 8 of 10" claim.
- [ ] CP-EDIT Edit-path terminal-type ownership (design gate first):
    ONE conversation-derivation owner with ONE precedence rule — today
    `ai_builder_proposal_policy.py:265` (latest message first) and
    `ai_builder_plan_quality_critic.py:85` (committed slot first)
    disagree and feed two different guards. Carries the
    `aggregation_intent` edit-wiring fix
    (`ai_builder_proposal_finalization.py:275` never passes it, so
    compare-edits draw false-positive critic hits).
- [ ] CP-D6 Commit-drift bypass — RECEIPT-GATED. One behavior test at
    the decision+persistence exit interface reproducing architecture
    drift WITH a selected question. VERIFIED: a `_phase_priority`
    reorder would be INERT — `revise_architecture` is only eligible
    when there are no ask targets, and the turn controller
    short-circuits `ask_question` first
    (`ai_builder_turn_controller.py:249`). If the receipt reproduces a
    lost turn, the fix is the ELIGIBILITY rule plus the controller
    contract; if it does not reproduce, DELETE this slice.
    `CommitDriftError` is retained either way.
- [ ] `json_to_text_summary` REMOVAL (user decision §6b SPLIT):
    delete all THREE live declarations — the derivation cascade branch
    (`ai_builder_architecture_derivation.py:186` region), pattern
    metadata (`pattern_registry.py:210` region), and assembly's
    supported set (`ai_builder_assembly/create.py:118` region) — make
    the tuple reject explicitly, add the product behavior test, drop
    the supported matrix row, AND write the matrix-state revision that
    CP8b's row 14 reads (receipt revision must match it).
- [ ] Critic disposition table (RECEIPT TASK, analysis lane): all 31
    invariant IDs with classification, canonical fact owner,
    normal-path action, destination (delete / postcondition / genuine
    guard), PRODUCTION reachability — not merely evaluator
    reachability — and the deletion test that dies with it. Until it
    exists, the audit's 13 DERIVABLE / 16 GENUINE / 2 DEAD split and
    the 731-line closure are CANDIDATES: counter-evidence already
    found — a candidate-DEAD invariant has a direct firing behavior
    test (`test_ai_builder_plan_quality_critic.py:1906`). Registry
    STRUCTURE is kept; each deletion rides its owning CP with per-ID
    evidence and updates the kind-pinning tests in the same commit.
- [ ] CP7 Validation-trigger attribution (widened in v9 — the ONE
    definition): the validation repair triggers NOT already owned by
    CP3's form-field family (32 of 38 — `unknown_form_field_refs_open`
    5 and `unplaced_form_fields` 1 are CP3's), dominated by
    `flow_step_invalid` (22) and `assembly_plan_invariant_failed` (7)
    plus singletons, plus `min_source_ref_steps`, `min_steps`,
    `max_steps` and `live_model_provenance_complete` from the
    conformance table, and
    the bounded `checkpoint_intent_mismatch` attribution
    (checkpoint/compiler seam, CP0 §4). Heterogeneous by ruling:
    attribute per inner code to a named product or instrument owner
    before any fix is implemented.
- [ ] CP9a Question-policy EVIDENCE PACKET (ANALYSIS, step 0 —
    v9.3): the forbidden-question and stall families are a
    PRODUCT-POLICY-VS-CASE-CONTRACT CONFLICT with no presumed side.
    Verified mechanics and receipt facts live in the evidence owner
    (`cp0-matrix-freeze.md` §8b); in short, the product deliberately
    asks `runtime_metadata_fields` on open interviews (issue created
    when metadata absent, no normal-path assumption case, behaviour
    tests expect the question) while 19 battle contracts forbid it.
    DECISION AUTHORITY (v9.5): no normative rule decides this — the
    tracked product contract says server policy owns questions and
    assumptions must be visible, but is silent on whether absent
    OPTIONAL metadata is safe to assume. It is therefore the USER'S
    THIRD DECISION (pending-decision 7 below), presented with the
    evidence and my recommendation; CP9a prepares that packet, it
    does not decide. If the product branch (CP9b) is chosen, its
    behaviour test must prove the question disappears on open
    prompts, the no-metadata assumption is VISIBLE and localized
    (the existing assumption seam), and the user can override it.
    Sequencing is owned by the numbered execution order (steps 0–1):
    evidence packet first; the CONDITIONAL rebaseline (rescored_cases
    per the standing Slice-3 protocol, offline recomputation of CP0
    counts and projections, manifest and conclusion updates) happens
    only after — and only if — the user chooses the rubric branch;
    the §6a/§6b decisions then read the final evidence. If the user
    chooses the product branch, the contracts stay frozen and only
    CP9b is scheduled. Any later instrument correction invalidates
    earlier candidate receipts and re-enters pre-registration. Stall
    answerability follows the same evidence-packet-then-user path
    at the same time.
- [ ] CP9b Question-policy product change (only if the USER chooses
    the product branch in decision 7): implemented in execution-order position 7, inside
    the existing discovery decision engine (the budget-exhaustion
    path's `assume_no_runtime_metadata` seam is the candidate), with
    the deliberately-expecting tests updated in the same slice. No new
    policy, no new store, no second owner.
- [ ] Remaining family assignments (v9 — every measured family has
    an ASSIGNED ATTRIBUTION SLICE; product owners are established by
    attribution; counts live in `cp0-matrix-freeze.md`): output-contract schema → CP5; input-contract schema and
    expected_form_fields and unknown_form_field_refs_open and
    unplaced_form_fields → CP3; min_source_ref_steps and
    live_model_provenance_complete → CP7 (see its single definition
    above); long tail → the standing re-attribution loop.
- [ ] Conditional paths for the two open decisions (v9): §6a
    conformance — if GATE: registry row 5 becomes gating, a
    mixed-conformance case limit is frozen with it, and the program
    commits to the full ~14-family scope; if TRAJECTORY: row 5 is
    marked non-gating and the release rests on the reachable rows —
    but RELEASE ELIGIBILITY IS NOT PROGRAM COMPLETION: the 9/10 claim
    is withheld until the pre-registered completion condition is met —
    FROZEN HERE: registry row 5 (expectation conformance) evaluated by
    CP8's own cluster-aware arithmetic reaches PASS on a subsequent
    measured run, AND at most 10% of the final corpus's cases (exact
    count derived by CP8 from the frozen manifest — the same bar as
    the mixed-first-pass gate) are conformance-unstable across
    repetitions — the same verdict machinery as the gate branch, so
    the trajectory branch cannot quietly use a weaker method — and the
    program continues after release until then. §6b branches — if COVER:
    the new cases for `json_to_text_summary` and `audio_transcription`
    are written, contract-hashed and frozen BEFORE the first candidate
    measurement (a corpus chosen after seeing product results is not
    pre-registered), and CP8 uses that final corpus identity; if REMOVE: delete
    the two cascade branches and make those tuples reject explicitly
    (create has no fallback, so silence is not an option). The plan
    is valid under either answer of each.
- [ ] Ownership-tranche gate: exploratory final-frozen-corpus ×3 checkpoint after
    CP1–CP3 land. The release gate is a separate N=5 release
    evaluation (CP0 established that repetitions supply instability
    DETECTION, not certification power), repeated after every material
    post-gate change.
- [ ] Post-CP5 re-attribution loop: rerun attribution and continue
    ownership transfers until the release registry passes — the
    five slices are a starting set, not assumed sufficient (31
    invariants remain in the registry;
    `ai_builder_critic_invariants.py:1823`).

### Execution order (v10.2 — the ONE canonical order; steps 0–0.8 of
### the v9 order are COMPLETE; dependencies hold)

1. **CP8b**, then **CP8c** — instrument completion. The CP8 barrier
   HOLDS: no builder product work and no candidate measurement until
   both land (never an enumerated slice list). CP8b derives every
   instability ceiling and checkpoint size from the FINAL frozen
   manifest and pins the rounding rule; this owner never duplicates
   those numbers.
2. **CP6** (release-critical: authoring accepts what runtime rejects —
   a deterministic published-flow defect the suite cannot price because
   it does not execute flows) and the **`json_to_text_summary`
   removal**. Disjoint files: may run as parallel worktrees, land in
   sequence.
3. **CP-D3** — one verified deletion; a cohort probe re-measures the
   mixed-audio family.
4. **CP2**, then **CP1** — evidence rank: CP2 has 6/6 deterministic
   receipts (`cp0-matrix-freeze.md` §CP2 step 1); disjoint files. CP1
   carries D7 only if its receipt proves the slot variant.
5. **CP-ADMIT implementation** — only after CP2+CP1 land AND its
   per-code dependency table exists; the table and design gate run in
   the analysis lane during steps 3–4.
6. **CP2b** (parse attribution; gates CP3 and CP5 by ruling), then
   **CP3** (+D2 +D4 +D8 +D10 — the schema materializer and the
   compile-context materializer are ONE lifecycle fix).
7. **Tranche checkpoint** — exploratory final-frozen-manifest ×3 after
   CP1–CP3, per the standing gate.
8. **CP4 → CP5**, then **CP-EDIT**, **CP-D6**, **CP9b** (only if
   decision 7 chose the product branch), **CP7**; the post-CP5
   re-attribution loop runs alongside.
9. Runtime lane, parallel throughout, own peer session
   (`flows-runtime-readiness`): **L2** (rescoped — see the launch
   stream), then **L1b → L3** (they collide on
   `docs/deployment/docker-compose.yml`, so they sequence), then **L5**
   as the terminal evidence slice.
10. Post-program: **PKG**, per `docs/flows/package-layout.md`.

Receipt tasks (analysis lane, any time): D5 reachability, D7
occurrence, the critic disposition table.

Maintainability rulings bind every slice: ownership transfers delete
their old path, tests die with their owners, no splits for their own
sake.

### Launch stream (parallel; a RELEASE GATE, not a lower tier)
- [x] L1a Topology verification — LANDED `8df804213` (gate green 8)
    ORIGINAL SPEC: (SPLIT + TRIMMED, iteration 34): the
    release artifact `docs/deployment/docker-compose.yml` already
    owns the three roles (execute, maintenance with
    `FLOW_CELERY_WORKER_ROLE=maintenance`, beat) with
    `restart: unless-stopped` — verify rather than build. Remaining
    deltas only:
    (a) QUEUE-NAME OWNERSHIP — one source of truth shared by producer
        and consumer config; the orphan incident was consumer-topology
        drift. Deployment declares a per-service ROLE and the settings
        own the names.
    (b) BEAT SINGLETON — NOT A GOAL of this slice and nothing is
        claimed about it: `container_name` only prevents a collision
        within one compose project, so a real guard (lease or advisory
        lock) needs its own design.
    ALL healthchecks — container-native and operator surfaces — belong
    to L3 alone.
    Devcontainer parity (three roles instead of `sleep infinity`) is
    developer ergonomics under the scoped 2026-08-10 permission — off
    the release critical path.
    DELETED as already shipped (verified `worker/celery/app.py:33`):
    prefetch-1, acks-late, reject-on-worker-lost. That trio + the
    status/revision CAS (`flow_dispatch.py:89`) IS the deliberate
    crash-safety design: the database owns execution eligibility and
    at-least-once broker delivery is a normal input, not a second
    lifecycle owner. `acks_late` stays untouched; any future change
    needs a process-crash matrix (before claim / after claim / during
    shutdown) first.
- [ ] L1b Immutable release identity (NEW, iteration 34): production
    reads the baked release manifest first — `GIT_COMMIT` is only a
    fallback (`main/config.py:193`) — while every deployment role
    ships mutable `:latest` images. Pin the COMPLETE base-stack
    image set by immutable digest — backend roles AND traefik,
    frontend, pgvector, redis, init (the deployment compose still
    carries `traefik:v3`, `:latest`, `pgvector:pg16` mutable tags) —
    plain digest-pinned compose variables, no release-manifest
    framework; verify the baked version; L5 records the full resolved
    digest set for rollback. Runtime `GIT_COMMIT`
    stamping remains a DEVCONTAINER-ONLY mechanism and is deleted
    from the production plan.
- [x] L1c Capacity envelope — LANDED `355ad6f68` (gate green 8)
    ORIGINAL SPEC: (NEW, iteration 34): max_connections=300
    was a dev-incident value, not policy — the configured envelope is
    already 3 HTTP workers × 30 pool (`run.sh:39`,
    `main/config.py:271`) + 2 celery roles × 4 processes × 30
    (`flows/runtime/cli.py:23`). Set max_connections in tracked deployment
    config (never a volume-local ALTER SYSTEM) to cover the shipped
    configured maximum with headroom; prove with a clean-volume rebuild
    in an ISOLATED disposable compose project (temporary project name +
    fresh volumes, validated then deleted) — never against production
    or development volumes. L5 verifies the envelope under load.
    DESIGN OF RECORD: each backend, ARQ and Celery WORKER process owns
    an independent pool (beat opens none; db-init uses one transient
    connection), so demand is the sum across roles, and every role
    reads `env_backend.env` so a tuning profile raises the celery pools
    too. The aggregate budget TABLE has one owner —
    `docs/deployment/env_backend.template` — and is not duplicated
    here: the shipped default configures a maximum of 360, so
    `max_connections=400` covers it plus 3 reserved slots and headroom;
    Large (600) is deliberately not covered and belongs behind a
    pooler. Pool right-sizing waits for L5's measured peak checkouts.
    The slice changes no pool, no concurrency and no code path.
- [ ] L2 Provider failure typing (RESCOPED, drift audit 2026-08-10 —
    two of the three original sub-claims were ALREADY SHIPPED and the
    real defect is broader than throttling). Verified: fail-fast is
    already in place (`litellm_runtime_config.py:35` forces
    `num_retries=0`), and there is NO flow-level throttle retry to
    remove (the only retry in the step path is a JSON-mode capability
    fallback, `step_execution_runtime.py:501`). The ACTUAL defect: the
    flow runtime DISCARDS the transport's typed provider failures —
    `litellm_transport.py:184` already raises a typed
    `provider_rate_limited`, but `executor.py:1881-1938` has no branch
    for it, so a 429 (and `provider_unavailable` alike) collapses into
    generic `STEP_EXECUTION_FAILED`. The slice is therefore an ADAPTER
    from the transport's typed codes into `FlowApiErrorCode` — both
    codes together, not throttling alone. The D12 ruling binds: the
    canonical typed disposition stays in the model-provider domain and
    the Builder must not gain a third vocabulary. Blast radius is the
    largest of the runtime lane: taxonomy registry (hard-fails on a
    missing code), en+sv messages (exact key-set equality test),
    regenerated SDK artifacts, and the error-catalog docs contract.
- [ ] L3 Health (SOLE healthcheck owner, iteration 35):
    execution-consumer presence + beat freshness on the existing
    operator surface, plus every deployment-native container
    healthcheck for the celery roles. No new public liveness
    endpoint.
- [ ] L4 Object-content scope (DEFAULT OUT, iteration 33): the tracked
    deployment default keeps bounded durable content in PostgreSQL
    with no separate object store (`docs/deployment/README.md:68`),
    so the BASE launch ships PostgreSQL-only. Object storage becomes
    a conditional opt-in gate (attach worker to object_content_net +
    one read/write journey) ONLY if the user opts in.
- [ ] L5 Launch receipt: pool-budget arithmetic vs SHOW
    max_connections under bounded load + one queue-recovery smoke at
    launch concurrency + exact deployment revision/config identity +
    rollback/drain evidence.
Release requires L1a–L1c, L2, L3, and L5 resolved (L4 only if the
user opts object storage in) or explicitly descoped by the user.

### Standing rulings — NOT slices (adjudicated; apply when touched)
- END STATE (above) is adopted and binding: no second skeleton
  compiler; surface closure means OMIT AND REJECT, never omit-and-strip.
- NON-REPAIRABLE CODES — a PROPERTY invariant, not a count. Every
  non-model-repairable code must (a) depend only on server/external
  state or denote a compiler defect, (b) never consume a model retry,
  and (c) fail BEFORE provider use whenever its inputs are already
  server-known. "The list may only shrink" is REJECTED: new genuine
  external or user-decision failures may legitimately appear.
- PROVIDER-ERROR VOCABULARY (D12): the canonical typed disposition
  lives in the MODEL-PROVIDER domain; the Builder and the Flow runtime
  each map it into their own public contracts. L2 must not create a
  third vocabulary — the Builder already has its own
  (`ai_builder_error_contract.py:326` region) alongside the transport's
  (`litellm_transport.py:184` region).
- GOD MODULES — a split must earn its diff by ONE of three
  justifications, and NO standalone split slice exists in this program.
  (A) DELETION-FIRST: never restructure what a slice deletes —
  `ai_builder_critic_invariants.py` keeps its registry structure and
  loses content via the CPs. (B) CHURN × SLICE-TRAFFIC: only the three
  highest-churn files qualify (`ai_builder_assembly/create.py` 59
  commits, `ai_builder_create_compiler.py` 52,
  `planning_state_builder.py` 52), and the extraction IS the owning
  slice's work — CP-ADMIT extracts only the gates seam; the
  compile-context seam extraction IS the D10/CP3 materializer. (C)
  DEPENDENCY STRUCTURE: rides PKG, deferred.
  `planning_state_builder.py` and `ai_builder_conversation_metadata.py`
  are RECORDED SEAMS — module names, interfaces and caller-change
  analysis are produced at the owning slice's design gate, never
  pre-committed here. DO NOT SPLIT: `ai_builder_repo.py` (2095 lines
  but 15 commits — big and quiet), `ai_builder_router.py` (projection
  seam noted only), `ai_builder_slot_classification_contract.py` (1720
  lines, 10 commits — CP3 EXTENDS it), `ai_builder_error_contract.py`
  and `ai_builder_framework_policy.py` (declared constant tables; size
  is data, not complexity).
- PACKAGE RESTRUCTURE (PKG) is DEFERRED out of the active program.
  `docs/flows/package-layout.md` is the tracked standard and is
  explicit that layout decisions are not mass-move plans. A cycle-free
  import graph proves feasibility, not value, and restructuring
  mid-migration would invalidate every frozen file:line anchor in this
  program. Post-migration: only moves that shorten a DEMONSTRATED
  change path, one at a time, with the root-count guard lowered in the
  same commit. The SCC digest is the PKG design gate's first input —
  it is NOT an active evidence requirement and supplies no evidence for
  critic deletion or ownership transfers.
- NO PROSE POPULATION CONSTANTS: every checkpoint population is
  "final-frozen-manifest × N"; renderers may display the derived count.
  The stale "155" this program carried for days is exactly what the
  ruling prevents.
- PRERELEASE — NO COMPATIBILITY (user directive, restated
  2026-08-10; SCOPED in iteration 37): Flows and the Flow AI Builder
  have zero production users. No legacy paths, no
  backwards-compatibility shims, no deprecation cycles, no feature
  flags or rollout scaffolding, no version-keyed COMPATIBILITY
  readers/branches for prerelease Flow/Builder data. When a transfer
  lands, the old path is DELETED in the same slice, not retired
  gradually. Bigger refactors are affordable when they remove real
  complexity — the constraint is clean ownership, not continuity.
  Persisted prerelease data may be regenerated instead of migrated
  (the frozen evidence packet stays readable offline for
  attribution — analysis, not a product obligation), with
  zero-production-use evidence recorded before any destructive
  regeneration. EXPLICITLY PRESERVED (not compatibility): immutable
  published Flow versions (core domain invariant), FCM/protocol
  version stamps as identity, operational rollback, and the
  repository's protected historical-job reader (AGENTS.md).
- `planning_state_builder.py` split (3 owners + facade) only AFTER the
  ownership tranche settles. `step_input_resolution.py` splits when
  CP5 touches it. `step_execution_runtime.py` provider seam only if
  L2 changes provider behavior. `executor.py`: never split.
  `flow_run_repo.py` / `flow_models.py`: wait.
- `field_diagnostics`→`compile_diagnostics` rename, Slice-5 commit 2,
  and JSON fan-in: RE-ATTRIBUTE after CP1–CP3 (their cohorts may
  dissolve); implement only what survives re-attribution.
- Edit guards and compiler postconditions stay until their owner makes
  them unreachable; each CP names its deletions in advance.
- Tests are proportional to observable risk (user directive
  2026-08-10): test CORE functionality, not everything reachable.
  When a slice deletes an invariant, repair path, or behavior, the
  tests guarding it are part of that slice's deletion list and die in
  the same commit. New tests pin an attributed mechanism or contract
  — never one-per-code-path, never a sibling of an existing guard.
  The tests themselves stay simple: plain arrange-act-assert on the
  real contract; no elaborate fixture machinery, mock towers, or
  parametrization mazes where a direct case is clearer. Test cleanup
  rides each slice; no standalone test-audit slice.

### Parallelization map (what runs concurrently; worker worktrees)
Commit gates stay sequential per stream, but implementation and
analysis overlap. Lanes that can run AT THE SAME TIME:
- Lane A (analysis, no product code): CP0 matrix freeze + CP9a
  question-policy evidence packet (delivered before the decisions
  and CP8) + CP2 step 1 attribution table + CP4 diagnosis — all
  offline over the frozen packet; independent workers or scripts.
- Lane B (builder code): CP1 (owner: `planning_state_builder.py`
  merge guard) and CP2 step 2 (owners: create proposal/preparation)
  touch DISJOINT files — separate worker worktrees in parallel once
  their design gates pass; land in sequence. HARD BARRIERS: no builder
  product code starts until (a) the user decisions are answered
  and (b) CP8 has landed, so verdict semantics are pre-registered in
  code before any product change or candidate measurement. Analysis
  (Lane A) and the runtime stream (Lane D) may proceed meanwhile.
- Lane C (early design gates): CP5's provider strict-tool probe and
  placement decision need no code and can be adjudicated while Lane B
  implements; CP3's delta-envelope design gate needs only CP0's
  archetype placement rows.
- Lane D (runtime stream): parallel with ALL builder work — different
  files, own peer session (`flows-runtime-readiness`), own worker
  worktrees. INTERNAL ordering corrected by the drift audit
  (2026-08-10): L1b and L3 COLLIDE on
  `docs/deployment/docker-compose.yml` (L1b rewrites nine `image:`
  lines, L3 adds `healthcheck:` blocks to four interleaved services),
  so they SEQUENCE — L1b first, it has near-zero blast radius. L5 is
  terminal: it consumes L1b's resolved digests and L3's probes. Only
  L2 is genuinely independent of the other three, so the true parallel
  pair is L2 with (L1b or L3), never L1b with L3. Note four of six
  launch slices now converge on that one untested compose file — a
  known risk L5's launch receipt is the check for. L3 will also touch
  `runtime/cli.py`, which L1a rewrote: same owner, no conflict, keep
  the runtime session sequential.
Dependencies that stay hard (v10.2 — the v9 prerequisites CP0 → CP9a
evidence → the three user decisions → the corpus freeze are all
COMPLETE): CP8b and CP8c before ANY builder product code or candidate
measurement (pre-registration integrity); CP2 step 1 before CP2 step 2;
CP2 and CP1 before CP-ADMIT implementation, and CP-ADMIT's per-code
dependency table before its design gate closes; CP2b before CP3 and
CP5; CP4 attribution before any CP4 fix; the tranche checkpoint after
CP1–CP3 land; the `json_to_text_summary` removal writes the
matrix-state revision CP8b's row 14 reads. One live worker per session
name; the orchestrator judges every diff and owns all git.

### Measurement cadence
Cohort probes (3 reps, named cohorts) per slice; exploratory
final-frozen-corpus ×3 at
the tranche gate; the N=5 release evaluation at the release gate
(detection power, not certification power), repeated after every
material post-gate change; suite runs ≥45 min
apart (provider limits).

## Operating protocol (for any agent continuing this)

- Branch: commit/push ONLY `refactor/flows-clean` on eneo-ai/eneo.
  Never stage the user's protected files (`SolReview/`,
  `docs/adr/marketplace-*`, `.devcontainer/`, `goal.md`,
  `notes/handoff.md`, `notes/hermes-*`, `state.yaml`,
  `frontend/package.json`). ONE scoped exception, granted
  2026-08-10: `.devcontainer` compose changes for the three-role
  dev-parity topology (L1a) may be edited and committed; every other
  protected path stays untouchable, and pre-existing devcontainer
  content must survive.
- Commits: `ENEO_DEVCONTAINER_NAME=developz_devcontainer-eneo-1
  git commit ...`; the container-side pyright pre-commit checks the
  DEPLOYED tree — if it OOMs (exit 247), run pyright manually on the
  changed files and `SKIP=pyright`, stating so in the message.
- Codex loops: `codex-peer-loop` session `flow-122-strategy`
  (builder; next iteration = check latest artifact under
  `.codex/artifacts/`), session `flows-runtime-readiness` (runtime).
  Implementation via `codex-implement-loop` workers in isolated git
  worktrees; the orchestrator judges every diff, re-runs decisive
  tests, owns all git. Peer-gate designs before code and commits
  after landing.
- Validation: `cd backend && uv run pytest tests/unittests/flows/ -q`
  (currently ~6445 green); ruff check/format + pyright
  (`--pythonpath .venv/bin/python`) on exact changed paths only.
- Measurement: harness + protocol in `conformance-program-plan.md`.
  Deploy bracket before gated runs: sync `/workspace` +
  `/tmp/eneo-clean` in container `developz_devcontainer-eneo-1` to the
  exact SHA, restart backend with fresh `GIT_COMMIT`, verify
  `/version`; celery via `cd /workspace/backend && bash run.sh` inside
  the worker/beat containers (maintenance consumer:
  `FLOW_CELERY_WORKER_ROLE=maintenance`); NEVER bare
  `docker restart` (kills the processes; safe pkill pattern
  `[b]in/celery`). Postgres max_connections=300 is a
  TEMPORARY measurement-environment value (volume-local); never
  promote it — L1c derives and owns the calculated launch envelope.
  Evidence packets:
  `/workspace/.codex/artifacts/slice2-evidence-manifest-20260810/`
  (self-replaying, hashed) and `evidence-freeze-20260809/`.
- Night window: no work 01:00–06:00 Stockholm (Codex included; no
  launches after ~00:10).

## Pending user decisions
1. ~~Permission to edit `.devcontainer/docker-compose.yml` for the
   durable three-role topology (L1)~~ — GRANTED 2026-08-10, scoped to
   the topology work (now dev-parity only; release proof targets the
   deployment compose).
2. ~~Object storage~~ — DECIDED 2026-08-10: PostgreSQL-only base
   launch; L4 stays dormant until the user opts in later.
3. ~~Sign-off~~ — APPROVED 2026-08-10, start held: execution begins
   only on the user's explicit go.
4. ~~§6a conformance scope~~ — DECIDED 2026-08-10 19:35: TRAJECTORY.
   Release rests on the reachable registry rows; conformance is the
   north star with the FROZEN completion condition (registry row 5
   PASS by CP8's arithmetic + ≤10% conformance-unstable cases); the
   9/10 claim is withheld until then and the program continues after
   release. No rebaseline was needed (see decision 7 — the product
   branch was chosen, so the 19 contracts stay frozen).
5. ~~§6b unmeasured branches~~ — DECIDED 2026-08-10 19:38: SPLIT.
   `audio_transcription` is COVERED (2–3 battle cases written,
   contract-hashed and frozen at step 0.8 before CP8);
   `json_to_text_summary` is REMOVED — the cascade branch is deleted
   and that tuple rejects explicitly (builder product code, rides
   behind CP8), and its matrix row is dropped from the supported set.
7. ~~Question policy~~ — DECIDED 2026-08-10 19:38: the BALANCED RULE.
   Ask what shapes the flow (architectural slots, docx mode when the
   terminal is docx); assume visibly what is optional — the
   runtime-metadata question disappears on open prompts in favour of
   a visible, overridable assumption, and stays available when the
   prompt mentions metadata. CP9b implements with its frozen
   acceptance criteria; the 19 battle contracts stay frozen (product
   branch), so NO rescoring and NO rebaseline.
6. OPTIONAL (CP0 §6c) — corpus expansion: precision only; blocks
   nothing.
