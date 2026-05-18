# Crawler ↔ Usage architecture boundary — production-polish plan

> **Status**: implemented on `feature/crawler-skip-unchanged-pages`. The document
> now records the shipped ownership boundary between `/admin/crawler/Aktivitet`
> and `/admin/usage`, plus the deferred ledger migration triggers.

## TL;DR

- `/admin/usage` is the **canonical accounting surface** (tenant-wide tokens,
  storage, model/source breakdown, cost when available).
- `/admin/crawler/Aktivitet` is the **causality + action surface** (which
  website caused crawler work, which space/owner is responsible, why it
  repeated work, what failed, what the admin can do *now*).
- The two pages share facts via the existing usage + storage repositories;
  they do not duplicate accounting logic.
- Crawler embedding usage flows into the existing `TokenUsageAnalyzer` as a
  third UNION source (`source_type = "crawler_embedding"`), labelled through
  `source_breakdown` / `source_types` so the usage page can split by source.
  No parallel cost service inside crawler.

---

## 1. Canonical ownership model

| Concern | Owner module | Owner page | Why |
|---|---|---|---|
| **Tenant token accounting** | `token_usage_*` (`TokenUsageAnalyzer`, `TokenUsageSummary`) | `/admin/usage/tokens` | Already the union-aggregator for Questions + AppRuns; extending it for crawler keeps one read-model. |
| **Tenant + space storage accounting** | `storage_*` (`StorageInfoRepository`) | `/admin/usage/storage` (+ `/admin/usage`) | Already aggregates `Websites.size` per space alongside Collections + IntegrationKnowledge. The single source of truth for "how full is this tenant". |
| **Model & provider cost (price) registry** | LiteLLM model registry + `crawl_runs.embedding_*` snapshot columns; will align with Max's cost branch when it lands. | `/admin/usage/tokens` (display) | Snapshots on `crawl_runs` mean re-pricing later doesn't rewrite history. |
| **Crawler run observability + causality** | `crawl_run_repo.website_processing_aggregate` (read-model) | `/admin/crawler/Aktivitet` | Per-website work, retention, failures, schedule, attribution — the investigation surface. |
| **Crawler inventory + bulk control** | `WebsiteAdminRepository.tenant_website_inventory` | `/admin/crawler/Webbplatser` | The canonical list-and-act surface, unchanged by this plan. |
| **Crawler health (broken/stuck lifecycle)** | `crawl_run_repo.recent_failures_for_tenant`, `watchdog_interventions_for_tenant` | `/admin/crawler/Hälsa` | Unchanged. |

**Rule**: the crawler admin never re-computes a tenant or space *total* that
`/admin/usage` already owns. It only computes per-website causality and
references attribution columns.

---

## 2. P0 — `/admin/crawler/Aktivitet` polish (this pass)

These items implement the locked contract from the chat thread. They are now
shipped in this branch. Order is dependency-driven: backend attribution
columns first, frontend redesign on top, copy cleanup at the end.

