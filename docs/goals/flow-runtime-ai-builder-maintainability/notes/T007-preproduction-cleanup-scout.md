# T007 Pre-production Cleanup Scout

## TL;DR

No Flow-wide cleanup Worker should start as a broad deletion pass.
I found no `delete_now` source-code candidate with enough grep/test/fixture/migration proof.
The best cleanup candidates are real, but most are `delete_after_tests` or `delete_after_fixture_cleanup` because current tests or migrations still encode the compatibility behavior.
The next decision should be a Judge task that chooses one narrow cleanup slice or defers cleanup in favor of a typed data-boundary slice.
The highest maintainability win is to avoid preserving pre-production compatibility by default while still refusing blind deletion.

## Scope And Current State

| Area | Result |
|---|---|
| Branch | `feature/refactor-flows-flowai` |
| Worktree | Only unrelated dirty/untracked files observed; this Scout did not touch source or tests. |
| Cleanup gate | Not satisfied for source-wide deletion; individual candidates need replacement tests or fixture/migration proof. |
| Production DB proof | Not required by charter because Flows/Flow AI Builder are pre-production. |
| Local proof required | Grep proof, behavior-test coverage, fixture/migration implication, and canonical owner decision. |

## Cleanup Proof Table

| Candidate | File:line | Intended replacement | Grep proof | Current tests/fixtures affected | Migration/seed implication | Decision |
|---|---:|---|---|---|---|---|
| Legacy form schema type normalization maps `"string"` to `"text"` | `backend/src/intric/flows/flow_validators_form.py:216` | A typed `FlowMetadataV1` / `FlowFormSchemaV1` parser that rejects or migrates old field types at one boundary. | `normalize_legacy_form_schema` is called from `backend/src/intric/flows/application/flow_service.py:92`, `:183`, `:185`, `:332`, and re-exported in `backend/src/intric/flows/flow_validators.py:28`. | `backend/tests/unittests/flows/test_flow_validators.py:474` and `backend/tests/unittests/flows/test_flow_run_input_payload.py:124` explicitly assert the legacy string behavior. | No migration currently backfills or rejects old `metadata_json.form_schema` field types; removing now risks hidden fixture/data drift. | `delete_after_tests` or `delete_after_fixture_cleanup` after the typed metadata/form-schema boundary is selected. |
| Review checkpoint public fallback for missing immutable step snapshots | `backend/src/intric/flows/api/flow_models.py:708` and `backend/src/intric/flows/api/flow_models.py:1511` | New review checkpoints should always include immutable `step_label`, `review_mode`, `output_type`, and `output_contract_json`; public API should not carry pre-snapshot compatibility indefinitely. | `step_snapshot_available` appears in assembler, router docs, evidence bundle, OpenAPI tests, and review/evidence integration tests. | `backend/tests/unittests/flows/test_flow_models.py:231` asserts legacy missing snapshot behavior; `backend/tests/unit/test_flow_openapi_contract.py:574` asserts OpenAPI text mentioning legacy checkpoints. | `backend/alembic/versions/20260502_review_checkpoints.py:90` created the table without snapshot columns; `backend/alembic/versions/20260508_review_checkpoint_contract_snapshot.py:29` adds nullable snapshot columns without backfill. | `delete_after_fixture_cleanup`; needs migration/fixture decision and replacement test that all current checkpoint creation paths populate snapshot fields. |
| `FlowPrincipal.legacy_user_id` and `user_id` mirroring for run/file creation | `backend/src/intric/flows/principal.py:35` | Principal identity should be canonicalized on `principal_type` + `principal_user_id` / `principal_api_key_id`; legacy `user_id` should disappear only after schema/API callers stop reading it. | `legacy_user_id` feeds `run_create_fields()` and `file_owner_fields()` at `backend/src/intric/flows/principal.py:84` and `:92`; Flow run service still writes `user_id` at `backend/src/intric/flows/application/flow_run_service.py:362` and `:585`. | Many run/file tests still assert or provide `user_id`; current consumer API test derives requester id from `run["user_id"]` in `backend/tests/integration/flows/test_flow_consumer_api_contract.py:259`. | `backend/alembic/versions/20260411_flow_run_identity_and_idempotency.py:41` added principal columns and backfilled from `user_id`, but it did not remove legacy columns. | `keep` until a dedicated identity-schema cleanup migrates tests/API payloads and decides whether public `user_id` remains exposed. |
| Runtime `legacy_prompt_binding_used` evidence flag | `backend/src/intric/flows/runtime/step_execution_runtime.py:261` and `backend/src/intric/flows/runtime/step_result_builder.py:10` | If removed, replace with a clearer typed provenance field that describes fallback input-binding behavior without the legacy name. | Used in runtime input resolution, step-result building, JSON export, OpenAPI example, and many executor/evidence tests. | `backend/tests/unittests/flows/test_flow_executor_runtime.py:2583`, `:2696`, and several evidence/export tests assert the flag. | No migration needed for code deletion, but persisted run evidence/export payloads would change and API examples would need an intentional contract update. | `keep`; this is active provenance behavior, not dead code. Rename only in a separate public evidence-contract slice. |
| `FlowRepository.save_step_result` branch for `result.step_id is None` legacy updates | `backend/src/intric/flows/infrastructure/flow_repo.py:577` | Step result persistence should require the canonical `(flow_run_id, step_id, attempt_no)` identity unless a current domain path proves otherwise. | Production executor calls save claimed results with step ids; grep shows the branch and one direct integration test around missing row behavior. | `backend/tests/integration/flows/test_flow_repository.py:297` asserts the legacy update branch raises when a missing row is updated. | Needs local schema/fixture proof that no seeded or persisted `flow_step_results.step_id IS NULL` rows are required. | `delete_after_tests`; promising narrow cleanup candidate after a Judge validates DB/schema assumptions and replaces the legacy-row test with canonical identity behavior. |
| AI Builder planner/orchestrator compatibility fields: `required_slot_names` and `has_new_evidence` fail-open language | `backend/src/intric/flows/ai_builder/ai_builder_planner.py:1237` and `backend/src/intric/flows/ai_builder/ai_builder_orchestrator.py:267` | `PlannerActionPolicy`, `asked_question_ids`, and `question_ids_with_new_evidence` may become the only server-owned guardrail inputs, but this needs an AI Builder-specific Scout/Judge decision. | `required_slot_names` appears across planner/orchestrator tests; `has_new_evidence` still appears in context derivation and guardrail tests. | `backend/tests/unittests/flows/ai_builder/test_ai_builder_planner_send_message.py:869` asserts resolved core slots are excluded from `required_slot_names`; `:1289` documents duplicate-question guard derivation. | No migration; primarily test/caller cleanup. Needs care because these fields still protect production guardrails today. | `keep` for this cleanup lane; revisit under a dedicated AI Builder guardrail/material-efficiency Scout. |
| Question catalog slot-key to legacy question-id bridge | `backend/src/intric/flows/ai_builder/question_catalog.py:23` | One canonical question id vocabulary, ideally slot-name based, with explicit compatibility map removed after downstream answer matching is migrated. | Question ids are used broadly in prompt, action policy, semantic adjudication, conversation compaction, and tests. | Multiple AI Builder tests assert canonicalization and legacy question-id normalization. | Conversation history may contain old question ids; cleanup needs a persisted-message compatibility decision. | `keep`; not safe as an early cleanup. |
| Flow Capability Manifest parity with legacy validators and rule vocabulary | `backend/src/intric/flows/flow_capability_manifest.py:364`, `:472`, `:646`, `:667` | The manifest should become the canonical engine capability/rule source; legacy string-table parity tests can then be deleted. | `test_flow_capability_manifest.py` imports legacy functions and asserts parity across chain compatibility, output artifact mode, citation capability, and MCP policy. | `backend/tests/unittests/flows/test_flow_capability_manifest.py:208`, `:320`, `:347`, `:417`, and `:823` intentionally lock parity. | No migration, but deleting now risks silent drift between old validators and the new typed manifest before ownership flips. | `keep` for now; later `delete_after_tests` only after Judge chooses FCM as canonical owner and migrates callers away from legacy validators. |
| Template file selection legacy flow-asset fallback | `backend/tests/unittests/flows/test_flow_template_asset_compatibility.py:62` | Template files should be represented by flow assets, not legacy `output_config.template_file_id` fallback. | Compatibility tests cover publishing, promotion, missing-file errors, and run-contract readiness for legacy template selection. | Existing tests at `backend/tests/unittests/flows/test_flow_template_asset_compatibility.py:62`, `:145`, `:234`, and `:284` protect the fallback. | Needs fixture cleanup and likely published-definition/template-asset boundary decision. | `delete_after_fixture_cleanup`; good later cleanup after template asset model is canonical and public run-contract tests cover current behavior. |
| Comment-only AI slop and stale compatibility prose | Examples: `backend/src/intric/flows/ai_builder/question_catalog.py:1`, `backend/src/intric/flows/flow_capability_manifest.py:364` | Prefer names, tests, and narrow invariant comments. Delete narrative history when it no longer explains a live invariant. | Grep finds many comments with `legacy`, `temporary`, and planning-ish explanation. | Comment changes can destabilize tests if they assert docs/OpenAPI descriptions; otherwise low test impact. | No migration. | `delete_now` only for comments in files already touched by another approved Worker; do not run a source-wide comment cleanup yet. |

