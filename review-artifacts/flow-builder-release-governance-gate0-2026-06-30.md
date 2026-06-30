# Flow Builder Release Governance Gate 0 - 2026-06-30

TL;DR:
- Flow AI Builder remains on the native Eneo authoring ship path; this packet does not start MCP/capability implementation.
- C8.6 closed terminal Builder session retention by reusing `DataRetentionService`; old `applied` and `cancelled` sessions are now count/delete eligible.
- C8.7 closed fake audit vocabulary; only real emitted Builder audit actions remain.
- Active `chatting` and `awaiting_approval` sessions are deliberately outside the current retention delete predicate.
- Repair/fallback pruning is not ready; telemetry and evals exist, but live repair branches are still unproven as deletable.

## Scope

This is a release-governance inventory for Flow AI Builder after C8.6 and C8.7. It records what the current source and landed roadmap work prove before the next implementation slice. It does not propose source, API, schema, frontend, generated-client, MCP, capability-descriptor, repair-pruning, or retention changes.

The active architecture decision for this packet is: Flow AI Builder ships as the native Eneo authoring UI if this release-hardening track passes. If that decision changes, the release path must gate Builder at backend route/settings registration, not only frontend navigation, per `review-artifacts/flows-9-10-architecture-roadmap-2026-06-29.md:53-65`.

## Lifecycle Matrix

| Item | Current state | Canonical owner / evidence | Governance decision |
|---|---|---|---|
| Session `chatting` | Active/resumable session state; accepts user messages and can transition to `awaiting_approval` or `cancelled`. | `SessionStatus.CHATTING` exists in `backend/src/intric/flows/ai_builder/ai_builder_domain_models.py:31-35`; transition table allows `chatting -> chatting`, `awaiting_approval`, or `cancelled` in `backend/src/intric/flows/ai_builder/ai_builder_session_transitions.py:9-14`. | Not terminal and not deleted by C8.6 retention. Old `chatting` sessions are kept by the behavior test at `backend/tests/integration/test_data_retention_hierarchical.py:834-870`. |
| Session `awaiting_approval` | Active/resumable approval state; can return to `chatting`, become `applied`, or be `cancelled`. | `SessionStatus.AWAITING_APPROVAL` exists in `backend/src/intric/flows/ai_builder/ai_builder_domain_models.py:31-35`; transitions are in `backend/src/intric/flows/ai_builder/ai_builder_session_transitions.py:15-19`. | Not terminal and not deleted by C8.6 retention. Old `awaiting_approval` sessions are kept by `backend/tests/integration/test_data_retention_hierarchical.py:843-870`. |
| Session `applied` | Terminal session state after an approved plan is applied. | `mark_plan_applied` updates the plan to `APPLIED` and the session to `APPLIED` in `backend/src/intric/flows/ai_builder/ai_builder_repo.py:909-927`; applied sessions self-transition only in `backend/src/intric/flows/ai_builder/ai_builder_session_transitions.py:20`. | Terminal and retention eligible after the existing hierarchical data/conversation retention policy says due. |
| Session `cancelled` | Terminal session state after explicit cancel or matching-active cancel. | `cancel_session` sets `SessionStatus.CANCELLED` and clears active send-lock fields in `backend/src/intric/flows/ai_builder/ai_builder_repo.py:210-237`; cancelled sessions self-transition only in `backend/src/intric/flows/ai_builder/ai_builder_session_transitions.py:21`. | Terminal and retention eligible after the existing hierarchical data/conversation retention policy says due. Explicit cancel also detaches session-file links before setting the status. |
| Plan `proposed` | Real plan lifecycle state; created when a Builder proposal is stored. | `PlanStatus.PROPOSED` exists in `backend/src/intric/flows/ai_builder/ai_builder_domain_models.py:38-42`; `create_plan` writes it in `backend/src/intric/flows/ai_builder/ai_builder_repo.py:832-849`. | Real plan status, but not an audit action after C8.7. Proposal outcomes belong to proposal telemetry, not fake audit vocabulary. |
| Plan `approved` | Real plan lifecycle state before apply. | `AIBuilderPlanLifecycle.approve_plan` requires `PROPOSED` and writes `APPROVED` in `backend/src/intric/flows/ai_builder/ai_builder_plan_lifecycle.py:165-178`. | Real state and real emitted audit action at `backend/src/intric/flows/ai_builder/ai_builder_router.py:1135-1150`. |
| Plan `applied` | Real plan lifecycle state after materialization. | `AIBuilderPlanLifecycle.apply_plan` materializes and calls `repo.mark_plan_applied` in `backend/src/intric/flows/ai_builder/ai_builder_plan_lifecycle.py:234-356`; `mark_plan_applied` writes `PlanStatus.APPLIED` in `backend/src/intric/flows/ai_builder/ai_builder_repo.py:909-927`. | Real state. The exported audit action is `AI_BUILDER_FLOW_APPLIED`, emitted at `backend/src/intric/flows/ai_builder/ai_builder_router.py:1222-1243`. |
| Plan `superseded` | Real plan lifecycle state for replaced proposed plans. | `supersede_existing_plans` marks proposed plans `SUPERSEDED` in `backend/src/intric/flows/ai_builder/ai_builder_repo.py:935-955`; revise uses that path in `backend/src/intric/flows/ai_builder/ai_builder_plan_lifecycle.py:216-232`. | Real state, not an exported audit action. No source evidence requires a separate compliance audit event for supersession. |
| `latest_plan_id` | Session pointer to the current plan snapshot. | Stored on `BuilderSessions` in `backend/src/intric/database/tables/flow_tables.py:2137`; constrained to the same session in `backend/src/intric/database/tables/flow_tables.py:2163-2169`; updated in `backend/src/intric/flows/ai_builder/ai_builder_repo.py:613-715`. | Keep as lifecycle state. It remains part of the next lifecycle/planning-state proof surface. |
| `planning_state_version` | CAS counter for persisted planning-state snapshot writes. | Stored on `BuilderSessions` in `backend/src/intric/database/tables/flow_tables.py:2138-2146`; updated with version compare/increment in `backend/src/intric/flows/ai_builder/ai_builder_repo.py:961-1013`; conversation-derived rebuild forwards the base version in `backend/src/intric/flows/ai_builder/ai_builder_repo.py:1118-1137`. | Keep. The governance risk is not existence; it is making the snapshot/conversation truth boundary obvious enough for release maintainers. |
| Active send lease | Per-session in-flight send lock. | Stored as `active_request_id`, `lock_token`, `locked_at`, `lock_expires_at` in `backend/src/intric/database/tables/flow_tables.py:2126-2136`; all-or-none constraint at `backend/src/intric/database/tables/flow_tables.py:2178-2190`; claimed/refreshed/released in `backend/src/intric/flows/ai_builder/ai_builder_repo.py:738-826`; lease owner lives in `backend/src/intric/flows/ai_builder/ai_builder_send_lease.py:34-62` and `:107-152`. | Keep. The next lifecycle proof should verify ownership and failure behavior, not add a generic lifecycle service. |

