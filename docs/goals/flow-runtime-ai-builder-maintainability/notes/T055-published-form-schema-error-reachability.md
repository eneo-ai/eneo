# T055 Published Form Schema Error Reachability

## Verdict

`flow_published_form_schema_invalid` is reachable from public Flow consumer paths and should be mapped by the existing frontend Flow API error owner.

## Evidence

| Question | Evidence | Decision |
|---|---|---|
| Where is the code raised? | `backend/src/intric/flows/published_definition.py:50-75` parses published `metadata_json` and raises `FLOW_PUBLISHED_FORM_SCHEMA_INVALID` when persisted form schema is invalid. | Backend code is stable and typed enough to treat as a public API error contract. |
| Can run-contract callers hit it? | `backend/src/intric/flows/flow_run_contract_service.py:246-263` reads `published_definition.metadata().form_schema`; `backend/src/intric/flows/api/flow_upload_router.py:73-91` exposes this through `GET /api/v1/flows/{id}/run-contract/`. | Public consumer path: yes. |
| Can run creation hit it? | `backend/src/intric/flows/application/flow_run_service.py:455-462` parses the published definition and validates the submitted run payload against `published_definition.metadata()`. | Public consumer path: yes. |
| Does backend behavior already have tests? | `backend/tests/unittests/flows/test_published_definition_contract.py:128`, `backend/tests/unittests/flows/test_flow_run_service.py:994`, and `backend/tests/unittests/flows/test_flow_run_service.py:2030` cover malformed published form schema paths. | No backend source change needed in this Scout. |
| Does frontend map the code? | `frontend/apps/web/src/lib/features/flows/flowRuntimeErrorMapping.ts:4-29` lists frontend-owned Flow API error codes and lacks `flow_published_form_schema_invalid`; `frontend/apps/web/messages/en.json:1799-1822` and `frontend/apps/web/messages/sv.json:1799-1822` lack the matching message key. | Queue a narrow frontend Worker. |

## Worker Recommendation

Add `flow_published_form_schema_invalid` to the existing `flowRuntimeErrorMapping.ts` Flow API error contract, with English and Swedish catalog messages and a focused descriptor/message test. Do not change backend contracts, generated clients, or Flow UI layout.

The user-facing message should name the actual problem without implying runner fault: the published flow has invalid form configuration and a flow editor should review the form fields before the flow is run.
