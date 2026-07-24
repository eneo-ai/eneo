# Flow launch scope and lifecycle

- **Status:** Accepted
- **Date:** 2026-07-11
- **Last revised:** 2026-07-24
- **Decision owners:** Product, security, and architecture
- **Scope:** Flow and Flow AI Builder launch behavior, destructive retention
  activation, and the portable-package platform boundary

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
- **Removed or unavailable launch surface:** Assistant/App package payloads and
  installation, a registry or marketplace, signing, MCP, HTTP mutation,
  attached-template portability, and compatibility shims. Each requires the
  trigger and contract recorded below before it can ship.
- **Implementation owner:** Accepted WI-13 owns strict Flow planning and
  installation. WI-13B owns the final external container contract. WI-13C owns
  package-import tenant/space/Flow integrity. WI-13D owns explicit, bounded
  provenance for source-local dependencies omitted from a package. Future
  Assistant, App, and marketplace work remains trigger-gated.
- **Deferred trigger:** A named product owner may propose an excluded capability
  only with its authorization, integrity, lifecycle, recovery, and consumer
  contract.
- **Revision rule:** Revise this record before expanding the portable subset;
  never infer support from fields that happen to serialize.

#### Implemented state and mandatory launch hardening

The implementation exports and imports Flow packages only. The external
container is `.eneopkg` with media type `application/vnd.eneo.package+zip`, and
the manifest's required `kind` field is the sole closed discriminator. The
reader validates structural ZIP safety and `manifest.json`, parses the manifest,
rejects Assistant or App kinds at the typed Flow endpoint, and only then applies
the exact Flow entry profile and payload parser. No Flow-specific extension,
`package_kind` alias, Assistant/App payload, planner, installer, receipt, or
marketplace exists.

Accepted WI-13C hardens the successful-retry query so the joined Flow matches
the receipt's tenant and space. Its read-only mismatch preflight and explicit
Flow-between-space update decision support the narrow Flow-side unique target
and composite foreign key over `(id, tenant_id, space_id)`; the existing
`uq_flows_id_tenant_id` tenant pair remains intact. The relation preserves
`ON DELETE CASCADE` and the terminal-shape constraint. Failed receipts remain
space-owned display/audit rows and never become retry candidates. The accepted
slice adds no Spaces `(id, tenant_id)` constraint, imaginary-production repair,
package registry, tombstone, or generic integrity framework.

One additional slice remains mandatory for the current package lane:

- **WI-13D — Make omitted local dependencies explicit and bounded.** A Flow
  package must not fail merely because unreachable source-local MCP association
  rows remain, and it must not discard those associations silently. Export
  counts distinct affected Flow step assistants once, records only a strict
  `mcp_attachment` kind and positive count in package provenance, and derives
  every validation, import-plan, response-header, audit, SDK, and UI advisory
  from that value. Ordinary exports carry a required empty omission list and no
  advisory header. The omission participates in `content_checksum`; strict v1
  readers reject a missing field, unknown field, or unknown omission kind.
  Re-export replaces an obsolete local archive. This is provenance for omitted
  source-local state, not portable MCP support.

#### Portable knowledge and local-integration boundary

Flow, Assistant, and App packages never carry knowledge documents, extracted
text, chunks, embeddings, vectors, vector indexes, retrieval caches,
vector-database or embedding-provider configuration, credentials, or
destination-local knowledge identifiers. A package may carry only bounded
logical knowledge requirements and safe setup guidance for explicit local
rebinding. `FlowPackageKnowledgeGuidance` limits `summary` and `setup_notes` to
4,000 characters, each `recommended_sources` and `do_not_include` collection to
20 entries, and every normalized entry to 1,000 characters. A separately
governed immutable content release may be considered later; WI-13D adds no
content-release coordinate, ingestion, or portable vector state.

Packages also never carry MCP URLs or configuration, transports, commands,
tool catalogs as trusted truth, headers, credentials, environment values,
certificates, approvals, trust material, or local server identifiers. Flow MCP
remains hard-disabled at authoring, publish, verified-definition, import, and
runtime boundaries. WI-13D removes only the blanket export failure caused by
unreachable source-local association rows. It counts distinct affected step
assistants in one tenant-scoped scalar query and writes one strict provenance
omission with fields `kind` and `count >= 1`; a server row plus tool rows for
one assistant still counts once.

