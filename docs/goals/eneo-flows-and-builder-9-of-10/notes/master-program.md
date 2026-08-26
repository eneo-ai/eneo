# Eneo Flows + Flow AI Builder — Master Program (living document)

Status: EXECUTION PHASE. This document carries what is left to do, the
decisions that bind it, and the rules for whoever continues. Work that has
landed is not listed here — it is in the git history of this file and of
`refactor/flows-clean`; the version before this one (`1b30f569d`) still holds
the full v10.13 done ledger and the completion narrative for all 79 landed
slices, should anyone need to reconstruct why something was built the way it
was.

## What is left — twelve slices

Each line names the slice and what it is for; the body under the same name in
The Ranked Program below carries the evidence, the gate and the acceptance
condition. The execution order there is authoritative — this table is a way in,
not a substitute for it.

| Slice | What it settles |
| --- | --- |
| FIELD-COLLIDE | One identity per confirmed runtime input, so a source-extracted comparison value cannot collide with a user-filled field. |
| STALL-POLICY | Adjudicate the 15 measured stalls by prompt quote, and separate clarification accounting from product economics. |
| RECOVERY | Deferred, evidence-decided: whether a classifier omitting a declared obligation at first emission needs its own recovery path. |
| FLOW-QUALITY | A bounded, reporting-only checkpoint on the quality of the Flow that gets produced — not just whether the plan was accepted. |
| CP-EDIT | One owner and one precedence rule for terminal type on the edit path; two files disagree today. |
| CP-D6 | Commit-drift bypass, receipt-gated: one behaviour test at the decision-and-persistence exit. |
| CP7 | Attribute the validation repair triggers CP3's form-field family does not already own. |
| Remaining family assignments | Every measured failure family gets an assigned attribution slice; counts live in `cp0-matrix-freeze.md`. |
| Post-CP5 re-attribution loop | Rerun attribution and keep transferring ownership until the release registry passes. The named slices are a starting set, not assumed sufficient. |
| BUILDER-API | The public authoring contract: the plan-create operation in the required OpenAPI set, one `aiBuilder` SDK facade, and the session listing made explicit. |
| L4 | Object-content scope. Default OUT: the base launch ships PostgreSQL-only and object storage is a conditional opt-in gate. |
| L5 | Launch receipt: pool-budget arithmetic under load, queue-recovery smoke, exact deployment identity, rollback and drain evidence. |

Reading order for someone joining: this table, then THE END STATE (what
"done" means), then the dual-ownership ledger (where a single concern still has
two owners), then the slice bodies. The operating protocol at the end is
binding on anyone continuing the work, not background.

## Mission

Production-excellent Flow AI Builder and Flows runtime (9/10): no
errors, near-zero repairs on supported archetypes, plans that satisfy
what the user actually asked, bounded resources, provable recovery,
clean single-owner architecture. Evidence-first: no fix without an
attributed mechanism; no claim without receipts; the battle suite
over the FINAL FROZEN CORPUS (3 repetitions, margin 5, rescored-case
discipline) is the instrument. Population is always derived from the
frozen manifest, never restated as a prose constant.


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
| D2 | Proposal tool schema built at two sites | LAYERED — one prepared schema | CP3 prerequisite (`ProposalPrepared.proposal_tool_schema`) |
| D3 | Mixed audio+doc re-inference on create | TRUE | CP-D3 |
| D4 | Terminal step `output_type` still emit-able | LAYERED — create output mechanics are server-derived and the retired provider key is rejected | CP3 |
| D5 | Form-field placement A/B exclusion divergence | UNPROVEN divergence; multi-consumer reachability proven | receipt task + CP3 evidence |
| D6 | Commit re-derivation at persist | SELF_CHECK — keep `CommitDriftError` | CP-D6 (receipt-gated) |
| D7 | Classifier slot vs merged slot re-ask | UNPROVEN | receipt task |
| D8 | Runtime-metadata request re-derived | LAYERED — one confirmed field/purpose record and one final-topology placement owner | CP3 |
| D9 | Edit terminal type: two derivations, opposite precedence | TRUE | CP-EDIT |
| D10 | `CreateCompileContext` built 4–5× with different args | LAYERED — one prepared materialization | CP3 prerequisite (`ProposalPrepared.compile_context`) |
| D11 | `confirmed_form_field_incompatible` has divergent identity and failure owners | ATTRIBUTED HAZARD — all captured source-shadow failures are exact-name collisions | FIELD-COLLIDE; become LAYERED in that slice |
| D12 | Rate-limit vocabulary | HAZARD | ruling below; binds L2 |
| D13 | Send-turn context and policy relayed as optional kwargs with divergent fallbacks | HAZARD — router→service→planner is the only production chain, but service/planner can repeat preflight and planner can drop tenant budget settings | CP3 follow-up when that owner is next touched: pass one prepared context, require policies/limits and delete duplicate fallback/replay paths; no standalone cleanup slice |


