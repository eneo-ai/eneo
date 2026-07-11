# Flow launch scope and lifecycle

- **Status:** Accepted
- **Date:** 2026-07-11
- **Decision owners:** Product, security, and architecture
- **Scope:** Flow and Flow AI Builder launch behavior

## Context

Flow launch safety depends on product choices that cannot be inferred from an
implementation. Package portability, external effects, evidence handling, file
retention, and deletion all change the correct runtime and data design. This
record makes those choices explicit before the dependent work lands.

This record owns product scope and lifecycle policy. Executable schemas,
validators, persistence, and runtime code remain authoritative for implemented
behavior. The dependent work items below must implement this record through the
existing owners described in the
[Flow Developer Quickstart](../flows/flow-developer-quickstart.md) and follow the
[Runtime Reliability Standard](../engineering/runtime-reliability-standard.md).

## Decisions

### 1. Package import is a strict human-file-transfer subset

- **Decision:** Package import launches only for Flow definitions that are
  strictly representable as a human-transferred file and its declared portable
  resources.
- **Consequences:** Planning and installation must accept the same strict
  portable shape, resolve every declared resource, and fail unsupported content
  before installation. No permissive or legacy interpretation is allowed.
- **Retained surface:** Strict file export, plan, and import for the supported
  subset, with checksums, explicit mappings, and complete import receipts.
- **Removed or unavailable surface:** Signing, a registry or marketplace, MCP,
  HTTP mutation, attached-template portability, and compatibility shims. Each
  requires a separate concrete contract before it can ship.
- **Implementation owner:** WI-13 owns strict planning and installation after
  WI-22A and WI-22B settle portable capabilities and WI-23 settles import-row
  lifecycle.
- **Deferred trigger:** A named product owner may propose an excluded capability
  only with its authorization, integrity, lifecycle, recovery, and consumer
  contract.
- **Revision rule:** Revise this record before expanding the portable subset;
  never infer support from fields that happen to serialize.

### 2. Terminal webhooks are a launch guarantee

- **Decision:** Terminal webhook delivery remains part of the launch contract.
  WI-20 protection mode must land before WI-03 widens retention purge.
- **Consequences:** Pending delivery and an actively claimed delivery intent
  block purge. Delivered and dead-lettered terminal states are purge-permitted
  when the later retention implementation removes the owning run.
- **Retained surface:** Terminal POST output through the durable webhook outbox,
  including stable intent identity, bounded claims and retries, dead-lettering,
  and visible blocked counts.
- **Removed or unavailable surface:** Retention may not silently erase unresolved
  terminal webhook work, and retention may not act as the delivery terminalizer.
- **Implementation owner:** WI-20 owns the protection predicate and observability;
  WI-03 must consume that predicate when reclaiming final run references.
- **Deferred trigger:** None for launch. A future removal requires deleting the
  complete authoring, public, runtime, outbox, generated-client, and documentation
  surface before weakening retention protection.
- **Revision rule:** Change the guarantee only through a new product decision and
  an executable migration or removal plan.

### 3. HTTP POST input is deleted

- **Decision:** Delete HTTP POST input from Flow authoring, package, publish,
  runtime, public contract, generated client, and documentation.
- **Consequences:** Existing pre-production definitions and package fixtures must
  be counted and deliberately rejected, migrated, or removed. They must never be
  silently reinterpreted as GET or terminal delivery.
- **Retained surface:** HTTP GET input and terminal POST output through the
  existing durable webhook outbox.
- **Removed or unavailable surface:** Inline side-effecting HTTP POST input and
  any unreleased compatibility branch that preserves it.
- **Implementation owner:** WI-22A owns persisted-data preflight, capability
  deletion, fail-closed historical behavior, public contract regeneration, and
  documentation updates.
- **Deferred trigger:** Reintroduction requires its own durable
  intent/receipt/reconciliation contract and a crash test for outcome ambiguity.
- **Revision rule:** Never restore inline POST as a fallback or treat an
  idempotency header as proof that an arbitrary receiver is idempotent.

### 4. Flow MCP is hard-disabled

- **Decision:** Hard-disable Flow MCP at publish, runtime, and package boundaries,
  and remove the unenforced Flow MCP policy.
- **Consequences:** Flow definitions and packages that depend on MCP fail
  deterministically. Tool approval and tool-name or description heuristics do not
  constitute a Flow external-effect contract.
