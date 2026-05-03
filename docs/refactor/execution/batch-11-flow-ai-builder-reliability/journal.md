# Batch 11 — Flow AI Builder Reliability Journal

## Status

11.5d IMPLEMENTATION COMPLETE

## Starting Point

- Branch: `feature/refactor-flows-flowai`
- HEAD at Batch 11 implementation start: `832f4c1b flows: close branding namespace docs`
- Previous completed source slice: Batch 10 Slice 10.6 branding namespace documentation closure
- Staged files at start: none
- Known unrelated dirty files:
  - `scripts/run_codex_review.sh`
  - `PRODUCT.md`
  - `docs/refactor/goals.md`
- Slices recorded in this journal: 11.0 through 11.5d Flow AI Builder
  reliability, slot resolution, skeleton, form-field/resource, structured-output,
  and local smoke-validation slices.

## 11.0a Slice Plan

Problem:
Batch 11 reliability targets need a fixed automated corpus before behavior
changes. The current benchmark harness covers deterministic discovery metrics,
but it does not pin the reported Swedish audio-to-DOCX failure or the six
manual smoke prompts as typed Flow-shape expectations.

Canonical owner:
`backend/tests/integration/flows/ai_builder/benchmark/cases.py` already owns AI
Builder prompt fixtures. 11.0a will extend that owner with a separate typed
reliability tuple instead of creating a parallel JSON corpus under `tests/data`.
Existing `BENCHMARK_CASES` remains the owner for pre-LLM discovery metrics.

Implementation:

- Add typed reliability dataclasses and cases to `backend/tests/integration/flows/ai_builder/benchmark/cases.py`.
- Add `backend/tests/integration/flows/ai_builder/benchmark/test_reliability_corpus.py`.
- Validate the corpus with existing slot vocabulary, Flow enums, and FCM tuple legality.
- Include the reported Swedish audio-to-DOCX failure plus the six manual-runbook prompts.
- Use a minimum-count and content-based reported-failure assertion; do not add JSON schema/hash machinery.
- Use these contract names: `CorpusSource`, `DomainCoupling`, `BehavioralRisk`, `ExpectedSlot`, `ExpectedStepShape`, `ExpectedFlowShape`, and `ReliabilityCorpusCase`.

Acceptance criteria:

- At least seven Swedish cases exist and IDs are unique.
- Exactly one case has source `reported_failure`, terminal DOCX output, and an explicit audio transcription step.
- All expected slot names come from `KNOWN_REQUIREMENT_SLOT_NAMES`.
- Flow shape values come from `FlowInputType`, `FlowOutputType`, and `FlowOutputMode`.
- Every expected step tuple is legal according to FCM.
- Coverage checks are derived from Flow enums with enum-typed exclusions where the corpus is not meant to cover a value.
- The corpus covers all `BehavioralRisk` values, including multi-document/source aggregation, sectioning, and structured-data-to-natural-language grounding.
- No planner/compiler/runtime behavior changes are included.

Tests required:

- Focused corpus test.
- Pyright and Ruff on the new test file.
- Diff check over touched paths.

Risk / trade-off:
This slice does not measure current pass/fail rates yet. It deliberately pins
the evaluation target first; 11.0b must add measurement hooks and baseline
numbers before 11.1 source behavior changes.

Human reviewability impact:
The diff should be small, data-first, and easy to review without understanding
the whole AI Builder compile path.

Confidence: high.

## 11.5b Proposal Boundary And Artifact Body Source Hardening

### Scope

This slice closes two related Batch 11 reliability gaps that surfaced after the
planner structured-output rail:

- proposal tool-call completions must not receive planner-only
  `response_format` kwargs when LiteLLM is called with `tools`;
- document artifact flows must not let a final body-writing step collapse into
  metadata-only JSON before the backend DOCX/PDF renderer runs.

The second gap came from a live audio-to-DOCX debug export where the penultimate
step returned only `docx_title` and `document_sections_count`, then the terminal
DOCX step consumed that tiny JSON instead of the content-rich section text.

Canonical owners:

| Concept | Owner | Decision |
|---|---|---|
| Proposal tool-call completion kwargs | `AIBuilderProposalProcessor.call_proposal_completion` | Strip planner `response_format` and caller-owned `drop_params` at the central proposal seam. |
| Backend-owned artifact mechanics | `StepSkeletonPlan` | Keep content-bearing semantic steps as text when they feed backend-fixed text artifact consumers. |
| Document body fan-in | `StepSkeletonPlan._last_document_body_reads_all_prior_work` | Multi-phase DOCX/PDF body steps use `all_previous_steps` so earlier structured sections reach synthesis. |
| JSON-to-text underlag bridge | `compile_input_bindings` | Explicitly bind `{{ previous.output.structured }}` when a text step consumes previous JSON. |

### Implementation Result

| Area | Outcome |
|---|---|
| Proposal seam naming | Renamed the public proposal helper from `call_repair_completion` to `call_proposal_completion`; no compatibility alias was kept. |
| Proposal kwargs | `response_format` is dropped before proposal LiteLLM calls; ordinary provider kwargs such as `api_base` still pass through. |
| Artifact body output type | Final semantic content steps feeding backend-fixed text consumers stay `output_type=text` even when the LLM asks for JSON output fields. |
| Drift evidence | Skeleton output drift records `dropped_output_fields=True` when JSON fields are intentionally dropped. |
| Document body fan-in | Final semantic body steps in DOCX/PDF `text_for_all_semantic` flows with three or more semantic phases use `all_previous_steps`. |
| Underlag bridge | Text steps consuming previous JSON get `{{ step_a.output.structured }}` unless specific `uses_previous_fields` select narrower bindings. |
| Runbook | Added local audio fixture, graph/evidence/artifact endpoints, and definitions for primary runtime input, `Inmatningsfält`, and `Underlag till text`. |

### Validation Result

| Command | Result |
|---|---|
| `uv run pytest tests/unittests/flows/ai_builder/test_ai_builder_step_skeleton.py tests/unittests/flows/ai_builder/test_ai_builder_create_compiler.py tests/unittests/flows/ai_builder/test_ai_builder_proposal_processor.py tests/unittests/flows/ai_builder/test_ai_builder_proposal_repair.py tests/unittests/flows/ai_builder/test_ai_builder_parse_repair.py tests/unittests/flows/ai_builder/test_ai_builder_response_format.py -q` | Passed: `187 passed, 1 warning`. |
| `uv run ruff check <11.5b touched source and test files>` | Passed. |
| `uv run ruff format --check <11.5b touched source and test files>` | Passed. |
| `uv run pyright <11.5b touched source and test files>` | Passed: `0 errors, 0 warnings, 0 informations`. |
| Local API smoke: create/approve/apply/publish audio-to-DOCX builder plan | Passed. Flow `6d31e3f5-a004-4432-9424-c69b285dbd44` created six steps with body step `input_source=all_previous_steps` and terminal step `output_type=docx`. |
| Local API smoke: run generated flow with `utvecklingssamtal.mp3` | Passed. Run `78f4599b-dae8-4c0d-9c43-a012e2cac338` completed and generated `step_6_output.docx`. |
| Local API smoke: evidence and artifact endpoints | Passed. `steps/`, `evidence/`, `evidence/export?format=json`, and artifact signed-url all returned `200`. |

Docker validation note: `docker exec eneo-41ae93-eneo-1 ...` was attempted after
the user authorized it, but the current tool approval policy rejected docker
execution before the command reached the container. The same targeted validation
was therefore run locally in the backend environment.

### Claude Implementation Review

| Iteration | Artifact | Verdict | Green light | Minimum score | Outcome |
|---:|---|---|---|---:|---|
| 1 | `.codex/artifacts/claude-peer-loop-batch-11-flow-builder-reliability-architecture-20260503T084034Z.md` | `changes_required` | `no` | 6 | Rejected a proposed extra synthesis step and identified skeleton output/input mechanics as the right owner. |
| 2 | `.codex/artifacts/claude-peer-loop-batch-11-flow-builder-reliability-architecture-20260503T085003Z.md` | `green` | `yes` | 7 | Approved the skeleton gate and JSON-to-text bridge direction. |
| 3 | `.codex/artifacts/claude-peer-loop-batch-11-flow-ai-builder-final-verification-after-live-smoke-20260503T090402Z.md` | `GREEN-LIGHT-WITH-FOLLOWUPS` | `YES` | 7.5 | Approved the final body fan-in fix; requested a named threshold plus PDF and four-phase tests. |

Accepted final-review follow-ups:

| Finding | Resolution |
|---|---|
| The `> 2` fan-in threshold was principled but unnamed. | Added `_MIN_DOCUMENT_BODY_FAN_IN_PHASES = 3`. |
| PDF terminal membership was not covered. | Parameterized the document artifact fan-in test over `docx` and `pdf`. |
| Four semantic phases were not covered. | Added an audio-to-DOCX four-phase body fan-in regression. |

### Live Smoke Result

Prompt:

```text
Jag vill bygga ett transkriberingsflöde där jag kommer att spela in en ljudfil
eller skicka in en ljudfil som sedan transkriberas. Därefter ska mötet delas upp
i rubriker för ett kommunstyrelsemöte: föregående protokoll, nuvarande
protokoll, introduktion, syfte, farhågor, slutsatser och en sammanfattning av
allt ovan. Jag vill ha en Word-fil i slutet.
```

Observed flow shape after apply:

| Step | Input | Output | Source | Purpose |
|---:|---|---|---|---|
| 1 | audio | text | flow_input | transcribe only |
| 2 | text | json | previous_step | transcript metadata |
| 3 | json | json | previous_step | meeting sections |
| 4 | json | json | previous_step | quality check |
| 5 | text | text | all_previous_steps | Word document body |
| 6 | text | docx | previous_step | backend DOCX artifact |

The generated run used the actual development-conversation transcript and
produced the requested headings. It no longer generated unrelated generic group
workflow prose.

### Carry-Forward

| Item | Owner |
|---|---|
| The builder still asked avoidable `input_material_mode` and `final_output_mode` follow-up questions in live smoke even though discovery analysis resolves the same prompt locally. | 11.2/next question-selection slice. |
| `StepSkeletonPlan` now has two last-semantic fan-in rules. They do not conflict today, but should be unified if a third fan-in rule appears. | Later skeleton cleanup. |
| `PlannerOutput` strict-schema compatibility remains undecided. | Later structured-output contract slice. |

## 11.5c Terminal Output Clause Anchors And Audio-File Input Resolution

### Scope

This slice targets the follow-up question-quality gap carried from 11.5b. The
live Swedish prompt clearly said the user would provide a `ljudfil` and wanted a
`Word-fil i slutet`, but the deterministic discovery path still selected input
and output questions.

Local evidence before implementation:

| Check | Result |
|---|---|
| `build_planning_state_from_conversation(...)` for the live-smoke prompt | Resolved no slots. |
| `analyze_discovery(...)` for the live-smoke prompt | Selected `flow_input_architecture` and `final_output_mode`. |
| Input root cause | The input clause swallowed the terminal `Word-fil i slutet` phrase, so input detection saw document evidence that belonged to the final output. |
| Output root cause | `Word-fil i slutet` did not have an explicit output verb in the minimal repro, so output intent looked only at the leading neutral/audio fragment. |

### Claude Plan Review

| Iteration | Artifact | Verdict | Green light | Minimum score | Outcome |
|---:|---|---|---|---:|---|
| 1 | `.codex/artifacts/claude-peer-loop-batch-11-5c-question-policy-audio-word-plan-20260503T093253Z.md` | timeout | no output | n/a | Timed out after 240 seconds. |
| 2 | `.codex/artifacts/claude-peer-loop-batch-11-5c-question-policy-audio-word-plan-retry-20260503T093545Z.md` | `changes_required` | `no` | 6 | Rejected downstream output fallbacks and pointed the fix at clause segmentation plus a precise audio-file guard. |

Accepted plan changes:

| Finding | Resolution |
|---|---|
| Output fallback in `ai_builder_framework_policy.py` would deepen an overloaded heuristic chain. | Move terminal artifact phrasing to the clause segmenter instead. |
| Audio-file upload should not suppress real mixed audio plus document flows. | No new guard was needed after clause scoping; mixed `ljudfil + dokument/bilaga/pdf/docx` remains a clarification case. |
| Phrase hardcoding should stay generic. | Use terminal-position anchors and artifact nouns, not transcription or municipality-specific strings. |

### Planned Validation

| Command | Purpose |
|---|---|
| `uv run pytest tests/unittests/flows/ai_builder/test_ai_builder_clause_segmenter.py tests/unittests/flows/ai_builder/test_ai_builder_input_architecture_policy.py tests/unittests/flows/ai_builder/test_planning_state_builder.py tests/unittests/flows/ai_builder/test_discovery_flow.py -q` | Focused behavior coverage for clause scoping, input resolution, PlanningState, and discovery questions. |
| `uv run pyright <11.5c touched source and test files>` | Type safety. |
| `uv run ruff check <11.5c touched source and test files>` | Lint. |
| `uv run ruff format --check <11.5c touched source and test files>` | Formatting. |
| `git diff --check -- <11.5c touched paths>` | Whitespace/review hygiene. |

### Implementation Outcome

| Result | Evidence |
|---|---|
| Terminal Word/PDF/DOCX artifact phrasing is scoped as output only when the artifact is near a terminal-position marker and is not the uploaded input file itself. | `ai_builder_clause_segmenter.py` terminal output clause tests. |
| `Skicka in en DOCX i slutet` and `Ladda upp en PDF i slutet` stay document input. | Input policy regression tests. |
| The reported Swedish audio-to-Word prompt resolves `primary_runtime_input=audio`, `terminal_output=docx_document`, and `docx_output_mode=generated_docx` without a follow-up question. | PlanningState and discovery tests. |
| No audio-file document guard was added because the root issue was clause scoping; genuine mixed `ljudfil + dokument` still asks for architecture clarification. | Input policy mixed-mode test. |

### Validation Result

| Check | Result |
|---|---|
| Focused unit suite | `98 passed, 1 warning`. |
| AI Builder benchmark corpus | `18 passed, 16 warnings`. |
| `ruff check` on touched source/tests | Passed. |
| `ruff format --check` on touched source/tests | Passed. |
| `pyright` on touched source/tests | Passed. |
| `git diff --check` on touched paths | Passed. |
| Claude iteration 2 | `.codex/artifacts/claude-peer-loop-batch-11-5c-terminal-output-clause-implementation-verification-20260503T094834Z.md`; `GREEN_LIGHT: no`, found terse DOCX/PDF upload regression. |
| Claude iteration 3 | `.codex/artifacts/claude-peer-loop-batch-11-5c-terminal-output-clause-final-verification-20260503T095532Z.md`; `GREEN_LIGHT: yes`, `MIN_SCORE: 8`. |
| Live AI Builder smoke | Session `821c84f5-7d0e-4ce5-8b05-5be60f2a55fc`; prompt produced requirements summary with `Indata vid körning: Ljud`, `Slutresultat: DOCX-dokument`, and no question events. |
| Live plan smoke | Plan `126ead32-e909-46d2-99ee-6451ce8865d6`; produced a 5-step audio → text → JSON → text → DOCX chain with no duplicate DOCX artifact step. |

Live smoke follow-up observation:

| Observation | Disposition |
|---|---|
| The live planner added optional runtime fields for language, document style, and timestamps. They are valid form fields and the binding references resolve, but they were inferred rather than requested. | Track in a later runtime-field minimality slice; this 11.5c slice fixed avoidable discovery questions and terminal output scoping. |

## 11.5d Runtime Metadata Minimality And Source-Material Underlag Dataflow

### Scope

This slice closes the runtime-field and underlag gaps exposed by the latest
debug export:

- the generated flow accepted only an audio file at runtime, but the planner
  still inferred optional form fields for language/style/timestamps;
- step 4 generated protocol sections from step 3 metadata JSON and did not
  receive the original transcript as `Underlag till text`;
- step 6 rendered DOCX content from whatever previous text it saw, while the
  effective prompt showed only generic terminal instructions.

The fix stays out of prompt repair. `Underlag till text` remains the
step-input/dataflow owner, and `Inmatningsfält` remains secondary user-supplied
runtime metadata.

### Claude Review

| Iteration | Artifact | Verdict | Green light | Minimum score | Outcome |
|---:|---|---|---|---:|---|
| 1 | `.codex/artifacts/claude-peer-loop-batch-11-5d-runtime-field-gating-plan-20260503T101054Z.md` | `changes_required` | `no` | n/a | Pushed the runtime-field fix away from prompt text and toward resolved metadata state. |
| 2 | `.codex/artifacts/claude-peer-loop-batch-11-5d-runtime-field-gating-revised-plan-20260503T101533Z.md` | `green` | `yes` | n/a | Approved compiler-gated runtime fields. |
| 3 | `.codex/artifacts/claude-peer-loop-batch-11-5e-swedish-audio-input-architecture-brittleness-20260503T110606Z.md` | `changes_required` | `no` | n/a | Identified that audio/document confusion needed architectural input resolution, not more Swedish prompt wording. |
| 4 | `.codex/artifacts/claude-peer-loop-batch-11-5e-long-term-llm-first-flow-ai-builder-architecture-20260503T111809Z.md` | `changes_required` | `no` | n/a | Rejected an LLM-first workaround and asked for deterministic slot/source-material ownership. |
| 5 | `.codex/artifacts/claude-peer-loop-batch-11-5f-flow-ai-builder-underlag-dataflow-plan-20260503T113034Z.md` | `changes_required` | `no` | n/a | Required a smaller typed source-scope contract. |
| 6 | `.codex/artifacts/claude-peer-loop-batch-11-5f-revised-source-scope-dataflow-plan-20260503T114010Z.md` | `changes_required` | `no` | n/a | Approved the direction but asked to keep it in skeleton/compiler mechanics. |
| 7 | `.codex/artifacts/claude-peer-loop-batch-11-5f-underlag-dataflow-implementation-verification-20260503T115438Z.md` | `green` | `yes` | 7 | Verified the implementation with small follow-ups. |
| 8 | `.codex/artifacts/claude-peer-loop-batch-11-5d-underlag-runtime-final-verdict-format-20260503T121823Z.md` | `green` | `yes` | 8 | Re-verified final follow-ups, docs, typed runtime metadata gating, and parser-readable green light. |

Accepted final-review follow-ups:

| Finding | Resolution |
|---|---|
| `uses_previous_outputs` should be backend-owned and hidden from the outline tool schema. | Added it to `_OUTLINE_STEP_BACKEND_OWNED_KEYS` and schema coverage. |
| Previous-output refs should target text producers only. | Validator and dataflow normalization reject/prune non-text references. |
| Dead previous-output instruction branch should be removed. | Kept source-material references in `input_bindings.question`; removed the unused instruction branch. |
| Source-material label should localize. | Swedish skeleton compilation uses `Källmaterial`; English uses `Source material`. |
| The input-type override needed a reason. | Added a short invariant comment where source foundation refs force text input. |
| PDF parity should be explicit. | Added PDF coverage showing all-previous fan-in remains the PDF-safe shape. |

### Implementation Result

| Area | Outcome |
|---|---|
| Previous text-output refs | Added `PreviousOutputRef` and `NewStepDraft.uses_previous_outputs` for typed non-adjacent text dependencies. |
| Underlag rendering | `compile_input_bindings` now renders immediate previous JSON plus explicit prior text outputs in one `question` binding. |
| Validation and normalization | Invalid/future/duplicate/non-text previous-output refs are rejected or pruned before compilation. |
| Audio source foundation | Audio-to-document skeletons attach the first transcription text as `Källmaterial` / `Source material` to downstream semantic document steps. |
| Runtime metadata minimality | Resolved primary runtime inputs default to `no_extra_metadata`; outline `input_fields` are dropped unless metadata is explicitly allowed. |
| Audio input resolution | Runtime audio upload phrasing wins when explicit, and final Word/PDF/DOCX artifact language no longer displaces the source material type. |
| Redundant transcription steps | LLM-authored leading transcription steps are dropped or rewritten because the backend owns the transcribe-only prefix. |
| Artifact body naming | Pre-terminal DOCX/PDF text steps are renamed to prepare content so terminal artifact steps remain the file creators. |

### Validation Result

| Command | Result |
|---|---|
| `uv run pytest tests/unittests/flows/ai_builder -q` | Passed: `1811 passed, 4 skipped`, 12 existing warnings. |
| `uv run pytest tests/integration/flows/ai_builder/benchmark/test_slot_resolver_corpus.py tests/integration/flows/ai_builder/benchmark/test_baseline_benchmark.py -q` | Passed: `69 passed`, 16 existing warnings. |
| `uv run ruff check <11.5d touched source and test files>` | Passed after deleting one unused helper found by Pyright/Ruff review. |
| `uv run pyright <11.5d touched source and test files>` | Passed after deleting `_mentions_document_reference`, which the proximity-based runtime-file helper replaced. |
| `git diff --check -- <11.5d touched paths>` | Passed. |
| `docker exec -w /workspace/backend eneo-41ae93-eneo-1 ...` | Blocked before Docker ran by tool policy: `approval required by policy, but AskForApproval is set to Never`. |

