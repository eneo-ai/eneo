# SharePoint Integration — Hardening Tracker

Living checklist for hardening the SharePoint/OneDrive → info_blob (RAG) ingestion flow.
Source: deep multi-agent architecture review (2026-06-25). Goal: move every dimension toward 10/10.

**Overall grade at review time: 6/10** — competent core (best-in-class throttling, correct
subscription lifecycle vs Graph limits, real single-flight concurrency, correct multi-tenancy),
but with real security + data-integrity defects bolted onto an older v1.

Status legend: ✅ done · 🟡 partial · ⬜ todo · ⏭️ deferred (large/low-value) · ❌ skip (not worth it)

---

## Per-dimension scores (review baseline → target)

| Dimension | Baseline | Core blockers to 10 |
|---|---|---|
| Auth & OAuth token lifecycle | 5/10 | plaintext tokens, missing CSRF state |
| Subscription lifecycle & renewal | 7/10 | no escalation on health data; create race |
| Webhook ingestion & security | 6/10 | fail-open clientState; non-constant-time compare |
| Delta sync, extraction & info_blob | 6/10 | ChangeKey-before-commit; folder-subtree orphans; silent extraction garbage |
| Orchestration, idempotency, multi-tenancy | 7/10 | no stuck-job reaper; string-matched error mapping |
| DDD layering & maintainability | 5/10 | inverted-DDD imports; god-objects |

---

## P0 — Security & data integrity (real bugs, fix now)

### 1. Per-user OAuth tokens stored in plaintext ⬜ `[high / security]`
`access_token` + `refresh_token` written verbatim (Confluence **and** SharePoint).
- `backend/src/intric/integration/infrastructure/mappers/oauth_token_mapper.py:18-24` (write)
- `backend/src/intric/integration/domain/factories/oauth_token_factory.py:36-52` (read)
- `backend/src/intric/database/tables/integration_table.py:~98` (columns)
- Same feature already encrypts `client_secret` via `EncryptionService` (`settings/encryption_service.py`).
- **Plan:** inject `EncryptionService` into `OauthTokenMapper`; encrypt on write, decrypt on read.
  Lazy migration: read legacy plaintext through unchanged (`is_encrypted()` guard), re-encrypt on next
  write. No schema change. Works whether or not `ENCRYPTION_KEY` is set.
  Note: `decrypt()` hard-rejects un-prefixed plaintext when active → handle plaintext in the mapper, not via `decrypt()`.

### 2. ChangeKey written to Redis before the DB transaction commits ⬜ `[high / data-integrity]`
On rollback (lease-loss cancel → `CancelledError` bypasses per-item `except`, or commit failure) the
blob is gone but Redis says "processed" → file skipped up to 7 days (TTL) or until 410 full resync.
- `backend/src/intric/integration/infrastructure/content_service/sharepoint_content_service.py:~811`
- **Plan:** set ChangeKey only **after** commit, or invalidate the ChangeKey on rollback.

### 3. Moving a folder out of scope orphans all child info_blobs 🟡 `[high / data-integrity]` — GH 189874542
Graph delta sends the folder item, not the unchanged children. Out-of-scope branch deletes by the
**folder's** id, which matches no file blob → whole subtree orphaned.
- `backend/src/intric/integration/infrastructure/content_service/sharepoint_content_service.py:~730`
- **Done (WIP):** out-of-scope *files* are now deleted; facet detection hardened (`_has_graph_facet`).
- **Remaining:** delete the *subtree* when a folder goes out of scope / is deleted (by parent path prefix).

### 4. Per-user OAuth callback does not validate `state` (CSRF) ⬜ `[medium / security]`
Callback never verifies `state`; default is the literal `"state"`. Admin flow does this correctly.
- `backend/src/intric/integration/presentation/integration_auth_router.py:29-60`
- `backend/src/intric/integration/infrastructure/auth_service/sharepoint_auth_service.py:~97`
- **Plan:** reuse the admin flow's `_store_oauth_state` / `_pop_oauth_state` (random state, Redis TTL, atomic pop, tenant binding).

### 5. clientState is the only webhook auth, but the check fails open ⬜ `[medium+low / security]`
Endpoint is `with_user=False`; the per-notification check is skipped entirely if the secret is falsy,
and uses `!=` instead of constant-time compare.
- `backend/src/intric/integration/infrastructure/sharepoint_webhook_service.py:82-96`
- **Plan:** fail-closed gate at the top of `handle_notifications`; `hmac.compare_digest` for the compare.

---

## P1 — Robustness & correctness (fix soon)

### 6. Full sync never deletes orphans; reconciliation code is dead ⬜ `[medium]` — GH 189874542
`_get_all_sharepoint_files` / `_collect_files_recursive` (~100 lines) have zero callers. Leak is limited
to the 410-recovery tail (an expired delta token does not replay missed deletions).
- `backend/src/intric/integration/infrastructure/content_service/sharepoint_content_service.py:~1599`
- **Plan:** wire reconciliation into full sync, OR delete the dead code and document full sync as add-only.

### 7. Content extraction produces silent garbage instead of failing ⬜ `[medium]`
DOCX/PPTX via raw regex over XML bytes; PDF falls through to `binary_to_text`; sentinels embedded as content.
- `backend/src/intric/integration/infrastructure/content_service/utils.py:117-163, 326-354`
- **Plan:** treat sentinels / low printable-ratio as extraction failure; prefer `python-docx`.