## Retention Inventory

| Artifact | Where it lives | Current cleanup behavior | Decision / risk |
|---|---|---|---|
| Conversation messages | `builder_sessions.conversation` at `backend/src/intric/database/tables/flow_tables.py:2121-2125`. | Deleted when an expired terminal Builder session row is deleted by `DataRetentionService`; not trimmed immediately after apply. | Current policy is session-level retention, not per-message trimming. |
| Planning state | `builder_sessions.planning_state_jsonb` and `planning_state_version` at `backend/src/intric/database/tables/flow_tables.py:2138-2146`. | Deleted with the expired terminal session row. | Current policy keeps planning state with the session until terminal session retention. |
| Plans/proposals | `builder_plans.status`, `proposal_json`, and `spec_hash` at `backend/src/intric/database/tables/flow_tables.py:2222-2259`. | Cascade-delete when the owning Builder session is deleted. | Plans/proposals are retained after apply until session retention deletes them. |
| Session files | `builder_session_files` at `backend/src/intric/database/tables/flow_tables.py:2195-2219`. | Explicit cancel detaches links in `backend/src/intric/flows/ai_builder/ai_builder_repo.py:210-221`; retention delete cascades links with the session. | Builder retention removes Builder pins, but does not directly delete global `files` rows. |
| Created Flow linkage | `builder_sessions.flow_id` at `backend/src/intric/database/tables/flow_tables.py:2102-2106`; set during apply in `backend/src/intric/flows/ai_builder/ai_builder_repo.py:909-933`. | Deleting Builder session history does not delete the created or edited Flow. | Flow lifecycle remains owned by Flow services, not Builder retention. |
| Telemetry/log events | Failed proposal-turn payload at `backend/src/intric/flows/ai_builder/ai_builder_proposal_telemetry.py:281-303`; log emission at `backend/src/intric/flows/ai_builder/ai_builder_proposal_telemetry.py:322-370`. | Not stored in Builder session tables and not deleted by Builder session retention. | Telemetry is enough to observe terminal failures, not enough yet to prune repair branches. |
| Audit events | `audit_logs.action`, `entity_type`, and `entity_id` live in `backend/src/intric/database/tables/audit_log_table.py:35-38`. | Not deleted by Builder session retention. Audit has a separate soft-delete retention path in `backend/src/intric/audit/application/retention_service.py:162-170`. | Keep audit retention separate. Do not claim Builder cleanup deletes audit history. |

## Retention Owner

