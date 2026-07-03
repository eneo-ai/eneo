# Fable 07 v2 Prompt: Flow Evidence, Provenance, And Legal Transparency Export

You are Claude Fable running a max-effort, source-backed architecture review for Eneo Flows evidence, provenance, auditability, and legal/public-record transparency.

Repository root: `/Users/ccimen/eneo/eneo-flows-clean`

Save-path expectation: stdout will be saved to:

`fablereview/2026-07-03-eneo-flows-ai-builder/fable-07-evidence-legal-transparency-v2-review.md`

## Mission

Review whether Eneo Flows can produce a legally defensible "what exactly happened" package for a completed, failed, reviewed, rerun, or partially completed flow run.

The concrete product/legal need is:

> If Eneo must disclose material for a legal request or public-record style request, we should be able to show everything Eneo can reasonably show from our side: exact flow version, step definitions, prompts, input bindings, resolved source material, files, model, temperature/settings, RAG chunks, knowledge sources, timestamps, actor/service principal/API key context, errors/retries, outputs, artifacts, and an export manifest explaining any gaps, redactions, and retention limits.

Assume the current system already has evidence/export support. Your job is to find what is missing, misleading, brittle, duplicated, or not transparent enough before production.

This session must not repeat completed Fable reviews on:

- Builder proposal repair and model self-correction;
- Builder compiler/topology/underlag/RAG semantic contracts except where they affect evidence completeness;
- Builder planning-state/JSONB trade-offs except where evidence/export schemas rely on hidden JSON contracts;
- Builder discovery, attachments, dialog cadence, and user-question behavior;
- runtime crash recovery except where retries, crashes, reruns, review checkpoints, or terminalization affect evidence completeness.

This is not:

- a generic compliance platform design;
- a full security/tenant-boundary review;
- the public API consumer DX pass;
- the dead-code/deletion audit.

## Non-Negotiable Output Rules

- Return a complete Markdown review.
- Start with a five-line TL;DR.
- Use file:line citations for concrete claims.
- Include confidence for every material finding.
- Apply Ponytail: delete, merge, move, reuse, simplify before adding.
- Do not edit source, tests, migrations, package files, config, or docs.
- Do not write files yourself.
- Treat Fable as a reviewer, not an implementer.
- The authoritative deliverable is: `Disclosure Inventory Matrix`, `Ranked Findings`, evidence/export owner reconciliation, capture traceability, and `Missing Red Tests`. If output length becomes a problem, skip lower-value narrative rather than thinning those sections.

## Read First

Read:

- `fablereview/2026-07-03-eneo-flows-ai-builder/index.md`
- `fablereview/2026-07-03-eneo-flows-ai-builder/fable-06-operational-runtime-reliability-maintainability-review.md`
- `fablereview/2026-07-03-eneo-flows-ai-builder/codex-verify-fable-06-runtime-report.md`
- `docs/engineering/maintainability-standards.md`
- `docs/engineering/api-design-standard.md`
- `docs/engineering/testing-standard.md`

Then inspect source yourself.

## Primary Source Scope

Start with:

- `backend/src/eneo/flows/flow_run_evidence.py`
- `backend/src/eneo/flows/flow_run_evidence_bundle.py`
- `backend/src/eneo/flows/flow_run_evidence_export_manifest.py`
- `backend/src/eneo/flows/flow_run_evidence_export_summary.py`
- `backend/src/eneo/flows/flow_run_export_json.py`
- `backend/src/eneo/flows/flow_run_provenance.py`
- `backend/src/eneo/flows/flow_evidence_policy.py`
- `backend/src/eneo/flows/application/flow_run_evidence_service.py`
- `backend/src/eneo/flows/api/flow_run_evidence_router.py`
- `backend/src/eneo/flows/flow_run_contract_models.py`
- `backend/src/eneo/flows/flow_run_contract_service.py`
- `backend/src/eneo/flows/flow_run_input_envelope.py`
- `backend/src/eneo/flows/flow_run_step_result_file.py`
- `backend/src/eneo/flows/output_modes.py`
- `backend/src/eneo/flows/output_processing.py`
- `backend/src/eneo/flows/runtime/output_runtime.py`
- `backend/src/eneo/flows/runtime/step_execution_result.py`
- `backend/src/eneo/flows/runtime/step_result_builder.py`
- `backend/src/eneo/flows/runtime/executor.py`
- `backend/src/eneo/flows/runtime/step_execution_runtime.py`
- `backend/src/eneo/flows/runtime/rag_retrieval.py`
- `backend/src/eneo/flows/runtime/template_fill_runtime.py`
- `backend/src/eneo/flows/infrastructure/flow_run_repo.py`
- `backend/src/eneo/flows/infrastructure/flow_run_history_purge_repo.py`
- `backend/src/eneo/flows/application/flow_run_audit_outbox_policy.py`
- `backend/src/eneo/flows/application/flow_run_audit_outbox_delivery.py`
- `backend/src/eneo/flows/application/flow_run_lifecycle_events.py`
- `backend/src/eneo/database/tables/flow_tables.py`
- relevant retention/classification/audit files under `backend/src/eneo`.

Inspect tests:

- `backend/tests/unittests/flows/test_flow_run_evidence.py`
- `backend/tests/unittests/flows/test_flow_run_evidence_service.py`
- `backend/tests/unittests/flows/test_flow_evidence_router.py`
- `backend/tests/unittests/flows/test_flow_evidence_policy.py`
- `backend/tests/integration/flows/test_flow_evidence_api_contracts.py`
- `backend/tests/unittests/data_retention/test_flow_run_history_purge_selector.py`
- `backend/tests/integration/test_flow_runtime_retention_cleanup.py`
- relevant runtime schema/provenance/retention migration tests.

