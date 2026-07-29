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
| 2026-07-29 | JSONB docs honesty (`36c35b734`, `a3318a169`) |
| 2026-07-28 | RAG evidence transparency, `615200dcc..cf0cddc16`: verbatim retrieved passages as typed bounded evidence; sensitivity-gated disclosure; single-statement bounded admission with per-step attribution; corruption fail-closed; four-limit complete-or-refuse exports; admin tenant policy for recording limits; full source rendering sv+en |
| 2026-07-28 | Bounded evidence view + honest export refusal (`3ad737a79`) |
| 2026-07-27 | Exact resolved-input lineage persisted at every resolution path (`f515fe9df`, `e387615ec`) |
| 2026-07-27 | Provider-call evidence v2 contract (`9e527fcbd`); requested provider capabilities (`9a4c14243`) |
| earlier | Honest unknown-token usage; builder resume-failure recovery; authoring/builder vocabulary neutrality; builder draft retention |

## In flight

- **Corrupt-evidence visibility follow-ups** (task #1): surface
  `corrupt_passage_aggregates` in the public knowledge view with truthful
  reason-neutral omission copy sv+en + real fixtures. Worker iteration 3
  (wrapper-contract wording); gate at 7/10 and converging; lands on green ≥8.
- **Roadmap reconciliation pass 2** (peer, xhigh): verifying the old
  ledger's open items (OPEN-WORK A–D, M6.6, M6.7, M2.9 operational half,
  BM5.4, BM2.4/2.7/4.10/5.2/5.3, FE.1–4, BM0.2) against current source
  under the no-compat policy, plus a docs-site correctness audit. Its
  verified output finalizes the ranking below.

## Ranked plan (current working version; pass-2 merge pending)

1. **One consistent bounded evidence snapshot** — remove the shared-session
   `asyncio.TaskGroup` fan-out in `flow_run_evidence_service`; sequential
   reads inside one `REPEATABLE READ` transaction; proven by a real
   PostgreSQL two-session interleaving test. *(Verified P1: unsupported
   concurrent AsyncSession use + preflight and load can see different
   committed states.)*
2. **Complete export/view bounds** — preflight and admission must count
   attempts and measure `input_payload_json`/`output_payload_json` bytes,
   which today bypass every guard (`limit is None` on export; admission
   sums `pg_column_size(provenance_json)` only). New named export limits,
   fixed ceilings (correctness invariants, not tenant policy).
3. **Delete duplicate provenance projections** — field-by-field: drop
   attempt-provenance copies of `runtime_input`, `transcription`, `guards`
   (step-result snapshot and reduced citations stay — they have runtime
   readers); `artifacts` only after the relational result-file owner
   provably covers export semantics. Deletion, not a new writer abstraction.
4. **Resolved-input lineage projection** — expose the persisted exact
   lineage through the evidence bundle for admitted attempts, under the
   slice-1 snapshot, with an aggregate budget; retained / purged / corrupt
   / omitted states explicit. The last big transparency gap.
5. **Type surviving provenance sections** — after the deletions: reuse
   `RetrievedKnowledgeEvidence` for the RAG envelope; close other
   `extra="allow"` sections only where a real producer/consumer contract
   exists. No-compat policy applies: correct v-current directly.
6. **Docs-site correctness audit fixes** — scope set by pass 2's findings;
   flows developer docs must match actual behavior.
7. **Server-owned ceilings in the policy API** — return ceiling metadata in
   the typed policy response; delete the duplicated TS constants in the
   admin page. Fold in the triplicate ai_builder `File` test factory when
   those tests next change.

**Deferred:** export streaming/pagination (M6.7 transport) until the
bounded-complete path exists and measured run sizes demand more; BM0.2
(needs external branch-protection evidence); M2.9 operational half
(deferred by the product owner — running the HTTP-secret inventory against
a deployment).

## Update protocol

Landing a slice updates this file in the same commit series: move the item
to Landed with its SHA, re-rank if evidence changed, record newly accepted
follow-ups. Peer-gate scores and artifacts stay in `.codex/artifacts/`
(untracked); this file records outcomes only.
