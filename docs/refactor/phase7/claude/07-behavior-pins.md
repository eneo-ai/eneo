## Summary

The list covers most of the right *areas* but ~half the entries are too vague to drop straight into a TDD harness, several PRD-named tests are already designated to own them (so they should be cited explicitly), and at least four high-value pins are missing. The list also doesn't separate "rewrite an existing brittle test" from "add a new behavior pin," which the PRD explicitly cares about (`docs/refactor/prd/PRD-007-testing-strategy.md:106-115`).

**Pins that are too vague to implement (need observable side-effects, not "happy path"):**

- "existing Flow run happy path" / "published flow run through worker execution" — collapse into one pin and define it by observed state: `flow_runs` row transitions `created → running → terminal`, every `flow_step_attempts` row reaches a terminal status, evidence is queryable, audit rows exist for each state transition with correct tenant/actor/action_type, artifacts land in storage. This is exactly what the PRD calls `test_flow_runtime_worker_contract.py` (`PRD-007:99`).
- "external API start-run/poll/result path" — needs explicit sub-pins: upload → create-run with idempotency-key → poll status → step-output read → evidence export → artifact signed-url, plus error contracts (409 idempotency conflict, 404 cross-tenant, 422 schema mismatch). PRD-named owner: `test_flow_consumer_api_contract.py` (`PRD-007:100`).
- "current file handling before deleting top-level file_ids" — must specify cross-step routing: a file uploaded against step-1 never reaches step-2 input resolution; flow-level `file_ids` only flow into steps with `input_source=flow_input`. Owner: `test_flow_step_file_mapping_contract.py` (`PRD-007:101`).
- "terminalization before replacement" — split into (a) timeout, (b) reconciler-after-worker-crash, (c) idempotent double-terminalization, (d) open-attempt rollup. Owner: `test_flow_terminalization_contract.py` (`PRD-007:102`).
- "current permission behavior" — needs an explicit role × action × resource matrix (editor/viewer/admin × create/run/publish/delete × flow/run/evidence). Without it, the typed-policy refactor can flip a deny to an allow silently. Extend `backend/tests/unittests/flows/test_flow_permissions.py` rather than adding a new test.
- "frontend critical route/dialog behavior" — name the dialogs: `FlowRunDialogForm.svelte`, `FlowAIBuilderEditHost.svelte`, `FlowGraphPanel.svelte`, runs/evidence panels. The only existing E2E surface is the placeholder `frontend/apps/web/tests/test.ts`; PRD targets `frontend/apps/web/tests/flows-runtime.spec.ts` (`PRD-007:103`).

**High-value pins missing from the list:**

1. **Idempotency-Key contract on `POST /flows/{id}/runs/`.** The frontend SDK derives a stable key from intent (`frontend/packages/intric-js/src/endpoints/flows.test.js:158-203`). Same key → same run id; differing payload + same key → 409. Highest-blast-radius miss for the consumer-router refactor; not pinned anywhere I can see.
2. **`expected_flow_version` mismatch.** Frontend sends it on every run create (`flows.test.js:96-118`). Stale-version path must reject and not dispatch — easy to silently regress when the publish/version surface changes.
3. **Audit-row coverage tied to the run lifecycle.** CLAUDE.md mandates audit on every state transition; the proposed worker pin doesn't say "audit row per transition." Fold it into `test_flow_runtime_worker_contract.py` so refactors can't silently drop rows.
4. **Cross-tenant 404 on every flow surface (run, evidence, AI Builder session, template asset, runtime files).** `backend/tests/integration/test_multi_tenant_data_isolation_adversarial.py` is general; flows need a narrow pin. Owner: new `test_flow_tenant_isolation_contract.py`.
5. **Output-config secret redaction in evidence exports.** Already exercised in `backend/tests/integration/flows/test_flow_evidence_api_contracts.py:71-76` (Bearer + X-Api-Key in output_config) — but no assertion that secrets are *absent* from the exported JSON; add it before the trace-audit refactor.
6. **Cancel and redispatch state-machine transitions.** `flow_consumer_router` exposes `cancel_flow_run_alias` and `redispatch_flow_run_alias`; neither is in the list. Cancel: running → cancelled + audit. Redispatch: only from terminal failure, not from running.
7. **Evidence `schema_version` literal** — `"flow-evidence-export.v2"` is asserted by the frontend (`flows.test.js:80-83`). Pin in `backend/tests/unit/test_flow_openapi_contract.py` so the JSON contract value can't drift during the export-router split.

**Existing tests to rewrite (cheaper than adding parallel ones):**

- `backend/tests/unittests/flows/test_flow_router.py` (mock-heavy direct endpoint calls, ~all of it) → rewrite as the HTTP-driven `test_flow_consumer_api_contract.py` instead of leaving both. PRD calls this out (`PRD-007:115`).
- `backend/tests/unittests/flows/test_flow_template_asset_compatibility.py` → rewrite as `test_flow_template_asset_canonical.py` covering only the canonical `template-files/` surface — same scenarios, no shim. PRD `:113`.
- `backend/tests/unittests/flows/http_transport/test_normalizer.py` legacy converter branches → drop and replace with one DB-fixture round-trip in `test_flow_http_authored_config_contract.py` proving authored config still produces the runtime shape the normalizer used to. Keep the discriminator tests (`is_authored_config`) since they're cheap. PRD `:114`.
- `backend/tests/unit/test_server_startup_imports.py:74-95, 113-213` (re-export identity asserts) → replace with route-registration + operation-id contract test in `test_flow_openapi_contract.py`. PRD `:110-112`.
- `backend/tests/unittests/flows/test_flow_runtime_builders.py` + `test_flow_run_outcome.py` are already behavior-focused — extend with terminalization scenarios rather than spinning up a fully separate runtime contract file at the unit layer.
- AI Builder SSE pin — extend `backend/tests/integration/flows/test_ai_builder_session_api_regressions.py` rather than authoring a new file; that test already owns SSE-shaped regressions and is thinly covered.

