# Flows & Flow AI Builder — production-readiness roadmap

Living document. Updated as part of landing every slice; the git history of
this file is the program's audit trail. Supersedes the retired 99-item
ledger (final state ~81/99; its remaining items were reconciled into this
plan against current source, not carried over blind).

## Mission and standing policies

- Target: production quality 9/10 across maintainability, clean
  architecture, reliability, robustness — for an enterprise Flow AI engine
  whose public APIs external frontend developers consume.
- Flows and Flow AI Builder are **unreleased with zero users**: aggressive
  refactors are preferred when they buy the cleaner long-term owner. **No
  backwards compatibility**, no dual reads/writes, no tolerant-read
  versioning, no rollout scaffolding. Correct schemas and contracts
  directly.
- No hardcoded operational policy an admin should own — admin panel, not
  env vars. Fixed correctness/safety invariants stay in code with named
  reasons.
- Multi-tenancy will be retired later: preserve isolation (a security
  requirement today), never deepen tenancy machinery.
- Working model: the lead agent owns scope, source verification, validation,
  final judgment, roadmap, and git. Workers implement only substantial frozen,
  independently testable slices in separate worktrees; the lead handles small
  or context-heavy corrections directly. One skeptical gate reviews a stable
  candidate (green ≥8 to land); resume it only for a verified material finding,
  never for routine polish or landing mechanics.
- Evidence vocabulary: retrieved ≠ included-in-prompt ≠ material influence.
  Exports are complete-or-refuse; views narrow honestly and say what they
  left out.

## Landed (most recent first)

