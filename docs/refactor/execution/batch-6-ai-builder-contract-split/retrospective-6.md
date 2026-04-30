# Frontend AI Builder Protocol Alias Retrospective 6

## Result

Status: YELLOW

Fails: 1

The source diff is within scope and static validation is clean. The one fail is
validation completeness: AI Builder jsdom component tests could not run because
`jsdom` is missing from the frontend workspace. Non-jsdom AI Builder tests
passed through Vitest, and touched-file formatting/lint/diff checks passed.

## A. Plan adherence

- pass - Implemented the approved generated-alias plan: HTTP/API protocol
  surfaces now reference generated `intric-js` aliases where schemas exist,
  while SSE/UI-only contracts remain local.
- pass - Stayed within the planned files: AI Builder protocol/rendering files,
  `intric-js` resource aliases, and batch process docs.
- pass - Scope did not drift after the plan; no backend, Driver/Service
  state-owner, generated schema regeneration, package rename, or namespace
  migration work started.
- n/a - No deletion or destructive behavior change was planned for this slice.
- pass - Preserved load-bearing decisions: no compatibility alias namespace, no
  broad frontend state refactor, no backend schema work hidden in the frontend
  slice.

## B. Acceptance criteria

- pass - PRD-006 frontend generated-type drift reduction is satisfied for AI
  Builder HTTP/API protocol aliases in
  `frontend/apps/web/src/lib/features/flows/ai-builder/protocol.ts` and
  `frontend/packages/intric-js/src/types/resources.d.ts`.
- pass - UI-only/SSE-only contracts remain explicit in `protocol.ts`: stream
  event envelopes, event payloads, UI chat messages, edit-diff metadata, and
  apply-error projection are not disguised as generated schemas.
- pass - Generated optional fields are handled at render edges in
  `FlowAIBuilderStepCard.svelte` and `FlowAIBuilderPlanPane.svelte`, not by
  weakening generated aliases.
- pass - No criterion is marked done based on intent alone; remaining schema
  gaps are recorded in the journal carry-forward section.

## C. Behavior pins and validation

- pass - `cd frontend/packages/intric-js && bun run check` passed.
- pass - `cd frontend/packages/intric-js && bun run lint` passed.
- pass - Touched-file Prettier, ESLint, `git diff --check`, and anti-slippage
  grep passed after formatting `protocol.ts`.
- fail - Full AI Builder component validation did not complete: Bun's test
  runner lacks the Vitest jsdom environment, and Vitest reports missing
  `jsdom`. This is recorded as an environment/baseline gap rather than a
  product regression.
- pass - Non-jsdom AI Builder Vitest coverage passed: 48 tests in 7 files.

## D. Pre-production deletion discipline

- n/a - No Tier A deletion was planned.
- pass - Tier B/public compatibility surfaces were not touched.
- pass - No compatibility shim, fallback path, support-both branch, or
  `legacy_*` symbol was introduced.
- pass - No `as any`, `@ts-ignore`, or `@ts-expect-error` was introduced; no
  backend `Any`, `dict[str, Any]`, broad exception, or HTTP exception changes
  were made.

## E. Single source of truth

- pass - Generated backend schemas are now the source of truth for AI Builder
  HTTP/API response and request-adjacent types that exist in `schema.d.ts`.
- pass - Frontend-owned SSE/UI projections remain local and explicitly
  classified instead of being invented as generated-compatible shapes.

## F. File splits and naming

- n/a - No production file was split.
- pass - No prohibited helper/common/shared file was added.
- n/a - No new production file needed a named domain concept.

## G. Comments and readability

- pass - Added one narrow protocol comment explaining the `Required<>`
  telemetry trade-off; deleting it would hide a generated-schema nullability
  decision.
- pass - No comments were added that narrate control flow.
- pass - Renderer defaults are named derivations rather than explanatory
  comments.

## H. Test quality

- pass - No new tests assert private helper calls.
- pass - Existing non-jsdom behavior tests continue to exercise driver state,
  protocol-adjacent telemetry, reset, plan diff, apply navigation, structured
  questions, and MCP resource labels.
- n/a - No tests were deleted.

## I. Boundary discipline

- n/a - ORM models were not touched.
- n/a - Pydantic schemas were not touched.
- n/a - HTTP exception translation was not touched.
- n/a - Celery payloads were not touched.

## J. Scope and risk

- pass - Touched only Flow / Flow AI Builder frontend protocol/rendering files,
  `intric-js` generated alias exports, and curated batch docs.
- pass - The shared `intric-js` resource alias file changed only to expose
  generated AI Builder aliases already present in `schema.d.ts`.
- pass - Carry-forward risks are recorded in `journal.md`: SSE payload schemas,
  `SendMessageRequest.edit_context`, generic `PlanResponse.edit_result_json`,
  missing jsdom validation, and untouched Driver/Service state ownership.

## Final Gate

YELLOW: 1 fail. The fail is a validation-environment gap, not an accepted
source/test product regression. Continue only after Claude verification confirms
no accepted or partial findings remain.
