# Flow Builder Release Governance Packet - 2026-06-30

TL;DR:
- This packet is the Gate 1 decision record after the C9.0 Gate 0 refresh.
- Flow AI Builder stays native Eneo authoring; no MCP/capability implementation starts here.
- Gate 1 chooses active abandoned-session expiration as the next release-risk reducer.
- Reuse `DataRetentionService`; do not add a Builder retention service or generic file cleaner.
- Repair/fallback pruning remains blocked until real branch-level evidence exists.

Primary evidence: `review-artifacts/flow-builder-release-governance-gate0-2026-06-30.md`. C9.0 refreshed lifecycle, retention, audit, JSONB ownership, and migration evidence; this packet records the release decisions that follow from that inventory.

## Lifecycle Summary

| Area | Gate 1 release state | Evidence |
|---|---|---|
| Session statuses | `chatting` and `awaiting_approval` are active/resumable; `applied` and `cancelled` are terminal. | Gate 0 lifecycle matrix; `backend/src/intric/flows/ai_builder/ai_builder_domain_models.py:31`; `backend/src/intric/flows/ai_builder/ai_builder_session_transitions.py:9`. |
| Plan statuses | `proposed`, `approved`, `applied`, and `superseded` are real plan states. There is no rejected state. | Gate 0 audit inventory; `backend/src/intric/flows/ai_builder/ai_builder_domain_models.py:38`. |
| Current plan pointer | `latest_plan_id` remains session-owned and same-session constrained. | Gate 0 lifecycle matrix; `backend/src/intric/database/tables/flow_tables.py:2137`; `backend/src/intric/database/tables/flow_tables.py:2163`. |
| Planning snapshot | `planning_state_jsonb` and `planning_state_version` remain the repository-owned CAS snapshot. | Gate 0 lifecycle/retention rows; `backend/src/intric/database/tables/flow_tables.py:2138`; `backend/src/intric/flows/ai_builder/ai_builder_repo.py:1025`. |
| Active send lease | Fresh send leases are meaningful runtime state and must block active-session expiration. | `backend/src/intric/flows/ai_builder/ai_builder_repo.py:758`; `backend/src/intric/flows/ai_builder/ai_builder_repo.py:796`; no-lease lifecycle updates already reject fresh locks at `backend/src/intric/flows/ai_builder/ai_builder_repo.py:476` and `backend/src/intric/flows/ai_builder/ai_builder_repo.py:493`. |

## Retention Decisions

