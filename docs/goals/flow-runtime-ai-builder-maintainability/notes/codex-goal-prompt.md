# Codex Goal Prompt — Flow Runtime / AI Builder Maintainability

```text
/goal Follow docs/goals/flow-runtime-ai-builder-maintainability/goal.md through successive safe verified maintainability and production-readiness phases on the current branch. Commit completed verified phases locally, but do not push. Do not stop after planning unless blocked.

Read first:
- docs/goals/flow-runtime-ai-builder-maintainability/goal.md
- docs/goals/flow-runtime-ai-builder-maintainability/state.yaml
- docs/goals/flow-runtime-ai-builder-maintainability/notes/T000-codex-source-check.md
- docs/goals/flow-runtime-ai-builder-maintainability/notes/T000-maintainability-review-findings.md
- docs/refactor/flow-ai-builder-production-readiness-review-packet.md
- docs/refactor/flow-ai-builder-production-readiness-chatgpt-prompt.md
- docs/refactor/flow-ai-builder-material-efficiency-review-handoff.md
- docs/goals/flow-runtime-ai-builder-production-readiness/notes/T000-plan-synthesis.md
- .codex/artifacts/claude-peer-loop-flow-production-readiness-packet-final-gate-20260510T184654Z.md if present locally. If missing, use docs/goals/flow-runtime-ai-builder-maintainability/notes/T000-maintainability-review-findings.md and the committed review packet instead.

This is not a cosmetic refactor. The target is 9/10 maintainability and production readiness for Eneo Flows and Flow AI Builder:
- code humans can read and safely change,
- one canonical owner per concept,
- typed data boundaries,
- excellent public API error handling,
- OpenAPI/Swagger useful to humans and LLM-generated clients,
- behavior tests that catch real runtime/API failures,
- less dead code, dead tests, legacy fallback, and AI-slop comments.

Important context:
Flows and Flow AI Builder are not in production and have no live users. Do not keep legacy/backwards-compatibility code merely out of fear. However, do not delete blindly. A deletion still needs grep proof, tests, fixture/migration implications, and a clear replacement behavior. Production DB proof is not required unless the owner explicitly says production-like data must be preserved.

Do not treat "pre-production" as permission to skip migration/fixture thinking. It only means we do not preserve compatibility for external users by default.

Stay on the current branch:
- Do not create, switch, rebase, push, or open a PR.
- Commit after each coherent verified phase.
- Preserve unrelated dirty files.
- Do not stage wholesale.
- Do not commit `.codex/artifacts`, local eval output, curl logs, temporary scripts, scorecards, screenshots, API keys, `.env` files, caches, MP3s, or unrelated docs.

Commit cadence and messages:
- Stay on `feature/refactor-flows-flowai` unless the owner explicitly says otherwise.
- Make local commits at good reviewable intervals: board setup first, then each coherent verified P0/API/runtime/data-boundary/cleanup phase.
- Do not bundle multiple major phases into one catch-all commit.
- Do not create noisy checkpoint commits for incomplete work.
- Do not mix board setup docs and production source changes in one commit.
- Use concise human-readable commit subjects that describe the behavior or maintainability improvement, not generic AI wording.
- Commit subjects and bodies must not contain internal planning vocabulary such as `P0.x`, `A.x`, `Phase N`, `slice`, `Worker`, `Scout`, `Judge`, or `Tranche`.

Use Goal Maker board discipline:
- Work only on the active task.
- Keep one active task.
- Write receipts and update state.yaml.
- Use the tiered Claude gate from goal.md; do not invoke Claude for low-risk cleanup or every local implementation choice.
- Run blocking Claude commit gate for P0/API/runtime/data-boundary/lifecycle phase commits.
- Run separate Claude plan gate only when canonical ownership, public API/error contract, schema/migration shape, red-test harness, or allowed files are uncertain.
- Use Claude in skeptical/blocking mode for architecture/runtime/API decisions that change ownership, public contracts, schemas, lifecycle transaction boundaries, or frontend/backend error contracts.
- Treat Claude as pressure, not authority; verify claims locally.
- After each completed big phase or important architecture/runtime/API decision, run a Claude loop that explicitly asks for maintainability improvements before green-lighting the next phase.
- A `GREEN_LIGHT: no` blocks when the concern is correctness, canonical ownership, type contract, behavior-test adequacy, public API/error contract, regression risk, data-loss risk, or security risk. Stylistic, out-of-scope, duplicate-policy, or process-cost objections may be overruled only in the receipt with file:line evidence and a one-line owner rationale.

Before implementation:
- If the goal board files are uncommitted and the owner has not asked to keep them uncommitted, make a docs-only commit for:
  - docs/goals/flow-runtime-ai-builder-maintainability/goal.md
  - docs/goals/flow-runtime-ai-builder-maintainability/state.yaml
  - docs/goals/flow-runtime-ai-builder-maintainability/notes/T000-codex-source-check.md
  - docs/goals/flow-runtime-ai-builder-maintainability/notes/T000-maintainability-review-findings.md
  - docs/goals/flow-runtime-ai-builder-maintainability/notes/codex-goal-prompt.md
- Do not mix board setup with production code changes.

Primary work order:
1. Scout current branch and dirty state.
2. Pick exactly one first P0 Worker slice.
3. Add red behavior test before implementation.
4. Implement smallest clean typed fix.
5. Verify with targeted tests, strict pyright, ruff/format as configured, and git diff --check.
6. Run Claude commit gate when required by the tiered gate.
7. Ask Claude to identify any higher-ROI maintainability improvements before the next phase is green-lit.
8. Commit local phase if green.
9. Continue to the next safe phase.

P0 candidates to reverify:
1. Required runtime inputs advertised by run contract but bypassed when step_inputs is omitted.
2. Review checkpoint edits bypass output-contract validation.
3. Executor failure terminalization loses persisted failed state.
4. Late provider success overwrites or mutates terminalized run state.

Likely first slice:
P0-required-step-inputs-omitted, because it has high API consumer value and likely lower blast radius. This is a hypothesis, not a command. Scout/Judge may choose another P0 if current evidence says it is safer.

Do not silently bundle create-run idempotency fingerprint canonicalization into that first slice. If omitted `step_inputs` and `{}` should canonicalize identically for successful requests, treat that as a separate public API behavior decision unless Judge explicitly includes it.

Maintainability rules:
- No new shallow services, managers, generic helpers, or speculative abstractions.
- No broad rewrites.
- No new `Any`, `cast`, `# type: ignore`, or dict-shaped persisted payload unless the boundary reason is explicit and reviewed.
- No comments that restate code. Comments must explain invariants, transaction boundaries, or non-obvious tradeoffs.
- No internal planning vocabulary in source comments/docstrings.
- Reuse existing canonical owners. Deepen them; do not create parallel ownership.
- For public API work, error handling is part of the contract: stable code, message, context, request id where appropriate, and OpenAPI examples.
- For AI Builder material routing, do not use all_previous_steps as a dropped-context band-aid. Prefer explicit, bounded material references.

