# Agent Review: Runtime Dataflow, Underlag, RAG, And Validation

## TL;DR

Runtime/dataflow risk is not only Builder-specific; several Builder outputs are validated more deeply than directly authored flows.
The highest risk remains RAG/knowledge retrieval using the full resolved `step_input.text` underlag as the semantic query.
Shared create/update/publish validation is shallower than Builder validation around template paths, `step_input`, arrays, and contractless JSON refs.
Rerun without explicit `step_inputs` is less severe than it first appears because normal reruns inherit predecessor files, but edge cases still need tests.
These findings should feed Fable's runtime/dataflow contract session and the implementation backlog.

## Ranked Findings

| Rank | Finding | Evidence | Proposed owner / fix |
|---:|---|---|---|
| 1 | RAG query is the full resolved underlag, so large source material, previous outputs, and runtime uploads can become the embedding query. | `backend/src/eneo/flows/runtime/step_execution_runtime.py:953`, `backend/src/eneo/flows/runtime/rag_retrieval.py:66`, `backend/src/eneo/assistants/references.py:165` | Runtime/RAG boundary should derive one bounded semantic retrieval query with provenance. The LLM can still receive full underlag. |
| 2 | Shared publish/manual validation is not runtime-equivalent; direct/UI authored flows can pass weaker checks than Builder. | `backend/src/eneo/flows/application/flow_service.py:113`, `backend/src/eneo/flows/application/flow_service.py:237`, `backend/src/eneo/flows/application/flow_service.py:432`, `backend/src/eneo/flows/flow_validators.py:735`, `backend/src/eneo/flows/ai_builder/ai_builder_validation_references.py:45` | `flow_validators.py` should become the lifecycle gate for runtime path grammar, with Builder reusing/preflighting the same checks. |
| 3 | Structured array paths are lenient in Builder validation but strict at runtime. | `backend/src/eneo/flows/ai_builder/ai_builder_json_schema_paths.py:13`, `backend/src/eneo/flows/variable_resolver.py:146`, `backend/tests/unittests/flows/ai_builder/test_ai_builder_validator.py:731` | Runtime path grammar should win. Delete/flip lenient array traversal and require explicit numeric indexes. |
| 4 | Contractless JSON structured-field refs are accepted. | `backend/src/eneo/flows/ai_builder/ai_builder_validation_references.py:142`, `backend/src/eneo/flows/ai_builder/ai_builder_new_step_compiler.py:391`, `backend/src/eneo/flows/runtime/output_formats/json.py:19` | Field-level structured refs should require a declared output contract; whole-object refs can remain a deliberate separate case. |
| 5 | `step_input` metadata contract drifts between runtime producer and static analyzer. | `backend/src/eneo/flows/runtime/step_input_resolution.py:329`, `backend/src/eneo/flows/flow_variable_definitions.py:82`, `backend/src/eneo/flows/template_reference_analyzer.py:207` | Make `step_input_resolution.py` or a nearby typed contract the producer-owned source of truth; derive analyzer shapes from it. |
| 6 | Source-material completion treats structured-subfield-only underlag as intentional partial. | `backend/src/eneo/flows/ai_builder/ai_builder_source_material.py:117`, `backend/src/eneo/flows/ai_builder/ai_builder_step_transition_policy.py:251`, `backend/src/eneo/flows/ai_builder/ai_builder_validation_quality.py:339` | Split "has original source text" from "has some structured subfield"; warn or complete source grounding for final artifact/report boundaries. |
| 7 | Bare text flow input can compile to `{{ indata_text }}`, but runtime only exposes `indata_text` for non-empty stripped text. | `backend/src/eneo/flows/ai_builder/ai_builder_new_step_compiler.py:426`, `backend/src/eneo/flows/variable_resolver.py:59`, `backend/src/eneo/flows/flow_run_input_payload.py:26` | Choose one clear contract: omit explicit binding for bare text flow input or reject empty primary text at run start with a clear API error. |
| 8 | Whole-plan edits can leave stale literal `step_N` aliases when existing steps are deleted. | `backend/src/eneo/flows/ai_builder/ai_builder_edit_compiler.py:748`, `backend/src/eneo/flows/ai_builder/ai_builder_edit_compiler.py:823`, `backend/tests/unittests/flows/ai_builder/test_ai_builder_edit_proposal.py:330` | Block or explicitly repair aliases to deleted existing steps; do not silently leave original aliases. |
| 9 | Rerun omitted `step_inputs` normally inherit predecessor files, so this is not the same P1 as missing first-run files. | `backend/src/eneo/flows/application/flow_run_rerun_service.py:317`, `backend/src/eneo/flows/runtime/executor.py:1115`, `backend/src/eneo/flows/infrastructure/flow_run_repo.py:940` | Add characterization tests for normal inheritance and corrupt/no-predecessor required-input behavior before changing this path. |

## Canonical Ownership Suggestions

| Concept | Suggested canonical home |
|---|---|
| Runtime variable/path grammar | Runtime resolver path grammar, enforced by shared `flow_validators.py` lifecycle gate. |
| `input_bindings.question` validation | Shared lifecycle validation, with Builder as a preflight caller. |
| `step_input` public metadata keys | Runtime-owned typed metadata contract, not hand-maintained static drift. |
| RAG retrieval query | Runtime/RAG boundary that derives a bounded semantic query. |
| Source-material completion | `ai_builder_source_material.py`, but with "source text present" explicit. |
| JSON structured refs | Shared validator requiring output contracts for field-level refs. |

## Delete / Merge Candidates

| Candidate | Reason |
|---|---|
| False lenient-array-path docstring in `ai_builder_json_schema_paths.py` | It contradicts runtime resolver behavior. |
| Lenient array traversal in Builder validation | It accepts paths runtime rejects. |
| Independent `STEP_INPUT_KEY_SHAPES` map | It drifted from runtime metadata. |
| Direct RAG call using full `prepared.step_input.text` | It overloads underlag as retrieval query. |
| Subfield-only `INTENTIONAL_PARTIAL` shortcut | It can hide missing source grounding. |
| Edit alias fallback for deleted `step_N` references | It can silently retarget dataflow. |

## Fable Follow-Up Questions

- Should runtime path grammar become the single shared authoring/publish validation contract?
- Should RAG retrieval get an explicit query contract compiled by Builder/runtime rather than using full underlag?
- Should source-material grounding be a first-class dataflow invariant for document/PDF/DOCX final outputs?
- Which findings belong in tomorrow's first implementation slice versus a later runtime hardening pass?
