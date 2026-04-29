# Batch 2 - Permissions And Data Contracts Journal

## Status

IN_PROGRESS

## Iteration Log

### Iteration 1

- Plan: `docs/refactor/execution/batch-2-permissions-data-contracts/plan.md`
- Validation: local fallback GREEN; Docker commands blocked by host approval policy before execution
- Retrospective: `docs/refactor/execution/batch-2-permissions-data-contracts/retrospective-1.md` (`GREEN`, 0 fails)
- Claude review:
  - Iteration 1: `.codex/artifacts/claude-peer-loop-batch-2-permissions-data-plan-20260429T202345Z.md`
  - Result: `GREEN_LIGHT: no`, `VERDICT: changes_required`
- Reconciliation: plan revised to address accepted source-of-truth, AI Builder action, published definition, idempotency, and validation findings.
- Outcome: implementation validation complete; awaiting Claude implementation review

### Iteration 2

- Trigger: Claude implementation review returned `GREEN_LIGHT: yes` but raised three concrete minor findings worth fixing immediately.
- Claude review: `.codex/artifacts/claude-peer-loop-batch-2-permissions-data-implementation-20260429T211151Z.md`
- Reconciliation: `docs/refactor/execution/batch-2-permissions-data-contracts/claude-reconciliation-1.md`
- Fixes:
  - added `flow_definition_flow_id_invalid`
  - narrowed `flow_runs.user_id` source guard to read-filter patterns
  - removed `flow_router_common.audit_actor_kwargs` pass-through and retargeted callers
- Validation: local fallback GREEN; Docker commands still blocked by host approval policy before execution
- Retrospective: `docs/refactor/execution/batch-2-permissions-data-contracts/retrospective-2.md` (`GREEN`, 0 fails)
- Claude verification:
  - `.codex/artifacts/claude-peer-loop-batch-2-permissions-data-verification-20260429T211830Z.md`
  - `.codex/artifacts/claude-peer-loop-batch-2-permissions-data-verification-format-confirmation-20260429T211923Z.md`
- Reconciliation: `docs/refactor/execution/batch-2-permissions-data-contracts/claude-reconciliation-2.md`
- Result: `GREEN_LIGHT: yes`, `MIN_SCORE: 9`, no accepted or partial findings remain
- Outcome: stop conditions satisfied; ready for commit boundary

## Validation Summary

- Docker validation mode was attempted for the planned pytest and pyright commands, but the host tool policy rejected `docker exec ...` before execution: `approval required by policy, but AskForApproval is set to Never`.
- Local fallback validation passed:
  - `git diff --check` over Batch 2 touched files: pass
  - source guard `rg` for string route access, raw API-key scope state, Flow permission mapping, and service-key decode duplication: only expected canonical hits in `backend/src/intric/flows/principal.py`
  - source/test internal planning vocabulary guard: pass, no hits
  - `cd backend && uv run pyright ...`: pass, `0 errors, 0 warnings`
- `cd backend && uv run pytest ... -q`: pass, `214 passed, 18 warnings` after iteration 2
  - `cd backend && uv run ruff check ...`: pass
  - `cd backend && uv run lint-imports --no-cache`: pass, `3 kept, 0 broken`
- Raw local validation output was captured to ignored local files:
  - `docs/refactor/execution/batch-2-permissions-data-contracts/validation-1.log`
  - `docs/refactor/execution/batch-2-permissions-data-contracts/validation-2.log`

## Claude Review Summary

- Iteration 1 implementation review returned green but identified three concrete minor issues. Codex accepted/fixed them:
  - separated malformed published-definition `flow_id` into `flow_definition_flow_id_invalid`
  - narrowed the `flow_runs.user_id` guard to read-filter patterns
  - removed `flow_router_common.audit_actor_kwargs` pass-through
- Iteration 2 verification returned green with no accepted or partial findings. The first verification artifact used bolded labels that the wrapper could not parse, so Codex ran a same-session format-only confirmation; it returned plain `GREEN_LIGHT: yes` and exit code 0.

## Implementation Summary

- Added `backend/src/intric/flows/flow_access_policy.py` as the typed Flow / Flow AI Builder action policy owner.
- Retargeted Flow route access declarations from string literals to `FlowApiAction`.
- Retargeted AI Builder route authorization to one typed helper that owns tenant permission, API-key space scope, optional list filtering, and creator checks.
- Kept `FlowPrincipal` as the service-key/user identity owner and removed duplicated service-key ownership decoding from Flow route helpers.
- Added `backend/src/intric/flows/published_definition.py` as the versioned published-definition envelope parser/writer/checksum owner.
- Added a dedicated `flow_definition_flow_id_invalid` corruption code for malformed published-definition `flow_id`.
- Retargeted runtime, file upload, run creation, evidence, and publish paths to the published-definition owner.
- Added behavior pins for permission migration, source ownership, published-definition parsing, idempotency row-lifetime replay, and cross-principal idempotency isolation.
- Added `docs/refactor/flow-permission-and-data-contracts.md` documenting the permission matrix, principal identity contract, published JSONB contract, idempotency semantics, JSONB extraction gate, and future runtime table schemas.

## Input Checkpoints

- Batch 0 source/test checkpoint: `d6a9365e477b83651d94566f58a9a7e13d0b9363`
- Post-Batch-0 governance/docs checkpoints:
  - `88cfc4016aa4c5b69506bee5f8b887a1f70a47c1`
  - `8f21fd4f9ca745df8bd0761923350e2f304640ed`
  - `ad472c61bf34b3a5ced13198e141c78c693e5bc0`
