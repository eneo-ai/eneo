# Flow architecture

This is the maintainer map for the final Flow implementation. Start with the
[developer quickstart](./flow-developer-quickstart.md) for the data model and
[package layout](./package-layout.md) before moving root-level modules.

## Product boundary

Core Flows owns manual authoring, immutable published versions, execution,
review, evidence, packages, retention, and operations. Flow AI Builder is a
stacked extension: it discovers intent and compiles an approved plan into the
same draft model. Builder does not own a second runtime or schema interpretation.

The final product deliberately has:

- one complete run per execution request;
- retry and recovery attempts within that run;
- no partial-step rerun or result-invalidation API;
- complete Flow → Space → Organization run-history policy inheritance;
- no classification-retention control plane, preview workflow, or tombstones;
- platform-owned task execution and maintenance, with no Flow-private worker or
  scheduler process.

## Stable model

| Object | Source of truth | Rule |
| --- | --- | --- |
| Draft Flow | `flows` and `flow_steps` | Mutable authoring state protected by draft revision. |
| Published version | `flow_versions.definition_json` | Immutable, checksummed runtime snapshot. |
| Run | `flow_runs` and runtime child tables | One execution pinned to one published version and tenant. |
| Attempt | `flow_step_attempts` | Retry, recovery, and diagnostic evidence inside one run. |
| Builder session | Builder tables on the stacked branch | Authoring evidence only; compilation targets the core draft model. |

Runtime must never read mutable draft steps. To repeat completed work, create a
new run against an explicit published version.

## Main journey

```text
draft authoring
  -> publish immutable definition
  -> create queued run and commit
  -> dispatch through PlatformFlowExecutionBackend
  -> platform execution worker claims the run
  -> execute steps and persist attempts/results/evidence
  -> optionally await review
  -> terminalize from persisted state
  -> deliver audit and webhook outboxes
```

The API commits the run before dispatch. Dispatch uses a compare-and-swap
contract so a delayed delivery, request retry, or maintenance redispatch cannot
claim a newer lifecycle generation. Provider calls with an unknown outcome are
not repeated automatically.

## Canonical owners

| Concern | Owner |
| --- | --- |
| Draft lifecycle and publish | `flows/application/flow_service.py` |
| Published definition build/parse | `flows/published_definition.py` |
| Runtime consumer contract | `flows/flow_run_contract_service.py` |
| API authorization context | `flows/api/flow_access_context.py` and `flow_access_policy.py` |
| Run creation and dispatch | `flows/application/flow_run_service.py` |
| Queue-neutral task boundary | `flows/runtime/tasks.py` |
| Platform ARQ registration | `worker/platform_tasks.py` |
| Execution loop | `flows/runtime/executor.py` |
| Terminal lifecycle writes | `flows/application/flow_run_terminalizer.py` |
| Persistence and locking | `flows/infrastructure/flow_run_repo.py` |
| Human review | review checkpoint service and repository |
| Evidence and artifacts | evidence service plus runtime file repositories |
| Audit delivery | audit-outbox repository and delivery service |
| Webhook delivery | webhook repository and delivery service |
| Portable Flow packages | `eneo/flow_packages` |
| Retention policy | `flows/domain/flow_run_retention_policy.py` and `flows/application/flow_run_retention_policy_service.py` |

API adapters parse, authorize, and delegate. Application services own use-case
transactions. Repositories own tenant-scoped persistence and locks. Domain
modules own closed contracts and invariants. Runtime code decides when work is
ready but delegates terminal state changes to the application owner.

## Platform task runtime

Flows contributes adapters to the shared platform task system. Production needs
two platform processes:

- `task-execution-worker` for run execution;
- `task-maintenance-worker` for scheduled recovery and outbox work.

The maintenance worker registers five Flow tasks: reconcile stale running runs,
expire review checkpoints, redispatch stale queued runs, deliver lifecycle audit
outbox rows, and deliver webhook outbox rows. ARQ configuration, queues,
capacity, scheduling, timeouts, tracing, and health belong to the platform.
Flow services remain queue-neutral.

## Attempts, evidence, and review

