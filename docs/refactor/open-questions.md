# Open Questions

TL;DR:
1. Phase 7 closed several architecture questions by choosing defaults grounded in code evidence.
2. The highest-risk remaining questions are terminal audit fail policy, evidence export shape, legacy permission migration, and frontend validation command.
3. Runtime file mapping, pause/edit/resume mechanics, status DB representation, ADR location, prompt-test shape, and generated TypeScript review discipline now have defaults.
4. Remaining questions must be resolved in the first implementation batch that depends on them.
5. If a question stays open at implementation time, use the default and document the decision.

## Still Open

| Question | Why It Matters | Owner Needed | Default Recommendation If Unanswered | Related PRD |
|---|---|---|---|---|
| Should terminal audit outbox insert failure block terminalization? | Determines whether runs can remain non-terminal during audit outage or terminalize without durable audit. | Backend/runtime plus compliance/product owner. | Fail before terminal state change; ADR required to choose fail-open. | PRD-003, PRD-009 |
| Evidence export: JSON API, attachment download, or both? | Generated clients and API consumers need accurate response semantics. | API maintainer plus frontend/product. | Prefer JSON for SDK unless browser download is primary; otherwise expose a separate download endpoint. | PRD-004 |
| Should `flow_runs.user_id` be dropped or kept historical-only? | Principal identity is authorization-sensitive. | Data model/backend owner. | Mark historical-only first; drop after no code reads it and migration proves safety. | PRD-002 |
| What frontend test command is canonical after fixing `jsdom`? | PRD-006/007 need reliable validation before frontend state-owner refactors. | Frontend owner. | Fix Vitest env and document package-specific commands in PRD-007 implementation. | PRD-007 |
| What should happen to historical evidence fields after `file_ids` deletion? | Evidence/export may need to preserve old lineage keys even when request support is deleted. | Runtime/evidence owner. | Delete request support but preserve historical/export lineage until evidence schema version changes. | PRD-003 |

## Closed By Phase 7

| Question | Decision | Evidence / Owner Doc |
|---|---|---|
| Pagination: `has_more` or `total_count`? | Default to `has_more` unless exact totals are a product requirement. | `docs/refactor/architecture-decision-backlog.md`, PRD-004. |
| How should legacy `FLOWS`/`FLOWS_MANAGE` map to granular permissions? | Minimal explicit mapping; no review/resume/rerun/audit grant by default. Implementation still enumerates exact allowed legacy actions in the permission matrix. | PRD-002 and `docs/refactor/architecture-decision-backlog.md`. |
| Should runtime step inputs/artifacts become tables? | Use a hybrid: versioned JSONB for heterogeneous snapshots; relational rows for lifecycle, audit, retry, permission, file reference, rerun, and review facts. | `docs/refactor/phase7/data-model-scalability-stress-test.md`, PRD-002, PRD-003. |
| What is the exact review checkpoint persistence shape? | Use DB state machine plus thin Celery resume task; persist checkpoint/revision/next pointer, exit worker at pause, resume via typed command. | `docs/refactor/prd/PRD-003-runtime-reliability-and-feature-gaps.md`. |
| Which class owns AI Builder frontend state? | Run a small spike before editing; if inconclusive, Service/controller owns Svelte state and Driver is stateless transport/SSE decoder. | PRD-006. |
| How stable should AI Builder prompt tests be? | Test prompt assembly and contractual obligations, not exact natural language output. | PRD-005 and `docs/refactor/architecture-decision-backlog.md`. |
| Where should ADRs live? | Use existing ADR location if any; otherwise `docs/adr/`. | PRD-010. |
| Should generated TypeScript schema be committed with handwritten changes? | Separate generated-only diffs from handwritten adapters. | PRD-004, PRD-006. |
| Should status DB representation become PostgreSQL enum? | Keep varchar CHECK plus explicit migrations until lifecycle stabilizes. | PRD-002. |
| How should idempotency expiry behave for old retries? | Document fixed retention; after expiry, key is treated as new unless run lookup by ID is used. | PRD-002, PRD-004. |