| When | What |
|---|---|
| 2026-07-30 | **Model-aware Builder resource policy**: attachment text now shares the selected model's declared input window after output, safety, and conversation reserves instead of using fixed character quotas; admins own effective attachment, message, aggregate DOCX-inspection, placeholder, and token-reserve policy; fixed API, parser, and planning-state safety ceilings are returned through the typed settings contract and explained in Swedish/English; frontend/backend admission agrees, template failures are explicit before provider work, and shared settings writes are serialized with a lost-update regression proof (`478dfeb1c`, gate green 8/10 after three same-session passes, no findings) |
| 2026-07-30 | **Atomic Builder template attachment binding**: exactly one confirmed DOCX is compiled into required, runtime-provable placeholder bindings before proposal hashing; transcription-dependent templates make audio input required; apply reuses the same uploaded File and atomically creates the Flow asset and normal resource binding; authorization, bounded inspection, rollback, retry, replay, deletion races, publish pinning, real DOCX rendering, and deterministic zero-token execution are proven, while reference/context/example attachments remain planning-only (`2d608b309`, gate green 9/10 after six same-session passes, no findings) |
| 2026-07-30 | **Reliable Builder attachment interpretation**: canonically equal explicit schemas now merge with complete provenance, distinct schemas ask one replay-safe bounded question before provider work, and selected example outputs contribute cited structure/style guidance plus deliberately open inferred JSON shape without exact-fidelity or closed-world claims; one focused schema-evidence owner enforces strict JSON, byte/depth/field bounds, conservative inference, and shared field projection, while `PlanningState` owns one atomic attachment-interpretation transition (`f25b029e6`, gate green 8/10 after four same-session passes, no findings) |
| 2026-07-30 | **Honest Builder attachment evidence**: persisted file-role evidence now retains independent readability and exact coverage through live refresh and classifier replay; inventory-only files cannot promote semantic roles; full placeholder identity survives persistence and compilation while shared prompt rendering is safely bounded; deterministic discovery records every valid schema candidate and refuses multiple candidates before provider work; a private full-evidence fingerprint invalidates confirmation even for omitted or display-colliding attachments, while Swedish/English summaries stay bounded (`caa17c3ef`, gate green 8/10 after four same-session passes, no findings) |
| 2026-07-30 | **Honest Builder execution profile**: proposals now expose an output-only static profile for completion-model, transcription-model, deterministic, schema-constrained, and authored mapped work; one pure mapped-execution owner aligns validation, runtime dispatch, and projection while rejecting invalid or dual configurations as structured Builder feedback; the advanced Swedish/English UI explains overlapping categories and avoids provider-call claims; five disproven lints were deleted while the two source-proven structural-waste critic rules remain (`5509eef84..fb6934b5a`, gate green 8/10 after four focused passes, no findings) |
| 2026-07-30 | **Bounded Builder persistence and replayable terminal failures**: locally detected oversized planning state now commits one typed terminal outcome that preserves the last valid state and replays without another provider call, while genuine unknown provider outcomes remain untouched; immutable proposal snapshots have one current-only top-level schema version, a 1 MiB serialized bound, and canonical fail-closed hydration that rejects unknown or normalized persisted values without weakening provider-input normalization; the established draft-title path remains intact (`c606411f7..48e9be497`, gate green 8/10 after two passes, no findings) |
| 2026-07-29 | **Bounded interactive attempt evidence**: current and recent attempt candidates stop at 500 rows plus one truncation sentinel before ranking, aggregation, and payload hydration; every attempt-derived count is explicitly exact or a lower bound through the API and Swedish/English UI; unlimited exports remain complete; narrow PostgreSQL indexes are resumable and reject wrong, mixed-direction, or widened definitions (`acf340e9a..f82a2419a`, gate green 8/10 after three total passes, no findings) |
| 2026-07-29 | **Canonical completion-model capability**: every Flow output mode now has one typed completion-backed classification shared by runtime disclosure, retrieval validation, the capability manifest, authoring, and materialization; deterministic template-fill steps shed unused completion-model bindings, and new output modes must be explicitly classified (`4b0796152`, gate green 9/10, no findings) |
| 2026-07-29 | **Honest run token totals**: provider-call lifecycle rows now own live usage; retained attempts preserve typed totals and per-dimension completeness in identity-validated tombstones; superseded/rerun spend survives retention; invalid retained evidence makes recoverable totals explicitly incomplete; live and retained reads stream and fold with bounded application memory; the UI distinguishes zero, incomplete, and unrecorded usage in Swedish and English (`9f7d70165`, gate green 8/10, no findings) |
| 2026-07-29 | **Slice 2**: every evidence section measured and bounded — serialized per-projection measurement with a per-row floor, ceiling+1 bounded preflight, memory-budget-derived aggregate ceilings with peak/leak proofs, complete-or-refuse exports with typed section/limit context, ordered admitted prefixes with one truthful typed omissions collection sv+en, frontend consuming the generated union (`b1ee9b7e5`, gate green 8/10 after five iterations, no blockers) |
| 2026-07-29 | **Slice 2b**: three production defects fixed — unprivileged resolved-policy reader for all runtime consumers (service keys work on documented paths, both defense layers intact), resume returns the canonical persisted step result, audio critic invariant scoped to structured source readers. Full integration suite 439/0 for the first time (`69f242cdd`, gate green 8/10, no blockers) |
| 2026-07-29 | Integration expectations realigned with their production owners (8 stale tests repaired; 5 left deliberately red exposing verified production defects — see item 2b) (`bc20307fa`, gate green 8/10) |
| 2026-07-29 | **Slice 1**: every evidence response reads one REPEATABLE READ snapshot — route-owned isolation before the first statement, shared-session TaskGroup deleted, proven at the route boundary with a mid-read mutation and a revert-detection test (`f38354342`, gate green 8/10, no findings remaining) |
| 2026-07-29 | Corruption-caused omission distinguished from size-based omission in the public knowledge view; reason-neutral narrowing contract sv+en (`27cef0327`, gate green 8/10) |
| 2026-07-29 | JSONB docs honesty (`36c35b734`, `a3318a169`) |
| 2026-07-28 | RAG evidence transparency, `615200dcc..cf0cddc16`: verbatim retrieved passages as typed bounded evidence; sensitivity-gated disclosure; single-statement bounded admission with per-step attribution; corruption fail-closed; four-limit complete-or-refuse exports; admin tenant policy for recording limits; full source rendering sv+en |
| 2026-07-28 | Bounded evidence view + honest export refusal (`3ad737a79`) |
| 2026-07-27 | Exact resolved-input lineage persisted at every resolution path (`f515fe9df`, `e387615ec`) |
| 2026-07-27 | Provider-call evidence v2 contract (`9e527fcbd`); requested provider capabilities (`9a4c14243`) |
| earlier | Provider-call completeness recording (`not_reported` usage states); builder resume/draft recovery paths; authoring/builder vocabulary renames (remnants remain, see item 8); builder draft retention |

## Historical-ledger reconciliation (verified against source 2026-07-29)

