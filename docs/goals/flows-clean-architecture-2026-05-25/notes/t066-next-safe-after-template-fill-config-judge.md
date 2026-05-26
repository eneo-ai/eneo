# T066 Judge: Next Safe Tranche After Template-Fill Config Typing

## Decision

Activate `T067`: `refactor(flows-ui): reuse HTTP authored-config owner in step transitions`.

This is the next narrow `T016` frontend state ownership/consolidation sub-slice. It removes the remaining manual HTTP authored-default seeding in `flowStepTransitionPolicy.ts` without touching backend runtime, API/OpenAPI, generated client, schema, service-key, retention, webhook, Flow AI Builder, or final architecture docs.

## Evidence

| Concept | Current locations | Behavior differences | Canonical owner | Merge/delete path |
|---|---|---|---|---|
| Frontend HTTP authored config defaults and parsing | `components/http/httpConfigDefaults.ts`, `components/http/httpConfigTypes.ts`, `FlowEditor.ts`, `FlowStepInputSection.svelte`, `FlowStepOutputSection.svelte`, `FlowStepSummaryCard.svelte`, and `flowStepTransitionPolicy.ts` | Most consumers use `createDefaultHttpConfig(...)` + `parseHttpAuthoredConfig(...)`; `flowStepTransitionPolicy.ts` still has a private `withHttpDefaults` that hand-seeds `auth`, `timeout_seconds`, `body`, `custom_headers`, and `response_format`. | `components/http/httpConfigDefaults.ts` + `components/http/httpConfigTypes.ts` for authored HTTP defaults/parsing. | In T067, replace manual known-field seeding in `withHttpDefaults` with the canonical default/parser owner while preserving unrelated `input_config` keys. |

Key source evidence:

- `frontend/apps/web/src/lib/features/flows/flowStepTransitionPolicy.ts:62-64` calls private `withHttpDefaults`.
- `frontend/apps/web/src/lib/features/flows/flowStepTransitionPolicy.ts:249-274` manually seeds HTTP authored defaults.
- `frontend/apps/web/src/lib/features/flows/components/http/httpConfigDefaults.ts:4-15` owns default HTTP authored config.
- `frontend/apps/web/src/lib/features/flows/components/http/httpConfigTypes.ts:55-68` owns parsing/sanitizing authored config.
- `frontend/apps/web/src/lib/features/flows/FlowEditor.ts:218-232`, `FlowStepInputSection.svelte:82-84`, `FlowStepOutputSection.svelte:50-53`, and `FlowStepSummaryCard.svelte:38-44` already use the canonical owner path.

## Chosen Worker Contract

T067 must:

- keep `flowStepTransitionPolicy.ts` as the owner for step input-source transitions;
- reuse `createDefaultHttpConfig("input", method)` and `parseHttpAuthoredConfig(...)` for known HTTP authored config fields;
- preserve unrelated `input_config` keys such as runtime-input metadata so this remains behavior-preserving for step transitions;
- add focused tests proving HTTP defaults come from the owner path and malformed known fields are normalized while unrelated keys remain;
- avoid backend/runtime/API/generated-client/schema/final-docs/Flow-AI-Builder work.

## Review Tier

Medium-risk frontend state ownership and behavior-preserving owner consolidation. Use Claude-only implementation gate after the diff is stable. Skip Antigravity unless Claude and Codex disagree or the slice expands into API/runtime/data/schema/final-audit work.

## Consolidation Effect

- Reused existing owner: `components/http/httpConfigDefaults.ts` and `components/http/httpConfigTypes.ts`.
- Logic moved from: manual known-field HTTP default seeding in `flowStepTransitionPolicy.ts`.
- Logic deleted: local `auth/body/custom_headers/response_format/timeout` default object construction for HTTP input-source transitions.
- Duplicate path removed: transition policy should no longer be a second owner for HTTP authored defaults.
- New code added: at most a small transition-local wrapper that preserves unrelated `input_config` keys while delegating known HTTP fields to the canonical owner.
- Why existing owners were insufficient: they are sufficient for known HTTP fields; transition policy still needs to preserve step-transition-specific unrelated keys.
- Guard/test preventing duplicate logic from returning: focused transition-policy tests plus grep guard against re-added manual HTTP default literals in `flowStepTransitionPolicy.ts`.
- Net Flow logic surface area: reduced.
- If increased, why the increase is necessary: any wrapper code is only the transition boundary between step state and the existing HTTP config owner.

## Naming Gate

No new public module/class/type/status/file names are approved. Any private helper must reveal that it belongs to HTTP input-source transition config, not generic helper/manager/processor vocabulary.

Final docs readiness: the future "where to change X" table can say "HTTP authored config fields/defaults/parsing start in `components/http/httpConfigDefaults.ts` and `components/http/httpConfigTypes.ts`; step source transitions are in `flowStepTransitionPolicy.ts`."

## Candidate Disposition

- `T014`: queued; schema/migration work still needs Docker/Postgres-backed verification or a separate read-only preflight.
- `T015`: queued; public API/OpenAPI/generated-client work should be split by exact Judge evidence.
- `T016`: queued broad placeholder; `T067` is the next narrow frontend state ownership sub-slice.
- `T901`: queued final docs Worker; do not start while architecture is still changing.
- `T009/T010/T011`: blocked by product/data decisions.

## Commands Run

- `jq '{schema_version,status,active_task,blockers}' /Users/ccimen/.codex/overnight-watchdog/flows-clean-architecture-watchdog.json` - pass; status ok, blockers empty.
- `ruby -ryaml -e '...' docs/goals/flows-clean-architecture-2026-05-25/state.yaml` - pass; active task T066.
- `rg -n "withHttpDefaults|createDefaultHttpConfig|parseHttpAuthoredConfig|auth: \\{ mode: \"none\" \\}|custom_headers|response_format|body: \\{ mode: \"none\" \\}" frontend/apps/web/src/lib/features/flows -g "*.{ts,svelte}"` - pass; duplicate transition-policy path found.
- `nl -ba frontend/apps/web/src/lib/features/flows/flowStepTransitionPolicy.ts` - pass; source evidence captured.
- `nl -ba frontend/apps/web/src/lib/features/flows/components/http/httpConfigDefaults.ts` and `httpConfigTypes.ts` - pass; canonical owner evidence captured.
