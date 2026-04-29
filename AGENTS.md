# AGENTS.md — Eneo Maintainability Rules

## Mission

This repository is being reviewed and refactored for long-term human maintainability.

Optimize for:
- maintainability over cleverness
- clear ownership over scattered logic
- typed contracts over implicit dicts
- deep modules over shallow pass-through abstractions
- boring reliability over optimistic runtime behavior
- excellent API consumer and API maintainer experience
- code a new senior engineer can understand in week one

The architecture should feel intentional, elegant, and practical.

## Default mode for architecture review sessions

Unless the user explicitly asks for implementation:

- Do not modify source code.
- Do not modify tests.
- Do not modify migrations.
- Do not add dependencies.
- Do not run destructive commands.
- Only write review/planning/PRD output under `docs/refactor/`.
- If a source change seems necessary, document it as a proposed work item instead.

## Evidence standard

Concrete claims require file:line evidence.

Bad:
> The planner is too large.

Good:
> `backend/src/.../ai_builder_planner.py:120-410` mixes prompt construction, plan mutation, fallback repair, and persistence orchestration.

Every finding should include:
- problem
- why it matters for maintainability
- evidence with file:line
- proposed canonical home or fix
- acceptance criteria
- tests required
- risk/trade-off
- confidence: high / medium / low

## Claude peer review loop

For non-trivial plans, architecture changes, reliability-sensitive work, API/data-model/runtime changes, agent/rule changes, or high-impact review findings, use Claude Code as a peer reviewer before committing to a direction.

Canonical command:

```bash
/Users/ccimen/.agents/skills/claude-peer-loop/scripts/claude_peer_loop.py
```

Required loop:
- Iteration 1: ask Claude to challenge Codex's plan or finding before implementation or final recommendation.
- Codex then verifies Claude's claims against source evidence and revises the plan, code, or recommendation when the critique is valid.
- Iteration 2: resume the same Claude session with the same `--session` value and ask Claude whether the revision earns green light.
- Continue only when Claude gives `GREEN_LIGHT: yes`, or when Codex documents the remaining disagreement with file:line evidence and explains why proceeding is still the cleaner choice.

Default questions for Claude:
- Could this be done in a smarter, cleaner way?
- Will this create future technical debt?
- Could maintainability or reliability improve with a different ownership boundary?
- What are the highest-ROI changes for maintainability and reliability?
- Are there AI slop comments, names, abstractions, tests, or compatibility paths?
- Are typed contracts, canonical homes, and runtime failure modes explicit?
- Is the architecture cleaner after the change, or just different?

Claude is a peer, not an authority. Verify concrete claims locally. Preserve Claude artifacts under `.codex/artifacts/` when they influence a decision.

## Engineering standards references

Before architectural review, refactoring, implementation, or agent configuration work, read the standards relevant to the task instead of duplicating long guidance in prompts or subagents:

- `docs/engineering/maintainability-standards.md`
- `docs/engineering/comment-and-readability-standard.md`
- `docs/engineering/api-design-standard.md`
- `docs/engineering/testing-standard.md`
- `docs/engineering/frontend-state-standard.md`

When proposing a change, cite the relevant standard section. When a standard does not fit, explain the trade-off and propose an ADR instead of silently inventing a parallel rule.

## Core operating model

The detailed standards live in `docs/engineering/maintainability-standards.md`. In short:

- Always identify the canonical owner before creating, preserving, or recommending code.
- Run the reuse-before-inventing protocol before adding files, helpers, services, schemas, interfaces, statuses, components, or types.
- Prefer delete/merge/rename/move before adding.
- Treat AI slop as a maintainability defect.
- Include human reviewability impact for major recommendations.

## Eneo Branding / Namespace Policy For Flow And Flow AI Builder

Eneo is the desired product/platform brand going forward.

For net-new Flow / Flow AI Builder user-facing or product-facing names, prefer `Eneo` / `eneo` over `Intric` / `intric`.

Do not opportunistically rename existing Python imports, modules, or package paths from `intric.*` to `eneo.*`. The current canonical backend package namespace remains `intric.*` until a dedicated namespace migration is planned.

Do not create a parallel `eneo.*` Python package, thin `eneo.*` re-export modules, or dual import namespaces.

Avoid mixed prefixes inside an existing surface. If a translation namespace, OpenAPI tag group, audit namespace, telemetry prefix, or generated-client package already consistently uses `intric`, keep that convention until the scheduled wholesale rebrand. New surfaces may use `eneo` from inception.

