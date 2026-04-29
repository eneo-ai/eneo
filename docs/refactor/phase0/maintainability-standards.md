# Phase 0 Maintainability Standards

TL;DR:
1. The governing standard is canonical ownership: every concept must have one clear home and no unplanned parallel path.
2. The review will prefer deletion, merge, rename, and move recommendations before adding abstractions or compatibility layers.
3. Boundary contracts must be typed; broad JSON bags are findings unless they have an explicit schema owner and migration strategy.
4. Runtime recommendations must name persisted state, idempotency, transaction boundaries, retry behavior, crash behavior, and audit behavior.
5. Every reviewer must score against one declared scorecard and every PRD must be executable: scope, non-goals, acceptance criteria, validation commands, rollback/recovery, tests, and reviewability impact.

## Standards Read

| Standard | Relevant Lines | How It Applies |
|---|---|---|
| Maintainability standards | `docs/engineering/maintainability-standards.md:11`, `docs/engineering/maintainability-standards.md:23`, `docs/engineering/maintainability-standards.md:41-44` | Review every flow concept for a canonical owner and parallel implementations. |
| Reuse/deletion protocol | `docs/engineering/maintainability-standards.md:58`, `docs/engineering/maintainability-standards.md:66`, `docs/engineering/maintainability-standards.md:73-85` | Propose delete/merge paths for shims, legacy fallbacks, and duplicate schemas. |
| Interface justification | `docs/engineering/maintainability-standards.md:87`, `docs/engineering/maintainability-standards.md:174`, `docs/engineering/maintainability-standards.md:187-191` | Reject shallow interfaces and require reviewability/change-path analysis. |
| Comment/readability standard | `docs/engineering/comment-and-readability-standard.md:5`, `docs/engineering/comment-and-readability-standard.md:37-41` | Treat restating comments, unclear names, and week-one readability failures as findings. |
| API design standard | `docs/engineering/api-design-standard.md:3`, `docs/engineering/api-design-standard.md:22-36`, `docs/engineering/api-design-standard.md:43-47` | Routers are adapters; endpoint reviews must cover owners, operation IDs, error shape, OpenAPI/client impact, and contract tests. |
| Testing standard | `docs/engineering/testing-standard.md:3`, `docs/engineering/testing-standard.md:8-12`, `docs/engineering/testing-standard.md:16-24` | Tests must protect behavior, not internal calls; recommendations must name failure mode and layer. |
| Frontend state standard | `docs/engineering/frontend-state-standard.md:3`, `docs/engineering/frontend-state-standard.md:7-18` | Frontend state must have one owner; flag duplicated driver/service/component state, manual backend types, and unclear side-effect boundaries. |

## Review Rubric

Phase 2 must use the ten dimensions required by `prompt.md`. Phase 1 reviewers should use their prompt-specified dimensions; if a prompt scope does not define a narrower set, use the ten-dimension vector below. Human reviewability remains a required finding field from `AGENTS.md` even where it is not a separate score.

| Dimension | Score Meaning For This Review |
|---|---|
| Maintainability | Can a new senior engineer identify the entry point, concept owner, invariants, and change path in week one? |
| Code Quality | Are names concrete, control flow explicit, comments useful, types meaningful, and fallback paths intentional? |
| Clean Architecture | Are domain/application rules independent from HTTP, DB, queue, and UI details? |
| Separation of Concerns | Does each module own one lifecycle phase or domain concept rather than a grab bag? |
| Single Source of Truth | Are statuses, schemas, policies, state derivations, and generated/client types canonical? |
| Human Readability | Is the code understandable without reconstructing implicit conventions from tests or scattered helpers? |
| Runtime Reliability | Are retries, idempotency, crash recovery, duplicate starts, persisted state, and audit behavior explicit? |
| API Consumer DX | Can an external developer understand auth, inputs, uploads, run start, polling, evidence, errors, and recovery without reading backend source? |
| API Maintainer DX | Can a backend maintainer add endpoints, schemas, permissions, errors, tests, and generated-client updates safely? |
| Testability | Do tests protect behavior at the right layer without mocking private implementation details? |