- **Retained surface:** Non-Flow MCP behavior remains unchanged under its own
  conversation and approval owners.
- **Removed or unavailable surface:** Flow MCP execution, Flow package claims of
  MCP support, the no-op policy field, and heuristic claims of read-only or
  idempotent tool behavior.
- **Implementation owner:** WI-22B owns persisted-data preflight, publish/runtime/
  package rejection, policy deletion, non-Flow regression proof, generated
  contracts, and documentation.
- **Deferred trigger:** Reintroduction requires enforceable per-tool effect
  classification plus durable intent, receipt, approval, and recovery semantics.
- **Revision rule:** Do not substitute the current admin approval flag or semantic
  heuristics for that contract.

### 5. Attached templates require confirmed, transactional promotion

- **Decision:** Auto-promote an attached template only when the file is authorized
  and explicitly confirmed as the template, and when copy, binding, and cleanup
  are transactional and idempotent. Otherwise return typed `needs_action` for
  manual setup.
- **Consequences:** Builder may not produce a publishable-looking topology with an
  unbound or unauthorized template. Retry must converge, and partial material must
  be cleaned up through existing file and template-asset owners.
- **Retained surface:** Confirmed Builder attachment roles, tenant-safe template
  assets and checksums, typed bindings, idempotent retry, and manual setup.
- **Removed or unavailable surface:** Implicit template promotion, raw session file
  identifiers in published definitions, and silent success with unresolved
  placeholders or assets.
- **Implementation owner:** WI-09 owns file-specific role confirmation; WI-10A
  owns promotion and typed `needs_action`; WI-10B owns exact placeholder binding.
- **Deferred trigger:** Attached-template portability in packages remains excluded
  until a separate portable asset contract is approved.
- **Revision rule:** Relaxation requires equivalent authorization, transaction,
  retry, cleanup, and publishability evidence.

### 6. Apply failure remains explicitly partial

- **Decision:** Retain explicit partial apply failure. A failed apply may leave the
  Flow unpublished and must return typed recovery guidance. Do not invent atomic
  rollback.
- **Consequences:** UI and API consumers must distinguish an unapplied plan from a
  Flow whose prior publication was removed before later apply work failed. Recovery
  is explicit retry, correction, or manual action according to the typed result.
- **Retained surface:** The existing unpublish/apply lifecycle and its visible
  recovery contract.
- **Removed or unavailable surface:** A false all-or-nothing guarantee, hidden
  republish fallback, or best-effort rollback presented as atomicity.
- **Implementation owner:** The existing Builder apply lifecycle remains the owner;
  no new implementation work item is authorized by this decision.
- **Deferred trigger:** A future atomic apply design requires one transaction or a
  durable compensating state machine with crash/replay proof.
- **Revision rule:** Revise this record and the public recovery contract before
  changing partial-failure semantics.

### 7. Corpus processing covers every source sequentially

- **Decision:** Launch posture is `one_record_per_source`, all-source coverage,
  sequential bounded mapping, and no resumable fan-out. Selective retrieval is not
  a launch default and requires a later explicit, evidence-backed decision.
- **Consequences:** Result detail, source coverage, retrieval posture, source-record
  cardinality, extraction quality, and processing strategy remain separate typed
  decisions. Concise output never implies that fewer sources may be read.
- **Retained surface:** Deterministic per-source order, explicit limits and one
  aggregate deadline, exact source references, and whole-step retry semantics.
- **Removed or unavailable surface:** Implicit `contained_records`, selective
  retrieval inferred from words such as “overview,” resumable fan-out, silent
  truncation, and invented conditional `item_template` syntax.
- **Implementation owner:** WI-11A owns accepted corpus state; WI-11B owns exact
  compiler materialization; WI-11C owns optional/required retrieval failure; and
  WI-11D owns bounded sequential execution. WI-11C does not authorize selective
  retrieval for launch.
- **Deferred trigger:** `contained_records`, selective retrieval, concurrency, or
  resumability requires representative evidence, explicit product approval, and a
  typed executable contract with failure and recovery semantics.
- **Revision rule:** Change cardinality or coverage only in accepted state first;
  prompts and field names may never become parallel policy owners.

### 8. Missing evidence is explicit and load-bearing unreadability blocks

- **Decision:** Missing or degraded extraction renders a localized explicit
  unknown such as “framgår ej” and exposes visible degradation. Block when
  unreadable evidence affects a required or load-bearing field. Omit only a field
  that accepted state explicitly marks optional.
