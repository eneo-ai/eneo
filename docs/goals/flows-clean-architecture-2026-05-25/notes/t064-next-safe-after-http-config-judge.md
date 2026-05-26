# T064 Judge: Next Safe Tranche After HTTP Config Typing

## Decision

Activate `T065`: `refactor(flows-ui): parse template-fill output config through typed owner`.

This is the smallest safe follow-up under the broad `T016` frontend state ownership placeholder. It reuses and deepens the existing `frontend/apps/web/src/lib/features/flows/templateFillConfig.ts` owner instead of creating another contract shape or moving runtime/API/schema work forward without the required gates.

## Evidence

| Candidate | Classification | Evidence | Decision |
|---|---|---|---|
| Template-fill output config typing | `safe_now` | `templateFillConfig.ts` already owns `TemplateFillOutputConfig`, `getTemplateFillOutputConfig`, readiness, dry-run validation, placeholder rows, and binding suggestions. The current boundary returns `step.output_config as TemplateFillOutputConfig`, so invalid persisted/generated payload shapes can leak to all consumers. | Activate a narrow Worker that parses and sanitizes this boundary inside the existing owner. |
| HTTP config backend JSONB ownership preflight | `needs_preflight` | T063 reduced frontend authored-config shape sniffing, but backend runtime/persistence ownership needs source preflight and may cross API/runtime/data boundaries. | Do not start before a separate Scout/Judge pins scope. |
| T014 schema invariants | `needs_environment` | Database-backed verification is still required; local Docker/Postgres availability was not established. | Keep queued. |
| T015 API consumer DX | `needs_judge_split` | Broad public API/OpenAPI/generated-client work is higher risk and should be split by source-backed Judge decision. | Keep queued. |
| T016 frontend state ownership | `safe_when_sliced` | T063 completed one HTTP config sub-slice; template-fill config is the next narrow same-owner sub-slice. | Activate T065 as a T016 sub-slice. |
| T901 final architecture docs | `final_docs_only` | The implementation architecture is still changing. | Keep queued until final pre-merge docs Worker. |
| T009/T010/T011 | `blocked_on_decision` | Product/data decisions for retention and service-key identity/review/rerun are not recorded as unblocked. | Keep blocked. |

## Chosen Worker Contract

T065 must:

- keep `templateFillConfig.ts` as the canonical owner for frontend template-fill output config parsing and derived UI state;
- preserve valid legacy `template_file_id` behavior;
- reject or drop malformed fields at the boundary instead of trusting `as TemplateFillOutputConfig`;
- keep the slice frontend-only and Flow-proper-only;
- avoid new modules, generic helpers, parallel contract shapes, backend/API/OpenAPI/generated-client edits, migrations, retention, service-key, webhook, Flow AI Builder, or `docs/flows/architecture.md` work.

## Review Tier

This is medium-risk frontend state ownership work. Per the tiered review rule, use Claude-only review after the diff is stable. Skip Antigravity unless Claude and Codex disagree or the slice expands into API/runtime/data/schema/final-audit territory.

## Consolidation Effect

- Reused existing owner: `frontend/apps/web/src/lib/features/flows/templateFillConfig.ts`.
- Logic moved from: unchecked `step.output_config as TemplateFillOutputConfig` at the template-fill boundary.
- Logic deleted: the trusted cast should disappear from production template-fill config parsing.
- Duplicate path removed: none yet; this prevents consumers from each adding their own shape guards.
- New code added: only boundary parsing/sanitizing inside the existing owner, if needed.
- Why existing owners were insufficient: the owner exists but currently trusts the generated JSON payload by assertion rather than validating field types.
- Guard/test preventing duplicate logic from returning: targeted parser tests plus an anti-leak grep for added production `as TemplateFillOutputConfig`, `as any`, and `as never` in touched template-fill files.
- Net Flow logic surface area: preserved to slightly reduced; no new owner, no new module, fewer unsafe places to debug.
- If increased, why the increase is necessary: any added parser branches are boundary validation replacing an unsafe cast, not a second ownership path.

## Naming Gate

No new module/class names are approved. If a local helper is needed, it must be private and domain-specific to template-fill config parsing, not generic `helper`, `manager`, `processor`, `common`, or `types`.

The existing owner would appear clearly in the final `docs/flows/architecture.md` "where to change X" table as: template-fill frontend authored output config and UI-derived binding state start in `templateFillConfig.ts`.

## Commands Run

- `jq '.' /Users/ccimen/.codex/overnight-watchdog/flows-clean-architecture-watchdog.json` - pass; status ok, blockers empty.
- `git status --short --branch` - pass; unrelated dirty/untracked files preserved.
- `rg -n "T064|T065|template-fill|template fill|templateFill|TemplateFill|output_config|input-policy|run-contract|architecture.md|service-key|retention" ...` - pass; confirmed final docs and decision gates remain active constraints.
- `rg -n "templateFill|template_fill|TemplateFill|output_config" frontend/apps/web/src/lib/features/flows backend/src/intric/flows backend/tests -g "*.{ts,svelte,py}"` - pass; Flow-proper frontend owner and consumers identified.
- `nl -ba frontend/apps/web/src/lib/features/flows/templateFillConfig.ts` - pass; unchecked production cast found at line 100.
- `rg -n "getTemplateFillOutputConfig|TemplateFillOutputConfig|templateFillConfig|as TemplateFillOutputConfig|template_file_id|template_asset_id" frontend/apps/web/src/lib/features/flows ...` - pass; consumers route through the existing owner.
