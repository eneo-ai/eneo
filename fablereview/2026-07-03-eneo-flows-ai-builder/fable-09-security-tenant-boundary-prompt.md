# Fable 09 Prompt: Flow Security, Authorization, Tenant Boundary, And Evidence Access Review

You are Claude Fable running a max-effort, source-backed security and authorization architecture review for Eneo Flows.

Repository root: `/Users/ccimen/eneo/eneo-flows-clean`

## Mission

Review whether Eneo Flows enforces the right authorization and tenant/space boundaries across public API, runtime, evidence, files, packages, service keys, and API keys.

This is an adversarial cross-layer review. Look for request paths that are router-permitted but policy-denied, policy-permitted but router-denied, list endpoints that leak cross-tenant data, evidence/export endpoints that expose sensitive details, and one-off permission overrides that can drift.

This session must not repeat Builder repair, compiler/runtime underlag semantics, planning-state JSONB, discovery dialog cadence, public API naming/DX, runtime crash recovery, evidence completeness, or dead-code deletion except where those concerns directly affect authorization or tenant isolation.

## Non-Negotiable Output Rules

- Return a complete Markdown review.
- Start with a five-line TL;DR.
- Use file:line citations for concrete claims.
- Include confidence for every material finding.
- Apply Ponytail: delete, merge, move, reuse, simplify.
- Do not edit source, tests, migrations, package files, config, or docs.
- Do not write files yourself. Your stdout will be saved to:
  `.codex/artifacts/fable-review-program-20260703/fable-09-security-tenant-boundary-review.md`

## Read First

Read:

- `.codex/artifacts/fable-review-program-20260703/index.md`
- `docs/engineering/maintainability-standards.md`
- `docs/engineering/api-design-standard.md`
- `docs/engineering/testing-standard.md`

Then inspect source yourself.

## Primary Source Scope

Start with:

- `backend/src/eneo/server/routers.py`
- `backend/src/eneo/authentication/auth_dependencies.py`
- `backend/src/eneo/authentication/api_key_resolver.py`
- `backend/src/eneo/authentication/auth_models.py`
- `backend/src/eneo/flows/flow_access_policy.py`
- `backend/src/eneo/flows/flow_evidence_policy.py`
- `backend/src/eneo/flows/api/flow_access_context.py`
- `backend/src/eneo/flows/api/flow_definition_access.py`
- `backend/src/eneo/flows/api/flow_run_execution_router.py`
- `backend/src/eneo/flows/api/flow_run_evidence_router.py`
- `backend/src/eneo/flows/api/flow_upload_router.py`
- `backend/src/eneo/flows/api/flow_run_steps_router.py`
- `backend/src/eneo/flows/api/flow_authoring_router.py`
- `backend/src/eneo/flows/application/flow_run_access_policy.py`
- `backend/src/eneo/flows/application/flow_run_service.py`
- `backend/src/eneo/flows/application/flow_run_rerun_service.py`
- `backend/src/eneo/flows/infrastructure/flow_run_repo.py`
- `backend/src/eneo/flows/flow_template_asset_service.py`
- `backend/src/eneo/flows/flow_template_asset_repo.py`
- `backend/src/eneo/flow_packages/api/flow_package_router.py`
- `backend/src/eneo/flow_packages`
- relevant file/upload/auth/storage surfaces used by Flow.

Inspect tests:

- `backend/tests/unittests/flows/test_flow_run_access_policy.py`
- `backend/tests/unittests/flows/test_flow_scope_errors.py`
- `backend/tests/integration/test_api_key_access_matrix.py`
- `backend/tests/integration/test_api_key_scope_integration.py`
- `backend/tests/integration/test_api_key_service_keys.py`
- `backend/tests/integration/test_service_key_endpoint_gates.py`
- `backend/tests/integration/test_multi_tenant_data_isolation_adversarial.py`
- `backend/tests/integration/flows/test_flow_consumer_api_contract.py`
- `backend/tests/integration/flows/test_flow_evidence_api_contracts.py`
- `backend/tests/unit/test_flow_openapi_contract.py`

