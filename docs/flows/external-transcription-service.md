# External transcription service for flow audio steps

Flow `transcribe_only` steps can delegate transcription to an external
speaker-diarization service (such as [Tolka](https://github.com/eneo-ai/tolka))
instead of the model-registry LiteLLM path, or use it only for speaker
identification. Either way the flow transcript becomes the service's rendered,
speaker-labeled output (`[HH:MM:SS - HH:MM:SS] SPEAKER_00: ...` lines).

This is a deployment-level switch, not a catalog entry: either the deployment
has a transcription service configured or it does not. Knowledge uploads and
app runs always use the model-registry path regardless.

## Modes

| `FLOW_TRANSCRIPTION_SERVICE_MODE` | Transcription | Speaker labels | Flow model picker |
| --- | --- | --- | --- |
| `full` (default) | the service | the service | hidden; the flow's model is only the governance anchor |
| `diarize` | the flow's transcription model (registry, tenant provider credentials), with word timestamps | the service, from those word timestamps (`task=diarize` job) | shown; the model does the transcribing |

`diarize` mode keeps model governance in Eneo and reduces the service to a
diarization backend (Tolka's `TOLKA_ENGINE=diarize` tier needs no ASR model at
all). It costs one extra upload of the audio per file (Eneo to the provider,
then Eneo to the service). The provider is trusted for text only:

- Eneo splits the audio into five-minute chunks, measures each chunk, and
  sends the service one segment per chunk spanning that measured window. No
  provider word or segment timestamps are requested or forwarded; they have
  produced interleaved sentences when a server emitted broken timings.
- The service force-aligns the text inside each window (result metadata shows
  `alignment: forced`; anything else on a diarize job is worth alerting on).
  If alignment fails it labels whole segments, so text order is never lost.
- A transcript with no text at all is not sent; run metadata shows
  `diarization: skipped:empty_transcript` and the step carries an
  `audio_diarization_skipped` diagnostic.
- A failure of the service after a successful transcription fails the step
  (the author asked for speaker identification; silently dropping it would
  hide that).

Speaker labels are assigned per audio file by the service; Eneo renumbers them
so a multi-file transcript has unique labels, and records a speaker inventory
in the step's transcription metadata. A follow-up `speaker_mapping` step (see
`flow-developer-quickstart.md`) can map those labels to real participants.

The service's segments (`start`, `end`, `speaker`, `text` per rendered line)
are stored alongside the text as `transcription.segments` in the step's input
payload, with a `file_index` per audio file and the same renumbered labels.
The run review and evidence views use them to play the recording with the
spoken line highlighted; `POST
/api/v1/flows/{id}/runs/{run_id}/input-files/{file_id}/signed-url/` signs the
audio for anyone allowed to download the run's artifacts. Oversized segment
lists are dropped (`segments: null`, `segments_omitted_reason: "too_large"`)
and the views fall back to parsing the timestamped lines.

The frontend reads the mode from `GET /api/v1/settings/`
(`flow_transcription_service_mode`) to decide whether to show the model picker.

## Configuration

Set both variables on the backend API **and** the flow execution worker
(`task-execution-worker`); the worker is what actually calls the service.

| Variable | Required | Default | Meaning |
| --- | --- | --- | --- |
| `FLOW_TRANSCRIPTION_SERVICE_URL` | yes (to enable) | unset | Base URL of the service, without a `/v1` suffix, e.g. `http://tolka:8000`. Unset disables the feature. |
| `FLOW_TRANSCRIPTION_SERVICE_API_KEY` | yes when URL is set | unset | Static bearer token. Startup fails if the URL is set without it. |
| `FLOW_TRANSCRIPTION_SERVICE_SUBMIT_TIMEOUT_SECONDS` | no | 600 | HTTP timeout for the multipart job submission (uploads can be large). |
| `FLOW_TRANSCRIPTION_SERVICE_POLL_INTERVAL_SECONDS` | no | 5.0 | Delay between job-status polls. |
| `FLOW_TRANSCRIPTION_SERVICE_RESULT_TIMEOUT_SECONDS` | no | 120 | HTTP timeout for status and result requests. |
| `FLOW_TRANSCRIPTION_SERVICE_MODE` | no | `full` | `full` or `diarize`; see Modes above. |

Polling uses the step attempt's remaining execution budget. The default step
budget is `FLOW_STEP_BUDGET_SECONDS` (3600); a step's `timeout_seconds` can raise
it within the deployment ceiling.

### Service-side requirements (Tolka)

- Provision a named credential for Eneo: `TOLKA_API_TOKENS=eneo=<secret>`, and
  put the same secret in `FLOW_TRANSCRIPTION_SERVICE_API_KEY`. All Eneo
  tenants share this one client identity; size
  `TOLKA_MAX_QUEUED_JOBS_PER_CLIENT` for the whole deployment's fan-in.
- The flow execution worker must be able to reach the service over the
  network. Tolka's reference compose binds its API to `127.0.0.1`; expose it
  on a network the worker shares.
- `TOLKA_MAX_AUDIO_BYTES` (default 2 GiB) must cover Eneo's audio upload
  limit. Eneo sends the original uploaded bytes (mp3 etc.), not decoded wav.

## How it behaves

- **Engine selection** happens once per run at worker wiring
  (`flows/runtime/tasks.py`): URL configured means every audio step in the run
  uses the service (`flows/runtime/remote_transcription.py`); otherwise the
  model-registry `Transcriber` runs exactly as before.
- **The flow's transcription model is still required.** The wizard's model
  selection and space governance are unchanged; the selected model is the
  entitlement anchor, while the service does the transcribing. Usage seconds
  come from the service's measured duration.
- **Job flow**: one multipart `POST /v1/jobs` per audio file (with
  `language` and `diarize` from the flow's transcription config), a
  status poll every poll-interval, then `GET /v1/jobs/{id}/result`. Submission
  is retried on rate limiting and outages; once a job id exists nothing
  resubmits.
- **Failures** surface as the step error `TYPED_IO_TRANSCRIPTION_FAILED`,
  same as the model-registry path. There is no cancel endpoint: a cancelled
  or timed-out step leaves the service job to finish server-side, and the
  provider-call record marks the outcome unknown.
- **No progress signal** exists; a running step shows the usual running
  state until the job completes.

## Local development

Run Tolka from its repo with the no-GPU fake engine:

```bash
TOLKA_ENGINE=fake TOLKA_API_TOKENS=eneo=devtoken uv run uvicorn tolka.main:app --port 8000
```

Then in `backend/.env` (the devcontainer reaches the host via
`host.docker.internal`):

```bash
FLOW_TRANSCRIPTION_SERVICE_URL=http://host.docker.internal:8000
FLOW_TRANSCRIPTION_SERVICE_API_KEY=devtoken
```

Restart the backend and the flow execution worker, publish a flow with an
audio runtime input, and run it with any mp3. The transcript should be the
service's canned speaker-labeled output.

## Troubleshooting

| Symptom | Likely cause |
| --- | --- |
| Startup exits with `FLOW_TRANSCRIPTION_SERVICE_API_KEY is required` | URL set without a key. |
| Step fails immediately, logs show invalid credentials | Key does not match a token in `TOLKA_API_TOKENS`. |
| Step fails with `flow_step_timeout` | The step's execution budget is exhausted. Check the service's queue depth and worker health, or raise the step's `timeout_seconds` within the deployment ceiling. |
| Steps fail with rate-limit errors | The service's per-client queue cap is full; raise `TOLKA_MAX_QUEUED_JOBS_PER_CLIENT` or add service workers. |
| Transcript has no speaker labels | Speaker identification is off for the flow (wizard step 2), or the service ran without diarization support; check its engine tier and extras. In `diarize` mode also check the step for an `audio_diarization_skipped` diagnostic: the transcription model returned no word timestamps. |
| `diarize` mode: service rejects jobs with 422 | The service does not accept `task=diarize` (older Tolka); upgrade it or use `full` mode. |
| `diarize` mode: steps fail with `diarize_task_unsupported` | The service ignored `task=diarize` and transcribed with its own model (pre-task Tolka); Eneo refuses that result because it did not come from the flow's model. Upgrade the service. |


## Speaker review rollout

`FLOW_TRANSCRIPTION_INCLUDE_SPEAKER_REVIEW` defaults to `false`. Set it to
`true` only for a validated, limited rollout. It sends Vemsa's multipart
`include_speaker_review=true` on diarized jobs. Turning it off stops new opt-in
requests; existing review metadata and saved decisions remain readable.

The consumer implements [Vemsa contract v1](https://github.com/eneo-ai/vemsa/blob/97096dcacb919ed8f8258552f807b39d5bdc4ddb/docs/speaker-review-contract.md).
The six shared cases are pinned verbatim in
`backend/tests/fixtures/speaker_review.json` from that commit.

### Storage and decisions

- The transcription metadata's `speaker_review.files` array retains each file's
  version, overlap-detection availability and precise overlap intervals. Each
  entry includes `file_index` and `file_id`. Overlap IDs are prefixed with the
  stable file ID, both in the intervals and segment/word-sidecar references.
- Segments remain in the final stored order, with precise timing and original
  model `speaker_attribution`. Word-sidecar indices refer to that same order.
  Oversized structured detail is omitted within the existing caps; rendered
  text keeps uncertainty markers and the UI explains unavailable editing detail.
- Correction schema v3 adds `decision: confirmed | unresolved` and nullable
  speakers. Confirmation requires a resulting speaker; unresolved requires null.
  An unchanged label can be confirmed. Undo removes the overlay.
- PATCH uses the existing step-scoped corrections endpoint with
  `schema_version: 3`, the current `segments_hash` from the steps response, and
  `expected_revision`. Both full replacement lists must be sent. Old writes
  cannot replace v3 sets. Changed source hashes and stale revisions are rejected.
  Old v2 speaker assignments are read as confirmed.
- All wire character offsets count Unicode code points, not JavaScript UTF-16
  units. Both clients convert against immutable source text. A v3 text replacement
  that crosses a partial speaker-decision boundary is rejected with
  `transcript_corrections_invalid_occurrence` and reason
  `crosses_speaker_boundary`. Split replacements at those boundaries.
  Original word timings remain evidence; corrected text must not inherit
  fabricated word alignment.
- Corrections and their required actor audit are committed together. Approval
  blocks if required v3 propagation fails. Deliberately unresolved passages
  are valid and retain readable words in continuation text and transcript exports.

### Operator behavior

The built-in player shows provisional overlap as
“Överlappande tal – osäker talare”, with the model suggestion and overlap evidence
in review details. Operators can listen, confirm, change, leave unresolved, or undo
a decision, including within a selected span. Confirmed attribution can use a
mapped name; unresolved passages show “Talare går inte att avgöra”.
Provisional passages are excluded from confident speaker-naming samples.
A speaker without a clean sample remains in the inventory.

Transcript downloads use the same effective attribution as the player.
Changes saved after a summary was generated do not rewrite that summary:
use the explicit regeneration endpoint below to create updated output. Realignment of reviewed input
requires a deliberate re-diarization and invalidation workflow; stripping
review metadata is not supported.

### Before enabling

The repository tests cover the shared cases, multi-file IDs and word indices,
precision, size fallback, v3 persistence and undo, stale revisions/source hashes,
legacy reads, guarded writes, overlap UI boundaries, missing audio, exports,
unresolved approval, propagation failures, and audit persistence.

Deployment validation is still required: replay the fixed synthetic recordings
through the deployed Vemsa alignment path and evaluate consented representative
recordings for overlap quality, latency and output size. These consumer tests do
not establish diarization accuracy on real meetings.

### Explicit regeneration for completed runs

Lyssna can connect its explicit regenerate action to:

```http
POST /api/v1/flows/{flow_id}/runs/{run_id}/steps/{transcription_step_id}/transcript-regenerations/
Idempotency-Key: <unique key for this action>
Content-Type: application/json

{
  "expected_run_revision": 1,
  "expected_correction_revision": 8,
  "segments_hash": "<original 64-character source hash>"
}
```

Save the complete correction set successfully before requesting regeneration.
Use its accepted revision (or null if no correction set exists) and the run
revision from Eneo. The caller needs run and review access, including permission
to read the source content. Existing run capacity and file access rules apply.

The response is 201 for a new run, or 200 for an idempotent replay:

```json
{
  "run": { "...": "normal FlowRunPublic fields" },
  "created": true,
  "source_run_id": "<original run UUID>",
  "correction_revision": 8,
  "first_regenerated_step_id": "<first downstream step UUID>"
}
```

Poll the returned run ID using the existing run endpoint. The SDK exposes
`flows.runs.regenerateTranscript({ flowId, runId, stepId, expectedRunRevision,
expectedCorrectionRevision, segmentsHash, idempotencyKey })`.
The Lyssna browser/BFF action still needs to be connected to this endpoint;
its older per-step `rerunStep` helper is not this API.

#### Execution and provenance

- The source run must be completed. Its published version must still be the
  flow's current published version; regeneration never silently changes prompts.
- The transcription must be the first step, optionally followed immediately by
  one completed speaker-mapping step. At least one downstream step is required.
  Later audio inputs or speaker-mapping steps, missing structured segments and
  file-backed prefix output are rejected.
- Eneo imports only that prefix as completed snapshot attempts and executes all
  subsequent steps normally, including review gates and new output-file creation.
  It does not send reviewed text back to Vemsa for transcription or realignment.
- The snapshot is rendered from original segments and saved corrections, then
  existing speaker names are applied. Confirmed, provisional and explicit
  unresolved attribution remain distinct. Raw segments and matching word evidence
  are copied separately, along with the correction revision and original editor.
- The new run's `input_payload_json.transcript_regeneration` records source run
  and flow version, source/correction revisions, original segments hash, reviewed
  text hash, and first regenerated step. Imported attempts also identify their
  source step result and attempt. They report zero new provider tokens.
- Original summaries, files and history remain intact. Later source edits cannot
  change the accepted snapshot. The returned run owns the regenerated output.
  This is an explicit action; saving corrections alone does not start it.

#### Conflicts and retries

Reuse the same idempotency key and exact request after an uncertain response.
Eneo returns the accepted run even if the source correction revision has since
advanced. Reusing that key with different input returns
`run_idempotency_conflict`. A new key with stale run/correction revisions or hash
returns a 400 conflict with a reason in `context`; the module must preserve the
draft and surface the conflict instead of silently rebasing.

Unsupported transcript layouts return 400; inaccessible tenant-scoped resources
return 403/404. Capacity rejection returns 429 with `Retry-After`. Required audit
failure returns 503 and rolls back the new run and imported evidence. Creation
and its required audit commit before recoverable dispatch. After any uncertain
server response, retry the same key and request to discover the accepted outcome.
No new environment variable or flow configuration setting enables this endpoint.
