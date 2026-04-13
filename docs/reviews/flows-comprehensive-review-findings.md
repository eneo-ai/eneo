# Flows + Flows AI Builder — Comprehensive Review Findings

_Date:_ 2026-04-11  
_Mode:_ cautious, verified, ROI-ordered  
_Scope:_ `backend/src/intric/flows/**`, `backend/src/intric/flows/ai_builder/**`, flow-related Celery/runtime, flow-related migrations/tests, and backend API surfaces directly serving flows.

## 1. Review method and evidence

### Evidence gathered
- Read `docs/reviews/flows-comprehensive-review.md` twice, including the updated maintainability appendix and quality gates.
- Inspected the main hot spots named in the brief:
  - `backend/src/intric/flows/flow_permissions.py`
  - `backend/src/intric/flows/api/{flow_api_common.py,flow_router_common.py,flow_authoring_router.py,flow_run_execution_router.py,flow_run_steps_router.py,flow_run_evidence_router.py,flow_upload_router.py}`
  - `backend/src/intric/flows/application/{flow_service.py,flow_run_service.py,flow_dispatch.py}`
  - `backend/src/intric/flows/infrastructure/{flow_repo.py,flow_run_repo.py}`
  - `backend/src/intric/flows/runtime/{celery_app.py,celery_execution_backend.py,tasks.py,claim_resolution.py,output_runtime.py}`
  - `backend/src/intric/flows/ai_builder/{ai_builder_router.py,ai_builder_service.py,ai_builder_repo.py,ai_builder_plan_lifecycle.py,ai_builder_planner.py}`
  - `backend/src/intric/database/tables/flow_tables.py`
  - flow-related migrations under `backend/alembic/versions/`
- Database inspection via `docker exec eneo-41ae93-db-1 psql -U postgres -d postgres`:
  - foreign keys
  - indexes
  - sequential scan counters
  - `EXPLAIN (ANALYZE, BUFFERS)` for stale queued-run redispatch query
- Runtime verification:
  - `docker exec -w /workspace/backend eneo-41ae93-eneo-1 bash -lc 'export PATH=/home/vscode/.local/bin:$PATH && uv run pyright src/intric/flows'`
    - result: `0 errors, 0 warnings, 0 informations`
  - `docker exec -w /workspace/backend eneo-41ae93-eneo-1 bash -lc 'export PATH=/home/vscode/.local/bin:$PATH && uv run pytest tests/unittests/flows/test_flow_router.py tests/unittests/flows/ai_builder/test_ai_builder_router.py tests/unittests/flows/test_celery_runtime.py -q'`
    - result: `122 passed, 17 warnings`
- Coverage spot checks:
  - `security_classification` mentions in flow tests: `0`
  - `session_creator_required` mentions in AI Builder router/integration tests: `0`
  - `Idempotency-Key` mentions in flows API/application code: `0`

### Important verification caveat
Flow integration tests are currently blocked by the branch's Alembic graph, not by a verified flow logic failure:
- running flow integration tests produced `alembic.util.exc.CommandError: Multiple head revisions are present for given argument 'head'; 202604091000, 20260410_schema_drift_guard`.
- I am treating that as a **follow-up / branch migration topology issue**, not as a flows-subsystem logic defect, because the conflicting head is not a flow-only migration and the failure occurs before the flow tests execute.

### Overall assessment
- **Guard coverage exists** on the reviewed flows endpoints; the biggest problems are **guard granularity and ownership policy drift**, not a total absence of guards.
- **Tenant scoping is generally present** in the repositories inspected.
- **Optimistic locking exists** for flow draft edits via `draft_revision`.
- The highest-ROI work is **not** a rewrite. It is a sequence of surgical permission, dispatch, idempotency, and lifecycle fixes that improve maintainability by centralizing policy in fewer places. The preferred execution style is characterization tests first, then the smallest policy/dispatch seam needed to fix the specific bug.

---

## 2. ROI-ranked top 10 action items

ROI formula from the brief:

> **ROI = (Severity × Likelihood) / (Cost × Fix risk)**

| Rank | ID | Title | Dimension(s) | Sev | Likelihood | Cost | Fix risk | ROI | Priority |
|---|---|---|---|---:|---:|---:|---:|---:|---|
| 1 | F-01 | Replace best-effort timeout cancellation with a real task-stop contract | Celery, Clean architecture | 4 | 4 | 2 | 2 | **4.00** | P1 |
| 2 | F-02 | Add missing regression coverage for ownership / creator-only / classification boundaries | Tests | 2 | 4 | 2 | 1 | **4.00** | P1 |
| 3 | F-03 | Make AI Builder session ownership explicit and consistent on read/send/cancel/list endpoints | Permissions | 4 | 4 | 2 | 2 | **4.00** | P1 |
| 4 | F-04 | Encode an explicit draft-visibility policy in list endpoints | Permissions | 4 | 4 | 2 | 2 | **4.00** | P1 |
| 5 | F-05 | Add run-creation idempotency for API consumers | API ergonomics | 4 | 3 | 2 | 2 | **3.00** | P1 |
| 6 | F-14 | Define explicit service-key principal semantics for flows and runs | API keys, Permissions, Data model | 4 | 4 | 3 | 2 | **2.67** | P1 |
| 7 | F-06 | Replace blanket flow-viewer run/artifact visibility with an explicit policy | Permissions | 5 | 3 | 2 | 3 | **2.50** | P1 |
| 8 | F-07 | Prevent duplicate active AI Builder sessions under concurrent create/resume | Database, AI Builder | 3 | 3 | 2 | 2 | **2.25** | P2 |
| 9 | F-08 | Add recovery for runs stuck in `running` after worker loss | Celery | 4 | 3 | 3 | 2 | **2.00** | P1 |
| 10 | F-09 | Preserve historical run traceability when flows are deleted | Database & schema | 4 | 3 | 3 | 2 | **2.00** | P1 |