| # | Change | Files |
|---|---|---|
| 1 | **Aggregate response** carries attribution + cumulative storage per row: `space_id`, `space_name`, `collection_name`, `owner_user_id`, `owner_email`, `indexed_size_bytes` (from `Websites.size`), `latest_run_at`. Joined into the existing `aggregated_stmt` via `Spaces`, `CollectionsTable`, `Users`. | `backend/.../crawl_run_repo.py`, `crawler_website_processing_aggregate.py` (dataclass fields), `crawler_admin_models.py` (response item). |
| 2 | **SDK update** via manual schema patch + `crawlerGeneratedTypes.test.ts` verification because local OpenAPI generation was not available in this environment. No `any`. | `frontend/packages/intric-js/src/types/schema.d.ts`, `endpoints/crawler-admin.js`. |
| 3 | **Feature helpers**: `getCrawlerWebsiteProcessingOwnerLabel`, `getCrawlerWebsiteProcessingSpaceLabel`, `getCrawlerWebsiteProcessingEmbeddingCellLabel` (3-way fallback per locked copy), `getCrawlerWebsiteProcessingHealthSignal(item) → "healthy" \| "waste" \| "failure" \| "paused" \| "too_large"`. | `frontend/.../crawlerWebsiteProcessing.ts`. |
| 4 | **Row redesign**, always-visible secondary line (no hover-only). Primary line: Webbplats · Schema · Storlek · Senaste bäddning · Hälsa · ⋮. Stacked under URL: Arbetsyta · Ägare. Secondary line (muted): Senast körd · {n} körningar · {p} sidor · {f} filer · {r} % återanvänt. | `frontend/.../AktivitetTab.svelte`. |
| 5 | **Hälsa cell**: shadcn `Badge` with icon **plus** short text per state — `✗ Fel`, `⚠ Låg återanvändning`, `📦 För stora filer`, `⏸ Pausad`, `✓ Frisk`. Color never alone. | `frontend/.../AktivitetTab.svelte`. |
| 6 | **Row action menu** (investigation subset): `Visa detaljer`, `Ändra intervall`, `Sätt till manuellt eller pausa`, `Kör igen`, `Visa granskningslogg`, `Ta bort webbplats`. Reuses `crawlerAdminPageState.svelte` dialog state. | `frontend/.../AktivitetTab.svelte`. |
| 7 | **Sort options reframed**: add `indexed_size`, `tokens`, `low_retention` to `CrawlerWebsiteProcessingSort` enum; rename UI labels to admin-question shape (`Prioritet`, `Tokens/kostnad`, `Storlek`, `Lägst återanvändning`, `Fel`, `Senast aktiv`). `load_pressure` stays as the backend value behind `Prioritet`, never rendered as `542`. | Backend enum + repo ORDER BY branches, frontend label dispatcher. |
| 8 | **Drop horizontal scroll**: remove `min-w-[66rem]`. Target: fits at 1024 px without scroll. Mobile reflow remains. | `frontend/.../AktivitetTab.svelte`. |
| 9 | **Period summary band** replaces the standalone "Schemalagd crawler-belastning" card. Four compact tiles: `Indexerat`, `Tokens`, `Behöver åtgärd`, `Hämtat`. The token tile shows token volume only; full cost accounting lives on `/admin/usage`. | `frontend/.../AktivitetTab.svelte`. |
| 10 | **Copy locks** (sv.json + en.json): retire `Behållet` → `Återanvänt`, retire `Source-skip hjälper inte` → `Sitemap hjälpte inte` (or `Oförändrat innehåll hämtades igen`), retire `Ingen användning registrerad` → tri-state copy rule (`0 nya tokens · inget nytt bäddades in` / `Saknas för den här körningen` / `12 408 tokens · kostnad saknas`), `Belastningstryck` → `Prioritet`, dynamic period copy (`Periodens X`, no `Veckans` outside literal 7-day usage). | `messages/sv.json`, `messages/en.json`. |
| 11 | **Cross-link to `/admin/usage`** above the table: small inline link "Se total token-användning i Användning". Does *not* duplicate the totals on Aktivitet. | `frontend/.../AktivitetTab.svelte`. |

### Out of P0 (deferred)

- Tenant-wide cost totals on Aktivitet (codex risk: fake precision). Belongs on `/admin/usage` once P1 lands.
- Cost-trend sparkline per row (premature; needs ledger refactor first).
- Recommendation engine ("drop to weekly?").

---

## 3. P1 — Plug crawler embedding into `/admin/usage`

This is the work that closes the loop so the cost-conscious admin doesn't
need two tabs to read their tenant's bill.

| # | Change | Files |
|---|---|---|
| 1 | **Extend `ModelTokenUsage`** with `model_kind`, `source_types`, `source_breakdown`, and optional `total_cost_usd`. Backward-compatible: existing JSON payload keeps current fields; new fields are additive. | `token_usage/domain/token_usage_models.py`. |
| 2 | **Extend `TokenUsageAnalyzer`** with a third UNION ALL source — `crawl_runs` rows where `embedding_input_tokens IS NOT NULL` *or* `embedding_total_cost_usd IS NOT NULL`. Join `EmbeddingModels` and model providers so the same result shape covers completion and embedding models. Source grouping stays explicit via `source_type`. | `token_usage/infrastructure/token_usage_analyzer.py`. |
| 3 | **Source filter on the endpoint**: `GET /api/v1/token-usage/?source_type=chat,app_run,crawler_embedding` (csv enum). Default = all. | `token_usage/presentation/token_usage_router.py`. |
| 4 | **Add a per-source filter strip** to `/admin/usage/tokens` so the admin can split chat vs app vs crawler. UI stays on the existing `@intric/ui` components; do not migrate Usage to shadcn in this pass. | `frontend/.../usage/tokens/*`. |
| 5 | **Cost coverage signal**: surface a quality indicator on the usage view — "Kostnad: 92 % av token-användningen har leverantörskostnad rapporterad". Computed token-weighted as `cost_covered_token_usage / cost_trackable_token_usage`. Never fake-backfill historical missing cost. | `token_usage/infrastructure/token_usage_analyzer.py` + frontend. |
| 6 | **Top 5 arbetsytor band on Aktivitet** (promoted from P2 per chat). Sourced from a small per-space rollup over the same aggregate scope, capped to top 5 by selected sort axis. Click a band entry → applies a `space_id` filter to the website table. | Backend repo, frontend tab. |