## The Ranked Program (v10.6 — execution phase; slice bodies carry
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
Measured tranche status (2026-08-14): CT, AUDIO-ARCH and FIELD-COLLIDE are
integrated in the clean `36ec81f67` measurement lineage. The pinned-Luna
strict-tools probe passed. AUDIO-ARCH passed its tracked 3×3 live gate with 9/9
first-pass and conformance pass, and zero repairs. FIELD-COLLIDE remains
provisionally retained. Its exact nine-case cohort was recovered from the sealed
pre-candidate 0bf4 receipt using the pre-candidate collision-failure selection
rule: all 27 observations stayed accepted, first pass moved 6→26, repairs 21→1,
the 17 observed collision codes fell to zero, and all confirmed fields remained
present and bound. Conformance moved 8/27→6/27, so FIELD remains open rather than
claiming its flat-or-better quality guard. CT's structural work is retained, but
its semantic gate is open because the broad smoke exposed the citation
ownership defect below.

- [ ] FIELD-COLLIDE Confirmed runtime-input namespace closure (absorbs D11):
    project exact confirmed runtime-input identities and purposes into the one
    prepared proposal contract and require a distinct identity for a
    source-extracted comparison value. Consolidate effective input type and the
    create shadow postcondition under exact folded-name identity; delete the
    token-subset, label, prefix and context-token heuristic family. A residual
    provider-authored collision is repairable only because the reserved
    namespace is now observable. A genuinely server-injected collision is
    resolved by its injection owner and never consumes a model retry. D8's
    assembly placement owner is unchanged. The nine-case ×3 cohort must have
    zero normal-path collision repairs, preserve and place every confirmed
    field, and keep acceptance/conformance flat or better.
- [ ] STALL-POLICY Adjudicate the 15 stalls by prompt quote, then separate
    clarification accounting from product economics. Each stalled question is
    classified: (i) the prompt already settles the slot (e.g. a runtime-sample
    prompt says documents are uploaded at run time and the case forbids
    `primary_runtime_input`; a summary prompt names the uploaded decision as
    the input; a cyber-incident prompt states the transformation and the PDF)
    → PRODUCT-owned classifier/slot-resolution defect, attributed and fixed
    like any other family; (ii) the prompt genuinely leaves the choice open
    (`terminal_output` on "DOCX eller PDF"; purpose before disposition is
    intended precedence, `ai_builder_discovery_issue_rules.py` ~238, and the
    ambiguous-report case carries a stale expected question id) → intended
    clarification: the case allows the question (observation leaves the
    plan-eligible denominator) or scripts a genuine user choice (a different
    interaction; fresh captures required, offline re-evaluation is not
    evidence). Applied corpus-wide with the prompt quote (CP4 discipline),
    old/new denominators printed, published as a new rebased lineage — never
    counted as accepted-plan recovery and never before the broad comparison
    run on the unchanged corpus.
- [ ] RECOVERY (deferred, evidence-decided): whether classifier omission of
    a declared obligation at first emission (measured 1/3 on two nested
    cases; admission lossless; the confirmation turn re-emitted the names but
    the current-evidence guard rightly rejected a stale-cited delta) merits a
    separately gated recovery lifecycle is decided from the post-D1 broad
    measurement. Not a D1 prerequisite; no tombstones, recover operations,
    unions or name-length refusals exist in the active plan. If it is taken
    up, its gate must define the total wire/parser contract (empty, `null`,
    invalid citations, removals, cache and prompt-hash identity), the lanes
    it may run in, the carrier through the chained decision path, and the
    fail-closed confirmation behaviour, and it changes persisted named-result
    state only — CONFIRM-STABILITY's disclosure invalidates confirmation.
