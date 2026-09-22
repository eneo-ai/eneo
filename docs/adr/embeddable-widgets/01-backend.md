# Embeddable Widgets — Backend

Companion to [00-overview.md](00-overview.md). Paths are relative to `backend/src/eneo/`.

## Data model

### `widgets`

| Column | Type | Notes |
|---|---|---|
| `id` | UUID PK | internal id, used by admin routes |
| `public_id` | text, unique | `wgt_` + 22 base62 chars, generated server-side; the only identifier in page source |
| `tenant_id` | UUID FK tenants | data partition |
| `space_id` | UUID FK spaces ON DELETE CASCADE | owning space; editors manage it there |
| `target_type` | text | `assistant` in v1; enum kept open for `group_chat`, `app` |
| `target_id` | UUID | FK enforced in service layer per `target_type`; assistant deletion cascades via a trigger-free nightly consistency check + `ON DELETE` handled in `AssistantService.delete` |
| `status` | text | `draft` → `active` → `paused` → `archived`; only `active` serves visitors |
| `token_generation` | int, default 0 | bumped on pause/archive/config change that must invalidate outstanding visitor tokens |
| `name` | text | internal label |
| `texts` | JSONB | `title`, `welcome`, `placeholder`, `suggested_questions[]` (max 4), `subtitle` (required; an AI disclosure by default), `footer_text`, `footer_link_url`, `footer_link_label` |
| `theme` | JSONB | `primary_color`, `color_scheme` (`auto`/`light`/`dark`), `position` (`bottom-right`/`bottom-left`), `launcher` (`bubble`/`bar`/`none`), `radius`, `logo_file_id` |
| `language` | text | `sv`, `en` or `auto` (follow host `<html lang>`) |
| `allowed_origins` | JSONB list | validated with `_validate_origin_format` rules; wildcards `https://*.kommun.se` allowed; at least one required to activate |
| `limits` | JSONB | `messages_per_visitor_10min` (default 10), `messages_per_ip_hour` (60), `daily_token_budget` (500k), `max_question_chars` (2000), `max_session_turns` (30) |
| `privacy` | JSONB | `retention_days` (30; `0` = do not persist), `store_feedback_text` (bool) |
| `bot_protection` | text | `altcha` (default) or `none` (sysadmin policy may forbid `none`) |
| `created_by`, `activated_by`, `activated_at`, `paused_at`, `created_at`, `updated_at` | | audit convenience; the audit log is the source of truth |

Indexes: `(tenant_id, status)`, unique `(public_id)`, `(space_id)`, `(target_type, target_id)`.

### `sessions` extensions

- `widget_id UUID NULL FK widgets ON DELETE CASCADE`, `visitor_id UUID NULL`.
- Replace the XOR check with *exactly one of* `user_id`, `api_key_id`, `widget_id`; `visitor_id IS NOT NULL` iff `widget_id IS NOT NULL`.
- Index `(widget_id, visitor_id, created_at DESC)` for follow-up ownership checks and retention.
- `SessionAdd`/`sessions_repo` get `widget_id`/`visitor_id` alongside the existing `api_key_id` principal scoping (`sessions_repo.py:228-290`).

### `widget_daily_usage`

UUID primary key, unique `(widget_id, day)`. Holds `questions`, `input_tokens`, `output_tokens`, `blocked_budget`, `blocked_rate` and `reserved_tokens`. PostgreSQL is the canonical owner of both completed usage and in-flight budget charges. The overview filters by tenant before aggregating and includes today's budget in that same query.

### `widget_budget_reservations`

One UUID receipt per admitted turn: widget, admission day, reserved token count and state (`reserved`, `settled`, `released`). No conversation content or visitor identifier. A conditional update of the daily row serializes admission; locking the receipt makes settlement/release idempotent. Receipt and daily total updates commit together in a short transaction independent of the streaming request. A process crash conservatively leaves unknown usage charged for its admission day. Receipts older than seven days are pruned by the widget maintenance job; daily totals remain.

### Concurrent changes and deletion ownership

