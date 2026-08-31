# Endpoints and errors

Paths are relative to the deployment API base. Prefer `runtime_paths` from `GET /flows/{flow_id}/published/`; it makes a client portable across configured prefixes.

## Runtime endpoint map

| Purpose                        | Method and path                                                            |
| ------------------------------ | -------------------------------------------------------------------------- |
| Status behavior                | `GET /flows/runs/status-capabilities/`                                     |
| Capacity snapshot              | `GET /flows/runs/capacity/`                                                |
| List published Flows           | `GET /flows/?space_id={space_id}&limit={limit}&offset={offset}`            |
| Published projection and paths | `GET /flows/{flow_id}/published/`                                          |
| Current run contract           | `GET /flows/{flow_id}/run-contract/`                                       |
| Runtime-safe graph             | `GET /flows/{flow_id}/graph/`                                              |
| Upload a step input            | `POST /flows/{flow_id}/steps/{step_id}/runtime-files/`                     |
| Delete an abandoned upload     | `DELETE /flows/{flow_id}/runtime-files/{file_id}/`                         |
| Create or list runs            | `POST` or `GET /flows/{flow_id}/runs/`                                     |
| Poll content-free status       | `GET /flows/{flow_id}/runs/{run_id}/status/`                               |
| Read audited run detail        | `GET /flows/{flow_id}/runs/{run_id}/`                                      |
| Cancel                         | `POST /flows/{flow_id}/runs/{run_id}/cancel/`                              |
| Redispatch a stale queued run  | `POST /flows/{flow_id}/runs/{run_id}/redispatch/`                          |
| Active review                  | `GET /flows/{flow_id}/runs/{run_id}/review-checkpoints/active/`            |
| Edit review                    | `PATCH /flows/{flow_id}/runs/{run_id}/review-checkpoints/{checkpoint_id}/` |
| Approve, reject, or resume     | `POST` the corresponding `.../{checkpoint_id}/{action}/` path              |
| Step outputs                   | `GET /flows/{flow_id}/runs/{run_id}/steps/`                                |
| Rerun one step                 | `POST /flows/{flow_id}/runs/{run_id}/steps/{step_id}/rerun/`               |
| Artifact authorization         | `POST /flows/{flow_id}/runs/{run_id}/artifacts/{file_id}/signed-url/`      |
| Evidence                       | `GET /flows/{flow_id}/runs/{run_id}/evidence/`                             |
| Provider calls                 | `GET /flows/{flow_id}/runs/{run_id}/provider-calls/`                       |
| Evidence export                | `GET /flows/{flow_id}/runs/{run_id}/evidence/export` (no trailing slash)   |

Run creation returns a content-bearing run. Run lists and status return summaries. Detail is the audited content-bearing read.

Cancel on a terminal run is a successful no-op and returns the unchanged terminal status. Read the body instead of assuming `cancelled`.

## Error envelope

```json
{
  "message": "Flow must be published before creating runs.",
  "code": "flow_not_published",
  "context": null,
  "request_id": "request-id-for-support"
}
```

`code` is the control-flow contract. `message` is for display, `context` can carry recovery hints, and `request_id` or optional `error_id` belongs in support logs. Optional fields can be omitted. Ignore numeric `eneo_error_code` for branching.

Always keep an unknown-code branch that shows a generic failure, records the raw code and request ID, and refuses unsafe automatic retries.

## High-value request recovery

| HTTP / code                                | Recovery                                                                       |
| ------------------------------------------ | ------------------------------------------------------------------------------ |
| `401 authentication_error`                 | Send one supported credential.                                                 |
| `401 invalid_api_key`                      | Replace or reissue the key; do not retry it.                                   |
| `403 insufficient_scope`                   | Fix key scope. Do not infer whether the resource exists.                       |
| `403 insufficient_resource_permission`     | Reissue with the required permission reported in context.                      |
| `404 not_found`                            | Refetch discovery; do not retry the stale ID blindly.                          |
| `413 file_too_large`                       | Read the effective step limit from the run contract.                           |
| `415 unsupported_media_type`               | Match both declared MIME type and bytes to `accepted_mimetypes`.               |
| `422 request_validation_error`             | Fix the client request shape.                                                  |
| `429 flow_run_concurrency_limit_reached`   | Honor `Retry-After`, poll active runs, then retry the same logical submission. |
| `503` audit/content dependency unavailable | Retry the sensitive read with bounded backoff; do not bypass audit.            |

## Flow-specific recovery

| Code                                        | Recovery                                                                    |
| ------------------------------------------- | --------------------------------------------------------------------------- |
| `flow_not_published`                        | Ask for publication or select another published Flow.                       |
| `flow_run_stale_version`                    | Refetch published projection and run contract, then rebuild the request.    |
| `flow_run_idempotency_conflict`             | Reuse the original request or choose a new key for a genuinely new request. |
| `flow_run_reserved_input_payload_key`       | Remove runtime-owned keys from `input_payload_json`.                        |
| `flow_run_required_step_input_missing`      | Attach files to every required step in the contract.                        |
| `flow_run_unknown_step_input`               | Remove stale step IDs after refetching the contract.                        |
| `flow_run_top_level_file_ids_not_supported` | Move IDs into `step_inputs[step_id].file_ids`.                              |
| `flow_runtime_file_attached`                | Stop orphan cleanup; the run now owns the file lifecycle.                   |
| `flow_review_stale_revision`                | Refetch the active checkpoint and show the competing change.                |
| `flow_review_not_approved`                  | Approve first, then resume with the newest revision.                        |
| `flow_review_idempotency_key_required`      | Reuse one stable key for retries of that logical resume.                    |
| `flow_review_edit_not_allowed`              | Offer approve or reject instead of edit.                                    |
| `flow_review_edit_file_backed_unsupported`  | Do not edit the preview; offer approve or reject.                           |
| `flow_run_artifact_content_unavailable`     | Show retained metadata and mark bytes unavailable.                          |
| `flow_evidence_export_too_large`            | Use inline evidence or paginate provider calls.                             |

Run execution errors also appear in terminal run detail. Do not automatically retry timeouts or ambiguous provider failures: the external work may have started. Let an operator or user choose whether to submit a new run or rerun an eligible step.