- **Consequences:** A report cannot silently turn unreadable or missing source
  evidence into absence, certainty, or model invention. The rendered result and
  provenance must agree about degradation.
- **Retained surface:** Localized unknown values, visible source-quality status,
  explicit optional-field policy, and typed blocking failures.
- **Removed or unavailable surface:** Silent omission of required evidence,
  unsupported guessing, and prompt-only degradation semantics.
- **Implementation owner:** WI-08 owns confirmed evidence obligations and localized
  presentation; WI-11A owns extraction posture in accepted state; WI-11B and
  WI-11C own executable material and retrieval failure behavior.
- **Deferred trigger:** A different omission policy requires a confirmed product
  decision naming the affected fields and audit consequences.
- **Revision rule:** Required evidence may not be downgraded to optional by a
  rendering default, prompt, or runtime fallback.

### 9. Load-bearing choices require explicit confirmation

- **Decision:** Require explicit confirmation for choices that change evidence
  omission, source coverage, retrieval, runtime inputs, external delivery,
  audit/compliance posture, or `report_disposition`. Benign formatting defaults may
  be visible, typed, vetoable assumptions.
- **Consequences:** Accepted state must preserve provenance and replay these choices
  deterministically. A human review request maps approve/reject to `view`, maps
  edit/correct to `edit`, and maps no request to no checkpoint. A materially
  ambiguous target or capability receives one bounded clarification.
- **Retained surface:** Existing structured questions, accepted semantic state,
  localized requirements/plan review, the existing typed per-step review policy,
  and the existing runtime checkpoint state machine.
- **Removed or unavailable surface:** Silent load-bearing defaults, raw classifier
  prose as public truth, a fake AI review step, renderer/delivery checkpoint
  placement, and an invented default human checkpoint.
- **Implementation owner:** WI-08 owns confirmation, provenance, localization, and
  review obligations; WI-09 follows for file-specific roles. Accepted WI-02A
  provides deterministic evidence, while WI-02B gates only named live-evidence and
  heuristic-deletion work.
- **Deferred trigger:** Additional load-bearing choices enter this set only through
  a product-approved typed decision with deterministic and live evidence where
  required.
- **Revision rule:** A prompt instruction alone cannot add, remove, or retarget a
  confirmed obligation.

### 10. Builder uploads are temporary unless explicitly promoted

- **Decision:** A Builder attachment is a temporary session artifact by default and
  becomes a reusable principal file only after explicit promotion. Current
  cancellation and detachment remove session membership only. No automated Builder
  blob deletion ships at launch.
- **Consequences:** Session cleanup must not imply blob deletion. Existing global
  references continue to fence file deletion, and upload provenance must remain
  inspectable until an approved retention implementation safely consumes it.
- **Retained surface:** Authorized BuilderSessionFiles membership, explicit
  promotion, shared file-reference fencing, and membership-only cancellation and
  detachment.
- **Removed or unavailable surface:** Launch-time automated Builder blob deletion,
  implicit promotion, ownership inferred from one membership row, or deletion by a
  generic orphan scanner.
- **Implementation owner:** No launch implementation work item deletes Builder
  blobs. Existing Builder session and file-reference owners remain authoritative;
  WI-10A owns only the narrow confirmed-template promotion described above.
- **Deferred trigger:** A future focused work item is earned only when a named
  retention horizon and product/security owner require it and provenance,
  lock/recheck ownership, global-reference fencing, candidate counts and bytes,
  rollback, and idempotency are proven.
- **Revision rule:** Do not repurpose WI-19 or WI-24 for Builder blobs without that
  trigger and an explicit revision to this record.

### 11. Differential source-only retention is deferred

- **Decision:** Do not introduce a shorter differential source retention horizon at
  launch.
- **Consequences:** Source files follow whole-run final-reference deletion until
  that lifecycle is accepted. A vague promise of later cleanup is not authority to
  classify or delete source evidence differently.
- **Retained surface:** One final-reference retention model, existing authorization
  and reference fences, and the later whole-run cleanup path.
- **Removed or unavailable surface:** Source-only expiry, inferred sensitivity
  classes, or deletion without observable evidence and recovery ownership.
- **Implementation owner:** WI-03 establishes final retained-reference cleanup and
  WI-24 establishes Flow finalization; neither introduces differential retention.