`FlowPackageProvenance.omissions` is the sole durable omission owner. The field
is required in strict provenance v1, empty for an ordinary export, and covered
by the provenance hash and `content_checksum`. Unknown omission fields or kinds
require a provenance schema-version decision rather than permissive parsing.
The binary export remains one `.eneopkg` response. A positive omission adds the
conditional `Eneo-Package-Omitted-Mcp-Assistant-Count` header; zero is represented
only by an absent header. The canonical CORS expose-header owner covers normal
middleware and manual error responses. The generated SDK parses the header
into the strict omission type. Localized Swedish/English export UI presents the
advisory before the existing save helper runs; import UI presents
package-carried omissions before installation. Package bytes, responses, audit,
and logs contain no names,
URLs, credentials, headers, local identifiers, prompts, or source content.

A future executable Assistant or App may declare a bounded abstract local
integration requirement only in its own strict vertical contract. An authorized
destination administrator then maps an independently configured local server,
and installation cannot claim ready while a required integration remains
unresolved. WI-13D adds neither that type nor capability matching, server
export, marketplace state, or a generic integration registry.

#### Portable container and module ownership

The target user-facing container is one `.eneopkg` ZIP archive with media type
`application/vnd.eneo.package+zip`. The manifest's `kind` field is the sole
package-kind discriminator. Per-kind HTTP endpoints remain typed; the container
does not create one generic upload or install API.

For now, dependency-clean artifact mechanics stay inside
`eneo.flow_packages`, and their dependency direction is frozen in place. A
shared module with one consumer would add ceremony without removing
duplication. When Assistant packaging is scheduled as the second concrete
consumer, WI-PKG-01 extracts only the proven shared archive, manifest,
checksum, and bounded-reader mechanics into `eneo.packages`. Error descriptors
move only if two real verticals later prove identical semantics.

Vertical owners remain `eneo.flow_packages`, future
`eneo.assistant_packages`, and future `eneo.app_packages`. Each vertical owns
its strict portable authoring payload, authorization, requirement topology,
destination planning, installation, transaction and recovery behavior, and
concrete FK-backed receipt lifecycle. Shared requirement descriptors may move
only after two real verticals prove identical semantics; topology and
destination binding stay vertical. Kind dispatch is closed and exhaustive. It
does not use a Protocol, dynamic registry, plugin framework, service locator,
`BasePackageService`, generic CRUD installer, or package god module.

#### Integrity and digest vocabulary

- **`content_checksum`:** checksum of canonical manifest metadata, the Flow
  draft, requirements, and provenance. It identifies the exact canonical
  content reviewed for import, not necessarily the compressed archive bytes.
  Provenance includes export time today, so an unchanged Flow re-export can
  produce a different checksum. Deduplication and update logic must not assume
  stable equality across re-exports.
- **`spec_hash`:** hash of the Flow draft specification only. It is a
  Flow-internal payload fact, not a universal package semantic digest.
- **`archive_digest`:** future marketplace digest of the exact immutable bytes
  stored and served. It appears only when marketplace storage exists.

Do not add a fourth generic payload digest until a concrete update,
deduplication, signing, or comparison contract needs it. Manifest v1 contains
no marketplace listing or publisher UUID, signature or key, compatibility
matrix, destination-local ID, user or space identity, secret, credential, or
mutable install state. The offline `package_version` remains a bounded non-empty
label; marketplace release ordering may define a stricter version policy later,
but manifest v1 does not impose SemVer for architectural symmetry.

#### Trigger-gated package and marketplace expansion

The following work is part of the long-term roadmap but does not enter the
current launch denominator until its named trigger or D0 decision activates it:

- **WI-PKG-01:** extract `eneo.packages` only when Assistant packaging is
  scheduled and two concrete consumers prove the seam.
- **WI-PKG-02A:** define one strict, secret-free, local-ID-free portable
  Assistant authoring contract. Preflight deployed Assistant data and decide
  which unsupported state is deleted, migrated, or rejected. A Flow-managed
  Assistant cannot export as a standalone Assistant package.
- **WI-PKG-02B:** implement Assistant export, plan, and install in the Assistant
  package vertical, ending in the canonical Assistant authoring owner and a
  concrete Assistant receipt.
