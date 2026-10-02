# Svelte → web-next migration status, 2 October 2026

Inventory of frontend/apps/web routes and features against web-next, after the
ports landed on feat/web-next-astryx. Update this file when an item moves.

## Ported today (parity with develop, new standard)

- Image models in admin › Modeller (list, enable, add via the wizard, edit,
  delete with the "used by image generation" guard).
- Prompt library: search, sortable table, version history, read-only version
  view, restore.
- Chat: "Felsök" tab in the activity panel for `assistant_debug` users (turn
  diagnostics, skill activation evidence), reasoning-effort selector beside the
  model picker (stored on the personal assistant as in the Svelte app), insights
  period picker and "Utforska konversationer".
- Module login hand-off (`/module-login` route + failed page, same contract as
  the SvelteKit server route), `/invite` notice page, help centre link.

## Waiting for a product decision

- Zitadel and MobilityGuard sign-in links on the login page (Svelte builds them
  behind `newAuth`/`FORCE_LEGACY_AUTH`). Port or retire.
- `/invite/[organisationId]` as a real Zitadel registration flow (today a notice
  that points to the login page).
- First/last-name editing on the account page (Zitadel-backed in Svelte).

## Deliberately dropped (confirm)

- Legacy user groups admin area.
- Separate pages for templates and prompts (dialogs now).
- Locale-prefixed URLs (cookie now) and the mobile user-agent redirect.

## Not in either app (new work, see the AI SDK handover)

- Documents/artifacts side panel, MCP Apps (`ui://` resources), chat dictation.

## Known differences kept on purpose

- Create assistant/app/group chat opens the editor directly with a default name.
- Admin landing is an overview; feature toggles and the audit retention policy
  live under Inställningar.
- Answers render in the app's sans; `font-voice` keeps the serif available.
