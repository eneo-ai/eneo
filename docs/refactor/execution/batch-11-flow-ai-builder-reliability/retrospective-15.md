# Batch 11.5d Retrospective - Underlag Dataflow And Runtime Metadata

## TL;DR

1. Slice 11.5d fixes the reported audio-to-DOCX failure at the dataflow owner, not by adding more prompt wording.
2. Later semantic document steps can now receive both immediate metadata JSON and the original transcript text as `Underlag till text`.
3. Runtime `Inmatningsfält` are gated by the resolved runtime metadata slot, so source-derived fields do not become user questions.
4. Audio input architecture is protected from final Word/PDF/DOCX artifact wording and from model slot displacement when the heuristic is high confidence.
5. Focused Claude review, AI Builder unit tests, benchmark tests, lint, type, and diff checks passed locally; Docker execution remains tool-policy blocked.

## Result

| Area | Outcome |
|---|---|
| Source-material dependency contract | Added typed `uses_previous_outputs` refs for prior text-output dependencies. |
| Underlag rendering | `compile_input_bindings` combines immediate previous structured JSON with explicit non-adjacent text outputs. |
| Create validation | Previous-output refs must point to earlier text-producing steps; invalid refs are validator errors and normalization prunes them. |
| Audio-to-document skeletons | Downstream semantic document steps get the original transcription text as `Källmaterial` / `Source material`. |
| Runtime metadata fields | `no_extra_metadata` now suppresses outline `input_fields` and step `uses_input_fields`; detailed metadata keeps them. |
| Audio architecture | Explicit uploaded/recorded audio cannot be displaced by final artifact words or by a later model classification. |
| Redundant transcription outlines | LLM-authored duplicate transcription steps are dropped or rewritten because the backend owns the transcribe-only prefix. |

## Acceptance

| Criterion | Status | Evidence |
|---|---|---|
| The reported protocol step receives transcript underlag and metadata. | pass | DOCX protocol regression pins `{{ step_c.output.structured }}` plus `Källmaterial: {{ step_a.output.text }}`. |
| Previous text-output refs do not erase immediate previous JSON. | pass | Non-adjacent previous-output and previous-field compiler tests preserve immediate JSON. |
| Invalid previous-output refs do not compile silently. | pass | Validator and dataflow normalization tests cover non-text and invalid refs. |
| Runtime fields disappear when metadata is explicitly absent/defaulted absent. | pass | Outline compiler regression drops language/style/timestamps under `no_extra_metadata`. |
| Explicit runtime metadata still works. | pass | Detailed metadata regression keeps an `audience` field and binding. |
| The LLM cannot override high-confidence explicit audio input with documents/text. | pass | PlanningState merge regression pins the heuristic. |
| The solution does not make instructions the dataflow owner. | pass | Source material is rendered in `input_bindings.question`, not appended to assistant instructions. |

## Validation

| Command | Result |
|---|---|
| `uv run pytest tests/unittests/flows/ai_builder -q` | Passed: `1811 passed, 4 skipped`, 12 existing warnings. |
| `uv run pytest tests/integration/flows/ai_builder/benchmark/test_slot_resolver_corpus.py tests/integration/flows/ai_builder/benchmark/test_baseline_benchmark.py -q` | Passed: `69 passed`, 16 existing warnings. |
| `uv run ruff check <11.5d touched source and test files>` | Passed. |
| `uv run pyright <11.5d touched source and test files>` | Passed. |
| `git diff --check -- <11.5d touched paths>` | Passed. |
| Claude final verification | Passed: `.codex/artifacts/claude-peer-loop-batch-11-5d-underlag-runtime-final-verdict-format-20260503T121823Z.md`, `GREEN_LIGHT: yes`, `MIN_SCORE: 8`. |
| `docker ps --format '{{.Names}}'` | Blocked before Docker ran by tool policy: `approval required by policy, but AskForApproval is set to Never`. |

## Risk

| Risk | Mitigation |
|---|---|
| Extra source-material underlag could overfeed small models in long chains. | The rule is limited to audio-to-document semantic steps and references the transcript text only once per step. |
| `uses_previous_outputs` could become a second field-ref system. | It is restricted to text outputs, backend-owned in outline mode, and validated/pruned centrally. |
| Runtime metadata gating could drop useful optional fields. | Detailed metadata states still keep fields; absent/defaulted metadata now matches the primary runtime-input-only contract. |
| Live API behavior could differ from compile tests. | The exact debug-export failure is covered at compile level; a follow-up live smoke is documented when the local API path is available. |

## Follow-Ups

| Item | Owner |
|---|---|
| Run the exact reported audio-to-DOCX prompt through the local API after the tool path permits local API/Docker smoke commands. | Manual eval harness / next smoke slice. |
| Add a source-scope enum only if another source-material pattern proves `uses_previous_outputs` is too narrow. | Later skeleton/compiler cleanup. |
| Promote this exact Swedish prompt into the benchmark corpus if it recurs beyond the compile regression. | Reliability corpus maintenance. |

Confidence: high.
