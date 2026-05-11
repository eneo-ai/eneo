# T025 Typed Metadata Boundary Scout

## TL;DR

Do not add `FlowMetadataV1` as a one-off parser in a single call path.
The metadata boundary spans 151 `metadata_json` hits across 26 Flow files and 81 `form_schema` hits across 10 Flow files.
The canonical owner should be a new Flow-domain metadata module, not an API model, AI Builder model, or published-definition wrapper.
Use `FlowFormSchemaV1` as a standalone model nested under `FlowMetadataV1.form_schema`; this avoids a false binary between standalone-only and embedded-only ownership.
The first Worker should introduce the typed model at the validator/run-contract/run-input boundary; later Workers should migrate FlowService/published snapshots and then AI Builder readers so no parallel dict-reader owner remains.

## Current Boundary Map

| Metric | Count | Command |
|---|---:|---|
| `metadata_json` hits | 151 | `rg -n "metadata_json" backend/src/intric/flows -g '*.py'` |
| files with `metadata_json` | 26 | `rg -l "metadata_json" backend/src/intric/flows -g '*.py'` |
| `form_schema` hits | 81 | `rg -n "form_schema" backend/src/intric/flows -g '*.py'` |
| files with `form_schema` | 10 | `rg -l "form_schema" backend/src/intric/flows -g '*.py'` |

## Reader Inventory

