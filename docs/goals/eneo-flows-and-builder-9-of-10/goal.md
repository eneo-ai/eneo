# Eneo Flows and Flow AI Builder 9/10 implementation program

## Objective

Continuously implement and verify every required slice in the authoritative
Flows proper and Flow AI Builder roadmaps until the final program audit proves
the 9/10 maintainability, robustness, clean-architecture, API-DX, operability,
and release-readiness objective.

## Goal Kind

`program`

## Current Tranche

Fresh read-only Judge T089 verified that the preserved T076 M4.5a candidate is
an exact mechanical replay on published base `92dac395...`. The PM then stopped
T090 before Worker dispatch because its required normal commit would invoke a
container-only Pyright hook while no `eneo` devcontainer exists. Exact resumed
Judge T091 returned `blocked_authority`: the user's one-commit host substitution
was limited to T086 and cannot be inferred for T090. T090 remains clean,
untouched, and undispatched pending one narrowly scoped authorization to use
`SKIP=pyright` for its single normal commit only after an immediately preceding
full host Pyright run is 0/0/0; every other hook must run normally. No second
Writer is dependency-ready; M4.5b and M4.5c remain unauthorized.

## Problem and Why It Matters

The review packet records a red Flow unit fence, a red Builder unit fence, and
high-impact integrity, contract, runtime, frontend, evidence, and security
slices. A red baseline cannot prove later behavior, while implementing roadmap
items without one owner and exact collision leases would recreate the
duplication and hidden failure modes this program exists to remove.

## Canonical Authorities

- Work items, dependencies, and acceptance criteria:
  `fablereview/flows-9-of-10-2026-07-16/flows-proper/roadmap.md` and
  `fablereview/flows-9-of-10-2026-07-16/flow-ai-builder/roadmap.md`.
- Target ownership:
  the matching `blueprint.md` files.
- Cross-surface convergence and collision scheduling:
  `fablereview/flows-9-of-10-2026-07-16/delivery-coordination.md`.
- Pull priority:
  `/Users/cimen/.codex/skills/goal-maker/references/eneo-flows-first.md`.
- Runtime truth:
  current source, tests, schemas, migrations, and generated contracts.

The PM is the only board writer and integration steward. Each Worker deepens
the roadmap-named canonical owner and reuses, moves, merges, or deletes before
creating code.

## Non-Negotiable Constraints

- Preserve all user-owned local changes exactly; never stash, reset, restore,
  stage, reformat, or commit them.
- Keep `.devcontainer/devcontainer.json`, `.gitignore`,
  `AGENTS.md.backup-20260629-220449`, and ignored
  `.devcontainer/devcontainer-lock.json` outside every Worker lease.
- Flows proper is the primary track. Builder writes before the Flow transition
  gate are limited to BM0, BM1.1 when Flow M2.2 needs it, coordinated
  vocabulary convergence, source-proved shared-contract work, or a fully
  externally blocked Flow track.
- One bounded roadmap slice per Worker, one detached worktree, one focused
  commit, exact files, exact collision leases, deterministic validation, and
  explicit stop conditions.
- Four steady write Workers; a temporary fifth requires a current disjointness
  proof. Never launch a sixth implementation Worker.
- Workers never push, integrate, update the integration branch, open pull
  requests, or write this board.
- Public/generated contracts, migration heads, vocabulary, frontend state,
  runtime lifecycle, evidence/operator surfaces, and shared schemas are
  exclusive collision domains.
- Every newly activated slice records `documentation impact: required` or
  `documentation impact: unaffected` with current-source evidence. A change to
  a public endpoint, schema, status, error, OpenAPI/generated client, supported
  capability, consumer workflow, runtime lifecycle/failure behavior, or
  persisted data shape is incomplete until its owning convergence group
  updates the canonical source-owned docs and relevant docs-site
  pages/examples, or proves them unaffected.
- Public/OpenAPI/generated-client/docs-site consumer-contract state is one
  exclusive collision domain. Reuse existing generators and catalogs; never
  hand-copy generated contracts, and absorb documentation into the owning
  implementation/convergence slice rather than creating a documentation-only
  Worker or branch.
