# Temporary dependency security fixes

Frontend maintainers own these patches. Remove each patch and its exception as
soon as a fixed upstream version is installed; retain the behavior regressions.

## deepmerge 4.3.1 — CVE-2026-93753 / GHSA-gcqx-w48m-w2h4

Reviewed 2026-10-28. Review/exception expires 2026-11-27 (CI fails after that date).
The [advisory](https://github.com/advisories/GHSA-gcqx-w48m-w2h4) lists no fixed
release. The transitive build dependency is used by the Svelte Vite plugin and
Rollup's node-resolve plugin. The downstream patch rejects `__proto__` keys in
both the target-copy and source-merge loops, including recursive merges, so a
null-prototype target or an own `__proto__` property cannot change the returned
object's prototype. Source, CommonJS and UMD distributions receive the same fix.

`scripts/security-patches.test.mjs` resolves the installed package through the
Svelte plugin and tests both shipped distributions. It covers poisoned target
and source objects, null-prototype targets, nested null/undefined/primitive
placeholders and `merge.all`, as well as ordinary nested configuration, arrays
and symbol keys. The poisoning tests fail against unpatched 4.3.1. CI runs these
regressions before accepting only this advisory and exact affected range; the
accepted entry in `scripts/audit-dependencies.mjs` also records that the
dependency is build-time only and never sees request input.

Frontend maintainers must replace this mitigation with a fixed upstream release
when available, removing the patch and audit exception together. Reverting the
patch requires reverting the exception too; container scanners may continue to
report the upstream version. No product configuration or permission changes.

## braces 3.0.3 — CVE-2026-93687 / GHSA-vfj7-8cjw-p6xm

Reviewed 2026-10-05. Review/exception expires 2026-11-05 (CI fails after that date).
There is no published fixed version. The parser and recursive AST walkers now
bound nesting to 100; prebuilt ASTs and cyclic parent chains are also guarded.
This is a downstream mitigation, not a claim that upstream 3.0.3 is fixed.

The patch reuses the five library-file changes from the MIT-licensed upstream
proposal [micromatch/braces#72](https://github.com/micromatch/braces/pull/72),
commit `28d440b5dd449dbf1fe6f3506cf94ecca4d02660`. That proposal was closed without
merging, so Eneo owns testing and maintaining the downstream patch. The
[advisory](https://github.com/advisories/GHSA-vfj7-8cjw-p6xm) describes the
unbounded recursion this mitigates.

`node --test scripts/security-patches.test.mjs` exercises the installed copy
through Nextra → fast-glob → micromatch, including ordinary patterns, excessive
brace/parenthesis nesting, direct AST inputs and cyclic parents. CI runs it
before allowing exactly this advisory in the version-based audit. Other high or
critical advisories still fail; lower severities produce warnings. Container
scans retain the unmodified findings for review;
the same tested patch is installed by the frozen Bun install in both Dockerfiles.

The resolutions for xmldom, PostCSS, Mermaid and sharp select published fixes
where upstream parents still pin vulnerable versions. Revisit those overrides
when the parents accept the fixed releases; do not widen them across API majors.

## KaTeX resolution — GHSA-238p-pmpm-9mq7

Reviewed 2026-10-22. The root resolution selects KaTeX 0.18.11 for both apps
and the transitive renderers (rehype-katex, Mermaid, Nextra and
micromark-extension-math). This includes the upstream 0.18.2 fix for inherited
settings, setting metadata and namespace entries. There is no audit exception.

The resolution overrides the parents' older `^0.16` ranges; remove it once
those parents require a fixed version. The beta's math and clipboard tests
cover rendering, size limits and untrusted formulas, including inherited
`trust` and `processor` properties. Both apps retain the shared
`@eneo/markdown-math` options. KaTeX 0.18 prefixes internal CSS classes;
application styles use the stable outer `.katex` and `.katex-display` classes.

## Seroval resolution — CVE-2026-116582 / CVE-2026-116583

Reviewed 2026-10-29. The root resolution selects Seroval 1.6.11, including the
upstream fixes for [RegExp script injection](https://github.com/advisories/GHSA-9wx9-5pv9-3349)
and [typed array constructor injection](https://github.com/advisories/GHSA-f86p-h4j2-7qgj).
There is no audit exception. The installed chain is the beta's
`@tanstack/react-query-devtools` → `@tanstack/query-devtools` → `solid-js` →
`seroval`. Remove the override once the parents require a fixed version.

The existing `scripts/security-patches.test.mjs` suite resolves Seroval through
that chain. It checks synchronous and asynchronous serialization of typed
arrays with an untrusted own `constructor`, with and without compact buffer
views, and prevents RegExp sources from ending an HTML script element. It also
checks typed array contents, RegExp flags, named groups and lookbehinds survive
the round trip. CI runs these regressions before the dependency audit.
