# Retention levels, rules and the execution clock

- **Status:** Proposed; accepted when this record merges to `develop`
- **Date:** 2026-11-08
- **Decision owners:** Product and architecture
- **Scope:** How a retention period is chosen on the organisation, space and
  Assistant or App levels; the rule vocabulary that every retention task is
  declared against; the clock that decides due-ness. Builds on
  [One retention engine](retention-engine.md), whose runner, units and
  registration it keeps.

## Context

Nothing is removed without an active choice: an organisation, a space or an
Assistant or App chooses a period, and the choice says what is removed. The
same kind of choice exists for other policies, for example an access
requirement that any level can switch on. Before this record each policy
resolved its levels on its own: the conversation history rule was a
`COALESCE` written by hand beside a separate enum naming its levels, no list
said which removals a task may make, and the nightly run took its clock from
the worker process.

## Decision

### One level kernel, shared by every policy

`eneo.policy_levels` is a pure module (standard library only, no I/O):

- `PolicyLevel`: `installation`, `organization`, `space`, `assistant_or_app`,
  `flow`. The strings are released API and audit values.
- `resolve(chain, *, stricter, bounding)` takes the levels from the outermost
  to the innermost. The nearest chosen value is inherited. A value chosen on a
  bounding level is a bound that no inner value loosens, so the result is the
  stricter of the nearest value and the bound. The result carries the value,
  the level it came from, the bound and the outermost level that set it.
- `None` means nothing is chosen at that level. Any other value, `False`
  included, is a choice. On a tie the nearest level is the origin. An empty
  chain, or one without a choice, resolves to nothing chosen.
- `admits(parent, proposed, *, stricter)` says whether a level may choose a
  value below its parent's resolution: inheriting, or anything at least as
  strict as the parent's bound.

Each domain supplies what "stricter" means and which levels bound. Retention
passes "fewer days" and, for conversation history, no bounding level: the
nearest choice wins, also when it is longer than an outer one. An access
requirement passes "required" with every level bounding, which makes the
levels an OR that an inner level can raise and never lower. The tests pin
both compositions. Authorization to write a level, confirmation, persistence
and SQL stay in each domain; the kernel has no registry and no global order
of values.

### Rules and their dispositions

`eneo.data_retention.domain.rules` is the vocabulary of what can be chosen for
removal. Every `RetentionRule` has exactly one disposition:

| Rule | Disposition |
| --- | --- |
| `conversation_history` | task `conversations.history`, levels organisation, space, Assistant or App, no bound |
| `widget_conversations` | exemption: each widget's own nightly job removes its conversations, held to the organisation's widget policy |

The SQL that selects due conversations is built from the rule's levels
(`nearest_period`): a `COALESCE` and a level `CASE` in the rule's order, from
the innermost level out. It refuses a rule with a bound, which needs its bound
in SQL first. A parity test runs every combination of the three levels and
the organisation switch through the database and through `resolve_period`,
and both must match the rule written out. The level a removal came from stays
the audit count key: `by_assistant_or_app_rule`, `by_space_rule`,
`by_organization_rule`.

### The registration contract

`retention_registration_violations` compares the vocabulary, the
dispositions, the registered tasks and `EXISTING_WITHOUT_CHOICE`. It reports:

- a rule without a disposition, and a disposition outside the vocabulary;
- a rule whose task is not registered;
- a registered task that removes no rule's roots and is not listed among the
  removals that run without a choice;
- a listed task that is not registered, or that is also a rule's task;
- a listed switch that is not a setting.

A test runs it against the platform's own declaration, and once per check
with an omission that must fail. A separate test proves each listed switch
really turns its task off. To add a removal: add the rule and its
disposition, register the task (or state the exemption), and document it on
the retention page. A task that removes without a rule must be listed with a
switch that turns it off.

The check covers registered tasks and declared rules. It cannot see a removal
written outside the engine, in arbitrary SQL, a log or another store.

### The database clock

Due-ness follows the database's clock, never a worker's. The nightly run
reads `now()` from the database once per execution and gives that instant to
conversation history and empty sessions, so their discovery and the fresh
check inside each `DELETE` compare with the same cutoff for the whole
execution. Unused files and the engine's job history compare with `now()` in
each of their own transactions, which is still the database's clock; a record
that crosses its threshold during an execution can be removed by those two
tasks in the same execution.

### What a change to a period does

| Change | Effect |
| --- | --- |
| Adoption of this record | none: no schema or data change, and the same questions and App runs are due before and after |
| A shorter period | older conversations become due at the next execution |
| A longer period | the fresh check inside the delete stops removal of conversations no longer due |
| A cleared period | the level inherits the next chosen value outward, which can be shorter, longer or none, so more conversations can become due |
| A first period | conversations older than it become due |

A removed row never returns. Each period is compared with the root's
`created_at`, against the execution's database clock. Questions without an
owner Assistant follow no policy and are not removed; that is unchanged.

### Values that remove without a choice, and defaults

- The audit log keeps 365 days unless an administrator changes it on the audit
  log page. That existing behaviour is listed with the removals that run
  without a choice. `eneo.audit.domain.constants.DEFAULT_RETENTION_DAYS` is its
  one definition, used by the table default, the first read of the policy and
  the retention engine's own job history.
- Every retention period is validated against 1 to 2555 days, a technical
  sanity bound with one owner, `eneo.data_retention.constants`.
- The Prompt Guide is installed without a period. Its conversations follow
  the space or the organisation until an administrator chooses a period for
  it. Guides installed before keep the period they were installed with.

## Consequences

- Count keys, task and step names and the `RETENTION_*` settings are
  unchanged.
- A policy that needs levels imports the kernel instead of writing its own
  inheritance; a change to the kernel is reviewed against every caller.
- A new removal fails the registration test until it is declared.
- Holds that stop a removal, and a lock that keeps a promise made when work
  is accepted consistent with a concurrent policy change, are not part of this
  record. A hold becomes one more condition in each fresh check.

## Follow-ups

- The organisation's conversation period becomes visible and editable in the
  administration pages of both apps, with the number of conversations a save
  makes due shown before saving.
- Copies of another conversation's content, and consultations of other
  Assistants, join the conversation history rule with their own steps.