- Batch 1 source/test/docs checkpoint: `61c17ed712e245eb25c2f124f334c6c9cbc42413`

## Batch 1 Carry-Forward Risks

- Docker validation could not run in the Batch 1 thread because the host tool policy rejected `docker ps` before execution. Batch 2 should prefer Docker validation but record a local fallback if the same policy blocks it.
- `frontend/packages/intric-js/src/types/schema.d.ts` was manually patched in Batch 1 after full local regeneration produced unrelated churn. Batch 5 owns clean generated-client reconciliation.
- `OffsetPaginatedResponse` is intentionally narrow; consolidate pagination if another API surface adopts `has_more`.
- `_retag_flow_ai_builder_operations` remains in `server/main.py` until AI Builder route/tag composition can own tags without postprocessing.
- Idempotency replay remains tied to retained `flow_runs` rows. Batch 2 must make read-side semantics explicit before any retention/deletion policy.
- Route functions include literal `count` values even though `PaginatedResponse.count` is computed during response serialization. Future pagination consolidation should remove the redundancy or make `count` a normal field.

## Batch 0 Carry-Forward Risks

- Runtime worker contract still executes `FlowRunExecutor` directly instead of the Celery task wrapper. Batch 3 should add an eager Celery/task-wrapper contract.
- Runtime worker contract imports private `_enable_autobegin_for_flow_task_session`; Batch 3 should expose a public helper/fixture during runtime cleanup.

## Initial Findings

- `backend/src/intric/flows/api/flow_api_common.py` accepts `required_access: str` and branches over `"manage"`, `"run"`, and default view. This is the current highest-risk permission source-of-truth gap for Flow route call sites.
- `backend/src/intric/flows/ai_builder/ai_builder_router.py` still reads `request.state.api_key_scope_type`, `api_key_scope_id`, and `scope_enforcement_enabled` directly for AI Builder scope checks.
- `backend/src/intric/flows/principal.py` already owns principal identity for runs, files, and audit actor fields. Batch 2 should reuse it rather than inventing another principal model.
- Published definitions are written by `FlowService` and parsed by runtime helpers from raw `definition_json`. Batch 2 needs a schema-version contract owner, not a new persistence table.
- Existing idempotency semantics are row-lifetime based through `flow_runs.idempotency_key` and `request_fingerprint`; Batch 2 should document/test this without adding TTL migrations.

## Claude Plan Review Reconciliation

Accepted findings from Claude iteration 1:

- The first plan did not prove `flow_access_policy.py` would be the only Flow module mapping `Permission.FLOWS_*` via `has_permission(...)`.
- The first plan did not collapse duplicated service-key ownership decoding across `flow_permissions.py`, `flow_api_common.py`, and `principal.py`.
- AI Builder typed actions were not enumerated, and the plan did not require one action-based helper for the existing endpoint access pattern.
- `scope_enforcement_enabled` needed an explicit no-production-bypass pin, not only a raw-scope-read guard.
- Permission migration mapping needed parametrized behavior coverage, including future action non-grants.
- Published definition ownership needed a clear envelope-vs-step-parser boundary and named corruption error codes.
- Idempotency retention needed explicit "no TTL/sweep exists today" wording and cross-principal isolation coverage.
- `flow_router_common.py` service-key re-exports and AI Builder `_ROUTER_TEST_COMPAT_HELPERS` needed explicit Tier A handling after proof.

Deferred finding:

- `_resolve_litellm_params` is a router test seam, but it is not permission, scope, JSONB, or idempotency behavior. Carry it forward to Batch 6 AI Builder split cleanup.

Claude verification iteration 2 returned `GREEN_LIGHT: yes` in
`.codex/artifacts/claude-peer-loop-batch-2-permissions-data-plan-verification-20260429T202923Z.md`.
The non-blocking polish was applied after verification:

- remove hedged wording around idempotency source naming
- keep the router audit actor helper only as an HTTP adapter delegating to `FlowPrincipal.audit_actor_fields`
- require the permission migration matrix to record whether each AI Builder action has a `flow.edit` precondition
- require the cross-principal idempotency isolation test to use the integration repository/database path so the partial unique indexes are exercised

## Carry-Forward Risks

Items marked YELLOW that move to the next batch:

- `_resolve_litellm_params` remains a router test seam in `ai_builder_router.py`; it is out of Batch 2 scope and should move with the Batch 6 AI Builder split.
- Docker validation remains blocked in this Codex app environment by host approval policy. Local fallback validation is green, but a human or environment with Docker permission should run the documented Docker commands before relying on container-specific parity.
- AI Builder plan approve/apply/revise preserve existing non-creator behavior while declaring typed actions. If creator ownership should apply to those operations, make it an explicit product/security decision before changing behavior.
- Future runtime tables are documented but not implemented; later runtime batches must not add run-local artifact/input/review/rerun/audit tables without confirming the documented constraints or updating the ADR/backlog.

## Decisions Made During This Batch That Might Affect Future Batches

- Existing `FLOWS` remains a legacy alias for shipped view/run/edit/builder/trace behavior, but future review/resume/rerun/audit actions are denied by default until explicitly mapped.
- Flow idempotency has no TTL/expiry semantics today. A missing retained row means the same idempotency key becomes a new create request after normal validation.
- `FlowVersions.definition_json` remains JSONB for published snapshots; `published_definition.py` owns envelope parsing and delegates step-body validation to `runtime.step_definition_parser`.
- `flow_runs.user_id` remains a legacy projection and must not be used as a new read filter.
- Generated-client/package naming remains deferred to Batch 5; no `intric.*` to `eneo.*` namespace migration happened.