Overall score is the minimum dimension score. Any dimension `<= 3` means refactor is required before further feature work; `4-6` means refactor opportunistically and do not worsen; `7-8` is ship-ready with normal follow-up; `9-10` is exemplar.

## Finding Template Required In Phase 1+

| Field | Requirement |
|---|---|
| Problem | Name the maintainability or correctness issue in one sentence. |
| Why it matters | Explain the failure mode or future change cost. |
| Evidence | Use file:line citations for code-backed claims. |
| Current owner | Name the current module/service/component owning the concept, if any. |
| Proposed canonical home | Name the target owner or state that none exists yet. |
| Merge/delete path | State what should be deleted, merged, renamed, moved, or not preserved. |
| Acceptance criteria | Give reviewable end-state checks. |
| Tests required | Name behavior, failure mode, test layer, fixtures, and why it survives refactors. |
| Risk/trade-off | Call out migration, compatibility, data, runtime, or DX risk. |
| Human reviewability impact | Explain how the recommendation makes future diffs easier to approve. |
| Confidence | High, medium, or low. |

## Phase 1 Reviewer Contract

Each parallel reviewer must:

- Stay documentation-only and write only the assigned `docs/refactor/phase1/*.md` output.
- Start with a five-line TL;DR.
- Use file:line evidence for concrete claims.
- Include inventories in tables.
- Include "No findings." for empty sections.
- Identify current owner and proposed canonical home.
- Prefer delete/merge/rename/move before adding new abstractions.
- Separate environmental/tooling failures from product architecture findings.
- Include tests required, risk/trade-off, reviewability impact, and confidence.
- Avoid PRDs or implementation code; Phase 4 owns PRDs.
- Treat cross-cutting concepts as owned review subjects, not leftovers for synthesis.
- Use the 25-minute Claude timeout for peer-review gates unless the user changes it.

## Concepts That Must Get Canonical Owners

| Concept | Seed Evidence | Why It Is High Risk |
|---|---|---|
| Flow definition/draft/published version | `backend/src/intric/database/tables/flow_tables.py:231-253`, `backend/src/intric/flows/application/flow_service.py:686-697`, `backend/src/intric/flows/runtime/step_definition_parser.py:33-42` | It crosses authoring API, SQLAlchemy tables, domain models, version snapshots, frontend editor state, generated client calls, and old-run compatibility. |
| Flow step contract/config/bindings | `backend/src/intric/flows/domain/flow.py:38-46`, `backend/src/intric/flows/runtime/step_definition_parser.py:46-90`, `frontend/apps/web/src/lib/features/flows/FlowEditor.ts:276` | It appears as JSONB, Pydantic `dict[str, Any]`, frontend records, AI Builder specs, and runtime parsing. |
| Flow run lifecycle/status | `backend/src/intric/flows/enums.py:64-69`, `backend/src/intric/database/tables/flow_tables.py:397-400`, `backend/src/intric/database/tables/flow_tables.py:439-444` | It crosses API creation/cancel/redispatch, Celery task dispatch, DB persisted status, runtime terminalization, audit, and UI polling. |
| Step result and attempt lifecycle | `backend/src/intric/flows/enums.py:72-85`, `backend/src/intric/database/tables/flow_tables.py:503-506`, `backend/src/intric/database/tables/flow_tables.py:570-572`, `backend/src/intric/flows/runtime/step_execution_runtime.py:738-1013` | It crosses execution, retries, evidence, provenance, token accounting, debug export, and frontend evidence display. |
| Runtime input/file upload contract | `backend/src/intric/flows/api/flow_upload_router.py:22-81`, `backend/src/intric/flows/api/flow_upload_router.py:149-266`, `frontend/apps/web/src/lib/features/flows/components/FlowRunDialog.svelte:67` | It crosses run-contract API, upload endpoints, file validation, frontend run dialog, and generated client helpers. |
| Evidence/redaction/provenance | `backend/src/intric/flows/api/flow_run_evidence_router.py:66-135`, `backend/src/intric/flows/runtime/executor.py:1089-1111`, `frontend/apps/web/src/lib/features/flows/components/FlowRunEvidence.svelte:46-49` | It crosses policy, debug export, audit logging, JSON export, frontend evidence viewers, and support/compliance use cases. |
| AI Builder session/planning/materialization | `backend/src/intric/flows/ai_builder/ai_builder_planner.py:944-1536`, `backend/src/intric/flows/ai_builder/ai_builder_proposal_processor.py` (2,663 LOC), `frontend/apps/web/src/lib/features/flows/ai-builder/FlowAIBuilderDriver.ts:578` | It crosses chat sessions, planner state, prompts, draft validation, repair loops, materialization into flows, and frontend driver protocol. |
| Frontend flow state | `frontend/apps/web/src/lib/features/flows/FlowEditor.ts:276`, `frontend/apps/web/src/lib/features/flows/ai-builder/FlowAIBuilderService.svelte.ts:65`, `frontend/apps/web/src/routes/(app)/spaces/[spaceId]/flows/ai-builder/+page.svelte:16` | It crosses SvelteKit route `load`, managers, `FlowEditor`, AI Builder service/driver, components, and generated/client types. |
| API/generated client contract | `backend/src/intric/flows/api/flow_models.py:230`, `backend/src/intric/flows/api/flow_models.py:931`, `frontend/packages/intric-js/src/endpoints/flows.js:440` | It crosses FastAPI models/OpenAPI, `frontend/packages/intric-js`, handwritten protocol types, and Svelte components. |
| Legacy/fallback/compatibility paths | `backend/src/intric/flows/flow.py:1`, `backend/src/intric/flows/flow_service.py:1`, `backend/src/intric/flows/flow_run_service.py:1`, reverse-import counts in `docs/refactor/phase0/baseline.md` | The repository is pre-production, so unowned compatibility layers need explicit deletion or migration points. |
| Celery/operability lifecycle | `backend/src/intric/flows/runtime/celery_app.py:25-38`, `backend/src/intric/flows/runtime/tasks.py:179`, `backend/src/intric/flows/runtime/tasks.py:362`, `backend/celerybeat-schedule` | Queue routing, beat reconciliation, runtime artifacts, retry semantics, crash recovery, and audit behavior need one operability owner. |