- **WI-PKG-03A:** define one strict portable App authoring contract and decide
  executable and asset boundaries.
- **WI-PKG-03B:** implement App export, plan, and install in the App package
  vertical, ending in the canonical App authoring owner and a concrete App
  receipt.
- **WI-MKT-D0:** decide publisher authority, municipality/tenant audiences,
  moderation, licensing, release ordering and version policy, withdrawal and
  yanking, telemetry/privacy, asset scanning and limits, template-gallery
  disposition, central versus federated topology, and the required trust or
  signing stage.
- **WI-MKT-01:** after WI-MKT-D0, implement immutable publisher, listing, and
  release metadata; exact archive-byte storage; authorized browse/search;
  moderation; and bounded cursor pagination.
- **WI-MKT-02:** install one selected release by delegating to its existing
  kind-specific plan/install vertical. Marketplace code never owns destination
  planning or installation semantics.

Federation, detached signing, key rotation/revocation, trust roots,
update/merge/rollback policy, publisher analytics, and large assets require
separate later triggers. They are not implicit consequences of WI-MKT-01 or
WI-MKT-02.

#### Marketplace and data-model guardrails

- Model publisher, listing, and immutable release as one relational aggregate.
  Use unique publisher/kind/package coordinates and an immutable release-version
  key.
- Store exact archive bytes in object storage, not the relational database.
  Compute `archive_digest`, store bytes before publishing the release row, and
  clean bounded orphan uploads.
- Use explicit `draft -> published -> yanked` release state, audience and
  visibility, and moderation state. Browse/search uses indexed cursor
  pagination; it never materializes the full catalog or relies on offset-only
  pagination for large lists.
- Same-instance distribution uses ordinary authorization and moderation, not
  signature theater. Known cross-instance transfer uses TLS plus digest
  pinning. Untrusted/federated distribution earns detached signatures, key
  rotation/revocation, and trust roots through a later decision.
- Keep install receipts concrete and FK-backed by kind. Never add a generic
  polymorphic `target_uuid`.
- Asset support requires an explicit inventory, media type, byte size, digest,
  bidirectional archive-coverage check, strict caps, scanning policy, and no
  executable plugin interpretation.
- Existing Assistant and App template galleries are already catalog-like
  owners. WI-MKT-D0 must count deployed rows and choose whether they remain
  local creation shortcuts or migrate curated entries to marketplace releases
  with a deletion plan. A third unrelated catalog is forbidden.

#### Package-platform must-not-build ledger

- No shared package module with one consumer.
- No generic package installer or service, plugin system, dynamic registry,
  service locator, one-implementation port, or package god module.
- No FK-less polymorphic install records.
- No mutable marketplace releases, implicit auto-update, or hidden dual
  formats.
- No portable local IDs, credentials, users, spaces, publisher-local UUIDs, or
  source trust.
- No manifest-v1 signature, key, catalog, or compatibility fields.
- No database archive blobs, unbounded assets or fan-out, N+1 candidate loading,
  or full-catalog materialization.
- No third template or catalog owner.

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
  sequential bounded mapping, and no resumable fan-out. Every published
  `per_source` step declares a positive `runtime_input.max_files` ceiling, and
  every published `item_map` step declares its own positive `max_items` ceiling.
  Runtime rejects max+1 before preparing an assistant or making a provider call.
  Selective retrieval is not a launch default and requires a later explicit,
  evidence-backed decision.
- **Consequences:** Result detail, source coverage, retrieval posture, source-record
  cardinality, extraction quality, and processing strategy remain separate typed
  decisions. Concise output never implies that fewer sources may be read.
- **Retained surface:** Deterministic sequential mapping, definition-owned file
  and item ceilings, exact source references, and whole-step retry semantics.
  The Celery soft/hard task timeout remains the one aggregate mapped-step
  deadline; no per-source or per-item deadline owner is added.
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

### 14. Tenant administration activates automatic Flow deletion

- **Decision:** Automatic Flow run-content deletion is off unless an optional
  tenant organization policy (`T`) or the optional policy for the Space's
  matching tenant security classification (`C`) applies. Let `A` be the minimum
  configured value of `T` and `C`; if both are absent, `A` is off. When `A` is
  active, effective Flow run days are the minimum configured value of `A`, Space
  days, and Flow days. Space and Flow values can tighten but cannot activate,
  lengthen, or disable the admin envelope. Classification-only activation is
  deliberate and affects only matching classified Spaces.