- [ ] FLOW-QUALITY Produced-flow quality checkpoint — bounded, reporting-only
    (user direction 2026-08-15: the Builder is the de-facto way Flows are
    created, edited and maintained, so the produced Flow must be excellent on
    every axis, not only accepted). Population: the plan-bearing observations
    of the sealed receipt (`eeb8371e8`: 389 of 474 — 368 first pass + 21
    repaired), never the whole slot count. One attributed report over that
    population, then specifically sliced follow-ups; this is a checkpoint that
    closes, not a permanent quality owner. Facts, from existing owners only:
    (1) *Questions* — already scored per observation (ids, count,
    first-question relevance v3, preferred/allowed/forbidden, repeated,
    reopened, min/max, stalls); the report adds one economics line (questions
    per accepted plan, by family). Wording is human-reviewed under the
    existing question owner with a receipt: one Swedish/English inventory of
    the surviving canonical questions showing each explains the consequence of
    the choice, uses plain municipal language and has matching translations
    (decision 8c).
    (2) *Input fields (inmatningsfält)* — the typed contract already carries
    field type, requiredness and `options` (`FlowInputFieldIntent`), and in
    create mode the server-owned compile context supplies the fields; the
    harness plan summary keeps only names, and the sealed corpus produced 182
    fields with zero options and has no option contracts, so "zero selects" is
    NOT yet attributable. Correction: extend `_summarize_plan` with the
    complete typed field facts (no second report schema) and author four
    focused case contracts — single-select with exact options, multiselect
    with exact options, required vs optional, and an open text field that
    must NOT become a select. Expected options are authored in the case, never
    inferred by the evaluator from prose.
    (3)+(4) *Underlag → text and run economy are ONE static topology report*,
    not a cost model: production already publishes `execution_shape` (model
    steps, transcription, deterministic, schema-constrained, mapped bounds —
    static facts, explicitly not provider-call estimates), and the harness
    already records input source, source refs, duplicate refs, implicit
    previous-step reads, primary-JSON-extraction and cleanup-chain metrics and
    enforces no duplicate source refs plus case-specific
    `max_all_previous_steps`. Report the factual vector per plan —
    `execution_shape`, raw-flow-input consumer count, `all_previous_steps`
    count, total/max source-ref fan-in, duplicate-ref count,
    post-extraction cleanup-step count — with no weighting, no scalar score
    and no ×1000 arithmetic. Measured runtime tokens are comparable only
    within the same case, model, build, inputs and runtime configuration
    (today three executions of one case), so lineage comparison uses a frozen
    executed cohort, never cross-case totals. Extract-once assembly defaults
    or new contracts are authorized only when an archetype-specific contract
    shows the extra read is avoidable without reducing output quality; no new
    critic, no prompt heuristic, no efficiency repair loop.
    Closure: the report is filed as a receipt with a family map; each family
    that names a product owner becomes its own slice with a predeclared
    cohort; the rest stays reporting.
- [ ] CP-EDIT Edit-path terminal-type ownership (design gate first):
    ONE conversation-derivation owner with ONE precedence rule — today
    `ai_builder_proposal_policy.py:265` (latest message first) and
    `ai_builder_plan_quality_critic.py:85` (committed slot first)
    disagree and feed two different guards. The smaller
    `aggregation_intent` wiring defect lands earlier and is not cargo
    for this redesign. Also confirm whether flow-level inline-citation
    capability is a domain invariant: CREATE derives the terminal-step bit,
    while the inspected final guard is per-step. Do not change EDIT citation
    behavior unless source attribution proves the asymmetry is reachable.
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
- [ ] Remaining family assignments (v9 — every measured family has
    an ASSIGNED ATTRIBUTION SLICE; product owners are established by
    attribution; counts live in `cp0-matrix-freeze.md`): output-contract schema → CP5; input-contract schema and
    expected_form_fields and unknown_form_field_refs_open and
    unplaced_form_fields → CP3; min_source_ref_steps and
    live_model_provenance_complete → CP7 (see its single definition
    above); long tail → the standing re-attribution loop.
- [ ] Post-CP5 re-attribution loop: rerun attribution and continue
    ownership transfers until the release registry passes — the
    named slices are a starting set, not assumed sufficient. The live
    registry owner is `ai_builder_critic_invariants.CRITIC_INVARIANTS`.

