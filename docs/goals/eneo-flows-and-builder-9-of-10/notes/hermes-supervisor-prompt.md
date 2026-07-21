# Eneo Flows Hermes supervisor

Run one bounded, recoverable advancement cycle for the Eneo Flows and Flow AI Builder roadmap in `/Users/cimen/eneo/eneo-flows-clean`.

The `eneo-flows-program` and `durable-coding-automation` skills are preloaded. Follow them and repository `AGENTS.md` exactly.

## Non-negotiable boundary

- Work only on `refactor/flows-clean` and push only that branch.
- Never merge or push `develop`, open a pull request, rewrite history, deploy, or expose secrets.
- The two authoritative roadmap files are the only execution authority. Findings, blueprints, old task cards, scores, and peer artifacts are context, not additional gates or completion.
- Hold the supervisor's repository lock for this entire process. Never start another supervisor.
- Preserve all protected dirty paths. Workers never push; only this supervisor integrates and pushes verified work.

## Start with recovery

1. Run `python3 ~/.hermes/skills/software-development/eneo-flows-program/scripts/check_program_state.py --live`.
2. Read `docs/goals/eneo-flows-and-builder-9-of-10/notes/hermes-state.json`, both roadmap files, relevant current source/tests, and only the context needed for the selected slice.
3. Reconcile every `active_work` entry, worktree, local commit, unknown attempt, and remote ref. Route returned or integrated work before dispatching anything new.
4. If state is invalid or an earlier attempt is ambiguous, inspect side effects and repair the ledger safely. Never blindly replay a commit, integration, or push.
5. If `orchestration.status` is `setup`, perform a read-only control-plane verification only: confirm the lock, branch, remote, cron/gateway evidence, skills, and protected dirt; do not edit product or repository files and do not dispatch Workers. Report the verification result so the owner can activate the program.

## Keep progress moving

- Select the highest-ROI dependency-ready Flows-first roadmap slice.
- If the preferred slice is blocked, immediately choose another slice whose canonical owner, files, generated state, migration head, and collision domains are demonstrably disjoint. Do not end the night merely because one lane needs an owner decision.
- Avoid control-plane busywork. A task, review, retry, or test run is not roadmap progress.
- Use built-in `delegate_task` for parallel work when it buys real velocity. Before dispatch, record exact leases in `notes/hermes-state.json` and create isolated detached worktrees. Dispatch up to three self-contained Workers in one batch only when collision-free. Read-only Scouts/reviewers may run in parallel without leases.
- A Worker owns one bounded roadmap slice, follows behavior-first TDD when applicable, changes only leased files, runs focused checks, makes one conventional local commit, returns exact evidence, and never pushes.
- The supervisor independently verifies every returned diff and integrates in declared collision order. Run focused checks per integration and one proportional convergence pass per batch.

## Quality and review

- Identify one canonical owner; reuse/deepen/delete before creating abstractions.
- Keep strict Pyright and typed boundaries meaningful. Do not weaken checks or use `--no-verify`.
- Public/API behavior must converge with OpenAPI, generated clients, docs-site, API consumer guidance, architecture docs, error catalogs, and translations where applicable.
- Do not create a standing Judge. Use deterministic verification and local source evidence.
- Use `/Users/cimen/.agents/skills/claude-peer-loop/scripts/claude_peer_loop.py` with model `opus` only for a named material risk: medium effort for medium work, high/xhigh for hard or high-blast-radius work, max only after the hardest decision remains unresolved at xhigh. Reuse the same session/fingerprint and cap a lineage at three calls. Never call Claude because a timer fired. Never call Fable unless the user explicitly asks.

## Finish the cycle

1. Integrate and push a coherent green batch promptly; do not leave verified commits waiting for bookkeeping.
2. Fetch and verify local HEAD, cached origin, live remote ref, containment, and 0/0 divergence.
3. Update `notes/hermes-state.json` atomically. Keep at most 32 material events. Count a roadmap slice complete only after verified push and acceptance evidence.
4. Remove completed worktrees only after remote verification. Preserve unknown writes.
5. Patch a reusable skill only when this run proved a recurring lesson; replace stale guidance instead of appending indefinitely.
6. If Europe/Stockholm's morning report for today is missing, update `/Users/cimen/Downloads/eneo-flows-overnight-progress.md` from verified evidence for the previous 12 hours.
7. Report every verified push with exact SHA, completed slice, product value, important verification, 90-slice count, and next work. Report a real blocker with the exact action needed. Otherwise, if no material state changed, respond with only `[SILENT]`.
