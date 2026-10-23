# External transcription service for flow audio steps

Flow `transcribe_only` steps can use an external transcription service (such
as Vemsa). The flow's transcription model always writes the text; the service
places its words in time and, when the run labels speakers, identifies who is
speaking. With speaker labels the flow transcript becomes the text with speaker
labels (`[HH:MM:SS - HH:MM:SS] SPEAKER_00: ...` lines); without them it stays
the model's text, and the word times are stored beside it.

An administrator connects the service under Modeller, Transkription (the
Talaridentifiering section) in the admin interface, with its address and API key, and gives each space
access to it. There is no deployment environment variable for it. Knowledge
uploads and app runs always use the model-registry path regardless.

## How word timing works

When a run labels no speakers and the flow chose a service, Eneo sends the
service a `timestamp` job per audio file (each part of one recording on its
own): the audio and the model's transcript as one segment per five-minute
chunk, without speakers. The service force-aligns the words in those windows
and returns them as reader lines without speakers (`alignment: forced`).

- The step's text stays exactly the model's text, so later steps read no
  timestamps. The timed lines are stored as the transcript's segments, and
  their words in the words row, for playback that follows the audio word by
  word. A regeneration of such a transcript renders plain lines without times.
- The lines are admitted only when every line has words and no speaker, they
  render the service's text, and together they say what the model wrote (a
  token without a letter or digit, such as a lone dash, may be left out).
- A timing that fails does not fail the step: it keeps what it would have
  without a service, the model's text without segments (a live transcript
  keeps its live passages). Cancellation, the step's own time limit and a
  provider-call evidence gap still end the step.
- The step's transcription metadata records the outcome as `word_timing`:
  `{"status": "done"}`, or `{"status": "failed", "reason": ...}` with one of
  `unavailable` (the chosen service could not be used: not usable in the space,
  removed, or not reachable), `unsupported` (the service refused or ignored the
  `timestamp` task), `credentials` (it rejected the key), `failed` (the job
  failed or was cancelled, or its outcome was lost) or `no_timings` (the result
  held no usable word times for the transcript). A step whose flow chose no
  service, or that labels speakers, has no `word_timing`. With several files,
  every file is timed or the step keeps no segments, and the first failure is
  the reason.

## How speaker identification works

Model governance stays in Eneo and the service is reduced to a
diarization backend (Vemsa's `VEMSA_ENGINE=diarize` tier needs no ASR model at
all). It costs one extra upload of the audio per file (Eneo to the provider,
then Eneo to the service). The provider is trusted for text only:

- Eneo splits the audio into five-minute chunks, measures each chunk, and
  sends the service one segment per chunk spanning that measured window. No
  provider word or segment timestamps are requested or forwarded; they have
  produced interleaved sentences when a server emitted broken timings.
- The service force-aligns the text inside each window (result metadata shows
  `alignment: forced`; anything else on a diarize job is worth alerting on).
  If alignment fails it labels whole segments, so text order is never lost.
- A file with no transcription text is not sent for speaker identification.
  Empty chunks contribute no timestamp headings. If every file returns empty
  or whitespace-only text, the step fails with `typed_io_transcription_empty`.
- A failure of the service after a successful transcription fails the step
  when the run labels speakers (the author asked for speaker identification;
  silently dropping it would hide that).

Speaker labels are assigned per audio file by the service; Eneo renumbers them
so a multi-file transcript has unique labels, and records a speaker inventory
in the step's transcription metadata. The metadata also names the connection
that labelled the step (`speaker_service` and `speaker_service_id`), as it was
named then; the run's step details show it in Avancerad. A step that only had
its words timed names no speaker service. A follow-up `speaker_mapping` step
(see `flow-developer-quickstart.md`) can map those labels to real participants.

The service's segments (`start`, `end`, `speaker`, `text` per rendered line)
are admitted only when every entry is valid and their complete ordered rendering
matches the service's text before speaker renumbering. Otherwise the canonical
text is kept, with segment details omitted as `no_segments` and no word timings.
Admitted segments retain a `file_index` per audio file and the same renumbered labels.
The run review and evidence views use them to play the recording with the
spoken line highlighted; `POST
/api/v1/flows/{id}/runs/{run_id}/input-files/{file_id}/signed-url/` signs the
audio for anyone allowed to download the run's artifacts. Oversized segment
lists are dropped (`segments: null`, `segments_omitted_reason: "too_large"`)
and the views fall back to parsing the timestamped lines.