**Logged but not priority-queue material in this pass:**
- F-10: explicit space-owner / space-admin / tenant-admin mutation policy for flow authoring actions (**ROI 1.67**). Important, but it depends on first agreeing the policy matrix and service-principal model.
- F-11: end-to-end security classification propagation and runtime re-validation for flows (**ROI 0.94**). High impact, but materially cross-cutting and riskier than the items above. It should still be designed early because the public-sector security implications are serious.

---

**Execution prerequisite / risk item (must be handled before execution-phase verification):**
- **P-00 — Resolve the current Alembic multiple-head state first.** Flow integration tests are currently blocked by `202604091000` vs `20260410_schema_drift_guard`. Mitigation options: (a) add a merge migration and keep `alembic upgrade head`, or (b) temporarily teach the integration fixture to target explicit heads while the graph is being merged. Several high-ROI fixes below need integration verification, so this is an execution prerequisite even though it is not itself a flows-domain logic bug.

### Recommended policy baseline for the permission findings below
These findings are ranked using the following **recommended baseline policy**, so execution work should confirm or amend this matrix before any code change:

### Terminology guardrail (to avoid mixing admin types)
- **Tenant/platform admin** means a caller with tenant-wide administrative authority (for example `Permission.ADMIN`, and in your product language the predefined owner-level tenant role). This is **not** the same as a space admin. The review does **not** treat tenant admin as constrained by ordinary space-admin boundaries; tenant admin is effectively a higher-order platform authority and should be documented separately.
- **Space admin** means `SpaceRole.ADMIN` inside one space only. A space admin must **not** be treated as omnipotent if their tenant-level effective permissions are lower than another user's.
- **Effective rule for the flows review:** a caller's space role can only grant actions that are also allowed by the caller's tenant-level/predefined-role permission envelope. In other words, space-level admin rights must not become a way to hijack capabilities that the caller does not truly hold at the tenant/platform layer.
- Therefore, when this report says **same-space admin**, it means a space-scoped admin actor **without** automatic tenant-wide override powers.

### Ownership-model guardrail (parallel to the API-key discussion)
For flows, the analogous ownership concepts should be treated explicitly rather than implicitly:
- **`created_by_user_id` on Flow** = audit trail: who created the draft.
- **`owner_user_id` on Flow** = logical draft owner / principal whose authorship and override semantics matter.
- **`user_id` on FlowRun** = who executed the run.
- **AI Builder `actor_user_id`** = who owns the planning session and plan lifecycle.
- **Run artifacts** should not be treated as generic "file owner can read" objects in flows UX; they should inherit access from the resolved run/flow visibility policy.
- **Service keys** are non-human principals. If flows are meant to support them, they should not be forced through human-user ownership columns or human-membership assumptions.

This means the review should answer the same questions you raised for API keys:
1. If another member edits/publishes/deletes a flow, are they acting as themselves, or as the flow owner?
2. If another member downloads an artifact, is that allowed because they can view the flow, because they can view the run, because they are a space admin, or because they are tenant admin?
3. If the flow owner loses space membership or loses the tenant-level permissions that justified their effective authority, what still works, what becomes read-only, and what is revoked immediately?
4. If a same-space admin has a weaker tenant/predefined-role permission set than another same-space admin, they must not be able to use space role alone to hijack that stronger principal's flow authority.
5. If a service key is supposed to run or own flows, does the system model it as a first-class non-human principal, or is it accidentally being forced through `Users.id` foreign keys and human-only permission checks?

The high-ROI execution work should make those ownership transitions explicit for flows, runs, AI Builder sessions, service keys, and artifacts, just as with API keys.

| Action | Creator | Same-space editor (non-creator) | Same-space admin (non-owner) | Space owner | Space-scoped API key |
|---|---|---|---|---|---|
| List/view unpublished drafts | Yes | No | Yes | Yes | No broader than bound principal |
| Mutate/delete/publish another person's draft | n/a | No | No by default; only via explicit override workflow if product approves, and never beyond the caller's tenant-level effective permission envelope | Yes | No |
| Run published flow | Yes | Yes if flow is shared and caller has run permission | Yes | Yes | Yes, but only within scoped space and published-flow surface |
| Read another user's run history / step outputs / artifacts | Own runs only by default | No | Only with explicit space-admin trace/support policy and audit, and never beyond tenant-level effective permissions | Yes with audit | No by default |
| Evidence export / rich trace | Own runs only unless an explicit space-admin trace policy grants more | No | Yes only with `FLOWS_TRACE`-level policy and audit, and never beyond tenant-level effective permissions | Yes with audit | No by default |

---

## 3. Findings by review dimension

### 3.1 Permissions & Authorization

**Positive note:** I did not find an unguarded flows endpoint in the reviewed routers. The permission problems are about **policy granularity and ownership semantics**, not missing guard hooks.


