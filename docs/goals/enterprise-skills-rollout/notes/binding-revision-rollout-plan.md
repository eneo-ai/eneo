# Implementation plan: update bindings to the published version

Board task: `docs/goals/enterprise-skills-rollout/state.yaml`, the controlled
rollout worker task. Product contract:
`docs/enterprise-skills-roadmap.md#controlled-rollout-of-a-published-revision`
and `docs/adr/marketplace-hub-package-portability-and-skills.md` lines 519-538.

This is a plan only. No production code or tests are written yet.

Every claim below was re-verified against the worktree at `af6c81e9a`.

---

## 1. What the operation is

A tenant administrator, on the organisation Skill detail page, previews and then
explicitly advances existing pins for one organisation Skill from one expected
old revision to one expected currently published revision.

- Swedish label: **Uppdatera kopplingar till publicerad version**
- English label: **Update bindings to the published version**

It changes `skill_revision_id` and nothing else. It never adds or removes a
binding, never changes `position` or `activation_mode`, never moves
`skill_space_id`/`skill_id` (source identity is derived from the Skill's Space at
read time — `skill_repo_impl.py:1433-1436`, `:1504-1508` — so leaving those
columns alone is what preserves it), never calls a parent-save command, and never
overwrites a concurrent edit.

---

## 2. Three findings that reshape the task

### 2.1 Personal Chat is one row, not a fleet

`GovernancePolicies` carries
`UniqueConstraint("tenant_id", "scope", name="uq_governance_policies_tenant_id_scope")`
(`backend/src/eneo/database/tables/governance_policy_table.py:56-58`). There is
at most one `PERSONAL_DEFAULT_ASSISTANT` policy per tenant, and
`GovernancePolicySkillBindings` has PK `(policy_id, skill_id)`
(`skill_table.py:342-346`). Therefore **at most one Personal Chat binding row
exists per (tenant, Skill)**. The domain already models it that way:
`SkillAdoptionSummary.personal_chat` is a single optional value and
`SkillAdoptionRevisionCount.personal_chat_pinned` is a `bool`
(`skills/domain/skill.py:369-391`).

Personal Chat needs no cursor, no pagination, and no
`SkillAdoptionResourceKind` member.

### 2.2 The real fit owner is not the private method

`AssistantService._validate_skill_activation_fit`
(`assistant_service.py:563-658`) is not a calculator. It is an orchestration and
rejection-message mapper over three things that are already shared owners:

- `SkillTurnPlan.to_activation_runtime()` (`skills/domain/skill.py:952-982`) —
  the single selective-fit owner named by the completed slice-5A constraint;
- `assert_prompt_and_files_fit_context` — the context-window guard;
- `CompletionService.prepare_skill_activation_preflight`
  (`completion_models/infrastructure/completion_service.py:157-208`) — a
  deterministic, **local** upper bound. It performs no live MCP discovery and no
  network call; it reads the persisted, permission-filtered MCP catalogue.

The expensive, genuinely duplicable part is not the calculator — it is the ~80
lines of *input assembly* in `_validate_attachments_fit`
(`assistant_service.py:660-737`): governance resolution, vision-derived prompt
files, MCP narrowing, the knowledge exclusion, and the governed base
instructions. That assembly is what a second implementation would inevitably
re-derive, and re-deriving it is the stop condition.

### 2.3 Personal Chat's validator is already a tenant-wide unpaginated scan

