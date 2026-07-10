# Maintainability Standards

## Purpose

This document owns the shared standard for architecture reviews, refactors,
implementation plans, persistence design, and review-to-implementation handoff.
Focused API, runtime, testing, frontend, readability, and AI-review standards
own their narrower subjects.

Optimize for human maintainability, reliability, future change safety, clear
ownership, typed contracts, deep modules, and deletion of accidental
complexity. A new senior engineer should find the correct owner and change path
in their first week.

Start every non-trivial change with one question:

> What is the canonical home for this concept, and am I about to create or
> preserve a parallel implementation?

## Canonical ownership

Before creating, preserving, or recommending a module, function, type,
component, state, schema, or setting:

1. Search for the same responsibility and domain language.
2. Name the closest existing owners and any competing paths.
3. Choose reuse, extend, rename, move, merge, delete, or create.
4. Explain why the chosen owner protects the invariant better than its callers.
5. If creating something new, explain why the existing owners are insufficient.

Use this table when duplication is material:

| Concept | Location A | Location B | Difference | Canonical home | Delete or merge path |
|---|---|---|---|---|---|

One concept has one canonical type and lifecycle owner. Generated projections,
adapters, and views may represent it, but they must not become independent
authorities.

## Reuse and deletion before invention

Prefer this order:

1. Reuse the existing owner.
2. Deepen the owner with the missing invariant.
3. Rename or move misplaced logic.
4. Merge duplicate paths.
5. Delete obsolete behavior, compatibility, tests, and comments.
6. Create new code only when the existing owner cannot hold the responsibility
   without becoming less coherent.

Delete first:

- never-shipped compatibility and fallback paths;
- wrappers that add no invariant or useful compression;
- tests that preserve deleted or invalid behavior;
- repair layers that hide an invalid boundary;
- duplicate schemas, statuses, derived values, and permission logic;
- generic configuration that postpones a product decision;
- comments that narrate code or implementation history.

Avoid names such as `utils`, `helpers`, `common`, `manager`, `processor`,
`shared`, and `misc` when they hide domain ownership. A narrow domain name is
better than a generic bucket.

## Deep modules and justified abstractions

A useful module hides substantial complexity behind a smaller, stable
interface. A useful abstraction is justified by either:

- multiple real implementations with the same contract; or
- a real external, volatile, persistence, queue, generated-client, or
  cross-process seam.

In both cases, the abstraction must be smaller than the complexity it hides and
must make callers easier to use correctly.

Before adding an interface, protocol, port, base class, adapter, or service,
answer:

- What complexity or volatility does it contain?
- What invariant belongs behind it?
- What are its inputs, outputs, errors, ordering, idempotency, authorization,
  transaction, and performance assumptions?
- Could callers use the concrete owner directly?
- What code becomes simpler or disappears?
- Is the seam real, or was it introduced only to make mocking convenient?

Reject pass-through services, one-method ports without a real boundary, generic
factories, service locators, and abstractions whose interface is as complex as
their implementation.

## Clean boundaries and typed contracts

Clean architecture is a dependency rule, not a directory ceremony.

- Domain and application logic do not depend on HTTP frameworks, ORM sessions,
  UI components, or provider SDK response shapes.
- Routers, workers, persistence repositories, and frontend clients adapt at the
  boundary and depend inward.
- Transaction ownership is explicit. Do not spread commits across callers and
  repositories without one lifecycle owner.
- Translate domain/application errors at the adapter boundary.
- Catch broad exceptions only at a true containment boundary. Preserve
  unexpected-failure visibility, sanitize diagnostics, and deliberately
  re-raise, translate, or continue under an explicit partial-failure contract.
- Use strict types to make invalid states hard to construct. Keep strict Pyright
  and TypeScript checks meaningful; do not silence them with `Any`, `as any`,
  `@ts-ignore`, or unjustified ignores.
- Untrusted boundary data may begin as `unknown`, but it must be validated or
  narrowed before application or UI state depends on it.

Use a concrete class when one implementation and no volatile seam exist. Tests
should exercise public behavior rather than force production abstractions for
mocking.

## Persistence integrity

Data-model quality is architecture quality. Every persistent concept names:

- its canonical table or typed aggregate;
- tenant and ownership boundary;
- relationships and deletion behavior;
- constraints and indexes that enforce real invariants;
- lifecycle states and terminal states;
- transaction and locking owner;
- expected access shape, boundedness or pagination, and N+1/query-count risk;
- corruption, repair, and migration behavior;
- retention and audit consequences.

Put independently queried or transitioned lifecycle facts in relational
columns. JSON or JSONB is appropriate for a bounded aggregate that is loaded and
written as a whole, provided it has a typed schema, version, validation boundary,
migration policy, and explicit corruption behavior.

Schema migrations require a read-only preflight for affected data, lock and
index impact, ordered forward and rollback steps, and representative database
tests. Do not preserve a misleading foreign-key action or compatibility shape
when pre-production data can be migrated or deleted safely.

