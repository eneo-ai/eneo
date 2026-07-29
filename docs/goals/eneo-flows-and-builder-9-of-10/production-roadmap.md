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
- Working model: Codex workers implement frozen specs; Codex peer gates
  challenge plans and diffs (green ≥8 to land); Claude orchestrates, judges
  every diff against source, owns git.
- Evidence vocabulary: retrieved ≠ included-in-prompt ≠ material influence.
  Exports are complete-or-refuse; views narrow honestly and say what they
  left out.

## Landed (most recent first)

| When | What |
|---|---|
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

From the retired program's OPEN-WORK ledger: **A remains open** (public
token totals still sum legacy attempt columns `NULL→0` with no completeness
state — item 3). **B remains open** (the planning-state payload cap raises a
plain exception that the send lease converts into false
`PROVIDER_OUTCOME_UNKNOWN` — item 4). **C is obsolete** under the no-compat
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
   claim: attempt-admission window deliberately excluded, see 2c; the
   serialized-floor width assertion for attempts rides with 2c).
2c. **Bounded attempt admission** *(medium, contract redesign)* — the
   landed attempt window ranks/aggregates over the full history (bounded
   returned models, unbounded database work: ranking, cumulative sums,
   exact totals, `array_agg` over every attempt). Bound the current-first
   candidate relation before windowing; exact totals become explicitly
   truncated/lower-bound counts (public change to the knowledge-evidence
   totals semantics). Acceptance: `EXPLAIN (ANALYZE, FORMAT JSON)` proof
   on a materially over-limit attempt population that no scan node
   examines more than ceiling+1 rows.
2b. ~~Fix the three verified production defects~~ — **LANDED** `69f242cdd`.
3. **Honest run token totals, retention included** *(medium/large)* —
   relational provider-call events own totals for LIVE runs with typed
   input/output completeness; at provider-detail purge, retention writes
   one typed usage summary (totals + known/incomplete) into the
   tombstone; retained runs read the tombstone — never both, and never
   silent zero (today retention deletes every provider-call row keeping
   only a count, and the frontend hides zero totals entirely, erasing
   real spend). Delete the attempt-derived `NULL→0` aggregation
   (`flow_run_repo.list_token_usage_for_runs`). Superseded and rerun
   attempts count — they incurred real spend. Reset unsupported
   pre-release rows; no backfill. Frontend renders incompleteness
   explicitly. Tests: before/after retention, superseded, reruns, mixed
   reported/unreported, outcome-unknown.
4. **Bounded Builder persistence and terminal behavior** *(large, two
   reviewable commits)* — (a) a locally detected oversized planning state
   becomes a typed, replayable terminal outcome preserving the last valid
   state; the handler catches ONLY `PlanningStatePayloadTooLargeError` and
   never rewrites an existing `PROVIDER_OUTCOME_UNKNOWN` (no combined
   ambiguity/oversize state); (b) bound builder proposal JSON with a
   top-level current-only schema version — do not wrap `content`, and do
   not break the draft-title JSON path (BM4.10). Max+1
   repository-level test proves retry replays without another provider call.
5. **Operational attachment semantics** *(large)* — the conversion happens
   at the post-flow-creation materialization seam, inside the existing
   atomic apply transaction: the Builder carries one typed
   template-attachment INTENT through the authoring command; after the
   materializer creates/locks the Flow, a deepened
   `FlowTemplateAssetService.create_from_existing_attached_file` converts
   it and the normal template-asset binding replaces the intent before
   steps are built. Builder never creates a temporary Flow, copies the
   file, or patches after apply (BM2.4 — currently documented but not
   implemented; `upload_asset` requires a persisted flow, which create-mode
   only has mid-materialization). Exactly ONE selected template for the
   terminal template-fill step; zero or multiple → typed question/refusal.
   JSON schema selection stops silently taking the first parseable file
   (BM2.7). Tests: detach/retention races, tenant/space mismatch, replay,
   rollback, publish, runtime rendering, survival after Builder-session
   deletion.
6. **One canonical attempt-evidence projection** *(medium/large)* —
   ownership boundary: the immutable attempt input owns the exact execution
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
8. **Builder frontend/server contract closure** *(medium, three reviewed
   commits by owner)* — (a) stream/attachment/draft contract: validate
   known SSE payload shapes at runtime (parser currently casts parsed
   JSON), one explicit stream-failure state, KEEP fail-fast unknown-event
   behavior; attachment limits; explicit draft lifecycle. (b) vocabulary
   neutrality: direct pre-release correction of `case_documents`,
   `basic_case_metadata`, `case_like_flow` — no tolerant readers.
   (c) serve RAG policy ceilings through the existing settings response
   and delete the duplicated admin-page TS constants — no generic
   constraints-discovery API.
9. **Docs-site contract correction** *(medium, per-slice from now on)* —
   the false "influenced the answer" claim is CORRECTED (2026-07-29, with
   this roadmap revision); each remaining correction lands with its owning
   slice: attachment-to-template promise with item 5, export limits +
   lineage writer with items 2/7. Add contract tests covering all four
   export limits and prohibiting material-influence wording.
10. **Release proof** *(external gates, tracked not implemented here)* —
    BEFORE any live run, freeze in the tracked gate input: repetition
    count, required cases, non-municipal domain families, provider
    route/model identity, and numeric p50/p95 latency + token/call
    ceilings (the harness today has none of these and only
    municipal-domain cases; thresholds must never be chosen after
    observing results). Preserve raw receipts. Then: server build
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

## Update protocol

Landing a slice updates this file in the same commit series: move the item
to Landed with its SHA, re-rank if evidence changed, record newly accepted
follow-ups. Peer-gate scores and artifacts stay in `.codex/artifacts/`
(untracked); this file records outcomes only.
