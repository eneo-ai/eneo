# Flow Builder Release Governance Packet - 2026-06-30

TL;DR:
- This packet is the Gate 1 decision record after the C9.0 Gate 0 refresh.
- Flow AI Builder stays native Eneo authoring; no MCP/capability implementation starts here.
- C9.2 completed active abandoned-session expiration in `DataRetentionService`.
- C9.3 accepts retained Builder-uploaded global `Files` rows for first release after Builder session pins are removed.
- C9.6 accepts current bounded repair/fallback branches for first release; branch value remains unproven.

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

## Repair / Fallback Branch Decisions

Current evidence is source reachability, unit behavior coverage, typed failed-turn telemetry coverage, and deterministic materialization goldens. That is useful engineering proof, but it is not real provider-output branch-value data. Do not prune repair/fallback code until a future slice can show branch frequency, recovery contribution, failed cost, final error-code distribution, provider finish reason where available, and content-free payload verification.

C9.6 first-release posture: keep the current bounded JSON/text fallback, forced-tool retry, self-correction, direct terminal classifiers, and architecture-error paths for first release. C9.5 found no usable branch-value dataset, and that no-data result proves neither value nor uselessness. Future pruning is blocked until a real branch-value dataset, production-like controlled eval, or explicitly scheduled live-eval artifact proves a branch is dead, harmful, redundant, or replaced.

| Branch family | Owner / reachability | Existing evidence | Decision | Future prune/delete acceptance criteria |
|---|---|---|---|---|
| JSON/text fallback | `ai_builder_proposal_repair.py` owns JSON-text parsing and processing at `backend/src/intric/flows/ai_builder/ai_builder_proposal_repair.py:757`; forced retry reaches it at `backend/src/intric/flows/ai_builder/ai_builder_proposal_repair.py:663`. | C8.14 cites behavior coverage at `backend/tests/unittests/flows/ai_builder/test_ai_builder_proposal_repair.py:419-531`; deterministic goldens prove materialization coverage, not live provider branch value, at `backend/tests/unittests/flows/ai_builder/eval_matrix/test_eval_matrix.py:142`. | Blocked: keep until real branch-level value data exists. | Delete only if real branch data proves it never saves proposals, is harmful, or is fully replaced by a stronger live branch. |
| Forced-tool retry after conversational/non-tool output | Proposal submission routes text-only missing-tool output into forced retry at `backend/src/intric/flows/ai_builder/ai_builder_proposal_submission.py:314` and `backend/src/intric/flows/ai_builder/ai_builder_proposal_submission.py:621`; repair owns the forced retry at `backend/src/intric/flows/ai_builder/ai_builder_proposal_repair.py:656`. | C8.14 cites tests for typed invocation, feedback, and information-request preservation at `backend/tests/unittests/flows/ai_builder/test_ai_builder_proposal_repair.py:336-417` and `backend/tests/unittests/flows/ai_builder/test_ai_builder_proposal_repair.py:535-588`. | Blocked: keep until real branch-level value data exists. | Delete only if branch data proves retry cost exceeds recovery value or another branch handles the same reachable provider output better. |
| Self-correction / repair for malformed or invalid tool arguments | Proposal submission routes malformed/invalid `propose_flow` tool submissions into self-correction at `backend/src/intric/flows/ai_builder/ai_builder_proposal_submission.py:547`; repair owns retry and terminal routing at `backend/src/intric/flows/ai_builder/ai_builder_proposal_repair.py:440`. | C8.13 added terminal failed-turn telemetry; C8.14 cites retry/recovery coverage at `backend/tests/unittests/flows/ai_builder/test_ai_builder_proposal_repair.py:695-743` and `backend/tests/unittests/flows/ai_builder/test_ai_builder_proposal_repair.py:1223-1415`, plus failed-turn coverage at `backend/tests/unittests/flows/ai_builder/test_ai_builder_proposal_repair.py:867-1220`. | Blocked: keep until real branch-level value data exists. | Delete or simplify only after branch data plus deterministic materialization review proves a sub-branch is dead, harmful, or redundant. |
| Direct terminal proposal failures | Proposal submission logs provider completion error, empty choices, provider truncation, and final forced-tool missing submission at `backend/src/intric/flows/ai_builder/ai_builder_proposal_submission.py:240`; failed-turn payload ownership is `backend/src/intric/flows/ai_builder/ai_builder_proposal_telemetry.py:60` and `backend/src/intric/flows/ai_builder/ai_builder_proposal_telemetry.py:291`. | C8.2/C8.13 cover content-free failed-turn payloads; C8.14 cites provider truncation and forced-tool terminal coverage at `backend/tests/unittests/flows/ai_builder/test_ai_builder_proposal_processor.py:397-524`. | Keep: these are classifiers/observability, not repair code. | Do not delete unless a future telemetry taxonomy replacement preserves the same release-readiness signal. |
| Architecture-error terminal paths | Architecture errors are not `ProposalFailedTurnBranch` values at `backend/src/intric/flows/ai_builder/ai_builder_proposal_telemetry.py:60`; they record first-attempt architecture failure at `backend/src/intric/flows/ai_builder/ai_builder_architecture_errors.py:51` and sanitized proposal error events at `backend/src/intric/flows/ai_builder/ai_builder_architecture_errors.py:68`. Live catch paths are at `backend/src/intric/flows/ai_builder/ai_builder_proposal_submission.py:580`, `backend/src/intric/flows/ai_builder/ai_builder_proposal_repair.py:403`, and `backend/src/intric/flows/ai_builder/ai_builder_proposal_repair.py:741`. | Tests prove sanitized architecture errors and first-attempt telemetry at `backend/tests/unittests/flows/ai_builder/test_ai_builder_proposal_submission.py:240-295` and `backend/tests/unittests/flows/ai_builder/test_ai_builder_proposal_repair.py:1443-1603`. | Keep: separate terminal architecture classification; do not treat as failed-turn pruning evidence. | Revisit only if product/observability owners choose a unified terminal-outcome taxonomy; do not fold it into repair pruning by default. |

