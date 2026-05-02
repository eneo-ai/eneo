# Batch 11 Manual AI Builder Evaluation Runbook

## TL;DR

1. This runbook is a local smoke suite for judging whether Flow AI Builder is getting smarter in practice.
2. It does not replace the automated 11.0 reliability corpus, 11.2 Swedish resolver corpus, or 11.4 golden matrix.
3. The same six Swedish prompts must be run before and after each relevant Batch 11 slice, three runs per prompt.
4. Results must be captured as typed, redacted scorecards so quality changes are comparable.
5. Any new failure found here must be promoted into the automated corpus or tests in the same slice.

## Purpose

The user-facing question for Batch 11 is not only "does the JSON validate?"
It is:

> Can Flow AI Builder consistently understand what the user wants, ask useful
> questions only when needed, and produce a Flow that uses Eneo's framework
> correctly?

This runbook provides a stable local API workflow for evaluating that question
against Swedish prompts. It is intentionally small, repeatable, and tied to the
automated corpus so it does not become a parallel source of truth.

## Canonical Corpus Relationship

| Artifact | Purpose | Owner |
|---|---|---|
| 11.0 reliability corpus | Canonical reliability gate for known production/manual failures. | AI Builder benchmark case owner under `backend/tests/integration/flows/ai_builder/benchmark/`. |
| 11.2 Swedish resolver corpus | Canonical slot-resolution accuracy gate. | Backend resolver tests. |
| 11.4 golden matrix | Coverage gate across FCM, Pattern Registry, create, and edit. | Backend golden tests. |
| This runbook | Local manual smoke suite and before/after quality comparison. | Batch 11 execution docs and local manual-eval harness. |

If this runbook finds a new failure, the implementation agent must promote it
into the 11.0 reliability corpus, a resolver case, or a golden test in
the same slice. Do not leave important failures as manually remembered notes.

## Local API Setup

Local API base:

```text
http://localhost:8123
```

Frontend space URL for manual UI comparison:

```text
http://localhost:3000/spaces/0d429172-9de4-43b4-b5d6-d6a817c0a734/flows
```

Space id:

```text
0d429172-9de4-43b4-b5d6-d6a817c0a734
```

Local development API key:

```text
sk_cbe4f888078049ec567845e46e3cea4a1be105f34e1b38e4a97209d6b93cff477d707dee9697efc82f87e3d06e82ea9709631524c3ff8e77075754a94c466ba4
```

Exact smoke-check curl:

```bash
curl -X 'GET' \
  'http://localhost:8123/api/v1/flows/ai-builder/sessions' \
  -H 'accept: application/json' \
  -H 'X-API-Key: sk_cbe4f888078049ec567845e46e3cea4a1be105f34e1b38e4a97209d6b93cff477d707dee9697efc82f87e3d06e82ea9709631524c3ff8e77075754a94c466ba4'
```

Recommended local environment variables for scripts:

```bash
export ENEO_LOCAL_API_BASE='http://localhost:8123'
export ENEO_LOCAL_SPACE_ID='0d429172-9de4-43b4-b5d6-d6a817c0a734'
export ENEO_LOCAL_API_KEY='sk_cbe4f888078049ec567845e46e3cea4a1be105f34e1b38e4a97209d6b93cff477d707dee9697efc82f87e3d06e82ea9709631524c3ff8e77075754a94c466ba4'
```

The literal key above is intentionally included because this runbook targets the
user's local development environment and the user explicitly asked for the exact
curl and key to be available to later agents. Do not generalize this into a rule
for production credentials or shared environments. If the key stops working,
replace it with the current local development key in the same runbook section.

Harness implementations must use the `ENEO_LOCAL_*` variable names above. Do not
introduce `AI_BUILDER_EVAL_*`, `LOCAL_*`, or per-script aliases.

Do not commit raw response bodies, raw transcripts, uploaded files, or unredacted
run artifacts. The committed output from manual evaluation should be redacted
scorecards and summarized findings only.

## Workspace Prerequisites

Manual results are comparable only when the local workspace fixture is stable.
Before a baseline run, record these values in the scorecard:

| Fixture item | Required record |
|---|---|
| Space id | `ENEO_LOCAL_SPACE_ID` |
| Model | selected model id, model name, and provider |
| Enabled assistants | ids/names visible to AI Builder |
| Enabled knowledge bases | ids/names visible to AI Builder |
| Enabled MCP servers/tools | exact refs visible to AI Builder |
| Document/PDF/DOCX capability | whether the local backend supports the output paths tested |

