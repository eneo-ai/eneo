## Summary

The premise is right ("delete tests when their target code is intentionally deleted"), but the proposed deletion list is mis-labelled. Three of the six categories are not actually dead, and `test_server_startup_imports.py` and `test_flow_router.py` each contain a substantial layer of security/authorization/audit/idempotency pins underneath a thin layer of shim assertions. Wholesale deletion would silently strip those pins. The fix is to split the files first, then delete only the genuinely-shim tests.

## Alternatives

- **Split before delete.** Move pinning tests out of the proposed-deletion files into renamed files first (e.g. `test_server_startup_imports.py` → keep the OpenAPI/import-side-effect halves, rename to `test_flow_openapi_contract.py`; delete only the layered-package re-export tests once the shims they cover also get deleted in the same commit). This is the cheapest way to avoid sweeping out coverage by accident.
- **"Rewrite as behavior test" before deletion, not after.** For the over-mocked router tests, write the TestClient-based replacements first, get them green for the same scenarios (permissions, scope mismatch, audit logged, audit *not* logged on failure, idempotency forwarding), then delete the mock-heavy originals. Doing it in the opposite order leaves a coverage gap.
- **Treat "legacy" as a name-only signal.** Re-classify `normalize_legacy_config`/`is_authored_config` and `normalizeFlowFormFieldType` as *runtime data-migration* paths, not legacy. Their callers are still on the hot path in production code, so their tests are current-correctness fences.

## Risks or Blind Spots

**1. `backend/tests/unit/test_server_startup_imports.py` — only ~3 of 9 tests are shims.** The other six pin live contracts:
- `test_intric_flows_package_does_not_import_services_as_side_effect` and `..._runtime_package_does_not_import_celery_as_side_effect` are package-init purity invariants — they keep celery out of the web-dyno cold start. Delete these and a future "let me just import this at the top" PR silently regresses startup time and Celery coupling.
- `test_flow_and_ai_builder_routes_have_unique_contracts_and_docs` is a duplicate (method, path) and duplicate `operation_id` detector across the entire `/api/v1/flows*` surface. This is a real bug fence — splits routers across the codebase have produced duplicates before. There is no "shim" content here.
- `test_flow_and_ai_builder_openapi_documents_parameters_and_error_examples` (lines 309-451) pins the public OpenAPI error-code surface: `insufficient_scope` (403), `not_found` (404), `stale_revision` (409), `flow_evidence_audit_logging_failed` (503), `flow_evidence_export_format_not_supported` (400). Several of these codes are compliance-load-bearing — `flow_evidence_audit_logging_failed` (503) pins the "fail closed when audit-log write fails" rule. Delete the file and this contract becomes implicit.

**2. `backend/tests/unittests/flows/test_flow_router.py` — calling this "over-mocked, asserts internal calls" is wrong on close read.** It contains:
- **SSRF guard pin** (`test_test_flow_http_applies_ssrf_runtime_guards`, lines 360-454): preflight URL allow-listing + connected-peer IP assertion. Re-deriving this is non-trivial.
- **Cross-space scope denial** (3 instances: `get_flow_graph`, `create_flow_run`, `create_flow`) — these pin tenancy/scope-filter behavior, which is the P0 isolation invariant.
- **Permission denial paths** for `FLOWS`-without-roles, `FLOWS_VIEW`-without-`FLOWS_AI_BUILDER` etc.
- **Unpublished-flow viewer rule** (`test_flow_run_alias_viewer_cannot_read_unpublished_flow`, lines 1636-1667) — `published_version IS NULL ∧ can_read_flow=False → insufficient_space_permission`. This is the rule that protects authoring-in-progress drafts from viewers.
- **21 audit-log assertions** (positive and negative, including the broker-down case where audit must NOT log).
- **Dispatch failure mode** (`test_dispatch_flow_run_after_commit_marks_failed_on_dispatch_error`, lines 1041-1099): when the broker is down the run is marked FAILED with `flow_dispatch_failed`. Without this, broker brownouts silently leave runs zombie-QUEUED.
- **Idempotency-Key header forwarding** into `create_run`.
- **Service-key principal handling** for run create + the audit log shape.

These are observable contracts. The mocks are heavy because the file substitutes for an integration suite, but the *assertions* are about externally-observable behavior, not implementation detail.

**3. `test_celery_runtime.py` is the only fence on the cross-process Celery task schema.** It pins `kwargs={run_id, flow_id, tenant_id, principal_type, principal_user_id, principal_api_key_id}`. `principal_api_key_id` carries audit-trail attribution for service-key-driven runs. If this kwarg is renamed or dropped, audit attribution silently breaks and there is no other test that catches it.

**4. The "legacy HTTP normalizer" tests cover live code.** `normalize_legacy_config` and `is_authored_config` are imported in `flow_assembler.py`, `flow_http_test_router.py`, `flow_validators_http.py`, and the http_transport package itself (6 production files). This is a runtime data-migration path — every HTTP step that lacks the new `auth` key flows through `normalize_legacy_config`. Pre-production dev tenants and the devcontainer seed already have such configs in JSONB. Deleting these tests removes coverage for: bearer-token inference from `Authorization: Bearer …` headers, case-insensitive header detection, body_template/body_json mode inference, secret-marking of custom headers, default response_format handling, and defensive empty/missing URL handling. All observable.

