# Flows + Flows AI Builder — Comprehensive Review & Improvement Brief

> **Purpose:** Deep, honest review of the Flows and Flows AI Builder subsystems to find and fix real problems in permissions, security classification, Celery reliability, database design, API ergonomics, clean architecture, and tests — before we grow past 10,000 users in production.
>
> **Mode of operation:** Cautious, verified, ROI-ordered. No speculative refactors. No false positives. Every change must be justified, typechecked, tested, and backwards compatible.

---

## 1. Mission

Conduct a rigorous, end-to-end review of Eneo's Flows and Flows AI Builder subsystems across seven dimensions, and execute the highest-ROI fixes without breaking any existing functionality. The code must be ready to handle production traffic from municipal workers building automation pipelines, and from API consumers building third-party apps on top of Eneo (transcription services, multi-step agent systems, etc.). Ensure you also try to improve the maintainability of the code.

## 2. Scope

### IN SCOPE
- `backend/src/intric/flows/**` (all flows code)
- `backend/src/intric/flows/ai_builder/**` (AI builder)
- `backend/src/intric/flows/runtime/celery_app.py` + `celery_execution_backend.py` + all Celery tasks touched by flows
- Alembic migrations that add/modify flows-related tables
- API routers under `backend/src/intric/flows/api/**`
- Integration tests and unit tests under `backend/tests/**` that cover flows / ai-builder / celery flow tasks
- Frontend code **only** when a backend change breaks its contract (e.g., API schema change)
- Permission checks in `FlowService`, `FlowRepo`, `FlowRunRepo`, and the API routers
- Security classification propagation in flow validators and runtime executors
- Data model (`Flow`, `FlowStep`, `FlowRun`, `FlowVersion`, AI builder sessions, step attempts)

### OUT OF SCOPE (do not touch)
- ARQ worker (used by other subsystems — flows uses Celery, everything else uses ARQ)
- Assistants, chat, knowledge, spaces, users modules — **except** where flows calls into them
- Generic refactors unrelated to flows or ai-builder
- Style-only nitpicks (unless you are already touching that file for a real fix)
- Performance optimizations without measurable impact
- `frontend/**` code unless directly forced by a backend API contract change

### Scope tripwire
If you find a real bug outside scope, **document it** but do NOT fix it. Add it to a "follow-up" section in the findings report. Never expand scope silently.

## 3. Environment

The developer runs Eneo in a devcontainer. All backend commands must go through Docker:

```bash
# Run a backend command inside the devcontainer (replace <command>)
docker exec -w /workspace/backend eneo-41ae93-eneo-1 bash -c \
  "export PATH=/home/vscode/.local/bin:\$PATH && <command>"

# Run the full test suite (parallel, stop on first failure)
docker exec -w /workspace/backend eneo-41ae93-eneo-1 bash -c \
  "export PATH=/home/vscode/.local/bin:\$PATH && uv run pytest tests/ -x -n 5"

# Run only flow-related tests
docker exec -w /workspace/backend eneo-41ae93-eneo-1 bash -c \
  "export PATH=/home/vscode/.local/bin:\$PATH && uv run pytest tests/flows -x -n 5 -v"

# Strict pyright on a changed file
docker exec -w /workspace/backend eneo-41ae93-eneo-1 bash -c \
  "export PATH=/home/vscode/.local/bin:\$PATH && uv run pyright src/intric/flows/<relative-path>.py"

# Strict pyright on the whole flows module
docker exec -w /workspace/backend eneo-41ae93-eneo-1 bash -c \
  "export PATH=/home/vscode/.local/bin:\$PATH && uv run pyright src/intric/flows"

# Database access (schema inspection, query analysis, test data)
docker exec -it eneo-41ae93-db-1 psql -U postgres -d postgres
```

**Database credentials (local only, do not share):**
```
POSTGRES_USER=postgres
POSTGRES_PASSWORD=postgres
POSTGRES_PORT=5432
POSTGRES_HOST=localhost
POSTGRES_DB=postgres
```

### Useful inspection queries

```sql
-- Foreign keys on flow tables
SELECT conrelid::regclass AS table, conname, pg_get_constraintdef(oid)
FROM pg_constraint
WHERE contype='f' AND conrelid::regclass::text LIKE '%flow%'
ORDER BY table;

-- All indexes on flow tables
SELECT tablename, indexname, indexdef
FROM pg_indexes
WHERE tablename LIKE '%flow%'
ORDER BY tablename, indexname;

-- Table + index sizes
SELECT relname,
       pg_size_pretty(pg_table_size(relid)) AS table_size,
       pg_size_pretty(pg_indexes_size(relid)) AS index_size
FROM pg_catalog.pg_statio_user_tables
WHERE relname LIKE '%flow%'
ORDER BY pg_total_relation_size(relid) DESC;

-- Slow query suspects (tables with sequential scans)
SELECT relname, seq_scan, idx_scan,
       n_live_tup, n_dead_tup
FROM pg_stat_user_tables
WHERE relname LIKE '%flow%'
ORDER BY seq_scan DESC;
```

