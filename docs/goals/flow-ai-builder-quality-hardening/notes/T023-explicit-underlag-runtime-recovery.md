# T023 Explicit Underlag Runtime Recovery

## Result

Done.

## Problem

The reported meeting flow showed two separate failure modes:

- Runtime resolved `input_bindings.question` but JSON step preparation could still validate or overwrite against the implicit previous JSON source.
- The editor graph/warning logic treated `previous_step` as the only valid dependency for a step, even when explicit underlag intentionally referenced older steps.

The later live run completed successfully. Its debug export still shows an optimization signal: intermediate JSON analysis steps generated before a backend restart can remain plain previous-step JSON while their instructions say they read the whole transcript. Current local compiler tests cover the desired source-material normalizer behavior.

## Changes

- Preserve resolved explicit underlag as the effective runtime input.
- Skip JSON input-contract validation when explicit underlag is prose rather than structured JSON.
- Let AI Builder clear input contracts when it compiles explicit underlag for a JSON step.
- Add graph dependency edges for explicit underlag references.
- Align frontend reference conflict detection with backend graph semantics.

## Validation

- `cd backend && uv run pytest tests/unittests/flows/test_flow_graph.py tests/unittests/flows/test_typed_io_executor.py tests/unittests/flows/test_step_execution_runtime.py tests/unittests/flows/ai_builder/test_ai_builder_create_compiler.py -k 'not document_outputs_generate_downloadable_artifacts' -q`
- `cd backend && uv run pyright src/intric/flows/api/flow_graph.py src/intric/flows/step_lineage.py src/intric/flows/runtime/step_input_resolution.py src/intric/flows/runtime/step_execution_runtime.py src/intric/flows/ai_builder/ai_builder_new_step_compiler.py tests/unittests/flows/test_flow_graph.py tests/unittests/flows/test_typed_io_executor.py tests/unittests/flows/test_step_execution_runtime.py tests/unittests/flows/ai_builder/test_ai_builder_create_compiler.py`
- `cd backend && uv run ruff check src/intric/flows/api/flow_graph.py src/intric/flows/step_lineage.py src/intric/flows/runtime/step_input_resolution.py src/intric/flows/runtime/step_execution_runtime.py src/intric/flows/ai_builder/ai_builder_new_step_compiler.py tests/unittests/flows/test_flow_graph.py tests/unittests/flows/test_typed_io_executor.py tests/unittests/flows/test_step_execution_runtime.py tests/unittests/flows/ai_builder/test_ai_builder_create_compiler.py`
- `cd frontend/apps/web && bun run test:unit -- src/lib/features/flows/flowVariableTokens.test.ts src/lib/features/flows/flowStepUxCopy.test.ts --run`
- `cd frontend/apps/web && bunx prettier --check src/lib/features/flows/flowVariableTokens.ts src/lib/features/flows/flowVariableTokens.test.ts src/lib/features/flows/components/FlowStepEditPanel.svelte`
- `git diff --check` for selected task files.

## Claude

Claude peer loop `flow-underlag-dependency-20260505` returned `GREEN_LIGHT: yes` on iteration 3. Artifact:

`.codex/artifacts/claude-peer-loop-flow-underlag-dependency-implementation-review-iteration-3-20260505T122726Z.md`

## Remaining Note

The successful live debug export confirms the final artifact step receives explicit fan-in. For best intermediate analysis quality, regenerated flows should be produced by a restarted server containing the current source-material normalizer so JSON section extractors that claim to read the transcript also receive it in explicit underlag.
