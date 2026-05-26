# T062 Next Safe Post-Step-Identity Judge

## Decision

Activate T063:

`refactor(flows-ui): centralize HTTP authored config typing`

T014 is not the next safe local slice because Docker/Postgres is unavailable from the host, and both schema/migration work and the T061 repository integration stop-before-push condition require database-backed verification. T009/T010/T011 remain product/data-decision blocked. T901 remains queued as final maintainer documentation and must not run while runtime/API/schema/frontend architecture is still changing.

T063 is the smallest safe post-step-identity tranche because it consolidates a repeated frontend typed-boundary smell inside existing owners, requires no backend/API/generated-client/migration work, and can be verified locally with focused frontend checks plus clean-checkout verification.

## Source Evidence

| Concept | Current locations | Behavior differences | Canonical owner | Merge/delete path |
|---|---|---|---|---|
| Persisted HTTP authored config crossing from generated Flow step JSON to frontend typed state | `FlowStepInputSection.svelte`, `FlowStepOutputSection.svelte`, `FlowStepSummaryCard.svelte`, `FlowEditor.ts` | View components cast JSON config to `HttpAuthoredConfig`; `FlowEditor` separately shape-sniffs `?.auth` and reads JSON URLs directly | `components/http/httpConfigTypes.ts` owns the unknown-JSON to `HttpAuthoredConfig` boundary; `FlowEditor` consumes it as the frontend state owner | Add one structural-and-recovering parser in the HTTP config owner, use it in FlowEditor and the three view components, delete local casts/shape checks |
| HTTP auth discriminated union access | `httpConfigDefaults.ts`, focused HTTP tests | Production code and tests use `as any`/unnecessary `as HttpAuth` even though `HttpAuth` already narrows by `mode` | `HttpAuth` union in `httpConfigTypes.ts` | Remove casts and rely on discriminated-union narrowing |
| Secret sentinel detection | `httpConfigTypes.ts` | `isSecretSentinel` uses `(value as any).$secret` after an `in` check | `isSecretSentinel` in `httpConfigTypes.ts` | Remove `as any` and cover edge cases |
| Template-fill config cast sibling pattern | `templateFillConfig.ts` | Same broad config-cast pattern exists for template fill, but it is outside the HTTP slice | Future template-fill config owner task | Record as follow-up; do not broaden T063 |

## Approved T063 Scope

T063 must add one domain-specific parser, preferably `parseHttpAuthoredConfig(value: unknown, defaults: HttpAuthoredConfig): HttpAuthoredConfig`, with structural-and-recovering semantics:

- the step's `input_source` or `output_mode` decides whether a step is HTTP;
- missing or malformed fields fall back field-by-field to the caller-provided defaults;
- malformed `auth.mode` falls back to the default auth arm;
- the parser centralizes frontend recovery from untyped backend JSONB but does not solve backend JSONB ownership.

## Verification Requirements

- Focused Vitest for HTTP config defaults/helpers and `FlowEditor.test.ts`.
- ESLint and Prettier on touched files.
- Project-wide `bun run check` if clean; otherwise a focused TS/Svelte check must pass.
- Added-line and final-file `rg` guards must show no `as any`, `as unknown as HttpAuthoredConfig`, or unnecessary `as HttpAuth` in the touched HTTP config/FlowEditor files.
- Clean-checkout verification with only the T063 patch applied.
- `git diff --check`.
- `scripts/gate-local/anti_slippage.sh`.

## Peer Review

- Claude iteration 1: `.codex/artifacts/claude-peer-loop-t062-next-safe-post-step-identity-tranche-20260526T172656Z.md`; `GREEN_LIGHT no`, valid blockers were missing `FlowEditor.ts`, undeclared parser recovery semantics, incomplete cast-removal scope, and missing clean-checkout verification.
- Claude iteration 2: `.codex/artifacts/claude-peer-loop-t062-next-safe-post-step-identity-tranche-revised-20260526T173115Z.md`; `GREEN_LIGHT yes`, `MIN_SCORE 8`.
- Antigravity skipped by the tiered review rule: this is a medium-risk frontend state ownership slice, Claude and Codex agree, and it does not cross runtime/API/data boundaries.

## Consolidation Effect

- Reused existing owner: frontend Flow HTTP config owner under `components/http`, plus `FlowEditor` as frontend Flow state owner.
- Logic moved from: repeated component/controller JSON shape sniffing into one typed HTTP config boundary.
- Logic deleted: production `as any` auth access, repeated `as unknown as HttpAuthoredConfig`, and unnecessary HTTP config test casts.
- Duplicate path removed: each component/controller deciding generated JSON shape locally.
- New code added: one domain-specific parser/type boundary in the existing HTTP config owner.
- Why existing owners were insufficient: `HttpAuthoredConfig` existed but had no public parser from generated JSONB-shaped contract, so each caller cast locally.
- Guard/test preventing duplicate logic from returning: parser recovery tests, FlowEditor validation test, focused cast anti-leak `rg`, and clean-checkout verification.
- Net Flow logic surface area: reduced.

## Maintainer-Doc Readiness

T901 can later document this as: HTTP authored config JSON from generated Flow step config crosses into typed frontend state only through the `components/http` owner; `FlowEditor` and step section/summary components consume that owner for validation and display.
