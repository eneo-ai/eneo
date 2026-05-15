# T098 Manual Crawl Terminal Ownership Scout

## Problem

Manual crawl enqueue failures still write terminal state through `JobService.fail_job(...)` while worker/scheduler paths use `TerminalEvent` plus `commit_terminal(...)`. This keeps a second terminal-write path alive and means manual-trigger failures can miss typed `CrawlOutcomeCode` state.

## Direct Failure Inventory

| Site | Current behavior | Risk |
|---|---|---|
| `backend/src/intric/websites/domain/crawl_service.py:204-228` | `PendingQueue.add(...)` raises `PendingQueueAddError`; `CrawlService` calls `self.task_service.job_service.fail_job(job_id, error_message=f"Failed to queue: {exc}")` and re-raises. | Job gets failed string detail, but `CrawlRuns.outcome_code` is not set to `CRAWL_QUEUE_ENQUEUE_FAILED`. UI/admin outcome parity differs from scheduled enqueue failures. |
| `backend/src/intric/websites/domain/crawl_service.py:304-335` | Direct ARQ enqueue or pre-acquired flag handoff fails; code deletes the flag, releases the slot, then calls `JobService.fail_job(..., f"Enqueue failed: {exc}")`. | Same typed outcome gap; additionally this path has an ordering invariant: release/delete slot resources before terminal failure commit. |

No other `task_service.job_service.fail_job(...)` call sites exist in `crawl_service.py`.

## Session / UoW Evidence

- `CrawlService.__init__` accepts only `CrawlRunRepository`, `TaskService`, and Redis client (`backend/src/intric/websites/domain/crawl_service.py:51-61`). It does not explicitly accept `AsyncSession` or a unit-of-work object.
- `commit_terminal(...)` currently requires an `AsyncSession` (`backend/src/intric/worker/crawl/terminal.py:76-79`).
- `CrawlRunRepository` stores the active session as `self.session` (`backend/src/intric/websites/domain/crawl_run_repo.py:60-63`), and `JobRepository` stores it through `BaseRepositoryDelegate.session` (`backend/src/intric/jobs/job_repo.py:13-21`). So manual crawl paths run inside a session-backed object graph today, but `CrawlService` should not reach through repository internals as an implicit UoW.
- Request containers use `get_session_with_transaction` by default (`backend/src/intric/server/dependencies/container.py:35-53`), so manual website endpoints run under one transaction-scoped container.
- Worker batch queueing also uses session scopes before calling crawl services in fallback/direct mode (`backend/src/intric/worker/crawl_tasks.py:515-518`, `backend/src/intric/main/container/container.py:1423-1458`).

## Ownership Decision

`TerminalEvent` is not worker-specific anymore. It describes durable crawl/job terminal state for any crawl trigger path. The current home, `backend/src/intric/worker/crawl/terminal.py`, is now too narrow because manual `CrawlService` would need to import worker internals to use the canonical terminal writer.

Recommended canonical home:

- Move `ACTIVE_TERMINAL_JOB_STATUSES`, `TerminalEvent`, `TerminalBatchEvent`, `CrawlRunTerminalUpdate`, `TerminalCommitResult`, `commit_terminal(...)`, and `commit_terminal_batch(...)` to a website-owned persistence boundary, tentatively `backend/src/intric/websites/domain/crawl_terminal.py`.
- Update `worker/crawl/__init__.py` to re-export the moved names from `intric.websites.domain.crawl_terminal` for existing worker callers. New manual code should import from the canonical website path.
- Delete `backend/src/intric/worker/crawl/terminal.py` in the relocation slice. Do not leave a compatibility shim; the package-level re-export is enough for worker convenience and avoids dual implementation homes.
- Do not create an interface or factory. There is one implementation and one persistence operation.

Why this is better than injecting `AsyncSession` into `CrawlService` directly:

- It fixes the import direction before manual parity, instead of deepening `websites.domain -> worker.crawl`.
- It keeps one terminal commit implementation for worker, watchdog, scheduler, and manual paths.
- It avoids teaching `CrawlService` to reach into `repo.session`, which would hide transaction ownership behind repository internals.
- It accepts the repo's current layering reality: website domain repository modules already perform SQL persistence, and a crawl terminal commit is a coupled `CrawlRuns`/`Jobs` invariant.

## Proposed Next Worker

### T099 Terminal Ownership Relocation

Behavior-preserving precursor:

- Move the terminal event dataclasses and commit functions from `intric.worker.crawl.terminal` to `intric.websites.domain.crawl_terminal`.
- Update production and test imports to the new canonical module where practical.
- Keep `intric.worker.crawl.__init__` re-exporting the names from `intric.websites.domain.crawl_terminal` so existing worker package imports remain stable.
- Delete the old `intric.worker.crawl.terminal` implementation file in the same slice.

Red-test plan:

- Import test fails before the move: `from intric.websites.domain.crawl_terminal import ACTIVE_TERMINAL_JOB_STATUSES, TerminalEvent, TerminalBatchEvent, CrawlRunTerminalUpdate, TerminalCommitResult, commit_terminal, commit_terminal_batch`.
- Worker package re-export test must stay green after the move: `from intric.worker.crawl import TerminalEvent, commit_terminal`.
- Existing `test_crawl_terminal.py` must keep proving job and crawl-run terminal row behavior.

Verification:

- `cd backend && uv run pytest tests/unittests/worker/test_crawl_terminal.py -q`
- `cd backend && uv run pytest tests/unittests/worker/test_crawl_task_terminal_outcomes.py -q`
- `cd backend && uv run pytest tests/integration/test_phase0_zombie_reconciliation.py -q`
- `cd backend && uv run ruff check src/intric/worker/crawl src/intric/websites/domain/crawl_terminal.py tests/unittests/worker/test_crawl_terminal.py`
- `cd backend && uv run ruff format --check src/intric/worker/crawl src/intric/websites/domain/crawl_terminal.py tests/unittests/worker/test_crawl_terminal.py`
- `cd backend && uv run pyright --project pyrightconfig.json src/intric/worker/crawl/__init__.py src/intric/worker/crawl_tasks.py src/intric/worker/feeder/watchdog.py src/intric/websites/domain/crawl_terminal.py tests/unittests/worker/test_crawl_terminal.py tests/unittests/worker/test_crawl_task_terminal_outcomes.py`
- `! rg 'async def commit_terminal\b|async def commit_terminal_batch\b' backend/src/intric/worker/`
- `! rg 'from intric\.worker\.crawl\.terminal' backend/src backend/tests`
- `rg 'from intric\.websites\.domain\.crawl_terminal' backend/src/intric/worker/crawl/__init__.py`

Stop if:

- Moving the module requires changing terminal write semantics.
- Existing terminal tests need behavioral rewrites rather than import/ownership updates.
- The diff starts touching `CrawlService` failure handling, `WorkerAdapter`, admin UI, or scheduler behavior.
- The diff touches `crawl_tasks.py` or `watchdog.py` beyond import-path-only changes.
- The diff introduces a protocol, factory, registry, or session/UoW wrapper.

## Follow-up Worker Split

After the terminal owner is importable from a website/crawl-owned module:

- A1: Route `CrawlService._add_to_pending_queue(...)` `PendingQueueAddError` through `TerminalEvent(CRAWL_QUEUE_ENQUEUE_FAILED, ...)`.
- A2: Route direct ARQ/pre-acquired-flag enqueue failure through `TerminalEvent(...)`, with an explicit test that flag deletion and slot release happen before terminal commit.

Both follow-ups should use the same terminal commit implementation and should delete the corresponding `JobService.fail_job(...)` escape path.