`DataRetentionService` is the release retention orchestrator. It defines terminal Builder statuses as `applied` and `cancelled` in `backend/src/intric/data_retention/infrastructure/data_retention_service.py:64-67`, builds one shared due-query in `backend/src/intric/data_retention/infrastructure/data_retention_service.py:472-491`, counts with the same query in `backend/src/intric/data_retention/infrastructure/data_retention_service.py:493-500`, and deletes with the same query in `backend/src/intric/data_retention/infrastructure/data_retention_service.py:502-534`.

The scheduled worker invokes that retention path and reports `builder_sessions` counts in `backend/src/intric/data_retention/infrastructure/data_retention_worker.py:204-219` and `backend/src/intric/data_retention/infrastructure/data_retention_worker.py:313-328`.

The focused test proves old terminal sessions are counted/deleted, recent terminal sessions are kept, active/resumable sessions are kept, session-owned plans and links disappear, and global `files` rows remain in `backend/tests/integration/test_data_retention_hierarchical.py:790-890`.

## File Ownership

Builder retention removes Builder-owned session-file links. It does not own global file deletion. `FlowRunHistoryPurgeRepository` still treats `BuilderSessionFiles` as one file-reference guard in `backend/src/intric/flows/infrastructure/flow_run_history_purge_repo.py:339-372`. After Builder links are deleted, those links no longer pin the file through that guard; the current source does not prove a general orphan-file sweep.

## Audit Vocabulary Inventory

| Vocabulary item | Current classification | Evidence | Decision |
|---|---|---|---|
| Plan proposed | Real plan status; deleted fake audit action. | `PlanStatus.PROPOSED` exists in `backend/src/intric/flows/ai_builder/ai_builder_domain_models.py:38-42`; `AI_BUILDER_PLAN_PROPOSED` no longer appears in `backend/src/intric/audit/domain/action_types.py:119-123`. | Keep as lifecycle state only. Do not wire an artificial audit event. |
| Plan approved | Real plan state and real audit action. | Router emits `AI_BUILDER_PLAN_APPROVED` in `backend/src/intric/flows/ai_builder/ai_builder_router.py:1135-1150`; enum/mapping keep it in `backend/src/intric/audit/domain/action_types.py:119-123` and `backend/src/intric/audit/domain/category_mappings.py:115-118`. | Keep. |
| Plan applied / flow applied | Real plan state; real audit action is Flow applied. | Apply marks plan/session applied in `backend/src/intric/flows/ai_builder/ai_builder_repo.py:909-927`; router emits `AI_BUILDER_FLOW_APPLIED` in `backend/src/intric/flows/ai_builder/ai_builder_router.py:1222-1243`. | Keep `AI_BUILDER_FLOW_APPLIED`; do not add a separate fake plan-applied audit action. |
| Plan superseded | Real plan state; no exported audit action. | `supersede_existing_plans` writes `SUPERSEDED` in `backend/src/intric/flows/ai_builder/ai_builder_repo.py:935-955`. | Keep as lifecycle state only unless a product/compliance requirement names an auditable transition. |
| Session cancelled | Real session state and real audit action. | Router emits `AI_BUILDER_SESSION_CANCELLED` in `backend/src/intric/flows/ai_builder/ai_builder_router.py:1075-1089`. | Keep. |
| Plan rejected | Deleted fake audit action; no plan state. | Plan statuses are only proposed/approved/applied/superseded in `backend/src/intric/flows/ai_builder/ai_builder_domain_models.py:38-42`; Builder audit enum now has only four actions in `backend/src/intric/audit/domain/action_types.py:119-123`. | Do not reintroduce without a real lifecycle state and compliance requirement. |

The guard test `backend/tests/unit/test_audit_category_mappings.py:104-119` now asserts Builder audit actions match the four emitted lifecycle actions.

## Repair / Fallback Readiness Note

Repair/fallback pruning is not ready. C8.1-C8.5 improved terminal truncation behavior, failed-turn telemetry, structured-answer ingestion, edit/revise routing, and deterministic materialization coverage, but the source still contains live bounded repair/self-correction paths. `MAX_SELF_CORRECTION_RETRIES = 3` remains in `backend/src/intric/flows/ai_builder/ai_builder_proposal_repair.py:58`; forced-tool retry remains in `backend/src/intric/flows/ai_builder/ai_builder_proposal_repair.py:574-585`. Failed-turn telemetry exists at `backend/src/intric/flows/ai_builder/ai_builder_proposal_telemetry.py:281-303`, but the landed evidence does not yet prove any repair branch is dead or harmful.

## Gate 0 Result

Flow AI Builder stays on the release-hardening track as native Eneo authoring UI. The next implementation should stay in Builder internals and avoid MCP/capability descriptors, broad lifecycle rewrites, and repair pruning. The recommended next bounded slice is lifecycle/planning-state ownership proof and invariant cleanup: verify the active send lease, `latest_plan_id`, and `planning_state_version` ownership/failure behavior, then delete or clarify only what is directly proven ambiguous.