### Execution order (v10.10 — the ONE canonical order)

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
6. **CP2b complete** — parse attribution assigned the general schema failures
   to CP3 and CP5 without adding a case-specific repair path.
7. **CP9b complete** — omitted optional runtime metadata uses a visible,
   overridable assumption instead of another interview question.
8. **CP3 D8 complete** — one structured field-details owner and one
   final-topology assembly placement owner replaced the provider/heuristic
   paths; no second schema, classifier snapshot or compile-context owner.
9. **MEASURE-TRUTH complete** — deterministic attachment/outcome evidence,
   terminal-error identity and parse-subfamily causality are sealed.
10. **CT-STRUCTURAL, CT-CITATION and AUDIO-ARCH complete; FIELD-COLLIDE
    provisionally retained** — structural parse failures fell 12→1, citation
    repairs fell to zero, pure transcription reached 9/9 first pass and the
    complete ×3 had zero citation or collision repair codes. FIELD stays open
    until its exact predeclared membership proves field preservation/placement.
11. **Ownership-tranche checkpoint, OFFLINE-ATTR and QUESTION-EVAL complete** — the clean
    474-observation receipt owns the stable/mixed family map, leaf evidence
    buckets, question reasons and terminal codes above. Evaluator semantics v3
    corrects the commit-grade boundary without rewriting the sealed receipt.
12. **Lineage integration, CP4, critic disposition, question issuance and
    named-result admission complete (2026-08-15).** The measured lineage is one branch again;
    CP4 is a corpus-wide, prompt-verbatim completion evaluated on the same
    sealed 474 observations; the critic registry is 30 = 13 + 17; the purpose
    question is asked before a guessed purpose settles it (the one question
    trace that convicted the product); named-result obligations reach planning
    (a sentence-final period is no longer read as a dotted path; a delta may
    cite every sentence that names results). FIELD's provenance join is
    complete but its conformance guard remains open.
13. **158×1 smoke and sealed 158×3 on `eeb8371e8` complete (2026-08-15).**
    Guardrail breach attributed to one deliberately unlocked family (the
    presence critic: 20 repairs + 4 errors); stability flat (135/158 vs
    136/158); the 56-observation loss ledger is derived from the sealed
    attempt failure ladders (`LOSS-LEDGER.md`, exclusive buckets: CP5-D1-only
    22, TEMPLATE-MODE 6, SECTION-WRITERS 4, CONFIRM-STABILITY 4, mixed
    D1/residual 2, residual 3, 15 stalls
    unadjudicated). The `eeb8371e8` receipt is the comparison baseline for
    every following slice; the ddb3 guardrails stay the release floor.
14. **Plan-economics tranche — proofs match the slice type; corpus changes
    come last:**
    (a) **STRICT-CAP** — first: user directive, and every later probe receipt
    must seal a capability, not a constant; the probe's `--tool-schema-file`
    lands with it. Proof: typed contract tests + sealed capability probe.
    (b) **TOKEN-TRUTH** — sealed schema-token probe from clean source for
    base, realistic 9/12 and the longest legal names under the typed cap,
    conservative at both budget consumers, including container behaviour.
    Proof: probe receipts. Must precede D1 only.
    (c) **CONFIRM-STABILITY** — own design gate; sole owner of the disclosed
    summary and the requirements version as the single confirmation identity;
    raw-state fingerprint retired after the disclosure is complete; local
    behaviour tests first, then its targeted `eeb8371e8` cohort ×3. May run
    before or alongside (b); lands before D1.
    (d) **CP5-D1** provider-schema materialization of the admitted projection
    with the compact self-excluding container index (entry gates 1–4 and the
    acceptance list in the CP5 body; removes the 24 presence-critic failures
    by construction and can claim at most the 22 D1-only observations; the
    critic becomes a postcondition). Cohort ×3 predeclared from the ledger
    rows; recovery of unemitted names is decided later from evidence.
    (e) **TEMPLATE-MODE** (6 stable stalls; reuse the resolver at the merge
    point). Cohort ×3.
    (f) **SECTION-WRITERS** (stop promoting example headings; downgrade or
    delete the hidden critic). Cohort ×3.
    (g) **Broad 158×1 on the UNCHANGED corpus** against the `eeb8371e8`
    baseline — the product comparison, before any case SHA changes.
    (h) **FLOW-QUALITY checkpoint** — the reporting-only produced-flow
    report over the plan-bearing observations of the freshest sealed receipt
    (N = plans, stated in the report), after (g) and before N=5; its output
    is a family map and specifically sliced follow-ups.
    (i) **STALL-POLICY** — prompt-quote adjudication of the 15 stalls; the
    product-owned ones become attributed slices; the clarification ones
    change contracts offline (allow) or with fresh captures (scripted answer)
    and publish a new rebased lineage; the four input-field option contracts
    from FLOW-QUALITY ride in the same corpus release.
    Then CP5's remaining slices (non-JSON
    outcome binding through the existing placement owners, nested template
    placeholder evidence), the selected-step revision defects as one bounded
    edit-path slice (mixed intent silently dropped, DOCX artifact revision
    compiles to an unsupported pass-through mode, negation-blind token gate,
    and the deletion of the model-family word list in favour of the catalog
    check that already guards it), **CP-EDIT**, **CP-D6**, **CP7**; the
    post-CP5 re-attribution loop (source refs 12, output-schema 10,
    review-policy 9, file roles) runs alongside on the fresh ×3.
