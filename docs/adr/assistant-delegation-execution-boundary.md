# Assistant delegation execution boundary

- Status: proposed transport decision; preparation/execution separation implemented
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
| `group_chat/application/group_chat_service.py` | Membership, mentions, conversation entry | Explicit orchestrator configuration and multi-consultation synthesis |
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

## Security and lifecycle requirements for the next slice

The current refactor does not claim these delegation requirements are delivered:

- Bind caller, tenant, space, parent turn and permitted candidates on the server.
  Recheck each candidate with the existing space actor. Group membership alone
  is not a substitute for permission to use a specialist.
- Apply the effective space classification to the parent model, child model,
  retrieval providers and tool providers. Recheck before evidence is given to
  the parent; summarization does not reduce the requirement.
- Share limits across all parent and child model/tool work and bound the total
  duration and context/output. `MAX_TOOL_ROUNDS` currently resets for every
  adapter invocation, so it is not a run-wide budget.
- Keep one active specialist and no recursive delegation initially.
- Propagate caller tool opt-outs. The current approval-wait mechanism is in the
  streaming path; a child called with `stream=False` must not silently lose the
  parent's approval requirement. Either carry approval events through the
  parent or explicitly deny those operations before enabling delegation.
- Use typed success, denial, timeout, cancellation and incomplete outcomes.
  Cancel local child work when the parent stops; remote completed effects cannot
  be rolled back by cancellation.
- Persist each actual subquestion/reply and its source identity once beneath
  the parent. Use existing question/tool-step persistence if it can represent
  the contract without overloading unrelated fields. Decide this in the proof,
  before any migration or UI implementation.
- Lead the UI with the synthesized answer; retain expandable authorized steps.
  Reopening history must not regenerate specialist replies.

## Smallest reviewable implementation

The first code change stays in `AssistantService`:

1. `_prepare_turn` resolves authorization, effective configuration, Skills,
   classification and tool opt-outs before creating conversation records.
2. `_execute_turn` attaches the existing tools and calls `Assistant.ask`.
3. `ask` retains ordinary session creation, placeholders, response persistence,
   streaming and failure-state ownership. Its failure handler now also sees
   tool/loopback setup errors raised inside `_execute_turn`; before the model
   call the Skill snapshot is unchanged, so that handler only re-raises them.

The typed request-local prepared value connects those phases. Code is moved
within its canonical owner; policy/configuration resolution is not copied.
Nothing is enabled in group chats, no new endpoint or database schema is added,
and the shared-space default assistant keeps its existing behavior.

Acceptance for this mechanical slice: ordinary new/resumed asks keep their
answer, source, usage and history contracts; preparation performs no model call
or conversation write; denied access/classification fail before those effects;
tool opt-outs and local cancellation remain effective.

## Validation and remaining evidence

The focused tests use real `Assistant`, `Space`, actor checks, context building,
`CompletionService` and `TenantModelAdapter`, replacing database repositories
and the outbound provider. They prove the extraction's runtime behavior, not
database commit semantics, a distributed transport, live-model synthesis quality
or the full #1151 delegation proof.

From `backend`, with an existing synchronized environment:

```sh
uv run --no-sync pytest -q \
  tests/unit/assistants/test_assistant_turn_preparation.py \
  tests/unit/assistants/test_assistant_service_attachment_references.py \
  tests/unit/assistants/test_assistant_service_builtin_providers.py \
  tests/unit/test_group_chat_selector_repro.py
```

Before enabling group-chat orchestration, #1151 still requires its
procurement → IT → IT-follow-up proof through the real model/tool loop, shared
budget exhaustion, parent/child cancellation, classification changes, approval
behavior and round-trip persistence. Follow with focused integration checks in
CI or an explicitly authorized environment; do not infer those results from
unit tests.

## Risk and recovery

The extraction touches the ordinary ask path, so lost configuration or a changed
history write order is the primary regression risk. Keep its diff separate from
delegation behavior. It can be reverted without migrating stored conversations.
Later run/step persistence and rollout changes need their own recovery plan.

The intended result is one execution owner with two explicit lifecycles:
ordinary user turns and bounded specialist consultations. No duplicate runtime,
policy algorithm or legacy routing fallback is created in this first slice.
