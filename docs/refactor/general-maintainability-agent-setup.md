# General Maintainability Agent Setup

TL;DR:
The custom Codex agents are now a reusable engineering quality review board.
They are no longer tied only to flows or AI Builder.
Shared standards live in `AGENTS.md` and `docs/engineering/`.
Each agent has a narrow architectural lens and accepts a target scope from the prompt.
Claude peer review is the validation loop for non-trivial agent/config changes.

## Current Setup

| Area | Location | Purpose |
|---|---|---|
| Durable repo behavior | `AGENTS.md` | Mission, review rules, peer-review loop, ownership/reuse/delete standards |
| Shared standards | `docs/engineering/*.md` | Long-form maintainability, comments, API, testing, frontend state standards |
| Custom agents | `.codex/agents/*.toml` | Narrow review roles with shared output contract |
| Hooks | `.codex/hooks*.json`, `.codex/hooks/*.py` | Session/prompt/stop nudges for Claude peer review |
| Rules | `.codex/rules/maintainability.rules` | Guardrails for risky commands |
| Claude loop skill | `/Users/ccimen/.agents/skills/claude-peer-loop` | Two-pass external peer review via Claude Code |

## Review Board Agents

| Agent | Lens |
|---|---|
| `architecture_boundaries_reviewer` | Dependency direction, bounded contexts, layer leaks, canonical ownership |
| `maintainability_interface_reviewer` | Deep modules, fake seams, interface value, DDD pragmatism |
| `api_contract_reviewer` | API consumer/maintainer DX, schemas, errors, OpenAPI, generated clients |
| `data_model_reviewer` | SQLAlchemy/Pydantic, migrations, JSON contracts, constraints, schema evolution |
| `runtime_reliability_reviewer` | Background jobs, retries, idempotency, crash recovery, persisted state |
| `frontend_state_reviewer` | State ownership, component boundaries, generated types, SvelteKit maintainability |
| `test_quality_reviewer` | Test pyramid, behavior coverage, over-mocking, flaky/dead tests |
| `readability_and_slop_reviewer` | Naming, comments, long functions, AI slop, week-one comprehension |
| `dead_code_deletion_reviewer` | Dead code, stale compatibility, unused exports, deletion opportunities |
| `observability_operability_reviewer` | Logs, metrics, tracing, audit events, incident readiness |
| `developer_experience_reviewer` | Onboarding, docs, local setup, validation commands, navigation |

## Use Pattern

Prompt agents with a target scope:

- bounded context
- backend package
- frontend feature area
- API surface
- product area

Ask for the required review output: TL;DR, top risks, ownership map, duplication map, delete list, interface audit, change-path analysis, invariant ledger, concept glossary, reviewability findings, and ranked work items.

## Local Vs Team Scope

`.codex/` is currently git-ignored in this repository. That means the custom agents, hooks, rules, and Claude peer-loop artifacts are local Codex infrastructure unless the team later chooses to unignore selected safe files.

If this should become team-wide, unignore only non-secret configuration:

- `.codex/config.toml`
- `.codex/hooks.json`
- `.codex/hooks/*.py`
- `.codex/agents/*.toml`
- `.codex/rules/*.rules`

Do not commit `.codex/artifacts/`, local tokens, machine-specific MCP settings, or personal provider credentials.
