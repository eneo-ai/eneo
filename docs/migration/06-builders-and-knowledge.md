# Phase 6 — Builders (assistants, group chats, apps, services) and knowledge

## Goal
Everything a space editor configures: assistant CRUD + editor (prompt, knowledge selection, MCP servers, publish, templates), group-chat editor, apps (CRUD, run with form inputs, results), services (CRUD + run), and the knowledge hub (collections, websites/crawls, integrations) including uploads with job tracking.

## Prerequisites
- Phase 5 gate green (chat exists, so configuring assistants is immediately verifiable in-app).
- Source references: `frontend/apps/web/src/routes/(app)/spaces/[spaceId]/{assistants,group-chats,apps,services,knowledge}`, `AttachmentManager.ts`, `JobManager.ts`, templates plumbing (`TemplateController.ts`).

## Scope
**In**:
- Assistants: list, create (with template picker if tenant templates enabled), editor (name/description/prompt, completion model + kwargs, knowledge attach: collections/websites/integration knowledge, MCP server attach/detach, attachments rules, publish/unpublish, transfer), delete. Help-assistant redirect rule (help assistants edit in admin) preserved.
- Group chats: create, editor (assistant multi-select, mention mode, response labels, icon upload, publish, insights toggle), delete.
- Apps: list/create/editor (input config, prompt, model), run page (form inputs incl. file/audio inputs, run, results list, result detail), delete, publish. Dashboard app routes (`/dashboard/app/[appId]`, `/results/[resultId]`).
- Services: list, create, editor, run (single input → output), delete.
- Knowledge hub: tabs Collections/Websites/Integrations. Collections: create (embedding model), upload documents (multipart, progress, job tracking), blob list, delete. Websites: create (URL, crawl interval, embedding model), recrawl, bulk recrawl, run history, blob list. Integrations: available list, OAuth connect popup flow (incl. `/integrations/callback/token` for service accounts), preview + import (single/batch), sync, sync-log dialog, rename/delete wrappers.
- Job tracking: port JobManager as a `useJobs` Query-based poller (2s fast / 30s slow adaptive), completion → invalidate affected keys; header job indicator. WebSocket `app_run_updates` is NOT ported initially: polling covers parity; revisit with RB-4 (ticket endpoint) only if app-run UX measurably suffers.
**Out**: admin-side templates/integrations/MCP administration (Phase 7), insights (Phase 7).

## Design notes
- Editors are the highest-complexity forms: react-hook-form + zod per editor, with an unsaved-changes guard (the Svelte app has confirm-on-leave for group chats; generalize it).
- Multipart uploads go through the `/api/eneo` proxy; verify streamed request bodies (Node `duplex: "half"`) and size limits in the route handler config. Progress: fetch upload progress is not natively observable; either accept indeterminate progress per file (queue position + spinner) or upload via a dedicated route handler that reports progress server-side. Decide during build; do not block on byte-level progress parity.
- Icon upload (group chats/assistants) and signed-URL display reuse the files endpoints.
- Template flows: space-level create-from-template adapters (admin template CRUD is Phase 7).
- MCP attach UI on the assistant editor consumes `GET/POST/DELETE /api/v1/assistants/{id}/mcp-servers/…` and the space-settings MCP section stubbed in Phase 4 gets completed here.

## Step-by-step
1. `useJobs` poller + header indicator + invalidation contract (test with a slow fixture).
2. Knowledge hub: collections (incl. uploads) → websites (incl. crawl runs) → integrations (OAuth popup, preview/import, sync logs).
3. Assistant list + editor + publish/transfer + template create path; verify immediately via Phase 5 chat (edit prompt → behavior changes).
4. Group-chat editor.
5. Apps: editor, run page with input forms, results; dashboard app routes.
6. Services: CRUD + run.

## Files/structure created (representative)
```
src/features/jobs/{use-jobs.ts, job-indicator.tsx}
src/app/(app)/spaces/[spaceId]/assistants/{page.tsx, [assistantId]/edit/page.tsx}
src/app/(app)/spaces/[spaceId]/group-chats/[groupChatId]/edit/page.tsx
src/app/(app)/spaces/[spaceId]/apps/{page.tsx, [appId]/{page.tsx, edit/page.tsx, results/[resultId]/page.tsx}}
src/app/(app)/spaces/[spaceId]/services/{page.tsx, [serviceId]/page.tsx}
src/app/(app)/spaces/[spaceId]/knowledge/{page.tsx, collections/[collectionId]/page.tsx, websites/[id]/page.tsx, integrations/wrapper/[wrapperId]/page.tsx}
src/app/integrations/callback/token/route.ts
src/features/{uploads,knowledge,builders}/…
```

## VALIDATION GATE
1. `bun run check && bun run lint && bun run test && bun run build` — green.
2. Manual, against dev backend:
   - Create an assistant from scratch and one from a template; edit its prompt; chat reflects the change. Attach a collection; ask a question answered only by an uploaded document; references cite it.
   - Upload 3 documents to a collection → job indicator shows progress states → completion refreshes the blob list without manual reload.
   - Create a website with a crawlable URL → trigger recrawl → run history shows the run; bulk recrawl works on 2+ sites.
   - Connect an integration via OAuth popup (dev tenant with one configured provider), preview, import an item, see it as knowledge, sync log dialog shows the run.
   - Group chat: create with 2 assistants, mention mode on; verified in chat (Phase 5 mention flow targets correctly); icon upload renders.
   - App: create with a text + file input, run it, see the result in the list and the detail page; same from the dashboard app route.
   - Service: create and run with a sample input.
   - Publish/unpublish an assistant and an app; a viewer-role user sees published ones only (dashboard `only_published` behavior).
3. Permission checks: editor vs viewer affordances on every list page.
4. RB-5 workaround inventory updated for every POST-as-update endpoint touched.

## Exit criteria
A space editor can build and operate everything they can in the old app; knowledge round-trips from upload to cited chat answer.

## Risks / unknowns
- This is the widest phase; if it sprawls, split the gate: 6a (knowledge + jobs), 6b (builders). The order above already supports that cut.
- Integration OAuth popups depend on provider config in the dev environment; if none is configured, gate that item on a staging environment and say so in the phase PR.
- Upload progress fidelity (see design note); agree on the acceptable UX before building.
- App input forms are dynamically shaped by app config; enumerate the input field types from the backend models before designing the form renderer.
