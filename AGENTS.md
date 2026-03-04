# AGENTS.md — Eneo Multi-Agent Review System

## Critical Rules
1. **DO NOT USE GREP to do work on Beads issues.** Use `br` commands to do work on Beads issues.
2. **ONLY use `br` commands** (`br show`, `br ready`, `br list`, `br comments`, `br search`, `br graph`, `br dep`) to interact with beads. Never grep/sed/jq against `.beads/issues.jsonl`.
3. **Beads are the source of truth** for task scope, design decisions, and review history.
4. **Update beads continuously during execution.** Add comments at milestone start, milestone completion, when blocked, when tests fail, and when tests are fixed.
5. **TDD is mandatory for implementation beads.** Start with failing tests (`tdd:red`), then implement until passing (`tdd:green`), then refactor safely.
6. **Verification is mandatory at every milestone.** Run tests/type checks/lint after each milestone and repair failures before continuing.
7. **Hardening is mandatory.** Prioritize maintainability, readability, robustness, error handling, separation of concerns, and clean complexity.
8. **Avoid huge files and mixed concerns.** Refactor into focused modules/components when files become hard to reason about.
9. **Do not commit or push** unless the human explicitly requests it in the current session.

## Architecture (Choose Your Orchestrator)

### Option A: Codex
```
Human → Creates epics + beads in br
  ↓
Codex lead_planner  → Reads beads, creates milestone plan + validation matrix
  ↓
Codex lead_developer → Spawns workers/specialists, implements milestone, runs verification
  ↓
Codex lead_reviewer ↔ Iterative review loop with lead_developer until clean rounds
  ↓
Codex worker agent   → Claims scoped tasks, implements TDD, closes with verification evidence
```

### Option B: Claude Code
```
Human → Creates epics + beads in br
  ↓
claude --agent lead-reviewer → Reads beads, spawns Claude specialist subagents, writes findings as comments
  ↓                          → Uses $codex-review skill for second opinions when needed
Claude main session          → Claims beads, implements TDD, closes with verification evidence
```

Both orchestrators use the same core specialist roles and beads integration. Codex may additionally use `lead_planner`, `lead_developer`, and `ui_ux_expert` for long-horizon execution.
For overnight/long-horizon runs, follow `docs/MULTI_AGENT_LONG_HORIZON_RUNBOOK.md`.

## Milestone Verification Loop (Mandatory)
For every milestone:
1. Plan scope and acceptance criteria from bead context.
2. Implement using TDD (`tdd:red` → `tdd:green`).
3. Run verification (unit, integration, type check, lint, build where relevant).
4. If verification fails, fix immediately before new scope.
5. Add bead comment with evidence (what changed, what was run, pass/fail).
6. Continue only when the milestone is verified.

## Codex Long-Horizon Agent Loop (Required)
Use this exact loop for long tasks:
1. Plan
2. Edit code
3. Run tools (tests/build/lint/typecheck)
4. Observe results (errors, diffs, logs)
5. Repair failures
6. Update docs/status + bead comments
7. Repeat

Why this is required:
1. Real feedback keeps implementation grounded in facts.
2. Externalized state in files/docs/beads reduces drift over long sessions.
3. Steerability remains high because humans can course-correct at each loop.

## Required Bead Comment Events
Add `br comments` entries for all of these:
1. Milestone started (scope + planned validations)
2. Milestone completed (files changed + verification evidence)
3. Blocked state (root cause + unblock request)
4. Test failure discovered (failing test and reason)
5. Test failure resolved (fix summary + passing evidence)
6. Review findings applied (what was fixed and why)

## TDD Protocol (Mandatory)
1. Write or update tests first for intended behavior and edge cases.
2. Mark bead with `tdd:red` while tests fail.
3. Implement minimal change until tests pass.
4. Mark bead with `tdd:green` only after verification passes.
5. Refactor for readability/maintainability without changing behavior.

## Quality Hardening Standard
All implementation and review agents enforce:
1. Maintainability: clear structure and low coupling.
2. Readability: understandable control flow and naming.
3. Robustness: explicit edge-case handling and defensive checks.
4. Error handling: actionable errors at correct boundaries.
5. Separation of concerns: avoid god classes/files and mixed responsibilities.
6. Complexity control: avoid overengineering and underengineering.
7. Performance awareness: avoid obvious hot-path regressions.

## Second-Opinion Protocol
Each orchestrator can invoke the other for cross-model verification:
- **Codex** → `$claude-review` → Gets Claude Code's perspective
- **Claude Code** → `$codex-review` → Gets Codex's perspective

Use second opinions:
- Before finalizing a complex plan
- When agents disagree on a finding
- For architecture decisions needing cross-model verification
- Write input as bead comment: `br comments add <id> --author "<reviewer>" "..."`

## Running with Claude Code

### As Orchestrator (lead-reviewer as main agent)
```bash
claude --agent lead-reviewer "Review beads for epic en-xxx"
```

### Review a specific bead
```bash
claude --agent lead-reviewer "Review bead en-abc. Spawn relevant specialists."
```