`widgets.revision` increments on every mutation. PATCH, link-template and detach-template require the revision read by the editor; the repository also compares it atomically before updating. A stale revision returns `409 widget_revision_conflict`. Autosave stops for an explicit reload, and a late response cannot replace a newer lifecycle response. Pause and archive are the exception: they write only their lifecycle columns (`status`, `paused_at`, `token_generation`) without the revision check, so a kill switch never loses to a concurrent autosave and never overwrites one; the bumped revision then makes the stale editor's next save a 409.

### Templates: draft, release and locks

A template row holds the draft admins edit and, in `published`, the release widgets are held to. Linking (`POST /widgets/{id}/link-template/`, or `template_id` on create) requires a published template and copies the whole release onto the widget once. The release's `locked_groups` (`appearance`, `language`, `legal_texts`, `wording`) are written onto every active follower with each publication, in the same transaction and under `FOR UPDATE`; a publication whose locks changed bumps the followers' revision even when their values already match, so open editors reload and see the new locks. `PATCH /widgets/{id}/` answers `400 field_locked_by_template` when a locked field would change. Archived widgets keep their `template_id` as history but neither follow nor count as followers, so they never block `DELETE /admin/widget-templates/{id}/` (`409 template_in_use` otherwise). Suggested questions are never templated.

A database trigger removes a question's model log when its last question owner is deleted, including FK cascades from sessions, assistants and spaces. It does not sweep historical orphan logs whose ownership is no longer identifiable.

## Public API (`/api/v1/widgets/{public_id}/…`, no Eneo auth)

All routes: `response_model`/`responses.get_responses` per the route-metadata ratchet, `Cache-Control: no-store` except `config`, structured 4xx codes below, and a dedicated FastAPI dependency `get_widget_principal` that replaces `get_container(with_user=…)`.

