# T034 Published Definition Metadata Accessor Scope

## TL;DR

Add a typed published-definition metadata accessor before AI Builder cleanup.
The next Worker should make `PublishedFlowDefinition` expose `FlowMetadataV1` through a lazy `metadata()` method parsed from `definition_json["metadata_json"]`.
Move the two live runtime/contract consumers off `published_definition.metadata_json`.
Keep AI Builder and published snapshot writing out of this Worker.
Run a host Claude plan gate because this touches published runtime/read contracts.

## Decision

Proceed to a Claude-gated Worker that adds typed metadata access on `PublishedFlowDefinition`.

The target is not a new `PublishedFlowDefinitionV1` shell. The existing `PublishedFlowDefinition` dataclass should remain the outer snapshot owner. The inner `metadata_json` should be parsed through the canonical `FlowMetadataV1` owner from `flow_metadata.py`.

Decisions after Claude iteration 1:

- Remove `metadata_json` from the `PublishedFlowDefinition` dataclass. `definition_json` remains the authoritative envelope.
- Add `PublishedFlowDefinition.metadata() -> FlowMetadataV1` as a lazy accessor that parses `definition_json["metadata_json"]` with `parse_flow_metadata(..., mode=PERSISTED_READ)`.
- Keep `flow_published_form_schema_invalid` owned by `flow_run_contract_service._published_form_fields`; `published_definition.py` must not raise public API error codes for metadata shape.
- Do not include `flow_run_input_payload.py` in this Worker. Rerun can serialize the typed published metadata back to JSON for the existing input-payload function in this slice, and a later follow-up can tighten that function's signature to accept `FlowMetadataV1`.

## Evidence

| Evidence | Current shape | Worker implication |
|---|---|---|
| `backend/src/intric/flows/published_definition.py:30-38` | `PublishedFlowDefinition` stores raw `metadata_json: JsonObject | None`. | Remove the raw field and add a lazy `metadata()` accessor. |
| `backend/src/intric/flows/published_definition.py:118-126` | Parser casts `metadata_json` to `JsonObject`. | Delete this cast; metadata parsing belongs in `metadata()` and delegates to `flow_metadata.py`. |
| `backend/src/intric/flows/flow_run_contract_service.py:83-91` | Run contract parses the published definition, then passes `published_definition.metadata_json` into `_published_form_fields`. | Change `_published_form_fields` to consume `FlowMetadataV1` or `FlowFormSchemaV1`, not raw JSON. |
| `backend/src/intric/flows/flow_run_contract_service.py:244-267` | `_published_form_fields` parses raw metadata and maps form fields to public contract fields. | Remove the raw metadata parse from this service; preserve `flow_published_form_schema_invalid` for invalid published field payloads. |
| `backend/src/intric/flows/application/flow_run_service.py:620-732` | Rerun parses the published definition, then passes `published_definition.metadata_json` to run-payload normalization. | Move this caller to a typed published metadata method/serializer so it no longer reads raw snapshot metadata directly. |
| `backend/src/intric/flows/api/flow_run_steps_router.py:234` and `backend/src/intric/flows/application/flow_run_service.py:1394` | Other published-definition callers use steps only. | No metadata changes needed there. |
| `backend/tests/unittests/flows/test_published_definition_contract.py:38-56` | Writer test asserts envelope and ordered steps, not typed metadata parsing. | Add metadata parser/accessor tests here. |
| `backend/tests/unittests/flows/test_flow_run_contract_service.py:253-289` | Invalid published form schema currently maps to `flow_published_form_schema_invalid`. | Preserve this public error code after moving the parser boundary. |

## Proposed Worker T035

Objective:

> Add typed `FlowMetadataV1` access to `PublishedFlowDefinition` and update published runtime/contract readers to consume that typed metadata instead of `published_definition.metadata_json`, while preserving published run-contract error behavior.

Preferred shape:

- `PublishedFlowDefinition` removes the `metadata_json` field.
- `PublishedFlowDefinition.metadata()` lazily parses `definition_json["metadata_json"]` through `parse_flow_metadata(..., mode=PERSISTED_READ)`.
- `_published_form_fields(...)` consumes `FlowMetadataV1` or `FlowFormSchemaV1` and keeps translating invalid published form schemas to `flow_published_form_schema_invalid`.
- rerun inline payload normalization receives `serialize_flow_metadata(published_definition.metadata())` for now. The typed `flow_run_input_payload.py` signature is a named follow-up, not part of this Worker.