`AssistantService.assert_personal_default_governance_context_fit`
(`assistant_service.py:756-871`) validates the candidate baseline against **every**
personal-default Assistant in the tenant, loaded in one query by
`AssistantRepository.get_personal_defaults_for_tenant`
(`assistant_repo.py:558-603`) with eager `selectinload`s for user, roles,
attachments, template and MCP servers. It is unpaginated by design ("The scan is
intentionally linear").

This is the canonical Personal Chat fit owner. Reusing it is mandatory. It is
also the reason one line of the task's `verify` list cannot be met as written —
see section 9.

---

## 3. Decision 1 — how the shared fit function is reused

**Recommendation: promote the method on `AssistantService`, keep the assembly
there, and inject `AssistantService` into `OrganizationSkillService`.**

Concretely:

1. Rename `_validate_skill_activation_fit` → `validate_skill_activation_fit`
   (public, same signature). Three existing call sites move with it
   (`:731-737`, `:802-813`, `:864-871`).
2. Add **one** new public entry point on `AssistantService` that owns the
   assembly for a hypothetical pin:

   ```python
   async def assert_assistant_fits_candidate_pin(
       self,
       *,
       assistant: Assistant,
       space_is_personal: bool,
       candidate_bindings: list[ResolvedSkillBinding],
       preflight_adapter: CompletionModelAdapter | None = None,
   ) -> None
   ```

   It runs the same body as `_validate_attachments_fit`, except that
   `_create_skill_turn_plan` takes the candidate binding list instead of
   re-reading the stored one. That means one new optional parameter threaded
   through `_create_skill_turn_plan` / `_resolve_assistant_skill_runtime`, not a
   parallel path. Ordinary save keeps calling it with the stored bindings.
3. Wire `assistant_service` into `organization_skill_service` in
   `main/container/container.py`. The `organization_skill_service` provider
   (`:1032-1036`) must move below `assistant_service` (`:1259-1283`);
   `org_space_assistant_role_service` (`:1284-1297`) is the existing precedent
   for depending on `AssistantService`. Import it under `TYPE_CHECKING` only, as
   `OrganizationSkillService` already does for `SpaceService`
   (`organization_skill_service.py:33-34`), so no import cycle appears.

**What it costs.** `OrganizationSkillService` stops being a leaf service and
gains a heavy collaborator: `AssistantService` pulls roughly twenty providers.
Constructing it per request for a rollout endpoint is not free, and any future
change to `AssistantService`'s constructor now also touches the rollout path.

**Why the alternatives are worse.**

- *Extract to a neutral module.* The calculator is already neutral
  (`SkillTurnPlan`, `SkillActivationRuntime`). Extracting only the wrapper moves
  ~90 lines and still leaves the assembly in `AssistantService`, so the rollout
  would have to re-derive governance resolution, vision expansion and MCP
  narrowing — exactly the second fit calculation the stop condition forbids.
  This looks like the clean option and is the trap.
- *Inject a one-method protocol.* That is the "one-method interface" the
  repository standard rejects, and it hides which owner is really running.
- *Write the pin, validate, roll back a savepoint.* Attractive because it reuses
  the save path byte-for-byte, but it makes a read-only preview write rows, and
  a nested transaction per target across a 10 000-target preview is a worse
  trade than one optional parameter.

**Reused exactly once.** `validate_skill_activation_fit` remains the only place
that turns a plan plus a model into a verdict; `assert_assistant_fits_candidate_pin`
remains the only place that assembles its inputs for an Assistant; and Personal
Chat keeps using `assert_personal_default_governance_context_fit` unchanged.

---

## 4. Decision 2 — Personal Chat as a target

**Recommendation: Personal Chat is a first-class target in PR 1, and it is
deliberately *not* made paginable.**

What it takes: nothing structural. One row, located by the predicate that
already exists in `_organization_adoption_facts`
(`skill_repo_impl.py:223-238`) — `GovernancePolicySkillBindings` joined to
`GovernancePolicies` where `scope == PolicyScope.PERSONAL_DEFAULT_ASSISTANT` and
both rows are tenant-scoped. One guarded `UPDATE`. One call to the existing
`assert_personal_default_governance_context_fit`.

What is explicitly **not** done, and why:

- No `SkillAdoptionResourceKind.PERSONAL_CHAT`. The enum drives
  `SkillAdoptionCursor` (`skills/domain/skill.py:83-113`) whose only job is
  paginating a fleet. Adding a member for a cardinality-one target adds a cursor
  branch, a seek clause and a page-boundary test for a page that can never have a
  second item.
- No `(skill_id, policy_id)` index. The existing
  `ix_governance_policy_skill_bindings_skill_id` (`skill_table.py:386-389`)
  already resolves the single row.

Why PR 1 and not later: Personal Chat is the highest-value single target in the
feature — it is every employee's chat — and it is the only target whose rollout
needs neither pagination, nor a durable operation, nor chunking, nor
cancellation. It is the thinnest slice that proves the whole contract end to end:
admin gate, expected-value guard, exact-pin-only write, shared fit reuse,
body-free audit receipt, and the confirm-dialog UI.

---

## 5. Decision 3 — operation persistence

**Recommendation: PR 1 persists nothing. The operation tables arrive in PR 2,
when Assistants do.**

### 5.1 Why PR 1 needs no row

One row, one transaction, one HTTP request. Idempotency falls out of the
expected-old-pin guard: a second apply finds the pin already at the target
revision and returns a typed no-op, which is precisely the precedent
`create_revision` already sets (`skill_repo_impl.py:1047-1058`). Resumability and
cancellation are meaningless for a single-statement change. Adding a durable
operation row to PR 1 would be infrastructure for a hypothetical need.

### 5.2 The two tables, from PR 2

Skills-owned, Skill-named, no polymorphic target column, no generic jobs
framework.

`skill_revision_rollouts` — one row per operation. Shape borrowed from
`ObjectContentReconciliationState`
(`database/tables/object_content_table.py:558-614`): a resume cursor plus a
lease, without its singleton `id = 1` constraint.

| column | type | notes |
| --- | --- | --- |
| `id` | uuid PK | |
| `tenant_id`, `skill_id` | uuid | FK `(tenant_id, skill_id)` scoped like the binding tables |
| `from_revision_id`, `to_revision_id` | uuid | FK to `skill_revisions (skill_id, id)` |
| `state` | varchar(32) | CHECK IN `('preparing','ready','applying','completed','cancelled','failed')` |
| `idempotency_key` | text | UNIQUE `(tenant_id, skill_id, idempotency_key)` |
| `requested_by_user_id` | uuid | `ON DELETE SET NULL`, as `ObjectContentMoves` does |
| `discovery_cursor` | text | serialized `SkillAdoptionCursor`; null once discovery completes |
| `apply_cursor` | text | null until apply starts |
| `prepared_count`, `ready_count`, `excluded_count`, `applied_count`, `skipped_count`, `failed_count` | integer | CHECK `>= 0` |
| `failure_code` | varchar(64) | CHECK IN `('publication_changed','unpublished','execution_blocked','revision_missing')`; CHECK `state <> 'failed' OR failure_code IS NOT NULL` |
| `lease_owner` / `lease_until` | varchar(128) / timestamptz | pair CHECK, as the reconciliation state does |
| `created_at`, `updated_at` | timestamptz | |

Partial unique index: at most one non-terminal rollout per `(tenant_id,
skill_id)`.

`skill_revision_rollout_targets` — one row per Assistant target. Shape borrowed
directly from `ObjectContentMoves` (`object_content_table.py:267-346`).

| column | type | notes |
| --- | --- | --- |
| `rollout_id`, `assistant_id` | uuid | composite PK |
| `tenant_id`, `space_id` | uuid | tenant scoping on every read |
| `state` | varchar(32) | CHECK IN `('ready','excluded','applied','skipped','failed')` |
| `pinned_revision_id` | uuid | the pin observed at preparation |
| `failure_code` | varchar(64) | CHECK IN `('context_incompatible','no_completion_model','on_demand_not_activatable','concurrent_change','pin_absent','target_missing')` |
| `failure_detail` | varchar(512) | CHECK `char_length <= 512` |
| `attempt_count` | integer | CHECK `>= 0` |
| `next_attempt_at` | timestamptz | nullable |

No Skill body, prompt, instruction text, tool result, credential or incident
reason is stored. `failure_detail` carries a bounded operator hint only.

### 5.3 Migration sketch

One revision, `backend/alembic/versions/2026MMDDHHMM_add_skill_revision_rollouts.py`,
following the naming of `202607231330_add_skill_adoption_cursor_indexes.py`.

```
upgrade():
  op.create_table("skill_revision_rollouts", ...)   # columns + CHECKs above
  op.create_index("ix_skill_revision_rollouts_tenant_skill_state", ...)
  op.create_index("uq_skill_revision_rollouts_open", ..., unique=True,
                  postgresql_where=state NOT IN ('completed','cancelled','failed'))
  op.create_table("skill_revision_rollout_targets", ...)
  op.create_index("ix_skill_revision_rollout_targets_rollout_state", ...)
downgrade():
  drop both indexes and both tables, newest first
```

Round-trip tested under `backend/tests/integration/migrations/`.

### 5.4 Execution model — no background worker

Chunks are driven by the admin's browser, not by ARQ. `POST
.../rollout/{rollout_id}/advance/` processes one bounded chunk (25 targets) in
one transaction and returns the updated state and counts; the dialog loops while
it is open.

This yields, with no new infrastructure:

- **resumability** — the cursor is durable, so reopening the page continues;
- **cancellation** — a `cancelled` state checked at the top of each chunk, no
  cooperative-cancel plumbing, no Redis flag as in
  `audit/infrastructure/export_job_manager.py`;
- **idempotency** — chunk boundaries are transaction boundaries;
- **bounded lock scope** — locks are held for one chunk, never for the fleet.

`lease_owner`/`lease_until` stay, cheaply, so two admins driving the same rollout
from two tabs cannot interleave chunks.

`eneo/jobs/` is a thin ARQ enqueue layer with no cursor, lease, attempt count or
cancel flag. It is not used, not extended, and no framework is built over it.

---

## 6. Decision 4 — audit

**New action type.** `ActionType.SKILL_BINDINGS_ADVANCED = "skill_bindings_advanced"`
in `audit/domain/action_types.py`, after `SKILL_DELETED` (`:55-61`). "Advanced"
names the narrow pin-advance authority and cannot be misread as a parent save,
which the ADR requires the rollout never to impersonate.

**Category mapping.** `ActionType.SKILL_BINDINGS_ADVANCED.value: "user_actions"`
in `audit/domain/category_mappings.py`, beside the other `SKILL_*` entries
(`:66-72`). A new action type is inert without this row.

**Where it is emitted.** From the router, as every Skill audit event already is
(`organization_skill_router.py:357-393`), guarded so nothing is logged when
nothing changed. Never from the service.

**Shape — body-free.**

```python
AuditMetadata.standard(
    actor=user,
    target=skill,
    changes={"pinned_revision": {"old": from_revision_number,
                                 "new": to_revision_number}},
    extra={
        **skill_audit_extra(skill),          # skills/presentation/skill_audit.py:14-25
        "from_revision_id": str(...),
        "to_revision_id": str(...),
        "scope": ["personal_chat"],           # + "assistant" from PR 3
        "advanced_count": ..., "skipped_count": ...,
        "excluded_count": ..., "failed_count": ...,
        "failure_codes": [...],               # distinct codes, closed set, bounded
        "rollout_id": str(...),               # from PR 2 on
    },
)
```

`skill_audit_extra` is what "body-free" means here: identity, digest and
`instruction_length`, never instructions.

**Not `AuditMetadata.multi_target`.** The scout flagged it as the natural batch
shape (`audit/application/audit_metadata.py:22-27`), but it materialises a list
of targets. At 10 000 Assistants that is an unbounded audit payload and forces
the whole target set into memory to write one row. Use `standard` with the Skill
as the single target and bounded aggregate counts instead.

**Cardinality.** Exactly one event per rollout, written when it reaches a
terminal state (`completed`, `cancelled`, `failed`). One event per chunk would
flood the log; a start event plus an end event would double every receipt for no
extra fact. In PR 1 the operation is synchronous, so terminal is the single
request.

---

## 7. The PR sequence

Three PRs. Each is independently shippable, behavior-tested, and updates the
docs-site in the same change.

### PR 1 — Personal Chat pin advance

*Observable behavior.* On the organisation Skill detail page, when the Personal
Chat pin is behind the published revision, an administrator sees which revision
it is on and which it would move to, and a button labelled **Uppdatera kopplingar
till publicerad version**. Confirming updates that one pin. Position, activation
mode, source identity and every other Governance Policy field are unchanged.
Non-admins never see the affordance and are refused by the API. The action fails
closed, with its own reason code and recovery copy, when the Skill is execution
blocked, is not currently published, has been published to a different revision
since the preview, has been edited concurrently, or when the new revision does
not fit the personal-default fleet's context.

*Canonical owners extended.* `OrganizationSkillService` (authorization and
lifecycle, `_require_admin` at `:58-63`), `SkillRepo` (discovery and the guarded
write), `AssistantService` (fit).

*Reused.* `require_session_auth` on the router (`organization_skill_router.py:37-41`
— it already denies API keys, which covers the scoped-key half of the `verify`
list); `_require_admin`; the Personal Chat predicate from
`_organization_adoption_facts`; the lock/re-read/compare/typed-error guard from
`publish_organization` (`skill_repo_impl.py:1143-1163`) and
`unblock_organization_skill` (`:1341-1366`); the no-op short-circuit from
`create_revision` (`:1047-1058`); `assert_personal_default_governance_context_fit`
unchanged; the `ErrorCodes` conflict contract and its Swedish/English recovery
copy landed in `#619`; `skill_audit_extra`; the `AlertDialog` +
saving/error pattern from the publication block (`+page.svelte:568-604`).

*Created.* Two endpoints (`GET .../organization/{skill_id}/binding-rollout/preview/`,
`POST .../organization/{skill_id}/binding-rollout/`, the latter carrying
`expected_current_revision_id` and `target_revision_id`); two repo methods
(`get_personal_chat_pin`, `advance_personal_chat_pin`); one `ActionType` plus its
category mapping; the promoted `validate_skill_activation_fit`; one new reason
code; a confirm dialog inside `SkillAdoptionProjection.svelte`'s existing Personal
Chat section (`:248-271`); message keys in `en.json`/`sv.json`; regenerated
`eneo-js` endpoint and schema; a `## Versions and adoption` addition to
`frontend/apps/docs-site/src/content/guides/skills.mdx`.

*Acceptance criteria.*
1. A tenant admin advances the Personal Chat pin from the expected old revision
   to the published revision; only `skill_revision_id` differs afterwards.
2. `position` and `activation_mode` on that row, and every other row in
   `governance_policy_skill_bindings` for that policy, are byte-identical before
   and after.
3. Every other Governance Policy field is unchanged.
4. A non-admin with `SKILLS` is refused; an API-key caller is refused with
   `session_auth_required`; a foreign-tenant Skill is a 404.
5. A stale `expected_current_revision_id` is a typed 409 with its own reason
   code, and nothing is written.
6. An active execution block, an unpublished Skill, and a target revision that is
   not the currently published one each fail closed with distinct reason codes.
7. A candidate revision that pushes a personal-default Assistant past its context
   window is rejected with the same message ordinary governance save produces.
8. Repeating the successful call is a typed no-op and emits no second audit
   event.
9. Exactly one `skill_bindings_advanced` audit row, containing no instruction
   text.

*Test plan.* Integration tests in `backend/tests/integration/skills/` for 1-3 and
5-8, following `test_skill_conflict_contract.py` and `test_skill_concurrency.py`;
a concurrency test that interleaves a governance save and a rollout and asserts
the skip; unit tests in `backend/tests/unittests/skills/` for the service
authorization matrix (4); an audit assertion for 9; frontend component tests in
`organization-skill-detail.svelte.test.ts` for the dialog, the disabled states,
the error surfaces and Swedish/English copy.

*Explicitly defers.* Assistants, Apps, the operation tables, chunking,
cancellation, resumability, 10 000-target evidence.

### PR 2 — Durable operation and Assistant preview

*Observable behavior.* An administrator starts a rollout for a Skill with
Assistant bindings behind the published revision. The dialog reports preparation
progress, then an exact ready count, an already-current count, and an excluded
count broken down by reason. No binding is written. Closing and reopening the
page resumes preparation where it stopped. Cancelling stops it at the next chunk
boundary and leaves nothing applied.

*Canonical owners extended.* `SkillRepo` gains target discovery and operation
persistence; `OrganizationSkillService` gains the operation lifecycle;
`AssistantService.assert_assistant_fits_candidate_pin` from PR 1 does the
per-target verdict.

*Reused.* `SkillAdoptionCursor` restricted to `ASSISTANT`, whose
`(skill_id, assistant_id)` index already exists
(`202607231330_add_skill_adoption_cursor_indexes.py:33-50`); the `limit + 1`
overfetch and seek logic (`skill_repo_impl.py:563-587`);
`OperationLeaseCheckpoint` (`object_content/lease.py:24+`);
`CompletionService.load_skill_activation_preflight_adapters` (`:210-219`) to load
each distinct model adapter once per chunk rather than once per target.

*Created.* The migration and two tables; a cursor-paginated batch Assistant
loader modelled on `get_personal_defaults_for_tenant` (`assistant_repo.py:558-603`)
but bounded per chunk, carrying `has_knowledge` and configured MCP servers so
each chunk is a fixed number of queries regardless of chunk size; preview and
advance endpoints; the operation state block in the frontend, built from `Badge`,
`Alert`, `Button` and `Table` (there is no `progress` component installed, so
progress is stated as "N of M prepared" text with `aria-live="polite"`, not a
bar).

*Acceptance criteria.* Bounded memory and a fixed query count per chunk at 10 000
Assistant targets; a stable cursor across concurrent binding inserts and deletes;
exclusions carry a typed reason; resume after an interrupted preparation
continues from the cursor and does not re-prepare a prepared target;
cancellation is honoured at the next chunk boundary; a second start with the same
idempotency key returns the existing rollout.

*Test plan.* A scale test that seeds 10 000 Assistant bindings and asserts the
per-chunk query count and peak row count; cursor-stability tests; resume and
cancel integration tests; frontend tests for the progress, ready, excluded and
cancelled states.

*Explicitly defers.* Writing to Assistant pins; Apps.

### PR 3 — Apply to Assistant pins

*Observable behavior.* From a ready preview, the administrator applies. Pins
advance in bounded chunks. An Assistant edited since preparation is skipped, not
overwritten. If the Skill is unpublished, published to a different revision, or
execution blocked mid-rollout, the operation stops with a typed terminal failure
and requires a fresh preview; pins already advanced are not reverted. One audit
receipt is written at the terminal transition.

*Canonical owners extended.* `SkillRepo` gains `advance_assistant_pin` — a
guarded in-place `UPDATE` of `skill_revision_id` only, safe because the
`(skill_id, skill_revision_id)` FK is `DEFERRABLE INITIALLY DEFERRED`
(`skill_table.py:242-249`). This is the first in-place binding write; the three
existing write paths (`replace_assistant_bindings` `:1774-1803`,
`replace_app_bindings` `:1862-1888`, `replace_policy_bindings` `:1920-1948`) are
delete-then-bulk-insert and are left alone.

*Reused.* `lock_assistant_space_for_update` (`:1718-1725`) per target;
`_lock_organization_skill` (`:1127-1141`) per chunk for the publication/block
recheck; the PR 1 audit shape.

*Acceptance criteria.* Only `skill_revision_id` changes, proven by a row-level
before/after comparison over all binding columns; a concurrent parent save
between preparation and apply produces `concurrent_change` and leaves the pin
alone; unpublish, republish and block during apply each stop the rollout with a
distinct terminal `failure_code`; partial failure leaves applied pins applied and
the operation resumable or restartable; one audit event with the aggregate counts.

*Explicitly defers.* Apps, which are the next board task, an eager-only extension
with its own acknowledgement and queued-snapshot proof.

---

## 8. Constraints this plan holds itself to

- One fit calculation. `SkillTurnPlan.to_activation_runtime()` stays the only
  selective-fit owner; `validate_skill_activation_fit` stays the only verdict
  wrapper; the assembly stays in `AssistantService`.
- No generic jobs or bulk-operation framework, no second token counter, no
  parallel binding API, no pass-through service, no one-method interface.
- Tenant isolation is the existing `_organization_scope`
  (`skill_repo_impl.py:191-197`) and the existing `tenant_id` predicates on every
  binding table. No new multi-tenancy abstraction.
- Frontend uses only installed shadcn-svelte components. There is no `progress`
  component; progress is text with `aria-live="polite"`.
- Swedish copy is drafted as Swedish product language, not a translation of the
  English, and keeps the word "Skill" as the codebase already does
  (`organization_skills_adoption_heading` = "Kopplingar och uppdateringsstatus").
- No board task IDs appear in production code, test names, branch names or PR
  titles.
- Each PR updates `frontend/apps/docs-site/src/content/guides/skills.mdx` in the
  same change.

---

## 9. Risks, and what the `verify` list cannot deliver as written

### 9.1 Biggest risk — the bounded-memory claim collides with the mandated fit owner

`verify` asks for "Ten-thousand-target bounded memory, lock scope, stable cursor,
and no N+1 target loading". For the Assistant fleet this plan delivers it.

For **Personal Chat it cannot be delivered**, because the only permitted fit
owner, `assert_personal_default_governance_context_fit`, loads every
personal-default Assistant in the tenant in a single unpaginated query with eager
`selectinload`s (`assistant_repo.py:584-603`) and validates them linearly. At
10 000 users, advancing the one Personal Chat pin materialises 10 000 Assistant
aggregates with their attachments and MCP servers.

Writing a bounded version would be a second fit calculation — an explicit stop
condition. The honest resolution is:

- state the carve-out in the PR: bounded-memory evidence covers the Assistant
  fleet path; Personal Chat inherits the existing governance-save scan and is
  neither better nor worse than saving the Personal Chat policy today;
- record a separate, bounded follow-up to paginate that scan for **both** the
  governance save path and the rollout, so one change fixes one owner.

This should be agreed before PR 1 starts. It is the one place where the task as
written and the constraints as written point in opposite directions.

### 9.2 "Exact ready preview" needs a stated meaning

`verify` asks for an "exact ready preview"; `stop_if` forbids achieving stability
by copying parent or Skill content into operation rows. Both hold only under one
reading, which the PRs must state plainly: **the preview is exact as of
preparation**, and apply re-validates each target inside its own transaction
before writing, so a target whose model, prompt or attachments changed in between
becomes `skipped` or `failed` rather than silently wrong. Nothing is copied; the
guarantee is "no wrong write", not "the number cannot move".

Without that sentence, a reviewer can reasonably read "exact" as a guarantee at
apply time, which is unachievable without snapshotting parent content.

### 9.3 "Cancellation" cannot mean interrupting a chunk

With admin-driven chunking there is no in-flight process to signal. Cancellation
is honoured at the next chunk boundary, and already-advanced pins are not
reverted — which the roadmap already states ("completed pins are not silently
reverted", `docs/enterprise-skills-roadmap.md:988`). Say so in the UI copy; do
not build a cooperative-cancel mechanism to close the gap.

### 9.4 The preflight runs under the administrator's identity

`prepare_skill_activation_preflight` builds MCP identity headers from
`self.user` (`completion_service.py:180`), which during a rollout is the
administrator, not the Assistant's owner. There is no live discovery and tools
come from the persisted permission-filtered catalogue, so no cross-user data is
read — and `assert_personal_default_governance_context_fit` already behaves this
way today when an admin saves the Personal Chat policy. It is precedent, not a
new leak, but it should be named in the security review of PR 2 rather than
discovered there.

### 9.5 Lower-order risks

- Moving the `organization_skill_service` provider below `assistant_service` in
  the container touches a heavily shared file. Keep it a single mechanical move
  in PR 1 with no other container edits.
- `advance_assistant_pin` is the first in-place binding write. The FK is
  deferrable so it is transaction-safe, but the PR 3 review should confirm no
  read path assumes bindings are only ever replaced wholesale.
- Three PRs mean the button exists with Personal Chat scope only after PR 1. The
  dialog must state its scope explicitly so the affordance is honest rather than
  half-finished.