| File | Hits `metadata_json` / `form_schema` | Classification | Current responsibility | Typed-boundary action |
|---|---:|---|---|---|
| `backend/src/intric/flows/application/flow_service.py` | 28 / 13 | `read_write`, `validator`, `serializer`, `published_snapshot` | Create/update/publish normalizes legacy form schema, validates metadata, validates steps, and stores normalized metadata. Evidence: `flow_service.py:92`, `:183`, `:332`, `:400`. | Make this the first application consumer of `FlowMetadataV1.parse_for_write(...)`; persist serialized metadata from the canonical model. |
| `backend/src/intric/flows/flow_validators_form.py` | 28 / 34 | `validator`, `legacy_normalizer` | Owns current form schema validation and legacy field-type normalization via dict walks and casts. Evidence: `flow_validators_form.py:61`, `:216`. | Replace with typed model validators; delete or shrink after typed model covers validation and legacy aliases. |
| `backend/src/intric/flows/flow_care_data_policy.py` | 11 / 0 | `validator`, `read_only` | Parses and validates `care_data_policy` from raw metadata. Evidence: `flow_care_data_policy.py:21`, `:46`. | Compose this policy into `FlowMetadataV1` or keep as a submodel used by `FlowMetadataV1`; do not leave as separate raw dict reader long term. |
| `backend/src/intric/flows/flow_run_contract_service.py` | 3 / 5 | `runtime_contract`, `read_only` | Published run-contract exposes `form_fields` by walking `published_definition.metadata_json`. Evidence: `flow_run_contract_service.py:92`, `:245`. | Read `FlowMetadataV1.form_schema.fields` so API consumer contract depends on the canonical parser. |
| `backend/src/intric/flows/flow_run_input_payload.py` | 2 / 5 | `runtime_contract`, `validator` | Normalizes and validates run payload fields from raw `form_schema`; has its own legacy type normalization map. Evidence: `flow_run_input_payload.py:33`, `:77`. | Replace field parsing with `FlowFormSchemaV1.ordered_fields`; remove duplicate legacy normalization map after tests move. |
| `backend/src/intric/flows/published_definition.py` | 6 / 0 | `published_snapshot`, `serializer` | Already has typed outer `PublishedFlowDefinition`, but inner `metadata_json` is raw/cast. Evidence: `published_definition.py:30`, `:36`, `:118`. | Keep the existing outer dataclass; parse its `metadata_json` into `FlowMetadataV1` or expose a typed accessor without inventing a second published-definition shell. |
| `backend/src/intric/flows/application/flow_run_service.py` | 4 / 0 | `runtime_contract`, `runtime_execution`, `read_only` | Uses draft/published metadata for sensitive export policy and run payload normalization. Evidence: `flow_run_service.py:196`, `:451`, `:731`. | Use typed metadata from draft flow and published definition; avoid parallel draft vs published semantics. |
| `backend/src/intric/flows/flow_validators.py` | 4 / 4 | `validator` | Aggregates form, care-data, transcription, variable-alias, and step validations. Evidence: `flow_validators.py:64`, `:307`. | Keep as orchestration layer initially; delegate metadata parsing to canonical model, not raw dict functions. |
| `backend/src/intric/flows/flow_evidence_policy.py` | 2 / 0 | `read_only`, `policy` | Checks sensitive flow metadata via care-data policy. Evidence: `flow_evidence_policy.py:93`. | Consume typed care-data policy through `FlowMetadataV1`. |
| `backend/src/intric/flows/infrastructure/flow_repo.py` | 2 / 0 | `serializer`, `persistence` | Hydrates/persists `metadata_json` on Flow rows. Evidence from grep at `flow_repo.py:116`, `:429`. | Stay thin: persist serialized dict only; do not parse business rules in repository. |
| `backend/src/intric/flows/domain/flow.py` | 1 / 0 | `domain_storage` | `Flow.metadata_json` is currently raw `JsonObject | None`. Evidence: `flow.py:113`. | Consider keeping raw storage on the domain object for first Worker, then adding typed accessor only if it reduces callers. |
| `backend/src/intric/flows/runtime/executor.py` | 1 / 0 | `runtime_execution`, `published_snapshot` | Pulls published snapshot metadata into runtime version metadata. Evidence from grep at `executor.py:525`. | Do not make runtime parse metadata unless it needs metadata semantics; avoid expanding runtime ownership. |
| `backend/src/intric/flows/api/flow_models.py` | 5 / 0 | `api_schema` | Public create/update/read models expose raw `metadata_json`. Evidence: `flow_models.py:410`, `:442`, `:486`. | Keep HTTP schema permissive initially; typed validation should happen in application boundary until API contract is intentionally tightened. |
| `backend/src/intric/flows/api/flow_authoring_router.py` | 2 / 0 | `adapter` | Passes request metadata to FlowService. | Keep thin; no metadata parsing in router. |
| `backend/src/intric/flows/api/flow_router_common.py` | 6 / 0 | `adapter`, `serializer` | Casts partial update payload metadata to service input. Evidence: `flow_router_common.py:94`. | Keep thin; remove `Any`/cast only after API model shape changes. |
| `backend/src/intric/flows/flow_capability_manifest.py` | 1 / 0 | `documentation`, `capability_text` | Only mentions metadata in a capability description. | No migration required. |
| `backend/src/intric/flows/ai_builder/ai_builder_materializer.py` | 10 / 2 | `read_write`, `serializer`, `ai_builder_materialization` | Builds metadata from draft spec form fields while preserving existing metadata. Evidence: `ai_builder_materializer.py:178`, `:533`. | Later Worker should build `FlowMetadataV1` then serialize; current comment-only prose should be cleaned when touched. |
| `backend/src/intric/flows/ai_builder/ai_builder_form_fields.py` | 5 / 4 | `read_only`, `ai_builder_patch` | Extracts `FormFieldSpec` from raw metadata and computes effective field names. Evidence: `ai_builder_form_fields.py:10`, `:55`. | Replace with canonical model adapters so AI Builder does not own a second form-schema parser. |
| `backend/src/intric/flows/ai_builder/ai_builder_flow_context.py` | 5 / 6 | `read_only`, `prompt_context` | Renders form fields into builder context and extracts names. Evidence: `ai_builder_flow_context.py:160`, `:406`. | Read canonical form schema; keep prompt rendering here, not parsing. |
| `backend/src/intric/flows/ai_builder/ai_builder_validation_flow_parity.py` | 5 / 4 | `serializer`, `validator`, `ai_builder_parity` | Builds temporary metadata from form fields and calls production validators. Evidence: `ai_builder_validation_flow_parity.py:28`, `:99`. | Use canonical metadata builder/parser; maintain parity with FlowService validation. |
| `backend/src/intric/flows/ai_builder/ai_builder_discovery_flow_defaults.py` | 4 / 4 | `read_only`, `ai_builder_defaults` | Detects whether a flow has form fields to derive runtime metadata defaults. Evidence: `ai_builder_discovery_flow_defaults.py:217`, `:241`. | Use canonical `FlowMetadataV1.has_form_fields` style API. |
| `backend/src/intric/flows/ai_builder/ai_builder_edit_compiler.py` | 4 / 0 | `read_only`, `ai_builder_patch` | Compiles edit draft form operations using current metadata. Evidence: `ai_builder_edit_compiler.py:70`, `:878`. | Keep compiler semantics; replace raw metadata parameter with typed metadata or canonical extraction helper. |
| `backend/src/intric/flows/ai_builder/ai_builder_edit_normalizer.py` | 2 / 0 | `read_only`, `ai_builder_patch` | Normalizes edit draft mechanics using current metadata field names. Evidence: `ai_builder_edit_normalizer.py:79`. | Use canonical form field extraction. |
| `backend/src/intric/flows/ai_builder/ai_builder_edit_validator.py` | 2 / 0 | `read_only`, `ai_builder_patch` | Validates edit draft operations against current metadata field names. Evidence: `ai_builder_edit_validator.py:45`. | Use canonical form field extraction. |
| `backend/src/intric/flows/ai_builder/ai_builder_edit_proposal.py` | 7 / 0 | `read_only`, `ai_builder_patch`, `ai_builder_provenance` | Passes current metadata through edit normalization/validation/compile and extracts `ai_builder.description` provenance. Evidence: `ai_builder_edit_proposal.py:129`, `:484`. | Use typed metadata for form-field reads; decide separately whether `ai_builder.description` belongs in `FlowMetadataV1` or an AI Builder metadata submodel. |
| `backend/src/intric/flows/ai_builder/ai_builder_domain_models.py` | 1 / 0 | `serializer`, `ai_builder_result` | `FlowChangeSet.metadata_json` remains raw. Evidence: `ai_builder_domain_models.py:326`. | Keep serialized output raw at boundary, but source it from canonical model after AI Builder migration. |

