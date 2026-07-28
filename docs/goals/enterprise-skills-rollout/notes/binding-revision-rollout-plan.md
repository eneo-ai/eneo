# Implementation plan: update bindings to the published version

Board task: `docs/goals/enterprise-skills-rollout/state.yaml`, the controlled
rollout worker task. Product contract:
`docs/enterprise-skills-roadmap.md#controlled-rollout-of-a-published-revision`
and `docs/adr/marketplace-hub-package-portability-and-skills.md:519-537`.

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

## 2. Four findings that reshape the task

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
also the only thing blocking a bounded-memory claim — see section 8.

### 2.4 The expected-old-pin guard makes re-running equivalent to resuming

`create_revision` (`skill_repo_impl.py:1047-1058`) already establishes the house
pattern: compare the caller's expected value, and when it already matches the
desired end state, short-circuit as a typed no-op instead of writing again.

Applied per binding, this scales. A guarded update
`WHERE assistant_id = ? AND skill_id = ? AND skill_revision_id = :old_revision`
matches zero rows once that pin has advanced. A second pass over the same fleet
therefore skips everything already done, without consulting any record of what
was done. **Re-running is resuming.** This is the finding that decides section 5.

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
  the save path byte-for-byte, but it makes a read-only check write rows, and a
  nested transaction per target across a 10 000-target pass is a worse trade
  than one optional parameter.

**Reused exactly once.** `validate_skill_activation_fit` remains the only place
that turns a plan plus a model into a verdict; `assert_assistant_fits_candidate_pin`
remains the only place that assembles its inputs for an Assistant; and Personal
Chat keeps using `assert_personal_default_governance_context_fit` unchanged.

---

## 4. Decision 2 — Personal Chat as a target

**Recommendation: Personal Chat is a first-class target in PR 1, and it is
deliberately *not* made paginable.**

What it takes: nothing structural. One row, located by the predicate that already
exists in `_organization_adoption_facts` (`skill_repo_impl.py:223-238`) —
`GovernancePolicySkillBindings` joined to `GovernancePolicies` where
`scope == PolicyScope.PERSONAL_DEFAULT_ASSISTANT` and both rows are
tenant-scoped. One guarded `UPDATE`. One call to the existing
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
feature — it is every employee's chat — and it needs neither pagination, nor
chunking, nor any notion of a multi-step operation. It is the thinnest slice that
proves the whole contract end to end: admin gate, expected-value guard,
exact-pin-only write, shared fit reuse, body-free audit receipt, confirm dialog.

---

## 5. Decision 3 — operation persistence: stateless chunked pass, no tables

**Recommendation: neither PR ships an operation table or a migration. The fleet
rollout is a stateless chunked pass driven by the administrator's browser.
Durable rollout rows become an evidence-gated follow-up.**

### 5.1 The design

`POST /api/v1/skills/organization/{skill_id}/binding-rollout/chunk/` with body
`{from_revision_id, to_revision_id, after}`. One call:

1. **Read phase, no locks.** Keyset-select up to 100 Assistant bindings for this
   Skill and tenant with `skill_revision_id = from_revision_id` and
   `assistant_id > after`, ordered by `assistant_id`. Batch-load their Assistant
   aggregates.
2. **Validate phase, no locks, no open write transaction.** For each target, call
   `assert_assistant_fits_candidate_pin`. Model adapters are loaded once per
   chunk via `load_skill_activation_preflight_adapters`
   (`completion_service.py:210-219`), not once per target.
3. **Write phase, one short transaction.** Lock the Skill
   (`_lock_organization_skill`, `skill_repo_impl.py:1127-1141`), re-check
   publication and execution block, then per passing target take
   `lock_assistant_space_for_update` (`:1718-1725`) and issue the guarded
   `UPDATE ... WHERE skill_revision_id = :from_revision_id`. A zero-row match is
   `concurrent_change`, not an error. Commit.
4. Return `{next_after, advanced, skipped, failed, failure_counts_by_reason}`.

