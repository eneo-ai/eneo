# Eneo documentation site

Source of [docs.eneo.ai](https://docs.eneo.ai): a [Nextra 4](https://nextra.site) (Next.js, static export) site deployed to GitHub Pages by [`.github/workflows/deploy_docs.yml`](../../../.github/workflows/deploy_docs.yml).

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

`bun run build` produces a single-version export in `out/` (plus the Pagefind search index), which is what pull-request checks run.

## Versions

The published site contains several versions, derived from git refs — nothing is edited when a release is cut:

| Path     | Version | Built from                                                                                                |
| -------- | ------- | --------------------------------------------------------------------------------------------------------- |
| `/`      | stable  | the `release/vX.Y` branch tip of the highest final `vX.Y.Z` tag (or the tag itself if the branch is gone) |
| `/vX.Y/` | archive | the next `DOCS_ARCHIVED_LINES` older release lines                                                        |
| `/dev/`  | dev     | `develop`                                                                                                 |

Release candidates (`v2.2.0-rc.1`) do not count, so stable only moves when the final tag exists. Tagging a release, pushing a docs change to a release branch, or pushing to `develop` all rebuild every version.

Every version is built with the **current site code** and **that ref's `src/content` + `public`**, so changes to the chrome apply to all versions without touching release branches. Non-stable versions get a banner and `noindex`.

To preview all versions locally:

```bash
bun run build:versions          # writes site/ (site/dev, site/v2.0, …)
bun run preview                 # serves site/ on http://localhost:3000
bun run versions                # prints the versions that would be built
```

`build:versions` temporarily swaps `src/content` and `public` while building each ref and restores the working tree afterwards, even on failure or Ctrl-C. Archived versions that no longer build are skipped with a warning (`--strict` makes that fatal); stable and dev must build.

### Fixing docs for a released version

Docs live with the code. To correct the stable docs, open a PR against the release branch (e.g. `release/v2.1`) touching `frontend/apps/docs-site/**`; merging it republishes stable. Cherry-pick the fix to `develop` as with any other change so `/dev` and the next release carry it too.

## Writing pages

- Verify every claim against the code before writing it (env vars, endpoints, defaults, UI labels, commands). Prefer linking to the real file (`docs/deployment/env_backend.template`, `/openapi.json`) over restating long lists.
- Map code areas to the pages that describe them in [`DOCS_MAP.md`](./DOCS_MAP.md); pull requests that change documented behaviour are expected to update the affected page.
- Use `develop` in GitHub links, never `main`.
- Add new pages to the folder's `_meta.ts`; unlisted pages are appended unordered.
- Anything under `src/content/` is published — keep scratch files out of it.