Allowed files:

- `backend/src/intric/flows/published_definition.py`
- `backend/src/intric/flows/flow_run_contract_service.py`
- `backend/src/intric/flows/application/flow_run_service.py`
- `backend/tests/unittests/flows/test_published_definition_contract.py`
- `backend/tests/unittests/flows/test_flow_run_contract_service.py`
- `backend/tests/unittests/flows/test_flow_run_service.py`

Red tests:

- `parse_published_definition(...)` exposes typed metadata that normalizes legacy published form field aliases and preserves unrelated top-level metadata keys.
- `PublishedFlowDefinition` no longer has a `metadata_json` dataclass field.
- invalid published `metadata_json.form_schema.fields` still raises through run-contract as `flow_published_form_schema_invalid`.
- run-contract form-field mapping consumes the typed published metadata and still sorts by field order.
- rerun inline payload normalization uses typed published metadata, preserving required form-field validation behavior.
- rerun with a published required form field and omitted payload raises the existing missing-required-field error through the rerun path.
- after implementation, `git grep -n "published_definition.metadata_json" -- backend/src backend/tests` returns no live runtime/contract consumers.
- after implementation, `git grep -n "cast(JsonObject, metadata_json)" -- backend/src/intric/flows/published_definition.py` returns no hits.

Verification:

```bash
cd backend && uv run pytest \
  tests/unittests/flows/test_published_definition_contract.py \
  tests/unittests/flows/test_flow_run_contract_service.py \
  tests/unittests/flows/test_flow_run_service.py \
  -q

cd backend && uv run pyright \
  src/intric/flows/published_definition.py \
  src/intric/flows/flow_run_contract_service.py \
  src/intric/flows/application/flow_run_service.py \
  tests/unittests/flows/test_published_definition_contract.py \
  tests/unittests/flows/test_flow_run_contract_service.py \
  tests/unittests/flows/test_flow_run_service.py

cd backend && uv run ruff check \
  src/intric/flows/published_definition.py \
  src/intric/flows/flow_run_contract_service.py \
  src/intric/flows/application/flow_run_service.py \
  tests/unittests/flows/test_published_definition_contract.py \
  tests/unittests/flows/test_flow_run_contract_service.py \
  tests/unittests/flows/test_flow_run_service.py

cd backend && uv run ruff format --check \
  src/intric/flows/published_definition.py \
  src/intric/flows/flow_run_contract_service.py \
  src/intric/flows/application/flow_run_service.py \
  tests/unittests/flows/test_published_definition_contract.py \
  tests/unittests/flows/test_flow_run_contract_service.py \
  tests/unittests/flows/test_flow_run_service.py
```

Stop if:

- the implementation needs AI Builder files, routers, generated clients, migrations, frontend files, or unrelated dirty files;
- the implementation creates a parallel `PublishedFlowDefinitionV1` outer snapshot model;
- public run-contract error code `flow_published_form_schema_invalid` changes unintentionally;
- rerun payload validation behavior changes without a dedicated test;
- `published_definition.py` starts owning metadata schema rules instead of delegating to `flow_metadata.py`;
- `PublishedFlowDefinition` keeps both `metadata_json` and typed metadata as dataclass storage fields;
- `flow_run_input_payload.py` is touched instead of deferring the typed input-payload signature cleanup;
- new `Any`, `# type: ignore`, or Pyright ignore comments are added to get green checks.

## Deferred Work

- Tighten `normalize_and_validate_flow_run_payload(...)` in `flow_run_input_payload.py` to accept `FlowMetadataV1 | None` instead of reparsing serialized metadata dicts.
- Decide whether draft create-run payload normalization should also parse `flow.metadata_json` through `FlowMetadataV1` before calling the input-payload helper.

## Claude Gate

Run a host Claude plan gate before activation. This touches runtime contract readers and published snapshot parsing, so the ownership/test boundary should be peer-reviewed before source edits.
