# Batch 9 Claude Reconciliation 5

TL;DR:
1. Claude required changes on the first Slice 9.2 implementation review.
2. The blocking findings were valid for review-policy ownership and write-path validation.
3. The implementation now uses one typed `FlowStepReviewPolicy` contract across API, domain, persistence, published definitions, and runtime parsing.
4. `validate_steps` rejects review policies before publish/write when a step uses outbound delivery.
5. Claude returned `GREEN_LIGHT: yes`; Docker validation remains blocked by the host approval policy before execution.

## Review Artifacts

| Iteration | Artifact | Verdict | Green light | Minimum score |
|---|---|---:|---:|---:|
| 1 | `.codex/artifacts/claude-peer-loop-batch-9-slice-9-2-review-policy-open-command-20260502T165110Z.md` | `changes_required` | `no` | `5` |
| 2 | `.codex/artifacts/claude-peer-loop-batch-9-slice-9-2-review-policy-open-command-verification-20260502T170329Z.md` | `green` | `yes` | `9` |

## Accepted Changes

| Finding | Resolution |
|---|---|
| Review policy could bypass the write/publish validator. | `validate_steps` now calls `parse_flow_step_review_policy` for every step, so invalid review policies fail before the definition is persisted. |
| API/domain/published/runtime paths duplicated the contract as raw JSON. | `FlowStepCreateRequest`, `FlowStepPublic`, `FlowStep`, and `RuntimeStep` now use `FlowStepReviewPolicy`; repository and published-definition serialization use `model_dump(mode="json")`. |
| `parse_flow_step_review_policy` accepted raw output-mode strings and could leak enum conversion errors. | The parser now accepts `FlowOutputMode`; callers normalize before entry. |
| Outbound delivery errors could be hidden by malformed policy shape. | The outbound-delivery check now runs before shape validation when a policy is present. |
| The hand-written `to_json` method would drift from future fields. | Removed it in favor of Pydantic JSON-mode dumps. |
| `FlowAssembler.to_domain_step` dropped `review_policy`. | The assembler now preserves the typed policy from the API request into the domain step. |
| JSONB round-trip coverage was missing. | The checkpoint repository integration fixture now persists a review policy through `FlowRepository.create` and asserts the reloaded domain model is typed. |
| `next_step_ids` ownership was opaque. | `open_review_checkpoint_for_completed_step` now documents that the caller resolves graph topology and the repository only persists downstream IDs while holding run locks. |

## Rejected Or Deferred

| Claude suggestion | Decision |
|---|---|
| Enforce the outbound-review incompatibility directly on `FlowStep`. | Deferred. `validate_steps` is the canonical write/publish validator today; a `FlowStep` cross-field validator can be revisited if more policy fields need domain-level invariants. |
| Introduce a typed `PublishedStepDefinition` model. | Deferred. The slice keeps the current published-definition writer shape and adds parser/write-path tests instead. |
| Validate `next_step_ids` inside the repository open command. | Deferred to the service/runtime wiring slice. The repository is the SQL owner; the caller owns graph interpretation from the published run definition. |
| Run Docker validation. | Blocked before execution by this Codex host policy: `Rejected("approval required by policy, but AskForApproval is set to Never")`. Local backend validation passed. |

## Validation

| Command | Result |
|---|---|
| `uv run ruff check ...` from `backend/` on Slice 9.2 source/test files | Passed |
| `uv run ruff format --check ...` from `backend/` on Slice 9.2 source/test files | Passed |
| `uv run pyright ...` from `backend/` on Slice 9.2 source/test files | Passed, `0 errors` |
| `uv run python -m py_compile alembic/versions/20260502_flow_step_review_policy.py` from repo root | Passed |
| `uv run pytest tests/unittests/flows/test_flow_review_policy.py tests/unittests/flows/test_flow_validators.py tests/unittests/flows/test_published_definition_contract.py tests/integration/flows/test_flow_run_review_checkpoint_repository.py -q` from `backend/` | Passed, `54 passed`, `16` existing warnings |
| `docker exec -w /workspace/backend eneo-41ae93-eneo-1 .venv/bin/pytest tests/unittests/flows/test_flow_review_policy.py -q` | Blocked before execution by host policy |
| `git diff --check` | Passed |
| `rg -n "review_policy=\\{" backend/src` | Passed, no source matches |

## Forward Debt

| Owner slice | Debt | Acceptance note |
|---|---|---|
| Slice 9.3 | Wire `RuntimeStep.review_policy` into the executor pause/yield branch and call `open_review_checkpoint_for_completed_step`. | The repository command is intentionally dormant until runtime wiring chooses the checkpoint step from the published definition. |
| Slice 9.3 | Validate checkpoint `step_id` and downstream `next_step_ids` against the run's published definition before opening a checkpoint. | Repository locks and persists; service/runtime owns graph interpretation. |
| Runbook | Note that downgrading `20260502_flow_step_review_policy` drops `flow_steps.review_policy`. | Acceptable for unreleased Flows, but rollback instructions should state the data-loss precondition. |

## Implementation Gate

Slice 9.2 is implementation-ready after local validation and Claude green light.
