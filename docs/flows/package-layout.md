# Flow Package Layout

This page freezes the current root-level Flow package shape and records the
target home for each root entry. It is a layout decision, not a mass-move plan.
Root-level Flow modules should shrink over time; new root entries require an
explicit architecture decision.
When a root entry moves into a package, lower the guard's expected root count in
the same commit.

Allowed target homes:

- `api`: HTTP adapters, API schemas, OpenAPI-facing errors, and presenters.
- `application`: use-case services and request-independent orchestration.
- `domain`: typed contracts, policies, value objects, and invariants.
- `infrastructure`: persistence and external storage adapters.
- `runtime`: worker, executor, step execution, and runtime adapter code.
- `canonical-home`: an existing top-level package that is already a stable home.
- `plugin`: Flow-adjacent plugin boundary.
- `remove-merge-later`: duplicate or temporary root import surface to delete.

Portable transfer is owned by `eneo.flow_packages`, not by a new root entry
under `eneo.flows`. Within that package, `FlowPackageProvenance` is the only
durable omissions owner. `FlowRepository` and `FlowService` contribute one
tenant-scoped scalar distinct-assistant count for source-local MCP associations;
they do not copy MCP implementation, identifiers, configuration, credentials,
or content into Flow package code. Public adapters project the closed
provenance value instead of creating another omission model.