### 8. Unconditional re-embedding ignores `content_hash` ⬜ `[medium / perf]`
`content_hash` column exists (crawler uses it) but SharePoint never sets/reads it → metadata edits and
co-author saves pay full embedding cost.
- `backend/src/intric/integration/infrastructure/content_service/sharepoint_content_service.py` (`_process_info_blob`)
- **Plan:** hash extracted text; skip re-embed when unchanged.

### 9. Refresh assumes Entra always returns a new refresh_token ⬜ `[low]`
- `backend/src/intric/integration/infrastructure/oauth_token_service.py:84-88`
- **Plan:** keep the prior refresh_token when the response omits one (two sibling paths already guard this).

### 10. Tree-endpoint maps errors by matching exception message strings ⬜ `[low / robustness]`
Rewording a message silently changes the HTTP status.
- `backend/src/intric/integration/presentation/integration_router.py:388-412`
- **Plan:** raise typed domain exceptions and map those.

### 11. No stuck-job detection for SharePoint sync ⬜ `[medium / robustness]`
Hard crash mid-sync: arq does not retry, the Job row stays `IN_PROGRESS` forever. Crawl has an
OrphanWatchdog; sync does not.
- **Plan:** sweeper mirroring the crawl OrphanWatchdog.

### 12. Subscription health: record + act ✅ (data) / ⬜ (escalation) — GH 189874639
- **Done (WIP):** `consecutive_renewal_failures`, `last_renewal_failed_at`, `last_renewal_error`,
  `last_webhook_received_at` plumbed end-to-end; worker records failures; webhook records arrivals;
  admin API exposes them.
- **Remaining (optional):** a computed `needs_attention` flag / threshold escalation surface.

---

## P2 — Architecture / maintainability (safe subset)

### 13. Inverted DDD: domain imports from infrastructure AND presentation ⬜ `[medium]`
- `backend/src/intric/integration/domain/entities/oauth_token.py:8,13`
- `backend/src/intric/integration/domain/factories/oauth_token_factory.py:11-12`
- `backend/src/intric/integration/domain/entities/sync_log.py:6`
- **Plan:** relocate shared types (`OAuthResource`, `IntegrationType`) to `domain/value_objects`. (Assess ripple first — `IntegrationType` is widely imported from presentation.)

### 14. admin_sharepoint_router provisioning logic copy-pasted between two endpoints ⬜ `[small]`
- `backend/src/intric/integration/presentation/admin_sharepoint_router.py` (~75 lines duplicated)
- **Plan:** extract a shared provisioning helper.

---

## ⏭️ Deferred (large / low value — separate focused work)

- Full god-object split of `sharepoint_content_service.py` (1745 lines) and `admin_sharepoint_router.py` (1201 lines). Refactor opportunistically, not as a bundled change.
- Cross-process refresh-token lock (`asyncio.Lock` is process-local; backend/worker are separate containers). Narrow window, Entra grace period, recoverable.
- Webhook ACK-202-then-process-async. Current handler already enqueues arq jobs rather than syncing inline, so risk is lower; revisit if Graph delivery timeouts appear.
- Subscription create check-then-act race (orphan Graph subscription, self-heals in ~29 days).

## ❌ Skip (against Graph's contract / not applicable)

- **GH 189875010 — proactive delta-token refresh.** SharePoint/OneDrive delta tokens have no documented
  proactive expiry; reactive 410 (`resyncRequired`) handling is the correct model and is already implemented.
- **GH 189874886 — webhook payload encryption / rich notifications.** SharePoint/OneDrive notifications are
  "thin" and carry no resource data; `includeResourceData` / rich notifications are primarily an
  Outlook/Teams concept. clientState + delta fetch is the right model here. Harden clientState instead (item 5).

---

## GitHub findings → verdict

| Finding | Verdict | Note |
|---|---|---|
| 189874542 orphaned info_blobs | fix (partial done) | items 3 + 6 |
| 189874639 subscription health | fix (data done) | item 12 |
| 189874729 audit trail | partial / later | security-relevant rejections already logged; audit table low priority |
| 189874886 payload encryption | ❌ skip (SharePoint) | thin notifications; harden clientState instead |
| 189875010 proactive delta token | ❌ skip | against Graph contract; reactive 410 already correct |

---

## MCP — replacement, complement, or natural addition?

**Complement — not a replacement — and worth doing.**

MCP is a synchronous, pull-based tool protocol: no pre-indexing, no push/change notifications, no bulk
embedding, no own freshness mechanism. It must **not** replace the webhook+delta RAG ingestion (would
cost latency, recall, token cost, and resilience when Graph throttles).

Where MCP genuinely adds value (gaps the current design has):
1. **Query-time, permission-trimmed access** — strongest argument. Current pipeline indexes with a
   service-account/tenant-app and stores **one shared** info_blob set; it does not enforce the asking
   user's SharePoint ACL at retrieval. A Graph-MCP tool called with the end-user's delegated token
   returns only what that user may see.
2. Freshness-critical point lookups before delta has run.
3. Long-tail / unindexed content (skipped types, >50MB files, un-indexed sites).
4. Agentic write actions read-only RAG can never do.

eneo already has a complete MCP client subsystem (`mcp_servers/`, HTTP Streamable transport, per-space/
assistant enablement, `security_classification` gating). Adding Microsoft's official Graph MCP server is
configuration + a catalog entry, not new architecture. Do it as a separate, permission-aware layer
**after** the P0 security items land.