Each step result is the current persisted outcome for a published step. Attempts
record bounded execution history and diagnostics. They support retries and crash
recovery; they are not a user-facing rerun graph.

Review begins only after the completed step result is durable. A checkpoint is
revisioned and tenant-scoped. Exactly one requester identity and one valid
decision actor are accepted. Approval resumes the same run; rejection or expiry
uses canonical terminalization.

Evidence and files preserve their tenant, run, step, and attempt provenance.
Export of a run's evidence is off until the flow's own metadata allows it
(`evidence_policy.allow_export`); the run access policy enforces it from the
flow's current row for every principal its other rules let through, so a caller
who may not export learns nothing about the setting.
Raw evidence export is exceptional, audited before response, and fails closed
when its protection preconditions are not met.

### AI Builder failure telemetry

Builder provider failures log the estimated request input tokens, selected
model's context and output limits, reserved answer space, configured deadline,
and elapsed provider-call time. Recognized rejection codes and parameter names
are included when available. Two derived facts make slow-path failures
attributable: `deadline_reached` says whether the call ran into Eneo's own
deadline, and `upstream_timeout_suspected` is set when a 504 arrived while no local
deadline had expired, which means a proxy or gateway between Eneo and the provider
gave up first; that case is also logged as a warning naming the proxy timeout
as the thing to check, since raising Eneo's deadline cannot fix it. A 502 or
503 is an upstream failure, not a timeout, and is recorded as its status. These are request measurements; a failed call's token usage
remains unknown unless the provider reports it. Prompts, attachment text,
credentials, and raw provider messages are excluded.