## 4. Review Dimensions

### 4.1 Permissions & Authorization

**The threat model to verify:**
- A **space admin** must not be able to hijack, overwrite, or destroy another admin's flows without clear, intentional authorization.
- A **space owner** (the person who created the space, or the designated owner) has powers that even admins do not — e.g., transferring ownership, deleting the space itself, demoting admins.
- Another admin must not be able to demote the owner, delete the owner's published flows unilaterally, or steal ownership.
- A non-admin space member must only see and run flows they have been explicitly granted access to.
- A user outside the space must never see, run, or modify flows in that space — not even by passing a flow UUID directly to an endpoint.

**Specific checks:**
1. **Every flow endpoint has a guard.** List, read, create, update, delete, publish, unpublish, run, cancel, rerun, inspect history, evidence export — all of them. Grep for `FastAPI` route decorators in `flows/api/**` and verify each has a permission dependency.
2. **IDOR (Insecure Direct Object Reference) check.** For each endpoint that takes a flow_id, verify the repo/service filters by the user's tenant AND their space membership. Never trust the ID alone.
3. **Draft vs published.** Draft flows should only be visible to the author and space admins. Published flows should be runnable by anyone in the space who has at least "run" permission. Check that draft queries filter by author.
4. **AI builder sessions.** An AI builder draft session belongs to one user; another user — even an admin — should not be able to resume or delete someone else's session without explicit permission rules.
5. **Owner vs admin distinction.** Search for `is_owner` / `SpaceRole.owner` / `SpaceRole.admin` and verify the code distinguishes them where it matters. If the code only checks "is admin", that's a gap.
6. **Permission inheritance.** When a flow is published, it inherits certain settings from the space. Verify that inheritance does not accidentally grant more permission than intended.
7. **Delete cascade safety.** When a user is deactivated, what happens to their draft flows? When a space admin is demoted, what happens to flows they created? When a space is deleted, what happens to its flows and runs?
8. **Audit trail.** Every permission-sensitive action (create, delete, publish, unpublish, change ownership, grant/revoke) should have an audit log entry including actor, subject, timestamp, old/new state.

**How to verify:**
- Read `flow_permissions.py` end-to-end
- Grep every `@router.*` in `flows/api/**` and trace the permission dependency chain
- Read `SpaceRole` enum and every usage
- Write integration tests that simulate "admin A tries to delete admin B's flow" and "external user tries to access flow_id"

---

### 4.2 Security Classification Propagation

**The rule (Bell-LaPadula "no write down"):**
> Data is allowed to flow **upward** in the classification hierarchy (less sensitive → more sensitive), but never **downward** (more sensitive → less sensitive). A k3 step must not be able to pass its output into a k1 step — that would leak sensitive data into a less-restricted channel. A k1 step passing to a k3 step is fine — the data just becomes more restricted.

**What must be checked:**
1. **Flow-level classification.** Every flow has a classification (or inherits one from its space). Verify this is set, stored, and propagated.
2. **Step-level classification.** Each step's effective classification is the max of: the flow's classification, the step's input source's classification, the step's knowledge bases' classifications, the step's attachments' classifications, the step's MCP tools' classifications.
3. **Model classification.** Every AI model has a classification (or an organizational default). A step must only be allowed to use a model whose classification is **at least as high** as the step's effective classification.
4. **Tool classification.** Every MCP tool has a classification. Same rule as models.
5. **Knowledge classification.** Every knowledge source (website, collection, integration) has a classification. Including a knowledge source in a step raises the step's effective classification.
6. **No-write-down enforcement in chaining.** If step N produces output classified at k3, step N+1 must be at k3 or higher. Reject flows at publish time where this rule is violated.
7. **Runtime re-validation.** Even if a flow passes validation at publish time, at runtime the classifications of involved resources may have changed (e.g., a knowledge source was reclassified). The runtime must re-check classifications before executing each step, not trust the publish-time snapshot.
8. **Surface the effective classification to the user.** In the step editor and in the FlowRunDialog, show the effective classification for each step so users understand why certain models/tools are unavailable.

**Where to look:**
- `SecurityClassification` model and all imports/usages
- `FlowValidator*` files — is classification checked?
- `flow_dispatch.py` and runtime — is classification checked at execution time?
- `spaces/` module — how classification is inherited
- Model / MCP / knowledge modules — how classification is stored and read
- The existing classification enforcement on the **assistant** — flows should follow the same patterns

