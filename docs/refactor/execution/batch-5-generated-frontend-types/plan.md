# Batch 5 Generated Frontend Types Plan

## Loop Iteration 1

Status: planned before implementation; updated with validation-discovered local
Flow type fallout before final review.

## Scope Guard

Batch 5 owns the generated frontend type cleanup for Flow API/runtime contracts.
It does not own AI Builder state refactors, app state-owner movement, package
renaming, or broad schema regeneration.

Do not touch:

- `frontend/packages/ui/src/icons/types.d.ts`
- `scripts/run_codex_review.sh`
- `PRODUCT.md`

## Canonical Owners

| Concept | Current owner | Batch 5 decision |
|---|---|---|
| Backend API contract | FastAPI/Pydantic schemas exported through OpenAPI | Treat generated `schema.d.ts` as the frontend source of truth for Flow public API shapes already present there. |
| Frontend resource aliases | `frontend/packages/intric-js/src/types/resources.d.ts` | Keep as ergonomic alias layer only; remove manual Flow public API shape ownership. |
| Handwritten client methods | `frontend/packages/intric-js/src/endpoints/flows.js` | Keep as thin request wrapper; do not make it a schema owner. |
| Flow app state | Existing web Flow editor/run UI files | Out of scope except type fallout from alias cleanup. |
| Package naming | `@intric/intric-js` and `frontend/packages/intric-js` | Keep unchanged in Batch 5; document the migration decision in `naming-decision.md`. |

## Reuse Before Inventing

Closest existing owners:

- `frontend/packages/intric-js/src/types/schema.d.ts` already contains generated
  Flow schemas for definitions, runtime views, run create, run/result,
  evidence, graph, pagination, input limits, evidence policy, and retention
  policy.
- `frontend/packages/intric-js/src/types/resources.d.ts` currently duplicates
  those Flow shapes manually.
- `frontend/apps/web/src/lib/features/flows/flowFormSchema.ts` already owns UI
  normalization for old and current form field types.

Decision:

- Reuse generated schemas as aliases in `resources.d.ts`.
- Retain only narrow frontend-owned envelope types where the generated backend
  contract intentionally exposes an untyped JSON payload.
- Add package-local type/import smoke coverage instead of a broad package
  typecheck, because the current package `tsconfig.json` includes existing JS
  test/client baseline errors unrelated to this batch.

## Manual Type Mapping Table

Consumer counts are `rg` hits across `frontend/apps/web/src`,
`frontend/packages/intric-js/src`, and `frontend/packages/ui/src`, excluding
`resources.d.ts` and `schema.d.ts`. Counts include local same-name concepts when
the symbol is generic; the action column states the actual migration intent.
The `Migration risk` column names the concrete type-system change, not only a
severity label.