A failed turn that ends with an assistant message persists typed attribution in
that message's telemetry (attempts, producers, timing). A terminal turn without an
assistant message leaves a structured log event instead: a known provider rejection
emits `ai_builder.provider.failure` (`schema_version` 1, the provider failure with its
timing, without the proposal attempts), and a failed proposal turn emits
`ai_builder.proposal.failed_turn` (`schema_version` 3, with the attempts). A persisted
snapshot for these turns is V0.2c.
Every correctable failure names the owner of each rule whose feedback it carries
(`parse`, `assembly`, `platform_validator`, `lint`, `critic`, `review_guard`,
`scope_guard`); a merged failure names every contributor, and each failed
proposal attempt records that set as `producers`. Each call record carries the
provider timing measured in the provider-call owner: `first_chunk_ms` (from the
start of that call's own request; absent for a whole, non-streamed answer),
`max_gap_ms` (the longest wait between chunks, the wait the call ended on
included), `provider_elapsed_ms`, and, on a failed call, `local_deadline`
(`silence` or `ceiling` when Eneo's own timer expired, absent for an SDK or
gateway timeout). A request refused for one sampling control and sent again
without it is two call records, each timed from its own request; the shared
ceiling still bounds both. A requirement-classification call record also carries
`classification_outcome`, what its reply was (`resolved`, `no_content`,
`parse_failed`, `output_limit_exceeded`). A reply cut off at the output cap is
asked once more with the identical request, as a second call record, under what
the first ask left of the same ceiling (every request of the first ask counted);
when the re-ask fails at the provider, its failure stays on that record and the
turn keeps the first reply's outcome, so the user is asked to send the message
again. Empty and unparsable replies are not asked again. One owner ends an attempt on a provider failure: it
records the failure on the pending call and closes the attempt in the same step,
so a failed call is never completed afterwards, and it refuses to fail a turn
that has no open attempt. A cancelled turn is not persisted and its open call is
not recorded as failed. The provider-failure log always carries
`provider_elapsed_ms` and `deadline_reached`, `null` when the failure came
before the provider call was timed. The creator-only proposal-telemetry diagnostics project
these fields; records written before them read as empty or absent. The
failed-turn log event is `schema_version` 3.

An accepted create proposal also records what the model declared, before assembly
admitted it, in `planner_telemetry.declared_authoring`: per proposal step its
`uses_form_fields` (after argument normalization: trimmed, de-duplicated) and
`review_mode`, and `review_target`, which covers the structured-result review only: `declared` when
the model named the reviewed step, `inferred` when the server placed the requested
review, and `none` when no structured-result review was requested (a transcript
review can still exist). Every accepted create plan records it: the first attempt,
a repaired plan and a forced continuation. The creator-only proposal-telemetry diagnostics
project it per turn as `declared_authoring`, and the battle bundle's
`journey.plan_outcome.proposal_turns[].declared_authoring` carries the same record.
`null` means not recorded: an edit turn, a record written before the field, or one
that does not read back whole. Only a create turn tells "declared nothing" (empty
lists) from "not recorded". It is evidence for error analysis only; no scorer reads
it.

The AI Builder failure summary reads `builder_sessions`, `flow_runs`, and
`builder_client_errors`. Each section returns at most 20 failure families and
five sample identifiers per family, with `truncated` and `total_families`
exposing omitted families. The Builder section is a current-state snapshot, not
history: it includes sessions updated since the cutoff whose latest turn still
represents a failure. A later successful turn removes a session from this
section, while a later update to a session with a standing failure can make it
appear in a recent window.

Client error reports persist the stable `code`, `category`, and `phase`, plus
`request_id` when available, but never display text. They are deleted when their
session or tenant is deleted, and the daily data-retention worker removes rows
older than 90 days.

### AI Builder request budgets

The selected model contributes two facts to every request: its context window
(`max_input_tokens`, treated as the window that input and answer share) and its
output ceiling (`max_output_tokens`). Nothing else about the model enters the
budget, and no provider or model is special-cased.

Each provider call is allocated once, in two steps, by one owner
(`AIBuilderRequestBudget` in `ai_builder_settings.py`); the allocation made
during preparation is the one the call is sent with, and only a repair call,
which carries new protected content, plans again:

1. The request's required input is measured with the conservative token reserve:
   the scaffold prompt, the tool schemas as the provider receives them and the
   current turn for a proposal, the protected sources and response schema for
   classification, the prompt and schema without excerpts for review. If that input, together with the configured safety buffer, leaves no
   room in the window, the request is refused before any provider work
   (`planner_context_limit_exceeded`). If the required input already exceeds a
   tenant input cap, the same refusal applies.
2. Answer room is reserved from what the required input leaves: the model's
   ceiling when it fits within the configured share of that room, otherwise that
   share. The share (`AI_BUILDER_ANSWER_RESERVE_SHARE`, default one half) is a
   dimensionless allocation policy, not a token count. Optional input
   (conversation history, attachment excerpts, run evidence) is then packed into
   the rest, with truncation marked; the reserve is fixed for the whole packing
   pass, so growing input can never shrink it.

The packed request is measured whole and the model is told it may write the
ceiling within the room that request leaves, never a fixed number and never less
than the reserve. For models whose ceiling is small next to their window
(gpt-4o, Claude, Gemini) this is the full ceiling. For models whose catalogue
metadata declares a ceiling at or above the window (Mistral, Grok, several Azure
and Ollama entries) the request is not refused: half of the room stays free for
the answer and the rest carries input. A request-independent check still refuses
a model whose window does not exceed the safety buffer
(`planner_model_incompatible_token_limits`).

Configured model limits take precedence. Missing limits may come from Eneo's
shared provider-aware LiteLLM metadata resolver; unknown output capacity is never
inferred from the input window. Where a catalogue entry reports an input-only
ceiling rather than the shared window (GPT-5 is one), treating it as the window
is conservative and may leave capacity unused; an administrator who knows the
true window can raise the stored value. Every call kind rejects a
provider answer marked as length-limited as incomplete output: it is neither
accepted nor cached, even when what arrived parses. A tenant review-evidence cap
bounds the complete input of review suggestions and review-backed proposals; it
never consumes any of the answer's room.

Provider-call telemetry keeps the three numbers apart: the model's ceiling, the
reserve kept while packing, and the cap the call was sent.

Upload byte limits protect storage and file processing. Message, collection,
schema, and archive inspection bounds protect their respective API, persistence,
and parsing boundaries. Those limits remain independent of model context size.

### AI Builder MCP tool catalogue

Every prepared Builder message turn, in create and edit sessions alike, reads
the MCP tools of the session's space through the step editor's reader
(`read_space_tool_options` in `flows/application/flow_tool_options.py`), so the
Builder and the editor apply one grant chain. The proposal prompt can carry a
read-only projection of it (`ai_builder_tool_catalog.py`): the usable tools
ordered by server name, then tool name, each with its approved description cut
to the resource description bound and, while classifications are on, the
server's level. A tool is listed when its lines fit what is left of a
6,000-character overview budget; a tool that does not fit is skipped and
counted, and the number left out is stated. Approved input schemas share a
separate 12,000-character budget; a tool whose schema does not fit is listed
with its schema marked as not shown. When the space has usable tools but none
is listed, or the space's list exceeds the editor's list bounds, the prompt says
the catalogue is not shown. Refused tools are not offered; the turn keeps them
with their refusal code for guidance, and names them, within a 2,000-character
budget of their own, by name and refusal code only. The projection holds no
server address or credential: the reader does not read them.

Each tool has a ref (`tool_` and the first twelve hex digits of the SHA-256 of
its server's and its own id; two tools whose refs coincide, which a space does
not have in practice, get none), so a ref is a function of the two ids alone,
the same in every turn, and resolves for every tool of the space, also one the
budgets left out. A proposed step reads a tool through its
`tool_use` (`ai_builder_tool_use.py`): the ref of a tool the prompt names and,
per argument, a fixed JSON value, a run-form field or a field an earlier step's
JSON output declares, that step counted as the proposal lists its steps (in
create through `PlannedStep.proposal_steps`, so a step the assembly adds takes
no number). The step compiler writes the editor's `ToolInputConfig`
from it with the owners other reads use (`form_field_reference_expression`,
`SourceRefBinding.template_expression`), after the earlier-step reference has
passed the declared-field check; a run-form field the argument names and the
form does not have is added in create, typed from the argument's schema and
required when any argument that reads it is, while an edit adds it only through
its `form_fields`. A field the form has is bound only when its type and options
fit the argument's schema and it is required wherever the argument is; the
model is asked for another field name otherwise. An argument whose schema has an
`enum` the run form cannot hold exactly (a padded or non-string value) gets no
field: the model gives a fixed value or an earlier step's field. A tool step's input type is
text. A ref no tool of the space has is sent back to the model; a ref of a
refused tool ends the turn with an answer naming the refusal
(`tool_use_ref_outcome`, before compile). On the final spec,
`prepare_compiled_spec_for_session` runs publish's own argument checks
(`check_tool_configuration` in `flow_tool_publication.py`, which publish raises
through) on every tool step the turn wrote: a missing required argument, an
argument whose name the schema refuses, or a fixed value the schema refuses is
an error the model repairs; a schema no flow
can check ends the turn with an answer; a checker host fault leaves a warning.
An edit writes a saved tool step's tool use and nothing else of it, or removes
the step (a kept step that still reads it is refused by the edit's read check
and sent back to the model); a tool step the edit does not write stays
protected as saved. Every saved tool step's reads keep naming the producer they
named when saved (`kept_step_read_retargeted`), but the tool arguments of a step
whose tool use the edit writes.

The person decides about tools through three question families, whose ids are
built and read only in `ai_builder_tool_question_ids.py`: `tool_relevance`,
`tool_choice:<use_ref>` and `tool_argument:<use_ref>:<tool_ref>:<argument>`,
where `use_ref` is the planner's key for one use of a tool and `tool_ref` the
tool the argument belongs to. A create turn whose space
has usable tools asks `tool_relevance` (use the tools, build without them, show
them first) from `prepare_planner_request` until it is answered with use or
don't use; until a use answer the create step schema offers no `tool_use` and
the prompt lists no tools (`AIBuilderToolCatalogNotOffered`). A create session
whose space has only refused tools is not asked and keeps the listing of the
refused ones, and an edit always offers the tools. After a use answer the
run-input question (`primary_runtime_input`) also offers `no_run_input`:
nothing is uploaded or pasted, and the tools' arguments come from run-form
fields or fixed values. `offers_no_run_input` in `ai_builder_tool_answers.py`
(which reads the answers to the tool questions, for `fold_tool_decisions`
too) holds only in a create session whose latest `tool_relevance` answer is
use and whose person has not chosen no tool for every use they decided.
`situate_question` drops the option wherever it does not hold, the answer
intake refuses the value there (`unsupported_question_value`), the slot
classifier is never offered it, and the planning-state fold (`_resolve_slots`)
ignores a stored no_run_input answer once the predicate no longer holds, so
the question is asked again without the option. The space's catalogue is not
one of the predicate's inputs: the turn's commit (`commit_turn`) rebuilds the
slots from the conversation alone. A commit that reads no run input
(`ArchitectureCommit.reads_run_input` false) is checked on the final create
spec (`_require_no_run_input_read`, the last stage of
`compile_create_intent_to_spec`): a first step that does not read an MCP tool,
or any step that reads the run input other than through the run form's
declared fields, is sent back to the model with the steps named
(`run_input_read_without_run_input`). A plan whose first step reads a tool
gets no main-text field, so a plan that passes has none; the planner prompt of
a create session says the first step reads an MCP tool. A created template-fill
DOCX flow takes no tool step, so in a create session the action policy's
compatibility check (`_architecture_refusal_code`) refuses such a commit before
planning with `unsupported_architecture`, the user-action answer; an edit of a
saved tool flow that fills a template is not refused. An edit reads the value off the saved flow
(`steps_reading_run_input` with the form's declared field names), so a saved
tool flow whose arguments read form fields is not asked about its run
input. A draft's tool uses are then
settled against the decisions before compile (`settle_tool_uses` in
`ai_builder_tool_questions.py`), in create and edit alike: more than 20 uses
end the turn with an answer (`too_many_tool_uses`); a use_ref given twice, or a
use that contradicts the person's choice of tool, is sent back to the model; a
tool whose whole input schema is larger than the catalogue's schema budget, or
a chosen tool whose schema neither the listing nor the decisions show, ends the
turn with an answer. A use the person has not chosen a tool for is asked as
`tool_choice` when another listed tool would serve it too, when its schema was
not in the prompt, or, in an edit, when it is not the saved step's own tool; in
create, the relevance answer is the consent, so a use with one fitting tool
whose schema the prompt showed is not asked. The
question recommends the model's pick (also in an edit: `situate_question`
with `keeps_recommendation_in_edit`), and the use's `evidence_quote` is shown
as why only when the slot classifier's evidence owner finds it in a message the
user wrote unprompted; it never skips the question. An argument the planner
wrote as `ask_user` is asked as `tool_argument`, offering the schema's allowed
values or a typed value, the run-form fields the argument binds to (where the
plan may add a field, a new one whose name no field of the form takes), and the
earlier steps' declared fields of the argument's JSON type whose names a field
path reads whole. Asking ends the turn with the question
(`ProposalNeedsDecision`, persisted by `persist_backend_question` with the
turn's planner telemetry); the draft is not kept. An answer is accepted only
when it picks one option of the showing it answers (`tool_answer_is_valid`), a
typed value only on the fixed-value option. `PlanningState.tool_decisions` is
rebuilt every turn from the conversation (`fold_tool_decisions`) and never
stored; `build_proposal_prepared` reads it again, so a proposal continued from
a stored state after a server decision sees the answers. The last answer per
question id counts against the latest showing, a choice of a tool the space no
longer offers is dropped, an argument's answer fills only the tool its question
named (`arguments_for`), an answer to a question about a tool other than the
chosen one decides nothing, answers for another tool are dropped when a tool is
chosen, an answer this build cannot read as a decision is skipped,
and only the 20 uses and 40 arguments per use answered most recently are kept.
A decided argument replaces the planner's only when it still fits the use's
tool and plan, checked every round, also when the draft leaves the argument
out (a decision for an argument the tool does not declare is not written): a
fixed value with publish's fixed value check (a typed value read against the
argument's schema: text, date and choice arguments as text, others as JSON;
every fixed value, typed or picked, holds only numbers the editor keeps
exactly, `holds_exact_numbers`, and an allowed value that does not is not
offered; an argument no option fits, an enum without one exact value and no
fitting run-form or earlier step's field, ends the turn with an answer,
`tool_argument_values_not_exact`), a run-form
field with the owner compile uses (`run_form_fields_for_tool_uses`, against the
form `create_run_form_fields` builds, or in an edit the form compile reads: the
proposal's or the saved fields with the fields the server owns, projected once
for both), an earlier step's field against the fields the steps before the use
declare. One that does not fit is asked again, never put back. A use that
needs more than 40 decided values ends the turn with an answer
(`too_many_tool_arguments`).
The prompt states the decisions, each value with the tool it was given for,
with the whole approved input schema of each
chosen tool the tool listing does not already show, once
(`decided_schema_refs`, the most recently chosen first within the catalogue's
schema budget). A refusal reaches the web typed: the answer's
text event and its stored `non_plan_outcome` carry `tool_refusal` (tool name,
server name, kind `refused`, `input_schema_invalid` or `input_schema_too_large`,
and the refusal code).

The catalogue is optional prompt content. The request budget is planned from
the prompt without it, so the answer reserve is the same as in a turn without
tools except for the `tool_use` property the step schema then carries, and it is
fitted last, after the replayed requirements, review evidence
and attachments, into the room left for the system prompt; conversation history
above the configured minimum yields to it, as it does to attachments. Its
reductions are tried in order and the first that fits is sent: the refused
tools' names are dropped first, then schemas (the last listed first), then tools
(the last first), then the
list gives way to the "not shown" sentence; when not even that fits, the block
is left out and the turn records the typed `left_out` outcome. The projection
recorded on the prepared turn is the one sent, and the step schema's
`tool_use` offers the refs of exactly the tools it names.

Every Builder provider call goes through one owner
(`ai_builder_provider_call.complete_with_silence_deadline`). The answer is
streamed and rebuilt into the complete completion, so a slow model is
observable while it works. The silence timeout bounds *silence*: the longest
wait for the provider's next yielded chunk once the model has produced output. A
model that keeps yielding is not cut off by that deadline however long its answer
takes, while a stalled stream is still detected. Before its first output (chunks
that carry none, such as a role-only opening, do not count) a hung call cannot be
told from one that is thinking without streaming its reasoning. A call that may
think therefore waits for the response and that output up to the call ceiling
below: it sends a reasoning effort other than `none`, or sends no effort on a route
that takes one (the provider's default then applies, so a reasoning route that is off
by default waits longer on a hung call too). Any other call waits only the silence
timeout. The provider SDK's own read timeout is set to the ceiling, behind these
local deadlines. The call ceiling bounds the whole call, whether it keeps
producing or, for a call that may think, never produces; it is policy of its own
and never below the silence timeout. Neither is the send-lock lease, which the
turn renews while it works.
The deployment sets the defaults (`AI_BUILDER_PROPOSAL_TIMEOUT_SECONDS`, 300,
and `AI_BUILDER_PROVIDER_CALL_CEILING_SECONDS`, 1800); an admin overrides
either in Admin > Flow settings as `flow_settings.ai_builder.silence_timeout_seconds` and
`call_ceiling_seconds` (each a positive number of whole seconds). An absent key
follows the deployment default, including a later change of it. Three ordering
rules hold for the effective values, whichever side set each: the silence
timeout, and a classification timeout the deployment sets, may not exceed the
call ceiling, and a classification ceiling the deployment sets lies between the
classification silence timeout (the silence timeout unless the deployment sets
one) and the call ceiling. Deployment startup checks them on the env values; the
settings write refuses a change that breaks one, and a turn whose effective
values break one (the deployment lowered its ceiling under a tenant's silence
timeout) is refused until an admin repairs it. The API error names both values and
where each comes from; the web Builder shows a fixed "settings are invalid"
sentence, so the values appear only in the API response. An explicitly configured
`AI_BUILDER_CLASSIFICATION_TIMEOUT_SECONDS` overrides the silence deadline for
classification, whose wait before its first output is bounded by its own ceiling
below only for a call that may think; leaving it unset restores inheritance. Classification has a
whole-call ceiling of its own, shared by its ask and its one re-ask after a
cut-off answer: `AI_BUILDER_CLASSIFICATION_CEILING_SECONDS`, by default twice
its silence deadline and never above `AI_BUILDER_PROVIDER_CALL_CEILING_SECONDS`.
A classification answer is bounded by the model's output limit and the room its
request leaves, like every other Builder call, unless
`AI_BUILDER_CLASSIFICATION_ANSWER_CAP_TOKENS` sets a cost cap. When the turn
sends a reasoning effort, classification sends the lowest level below it that
the model offers and the route can send, so it never reasons more than the
turn, unless `AI_BUILDER_CLASSIFICATION_REASONING_EFFORT=turn` keeps the
user's. Model
context capacity does not establish provider processing speed, so the deadlines are
deployment defaults that an admin may override. A proxy between
Eneo and the provider that closes idle connections must allow at least this
silence, and for a call that may think the whole-call ceiling for its first
output; see the failure telemetry above for how such a
timeout is recognised (`local_deadline` names the timer that expired, silence
or ceiling, when one did). The same two facts, with the limit in seconds as
`deadline_seconds`, are in the details of the public error the user receives, so
the Builder can say that the model took too long and which limit to change.

A turn that no longer owns its session stops its provider work at once. The
send lease mints one gate per turn that every provider call of the turn goes
through: it admits each request (a lease-guarded write) and carries two
signals. *Ownership lost* is set only when the session is confirmed to be no
longer the turn's, and stops the work in flight; *lease lost* is set whenever
the lease can no longer be trusted (that loss, or a refresh that failed) and
is read only by the planner's post-dispatch result fencing: a server
decision's result is not emitted once it is set. Proposal results are fenced
by the lease-guarded writes, not by this signal. Three bounds are kept
apart:

- *Stopping work.* Besides the lock-extending refresh (a third of
  `AI_BUILDER_SEND_LOCK_LEASE_SECONDS`), the send lease runs a read-only
  ownership probe every 2 s that waits at most 5 s for its answer. When the
  probe, or a refresh, finds the row is no longer this turn's (the session was
  cancelled, or another turn took the lock after the lease ran out), every wait
  of the call in flight, for the first response and for each chunk, ends and
  the stream is closed. While probes answer, a loss is noticed within
  `SEND_OWNERSHIP_LOSS_DETECTION_SECONDS` (one probe interval plus two probe
  waits, 12 s at the defaults: a probe that read the row just before the loss
  may still answer "owned" at the end of its wait, and the next probe follows
  an interval later), assuming a timed-out probe's cancellation ends promptly;
  the stream then closes within its own close bound (1 s). A probe that fails
  or times out proves nothing; it is tried again, so a database hiccup cannot
  cancel healthy work, but probes that keep failing give no finite detection
  guarantee: only a refresh that finds the row gone confirms the loss then.
  The turn's first probe failure is logged in full, later ones as a summary at
  most once a minute. Each outbound request, a replacement sent without a
  refused sampling control included, is admitted through the gate right
  before it is sent, so no request leaves after the loss is known; the
  admission is the turn's own wait, so the silence deadline, the call
  ceiling and the call's timing start only once a request is admitted, and
  a refused admission is the turn's own error, never a provider failure. The
  stopped call is not a provider failure and is not recorded as one; it
  leaves one `ai_builder_provider_call_stopped` log line (session, request,
  call kind, model, and the provider time of the last request sent, absent
  when none was sent). Accounting the abandoned call in the
  turn's usage totals is left to the aggregate turn budget (V1.9a-3).
