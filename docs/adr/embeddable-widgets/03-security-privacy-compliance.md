# Embeddable Widgets — Security, privacy and compliance

Companion to [00-overview.md](00-overview.md).

## Threat model

| Threat | Control | Where |
|---|---|---|
| Host site embeds a widget it is not allowed to | `frame-ancestors` from `widget.allowed_origins` — enforced by the browser, cannot be spoofed by the embedder | embed page headers |
| Scripted abuse of the public ask endpoint (cost) | ALTCHA proof of work to mint; per-visitor and per-IP rate limits; daily token budget with reserve-then-settle; pause bumps `token_generation` → all tokens die within seconds | backend |
| Visitor A reads visitor B's conversation | sessions keyed by `(widget_id, visitor_id)`; any mismatch is 404; no listing endpoint for visitors | backend |
| Stolen visitor token | 15-minute lifetime, bound to one widget and generation, useless for anything but that widget's ask/feedback | token design |
| Widget used to reach tools, uploads, web search, MCP, other assistants | ask path hard-disables capabilities/MCP/files regardless of assistant config; scope is one target | `WidgetAskService` |
| Prompt injection through the visitor question | same posture as any public chatbot: knowledge-only assistant, no tools, governance `effective_config`; answers are rendered through the existing sanitised Markdown pipeline (no raw HTML) | assistant config + UI |
| Clickjacking of the Eneo app itself | Phase 0: `frame-ancestors 'none'` + `X-Frame-Options: DENY` app-wide; only `/embed` overrides | hooks |
| Host page reads or manipulates the chat DOM (host XSS) | chat runs in a cross-origin iframe; the loader's shadow root holds only the launcher; the postMessage surface carries no secrets (open/close/resize/theme/context) | architecture |
| Iframe navigates or pops out of the host page | `sandbox` without `allow-top-navigation`; popups only for citation links (`allow-popups`, `rel="noopener"`) | loader |
| Loader script tampering | served from Eneo over HTTPS; pinned URLs with SRI available; floating `v1` documented as auto-updating | route |
| Leaking configuration to the public | `config/` returns display fields only; `allowed_origins`, limits (except question length), ids and model names stay private | public config model |
| Logging question content | question/answer text never at info level; OTEL spans carry ids and sizes only; the callback-style "no query strings in ingress logs" rule applies to `/embed?origin=` (no secrets there anyway) | logging policy |
| Redis outage | fail closed for limits and budget by default (`widget_rate_limit_fail_open=false`) | settings |

What the origin allowlist does **not** do: it does not stop a script from calling `/api/v1/widgets/{public_id}/ask/` directly with a forged `Origin`. That is by design — every public chatbot has this property. The controls for that path are ALTCHA, rate limits and the budget. The allowlist controls *where the UI may render* and is documented as such in the admin page help text.

## Headers on the embed page

```
Content-Security-Policy: default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline';
                         img-src 'self' data: blob:; connect-src 'self'; font-src 'self';
                         frame-ancestors 'self' https://www.kommun.se https://*.kommun.se;
                         base-uri 'none'; form-action 'self'
Referrer-Policy: strict-origin-when-cross-origin
Permissions-Policy: camera=(), microphone=(), geolocation=(), payment=()
X-Content-Type-Options: nosniff
Cache-Control: no-store
```

`style-src 'unsafe-inline'` is only needed if the theme colour is injected as an inline style; the plan sets it through a `<style>` nonce from SvelteKit's CSP config instead, so the target is to drop `'unsafe-inline'` before Phase 4 closes. No third-party script, font or analytics ever loads inside the iframe.

## Storage and cookies

- The embed page sets **no cookies**. State is `localStorage` in the iframe: `visitor_id` with its server-issued `visitor_key`, the current token, last `session_id`, dismissed hints. The key is what makes the pseudonym unforgeable: without it the server issues a new id, so nobody can claim another visitor's conversations. Chrome 115+, Firefox and Safari partition this per top-level site, so it works across pages of `kommun.se` and cannot track a visitor across sites.
- Nothing is written before the visitor sends a message (Lagen om elektronisk kommunikation: storage strictly necessary for a service the user requested). The admin page ships a ready-made sentence for the host site's cookie/storage notice.
- The host page never receives visitor identifiers.

## GDPR

- Conversations may contain personal data typed by the visitor. The data controller is the municipality (tenant); Eneo is a processor in hosted setups. The plan therefore gives every widget: a non-removable personal-data notice, a privacy URL, configurable retention with automatic deletion, and `retention_days=0` for "do not store".
- Recommend a DPIA before the first activation; the docs page links DIGG/IMY's guidelines for generative AI in the public sector and includes a DPIA checklist specific to widgets (purpose, data flows, retention, model provider, sub-processors).
- Visitor identifiers are random UUIDs with no link to a person; IP addresses are used only transiently for rate limiting (Redis keys, 60-minute TTL) and are not stored with sessions.
- Feedback free text is off by default (`store_feedback_text=false`).

## EU AI Act, Article 50

Transparency obligations for AI systems interacting with natural persons apply since **2 August 2026**. The widget renders the `subtitle` text under the title on every load; it cannot be empty (activation blocker), only reworded, and it defaults to an AI disclosure. Default (sv): "Du chattar med en AI-assistent. Svaren kan innehålla fel – kontrollera viktig information." The stand-alone page shows the same text in the header.

## DOS-lagen / EN 301 549

The widget becomes part of the municipality's website and must be covered by its accessibility statement. Phase 4 delivers: an accessibility statement template (sv/en) describing the widget, the WCAG acceptance table from [02-frontend.md](02-frontend.md) as an auditable checklist, and axe results in CI. Konsumentverket's AI chat (separate subdomain, own statement, disclosure, personal-data notice) is the reference example for how a Swedish authority presents this.

## Incident response

- **Pause** (one click, space editor or tenant admin): visitors get "chatten är pausad", tokens die within the generation-cache window, audit event written.
- **Budget exhausted**: automatic; admin notification through the existing notification channel (same mechanism as API-key expiry notices); visitors see a friendly "kom tillbaka senare".
- **Origin misuse suspected**: edit `allowed_origins` → generation bump → the browser stops rendering the iframe on the removed origin on next load.
- **Rotate**: archiving a widget and creating a new one yields a new `public_id`; there is no secret to rotate.

## Compliance checklist before first production activation

- [ ] Phase 0 app-wide `frame-ancestors 'none'` merged
- [ ] DPIA done by the tenant; privacy URL set
- [ ] AI disclosure text reviewed by the tenant
- [ ] Accessibility statement updated on the host site
- [ ] Daily budget and retention set consciously (not defaults) by the tenant admin
- [ ] Load test: 200 concurrent visitors, limits and budget behave, no unmetered path
