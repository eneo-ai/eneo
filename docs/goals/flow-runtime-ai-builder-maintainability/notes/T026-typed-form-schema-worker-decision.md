# T026 Typed Form Schema Worker Decision

## TL;DR

Claude did not green-light the T025 Worker 1 plan because it mixed a form-schema slice with a half-claimed full metadata envelope.
Codex accepts that critique.
The next Worker should introduce `FlowFormSchemaV1` and `FlowFormFieldV1` first, not a full `FlowMetadataV1` envelope.
The full metadata envelope remains the Worker 2 target when `care_data_policy`, published snapshots, and FlowService write paths can move together.
Before activation, this revised plan goes back to the same Claude session for green light.

## Claude Iteration 1 Result

Artifact: `.codex/artifacts/claude-peer-loop-t026-typed-metadata-worker-plan-20260511T022334Z.md`

Result:

- `VERDICT: changes_required`
- `GREEN_LIGHT: no`
- `MIN_SCORE: 6`

Accepted findings:

- Worker 1 should not half-introduce `FlowMetadataV1` while `care_data_policy` remains a sibling raw metadata reader.
- Error semantics for `validate_form_schema` must be enumerated before replacing dict validation.
- Read-tolerant versus write-strict parsing must be explicit.
- OpenAPI and public consumer API contract tests should be in the verification list because run-contract form fields are a public API surface.
- `FlowMetadataPatch` is not production-wired today and should be resolved explicitly in the later AI Builder closer.

Rejected findings:

- None. The critique matched source evidence and improves reviewability.

## Revised Worker 1 Scope

Worker 1 is now a typed **form schema** boundary slice, not a full metadata-envelope slice.

Canonical owner:

- `backend/src/intric/flows/flow_metadata.py`

Public surface for Worker 1:

- `FlowFormSchemaV1`
- `FlowFormFieldV1`
- `parse_flow_form_schema(metadata_json: JsonObject | Mapping[str, object] | None, *, mode: FlowFormSchemaParseMode) -> FlowFormSchemaV1 | None`
- `serialize_flow_form_schema(schema: FlowFormSchemaV1) -> JsonObject`

Explicitly deferred to Worker 2:

- `FlowMetadataV1`
- `care_data_policy` typed ownership
- published-definition typed metadata accessor
- FlowService create/update/publish metadata serialization

Rationale:

- This kills duplicate form-schema normalization and parsing without creating a partial metadata envelope.
- `care_data_policy` can move with the full metadata envelope later instead of forcing Worker 1 to touch more lifecycle and data-policy files.
- A future `FlowMetadataV1.form_schema` can embed the same `FlowFormSchemaV1`, so Worker 1 still deepens the eventual canonical owner instead of creating throwaway code.

## Parser Policy

Worker 1 must use explicit parser modes:

| Mode | Intended caller | Behavior |
|---|---|---|
| `write` | save/update validation through `validate_form_schema` | strict; preserves current write validation errors unless explicitly changed in the error table |
| `persisted_read` | run payload and run contract reading existing published/draft metadata | tolerant of absent or structurally unusable `form_schema`; caller preserves existing behavior for public error code translation |

Public run-contract behavior remains:

- `_published_form_fields` continues to translate invalid published field payloads to `flow_published_form_schema_invalid`.
- Worker 1 may parse through `FlowFormSchemaV1`, but it must not leak a lower-level parser error directly to the run-contract API path.

The invariant after Worker 1:

- `flow_run_input_payload.py` and `flow_run_contract_service.py` no longer maintain their own raw form-schema dict walks or legacy type maps.
- Other metadata readers may still read raw `metadata_json` until Worker 2 and Worker 3, but the Worker receipt must name the remaining raw readers.

## Error Contract Preservation Table

Worker 1 must preserve or intentionally document every current `validate_form_schema` error.

