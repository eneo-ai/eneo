## Summary

The inventory's macro split is sound — relational for queryable / lifecycle / referenced / idempotency-load-bearing facts; JSONB for run-local snapshots and provider blobs. The weak points are:

- It silently treats run-level **input envelopes** (incl. `step_inputs` per-step file_ids) as JSONB-only, even though those mappings *are* queryable concerns (file-deletion impact, retention, rerun lineage).
- It treats `FlowSteps.input_bindings` as JSONB while a separate relational projection (`flow_step_dependencies`) already exists — nothing enforces consistency between them.
- It papers over duplication between `FlowStepAttempts` columns and `provenance_json`.
- **Versioning/corruption story for run-level JSONB and idempotency fingerprints is missing.**

## Alternatives

**Fields proposed JSONB that I'd push to relational (or to relational *projection*):**

1. **Per-step file mappings on a run.** PRD-003 puts `step_inputs.[step_id].file_ids` inside `flow_runs.input_payload_json` (the design table at `PRD-003.md:178-184` calls this the "canonical step-input snapshot"). The inventory says "relational for run step file mappings" but does not tie it to that snapshot. Ground truth needs a `flow_run_step_files (flow_run_id, step_id, file_id, ordinal, tenant_id)` join table:
   - `flow_runs` already CASCADEs from `Files` only via JSONB scan today.
   - File deletion / retention / "which runs reference file X" all need an FK + index.
   - Run validation already enforces ownership (`flow_run_step_inputs.py:131-147`); making it an FK enforces it at the schema level.
   - Keep the JSONB envelope for the **immutable idempotency snapshot**, but the relational table is the source of truth.

2. **Step *output* file artifacts.** Currently `FlowStepResults.output_payload_json` is the only place a generated PDF/DOCX file reference lives (`runtime/template_fill_runtime.py`, `runtime/docx_template_runtime.py`). Downstream steps that consume "the file produced by step N" then have a structural cross-row reference encoded as a JSON blob. Add `flow_run_step_result_files (flow_step_result_id, file_id, role)`. Otherwise PRD-003's DAG-rerun invalidation can't reason about which output files become superseded.

3. **`FlowSteps.input_bindings` ↔ `FlowStepDependencies` consistency.** `input_bindings` (JSONB at `flow_tables.py:140-142`) names parent steps; `FlowStepDependencies` (`flow_tables.py:186-228`) materializes the edges. Nothing prevents a `FlowSteps` row's bindings from drifting from its dependency rows under partial writes. Either:
   - Make `FlowStepDependencies` the source of truth and derive `input_bindings` JSON in repo write paths, or
   - Add a transaction-level invariant in the step repo that the two never split.
   The inventory should explicitly own this — it's the textbook "JSONB shadow of a relational graph" anti-pattern.

4. **Builder review-checkpoint state (the PRD-002 / PRD-003 open question).** Inventory says relational; agree, but be surgical — only extract `state`, `revision`, `reviewer_principal_user_id|api_key_id`, `created_at`, `expected_resume_by`, `next_step_ids` (or even `next_step_id` if single). Keep `original_payload` / `editable_payload` / `edited_payload` as JSONB on that row. PRD-003's checkpoint sketch at `PRD-003.md:252-271` over-flattens.

**Relational proposals that I'd argue are over-modeled or risk redundancy:**

5. **`FlowStepAttempts.provenance_json` vs explicit columns.** `requested_model`, `response_model`, `provider`, `finish_reason`, `provider_response_id`, `num_tokens_input/output` are *already* relational columns on `FlowStepAttempts` (`flow_tables.py:554-560`), and `provenance_json` redundantly carries the same payload (used by `flow_run_evidence.py:233-310`, `flow_run_evidence_bundle.py:153-169`, `flow_run_export_json.py:208/258/659/856/875`). Pick one as canonical. If columns are canonical, JSONB is a debug blob and should be marked as such — including a `corruption-tolerant` parser. If JSONB is canonical, drop the columns. Don't keep two stores updated by hand.

6. **A separate `flow_run_lifecycle_events` projection.** PRD-003 §"lifecycle projection" implies a new owner; if the temptation arises to materialize a per-event projection table, push back. `FlowRuns.status` + `FlowStepAttempts` + outbox already encode the timeline. Read-side projection is fine; persistent duplicate isn't.

7. **`BuilderSessions.conversation`** (`flow_tables.py:692-696`). The inventory keeps it JSONB. Defensible *now* (read by index in `ai_builder_edit_scope.py:159` and turn-counted in the planner), but: it grows unbounded, has no per-message lifecycle, and audit ("show me sessions where the user said X") is impossible. I would not extract today, but I would write the threshold rule into the ADR: **extract to `builder_session_messages` when (a) audit search needs hit, (b) per-message redaction needs hit, or (c) average row exceeds N KB**. Without that trigger documented, this becomes a deferred problem nobody owns.

## Risks or Blind Spots

**Parser / version / corruption gaps the inventory does not address:**

A. **`FlowVersions.definition_json` schema_version lives *inside* the JSONB.** Read at `runtime/executor.py:1449-1450` as `definition_json.get("schema_version")`. PRD-002 acceptance criterion says "Published flow definitions get a first-class schema version or equivalent migration-safe owner" — but the inventory still parks it in JSONB. **Promote `schema_version` to a column on `FlowVersions` alongside `definition_checksum`** (`flow_tables.py:242-243`); the JSONB then becomes truly opaque to the runtime claim path.

