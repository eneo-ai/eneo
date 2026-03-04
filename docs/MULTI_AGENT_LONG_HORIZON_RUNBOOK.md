# Multi-Agent Long-Horizon Runbook

This runbook standardizes overnight Codex runs for high-quality delivery with beads tracking.

## Objectives
1. Keep long sessions coherent with durable project memory.
2. Enforce milestone-by-milestone verification and repair loops.
3. Track planning, execution, failures, fixes, and review outcomes in beads.
4. Improve maintainability, readability, robustness, error handling, and performance without overengineering.
5. Keep Flow hardening non-breaking for existing assistants and current users.

## Execution Environment (Eneo Devcontainer)
Run validation commands inside the devcontainer:
1. `docker exec eneo_devcontainer-eneo-1 bash -lc "<command>"`
2. Backend path: `/workspace/backend` and use `uv`.
3. Frontend path: `/workspace/frontend/apps/web` and use `bun`.
4. If frontend translations/messages change, run `bun run i18n:compile`.
5. For Flow runtime behavior, use Celery-based flow execution paths as source of truth.

## Required Loop
For each milestone, always run:
1. Plan
2. Edit code
3. Run tools (tests/build/lint/typecheck)
4. Observe results
5. Repair failures
6. Update docs/status + bead comments
7. Repeat

Do not move to new scope if current milestone verification fails.

## Role Flow
1. `lead_planner` prepares scope, milestones, acceptance criteria, and validation matrix.
2. `lead_developer` implements milestones by spawning workers/specialists in parallel.
3. `lead_reviewer` performs multi-agent review rounds and emits prioritized findings.
4. `lead_developer` applies findings and re-runs verification.
5. Target up to 5 developer/reviewer iterations for overnight hardening.
6. Stop early only when there are no BLOCKER/WARNING findings for 2 consecutive review rounds (or human stop).

## Durable Memory Files
Keep these files updated during long runs:
1. `docs/agent-memory/prompt.md`
2. `docs/agent-memory/plan.md`
3. `docs/agent-memory/implement.md`
4. `docs/agent-memory/status.md`

## Beads Protocol
Never parse `.beads/issues.jsonl` directly. Use only `br` commands.

### Session Start
1. `git pull`
2. `br sync --import-only`
3. `br ready --json`

### Required Bead Comments
Add `br comments add` entries for:
1. Milestone started (scope + validations)
2. Milestone completed (changes + evidence)
3. Blocked status (root cause + unblock request)
4. Test failure discovered
5. Test failure repaired
6. Review findings applied

### Session End
1. `br sync --flush-only`
2. Do not commit or push unless explicitly instructed by the human.

## TDD and Test Tracking
1. Write tests first and set `tdd:red`.
2. Implement until tests pass and set `tdd:green`.
3. Keep unit and integration evidence in bead comments.
4. Refactor after green while preserving behavior.

## Quality Gates Per Milestone
1. Tests for changed behavior pass.
2. Type checks for touched areas pass.
3. Lint/build checks pass for touched areas.
4. Error handling is explicit and actionable.
5. Separation of concerns remains clear.
6. No oversized god-files introduced.
7. Complexity is proportional to value.

### Flow Verification Commands (Devcontainer)
Use these commands for Flow hardening milestones:
1. `docker exec eneo_devcontainer-eneo-1 bash -lc "export PATH=/home/vscode/.local/bin:$PATH && cd /workspace/backend && uv run pytest tests/unittests/flows tests/integration/flows -n 5 -x -v"`
2. `docker exec eneo_devcontainer-eneo-1 bash -lc "export PATH=/home/vscode/.local/bin:$PATH && cd /workspace/backend && uv run pytest tests/unit/test_flow_managed_assistant_guards.py -n 5 -x -v"`
3. `docker exec eneo_devcontainer-eneo-1 bash -lc "export PATH=/home/vscode/.local/bin:$PATH && cd /workspace/backend && uv run pyright src/intric/flows src/intric/server/routers.py src/intric/assistants/api/assistant_router.py"`
4. `docker exec eneo_devcontainer-eneo-1 bash -lc "export PATH=/home/vscode/.bun/bin:$PATH && cd /workspace/frontend/apps/web && bun run check"`
5. `docker exec eneo_devcontainer-eneo-1 bash -lc "export PATH=/home/vscode/.bun/bin:$PATH && cd /workspace/frontend/apps/web && bun run test:unit"`
6. `docker exec eneo_devcontainer-eneo-1 bash -lc "export PATH=/home/vscode/.bun/bin:$PATH && cd /workspace/frontend/apps/web && bun run i18n:compile"` (only when translations/messages changed)

## UI/UX Gate (when frontend scope exists)
1. Apply Nordic design direction (clean hierarchy, calm visual tone, clear readability).
2. Enforce accessibility and keyboard navigation.
3. Verify responsive behavior.
4. Preserve regular-vs-advanced progressive disclosure.
5. Use `ui_ux_expert` with Context7 and primary docs when behavior is version-sensitive.

## Prompt Template: Planning
```text
Review bead <ID>. Act as lead_planner.
Create milestone plan, acceptance criteria, risk register, and validation matrix.
Spawn only needed planning specialists.
Write concise plan summary to bead comments.
Create/update docs/agent-memory/{prompt,plan,implement,status}.md.
```

## Prompt Template: Implementation
```text
Act as lead_developer for bead <ID>.
Execute milestones from docs/agent-memory/plan.md.
Spawn explorer/worker/specialists in parallel by scope.
Run verification after each milestone and repair failures immediately.
Write bead comments for each milestone and test outcome.
Never commit or push.
```

## Prompt Template: Review Iteration
```text
Act as lead_reviewer for bead <ID>.
Run focused multi-agent review, cross-verify blocker findings, and publish prioritized fix queue.
Then hand off to lead_developer to apply fixes.
Run up to 5 iterations, stopping early only after 2 consecutive clean rounds (no BLOCKER/WARNING).
```