- *Ending the stream.* The turn then ends with `session_send_lease_lost` and
  `done`, after the turn's cleanup below.
- *Releasing ownership.* The cleanup is shielded from a client disconnect and
  bounded at 30 s. It spends at most 5 s in all stopping the heartbeat (half
  for a beat in progress to finish, the rest for a cancelled one to end), so a
  refresh stuck on the database cannot hold the release; a heartbeat task
  that ignores its cancellation is logged by name and kept referenced until
  it ends. The cleanup then clears the row if it is still this turn's. When
  the database cannot release it within the bound, the lock is left to its
  lease, which the next claim recovers from.

These probe, drain and release bounds are mechanism constants of the send
lease, not tenant policy. A cancelled call may still complete and bill at the
provider. Server-side orchestration between provider calls is still fenced by
the lease-guarded writes and the post-dispatch result fencing, not stopped
mid-await.

A stream that ends without a terminal finish reason is an incomplete answer
with an unknown provider outcome, even when what arrived parses; it is never
accepted and never retried by the call itself. Usage keeps its provenance:
the rebuilt answer carries the usage the provider itself sent, combined
across its chunks as running totals (a provider may report input tokens in
its first event and output tokens in its last), and none when the provider
sent none, so the existing estimate contract applies; the SDK's own recount
never passes as the provider's.