**5. `template_file_id` is used in 7 production files** (`flow_models.py`, `flow_file_upload_service.py`, ai_builder, runtime, validators). Even if the API surface has moved on to a new alias, `flow_versions.definition_json` is content-addressed and immutable per row — old flows already in tenant DBs will keep emitting `template_file_id`. The "compatibility tests" pin the read-side rule that those snapshots still resolve. Deleting them is a rug-pull on already-persisted data.

**6. Frontend `flowFormSchema.test.ts` line 16-20 ("normalizes legacy text-like field types") is a JSONB-level migration pin.** `flow_versions.definition_json` and `flows.form_fields_json` outlive code edits. Field types `email`, `textarea`, `string` baked into existing rows will still come back from the API. Deleting the test invites someone to delete `normalizeFlowFormFieldType` thinking it's dead — and the editor crashes on existing flows.

**7. "Top-level `file_ids` is legacy" is wrong.** The current canonical run-create payload supports both shapes: `{file_ids: [...]}` for single-step flows and `{step_inputs: {step_id: {file_ids: [...]}}}` for multi-step. See `frontend/packages/intric-js/src/endpoints/flows.test.js` lines 134-140 (sorting), 142-156 (idempotency header), 158-203 (upload-intent idempotency key derivation). Removing top-level `file_ids` tests deletes coverage for the simplest happy path and for the file-ID-sort rule that the upload-intent idempotency-key derivation depends on.

**Behavior pins I think are missing from the proposal's list:**

- **OpenAPI error-code contract:** `flow_evidence_audit_logging_failed` (503 — fail-closed-on-audit-failure), `stale_revision` (409), `flow_evidence_export_format_not_supported` (400), `insufficient_scope` vs `insufficient_tenant_permission` vs `insufficient_space_permission` (the three layers must stay distinct).
- **Negative audit invariants:** "audit MUST NOT log on bad input" and "audit MUST NOT log on dispatch failure." Easy to lose silently.
- **Unpublished-flow viewer rule** (separate from the standard 404/403 — it's a different code path).
- **`manage` vs `view` permission split** for `inspect_flow_template` vs `get_flow_run_contract`.
- **Cross-process Celery task schema** including `principal_api_key_id`.
- **Idempotency chain:** `Idempotency-Key` header forwarding + JS client `deriveUploadIntentIdempotencyKey` + file-ID lexicographic sort. All three together form the idempotency contract; any one missing breaks reproducibility across clients.
- **Worker run-step input shape** (`step_inputs.{step_id}.file_ids`).
- **Three runtime data-migration paths:** legacy field types (`email`/`textarea`/`string`), legacy HTTP `Authorization` header → bearer, legacy `body_template`/`body_json` → typed body.
- **Frontend route guards:** the editor and run dialog permission gates.

## Recommended Next Step

Before any deletion lands, do this in three commits, in this order:

1. **Add the missing behavior pins** (OpenAPI error-code contract, negative audit invariants, JSONB-migration pins, Celery principal contract, idempotency chain, dispatch-failure pin). These should land as TestClient-driven integration tests in `backend/tests/integration/flows/` and JS tests in `intric-js`, so they survive the deletion of the mock-heavy unit tests later.
2. **Split `test_server_startup_imports.py`** into (a) `test_flow_openapi_contract.py` keeping the OpenAPI + duplicate-route + import-side-effect tests, and (b) the genuine shim-reexport tests. Delete (b) only in the same commit that deletes the corresponding shim modules.
3. **Rewrite `test_flow_router.py`** as a TestClient-based integration suite that hits the actual `/api/v1/flows/...` paths. Get every existing assertion (SSRF guard called, audit logged on cancel/redispatch/evidence-view, audit NOT logged on bad config / dispatch failure, scope mismatch → 403, unpublished + viewer-only → 403, idempotency-key forwarded, service-key principal accepted, dispatch-failure marks run FAILED) green in the new file. Only then delete the mock-heavy original. Same pattern for `test_ai_builder_router.py`.

Rename, don't delete: `test_normalizer.py` → `test_http_config_normalizer.py` (drop the "legacy" stigma — the function is on the live data-migration path). Keep `flowFormSchema.test.ts`'s "legacy text-like field types" test verbatim — it's a JSONB-migration pin, not a legacy artifact. Keep `test_celery_runtime.py` — it's the only fence on the cross-process schema.

## Confidence

High on points 1-4 and 7 — I read the test files end-to-end and verified the production callers (`normalize_legacy_config` × 6 prod files, `template_file_id` × 7, `file_ids` × 26, 21 audit assertions in `test_flow_router.py`, `principal_api_key_id` kwarg in `test_celery_runtime.py`).

Medium on point 5 — I could not find a file literally named `test_template_file_id_compatibility.py`; my conclusion that "template_file_id compatibility" tests are alive is inferred from the fact that the symbol is used in 7 production files, including content-addressed JSONB snapshots. If the prompt is referring to a specific file or test name, point me at it and I'll re-read.

Lower on whether the reviewers' "frontend legacy invalid option tests" refers exclusively to the line 16-20 case in `flowFormSchema.test.ts` or to other places — the search surfaced 22 frontend files containing "invalid"/"legacy"/"file_ids"/"template_file_id." If "legacy invalid option" is more specific (e.g. the `select`/`multiselect` option-list normalization at line 22-40), that test is also a forward-compat pin and should be kept for the same reason.


Artifact saved to /Users/ccimen/eneo/eneo/.codex/artifacts/ask-claude-phase7-packet-02-dead-tests-20260428T201424Z.md
