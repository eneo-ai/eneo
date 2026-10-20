# Endpoints and errors

All paths are under the API prefix (`/api/v1` by default) and `/flows`.

| Method | Path                                                                | Body / query                                                                                            | Answer                                                                            |
| ------ | ------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------- | --------------------------------------------------------------------------------- |
| GET    | `/{id}/published/`                                                  |                                                                                                         | flow metadata + `runtime_paths`                                                   |
| GET    | `/{id}/run-contract/`                                               |                                                                                                         | `form_fields`, `steps_requiring_review`, `final_output`, `published_flow_version` |
| POST   | `/{id}/runtime-files/`                                              | multipart `upload_file`                                                                                 | file (`id`, `name`, `mimetype`)                                                   |
| DELETE | `/{id}/runtime-files/{file_id}/`                                    |                                                                                                         | 204; 409 once a run used it                                                       |
| POST   | `/{id}/runs/`                                                       | `values`, `files`, `run_label`, `expected_flow_version`, `draft` (users only); header `Idempotency-Key` | run (201)                                                                         |
| GET    | `/{id}/runs/`                                                       | `limit`, `offset`, `status` (repeatable)                                                                | run summaries, newest first                                                       |
| GET    | `/{id}/runs/{run_id}/`                                              |                                                                                                         | run with inputs, outputs, steps, files, active checkpoint                         |
| GET    | `/{id}/runs/{run_id}/status/`                                       |                                                                                                         | run summary                                                                       |
| GET    | `/{id}/runs/{run_id}/steps/`                                        |                                                                                                         | steps with payloads and files                                                     |
| POST   | `/{id}/runs/{run_id}/cancel/`                                       |                                                                                                         | run                                                                               |
| GET    | `/{id}/runs/{run_id}/review-checkpoints/active/`                    |                                                                                                         | checkpoint or null                                                                |
| PATCH  | `/{id}/runs/{run_id}/review-checkpoints/{cp}/`                      | `expected_checkpoint_revision`, `current_payload_json`                                                  | checkpoint                                                                        |
| POST   | `…/{cp}/approve/`, `…/{cp}/resume/`, `…/{cp}/approve-and-continue/` | `expected_checkpoint_revision`                                                                          | `{checkpoint, run}`                                                               |
| POST   | `…/{cp}/reject/`                                                    | `expected_checkpoint_revision`, `reason`                                                                | checkpoint                                                                        |
| POST   | `/{id}/runs/{run_id}/artifacts/{file_id}/signed-url/`               | `expires_in`, `content_disposition`                                                                     | `{url, expires_at}`                                                               |
| POST   | `/{id}/runs/{run_id}/input-files/{file_id}/signed-url/`             | same                                                                                                    | same                                                                              |
| GET    | `/{id}/runs/{run_id}/transcript-corrections/`                       |                                                                                                         | corrections per transcribe step, with `stale`                                     |
| PATCH  | `/{id}/runs/{run_id}/steps/{step_id}/transcript-corrections/`       | `schema_version`, `segments_hash`, `expected_revision`, `occurrences`, `speaker_edits`, `speaker_names` | corrections                                                                       |
| GET    | `/{id}/runs/{run_id}/steps/{step_id}/transcript/`                   |                                                                                                         | corrected segments, `speaker_names`, rendered `text`, `segments_hash`             |
| GET    | `/{id}/artifacts/`                                                  | `limit`                                                                                                 | files the flow's runs produced                                                    |

Run statuses: `queued`, `running`, `awaiting_review`, `completed`,
`failed`, `cancelled`. Step statuses add `pending` and `skipped`.
Checkpoint states: `awaiting_review`, `edited`, `approved`, `rejected`,
`resumed`, `cancelled`, `expired`.

Correction shapes: occurrence `{segment_index, char_start, char_end,
original, corrected}`; speaker edit `{segment_index, char_start,
char_end, original, original_speaker, speaker, decision}` (all span fields
null for a whole segment); names `{"SPEAKER_00": "Anna" | null}`.

Error codes: `flow_transcript_corrections_stale_revision`,
`_segments_unavailable`, `_invalid_occurrence`, `_invalid_speaker_edit`
(400 with `context.reason`); `insufficient_permission` (403);
`flow_runtime_file_in_use` (409). Failed runs carry `error.code`, for
example `flow_step_timeout`, `flow_step_outcome_unknown`,
`flow_run_rejected_in_review`, `flow_step_function_failed`.
