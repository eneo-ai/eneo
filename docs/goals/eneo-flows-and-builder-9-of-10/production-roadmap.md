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
- Preserve the Builder's architectural spine: bounded structural evidence and
  one cited semantic-understanding owner feed `PlanningState`; server policy owns
  questions and confirmation; the model proposes semantic intent; the compiler
  alone owns schemas, dataflow, topology, and runtime mechanics; normal Flow
  draft/publish/runtime remains the only execution path. Do not introduce a
  second agent graph, planning store, or workflow runtime.
- Working model: the lead agent owns scope, source verification, validation,
  final judgment, roadmap, and git. Workers implement only substantial frozen,
  independently testable slices in separate worktrees; the lead handles small
  or context-heavy corrections directly. One skeptical Codex gate reviews a
  stable candidate (green ≥8 to commit); the committed candidate then receives
  one read-only Claude Opus/high gate before push, with one final resume only
  for a verified material finding. Never review routine landing mechanics or
  duplicate a gate that already covers the exact commit range.
- Testing stays proportional to observable risk: reuse the narrowest existing
  behavior or contract surface, replace stale internal assertions instead of
  adding parallel tests, and add a regression only for a distinct user-visible
  failure mode. Do not build broad matrices, mock-heavy wiring tests, or new test
  abstractions when an existing owner-level check proves the behavior.
- Evidence vocabulary: retrieved ≠ included-in-prompt ≠ material influence.
  Exports are complete-or-refuse; views narrow honestly and say what they
  left out.

## Landed (most recent first)

| When | What |
|---|---|
| 2026-08-04 | **Canonical checkpoint parity (B4(b))**: one shared requested-versus-compiled checkpoint predicate (`ai_builder_checkpoint_contract.py`) now powers create compilation, the critic registry, and apply-time drift re-checks. Checkpoint intents are tri-state — `set` carries a mode, `clear` is a typed tombstone, absence means unchanged (`BUILDER_SCHEMA_VERSION` 15). Create compilation strips model-authored review modes before assembly and projects intents onto their terminal producers (transcript review onto the backend-inserted transcription step); the proposal prompt no longer asks for `review_mode` in create mode and the duplicate leading-transcription instruction is deleted. The edit lane compares against the existing Flow's canonical authoring snapshot as the preserved baseline — body-writer identity reconstruction moved into `current_flow_authoring_spec` so edit compilation and checkpoint comparison share one owner — and a `set`/`clear` intent releases its producer kind's baseline checkpoint on both sides, so requested changes survive retyped or relocated producers while unsolicited additions and removals are rejected. The never-shipped `planning_state_version == 0` apply bypass is deleted; a transcript checkpoint without a transcription producer is a non-model-repairable contradiction; confirmation renders requested clears bilingually; four stale `checkpoint_updates` fixtures repaired, restoring the green Builder fence (`3c2a1faf1`; Codex gate green 8/10 after six iterations, 3,123 Builder + 6,204 flows unit tests passed, Pyright 0) |
| 2026-08-03 | **Classifier attempts remain observable without weakening failure ownership**: the existing classifier metadata now records a closed resolved, no-content, parse-failed, or skipped-no-resolvable-slots outcome; only resolved attempts carry or replay semantic facts, provider failures remain in the typed provider-turn lifecycle, invalid internal input fails before provider work, and validated metadata is admitted before live planning state changes. Route and source identities are preserved without unrelated local caps, malformed non-string responses remain measurable even when provider usage is absent, and the strict response parser shares its envelope owner with the emitted schema (`3afe6e947`; Codex gate green 8/10, 3,054 Builder tests passed) |
| 2026-08-03 | **Complete source-capture requirements**: compiler guidance now renders every already-admitted typed field in deterministic order, preserves complete descriptions, and no longer suppresses requirements through 8-field, 96-character, 900-character, or substring heuristics. The selected Flow-step model's existing save-time prompt admission and typed runtime context-window failure remain the fit owners; no replacement cap or admin setting was added (`aa411ec1c`; Codex gate green 9/10, 6 focused tests plus reused admission/overflow checks passed) |
| 2026-08-03 | **Related document packages remain linear**: several related files in one run no longer imply cross-step Flow fan-in; only explicit commit-grade same-run comparison selects non-linear dataflow, so document-package journeys can compile their declared JSON terminal contract instead of failing after proposal. The separate compare-to-JSON product decision remains fail-closed and unchanged (`85516be94`; Codex gate green 8/10, 3,045 Builder tests passed) |
| 2026-08-03 | **Explicit Builder evidence admission**: source-validated explicit requirements now retain their evidence level through replay into strict persisted planning state; cited medium-confidence facts can commit without a redundant question, inferred facts remain assumptions, incoherent model provenance fails validation, and confirmation uses the same provenance boundary. Parser-to-policy and JSONB round-trip proofs cover both admission and downgrade (`ef4a45416`; supporting type and test-contract corrections `f0a425b8c`, `74d014ad3`; Codex gate green 8/10, 2,988 Builder tests passed) |
| 2026-08-03 | **Intent-led Builder questions and durable confirmation**: discovery now owns which unresolved consequential question is asked while action policy preserves its order instead of reconstructing heuristic or pattern questions; typed planning-state reconciliation removes stale document/comparison answers after input changes; visible legal assumptions survive confirmation through the existing requirements contract; fixed-choice questions no longer advertise unsupported custom answers, and the bounded mapped-file question appears only for a coherent document/file architecture with its actual organization ceiling. The duplicate forced-ask and prompt-reconstruction paths are deleted (`b1e9b3ae8`; Codex gate green 9/10, Claude Opus gate green 8/10, 493 changed-file behavior tests passed) |
| 2026-08-02 | **Trustworthy Builder journey evaluation**: the 120-case v4 corpus now continues through bounded configured interviews, records ordered and reopened questions plus first-pass/repair outcomes, checks directional JSON contracts through applied flows, preserves one v2 case/failure identity across every receipt, and gates only the seven required cases; benchmark failures remain visible without blocking release (`22ece969a`; Codex and Claude gates green 8/10, no blockers) |
| 2026-08-02 | **Evidence-backed Builder architecture admission**: architecture-changing slots now commit only from explicit answers, existing-flow defaults, a typed confirmed-requirements projection, deterministic attachment structure, or citation-backed high-confidence model evidence; policy defaults and heuristics remain visible assumptions but cannot silently shape topology. The create compiler consumes only the persisted architecture commit, and the language-specific requirements-summary parser and draft/raw-slot compiler fallbacks are deleted (`7fa0c6a16`) |
| 2026-08-02 | **Language-neutral Builder discovery ownership**: `PlanningState` and typed input/output intent remain the semantic truth while the parallel phrase-derived `case_like_flow` flag, the unused document-category question and synonym inventory, and the behavior-locking specialty recognizer are deleted; runtime-metadata values are neutral direct contracts with no compatibility aliases, and generic `underlag` no longer invents a domain or minimum viable purpose (`3409a8409`) |
| 2026-08-02 | **Precise Builder source-material dataflow**: explicit structured Underlag now compiles to exact field projections whose schema and lineage are shared by Builder compilation, publish validation, and runtime resolution; form fields remain at their declared consumers, post-transcription steps describe the text they actually receive, and blanket raw-plus-structured repair plus whole-object coverage heuristics are deleted. Compiler-to-runtime parity and large-transcript regressions protect the contract (`732c7cffb`; Codex and Claude gates green 8/10, no blockers) |
| 2026-08-02 | **Explicit Builder source-reference failures**: typed source references now remain typed through the shared create/edit compilation boundary; every candidate is validated before deduplication, contract-invalid references fail with named target-correct Builder feedback instead of being flattened into a plausible free-text Underlag question, and the shared input-binding contract remains the validator (`b02529d5d`; Codex and Claude gates green 8/10, no blockers) |
| 2026-08-02 | **Exact Builder runtime-field consumers**: confirmed runtime fields now reach proposal drafting with their exact server-owned names, types, required state, labels, and options; `uses_form_fields` is the sole semantic consumer contract, confirmed definitions override model redeclarations, missing consumers return named repairable feedback, and the compiler no longer hides unused fields by attaching them to the final step; behavior tests pin comparison, report, audio, template, and JSON-input placement (`7ffaf5f6b`; Codex and Claude gates green 8/10, no blockers) |
| 2026-08-02 | **Directional Builder JSON contract compilation**: resolved input-schema evidence now reaches the first Flow-input JSON consumer while independently resolved output evidence remains on the terminal JSON contract; compiler-owned raw JSON bindings are removed only at that typed boundary, downstream step contracts remain independent, composite JSON/form input fails explicitly without futile model-repair turns, and a real JSON golden proves both declared contracts survive canonical authoring materialization (`f465e9a6d`; Codex and Claude gates green 8/10, no blockers) |
| 2026-08-01 | **Explicit Builder schema direction**: one neutral schema-evidence owner now retains bounded JSON Schema candidates with complete provenance, while `PlanningState` stores independently selected input and output evidence; explicit structured answers or citation-backed user intent can assign the same or different candidates to either boundary, a replay-safe bilingual multi-select question resolves genuine ambiguity, and reference-only schemas remain unassigned; attachment-only evidence cannot choose direction, schemas do not reopen the terminal output, and the public overflow error plus generated client use one direction-neutral contract (`8f78a04fc`) |
| 2026-08-01 | **Canonical Builder discovery evidence**: free-text replies now reach one cited classifier instead of deterministic option matching, and accepted typed planning slots replace conflicting raw signals in the discovery profile while raw text still fills genuinely missing input, output, and output-submode dimensions; a resolved primary input projects one coherent architecture and cannot reopen a stale mixed-input question (`cbc1132e2`, `65af265bb`; Codex and Claude gates green 8/10, no blockers) |
| 2026-08-01 | **Explicit Builder question exhaustion**: architecture candidates and quality questions with an explicit `ask` policy remain askable after the normal user-question budget; every registered quality question has a terminal policy if it reaches the budget decision—to ask, surface a no-runtime-fields assumption, or reject an irrelevant refinement; rejected candidates still do not consume a question family, now pinned by a behavior test, and the assumption survives the public confirmation and persisted requirements contract (`414177328..631f2504e`, Codex and Claude gates green 8/10, no blockers) |
| 2026-07-31 | **Flows and platform convergence**: integrated the frozen develop platform foundations into Flow and Builder at their canonical owners; durable object content, Skills, typed identity, generated SDK contracts, and Flow runtime evidence now coexist behind one Alembic head without parallel compatibility paths; frontend builds now use bounded translation output, direct icon modules, and the Bun 1.3.14 workspace lock without unsafe heap overrides (`64fd7446e` integrated, Codex gate green 9/10, no blockers) |
| 2026-07-31 | **Typed Builder stream boundary**: every known SSE event and nested payload is validated before entering frontend state; malformed and unknown events fail closed; one explicit `idle/streaming/failed` lifecycle owns transport and server failures without duplicate banners; structured request identity and backend error codes survive the boundary; DOM tests run in an isolated jsdom project while pure protocol tests stay in the default project (`a2642c1a1`, Codex and Claude gates green 8/10, no findings) |
| 2026-07-31 | **Exact resolved-input evidence**: every admitted attempt now exposes one typed lineage state in evidence views and v16 exports; one tenant/run-scoped batch read stays inside the repeatable-read snapshot and existing attempt-evidence budgets; identity-scoped retention proof prevents foreign markers from creating false purge claims across lineage, manifests, retention, and RAG summaries; malformed data remains explicit corruption; the generated SDK and docs define all states and all four synchronous export safety guards without claiming retrieval proves influence (`4d13889a4`, gate green 8/10 after three same-session passes, no findings) |
| 2026-07-30 | **Canonical Flow attempt input**: one strict immutable envelope now owns the activation start, resolved input, exact per-call question/effective prompt/context version, and one shared preferred/capability-safe model configuration; unsupported parameters are removed before the plan is frozen, mapped JSON capability learning preserves the admitted `N+1` provider-call bound, terminal projections cannot overwrite start truth, and attempt provenance retains only irreconstructible evidence (`2f1447446`, gate green 8/10 after four same-session passes, no findings) |
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
DB proof). Vocabulary neutrality is complete: the unused document-category
contract is deleted, runtime-metadata values are domain-neutral, and the
parallel phrase-owned `case_like_flow` truth is deleted (item 8). M6.6 stays
measurement-gated; M6.7 is superseded by item 2 except
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
6. ~~One canonical attempt-evidence projection~~ — **LANDED**
   `a3d2ba41d..2f1447446`. The strict typed attempt input now owns the exact
   execution snapshot known before provider work: immutable start policy,
   resolved input, ordered per-call question/effective prompt/context version,
   and one shared preferred/capability-safe model configuration. Completion
   parameters are filtered through the selected model's canonical capabilities
   before persistence and dispatch; mapped calls learn one JSON rejection and
   remain inside the admitted `N+1` call bound. Relational provider calls and
   result files remain canonical, terminal projections cannot replace activation
   truth, and attempt provenance v3 retains only irreconstructible RAG,
   completion/tool-call, and citation evidence. `step_result_builder` is the
   terminal projection owner; the executor only orchestrates. The survivor
   matrix, evidence/export readers, retention markers, SDK, and generated
   developer schema all follow that ownership boundary.