Use `rg` to find:

- `evidence`, `provenance`, `manifest`, `export`, `audit`, `trace`;
- `prompt`, `effective_prompt`, `temperature`, `completion_kwargs`, `model_parameters_json`, `model`;
- `chunk`, `retrieval`, `reference`, `rag`, `knowledge`;
- `retention`, `purge`, `classification`, `redact`, `redaction`;
- `attempt`, `run_trace`, `step_input_attempt`, `step_result`, `rerun`, `review_checkpoint`;
- `input_bindings`, `question`, `flow_input`, `step_input`.

## Known Lead To Reconcile

Start by reconciling the strict export manifest and live debug projection:

- strict evidence export manifest/schema version, e.g. `flow-evidence-export.v7`;
- live debug/export projection, e.g. `debug-export.v2`;
- whether one canonical evidence owner exists or whether the API exposes two disclosure stories;
- whether `Any`, `dict[str, Any]`, casts, or hidden JSONB shapes make the debug projection unsuitable for legal transparency.

Do not assume this is wrong. Verify whether it is deliberate, whether it is tested, and whether the export explains the difference honestly.

## Disclosure Inventory To Build

Create a matrix for each item below:

- flow id/name/version and exact published/draft snapshot used at run time;
- step ids/names/order/types and exact step spec used;
- original user/API request and idempotency metadata;
- runtime input envelope after validation;
- uploaded files: id, name, MIME type, size, checksum/hash if available, storage/blob pointer, text extraction/transcription status, deletion/retention behavior;
- template assets and generated result files;
- resolved `input_bindings.question`;
- resolved source material / underlag sent into each step;
- exact prompt/messages sent to the model after interpolation, including system/developer/user messages if applicable;
- model provider, model id, deployment name, model version if available;
- temperature and all relevant completion kwargs;
- max tokens, token limits, token usage if captured;
- RAG query used, knowledge source ids, selected chunks, chunk text or stable chunk id, retrieval scores, source files, embedding model, chunking configuration if available;
- tool calls, MCP calls, external HTTP calls if applicable;
- timestamps for run creation, step start, provider call, provider response, step finish, review pause/resume, rerun, export creation;
- actor: user, API key, service principal, tenant/space scope;
- errors, retries, provider failures, repair/fallback behavior, and terminalization;
- step outputs, final output, artifacts, evidence bundle, and export manifest;
- redactions or omissions and their stated reason;
- retention/purge behavior and whether export can explain missing/deleted data.

For each item, mark:

- captured in persistent state?
- exported in evidence bundle/API?
- reconstructable only indirectly?
- not captured?
- retention risk?
- schema owner?
- tests proving it?

## Focus Questions

Do not restate the inventory in prose. Use the matrix as the spine, then answer only the additive questions:

1. Which disclosure items are captured but not exported, exported but not typed, or inferred after the fact?

2. Are prompts/model settings captured before execution, after interpolation, or inferred after the fact?

3. Does the export distinguish "not applicable", "not captured", "captured but purged", "redacted", and "captured but not included"?

4. Does evidence survive reruns, retries, review checkpoints, purge, and crash/terminalization paths?

5. Where is the canonical owner for evidence manifest and disclosure semantics?

6. Are broad "best effort" or fallback paths making the export look more complete than it is?

7. What should be deleted, moved, merged, or simplified before production, and what is not worth fixing now?

## Required Sections

Return:

1. `TL;DR`
2. `Ratings`
   - legal transparency readiness;
   - prompt/model-setting traceability;
   - RAG/chunk traceability;
   - file/template provenance;
   - retention/purge explainability;
   - schema ownership;
   - API/export consumer clarity;
   - testability.
3. `Disclosure Inventory Matrix`
4. `Evidence / Export Owner Reconciliation`
   - include the strict export manifest vs debug projection lead;
   - name the canonical owner or the missing owner;
   - classify each relevant schema as typed-owned, hidden JSON/JSONB, or `Any`/dict-shaped.
5. `Ranked Findings`
   - severity, problem, why it matters, evidence, owner/fix, acceptance criteria, tests, risk/trade-off, confidence.
6. `Capture Traceability`
   - prompt/model settings;
   - RAG/chunks/knowledge;
   - files/templates/generated artifacts;
   - actor/timestamps/retries/reviews/reruns.
7. `Retention / Purge / Missing Data Manifest`
8. `Evidence-Coupled Delete / Merge / Move List`
9. `What Current Tests Already Cover`
10. `Missing Red Tests`
    - for each `captured but untested` matrix item, name the smallest red test that proves it survives rerun, retry, review checkpoint, purge, or terminalization as applicable.
11. `What Is Not Worth Fixing`
12. `Tomorrow Implementation Slices`
13. `Claims Codex Must Verify`
14. `Confidence`

## Guardrails

- Do not propose storing every token forever without naming retention/security costs.
- Do not propose a generic compliance platform.
- Do not turn this into a full security review; only discuss authorization where evidence/export sensitivity requires it.
- Prefer a typed evidence manifest over scattered "best effort" fields.
- Treat legally ambiguous terms as product/legal questions, but still identify technical gaps precisely.
- If something is intentionally not captured, say whether the export explains that honestly.
- Prefer one canonical evidence/export owner; do not create new abstractions unless they remove concrete duplicate ownership or make missing data honest.
