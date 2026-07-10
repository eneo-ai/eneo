# Flow draft versioning — design spec

Status: proposal (frontend stopgap shipped separately; no backend work started).
Owner surface: Flows publish lifecycle.

## Problem

Editing a published flow today requires unpublishing it. Unpublish is
immediate and space-wide: colleagues lose a working flow until the editor
publishes again. The UI consequence is worse than the mechanics: a published
flow greets its owner with a warning banner, disabled fields, and a
destructive-styled button — a successful flow feels like an error state, so
cautious users never improve their flows and bold users interrupt service for
everyone else.

A confirmation dialog (shipped as a stopgap) makes the trade-off explicit but
does not remove it. The real fix is draft-alongside-published versioning: the
model used by CMSes, GitHub draft PRs, and API-gateway revision systems.

## Goal

- Editing never takes a running flow away from anyone.
- Publishing is an atomic swap from one reviewable state to another.
- Runs are always attributable to an exact immutable version (Bevisunderlag
  and EN 301 549 audit expectations already assume this).

Non-goals: multi-draft branching, collaborative simultaneous drafts, rollback
UI beyond re-publishing a previous version (can layer on later).

## Data model

Today `flows` carries builder state and a `published_version` marker, and runs
pin `flow_version` (visible in Historik). The spec keeps one mutable working
copy and immutable published snapshots:

- `flows` — the working copy (what the builder edits). Unchanged ownership,
  tenant scoping, audit hooks.
- `flow_versions` (exists in some form for run pinning today; extend or
  formalize) — immutable snapshots: `id`, `flow_id`, `version` (int,
  monotonic), `spec_json` (compiled steps + assistants + contracts),
  `published_at`, `published_by`, `retired_at NULL`.
- `flows.active_version_id NULL` — the currently runnable snapshot. NULL means
  never published (pure draft).
- Draft state indicator is derived, not stored: the working copy differs from
  the active snapshot ⇔ "Utkast v(N+1)" exists. A content hash
  (`flows.working_copy_hash` vs `flow_versions.spec_hash`) makes the
  comparison cheap and avoids a false "draft" after a no-op edit.

### Invariants

1. Runs reference `flow_versions.id`, never the working copy. In-flight runs
   are unaffected by publish/unpublish/edit (crash recovery and retries
   already assume immutable step specs).
2. `flow_versions` rows are append-only; retirement is a timestamp, not a
   delete (evidence trail).
3. Exactly one `active_version_id` per flow (or NULL).
4. Editing the working copy requires `flows_manage`; it never requires
   changing `active_version_id`.

## API surface (OpenAPI + generated-client impact)

- `POST /flows/{id}/publish` — snapshots the working copy into
  `flow_versions`, sets `active_version_id`, returns the new version. Replaces
  the current publish. Idempotent when the working copy hash equals the active
  snapshot hash (returns the existing version, no new row).
- `POST /flows/{id}/unpublish` — kept for the explicit "ta bort ur drift"
  action: clears `active_version_id` (snapshot remains for history/runs).
  No longer the path to editing.
- `GET /flows/{id}` — gains `active_version` (number + published_at) and
  `has_draft_changes: bool`. The builder no longer needs "published ⇒
  read-only" logic.
- `GET /flows/{id}/versions` — list for Historik/version picker.
- Runs API: unchanged (already version-pinned); `POST /flows/{id}/runs`
  resolves `active_version_id` and 409s with a typed error when NULL.

Audit: publish/unpublish keep their audit entries; add one for
"draft diverged from published" only if compliance asks (derived state —
default no).

## Runtime

- Celery workers load step specs from the pinned `flow_versions.spec_json` —
  no behavior change, but the loader must stop falling back to the live flow
  row (verify: the version-pinning boundary must be the snapshot, not the
  working copy).
- Triggers/schedules bind to the flow, resolve the active version at fire
  time; a NULL active version surfaces the existing "not runnable" error.

## UI states (Flows builder)

| State | Header | Builder |
| --- | --- | --- |
| Never published | `Utkast` badge | Fully editable (today's draft UX) |
| Published, no draft changes | `Publicerad v3` badge + `Kör flöde` | Fully editable; first edit creates draft state implicitly |
| Published + draft changes | `Publicerad v3` + `Utkast v4` badges | Editable; sticky bar: "Du redigerar ett utkast. Publicerad v3 fortsätter fungera." + `Publicera v4` + `Kasta utkastet` |
| Unpublished (explicit) | `Avpublicerad` badge | Editable; `Publicera` restores service |

- The red "Avpublicera för att redigera" button and the yellow read-only
  banner disappear entirely; "Avpublicera" moves into an overflow menu as a
  deliberate service action with its confirmation dialog.
- `Kasta utkastet` resets the working copy to the active snapshot (needs
  `POST /flows/{id}/discard-draft` or client-side restore from snapshot).
- Historik rows already show `v{n}`; the version list view can link each run
  group to its snapshot.
- AI-byggaren edit mode operates on the working copy — with versioning it no
  longer needs the published/unpublished distinction at all.

## Migration

1. Backfill: for every published flow, snapshot the current working copy as
   `flow_versions` v(published_version) and set `active_version_id`.
2. Existing runs keep their `flow_version` int; map to snapshot ids during
   backfill (or leave int-based and join on `(flow_id, version)`).
3. Ship the API additively (new fields nullable); switch the frontend; then
   remove the read-only-when-published builder logic.

## Test plan (backend slice)

- Publish is idempotent on identical hash; creates v+1 on change.
- Runs started before a publish complete against the old snapshot.
- Unpublish blocks new runs, never in-flight ones.
- Tenancy: versions inherit flow tenancy filters (cross-tenant read must fail).
- Audit rows exist for publish/unpublish.

## Open questions

1. Should `flows_publish` become a distinct permission from `flows_manage`
   (edit-vs-deploy separation many municipalities ask for)?
2. Retention: do old snapshots ever get pruned, and does Bevisunderlag export
   need to embed the snapshot before pruning?
3. Does the trigger surface need "pin to version" (run v3 forever) or is
   "always active version" enough for launch? (Recommend: active-only first.)