Cross-process lifecycle persistence, retry, effects, and finalization follow the
[Runtime Reliability Standard](runtime-reliability-standard.md).

## Change-path analysis

Common changes should have one obvious starting owner. For each important
change path, ask:

- Where does the canonical contract change?
- Which adapters, generated projections, tests, and docs derive from it?
- Can drift occur between those consumers?
- Does the type system expose incomplete propagation?
- Which behavior check proves the public result?
- Can a reviewer understand the change without reconstructing hidden wiring?

Touching several files is not itself a defect. Touching unrelated authorities
for one concept is. Prefer generated propagation and one contract test over
manually synchronized copies.

## Optional architecture aids

Use a glossary when repeated vocabulary or forbidden synonyms cause real
confusion:

| Concept | Definition | Canonical type or module | Forbidden synonyms | Notes |
|---|---|---|---|---|

Use an invariant ledger when several boundaries enforce the same durable rule:

| Invariant | Why it matters | Enforcement | Known violation | Owner |
|---|---|---|---|---|

Use diagrams, inventories, scorecards, and matrices only when they make several
relationships materially easier to verify. Do not require them for narrow work,
and do not use numeric scores as a substitute for a concrete finding.

## Findings and recommendations

Lead with the outcome and ranked findings. Every concrete finding names:

- problem and impact;
- current file:line evidence;
- current and proposed canonical owner;
- delete, reuse, move, merge, or create disposition;
- deliberately excluded scope;
- acceptance check and behavior test;
- risk, rollback, or recovery;
- confidence when evidence is incomplete.

Recommendations must be executable and smaller than the problem they solve.
Replace vague advice such as “consider refactoring,” “extract a helper,” or “add
tests” with the owner, exact behavior, proof, and deletion boundary.

Review formatting is proportional to the decision. Use tables or diagrams for
real mappings and dependencies, not as mandatory report decoration.

## Review-to-Implementation Handoff

A review is implementation-ready when it defines reviewable work items with
dependencies, unresolved product decisions, acceptance criteria, tests, risk,
and recovery. When a review spans several artifacts, designate one entry point,
one finding authority, and one execution authority. Review citations are a
snapshot; the implementer reopens current source before editing.

### Dirty worktree ownership

At the start of a slice, record the branch, `HEAD`, and
`git status --short --untracked-files=all` or an equivalent complete inventory.
Treat every pre-existing tracked or untracked change as user-owned unless the
current task explicitly brings it into scope. Do not stash, reset, restore,
reformat, stage, or include it in the slice's diff. If the slice overlaps active
or ambiguous work, preserve it and stop for coordination when the changes cannot
be separated safely.

At handoff, distinguish the initial state from files changed by the slice.

### One-slice execution

When implementing a multi-item review or roadmap, select one work item whose
dependencies and product decisions are satisfied. Stop after validating that
slice and writing its receipt; do not guess an unresolved decision or mix in an
adjacent roadmap item. A slice includes its behavior tests and may include a
focused migration or generated contract when those changes are inseparable from
the behavior.

### Implementation receipt

For a non-trivial slice executed from a review or roadmap, record:

- work-item and finding identifiers, when present;
- branch, `HEAD`, and initial dirty state;
- dependencies and product decisions satisfied;
- current and proposed canonical owner;
- reuse, move, merge, delete, or create disposition;
- non-goals and exact files changed;
- acceptance-criteria disposition;
- exact validation commands and results;
- pre-existing failures versus failures introduced by the slice;
- API, generated-contract, data, migration, and runtime effects;
- risk, rollback, and recovery;
- peer-review verdict and locally verified corrections;
- next dependency or eligible item, without starting it.

Store local receipts under `.codex/artifacts/implementation-receipts/` unless
the implementation issue or pull request is the durable project owner. Do not
create a second roadmap or status source in repository documentation.

### Local and tracked artifacts

Tracked documentation is an intentional shared source of truth. Local review
packets, raw output, scratch notes, and implementation receipts remain in
ignored local paths unless explicitly promoted.

Do not add a one-off review directory to the tracked `.gitignore`. For an
artifact that should remain local to this clone, use the file returned by
`git rev-parse --git-path info/exclude`. Clone-local exclusions may apply to
linked worktrees sharing the same Git directory, and untracked files do not
transfer to another worktree or clone. Copy the packet to the target workspace
or deliberately promote it to tracked documentation.

Add a pattern to `.gitignore` only when every contributor should ignore that
class of artifact.

## Recommendations to reject

Reject recommendations that:

- split a file only because it is long;
- create a service, interface, helper, or framework without a real owner or
  seam;
- preserve unreleased compatibility without persisted-data evidence, an owner,
  and a deletion trigger;
- keep old and new paths without a bounded migration and removal plan;
- move domain logic into routers, workers, ORM models, or UI components for
  convenience;
- add config flags instead of making an owned product decision;
- replace clear concrete code with patterns that add more concepts than they
  remove;
- add mock-heavy tests that assert implementation wiring;
- add comments instead of improving names, types, ownership, or structure;
- claim “flexibility” without a concrete second use case or volatile seam.