B. **No version column on run-level JSONB envelopes.** `FlowRuns.input_payload_json`, `FlowRuns.output_payload_json`, `FlowStepResults.input_payload_json/output_payload_json/model_parameters_json` all carry implicit schemas (form_schema-driven payload structure, `step_inputs` shape). Drift = silent corruption, especially since `request_fingerprint` (`flow_tables.py:355-357`) is computed *over* this shape. Add `input_payload_schema_version` (small int) on `FlowRuns`; refuse reads when null. Same on results table.

C. **No `request_fingerprint_algo_version`.** The fingerprint is part of idempotency (the inventory's own criterion). If canonicalization changes, old hashes silently match new requests they shouldn't, or vice versa. Add a column; bump on parser changes.

D. **`provenance_json`, `tool_calls_metadata`, `edit_result_json`, `metadata_json` — no documented corruption code.** `domain/flow.py:170` types `tool_calls_metadata` as `list | dict | None` which is genuinely heterogeneous, but consumers (`runtime/executor.py:182-183`) silently fall through on parse mismatch. PRD-002 §"Rollback/Recovery" says "reject execution with a named corruption error" — that error code does not exist per-parser. Each owned-JSONB parser must declare its corruption code (e.g. `flow_provenance_corrupt`, `flow_input_payload_corrupt`, `builder_edit_result_corrupt`).

E. **No `jsonb_typeof` shape constraints.** `BuilderPlans.spec_json` and `envelope_json` are `JSONB NOT NULL` (`flow_tables.py:799-801`) — Postgres still allows `'null'::jsonb`, scalars, or arrays. Add `CHECK (jsonb_typeof(spec_json) = 'object')` (and friends) for envelopes the parser assumes are objects. Cheap; catches a real class of bug at insert.

F. **`BuilderPlans.edit_result_json` is mutated mid-flight** (`ai_builder_service.py:601-618` dict-merges into it). That's awkward in JSONB without a `revision` / `version` column on the plan to enforce CAS. Either add `edit_result_revision: int` to `BuilderPlans` or move the mutated fields out.

G. **`FlowTemplateAssets.placeholders`** (`flow_tables.py:280-282`) — JSONB list-of-strings derived from the underlying file. Acceptable as a denormalized cache, but the inventory should call this out as derived (rebuildable from `file_id`) so it's clear that schema drift on the file format means rebuilding the cache, not a corruption stop-the-world.

**Other blind spots:**

- **`BuilderSessions.architecture_hash`** (`flow_tables.py:722-726`) is already an extracted, indexed projection of `planning_state_jsonb`. That's the proven pattern: extract on need. The inventory should name `architecture_hash` as an example of the policy actually being applied — and ask whether `latest_plan_id`, `planning_phase`, `planning_state_version` are similarly stable enough to be extracted (looks like yes; partial extraction is already happening).
- **`FlowRuns.user_id` legacy duplication** with `principal_user_id` (`flow_tables.py:333-344`) — this is a relational vs. relational issue, not JSONB, but the inventory should either commit to deletion-with-migration or freeze as historical-only per PRD-002 acceptance criterion. Leaving both columns active perpetuates a dual-identity authz path.

## Recommended Next Step

Before the inventory closes, add three explicit subsections to it:

1. **"Run-level file mappings"** — name the new `flow_run_step_files` table (input side) and `flow_run_step_result_files` table (output side) as the canonical relational shape; demote `step_inputs` inside `input_payload_json` to the immutable idempotency snapshot. Cite `flow_tables.py:372-377` and `flow_run_step_inputs.py:131-147` as the touchpoints.

2. **"JSONB envelopes that need version + corruption columns"** — enumerate the parsers (`FlowVersions.definition_json`, `FlowRuns.input_payload_json/output_payload_json`, `FlowStepResults.{input,output,model_parameters}_payload_json`, `FlowStepAttempts.provenance_json`, `BuilderPlans.{spec,envelope,edit_result}_json`, `BuilderAttachmentObservations.{observation,deterministic_signals}_json`), and require for each: schema-version column or sentinel, `jsonb_typeof` check, named corruption error code, and explicit "what does the runtime do on parse failure" answer.

3. **"Authoring-graph consistency"** — declare whether `FlowStepDependencies` or `FlowSteps.input_bindings` is the source of truth for step DAG references, and where the invariant is enforced. PRD-003's DAG-driven rerun invalidation depends on this not drifting.

Treat (B) and (D) above as **load-bearing** — without them, idempotency, evidence, and corruption recovery have no schema-level grip.

## Confidence

High on the structural critiques: (1)–(3) and (A)–(D) are grounded in the file references cited and in the explicit text of PRD-002/003. Medium on (5) — the duplication between `FlowStepAttempts` columns and `provenance_json` is real, but I haven't traced whether any consumer treats the JSONB as canonical instead of decorative; an Explore pass on `flow_run_evidence_bundle.py:153-169` and the export modules would settle it. Medium on (6) — depends on whether you intended a lifecycle projection table at all, which the inventory should make explicit either way. Lower on (G) and (η) — those are policy hygiene, not load-bearing schema bugs.


Artifact saved to /Users/ccimen/eneo/eneo/.codex/artifacts/ask-claude-phase7-packet-06-jsonb-relational-20260428T201555Z.md
