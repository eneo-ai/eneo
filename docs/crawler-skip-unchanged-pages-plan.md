# Crawler Skip Unchanged Pages - Architecture Review And Implementation Plan

Branch: `feature/crawler-skip-unchanged-pages`

Status: implementation validation, Claude implementation re-review, and local commit are complete on this branch. Do not push from this branch unless explicitly requested.

Purpose: reduce embedding-token spend and database churn for scheduled website crawls by retaining URL blobs whose normalized page content hash has not changed, without weakening stale-cleanup correctness or crawl reliability.

## Implementation Progress

- [x] Architecture research, ChatGPT Pro review, Claude peer-loop review, and Scrapy/ARQ inspection.
- [x] Persistence value types, hash/model retention gate, and `PersistBatchResult`.
- [x] Crawl orchestration cleanup protection, file-skip alignment, and tenant-scoped deletes.
- [x] Safe fetch-skip plumbing using Scrapy `HttpCacheMiddleware` and `RFC2616Policy`, disabled by default until durable worker storage is configured.
- [x] Typed backend crawl/job failure details suitable for frontend display.
- [x] Frontend-visible crawl/job failure states.
- [x] Targeted tests, strict pyright, ruff, and regression validation.
- [x] Claude peer-loop implementation review.
- [x] Local commit only; do not push from this branch.

## User Impact

The first implemented slice still fetches pages, but it improves the parts users are most likely to feel in cost, runtime, and reliability:

- Much lower embedding cost: scheduled crawls embed only changed or new pages instead of every page.
- Less crawl failure from embedding/model/provider issues: unchanged pages can be retained without entering the embedding path.
- Less database churn: unchanged pages skip blob/chunk delete-and-insert work.
- Better correctness foundation: the implementation makes persisted, retained, failed, and stale page states explicit before source-level fetch skipping is added.
- No user-visible behavior regression: changed pages still update, deleted pages still delete, failed pages remain protected, tenant scoping is tightened, and existing file-skip behavior becomes safer through embedding-model compatibility.

## Review Inputs

Sources used in this plan:

- Local code inspection in `/Users/ccimen/eneo/eneocrawlerupdate`.
- `karpathy-guidelines` skill: surgical scope, explicit assumptions, no speculative abstractions, verifiable success criteria.
- `improve-codebase-architecture` skill: Module, Interface, Implementation, Depth, Seam, Adapter, Leverage, and Locality vocabulary. No repo `CONTEXT.md` or ADR folder was found in this checkout, so this review is code-evidence based.
- Host Claude peer-loop wrapper, `claude-opus-4-7`, `xhigh`, blocking skepticism.
- ChatGPT Extended Pro review supplied by the user.
- Scrapy official documentation for `HttpCacheMiddleware`, `RFC2616Policy`, `SitemapSpider.sitemap_filter()`, and `JOBDIR`/dupefilter persistence.

Claude artifact:

- `.codex/artifacts/claude-peer-loop-crawler-skip-unchanged-pages-architecture-review-20260511T081955Z.md`
- `.codex/artifacts/claude-peer-loop-crawler-skip-unchanged-pages-plan-verification-20260511T082447Z.md`
- `.codex/artifacts/claude-peer-loop-crawler-failure-ux-plan-addendum-review-20260511T083044Z.md`
- `.codex/artifacts/claude-peer-loop-crawler-hash-skip-chatgpt-pro-feedback-review-20260511T092043Z.md`
- `.codex/artifacts/claude-peer-loop-crawler-hash-skip-revised-plan-verification-20260511T093336Z.md`
- `.codex/artifacts/claude-peer-loop-crawler-hash-skip-chatgpt-pro-refinements-verification-20260511T102437Z.md`
- `.codex/artifacts/claude-peer-loop-crawler-skip-unchanged-pages-implementation-review-20260511T114454Z.md`
- `.codex/artifacts/claude-peer-loop-crawler-skip-unchanged-pages-implementation-re-review-20260511T120343Z.md`

Claude loop summary:

- Initial plan review: `changes_required`, `MIN_SCORE: 6`.
- Revised plan review: `green`, `MIN_SCORE: 8`.
- Failure UX addendum review: `green`, `MIN_SCORE: 8`.
- ChatGPT Pro feedback review: `changes_required`, `MIN_SCORE: 5`, because the plan was missing embedding-model compatibility in the retain predicate.
- Revised plan verification after incorporating ChatGPT Pro and Claude blockers: `green`, `GREEN_LIGHT: yes`, `MIN_SCORE: 8`.
- ChatGPT Pro refinements verification: `green`, `GREEN_LIGHT: yes`, `MIN_SCORE: 8`.
- Initial implementation review: `changes_required`, `GREEN_LIGHT: no`, `MIN_SCORE: 6`.
- Implementation re-review after closing blockers: `green`, `GREEN_LIGHT: yes`, `MIN_SCORE: 8`.

Claude agreed with the core architecture:

- `persist_batch()` is the right canonical owner for URL hash matching.
- A typed result is better than extending the current 4-tuple.
- The hash prepass should happen before embedding-service setup.
- ChatGPT Pro correctly identified that stored embeddings are only reusable when both `content_hash` and `embedding_model_id` are compatible with the current crawl.

Claude blocked on these plan gaps, now incorporated below:

- Current-slice observability must be concrete: do not overload `failure_summary`.
- all-unchanged batches with broken embedding configuration need a structured warning, or operator alarms become silent.
- cleanup retention testing is required, not optional.
- tuple-to-result migration touches more tests than the original plan listed.
- internal failure tracking should use `FailureReason`, not raw strings.
- cleanup protection should be named as cleanup protection, not "retained" twice.
- skip compatibility must compare stored `embedding_model_id` as well as `content_hash`.
- existing file hash skipping must be aligned with the new URL/page retain predicate.
- `PersistBatchResult` counts must be computed from collections, not stored as redundant fields.
- mutating delete queries in the crawl path should include `tenant_id` with `website_id` and title.
- Current-slice tenant-delete scope should be explicit: include page replacement, stale cleanup, and same-title website file replacement because all three are local to the crawl path.
- tests should assert model-change replacement writes the current `embedding_model_id` and should cover the `ExistingBlobState.is_current_for()` truth table.

## Executive Recommendation

Implement the hash gate inside `backend/src/intric/worker/crawl/persistence.py`, because that module already owns the current page persistence Interface:

- compute page content hash,
- split text into chunks,
- call the embedding model,
- delete old URL blobs,
- insert replacement blobs and chunks,
- report persisted and failed URLs back to the crawl task.

This is a deep Module: callers should not need to know the ordering details of hash comparison, embedding setup, and DB writes. Moving the hash gate into `crawl_tasks.py` would make the orchestration layer remember too much about the persistence Implementation and would make the stale-cleanup bug easier to reintroduce.

Do not implement sitemap `<lastmod>` filtering in this implementation slice. The current cleanup logic treats "not returned by the processing loop" as stale. Filtering URLs out before persistence would make unchanged pages look deleted and risks silent data loss.

The current implementation shape is:

1. Load existing blob titles, hashes, and embedding model ids during crawl bootstrap.
2. Pass the existing blob-state map into `persist_batch()`.
3. In `persist_batch()`, compare SHA-256 and stored `embedding_model_id` before chunking, embedding, and embedding-service setup.
4. Use the same blob-state compatibility predicate for existing file skipping.
5. Return a typed `PersistBatchResult` with `persisted_urls`, `retained_urls`, and `failures_by_reason`; counts are computed properties.
6. In `crawl_tasks.py`, protect `batch_result.cleanup_protected_titles` from stale cleanup.
7. Wire Scrapy HTTP cache support through the existing crawler settings as an optional disabled-by-default fetch optimization.
8. Track unchanged page/file skip counts in structured logs, the human summary log, performance extras, and audit metadata.
9. Do not write hash skips to `failure_summary` in this implementation slice.

Related reliability/UX requirement:

- Crawl and job failures should be understandable from the frontend. The current hash-skip slice must not make this worse, and a follow-up error-contract slice should make backend failure reasons typed, localized, and visible in the website list and crawl history instead of relying on silent logs or raw `result_location` text.

## Implementation Naming And Commit Strategy

