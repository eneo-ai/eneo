# T019 Next Slice Decision

## Decision

Activate T006 as the next Worker: a public API golden journey for Flow web-app
consumers and LLM-generated clients.

## Why This Outranks Alternatives

Runtime P0s now have receipts for required runtime input, review edit contract
validation, failed-state persistence, late-output terminalization, and review-open
terminalization.

The next highest ROI is executable API-consumer documentation:

- `backend/tests/integration/flows/test_flow_consumer_api_contract.py` already
  covers pieces of the journey, but no single journey proves that a client can
  discover runtime paths, read the run contract, handle typed missing-input
  errors, create a valid run, handle review checkpoint validation, resume, and
  fetch output/evidence without backend-source knowledge.
- `FlowRuntimePathsPublic` currently exposes create/list/get/steps/evidence
  templates, but not review checkpoint templates. Review endpoint docs exist,
  but discoverability from the published runtime projection is incomplete for
  generated clients.
- Cleanup should remain blocked until public behavior/API tests protect the
  replacement behavior.
- Typed JSONB/data-boundary work is still valuable, but the public consumer
  journey reduces fear of changing those boundaries later.
- Frontend work remains blocked until backend error/path contracts are stable.

## Proposed T006 Worker

Objective:

Add a public Flow API golden journey that acts as executable documentation for a
web app or LLM-generated client. The journey must prove that a client can inspect
a published flow, fetch the run contract, identify required fields/file inputs,
identify final output type and review steps, submit a missing required runtime
input and receive a typed error, submit a valid run request, handle a review
checkpoint with typed edit errors, approve/resume it, and fetch run output or
evidence through discoverable paths.

Allowed files:

- `backend/src/intric/flows/api/flow_models.py`
- `backend/src/intric/flows/api/flow_assembler.py`
- `backend/src/intric/flows/api/flow_run_execution_router.py`
- `backend/tests/integration/flows/test_flow_consumer_api_contract.py`
- `backend/tests/unit/test_flow_openapi_contract.py`
- `docs/goals/flow-runtime-ai-builder-maintainability/notes/T006-public-api-golden-journey.md`
- `docs/goals/flow-runtime-ai-builder-maintainability/state.yaml`

`flow_run_contract_models.py` is intentionally excluded. The run contract already
owns form fields, runtime file inputs, final output, and review-step contracts.
This slice should not add fields there unless a later red test proves the
pre-run contract itself is missing information.

## Public Contract Shape

Add one grouped review-path field to `FlowRuntimePathsPublic`:

```python
class FlowReviewCheckpointRuntimePathsPublic(BaseModel):
    active_template: str
    edit_template: str
    approve_template: str
    reject_template: str
    resume_template: str
```

`FlowRuntimePathsPublic.review_checkpoints` should contain:

- `active_template`: `/api/v1/flows/{flow_id}/runs/{run_id}/review-checkpoints/active/`
- `edit_template`: `/api/v1/flows/{flow_id}/runs/{run_id}/review-checkpoints/{checkpoint_id}/`
- `approve_template`: `/api/v1/flows/{flow_id}/runs/{run_id}/review-checkpoints/{checkpoint_id}/approve/`
- `reject_template`: `/api/v1/flows/{flow_id}/runs/{run_id}/review-checkpoints/{checkpoint_id}/reject/`
- `resume_template`: `/api/v1/flows/{flow_id}/runs/{run_id}/review-checkpoints/{checkpoint_id}/resume/`

Do not rename existing `runtime_paths` fields. Keep
`FlowAssembler.to_runtime_public(...)` as the single runtime-path emission owner.
If avoiding route-string duplication requires a shared constant module, stop and
return to Judge before creating a new file.

## Red Assertions

The Worker must start with failing tests that prove the current gap:

- Integration: `published_payload["runtime_paths"]["review_checkpoints"]["active_template"]`
  exists and is used to call the active checkpoint endpoint. This fails today
  because `review_checkpoints` does not exist.
- Integration: the same journey uses `edit_template`, `approve_template`, and
  `resume_template` from `runtime_paths.review_checkpoints` instead of hard-coded
  review URLs. This fails today because those templates do not exist.
- OpenAPI: `FlowRuntimePathsPublic` exposes a `review_checkpoints` property
  whose schema points to the grouped review-path model and documents
  `{run_id}` and `{checkpoint_id}` placeholders. This fails today because the
  field/model do not exist.

The Worker receipt must name which assertions failed before implementation.