### Out of P1 (deferred to P2)

- Migration to a dedicated `usage_records` ledger.
- CSV export of usage / crawler activity.
- Per-user usage breakdown.

---

## 4. P2 — Usage ledger refactor (when scale demands)

The triple UNION (Questions + AppRuns + CrawlRuns) is fine until any of the
three source tables hits ~10⁷ rows per tenant per month. Above that, plan a
dedicated immutable `usage_records` ledger.

| # | Change | Sketch |
|---|---|---|
| 1 | **`usage_records` table**: `id`, `tenant_id`, `created_at`, `source_type`, `source_id` (FK to crawl_run/question/app_run), `model_id`, `provider`, `input_tokens`, `output_tokens`, `cost_usd`, `space_id`, `user_id`. | Append-only. Soft-deleteable per `source_type` tombstones. |
| 2 | **Writers**: question-saver, app-run-saver, crawl-run-saver each insert one row per source row when usage is recorded. Same transaction. Idempotent on `(source_type, source_id)`. | |
| 3 | **TokenUsageAnalyzer V2**: queries `usage_records` directly. Single index path; no UNION. | |
| 4 | **CSV/Parquet export**: stream from `usage_records` with cursor pagination. | |

Triggers for the migration:
- Median crawler tenants approaching 10k crawl_runs/day, or
- `/admin/usage` p95 query latency above 800 ms on production-shaped data.

Until then, the UNION approach is the right scope/value trade.

---

## 5. Files to extend (and why)

| File | Why |
|---|---|
| `backend/src/intric/websites/domain/crawl_run_repo.py` | Add attribution joins + `latest_run_at` column; extend the existing `aggregated_stmt`, do not branch. |
| `backend/src/intric/websites/domain/crawler_website_processing_aggregate.py` | Add per-row attribution fields to the dataclass. |
| `backend/src/intric/websites/presentation/crawler_admin_models.py` | Mirror the dataclass on the response model. |
| `backend/src/intric/admin/crawler_admin_router.py` | New sort enum values + telemetry labels (`source_type` if used cross-cutting). |
| `backend/src/intric/token_usage/infrastructure/token_usage_analyzer.py` | P1: add the third UNION source and `source_type` labelling. |
| `backend/src/intric/token_usage/domain/token_usage_models.py` | P1: `source_type` field on `ModelTokenUsage`; optional `total_cost_usd`. |
| `backend/src/intric/token_usage/presentation/token_usage_router.py` | P1: `source_type` query filter. |
| `frontend/apps/web/src/lib/features/admin/crawlerWebsiteProcessing.ts` | New helpers, sort enum extension, copy lock dispatcher. |
| `frontend/apps/web/src/routes/(app)/admin/crawler/AktivitetTab.svelte` | Row redesign + period summary band + action menu + Top-5 spaces band. |
| `frontend/packages/intric-js/src/types/schema.d.ts` + `endpoints/crawler-admin.js` + `endpoints/usage.js` | SDK regen for new query params and response fields. |
| `frontend/apps/web/messages/sv.json` + `en.json` | Copy locks. |

## 6. Files to leave alone

| File | Why |
|---|---|
| `backend/src/intric/storage/domain/storage_repo.py` | Already the canonical tenant + space storage source. Crawler must not invent a parallel storage calculation. |
| `backend/src/intric/storage/application/storage_services.py` | Same. |
| `frontend/apps/web/src/routes/(app)/admin/usage/+page.{ts,svelte}` | The accounting surface UI stays on `@intric/ui`. We do not migrate it to shadcn in this pass. Reuse the *logic*, not the components. |
| `frontend/apps/web/src/routes/(app)/admin/crawler/WebbplatserTab.svelte` | The inventory + bulk + full-action surface. Aktivitet is its complement, not its replacement. |

