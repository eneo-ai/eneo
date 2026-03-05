# Flow API File Inputs (Consumer Guide)

This guide describes the flow-first runtime API path for external developers building custom apps
on top of Eneo Flows (for example, speech-to-text workflows).

## Runtime sequence (flow-first)

1. Discover input policy

```http
GET /api/v1/flows/{flow_id}/input-policy/
```

Response tells you:
- if upload is allowed (`accepts_file_upload`)
- accepted MIME types (`accepted_mimetypes`)
- effective max file size (`max_file_size_bytes`)

2. Upload input file(s)

```http
POST /api/v1/flows/{flow_id}/files/
Content-Type: multipart/form-data
upload_file=<binary>
```

Returns a `FilePublic` object. Use response field `id` as the file identifier in run `file_ids`.

Example response:

```json
{
  "id": "00000000-0000-0000-0000-000000000010",
  "name": "call.wav",
  "mimetype": "audio/wav",
  "size": 182344
}
```

3. Create run

```http
POST /api/v1/flows/{flow_id}/runs/
Content-Type: application/json

{
  "file_ids": ["<file_public.id>"],
  "input_payload_json": {
    "text": "optional free-form fields"
  }
}
```

4. Poll run status

```http
GET /api/v1/flows/{flow_id}/runs/{run_id}/
```

5. Read ordered step outputs

```http
GET /api/v1/flows/{flow_id}/runs/{run_id}/steps/
```

This endpoint is designed for UI rendering of intermediate outputs, diagnostics, and token usage.

## Common error contracts

All flow runtime errors use `GeneralError` JSON with machine-readable fields:

```json
{
  "message": "Human-readable error message",
  "intric_error_code": 9007,
  "code": "flow_not_published",
  "context": {
    "field_name": "text"
  },
  "request_id": "req-123"
}
```

Use `code` for programmatic handling and `request_id` for support/debug traces.

### `POST /api/v1/flows/{id}/runs/`
- `400`: `flow_not_published` when flow is not published
- `400`: `flow_run_input_payload_too_large` when request body exceeds configured limit
- `400`: `flow_run_concurrency_limit_reached` when too many active runs already exist
- `400`: `flow_input_required_field_missing` / `flow_input_required_field_empty`
- `400`: `flow_input_invalid_number` / `flow_input_invalid_date` / `flow_input_invalid_select_option`
- `403`: API key scope mismatch
- `404`: flow not found in tenant scope
- `422`: schema validation errors (request shape/type-level)

### `POST /api/v1/flows/{id}/files/`
- `400`: `flow_input_upload_not_supported` when flow `flow_input` does not allow files
- `400`: `flow_input_file_empty` when uploaded payload is zero bytes
- `400`: `flow_input_policy_missing_limit` when tenant flow limits are misconfigured
- `403`: API key scope mismatch
- `404`: flow not found in tenant scope
- `413`: `file_too_large` when file exceeds effective flow limit
- `415`: `unsupported_media_type` when declared or detected mimetype is not allowed
- `422`: invalid multipart/body

### `GET /api/v1/flows/{id}/input-policy/` and run aliases
- `403`: API key scope mismatch
- `404`: flow or run not found for tenant scope

## Speech-to-text pattern

Recommended flow shape:
- Step 1: `input_type=audio`, `output_mode=transcribe_only`, `output_type=text`
- Step 2+: text processing (summarization, extraction, legal/RAG analysis, document generation)

This avoids unnecessary completion-model token usage in the transcription step and keeps step traces auditable.
