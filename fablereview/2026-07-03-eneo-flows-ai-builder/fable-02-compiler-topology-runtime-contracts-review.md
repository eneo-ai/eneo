# Fable 02: Compiler Topology Runtime Contracts Review

All source verification is complete. I have everything needed to write the review — every material claim below was verified against source in this session.

---

# Fable 02 Review: Compiler, Topology, Underlag, RAG, and Runtime Contracts

Reviewer: Claude Fable 5 · Date: 2026-07-03 · Repo: `/Users/ccimen/eneo/eneo-flows-clean` · Read-only review; no files edited.

## TL;DR

1. The Builder compiles mostly-valid specs directly — the skeleton/pattern architecture is server-owned and sound — but three compiled defaults are self-contradictory: file/document/audio primary steps emit `{{ step_input.text }}` bindings while `NewStepDraft.runtime_required` defaults to `False`, so a run without an upload crashes on a raw missing-key error *before* the runtime's own friendly typed validation can fire.
2. The single worst production defect is unchanged from prior reviews and fully re-verified: RAG uses the entire composed underlag (up to the 1 MB inline cap) as the embedding query (`step_execution_runtime.py:955` → `references.py:171` → `semantic_search`), silently destroying retrieval quality on exactly the flows targeted underlag was built to help.
3. Validation is three non-equivalent dialects: Builder (deep but array-lenient), publish/manual (near-vacuous — skips `step_input`, skips unknown roots, never analyzes instructions), and runtime (strict, crash-on-miss); the fix is one shared reference-grammar gate in `flow_validators.py` that Builder preflights, not a new validation service.
4. Underlag field selection is a hand-rolled Swedish stemmer/marker system inside the compiler (`ai_builder_create_dataflow.py:51-159`) that silently drops out-of-range refs with zero telemetry and treats English flows systematically worse than Swedish ones; the skeleton already knows slot roles, so most of the token matching is deletable by deriving composer roles structurally.
5. Three tests actively pin wrong behavior (lenient array paths, intentional-partial underlag, the false "runtime keeps leniency" docstring's premise), and the edit path normalizes twice such that the user-approved diff is computed on a *different* spec than the one persisted — both are cheap, high-value fixes before production.

---

## Ratings

| Axis | Score (1-10) | Rationale |
|---|---|---|
| Architecture cleanliness | 5 | Typed spec core (`FlowDraftSpecCore`), server-owned architecture envelope, and clear module naming are good. But underlag ownership is split across three layers (draft-level dataflow, spec-level transition policy, source-material completion), and terminal-artifact topology is handled at three layers (skeleton, normalizer, validation error). |
| Maintainability | 5 | Small pure functions and dataclasses throughout; but Swedish token tables, two path-grammar implementations, double normalization on edit, and heuristic string matching embedded in compile logic will rot. |
| Runtime robustness | 4 | Strict resolver is right in principle, but compiled defaults route users into raw `BadRequestException` crashes; RAG degradation is silent; typed validation exists but is unreachable in the binding case due to ordering. |
| Dataflow correctness | 6 | Compiled dataflow is largely correct for the Swedish happy path; silent ref drops, selection caps, edit alias retargeting, and language asymmetry erode it at the edges. |
| Token/RAG efficiency | 3 | Targeted underlag (good idea, real implementation) is negated at the retrieval boundary by full-underlag embedding queries. `autocut_cutoff=3, num_chunks=30` with a megabyte query is not retrieval, it's noise. |
| Testability | 7 | 250 test files under `tests/unittests/flows`, heavily pure-function-oriented; 18 tests on create dataflow alone. Weakness: three tests pin the wrong contract (details below). |
| Production readiness | 4 | Fine for pre-production. Findings 1–4 below are release blockers for real municipal users; everything else is ordered hardening. |

---

## End-To-End Dataflow Map

**Create path (verified):**

1. **User input → discovery → PlanningState.** Server-owned slots (`primary_runtime_input`, `terminal_output`, patterns, aggregation intent) become a `CreateCompileContext` (`ai_builder_create_compiler.py:117-258`). `runtime_required` defaults `True` here (`:94`), so skeleton-created source steps are usually safe.
2. **LLM semantic intent → heuristic pre-normalization.** Redundant leading audio-transcription steps are dropped/rewritten via Swedish/English token prefixes (`:699-733`, `:791-818`); zero-contract leading text steps are folded (`:654-696`); shadow form fields dropped with logging (`:559-651`).
3. **Skeleton composition.** `materialize_step_skeleton` + `compose` produce `NewStepDraft`s; failures raise typed `AIBuilderArchitectureError` (`:206-234`) — correctly *not* routed to model self-correction.
4. **Draft mechanics normalization** (`ai_builder_create_dataflow.py:162-192`): two passes of ref sanitization around `auto_bind_targeted_underlag_for_text_composer`. Out-of-range/invalid `uses_previous_fields`/`uses_previous_outputs` are **silently dropped with no log** (`:292-340`). Underlag field selection runs the Swedish-marker chain: always-broad → semantic score → broad → source-summary → floor → priority fallback (`:796-835`), capped at 3/prior, 8 total, 16 broad (`:47-49`).
5. **Per-step compile** (`ai_builder_new_step_compiler.py:74-131`): `compile_step_input_bindings` builds the `input_bindings.question` underlag (`:229-299`); `flow_input`+document/file/audio → `{{ step_input.text }}` (`:429-430`), text → `{{ indata_text }}` (`:431`), json → `{{ indata_json }}` (`:428`); previous JSON step → whole `output.structured` unless a targeted field ref suppresses it (`:302-324`). `resolve_runtime_input_config` forces `enabled=True` and `setdefault("required", False)` (`flow_authoring_runtime_input.py:44-45`).
6. **Spec-level normalization + validation** (`ai_builder_compiled_spec_preparation.py:38-92`): `normalize_ai_builder_spec` (terminal tail fold, terminal contract promotion, pre-terminal body rename, all_previous rewire, source-material underlag completion — `ai_builder_step_transition_policy.py:64-189`), then `validate_spec` (`ai_builder_validator.py:107-154`) = shared graph checks + deep reference validation + warning-only lints.
7. **Materialization/publish.** Plan refs rewritten to `step_N` aliases (`flow_authoring_variable_rewriting.py:93-112`; unknown refs pass through untouched). Publish gate = `validate_steps(..., require_complete_template_fill_config=True)` (`flow_service.py:435-439`) — **no reference-grammar validation** (`flow_validators.py:735-797`).
8. **Runtime.** `parse_runtime_steps` re-checks enums/binding keys/contract conflicts/chain rules but no templates (`step_definition_parser.py:456-544`). `resolve_step_input` loads runtime files only if IDs were submitted (`step_input_resolution.py:110-166`), interpolates `bindings.question` — which **replaces** source input (`:168-206`) — then JSON-parses (`:224-248`) and caps size (`:250-255`). `prepare_step_execution` runs typed input policy *after* resolution (`step_execution_runtime.py:836-849`).
9. **RAG.** `complete_step_execution` passes `question=prepared.step_input.text` (`step_execution_runtime.py:953-955`) → `retrieve_rag_chunks` (`rag_retrieval.py:73-83`) → `ReferencesService.get_references` with `embed_method=CONCATENATE` defaulting, and since flows pass no session/files, `_concatenate_conversation` returns the question verbatim (`references.py:117-171`) → `datastore.semantic_search(input_string=<full underlag>)` (`:68-75`).
10. **Output → next step.** JSON output validated only when `output_contract` present (`runtime/output_formats/json.py:34-42`); next step reads `output_payload_json["text"]` or `structured` via source resolution (`step_input_resolution.py:427-450`) or template refs resolved strictly (`variable_resolver.py:125-167`).

**Edit path deltas:** projection materializes ordered edits; deterministic repairs (leading-audio insertion, `ai_builder_edit_compiler.py:332-382`); alias canonicalization leaves stale aliases to deleted steps untouched (`:829-831`); `normalize_ai_builder_spec` runs **twice** — once inside `compile_edit_proposal` without terminal context (`:137-144`), once in `prepare_compiled_spec_for_session` with terminal context and name disambiguation (`ai_builder_edit_proposal.py:126-137`) — while the user-approved diff is built from the first pass and the persisted spec from the second (`:184-191`).

---

## Canonical Ownership Map

| Concept | Current owner(s) | Should be |
|---|---|---|
| Variable/path grammar | Three dialects: `variable_resolver.py` (strict, runtime), `ai_builder_json_schema_paths.py` (lenient default), `ai_builder_structured_field_paths.py` (strict, drafts) | Runtime resolver grammar is canonical; both authoring checkers must match it (strict array indexing); one schema-walk implementation. |
| Reference validation lifecycle gate | Builder-only (`ai_builder_validation_references.py`); publish nearly vacuous (`flow_validators.py:735-797`) | `flow_validators.py` owns it for create/update/publish; Builder calls the same functions as preflight. |
| `input_bindings.question` semantics | Split: parser (`step_definition_parser.py:316-345`), publish (`flow_validators.py:769-797`), runtime replacement (`step_input_resolution.py:168-206`), key rules (`input_binding_contract_rules.py`) | Keep `input_binding_contract_rules.py` as the shared rule module; extend it with the consumption rule (both directions) so publish/parser/runtime cite one predicate. |
| `step_input` metadata keys | Producer: `step_input_resolution.py:329-351` (8 keys); consumer contract: `flow_variable_definitions.py:82-87` (4 keys) | Producer-owned typed contract next to `_build_runtime_input_metadata`; `STEP_INPUT_KEY_SHAPES` derived from it. |
| Underlag/dataflow binding (create) | `ai_builder_create_dataflow.py` (draft level) + `ai_builder_step_transition_policy.py` + `ai_builder_source_material.py` (spec level) | Create compiler owns it once at draft level, driven by skeleton slot roles; spec-level source-material completion remains only for the edit path (model-authored steps without slots). |
| Terminal-artifact topology | Skeleton (create), three normalizers (`ai_builder_step_transition_policy.py:294-564`), alignment error (`ai_builder_compiled_spec_preparation.py:95-121`) | Create: skeleton only (normalizers should be no-ops; assert, don't repair). Edit: normalizers legitimately own it. Validation error stays as the fence. |
| RAG retrieval query | None — underlag is overloaded as query (`step_execution_runtime.py:955`) | Runtime RAG boundary (`rag_retrieval.py` or the call site) derives a bounded query; **not** a new Builder authoring contract (see Finding 1). |
| Source grounding across steps | `ai_builder_source_material.py` (good home) | Keep, but split "source text present" from "some structured subfield present" (Finding 9). |
| Step lineage / aliases | `step_lineage.py` (canonical, clean) + edit compiler rewrites | Keep; edit compiler must stop falling back to stale literals (Finding 8). |
| Typed runtime input requirements | Authoring default (`flow_authoring_runtime_input.py`), run-start check (`flow_run_step_inputs.py:266-277`), runtime policy (`step_input_validation.py`) | One rule: a step whose binding consumes `step_input.*` has a *defined* value for `step_input` in every run — via always-built metadata (recommended) or forced `required=True`. |

---

## Ranked Findings

### F1 — RAG embedding query is the full composed underlag — **P0/P1**

- **Problem:** `complete_step_execution` passes `question=prepared.step_input.text` into retrieval (`step_execution_runtime.py:953-958`); `retrieve_rag_chunks` forwards it (`rag_retrieval.py:73-83`); `get_references` with default `EmbedMethod.CONCATENATE` and no session/files returns the string unchanged (`references.py:165-171`, `:117-145`) into `datastore.semantic_search` (`:68-75`). The only bound is the ~1 MB inline cap.
- **Why it matters:** For exactly the flows this system targets (transcript → analysis with legal knowledge refs), the "query" is a 50–500 KB transcript. Embedding it produces a topic-soup vector; `autocut_cutoff=3` then prunes against noise. Retrieval silently degrades — no error, no diagnostic, wrong law citations in municipal decision documents.
- **Canonical owner / fix:** Runtime RAG boundary. Derive a bounded query at the call site: prefer the step's semantic intent (instructions/name, which are short and available on `prepared`) plus a bounded head of the underlag; record `rag_metadata["query_derivation"]` provenance. **Do not** add a Builder-compiled `retrieval_query` binding: it would not cover manually authored flows, adds a second authoring surface, and the runtime has everything it needs.
- **Acceptance criteria:** A 200 KB `step_input.text` never reaches `semantic_search` unchanged; `rag_metadata` records the derived query length and strategy; LLM prompt still receives full underlag.
- **Tests:** `test_complete_step_execution_derives_bounded_rag_query_from_large_step_input`; assert forwarded `question` length ≤ bound and provenance recorded.
- **Risk/trade-off:** Any derivation changes retrieval results for existing flows; pre-production, acceptable. Keep the strategy trivially simple (truncate+instructions) — no summarizer model call in the retrieval path.
- **Confidence:** High (every hop read in source this session).

### F2 — Compiled `{{ step_input.text }}` + optional-by-default runtime input = crash before friendly validation — **P1**

- **Problem:** The compiler emits `{"question": "{{ step_input.text }}"}` for every `flow_input` document/file/audio step (`ai_builder_new_step_compiler.py:429-430` via `:281-299`), and `resolve_runtime_input_config` sets `enabled=True` with `setdefault("required", False)` (`flow_authoring_runtime_input.py:44-45`). `NewStepDraft.runtime_required` defaults `False` (`ai_builder_new_step_models.py:143`) — the create path overrides it to `True` via `CreateCompileContext` (`ai_builder_create_compiler.py:94`), but edit-path added steps and any draft built without the envelope keep `False`. At runtime, metadata is built only when file IDs were submitted (`step_input_resolution.py:108-117`); with none, `current_step_input=None` means `step_input` never enters the context (`variable_resolver.py:102-103`), and interpolating the question raises a raw `BadRequestException: Unknown variable reference: 'step_input.text'` (`variable_resolver.py:133-142`) at `step_input_resolution.py:179` — *before* the consumption check at `:200-206` and *before* the typed `TYPED_IO_EMPTY_EXTRACTION` policy error (`step_input_validation.py:43-47`, invoked at `step_execution_runtime.py:836-849`). `prepare_step_execution` catches only `TypedIOValidationException` (`step_execution_runtime.py:806-811`), so this surfaces as an unclassified failure. Rerun compounds it: omitted `step_inputs` skips all validation (`flow_run_rerun_service.py:338-339`); inheritance (`executor.py:1115-1132`) covers normal cases but not a predecessor that legitimately ran file-less.
- **Why it matters:** An optional-upload flow run without an upload is a *supported user action* that produces an unfriendly crash. The pivot contract's own compiled default defeats the runtime's typed-error design.
- **Canonical owner / fix:** Runtime contract, one rule: **when `runtime_input.enabled` is true, `step_input` metadata is always built** — empty text, empty file list — so the shape is guaranteed and values degrade to `""`. This also makes the `RUNTIME_INPUT_NOT_CONSUMED` check (`:200-206`) fire consistently instead of only when files happen to exist. Then let `validate_runtime_input_policy` produce the friendly typed error for required-but-empty extraction. Optionally, run-start required-check (`flow_run_step_inputs.py:266-277`) should treat "binding consumes `step_input.*`" as effectively required.
- **Acceptance criteria:** Enabled runtime input + no files + `{{ step_input.text }}` binding yields either a typed validation failure (required) or an empty-string interpolation plus diagnostic (optional) — never a missing-key exception.
- **Tests:** `test_resolve_step_input_builds_empty_metadata_when_runtime_input_enabled_without_files`; `test_optional_file_step_question_binding_interpolates_empty_and_diagnoses`; rerun characterization: `test_rerun_inherits_predecessor_files` and `test_rerun_with_fileless_predecessor_fails_typed_for_required_input`.
- **Risk/trade-off:** Always-built metadata makes `{{ step_input.text }}` silently empty for optional inputs — acceptable only with the existing `empty_prior_step_input`-style diagnostic extended to this case. Do not make general interpolation lenient.
- **Confidence:** High.

### F3 — Publish/manual validation is not runtime-equivalent; Builder is the only deep gate — **P1**

- **Problem:** The shared gate validates bindings only for `step_N` ordering: it skips `step_input.*` outright (`flow_validators.py:743-744`), ignores any non-`step_` head (`:745-746` — typos, unknown roots, garbage all pass), never checks `output.text`/`output.structured.<field>` path validity or contract membership, and **never analyzes instruction templates at all**. Runtime-input publish rules enforce enabled ⇒ question consumes `step_input.*` (`:769-797`) but not the converse: a question consuming `step_input.*` with runtime input *disabled* publishes fine and crashes every run (F2 mechanics). Binding-key whitelisting only applies at publish strictness (`:322-329`; pinned by `test_flow_validators.py:400`). Meanwhile Builder runs the full `validate_variable_references` (`ai_builder_validator.py:138`) — so manually authored/edited flows (the UI exposes direct binding editing) are held to a *lower* standard than Builder output.
- **Why it matters:** Every guarantee the Builder earns can be undone by one manual edit that publishes cleanly and fails at interpolation.
- **Canonical owner / fix:** `flow_validators.py` gains reference validation over instructions + `input_bindings` + `output_config` using the machinery that already exists: `analyze_template` handles `step_N` heads natively (`template_reference_analyzer.py:115-124`), and `missing_structured_output_path(..., require_array_index=True)` checks contracts. Builder's `validate_variable_references` becomes a thin adapter over the same checks (plan-ref map instead of `step_N` map). Add the converse runtime-input rule to `input_binding_contract_rules.py` so parser/publish/runtime share it.
- **Acceptance criteria:** Publish rejects: unknown reference roots, unsupported step-output paths, contract-missing structured fields, unknown `step_input` keys, and `step_input.*` consumption with runtime input disabled. Builder validation results are unchanged (its checks are a superset today, minus array strictness fixed in F4).
- **Tests:** `test_validate_steps_rejects_unknown_binding_root`, `test_validate_steps_rejects_binding_structured_path_missing_from_output_contract`, `test_validate_steps_rejects_step_input_reference_when_runtime_input_disabled`, plus an instructions-template case.
- **Risk/trade-off:** Previously-publishable manual flows may now fail validation. Pre-production: correct behavior. Message quality matters — reuse Builder's suggestion helpers (`_suggest_similar`).
- **Confidence:** High.

### F4 — Two array-path grammars; the lenient one is validated, the strict one executes — **P1**

- **Problem:** `missing_structured_output_path` defaults `require_array_index=False` and its docstring claims "Runtime template validation keeps that lenient behavior" (`ai_builder_json_schema_paths.py:13-20`, `:29-37`) — false: the resolver requires numeric list indexes (`variable_resolver.py:146-152`). Builder validation calls it lenient (`ai_builder_validation_references.py:148-151`), so `{{ step_a.output.structured.risker.rubrik }}` validates and then crashes at runtime. The behavior is pinned by `test_ai_builder_validator.py:731-767` (name literally encodes the false premise). Meanwhile the *draft*-level checker `missing_draft_field_path` is already strict and documents runtime parity (`ai_builder_structured_field_paths.py:12-18`) — two implementations of one grammar with opposite semantics.
- **Why it matters:** Builder-blessed specs crash at runtime; the docstring will keep misleading maintainers into "fixing" the strict side.
- **Canonical owner / fix:** Runtime grammar wins. Flip the default (or pass `require_array_index=True` at both Builder and the new shared-gate call sites), correct the docstring, rewrite the pinning test to reject `risker.rubrik` and keep accepting `risker.0.rubrik` (`:695-729` already covers the numeric case). Longer term, fold `missing_draft_field_path` and `missing_structured_output_path` traversal into one walker (drafts vs. JSON schema differ only in node shape).
- **Acceptance criteria:** No caller uses lenient traversal; `require_array_index` parameter deleted (constant behavior); docstring accurate.
- **Tests:** Flip `test_structured_access_keeps_lenient_array_property_fallback_for_runtime_templates` to a rejection test.
- **Risk/trade-off:** Existing persisted drafts with lenient paths will start failing validation — they were already broken at runtime, so this converts a runtime crash into an authoring error.
- **Confidence:** High.

### F5 — Edit path: user approves a diff of spec A, system persists spec B — **P2**

- **Problem:** `compile_edit_proposal` normalizes once *without* terminal context (`ai_builder_edit_compiler.py:137-144`) and builds the approval diff from that result (`:176-224`). `process_edit_proposal` then re-normalizes with `terminal_output_type` and duplicate-name disambiguation (`ai_builder_edit_proposal.py:126-137`) and stores `FlowBuilderProposalContent(spec=<second pass>, edit=<first-pass approval>)` (`:184-191`). Precisely the transformations that only run with terminal context — terminal artifact helper folding (`ai_builder_step_transition_policy.py:448-518`), terminal text→DOCX/PDF promotion with instruction rewriting (`:521-564`), pre-terminal body renames (`:294-374`) — are the ones the approved diff can never show. A terminal step can appear "unchanged" in the preview while the persisted plan changed its `output_type` and instructions.
- **Why it matters:** The edit approval is the product's trust surface ("calm confidence"); preview/apply divergence on output type is exactly the kind of silent surprise the review flow exists to prevent.
- **Canonical owner / fix:** One normalization point. Pass `terminal_output_type` and `disambiguate_duplicate_step_names=True` into `compile_edit_proposal`'s internal normalize and make `prepare_compiled_spec_for_session` skip re-normalization for the edit path (or, minimal version: compute the diff after the final spec exists). The double pass also silently depends on every normalizer being idempotent — untested today.
- **Acceptance criteria:** The spec inside `FlowBuilderProposalContent` is byte-identical to the spec the approval diff was computed from.
- **Tests:** `test_edit_proposal_approval_diff_matches_persisted_spec` (construct an edit whose terminal step gets promoted; assert the diff shows the promotion).
- **Risk/trade-off:** None meaningful; this is consolidation.
- **Confidence:** High on the mechanism; medium on user-visible frequency (requires terminal-type mismatch in an edit, which the terminal normalizers exist to handle — so it does occur).

### F6 — Structured field refs into contract-less JSON steps validate silently, fail at runtime — **P2**

- **Problem:** When a referenced JSON step has no `output_contract`, Builder validation skips path checking entirely (`ai_builder_validation_references.py:143-146`); the compiler emits no contract when the LLM declared no output fields (`ai_builder_new_step_compiler.py:391-396`); runtime JSON output is freeform without a contract (`runtime/output_formats/json.py:34-42`); the strict resolver then raises on whatever key the model didn't happen to emit. The only guard is an INFO-severity lint (`ai_builder_validation_quality.py:167-187`).
- **Why it matters:** This is validation theater — the exact class of run-time key error the reference validator exists to prevent, waved through whenever the contract is missing.
- **Canonical owner / fix:** Shared gate (F3) + Builder: field-level `output.structured.<field>` refs require the referenced step to declare an `output_contract`; whole-object `output.structured` refs stay legal. On the create path this is nearly free — targeted underlag already only binds JSON priors *with* output fields (`ai_builder_create_dataflow.py:786-793`), so the error will fire mainly on edit/manual paths where it belongs.
- **Acceptance criteria:** `structured_access_requires_output_contract` error at Builder and publish; whole-object refs unaffected.
- **Tests:** `test_structured_field_access_to_contractless_json_step_is_rejected`; keep `test_missing_output_contract_field_reference_rejected` (`test_ai_builder_validator.py:666-693`) green.
- **Risk/trade-off:** Slightly more friction for LLM proposals lacking output fields — correct friction; the critic already pushes toward declared fields.
- **Confidence:** High.

### F7 — `STEP_INPUT_KEY_SHAPES` drift causes false rejections of valid runtime references — **P2**

- **Problem:** Runtime metadata emits 8 keys (`text`, `file_ids`, `files_count`, `files`, `total_file_size`, `extracted_text_length`, `input_format`, `capture_mode` — `step_input_resolution.py:329-351`); the static contract knows 4 (`flow_variable_definitions.py:82-87`). Consequences: (a) `{{ step_input.files_count }}` is rejected as unknown at authoring (`template_reference_analyzer.py:207-217`) though it resolves at runtime; (b) `consumes_runtime_input` requires `path_error_code is None` (`:55-61`), so a question binding referencing *only* `step_input.files_count` is treated as not consuming runtime input and publish rejects it (`flow_validators.py:793-797`) — a false positive built on drift.
- **Canonical owner / fix:** Producer-owned. Define the typed key contract next to `_build_runtime_input_metadata` and derive `STEP_INPUT_KEY_SHAPES` from it; add a parity test so the maps cannot drift again.
- **Acceptance criteria:** Static key set == producer key set, enforced by test; `files` (sequence of mappings) modeled honestly or explicitly excluded with a comment stating why.
- **Tests:** `test_step_input_static_keys_match_runtime_metadata_contract`; `test_step_input_files_count_is_valid_runtime_reference`.
- **Risk/trade-off:** Exposing `files` (nested mappings) needs shape rules beyond SCALAR/SEQUENCE; fine to keep it internal-only if declared deliberately.
- **Confidence:** High.

### F8 — Whole-plan edits silently retarget stale `step_N` aliases to whichever step now holds that order — **P2**

- **Problem:** Alias canonicalization maps only surviving existing steps (`ai_builder_edit_compiler.py:748-765`); an alias to a deleted step's old order returns the original literal (`:829-831`); downstream validation then resolves `step_N` against the *new* compiled order (`template_reference_analyzer.py:115-124` + `ai_builder_validation_references.py`), which usually exists — so the spec validates while the dataflow quietly points at the wrong step. The same tolerant-passthrough pattern exists at materialization (`flow_authoring_variable_rewriting.py:110`).
- **Canonical owner / fix:** Edit compiler. When rewriting, an alias whose old order maps to no surviving step is a compile error (`stale_step_alias_to_removed_step`) fed back to the model — not a passthrough. This is a *good* use of the repair loop: reject with a precise message rather than normalize.
- **Acceptance criteria:** Deleting existing step 2 while another step's binding/instructions reference `{{ step_2.* }}` fails compilation with the stale-alias error; insertion remap tests (`test_ai_builder_edit_proposal.py:330-375`) stay green.
- **Tests:** `test_ordered_whole_plan_delete_blocks_stale_literal_step_alias_to_removed_order` (characterization first — it will currently pass validation, which is the bug).
- **Risk/trade-off:** More edit-proposal rejections initially; correct trade.
- **Confidence:** High.

### F9 — Underlag selection: Swedish-only heuristics, silent drops without telemetry, under-selection at report boundaries — **P2**

- **Problem, three parts:**
  (a) **Language asymmetry.** Broad-composer detection is driven by Swedish marker phrases — "skapa docx", "sammanställ dokument", "färdigt word" (`ai_builder_create_dataflow.py:51-86`) — plus Swedish stopwords/suffix stemming (`:87-159`, `:1108-1127`). The terminal-artifact normalizers are bilingual (`ai_builder_step_transition_policy.py:44-52`), but the field-selection layer is not: an English "Create the final Word document" composer misses `always_broad` and can land in the semantic/floor branches, receiving as little as one field per prior (`:990-997`). Same flow, different language, different data flow.
  (b) **Zero-telemetry drops.** `_compile_safe_previous_field_refs` / `_compile_safe_previous_output_refs` (`:292-340`) silently discard LLM-declared refs (out-of-range, non-JSON target, missing path) with no log — in contrast to shadow-field drops which are logged (`ai_builder_create_compiler.py:637-651`) and advisory-surfaced on edit. The model never learns; the user never sees.
  (c) **Partial-source blind spot.** `source_material_binding_status` classifies any question mentioning *one* prior structured subfield as `INTENTIONAL_PARTIAL` (`ai_builder_source_material.py:119-123`), which suppresses both completion (`ai_builder_step_transition_policy.py:251-256`) and the lint (`ai_builder_validation_quality.py:339-356`); pinned by `test_ai_builder_step_transition_policy.py:1362`. A final DOCX/PDF composer bound to `{{ step_2.output.structured.summary }}` alone keeps a fraction of the source with no warning. Meanwhile `question_targets_prior_structured_field=False` is hardcoded in create-mode signals (`ai_builder_create_dataflow.py:471`) — the policy inputs differ between the two layers evaluating the same question.
- **Why it matters:** These heuristics decide what evidence reaches the model for final municipal documents. Silent narrowing is a data-quality failure users cannot detect.
- **Canonical owner / fix (ordered, Ponytail):**
  1. Log dropped field/output refs (one INFO with names+reasons) — 20 lines.
  2. Add an advisory/warning when a document/report boundary is `INTENTIONAL_PARTIAL` with structured-subfield-only grounding (split "mentions source text" from "mentions some subfield" in `source_material_binding_status`).
  3. Derive "final composer / broad composer" from **skeleton slot roles** on the create path — the skeleton already knows which slot composes the document body (`composition.document_body_writer_step_indexes`, `ai_builder_create_compiler.py:256`) — and keep token matching only as the edit-path fallback where no slot identity exists. This deletes most of the marker tables from the create path and makes it language-neutral by construction.
- **Acceptance criteria:** English and Swedish equivalents of "create the final document" flows produce the same binding mode; dropped refs appear in logs; document-boundary partial grounding warns.
- **Tests:** `test_targeted_underlag_binding_mode_is_language_invariant_for_document_composers`; `test_dropped_previous_field_refs_are_logged`; `test_document_boundary_with_subfield_only_underlag_warns`.
- **Risk/trade-off:** Part 3 touches the create compiler/skeleton seam — do it as its own slice with the 18 existing dataflow tests as the fence. Parts 1–2 are near-zero risk.
- **Confidence:** High on mechanics; medium on how often English flows occur today (product is Swedish-first, but nothing fences the builder to Swedish).

### F10 — `{{ indata_text }}` / `{{ indata_json }}` compiled unconditionally; resolver exposes them conditionally — **P3**

- **Problem:** Compiler emits them for bare text/JSON flow input (`ai_builder_new_step_compiler.py:426-431`); the resolver exposes `indata_text` only for non-empty stripped text (`variable_resolver.py:59-61`) and `indata_json` only for dict/list payloads (`:63-67`); run payload validation doesn't require them (`flow_run_input_payload.py`). Empty-text run → missing-key crash, same family as F2.
- **Fix:** Piggyback on F2's decision: declared primary text/JSON inputs get a defined (possibly empty) value, or run-start rejects empty primary input for flows compiled with these bindings. Pinned emission tests exist (`test_ai_builder_create_compiler.py` per prior verification), so change the runtime side, not the compiler.
- **Confidence:** High. Severity P3 because empty-payload runs are rarer than no-file runs.

### F11 — Redundant/diagnostic residue: double JSON parse, unreachable contract-skip diagnostic, double draft-ref normalization — **P3**

- `step_input_resolution.py:224-248`: with `used_question_binding`, JSON parse runs at `:229` and again at `:244-248` when the first fails — the second is dead by construction. The `flow_input_contract_skipped_for_binding` diagnostic (`step_execution_runtime.py:870-885`) guards a state the parser already rejects (`step_definition_parser.py:316-333`). `normalize_create_step_mechanics` runs ref sanitization twice around auto-binding (`ai_builder_create_dataflow.py:179-192`) — the second pass exists because auto-binding introduces refs; fine, but deserves the one-line reason it lacks. Cleanup tier; fold into adjacent work only.
- **Confidence:** High.

### F12 — Tolerant coercions in `flow_authoring_spec` are acceptable but undocumented as LLM-boundary policy — **P4**

- `FormFieldSpec.coerce_field_type` maps unknown types to `"text"` (`flow_authoring_spec.py:197-206`); `normalize_document_body_writer_step_refs` silently drops invalid refs (`:219-236`). For LLM payloads, coercion beats rejection; for manual API authors it hides typos. Not worth changing now — worth one comment stating the boundary these validators serve, so F3's stricter gate doesn't accidentally "fix" them.
- **Confidence:** Medium.

---

## Runtime Equivalence Gaps

| Dimension | Builder validation | Publish/manual (`flow_validators.py`) | Runtime parser | Runtime execution | Verdict |
|---|---|---|---|---|---|
| JSON array paths | Lenient (`ai_builder_validation_references.py:148-151`) | Not checked | Not checked | Strict numeric index (`variable_resolver.py:146-152`) | **Gap** (F4) |
| Contract-less JSON field refs | Skipped (`:143-146`) | Not checked | Not checked | Missing-key crash | **Gap** (F6) |
| `step_input` keys | Static 4-key map (`flow_variable_definitions.py:82-87`) | Same map via `consumes_runtime_input` | Not checked | 8 keys produced (`step_input_resolution.py:329-351`) | **Gap both directions** (F7) |
| `indata_text` / `indata_json` | Reserved roots accepted | Reserved roots skipped | Not checked | Conditionally present (`variable_resolver.py:59-67`) | **Gap** (F10) |
| Template expressions in instructions | Fully analyzed (`ai_builder_validation_references.py:26-166`) | **Never analyzed** | Never analyzed | Strict interpolation crash | **Gap** (F3) |
| Unknown binding roots | Rejected with suggestions | Silently allowed (`flow_validators.py:745-746`) | Not checked | Crash | **Gap** (F3) |
| Binding key whitelist | Via shared graph checks | Publish-strict only (`:322-329`) | Enforced (`step_definition_parser.py:479`) | n/a | Minor (drafts intentionally loose) |
| Contract-vs-question conflict | Enforced | Enforced (`:630-650`) | Enforced (`:480`) | Soft diagnostic (F11) | **Equivalent** — the one rule with a true single owner (`input_binding_contract_rules.py`); use it as the template |
| Runtime-input consumption | n/a | enabled⇒consume only (`:769-797`) | n/a | Checked only when files present (`step_input_resolution.py:200-206`) | **Gap both directions** (F2/F3) |
| Required files | n/a | n/a | n/a | Run-start only for `required=True` (`flow_run_step_inputs.py:266-277`); rerun skips when omitted (`flow_run_rerun_service.py:338-339`) | **Gap** (F2) |

---

## Delete / Merge / Move List

| Action | Target | Justification |
|---|---|---|
| **Delete** | Lenient default + false docstring in `ai_builder_json_schema_paths.py:13-20,29-37`; the pinning test `test_ai_builder_validator.py:731-767` (rewrite as rejection) | F4 — runtime grammar is the only grammar. |
| **Delete** | Direct `question=prepared.step_input.text` retrieval call shape (`step_execution_runtime.py:955`) | F1 — replace with derived bounded query. |
| **Delete** | Second (dead) JSON parse branch reachability + `flow_input_contract_skipped_for_binding` diagnostic (`step_execution_runtime.py:870-885`) | F11 — parser makes the state unreachable. |
| **Delete (create path)** | Most of `_UNDERLAG_*` marker/stemming tables once composer roles derive from skeleton slots (`ai_builder_create_dataflow.py:51-159`) | F9.3 — structure over string matching; keep a minimal fallback for edit-path steps. |
| **Merge** | `missing_draft_field_path` + `missing_structured_output_path` traversal cores | F4 — one path grammar, two node adapters. |
| **Merge** | `STEP_INPUT_KEY_SHAPES` into a producer-owned contract beside `_build_runtime_input_metadata` | F7. |
| **Merge** | Edit path's two `normalize_ai_builder_spec` invocations into one (`ai_builder_edit_compiler.py:137` vs `ai_builder_edit_proposal.py:126`) | F5 — preview must equal apply. |
| **Move** | Reference-grammar validation from Builder-only into `flow_validators.py`, Builder preflights it | F3. |
| **Move** | Terminal-artifact normalizers to edit-only application; on create, assert instead of repair (`ai_builder_step_transition_policy.py:294-564`) | Create skeleton already owns terminal shape; a normalizer that fires on create output is a masked compiler bug — log loudly, then error once telemetry confirms silence. |
| **Simplify** | Stale-alias fallback `return match.group(0)` (`ai_builder_edit_compiler.py:829-831`) → compile error | F8. |
| **Keep (explicitly)** | `input_binding_contract_rules.py`; `step_lineage.py`; `ai_builder_source_material.py` as grounding owner; the create-path heuristic folds in `ai_builder_create_compiler.py:654-733` (logged, bounded, cheap) | Working single-owner patterns; don't churn. |

---

## What Current Tests Already Cover

- **Shared graph rules well-fenced:** ordering, duplicate names, chain violations, HTTP configs, template-fill rules, citation modes, contract/binding conflict, forward binding refs, `step_input` allowance, publish-strict binding keys (`test_flow_validators.py:76-893`).
- **Builder reference validation:** unknown refs, future refs, unsupported paths, contract-field membership incl. composite schemas, numeric array indexes accepted (`test_ai_builder_validator.py:660-790`).
- **Underlag machinery breadth:** 18 tests on create dataflow; transition-policy suite covers rewires, terminal folding/promotion, source-material completion and intentional-partial preservation (`test_ai_builder_step_transition_policy.py:1362`); dedicated suites for structured field paths, skeleton, edit proposals incl. insertion remap (`test_ai_builder_edit_proposal.py:330-375`).
- **Runtime:** step execution, variable resolver, rerun repo/service, run step inputs, output formats each have dedicated suites (131 test files at flows level plus 100+ under `ai_builder/`).
- **Fences that pin the wrong contract (the notable defect):** lenient array acceptance (`test_ai_builder_validator.py:731`), intentional-partial preservation without a document-boundary carve-out (`:1362`), and compiled `{{ indata_text }}` emission (per prior verified review, `test_ai_builder_create_compiler.py:3643-3648`) — each will resist the correct fix until rewritten deliberately.

## Missing Red Tests

1. `test_complete_step_execution_derives_bounded_rag_query_from_large_step_input` (F1).
2. `test_resolve_step_input_builds_empty_metadata_when_runtime_input_enabled_without_files` + `test_optional_file_step_run_without_files_fails_typed_not_missing_key` (F2).
3. `test_validate_steps_rejects_unknown_binding_root` / `..._rejects_binding_structured_path_missing_from_output_contract` / `..._rejects_step_input_reference_when_runtime_input_disabled` / instructions-template variant (F3).
4. Flip of the lenient array test; keep numeric-index acceptance (F4).
5. `test_edit_proposal_approval_diff_matches_persisted_spec` (F5).
6. `test_structured_field_access_to_contractless_json_step_is_rejected` (F6).
7. `test_step_input_static_keys_match_runtime_metadata_contract` + `files_count` reference validity (F7).
8. `test_ordered_whole_plan_delete_blocks_stale_literal_step_alias_to_removed_order` (F8 — write as characterization first).
9. `test_targeted_underlag_binding_mode_is_language_invariant_for_document_composers` + dropped-ref logging + document-boundary partial-grounding warning (F9).
10. Rerun characterization: predecessor-file inheritance and fileless-predecessor behavior (F2 edge).

## What Is Not Worth Fixing

- **Wholesale replacement of token heuristics with an ML/semantic matcher** — F9.3 (slot roles) removes most of the need; don't build a matcher service.
- **A Builder-compiled `retrieval_query` authoring contract** — runtime derivation (F1) covers all flows including manual ones; revisit only if derivation proves insufficient with telemetry.
- **JSONB → relational moves** for anything in this scope (out of session anyway; prior agent verdicts stand).
- **Hand-built 1-based/0-based ref maps** in critic/policy code — internally consistent; fix opportunistically (prior finding #7, still P3).
- **`FormFieldSpec` coercions and `document_body_writer` silent drops** (F12) — LLM-boundary tolerance is a feature; add one explanatory comment when nearby.
- **Create-compiler fold/audio-drop heuristics** (`ai_builder_create_compiler.py:654-733`) — logged, bounded, and cheap; leave them.
- **Making interpolation lenient globally** — would convert loud failures into silent document corruption; F2/F10 are targeted contract fixes, not resolver softening.
- **Router/HTTP validator surfaces** — no equivalence gaps found in scope; already parser-enforced.

## From-Scratch Cleaner Design

If rebuilt from today's learnings, the shape is close to what exists, minus the duplicated ownership:

1. **One compile pipeline, one direction:** semantic intent → server architecture (skeleton slots carrying explicit *roles*: source-surfacer, extractor, composer, renderer) → dataflow binding derived from slot roles + declared refs. Role-driven binding replaces token matching on the create path entirely; string heuristics survive only as the edit-path fallback where model-authored steps have no slot identity.
2. **Reject vs. normalize split by ownership:** mechanics the model must not own (paths, joins, upload flags, topology) are normalized *with telemetry*; semantics the model must own (which steps, which fields, which sources) are rejected back into the repair loop with precise codes — never silently dropped (fixes the F9(b) class).
3. **One reference grammar** — the runtime resolver's — implemented once, consumed by one lifecycle gate in `flow_validators.py`; Builder, manual create/update, publish, and import all call it; the runtime parser keeps only cheap invariants and identity checks.
4. **`step_input` as a total contract:** when runtime input is enabled the metadata object always exists with a producer-owned typed schema; presence never depends on runtime data (fixes F2/F7 structurally).
5. **Retrieval query as a runtime derivation with provenance**, never the composed underlag (F1).
6. **Normalization runs exactly once per proposal**, and the approval diff is computed from the final spec (F5).
7. **Grounding as an invariant, not a heuristic:** "final artifact steps must reference the primary source text or an explicit summary field" becomes a validation rule with a user-visible warning, replacing the `INTENTIONAL_PARTIAL` silence.

This is a re-plumbing of ownership, not a rewrite — every needed mechanism (skeleton, `analyze_template`, `input_binding_contract_rules`, `step_lineage`, source-material module) already exists.

## Tomorrow Implementation Slices

| # | Slice | Files | Size |
|---|---|---|---|
| 1 | Bounded RAG query + provenance metadata (F1) | `step_execution_runtime.py`, `rag_retrieval.py`, tests | S |
| 2 | Always-built `step_input` metadata when enabled + typed empty-input error + rerun characterization tests (F2, F10 groundwork) | `step_input_resolution.py`, `step_input_validation.py`, tests | M |
| 3 | Strict array grammar everywhere + docstring + test flip (F4) | `ai_builder_json_schema_paths.py`, `ai_builder_validation_references.py`, tests | S |
| 4 | Shared reference-validation gate in `flow_validators.py`; Builder delegates (F3, carries F6) | `flow_validators.py`, `ai_builder_validation_references.py`, tests | L (its own slice, tier-2 review) |
| 5 | Producer-owned `step_input` key contract + parity test (F7) | `step_input_resolution.py`, `flow_variable_definitions.py`, tests | S |
| 6 | Stale-alias compile error on whole-plan deletes (F8) | `ai_builder_edit_compiler.py`, tests | S |
| 7 | Single edit-path normalization; diff == persisted spec (F5) | `ai_builder_edit_compiler.py`, `ai_builder_edit_proposal.py`, `ai_builder_compiled_spec_preparation.py`, tests | M |
| 8 | Dropped-ref logging + document-boundary partial-grounding warning (F9.1–9.2) | `ai_builder_create_dataflow.py`, `ai_builder_source_material.py`, `ai_builder_validation_quality.py`, tests | S |
| 9 | Slot-role-driven composer identity, delete Swedish marker tables from create path (F9.3) | `ai_builder_create_dataflow.py`, `ai_builder_step_skeleton.py` seam | L — plan-gate before starting |

Order 1→3 are independent and can land in any sequence; 4 before 6 is unnecessary but 4's machinery makes 6's test cleaner; 9 last.

## Claims Codex Must Verify

1. `ReferencesService.get_references` is reached from flows *only* via `retrieve_rag_chunks` with no session/files, so `CONCATENATE` degenerates to the raw question (`references.py:165-171`) — check for any other flow-side caller passing `embed_method`.
2. No code path builds `runtime_input_metadata` when `requested_file_ids` is empty (`step_input_resolution.py:108-117`) — including the audio branch and any HTTP-source interplay.
3. The edit approval object (`edit_result.approval`) is actually rendered to the user from `FlowBuilderProposalContent.edit` without recomputation downstream (frontend + apply service) — F5's user impact rests on this.
4. `_validate_binding_references` is the *only* template inspection in create/update/publish (`flow_service.py:114,237,435` → `flow_validators.py`) — confirm no router-level or repo-level validation I missed.
5. Every compiled `flow_input`+document/file/audio step carries the `{{ step_input.text }}` question binding (i.e., no `compile_step_input_bindings` branch returns `None` for that shape) — I traced `:268-277` as not applying to `flow_input`, verify with a compile test.
6. `MaterializedAddStep` on the edit path can reach compilation with `runtime_required=False` for a first-position file step (drives F2 severity on edits).
7. The prior-review line refs for pinned compiler emission tests (`test_ai_builder_create_compiler.py:3643-3648`, `:3725-3728`) still hold after the 2026-07-02/03 refactors.
8. `state.step_ref_mapping` used at `step_input_resolution.py:187` is built via `build_step_ref_mapping` including `existing_step_ref` aliases, so the underlag-summary diagnostic counts refs correctly on edited flows.

## Challenge This Brief

1. **"Post-hoc normalization" is not one thing.** The brief implies normalization is a smell to be deleted. At an LLM boundary, the correct rule is *ownership-based*: normalize backend-owned mechanics loudly (with telemetry), reject model-owned semantics precisely. Several normalizers here (all_previous rewire, template-fill key clearing, citation clearing) are legitimate and should stay; the defect is the *silent* subset and the *duplicated* subset, not the category.
2. **The brief's carry-forward frames rerun as a P1; source says P3.** Predecessor-file inheritance (`executor.py:1115-1132`) covers the normal case; the true P1 lives in the optional-input compiled default, first run included. Fixing "rerun validation" alone would miss the root cause.
3. **"Should RAG use an explicit bounded retrieval-query contract" presumes an authoring-side answer.** The cheaper, complete answer is runtime derivation — an authoring contract would leave manual flows broken and add a surface the discovery dialog would then have to ask about.
4. **The underlag question ("does it preserve enough?") has a hidden twin: "does it preserve it in the right shape?"** The single interpolated `question` string collapses provenance — the model cannot tell source text from prior analysis except by labels. A structured underlag (labeled sections passed as separate prompt parts) would make grounding auditable, but that is a v2 architecture change; nothing in this review requires it.
5. **The brief asks whether Builder compiles valid specs "directly."** The honest answer is: the create path mostly does (skeleton + typed intent), and the biggest threats to validity are not the LLM's payloads but the *system's own defaults* (F2) and *validation asymmetries* (F3/F4). Hardening the model boundary further has lower ROI than fixing the deterministic side.

## Confidence

**High overall.** Every finding above rests on source read end-to-end in this session, with file:line citations verified against current working-tree state; no claim depends on the parallel Fable sessions or on unverified artifact assertions. Medium-confidence spots are flagged inline: F5's user-visible frequency (depends on how the approval diff is consumed in the frontend — Codex claim 3), F9's English-flow prevalence (product is Swedish-first today), and F12's judgment call on tolerant coercions. The 2026-07-02 artifact line references I reused (two pinned compiler tests) are marked for re-verification (Codex claim 7); all other line references are from this session's reads.
