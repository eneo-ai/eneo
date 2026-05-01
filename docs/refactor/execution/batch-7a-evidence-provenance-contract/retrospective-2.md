# Retrospective 2 — Evidence / Provenance Contract Foundation

## A. Plan adherence

- [x] pass — Implemented the revised 7A.1 plan plus Claude-green implementation refinements inside the same scope (`journal.md`, Claude Implementation Review 1).
- [x] pass — Stayed within planned files: evidence router, evidence/OpenAPI/router/integration tests, `intric-js` generated schema docs, and batch execution docs.
- [x] pass — Scope changes were plan/Claude-reviewed before source edits; post-review refinements were small behavior-preserving hardening inside the planned raw-reason validation.
- [x] pass — Behavior pins landed before the unsupported-format branch/test deletion.
- [x] pass — Preserved load-bearing readiness decisions: no new evidence ledger, no migration, no compatibility shim, no frontend UI rewrite, no package/namespace rename.

## B. Acceptance criteria

- [x] pass — Evidence/provenance owner and duplicate-reader inventories exist in `plan.md`.
- [x] pass — Unsupported-format runtime branch/test and live schema references were removed or retargeted; anti-slippage `rg` returned no matches.
- [x] pass — Raw export rejects generic/blank reasons before run lookup and before audit/export; redacted default audit metadata remains pinned.
- [x] pass — Export audit fail-closed behavior is pinned through router unit and HTTP integration tests.
- [x] pass — Current manifest key set is pinned before typed manifest migration.
- [x] pass — No criterion is marked done without code/test evidence.

## C. Behavior pins and validation

- [x] pass — All plan-listed validation commands were rerun after the Claude-refined code change.
- [x] pass — All commands passed: 49 targeted backend tests, 17 evidence/service tests, pyright, ruff check, ruff format check, lint-imports, anti-slippage `rg`, `git diff --check`, `intric-js` check, and `intric-js` lint.
- [x] pass — Added behavior pins exercise API/OpenAPI shape, raw reason validation order, redacted/raw audit metadata, export fail-closed behavior, and manifest shape.

## D. Pre-production deletion discipline

- [x] pass — Deleted planned Tier A unsupported-format branch/test; did not preserve direct-function compatibility for a never-shipped format.
- [x] pass — Left Tier B/persisted/public surfaces alone and documented deletion conditions for later slices.
- [x] pass — Introduced no compatibility shim, fallback path, dual namespace, or legacy branch.
- [x] pass — Introduced no new untyped domain/application boundary, broad catch, domain HTTP exception, `as any`, `@ts-ignore`, or `@ts-expect-error`.

## E. Single source of truth

- [x] pass — Did not add a duplicate evidence owner; documented existing duplicate tool-call/artifact owners with next-slice deletion conditions.
- [x] n/a — Added no utility/helper file.

## F. File splits and naming

- [x] n/a — No file split.
- [x] pass — Added no prohibited file names.
- [x] n/a — Added no new source file.

## G. Comments and readability

- [x] n/a — No comments were deleted.
- [x] pass — Added no production comments; constants carry the raw reason contract.
- [x] n/a — Added no non-trivial comments.

## H. Test quality

- [x] pass — New/changed tests assert public behavior rather than private helper calls.
- [x] pass — Existing router/container seam style was preserved; no internal collaborator mocking was added beyond the current test pattern.
- [x] pass — Deleted only the test for the intentionally removed unsupported-format branch.

## I. Boundary discipline

- [x] pass — ORM models stayed in persistence.
- [x] pass — Pydantic schemas stayed out of domain logic.
- [x] pass — HTTP error translation stayed in the router adapter.
- [x] n/a — No Celery payload changes.

## J. Scope and risk

- [x] pass — Touched only Flow evidence/API tests, generated `intric-js` API schema docs, and batch execution docs.
- [x] pass — The generated schema doc edit was directly required by the OpenAPI response change and validated with package check/lint; full regeneration verification is carried forward.
- [x] pass — Carry-forward risks are recorded in `journal.md`.

## Final gate

- Fail count: 0
- Gate: GREEN
