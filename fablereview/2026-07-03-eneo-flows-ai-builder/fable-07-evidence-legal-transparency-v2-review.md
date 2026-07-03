# Fable 07 v2: Evidence And Legal Transparency Review

I've now read the full evidence chain — capture (executor/step runtime/RAG/template/HTTP), persistence (tables/repos), retention (debug redaction, tombstones, purge), assembly (bundle/debug export/manifest/summary), policy/access, API surface, and the test inventory. Everything needed for the review is verified against source. Here is the complete deliverable:

---

# Fable 07 v2 — Flow Evidence, Provenance, and Legal Transparency Export Review

Reviewer: Claude (Fable 5) · Date: 2026-07-03 · Repo: `/Users/ccimen/eneo/eneo-flows-clean` @ `refactor/flows-clean`

## TL;DR

1. **The export skeleton is genuinely strong** — typed `flow-evidence-export.v7` manifest, content hash, schema-versioned attempt provenance with corrupt/purged/not-tracked markers, retention tombstones with honest notes, checksummed artifact manifest with RESTRICT-protected file references, and fail-closed audit on every evidence access (`flow_run_export_json.py:105-171`, `flow_run_provenance.py:295-387`, `flow_trace_audit.py:24-60`).
2. **The biggest disclosure hole is rerun:** accepting a rerun nulls the step result's full input, output, effective prompt, and model parameters (`flow_run_rerun_repo.py:89-102`) and replaces the run's input envelope (`flow_run_rerun_repo.py:370-390`); superseded attempts keep only ≤16KB previews — and usually **no output text at all**, because `raw_completion_text` is captured only when citations were observed (`step_execution_runtime.py:1170-1175`). The export does not say any of this. Meanwhile `flow_step_attempts.input_payload_json`/`output_payload_json` — the obvious home for surviving per-attempt evidence — exist and are **never written** (`flow_tables.py:1125-1133`).
3. **Model-setting traceability is subtly misleading:** persisted `model_parameters_json` snapshots the assistant's *configured* kwargs, not the kwargs actually sent — the runtime silently adds `response_format={"type":"json_object"}` and can silently retry a second provider call with the original kwargs, none of which is recorded (`step_execution_runtime.py:961-991, 1030-1043, 1156`).
4. **Outbound-transfer disclosure is split-brain:** HTTP/webhook request evidence (resolved URL, status, timing, delivery attempts) lives only in a **best-effort** audit log that swallows failures and stores host+path only (`http_audit.py:42-96`); `flow_run_webhook_deliveries` rows are not in the evidence bundle at all, and run purge deletes them (`flow_run_history_purge_repo.py:94-97`).
5. Owner reconciliation: there is **one** canonical assembly chain (`FlowRunEvidenceService` → `build_evidence_bundle` → `render_evidence_json_export`), not two competing stories — but the embedded `debug-export.v2` is a weakly-typed (`step_id: Any`) secondary projection whose numbers the typed summary re-derives with drifting fallbacks (`flow_run_evidence.py:39-51`, `flow_run_export_json.py:381-406, 471-479`), and the manifest advertises a retention state (`redacted_for_deletion`) that no producer can ever write (`flow_retention_tombstone.py:19-21, 69-97`).

---

## Ratings

Per `docs/engineering/maintainability-standards.md`, overall = minimum dimension.

| Dimension | Score | Basis |
|---|---:|---|
| Legal transparency readiness | **6** | Manifest/tombstone/hash machinery is real; rerun evidence loss, prompt-preview caps, missing outbound-call disclosure, and missing idempotency metadata keep "show everything we reasonably can" untrue today |
| Prompt/model-setting traceability | 6 | Pre-dispatch `attempt_start` + finish-time provenance is the right shape; configured-vs-sent kwargs divergence and the invisible JSON-mode retry undermine it |
| RAG/chunk traceability | 6 | Retrieval + prompt-inclusion tracked with *honest* limitation notes (`flow_run_provenance.py:235-246`); chunk text is 200-char snippets with caps, no stable chunk identity, no embedding/chunking config |
| File/template provenance | 8 | Checksums everywhere, per-attempt file rows, RESTRICT FKs (`flow_tables.py:1549-1553, 1640-1644`), template asset id+checksum chain (`template_fill_runtime.py:217-223`), fail-closed template purge |
| Retention/purge explainability | 7 | Tombstones + "indistinguishable from never-tracked" honesty (`flow_run_export_json.py:70-73`); one dead state, and pre-tombstone rows are honestly ambiguous |
| Schema ownership | 6 | One assembly owner and typed manifest; but three overlapping step projections, duplicated derivations, `extra=allow` provenance sections, and dead attempt payload columns |
| API/export consumer clarity | 7 | Two documented endpoints, tiered capability policy, raw-reason gate, typed response with a *documented* open `bundle` (`flow_models.py:2033-2038`); view/export actor-enrichment asymmetry |
| Testability | 7 | Dense export-shape/policy/corruption tests; no end-to-end rerun-survival, redaction→export, or captured-vs-sent tests |

Overall: **6** — ship-adjacent, but the P1 findings below must land before this export is presented as the legal disclosure artifact.

---

## Disclosure Inventory Matrix

Legend — **Captured**: in persistent state; **Exported**: in evidence bundle/export; **Recon**: reconstructable only indirectly; **Retention risk**: lost before full purge or lost on lifecycle events; **Owner**: schema owner; **Tests**: tests proving it.