- **Persistence:** Add nullable, `1..2555` CHECK-constrained tenant columns
  `flow_run_history_retention_days` and
  `flow_runtime_upload_abandonment_days`. Keep matching classification days in
  the existing relational policy table. Do not put either destructive selector
  input in `tenant.flow_settings` JSONB. Keep
  `run_debug_evidence_days` in that existing versioned JSONB owner because its
  cleanup is already Python-resolved. Reuse the typed ADMIN-only settings,
  classification, and audit surfaces as control-plane adapters;
  `DataRetentionService` remains the sole deletion decision-maker and owns one
  SQL envelope expression reused by purge, preview, and effective-policy reads.
- **Safe activation:** Every organization or classification change that enables
  or shortens Flow deletion uses the same preview/confirm gate. Preview and purge
  share predicates and clock anchor and expose counts, bytes, existing-data
  impact, latent Space/Flow values, and lifecycle blockers. Confirmation is bound
  to exact proposed values, current policy revision or expected state, and the
  exact preview result; a concurrent admin change fails compare-and-set. Audit
  records actor, old/new values, preview summary, and activation time without
  payloads or secrets. Disabling or lengthening needs no destructive
  confirmation. No pending-policy table is introduced.
- **Space and Flow behavior:** `Spaces.data_retention_days` continues to control
  conversation and App-run retention. Space UI shows that behavior separately
  from Flow behavior: the same value is inert for Flow while `A` is off and
  tighten-only while `A` is active. Activation preview includes all latent Space
  and Flow values. Release one keeps Flow overrides pre-publish-only; a published
  Flow displays configured/effective values read-only and gains no hidden
  retention-only mutation path. A dedicated Space Flow-retention column is
  deferred until a customer needs conversation and Flow horizons to differ.
- **Never-attached uploads:** WI-19 runs only when
  `flow_runtime_upload_abandonment_days` is present for the tenant and anchors age
  to persisted upload `created_at`. Absence produces no abandonment candidates or
  deletion I/O. No Space, Flow, step, classification, or global grace contributes.
  Attached sources follow run-history policy and WI-03's final-reference fence.
  Reuse the daily worker, ordered bounded batches, bind-versus-sweep lock, final
  reference recheck, retry convergence, and one transaction owner.
- **Deployment and UX:** Preflight is bidirectional on representative PostgreSQL:
  count runs newly eligible under the envelope and runs eligible today only
  through Space/Flow values that become inert. The local zero-row database is not
  representative evidence. Release notes and admin UI state both changes. Add
  **Admin > Governance > Flow data retention**, not an Audit logs panel, with
  organization Flow history and unattached-upload Off/N days, classification
  links, anchors, affected data, preview/confirm, audit actor, and preservation/
  hold caveat. Classification edits remain under Security classifications and
  call the shared gate; Space and Flow show configured values, effective off/days,
  and all contributors. Copy says “Automatic deletion is off” in Swedish and
  English, not “no limit,” and makes no compliance claim.
- **Retained surface:** Information classification selects an admin policy but
  does not hard-code a clock. Audit and AI-log retention remain separately owned.
  Legal/records holds remain a future purge blocker. A dedicated Flow with a
  one-day policy is the honest first-release stricter option.
- **Removed or unavailable surface:** Numeric or seven-day defaults, class-3
  defaults, silent grace periods, Space/Flow-only activation, global upload
  abandonment, automatic Builder attachment deletion, day-zero finalization,
  pre-launch step retention, and claims that deletion is immediate.
- **Implementation owner:** WI-19A owns relational tenant policy, typed admin
  control plane, preview/confirm/CAS/audit, generated contract, and admin UI.
  WI-19B owns the canonical envelope/effective projection, Space/Flow behavior,
  copy, docs, and bidirectional rollout preflight. WI-19 then owns only the
  never-attached-upload sweep. WI-24 follows the final retention/finalization
  ownership.
- **Deferred triggers:** A real customer or contractual requirement for sub-daily
  erasure earns a separate typed mode with bounded sub-daily cadence, terminal
  blockers, recovery and backup/PITR limits, and real-process proof. Step-level
  deletion requires a concrete mixed-sensitivity Flow plus typed partial-run
  provenance, redaction, retry, export, and audit semantics. A legal/records hold
  requires its own authority and purge-blocker contract.
