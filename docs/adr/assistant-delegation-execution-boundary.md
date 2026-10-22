# Assistant delegation execution boundary

- Status: local delegation implemented; integration/visual deployment checks required before release
- Date: 2026-10-20
- Scope: #1150, #1151; mechanical prerequisite #1155
- Baseline: `db8d37d048cf9083ccbda941d996aa10d8441792` (`develop`)

## Problem and decision

A specialist must retain the same model, instructions, Skills, knowledge and
tool policy when another assistant consults it. Calling the public ask method
as a tool would also create a normal user message and complete its answer.
That is the wrong lifecycle for a consultation within one parent turn.

Keep execution in `AssistantService` and its existing `Assistant.ask` →
`CompletionService` → tenant-model adapter path. Separate request preparation
and execution from the ordinary conversation's persistence lifecycle. Build
delegation as a local function in that existing model/tool loop, following the
local Skill activation precedent. Continue to use the current MCP proxy and
loopback servers for specialist knowledge, files and built-in providers.

Do not introduce a second model loop, a separate assistant server, or a generic
agent framework. Do not expose the preparation boundary as a public API or
persist a prepared turn as an authorization grant.

This decision is about **assistant-to-assistant execution**. It does not replace
MCP for existing tools or change their transport and administration.

## What the existing code actually provides

| Owner | Reused responsibility | Missing for delegation |
| --- | --- | --- |
| `assistants/assistant.py` (`specialists`) | The assistant's configured specialists in its Space | Multi-consultation synthesis driven by the asked assistant |
| `assistants/assistant_service.py` | Caller authorization, governance, Skills, classification, effective tools, normal history lifecycle | Parent/child lifecycle and authorization before each later handoff |
| `assistants/assistant.py` | Configured assistant execution and knowledge retrieval | Shared run limits supplied by the caller |
| `completion_models/infrastructure/adapters/tenant_model_adapter.py` | Provider calls, tool iteration, local Skill functions, usage and progress | A budget shared by parent and child invocations |
| `internal_mcp/foundation.py` | Scoped JWT, user-bound container and per-request transaction | Parent run identity, shared budget, cross-request cancellation and child approvals |
| `sessions/session_service.py`, questions | Short, independently committed placeholder and completion writes | Ordered specialist questions, actual replies, status and sources under the parent |

The normal session writer already uses short independent transactions. The
problem is not that every current ask holds an uncommitted placeholder. The
loopback tool context *additionally* wraps the whole tool in `session.begin()`;
putting a multi-round assistant there would extend that transaction over
nested provider/tool work. Reuse the short-write persistence pattern.

There is a second transaction boundary to settle before enabling delegation:
the service and completion-provider lookup use the request's injected database
session. Extracting methods does not close that transaction. The executable
proof must demonstrate short preparation/commit scopes around provider work
rather than claiming this refactor alone establishes them.

## Transport alternatives

| Choice | Benefit | Cost and operational consequence |
| --- | --- | --- |
| Existing stateless HTTP loopback | Existing tool catalog, JWT and MCP plumbing | Each request creates a new server context; another worker may serve it. A mutable run budget or cancellation scope cannot be passed as a Python object. New trusted run context and coordination would be required. The current one-outbound-call contract also excludes multi-round assistants. |
| Local function in the existing completion loop | Same task lifetime and explicit shared run state; existing assistant execution remains canonical | A small typed delegation function and result mapping must be added alongside the existing local Skill function dispatch. |
| Separate MCP agent service/framework | Independent deployment and scaling | Duplicate or remote policy/configuration resolution, another lifecycle and deployment to operate; no demonstrated need in the first delivery. |

Select the local function for the first delivery. A tool-shaped model interface
does not require an HTTP server. Local Skill activation already establishes
that distinction in this codebase.

Revisit an independently operated assistant endpoint only if there is a concrete
cross-service consumer or isolation/scaling requirement. Before then it must
have a durable run identity, bounded reservations, cancellation behavior across
workers, idempotency for side effects, and a tested approval/persistence contract.
No fallback transport or unused plugin interface is added now.

The SDK's [stateless request handler at v1.30.0](https://github.com/modelcontextprotocol/python-sdk/blob/v1.30.0/src/mcp/server/streamable_http_manager.py)
creates a new server/transport for every request, including notifications.
`backend/scripts/probe_loopback_cancellation.py` reproduces the consequence with
two concurrent in-memory HTTP requests: start a tool, send
`notifications/cancelled` for its request ID, wait up to 0.5 s for the tool to
stop, then observe whether it did. It releases and joins all work before
exiting. The probe measures
protocol notification behavior, not TCP disconnect behavior or production
load-balancer cancellation.

Observed with the lockfile's MCP **1.30.0**: the cancellation notification
returned HTTP 202, the original tool was still running, and it subsequently
returned HTTP 200 with its normal result when released. The initial check used
the workstation's older 1.28.1 environment; the result was then reproduced in
an isolated 1.30.0 environment without modifying that shared environment.
Neither result establishes a safe cancellation contract for nested assistant
runs over the existing stateless endpoint.

