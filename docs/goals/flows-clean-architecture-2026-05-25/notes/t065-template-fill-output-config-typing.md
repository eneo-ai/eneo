# T065 Worker: Template-Fill Output Config Typing

## Result

Done.

`frontend/apps/web/src/lib/features/flows/templateFillConfig.ts` remains the canonical frontend owner for template-fill authored output config. The owner now parses the generated/persisted JSON boundary instead of asserting `step.output_config as TemplateFillOutputConfig`.

## Source Change

- `getTemplateFillOutputConfig` now accepts `{ output_config?: unknown }` so malformed JSON can be tested and parsed at the boundary without hiding it behind `as never`.
- Supported string fields are copied only when they are strings: `template_asset_id`, `template_file_id`, `template_name`, `template_checksum`.
- `placeholders` keeps only string values.
- `bindings` keeps only string values.
- Unsupported keys and malformed values are dropped at the owner boundary.
- No consumer-local shape guards, new modules, backend/API/generated-client changes, migrations, Flow AI Builder edits, or final architecture docs were added.

## Verification

| Command | Result | Notes |
|---|---|---|
| `cd frontend/apps/web && ../../node_modules/.bin/vitest run src/lib/features/flows/templateFillConfig.test.ts src/lib/features/flows/flowStepTransitionPolicy.test.ts src/lib/features/flows/FlowEditor.test.ts` | pass | 3 files, 64 tests passed. |
| `cd frontend/apps/web && ../../node_modules/.bin/eslint src/lib/features/flows/templateFillConfig.ts src/lib/features/flows/templateFillConfig.test.ts` | pass | No output. |
| `cd frontend/apps/web && ../../node_modules/.bin/prettier --check src/lib/features/flows/templateFillConfig.ts src/lib/features/flows/templateFillConfig.test.ts` | pass | All matched files use Prettier code style. |
| `cd frontend/apps/web && tmp_config=.t065-template-fill-tsconfig.json && printf ... && ../../node_modules/.bin/tsc --project "$tmp_config" --noEmit; rc=$?; rm -f "$tmp_config"; exit $rc` | pass | Focused TS check over `templateFillConfig.ts`, `templateFillConfig.test.ts`, and `flowStepTransitionPolicy.ts`. |
| `! git diff -- frontend/apps/web/src/lib/features/flows/templateFillConfig.ts frontend/apps/web/src/lib/features/flows/templateFillConfig.test.ts \| rg -n '^\+.*(as any\|as never\|@ts-ignore\|as TemplateFillOutputConfig)'` | pass | No added anti-pattern lines. |
| `git diff --check -- docs/goals/flows-clean-architecture-2026-05-25/state.yaml docs/goals/flows-clean-architecture-2026-05-25/notes/t064-next-safe-after-http-config-judge.md frontend/apps/web/src/lib/features/flows/templateFillConfig.ts frontend/apps/web/src/lib/features/flows/templateFillConfig.test.ts` | pass | No whitespace errors. |
| `scripts/gate-local/anti_slippage.sh` | pass | Nothing staged at the time. |

Blocked-existing/revised check:

- The first focused TypeScript command used `jq` against JSONC `tsconfig.json` and failed. The board command was revised to create a temporary TypeScript config using `printf`.
- Including `FlowEditor.ts` in the focused TypeScript check surfaces existing unrelated diagnostics (`FlowEditor.ts:309` and generated JS/module declarations). `FlowEditor.test.ts` covers the relevant behavior, and the focused TS check stays on the touched owner and transition-policy type consumer.

## Peer Review

Claude commit gate:

- Artifact: `.codex/artifacts/claude-peer-loop-t065-template-fill-output-config-typing-implementation-review-20260526T180749Z.md`
- Verdict: green
- Green light: yes
- Minimum score: 9

Valid Claude cautions:

- Commit hygiene: stage exact allowed files only. Accepted.
- Helper naming: Claude suggested `isPlainObject` as a P3 cosmetic rename. Not changed because the board naming gate discourages generic helper names; the current private predicate remains local to the template-fill owner.
- Literal key tuple: Claude suggested a future typed-key whitelist refinement. Deferred as cosmetic.

Antigravity:

- Skipped by tiered review rule. T065 is medium-risk frontend state ownership work, Claude was green, and no API/runtime/data/schema/final-audit boundary was crossed or disputed.

## Consolidation Effect

- Reused existing owner: `frontend/apps/web/src/lib/features/flows/templateFillConfig.ts`.
- Logic moved from: unchecked production `step.output_config as TemplateFillOutputConfig`.
- Logic deleted: unchecked production domain assertion and touched-test `as never` casts.
- Duplicate path removed: no duplicate module existed; this prevents consumers from needing local template-fill shape guards.
- New code added: small field parser inside the canonical owner.
- Why existing owners were insufficient: the owner existed but trusted generated JSON by assertion.
- Guard/test preventing duplicate logic from returning: parser tests for supported-field filtering and malformed dry-run behavior, plus added-line anti-leak grep.
- Net Flow logic surface area: reduced for maintainer experience; one owner now owns the boundary instead of pushing bad shapes downstream.
- If increased, why the increase is necessary: the only added branches are explicit boundary parsing that replaces an unsafe cast.

## Naming Gate

No new public module/class/type/status/file names were added. The private predicate is scoped to template-fill config parsing and would not appear as a maintainer entry in `docs/flows/architecture.md`.

Final docs readiness: the future `where to change X` table can say "template-fill frontend authored config parsing and UI-derived binding state start in `templateFillConfig.ts`."