7. ~~Resolved-input lineage projection~~ — **LANDED** `4d13889a4`.
   The existing bounded persisted aggregate is batch-projected for exactly the
   admitted attempts inside the repeatable-read snapshot and attempt-evidence
   budgets. A shared attempt-scoped provenance result owns retention identity
   for lineage, serialized provenance, manifests, retention, RAG, and redaction:
   a valid matching marker yields `retention_purged` with exact counts
   (including zero), no valid proof yields `not_tracked`, and malformed or
   foreign markers become explicit corruption without creating false purge
   summaries. The required typed union is generated into the SDK and export v16.
7b. **Bound mapped and structured execution before expensive work** *(high)* —
   `FlowMappedExecutionPolicy` is the current owner but accepts arbitrarily large
   admin values and treats malformed persisted policy as absent; mapped
   cardinality and structured JSON can therefore reach preparation and JSONB
   persistence without a source-owned safety ceiling. Deepen this owner with
   named deployment/storage invariants and admin-configurable effective values
   below them; reject malformed stored policy explicitly; admit mapped
   collection cardinality, aggregate packaged input, serialized structured
   output, and the existing overview/reducer fan-in before provider preparation,
   leaf calls, or persistence. Authoring may expose selected-model reserves,
   admin-effective bounds, structural fan-out, explicit representative-input
   assumptions, and exact headroom for supplied samples; it must not promise that
   unknown future uploads fit or invent provider-call/currency estimates. Fix
   numeric ceilings from the pre-release capacity evidence in item 10, not
   post-hoc observation.
7c. **One authored HTTP timeout policy** *(medium)* — backend configuration,
   authored-schema defaults, runtime fallbacks, and frontend validation currently
   repeat 30/120-second values. Make one backend policy own the effective default
   and maximum, validate positive/default-at-most-maximum deployment inputs at
   startup, expose the effective contract to authoring, and delete duplicated
   frontend/schema/runtime constants. Admins may lower operational values below
   the named deployment safety ceiling; no generic constraints-discovery API.
