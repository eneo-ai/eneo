# Eneo Marketplace: simple, governed sharing of Skills, Flows, Assistants, Apps and MCP servers

Design brief, revision 3 (after peer review passes 1 and 2), 2026-10-19.
Repository eneo-ai/eneo at a2481f318 (develop). Flows and the package core
live on branch `feature/flows-and-builder` (ae83fbeca; to be merged later).
eneo-ai/eneo-marketplace contains only README and LICENSE.

## 1. What the product owner asked for

- Municipalities and agencies share Skills (including scripts), Flows,
  Assistants, Apps and MCP server definitions. Modules may come later.
- Prompts and configuration travel. Knowledge does not. Credentials never.
- Every listing is well described: what it does, how it is built, what it
  needs. Prerequisites must be clear before anyone installs.
- Versioned with history. Immutable releases.
- Integrated with Eneo: download a file, or sync to your own instance.
  Install into a personal space, a shared space, or at organisation level.
- Control: not anyone can upload; things must be maintained; withdrawal
  must be possible.
- Sundsvalls kommun runs one public Hub with a login limited to allowlisted
  e-mail addresses or domains.
- Do not overcomplicate. Easy to set up and maintain. Good UX and DX so the
  two code bases stay in sync.
- Plan as if Flows are on develop; shells can start now.

## 2. What exists today (verified)

Eneo, develop:
- Skills: immutable revisions, Space-owned, organisation catalogue with
  exact pins, selective activation, execution blocks, audit. Creating or
  editing a Skill requires `SKILLS_MANAGEMENT`
  (`actors/actors/space_actor.py:752`). The text digest covers name,
  description and instructions only (`skills/domain/skill.py:290`). Epic
  #660 (rewritten today) adds Agent Skills ZIP packages with scripts, a
  canonical `package_digest`, exact package download and `check_javascript`.
  Parent rollout to a newer revision is an admin action on published
  organisation Skills (`organization_skill_service.py:541`).
- MCP servers: `MCPServer` entity (`mcp_servers/domain/entities/mcp_server.py:358`).
  `http_auth_config_schema` holds values, including the secret `token`
  (`mcp_server_service.py:330`). Creation connects and discovers tools before
  saving; general-purpose servers are created enabled (`:589-600`).
- Assistants (`assistants/assistant.py:60-89`): name, description, prompt,
  completion model + kwargs, knowledge (collections, websites, integration
  knowledge), attachments, mcp_servers + per-tool `mcp_tools`,
  `enabled_capabilities`, Skill bindings, icon, `knowledge_mode`,
  `document_template`, logging, insight, retention.
- Apps (`apps/apps/app.py:74-94`): name, description, prompt, completion +
  transcription model, kwargs, input fields, attachments, icon. The App
  completion call passes no MCP servers and no Skill activation runtime
  (`app.py:328`).
- Templates (`templates/`, flag `using_templates`): local creation shortcuts.
- `settings/encryption_service.py` encrypts secrets at rest (used for MCP
  auth). The crawler has a destination policy against SSRF to reuse.

Eneo, branch feature/flows-and-builder:
- `resource_packages/`: shared archive mechanics. Manifest (schema_version
  1, kinds flow | assistant | app, payload_schema per kind, package_id,
  free-form package_version ≤64, content_checksum), bounded ZIP
  reader/writer with typed unsafe reasons, canonical JSON checksum,
  provenance with omissions, import record, 5 MiB cap, adapter protocol.
- `flow_packages/`: the Flow vertical. Archive entries are closed:
  `manifest.json`, `flow.draft.json`, `requirements.json`,
  `provenance.json`, optional `templates/<checksum>.docx`; unknown entries
  are rejected (`flow_package_zip_reader.py:152`). Validation imports Flow
  authoring and domain contracts (`flow_package_draft.py:20`). Endpoints:
  validate, plan, import as draft, export. Install binds the reviewed
  content checksum and target state and rejects drift
  (`flow_package_install_service.py:102`); the import request repeats the
  reviewed checksum and uses an idempotency identity
  (`flow_package_router.py:327`). The plan separates
  `can_install_as_draft` from publishability (`flow_package_import_plan.py:331`).
- `assistants/assistant_package_adapter.py`: prompt, logical model, knowledge
  slots. Not wired. No Skills, MCP, Functions, kwargs, knowledge_mode.
- Svelte: FlowPackageExportDialog, FlowPackageImportDialog (upload →
  validation → plan → confirm → draft). Docs: `docs/flows.mdx`.