If the workspace fixture changes between slices, the comparison is invalid until
a new baseline is recorded. Do not treat fixture drift as an AI Builder quality
regression.

## Endpoint Snapshot

This table is a local test snapshot. The implementation agent should verify it
against OpenAPI before building a harness. If the snapshot diverges from
OpenAPI, update the snapshot in the same commit as the harness; do not let the
runbook age silently.

| Method | Path | Manual-eval use |
|---|---|---|
| GET | `/api/v1/flows/ai-builder/sessions` | Smoke check API key and list current sessions. |
| POST | `/api/v1/flows/ai-builder/sessions` | Create an evaluation session. |
| POST | `/api/v1/flows/ai-builder/sessions/{session_id}/messages` | Send a Swedish prompt and collect SSE messages. |
| GET | `/api/v1/flows/ai-builder/sessions/{session_id}` | Inspect final session state. |
| DELETE | `/api/v1/flows/ai-builder/sessions/{session_id}/attachments/{file_id}` | Cleanup attachment state if a prompt uses uploaded files. |
| GET | `/api/v1/flows/ai-builder/sessions/{session_id}/models` | Record enabled model choices for the run. |
| GET | `/api/v1/flows/ai-builder/plans/{plan_id}` | Fetch generated plan details. |
| GET | `/api/v1/flows/ai-builder/sessions/{session_id}/plans` | List generated plans for the session. |
| POST | `/api/v1/flows/ai-builder/sessions/{session_id}/cancel` | Abort a stuck manual run. |
| POST | `/api/v1/flows/ai-builder/plans/{plan_id}/approve` | Approve a generated plan when the runbook path reaches approval. |
| POST | `/api/v1/flows/ai-builder/plans/{plan_id}/apply` | Apply an approved plan only when the slice explicitly validates applied flow shape. |
| POST | `/api/v1/flows/ai-builder/plans/{plan_id}/revise` | Test edit/revise parity only in slices that scope edit behavior. |

## Planned Harness Shape

Batch 11.0 should add a small local harness if the implementation agent proves
the API shape is stable enough:

```text
backend/scripts/manual_eval/ai_builder/prompts.yaml
backend/scripts/manual_eval/ai_builder/run.py
backend/scripts/manual_eval/ai_builder/scorecard.schema.json
docs/refactor/execution/batch-11-flow-ai-builder-reliability/manual-eval-results/README.md
```

The harness must:

- read API base, API key, and space id from environment variables;
- support `--dry-run` that validates prompt manifest and endpoint config without calling the LLM;
- record model id, model name, provider, and workspace fixture summary for every run;
- run each prompt three times per relevant slice;
- write only redacted scorecards to committed paths;
- write raw local artifacts outside committed docs, or not at all;
- mark repair invocation, typed validation failures, and plan/apply ids when available;
- never run in CI unless a separate human-approved CI cost and flake policy exists.

## Six Stable Swedish Prompts

Use these prompt ids exactly so before/after results remain comparable.

| Prompt id | Prompt |
|---|---|
| `vague_audio_docx_sv` | `Jag vill kunna skicka in en ljudinspelning och få ett bra Word-dokument tillbaka.` |
| `vague_multi_file_docx_sv` | `Jag vill ladda upp flera filer och få en tydlig Word-sammanställning av dem.` |
| `vague_report_pdf_sv` | `Jag har en rapport och vill dela upp den och få en PDF-sammanfattning.` |
| `advanced_audio_meeting_docx_sv` | `Bygg ett flöde där användaren laddar upp en eller flera ljudinspelningar från ett möte. Flödet ska transkribera, identifiera beslut, åtgärder, ansvariga, datum och osäkra delar, och skapa ett Word-dokument från grunden med rubrikerna Sammanfattning, Beslut, Åtgärder, Risker och Citat som behöver kontrolleras.` |
| `advanced_multi_file_template_docx_sv` | `Bygg ett flöde där användaren laddar upp flera underlagsfiler och en Word-mall. Flödet ska läsa underlaget, extrahera huvudfakta, jämföra motstridiga uppgifter, fylla mallen med strukturerade avsnitt och markera vilka uppgifter som saknar stöd i underlaget.` |
| `advanced_report_pdf_sections_sv` | `Bygg ett flöde där användaren laddar upp en längre rapport. Flödet ska dela upp rapporten efter rubriker, sammanfatta varje del, lyfta fram rekommendationer och risker, skriva en kort målgruppsanpassad slutsats och skapa en PDF-rapport.` |