8. **Builder frontend/server contract closure** *(medium, owner-separated
   slices)* — (a) stream/attachment/draft contract: attachment-limit
   ownership is **LANDED** `478dfeb1c`; runtime SSE validation, fail-closed
   unknown-event handling, and explicit stream failure are **LANDED**
   `a2642c1a1`; remaining work makes the draft lifecycle explicit. (b) make the
   existing cited slot classifier the sole semantic owner for supported
   free-text replies, while explicit answer submissions remain the only source
   of explicit-answer metadata; preserve the user-question budget through a
   typed response-only lifecycle marker, and delete the weaker matcher,
   adjudicator, and dead follow-up paths behind the focused evaluation gate in
   B7. (c) **LANDED `3409a8409`** — typed resolved slots are projected before
   text fallback; the unused document-category contract is deleted and
   runtime-metadata values are domain-neutral; phrase-owned domain inference, including generic
   `underlag`, is deleted with no tolerant readers. (d) serve RAG policy ceilings
   through the existing settings
   response and delete the duplicated admin-page TS constants — no generic
   constraints-discovery API. (e) **LANDED `7fa0c6a16`** — architecture-impact
   commitment admits only explicit, flow-default, requirements-summary, or cited
   high-confidence model evidence without changing the honest confirmation
   buckets. The question-selection follow-up is **LANDED `b1e9b3ae8`** — the
   bounded journey receipt exposed and the implementation deleted the separate
   action-policy forced-ask and prompt reconstruction paths; discovery now owns
   consequential question choice and
   order, confirmed visible slot decisions become typed requirements evidence,
   stale dependent decisions are pruned after input/output changes, and catalog
   custom-answer support is honest. No new assumption ledger, state taxonomy,
   or phrase family was introduced. (f) next, preserve the classifier's already
   validated `explicit`/`inferred` evidence level in `ResolvedSlot`: an exact,
   user-owned cited `explicit` fact may be commit-grade at medium confidence,
   while inferred/medium, missing or invalid citations, low confidence, and
   explicit unknowns remain unresolved. The same provenance owns confirmation
   bucketing; add no second verifier or evidence ledger. (g) make the existing
   confirmation payload honest without changing its wire shape: remove fixed
   process guarantees from assumptions and require exhaustive bilingual labels
   for every catalog slot. (h) after a product decision on purpose-first versus
   input-first vague interviews, delete the remaining processing-goal phrase
   family and move its critic consumer to typed planning/result evidence; do not
   replace it with another matcher. (i) **LANDED `3afe6e947`** — every classifier
   attempt now persists through the existing classifier metadata with a closed
   resolved/no-content/parse-failed/skipped-no-resolvable-slots outcome. Only
   resolved attempts carry or replay facts, provider failures stay in the existing
   provider-turn lifecycle, and no retry policy or second ledger was added. (j)
   move aggregate classifier transcript admission into the
   existing model-aware/admin budget owner only after those attempt outcomes are
   measurable; keep named per-source parser-shape invariants fixed until item 10
   benchmarks them. (k) keep ask/progress/plan/diagram as typed server events
   and frontend projections, delete the dead Builder MCP label-resolver path, and
   add no model-visible presentation tools; an end-result preview is a later
   plan-bound structural projection only if user-value evidence justifies it.
   Directional schemas and precise dataflow are owned by B9/B10 below; multi-stage
   exact-template authoring is owned by B11.
9. ~~Docs-site contract correction~~ — **LANDED** `4d13889a4`.
   The attachment-to-template lifecycle landed with item 5 (`2d608b309`).
   The guide now documents the exact lineage reader/writer contract and all
   four source-owned synchronous export guards, distinguishes retained-byte
   preflight from the additional carried-text check, and prohibits
   material-influence wording through executable contract tests.