| # | Disclosure item | Captured | Exported | Recon only | Retention risk | Owner | Tests |
|---|---|---|---|---|---|---|---|
| 1 | Flow id/version + exact published snapshot | ✅ `flow_runs.flow_version` FK-pinned to `flow_versions` (`flow_tables.py:793-798`) | ✅ `definition_snapshot` + checksum (`flow_run_evidence_bundle.py:76`, `flow_run_evidence.py:164-169`) — shipped **twice** (F-9) | — | Low (version RESTRICT) | `FlowVersion` (typed row, JSONB definition) | export tests (`test_flow_run_evidence.py:925`) |
| 2 | Step ids/names/order/types, exact step spec | ✅ inside definition snapshot | ✅ snapshot + `debug_export.steps` + `summary.step_overview` | — | Low | snapshot = hidden JSON; projections weakly typed (F-8) | multiple |
| 3 | Original request + idempotency metadata | ✅ `flow_runs.idempotency_key`, `request_fingerprint` (`flow_tables.py:723-730`) | ❌ **not exported** — `FlowRun` domain model omits both (`domain/flow.py:178-204`) | fingerprint not invertible | Run purge | `FlowRuns` row | ❌ none |
| 4 | Runtime input envelope after validation | ✅ `flow_runs.input_payload_json` + per-step `runtime_input` metadata | ✅ run section + typed relational file metadata (`flow_run_evidence_bundle.py:396-424`) | — | **Replaced by rerun override, original not preserved** (F-1b); step copy cleared by debug redaction | envelope helpers typed (`flow_run_input_envelope.py`); payload hidden JSON | `test_evidence_bundle_export_uses_relational_runtime_file_metadata` (:2756) |
| 5 | Uploaded files (id/name/mime/size/checksum/extraction status) | ✅ `FlowRunStepInputFileMetadata` (`flow_run_step_input_file.py:11-35`), RESTRICT FKs | ✅ per step result | — | Rows cascade at run purge; underlying upload is **flow-scoped and outlives run retention** (`flow_tables.py:534-614`) — over-retention question | typed | service test (:70) |
| 6 | Template assets + generated result files | ✅ template id/file/checksum/version (`template_fill_runtime.py:217-223`); artifacts with sha256 (`output_runtime.py:118`) | ✅ artifact manifest + availability (`flow_run_export_json.py:289-308`) | template *content* after asset purge: checksum-only | Fail-closed template purge; artifact rows RESTRICT | typed manifest item | retention integration (:814-925) |
| 7 | Resolved `input_bindings.question` | ✅ binding template in snapshot; resolved text = step input text; `used_question_binding` flag | ✅ + lineage expressions (`flow_run_export_json.py:1073-1133`) | — | Cleared by debug redaction; **lost on rerun** | lineage summary weakly typed (JsonValue) | `:2485` |
| 8 | Resolved underlag/source material per step | ✅ `input_payload_json.text/source_text` (full text) (`step_result_builder.py:39-63`) | ✅ raw; redacted masks only key/pattern hits | — | **Current attempt only** (F-1); debug redaction clears | hidden JSON | shape tests only |
| 9 | Exact prompt/messages sent to model | ⚠️ `effective_prompt` full on *current* step result (`flow_tables.py:881`); ≤16KB preview + sha256 on attempt (`executor.py:418`, `flow_run_provenance.py:24, 249-261`); **final message array assembled in assistant layer, never captured** (`step_execution_runtime.py:331-341`) | ✅ what exists | full message array: ❌ not reconstructable | Prior attempts preview-only; debug redaction clears column | `LlmProvenance` (extra=allow) | truncation test (:594) |
| 10 | Model provider/id/version | ✅ requested/response model, provider, `provider_response_id` on attempt (`flow_tables.py:1118-1122`) | ✅ (+ silent backfill enrichment, F-7) | deployment name: provider string only | attempt provenance replaced at debug redaction; columns survive | typed columns | many |
| 11 | Temperature + completion kwargs | ⚠️ `model_parameters_json` = assistant-configured kwargs + `parameter_semantics` (`step_execution_runtime.py:513-528`); pre-dispatch snapshot (`flow_run_provenance.py:66-85`) | ✅ | **actually-sent kwargs (json-mode override/retry): not captured** (F-2) | debug redaction clears | snapshot typed; full params dict-shaped | semantics tests (:2849) |
| 12 | Token limits/usage | ✅ per-attempt tokens (`executor.py:1731-1732`); estimate pre-dispatch | ✅ + run rollup (`flow_run_evidence.py:197-209`) | — | Low | typed | `:830` |
| 13 | RAG query, sources, chunks, scores | ⚠️ query = composed step input (not labeled as query); source ids + per-source ≤5 chunk snippets (200 chars) + rounded scores + truncation flags (`rag_retrieval.py:73-155`, `rag_metadata.py:60-146`); prompt-inclusion trace (`step_execution_runtime.py:531-583`) | ✅ with honest tracking states (`flow_run_export_json.py:638-677`) | **full chunk text**: only if info-blob still exists and chunking unchanged; embedding model/chunk config: ❌ | references cleared by debug redaction (tombstoned) | `RagProvenance` extra=allow (hidden JSON) | extensive (:1245-1494) |
| 14 | Tool/MCP/external HTTP calls | ⚠️ tool_calls ≤16KB JSON preview (`executor.py:420-422`); MCP config in snapshot, **MCP invocations not captured**; HTTP: response text persisted as step input, **resolved URL/headers/body not in run evidence** (`executor.py:460-468`, `http_orchestration.py:154-314`) | ⚠️ partial | resolved URL: template + envelope re-interpolation | HTTP audit best-effort, host+path only (F-3) | provenance sections extra=allow | ❌ nothing on HTTP evidence |
| 15 | Timestamps (create/step/provider/review/rerun/export) | ✅ run created/started/finished; step + attempt started/finished; checkpoint decision timestamps (`domain/flow.py:410-415`); `exported_at` | ✅ | provider-call start/end: attempt-level only | `debug_export` run duration uses `updated_at` (F-10) | typed | partial |
| 16 | Actor (user / service key / API key / tenant) | ✅ principal columns + `runtime_service_permission` (`flow_tables.py:696-716`) | ✅ ids; human-readable service-principal enrichment **only on the view endpoint** (`flow_run_evidence_router.py:145`, absent in export) | — | **`created_by_api_key_id` SET NULL on key deletion** (`flow_tables.py:709-712`) — attribution decays (F-6) | typed | presenter test (:231) |
| 17 | Errors/retries/failures/terminalization | ✅ run `error_json`, step + attempt error codes, rerun lineage, superseded links | ✅ | generic exceptions: logs only (Fable 06); **json-mode retry invisible** (F-2) | attempt provenance marker replaces detail at debug redaction | typed enums + hidden error JSON | terminalization contract tests |
| 18 | Step outputs, final output, artifacts | ✅ full output on current step result; run output = last completed step (`run_outcome.py:71-77`) | ✅ + typed final-output summary | superseded outputs: ❌ (F-1) | rerun reset; debug redaction keeps outputs (only clears `template_fill_debug`) (`data_retention_service.py:1015-1021`) | hidden JSON payloads, typed summary | `:1791` |
| 19 | Redactions & omissions + reasons | ✅ masked paths/fields/reasons + policy version (`flow_run_redaction.py:9, 54-58`) | ✅ | — | — | typed | `:1074-1244` |
| 20 | Retention/purge explanation | ✅ schema-versioned tombstones (`flow_retention_tombstone.py:50-100`) | ✅ manifest retention summary + honest pre-tracking note | — | one dead state (F-5); webhook/audit-outbox deletion at purge is unexplained | typed | `:1125-1218` + retention integration |
| 21 | Review checkpoints (pause/edit/resume) | ✅ original vs current payloads, decider principal, per-state timestamps (`domain/flow.py:370-415`) | ✅ with `output_changed` tri-state + `resume_key_present` instead of the key (`flow_run_evidence_bundle.py:30-34, 427-453`) | — | checkpoints deleted at run purge (rows, not summaries, are the evidence) | typed | `:1494-1783`, integration `:837-1082` |