| Artifact / policy | Gate 1 decision | Evidence / owner |
|---|---|---|
| Terminal Builder sessions | Keep C8.6 behavior: old `applied` and `cancelled` sessions expire through existing hierarchical tenant/space retention. | `DataRetentionService` terminal status tuple at `backend/src/intric/data_retention/infrastructure/data_retention_service.py:64`; due query/count/delete at `backend/src/intric/data_retention/infrastructure/data_retention_service.py:472`, `backend/src/intric/data_retention/infrastructure/data_retention_service.py:493`, and `backend/src/intric/data_retention/infrastructure/data_retention_service.py:502`. |
| Active abandoned Builder sessions | New Gate 1 decision: old abandoned `chatting` and `awaiting_approval` sessions should also expire through the same tenant/space retention policy. Implement later; current source only proves they are kept today. | Current keep proof: `backend/tests/integration/test_data_retention_hierarchical.py:834` and `backend/tests/integration/test_data_retention_hierarchical.py:866`. Next owner: extend the existing `DataRetentionService` Builder due-query/count/delete path. |
| Active-session age anchor | Use `builder_sessions.updated_at` as the first-release age anchor unless a later product/privacy rule chooses another persisted timestamp. | Current Builder retention already uses `BuilderSessions.updated_at` in `backend/src/intric/data_retention/infrastructure/data_retention_service.py:486`; send claim/refresh/release update `updated_at` in `backend/src/intric/flows/ai_builder/ai_builder_repo.py:758`, `backend/src/intric/flows/ai_builder/ai_builder_repo.py:796`, and `backend/src/intric/flows/ai_builder/ai_builder_repo.py:823`. |
| Fresh send leases | Do not delete sessions with a fresh active send lease. Expired locks may be treated as abandoned if the age predicate is also due. | Fresh locks are represented by lock fields in `backend/src/intric/database/tables/flow_tables.py:2126`; existing no-lease lifecycle updates require lock availability at `backend/src/intric/flows/ai_builder/ai_builder_repo.py:476`. |
| Applied conversations and planning state | Retain with the Builder session until session retention deletes the row. Do not add immediate post-apply field trimming in the next slice. | JSONB owners are registered at `backend/src/intric/flows/infrastructure/flow_jsonb_ownership.py:460` and `backend/src/intric/flows/infrastructure/flow_jsonb_ownership.py:474`; session-level deletion is the current cleanup unit. |
| Plans/proposals after apply | Retain with the session and cascade-delete with session retention. | `builder_plans.session_id` cascades at `backend/src/intric/database/tables/flow_tables.py:2225`; test proof starts at `backend/tests/integration/test_data_retention_hierarchical.py:872`. |
| Session-file links | Remove with explicit cancel or session deletion. | `builder_session_files` is session-owned at `backend/src/intric/database/tables/flow_tables.py:2195`; cancel detaches links at `backend/src/intric/flows/ai_builder/ai_builder_repo.py:230`; retention test proves link removal at `backend/tests/integration/test_data_retention_hierarchical.py:875`. |
| Global file rows | Accept current first-release posture: Builder retention removes pins, but Builder-only global `files` row cleanup is unproven and deferred. Do not add a generic file sweeper. | Gate 0 file row; `FlowRunHistoryPurgeRepository` only deletes run/template candidate ids at `backend/src/intric/flows/infrastructure/flow_run_history_purge_repo.py:91` and `backend/src/intric/flows/infrastructure/flow_run_history_purge_repo.py:155`, while checking Builder links as a guard at `backend/src/intric/flows/infrastructure/flow_run_history_purge_repo.py:339`. The retention test keeps the global `Files` row at `backend/tests/integration/test_data_retention_hierarchical.py:889`. |
| Created Flow linkage | Created or edited Flows outlive Builder session history. Builder retention must not delete Flow rows. | `builder_sessions.flow_id` exists at `backend/src/intric/database/tables/flow_tables.py:2102`; Gate 0 retention inventory records Flow lifecycle as separate. |
| Cleanup scope/config | Reuse existing tenant/space retention policy. Do not add Builder-specific retention config for first release. | Effective policy resolution starts at `backend/src/intric/data_retention/infrastructure/data_retention_service.py:254`; Builder due query joins `Spaces` and `AuditRetentionPolicy` at `backend/src/intric/data_retention/infrastructure/data_retention_service.py:472`. |

## Audit Decisions

| Item | Gate 1 decision | Evidence |
|---|---|---|
| Audit retention | Keep audit retention separate from Builder session deletion. | Audit log schema at `backend/src/intric/database/tables/audit_log_table.py:35`; audit retention path at `backend/src/intric/audit/application/retention_service.py:162`. |
| Live Builder audit actions | Keep only the four C8.7 actions: session created, session cancelled, plan approved, and flow applied. | `backend/src/intric/audit/domain/action_types.py:120`; category mapping at `backend/src/intric/audit/domain/category_mappings.py:115`; guard test at `backend/tests/unit/test_audit_category_mappings.py:104`. |
| Plan proposed / rejected audit | Keep deleted. `proposed` remains a plan state; `rejected` is not a plan state. | Gate 0 audit inventory; exact `rg` in C9.0 found no `AI_BUILDER_PLAN_PROPOSED` or `AI_BUILDER_PLAN_REJECTED` after C8.7. |
| Proposal-shown audit | Not a release blocker. Add later only if product/compliance names a real auditable transition. | No source evidence currently justifies wiring an artificial event. |

## Repair / Fallback Decision

