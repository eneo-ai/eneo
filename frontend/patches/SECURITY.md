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
before allowing exactly this advisory in the version-based audit. All other
advisories still fail. Container scans retain the unmodified findings for review;
the same tested patch is installed by the frozen Bun install in both Dockerfiles.

The resolutions for xmldom, PostCSS, Mermaid and sharp select published fixes
where upstream parents still pin vulnerable versions. Revisit those overrides
when the parents accept the fixed releases; do not widen them across API majors.