---

## Evidence / Export Owner Reconciliation

**The known lead resolves cleanly: there is one disclosure pipeline, not two.** `FlowRunEvidenceService` is the only consumer of `build_evidence_bundle` / `redact_evidence_bundle` / `render_evidence_json_export` (grep-verified, single import chain into `flow_run_evidence_service.py:17-21`). `debug-export.v2` (`flow_run_evidence.py:20`) is not a competing endpoint — it is a projection **embedded inside** the bundle (`flow_run_evidence_bundle.py:198-206`) and inside the typed view response (`flow_models.py:1649`). The strict `flow-evidence-export.v7` manifest wraps the bundle and hashes it (`flow_run_export_json.py:114-120, 186-213`). This is deliberate and tested (`test_render_evidence_json_export_adds_manifest_and_summary`, `test_flow_run_evidence.py:925`).

**What is *not* clean is internal to that one export:** the same payload carries three step projections — `bundle.step_results` (records), `bundle.debug_export.steps` (definition-shaped), `summary.step_overview` (typed) — and the summary re-derives debug-export numbers with fallback recomputation that has *different semantics*: `_collect_models_used` in the debug export falls back to provenance `model_parameters.model_name` (`flow_run_evidence.py:333-351`) while the summary's local fallback does not (`flow_run_export_json.py:471-479`); `steps_count`/`attempts_count` fall back to independent counts (`flow_run_export_json.py:381-406`). Today the debug summary is always present so the fallbacks are dead-but-load-bearing-looking; the drift risk is real the day someone reorders assembly.

**Canonical owner naming:**

- **Export/manifest semantics owner:** `flow_run_evidence_export_manifest.py` + `flow_run_export_json.render_evidence_json_export` — exists, typed, correct home.
- **Capture-contract owner: missing.** What must be recorded per attempt is scattered across `executor._build_attempt_provenance` (`executor.py:409-469`), `step_result_builder.py`, `rag_retrieval.py`, `template_fill_runtime.py`, and the assistant layer. `FlowAttemptProvenance` is the de-facto contract, but eleven of its twelve sections are `extra="allow"` empty models (`flow_run_provenance.py:88-125`) — i.e., hidden JSON contracts wearing Pydantic hats. There is no single place a reviewer can read to answer "what is Eneo committed to capturing."

**Schema classification:**

| Schema | Class | Evidence |
|---|---|---|
| `EvidenceExportManifest`, `EvidenceExportSummary`, `EvidenceArtifactManifestItem`, `EvidenceStepReviewImpact` | **typed-owned** (`extra=forbid`) | `flow_run_evidence_export_manifest.py:90-113`, `flow_run_evidence_export_summary.py:158-181` |
| `EvidenceRetentionStateSummary` | typed but `extra="allow"` — the one forward-compat outlier | `flow_run_evidence_export_manifest.py:36` |
| `AttemptStartProvenance`, `ModelParameterSnapshot`, `PayloadPreview`, corruption/retention markers | **typed-owned** | `flow_run_provenance.py:48-85, 151-166` |
| `LlmProvenance`, `RagProvenance`, `HttpProvenance`, `TemplateProvenance`, `RuntimeInputProvenance`, `TranscriptionProvenance`, `ArtifactProvenance`, `AgenticProvenance`, `GuardsProvenance`, `McpProvenance`, `CitationsProvenance` | **hidden JSON** (`extra=allow`, no declared fields except llm) | `flow_run_provenance.py:57-125` |
| `DebugStepProjection` (`step_id: Any`, `step_order: Any`, `dict[str, Any]` groups) | **`Any`/dict-shaped** | `flow_run_evidence.py:39-51` |
| `EvidenceStepInputLineageSummary`, `EvidenceStepKnowledgeRetrievalSummary` (fields typed `JsonValue`) | typed shell, dict-shaped content | `flow_run_evidence_export_summary.py:56-88` |
| `step_results.input_payload_json` / `output_payload_json`, `rag` metadata, `runtime_input` metadata | **hidden JSONB**, hand-built | `step_result_builder.py:39-63`, `rag_retrieval.py:39-58` |
| Export `bundle` + `redaction` sections | `dict[str, Any]` — but **documented** as the open hashed object | `flow_models.py:2032-2038` |

**Verdict on the lead:** deliberate, partially tested, and the manifest/summary honestly points consumers at the typed layer. The debug projection is *not* suitable as a legal surface on its own — and the code does not present it as one. The real fixes are the drifting duplicate derivations (F-8) and the missing capture contract (F-4), not an owner war.

---

## Ranked Findings

