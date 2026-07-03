# Peer Loop Brief: Fable 06 Runtime Reliability + Maintainability

## Decision Under Review

Run a single Fable max-effort pass next, starting with runtime reliability plus runtime-coupled maintainability ownership for Eneo Flows.

## Why This Scope

The user asked whether Fable 05-08 should be retried and suggested runtime reliability together with maintainability. The best next spend among 05-08 is Fable 06 because it covers production failure modes and long-term maintainability at the runtime boundary:

- run lifecycle;
- step lifecycle;
- Celery task boundaries;
- idempotency and duplicate starts;
- crash recovery;
- stale queued/running recovery;
- terminalization;
- audit/webhook outbox and dead-letter;
- review checkpoints and reruns;
- retention/purge;
- operator debugging;
- ownership boundaries between runtime tasks, services, repos, terminalizers, and policies.

## Current Fable State

Completed:

- Fable 01 proposal repair boundary;
- Fable 02 compiler/topology/runtime contracts, underlag, RAG;
- Fable 03 planning state/JSONB/persistence scale;
- Fable 04 discovery/attachments/dialog cadence.

Quota-limited/no review content:

- Fable 05 API consumer DX;
- Fable 06 operational runtime reliability;
- Fable 07 evidence/legal transparency;
- Fable 08 dead-code/deletion audit;
- Fable 09 security/tenant boundaries.

## Proposed Prompt Revision

Create `fable-06-operational-runtime-reliability-maintainability-prompt.md` and run it with Claude Fable, max effort, saving output directly to:

`fablereview/2026-07-03-eneo-flows-ai-builder/fable-06-operational-runtime-reliability-maintainability-review.md`

The revised prompt should improve the old Fable 06 prompt by adding:

- explicit runtime owner map for lifecycle concepts only;
- crash/idempotency ownership boundaries between task, service, repo, terminalizer, policy, and outbox code;
- Ponytail delete/merge/reuse pressure only where it reduces runtime reliability complexity;
- change-path analysis for common runtime changes;
- "do not propose workflow engine rewrite";
- "do not preserve compatibility for pre-production behavior without evidence";
- behavior-test requirements focused on actual crash/retry/idempotency failure modes.

The prompt deliberately does not perform the broad dead-code/deletion audit reserved for Fable 08.

## Main Question For Claude

Given the user asked to choose among 05-08 and suggested runtime reliability plus maintainability, is the revised Fable 06 runtime reliability prompt focused enough to run now? Challenge whether it is still too broad, whether it should be split, and what Ponytail would delete/simplify in the prompt itself. Note that security/tenant boundaries remains the documented global priority outside 05-08.

## Desired Outcome

Either green-light the revised Fable 06 run under the user's 05-08 framing, or recommend one smaller edit before spending Fable quota.
