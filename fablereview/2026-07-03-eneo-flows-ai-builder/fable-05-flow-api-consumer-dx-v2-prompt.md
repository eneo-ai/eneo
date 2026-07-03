# Fable 05 v2 Prompt: Flow Public API, SDK Consumer DX, And API Maintainer DX

You are Claude Fable running a max-effort, source-backed API architecture review for Eneo Flows.

Repository root: `/Users/ccimen/eneo/eneo-flows-clean`

Save-path expectation: stdout will be saved to:

`fablereview/2026-07-03-eneo-flows-ai-builder/fable-05-flow-api-consumer-dx-v2-review.md`

## Mission

Review Eneo Flows as a public/developer-facing flow engine API and as an API codebase that a senior engineer should be able to maintain for years.

The target is not “good enough for launch.” The target is 9.5/10 maintainability, clean architecture, robustness, public API DX, and API maintainer DX. Flow and Flow AI Builder are not in production yet, so prefer the clean long-term design over compatibility preservation. Refactors, deletions, route/schema consolidation, and stronger typed contracts are acceptable recommendations when they make the system clearer and more reliable.

This review will be used by Codex or Claude later to implement the improvements. Structure your findings so a later implementation agent can act without re-litigating the architecture: name canonical owners, smallest safe implementation slices, acceptance criteria, red tests, risks, and what to delete/merge/move.

Focus on:

- how an external API consumer discovers, understands, and runs a flow;
- how they upload files, map inputs, start a run, poll status, inspect outputs, retrieve evidence/artifacts, pause/review/resume/rerun, and handle errors;
- whether OpenAPI, generated TypeScript, SDK helpers, and docs make the API easy to use correctly;
- whether API maintainer ownership, router boundaries, schema naming, error contracts, authorization, idempotency, and versioning are clean;
- whether the public API honestly exposes the verified runtime reliability and evidence/legal transparency truths from Fable 06 and Fable 07.

This session must not repeat completed Fable reviews on:

- Builder proposal repair and model self-correction;
- Builder compiler/underlag/RAG semantic contracts except where Builder-created Flow definitions leak into public runtime contracts;
- Builder planning-state/JSONB trade-offs except where public API schemas hide JSONB contracts;
- Builder discovery, attachments, dialog cadence, and user-question behavior;
- runtime crash recovery details except where the API hides or exposes stuck/retry/recovery state;
- evidence capture internals except where the API/export/SDK/docs expose or obscure legal transparency.

This is not:

- a new workflow engine design;
- a generic API gateway/versioning/framework proposal;
- the broad dead-code/deletion audit reserved for Fable 08;
- a full security/tenant-boundary review, although authorization clarity at API boundaries is in scope.

## Non-Negotiable Output Rules

- Return a complete Markdown review.
- Start with a five-line TL;DR.
- Use file:line citations for concrete claims.
- Include confidence for every material finding.
- Apply Ponytail: delete, merge, move, reuse, simplify before adding.
- Treat pre-production compatibility as expendable unless source evidence proves a real persisted-data or external-user dependency.
- Do not edit source, tests, migrations, package files, config, or docs.
- Do not write files yourself.
- Treat Fable as a reviewer, not an implementer.
- If output length becomes a problem, ship complete `Ranked Findings`, `Implementation Backlog For LLM Coding`, `API Contract Owner Map`, and `Missing API Contract Tests` first. A partial findings/backlog set is more valuable than a complete matrix with truncated findings. Truncate or reduce fidelity in `Consumer Journey Matrix`, `Endpoint / Contract Inventory`, ratings, and maintainer playbook before thinning source-backed findings.

## Read First

Read:

- `fablereview/2026-07-03-eneo-flows-ai-builder/index.md`
- `fablereview/2026-07-03-eneo-flows-ai-builder/fable-06-operational-runtime-reliability-maintainability-review.md`
- `fablereview/2026-07-03-eneo-flows-ai-builder/codex-verify-fable-06-runtime-report.md`
- `fablereview/2026-07-03-eneo-flows-ai-builder/fable-07-evidence-legal-transparency-v2-review.md`
- `fablereview/2026-07-03-eneo-flows-ai-builder/codex-verify-fable-07-evidence-report.md`
- `docs/engineering/api-design-standard.md`
- `docs/engineering/maintainability-standards.md`
- `docs/engineering/testing-standard.md`

