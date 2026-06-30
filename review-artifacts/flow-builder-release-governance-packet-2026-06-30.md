# Flow Builder Release Governance Packet - 2026-06-30

TL;DR:
- This packet is the Gate 1 decision record after the C9.0 Gate 0 refresh.
- Flow AI Builder stays native Eneo authoring; no MCP/capability implementation starts here.
- C9.2 completed active abandoned-session expiration in `DataRetentionService`.
- C9.3 accepts retained Builder-uploaded global `Files` rows for first release after Builder session pins are removed.
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
| Terminal and abandoned active Builder sessions | C8.6/C9.2 behavior is accepted for first release: old `applied`, `cancelled`, `chatting`, and `awaiting_approval` sessions expire through existing hierarchical tenant/space retention. | `DataRetentionService` names active and retention-eligible Builder statuses at `backend/src/intric/data_retention/infrastructure/data_retention_service.py:64-72`; the shared due query/count/delete path is at `backend/src/intric/data_retention/infrastructure/data_retention_service.py:491-556`; C9.2 behavior proof is at `backend/tests/integration/test_data_retention_hierarchical.py:841-939`. |
| Active-session age anchor | Use `builder_sessions.updated_at` as the first-release age anchor unless a later product/privacy rule chooses another persisted timestamp. | C9.2 retention uses `BuilderSessions.updated_at` at `backend/src/intric/data_retention/infrastructure/data_retention_service.py:508`; send claim/refresh/release update `updated_at` in `backend/src/intric/flows/ai_builder/ai_builder_repo.py:758`, `backend/src/intric/flows/ai_builder/ai_builder_repo.py:796`, and `backend/src/intric/flows/ai_builder/ai_builder_repo.py:823`. |
| Fresh send leases | Do not delete sessions with a fresh active send lease. Expired locks may be treated as abandoned if the age predicate is also due. | Fresh locks are represented by lock fields in `backend/src/intric/database/tables/flow_tables.py:2126`; C9.2 protects fresh leases at `backend/src/intric/data_retention/infrastructure/data_retention_service.py:80-90`; the test keeps a fresh-lock active session at `backend/tests/integration/test_data_retention_hierarchical.py:869-918`. |
| Applied conversations and planning state | Retain with the Builder session until session retention deletes the row. Do not add immediate post-apply field trimming in the next slice. | JSONB owners are registered at `backend/src/intric/flows/infrastructure/flow_jsonb_ownership.py:460` and `backend/src/intric/flows/infrastructure/flow_jsonb_ownership.py:474`; session-level deletion is the current cleanup unit. |
| Plans/proposals after apply | Retain with the session and cascade-delete with session retention. | `builder_plans.session_id` cascades at `backend/src/intric/database/tables/flow_tables.py:2225`; C9.2 test proof starts at `backend/tests/integration/test_data_retention_hierarchical.py:921`. |
| Session-file links | Remove with explicit cancel or session deletion. | `builder_session_files` is session-owned and session-cascaded at `backend/src/intric/database/tables/flow_tables.py:2195-2219`; cancel detaches links at `backend/src/intric/flows/ai_builder/ai_builder_repo.py:230`; C9.2 proves link removal at `backend/tests/integration/test_data_retention_hierarchical.py:924-936`. |
| Global file rows | C9.3 accepts current first-release posture: Builder retention removes session pins, but Builder-uploaded global `files` rows can remain after pin removal. Do not add a generic orphan-file sweeper. | Gate 0 file row; `FlowRunHistoryPurgeRepository` deletes only run/template candidate ids at `backend/src/intric/flows/infrastructure/flow_run_history_purge_repo.py:91-104` and `backend/src/intric/flows/infrastructure/flow_run_history_purge_repo.py:155-160`, while checking Builder links as one guard at `backend/src/intric/flows/infrastructure/flow_run_history_purge_repo.py:339-371`. C9.2 keeps the global `Files` row at `backend/tests/integration/test_data_retention_hierarchical.py:939`. |
| Created Flow linkage | Created or edited Flows outlive Builder session history. Builder retention must not delete Flow rows. | `builder_sessions.flow_id` exists at `backend/src/intric/database/tables/flow_tables.py:2102`; Gate 0 retention inventory records Flow lifecycle as separate. |
| Cleanup scope/config | Reuse existing tenant/space retention policy. Do not add Builder-specific retention config for first release. | Effective policy resolution starts at `backend/src/intric/data_retention/infrastructure/data_retention_service.py:254`; Builder due query joins `Spaces` and `AuditRetentionPolicy` at `backend/src/intric/data_retention/infrastructure/data_retention_service.py:496-500`. |