Error handling requirements:
- For every touched API error, assert the actual HTTP response body, not only OpenAPI schema.
- Prefer domain/application exceptions with stable codes over direct HTTPException dicts.
- Add examples/schema updates when endpoints are touched.
- Make errors useful for frontend developers and LLM-generated clients.
- After a backend error contract is stabilized, Scout whether the frontend Flow run/review surfaces render that failure clearly. Queue a small frontend Worker only if the current UI cannot show an actionable error.

Legacy/dead-code cleanup policy:
- Because this is pre-production, plan cleanup aggressively but safely.
- Classify candidates into delete_now, delete_after_tests, delete_after_fixture_or_migration_cleanup, keep.
- Delete tests only after a public/behavior test supersedes them.
- Do not preserve fallback paths for hypothetical old users.
- Do preserve behavior that protects current intended product capability.
- Production DB proof is not required by default for Flow/AI Builder cleanup in this branch. Local fixture/schema/migration proof still is.

Testing requirements:
- P0 fixes require red tests first.
- Each P0 must name the concrete red-test harness before Worker activation.
- Mock-call-only tests do not count for persistence, race, lifecycle, or public API contract bugs.
- Prefer fresh-session persistence assertions for runtime state.
- Prefer HTTP/API integration assertions for API consumer behavior.
- Add property/normalization tests where cheap, especially for step_inputs fingerprint normalization.
- Run strict pyright on changed files and touched tests.

