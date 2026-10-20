---
name: eneo-flows-api
description: Use this skill when building, debugging or reviewing an application that runs already-published Eneo flows through the runtime API. It covers discovery, uploads, versioned and idempotent run creation, polling, human review, results and signed downloads, transcripts and their corrections, and the error codes. Do not use it for authoring flows (people write flows in Eneo's chat) or for unrelated Eneo APIs.
---

# Eneo Flows API

Build consumers against the published flow runtime contract. Prefer what
the server reports (`GET /flows/{id}/published/` and its `runtime_paths`,
`GET /flows/{id}/run-contract/`, the deployment's `/openapi.json`) over
copied constants.

## Workflow

1. Read the published projection and the run contract; keep
   `published_flow_version`.
2. Build the form from `form_fields`; upload files through
   `POST /flows/{id}/runtime-files/` and bind their ids to file fields.
3. Create one run with `values`, `files`, `expected_flow_version` and an
   `Idempotency-Key`.
4. Poll `…/runs/{run_id}/status/`; read the full run only for content.
5. Resolve `awaiting_review` through the checkpoint endpoints, always with
   `expected_checkpoint_revision`.
6. Mint signed links for `result_files`; read transcripts through
   `…/steps/{step_id}/transcript/` and correct them with
   `PATCH …/transcript-corrections/`.
7. Recover from the error envelope's `code` (see references).

## Authentication

One credential per request: `X-API-Key` for an API key, `Authorization:
Bearer` for a user session. A service key sees published flows and the runs
it started; it never authors and never sees drafts. DELETE needs an
admin-level key. Keep keys on a trusted server.

Read [references/endpoints-and-errors.md](references/endpoints-and-errors.md)
for the path list, the request bodies and the error codes.