### F-03 — P1 — AI Builder session ownership is not encoded consistently on read/send/cancel/list endpoints
**ROI:** 4.00 (`(4×4)/(2×2)`)  
**Affected files:**
- `backend/src/intric/flows/ai_builder/ai_builder_router.py`
- `backend/src/intric/flows/ai_builder/ai_builder_service.py`
- `backend/src/intric/flows/ai_builder/ai_builder_planner.py`

**Why it matters (concrete scenario):**
A same-space editor or same-space admin can fetch another user's AI Builder session, read the full conversation, stream new planner messages into it, cancel it, and list its plans. In a municipality scenario this can expose prompts, uploaded-case context, and draft automation intent from another employee. **This is a defect if the intended policy is creator-scoped AI Builder work; the current code does not encode that policy explicitly.**

**Verified evidence:**
- Router endpoints `send_message`, `get_session`, `get_session_models`, `get_plan`, `list_session_plans`, and `cancel_session` all load the session/plan and then only call `_require_flow_edit_permission(container, session.space_id)`.
- `AIBuilderService.send_message()` and `AIBuilderPlanner.send_message()` do **not** re-check `session.actor_user_id == self.user.id`.
- Creator-only checks exist only in:
  - `AIBuilderPlanLifecycle._require_session_creator()` for `approve_plan` / `apply_plan`
  - `AIBuilderService.revise_plan()`
- Coverage gap confirmed: `session_creator_required` mentions in AI Builder router/integration tests = `0`.

**Pros of fixing:**
- Closes a concrete same-space data exposure vector.
- Makes AI Builder behavior consistent: creator-only should mean creator-only everywhere, not only during approve/apply.
- Reduces future policy drift by forcing a single ownership rule.

**Cons / risks of fixing wrong:**
- If some teams intentionally share AI Builder sessions between same-space admins, a creator-only clamp could remove a workflow they depend on. If the intended policy is shared-by-role rather than creator-only, that rule should be encoded explicitly instead of left implicit.
- API-key behavior must remain coherent with space-scoped automation tokens.

**Test plan for the fix:**
- Unit router tests for `get_session`, `send_message`, `get_plan`, `list_session_plans`, and `cancel_session` with:
  - creator user → allowed
  - same-space non-creator space admin/editor → denied
  - wrong-space caller → denied
- Integration test: user A creates session; user B in same space cannot read/cancel/send.

**Estimated effort:** M

---

### F-04 — P1 — `GET /flows/` does not encode an explicit unpublished-draft visibility rule
**ROI:** 4.00 (`(4×4)/(2×2)`)  
**Affected files:**
- `backend/src/intric/flows/api/flow_authoring_router.py`
- `backend/src/intric/flows/application/flow_service.py`
- `backend/src/intric/flows/infrastructure/flow_repo.py`
- `backend/src/intric/actors/actors/space_actor.py`

**Why it matters (concrete scenario):**
A viewer in a shared municipal space can call `GET /api/v1/flows/?space_id=...` and enumerate draft flow names/descriptions created by other employees, even though `GET /api/v1/flows/{id}/` already blocks viewers from opening unpublished flows directly. **This is a defect if unpublished drafts are intended to be creator-scoped or space-admin-scoped; the current code does not encode that policy explicitly in the list path.**

**Verified evidence:**
- `list_flows()` checks only `access_context.actor.can_read_flows()`.
- It then returns `flow_service.list_flows(space_id=...)`, which returns all flows in the space.
- No author filter, no published filter, no per-item `actor.can_read_flow(flow)` filter is applied.
- `SpaceActor.can_perform_action()` only applies unpublished-resource filtering for `SpaceRole.VIEWER` **when a concrete resource object is passed**; the list path never passes a resource.

**Pros of fixing:**
- Aligns list behavior with direct `GET /flows/{id}/` behavior.
- Prevents silent metadata leakage.
- Simplifies the mental model: unpublished drafts are private unless policy says otherwise.

**Cons / risks of fixing wrong:**
- Existing shared drafting workflows could lose visibility if the product intentionally allows non-author editors/admins to list drafts. If the intended policy is shared-by-role rather than creator/space-admin-scoped drafts, that rule should be encoded explicitly instead of left implicit.
- Needs a deliberate answer for editors vs space admins vs space owners vs creator, separate from tenant-admin override behavior.

**Test plan for the fix:**
- Unit tests for list endpoint:
  - viewer sees only published flows
  - non-author editor behavior follows explicit policy
  - same-space admin behavior follows explicit policy
  - author always sees own drafts
- Integration test with mixed published/unpublished flows in one space.

**Estimated effort:** M

---

### F-06 — P1 — Run payloads, step outputs, and artifacts currently follow a blanket flow-viewer access rule
**ROI:** 2.50 (`(5×3)/(2×3)`)  
**Affected files:**
- `backend/src/intric/flows/api/flow_run_execution_router.py`
- `backend/src/intric/flows/api/flow_run_steps_router.py`
- `backend/src/intric/flows/api/flow_run_evidence_router.py`
- `backend/src/intric/flows/application/flow_run_service.py`
- `backend/src/intric/flows/api/flow_api_common.py`