## Builder Global File Posture

| Decision | C9.3 posture |
|---|---|
| Owner acceptance | Release governance accepts retained Builder-uploaded global `Files` rows for first release after Builder session retention removes `BuilderSessionFiles` pins. |
| Privacy/product rationale | Session conversation/planning/proposal rows and Builder file pins expire through `DataRetentionService`; deleting global `Files` rows without a Builder-specific candidate source would require a broader product/data-retention decision and risks a generic orphan sweeper. |
| What this does not claim | It does not claim uploaded file blobs are deleted, anonymized, or privacy-complete after Builder session deletion. |
| Deletion trigger | Revisit only if release owners reject retained Builder-uploaded global file rows, or if a future source owner records Builder upload candidate file ids safely enough to drive cleanup. |
| Future cleanup criteria | A later slice must name the candidate-id source, reuse or extract existing reference-guard semantics, prove cross-owner safety with behavior tests, and document whether migration/schema changes are required. |

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
| Builder retention/deletion/count | Done in C8.6 and C9.2. `DataRetentionService` owns terminal and abandoned active Builder count/delete; session rows are the deletion unit; plans and session-file links cascade; global files are not directly deleted. |
| Builder audit vocabulary delete-or-wire | Done in C8.7. Fake plan proposed/rejected audit actions were deleted; live emitted actions remain. |
| Lifecycle active-send/apply invariant | Done in C8.8. No-lease lifecycle transitions now respect active send locks. |
| Repair pruneability decision | Done in C8.14. No branch was pruned; branch-level evidence is still required. |
| Builder global file posture | Done in C9.3. Retained Builder-uploaded global `Files` rows are accepted for first release after Builder pins are removed; no generic file cleaner is added. |

## Next Implementation Lane

| Rank | Lane | Release value | Boundary |
|---|---|---|---|
| 1 | Repair/fallback branch-data review | Repair pruning remains blocked by missing branch-level evidence, not by missing framework code. | Read-only evidence review first; no pruning unless real telemetry/eval data proves a branch is dead, harmful, or too expensive. |

Deferred future risk: Builder-only global file-row cleanup is accepted for first release, not selected as the next lane. Revisit only if retained global file rows after Builder pin removal become unacceptable, and only with a named candidate-id source, reference guard, owner, and tests. Do not add a generic sweeper.

Question/slot cleanup and broader Builder maintainability can resume after the repair/fallback evidence review or if release owners decide repair pruning is no longer a release blocker.

## Recommended Next Bounded Prompt

Continue with exactly one bounded evidence/readiness slice: Flow AI Builder repair/fallback branch-data review.

Required acceptance criteria:
- Inventory JSON-text fallback, forced-tool retry, self-correction, and direct terminal failure branches against current C8.2/C8.5/C8.13 telemetry/eval evidence.
- Decide keep/delete/blocked for each branch, with file:line evidence and no production telemetry claims unless real artifacts exist.
- Do not prune source unless a branch is proven dead, unreachable, or harmful.
- Do not add telemetry frameworks, eval frameworks, MCP/capability descriptors, frontend/API/generated clients, Flow runtime changes, audit vocabulary, retention changes, or schema/migrations.

## Remaining Builder Release Blockers

| Blocker | Why it remains | Next action |
|---|---|---|
| Builder-only global file-row cleanup | C9.3 accepts retained global `Files` rows for first release after Builder pins are removed. | Not a release blocker unless product/privacy owners reject this posture; if rejected, use a separate candidate-driven cleanup slice. |
| Repair branch deletion evidence | Existing evidence does not prove repair/fallback branches are dead or harmful. | Collect/review branch-level evidence before any pruning slice. |

## What Not To Do Next

- Do not implement MCP, capability descriptors, `AssistantConfigurationService`, or PR #480 loopback-MCP behavior.
- Do not prune repair/fallback branches without branch-level evidence.
- Do not create a Builder retention service, generic lifecycle manager, command bus, event-sourcing layer, legal-hold framework, or generic file cleaner.
- Do not broaden into frontend redesign, generated-client cleanup, Flow runtime/API changes, audit vocabulary changes, or schema/migration work from this packet.
- Do not split large Builder files by line count before deleting or consolidating named duplicate owners.