**Owning paths (concrete):**

| Pin | Owner |
|---|---|
| Flow run + worker + audit | `backend/tests/integration/flows/test_flow_runtime_worker_contract.py` (new, PRD-named) |
| Consumer API + idempotency + version-mismatch | `backend/tests/integration/flows/test_flow_consumer_api_contract.py` (new, PRD-named; subsumes much of `unittests/flows/test_flow_router.py`) |
| Step-file mapping cross-step | `backend/tests/integration/flows/test_flow_step_file_mapping_contract.py` (new) |
| Terminalization × 4 modes | `backend/tests/integration/flows/test_flow_terminalization_contract.py` (new) |
| Evidence + artifact + secret redaction | extend `backend/tests/integration/flows/test_flow_evidence_api_contracts.py` |
| Permission matrix | extend `backend/tests/unittests/flows/test_flow_permissions.py` + new `test_flow_tenant_isolation_contract.py` |
| AI Builder create/plan/revise/apply | extend `backend/tests/integration/flows/ai_builder/test_ai_builder_orchestrator_v2.py` and `test_ai_builder_apply_to_draft.py`; SSE → extend `test_ai_builder_session_api_regressions.py` |
| OpenAPI / generated-client | extend `backend/tests/unit/test_flow_openapi_contract.py` and `test_ai_builder_openapi_contract.py`; add a route-coverage cross-check that walks `frontend/packages/intric-js/src/endpoints/flows.ts` URLs against the OpenAPI document |
| Template asset canonical | new `backend/tests/integration/flows/test_flow_template_asset_canonical.py` (rewrite of compatibility test) |
| HTTP authored config E2E | new `backend/tests/integration/flows/test_flow_http_authored_config_contract.py` |
| FlowRunDialog journey | new `frontend/apps/web/tests/flows-runtime.spec.ts` (PRD-named) |
| AI Builder apply confirmation | extend `frontend/apps/web/src/lib/features/flows/ai-builder/FlowAIBuilder.test.ts` |

## Alternatives

- **Tighten in one round vs. iterate.** Brief says one round unless a missing pin protects a load-bearing decision. Idempotency-Key (#1) and version-mismatch (#2) both protect the consumer-router split — those alone justify a second pass to convert "external API start-run/poll/result" into the explicit sub-pin list. The vague "happy path" pins do not — call them under-specified and proceed.
- **Skip frontend pins until backend state contracts settle (PRD-006 dep).** PRD-007:159-161 names PRD-006 as a dep. If state-owner contracts aren't frozen, frontend journey pins risk re-pinning bad behavior; deferring them is cheaper than rewriting.

## Risks or Blind Spots

- The list treats "AI Builder SSE error/done stream" as a single pin, but SSE has two contracts: event ordering (`question → plan → apply → done`) and event payload shape. Splitting the router/service can break either independently.
- No pin for AI Builder **session migration / planning_state JSONB shape**. Migrations exist (`test_builder_planning_state_migration.py`) but the JSONB discipline test (`test_planning_state_jsonb_discipline.py`) is unit-level. Before deleting any planning_state attribute the JSONB shape needs an integration pin so a stale `builder_plans` row can still load — call this out before declaring the cleanup complete.
- The proposed pin "current file handling" probably also needs a **virus-scan / file-size limit / MIME-type** pin if those guards live in the file routes; otherwise deleting top-level `file_ids` could quietly remove the guards. I didn't read `flow_upload_router.py` deeply enough to assert this — flag for confirmation.
- "Generated client/OpenAPI shape before manual TS deletion" — the manual TS at `frontend/packages/intric-js/src/endpoints/flows.ts` already diverges from the spec in subtle ways (e.g. it normalizes file-id ordering on the client side, `flows.test.js:120-140`). A naive shape-only contract test won't catch a server that stops accepting the unsorted form. Pin needs to be "client-emitted requests are accepted by server" not just "schemas match."

## Recommended Next Step

Re-issue the pin list with: (a) the seven missing pins folded in, (b) the six vague pins rewritten with observable side-effects + the PRD-named owning files, (c) a `[rewrite]` vs `[new]` tag on each pin so reviewers can see which pins replace brittle tests instead of layering on top. The PRD already names most owners (`PRD-007:99-104, 110-115`) — citing them removes ambiguity at zero cost.

## Confidence

Medium-high on the pin coverage gaps (read PRD-007, sampled the existing test tree, cross-checked the frontend SDK contract). Lower on the file-upload guard and SSE-payload-shape sub-pins — flagged for confirmation rather than asserted.


Artifact saved to /Users/ccimen/eneo/eneo/.codex/artifacts/ask-claude-phase7-packet-07-behavior-pins-20260428T201555Z.md