From the retired program's OPEN-WORK ledger: **A is done** (`9f7d70165`:
provider-call-owned totals, typed completeness, retention-safe summaries).
**B is done** (`c606411f7..48e9be497`: oversized planning state is a typed,
replayable terminal outcome, and versioned proposal snapshots are bounded and
canonical on hydration). **C is obsolete** under the no-compat
pre-release policy (no data preflight, no tolerant reader). **D is done**
(typed discriminated rerun-revision contract + repository reads + multi-rerun
DB proof). Vocabulary neutrality is NOT fully landed: `case_documents`,
`basic_case_metadata`, `case_like_flow` persist in builder discovery
(item 8). M6.6 stays measurement-gated; M6.7 is superseded by item 2 except
transport (deferred); M2.9 code exists but the deployment inventory is an
external release gate (item 10); BM0.2 is external (item 10).

## Ranked plan (merged and source-verified, 2026-07-29 pass 2)

1. ~~One consistent evidence snapshot~~ — **LANDED** `f38354342`. The
   retention-purge race variant of the mutation-barrier proof carries into
   item 7's acceptance (where purged-state semantics are implemented).
2. ~~Whole-bundle evidence bounds~~ — **LANDED** `b1ee9b7e5` (narrowed
   claim: the companion attempt-admission window and serialized-floor proof
   landed under 2c).
2d. ~~Correct deterministic template-fill capability truth~~ — **LANDED**
   `4b0796152`. Completion-backed modes now have one typed owner shared by
   runtime, authoring, materialization, and the capability manifest; new output
   modes fail the exhaustive classification test until explicitly classified.
2c. ~~Bounded attempt admission~~ — **LANDED** `acf340e9a..f82a2419a`.
   Current-first admission is bounded before windows and aggregates; counts
   expose exact or lower-bound semantics through the public contract and UI;
   a real 5,004-attempt PostgreSQL plan proves every scan and aggregate/window
   input stays at ceiling+1 or below.
2b. ~~Fix the three verified production defects~~ — **LANDED** `69f242cdd`.
3. ~~Honest run token totals, retention included~~ — **LANDED**
   `9f7d70165`.
4. ~~Bounded Builder persistence and terminal behavior~~ — **LANDED**
   `c606411f7..48e9be497`. Oversized planning state commits a typed replayable
   terminal outcome without rewriting genuine unknown provider outcomes;
   current-only proposal snapshots are versioned, bounded, and canonical on
   hydration while preserving the draft-title JSON path.
4b. ~~Honest static execution shape~~ — **LANDED**
   `5509eef84..fb6934b5a`. An output-only proposal projection distinguishes
   completion-model, transcription-model, and deterministic work, makes model
   overlap explicit, reports schema-constrained outputs and authored mapped
   cardinality, and never estimates provider calls or cost. One shared resolver
   owns mapped eligibility for validation, runtime dispatch, and projection;
   invalid, unbounded, unsupported, and dual configurations fail as structured
   Builder feedback. Five disproven heuristic lints were deleted. The two
   source-proven structural-waste critic rules remain; adding new critic
   topology is recorded as `measured_no_change`.
5. ~~Operational attachment semantics~~ — **LANDED**
   `caa17c3ef..2d608b309`. Actual readability, exact coverage, full placeholder
   identity, schema/example interpretation, and one replay-safe conflict
   question survive confirmation and replay. Exactly one confirmed DOCX becomes
   a typed intent; after the Flow exists, the atomic materializer reuses the
   same authorized File, creates or reuses the normal template asset and
   resource binding, revalidates the approved exact placeholder contract, and
   commits no partial authoring effects on failure. Runtime and lifecycle proofs
   cover required transcription input, detach/deletion races, authorization,
   rollback, retry, replay, publish pinning, session deletion, real DOCX render,
   and deterministic zero-token template fill.