Transcripts above the inline text limit are stored once as a generated plain-text
file. An unchanged `transcribe_only` output reuses that file. If an input binding
changes the output, for example by adding a heading, the output follows the usual
inline limit and gets a separate file when it exceeds the limit. Later steps read
the complete output through `previous_step`; `{{transkribering}}` resolves the
run's transcript, not the step's output. A `speaker_mapping` step, and a reviewer's
correction of it, replace that transcript with the named text only while it is
still the inline transcript the speaker step read; a file-backed transcript, or one
an input binding changed, stays raw. File-backed outputs keep bounded previews. Section processing
gives each model call only its selected section. The existing material size and
model context limits still apply. Segment and word timing limits are unchanged.

File-backed transcript outputs cannot be edited at a review checkpoint, have
corrections folded into them, be reused in a prefix retry, or be regenerated
from corrections. Speaker naming still rejects a renamed transcript above the
inline output limit. These operations do not rewrite the generated transcript
file; its bytes remain fixed for checkpoint history and evidence.

## Configuration

Connect the service in the admin interface under Modeller, Transkription, in the
Talaridentifiering section:
enter its base address (for example `https://vemsa.example.org`; a trailing
`/v1` is removed) and its API key. Then give each space that needs word timings
or speaker identification access to the connection. The backend API and the
flow execution worker (`task-execution-worker`) both read the connection from
Eneo, so no environment variables are needed on either. The operator steps are
in the docs-site guide `guides/transcription.mdx`.

Polling uses the step attempt's remaining execution budget. By default a step may
use the whole invocation ceiling (`TASK_EXECUTION_TIMEOUT_SECONDS` minus the
finalization allowance) less what earlier steps of the run consumed; a step's
`timeout_seconds` can lower it, never raise it past the ceiling.

### Service-side requirements (Vemsa)

- Provision a named credential for Eneo: `VEMSA_API_TOKENS=eneo=<secret>`, and
  enter the same secret as the API key of the connection in the admin interface.
  Every space that uses the connection shares this one client identity; size
  `VEMSA_MAX_QUEUED_JOBS_PER_CLIENT` for the combined load.
- The flow execution worker must be able to reach the service over the
  network, and so must the backend API, which runs the connection test.
  Vemsa's reference compose publishes its API on `127.0.0.1`; set `VEMSA_BIND`
  to a private interface, or attach the API to a network the worker shares
  with Vemsa's `compose.eneo.yaml`.
- The service must accept the `timestamp` and `diarize` tasks. A Vemsa
  without `timestamp` refuses the timing jobs, so runs without speaker labels
  keep the model's text without word times (`word_timing` reason
  `unsupported`).
- `VEMSA_MAX_AUDIO_BYTES` (default 2 GiB) must cover Eneo's audio upload
  limit. Eneo sends the original uploaded bytes (mp3 etc.), not decoded wav.
  The parts of one recording (`single_recording`) are the exception: they are
  sent joined as one 16 kHz WAV.

## How it behaves

- **The service** is used by every run of a flow that chose a connected
  service its space can use: it times the words, and labels the speakers
  when the run asks for labels. Otherwise the transcript has no word times
  and no speaker labels. Nothing is chosen for a flow at run time
  (`resolve_speaker_service`): not the space's only service, not a fallback
  when the chosen one becomes unusable. The wizard key
  `transcription_speaker_service` holds the author's choice: absent means no
  choice yet, `null` means none. A chosen service must be usable in the space
  when it is written and when the flow is published, whatever the speaker
  setting. A flow that asks for labels without a choice is refused at publish
  (`flow_speaker_service_not_chosen`). An administrator may mark one
  connection as the organisation's default (`is_default`); a draft that
  transcribes and has made no choice gets it stored as its choice when the
  draft is written, where its space can use it, and a choice of none is never
  replaced. Publishing and running never read the default.
- **The flow's transcription model is always required.** The flow's model
  selection and space governance apply; the selected model writes the text.
