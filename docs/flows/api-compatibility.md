# Flows API: rebuild versus the previous branch

Generated 2026-10-20 from `feature/flows-and-builder`'s committed client schema and the rebuild's `app.openapi()`. Paths under `/api/v1/flows`.

## Kept (run side and authoring reads)

- `/api/v1/flows/` get, post
- `/api/v1/flows/{id}/` delete, get (methods before: delete, get, patch; now: delete, get)
- `/api/v1/flows/{id}/published/` get
- `/api/v1/flows/{id}/run-contract/` get
- `/api/v1/flows/{id}/runs/` get, post
- `/api/v1/flows/{id}/runs/{run_id}/` get
- `/api/v1/flows/{id}/runs/{run_id}/artifacts/{file_id}/signed-url/` post
- `/api/v1/flows/{id}/runs/{run_id}/cancel/` post
- `/api/v1/flows/{id}/runs/{run_id}/input-files/{file_id}/signed-url/` post
- `/api/v1/flows/{id}/runs/{run_id}/review-checkpoints/active/` get
- `/api/v1/flows/{id}/runs/{run_id}/review-checkpoints/{checkpoint_id}/` patch
- `/api/v1/flows/{id}/runs/{run_id}/review-checkpoints/{checkpoint_id}/approve-and-continue/` post
- `/api/v1/flows/{id}/runs/{run_id}/review-checkpoints/{checkpoint_id}/approve/` post
- `/api/v1/flows/{id}/runs/{run_id}/review-checkpoints/{checkpoint_id}/reject/` post
- `/api/v1/flows/{id}/runs/{run_id}/review-checkpoints/{checkpoint_id}/resume/` post
- `/api/v1/flows/{id}/runs/{run_id}/status/` get
- `/api/v1/flows/{id}/runs/{run_id}/steps/` get
- `/api/v1/flows/{id}/runs/{run_id}/steps/{step_id}/transcript-corrections/` patch
- `/api/v1/flows/{id}/runs/{run_id}/transcript-corrections/` get
- `/api/v1/flows/{id}/runtime-files/{file_id}/` delete

## Added by the rebuild

- `/api/v1/flows/authoring-assistant/` get
- `/api/v1/flows/{id}/artifacts/` get
- `/api/v1/flows/{id}/conversation/` post
- `/api/v1/flows/{id}/revisions/` get
- `/api/v1/flows/{id}/revisions/{revision}/` get
- `/api/v1/flows/{id}/revisions/{revision}/restore/` post
- `/api/v1/flows/{id}/runs/{run_id}/steps/{step_id}/transcript/` get
- `/api/v1/flows/{id}/runtime-files/` post

## Not served by the rebuild (404)

- `/api/v1/flows/ai-builder/client-errors` post
- `/api/v1/flows/ai-builder/flows/{flow_id}/review-packet` get
- `/api/v1/flows/ai-builder/flows/{flow_id}/review-suggestions` post
- `/api/v1/flows/ai-builder/flows/{flow_id}/run-failures/{run_id}/steps/{step_order}` get
- `/api/v1/flows/ai-builder/plans/{plan_id}` get
- `/api/v1/flows/ai-builder/plans/{plan_id}/apply` post
- `/api/v1/flows/ai-builder/plans/{plan_id}/approve` post
- `/api/v1/flows/ai-builder/plans/{plan_id}/create` post
- `/api/v1/flows/ai-builder/plans/{plan_id}/revise` post
- `/api/v1/flows/ai-builder/sessions` get, post
- `/api/v1/flows/ai-builder/sessions/{session_id}` get
- `/api/v1/flows/ai-builder/sessions/{session_id}/attachments/{file_id}` delete
- `/api/v1/flows/ai-builder/sessions/{session_id}/cancel` post
- `/api/v1/flows/ai-builder/sessions/{session_id}/messages` post
- `/api/v1/flows/ai-builder/sessions/{session_id}/models` get
- `/api/v1/flows/ai-builder/sessions/{session_id}/plans` get
- `/api/v1/flows/ai-builder/sessions/{session_id}/tools` get
- `/api/v1/flows/runs/capacity/` get
- `/api/v1/flows/runs/status-capabilities/` get
- `/api/v1/flows/{flow_id}/runs/{run_id}/steps/{step_id}/attempts/{attempt_no}/transcript-source/` get
- `/api/v1/flows/{id}/assistants/` post
- `/api/v1/flows/{id}/assistants/{assistant_id}/` delete, get, patch
- `/api/v1/flows/{id}/graph/` get
- `/api/v1/flows/{id}/http-test` post
- `/api/v1/flows/{id}/package-exports/` post
- `/api/v1/flows/{id}/publish/` post
- `/api/v1/flows/{id}/runs/{run_id}/evidence/` get
- `/api/v1/flows/{id}/runs/{run_id}/evidence/export` get
- `/api/v1/flows/{id}/runs/{run_id}/provider-calls/` get
- `/api/v1/flows/{id}/runs/{run_id}/redispatch/` post
- `/api/v1/flows/{id}/runs/{run_id}/retry/` post
- `/api/v1/flows/{id}/runs/{run_id}/review-checkpoints/{checkpoint_id}/edits` get
- `/api/v1/flows/{id}/runs/{run_id}/steps/{step_id}/transcript-regenerations/` post
- `/api/v1/flows/{id}/runs/{run_id}/steps/{step_id}/transcript-words/` get
- `/api/v1/flows/{id}/runs/{run_id}/transcript-corrections/{step_id}/revisions` get
- `/api/v1/flows/{id}/security-classification/preview` post
- `/api/v1/flows/{id}/steps/{step_id}/live-transcription-sessions/` post
- `/api/v1/flows/{id}/steps/{step_id}/runtime-files/` post
- `/api/v1/flows/{id}/template-files/` get, post
- `/api/v1/flows/{id}/template-files/{file_id}/` delete
- `/api/v1/flows/{id}/template-files/{file_id}/signed-url/` post
- `/api/v1/flows/{id}/template-inspect/` get
- `/api/v1/flows/{id}/tool-options` get
- `/api/v1/flows/{id}/unpublish/` post

## Known semantic changes on kept paths

- `POST /{id}/runs/`: `step_inputs` is gone; `values` (by form field key) and `files` (file ids by file form field key) replace it. `draft: true` starts a test run of the draft (users only). `flow_version` in responses is null for test runs; `is_test` says so.
- Runtime uploads are per flow (`POST /{id}/runtime-files/`), not per step; the upload binds to a file form field in the run request.
- `FlowRuntimePathsPublic` lists only served paths (no graph, evidence, provider-call, redispatch or transcript-word templates).
- Transcript segments live in the step result's `input_payload_json.transcription.segments`; `GET …/steps/{step_id}/transcript/` returns them with corrections applied.
- Transcript corrections keep the request and response shape (`segments_hash`, `expected_revision`, `occurrences`, `speaker_edits`, `speaker_names`) and the error codes `flow_transcript_corrections_stale_revision`, `_segments_unavailable`, `_invalid_occurrence`, `_invalid_speaker_edit`; revision history is not served.
- Service keys see only the runs they started, read published flows only, and never author.