Run from `backend` in the project environment, which uses the MCP version
pinned in `backend/uv.lock`:

```sh
uv run --no-sync python scripts/probe_loopback_cancellation.py
```

## Implemented execution and persistence contract

`AssistantService` remains the canonical owner of assistant preparation and
execution. `AssistantDelegation` exposes one typed local function to the parent
adapter; specialists receive no delegation function. The adapter reuses its
existing Skill and MCP tool loop. Loopback knowledge/files and the MCP proxy
remain the tool transport, including tools nested under a specialist.

The plan binds the interactive caller, tenant, Space, orchestrating assistant,
its specialist IDs and permitted attachment IDs on the server. The orchestrator
is the assistant that received the question; its specialists are persisted in
`assistants_specialists` and must belong to the same Space. Candidates are
resolved before any history row is written: a specialist the caller may not
use is left out without exposing its name, the root learns only how many are
unavailable, and a question with no usable specialist is refused up front. Each later model,
query-embedding, reranking and MCP boundary rechecks current access/configuration in a short
transaction. The parent is checked again before receiving specialist evidence.
Changes to user eligibility, the specialist list, effective model, prompt,
Skills or tool configuration stop the affected execution. Prepared values are not
persisted authorization grants.

The ask returns a lazy execution stream from the request's preparation
transaction. Provider and retrieval repositories own short reads when there is
no ambient transaction. Model and MCP calls happen after those scopes exit.
Non-streaming HTTP requests drain the same execution, so they cannot bypass the
specialist's ordinary streaming tool loop.

`ExecutionBudget` is one context shared across the root and its serial children.
It bounds consultations, model requests, the size of a single request, local
tool dispatches, model output and total/child time; the limits come from the
`ORCHESTRATION_*` settings. Request size is an admission limit per request, not
a sum over the turn: every round re-sends the conversation, so a cumulative
input counter would cap a long conversation at a few rounds regardless of the
model's window. Part of the model-request, output and time budget is reserved
for the root's final synthesis; a child cannot start or continue on it, and a
consultation refused for that reason is reported to the root as incomplete so
the turn still ends in an answer that names its gaps. Waiting for a user's tool
approval pauses the registered deadlines. MCP transports still enforce their
own per-call limits. Provider work inside an HTTP MCP request, including Eneo's loopback
leaf tools, is not separately charged to these in-process counters: the shared
budget admits the tool dispatch, and its existing server-side limits apply.
Distributed provider accounting is not implemented by passing Python context
across HTTP. No child
can recursively delegate. Tool approval uses the parent's session and existing
approval manager; cancellation closes child generators before proxy cleanup and
partial history saving. Already completed remote side effects are not undone.

The parent Question owns a nullable versioned `consultations` JSONB column.
Snapshots retain actual questions/replies, statuses, sources and server-generated
step UUIDs. Provider IDs are only round-local and cannot identify history steps.
Raw tool results are fetched through the existing authorized result endpoint;
public events/history strip them and do not include specialist reasoning.
Existing file persistence links generated specialist files to the parent.

Question token columns retain the root model's usage. The shared usage SQL
projection adds executed consultations with their own model IDs; public chat
usage totals sum both. This avoids billing all specialist work at the root
model's rate. Unexecuted consultations contribute no model row.

## Configuration, compatibility and rollout

Specialists are a setting on the assistant, next to its knowledge and tools.
An assistant with specialists orchestrates whenever its effective model can
call tools; without such a model it answers on its own and the editor says so.
Specialists are consulted without their own specialists (depth one), so there
are no cycles and no nested budgets. The table `assistants_specialists` rejects
a self-reference; deleting a specialist cascades the link and moving an
assistant to another Space drops its links in both directions.

Group chats are retired by the follow-up migration `202610221200`: every group
becomes an assistant with the same id and its members become that assistant's
specialists, sessions move to the assistant, and the group tables are dropped.
The old `/group-chats` API answers 410. Shared-Space default assistant
orchestration and API-key execution are separate decisions that build on this
one.

The migration adds the specialists table and a nullable consultation column on
questions; it does not rewrite existing assistants or question history. A
database downgrade drops consultation history and the specialist links, so
export them before deliberately downgrading. Deploy the migration before the
new backend and ship the matching client that renders consultation events.

The Svelte client leads with the synthesis and provides collapsed specialist
steps with nested tool results. Blocking approvals stay outside that collapsed
trace. The beta client is outside this implementation scope; API v3 publishes
the data part for a future renderer.

## Validation boundary

Focused tests run the actual assistant preparation, actor checks, model context,
Skill activation, tool loop, MCP proxy, response protocol and history projection.
Database/outbound provider boundaries are substituted in local unit tests;
PostgreSQL JSON expansion has an integration test for CI. The loopback transport
probe above remains the evidence for choosing local delegation.

These checks do not establish live-model routing quality, production transport
behaviour, a visual browser review or applied migration correctness in a running
environment. No local application server, browser suite or production build is
required for the focused proof. Run deployment integration checks and review the
rendered chat before release.