10. **Release proof** *(tracked harness plus external live gates)* —
    The durable live evaluation owner is
    `backend/scripts/ai_builder_api_battle_cases.json`: currently 120 unique
    prompts across 46 municipal domains, including vague first turns,
    single-missing-dimension cases, seven required multi-turn dialogues,
    complete JSON/PDF requests, detailed contracts, and human-reviewed applied
    results. After each deployable Builder slice, compare a locked-model smoke
    cohort with the preceding receipt; assess question choice, unsupported
    assumptions, plan topology, schema use, and failure category rather than
    optimizing for one example prompt. The target is a correct first proposal;
    bounded repair remains a safety net and is measured as a degraded path, not
    counted as success. Receipts retain each ordered structured-question payload
    (id, text, option ids, custom-answer support, and turn), question count and
    repetition, first-question fit to the highest-impact unknown, grounded
    assumptions, first-proposal outcome, repair rounds/codes, plan topology,
    directional input/output contract use, review moments, and authoring
    token/call/latency usage. Report true first-pass success separately from
    repaired success and terminal failure. Raw per-run facts are canonical;
    compute p50/p95 only for the frozen three-repetition formal baseline, not in
    single-repetition exploratory receipts.
    The 2026-08-02 120-case run is diagnostic, not a numeric comparison baseline:
    its harness stopped at an unconfigured question and refused a repeated
    question id, so the observed 72/74 plan-ready stops and 321,408 tokens mix
    product over-questioning with evaluator truncation. Source inspection still
    proves the forced-ask defects. The v2 journey contract first records ordered
    question occurrences, exact configured answers, reopening, termination, and
    first-pass versus repaired outcome. Run the locked 12-case smoke against the
    unchanged pre-fix build to decide whether a full pre-fix v2 baseline is worth
    its cost; otherwise use deterministic acceptance tests plus an absolute
    post-fix floor and claim no numeric before/after lift.
    The locked 12-case v2 smoke completed on 2026-08-02 against the unchanged
    Luna route. Harness and transport integrity were green (12 runs, zero case
    errors, skips, or identity failures), but product quality was not: 10 runs
    failed quality checks, including all five selected required cases. Only
    three runs produced plans, all after repair; there were no first-pass
    successes. The journeys recorded 23 questions (15 resolved, seven left
    unanswered because no approved case/profile answer covered the selected
    question, three forbidden, and 11 unclassified), 39 model calls, five
    repair attempts, and 157,763 authoring tokens. Evidence includes document
    questions in the audio journey, an unrelated comparison question in a JSON
    handoff, unnecessary questions for otherwise complete requests, missing
    expected JSON leaves, and one terminal document-report topology rejection.
    This makes a full pre-fix 120-case v2 run both noisy and disproportionately
    expensive. Preserve this smoke as the pre-fix floor, correct corpus answer
    closure only for questions the journey is meant to continue through, fix
    the general question-selection and first-proposal defects without adding
    phrase matching, then rerun the identical 12-case cohort before the full
    120-case release evaluation. Do not claim numeric lift from the earlier
    truncated 120-case receipt.
    The identical locked 12-case smoke reran on 2026-08-03 after the question-
    selection slice with the same harness, corpus and per-case prompt hashes,
    model id, and Luna route. Questions fell from 23 to 10, forbidden questions
    from three to zero, and unclassified questions from 11 to one; plan creation
    rose from three to seven and true first-pass plans from zero to five. Repair
    attempts fell from five to four. The harness recorded 38 model calls and
    154,335 authoring tokens versus 39 and 157,763 before the change, but the
    unknown provider outcome in one post-fix run makes those cost totals lower
    bounds rather than proof of an efficiency gain. The comparison is
    directionally strong but not release-green: nine of 12 runs,
    including four required cases, still failed at least one quality check. One
    detailed audio-to-DOCX proposal duplicated transcription and moved the
    requested transcript review onto the duplicate model step; multiple JSON
    proposals lost required terminal leaf fields; a requested human review was
    attached to the wrong producing step; and the many-document report remained
    compiler-invalid. Two question-order mismatches require manual product
    adjudication before changing policy, and one otherwise complete JSON case
    ended with an explicitly recorded unknown provider outcome after timeout.
    Treat these as owner-level topology, contract-fidelity, review-placement,
    and provider-reliability evidence—not as permission to add prompt-specific
    words or case-specific repair rules. Run the full 120-case diagnostic next
    and use cohort evidence to rank the smallest complete owner-level slice.
    The full single-repetition diagnostic completed on 2026-08-03 at
    `6e0397938` with the same locked Luna model, harness hash, and corpus hash.
    A host interruption split the receipt into 103 + 16 + one clean replacement
    observation; identity verification found all 120 unique case ids with no
    duplicate or missing result. Four attachment/template cases skipped because
    their local file fixtures were not configured, leaving 116 live journeys.
    Sixty-one journeys created plans: 48 true first-pass and 13 repaired; 37
    stopped on an unanswered question and 18 ended in Builder
    proposal/compiler errors. Ninety-seven of 116 live journeys failed at least
    one configured quality check. The Builder emitted 116 questions (79
    resolved, 37 unanswered, zero reopened): only 29 were the preferred
    highest-impact unknown, 49 were allowed, 12 were forbidden, and 26 were
    unclassified. Vague cases averaged 2.92 questions, but only two of 24 began
    with the preferred processing-goal question and 12 asked forbidden low-value
    runtime metadata; 16 of 17 complete everyday cases avoided questions, while
    all 17 still failed a plan/contract quality check. The largest build failure
    was exact JSON retention: 29 leaf-field checks failed, the only exact input-
    schema case failed, and three of four exact output-schema cases failed.
    Human-review producer targeting failed in both applied review cases, and at
    least three of six produced audio plans repeated transcription semantics
    after deterministic transcription. The 61 plans contained 165 steps, but
    semantic duplication and contract loss—not the numeric average—are the
    defect. Recorded authoring work was 335 model calls and 1,367,413 tokens;
    no valid case executed its generated Flow, so runtime efficiency remains a
    topology inference. Treat the receipt as broad diagnostic evidence, not a
    variance baseline or license for post-hoc thresholds. Manually adjudicate
    rubric mismatches, correct clarification stops, and representative journeys
    before promoting a failure to product policy.
    The tracked 12-case `smoke_v3` cohort ran once on 2026-08-04 against the
    served build at `6ccb6f631` (B4(b) included) with the locked Luna route:
    9 live journeys (3 attachment-fixture skips), 5 first-pass plans, 1
    intended clarification stop, 3 Builder errors, 3 questions total, 0
    repairs. No failure is attributable to B4(b): checkpoint projection
    placed exactly the intents planning state held in both review cases. The
    run surfaced (1) checkpoint-classifier over-emission — an explicit user
    refusal of report review was emitted as a `report_text` update, and an
    unrequested `structured_result` review appeared in the complex case; the
    typed owner now makes this precision defect visible, and its fix belongs
    in the classifier prompt/frozen fixtures (B4-family follow-up), not the
    compiler; (2) two `assembly_document_report_compose_topology_missing`
    errors matching the recorded B10(e) residuals; (3) one
    `self_correction_invalid_plan`; (4) persisting duplicate-transcription
    semantics — the typed transcript-text proposal boundary remains the open
    B4 tail. Receipt provenance carries `tracked_clean: false` because the
    served worktree had unrelated user-dirty files; treat totals as
    directional. Cohort note: `smoke_v3` overlaps but is not identical to the
    earlier manual 12-case list, so cross-receipt deltas are directional
    only.
    The full identity-verified 120-case diagnostic then ran once on
    2026-08-04 against the served `6ccb6f631` build (clean client checkout,
    server `GIT_COMMIT`-stamped, locked Luna route). 116 live journeys (4
    fixture skips): 46 first-pass plans, 19 repaired plans, 15 intended
    clarification stops, 10 stalls, 25 Builder errors, 1 interaction-limit
    stop, 0 provider-unknown outcomes, 99 questions; 92/116 journeys failed
    at least one configured check (sentinel verdict: fail, 2 required-case
    expectation failures). Versus the `0ee738f41` baseline this is roughly
    flat in aggregate (64→65 plans; 49→46 first-pass; 23→25 Builder errors;
    116→99 questions) — expected, because B4(b) targeted checkpoint
    ownership, not the dominant failure owners. Decisive ranking signal: the
    25 Builder errors decompose into
    `assembly_document_report_compose_topology_missing` ×10 (the recorded
    B10(e) residuals), `self_correction_quality_failure` ×5 +
    `self_correction_invalid_plan` ×4 (repair exhaustion),
    `assembly_document_report_citations_unsupported` ×4 (newly measured
    report+citations gap, needs a support-or-refuse-before-proposal
    disposition), and `architecture_critic_invariant_failed` ×2. No
    checkpoint-related failure code appears anywhere — B4(b) shows no
    regression at scale. A same-day causal cross-tab over the receipt
    (unique journeys → earliest causal blocker, peer-review-mandated)
    supersedes the first same-day ranking. Unique-journey mass:
    first-question relevance 22 (the purpose-first B7(h) domain; product
    decision recorded 2026-08-04: purpose-first), prose-leaf/schema retention
    20 pure + 9 mixed, report topology (B10(e) residuals) 10 hard terminal
    errors, corpus answer-closure stalls 10, repair exhaustion 9, citations
    4, checkpoint-involved 3. Repair-exhaustion attribution: 5 of 9 trace to
    the phrase-scanning blocking critic rules
    (`explicit_json_contract_request_without_step`,
    `rich_workflow_requires_json_contract_step`) — owned by the
    typed-evidence critic migration, not a new pre-proposal slice; 2 of 9 are
    the parked B9(e2) compare-to-JSON family (two more live evidence cases);
    2 misc. Adopted order after landing B7(j)+B11: (1) B7(h) purpose-first
    question policy plus blocking-critic typed-evidence migration (~27
    unique journeys); (2) prose-leaf recall in the existing `SchemaEvidence`
    owner (~27); (3) B10(e) completion with EXPLICIT separate dispositions
    for policy-unset `None`, unaccepted `None`, and accepted `1` mapped
    limits (10; after B11 lands — shared critic file); (4)
    checkpoint-classifier precision with a refusal/negation prompt
    invariant, deterministic parsing tests, and a locked sv/en
    add/refuse/clear/correct matrix (after B7(j) — shared owner); (5) corpus
    answer-closure and attachment/template fixture configuration (harness);
    (6) a small frozen executed cohort, three repetitions, measured per-step
    tokens/duplicate material, transparent 1000-run extrapolation. The
    report-citations support-or-refuse choice stays a separate product
    decision; the typed refusal stands and detection may move earlier.
    Single repetition: directional, no variance claims.
    Corpus investment (product-owner directive, 2026-08-04; full text in
    local `fablereview/2026-08-04-corpus-strategy/`): keep the generic
    primitives as release gates and add ~7–8 vertical journeys — the
    four-case Sundsvall tjänsteskrivelse flagship family
    (`interview_open_tjansteskrivelse`,
    `advanced_sundsvall_tjansteskrivelse_runtime_sources_docx` with an
    authentic anonymized DOCX template + six-document runtime fixture,
    `edit_tjansteskrivelse_single_section` retention,
    `failure_tjansteskrivelse_template_contract` typed degradation), then a
    real `.oeflow` Open ePlatform food-registration migration, own-sewage
    completeness with downstream-only rerun, and an elevresor governed
    decision packet where deterministic capabilities own eligibility. All
    checks deterministic; the flagship journey is measured EXECUTED
    (per-step tokens, source duplication, local rerun). Synthetic fixtures
    for the four skipped cases are configured first; the user supplies the
    internal fixture packet (anonymized template, matter documents,
    `.oeflow` export, three submissions).
    The corpus/harness slice landed at `c5bc31f22` (five-iteration gate,
    green 8/10): deterministic fixtures un-skip the four attachment/template
    cases, the tjansteskrivelse plan-authoring family (two honest cases)
    anchors on the authentic BUN §17 protokollsutdrag, the loader rejects
    runtime bindings on non-executed cases, and the evaluator gains
    `expected_primary_input_type` validated against proposal AND applied
    flow with mutation-proven behavior tests. Deferred by honesty: the
    template-failure and edit-retention journeys return with executed-cohort
    and edit-session harness support respectively.
    The full 122-case diagnostic at `027689ef5` (2026-08-05,
    identity-verified, all fixtures live, single repetition): 121 live
    journeys — 57 first-pass + 14 repaired plans (65→72 total, repairs
    down), 19 Builder errors (25→19), 17 intended stops, 8 stalls, 12 clean
    plans (9→12). Structural wins: `compose_topology_missing` 10→0 (B10(e)
    eliminated its family), citations 4→1, fixture skips 4→1, preferred
    questions 29→37, preferred-first rate 46%→54%. Fresh causal ranking:
    leaf/schema retention ~34 (unchanged top owner; prose-leaf slice with
    raw-response attribution first), question rubric 20
    (first_question_relevance ×18 persists — adjudication needed),
    repair exhaustion 15 (action_followup_requires_followup_fields ×8 —
    candidate durable fix is compile-time canonical obligation completion
    plus prompt contract, prevention not repair;
    aggregate-to-JSON ×3 = the decided B9(e2) slice), stalls 8 (answer
    closure; flagship docx_output_mode candidate rule: confirmed template
    attachment resolves it). Strategy peer review of this ranking in
    progress; next slices dispatch from its adjudication.
    Product decisions recorded 2026-08-05: compare/corpus-to-JSON is
    SUPPORTED (B9(e2) becomes an implementation slice) and document-report
    CITATIONS are SUPPORTED (carry citation identity through compose/render
    in the document_report owner; replaces the
    assembly_document_report_citations_unsupported refusal; 4 live cases).
    First tjansteskrivelse/attachment cohort attempt (2026-08-05,
    `7d791c41a`): attachment cases still fixture-skip pending the
    post-upload evidence-SHA capture loop (file IDs uploaded; capture in
    progress). The vague tjansteskrivelse interview case showed run-to-run
    variance: one run asked a non-preferred first question and errored, the
    next produced a first-pass two-step plan but asked zero questions where
    the rubric requires at least one — a purpose-first ask-rate signal to
    watch across repetitions, not yet a policy change.
    The post-B7(h) smoke_v3 run (2026-08-05, served `a4894ee63`, locked
    Luna route, 9 live journeys) shows purpose-first live: every asked first
    question rated preferred, zero forbidden questions, the prior
    unanswered-question stall now completes as a repaired plan (6/9 plans),
    and the two remaining Builder errors are the recorded B10(e) residuals.
    No checkpoint or admission regressions. Single repetition: directional.
    A 2026-08-03 source-verified Fable review ranks the product work without
    creating another roadmap. First preserve the classifier's validated
    explicit evidence level through `ResolvedSlot`, action admission, replay,
    and confirmation; the current projection drops it and therefore re-asks
    facts already stated by the user. Second retain bounded, cited,
    prose-enumerated JSON leaf names as typed planning evidence, while reusing
    the existing exact `SchemaEvidence` owner for declared/example schemas and
    keeping report headings separate. Third split deterministic proposal
    failures by owner: aggregate/compare plus JSON is decidable from committed
    architecture before provider work and awaits a support/refusal product
    decision, while document-report compose topology depends on proposed steps
    and must become total deterministic compiler lowering for every supported
    report disposition. Fourth, carry typed checkpoint intent onto the actual
    producer: audio transcript review belongs on the fixed transcription step,
    downstream review remains on its semantic producer, and the contradictory
    prompt instruction to author another transcription step is deleted without
    deleting legitimate downstream transcript-input guidance. Fifth, simplify
    the existing confirmation contract rather than expanding it: remove two
    fixed process guarantees from assumptions and make catalog labels
    exhaustively bilingual. Last, after the human question-order decision,
    delete processing-goal phrase inference and move action-follow-up critic
    enforcement to typed planning/result evidence. These are owner-level
    changes; no phrase detector, duplicate-step matcher, global step cap,
    second schema ledger, or new confirmation API is accepted.
    A complete, identity-verified 120-case diagnostic then ran at `0ee738f41`
    with all fixtures present. It produced 49 first-pass plans, 15 repaired
    plans, 15 correct clarification stops, 12 unanswered-question stalls, 23
    Builder errors, four provider-unknown outcomes, one unconfirmed journey,
    and one applied-case precondition failure. The 64 plans contained 165
    steps; authoring recorded at least 343 model calls, 1,539,175 tokens, and 19
    repairs. JSON remained the weakest cohort: 11 related-document-package
    journeys failed only because file cardinality was misderived as Flow fan-in,
    29 requested-leaf checks failed across extraction misses, evaluator aliases,
    and journeys that never reached a plan, and four blocking critic failures
    still depended on raw phrase markers. Audio evidence still showed duplicate
    transcription semantics and misplaced review. A source-verified Fable High
    review therefore re-ranks the next Builder work as: (1) correct document-
    package admission; (2) persist typed classifier attempt outcomes; (3)
    deepen noun-phrase leaf recall inside the existing `SchemaEvidence` owner;
    (4) move remaining committed-slot contradictions before proposal and make
    supported report lowering total; (5) add typed checkpoint intent plus the
    transcript-text proposal boundary; (6) move blocking critic rules to typed
    evidence; (7) after product decisions, delete goal phrase inference and gate
    metadata timing; (8) close evaluator aliases and answer coverage before the
    next full diagnostic. This order is authoritative. The first correction
    landed at `85516be94`; the second landed at `3afe6e947` and adds attempt
    observability without changing interview decisions. Neither decides genuine
    compare/corpus-to-JSON support. Use the locked smoke plus the affected cohort between slices; save
    another full 120-case run for a multi-slice diagnostic checkpoint.
    The affected 11-case related-document JSON cohort then ran once against
    product behavior `85516be94` with the locked Luna route and the latest
    harness. Seven journeys reached plans (three first pass, four repaired) and
    five passed every configured case check. The former aggregate/JSON failure
    remained in only the procurement journey, whose prompt explicitly requests
    same-run comparison and therefore belongs to the unresolved B9(e2) product
    decision rather than the related-package correction. Residual failures were
    separately owned: one typed critic source-capture issue, one incomplete
    self-correction payload, one prose-leaf miss, one allowed rather than
    preferred first question, and one unanswered question. The cohort still
    spent 36 model calls, 177,127 tokens, and eight repair attempts. Treat this
    as directional proof that related-package admission is no longer the shared
    blocker, not as a broad quality or efficiency win; later slices must remove
    the newly exposed owner-specific failures before the next full diagnostic.
    The identical 12-case smoke ran once more on 2026-08-03 after explicit-
    evidence admission landed at `5e7956f8d`. The per-case prompt hashes and
    locked Luna route matched the preceding receipt. Plan creation rose from
    seven to nine and first-pass plans from five to six, while total questions
    stayed at ten and unclassified questions fell from one to zero. The same
    run also added one forbidden metadata question, one repair attempt, six
    model calls, and 18,021 authoring tokens (44 calls and 172,356 tokens in
    total). Offline reanalysis of both receipts with the same final harness
    rules found nine of 12 product-quality failures in each. Four JSON journeys
    still lost required terminal leaf names, the complex audio plan still
    duplicated transcription and misplaced transcript review, one ambiguous
    report skipped its required disposition question and assumed a combined
    overview, and two journeys ended in deterministic Builder errors. Treat the
    extra plans as directional evidence that explicit facts now reach proposal,
    not as an aggregate quality or efficiency win. The harness and corpus were
    edited concurrently by another workstream during the live run, so its
    source-identity check correctly failed; the in-memory journeys remain useful
    evidence, but this receipt is not a release gate and must not be used for
    p50/p95 or variance claims. The tracked smoke cohort may replace manual case
    lists only after its attachment and six-file runtime fixtures are configured
    and its harness/corpus revision is frozen before execution.
    Question review also records whether the question is answerable from the
    user's perspective, non-leading, offers sufficient option coverage or a
    usable custom-answer path, resolves after its answer, and avoids reopening
    already settled requirements. Proposal review uses a requirement-coverage
    matrix rather than one overall score: primary input, secondary runtime
    fields, prompt variables, targeted Underlag, directional schemas, requested
    output shape, justified review checkpoints, and deterministic versus
    model-backed work. It flags redundant steps, duplicated or unrelated
    context, unsupported assumptions by severity, and needless model calls.
    Applied cases compare the built contract with actual execution evidence,
    including per-step token use and schema/artifact validity; plan plausibility
    alone is insufficient.
    Segment comparisons by vague, single-missing-dimension, complete,
    attachment/template, JSON, audio, form-field, and human-review cohorts;
    aggregate improvement cannot hide a critical-cohort regression. Pin the
    baseline commit, corpus/harness hashes, model/provider route, UI language,
    and configuration; repeat observations to measure output variance, include
    paraphrase and Swedish/English intent-equivalence pairs, manually
    adjudicate representative wins and failures, and execute applied cases where
    the harness supports it so a plausible plan is not mistaken for a correct
    Flow. Promote a failure to a deterministic product test only when it
    expresses a general rule. Before the release-gate
    live run, freeze in the tracked gate input: three repetitions, required
    cases, non-municipal domain families, provider route/model identity, and
    numeric p50/p95 latency + token/call ceilings (the corpus still has only
    municipal-domain cases and no frozen numeric thresholds; thresholds must
    never be chosen after observing results). Benchmark and freeze the Builder platform ceilings
    for attachment count, message length, per-file and aggregate DOCX
    inspection, placeholder evidence, and synchronous parser capacity before
    production; the current safety values are conservative bounds, not
    certified best-practice capacity. Freeze selected-model semantic thresholds
    for the cited classifier's supported slots before live evaluation, including
    Swedish/English exact-label, paraphrase, negation, ambiguity, adversarial,
    and topic-change cases; benchmark aggregate classifier context plus the
    named source-count and structured-value shape ceilings. Include exact input
    plus output schema direction, confirmed form-field consumers, targeted
    Underlag, a simple one-step transform, checkpoint/template behavior, and a
    frozen representative high-cardinality exhaustive-processing case. Repeated
    runtime economics use measured representative runs and visible assumptions;
    any x1000 figure is arithmetic over that evidence, never a guessed estimate.
    Preserve raw receipts. Then: server build identity, structural goldens (BM5.2–5.4),
    HTTP-secret deployment inventory (M2.9 operational half; with zero users any
    hit means reset/delete), branch-protection evidence (BM0.2).