ADR `docs/adr/marketplace-hub-package-portability-and-skills.md` and epic
#546 plan a central Hub with separate human identity, OAuth client
credentials (private_key_jwt or mTLS), separation of duties, quarantine +
validation + review + immutable publication, audiences, cursor catalogue,
authenticated exact-byte download, pull-only connector, admin-only native
Marketplace, install-new-only, object storage, Flow-first. #558 is the
native Flow Marketplace task.

## 3. Principles

Kept from the ADR (cheap, protective):
- Immutable releases. Approval binds to frozen bytes and reviewed metadata.
  Review before publication; separation of duties. Yank/revoke never
  deletes local copies.
- Pull-only. The Hub never calls or changes an Eneo instance.
- Eneo humans and Hub humans are separate identities. No token exchange.
- A local person with the right permissions for the complete creation
  graph confirms every install after seeing the complete content.
- Confirmation binds release, digest, target and mappings. Eneo rechecks
  local permission and Hub release state immediately before mutation.
  Create resource, receipt and audit atomically in the kind's owner.
- Packages carry no credentials, no local IDs, no knowledge content, no
  execution history by construction of the exporter. Publisher-authored
  text and files are reviewed by a curator and attested by the publisher;
  Eneo does not claim to prove their absence.
- One strict contract shared by both code bases: a versioned contract
  artifact built from the Eneo repository, pinned by the Hub.

Simplified (with the guards that keep them safe):
- Instance authentication: Hub-issued access token for an approved,
  registered instance; one connection per Eneo tenant; hashed at rest;
  expiry; overlapping rotation; revocation separate from human sessions.
  Not private_key_jwt or mTLS.
- Human login: passwordless e-mail with single-use, short-lived links and
  rate limits, built on a maintained library. E-mail admission (allowlist)
  is separate from organisation membership and roles, which admins assign.
  OIDC later.
- Package bytes in Postgres (bytea/TOAST, catalogue queries never select
  bytes), retention bounds, tested backup/restore. Object storage is a
  later adapter if volume demands.
- One Hub, two audiences (all members, own organisation), no federation,
  no signing.
- Browse in Eneo for signed-in users (local setting). Install authority
  follows the complete creation graph of the target, not only the parent.

## 4. Package contract (owned by eneo-ai/eneo)

Shared archive mechanics, closed per-kind profiles. Each kind owns its
entry set, parser, planner, installer, receipt and fixtures. Existing Flow
v1/v2 bytes and checksums do not change.