### Regression Evidence

| Failure mode from debug export | Guard now covering it |
|---|---|
| Protocol step saw only metadata JSON and not the transcript. | `test_compile_outline_audio_docx_protocol_step_keeps_transcript_underlag` pins `{{ step_c.output.structured }}` plus `Källmaterial: {{ step_a.output.text }}`. |
| Optional runtime fields were inferred from likely preferences instead of requested metadata. | `test_compile_outline_flow_drops_runtime_fields_when_metadata_is_disabled` drops language/style/timestamps under `no_extra_metadata`. |
| LLM-generated transcription step duplicated backend transcribe-only mechanics. | Outline compiler tests cover dropping plain duplicate transcription steps and rewriting structured transcript extraction steps. |
| Final artifact phrasing made intermediate text steps sound like file creators. | Step-transition tests rename pre-terminal DOCX/PDF body text steps to content preparation. |

### Carry-Forward

| Item | Owner |
|---|---|
| Add live local API smoke for this exact reported debug-export flow when the local API is reachable in a non-blocked tool path. | Manual eval harness / next smoke slice. |
| Consider an explicit source-scope enum if a second source-material pattern needs more than prior text-output refs. | Later skeleton/compiler cleanup, only with another concrete use case. |
| Promote the exact Swedish audio prompt into the benchmark expectation corpus if it recurs outside unit-level compile coverage. | Benchmark corpus slice. |

## 11.6 Local Manual API Smoke Harness

### Scope

This slice adds the long-term measurement loop for the 11.5d
`Underlag till text` and `Inmatningsfält` fixes. It deliberately reuses the
existing AI Builder benchmark owner instead of adding a new `scripts/manual_eval`
path.

The slice is local-only by default:

- dry-run scorecards validate typed prompt cases without calling the API or LLM;
- live mode is opt-in through `ENEO_LOCAL_API_BASE`,
  `ENEO_LOCAL_SPACE_ID`, and `ENEO_LOCAL_API_KEY`;
- committed scorecards are redacted and never include raw prompts, API keys,
  transcripts, uploaded files, raw SSE streams, or unredacted UUIDs.

### Claude Review

| Iteration | Artifact | Verdict | Green light | Minimum score | Outcome |
|---:|---|---|---|---:|---|
| 1 | `.codex/artifacts/claude-peer-loop-batch-11-6-manual-api-smoke-harness-plan-20260503T123145Z.md` | `changes_required` | `no` | 4 | Rejected a parallel scripts/YAML/JSON-Schema harness and flagged the committed local API key. |
| 2 | `.codex/artifacts/claude-peer-loop-batch-11-6-manual-api-smoke-harness-revised-plan-20260503T123747Z.md` | `green` | `yes` | 7 | Approved the benchmark-owner plan with implementation clarifications. |
| 3 | `.codex/artifacts/claude-peer-loop-batch-11-6-manual-api-smoke-harness-implementation-review-20260503T125738Z.md` | `changes_required` | `no` | 5 | Blocked audio-only underlag scoring, runtime-field false positives, missing live model provenance, and untested live HTTP path. |
| 4 | `.codex/artifacts/claude-peer-loop-batch-11-6-manual-api-smoke-harness-final-implementation-20260503T131550Z.md` | `green` | `yes` | 8 | Substantively approved the structural fixes; wrapper failed parsing because Claude emitted Markdown-bold headers. |
| 5 | `.codex/artifacts/claude-peer-loop-batch-11-6-manual-api-smoke-harness-final-green-confirmation-20260503T131704Z.md` | `green` | `yes` | 8 | Exact output-contract confirmation cleared the wrapper gate. |
| 6 | `.codex/artifacts/claude-peer-loop-batch-11-6-manual-api-smoke-harness-post-green-cleanup-20260503T132425Z.md` | `green` | `yes` | 8 | Verified post-green cleanup for exact case-id validation, provider-disambiguated model matching, and redacted live failure status. |

Accepted plan changes:

| Finding | Resolution |
|---|---|
| New `backend/scripts/manual_eval` path would duplicate the benchmark eval pattern. | Harness lives under `backend/tests/integration/flows/ai_builder/benchmark/`. |
| `prompts.yaml` would create a second prompt owner. | Harness references existing `RELIABILITY_CORPUS_CASES` manual-runbook entries. |
| `scorecard.schema.json` would duplicate serializer/dataclass state. | Frozen dataclasses own the scorecard contract and version policy. |
| Literal local API key contradicted redaction rules. | Replaced with `ENEO_LOCAL_API_KEY` placeholder and removed the key from current docs. |
| `uses_underlag_till_text_correctly` was subjective. | Added deterministic source-material boundary scoring and bad/good fixtures. |
| AI Builder SSE parsing was undeclared. | Added a harness SSE parser with tests for multiline data, ping/comment lines, error, and done events. |
| Endpoint snapshot could drift. | Live mode validates required OpenAPI `operationId` values. |

### Implementation Result

| Area | Outcome |
|---|---|
| Shared eval primitives | Added `eval_support.py` for redaction hashes, ISO timestamps, dataclass scorecard serialization, and stable JSON fingerprints. |
| Manual API scenarios | Added typed manual API scenario metadata to the existing benchmark case owner without duplicating the six prompts. |
| Deterministic scoring | Added `manual_api_scoring.py` for typed plan observations, source-material underlag predicates, runtime-field minimality, and chain compatibility. |
| Local harness | Added `manual_api_eval.py` with dry-run scorecards, env-gated live config, OpenAPI operation-id validation, SSE streaming parse, model provenance, redacted IDs, prompt/mode filters, unsupported-scenario filtering, redacted live failure status, and output directory writing. |
| Regression fixtures | Added bad/good plan-shape tests for the reported metadata-only JSON plus invented runtime-field failure, the 11.5d post-fix shape, document source-material boundaries, allowed secondary runtime fields, live MockTransport happy path, and redacted live failure handling. |
| Runbook and storage | Removed the literal local key, documented dataclass scorecards, hashed IDs, operation ids, SSE parser responsibility, version precedence, and manual-eval result storage rules. |

### Validation Result

| Command | Result |
|---|---|
| `uv run pytest tests/integration/flows/ai_builder/benchmark/test_manual_api_eval.py -q` | Passed: `13 passed`, 16 existing warnings. |
| `uv run pytest tests/integration/flows/ai_builder/benchmark/test_manual_api_scoring.py -q` | Passed: `4 passed`, 16 existing warnings. |
| `uv run pytest tests/integration/flows/ai_builder/benchmark -q` | Passed: `106 passed`, 16 existing warnings. |
| `uv run ruff check <11.6 touched benchmark files>` | Passed after import cleanup. |
| `uv run ruff format --check <11.6 touched benchmark files>` | Passed after formatting. |
| `uv run pyright <11.6 touched benchmark files>` | Passed: `0 errors`. |

### Carry-Forward

| Item | Owner |
|---|---|
| Live local API scorecards still need to be run outside this tool environment once the local API key is set in the shell. | Manual eval operator |
| Content-changing `revise_plan` scenarios are represented but marked unsupported until the API supports a real content revision path beyond `keep_current_description`. | AI Builder API/edit parity slice |
| Executed-run artifact/evidence scoring is operation-id-gated but not called by dry-run. | Future manual eval execution slice |

## 11.0a Claude Plan Review Iteration 1

- Artifact: `.codex/artifacts/claude-peer-loop-batch-11-production-failure-corpus-plan-20260502T232903Z.md`
- Verdict: `changes_required`
- Green light: `no`
- Minimum score: `4`

Accepted findings and changes:

| Finding | Change |
|---|---|
| A new JSON corpus under `tests/data` would create a parallel prompt owner next to the existing AI Builder benchmark cases. | Moved the 11.0a owner to `backend/tests/integration/flows/ai_builder/benchmark/cases.py` and kept discovery metrics and reliability expectations as separate tuples in the same owner. |
| JSON + Pydantic + schema/hash would overbuild a seven-case corpus. | Replaced JSON fixture parsing with frozen dataclasses and closed source/domain tags. |
| The reported failure should not be pinned only by a magic case id. | Made the test requirement content-based: exactly one reported-failure case must include an audio-to-DOCX shape. |
| Flow-shape values must be checked against FCM, not only enum strings. | Added FCM tuple legality to the 11.0a acceptance criteria and test plan. |
| Source provenance needs a closed set. | Added a typed `CorpusSource` requirement. |
| `production_failures` overstates six manual-runbook prompts as failures. | Renamed the slice artifact to reliability corpus; the reported failure remains a tagged case. |
| Prose risk coverage should not become a brittle keyword list. | Changed coverage to enum-derived checks plus explicit exclusions and named behavioral assertions. |

### Plan Verification Iteration 2

- Artifact: `.codex/artifacts/claude-peer-loop-batch-11-reliability-corpus-plan-verification-20260502T233406Z.md`
- Verdict: `green`
- Green light: `yes`
- Minimum score: `7`

Accepted polish:

| Finding | Change |
|---|---|
| Minimum count said six although the slice requires reported failure plus six manual prompts. | Raised the minimum to seven. |
| Expected-shape/source/risk types were named only generically. | Pinned `CorpusSource`, `DomainCoupling`, `BehavioralRisk`, `ExpectedSlot`, `ExpectedStepShape`, `ExpectedFlowShape`, and `ReliabilityCorpusCase`. |
| The reported failure needs to pin the actual transcribe-only bug. | Required an explicit `audio -> text / transcribe_only` step in the reported-failure shape. |
| Enum exclusions could drift if represented as strings. | Required enum-typed exclusions with rationales. |
| Behavioral risk coverage was still prose. | Required a `BehavioralRisk` enum and full enum coverage. |
| Unit-to-integration import coupling was avoidable. | Moved the planned test to the benchmark integration package next to the case data. |
| The existing benchmark harness should be validated after extending its case owner. | Added `test_baseline_benchmark.py` to validation. |

## 11.0a Implementation Result

Implemented:

- `backend/tests/integration/flows/ai_builder/benchmark/cases.py` now owns `RELIABILITY_CORPUS_CASES` next to `BENCHMARK_CASES`.
- The reliability corpus uses frozen dataclasses for `ExpectedSlot`, `ExpectedStepShape`, `ExpectedFlowShape`, and `ReliabilityCorpusCase`.
- Closed enums now tag source provenance, domain coupling, and behavioral risks.
- The corpus includes the reported Swedish audio-to-DOCX failure plus the six stable Swedish manual-runbook prompts.
- `backend/tests/integration/flows/ai_builder/benchmark/test_reliability_corpus.py` validates:
  - minimum count and unique IDs
  - manual-runbook prompt IDs
  - Swedish-only language and closed tags
  - content-based reported-failure detection
  - explicit `audio -> text / transcribe_only` reported-failure step
  - canonical requirement-slot names
  - internal shape consistency
  - FCM-legal step tuples and chains
  - enum-derived Flow input/output/mode coverage with typed exclusions
  - full `BehavioralRisk` coverage
  - behavioral-risk tags backed by typed evidence
  - domain-coupling limited to the reported failure

Behavior changes:

- none. This slice changes test data and tests only.

Validation:

| Command | Result |
|---|---|
| `cd backend && uv run pytest tests/integration/flows/ai_builder/benchmark/test_reliability_corpus.py tests/integration/flows/ai_builder/benchmark/test_baseline_benchmark.py -q` | Passed: `75 passed`; warnings were pre-existing deprecations in unrelated packages. |
| `cd backend && uv run pytest tests/integration/flows/ai_builder -q` | Passed after Claude review polish: `79 passed, 20 deselected`; warnings were pre-existing deprecations in unrelated packages. |
| `cd backend && uv run pyright tests/integration/flows/ai_builder/benchmark/cases.py tests/integration/flows/ai_builder/benchmark/test_reliability_corpus.py` | Passed: `0 errors, 0 warnings, 0 informations`. |
| `cd backend && uv run ruff check tests/integration/flows/ai_builder/benchmark/cases.py tests/integration/flows/ai_builder/benchmark/test_reliability_corpus.py` | Passed. |
| `cd backend && uv run ruff format --check tests/integration/flows/ai_builder/benchmark/cases.py tests/integration/flows/ai_builder/benchmark/test_reliability_corpus.py` | Passed after formatting the new test file. |
| `cd backend && uv run lint-imports --no-cache` | Passed: 3 contracts kept, 0 broken. |
| `git diff --check -- backend/tests/integration/flows/ai_builder/benchmark/cases.py backend/tests/integration/flows/ai_builder/benchmark/test_reliability_corpus.py docs/refactor/execution/batch-11-flow-ai-builder-reliability docs/refactor/prd/PRD-011-flow-ai-builder-reliability.md docs/refactor/implementation-order.md` | Passed. |
| `./scripts/gate-local/anti_slippage.sh --worktree` | Passed: `anti-slippage: worktree clean`. |

Known carry-forward:

- 11.0b must add first-attempt compile/repair measurement hooks and write baseline numbers before 11.1 behavior changes.
- 11.2 must replace or validate free-form `ExpectedSlot.value` strings against the typed slot resolver vocabulary once that vocabulary exists.
- 11.2 should reuse the same corpus owner decision unless a new owner is justified with a stronger reason than convenience.

## 11.0a Claude Implementation Review

- Artifact: `.codex/artifacts/claude-peer-loop-batch-11-reliability-corpus-implementation-20260502T234807Z.md`
- Verdict: `green`
- Green light: `yes`
- Minimum score: `8`

Accepted polish after green:

| Finding | Change |
|---|---|
| Prompt non-empty validation would make the runtime language/tag test less tautological. | Added a prompt `.strip()` assertion to `test_cases_are_swedish_with_closed_provenance_tags`. |
| Free-form `ExpectedSlot.value` strings are a deferred debt for the slot resolver. | Recorded 11.2 carry-forward in the journal and retrospective. |

Codex explicitly did not add Claude's optional duplicate-shape comment because
the duplicate reported/vague audio-to-DOCX shape is already pinned by typed tests
and an added comment would be easy to turn into restating noise.

## 11.0b Slice Plan

Problem:
11.0a pinned the reliability corpus, but the proposal task still lacked a
typed measurement contract for first-attempt proposal outcomes and repair
reasons. The create path had a string-form first-attempt log, while edit and
missing-tool forced retry paths did not have equivalent proposal telemetry.

Canonical owners:

| Concept | Owner | Decision |
|---|---|---|
| Per-turn `planner_telemetry` dict shape | `backend/src/intric/flows/ai_builder/ai_builder_telemetry.py` | Keep this as the only owner of the telemetry dict fields. |
| Proposal turn token/attempt accounting | `backend/src/intric/flows/ai_builder/ai_builder_proposal_telemetry.py` | Move the processor-local tracker into a narrow proposal telemetry module and rename it to `ProposalTurnTelemetry`. |
| Tool-result failure taxonomy | `ToolProcessingFailureKind` | Type internal repair-loop values: `parse`, `recoverable_parse`, `validation`, and `quality`. |
| Sanitized proposal failure taxonomy | `ProposalFailureKind` | Expose proposal measurement values: `parse`, `validation`, `quality`, and `missing_submission_tool`. |

Implementation:

- Extend canonical `build_planner_telemetry` with optional proposal fields.
- Add `ProposalTurnTelemetry` for one proposal turn.
- Record first-attempt proposal outcome and repair reason for:
  - create `outline_flow`
  - edit `edit_flow`
  - missing required proposal tool followed by forced retry
- Keep `confirm_requirements` and discovery-question repair out of proposal
  compile telemetry.
- Tighten `ToolProcessingResult.failure_kind` and proposal repair signatures to
  the internal typed taxonomy.
- Add unit coverage for telemetry payloads, structured log payloads,
  first-attempt idempotency, no-tool forced retry, edit parse failure, and
  failure-kind taxonomy drift.
- Write deterministic baseline numbers before starting 11.1.

Acceptance criteria:

- A successful initial create proposal stores `proposal_first_attempt_success=true`
  on planner telemetry.
- A repaired proposal stores the original first-attempt failure kind and repair
  reason.
- A missing-tool first attempt remains `missing_submission_tool` even if forced
  retry succeeds.
- Edit proposal parse/process failures produce the same measurement shape.
- No public API telemetry shape or frontend generated type changes are required.

Risk / trade-off:
The live LLM first-attempt success rate is not measured by this deterministic
slice. The manual API baseline remains governed by `manual-eval-runbook.md`
until a local API run is performed with the required workspace/model fixture.

Human reviewability impact:
Reviewers can see proposal measurement as a narrow telemetry extraction plus
recording calls. Behavior changes are intentionally out of scope.

Confidence: high after Claude plan iteration 3.

## 11.0b Claude Plan Review

### Iteration 1

- Artifact: `.codex/artifacts/claude-peer-loop-batch-11-0b-proposal-reliability-measurement-plan-20260503T000534Z.md`
- Verdict: `changes_required`
- Green light: `no`
- Minimum score: `6`

Accepted findings and changes:

| Finding | Change |
|---|---|
| Proposal telemetry fields would split the `planner_telemetry` schema if added directly by the new module. | Kept `build_planner_telemetry` as the only telemetry dict owner and made the proposal module pass optional values into it. |
| First-attempt idempotency was unspecified for missing-tool followed by forced retry success. | Defined first attempt as the first model proposal behavior and added first-write-wins coverage for the no-tool forced-retry path. |
| `ToolProcessingResult.failure_kind` was still free-form. | Tightened failure kinds to typed literals and added a source drift test. |
| `ProposalUsageTracker` would become a misleading name after adding attempt outcome state. | Renamed it to `ProposalTurnTelemetry`; no compatibility alias was preserved. |
| Baseline numbers could become placeholders. | Required actual deterministic numbers in the journal before commit. |

### Iteration 2

- Artifact: `.codex/artifacts/claude-peer-loop-batch-11-0b-proposal-reliability-measurement-plan-verification-20260503T000947Z.md`
- Verdict: `changes_required`
- Green light: `no`
- Minimum score: `8`

Accepted findings and changes:

| Finding | Change |
|---|---|
| Tightening `ToolProcessingResult.failure_kind` also affects `ai_builder_proposal_repair.py`. | Added the repair module and `_build_self_correction_error_event` to the typed surface. |
| `missing_submission_tool` is not a valid tool-result failure. | Split `ToolProcessingFailureKind` from sanitized `ProposalFailureKind`. |
| JSON logging strips top-level `None` extras. | Used a nested `ai_builder_proposal_telemetry` log payload and omitted failure fields on success rows. |
| Failure-kind drift test wording was mechanism-focused. | Implemented a fixed-file AST test named by the taxonomy contract. |
| Deterministic vs live LLM baselines could be confused. | The baseline section below separates deterministic numbers from deferred live LLM first-attempt rate. |

### Iteration 3

- Artifact: `.codex/artifacts/claude-peer-loop-batch-11-0b-proposal-reliability-measurement-plan-verification-2-20260503T001225Z.md`
- Verdict: `green`
- Green light: `yes`
- Minimum score: `9`

Accepted polish after green:

| Finding | Change |
|---|---|
| `recoverable_parse` is a tested-but-currently-unproduced internal contract. | Documented the distinction in `ai_builder_proposal_telemetry.py`. |
| The injected self-correction error event callable was too loose. | Added a typed protocol for the callback in `ai_builder_proposal_repair.py`. |
| `ProposalRepairReason` could drift from `ProposalFailureKind`. | Made it an alias of `ProposalFailureKind`, not a separate literal. |
| The source drift test needed a fixed source set. | Pinned the AST scan to proposal processor and edit proposal production files. |

## 11.0b Implementation Result

Implemented:

- `backend/src/intric/flows/ai_builder/ai_builder_proposal_telemetry.py`
  now owns `ProposalTurnTelemetry`, proposal failure taxonomies, and structured
  proposal log payload helpers.
- `backend/src/intric/flows/ai_builder/ai_builder_telemetry.py` remains the
  canonical `planner_telemetry` dict owner and accepts optional proposal fields.
- `backend/src/intric/flows/ai_builder/ai_builder_proposal_processor.py`
  records first-attempt outcome and repair reason for create proposals, edit
  proposals, and missing-tool forced retry.
- `backend/src/intric/flows/ai_builder/ai_builder_edit_proposal.py` and create
  proposal processing now separate proposal success recording from metadata
  building, so successful first-attempt telemetry is persisted only on accepted
  proposal paths.
- `backend/src/intric/flows/ai_builder/ai_builder_proposal_repair.py` now shares
  the typed failure-kind contract used by `ToolProcessingResult`.
- `backend/tests/unittests/flows/ai_builder/test_ai_builder_proposal_telemetry.py`
  covers the proposal telemetry payload, structured log shape, first-write-wins
  behavior, taxonomy mapping, and failure-kind drift.