**Product decisions adopted as defaults (owner may override):** token
totals survive debug retention via a typed tombstone summary rather than
an explicit `retention_purged`-only state; exactly one template attachment
is required per template-fill step (multiple template-role files become a
structured question); release-gate numeric thresholds are product-owned
inputs to be fixed before execution.

**Deferred:** export streaming/pagination transport until item 2 exists and
measured refusal metrics justify more; document-render offloading (M6.6)
until loop-lag/heartbeat measurements with maximum-size inputs demand it;
hierarchical single-source chunking or cross-source reduction until B12's frozen
two-condition gate is met.
**Rejected:** standalone test-factory consolidation (three local `File`
constructors stay local until a real contract emerges); any new snapshot
coordinator/query-bus/per-repo-session machinery; a second aggregation
service for token totals; a separate "official decision basis" store; internal
Builder MCP for native question/progress/plan/diagram/preview actions; importing
a generic agent/workflow runtime beside Eneo's compiler and Flow runtime.

## Builder-excellence track (source-verified 2026-08-01)

Source: the initial review of Builder intent-understanding, attachments, HITL,
and generated-flow efficiency against `10ccd6b94`, refreshed against current
source after the platform merge and a whole-system review of schema direction,
Underlag/form-field dataflow, large-input topology, exact template workflows,
native UX tools, and official Dify/n8n/Flowise/LangGraph/PydanticAI patterns. The
refresh verified explicit-answer provenance end to end, rejected a disproven
question-exhaustion crash, found the classifier's exact supported-slot boundary,
and froze the semantic-owner and question-lifecycle sequence below. The external
systems support typed map/loop/HITL/projection patterns; none becomes a parallel
Eneo runtime or source of executable topology.
`production-roadmap.md` is the SOLE execution authority; the retired BM
ledger is evidence only. (`goal.md`/`notes/handoff.md` still name retired
roadmaps — user-owned dirty files, flagged to the human owner.)