- No fake abstractions, pass-through services, generic helpers, speculative
  compatibility paths, duplicate schemas, handwritten frontend copies, or new
  tenancy machinery.
- Never call Fable automatically. Follow the complementary peer-loop policy in
  `docs/engineering/ai-review-workflow.md` with
  `peer_review.mode: milestone_only`: never run Claude per Worker, per local
  commit, per timer, or for routine baseline and fixture work. Ambiguous risk
  does not create a gate.
- For each risk-gated milestone, use a new content fingerprint, allow the
  Opus/Max reviewer at least 3,600 seconds, and apply the Ponytail
  delete/reuse/simplify lens. Record the consolidated plan disposition and the
  resumed same-session verification in the convergence group's PM integration
  receipt; `peer_review.active_session` and
  `peer_review.last_reviewed_fingerprint` describe only the currently open
  session and its final integrated fingerprint.
- Claude is a peer, never an authority or implementer. The PM verifies concrete
  findings against current source, callers, contracts, migrations, and runnable
  tests, records accepted corrections or evidence-backed rejections, and turns
  only verified issues into bounded Worker tasks.
- Passing tests alone is not completion: ownership, deleted duplicate paths,
  explicit failure modes, API DX, and week-one maintainability must also be
  verified.

## Deliberately Not Changed

- No broad tenancy removal.
- No Python namespace migration from `intric.*` to `eneo.*`.
- No new roadmap, backlog, architecture authority, status ledger, pull request,
  or duplicate watchdog.
- No live provider evaluation without explicit authorization, isolation, and
  spend approval.
- No unmeasured M6 conversion when its measurement trigger is absent.

## Acceptance and Verification

- M0/BM0 proof fences, strict Pyright, Ruff, and required CI checks are green.
- Every roadmap item has one stable board disposition.
- Every implementation receipt is tied to its dispatch token, base revision,
  allowed files, collision lease, commit, and deterministic validation.
- Public/OpenAPI/generated-client changes pass generation and drift checks.
- Documentation-impact evidence is present on every newly activated card.
  Relevant Flow convergence uses `make docs:regen`, the focused or full
  `test_flow_docs_site_contract.py` contract, OpenAPI/client drift checks, and
  `cd frontend/apps/docs-site && bun run build` when docs-site content or its
  contract changes. Builder convergence keeps `ai-builder.mdx`, shared
  `docs/flows.mdx`, and affected consumer/developer pages accurate.
- Migration/data slices include preflight, upgrade, downgrade, one-head, and
  recovery evidence.
- Runtime slices prove relevant duplicate, retry, crash, terminalization, and
  operator-visible failure behavior.
- Frontend slices consume generated types and prove user-visible state behavior.
- The PM prepares and locally verifies the complete integrated completion
  fingerprint required by T999. Only the read-only Judge may return
  `decision: program_complete`, after the mandatory final complementary peer
  loop has no PM-verified blocker on that unchanged fingerprint and no active
  or queued required Worker, unknown write, unintegrated commit, stale
  worktree, or supervision automation remains.

## Risk and Recovery

Every slice is independently reviewable and revertible. Unknown Worker writes
are quarantined with their worktree, base revision, files, and collision
domains. The PM integrates only verified commits in recorded order and pushes
only a fully green batch to `refactor/flows-clean`.

## Delivery Policy

- Integration branch: `refactor/flows-clean`.
- Workers use detached worktrees and return focused commits.
- The PM integrates verified commits in recorded collision order.
- Direct commits: `true`.
- Pull requests: `false`.
- Worker pushes: `false`.
- PM push: after ordered integration and full verification.

## Reporting Contract

- The implementation watchdog owns the compact higher-level TL;DR while it is
  active. Publish only after at least 60 minutes since
  `reporting.last_report_at`, when user input is required, or when the program
  completes; keep the standalone hourly fallback paused.
- Every hourly or morning TL;DR includes one factual
  `Since overnight start` line computed from `checks.initial_head` on the
  integration branch: integrated commit count, unique changed-file count, and
  Git additions/deletions.