## 7. Duplicates we will not create

1. **A second tenant / space storage rollup inside `/admin/crawler`.** Storage lives in `StorageInfoRepository`. Crawler exposes per-website `indexed_size_bytes` only as attribution context.
2. **A crawler-specific cost service.** Cost flows through `TokenUsageAnalyzer` → `/admin/usage`. Crawler shows the per-row latest-run bäddning cell only; the period total stays on `/admin/usage`.
3. **A crawler-only token analyzer.** Anything cross-source goes through `TokenUsageAnalyzer`. Crawler-only roll-ups would re-introduce the UNION at every consumer.
4. **A `usage_records` table in P0 or P1.** Defer until scale forces it.
5. **A "Veckans kostnad" tile on Aktivitet.** This was on the codex synthesis; correct call now is to cross-link to `/admin/usage` instead.
6. **Manual token estimation.** Use only `embedding_input_tokens` reported by LiteLLM. If the row predates that pipeline, show `Saknas för den här körningen`. No estimation.

## 8. API / data-shape recommendations

### 8.1 `/api/v1/admin/crawler/website-processing` response (per-row item)

Additive only:

```jsonc
{
  "website_id": "…",
  "website_name": "…",
  "website_url": "https://…",
  "update_interval": "weekly",
  "space_id": "…",                   // new
  "space_name": "…",                 // new
  "collection_name": "…" | null,     // new (optional, only when set)
  "owner_user_id": "…",              // new
  "owner_email": "…",                // new
  "indexed_size_bytes": 1234567,     // new — from Websites.size
  "latest_run_at": "2026-05-18T…",   // new
  "total_runs": 2,
  "terminal_runs": 2,
  "failed_runs": 1,
  "pages_crawled": 494,
  "files_downloaded": 48,
  "pages_hash_retained": 0,
  "files_hash_retained": 0,
  "pages_source_retained": 0,
  "files_too_large_skipped": 0,
  "pages_failed": 0,
  "files_failed": 0,
  "indexed_content_count": 542,
  "schedule_frequency_weight": 1.0,
  "retention_rate": 0.0,
  "cost_pressure_score": 542.0,
  "embedding_input_tokens": 12408,
  "embedding_total_cost_usd": null,
  "latest_embedding_model_name_snapshot": "…",
  "latest_embedding_model_litellm_name_snapshot": "…",
  "latest_embedding_model_provider_snapshot": "openai",
  "latest_embedding_input_tokens": 12408,
  "latest_embedding_total_cost_usd": null,
  "latest_embedding_usage_source": "provider_reported"
}
```

Response-level (already shipped this branch):

```jsonc
{
  "items": [...],
  "total": 6,
  "limit": 10,
  "offset": 0,
  "days": 7,
  "since": "…",
  "until": "…",
  "low_retention_threshold": 0.5,
  "source_skip_drift_min_indexed": 50,
  "summary": {
    "website_count": 6,
    "indexed_size_bytes": 104857600,
    "embedding_input_tokens": 12408,
    "embedding_total_cost_usd": "0.000012408000"
  },
  "space_rollup": [
    {
      "space_id": "…",
      "space_name": "…",
      "website_count": 3,
      "total_runs": 7,
      "pages_crawled": 494,
      "files_downloaded": 48,
      "indexed_size_bytes": 92013,
      "embedding_input_tokens": 12408,
      "embedding_total_cost_usd": "0.000012408000",
      "action_required_count": 1,
      "latest_run_at": "2026-05-18T…"
    }
    // up to 5 entries; ranking honors the active sort axis
  ]
}
```

### 8.2 `/api/v1/token-usage/` (P1)

Additive:

```jsonc
{
  "start_date": "2026-04-18T…",
  "end_date": "2026-05-18T…",
  "models": [
    {
      "model_id": "…",
      "model_name": "text-embedding-3-small",
      "model_org": null,
      "model_provider": "openai",
      "model_kind": "embedding",            // new
      "source_types": ["crawler_embedding"], // new
      "input_token_usage": 12408,
      "output_token_usage": 0,
      "total_cost_usd": "0.000028",         // new — null when not provider-reported
      "request_count": 1
    },
    // …
  ],
  "source_breakdown": [
    {
      "source_type": "crawler_embedding",
      "model_kind": "embedding",
      "input_token_usage": 12408,
      "output_token_usage": 0,
      "total_cost_usd": "0.000028",
      "request_count": 1
    }
  ],
  "cost_coverage_ratio": 0.92               // token-weighted coverage
}
```