- `backend/tests/unittests/flows/ai_builder/test_ai_builder_proposal_processor.py`
  covers initial proposal success, repaired proposal metadata, missing-tool
  forced retry success, quality-failure first-attempt recording, and edit parse
  failure telemetry.

Behavior changes:

- none intended. The proposal, compile, validation, and repair behavior remains
  unchanged; this slice records measurement data around existing paths.

## 11.0b Claude Implementation Review

### Iteration 4

- Artifact: `.codex/artifacts/claude-peer-loop-batch-11-0b-proposal-telemetry-implementation-20260503T003537Z.md`
- Verdict: `changes_required`
- Green light: `no`
- Minimum score: `5`

Accepted finding:

| Finding | Change |
|---|---|
| Success telemetry was recorded through a metadata-builder side effect before downstream validation and quality checks completed. First-write-wins could therefore hide a real validation or quality failure. | Split success recording from metadata construction, made MCP clarification metadata lazy, and added quality-failure regression coverage for create and edit paths. |

### Iteration 5

- Artifact: `.codex/artifacts/claude-peer-loop-batch-11-0b-proposal-telemetry-verification-20260503T004709Z.md`
- Verdict: `GREEN_LIGHT`
- Green light: `yes`
- Minimum score: `8.5`

Accepted verification:

| Finding | Resolution |
|---|---|
| The eager success-recording blocker was fixed structurally. | `proposal_success_recorder` and `assistant_metadata_builder` are separate callables; success is recorded only from accepted proposal persistence or MCP-question persistence paths. |
| Regression tests now protect the invariant. | Added real outline quality-failure telemetry coverage and edit quality-failure no-success-callback coverage. |
| No code/comment/compatibility blocker remained. | Proceeded with validation and commit preparation. |

## 11.0b Deterministic Baseline

Included in this committed baseline:

| Surface | Baseline result |
|---|---|
| Proposal telemetry focused tests | `58 passed`; pre-existing `python_multipart` warning only. |
| Reliability corpus + benchmark integrity tests | `75 passed`; 7 reliability cases; 5 `BehavioralRisk` values covered. |
| AI Builder integration suite | `79 passed, 20 deselected`; pre-existing deprecation warnings only. |
| Benchmark runner case count | 17 benchmark cases. |
| Benchmark runner diff vs frozen `baseline.json` | 0 added, 0 removed, 10 changed cases: `attachment_heavy_01_sv`, `audio_01_sv`, `audio_02_en`, `json_pipeline_01_sv`, `mixed_runtime_input_01_sv`, `rich_01_sv`, `template_fill_02_en`, `text_only_01_sv`, `text_only_02_en`, `vague_01_sv`. |

Not included:

- Live LLM first-attempt success rate. That number requires the manual API
  workflow in `manual-eval-runbook.md` with the pinned workspace/model fixture,
  three runs per prompt/mode, and redacted scorecards.
- Any frontend UI quality score.

## User Requirement

The user asked for a new Batch 11 focused fully on Flow AI Builder reliability, including a rebuild if needed. The target is a builder that understands the Eneo Flow framework, works well in Swedish, asks only useful follow-up questions, uses enabled assistants/knowledge/MCP/tools, and reliably produces coherent Flow mechanics without relying on repair/rebuilder loops as the happy path.

The user also asked to consider LiteLLM JSON mode / structured outputs and to iterate with Claude three times before finalizing the Batch 11 shape.

The user later asked for Batch 11 to include a concrete local API evaluation workflow with the local development API key, exact curl, the AI Builder endpoints, the local space id, and six reusable Swedish prompts. The goal is to measure whether each implementation slice actually improves Flow AI Builder's practical quality: relevant follow-up questions, correct input/output types, correct use of runtime inputs and `Underlag till text`, coherent step chains, better generated flows, and less reliance on repair.

The user then added that the same evaluation must test edit behavior: revising a proposed plan before apply, editing an existing/applied Flow, changing a specific part without damaging unrelated mechanics, and judging whether the output quality remains high.

## Reported Failure

The user reported a Swedish audio-to-DOCX scenario:

- The UI interpreted the plan as runtime input `Ljud` and final output `DOCX-dokument`.
- Later proposal processing failed with "Plan still invalid after correction."
- Logs showed the quality issue: the conversation mentioned audio/transcription, but no step had `input_type="audio"` or `output_mode="transcribe_only"`.
- Proposal repair then bailed to conversational JSON after retry, even though repair is not supposed to emit backend-owned mechanics.

Batch 11 treats this as an architecture/materialization reliability failure, not only a prompt or JSON formatting failure.

## Claude Ideation Artifacts

| Iteration | Artifact | Result |
|---:|---|---|
| 1 | `.codex/artifacts/ask-claude-batch-11-flow-ai-builder-reliability-ideation-1-20260502T201019Z.md` | Completed. Diagnosed audio/DOCX as server-derivation/materialization gap; recommended step skeleton materialization, structured output rail, Swedish slot resolver. |
| 2 | `.codex/artifacts/ask-claude-batch-11-flow-ai-builder-reliability-ideation-2-focused-20260502T202440Z.md` | Completed. Reordered priorities: skeleton-as-contract and critic retargeting before structured outputs; slot resolver before schema rail. |
| 3 | `.codex/artifacts/ask-claude-batch-11-flow-ai-builder-reliability-ideation-3-retry-20260502T203231Z.md` | Completed. Produced final five-slice shape, success metrics, non-goals, and structured-output constraints. |

Timed-out attempts were saved but not counted as valid ideation iterations:

- `.codex/artifacts/ask-claude-batch-11-flow-ai-builder-reliability-ideation-2-retry-20260502T201820Z.md`
- `.codex/artifacts/ask-claude-batch-11-flow-ai-builder-reliability-ideation-3-final-shape-20260502T202819Z.md`

## Accepted Decisions

| Decision | Reason |
|---|---|
| Batch 11 gets a new PRD: `PRD-011-flow-ai-builder-reliability.md`. | PRD-005 covered architecture split, but the user's new requirement is a reliability/rebuild program with measurable gates. |
| Skeleton-as-contract comes before LiteLLM structured outputs. | The reported failure is architecture-class; structured outputs reduce parse failures but cannot make backend-owned mechanics appear. |
| Backend owns Flow mechanics; LLM fills semantic content. | This keeps Flow framework truth in FCM/PlanningState/Pattern Registry and makes small-model output more reliable. |
| Swedish slot resolver gets a frozen eval corpus. | Keyword lists are brittle and cannot prove Swedish/general-flow quality. |
| Existing resource owners are reused. | `ai_builder_mcp_resources.py`, `ai_builder_mcp_intent.py`, and `ai_builder_flow_capability_reference.py` already own resource normalization and LLM reference material. |
| Repair remains, but not as happy path. | Repair is still valid for parse/ref-resolution errors; architecture-class drift should be impossible or treated as a backend bug. |

## Claude Peer Review

### Plan Review Iteration 1

- Artifact: `.codex/artifacts/claude-peer-loop-batch-11-flow-ai-builder-reliability-plan-20260502T204313Z.md`
- Verdict: `changes_required`
- Green light: `no`
- Minimum score: `6`

Accepted findings and changes:

| Finding | Change |
|---|---|
| Success metrics were circular because goldens were introduced later in the same batch. | Added 11.0 production-failure corpus and made goldens coverage gates, not the baseline reliability gate. |
| 11.1 `materialize_step_skeleton` gate was mixed with 11.2 Swedish intent resolver gate. | Split 11.1 fixed-PlanningState/FCM tuple gate from 11.1+11.2 Swedish corpus gate. |
| Skeleton fill/merge rules were undefined. | Added explicit slot-fill rules for count mismatch, extra steps, mechanic conflicts, and edit-mode preservation. |
| Structured-output capability source was forked. | Made `TenantModelAdapter` the single owner with explicit model config as authoritative override and LiteLLM support checks as evidence. |
| Tool calls were incorrectly treated as a structured-output fallback rung. | Collapsed the structured-output modes to `strict_json_schema`, `json_object`, and `prompt_with_pydantic_validation`; tool calls remain orthogonal. |
| Architecture-class invariant failures lacked a failure surface. | Added typed architecture error requirement that bypasses repair. |
| Keyword prior deletion criterion was vague. | Added numeric deletion starting point: 95% corpus match/improvement plus seven-day reviewed-production disagreement gate. |
| 11.1 was too large. | Pre-split 11.1 into 11.1a/11.1b/11.1c. |
| Eval corpus integrity was not concrete. | Added minimum case count and integrity/minimum-count test requirement. |
| Capability reference strengthening was too vague. | Added exact per-slice capability-reference additions. |

### Plan Verification Iteration 2

- Artifact: `.codex/artifacts/claude-peer-loop-batch-11-flow-ai-builder-reliability-plan-verification-20260502T204917Z.md`
- Verdict: `changes_required`
- Green light: `no`
- Minimum score: `7`

Accepted findings and changes:

| Finding | Change |
|---|---|
| A stale four-tier structured-output rail remained in PRD-011. | Replaced it with `strict_json_schema -> json_object -> prompt_with_pydantic_validation`; tool calls remain orthogonal. |
| Provider call mechanics row used old language. | Updated the canonical owner action so `TenantModelAdapter` owns typed capability and AI Builder callers do not query LiteLLM directly. |
| Structured-output capability was still listed as open. | Removed the resolved open question. |
| Naming still hedged across competing terms. | Standardized on `StepSkeleton` as the value object and `materialize_step_skeleton` as the pure function. |
| Decision boundary omitted architecture failure surface. | Added a boundary row for `AIBuilderArchitectureError` bypassing repair. |
| Capability reference rollout was buried under 11.3. | Promoted it to a top-level table in PRD and plan. |
| Suggested commit list did not match slice structure. | Collapsed the form-field/resource commit suggestion into one commit. |
| 11.1c could overflow the LOC ceiling. | Added an explicit split-further instruction for 11.1c. |
| Skeleton fill rules were duplicated. | Kept the canonical contract in PRD-011 and made the plan cross-reference it. |

### Plan Verification Iteration 3

- Artifact: `.codex/artifacts/claude-peer-loop-batch-11-flow-ai-builder-reliability-plan-verification-2-20260502T205507Z.md`
- Verdict: `green`
- Green light: `yes`
- Minimum score: `8`

Accepted optional polish:

| Finding | Change |
|---|---|
| A problem-statement row still used the old `schema/tool/json-object/prompt` shorthand. | Replaced it with the resolved structured-output modes. |
| `StepSkeleton` was used awkwardly as the bug locus. | Changed the wording to backend materialization or validator bugs. |
| 11.1 sub-slice commit shape was implicit. | Added that 11.1 may split across 11.1a/11.1b/11.1c commits if a sub-slice approaches the LOC ceiling. |

### Manual Evaluation Addendum Review Iteration 1

- Artifact: `.codex/artifacts/claude-peer-loop-batch-11-manual-api-eval-addendum-20260502T211054Z.md`
- Verdict: `changes_required`
- Green light: `no`
- Minimum score: `3`

Accepted findings and changes:

| Finding | Change |
|---|---|
| The manual prompts could become a third independent corpus. | Added `manual-eval-runbook.md` as a local smoke-suite runbook tied to 11.0, with explicit promotion into the canonical automated corpus/tests for every new failure. |
| The scorecard needed typed, comparable fields instead of subjective notes. | Added a scorecard shape covering prompt ids, session/plan ids, typed pass/fail counts, repair invocation, input/output compatibility, `Underlag till text`, refs, and manual scores. |
| Baseline comparison needed repeatability and variance. | Required three runs per prompt before and after each relevant slice, with median typed failures/manual scores and variance. |
| Raw transcripts and local credentials could leak into committed docs. | Kept the user-approved local development key and exact curl in the runbook by explicit user request, but required committed outputs to be redacted scorecards and summaries only. |
| Endpoint list should not drift silently. | Marked the endpoint table as a local snapshot that the implementation agent must verify against OpenAPI before building a harness. |
| The six user prompts needed both vague and advanced examples. | Added three vague prompts and three advanced prompts covering audio-to-DOCX, multi-file DOCX, DOCX template fill, report-to-PDF, sectioning, and `Underlag till text`. |
| The manual scorecard needed stable fixture/model context. | Added workspace prerequisites, model/provider recording, and fixture fingerprint requirements. |
| Scorecard fields mixed observed API values and derived heuristics. | Split the scorecard into `observed` and `derived` blocks and required deterministic derivation rules. |
| Edit/revise coverage was missing. | Added `create_plan`, `revise_plan`, and `edit_existing_flow` modes with reusable Swedish revision/edit prompts. |

### Manual Evaluation Addendum Review Iteration 2

- Artifact: `.codex/artifacts/claude-peer-loop-batch-11-manual-api-eval-addendum-verification-20260502T212126Z.md`
- Verdict: `changes_required`
- Green light: `no`
- Minimum score: `5`

Codex accepted most findings, but explicitly disagreed with the API-key blocker
because the user repeated that the local development API key and exact curl
should be present in the runbook. The disagreement is documented as a local-only,
user-approved exception, not a general credential policy.

Accepted findings and changes:

| Finding | Change |
|---|---|
| Environment variable names could fragment. | Pinned harness implementations to the `ENEO_LOCAL_*` names. |
| Workspace fixture was unspecified. | Added workspace prerequisites and fixture recording. |
| Model pinning was missing. | Added model id/name/provider/temperature to the scorecard and comparison rule. |
| Heuristic and API-observed fields were conflated. | Split `observed` and `derived` scorecard blocks. |
| Per-prompt expected outcomes were prose-only. | Added a typed `prompts.yaml` manifest shape. |
| Previous-baseline comparison was implicit. | Added redacted baseline file and same prompt/mode/model/workspace comparison rules. |

### Manual Evaluation Addendum Review Iteration 3

- Artifact: `.codex/artifacts/claude-peer-loop-batch-11-manual-api-eval-addendum-verification-2-20260502T212638Z.md`
- Verdict: `green`
- Green light: `yes`
- Minimum score: `7`

Accepted polish applied after green light:

| Finding | Change |
|---|---|
| Manifest and scorecard used different terms for forbidden questions. | Standardized on `disallowed_follow_up_topics`. |
| Edit-flow seeding sequence was implicit. | Added create -> approve -> apply -> capture `flow_id` -> edit sequence to the baseline procedure. |
| Slice-to-evaluation-mode mapping was prose-only. | Added a table mapping 11.0 through 11.5 to required `create_plan`, `revise_plan`, and `edit_existing_flow` modes. |
| `derivation_rules_version` lacked a comparison rule. | Added derived-baseline invalidation rule when derivation rules change. |
| Edit/revision scorecard nullability was ambiguous. | Clarified revision fields are `null` for create and required for revise/edit. |
| Workspace fingerprint algorithm was undefined. | Added a stable sorted-resource hash requirement, with exact algorithm owned by the schema/README. |
| Temperature/seed policy was only recorded after the fact. | Required `temperature=0` where supported, otherwise explicit deterministic-output policy in each scorecard. |

## Carry-Forward Risks

| Risk | Owner slice |
|---|---|
| Current architecture-class critic invariants may still target compiled model payloads rather than server skeletons. | 11.1 |
| Current keyword intent logic may miss Swedish phrasing not present in marker lists. | 11.2 |
| Form-field lifecycle and edit-path parity may remain under-covered. | 11.3 / 11.4 |
| LiteLLM provider support differs by tenant/model, especially custom OpenAI-compatible endpoints. | 11.5 |
| Batch 10 operability work is not the same concern and must not be mixed with Batch 11 implementation commits. | All slices |
| Manual API quality checks could become subjective or stale if not promoted into tests. | 11.0 |
| The local development API key in the runbook is intentionally user-approved but would be unacceptable for shared or production credentials. | 11.0 / docs review |

## Validation For This Planning Pass

Completed:

- `git diff --check -- docs/refactor/prd/PRD-011-flow-ai-builder-reliability.md docs/refactor/execution/batch-11-flow-ai-builder-reliability docs/refactor/implementation-order.md` passed.
- Anti-stale-doc grep for old structured-output ladder, unresolved naming hedges, and stale fallback wording passed with no matches in the Batch 11 docs.
- Claude peer-loop plan verification reached `GREEN_LIGHT: yes` in iteration 3.

Completed after final manual-eval polish:

- `git diff --check -- docs/refactor/prd/PRD-011-flow-ai-builder-reliability.md docs/refactor/execution/batch-11-flow-ai-builder-reliability docs/refactor/implementation-order.md` passed.
- Anti-stale-doc grep passed with only historical journal entries documenting resolved Claude findings.

## 11.1a StepSkeleton Materialization

### Scope

Implemented the typed skeleton/materialization owner without changing create
proposal behavior or wiring `compile_outline_to_create_draft` to consume the
skeleton yet.

### Source Changes

| Area | Evidence | Decision |
|---|---|---|
| Skeleton contract | `backend/src/intric/flows/ai_builder/ai_builder_step_skeleton.py:116`, `backend/src/intric/flows/ai_builder/ai_builder_step_skeleton.py:187` | Added `StepSkeleton` and `StepSkeletonPlan` as typed dataclasses. The plan owns backend prefix/suffix slots plus a repeatable semantic slot template. |
| Materialization function | `backend/src/intric/flows/ai_builder/ai_builder_step_skeleton.py:333` | Added `materialize_step_skeleton` as the deterministic owner for architecture-derived skeleton plans. |
| Variable semantic count | `backend/src/intric/flows/ai_builder/ai_builder_step_skeleton.py:212` | `slots_for_semantic_count` expands the semantic template for outline step counts instead of hardcoding comparison or linear step counts. |
| Pattern-chain templates | `backend/src/intric/flows/ai_builder/ai_builder_step_skeleton.py:411` | Moved backend-added step template/default structured fields into the skeleton owner and reused them from the existing chain realizer. |
| Current compiler behavior | `backend/src/intric/flows/ai_builder/ai_builder_create_outline.py:1551`, `backend/src/intric/flows/ai_builder/ai_builder_create_outline.py:1696` | Left the existing compiler mechanics helpers in place for 11.1b integration/deletion instead of mixing behavior changes into 11.1a. |
| Step chain owner split | `backend/src/intric/flows/ai_builder/ai_builder_outline_pattern_chains.py:1` | Kept pattern-chain realization narrow; it now consumes skeleton-owned defaults rather than owning skeleton materialization. |
| Chain-step token type | `backend/src/intric/flows/ai_builder/pattern_registry.py:49` | Added `ChainStepToken` alias so skeleton fields do not use an anonymous `str` for registry chain tokens. |

### Test Changes

| Coverage | Evidence |
|---|---|
| Closed policy tuples | `backend/tests/unittests/flows/ai_builder/test_ai_builder_step_skeleton.py:78` |
| Audio, template-fill, structured-quality, text-to-JSON skeletons | `backend/tests/unittests/flows/ai_builder/test_ai_builder_step_skeleton.py:88`, `:107`, `:134`, `:159`, `:185` |
| Multi-step linear expansion | `backend/tests/unittests/flows/ai_builder/test_ai_builder_step_skeleton.py:204` |
| Comparison fan-in expansion for 2, 3, and 4 semantic steps | `backend/tests/unittests/flows/ai_builder/test_ai_builder_step_skeleton.py:227`, `:359` |
| Compiler mechanics equivalence for audio, linear, DOCX template, and comparison paths | `backend/tests/unittests/flows/ai_builder/test_ai_builder_step_skeleton.py:254`, `:292`, `:324`, `:359` |

### Claude Peer Review

| Iteration | Artifact | Verdict | Green light | Minimum score | Outcome |
|---:|---|---|---|---:|---|
| 1 | `.codex/artifacts/claude-peer-loop-batch-11-1a-step-skeleton-plan-20260503T005555Z.md` | `changes_required` | `no` | 6 | Rejected early fixed-shape/owner plan. |
| 2 | `.codex/artifacts/claude-peer-loop-batch-11-1a-step-skeleton-revised-plan-20260503T010206Z.md` | `green` | `yes` | 8 | Approved typed schema and owner direction with implementation follow-ups. |
| 3 | `.codex/artifacts/claude-peer-loop-batch-11-1a-step-skeleton-implementation-20260503T012233Z.md` | `changes_required` | `no` | 6 | Found fixed comparison/linear skeleton shapes and tautological tests. |
| 4 | `.codex/artifacts/claude-peer-loop-batch-11-1a-step-skeleton-verification-20260503T013423Z.md` | `green` | `yes` | 8 | Accepted variable-count `StepSkeletonPlan` shape. |
| 5 | `.codex/artifacts/claude-peer-loop-batch-11-1a-step-skeleton-final-verification-20260503T013954Z.md` | `green` | `yes` | 4/5 | Accepted final polish and wider equivalence tests. |

### Accepted Claude Findings

