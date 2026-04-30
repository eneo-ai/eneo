# Batch 3 - Lifecycle Terminalization Audit Journal

## Status

READY_FOR_COMMIT_BOUNDARY - implementation, retrospective, validation, and
Claude verification are complete.

## Iteration Log

### Iteration 1

- Start gate:
  - `git log --oneline --max-count=5` shows Batch 2 latest:
    `39b8652b flows: define access and published definition contracts`.
  - `git status --short` contains only known unrelated dirty files:
    `frontend/packages/ui/src/icons/types.d.ts`,
    `scripts/run_codex_review.sh`, and `PRODUCT.md`.
  - `git diff --cached --name-only` is empty.
- Plan: `docs/refactor/execution/batch-3-lifecycle-terminalization-audit/plan.md`.
- Docker pre-check:
  - Command attempted: `docker ps --format '{{.Names}}'`.
  - Result: blocked by host approval policy before execution:
    `approval required by policy, but AskForApproval is set to Never`.
  - Validation mode for this Codex environment is therefore local fallback
    unless a later command becomes available.
- Alembic head inspection:
  - `cd backend && uv run alembic heads` returned
    `20260426_drop_step_mcp_tools (head)`.
  - If Batch 3 adds the planned outbox migration, that head is the
    expected `down_revision` unless another migration lands first.
- Claude plan review:
  - Artifact:
    `.codex/artifacts/claude-peer-loop-batch-3-lifecycle-terminalization-audit-plan-20260430T063406Z.md`
  - Result: `GREEN_LIGHT: no`, `VERDICT: changes_required`, minimum score `6`.
  - Reconciliation:
    `docs/refactor/execution/batch-3-lifecycle-terminalization-audit/claude-plan-reconciliation.md`.
  - Outcome: accepted concrete plan findings before implementation.
    The plan now has the complete terminal call-site inventory, deletes
    old direct terminal helpers and ARQ-backed terminal audit, uses
    `enums.py` for status predicates and terminal source enums, pins
    outbox uniqueness as `UNIQUE (flow_run_id)`, removes premature
    delivery columns, and records FK/delete behavior.
- Claude plan verification:
  - Artifact:
    `.codex/artifacts/claude-peer-loop-batch-3-lifecycle-terminalization-audit-plan-verification-20260430T063932Z.md`
  - Result: `GREEN_LIGHT: yes`, `VERDICT: green`, minimum score `8`.
  - Non-blocking polish applied after verification: plan now states that
  outbox `description` is deterministic from `(action, source)` and
  that terminalization uses a strict queued/running CAS with
  already-terminal no-op handling.
- Implementation summary:
  - Added canonical run status predicates and closed terminal source enum in
    `backend/src/intric/flows/enums.py`.
  - Added `flow_run_audit_outbox` SQLAlchemy model and migration.
  - Added `FlowRunTerminalizer` as the application owner for terminal
    transitions, step-result/attempt closure, and terminal outbox insert.
  - Retargeted executor, dispatch, service cancellation/reconciliation, and
    Celery failure paths to terminalization.
  - Deleted direct repository terminal helpers and executor/task terminal
    audit/status helpers after behavior pins existed.
- Validation:
  - Raw log: `validation-1.log`.
  - `cd backend && uv run alembic heads`: pass,
    `20260430_flow_run_audit_outbox (head)`.
  - Targeted pyright: pass, `0 errors, 0 warnings, 0 informations`.
  - Targeted pytest: failed, `1 failed, 175 passed, 18 warnings`.
  - Failure:
    `tests/unittests/flows/test_flow_executor_runtime.py::test_webhook_failure_logs_exception_context`
    asserted through `caplog`; combined runtime logging setup made that
    implementation-detail assertion order-dependent.
- Retrospective:
  - `retrospective-1.md` is RED because a planned behavior-pin validation
    command failed.
- Focused fix:
  - Replaced the order-dependent `caplog` check with a direct assertion
    against the executor logger's `exception` call, keeping the test focused on
    the webhook failure log contract.

### Iteration 2

- Focused validation after the webhook-log test fix:
  - Raw log: `validation-2.log`.
  - `cd backend && uv run alembic heads`: pass,
    `20260430_flow_run_audit_outbox (head)`.
  - Targeted pyright: pass, `0 errors, 0 warnings, 0 informations`.
  - Targeted pytest: pass, `176 passed, 18 warnings`.
  - `git diff --check`: pass.
  - Terminal call-site/source guard: pass; remaining hits are enum values,
    terminalizer-owned transitions, terminalizer callers, and non-transition
    string result payloads.
  - `cd backend && uv run lint-imports --no-cache`: pass, `Contracts: 3 kept,
    0 broken`.
  - Touched-file ruff: pass.
  - Broad Flow ruff check: failed with 5 pre-existing import-order issues in
    untouched files:
    `src/intric/flows/api/flow_run_steps_router.py`,
    `src/intric/flows/flow_factory.py`,
    `src/intric/flows/flow_validators_form.py`,
    `src/intric/flows/http_transport/__init__.py`, and
    `src/intric/flows/runtime/claim_resolution.py`.
  - Extra typed-IO executor suite: failed one PDF render test because the local
    macOS environment lacks WeasyPrint native library `libgobject-2.0-0`;
    `57 passed, 1 failed, 2 warnings`. This is an environment issue, not a
    Batch 3 product regression.
