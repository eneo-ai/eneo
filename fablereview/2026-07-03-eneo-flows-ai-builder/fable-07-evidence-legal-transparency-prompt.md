# Fable 07 Prompt: Flow Evidence, Provenance, And Legal Transparency Export

You are Claude Fable running a max-effort, source-backed architecture review for Eneo Flows evidence, provenance, auditability, and legal transparency.

Repository root: `/Users/ccimen/eneo/eneo-flows-clean`

## Mission

Review whether Eneo Flows can produce a legally defensible "what exactly happened" package for a completed, failed, or partially completed flow run.

The concrete product/legal need is:

> If Eneo must disclose material for a legal request or public-record style request, we should be able to show everything Eneo can reasonably show from our side: exact flow version, step definitions, prompts, input bindings, resolved source material, files, model, temperature/settings, RAG chunks, knowledge sources, timestamps, actor/service principal, errors/retries, outputs, artifacts, and the export manifest explaining any gaps or retention limits.

Assume the current system already has evidence/export support. Your job is to find what we missed, what is brittle, what is not transparent enough, and what should be simplified before production.

This session must not repeat the previous Fable sessions on Builder repair, underlag semantics, JSONB trade-offs, discovery dialog cadence, public API DX, or runtime crash recovery except where those concerns directly affect evidence/provenance/export transparency.

## Non-Negotiable Output Rules

- Return a complete Markdown review.
- Start with a five-line TL;DR.
- Use file:line citations for concrete claims.
- Include confidence for every material finding.
- Apply Ponytail: delete, merge, move, reuse, simplify.
- Do not edit source, tests, migrations, package files, config, or docs.
- Do not write files yourself. Your stdout will be saved to:
  `.codex/artifacts/fable-review-program-20260703/fable-07-evidence-legal-transparency-review.md`

## Read First

Read:

- `.codex/artifacts/fable-review-program-20260703/index.md`
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
- `backend/src/eneo/flows/application/flow_run_evidence_service.py`
- `backend/src/eneo/flows/api/flow_run_evidence_router.py`
- `backend/src/eneo/flows/flow_run_contract_models.py`
- `backend/src/eneo/flows/flow_run_contract_service.py`
- `backend/src/eneo/flows/flow_run_input_envelope.py`
- `backend/src/eneo/flows/flow_run_output_models.py`
- `backend/src/eneo/flows/flow_run_step_result_file.py`
- `backend/src/eneo/flows/runtime`
- `backend/src/eneo/flows/infrastructure/flow_run_repo.py`
- `backend/src/eneo/flows/infrastructure/flow_run_history_purge_repo.py`
- `backend/src/eneo/flows/application/flow_run_audit_outbox_policy.py`
- `backend/src/eneo/flows/application/flow_run_audit_outbox_delivery.py`
- `backend/src/eneo/database/tables/flow_tables.py`
- relevant retention/classification files under `backend/src/eneo`.
- tests under:
  - `backend/tests/unittests/flows/test_flow_run_evidence.py`
  - `backend/tests/unittests/flows/test_flow_run_evidence_service.py`
  - `backend/tests/unittests/data_retention`
  - `backend/tests/integration/flows`
  - migration tests for flow trace/provenance/evidence/retention.

Use `rg` to find:

- `evidence`
- `provenance`
- `manifest`
- `export`
- `audit`
- `trace`
- `prompt`
- `temperature`
- `model`
- `chunk`
- `retrieval`
- `reference`
- `retention`
- `purge`
- `classification`
- `attempt`
- `run_trace`
- `step_input_attempt`
- `step_result`

## Transparency Inventory To Build

Create a matrix for each item below:

- flow id/name/version and published/draft snapshot used at run time;
- step ids/names/order/types and exact step spec used;
- original user/API request and idempotency metadata;
- runtime input envelope after validation;
- uploaded files: id, name, MIME type, size, checksum/hash if available, storage/blob pointer, text extraction/transcription status, deletion/retention behavior;
- template assets and generated result files;
- resolved `input_bindings.question`;
- resolved source material / underlag sent into each step;
- exact prompt/messages sent to model after interpolation, including system/developer/user messages if applicable;
- model provider, model id, deployment name, model version if available;
- temperature and all relevant completion kwargs;
- max tokens / token limits / token usage;
- RAG query used, knowledge source ids, selected chunks, chunk text or stable chunk id, retrieval scores, source files, embedding model, chunking configuration if available;
- tool calls / MCP calls / external HTTP calls if applicable;
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

## Questions To Answer

1. Can a legal/compliance reviewer reconstruct exactly what Eneo sent to the model for each step?

2. Can they reconstruct which knowledge chunks/files influenced each answer, including chunk text or a stable pointer that survives retention rules?

3. Does the export distinguish "not applicable", "not captured", "captured but purged", "redacted", and "captured but not included"?

4. Are prompts and model settings captured before execution, after interpolation, or inferred after the fact?

5. Is model/provider/version/temperature/completion-kwargs capture complete enough for disclosure?

6. Are file/template/transcription/knowledge-source artifacts traceable end-to-end?

7. Does evidence survive reruns, retries, step edits, review checkpoints, and crash recovery?

8. Does retention/purge behavior preserve enough manifest metadata to explain missing content?

9. Are evidence/export schemas typed and owned, or are they hidden JSONB contracts?

10. Are there duplicated evidence/provenance/export concepts that should be merged?

11. Are there broad "best effort" or fallback paths that make the export look more complete than it is?

12. What should be deleted, moved, or simplified before production?

13. What is not worth fixing now?

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
3. `Evidence Lifecycle Map`
4. `Disclosure Inventory Matrix`
5. `Ranked Findings`
   - severity, problem, why it matters, evidence, owner/fix, acceptance criteria, tests, risk/trade-off, confidence.
6. `Prompt / Model Settings Traceability`
7. `RAG / Chunk / Knowledge Provenance`
8. `File / Template / Generated Artifact Provenance`
9. `Retention / Purge / Missing Data Manifest`
10. `Rerun / Retry / Review Checkpoint Evidence`
11. `API / Export Shape Review`
12. `Delete / Merge / Move List`
13. `What Current Tests Already Cover`
14. `Missing Red Tests`
15. `What Is Not Worth Fixing`
16. `From-Scratch Cleaner Evidence Design`
17. `Tomorrow Implementation Slices`
18. `Claims Codex Must Verify`
19. `Challenge This Brief`
20. `Confidence`

## Guardrails

- Do not propose storing every token forever without naming retention/security costs.
- Do not propose a generic compliance platform.
- Prefer a typed evidence manifest over scattered "best effort" fields.
- Treat legally ambiguous terms as product/legal questions, but still identify technical gaps precisely.
- If something is intentionally not captured, say whether the export explains that honestly.
