# Eneo Flows + Flow AI Builder — Master Program (living document)

Status: EXECUTION PHASE, program **v10.3** (v10.2 architecture retained;
post-merge order adjudicated 2026-08-11 by the separate Fable runtime
and Builder sessions, both green at 8). LANDED: CP0 evidence, CP8a–c,
CP6, the unsupported JSON-to-text removal, CP-D3, L1a, L1c, and the
develop-to-Flows integration at `b9c0aa238`, FLOW-AUTH, and
CP-ADMIT-0, and CP2 terminal ownership consolidation. All three user
decisions stand (TRAJECTORY / SPLIT /
BALANCED).

v10.2 REPLACED v9.8 after three source-verified audits — structural
debt, a systematic dual-ownership inventory, and runtime-slice drift —
established that the program owned the measured failure FAMILIES but
not the structural DISEASES behind them. What changed: an adopted END
STATE, a dual-ownership ledger with load-bearing statuses, five new
slices, an evidence-ranked order, and a god-module doctrine under which
no standalone split slice exists.

v10.3 does not redesign that end state. It records what landed, closes
two verified pre-production defects before the next ownership transfer,
moves the already-chosen BALANCED question behavior before the tranche
that measures it, and makes public-contract and launch work explicit.

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

## Where we are (2026-08-11; product-code baseline `b9c0aa238` — this
## document evolves past it, see git log for the doc HEAD)

- Three checkpoints: deaths 50→30→27; architecture kills 13→10→2;
  provider wedges 22→6→2; conformance 149→162→170 of 465 (formally
  no_measurable_change; 81 cases in the then-frozen manifest were
  unstable run-to-run).
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
- Instrument barrier: CP8b/CP8c are landed, the frozen CP0 receipt
  still replays exactly, acquisition bundles seal derived observations,
  and release verdicts fail closed on final identity. The first completed
  post-integration runtime sentinel exposed one instrument defect: raw
  fixture-byte hashes were compared with the extracted-text hashes the
  runtime actually consumes. The harness now seals those as distinct
  identities, validates runtime lineage against the uploaded projection's
  size, and versions the corrected identity semantics; gate arithmetic is
  unchanged.
- Product changes since the barrier: authoring rejects unindexed array
  paths, the unmeasured JSON-to-text tuple rejects explicitly, and the
  mixed-audio topology guards no longer re-infer create intent. Fully
  resolved unsupported Builder architectures now return a typed,
  localized terminal refusal; server-known choices consume no provider
  call, and create mode offers the existing fresh-session recovery.
  Create compilation now takes its terminal type only from the committed
  architecture; conversation intent remains an edit-only concern, and a
  create postcondition mismatch is a typed compiler defect rather than a
  model-repair instruction. On the comparable 155-case population, its N=1
  smoke moved accepted plans from 87.0% to 86.2%, first-pass plans from
  69.1% to 65.9%, conformance from 39.0% to 41.5%, and Builder errors from
  5.8% to 3.9%. A targeted repeat returned 10 of 14 apparent first-pass
  losses to first pass and recovered all six apparent acceptance losses,
  so they are treated as model variance rather than repair targets. Both
  previously stable TEXT-terminal deaths now produce plans; none of the
  new failures used CP2's terminal-mismatch code.
- Platform integration: current develop storage, knowledge/internal
  tools, API, SDK and frontend work is merged without weakening Flow
  governance. Internal-tool approval now trusts runtime provenance,
  not tenant-controlled server names.
- Flow authorization: service-key principals remain scoped to their own
  runs and subject to explicit evidence capability even when the key
  carries the synthetic tenant-admin permission. Human tenant-admin
  behavior is unchanged. The affected Flow suite is 6519 passed,
  10 skipped, 1 xfailed.

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
| D1 | Terminal output type (create) | SELF_CHECK | CP2 (`CreateCompileContext.final_output_type` → create postcondition; conversation derivation isolated to edit) |
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
- [x] CP8b sealed acquisition and receipt-owned suite verdict
      (`832095bd8`; Claude gate green 8)
