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
file=<binary>
```

Returns `file_id` used in run creation.

3. Create run

```http
POST /api/v1/flows/{flow_id}/runs/
Content-Type: application/json

{
  "file_ids": ["<file_id>"],
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

### `POST /flows/{id}/files/`
- `400`: flow does not accept file upload for `flow_input`
- `403`: API key scope mismatch
- `404`: flow not found in tenant scope
- `413`: file exceeds effective flow limit
- `415`: unsupported media type for current flow input policy
- `422`: invalid multipart/body

### `GET /flows/{id}/input-policy/` and run aliases
- `403`: API key scope mismatch
- `404`: flow or run not found for tenant scope

## Speech-to-text pattern

Recommended flow shape:
- Step 1: `input_type=audio`, `output_mode=transcribe_only`, `output_type=text`
- Step 2+: text processing (summarization, extraction, legal/RAG analysis, document generation)

This avoids unnecessary completion-model token usage in the transcription step and keeps step traces auditable.
