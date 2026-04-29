# Maintainability Standards

This is the shared standard for architecture reviews, refactors, implementation plans, and custom agents in this repository.

## Operating Model

Optimize for human maintainability, reliability, future change safety, clear ownership, typed contracts, deep modules, deletion of accidental complexity, and code a new senior engineer can understand in week one.

Every reviewer and implementation agent must first ask:

> What is the canonical home for this concept, and am I about to create or preserve a parallel implementation?

## Scorecard

Score every important module or change from 1-10. The overall score is the minimum dimension score.

| Dimension | High-score signals |
|---|---|
| Maintainability | Confident change path, useful tests, strict typing, clean dependency direction, structured observability |
| Code Quality | Correct, idiomatic, low duplication, no dead code, no unjustified ignores |
| Clean Architecture | Domain does not depend on frameworks; adapters depend inward; transactions have clear owners |
| Separation of Concerns | One reason to change; no god objects; concerns separable by deletion |
| Single Source of Truth | One canonical schema/status/setting/derived value; generated types where appropriate |
| Human Readability | Domain language, clear names, short comprehensible functions, comments explain why |
| Human Reviewability | Coherent diffs, explicit contracts, behavior tests, visible deletion/move/rename/change boundaries |

Action bands:

| Score | Action |
|---|---|
| Any dimension <= 3 | Refactor required before further feature work |
| 4-6 | Refactor opportunistically; do not worsen |
| 7-8 | Ship-ready with normal follow-up |
| 9-10 | Exemplar worth referencing |

## Canonical Ownership Rule

Before creating, preserving, or recommending a module/function/type/component:

1. Does this concept already exist elsewhere?
2. Is there already a canonical owner?
3. Are there parallel implementations?
4. Is new code deepening the canonical owner, or creating a competing path?
5. Can something be deleted or merged instead of added?

Use this table for duplicates:

| Concept | Location A | Location B | Difference | Canonical home | Delete/merge path |
|---|---|---|---|---|---|

Forbidden defaults:

- create a new helper
- add a new service
- add another adapter
- keep both for flexibility

Allowed only with two real use cases, a stable boundary, a smaller interface than implementation complexity, and a documented canonical owner.

## Reuse-Before-Inventing Protocol

Before proposing a new abstraction, file, component, utility, schema, status, helper, service, or interface:

1. Search for existing concepts with the same responsibility.
2. Name the closest existing owners.
3. Decide: reuse, extend, rename, move, merge, delete, or create.
4. If creating new, explain why existing owners are insufficient.

Avoid `utils`, `helpers`, `common`, `manager`, `shared`, `misc`, `types`, and `constants` unless the file has a narrow domain name and one clear reason to change.

## Delete-First Refactoring

Before proposing a new abstraction, ask what can be deleted.

Prefer deleting:

- duplicate code before improving the canonical owner
- never-shipped compatibility
- fallback paths that hide invalid state
- wrappers with no independent responsibility
- tests that protect bad architecture
- comments that restate code
- dead branches instead of documenting them

Every recommendation must state what to add, change, delete, and not preserve.

## Interface Justification Checklist

Before recommending an interface, protocol, port, base class, adapter, service, or abstraction, answer:

- What complexity does this interface hide?
- Is the interface smaller than the implementation?
- Are there two real implementations today?
- If not, what real future implementation is already planned?
- Is the seam external, volatile, or cross-process?
- Would tests be better with a fake at this seam?
- Could the concrete class be injected directly instead?
- Does the interface speak domain language?
- Are ordering, errors, idempotency, and transaction behavior documented?
- What code becomes simpler because this interface exists?

If the main reason is "for mocking," reject the interface.

## Change-Path Analysis

For each important concept, describe how a future developer would change it. Common examples:

- add a new status
- add a new API field
- add a new permission
- add a new step type
- add a new frontend state
- add a new provider
- change persistence shape
- add a background task
- add a validation rule

For each path, answer:

1. Which files must be touched?
2. Is there one obvious place to start?
3. Does the change require parallel backend/frontend/tests/docs edits?
4. Is drift possible?
5. Is the type system helping?
6. Are tests protecting behavior?
7. Would a new senior engineer find the path in week one?

If a common change requires touching 5+ unrelated files, flag it as a maintainability smell.

## Concept Glossary

For important concepts, keep a glossary:

| Concept | Definition | Canonical type/module | Forbidden synonyms | Notes |
|---|---|---|---|---|

The `Forbidden synonyms` column matters. Multiple names for the same concept create duplicated logic and review confusion.

## Architecture Invariant Ledger

For durable architecture rules, create or update an invariant ledger:

| Invariant | Why it matters | Enforcement | Current violations | Owner |
|---|---|---|---|---|

Useful invariants include:

- domain must not import HTTP framework
- runtime state must be persisted
- frontend API types come from OpenAPI or a central generated source
- comments explain why, not what
- public runtime transitions are idempotent and auditable

## Bad Recommendations To Avoid

Do not recommend:

- splitting a file only because it is long
- creating interfaces without real seams
- adding design patterns without naming the problem they solve
- introducing generic helpers
- preserving compatibility for never-shipped behavior
- adding tests that assert implementation details
- replacing clear concrete code with abstract factories
- moving logic into a service when it belongs on a domain object
- moving domain logic into a router because it is convenient
- adding comments instead of improving names
- adding config flags instead of making a decision
- using "flexibility" without a concrete second use case
- keeping old and new paths without a migration plan and deletion date

## Good Recommendation Requirements

A good recommendation must be evidence-backed, specific, smaller than the problem it solves, deletion-aware, testable, understandable to a new senior engineer, aligned with one canonical owner, explicit about trade-offs, and explicit about what not to do.

Weak recommendations include "consider refactoring," "could be cleaner," "maybe use a service," "extract helper," "improve naming," and "add tests." Rewrite weak recommendations into executable work items.

## Required Review Output

Every architecture or maintainability review must include:

1. Five-line TL;DR
2. Top risks ranked by severity, with confidence and affected files
3. Canonical ownership map
4. Duplication map
5. Delete list
6. Interface audit
7. Change-path analysis
8. Architecture invariant ledger
9. Concept glossary with forbidden synonyms
10. Human reviewability findings
11. Ranked refactor work items with motivation, scope, files affected, acceptance criteria, tests, risk, dependencies, and effort
