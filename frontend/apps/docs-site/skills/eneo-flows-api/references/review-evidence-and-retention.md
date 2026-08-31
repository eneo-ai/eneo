# Review, evidence, and retention

These surfaces can expose sensitive inputs and outputs. Fetch them only for a user-visible need and handle audit failure explicitly.

## Human review sequence

When status is `awaiting_review`:

1. `GET` the active checkpoint path.
2. Treat HTTP `200` with literal JSON `null` as “no checkpoint is currently open”; keep polling.
3. Render `current_payload_json` and use `review_mode`, `output_type`, and `output_contract` to choose controls.
4. If editing is allowed, send the corrected step value as `edited_value` with `expected_checkpoint_revision`.
5. Approve with the latest revision, or reject with that revision and a required reason of 1–1024 characters.
6. After approval, call resume separately with the latest revision and a stable `Idempotency-Key` for that logical resume.
7. Resume returns `202`; continue polling.

Review endpoint behavior:

| Operation | Idempotency key   | Concurrency rule                |
| --------- | ----------------- | ------------------------------- |
| Edit      | not used; omit it | `expected_checkpoint_revision`  |
| Approve   | not used; omit it | `expected_checkpoint_revision`  |
| Reject    | not used; omit it | revision plus required `reason` |
| Resume    | required          | revision plus stable retry key  |

`edited_value` is the step value, not `current_payload_json` and not a JSON Patch document. Send a string for text output and a JSON object or array for JSON output. Do not edit a `view` checkpoint or file-backed/artifact output; offer approve or reject instead.

On `flow_review_stale_revision`, refetch the active checkpoint. Do not silently overwrite another reviewer's decision. Approval does not resume, and minting a fresh key for every resume retry defeats replay protection.

## Sensitive read boundary

Use these content-free surfaces for routine UI and polling:

- run history/list;
- run status;
- status capabilities.

These omit accepted input, result content, result-file metadata, terminal errors, usage, and outbound-delivery details.

The following are sensitive, audited reads:

- run detail;
- active review content and review mutations;
- evidence and provider-call detail;
- evidence export;
- artifact and input-file signed-URL access.

Required audit persistence is fail-closed. A content request can return `503` rather than disclose content without an audit record. Show a temporary-unavailable state and retry with bounded backoff; do not replace it with cached content from a different run.

## Evidence

Use `GET .../evidence/` for rich inline inspection. Use the paginated provider-calls endpoint for provider lifecycle detail. Evidence access is permission- and policy-gated; a service key may access only its own runs and needs explicit Flow evidence capability.

Exports support redacted and raw detail. Prefer redacted. Raw export requires a meaningful reason and can be further restricted for sensitive classifications. Evidence export is synchronous and can refuse oversized bundles with `413 flow_evidence_export_too_large`; page provider calls instead of attempting an unbounded export.

Do not claim evidence proves which retrieved passage influenced a model. It records retrieval, prompt inclusion, attempts, and outputs; material influence remains unknown.

## Retention and deletion

Flow retention policy is opt-in and hierarchical. It records when history or file content becomes eligible for an administrator-reviewed purge. It does not itself delete data.

For this release:

- no scheduled Flow-owned task automatically purges run history, step history, generated files, or evidence;
- no public admin purge endpoint is exposed;
- an absent policy means keep data until an administrator deliberately configures retention;
- a `review_required` policy still requires a future explicit purge action;
- metadata can outlive file bytes, so clients must handle `availability: content_purged` and HTTP `410` even when viewing retained run records.

Do not tell users that a retention duration guarantees deletion on that date. Describe it as eligibility under the effective organization, space, or Flow policy. Actual purge tooling and approval remain operator concerns outside this runtime consumer skill.

Runtime uploads abandoned before a run are a separate concern: the consumer should delete them explicitly. Once a file is attached to a run, retention and deletion are server-owned.