6. **One canonical attempt-evidence projection** *(medium/large)* —
   **DELETION BOUNDARY LANDED** `a3d2ba41d`. Attempt provenance v2 rejects
   duplicate artifact, template, runtime-input, transcription, guard, HTTP,
   token-receipt, and agentic projections; relational provider calls and result
   files remain canonical, original attempt payloads remain immutable, and
   `step_result_builder` owns terminal evidence construction. Remaining work:
   converge prompt, model-parameter, and attempt-start scalars on a typed
   immutable attempt input, then type the surviving provenance envelopes.
   Target ownership boundary: the immutable attempt input owns the exact execution
   snapshot; relational result files own artifacts; attempt provenance owns
   only what cannot be reconstructed (verbatim RAG, provider-call facts);
   the mutable step result is a runtime projection, not a parallel forensic
   store. `step_result_builder` becomes the sole projection builder,
   executor orchestrates. Delete redundant fields FIRST, then type the
   surviving envelopes (reuse `RetrievedKnowledgeEvidence`); typing before
   deletion would formalize duplication. Acceptance: a survivor matrix
   proving each exported fact has exactly one owner and retention-purged
   output stays honest.
7. **Resolved-input lineage projection** *(medium)* — batch-project the
   persisted exact lineage into the existing evidence bundle for admitted
   attempts, under the item-1 snapshot, inside the item-2 aggregate
   budget. A missing lineage row today parses as `not_tracked` even when
   retention purged it; the projection must reuse the attempt retention
   marker: missing + marker = `retention_purged`, missing without =
   `not_tracked`, malformed = `corrupt`.
8. **Builder frontend/server contract closure** *(medium, four reviewed
   commits by owner)* — (a) stream/attachment/draft contract: attachment-limit
   ownership is **LANDED** `478dfeb1c`; remaining work validates known SSE
   payload shapes at runtime (parser currently casts parsed JSON), adds one
   explicit stream-failure state, preserves fail-fast handling for unknown
   events, and makes the draft lifecycle explicit. (b) vocabulary
   neutrality: directly correct `case_documents`, `basic_case_metadata`,
   `case_like_flow`, including the false use of generic `underlag` as a
   case-domain marker — no tolerant readers. (c) delete another heuristic
   family only after source evidence proves a canonical semantic owner and
   behavior equivalence. (d) serve RAG policy ceilings through the existing
   settings response and delete the duplicated admin-page TS constants — no
   generic constraints-discovery API.
9. **Docs-site contract correction** *(medium, per-slice from now on)* —
   the false "influenced the answer" claim is CORRECTED (2026-07-29, with
   this roadmap revision); the attachment-to-template lifecycle is CORRECTED
   with item 5 (`2d608b309`). Remaining corrections land with their owning
   slice: export limits and lineage writer with items 2/7. Add contract tests
   covering all four export limits and prohibiting material-influence wording.
10. **Release proof** *(external gates, tracked not implemented here)* —
    BEFORE any live run, freeze in the tracked gate input: repetition
    count, required cases, non-municipal domain families, provider
    route/model identity, and numeric p50/p95 latency + token/call
    ceilings (the harness today has none of these and only
    municipal-domain cases; thresholds must never be chosen after
    observing results). Benchmark and freeze the Builder platform ceilings
    for attachment count, message length, per-file and aggregate DOCX
    inspection, placeholder evidence, and synchronous parser capacity before
    production; the current safety values are conservative bounds, not
    certified best-practice capacity. Preserve raw receipts. Then: server build
    identity, structural goldens (BM5.2–5.4), HTTP-secret deployment
    inventory (M2.9 operational half; with zero users any hit means
    reset/delete), branch-protection evidence (BM0.2).

**Product decisions adopted as defaults (owner may override):** token
totals survive debug retention via a typed tombstone summary rather than
an explicit `retention_purged`-only state; exactly one template attachment
is required per template-fill step (multiple template-role files become a
structured question); release-gate numeric thresholds are product-owned
inputs to be fixed before execution.

**Deferred:** export streaming/pagination transport until item 2 exists and
measured refusal metrics justify more; document-render offloading (M6.6)
until loop-lag/heartbeat measurements with maximum-size inputs demand it.
**Rejected:** standalone test-factory consolidation (three local `File`
constructors stay local until a real contract emerges); any new snapshot
coordinator/query-bus/per-repo-session machinery; a second aggregation
service for token totals; a separate "official decision basis" store.

## Builder-excellence track (source-verified 2026-07-29, peer pass 2)

Source: xhigh peer review of Builder intent-understanding, attachments,
HITL, and generated-flow efficiency against source at `10ccd6b94`.
`production-roadmap.md` is the SOLE execution authority; the retired BM
ledger is evidence only. (`goal.md`/`notes/handoff.md` still name retired
roadmaps — user-owned dirty files, flagged to the human owner.)