- Report active but unintegrated Worker diffs separately. Line counts describe
  scope only and are never a quality score.

## Ordered Tracks

1. Flows proper
2. Flow AI Builder

Flows remains the pull priority until a read-only Judge records one
`flow_core_transition_ready` receipt. That receipt must prove all
release-critical/P0/P1 Flow work and the Flow baseline, analyzer/publish,
public/generated-contract, migration/data-integrity, runtime-reliability, and
API-DX/docs checkpoints needed by Builder are green; no higher-ROI
dependency-ready Flow blocker remains; and every remaining Flow item has a
stable authorized measurement-gated, low-ROI cleanup, owner/external-blocked,
deferred, excluded, or completed disposition. “Diminishing returns” must be
evidenced against the highest-ROI ready Flow and Builder outcomes, not inferred
by the PM.

After that receipt, the active pull track becomes Flow AI Builder. Keep at most
one steady Worker on the highest-ROI dependency-ready Flow tail and use the
remaining proved-disjoint lanes for Builder; use all safe lanes for Builder
when no useful Flow tail is ready. Serialize any Flow tail that collides with a
shared generated/docs/migration/vocabulary/runtime owner, and continue tracking
the tail to stable completion, deferral, exclusion, or another authorized
disposition. A free slot never proves independence.

Before the receipt, later-track implementation remains limited to the recorded
proof-fence/shared-contract exceptions or explicit user authority. Read-only
lookahead is allowed.

## Anti-Loop Rule

A completed or measurement-closed slice is not reopened without new
current-source evidence, a failing behavior/contract test, production evidence,
or an explicit user decision. Do not manufacture M6 work without its
measurement trigger. At tranche boundaries, choose the highest-ROI remaining
bounded outcome across the eligible tracks; when a track offers only
speculative polish, transition under the Judge-controlled rule instead of
iterating indefinitely.

## Runtime Profiles

- PM/orchestrator: `gpt-5.6-sol`, `xhigh`, standard mode, full access.
- Workers: installed `goal_worker`, `gpt-5.6-sol`, `high`, standard mode, full
  access.
- Judge: installed `goal_judge`, `gpt-5.6-sol`, `xhigh`, standard mode,
  read-only.
- Scouts: read-only and used only when source evidence is missing.
- Fable: never automatic.
- Claude Opus/Max: the complementary peer loop defined by
  `docs/engineering/ai-review-workflow.md`, applied only at recorded high-risk
  milestones and mandatorily at final completion.

## Stop Rule

Pause only for a destructive or irreversible action, a genuine owner-only
product/security/API/migration decision, authentication or permission failure,
quota exhaustion with no safe work, or another blocker that leaves no
independent safe work.

Stop permanently only after `decision: program_complete`.

## Canonical Board

`docs/goals/eneo-flows-and-builder-9-of-10/state.yaml`

The board owns task status, receipts, supervision state, verification
freshness, roadmap dispositions, and completion truth.

## Run Command

`/goal Follow docs/goals/eneo-flows-and-builder-9-of-10/goal.md continuously using the goal-orchestrator profile. Execute the active task or proved-disjoint worktree batch, verify and integrate receipts in collision order, and immediately continue to the next safe work. Do not stop after planning or a tranche audit. Stop only for a genuine owner-only blocker or a program-wide completion audit.`

## PM Loop

1. Read this charter, `state.yaml`, `notes/handoff.md`, and every roadmap
   source.
2. Reconcile the recorded revision, roadmap fingerprint, active tasks,
   worktrees, and collision leases against repository truth.
3. Execute only the active task or active proved-disjoint Worker batch.
4. Verify every progress claim against current source, commits, and tool
   results.
5. Write receipts, integrate verified commits in recorded order, run focused
   and convergence checks, and validate the board.
6. Push only the fully verified integration batch, verify the remote ref, then
   activate the next safe task or batch immediately.
7. Rotate at a safe boundary after two tranches, six hours, or earlier app
   slowdown; retarget the same verified heartbeat only after successor
   acknowledgement.
8. Continue until program completion.