Query params: `?source_type=chat,app_run,crawler_embedding` (csv). Omit = all.

## 9. Time complexity + indexing

### 9.1 Crawler aggregate (this branch)
- Hash-aggregate over `crawl_runs` in window: O(N + W log W), where N is
  matching crawl-run rows and W is distinct websites.
- Adding `space_id` / `owner_email` to the GROUP BY adds constant per-row work;
  no new table scan is introduced.
- The Top-5 workspace band groups the same aggregate scope by `space_id`:
  O(W + S log S), where S is distinct spaces in the filtered result. It is not
  a separate crawl-run scan in application code.
- `space_id` filtering uses the existing `websites.space_id` join path and stays
  tenant-scoped.
- `pg_trgm` GIN indexes on `websites.url`, `websites.name` already exist (V2-G migration) and serve the search filter.

### 9.2 TokenUsageAnalyzer 3-way UNION (P1)
- Each branch: `O(N_source)` linear scan, filtered by `(tenant_id, created_at)`.
- Outer aggregate: `O(M)` where M = distinct `(model_id, source_type)` per window. Small.
- **New index shipped**: `crawl_runs (tenant_id, created_at, embedding_model_id) WHERE embedding_input_tokens IS NOT NULL` — partial index, speeds up the third UNION's predicate.

### 9.3 P2 ledger
- `usage_records (tenant_id, created_at, source_type)` btree, plus `usage_records (tenant_id, source_id)` for idempotency. Removes the UNION entirely.

## 10. Acceptance criteria + tests

### Aktivitet (P0)

- [x] Response carries `space_name`, `owner_email`, `indexed_size_bytes`, `latest_run_at` per row. Integration test asserts attribution columns survive tenant scoping.
- [x] Row redesign removes the wide min-width table and uses a 6-column desktop table plus stacked mobile cards.
- [x] Hälsa cell renders icon + label, not color alone.
- [x] `load_pressure` score is not rendered as a raw unitless cell; UI label is `Prioritet`.
- [x] Copy locks: user-facing copy uses `Återanvändning`, `Sitemap hjälpte inte`, `Saknas för den här körningen`, and period-scoped language.
- [x] Period summary band has no cost total; cross-link to `/admin/usage` is present.
- [x] Row action menu reuses the same dialog state as Webbplatser for detail, retry, interval, audit log, and delete.

### Token-usage extension (P1)

- [x] `TokenUsageAnalyzer.get_model_token_usage` returns `crawler_embedding` rows when `crawl_runs` has usage in the window.
- [x] `source_type` filter narrows correctly; `?source_type=chat` excludes crawler rows.
- [x] `cost_coverage_ratio` is token-weighted and reflects the share of trackable tokens with provider-reported cost.
- [x] No hidden retry collapse: two crawl-run rows for the same website are summed because each run is billable work.

### Boundaries (negative tests)

- [x] `/admin/crawler/website-processing` response does **not** include `tenant_total_storage_bytes` or `tenant_total_tokens` (contract test on response schema).
- [x] `/admin/usage/tokens` response does **not** include per-website attribution. Test asserts shape.

## 11. UX placement matrix

| Metric | `/admin/usage` | `/admin/crawler/Aktivitet` | `WebsiteDetailDialog` |
|---|---|---|---|
| Tenant total tokens (period) | ✅ headline | ❌ (cross-link only) | ❌ |
| Tenant total storage | ✅ headline | ❌ (cross-link only) | ❌ |
| Tenant total cost (USD) | ✅ when coverage ≥ 80 % | ❌ (cross-link only) | ❌ |
| Cost coverage ratio | ✅ small caption | ❌ | ❌ |
| Per-model token breakdown | ✅ | ❌ | ❌ |
| Per-source breakdown (chat/app/crawler) | ✅ | ❌ | ❌ |
| Per-space storage breakdown | ✅ | ❌ (only Top-5 band, not totals) | ❌ |
| Per-website crawler causality (runs, retention, failures) | ❌ | ✅ primary | ✅ secondary |
| Per-website indexed size (cumulative) | ❌ (totals only) | ✅ attribution column | ✅ |
| Per-website latest-run tokens / cost | ❌ | ✅ "Senaste bäddning" cell | ✅ "Aktivitet" section |
| Per-website schedule | ❌ | ✅ column | ✅ |
| Per-website owner / space | ❌ | ✅ stacked under URL | ✅ |
| Per-website actions (change interval / pause / retry / delete / audit log) | ❌ | ✅ row menu | ✅ footer |
| Top-5 arbetsytor band on Aktivitet | ❌ | ✅ (P1) | ❌ |
| Cross-link Aktivitet → Usage for full token bill | ❌ | ✅ small inline link | ❌ |