The dialog loops until `next_after` is null. Validation, which is the expensive
part, is deliberately outside any lock so lock duration stays in milliseconds
regardless of chunk cost — this is what satisfies "bounded lock scope" honestly.

Cancellation is the client stopping the loop. Publication change, unpublication
or a new execution block is detected at step 3 and returns a typed terminal
failure that ends the run and requires a fresh start, as the ADR requires.

### 5.2 Judgement against the four points

**1. Re-scan cost — passes, and is cheaper than the durable design.**

`ix_assistant_skill_bindings_skill_id_assistant_id` on `(skill_id, assistant_id)`
(`skill_table.py:250-254`) supports the query as a forward index range scan:
`skill_id` is the equality prefix, `assistant_id > :after` is the range
condition, and the index order is exactly the required `ORDER BY`.
`skill_revision_id` and `tenant_id` are not in the index and are applied as heap
filters.

Because the cursor only moves forward, a run never re-reads what it already
walked. Total work for a full run is **one forward pass** over that Skill's
binding index entries plus one heap fetch each — roughly 10 000 index entries and
10 000 narrow heap tuples spread across 100 chunks. The durable design pays the
same pass during discovery, writes 10 000 target rows, and then pays a second
pass over the target table during apply. Stateless is one pass; durable is two
passes plus 10 000 inserts.

Worst case is a Skill where almost every binding is already current and one
straggler sits last: the final chunks walk the remaining entries to find it. That
is still bounded by the same single pass. No new index is needed, and none should
be added speculatively.

**2. The looping-failure problem — solved within a run, and intentionally not
solved across runs.**

Within a run the keyset cursor is the answer. A target that fails validation
stays on the old revision but is *behind* the cursor, so the next chunk starts
past it. The run terminates when a chunk returns no next cursor. There is no
loop.

Across runs, a fresh run starts at `after = null`, re-encounters that target,
re-validates it and reports it again. **That is the intended behavior and the
plan states it as such.** A rollout run is a pass over current truth, not a job
with memory. Between runs an administrator may have raised the model's context
window, removed an attachment or changed the Assistant's model — in which case
the target now passes. A durable `excluded` row would have been stale and would
have needed something to invalidate it. Re-evaluating is not a weakness of the
stateless design; it is the correct semantics, and the durable design would need
extra machinery to reproduce it.

**3. What is genuinely lost — the mid-run report, not the work.**

Two things do not survive a page reload:

- *Per-reason exclusion counts accumulated so far in this run.* The administrator
  loses the running tally, then re-runs. Every target already advanced is skipped
  instantly by the guard (finding 2.4), so the second run re-walks the index but
  re-validates only the targets still on the old revision — which are exactly the
  failures plus anything not yet reached. **The work is not lost; the report is.**
  For a fleet where most targets succeed, the second run is dramatically cheaper
  than the first.
- *A queryable rollout history.* This is covered by audit, not by a feature
  table. The roadmap's requirement is "a body-free, queryable receipt with actor,
  scope, counts, outcomes, and reason codes"
  (`docs/enterprise-skills-roadmap.md:278-279`). The audit log is the queryable
  compliance store; a `skill_revision_rollouts` table would be a second, weaker
  one with no retention or export story. Section 6 shows the receipt carrying
  every field that sentence asks for.

Quantified for a tenant administrator: the cost is re-running a bounded pass
after an accidental reload, and not being able to ask "what happened three weeks
ago" anywhere except the audit log — which is where they would look anyway.

**4. Concurrency — the per-target guards make interleaving harmless.**

Two administrators in two tabs on the same Skill and the same `from`/`to` pair
may select overlapping chunks. Every write is
`UPDATE ... WHERE skill_revision_id = :from_revision_id` under
`lock_assistant_space_for_update`, so the second writer matches zero rows and
records `concurrent_change`. Nothing is double-applied, nothing is corrupted, and
the wasted work is duplicate validation CPU. Two administrators running different
`from` revisions address disjoint row sets and cannot interact at all. If one
publishes a new revision mid-run, the other's step-3 recheck under the Skill lock
catches it and terminates that run.