| Method & path | Auth | Purpose |
|---|---|---|
| `GET config/` | none | `WidgetPublicConfig`: widget name, texts, theme, language, `bot_protection`, `limits.max_question_chars`, `token_generation`. `ETag` + `Cache-Control: public, max-age=60` (304 on `If-None-Match`). 404 unless `status=active`. Never includes `allowed_origins`, internal ids or model names. Delivered with the visitor-token PR (#848) because the embed page needs it before the ask path exists. |
| `GET challenge/` | none | ALTCHA challenge (`algorithm`, `challenge`, `salt`, `signature`, `maxnumber`). Rate limited per IP. |
| `POST visitor-sessions/` | none | Body: `{visitor_id?, visitor_key?, altcha?, previous_token?}`. Returns `{token, expires_in, visitor_id, visitor_key}`. Exactly one of `altcha` (new/expired visitor) or `previous_token` (silent rotation; accepted while the old token is valid or expired < 60 min and its `gen` still matches). A claimed `visitor_id` is honoured only with the `visitor_key` the server issued for it (HMAC over widget + visitor id, key derived from `url_signing_key`); otherwise a fresh pseudonym is issued, never an error. |
| `POST ask/` | visitor Bearer | Body `{question, session_id?}`. Always streams (`text/event-stream`), reusing the existing SSE event types. `session_id` must belong to `(widget_id, visitor_id)`. |
| `GET sessions/{session_id}/` | visitor Bearer | `SessionPublic` for the visitor's own session (history restore after reload). |
| `POST sessions/{session_id}/feedback/` | visitor Bearer | `SessionFeedback` (thumbs, optional text if `store_feedback_text`). |

Error codes: `widget_not_active` (404), `challenge_invalid`/`challenge_replayed` (400), `visitor_token_invalid` (401), `visitor_token_stale` (401, generation bumped — client re-mints), `rate_limited_visitor`/`rate_limited_ip` (429 + `Retry-After`), `budget_exhausted` (429, `Retry-After` until midnight tenant-local), `question_too_long` (400), `session_not_owned` (404 — never reveal existence).

### Visitor token

Signed with the existing `AuthService` primitives (same key/alg as `create_scoped_mcp_token`), claims:

```
token_use = "widget_visitor"
aud       = "eneo-widget:<widget.id>"
sub       = <visitor_id>          # UUIDv4, server-generated on first mint
wid       = <widget.id>, tid = <tenant_id>
gen       = <widget.token_generation>
iat, exp  = 15 min, jti
```

Verification: signature, `exp`, `aud`, `token_use`, and `gen == widget.token_generation`. The widget row is read per request by its unique `public_id` (one indexed lookup, also needed for the status check and limits), so pausing takes effect immediately; a generation cache can be added later if profiling shows the read matters. No refresh tokens: the client re-mints with `previous_token` inside a 60-minute grace after expiry.

### ALTCHA (proof of work)

- Server-side with the `altcha` Python library (v2 API): `create_challenge("SHA-256", cost, expires_at, hmac_secret)` returns `{parameters: {algorithm, cost, keyLength, keyPrefix, nonce, salt, expiresAt}, signature}`; the browser returns a base64 payload `{challenge, solution}` verified with `verify_solution`. The HMAC key is derived from `url_signing_key`, so challenges need no storage. `cost` is the expected hash count (`widget_altcha_cost`, default 50 000; ~0.25 s in Python, faster in browsers).
- Replay protection: the solved challenge's `nonce` is stored in Redis with `SET NX` for the challenge's remaining lifetime (`widget_altcha_challenge_ttl_seconds`, default 5 min).
- Challenge issuance is itself rate limited per IP (60/min) and per widget.
- `bot_protection=none` skips the challenge; the tenant policy (`WidgetPolicy`) may forbid it.

### Request limits (Redis) and daily budget (PostgreSQL)

Request-limit keys are namespaced `widget:<id>:…` and use `check_rate_limit` from `audit/infrastructure/rate_limiting.py`:

| Key | Window | Default |
|---|---|---|
| `visitor:<vid>` | 10 min | 10 questions |
| `ip:<ip>` | 60 min | 60 questions |
| `challenge:<ip>` / `mint:<ip>` | 1 min | 60 each |

Budget uses **reserve-then-settle** in PostgreSQL, with a default limit of 500,000 tokens per day in `WIDGET_BUDGET_TIMEZONE` (default `Europe/Stockholm`). The configured reservation (default 8,000 tokens) is an admission estimate; it does not bound the model's eventual consumption. Successful answers settle their own question's token counts against the admission day. Pre-stream failures release their reservation; interrupted streams retain their charge when usage is uncertain. Redis loss cannot reset the budget. `widget_rate_limit_fail_open` affects only request-rate and ALTCHA replay checks.

Client IP comes from `resolve_client_ip` (same trusted-proxy rules as API keys). Behind Traefik, Dokploy or any other reverse proxy `TRUSTED_PROXY_COUNT` (and `TRUSTED_PROXY_HEADERS`) **must** be set, or every visitor resolves to the proxy's address and the per-IP message and mint limits throttle the whole site after the first visitor's share; the docs guide says so in the operator section. IP limits are a backstop, not the primary control — CGNAT and campus networks share IPs.

An active widget whose assistant has been unpublished answers `404 widget_not_active` on the whole public surface (`get_active_widget` checks the target), the same as a pause; the admin overview lists the reason in `activation_blockers`.

### Ask path

`WidgetAskService` composes the existing services instead of duplicating them:

1. Resolve widget (`active`), verify token, enforce limits and budget, validate `question` length.
2. Load the target assistant through `AssistantService` **as the widget principal**: a `WidgetPrincipal` dataclass (not a synthetic `UserInDB`) carrying `tenant_id`, `widget_id`, `visitor_id`. `SpaceActor`/permission checks are bypassed by construction because the widget was authorized at activation time by a tenant admin; the ask path only needs the assistant's resolved config.
3. Build the `AskAssistant` payload with `stream=True`, `files=[]`, `tools=None`, every `CapabilityPurpose` disabled except plain completion + knowledge retrieval, and all MCP servers disabled. Governance `effective_config` still applies (model allowlist, prompt library, security classification).
   The ask uses the citing protocol (`version=2`): the model tags claims with `<inref/>` and only cited documents are returned as references, so the embed page can render numbered citations and a short source list. Retrieval is capped by `widget_retrieval_chunks` (default 30) instead of version 2's half-context default, keeping visitor questions inside the budget reservation.
4. Create/continue the session with `widget_id`/`visitor_id` and stream through the same `response_stream` layers as today (so new SSE event types keep flowing; see the three chunk-filter layers note in `docs/`).
5. Settle the durable receipt and daily usage atomically, then apply content retention even if settlement failed.

Retention: a worker cron job (`purge_widget_sessions`, daily 03:30 UTC, one transaction per widget) deletes widget sessions older than `privacy.retention_days`; `retention_days=0` deletes the session when streaming ends, independently of budget settlement, and includes pre-existing sessions in the next scheduled purge, so nothing outlives the turn and follow-ups answer 404.

## Admin API (Eneo session auth)

| Method & path | Permission | Notes |
|---|---|---|
| `GET /spaces/{space_id}/widgets/` | space member | list with status and 7-day usage |
| `POST /spaces/{space_id}/widgets/` | space editor + `Permission.WIDGETS` | create as `draft` for an assistant in that space |
| `GET/PATCH /widgets/{id}/` | space editor | config; PATCH bumps `token_generation` when `allowed_origins`, `limits`, `privacy` or `bot_protection` change |
| `POST /widgets/{id}/activate/` | tenant admin | requires `allowed_origins` non-empty, `subtitle` non-empty, assistant published; audited |
| `POST /widgets/{id}/pause/` · `archive/` | tenant admin (pause also space editor, so an editor can stop an incident) | bumps generation; audited |
| `GET /widgets/{id}/usage/?days=30` | space member | from `widget_daily_usage` |
| `POST /widgets/{id}/preview-token/` | space editor | visitor token whose `aud` carries `preview=1`; ask works only from Eneo's own origin and does not count towards the budget beyond a small preview allowance |
| `GET /widgets/{id}/snippet/` | space member | canonical embed snippet + pinned-version SRI hash (see 02-frontend) |

`Permission.WIDGETS` is a new tenant role permission (default in Owner/Admin and any role that already has `API_KEYS`), so tenants can delegate widget *configuration* without granting activation.

`WidgetPolicy` (tenant, sysadmin-managed like API-key policy): `max_daily_token_budget`, `allow_bot_protection_none`, `min_retention_days`/`max_retention_days`. (`max_active_widgets` was dropped during Phase 4, see 04-review D22; `GET /admin/widgets/` gives admins the overview instead.)

## Audit, observability, insights

- Audit events: `widget.created`, `widget.updated` (diff of non-secret fields), `widget.activated`, `widget.paused`, `widget.archived`, `widget.budget_exhausted` (once per day), `widget.policy_updated`.
- Metrics (OTEL): questions, blocked (by reason), latency to first token, tokens, per `widget_id`; no question text in logs or spans.
- Insights: widget sessions never appear in a user's conversation list (they have no `user_id`). Including them in the assistant's Insights is deferred (see 04-review D4).

## Testing

- Unit: policy validation, origin → CSP conversion, token claims/generation, ALTCHA verify + replay, pre-stream release, interrupted streams and cleanup after settlement failures.
- Integration (testcontainers): full mint → ask → follow-up → feedback; cross-visitor session access returns 404; stale writes cannot undo pause; retention including question-owned logs and `retention_days=0`; durable concurrent reservation and idempotent settlement/release; tenant-filtered overview in one query.
- Contract: `schema.d.ts` regenerated canonically (pre-push byte gate); route-metadata ratchet green.


## Deployment and recovery (next release on develop)

Apply migration `202609171600` before deploying the matching backend and frontend. Drain widget streams and stop old backend writers during the switch from Redis accounting to PostgreSQL; mixed versions cannot share reservations or the required revision contract. Completed usage already in `widget_daily_usage` is retained. No live migration or purge is performed by the code change itself.

The schema change is additive. Rollback requires draining streams again and deploying matched backend/frontend versions. Prefer leaving the added schema in place while investigating; downgrading removes reservation receipts and the log-deletion trigger. Deleted conversation content can only be recovered from a backup. Historical orphan model logs are not automatically removed because their widget/tenant ownership is no longer recoverable from the schema.
