# T067 Worker: HTTP Transition Config Owner

## Result

Done.

`flowStepTransitionPolicy.ts` no longer hand-seeds known HTTP authored config defaults. Step input-source transitions now delegate known HTTP fields to the canonical frontend HTTP config owner:

- `components/http/httpConfigDefaults.ts`
- `components/http/httpConfigTypes.ts`

The transition policy still preserves unrelated `input_config` siblings such as `runtime_input` and legacy keys because the transition owner is responsible for preserving step state outside the HTTP authored-config namespace.

## Source Change

- Imported `createDefaultHttpConfig` and `parseHttpAuthoredConfig`.
- Replaced the old private `withHttpDefaults` manual default path with `withHttpInputSourceDefaults`.
- The wrapper shallow-copies the current `input_config` record, then overlays parsed canonical HTTP authored fields.
- Known fields are normalized by the HTTP owner; unrelated keys remain untouched.
- Removed the old local comments and duplicate default literals from `flowStepTransitionPolicy.ts`.

## Verification

| Command | Result | Notes |
|---|---|---|
| `cd frontend/apps/web && ../../node_modules/.bin/vitest run src/lib/features/flows/flowStepTransitionPolicy.test.ts` | pass | 8 tests passed after adding the valid-config preservation test. |
| `cd frontend/apps/web && ../../node_modules/.bin/vitest run src/lib/features/flows/flowStepTransitionPolicy.test.ts src/lib/features/flows/components/http/httpConfigDefaults.test.ts src/lib/features/flows/FlowEditor.test.ts` | pass | 3 files, 71 tests passed. |
| `cd frontend/apps/web && ../../node_modules/.bin/eslint src/lib/features/flows/flowStepTransitionPolicy.ts src/lib/features/flows/flowStepTransitionPolicy.test.ts` | pass | No output. |
| `cd frontend/apps/web && ../../node_modules/.bin/prettier --check src/lib/features/flows/flowStepTransitionPolicy.ts src/lib/features/flows/flowStepTransitionPolicy.test.ts` | pass | All matched files use Prettier code style. |
| `cd frontend/apps/web && tmp_config=.t067-http-transition-tsconfig.json && printf ... && ../../node_modules/.bin/tsc --project "$tmp_config" --noEmit; rc=$?; rm -f "$tmp_config"; exit $rc` | pass | Focused TS check over transition policy/test and HTTP owner files. |
| `! rg -n 'withHttpDefaults' frontend/apps/web/src` | pass | Old helper name is gone. |
| `! rg -n 'function withHttpDefaults\|auth: \{ mode: "none" \}\|body: \{ mode: "none" \}\|custom_headers: \[\]\|response_format: "text"' frontend/apps/web/src/lib/features/flows/flowStepTransitionPolicy.ts` | pass | Manual default literals are gone from the transition owner. |
| `git diff --check -- docs/goals/flows-clean-architecture-2026-05-25/state.yaml docs/goals/flows-clean-architecture-2026-05-25/notes/t066-next-safe-after-template-fill-config-judge.md frontend/apps/web/src/lib/features/flows/flowStepTransitionPolicy.ts frontend/apps/web/src/lib/features/flows/flowStepTransitionPolicy.test.ts` | pass | No whitespace errors. |
| `scripts/gate-local/anti_slippage.sh` | pass | Nothing staged at the time. |

## Peer Review

Claude commit gate:

- Artifact: `.codex/artifacts/claude-peer-loop-t067-http-transition-config-owner-implementation-review-20260526T181856Z.md`
- Verdict: green
- Green light: yes
- Minimum score: 8

Valid Claude concerns:

- Commit hygiene: stage exact allowed files only. Accepted.
- Add a valid-config transition test. Accepted; `flowStepTransitionPolicy.test.ts` now covers bearer auth, JSON-template body, custom headers, JSON response format, and unrelated `runtime_input` preservation.
- Dead `_method` parameter in `createDefaultHttpConfig` predates this slice and belongs to a future HTTP owner cleanup task, not T067.

Antigravity:

- Skipped by tiered review rule. T067 is medium-risk frontend state ownership work, Claude was green, and no API/runtime/data/schema/final-audit boundary was crossed or disputed.

## Consolidation Effect

- Reused existing owner: `components/http/httpConfigDefaults.ts` and `components/http/httpConfigTypes.ts`.
- Logic moved from: duplicate known-field defaulting in `flowStepTransitionPolicy.ts`.
- Logic deleted: old private `withHttpDefaults` known-field default literals and comments.
- Duplicate path removed: step transitions no longer own HTTP authored defaults for `auth`, `body`, `custom_headers`, `response_format`, `timeout_seconds`, or URL parsing.
- New code added: a transition-local wrapper that preserves unrelated `input_config` siblings and delegates known HTTP fields to the canonical owner.
- Why existing owners were insufficient: HTTP owner handles known authored fields; transition policy still owns preserving wider step state.
- Guard/test preventing duplicate logic from returning: transition-policy tests plus grep guards for `withHttpDefaults` and manual default literals.
- Net Flow logic surface area: reduced.
- If increased, why the increase is necessary: wrapper is the boundary between loose `FlowStep.input_config` and typed HTTP authored config.

## Naming Gate

No new public module/class/type/status/file names were added. The private `withHttpInputSourceDefaults` name identifies the HTTP input-source transition axis.

Final docs readiness: the future "where to change X" table can map HTTP authored defaults/parsing to `components/http/*` and step input-source transition behavior to `flowStepTransitionPolicy.ts`.