| Finding | Resolution |
|---|---|
| Fixed comparison skeleton invented a 3-step shape. | Replaced fixed comparison slots with a repeatable semantic slot and `fan_in_policy="last_semantic"`. |
| Linear skeleton was one-slot only. | `StepSkeletonPlan.slots_for_semantic_count` expands linear mechanics for arbitrary semantic step counts. |
| Equivalence tests were tautological. | Added variable-count comparison coverage and parametrized audio/linear equivalence tests. |
| Terminal-step defaults leaked into non-terminal semantic slots. | Added slot-id-specific semantic default names/instructions for audio, structured, template, comparison, and linear semantic templates. |
| Pattern-chain owner would become too large if skeleton stayed there. | Split the skeleton owner into `ai_builder_step_skeleton.py` and kept `ai_builder_outline_pattern_chains.py` focused on chain realization. |
| Returned chain-step context was unused. | Simplified the skeleton context helper to return only augmented pattern ids. |

### Validation

| Command | Result |
|---|---|
| `cd backend && uv run pytest tests/unittests/flows/ai_builder/test_ai_builder_step_skeleton.py tests/unittests/flows/ai_builder/test_ai_builder_create_compiler.py tests/unittests/flows/ai_builder/test_pattern_registry.py -q` | Passed: `132 passed`. |
| `cd backend && uv run pyright src/intric/flows/ai_builder/ai_builder_step_skeleton.py src/intric/flows/ai_builder/ai_builder_outline_pattern_chains.py src/intric/flows/ai_builder/ai_builder_create_outline.py src/intric/flows/ai_builder/pattern_registry.py tests/unittests/flows/ai_builder/test_ai_builder_step_skeleton.py tests/unittests/flows/ai_builder/test_ai_builder_create_compiler.py tests/unittests/flows/ai_builder/test_pattern_registry.py` | Passed: `0 errors, 0 warnings, 0 informations`. |
| `cd backend && uv run ruff check src/intric/flows/ai_builder/ai_builder_step_skeleton.py src/intric/flows/ai_builder/ai_builder_outline_pattern_chains.py src/intric/flows/ai_builder/ai_builder_create_outline.py src/intric/flows/ai_builder/pattern_registry.py tests/unittests/flows/ai_builder/test_ai_builder_step_skeleton.py tests/unittests/flows/ai_builder/test_ai_builder_create_compiler.py tests/unittests/flows/ai_builder/test_pattern_registry.py` | Passed. |
| `cd backend && uv run ruff format --check src/intric/flows/ai_builder/ai_builder_step_skeleton.py src/intric/flows/ai_builder/ai_builder_outline_pattern_chains.py src/intric/flows/ai_builder/ai_builder_create_outline.py src/intric/flows/ai_builder/pattern_registry.py tests/unittests/flows/ai_builder/test_ai_builder_step_skeleton.py tests/unittests/flows/ai_builder/test_ai_builder_create_compiler.py tests/unittests/flows/ai_builder/test_pattern_registry.py` | Passed: `7 files already formatted`. |
| `cd backend && uv run lint-imports --no-cache` | Passed: 3 contracts kept, 0 broken. |
| `git diff --check -- backend/src/intric/flows/ai_builder/ai_builder_step_skeleton.py backend/src/intric/flows/ai_builder/ai_builder_outline_pattern_chains.py backend/src/intric/flows/ai_builder/ai_builder_create_outline.py backend/src/intric/flows/ai_builder/pattern_registry.py backend/tests/unittests/flows/ai_builder/test_ai_builder_step_skeleton.py` | Passed. |
| `./scripts/gate-local/anti_slippage.sh --worktree` | Passed: `anti-slippage: worktree clean`. |

Broader `cd backend && uv run pytest tests/unittests/flows/ai_builder -q`
was run during the slice and failed on pre-existing surfaces outside this
change: one server-action assertion, missing local WeasyPrint native
libraries (`libgobject-2.0-0`), and import-linter source-module drift. Focused
tests for the touched owner and existing compiler/pattern behavior pass.

## 11.1b StepSkeleton Fill And Compile Integration

### Scope

Rewired create-outline compilation to consume `materialize_step_skeleton` and
`StepSkeletonPlan.compose`. Deleted the old outline pattern-chain realization
module and the duplicate create-outline mechanics helpers.

### Source Changes

| Area | Evidence | Decision |
|---|---|---|
| Skeleton composition | `backend/src/intric/flows/ai_builder/ai_builder_step_skeleton.py:99`, `backend/src/intric/flows/ai_builder/ai_builder_step_skeleton.py:276` | Added typed composition result/drift data and made `StepSkeletonPlan.compose` the final create-step mechanics resolver. |
| Create-outline compile path | `backend/src/intric/flows/ai_builder/ai_builder_create_outline.py:507`, `backend/src/intric/flows/ai_builder/ai_builder_create_outline.py:562`, `backend/src/intric/flows/ai_builder/ai_builder_create_outline.py:575` | The compiler now parses/folds semantic outline content, materializes a skeleton, composes `NewStepDraft`s, logs drift, and returns the draft. |
| Deleted parallel mechanics path | `backend/src/intric/flows/ai_builder/ai_builder_outline_pattern_chains.py` | Removed the old chain realizer and create-outline `_derive_step_*` / terminal-step / fan-in helper path. |
| Compiled chain coverage | `backend/src/intric/flows/ai_builder/ai_builder_step_skeleton.py:498`, `backend/tests/unittests/flows/ai_builder/test_pattern_registry.py:347` | `materialized_compiled_pattern_ids()` replaces the old realizer-id guard so registry compiled chains cannot drift from skeleton materializers. |
| Artifact suffixes | `backend/src/intric/flows/ai_builder/ai_builder_step_skeleton.py:936`, `backend/src/intric/flows/ai_builder/ai_builder_step_skeleton.py:1074` | Linear and audio DOCX/PDF paths now use semantic text slots plus backend terminal artifact suffixes. |
| Locked mechanics | `backend/src/intric/flows/ai_builder/ai_builder_step_skeleton.py:592` | Backend-fixed slots keep their declared input type even if previous semantic slots emit JSON. |
| Drift logging | `backend/src/intric/flows/ai_builder/ai_builder_create_outline.py:618` | Explicit semantic output-type conflicts are logged as `ai_builder_skeleton_semantic_output_type_drift`. |

### Test Changes

| Coverage | Evidence |
|---|---|
| Linear artifact terminal suffix | `backend/tests/unittests/flows/ai_builder/test_ai_builder_step_skeleton.py:238` |
| Typed output-type drift data | `backend/tests/unittests/flows/ai_builder/test_ai_builder_step_skeleton.py:276` |
| Compose fallback terminal text after structured semantic content | `backend/tests/unittests/flows/ai_builder/test_ai_builder_step_skeleton.py:309` |
| Backend-fixed locked input type after structured semantic outputs | `backend/tests/unittests/flows/ai_builder/test_ai_builder_step_skeleton.py:332` |
| Audio-to-DOCX skeleton terminal artifact | `backend/tests/unittests/flows/ai_builder/test_ai_builder_create_compiler.py:2060` |
| Audio aggregate fan-in on terminal artifact | `backend/tests/unittests/flows/ai_builder/test_ai_builder_create_compiler.py:2115` |
| Requested JSON intermediate preservation | `backend/tests/unittests/flows/ai_builder/test_ai_builder_create_compiler.py:2753` |
| Semantic output-type drift log contract | `backend/tests/unittests/flows/ai_builder/test_ai_builder_create_compiler.py:2781` |

### Claude Peer Review

| Iteration | Artifact | Verdict | Green light | Minimum score | Outcome |
|---:|---|---|---|---:|---|
| 1 | `.codex/artifacts/claude-peer-loop-batch-11-1b-step-skeleton-fill-plan-20260503T015736Z.md` | `changes_required` | `no` | 5 | Rejected separate fill module and missing terminal artifact suffixes. |
| 2 | `.codex/artifacts/claude-peer-loop-batch-11-1b-step-skeleton-fill-plan-verification-20260503T020242Z.md` | `green` | `yes` | 7 | Accepted `StepSkeletonPlan.compose` as the canonical resolver with clarifications. |
| 3 | `.codex/artifacts/claude-peer-loop-batch-11-1b-step-skeleton-fill-implementation-20260503T021655Z.md` | `green` | `yes` | 7 | Accepted implementation, with hardening suggestions for locked slots and compose fallback coverage. |
| 4 | `.codex/artifacts/claude-peer-loop-batch-11-1b-step-skeleton-fill-final-verification-20260503T022224Z.md` | `green` | `yes` | 8 | Content green, wrapper parse failed because the response was nested in summary tags. |
| 5 | `.codex/artifacts/claude-peer-loop-batch-11-1b-step-skeleton-fill-final-verification-contract-20260503T022312Z.md` | `green` | `yes` | 8 | Parser-clean final green light. |

### Accepted Claude Findings

| Finding | Resolution |
|---|---|
| Separate fill module would become a second mechanics owner. | Put fill on `StepSkeletonPlan.compose`. |
| Linear/audio artifact paths would let an LLM-authored semantic step emit DOCX/PDF directly. | Added backend `TERMINAL_ARTIFACT_STEP` suffixes for generated DOCX/PDF. |
| Pattern-chain deletion needed a replacement invariant. | Added `materialized_compiled_pattern_ids()` and rewired the registry test. |
| Audio aggregate fan-in slot was ambiguous. | Pinned generated-artifact fan-in to the terminal artifact slot. |
| Locked backend-fixed slots could still have input type flipped by prior JSON. | Added locked-policy guard and a structured-quality regression test. |
| Compose fallback was untested and had a dead drift branch. | Added fallback coverage and removed the dead branch. |

### Validation

| Command | Result |
|---|---|
| `cd backend && uv run pytest tests/unittests/flows/ai_builder/test_ai_builder_step_skeleton.py tests/unittests/flows/ai_builder/test_ai_builder_create_compiler.py tests/unittests/flows/ai_builder/test_pattern_registry.py -q` | Passed: `140 passed`. |
| `cd backend && uv run pyright src/intric/flows/ai_builder/ai_builder_step_skeleton.py src/intric/flows/ai_builder/ai_builder_create_outline.py tests/unittests/flows/ai_builder/test_ai_builder_step_skeleton.py tests/unittests/flows/ai_builder/test_ai_builder_create_compiler.py tests/unittests/flows/ai_builder/test_pattern_registry.py` | Passed: `0 errors, 0 warnings, 0 informations`. |
| `cd backend && uv run ruff check src/intric/flows/ai_builder/ai_builder_step_skeleton.py src/intric/flows/ai_builder/ai_builder_create_outline.py tests/unittests/flows/ai_builder/test_ai_builder_step_skeleton.py tests/unittests/flows/ai_builder/test_ai_builder_create_compiler.py tests/unittests/flows/ai_builder/test_pattern_registry.py` | Passed. |
| `cd backend && uv run ruff format --check src/intric/flows/ai_builder/ai_builder_step_skeleton.py src/intric/flows/ai_builder/ai_builder_create_outline.py tests/unittests/flows/ai_builder/test_ai_builder_step_skeleton.py tests/unittests/flows/ai_builder/test_ai_builder_create_compiler.py tests/unittests/flows/ai_builder/test_pattern_registry.py` | Passed: `5 files already formatted`. |
| `cd backend && uv run lint-imports --no-cache` | Passed: 3 contracts kept, 0 broken. |
| `git diff --check -- <11.1b touched paths>` | Passed. |
| `./scripts/gate-local/anti_slippage.sh --worktree` | Passed: `anti-slippage: worktree clean`. |
| `cd backend && uv run pytest tests/unittests/flows/ai_builder -q` | Failed on known unrelated/environmental surfaces: one server-action wording assertion, four missing WeasyPrint native-library failures for `libgobject-2.0-0`, and import-linter source-module drift. Passing count before those failures: `1685 passed`; failures: `6`. |

### Carry-Forward

| Item | Owner slice |
|---|---|
| Typed architecture error surface and critic invariant classification. | 11.1c |
| Edit-path fill/preserve/reject mechanics. | 11.1c |
| Potential split of `ai_builder_step_skeleton.py` if 11.1c adds substantial materializer/compose code. | 11.1c |
| Generalize `StepSkeletonOutputTypeDrift` only if 11.1c needs additional drift classes. | 11.1c |

## 11.1c Architecture Error Surface And Critic Classification

### Scope

Implemented the create-path architecture-error surface and critic invariant
classification. Edit-path fill/preserve/reject mechanics stay out of this slice
and remain a follow-up so create-path repair policy is reviewable on its own.

### Source Changes

| Area | Evidence | Decision |
|---|---|---|
| Shared architecture error contract | `backend/src/intric/flows/ai_builder/ai_builder_architecture_errors.py:7`, `:14` | Added `ArchitectureErrorCode` and `AIBuilderArchitectureError(Exception)` with scalar log context. |
| Create-outline skeleton boundary | `backend/src/intric/flows/ai_builder/ai_builder_create_outline.py:565`, `:583` | Wrap only skeleton materialization/composition `ValueError`s as `architecture_materialization_failed`; outline argument validation still follows the existing parse path. |
| Critic invariant classification | `backend/src/intric/flows/ai_builder/ai_builder_critic_invariants.py:855`, `:880`, `:907` | Kept one `CRITIC_INVARIANTS` registry, added typed issue evaluation, and added architecture enforcement for backend-owned mechanics failures. |
| Create proposal strict critic path | `backend/src/intric/flows/ai_builder/ai_builder_proposal_processor.py:473`, `:481`, `:488` | Create proposals build one critic context, enforce architecture issues, then render semantic-only quality feedback. |
| Proposal error translation | `backend/src/intric/flows/ai_builder/ai_builder_proposal_processor.py:245`, `:262`, `:1377`, `:1626`, `:1727` | Direct submission, repair processing, and forced-tool retry paths record first-attempt `architecture` failures and yield one sanitized SSE error event without self-correction. |
| Telemetry taxonomy | `backend/src/intric/flows/ai_builder/ai_builder_proposal_telemetry.py:37`, `:45`, `:74` | `ProposalFailureKind` includes `architecture`; `ProposalRepairReason` excludes it. Tool-processing failures still map only to repairable reasons. |
| Bridge materialization error | `backend/src/intric/flows/ai_builder/ai_builder_materialization_bridge.py:84` | `MaterializationError` now subclasses the shared architecture error without keeping a `ValueError` parent. |
| SSE error code mapping | `backend/src/intric/flows/ai_builder/ai_builder_events.py:104` | Architecture error codes map to the existing bad-request error family. Frontend SSE handling was checked and treats unknown AI Builder error codes as strings. |

### Test Changes

| Coverage | Evidence |
|---|---|
| Critic kind map and typed issue evaluation | `backend/tests/unittests/flows/ai_builder/test_ai_builder_plan_quality_critic.py:105`, `:112` |
| Architecture critic enforcement | `backend/tests/unittests/flows/ai_builder/test_ai_builder_plan_quality_critic.py:121` |
| Semantic-only feedback rendering | `backend/tests/unittests/flows/ai_builder/test_ai_builder_plan_quality_critic.py:132`, `:153` |
| Direct architecture error bypasses repair and keeps repair count zero | `backend/tests/unittests/flows/ai_builder/test_ai_builder_proposal_processor.py:1180` |
| Self-correction and forced-tool architecture errors use sanitized SSE events | `backend/tests/unittests/flows/ai_builder/test_ai_builder_proposal_processor.py:1248`, `:1304` |
| Audio-to-DOCX proposal canary returns a plan without self-correction | `backend/tests/unittests/flows/ai_builder/test_ai_builder_proposal_processor.py:1348` |
| Skeleton materialization `ValueError` wraps as `AIBuilderArchitectureError` | `backend/tests/unittests/flows/ai_builder/test_ai_builder_create_compiler.py:2118` |
| `MaterializationError` public parent | `backend/tests/unittests/flows/ai_builder/test_ai_builder_materialization_bridge.py:724` |
| `architecture` is not a repair reason | `backend/tests/unittests/flows/ai_builder/test_ai_builder_proposal_telemetry.py:136` |

### Claude Peer Review

| Iteration | Artifact | Verdict | Green light | Minimum score | Outcome |
|---:|---|---|---|---:|---|
| 1 | `.codex/artifacts/claude-peer-loop-batch-11-1c-architecture-error-plan-20260503T024035Z.md` | `changes_required` | `no` | 6 | Required telemetry policy, explicit parent class, invariant classification, and critic split. |
| 2 | `.codex/artifacts/claude-peer-loop-batch-11-1c-architecture-error-plan-verification-20260503T024513Z.md` | `changes_required` | `no` | 7 | Found the broad `_process_outline_arguments` catch would swallow architecture errors and that repair reasons still aliased failure kinds. |
| 3 | `.codex/artifacts/claude-peer-loop-batch-11-1c-architecture-error-plan-verification-3-20260503T024858Z.md` | `green` | `yes` | 7 | Approved the revised plan. Non-blocking edit-path catch was dropped before implementation to keep scope create-path focused. |
| 4 | `.codex/artifacts/claude-peer-loop-batch-11-1c-architecture-error-implementation-20260503T030741Z.md` | `green` | `yes` | 8 | Content green; wrapper parse failed because the response used bold output-contract labels. |
| 5 | `.codex/artifacts/claude-peer-loop-batch-11-1c-architecture-error-final-verification-contract-20260503T031047Z.md` | `green` | `yes` | 9 | Parser-clean final verification after renaming repair-reason conversion. |

### Accepted Claude Findings

| Finding | Resolution |
|---|---|
| Architecture failures need telemetry but must not invoke repair. | Added `architecture` to `ProposalFailureKind`, split `ProposalRepairReason`, and added zero-repair assertions. |
| `AIBuilderArchitectureError` must not inherit `ValueError`. | Added a shared `Exception` subclass and reparented `MaterializationError`. |
| Critic invariants need explicit semantic/architecture policy. | Added `kind` to every invariant and tests for the complete id map. |
| `render_critic_issues` must not become a parallel evaluator. | Added `evaluate_critic_invariants` and made render/enforce consume it. |
| `_process_outline_arguments` broad catch would swallow the new error. | Added an explicit re-raise before the broad fallback. |
| Edit-flow catch was speculative in this create-path slice. | Dropped it; edit-path mechanics remain a follow-up slice. |
| Repair conversion helper name was stale after the repair-reason split. | Renamed it to `proposal_repair_reason_from_tool_failure` and renamed local variables at call sites. |

### Validation

| Command | Result |
|---|---|
| `cd backend && uv run pytest tests/unittests/flows/ai_builder/test_ai_builder_plan_quality_critic.py tests/unittests/flows/ai_builder/test_ai_builder_proposal_processor.py tests/unittests/flows/ai_builder/test_ai_builder_create_compiler.py tests/unittests/flows/ai_builder/test_ai_builder_materialization_bridge.py tests/unittests/flows/ai_builder/test_ai_builder_proposal_telemetry.py -q` | Passed: `206 passed`, one existing Starlette multipart warning. |
| `cd backend && uv run pyright <11.1c touched source/test files>` | Passed: `0 errors, 0 warnings, 0 informations`. |
| `cd backend && uv run ruff check <11.1c touched source/test files>` | Passed. |
| `cd backend && uv run ruff format --check <11.1c touched source/test files>` | Passed: `13 files already formatted`. |
| `cd backend && uv run lint-imports --no-cache` | Passed: 3 contracts kept, 0 broken. |
| `git diff --check -- <11.1c touched paths>` | Passed. |
| `./scripts/gate-local/anti_slippage.sh --worktree` | Passed: `anti-slippage: worktree clean`. |
| Added-line slop grep for `deprecated`, `legacy`, `backwards compatibility`, session/tooling references, and TODO/FIXME markers | Passed with no matches. |
| Claude final implementation verification | Passed: parser-clean `GREEN_LIGHT: yes`, `MIN_SCORE: 9`. |

### Carry-Forward

| Item | Owner slice |
|---|---|
| Edit-path fill/preserve/reject mechanics. | Next 11.1 follow-up slice |
| Promote any manual audio-to-DOCX API smoke failures into the automated corpus. | 11.1 success gate |
| Watch `ai_builder_step_skeleton.py` size if edit mechanics add more policy. | Next 11.1 follow-up slice |

### 11.1a Carry-Forward Closed In 11.1b

| Item | 11.1b closure |
|---|---|
| Make `compile_outline_to_create_draft` consume `materialize_step_skeleton`. | Done through `StepSkeletonPlan.compose`. |
| Delete or move `_derive_step_output_type`, `_derive_step_input_source`, `_derive_step_input_type`, `_requires_server_owned_fan_in`, `_ensure_required_server_owned_fan_in`, `_document_delivery_mode_for_step`, and `_ensure_final_artifact_step`. | Done; create-outline no longer owns those mechanics helpers. |
| Delete equivalence tests once compiler consumes the skeleton directly. | Done; replacement tests assert behavior through the compiler and registry invariant. |
| Watch `ai_builder_step_skeleton.py` size during integration. | Carried to 11.1c as a split trigger if more compose/materializer code is added. |