- Do not use phase labels such as `v1`, `v1_5`, or `v2` in code names, schema names, logs, metrics, enum values, comments, or tests.
- Use domain names that describe behavior: `ExistingBlobState`, `_PageToEmbed`, `PersistBatchResult`, `must_keep_titles`, `cleanup_protected_titles`, and `_compute_stale_titles`.
- Keep all work on `feature/crawler-skip-unchanged-pages`, but split implementation into clear commits:
  1. persistence hash/model retention and page tests,
  2. crawl orchestration cleanup/file-skip alignment and tenant-scoped deletes,
  3. observability/test cleanup,
  4. optional follow-up commit for failure UX contracts only if we deliberately pull that into scope.

## Hard Current-Slice Decisions

### 1. Observability

Decision:

- Do not add `HASH_MATCH_SKIPPED` to `FailureReason`.
- Do not write unchanged-page skips into `failure_summary`.
- Do track `pages_hash_skipped` in logs and audit metadata.

Reason:

- `backend/src/intric/database/tables/websites_table.py:24-28` documents `failure_summary` as failure reason counts.
- A hash match is a successful retention outcome, not a failure.
- Overloading a failure-shaped public contract would make frontend/user reporting misleading.

Follow-up:

- If product needs crawl-history API visibility for skipped unchanged pages, add a real schema/API field such as `pages_skipped_unchanged` or a broader `outcome_summary`. That should be a separate slice.

### 2. All-Unchanged Batches And Broken Embedding Configuration

Decision:

- If all pages in a batch are unchanged, `persist_batch()` should not require an embedding model or provider.
- Changed or new pages still require valid embedding configuration and fail as today when it is missing.
- If `embedding_model is None` or provider id is missing, and the crawl retained pages/files but has no changed/new pages/files to embed, emit one structured warning per crawl:

```text
reason="embedding_misconfigured_but_no_changes"
website_id=<website_id>
tenant_id=<tenant_id>
retained_count=<count>
```

Emit site:

- Derive and emit this warning in `crawl_tasks.py` after page/file processing, not inside `persist_batch()`.
- The result contract should not grow a warning flag for this; `crawl_tasks.py` already has run-level visibility into retained page/file counts and embedding configuration.

Reason:

- No embedding call is needed for unchanged content, so requiring embedding setup would preserve an avoidable failure mode.
- However, without a warning, a stable website with broken embedding config would stop alerting operators. The warning preserves observability without failing a valid retention-only run.

### 3. Stored Blob Compatibility

Decision:

- Do not pass `dict[str, bytes]` as the retention input.
- Pass a typed stored-blob state that includes both `content_hash` and `embedding_model_id`.
- Reuse the same compatibility predicate for URL pages and files.

Recommended shape:

```python
from uuid import UUID


@dataclass(frozen=True, slots=True)
class ExistingBlobState:
    content_hash: bytes
    embedding_model_id: UUID | None

    def is_current_for(
        self,
        *,
        content_hash: bytes,
        embedding_model_id: UUID | None,
    ) -> bool:
        if self.content_hash != content_hash:
            return False
        if embedding_model_id is None:
            return True
        return self.embedding_model_id == embedding_model_id
```

Reason:

- Embeddings are a function of content and embedding model, not content alone.
- If a website changes embedding model, retaining hash-matched old vectors would silently keep stale vectors and make the crawl look successful.
- `InfoBlobs` already stores `embedding_model_id`, so this safety check needs no schema migration.
- `embedding_model_id is None` represents a missing current embedding config. In that case, retaining identical content is acceptable because there is no current model to compare against, but the run-level structured warning must fire.

Future:

- A durable `processing_fingerprint` should eventually include embedding model, chunking version, text normalization version, and embedding dimensions. For the current slice, `embedding_model_id` is the minimum available fingerprint.

### 4. Result Contract

Decision:

- Replace the current 4-tuple return with `PersistBatchResult`.
- Do not add tuple backward compatibility via `__iter__`; that would create two Interfaces for one value.
- Store URL/failure collections as the source of truth. Counts must be computed properties so they cannot drift from the collections.

Recommended shape:

```python
from dataclasses import dataclass, field
from itertools import chain


@dataclass(frozen=True)
class PersistBatchResult:
    """Result of persist_batch; separates persisted, retained, and failed URLs."""

    persisted_urls: tuple[str, ...] = ()
    retained_urls: tuple[str, ...] = ()
    failures_by_reason: dict[FailureReason, tuple[str, ...]] = field(
        default_factory=dict
    )

    @property
    def persisted_count(self) -> int:
        return len(self.persisted_urls)

    @property
    def retained_count(self) -> int:
        return len(self.retained_urls)

    @property
    def failed_count(self) -> int:
        return sum(len(urls) for urls in self.failures_by_reason.values())

    @property
    def failed_urls(self) -> frozenset[str]:
        return frozenset(chain.from_iterable(self.failures_by_reason.values()))

    @property
    def cleanup_protected_titles(self) -> frozenset[str]:
        return frozenset(self.persisted_urls) | frozenset(self.retained_urls)
```

Reason:

- `persisted_urls` means new DB state was written.
- `retained_urls` means existing DB state is intentionally kept because the hash matched.
- `cleanup_protected_titles` means stale cleanup must not delete these titles.
- `failed_urls` makes the cleanup exclusion explicit at the call site.
- Computed counts prevent `persisted_count`, `retained_count`, `failed_count`, and `failures_by_reason` from drifting apart.
- Tuple values are the important immutability contract. Use a normal dict for clean strict-pyright behavior; do not spend complexity budget on runtime read-only wrappers.
- Callers must treat `failures_by_reason` as read-only. Full dict immutability is intentionally not pursued because it creates more typing noise than reliability value here.
- These are three different concepts; one tuple named `successful_urls` is too easy to misuse.

### 5. Failure Reason Typing

Decision:

- Use `dict[FailureReason, list[str]]` internally while building a batch result.
- Freeze internal `list[str]` buckets to tuple values in `PersistBatchResult`.
- Convert to JSON-safe strings only at the crawl-run persistence boundary.

Reason:

- This gives pyright a chance to catch mistyped failure reasons.
- The returned result avoids mutable failure URL lists while keeping the type simple for strict pyright and tests.
- `failure_summary` remains a JSONB/string boundary concern in `crawl_tasks.py`, not a persistence-internal contract.
- If strict pyright rejects `field(default_factory=dict)` for `failures_by_reason`, use a typed `_empty_failures() -> dict[FailureReason, tuple[str, ...]]` helper rather than `cast`.

### 6. Comments And AI-Slop Guard

Decision:

- No new `Any`, `cast`, `type: ignore`, or broad dict bags.
- No new interface, protocol, factory, adapter, or service.
- `PersistBatchResult` gets a one-line docstring only.
- Add small private dataclasses/functions only when they protect a named crawl rule, not for generic reuse.
- New code should rely on precise names rather than tutorial comments.
- Do not add "Phase 1.5", "magic", or TODO comments.

Reason:

- The existing crawler is already long and comment-heavy. This change should improve Locality and reviewability, not add prose noise.

## Current Findings

### 1. Sitemap Crawls Fetch Every URL Every Scheduled Run

Evidence:

- The card identifies `backend/src/intric/crawler/spiders/sitemap_spider.py:10-34` as a vanilla Scrapy spider with no `sitemap_filter()` override.

Problem:

- Every scheduled sitemap crawl downloads and parses all URLs.

Decision:

- Leave this alone in the current slice. Filtering here is too early because cleanup currently does not know that filtered URLs were still present in the source.

Future canonical owner:

- Sitemap fetch/filter policy belongs in the crawler source-enumeration Module, but only after cleanup bookkeeping is split into `seen_in_source`, `fetched`, and `persisted_or_retained`.

### 2. Page Persistence Computes The Right Hash But Does Not Compare It

Evidence:

- `backend/src/intric/worker/crawl/persistence.py:82-129` defines `persist_batch()` as the two-phase page persistence function.
- `backend/src/intric/worker/crawl/persistence.py:214-235` computes `content_hash = hashlib.sha256(content.encode("utf-8")).digest()`.
- `backend/src/intric/worker/crawl/persistence.py:268-278` calls the embedding API.
- `backend/src/intric/worker/crawl/persistence.py:381-389` deletes the existing blob by `(title, website_id)`.
- `backend/src/intric/worker/crawl/persistence.py:391-433` inserts the blob and chunks again.