- [x] CP8c bounded provider-fault remeasurement (`07fa4ed42`; Claude
      gate green 8)
- [x] CP6 authoring/runtime array-path parity (`269bc55ee`; Claude
      gate green 8)
- [x] Unsupported JSON-to-text architecture removal (`92166d924`;
      frozen matrix-state revision retained)
- [x] CP-D3 mixed-audio create re-inference deletion (`ad10a647b`;
      14-case audio cohort x3 produced 42 sealed observations)
- [x] Current develop integration (`b9c0aa238`; Claude iterations 93
      and 95 green 8; one Alembic head, deterministic OpenAPI
      regeneration, provenance-owned internal-tool trust)
- [x] v10.3 production-order review — separate Fable runtime iteration
      2 and Builder iteration 2, both green 8
- [x] FLOW-AUTH service-key evidence and run-list access remain
      principal-scoped even when the key carries tenant-admin
      permission; human tenant admins remain unchanged (Claude
      iteration 97 green 8)
- [x] CP-ADMIT-0 typed unsupported-architecture refusal: one derivation
      and action-policy path, one shared structured-answer echo owner,
      no provider or planning mutation for server-known choices, and
      fresh-session recovery in create mode (Claude iteration 100
      green 9; Codex value gate iteration 2 green 8)
- [x] CP2 create terminal ownership: normal and scoped create paths use
      the already-materialized `CreateCompileContext.final_output_type`;
      all create terminal types retain one compiler postcondition, while
      true edit conversation inference and repair behavior remain intact
      (Claude iteration 102 green 9).
- [x] CP-ADMIT architecture-commit admissibility: four server-decidable
      contradictions now refuse before proposal generation through the existing
      action-policy and durable error lifecycle; compiler-only checks remain
      postconditions. The impossible review-conflict question direction was
      corrected to retain the defensive compiler postcondition rather than
      inventing a second checkpoint state or question path.

## The Ranked Program (v10.3 — execution phase; slice bodies carry
## their originating iteration tags)

### Gate inventory — owned by `cp0-matrix-freeze.md` §3
CP8 owns the release contract; this section points at the inventory it
satisfies. The inventory lives there and is authoritative. Do not
restate its numbers here.

The three user decisions are COMPLETE: TRAJECTORY, SPLIT
(`audio_transcription` covered and JSON-to-text removed), and BALANCED.
CP8b/CP8c are landed, so product work and named cohort probes may now
proceed under the pre-registered verdict semantics. The final-frozen
manifest, never a prose count, remains the population owner.
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
### commit-gated → proportionate live smoke)
- [x] CP0 Matrix freeze — analysis DONE 2026-08-10 (evidence + gate
    inventory; not a frozen statistical contract). Evidence, dispositions, corrected taxonomy and the
    gate INVENTORY live in `cp0-matrix-freeze.md`;
    clone-local hashed evidence packet
    `.codex/artifacts/cp0-freeze-20260810/` (manifest and digest live
    in the evidence owner; verify there, not here). The numbered
    execution order is the sole lifecycle owner.
- [x] CP8 Release-gate implementation — CP8b sealed each derived
    observation inside its bundle, bound suite acquisition verdicts to
    immutable receipt evidence, and reproduced every CP0 count
    (`832095bd8`). CP8c added bounded provider-fault slot
    remeasurement without changing frozen arithmetic (`07fa4ed42`).
    The pre-registration barrier is closed. A later live runtime proof
    corrected the harness's post-integration raw-fixture versus extracted-
    runtime identity comparison without changing the 14-row definitions:
    both identities remain sealed, runtime evidence stays fail-closed, and
    their semantics version prevents unlike receipts from being compared.