`lease_owner`/`lease_until` would buy one thing: a friendlier "another
administrator is running this" message. That UX nicety does not justify two tables
and a migration.

### 5.3 The genuine casualty the four points do not cover

`ADR:529-533` states: "An exact preview across thousands of heterogeneous
resources requires durable, bounded work... The Skills owner therefore gets one
concrete, resumable operation with an idempotency key, closed lifecycle, bounded
aggregate counts, stable cursor, and body-free target outcomes."

Most of that survives statelessly. The idempotency key becomes semantic rather
than synthetic — `(skill_id, from_revision_id, to_revision_id)` — which is
stronger, because it cannot drift from what the operation actually does. Bounded
aggregate counts, stable cursor and body-free target outcomes are all delivered
per chunk.

Two clauses do not survive:

- **"Exact preview."** Statelessly, the pre-run preview is provisional: it shows
  what the already-shipped adoption summary computes for free —
  `behind_published_count` and the per-revision counts
  (`skill_repo_impl.py:614-742`) — plus a plain statement that each binding is
  checked before it is updated and may be excluded. Exactness arrives per chunk,
  at the moment of commit.
- **"Durable... closed lifecycle."** The run's lifecycle lives in the
  request/response cycle, not in a row.

This is a **product contract change and must be decided, not assumed.** The plan
recommends accepting it, for three reasons:

1. Nothing irreversible happens to an excluded target — it is left exactly as it
   was. Pre-knowledge of exclusions is informative, not protective.
2. The administrator gets the same protection sooner and cheaper: **the first
   chunk is the sample.** Run one chunk of 100, see the exclusion rate, and stop
   if it is unacceptable. That is a better decision aid than a whole-fleet preview
   that costs a full validation pass before anything useful happens.
3. An exact whole-fleet preview costs a complete validation pass, which is the
   expensive half of the operation. Paying it twice — once to preview, once to
   apply — doubles the cost of the feature to buy information the first chunk
   already provides.

If this is rejected, the durable tables come back and PR 2 grows accordingly.
That is the one decision on which the shape of PR 2 turns, and it belongs to
whoever owns the ADR.

`docs/adr/marketplace-hub-package-portability-and-skills.md` is in the task's
`allowed_files`; PR 2 amends `:529-537` in the same change to state provisional
pre-run counts, exact per-chunk outcomes, a semantic idempotency key, and
re-running as the resume mechanism.

### 5.4 If durable rows are needed later

Only on evidence — an operator asking for mid-run report persistence, or a
compliance need audit cannot serve. It would then be a third PR shipping two
tables: `skill_revision_rollouts` (state, cursors, bounded counts, closed
`failure_code` set, lease) modelled on `ObjectContentReconciliationState`
(`object_content_table.py:558-614`), and `skill_revision_rollout_targets` (state,
`failure_code`, bounded `failure_detail`, `attempt_count`) modelled on
`ObjectContentMoves` (`:267-346`). Not a generic jobs framework, not a
polymorphic target table, and not built now.

`eneo/jobs/` is a thin ARQ enqueue layer with no cursor, lease, attempt count or
cancel flag. It is not used and not extended.

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
(`organization_skill_router.py:357-393`), guarded so nothing is logged when no
pin changed. Never from the service.

**Cardinality — one event per chunk that changed at least one pin.** This is the
shape the stateless design forces and, on inspection, the more honest one: each
event corresponds to one committed transaction, so the log records what landed
and when. The alternatives are worse. One event per run cannot be written
reliably, because a run has no server-side terminal moment and the client's
accumulated totals must never be trusted in a compliance record. At 100 targets
per chunk a 10 000-binding rollout produces at most 100 events — far fewer than
the 10 000 the equivalent parent-save path would produce.