## Canonical Owner Recommendation

Create a Flow-domain metadata module:

`backend/src/intric/flows/flow_metadata.py`

This name is specific enough to avoid a generic `utils`/`types` smell, and it keeps metadata ownership in the Flow domain instead of HTTP adapters, AI Builder, or persistence.

Recommended public surface:

- `FlowMetadataV1`
- `FlowFormSchemaV1`
- `FlowFormFieldV1`
- `FlowCareDataPolicyV1` or a composed typed adapter around existing `FlowCareDataPolicy`
- `parse_flow_metadata(raw: JsonObject | Mapping[str, object] | None) -> FlowMetadataV1`
- `serialize_flow_metadata(metadata: FlowMetadataV1) -> JsonObject | None`

`FlowFormSchemaV1` should be a standalone model in the same module and be referenced as `FlowMetadataV1.form_schema`. This gives form schema its own validators and test surface while keeping the persisted metadata document under one canonical metadata owner.

Use Pydantic for boundary parsing because:

- this is JSONB/API-shaped input,
- the current code already has Pydantic response models for form fields,
- strict validation and `extra="forbid"` can remove many casts,
- legacy aliases such as `"string"` -> `"text"` can live in one `model_validator(mode="before")`.

Do not put the canonical owner in:

- `api/flow_models.py`: that would make HTTP models own domain metadata.
- `ai_builder/*`: AI Builder consumes Flow metadata; it must not own engine truth.
- `published_definition.py`: it already owns the outer published snapshot; the inner metadata payload is shared with draft Flow metadata.
- `flow_validators_form.py`: this file should shrink or become a compatibility wrapper, not become the long-term owner.

## Relationship To Existing `FlowMetadataPatch`

`backend/src/intric/flows/ai_builder/ai_builder_edit_models.py:117` defines `FlowMetadataPatch` for AI Builder edit commands:

- Keep it as an edit-command DTO for the first typed-boundary Worker.
- Do not treat it as persisted metadata truth.
- Later AI Builder Worker should compose it with `FlowMetadataV1`: patch operations should apply to a typed metadata object and serialize back through the canonical owner.

This avoids three parallel shapes: raw dict, AI Builder patch DTO, and `FlowMetadataV1`.

## Worker Sequence

### Worker 1: Introduce Core Typed Metadata/Form Schema Boundary

Goal: make the existing validation/run-contract/run-input form schema behavior consume one typed owner without changing API shape.

Suggested allowed files:

