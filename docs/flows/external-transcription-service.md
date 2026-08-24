# External transcription service for flow audio steps

Flow `transcribe_only` steps can delegate transcription to an external
speaker-diarization service (such as [Tolka](https://github.com/eneo-ai/tolka))
instead of the model-registry LiteLLM path. The service transcribes and
diarizes server-side; the flow transcript becomes its rendered, speaker-labeled
output (`[HH:MM:SS - HH:MM:SS] SPEAKER_00: ...` lines).

This is a deployment-level switch, not a catalog entry: either the deployment
has a transcription service configured or it does not. Knowledge uploads and
app runs always use the model-registry path regardless.

## Configuration

Set both variables on the backend API **and** the flow execution worker
(`task-execution-worker`); the worker is what actually calls the service.

| Variable | Required | Default | Meaning |
| --- | --- | --- | --- |
| `FLOW_TRANSCRIPTION_SERVICE_URL` | yes (to enable) | unset | Base URL of the service, without a `/v1` suffix, e.g. `http://tolka:8000`. Unset disables the feature. |
| `FLOW_TRANSCRIPTION_SERVICE_API_KEY` | yes when URL is set | unset | Static bearer token. Startup fails if the URL is set without it. |
| `FLOW_TRANSCRIPTION_SERVICE_SUBMIT_TIMEOUT_SECONDS` | no | 600 | HTTP timeout for the multipart job submission (uploads can be large). |
| `FLOW_TRANSCRIPTION_SERVICE_POLL_INTERVAL_SECONDS` | no | 5.0 | Delay between job-status polls. |
| `FLOW_TRANSCRIPTION_SERVICE_POLL_TIMEOUT_SECONDS` | no | 3300 | Deadline for a job to finish. Must stay below `TASK_EXECUTION_TIMEOUT_SECONDS` (3600) so a waiting step fails before the whole run is reaped; startup enforces this. |
| `FLOW_TRANSCRIPTION_SERVICE_RESULT_TIMEOUT_SECONDS` | no | 120 | HTTP timeout for status and result requests. |

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
  `language` from the flow's transcription config and `diarize=true`), a
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
| Step fails after ~55 minutes | Poll deadline reached; the service is overloaded or the job is stuck. Check the service's queue depth and worker health. |
| Steps fail with rate-limit errors | The service's per-client queue cap is full; raise `TOLKA_MAX_QUEUED_JOBS_PER_CLIENT` or add service workers. |
| Transcript has no speaker labels | The service ran without diarization support; check its engine tier and extras. |