| Manual symbol | Generated counterpart | Bucket | Consumer count | Migration risk | Action | Rollback note |
|---|---|---:|---:|---|---|---|
| `Permission` | `components["schemas"]["Permission"]` | 1 | 25 | Duplication removal; generated enum already includes `flows`, `flows_view`, `flows_run`, `flows_manage`, `flows_ai_builder`, and `flows_trace`. | Delete redundant Flow-specific augmentation and alias directly to generated enum. | Revert all Permission/Role alias changes together if role consumers fail. |
| `FlowInputLimits` | `components["schemas"]["FlowInputLimitsPublic"]` | 1 | 3 | Low; fields match. | Replace manual shape with generated alias. | Restore previous manual type if settings endpoint typing regresses. |
| `FlowEvidencePolicy` | `components["schemas"]["FlowEvidencePolicyPublic"]` | 1 | 3 | Low; already generated alias. | Keep generated alias. | None. |
| `FlowRetentionPolicy` | `components["schemas"]["FlowRetentionPolicyPublic"]` | 1 | 3 | Low; already generated alias. | Keep generated alias. | None. |
| `FlowDocumentRenderLimits` | Missing from checked-in `schema.d.ts` | 4 | 3 | High; backend route exists but checked-in generated schema lacks this path/schema. | Retain manual type for now and document schema gap; do not regenerate broad schema in this pass unless Claude or validation shows it is required. | Manual type remains rollback. |
| `FlowStep` | `components["schemas"]["FlowStepPublic"]` | 1 | 184 | Enum-preserving; generated step fields use generated enum schemas. Optionality unchanged for current editor-required fields. | Replace with generated alias and fix local type fallout only. | Revert Flow alias block as one unit if app check shows broad non-local fallout. |
| `FlowFormFieldType` | App-owned `flowFormSchema.ts`, not generated resource alias | 3 | 5 | Delete zero real `@intric/intric-js` consumers; generated `FormFieldPublic.type` is loose `string`, while app normalization owns old/current field narrowing. | Remove from `resources.d.ts`; keep tight old/current form-field union in app-owned `flowFormSchema.ts`. | Re-add only if a real `@intric/intric-js` import is found. |
| `FlowFormField` | `components["schemas"]["FormFieldPublic"]` through `FlowRunContract["form_fields"]` | 3 | 12 | Avoid silent enum-loosening export; app local type owns normalized form fields. | Remove public resource alias; use generated contract field where needed and app-local `FlowFormField` for normalization. | Re-add only with a narrowed alias and a consumer proof. |
| `FlowFormSchema` | No public backend schema; app metadata envelope | 3 | 0 | Delete zero-consumer manual metadata envelope. | Remove from `resources.d.ts`; form schema editing stays app-owned in `flowFormSchema.ts`. | Re-add only with a generated backend schema or real consumer proof. |
| `FlowSparse` | `components["schemas"]["FlowSparsePublic"]` | 1 | 12 | Low; list responses already generated. | Replace with generated alias. | Restore manual type if list page check regresses. |
| `Flow` | `components["schemas"]["FlowPublic"]` | 1 | 37 | Medium; editor mutates draft steps. | Replace with generated alias. | Restore manual type if editor assignments fail beyond local type cleanup. |
| `FlowTemplatePlaceholder` | `components["schemas"]["FlowTemplatePlaceholderPublic"]` | 1 | 3 | Low; app has separate local template-fill types. | Alias generated shape. | Revert alias line only. |
| `FlowTemplateInspection` | `components["schemas"]["FlowTemplateInspectionPublic"]` | 1 | 8 | Low; fields match current route. | Alias generated shape. | Revert alias line only. |
| `FlowTemplateAsset` | `components["schemas"]["FlowTemplateAssetPublic"]` | 1 | 0 | Medium; generated required fields are stricter than manual optional fields. | Alias generated shape; no current consumer. | Revert alias if a hidden app import appears. |
| `FlowRunContractStepInput` | `components["schemas"]["FlowRuntimeInputContractPublic"]` | 1 | 18 | Low; route contract owns runtime input shape. | Alias generated shape. | Revert alias line only. |
| `FlowRunContractTemplateReadiness` | `components["schemas"]["FlowTemplateReadinessPublic"]` | 1 | 8 | Generated schema preserves consumed fields: `template_asset_id`, `template_file_id`, `template_name`, `checksum`, `published_flow_version`, `status`, `can_edit`, `can_download`, `message_code`. Manual-only fields `reason_code`, `message`, `action_text`, and `can_run` have no current consumers. | Alias generated shape; do not preserve unconsumed manual-only fields. | Revert contract aliases as one block if app check reveals a real consumer. |
| `FlowRunContract` | `components["schemas"]["FlowRunContractPublic"]` | 1 | 4 | Medium; generated optional arrays may surface null/undefined checks. | Alias generated shape and fix local consumers if needed. | Restore manual type if runtime dialog fallout is not local. |
| `FlowRunArtifact` | No generated dedicated output payload schema | 3 | 0 | Low; only used inside UI output payload envelope. | Keep as UI/presentation helper type for current output payload parsing. | None. |
| `FlowRunOutputPayload` | Generated output payload is `{ [key: string]: unknown }` | 3 | 2 | UI envelope over intentionally untyped JSON; not a backend public schema owner. | Keep as UI-owned envelope and introduce one `WithTypedRunOutput<T>` helper so run/step aliases do not drift independently. | Remove helper once backend emits a typed output payload schema. |
| `FlowRun` | `WithTypedRunOutput<components["schemas"]["FlowRunPublic"]>` | 2 | 4 | Explicit UI envelope over generated run; optionality otherwise generated-owned. | Alias with `WithTypedRunOutput<T>`. | Revert Flow run aliases as one block if output-payload helper causes fallout. |
| `FlowRunStepInput` | `components["schemas"]["StepRunInput"] & { file_ids: string[] }` | 2 | new | Intentional frontend run-intent tightening: generated `StepRunInput.file_ids` is optional, but the app only submits populated runtime file entries after Batch 4 removed top-level `file_ids`. | Add as an explicit frontend helper alias for `FlowRunStepInputs`; keep generated create-run schema unchanged. | Relax to generated `StepRunInput` if a real consumer needs empty per-step input entries. |
| `FlowRunStepInputs` | `Record<string, components["schemas"]["StepRunInput"] & { file_ids: string[] }>` | 2 | 4 | Generated `StepRunInput.file_ids` is optional, but the UI builder only submits populated step entries. | Use generated step input as the base and require `file_ids` in the frontend run-intent helper alias. | Restore manual record only if generated optionality requires a backend schema fix. |
| `FlowInputPolicy` | `components["schemas"]["FlowInputPolicyPublic"]` | 1 | 0 | Low; generated route shape exists. | Alias generated shape. | Revert alias line only. |
| `FlowRunStepOutput` | `components["schemas"]["FlowRunStepPublic"]` | 2 | 4 | Duplicate name for same generated concept. | Delete public alias and migrate current consumers to canonical `FlowRunStep`. | Revert all Flow run-step rename edits together if app check fails. |
| `FlowStepResult` | `components["schemas"]["FlowRunStepPublic"]` | 2 | 5 | Duplicate name for same generated concept. | Delete public alias and migrate current consumers to canonical `FlowRunStep`. | Revert all Flow run-step rename edits together if app check fails. |
| `FlowRunStep` | `WithTypedRunOutput<components["schemas"]["FlowRunStepPublic"]>` | 2 | new | New canonical resource alias replacing the two duplicate names. | Add as the single public step result/output alias. | Remove if the rename is reverted. |
| `FlowGraphNode` | `components["schemas"]["GraphNode"]` | 1 | 2 | Enum-loosened: generated `type` is `string`; current consumer only narrows `step_order`, and backend examples use `step`. | Alias generated graph node; do not preserve outdated `"input" | "llm" | "output"` union. | Revert Flow graph aliases as one block if app check fails. |
| `FlowGraphEdge` | `components["schemas"]["GraphEdge"]` | 1 | 0 | Low; generated shape is richer. | Alias generated graph edge. | Revert alias line only. |
| `FlowGraph` | `components["schemas"]["GraphResponse"]` | 1 | 6 | Additive/looser generated node details. | Alias generated graph response. | Revert Flow graph aliases as one block if app check fails. |
| `FlowRunDebugIoTypes` | `components["schemas"]["FlowRunDebugIoTypes"]` | 1 | 0 | Low. | Alias generated debug shape. | Revert alias line only. |
| `FlowRunDebugInput` | `components["schemas"]["FlowRunDebugInput"]` | 1 | 0 | Low. | Alias generated debug shape. | Revert alias line only. |
| `FlowRunDebugOutput` | `components["schemas"]["FlowRunDebugOutput"]` | 1 | 0 | Low. | Alias generated debug shape. | Revert alias line only. |
| `FlowRunDebugMcp` | `components["schemas"]["FlowRunDebugMcp"]` | 1 | 0 | Low; generated uses server/tool arrays instead of old allowlist. | Alias generated debug shape. | Revert alias line only. |
| `FlowRunDebugRagReferenceChunk` | `components["schemas"]["FlowRunDebugRagReferenceChunk"]` | 1 | 5 | Low; generated defaulted fields are optional. | Alias generated debug shape. | Revert alias line only. |
| `FlowRunDebugRagReference` | `components["schemas"]["FlowRunDebugRagReference"]` | 1 | 8 | Low; generated shape is richer. | Alias generated debug shape. | Revert alias line only. |
| `FlowRunDebugRag` | `components["schemas"]["FlowRunDebugRag"]` | 1 | 2 | Low; generated shape is richer. | Alias generated debug shape. | Revert alias line only. |
| `FlowRunDebugStep` | `components["schemas"]["FlowRunDebugStep"]` | 1 | 0 | Low. | Alias generated debug shape. | Revert alias line only. |
| `FlowRunDebugAttempt` | `components["schemas"]["FlowRunDebugAttempt"]` | 1 | 0 | Low. | Alias generated debug shape. | Revert alias line only. |
| `FlowRunDebugExport` | `components["schemas"]["FlowRunDebugExport"]` | 1 | 4 | Low; toolbar consumes redaction flag present in generated shape. | Alias generated debug export. | Revert alias line only. |
| `FlowRunEvidence` | `components["schemas"]["FlowRunEvidenceResponse"]` | 1 | 3 | Low. | Alias generated evidence response. | Revert alias line only. |
| `FlowRunEvidenceWithTypedSteps` | `Omit<FlowRunEvidence, "step_results"> & { step_results: FlowRunStep[] }` | 2 | new | Evidence rendering needs the same typed `output_payload_json` projection as run progress; generated evidence keeps raw `FlowRunStepPublic`. | Add one shared typed evidence alias instead of local component-only evidence contracts. | Delete the alias when backend types Flow step output payloads. |
| `FlowRunEvidenceExport` | `components["schemas"]["FlowRunEvidenceExportResponse"]` | 1 | 1 | Low. | Alias generated evidence export response. | Revert alias line only. |
| `FlowRunRedispatchResult` | `components["schemas"]["FlowRunRedispatchResponse"]` | 1 | 1 | Low. | Alias generated redispatch response. | Revert alias line only. |
| `DryRunResult` | No generated Flow route currently exposes it | 3 | 0 | Delete zero-consumer manual API shape. | Remove from `resources.d.ts`; re-add only with a generated backend route/schema. | Re-add only with a generated backend route/schema. |

