# Crawler Reliability, Robustness, Transparency, And Maintainability Plan

Branch: `feature/crawler-skip-unchanged-pages`

Status: Claude-reviewed implementation roadmap. Claude pass 4 returned `VERDICT: green`, `GREEN_LIGHT: yes`, `MIN_SCORE: 8`. Non-blocking P2/P3 refinements from that pass are incorporated below.

Goal: make crawler runs cheaper, more reliable, easier to reason about, easier to operate, and easier for users/admins to diagnose without adding quick workarounds or new technical debt.

## Plan Progress

- [x] Establish active roadmap goal.
- [x] Inspect crawler, worker, watchdog, outcome, settings, and admin UI owners.
- [x] Check ARQ and Scrapy capabilities from official documentation.
- [x] Claude peer-loop plan review pass 1.
- [x] Apply Claude pass-1 blockers to this document.
- [x] Claude peer-loop verification pass 2.
- [x] Apply Claude pass-2 blockers to this document.
- [x] Claude peer-loop verification pass 3 failed due to a Claude API socket close, not plan content.
- [x] Claude peer-loop verification pass 4 returned green with `MIN_SCORE: 8`.
- [x] Apply non-blocking Claude pass-4 refinements to this document.
- [x] Start implementation only after this roadmap gets green.
- [x] Step 1 parser/parity tranche: strict/lenient outcome parser functions, explicit read-side lenient imports, and `tests/fixtures/crawl_outcome_parity.json`.
- [x] Step 1 typed-settings tranche: replace dict-bag crawler setting specs with `CrawlerSettingSpec`, remove avoidable `Any`/casts from the touched helper boundary, and keep tenant settings tests/Pyright green.
- [x] Step 1 terminal-write inventory tranche: document direct `CrawlRuns`/`Jobs` terminal writes and private `TaskManager` escape paths as the Step 2 deletion list.
- [x] Step 2 starter tranche: replace direct private `TaskManager` mutation with explicit public terminal acknowledgement while preserving current terminal write behavior.
- [x] Step 2 duplicate-skip tranche: introduce `TerminalEvent` / `commit_terminal(...)` and route duplicate crawl skips through the canonical terminal commit seam.
- [x] Step 2 zero-output tranche: route terminal no-output crawl-run counters and failed job state through `TerminalEvent` / `commit_terminal(...)` before post-commit reactors.
- [x] Step 2 exception/shutdown tranche: route exception and shutdown terminal outcomes through `TerminalEvent` / `commit_terminal(...)` while preserving historical outcome-write policy.
- [x] Step 2 completion tranche: route normal and partial completion counters plus job completion through `TerminalEvent` / `commit_terminal(...)`.
- [x] Step 2 max-age busy-wait tranche: remove direct CrawlRun repository terminal write and map max-age abandonment through exception-to-`TerminalEvent`.
- [x] Step 2 pending-queue enqueue tranche: replace enqueue rollback repository writes with `commit_terminal(...)` and add typed `CRAWL_QUEUE_ENQUEUE_FAILED` backend/frontend presentation.
- [x] Step 4 watchdog terminal tranche: add `TerminalBatchEvent` / `commit_terminal_batch(...)` and route early-zombie plus long-running watchdog terminal writes through it.
- [x] Step 4 watchdog Phase 1 tranche: route expired queued crawl jobs with `CrawlRun` rows through `commit_terminal_batch(...)` and keep orphaned Job-only cleanup explicit.
- [x] Step 3 transparency tranche: add distinct `CRAWL_RUNTIME_TIMEOUT` for long-running crawls, keep queued max-age distinct, and regenerate the generated frontend schema enum.
- [x] Step 0 baseline tranche: add a read-only sysadmin crawler baseline endpoint with bounded crawl-run aggregation and typed UNKNOWN-vs-legacy fallback metrics.
- [x] Step 2 audit-reactor tranche: extract website-crawl audit payload construction and emission into a typed `worker/crawl/audit.py` boundary while preserving existing audit service/action/entity semantics.
- [x] Step 2 circuit-breaker reactor tranche: extract website crawl backoff/auto-disable policy into a typed `worker/crawl/circuit_breaker.py` boundary with direct tests for reset, first failure, capped backoff, and auto-disable.
- [x] Step 2 website-timestamp reactor tranche: extract post-crawl website timestamp policy and SQL write into a typed `worker/crawl/website_timestamps.py` boundary while preserving the existing timestamp operation name and lifecycle policy.
- [x] Step 2 auto-disable threshold tranche: make the crawler auto-disable failure threshold a domain-owned constant shared by `Website` and the circuit-breaker reactor.
- [x] Step 2 feeder duplicate baseline tranche: reconcile stale integration tests with ARQ-native duplicate semantics and the corrected duplicate slot-release invariant.
- [x] Step 2 slot-release reactor tranche: extract crawl-task slot release into a typed post-terminal reactor while preserving existing Redis slot semantics.
- [x] Step 3 historical outcome backfill tranche: backfill known legacy crawl outcomes with a bounded SQL migration while preserving unknown historical rows, non-terminal rows, existing typed outcomes, and historical `updated_at`.
- [x] Step 3 frontend generated-type cleanup tranche: fix crawler run and website aliases to existing OpenAPI schema IDs, remove the local crawl outcome shim, and key outcome labels by generated `CrawlOutcomeCode`.
- [x] Step 3 website crawler status tranche: remove direct `result_location` reads from website crawl status/failure UI and preserve unknown historical detail through typed `outcome.detail`.
- [x] Step 3 job dropdown tranche: stop the generic job dropdown from rendering raw `result_location` for crawl jobs while preserving non-crawl job details.
- [x] Step 3 failure-summary typed-contract tranche: route backend `failure_summary` through `FailureReason` internally while preserving the string-keyed JSON wire shape and metering unknown historical buckets.
- [x] Step 4 lifecycle anchor tranche: introduce `CrawlLifecycle` and pure derivation from existing `CrawlRun` state without production consumers or behavior changes.
- [x] Step 5 bootstrap tranche: extract website/session/auth/context/blob-state bootstrap into typed `worker/crawl/bootstrap.py` boundaries without passing `Container`.
- [x] Step 5 page-processing tranche: extract page iteration, heartbeat abort/preemption, batching, source-retention bookkeeping, and persistence-result aggregation into typed `worker/crawl/page_processing.py` boundaries.
- [x] Step 5 file-processing tranche: extract downloaded-file hash retention, changed-file callback processing, per-file failure isolation, and cleanup bookkeeping into typed `worker/crawl/file_processing.py` boundaries.
- [x] Step 5 cleanup tranche: extract stale cleanup calculation and delete-callback execution into typed `worker/crawl/cleanup.py` boundaries.
- [x] Active-crawl duplicate-guard index tranche: add task-scoped PostgreSQL lookup indexes, make the duplicate-guard query explicitly crawl-only, and cover pre/post planner behavior with a migration-isolation regression test.
- [x] Step 5 slot-acquire tranche: extract pre-acquired crawl slot discovery/reuse/mismatch handling into typed `worker/crawl/slot_acquire.py` boundaries while keeping ARQ retry and busy-wait policy in `crawl_tasks.py`.
- [x] Redis slot-key ownership tranche: consolidate the pre-acquired crawl slot Redis key behind one canonical helper reused by acquire, release, feeder, capacity, heartbeat, and watchdog code.
- [x] Admin active-crawler inventory tranche: add a read-only sysadmin endpoint for active/queued crawler jobs with typed lifecycle derivation, bounded pagination, tenant filtering, and orphan queued-job visibility.
- [x] Admin active-crawler name-resolution tranche: enrich the active/queued crawler inventory response with nullable website and tenant labels through bounded LEFT joins while keeping the count query lean.
- [x] Admin crawler failure-inventory tranche: add a read-only sysadmin endpoint for auto-disabled and backed-off crawler websites from durable circuit-breaker state.
- [x] Admin recent-failures inventory tranche: add a read-only sysadmin endpoint for terminal failed crawl runs with typed outcomes, bounded pagination, tenant filtering, failure-summary parsing, and explicit `since`/`until` windows.
- [x] Admin scheduled-crawler aggregate tranche: add a read-only sysadmin endpoint grouped by `UpdateInterval`, with zero buckets, typed totals, tenant filtering, and unparseable legacy interval accounting.
- [x] Admin per-website processing aggregate tranche: add a read-only sysadmin endpoint grouped by website, with bounded windowing, tenant filtering, stable throughput ordering, orphan-job preservation, and retained/failed/too-large counters.
- [x] Step 5 post-terminal effects naming tranche: rename the post-terminal side-effect owner away from Twisted-conflicting reactor vocabulary and pass `AuditService` directly instead of routing audit emission through the DI container.
- [x] Step 5 recovery executor container-trim tranche: remove the unused `Container` argument from the session-per-operation recovery executor and post-terminal recovery context without changing transaction semantics.
- [x] Step 5 dead recovery deletion tranche: delete orphaned `recover_session(...)`, its public exports, and the tests that only covered that dead path.
- [x] Step 5 recovery plumbing trim tranche: remove vestigial `SessionHolder`, `session_holder`, and `created_sessions` plumbing now that sessions are fully owned inside `execute_with_recovery(...)`.
- [x] Step 5 post-terminal recovery-context collapse tranche: delete the one-field `PostTerminalRecoveryContext` wrapper and pass the typed recovery executor directly through `PostTerminalEffectInput`.
- [x] Step 5 post-terminal operation-name coverage tranche: cover both post-terminal circuit-breaker operation-name literals while keeping the recovery fake behavior-focused and signature-exact.
- [x] Step 5 crawler TaskManager result-location trim tranche: remove normal-completion dependence on generic `TaskManager.result_location` while preserving the terminal job result URL.
- [x] Step 5 container override seam tranche: centralize crawler dependency-injector override casts behind `container_overrides.py`, add scoped restoration tests, and remove worker `Any`/`cast` imports from `crawl_tasks.py` and `persistence.py`.
- [x] Step 5 pre-resolved embedding contract tranche: replace stringly pre-resolved embedding model detection with `PreResolvedEmbeddingModelLike` plus a TypeGuard, preserving provider failure semantics and proving no-DB credential/config pass-through behavior.
- [x] Step 5 adapter batch-size ownership tranche: make `EmbeddingModelAdapter` the single owner of effective embedding batch-size resolution, remove defensive `self.model` getattr reads, and delete duplicate LiteLLM batch-count calculation.
- [x] Redis slot Lua ownership tranche: delete duplicated slot Lua and raw slot-key ownership from `CrawlService`, route optimistic acquire/release through `LuaScripts`, and lock the canonical owner with behavior tests.
- [x] Pending queue ownership tranche: make `PendingQueue.add` the typed canonical writer, remove raw queue key/serialization/rpush ownership from `CrawlService`, and preserve scheduled/manual rollback behavior with tests.
- [x] Tenant limiter Lua ownership tranche: route `TenantConcurrencyLimiter` through `LuaScripts.acquire_slot/release_slot`, preserving circuit-breaker and fallback semantics while removing inline Redis slot eval ownership.
- [x] Terminal ownership relocation tranche: move `TerminalEvent` / `commit_terminal(...)` to a website-owned crawl terminal persistence boundary and delete the worker-local implementation file.
- [x] Manual pending-queue terminal parity tranche: route `CrawlService` pending queue add failures through `TerminalEvent(CRAWL_QUEUE_ENQUEUE_FAILED)`, share the bounded enqueue-failure message helper with scheduled crawls, and keep the original `PendingQueueAddError` authoritative when terminal commit fails.
- [x] Manual direct-enqueue terminal parity tranche: route `CrawlService` direct ARQ/pre-acquired rollback failures through `TerminalEvent(CRAWL_DIRECT_ENQUEUE_FAILED)`, preserve flag-delete/slot-release/terminal-commit ordering, and expose the distinct typed outcome through backend/frontend presentation.
- [x] Completion audit tranche: T105 and Claude both rejected marking the whole roadmap complete; remaining WorkerAdapter, admin write controls, lifecycle completion, OpenAPI regeneration, and phase-size/type cleanup remain explicit follow-up work.
- [x] Static terminal-ownership guard tranche: add a source-level regression test that keeps crawler `CrawlRuns` terminal writes and crawler entrypoint job terminal mutations on the canonical `crawl_terminal.py` / `TerminalEvent` path.
- [x] Typed Redis pipeline boundary tranche: move Redis pipeline result typing to `worker/redis/client.py` so `worker/crawl/heartbeat.py` and `worker/crawl/recovery.py` no longer need local `cast(...)` for pipeline results.
- [x] Step 5 completion-log tranche: move crawl completion/performance logging into `worker/crawl/completion_log.py`, reuse `CrawlRunProcessingSummary`, and protect source-retained/hash-retained/too-large metric semantics with behavior tests.
- [x] Queue-boundary scout tranche: reject premature `WorkerAdapter`/one-file Redis protocol work and select a concrete typed crawl enqueue owner as the next ownership-collapse slice.
- [x] Typed crawl enqueue owner tranche: add a concrete union-typed enqueue owner for already-created crawl jobs, reuse it from pending queue, manual direct handoff, and watchdog requeue paths, and stop watchdog from constructing `arq.jobs.Job` directly.
- [x] Pending-feeder typed enqueue consumption tranche: remove the tuple-shaped pending enqueue compatibility edge, make `CrawlFeeder._process_tenant_queue` consume `CrawlEnqueueResult` exhaustively, and prove pending-entry, slot, and pre-acquired-flag invariants with behavior tests.
- [x] Typed Redis feeder/queue boundary tranche: move Redis list, delete, expiry, and SCAN typing uncertainty to `worker/redis/client.py`, remove local Redis `Any`/`cast` usage from pending queue and feeder consumers, split strict producer payloads from lenient parsed payloads, and cover raw-byte LREM, cursor scanning, DLQ ordering, and source-ownership guard behavior.
- [x] Watchdog/capacity Redis SCAN boundary tranche: route watchdog Phase 0 active-counter scanning and capacity pending-queue scanning through `redis_scan_match_bytes(...)`, remove local Redis `Any`/raw SCAN ownership, and protect the boundary with behavior plus AST source-guard tests.
- [x] Sysadmin watchdog-status tranche: add a read-only `/sysadmin/crawler/watchdog-status` endpoint that exposes the canonical Redis watchdog snapshot, bounded watchdog-driven interventions, tenant filtering, pagination, malformed-snapshot degradation, and shared producer/healthz key ownership.
- [x] Typed crawl job-status owner tranche: move ARQ `JobStatus` behind `worker/feeder/crawl_status.py`, make watchdog requeue consume crawler-domain status, and guard the worker tree against direct `arq.jobs` imports.
- [x] Generated crawler sysadmin OpenAPI contract tranche: regenerate `@intric/intric-js` schema types from the current backend OpenAPI snapshot and add type-level coverage for the seven sysadmin crawler response and operation contracts.
- [x] OpenAPI freshness guard tranche: add a CI-backed regenerate-and-diff check that compares checked-in `@intric/intric-js` schema types with the current backend `app.openapi()` output.
- [x] Tenant-scoped admin recent-failures tranche: add `/admin/crawler/recent-failures` as the first browser/admin-callable crawler diagnostics endpoint, scoped to the current admin's tenant without exposing `tenant_id`, and split repository entry points into tenant-required vs sysadmin-optional methods.
- [x] Tenant admin recent-failures UI tranche: consume the tenant-scoped recent-failures endpoint from the admin crawler page through a typed Intric client method, using shadcn-Svelte components and bounded presentation helpers for outcome, website fallback, and activity labels.
- [x] Tenant admin recent-failures hardening tranche: replace the synthetic CrawlRun UI adapter with a narrower shared result-label source type, prove diagnostics-load failure does not break crawler settings, and show explicit shown/total recent-failure counts in the admin UI.
- [x] Post-T134 audit tranche: reject goal completion, select tenant-scoped active crawler inventory as the next bounded read-only admin transparency slice, and keep the admin UI consumer as an explicit follow-up.
- [x] Tenant-scoped active crawler inventory endpoint tranche: expose active/running crawler inventory under `/api/v1/admin/crawler/active` with a tenant-required repository method, shared presentation owner, no tenant_id query parameter, and tests for tenant scope, orphan exclusion, bounds, and OpenAPI typing.
- [x] Tenant admin active crawler UI tranche: consume `/api/v1/admin/crawler/active` in the admin crawler page so admins can see current queued/running crawler jobs without sysadmin endpoints.
- [x] Post-T137 roadmap reconciliation tranche: refresh stale plan evidence before starting another code slice, close baseline/phase-skeleton checklist drift against current code, and keep broader admin overview, WorkerAdapter, and write-control work as explicit follow-ups.
- [x] Tenant-scoped scheduled crawler aggregate endpoint tranche: expose `/api/v1/admin/crawler/scheduled` through the existing tenant admin crawler router, split scheduled aggregate repository ownership into tenant/sysadmin entry points, and move the shared scheduled response model into the crawler admin presentation owner.
- [x] Tenant admin scheduled crawler load UI tranche: consume `/api/v1/admin/crawler/scheduled` in the admin crawler page with a bounded shadcn summary card, independent load failure handling, locale-aware scheduled-count/size labels, and explicit shadcn plus UX review gates.
- [x] Step 6 ARQ abort primitive tranche: add `JobManager.abort_job(...)` as the narrow ARQ-native abort owner while deferring crawler-domain abort terminal/cleanup/slot/admin semantics until a production caller exists.
- [x] Step 6 queued-only abort tranche: add the first real tenant admin abort caller for queued crawl jobs, write a typed terminal abort outcome, and prevent pending-queue resurrection while explicitly deferring running abort.
- [x] Tenant admin queued abort UI tranche: expose queued-only crawler cancellation from the admin crawler page with shadcn confirmation, canonical typed 409 handling, generated OpenAPI coverage, localized `CRAWL_ABORTED` presentation, and audit metadata that preserves the website label.
- [x] Backend-owned active-inventory abortability tranche: expose `is_abortable` on active crawler inventory from the shared queued-abort predicate, so frontend action visibility no longer derives from lifecycle presentation state.
- [x] Sysadmin orphan abortability tranche: keep orphan queued crawl jobs visible in sysadmin active inventory while marking them non-abortable, because queued abort requires a `CrawlRun`-backed target.
- [x] Tenant admin website-processing UI tranche: expose tenant-scoped per-website crawler work with fetched, retained, too-large, and failure counters using a typed backend contract, generated frontend schema, shadcn table/card composition, and bounded default windowing.
- [x] Tenant admin crawler failure-state UI tranche: expose backed-off and paused-after-failures crawler websites to tenant admins with tenant-safe API contracts, shadcn table/card composition, and clear recovery-oriented copy.
- [x] Too-large file sample tranche: persist the configured download limit plus capped too-large file URL samples on crawl runs, expose them through generated backend/frontend contracts, and show actionable crawl-result tooltips without storing unbounded crawl logs.
- [x] Tenant admin watchdog-interventions tranche: expose watchdog-driven terminal outcomes through a tenant-scoped admin endpoint, generated frontend contract, and shadcn admin card without exposing a `tenant_id` query parameter.
- [x] Step 8 circuit-breaker reset tranche: tenant-admin endpoint `POST /api/v1/admin/crawler/websites/{website_id}/reset-circuit-breaker` that clears `consecutive_failures` and `next_retry_at` on the targeted website without touching `update_interval`, typed `CrawlCircuitResetResult` union with `CrawlCircuitResetPreviousState` (HEALTHY/BACKED_OFF/AUTO_DISABLED) so the audit metadata mirrors what the operator saw, `ActionType.WEBSITE_CRAWL_CIRCUIT_RESET` audit action with shared `integration_events` category, shadcn AlertDialog reset confirmation with separate copy for backed-off vs paused-after-failures rows, intric-js `crawlerAdmin.resetCircuitBreaker(websiteId)`, and a generated schema contract change. Also fixed the prior latent regression where `WEBSITE_CRAWL_ABORTED` was missing from `category_mappings.py` and `action_metadata.py` — surfaced by the same audit-registry exhaustiveness test that gates this tranche. Codex peer reviewer dispatched in fresh context (verdict AB) caught the audit-registry gap before commit. Deletion targets: none beyond replacing the manual DB intervention path now documented in the runbook.
- [x] Step 4 page-progress lifecycle fact tranche: introduce `has_no_page_progress(*, pages_crawled)` Python predicate plus `no_page_progress_sql_predicate(pages_crawled_column)` SQL counterpart in `websites/domain/crawl_lifecycle.py`, then route watchdog Phase 3.5 SQL through the SQL helper instead of inlining `or_(CrawlRuns.pages_crawled.is_(None), CrawlRuns.pages_crawled == 0)`. Did not add a `RUNNING_NO_PAGES` enum value because the public `CrawlLifecycle` OpenAPI contract is observed by `CrawlerActiveInventoryItem.lifecycle_state` consumers — a new state would force a frontend ripple that exceeds the per-tranche budget. The plan note at lines 583–586 acknowledges Phase 3.5's page-only predicate differs from `RUNNING_NO_PROGRESS` counter-wide semantics, so a *fact* (predicate) rather than a *state* (enum value) is the correct shape. Codex peer reviewer dispatched in fresh context (verdict AB) confirmed no other callsite carries the same predicate and recommended swapping the substring SQL assertion for byte-identical equality against the canonical `or_()` expression — applied. Unblocks plan follow-ups #1 (preserve Phase 3.5 named lifecycle transition — done, the watchdog SELECT now reads as a named predicate call) and #2 (replace null/zero watchdog heuristics — done; no other callsites today, but future watchdog code now has one canonical owner to import). Follow-ups #3 (`cleanup_policy` on `TerminalEvent`) and #4 (`CrawlAdminDetail.lifecycle_state` retype) have separate prerequisites and remain blocked. Deletion target: the inline `or_(CrawlRuns.pages_crawled.is_(None), CrawlRuns.pages_crawled == 0)` at `worker/feeder/watchdog.py:914` is replaced; no remaining raw page-progress predicate in worker code.
- [x] Step 8 abort running crawl tranche: lift the queued-only abort restriction. Tenant admins now abort QUEUED *and* IN_PROGRESS crawls from the same `POST /api/v1/admin/crawler/jobs/{job_id}/abort` endpoint. The canonical signal is a terminal `CRAWL_ABORTED` event written by `commit_terminal`; the worker's heartbeat preemption short-circuit observes `Jobs.status=FAILED` and exits via the slot-release reactor. Codex peer review in fresh context surfaced four high-severity defects in the initial design and the tranche shipped only after they were fixed: (1) **`commit_terminal` half-update** — the CrawlRuns UPDATE was unconditional even when the Jobs UPDATE matched zero rows due to the optimistic concurrency gate, allowing terminal-state corruption (Jobs=COMPLETE while CrawlRuns.outcome_code=CRAWL_ABORTED) when a worker terminated between the SELECT and the UPDATE. Fix: gate the CrawlRuns UPDATE on `job_rows_updated > 0`, with an explicit unit test in `tests/unittests/worker/test_crawl_terminal.py`. (2) **Slot over-decrement** — the original cleanup helper unconditionally released the tenant slot when the preacquired flag was present, but a running worker holds the slot and will decrement it on its way out via the slot-release reactor; double-decrementing would let a future crawl exceed the configured tenant concurrency limit. Fix: split cleanup so running aborts skip slot release entirely, with an integration test seeding `tenant:<id>:active_jobs=2` plus the preacquired flag and asserting both are untouched after the admin abort. (3) **ARQ abort blocked HTTP requests** — `JobManager.abort_job(job_id)` defaulted to `timeout=None`, meaning the admin HTTP request blocked until the worker fully unwound (10+ minutes for long crawls). Fix: signal-only `timeout=0`, asserted in the integration test. (4) **No pre-cleanup preemption check** — heartbeat polls pause during synchronous SQL phases, so a tenant admin aborting between heartbeats could see the worker complete cleanup before observing FAILED, violating the "safe-cleanup skip" guarantee. Fix: added an explicit preemption check immediately before `cleanup_stale_blobs` in `worker/crawl_tasks.py` that raises `JobPreemptedError` to short-circuit cleanup. Also removed `CrawlAbortConflictCode.RUNNING_ABORT_NOT_IMPLEMENTED` (named deletion target), renamed `is_queued_crawl_abortable_*` predicates to `is_crawl_abortable_*` to reflect their new scope, renamed `CrawlService.abort_queued_crawl` → `abort_crawl`, and renamed `intric-js` `abortQueuedJob` → `abortCrawl`. Frontend AlertDialog copy is lifecycle-aware (separate queued vs running titles, descriptions, confirm labels, and success toasts) with new i18n strings in both `en.json` and `sv.json`. Generated OpenAPI schema regenerated. Follow-up (B-tier from codex review, deferred): let `JobPreemptedError` propagate out of `crawler.py:741-748` instead of being swallowed by the broad `except Exception` in `heartbeat_loop` — separate atomic change scoped beyond this tranche.
- [x] Step 8 pause/resume scheduled crawl + interval change tranche: tenant admins can pause (set `update_interval=NEVER`), resume (set to a recurring value), or pick a different recurring interval from a new `PATCH /api/v1/admin/crawler/websites/{website_id}/update-interval` endpoint without navigating to the space-owned website edit page. The endpoint bypasses `WebsiteCRUDService.update_website` because tenant admin permission is broader than the space-actor permission that service authorizes against; the new tenant-scoped `WebsiteAdminRepository.set_crawl_update_interval_for_tenant(...)` constrains the SQL to `WHERE id = :id AND tenant_id = :tenant_id`. Domain result types: `CrawlIntervalChangeApplied | CrawlIntervalChangeUnchanged | CrawlIntervalChangeNotFound`. Idempotent no-op (requested interval equals stored value) returns 204 and writes no audit row to keep the audit trail signal-to-noise high. New `ActionType.WEBSITE_CRAWL_INTERVAL_CHANGED` registered in `category_mappings.py` (integration_events 21→22) and `action_metadata.py` (Swedish display copy). Codex peer review in fresh context (verdict AB, Borda 22/25) surfaced one material product bug: resuming an auto-disabled website (previous=NEVER + counters ≥ threshold + new=recurring) without clearing `consecutive_failures` would let the next crawl failure immediately re-trip auto-disable, leaving operators with no recovery path short of also calling `/reset-circuit-breaker`. Fix: the repo method now clears `consecutive_failures` and `next_retry_at` in the same UPDATE strictly for the auto-disable-resume transition; pause and recurring-to-recurring changes intentionally preserve the counters so "change schedule" stays distinct from "reset circuit breaker". The `CrawlIntervalChangeApplied` result exposes `failure_state_cleared: bool` so the audit metadata records the side effect honestly. Frontend adds a "Change schedule" button on each failure-inventory row alongside the existing Reset button, opens an `AlertDialog` with a shadcn `Select` over the four `UpdateInterval` options. Confirm-button copy branches on the transition (`confirm_pause` for recurring→never, `confirm_resume` for never→recurring, `confirm` otherwise) via the new `crawlerUpdateInterval.ts` helper. `intric-js` exposes `crawlerAdmin.setUpdateInterval(websiteId, updateInterval)`. Deferred follow-ups (non-blocking from codex review): rename the `_UpdateIntervalRequest` Pydantic body class (leading underscore leaks into the OpenAPI component name); add a Svelte component test for the dialog state machine when the admin page gets a component-test harness; switch audit metadata from `extra={previous,new}` to the idiomatic `changes={"update_interval": {"old", "new"}}` shape used by other entity updates.
- [x] Step 7 admin filter set (initial) tranche: add the highest-signal filters to the existing tenant admin diagnostics endpoints — `outcome_code` query parameter on `GET /api/v1/admin/crawler/recent-failures` and `GET /api/v1/admin/crawler/watchdog-interventions` (each validates the requested `CrawlOutcomeCode` is within the endpoint's published allowlist before reaching the repo, returns 422 otherwise so the operator gets immediate feedback instead of silent zero rows); `state` query parameter on `GET /api/v1/admin/crawler/failure-inventory` accepting `BACKED_OFF` or `AUTO_DISABLED` to narrow the response to a single failure bucket. Repo signatures gained typed optional parameters (`outcome_filter: CrawlOutcomeCode | None`, `state_filter: CrawlerFailureState | None`) that the SQL builders apply by tightening the `WHERE` clause; omitting the filter preserves the prior unfiltered semantics so existing UI continues to work unchanged. The `_recent_terminal_outcomes` helper raises `ValueError` if a caller passes an `outcome_filter` outside the endpoint's allowlist — defensive belt for the allowlist check that already lives at the router boundary. 7 integration tests cover both filter directions, the cross-allowlist 422 rejection, the unknown-enum 422 rejection from FastAPI validation, and the omitted-filter regression. Generated OpenAPI schema regenerated. Deferred follow-ups (non-blocking): tenant filter on cross-tenant sysadmin endpoints (already implicit via tenant-scoped endpoints); space + user attribution enrichment on active inventory rows; lifecycle-status filter on active inventory; richer filter UI controls on the admin page (toolbar of toggle groups + outcome picker) — separate UX-focused tranche to apply the `impeccable` design pass to the filter affordances.
- [x] Token-efficiency drift surface (item 4) tranche: surface operator-visible drift signals on the website-processing aggregate. Two typed predicates in `crawlerWebsiteProcessing.ts`: `isCrawlerWebsiteProcessingLowRetention(item)` flags rows where `retention_rate < 0.5` and `indexed_content_count > 0` (cold websites stay unflagged), and `isCrawlerWebsiteProcessingSourceSkipDrift(item)` flags rows where `indexed_content_count >= 50` and `pages_source_retained == 0` (busy websites where sitemap source-skip stopped helping). The constants `CRAWLER_LOW_RETENTION_THRESHOLD = 0.5` and `CRAWLER_SOURCE_SKIP_DRIFT_MIN_INDEXED = 50` stay exported so the test suite + future tuning callers share one source of truth. UI: two caution-toned badges next to the retained count on each website-processing table row, with accessible `title` tooltips explaining the signal (`Low retention` + `Source-skip not helping`). i18n: 4 new keys × 2 locales. 4 new unit tests cover both predicates' positive/negative cases including the cold-website / quiet-website carve-outs. Deletion target: "token-efficiency only in logs" operational dependence for the surfaced metrics is removed — operators see retention regression + source-skip drift at-a-glance on the admin crawler page. Backend already exposed `retention_rate` and `pages_source_retained`, so no backend change needed for this tranche; the drift signal is purely a presentation contract.
- [x] Step 0 admin crawler page telemetry (item 5) tranche: add bounded latency instrumentation to all six tenant-admin crawler GET endpoints via the `_admin_crawler_query_telemetry(...)` async context manager in `admin/crawler_admin_router.py`. Emits one structured log entry per request with `metric_name=crawler.admin.query_duration_ms` and `metric_value=<elapsed_ms>` plus `endpoint` and `tenant_id` keys — uses the existing log-as-metric ingestion pattern already established by `crawler.settings.invalid_overrides_ignored` (in `crawler_settings_helper.py:293`) and `tenant_concurrency` metrics, so no new dependency or storage is introduced. The timing window covers only the repo + presentation work the endpoint owns; payload-size telemetry stays on the FastAPI middleware layer's content-length record so the per-endpoint hot path doesn't pay for a second JSON encode. Coverage: `active_inventory`, `failure_inventory`, `recent_failures`, `watchdog_interventions`, `scheduled_aggregate`, `website_processing_aggregate`. Deletion target: plan Step 0 open item "Record current admin crawler page query latency and payload size" is closed — operators can compare before/after admin page slices against the metric stream. 25 integration tests pass across the instrumented endpoints with the instrumentation transparent to the wire shape. Frontend client-side telemetry is intentionally deferred — the backend duration metric is the operator-relevant signal; client-side fetch timing would add console noise without proportionate operator value.
- [x] Audit emission helper (sub-tranche 7a) tranche: extract `_log_crawler_admin_website_action(...)` in `admin/crawler_admin_router.py` as the single canonical audit emission for all crawler admin website mutations. The four write endpoints (abort, circuit-breaker reset, interval change, and any future per-website action) share the same audit shape — tenant-scoped, actor=current_user, entity=WEBSITE, metadata=AuditMetadata.standard with an extra payload — and the helper centralizes the tenant scoping + entity_type + actor wiring so the audit-coverage gate is visible at the router boundary instead of buried inside three near-identical blocks. Backed by a narrow `_AuditableWebsite` Protocol (read-only `id` UUID + `name` str via `@property`) so the helper accepts every domain result type (`CrawlAbortWebsite`, `CrawlCircuitResetWebsite`, `CrawlIntervalChangeWebsite`) without importing each one for typing. Deletion target: 3 near-identical audit emission blocks at `crawler_admin_router.py:275`, `:329`, `:398` replaced with one-line helper calls (16-line audit boilerplate → 9-line helper call per site = 21 lines deleted). Frontend `ConfirmActionDialog` Svelte component (deletion of 3 inline `AlertDialog` blocks at `+page.svelte:1216/1251/1284`) deferred to sub-tranche 7b. 23 integration tests pass across the three audit-emitting endpoints (abort, circuit-breaker reset, interval change), verifying the helper produces the exact same audit row shape as before.
- [x] Test/contract hygiene (item 8) tranche: close the punch list of pre-existing breakage and naming smells flagged earlier in the session. Replaced dict-subscript access `CRAWLER_SETTING_SPECS["download_timeout"]["default"]` with the dataclass attribute access `.default` at `tests/integration/test_crawler_timeout_enforcement.py:260,282` — the dict→dataclass migration in the prior typed-settings tranche left these two tests with `TypeError: 'CrawlerSettingSpec' object is not subscriptable` for the full session window. Renamed `_UpdateIntervalRequest` → `UpdateIntervalRequest` in `admin/crawler_admin_router.py:361,375`; the leading underscore was a Python private convention that incorrectly leaked into the public OpenAPI component name. Generated `intric-js` schema regenerated and freshness check passes. Tests: 21 passed across `test_crawler_timeout_enforcement.py` (10 incl. the previously-failing default-behavior tests) + `test_admin_crawler_set_update_interval.py` (11, including the renamed-class regression). Deletion targets: the broken dict-subscript access pattern in the timeout test and the underscore-prefixed schema component name in the public generated OpenAPI types are both removed.
- [x] Admin-editable settings expansion (sub-tranche 3a) tranche: expand the tenant-admin self-service crawler settings allowlist to include five tenant-scoped runtime knobs — `crawl_max_length`, `crawl_stale_threshold_minutes`, `queued_stale_threshold_minutes`, `crawl_heartbeat_interval_seconds`, `crawl_job_max_age_seconds`. Each value is read at crawl start so a tenant-admin change does not affect already-running crawls; each new crawl picks up the updated value. Bounds come from the canonical `CrawlerSettingSpec` so the API boundary (Pydantic `ge=/le=`) and the worker runtime stay in one source of truth. Explicitly excluded from this expansion: `tenant_worker_concurrency_limit` and `tenant_worker_semaphore_ttl_seconds` (capacity governance — sysadmin), `crawl_feeder_*` (global feeder runtime), `crawl_page_batch_size` (deferred to the token-efficiency tranche where the right operator-facing surface is a retention/cost observation rather than a free knob). Backend: 5 new `Field(ge=, le=)` definitions on `CrawlerSettingsSelfServiceUpdate`; 5 new entries in `SELF_SERVICE_CRAWLER_SETTING_KEYS`; the existing tenant settings endpoint, audit row (`TENANT_SETTINGS_UPDATED`), and `specs`/`editable_settings` response fields automatically pick the new keys up. Frontend: 5 new `CrawlerNumberField` entries in `CRAWLER_SETTINGS_NUMBER_FIELDS` with i18n title/description/unit keys (including a new `crawler_unit_minutes`); `CrawlerSettingsUpdate` Pick union widened; `emptyFormValues` + `buildFormValues` propagate the new keys; the existing settings page automatically renders the new inputs with proper bounds from the response specs map. Tests: existing operator-only test updated to assert that capacity governance + feeder runtime + `crawl_page_batch_size` still reject, new `test_admin_can_update_tenant_runtime_knobs` integration test for the happy path with override propagation + spec bounds visible on the response, new `test_admin_runtime_knob_update_rejects_out_of_bounds` for the API-boundary validation. Frontend unit tests updated to reflect the new editable keys. Generated OpenAPI schema regenerated. Item 3 (Expand admin-editable crawler settings) sub-tranche A shipped; B (UI bounds refinement), C (audit shape), D (safety guards on hot keys like crawl_max_length affecting active crawls) remain deferred. Deletion target: env-only paths for the 5 newly exposed settings are no longer the only way to change tenant runtime — tenant admins can now edit them from the admin page without sysadmin key.
- [x] Active inventory frontend surfacing (sub-tranche 2c) tranche: surface the 2a attribution and 2b filter as operator-visible UI on the admin crawler page. Adds shadcn-Svelte `toggle-group` + `toggle` primitives (installed via shadcn-svelte CLI) and a `ToggleGroup` filter bar above the active inventory table (`all` / `queued` / `running with progress` / `running waiting for progress`); changing the toggle triggers a client-side fetch via `intric.crawlerAdmin.activeInventory({ lifecycle_status })` and replaces the visible payload, so rapid toggling stays responsive without re-running the SvelteKit load function. Two new table columns (`Source` = `Space › Collection`, `Started by` = user email) with truncation and accessible tooltips. Helper functions in `crawlerActiveInventory.ts` (`getCrawlerActiveInventorySourceLabel`, `getCrawlerActiveInventoryStartedByLabel`, `getCrawlerActiveInventoryLifecycleFilterLabel`, `CRAWLER_ACTIVE_INVENTORY_LIFECYCLE_FILTER_OPTIONS`) own the label vocabulary so the Svelte page stays declarative. 4 new unit tests cover source-label composition (space + collection vs missing one vs both missing), started-by-label trimming, filter-option exhaustiveness, and filter-label copy. `intric-js` client signature widened to accept the new optional `lifecycle_status` parameter. 12 new i18n keys × 2 locales. Frontend `bun run check` (0 errors) + `bun run lint` (clean after format). Deletion target completed: the `limit:8`-default-only visibility path is now operator-bypassable via the filter — the active inventory card no longer forces operators to scan a mixed bag of queued/running rows at a fixed page size. Item 2 (Active inventory completeness) is now fully shipped across 2a (attribution backend), 2b (lifecycle filter backend), and 2c (frontend surfacing).
- [x] Active inventory lifecycle filter (sub-tranche 2b) tranche: add `lifecycle_status` query parameter on `GET /api/v1/admin/crawler/active` accepting any `CrawlLifecycle` value. New `lifecycle_predicate_for_active_query(...)` SQL helper in `websites/domain/crawl_lifecycle.py` mirrors the Python `derive_crawl_lifecycle_from_counters` classifier so the SQL filter agrees byte-for-byte with the row-rendered `lifecycle_state` (drift here would silently hide rows from operators). `CrawlLifecycle.TERMINAL` filter returns an empty payload rather than 422 — operators toggling a ToggleGroup get a clean empty state instead of a validation error mid-toggle. 5 integration tests cover the 3 active buckets parametrically, the terminal-empty contract, the unknown-enum 422 from FastAPI validation, and the omitted-filter regression. Generated OpenAPI schema regenerated. Frontend filter UI deferred to sub-tranche 2c (impeccable design pass on the toggle bar + attribution columns). Deletion target: the `limit:8`-default-only visibility path is now opt-out — operators with too many active crawls can narrow by lifecycle without raising the limit.
- [x] Active inventory attribution (sub-tranche 2a) tranche: add typed `space_id`/`space_name`/`collection_id`/`collection_name`/`user_started_by_id`/`user_started_by_email` attribution to `GET /api/v1/admin/crawler/active` so tenant admins can see — without leaving the admin page — which Space + Collection a running crawl serves and which user started it. Domain `CrawlerActiveInventoryItem` gains six nullable fields; repo `_active_inventory` adds four LEFT JOINs (Websites is tightened to tenant-qualified too) feeding only the SELECT; presentation `CrawlerActiveInventoryItem` Pydantic mirrors. Generated OpenAPI schema regenerated. Codex peer review verdict AB (19/20): the JOINs originally trusted `actor.can_read_space()` history at write time; codex flagged that a future regression (admin import, recovery path bug, backfill) could leak foreign-tenant space/collection name or email. Fix: tightened all four attribution JOIN predicates with `tenant_id == CrawlRuns.tenant_id` (and `Users.deleted_at IS NULL`) so the join itself fails closed; swapped projection columns from raw FK columns to joined-row IDs (`Spaces.id`/`CollectionsTable.id`/`Users.id`) so all six attribution fields render nullably together when any predicate filters out a cross-tenant or soft-deleted row — no partial-leak surface. Three integration tests (full attribution populated, bare website with no space/collection, cross-tenant poisoning regression) cover the wire shape. Lifecycle-status filter, pagination plumbing, and frontend surfacing deferred to sub-tranches 2b/2c. Deletion target: the `limit:8`-default-only visibility path stays in place pending 2c; this tranche enables the attribution-aware UI that 2b will surface.
- [x] Bounded running-abort stop tranche: closes the high-severity defect surfaced by codex peer review of the prior running-abort tranche — the broad `except Exception` swallow at `crawler.py:741` AND a second swallow site at `crawler.py:856` ate the worker's `JobPreemptedError`, so admin aborts of IN_PROGRESS crawls kept embedding/persisting until next heartbeat or `max_length`. New `CrawlPreempted` exception in `intric/main/exceptions.py` is the crawler-layer terminal stop signal. Extracted `_run_heartbeat_until_done(...)` helper at module level in `crawler.py` (parameter `_CrawlStoppable` Protocol for narrow test substitution) replaces both inline `heartbeat_loop` closures: on `CrawlPreempted` it calls `manager.stop_crawl(reason="preempted")` and returns the exception; on other `Exception` it logs and continues (transient resilience preserved). Both `_run_crawl_with_timeout` and `_run_sitemap_crawl_with_timeout` await the helper inside the existing try/finally, cancel it on teardown if still pending (codex AB regression fix — without the explicit cancel, teardown blocks on a stuck Redis/DB callback until the client's connection timeout fires), and raise the returned `CrawlPreempted` after `to_thread(blocking_crawl)` observes the engine shutdown. Worker boundary: `HeartbeatMonitor.crawler_tick()` in `worker/crawl/heartbeat.py` translates `JobPreemptedError` AND `HeartbeatFailedError` to `CrawlPreempted` so the crawler module never imports worker exception types; `worker/crawl_tasks.py:1024` switched from `heartbeat_monitor.tick` to `heartbeat_monitor.crawler_tick`. Codex peer review verdict AB (17/20); the cancellation regression fix and two missing tests (`crawler_tick` translation for both worker exception types + teardown-with-stuck-callback regression) shipped before commit. Deferred follow-up (codex D3, non-blocking): branch `_crawl_task_exception_outcome` on `CrawlPreempted` to surface heartbeat-failure-induced terminations as a distinct `CRAWL_HEARTBEAT_FAILED` outcome rather than falling through to `UNKNOWN_CRAWL_ERROR` — needs new outcome code, separate tranche. Deletion target: both broad `except Exception` preemption-swallow branches in the inline heartbeat loops are unreachable (replaced by the helper's narrow `except CrawlPreempted` + transient `except Exception`).
- [x] Retry-now (item 3) backend preparation sub-tranche: lay the audit-registry + typed-result groundwork for the tenant-admin `POST /api/v1/admin/crawler/websites/{website_id}/retry` endpoint without yet wiring the HTTP route or service method, so the next sub-tranche can ship the endpoint without touching audit schema again. Behavior added: new `ActionType.WEBSITE_CRAWL_RETRY_REQUESTED = "website_crawl_retry_requested"`; registered in `category_mappings.py` (integration_events) and `action_metadata.py` (Swedish display: "Crawl begärd omedelbart" / "Loggar när en administratör begär en omedelbar omkörning av en crawl"); new typed domain module `intric/websites/domain/crawl_retry.py` exposing `CrawlRetryWebsite` (subset for the audit emitter, mirrors `CrawlAbortWebsite` / `CrawlCircuitResetWebsite` / `CrawlIntervalChangeWebsite` so the shared `_AuditableWebsite` Protocol accepts every result type), `CrawlRetryQueued` (carries the new `crawl_run_id` for cross-reference), `CrawlRetryNotFound` (tenant-scope hides cross-tenant existence), and the `CrawlRetryResult` TypeAlias union. Behavior preserved: no existing action types or category mappings changed; no audit row written by this tranche (audit registry additions are forward-looking). Files (production): `backend/src/intric/audit/domain/action_types.py` (+1 line: new enum value), `backend/src/intric/audit/domain/category_mappings.py` (+1 line: integration_events), `backend/src/intric/audit/domain/action_metadata.py` (+4 lines: Swedish display copy), `backend/src/intric/websites/domain/crawl_retry.py` (new, 64 lines). Validation: `uv run ruff check ...` passed, `uv run pyright --project pyrightconfig.json ...` 0 errors, `uv run pytest tests/unittests/audit/ tests/unittests/websites/ -q` 160 passed (existing audit-registry exhaustiveness test gates that every new ActionType lands in BOTH category_mappings AND action_metadata; this tranche satisfies that gate up-front). Deferred next sub-tranche: the actual `POST .../retry` endpoint, `CrawlService.retry_crawl_for_tenant(website_id, tenant_id) -> CrawlRetryResult` method, and the tenant-scoped repository read that returns a `CrawlableWebsite` (`Website | WebsiteSparse`) suitable for `CrawlService.crawl(website)`. The blocker was that the ORM `Websites` row does not directly satisfy the `CrawlableWebsite` Protocol (pyright catches the type drift); the next sub-tranche should either add a `get_crawlable_website_for_tenant(website_id, tenant_id) -> Website | None` to `WebsiteAdminRepository` that returns the domain type, or refactor `CrawlService.crawl` to accept the wider ORM type. Also deferred: codex AB review (will fire once the endpoint lands), integration tests for happy path + 404 + audit row shape, intric-js `crawlerAdmin.retryCrawl(websiteId)` method, frontend dialog + button reusing `_AuditableWebsite` + `ConfirmActionDialog`. Plan line 805 "Retry now" remains open until the endpoint ships.
- [x] Heartbeat-failure terminal outcome (item 5) tranche: surface heartbeat-driven crawl terminations as a distinct typed outcome instead of the generic `UNKNOWN_CRAWL_ERROR` fallback. Behavior added: new `CrawlPreemptionCause` enum (`ADMIN_ABORT` / `HEARTBEAT_FAILURE`) on `intric.main.exceptions.CrawlPreempted` so the raise site discriminates the source at exception construction time; `HeartbeatMonitor.crawler_tick` re-raises `JobPreemptedError` as `cause=ADMIN_ABORT` and `HeartbeatFailedError` as `cause=HEARTBEAT_FAILURE`; new `CrawlOutcomeCode.CRAWL_HEARTBEAT_FAILED` value; `_crawl_task_exception_outcome` routes `CrawlPreempted(cause=HEARTBEAT_FAILURE)` to the new code while `ADMIN_ABORT` preemptions fall through to `UNKNOWN_CRAWL_ERROR` on purpose (the abort flow already commits `CRAWL_ABORTED` independently and a second terminal commit would race the abort). Behavior preserved: existing `CrawlPreempted(reason)` raise sites default to `cause=ADMIN_ABORT`; pre-existing `CrawlShutdownError` and `CrawlMaxAgeExceededError` branches in `_crawl_task_exception_outcome` are untouched; `CrawlPreempted.__init__` keeps `cause` as a keyword-only argument so existing positional construction in unit tests (e.g. `test_heartbeat_preemption_loop.py:111,191`) still works. Codex AB review verdict (gpt-5.5 / high effort, fresh context): BLOCKER + HIGH findings caught two real shippers that landed before commit: (B-BLOCKER) the public presentation mapper `_crawl_outcome_from_code` at `crawl_models.py:281-431` is an explicit if-chain that rewrites unknown codes to `UNKNOWN_CRAWL_ERROR` — the worker would have persisted `CRAWL_HEARTBEAT_FAILED` correctly but the API response would have erased it back to the generic bucket, making the new frontend label dead code on the wire. Fix: added a `CRAWL_HEARTBEAT_FAILED` branch returning `severity=ERROR`, `message_key="crawl_outcome_heartbeat_failed"`. (B-HIGH) the admin recent-failures + watchdog-interventions allowlist `RECENT_FAILURE_OUTCOME_CODES` at `crawler_recent_failures.py:11-26` is deny-by-default; omitting the new code would have hidden heartbeat terminations from the admin recent-failures panel and rejected them as filter values. Fix: added to the frozenset. Also caught a pre-existing cleanup-policy gap: `_CLEANUP_POLICY_BY_OUTCOME` was missing both the new `CRAWL_HEARTBEAT_FAILED` AND the existing `CRAWL_ABORTED` (the abort tranche shipped without updating the cleanup map, the exhaustiveness test was failing pre-commit). Fix: added both with `CLEANUP_NOT_REACHED` (admin abort + heartbeat failure both stop the worker mid-crawl with a partial page set — stale-blob deletion against a partial view would orphan canonical content). Files (production): `backend/src/intric/main/exceptions.py` (+30 lines: `CrawlPreemptionCause` enum + `cause` field on `CrawlPreempted`), `backend/src/intric/worker/crawl/heartbeat.py` (modified: explicit `cause=` keyword on both re-raises), `backend/src/intric/websites/domain/crawl_outcome.py` (+1 line: new enum value), `backend/src/intric/worker/crawl_tasks.py` (modified: new branch in `_crawl_task_exception_outcome`), `backend/src/intric/websites/crawl_dependencies/crawl_models.py` (modified: new presentation-mapper branch), `backend/src/intric/websites/domain/crawler_recent_failures.py` (modified: allowlist), `backend/src/intric/websites/domain/crawl_cleanup_policy.py` (modified: cleanup map gap fix). Tests: 7 new unit tests in `tests/unittests/worker/test_crawl_heartbeat_preemption_outcome.py` pin both ends of the contract (raise-time discriminator + outcome-mapping branch + admin-abort fallback + pre-existing branch regression). Commands: `uv run ruff check ...` passed, `uv run ruff format ...` passed, `uv run pyright --project pyrightconfig.json ...` 0 errors / 0 warnings, `uv run pytest tests/unittests/worker/test_crawl_heartbeat_preemption_outcome.py tests/unittests/worker/crawl/ tests/unittests/websites/ tests/unittests/crawler/ -q` 266 passed, `bash scripts/check-intric-js-openapi-schema.sh` clean (regenerated `frontend/packages/intric-js/src/types/schema.d.ts`). Deletion target achieved: heartbeat-induced terminations no longer fall through to `UNKNOWN_CRAWL_ERROR`. Deferred follow-up: scoped SQL backfill of pre-existing `crawl_runs.outcome_code = 'UNKNOWN_CRAWL_ERROR'` rows whose `result_location LIKE 'Crawl preempted: heartbeat failures exceeded threshold%'` to flip them to the new code — separate sub-tranche so historical and forward-looking heartbeat terminations land in the same admin filter bucket. Codex AB-tier recommendation NOT applied this tranche but documented in plan progress as the next sub-tranche.
- [x] crawl_tasks.py reduction (item 4) terminal-zero-output tranche: extract the no-output crawl terminator block from `worker/crawl_tasks.py` into a new typed module `worker/crawl/terminal_zero_output.py`. Behavior preserved: same `CrawlOutcomeCode` set (CRAWL_NO_PAGES_RETURNED / CRAWL_SITEMAP_NO_PAGES / CRAWL_FILES_TOO_LARGE_ONLY / CRAWL_TIMEOUT_NO_PAGES routed through the canonical `_terminal_zero_output_message(...)` helper that stays in the orchestrator), same `execute_with_recovery(operation_name="terminal_zero_output_commit", ...)` semantics, same `apply_post_terminal_effects(PostTerminalEffectInput(...))` payload with `circuit_breaker_operation_name="terminal_circuit_breaker_update"` and all-zero counters EXCEPT `files_too_large_skipped` (which carries the only successful-ish work the crawler did before terminating — operators need it in the audit trail to explain "the crawl ended but we still spent download bandwidth"), same `task_manager.acknowledge_terminal_commit(successful=False)` so the orchestrator's outer exception handler does not subsequently flip the job status, same `{"status": "failed", "outcome_code": <value>}` return dict so the ARQ job result wire shape is unchanged. Public surface: `CommitZeroOutputTerminalInput` frozen dataclass + `commit_zero_output_terminal(input, *, audit_service, task_manager) -> dict[str, str]`. Tests: 2 new unit tests in `tests/unittests/worker/crawl/test_terminal_zero_output.py` cover the happy path (status dict + ack invariants + zero-counter terminal commit + audit payload propagation) plus the files-too-large counter pass-through case via behavior-focused `_RecordedTerminalCommit` / `_RecordedPostEffects` fakes + monkey-patched `execute_with_recovery` and `apply_post_terminal_effects` seams — provable without a real DB session or the audit service stack. Existing `test_crawl_task_terminal_outcomes.py` updated to also patch `terminal_zero_output.execute_with_recovery` (since the new module owns its own import) so the 4 previously-failing "terminal-no-output" parametrize cases pass green again. Files (production): `worker/crawl/terminal_zero_output.py` (new, 178 lines), `worker/crawl_tasks.py` (modified, -65 net lines: 1581 → 1520). Commands: `uv run ruff check ...` (passed after one auto-fixable import sort), `uv run ruff format ...` (passed after format on test file), `uv run pyright --project pyrightconfig.json ...` (0 errors / 0 warnings), `uv run pytest tests/unittests/worker/ tests/unittests/crawler/ tests/unittests/tenants/ -q` (579 passed). Deletion target achieved: the ~90-line inline block at the previous `crawl_tasks.py:1005-1094` is replaced with a single typed function call that constructs the input dataclass and delegates to the new module. Long-term ≤400 line gate progress: 1634 (pre-tranche) → 1581 (post duplicate-guard) → 1520 (post terminal-zero-output). Codex review not triggered: change is below the LOC/risk thresholds (no audit schema change, no ActionType change, no terminal commit signature change — the TerminalEvent + CrawlAuditPayload + acknowledge_terminal_commit calls are relocated to a new module with byte-identical shape, the recovery + post-effects boundary contracts are unchanged).
- [x] Hydration mismatch P0 (item 1) toaster source tranche: fix the app-wide `hydration_mismatch` warning at `+layout.svelte:12,14,144` reproducible on `/admin` and `/admin/crawler`. Root cause: two toaster components in the layout chain rendered different DOM on SSR vs initial client render. (1) `lib/components/toast/Toaster.svelte` uses melt-ui's `use:portal` action — on SSR the action is a no-op so the toast container renders at its source position inside the layout subtree, on client the action moves it to `document.body` after mount. Svelte 5 treats the position drift as a hydration mismatch and bails the layout subtree out, which clears the page content area and was the reason `/admin/crawler` rendered blank after the warning. (2) `lib/components/ui/sonner/sonner.svelte` renders `<Sonner theme={mode.current}>` from `mode-watcher` — `mode.current` resolves to `undefined` on SSR but to the `prefers-color-scheme`/localStorage value on the client, so the rendered theme attribute differs. Both fixes use the same minimal pattern: `let mounted = $state(false)` + `onMount(() => { mounted = true })` + `{#if mounted}` gate around the rendered output. SSR and initial-client-render (which is hydration) both emit nothing at the source position, so Svelte's hydration walker sees a matching shape; after `onMount` fires the toast container and the sonner toaster render and mount cleanly. Files: `frontend/apps/web/src/lib/components/toast/Toaster.svelte` (+15 lines: `mounted` flag, comment, `{#if}` gate), `frontend/apps/web/src/lib/components/ui/sonner/sonner.svelte` (+13 lines: same pattern). Tests: existing 192 unit tests pass — Playwright smoke for `main childElementCount > 0 after hydration on /admin/crawler` deferred because the existing Playwright harness has no admin auth setup (the test would require a Storage State fixture with a valid JWT, which is a separate harness tranche). Commands: `bun run lint` (clean), `bun run test:unit` (192 passed, 1 skipped, 1 todo), `bun run check` (0 errors, 1 unrelated warning). Deletion target: the two SSR-time toaster renders that diverged from client are gone — both components now emit nothing on SSR. Follow-up: a second hydration mismatch source remains intermittent in dev (page sometimes renders correctly, sometimes still bails out after the same reload) — likely the `<html data-theme>` inline script in `app.html` writing `data-theme="light"` from localStorage before hydration while SSR rendered `data-theme="system"`; the proper fix is to read a `theme` cookie in `hooks.server.ts` and inject it via `transformPageChunk` so SSR + client agree from first paint. This belongs in a separate "theme cookie SSR" tranche.
- [x] crawl_tasks.py reduction (item 6) duplicate-guard tranche: extract the duplicate-crawl-guard ownership out of `worker/crawl_tasks.py` into a new typed module `worker/crawl/duplicate_guard.py`. Behavior added/preserved: `find_primary_active_job_id(session, *, website_id)` is the pure read of the oldest active CRAWL job for a website (moved verbatim from the previous private `_get_primary_active_job_id` helper, preserving the QUEUED/IN_PROGRESS active-status set, the `created_at ASC LIMIT 1` ordering, and the CRAWL-task scope); `try_duplicate_skip(*, session_scope, job_id, run_id, website_id) -> DuplicateSkipDecision | None` opens a fresh session via the caller-supplied `session_scope`, decides whether the running job is a duplicate, commits a typed `TerminalEvent(CRAWL_DUPLICATE_SKIPPED)` exactly once if so (with the same `Skipped duplicate crawl; active job {primary_job_id}` result-location copy operators see today), and returns a typed `DuplicateSkipDecision` carrying the primary job ID so `crawl_task(...)` can log + return the duplicate skip without re-querying the DB. The caller's broad `except Exception` defensive-fallback policy (proceed with the crawl if the guard read raises) stays in `crawl_task(...)` because it is orchestration-level policy, not duplicate-guard policy. Files (production): `backend/src/intric/worker/crawl/duplicate_guard.py` (new, 142 lines), `backend/src/intric/worker/crawl_tasks.py` (modified, -53 net lines: 1634 → 1581), `backend/src/intric/worker/crawl/__init__.py` (modified, +6 lines re-export). Tests: 4 new unit tests in `backend/tests/unittests/worker/crawl/test_duplicate_guard.py` pin the contract for the "no primary" / "this job is the primary" / "duplicate committed" / "duplicate committed even when job_rows_updated=0 race" cases via behavior-focused `_FakeSession` + monkeypatched `commit_terminal` seam — provable without a real DB or the full crawler stack. `tests/integration/test_crawl_scheduler_dedupe.py` updated to import from the new module name. `tests/unittests/worker/test_crawl_task_terminal_outcomes.py` updated to monkeypatch `crawl_tasks.try_duplicate_skip` (returns `None` for the "this job is primary" semantics it was already exercising) instead of the private helper. Commands: `uv run ruff check src/intric/worker/crawl_tasks.py src/intric/worker/crawl/duplicate_guard.py src/intric/worker/crawl/__init__.py tests/unittests/worker/crawl/test_duplicate_guard.py tests/integration/test_crawl_scheduler_dedupe.py` (passed), `uv run ruff format --check ...` (passed after format on test file), `uv run pyright --project pyrightconfig.json ...` (0 errors / 0 warnings), `uv run pytest tests/unittests/worker/ tests/unittests/tenants/ tests/unittests/crawler/ -q` (577 passed). Deletion targets achieved: the private `_get_primary_active_job_id` helper (~30 lines) and the inline duplicate-guard block (~60 lines including the TerminalEvent construction, the `commit_terminal` call, the duplicate-skip return shape, the log-zero-rows-updated guard, and the "proceed with the crawl" outer except — the policy except stays as orchestration policy in `crawl_task(...)`). Long-term ≤400 line gate progress: `crawl_tasks.py` 1634 → 1581. Partial — this is the first of several extraction slices; remaining candidates include the terminal zero-output commit + post-terminal effects block, the bootstrap → crawl-context wiring block, and the HTTP-cache-dir setup block, each of which fits the per-tranche reviewability budget. Codex review not triggered: change is below the LOC/risk thresholds (no audit schema change, no ActionType change, no terminal commit signature change — only relocates an existing canonical commit pattern to a new module with byte-identical SQL and TerminalEvent construction; the touched terminal commit is unchanged in shape, ownership, and semantics).

## Non-Negotiable Principles

- Prefer long-term maintainability over smallest diff.
- Prefer one canonical owner over scattered lifecycle branches.
- Prefer typed domain contracts over string parsing, raw JSON bags, private flags, and implicit conventions.
- Prefer Scrapy and ARQ built-ins where they fit the actual crawler problem.
- Prefer behavior tests that fail on real bad behavior over mock-heavy implementation tests.
- Prefer bounded diagnostics over storing unlimited logs, URL lists, or queue payloads.
- Every step must name what gets deleted or made unreachable.
- Do not use code names such as `v1`, `v1_5`, or `v2` in implementation names.

## Current Evidence

The current branch already improved skip-unchanged behavior, source-retained counts, too-large file visibility, typed crawler settings, and frontend outcome presentation. The next reliability work is not another isolated skip optimization; it is lifecycle ownership and operational transparency.

Important current friction:

- `backend/src/intric/worker/crawl_tasks.py` is still too large at 1,593 lines, but bootstrap, page iteration, file processing, cleanup, audit, circuit breaker, website timestamps, slot acquire/release, terminal commits, and cleanup policy are now extracted behind typed boundaries.
- `backend/src/intric/worker/crawl_tasks.py` now uses a public `TaskManager.acknowledge_terminal_commit(...)` seam. Duplicate crawl skips, zero-output crawls, exception/shutdown outcomes, normal/partial completion, max-age busy-wait abandonment, pending-queue enqueue failure rollback, and manual `CrawlService` pending/direct enqueue failures go through `commit_terminal(...)`.
- `_get_primary_active_job_id(...)` now filters explicitly to crawl jobs and is backed by reversible PostgreSQL indexes on active crawl jobs and crawl-run website/job lookups. The migration test proves the duplicate-guard lookup changes from a crawl-run sequential scan before the migration to planner-visible index usage after it.
- `backend/src/intric/worker/crawl_feeder.py` owns custom scheduling, Redis queues, leader election, tenant capacity, and pre-acquired slot protocol.
- `backend/src/intric/worker/feeder/watchdog.py` owns rescue/reconciliation logic that overlaps with worker lifecycle state. Its Phase 3.5 early-zombie behavior and Phase 3 long-running behavior must remain distinct lifecycle concepts.
- `backend/src/intric/crawler/crawler.py` mostly owns Scrapy diagnostics already; those diagnostics need a stable product-facing path.
- `backend/src/intric/websites/domain/crawl_outcome.py` now has strict and lenient outcome parsers; remaining work is deleting normal new-row dependence on legacy result strings.
- `backend/src/intric/websites/crawl_dependencies/crawl_models.py` still contains legacy read-side result string fallback from `result_location`.
- `backend/src/intric/tenants/crawler_settings_helper.py` now owns typed `CrawlerSettingSpec` values as the crawler-settings source of truth.
- `frontend/apps/web/src/routes/(app)/admin/crawler/+page.svelte` exposes current tenant crawler settings, active/queued crawl jobs, scheduled load, per-website processing, high-cost/cost-pressure ranking, backed-off/paused failure state, and recent terminal failures. Crawl-run result presentation now also exposes too-large file counts, the configured download limit, and capped URL samples; watchdog interventions remain a separate admin visibility gap.

## Core Recommendation

Stay on ARQ and make the crawler's ARQ boundary explicit. The reliability work should remove queue/runtime leakage from crawler orchestration rather than introduce a queue-runtime migration.

The correct order is:

1. Add type foundations and behavior-preserving seams.
2. Introduce a narrow `TerminalEvent` plus `commit_terminal(...)`.
3. Remove private TaskManager escape paths.
4. Make lifecycle and cleanup policy explicit.
5. Put ARQ behind a `WorkerAdapter`.
6. Build product/admin visibility from durable crawl-run records.

## Target Architecture

### Canonical Owners

| Concept | Current friction | Canonical owner | Why |
|---|---|---|---|
| Terminal event shape | Outcome code, job status, cleanup policy, audit policy, and details are implicit across branches | `TerminalEvent` domain value | One typed object describes what a crawl ended as before anything is written. |
| CrawlRun + Job terminal DB commit | Direct `sa.update(CrawlRuns)` / `sa.update(Jobs)` calls exist in multiple paths | `commit_terminal(session, event)` | One transaction commits durable run/job terminal state. |
| Audit, circuit breaker, website timestamps, slot release | Risk of making a new god Module if these are swallowed by a broad writer | Post-commit reactors keyed by `TerminalEvent` | Each reactor has one reason to change and can be tested independently. |
| Run lifecycle state | Implicit in status fields, null counters, watchdog phases, and result strings | `CrawlLifecycle` | One typed state model decides cleanup policy and terminal event construction. |
| Scrapy fetch diagnostics | Already mostly in `CrawlDiagnostics` | `CrawlDiagnostics` | Keep Scrapy stats parsing close to Scrapy and expose typed facts. |
| Queue enqueue/status/abort/health | ARQ calls and custom slot protocol leak across worker/feeder/watchdog | `WorkerAdapter` with an ARQ adapter first | Gives one seam for crawler code to use ARQ through typed operations. |
| Crawler settings runtime policy | Typed snapshot exists, but specs still carry `Any` | `TenantCrawlerSettings` plus typed `CrawlerSettingSpec` | Settings remain bounded, validated, and safe for admins. |
| Admin crawler visibility/control | No aggregate admin control plane | `AdminCrawlerOperations` | Product/admin UX reads durable domain state, not raw queue internals. |

### Terminal Event Shape

Suggested domain value:

```python
@dataclass(frozen=True, slots=True)
class TerminalEvent:
    crawl_run_id: UUID
    job_id: UUID
    outcome_code: CrawlOutcomeCode
    job_status: Status
    cleanup_policy: CleanupPolicy
    audit_policy: AuditPolicy
    finished_at: datetime
    failure_summary: FailureSummary | None
    processing_summary: CrawlRunProcessingSummary
    user_message_key: str
    user_detail: str | None
    admin_detail: CrawlAdminDetail | None
```

Rules:

- `TerminalEvent` is built from typed lifecycle facts, not from result strings.
- `commit_terminal(session, event)` writes only the `CrawlRuns` and `Jobs` terminal row fields.
- Audit, circuit breaker, website timestamp updates, and slot release are post-commit reactors. They may run in the same task, but they are not hidden inside `commit_terminal(...)`.
- Post-commit reactors are idempotent and best-effort: a reactor failure is logged with a metric and retried by watchdog/repair paths where possible, but it must not roll back an already committed terminal CrawlRun/Job state.
- No caller mutates `TaskManager` private fields to avoid default finalization.

### AuditPolicy

`AuditPolicy` should be a closed enum or `Literal` over the existing audit action domain. It must not be a raw string passthrough.

Required initial values:

- `WEBSITE_CRAWLED`
- `WEBSITE_CRAWL_FAILED`
- `WEBSITE_CRAWL_ABORTED`
- `WEBSITE_CRAWL_DUPLICATE_SKIPPED`
- `WEBSITE_CRAWL_PARTIAL`

Rules:

- `TerminalEvent` carries one `AuditPolicy`.
- The audit reactor maps `AuditPolicy` to the existing audit action type and metadata shape.
- Adding a new terminal outcome that changes audit behavior requires adding an `AuditPolicy` case and a test.

### CrawlAdminDetail

`CrawlAdminDetail` is a bounded typed diagnostic object, not a replacement for raw `result_location` text.

Suggested shape:

```python
@dataclass(frozen=True, slots=True)
class CrawlAdminDetail:
    lifecycle_state: str  # retype to CrawlLifecycle in Step 4
    cleanup_policy: CleanupPolicy
    worker_context: WorkerContext | None
    diagnostics: CrawlDiagnosticsSnapshot | None
    phase_durations_ms: Mapping[str, int]  # retype to Mapping[Phase, int] in Step 5
    samples: tuple[str, ...]
```

Rules:

- `samples` is capped.
- `diagnostics` is derived from `CrawlDiagnostics`, not raw Scrapy logs.
- `phase_durations_ms` is bounded to known phase names.
- `worker_context` carries queue/runtime facts that exist before `WorkerAdapter` lands.
- No field is typed as `Any` or `dict[str, Any]`.

`CrawlDiagnosticsSnapshot` is the bounded public/admin projection of `CrawlDiagnostics`: request/response counts, HTTP status counts, robots blocked count, downloader exception counts, file status counts, finish reason, elapsed time, and capped samples only.

### WorkerContext

Step 2 may need queue/runtime facts before `WorkerAdapter` lands. Use a small value object, not direct ARQ leakage:

```python
@dataclass(frozen=True, slots=True)
class WorkerContext:
    job_id: UUID
    worker_id: str | None
    job_try: int | None
    abort_requested: bool = False
```

`WorkerAdapter` later becomes the canonical source of `WorkerContext`; until then, crawler code may construct it at the ARQ boundary only.

### AuditPolicy Mapping

The audit reactor owns this mapping. Every emitted `CrawlOutcomeCode` must map to exactly one `AuditPolicy`.

| Outcome category | AuditPolicy |
|---|---|
| normal success, all unchanged, source-retention-only, files-too-large-only | `WEBSITE_CRAWLED` |
| no-pages, timeout-no-pages, shutdown error, embedding config missing, completed with page failures, unknown error | `WEBSITE_CRAWL_FAILED` |
| partial timeout with output retained | `WEBSITE_CRAWL_PARTIAL` |
| admin/user abort | `WEBSITE_CRAWL_ABORTED` |
| duplicate skipped | `WEBSITE_CRAWL_DUPLICATE_SKIPPED` |

### Post-Commit Reactor Recovery

`commit_terminal(...)` is the durable transaction. Reactor failures do not roll it back.

| Reactor | Failure behavior |
|---|---|
| audit | Best-effort with metric; missing audit can be repaired by replaying terminal events if an audit repair job exists later. |
| circuit breaker | Idempotent durable update; failure logs metric and is retried by watchdog/repair path because retry/backoff behavior depends on it. |
| website timestamps | Idempotent durable update; failure logs metric and is retried by watchdog/repair path because scheduling depends on it. |
| slot release | Idempotent capacity cleanup; failure logs metric and is retried by watchdog because stuck slots block future crawls. |

### FailureSummary

Current implementation uses `FailureReason` as the canonical internal key and
keeps the persisted/public JSON shape string-keyed. A dedicated value object is
deferred until a second invariant beyond typed keys earns the extra type.

Potential future domain value object:

```python
@dataclass(frozen=True, slots=True)
class FailureSummary:
    counts: Mapping[FailureReason, int]
```

Rules:

- JSONB serialization happens at repository/presentation boundaries.
- Worker/persistence/domain code uses `FailureReason`, not raw strings.
- Unknown stored historical strings are handled only in one read-compatibility boundary.
- Counts are derived from collections where possible and should not drift from URL/failure buckets.

### Strict Outcome Parsing

Keep a lenient read-side parser only for historical rows:

```text
parse_crawl_outcome_code_lenient(value) -> CrawlOutcomeCode | None
```

Add a strict write-side parser:

```text
parse_crawl_outcome_code_strict(value) -> CrawlOutcomeCode
```

Rules:

- Write paths must raise on unknown outcome strings.
- Historical read fallback may map unknown values to `UNKNOWN_CRAWL_ERROR`, but only inside the read-compatibility function and with a metric.
- Step 2 must delete broad substring parsing from normal new-row rendering.

### CrawlLifecycle

Suggested shape:

```text
Queued
RunningNoProgress
RunningWithProgress
Terminal(TerminalEvent)
```

Required terminal cleanup policies:

- `cleanup_allowed`: source frontier is complete and page processing is safe.
- `cleanup_skipped_partial`: timeout/shutdown/partial crawl; source frontier may be incomplete.
- `cleanup_not_reached`: crawl failed before meaningful output.
- `cleanup_noop`: duplicate, all unchanged, or source-retention-only where nothing should be deleted.

## Reviewability Budgets

Each implementation PR should stay within one coherent vertical slice.

Default guardrails:

- Prefer 1 to 4 production files per PR.
- Prefer under 500 net changed lines unless the PR is mostly deletion or generated type updates.
- Every PR description must include:
  - behavior added,
  - behavior preserved,
  - files changed,
  - branches deleted,
  - tests added,
  - commands run,
  - known follow-up.
- If a slice needs to exceed the budget, stop and update the plan before coding.

## Roadmap

### Step 0: Baseline And Safety Metrics

Status: closed for implemented baseline counters. The only remaining item is
runtime/UI performance telemetry for the admin crawler page, which is deferred
until the admin overview surface is stable enough to measure meaningfully.

Purpose: capture the current state before refactoring so we can prove reliability improved instead of trusting intuition.

Work:

- [x] Record baseline percentage of failed crawls that surface `UNKNOWN_CRAWL_ERROR`.
- [x] Record count/rate of read-side legacy outcome fallback usage.
- [x] Record counts for hash-retained pages/files, source-retained pages, too-large files, page failures, partial timeouts, duplicate skips, and no-page failures.
- [ ] Record current admin crawler page query latency and payload size if available.

Acceptance criteria:

- Baseline can be reproduced from DB/API without reading logs.
- Metrics are bounded by date window and tenant scope.
- Baseline does not store full Scrapy logs or unlimited URL lists.
- After Step 3, new crawl runs should have `UNKNOWN_CRAWL_ERROR` under 1% of failed crawler runs over a 7-day window, excluding explicitly marked historical fallback rows.

Deletion target:

- None. This step is measurement only.

Tests:

- Domain unit: aggregation on a small set of crawl-run facts.
- Integration: query returns bounded results for empty, small, and mixed datasets.

### Step 1: Type Foundations And Safe Phase Entry Points

Status: closed for foundational type work. The early phase-skeleton intent was
superseded by the concrete Step 5 phase extractions listed below.

Purpose: reduce type debt and create behavior-preserving entry points before moving terminal writes.

Work:

- [x] Replace `CRAWLER_SETTING_SPECS: dict[str, dict[str, Any]]` with a typed `CrawlerSettingSpec` dataclass or discriminated union.
- [x] Remove avoidable `Any` in `crawler_settings_helper.py` touched by the setting spec change.
- [x] Add strict and lenient crawl outcome parsers; keep lenient parser only for historical read fallback.
- [x] Introduce typed phase input/output skeletons for bootstrap, crawl, persist, cleanup, and finalize without moving terminal write semantics yet.
- [x] Document the direct terminal write sites in `crawl_tasks.py` as the deletion list for Step 2.
- [x] Add `tests/fixtures/crawl_outcome_parity.json` as the parity oracle for current `derive_crawl_outcome(...)` output: one row per currently emitted `CrawlOutcomeCode` plus one historical-unknown row.

Acceptance criteria:

- No new `Any`, `cast`, or `type: ignore` is added.
- `CRAWLER_SETTING_SPECS` remains the single source of truth, but is typed.
- Strict parser raises on unknown write-side values.
- Lenient parser is callable only from historical read fallback.
- Phase skeleton does not change public behavior.

Deletion targets:

- Untyped setting spec dictionaries.
- Any setting-spec helper comments that merely narrate obvious code.

Step 2 terminal-write deletion inventory:

| Site | Current behavior | Step 2 deletion path |
|---|---|---|
| `backend/src/intric/worker/crawl_tasks.py:274-294` | `_record_crawl_task_exception(...)` uses `TerminalEvent` and `commit_terminal(...)` after shutdown/unknown exceptions, with the previous "only fill missing crawl-run outcome" policy preserved. | Keep exception terminal writes on the canonical commit seam; move audit policy into post-commit effects later. |
| `backend/src/intric/worker/crawl_tasks.py:746-778` | Duplicate crawl guard uses `TerminalEvent` and `commit_terminal(...)`, then acknowledges terminal completion through `TaskManager`. | Treat duplicate skip as a non-error terminal outcome in audit/UI and reassess the acknowledgement seam now that row ownership is canonical. |
| `backend/src/intric/worker/crawl_tasks.py:1071-1132` | Zero-output terminal path uses `TerminalEvent`, `CrawlRunTerminalUpdate`, and `commit_terminal(...)`, then acknowledges terminal failure through `TaskManager`. | Keep row commit atomic while post-terminal effects stay independent; reassess whether `TaskManager` still needs a public terminal acknowledgement seam. |
| `backend/src/intric/worker/crawl_tasks.py:1447-1480` | Normal/partial completion uses `TerminalEvent` plus `CrawlRunTerminalUpdate` and `commit_terminal(...)` for counters, failure summary, outcome, job status, finish time, and result location, then acknowledges terminal success through `TaskManager`. | Keep audit and circuit breaker as post-terminal effects; reassess whether `TaskManager` still needs a public terminal acknowledgement seam. |
| `backend/src/intric/worker/task_manager.py:162-164` | `TaskManager` has a public terminal acknowledgement backed by private state. | Keep `TaskManager` out of terminal row ownership; after all terminal paths use `commit_terminal(...)`, reassess whether the acknowledgement seam is still needed. |

Tests:

- Red domain unit: unknown write-side outcome value raises.
- Red presentation unit: historical unknown read-side value still renders safe fallback and emits fallback metric.
- Red domain unit: a typed crawler setting spec rejects bool for integer settings.
- Red presentation unit: rows from `tests/fixtures/crawl_outcome_parity.json` keep identical public output.

### Step 2: TerminalEvent Commit And TaskManager Escape Removal

Status: in progress.

Purpose: remove private terminal escape paths and make durable terminal writes canonical.

Work:

- [x] Introduce `TerminalEvent`.
- [x] Introduce `commit_terminal(session, event)` for `CrawlRuns` + `Jobs` terminal row updates only.
- [x] Extract the website-crawl audit emission path into a typed post-commit reactor boundary.
- [x] Extract the website-crawl circuit-breaker path into a typed post-commit reactor boundary.
- [x] Add remaining post-commit reactors for website timestamps and slot release.
- [x] Replace direct terminal `sa.update(CrawlRuns)` and `sa.update(Jobs)` call sites in one vertical path at a time. Complete so far: worker crawl-task terminal branches, watchdog CrawlRun terminal branches, terminal writer ownership relocation, manual pending-queue failure parity, and manual direct-ARQ/pre-acquired rollback parity. Remaining generic `TaskManager.job_service.fail_job(...)` fallback is outside crawler terminal row ownership and should be reassessed only if crawler code starts relying on it again.
- [x] Remove all direct `setattr(task_manager, "_job_already_handled", True)` call sites.
- [x] Replace TaskManager private-flag coordination with an explicit public terminal-commit acknowledgement or remove TaskManager from crawler terminal ownership.

Acceptance criteria:

- No crawler code mutates private TaskManager fields.
- Grep for terminal `sa.update(CrawlRuns)` and `sa.update(Jobs)` in crawler code points to `commit_terminal(...)`, except migrations/tests.
- `commit_terminal(...)` does not call audit, circuit breaker, timestamp, or slot-release code internally.
- Post-commit reactors are independently testable.
- Post-commit reactor failures are idempotent best-effort failures: they log a metric, do not roll back committed terminal state, and have a documented retry/repair path where the reactor changes durable state.
- Duplicate skip, terminal no-output, partial timeout, shutdown, unknown exception, and successful completion each produce a `TerminalEvent`.

Deletion targets:

- All direct `setattr(task_manager, "_job_already_handled", True)` call sites. Completed in the Step 2 starter tranche.
- Direct terminal CrawlRun/Job update branches replaced by `commit_terminal(...)`.
- Comments explaining why the private TaskManager flag exists.

Tests:

- Red DB integration: duplicate crawl commits one terminal event with duplicate outcome and no private TaskManager mutation.
- Red DB integration: terminal no-pages commits failed job status, finished timestamp, outcome code, and no cleanup.
- Red DB integration: successful crawl commits complete job status and summary counts.
- Red DB integration: partial timeout commits warning outcome and cleanup-skipped policy.
- Red DB integration: unknown exception commits `UNKNOWN_CRAWL_ERROR` only through a typed terminal event.
- Red reactor unit: audit reactor failure logs a metric and does not change committed CrawlRun/Job state.
- Red DB integration: DB error during `commit_terminal(...)` rolls back both CrawlRun and Job terminal writes.
- Static architecture test: crawler `CrawlRuns` terminal writes stay in `crawl_terminal.py`, and crawler entrypoints do not call `job_service.fail_job`, mutate private TaskManager terminal flags, or update `Jobs` terminal state directly.

### Step 3: Backfill Outcome Codes And Delete Normal String Fallback

Status: in progress.

Purpose: remove "unknown reason" behavior caused by historical string parsing.

Work:

- [x] Keep one narrow historical compatibility function with metrics until old rows are backfilled.
- [x] Delete broad new-row substring parsing from `crawl_models.py`.
- [x] Preserve unknown historical detail as admin detail without pretending it is a known outcome.
- [x] Write a migration/backfill for known historical `result_location` patterns and counter-derived historical outcomes, leaving genuinely unknown rows for the legacy fallback metric.
- [x] Remove frontend dependence on legacy result strings.
- [x] Type backend `failure_summary` through `FailureReason` internally while preserving existing string-keyed JSON storage and public JSON output.
- [x] Emit a structured metric when historical `failure_summary` rows contain unknown buckets that must be dropped by the lenient read path.
- [x] Regenerate frontend API types through the normal OpenAPI flow.
- [x] Remove narrow frontend outcome type shims once generated types include the fields.

Generated-type cleanup note: the crawler outcome aliases now use the generated
schema contracts directly. The crawler sysadmin contract regeneration used the
current backend `app.openapi()` snapshot instead of the stale local
`localhost:8123` runtime, preserved OpenAPI path order, and produced a bounded
generated diff containing the seven sysadmin crawler paths, their component
schemas, `FailureReason`, `CrawlLifecycle`, and matching operations.

Failure-summary schema note: `CrawlRunPublic`, `CrawlRunUpdate`, and sysadmin
crawler failure rows now describe `failure_summary` as a JSON object whose
property names are constrained to the `FailureReason` enum in backend OpenAPI.
Runtime JSON remains the same string-keyed object. `openapi-typescript` v7.13.0
does not preserve JSON Schema `propertyNames` as a TypeScript key constraint, so
the generated type remains `{ [key: string]: number }`; preserving enum-keyed
maps would require a later generator customization or post-process, not a
hand-written frontend shim.

OpenAPI freshness guard note: CI now runs
`scripts/check-intric-js-openapi-schema.sh`, which imports the current backend
FastAPI app, writes `app.openapi()` to a temporary file, regenerates
`frontend/packages/intric-js/src/types/schema.d.ts` into a temporary file, and
diffs that output against the checked-in generated schema. This protects the
generated crawler contracts without requiring a running local backend or a
browser-callable sysadmin auth path.

Raw-result-location cleanup note: website crawl status, crawl-run result
presentation, and the generic job dropdown no longer render raw
`result_location` for crawl jobs. The generic job dropdown still renders
`result_location` for non-crawl jobs because those task domains do not yet have
a typed outcome contract in this roadmap.

Ordering note: extract the historical compatibility boundary before the
backfill. A backfill should be based on one reviewed legacy classifier instead
of creating a second, hidden runtime classifier inside migration SQL. The
backfill migration may still use a one-time SQL snapshot for migration
stability, but the runtime owner remains the historical compatibility boundary.

Acceptance criteria:

- New crawl rows never require parsing `result_location` to explain failure.
- Historical rows still render a safe fallback.
- `UNKNOWN_CRAWL_ERROR` means genuinely unknown, not "we forgot to parse a string."
- Frontend can display status, result, reason, retained/skipped counts, and too-large file counts from typed fields.

Deletion targets:

- Broad substring fallback branches for normal new-row rendering.
- Frontend crawler outcome type shims made obsolete by generated API types.

Tests:

- Red migration test maps known legacy rows.
- Red API test returns typed outcome for known historical rows.
- Red API test returns safe historical unknown fallback only through the compatibility boundary.
- Red frontend test renders a typed no-pages failure without using result string parsing.

### Step 4: CrawlLifecycle State Model

Status: in progress.

Purpose: make worker, watchdog, feeder, and UI agree on what a crawl is doing and what terminal action is allowed.

Work:

- [x] Introduce `CrawlLifecycle` with explicit running and terminal states.
- [x] Add watchdog Phase 3.5 and Phase 3 lifecycle observations without changing cleanup selection.
- [ ] Blocked follow-up: preserve watchdog Phase 3.5 early-zombie and Phase 3
  long-running concepts as named lifecycle transitions after a page-progress
  lifecycle fact exists.
- [ ] Blocked follow-up: replace null/zero watchdog heuristics only after equivalent
  lifecycle facts exist.
- [ ] Blocked follow-up: define cleanup policy on terminal event values only when a
  second runtime consumer cannot use `outcome_code`.
- [x] Introduce `CleanupPolicy` and exhaustive `CrawlOutcomeCode` mapping without
  production consumers or runtime behavior changes.
- [x] Use `CleanupPolicy` at the stale-cleanup boundary instead of the primitive
  `crawl_is_partial` flag.
- [x] Audit terminal transitions: crawl-task paths use `TerminalEvent`, watchdog
  batch paths use `TerminalBatchEvent`, and no cleanup-policy field is added yet.
- [ ] Blocked follow-up: retype `CrawlAdminDetail.lifecycle_state` from `str` to
  `CrawlLifecycle` only after `CrawlAdminDetail` exists in production code.

Lifecycle anchor note: the first Step 4 tranche is intentionally types-only.
`CrawlLifecycle` currently distinguishes queued, running without recorded
progress, running with recorded progress, and terminal rows. No worker,
watchdog, sysadmin, API, or frontend consumer is wired yet; those come in
separate behavior-preserving slices.

Watchdog lifecycle consumer note: the first production consumer must be
observational only. Phase 3.5 currently selects stalled startup jobs using
`pages_crawled IS NULL OR pages_crawled = 0`, while `CrawlLifecycle` treats all
crawler counters as recorded progress. Until a later task reconciles that
product decision, watchdog SQL predicates and terminal actions stay unchanged.

Watchdog lifecycle observation tranche: completed. Watchdog now records
`CrawlLifecycle` counts for Phase 3.5 and Phase 3 rows in phase logs, aggregate
cleanup metrics, and the Redis watchdog metrics snapshot. The derivation lives
in `crawl_lifecycle.py` through a primitive-field helper so watchdog does not
synthesize `CrawlRun` entities for observation.

Cleanup policy contract tranche: completed. `crawl_cleanup_policy.py` now owns
the closed cleanup-policy enum and the exhaustive mapping from
`CrawlOutcomeCode | None` to cleanup behavior. This intentionally has no
runtime consumer yet; the next wiring slice can use it without re-litigating
which terminal outcomes allow cleanup, skip cleanup, never reached cleanup, or
were no-op content mutations.

Cleanup policy stale-cleanup tranche: completed. The private stale-title
predicate now receives `CleanupPolicy`, derives it at the single production
callsite from the crawler-level outcome, preserves current stale-deletion and
partial-crawl skip behavior, and raises if a terminal category that never
reaches cleanup is passed to that boundary.

Step 4 deferred follow-ups:

- Add a page-progress lifecycle fact, likely `RUNNING_NO_PAGES`, before
  replacing watchdog Phase 3.5's `pages_crawled IS NULL OR pages_crawled = 0`
  SQL predicate.
- Keep `TerminalEvent.cleanup_policy` deferred. `cleanup_policy_for_outcome(...)`
  is deterministic and the current runtime consumer already has `outcome_code`.
- Keep `CrawlAdminDetail.lifecycle_state` deferred. `CrawlAdminDetail` is
  currently a planned diagnostic shape, not production code.

Acceptance criteria:

- Watchdog cannot mark a run failed without a lifecycle transition.
- UI cannot remain in "syncing" after terminal event commit.
- Cleanup policy is explicit in every terminal transition.
- Phase 3.5 and Phase 3 watchdog behavior are not collapsed accidentally.

Deletion targets:

- Watchdog lifecycle heuristics that become represented by named lifecycle transitions.
- Duplicate cleanup-policy conditionals in crawl task paths.

Tests:

- Red unit: queued crawl can transition to running-no-progress.
- Red unit: running-no-progress can transition to early-zombie terminal timeout.
- Red unit: running-with-progress can transition to partial timeout with cleanup skipped.
- Red unit: all-unchanged complete transition produces cleanup-noop.
- Red integration: watchdog writes terminal timeout through `TerminalEvent`.

### Step 5: CrawlPipeline Phase Extraction

Status: in progress.

Purpose: make the large crawl task readable and reviewable without moving complexity into shallow helpers.

Work:

- [ ] Move behavior-preserving phase skeletons from Step 1 into real phase modules.
- [x] Start with the tested `build_embedding_model_spec(...)` provider pre-resolution slice before moving the whole bootstrap phase.
- [x] Extract website/session/auth/context/blob-state bootstrap into `bootstrap_crawl(...)` with typed output and behavior tests.
- [x] Extract page processing into `process_pages(...)` with typed success/abort output and behavior tests.
- [x] Extract downloaded-file processing into `process_files(...)` with typed output and behavior tests for retention, changed-file processing, per-file failures, missing embedding model diagnostics, and cleanup bookkeeping.
- [x] Extract stale cleanup into `cleanup_stale_blobs(...)` with typed output and behavior tests for cleanup policy, ordered stale titles, empty cleanup, delete-callback failures, and report/action consistency.
- [x] Extract crawl slot acquire behavior into `acquire_crawl_slot(...)` with typed output and behavior tests for normal acquire, limit reached, pre-acquired reuse, tenant-injection discovery, tenant mismatch release, Redis read failures, invalid Redis state, TTL refresh failures, and mismatch release followed by limit reached.
- [x] Extract website size recalculation into `update_website_size_after_crawl(...)` with a typed tenant-scoped SQL boundary and behavior test.
- [x] Extract crawler job preemption detection into `is_job_preempted(...)` and reuse it from both heartbeat and final preemption checks.
- [x] Extract completion/performance logging into `emit_crawl_completion_logs(...)` while keeping processing counters owned by `CrawlRunProcessingSummary`.
- [ ] Each phase returns a typed output and does not write terminal state directly.
- [ ] Keep Scrapy-specific behavior in `crawler.py` and `CrawlDiagnostics`.
- [ ] Keep persistence retention behavior in `persist_batch()`.
- [ ] Keep terminal state in `TerminalEvent` + `commit_terminal(...)`.
- [ ] Introduce a `Phase` enum and retype `CrawlAdminDetail.phase_durations_ms` to `Mapping[Phase, int]`.
- [ ] Remove restating comments while preserving comments that explain upstream Scrapy constraints, transaction/idempotency invariants, or production incident history.
- [x] Centralize dependency-injector override typing in `container_overrides.py` and remove the obvious crawler `cast(Any, container.*).override(...)` sites from worker code.
- [x] Centralize Redis pipeline result typing in `worker/redis/client.py` and remove crawl-phase `cast(...)` calls from `heartbeat.py` and `recovery.py`.
- [ ] Address obvious `Any`/cast seams introduced by the split with typed phase inputs, not broad ignores.

Acceptance criteria:

- `crawl_task()` becomes orchestration glue rather than the implementation of every phase.
- `crawl_tasks.py` is reduced to 400 lines or less after Step 5, unless the plan is updated with a specific reason.
- Each phase has one reason to change.
- No new file is named `utils`, `helpers`, `manager`, `processor`, or `common`.
- Strict pyright passes for touched backend modules.
- After Step 5, no `Any` import remains in `backend/src/intric/worker/`, `backend/src/intric/worker/feeder/`, or `backend/src/intric/crawler/` top-level imports unless the survivor is documented as an external library boundary with a typed wrapper plan.

Deletion targets:

- Phase implementation blocks moved out of `crawl_tasks.py`.
- Obsolete comments that narrated the moved code.

Tests:

- Red phase test: bootstrap output contains typed settings snapshot and existing blob state.
- Red phase test: crawl output exposes pages, files, source-retained URLs, partial flag, and diagnostics.
- Red phase test: persist output exposes persisted, hash-retained, failed, and too-large counts.
- Red phase test: cleanup honors lifecycle cleanup policy.
- Red parity test: public outcome for successful, all-unchanged, partial-timeout, and no-pages runs remains unchanged.

### Step 6: WorkerAdapter For ARQ, Idempotency, Abort, And Health

Status: interface not started. Several concrete queue/Redis/status owners now
exist, but no `WorkerAdapter` abstraction exists yet; abort semantics and
idempotency tests remain open.

Purpose: isolate ARQ queue/runtime behavior behind a typed crawler-facing seam.

Work:

- [ ] Add a narrow `WorkerAdapter` Interface for enqueue, duplicate detection, status, abort, worker health, and slot release.
- [ ] First collapse repeated crawl enqueue/status ownership into a concrete typed owner before introducing a `WorkerAdapter` interface.
- [ ] Implement `ArqWorkerAdapter`.
- [ ] Move `slot_preacquired` protocol behind the adapter.
- [ ] Define retry semantics for crawl jobs explicitly.
- [ ] Add idempotency tests for worker death mid-batch and post-cleanup-before-finalize.
- [ ] Add abort behavior for queued and running crawler jobs.

Acceptance criteria:

- Crawler domain code does not call ARQ directly.
- Duplicate enqueue behavior uses ARQ custom job id semantics.
- Abort releases capacity and writes a terminal event.
- Running abort skips unsafe stale cleanup.
- Worker health is visible to admin read APIs without raw Redis payload leakage.

Deletion targets:

- Direct ARQ status/abort/enqueue reads outside the adapter, except worker bootstrap.
- Public leakage of `slot_preacquired` outside adapter-owned code.

Tests:

- Red adapter integration: duplicate job id returns duplicate, not exception-string parsing.
- Red adapter integration: queued abort writes terminal event and releases slot.
- Red adapter integration: running abort writes terminal event and skips cleanup.
- Red worker integration: mid-batch failure does not double-write terminal state.
- Red worker integration: post-cleanup-before-finalize failure is recoverable and does not replay unsafe cleanup.

### Step 7: AdminOperations Read-Only Dashboard/API

Status: in progress. Sysadmin read APIs exist for the main crawler inventory
views, and the first tenant-scoped admin diagnostics endpoint is now consumed by
the browser admin crawler page.

Purpose: give admins visibility into crawler cost, failures, stuck work, and scheduled load without logging into user accounts.

Work:

- [x] Add read-only admin endpoints for crawler active/queued inventory.
- [ ] Add read-only admin endpoints for broader crawler overview.
- [ ] Show active and queued crawls with age, tenant/space/website, worker state, and lifecycle state.
- [x] Expose scheduled crawls grouped by interval and approximate content size through a bounded sysadmin endpoint.
- [x] Expose scheduled crawls grouped by interval and approximate content size through a tenant-scoped admin endpoint.
- [x] Show scheduled crawls grouped by interval and approximate content size in the tenant admin browser page.
- [x] Expose per-website processing totals for pages, files, retained content, too-large files, and failed items over a bounded window.
- [x] Show high-cost websites by a defined score: `schedule_frequency_weight * indexed_content_count * (1 - retention_rate)`, with embedding spend added later only when reliable cost data exists.
- [x] Expose recent terminal failed crawler runs by typed `CrawlOutcomeCode` through a bounded sysadmin endpoint.
- [x] Expose recent terminal failed crawler runs through a bounded tenant-scoped admin endpoint without a `tenant_id` query parameter.
- [x] Show recent terminal failed crawler runs in the tenant admin crawler page without calling super-API-key `/sysadmin` endpoints.
- [x] Show too-large file counts and capped samples through a durable bounded crawl-run storage contract.
- [x] Show hash-retained/source-retained/file-retained counts and rates in tenant admin processing rows.
- [x] Show current backed-off and paused-after-failures circuit-breaker state in the tenant admin crawler page.
- [x] Show watchdog interventions in tenant/admin crawler visibility.
- [ ] Add filters by tenant, space, status, outcome, update interval, and time range.

Acceptance criteria:

- Default view is bounded: active/queued plus last 7 days of failures and scheduled aggregate.
- Pagination is mandatory for lists.
- Samples are capped.
- Empty states explain what is normal.
- Unknown errors show admin detail and next diagnostic step.
- Multi-tenant mode remains tenant-safe, even if most deployments are single tenant.
- Initial schedule weights are constants owned by `AdminCrawlerOperations`; making them tenant-configurable requires a later product decision.

Deletion targets:

- None at first. This is a new read model after lifecycle state is canonical.

Tests:

- Red API test: admin overview is bounded and paginated.
- Red API test: non-admin access is rejected.
- Red API test: tenant scope is respected.
- Red frontend test: active, queued, failed, all-unchanged, partial, too-large, source-retained, empty, and permission-denied states render.

### Step 8: Admin Write Controls

Status: in progress. Queued crawl abort is implemented end-to-end for tenant
admins; running abort, retry, pause/resume, interval changes, and circuit-breaker
reset remain separate safety slices.

Purpose: allow admins to safely intervene when crawls are expensive, broken, or stuck.

Dependencies:

- Must come after `TerminalEvent`, `CrawlLifecycle`, and the narrow queue
  operation being exposed. A broad `WorkerAdapter` is still deferred until
  direct ARQ leakage proves it is needed.

Work:

- [x] Abort queued crawl.
- [ ] Abort running crawl.
- [ ] Retry now.
- [ ] Pause/resume scheduled crawl.
- [ ] Change update interval.
- [ ] Reset circuit breaker.
- [ ] Adjust safe crawler settings where already exposed by tenant settings.

Acceptance criteria:

- Every action has an audit event.
- Every action has a lifecycle transition.
- Unsafe cleanup is skipped after abort/partial termination.
- UI confirms destructive or high-impact actions.
- Errors are typed and actionable.
- Admin cannot unknowingly enable risky source-skip globally.

Deletion targets:

- Manual DB/Redis intervention instructions that become obsolete.

Tests:

- One behavior test per action and state combination.

## Scrapy Built-Ins To Prefer

Use Scrapy built-ins where they fit:

- `RobotsTxtMiddleware` / `ROBOTSTXT_OBEY` for robots compliance.
- `DOWNLOAD_MAXSIZE` and per-request size limits for large file protection.
- `AutoThrottle` for polite adaptive crawling.
- Retry settings for transient network failures.
- `CloseSpider` settings for hard crawl bounds.
- `SitemapSpider` hooks where public hooks are sufficient.

Do not expand custom Scrapy internals unless required for cleanup-visible retained source items. When custom overrides are needed, keep them narrow and covered by upstream-behavior smoke tests.

HTTP cache remains a separate proposal. It should not be expanded in this roadmap unless durable storage, tenant purge, size caps, TTL policy, and deployment ownership are decided.

## Admin UX Direction

User-facing output should be concise and specific:

- unchanged/retained counts are success, not hidden work,
- too-large file skips are explained with the configured limit,
- partial timeouts are warnings with preserved counts,
- no-pages failures include the most likely diagnostic fact from `CrawlDiagnostics`,
- unknown errors include an admin detail path, not a blank "unknown reason."

Admin detail should include:

- outcome code,
- job id,
- lifecycle state,
- cleanup policy,
- Scrapy request/response counts,
- HTTP status distribution,
- robots blocked count,
- downloader exception counts,
- file too-large count and capped samples,
- hash/source/file-retained counts,
- duration breakdown,
- last heartbeat/progress timestamp,
- next scheduled run,
- circuit breaker state,
- audit trail for manual actions.

## Edge Case Matrix

| Case | Expected behavior |
|---|---|
| 0 requests issued | Typed no-output diagnostic; no cleanup; no stuck syncing. |
| Robots blocks all requests | Typed no-pages outcome with robots diagnostic. |
| HTTP responses but no page items | Typed no-pages outcome with status distribution. |
| All pages unchanged by hash/model | Success outcome; no embedding calls; no blob/chunk writes; UI says retained/unchanged. |
| All sitemap URLs source-retained | Success/warning outcome; no downloads for retained URLs; cleanup protected. |
| Some changed, some retained, some failed, some removed | Changed persists; retained protected; failed protected; removed deleted only when source frontier complete. |
| Timeout with partial output | Persist output; skip stale cleanup; warning outcome. |
| Timeout with zero output | Failed timeout outcome; no cleanup; no stuck syncing. |
| Too-large files only | Completed with too-large-only outcome; UI explains file size limit. |
| Embedding config missing and content unchanged | Retain existing content; warn once per run. |
| Embedding model changed | Re-embed even if content hash matches. |
| Worker dies mid-batch | Retry/idempotency path does not double-write terminal state and does not double-spend beyond hash gate. |
| Worker dies after cleanup before finalize | Watchdog/lifecycle can recover to a truthful terminal state without unsafe cleanup replay. |
| Duplicate job enqueued | Non-error duplicate outcome; no string parsing; UI does not show failed unknown. |
| Admin aborts queued job | Queue job prevented; terminal aborted outcome; slot released. |
| Admin aborts running job | Running job aborted if supported; cleanup skipped; terminal aborted outcome; audit written. |
| Lastmod lies | Source-skip remains opt-in; hash gate remains correctness layer. |
| Historical row lacks outcome_code | Backfilled where known; otherwise safe historical unknown detail. |

## Time And Space Complexity

Rules:

- Store exact counts, not unlimited item lists.
- Store bounded samples only.
- Default admin recent-failure window: 7 days.
- Paginate all lists.
- Aggregate scheduled crawl risk by interval, tenant, space, website, and size buckets.
- Expose Redis/queue counts and age, not raw queue payloads.
- Keep source-retained URL samples capped even for 100k URL sitemaps.
- Avoid reading all crawl runs to render admin pages.

Expected complexity:

- Hash lookup remains O(existing blobs for website), which is acceptable because cleanup already needs existing titles.
- Retention counters are O(batch size).
- Admin overview should be O(active jobs + recent window + scheduled aggregate), never O(all historical crawls).
- File size diagnostics should rely on Scrapy stats/extensions rather than downloading large files to discover they are too large.

## Validation Commands

Use host tooling when available, or the devcontainer prefix when needed.

```bash
cd backend
uv run ruff check src tests
uv run pyright --project pyrightconfig.json
set -a; source .env.template; set +a; uv run pytest tests/unittests tests/integration -q
```

```bash
cd frontend
bun run --filter @intric/web i18n:compile
bun run --filter @intric/web test:unit
bun run --filter @intric/web check
bun run --filter @intric/web lint
```

Docker/devcontainer form:

```bash
docker exec eneocrawlerupdate_devcontainer-eneo-1 bash -lc 'cd /workspace/backend && uv run pyright --project pyrightconfig.json'
docker exec eneocrawlerupdate_devcontainer-eneo-1 bash -lc 'cd /workspace/backend && uv run pytest tests/unittests tests/integration -q'
docker exec eneocrawlerupdate_devcontainer-eneo-1 bash -lc 'cd /workspace/frontend && bun run --filter @intric/web check'
```

Each implementation PR/commit should record exactly which commands were run and what was not run.

## Rollout And Recovery

- Keep skip-reembedding behavior always on because it is content/model correctness based.
- Keep sitemap source-skip opt-in because it trusts upstream `<lastmod>`.
- Keep HTTP cache out of this roadmap until storage and purge policy are decided.
- Add admin visibility before admin mutation controls.
- Add abort/retry controls only after terminal events, lifecycle, and adapter are canonical.
- Keep historical outcome fallback only until backfill and generated frontend types are complete.
- If a new lifecycle path fails in production, prefer disabling the new path via feature/config flag over reverting unrelated skip-retention work.

## What Not To Do

- Do not add new raw-string `result_location` parsing.
- Do not add another outcome enum in the frontend.
- Do not expose every Scrapy setting to admins.
- Do not turn sitemap source-skip on globally by default.
- Do not store unlimited URL samples or raw Scrapy logs in crawl runs.
- Do not split `crawl_tasks.py` into many shallow pass-through files.
- Do not add broad `Any`, `dict[str, Any]`, or type ignores to get pyright green.
- Do not create broad `utils`, `helpers`, `manager`, or `processor` modules.

## External References

- ARQ supports custom job ids for uniqueness, job status/info/result, abort when enabled, retries/cancellation behavior, and Redis worker health checks: https://arq-docs.helpmanual.io/
- Scrapy settings include robots compliance, download max size, AutoThrottle, CloseSpider, downloader middleware, and HTTP cache integration points: https://docs.scrapy.org/en/latest/topics/settings.html
