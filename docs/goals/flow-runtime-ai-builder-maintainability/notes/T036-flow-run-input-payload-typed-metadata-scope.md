# T036 Flow Run Input Payload Typed Metadata Scope

## TL;DR

The next safe task is to remove the raw `metadata_json` boundary from flow run input-payload normalization.
`normalize_and_validate_flow_run_payload(...)` should accept `FlowMetadataV1 | None` and use `metadata.form_schema` directly.
`FlowRunService` should become the caller-owned parse boundary for create-run and rerun.
Published metadata error translation should move to one canonical published-definition accessor used by both run-contract and rerun.
The Worker must preserve create-run draft-metadata behavior deliberately and name that draft/published divergence as deferred debt.
Run a host Claude plan gate before activation because this changes a shared validation signature and public error behavior.

## Decision

Queue a Claude-gated Worker that tightens `flow_run_input_payload.py` from raw metadata JSON to typed `FlowMetadataV1`.

This is the direct follow-up to T035: rerun currently calls `published_definition.metadata()`, serializes that typed model back to JSON, then `flow_run_input_payload.py` reparses it. That is a shallow typed boundary and keeps broad `dict[str, Any]` in the shared run-payload validator.

Claude iteration 1 rejected the first scope because it would duplicate `flow_published_form_schema_invalid` translation in rerun and run-contract, and because it did not pin the create-run draft-metadata leniency policy. The revised Worker must close both plan gaps before activation.

## Evidence

| Evidence | Current shape | Worker implication |
|---|---|---|
| `backend/src/intric/flows/flow_run_input_payload.py:26-36` | `normalize_and_validate_flow_run_payload(...)` accepts `metadata_json: dict[str, Any] | None`, parses form schema internally, and swallows `BadRequestException`. | Replace the raw JSON parameter with `metadata: FlowMetadataV1 | None`; no parser or broad catch belongs inside the payload coercion helper. |
| `backend/src/intric/flows/application/flow_run_service.py:452-457` | create-run passes mutable draft `flow.metadata_json` directly into the helper. | FlowRunService must parse draft metadata before calling the helper and explicitly decide whether to preserve the current invalid-draft passthrough behavior. |
| `backend/src/intric/flows/application/flow_run_service.py:732-734` | rerun serializes `published_definition.metadata()` back to JSON for the helper. | Pass the typed published metadata directly and remove the serialize/reparse wash. |
| `backend/src/intric/flows/flow_run_contract_service.py:244-253` | run-contract translates malformed published metadata to `flow_published_form_schema_invalid` locally. | Move this translation to a single published-definition accessor so rerun and run-contract do not duplicate one public error rule. |
| `backend/tests/unittests/flows/test_flow_run_input_payload.py:26-36` | tests encode malformed raw metadata passthrough inside the helper. | Move raw-metadata passthrough coverage to the service caller if behavior should remain; helper tests should construct/parse typed metadata. |
| `backend/tests/unittests/flows/test_flow_run_service.py:1839-1880` | rerun malformed published metadata currently fails loud with an uncoded `BadRequestException`. | Decide and test the desired public error code; leading candidate is `flow_published_form_schema_invalid` for published form-schema corruption. |
| `backend/tests/unittests/flows/test_flow_run_contract_service.py:253-289` | run-contract already translates invalid published form schema to `flow_published_form_schema_invalid`. | Align rerun with the published run-contract error if the Worker touches the parse boundary. |

## Proposed Worker T037

Objective:

> Change flow run input-payload normalization to consume `FlowMetadataV1 | None` instead of raw metadata JSON, remove the rerun serialize/reparse path, and make malformed published metadata errors explicit and tested without changing unrelated run behavior.

Preferred shape:

- `normalize_and_validate_flow_run_payload(...)` accepts `metadata: FlowMetadataV1 | None`.
- The helper reads `metadata.form_schema` directly and no longer imports `parse_flow_form_schema`, `FlowFormSchemaParseMode`, or catches metadata parse errors.
- `PublishedFlowDefinition.metadata()` is modified in place to catch metadata parse `BadRequestException` and re-raise with `code="flow_published_form_schema_invalid"`; do not add a parallel metadata accessor.
- `flow_run_contract_service._published_form_fields(...)` and `FlowRunService._normalize_rerun_inline_payload(...)` both use the same published-definition error accessor instead of carrying duplicate try/except translation.
- `FlowRunService.create_run(...)` parses draft `flow.metadata_json` at the service boundary through a clearly named private helper with this exact policy: `JsonObject | None -> FlowMetadataV1 | None`; swallow `BadRequestException` from draft metadata parsing and return `None` to preserve current create-run passthrough behavior for malformed draft metadata.
- Drop the redundant `isinstance(flow.metadata_json, dict)` guard while wiring the new draft helper; `flow.metadata_json` is already `JsonObject | None`.
- `flow_run_input_payload.py` remains focused on payload value coercion and required-field validation, not metadata schema parsing.
- Create-run continues to validate inline payload against draft metadata, while rerun validates against the published definition. That divergence is intentional in this Worker and should be recorded as a follow-up, not silently normalized.

Allowed files:

- `backend/src/intric/flows/published_definition.py`
- `backend/src/intric/flows/flow_run_contract_service.py`
- `backend/src/intric/flows/flow_run_input_payload.py`
- `backend/src/intric/flows/application/flow_run_service.py`
- `backend/tests/unittests/flows/test_published_definition_contract.py`
- `backend/tests/unittests/flows/test_flow_run_contract_service.py`
- `backend/tests/unittests/flows/test_flow_run_input_payload.py`
- `backend/tests/unittests/flows/test_flow_run_service.py`

Red tests:

- `normalize_and_validate_flow_run_payload(...)` no longer accepts `metadata_json=...`; tests must use typed `FlowMetadataV1 | None`.
- both run-contract and rerun malformed published form schema return `flow_published_form_schema_invalid` through the same `PublishedFlowDefinition` accessor.
- `PublishedFlowDefinition.metadata()` maps invalid top-level form schema shape, invalid field type, and coded field-name errors to `flow_published_form_schema_invalid`.
- update `test_rerun_step_rejects_malformed_published_form_schema` so it asserts `code == "flow_published_form_schema_invalid"` instead of `code is None`.
- rerun required-field validation still rejects empty payloads with `flow_input_required_field_missing`.
- rerun omitted payload still does not require form fields.
- rerun valid published metadata normalizes required fields through the typed helper path.
- create-run valid metadata still normalizes required fields and preserves behavior covered by existing tests.
- create-run draft metadata leniency has service-level tests for invalid form_schema shape, invalid field type, and invalid field name; those cases return passthrough behavior through the named service helper and do not live in `flow_run_input_payload.py`.
- grep proof: no `metadata_json=` argument remains for `normalize_and_validate_flow_run_payload(...)`.
- grep proof: `flow_run_input_payload.py` no longer imports anything from `intric.flows.flow_metadata`.
- grep proof: `FlowRunService` no longer imports `serialize_flow_metadata`.
- grep proof: no parallel published metadata accessor such as `metadata_or_invalid` is introduced.

Verification:

```bash
cd backend && uv run pytest \
  tests/unittests/flows/test_published_definition_contract.py \
  tests/unittests/flows/test_flow_run_contract_service.py \
  tests/unittests/flows/test_flow_run_input_payload.py \
  tests/unittests/flows/test_flow_run_service.py \
  -q

cd backend && uv run pyright \
  src/intric/flows/published_definition.py \
  src/intric/flows/flow_run_contract_service.py \
  src/intric/flows/flow_run_input_payload.py \
  src/intric/flows/application/flow_run_service.py \
  tests/unittests/flows/test_published_definition_contract.py \
  tests/unittests/flows/test_flow_run_contract_service.py \
  tests/unittests/flows/test_flow_run_input_payload.py \
  tests/unittests/flows/test_flow_run_service.py

cd backend && uv run ruff check \
  src/intric/flows/published_definition.py \
  src/intric/flows/flow_run_contract_service.py \
  src/intric/flows/flow_run_input_payload.py \
  src/intric/flows/application/flow_run_service.py \
  tests/unittests/flows/test_published_definition_contract.py \
  tests/unittests/flows/test_flow_run_contract_service.py \
  tests/unittests/flows/test_flow_run_input_payload.py \
  tests/unittests/flows/test_flow_run_service.py

cd backend && uv run ruff format --check \
  src/intric/flows/published_definition.py \
  src/intric/flows/flow_run_contract_service.py \
  src/intric/flows/flow_run_input_payload.py \
  src/intric/flows/application/flow_run_service.py \
  tests/unittests/flows/test_published_definition_contract.py \
  tests/unittests/flows/test_flow_run_contract_service.py \
  tests/unittests/flows/test_flow_run_input_payload.py \
  tests/unittests/flows/test_flow_run_service.py
```

Stop if:

- the implementation needs AI Builder, routers, frontend, generated clients, migrations, or unrelated dirty files;
- create-run public behavior changes without a dedicated test and explicit receipt note;
- rerun malformed published metadata remains uncoded;
- the helper keeps both typed metadata and raw metadata_json parameters;
- broad `Any`, new casts, type-ignore comments, or Pyright ignores are added to get green checks;
- the Worker grows into a general input-payload redesign beyond typed metadata and the existing coercion behavior.

## Claude Gate

Run a host Claude plan gate before activation. This touches a shared validator signature and public error behavior, so the plan should be challenged before source edits.

Iteration 1 result: `changes_required`, `GREEN_LIGHT: no`, `MIN_SCORE: 7`, artifact `.codex/artifacts/claude-peer-loop-t036-flow-run-input-payload-typed-metadata-plan-gate-20260511T080103Z.md`.

Iteration 2 result: `green`, `GREEN_LIGHT: yes`, `MIN_SCORE: 8`, artifact `.codex/artifacts/claude-peer-loop-t036-flow-run-input-payload-typed-metadata-plan-gate-iteration-2-20260511T080457Z.md`.

Accepted iteration 2 constraints:

- Modify `PublishedFlowDefinition.metadata()` in place; do not ship both a bare accessor and a translated accessor.
- Drop the redundant `isinstance(flow.metadata_json, dict)` guard in create-run.
- Add a parametrized published metadata corruption test that proves invalid shape, invalid field type, and coded field-name errors all map to `flow_published_form_schema_invalid`.
- Keep `_parse_draft_metadata_lenient(...) -> FlowMetadataV1 | None` typed with no `Any`, casts, type-ignore comments, or Pyright ignores.