## 11.1d Edit-Path Fill, Preserve, And Reject Mechanics

### Scope

Implemented the edit-path mechanics follow-up from 11.1c. This slice keeps
create and edit semantics aligned without adding compatibility paths or turning
user-authored invalid edits into architecture failures.

### Source Changes

| Area | Evidence | Decision |
|---|---|---|
| Shared new-step mechanics validation | `backend/src/intric/flows/ai_builder/ai_builder_new_step_mechanics.py:17` | Added one per-new-step mechanics validator for first-step source, runtime upload, document delivery, citations, structured output fields, output mode compatibility, and form-field references. |
| Create validator reuse | `backend/src/intric/flows/ai_builder/ai_builder_create_validator.py:29` | Replaced duplicated create-only mechanics checks with the shared validator while keeping create-only form declaration and previous-field rules local. |
| Edit fill owner | `backend/src/intric/flows/ai_builder/ai_builder_edit_mechanics.py:19` | Added an edit-only fill pass that defaults missing runtime upload flags for first file/audio/document `flow_input` add operations and preserves explicit choices through `model_fields_set`. |
| Edit proposal ordering | `backend/src/intric/flows/ai_builder/ai_builder_edit_proposal.py:129` | Runs malformed/ref cleanup, then fill, then validation so user-authored conflicts remain validation feedback. |
| Edit add validation | `backend/src/intric/flows/ai_builder/ai_builder_edit_validator.py:167` | Edit add operations now use the same per-new-step mechanics validator with the resolved insert index. |
| Edit modify rejection | `backend/src/intric/flows/ai_builder/ai_builder_edit_validator.py:315` | Explicit modify-patch `output_mode` conflicts are rejected against the merged persisted step plus patch and return field/value feedback. |
| Modify-patch output-mode derivation | `backend/src/intric/flows/ai_builder/ai_builder_edit_compiler.py:400` | When a modify patch omits `output_mode`, the compiler derives it through the existing `derive_new_step_output_mode` owner instead of preserving stale mechanics. Explicit output modes remain user-authored and validated. |
| Document delivery inference | `backend/src/intric/flows/ai_builder/ai_builder_edit_compiler.py:420` | Reconstructs the `document_delivery_mode` needed by the derivation function from the effective persisted step shape. |

### Test Changes

| Coverage | Evidence |
|---|---|
| Edit fill defaults, explicit runtime preservation, and non-first no-fill behavior | `backend/tests/unittests/flows/ai_builder/test_ai_builder_edit_mechanics.py:32`, `:61`, `:94` |
| Edit add validation through the shared mechanics owner | `backend/tests/unittests/flows/ai_builder/test_ai_builder_edit_validator.py:387`, `:415`, `:445`, `:473`, `:500`, `:531` |
| Edit modify explicit mechanics conflict feedback | `backend/tests/unittests/flows/ai_builder/test_ai_builder_edit_validator.py:598` |
| Modify-patch output-mode derivation and preservation | `backend/tests/unittests/flows/ai_builder/test_ai_builder_edit_compiler.py:400`, `:427`, `:454`, `:483` |
| Proposal feedback for user-authored mechanics conflict | `backend/tests/unittests/flows/ai_builder/test_ai_builder_proposal_processor.py:2269` |

### Claude Peer Review

| Iteration | Artifact | Verdict | Green light | Minimum score | Outcome |
|---:|---|---|---|---:|---|
| 1 | `.codex/artifacts/claude-peer-loop-batch-11-1d-edit-path-mechanics-plan-20260503T032518Z.md` | `changes_required` | `no` | 6 | Rejected duplicate create-validator logic in edit validator and underspecified modify-patch derivation. |
| 2 | `.codex/artifacts/claude-peer-loop-batch-11-1d-edit-path-mechanics-plan-verification-20260503T032907Z.md` | `green` | `yes` | 7 | Accepted shared validator, edit fill owner, compiler derivation helper, and validation-feedback classification. |
| 3 | `.codex/artifacts/claude-peer-loop-batch-11-1d-edit-path-mechanics-implementation-verification-20260503T034729Z.md` | `green` | `yes` | 8 | Accepted implementation. Non-blocking coverage questions were answered with extra edit add and compiler tests before commit. |

### Accepted Claude Findings

| Finding | Resolution |
|---|---|
| Do not duplicate create-validator mechanics in edit-validator. | Added `validate_new_step_mechanics` and made create/edit add paths call it. |
| Fill mechanics should not live in `normalize_edit_draft_mechanics`. | Added `fill_edit_draft_mechanics` as a sibling edit-only fill pass after cleanup normalization. |
| Modify patches must derive output mode against the merged effective step, not patch fields alone. | `_derive_modify_patch_output_mode` builds a transient `NewStepDraft` from the effective step and calls `derive_new_step_output_mode`. |
| Explicit user-authored conflicts are validation feedback, not architecture errors. | `process_edit_arguments` returns `failure_kind="validation"` before compile/store for explicit invalid `output_mode` combinations. |
| Edit add shared-validator coverage should include more than runtime flags. | Added edit add tests for media source mismatch and audio-citation rejection. |
| PDF delivery-mode inference needed coverage. | Added a template-fill DOCX-to-PDF modify-patch derivation test. |

### Validation

| Command | Result |
|---|---|
| `cd backend && uv run pytest tests/unittests/flows/ai_builder/test_ai_builder_edit_mechanics.py tests/unittests/flows/ai_builder/test_ai_builder_edit_normalizer.py tests/unittests/flows/ai_builder/test_ai_builder_edit_validator.py tests/unittests/flows/ai_builder/test_ai_builder_edit_compiler.py tests/unittests/flows/ai_builder/test_ai_builder_create_compiler.py tests/unittests/flows/ai_builder/test_ai_builder_create_dataflow.py tests/unittests/flows/ai_builder/test_ai_builder_materialization_bridge.py tests/unittests/flows/ai_builder/test_ai_builder_proposal_processor.py -q` | Passed: `239 passed`, one existing Starlette multipart warning. |
| `cd backend && uv run pyright <11.1d touched source/test files>` | Passed: `0 errors, 0 warnings, 0 informations`. |
| `cd backend && uv run ruff check <11.1d touched source/test files>` | Passed. |
| `cd backend && uv run ruff format --check <11.1d touched source/test files>` | Passed: `10 files already formatted`. |
| `git diff --check -- <11.1d touched paths>` | Passed. |
| Claude implementation verification | Passed: `GREEN_LIGHT: yes`, `MIN_SCORE: 8`. |

### Carry-Forward

| Item | Owner slice |
|---|---|
| If `derive_new_step_output_mode` starts depending on additional `NewStepDraft` fields, split the derivation core into an input/output/delivery-mode function and have both create/edit call it. | Future mechanics cleanup |
| Watch for a fourth edit operation walker before extracting shared traversal. | Future edit-path cleanup |
| Promote manual/API smoke failures into the automated corpus before closing the 11.1 success gate. | 11.1 success gate |

## 11.2a Swedish Slot Resolver Corpus And Existing Slot Contract

### Scope

Implemented the corpus-first part of 11.2. This slice freezes the Swedish
resolver evaluation target, derives legal expected values from the existing
question catalog, and measures the current keyword prior through the real
planning-state builder. It does not implement model-backed resolution or claim
the final 11.2 accuracy target.

### Source Changes

| Area | Evidence | Decision |
|---|---|---|
| Planning-state slot contract | `backend/src/intric/flows/ai_builder/planning_state.py:61`, `:70` | Extended the existing `ResolvedSlot` contract for future model output by adding `source="model"` and `confidence="low"` rather than creating another resolver decision type. |
| Legal slot values | `backend/src/intric/flows/ai_builder/question_catalog.py:575` | Added `legal_slot_values()` so corpus labels and future resolver validation use the question catalog as the value owner. |
| Slot corpus tags | `backend/tests/integration/flows/ai_builder/benchmark/cases.py:64` | Added closed coverage tags for material type, output/API shape, structured extraction, comparison, multi-step, and ambiguous prompts. |
| Slot corpus case type | `backend/tests/integration/flows/ai_builder/benchmark/cases.py:114` | Added `SlotResolverCorpusCase` next to the existing benchmark and reliability corpus types. |
| Frozen corpus | `backend/tests/integration/flows/ai_builder/benchmark/cases.py:599` | Added 80 Swedish, domain-neutral prompts with catalog-backed expected slots and coverage tags. |

### Test Changes

| Coverage | Evidence |
|---|---|
| Model/low slot contract | `backend/tests/unittests/flows/ai_builder/test_planning_state.py:246` |
| Catalog-derived legal slot values | `backend/tests/unittests/flows/ai_builder/test_question_catalog.py:337`, `:343` |
| Corpus count, unique IDs, and no overlap with existing benchmark IDs | `backend/tests/integration/flows/ai_builder/benchmark/test_slot_resolver_corpus.py:55` |
| Swedish prompts, non-empty labels, and non-empty coverage tags | `backend/tests/integration/flows/ai_builder/benchmark/test_slot_resolver_corpus.py:66` |
| Expected slot names and values use known slots plus catalog legal values or `unknown` | `backend/tests/integration/flows/ai_builder/benchmark/test_slot_resolver_corpus.py:77` |
| Per-tag minimum distribution | `backend/tests/integration/flows/ai_builder/benchmark/test_slot_resolver_corpus.py:88` |
| Domain-neutral prompt guard | `backend/tests/integration/flows/ai_builder/benchmark/test_slot_resolver_corpus.py:98` |
| Keyword-prior baseline through `build_planning_state_from_conversation` | `backend/tests/integration/flows/ai_builder/benchmark/test_slot_resolver_corpus.py:106` |

### Baseline

| Metric | Value |
|---|---:|
| Corpus cases | 80 |
| Expected slot labels | 276 |
| Keyword-prior matches | 229 |
| Observed keyword-prior score | 0.830 |
| Guard floor in test | 0.70 |
| Final 11.2 resolver target | >= 0.85 |

The guard floor protects against accidental baseline collapse only. It is not
the Batch 11.2 resolver success target.

### Claude Peer Review

| Iteration | Artifact | Verdict | Green light | Minimum score | Outcome |
|---:|---|---|---|---:|---|
| 1 | `.codex/artifacts/claude-peer-loop-batch-11-2a-swedish-slot-resolver-plan-20260503T040339Z.md` | `changes_required` | `no` | 5 | Rejected a parallel resolver contract, prompt-only baseline, third taxonomy, missing domain-neutrality guard, and speculative model telemetry. |
| 2 | `.codex/artifacts/claude-peer-loop-batch-11-2a-swedish-slot-resolver-plan-verification-20260503T040804Z.md` | `green` | `yes` | 8 | Accepted the existing-contract corpus split and baseline measurement through the real planning-state builder. |
| 3 | `.codex/artifacts/claude-peer-loop-batch-11-2a-swedish-slot-resolver-implementation-20260503T042153Z.md` | `green` | `yes` | 8 | Accepted implementation; non-blocking notes were handled with exact baseline documentation and two intent comments. |

### Accepted Claude Findings

| Finding | Resolution |
|---|---|
| Do not create a parallel `SlotResolverDecision` contract. | Extended the existing `ResolvedSlot` source/confidence literals. |
| Do not measure a prompt-only projection. | Baseline test calls `build_planning_state_from_conversation`. |
| Do not duplicate slot legal values in a resolver taxonomy. | Added `legal_slot_values()` from `QUESTION_CATALOG`. |
| Add domain-neutrality enforcement. | Added a prompt denylist test for municipal-domain terms. |
| Record exact baseline instead of only a soft floor. | Recorded `229/276 = 0.830` here and in the retrospective. |
| Explain `unknown` baseline scoring and `HTTP_API` coverage semantics. | Added two focused test/data comments that document non-obvious corpus decisions. |
| JSONB round-trip for model/low belongs with persisted resolver writes. | Carried to 11.2b. |

### Validation

| Command | Result |
|---|---|
| `cd backend && uv run pytest tests/unittests/flows/ai_builder/test_planning_state.py tests/unittests/flows/ai_builder/test_question_catalog.py tests/integration/flows/ai_builder/benchmark/test_slot_resolver_corpus.py -q` | Passed: `99 passed`, 17 warnings from existing deprecations and one existing serializer warning. |
| `cd backend && uv run pyright src/intric/flows/ai_builder/planning_state.py src/intric/flows/ai_builder/question_catalog.py tests/integration/flows/ai_builder/benchmark/cases.py tests/integration/flows/ai_builder/benchmark/test_slot_resolver_corpus.py tests/unittests/flows/ai_builder/test_planning_state.py tests/unittests/flows/ai_builder/test_question_catalog.py` | Passed: `0 errors, 0 warnings, 0 informations`. |
| `cd backend && uv run ruff check src/intric/flows/ai_builder/planning_state.py src/intric/flows/ai_builder/question_catalog.py tests/integration/flows/ai_builder/benchmark/cases.py tests/integration/flows/ai_builder/benchmark/test_slot_resolver_corpus.py tests/unittests/flows/ai_builder/test_planning_state.py tests/unittests/flows/ai_builder/test_question_catalog.py` | Passed. |
| `cd backend && uv run ruff format --check src/intric/flows/ai_builder/planning_state.py src/intric/flows/ai_builder/question_catalog.py tests/integration/flows/ai_builder/benchmark/cases.py tests/integration/flows/ai_builder/benchmark/test_slot_resolver_corpus.py tests/unittests/flows/ai_builder/test_planning_state.py tests/unittests/flows/ai_builder/test_question_catalog.py` | Passed: `6 files already formatted`. |
| `cd backend && uv run lint-imports --no-cache` | Passed: 3 contracts kept, 0 broken. |
| `git diff --check -- <11.2a touched paths>` | Passed. |
| `./scripts/gate-local/anti_slippage.sh --worktree` | Passed: `anti-slippage: worktree clean`. |
| Added-line slop grep for `deprecated`, `legacy`, source-control/session/tooling comments, and TODO/FIXME markers | Passed with no matches. |

### Carry-Forward

| Item | Owner slice |
|---|---|
| Model-backed resolver result model and parser. | 11.2b |
| Follow-up behavior for unknown or low-confidence architecture slots. | 11.2b |
| Resolver accuracy gate of at least 85% on the frozen 80-case corpus. | 11.2b |
| Keyword-prior deletion criterion and disagreement measurement. | 11.2b |
| Resolver telemetry for model, tenant, confidence, capability path, and latency. | 11.2b |
| JSONB round-trip coverage for `source="model"` and `confidence="low"`. | 11.2b |

## 11.2b Model Slot Resolver Runtime Overlay

### Scope

Implemented the model-backed resolver runtime overlay for PlanningState. This
slice reuses the existing `ResolvedSlot` contract from 11.2a, deletes the old
discovery-only semantic result/parser/cache path, and keeps the deterministic
corpus baseline on the sync builder path.

### Source Changes

| Area | Evidence | Decision |
|---|---|---|
| Shared classifier core | `backend/src/intric/flows/ai_builder/ai_builder_slot_classifier.py:1` | Added the single LLM slot classifier with `ClassifiedSlot`, `SlotClassificationResult`, canonical `slots/slot_name` parsing, shared cache, prompt hash helper, and tenant-aware logs. |
| Discovery semantic classification | `backend/src/intric/flows/ai_builder/ai_builder_semantic_adjudication.py:44` | Kept pending-question adjudication local, but moved discovery slot classification to the shared classifier. The old `SemanticAdjudicationResult` / `SemanticAdjudicationSignal` types and `_NON_ADJUDICABLE_QUESTION_IDS` constant were removed. |
| Non-LLM slot policy | `backend/src/intric/flows/ai_builder/ai_builder_slot_vocabulary.py:26` | Added `NON_LLM_RESOLVABLE_SLOT_NAMES` for DOCX/PDF generation mode so downstream setup choices remain explicit user/deterministic decisions. |
| Runtime PlanningState overlay | `backend/src/intric/flows/ai_builder/ai_builder_discovery_runtime.py:72` | Added `build_runtime_planning_state()` as the async owner for model classification and PlanningState overlay. |
| Planner wiring | `backend/src/intric/flows/ai_builder/ai_builder_planner.py:552` | `_prepare_planner_request` now uses the runtime PlanningState builder before action-policy computation. Blocking discovery passes `allow_classification=False`. |
| Sync merge contract | `backend/src/intric/flows/ai_builder/planning_state_builder.py:161` | Added `merge_llm_resolved_slots()` with conservative priority: explicit/summary/default evidence wins; high model can replace weak defaults; medium model can replace heuristics and fill missing slots; low/unknown/non-LLM values are ignored. |
| Discovery answer merge | `backend/src/intric/flows/ai_builder/ai_builder_discovery_profile_builder.py:274` | Renamed classifier-to-answer projection to `classification_answers()` and made low/unknown slots unresolved. |
| Discovery decision engine | `backend/src/intric/flows/ai_builder/ai_builder_discovery_decision_engine.py:244` | Rewired confidence resolution to `SlotClassificationResult.slots` and the shared `UNKNOWN_SLOT_VALUE`. |

### Test Changes

| Coverage | Evidence |
|---|---|
| Canonical classifier shape, illegal-value filtering, cache reuse, prompt hash, and tenant logging | `backend/tests/unittests/flows/ai_builder/test_ai_builder_slot_classifier.py:27`, `:48`, `:105`, `:132`, `:180` |
| Runtime gates for strong resolved slots, weak-slot upgrade, empty text, disabled classification, and overlay persistence | `backend/tests/unittests/flows/ai_builder/test_ai_builder_discovery_runtime.py:71`, `:93`, `:146`, `:164`, `:182` |
| DOCX/PDF model-resolution exclusion | `backend/tests/unittests/flows/ai_builder/test_ai_builder_semantic_adjudication.py:164`, `:194` |
| Merge priority and skip rules | `backend/tests/unittests/flows/ai_builder/test_planning_state_builder.py:289`, `:336`, `:367`, `:397`, `:424`, `:437`, `:450`, `:469` |
| Non-LLM slot vocabulary | `backend/tests/unittests/flows/ai_builder/test_ai_builder_slot_vocabulary.py:35` |
| Planner blocking-discovery zero-LLM behavior | `backend/tests/unittests/flows/ai_builder/test_discovery_flow.py:1881` |
| Corpus baseline remains deterministic | `backend/tests/integration/flows/ai_builder/benchmark/test_slot_resolver_corpus.py:106` |

### Claude Peer Review

| Iteration | Artifact | Verdict | Green light | Minimum score | Outcome |
|---:|---|---|---|---:|---|
| 1 | `.codex/artifacts/claude-peer-loop-batch-11-2b-slot-resolver-runtime-plan-20260503T043632Z.md` | `changes_required` | `no` | 5 | Rejected a duplicate resolver module, async merge logic in the sync builder, weak merge priority, unstable evidence, and underspecified logging/tests. |
| 2 | `.codex/artifacts/claude-peer-loop-batch-11-2b-slot-resolver-runtime-plan-verification-20260503T044044Z.md` | `changes_required` | `no` | 7 | Required one canonical JSON shape, type rename, prompt hash outside result type, explicit cache key, clearer gate, and PDF parity with DOCX non-LLM policy. |
| 3 | `.codex/artifacts/claude-peer-loop-batch-11-2b-slot-resolver-runtime-plan-verification-3-20260503T044548Z.md` | `green` | `yes` | 8 | Approved the revised plan with low implementation clarifications. |
| 4 | `.codex/artifacts/claude-peer-loop-batch-11-2b-slot-resolver-runtime-implementation-20260503T050605Z.md` | `green` | `yes` | 7 | Accepted the implementation and identified low cleanup items. |
| 5 | `.codex/artifacts/claude-peer-loop-batch-11-2b-slot-resolver-runtime-final-verification-20260503T051437Z.md` | `green` | `yes` | 8 | Confirmed cleanup and weak-slot candidate fix. |
| 6 | `.codex/artifacts/claude-peer-loop-batch-11-2b-slot-resolver-runtime-post-dead-branch-removal-20260503T052014Z.md` | `green` | `yes` | 9 | Content green but wrapper parse failed because Claude bolded the output-contract fields. |
| 7 | `.codex/artifacts/claude-peer-loop-batch-11-2b-slot-resolver-runtime-parser-clean-final-20260503T052115Z.md` | `green` | `yes` | 9 | Parser-clean final verification. |

### Accepted Claude Findings