**Why it matters (concrete scenario):**
A user who can only view a published flow can currently list all runs for that flow, fetch another user's run payload, inspect step outputs, and generate a signed download URL for the other user's artifact. In a public-sector case-work flow that may expose uploaded transcripts, generated summaries, PDFs, or intermediate reasoning to unrelated colleagues. **This is a defect if flow execution rights are not supposed to imply cross-user run visibility; the current code chooses that policy broadly and explicitly.**

**Observed behavior in code:**
- `list_flow_runs_alias()`, `get_flow_run_alias()`, `list_flow_run_steps()`, and `generate_flow_run_artifact_signed_url()` all enforce only `required_access="view"`.
- `/evidence/` and `/evidence/export` additionally require `ensure_can_view_flow_trace(user)`; the other run/step/artifact endpoints do not.
- `flow_run_steps_router.py` explicitly documents the current behavior: _"any user with access to the flow can download artifacts from any run, regardless of who created the run."_

**Policy implication / risk:**
- In a public-sector setting, this means current code equates flow-view permission with cross-user run-history visibility unless a stricter policy is added.

**Pros of fixing:**
- Makes sensitive run outputs default-safe.
- Lets the system support explicit policies such as creator-only, same-space-admin override, or shared-run-by-design.
- Brings traceability endpoints under one coherent authorization story.

**Cons / risks of fixing wrong:**
- Some teams may rely on shared run visibility for collaboration or support.
- Tightening visibility may require frontend or API consumer messaging if current behavior is depended on. Because the current behavior is explicitly documented, this item should be treated as a **policy hardening change** rather than an accidental typo fix.

**Test plan for the fix:**
- Unit tests for each run/history/artifact endpoint under creator, same-space admin, same-space non-creator member, tenant admin, and outsider scenarios.
- Integration test: user A runs flow; user B can execute same flow but cannot view A's runs/artifacts unless policy explicitly allows it. The suite should freeze whether same-space admins/support users get an override path or not, and keep that distinct from tenant-admin override behavior.

**Estimated effort:** M

---

### F-10 — P1 — Flow ownership, space-admin authority, and tenant-admin override are not encoded explicitly enough in mutate/delete/publish authorization
**ROI:** 1.67 (`(5×3)/(3×3)`)  
**Affected files:**
- `backend/src/intric/flows/application/flow_service.py`
- `backend/src/intric/flows/api/flow_definition_access.py`
- `backend/src/intric/flows/api/flow_authoring_router.py`
- `backend/src/intric/actors/actors/space_actor.py`
- `backend/src/intric/flows/domain/flow.py`

**Why it matters (concrete scenario):**
A same-space admin can update, publish, unpublish, or delete another same-space admin's draft flow because the system stores `owner_user_id` but never consults it during authorization. That directly conflicts with the review brief's owner-vs-space-admin threat model. Separately, the code does not make it explicit that a tenant/platform admin is a different authority tier from a space admin, which makes it easy for future changes to blur those two concepts. **This is a policy-gap finding unless the product intentionally treats `owner_user_id` as informational only.**

**Verified evidence:**
- `owner_user_id` is stored on `Flow`, persisted in `FlowRepository`, and returned by models.
- Under `backend/src/intric/flows/**`, the only `owner_user_id` usages are model/persistence; there is **no** authorization use.
- `require_flow_edit_access()` checks only `actor.can_edit_flows()`.
- `delete_flow()` checks only `actor.can_delete_flows()`.
- `publish_flow()` / `unpublish_flow()` check only `actor.can_publish_flows()`.
- `SpaceActor` provides flow-level create/edit/delete/publish actions, but not a resource-specific creator/owner mutation rule.

**Pros of fixing:**
- Prevents same-space admin/editor hijack of another person's draft work.
- Aligns code with stored domain data (`owner_user_id`).
- Clarifies how tenant admin, space owner, space admin, editor, and viewer differ for unpublished artifacts and authoring actions.
- Gives flows the same clean ownership model that API keys already rely on: owner/principal vs rotator/actor vs auditor.

**Cons / risks of fixing wrong:**
- Requires a clear product policy for when a same-space admin may override another creator, and how that differs from tenant-admin override. If the intended policy is shared-by-role rather than owner-aware mutation, that rule should be encoded explicitly instead of inferred from stored metadata.
- Touches hot authorization paths and may affect existing admin workflows.

**Test plan for the fix:**
- Integration tests:
  - space admin A cannot mutate/delete space admin B's draft without explicit override rule
  - space owner override behavior follows policy
  - published-flow override behavior follows policy
- Unit tests for a new resource-specific flow mutation policy helper.

**Estimated effort:** M

---

### 3.2 Security Classification Propagation

### F-11 — P1 (logged, ROI < 1) — Flow classification is represented as metadata only; enforcement is missing at publish and runtime
**ROI:** 0.94 (`(5×3)/(4×4)`)  
**Affected files:**
- `backend/src/intric/flows/flow_validators.py`
- `backend/src/intric/flows/application/flow_service.py`
- `backend/src/intric/flows/runtime/**`
- `backend/src/intric/flows/api/flow_models.py`
- `backend/src/intric/flows/flow_run_evidence.py`

**Why it matters (concrete scenario):**
A municipality could build a flow that pulls a high-classification knowledge source into one step, routes the output into a lower-classification downstream step or model, and nothing in flows would reject it. That is a direct Bell-LaPadula “no write down” violation.

**Verified evidence:**
- In `backend/src/intric/flows/**`, classification references are almost entirely limited to:
  - `output_classification_override` on step/domain/API/evidence models
  - graph/evidence/report plumbing