- [x] CP-ADMIT-0 Unsupported-architecture refusal (Fable Builder
    iteration 2): fully resolved unsupported tuples now produce one
    typed, localized terminal refusal. The existing derivation cascade
    remains the supportedness owner; action policy owns the legal
    refusal; SSE, generated SDK and web UI reuse their existing contract
    owners. Localized structured controls refuse before provider use or
    planning mutation, while genuine corrective text still reaches
    classification. Create mode reuses fresh-session recovery. No table,
    service, framework or module was added, and the later CP-ADMIT
    dependency-table transfer remains separate.
- [x] CP1 File-role flip closure (completed 2026-08-11). The margin
    regression is the task-14 case: repeated classification could reinterpret
    the same cited user message and replace an explicit role. The existing
    merge owner now applies monotonic precedence from evidence level and the
    complete citation source identity: a role cannot flip within one source,
    inferred evidence cannot downgrade an explicit role, and a genuinely new
    explicit source can replace the role and its evidence atomically. The
    earlier candidate ambiguity direction is retired: `candidate_roles` is a
    proposal hint, not a fail-closed selection state, and deterministic
    precedence leaves no unresolved merge state. A future user-resolvable
    ambiguity lifecycle would require its own product contract; CP1 adds no
    state, schema, question path, module or role-history store. The full Flow
    suite passes (6523 passed, 10 skipped, 1 xfailed), and the frozen
    465-observation receipt reproduces every CP0 count. The extra question
    round remains attributed to this case for the next permitted progress
    smoke rather than being guessed at from deterministic tests.
- [x] CP2 Terminal ownership consolidation (completed 2026-08-11):
    both create-only paths now consume
    `CreateCompileContext.final_output_type`; scoped plan revision reuses
    the context already built during request preparation instead of
    materializing another copy. The existing terminal postcondition
    checks every create output type, including TEXT, and reports any
    disagreement as typed `architecture_materialization_failed` with
    internal code `terminal_output_type_mismatch`; it cannot enter model
    repair. Conversation-derived terminal intent is named and retained
    only for true edit semantics, where the existing validation feedback
    remains. The frozen 465-observation receipt still reproduces every
    CP0 count, and the real negated-format regression now compiles the
    committed TEXT terminal. `flow_step_invalid` remains a separate
    heterogeneous family (`flow_validators.py:227`).
- [x] Edit aggregation-intent wiring correction (completed 2026-08-11):
    edit compilation now materializes the planning-state compile context once,
    reuses it for runtime input, and carries its typed aggregation intent through
    `CompiledProposal` into the existing contextual quality owner. The silent
    `linear` defaults at both severed boundaries no longer judge a committed
    compare edit with linear topology; the finalization wrapper now requires an
    explicit intent, and the redundant one-use runtime-input helper is deleted.
    One existing edit behavior test protects the carrier and one finalization
    behavior test protects plan persistence. The full Flow suite passes (6524
    passed, 10 skipped, 1 xfailed), and the frozen 465-observation receipt still
    reproduces every CP0 count. No helper, policy, schema or public contract was
    added.
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
- [x] CP6 Authoring rejects unindexed array paths — LANDED
    `269bc55ee`.
    (RELEASE-CRITICAL, direction FROZEN in v9.1 — "parity" alone could
    be satisfied by weakening the runtime, which is the wrong
    architecture): the runtime's numeric-index requirement
    (`variable_resolver.py:374`) is the correct semantic; authoring's
    lenient default (`ai_builder_json_schema_paths.py:9`) and its
    backwards-compat mode are deleted under the prerelease no-compat
    ruling, and a behaviour test proves an invalid path cannot be
    published.