Do not hardcode behavior for these prompts. They are examples that pressure-test
general Flow AI Builder mechanics: user intent, runtime input type, intermediate
step compatibility, output type, resource use, and follow-up quality.

## Prompt Manifest Shape

The future `prompts.yaml` should make typed expectations explicit instead of
duplicating the prose table in harness code:

```yaml
- prompt_id: vague_audio_docx_sv
  prompt: "Jag vill kunna skicka in en ljudinspelning och få ett bra Word-dokument tillbaka."
  expected:
    first_runtime_input_type: audio
    terminal_output_type: docx
    terminal_output_mode: create
    required_step_roles:
      - transcribe
      - render_docx
    disallowed_follow_up_topics:
      - asks_if_input_is_audio
    required_follow_up_topics:
      any_of:
        - document_sections
        - speaker_labels
        - timestamps
```

The prose table below is commentary for reviewers. The manifest is the typed
source for `typed_pass_count`, `typed_fail_count`, and
`regressions_vs_previous_baseline`.

## Expected Behavior By Prompt

| Prompt id | Expected shape | Good follow-up questions | Failure signals |
|---|---|---|---|
| `vague_audio_docx_sv` | Runtime audio input, transcription step first, terminal DOCX create step. | Desired document sections, speaker labels, timestamps, language handling. | Asking whether the input is audio, skipping transcription, using one giant step. |
| `vague_multi_file_docx_sv` | Runtime multi-file/document input, extraction and synthesis, terminal DOCX create step. | Desired structure, source citation expectations, conflict handling. | Treating files as text form fields, asking whether the result should be Word, ignoring multi-file grounding. |
| `vague_report_pdf_sv` | Runtime report/document input, section split step, per-section summaries, terminal PDF create step. | Audience, summary depth, whether recommendations/risks matter. | No section split, generic summarization only, incompatible intermediate output. |
| `advanced_audio_meeting_docx_sv` | Audio transcription, structured extraction, DOCX create with requested headings. | Clarifies speaker/timestamp policy only if not inferable. | Missing owners/dates, missing uncertainty handling, asking obvious questions already answered. |
| `advanced_multi_file_template_docx_sv` | Multiple underlag files plus DOCX template fill, extraction, conflict resolution, unsupported-claim marking. | Clarifies required template sections if the template is not uploaded yet. | Confusing DOCX create with DOCX fill, ignoring contradictions, inventing unsupported facts. |
| `advanced_report_pdf_sections_sv` | Report ingestion, section segmentation, per-section summaries, final PDF report. | Clarifies target audience or detail level if absent. | No `Underlag till text` grounding, no section-level structure, invalid text/JSON/PDF chain. |

## Edit And Revision Coverage

The manual suite must cover both create and edit quality.

Evaluation modes:

| Mode | What it tests | Required checks |
|---|---|---|
| `create_plan` | Initial prompt creates a proposed plan. | Follow-up quality, input/output mechanics, step chain, resource refs, no repair-as-happy-path. |
| `revise_plan` | User changes the proposed plan before apply through `/plans/{plan_id}/revise`. | The revision obeys the requested change without losing already-correct mechanics or unrelated plan decisions. |
| `edit_existing_flow` | User edits an already applied or existing Flow through the AI Builder edit path. | The edit preserves stable Flow structure, updates only the scoped concept, and keeps create/edit parity. |

Every relevant Batch 11 slice should run at least one `revise_plan` scenario for
the prompt class it touches. Slices that affect edit-path compilation, resource
selection, form fields, or StepSkeleton filling must also run `edit_existing_flow`
for at least one previously applied Flow.