Then inspect source yourself.

## Verified Findings To Carry Into This API Review

Do not blindly trust these as final API findings; use them as context and verify public-surface implications:

- Fable 06/Codex verified that stale RUNNING reconciliation has a likely transaction/commit defect under `autobegin=False`. API/SDK/docs should not imply stuck runs always recover unless the contract and implementation prove it.
- Fable 06/Codex verified runtime reliability gaps around webhook/outbox visibility, health signals, beat wrapper timeout behavior, and dual writer ambiguity for `flow_step_results`.
- Fable 07/Codex verified that rerun acceptance can overwrite current full step-result evidence while attempt rows do not currently persist full input/output payload snapshots.
- Fable 07/Codex verified that persisted model parameters may be configured kwargs rather than actual provider-call kwargs after JSON-mode mutation/fallback.
- Fable 07/Codex verified gaps around outbound HTTP/webhook evidence in the legal evidence package.
- Fable 07/Codex verified the API/export/debug story should be honest about retention, purge, omissions, and evidence limits.

Your job is to answer: does the public API, generated SDK, docs, and test contract make these truths clear and usable, or does it create a cleaner-looking story than the system can guarantee?

## Primary Source Scope

Start with API adapters and route composition:

- `backend/src/eneo/flows/api/flow_router.py`
- `backend/src/eneo/flows/api/flow_run_router.py`
- `backend/src/eneo/flows/api/flow_definition_router.py`
- `backend/src/eneo/flows/api/flow_authoring_router.py`
- `backend/src/eneo/flows/api/flow_assistant_router.py`
- `backend/src/eneo/flows/api/flow_consumer_router.py`
- `backend/src/eneo/flows/api/flow_run_execution_router.py`
- `backend/src/eneo/flows/api/flow_run_steps_router.py`
- `backend/src/eneo/flows/api/flow_run_evidence_router.py`
- `backend/src/eneo/flows/api/flow_upload_router.py`
- `backend/src/eneo/flows/api/flow_template_router.py`
- `backend/src/eneo/flows/api/flow_http_test_router.py`
- `backend/src/eneo/flows/api/flow_http_test_models.py`
- `backend/src/eneo/flows/api/flow_runtime_paths.py`
- `backend/src/eneo/flows/api/flow_runtime_endpoint_registry.py`
- `backend/src/eneo/flows/api/flow_models.py`
- `backend/src/eneo/flows/api/flow_api_common.py`
- `backend/src/eneo/flows/api/flow_api_error_metadata.py`
- `backend/src/eneo/flows/api/flow_trace_audit.py`
- `backend/src/eneo/flows/api/flow_run_status_capability_models.py`
- `backend/src/eneo/flows/api/flow_service_principal_actor_read_model.py`
- `backend/src/eneo/flows/ai_builder/ai_builder_router.py`
- `backend/src/eneo/flow_packages/api/flow_package_router.py`
- `backend/src/eneo/flow_packages/api/flow_package_models.py`
- `backend/src/eneo/flow_packages/api/flow_package_openapi_examples.py`

Treat this list as a starting set, not an exhaustive inventory. Enumerate every `*_router.py` under `backend/src/eneo/flows/api`, `backend/src/eneo/flows/ai_builder`, and `backend/src/eneo/flow_packages/api`, then explicitly triage each as in-scope, authoring-only but public, consumer-runtime, AI-Builder-specific, package-specific, dead/orphaned, or out-of-scope for this API DX pass. Orient route/path drift review around `backend/src/eneo/flows/api/flow_runtime_endpoint_registry.py` and `backend/src/eneo/flows/api/flow_runtime_paths.py` as likely runtime endpoint metadata sources of truth; verify whether they are actually complete.

