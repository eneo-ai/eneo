# T004 generated client, admin UI, and documentation receipt

## Outcome

The generated client exposes the typed deployment-policy GET/PUT contract. The
existing admin area now has a Storage page that is readable by tenant admins and
editable only by session-backed platform admins. Its page-local state owns
loading, retry, full replacement, stale-revision recovery, and save feedback.

The page shows:

- the one deployment-wide target for eligible new File/Icon writes;
- all four configurable business limits and all five effective use-case rows;
- configured, effective, operator-ceiling, and constraining-source values;
- sanitized target readiness and bounded target/state inventory facts;
- explicit new-writes-only, no-implicit-move, and no-fallback behavior;
- truthful unavailable and degraded object-store states.

Current deployment templates no longer carry the four legacy business settings.
The migration and migration-focused tests remain their only owner. The focused
and docs-site deployment references describe PostgreSQL-inline as the complete
default, compatible object storage as optional, the admin/operator split,
no-restart updates, restore recovery, and policy versus full-release rollback.

## Validation

- Exact backend OpenAPI regeneration matched
  `frontend/packages/eneo-js/src/types/schema.d.ts`.
- Eneo JS tests: 15 passed; lint passed.
- Focused browser behavior tests: 9 passed, including mid-session platform-admin
  revocation switching the page to its read-only presentation.
- Full web unit suite: 59 files and 333 tests passed on the stable rerun. The
  first run populated Vite's fresh-worktree dependency cache and failed after a
  Vite dependency-optimization reload; no source change was made before the
  complete green rerun.
- Svelte check: 0 errors and 0 warnings.
- Frontend lint passed. Docs-site production build passed with only its existing
  unoptimized-image warning.
- Focused backend FileProtocol regression: 14 passed; Ruff and format passed.
- `bash -n scripts/sync-frontend-with-backend.sh`, `git diff --check`, and the
  shipping-source scan for the four retired setting names passed.
- Goal Maker board checker passed.

## Scope

No tenant-specific policy, fallback, dual write, implicit move, provider
registry, secret-bearing browser path, PR2 move workflow, knowledge-generation
work, or Flow work was added.