Product defaults adopted (owner may override): an uploaded fillable
template binds as an immutable TEMPLATE_FILL asset (exact layout); an
example-output attachment derives bounded structure/style/schema
constraints surfaced at confirmation — never exact-visual-fidelity
claims. Checkpoint vocabulary freezes to FlowStepReviewMode (view/edit).

Hard ordering constraints: the B5a prerequisite for item 2c is complete
(`4b0796152`); B5b follows B1; B2 runs evidence → interpretation → binding;
B4 runs understanding/confirmation → compile/apply. The ranked plan above
controls all other ordering.

- **B1** (= item 4): **LANDED** `c606411f7..48e9be497`. Terminal replayable
  Builder persistence and bounded canonical proposal snapshots. *(L)*
- **B2** (= item 5 deepened, three ordered owner slices): (a) **LANDED
  `caa17c3ef`** — preserve the attachment owner's actual evidence contract
  (`fully_seen/excerpt_truncated/inventory_only` plus readability) through role
  selection and replay, keep full placeholder identity with display-only
  clipping, discover all schema candidates, and refuse ambiguity before
  provider work; (b) **LANDED `f25b029e6`** — derive and confirm bounded,
  cited structure/style/schema constraints, deduplicate canonically equal
  schemas, ask one replay-safe question on real conflicts, and keep inferred
  example shape open and explicitly non-exact; (c) **LANDED `2d608b309`** —
  bind exactly one selected template at the atomic materialization seam, reuse
  the same File, compile exact runtime-provable placeholders before approval,
  and keep reference/context/example attachments planning-only. Evidence,
  interpretation, then binding; no richer coverage state was invented. *(L)*
- **B3**: no silent guessing after question-budget exhaustion — preserve each
  candidate's source-specific commit-grade policy; every material commit-grade
  candidate ends asked, explicitly defaulted and surfaced at confirmation, or
  rejected as irrelevant. Do not make the generic `ResolvedSlot.is_commit_grade`
  default into a new global policy. *(M)*
- **B4** (two ordered slices): (a) the existing understanding pass records typed,
  cited checkpoint intents and confirmation exposes them; (b) compile/apply and
  the critic share one canonical requested-versus-compiled checkpoint predicate.
  No parallel HITL classifier or duplicate matching rule. *(M)*
- **B5a** (= item 2d): **LANDED** `4b0796152`. *(S)*
- **B5b** (= item 4b): **LANDED** `5509eef84..fb6934b5a`. Factual execution
  shape, shared mapped-execution ownership, heuristic-lint deletion, and
  `measured_no_change` for speculative new critic invariants. *(M)*
- Generated-flow proof is not a standalone B6 slice. Each owning slice carries
  its behavior tests: form variables (inmatningsfält), targeted underlag per
  step, enforced JSON input/output schemas, unusual-input resilience, and
  deterministic zero-call behavior. Measured economics stay in item 10.
- **B7** (= item 8b/8c): first correct the known vocabulary defects directly;
  then delete one heuristic family at a time only after evidence proves the
  canonical semantic owner and behavior equivalence. *(M)*
- The resource-limit audit leaves bounded follow-ups with existing owners:
  B3 evaluates discovery question and transcript exhaustion; B7 evaluates
  source/output compaction heuristics only with their semantic-owner work; item
  10 measures attachment/parser budgets and the four-call proposal
  spend/reliability guard before any policy change. Planning/proposal
  persistence and run-evidence/export bounds remain fixed backend invariants
  unless storage or runtime measurements justify changing their owners.
- **B8** (deferred): skills value gate — offline comparative evaluation
  (same briefs with/without a curated playbook) before ANY coupling;
  free-text admin guidance REJECTED (unversioned prompt ownership). This is an
  evidence gate, not an implementation commitment; only proven lift may create
  a later scoped roadmap item.

**Rejected as overengineering**: a second assumption ledger (the
ResolvedSlot -> action-policy -> confirmation surface already exists); a
token/currency cost estimator; a numeric step-count knob; per-step
rationale fields; attachment RAG/indexing; module splits driven by line
count (the critic/compiler/metadata modules are deep, not defective —
the debt is duplicated semantic ownership).

## Update protocol

Landing a slice updates this file in the same commit series: move the item
to Landed with its SHA, re-rank if evidence changed, record newly accepted
follow-ups. Peer-gate scores and artifacts stay in `.codex/artifacts/`
(untracked); this file records outcomes only.
