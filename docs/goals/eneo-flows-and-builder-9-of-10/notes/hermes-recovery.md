# Hermes recovery blueprint — Eneo Flows

## TL;DR

1. One Hermes cron entry starts one locked supervisor; no second scheduler or standing Judge writes the repository.
2. Every cycle reconstructs state from Git, two authoritative roadmaps, a bounded JSON ledger, worktrees, and cron history—not chat history.
3. Hermes delegation supplies up to three parallel Workers only in isolated, collision-free worktrees; integration and push remain single-writer.
4. A blocked lane never stops unrelated dependency-ready roadmap work; bounded retries and disjoint rerouting keep overnight progress alive.
5. Claude Opus is an event-driven peer for material risk; Fable remains manual-only, and deterministic tests remain the acceptance authority.

## Canonical control plane

| Concern | Owner |
|---|---|
| Required work, dependencies, acceptance criteria | The two tracked `roadmap.md` files |
| Current implementation truth | Source, tests, migrations, generated contracts, docs, Git, and live remote |
| Execution status | `notes/hermes-state.json` |
| Historical Codex evidence | Frozen `state.yaml` and `notes/handoff.md` |
| Reusable operating procedure | Hermes skill `eneo-flows-program` |
| Scheduling and execution audit | Hermes cron `jobs.json` and `executions.db` |
| Whole-run exclusion | `fcntl` lock at `~/.hermes/programs/eneo-flows/writer.lock` |

Findings, blueprints, coordination notes, scores, peer artifacts, and handoffs may inform a slice, but they cannot add roadmap work or mark a slice complete.

## Runtime shape

The sole cron job is script-only. Its Python wrapper acquires the repository-wide advisory lock and keeps the file descriptor open while it runs one pinned Hermes one-shot supervisor. This closes the gap between Hermes's scheduler-level overlap protection and the repository-wide writer boundary.

The nested supervisor uses the default Hermes runtime with only the terminal, file, code-execution, skills, todo, and delegation toolsets. It preloads `eneo-flows-program` and `durable-coding-automation`, reads project `AGENTS.md`, reconciles durable state, advances one bounded batch, verifies, commits, pushes, checkpoints, and exits. A later tick starts fresh.

There are no separate implementation watchdog, commit reporter, recovery job, or morning-summary agent. The one supervisor performs recovery first, reports material events, and maintains the daily report. Consolidating these responsibilities removes stale observers and prevents conflicting control planes.

## Delegation and velocity

The supervisor may run up to three built-in Hermes delegates concurrently. Before a writing dispatch it must:

1. prove roadmap dependencies and product decisions are satisfied;
2. define canonical owner, red behavior test, acceptance criteria, exact allowed files, collision domains, and stop conditions;
3. atomically record leases in `notes/hermes-state.json`;
4. create one detached worktree per Worker;
5. send each Worker a self-contained packet and exact worktree path.

Workers never write the integration checkout and never push. The supervisor routes returned commits before new dispatch, verifies each diff locally, integrates in declared order, runs convergence checks, and pushes promptly. If a delegate disappears, its worktree and commit are durable recovery evidence; the next cycle inspects them before retrying.

## Liveness policy

A block belongs to a lane, not to the whole program. When the preferred slice needs a product decision, environment, credential, or migration authority, the supervisor records it and chooses the highest-ROI dependency-ready slice with disjoint ownership and collision surfaces. Only a repository-wide safety conflict, branch divergence, unknown integration write, or lack of any decision-ready roadmap slice may stop mutation.

Transient provider and tool failures receive bounded retries. Exhaustion records a material blocker and reroutes work. Repeated review, unchanged peer fingerprints, empty heartbeat messages, and control-plane tasks never become surrogate progress.

## Peer review and self-improvement

Use `/Users/cimen/.agents/skills/claude-peer-loop/scripts/claude_peer_loop.py` with Claude Opus only for named material risk. Use medium effort for medium work, high or xhigh for hard/high-blast-radius work, and max only after the hardest decision remains unresolved at xhigh. Reuse the same session and content fingerprint, with no more than three calls per lineage. Verify every concrete claim locally. Fable runs only on an explicit user request.

Hermes Curator remains enabled for deterministic skill lifecycle maintenance, with consolidation off. After a recurring failure or proven workflow, the supervisor patches the narrowest skill and its verification step. Task status, commit IDs, and transient incidents never enter memory or skills. Obsolete guidance is replaced or removed rather than accumulated.

## Recovery after interruption

1. Install/import the Hermes profile and this repository clone.
2. Check out `refactor/flows-clean`; never use `develop` as an integration target.
3. Restore the `eneo-flows-program` and `durable-coding-automation` skills or import a Hermes profile backup.
4. Verify `notes/hermes-state.json`, the two roadmap fingerprints, protected dirty paths, worktrees, local commits, cached origin, and live remote.
5. Install the wrapper at `~/.hermes/scripts/eneo_flows_supervisor.py` and run it with `--check`. The compact-state validator lives at `~/.hermes/skills/software-development/eneo-flows-program/scripts/check_program_state.py`.
6. Install/start the user gateway service and recreate exactly one 15-minute script-only cron job.
7. Trigger one setup cycle. Confirm the cron execution ledger, wrapper lock metadata, no duplicate writer, and no unexpected repository changes.
8. Set `orchestration.status` to `active` only after that verification.

Never infer failure from an abandoned cron attempt. Hermes records abandoned execution as `unknown`; inspect Git, worktrees, pushes, and ledger state before deciding whether to resume or retry.

## Failure handling

| Failure | Recovery |
|---|---|
| Lock already held | Silent no-op; the current writer remains authoritative |
| Gateway restart | Next due tick starts a fresh reconciling cycle |
| Cron attempt becomes `unknown` | Inspect side effects; classify recovered, resumable, retryable, blocked, or still unknown |
| Delegate disappears | Inspect its worktree, base, status, and commits before re-dispatch |
| Provider/tool transient failure | Bounded retry, then record and reroute a disjoint slice |
| Branch or remote diverges | Stop mutation, preserve evidence, reconcile explicitly |
| One lane needs user input | Report exact action and continue safe disjoint roadmap work |
| Verification fails | Do not push; fix the root cause or block that slice |
| Push result is ambiguous | Query live remote before any repeat push |

## Verification and completion

A slice is complete only after its roadmap acceptance criteria are proven, relevant contracts/docs are converged, the commit is integrated and pushed to `refactor/flows-clean`, and the live remote is verified. Program completion requires 90/90 required slices or an explicitly authorized stable disposition recorded in the roadmaps, no required unintegrated work, no unknown writes, and a final independent audit.
