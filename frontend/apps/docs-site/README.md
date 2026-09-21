# Eneo documentation site

Source of [docs.eneo.ai](https://docs.eneo.ai): a [Nextra 4](https://nextra.site) (Next.js, static export) site deployed to GitHub Pages by [`.github/workflows/deploy_docs.yml`](../../../../.github/workflows/deploy_docs.yml).

## Layout

| Path                                                                   | Purpose                                                                                                                                                                                                                                                                |
| ---------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `src/content/**/*.mdx`                                                 | The pages. Folders map to URL paths; `_meta.ts` in each folder sets sidebar order and titles.                                                                                                                                                                          |
| `public/`                                                              | Images, diagrams and `CNAME`. Reference them with absolute paths (`/diagrams/x.svg`); `src/mdx-components.js` prefixes the version base path.                                                                                                                          |
| `src/components/DocsShell.tsx`, `src/app/[[...mdxPath]]/layout.tsx`    | The document and site chrome: `<html lang>`, navbar, language and version switchers, banner, search, footer. The language comes from the URL, so there is no root layout.                                                                                              |
| `src/app/global-not-found.tsx`, `src/app/[[...mdxPath]]/not-found.tsx` | The site-wide `404.html`, rendered through the shell via Next's `global-not-found` convention (`experimental.globalNotFound` in `next.config.ts`; still experimental, keep it when upgrading Next). The page switches to Swedish for `/sv/` addresses after hydration. |
| `src/lib/versions.ts`, `src/components/VersionSwitcher.tsx`            | Version metadata injected at build time (see below).                                                                                                                                                                                                                   |
| `scripts/resolve-versions.mjs`, `scripts/build-versions.mjs`           | Multi-version build used by CI.                                                                                                                                                                                                                                        |

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

## Languages

English keeps its existing URLs (`/vX.Y/guides/deployment`, `/dev/guides/deployment`).
Swedish lives **inside the same version build**, at `/vX.Y/sv/guides/deployment`
and `/dev/sv/guides/deployment`. Root aliases include `/sv/` and continue to
follow stable. The workflow still builds once per version, not once per language.

The catch-all root layout owns the HTML language and localized site chrome.
`src/lib/languages.ts` owns route, source and fallback selection;
`src/lib/navigation.ts` translates the selected ref's navigation without adding
pages or changing its order. `src/lib/content.ts` reads Nextra's source inventory.
The English inventory defines which pages exist in a version. Swedish source
pages under `src/content/sv/` replace their English equivalents incrementally.
A translation without an English counterpart is not published.

An untranslated page displays the selected ref's English text inside a Swedish
shell, with a visible notice, `lang="en"` on its body, and `noindex` for search
engines. Older refs with no translations get this same honest fallback; current
translations are never copied onto an older release. The normal snapshot
extraction in `build-versions.mjs` already isolates the entire content tree.

[Pagefind separates indexes using the HTML language](https://pagefind.app/docs/multilingual/).
The fallback wrapper uses `data-pagefind-ignore="all"`, including its nested
Nextra `data-pagefind-body`, so English fallback text cannot enter Swedish search
or duplicate the original in English search. This is tested against Pagefind's
actual indexer. Versions with **no** Swedish pages show an English-search link
instead: Pagefind could otherwise fall back to another language's index.
Language changes use document navigation to reset Pagefind's cached index.

MDX links use `DocsLink`; the small remark plugin routes explicit JSX anchors
and `Cards.Card` through the same language adapters. Nextra/Next adds the version
base path once. Images remain version assets, without a language prefix.
Version switching probes the corresponding localized page, then its English
original, then the localized root and version root. Query strings are retained;
fragments are retained only when staying on the corresponding page.

The web app's `src/lib/core/docs.ts` owns external docs URLs. Storage links and the widget installation card pass
Paraglide's reader locale, independently of the widget visitor language. English URLs and fragment identifiers stay intact.

Target branch: `develop`, next release (currently 2.2); site routing applies to
all published lines, while translated prose ships only with the ref containing
it. No release-specific instructions are backported. Roll back by reverting the
change and rerunning the existing atomic publication workflow. CI performs the
full static exports; local checks intentionally cover contracts and MDX only.

Focused language checks (through the resource supervisor on the shared Mac):

```bash
bun test scripts/languages.test.ts
```

## Writing pages

- Verify every claim against the code before writing it (env vars, endpoints, defaults, UI labels, commands). Prefer linking to the real file (`docs/deployment/env_backend.template`, `/openapi.json`) over restating long lists.
- Map code areas to the pages that describe them in [`DOCS_MAP.md`](./DOCS_MAP.md); pull requests that change documented behaviour are expected to update the affected page.
- Link to code on the version being described. The automatic edit-page link uses the selected release branch or tag.
- Add new pages to the folder's `_meta.ts`; unlisted pages are appended unordered.
- Anything under `src/content/` is published — keep scratch files out of it.