- [x] CP-D3 Mixed-audio create re-inference — LANDED `ad10a647b` as
    DELETION, not
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
- [x] CP-ADMIT Architecture-commit admissibility (completed 2026-08-11).
    The design gate classified every member of
    `_NON_MODEL_REPAIRABLE_ARCHITECTURE_FAILURE_CODES` by its actual inputs.
    Four server-decidable contradictions moved into the existing commit/action
    policy lifecycle before proposal generation:
    `assembly_unsupported_architecture_hints` reuses
    `unsupported_architecture`; a transcript checkpoint on non-audio input uses
    `transcript_checkpoint_requires_audio`; template-fill selection and
    readability use `template_attachment_selection_invalid` and
    `template_attachment_unreadable`. The exact architecture-hint predicate was
    moved to the derivation owner and is reused by assembly; checkpoint and
    template predicates remain in their existing contract owners. One
    generalized `RefuseArchitectureCommit` decision carries the canonical
    public error code through the existing durable SSE/replay path. Structured
    server-known choices refuse without a proposal call or planning mutation;
    genuine corrective text still reaches classification.

    The following remain compiler or assembly postconditions because they need
    the compiled semantic topology or bindings:
    `assembly_document_report_compose_topology_missing`, both
    `flow_input_schema_*` codes, `section_writer_structured_source_ambiguous`,
    `terminal_output_type_mismatch`, and `template_placeholder_unresolved`.
    `assembly_document_report_review_mode_conflict` also remains a defensive
    non-repairable postcondition: production create strips model-authored
    review modes and `PlanningState` permits one checkpoint intent per producer,
    so no typed conflict exists from which to ask the frozen candidate user
    question. Inventing an ambiguity state would duplicate checkpoint ownership.
    No module, proposal skeleton, repair path, persistence schema or frontend
    workflow was added; two proposal-layer tests for the transferred hints
    failure were deleted in favor of the admission owner, one retained compiler
    postcondition, and one representative planner lifecycle proof.
- [x] Edit aggregation-intent wiring correction (severed from
    CP-EDIT): reuse the planning-state compile context, carry its
    `aggregation_intent` through the existing compiled proposal, and pass it
    into the existing contextual quality owner. A compare edit is no longer
    judged with the default linear topology. The redundant one-use helper was
    deleted; no helper or policy was added.
- [ ] CP-EDIT Edit-path terminal-type ownership (design gate first):
    ONE conversation-derivation owner with ONE precedence rule — today
    `ai_builder_proposal_policy.py:265` (latest message first) and
    `ai_builder_plan_quality_critic.py:85` (committed slot first)
    disagree and feed two different guards. The smaller
    `aggregation_intent` wiring defect lands earlier and is not cargo
    for this redesign.
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
- [x] `json_to_text_summary` REMOVAL — LANDED `92166d924` (user
    decision §6b SPLIT):
    delete all THREE live declarations — the derivation cascade branch
    (`ai_builder_architecture_derivation.py:186` region), pattern
    metadata (`pattern_registry.py:210` region), and assembly's
    supported set (`ai_builder_assembly/create.py:118` region) — make
    the tuple reject explicitly, add the product behavior test, drop
    the supported matrix row, AND write the matrix-state revision that
    CP8b's row 14 reads (receipt revision must match it).
- [ ] Critic disposition table (RECEIPT TASK; must close before
    CP4/CP5): all 31
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
- [x] CP9a Question-policy EVIDENCE PACKET — COMPLETE; it produced the
    BALANCED decision. The forbidden-question and stall families were a
    PRODUCT-POLICY-VS-CASE-CONTRACT CONFLICT with no presumed side.
    Verified mechanics and receipt facts live in the evidence owner
    (`cp0-matrix-freeze.md` §8b); in short, the product deliberately
    asks `runtime_metadata_fields` on open interviews (issue created
    when metadata absent, no normal-path assumption case, behaviour
    tests expect the question) while 19 battle contracts forbid it.
    The chosen product branch keeps the contracts frozen. CP9b must
    prove that the question disappears on open prompts, the no-metadata
    assumption is visible through the existing assumption seam, and the
    user can override it. Any later instrument correction invalidates
    earlier candidate receipts and re-enters pre-registration.
- [ ] CP9b Question-policy product change (REQUIRED by the completed
    BALANCED decision): implemented before CP3 and the ownership
    checkpoint, inside
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
- [x] Decision branches resolved. TRAJECTORY keeps registry row 5
    non-gating for release, but release eligibility is not program
    completion: the 9/10 claim remains withheld until row 5 reaches
    PASS under CP8's cluster-aware arithmetic and at most 10% of the
    final manifest's cases are conformance-unstable across repetitions.
    SPLIT covered `audio_transcription` with pre-registered cases and
    removed `json_to_text_summary`; silence is not a fallback.
