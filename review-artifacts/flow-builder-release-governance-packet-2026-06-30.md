# Flow Builder Release Governance Packet - 2026-06-30

## Summary

This packet reconciles the Builder release-governance state after C8.6 retention and C8.7 audit cleanup. It is intentionally small: it points to the Gate 0 evidence packet, records Gate 1 decisions, ranks at most two next lanes, and recommends one bounded implementation slice. It is not a PRD, not an ADR, and not a source-change proposal.

Primary companion artifact: `review-artifacts/flow-builder-release-governance-gate0-2026-06-30.md`.

## Lifecycle Summary

| Area | Release state | Evidence |
|---|---|---|
| Session statuses | `chatting` and `awaiting_approval` are active/resumable; `applied` and `cancelled` are terminal. | `backend/src/intric/flows/ai_builder/ai_builder_domain_models.py:31-35`; `backend/src/intric/flows/ai_builder/ai_builder_session_transitions.py:9-21`. |
| Plan statuses | `proposed`, `approved`, `applied`, and `superseded` are real lifecycle states. There is no rejected state. | `backend/src/intric/flows/ai_builder/ai_builder_domain_models.py:38-42`. |
| Current plan pointer | `latest_plan_id` is stored on the session and constrained to the same session. | `backend/src/intric/database/tables/flow_tables.py:2137`; `backend/src/intric/database/tables/flow_tables.py:2163-2169`. |
| Planning snapshot | `planning_state_jsonb` plus `planning_state_version` stores the current interpreted snapshot with CAS writes. | `backend/src/intric/database/tables/flow_tables.py:2138-2146`; `backend/src/intric/flows/ai_builder/ai_builder_repo.py:961-1013`. |
| Active send lease | One active send is represented by all-or-none lock fields and a per-turn lease. | `backend/src/intric/database/tables/flow_tables.py:2126-2136`; `backend/src/intric/database/tables/flow_tables.py:2178-2190`; `backend/src/intric/flows/ai_builder/ai_builder_send_lease.py:34-62`. |

## Retention Summary

| Artifact | Gate 1 policy | Evidence |
|---|---|---|
| Terminal Builder sessions | Expire old `applied` and `cancelled` sessions through existing hierarchical data/conversation retention. | `backend/src/intric/data_retention/infrastructure/data_retention_service.py:64-67`; `backend/src/intric/data_retention/infrastructure/data_retention_service.py:472-534`. |
| Active Builder sessions | Keep `chatting` and `awaiting_approval` regardless of age under current source policy. | `backend/tests/integration/test_data_retention_hierarchical.py:834-870`. |
| Conversations and planning state | Retained with the session until terminal session retention deletes the session row. | `backend/src/intric/database/tables/flow_tables.py:2121-2146`; `backend/tests/integration/test_data_retention_hierarchical.py:790-890`. |
| Plans/proposals | Retained with the session and cascade-deleted with the session. | `backend/src/intric/database/tables/flow_tables.py:2222-2259`; `backend/tests/integration/test_data_retention_hierarchical.py:872-887`. |
| Session-file pins | Builder session-file links are removed by explicit cancel or cascaded by session deletion; global file rows are not directly deleted by Builder retention. | `backend/src/intric/flows/ai_builder/ai_builder_repo.py:210-221`; `backend/tests/integration/test_data_retention_hierarchical.py:875-890`. |
| Created Flow linkage | Builder session history may be deleted without deleting the Flow. | `backend/src/intric/database/tables/flow_tables.py:2102-2106`; `backend/src/intric/flows/ai_builder/ai_builder_repo.py:909-933`. |
| Telemetry/log events | Failed-turn telemetry is content-free and outside Builder session-row retention. | `backend/src/intric/flows/ai_builder/ai_builder_proposal_telemetry.py:281-303`; `backend/src/intric/flows/ai_builder/ai_builder_proposal_telemetry.py:322-370`. |
| Audit events | Not deleted by Builder session retention; audit logs have their own retention path. | `backend/src/intric/database/tables/audit_log_table.py:35-38`; `backend/src/intric/audit/application/retention_service.py:162-170`. |

## Audit Vocabulary Summary