## 12. Risks / trade-offs / what not to do

| Risk | Mitigation |
|---|---|
| **Admin reads Aktivitet's bäddning column as their full bill.** | Aktivitet is window-scoped per crawl run; the cross-link to `/admin/usage` is non-negotiable. Cost coverage caption on `/admin/usage`. |
| **Stale price snapshots after Max's cost branch lands.** | Cost is read from `crawl_runs.embedding_total_cost_usd` snapshot, not recomputed live. Re-pricing of *future* rows after Max's branch is fine; historical rows stay accurate to their moment. |
| **UNION ALL scales linearly until ~10⁷ rows/source.** | Document the trigger condition; defer ledger refactor until p95 latency or row count crosses the threshold. |
| **Partial cost coverage misleads the admin.** | Show a `cost_coverage_ratio` caption; never extrapolate to a "full" total when coverage < 80 %. |
| **Row redesign drifts back into "show every field everywhere".** | Locked column set + locked copy table (§2 #10). Reviewer enforces before future crawler admin changes. |
| **`Hälsa` icon becomes color-only on dark mode.** | Icon + short text per state; explicit aXe check in acceptance. |
| **Attribution join slows the aggregate query.** | `Spaces`, `Users`, `CollectionsTable` joins are PK-based; existing tenant-inventory query already does them with no measured slowdown. |
| **Per-row action menu erodes Aktivitet's investigation purpose.** | Action subset is locked to investigation-relevant items; bulk and inventory remain in Webbplatser. |
| **Frontend `@intric/ui` (Usage) vs shadcn (Crawler) drift.** | This pass *does not* migrate Usage. Crawler admin keeps the shadcn track; the two share *logic*, not UI primitives. Migration of Usage to shadcn is a separate initiative. |

## 13. Alignment with Max's model-cost branch

- Use the existing snapshot columns on `crawl_runs` (`embedding_model_litellm_name_snapshot`, `embedding_model_provider_snapshot`, `embedding_input_cost_per_token_snapshot`, `embedding_total_cost_usd`, `embedding_usage_source`) so re-pricing later is additive.
- LiteLLM-reported usage when `embedding_usage_source = "provider_reported"`. When `"missing"` or null, show "Saknas" with tooltip explanation. Never estimate.
- When Max's branch lands a unified `model_cost_registry` (or similar), the analyzer's price-resolution step migrates one line — the snapshot strategy means no history rewrite.
- Coordinate the `source_type` enum naming with Max if their branch introduces a similar dimension. Single SoT.

## 14. Open questions

1. **Single source-type enum** for `token_usage` (`chat | app_run | crawler_embedding`) vs split into `interaction_type` and `embedding_type`? — Implemented as the flat enum. Revisit only if a fourth source makes the enum ambiguous.
2. **Per-space rollup band ranking** — Implemented: rank by the current sort axis so the band follows the operator's investigation question.
3. **Cost coverage UX** — Implemented as a caption on `/admin/usage`. Future product call: whether low coverage should hide the total cost entirely.
4. **Backfill of pre-snapshot rows** — Decision: leave NULL; backfills are dishonest accounting.
5. **`/admin/usage` shadcn migration** — A follow-up initiative, not in scope here.

## 15. Implementation order summary

1. **Shipped earlier (`ff2710b5`)**: Aktivitet baseline + dialog primitive.
2. **Completed in this tranche (§2)**: row redesign + attribution + copy locks.
3. **Completed in this tranche (§3)**: TokenUsageAnalyzer crawler integration; cost coverage signal; Top-5 spaces band.
4. **Deferred (§4)**: usage ledger refactor, CSV export — only when scale forces it.

> Maintainability principle: each surface answers one question well. Usage =
> "how much was used / cost / stored." Crawler = "which crawler caused what
> work, and what can I do about it." Never grow either into the other.
