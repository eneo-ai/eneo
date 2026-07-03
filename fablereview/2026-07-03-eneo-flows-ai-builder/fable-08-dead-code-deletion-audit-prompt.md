# Fable 08 Prompt: Flow And Flow AI Builder Dead Code, Deletion, And Simplification Audit

You are Claude Fable running a max-effort, source-backed deletion and maintainability audit for Eneo Flows and Flow AI Builder.

Repository root: `/Users/ccimen/eneo/eneo-flows-clean`

## Mission

Find high-ROI code, tests, migrations, compatibility paths, fallback paths, duplicate concepts, and shallow modules that can be deleted, merged, moved, or simplified before production.

This is not a general architecture review. Do not repeat the main findings from the earlier Fable sessions unless the deletion/simplification angle is concrete and new.

The product is pre-production for Flow and Flow AI Builder. Do not preserve imaginary backwards compatibility. Compatibility code must name real persisted data, a real user/API contract, an owner, and a deletion trigger.

## Non-Negotiable Output Rules

- Return a complete Markdown review.
- Start with a five-line TL;DR.
- Use file:line citations for concrete claims.
- Include confidence for every material finding.
- Apply Ponytail aggressively: delete, merge, move, reuse, simplify.
- Do not edit source, tests, migrations, package files, config, or docs.
- Do not write files yourself. Your stdout will be saved to:
  `.codex/artifacts/fable-review-program-20260703/fable-08-dead-code-deletion-audit-review.md`

## Read First

Read:

- `.codex/artifacts/fable-review-program-20260703/index.md`
- `docs/engineering/maintainability-standards.md`
- `docs/engineering/comment-and-readability-standard.md`
- `docs/engineering/testing-standard.md`

Then inspect source yourself.

## Scope

Review only Flow and Flow AI Builder surfaces plus directly coupled generated-client/API/migration/test code:

- `backend/src/eneo/flows`
- `backend/src/eneo/flows`
- `backend/src/eneo/database/tables/flow_tables.py`
- `backend/src/eneo/database/tables/flow_tables.py`
- Flow-related migrations under `backend/alembic/versions`
- Flow and AI Builder tests under `backend/tests`
- frontend Flow and AI Builder code under `frontend/apps/web/src/lib/features/flows`
- generated client endpoint wrappers under `frontend/packages/eneo-js/src/endpoints/flows.js`
- generated schema only where it reveals duplicate/dead API shapes.

Use `rg` and source reading. Suggested searches:

- `legacy`
- `compat`
- `deprecated`
- `TODO`
- `FIXME`
- `HACK`
- `fallback`
- `repair`
- `best effort`
- `except Exception`
- `try:`
- `Any`
- `dict[str, Any]`
- `type: ignore`
- `as any`
- `@ts-ignore`
- `utils`
- `helpers`
- `manager`
- `processor`
- `adapter`
- `stub`
- `not used`
- `unused`
- `MIGRATION`
- `backfill`
- `old_`
- `new_`
- `v1`
- `v2`
- `flow_legacy`
- stale Flow package namespace references

## Specific Audit Targets

1. Dead or duplicate Python modules.

2. Duplicate Flow package paths that are compatibility mirrors or stale copies.

3. Legacy migrations or backfills that exist only because Flow/Builder changed shape before production.

4. Tests that pin behavior we should delete instead of preserve.

5. Fallback/repair paths that hide invalid state instead of enforcing one contract.

6. Pass-through services, one-implementation ports, fake adapters, broad processors, or generic helpers.

7. Duplicate source-of-truth concepts:
   - run status;
   - step status;
   - review status;
   - Builder proposal/plan/session state;
   - runtime input contracts;
   - file mappings;
   - evidence/provenance;
   - API schemas;
   - frontend state.

8. Dead migrations or migration tests that can be removed if the team accepts a pre-production reset/rebase strategy.

9. Generated-client or frontend wrappers with redundant local types or stale endpoints.

10. Comments/docs that are outdated enough to mislead implementation.

## Questions To Answer

1. What can be safely deleted tomorrow with low blast radius?

2. What can be merged into an existing canonical owner?

3. What is probably dead but needs one verification command or source check first?

4. What compatibility paths should be kept, and what concrete persisted-data evidence justifies keeping them?

5. Which tests are preserving accidental behavior and should be rewritten or deleted?

6. Which Flow/Builder migrations are likely dead if we are allowed to squash/rebase pre-production flow history?

7. Which files/classes are "AI-sloppy": too many shallow names, duplicated concepts, defensive code without a real failure mode, restating comments, or unused flexibility?

8. What should not be deleted now because it is a real boundary, generated artifact, migration dependency, or active API contract?

## Required Sections

Return:

1. `TL;DR`
2. `Ratings`
   - deletion opportunity;
   - dead-code risk;
   - duplicate ownership risk;
   - test-suite accidental-behavior risk;
   - migration cleanup opportunity;
   - implementation confidence.
3. `Deletion Candidate Inventory`
4. `Ranked Findings`
   - severity, problem, why it matters, evidence, owner/fix, acceptance criteria, tests/verification, risk/trade-off, confidence.
5. `Low-Risk Deletes For Tomorrow`
6. `Merge / Move Candidates`
7. `Compatibility Paths To Delete Or Justify`
8. `Dead Or Squashable Migrations`
9. `Tests That Pin Accidental Behavior`
10. `False Positives / Things To Keep`
11. `One-Command Verification Checklist`
12. `What Is Not Worth Fixing`
13. `Implementation Slices`
14. `Claims Codex Must Verify`
15. `Challenge This Brief`
16. `Confidence`

## Guardrails

- Do not recommend deleting generated schema files merely because they are large.
- Do not recommend deleting migrations unless you explain whether it requires a pre-production schema reset/squash.
- Do not recommend removing a compatibility path without stating how to verify persisted data does not need it.
- Prefer fewer, higher-confidence deletion opportunities over long speculative lists.
- A "delete" recommendation is only useful if it names the exact file/function/test/migration and the verification needed.
