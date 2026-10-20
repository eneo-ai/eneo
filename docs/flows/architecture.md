# Flows architecture

## Decisions

- **Creation is a conversation, execution is a program.** The model authors
  a flow through MCP tools and never executes one. A flow is deterministic:
  the same inputs run the same steps with the same prompts. This removed the
  editor, the AI builder and the output-mode grid of the previous branch.
- **One definition document.** Form fields and steps are JSON in the flow
  row; publishing freezes a snapshot; a run snapshots what it executes. No
  per-step tables, no per-step hidden assistants, no bindings or fan-out.
- **Providers are the platform's.** Document and function steps reach the
  same capability providers a chat turn would, through the hidden flows
  assistant, so administration of functions, security classifications and
  user permissions is not duplicated for flows.
- **Singleton services are settings.** The speaker-labelling service is a
  URL and a key in the configuration, like the other services Eneo calls,
  not a catalog entity with its own admin page.
- **Everything stored is readable later.** Transcript segments stay with the
  step result; corrections are an overlay anchored by hash and applied on
  read; review payloads keep original and current; revisions keep every
  save.
- **Service keys are automation principals.** They run published flows and
  read their own runs; they do not author, and what they upload or produce
  belongs to the flow's author (an API key owns no rows).

## Request paths

```
chat turn ── hidden flows assistant ── loopback flows MCP ── FlowService / FlowRunService
                                                            │
flows page / panel ── REST (flow_router) ───────────────────┤
                                                            │
API consumer ── REST run side (published, run-contract, runs, review, …)
                                                            ▼
                                             durable job run_flow ── FlowRunExecutor ── StepRunners
                                                                              │
                                                     completion service, references, transcriber,
                                                     capability providers via MCP proxy, speaker service
```

## Execution model

Three transactions per step (claim, prepare, persist) with provider I/O in
between; the attempt row is the receipt of a provider call. A review step
opens a checkpoint and parks the run (`awaiting_review`); resume queues a
new job with the same run id and the executor finds the approved checkpoint
when it reaches the step again. Cancellation is a compare-and-swap on the
run status that the worker honours at the next step boundary.

## Files

Every file a flow touches is a `files` row: templates attached in the chat
and pinned (`flow_files.role = template`), runtime uploads for API runs
(`runtime_upload`), run inputs and outputs (`flow_run_files`). Providers
receive signed original-download links minted per run; stored payloads keep
the links redacted. Signed links for readers are minted through the run
(artifact and input-file endpoints), so every reader of a flow can open a
run's files, not only their uploader.

## Transcription

The transcription model produces text in 5-minute chunk windows; those
windows are the segments. With speaker labels the audio and the windows go
to the speaker service, which labels speakers inside them and never
rewrites the text; labels are renumbered across files. Names come from a
participant list or from the conversation itself, through a fixed prompt
whose answer is validated against a JSON contract. Corrections (text spans,
speaker edits, names) are an overlay keyed by the segment hash.

## What the previous branch had that this does not (yet)

HTTP delivery, packages, fan-out over lists, evidence export, retention
holds, schedules, word timings and live transcription, correction revision
history, and the admin-managed transcription service catalog. Each is
sized in the program plan and can be added without changing the model.
