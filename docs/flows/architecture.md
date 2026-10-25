# Flow architecture

This is the maintainer map for the final Flow implementation. Start with the
[developer quickstart](./flow-developer-quickstart.md) for the data model and
[package layout](./package-layout.md) before moving root-level modules.

## Product boundary

Core Flows owns authoring, immutable published versions, execution, review,
evidence, packages, retention, and operations. A flow is authored in the editor
or from its authoring chat, an ordinary assistant chat whose loopback tools
change the same draft through the same authoring operations. Neither path owns a
second runtime or schema interpretation.

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
| Authoring chat | `flow_authoring_chats` | One per user and flow: an ordinary conversation and hidden assistant bound to the flow, with an edit-mode switch. |

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
| Editor and authoring chat changes | `flows/application/flow_authoring_operations.py` |
| Step move, insert and remove | `flows/application/flow_step_structure.py` |
| Authoring chat and its tools | `flows/application/flow_authoring_chat.py` and `internal_mcp/flows.py` |
| Publish validation | `flows/flow_validators.py` |
| A step's reads, by channel | `flows/step_lineage.py` |
| Flow suggestions | `flows/domain/flow_suggestions.py` and `flow_suggestion_*.py`, `flows/application/flow_suggestion_service.py` |
| Applying suggestions | `flows/application/flow_suggestion_apply.py` on `apply_editor_update` |
| Suggestion evidence (numbers from runs) | `flows/infrastructure/flow_suggestion_evidence_repo.py` |
| Forwarding facts | `flows/runtime/forwarding_facts.py` and `forwarding_capture.py` |
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

The maintenance worker schedules six Flow crons (reconcile stale running runs,
expire review checkpoints, redispatch stale queued runs, drain retired runs,
deliver lifecycle audit outbox rows, and request webhook delivery) and runs one
Flow task, the webhook outbox job, which those requests and a run that ends in
a webhook enqueue. ARQ configuration, queues,
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

## Authoring

The editor and the authoring chat are two front ends over one authoring path.
The REST authoring routes delegate to `flow_authoring_operations.py`; the editor
route (`PATCH /api/v1/flows/{id}/editor/`) applies flow settings, step edits,
new steps and a new step order in one revision, fenced on `expected_revision`.
The authoring chat (`POST /api/v1/flows/{id}/authoring-chat/`) is an ordinary
conversation with a hidden assistant whose tools come from Eneo's loopback
`flows` server and reach only that flow. Every tool that changes the draft calls
the same operations (`apply_editor_update`, `publish_flow`, `unpublish_flow`) on
top of `FlowService`, so access checks, revision fencing, classification,
snapshots and audit are the editor's. The chat starts in view mode: its writing
tools are refused until the user turns edit mode on, and the mode switch is
itself fenced on the draft revision.

Moving, inserting and removing steps goes through `restructure_steps`: the
`step_N` aliases a kept step reads (in its bindings, interpolated configuration
and prompt) follow their producers, and a change that removes a step another
step reads, or moves it after that reader, is refused with
`flow_step_read_lost_producer`.

Both front ends list a tool step's options through one route: the editor's
`GET /api/v1/flows/{id}/tool-options` and the chat's `read_tool_options` both
read `FlowService.list_tool_options`, which applies the space's grant chain
(`flow_tool_options.py`). Publish runs `check_tool_configuration`
(`flow_tool_publication.py`) on every tool step.

Publish is where the rules about what a step may read hold, whichever path wrote
the draft; the [developer quickstart](./flow-developer-quickstart.md#how-data-moves-between-steps)
lists them. Flow packages author through `flow_authoring_command.py` and draft
materialization, which lower a `FlowDraftSpecCore` into the same draft rows and
meet the same publish.

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

Core Flow schema is created by two squashed revisions:

1. core Flow baseline `202608201000`;
2. core follow-up `202608201100`.

The core baseline creates 19 Flow tables. Revision `202608201200` and its
follow-ups added the tables of a dedicated builder that has since been removed
(its sessions, plans, session files and client error reports); `202610212200`
drops them together with that builder's two role permissions. Do not
reintroduce the historical migration churn or a second definition of the final
schema in tests or prose.

## Change review checklist

For every Flow change, verify:

1. the owning layer is unchanged or deliberately revised, and the editor and
   the authoring chat still change a flow through the one shared authoring
   path;
2. every query and mutation remains tenant-scoped;
3. mutation audit and lifecycle-outbox behavior remain atomic;
4. dispatch/recovery remains generation-fenced and idempotent;
5. runtime reads only the immutable published definition;
6. behavioral tests cover success, denial, conflict, and retry/recovery paths;
7. docs describe behavior rather than restating enums, tables, or indexes.

The final tidy plan and its review report carry measured suite, migration,
process, and mutation evidence. This page owns the durable architecture, not a
copy of those changing metrics.