Use `rg` to find:

- `FlowApiAction`
- `require_flow`
- `require_*access`
- `service_key`
- `api_key`
- `tenant_id`
- `space_id`
- `evidence`
- `classification`
- `sensitive`
- `shared`
- `published`
- `draft`
- `scope`
- `permission`
- `FLOW_METHOD_PERMISSION_OVERRIDES`
- `authorize`

## Authorization Matrix To Build

Build a matrix for these actors:

- logged-in user session;
- user API key;
- tenant-scoped service key;
- space-scoped service key;
- tenant admin;
- space owner/admin/member/viewer;
- run creator/owner;
- non-owner same-space user;
- cross-space same-tenant user;
- cross-tenant user;
- disabled/deleted user/API key/service principal if modeled;
- actor requesting sensitive evidence/export details.

Evaluate access to:

- list flows;
- inspect draft flow;
- inspect published flow;
- create/edit/publish/delete flow;
- upload runtime files/template assets;
- start a run;
- list runs;
- get run details;
- get step outputs;
- edit/review/resume/rerun;
- get artifacts/generated files;
- get evidence/export/provenance;
- package import/export;
- webhook/outbound-delivery configuration if exposed;
- retention/history endpoints if exposed.

For each important endpoint/path, identify:

- router dependency gate;
- action/permission enum;
- application/domain policy owner;
- DB query tenant/space filter owner;
- error code/response;
- tests that prove fail-closed behavior;
- drift risk or duplication.

## Questions To Answer

1. Which endpoints are router-permitted but policy-denied, or router-denied but policy-permitted?

2. Where can list endpoints, package endpoints, upload endpoints, evidence/export endpoints, rerun/review endpoints, or generated-file endpoints leak tenant/space/draft/classification-scoped data?

3. Are service-key tenant and space scopes enforced consistently across Flow routes and shared file/template/package routes?

4. Is sensitive evidence governed by a distinct policy, or accidentally covered by broad run-read permissions?

5. Is there one canonical owner for Flow authorization, or do router gates, `flow_access_context`, `FlowRunAccessPolicy`, evidence policy, repo filters, and tests duplicate decisions?

6. Are method-name permission overrides stable enough, or are they a drift-prone compatibility path?

7. Do OpenAPI/SDK docs reveal the authorization model clearly enough for API consumers?

8. Are unauthorized/not-found/forbidden errors shaped consistently without leaking existence across tenants?

9. Which tests are adversarial API behavior tests versus internal policy mock tests?

10. What can be deleted, merged, or made less AI-sloppy under Ponytail?

11. What is not worth fixing now?

## Required Sections

Return:

1. `TL;DR`
2. `Ratings`
   - tenant isolation;
   - authorization ownership;
   - service-key/API-key safety;
   - evidence access safety;
   - error confidentiality;
   - testability;
   - production readiness.
3. `Authorization Boundary Map`
4. `Actor / Endpoint Matrix`
5. `Ranked Findings`
   - severity, problem, why it matters, evidence, owner/fix, acceptance criteria, tests, risk/trade-off, confidence.
6. `Router Gates vs Domain Policy`
7. `Tenant / Space Query Filter Review`
8. `API Key / Service Key Scope Review`
9. `Evidence / Artifact Access Review`
10. `Package / Import / Export Access Review`
11. `Error Confidentiality Review`
12. `Delete / Merge / Move List`
13. `What Current Tests Already Cover`
14. `Missing Adversarial Tests`
15. `What Is Not Worth Fixing`
16. `From-Scratch Cleaner Authorization Design`
17. `Tomorrow Implementation Slices`
18. `Claims Codex Must Verify`
19. `Challenge This Brief`
20. `Confidence`

## Guardrails

- Do not propose a generic policy engine unless the current boundary actually needs it.
- Prefer one canonical Flow authorization owner and thin router adapters.
- Treat existence leaks across tenant/space boundaries as security findings.
- Treat evidence/export as potentially more sensitive than ordinary run-read access.
- Be concrete: endpoint/path + actor + expected/actual behavior + test gap.