| Kind | Archive entries (besides manifest.json, provenance.json) | Travels | Requirement slots at install | Never travels / omitted (listed in provenance) |
|---|---|---|---|---|
| `flow` (exists) | `flow.draft.json`, `requirements.json`, `templates/<sha>.docx` | steps, settings, requirements, Word templates | models, knowledge, template uploads | run history, credentials, knowledge |
| `assistant` | `assistant.json`, `skills/<key>/…` (Agent Skills trees) | see dispositions below | completion model, knowledge slots, MCP server slots, Functions | attachments, icon, knowledge content, credentials, sessions, publication |
| `app` | `app.json`, `skills/<key>/…` | see dispositions below | completion model, transcription model | attachments, run history |
| `skill` (new) | `skill/<name>/SKILL.md`, `scripts/`, `references/`, `assets/` (the #663 bytes, verbatim) | instructions, scripts, declared metadata | target Space only; compute Function shown as a prerequisite for scripts | activation state, bindings, local IDs |
| `mcp_server` (new) | `mcp_server.json` | closed definition, see below | none; admin fills credentials later | credential values, audience, user groups, enabled state, classification, identity forwarding |

Assistant field dispositions (every behaviour-bearing field has one):

| Field | Disposition |
|---|---|
| name, description, prompt | portable |
| completion model | logical requirement (provider/model name, constraints) |
| completion_model_kwargs | portable, bounded |
| knowledge_mode | portable value |
| collections, websites, integration knowledge | requirement slots (names, no content) |
| enabled_capabilities (Functions) | portable list; requirement: each Function available locally, else blocker or explicit opt-out per Function |
| mcp_servers + mcp_tools | MCP requirement slots with the required tool names; each marked required or optional by the publisher; a required slot cannot be skipped |
| Skill bindings | nested exact Skill snapshots with position and activation mode |
| document_template | requirement slot (local template chosen at install) or omitted with notice |
| attachments | omitted, listed |
| icon | omitted and listed; Eneo's icon owner stages uploads outside the database transaction and accepts raster only, so icons wait for a later asset contract |
| logging, insight, retention, published, is_default, source_template | local policy, never portable |

App dispositions: name, description, prompt, kwargs, input fields portable;
completion and transcription models as requirements; nested Skills
instruction-only and eager; a Skill with scripts is an export blocker for
Apps until the App execution contract supports tools; attachments and icon
omitted and listed.

MCP server portable definition (closed): name, description, http_url,
`http_auth_type` ∈ external types only (reject `internal`, `bundled`),
non-secret setup fields (for example `header_name`), documentation_url,
tags, and an informational tool list (names, descriptions, suggested
approval). Import creates the server through a new explicit operation on
the MCP owner: unconfigured and disabled, no connection attempt, no tool
definitions. Tools become real only after the admin adds credentials and
runs the existing discovery and review. Classification and identity
forwarding are local decisions.

Rules:
- A Skill package carries the files of a #663 revision as entries of the
  envelope (no nested ZIP, which validators reject). Export writes the
  stored entries; import rebuilds the Agent Skills ZIP for the existing
  #663 importer. Equality is the canonical `package_digest` over paths and
  bytes, which #663 defines independent of ZIP order and compression. One
  byte-for-byte round-trip fixture proves it before E3 starts.
- A Skill never contains an MCP server. Skills may describe tool use.
  Assistants carry MCP requirements. Standalone `mcp_server` packages share
  a definition.
- Nested Skills inherit the parent version; standalone Skills have their own.
- `package_version` is SemVer on the Hub; offline files keep the free form.
- Receipt per kind (concrete FK): listing id, release id and version,
  archive digest, content checksum, hub id, target, installer, installed_at,
  plus the local baseline: created resource id, its revision id and digests.
  Receipts append; a later install or update adds a row.

## 5. The Hub (owned by eneo-ai/eneo-marketplace)

Stack: FastAPI + Postgres; one Compose file (hub, postgres; no Redis, no
object storage). Front end: Next.js with Astryx, built as a static export
served by the API container, or one Node container; FastAPI owns the API
and authentication (no second auth owner in Next.js). Chosen for parity
with web-next; the Hub team may choose server templates instead.

Identity and access:
- Admission: allowlist of domains and addresses, managed by Hub admins.
- Login: e-mail magic link (single-use, 15 minutes, rate-limited, cookie
  session), via a maintained library.
- Organisations and roles are assigned, not inferred from e-mail: member
  (browse, download), publisher (upload drafts for the organisation),
  organisation admin (members, instances), curator (Hub-wide review and
  publish), Hub admin (allowlist, organisations, policy).
- Instance enrollment: an organisation admin registers an Eneo instance
  (name, tenant hint) and issues its token; or a member requests and the
  organisation admin approves. One active connection per Eneo tenant.
  Tokens: `catalog:read`, `release:download`, later `release:submit`;
  hashed, expiring, overlapping rotation, revocable, last-used shown.
  Removing a member or domain does not revoke instance tokens; that is a
  separate, visible action.

Listings and releases:
- Listing: organisation, kind, package_id, title, summary, description
  (Markdown, sanitized), category, language, tags, maintainer contact,
  license, data-sensitivity notes, screenshots, maintenance status
  (`maintained | needs_maintainer | deprecated`), audience (all members |
  own organisation).
- Release: SemVer, changelog, exact `.eneopkg` bytes, archive digest, size,
  validation report, compatibility (payload schemas, minimum Eneo version),
  derived prerequisites plus publisher notes, and an immutable **reviewed
  snapshot** of the review-sensitive listing fields at approval: title,
  summary, description, license, data-sensitivity notes, screenshot
  references, maintainer contact. Release detail and Eneo's installation
  review render the snapshot, never the live listing. The listing keeps
  only editorial fields mutable: category, tags, maintenance status,
  maintainer contact for future releases, audience.
- Lifecycle: `draft → submitted → approved → published → yanked`;
  `submitted → rejected`; `published → revoked`. Submission freezes bytes
  and digest. Approval records reviewer, the reviewed snapshot and the
  policy version. A bytes or snapshot change on an unpublished candidate
  (`submitted` or `approved`) returns it to `draft`. A published, yanked or
  revoked release never changes: bytes, snapshot and version identity stay.
  A publisher cannot approve their own release.
  Yank blocks downloads and new installs; bytes stay for audit and
  recovery; status stays queryable for installed receipts. Revoke is for
  incidents.
- Audience checks apply to search, detail, preview and download.
- Validation: upload lands in quarantine; the contract artifact validates
  with aggregate nested-entry and uncompressed limits, per-kind asset
  profiles (scripts `.js`; references `.md`/`.txt`; assets and screenshots
  png/jpg/svg with size caps; flows docx), a validation timeout, and
  cleanup of rejected or abandoned drafts. The curator sees the complete
  content: prompts, nested Skills, scripts, flow steps, MCP requirements,
  asset inventory, validation report.
- Maintenance control: maintainer contact required; "unverified" flag after
  N months without release or acknowledgement (Hub setting); curators set
  `needs_maintainer` or `deprecated`; publisher role per organisation.

Catalogue API (bounded, cursor-paginated): discovery, catalog search,
listing, releases, release detail, download (exact bytes + digest header).
Install telemetry is not in the first delivery.

Operations: Compose, Postgres dump backups with a tested restore, SMTP,
rate limits, append-only audit (publish, approve, yank, tokens, downloads
by instance).

## 6. Eneo integration (owned by eneo-ai/eneo)

Backend `marketplace` module:
- Connection settings (admin): Hub URL, instance token (encrypted with the
  existing encryption service, never returned), connection test, status,
  supported profiles, who may browse (everyone | admins), disconnect.
  Audited.
- Connector: fixed-origin HTTPS, timeouts, byte caps, no cross-origin
  redirects, SSRF guard, catalogue projection cached per connection,
  exact-byte download with digest check. Marketplace provenance comes only
  from server-verified Hub metadata; an offline file import has none.
- Install dispatch: verified bytes go to the kind's existing plan/apply
  owner. No generic installer. The receipt is written by that owner in the
  same transaction as the resource and the audit event.
- Authorization: the planner authorizes the complete creation graph
  (parent, nested Skills with `SKILLS_MANAGEMENT`, bindings, selected local
  resources, MCP slots) and reports missing permissions before
  confirmation; apply authorizes again. Denial leaves no partial resource.
- Confirmation binds release id, archive digest, content checksum, target,
  mappings and a plan checksum that doubles as the idempotency key. A lost
  response followed by a retry returns the same resource and receipt. The
  import record gains a source `marketplace` next to `file_upload` and the
  Hub release identity, so the existing retry lookup (content, target,
  mappings) distinguishes an offline import from a Hub release with the
  same content, and two releases from each other.
  Immediately before apply, Eneo rechecks permissions and the Hub release
  state; a yanked or revoked release blocks.
- Updates (first delivery): refresh installed release ids against the Hub,
  keep withdrawal status even when the release disappears from the
  catalogue, show last-checked time during outages, and offer "install the
  newer version as a new copy". Bounded scans, deduplicated lookups.
- Skill revision update (later, separate task): an explicit update plan that
  compares the local Skill's current revision id and digests with the
  receipt baseline; if equal, create one new revision from the new release;
  pins and publication stay unchanged; rollout remains the separate admin
  action. If not equal, offer a new copy. No automatic pin movement.
- Export: "Export package" on Assistants, Apps, Skills (Flows exist).
  Omissions listed in provenance. Audited.
- Publish from Eneo: later (`release:submit`), review stays in the Hub.

Install targets: personal space, shared space, organisation (admin). MCP
server packages and organisation-level installs: tenant admin. Flows: the
existing Flow authoring permission. The wizard shows only allowed targets
and names the missing permission otherwise.

Audit (Eneo): connection changes; install started, completed, failed with
listing, version, digest, target, actor; export; download.

## 7. Shared contract and DX

- One installable contract artifact: a versioned Python wheel with a
  digest, built from the Eneo repository (`packages/eneo-package-contract`),
  containing the archive mechanics, the per-kind validators and fixtures.
  First prove a standalone Flow validator with explicit dependencies (move
  the canonical portable definitions out of `eneo.flows` rather than
  copying them); add kinds only with validator, importer and fixtures.
- Compatibility matrix: the Hub pins a contract version and tests against
  the supported Eneo versions; Eneo's connector pins the Hub HTTP contract
  and tests against a running Hub in CI, not only recorded responses.
- Fixtures per kind under `examples/packages/`, shared by both repositories,
  docs and the local dev setup. Adversarial archives included.
- Local dev: `docker compose --profile marketplace up` starts a Hub with a
  seeded allowlist and example listings.

## 8. UX details

Hub (publisher and curator):
- Publish wizard: upload → validation report (limit and path named) →
  derived prerequisites with editable notes → description checklist (what
  it does, who it is for, how it works, what it needs, how to test, known
  limits) → screenshots → version and changelog → submit. Preview as Eneo
  users will see it.
- Curator review: complete content left, listing text right, validation
  report, prerequisites, review checklist, approve or reject with a reason.
- Listing page: title, kind, publisher, maintenance badge, latest version,
  summary, prerequisites, description, how it works, screenshots, versions
  with changelog, "Download .eneopkg" per version, "Open in my Eneo".

Eneo (both apps; Svelte first because the Flow dialog exists there, web-next
parity inside the same vertical before it is done):
- Marketplace entry when connected and allowed.
- Browse: search, kind, category, language; cards with kind, publisher,
  version, maintenance badge, summary, prerequisite icons.
- Detail: listing text, package-level compatibility (profile and Eneo
  version), known prerequisites (models, Functions, MCP servers, compute
  for scripts). No "works here" promise before a target is chosen.
- Install wizard (existing Flow import dialog, extended per kind): 1 target,
  2 plan (mappings, conflicts, missing permissions, install and publish
  blockers, unknown states), 3 complete content preview, 4 confirm,
  5 result with links and receipt. Errors keep state.
- Installed resources: "From marketplace: listing vX", newer-version notice,
  yank/revoke warning, last checked.
- Admin › Marketplace: connection, token status, who may browse, installs log.
- Swedish and English, WCAG 2.2 AA, text never colour alone.

## 9. Governance summary

Publish: onboarded organisations, publisher role per organisation, curator
approval, separation of duties, maintainer contact, stale flagging,
yank/revoke. Install: local permission for the whole creation graph, admin
for tenant-wide kinds, complete content shown, audit on both sides. Never:
remote changes, credentials or knowledge exported, automatic updates,
execution at install time.

## 10. Delivery plan

Flow-only end to end first, complete (receipts, withdrawal checks, failure
recovery, audit). Then Skills, Assistants with nested Skills, Apps, MCP.

Eneo repo:
- E0 Contract artifact: standalone Flow validator with explicit dependencies,
  wheel build, fixtures, adversarial cases. (start now)
- E1 Connector + Admin › Marketplace: settings, encrypted token, discovery,
  catalogue projection, download + verify, audit, who may browse. (start
  now against a running dev Hub from H0/H2)
- E2 Flow install from Marketplace in Svelte: browse, detail, the extended
  Flow import dialog, bound confirmation and recheck, receipt with Hub
  fields in `flow_package_imports`, installed badge, withdrawal warning,
  update notice. web-next parity in the same task.
- E3 Skill vertical: `skill` kind (#663 bytes), planner authorizes
  `SKILLS_MANAGEMENT`, receipt with revision baseline, export button.
- E4 Assistant and App verticals: dispositions above, nested Skills, MCP and
  Function requirement slots, planner authorizes the full graph, export
  buttons. App Skills eager and script-free.
- E5 MCP server vertical: closed definition, explicit unconfigured-disabled
  creation in the MCP owner, no network at import.
- E6 Docs: user guide, publisher guide with the checklist, operator guide.
- Later: Skill revision update plan; publish from Eneo; install telemetry.

Hub repo:
- H0 Skeleton: FastAPI + Postgres + Compose, allowlist, magic-link login via
  a library, organisations and roles, audit, OpenAPI, CI running the
  contract fixtures. (start now)
- H1 Listings and releases: quarantine upload, validation with the contract
  wheel, draft/submit/review/publish with frozen bytes and reviewed-metadata
  hash, yank/revoke, maintenance status, versions and changelog.
- H2 Catalogue API, instance enrollment and tokens, download with digest,
  audience checks on every read.
- H3 Hub UI: browse, listing page, publish wizard, curator review, admin.
- H4 Pilot: two instances, one Flow; outage, yank, token rotation,
  backup/restore. Then one Skill with a script and one Assistant with
  nested Skills when E3/E4 land.

## 11. Open decisions for the product owner

1. Token-based instance auth with approved enrollment (proposed) vs the
   ADR's private_key_jwt/mTLS.
2. Postgres for package bytes (proposed) vs object storage from day one.
3. Browse for all signed-in Eneo users (proposed) vs admins only.
4. Hub front end: Next.js + Astryx static export (proposed) vs server
   templates.
5. Publish from Eneo in v1 or later (proposed later).
6. Magic-link login (proposed) vs OIDC from day one.

## 12. Non-goals

Federation, signing, auto-update or merge, automatic pin movement,
knowledge bundles, per-user audiences, remote install, iframes or remote
JavaScript, a generic installer, a plugin system, Solution Bundles,
module distribution (later), public anonymous access, install telemetry
in the first delivery, "works here" before target selection.
