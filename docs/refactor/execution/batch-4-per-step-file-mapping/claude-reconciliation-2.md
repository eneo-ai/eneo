# Batch 4 Claude Reconciliation - Iteration 2

## Claude Result

- Artifact:
  `.codex/artifacts/claude-peer-loop-batch-4-per-step-file-mapping-verification-20260430T094959Z.md`
- Verbatim attack:
  `docs/refactor/execution/batch-4-per-step-file-mapping/claude-attack-2.md`
- Verdict: `green`
- `GREEN_LIGHT: yes`
- Minimum score: `8`

## Findings

| Finding | Classification | Codex action |
|---|---|---|
| Iteration 1 accepted findings were closed. | accepted | No further action beyond preserving the fixes verified by Claude. |
| Route had a dead defensive idempotency-key fallback using `getattr(request, "headers", {})`. | accepted | Removed the fallback and updated the direct unit test to pass `idempotency_key` the way FastAPI injects the header parameter. |
| Migration mixed `op.f(...)` names and raw string composite FK names. | accepted | Wrapped the composite FK names in `op.f(...)` for consistency. |
| `cast(object, data)` in the Pydantic validator is ceremonial. | rejected: disagree | The cast is needed for strict Pyright after the before-validator narrows `object` to `Mapping[Unknown, Unknown]`; `validation-2.log` records the failing and passing Pyright runs. |
| Denormalized result projection `step_id` / `step_order` lacks a relational guard against direct inconsistent inserts. | rejected: out-of-scope | The repository is the only writer in this batch and copies values from the persisted `FlowStepResults` row. A second writer or direct mapping endpoint should add a consistency guard. |
| `FlowRunCreateRequest` still uses Pydantic's default extra-field behavior except for the removed `file_ids` key. | rejected: out-of-scope | Broad `extra="forbid"` request-schema hardening belongs in a separate API contract pass; Batch 4 only removes the top-level `file_ids` source contract. |
| Empty `step_inputs={}` and omitted `step_inputs` should both write zero projection rows. | rejected: out-of-scope | Current implementation already gates projection writes on non-empty normalized step file lists. A dedicated pin can be added if a future batch touches empty-vs-omitted request semantics. |

## Resulting Changes

- Removed the remaining defensive `getattr` branch from create-run idempotency
  forwarding.
- Normalized migration composite FK names through Alembic's naming convention
  helper.

## Gate

Claude returned green, but Codex accepted two low-risk cleanup findings. The
loop returns to focused validation as Iteration 3.