A server-generated `run_id`, minted on the first chunk and echoed through the
cursor, groups the events of one run. Tampering with it can only mis-group the
administrator's own events, since actor, tenant and Skill are all server-derived;
note this in review rather than defending against it.

**Shape — body-free.**

```python
AuditMetadata.standard(
    actor=user,
    target=skill,
    changes={"pinned_revision": {"old": from_revision_number,
                                 "new": to_revision_number}},
    extra={
        **skill_audit_extra(skill),          # skills/presentation/skill_audit.py:14-25
        "run_id": str(...),
        "scope": "personal_chat" | "assistant",
        "from_revision_id": str(...), "to_revision_id": str(...),
        "advanced_count": ..., "skipped_count": ..., "failed_count": ...,
        "failure_codes": [...],               # distinct, closed set, bounded
    },
)
```

`skill_audit_extra` is what "body-free" means here: identity, digest and
`instruction_length`, never instructions. Together these events carry actor,
scope, counts, outcomes and reason codes — the receipt the roadmap asks for
(`:278-279`).

**Not `AuditMetadata.multi_target`.** The scout flagged it as the natural batch
shape (`audit/application/audit_metadata.py:22-27`), but it materialises a list
of targets. Even per chunk it adds nothing over the counts, and it invites growing
the payload with the chunk size. Use `standard` with the Skill as the single
target.

---

## 7. The PR sequence

### PR 0 — Paginate the personal-default validation scan (enabler)

*Observable behavior.* None. Saving the Personal Chat Governance Policy behaves
identically; it stops loading the whole tenant's personal-default Assistants into
memory at once.

*Why it is first.* It is the only thing standing between this feature and an
honest bounded-memory claim (section 8), it fixes a pre-existing production risk
in an already-shipped path, and it is small.

*Change.* `AssistantRepository.get_personal_defaults_for_tenant`
(`assistant_repo.py:558-603`) gains keyset pagination on `Assistants.id` and
returns pages; `assert_personal_default_governance_context_fit`
(`assistant_service.py:815-871`) iterates pages instead of a list. The
complication is the MCP pre-pass at `:818-835`, which today builds projections for
the whole tenant and calls `space_repo.project_assistants_mcp_servers` once to
avoid an N+1 — that batching moves inside the page loop, preserving one projection
query per page instead of one per Assistant.

*Not a second fit calculation.* The verdict function is untouched. Every
Assistant is still validated by the same `validate_skill_activation_fit` call with
the same inputs; only the order and lifetime of the rows change. The stop
condition forbids a second compatibility calculation, not a change of loading
strategy.

*Acceptance criteria.* Identical accept/reject outcomes for the same tenant state
before and after; peak loaded Assistant count bounded by the page size at 10 000
personal defaults; one MCP projection query per page.

*Test plan.* The slice-5 governance tests merged in `#616` are the regression net;
add a bounded-memory/query-count test and a page-boundary test.

*Risk.* This path stabilised one day before this plan was written. Mitigation:
change only the loading strategy, add no branch to the verdict, and land it as its
own reviewable PR rather than folded into a feature slice.

### PR 1 — Personal Chat pin advance

*Observable behavior.* On the organisation Skill detail page, when the Personal
Chat pin is behind the published revision, an administrator sees which revision it
is on and which it would move to, and a button labelled **Uppdatera kopplingar
till publicerad version**. Confirming updates that one pin. Position, activation
mode, source identity and every other Governance Policy field are unchanged.
Non-admins never see the affordance and are refused by the API. The action fails
closed, with its own reason code and recovery copy, when the Skill is execution
blocked, is not currently published, has been published to a different revision
since the dialog opened, has been edited concurrently, or when the new revision
does not fit the personal-default fleet's context.

*Canonical owners extended.* `OrganizationSkillService` (authorization and
lifecycle, `_require_admin` at `:58-63`), `SkillRepo` (lookup and the guarded
write), `AssistantService` (fit).