- There is **no** verified publish-time or runtime evaluator that checks effective step classification against:
  - models
  - MCP tools
  - knowledge sources
  - uploaded/runtime files
  - downstream step chaining
- Flow test coverage confirms the gap: `security_classification` mentions in flow tests = `0`.

**Pros of fixing:**
- Essential for public-sector sensitive-data correctness.
- Makes flows consistent with the rest of Eneo's classification model.
- Enables auditable historical classification decisions.

**Cons / risks of fixing wrong:**
- Cross-cutting change touching validators, runtime execution, and probably UI contract surfaces.
- Easy to create false denials if inheritance/default rules are not modeled precisely. This item likely requires coordination with non-flows subsystems that already own classification on spaces, models, MCP, and knowledge, so it should be treated as a cross-cutting design program rather than a local one-file fix.

**Test plan for the fix:**
- Pure unit tests for effective-classification resolution.
- Publish-time validation tests for write-up allowed / write-down denied.
- Runtime reclassification tests (resource changes after publish).
- Integration tests covering models, MCP tools, knowledge sources, and runtime uploads.

**Estimated effort:** L

---

### 3.3 Celery Worker Reliability

### F-01 — P1 — Timeout handling does not guarantee that flow work actually stops
**ROI:** 4.00 (`(4×4)/(2×2)`)  
**Affected files:**
- `backend/src/intric/flows/runtime/tasks.py`
- `backend/src/intric/flows/runtime/celery_app.py`
- `backend/tests/unittests/flows/test_celery_runtime.py`

**Why it matters (concrete scenario):**
If flow execution exceeds the configured timeout, the task wrapper marks the run as failed and calls `future.cancel()`, but the underlying coroutine is running on a long-lived background event-loop thread. In asyncio, cancellation is cooperative. If the coroutine is blocked in non-cancellable work, it can continue mutating state or talking to external systems after the user has already been told the run failed.

**Verified evidence:**
- `execute_flow_run()` delegates to `_execute_flow_run_task()`.
- `_execute_flow_run_task()` waits on `future.result(timeout=get_settings().flow_task_timeout_seconds)`.
- On timeout it calls `future.cancel()`, logs failure, and marks the run failed.
- There is no Celery `soft_time_limit` / `time_limit` configuration in `create_celery_app()` or flow task decorator settings.
- The flow task loop is a process-global daemon thread (`_FLOW_TASK_LOOP_THREAD`), so the timeout path is not a hard stop of the underlying work.

**Pros of fixing:**
- Makes timeout behavior truthful: failed means stopped.
- Reduces the chance of late writes, duplicate side effects, or confusing post-failure artifacts.
- Clarifies the execution contract between Celery, asyncio, and run-state transitions.

**Cons / risks of fixing wrong:**
- Cooperative cancellation can be tricky around I/O and DB sessions.
- Hard time limits need reconciliation logic so they do not leave `running` rows behind.

**Test plan for the fix:**
- Unit tests for cooperative cancellation and timeout-to-failed behavior.
- Unit tests for hard-kill reconciliation into `failed`.
- Integration test with a deliberately hanging step.

**Acceptance gate:**
- A timed-out run cannot continue mutating DB state or external systems after failure is recorded.
- The flow worker uses a documented `soft_time_limit` / `time_limit` (or an equivalent hard-stop strategy) plus reconciliation.
- Timeout and worker-loss paths emit machine-readable failure reasons.

**Estimated effort:** M

---

### F-08 — P1 — There is no recovery path for runs stuck in `running`
**ROI:** 2.00 (`(4×3)/(3×2)`)  
**Affected files:**
- `backend/src/intric/flows/runtime/tasks.py`
- `backend/src/intric/flows/application/flow_run_service.py`
- `backend/src/intric/flows/infrastructure/flow_run_repo.py`
- `backend/src/intric/flows/runtime/celery_app.py`

**Why it matters (concrete scenario):**
If a worker process dies after a run has already transitioned from `queued` to `running`, and the task is not cleanly retried to completion, the run can remain `running` indefinitely. Users will see a permanently spinning flow with no automatic cleanup.

**Verified evidence:**
- There is a stale-queued redispatch path:
  - `list_stale_queued_runs()`
  - `claim_stale_queued_run_for_redispatch()`
  - `redispatch_stale_queued_runs()`
- There is **no equivalent stale-running watchdog**.
- Celery config includes `task_acks_late=True`, `task_reject_on_worker_lost=True`, and `worker_prefetch_multiplier=1`, but no `soft_time_limit`, `time_limit`, `task_failure`/`worker_lost` reconciliation, or periodic stuck-run scanner.

**Pros of fixing:**
- Prevents user-visible forever-running runs.
- Improves operator confidence and incident recovery.
- Provides a natural place for SLA-based observability.

**Cons / risks of fixing wrong:**
- A watchdog that is too aggressive can mark legitimately long runs as failed.
- Reconciliation logic must avoid fighting with late-arriving workers.

**Test plan for the fix:**
- Unit tests for stale-running scanner thresholds.
- Unit tests for state transition guard: only mark still-running rows as failed.
- Integration test with simulated worker loss / timeout.