15. **MEASURE-BUDGET is landed; before N=5** the harness must still prove its
    worst-case demand constants by counting real requests (the current proof is
    one-sided) and seal capacity for all 790 observations.
16. **Public contract lane:** after FLOW-AUTH, the retention bound and
    current-source Flow docs/OpenAPI accuracy slices may proceed in
    sequence, parallel to Builder ownership work. The Builder SDK,
    pagination and showcase-doc slice starts only after step 11 and
    must land before showcase/release.
17. **Runtime lane**, parallel throughout in its own Fable/peer
    session: **L2 → L1b → L3 complete; L5 in progress** (design decided
    2026-08-15: arithmetic proof plus a repaired `DB_POOL_DEBUG` seam, not a
    pool-event recorder; the webhook overlap contract landed at `29a5b1a6d`).
    The runtime audit's confirmed P1s — a concurrent publish silently undone
    by `PATCH /flows/{id}`, abandoned runtime uploads never reclaimed in
    production, one failing tenant aborting the maintenance sweep — are the
    lane's next slices; the tenant-admin classification-3 raw-export bypass
    is escalated to the user.
18. **Release evaluation:** final-frozen-manifest N=5 only at the
    release gate, repeated after every material post-gate product
    change. The full-corpus run is not an instrument-progress check.
19. Post-program: **PKG**, per `docs/flows/package-layout.md`.

Receipt tasks: D5 reachability and D7 occurrence may run in the
analysis lane. The critic disposition table closed in step 12, before CP5.

Maintainability rulings bind every slice: ownership transfers delete
their old path, tests die with their owners, no splits for their own
sake.

D13 follows the same ruling: when CP3's turn-context owner is next touched,
pass one `PreparedMessageContext` through router→service→planner, require the
already-resolved policies, limits and preflight state, and delete the service/
planner `None` fallbacks and duplicate replay branches. Do not create a
standalone god-module split or preserve production optionality for test
convenience.

### Public contract and documentation stream (pre-showcase)

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
  Amendment (owner, 2026-08-24, evidence-forced): for USER-NAMED RESULT
  fields the closure is VERIFY, NOT INJECT — the schema no longer carries a
  server copy of the attested names; the model's own declaration is verified
  against the attested contract (exact spelling, exactly once at the
  terminal root, declared-shape-compatible type, required-but-nullable), and
  a missing or conflicting name is rejected with the exact path. Nothing is
  silently stripped; the reject arm of the rule is unchanged.
- NO CATALOG-IDENTITY ROUTING (user decision 2026-08-15): product code never
  selects a feature, route or behaviour from a literal model name, model
  family, catalog row id, tenant or environment identity. Product selection
  consumes a typed capability resolved by the completion-model owner; each
  capability defines its own source — persisted administration (strict tool
  schemas: fail-closed, set per model), provider metadata, or a fixed adapter
  fact — and nothing forces every model-specific fact into admin
  configuration. Measurement identity lives in receipts and the tracked
  manifest; keyword lists that stand in for a catalog check are deleted in
  favour of the catalog. Protocol and provider names remain legitimate inside
  their own provider adapters and OpenAPI examples. A temporary exception is
  not a slice outcome — it is a defect with an owner and a removal date. The
  strict-tools route is the first removal (STRICT-CAP); the model-family word
  list in the selected-step edit path is the second (folded into the edit-path
  slice).