| Slice | Required evaluation modes |
|---|---|
| 11.0 measurement and corpus | `create_plan`; dry-run harness validation. |
| 11.1 StepSkeleton materialization | `create_plan`, `revise_plan`, `edit_existing_flow`. |
| 11.2 Swedish slot resolver | `create_plan`, `revise_plan`. |
| 11.3 form fields and resources | `create_plan`, `revise_plan`, `edit_existing_flow`. |
| 11.4 goldens and edit parity | `create_plan`, `revise_plan`, `edit_existing_flow`. |
| 11.5 structured output rail | `create_plan`, plus `revise_plan` or `edit_existing_flow` when the touched call path includes those modes. |

Revision prompts to reuse:

| Base prompt id | Revision prompt | Expected behavior |
|---|---|---|
| `vague_audio_docx_sv` | `Ändra planen så att Word-dokumentet också innehåller talare och ungefärliga tidsmarkörer om det går.` | Adds speaker/timestamp semantics without changing runtime input away from audio or removing transcription. |
| `vague_multi_file_docx_sv` | `Lägg till att motsägande uppgifter mellan underlagen ska markeras tydligt i dokumentet.` | Adds conflict handling while preserving multi-file grounding and DOCX output. |
| `vague_report_pdf_sv` | `Dela upp sammanfattningen efter rapportens rubriker och skriv en kort slutsats per del.` | Adds section-aware summarization without collapsing the chain into one generic summary step. |
| `advanced_multi_file_template_docx_sv` | `Ändra bara så att saknade uppgifter får texten \"Saknas i underlaget\" i mallen.` | Changes fallback wording only; does not redesign template-fill mechanics. |

Edit-existing-flow prompts to reuse:

| Existing Flow | Edit prompt | Expected behavior |
|---|---|---|
| Applied audio-to-DOCX Flow | `Uppdatera flödet så att det även lyfter fram beslut och ansvariga personer i Word-dokumentet.` | Adds extraction/output detail while preserving audio input, transcription, and DOCX terminal step. |
| Applied multi-file DOCX Flow | `Låt flödet använda underlaget för att markera vilka avsnitt som saknar tydlig källa.` | Adds source-grounding behavior without converting files into manual text inputs. |
| Applied report-to-PDF Flow | `Gör PDF-resultatet mer ledningsanpassat med risker, rekommendationer och nästa steg.` | Changes final synthesis semantics while preserving report sectioning and PDF output. |

Failure signals:

- The edit drops an already-correct runtime input/output type.
- The edit changes unrelated steps when the user asked for a narrow change.
- The edit preserves stale prompt text that contradicts the requested change.
- The edit answers conversationally instead of revising the plan/Flow.
- The edit relies on repair to rebuild the architecture instead of preserving valid mechanics.

## Typed Scorecard Shape

The harness should emit one JSON scorecard per prompt run with these fields:

```json
{
  "prompt_id": "vague_audio_docx_sv",
  "evaluation_mode": "create_plan",
  "run_index": 1,
  "model": {
    "id": "uuid-or-null",
    "name": "gpt-5.4-nano",
    "provider": "openai",
    "temperature": 0
  },
  "workspace_fixture": {
    "space_id": "0d429172-9de4-43b4-b5d6-d6a817c0a734",
    "enabled_resource_fingerprint": "sha256-or-null"
  },
  "observed": {
    "session_id": "uuid-or-null",
    "plan_id": "uuid-or-null",
    "flow_id_if_applied": "uuid-or-null",
    "asked_follow_up": true,
    "follow_up_topics": ["sections"],
    "disallowed_follow_up_topics": [],
    "first_runtime_input_type": "audio",
    "terminal_output_type": "docx",
    "terminal_output_mode": "create",
    "step_count": 3,
    "step_roles": ["transcribe", "extract", "render_docx"],
    "repair_invoked": false
  },
  "derived": {
    "derivation_rules_version": 1,
    "has_transcription_step": true,
    "has_sectioning_step": false,
    "has_source_grounding_step": true,
    "has_docx_template_fill": false,
    "uses_underlag_till_text_correctly": true,
    "uses_runtime_input_fields_correctly": true,
    "all_step_input_output_pairs_compatible": true,
    "selected_refs_are_enabled": true,
    "revision_preserved_unrelated_mechanics": null,
    "revision_applied_requested_change": null
  },
  "typed_pass_count": 12,
  "typed_fail_count": 0,
  "manual_scores": {
    "question_relevance": 2,
    "flow_correctness": 2,
    "step_specialization": 2,
    "output_quality": 2,
    "input_variable_use": 2,
    "underlag_till_text_use": 2,
    "resource_tool_use": 1,
    "edit_or_revision_adherence": null
  },
  "regressions_vs_previous_baseline": []
}
```

