# Eneo documentation site

Source of [docs.eneo.ai](https://docs.eneo.ai): a [Nextra 4](https://nextra.site) (Next.js, static export) site deployed to GitHub Pages by [`.github/workflows/deploy_docs.yml`](../../../../.github/workflows/deploy_docs.yml).

## Layout

| Path                                                         | Purpose                                                                                                                                       |
| ------------------------------------------------------------ | --------------------------------------------------------------------------------------------------------------------------------------------- |
| `src/content/**/*.mdx`                                       | The pages. Folders map to URL paths; `_meta.ts` in each folder sets sidebar order and titles.                                                 |
| `public/`                                                    | Images, diagrams and `CNAME`. Reference them with absolute paths (`/diagrams/x.svg`); `src/mdx-components.js` prefixes the version base path. |
| `src/app/layout.tsx`                                         | Site chrome: navbar, version switcher, banner, footer.                                                                                        |
| `src/lib/versions.ts`, `src/components/VersionSwitcher.tsx`  | Version metadata injected at build time (see below).                                                                                          |
| `scripts/resolve-versions.mjs`, `scripts/build-versions.mjs` | Multi-version build used by CI.                                                                                                               |

## Local development

```bash
cd frontend && bun install
cd apps/docs-site && bun run dev      # http://localhost:3001
```

`bun run build` produces a single-version export in `out/` (plus the Pagefind search index), for a single-version local preview. Pull-request checks build the complete versioned artifact.

## Versions

Start with [AUTHORING.md](AUTHORING.md) for branch selection and examples.
The version resolver owns which lines are published:

| URL                           | Content                                                                            |
| ----------------------------- | ---------------------------------------------------------------------------------- |
| `/vX.Y/`                      | Stable or archived release line, from its release branch (tag fallback)            |
| `/dev/`                       | Current `develop` documentation                                                    |
| `/` and unversioned page URLs | Redirects to the corresponding latest stable page, or dev before the first release |

Every selected line has a permanent version path, including the current
stable line. `DOCS_ARCHIVED_LINES` controls how many previous lines are retained
(default 3); explicitly retiring a line removes its content. RC tags never
promote a release to stable.

The builder copies current site code into a disposable `.docs-build-*` directory,
then selects that ref's `src/content`, `public` and, when present,
`frontend/packages/whats-new/releases.json`. The current package code/schema
renders the selected JSON. Old lines predating What's new receive an empty
release list, never development entries. Development previews use local content,
including uncommitted edits. Installed dependencies are linked, not recopied.

All selected versions must build. Only then does the complete artifact replace
`site/`. Failed builds and cancellation leave source files and the previous
publication untouched. GitHub Pages receives only a complete artifact, including
its `versions.json` manifest. There is no skip-failed-archive mode.

Publication runs from `develop` after docs/What's new changes or successful
existing CI/image workflows for pushed refs. An hourly input reconciliation
also catches old refs without matching workflows. It skips dependency
installation and builds when the publication digest matches the deployed
manifest. This works without backporting publication workflows to old branches.
GitHub may delay scheduled runs; use workflow_dispatch for immediate recovery.

After any failed publication, correct the failing page or renderer and rerun the
workflow on `develop`. The existing Pages deployment remains live. For a forced
process termination, an ignored `.docs-build-*` directory may remain; once the
build process has stopped it can be removed. It contains no source-file backups and a later build never reuses it.
If the final rename and rollback both fail, the error identifies a
`previous-site` recovery directory: restore that publication before cleanup. Roll back a bad deployment by reverting the
input change and manually rerunning the workflow.

Focused checks from this directory (use your environment's resource supervisor):

```bash
node --test --test-concurrency=1 scripts/*.test.mjs
node scripts/resolve-versions.mjs
```

Full builds/previews require explicit authorization on the shared Mac:

```bash
bun run build:versions          # complete artifact in site/
bun run preview                 # serve the completed artifact
```

## Writing pages

- Verify every claim against the code before writing it (env vars, endpoints, defaults, UI labels, commands). Prefer linking to the real file (`docs/deployment/env_backend.template`, `/openapi.json`) over restating long lists.
- Map code areas to the pages that describe them in [`DOCS_MAP.md`](./DOCS_MAP.md); pull requests that change documented behaviour are expected to update the affected page.
- Link to code on the version being described. The automatic edit-page link uses the selected release branch or tag.
- Add new pages to the folder's `_meta.ts`; unlisted pages are appended unordered.
- Anything under `src/content/` is published — keep scratch files out of it.