## Tests To Delete Or Collapse After Replacement Coverage

| Test | Current behavior protected | Delete/collapse condition |
|---|---|---|
| `backend/tests/unittests/flows/test_flow_validators.py:474` | Legacy `"string"` form field type normalization. | Delete after a typed form-schema parser either rejects `"string"` with a documented error or a migration converts all local fixtures. |
| `backend/tests/unittests/flows/test_flow_run_input_payload.py:124` | Runtime payload accepts legacy `"string"` form fields. | Collapse into typed metadata parser tests after form schema ownership moves out of dict-shaped metadata readers. |
| `backend/tests/unittests/flows/test_flow_models.py:231` | Review checkpoint public model tolerates missing step snapshots. | Delete after migration/fixture cleanup proves every current checkpoint creation path stores snapshots. |
| `backend/tests/unit/test_flow_openapi_contract.py:574` | OpenAPI tells consumers about legacy missing-snapshot checkpoints. | Rewrite after the public contract no longer exposes legacy checkpoint semantics. |
| `backend/tests/integration/flows/test_flow_repository.py:297` | `save_step_result` legacy `step_id is None` update branch. | Delete after a Worker proves canonical step-result identity is always present and adds a test for rejecting/avoiding missing step ids earlier. |
| AI Builder guardrail tests asserting `required_slot_names` compatibility | Older non-core required-slot surface. | Do not delete from this cleanup lane; revisit only after an AI Builder Scout proves action-policy callers and question-specific evidence fully replace the surface. |
| Flow capability manifest parity tests against legacy validators | Manifest mirrors legacy rule owners. | Replace when the manifest becomes the source of truth and old validator callers are removed. |