- [ ] Ownership-tranche gate: exploratory final-frozen-manifest ×3
    checkpoint after CP1–CP3 and CP9b land. The release gate is a
    separate N=5 release
    evaluation (CP0 established that repetitions supply instability
    DETECTION, not certification power), repeated after every material
    post-gate change.
- [ ] Post-CP5 re-attribution loop: rerun attribution and continue
    ownership transfers until the release registry passes — the
    named slices are a starting set, not assumed sufficient. The live
    registry owner is `ai_builder_critic_invariants.CRITIC_INVARIANTS`.

### Execution order (v10.3 — the ONE canonical order)

1. **Foundation complete:** CP8b → CP8c → CP6 → JSON-to-text removal
   → CP-D3 → current develop integration. Frozen arithmetic did not
   change; named cohort measurement is now permitted.
2. **FLOW-AUTH complete** — the existing access policy now keeps
   tenant-admin service keys inside the service-principal branch for
   evidence access and run listing.
3. **CP-ADMIT-0 complete** — typed unsupported-architecture refusal
   before provider use or mutation; corrective text remains admissible.
4. **CP2, CP1 and edit aggregation-intent wiring complete** — the ownership
   defects have deterministic receipts; CP1 did not absorb D7, and the bounded
   edit wiring correction remains separate from CP-EDIT.
5. **CP-ADMIT complete** — its per-code dependency table moved only the four
   server-decidable contradictions; compiled topology and binding checks remain
   postconditions.
6. **CP2b next** — parse attribution; it gates CP3 and CP5.
7. **CP9b** — land the already-chosen BALANCED question behavior so
   the tranche measures the product behavior intended for release.
8. **CP3** (+D2 +D4 +D8 +D10) — one proposal-schema and
   compile-context materialization lifecycle, not two abstractions.
9. **Ownership-tranche checkpoint** — exploratory
    final-frozen-manifest ×3 after CP1–CP3 and CP9b.
10. **Critic disposition receipt**, then **CP4 → CP5**, **CP-EDIT**,
    **CP-D6**, **CP7**; the post-CP5 re-attribution loop runs alongside.
11. **Public contract lane:** after FLOW-AUTH, the retention bound and
    current-source Flow docs/OpenAPI accuracy slices may proceed in
    sequence, parallel to Builder ownership work. The Builder SDK,
    pagination and showcase-doc slice starts only after step 9 and
    must land before showcase/release.
12. **Runtime lane**, parallel throughout in its own Fable/peer
    session: **L2 → L1b → L3 → L5**. L1b and L3 sequence because they
    share the deployment compose; L5 is terminal evidence.
13. **Release evaluation:** final-frozen-manifest N=5 only at the
    release gate, repeated after every material post-gate product
    change. The full-corpus run is not an instrument-progress check.
14. Post-program: **PKG**, per `docs/flows/package-layout.md`.

Receipt tasks: D5 reachability and D7 occurrence may run in the
analysis lane. The critic disposition table is not "any time"; it must
close before CP4 or CP5 within step 10.

Maintainability rulings bind every slice: ownership transfers delete
their old path, tests die with their owners, no splits for their own
sake.

### Public contract and documentation stream (pre-showcase)

- [x] FLOW-AUTH Evidence capability enforcement: service-key own-run
    and `flow_evidence` checks precede the human tenant-admin bypass in
    `FlowRunAccessPolicy`. Reuse the existing capability resolver and
    denial contracts. Tests: tenant-admin service key with no evidence
    capability cannot view or raw-export; no service key can access a
    non-matching run; human tenant-admin behavior is unchanged. No new
    policy layer or permission vocabulary.