**Builder target contract:** authoring may spend extra tokens to understand the
municipal process before compiling a Flow. One cited semantic-understanding owner
records what is known, missing, ambiguous, assumed, and supported by attachments;
server policy asks one relevant unresolved high-impact question at a time and
shows material assumptions at confirmation. It must not infer intent through an
ever-growing Swedish/English synonym table or treat free text as an explicit UI
answer.

Each generated step's prompt/instructions owns the task, quality criteria, and
required result. Compiler-owned **Underlag till text** supplies only the source,
attachment, form-input, or prior-step material that step needs; it does not
duplicate the prompt or forward every upstream result. Confirmed
**inmatningsfält** retain exact names and types, remain distinct from the primary
runtime input, and have explicit semantic consumers. Exact JSON input and output
schemas may coexist and compile onto their correct Flow boundaries. The Builder
chooses the fewest steps that preserve quality: split only for a real context,
model/tool, typed-artifact, retry, checkpoint, or deterministic-render boundary,
and merge adjacent model calls that use the same evidence for one coherent task.
Attachments retain explicit roles, and an exact output template remains the
deterministic rendering authority. High-cardinality uploads are a capacity and
recovery gate for this contract, not the center of the Builder design.

Product defaults adopted (owner may override): an uploaded fillable
template binds as an immutable TEMPLATE_FILL asset (exact layout); an
example-output attachment derives bounded structure/style/schema
constraints surfaced at confirmation — never exact-visual-fidelity
claims. Checkpoint vocabulary freezes to FlowStepReviewMode (view/edit).

Hard ordering constraints: the B5a prerequisite for item 2c is complete
(`4b0796152`); B5b follows B1; B2 runs evidence → interpretation → binding;
B7 runs semantic ownership → typed projection → vocabulary neutrality →
architecture commitment → transcript admission; B9 then closes schema direction,
B10 closes semantic dataflow, and B4/B11 close checkpoints and exact-template
topology before item 7b's remaining capacity work. B9's first terminal-output
guard may start after B7(a) if it does not overlap a changing owner; do not create
parallel edits in the same files. Item 7b precedes any B12 capability. The ranked
plan above controls all other ordering.

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
- **B3**: **LANDED `dc4a3a943`**. No silent guessing after question-budget
  exhaustion: every registered quality question has an explicit terminal policy
  if it enters the budget decision; architecture and explicit `ask` questions
  remain askable; the only default is surfaced at confirmation and persisted.
  The seven registered quality ids and seven policy keys are pinned equal; the
  earlier claim of a current unknown-candidate crash was disproven. *(M)*
- **B4** (two ordered slices): (a) **LANDED `b70a91dc1`** — the understanding
  pass records typed, cited checkpoint intents and confirmation exposes them.
  (b) **LANDED `3c2a1faf1`** — compile/apply and the critic share one canonical
  requested-versus-compiled checkpoint predicate with tri-state set/clear
  intents; transcript review projects onto the fixed transcription step; the
  duplicate-transcription proposal instruction is deleted; the edit lane
  enforces the existing-Flow baseline with intent-scoped releases. No parallel
  HITL classifier, phrase detector, or duplicate matching rule was added. *(M)*
- **B5a** (= item 2d): **LANDED** `4b0796152`. *(S)*
- **B5b** (= item 4b): **LANDED** `5509eef84..fb6934b5a`. Factual execution
  shape, shared mapped-execution ownership, heuristic-lint deletion, and
  `measured_no_change` for speculative new critic invariants. *(M)*
- Generated-flow proof is not a standalone B6 slice. Each owning slice carries
  its behavior tests: form variables (inmatningsfält), targeted underlag per
  step, enforced JSON input/output schemas, unusual-input resilience, and
  deterministic zero-call behavior. Measured economics stay in item 10.