## Recommended Next Decision

Do not activate T008 as a generic cleanup Worker yet. The cleanup entry gate is not met for source-wide deletion, and there is no safe code `delete_now` candidate with enough proof.

The next Judge should choose one of these:

1. A narrow cleanup Worker for `FlowRepository.save_step_result` legacy `step_id is None` update behavior if DB/schema proof confirms no current rows require it.
2. A typed boundary Worker for `FlowMetadataV1` / `FlowFormSchemaV1`, because it would unlock deletion of legacy form normalization and reduce dict-shaped metadata readers.
3. A typed published-definition/template-asset boundary Scout if the team wants to delete template fallback paths next.

My recommendation: choose the typed metadata/form-schema boundary before deleting the form normalization. It gives a canonical owner and makes later cleanup safer than removing compatibility from untyped JSON readers.

## Maintainability Assessment

| Dimension | Score | Reason |
|---|---:|---|
| Canonical ownership clarity | 7/10 | Cleanup candidates are mapped to likely owners, but form metadata and capability-rule ownership are still split. |
| Deletion readiness | 5/10 | Most candidates are real but currently protected by tests or migrations. |
| Fear-of-change reduction | 8/10 | The table prevents broad cleanup and gives concrete next slices. |
| False-positive risk | 7/10 | Grep found many `legacy` hits outside Flow; this Scout filtered to Flow/AI Builder evidence only. |
| Recommended immediate implementation confidence | Medium | Good candidate set, but source deletion should wait for Judge and, where needed, Claude with a 15-20 minute timeout. |

## Verification Performed

- `git status --short --branch`
- Targeted `rg` over `backend/src/intric/flows`, `backend/tests`, and `backend/alembic/versions`
- Targeted file reads with line numbers for Flow validators, review checkpoints, principal identity, runtime evidence, AI Builder guardrails, capability manifest, repository step-result persistence, and relevant tests/migrations