### Individual specialist (skip orchestration)
```bash
claude --agent security-analyst "Review auth changes in src/intric/authentication/"
claude --agent database-expert "Review migration in alembic/versions/xxx.py"
claude --agent api-consumer "Evaluate DX of the new /api/keys endpoints"
```

### Subagent files
All 10 agents live in `.claude/agents/`:
- `lead-reviewer.md` — Orchestrator, spawns specialists, consolidates findings
- `security-analyst.md` — Auth, injection, tenant isolation, audit logging
- `api-consumer.md` — External developer experience perspective
- `api-maintainer.md` — REST practices, backwards compat, guard completeness
- `code-quality-analyst.md` — Correctness, types, async, error handling
- `database-expert.md` — Schema, indexes, migrations, query performance
- `maintainability-expert.md` — Tech debt, testability, coupling, patterns
- `overengineering-expert.md` — Complexity calibration (over/under)
- `performance-analyst.md` — Time complexity, memory, N+1, async bottlenecks
- `solution-architect.md` — Design decisions, boundaries, data flow, scalability

## Beads Conventions

### Prefix: `en-`
### Lifecycle: `status` is the source of truth
- `open` → Bead is planned or under review
- `in_progress` → Claimed and being implemented
- `closed` → Done with verification evidence

### Labels (minimal — avoid duplication with status)
- `domain:backend`, `domain:frontend`, `domain:database`, `domain:api`, `domain:auth`
- `risk:high`, `risk:low` (determines review depth)
- `tdd:red` (tests written, not passing), `tdd:green` (tests passing)
- `breaking` (contains breaking API changes)
- `needs-migration` (requires DB migration)

### Priority: P0 (critical) → P1 (blocks release) → P2 (default) → P3 (nice-to-have) → P4 (backlog)

### Dependency Rules
- DB expand migration → backfill → contract migration → service code → API endpoint → frontend
- Tests are part of the implementing bead (not separate beads)

## Agent Roles

### lead_planner (Codex long-horizon orchestrator)
- Reads bead scope and dependencies, then creates milestone plan and validation matrix.
- Spawns planning specialists (architecture, security, maintainability, UX, performance) as needed.
- Writes planning summary to bead comments.

### lead_developer (Codex long-horizon orchestrator)
- Spawns implementation specialists/workers in parallel per milestone.
- Runs verification gates at each milestone and repairs failures before proceeding.
- Applies lead_reviewer findings in iterative loops until stop criteria are met.

### ui_ux_expert (Codex specialist)
- Reviews UI/UX for accessibility, responsive behavior, and Nordic design consistency.
- Enforces regular-vs-advanced progressive disclosure and low cognitive load defaults.
- Uses Context7 and primary docs for framework/component validation when needed.

### lead_reviewer (Orchestrator — sole spawner for review phase)
- Reads beads: `br ready --json`, `br show <id> --json`
- Assigns specialists based on domain labels + risk level
- Writes consolidated findings: `br comments add <id> --author "lead_reviewer" "..."`
- Only lead_reviewer and the human can run `br create`
- Can invoke second-opinion skill for cross-model verification

### Hard Specialists (always assigned for their domain)
- `security_analyst` — for `domain:auth` beads and `risk:high`
- `database_expert` — for `domain:database` and `needs-migration` beads
- `api_maintainer` — for `domain:api` and `breaking` beads

### Semi-Fungible Pool (assigned based on need)
- `code_quality_analyst`, `maintainability_expert`, `overengineering_expert`, `performance_analyst`

### api_consumer — Activated for ANY new or changed endpoint
### solution_architect — Always active on epics/architecture

## Review Stop Criteria
Stop iterating when: **no BLOCKER or WARNING for 2 consecutive rounds**, or confidence threshold met. Do NOT use fixed N.

## Implementation DoD Checklist
Before closing any bead:
- [ ] Tests exist and pass (unit + integration)
- [ ] Verification was run at each milestone (with repair loops when needed)
- [ ] Bead comments contain milestone-by-milestone evidence
- [ ] TDD lifecycle recorded (`tdd:red` → `tdd:green`)
- [ ] Type check clean (Pyright baseline not regressed)
- [ ] Audit logging present (if state-changing)
- [ ] Auth guards verified (if API endpoint)
- [ ] Bead comments all addressed

## Sync Protocol
```
Session start:  git pull → br sync --import-only
During work:    br commands modify local SQLite
Session end:    br sync --flush-only → git add .beads/issues.jsonl → git commit
```

### JSONL Merge Conflicts
1. `git checkout --theirs .beads/issues.jsonl`
2. `br sync --import-only`
3. Re-apply local changes via `br` commands
4. `br sync --flush-only`

## br Command Reference
```bash
br create "Title" --type task --priority 2 --labels "domain:backend"
br dep add <child> <parent>
br graph --all --compact
br show <id> --json
br comments list <id>
br comments add <id> --author "agent_name" "finding..."
br ready --json
br update <id> --status in_progress
br label add <id> tdd:red
br close <id> --reason "..."
br sync --flush-only
br sync --import-only
```
