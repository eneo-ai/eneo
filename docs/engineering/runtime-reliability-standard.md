# Runtime Reliability Standard

## Purpose

This document owns reliability rules for work that crosses a request/database,
database/broker, worker/process, provider, remote-effect, or
retention/deletion boundary. It defines guarantees and questions to answer; it
does not mandate a framework or one storage shape for every lifecycle.

The central rule is simple:

> Commit the local intent and state needed for recovery before unreliable work,
> then describe external guarantees honestly.

Exactly-once language applies only to committed local logical effects unless a
broker, provider, or remote system supplies a verified stronger contract.

## Lifecycle contract

Every changed lifecycle must account for:

- canonical persisted owner;
- legal, failed, and terminal states;
- transition precondition and competing-writer protection;
- transaction boundary and safe checkpoints;
- broker, provider, or remote-work boundary;
- retry eligibility, identity, budget, and exhaustion;
- process-crash and restart behavior;
- duplicate, stale, and outcome-unknown behavior;
- operator-visible diagnosis, audit, and metrics;
- retention, purge, and finalization consequences.

Use the smallest mechanism that enforces the real invariant. Depending on the
contention and boundary, that may be a uniqueness constraint, compare-and-swap,
row lock, lease, revision, explicit state transition, or concrete outbox. Do not
add all of them by default.

## Persisted state and transitions

- One persisted lifecycle owner or bounded typed aggregate is authoritative.
  Worker memory, task arguments, caches, logs, and metrics are not.
- Durable intent is committed before unreliable work when it must survive the
  initiating request or process.
- Queue tasks carry small typed identity and revision or generation metadata,
  not authoritative business state or large payloads.
- A transition has one owner and one transaction boundary. Competing writers
  use database enforcement appropriate to the race.
- Terminalization is idempotent. Repeating it cannot recreate active work,
  duplicate terminal effects, or move a terminal record backward.
- Immutable executable input is verified before use. Runtime code does not use a
  model or repair layer to reinterpret invalid published state.
- A checkpoint earns its transaction only when committed progress is safe and
  useful after process death. Do not split transactions merely to appear
  durable.

