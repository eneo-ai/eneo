# Integration workflow

Use this sequence for a runtime-only application. Paths below are relative to the deployment's configured API base; prefer the server-relative paths returned by the published projection.

## 1. Authenticate and discover

Send exactly one credential, unless the client is a module session:

```http
Authorization: Bearer <user-access-token>
```

or:

```http
X-API-Key: <api-key>
```

A module session acts for its signed-in user and sends both headers on every request:

```http
Authorization: Bearer <module-user-token>
X-API-Key: <module-service-key>
```

The module token alone gets `401`, and the key alone acts as the service key instead of the user. Service keys and module tokens are for trusted server-side clients. A service key must send `space_id` (otherwise `400 flow_service_key_space_id_required`), lists published Flows only within its scope, and later sees only its own runs. A user principal (a user token, a user-owned key, or a module session with both headers) may omit `space_id` to list the Flows of every space the user belongs to: personal, shared directly or through a group, and the organization space for its admins. A space-scoped key narrows that list to its space. Drafts appear where the caller may edit Flows, so send `published_only=true` before presenting runnable Flows. Items carry `space_name`; group them on `space_id`. Use the published projection rather than the draft/current-definition endpoint:

```http
GET /flows/?space_id={space_id}&published_only=true&limit=50&offset=0
GET /flows/{flow_id}/published/
GET /flows/{flow_id}/run-contract/
```

Page lists using `has_more`, not the current page's `count`; items come oldest first. A listed Flow promises neither run permission nor readiness.

The published response contains server-relative `runtime_paths`. Preserve trailing slashes exactly. Flow runtime endpoints use them except `GET .../evidence/export`.

## 2. Collect inputs

Render user fields from `form_fields`. Use the published field name as the key inside `input_payload_json` and honor `required`, `type`, and published options.

Render file inputs from `steps_requiring_input`, keyed by `step_id`. For each file:

1. Check `max_files`, `max_file_size_bytes`, and `accepted_mimetypes` client-side.
2. Set the multipart field name to `upload_file` and the file part's `Content-Type` to an accepted MIME type.
3. Upload through the step-specific path.
4. Store the returned ID under that step in `step_inputs`.

For a file of `size_mib`, calculate the initial upload timeout as `clamp(min_timeout_seconds, max_timeout_seconds, ceil(size_mib * seconds_per_mebibyte))`. Keep a progressing upload alive and apply `idle_timeout_seconds` only after no progress. Do not copy one fixed timeout into every deployment.

Delete a file that the user abandons before run creation with `delete_runtime_file_template`. There is no automatic orphan-upload sweep. An attached file returns `409 flow_runtime_file_attached` and cannot be deleted through this endpoint.

## 3. Create once, retry safely

Send only the published request fields:

```json
{
  "expected_flow_version": 3,
  "input_payload_json": {
    "case_reference": "ABC-123"
  },
  "step_inputs": {
    "00000000-0000-0000-0000-000000000101": {
      "file_ids": ["00000000-0000-0000-0000-000000000701"]
    }
  }
}
```

Add a top-level `speaker_labels` only when the run contract's `transcription.speaker_labels.selectable` is true; see the speaker-label rules in `inputs-and-results.md`.

Send `Idempotency-Key` with create. Persist the key with the local submission until the outcome is known.

- Same key and same request: returns the existing run.
- Same key and different request: `flow_run_idempotency_conflict`.
- Stale `expected_flow_version`: `flow_run_stale_version`; refetch the published projection and contract, re-render changed inputs, then submit a new logical request.

Do not automatically create another run after a timeout unless the original key can be retried. The server may already have accepted the first request.

## 4. Poll without reading content

Cache `GET /flows/runs/status-capabilities/`, then poll the run's `get_run_status_template`.

A practical cadence is every 2 seconds for 30 seconds, every 5 seconds until two minutes, then every 15 seconds. Keep an application deadline and allow cancellation. Use the capability matching the returned status:

- continue while `should_poll` is true;
- show cancel only when `is_cancellable` is true;
- open review when `is_awaiting_review` is true;
- stop when `is_terminal` is true.

`awaiting_review` is non-terminal and remains pollable. There is no caller-registered webhook, SSE stream, or run-status WebSocket; the live text socket carries preview text only. A Flow-authored terminal `outbound_http` step is separate and does not report intermediate states to the caller.

Use run lists and status for routine views. They omit content. Read detail only for a screen that needs accepted inputs, results, files, error content, provider usage, or outbound-delivery metadata.

## 5. Finish or recover

On `completed`, fetch detail and branch on `result.kind`. On `failed`, fetch detail once for the typed terminal error and decide whether a new logical run is safe.

Do not automatically rerun an ambiguous model, transcription, or outbound request. A provider may have performed work before the failure was observed. A step rerun repeats that step's provider work and can add cost.

`redispatch` is only for a stale queued run whose bounded broker dispatch budget was exhausted before a worker claimed it. It is not a general retry endpoint and requires the observed `dispatch_exhausted_at` compare value.

Tenant capacity rejection uses HTTP `429`, code `flow_run_concurrency_limit_reached`, and `Retry-After`. The capacity endpoint is a snapshot, not a slot reservation; run creation remains authoritative.

## Minimum behavior tests

Test observable behavior with a stub server or deployed test Flow:

1. exact retry of a create request returns one logical run;
2. key reuse with a changed body is surfaced as a conflict;
3. stale published version refreshes the form instead of silently submitting;
4. file type and size are rejected before upload and server rejection still renders correctly;
5. `awaiting_review` keeps polling and does not read as terminal;
6. a failed content-bearing detail read does not leak a cached prior run;
7. an unknown string error code remains visible and does not trigger a destructive retry.
