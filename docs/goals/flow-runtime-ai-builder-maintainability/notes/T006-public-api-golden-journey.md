# T006 Public API Golden Journey

## Result

Done.

This slice added an additive public runtime-path contract so web apps and
LLM-generated clients can discover human-in-loop review checkpoint routes from
`GET /api/v1/flows/{id}/published/` before a run reaches `awaiting_review`.

## Red Assertions

The first red run failed on the intended missing contract:

- `tests/integration/flows/test_flow_consumer_api_contract.py::test_flow_consumer_runtime_routes_support_start_replay_poll_and_steps`
  failed with `KeyError: 'review_checkpoints'`.
- `tests/integration/flows/test_flow_consumer_api_contract.py::test_flow_consumer_golden_journey_uses_review_runtime_paths`
  failed with `KeyError: 'review_checkpoints'`.
- `tests/unit/test_flow_openapi_contract.py::test_openapi_runtime_paths_expose_review_checkpoint_templates`
  failed with `KeyError: 'review_checkpoints'`.

## Changed Files

- `backend/src/intric/flows/api/flow_models.py`
- `backend/src/intric/flows/api/flow_assembler.py`
- `backend/tests/integration/flows/test_flow_consumer_api_contract.py`
- `backend/tests/unit/test_flow_openapi_contract.py`
- `docs/goals/flow-runtime-ai-builder-maintainability/notes/T006-public-api-golden-journey.md`
- `docs/goals/flow-runtime-ai-builder-maintainability/state.yaml`

## Implementation

Canonical owner:

- `FlowAssembler.to_runtime_public(...)` remains the only runtime-path emission
  owner.
- `FlowRuntimePathsPublic` remains the public schema owner for published flow
  runtime paths.

Added public schema:

- `FlowReviewCheckpointRuntimePathsPublic`
- `FlowRuntimePathsPublic.review_checkpoints`

The grouped path contract exposes:

- `active_template`
- `edit_template`
- `approve_template`
- `reject_template`
- `resume_template`

No router behavior, handler signatures, dispatch wiring, transaction behavior,
run-contract models, or FlowRunContractService logic changed.

## API Consumer Proof

The consumer integration test now proves:

- A client can fetch the published runtime projection.
- A client can discover `create_run`, `run_contract`, `evidence_template`, and
  grouped review checkpoint path templates from `runtime_paths`.
- A client can create a valid run through the discovered `create_run` path.
- A client can poll run state and list step output.
- A client can fetch evidence through the discovered `evidence_template`.
- A client can fetch the run contract and identify `final_output` and
  `steps_requiring_review`.
- A client can fetch active review checkpoint state through
  `review_checkpoints.active_template`.
- A client can submit an invalid review edit and receive
  `typed_io_contract_violation`.
- A client can submit a valid review edit, approve the checkpoint, and resume
  the run through discovered review checkpoint templates.

Existing tests still cover typed missing required runtime input errors:

- `test_flow_run_create_rejects_missing_required_runtime_step_inputs`

Existing tests still cover idempotency replay/conflict:

- `test_flow_consumer_runtime_routes_support_start_replay_poll_and_steps`

## Maintainability Self-Review

Maintainability score: 8.5/10.

- Canonical ownership: improved. Runtime path discovery stayed inside
  `FlowRuntimePathsPublic` and `FlowAssembler.to_runtime_public(...)`.
- Fear-of-change reduction: improved. Future API consumers can rely on one
  published runtime projection instead of reading route source to build review
  URLs.
- Type safety: no new `Any`, no new `cast`, no new `# type: ignore`.
- Error contract quality: existing typed missing-input and review-edit errors are
  covered by HTTP tests; this slice did not introduce new error codes.
- Test quality: behavior-focused API tests exercise real HTTP endpoints and only
  seed DB state to bypass provider/Celery progress.
- Comment quality: no source comments added.
- Complexity: no new services, wrappers, interfaces, fallback paths, or broad
  routing changes.
- Deletion quality: no cleanup performed in this Worker.

Anti-patterns avoided:

- Did not add a second runtime-path owner.
- Did not duplicate run-contract assembly in routers or tests.
- Did not change router handler bodies.
- Did not broaden into frontend, AI Builder, typed JSONB, or cleanup work.
- Did not re-open idempotency fingerprint canonicalization.

## Verification

- PASS `cd backend && uv run pytest tests/integration/flows/test_flow_consumer_api_contract.py -q`
- PASS `cd backend && uv run pytest tests/unit/test_flow_openapi_contract.py -q`
- PASS `cd backend && uv run pyright src/intric/flows/api/flow_models.py src/intric/flows/api/flow_assembler.py src/intric/flows/api/flow_run_execution_router.py tests/integration/flows/test_flow_consumer_api_contract.py tests/unit/test_flow_openapi_contract.py`
- PASS `cd backend && uv run ruff check src/intric/flows/api/flow_models.py src/intric/flows/api/flow_assembler.py src/intric/flows/api/flow_run_execution_router.py tests/integration/flows/test_flow_consumer_api_contract.py tests/unit/test_flow_openapi_contract.py`
- PASS `cd backend && uv run ruff format --check src/intric/flows/api/flow_models.py src/intric/flows/api/flow_assembler.py src/intric/flows/api/flow_run_execution_router.py tests/integration/flows/test_flow_consumer_api_contract.py tests/unit/test_flow_openapi_contract.py`
- PASS `git diff --check`
- PASS `node /Users/ccimen/.codex/skills/goal-maker/scripts/check-goal-state.mjs docs/goals/flow-runtime-ai-builder-maintainability/state.yaml`

## Claude Commit Gate

- VERDICT: green
- GREEN_LIGHT: yes
- MIN_SCORE: 8
- Artifact: `.codex/artifacts/claude-peer-loop-t006-public-api-golden-journey-commit-gate-20260511T004802Z.md`

Claude approved local commit and raised two non-blocking follow-ups:

- Add a structural route-template parity test if future runtime path fields are
  added.
- Decide later whether cancel, rerun, and redispatch should also be advertised
  in the published runtime projection.