| Finding | Resolution |
|---|---|
| Do not add a duplicate `ai_builder_slot_resolver.py`. | Added one shared `ai_builder_slot_classifier.py` used by discovery and PlanningState runtime. |
| Keep `planning_state_builder.py` synchronous. | Added only a sync mutation merge function; async LLM wiring lives in `ai_builder_discovery_runtime.py`. |
| Do not preserve the old `signals/question_id` shape during the refactor. | Parser accepts only canonical `slots/slot_name`; tests assert old shape produces no slots. |
| Rename stale semantic result types. | Deleted `SemanticAdjudicationResult` / `SemanticAdjudicationSignal` and introduced `SlotClassificationResult` / `ClassifiedSlot`. |
| Keep `prompt_hash` out of the result type. | Added `slot_classification_prompt_hash()` and made `merge_llm_resolved_slots(..., prompt_hash=...)` require it. |
| Consolidate non-LLM slot policy and include PDF parity. | Added `NON_LLM_RESOLVABLE_SLOT_NAMES = {"docx_output_mode", "pdf_generation_mode"}`. |
| Do not use `litellm_client=None` as an implicit gate. | Added explicit `allow_classification` on `build_runtime_planning_state()`. |
| Replace magic `unknown` literals with one owner. | Exported `UNKNOWN_SLOT_VALUE` from the classifier and reused it in merge/discovery consumers. |
| Runtime candidate set must allow model upgrades of weak deterministic slots. | `_llm_candidate_slot_values()` includes missing slots plus heuristic/policy-default slots; runtime test covers policy-default upgrade. |
| Remove dead model-to-model recency branch. | Deleted the merge branch and its test because model-sourced slots are not live runtime candidates today. |

### Validation

| Command | Result |
|---|---|
| `cd backend && uv run pytest tests/unittests/flows/ai_builder/test_ai_builder_slot_classifier.py tests/unittests/flows/ai_builder/test_ai_builder_discovery_runtime.py tests/unittests/flows/ai_builder/test_planning_state_builder.py tests/unittests/flows/ai_builder/test_ai_builder_semantic_adjudication.py tests/unittests/flows/ai_builder/test_ai_builder_slot_vocabulary.py tests/unittests/flows/ai_builder/test_ai_builder_planner.py tests/unittests/flows/ai_builder/test_discovery_flow.py tests/unittests/flows/ai_builder/test_ai_builder_understanding_goldens.py tests/integration/flows/ai_builder/benchmark/test_slot_resolver_corpus.py -q` | Passed: `129 passed`, 16 existing warnings from unrelated deprecations. |
| `cd backend && uv run pyright <11.2b touched source/test files>` | Passed: `0 errors, 0 warnings, 0 informations`. |
| `cd backend && uv run ruff check <11.2b touched source/test files>` | Passed. |
| `cd backend && uv run ruff format --check <11.2b touched source/test files>` | Passed: `18 files already formatted`. |
| `cd backend && uv run lint-imports --no-cache` | Passed: 3 contracts kept, 0 broken. |
| `git diff --check` | Passed. |
| `./scripts/gate-local/anti_slippage.sh --worktree` | Passed. |
| Added-line slop grep for source/test `deprecated`, `legacy`, `backwards compatibility`, source-control/session/tooling comments, and TODO/FIXME markers | Passed with no matches. |

### Carry-Forward

| Item | Owner slice |
|---|---|
| Provider-backed evaluation against the frozen 80-case corpus before claiming `>= 0.85`. | 11.2c or the next resolver eval slice |
| Keyword-prior deletion criterion and disagreement measurement. | Later 11.2 follow-up |
| Unify discovery question-id and PlanningState slot-name namespaces so classifier cache sharing works across both surfaces more often. | Future cleanup |
| If another weak slot source is introduced, lift the weak-source set used by runtime gating and merge priority into one named owner. | Future slot-source extension |

## 11.2c Slot Resolver Provider Evaluation Harness Plan

### Scope

Implement a local, opt-in provider evaluation harness for the frozen 80-case
slot resolver corpus. The harness measures the live runtime PlanningState path
introduced in 11.2b while keeping normal tests deterministic and avoiding raw
provider-response artifacts in git.

### Reuse-Before-Inventing

| Existing candidate | Decision |
|---|---|
| `backend/tests/integration/flows/ai_builder/benchmark/cases.py` | Reuse as the only slot prompt corpus owner. |
| `backend/tests/integration/flows/ai_builder/benchmark/runner.py` | Do not extend; it measures discovery benchmark archetypes and baseline JSON, not provider-backed runtime slot overlay. |
| `backend/tests/integration/flows/ai_builder/benchmark/test_slot_resolver_corpus.py` scoring helper | Extract into `slot_resolver_scoring.py` so deterministic baseline and provider eval use identical `unknown` match semantics. |
| `manual-eval-runbook.md` | Keep as API create/revise/edit smoke-suite owner; 11.2c is narrower and scores slot resolver corpus values. |
| `build_runtime_planning_state()` | Reuse the runtime path under test instead of adding a second resolver execution path. |

### Planned Files

| File | Purpose |
|---|---|
| `backend/tests/integration/flows/ai_builder/benchmark/slot_resolver_scoring.py` | Shared per-slot scoring, corpus hash, and keyword/runtime agreement helpers. |
| `backend/tests/integration/flows/ai_builder/benchmark/slot_resolver_provider_eval.py` | Local CLI and pure scorecard helpers for provider-backed slot corpus eval. |
| `backend/tests/integration/flows/ai_builder/benchmark/test_slot_resolver_provider_eval.py` | Deterministic tests for scoring, config validation, dry-run behavior, and fake-provider live guardrails. |
| `backend/tests/integration/flows/ai_builder/benchmark/test_slot_resolver_corpus.py` | Import shared scoring helpers so the baseline floor and provider eval cannot diverge. |
| `docs/refactor/execution/batch-11-flow-ai-builder-reliability/retrospective-9.md` | Retrospective for 11.2c. |
| `docs/refactor/execution/batch-11-flow-ai-builder-reliability/claude-reconciliation-9.md` | Claude reconciliation for 11.2c. |

### Acceptance Criteria

- The live scorecard is generated only with explicit `--live` and
  `ENEO_AI_BUILDER_SLOT_EVAL_MODEL` plus
  `ENEO_AI_BUILDER_SLOT_EVAL_TENANT_ID`.
- Dry-run mode validates corpus/config and writes no live provider results.
- The gated metric is per-slot LLM-resolvable score on provider-success cases.
  Full runtime score and keyword-prior score are context, not gates.
- Target claim requires zero provider errors and a provider-success path for
  every corpus case.
- Score calculation exposes keyword-vs-runtime agreement/disagreement counts
  by slot name for the future keyword-prior deletion decision.
- Scorecards contain allow-listed model/config metadata and slot
  values/sources/confidence, but no raw provider response, completion text,
  reason fields, API key, full API base URL, tenant id, or prompt copy outside
  existing corpus ids.
- Normal pytest uses a fake LiteLLM client only.
- The `>= 0.85` target is recorded as unclaimed unless an actual live scorecard
  is produced.
- The harness uses bare `litellm` configured through the existing
  `configure_litellm_runtime(litellm)` function; it does not use
  `TenantModelAdapter` or database model lookup.
- Scorecards use `scorecard_schema_version=1`; meaning changes require a
  schema-version bump.
- The corpus hash covers case id, language, prompt, expected slots, and
  coverage tags.
- Valid live scorecards are produced from a fresh CLI process so the
  process-local classifier cache does not turn repeated in-process runs into
  cache hits. `provider_call_count` is a sanity counter, not a quality metric.

### Validation Commands

```bash
cd backend && uv run pytest tests/integration/flows/ai_builder/benchmark/test_slot_resolver_provider_eval.py tests/integration/flows/ai_builder/benchmark/test_slot_resolver_corpus.py -q
cd backend && uv run pytest tests/unittests/flows/ai_builder -q
cd backend && uv run pyright tests/integration/flows/ai_builder/benchmark/slot_resolver_scoring.py tests/integration/flows/ai_builder/benchmark/slot_resolver_provider_eval.py tests/integration/flows/ai_builder/benchmark/test_slot_resolver_provider_eval.py tests/integration/flows/ai_builder/benchmark/test_slot_resolver_corpus.py
cd backend && uv run ruff check tests/integration/flows/ai_builder/benchmark/slot_resolver_scoring.py tests/integration/flows/ai_builder/benchmark/slot_resolver_provider_eval.py tests/integration/flows/ai_builder/benchmark/test_slot_resolver_provider_eval.py tests/integration/flows/ai_builder/benchmark/test_slot_resolver_corpus.py
cd backend && uv run ruff format --check tests/integration/flows/ai_builder/benchmark/slot_resolver_scoring.py tests/integration/flows/ai_builder/benchmark/slot_resolver_provider_eval.py tests/integration/flows/ai_builder/benchmark/test_slot_resolver_provider_eval.py tests/integration/flows/ai_builder/benchmark/test_slot_resolver_corpus.py
git diff --check -- backend/tests/integration/flows/ai_builder/benchmark/slot_resolver_scoring.py backend/tests/integration/flows/ai_builder/benchmark/slot_resolver_provider_eval.py backend/tests/integration/flows/ai_builder/benchmark/test_slot_resolver_provider_eval.py backend/tests/integration/flows/ai_builder/benchmark/test_slot_resolver_corpus.py docs/refactor/execution/batch-11-flow-ai-builder-reliability
```

Optional live command when provider config exists:

```bash
cd backend && uv run python -m tests.integration.flows.ai_builder.benchmark.slot_resolver_provider_eval --live --output .codex/artifacts/slot-resolver-provider-eval-$(date -u +%Y%m%dT%H%M%SZ).json
```

### Local Provider Fixture Check

The current shell does not expose `ENEO_AI_BUILDER_SLOT_EVAL_*`,
`OPENAI_API_KEY`, `ANTHROPIC_API_KEY`, `AZURE_OPENAI_API_KEY`, or
`ENEO_LOCAL_*` variable names. The slice can add and validate the harness, but
cannot claim the provider-backed target in this environment without additional
model configuration.

`.codex/artifacts/` is ignored by repo `.gitignore` and local
`.git/info/exclude`, so optional live scorecards written there remain local
unless explicitly promoted.

### Claude Plan Review Iteration 1

- Artifact: `.codex/artifacts/claude-peer-loop-batch-11-2c-slot-resolver-provider-eval-plan-20260503T053808Z.md`
- Verdict: `changes_required`
- Green light: `no`
- Minimum score: `6`

Accepted findings:

| Finding | Resolution |
|---|---|
| The `>= 0.85` gate metric was ambiguous. | Made the gated metric per-slot LLM-resolvable score on provider-success cases; full score and keyword-prior score are context only. |
| Existing `unknown` match semantics could drift. | Planned `slot_resolver_scoring.py` and updated `test_slot_resolver_corpus.py` to share the same helper as provider eval. |
| Tenant id handling was unspecified. | Made `ENEO_AI_BUILDER_SLOT_EVAL_TENANT_ID` required for `--live` and excluded it from scorecards. |
| LiteLLM client construction owner was undefined. | Planned bare `litellm` plus existing runtime configuration, with no `TenantModelAdapter` or DB lookup. |
| Process-local classifier cache could skew repeated in-process live runs. | Made valid live scorecards fresh-CLI-process artifacts and documented `provider_call_count` as a sanity counter. |
| Scorecard schema and corpus hash were vague. | Pinned `scorecard_schema_version=1`, bump policy, and corpus hash inputs. |
| Provider failures could distort model accuracy. | Target claim now requires zero provider errors and every case reaching provider-success. |
| Redaction list missed API base and tenant id. | Added both to the banned scorecard data list and required allow-listed config metadata. |
| Validation set was too narrow. | Added full `tests/unittests/flows/ai_builder -q` to validation. |

### Plan Verification Iteration 2

- Artifact: `.codex/artifacts/claude-peer-loop-batch-11-2c-slot-resolver-provider-eval-plan-verification-20260503T054232Z.md`
- Verdict: `green`
- Green light: `yes`
- Minimum score: `8`

Accepted non-blocking findings:

| Finding | Resolution |
|---|---|
| `.git/info/exclude` is per-clone. | Verified repo `.gitignore` already excludes `.codex/*`; no source change needed. |
| Provider conservatism should be visible separately from wrong values. | Added unresolved counts by slot name in the agreement summary. |
| Schema bump policy should say how additive fields behave. | Scorecard includes a policy string: additive fields keep the version; removal, rename, or semantic change bumps it. |

## 11.2c Implementation Result

### Source And Test Changes

| Area | Evidence | Decision |
|---|---|---|
| Shared scoring owner | `backend/tests/integration/flows/ai_builder/benchmark/slot_resolver_scoring.py:1` | Added one scoring module for slot match semantics, `unknown` handling, summaries, agreement breakdown, and corpus hash. |
| Provider eval runner | `backend/tests/integration/flows/ai_builder/benchmark/slot_resolver_provider_eval.py:1` | Added safe dry-run default plus explicit `--live` mode using bare LiteLLM and the runtime PlanningState path. |
| Existing corpus test | `backend/tests/integration/flows/ai_builder/benchmark/test_slot_resolver_corpus.py:1` | Reused shared scoring helpers so the deterministic baseline and provider harness cannot diverge. |
| Provider eval tests | `backend/tests/integration/flows/ai_builder/benchmark/test_slot_resolver_provider_eval.py:1` | Added deterministic tests for scoring, hash input, config validation, redaction, fake-provider success, fake-provider error, and serialized score fields. |
| Broad validation drift | `backend/.importlinter:13`, `backend/tests/unittests/flows/ai_builder/test_ai_builder_service.py:1383`, `backend/tests/unittests/flows/ai_builder/test_ai_builder_server_actions.py:122`, `backend/tests/unittests/flows/ai_builder/test_deterministic_signals_extractor.py:22` | Updated import-linter source coverage for existing Flow siblings, made stale assertions match current committed behavior, and skipped host PDF fixture tests when WeasyPrint system libraries are absent. |

### Scorecard Behavior

| Item | Value |
|---|---|
| Scorecard schema version | `1` |
| Gated metric | Per-slot LLM-resolvable score on provider-success cases |
| Context metrics | Deterministic keyword-prior score and full runtime score |
| Target claim conditions | Zero provider errors and provider-success path for every corpus case |
| Dry-run result in this environment | `live=false`, `target_claimable=false`, `case_count=80`, keyword prior score `0.8297101449275363` |
| Live-provider status in this environment | Not run; required `ENEO_AI_BUILDER_SLOT_EVAL_MODEL` and `ENEO_AI_BUILDER_SLOT_EVAL_TENANT_ID` are absent |
| Raw output handling | Dry-run scorecard written to ignored `.codex/artifacts/slot-resolver-provider-eval-dry-run.json` for local verification only |

### Claude Implementation Review

- Artifact: `.codex/artifacts/claude-peer-loop-batch-11-2c-slot-resolver-provider-eval-implementation-20260503T055655Z.md`
- Verdict: `green`
- Green light: `yes`
- Minimum score: `8`

Accepted low-risk polish:

| Finding | Resolution |
|---|---|
| The server-action summary assertion had become too weak. | Replaced substring checks with the exact Swedish committed summary. |
| Cache-hit/no-call status was conservative but easy to misread. | Added a why-comment explaining that no provider call cannot claim a fresh live target. |
| Prompt-redaction coverage should inspect the scorecard shape, not only one phrase. | Added an assertion that serialized per-case scorecards do not include a `prompt` field. |

Final verification:

| Item | Value |
|---|---|
| Artifact | `.codex/artifacts/claude-peer-loop-batch-11-2c-slot-resolver-provider-eval-final-verification-20260503T060427Z.md` |
| Verdict | `green` |
| Green light | `yes` |
| Minimum score | `9` |

### Validation

| Command | Result |
|---|---|
| `cd backend && uv run pytest tests/integration/flows/ai_builder/benchmark/test_slot_resolver_provider_eval.py tests/integration/flows/ai_builder/benchmark/test_slot_resolver_corpus.py tests/unittests/flows/ai_builder/test_ai_builder_server_actions.py::test_server_builds_confirm_requirements_checkpoint_after_commit -q` | Passed: `15 passed`, 16 existing warnings. |
| `cd backend && uv run pytest tests/unittests/flows/ai_builder -q` | Passed after validation fixes: `1735 passed, 4 skipped`, 12 existing warnings. The skipped tests require host WeasyPrint system libraries. |
| `cd backend && uv run pyright tests/integration/flows/ai_builder/benchmark/slot_resolver_scoring.py tests/integration/flows/ai_builder/benchmark/slot_resolver_provider_eval.py tests/integration/flows/ai_builder/benchmark/test_slot_resolver_provider_eval.py tests/integration/flows/ai_builder/benchmark/test_slot_resolver_corpus.py tests/unittests/flows/ai_builder/test_ai_builder_server_actions.py tests/unittests/flows/ai_builder/test_ai_builder_service.py tests/unittests/flows/ai_builder/test_deterministic_signals_extractor.py` | Passed: `0 errors, 0 warnings, 0 informations`. |
| `cd backend && uv run ruff check <11.2c touched Python files>` | Passed. |
| `cd backend && uv run ruff format --check <11.2c touched Python files>` | Passed: `7 files already formatted`. |
| `cd backend && uv run lint-imports --no-cache` | Passed: 3 contracts kept, 0 broken. |
| `git diff --check -- <11.2c touched paths>` | Passed. |
| `cd backend && uv run python -m tests.integration.flows.ai_builder.benchmark.slot_resolver_provider_eval --output ../.codex/artifacts/slot-resolver-provider-eval-dry-run.json` | Passed; wrote ignored dry-run scorecard. |
| `cd backend && uv run python -m tests.integration.flows.ai_builder.benchmark.slot_resolver_provider_eval --live` | Failed as expected with exit code `2`; required model and tenant env vars are missing. |
| Added-line slop grep for source/test `deprecated`, `legacy`, `backwards compatibility`, source-control/session/tooling comments, and TODO/FIXME markers | Passed with no matches. |

### Carry-Forward

| Item | Owner slice |
|---|---|
| Run the live provider command with a real `ENEO_AI_BUILDER_SLOT_EVAL_MODEL` and `ENEO_AI_BUILDER_SLOT_EVAL_TENANT_ID`; record the redacted scorecard before claiming the `>= 0.85` target. | 11.2 provider eval follow-up |
| Use the agreement/disagreement breakdown to decide keyword-prior deletion criteria from real model behavior. | Later 11.2 follow-up |
| Avoid in-process repeated live eval runs unless the classifier cache gets an explicit runtime guard. Valid scorecards should come from fresh CLI processes. | Future eval harness hardening |

## 11.3a Proposal Resource Reference Material Owner Plan

### Scope

Batch 10 is complete in this branch through `832f4c1b`, and Batch 11 is active
through `e55f2be3`. This slice continues Batch 11 with form-field and enabled
resource reliability. After Claude plan review, 11.3a is narrowed to the
proposal resource-material owner. Form-field lifecycle goldens and the Pattern
Registry decision move to 11.3b.

| Concept | Evidence | Decision |
|---|---|---|
| Model/knowledge/MCP refs | `backend/src/intric/flows/ai_builder/ai_builder_resource_catalog.py` canonicalizes submitted refs and returns typed issues. | Extend this owner to produce typed proposal resource material. |
| Selected MCP refs | `backend/src/intric/flows/ai_builder/ai_builder_plan_proposal_task.py` currently renders selected tools from normalized MCP input separately from the available-resource block. | Keep policy text in the proposal task, but render selected server/tool refs from the same catalog material. |
| Discovery resource rendering | `backend/src/intric/flows/ai_builder/ai_builder_prompts.py` has localized discovery prompt rendering. | Explicitly defer until proposal rendering stabilizes; proposal is the path that emits create/edit draft refs. |
| Existing-flow assistants in edit mode | `backend/src/intric/flows/ai_builder/ai_builder_flow_context.py` renders assistant snapshots for existing steps. | Keep as context. Do not add a selectable assistant-ref field in this slice. |

### Planned Source Shape

| File | Change |
|---|---|
| `backend/src/intric/flows/ai_builder/ai_builder_resource_catalog.py` | Add typed proposal resource material for exact refs, selected MCP refs, and bounded descriptions. |
| `backend/src/intric/flows/ai_builder/ai_builder_plan_proposal_task.py` | Render proposal resource material from `AIBuilderResourceCatalog` instead of local dict helpers. |
| `backend/tests/unittests/flows/ai_builder/test_ai_builder_resource_catalog.py` | Pin exact resource-material rendering, selected MCP grouping, description clamp, and malformed resource omission. |
| `backend/tests/unittests/flows/ai_builder/test_ai_builder_plan_proposal_task.py` | Pin proposal prompt resource material and selected MCP tool material. |

### Non-Goals

- No selectable `assistant_ref` field. Current create/edit contracts define
  inline `AssistantSpec` and flow-managed assistants; selecting existing
  assistants needs a separate API/product contract with tenant/workspace
  allow-listing, permissions, and materializer behavior.
- No form-field goldens in 11.3a; they move to 11.3b with a non-overlapping
  scenario matrix and a Pattern Registry decision.
- No discovery-time rendering change in 11.3a; it gets a follow-up after the
  proposal renderer shape is proven.
- No compatibility, legacy, or deprecated paths for never-shipped Flow behavior.
- No generic helper files or comments that restate code.

### Claude Plan Review Iteration 1