- **B7** (= item 8b/8c deepened, ordered owner slices): (a) **LANDED
  `cbc1132e2`** — one gated semantic-owner series deleted the unused
  discovery-follow-up and readiness
  paths, adds one typed `question_response` marker containing only the pending
  user-requirement question id, preserves distinct-question budget counts through
  compaction, freezes focused Swedish/English exact-label, paraphrase, negation,
  ambiguity, adversarial, and topic-change fixtures for the classifier's
  supported slots, then deletes the deterministic option matcher, uncited
  adjudicator, and duplicate provider-call gate. Only explicit request answers
  produce `question_answer`; supported free text resolves as cited model evidence;
  unsupported option questions remain honestly unresolved and re-promptable.
  Offline exact-label and negation contracts must be 100%; if exact-label cannot
  pass through the real classifier prompt/parse/bias contract, retain only exact
  normalized equality through the cited-evidence path, never explicit-answer
  metadata. Question policy asks only for unresolved information that can change
  the Flow's contract, topology, quality, or governance; the confirmation surface
  exposes consequential assumptions instead of hiding them. (b) **LANDED
  `65af265bb`** — typed resolved slots are canonical in the discovery profile and raw
  text resolves only missing dimensions. (c) **LANDED `3409a8409`** — correct
  the known neutral vocabulary defects, delete `case_like_flow` and the unused
  deterministic document-category question, and pin the resulting question topology; generic
  source-material wording no longer invents a domain or purpose. (d) **LANDED
  `7fa0c6a16`** — architecture-impact dimensions do not commit from policy
  defaults or heuristics and confirmation buckets remain honest. (e) **LANDED
  `b1e9b3ae8`** — discovery priority owns the question order, the forced-ask and
  prompt-reconstruction paths are deleted, confirmed visible slots project as
  typed requirements evidence, dependent answers reconcile after architecture
  changes, and fixed-choice custom-answer behavior is honest. (f) **LANDED
  `ef4a45416`** — preserve the classifier's already validated evidence level in
  `ResolvedSlot`, admit exact user-owned cited explicit facts at medium confidence,
  keep weaker evidence unresolved, and use the same provenance for honest
  confirmation bucketing.
  (g) **LANDED `ff9bacdee`** — fixed process guarantees no longer appear as
  assumptions; concise summary labels are owned by the canonical bilingual
  Question Catalog, cover every slot in Swedish and English, and fail closed
  instead of exposing internal identifiers; the public payload is unchanged.
  (h) **LANDED `5b018c604`** — purpose-first
  is enforced end to end: typed classifier evidence (unknown or
  low-confidence goal) creates the purpose question, the action policy ranks
  it ahead of every core gap except primary input, and the emitted turn
  decision is protected by a seam test. The processing-goal phrase family and
  its behavior-locking tests are deleted, and the three blocking critic
  rules (explicit JSON contract, action follow-up with canonical
  Swedish-capable obligation roles, typed field reuse) decide from
  commit-grade typed evidence with their marker tables removed
  (six-iteration Codex gate, final green 8/10). (i) **LANDED `3afe6e947`** —
  persist typed classifier attempt outcomes in the existing metadata owner, with
  resolved as the only fact-carrying/replayed outcome and provider failure owned
  separately. (j) **LANDED `961c8c63f`** — one
  classifier-owned admission predicate measures the complete request (fixed
  prompt, response schema, attachment sources in classifier rendering,
  transcript sources) against the selected model's window minus output/safety
  reserves; the admin conversation reserve is transcript capacity attachments
  must yield to, attachment context refits under the same predicate, budgets
  are required integers, and local rejection persists as the closed
  `skipped_context_budget` no-call outcome. The fixed 12,000-character
  aggregate cap is deleted; source-count and structured-value bounds remain
  named parser-shape invariants pending item 10 (three-iteration Codex gate,
  final green 8/10). *(L)*
- **B9** (directional JSON contracts, ordered owner slices): (a) **LANDED
  `0b7a450df`** — schema presence no longer changes terminal output before
  output direction is owned; a runtime-input schema plus requested generated
  DOCX remains DOCX through compilation, attachment-only classification cannot
  own the terminal choice, and schema evidence remains available for the
  directional owner without misleading confirmation or proposal instructions;
  (b) **LANDED `8f78a04fc`** — rename the already-neutral evidence value to
  `SchemaEvidence` and let `PlanningState.schema_resolution` retain at most two
  canonical shapes plus independent input and output assignment evidence, so the
  same near-limit schema is persisted once when both boundaries use it and no
  compatibility reader is required; deterministic
  parsing proves schema shape, while explicit or cited user evidence assigns a
  boundary direction and one typed question resolves genuine ambiguity; a schema
  may remain validation/reference material; provenance and candidate ceilings
  refuse explicitly instead of truncating; (c) **LANDED `f465e9a6d`** — compile
  input evidence onto the first Flow-input JSON consumer and output evidence onto
  the terminal JSON contract; the real JSON golden asserts both contracts through
  canonical authoring, and unsupported composite bindings fail without entering
  model repair. One parser, one evidence type, and one bounded in-state resolution
  aggregate—not a reusable schema registry or second ledger. (d) **LANDED
  `e26328be6`** — retain bounded, cited open-vocabulary JSON leaf names stated in
  prose as planning evidence and
  compile them through the existing terminal schema owner; explicit full schemas
  win conflicts, and ordinary lists, report headings, and form fields must not
  become output leaves. Refuse ambiguous or over-limit enumerations instead of
  truncating. (e1) **LANDED `85516be94`** — related document packages are
  linear multi-file input, not cross-step aggregation; only explicit same-run
  comparison selects non-linear dataflow, so package-to-JSON compilation no
  longer reaches the aggregate-output rejection. (e2) **product decision 2026-08-05: SUPPORTED** — genuine
  compare/corpus synthesis may terminate in a JSON contract. Implementation
  slice: one shared architecture-compatibility predicate before provider
  work plus compare-to-JSON compiler support; assembly's rejection remains a
  fail-closed invariant for genuinely impossible internal plans. Queued
  after prose-leaf recall. *(M)*
- **B10** (precise semantic dataflow, ordered owner slices): (a) **LANDED
  `7ffaf5f6b`** — project exact confirmed form-field names/types from `PlanningState`
  into proposal context, keep existing `uses_form_fields` as the semantic
  consumer contract, delete the final-step auto-placement fallback, and fail
  with structured feedback when a field has no actual consumer; (b) **LANDED
  `b02529d5d`** — validate compiled typed source refs through the shared binding
  contract and return a named repairable Builder compile error instead of
  degrading an invalid ref to rendered strings; (c) **LANDED `732c7cffb`** —
  compile exact input schemas for explicit structured Underlag projections,
  validate and resolve them through one shared contract, and remove broad
  `all_previous_steps` fan-in where declared dependencies are sufficient;
  post-transcription steps now describe the text they actually receive rather
  than asking a text-only model call to transcribe unavailable audio. The
  model names semantic obligations; only the compiler creates bindings and refs.
  Generated prompt/instructions describe the task and result; compiled Underlag
  owns the selected material. Behavior tests prove that prompts do not duplicate
  Underlag or unrelated prior outputs and that form variables appear only at
  their declared consumers. A 2026-08-02 live audio-to-PDF baseline used five
  steps and three completion calls (6,353 input plus 5,337 output tokens); its
  later semantic steps received overlapping raw and structured transcript
  material. Treat those calls as potentially quality-bearing: acceptance is
  narrower declared dependencies with output-quality parity, not call deletion
  for its own sake. A second large-audio run exposed the correctness failure:
  backend transcription produced 57,768 characters, but the next text-input
  step was still instructed to transcribe an unavailable audio file and emitted
  a schema-valid refusal; later steps recovered only because they also reread
  the raw transcript, spending 52,640 completion-input and 10,301 output tokens.
  Fix the topology and actual-input instructions at the compiler boundary; do
  not add language-specific refusal matching. No generic dataflow DSL. (d)
  **LANDED `aa411ec1c`** — every typed source-capture requirement now survives
  compilation: the fixed eight-field, 96-character description, and 900-character
  block limits plus substring-based suppression are deleted instead of replaced
  by another Builder heuristic. The compiler renders the complete admitted
  `SourceCaptureField` set, while the selected Flow-step model's existing
  save-time prompt admission and typed runtime context-window refusal remain the
  fit owners. More than eight fields, a complete long description, and a short
  name already occurring inside authored instructions are covered without a
  duplicate test matrix or admin setting. (e) **LANDED `fc5a7395d`** — report lowering is total for every
  committed disposition: multi-step plans lower without model-named
  documents arrays, retained structured producers bind into composition,
  requested sections survive as typed {original_label, derived_key} pairs
  (collision-proof keys, escaped grammar, verbatim labels), one canonical
  producer/field selection carries through binding, postcondition, critic,
  and single-call guidance, the three mapped-limit states have explicit
  behaviors, and report-shape admission moved from assembly/create.py into
  the document_report owner. The fail-closed assembly invariant remains for
  corrupt plans (seven-iteration Codex gate, final green 8/10). *(M)*