A provider that refuses the request while it is being established, before
any stream is acquired, because of one optional sampling control (a 400 naming
`temperature`, `top_p`, `reasoning_effort` or another control from the
capability snapshot as unsupported) has done no work. When the caller admits
one more request, the owner sends the call once more without that control,
which is the provider's default, under the same ceiling, and logs the refusal
as evidence that the persisted capability snapshot is wider than the route
(LiteLLM's discovery lists the controls it maps, not the values a deployment
accepts; the observed case is an Azure `gpt-5.6` deployment that accepts only
the default temperature and for which LiteLLM's `drop_params` keeps the
value). The caller charges the second request to its own call budget and
records the refused one as a failed call. A refusal after a stream was
acquired, a refusal of anything else, or a second refusal is raised.

Expiry stops the local wait and closes the stream; remote work may continue.
SDK retries are disabled, so nothing repeats provider work. The turn retains
its unknown-outcome state and requires acknowledgement before another provider
call. HTTP 400 rejections should be investigated using the rejection fields
and request budget; increasing the deadline does not resolve an invalid
request.

## Retention and deletion

Flow run history uses a complete `{mode, days}` policy resolved from Flow, then
Space, then Organization. A child either inherits the complete parent policy or
replaces both fields. The most specific policy wins, so a Flow may deliberately
retain history longer than its Space or Organization default. Dedicated Flow
policy columns keep this independent from `Spaces.data_retention_days`, which
continues to govern conversations and App runs.