General relational-versus-aggregate persistence and migration rules live in the
[Maintainability Standards](maintainability-standards.md#persistence-integrity).

## Broker dispatch

Assume broker delivery is at least once. Duplicate, delayed, reordered, and
stale messages are normal inputs.

- Commit the durable work record before broker send.
- Keep every committed dispatch intent durably discoverable until a worker can
  claim it. Close the commit-to-send gap with the queued work record plus an
  owned recovery dispatcher, or with a concrete transactional outbox when no
  existing work record can own recovery. A direct broker send alone is
  insufficient.
- The worker claims work using durable identity and, when the lifecycle can
  re-enter a queued state, the relevant revision or queue generation.
- Reuse an existing revision when it already distinguishes queue generations;
  do not add an epoch column by reflex.
- Reject stale or duplicate delivery through persisted state and database
  enforcement.
- Give retry eligibility one canonical persisted clock. Generic `updated_at`
  does not own scheduling semantics.
- Persist enough bounded current diagnosis to operate the lifecycle: attempt
  count, last attempt, sanitized failure category, next eligibility, and
  exhausted or terminal outcome when applicable.
- Broker acceptance followed by a local acknowledgement failure can produce a
  duplicate delivery. It is not proof of exactly-once dispatch.
- Persist retry exhaustion and resolve it through the existing terminal owner or
  an explicit operator-visible state. Do not leave exhaustion in logs only.

Do not add a dispatch outbox when the existing queued database row already is
the durable work record and a recovery scanner can safely resend it.

## Retry, idempotency, and ambiguous outcomes

For caller-retryable commands, use a stable logical key and request fingerprint
when duplicate payloads must be distinguished:

- same key and same fingerprint returns or resumes the same logical operation;
- same key and different fingerprint is a conflict.

Do not add an idempotency key when the database identity and transition
precondition already provide the required guarantee.

Failure modeling distinguishes the cases that require different recovery:

- failure before unreliable or external work began;
- known retryable failure;
- known permanent failure;
- retry budget exhausted;
- provider or remote outcome unknown.

An outcome-unknown operation is never repeated automatically unless a verified
remote idempotency or reconciliation contract makes repetition safe. Provider
or model calls that may duplicate spend or return an unrecoverable result follow
the same rule.

Broker, provider, and remote calls use bounded deadlines. A timeout, lost
connection, cancellation, or expired local lease is outcome-unknown unless the
remote contract proves that work did not occur. Lease expiry authorizes local
recovery; it does not cancel remote work.

Retries are bounded, preserve the original logical identity, and use one policy
owner. Claims and leases expire or have an explicit recovery path. Recovery
resumes from the last durable safe checkpoint; it does not infer success from
logs or replay already committed local effects.

Duplicate starts, stale revisions, and duplicate terminalization must be
harmless by construction.

## Mutating external effects

Every retained mutating external effect has a durable contract that closes the
local-commit/remote-effect gap, or the effect is unavailable. A concrete outbox
is one valid mechanism when the nearest existing lifecycle owner cannot
represent dispatch and recovery.

A concrete effect contract accounts for:

- durable intent committed atomically with the triggering local state;
- stable effect identity and the remote idempotency contract, if one exists;
- immutable typed effect request, schema/version, request fingerprint, or stable
  reference to verified immutable input; one effect identity cannot represent
  different content;
- tenant, actor, run, or step ownership as applicable;
- claim or lease and bounded retry policy;
- sanitized failure facts;
- durable receipt or explicit unknown outcome;
- reconciliation or manual-resolution behavior;
- retention of the intent and data needed to resolve it;
- crash after remote success but before local receipt commit.

An idempotency header is not a guarantee unless the remote system defines its
scope, retention window, payload-conflict behavior, and replay response. An
approval flag or policy string is not a durable effect boundary.

If a mutation lacks the required contract, reject or disable it at the narrowest
reliable API, compile, publish, or execution boundary. Do not run it optimistically
and add repair logic afterward.

An effect's failure state belongs to the nearest existing lifecycle owner. A
separate effect state machine earns its existence only when the effect is
independently claimed, retried, reconciled, or retained. A shared effect
abstraction earns its existence only after multiple concrete effects have
materially identical invariants and it removes more complexity than it adds.

## Retention and finalization

- Retention and deletion are reference-aware. Shared data survives while a
  retained reference exists; sensitive data is reclaimed after the final
  retained reference or an explicit abandonment horizon.
- Unresolved required audit delivery, external-effect intent, or reconciliation
  blocks deletion of the data needed to complete or diagnose it.
- Collect file, blob, and resource candidates before cascading deletion removes
  the membership rows that identify them.
- Route deletion through the canonical resource/reference owner and reuse an
  existing reference fence where one exists. Deleting a membership row does not
  prove shared storage is orphaned.
- Prevent a new retained reference from racing across the orphan decision. Use
  locking, compare-and-swap, constraints, serializable transactions, or another
  database-enforced mechanism appropriate to that owner.
- When reference deletion and external resource deletion cannot share one
  transaction, keep the candidate or deletion intent durably discoverable until
  deletion is confirmed. Reuse the canonical resource row or an existing
  recovery owner; create a dedicated intent only when neither can represent the
  lifecycle.
- Soft deletion has an idempotent finalization path once the canonical retention
  policy says the record is eligible and retained children, references, holds,
  and required operational blockers are clear.
- Direct parent or container deletion cannot bypass child finalization or
  candidate collection. Prefer an explicit resolvable blocker to a hidden
  partial cascade.
- Foreign-key actions, check constraints, deletion order, and application
  lifecycle must agree.
- Operational receipts must not make a parent immortal unless product policy
  explicitly requires it. Historical provenance belongs in the canonical audit
  owner.
- Cleanup retries converge on the same terminal state.

Use a bounded one-shot backfill when preflight finds historical stranded rows.
Do not build a permanent sweeper when fixing the steady-state producer makes new
stranding impossible.

## Operational visibility

Logs, metrics, traces, and audits project persisted lifecycle facts; they do not
replace those facts.

- Important transitions carry durable entity identity, revision or generation,
  attempt when applicable, transition, outcome category, and correlation
  identity.
- Persisted operational errors are bounded, classified, and sanitized. Do not
  store credentials, full provider payloads, or arbitrary exception text.
- Health and metrics expose the conditions an operator can act on: queue age,
  eligible backlog, retry exhaustion, expired claims, outcome-unknown work,
  unresolved effects, retention blockers, and finalization backlog when those
  states exist.
- Alerts name an owner and a recovery action. “An error was logged” is not a
  recovery plan.
- Audit records capture product-, security-, and compliance-significant events;
  they do not double as the operational state machine.
- Public and diagnostic projections are separate, typed, bounded, and
  authorization-scoped.

## Required behavior proofs

Choose the proofs that match the changed boundary. Tests land with the lifecycle
owner rather than in a generic mock-heavy harness.

Relevant proofs include:

- from public submit or create, through a real test broker and worker, to the
  public result;
- same-key replay and conflicting-key payload behavior;
- duplicate broker delivery and stale revision delivery;
- crash after durable intent but before broker or provider work;
- broker acceptance followed by failure before local acknowledgement;
- worker exit after claim and after each meaningful checkpoint;
- duplicate terminalization;
- remote success followed by process death before receipt commit;
- remote timeout or lease expiry followed by late remote success, without unsafe
  automatic repetition;
- retry exhaustion and operator- or user-visible terminal outcome;
- final-reference deletion racing with a new reference;
- process death after reference or cascade commit but before external resource
  deletion, and after remote deletion but before local confirmation;
- unresolved effect or audit state blocking purge;
- direct deletion and final-child deletion using the same finalization behavior;
- foreign-key, check, and cascade behavior on representative PostgreSQL;
- migration preflight, upgrade, downgrade, and one-head validation;
- public contract tests for exposed retryable, exhausted, ambiguous, and
  terminal states.

Use bounded state polling instead of arbitrary sleeps. Prefer real constraints
and process boundaries over mocks of internal collaborators when those
boundaries are the behavior under test.

## Designs to reject

Reject:

- a generic runtime engine or checkpoint store around an existing lifecycle
  owner;
- a generic lifecycle or finalizer manager;
- a generic external-effect framework before repeated concrete seams exist;
- retry helpers that hide failure classification, transaction ownership, or
  persisted state;
- generic event or attempt tables without a real query and retention need;
- a dispatch outbox that duplicates the queued work row;
- large task payloads or worker-memory checkpoints as authoritative state;
- `updated_at` as a scheduler, queue generation, or lease;
- log-only retries, exhaustion, or terminal outcomes;
- broad exception handling that classifies every failure as retryable;
- unbounded retries or permanent sweepers that compensate for an unfixed
  producer;
- approval flags or idempotency headers presented as a complete effect contract;
- runtime repair of invalid authored or published state;
- “exactly once” claims for broker, provider, or remote work without a verified
  external guarantee.