Problem:

- The expensive embedding call and delete/insert churn happen even when the content hash matches the already stored blob.

Canonical owner:

- `persist_batch()` should own the unchanged-page gate because it already has the required knowledge: hash, embedding, and write semantics.

### 3. Bootstrap Fetches Hashes But Excludes URLs And Embedding Model State

Evidence:

- `backend/src/intric/worker/crawl_tasks.py:912-923` selects `(InfoBlobs.title, InfoBlobs.content_hash)` for the website.
- `backend/src/intric/worker/crawl_tasks.py:921-923` only stores hashes when `not title.startswith("http")`, so URL hashes are excluded.
- `backend/src/intric/worker/crawl_tasks.py:1140-1161` uses the existing hash map to skip unchanged files, but currently compares content hash only.
- `backend/src/intric/database/tables/info_blobs_table.py:37-39` stores `embedding_model_id` on `InfoBlobs`.

Problem:

- The data needed for URL retention already exists but is deliberately limited to file names.
- Existing file skipping has the same hidden correctness gap that ChatGPT Pro identified for URL pages: unchanged content with a changed embedding model should be reprocessed, not retained.

Likely history:

- File skip landed first, while URL `content_hash` reliability was treated as future deduplication. `backend/src/intric/worker/crawl_context.py:160` still says `content_hash: bytes  # SHA-256 for change detection (future deduplication)`.

Intended change:

- Replace `existing_file_hashes` with `existing_blob_state_by_title`.
- Include URL titles and file titles in the same state map.
- Query `InfoBlobs.embedding_model_id` alongside title and hash.
- Add `InfoBlobs.tenant_id == crawl_context.tenant_id` to the bootstrap query.
- Ignore `title is None` rows to keep the map type honest.
- Ignore `content_hash is None` for the state map because a nullable hash cannot prove content compatibility.

Bootstrap sketch:

```python
stmt = sa.select(
    InfoBlobs.title,
    InfoBlobs.content_hash,
    InfoBlobs.embedding_model_id,
).where(
    InfoBlobs.website_id == params.website_id,
    InfoBlobs.tenant_id == crawl_context.tenant_id,
)
...
if title is None:
    continue
existing_titles.append(title)
if hash_bytes is not None:
    existing_blob_state_by_title[title] = ExistingBlobState(
        content_hash=hash_bytes,
        embedding_model_id=embedding_model_id,
    )
```

Note:

- `InfoBlobs.title` is nullable at `backend/src/intric/database/tables/info_blobs_table.py:18`.
- `InfoBlobs.content_hash` is nullable at `backend/src/intric/database/tables/info_blobs_table.py:21-24`.
- Current stale cleanup cannot match NULL titles through `title.in_(stale_titles)` anyway, so ignoring NULL titles preserves current behavior rather than introducing a new cleanup policy.

### 4. Cleanup Is The Correctness Trap

Evidence:

- `backend/src/intric/worker/crawl_tasks.py:960-962` initializes `crawled_titles` and `failed_titles`.
- `backend/src/intric/worker/crawl_tasks.py:1082` and `backend/src/intric/worker/crawl_tasks.py:1113` add only `successful_urls` returned from `persist_batch()` to `crawled_titles`.
- `backend/src/intric/worker/crawl_tasks.py:1206-1213` deletes existing titles that are not in `crawled_titles` and not in `failed_titles`.

Problem:

- If unchanged pages are skipped inside Phase 1 but not marked cleanup-protected, cleanup deletes them as stale.

Intended change:

```python
from collections.abc import Collection, Iterable


def _compute_stale_titles(
    *,
    existing_titles: Iterable[str],
    must_keep_titles: Collection[str],
    failed_titles: Collection[str],
) -> list[str]:
    return [
        title
        for title in existing_titles
        if title not in must_keep_titles and title not in failed_titles
    ]
```

Recommended rename:

- Rename `crawled_titles` to `must_keep_titles` in the current slice. This name better matches the actual cleanup semantics after this change.
- Keep `batch_result.cleanup_protected_titles` as the persistence result property, then feed it into orchestration state with `must_keep_titles.update(...)`.

Reason:

- Cleanup needs "must keep", not "was fetched" and not "was inserted".
- `_compute_stale_titles()` is allowed because it names the P0 business rule and gives the cleanup safety predicate one direct production test surface. Keep it private and local to `crawl_tasks.py`; do not create a generic helper module.

### 5. Current Failure Tracking Should Not Be Polluted By Skip-As-Failure

Evidence:

- `backend/src/intric/worker/crawl_context.py:16-39` defines `FailureReason` for real page persistence failures.
- `backend/src/intric/database/tables/websites_table.py:19-28` stores `failure_summary` as JSONB failure counts.
- `backend/src/intric/worker/crawl_tasks.py:1392-1407` stores `failure_summary` on the crawl run.

Problem:

- `HASH_MATCH_SKIPPED` is not a failure. Putting it into `failure_summary` would make the public contract easier to surface but less truthful.

Decision:

- The current slice uses logs and audit metadata only.
- API/UI visibility is a follow-up with an explicit success/skip outcome field.

### 6. All-Unchanged Batches Should Not Open The Embedding Session

Evidence:

- `backend/src/intric/worker/crawl/persistence.py:145-166` currently fails the whole page buffer early if the embedding model is missing or missing provider data.
- `backend/src/intric/worker/crawl/persistence.py:174-193` opens an embedding session and creates the embedding service before processing pages.

Problem:

- If every page in a batch is unchanged, no embedding call is needed. Requiring embedding setup preserves an avoidable failure path.

Intended behavior:

- Do a lightweight prepass inside `persist_batch()`:
  - reject empty content as today,
  - compute SHA-256,
  - compare against `existing_blob_state_by_title`,
  - collect retained URLs,
  - collect changed/new pages for chunking and embedding.
- Only validate/create the embedding service if at least one page needs embedding.
- If config is missing and every non-empty page was retained, return retained results without embedding setup; `crawl_tasks.py` emits the run-level `embedding_misconfigured_but_no_changes` warning after it sees the whole crawl.

### 7. Tenant-Scoped Website Delete Gaps Are Local Enough For This Slice

Evidence:

- `backend/src/intric/worker/crawl/persistence.py:381-389` deletes page blobs by title and website only during changed-page replacement.
- `backend/src/intric/info_blobs/info_blob_repo.py:371-377` deletes same-title website blobs by title and website only.
- `backend/src/intric/info_blobs/info_blob_service.py:133-136` calls that method for website file replacement and already has `InfoBlobAdd.tenant_id`.
- `backend/src/intric/info_blobs/info_blob_repo.py:558-583` batch-deletes stale website blobs by titles and website only.
- `backend/src/intric/worker/crawl_tasks.py:1223-1225` calls stale cleanup from a crawl context that already has `tenant_id`.

Decision:

- Include tenant-scoped predicates for these website crawl delete paths in the current slice. The signature changes are local and prevent the page path, file path, and stale-cleanup path from having different tenant guarantees.

### 8. Old Hash-Only Repository Helper Should Not Survive If Unused

Evidence:

- `backend/src/intric/info_blobs/info_blob_repo.py:585-602` defines `get_content_hash(website_id, title)`, which returns only `content_hash` and has no tenant predicate.
- `rg -n "get_content_hash\\(" backend/src backend/tests` currently finds no callers outside that definition.

Decision:

- Delete this helper in the current slice if it is still unused during implementation.
- If a caller appears, replace the helper with a tenant-scoped stored-blob-state lookup that returns both `content_hash` and `embedding_model_id`.

Reason:

- Leaving an unused hash-only lookup behind is a low-grade future footgun; it points future changes back toward the exact content-only predicate this plan is avoiding.

### 9. Scrapy Built-Ins Help Later, But Do Not Replace The Current Slice

Evidence:

- `backend/src/intric/crawler/crawler.py:212-234` creates a `CrawlerRunner` with feed, close spider, autothrottle, robots, size, timeout, DNS, and retry settings. It does not currently enable Scrapy HTTP cache settings.
- Scrapy's official `HttpCacheMiddleware` provides low-level HTTP request/response caching and can be combined with storage backends and cache policies.
- Scrapy's `RFC2616Policy` is explicitly aimed at production continuous runs and can revalidate stale responses using `Last-Modified` and `ETag`.
- Scrapy's default cache storage is filesystem-based, with DBM also available; Scrapy also allows custom cache storage.
- Scrapy's `SitemapSpider` supports overriding `sitemap_filter(entries)` and the official example filters by `entry["lastmod"]`.
- Scrapy's `JOBDIR` persists scheduler, duplicate-filter, and spider state for pausing/resuming a single job, and the docs warn the job directory must not be shared by different spiders or different jobs of the same spider.

Decision:

- Wire Scrapy `HttpCacheMiddleware` + `RFC2616Policy` as optional crawler settings in the current branch, but keep it disabled by default.
- Treat this as fetch-skip plumbing, not the correctness mechanism. Persistence hash/model retention remains the gate that prevents re-embedding and stale cleanup loss.
- Do not use Scrapy `JOBDIR` or the duplicate filter as the scheduled-crawl skip mechanism. They are for duplicate request filtering and pause/resume state, not for "source still contains this URL, retain its blob" semantics.
- Do not use `SitemapSpider.sitemap_filter()` for `<lastmod>` skipping until crawl bookkeeping distinguishes `seen_in_source`, `fetched`, and `persisted_or_retained`.

Reason:

- Scrapy HTTP cache can reduce network transfer when origins return cacheable responses or `304 Not Modified`, but production use still needs a durable tenant-scoped cache location. The branch scopes cache directories by tenant and website and adds TTL/size settings; deployment should only enable it when the configured directory survives worker restarts as intended and has an operational purge path.
- Even with HTTP cache, the spider can still emit a cached response body. Without the persistence hash gate, unchanged cached pages would still be re-embedded and rewritten.
- `sitemap_filter()` can skip request creation, which is exactly why it collides with current stale cleanup: skipped URLs would not naturally reach `must_keep_titles`.

Fetch-skip follow-up shape:

1. Keep hash/model retention as the correctness gate.
2. Split crawl bookkeeping into `seen_in_source`, `fetched`, and `persisted_or_retained`.
3. Enable the already-wired tenant/website-scoped Scrapy HTTP cache only where the cache directory is durable enough for scheduled crawls.
4. Prefer origin-provided `ETag` / `Last-Modified` revalidation over trusting sitemap `<lastmod>`.
5. Add sitemap `<lastmod>` only as a conservative fetch hint after source bookkeeping can retain present-but-not-fetched URLs safely.

### 10. Backend-To-Frontend Failure Visibility Is Partial

Evidence:

- `backend/src/intric/websites/presentation/website_models.py:70-78` exposes `pages_failed`, `files_failed`, `failure_summary`, `status`, `result_location`, and `finished_at` on `CrawlRunPublic`.
- `backend/src/intric/websites/crawl_dependencies/crawl_models.py:20-25` also exposes `failure_summary` for crawl run API models.
- `backend/src/intric/worker/crawl_context.py:16-39` defines typed page persistence failure reasons, but these are stored as a count map only.
- `backend/src/intric/worker/crawl_tasks.py:1392-1407` writes `failure_summary` to the crawl run.
- `backend/src/intric/jobs/job_service.py:48-55` stores uncaught job failure text in `Jobs.result_location`.
- `backend/src/intric/jobs/job_repo.py:83-107` has a dead `error_message` parameter in `mark_job_failed_if_running()`: the docstring says it stores an error message, but the update statement sets only `status` and `updated_at`.
- `frontend/apps/web/src/routes/(app)/spaces/[spaceId]/knowledge/websites/[id]/CrawlResultCell.svelte:16-43` maps `failure_summary` codes to translated labels and shows them in a tooltip.
- `frontend/apps/web/src/routes/(app)/spaces/[spaceId]/knowledge/websites/WebsiteStatus.svelte:43-88` mostly shows high-level status/counts and raw `result_location` for failed/skipped runs, not a structured failure breakdown.
- The frontend has divergent string contracts for skipped crawls: `WebsiteStatus.svelte:15` and `CrawlResultCell.svelte:14` use `"skipped duplicate crawl"`, while `CrawlRunsTable.svelte:21` uses `"skipped"`.

Problem:

- Page-level persistence failures have typed counts, but no page samples or recommended user action.
- Job-level failures are stored as free-text `result_location`, so the frontend cannot reliably translate or group them.
- Some failure paths can be silent or low-information from the user perspective.
- The website list, website detail page, and crawl-run history do not share one canonical presentation model for crawl failure reasons.
- `result_location` carries successful result URLs, duplicate-skip text, and arbitrary failure text, so its type no longer communicates what the frontend can safely render.

Canonical owner:

- Backend should own typed crawl/job failure contracts.
- Frontend should own localized labels, severity, and recovery copy for those typed contracts.
- `result_location` should not be the long-term owner of human-visible error semantics; it is currently carrying both URLs and failure text.

Decision for this hash-skip slice:

- Do not broaden this slice into a full backend/frontend failure-contract refactor.
- Do not add hash skips to `failure_summary` as a workaround for visibility.
- Do make the new misconfigured-retained warning structured in logs.
- Do include `pages_hash_skipped` in audit metadata, but treat public skip/error API visibility as a follow-up.

Recommended follow-up slice:

1. Add a typed crawl failure/outcome contract that separates:
   - page persistence failure counts,
   - job-level failure code,
   - user-safe message key,
   - optional technical detail for admins,
   - suggested recovery action,
   - sampled affected URLs or titles with a cap.
2. Stop using raw `result_location` as the frontend error source.
3. Ensure every terminal failure path writes either a typed job failure code or a typed crawl failure summary.
4. Make the frontend render the same failure summary in:
   - website list status,
   - website detail crawl history,
   - crawl result cell/tooltips,
   - manual crawl retry feedback.
5. Add i18n keys for all typed reasons and keep unknown codes visible but clearly marked.

Potential first backend codes, split by level:

Page persistence reason codes already exist as `FailureReason`:

- `EMPTY_CONTENT`
- `NO_CHUNKS`
- `EMBEDDING_TIMEOUT`
- `EMBEDDING_ERROR`
- `DB_ERROR`
- `NO_EMBEDDING_MODEL`
- `MISSING_PROVIDER`

Potential crawl/job-level outcome codes:

- `CRAWL_NO_PAGES_RETURNED`
- `SITEMAP_NOT_FOUND`
- `SITEMAP_MALFORMED`
- `HTTP_AUTH_DECRYPTION_FAILED`
- `CRAWL_HEARTBEAT_FAILED`
- `CRAWL_PREEMPTED`
- `CRAWL_DUPLICATE_SKIPPED`
- `CRAWL_MAX_AGE_EXCEEDED`

Minimum viable follow-up contract:

- typed crawl/job outcome code,
- bounded sample list when a page-level failure needs examples,
- existing frontend i18n maps for user-facing labels.

Defer until later:

- detailed recovery-action copy,
- admin-only technical details,
- broad redesign of crawl history.

Acceptance criteria for the follow-up:

- Failed crawl history rows show a translated reason, not only "Crawl failed".
- Website list status shows a concise translated failure reason and count when available.
- Admin/debug detail remains available without exposing secrets.
- Unknown backend reason codes render safely as "Unknown crawl error" plus the raw code for support.
- Duplicate crawl skips are not represented as failed in the UI language.
- Backend tests prove every terminal crawl failure path stores a typed reason.
- Frontend tests prove `failure_summary` and job-level failure codes render understandable text.
- Frontend tests prove skipped crawl classification is driven by typed code, not string prefixes.

### 11. ARQ Layer Does Not Need Hash-Retention Changes

Evidence:

- `backend/src/intric/worker/arq.py:20-43` only exposes configured worker functions, cron jobs, Redis settings, timeouts, and lifecycle hooks from `Worker`.
- `backend/src/intric/worker/routes.py:80-91` registers crawl as `@worker.long_running_function()`.
- `backend/src/intric/worker/worker.py:314-407` shows `long_running_function()` intentionally creates a sessionless container and leaves the long-running task to manage its own short-lived DB sessions.
- `backend/src/intric/worker/crawl_tasks.py:328-345` creates `TaskManager` with `job_service=None` and documents that crawl status is handled inside `crawl_task`.
- `backend/src/intric/worker/crawl_tasks.py:1565-1599` completes crawl jobs with an explicit session-per-operation update and then sets `_job_already_handled`.
- `backend/src/intric/jobs/job_repo.py:83-109` has `mark_job_failed_if_running(error_message)`, but the current update does not persist `error_message`; `backend/src/intric/jobs/job_service.py:48-55` does persist ordinary failure text through `result_location`.

Decision:

- No ARQ worker setting change is needed for hash/model retention.
- Do not put crawl skip or cleanup semantics in `backend/src/intric/worker/arq.py`; it is a worker registration/configuration Module, not the crawl persistence owner.
- Crawl error-reporting improvements should be made in `crawl_task` / crawl-run and job persistence, because crawl jobs bypass the generic `TaskManager` success/failure path.
- Track the `mark_job_failed_if_running(error_message)` mismatch in the failure-UX follow-up unless this branch deliberately includes the typed crawl/job outcome work.

Reason:

- ARQ schedules and runs the job, but the retained/persisted/failed/stale distinctions are crawl-domain semantics. Putting them at the ARQ layer would reduce Locality and make the behavior harder to test.

## Intended Implementation

### Step 1: Add Persistence Value Types - [x] Complete

File:

- `backend/src/intric/worker/crawl/persistence.py`

Reason:

- These types belong to the page persistence Module because they describe whether existing persisted blob state is reusable during persistence.
- Putting them in `crawl_context.py` would make crawl context carry operation-specific persistence contracts.

Do:

- Add `ExistingBlobState` for stored blob compatibility.
- Add private `_PageToEmbed` for the hash prepass:

```python
@dataclass(frozen=True, slots=True)
class _PageToEmbed:
    url: str
    content: str
    content_hash: bytes
```

- Use `tuple[str, ...]` for URL collections.
- Use `dict[FailureReason, list[str]]` internally.
- Freeze returned failure buckets to tuple values.
- Add computed count properties to `PersistBatchResult`.
- Add `failed_urls` and `cleanup_protected_titles` properties.
- Add a one-line docstring.

Do not:

- Add `__iter__` tuple compatibility.
- Add a new file for this type.
- Store redundant count fields.
- Carry loose `(page_data, content_hash)` tuples or dict bags through the prepass.

### Step 2: Build The Stored Blob State Lookup - [x] Complete

File:

- `backend/src/intric/worker/crawl_tasks.py`

Change:

- Rename `existing_file_hashes` to `existing_blob_state_by_title`.
- Query `InfoBlobs.title`, `InfoBlobs.content_hash`, and `InfoBlobs.embedding_model_id` with both website and tenant predicates.
- Add all non-null-title existing rows to `existing_titles`.
- Add rows with non-null title and non-null hash to `existing_blob_state_by_title`, including URL titles and file titles.
- Continue using the same state map for file skip checks by file name.
- Consider extracting a local pure `_build_existing_blob_lookup()` only if it keeps the bootstrap path readable and makes null/title/model handling directly testable.

Potential review concern:

- Adding the tenant predicate is likely planner-neutral because `website_id` should already imply tenant ownership and is indexed. If possible, check EXPLAIN in the real database before merging. If not possible locally, call it out as unverified but low risk.

### Step 3: Move Hash Comparison Before Embedding Setup - [x] Complete

File:

- `backend/src/intric/worker/crawl/persistence.py`

Function signature:

```python
async def persist_batch(
    page_buffer: list[CrawlPageData],
    ctx: CrawlContext,
    embedding_model: EmbeddingModelSpec | None,
    container: "Container",
    existing_blob_state_by_title: Mapping[str, ExistingBlobState] | None = None,
) -> PersistBatchResult:
```

Algorithm:

1. If `page_buffer` is empty, return an empty result.
2. Initialize `retained_urls`, `pages_to_embed: list[_PageToEmbed]`, and typed failure map.
3. For each page:
   - trim-check empty content and record `FailureReason.EMPTY_CONTENT` as today,
   - compute `content_hash`,
   - load `existing_blob_state_by_title.get(url)`,
   - retain only when `existing_state.is_current_for(content_hash=content_hash, embedding_model_id=ctx.embedding_model_id)`,
   - if content matches but stored `embedding_model_id` differs from the current model, treat the page as changed and re-embed,
   - if not compatible, append `_PageToEmbed(url=url, content=content, content_hash=content_hash)`.
4. If `pages_to_embed` is empty:
   - return retained result without creating the embedding session.
5. If `pages_to_embed` is non-empty:
   - validate embedding config as today,
   - create embedding service/session as today,
   - chunk/embed/write only changed/new pages,
   - convert each `_PageToEmbed` into the existing `PreparedPage` after chunking and embedding.
6. Keep the existing `assert embedding_model_id is not None` on the changed/new branch only.

Do not:

- Query the database per page.
- Add retained URLs to `PreparedPage`.
- Delete/reinsert chunks for retained URLs.
- Put retained URLs in failure tracking.

### Step 4: Align Existing File Skip With Blob Compatibility - [x] Complete

File:

- `backend/src/intric/worker/crawl_tasks.py`

Current concept:

```python
existing_file_hash = existing_file_hashes.get(filename)
if existing_file_hash is not None and existing_file_hash == new_file_hash:
    num_skipped_files += 1
    crawled_titles.add(filename)
    continue
```

Intended concept:

```python
existing_state = existing_blob_state_by_title.get(filename)
if existing_state is not None and existing_state.is_current_for(
    content_hash=new_file_hash,
    embedding_model_id=crawl_context.embedding_model_id,
):
    num_skipped_files += 1
    must_keep_titles.add(filename)
    continue
```

Reason:

- File and URL retention should share one definition of "existing blob is current".
- Without this change, a website embedding-model change would re-embed unchanged pages but keep stale file vectors.

### Step 5: Feed Cleanup Protection From The Result - [x] Complete

File:

- `backend/src/intric/worker/crawl_tasks.py`

Current concept:

```python
crawled_titles.update(successful_urls)
```

Intended concept:

```python
must_keep_titles.update(batch_result.cleanup_protected_titles)
failed_titles.update(batch_result.failed_urls)
```

Stale cleanup becomes:

```python
stale_titles = _compute_stale_titles(
    existing_titles=existing_titles,
    must_keep_titles=must_keep_titles,
    failed_titles=failed_titles,
)
```

This preserves:

- changed pages: persisted and protected,
- unchanged pages: retained and protected,
- failed pages: protected by `failed_titles`,
- removed pages: deleted as stale.

### Step 6: Tenant-Scope Mutating Deletes In The Crawl Path - [x] Complete

Files:

- `backend/src/intric/worker/crawl/persistence.py`
- `backend/src/intric/info_blobs/info_blob_repo.py`
- callers in `backend/src/intric/worker/crawl_tasks.py` and `backend/src/intric/info_blobs/info_blob_service.py`

Decision:

- Add `tenant_id` to the Phase 2 page replacement delete in `persist_batch()`.
- Extend `InfoBlobRepository.batch_delete_by_titles_and_website()` to accept `tenant_id` and add `InfoBlobs.tenant_id == tenant_id` to stale-cleanup deletes.
- Extend `InfoBlobRepository.delete_by_title_and_website()` to accept `tenant_id` and add `InfoBlobs.tenant_id == tenant_id`; `InfoBlobService._delete_if_same_title()` already has `InfoBlobAdd.tenant_id` available.
- Do not create a broad repository abstraction; update the concrete delete predicates in the existing owner.

Reason:

- `website_id` should imply tenant ownership, but tenant-scoped mutating predicates are cheap defense-in-depth.
- The acceptance criteria explicitly include tenant isolation for same URL and same content hash across tenants.
- Page replacement, stale cleanup, and same-title website file replacement are the mutating delete paths affected by this slice. Tenant-scoping the repository methods is small, local, and prevents one crawl path from becoming safer than another.