| Item | Decision after C8.7 | Evidence |
|---|---|---|
| `AI_BUILDER_SESSION_CREATED` | Kept; real route emission. | `backend/src/intric/flows/ai_builder/ai_builder_router.py:489-504`. |
| `AI_BUILDER_SESSION_CANCELLED` | Kept; real route emission. | `backend/src/intric/flows/ai_builder/ai_builder_router.py:1075-1089`. |
| `AI_BUILDER_PLAN_APPROVED` | Kept; real route emission. | `backend/src/intric/flows/ai_builder/ai_builder_router.py:1135-1150`. |
| `AI_BUILDER_FLOW_APPLIED` | Kept; real route emission. | `backend/src/intric/flows/ai_builder/ai_builder_router.py:1222-1243`. |
| `AI_BUILDER_PLAN_PROPOSED` | Deleted as fake enum/category-only audit vocabulary. Plan `proposed` remains a lifecycle state. | Current enum contains only four Builder actions in `backend/src/intric/audit/domain/action_types.py:119-123`; guard test in `backend/tests/unit/test_audit_category_mappings.py:104-119`. |
| `AI_BUILDER_PLAN_REJECTED` | Deleted as fake vocabulary; no rejected plan status exists. | `backend/src/intric/flows/ai_builder/ai_builder_domain_models.py:38-42`; `backend/src/intric/audit/domain/action_types.py:119-123`. |
| Category mapping | Only the four real Builder actions map to `user_actions`. | `backend/src/intric/audit/domain/category_mappings.py:115-118`. |

## Gate 1 Decisions

| Decision | Gate 1 answer | Basis |
|---|---|---|
| How long abandoned/cancelled Builder sessions are retained | Cancelled sessions are terminal and retained until existing hierarchical data/conversation retention says due. Active abandoned `chatting` and `awaiting_approval` sessions are kept indefinitely by current source policy unless a later attended policy slice changes that. | Terminal predicate in `backend/src/intric/data_retention/infrastructure/data_retention_service.py:64-67`; active-session keep proof in `backend/tests/integration/test_data_retention_hierarchical.py:834-870`. |
| Applied conversation retention / cleanup | Applied session conversation is retained with the session and deleted only when terminal session retention deletes the session row. No immediate after-apply trim exists. | Session JSON fields in `backend/src/intric/database/tables/flow_tables.py:2121-2146`; retention delete path in `backend/src/intric/data_retention/infrastructure/data_retention_service.py:502-534`. |
| Plans/proposals after apply | Plans/proposals remain with the session and are cascade-deleted when terminal session retention deletes the session. | Cascade FK in `backend/src/intric/database/tables/flow_tables.py:2222-2259`; cascade behavior proof in `backend/tests/integration/test_data_retention_hierarchical.py:872-887`. |
| Attached session files and global file rows | Builder session-file links are removed by explicit cancel or session retention cascade. Global `files` rows remain; once Builder links are gone, they are no longer pinned by `BuilderSessionFiles`. | `backend/src/intric/flows/ai_builder/ai_builder_repo.py:210-221`; file reference guard in `backend/src/intric/flows/infrastructure/flow_run_history_purge_repo.py:339-372`; file-row keep proof in `backend/tests/integration/test_data_retention_hierarchical.py:889-890`. |
| Audit events after conversation deletion | Builder session retention does not delete audit logs. Audit logs are separate records and have their own soft-delete retention path. | `backend/src/intric/database/tables/audit_log_table.py:35-38`; `backend/src/intric/audit/application/retention_service.py:162-170`. |
| Real audit actions after C8.7 | Session created, session cancelled, plan approved, and flow applied are real. Plan proposed/rejected are not audit actions. | `backend/src/intric/audit/domain/action_types.py:119-123`; router emissions in `backend/src/intric/flows/ai_builder/ai_builder_router.py:489-504`, `:1075-1089`, `:1135-1150`, `:1222-1243`. |
| Cleanup scope | Cleanup is tenant/space policy driven through `DataRetentionService`, `Spaces`, and `AuditRetentionPolicy`; it is not an ad hoc user-scoped cleanup. | Effective policy resolution in `backend/src/intric/data_retention/infrastructure/data_retention_service.py:254-285`; Builder query joins `Spaces` and `AuditRetentionPolicy` in `backend/src/intric/data_retention/infrastructure/data_retention_service.py:472-491`. |
| Hard-coded or tenant-configurable | Builder terminal retention reuses existing hierarchical retention policy. It is not a Builder-specific hard-coded duration. | Same policy owner in `backend/src/intric/data_retention/infrastructure/data_retention_service.py:254-285`. |