| Current case | Current code | Current context keys | Required Worker 1 behavior |
|---|---|---|---|
| `metadata_json.form_schema` is not an object | none | none | Preserve message substring unless adding a stable code is explicitly covered by API tests and documentation. |
| `metadata_json.form_schema.fields` is not a list | none | none | Preserve message substring unless adding a stable code is explicitly covered by API tests and documentation. |
| field item is not an object | none | none | Preserve message substring. |
| field name missing or blank | `flow_form_field_name_empty` | `field_index` | Preserve code and context shape. |
| duplicate field name | `flow_form_field_name_duplicate` | `field_index`, `field_name` | Preserve code and context shape. |
| field name contains `.` | `flow_form_field_name_dot` | `field_index`, `field_name` | Preserve code and context shape. |
| field name contains template delimiters | `flow_form_field_name_template_delimiters` | `field_index`, `field_name` | Preserve code and context shape. |
| field name is `flow_input` namespace head | `flow_form_field_name_namespace_head` | `field_index`, `field_name` | Preserve code and context shape. |
| field name is primary input key | `flow_form_field_name_primary_input_key` | `field_index`, `field_name` | Preserve code and context shape. |
| field name is step alias | `flow_form_field_name_step_alias` | `field_index`, `field_name` | Preserve code and context shape. |
| field type missing or blank | none | none | Preserve message substring. |
| field type not allowed | none | none | Preserve message substring after canonical legacy alias normalization. |
| `required` is present and not boolean | none | none | Preserve message substring. |
| `order` is present and not integer | none | none | Preserve message substring. |
| `order < 1` | none | none | Preserve message substring. |
| duplicate `order` | none | none | Preserve message substring. |
| multiselect options missing or not list | none | none | Preserve message substring. |
| option is missing, blank, or non-string | none | none | Preserve message substring. |
| duplicate option | none | none | Preserve message substring. |
| select options present but not list | none | none | Preserve message substring. |
| non-select/multiselect options present | none | none | Preserve message substring. |

Worker 1 should not opportunistically redesign all no-code `BadRequestException` cases. Stable codes for no-code cases are desirable, but they belong in a dedicated public API error-contract slice unless Worker 1 adds HTTP/OpenAPI tests for every changed error body.

## FlowMetadataPatch Disposition

`FlowMetadataPatch` is production-unwired today:

- source hits: `backend/src/intric/flows/ai_builder/ai_builder_edit_models.py:117`, `:156`
- test hits: `backend/tests/unittests/flows/ai_builder/test_ai_builder_edit_models.py`

Decision:

- Do not touch `FlowMetadataPatch` in Worker 1.
- Worker 3 must choose one of two explicit outcomes: delete `FlowMetadataPatch` and its tests if it is LLM-emitted dead weight, or wire it through a typed apply path that composes with the future `FlowMetadataV1`.
- No AI Builder-only metadata patch semantics may be invented in Worker 1.

## Allowed Files For Worker 1

Source:

- `backend/src/intric/flows/flow_metadata.py`
- `backend/src/intric/flows/flow_validators_form.py`
- `backend/src/intric/flows/flow_run_input_payload.py`
- `backend/src/intric/flows/flow_run_contract_service.py`

Tests:

- `backend/tests/unittests/flows/test_flow_metadata.py`
- `backend/tests/unittests/flows/test_flow_run_input_payload.py`
- `backend/tests/unittests/flows/test_flow_validators.py`
- `backend/tests/unittests/flows/test_flow_run_contract_service.py`
- `backend/tests/unit/test_flow_openapi_contract.py`
- `backend/tests/integration/flows/test_flow_consumer_api_contract.py`

Split rule:

- If `flow_run_contract_service.py` migration grows beyond replacing `_published_form_fields` form-schema parsing, split into a follow-up Worker.
- If a fix requires `flow_care_data_policy.py`, `flow_service.py`, `published_definition.py`, or AI Builder files, stop and return to Judge.

## Red Tests For Worker 1