- Artifact: `.codex/artifacts/claude-peer-loop-batch-11-3a-form-field-resource-plan-20260503T061515Z.md`
- Verdict: `changes_required`
- Green light: `no`
- Minimum score: `6`

Accepted findings:

| Finding | Resolution |
|---|---|
| Pattern Registry sufficiency was under-proved for multi-reference form-field lifecycle. | Split form-field goldens and Pattern Registry decision into 11.3b. |
| Available-resource and selected-MCP rendering could still drift. | 11.3a now routes both through one catalog-owned typed material shape. |
| Planned form-field goldens overlapped existing tests. | 11.3b now has a scenario matrix naming existing overlap and required new assertions. |
| Discovery-time resource rendering was unscoped. | Explicitly deferred with rationale because proposal rendering is the draft-emitting path. |
| Resource descriptions need a prompt-budget policy. | 11.3a now includes a catalog-owned description clamp. |
| Assistant-ref deferral needed a trigger condition. | Added the future trigger: tenant/workspace allow-list plus permission/materializer rules. |

### Plan Verification Iteration 2

- Artifact: `.codex/artifacts/claude-peer-loop-batch-11-3a-resource-plan-verification-20260503T061940Z.md`
- Verdict: `green`
- Green light: `yes`
- Minimum score: `8`

Accepted tightening notes:

| Finding | Resolution |
|---|---|
| The typed material shape needed a concrete name. | Planned frozen `AIBuilderResourceReferenceMaterial` / entry value objects in `ai_builder_resource_catalog.py`. |
| Prompt-local resource helpers should be deleted, not bypassed. | Added acceptance criteria for deleting `_resource_ref`, `_resource_display_name`, and `_resource_description`. |
| The description clamp needed a number. | Set `RESOURCE_DESCRIPTION_MAX_CHARS = 240` in the plan and test target. |
| Selected-MCP rendering should not normalize MCP resources in the proposal task after the move. | Added acceptance criteria for zero `normalize_ai_builder_mcp_resources` references in `ai_builder_plan_proposal_task.py`. |
| Assistant refs should be explicitly absent, not silently omitted. | Added that acceptance criterion until the allow-list/materializer/permission trigger exists. |
| Anti-slippage validation should be explicit. | Added `./scripts/gate-local/anti_slippage.sh --worktree` to the validation plan. |

### Validation Plan

```bash
cd backend && uv run pytest tests/unittests/flows/ai_builder/test_ai_builder_resource_catalog.py tests/unittests/flows/ai_builder/test_ai_builder_plan_proposal_task.py -q
cd backend && uv run pytest tests/unittests/flows/ai_builder -q
cd backend && uv run pyright src/intric/flows/ai_builder/ai_builder_resource_catalog.py src/intric/flows/ai_builder/ai_builder_plan_proposal_task.py tests/unittests/flows/ai_builder/test_ai_builder_resource_catalog.py tests/unittests/flows/ai_builder/test_ai_builder_plan_proposal_task.py
cd backend && uv run ruff check src/intric/flows/ai_builder/ai_builder_resource_catalog.py src/intric/flows/ai_builder/ai_builder_plan_proposal_task.py tests/unittests/flows/ai_builder/test_ai_builder_resource_catalog.py tests/unittests/flows/ai_builder/test_ai_builder_plan_proposal_task.py
cd backend && uv run ruff format --check src/intric/flows/ai_builder/ai_builder_resource_catalog.py src/intric/flows/ai_builder/ai_builder_plan_proposal_task.py tests/unittests/flows/ai_builder/test_ai_builder_resource_catalog.py tests/unittests/flows/ai_builder/test_ai_builder_plan_proposal_task.py
cd backend && uv run lint-imports --no-cache
./scripts/gate-local/anti_slippage.sh --worktree
git diff --check -- backend/src/intric/flows/ai_builder/ai_builder_resource_catalog.py backend/src/intric/flows/ai_builder/ai_builder_plan_proposal_task.py backend/tests/unittests/flows/ai_builder/test_ai_builder_resource_catalog.py backend/tests/unittests/flows/ai_builder/test_ai_builder_plan_proposal_task.py docs/refactor/execution/batch-11-flow-ai-builder-reliability
```

Docker status: `docker ps --format '{{.Names}}'` is blocked in this tool
profile before Docker runs. Use local `uv` commands unless Docker becomes
available later in the slice.

### Implementation Result

| Area | Evidence | Decision |
|---|---|---|
| Typed resource material | `backend/src/intric/flows/ai_builder/ai_builder_resource_catalog.py` | Added frozen resource-reference value objects and a material builder from the validation catalog. |
| Description budget | `backend/src/intric/flows/ai_builder/ai_builder_resource_catalog.py` | Added `RESOURCE_DESCRIPTION_MAX_CHARS = 240` and bounded rendered descriptions. |
| Proposal prompt rendering | `backend/src/intric/flows/ai_builder/ai_builder_plan_proposal_task.py` | Available resources and selected MCP refs now consume the same catalog material; prompt-local resource dict helpers were deleted. |
| Resource tests | `backend/tests/unittests/flows/ai_builder/test_ai_builder_resource_catalog.py` | Pinned exact refs, selected MCP server/tool grouping, malformed resource omission, truncation, and clamp-boundary behavior. |
| Prompt tests | `backend/tests/unittests/flows/ai_builder/test_ai_builder_plan_proposal_task.py` | Pinned assistant-ref absence in proposal material while existing resource/MCP prompt assertions continue to pass. |

### Claude Implementation Review

- Artifact: `.codex/artifacts/claude-peer-loop-batch-11-3a-resource-implementation-20260503T062808Z.md`
- Verdict: `green`
- Green light: `yes`
- Minimum score: `9`

Accepted tightening:

| Finding | Resolution |
|---|---|
| Unknown selected MCP refs are now dropped by the catalog intersection; this should be explicit. | Added `test_plan_proposal_prompt_drops_selected_mcp_ref_that_is_not_in_catalog`. |

### Claude Final Verification

- Artifact: `.codex/artifacts/claude-peer-loop-batch-11-3a-resource-final-verification-20260503T063337Z.md`
- Verdict: `green`
- Green light: `yes`
- Minimum score: `9`

Non-blocking note:

| Finding | Resolution |
|---|---|
| Unrelated dirty files remain in the worktree. | Stage only the 11.3a backend files and Batch 11 docs; do not bulk-add. |

### Validation Result

| Command | Result |
|---|---|
| `cd backend && uv run pytest tests/unittests/flows/ai_builder/test_ai_builder_resource_catalog.py tests/unittests/flows/ai_builder/test_ai_builder_plan_proposal_task.py -q` | Passed: `15 passed`. |
| `cd backend && uv run pytest tests/unittests/flows/ai_builder -q` | Passed: `1738 passed, 4 skipped`, 12 existing warnings. |
| `cd backend && uv run pyright src/intric/flows/ai_builder/ai_builder_resource_catalog.py src/intric/flows/ai_builder/ai_builder_plan_proposal_task.py tests/unittests/flows/ai_builder/test_ai_builder_resource_catalog.py tests/unittests/flows/ai_builder/test_ai_builder_plan_proposal_task.py` | Passed: `0 errors, 0 warnings, 0 informations`. |
| `cd backend && uv run ruff check src/intric/flows/ai_builder/ai_builder_resource_catalog.py src/intric/flows/ai_builder/ai_builder_plan_proposal_task.py tests/unittests/flows/ai_builder/test_ai_builder_resource_catalog.py tests/unittests/flows/ai_builder/test_ai_builder_plan_proposal_task.py` | Passed. |
| `cd backend && uv run ruff format --check src/intric/flows/ai_builder/ai_builder_resource_catalog.py src/intric/flows/ai_builder/ai_builder_plan_proposal_task.py tests/unittests/flows/ai_builder/test_ai_builder_resource_catalog.py tests/unittests/flows/ai_builder/test_ai_builder_plan_proposal_task.py` | Passed: `4 files already formatted`. |
| `cd backend && uv run lint-imports --no-cache` | Passed: 3 contracts kept, 0 broken. |
| `./scripts/gate-local/anti_slippage.sh --worktree` | Passed: `anti-slippage: worktree clean`. |
| `git diff --check -- <11.3a touched paths>` | Passed. |
| Exact grep for deleted proposal helpers and direct MCP normalization in `ai_builder_plan_proposal_task.py` | Passed with no matches. |
| Claude final verification | Passed: `green`, minimum score `9`. |

### Carry-Forward

| Item | Owner slice |
|---|---|
| Decide whether discovery-time resource prompt rendering should consume `AIBuilderResourceReferenceMaterial`. | 11.3 follow-up after proposal resource material is stable |
| Add form-field lifecycle goldens and decide whether the Pattern Registry needs an explicit form-field chain shape. | 11.3b |
| Revisit selectable assistant refs only after AI Builder has a tenant/workspace-scoped allow-list plus permission and materializer rules. | Future resource-contract slice |

## 11.3b Form-Field Lifecycle Goldens Plan

### Scope

This slice is test-only. It adds non-overlapping create/compiler goldens for
form-field lifecycle behavior and one Pattern Registry canonical-owner
invariant. If a golden exposes a source bug, the bug becomes 11.3c instead of
expanding this slice.

### Claude Plan Review Iteration 1

- Artifact: `.codex/artifacts/claude-peer-loop-batch-11-3b-form-field-lifecycle-plan-20260503T064226Z.md`
- Verdict: `changes_required`
- Green light: `no`
- Minimum score: `6`

Accepted findings:

| Finding | Resolution |
|---|---|
| Chain scenario was under-specified. | Plan now pins exact post-conditions for intermediate use, final-step non-reference, structured previous-field binding, and valid compiled spec. |
| Pattern Registry guard duplicated membership tests. | Replace the proposed guard with a single-owner invariant for `runtime_metadata_fields`. |
| 11.4 discoverability would be weak in the large create-compiler file. | Add lifecycle goldens in a dedicated `test_ai_builder_form_field_lifecycle.py`. |
| Edit-path twin was not explicitly carried forward. | 11.4 owns edit-path lifecycle twins; 11.3b remains create-path only. |
| Source-change exception could expand scope. | Any source bug found by these goldens becomes 11.3c; this slice stays test-only. |

### Planned Test Shape

| Scenario | Test owner | Key assertions |
|---|---|---|
| Declare-only input field | `test_ai_builder_form_field_lifecycle.py` | Explicitly declared field with no `uses_input_fields` attaches to the final draft step and appears exactly once in final-step bindings. |
| Intermediate chain | `test_ai_builder_form_field_lifecycle.py` | Intermediate step consumes the form field; final step references the intermediate structured field and does not contain the form-field marker. |
| Multi-reference | `test_ai_builder_form_field_lifecycle.py` | Two steps consume the same field; each binding contains the marker exactly once; the compiled form-field contract has one field. |
| Pattern Registry single owner | `test_pattern_registry.py` | `runtime_metadata_fields` belongs only to `form_field_runtime_inputs` across positive pattern required slots and question template ids. |

### Validation Plan

```bash
cd backend && uv run pytest tests/unittests/flows/ai_builder/test_ai_builder_form_field_lifecycle.py tests/unittests/flows/ai_builder/test_pattern_registry.py tests/unittests/flows/ai_builder/test_ai_builder_edit_validator.py -q
cd backend && uv run pytest tests/unittests/flows/ai_builder/test_ai_builder_create_compiler.py -q
cd backend && uv run pytest tests/unittests/flows/ai_builder -q
cd backend && uv run pyright tests/unittests/flows/ai_builder/test_ai_builder_form_field_lifecycle.py tests/unittests/flows/ai_builder/test_pattern_registry.py
cd backend && uv run ruff check tests/unittests/flows/ai_builder/test_ai_builder_form_field_lifecycle.py tests/unittests/flows/ai_builder/test_pattern_registry.py
cd backend && uv run ruff format --check tests/unittests/flows/ai_builder/test_ai_builder_form_field_lifecycle.py tests/unittests/flows/ai_builder/test_pattern_registry.py
./scripts/gate-local/anti_slippage.sh --worktree
git diff --check -- backend/tests/unittests/flows/ai_builder/test_ai_builder_form_field_lifecycle.py backend/tests/unittests/flows/ai_builder/test_pattern_registry.py docs/refactor/execution/batch-11-flow-ai-builder-reliability
```

### Claude Plan Verification Iteration 2

- Artifact: `.codex/artifacts/claude-peer-loop-batch-11-3b-form-field-lifecycle-plan-verification-20260503T064602Z.md`
- Verdict: `green`
- Green light: `yes`
- Minimum score: `8`

Accepted polish:

| Finding | Resolution |
|---|---|
| Split the single-owner invariant for clearer failures. | Added separate required-slot and question-template owner tests. |
| Keep names generic and behavior-oriented. | Lifecycle tests use neutral `priority`, `case_id`, and `audience` fields. |
| Make 11.4 discovery explicit. | The dedicated lifecycle file is the path marker for the future matrix harness. |

### Implementation Result

| Area | Outcome |
|---|---|
| Lifecycle test owner | Added `backend/tests/unittests/flows/ai_builder/test_ai_builder_form_field_lifecycle.py`. |
| Declare-only field golden | User-declared `priority` attaches to the final step and renders one binding marker. |
| Intermediate chain golden | `case_id` is consumed by the intermediate scoring step; the final step references `step_a.output.structured.risk_score` and does not re-render `case_id`. |
| Multi-reference golden | `audience` can feed two separate step bindings, once per step. |
| Pattern Registry owner invariant | `runtime_metadata_fields` now has one positive required-slot owner and one positive question-template owner: `form_field_runtime_inputs`. |
| Source scope | No source behavior changes were made. |

### Validation Result

| Command | Result |
|---|---|
| `uv run pytest tests/unittests/flows/ai_builder/test_ai_builder_form_field_lifecycle.py tests/unittests/flows/ai_builder/test_pattern_registry.py tests/unittests/flows/ai_builder/test_ai_builder_edit_validator.py -q` | Passed: `90 passed`. |
| `uv run pytest tests/unittests/flows/ai_builder/test_ai_builder_create_compiler.py -q` | Passed: `75 passed`. |
| `uv run pytest tests/unittests/flows/ai_builder -q` | Passed: `1743 passed, 4 skipped`, 12 existing warnings. |
| `uv run pyright tests/unittests/flows/ai_builder/test_ai_builder_form_field_lifecycle.py tests/unittests/flows/ai_builder/test_pattern_registry.py` | Passed: `0 errors, 0 warnings, 0 informations`. |
| `uv run ruff check tests/unittests/flows/ai_builder/test_ai_builder_form_field_lifecycle.py tests/unittests/flows/ai_builder/test_pattern_registry.py` | Passed. |
| `uv run ruff format --check tests/unittests/flows/ai_builder/test_ai_builder_form_field_lifecycle.py tests/unittests/flows/ai_builder/test_pattern_registry.py` | Passed: `2 files already formatted`. |
| `./scripts/gate-local/anti_slippage.sh --worktree` | Passed: `anti-slippage: worktree clean`. |
| `git diff --check -- <11.3b touched paths>` | Passed. |
| `docker exec -w /workspace/backend eneo-41ae93-eneo-1 uv run pytest tests/unittests/flows/ai_builder/test_ai_builder_form_field_lifecycle.py -q` | Blocked before Docker ran by tool policy: `approval required by policy, but AskForApproval is set to Never`. |

### Claude Implementation Review

- Artifact: `.codex/artifacts/claude-peer-loop-batch-11-3b-form-field-lifecycle-implementation-20260503T065235Z.md`
- Verdict: `green`
- Green light: `yes`
- Minimum score: `8`

Accepted notes:

| Finding | Resolution |
|---|---|
| Exact binding equality in the intermediate-chain test is the most formatting-sensitive assertion. | Keep it intentionally strict; a binding-shape change should update this golden deliberately. |
| Optional docstrings were not necessary. | Test names carry the invariant and no restating comments were added. |

## 11.4a Golden Coverage Matrix Harness Plan

### Scope

This slice starts the 11.4 matrix work with a test-only umbrella harness. It
does not move existing behavior fixtures into a new registry. Instead, it makes
their ownership explicit and validates that the referenced owner tests still
exist, their FCM tuple chains are legal, Pattern Registry ids resolve, create
goldens have edit twins or explicit exceptions, and form-field lifecycle rows
meet the initial coverage target.

### Claude Plan Review Iteration 1

- Artifact: `.codex/artifacts/claude-peer-loop-batch-11-4a-golden-coverage-matrix-plan-20260503T065957Z.md`
- Verdict: `changes_required`
- Green light: `no`
- Minimum score: `7`

Accepted findings:

| Finding | Resolution |
|---|---|
| Domain-neutrality scope was undefined. | Limit 11.4a neutrality to matrix metadata and new lifecycle test names; existing fixture-body cleanup is a follow-up. |
| The 30% form-field-chain denominator was not concrete. | Row unit is now a coverage owner; planned denominator is 5 owner rows with 4 form-field-chain rows. |
| Edit exceptions had no expiration policy. | Exceptions now require `reason` and `retire_when`. |
| Owner-by-reference mechanism was unspecified. | Use static AST owner resolution, not sibling test imports. |
| `concerns` would have been stringly typed. | Use `CoverageConcern` enum values. |

### Claude Plan Verification Iteration 2

- Artifact: `.codex/artifacts/claude-peer-loop-batch-11-4a-golden-coverage-matrix-plan-verification-20260503T070329Z.md`
- Verdict: `green`
- Green light: `yes`
- Minimum score: `8`

Accepted polish:

| Finding | Resolution |
|---|---|
| Percentage gates are fragile with a 5-row denominator. | Added that new non-chain/non-edit rows must backfill counterpart rows instead of lowering gates. |
| Aggregate-row semantics needed a rule beyond the bridge example. | Added that aggregate rows are allowed only when their owner test already fails on missing internal fixtures. |
| `retire_when` string could rot. | Implementation will reject short values and placeholder words. |
| Metadata neutrality should use a named token set. | Implementation will use a named municipality-only token constant. |

### Canonical Owners

| Concept | Current owner | 11.4a decision |
|---|---|---|
| Pattern Registry / FCM archetype round-trip coverage | `backend/tests/unittests/flows/ai_builder/test_ai_builder_materialization_bridge.py` | Reuse as `registry_bridge` row owner; do not duplicate `_ARCHETYPE_CASES`. |
| Form-field lifecycle behavior | `backend/tests/unittests/flows/ai_builder/test_ai_builder_form_field_lifecycle.py` | Extend with one edit-path multi-reference twin and reference its create/edit tests from the matrix. |
| Edit compiler form-field bindings | `backend/tests/unittests/flows/ai_builder/test_ai_builder_edit_compiler.py` and lifecycle file | Keep existing edit compiler tests; add only the missing multi-reference lifecycle twin. |
| Golden coverage metadata | New `test_ai_builder_golden_coverage_matrix.py` | Owns metadata rows and gates, not behavior fixtures. |

### Planned Matrix Rows

| Row | Owner test | Surface | Edit parity |
|---|---|---|---|
| `create_form_field_declare_only` | `test_declared_input_field_without_step_use_attaches_to_final_step` | create | Exception with retire trigger: remove when edit-mode field inference lands. |
| `create_form_field_intermediate_chain` | `test_intermediate_form_field_use_flows_through_structured_previous_field` | create | Exception with retire trigger: remove when edit mode can materialize create-time intermediate chains. |
| `create_form_field_multi_reference` | `test_one_input_field_can_feed_two_step_bindings_once_each` | create | Twin: `edit_form_field_multi_reference`. |
| `edit_form_field_multi_reference` | new edit lifecycle test | edit | Edit twin row. |
| `pattern_registry_materialization_bridge` | `TestArchetypeCoverage.test_every_positive_pattern_has_a_fixture` | registry_bridge | Not a create row. |

Initial denominator:

- 5 owner rows total.
- 4 rows carry `CoverageConcern.FORM_FIELD_CHAIN`, so the initial
  form-field-chain ratio is 80%.
- 1 row has `surface=edit`, so the initial edit-row ratio is 20%.
- Adding a non-chain or non-edit row must backfill a counterpart row in the
  same slice; do not lower the percentage gates to absorb denominator growth.

### Planned Gates

| Gate | Acceptance |
|---|---|
| Owner existence | Resolve each `owner_module` with `find_spec`, parse its source with AST, and assert `test_name` exists without importing sibling test modules. |
| Pattern ids | Every listed pattern exists in `PATTERN_REGISTRY`. |
| FCM legality | Every typed step tuple resolves and each row chain passes `validate_step_chain`. |
| Edit parity | Every create row has an edit twin or an exception with `reason` and `retire_when`; at least 20% of rows are edit rows. |
| Form-field coverage | At least 30% of owner rows include `CoverageConcern.FORM_FIELD_CHAIN`; planned start is 4/5 rows. |
| Metadata neutrality | Matrix metadata and new lifecycle test names avoid domain-specific Swedish municipal/legal/procurement vocabulary; existing fixture bodies are out of 11.4a scope. |