- **Deferred trigger:** A future work item requires accepted whole-run deletion and
  a named legal/product owner who defines a shorter horizon, classification,
  observability, recovery, and deletion evidence.
- **Revision rule:** The concrete trigger above, not elapsed time or implementation
  convenience, is required before differential retention work begins.

### 12. Central audit is the post-deletion provenance owner

- **Decision:** Central audit is sufficient durable provenance after Flow or space
  deletion. Successful package import rows will cascade with their Flow in WI-23;
  failed rows remain subordinate to their space.
- **Consequences:** Package-import rows are operational records, not permanent
  tombstones. WI-23 must verify that the required central audit event and retention
  policy satisfy this decision before enabling the cascade; current source's audit
  enqueue attempt alone is not that verification.
- **Retained surface:** Central audit under its retention and authorization policy,
  failed import rows while their space exists, and typed import outcomes while the
  owning Flow or space exists.
- **Removed or unavailable surface:** A permanent successful-import row that blocks
  Flow or space deletion, an additional provenance tombstone, or a second audit
  store.
- **Implementation owner:** WI-23 owns the successful-row cascade, failed-row space
  lifecycle, blocker deletion, audit verification, and deletion tests.
- **Deferred trigger:** A longer-lived package provenance store requires a named
  legal/audit requirement that central audit cannot satisfy.
- **Revision rule:** Do not retain operational rows indefinitely as an accidental
  substitute for a deliberate audit policy.

### 13. Flow-owned artifacts end with the final retained run

- **Decision:** Published versions, template assets, and source files do not survive
  the final retained run unless a named legal/audit owner supplies a longer horizon.
  WI-24 will finalize and fence files after its prerequisites.
- **Consequences:** A soft-deleted Flow tombstone is not permanent retention. Final
  cleanup must lock and recheck the Flow, collect all file candidates before
  cascade, remove authoring state in constraint-safe order, and pass candidates
  through the one global reference fence.
- **Retained surface:** Runs within their approved horizon, shared files with any
  live reference, central audit, and blocked finalization while prerequisites or
  references remain.
- **Removed or unavailable surface:** Stranded published version rows, template
  assets, source bindings, permanent no-run Flow tombstones, and direct blob
  deletion that bypasses reference fencing.
- **Implementation owner:** WI-03 owns final-run source-reference reclamation.
  WI-24 owns Flow finalization after WI-20 and WI-23. WI-19 must coordinate so
  runtime-upload candidates are collected before Flow cascade removes their
  bindings.
- **Deferred trigger:** A longer horizon requires a named legal/audit owner, exact
  retained artifacts, restore/deletion evidence, and an operational policy.
- **Revision rule:** Never extend retention accidentally through incomplete cascade
  or weaken it by deleting shared files without the global fence.

## Delivery order and gates

The immediate next dependency is **WI-20 in protection mode**. It must finish
before WI-03 changes retention selection. The accepted lifecycle/package order is:

1. WI-20 protection mode
2. WI-22A
3. WI-22B
4. WI-23
5. WI-03
6. WI-19
7. WI-24
8. WI-13
9. WI-14
10. WI-15
11. WI-21 as the final cleanup slice

Additional gates:

- WI-14 waits for the WI-22A/WI-22B capability shape and the WI-13 public package
  shape.
- WI-19 and WI-24 coordinate so Flow finalization collects runtime-upload
  candidates before cascade removes their bindings.
- WI-22A records persisted HTTP POST input and Flow MCP counts and whether real
  stored data requires a migration. Every migration-bearing work item starts from
  the then-current accepted Alembic head.
- WI-22A and WI-22B may both affect generated schema and documentation. Reconfirm
  exact frontend ownership, regenerate once after WI-22B, and stop on overlap.
- WI-D0 plus accepted WI-02A permits WI-08; WI-09 follows WI-08. WI-02B gates
  WI-12 heuristic-deletion families and other explicitly named live-evidence gates,
  not all semantic construction. WI-08 and WI-09 remain operationally deferred
  while concurrent frontend ownership overlaps their files.

## Revision governance

These decisions remain in force until product, security, and architecture approve
a revision. A dependent work item may narrow its implementation when source
evidence demands a safer result, but it may not silently broaden an included
surface, restore an excluded capability, weaken an explicit confirmation or
retention trigger, or create a parallel lifecycle owner. Revise this record before
merging behavior or public contracts that contradict it.
