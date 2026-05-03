# Batch 11.5b Retrospective - Proposal Boundary And Document Artifact Body

## TL;DR

1. Slice 11.5b hardens proposal tool-call kwargs and fixes the DOCX/PDF metadata-only body failure.
2. The canonical fix lives in proposal completion and StepSkeleton/input-binding mechanics, not in repair.
3. Final multi-phase DOCX/PDF body synthesis now stays as text and reads all prior semantic work.
4. JSON-to-text boundaries now get explicit underlag bindings when the previous structured object would otherwise be lost.
5. Targeted unit, lint, type, Claude, and live local API smoke validation passed; Docker validation was blocked by the current tool policy.

## Result

| Area | Outcome |
|---|---|
| Proposal seam | `AIBuilderProposalProcessor.call_proposal_completion` is the single proposal LiteLLM boundary and strips planner-only `response_format` before tool calls. |
| Naming | Repair-oriented proposal completion naming was removed instead of kept as a compatibility alias. |
| Artifact body planning | Final multi-phase DOCX/PDF semantic writer steps are forced to text and no longer emit metadata-only JSON before artifact rendering. |
| Body fan-in | Final semantic body synthesis reads `all_previous_steps` for multi-phase DOCX/PDF flows so transcripts, extraction, and structure remain available. |
| Drift evidence | Dropped proposal output fields are recorded in `StepSkeletonOutputTypeDrift.dropped_output_fields`. |
| Underlag bridge | JSON-to-text transitions bind `{{ previous.output.structured }}` unless selected field bindings intentionally narrow the material. |
| Manual evaluation | The runbook now documents local API key/curl setup, local audio fixture usage, evidence endpoints, and runtime input/form-field/underlag semantics. |

## Acceptance

| Criterion | Status | Evidence |
|---|---|---|
| Proposal tool calls do not receive planner `response_format`. | pass | Proposal processor tests cover central seam stripping and proposal paths. |
| Safe provider kwargs still pass through proposal calls. | pass | Test coverage keeps provider kwargs while removing planner-only kwargs. |
| Terminal DOCX/DOCX-like flow does not consume metadata-only JSON. | pass | Create compiler tests pin final semantic body text plus terminal DOCX output. |
| PDF artifact body planning uses the same safe pattern. | pass | PDF regression pins final semantic body text before terminal PDF output. |
| Longer document chains preserve all prior work. | pass | Four-phase DOCX regression pins `InputSource.ALL_PREVIOUS_STEPS`. |
| JSON-to-text underlag is explicit where needed. | pass | New compiler tests cover previous structured object binding and selected-field narrowing. |
| Repair is not the happy path. | pass | The fix is in compile/skeleton planning; no repair fallback is required for these cases. |
| Live generated flow shape is correct. | pass | Applied graph had step 5 `all_previous_steps` text and step 6 previous text to DOCX. |

## Validation

| Command | Result |
|---|---|
| `uv run pytest tests/unittests/flows/ai_builder/test_ai_builder_step_skeleton.py tests/unittests/flows/ai_builder/test_ai_builder_create_compiler.py tests/unittests/flows/ai_builder/test_ai_builder_proposal_processor.py tests/unittests/flows/ai_builder/test_ai_builder_proposal_repair.py tests/unittests/flows/ai_builder/test_ai_builder_parse_repair.py tests/unittests/flows/ai_builder/test_ai_builder_response_format.py -q` | Passed: `187 passed`, 1 existing warning. |
| `uv run ruff check <11.5b touched source and test files>` | Passed. |
| `uv run ruff format --check <11.5b touched source and test files>` | Passed. |
| `uv run pyright <11.5b touched source and test files>` | Passed: `0 errors, 0 warnings, 0 informations`. |
| Live local API smoke against `http://localhost:8123` | Passed: plan/apply/run/evidence/artifact path completed. |
| Docker validation | Not run: tool policy rejected `docker exec` as approval-required while approval mode is `never`. |

## Live Smoke

| Item | Value |
|---|---|
| Session | `13cfd0e1-6aad-475f-b6ec-8efd30d0c516`. |
| Plan | `ae3f289c-6c3a-46c9-b52a-8a4a02446706`. |
| Flow | `6d31e3f5-a004-4432-9424-c69b285dbd44`. |
| Run | `78f4599b-dae8-4c0d-9c43-a012e2cac338`. |
| Artifact | `step_6_output.docx`, file id `33f34175-acda-4b37-becc-ca0fb3f697c1`. |
| Evidence endpoints | `/steps/`, `/evidence/`, `/evidence/export`, and signed artifact URL returned successfully. |

Raw responses, transcript, and artifact content stayed outside git. The local
audio fixture `utvecklingssamtal.mp3` remains untracked.

## Follow-Ups

| Item | Owner |
|---|---|
| Reduce unnecessary clarification questions when the prompt already states the primary input and terminal output. | Later Batch 11 conversation-quality slice. |
| Promote any repeated manual smoke quality failure into the reliability corpus or golden matrix. | Next matching Batch 11 slice. |
| Consider extracting a shared chain-analysis value object only if another artifact-output pattern needs the same fan-in rule. | StepSkeleton cleanup, only when justified. |
| Build the manual eval harness so the six Swedish prompts produce durable redacted scorecards. | Manual eval harness slice. |

## Risk

| Risk | Mitigation |
|---|---|
| `all_previous_steps` could include more context than a small model can use cleanly in very long flows. | Gate is limited to final multi-phase DOCX/PDF body synthesis; live smoke and tests pin the intended artifact pattern. |
| A future proposal could request useful JSON fields on a final body step. | Dropped fields are recorded as drift; terminal artifact rendering still gets body text. |
| Conversation quality remains uneven for vague Swedish prompts. | Documented as a separate follow-up; not hidden by this artifact-body fix. |
| Docker behavior could differ from local `uv` validation. | Docker validation gap is explicit because the tool rejected `docker exec`; local backend smoke exercised the API/runtime path. |

Confidence: high.