## Decisions Still Blocked Or Needing Acceptance

| Item | Status | Release impact |
|---|---|---|
| Abandoned active sessions | Current source keeps old `chatting` and `awaiting_approval` sessions. Product/privacy owner must accept that for first release or send a bounded active-abandonment policy slice. | Not a source blocker if accepted; otherwise the next implementation must define terminal-equivalent active abandonment without guessing. |
| Repair/fallback pruning | Not ready. Failed-turn telemetry and deterministic evals exist, but source still has live self-correction and forced-tool retry branches. | Do not prune next. Add measurement only if supervisor chooses a repair-evidence lane. |
| Proposal-shown audit | C8.7 deleted fake `PLAN_PROPOSED`. Product/compliance can request a real proposal-shown audit later, but current source does not justify it. | Not a release blocker unless compliance requires proposal display auditing. |

## Completed Implementation Lanes

| Lane | Result |
|---|---|
| Builder retention/deletion/count policy | Completed by C8.6. `DataRetentionService` owns terminal Builder count/delete; session rows are the deletion unit; plans and session-file links cascade; global files are not directly deleted. |
| Builder audit vocabulary delete-or-wire | Completed by C8.7. Fake plan proposed/rejected actions are gone; live emitted actions remain; generated audit action vocabulary was updated in the C8.7 slice. |

## Next Implementation Lanes

| Rank | Lane | Release value | Boundaries |
|---|---|---|---|
| 1 | Lifecycle / `PlanningState` ownership proof and invariant cleanup | Gate 0 still exposes active send lease, `latest_plan_id`, and `planning_state_version` as the hardest remaining lifecycle truth surface. | Stay in existing owners. Prove or clarify invariants; delete duplicate weak paths if found. Do not create a lifecycle manager, command bus, or broad Builder redesign. |
| 2 | Question/slot vocabulary consolidation | C8.3 made structured answers stricter, and the roadmap already identifies duplicate question/slot mapping ownership. | Reuse `question_catalog` as the likely owner. Do not introduce a generic form/answer framework or capability registry. |

Repair telemetry completeness remains required before repair pruning, but pruning is not the next implementation lane. The current source still has live bounded repair paths at `backend/src/intric/flows/ai_builder/ai_builder_proposal_repair.py:58` and `backend/src/intric/flows/ai_builder/ai_builder_proposal_repair.py:574-585`.

## Recommended Next Slice

Send one bounded implementation prompt for lifecycle / `PlanningState` ownership proof and invariant cleanup:

- Verify current owners for active send lease, `latest_plan_id`, `planning_state_version`, and conversation-derived planning snapshots.
- Add or extend behavior tests only where a real invariant is missing or ambiguous.
- Delete, reuse, or move only directly proven duplicate lifecycle logic.
- Record active abandoned-session policy as accepted current behavior or explicitly stop for product/privacy decision.
- Do not touch MCP/capability descriptors, repair pruning, frontend redesign, Flow runtime, generated clients, retention schema, or broad Builder module splitting.

## Remaining Builder Release Blockers

| Blocker | Why it remains | Next action |
|---|---|---|
| Active abandoned-session policy acceptance | Current retention keeps active/resumable sessions indefinitely. That is clear source behavior, but release owner must accept it or define a policy. | Include acceptance or scoped policy in the lifecycle next slice. |
| Lifecycle truth readability | The state is mostly owned by existing modules, but release maintainers need proof that lease, plan pointer, and planning-state CAS cannot drift silently. | Recommended next slice. |
| Repair branch deletion evidence | Telemetry/evals exist but do not yet prove JSON-text, forced-tool retry, or self-correction paths are dead or harmful. | Do not prune until telemetry/eval proof is reviewed. |

## What Not To Do Next

- Do not implement MCP, capability descriptors, `AssistantConfigurationService`, or PR #480 loopback-MCP behavior.
- Do not prune repair/fallback branches without branch-level evidence.
- Do not create a generic lifecycle manager, event-sourcing layer, retention framework, legal-hold framework, or command bus.
- Do not broaden into frontend redesign, generated-client cleanup, or Flow runtime/API changes from this governance packet.
- Do not split large Builder files by line count before deleting or consolidating named duplicate owners.