Inspect public contract and runtime input owners:

- `backend/src/eneo/flows/flow_api_error_code.py`
- `backend/src/eneo/flows/flow_api_exceptions.py`
- `backend/src/eneo/flows/flow_error_taxonomy.py`
- `backend/src/eneo/flows/flow_run_contract_models.py`
- `backend/src/eneo/flows/flow_run_contract_service.py`
- `backend/src/eneo/flows/flow_run_input_envelope.py`
- `backend/src/eneo/flows/flow_run_input_payload.py`
- `backend/src/eneo/flows/flow_run_payload_validation.py`
- `backend/src/eneo/flows/flow_run_dispatch_request.py`
- `backend/src/eneo/flows/flow_run_rerun_request.py`
- `backend/src/eneo/flows/flow_run_rerun_graph.py`
- `backend/src/eneo/flows/flow_run_step_inputs.py`
- `backend/src/eneo/flows/flow_run_step_result_file.py`
- `backend/src/eneo/flows/application/flow_run_recovery_policy.py`
- `backend/src/eneo/flows/application/stale_queued_redispatch.py`
- `backend/src/eneo/flows/flow_runtime_file_service.py`
- `backend/src/eneo/flows/flow_runtime_upload_repo.py`
- `backend/src/eneo/flows/flow_runtime_file_integrity.py`
- `backend/src/eneo/flows/runtime_input.py`
- `backend/src/eneo/flows/published_runtime.py`
- `backend/src/eneo/flows/output_modes.py`
- `backend/src/eneo/flows/output_processing.py`
- `backend/src/eneo/flows/runtime/output_runtime.py`
- `backend/src/eneo/flows/runtime/step_execution_result.py`
- `backend/src/eneo/flows/runtime/step_result_builder.py`

Inspect evidence/artifact public surface as API, not as internals:

- `backend/src/eneo/flows/flow_run_evidence.py`
- `backend/src/eneo/flows/flow_run_evidence_bundle.py`
- `backend/src/eneo/flows/flow_run_evidence_export_manifest.py`
- `backend/src/eneo/flows/flow_run_evidence_export_summary.py`
- `backend/src/eneo/flows/flow_run_export_json.py`
- `backend/src/eneo/flows/application/flow_run_evidence_service.py`
- `backend/src/eneo/flows/application/flow_run_review_checkpoint_service.py`
- `backend/src/eneo/flows/application/flow_run_rerun_service.py`

Inspect generated SDK/types and docs:

- `frontend/packages/eneo-js/update.js`
- `frontend/packages/eneo-js/src/endpoints/flows.js`
- `frontend/packages/eneo-js/src/endpoints/flows.test.js`
- `frontend/packages/eneo-js/src/types/schema.d.ts`
- `frontend/packages/eneo-js/src/types/flow-resource-aliases.types.ts`
- `frontend/packages/eneo-js/src/flows/flow-api-error-codes.js`
- `frontend/packages/eneo-js/src/flows/flow-api-error-codes.d.ts`
- `frontend/packages/eneo-js/src/flows/flow-run-status-capabilities.js`
- `frontend/packages/eneo-js/src/flows/flow-run-status-capabilities.d.ts`
- `frontend/packages/eneo-js/src/flows/flow-run-reserved-input-payload-keys.js`
- `frontend/packages/eneo-js/src/flows/flow-run-reserved-input-payload-keys.d.ts`
- `frontend/packages/eneo-js/src/flows/runtime-upload-policy.js`
- `frontend/packages/eneo-js/src/flows/runtime-upload-policy.d.ts`
- `frontend/packages/eneo-js/src/flows/runtime-upload-policy.test.js`
- `frontend/apps/docs-site/src/content/guides/flows/index.mdx`
- `frontend/apps/docs-site/src/content/guides/flows/integrating-flows.mdx`
- `frontend/apps/docs-site/src/content/guides/flows/flows-faq.mdx`
- `frontend/apps/docs-site/src/content/guides/flows/designing-flows.mdx`
- `frontend/apps/docs-site/src/content/guides/flows/reference/errors.mdx`