- NON-REPAIRABLE CODES — a PROPERTY invariant, not a count. Every
  non-model-repairable code must (a) depend only on server/external
  state or denote a compiler defect, (b) never consume a model retry,
  and (c) fail BEFORE provider use whenever its inputs are already
  server-known. In addition, (d) a failure whose deciding inputs the model
  cannot observe through its declared proposal surface must not consume a model
  retry: project the necessary inputs into the canonical contract or resolve the
  contradiction in its server owner. "The list may only shrink" is REJECTED:
  new genuine external or user-decision failures may legitimately appear.
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
- Runtime: L2, L1b and L3 are complete. L5 consumes the typed provider
  failures, immutable image set and health contracts under load.

Dependencies that stay hard (v10.7): FLOW-AUTH before Flow public
contract work; CP-ADMIT-0 before the next Builder ownership transfer;
CP2 step 1 before CP2 step 2; CP2 and CP1 before full CP-ADMIT, and its
per-code dependency table before that design gate closes; CP2b before
CP3 and CP5; CP9b before CP3; MEASURE-TRUTH before CT's causal gates;
the strict-tools receipt before CT freezes its provider wire; MEASURE-BUDGET
before N=5 release acquisition; FIELD-COLLIDE's exact predeclared membership
join before FIELD closure; the critic disposition receipt before CP4 or CP5;
CP4's corpus-wide attribution and case-contract release before a
CP4 fix or CP5 implementation. CP8b/CP8c and the JSON-to-text matrix-state revision are
completed historical prerequisites, not active blockers. The
orchestrator verifies every diff and owns all git.

### Measurement cadence
After a material Builder ownership slice, use one repetition of the
final-frozen manifest as the broad progress smoke; derive its population from
the tracked manifest rather than a prose constant. Use
an affected named cohort at ×3 when the slice transfers measured behavior or
when attribution needs protection from provider variance; Luna's lower cost
makes this the default targeted check rather than an exceptional tranche-only
expense. N=1 still detects broad deterministic regressions and new failure
families but makes no stability claim, while a targeted ×3 describes only its
named mechanism and never certifies the full product. Run the final-frozen
manifest ×3 at the ownership-tranche gate, then N=5 at the release gate
(detection power, not certification power), repeated after every material
post-gate change.

Every sealed ×N analysis emits the `(case, check, repetition)` stable/mixed map
before a product or evaluator slice is selected. Stable case-grain conformance
over accepted observations is the quality north star; flaky conformance and
availability are reported separately. The aggregate evaluated-pass percentage
remains visible for continuity but never ranks a slice by itself. Against the
`ddb3ccd84f98` ownership checkpoint, a material follow-up must keep broad
acceptance at least 93.62%, first pass at least 90.78%, repairs at most 2.84%,
Builder errors at most 1.42% and accepted p95 at most 33.825 seconds, subject to
the frozen comparator's variance rules. A guard breach is a rollback/attribution
event, not an acceptable trade for higher conformance.

Accepted-latency p95 ≤ 33.825 seconds is certified only by acquisitions run on
the measurement environment frozen with `ddb3ccd84f98`. A result from another
environment is non-certifying for that absolute guard; it is neither a pass nor
a waiver. Outside the sealed environment, a development slice may use
immediate-parent non-inferiority only when parent and candidate are acquired
back-to-back on the same idle validated stack, with identical model, harness,
corpus, concurrency, and worker topology, using a latency margin declared and
justified before either acquisition. This relative gate does not replace
sealed-environment certification at the next tranche or release gate. This
ruling applies only to acquisitions begun after its adoption (adopted
2026-08-24, peer-gate iteration 15 wording, verbatim).

Before a sealed suite that executes generated Flows, preflight the dedicated
measurement tenant's runtime capacity and API request budget and record both in
the suite manifest. The request preflight records a conservative whole-suite
demand, configured ceiling, observed remaining capacity and non-secret
rate-policy/key identity; it refuses launch unless remaining capacity covers
the complete acquisition, including the heaviest runtime sentinel. Stale queued
or running work that already consumes the tenant's concurrency is an environment
failure: stop and recover it through the runtime lifecycle owner before
acquisition. Never count it as a Builder product failure, clear unrelated live
work implicitly, bypass production limits or split the frozen corpus to fit a
quota.