| Entry | Kind | Target home | Rationale |
| --- | --- | --- | --- |
| ai_builder | package | plugin | Flow AI Builder plugin boundary; only shared contracts should cross into Flow proper. |
| api | package | canonical-home | HTTP adapters and API schemas already live here. |
| application | package | canonical-home | Flow use cases and application services already live here. |
| domain | package | canonical-home | Domain entities and invariants already live here. |
| http_transport | package | runtime | HTTP transport belongs under runtime step handling. |
| infrastructure | package | canonical-home | Persistence and storage adapters already live here. |
| runtime | package | canonical-home | Worker and execution concerns already live here. |
| assistant_authoring_snapshot | module | domain | Assistant authoring snapshot is a typed published-definition value. |
| assistant_execution_snapshot | module | runtime | Assistant execution snapshot is consumed by runtime execution. |
| citation_sidecar | module | domain | Citation sidecar is a typed Flow data contract. |
| enums | module | domain | Shared Flow vocabularies belong with domain contracts. |
| execution_backend | module | runtime | Execution backend selection is runtime behavior. |
| flow_access_policy | module | application | Access policy supports use-case authorization decisions. |
| flow_ai_builder_budget_settings | module | plugin | Builder budget settings should live with the builder boundary. |
| flow_api_error_code | module | api | Public Flow error catalog is API-facing. |
| flow_api_exceptions | module | api | Public Flow error helpers are API-facing. |
| flow_error_taxonomy | module | api | Public Flow error taxonomy is API consumer-facing metadata. |
| flow_authoring_name | module | domain | Authoring name normalization is a domain value rule. |
| flow_authoring_runtime_input | module | domain | Runtime-input authoring rules are Flow contract rules. |
| flow_authoring_spec | module | domain | Authoring spec is a domain contract. |
| flow_authoring_transcription | module | domain | Transcription authoring config is a domain contract. |
| flow_authoring_variable_rewriting | module | domain | Variable rewrite rules are authoring-domain rules. |
| flow_capability_manifest | module | domain | Capability vocabulary is a Flow domain contract. |
| flow_document_limits | module | domain | Document limits are Flow policy values. |
| flow_evidence_policy | module | domain | Evidence policy is a Flow domain policy. |
| flow_input_limits | module | domain | Runtime input limits are Flow policy values. |
| flow_metadata | module | domain | Flow metadata is a domain contract. |
| flow_resource_bindings | module | domain | Resource bindings are Flow domain relationships. |
| flow_retention_policy | module | domain | Retention policy is a data/domain policy. |
| flow_retention_tombstone | module | domain | Retention tombstones are domain audit records. |
| flow_review_expiry_policy | module | domain | Review expiry rules are Flow domain policy. |
| flow_review_policy | module | domain | Review requirements are Flow domain policy. |
| flow_run_contract_models | module | api | Run contract models are public API-facing schemas. |
| flow_run_contract_service | module | application | Run-contract assembly is an application use case. |
| flow_run_dispatch_request | module | runtime | Dispatch payload is a worker/runtime command. |
| flow_run_error | module | domain | Run error payloads are Flow domain contracts. |
| flow_run_evidence | module | application | Evidence assembly spans runtime records into consumer output. |
| flow_run_evidence_bundle | module | application | Evidence bundle shape supports evidence assembly. |
| flow_run_evidence_export_manifest | module | application | Export manifest belongs with evidence export assembly. |
| flow_run_evidence_export_summary | module | application | Export summaries belong with evidence export assembly. |
| flow_run_export_json | module | application | Evidence JSON export is application-level presentation. |
| flow_run_input_envelope | module | domain | Run input envelope is a typed Flow contract. |
| flow_run_input_payload | module | domain | Run input payload is a typed Flow contract. |
| flow_run_payload_validation | module | domain | Payload validation enforces Flow contract invariants. |
| flow_run_provenance | module | domain | Provenance is Flow run domain metadata. |
| flow_run_redaction | module | domain | Redaction policy belongs with privacy/domain rules. |
| flow_run_rerun_graph | module | domain | Rerun graph rules are domain lifecycle rules. |
| flow_run_rerun_request | module | application | Rerun request normalization belongs with the rerun use case. |
| flow_run_step_input_file | module | domain | Step input file references are domain contracts. |
| flow_run_step_inputs | module | application | Step-input resolution is run-creation/rerun orchestration. |
| flow_run_step_result_file | module | domain | Step result file references are domain contracts. |
| flow_runtime_file_integrity | module | runtime | Runtime file integrity is execution/runtime safety. |
| flow_runtime_file_service | module | application | Runtime-file operations are application use cases. |
| flow_runtime_policy | module | domain | Runtime policy is a Flow domain policy. |
| flow_runtime_upload_repo | module | infrastructure | Runtime upload persistence is infrastructure. |
| flow_security_classification | module | domain | Security classification is a domain policy value. |
| flow_settings | module | domain | Flow settings are typed domain configuration. |
| flow_template_asset_repo | module | infrastructure | Template asset persistence is infrastructure. |
| flow_template_asset_service | module | application | Template asset operations are application use cases. |
| flow_validators | module | domain | Cross-field validators enforce domain contracts. |
| flow_validators_form | module | domain | Form validators enforce domain contracts. |
| flow_validators_http | module | domain | HTTP-step validators enforce domain contracts. |
| flow_validators_template | module | domain | Template validators enforce domain contracts. |
| flow_variable_definitions | module | domain | Variable definitions are Flow domain contracts. |
| input_binding_contract_rules | module | domain | Input binding rules are contract invariants. |
| output_modes | module | domain | Output modes are Flow domain vocabulary. |
| output_processing | module | runtime | Output processing is runtime execution behavior. |
| principal | module | domain | Flow principal identity is a domain contract. |
| published_definition | module | domain | Published definition parsing owns snapshot invariants. |
| published_runtime | module | runtime | Published runtime parsing feeds execution. |
| runtime_input | module | runtime | Runtime input resolution feeds execution. |
| source_display | module | domain | Source display values are Flow domain presentation. |
| source_identity | module | domain | Runtime source identity fields and schema projection are Flow contract rules. |
| step_chain_rules | module | domain | Step chain rules are domain invariants. |
| step_item_map | module | domain | Item-map configuration and validation are Flow step contract rules. |
| step_lineage | module | domain | Step lineage is domain metadata. |
| template_reference_analyzer | module | domain | Template reference analysis enforces domain contracts. |
| transcription_config | module | domain | Transcription config is a domain contract. |
| type_policies | module | domain | Type policy is a domain contract. |
| variable_resolver | module | runtime | Variable resolution is runtime execution behavior. |
