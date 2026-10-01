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
ceiling still bounds both. One owner ends an attempt on a provider failure: it
records the failure on the pending call and closes the attempt in the same step,
so a failed call is never completed afterwards, and it refuses to fail a turn
that has no open attempt. A cancelled turn is not persisted and its open call is
not recorded as failed. The provider-failure log always carries
`provider_elapsed_ms` and `deadline_reached`, `null` when the failure came
before the provider call was timed. The creator-only proposal-telemetry diagnostics project
these fields; records written before them read as empty or absent. The
failed-turn log event is `schema_version` 3.

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

Every Builder provider call goes through one owner
(`ai_builder_provider_call.complete_with_silence_deadline`). The answer is
streamed and rebuilt into the complete completion, so a slow model is
observable while it works. `AI_BUILDER_PROPOSAL_TIMEOUT_SECONDS` (default 300)
bounds *silence*: the longest wait for the provider's next yielded chunk, the
first one included. A model that keeps yielding is not cut off by that
deadline however long its answer takes, while a dead connection is still
detected; reasoning models can be silent for minutes on large prompts before
their first token, which is what the default allows for.
`AI_BUILDER_PROVIDER_CALL_CEILING_SECONDS` (default 1800) bounds the whole
call, however much it keeps producing; it is policy of its own and never below
the silence deadline. Neither is the send-lock lease, which the turn renews
while it works. An explicitly configured
`AI_BUILDER_CLASSIFICATION_TIMEOUT_SECONDS` overrides the silence deadline for
classification; leaving it unset restores inheritance. Model context capacity
does not establish provider processing speed, so deadlines are deployment
policy. A proxy between Eneo and the provider that closes idle connections must
allow at least this silence; see the failure telemetry above for how such a
timeout is recognised (`local_deadline` names the timer that expired, silence
or ceiling, when one did).

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
