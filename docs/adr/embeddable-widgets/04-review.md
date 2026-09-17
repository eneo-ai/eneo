# Embeddable Widgets — Plan review log

A self-review of the first draft of this plan against current practice (OpenAI ChatKit, Intercom Messenger, Dify's `embed.js`, Flowise embed, Chrome storage partitioning, ALTCHA, WCAG 2.2, AI Act Art. 50). Each finding names what the draft said, why it was wrong or weak, and what the plan now says.

| # | Draft | Problem | Resolution |
|---|---|---|---|
| 1 | Mint the visitor token on iframe load | Sets storage and spends a proof of work for every page view, including visitors who never chat; also weakens the "strictly necessary storage" argument | Lazy identity: challenge pre-fetched on composer focus, token minted and `visitor_id` stored on first send ([02](02-frontend.md)) |
| 2 | Loader as ES module `import` from a CDN (Flowise style) | Breaks in CMS script modules and older integrations that inject classic scripts; `type=module` cannot be `async`-loaded from all CMSs | Classic IIFE with `async`, custom element registered on load, pre-init command queue ([02](02-frontend.md)) |
| 3 | Host origin passed by the loader is treated as an authorization input | The embedder controls that value; using it for access decisions is security theatre | It is used only as the `postMessage` target/expected origin (a lie only hurts the liar). The enforceable gate is `frame-ancestors`; the API path is protected by ALTCHA, limits and budget. Documented explicitly in [03](03-security-privacy-compliance.md) |
| 4 | Reuse the API-key rate limiter as-is | It limits per key; one abuser would exhaust the whole widget for every visitor | Per-visitor, per-IP and per-widget-per-day keys on the same atomic Redis primitive ([01](01-backend.md)) |
| 5 | Daily budget as a simple counter incremented after the answer | Concurrent requests overshoot the budget; a burst can spend far more than the cap | Reserve-then-settle with `INCRBY`/`DECRBY`; fail closed on Redis loss ([01](01-backend.md)) |
| 6 | Pause = `status=paused` only | Outstanding 15-minute tokens keep working after the kill switch | `token_generation` claim, bumped on pause/archive/config change, checked through a 30-second cache ([01](01-backend.md)) |
| 7 | Refresh tokens for visitor sessions | Adds a second secret to store for no benefit | Silent re-mint with `previous_token` inside a 60-minute grace, else a new challenge ([01](01-backend.md)) |
| 8 | `sandbox="allow-scripts allow-same-origin …"` described as isolation | For a frame that is same-origin with Eneo those two flags neutralise the sandbox as isolation; its real value is denying `allow-top-navigation` | Reworded: sandbox prevents the frame from navigating or hijacking the host page; isolation from the host comes from the cross-origin boundary ([02](02-frontend.md), [03](03-security-privacy-compliance.md)) |
| 9 | Streaming answers in an `aria-live` region | Screen readers would read every token fragment; unusable (WCAG 4.1.3 in spirit, and practice at Intercom/ChatKit is to announce completion) | `role="log"` list plus one polite announcement on completion/error ([02](02-frontend.md)) |
| 10 | Dify-style icon-only launcher with hard-coded `z-index: 2147483647` | Dify's loader lacks `aria-expanded`, focus return and text alternatives; max z-index breaks host overlays | Real button semantics, focus management, `--eneo-widget-z` custom property ([02](02-frontend.md)) |
| 11 | Widget principal modelled as a synthetic `UserInDB` (like service keys) | Synthetic users leak into code paths that expect a `users` row (the image-generation note in `user_service.py` is the precedent) | Explicit `WidgetPrincipal` dataclass; ask path composes services without pretending to be a user ([01](01-backend.md)) |
| 12 | `settings.chatbot_widget` JSONB considered for widget config | It is a per-user preferences bag (copy format, API-key notifications) and cannot hold per-space config | Left untouched; a rename to `preferences` is a separate chore ([00](00-overview.md)) |
| 13 | Public config included `allowed_origins` so the embed page could validate the parent | Leaks the tenant's site map and gains nothing (see #3) | Removed from the public model ([01](01-backend.md)) |
| 14 | Stand-alone `mode=full` page inherited the widget's `frame-ancestors` | A full page has no reason to be framed; framing it re-enables clickjacking-style overlays | `frame-ancestors 'self'` for `mode=full` ([02](02-frontend.md)) |
| 15 | Cloudflare Turnstile as the bot check | Third-party JavaScript and IP transfer on a Swedish municipal site; conflicts with the no-third-party rule | ALTCHA, self-hosted, MIT, WCAG 2.2 AA, no cookies ([01](01-backend.md), [03](03-security-privacy-compliance.md)) |
| 16 | Tenant admin creates and configures widgets | Too narrow: municipalities want editors to prepare and preview, admins to approve | Split: `Permission.WIDGETS` for configuration, `Permission.ADMIN` for activation; pause allowed for editors so an incident can be stopped fast ([01](01-backend.md)) |
| 17 | Build the embed page as its own tiny app to keep it small | Duplicates the streaming/citation/feedback stack and the WCAG work; the prototype already showed `ConversationView` renders outside `(app)` | Reuse with an explicit `WidgetAppContext` and a transport seam in `ChatService` ([02](02-frontend.md)) |
| 18 | Insights excluded widget sessions "for privacy" | Editors need to see what visitors ask to improve the assistant; the sessions have no user and are already pseudonymous | Included, tagged `source=widget`, never in per-user views ([01](01-backend.md)) |
| 19 | `retention_days` only | Some tenants will require "store nothing" | `0` = stream only, no persistence, no follow-ups ([01](01-backend.md)) |
| 20 | Unversioned `postMessage` messages | Loader and embed page ship independently (floating `v1`); an unversioned protocol cannot evolve safely | `{ ns, v, type, payload }` with `v: 1`; the embed page must accept `v ≤ current` ([02](02-frontend.md)) |

## Checked and kept

- **Loader + iframe over shadow-DOM-only rendering.** ChatKit (web component around an OpenAI-hosted iframe), Intercom, Dify and Stripe all isolate the UI in a frame; Flowise is the shadow-DOM exception and needs a CORS proxy with a domain allowlist to hide its ids. The hybrid (shadow-DOM launcher, iframe panel) keeps the launcher in the host tab order and the chat isolated.
- **Short-lived, backend-minted client credentials** (ChatKit `client_secret`, Intercom JWT) rather than a publishable key in page source.
- **Partitioned storage** as a feature, not a bug: continuity on one site, no cross-site tracking.
- **Same-origin API from the iframe**: removes CORS and host-CSP `connect-src` requirements; nothing in the host page ever holds a credential.

## Deviations recorded during implementation

| # | Plan said | Implementation | Why |
|---|---|---|---|
| D1 | Widget principal as a `WidgetPrincipal` dataclass, never a synthetic `UserInDB` (#11) | The public `ask` runs with a synthetic visitor `UserInDB` carrying `active_widget` (same pattern as service keys' `active_api_key`); `WidgetPrincipal` is what the token dependency produces and what widget code reasons about | `AssistantService.ask` is ~400 lines coupled to the container user (space actor, governance, skills, files, streaming, persistence). Reimplementing it for a second principal type was the larger risk. The one place ownership is decided — `SessionService._principal_columns` — now returns widget + visitor, the space actor grants the visitor `VIEWER` only in the widget's own space, and the synthetic user has no permissions, so the leakage concern in #11 is contained to a role rather than a user. |
| D2 | 30-second generation cache backed by Redis | The widget row is read per request by unique `public_id` | One indexed lookup that is needed anyway for status and limits; pause takes effect immediately. |
| D3 | `config/` in the ask PR | Delivered with the visitor-token PR | The embed page needs it before the ask path exists. |
| D4 | Widget sessions included in Insights tagged `source=widget` | Deferred | The Insights repository inner-joins `users` on `sessions.user_id` in eleven places; widening it is its own change and is tracked as a follow-up on the epic. |
| D5 | `retention_days=0` never creates a session row | The session is created for the streaming turn and deleted when the stream finishes | The streaming pipeline persists placeholder rows before the model answers (stream-abort fix); deleting after settlement keeps that path intact and leaves nothing behind. |
| D7 | `config/` never includes allowed origins (#13) | `config/` includes `frame_ancestors` (the CSP host sources derived from the allowed origins) | The embed page's `frame-ancestors` response header exposes the same list to anyone who loads it; hiding it from the config gained nothing and forced the SvelteKit server to fetch it another way. |
| D8 | Visitor authorization via the space actor's role only | The space actor's tenant-level gate (`tenant_permits`) also recognises widget visitors: READ on ASSISTANT passes, everything else is denied, in addition to the VIEWER role in the widget's space | Every tenant-permission gate would otherwise require the synthetic visitor to carry `Permission.ASSISTANTS`, which is broader than "may ask this widget's assistant". |
| D9 | Own ALTCHA solver in a Web Worker | The `altcha` npm widget (v3, MIT, ~34 kB gz) in `display="invisible"` inside a `hidden aria-hidden` wrapper, fetching the challenge from the widget's challenge URL and solved on the first send | The v2 protocol is iterated SHA-256 (`cost` rounds per attempt); a hand-written WebCrypto solver would be far slower than the widget's optimised workers. The workers are blob: URLs, so the embed route's CSP adds `worker-src 'self' blob:`. |
| D10 | Visitors see the answering model in the first chunk (inherited from the conversation protocol) | The widget ask strips `completion_model` before streaming | Model names and pricing are internal configuration; the visitor only needs the answer. |
| D6 | Budget reservation from the model's `max_completion_tokens` | Fixed `widget_budget_reservation_tokens` (default 8 000), settled to the real prompt + completion tokens of the last question | Simple and sufficient to prevent overshoot; tunable per deployment. |

## Still open after review

- Exact split of `ConversationView` dependencies on `(app)` context is unknown until the Phase 2 spike; the plan budgets it as a task, not a risk to the architecture.
- `style-src 'unsafe-inline'` should be eliminated with a nonce before Phase 4 closes.
- Whether Traefik's rate-limit middleware belongs in the deployment template as defence in depth (proposal: yes, on `/api/v1/widgets/` and `/embed/`, in Phase 5).