| Area | Gate 1 decision | Evidence |
|---|---|---|
| JSON-text fallback, forced-tool retry, self-correction | Do not prune. Measure branch value first. | C8.14 records pruning as blocked until branch-level telemetry/eval evidence exists in `review-artifacts/implementation-progress-2026-06-29.md:1940`. |
| New telemetry/eval framework | Do not add one from this packet. | C8.13/C8.14 already improved failed-turn logging; the missing piece is real branch data, not a generic framework. |

## Completed Lanes

| Lane | Result |
|---|---|
| Terminal Builder retention/deletion/count | Done in C8.6. `DataRetentionService` owns terminal Builder count/delete; session rows are the deletion unit; plans and session-file links cascade; global files are not directly deleted. |
| Builder audit vocabulary delete-or-wire | Done in C8.7. Fake plan proposed/rejected audit actions were deleted; live emitted actions remain. |
| Lifecycle active-send/apply invariant | Done in C8.8. No-lease lifecycle transitions now respect active send locks. |
| Repair pruneability decision | Done in C8.14. No branch was pruned; branch-level evidence is still required. |

## Next Implementation Lane

| Rank | Lane | Release value | Boundary |
|---|---|---|---|
| 1 | Active abandoned-session retention in `DataRetentionService` | Highest remaining release-governance risk: old active sessions can retain user-like conversation/planning/proposal data indefinitely today. | Extend the existing due Builder-session predicate/count/delete path. No new service, config, repository wrapper, generic lifecycle manager, or file cleaner. |

Deferred future risk: Builder-only global file-row cleanup evidence is not the selected implementation lane. Revisit it only if retained global file rows after Builder pin removal become unacceptable, and only with a named candidate-id source, reference guard, owner, and tests. Do not add a generic sweeper.

Question/slot cleanup and broader Builder maintainability can resume after active abandoned-session retention is implemented or explicitly rejected by release owners. Repair pruning remains later than branch-data review.

## Recommended Next Bounded Prompt

Continue with exactly one bounded implementation slice: active abandoned Flow AI Builder session retention in `DataRetentionService`.

Required acceptance criteria:
- Extend the existing Builder due-query/count/delete path to include old abandoned `chatting` and `awaiting_approval` sessions.
- Reuse the existing effective tenant/space retention policy and `BuilderSessions.updated_at` age anchor.
- Skip sessions with a fresh active send lease; handle expired locks deliberately.
- Keep recent active sessions.
- Preserve C8.6 terminal-session behavior.
- Cascade-delete session-owned plans and `builder_session_files` links; do not directly delete global `Files` rows.
- Keep created Flows and audit logs.
- Add focused retention/worker tests proving count/delete predicates match, tenant/space scope is respected, fresh leases block deletion, expired abandoned sessions delete, recent active sessions stay, and global file rows remain.
- Do not touch MCP/capability descriptors, frontend/API/generated clients, Flow runtime, proposal repair/fallback branches, audit vocabulary, or schema/migrations unless source review proves unavoidable.

## Remaining Builder Release Blockers

| Blocker | Why it remains | Next action |
|---|---|---|
| Active abandoned-session retention | Current source keeps old active/resumable sessions. Gate 1 now decides that should be fixed before release. | Implement the recommended next slice in `DataRetentionService`. |
| Builder-only global file-row cleanup | Current source removes Builder pins but does not prove a Builder-only global file cleanup owner. | Accept for first release; revisit only with a candidate-driven owner and tests. |
| Repair branch deletion evidence | Existing evidence does not prove repair/fallback branches are dead or harmful. | Collect/review branch-level evidence before any pruning slice. |

## What Not To Do Next

- Do not implement MCP, capability descriptors, `AssistantConfigurationService`, or PR #480 loopback-MCP behavior.
- Do not prune repair/fallback branches without branch-level evidence.
- Do not create a Builder retention service, generic lifecycle manager, command bus, event-sourcing layer, legal-hold framework, or generic file cleaner.
- Do not broaden into frontend redesign, generated-client cleanup, Flow runtime/API changes, audit vocabulary changes, or schema/migration work from this packet.
- Do not split large Builder files by line count before deleting or consolidating named duplicate owners.