- [ ] FLOW-RETENTION Contract bound: apply the existing strict
    `MIN_RETENTION_DAYS`/`MAX_RETENTION_DAYS` range to
    `run_debug_evidence_days` in public and update schemas. Keep this
    behavior change separate from documentation-only metadata.
- [ ] FLOW-DOC Current-source accuracy: re-verify the 2026-08-11
    endpoint sweep against current `eneo` owners and apply only facts
    that still hold. Correct consumer authentication, nested step
    inputs, review/rerun lifecycle, evidence export, Celery topology,
    retention precedence, links and OpenAPI examples. The old-branch
    patch is specification evidence, never a patch to apply blindly.
    Prove documentation-only OpenAPI edits preserve paths, operations,
    required fields and property sets.
- [ ] BUILDER-API Public authoring contract (after the ownership
    tranche): add the existing retry-safe plan-create operation to the
    required OpenAPI path/operation set; expose one `aiBuilder` SDK
    facade that reuses generated types and typed SSE events; make the
    silent recent-20 session list explicitly bounded and pageable so
    the next page is reachable. Add one compiled consumer example and
    proportionate behavior tests, not a route-by-route matrix. Public
    docs explain architecture-shaping questions, visible reversible
    defaults, and authoring cost versus repeated runtime cost.

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
    (b) BEAT SINGLETON — deliberately not a product contract. Normal
        overlapping maintenance invocations are bounded by the worker
        pool; duplicate ticks add queue depth, not another lifecycle
        owner. Do not add a lease or advisory lock without a new
        receiver-facing product requirement.
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
    rollback/drain evidence. It also records the webhook contract beside
    the existing delivery constants: concurrency is per task invocation
    and the observed aggregate ceiling is maintenance-worker processes
    × per-invocation concurrency. One live HTTP-stub overlap proof
    observes maximum simultaneous requests, proves no duplicate while a
    claim is valid, proves a claim-lost deliverer cannot record an
    outcome, and permits the declared at-least-once redelivery after
    claim expiry. Cite existing proofs for the other maintenance tasks;
    do not build a five-task live matrix or a global semaphore.
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
- BUILDER FRESH-SESSION FENCING: backend locking already prevents
  competing active drafts, but the frontend driver does not expose
  session creation as pending state. If hardened, one driver-owned flag
  must fence every fresh-session control; do not add per-button flags.
  This non-blocking shared lifecycle P3 is not part of CP-ADMIT-0.
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
  The stale prose population count this program once carried is exactly
  what the ruling prevents.
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

### Parallelization map

One write-capable slice and one commit gate run at a time in each
stream. Read-only attribution can overlap implementation when it does
not inspect mutable candidate results:

- Builder: CP2 attribution may prepare the CP2 implementation; D5 and
  D7 receipts and CP4 diagnosis may run offline over the frozen packet.
  CP2 then CP1 still land in the numbered order even though their code
  owners are disjoint.
- Public contracts: FLOW-RETENTION and FLOW-DOC may proceed after
  FLOW-AUTH, in sequence and independently of Builder ownership work.
  BUILDER-API waits for the ownership-tranche checkpoint.
- Runtime: L2 may overlap Builder work. L1b, L3 and L5 remain sequential
  because L1b and L3 share the deployment compose and L5 consumes both
  outcomes.

Dependencies that stay hard (v10.3): FLOW-AUTH before Flow public
contract work; CP-ADMIT-0 before the next Builder ownership transfer;
CP2 step 1 before CP2 step 2; CP2 and CP1 before full CP-ADMIT, and its
per-code dependency table before that design gate closes; CP2b before
CP3 and CP5; CP9b before CP3 and the ownership checkpoint; the
critic disposition receipt before CP4 or CP5; CP4 attribution before a
CP4 fix. CP8b/CP8c and the JSON-to-text matrix-state revision are
completed historical prerequisites, not active blockers. The
orchestrator verifies every diff and owns all git.

