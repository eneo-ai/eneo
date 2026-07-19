# Program Handoff

## Identity

- Goal:
  `docs/goals/eneo-flows-and-builder-9-of-10/goal.md`
- Board:
  `docs/goals/eneo-flows-and-builder-9-of-10/state.yaml`
- Predecessor task: none; initial PM task.
- Current PM task:
  `019f7c78-fa66-7461-8b06-13c857569fb5`,
  `Eneo Flows implementation PM — active`.
- Last verified revision:
  `f847ff45dcaf0d610fd871f7baa6f0bdbc3a3d0c`.

## Roadmap Reconciliation

- Sources: both authoritative roadmap files, delivery coordination, and the
  Eneo Flows-first scheduling overlay listed in `state.yaml`.
- Fingerprint:
  `sha256:863579596211606532387b704e38b4abd1b8aecc2691c8fcbff78fd0f82f37b4`.
- Completed: M0.1, M0.2, M0.3, M0.4, M0.5, and BM0.1.
- Active: next high-risk tranche documentation and gate reconciliation.
- Remaining: 84 roadmap slices recorded by the board, with BM5.5 externally
  gated.
- Deferred: D6, BD1, BD5, BM5.5, and both record-only P3 ledgers.
- Excluded: BD4 as the explicit Builder-side reference-only alias of Flow D2.

## Current Boundary

- Active task: T010, PM-only reconciliation of documentation impact, exact
  leases, and one consolidated high-risk fingerprint. No coding Worker is
  active.
- Integration branch:
  `refactor/flows-clean` at
  `f847ff45dcaf0d610fd871f7baa6f0bdbc3a3d0c`; the fetched remote remains
  `836ee6cc6d76658f78fdceb3338f1474135efdd5` until the verified M0 convergence
  group is complete.
- Pending commits: none; T009 is integrated and its immutable receipt is
  recorded.
- Collision leases: no write lease is active. Read-only lookahead is
  reconciling M1.2, M3.7, and M1.4 before the Judge and Opus/Max gates.
- Worktrees: T003–T007 and T009 retain their clean detached immutable commits.
- Validation status: integrated Flow fence 2,419 passed / 10 skipped; Builder
  fence 2,413 passed; retention envelope 7 passed; strict Pyright 0/0; Ruff
  lint green; locked Ruff 0.12.12 reports all 1,191 `src/eneo` files formatted.
- Unresolved decisions: BM0.2 is read-only inspection only; any governance
  mutation requires a separate attended change contract. No decision blocks
  the active source batch.
- Unknown write outcome: none.
- Last processed callbacks: T009 was independently verified and integrated;
  the post-integration Flow, Builder, retention, Pyright, Ruff, lock, and exact
  diff gates passed and T010 opened.
- Supervision: the existing `eneo-flows-implementation-watchdog` is tool-verified
  ACTIVE at its preserved 15-minute cadence, targets the current PM task, and
  points to this goal path. `eneo-flows-hourly-roadmap-brief` remains
  tool-verified PAUSED.
- Reporting: the watchdog prompt and charter require a
  `Since overnight start` line from `checks.initial_head` with integrated
  commits, unique changed files, and additions/deletions; active unintegrated
  Worker diffs stay separate and LOC is not a quality score.

## Durable Transition and Documentation Clauses

- Every future activated card must state `documentation impact: required` or
  `unaffected` and cite current source. Public/API/OpenAPI/generated-client,
  consumer-workflow, runtime/failure, data-shape, and capability changes carry
  their canonical docs and docs-site work in the same convergence group; no
  hand-copied generated contract and no documentation-only Worker.
- Public/OpenAPI/generated-client/docs-site consumer-contract state is one
  exclusive collision domain. Relevant Flow checks are `make docs:regen`, the
  focused/full docs-site contract test, OpenAPI/client drift checks, and the
  docs-site build when affected. Builder work keeps `ai-builder.mdx`, shared
  `docs/flows.mdx`, and affected consumer/developer pages current.
- Flows stays the pull priority until a read-only Judge records
  `flow_core_transition_ready` with the release-critical checkpoint, stable
  disposition, no-higher-ROI-ready-Flow-blocker, and cross-track ROI evidence
  defined in `goal.md` and `state.yaml`.
- After that receipt, Builder becomes the active pull track; at most one steady
  Worker may continue the highest-ROI ready Flow tail, shared-owner collisions
  serialize, and Builder receives all remaining safe lanes.
- Closed or measurement-gated slices do not reopen without new source
  evidence, a failing behavior/contract test, production evidence, or explicit
  user direction. M6 work requires its measurement trigger; tranche selection
  favors the highest-ROI bounded outcome over speculative polish.
- Parallelism remains four steady Workers, a proved-disjoint temporary fifth,
  and never a sixth, with detached worktrees, exact leases, one shared immutable
  base, predeclared integration order, focused commits, PM-only
  integration/push, and read-only lookahead when serialization leaves lanes
  waiting.

## Recent Conversation Tail

- Last explicit user instruction: treat retired automatic Claude hooks as
  superseded by `peer_review.mode: milestone_only`, keep only consolidated
  high-risk milestone gates and the mandatory final audit, and make overnight
  reports compute factual integrated progress from `checks.initial_head`.
- Last assistant commitment/outcome: completed and verified M0.5, left the
  complete M0/BM0 convergence green, incorporated the documentation,
  transition, anti-loop, throughput, and overnight reporting policies, and
  opened a PM-only high-risk tranche reconciliation task.
- Unfinished action: freeze exact documentation-aware M1.2/M3.7/M1.4 candidate
  cards, run the tokened read-only Judge and one consolidated Opus/Max plan
  gate, then dispatch only the approved proved-disjoint batch.

## Last Hourly TL;DR

No hourly TL;DR has been published from this PM task yet;
`state.yaml -> reporting.last_report_at` remains `null`. The next eligible
report must use the current board evidence and include the chartered
`Since overnight start` line.