The current modes mark history for a later explicit administrator workflow:
`preserve` makes aged history eligible for manual purge, while
`review_required` places it in a read-only human-review queue. Neither mode
schedules deletion, and saving or reading a policy never deletes data. A future
purge path must retain parent ownership and foreign-key safety, block on pending
or dead-lettered audit delivery, and produce an immutable audit receipt. There
is no classification policy plane or retention tombstone.

## Tenancy and audit invariants

- Every repository operation proves `tenant_id`; identifiers alone are never an
  authorization boundary.
- Space-scoped access is resolved before mutation.
- Mutations write the required audit entry in the owning transaction.
- Lifecycle audit is durable outbox state and is not disabled by tenant feature
  flags.
- Parent rows are locked before active child mutation, preventing work from
  reopening after terminalization.
- Public failures are typed and sanitized; persisted evidence holds bounded
  diagnosis without secrets.

## Final schema baseline

Core Flow schema is created by three squashed revisions:

1. core Flow baseline `202608201000`;
2. core follow-up `202608201100`;
3. stacked Builder baseline `202608201200`.

The core baseline creates 19 Flow tables. Builder adds three authoring-session
tables on its stacked branch. Do not reintroduce the historical migration churn
or a second definition of the final schema in tests or prose.

## Change review checklist

For every Flow change, verify:

1. the owning layer and core/Builder boundary are unchanged or deliberately
   revised;
2. every query and mutation remains tenant-scoped;
3. mutation audit and lifecycle-outbox behavior remain atomic;
4. dispatch/recovery remains generation-fenced and idempotent;
5. runtime reads only the immutable published definition;
6. behavioral tests cover success, denial, conflict, and retry/recovery paths;
7. docs describe behavior rather than restating enums, tables, or indexes.

The final tidy plan and its review report carry measured suite, migration,
process, and mutation evidence. This page owns the durable architecture, not a
copy of those changing metrics.