Bucket legend:

1. Direct generated alias.
2. Generated alias with explicit `Omit` / intersection / adapter type.
3. UI-only retained type, with a narrow reason.
4. Backend schema or generated-schema gap; do not hide the gap by expanding
   handwritten frontend ownership.

## Behavior Pins Before Cleanup

- Add `frontend/packages/intric-js/src/types/flow-resource-aliases.types.ts`
  as a type-only smoke fixture.
- The fixture imports aliases from `@intric/intric-js`, constructs minimum
  valid generated-backed shapes for:
  - `Flow`
  - `FlowStep`
  - `FlowRunContract`
  - `FlowRunStepInputs`
  - `FlowRun`
  - `FlowRunStep`
  - `FlowGraph`
  - `FlowRunEvidenceExport`
- Include `// @ts-expect-error` anchors for the concrete drift risks:
  - top-level `file_ids` on generated `FlowRunCreateRequest`
  - invalid `FlowStep.input_source`
  - missing required `FlowTemplateAsset` identifiers
  - outdated `FlowGraphNode.type` assumptions if a consumer tries to force the
    old `"input" | "llm" | "output"` union as the generated API contract
  - missing required `file_ids` in the stricter frontend `FlowRunStepInputs`
    alias
- Keep existing `frontend/packages/intric-js/src/endpoints/flows.test.js`
  wrapper tests for Batch 4 request behavior.

