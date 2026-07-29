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

1. **One consistent evidence snapshot** *(medium)* — remove the
   shared-session `asyncio.TaskGroup` fan-out in
   `flow_run_evidence_service`; one sequential `REPEATABLE READ` evidence
   transaction owned by the service; proven by a real PostgreSQL two-session
   mutation-barrier test (all-before or all-after, never mixed).
   *(Verified P1: unsupported concurrent AsyncSession use + independently
   observed database states. Only shared-session fan-out in flows; the
   webhook delivery TaskGroup opens a session per task and is the in-repo
   exemplar of safe concurrency.)*
2. **Whole-bundle evidence bounds** *(large)* — within that snapshot,
   preflight EVERY emitted section against named row/stored-byte/logical-
   byte limits before materialization: attempts (`limit is None` on export
   today), attempt AND step-result `input/output/model_parameters` payload
   columns (invisible to the provenance-only measurement), rerun revisions,
   checkpoints, result files. Export refuses before loading an incomplete
   bundle; the view discloses typed omissions. Fixed ceilings (correctness
   invariants, not tenant policy). Tests: max+1 rows per section, highly
   compressible JSON (stored vs logical), concurrent mutation.
3. **Honest run token totals** *(medium)* — relational provider-call events
   become the sole owner of run totals with typed input/output completeness;
   delete the attempt-derived `NULL→0` aggregation
   (`flow_run_repo.list_token_usage_for_runs`). A known+unreported run
   returns typed incomplete totals, never a silent partial number. Tests:
   mixed, unknown-only, zero-provider, outcome-unknown runs.
4. **Bounded Builder persistence and terminal behavior** *(large)* — a
   locally detected oversized planning state becomes a typed, replayable
   terminal outcome preserving the last valid state (never
   `PROVIDER_OUTCOME_UNKNOWN`, which asserts provider ambiguity that does
   not exist); bound and version builder proposal JSON (BM4.10). Max+1
   repository-level test proves retry replays without another provider call.
5. **Operational attachment semantics** *(large)* — Builder apply converts
   an attached template file into a real template binding by reusing
   `FlowTemplateAssetService` (BM2.4 — currently documented but not
   implemented); JSON schema selection stops silently taking the first
   parseable file (BM2.7). An attached DOCX must survive apply, publish,
   and runtime rendering through the existing asset owner.
6. **One canonical attempt-evidence projection** *(medium/large)* —
   ownership boundary: the immutable attempt input owns the exact execution
   snapshot; relational result files own artifacts; attempt provenance owns
   only what cannot be reconstructed (verbatim RAG, provider-call facts);
   the mutable step result is a runtime projection, not a parallel forensic
   store. `step_result_builder` becomes the sole projection builder,
   executor orchestrates. Delete redundant fields FIRST, then type the
   surviving envelopes (reuse `RetrievedKnowledgeEvidence`); typing before
   deletion would formalize duplication.
7. **Resolved-input lineage projection** *(medium)* — batch-project the
   persisted exact lineage into the existing evidence bundle for admitted
   attempts, under the item-1 snapshot, inside the item-2 budgets;
   retained / purged / corrupt / omitted states explicit.
8. **Builder frontend/server contract closure** *(medium)* — generated
   event types, attachment limits, explicit draft lifecycle, tolerant
   validated SSE handling (FE remnants); finish vocabulary neutrality
   (`case_documents`, `basic_case_metadata`, `case_like_flow` — direct
   pre-release correction, no tolerant readers); serve RAG policy ceilings
   from the server and delete the duplicated admin-page TS constants.
9. **Docs-site contract correction** *(medium, after contracts freeze)* —
   remove causal "influenced the answer" overclaims (runtime records
   influence as unknown); stop promising attachment-to-template binding
   until item 5 lands; document all four export refusal limits (guide names
   only one); lineage writer is active, not future work. Add contract tests
   covering all four limits and prohibiting material-influence wording.
10. **Release proof** *(external gates, tracked not implemented here)* —
    live quality/economics thresholds run repeatedly (p50/p95), server
    build identity, diverse structural goldens (BM5.2–5.4), HTTP-secret
    deployment inventory (M2.9 operational half; with zero users any hit
    means reset/delete, not compatibility), branch-protection evidence
    (BM0.2).

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