## Operational AI Slop Definition

For this review, "AI slop" means evidence-backed maintainability defects, not an aesthetic label. Flag:

- vague names that hide lifecycle responsibility, such as `manager`, `processor`, `handler`, `data`, `result`, and `item`, when a domain name is available;
- comments that restate code instead of explaining an invariant, trade-off, migration, or incident history;
- compatibility, fallback, repair, or legacy branches without an owner, deletion point, or shipped-user reason;
- broad `Any`, `dict[str, Any]`, `Record<string, unknown>`, or `as any` at application/domain/state boundaries without a typed parser;
- tests that preserve implementation shape or mock internals rather than protecting behavior;
- pass-through services, fake seams, or one-implementation interfaces.

## Non-Goals For This Review Pass

| Non-Goal | Reason |
|---|---|
| Implement source changes | `AGENTS.md` says architecture review sessions should write only review/planning/PRD output under `docs/refactor/`. |
| Fix formatting/typecheck failures | Baseline only records them; implementation PRDs can later schedule fixes. |
| Preserve compatibility for imaginary shipped users | The standards prefer deletion unless a real migration plan or second use case exists. |
| Add abstractions for future flexibility | Interfaces must earn existence through real seams and explicit complexity reduction. |
| Rewrite tests mechanically | Test recommendations must be behavior-focused and tied to refactor risk. |

## Validation Expectations

Every PRD generated later should name the smallest useful validation set. The baseline commands available now are:

```bash
cd backend && ./.venv/bin/python -m pytest --collect-only
cd backend && uv run pyright
cd backend && uv run ruff check --no-fix src/intric/flows tests/unittests/flows tests/integration/flows
pnpm -C frontend check
```

When a command is currently failing for unrelated repo-wide reasons, the PRD must either propose a narrower validation command or explicitly state that the command is a residual baseline blocker.

## Confidence

High. The standards are explicit and map directly to the flow review scope. The only unresolved part is how strictly each standard should be staged across PRDs, which depends on Phase 1 evidence and Claude peer review.