- `FlowFormSchemaV1` rejects non-object form schema and non-list fields with current write-path error semantics.
- `FlowFormSchemaV1` normalizes legacy aliases `"string"`, `"email"`, and `"textarea"` to `"text"` in one place.
- A persisted/read-mode schema using `"email"` or `"textarea"` still yields the same runtime payload behavior after deleting the run-payload legacy normalization map.
- Run input payload validation no longer owns `_RUN_FIELD_TYPE_LEGACY_NORMALIZATION`.
- Run contract form fields still sort by typed field order.
- Invalid published field payloads still surface `flow_published_form_schema_invalid`.
- Internal `FlowFormFieldV1` to public `FormFieldPublic` mapping is lossless for fields used by the run-contract endpoint.
- OpenAPI and consumer API contract tests still document the run-contract form-field shape.

## Validation Commands For Worker 1

```bash
cd backend && uv run pytest \
  tests/unittests/flows/test_flow_metadata.py \
  tests/unittests/flows/test_flow_run_input_payload.py \
  tests/unittests/flows/test_flow_validators.py \
  tests/unittests/flows/test_flow_run_contract_service.py \
  tests/unit/test_flow_openapi_contract.py \
  tests/integration/flows/test_flow_consumer_api_contract.py \
  -q

cd backend && uv run pyright \
  src/intric/flows/flow_metadata.py \
  src/intric/flows/flow_validators_form.py \
  src/intric/flows/flow_run_input_payload.py \
  src/intric/flows/flow_run_contract_service.py \
  tests/unittests/flows/test_flow_metadata.py \
  tests/unittests/flows/test_flow_run_input_payload.py \
  tests/unittests/flows/test_flow_validators.py \
  tests/unittests/flows/test_flow_run_contract_service.py \
  tests/unit/test_flow_openapi_contract.py \
  tests/integration/flows/test_flow_consumer_api_contract.py

cd backend && uv run ruff check \
  src/intric/flows/flow_metadata.py \
  src/intric/flows/flow_validators_form.py \
  src/intric/flows/flow_run_input_payload.py \
  src/intric/flows/flow_run_contract_service.py \
  tests/unittests/flows/test_flow_metadata.py \
  tests/unittests/flows/test_flow_run_input_payload.py \
  tests/unittests/flows/test_flow_validators.py \
  tests/unittests/flows/test_flow_run_contract_service.py \
  tests/unit/test_flow_openapi_contract.py \
  tests/integration/flows/test_flow_consumer_api_contract.py

cd backend && uv run ruff format --check \
  src/intric/flows/flow_metadata.py \
  src/intric/flows/flow_validators_form.py \
  src/intric/flows/flow_run_input_payload.py \
  src/intric/flows/flow_run_contract_service.py \
  tests/unittests/flows/test_flow_metadata.py \
  tests/unittests/flows/test_flow_run_input_payload.py \
  tests/unittests/flows/test_flow_validators.py \
  tests/unittests/flows/test_flow_run_contract_service.py \
  tests/unit/test_flow_openapi_contract.py \
  tests/integration/flows/test_flow_consumer_api_contract.py
```

## Stop Conditions For Worker 1

- The implementation needs to touch care-data, published-definition, FlowService write paths, or AI Builder behavior.
- The implementation adds `Any`, `cast`, or `# type: ignore` outside the parser boundary without an explicit boundary reason.
- The public run-contract endpoint leaks typed parser errors instead of preserving `flow_published_form_schema_invalid`.
- The new module contains tutorial comments or comments longer than two lines that do not document a real invariant.
- `FlowFormFieldV1.options` uses a mutable default instead of `list[str] | None`.
- The Worker cannot remove the duplicate run-payload legacy normalization map.

## Worker 1 Receipt Requirements

- Before/after counts for `Any`, `cast`, and `# type: ignore` in changed files.
- Before/after count of raw `metadata_json` and `form_schema` readers in changed files.
- Error contract table showing preserved and intentionally changed errors.
- Every added or changed comment pasted verbatim.
- List of remaining raw metadata readers after the slice.
- Answer: what exact file/function became easier to understand and why?
- Claude commit gate with at least 15 minutes, preferably 20 minutes, before committing source changes.
