# Batch 11 — Flow AI Builder Reliability Journal

## Status

11.1a IMPLEMENTATION COMPLETE

## Starting Point

- Branch: `feature/refactor-flows-flowai`
- HEAD at Batch 11 implementation start: `832f4c1b flows: close branding namespace docs`
- Previous completed source slice: Batch 10 Slice 10.6 branding namespace documentation closure
- Staged files at start: none
- Known unrelated dirty files:
  - `scripts/run_codex_review.sh`
  - `PRODUCT.md`
  - `docs/refactor/goals.md`
- Source implementation in this pass: 11.0a reliability corpus and integrity test

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

### Carry-Forward To 11.1b

| Item | Reason |
|---|---|
| Make `compile_outline_to_create_draft` consume `materialize_step_skeleton`. | 11.1a intentionally introduces the typed owner without changing proposal behavior. |
| Delete or move `_derive_step_output_type`, `_derive_step_input_source`, `_derive_step_input_type`, `_requires_server_owned_fan_in`, `_ensure_required_server_owned_fan_in`, `_document_delivery_mode_for_step`, and `_ensure_final_artifact_step`. | These helpers still own mechanics in the old compiler path and should collapse into the skeleton owner in 11.1b. |
| Delete equivalence tests once compiler consumes the skeleton directly. | They are transition guards between independent old/new derivations; after integration they become same-source assertions. |
| Watch `ai_builder_step_skeleton.py` size during integration. | The file is responsibility-coherent but large; if 11.1b moves more helper logic into it, split defaults/helpers by ownership tier rather than letting the module grow unbounded. |