Inspect tests:

- `backend/tests/integration/flows/test_flow_consumer_api_contract.py`
- `backend/tests/integration/flows/test_flow_evidence_api_contracts.py`
- `backend/tests/integration/flows/test_flow_runtime_worker_contract.py`
- `backend/tests/integration/flows/test_flow_review_pause_worker_contract.py`
- `backend/tests/integration/flows/test_flow_runtime_health.py`
- `backend/tests/unittests/flows/test_flow_run_execution_router.py`
- `backend/tests/unittests/flows/test_flow_upload_router.py`
- `backend/tests/unittests/flows/test_flow_evidence_router.py`
- `backend/tests/unittests/flows/test_flow_review_checkpoint_router.py`
- `backend/tests/unittests/flows/test_flow_template_router.py`
- `backend/tests/unittests/flows/test_flow_runtime_paths.py`
- `backend/tests/unittests/flows/test_flow_run_contract_service.py`
- `backend/tests/unittests/flows/test_flow_run_input_payload.py`
- `backend/tests/unittests/flows/test_flow_run_input_envelope.py`
- `backend/tests/unittests/flows/test_flow_api_error_codes.py`
- `backend/tests/unittests/flows/test_flow_docs_site_contract.py`
- relevant generated-client/OpenAPI drift tests.

Use `rg` to find:

- route decorators, `operation_id`, `tags`, `summary`, `description`, `responses`;
- `include_router`, route prefixes, runtime path templates;
- routers with zero decorators or routers not mounted anywhere, especially possible pre-production delete candidates;
- run creation, idempotency keys, cancel, redispatch, review, resume, rerun;
- runtime uploads, template assets, artifacts, signed URLs;
- evidence/export/raw export/audit reason;
- error adapters, `FlowApiErrorCode`, taxonomy, generated error code files;
- generated SDK paths and any manual type duplication;
- docs links/examples that reference old routes, old names, or incomplete journeys.

## API Consumer Journey To Review

Create a matrix showing whether a consumer can easily:

1. authenticate and understand service-key/user actor differences;
2. list flows;
3. inspect a draft flow versus a published runtime-safe projection;
4. discover required runtime inputs and upload policy;
5. understand accepted input types for text, JSON, form fields, audio, files, template assets, and generated files;
6. upload runtime files and template assets without confusing those two lifecycles;
7. map files to steps or runtime inputs;
8. start a run idempotently and safely;
9. poll status and understand terminal, review, retry, stuck, cancel, and redispatch states;
10. get step output and final output;
11. retrieve evidence, canonical export, artifacts, generated files, RAG provenance, and omission/retention notes;
12. pause for review, inspect active checkpoints, approve/reject, resume, and handle stale revisions/idempotency;
13. rerun a step or run and understand which inputs/files/evidence are superseded or retained;
14. handle validation, auth, missing-file, template, transcription, model, RAG, HTTP, webhook, evidence, retention, and runtime errors;
15. debug a failed/stuck/partially completed run without reading backend source.

For each journey item, mark:

- endpoint(s);
- response/request model(s);
- SDK helper(s);
- docs/example coverage;
- error/status contract coverage;
- missing ambiguity;
- canonical owner;
- current tests;
- confidence.

## Questions To Answer

1. Are routes named, tagged, and shaped coherently for API consumers?

2. Are operation IDs and generated TypeScript types clean enough for SDK consumers?

3. Are request/response schemas understandable without backend source?

4. Is the runtime input contract explicit enough for files/audio/document/text/json/form fields?

5. Are runtime file uploads and template asset uploads understandable as separate lifecycles?

6. Are idempotency contracts visible for run start, review actions, resume, rerun, upload, and redispatch?

7. Are run, step, review, rerun, cancel, redispatch, stuck, and failure states visible and actionable?

8. Are error codes and error payloads consistent, typed, generated, documented, and actionable?

