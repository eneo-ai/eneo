# T028 Typed Metadata Worker 2a Scope

## TL;DR

Do not mark the tranche complete.
Do not activate T008 cleanup or T010 AI Builder material efficiency yet.
Activate one narrow typed metadata Worker only after Claude plan-gate review.
Worker 2a should introduce `FlowMetadataV1` and `FlowCareDataPolicyV1` in the existing `flow_metadata.py` owner and route care-data policy reads/writes through that owner.
Worker 2a must not touch `FlowService` create/update/publish write paths, `published_definition.py`, or AI Builder behavior.

## Decision

Proceed with a narrow Worker 2a plan, gated by Claude before implementation.

The next source change should deepen the canonical metadata owner created by T009 without reopening the previously rejected broad metadata-envelope plan. The scope is only:

- define `FlowMetadataV1` in `backend/src/intric/flows/flow_metadata.py`;
- define `FlowCareDataPolicyV1` in the same file;
- parse and serialize `care_data_policy` through the metadata owner;
- remove the local `FlowCareDataPolicy` dataclass from `flow_care_data_policy.py`; `FlowCareDataPolicyV1` becomes the single care-data policy value returned by `resolve_flow_care_data_policy`;
- make `flow_care_data_policy.py` a thin adapter over the typed metadata parser;
- update `flow_evidence_policy.py` only if needed to remove raw `dict[str, Any]` typing from its metadata argument.

## Evidence

| Evidence | Current shape | Worker 2a implication |
|---|---|---|
| `backend/src/intric/flows/flow_metadata.py:40` and `:51` | `FlowFormFieldV1` and `FlowFormSchemaV1` already live in the intended canonical metadata module. | Add the envelope and care-data submodel here instead of a new module. |
| `backend/src/intric/flows/flow_metadata.py:95` | `parse_flow_form_schema(...)` already uses explicit parse modes. | Reuse the mode concept for metadata/care-data reads instead of inventing another tolerance flag. |
| `backend/src/intric/flows/flow_care_data_policy.py:21` | `resolve_flow_care_data_policy` accepts `dict[str, Any] | None`, walks raw metadata, casts raw policy, and tolerates legacy truthy `sensitive`. | Replace the raw walk with `parse_flow_metadata(...).care_data_policy` while preserving fail-closed legacy read behavior. |
| `backend/src/intric/flows/flow_care_data_policy.py:46` | `validate_flow_care_data_policy` repeats raw dict validation and forbids unknown policy fields. | Write-mode care-data parsing should preserve these validation errors and unknown-field rejection. |
| `backend/src/intric/flows/flow_evidence_policy.py:93` | `flow_metadata_marks_sensitive` still takes `dict[str, Any] | None` and delegates to the raw care-data parser. | It can take `JsonObject | Mapping[str, object] | None` and delegate to the typed adapter. |
| `backend/src/intric/flows/application/flow_service.py:400` | FlowService still calls `validate_form_schema` and `validate_flow_care_data_policy` separately. | Do not rewrite FlowService in Worker 2a; preserve the adapter function name so the call site remains stable. |
| `backend/src/intric/flows/published_definition.py:118` | Published definition still casts raw `metadata_json`. | Defer typed published-definition accessor to Worker 2b/2c, not Worker 2a. |
| `backend/tests/unittests/flows/test_flow_care_data_policy.py:4` | Existing care-data tests cover supported fields, absent metadata defaults, legacy truthy sensitive, and unknown enum dropping. | Add write-validation tests and typed metadata tests without weakening existing read tolerance. |
| `backend/tests/unittests/flows/test_flow_service.py:216` | FlowService already has a write-path invalid care-data policy test. | Include this test in verification but avoid changing FlowService source. |

## Per-Mode Extra Policy

Use explicit policies instead of broad permissiveness everywhere:

| Model | Mode | Extra policy | Reason |
|---|---|---|---|
| `FlowMetadataV1` | write | allow/preserve unknown top-level metadata keys | Existing metadata contains non-care-data owners such as `form_schema`, AI Builder provenance, transcription config, and future metadata. Worker 2a must not become a top-level metadata deletion. |
| `FlowMetadataV1` | persisted_read | allow/preserve unknown top-level metadata keys | Runtime reads must remain tolerant and must not lose unrelated metadata. |
| `FlowCareDataPolicyV1` | write | forbid unknown fields | Preserve current `validate_flow_care_data_policy` behavior from `flow_care_data_policy.py:55-61`. |
| `FlowCareDataPolicyV1` | persisted_read | tolerate unknown fields and invalid enum values | Preserve current `resolve_flow_care_data_policy` behavior from `flow_care_data_policy.py:26-43`. |

## Implementation Strategy

`FlowCareDataPolicyV1` is the canonical care-data policy type. The existing `FlowCareDataPolicy` dataclass in `flow_care_data_policy.py:14-19` should be deleted instead of kept as a second representation. Current source callers only consume attributes through `resolve_flow_care_data_policy(...)`, so returning the Pydantic model directly keeps call sites small without two policy owners.