**Common gaps to look for:**
- Classification checked at the API layer but not at the service layer (bypassable by other callers)
- Classification checked on the step's model but not on its knowledge sources
- Classification checked at validation time but not at runtime
- Classification not stored on flow runs, so historical runs can't be audited
- Classification silently ignored when a default value is missing

---

### 4.3 Celery Worker Reliability

**Target: Production-grade Celery usage.**

**Best practices to evaluate one-by-one:**

1. **Task idempotency.** Can any task be safely retried? If a task updates a DB row, uploads a file, and calls an external API, what happens if it crashes between steps and is retried? Use idempotency keys, upserts, and "if not exists" guards.

2. **Retry policy.**
   - Exponential backoff with jitter: `retry_backoff=True`, `retry_jitter=True`, `retry_backoff_max=600`.
   - `max_retries` set explicitly (default infinity is dangerous).
   - `autoretry_for=(ConnectionError, TimeoutError, ...)` for transient errors.
   - Never retry validation errors (`autoretry_for` excludes them).

3. **Acks_late + reject_on_worker_lost.**
   - Long-running tasks should use `acks_late=True, task_reject_on_worker_lost=True` so that if a worker crashes mid-task, Celery requeues the task instead of losing it.
   - For non-idempotent tasks, understand the tradeoff — acks_late means double-execution on crash.

4. **Time limits.**
   - `soft_time_limit` (e.g., 540s) — raises `SoftTimeLimitExceeded` so the task can clean up.
   - `time_limit` (e.g., 600s, 60s higher than soft) — hard kill. Protects the worker process.
   - Match to SLA, not arbitrary defaults.