Expected implementation shape:

- Prefer extending `FlowRuntimePathsPublic` with review checkpoint path templates
  over duplicating hard-coded review URLs in tests or docs.
- Keep routers thin; only documentation/schema metadata should change in routers
  unless a red test proves behavior is missing.
- Keep `FlowRunContractService` as the owner of pre-run fields/output/review
  contracts; do not duplicate run-contract assembly in tests or routers.
- The integration golden journey may use controlled DB seeding for runtime
  progress/checkpoints, but all consumer interactions must go through HTTP API
  endpoints.
- `flow_run_execution_router.py` changes are capped to OpenAPI response examples
  and operation description text only. Handler bodies, signatures, dependency
  wiring, and runtime behavior are out of scope.
- DB seeding is allowed only to bypass Celery/provider lifecycle transitions
  that a real API client cannot force in-process. Contract reads, path
  discovery, typed error responses, review edit/approve/resume calls, polling,
  and evidence retrieval must be HTTP-driven.
- Keep existing focused tests unless a new golden journey fully subsumes one and
  the deletion is obvious. Do not delete tests in this Worker without explicit
  receipt proof.
- Do not re-assert idempotency replay/conflict in the new golden journey; the
  existing consumer contract test already covers it, and create-run fingerprint
  canonicalization remains a separate decision.
- New OpenAPI assertions should encode consumer invariants that integration
  tests cannot prove, not restate generic JSON Schema structure.

Verify:

- `cd backend && uv run pytest tests/integration/flows/test_flow_consumer_api_contract.py -q`
- `cd backend && uv run pytest tests/unit/test_flow_openapi_contract.py -q`
- `cd backend && uv run pyright src/intric/flows/api/flow_models.py src/intric/flows/api/flow_assembler.py src/intric/flows/api/flow_run_execution_router.py tests/integration/flows/test_flow_consumer_api_contract.py tests/unit/test_flow_openapi_contract.py`
- `cd backend && uv run ruff check src/intric/flows/api/flow_models.py src/intric/flows/api/flow_assembler.py src/intric/flows/api/flow_run_execution_router.py tests/integration/flows/test_flow_consumer_api_contract.py tests/unit/test_flow_openapi_contract.py`
- `cd backend && uv run ruff format --check src/intric/flows/api/flow_models.py src/intric/flows/api/flow_assembler.py src/intric/flows/api/flow_run_execution_router.py tests/integration/flows/test_flow_consumer_api_contract.py tests/unit/test_flow_openapi_contract.py`
- `git diff --check`
- `node /Users/ccimen/.codex/skills/goal-maker/scripts/check-goal-state.mjs docs/goals/flow-runtime-ai-builder-maintainability/state.yaml`

Stop if:

- The journey requires frontend changes.
- The journey requires real Celery execution or sleeps/polling instead of
  deterministic API plus controlled DB state transitions.
- The implementation creates a second run-contract owner or hard-codes contract
  assembly in the router.
- The implementation changes `flow_run_execution_router.py` handler bodies,
  signatures, dependencies, dispatch behavior, or transaction behavior.
- The implementation adds fields to `FlowRunContractPublic` without returning to
  Judge with the exact field and red assertion.
- The review path shape appears to require a versioning bump or generated-client
  migration concern beyond additive fields.
- The implementation broadens into cleanup, typed JSONB migration, AI Builder
  planning, or UI redesign.
- The implementation weakens existing OpenAPI schema quality or removes current
  error examples.
- New `Any`, casts, `# type: ignore`, or untyped dict-shaped public models are
  introduced.

## Claude Challenge Request

Challenge whether T006 is the right next slice and whether the allowed files and
acceptance criteria are narrow enough. If another task has higher maintainability
ROI now, identify it with evidence and exact scope.

## Claude Gate

- Iteration 1: `changes_required`, `GREEN_LIGHT: no`, `MIN_SCORE: 6`.
- Iteration 2 after tightening scope: `green`, `GREEN_LIGHT: yes`, `MIN_SCORE: 8`.

Accepted iteration-1 critiques:

- Remove `flow_run_contract_models.py` unless a specific field change is proven.
- Cap `flow_run_execution_router.py` to OpenAPI metadata/description only.
- Name concrete red assertions before activating the Worker.
- Restrict DB seeding to Celery/provider lifecycle bypass only; consumer-visible
  actions must be HTTP-driven.
- Avoid duplicating existing idempotency coverage in the new journey.