**Proposed recovery contract for execution:**
- Treat a run as stale-running only when it is still `running` and older than `flow_task_timeout_seconds + 60s` (or a clearly documented minimum floor).
- Reconciliation must be compare-and-set on the current `running` state only.
- Emit an audit/log/metric event with a machine-readable reason such as `worker_stalled_reconciled`.

**Estimated effort:** M

---

### 3.4 Database & Schema

### F-07 — P2 — AI Builder resumable-session creation is race-prone under concurrent starts
**ROI:** 2.25 (`(3×3)/(2×2)`)  
**Affected files:**
- `backend/src/intric/flows/ai_builder/ai_builder_service.py`
- `backend/src/intric/flows/ai_builder/ai_builder_repo.py`
- `backend/src/intric/database/tables/flow_tables.py`
- `backend/alembic/versions/202603121400_add_ai_builder_tables.py`

**Why it matters (concrete scenario):**
If the same user opens two tabs and hits “start/resume AI Builder” nearly simultaneously, both requests can miss `find_latest_resumable_session()` and create separate active sessions for the same `(tenant, actor, space, target_kind, flow)` tuple.

**Verified evidence:**
- The create path is:
  - `find_latest_resumable_session(...)`
  - if none found → `create_session(...)`
- There is no DB uniqueness constraint or locking on active resumable sessions.
- Current indexes are single-column (`tenant_id`, `flow_id`, `actor_user_id`), not a uniqueness or exclusion rule.

**Pros of fixing:**
- Prevents duplicate draft threads and conflicting plan history.
- Makes resume semantics deterministic.
- Lowers support/debugging burden for AI Builder issues.

**Cons / risks of fixing wrong:**
- Requires care around `cancelled` / `applied` sessions so legitimate new sessions are not blocked.
- A partial unique index must match the business rule exactly.

**Test plan for the fix:**
- Repository concurrency test for same-user same-flow session creation.
- Integration test with concurrent create/resume requests.
- Migration test for partial unique index / locking behavior.

**Estimated effort:** M

---

### F-09 — P1 — Flow deletion preserves rows but destroys historical step linkage
**ROI:** 2.00 (`(4×3)/(3×2)`)  
**Affected files:**
- `backend/src/intric/flows/infrastructure/flow_repo.py`
- `backend/src/intric/database/tables/flow_tables.py`
- `backend/src/intric/flows/api/flow_authoring_router.py`
- `backend/src/intric/flows/application/flow_run_service.py`

**Why it matters (concrete scenario):**
Deleting a flow soft-deletes the flow row but hard-deletes all `flow_steps`. Historical `flow_step_results.step_id` and `flow_step_attempts.step_id` use `ON DELETE SET NULL`, so deleting a flow destroys step linkage for historical evidence. The historical runs remain in the DB but become harder to audit, and the deleted flow is no longer retrievable through flow-first APIs.

**Verified evidence:**
- `FlowRepository.delete()`:
  - sets `flows.deleted_at`
  - hard-deletes `FlowSteps`
  - hard-deletes eligible flow-managed assistants
- `flow_step_results.step_id` and `flow_step_attempts.step_id` both reference `flow_steps.id` with `ON DELETE SET NULL`.
- Flow-first run access paths resolve the flow through `flow_service.get_flow()`, which filters `deleted_at IS NULL`.

**Pros of fixing:**
- Preserves evidence fidelity and auditability.
- Makes deletion semantics coherent: archive, not partial erasure.
- Reduces future surprises when run-history consumers appear.

**Cons / risks of fixing wrong:**
- Deletion semantics are sensitive: some users may expect immediate hard removal.
- Preserving steps/assistants for history can complicate draft cleanup unless clearly separated.

**Test plan for the fix:**
- Integration test: delete flow with historical run and verify step/evidence linkage is preserved according to policy.
- Repository test for assistant cleanup vs history preservation.
- API test for archived/deleted flow history behavior if supported.

**Acceptance gate:**
- Deleting a flow must not silently null out historical step references needed for audit.
- Historical runs/evidence must either remain retrievable under an explicit archive policy or be explicitly purged by a deliberate retention workflow—not as a side effect of draft deletion.

**Estimated effort:** M

---

### 3.5 API Consumer Perspective

### DX scorecard for the top 5 flow-consumer endpoints

| Endpoint | Current statuses documented | Error shape quality | Async clarity | Discoverability | DX score |
|---|---|---|---|---|---:|
| `GET /flows/{id}/run-contract/` | 200, 400, 403, 404 | good | n/a | strong | 8/10 |
| `POST /flows/{id}/files/` | 201, 400, 403, 404, 413, 415 | good | good | strong | 8/10 |
| `POST /flows/{id}/runs/` | 201, 400, 403, 404 | good per-field codes, but no idempotency | **weak** | decent | 5/10 |
| `GET /flows/{id}/runs/{run_id}/` | 200, 403, 404 | acceptable | poll-only | decent | 6/10 |
| `POST /flows/{id}/runs/{run_id}/artifacts/{file_id}/signed-url/` | 200, 403, 404 | acceptable | good | decent | 6/10 |

**Common error envelope observed:** `GeneralError`-style payloads with `message`, `intric_error_code`, optional `code`, and optional `context`.

### F-05 — P1 — Run creation has no idempotency contract for external consumers
**ROI:** 3.00 (`(4×3)/(2×2)`)  
**Affected files:**
- `backend/src/intric/flows/api/flow_run_execution_router.py`
- `backend/src/intric/flows/api/flow_models.py`
- `backend/src/intric/flows/application/flow_run_service.py`
- `backend/src/intric/flows/infrastructure/flow_run_repo.py`

