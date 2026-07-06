# Web-next improvement potential — 2026-07-06

Nice-to-have opportunities collected during the 2026-07-06 migration review
(`REVIEW-web-next-2026-07-06.md`). Nothing here is a parity gap or a bug — those
live in the review doc. Each item is tagged **[logic]** (robustness/correctness
hardening) or **[ux]**. Ordered roughly by value within each area.

## Platform / architecture

- **[logic] Serialize editor autosaves.** One in-flight mutation queue per
  resource (or field-scoped cache merges) in `use-assistant.ts` /
  `use-group-chat.ts` / `use-app.ts` removes the whole out-of-order class of
  problems and makes autosave trivially safe to extend. (Remedy for review §3.1
  but worth doing as a shared composite, not a spot fix.)
- **[ux] Per-field save status.** Give each autosave field a unique status key
  (`general.name` not `general`) and surface per-field dirty/error markers next
  to the input; keep the header chip as the aggregate. `use-autosave.ts`,
  `save-status.tsx`.
- **[logic] Port the old lint guardrails.** ESLint rules equivalent to
  `intric/no-hardcoded-text` and `intric/no-raw-color` for web-next. i18n is
  clean today purely by discipline; raw palette colors are already at ~236
  occurrences. Cheap insurance, big drift prevention.
- **[logic] `Cache-Control: no-store`** on both proxy routes
  (`api/eneo/[...path]/route.ts`, `api/chat/route.ts`).
- **[logic] Extend the E2E smoke suite** with one chat round-trip and one
  space/knowledge flow — the two highest-risk uncovered paths today.
- **[ux] Gate `/(app)/chat-mock`** (and any design-preview routes) behind
  dev-only.
- **[logic] Dynamic-import recharts** in `admin/insights/insights-page.tsx`
  (only consumer) to keep it out of the shared client bundle.
- **[ux] Add `(public)/error.tsx` and an `(app)/not-found.tsx`** so failures
  keep the app chrome; redact `error.message` for non-`EneoApiError`s.
- **[ux] Skip-to-content link + default accessible names** for the vendored
  ai-elements icon buttons (scroll-to-bottom, download, copy) — small, global
  a11y wins.

## Chat

- **[logic] Richer citation previews.** `providerMetadata.eneo` already carries
  the full info-blob (incl. text); the hover preview (`citation.tsx:112-120`)
  shows only title+host. Rendering the blob text restores old-app preview parity
  once inref parsing lands. Same for URL-less source chips
  (`message-parts.tsx:93-102`) — make them open a content preview instead of
  being inert.
- **[logic] Verify `onFinish` fires after `stop()`** (AI SDK v6 abort) — history
  invalidation + auto-title depend on it (`chat-view.tsx:200-213`); the old app
  reloaded history explicitly on abort.
- **[logic] Harden the bridge against pre-succeeded tools** — emit the
  tool-input phase before `tool-output-available` when the first snapshot is
  already terminal (`ui_message_stream.py:82-115`).
- **[ux] History sidebar timestamps.** The old history table showed created-at;
  relative times would help long histories (`history-panel.tsx`).
- **[ux] Dashboard chat error state.** `dashboard-chat.client.tsx:17-30` leaves
  a permanent skeleton if the assistant fetch fails.

## Builders

- **[ux] Commit the prompt on debounce/`visibilitychange`**, and extend the
  unload guard to dirty (not just in-flight) state — `instructions-section.tsx`.
- **[logic] Clamp numeric kwargs to `kwargCapability` min/max on blur** instead
  of posting out-of-range values for a 422 (`ai-section.tsx:376-395`,
  `service-editor.tsx:230-244`).
- **[ux] Wire `accept` + size limits from `allowed_attachments`** into the
  attachments dropzone (`attachments-section.tsx:489`) — every rejection is
  currently a server round-trip.
- **[ux] Client-side name filter on the tile grids** (assistants/apps/services)
  to restore old table search for large spaces.
- **[logic] Move `getResultTitle` strings behind `t()`** with a translated
  fallback title (`apps/apps.ts:59-64`).

## Knowledge / jobs

- **[ux] Fast-poll crawl runs after "Sync now"** — gate the 30s poll on an
  active run and fast-poll after `trackJob` (`website-detail.client.tsx:98-101`),
  like `result-detail.tsx` already does.