P0 implementation anti-patterns:
- Adding a second validator when an existing validator can be extracted or reused.
- Adding a read-then-write application check where an atomic repository/SQL guard is required.
- Fixing one failure branch while leaving sibling branches with copy-pasted lifecycle logic.
- Returning generic BadRequestException without stable code/context for public API failures.
- Adding broad dict-shaped payloads at new persistence/API boundaries.
- Adding comments that explain review history instead of runtime invariants.
- Adding compatibility branches for hypothetical old users in this pre-production branch.

Suggested first-slice acceptance if P0-required-step-inputs-omitted is selected:
- GET /run-contract/ exposes a required runtime input.
- POST /runs/ with omitted step_inputs fails typed 400 with flow_run_required_step_input_missing.
- POST /runs/ with step_inputs={} fails identically for the same required input.
- Optional runtime input remains omittable.
- Successful create-run idempotency fingerprint canonicalization for omitted vs empty step_inputs is explicitly out of scope unless Judge accepts it as part of this slice.
- Existing valid run creation paths still work.

After early P0s:
- Add one public API golden journey for a future web app.
- Verify error payload drift with a real HTTP integration test.
- Choose one typed data-boundary slice: PublishedFlowDefinitionV1 or FlowMetadataV1 / FlowFormSchemaV1.
- Run pre-production legacy cleanup: remove dead fallback code/tests after proof.
- Run AI Builder material-efficiency tranche if source-material routing risk remains.

If local API is available and AI Builder is touched:
- Run V1-V5 and C1-C5 prompts across five spaces round-robin using environment variables only.
- Save raw results only in /tmp and do not commit them.
- Summarize smart vs dumb shape.

Before every local commit:
- git status --short
- git diff --check
- targeted pytest
- strict pyright/typecheck for changed files
- ruff check / format check if configured
- Claude commit gate with require-green/min-score >= 8 if available

Self-review before every commit:
- Is this phase production-ready?
- Would you merge it?
- Could it be cleaner or smarter?
- Did it reduce fear of change?
- Which canonical owner did this deepen, and why did it not create a parallel owner?
- Did it improve API consumer/developer experience?
- Did it preserve canonical ownership?
- Did it add type debt, AI-slop comments, dead tests, compatibility dead weight, or speculative abstractions?
- How many new `Any`, `cast`, and `# type: ignore` entries did this add?
- Paste every added or changed source comment/docstring line, or state "none".
- What code became easier to understand after this phase? Name the exact file/function and why.
- What remains intentionally out of scope?
- Which relevant implementation anti-patterns did this phase avoid, and what concrete code choice avoided each?

Local Docker/Postgres context:
- App container: `docker exec eneo-41ae93-eneo-1 <command>`
- Database container: `docker exec -e PGPASSWORD=postgres eneo-41ae93-db-1 psql -U postgres -d postgres`
- Default local DB env:
  - `POSTGRES_USER=postgres`
  - `POSTGRES_PASSWORD=postgres`
  - `POSTGRES_PORT=5432`
  - `POSTGRES_HOST=localhost`
  - `POSTGRES_DB=postgres`

Final response after each implementation phase:
- commits made,
- files changed,
- tests run,
- pyright/lint results,
- Claude review result and whether Claude challenged the next phase with improvement areas,
- open risks,
- whether you would merge,
- whether this is production-ready,
- maintainability score estimate,
- next recommended slice.
```