- `backend/src/intric/flows/flow_metadata.py`
- `backend/src/intric/flows/flow_validators_form.py`
- `backend/src/intric/flows/flow_run_input_payload.py`
- `backend/src/intric/flows/flow_run_contract_service.py`
- `backend/tests/unittests/flows/test_flow_metadata.py`
- `backend/tests/unittests/flows/test_flow_run_input_payload.py`
- `backend/tests/unittests/flows/test_flow_validators.py`
- `backend/tests/unittests/flows/test_flow_run_contract_service.py`

This exceeds the normal six-file target only if all listed tests are touched. If needed, split tests so the source diff stays small and the red proof remains focused.

Red tests:

- `FlowFormSchemaV1` rejects non-object form schema and non-list fields with the same stable error semantics as today.
- `FlowFormSchemaV1` normalizes legacy aliases `"string"`, `"email"`, and `"textarea"` to `"text"` in one place.
- Run input payload validation no longer carries its own legacy type-normalization map.
- Run contract form fields sort by typed field order and reject invalid published form schema through the existing `flow_published_form_schema_invalid` behavior.

Validation:

- `cd backend && uv run pytest tests/unittests/flows/test_flow_metadata.py tests/unittests/flows/test_flow_run_input_payload.py tests/unittests/flows/test_flow_validators.py tests/unittests/flows/test_flow_run_contract_service.py -q`
- `cd backend && uv run pyright src/intric/flows/flow_metadata.py src/intric/flows/flow_validators_form.py src/intric/flows/flow_run_input_payload.py src/intric/flows/flow_run_contract_service.py tests/unittests/flows/test_flow_metadata.py tests/unittests/flows/test_flow_run_input_payload.py tests/unittests/flows/test_flow_validators.py tests/unittests/flows/test_flow_run_contract_service.py`
- `cd backend && uv run ruff check src/intric/flows/flow_metadata.py src/intric/flows/flow_validators_form.py src/intric/flows/flow_run_input_payload.py src/intric/flows/flow_run_contract_service.py tests/unittests/flows/test_flow_metadata.py tests/unittests/flows/test_flow_run_input_payload.py tests/unittests/flows/test_flow_validators.py tests/unittests/flows/test_flow_run_contract_service.py`
- `cd backend && uv run ruff format --check src/intric/flows/flow_metadata.py src/intric/flows/flow_validators_form.py src/intric/flows/flow_run_input_payload.py src/intric/flows/flow_run_contract_service.py tests/unittests/flows/test_flow_metadata.py tests/unittests/flows/test_flow_run_input_payload.py tests/unittests/flows/test_flow_validators.py tests/unittests/flows/test_flow_run_contract_service.py`

Stop if:

- preserving current error strings/codes requires duplicating validators,
- the new model is used by only one caller,
- new `Any`, `cast`, or `type: ignore` appears outside the parser boundary,
- the implementation weakens published run-contract behavior.

### Worker 2: Move FlowService And Published Snapshot Metadata Through The Canonical Owner

Goal: make create/update/publish and published snapshots parse/serialize metadata through `FlowMetadataV1`.

Suggested allowed files:

- `backend/src/intric/flows/application/flow_service.py`
- `backend/src/intric/flows/published_definition.py`
- `backend/src/intric/flows/application/flow_run_service.py`
- `backend/src/intric/flows/flow_care_data_policy.py`
- `backend/src/intric/flows/flow_evidence_policy.py`
- `backend/tests/unittests/flows/test_flow_service.py`
- `backend/tests/unittests/flows/test_published_definition_contract.py`
- `backend/tests/unittests/flows/test_flow_run_service.py`

Reviewability note: this may need to split into FlowService/published-definition first, then evidence/care-data second, if pyright or behavior tests show too many call sites.

Red tests:

- `parse_published_definition` returns typed metadata or a typed accessor without accepting invalid `metadata_json.form_schema`.
- `FlowService.create_flow`, `update_flow`, and `publish_flow` serialize normalized metadata from the canonical model.
- Sensitive evidence policy behavior remains unchanged for valid and legacy truthy care-data policy.

Validation:

- `cd backend && uv run pytest tests/unittests/flows/test_flow_service.py tests/unittests/flows/test_published_definition_contract.py tests/unittests/flows/test_flow_run_service.py -q`
- targeted Pyright/Ruff on changed files.