### Step 7: Observability And Audit Metadata - [x] Complete

Add local counters:

- `num_hash_skipped_pages`
- `num_hash_skipped_files` should continue to use the existing file-skip counter shape if one already exists.
- `page_hash_skip_rate`

Add to human summary log:

```text
Pages:   {num_pages} crawled, {num_failed_pages} failed, {num_hash_skipped_pages} unchanged skipped ({page_hash_skip_rate:.1f}%)
```

Add to performance log extras:

- `pages_hash_skipped`
- `page_hash_skip_rate`

Add to audit `crawl_stats` metadata:

- `pages_hash_skipped`
- file skip count if audit metadata already has a file skip slot; otherwise do not add a new public field in this slice just for files.

Do not add to:

- `failure_summary`
- `pages_failed`
- `failed_titles`
- circuit-breaker failure counts.

### Step 8: Wire Scrapy HTTP Cache Settings - [x] Complete

Add optional settings for Scrapy HTTP caching:

- `crawl_http_cache_enabled`
- `crawl_http_cache_dir`
- `crawl_http_cache_expiration_seconds`
- `crawl_http_cache_max_bytes_per_website`

Implementation requirements:

- Keep the cache disabled by default.
- Scope filesystem cache directories by tenant id and website id.
- Use Scrapy `HttpCacheMiddleware` with `RFC2616Policy`.
- Prune the website cache directory by size before each crawl.
- If the cache directory cannot be created or pruned, log a warning and continue without HTTP cache.

Reason:

- This uses Scrapy's built-in HTTP revalidation machinery where deployment storage supports it, without making HTTP cache correctness-critical.
- The persistence hash/model retention gate still protects embeddings, DB writes, and stale cleanup even when the HTTP cache is disabled or misses.

### Step 9: Typed Crawl Outcome For Frontend Failure Visibility - [x] Complete

Add a derived typed crawl outcome on crawl-run API models:

- `CrawlOutcomeCode`
- `CrawlOutcomeSeverity`
- `CrawlOutcomePublic`
- `derive_crawl_outcome(...)`

Implementation requirements:

- Keep page-level `failure_summary` as page-failure counts.
- Derive crawl/job-level outcomes separately from page-level `FailureReason`.
- Use `FailureReason` enum values when interpreting `failure_summary`; do not introduce new raw string failure protocols.
- Keep `result_location` as a backward-compatible detail source while the API exposes typed outcome values.
- Update the website list, crawl history table, and crawl result cell to render typed outcomes and translated messages.
- Classify duplicate crawl skips from `outcome.code`, not from frontend string prefixes.

Reason:

- Users need to see why a crawl failed or was skipped without relying on raw backend strings.
- The branch improves the public contract without a migration because the outcome is derived from fields already stored on crawl runs/jobs.

## Current-Slice Acceptance Criteria

1. URL with unchanged content and matching current `embedding_model_id` does not call the embedding API and does not write to `info_blobs` or `info_blob_chunks`.
2. URL with unchanged content but different stored `embedding_model_id` re-embeds and replaces chunks.
3. URL with unchanged content is retained and is not deleted by stale cleanup.
4. URL with changed content re-embeds and replaces chunks, preserving current behavior.
5. URL removed from the source between runs is still deleted by stale cleanup.
6. Files and URL pages use the same stored-blob compatibility predicate.
7. File with unchanged content but different stored `embedding_model_id` is reprocessed.
8. Retained URLs/files and failed URLs/files are excluded from stale deletion for different explicit reasons.
9. Phase 2 page replacement delete includes `tenant_id`, `website_id`, and title.
10. Stale cleanup is tenant-scoped through `batch_delete_by_titles_and_website(..., tenant_id=...)`.
11. Same-title website file replacement is tenant-scoped through `delete_by_title_and_website(..., tenant_id=...)`.
12. Two tenants with the same URL and identical content hash do not share or delete each other's blobs.
13. `PersistBatchResult` count properties cannot drift from URL/failure collections.
14. `failure_summary` contains only real page failures, never unchanged skips.
15. Missing embedding config does not fail all-retained unchanged pages/files, but emits one structured run-level warning.
16. Old hash-only helpers such as `InfoBlobRepository.get_content_hash()` are deleted if unused; if a use appears, they must become tenant-scoped stored-blob-state lookups instead.
17. `pyright --strict` or the repo-equivalent pyright command passes.
18. Audit log behavior remains compatible; no new mutating endpoint is introduced.
19. Scrapy HTTP cache support is available through disabled-by-default settings and uses tenant/website-scoped filesystem directories when enabled.
20. Duplicate crawl skips and crawl failures are exposed to the frontend through typed crawl outcomes rather than frontend-only string-prefix detection.
21. Frontend crawl status views render translated outcome labels/details for known failure and skip states.

## Required Tests

### `backend/tests/unittests/worker/test_persist_batch_logic.py`

Add or update tests:

1. `test_hash_match_retains_url_without_embedding_session_embedding_call_or_db_write`
   - Existing hash equals new content hash and stored `embedding_model_id` equals `ctx.embedding_model_id`.
   - Assert `sessionmanager.create_session` is not called.
   - Assert embedding service is not called.
   - Assert Phase 2 DB session is not opened.
   - Assert result has `retained_urls == (url,)`, `persisted_count == 0`, `retained_count == 1`, `failed_count == 0`.

2. `test_hash_match_with_different_embedding_model_id_re_embeds`
   - Existing hash equals new content hash.
   - Stored `embedding_model_id` differs from `ctx.embedding_model_id`.
   - Assert the page goes through the embedding/write path and is returned in `persisted_urls`, not `retained_urls`.
   - Assert the replacement `InfoBlobs.embedding_model_id` equals `ctx.embedding_model_id`, not the stale stored model id.
   - This is required before implementation because content-only retention would silently keep stale vectors after a model change.

3. `test_existing_blob_state_is_current_for_truth_table`
   - Same hash + same current model returns true.
   - Same hash + different current model returns false.
   - Same hash + missing current model returns true and relies on the run-level warning path.
   - Different hash returns false regardless of model id.

4. `test_hash_match_does_not_require_embedding_model`
   - Existing hash equals new content hash.
   - Stored `embedding_model_id` can be `None` or different because there is no current model to compare against.
   - Pass `embedding_model=None`.
   - Assert retained success and no `FailureReason.NO_EMBEDDING_MODEL`.

5. `test_missing_current_model_with_changed_content_fails_changed_page`
   - Existing hash differs or no existing state exists.
   - Pass `embedding_model=None`.
   - Assert the changed/new page fails with the current no-model failure reason.
   - Assert any hash-matched page in the same batch remains retained.

6. `test_mixed_batch_retains_persists_and_reports_failed_url`
   - One URL has matching hash and matching `embedding_model_id`.
   - One URL has changed content and persists.
   - One changed URL fails during embedding or DB write.
   - Assert retained and persisted titles are cleanup-protected and the failed URL is exposed through `failed_urls`.

7. `test_mixed_batch_retains_unchanged_and_persists_changed`
   - One URL has matching hash and matching `embedding_model_id`.
   - One URL has different hash or different stored `embedding_model_id`.
   - Assert only the changed page embeds and writes.
   - Assert `cleanup_protected_titles` includes both.

8. `test_hash_mismatch_preserves_current_delete_insert_behavior`
   - Existing hash differs.
   - Assert delete and insert still happen in Phase 2.
   - Assert the delete predicate includes `tenant_id`, `website_id`, and title.

9. `test_failed_changed_page_is_not_cleanup_protected`
   - Changed page embedding fails.
   - Assert URL is in failures and not in `persisted_urls`, `retained_urls`, or `cleanup_protected_titles`.

10. `test_null_existing_hash_treats_page_as_changed`
   - Existing hash missing or NULL.
   - Assert page goes through embedding path.

11. `test_persist_batch_result_counts_match_collections`
   - Build a result with persisted URLs, retained URLs, and two failure buckets.
   - Assert computed `persisted_count`, `retained_count`, `failed_count`, `failed_urls`, and `cleanup_protected_titles`.

12. Existing no-embedding tests must still pass for changed/new pages.
   - The current `test_no_embedding_model_fails_all_pages` should still fail pages when no existing matching hash is supplied.