- **Job flow**: one multipart `POST /v1/jobs` per audio file, a status poll
  every poll-interval, then `GET /v1/jobs/{id}/result`. A diarize job sends
  `task=diarize`, `diarize=true`, `language`, `model`, `segments` and, when
  set, `max_speakers` and `include_speaker_review`. A timestamp job sends only
  `task=timestamp`, `language`, `model` and `segments`. Submission is retried
  on rate limiting and outages; once a job id exists nothing resubmits.
- **Failures** of the service in a run that labels speakers surface as the
  step error `typed_io_speaker_identification_failed`: the model's text was
  written and the service then failed on it. A failed word timing only records
  `word_timing` (see [How word timing works](#how-word-timing-works)). The run
  error's `details` carry
  `transcription_failure_kind` and, when the service gave one,
  `transcription_service_reason`. A step that runs out of time stays
  `flow_step_timeout`. A cancelled or timed-out step asks the service to stop
  the job (`DELETE /v1/jobs/{id}`, best effort), and the provider-call record
  marks the outcome unknown.
- **No progress signal** exists; a running step shows the usual running
  state until the job completes.

## Local development

Run Vemsa from its repo with the no-GPU fake engine. Vemsa also needs
`VEMSA_DATABASE_URL` pointing at a PostgreSQL database for its job store:

```bash
VEMSA_ENGINE=fake VEMSA_API_TOKENS=eneo=devtoken uv run uvicorn vemsa.main:create_app --factory --port 8000
```

Then in the admin interface under Modeller, Transkription (Talaridentifiering), connect it with the address
`http://host.docker.internal:8000` (the devcontainer reaches the host this way)
and the API key `devtoken`, and give your space access to it.

Publish a flow with an audio runtime input, and run it with any mp3. The
transcript should show the service's canned speaker labels.

## Troubleshooting

| Symptom | Likely cause |
| --- | --- |
| Step fails with `typed_io_speaker_identification_failed` once the model has transcribed, and the connection test shows "Key not accepted" | The connection's API key does not match a token in `VEMSA_API_TOKENS`. |
| Step fails with `flow_step_timeout` | The step's execution budget is exhausted. Check the service's queue depth and worker health, or raise the step's `timeout_seconds` within the deployment ceiling. |
| Step fails with `flow_step_timeout` and `transcription_failure_kind` is `capacity` | The service kept refusing the job until the step's budget ran out: its per-client queue cap is full. Raise `VEMSA_MAX_QUEUED_JOBS_PER_CLIENT` or add service workers. |
| Step fails with `typed_io_speaker_service_unavailable` | The run labels speakers but the flow's chosen service cannot be used; `details.speaker_service_gap` is `picked_unavailable` (the flow's choice is not usable in the space; a choice is never substituted) or `not_chosen` (a version published before the publish refusal existed). |
| Transcript has no speaker labels | Speaker identification is off for the flow (its transcription settings in the new web app), the run chose `speaker_labels: false`, the flow chose no service or its chosen service is not usable in the space (not granted, switched off, or below the space's security classification), or the service ran without diarization support; check its engine tier and extras. Also check the step for an `audio_diarization_skipped` diagnostic: the transcription produced no text to label. |
| Step fails with `typed_io_speaker_identification_failed` and `transcription_failure_kind` is `input` | The service rejected the job with 413 or 422: the audio or the transcript exceeds its size limit (`VEMSA_MAX_AUDIO_BYTES`, `VEMSA_MAX_TRANSCRIPT_BYTES`), or the service does not accept `task=diarize` (an older Vemsa); upgrade it. |
| Step fails with `typed_io_speaker_identification_failed` and the worker logs `remote_transcription.task_unsupported task=diarize` | The service ignored `task=diarize` and transcribed with its own model (a Vemsa that predates the task); Eneo refuses that result because it did not come from the flow's model. Upgrade the service. |
| Transcript has no word times | Read `word_timing` in the step's transcription metadata. Absent: the flow chose no service, or the run labelled speakers. `unavailable`: the chosen service is not usable in the space or not reachable from the worker. `unsupported`: the service does not accept `task=timestamp`; upgrade it. `credentials`: the connection's key is not accepted. `failed` or `no_timings`: read the service's log for the job. |


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
  existing speaker names are applied. A transcript whose segments name no
  speaker renders as plain lines without times, like the text its step kept.
  Confirmed, provisional and explicit
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
