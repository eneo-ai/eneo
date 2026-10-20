# Flows

A flow is a fixed, ordered list of typed steps that a space runs unattended
once someone starts it with its run inputs. The step kind decides what
executes; no model decides at run time whether a step runs or what it
produces. People do not edit flows by hand: a flow is written in a chat with
the space's hidden flows assistant, which authors through Eneo's own
loopback MCP server (`flows`), and the panel beside the chat shows every
parameter and every run.

This directory is the engineering view. The user-facing and integration
documentation lives on the docs site (`frontend/apps/docs-site`, "Flows").

## What a flow is made of

| Part | Where | Notes |
|---|---|---|
| Definition | `flows.definition` (draft), `flow_versions.definition` (published snapshots) | `backend/src/eneo/flows/definition.py`: a Pydantic discriminated union on `kind`; its JSON schema is what the model is told it may send. |
| Revisions | `flow_revisions` | Every save, with a note; restoring one is a new revision. |
| Runs | `flow_runs` + `flow_step_results` + `flow_step_attempts` | A run snapshots the definition it executes (`flow_runs.definition`); a test run of the draft has no version. |
| Files | `flow_files` (templates, runtime uploads), `flow_run_files` (inputs, outputs) | All files go through `FileService`, so the platform's file lifecycle applies. |
| Reviews | `flow_run_review_checkpoints` | One active checkpoint per run; compare-and-swap on `revision`. |
| Transcript corrections | `flow_transcript_corrections` | Anchored to the stored segments by hash; applied on read. |

### Step kinds

| kind | runs as |
|---|---|
| `llm` | One completion with a fixed prompt; text or schema-checked JSON (one bounded retry). Knowledge is injected through the references service, never through tools. |
| `compose` | `render_template` over run inputs and earlier outputs. No model. |
| `document` | A call to the file-creation provider: `create_document` from Markdown content (the organisation's document template applies) or `fill_template` for a form attached in the chat and pinned to the flow. |
| `function` | A call to the provider of any of Eneo's functions (web search, image generation, charts, compute, file analysis, file creation) with arguments fixed in the definition; the tool's text, structured value and files are the step's output. `list_functions` tells the model what exists. |
| `transcribe` | The space's transcription model over the audio of a form field, in 5-minute chunk windows; speaker labels through the configured speaker service (`FLOW_SPEAKER_SERVICE_URL`); names through one fixed-prompt completion. Segments stay with the step result. |
| `review` | Pauses the run; a person approves, edits and approves, or rejects. |

Templates read `{{form.<key>}}`, `{{steps.<key>}}`, `{{steps.<key>.json.<path>}}`,
`{{steps.<key>.file}}`, `{{files.<key>}}` and `{{previous}}` (`templating.py`).
A list of plain values renders as bullet lines.

## Execution

`FlowRunExecutor` (`flow_run_executor.py`) runs each step in three short
transactions: claim (`pending -> running`, open an attempt), prepare (resolve
models, files, providers into plain data), persist (store files, record the
outcome, close the attempt). Provider I/O runs between them. A redelivered
job skips completed steps through the claim; a step found `running` without
a claim means a worker died mid-call: the attempt becomes `outcome_unknown`,
the run fails, the call is never repeated. The ARQ task is `run_flow`
(`flow_run_worker.py`), a durable job with a heartbeat; the cron
`reconcile_stale_flow_runs` terminalizes runs whose heartbeat is older than
ten minutes.

`StepRunners` (`step_runners.py`) holds the runners. Document and function
steps resolve their provider exactly as a turn of the hidden flows assistant
would (`assistant_service.capability_server`), so the space's enabled
functions, the user's permissions and the security classification apply.

## Authoring

The hidden assistant (`flow_assistant_service.py`, `assistants.purpose =
'flows'`, one per space, holds every function capability) gets the loopback
`flows` server attached (`internal_mcp/flows.py`). Tools: `list_functions`,
`list_flows`, `get_flow`, `update_flow`, `list_revisions`,
`restore_revision`, `publish_flow`, `delete_flow`, `run_flow` (with
`draft=true` for a test run), `get_run`, `cancel_run`, `review_run`. A flow
is created empty from the flows page and bound to its chat; `flow_id`
defaults to the chat's own flow. Validation problems come back as text so
the model repairs them in the same turn. The prompt is
`authoring_prompt.py` (versioned; the assistant is repaired on load).

## REST

`flows/api/flow_router.py`, behind the tenant feature flag `flows_core`.
Authoring is read-only over REST (list, get, revisions, delete, bind
conversation). The run side is what API consumers integrate against and is
listed by `GET /flows/{id}/published/`; `docs/flows/api-compatibility.md`
compares it with the previous branch.

Principals: a user needs the space's flow permissions (viewer reads and
runs published flows; editor and up author). A service API key runs
published flows in its scope, sees only the runs it started, and never
authors; the job and the files of such a run belong to the flow's author.

## Settings

| Setting | Meaning |
|---|---|
| `FLOW_STEP_TIMEOUT_SECONDS` | Upper bound for one step (default 900). |
| `FLOW_SPEAKER_SERVICE_URL`, `FLOW_SPEAKER_SERVICE_API_KEY`, `FLOW_SPEAKER_SERVICE_POLL_SECONDS` | The speaker-labelling job service (`speaker_service.py`); unset means speaker labels cannot be published. |
| `FILE_REFERENCE_BASE_URL` / `PUBLIC_ORIGIN` | Where providers fetch the signed file links a step hands them. |

## History

`feature/flows-and-builder` (a hand-built editor, an AI builder driving it
and a far larger runtime) is superseded by this rebuild and kept only as a
quarry. See `architecture.md` for the decisions.