5. **Result backend hygiene.**
   - `result_expires` set (don't let results pile up forever).
   - Don't store large results in the result backend (use S3/filesystem for artifacts and put only the reference in results).
   - If you don't need the result, use `ignore_result=True`.

6. **Task routing.**
   - Separate queues for different SLAs (e.g., `flows.interactive`, `flows.batch`, `flows.ai_builder`).
   - Workers subscribe only to the queues they should handle. Don't run latency-sensitive tasks next to batch tasks.

7. **Chord / group orchestration.**
   - For multi-step flows, consider whether `celery.chord` or `celery.group` fits better than hand-rolled orchestration.
   - But only if it actually simplifies the code — don't force it.

8. **Heartbeat / watchdog for stuck runs.**
   - If a worker crashes and the task is lost, the flow run stays in "running" forever. Implement a periodic task that scans for runs stuck in "running" for longer than their time_limit and marks them as failed.
   - Or use Celery's `worker_lost` signal to update run state.

9. **Signal handlers.**
   - `task_prerun`, `task_postrun`, `task_failure`, `task_retry`, `task_revoked` — use them to maintain run state machines without polluting task code.

10. **Redispatch safety.**
    - If the user clicks "redispatch" on a queued run, verify the task is not already running. Use a DB-backed lock (`SELECT FOR UPDATE`) or Celery's `apply_async` with a unique `task_id`.

11. **Resource cleanup.**
    - On success AND failure, clean up temporary files, close DB sessions, release locks.
    - Use `finally` blocks, not separate cleanup calls that can be skipped on exception.

12. **Async vs sync.**
    - Celery tasks are sync by default. If your code is async (asyncio), use `asyncio.run()` carefully — never create an event loop inside another one.
    - Consider `celery[asyncio]` or an async wrapper if the async code is deep.

13. **Blocking operations.**
    - No `time.sleep()` in the task body (blocks the worker). If you need to poll, use `self.retry(countdown=N)` instead.
    - No synchronous HTTP calls without a timeout.

14. **Observability.**
    - Every task should log its start/end/failure with a correlation ID (flow_run_id).
    - Metrics: queue depth, task duration (p50/p95/p99), failure rate, retry count.
    - Consider Flower or Celery Events for monitoring.

15. **Prefetch + concurrency.**
    - `worker_prefetch_multiplier` should match task duration. For long tasks, set it to 1 to prevent one worker from holding many unstarted tasks.
    - Concurrency model (prefork vs threads vs eventlet) should match the workload.

**Where to look:**
- `backend/src/intric/flows/runtime/celery_app.py`
- `backend/src/intric/flows/runtime/celery_execution_backend.py`
- All `@app.task` or `@shared_task` decorators in flows
- Celery config (broker, result backend, queues, routes)
- Run state transitions (where does `FlowRun.status` change?)
- The redispatch and cancel endpoints — how do they interact with Celery?

---

### 4.4 Database & Schema

**Goals:** zero N+1 queries on hot paths, proper indexes on foreign keys and query filters, safe migrations, correct transaction boundaries, proper tenant isolation, clean cascade semantics, auditable file storage.

**Specific checks:**

1. **Foreign key indexes.** In PostgreSQL, foreign keys are NOT automatically indexed on the referencing side. Run the inspection query above and verify every FK has a matching index. Missing FK indexes cause slow DELETE cascades and slow joins.

2. **Query patterns and indexes.** Grep for common query filters (`WHERE flow_id=`, `WHERE space_id=`, `WHERE created_at >`) and verify they're backed by indexes. Use `EXPLAIN ANALYZE` on suspected slow queries.

3. **N+1 queries.** Loading a flow with N steps, each step with M bindings, each binding with K attachments — is that 1 query or 1 + N + N*M + N*M*K queries? Use SQLAlchemy `selectinload` / `joinedload` / `contains_eager` as appropriate.

4. **Transaction boundaries.**
   - Creating a flow + its initial steps — is that atomic?
   - Publishing a flow (writing a new version + updating the pointer) — is that atomic?
   - Deleting a flow (and all its runs, versions, steps, bindings) — is that atomic, or can partial deletion happen?
   - Use `async with session.begin()` or equivalent explicit boundaries.

5. **Tenant isolation.** Every SELECT on a flow table must include a tenant_id filter. This should be enforced at the repository layer, not scattered across services. Grep for any `session.execute(select(Flow))` without a tenant filter.

6. **Soft delete vs hard delete.**
   - If flows are hard-deleted, what happens to historical runs, evidence exports, and audit logs that reference them? Orphaned FKs?
   - Consider soft-delete (`deleted_at` column + partial index `WHERE deleted_at IS NULL`) for auditability.

7. **Cascade semantics.**
   - `ON DELETE CASCADE` is convenient but dangerous. Check every cascade relationship and ask: "Is this the behavior we actually want?"
   - Prefer `ON DELETE RESTRICT` for anything audit-worthy (flow versions, run history).

8. **Concurrent updates.**
   - Two users editing the same flow — what happens? Last-write-wins? Optimistic locking with a version column?
   - Flow state transitions (queued → running → completed) — are they guarded against race conditions? Use `SELECT ... FOR UPDATE` or atomic state machine transitions.

9. **File storage.**
   - Where are flow artifacts stored? Local filesystem? S3-compatible? What's the cleanup strategy?
   - If local filesystem: are paths tenant-scoped? Can a user access another tenant's files via path traversal?
   - On run delete, are artifacts deleted too? On failure mid-run, are partial files cleaned up?
   - Are file references in the DB consistent with what's on disk (no dangling references)?

10. **Migration safety.**
    - Any new index should use `CREATE INDEX CONCURRENTLY` (Alembic: `op.create_index(..., postgresql_concurrently=True)`).
    - Any new NOT NULL column on a large table should be added as nullable + default, then backfilled, then set NOT NULL, in separate migrations.
    - Any column rename is risky — consider adding the new column, shadow-writing to both, migrating, then dropping the old.
    - Every migration should have a working downgrade (or explicit rationale for why it's one-way).

11. **JSONB columns.**
    - Are `output_config`, `input_bindings`, `metadata_json` schema-validated at the API boundary, or free-form? Free-form JSONB can drift into garbage over time.
    - Are there indexes on specific keys inside JSONB (e.g., `(metadata_json ->> 'some_key')`) for hot paths?

12. **Schema vs domain drift.**
    - Does the DB schema (Alembic models) match the domain model (Pydantic/dataclasses)? Any fields that are in one but not the other?

**File storage specifically:**
Eneo's flows generate artifacts (PDFs, DOCX, transcriptions, JSON exports). Figure out:
- Where they live (disk path? S3 bucket?)
- Who owns them (tenant? space? user?)
- When they're deleted
- How they're served to the user (signed URL? direct stream?)
- Whether the storage layer is pluggable (so we can switch from local to S3 later without a rewrite)

---

### 4.5 API Consumer Perspective

**Scenario to play out:**
A developer at a Swedish municipality is building a transcription-and-summary web app. They will:
1. Authenticate to Eneo's API with an API key.
2. Create a flow (via UI, then reference it by ID from the app).
3. Run the flow programmatically by POSTing an audio file.
4. Poll for the result (or receive a webhook).
5. Download the final PDF/DOCX.

**Questions the reviewer must answer:**

1. **Discoverability.** Can this developer figure out which endpoint to call from the OpenAPI schema alone, or do they need tribal knowledge? Is the generated OpenAPI accurate?
2. **Error messages.** If they POST invalid input, does the error say exactly what's wrong ("missing field 'file' in step_1 inputs") or is it generic ("validation error")?
3. **HTTP semantics.**
   - 200 for success, 201 for "created" (POST), 202 for "accepted, processing async"
   - 400 for bad request, 401 for no auth, 403 for wrong user, 404 for not found, 409 for conflict, 422 for validation error
   - Audit every endpoint's status codes
4. **Idempotency.** Can the client safely retry `POST /flows/{id}/runs` if they didn't receive a response? Use an `Idempotency-Key` header or a client-supplied UUID.
5. **Long-running operations.** For a flow that takes 60s to run, does the API:
   - Return 202 immediately with a run_id to poll?
   - Support webhooks / Server-Sent Events for completion?
   - Let the client stream updates?
6. **Pagination.** `GET /flows`, `GET /flows/{id}/runs` — are they paginated? Cursor or offset? Is the ordering stable?
7. **Rate limiting.** Is there a rate limit? Is it documented? What status code / header does the client receive when throttled?
8. **API versioning.** How are breaking changes communicated? Is there a deprecation policy?
9. **Schema contract stability.** If the reviewer touches a response shape, does that break any existing consumer?

**What to produce:**
- A list of endpoints with their current HTTP status codes and error shapes
- A "developer experience" score for the top 5 flows API endpoints
- Specific improvements (rewrite error messages, add idempotency header support, add webhook hook, etc.) ranked by ROI

---

### 4.6 Clean Architecture, Maintainability & Code Quality

**Structural:**
- **Layer separation.** Domain (models, rules) → Application (services, use cases) → Infrastructure (DB, HTTP, Celery). Does the code respect this, or does the domain import SQLAlchemy / FastAPI?
- **Dependency injection.** Are services constructed via DI or instantiated inline?
- **Pure vs impure functions.** Are flow validation rules pure functions that can be unit tested without a DB or a Celery broker?
- **Abstraction leaks.** Does the API layer reach into the database directly? Does the domain know about HTTP?
- **God objects.** Any class that cannot be described by a single invariant or responsibility — regardless of its size. A huge class that cleanly maintains one invariant is fine; a small class that does five unrelated things is not.
- **Tangled files.** A file is "too big" when it has multiple unrelated concerns that change for different reasons, not when it has many lines. Judge by cohesion, not by `wc -l`.

**Maintainability (first-class concern, judgment-based, not checklist-driven):**

Maintainability is about **future change cost**: if the next developer (or future-you) had to fix a bug or add a feature in this code next week, would the current structure help or fight them? That's the only question that matters. Every proposed maintainability fix must be measured against that question — not against a line-count rule, not against a metric, not against "best practices" from a blog.

**The core rule:** code is too big, too complex, or too coupled **when it is demonstrably slowing future change**. Not when a metric exceeds a threshold. Metrics are weak signals that point you to candidates for investigation — they are never conclusions on their own.

**Anti-heuristics (things that look like maintainability improvements but aren't):**

- "This file is 1,200 lines, split it." A 1,200-line file with one cohesive domain model and its methods is often the clearest expression of that model. Splitting it into 5 files so each is under 300 lines can scatter the model across the filesystem and force readers to jump around. Line count is a *hint*, not a verdict.
- "This function is 70 lines, extract helpers." A 70-line function that linearly executes a state machine with clear comments is more readable than 6 tiny functions that pass state between themselves. Extraction creates indirection; indirection has a cost.
- "This switch statement has 8 branches, use a strategy pattern." A flat switch on an enum is usually readable. Replacing it with class hierarchies hides the dispatch in polymorphism and makes the overall control flow harder to follow.
- "These two 20-line blocks look similar, DRY them." If they represent the *same concept*, yes. If they look similar today but model different domains that will diverge, forcing shared code creates future coupling pain. The "Rule of Three" exists for a reason.
- "This code has no docstrings, add them." A mandated docstring on `get_flow()` that says `"""Get the flow."""` is noise. Docstrings should exist where they explain intent, invariants, or non-obvious behavior — not to hit a coverage number.
- "These variable names are inconsistent, rename them." Mass renaming in stable code has a real cost (broken cherry-picks, invalidated IDE history, risk of missing dynamic references) and marginal benefit. Fix genuinely wrong names; don't batch-rename for uniformity.

**Signals that DO warrant investigation:**

1. **Multiple unrelated concerns in one file.** A file is too big when it has multiple things that change for different reasons. Ask: "if I had to fix a bug in concept X, would I be reading through unrelated concept Y just to find it?" If yes, consider splitting by concept (not by line count).

2. **Mixed abstraction levels within a function.** A function that does high-level orchestration and low-level string manipulation in the same body is harder to read than one that stays at a consistent level. This is a stronger signal than raw length.

3. **Nested conditional depth.** Three or more levels of nested `if`/`for`/`while` typically means the logic is trying to do too much in one place. Flat switches are fine; deep nesting is not.

4. **Shotgun surgery risk.** A change to concept X forces edits in 8 different files. This usually means concept X is spread across modules that should be unified, or a cross-cutting concern (e.g., audit logging) is being re-implemented in every site instead of centralized.

5. **Feature envy.** A method in class A repeatedly reaches into class B's data. The method likely belongs in B. This is a strong, testable signal.

6. **God objects / fat services.** A service where you can't articulate "what invariant does this class maintain?" in one sentence. The service is doing too many things. But beware: splitting a god object is risky — callers depend on its current surface. Plan the split carefully.

7. **Low cohesion within a module.** Five classes in a file that don't share domain vocabulary or concerns — they were put together for convenience, not design. Group by domain concept instead.

8. **Layer violations.** Domain code that imports SQLAlchemy or FastAPI. API code that talks directly to the database without going through a service. These are real defects that cause coupling pain.

9. **Duplicated concept, divergent implementation.** Two functions that do nearly the same thing differently. If the bug-fixer patches one but not the other, the divergence causes a future defect. This IS worth unifying — but only if the two uses really represent the same concept.

10. **Dead code you can *prove* is dead.** Unused imports (pyright/ruff find these). Unreachable branches (static analysis finds these). Private functions with no callers in the codebase. But before deleting a public function or an endpoint: check for dynamic references (grep the string name), check external API consumers, check test fixtures, check git history to see why it was added. A "dead" endpoint that a third-party app calls is a production incident.

11. **Tests that are hard to read or hard to maintain.** This is often a symptom of code that is hard to test — which is a symptom of tight coupling. The fix is usually in the production code, not the tests.

12. **Invariants that aren't expressed.** Code where "you just have to know" that field X must always be set before field Y, or that this function must be called after that function. Either encode the invariant in types, or document it clearly, or refactor so the invariant can't be violated.

**How to use these signals:**

For each signal that fires, you must answer three questions before proposing a fix:

1. **What concrete future change does this make harder?** (If you can't name a scenario, skip it.)
2. **What's the fix's own risk?** (Will splitting this file break cherry-picks? Will extracting this function cause a subtle behavior change?)
3. **Is the cost of the fix lower than the cost of leaving it alone, over the next ~6 months?** (If the file is stable and nobody touches it, the answer is often no.)

Only fixes that pass all three questions go into the findings report.

**Things NOT to include in the maintainability review:**

- Line-count thresholds as hard failures
- "Every function must have a docstring" rules
- Mass renames in stable files
- Refactors to introduce abstractions for "future flexibility" (YAGNI)
- Style-only cleanups (unless you're already touching the file for a real fix)
- Replacing clear-but-verbose code with clever-but-cryptic code
- Splitting files just because they're "too big" by some metric

**Type safety (pyright strict):**
- No `Any` except at system boundaries (HTTP request/response, JSON parse).
- No `# type: ignore` without a comment explaining why.
- No `Optional[X]` that should be `X` with a default.
- Generic types preferred over `dict[str, Any]`.
- `TypedDict` or Pydantic for structured data.

**Error handling:**
- Domain errors (validation failures) are custom exception types, not generic `Exception`.
- API layer catches domain exceptions and translates to HTTP errors.
- No bare `except:` or `except Exception: pass`.
- Exceptions are logged with context (flow_id, user_id, correlation_id).

**PEP8 / Python style:**
- Line length consistent (likely 100 or 120 per this project's config — check `pyproject.toml`).
- Imports sorted (isort) and grouped (stdlib / third-party / first-party).
- Function and class names follow conventions.
- Docstrings on public functions (Google or NumPy style).

**Time complexity:**
- Any O(n²) loop on user-controllable data? (e.g., matching step outputs to step inputs — if there are 20 steps and 50 variables per step, is this linear or quadratic?)
- Any repeated computation that could be memoized? (e.g., re-parsing a JSON string on every step access)
- Any eager loading of all runs when only the latest is needed?

**Dead code:**
- Unused imports
- Unreachable branches
- Functions that are never called
- Fields that are never read

---

### 4.7 Tests

**Coverage to verify:**
- Every permission check has a test that covers allow and deny.
- Every classification rule has a test (write-down denial, write-up allowance).
- Every Celery task has a test that covers success, retry, hard failure.
- Every state transition (queued → running, running → completed, running → failed, queued → cancelled) has a test.
- Every API endpoint has at least one happy-path and one error-path test.

**Test types:**
- **Unit tests:** Mock the DB with `AsyncMock`, test pure domain logic.
- **Integration tests:** Real PostgreSQL via testcontainers, real Celery broker (Redis testcontainer), end-to-end flow creation and execution.
- **No test should be flaky.** If it is, fix the flakiness or quarantine with clear reasoning.

**How to run:**
```bash
# Flow-specific tests
docker exec -w /workspace/backend eneo-41ae93-eneo-1 bash -c \
  "export PATH=/home/vscode/.local/bin:\$PATH && uv run pytest tests/flows -x -n 5 -v"

# AI builder tests
docker exec -w /workspace/backend eneo-41ae93-eneo-1 bash -c \
  "export PATH=/home/vscode/.local/bin:\$PATH && uv run pytest tests/flows/ai_builder -x -n 5 -v"

# Full suite (when done with all changes)
docker exec -w /workspace/backend eneo-41ae93-eneo-1 bash -c \
  "export PATH=/home/vscode/.local/bin:\$PATH && uv run pytest tests/ -x -n 5"
```

---

## 5. Quality Gates

Every fix, before being committed, MUST pass all of these:

1. **Pyright strict on changed files** — zero new errors.
2. **Tests pass** — `pytest tests/flows -x -n 5` (or a narrower subset if you know what you touched).
3. **New behavior has new tests.** Don't claim a fix works without a regression test.
4. **No false positives.** Each finding must include: "why this matters" (concrete scenario, severity) and "what could break if we fix it wrong" (risk assessment).
5. **ROI justified.** Each fix must articulate impact (severity × likelihood) vs cost (LOC changed × risk of regression).
6. **Backwards compatible.** No API schema changes without an explicit plan and user confirmation. Existing callers must continue to work.
7. **Migration safe.** Alembic migrations must run on a live DB — use `CREATE INDEX CONCURRENTLY`, avoid long locks, make changes reversible.
8. **Audit logged.** Any new sensitive action has an audit log entry (actor, action, subject, timestamp).
9. **One concern per commit.** Don't mix a permission fix with a code-style cleanup.
10. **Maintainability neutral or positive.** A fix must not make the code harder to understand, modify, or test. Concretely, after the fix:
    - The changed code should be at least as easy to read and reason about as before. If you add complexity, it must buy correctness or safety that is worth the cost.
    - New code should use the same domain vocabulary as the surrounding code — don't introduce new synonyms for existing concepts.
    - New abstractions must be justified by concrete, current needs. No "future flexibility" layers, no speculative interfaces, no hooks for features nobody asked for.
    - If a file or function is already hard to change because of tangled concerns, and your fix touches it, leave it at least a little cleaner than you found it — but only for the parts you're already changing, not the whole file.
    - Do not split files, extract functions, or rename things just to hit a metric. Only do it when the current shape is demonstrably making this specific fix harder.

## 6. Safety Rules

1. **Read first, write second.** Never modify code you haven't read. Never refactor a function without checking all callers.
2. **Never skip hooks (`--no-verify`)** or force-push, unless explicitly requested.
3. **Never `git reset --hard`** or other destructive git operations without confirming with the user.
4. **Never modify out-of-scope files.** If a fix requires touching another module, STOP and ask.
5. **Run tests after every logical change**, not at the end.
6. **If something looks wrong but out of scope, note it — don't fix it.**
7. **When in doubt, prefer the verbose/explicit/safe fix** over the clever one-liner.
8. **Database migrations are (effectively) irreversible in production.** Test locally. Write reversible downgrade. Think about live data.
9. **Don't break API contracts.** If a response shape changes, the old fields must still exist or the change must be explicitly approved.
10. **If a test is flaky, fix the flakiness** — don't retry until it passes.

## 7. Deliverables

### After planning (ralplan phase):
1. **Findings report** in `docs/reviews/flows-comprehensive-review-findings.md`, grouped by the 7 dimensions, each finding tagged P0/P1/P2/P3 with:
   - Short title
   - Affected files
   - Why it matters (concrete scenario)
   - Pros of fixing
   - Cons / risks of fixing wrong
   - Test plan for the fix
   - Estimated effort (S / M / L)
   - ROI score (see below)
2. **Prioritized action list** — top 10 items by ROI, in order.
3. **Maintainability sub-report** (appendix to the findings report). This is a **judgment report**, not a metrics dump. Only include items where you can name a concrete future change that the current shape makes harder, and where the fix's own risk is lower than leaving it alone. For each item:
   - Name the problem (e.g., "classification enforcement is spread across four files; adding a new classification level forces edits in all of them")
   - Name a concrete scenario it makes harder ("add a new k4 level", "add a new MCP tool classification", "trace why a specific step failed classification")
   - Propose a specific, minimal fix (not "refactor the module" — say what gets moved where)
   - State the fix's own risk (what could break, who might depend on the current shape)
   - Estimate effort (S / M / L) and ROI

   Topics to look for (only include if they meet the bar above):
   - **Files with tangled concerns.** Files where multiple unrelated things live together and changes to one regularly force rereading the rest.
   - **Functions that mix abstraction levels.** Orchestration and low-level detail in the same body, making it hard to follow the high-level flow.
   - **God objects / fat services.** Classes where you cannot articulate a single invariant they maintain.
   - **Feature envy.** Methods that reach into another class's internals repeatedly — usually belong in the other class.
   - **Shotgun surgery risks.** Changes to concept X that force edits in many unrelated files.
   - **Layer violations.** Domain code importing infrastructure, API code talking directly to the DB, etc.
   - **Duplicated concepts with divergent implementations.** Code that does the same thing differently in multiple places, where a bug-fix will likely be applied to only one.
   - **Provably dead code.** Unused imports, unreachable branches, private functions with zero callers, commented-out blocks — after verifying no dynamic references or external consumers.
   - **Unexpressed invariants.** "You just have to know" rules that should be in types, guards, or clear documentation.
   - **Tests that are hard to read.** Usually a symptom of hard-to-test production code; note the root cause.

   **Explicitly NOT in this report:**
   - "File X has N lines" observations without a concrete problem
   - "Function Y is long" observations without a concrete extraction
   - Style nits in files you are not otherwise changing
   - Mass rename proposals
   - Speculative abstractions for "future flexibility"
   - Replacing clear-and-verbose with clever-and-cryptic
4. **Scope confirmation** — a list of things that looked suspicious but were out of scope, as a follow-up list.

### After execution (ralph phase):
For each action item, a commit that:
1. Applies the smallest possible diff
2. Adds or updates tests covering the new behavior
3. Passes pyright strict on the changed files
4. Passes the test suite
5. Includes a commit message with: the problem, the fix, the trade-offs considered, the tests added

Plus a final summary at the end: what was fixed, what was deferred, what new issues were discovered.

## 8. ROI Framework

For each finding, score:
- **Severity (1-5):** How bad is the consequence if this breaks?
  - 1 = minor UX annoyance
  - 3 = data integrity at risk or silent permission bypass
  - 5 = production outage, data loss, or security breach
- **Likelihood (1-5):** How often will this be hit in production?
  - 1 = rare edge case
  - 3 = common usage
  - 5 = every request
- **Cost (1-5, lower = cheaper):** How much work to fix?
  - 1 = few lines, low risk
  - 3 = one module, moderate risk
  - 5 = cross-cutting change, high risk
- **Fix risk (1-5, lower = safer):** How likely is the fix to introduce new bugs?
  - 1 = trivial, well-tested
  - 3 = touches hot paths, needs careful review
  - 5 = could break backwards compat or data migration

**ROI = (Severity × Likelihood) / (Cost × Fix risk)**

Sort findings by ROI descending. Items with ROI < 1 are logged but not fixed in this pass. Items with ROI ≥ 2 are the priority queue.

## 9. Known Starting Points

You do not need to search blindly. Here are the most likely hot spots to investigate first:

- `backend/src/intric/flows/flow_permissions.py` — permission check core
- `backend/src/intric/flows/flow_service.py` — the main service orchestrating flow operations
- `backend/src/intric/flows/flow_repo.py` — repository for CRUD on flows
- `backend/src/intric/flows/flow_run_repo.py` — runs repo
- `backend/src/intric/flows/flow_run_service.py` — run lifecycle
- `backend/src/intric/flows/flow_dispatch.py` — dispatch layer
- `backend/src/intric/flows/application/flow_dispatch.py` — newer application layer
- `backend/src/intric/flows/runtime/celery_app.py` — Celery config
- `backend/src/intric/flows/runtime/celery_execution_backend.py` — Celery task definitions
- `backend/src/intric/flows/runtime/claim_resolution.py` — run claim locking (look here for stuck-task handling)
- `backend/src/intric/flows/api/flow_router.py` — main API surface
- `backend/src/intric/flows/api/flow_run_router.py` — run API surface
- `backend/src/intric/flows/api/flow_definition_access.py` — likely where permission guards live
- `backend/src/intric/flows/ai_builder/ai_builder_validator.py` — AI builder validation
- `backend/src/intric/flows/ai_builder/ai_builder_plan_store.py` — AI builder session storage
- `backend/alembic/versions/*flow*.py` — all flow-related migrations

After triaging these, follow the call graph outward.

## 10. Non-goals

- Do NOT rewrite the whole flows module from scratch.
- Do NOT switch from Celery to another worker — stick with Celery.
- Do NOT invent new abstractions unless they pay for themselves in maintainability within this PR.
- Do NOT touch frontend code unless forced by a backend API contract change.
- Do NOT expand the scope to other subsystems.
- Do NOT fix style-only nits in untouched files.

---

## Final note on tone and rigor

This is a high-stakes review. The audience is Swedish municipalities running AI on sensitive public-sector data. The bar is:

- **Every finding must be real** — no "looks funny to me" without a concrete scenario.
- **Every fix must be justified** — show the math: ROI, pros, cons, risk.
- **Every change must be verified** — tests pass, types pass, behavior is preserved.
- **When in doubt, ask.** Silent scope expansion is worse than stopping to ask.
- **Prefer boring over clever.** This code will be maintained by other humans under deadline pressure.

Proceed carefully, verify often, and keep the diff small.