If renaming user-facing translated strings, update `sv.json` and `en.json` together and run the i18n compile command.

Per-batch migration ownership lives in `docs/refactor/implementation-order.md` under "Branding And Namespace Migration Touchpoints".

## Human maintainability principles

### 1. Human maintainability beats theoretical purity

DDD, Clean Architecture, ports/adapters, repositories, services, and interfaces are tools, not goals.

Use DDD when it improves:
- domain language
- invariant protection
- locality
- testability
- change safety

Do not use DDD ceremony when it creates:
- pass-through layers
- fake seams
- one-method interfaces
- shallow modules
- duplicated state
- abstractions only used by tests

When DDD conflicts with maintainability, choose maintainability and explain why.

### 2. Prefer deep modules

A good module hides complexity behind a small, stable interface.

Flag:
- `utils.py`
- `helpers.py`
- `common.py`
- `manager.py`
- pass-through services
- one-implementation ports
- repositories that expose ORM details
- modules whose interface is as complex as their implementation

Use the deletion test:

> If this layer disappeared, would complexity vanish, or would it simply move into callers?

### 3. Interfaces must earn their existence

Use interfaces/protocols only at real seams:
- external services
- persistence boundaries
- queue/task boundaries
- generated client boundaries
- multiple real implementations
- testing through stable public behavior

Do not create an interface solely because a unit test wants a mock.

For each important interface, document:
- inputs
- outputs
- invariants
- error modes
- idempotency
- transaction behavior
- authorization expectations
- performance assumptions

A good interface is easy to call correctly and hard to call incorrectly.

### 4. Typed contracts at boundaries

Forbidden in domain/application code unless explicitly justified:
- `Any`
- `dict[str, Any]`
- untyped JSON blobs
- untyped Celery payloads
- untyped frontend API responses
- `as any`
- `@ts-ignore`
- stringly typed statuses
- raw primitive bags where value objects should exist

Default shape:
- Pydantic at HTTP/message boundaries
- dataclasses or rich value objects in domain/application logic
- SQLAlchemy models in persistence
- TypeScript generated or centrally defined API types on frontend
- typed Celery command payloads, usually IDs plus command metadata

### 5. Single source of truth

Every concept must have one canonical home.

Look for duplicates of:
- flow status
- run status
- step status
- builder status
- builder plan/spec/envelope
- file mapping
- input resolution
- output rendering
- evidence/artifact derivation
- permission checks
- API schema definitions
- frontend state derivation
- filtering/sorting rules
- tenant/workspace flow settings

When duplicated logic exists, name both locations and propose one canonical home.

### 6. Deletion bias

Because the system is pre-production, prefer deleting:
- never-shipped compatibility shims
- legacy fallback paths
- repair layers hiding invalid state
- dead exports
- dead tests
- tests for deleted behavior
- commented-out code
- outdated comments
- code generated by accident
- source files that only pass through

Do not preserve compatibility for imaginary users.

## Python backend rules

- Keep strict Pyright meaningful.
- Do not weaken typing with local ignores unless justified.
- Prefer `Protocol` over ABC inheritance for structural ports at real seams.
- Prefer concrete classes when there is only one implementation.
- Do not raise FastAPI `HTTPException` from domain/application code.
- Use domain/application exceptions internally and translate to HTTP at the adapter/router boundary.
- No broad `except Exception` except at true outer boundaries.
- If broad catch is necessary, classify, log, and re-raise or translate intentionally.
- Avoid `utils`, `helpers`, `common`, and `manager` names.
- Keep files above 400 LOC under suspicion; split only when it improves responsibility, locality, or interface depth.
- Keep functions above 60 LOC under suspicion; split by lifecycle phase or concept, not arbitrary line count.

## FastAPI API rules

Routers are HTTP adapters, not business logic.

Router functions should:
- parse request
- enforce auth/dependencies
- call application service/use case
- translate response
- translate domain errors to API errors

Endpoint review must cover:
- path naming
- operation ID
- tags
- request model
- response model
- status codes
- pagination/filtering/sorting
- error shape
- authorization
- idempotency
- OpenAPI and generated client quality

Public API must be understandable without reading backend source.

## Celery / runtime rules

Runtime state belongs in the database, not worker memory or task arguments.

Celery tasks should:
- receive small typed command payloads
- be idempotent
- be safe to retry
- handle duplicate starts
- handle worker crash recovery
- persist checkpoints
- use explicit terminalization
- log/audit important transitions

For every runtime transition, identify:
- owner
- persisted state
- transaction boundary
- retry behavior
- crash behavior
- audit event