## Type/Import Smoke Strategy

Add package-local smoke checking without pretending the existing package-wide
JS typecheck is clean:

- Add `frontend/packages/intric-js/tsconfig.type-smoke.json`.
- Add `frontend/packages/intric-js/package.json` script:
  - `"check": "tsc --noEmit -p tsconfig.type-smoke.json"`
- Validation command:
  - `cd frontend/packages/intric-js && bun run check`

Rationale:

- `bun x tsc --noEmit -p tsconfig.json` currently fails before this batch on
  unrelated JS/client/test typing issues, including `src/client/client.test.js`,
  `src/endpoints/flows.test.js`, `src/endpoints/settings.test.js`, and missing
  settings paths in checked-in `schema.d.ts`.
- A narrow smoke `tsconfig` gives Batch 5 a useful generated alias gate without
  converting the entire JS package to strict TypeScript in one diff.

## Generated Schema Regeneration Decision

Default decision: do not regenerate `frontend/packages/intric-js/src/types/schema.d.ts`
in Loop Iteration 1.

Evidence:

- The checked-in schema already contains generated counterparts for the core
  Flow runtime/API shapes this batch needs.
- Batch 1 and Batch 4 journals record that full local regeneration caused
  unrelated churn and that generated cleanup belongs here, but the current
  task can reduce drift by using the checked-in schema.
