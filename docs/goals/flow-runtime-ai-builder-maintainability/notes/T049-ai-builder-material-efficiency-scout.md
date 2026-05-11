# T049 AI Builder Material Efficiency Scout

## TL;DR

Do not activate T010 as an implementation Worker right now.
The named source-material routing risk already has a canonical owner, compile-path normalization, scoring coverage, and material-cost metrics.
The expected T010 tests are already present: source text plus structured fields, JSON-only negative coverage, and material metrics for bytes, fan-in, structured fields, whole-output refs, source duplication, and `all_previous_steps`.
The next maintainability work should move back to proof-backed cleanup rather than add another material-routing path.
If this area changes later, deepen `ai_builder_source_material.py`; do not add a parallel material planner or speculative versioned names.

## Evidence

| Question | Evidence | Finding |
|---|---|---|
| Canonical source-material owner | `backend/src/intric/flows/ai_builder/ai_builder_source_material.py:68`, `:98`, `:130`, `:158` | One module owns create-draft source-material normalization, compiled boundary detection, binding status, and question construction. |
| Create compiler path uses the owner | `backend/src/intric/flows/ai_builder/ai_builder_create_dataflow.py:77`, `:131`, `:134`; `backend/src/intric/flows/ai_builder/ai_builder_create_compiler.py:22`, `:23`, `:40` | Create drafts pass through backend-owned mechanics before compilation. The compile path does not need a second source-material planner. |
| Compiled spec normalization uses the owner | `backend/src/intric/flows/ai_builder/ai_builder_step_transition_policy.py:88`, `:166`, `:177`, `:183`, `:196` | The compiled-spec topology normalizer completes missing source-material underlag by calling the same source-material owner. |
| Quality/scoring uses the same boundary predicate | `backend/src/intric/flows/ai_builder/ai_builder_validation_quality.py:310`, `:313`, `:319`; `backend/tests/integration/flows/ai_builder/benchmark/manual_api_scoring.py:128`, `:132` | Warnings and deterministic scoring reuse `iter_compiled_source_material_boundaries` and `source_material_binding_status`; they do not duplicate ad hoc matching. |
| Material metrics exist | `backend/src/intric/flows/ai_builder/ai_builder_material_metrics.py:26`, `:38`, `:66`, `:98`, `:170` | Metrics cover `binding_bytes`, `fan_in_width`, `structured_field_count`, `whole_output_reference_count`, `source_duplication_count`, and `all_previous_steps_count`. |
| Source text plus structured fields are tested | `backend/tests/unittests/flows/ai_builder/test_ai_builder_create_compiler.py:4312`, `:4313`, `:4327`, `:4328`; `:4387`, `:4396`, `:4402`; `:4471`, `:4477` | Compile tests assert generated `input_bindings.question` contains both immediate structured output and source text for audio/document report chains. |
| JSON-only negative is tested | `backend/tests/unittests/flows/ai_builder/test_ai_builder_step_transition_policy.py:1078`, `:1109`, `:1111`, `:1112` | Pure JSON chains do not receive source-material normalization when no report/document boundary needs it. |
| Idempotence is tested | `backend/tests/unittests/flows/ai_builder/test_ai_builder_step_transition_policy.py:1134`, `:1137`, `:1139`, `:1140`; `:1175`, `:1184`, `:1190` | Re-running normalization does not keep appending underlag. |
| Metrics tests cover expected fields | `backend/tests/unittests/flows/ai_builder/test_ai_builder_material_metrics.py:30`, `:53`, `:55`, `:56`, `:57`, `:58`, `:59`, `:60`; `:129`, `:136`, `:138`; `:176`, `:203`, `:207`, `:211`, `:215`, `:219`, `:222` | The expected material-efficiency counters are directly asserted. |

## Decision

`source-material routing risk remains`: no, not enough to activate T010 now.

The current code already has a named owner and tests for the specific T010 expected behaviors. A Worker would risk becoming a redundant polish pass unless a new failing flow or metric regression is found.

## Recommended Board Update

Mark T010 as done with a no-op receipt:

- Reason: its activation condition was not met.
- No source changes.
- No new names/classes/files.
- No Claude gate required for the no-op decision.

Activate the next Judge for proof-backed cleanup:

- Candidate: reassess T008 using the already mapped `FlowRepository.save_step_result` `result.step_id is None` branch.
- Why: T007 marked it as `delete_after_tests`, and later runtime work now pre-seeds result rows and saves claimed runtime step results with real step IDs.
- Stop if schema/history proof shows `step_id IS NULL` rows are still needed for current intended behavior.

## Naming And Type-Safety Constraints For Any Future Worker

- Do not add `V1` suffixes unless the class represents a real versioned persisted/API contract.
- Do not add `legacy`, `backwards-compatible`, or `support both` branches for never-shipped Flow behavior.
- Do not add Pyright ignores.
- Do not add broad `Any` to avoid type checking.
- If source-material routing changes later, extend `ai_builder_source_material.py` or its existing direct consumers. Do not add a parallel material-routing owner.