### F-1 · P1 (blocker for the legal-disclosure story) — Rerun destroys the only full record of the superseded execution, and the export doesn't say so
- **Problem:** Rerun acceptance resets the step result row wholesale — `input_payload_json`, `output_payload_json`, `effective_prompt`, `model_parameters_json`, tokens, timestamps all → NULL (`flow_run_rerun_repo.py:89-102`), for the rerun root *and every invalidated downstream step*. The run-level input envelope is likewise replaced when an inline override is given (`flow_run_rerun_repo.py:370-390`); the operation row stores the *override* (`:274`), not the prior envelope. What survives on the superseded attempt is `provenance_json`: effective-prompt *preview* (≤16KB + sha256), rag/runtime-input/transcription metadata, model columns — but **no resolved input text** (only `attempt_start.input_text_length`, `flow_run_provenance.py:75-85`) and **usually no output text**, since `raw_completion_text` is only set when a citation sidecar observed citations (`step_execution_runtime.py:1170-1175`). The attempt table has `input_payload_json`/`output_payload_json` columns purpose-built for this that nothing writes (`flow_tables.py:1125-1133`; writers at `flow_run_repo.py:888-938, 1016-1097` never set them).
- **Why it matters:** the stated legal need includes reviewed and rerun runs. Today, one rerun of step 1 in a 3-step flow makes it impossible to disclose what the *original* execution read and produced — while the export still renders a complete-looking bundle with no "superseded evidence is preview-only" marker. If a run is rerun *because* its output is disputed, the disputed output is the thing that just got destroyed.
- **Owner/fix:** decide once, in `FlowRunRepository.finish_attempt`: **(a)** persist the attempt's input/output payloads (bounded — reuse `PayloadPreview` normalization with a larger cap, or full payload given debug retention already bounds lifetime), making attempts the append-only evidence spine reruns already link via `predecessor/superseded_by`; or **(b)** delete the two dead columns and add an explicit `superseded_evidence: "preview_only"` marker per superseded attempt in the export manifest. (a) is the honest fix; (b) is the honest cheap fix. Do not keep the current silent middle.
- **Acceptance criteria:** after rerun-with-override of step 1 of 2, the raw export either contains the original resolved input + output of attempt 1 verbatim, or the manifest explicitly enumerates them as `not_captured_superseded`. The pre-override run input envelope is recoverable (persist prior envelope on the operation row, mirroring how `root_step_input_override` is already stored).
- **Tests:** integration — run → complete → rerun with inline override → raw export; assert superseded attempt disclosure per chosen option; assert original envelope disclosure.
- **Risk/trade-off:** option (a) grows JSONB per attempt (bounded by debug retention and rerun frequency ≪ run count); it also concentrates more sensitive text in attempts, which the existing debug-redaction path already clears (`data_retention_service.py:882-908` would need to also clear the new columns — extend the same sweep). **Confidence: high** (reset values, non-writing repo methods, and the citation-gated raw text all read directly).