- `FlowDocumentRenderLimits` is the visible gap: backend routes exist, but the
  checked-in generated schema lacks the path/schema. This is documented as a
  generated-schema gap instead of papered over with a new manual surface.
- Closure trigger: delete the manual `FlowDocumentRenderLimits` type when a
  clean generated schema update includes
  `FlowDocumentRenderLimitsPublic`,
  `FlowDocumentRenderLimitsUpdate`, and the
  `/api/v1/settings/flow-document-render-limits` path.

Regeneration trigger:

- Only regenerate if Claude or validation proves the checked-in schema cannot
  support safe aliases.
- If regeneration is required, split generated `schema.d.ts` churn from
  handwritten alias/test changes in the final staging recommendation.

## API/Client Impact

- No route changes.
- No operation ID changes.
- No request/response model changes.
- No error shape changes.
- No OpenAPI tag changes.
- No generated-client package rename.
- Public TypeScript alias shapes become generated-backed. This can surface
  real optionality and enum differences to frontend consumers, which is the
  intended type-drift reduction.

## Package Naming Decision

Create `docs/refactor/execution/batch-5-generated-frontend-types/naming-decision.md`.

Decision to document:

- Keep `@intric/intric-js` and `frontend/packages/intric-js` for Batch 5.
- Do not rename to an Eneo package in this batch.
- Do not create `@eneo/*` aliases or dual packages.
- Revisit package naming only in a dedicated migration after consumer inventory.

## Exact Files Expected To Change

Planned source/test changes:

- `frontend/packages/intric-js/src/types/resources.d.ts`
- `frontend/packages/intric-js/src/types/flow-resource-aliases.types.ts`
- `frontend/packages/intric-js/tsconfig.type-smoke.json`
- `frontend/packages/intric-js/package.json`
- `frontend/packages/intric-js/src/endpoints/flows.js` only if formatting is
  required to make the existing `bun run lint` validation meaningful.
- `frontend/apps/web/src/lib/features/flows/components/flowRunProgress.ts`
- `frontend/apps/web/src/lib/features/flows/components/FlowRunProgressPanel.svelte`
- `frontend/apps/web/src/lib/features/flows/components/FlowRunEvidence.svelte`
- `frontend/apps/web/src/lib/features/flows/components/FlowRunEvidenceStepCard.svelte`
- `frontend/apps/web/src/lib/features/flows/components/FlowRunDialog.svelte`
- `frontend/apps/web/src/lib/features/flows/components/FlowRunDialogRuntimeStep.svelte`
- `frontend/apps/web/src/lib/features/flows/components/flowRunKnowledgeTrace.ts`
- `frontend/apps/web/src/lib/features/flows/components/FlowChunkViewer.svelte`

Planned docs/audit artifacts:

- `docs/refactor/execution/batch-5-generated-frontend-types/plan.md`
- `docs/refactor/execution/batch-5-generated-frontend-types/journal.md`
- `docs/refactor/execution/batch-5-generated-frontend-types/naming-decision.md`
- `docs/refactor/execution/batch-5-generated-frontend-types/retrospective-1.md`
- `docs/refactor/execution/batch-5-generated-frontend-types/claude-reconciliation-1.md`
- second-iteration retrospective/reconciliation files as required by the loop.

Expected not to change unless validation proves unavoidable:

- `frontend/packages/intric-js/src/types/schema.d.ts`
- `frontend/packages/ui/src/**`

## Validation Commands

Required by the user prompt:

```bash
cd frontend && bun run check
```

```bash
cd frontend/packages/intric-js && bun run lint
```

Package type/import smoke:

```bash
cd frontend/packages/intric-js && bun run check
```

```bash
cd frontend/apps/web && bun run check
```

Additional targeted source diff checks:

```bash
git diff --check -- \
  frontend/packages/intric-js/src/types/resources.d.ts \
  frontend/packages/intric-js/src/types/flow-resource-aliases.types.ts \
  frontend/packages/intric-js/tsconfig.type-smoke.json \
  frontend/packages/intric-js/package.json \
  frontend/packages/intric-js/src/endpoints/flows.js \
  frontend/apps/web/src/lib/features/flows/components/flowRunProgress.ts \
  frontend/apps/web/src/lib/features/flows/components/FlowRunProgressPanel.svelte \
  frontend/apps/web/src/lib/features/flows/components/FlowRunEvidence.svelte \
  frontend/apps/web/src/lib/features/flows/components/FlowRunEvidenceStepCard.svelte \
  frontend/apps/web/src/lib/features/flows/components/FlowRunDialog.svelte \
  frontend/apps/web/src/lib/features/flows/components/FlowRunDialogRuntimeStep.svelte \
  frontend/apps/web/src/lib/features/flows/components/flowRunKnowledgeTrace.ts \
  frontend/apps/web/src/lib/features/flows/components/FlowChunkViewer.svelte \
  docs/refactor/execution/batch-5-generated-frontend-types
```

```bash
git diff --name-only
```

Baseline already observed before implementation:

- `cd frontend/packages/intric-js && bun x tsc --noEmit -p tsconfig.json`
  fails on existing JS/package typecheck issues unrelated to this batch.
- `cd frontend/packages/intric-js && bun run lint` fails on existing Prettier
  formatting in `src/endpoints/flows.js`; the plan allows formatting that file
  because it is a Flow wrapper file in this batch's package scope.

## Acceptance Criteria

- Flow public/runtime aliases in `resources.d.ts` no longer manually define
  backend-owned public API shapes where generated schemas exist.
- UI-only retained types are named and justified.
- Generated schema gaps are documented instead of hidden by new manual types.
- Package-local type/import smoke coverage proves the generated aliases are
  importable and rejects the deliberate drift cases listed above.
- Duplicate `FlowRunStepOutput` / `FlowStepResult` public names are replaced by
  one canonical `FlowRunStep` alias in current consumers.
- The smoke fixture rejects the five enumerated drift cases.
- `rg -n "FlowRunStepOutput|FlowStepResult"` returns no source consumers after
  the canonical `FlowRunStep` migration, except historical docs if present.
- Package naming decision is documented and no rename ships.
- Existing unrelated dirty files remain untouched.
- Latest Claude review must be green, or all accepted/partial findings must be
  fixed and reconciled, before the batch reaches the commit boundary.

## Rollback

- Revert `resources.d.ts` Flow alias changes as one block if frontend type fallout is
  larger than local cleanup.
- Revert the `FlowRunStep` consumer rename as one block if app check fails.
- Remove the package-local smoke `check` script and `tsconfig.type-smoke.json`
  if the package-level check approach proves too brittle.
- Keep `schema.d.ts` unchanged unless a separate generated diff is explicitly
  approved in the final staging list.