Do not:

- Mock `hashlib.sha256`. The hash is the contract.

### Cleanup Retention Test

This is required.

Target:

- `backend/tests/integration/test_slot_leak_fixes.py`.

Assertion shape:

```python
existing_titles = {"deleted", "unchanged", "changed", "failed"}
must_keep_titles = {"unchanged", "changed"}
failed_titles = {"failed"}

stale_titles = _compute_stale_titles(
    existing_titles=existing_titles,
    must_keep_titles=must_keep_titles,
    failed_titles=failed_titles,
)

assert stale_titles == ["deleted"]  # or set(stale_titles) == {"deleted"}
```

Reason:

- This is the test that proves the P0 data-loss trap is closed.
- Prefer testing the local production helper `_compute_stale_titles()` instead of duplicating the list comprehension in a test-only helper.

Also add an integration-style crawl bookkeeping test for the highest-risk mixed run:

- retained unchanged title -> `must_keep_titles`,
- persisted changed title -> `must_keep_titles`,
- failed changed title -> `failed_titles`,
- existing title absent from source/results -> stale-deleted.

### Crawl Task And File Skip Tests

Add or update tests around `crawl_tasks.py` where practical:

1. `test_file_skip_with_matching_embedding_model_id_retains`
   - Existing file state has same hash and same `embedding_model_id`.
   - Assert file upload/embedding path is not called and the filename is cleanup-protected.

2. `test_file_skip_with_different_embedding_model_id_reprocesses`
   - Existing file state has same hash but different `embedding_model_id`.
   - Assert file processing runs so vectors are refreshed.

3. `test_embedding_misconfigured_but_no_changes_logs_once_per_crawl`
   - Retained pages/files exist.
   - No changed/new pages/files need embedding.
   - Embedding config is missing.
   - Assert one structured warning with `reason="embedding_misconfigured_but_no_changes"`.

### Bootstrap Blob State Lookup Test

This is required.

- Fake rows with:
  - URL title + hash + `embedding_model_id`,
  - file title + hash + `embedding_model_id`,
  - `title is None`,
  - `content_hash is None`.
- Assert only non-null titles enter `existing_titles`.
- Assert only non-null title plus non-null hash rows enter `existing_blob_state_by_title`.
- Assert both file and URL titles are accepted.
- Assert the stored `embedding_model_id` is preserved in `ExistingBlobState`.

If the bootstrap logic remains inline and hard to test, consider extracting only a tiny pure function with a narrow name such as `_build_existing_blob_lookup`. This function earns its place only if it improves testability without hiding crawl semantics. Do not create a generic helper module.

### Tenant-Scoped Delete Tests

Add focused tests for changed-content replacement and stale cleanup:

- Page Phase 2 replacement delete includes `tenant_id`, `website_id`, and title.
- Stale cleanup deletes only rows for the current tenant/website.
- Cross-tenant regression: two tenants with the same URL, same content hash, and different `embedding_model_id`; running tenant A's crawl must neither retain from nor delete tenant B's blob.
- Same-title website file replacement through `delete_by_title_and_website()` includes tenant scope.
- Delete unused `InfoBlobRepository.get_content_hash()` and confirm `rg -n "get_content_hash\\(" backend/src backend/tests` returns no callers.

### Test Files To Review Or Update

Known direct callers/destructures:

- `backend/tests/unittests/worker/test_persistence.py`
- `backend/tests/unittests/worker/test_persist_batch_logic.py`
- `backend/tests/integration/test_slot_leak_fixes.py`
- repo tests covering `InfoBlobRepository.batch_delete_by_titles_and_website()`, if present

Known comments/contract docs to review:

- `backend/tests/integration/test_slot_leak_stress.py`

Production callers:

- `backend/src/intric/worker/crawl_tasks.py`

Search command before implementation:

```bash
rg -n "persist_batch\\(|successful_urls|success_urls|success_count, failed_count" backend/src backend/tests
```

## Validation Commands - [x] Complete

Run from `/Users/ccimen/eneo/eneocrawlerupdate/backend` unless noted otherwise.

Completed validation on this branch:

```bash
uv run ruff check src/intric/worker/crawl_context.py src/intric/worker/crawl/persistence.py src/intric/worker/crawl_tasks.py src/intric/info_blobs/info_blob_repo.py src/intric/info_blobs/info_blob_service.py src/intric/crawler/crawler.py src/intric/main/config.py src/intric/websites/crawl_dependencies/crawl_models.py src/intric/websites/presentation/website_models.py src/intric/jobs/job_repo.py src/intric/worker/crawl/__init__.py tests/unittests/worker/test_persistence.py tests/unittests/worker/test_persist_batch_logic.py tests/unittests/crawler/test_crawler_timeout_tenant_aware.py tests/unittests/websites/test_crawl_outcome.py tests/integration/test_info_blob_repo_tenant_scope.py tests/integration/test_stale_job_preemption.py tests/integration/test_slot_leak_fixes.py tests/integration/test_slot_leak_stress.py
uv run pyright --project pyrightconfig.json src/intric/worker/crawl_context.py src/intric/worker/crawl/persistence.py src/intric/worker/crawl_tasks.py src/intric/info_blobs/info_blob_repo.py src/intric/info_blobs/info_blob_service.py src/intric/crawler/crawler.py src/intric/main/config.py src/intric/websites/crawl_dependencies/crawl_models.py src/intric/websites/presentation/website_models.py src/intric/jobs/job_repo.py src/intric/worker/crawl/__init__.py
uv run pyright --project pyrightconfig.json tests/integration/test_info_blob_repo_tenant_scope.py
uv run pytest tests/unittests/worker/test_persistence.py tests/unittests/worker/test_persist_batch_logic.py tests/unittests/crawler/test_crawler_timeout_tenant_aware.py::TestScrapyHttpCacheSettings tests/unittests/websites/test_crawl_outcome.py tests/integration/test_info_blob_repo_tenant_scope.py tests/integration/test_stale_job_preemption.py::TestJobRepoMarkJobFailedIfRunning tests/integration/test_slot_leak_fixes.py tests/integration/test_slot_leak_stress.py -q
```

Completed frontend validation:

```bash
bunx prettier --write apps/web/messages/en.json apps/web/messages/sv.json 'apps/web/src/routes/(app)/spaces/[spaceId]/knowledge/websites/WebsiteStatus.svelte' 'apps/web/src/routes/(app)/spaces/[spaceId]/knowledge/websites/[id]/CrawlResultCell.svelte' 'apps/web/src/routes/(app)/spaces/[spaceId]/knowledge/websites/[id]/CrawlRunsTable.svelte'
bun eslint 'src/routes/(app)/spaces/[spaceId]/knowledge/websites/WebsiteStatus.svelte' 'src/routes/(app)/spaces/[spaceId]/knowledge/websites/[id]/CrawlResultCell.svelte' 'src/routes/(app)/spaces/[spaceId]/knowledge/websites/[id]/CrawlRunsTable.svelte'
bun run check
```

Notes:

- Backend targeted tests: 70 passed.
- `bun run check`: 0 errors, 1 pre-existing warning in `src/lib/features/api-keys/ExtendExpirationDialog.svelte`.

Reference command set from the original plan:

```bash
uv run pytest tests/unittests/worker/test_persist_batch_logic.py -q
uv run pytest tests/unittests/worker/test_persistence.py -q
uv run pytest tests/integration/test_slot_leak_fixes.py -q
uv run pytest tests/integration/test_slot_leak_stress.py -q
uv run ruff check src/intric/worker/crawl/persistence.py src/intric/worker/crawl_tasks.py tests/unittests/worker/test_persist_batch_logic.py tests/unittests/worker/test_persistence.py tests/integration/test_slot_leak_fixes.py tests/integration/test_slot_leak_stress.py
uv run pyright --project .
```

Optional database validation:

```sql
EXPLAIN
SELECT title, content_hash, embedding_model_id
FROM info_blobs
WHERE website_id = '<website-id>' AND tenant_id = '<tenant-id>';
```

Goal:

- Confirm adding `tenant_id` does not materially regress the existing website lookup plan.

## Risks And Mitigations