- **[logic] Unify the "skipped" status constant** — `crawl-runs.tsx:17` and
  `websites.tsx:45` carry diverging copies of `SKIPPED_PREFIX`.
- **[ux] Translate raw backend status strings** in sync-history badges
  (`sync-history.tsx:42`).
- **[logic] Add `["app-runs"]` to `JOB_INVALIDATION_KEYS`** (`use-jobs.tsx:43-50`)
  so run-detail freshness doesn't depend on its own poll.
- **[ux] Render incompatible knowledge sections with the
  `sources_not_compatible` message** instead of dropping them silently
  (`knowledge-picker.tsx:143-146` currently makes that branch unreachable).
- **[logic] Treat unknown job statuses as terminal explicitly**
  (`use-jobs.tsx:52-53`, old app used an allowlist).

## Admin

- **[ux] Inline per-entity impact list in the migrate dialog** — the data is
  already available via `modelUsageDetailsQueryOptions`; old app showed it,
  new shows counts only.
- **[ux] Restore aggregate deprecated/retiring banners** on the models page
  (old had `role="alert"` count banners; new only tints rows — easy to miss at
  scale).
- **[ux] Model detail dialog completeness** — InfoTab omits tool-calling badge,
  costs, litellm `name`, org and classification that the old dialog showed.
- **[logic] Feed `ProviderEditDialog` the real `ModelProvider`** already in the
  query cache instead of a fabricated object (`provider-overview.tsx:145-156`).
- **[logic] Decide on migrated-model visibility** in provider cards (old
  filtered them out; new shows them unmarked) — show-with-badge or hide.
- **[logic] Map `entity_type` to i18n labels** in usage details and drop the
  misleading `?? "app"` fallback (`models.ts:84-91`).
- **[ux] Provider select in the wizard** could show logo + key status like the
  provider cards do (`add-model-wizard.tsx:285-296`).
- **[logic] GDPR user picker should search all user states** — deactivated users
  (a prime GDPR target) can't currently be selected (`audit-filters.tsx:46-50`).
- **[ux] Audit retention panel** uses a local dirty-Save button — either
  autosave like the rest of settings or document it as deliberate for a
  compliance field (`retention-panel.tsx:54`).
- **[logic] Re-sync feature toggles after `router.refresh()`** — state seeds
  once and never re-syncs with server changes (`feature-toggles.tsx:33-35`).
- **[logic] Clamp URL `page` against `total_pages`** on users admin
  (`users-page.tsx:38`); add the missing `generateMetadata` on `usage/page.tsx`.
- **[ux] Mobile admin nav** — the sidebar is `hidden md:block` with no
  alternative below `md` (`admin/layout.tsx:22`).
- **[ux] Classification delete impact warning + reorder announcement** —
  reorder is keyboard-accessible but silent; delete shows no affected
  spaces/models (`classifications-page.tsx`).
- **[ux] `aria-pressed`/selected styling on insights range presets**
  (`insights-page.tsx:256-265`, the Compare button next to them does it right).

## Auth / shell / account / spaces

- **[ux] SSO auto-redirect** when SSO is the only login method (old behavior),
  with `?showLogin=true` as the escape hatch; hide the password form for
  SSO-only tenants.
- **[ux] Space overview density** — old greeted personal users by name, showed
  member chips and per-type tiles (services/collections/websites) deep-linking
  into knowledge tabs; new collapses to one knowledge count.
- **[ux] Spaces list cards** offer only delete; add an Edit/settings shortcut
  for space admins (`spaces-list.client.tsx`).
- **[logic] Debounce member search** in AddMemberDialog (query per keystroke,
  `space-members.tsx`); use `placeholderData` to avoid flicker.
- **[ux] API keys table skeleton** while `isPending`, and surface the old
  "no create permission" notice instead of hiding the create button.
- **[logic] `autoComplete="username"`** on the login identifier field (password
  managers key on it; old app used it).
- **[ux] Dashboard scroll restoration** (old kept it in sessionStorage — the
  dashboard is the phone-oriented surface).
- **[ux] Localized default-assistant tile name** ("Personal assistant") on the
  dashboard instead of the raw backend name.
