# Claude Reconciliation 4 — Provenance Schema Versioning

## Plan Review

- Session: `batch-7a-3-provenance-versioning-plan`
- Final phase: plan verification
- Final verdict: `green`
- Green light: `yes`
- Minimum score: 8

Claude initially challenged the plan on writer/parser drift, marker shape, raw/redacted parity, and manifest status ownership. Codex accepted the findings and tightened the plan:

- Runtime-emitted attempt provenance must round-trip through `FlowAttemptProvenance` before persistence.
- Corruption markers use a strict Pydantic model and a distinct marker schema.
- Bundle normalization produces typed parse results consumed by both serialized export payloads and manifest summary.
- Raw and redacted exports share the `EvidenceBundlePayload` handoff.
- The corruption marker lands only in the export bundle; the typed evidence read model remains unchanged in this slice.
- No historical reader ships without row-count proof or a concrete persisted-data reason.

## Implementation Review Iteration 1

- Session: `batch-7a-3-provenance-versioning-implementation`
- Phase: implementation
- Verdict: `green`
- Green light: `yes`
- Minimum score: 7

Claude returned green but named several accepted cleanup findings.

Accepted findings:

- `_dump_attempt_record` mixed persisted provenance parsing with export-time attempt-row enrichment.
- A parse-result reassignment was no-op and misleading.
- The writer round-trip test validated the model output but did not prove the parser accepts writer output as `tracked`.
- Current-schema validation-failure behavior lacked direct coverage.
- Corruption markers emitted empty `unknown_keys` and mostly uninformative `raw_value_type` fields.
- `_build_attempt_provenance` dumped `LlmProvenance` before final `FlowAttemptProvenance` validation.
- `_dump_attempt_record` returned a redundant shallow copy.

Codex changes:

- Added `_enrich_attempt_provenance_for_export` so parsing remains distinct from export enrichment.
- Removed parse-result mutation and the no-op reassignment.
- Returned the dumped attempt record directly.
- Emitted `unknown_keys` and `raw_value_type` only when informative.
- Passed `LlmProvenance` into final writer validation without an intermediate dump.
- Added a writer/parser handshake assertion with `parse_attempt_provenance(provenance_payload).status == "tracked"`.
- Added a malformed-current-schema test for the Pydantic validation-failure path.
- Added a bounded LLM-section key assertion as the scoped guard while nested provenance sections remain additive.

Deliberate carry-forward:

- Nested provenance sections retain `extra="allow"` in this slice because the plan explicitly keeps nested additivity while hardening the top-level schema. Tool-call, RAG, and artifact sections can tighten in 7A.4-7A.6 when their canonical ownership lands.
- Raw `EvidenceBundle.to_export_payload()` remains computed on demand. Current export rendering calls it once; caching parse results would add another state copy without measured need.

## Implementation Review Iteration 2

- Session: `batch-7a-3-provenance-versioning-implementation`
- Phase: verification
- Verdict: `green`
- Green light: `yes`
- Minimum score: 8

Claude verified the accepted findings were resolved, but the wrapper could not parse the markdown-headed `GREEN_LIGHT` line and exited nonzero. Codex reran the same session with an exact output-contract request.

## Implementation Review Iteration 3

- Session: `batch-7a-3-provenance-versioning-implementation`
- Phase: verification
- Verdict: `green`
- Green light: `yes`
- Minimum score: 8

Claude verified no accepted or partial findings remain. It confirmed:

- parse/enrich separation is closed
- no parse-result mutation remains
- writer/parser handshake coverage is present
- marker noise reduction is present
- validation-failure coverage is present
- no shallow-copy/no-op reassignment remains

## Local Verification After Reconciliation

- `cd backend && uv run pytest tests/unittests/flows/test_flow_run_evidence.py tests/unittests/flows/test_step_attempt_runtime.py tests/integration/flows/test_flow_evidence_api_contracts.py::test_flow_run_evidence_export_returns_redacted_json_attachment tests/integration/flows/test_flow_evidence_api_contracts.py::test_flow_run_evidence_export_marks_corrupt_attempt_provenance -q`: 39 passed.
- `cd backend && uv run pyright src/intric/flows/flow_run_provenance.py src/intric/flows/flow_run_evidence_bundle.py src/intric/flows/flow_run_export_json.py src/intric/flows/runtime/executor.py tests/unittests/flows/test_flow_run_evidence.py tests/unittests/flows/test_step_attempt_runtime.py tests/integration/flows/test_flow_evidence_api_contracts.py`: 0 errors.
- `cd backend && uv run ruff check ...`: all checks passed.
- `cd backend && uv run ruff format --check ...`: 7 files already formatted.
- `cd backend && uv run lint-imports --no-cache`: 3 contracts kept, 0 broken.
- Anti-slippage `rg` across touched source/test files: no matches.
- `git diff --check -- ...`: passed.

Docker/devcontainer note:

- `docker ps --format '{{.Names}}'` was attempted after explicit user permission, but the local Codex tool policy rejected Docker execution before Docker ran: `approval required by policy, but AskForApproval is set to Never`.