**Why it matters (concrete scenario):**
A municipality integration posts an audio file to `POST /flows/{id}/runs/`, the network times out before the client receives the response, and the client retries. Eneo currently has no `Idempotency-Key` header handling or client-supplied request UUID for run creation, so the same input can create two runs and duplicate downstream artifact generation.

**Verified evidence:**
- `FlowRunCreateRequest` has `expected_flow_version`, `input_payload_json`, `step_inputs`, and `file_ids` — no idempotency field.
- Flows API/application code contains `0` matches for `Idempotency-Key` / `idempotency`.
- Existing idempotency handling in flows is limited to webhook delivery internals, not public run creation.

**Pros of fixing:**
- Directly improves third-party API reliability.
- Reduces accidental duplicate work and duplicate billable execution.
- Straightforward to document in OpenAPI.

**Cons / risks of fixing wrong:**
- Needs a durable uniqueness scope (tenant + flow + key + time window) that is strict enough to prevent duplicates but flexible enough for legitimate reuse.
- Response replay semantics must be explicit.

**Test plan for the fix:**
- API test: same `Idempotency-Key` + same payload returns same run.
- API test: same key + different payload rejected.
- Repository test for unique key persistence.

**Proposed idempotency contract for execution:**
- Scope key uniqueness to `(tenant_id, flow_id, actor_id_or_service_principal, idempotency_key)`.
- Store a normalized request fingerprint.
- Replay with identical fingerprint returns the original run resource.
- Replay with a different fingerprint returns `409 Conflict`.

**Estimated effort:** M

---

### 3.6 Clean Architecture, Maintainability & Code Quality

### F-12 — P2 — Permission semantics are centralized only halfway, which is why the current authorization bugs exist
**ROI:** 1.50 (`(3×4)/(2×4)`)  
**Affected files:**
- `backend/src/intric/flows/api/flow_api_common.py`
- `backend/src/intric/flows/api/flow_definition_access.py`
- `backend/src/intric/flows/ai_builder/ai_builder_router.py`

**Why it matters (concrete scenario):**
Adding a new rule such as “run history requires creator-or-space-admin” or “drafts are creator-only” currently requires touching multiple routers plus helper layers, because `required_access` is only enforced at the tenant-permission layer while the actor-level check in `enforce_flow_scope()` is hard-coded to `can_read_flows()`. That mismatch is how broad run visibility survived despite separate trace permissions.

**Verified evidence:**
- `_ensure_required_tenant_permission()` respects `manage` / `run` / `view`.
- `enforce_flow_scope()` then only checks `if access_context.actor is not None and not access_context.actor.can_read_flows(): ...`.
- Resource-specific checks are scattered:
  - `get_flow()` calls `actor.can_read_flow(flow)`
  - edit/delete/publish paths use route-local `can_edit_flows()` / `can_delete_flows()` / `can_publish_flows()`
  - AI Builder has its own space-edit helper
- The result is duplicated policy with inconsistent semantics. Given the brief's threat model, I am treating this as a root-cause maintainability defect, not a style complaint.

**Pros of fixing:**
- Reduces future auth regressions.
- Makes tenant-admin / space-owner / space-admin / session-creator rules easier to express and test.
- Improves readability: one policy surface instead of many partially overlapping route checks.

**Cons / risks of fixing wrong:**
- Refactoring the auth surface can break multiple endpoints at once if done too broadly.
- Must stay surgical: centralize policy, do not redesign the whole actor model.

**Test plan for the fix:**
- Characterization tests before refactor.
- Router tests per endpoint after refactor.
- One small policy-helper unit suite for each access mode.

**Estimated effort:** M

---

### 3.7 Tests

### F-02 — P1 — Critical ownership and classification boundaries are not protected by regression tests
**ROI:** 4.00 (`(2×4)/(2×1)`)  
**Affected files:**
- `backend/tests/unittests/flows/test_flow_router.py`
- `backend/tests/unittests/flows/ai_builder/test_ai_builder_router.py`
- `backend/tests/integration/flows/test_ai_builder_session_api_regressions.py`
- missing tests for classification rules under `backend/tests/unittests/flows/**`

**Why it matters (concrete scenario):**
The current code already has creator-only behavior in some AI Builder paths and broad same-space access in others, but the suite does not pin those boundaries. That means a future “cleanup” can silently widen or narrow access without anyone noticing until production.

**Verified evidence:**
- AI Builder router/integration tests contain `0` matches for `session_creator_required`.
- Flow tests contain `0` matches for `security_classification` / Bell-LaPadula terms.
- The unit suite does cover many happy paths and some deny paths (`122 passed` in the router/Celery subset), but not the most sensitive creator-only and classification boundaries from this brief. This finding is intentionally a **protective prerequisite**, not a substitute for choosing the correct product policy.

**Pros of fixing:**
- Cheapest way to make subsequent permission/classification fixes safer.
- Prevents regression while higher-risk fixes are implemented.
- High maintainability payoff: future contributors get executable policy examples.

**Cons / risks of fixing wrong:**
- If tests codify the wrong product policy, they can freeze a bad rule in place.
- This work must be split into characterization tests first and policy-locking tests second.