9. Are evidence/artifacts/provenance endpoints shaped for real debugging, legal transparency, and honest missing-data disclosure?

10. Does the API expose enough of the Fable 06 runtime reliability truth, including health/outbox/stuck-run signals, without overpromising?

11. Does the API expose enough of the Fable 07 evidence truth, including rerun evidence gaps, model-parameter actuals, HTTP/webhook evidence gaps, and retention honesty?

12. Are routers thin adapters, or do they leak business logic?

13. Are generated frontend/client types the single source of truth, or are there local manual copies/drift?

14. What should be deleted, merged, moved, or simplified in the API layer before production?

15. What is not worth fixing now even under the 9.5/10 maintainability target?

## Required Sections

Return:

1. `TL;DR`
2. `Ratings`
   - API consumer DX;
   - API maintainer DX;
   - OpenAPI/generated-client quality;
   - SDK helper quality;
   - docs/example quality;
   - error-contract quality;
   - runtime input clarity;
   - idempotency/state clarity;
   - evidence/artifact API clarity;
   - authorization clarity;
   - testability;
   - production readiness;
   - gap to 9.5/10 target, framed as what blocks a multi-year maintainer and external API consumer from using this confidently rather than as a reason to manufacture extra work.
3. `Ranked Findings`
   - severity, problem, why it matters, evidence, canonical owner/fix, acceptance criteria, tests, risk/trade-off, confidence.
4. `Implementation Backlog For LLM Coding`
   - priority;
   - canonical owner;
   - smallest reviewable change;
   - files likely touched;
   - red test;
   - acceptance criteria;
   - risk/rollback;
   - dependencies on Fable 06/07 fixes.
5. `API Contract Owner Map`
   - endpoints/route topology;
   - request/response schemas;
   - runtime input contract;
   - uploads/template assets/artifacts;
   - status/idempotency/review/rerun;
   - errors/taxonomy/docs links;
   - SDK/generated types;
   - docs/examples;
   - evidence/export surface.
6. `Missing API Contract Tests`
7. `Consumer Journey Matrix`
8. `Endpoint / Contract Inventory`
9. `Runtime Reliability Truth At The API Boundary`
   - use Fable 06/Codex context only for public API implications.
10. `Evidence / Legal Transparency Truth At The API Boundary`
   - use Fable 07/Codex context only for public API implications.
11. `Generated Client / Frontend Type Drift`
12. `Error / Status / Idempotency Contract Review`
13. `Docs And Examples Review`
14. `Delete / Merge / Move / Reuse List`
    - include only candidates tied to API maintainability, generated-client quality, docs drift, or public contract clarity.
15. `What Current Tests Already Cover`
16. `What Is Not Worth Fixing`
17. `API Maintainer Playbook`
    - adding an endpoint;
    - adding a schema;
    - adding an error;
    - adding an SDK helper;
    - adding docs/examples;
    - updating OpenAPI/generated types;
    - proving route/schema/docs/client drift did not occur.
18. `Target 9.5/10 API Architecture`
    - concise future-state description;
    - canonical owners;
    - accepted trade-offs;
    - explicit non-goals.
19. `Claims Codex Must Verify`
20. `Challenge This Brief`
21. `Confidence`

## Guardrails

- Do not propose a new API framework.
- Do not invent versioning ceremony unless there is a concrete drift risk.
- Do not preserve compatibility for pre-production Flow behavior without persisted-data evidence, owner, and deletion trigger.
- Do not repeat Builder internal findings unless they directly affect public API contracts.
- Do not repeat runtime/evidence internals unless they directly affect what API consumers can see, rely on, debug, or disclose.
- Prefer one canonical schema/error/permission/docs/SDK owner per concept.
- Prefer generated types and route metadata over manual SDK type copies.
- Prefer typed request/response models over hidden JSON/dict-shaped public contracts.
- Prefer behavior/API contract tests over tests that mock internal router collaborators.
- If an API cannot guarantee something, recommend either making the guarantee real or documenting/exporting the limitation honestly.