*Reused.* `require_session_auth` on the router
(`organization_skill_router.py:37-41` — it already denies API-key callers, which
covers the scoped-key half of the `verify` list); `_require_admin`; the Personal
Chat predicate from `_organization_adoption_facts`; the
lock/re-read/compare/typed-error guard from `publish_organization`
(`skill_repo_impl.py:1143-1163`) and `unblock_organization_skill` (`:1341-1366`);
the no-op short-circuit from `create_revision` (`:1047-1058`);
`assert_personal_default_governance_context_fit` unchanged; the `ErrorCodes`
conflict contract and its Swedish/English recovery copy landed in `#619`;
`skill_audit_extra`; the `AlertDialog` + saving/error pattern from the publication
block (`+page.svelte:568-604`).

*Created.* One endpoint
(`POST .../organization/{skill_id}/binding-rollout/personal-chat/`, carrying
`from_revision_id` and `to_revision_id`); two repo methods
(`get_personal_chat_pin`, `advance_personal_chat_pin`); the
`SKILL_BINDINGS_ADVANCED` action type plus its category mapping; the promoted
`validate_skill_activation_fit` and the new `assert_assistant_fits_candidate_pin`
from section 3; the container provider move; one new reason code; a confirm dialog
inside `SkillAdoptionProjection.svelte`'s existing Personal Chat section
(`:248-271`); message keys in `en.json`/`sv.json`; regenerated `eneo-js` endpoint
and schema; a `## Versions and adoption` addition to
`frontend/apps/docs-site/src/content/guides/skills.mdx`.

*Acceptance criteria.*
1. A tenant admin advances the Personal Chat pin from the expected old revision to
   the published revision; only `skill_revision_id` differs afterwards.
2. `position` and `activation_mode` on that row, and every other row in
   `governance_policy_skill_bindings` for that policy, are byte-identical before
   and after.
3. Every other Governance Policy field is unchanged.
4. A non-admin with `SKILLS` is refused; an API-key caller is refused with
   `session_auth_required`; a foreign-tenant Skill is a 404.
5. A stale `from_revision_id` is a typed 409 with its own reason code, and nothing
   is written.
6. An active execution block, an unpublished Skill, and a `to_revision_id` that is
   not the currently published one each fail closed with distinct reason codes.
7. A candidate revision that pushes a personal-default Assistant past its context
   window is rejected with the same message ordinary governance save produces.
8. Repeating the successful call is a typed no-op and emits no second audit event.
9. Exactly one `skill_bindings_advanced` audit row, containing no instruction
   text.

*Test plan.* Integration tests in `backend/tests/integration/skills/` for 1-3 and
5-8, following `test_skill_conflict_contract.py` and `test_skill_concurrency.py`;
a concurrency test interleaving a governance save and a rollout that asserts the
skip; unit tests in `backend/tests/unittests/skills/` for the authorization matrix
(4); an audit assertion for 9; frontend component tests in
`organization-skill-detail.svelte.test.ts` for the dialog, disabled states, error
surfaces and Swedish/English copy.

*Explicitly defers.* Assistants, Apps.

### PR 2 — Assistant fleet, preview and apply

*Observable behavior.* On the same page, an administrator sees how many Assistant
bindings are pinned to an older revision and starts the update. Bindings advance
in chunks of 100 while the dialog reports what each chunk did: advanced, skipped
because another editor changed them, excluded because the new revision no longer
fits that Assistant's model and prompt. Stopping the dialog stops the run and
leaves already-advanced pins advanced. Starting again continues where it
effectively left off, because already-advanced bindings no longer match. If the
Skill is unpublished, published to a different revision, or execution blocked
mid-run, the run ends with a typed terminal failure and a fresh start is required.

*Canonical owners extended.* `SkillRepo` gains the keyset target query and
`advance_assistant_pin`; `OrganizationSkillService` gains the chunk operation;
`AssistantService.assert_assistant_fits_candidate_pin` from PR 1 gives the
per-target verdict.

