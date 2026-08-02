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
- Evidence vocabulary: retrieved ≠ included-in-prompt ≠ material influence.
  Exports are complete-or-refuse; views narrow honestly and say what they
  left out.

## Landed (most recent first)

| When | What |
|---|---|
| 2026-08-02 | **Trustworthy Builder journey evaluation**: the 120-case v4 corpus now continues through bounded configured interviews, records ordered and reopened questions plus first-pass/repair outcomes, checks directional JSON contracts through applied flows, preserves one v2 case/failure identity across every receipt, and gates only the seven required cases; benchmark failures remain visible without blocking release (`22ece969a`; Codex and Claude gates green 8/10, no blockers) |
| 2026-08-02 | **Evidence-backed Builder architecture admission**: architecture-changing slots now commit only from explicit answers, existing-flow defaults, a typed confirmed-requirements projection, deterministic attachment structure, or citation-backed high-confidence model evidence; policy defaults and heuristics remain visible assumptions but cannot silently shape topology. The create compiler consumes only the persisted architecture commit, and the language-specific requirements-summary parser and draft/raw-slot compiler fallbacks are deleted (`this change`) |
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
   buckets. A 2026-08-02 live run then exposed a separate action-policy defect:
   neutral defaults and heuristics were deliberately non-commit-grade but every
   such architecture slot was forced back into the ask set. Land the bounded
   journey receipt in item 10, then delete that forced-ask path, freeze confirmed
   visible slot decisions as typed requirements-summary evidence, make catalog
   custom-answer support honest, and route first-question order through the
   existing discovery-priority owner. No new assumption ledger, state taxonomy,
   or phrase family. (f) persist every classifier attempt with a closed
   resolved/no-content/parse-failed/skipped-no-resolvable-slots outcome; add no
   retry policy. (g) move aggregate classifier transcript admission into the
   existing model-aware/admin budget owner only after those attempt outcomes are
   measurable; keep named per-source parser-shape invariants fixed until item 10
   benchmarks them. (h) keep ask/progress/plan/diagram as typed server events
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
- **B7** (= item 8b/8c deepened, five ordered owner slices): (a) **LANDED
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
  defaults or heuristics and confirmation buckets remain honest. (e) current
  corrective series: the v2 journey receipt lands first; then delete the
  action-policy forced-ask path, project confirmed assumptions into typed
  requirements-summary evidence, close custom-answer emission/validation, and
  reuse discovery priority for the first question. (f) persist typed classifier
  attempt outcomes. (g) only then join aggregate classifier transcript admission
  to the existing model-aware/admin budget owner while source-count and
  structured-value bounds remain named parser-shape invariants pending item 10.
  No classifier expansion for intentionally structured-only lanes. *(L)*
- **B9** (directional JSON contracts, three ordered slices): (a) **LANDED
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
  aggregate—not a reusable schema registry or second ledger. *(M)*
- **B10** (precise semantic dataflow, three ordered slices): (a) **LANDED
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
  not add language-specific refusal matching. No generic dataflow DSL. *(M)*
- **B11** (exact-template workflow topology): after B4's checkpoint-intent owner
  is available, allow justified analysis/validation/review stages before the
  existing deterministic TEMPLATE_FILL terminal step. Preserve the exact selected
  attachment, placeholder completeness, atomic asset binding, zero-token fill,
  and typed rejection behavior. Prove “analyze, validate, then fill this exact
  template” without permitting model-authored render mechanics. *(M)*
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
