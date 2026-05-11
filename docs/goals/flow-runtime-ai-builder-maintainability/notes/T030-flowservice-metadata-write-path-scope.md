# T030 FlowService Metadata Write-Path Scope

## TL;DR

Worker 2b should move FlowService create/update/publish metadata normalization through `FlowMetadataV1`.
The current WRITE serializer already preserves `care_data_policy: {}` and explicit `{"sensitive": false}`; Worker 2b should verify that before editing serializer behavior.
Keep `published_definition.py` and AI Builder out of this Worker.
Delete the old `normalize_legacy_form_schema` wrapper instead of keeping a compatibility shim once FlowService uses metadata-level normalization.
Run a Claude plan gate before activation because this touches write-path persistence semantics.

## Decision

Proceed to a Claude-gated Worker 2b plan, not direct implementation.

The next implementation should deepen the metadata owner without broadening into snapshot parsing or AI Builder cleanup:

- verify `serialize_flow_metadata(...)` current write-mode care-data default behavior before editing it;
- route FlowService user-provided create/update metadata normalization through `parse_flow_metadata(..., mode=WRITE)` and `serialize_flow_metadata(...)`;
- route existing persisted metadata normalization through `parse_flow_metadata(..., mode=PERSISTED_READ)` when `update_flow` receives no replacement metadata and when `publish_flow` normalizes an already-stored draft;
- preserve current write-validation error strings and codes;
- preserve unknown top-level metadata keys;
- preserve legacy form-schema alias normalization;
- preserve care-data policy validation;
- avoid touching `published_definition.py`, `ai_builder/*`, routers, generated clients, or migrations.

## Evidence

| Evidence | Current shape | Worker 2b implication |
|---|---|---|
| `backend/src/intric/flows/application/flow_service.py:92`, `:183`, `:332` | Create/update/publish call `_normalize_legacy_form_schema(...)` before validation and persistence. | Replace the form-only normalization path with a metadata-level normalization path. |
| `backend/src/intric/flows/application/flow_service.py:400-407` | `_validate_form_schema` validates both form schema and care-data policy; `_normalize_legacy_form_schema` delegates to the form-specific compatibility function. | Keep validation call shape stable, but normalize through the canonical metadata owner before validation. |
| `backend/src/intric/flows/flow_validators_form.py:23-37` | `normalize_legacy_form_schema` parses only `form_schema` with persisted-read tolerance and serializes only that key. | This function is now the wrong long-term name/owner for metadata-level persistence normalization. Worker 2b should either replace it with `normalize_flow_metadata_for_write` in a better owner or make it a compatibility wrapper over the metadata parser with a named deletion path. |
| `backend/src/intric/flows/flow_metadata.py:174-200` | `parse_flow_metadata` and `serialize_flow_metadata` exist but serializer is not production-wired. | Fix serializer semantics now, then use it from FlowService normalization. |
| `backend/src/intric/flows/flow_metadata.py:264-291` | Claude flagged that write-mode and persisted-read mode can serialize default `sensitive` differently. | Before using the serializer in writes, choose the preservation policy and test it. |
| `backend/tests/unittests/flows/test_flow_service.py:2040-2115` | FlowService tests already protect invalid form field type/options after the T029 verification. | Include these tests so metadata-level normalization does not re-mask invalid write payloads. |
| `backend/tests/unittests/flows/test_flow_service.py:216-235` | FlowService write path rejects invalid care-data policy. | Keep this as a transitive write-path proof. |

## Mode Policy

Use two explicit normalization entry points:

| FlowService path | Mode | Reason |
|---|---|---|
| `create_flow(..., metadata_json=...)` | `WRITE` | User-provided metadata should fail loudly and serialize through the canonical write contract. |
| `update_flow(..., metadata_json=<provided>)` | `WRITE` | User-provided replacement metadata should fail loudly and serialize through the canonical write contract. |
| `update_flow(..., metadata_json=NOT_PROVIDED)` | `PERSISTED_READ` | Existing stored draft metadata is not being edited; preserve the current tolerant cleanup behavior for previously persisted flags such as `required: "yes"`. |
| `publish_flow(...)` | `PERSISTED_READ` for the stored draft metadata | Publishing an already-stored draft should preserve the current tolerant cleanup behavior while producing a deterministic snapshot. |

This means FlowService no longer runs a separate care-data WRITE parse after metadata normalization. User-provided write paths fail during `normalize_flow_metadata_for_write`. Existing persisted paths normalize tolerantly and then proceed with the normalized shape.

## Sensitive Default Serialization Policy

Choose preservation over adding defaults:

- If incoming metadata has no `care_data_policy`, serialization must not add one.
- If incoming metadata has `care_data_policy: {}`, serialization should preserve `{}` rather than add `{"sensitive": false}`.
- If incoming metadata has `care_data_policy: {"sensitive": false}`, serialization should preserve `{"sensitive": false}`.
- If persisted-read sees a legacy truthy value such as `{"sensitive": "yes"}`, it should still fail closed to `{"sensitive": true}` when serialized.

Local check before this note revision:

```text
write {"care_data_policy": {}} -> {"care_data_policy": {}}
write {"care_data_policy": {"sensitive": false}} -> {"care_data_policy": {"sensitive": false}}
write {"care_data_policy": {"sensitive": "yes"}} -> BadRequestException
persisted_read {"care_data_policy": {}} -> {"care_data_policy": {"sensitive": false}}
persisted_read {"care_data_policy": {"sensitive": "yes"}} -> {"care_data_policy": {"sensitive": true}}
```