- **B11** (exact-template workflow topology): **LANDED `37777fab1`** —
  template flows admit model-authored analysis/validation stages between the
  fixed backend reader and the fixed TEMPLATE_FILL terminal (product
  decisions 2026-08-04: bounded model discretion, reader stays fixed; product
  default: at most five preparation stages, one shared predicate on create
  and edit with the model-repairable
  `template_preparation_stage_limit_exceeded` rejection). Critic guards are
  binding-aware, not mode-exempt; a review policy can never sit on the fill
  step (`template_fill_review_forbidden`, all lanes);
  `template_attachment_unreadable` is non-model-repairable. Placeholder
  completeness, atomic asset binding, exact layout, and zero-token fill are
  unchanged and runtime-proven (four-iteration Codex gate, final green 8/10;
  edit lane verified behaviorally compatible). Live template-cohort proof
  awaits the fixture configuration recorded in the corpus directive. *(M)*
- **B13** (action-followup contract compilability, live-defect slice):
  **LANDED `7d970f5ba`** — a real user session (2026-08-05, audio→PDF
  meeting follow-up) died after four repairs on
  `action_followup_requires_followup_fields`; the DB-recovered conversation
  proved an unwinnable loop: no completion path covered document flows
  without a JSON producer, terminal text fields were folded away before
  completion looked, and role matching was exact-ASCII/leaf-only. Now the
  compiler owns the outcome contract wherever the Builder owns the schema:
  terminal/single-step JSON completion in place; a compiler-inserted
  follow-up extraction step for text/document flows with required roles,
  with the terminal writer explicitly bound to BOTH narrative and
  extraction through typed `PlannedStep.previous_output_refs` (validated:
  future/flow-input/fan-in refs reject); user-pinned exact schemas win
  everywhere (assembly never appends; the critic applies the same
  precedence); role recognition is a closed diacritic-folded vocabulary at
  any schema depth; insertion is gated on
  `ResultContract.required_output_field_roles` carried through
  `CreateCompileContext` (name inference deleted); both assembly completion
  paths share one role-aware merge (no Swedish/canonical duplicates);
  empty field lists no longer log as dropped. Three-round Codex gate
  (4→7→green 8/10, final round zero blockers, independent probes).
  Follow-up owned by the strategy program: lossless-or-rejected
  output_fields admission at the parser boundary (slice B). *(M)*
- **B12** (large-corpus capability gate, deferred): item 7b first bounds the
  current per-source/per-item leaves and existing overview/reducer before any leaf
  call is paid, while authoring surfaces only factual policy/model shape and
  explicit assumptions. Implement hierarchical processing only when a frozen
  municipal release case both (1) requires exhaustive synthesis whose typed
  aggregate exceeds one selected-model context after per-source structuring and
  (2) is blocked by the honest refusal. If triggered, split individually oversized
  source chunk/map/reduce from cross-source hierarchical reduction; each needs
  deterministic batching/order, bounded calls/context/storage, explicit
  partial-versus-atomic failure, persisted restart progress, source/span
  provenance merge, and no silent summary replacing original evidence. Selective
  stable-corpus lookup remains RAG, not exhaustive coverage. *(gate, not current
  implementation commitment)*
- The resource-limit audit leaves bounded follow-ups with existing owners: B7
  owns classifier transcript admission and response-marker compaction; source and
  output compaction heuristics change only with their semantic owner; item 10
  measures attachment/parser/classifier budgets and the proposal
  spend/reliability guard before any policy change. Planning/proposal
  persistence and run-evidence/export bounds remain fixed backend invariants
  unless storage or runtime measurements justify changing their owners.
- **B8** (deferred): skills value gate — offline comparative evaluation
  (same briefs with/without a curated playbook) before ANY coupling;
  free-text admin guidance REJECTED (unversioned prompt ownership). This is an
  evidence gate, not an implementation commitment; only proven lift may create
  a later scoped roadmap item.

## Adopted solo program (2026-08-05 final peer session, artifact
`codex-peer-loop-122-case-diagnostic-strategy-review-20260805T193100Z`)

Peer budget is paused for several days; the final diag122-strategy session
(iteration 3, min 7, every correction accepted without dispute) is the
governing spec. Commits land self-validated (full flows suite, pyright,
ruff) and are recorded here as UNGATED for one batch peer review when quota
returns. Execution order and binding decisions:

1. **A-closeout** (action-followup prevention completion):
   `render_result_contract_prompt_block` renders the five required roles +
   the extraction-producer requirement for readable outcomes; a
   no-provider runtime input-resolution test proves the terminal writer
   receives BOTH narrative and extraction at runtime; the critic's
   pinned-schema exemption narrows from any non-template evidence to
   `source == "declared_schema"` only.
2. **Loss-matrix checklist** (four rows: prose schema, proposal fields,
   result obligations, file-role explicitness; transition ->
   preserve/derive/reject -> owner -> failure code -> behavior test);
   created before B, filled during slices, never a subsystem.
3. **B strict admission**: accept None/empty/typed drafts/canonical
   complete-object lists ONLY; reject strings, string lists, dict-of-name
   maps, missing names/properties, unknown types, over-depth objects —
   whole-proposal rejection via ProposalIntentArgumentError with
   first-decisive-error feedback naming the exact path; no field_N
   invention, no downgrades, no partial retention.
4. **C prose-leaf**: FIRST capture the real raw classifier response at the
   pre-parse boundary (attribution report §122); typed
   ProseOutputFieldHint(name, container_kind) delta; one SchemaEvidence
   with a semantic predicate over `source` (declared=exact, prose=name
   hints, inferred=open hint, template=template); ONLY declared_schema
   pins the terminal contract (compiler line ~890 narrows accordingly);
   unrepresentable quoted literals refuse visibly.
5. **E1 evaluator semantics v2** (before D so live measurements are
   trustworthy): the 7-step first-question rule from the artifact;
   cases-file v5 + question_relevance_semantics_version 2 in receipts; no
   cross-version rate comparisons.
6. **D compare->JSON**: narrow the nonlinear rejection to aggregate only;
   supported topologies per artifact; the ALL_PREVIOUS_STEPS fallback must
   be impossible for compare->JSON (typed rejection instead).
7. **E2**: the four terminal-before-unresolved-purpose product defects.
8. **F DOCX explicitness**: FileRoleEvidence.evidence_level (required for
   model source, forbidden otherwise, schema version bump); auto-resolve
   template fill only for explicit authored choice, structural
   placeholders, or exactly-one explicit commit-grade user-owned template
   role; corpus answer-closure separate.
**Ungated commits awaiting batch peer review** (self-validated: full flows
suite + pyright + ruff): `8e720e359` A-closeout (prompt roles +
declared-schema-only critic exemption + runtime input-resolution proof);
slice B strict output_fields admission (lossless-or-rejected, this series).
Loss-matrix checklist: `notes/loss-matrix.md`.

9. **G citations**: write ONLY the red end-to-end test
   (test_document_report_citation_survives_compose_render_and_public_artifact
   per the artifact's exact assertions); keep
   assembly_document_report_citations_unsupported; no solo implementation.
   This is the named riskiest-solo-failure guardrail.

**Rejected as overengineering**: a second assumption ledger (the
ResolvedSlot -> action-policy -> confirmation surface already exists); a
provenance enum on explicit-answer metadata after inferred producers are
deleted; a token/currency cost estimator; a numeric step-count knob; per-step
rationale fields; attachment RAG/indexing; model-visible native Builder MCP
presentation tools; dynamic/unpinned MCP catalogs as orchestration or permission
owners; generic LangGraph/PydanticAI/Dify/Flowise/n8n runtime adoption; module
splits driven by line count (the critic/compiler/metadata modules are deep, not
defective — the debt is duplicated semantic ownership).

## Update protocol

Landing a slice updates this file in the same commit series: move the item
to Landed with its SHA, re-rank if evidence changed, record newly accepted
follow-ups. Peer-gate scores and artifacts stay in `.codex/artifacts/`
(untracked); this file records outcomes only.