`--sealed-targeted-suite` seals the selected run's identity; it does not prove
cohort provenance or cross-run comparability. For CT and FIELD-COLLIDE, recover
the original sealed observation-to-case join, or predeclare a new tracked
cohort from pre-candidate evidence and take its baseline with the same harness
before evaluating the candidate. Never infer membership from candidate
outcomes.

From v10.4, every repair-reduction receipt also reports bounded internal
failure subfamilies, repair attempts and provider calls per accepted plan,
token and accepted-latency p95, and family movement by unique observation and
unique case. Capture families may overlap and are never summed as projected
gains. A targeted slice is green only when its attributed family falls to zero
or a predeclared residual, acceptance and conformance are flat or better, no new
family replaces it, and terminal errors do not rise. Cross-lineage receipts
with different source, harness, case or outcome-semantics identities remain
directional evidence, never a formal A/B claim.

Builder proposal-contract gates follow the cross-contract proof in the
[Testing Standard](../../../engineering/testing-standard.md#model-authored-contracts-cross-the-compile-boundary).
Any server-known contradiction is resolved by its compile or assembly owner
before a model repair can be charged.

First-question relevance does not authorize product work from an N=1 movement.
Require the same case to fail in at least two of three repetitions and join the
failure to captured discovery/question evidence before changing its canonical
owner. For this checkpoint, explicitly forbid prompt-phrase patches, evaluator
or outcome-selected case tuning, field-name alias tables, new repair loops, a second schema or
compiler, scoring the six-file case from partial evidence, benchmark-only
rate-limit bypasses, summed overlapping family gains, and formal A/B claims from
the contract-changed citation cohort. A case contract may change only through a
corpus-wide, prompt-quote-backed rule applied to passing and failing cases alike;
version the case SHA, keep the evaluator identity matcher unchanged and show the
same captured observations before and after the contract release.

All comparable Builder receipts use completion-model UUID
`90824b05-9913-4210-968f-9294eb017d31`, verified in the live model catalog as
enabled, non-deprecated `gpt-5.6-luna`. That identity is a measurement fact
recorded in receipts and this cadence, never a constant in product code; the
capabilities the Builder relies on for that model (native strict tools) are
persisted on its catalog row. A model change starts a new evidence
lineage and must not be compared as product movement. Completed suites may be
followed immediately by the next planned suite, but measurement runs must not
overlap. This cadence supersedes both the earlier N=1-only per-slice
interpretation and the fixed 45-minute spacing rule by user decision on
2026-08-11.



### Builder launch contract (adopted 2026-08-24, peer iteration 35)

"Never fails" means, precisely: no known deterministic failure within a
declared support envelope; recoverable external failures preserve work and
retry safely; unsupported cases fail explicitly. Regression floors prevent
regressions; this contract defines production-ready. The smallest set that
must be true before launch, each mapped to one owner and one executable gate
(existing lanes referenced, never duplicated):

- One authoritative program and a declared supported-use and model-capability
  matrix (route-by-route, qualified by repeated cohorts on each configured
  production route).
- Trusted evaluator and frozen corpus with named denominators.
- Zero known deterministic supported-case failures and zero silent loss of
  confirmed critical details (request-to-execution: confirmed details survive
  planning, compilation, applying and representative real execution).
- End-to-end executed-output tests across representative simple, complex,
  document, structured, attachment and governed cases, including source
  grounding fidelity, not merely field-name presence.
- Owner/SRE-approved success, latency, recovery and error-budget SLOs holding
  on each supported route.
- Safe preview/test-run, correction, undo, resume and explicit
  unsupported-state UX; wrong-auto-commit and skipped-necessary-question
  rates measured.
- Security, privacy, tenant isolation, authorization, prompt-injection,
  residency, retention/deletion and audit gates complete; raw debug capture
  disabled and retention-bounded in production.
- Provider outage, rate limiting, cancellation, SSE reconnect, idempotency,
  concurrent edit/publish, version skew and queue recovery exercised
  (existing runtime P1 lanes are hard dependencies).
- Operational telemetry, alerting, capacity evidence, canary, rollback and
  incident ownership (the failure ledger has an owner).
- Accessibility and Swedish/English behavior verified.
- A bounded domain-user pilot: completion rate, correction rate, abandonment,
  time to useful flow, and zero critical missed-detail defects.

These tracks run in parallel with product slices from 2026-08-24 on; they are
release gates, not a polish phase.

## Operating protocol (for any agent continuing this)

- Branch: commit/push ONLY `refactor/flows-clean` on eneo-ai/eneo.
  Never stage the user's protected files (`SolReview/`,
  `docs/adr/marketplace-*`, `.devcontainer/`,
  `frontend/package.json`). The goal, ledger and harness files this
  list used to name were deleted on the owner's instruction on
  2026-08-18; the rule survives them, and any file the owner is
  editing locally is protected whether or not it is listed here.
  ONE scoped exception, granted
  2026-08-10: `.devcontainer` compose changes for the three-role
  dev-parity topology (L1a) may be edited and committed; every other
  protected path stays untouchable, and pre-existing devcontainer
  content must survive. The historical L1a exception has landed; it
  does not authorize later devcontainer changes.
