# Fable 05 Prompt: Flow Public API, SDK Consumer DX, And API Maintainer DX

You are Claude Fable running a max-effort, source-backed API architecture review for Eneo Flows.

Repository root: `/Users/ccimen/eneo/eneo-flows-clean`

## Mission

Review Eneo Flows as a public/developer-facing flow engine API.

This session must not repeat the current Fable sessions on Builder repair, compiler underlag/runtime contracts, JSONB data model, or discovery dialog. Focus on the external API and generated client experience:

- how an external API consumer understands and runs a flow;
- how they upload files, map inputs, start a run, poll status, inspect outputs, retrieve evidence/artifacts, pause/review/resume/rerun, and handle errors;
- whether OpenAPI/generated clients are clear and stable;
- whether API maintainer ownership, router boundaries, schema naming, error contracts, authorization, idempotency, and versioning are clean.

## Non-Negotiable Output Rules

- Return a complete Markdown review.
- Start with a five-line TL;DR.
- Use file:line citations for concrete claims.
- Include confidence for every material finding.
- Apply Ponytail: delete, merge, move, reuse, simplify.
- Do not edit source, tests, migrations, package files, config, or docs.
- Do not write files yourself. Your stdout will be saved to:
  `.codex/artifacts/fable-review-program-20260703/fable-05-flow-api-consumer-dx-review.md`

## Read First

Read:

- `.codex/artifacts/fable-review-program-20260703/index.md`
- `docs/engineering/api-design-standard.md`
- `docs/engineering/maintainability-standards.md`

Then inspect source yourself.

## Primary Source Scope

Inspect relevant API, service, error, and generated-client surfaces. Start with:

- `backend/src/eneo/flows/api`
- `backend/src/eneo/flows/application`
- `backend/src/eneo/flows/flow_api_error_code.py`
- `backend/src/eneo/flows/flow_api_errors.py`
- `backend/src/eneo/flows/flow_run_contract_models.py`
- `backend/src/eneo/flows/flow_run_contract_service.py`
- `backend/src/eneo/flows/flow_run_input_envelope.py`
- `backend/src/eneo/flows/flow_run_input_payload.py`
- `backend/src/eneo/flows/flow_run_output_models.py`
- `backend/src/eneo/flows/flow_run_evidence_bundle.py`
- `backend/src/eneo/flows/flow_run_export_json.py`
- `backend/src/eneo/flows/flow_template_asset_service.py`
- `backend/src/eneo/flows/flow_template_asset_repo.py`
- `frontend/packages/eneo-js/src/types/schema.d.ts`
- `frontend/apps/web/src/lib/features/flows` only where it reveals generated-client drift or API ambiguity.
- relevant API/contract tests under `backend/tests`.

Use `rg` to find route decorators, operation IDs, OpenAPI models, generated-client references, error adapters, file upload endpoints, run/rerun/review endpoints, and evidence/artifact endpoints.

## API Consumer Journey To Review

Evaluate whether a consumer can easily:

1. authenticate;
2. list flows;
3. inspect a flow definition and required runtime inputs;
4. understand accepted input types and schemas;
5. upload files or template assets;
6. map files to steps or runtime inputs;
7. start a run idempotently/safely;
8. poll or stream status;
9. get step output and final output;
10. retrieve evidence, artifacts, generated files, and RAG provenance;
11. pause for review or answer review checkpoints;
12. edit/resume/rerun a step or run;
13. handle validation, auth, missing-file, template, transcription, model, RAG, and runtime errors;
14. debug a failed run without reading backend source.

## Questions To Answer

1. Are routes named, tagged, and shaped coherently for API consumers?

2. Are operation IDs and generated TypeScript types clean enough for SDK consumers?

3. Are request/response schemas understandable without backend source?

4. Is the runtime input contract explicit enough for files/audio/document/text/json/form fields?

5. Are file upload/template asset flows understandable and safe?

6. Are error codes and error payloads consistent, typed, and actionable?

7. Is run/rerun/review/resume idempotency and state transition behavior visible at the API boundary?

8. Are evidence/artifacts/provenance endpoints shaped for real debugging and audit?

9. Are routers thin adapters, or do they leak business logic?

10. Are generated frontend/client types the single source of truth, or are there local manual copies/drift?

11. What should be deleted/merged/simplified in the API layer before production?

12. What is not worth fixing now?

## Required Sections

Return:

1. `TL;DR`
2. `Ratings`
   - API consumer DX;
   - API maintainer DX;
   - OpenAPI/generated-client quality;
   - error-contract quality;
   - runtime input clarity;
   - authorization clarity;
   - production readiness.
3. `Consumer Journey Map`
4. `Endpoint / Contract Inventory`
5. `Ranked Findings`
   - severity, problem, why it matters, evidence, owner/fix, acceptance criteria, tests, risk/trade-off, confidence.
6. `Generated Client / Frontend Type Drift`
7. `Error Contract Review`
8. `Authorization / Tenant Scope Review`
9. `Delete / Merge / Move List`
10. `What Current Tests Already Cover`
11. `Missing API Contract Tests`
12. `What Is Not Worth Fixing`
13. `API Maintainer Playbook`
14. `Tomorrow Implementation Slices`
15. `Claims Codex Must Verify`
16. `Challenge This Brief`
17. `Confidence`

## Guardrails

- Do not propose a new API framework.
- Do not invent versioning ceremony unless there is a concrete drift risk.
- Do not repeat Builder internal findings unless they directly affect public API.
- Prefer one canonical schema/error/permission owner per concept.
