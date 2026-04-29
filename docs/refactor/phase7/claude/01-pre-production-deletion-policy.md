I have enough to pressure-test. The Phase 7 deletion policy doc is empty (`docs/refactor/phase7/claude/01-pre-production-deletion-policy.md` is 0 bytes), so I'm reviewing the *proposal*, not authored text. The Agent D inventory at `docs/refactor/phase1/04-dead-and-legacy.md` is the strongest source-of-truth and your brief largely tracks it — but the "delete now / no dual-run" framing flattens distinctions Agent D was careful about.

## Summary

The keep / delete-now / rewrite trichotomy is correct in spirit for never-shipped code (re-exports, identity tests, frontend aliases). It misclassifies anything that touches **persisted row shapes** or **external client contracts**, and it conflates "pre-production product" with "zero existing data." Eneo has dev/test flows, builder sessions, conversation messages, and HTTP step configs persisted right now. Several "shims" are actually live readers of legacy rows, not import bridges. Iter‑1 should split into two strict subsets:
1. Source-only deletes (no persisted data dependency, no public contract): immediate.
2. Anything reachable through DB or `intric-js`: behavior pin + count-query gate + bundled FE/BE rewrite, in one commit.

If iter‑1 keeps that split, the bias is fine. If it doesn't, you'll ship silent breakage in dev environments running existing flows.

## Alternatives

- **Two-tier kill list, not one.** Tier A: pure source compat (frontend `getRedispatchFeedback` alias, `FlowAIBuilderInput.focus` string overload, `flow_repo.py`/`flow_run_repo.py`/`flow_version_repo.py`/`flow_service.py`/`flow_dispatch.py` shims, `_LAZY_EXPORTS` entries, callable re-exports in `flow_consumer_router.py`/`flow_run_router.py`, identity tests at `test_server_startup_imports.py:74-213`, `ai_builder_models.py` wildcard barrel). Tier B: anything where a count query is required first — `normalize_legacy_config`, top-level `file_ids`, `template_file_id`, form-field type normalization (`flow_run_input_payload.py:9-13`), mirrored-instruction cleanup in `FlowEditor.ts:281-324`, `FlowPrincipal.legacy_user_id`. Treating Tier B as "delete now" because the product is pre-prod is the unsafe move.
- **Replace identity tests with import-linter contracts in the same commit, not after.** Otherwise the router-callable surface silently drifts between deletion and replacement.
- **Bundle backend + `intric-js` rewrites for `file_ids` → `step_inputs` into one commit.** The current `flows.js:78-95` `_normalizeRunIntent` still emits `file_ids` and the idempotency key at `flows.js:107-118` hashes over it. A backend that rejects `file_ids` while a JS client still sends it = broken uploads.

## Risks or Blind Spots

- **`normalize_legacy_config` is not test-only — it's a runtime read path.** Per Agent D, persisted `flow_steps.input_config`/`output_config` rows without `auth` would route through it (`http_transport/authored_config.py:65-70`, `flow_assembler.py:104-109`, `flow_service.py:635-644`). Codex's brief listing this as iter‑1 delete is unsafe without a count query in the same diff.
- **Top-level `file_ids` is double-keyed.** Even after request migration, `flow_run_export_json.py:558-568, 621-629` writes `file_ids` into the *historical run lineage*. Don't blanket-delete the field; delete only the request-side adapter (`flow_run_step_inputs.py:104-128`) and pin the export-side keys.
- **`template_file_id` deletion before DB backfill bricks existing drafts.** Backend `flow_service.py:880-919, 931-964` and `flow_file_upload_service.py:382-395`, plus frontend `templateFillConfig.ts:102-125`. Three coordinated touchpoints — none of them survive a source-only delete.
- **`flow_run_service.py` is a behavior shim, not a re-export.** It rebinds the application logger (Agent D §"`flow_run_service.py` logger-rebinding subclass"). Tests patch `intric.flows.flow_run_service.logger`. Deleting without retargeting `test_flow_run_service.py:27` and `test_typed_io_run_service.py:17` silently disables logger assertions.
- **AI Builder conversation messages may contain pre-`message_id` rows.** `ai_builder_question_state.py:76-84, 134-158` falls back to legacy tool-call IDs. If any builder session in dev predates the metadata change, deletion makes that session unloadable.
- **`flow_template_validation.py` shim deletion needs the import-linter rule landed first.** Otherwise the original cycle returns six weeks later as a startup ImportError, not a CI rule failure.
- **`ai_builder_models.py` wildcard re-export** — `from … import *` across three submodules can mask symbol collisions. `rg` for every `ai_builder_models.<Symbol>` callsite (incl. `test_server_startup_imports.py:255-302`) before deletion, not after.
- **Behavior pins mentioned but not specified.** They should include: OpenAPI snapshot of `/api/v1/flows/**`, `_deriveUploadIntentIdempotencyKey` golden vector, `is_authored_config`/`normalize_legacy_config` decision table against a sampled real row, frontend `flowRunRedispatchFeedback` test still importing canonical name. Without these, "pin then delete" is just "delete."
- **`Permission.FLOWS`** (`roles/permissions.py:28-59`) is persisted in role/API-key rows. Brief should explicitly classify "keep" — Agent D does, Codex's summary doesn't.
- **`FlowFactory`** wired through `container.py:520` — not in the brief but worth a "keep" pin so a future cleanup doesn't sweep it.

## Recommended Next Step

Before authoring `01-pre-production-deletion-policy.md`, split the kill list into Tier A (source-only, ship in one commit) and Tier B (count-query-gated, each gets its own commit with: count query → backfill if needed → coordinated FE+BE+codegen delete → import-linter rule replacing identity test). Make "behavior pin" concrete by enumerating the artifacts above (OpenAPI snapshot, idempotency vector, decision-table fixture). Add an explicit "keep" subsection citing `Permission.FLOWS`, `FlowFactory`, `flow_run_export_json.file_ids`, `is_authored_config`, planner `drop_params=True`, AI Builder repair loops, unknown-payload passthrough.

## Confidence

High on the Tier A vs. Tier B split and on each specific persisted-shape risk (Agent D inventory is grep-verifiable and I cross-checked the shim sizes, the `_LAZY_EXPORTS` table, `normalize_legacy_config`, `flow_template_validation.py`, `flow_models.py:410-434`, and `flows.js:48-95`). Medium on AI Builder conversation-row backward compatibility — would need a DB count of `assistant_question_id` provenance to be sure. Low on whether iter‑1 timeline pressure changes the right answer; the brief doesn't say how many commits iter‑1 may span.


Artifact saved to /Users/ccimen/eneo/eneo/.codex/artifacts/ask-claude-phase7-packet-01-pre-production-deletion-20260428T201424Z.md