*Reused.* `ix_assistant_skill_bindings_skill_id_assistant_id`
(`skill_table.py:250-254`) for the keyset scan; the `limit + 1` overfetch and seek
idiom (`skill_repo_impl.py:563-587`); the already-shipped adoption summary
(`:614-742`) as the provisional pre-run count, so the preview costs nothing new;
`load_skill_activation_preflight_adapters` (`completion_service.py:210-219`) to
load each distinct model adapter once per chunk; `lock_assistant_space_for_update`
(`:1718-1725`) and `_lock_organization_skill` (`:1127-1141`) in the write phase
only; the PR 1 audit shape with `scope: "assistant"`.

*Created.* One chunk endpoint; a cursor-paginated batch Assistant loader modelled
on `get_personal_defaults_for_tenant` as PR 0 leaves it, so each chunk is a fixed
number of queries regardless of chunk size; `advance_assistant_pin`, a guarded
in-place `UPDATE` of `skill_revision_id` only — the first in-place binding write,
safe because the `(skill_id, skill_revision_id)` FK is
`DEFERRABLE INITIALLY DEFERRED` (`skill_table.py:242-249`); the run block in
`SkillAdoptionProjection.svelte` built from `Badge`, `Alert`, `Button` and `Table`
(there is no `progress` component installed, so progress is stated as "N of M
updated" text with `aria-live="polite"`, not a bar); the ADR amendment at
`:529-537`; docs-site and message updates.

*Acceptance criteria.*
1. Only `skill_revision_id` changes, proven by a row-level before/after comparison
   across every binding column for a mixed fleet.
2. The three existing delete-then-insert write paths
   (`replace_assistant_bindings` `:1774-1803`, `replace_app_bindings`
   `:1862-1888`, `replace_policy_bindings` `:1920-1948`) are untouched, and no
   read path assumes bindings are only ever replaced wholesale.
3. At 10 000 Assistant bindings, a full run performs one forward index pass; the
   per-chunk query count is fixed and independent of chunk size; peak loaded
   Assistant aggregates are bounded by the chunk size.
4. Write-phase lock duration is bounded by the write transaction and does not
   include validation.
5. A concurrent parent save between the read and write phases produces
   `concurrent_change` and leaves that pin alone.
6. A target that fails validation is not revisited within the run; a fresh run
   re-evaluates it against current state.
7. Unpublish, republish to a different revision, and execution block during a run
   each end it with a distinct terminal reason code; pins already advanced are not
   reverted.
8. Two concurrent administrators produce no double application and no corruption.
9. One audit event per changed chunk, grouped by `run_id`, carrying counts and
   reason codes and no instruction text.

*Test plan.* A seeded 10 000-binding scale test asserting the query count per
chunk, the single forward pass and the peak aggregate count; cursor-stability
tests with concurrent inserts and deletes; the row-level preservation comparison
for (1); a two-writer concurrency test for (5) and (8); terminal-failure tests for
(7); frontend tests for the running, stopped, excluded and terminal-failure states
in both languages.

*Explicitly defers.* Apps, which are the next board task — an eager-only extension
with its own acknowledgement and queued-snapshot proof. Durable rollout rows, per
section 5.4.

---

## 8. The bounded-memory blocker — two options

`verify` asks for "Ten-thousand-target bounded memory, lock scope, stable cursor,
and no N+1 target loading". PR 2 delivers it for the Assistant fleet. PR 1 cannot
deliver it for Personal Chat, because the only permitted fit owner,
`assert_personal_default_governance_context_fit`, loads every personal-default
Assistant in the tenant in one unpaginated query with eager `selectinload`s
(`assistant_repo.py:584-603`). At 10 000 users, advancing one Personal Chat pin
materialises 10 000 Assistant aggregates with their attachments and MCP servers.

**Option (a) — carve Personal Chat out, record accepted debt.**
The PR states that bounded-memory evidence covers the Assistant fleet path, and
that Personal Chat inherits the existing governance-save scan — neither better nor
worse than saving the Personal Chat policy today. It contradicts one clause of one
`verify` line and is recorded as such on the board.
*Cost:* a compliance-adjacent claim carries a named exception into the tranche's
final PM audit, and the underlying production risk stays unfixed in a path that
already ships.

**Option (b) — paginate the scan first, as PR 0.**
*Cost:* one extra PR before any user-visible value lands, touching a path that
stabilised one day earlier.

**Recommendation: (b).**

Three reasons. It is genuinely small — one repo method, one loop, and moving an
existing batch projection inside that loop. It fixes a real pre-existing risk that
has nothing to do with this feature, so the work is not overhead borrowed against
the roadmap. And it lets both PR 1 and PR 2 claim the bounded-memory line honestly
rather than shipping a feature whose headline evidence has a footnote.

**It is not a second fit calculation, and is safely outside that stop
condition.** The stop condition forbids compatibility being *calculated* in more
than one owner. PR 0 does not touch the calculation: every Assistant is still
validated by the same `validate_skill_activation_fit` call with the same inputs
and the same verdict. Only which rows are resident in memory at which moment
changes. If PR 0 altered any accept/reject outcome, that would be the signal it
had strayed — which is why its first acceptance criterion is outcome identity.

---

## 9. Constraints this plan holds itself to

- One fit calculation. `SkillTurnPlan.to_activation_runtime()` stays the only
  selective-fit owner; `validate_skill_activation_fit` stays the only verdict
  wrapper; the assembly stays in `AssistantService`.
- No generic jobs or bulk-operation framework, no second token counter, no
  parallel binding API, no pass-through service, no one-method interface, and —
  after section 5 — no operation tables at all.
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
  same change; PR 2 also amends the ADR.

---

## 10. Risks and what the `verify` list cannot deliver as written

### 10.1 The ADR's exact-preview clause

Covered in 5.3. The stateless design trades an exact whole-fleet pre-run preview
for provisional pre-run counts plus exact per-chunk outcomes, with the first chunk
as the sample. This is a product contract change requiring the ADR amendment in
PR 2, and it is the one decision that changes PR 2's shape if rejected.

### 10.2 Bounded memory for Personal Chat

Covered in section 8. Resolved by PR 0 under the recommended option; an accepted,
named exception under the alternative.

### 10.3 "Cancellation" cannot mean interrupting a chunk

There is no in-flight process to signal. Cancellation is the administrator
stopping the loop; it takes effect at the next chunk boundary and already-advanced
pins are not reverted — which the roadmap already states ("completed pins are not
silently reverted", `docs/enterprise-skills-roadmap.md:988`). The UI copy must say
this rather than implying a rollback.

### 10.4 "Resumability" means re-running, not restoring

Also a wording gap. A stopped run is continued by starting again: bindings already
advanced no longer match the guard and cost one skip each. State this in the UI
and in the docs-site, because an administrator who expects a saved position will
otherwise read the restart as lost work.

### 10.5 The preflight runs under the administrator's identity

`prepare_skill_activation_preflight` builds MCP identity headers from `self.user`
(`completion_service.py:180`), which during a rollout is the administrator rather
than the Assistant's owner. There is no live discovery and tools come from the
persisted, permission-filtered catalogue, so no cross-user data is read — and
`assert_personal_default_governance_context_fit` already behaves this way when an
admin saves the Personal Chat policy. Precedent, not a new leak, but name it in
PR 2's security review rather than discovering it there.

### 10.6 Lower-order risks

- Moving the `organization_skill_service` provider below `assistant_service`
  touches a heavily shared file. Keep it a single mechanical move in PR 1 with no
  other container edits.
- A long run holds a browser dialog open. Chunks of 100 with validation outside
  locks keep each request short, but a 10 000-binding fleet is still minutes of
  looping. The mitigation is that stopping is safe and restarting is cheap; the UI
  must make both obvious.
- `run_id` is client-echoed and therefore only a grouping hint. Actor, tenant and
  Skill in every audit row are server-derived, so tampering can only mis-group an
  administrator's own events.