### Measurement cadence
After a material Builder ownership slice, use one repetition of the
final-frozen manifest as the broad progress smoke; derive its population from
the tracked manifest rather than a prose constant (currently 158 cases). Use
a smaller named N=1 cohort when the change is genuinely narrow or when
diagnosing a specific failure. N=1 detects deterministic regressions and new
failure families but makes no stability claim. Run the final-frozen manifest
×3 at the ownership-tranche gate, then N=5 at the release gate (detection
power, not certification power), repeated after every material post-gate
change. Suite starts remain at least 45 minutes apart for provider limits.
This cadence replaces per-slice cohort ×3 by user decision on 2026-08-11.

## Operating protocol (for any agent continuing this)

- Branch: commit/push ONLY `refactor/flows-clean` on eneo-ai/eneo.
  Never stage the user's protected files (`SolReview/`,
  `docs/adr/marketplace-*`, `.devcontainer/`, `goal.md`,
  `notes/handoff.md`, `notes/hermes-*`, `state.yaml`,
  `frontend/package.json`). ONE scoped exception, granted
  2026-08-10: `.devcontainer` compose changes for the three-role
  dev-parity topology (L1a) may be edited and committed; every other
  protected path stays untouchable, and pre-existing devcontainer
  content must survive. The historical L1a exception has landed; it
  does not authorize later devcontainer changes.
- Commits: set `ENEO_DEVCONTAINER_NAME` only to a validator whose
  `/workspace` bind source is this exact checkout (currently
  `eneo-flows-clean-pyright`). `developz_devcontainer-eneo-1` mounts a
  different checkout and is invalid for this branch. The container-side
  pyright hook must inspect the candidate tree. If it OOMs (exit 247),
  run pyright manually on the exact changed files and use
  `SKIP=pyright` only with that evidence recorded.
- Peer review: Claude reviews every stable pre-commit candidate in the
  resumable `flow-122-strategy` session; continue its recorded
  iteration sequence and require green at 8 or higher. Fable is for a
  named architecture decision, not routine commit review. The
  orchestrator verifies each finding in current source, reruns decisive
  tests, and owns all git.
- Validation: `cd backend && uv run pytest tests/unittests/flows/ -q`
  (current baseline: 6524 passed, 10 skipped, 1 xfailed); ruff
  check/format + pyright
  (`--pythonpath .venv/bin/python`) on exact changed paths only.
- Measurement: harness + protocol in `conformance-program-plan.md`.
  Every live run uses a clean tracked source at the exact candidate SHA;
  never borrow `/workspace` from another branch checkout. Restart the
  backend with fresh `GIT_COMMIT` and verify `/version`; celery runs via
  `cd /workspace/backend && bash run.sh` inside the worker/beat
  containers (maintenance consumer:
  `FLOW_CELERY_WORKER_ROLE=maintenance`); NEVER bare
  `docker restart` (kills the processes; safe pkill pattern
  `[b]in/celery`). Postgres max_connections=300 is a
  TEMPORARY measurement-environment value (volume-local); never
  promote it — L1c derives and owns the calculated launch envelope.
  Historical evidence packets are read-only in the separate
  `developz_devcontainer-eneo-1` evidence host, not a validation source:
  `/workspace/.codex/artifacts/slice2-evidence-manifest-20260810/`
  (self-replaying, hashed) and
  `/workspace/.codex/artifacts/evidence-freeze-20260809/`.
- Night window: no work 01:00–06:00 Stockholm (Codex included; no
  launches after ~00:10).

## Recorded user decisions
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
6. OPTIONAL (CP0 §6c) — corpus expansion: precision only; blocks
   nothing.
7. ~~Question policy~~ — DECIDED 2026-08-10 19:38: the BALANCED RULE.
   Ask what shapes the flow (architectural slots, docx mode when the
   terminal is docx); assume visibly what is optional — the
   runtime-metadata question disappears on open prompts in favour of
   a visible, overridable assumption, and stays available when the
   prompt mentions metadata. CP9b implements with its frozen
   acceptance criteria; the 19 battle contracts stay frozen (product
   branch), so NO rescoring and NO rebaseline.