- **Cadence consequence:** The current daily 03:00 worker would make a
  finalization-anchored mode approximately `0..24h` and a one-day policy
  approximately `24..48h`. They are not interchangeable. Launch keeps the
  honest one-day option instead of adding a mode, constraint, index, and cadence
  contract without a customer trigger.
- **Revision rule:** No adapter, child setting, classification label, or fallback
  may activate destructive Flow retention outside this envelope. Revise this
  record before adding another activator, clock, hold, or deletion mode.

### 15. Service-key rerun is an explicit own-run capability

- **Decision:** A service key may rerun only a run owned by the same service
  principal, and only when the route explicitly requests the rerun capability.
  The rerun operation records `requested_by_principal_type=service_key` together
  with `requested_by_service_id`; cross-principal rerun remains forbidden.
- **Consequences:** Service-key rerun fails closed by default at the API action
  policy and passes only through the explicit route capability plus the run
  access policy's own-principal check. Review and resume remain separate
  capability rows, and Flow AI Builder actions remain user-only.
- **Rejected posture:** The stale human-only posture is rejected because it
  contradicts the shipped typed requester constraint, own-run access boundary,
  and consumer API behavior. Restoring it would remove an already coherent
  runtime capability without improving attribution or cross-principal safety.
- **Implementation owner:** `FlowActionRequirement` in
  `flow_access_policy.py` owns route-requested action eligibility;
  `FlowRunRerunService` owns rerun validation, `FlowRunAccessPolicy` owns own-run
  scoping, and `FlowRunRerunOperations` owns typed requester persistence and its
  exactly-one-requester constraint.
- **Revision rule:** Expanding beyond own-run service-principal access requires a
  new product and security decision. Do not infer broader access from the
  existence of service-key attribution columns.

## Delivery order and gates

This record defines dependency order, not current execution status; accepted
receipts and the ranked roadmap record completion. WI-20 protection must
precede WI-03 retention selection. The lifecycle/package dependency order is:

1. WI-20 protection mode
2. WI-22A
3. WI-22B
4. WI-23
5. WI-03
6. WI-19A
7. WI-19B
8. WI-19
9. WI-24
10. WI-13
11. WI-13B
12. WI-14 and WI-13C after WI-13B, in parallel when file and migration
    ownership allow
13. WI-13D after WI-13B and WI-22B, when package model/schema, generated
    SDK/docs, CORS, and locale ownership are available
14. WI-15
15. WI-21 as the final cleanup slice

Additional gates:

- WI-14 waits for the WI-22A/WI-22B capability shape and WI-13B's final public
  package shape. WI-13C does not change that public shape, so it need not block
  WI-14. WI-13D consumes the accepted generated-client boundary and reruns its
  own schema/docs parity gates; it does not reopen WI-13B, WI-13C, WI-14,
  WI-22B, or WI-23.
- Package-lane launch completion requires WI-13B, WI-13C, and WI-13D. WI-13C
  used the serialized migration queue; WI-13D is migration-free unless current
  PostgreSQL plan evidence proves a separately reviewed schema need.
- Package-platform amendment added WI-13B and WI-13C; the omission decision adds
  WI-13D; this retention decision adds WI-19A and WI-19B. The roadmap has 46
  full-schema sections: 38 current and eight trigger-gated future. WI-12 remains
  five independently accepted execution identities with separate receipts and
  commits; the current execution denominator is therefore 42 and the total
  visible execution count is 50. The eight trigger-gated future sections are
  also eight future execution identities and remain excluded until their
  recorded trigger activates.
- WI-19A → WI-19B → WI-19 is the serial retention-policy path. WI-19 and WI-24
  coordinate so Flow finalization collects runtime-upload
  candidates before cascade removes their bindings.
- WI-22A records persisted HTTP POST input and Flow MCP counts and whether real
  stored data requires a migration. Every migration-bearing work item starts from
  the then-current accepted Alembic head.
- WI-22A and WI-22B may both affect generated schema and documentation. Reconfirm
  exact frontend ownership, regenerate once after WI-22B, and stop on overlap.
  WI-13D later serializes package model/schema, generated SDK/docs, CORS, and
  Swedish/English locale ownership for its one omission projection.
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