Stop if:

- public API request schema must be tightened in the same slice,
- repository persistence starts parsing business metadata,
- published snapshot versioning/migration becomes necessary.

### Worker 3: AI Builder Metadata/Form Field Closer

Goal: remove remaining AI Builder raw form-schema dict readers and route all Flow metadata reads/writes through the canonical owner.

Suggested allowed files:

- `backend/src/intric/flows/ai_builder/ai_builder_form_fields.py`
- `backend/src/intric/flows/ai_builder/ai_builder_materializer.py`
- `backend/src/intric/flows/ai_builder/ai_builder_flow_context.py`
- `backend/src/intric/flows/ai_builder/ai_builder_validation_flow_parity.py`
- `backend/src/intric/flows/ai_builder/ai_builder_discovery_flow_defaults.py`
- `backend/src/intric/flows/ai_builder/ai_builder_edit_compiler.py`
- `backend/src/intric/flows/ai_builder/ai_builder_edit_normalizer.py`
- `backend/src/intric/flows/ai_builder/ai_builder_edit_validator.py`
- `backend/src/intric/flows/ai_builder/ai_builder_edit_proposal.py`
- focused AI Builder form-field/edit/materializer tests.

This is the named closer slice. It is larger than the normal six-file target because it retires remaining raw form-schema readers in one reviewable owner boundary. If it grows beyond form-field metadata, split it and keep a final closer.

Red tests:

- AI Builder materializer creates metadata through the canonical owner and preserves unrelated metadata.
- Edit compiler/normalizer/validator use canonical form-field extraction.
- Discovery flow defaults use canonical `has_form_fields` semantics.
- Validation parity still calls production validation behavior, not a copied AI Builder validator.

Validation:

- `cd backend && uv run pytest tests/unittests/flows/ai_builder/test_ai_builder_materializer.py tests/unittests/flows/ai_builder/test_ai_builder_edit_compiler.py tests/unittests/flows/ai_builder/test_ai_builder_edit_normalizer.py tests/unittests/flows/ai_builder/test_ai_builder_edit_validator.py tests/unittests/flows/ai_builder/test_ai_builder_form_field_lifecycle.py tests/unittests/flows/ai_builder/test_ai_builder_transcription_defaults.py -q`
- targeted Pyright/Ruff on changed AI Builder files/tests.

Stop if:

- the slice starts changing material routing/fan-in behavior instead of metadata parsing,
- `FlowMetadataPatch` must be redesigned rather than composed with the canonical model,
- more than form-schema metadata ownership is pulled into the change.

## Legacy Normalization Test Decision

The current legacy-form tests should be replaced, not augmented, after Worker 1 lands:

- `backend/tests/unittests/flows/test_flow_validators.py:474` should move to `test_flow_metadata.py` as a parser-normalization test.
- `backend/tests/unittests/flows/test_flow_run_input_payload.py:124` should stop proving a second runtime normalization map; it should prove run payload consumes the already-normalized typed field type.

Keep equivalent behavior coverage, but delete duplicate legacy-normalization ownership from runtime payload tests once the canonical parser owns it.

## `FlowStepResult.step_id` Decision

Keep `FlowStepResult.step_id` type-tightening as a separate cleanup lane.

Reason:

- It is a real cleanup candidate from T007.
- It does not share the same canonical owner as Flow metadata/form schema.
- Bundling it into the typed metadata boundary would violate the "one coherent purpose" reviewability rule.

The later cleanup Worker should prove every live `save_step_result` caller has a `step_id`, then tighten `FlowStepResult.step_id` and delete `flow_repo.py:577` legacy update behavior plus `test_save_step_result_legacy_update_raises_when_row_missing`.

## Claude Plan Gate Requirement

Run a Claude plan gate before activating Worker 1.

The gate should review:

- `flow_metadata.py` as canonical owner,
- `FlowFormSchemaV1` as standalone model nested in `FlowMetadataV1`,
- compatibility with `FlowMetadataPatch`,
- whether Worker 1 is narrow enough,
- replacement tests for legacy normalization,
- type debt counts and Pyright strictness.

Use a 15-20 minute timeout and iterate until green.