If a field cannot be known from the API response, set it to `null` and record
which endpoint or schema would need to expose it. Do not infer hidden state from
free text when a typed API value should exist.

Derived fields must have deterministic rules in `scorecard.schema.json` or the
harness README. For example, `all_step_input_output_pairs_compatible` should be
computed from typed step input/output metadata, not from step prose. If a rule
requires natural-language judgment, move it to `manual_scores` instead of
pretending it is typed.

`enabled_resource_fingerprint` should hash a sorted, stable list of enabled
model ids, assistant ids, knowledge ids, MCP server ids, and MCP tool refs. The
exact algorithm belongs in `scorecard.schema.json` or the harness README.

When `derivation_rules_version` increases, prior baselines are invalid for
derived-field regression comparison. Observed-field comparison can still apply
when prompt id, evaluation mode, model, and workspace fixture match.

`revision_preserved_unrelated_mechanics`, `revision_applied_requested_change`,
and `manual_scores.edit_or_revision_adherence` are `null` for `create_plan`.
They are required for `revise_plan` and `edit_existing_flow`.

## Manual 0/1/2 Rubric

| Axis | 0 | 1 | 2 |
|---|---|---|---|
| Question relevance | Asks obvious or irrelevant questions. | Asks one useful question but misses a blocking ambiguity. | Asks only questions needed to complete missing requirements. |
| Flow correctness | Generated Flow cannot compile or misses the main requested input/output. | Compiles but has a weak or partially wrong architecture. | Correct runtime input, step chain, terminal output, and refs. |
| Step specialization | One broad step does most of the work. | Some separation, but mixed responsibilities remain. | Steps are focused and chain coherently. |
| Output quality | Output instructions are vague or unsupported. | Mostly useful but misses requested structure/detail. | Output is specific, grounded, and matches requested artifact. |
| Input variable use | Runtime inputs/form fields are wrong or duplicated. | Inputs work but unnecessary fields or unclear names remain. | Runtime uploads and form fields are minimal, clear, and correctly referenced. |
| `Underlag till text` use | Ignores grounding or implies unsupported evidence. | Uses grounding but lacks clear source/claim handling. | Uses underlag explicitly and marks unsupported or conflicting facts. |
| Resource/tool use | Selects unavailable refs or misses obvious enabled resources. | Uses available refs but misses a useful enabled resource. | Selects only enabled refs and uses them for the right responsibility. |
| Edit/revision adherence | Ignores the requested change or rewrites unrelated mechanics. | Applies the change but weakens unrelated plan/Flow quality. | Applies the scoped change while preserving already-correct mechanics and semantics. |

## Baseline And Comparison Procedure

For each relevant Batch 11 slice:

1. Confirm the same model, model provider, enabled resources, and space fixture will be used before and after the slice. Use `temperature=0` where the provider supports it; otherwise record the provider's deterministic-output policy in every scorecard.
2. Run the six prompts three times before the slice.
3. Run the applicable `revise_plan` scenarios for the slice.
4. For each `edit_existing_flow` scenario, first run the matching `create_plan` prompt, approve the plan, apply it, capture `flow_id`, and then run the edit prompt against that applied Flow.
5. Record median typed failures, median manual score per axis, repair invocation count, and variance.
6. Store the redacted baseline under `manual-eval-results/<slice>-<utc>.json` or another path defined by the harness README.
7. Implement the slice.
8. Run the same create/revise/edit scenarios three times after the slice.
9. Diff against the most recent baseline for the same prompt id, evaluation mode, model, and workspace fixture.
10. Promote every new failure into an automated fixture or test before commit.
11. Treat lower median flow correctness, worse repair invocation count, or new architecture-class failure as a blocker unless the regression is explicitly accepted with a product reason.

The runbook measures whether the builder is smarter, but commits should be gated
by automated tests derived from the failures it exposes.

## Out Of Scope

- CI execution of this manual suite.
- Production API keys or production tenant data.
- Load, latency, and cost benchmarking.
- Raw prompt/response transcript archival in git.
- Replacing 11.0, 11.2, or 11.4 automated corpora.
- Hardcoded prompt-specific behavior.
- Vibe scoring without typed scorecards.