- Standards polish after reviewing the retrospective checklist:
  - Replaced fresh `dict[str, Any]` terminal payload annotations with the
    existing Flow `JsonObject` alias in the new terminalization boundary.
- Latest validation after standards polish:
  - Raw log: `validation-3.log`.
  - `cd backend && uv run alembic heads`: pass,
    `20260430_flow_run_audit_outbox (head)`.
  - Targeted pyright: pass, `0 errors, 0 warnings, 0 informations`.
  - Targeted pytest: pass, `176 passed, 18 warnings`.
  - `git diff --check`: pass.
  - Terminal call-site/source guard: pass with the expected classified hits.
  - `cd backend && uv run lint-imports --no-cache`: pass, `Contracts: 3 kept,
    0 broken`.
  - Broad Flow ruff check still reports the same 5 untouched import-order
    issues listed above; touched-file ruff passes.

### Iteration 3

- Claude implementation review:
  - Artifact:
    `.codex/artifacts/claude-peer-loop-batch-3-lifecycle-terminalization-audit-implementation-20260430T074605Z.md`
  - Raw response:
    `docs/refactor/execution/batch-3-lifecycle-terminalization-audit/claude-attack-2.md`.
  - Result: `GREEN_LIGHT: no`, `VERDICT: changes_required`, minimum score `6`.
  - Reconciliation:
    `docs/refactor/execution/batch-3-lifecycle-terminalization-audit/claude-reconciliation-2.md`.
- Accepted/partial findings fixed:
  - Removed the cancel endpoint's duplicate ARQ-backed
    `FLOW_RUN_CANCELLED` lifecycle audit and added a router unit pin that
    cancel delegates to the service without calling `audit_service.log_async`.
  - Added a database CHECK so outbox `description` must equal
    `action || ':' || source`, preserving the planned deterministic column
    while preventing free-form drift.
  - Added `terminalize_stale_running_run` so reconciler-only `stale_before`
    does not live on the normal terminalization command surface.
  - Added cross-run integration coverage proving terminalizing one run does
    not close another run's active results or attempts.
  - Replaced `MethodType` audit-outbox failure patching with `AsyncMock`.
  - Added a warning for SYSTEM actor fallback in terminal audit actor
    resolution.
  - Removed the redundant single-column `flow_run_id` FK from the outbox
    migration/model while keeping composite run+tenant and run+flow FKs.
- Validation after first fix pass:
  - Raw log: `validation-4.log`.
  - Result: RED.
  - Targeted pyright failed because the attempted underscored repository
    methods triggered `reportPrivateUsage` from the terminalizer.
  - Full `test_flow_router.py` execution surfaced 7 unrelated router-test
    failures; the Batch 3 cancel behavior pin should be run as a targeted test,
    not by treating the whole existing router unit file as part of Batch 3
    validation.
  - Focused correction: restored public repository method names and kept the
    repository-method encapsulation finding as a documented rejected
    trade-off; targeted cancel pin is included in latest validation.
- Latest validation after focused correction:
  - Raw log: `validation-5.log`.
  - `cd backend && uv run alembic heads`: pass,
    `20260430_flow_run_audit_outbox (head)`.
  - Targeted pyright including the cancel router/test: pass, `0 errors,
    0 warnings, 0 informations`.
  - Targeted pytest including the cancel router pin: pass, `177 passed,
    18 warnings`.
  - `git diff --check`: pass.
  - Terminal lifecycle source guard: pass with expected classified hits only;
    no cancel endpoint `FLOW_RUN_CANCELLED` ARQ lifecycle audit remains.
  - `cd backend && uv run lint-imports --no-cache`: pass, `Contracts: 3 kept,
    0 broken`.
  - Touched-file ruff: pass.
  - `retrospective-3.md` is GREEN.
