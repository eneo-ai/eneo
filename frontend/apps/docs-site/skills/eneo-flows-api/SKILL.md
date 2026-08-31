---
name: eneo-flows-api
description: Use this skill when building, debugging, or reviewing an application that consumes already-published Eneo Flows through runtime API endpoints, especially when the deployment's private OpenAPI document is unavailable. It guides correct discovery, step-bound uploads, versioned and idempotent run creation, lifecycle polling, human review, typed results, artifacts, evidence, audit and retention boundaries, and typed error recovery. Do not use for Flow AI Builder, draft Flow authoring, retention administration, or unrelated Eneo APIs.
---

# Eneo Flows API

Build consumers against the published Flow runtime contract. Prefer server-reported paths, schemas, capabilities, and limits over copied constants.

## Scope

Use this skill for applications that discover and run an already-published Flow. It covers authentication, uploads, run lifecycle, review checkpoints, typed results, artifacts, evidence, audit behavior, retention, and errors.

Do not use it to create or edit draft Flows, operate Flow AI Builder, administer retention policies, or integrate unrelated Eneo APIs.

## Establish the deployment contract

1. Obtain the deployment origin and API prefix from the operator. `/api/v1` is common but configurable.
2. If the deployment exposes `/openapi.json`, use it to generate types and confirm exact operations. Otherwise use this skill's bundled contract.
3. In either case, treat `GET /flows/{flow_id}/published/`, its `runtime_paths`, and `GET /flows/{flow_id}/run-contract/` as runtime truth. They protect the client from published-version, path, input, and limit drift.
4. Use exactly one credential per request:
   - `Authorization: Bearer <user-access-token>`; or
   - `X-API-Key: <service-key>`.
5. Keep service keys on a trusted server. Never embed one in a browser or mobile binary.

## Follow the runtime workflow

1. Bootstrap from a published Flow ID or list the Space and keep only entries whose `published_version` is non-null. Fetch the selected Flow's published projection and current run contract.
2. Build form and file controls from that contract. Upload through the target step path and bind returned IDs under `step_inputs[step_id].file_ids`.
3. Create one run with `expected_flow_version` and a stable `Idempotency-Key` for identical retries.
4. Poll content-free status from the server's capability table. Resolve `awaiting_review` explicitly; approval and resume are separate operations.
5. Fetch audited detail only when content is needed, branch exhaustively on `result.kind`, authorize artifact downloads with signed URLs, and recover from the error envelope's string `code`.

Read [references/integration-workflow.md](references/integration-workflow.md) before implementing the end-to-end request sequence.

## Select the relevant reference

- For discovery, authentication, request order, polling, and retries, read [references/integration-workflow.md](references/integration-workflow.md).
- For run-contract fields, uploads, form values, result kinds, step outputs, and artifacts, read [references/inputs-and-results.md](references/inputs-and-results.md).
- For human review, evidence, audit boundaries, sensitive content, and retention, read [references/review-evidence-and-retention.md](references/review-evidence-and-retention.md).
- For exact runtime paths and typed error recovery, read [references/endpoints-and-errors.md](references/endpoints-and-errors.md).
- For compact TypeScript request patterns, read [references/typescript-patterns.md](references/typescript-patterns.md).

Load only the references needed for the current task. Do not copy the entire skill into an application's documentation.

## Build the consumer around explicit states

Model these as tagged unions or enums rather than arbitrary strings:

- run status: `queued`, `running`, `awaiting_review`, `completed`, `failed`, `cancelled`;
- final result kind: `inline_text`, `file_backed_text`, `structured`, `artifact`, `outbound_http`;
- artifact availability: at minimum `available` and `content_purged`;
- API error handling: known recovery cases plus an unknown-code fallback.

Do not recreate server-owned response objects as broad maps or `any`. Generate types from live OpenAPI when possible. Without live OpenAPI, define only the fields the consumer uses and validate boundary data before domain logic consumes it.

## Protect the sensitive-content boundary

- Poll `.../status/` for routine progress. It intentionally omits inputs, results, files, terminal errors, usage, and outbound-delivery details.
- Treat run detail, review content, evidence, provider calls, and signed artifact access as sensitive reads. They are audited and may fail closed with `503` if required audit persistence is unavailable.
- Do not assume retention policy means deletion. Flow retention records eligibility and review decisions; this release has no scheduled Flow-owned purge and no public admin purge endpoint.
- Delete abandoned runtime uploads explicitly before run creation. Once attached to a run, their lifecycle belongs to that run.

## Validate the integration

Before presenting code or approving a consumer, verify:

- the base URL does not hardcode a deployment-specific prefix without documenting it;
- one credential is sent and service credentials remain server-side;
- published projection and run contract are fetched before a run is created;
- file controls and validation come from `steps_requiring_input`;
- uploaded IDs are bound to their exact step IDs;
- one creation key is stable across identical retries and changes for a new logical request;
- polling uses the status endpoint and capabilities, including continued polling during `awaiting_review`;
- review edits use `edited_value`, revisions are refreshed after mutations, and approval is followed by resume;
- terminal rendering handles every `result.kind` and purged artifact content;
- error control flow uses `code` with a safe unknown-code branch;
- automated retries cannot duplicate ambiguous provider work or user-visible mutations;
- tests cover stale published versions, duplicate submission, MIME rejection, review races, unknown errors, and unavailable artifact bytes.

When returning an implementation plan or code review, name the selected authentication mode, discovery path, run-contract fields, lifecycle operations, sensitive reads, and recovery behavior. State any deployment assumptions that could not be verified from live OpenAPI.
