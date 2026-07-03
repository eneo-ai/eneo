# Fable 05 API Consumer DX Plan Brief

## TL;DR

1. Run one focused Fable session on public Flow API consumer DX and API maintainer DX.
2. Do not repeat Fable 06 runtime reliability or Fable 07 legal evidence findings except where the API hides or exposes those truths.
3. Treat Eneo Flows as pre-production: prefer clean long-term API architecture over compatibility preservation.
4. Ask Fable for implementation-ready findings that later Codex/Claude agents can turn into small reviewable changes.
5. Target a 9.5/10 maintainability and clean-architecture standard, with explicit gaps, owners, tests, and delete/merge/move candidates.

## Problem

The earlier Fable 05 prompt was broad, pointed at a few stale paths, and ran into quota before producing review content. Since then:

- Fable 06 verified runtime reliability gaps that the public API may need to expose honestly.
- Fable 07 verified evidence/legal transparency gaps that the public API and SDK must not obscure.
- The user now wants a long-term maintainability review aimed at a pre-production 9.5/10 API surface, not incremental patching.

## Why It Matters

The Flow API is the contract external developers and internal frontend/SDK consumers will build against. If required inputs, upload paths, idempotency, review/rerun semantics, evidence/export behavior, error contracts, or generated SDK types are unclear, the product becomes difficult to integrate and difficult to evolve. Public API debt is expensive after launch, so this is the right pre-production time to simplify, delete, merge, and refactor.

## Current Owner

Likely current owners to review:

- HTTP adapters and OpenAPI shape: `backend/src/eneo/flows/api/*`
- API error taxonomy and metadata: `backend/src/eneo/flows/flow_api_error_code.py`, `backend/src/eneo/flows/flow_api_exceptions.py`, `backend/src/eneo/flows/api/flow_api_error_metadata.py`
- Runtime input contract: `backend/src/eneo/flows/flow_run_contract_models.py`, `backend/src/eneo/flows/flow_run_contract_service.py`, `backend/src/eneo/flows/flow_run_input_envelope.py`, `backend/src/eneo/flows/flow_run_input_payload.py`
- Runtime/evidence implications: verified Fable 06 and Fable 07 reports in this folder
- Generated JS SDK/types: `frontend/packages/eneo-js/src/endpoints/flows.js`, `frontend/packages/eneo-js/src/types/schema.d.ts`, `frontend/packages/eneo-js/src/flows/*`
- Developer docs: `frontend/apps/docs-site/src/content/guides/flows/*`

## Proposed Canonical Review Boundary

Fable 05 should review the public contract boundary:

- endpoint topology and naming;
- OpenAPI operation IDs, tags, schemas, examples, and generated-client shape;
- external developer run journey;
- run contract and runtime upload policy discoverability;
- idempotency, review, resume, rerun, cancel, redispatch, and status semantics at the API boundary;
- evidence/artifact/export API clarity based on Fable 07;
- runtime failure/stuck/recovery signals based on Fable 06;
- error taxonomy/actionability;
- SDK/manual type drift;
- route/schema/test/doc ownership for long-term maintainability.

## Reuse, Move, Merge, Delete Bias

Because Flow is not in production yet:

- preserve compatibility only when source evidence proves real persisted data or external users depend on it;
- prefer one canonical endpoint contract owner over parallel docs/SDK/manual examples;
- delete stale helper exports, compatibility routes, duplicate SDK wrappers, or undocumented endpoint aliases if they do not earn their existence;
- merge shallow routers/models only when it improves locality and reviewability;
- avoid proposing a new API framework, broad API gateway, or generic versioning ceremony unless a concrete drift risk requires it.

## What Will Deliberately Not Change In This Pass

This pass will not ask Fable to:

- re-review Builder internals except where Builder-created Flow definitions leak into public API contracts;
- redo Fable 06 runtime crash recovery details;
- redo Fable 07 evidence capture internals;
- perform the broad dead-code/migration deletion audit reserved for Fable 08;
- design a new generic workflow platform.

## Acceptance Criteria For The Fable Output

The review should:

- start with a five-line TL;DR;
- include file:line evidence for concrete claims;
- rate the current API honestly against a 9.5/10 target;
- provide a consumer journey matrix with gaps and source owners;
- name canonical owners for endpoints, schemas, errors, docs, SDK, runtime-input contracts, and evidence/artifact contracts;
- produce ranked findings with severity, evidence, owner/fix, acceptance criteria, tests, risk, and confidence;
- state what current tests already cover;
- propose missing API/contract red tests;
- include a delete/merge/move list under the Ponytail lens;
- include an implementation backlog structured for later LLM coding.

## Tests And Validation Expected Later

Fable should propose, but not implement:

- backend API contract tests for the external run journey;
- OpenAPI/generated-client drift tests;
- docs-to-route/link contract tests;
- SDK behavior tests for upload/start/poll/evidence/review/rerun/error flows;
- error taxonomy completeness tests;
- status/idempotency/evidence surface tests that reflect Fable 06 and Fable 07 verified findings.

## Risk And Recovery

Main risk: Fable may produce a broad API wish list instead of source-backed, implementable findings. The prompt constrains this by:

- forcing source scope and file:line citations;
- making Fable 06 and 07 findings context rather than review scope;
- requiring “what is not worth fixing”;
- requiring smallest implementation slices and tests;
- requiring claims for Codex verification.

## Claude Review Questions

Challenge this plan before Fable runs:

- Is the Fable 05 scope narrow enough to produce high-value API findings?
- Is it using the verified runtime/evidence findings correctly without repeating them?
- Are we missing any must-read API/SDK/docs source paths?
- Is the 9.5/10 target framed usefully, or does it risk encouraging over-engineering?
- Does the prompt apply the Ponytail lens strongly enough: delete, merge, move, reuse, simplify?
- Is the output structured well enough for a later Codex/Claude implementation agent?