### Validation Plan

```bash
cd backend && uv run pytest tests/unittests/flows/ai_builder/test_ai_builder_golden_coverage_matrix.py tests/unittests/flows/ai_builder/test_ai_builder_form_field_lifecycle.py tests/unittests/flows/ai_builder/test_ai_builder_materialization_bridge.py -q
cd backend && uv run pytest tests/unittests/flows/ai_builder -q
cd backend && uv run pyright tests/unittests/flows/ai_builder/test_ai_builder_golden_coverage_matrix.py tests/unittests/flows/ai_builder/test_ai_builder_form_field_lifecycle.py
cd backend && uv run ruff check tests/unittests/flows/ai_builder/test_ai_builder_golden_coverage_matrix.py tests/unittests/flows/ai_builder/test_ai_builder_form_field_lifecycle.py
cd backend && uv run ruff format --check tests/unittests/flows/ai_builder/test_ai_builder_golden_coverage_matrix.py tests/unittests/flows/ai_builder/test_ai_builder_form_field_lifecycle.py
./scripts/gate-local/anti_slippage.sh --worktree
git diff --check -- backend/tests/unittests/flows/ai_builder/test_ai_builder_golden_coverage_matrix.py backend/tests/unittests/flows/ai_builder/test_ai_builder_form_field_lifecycle.py docs/refactor/execution/batch-11-flow-ai-builder-reliability
```

### Implementation Result

| Area | Outcome |
|---|---|
| Matrix owner | Added `backend/tests/unittests/flows/ai_builder/test_ai_builder_golden_coverage_matrix.py`. |
| Coverage row typing | Added enum-typed `CoverageSurface` / `CoverageConcern` and frozen row value objects. |
| Owner existence | Matrix uses `find_spec` plus AST checks for module-level tests and class-method tests. |
| FCM legality | Matrix rows use enum-typed step tuples and validate both tuple support and chain legality. |
| Edit parity | Create rows require an edit twin or retiring exception; starting denominator is 5 rows with 1 edit row. |
| Form-field ratio | 4 of 5 rows carry `FORM_FIELD_CHAIN`, above the 30% gate. |
| Edit lifecycle twin | Added `test_edit_form_field_multi_reference_feeds_two_step_bindings_once_each`. |
| Metadata neutrality | Added named municipality-only token guard over matrix metadata. |
| Source scope | No `backend/src` files changed. |

### Validation Result

| Command | Result |
|---|---|
| `uv run pytest tests/unittests/flows/ai_builder/test_ai_builder_golden_coverage_matrix.py tests/unittests/flows/ai_builder/test_ai_builder_form_field_lifecycle.py tests/unittests/flows/ai_builder/test_ai_builder_materialization_bridge.py -q` | Passed: `46 passed`. |
| `uv run pytest tests/unittests/flows/ai_builder -q` | Passed: `1751 passed, 4 skipped`, 12 existing warnings. |
| `uv run pyright tests/unittests/flows/ai_builder/test_ai_builder_golden_coverage_matrix.py tests/unittests/flows/ai_builder/test_ai_builder_form_field_lifecycle.py` | Passed: `0 errors, 0 warnings, 0 informations`. |
| `uv run ruff check tests/unittests/flows/ai_builder/test_ai_builder_golden_coverage_matrix.py tests/unittests/flows/ai_builder/test_ai_builder_form_field_lifecycle.py` | Passed. |
| `uv run ruff format --check tests/unittests/flows/ai_builder/test_ai_builder_golden_coverage_matrix.py tests/unittests/flows/ai_builder/test_ai_builder_form_field_lifecycle.py` | Passed: `2 files already formatted`. |

### Claude Implementation Review

- Artifact: `.codex/artifacts/claude-peer-loop-batch-11-4a-golden-coverage-matrix-implementation-20260503T071148Z.md`
- Verdict: `green`
- Green light: `yes`
- Minimum score: `8`

Accepted polish:

| Finding | Resolution |
|---|---|
| AST owner lookup should support async tests. | Added `ast.AsyncFunctionDef` support for module-level and class-method owner tests. |
| Edit twin/exception XOR was hard to read. | Added named booleans and an assertion message. |
| Percentage gates used naked numeric thresholds. | Added named `MIN_EDIT_ROW_PERCENTAGE` and `MIN_FORM_FIELD_CHAIN_PERCENTAGE` constants. |
| Edit twins could drift to unrelated concerns. | Added a twin concern superset assertion. |

## 11.5a Planner Provider Capability Rail

### Scope

This slice starts the structured-output rail at the provider-capability and
planner JSON boundary. It does not touch `outline_flow` / `edit_flow` tool-call
contracts, semantic repair, or proposal architecture behavior.

Canonical owners:

| Concept | Owner | Decision |
|---|---|---|
| Provider structured-output capability | `backend/src/intric/completion_models/infrastructure/tenant_model_capabilities.py` | New typed owner for strict schema, JSON object, and prompt-validation decisions. |
| Tenant model capability resolution | `TenantModelAdapter` and `CompletionService` | Adapter delegates to the capability owner; service exposes the typed async method to AI Builder. |
| Planner request response format | `backend/src/intric/flows/ai_builder/ai_builder_response_format.py` | Converts one capability decision into one planner request selection. |
| Planner call kwargs and telemetry | `backend/src/intric/flows/ai_builder/ai_builder_planner.py` | Main and chained planner turns reuse the same selection and emit compact structured-output telemetry. |
| Message-context prefetch | `backend/src/intric/flows/ai_builder/ai_builder_service.py` | Computes the capability decision once before SSE streaming. |

### Claude Plan Review

| Iteration | Artifact | Verdict | Green light | Minimum score | Outcome |
|---:|---|---|---|---:|---|
| 1 | `.codex/artifacts/claude-peer-loop-batch-11-5-structured-output-rail-plan-20260503T072546Z.md` | `changes_required` | `no` | 6 | Strict `PlannerOutput` schema feasibility, capability override scope, chained planner kwargs, and telemetry keys needed tightening. |
| 2 | `.codex/artifacts/claude-peer-loop-batch-11-5-structured-output-rail-revised-plan-20260503T073127Z.md` | `green` | `yes` | 8 | Approved the 11.5a planner-only slice after local strict-schema and LiteLLM support probes. |

Accepted plan constraints:

| Finding | Resolution |
|---|---|
| `PlannerOutput` is not strict-schema ready. | 11.5a downgrades strict-capable providers to `json_object` for planner turns and logs `planner_output_strict_blocked=true`. |
| Capability ownership should not fork between AI Builder and adapters. | Added one completion-model capability owner and delegated through `TenantModelAdapter` / `CompletionService`. |
| Explicit model overrides were too speculative. | No override surface was added; LiteLLM metadata is the capability evidence for this slice. |
| Proposal tool calls are orthogonal. | `outline_flow` / `edit_flow` prompts do not receive planner `response_format` kwargs in 11.5a. |
| Chained server actions must not rebuild capability state. | `send_message` builds one selection and passes it to both primary and chained planner paths. |

### Implementation Result

| Area | Outcome |
|---|---|
| Capability contract | Added `StructuredOutputCapabilityDecision`, `StructuredOutputMode`, `StructuredOutputDecisionSource`, and `unsupported_structured_output_decision`. |
| Adapter/service handoff | `TenantModelAdapter.resolve_structured_output_capability()` and `CompletionService.resolve_structured_output_capability()` now expose typed provider capability. |
| Planner response-format selection | Added `PlannerResponseFormatSelection` and blocker detection against the live `PlannerOutput.model_json_schema()`. |
| Strict downgrade | Strict-capable providers use `json_object` while `PlannerOutput` has union/default/optional-object blockers. |
| Planner kwargs | Main and chained planner calls share `_build_planner_litellm_kwargs(...)` and keep `drop_params=True` as a real LiteLLM kwarg. |
| Telemetry | Planner metrics now emit seven structured-output keys and no old JSON-mode compatibility keys. |
| Proposal separation | Proposal tool-call prompts are pinned to avoid planner `response_format` kwargs. |
| Tests | Added provider-capability, response-format, service-context, planner, chained-dispatch, parse-repair, proposal, and router coverage. |

### Claude Implementation Review

| Iteration | Artifact | Verdict | Green light | Minimum score | Outcome |
|---:|---|---|---|---:|---|
| 3 | `.codex/artifacts/claude-peer-loop-batch-11-5a-structured-output-implementation-20260503T075748Z.md` | `GREEN_LIGHT` | `yes` | 7.5 | Approved ship-with-follow-ups; flagged a typed-dependency `getattr` hedge, redundant telemetry keys, and missing same-selection chain assertion. |
| 4 | `.codex/artifacts/claude-peer-loop-batch-11-5a-structured-output-implementation-follow-up-20260503T080716Z.md` | `green` | `yes` | 8 | Verified the cleanup and cleared the slice for documentation and commit. |

Accepted implementation findings:

| Finding | Resolution |
|---|---|
| `resolve_planner_structured_output_capability` hedged a typed dependency with `getattr` / `isawaitable`. | Replaced it with a direct typed async call to `CompletionService.resolve_structured_output_capability`. |
| Planner telemetry carried old JSON-mode keys. | Removed `response_format_requested`, `drop_params`, and `json_mode_requested` from metrics; `drop_params=True` remains only as a LiteLLM kwarg. |
| No test proved the same selection reached chained dispatch. | Added `test_send_message_reuses_one_planner_response_format_selection_for_chain` with identity assertion. |

### Validation Result

| Command | Result |
|---|---|
| `uv run pytest tests/unit/test_tenant_model_capabilities.py tests/unit/test_tenant_model_adapter_prepare_kwargs.py tests/unittests/flows/ai_builder/test_ai_builder_response_format.py tests/unittests/flows/ai_builder/test_ai_builder_service.py::TestPlannerContextPreparation tests/unittests/flows/ai_builder/test_ai_builder_planner_send_message.py tests/unittests/flows/ai_builder/test_ai_builder_parse_repair.py tests/unittests/flows/ai_builder/test_ai_builder_proposal_processor.py tests/unittests/flows/ai_builder/test_ai_builder_router.py -q` | Passed: `164 passed`. |
| `uv run pytest tests/unittests/flows/ai_builder -q` | Passed: `1761 passed, 4 skipped`, 12 existing warnings. |
| `uv run pytest tests/integration/flows/ai_builder -q` | Passed: `93 passed, 20 deselected`, 16 existing warnings. |
| `uv run pyright <11.5a touched source and test files>` | Passed: `0 errors, 0 warnings, 0 informations`. |
| `uv run ruff check <11.5a touched source and test files>` | Passed. |
| `uv run ruff format --check <11.5a touched source and test files>` | Passed: `15 files already formatted`. |
| `uv run lint-imports --no-cache` | Passed: 3 import contracts kept, 0 broken. |
| `./scripts/gate-local/anti_slippage.sh --worktree` | Passed: `anti-slippage: worktree clean`. |

### Carry-Forward

| Item | Owner |
|---|---|
| Make `PlannerOutput` strict-schema compatible or document why strict schema is not maintainable. | 11.5b |
| Extend the typed rail to `outline_flow`, `edit_flow`, and parse repair only where the contract is a typed JSON object. | 11.5b |
| Run a live provider smoke for the actual tenant/model Anthropic Haiku alias instead of assuming LiteLLM metadata from memory. | 11.5b / provider eval |
| Consider removing the pre-existing `resolve_planner_params` introspection hedge in a separate planner cleanup slice. | Later Batch 11 cleanup |

## 11.6b Source-Material Boundary Canonicalization Follow-up

### Trigger

The user reran the Swedish audio-to-DOCX prompt and supplied the resulting debug
export. The run transcribed the audio correctly, but the final DOCX still said
there was no substantive meeting/transcript material because downstream JSON
steps consumed only immediate metadata JSON. The screenshots also showed that
the visible `Underlag till text` surface did not make the source-material mapping
obvious enough to trust prompt wording as the fix.

### Claude Gate

| Iteration | Artifact | Verdict | Green light | Minimum score | Outcome |
|---:|---|---|---|---:|---|
| 1 | `.codex/artifacts/claude-peer-loop-ai-builder-source-material-runtime-fields-plan-20260503T133745Z.md` | `changes_required` | `no` | n/a | Rejected the skeleton-only/source-wording path and required a canonical source-material boundary owner outside the retry loop. |
| 2 | `.codex/artifacts/claude-peer-loop-ai-builder-source-material-runtime-fields-verification-20260503T135932Z.md` | `green` | `yes` | 7 | Verified the deterministic create-draft + compiled-spec normalization shape. |

Post-green refinements applied from Claude's non-blocking notes:

| Finding | Resolution |
|---|---|
| Draft and compiled source pickers could diverge. | Both now prefer the primary flow-input source-material text step before falling back to the first prior text step. |
| Swedish label token `text` was too broad. | Removed it and added an English-label regression. |
| Manual API scoring duplicated source-material and primary-input predicates. | Scoring now imports the production source-material and primary-input owners. |
| Idempotency/order coverage was thin. | Added topology normalizer tests for idempotency, existing-question tail preservation, primary audio source preference, and English labels. |

### Implementation Result

| Area | Outcome |
|---|---|
| Source-material owner | Added `ai_builder_source_material.py` for source-material boundary detection, question construction, source labels, and create-draft enrichment. |
| Create draft | `normalize_create_draft_mechanics` now calls the source-material owner; `compile_create_draft` normalizes as a direct-caller guard. |
| Compiled spec | `normalize_ai_builder_step_topology` completes missing source-material underlag by setting `input_type=text` and a deterministic `question` binding. |
| Skeleton cleanup | Removed the earlier skeleton-local source-material enrichment so there is one owner instead of an audio-only path. |
| Validation | Added `source_material_boundary_missing_underlag` as a defensive quality warning; it is not in the retry warning set. |
| Runtime fields | Added transcript/transcription aliases as audio primary-input shadows. |
| Scoring | Manual API scoring uses the production source-material and primary-input predicates. |

### Validation Result

Docker validation was attempted first with `docker ps --format '{{.Names}}'`, but
the current tool environment rejected Docker process creation as approval-gated
while approval is disabled. Local validation was used as the fallback.

| Command | Result |
|---|---|
| `cd backend && uv run ruff check <11.6b touched source and test files>` | Passed. |
| `cd backend && uv run pyright <11.6b touched source and test files>` | Passed: `0 errors, 0 warnings, 0 informations`. |
| `cd backend && uv run pytest tests/unittests/flows/ai_builder/test_ai_builder_create_dataflow.py tests/unittests/flows/ai_builder/test_ai_builder_create_compiler.py tests/unittests/flows/ai_builder/test_ai_builder_step_transition_policy.py tests/unittests/flows/ai_builder/test_ai_builder_validator.py tests/unittests/flows/ai_builder/test_ai_builder_primary_input_fields.py tests/unittests/flows/ai_builder/test_ai_builder_form_field_lifecycle.py tests/unittests/flows/ai_builder/test_ai_builder_runtime_input_fields.py tests/integration/flows/ai_builder/benchmark/test_manual_api_scoring.py -q` | Passed: `211 passed`, existing warnings only. |
| `cd backend && uv run pytest tests/unittests/flows/ai_builder/test_ai_builder_step_skeleton.py tests/unittests/flows/ai_builder/test_ai_builder_proposal_processor.py::test_outline_audio_to_docx_returns_plan_without_self_correction tests/unittests/flows/ai_builder/test_ai_builder_materialization_bridge.py -q` | Passed: `63 passed`, existing warning only. |
| `cd backend && uv run pytest tests/integration/flows/ai_builder/benchmark -q` | Passed: `107 passed`, existing warnings only. |

### Carry-Forward

| Item | Owner |
|---|---|
| Re-run Docker validation in an environment where Docker commands are not approval-blocked. | Next implementation operator |
| Promote any additional live debug-export failure into the source-material boundary tests before changing prompt wording. | Batch 11 reliability |

## 11.6c Edit Confirmation, Source-Material Status, And Published-Flow Apply UX

### Trigger

The user supplied a live debug export and screenshots from an edited Swedish
audio-to-DOCX flow. The flow transcribed the audio but generated a DOCX that
claimed no substantive transcription was available, while downstream steps had
visible variable chips that were not reliably mapped into `Underlag till text`.
The user also reported that existing-flow edits could stall after clicking
`Gå vidare till planen`, that the requirements summary card was too shallow,
and that published flows failed to apply edits without a clear unpublish path.

### Claude Gate

| Iteration | Artifact | Verdict | Green light | Minimum score | Outcome |
|---:|---|---|---|---:|---|
| 1 | `.codex/artifacts/claude-peer-loop-ai-builder-edit-confirmation-source-material-and-requirements-summary-plan-20260503T142948Z.md` | `changes_required` | `no` | n/a | Required stronger ownership around source-material binding status, edit confirmation, and published-flow UX before implementation. |
| 2 | `.codex/artifacts/claude-peer-loop-ai-builder-edit-confirmation-source-material-published-apply-ux-and-requirements-summary-verification-20260503T150947Z.md` | `changes_required` | `no` | n/a | Accepted the broad direction but required confirmation before unpublish, frontend-owned latest-request display, bounded legacy bridge, and one binding-status accessor. |
| 3 | `.codex/artifacts/claude-peer-loop-ai-builder-edit-confirmation-source-material-published-apply-ux-and-requirements-summary-verification-20260503T152556Z.md` | `green` | `yes` | 8 | Verified fixes and left only low-severity follow-ups: design-system dialog polish, Python i18n debt, and live DOCX smoke testing. |

### Implementation Result

| Area | Outcome |
|---|---|
| Source-material status | `backend/src/intric/flows/ai_builder/ai_builder_source_material.py:58-151` now exposes `SourceMaterialBindingStatus` so callers distinguish complete, intentionally partial, and missing underlag. |
| Normalizer and lint callers | `ai_builder_step_transition_policy.py:182-183`, `ai_builder_validation_quality.py:292-293`, and `manual_api_scoring.py:133` use the same status instead of duplicate boolean predicates. |
| Existing prompt order | `ai_builder_source_material.py:151-194` keeps the existing user prompt first and appends missing structured/source references after it. |
| Requirements versioning | `ai_builder_planner.py:1331-1341` persists `requirements_version`; `ai_builder_requirements_state.py:101-106` bridges version-less pre-2026-05-03 draft confirmations with a documented deletion trigger. |
| Requirements card | `FlowAIBuilderRequirementsSummary.svelte:82-88` shows the latest real user request; `FlowAIBuilderChat.svelte:49-56` derives that request from client-owned conversation state. |
| Height warning | `FlowAIBuilderRequirementsSummary.svelte` no longer uses the collapsible height animation that produced `Invalid keyframe value for property height: NaNpx`. |
| Published-flow edit UX | `FlowAIBuilderPlanPane.svelte:137-140` requires explicit confirmation before `unpublishAndApplyPlan`; `FlowAIBuilderDriver.ts:555-590` unpublishes, applies, and records `flow_unpublished_apply_failed` if apply fails after unpublish succeeds. |
| Route verification | Backend authoring route is `POST /api/v1/flows/{id}/unpublish/` from `backend/src/intric/flows/api/flow_authoring_router.py:563-598`, matching the frontend call. |

### Validation Result

| Command | Result |
|---|---|
| `cd backend && uv run pytest tests/unittests/flows/ai_builder -q` | Passed: `1823 passed, 4 skipped`, existing warnings only. |
| `cd backend && uv run pytest tests/integration/flows/ai_builder -q` | Passed: `111 passed, 20 deselected`, existing warnings only. |
| `cd backend && uv run pyright <11.6c touched source and test files>` | Passed: `0 errors, 0 warnings, 0 informations`. |
| `cd backend && uv run ruff check <11.6c touched source and test files>` | Passed. |
| `cd frontend/apps/web && bun test src/lib/features/flows/ai-builder/FlowAIBuilderDriver.test.ts` | Passed: `32 pass`. |
| `cd frontend/apps/web && bun run i18n:compile` | Passed. |
| `cd frontend/apps/web && bunx prettier --check <11.6c touched frontend files>` | Passed. |
| `cd frontend/apps/web && bunx svelte-check --tsconfig ./tsconfig.json` | Failed on pre-existing generated-client, Spaces, chat, dashboard, and FlowsTable typing errors; no `FlowAIBuilderDriver.ts` errors remained. |
| `git diff --check` | Passed. |

### Carry-Forward

| Item | Owner |
|---|---|
| Replace the browser-native confirmation with the design-system `AlertDialog` when the next UX polish slice touches published-flow destructive actions. | Frontend polish |
| Move backend-rendered Swedish/English requirement-summary labels out of Python if a third locale or cataloged server-rendered message format lands. | AI Builder i18n follow-up |
| Run a live DOCX-output smoke test for the new "user prompt first, data appended" source-material ordering in an environment with the full app and provider credentials. | Manual eval |
| Re-run Docker validation in an environment where Docker commands are not approval-blocked. | Next implementation operator |