- Lane exception, granted 2026-08-21 (decision O0 of that lane): the Flow AI
  Builder tidy refactor commits and pushes `refactor/flows-tidy-ai-builder`.
  Its execution authority is
  [tidy-ai-builder-plan.md](tidy-ai-builder-plan.md), which owns its own slice
  checkboxes and receipts and binds to the rulings, cadence and guardrails
  here. The exception covers that lane only.
- Corpus population for that lane: the tracked manifest stays the population
  owner, as NO PROSE POPULATION CONSTANTS requires. The lane's uncommitted tree
  adds the case-id range `evidence_municipal_173` through `robustness_182`,
  which lands as a corpus release in slice 0.4 of its plan, after the broad
  comparison on the manifest as tracked today. Until 0.4 lands, that range is
  outside the population and is not comparable evidence.
- Commits: set `ENEO_DEVCONTAINER_NAME` only to a validator whose
  `/workspace` bind source is this exact checkout (currently
  `eneo-flows-clean-pyright`). `developz_devcontainer-eneo-1` mounts a
  different checkout and is invalid for this branch. The container-side
  pyright hook must inspect the candidate tree. If it OOMs (exit 247),
  run pyright manually on the exact changed files and use
  `SKIP=pyright` only with that evidence recorded.
- Peer review and validation: follow the canonical
  [AI Review Workflow Standard](../../../engineering/ai-review-workflow.md)
  and the active task's acceptance checks. Record exact commands, results,
  reviewer disposition and candidate identity in its validation receipt;
  never treat an old session name or prose test count as the current gate.
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
- Night window: no work 00:10–07:00 Stockholm, Codex included (user decision
  2026-08-22, replacing the earlier 01:00–06:00 window). A pass at xhigh may
  run an hour, so do not launch one after ~23:10; stop anything still running
  at 00:10 and resume it by session name at 07:00.

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
8. ~~Template mode and terminal choice~~ — DECIDED 2026-08-15 16:20 by the
   user: (a) when the user attaches a Word template and says it is to be
   filled, do NOT ask `docx_output_mode` — commit fill mode; when a DOCX is
   attached as context or inspiration to build from, asking is right. This is
   exactly the existing resolver's guard (one explicit, commit-grade template
   role with a prompt quote → fill; inferred or multiple → ask), so
   TEMPLATE-MODE reuses it and adds no phrase matching. (b) When the prompt
   explicitly leaves the terminal alternative open ("DOCX eller PDF"), the
   Builder does NOT assume: it asks, and uses the question to guide the user
   to the right path; those stalls are clarification policy and the affected
   cases must allow or answer the question. Every other `terminal_output`
   stall stays under the same prompt-settled-versus-open adjudication as the
   rest (STALL-POLICY). (c) The users are municipal and government staff new
   to the system: every question must earn its place — ask what steers the
   flow, never what the evidence already answers, and phrase the choice with
   its consequence in plain language so the question itself is help, not
   friction. Acceptance for the wording review: one Swedish/English inventory
   of the surviving canonical questions under the existing question owner,
   each entry showing the consequence of the choice, plain municipal language
   and matching translations (FLOW-QUALITY (1)); the BALANCED rule (decision
   7) stands.
