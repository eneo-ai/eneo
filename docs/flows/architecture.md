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
- simple Flow → Space → Tenant retention-day inheritance;
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
| Retention policy | `flows/flow_retention_policy.py` and retention service |

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

## Retention and deletion

Retention is a single effective number of days resolved from Flow, then Space,
then Tenant. Cleanup follows parent ownership and database foreign keys. Pending
or dead-lettered audit delivery blocks deletion so required audit state is not
lost. There is no separate classification policy plane or retention tombstone.

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
