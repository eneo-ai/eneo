# Temporary dependency security fixes

Frontend maintainers own these patches. Remove each patch and its exception as
soon as a fixed upstream version is installed; retain the behavior regressions.

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

## katex 0.16.x — GHSA-238p-pmpm-9mq7

Reviewed 2026-10-13; audit policy updated 2026-10-29.
Low severity (CVSS 2.1): KaTeX reads inherited `Object.prototype` properties as
settings, so it only matters on a page that already has prototype pollution.
The fixed release is 0.18.2, but every dependent (rehype-katex, @streamdown/math,
mermaid, nextra, micromark-extension-math) still pins `^0.16`, so a root
resolution would run them against a version they have not released for.
No patch is installed on this release branch. The shared dependency audit
policy reports this low-severity advisory as a warning. The former KaTeX-only
exception and its 2026-12-01 deadline are removed; high/critical findings and
the other reviewed exceptions keep their normal checks.

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