So Worker 2b should add tests for the chosen policy first. It should not edit serializer behavior unless those tests prove the current implementation violates the policy.

## Normalization Owner Decision

Move normalization entry points to `flow_metadata.py`:

- `normalize_flow_metadata_for_write(metadata_json: JsonObject | None) -> JsonObject | None`
- `normalize_persisted_flow_metadata(metadata_json: JsonObject | None) -> JsonObject | None`

Delete `normalize_legacy_form_schema` from `flow_validators_form.py` and remove its re-export from `flow_validators.py` if FlowService/tests are the only remaining callers. Do not keep a wrapper only for old naming compatibility.

After this change, FlowService should not call `validate_flow_care_data_policy(...)` at the same boundary after metadata normalization. If the Worker keeps the second parse, the receipt must justify the duplicate validation as an intentional boundary defense; otherwise this is a stop condition.

## Proposed Worker 2b

Objective:

> Move FlowService create/update/publish metadata normalization through `FlowMetadataV1` and `serialize_flow_metadata`, using WRITE mode for user-provided metadata and PERSISTED_READ mode for already-stored draft metadata, without touching published-definition parsing or AI Builder behavior.

Allowed files:

- `backend/src/intric/flows/flow_metadata.py`
- `backend/src/intric/flows/flow_validators_form.py`
- `backend/src/intric/flows/flow_validators.py`
- `backend/src/intric/flows/application/flow_service.py`
- `backend/tests/unittests/flows/test_flow_metadata.py`
- `backend/tests/unittests/flows/test_flow_validators.py`
- `backend/tests/unittests/flows/test_flow_service.py`

Red tests:

- `normalize_flow_metadata_for_write({"care_data_policy": {}})` preserves `{"care_data_policy": {}}`.
- `normalize_flow_metadata_for_write({"care_data_policy": {"sensitive": False}})` preserves explicit false.
- `serialize_flow_metadata(parse_flow_metadata({"care_data_policy": {"sensitive": "yes"}}, mode=PERSISTED_READ))` returns `{"care_data_policy": {"sensitive": True}}`.
- FlowService create/update with user-provided metadata persist metadata normalized by `serialize_flow_metadata`, including form-schema legacy type aliases and unrelated top-level keys.
- `update_flow(..., metadata_json=NOT_PROVIDED)` with existing metadata containing a tolerated persisted field flag such as `required: "yes"` still succeeds and persists the normalized shape.
- `publish_flow(...)` produces `definition_json["metadata_json"]` equal to the new normalized shape, preserves unrelated top-level keys, and produces deterministic checksums for identical input.
- FlowService create/update/publish still reject invalid form options and invalid care-data policy with current messages.
- `normalize_legacy_form_schema` is deleted or renamed; no compatibility wrapper remains.
- FlowService performs one metadata WRITE parse for user-provided metadata normalization; it does not silently double-parse care-data policy at the same boundary.

Verification:

```bash
cd backend && uv run pytest \
  tests/unittests/flows/test_flow_metadata.py \
  tests/unittests/flows/test_flow_validators.py \
  tests/unittests/flows/test_flow_service.py \
  -q

cd backend && uv run pyright \
  src/intric/flows/flow_metadata.py \
  src/intric/flows/flow_validators_form.py \
  src/intric/flows/flow_validators.py \
  src/intric/flows/application/flow_service.py \
  tests/unittests/flows/test_flow_metadata.py \
  tests/unittests/flows/test_flow_validators.py \
  tests/unittests/flows/test_flow_service.py

cd backend && uv run ruff check \
  src/intric/flows/flow_metadata.py \
  src/intric/flows/flow_validators_form.py \
  src/intric/flows/flow_validators.py \
  src/intric/flows/application/flow_service.py \
  tests/unittests/flows/test_flow_metadata.py \
  tests/unittests/flows/test_flow_validators.py \
  tests/unittests/flows/test_flow_service.py

cd backend && uv run ruff format --check \
  src/intric/flows/flow_metadata.py \
  src/intric/flows/flow_validators_form.py \
  src/intric/flows/flow_validators.py \
  src/intric/flows/application/flow_service.py \
  tests/unittests/flows/test_flow_metadata.py \
  tests/unittests/flows/test_flow_validators.py \
  tests/unittests/flows/test_flow_service.py
```

Stop if:

- the implementation needs `published_definition.py`, `ai_builder/*`, routers, generated clients, migrations, or frontend files;
- the implementation changes public API request/response shape;
- the implementation changes current BadRequestException messages without explicit test updates and review;
- serializer changes drop unrelated top-level metadata keys;
- `normalize_legacy_form_schema` remains as a compatibility wrapper after FlowService moves to metadata-level normalization;
- FlowService silently double-parses care-data WRITE validation at the same boundary with no receipt rationale;
- `update_flow(..., metadata_json=NOT_PROVIDED)` changes tolerant existing-metadata behavior without an explicit test and receipt decision;
- `publish_flow` snapshot metadata shape/checksum changes without a dedicated test;
- new `Any`, `# type: ignore`, or Pyright ignore comments are added to get green checks.

## Deferred Work

- Worker 2c: add a typed published-definition metadata accessor and retire raw `metadata_json` casts in `published_definition.py`.
- Worker 3: retire AI Builder raw form-schema readers and decide whether to delete or wire `FlowMetadataPatch`.