## SQLAlchemy / data model rules

Data model quality is architecture quality.

For every table/model review:
- relationships
- constraints
- indexes
- status lifecycle
- ownership
- transaction boundaries
- N+1 risks
- migration impact
- audit impact

JSON/JSONB fields require:
- owner
- typed parser/schema
- version
- validation boundary
- migration strategy
- corruption behavior
- tests

Avoid JSON blobs that silently become hidden schema.

## SvelteKit / frontend rules

Frontend state must have one owner.

Flag:
- duplicated state between Driver, Service, and components
- duplicated derived values
- prop drilling that should be context/store
- components doing domain orchestration
- side effects in `load`
- `$effect` used to compensate for unclear ownership
- manual duplicate backend types
- `any`, `unknown`, `as any`, `@ts-ignore`

Reusable primitives should exist for repeated concepts:
- run status pill
- step status pill
- file uploader
- step editor
- evidence viewer
- artifact viewer
- error banner
- empty/loading states
- builder phase indicator

## API consumer perspective

Review as an external developer using Eneo Flows as a flow engine.

The API should make these flows obvious:
- authenticate
- list flows
- inspect flow definition
- understand required inputs
- upload files
- map files to steps
- start run
- poll status
- get step output
- get final result
- get evidence/artifacts
- pause for review
- edit step output
- resume run
- re-run a step
- handle errors safely

If a developer must read backend source to understand the API, that is a maintainability failure.

## API maintainer perspective

Review as the engineer who must safely evolve endpoints for years.

Look for:
- router dumping grounds
- inconsistent schema naming
- inconsistent error models
- domain errors leaking as HTTP errors
- missing operation IDs
- poor OpenAPI shape
- handwritten frontend types drifting from backend schemas
- inconsistent permission checks
- lack of versioning policy
- endpoints that are hard to test

Propose a maintainer playbook:
- adding an endpoint
- adding a schema
- adding a permission
- adding an error
- adding a test
- updating OpenAPI/client types

## Testing rules

Tests should protect behavior, not implementation.

Prefer:
- domain/unit tests for pure rules
- integration tests for DB/API/runtime wiring
- worker/runtime tests for Celery behavior
- frontend component tests for UI behavior
- E2E tests for critical journeys
- API contract tests for external consumers

Flag:
- tests that mock internal collaborators unnecessarily
- tests that assert private helper calls
- tests that duplicate implementation logic
- tests for legacy behavior we should delete
- huge test files without lifecycle organization
- flaky sleeps and arbitrary polling
- snapshot tests that preserve incidental details

## Comments and readability

Classify comments:
- `intent`: explains why or a non-obvious decision
- `restate`: repeats what code already says
- `outdated`: stale, wrong, or misleading
- `todo`: unresolved TODO/FIXME/XXX

Keep intent comments.
Delete or rewrite restating/outdated comments.
Track TODOs with verdict: do / delete / ticket.

Bad names are maintainability bugs. Propose better names when a name hides responsibility.

## Review document style

Every generated review doc must:
- start with a five-line TL;DR
- use file:line citations for concrete claims
- use tables for inventories
- use Mermaid diagrams where structure matters
- include confidence where evidence is incomplete
- include "No findings." when a section has nothing
- avoid filler
- be specific and opinionated

## PRD style

PRDs must include:
- problem
- goals
- non-goals
- users
- current state with file:line evidence
- proposed future state
- requirements
- design
- alternatives considered
- acceptance criteria
- implementation checklist
- tests
- risks
- rollback/recovery
- dependencies
- open questions

PRDs should be executable by a later implementation agent without re-litigating the architecture.

## Human maintainability PR checklist

Before proposing or implementing changes, verify:

- [ ] Does this change have one clear responsibility?
- [ ] Is the canonical home for each touched concept clear?
- [ ] Did I avoid adding a parallel implementation?
- [ ] Did I avoid `Any` / `dict[str, Any]` in domain/application code?
- [ ] Did I avoid new fake seams or one-implementation interfaces?
- [ ] Did I keep routers thin?
- [ ] Did I keep domain logic out of HTTP/persistence adapters?
- [ ] Did I use typed value objects/schemas at boundaries?
- [ ] Did I avoid comments that restate code?
- [ ] Did I add or update behavior-focused tests?
- [ ] Would a new senior engineer understand this file in week one?
- [ ] If this changes an API, is the OpenAPI/SDK impact clear?
- [ ] If this changes runtime behavior, is idempotency/crash recovery clear?
- [ ] If this changes data shape, is migration/versioning clear?