| Risk | Why it matters | Mitigation |
|---|---|---|
| Retained URLs not fed into cleanup | Would delete unchanged pages | `cleanup_protected_titles` result property plus required cleanup retention test |
| Hash-only retention keeps stale vectors after model change | Website embedding-model changes would appear successful while old vectors remain | `ExistingBlobState.is_current_for()` compares `content_hash` and current `embedding_model_id` |
| URL and file skip semantics drift | Pages and files could behave differently for the same website/model change | Reuse `ExistingBlobState` for both paths and add file skip model-change test |
| Skip count treated as failure | Misleading UX and circuit-breaker stats | Keep `retained_count` separate from `failed_count`; do not write to `failure_summary` |
| Broken embedding config becomes silent for stable sites | Operators lose an alarm | Structured warning when config is broken but all pages are retained |
| Embedding setup still required for all-unchanged batch | Wastes resources and preserves avoidable failure mode | Prepass hash gate before embedding service setup; assert no `create_session` call |
| Mutable hash map in frozen crawl context | Frozen dataclass would still hold mutable state | Pass `Mapping[str, ExistingBlobState]` as an argument to `persist_batch()` |
| Redundant counts drift from URL/failure collections | Metrics and cleanup decisions become inconsistent | `PersistBatchResult` computes counts from immutable collections |
| Tenant omission in mutating deletes | Defense-in-depth gap for shared-title/same-URL rows | Add tenant predicates to touched delete paths |
| Concurrent crawl non-idempotency | Existing delete/insert pattern can race | Do not solve in this slice; track unique constraint/update-in-place separately |
| Tuple-to-result migration misses tests | Breaks test suite and hides contract change | Enumerate call sites with `rg` and update tests explicitly |
| Old blobs with NULL hash | Cannot be skipped safely | Treat as changed and rewrite once; later runs can skip |
| New comments make code noisier | Human reviewability drops | One-line result docstring, no tutorial comments |
| Warning spam | Large stable misconfigured sites could produce many warnings | Emit one run-level warning in `crawl_tasks.py` |

## What Not To Do In Current Slice

- Do not add sitemap `<lastmod>` filtering.
- Do not enable Scrapy HTTP cache by default or rely on it as the correctness mechanism.
- Do not use a shared Scrapy cache directory without tenant/website scoping, TTL, size policy, and an operational purge path.
- Do not add a standalone `content_hash` index.
- Do not add broad crawler refactors.
- Do not add update-in-place chunk semantics.
- Do not add a broad frontend redesign; keep frontend work to typed crawl outcome rendering.
- Do not add a generic helper module.
- Do not add new interfaces, protocols, factories, adapters, or one-method seams.
- Do not add tuple backward compatibility.
- Do not add new `Any`, `cast`, or `type: ignore`.
- Do not retain a blob on `content_hash` alone.

## Follow-Up Improvements After This Branch

1. Split crawler bookkeeping into:
   - `seen_in_source`,
   - `fetched`,
   - `persisted_or_retained`.
2. Keep Scrapy HTTP cache disabled by default until the configured cache directory is backed by durable worker storage in production.
3. Add a stored crawl outcome column if product wants querying/alerting on outcome codes instead of deriving them at the API boundary.
4. Add idempotency protection for `(tenant_id, website_id, title)` if concurrent crawls remain possible.
5. Consider update-in-place for changed pages to reduce chunk-table churn further.
6. Add more specific user-facing warning states for sitemap-not-found and malformed-sitemap failures.
7. Revisit sitemap `<lastmod>` filtering after source/fetch/retention bookkeeping is split; keep it as a fetch hint, not the correctness mechanism.
8. Add a stored processing fingerprint that includes embedding model, chunking version, text-normalization version, and embedding dimensions.
9. Review broader info-blob tenant-scoping outside the website crawl paths, such as group and integration deletes, as a separate hardening slice.

## Questions For ChatGPT Extended Pro

Please review the plan above as a skeptical implementation reviewer. The desired outcome is a robust, maintainable implementation slice that reduces embedding spend without introducing silent data loss or misleading crawl status.

Specific questions:

1. Do you agree that `persist_batch()` is the right canonical owner for hash-match retention, given that it already owns hashing, embedding, and blob/chunk writes?
2. Is `ExistingBlobState(content_hash, embedding_model_id)` enough as the current compatibility contract, or should this slice include a broader fingerprint immediately?
3. For missing current embedding config, is it correct to retain hash-matched existing blobs because there is no current model to compare against, while emitting a run-level warning?
4. Do you see any downside to using the same `ExistingBlobState.is_current_for()` method for both URL pages and files?
5. Do you agree that `PersistBatchResult` should store only URL/failure collections and compute all counts from those collections?
6. Is `cleanup_protected_titles` the clearest name for stale-cleanup safety, or would `must_keep_titles` be clearer as the returned property?
7. Do you agree with renaming `crawled_titles` to `must_keep_titles` in the current slice so the cleanup predicate is readable?
8. Do you agree with not writing hash skips to `failure_summary`, even though that means no immediate crawl-history API field for skipped pages?
9. Is the run-level structured warning for all-unchanged/all-retained crawls with broken embedding config enough to avoid silent operator blind spots?
10. Would you extract `_build_existing_blob_lookup` for testability, or keep the bootstrap loop inline to avoid a shallow Module?
11. Is there a better way to test cleanup retention without adding a shallow helper solely for tests?
12. Are there any hidden correctness problems with using `InfoBlobs.title` as the lookup key for URL pages?
13. Are there performance concerns with holding `existing_blob_state_by_title` in memory for large websites?
14. Do you agree with scoping tenant-delete hardening in this slice to website crawl paths: page replacement, stale cleanup, and same-title website file replacement?
15. Should the implementation include EXPLAIN-plan verification for adding `tenant_id` to the bootstrap query, or is static reasoning enough?
16. Are there any reliability improvements in the immediate area that are small enough to include without broadening this slice?
17. What is the smallest durable backend-to-frontend crawl failure contract that would make failed crawls understandable without turning this hash-skip slice into a broad UI/backend refactor?
18. Should that failure contract be a new `crawl_outcome_summary` field, a replacement for `failure_summary`, or a separate job-failure detail model attached to `CrawlRunPublic`?
19. Should `result_location` stop carrying failure text entirely, or should we keep it as a backward-compatible fallback while typed failure details roll out?
20. Should crawl/job-level outcome codes be a different enum from page-level `FailureReason`, or can one enum stay understandable enough?
21. Should duplicate crawl skips become a non-failed terminal status/outcome rather than a failed job with a string prefix?
22. Do you agree that Scrapy `HttpCacheMiddleware` + `RFC2616Policy` is the best fetch-skip follow-up starting point for avoiding body downloads, while still keeping persistence hash/model retention as the correctness gate?
23. What out-of-scope follow-ups would you cut or defer more aggressively to keep this slice human-reviewable?

## Current Score After Implementation

| Dimension | Score | Reason |
|---|---:|---|
| Maintainability | 8 | Retention ownership stays in `persist_batch()`, orchestration consumes a typed result, and follow-ups are explicit |
| Code Quality | 8 | URL and file retention share one compatibility predicate, and counts are computed from source collections |
| Clean Architecture | 8 | Persistence, crawl orchestration, crawler adapter settings, and frontend outcome rendering stay in their existing owners |
| Separation of Concerns | 8 | Persisted, retained, failed, stale, and crawl/job outcome concepts are no longer conflated |
| Single Source of Truth | 8 | `ExistingBlobState.is_current_for()` is the shared current-blob predicate for pages and files |
| Human Readability | 8 | `must_keep_titles`, `cleanup_protected_titles`, and typed outcomes make the data-loss boundary reviewable |
| Human Reviewability | 8 | Diff is covered by focused tests, strict pyright, frontend checks, and Claude commit-gate review |
| Testability | 8 | Tests cover retention, model changes, cleanup safety, tenant-scoped deletes, warning path, and outcome derivation |
| Failure UX | 8 | Frontend now consumes typed crawl outcomes and translated messages without raw skip-prefix fallbacks |

Overall score: 8.

Claude implementation re-review agreed with this score: `VERDICT: green`, `GREEN_LIGHT: yes`, `MIN_SCORE: 8`.