### F-2 · P1 — Recorded model parameters are the *configured* parameters, not the *sent* parameters; the JSON-mode retry is a second, invisible provider call
- **Problem:** `StepExecutionOutput.model_parameters_json = deps.effective_model_parameters(prepared.assistant)` (`step_execution_runtime.py:1156`) dumps `assistant.completion_model_kwargs` (`:513-528`). But the actual call may use `model_kwargs` mutated with `response_format={"type":"json_object"}` (`:967-991`), and on a JSON-mode rejection the runtime **silently issues a second provider call** with the original kwargs (`:1030-1043`). Neither the effective `response_format`, nor the fact that two provider calls happened, nor the first call's error is persisted — one attempt row, one `model_parameters_json`, both describing neither call precisely.
- **Why it matters:** "temperature/settings actually used" is an explicit disclosure item. A parameter record that can differ from what was sent is worse than absent for legal purposes because it reads as authoritative. `parameter_semantics` (configured vs model_default) shows the team already cares about exactly this distinction — the gap is only the call-time layer.
- **Owner/fix:** thread the *actually sent* kwargs into `StepExecutionOutput` (they're in scope at the call site); record `response_format` and a `provider_call_count`/`json_mode_fallback: true` marker in `LlmProvenance`. Small, contained in `step_execution_runtime.complete_step_execution`.
- **Acceptance criteria:** a step that triggers JSON-mode then falls back exports `model_parameters` matching the final call plus a fallback marker naming the first call's rejection.
- **Tests:** unit — stub `is_json_mode_rejection` path; assert provenance contains sent-kwargs + fallback marker (red today).
- **Risk:** none beyond a provenance field addition (schema is `extra=allow`, and `parse_attempt_provenance` tolerates new keys inside sections). **Confidence: high.**

### F-3 · P1 — Outbound HTTP/webhook transfers have no run-evidence record; their only trail is best-effort and lossy
- **Problem:** For `http_get`/`http_post` input steps, the run evidence records the *response* (as step input text) but not the resolved request — attempt provenance's `http` section is just `{input_source, structured_input_present}` (`executor.py:460-468`). The full record (URL host+path, method, status, duration) goes to the audit log via `audit_http_outbound`, which **swallows all exceptions** (`http_audit.py:90-96`) and deliberately drops query strings (`:58-65`) — for GET steps the query *is* the input. Webhook output: `flow_run_webhook_deliveries` rows (attempts, `delivered_at`, dead-letter, receiver idempotency key) are **not part of the evidence bundle** (bundle sections enumerated at `flow_run_evidence_bundle.py:74-108`) and are deleted at run purge (`flow_run_history_purge_repo.py:94-97`); the export merely strips legacy `webhook_delivered` mirror keys (`flow_run_export_json.py:1038-1051`, test `:1871`).
- **Why it matters:** "we transmitted this citizen's data to endpoint X at time T, receipt status S" is precisely what a public-record request about an outbound integration asks. Today Eneo can answer only from audit logs that may silently lack the row, and never with the resolved query parameters.
- **Owner/fix:** two slices. (1) Add an `http` provenance payload at capture time (resolved URL with secret-bearing params redacted via the existing `redact_url_secrets`, method, status_code, duration_ms, response size) — owner `http_orchestration.py`, landing in the existing `HttpProvenance` section. (2) Include webhook delivery rows (minus encrypted headers) as a bundle section, and have purge explainability cover them.
- **Acceptance criteria:** raw export of an http_get run shows the resolved URL (redacted per `flow_run_redaction.py`) and status; export of a webhook run shows per-attempt delivery timestamps and final state.
- **Tests:** integration — http-input flow export contains request evidence; webhook flow export contains delivery lineage.
- **Risk:** resolved URLs may embed personal data in paths — route them through the redaction pass like every other bundle string (they would be, automatically, once in the bundle). **Confidence: high** on the gap; medium on the right redaction granularity for query params (product/legal call).
- **Ponytail note:** this *reuses* `HttpProvenance`, `redact_url_secrets`, and the existing bundle/redaction machinery — no new abstraction.

### F-4 · P2 — No typed capture contract: eleven `extra=allow` provenance sections are hidden JSON with scattered producers
- **Problem:** `RagProvenance` through `CitationsProvenance` are empty `extra="allow"` models (`flow_run_provenance.py:88-125`); their actual shapes are defined by hand-built dicts in five producer files (`rag_retrieval.py:39-58`, `executor.py:409-469`, `template_fill_runtime.py:210-223`, `step_result_builder.py:39-63`, `step_execution_runtime.py:531-583`). The export layer then re-parses them defensively with 20+ `_as_json_object`/`_int_or_none` coercions (`flow_run_export_json.py:79-103, 456-479, 969-979`). `McpProvenance` and `AgenticProvenance` have **no producer at all** — schema vocabulary for data that is never captured.
- **Why it matters:** a legal reviewer cannot answer "what do we capture?" without reading the runtime; the coercion layer hides shape drift instead of failing it; empty sections imply capture that doesn't exist.
- **Owner/fix:** promote the fields the export actually reads into declared typed fields on each section (keep `extra=allow` for forward-compat), starting with `RagProvenance` (status, references, prompt_context, tracking) and the new `HttpProvenance` from F-3. Delete `McpProvenance`/`AgenticProvenance` until a producer exists — reintroducing a section is one line; carrying phantom vocabulary in a disclosure schema is misleading.
- **Acceptance criteria:** `rg "extra=\"allow\"" flow_run_provenance.py` shows sections with declared fields; no section without a producer.
- **Tests:** existing corruption-marker tests keep protecting the parse path; add one round-trip test per typed section.
- **Risk:** low — `parse_attempt_provenance` already fails-closed to corruption markers on shape violations. **Confidence: high.**

### F-5 · P2 — The manifest counts a retention state that can never exist
- **Problem:** `FlowRetentionState` includes `"redacted_for_deletion"` (`flow_retention_tombstone.py:19-21`), and the manifest exports `redacted_for_deletion_count` (`flow_run_evidence_export_manifest.py:42`, `flow_run_export_json.py:245-269`) — but `validate_count_shape` accepts only three state combinations, none of them `redacted_for_deletion` (`flow_retention_tombstone.py:69-97`), so such a tombstone cannot validate and `extract_retention_tombstones` would drop it (`:140-148`). No producer writes it (grep: only counters and the Literal). Similarly, `artifact_content_purged` has a valid shape but **no producer** — nothing in `backend/src/eneo` nulls `Files.blob/text` in place (grep-verified), so `availability: "content_purged"` (`flow_run_repo.py:1146-1149`) and its ResourceGone path (`flow_run_evidence_service.py:67-73, 110-121`) currently defend against a state only external scrubbing can create.
- **Why it matters:** a legal manifest that enumerates counters implies those lifecycles are operational. "Structurally always zero" is the definition of looking more complete than you are.
- **Owner/fix:** delete `redacted_for_deletion` from the Literal, the manifest field, and the counter (Ponytail delete). Keep `artifact_content_purged`/`content_purged` only with a one-line comment naming the intended producer (or wire the artifact-content purge that the tombstone shape was clearly designed for).
- **Acceptance criteria:** every member of `FlowRetentionState` is producible by `validate_count_shape`; a parametrized test constructs one valid tombstone per state (red today for `redacted_for_deletion`).
- **Risk:** none — pre-production schema, version-bump `flow-evidence-export.v8` if field removal is treated as breaking. **Confidence: high.**

### F-6 · P2 — API-key attribution on runs decays on key deletion; export lacks the actor resolution the view has
- **Problem:** `flow_runs.created_by_api_key_id` is `ondelete="SET NULL"` (`flow_tables.py:709-712`) — deleting/rotating an API key silently erases which key created historical runs, while `principal_user_id`/`principal_service_id` are RESTRICT. Separately, the human-readable service-principal actor summaries are added only by the view endpoint's presenter (`flow_run_evidence_router.py:141-146`, `flow_service_principal_actor_read_model.py:47-77`); the JSON export ships raw UUIDs only, and even the view enriches only checkpoint/rerun actors, not the run principal itself.
- **Why it matters:** actor/service-principal/API-key context is an explicit disclosure item; the artifact handed to lawyers is the *export*, not the view.
- **Owner/fix:** (1) snapshot a denormalized key label (or keep the id via soft-delete on keys) — data-model owner decision; at minimum document that audit logs are the durable key-attribution source. (2) Move actor enrichment into `render_evidence_json_export` as a manifest-level `actors` section (outside the hashed bundle, like `redaction`), reusing the presenter.
- **Acceptance criteria:** export of a service-key run names the service principal; deleting the creating API key does not reduce what the export can say about who started the run.
- **Tests:** export unit test with service-key run; integration test deleting the key first.
- **Risk:** low. **Confidence: high** on mechanics; medium on how often key deletion (vs rotation-by-new-key) occurs in practice.

### F-7 · P2 — Exported provenance is silently enriched/normalized at read time — "as recorded" is subtly untrue
- **Problem:** `_dump_attempt_record`/`_enrich_attempt_provenance_for_export` backfill `model_name`/`provider` into exported provenance from attempt columns (`flow_run_evidence_bundle.py:456-510`); `normalize_rag_payload` rewrites `usage_state` to `inserted_into_prompt`, injects display names, and recomputes chunk counts at parse time (`flow_run_provenance.py:469-523`). All derivations come from same-row persisted data — nothing is fabricated — but the export presents the *normalized* form as `provenance_json` with no marker, and the content hash covers the enriched form, so "stored bytes" vs "exported bytes" differ by design without saying so.
- **Why it matters:** in a dispute, the difference between "what the system recorded at execution time" and "what the export renderer derived later" is exactly the kind of thing opposing counsel finds.
- **Owner/fix:** one manifest boolean + note (`provenance_normalization_applied: true`, naming the normalizer version — the schema constants already exist), or stop backfilling and let the summary carry derived values (they already do). Prefer the note; the enrichment is useful.
- **Acceptance criteria:** manifest states that provenance is normalized-on-export and by which policy version.
- **Risk:** none. **Confidence: high.**

### F-8 · P2 — Duplicated derivations between debug export and typed summary will drift
- **Problem:** two `_collect_models_used` with different fallback semantics (`flow_run_evidence.py:333-351` vs `flow_run_export_json.py:471-479`); summary counts fall back to local recomputation when debug summary keys are absent (`flow_run_export_json.py:381-406`); three int-coercion helpers (`parse_step_order`, `_int_or_none`, `_strict_int_or_none`) across the same feature; `untracked_rag_summary` (`flow_run_export_json.py:623-635`) vs `default_rag_tracking` (`flow_run_provenance.py:235-246`) as two "not tracked" vocabularies.
- **Fix:** make the typed summary the sole deriver — the debug summary should *consume* summary numbers (or be reduced to the step projection the UI needs); merge the coercers into one module-level helper; keep one not-tracked vocabulary. This is the Ponytail merge for this slice.
- **Acceptance:** one `_collect_models_used`; `rg "def _collect_models_used" backend/src/eneo/flows` returns one hit.
- **Risk:** low; behavior-pinning tests exist. **Confidence: high.**

### F-9 · P3 — The export ships the full definition snapshot twice and hashes both copies
- `bundle.definition_snapshot` (`flow_run_evidence_bundle.py:76`) and `bundle.debug_export.definition_snapshot` (`flow_run_evidence.py:170`) are the same `version.definition_json`. For large flows this doubles export size and makes two sources for "the exact definition". Drop the copy inside the embedded debug export (keep it in the standalone debug model if the UI needs it). Version-bump the export schema. **Confidence: high.**

### F-10 · P3 — Debug run duration uses `created_at→updated_at`
- `_calculate_duration_ms(run.created_at, run.updated_at)` (`flow_run_evidence.py:148`) measures queue wait + every later row touch (reruns bump it), while `started_at`/`finished_at` exist and are populated (`flow_run_repo.py:818`). The typed summary inherits the number via debug fallback (`flow_run_export_json.py:404`). Use `started_at→finished_at`, null when absent. **Confidence: high.**

### F-11 · P3 — "Redacted" export does not state its scope; free-text personal data is not masked
- Redaction is key-name + bearer/URL-pattern based (`flow_run_redaction.py:10-51`); prompts, underlag, and outputs pass through untouched in redacted mode. That's a defensible policy (the content *is* the evidence), but the export's `redaction` section lists only what *was* masked, never what the policy does not attempt (no anonymization/PII claim disclaimer). Add one fixed sentence to the redaction section — mirror the honesty of `_RETENTION_NOT_TRACKED_NOTE` (`flow_run_export_json.py:70-73`). Treat "should redacted exports anonymize personal data" as the product/legal question it is; the technical gap is only the missing scope statement. **Confidence: high.**

### F-12 · P3 — RAG evidence lacks retrieval-configuration identity
- No embedding model id, chunking config version, or stable chunk identifier is captured (`rag_retrieval.py`/`rag_metadata.py` persist `info_blob_id` + `chunk_no` + snippet). If the knowledge base is re-chunked or re-embedded, `chunk_no` silently points at different text and "reconstructable via info-blob" quietly becomes false. Smallest honest fix: add embedding-model id + a per-chunk `sha256(chunk_text)` to references (the pattern exists — `PayloadPreview.sha256`). Full chunk-text capture is a cost/retention decision — snippets+hashes give verifiability without storing the corpus per run. **Confidence: high** on the gap; the fix depends on what the datastore result exposes (Codex #6).

---

## Capture Traceability

**Prompt/model settings.** Prompt is interpolated at prepare time (`step_execution_runtime.py:858-867`), optionally extended with a citation appendix at call time (`:1002-1012` — the *appendix-extended* `prompt_override` is what's persisted, correctly). Capture points: pre-dispatch `attempt_start` (lengths, token estimate, deadline, parameter snapshot) persisted and committed **before** the LLM call (`executor.py:1310-1352`) — so even a crash mid-call leaves triage data; at finish, full prompt on the step-result column + ≤16KB preview + sha256 in attempt provenance (`executor.py:418`, `flow_run_provenance.py:249-261`). Typed failures preserve the prompt on the failed result (`step_result_builder.py:34-35`, `step_execution_runtime.py:264-281`); generic failures don't (`step_attempt_runtime.py:166-185`) — prompt survives there only as the attempt_start length. The final provider message array (system/user roles, chunk formatting) is assembled inside `assistant.get_response` (`step_execution_runtime.py:331-341`) and never captured — disclosure can honestly say "prompt + input + included chunks" but not "the exact message array". Settings: configured-vs-sent gap is F-2.

**RAG/chunks/knowledge.** Query = composed step input text (`rag_retrieval.py:74-76`; Fable-06 carry-forward, unchanged) — persisted as the step input, but never labeled "this was the retrieval query". Captured per attempt: status/timings/error taxonomy, source ids, per-source ≤5 chunks (chunk_no, rounded score, 200-char snippet), truncation flags, source metadata (url/kind/container), prompt-context inclusion (included/not-included source ids, chunk counts, token budget truncation) via `knowledge_trace` (`step_execution_runtime.py:531-583`), and citation sidecars. The tracking self-description is exemplary honesty: "Exact prompt inclusion, citations, and material influence are not currently tracked" flips per-capability as capabilities engage (`flow_run_provenance.py:235-246`, `flow_run_export_json.py:638-677`). Full chunk text is used for quality scoring then dropped (`rag_metadata.py:102-124`, `rag_reference_quality.py:24-57`). Missing identity config is F-12.

**Files/templates/artifacts.** Uploads: typed metadata incl. checksum + extraction/transcription status (`flow_run_step_input_file.py`), relational per-attempt rows with RESTRICT FKs both ways (`flow_tables.py:1549-1577`), rerun copies input-file rows to the new attempt unless overridden (`flow_run_repo.py:940-1014`). Templates: asset id + file id + checksum + published version in both output payload and attempt provenance (`template_fill_runtime.py:217-223`); the rendered DOCX is stored as a checksummed file, and `template_fill_debug.rendered_docx_text_raw` keeps the rendered text until debug retention prunes exactly that key with a counted tombstone (`data_retention_service.py:1015-1044`). Generated artifacts: sha256 at creation (`output_runtime.py:118`), per-attempt rows, live availability, fail-closed template purge and ten-table unreferenced-file guard (`flow_run_history_purge_repo.py:249-264, 359-377`).

**Actor/timestamps/retries/reviews/reruns.** Run principal columns with a DB check constraint tying type↔ids↔permission (`flow_tables.py:764-782`); every evidence view/export writes an audit row or the request fails 503 (`flow_trace_audit.py:46-60`, router responses) — with `export_reason` recorded, and raw exports refusing the default reason (`flow_run_evidence_router.py:241-255`). Reviews capture original vs current payloads, decider principal, per-state timestamps, and the export computes `output_changed` honestly tri-state (`flow_run_evidence_export_summary.py:261-271`). Reruns have full lineage rows (prior/new attempt ids, roles, dependency sources) — the lineage survives; the *content* doesn't (F-1). Retries: none in-run except the invisible JSON-mode second call (F-2); Celery redeliveries are absorbed by CAS and leave `celery_task_id` on attempts. Terminalization is audited via the outbox exactly-once (Fable 06, Codex-verified); the lifecycle log events are explicitly labeled best-effort and non-authoritative (`flow_run_lifecycle_events.py:1-8`) — correct honesty.

---

## Retention / Purge / Missing Data Manifest

| Lifecycle stage | What happens | Export explanation | Honest? |
|---|---|---|---|
| Rerun accepted | Step-result evidence nulled; run envelope replaced on override | **None** | ❌ F-1 |
| Debug-evidence retention (tenant `run_debug_evidence_days`, default **None** = off, `settings.py:414`) | Step results: input/prompt/model-params → NULL + tombstone in output payload; `template_fill_debug` pruned; attempt provenance → retention marker (`data_retention_service.py:813-913`). Outputs and token counts kept. | Tombstone counts + note; per-attempt `retention_purged` status; rag tracking flips to `retention_purged` | ✅ |
| Pre-tombstone purges | indistinguishable from never-tracked | explicitly stated (`flow_run_export_json.py:70-73`) | ✅ exemplary |
| Full run purge (terminal + `LEAST(flow, space, classification)`, blockers for undelivered audit + active rerun) | Deletes deliveries, outbox, checkpoints, runs (cascade: step results, attempts, file rows), then unreferenced files (`flow_run_history_purge_repo.py:84-112`) | N/A — after purge there is nothing to export; run 404s. No tenant-level "purged runs ledger" exists | ⚠️ acceptable, but a legal request for a purged run gets "not found" rather than "purged on date D per policy P" — the tombstone design stops one level below the run. Worth a product decision, not a blocker |
| Webhook delivery rows | deleted at purge; never exported | none | ❌ F-3 |
| Uploaded runtime files | flow-scoped, survive run purge (`flow_tables.py:534-614`) | n/a | ⚠️ over-retention question for legal — flag to product |
| Artifact content | `content_purged` availability + 410 endpoint exist; **no producer** nulls content in place | manifest counts it | ⚠️ F-5 |
| API-key deletion | `created_by_api_key_id` → NULL | none | ❌ F-6 |
| Audit outbox rows after delivery | deleted per audit-log lifetime (`test..._follows_audit_log_lifetime`) — audit log itself is the durable record | n/a | ✅ |

---

## Evidence-Coupled Delete / Merge / Move List

| Action | Item | Evidence |
|---|---|---|
| **Decide: write or delete** | `FlowStepAttempts.input_payload_json` / `output_payload_json` (never written) | `flow_tables.py:1125-1133`; F-1 |
| Delete | `FlowRetentionState."redacted_for_deletion"` + manifest counter | `flow_retention_tombstone.py:19-21, 69-97`; F-5 |
| Delete | `McpProvenance`, `AgenticProvenance` (producer-less sections) | `flow_run_provenance.py:116-121`; F-4 |
| Delete | `_normalize_debug_rag` pass-through wrapper | `flow_run_evidence.py:323-324` |
| Delete | duplicate `definition_snapshot` inside embedded debug export | `flow_run_evidence.py:170` vs `flow_run_evidence_bundle.py:76`; F-9 |
| Merge | two `_collect_models_used`; three int-coercers; two "not tracked" RAG vocabularies | F-8 |
| Move | actor enrichment (presenter) into the export assembly as a manifest-level section | `flow_run_evidence_router.py:145`; F-6 |
| Simplify | summary fallbacks — make typed summary the single deriver, debug summary a consumer | `flow_run_export_json.py:381-406` |
| Do **not** delete | corruption/retention marker state machine (`FlowAttemptProvenanceParseResult` invariants, `flow_run_provenance.py:168-232`) — this is the honesty engine; it is depth, not ceremony |
| Do **not** delete | `debug-export.v2` itself — it feeds the typed UI read model (`flow_models.py:1270-1316`); trim it, don't kill it |
| Do **not** add | a generic "evidence event store" / compliance platform — the attempt table + outbox already are the event spine; F-1(a) deepens the existing owner |

---

## What Current Tests Already Cover

- Export assembly: manifest+summary presence, content-hash behavior (typed summary changes don't alter hash, `test_flow_run_evidence.py:1549`), single-typed-summary contract (`:1791`), unknown-field rejection on manifest/context (`:2023, 2090`).
- Honesty machinery: corrupt provenance markers by shape/version/keys (`:684-737`), corrupt-precedes-purged precedence (`:1137-1190`), retention tombstone counting and redacted preservation (`:1191-1244`), RAG tracking state lattice incl. purged/corrupt mixes (`:1245-1493`).
- Redaction: rerun/review lineage shape preservation through redaction, checkpoint payload redaction without resume key (integration `test_flow_evidence_api_contracts.py:887-1082`, unit `:1984`).
- Access/audit: trace permission tiers, space-admin path, raw-reason rejection, fail-closed audit on view and export (router tests `:373-763`; integration `:1394-1466`); evidence policy fail-closed flag parsing (`test_flow_evidence_policy.py`).
- Service correctness: run-id mismatch rejection and re-validation of caller-provided runs (`test_flow_run_evidence_service.py:150-205`), relational runtime-file metadata preference (`:70`, evidence `:2686-2848`).
- Retention: debug redaction before purge horizon, purge blockers (undelivered audit, active rerun), file-sharing/derived-child guards, classification tightening (`test_flow_runtime_retention_cleanup.py:961-1834`).
- Runtime capture: attempt-start provenance persisted before LLM dispatch (Fable 06: `test_flow_executor_runtime.py:3900`).

## Missing Red Tests

1. **Rerun evidence survival (F-1) — the headline red test.** Integration: complete a 2-step run → rerun step 1 with inline override → raw export. Assert the export either contains attempt-1's resolved input + output verbatim or explicitly marks them `not_captured_superseded`, and that the pre-override run input envelope is disclosed. Fails today on both options — forces the product decision.
2. **Sent-vs-recorded model kwargs (F-2).** Unit: JSON-mode-capable step whose provider rejects `response_format`; assert attempt provenance records the fallback and the final call's kwargs. Fails today.
3. **HTTP request disclosure (F-3).** Integration: `http_get` step run → raw export contains resolved (secret-redacted) URL + status code. Fails today.
4. **Webhook delivery lineage in export (F-3).** Integration: terminal `http_post` run with one retry → export shows delivery attempts/timestamps/final state. Fails today.
5. **Every retention state is producible (F-5).** Parametrized: for each `FlowRetentionState`, construct a validating tombstone. Fails today for `redacted_for_deletion`.
6. **Debug-redaction → export end-to-end.** Integration: set `run_debug_evidence_days`, run the real retention sweep, then call the real export endpoint; assert manifest `retention_state_summary.tracking_state == "tracked"` with correct counts and nulled step fields. Today redaction and export honesty are tested in separate layers, never composed.
7. **Idempotency metadata disclosure (matrix #3).** Export contains `idempotency_key`/`request_fingerprint` (or an explicit exclusion note). Fails today.
8. **Export determinism.** Two exports of the same untouched run yield identical `content_hash` (relies on the derived `generated_at`, `flow_run_evidence.py:85-92, 180-194` — clever, currently unpinned).
9. **API-key deletion attribution (F-6).** Delete the creating key → export still names the creating actor. Fails today.
10. **Crash-terminalized run export.** After the (Fable-06 P0-fixed) stale-RUNNING reconciler fails a run, export shows the open attempt closed with `attempt_start` provenance intact and the run error code — pins evidence completeness through the crash path.

## What Is Not Worth Fixing

- The `bundle: dict[str, Any]` export field — it is the hashed open object and says so (`flow_models.py:2033-2038`); typing it would freeze the hash input against every additive change.
- 16KB preview caps with sha256 — right trade-off; the full-text home is the step/attempt payload question (F-1), not bigger previews.
- `EvidenceRetentionStateSummary`'s `extra="allow"` — harmless forward-compat outlier; align opportunistically.
- Redaction being key/pattern-based rather than NLP-PII — a policy statement (F-11) fixes the honesty; content-level anonymization is a different product.
- The three-projection payload as such — trimming duplication (F-8/F-9) is enough; collapsing debug-export into the summary would break the typed UI read model for no disclosure gain.
- `_typed_payload_preview_or_none` and similar one-call wrappers — noise-level.
- Per-request live assembly of the bundle (no cached/signed export artifact) — fine at current volumes; revisit only if legal requests require tamper-evident *stored* exports (then store `content_hash` + manifest at export time in the audit metadata — which `log_flow_trace_audit_or_raise` `extra` can already carry).

## Tomorrow Implementation Slices

1. **(~2h) F-5 + F-4 deletions:** remove `redacted_for_deletion` end-to-end, delete producer-less provenance sections, add the per-state producibility test. Pure honesty, zero behavior risk.
2. **(~3h) F-1 decision slice:** write attempt input/output payloads in `finish_attempt` (option a) + extend debug-redaction sweep to the new columns + red test #1. If product picks option (b), it's ~1h for the manifest marker instead.
3. **(~2h) F-2:** thread sent-kwargs + json-mode-fallback marker into `LlmProvenance` + red test #2.
4. **(~2h) F-3 slice 1:** `HttpProvenance` request capture in `http_orchestration.py` + red test #3.
5. **(~2h) F-3 slice 2:** webhook deliveries as a bundle section + red test #4; bump export schema once for slices 2-5 together (`v8`).
6. **(~1h) Matrix #3 + F-10 + F-7:** add idempotency fields to `FlowRun` domain/export, fix duration source, add normalization note.
7. **(~2h) F-8/F-9 merge slice:** single deriver, single coercer, drop duplicate snapshot.
8. **(~1h) F-6:** actor section in export; open the key-deletion SET NULL question with product.

## Claims Codex Must Verify

1. **F-1 completeness:** confirm no other writer populates `FlowStepAttempts.input_payload_json`/`output_payload_json` (my grep across `backend/src` found none), and that no path preserves the pre-override run envelope on rerun besides `rerun_operations.input_payload_json` holding the override.
2. **F-2 call-site:** confirm `assistant.get_response` receives `model_kwargs` (possibly json-mode-modified) while `StepExecutionOutput.model_parameters_json` derives from `assistant.completion_model_kwargs`, and that the fallback second call reuses the same attempt row.
3. **F-3:** confirm no evidence-bundle section or step-result key persists webhook delivery state (the `webhook_delivered` keys in `_strip_artifact_wrapper_keys` should have zero producers).
4. **F-5:** re-confirm zero producers for `redacted_for_deletion` and `artifact_content_purged` tombstones, and that nothing inside or outside `eneo` nulls `Files.blob`/`text` in place (I checked `backend/src/eneo` only).
5. **`raw_completion_text` gating:** confirm no other path than `step_execution_runtime.py:1170-1175` sets it (transcribe-only sets `""` prompts but check its raw-text handling), i.e., non-citation steps truly lose superseded output text.
6. **F-12 feasibility:** whether `InfoBlobChunkInDBWithScore` / the datastore result exposes an embedding-model identifier or stable chunk id the reference builder could persist cheaply.
7. **Actor presenter scope:** confirm the export path never resolves service-principal names (presenter used only at `flow_run_evidence_router.py:145`).
8. **Purged-run answerability:** confirm there is no surviving per-run record (audit log entries survive?) from which "run X was purged on date D under policy P" could be answered post-purge — this calibrates whether the run-purge ledger idea is needed or already covered by audit retention.

## Confidence

**High** on F-1, F-2, F-3, F-5, F-7, F-8, F-9, F-10 — every load-bearing line (rerun reset values, kwargs derivation, citation-gated raw text, tombstone validator, enrichment functions, duplicate deriveers) was read directly this session, and the negative claims (never-written columns, no producers, missing exports) are grep-backed with the residual risk isolated in Codex claims #1-#5. **Medium-high** on F-4 (the hidden-JSON characterization is direct; the right field promotion set needs producer-by-producer confirmation), F-6 (SET NULL is direct; operational frequency of key deletion is not), and F-12 (gap direct; fix feasibility depends on datastore surface, Codex #6). Matrix rows marked ⚠️ carry their caveats inline. The one deliberate extrapolation — that a legal reviewer would treat silent normalization and structurally-zero counters as material — is a judgment call, flagged as such in F-5/F-7 rather than asserted as defect severity.