**Test plan for the fix:**
- Phase 1: characterization tests that pin current session ownership, current draft visibility, current run visibility, and current timeout publication/reconciliation behavior without asserting the future policy yet.
- Phase 2: after policy approval, add red/green regression tests for:
  - non-creator AI Builder session access
  - space-admin-vs-space-owner flow mutation behavior
  - list-draft visibility rules
  - run-history visibility rules
  - classification write-up/write-down rules
- Add integration tests once the Alembic-head prerequisite is resolved.

**Estimated effort:** S

---

## 4.6 Maintainability appendix (judgment-based)

These are **not** generic cleanup suggestions. Each item below names a concrete future change that the current structure makes harder, and a specific minimal fix with a favorable maintenance trade-off.

### M-01 — Flow authorization policy is spread across helpers and routers
- **Problem:** tenant permission, space actor permission, resource visibility, and session ownership are checked in different layers with different semantics.
- **Concrete future change it makes harder:** “make draft flows creator-only but published flows shared” currently requires touching list/get/update/delete/publish routes plus helper functions and AI Builder routes.
- **Minimal fix:** add one small `FlowAccessPolicy` / `AIBuilderSessionAccessPolicy` seam that accepts `(user, actor, resource, action)` and is reused by list/get/run/history endpoints, instead of widening the refactor beyond the current hot paths.
- **Fix risk:** moderate; touches hot auth paths.
- **Effort / ROI:** M / high.

### M-02 — Timeout, cancellation, and recovery semantics are spread across task wrapper code and state-transition code
- **Problem:** timeout handling lives in `runtime/tasks.py`, while stuck-run recovery and redispatch live elsewhere, so it is easy to change one half of the lifecycle without the other.
- **Concrete future change it makes harder:** introducing Celery-native soft/hard time limits or a worker-loss reconciliation rule without regressing timeout behavior.
- **Minimal fix:** define one small flow-task execution contract (timeout, cancellation, reconciliation, observability) and use it for both timeout failure and stale-running recovery.
- **Fix risk:** moderate because this is a hot runtime path.
- **Effort / ROI:** M / high.

### M-03 — AI Builder route access checks are duplicated and incomplete
- **Problem:** many AI Builder routes repeat `get session -> scope check -> space edit check`, but creator ownership is easy to forget.
- **Concrete future change it makes harder:** adding a new plan/session route without repeating the ownership bug.
- **Minimal fix:** introduce a single router-level helper that resolves the session/plan and optionally enforces `require_creator=True`.
- **Fix risk:** low.
- **Effort / ROI:** S-M / high.

### M-04 — Classification data is threaded through DTOs without a policy engine
- **Problem:** `output_classification_override` is persisted and surfaced, but there is no pure, reusable evaluator that explains a step's effective classification.
- **Concrete future change it makes harder:** “add k4”, “enforce MCP tool classification”, or “explain to a user why this model is unavailable” all require inventing policy during implementation.
- **Minimal fix:** a pure `resolve_effective_step_classification(...)` and `validate_flow_classification(...)` module reused at publish time and runtime.
- **Fix risk:** medium because this touches security-sensitive behavior.
- **Effort / ROI:** M-L / medium.

---

## 5. Scope confirmation / follow-ups

These items looked important but I am **not** treating them as in-scope fixes for this planning pass:

1. **Current branch Alembic multiple-head state**
   - Verified blocker for flow integration tests:
     - heads seen in test setup error: `202604091000`, `20260410_schema_drift_guard`
   - This is a migration-graph hygiene issue that must be resolved before relying on flow integration tests again.

2. **Space ownership / demotion rules outside flows**
   - The deeper tenant-admin / space-owner / space-admin semantics live primarily in `spaces/` and `actors/`.
   - Flows should consume that policy, but a broader ownership audit belongs in a separate review.

3. **Generic file/blob retention policy**
   - Flows artifacts are created via the shared `files` subsystem.
   - System-wide retention, storage backend migration, and blob cleanup policy likely need a cross-subsystem design.

4. **Non-flows Pydantic deprecation warnings seen during tests**
   - Observed in audit/group_chat/integration modules.
   - Real, but not flows-specific.

---

## 6. Recommended execution order for a later `$ralph` phase

If execution starts after planning approval, the best ROI-preserving sequence is:

1. **F-02 (phase 1)** add characterization tests first for current dispatch, session ownership, and visibility behavior.
2. **F-01** introduce a real timeout / hard-stop / reconciliation contract for flow tasks.
3. Confirm the explicit permission matrix above with the product owner / reviewer.
4. **F-02 (phase 2)** convert the approved policy into locking regression tests.
5. **F-03 + F-04** tighten AI Builder session ownership and draft list visibility.
6. **F-14** decide and encode the service-key contract for flows (explicit denial now, or first-class service principal support).
7. **F-06 + F-10** implement the approved flow/run ownership and visibility policy (creator vs space admin vs space owner vs tenant admin vs service principal vs shared-history).
8. **F-05** add public run idempotency using the contract above.
9. **F-08 + F-09** improve stuck-run recovery and delete/history preservation using the contracts above.
10. **F-11** design and implement classification policy only after the lower-risk authorization/runtime seams are stable.

That order maximizes safety, improves maintainability, and avoids speculative refactoring. The earlier timeout/recovery work should be kept surgical: clarify the task-stop contract, then wire the minimum Celery and repository changes needed to make it true.
