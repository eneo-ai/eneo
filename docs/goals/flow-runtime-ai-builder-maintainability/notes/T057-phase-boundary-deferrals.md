# T057 Phase Boundary Deferrals

## Verdict

The remaining items are explicit follow-ups, not hidden completion blockers for the current tranche. None is a P0/P1 runtime, API contract, data-loss, type-safety, or frontend-visible gap after T054 and T056.

## Deferral Table

| Follow-up | Owner | Trigger | Acceptance criteria | Why it does not block this tranche |
|---|---|---|---|---|
| `review-edit-openapi-error-examples` | Flow run execution router OpenAPI response docs. | Next API documentation polish or public API golden journey extension that touches review-edit docs. | The review-edit 400 response includes worked examples for both `typed_io_contract_violation` and `flow_review_stale_revision`; an OpenAPI contract test asserts both examples remain present. | Runtime behavior and frontend rendering are already covered; this is API documentation quality, not a correctness blocker. |
| `review-edit-validator-callback-followup` | `FlowRunRepository.edit_review_checkpoint_payload` plus `FlowRunService` review-edit validation boundary. | Before the next review-lifecycle slice that adds another edit, approve, reject, or resume precondition hook. | Repository keeps one locked lifecycle precondition path; service can inject schema/application validation without repository importing output contract validation; behavior tests still prove invalid edits do not mutate checkpoint, projection, revision, or outbox state. | Current review-edit behavior is already protected; this is a future complexity guard before adding more lifecycle hooks. |
| `comments-ai-slop-audit` | Each touched module owner; no broad standalone rewrite unless Scout proves a low-risk cleanup cluster. | Opportunistically when touching Flow runtime/API/AI Builder modules, or as a Scout-selected cleanup if comments become a reviewability blocker. | Restating or outdated comments are deleted or rewritten; intent comments remain; TODOs have do/delete/ticket verdicts; no broad churn commit. | No current comment issue blocks runtime/API correctness after the accepted dead branch was removed. |
| AI Builder live material-efficiency smoke | Flow AI Builder eval/live smoke harness owner. | Before declaring the broader Flow AI Builder production-readiness goal complete, or when a local API/server and required credentials are available. | Record exact commands and results for representative V1-V5/C1-C5 flow-generation cases, including material routing and failure notes. | T049 found the specific material-efficiency source-routing concern already covered by focused tests; live smoke remains useful but environment-dependent. |

## Naming Check

Current source code uses `FlowMetadata`, `FlowFormSchema`, `FlowCareDataPolicy`, and `PublishedFlowDefinition`. There is no source-level `FlowMetadataV1` or `PublishedFlowDefinitionV1` class. Current board guidance should use the unversioned names unless it refers to historical receipts.
