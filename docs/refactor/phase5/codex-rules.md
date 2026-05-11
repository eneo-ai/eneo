# Phase 5 Codex Rules Proposal

TL;DR:
1. These are proposal-only guardrails for future implementation sessions; no source or agent config was changed.
2. Rules focus on preventing known regressions: deprecated imports, fake interfaces, broad JSON, raw scope reads, global OpenAPI patches, and frontend type drift.
3. Every rule includes intent, pattern, allowed exceptions, example violation, and example allowed usage.
4. The rules should be enforced as warnings first except for writes to kill-listed paths after deletion.
5. Highest priority: deprecated imports, typed-boundary escapes, flow-specific OpenAPI surgery, and raw AI Builder scope reads.

## Rule Table

| Rule | Intent | Pattern | Allowed Exceptions | Example Violation | Example Allowed Usage |
|---|---|---|---|---|---|
| `no-flow-compat-imports` | Stop recreating false owners after shim deletion. | New imports from `intric.flows.flow_repo`, `flow_version_repo`, `flow_service`, `flow_run_repo`, `flow_run_service`, `flow_dispatch`, or `flow.py` once migrated. | Migration PR that removes the final import in the same diff. | `from intric.flows.flow_run_service import FlowRunService` | `from intric.flows.application.flow_run_service import FlowRunService` |
| `no-router-callable-reexports` | Keep endpoint ownership in leaf routers. | New `__all__` or imports of endpoint callables inside aggregator routers. | Temporary route assembly module exposing only `router`. | `from .flow_run_execution_router import create_flow_run` in aggregator. | `router.include_router(flow_run_execution_router.router)` |
| `no-ai-builder-star-barrel-growth` | Prevent `ai_builder_models.py` from gaining more ownership before migration. | New imports or exports from `ai_builder_models.py`. | A migration-only diff reducing imports. | `from .ai_builder_models import PlannerPlanEnvelope` | `from .ai_builder_api_models import PlannerPlanEnvelope` |
| `warn-domain-any-dict` | Keep typed contracts meaningful. | New `Any`, `dict[str, Any]`, or broad JSON aliases in `backend/src/intric/flows/domain`, `application`, or `runtime` owned envelopes. | Arbitrary user/model output explicitly named `JsonValue` with owner and parser boundary. | `payload: dict[str, Any]` in a runtime command. | `PublishedFlowDefinition` parser with an explicit `schema_version` plus `freeform_output: JsonValue`. |
| `warn-new-jsonb-without-policy` | Stop hidden schemas. | New SQLAlchemy JSON/JSONB column without owner, parser, version, migration, corruption behavior, and tests. | Test fixture tables. | `metadata_json = mapped_column(JSONB)` with no contract. | `definition_json` with `schema_version`, parser, migration test. |
| `warn-broad-except-runtime` | Classify runtime failures. | New `except Exception` in flow runtime/application code. | True outer boundary with categorized logging, translation, retry/terminalization policy. | `except Exception: pass` in executor. | `except Exception as exc: terminalize_unexpected_failure(... failure_category="bug")` |
| `no-http-exception-outside-adapter` | Keep domain/application HTTP-free. | New `HTTPException` outside `api/` or server HTTP adapter modules. | None without ADR. | `raise HTTPException(404)` in service. | Raise domain error and map in router/exception handler. |
| `no-raw-request-scope-flow` | Centralize authorization. | Reads of `request.state.api_key_scope_type` or `api_key_scope_id` in flow/AI Builder routes. | Global auth middleware only. | AI Builder route checks `Request.state` directly. | `FlowPrincipal` plus `FlowAccessPolicy.require(...)`. |
| `no-string-flow-access` | Replace stringly typed permissions. | New `required_access: str` or action strings in flow policy calls. | Migration wrapper around old helper. | `enforce_flow_scope(required_access="manage")` in new endpoint. | `require_flow_action(FlowApiAction.EDIT)` |
| `no-flow-specific-openapi-surgery` | Fix schemas at source. | New flow endpoint schema rewrites in `server/main.py` or global OpenAPI postprocessor. | Global generator compatibility not specific to flow endpoints. | Patching `/flows/{id}/files/` schema in `custom_openapi`. | Endpoint signature/model emits correct multipart schema. |
| `require-pagination-contract` | Make list APIs usable. | New/refactored list endpoint without `has_more` or `total_count`. | Internal-only endpoint documented as non-paginated. | `PaginatedResponse(count=len(items))` only. | `PaginatedResponse(count=len(items), has_more=...)` |
| `no-dual-run-file-shapes` | Delete top-level `file_ids` drift. | New support for both top-level `file_ids` and richer `step_inputs.files` as public request contract. | Short migration adapter with deletion date and telemetry. | `FlowRunCreateRequest.file_ids` plus new `StepRunInput.files`. | Canonical `step_inputs[step_id].file_ids` only. |
| `require-dag-rerun` | Prevent ordinal invalidation bugs. | Rerun code returning or computing invalidation by step order range. | Display-only order labels after DAG computation. | `invalidated_step_orders = range(step.order, last)` | `invalidated_step_ids = dependency_graph.descendants(step_id)` |
| `require-review-yield` | Prevent worker starvation. | Human review implementation that awaits human input inside worker task. | None. | Worker loops until review approved. | Worker persists checkpoint and exits; resume dispatches fresh task. |
| `warn-frontend-any-flow` | Keep frontend contracts typed. | New `any`, `as any`, `@ts-ignore`, `@ts-expect-error`, or public `Record<string, unknown>` in flow frontend boundary code. | Narrow UI-only unknown parsing with type guard and comment. | `const run = response as any` | `type FlowRun = components["schemas"]["FlowRunPublic"]` |
| `no-manual-flow-contract-types` | Generated schema is canonical after PRD-004. | New manual Flow runtime/API types in `resources.d.ts` or AI Builder `protocol.ts`. | UI-only view model not present in API. | Manual `type FlowRunStatus = "queued" | ...` | Alias to `components["schemas"]["FlowRunStatus"]`. |
| `no-driver-service-mirror` | One frontend state owner. | Field-by-field copying of full workflow state between Driver and Service/controller. | Stateless projection/view model derived from canonical owner. | `#applyState(driver.state)` copies all fields. | Driver parses SSE, Service owns state; or Driver owns state, adapter only views. |
| `warn-restating-comments` | Avoid comments that narrate code. | New comments matching "set x", "get y", "temporary" without owner/date/deletion condition, or compatibility without gate. | Intent comments about migration, security, ordering, external behavior. | `// Backward compatibility for old callers` with no gate. | `// Remove after migration 202604xx proves zero template_file_id rows.` |
| `warn-file-loc-hotspot` | Stop unchecked hotspot growth. | New file over 400 LOC or function over 60 LOC in flow/AI Builder without responsibility note. | Generated files; deliberate deep module with documented interface. | Adding 200 LOC to `ai_builder_planner.py`. | Extracting a planner turn use case with typed input/output. |
| `prompt-before-interface` | Avoid fake seams. | New interface/protocol/ABC/factory/adapter with one implementation. | External service seam, generated client seam, queue/task boundary, or documented second implementation. | `class FlowRunServicePort(Protocol)` only for mocking. | Concrete class injected directly, or Protocol for external storage provider. |
| `prompt-before-celery-blob` | Keep task payloads small and typed. | New Celery task args carrying large state blob or untyped dict. | Temporary migration command with explicit size and deletion gate. | `execute_flow_run(payload: dict[str, Any])` | `FlowRunExecutionCommand(run_id, flow_id, tenant_id, principal)` |
| `prompt-before-bulk-generation` | Preserve reviewability. | Bulk generated/manual file creation. | Generated OpenAPI/TS output separated from handwritten diff. | Generated schema and frontend rewrites in same commit. | One generated-only diff followed by handwritten adaptation diff. |
| `prompt-before-migration` | Make data-shape changes explicit. | New Alembic migration touching flow tables. | None. | Migration without rollback/preflight/zero-row query. | Migration with preflight, backfill, tests, rollback note. |

## Suggested Enforcement Levels

| Level | Rules |
|---|---|
| Hard block after migration | `no-flow-compat-imports`, `no-router-callable-reexports`, `no-ai-builder-star-barrel-growth` once replacement owners land. |
| Warning with required justification | Typed-boundary, JSONB, broad exception, frontend `any`, LOC hotspot, interface, Celery payload, migration rules. |
| Design review required | Rerun, human review, audit fail policy, permission migration, generated type strategy. |

## Implementation Notes

- The exact mechanism can be import-linter, Ruff custom rules, ESLint, pyright strictness, code review checklist, or Codex prefix rules.
- During migration PRs, warnings should allow a diff that reduces violations even if it touches deprecated paths.
- Generated files should be excluded from LOC/comment rules but included in generated-client drift checks.