Use manual validation that raises `BadRequestException` with the current message strings, following the `parse_flow_form_schema(...)` pattern in `flow_metadata.py:95-142`. Pydantic should be used as the typed container after manual boundary checks, not as the error producer and not through broad `ValidationError` translation.

`parse_flow_metadata(...)` must preserve unrelated top-level metadata keys in both write and persisted-read modes. Worker 2a must add a round-trip test with `form_schema`, `care_data_policy`, and at least one unrelated metadata key so AI Builder provenance, transcription config, and future metadata cannot be silently dropped.

## Proposed Worker 2a

Objective:

> Introduce `FlowMetadataV1` and `FlowCareDataPolicyV1` in the canonical flow metadata module, then route care-data policy validation and sensitive-export reads through that typed metadata parser while preserving current write errors and persisted-read fail-closed behavior.

Allowed files:

- `backend/src/intric/flows/flow_metadata.py`
- `backend/src/intric/flows/flow_care_data_policy.py`
- `backend/src/intric/flows/flow_evidence_policy.py`
- `backend/tests/unittests/flows/test_flow_metadata.py`
- `backend/tests/unittests/flows/test_flow_care_data_policy.py`

Red tests:

- `FlowMetadataV1` composes the existing `FlowFormSchemaV1` without changing form-schema parse behavior.
- `parse_flow_metadata(..., mode=WRITE)` preserves unrelated top-level metadata keys through serialization.
- `parse_flow_metadata(..., mode=PERSISTED_READ)` preserves unrelated top-level metadata keys through serialization.
- metadata without `care_data_policy` yields a default non-sensitive `FlowCareDataPolicyV1` through `resolve_flow_care_data_policy`.
- Write-mode `care_data_policy` rejects non-object policy values with the current message.
- Write-mode `care_data_policy` rejects unknown fields with the current message.
- Write-mode `sensitive` rejects non-boolean values with the current message.
- Write-mode enum fields reject unsupported values with the current messages.
- Write-mode failures still raise `BadRequestException`, not Pydantic `ValidationError`.
- Persisted-read care-data policy preserves default behavior for absent metadata.
- Persisted-read care-data policy preserves fail-closed truthy legacy `sensitive` values.
- Persisted-read care-data policy drops unsupported enum values.
- `validate_flow_care_data_policy` and `resolve_flow_care_data_policy` no longer cast raw policy dicts directly.

Verification:

```bash
cd backend && uv run pytest \
  tests/unittests/flows/test_flow_metadata.py \
  tests/unittests/flows/test_flow_care_data_policy.py \
  tests/unittests/flows/test_flow_service.py \
  -q

cd backend && uv run pyright \
  src/intric/flows/flow_metadata.py \
  src/intric/flows/flow_care_data_policy.py \
  src/intric/flows/flow_evidence_policy.py \
  src/intric/flows/application/flow_run_service.py \
  tests/unittests/flows/test_flow_metadata.py \
  tests/unittests/flows/test_flow_care_data_policy.py \
  tests/unittests/flows/test_flow_service.py

cd backend && uv run ruff check \
  src/intric/flows/flow_metadata.py \
  src/intric/flows/flow_care_data_policy.py \
  src/intric/flows/flow_evidence_policy.py \
  tests/unittests/flows/test_flow_metadata.py \
  tests/unittests/flows/test_flow_care_data_policy.py \
  tests/unittests/flows/test_flow_service.py

cd backend && uv run ruff format --check \
  src/intric/flows/flow_metadata.py \
  src/intric/flows/flow_care_data_policy.py \
  src/intric/flows/flow_evidence_policy.py \
  tests/unittests/flows/test_flow_metadata.py \
  tests/unittests/flows/test_flow_care_data_policy.py \
  tests/unittests/flows/test_flow_service.py
```

Stop if:

- the implementation needs to touch `application/flow_service.py`, `published_definition.py`, or `ai_builder/*`;
- `FlowMetadataV1` becomes a shallow envelope used by only one read path without a named closer;
- the implementation adds `# type: ignore` or broad `Any` to bypass Pyright instead of fixing the parser boundary;
- source comments or docstrings mention `T028`, `Worker 2a`, `tranche`, or other internal planning vocabulary;
- write-mode care-data errors change without explicit test updates and API/error-contract review;
- persisted-read mode stops failing closed for legacy truthy `sensitive`;
- top-level metadata unknown keys are dropped.

## Deferred Work

- Worker 2b: move `FlowService` create/update/publish normalization and serialization through `FlowMetadataV1`. Trigger this as the next Worker after 2a's commit gate clears unless a fresh P0 runtime/API regression appears.
- Worker 2c: add a typed published-definition metadata accessor and retire raw `metadata_json` casts there.
- Worker 3: retire AI Builder raw form-schema readers and decide whether to delete or wire `FlowMetadataPatch`.
- Future evidence/settings cleanup: `flow_evidence_policy.apply_flow_evidence_policy_patch` remains out of Worker 2a but should be considered when the metadata envelope starts owning flow-level policy/settings writes.