- Claude verification:
  - Artifact:
    `.codex/artifacts/claude-peer-loop-batch-3-lifecycle-terminalization-audit-verification-20260430T075943Z.md`
  - Raw response:
    `docs/refactor/execution/batch-3-lifecycle-terminalization-audit/claude-attack-3.md`.
  - Reconciliation:
    `docs/refactor/execution/batch-3-lifecycle-terminalization-audit/claude-reconciliation-3.md`.
  - Result: `GREEN_LIGHT: yes`, `VERDICT: green`, minimum score `8`.
  - Outcome: no accepted or partial findings remain for Batch 3. Claude listed
    non-gating follow-ups for per-run reconciler transaction boundaries,
    source-guard CI hardening, and operator visibility of the actor fallback
    warning.

## Input Checkpoints

- Batch 0 source/test checkpoint:
  `d6a9365e477b83651d94566f58a9a7e13d0b9363`
- Post-Batch-0 governance/docs checkpoints:
  - `88cfc4016aa4c5b69506bee5f8b887a1f70a47c1`
  - `8f21fd4f9ca745df8bd0761923350e2f304640ed`
  - `ad472c61bf34b3a5ced13198e141c78c693e5bc0`
- Batch 1 source/test/docs checkpoint:
  `61c17ed712e245eb25c2f124f334c6c9cbc42413`
- Batch 2 source/test/docs checkpoint:
  `39b8652bc2e8d2db8095626494b67a55e1e84207`

## Batch 2 Carry-Forward Risks Consumed By This Batch

- Runtime worker contract still executes `FlowRunExecutor` directly
  instead of the Celery task wrapper. Batch 3 will add a Celery wrapper
  behavior pin where fixture cost is reasonable.
- Runtime worker contract imports private
  `_enable_autobegin_for_flow_task_session`. Batch 3 will expose a public
  test helper/fixture or document the remaining gap.
- Docker validation remains blocked in this Codex app environment by
  host approval policy. Batch 3 records this and uses local fallback.
- Future runtime tables are documented but not implemented. Batch 3 will
  implement only the Flow lifecycle audit outbox table required for
  terminalization, not file/rerun/review tables.

## Initial Source Evidence

- `backend/src/intric/flows/enums.py:64` defines run statuses but no
  lifecycle predicate owner.
- `backend/src/intric/flows/infrastructure/flow_run_repo.py:40` defines
  active statuses locally.
- `backend/src/intric/flows/application/flow_run_service.py:91` and
  `backend/src/intric/flows/runtime/executor.py:240` duplicate terminal
  status sets.
- `backend/src/intric/flows/infrastructure/flow_run_repo.py:268`
  directly fails stale running runs without closing attempts or durable
  lifecycle audit.
- `backend/src/intric/flows/infrastructure/flow_run_repo.py:483` closes
  pending/running step results only as cancelled.
- `backend/src/intric/flows/infrastructure/flow_run_repo.py:552` can
  finish one attempt but has no run-scoped open-attempt closure.
- `backend/src/intric/flows/runtime/tasks.py:151` manually marks task
  failures failed through repository methods.
- `backend/src/intric/flows/runtime/tasks.py:322` stale-running
  reconciliation manually marks pending steps cancelled and fails the run.
- `backend/src/intric/flows/runtime/executor.py:717` performs normal
  completion/failure terminal updates directly.
- `backend/src/intric/flows/runtime/executor.py:1071` audits terminal
  state through `audit_service.log_async`.
- `backend/src/intric/audit/application/audit_service.py:234` enqueues
  audit through ARQ Redis, which is not the durable Flow lifecycle audit
  mechanism required by PRD-003/PRD-009.

## Carry-Forward Risks

- Docker validation is blocked in this Codex app environment by host approval
  policy before `docker ps` can execute. Local fallback validation is used for
  this batch.
- Broad `ruff check src/intric/flows ...` still reports 5 untouched import-order
  issues outside the Batch 3 diff. Touched-file ruff passes; do not auto-fix
  the broad import-order baseline inside this lifecycle batch.
- Local `tests/unittests/flows/test_typed_io_executor.py` still depends on
  WeasyPrint native library `libgobject-2.0-0` for the PDF render parameter.
  The failure is environmental in this host fallback mode.
- The all-tenant stale reconciler currently terminalizes multiple runs inside
  one session scope. Claude accepted this for Batch 3 but recommends
  considering per-run transaction boundaries before Batch 10 observability and
  runtime health work expands the reconciler.
- Repository terminal SQL primitives remain public repository methods because
  strict pyright rejected cross-class private usage and a second private
  repository would add ceremony. The source guard in validation remains the
  current anti-slippage proof for direct terminal status writes.
- Consider promoting the terminal-source guard into a durable local gate or CI
  check if future batches keep relying on it.
- Confirm operator-visible logging for
  `flow_run_terminalization.audit_actor_fallback` during observability work.
- Batch 4 is not blocked by Batch 3 source/test changes. Claude verification
  returned green with no accepted or partial findings.
