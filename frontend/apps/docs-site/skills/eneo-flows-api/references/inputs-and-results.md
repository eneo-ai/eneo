# Inputs and results

The run contract is the client form schema and result preview. Fetch it for the published version the user is about to run.

## Run-contract fields

| Field                    | Consumer use                                                                                                                                              |
| ------------------------ | --------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `published_flow_version` | Send as `expected_flow_version` so stale forms fail explicitly.                                                                                           |
| `form_fields`            | Render structured values placed inside `input_payload_json`.                                                                                              |
| `steps_requiring_input`  | Render step-specific file controls and build `step_inputs`.                                                                                               |
| `runtime_upload_policy`  | Derive upload timeouts from size within the published minimum and maximum.                                                                                |
| `steps_requiring_review` | Prepare review UI for the modes and output types that may pause.                                                                                          |
| `aggregate_max_files`    | `0` means no runtime file steps. A positive value is the combined limit. `null` means at least one step is unbounded, so enforce per-step limits instead. |
| `final_output`           | Prepare terminal rendering for payload, artifact, or outbound delivery.                                                                                   |
| `template_readiness`     | Explain a document-generation Flow that is not ready to run.                                                                                              |

Each item in `steps_requiring_input` reports `step_id`, order, label, description, whether input is required, input format, maximum files, maximum bytes per file, and accepted MIME types. Never infer these limits from the label or from a previous Flow version.

Supported runtime file formats are determined by each returned step contract. Do not offer an image upload merely because a backend enum or old client type contains `image`; the published run contract and deployment documentation are authoritative.

## Form values

Form field types include text, number, date, select, multiselect, and list. Send values under their published names inside `input_payload_json`.

The server rejects these runtime-owned keys when a consumer sends them inside `input_payload_json`:

- `expected_flow_version`
- `file_ids`
- `step_inputs`
- `transkribering`

The server validates required fields, dates, finite numbers, collection shapes, allowed options, and reserved payload keys. Treat validation failures as a form correction, not a run failure.

## Step-bound uploads

Upload before starting the run:

```http
POST /flows/{flow_id}/steps/{step_id}/runtime-files/
Content-Type: multipart/form-data
```

The multipart field must be `upload_file`. Bind the result to the same logical step:

```json
{
  "step_inputs": {
    "<step-id>": {
      "file_ids": ["<runtime-file-id>"]
    }
  }
}
```

A file ID may be reused under multiple compatible step IDs when the same binary should feed multiple steps. Keep per-step file order stable between key derivation and run creation. Do not rely on file order to express business meaning; model semantic ordering in the published Flow.

There is no chunked or resumable upload and no general mid-run file injection. A supported step rerun may accept replacement input for that step only.

## Closed final-result union

On a completed run, `result` has exactly one `kind`:

| Kind               | Meaning                                                  | Consumer action                                                         |
| ------------------ | -------------------------------------------------------- | ----------------------------------------------------------------------- |
| `inline_text`      | Complete text is inline.                                 | Render `text`.                                                          |
| `file_backed_text` | Inline text is only a bounded preview.                   | If the file is available, request its signed URL for the complete text. |
| `structured`       | Authored JSON value plus the historical output contract. | Validate/render `value` using that run's `output_contract`.             |
| `artifact`         | One or more generated files.                             | Show metadata and request signed URLs on demand.                        |
| `outbound_http`    | A Flow-authored terminal delivery succeeded.             | Render the delivery receipt; no destination or payload is exposed.      |

Use an exhaustive branch. `result` is null before successful completion.

Historical results belong to each run's `flow_version`. Do not interpret an old structured value with the currently published output contract.

## Step outputs

`GET .../steps/` returns a bare array, not a paginated envelope. Use it for intermediate state, diagnostics, step usage, and current-attempt output. Prefer the run-level `result` for the stable terminal result.

Step status values are `pending`, `running`, `completed`, `failed`, and `cancelled`.

If `output_payload_json.text_overflow` exists, inline `text` is only a preview and its generated file identifies the complete output. Transcription text is a step output, not a run-input field. When multiple steps have structured output, choose by step ID/order and domain purpose instead of taking the first structured object.

## Artifact access

Request authorization before bytes:

```http
POST /flows/{flow_id}/runs/{run_id}/artifacts/{file_id}/signed-url/

{
  "expires_in": 3600,
  "content_disposition": "attachment"
}
```

Then perform an unauthenticated `GET` to the returned URL. Do not attach the Eneo credential to storage/download origins. Treat the signed URL itself as a short-lived secret: do not persist it, expose it to analytics, or write it to normal application logs.

Check file `availability` before showing download. `content_purged` means metadata remains but bytes do not; the signed-URL endpoint returns `410 flow_run_artifact_content_unavailable`. Never present a file-backed preview as the complete result.