Do not add a telemetry framework, eval framework, metric schema, event bus, or repair-policy layer from this packet. The missing evidence is branch value from real or production-like Builder runs, not more framework code.

## Completed Lanes

| Lane | Result |
|---|---|
| Builder retention/deletion/count | Done in C8.6 and C9.2. `DataRetentionService` owns terminal and abandoned active Builder count/delete; session rows are the deletion unit; plans and session-file links cascade; global files are not directly deleted. |
| Builder audit vocabulary delete-or-wire | Done in C8.7. Fake plan proposed/rejected audit actions were deleted; live emitted actions remain. |
| Lifecycle active-send/apply invariant | Done in C8.8. No-lease lifecycle transitions now respect active send locks. |
| Repair pruneability evidence and packet reconciliation | Done in C8.14 and reconciled in C9.4; C9.6 accepts current bounded branches for first release. No branch was pruned; no branch is delete-ready; real branch-level value data is required before any pruning slice. |
| Builder global file posture | Done in C9.3. Retained Builder-uploaded global `Files` rows are accepted for first release after Builder pins are removed; no generic file cleaner is added. |

## Next Release Lane

| Rank | Lane | Release value | Boundary |
|---|---|---|---|
| 1 | PG-10b global validation error contract | C9.6 closes the Builder repair/fallback first-release posture without claiming branch value is proven. The next code slice should move back to the app-global API contract gap that still blocks API consumer DX. | Main-app FastAPI `RequestValidationError` -> `GeneralError`; OpenAPI/generated-client impact; Flow endpoint tests; representative non-Flow endpoint tests; SCIM/sub-app compatibility review. Do not implement PG-10b inside Builder governance work. |

Deferred future risk: Builder-only global file-row cleanup is accepted for first release, not selected as the next lane. Revisit only if retained global file rows after Builder pin removal become unacceptable, and only with a named candidate-id source, reference guard, owner, and tests. Do not add a generic sweeper.

Question/slot cleanup and broader Builder maintainability can resume later. Do not send another repo-only source-pruning or no-data search slice for these branches without a named real branch-value dataset, controlled eval, or scheduled live-eval artifact.

## Recommended Next Bounded Prompt

Continue with exactly one bounded implementation slice: PG-10b app-global FastAPI validation error contract.

Required acceptance criteria:
- Decide and implement or explicitly defer main-app `RequestValidationError` -> `GeneralError`.
- Review generated-client/OpenAPI impact before changing the global 422 shape.
- Cover Flow endpoints plus representative non-Flow endpoints, including SCIM/sub-app compatibility review.
- Do not touch Builder repair/fallback pruning, telemetry frameworks, eval frameworks, MCP/capability descriptors, frontend redesign, Flow runtime changes, audit vocabulary, retention changes, or schema/migrations outside the API contract slice.

## Deferred Builder Risks After First-Release Acceptance

| Deferred risk | Why deferred | Next action |
|---|---|---|
| Builder-only global file-row cleanup | C9.3 accepts retained global `Files` rows for first release after Builder pins are removed. | Not a release blocker unless product/privacy owners reject this posture; if rejected, use a separate candidate-driven cleanup slice. |
| Repair branch deletion evidence | Existing source/test/eval evidence is concrete but not branch-value evidence. C9.6 accepts the current bounded branches for first release, but no branch is delete-ready. | Collect/review real or production-like branch data before any pruning slice; do not repeat repo-only no-data searches. |

## What Not To Do Next

- Do not implement MCP, capability descriptors, `AssistantConfigurationService`, or PR #480 loopback-MCP behavior.
- Do not prune repair/fallback branches without branch-level evidence.
- Do not create a Builder retention service, generic lifecycle manager, command bus, event-sourcing layer, legal-hold framework, or generic file cleaner.
- Do not broaden Builder governance into frontend redesign, generated-client cleanup, Flow runtime/API changes, audit vocabulary changes, or schema/migration work; PG-10b handles API/generated-client impact separately.
- Do not split large Builder files by line count before deleting or consolidating named duplicate owners.
