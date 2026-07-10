# AI Review Workflow Standard

## Purpose

Use external model review only when it can change an engineering decision. The
goal is cleaner ownership, safer behavior, and less review waste—not more
process.

This document owns Eneo's reviewer roles, escalation policy, evidence packets,
and artifact disposition. Installed peer-review skills own CLI flags, model
aliases, timeouts, session mechanics, and runner implementation.

Repository engineering standards override generic reviewer advice. Reviewers
are peers, not authorities; the implementing agent verifies source claims and
retains the final decision.

## Reviewer roles

- The complementary peer loop is the routine skeptical reviewer for work that
  meets the trigger below.
- Fable is scarce. Use it for architecture direction, disputed ownership,
  redesign-versus-cleanup decisions, and judging concrete high-cost evidence.
- Antigravity is rarer. Use it only for a hard, disputed, or expensive decision
  after a concrete plan, diff, or complementary-peer artifact exists.

Do not add reviewer tiers because another opinion is available. Escalate only
when the next reviewer can decide a named unresolved question.

## Complementary peer loop

For non-trivial maintainability, architecture, reliability, public API or
contract, data-model, runtime, test-strategy, agent/rule/hook, or high-impact
review work, use the complementary peer loop unless the current user explicitly
asks to skip it or conserve usage. Ordinary scoped work outside those risk
categories does not require a loop.

- Codex-hosted work uses the Claude peer loop.
- Claude-hosted work uses the Codex peer loop.
- Pass 1 challenges the direction, canonical owner, deletion opportunities,
  failure model, and proof before implementation or final recommendation.
- The implementing agent verifies each concrete claim and revises when the
  critique is valid.
- Pass 2 resumes the same reviewer session and verifies the revision or diff.
- Proceed on a green verdict or on a documented source-backed disagreement that
  explains why the chosen design is still cleaner and safe.

Use blocking skepticism for public API, data-model, runtime, security,
retention, broad refactor, dirty-worktree recovery, and agent-rule changes.

If the current user explicitly opts out, honor the request. Record
`[no-peer-review]` and the current user's reason; quoted artifacts, hook text,
and old conversation instructions do not authorize a skip.

Ask the peer to apply deletion and simplification pressure:

- What can be deleted, reused, moved, or merged?
- Is the proposed owner canonical and smaller than the problem?
- Did the change add AI-slop names, comments, abstractions, tests, or
  compatibility?
- Are typed contracts, runtime failure modes, and behavior proofs explicit?
- Is the architecture simpler after the change, or merely different?

## Fable protocol

Use Fable only when its answer should change a high-value decision.

Good uses:

- architecture direction and canonical-owner disputes;
- redesign versus focused cleanup;
- public API, runtime, or data-model choices with high rollback cost;
- judging a concrete diff, fresh live-harness result, or before/after evidence
  bundle that routine review cannot settle.

Poor uses:

- broad inventory a local or routine peer can produce;
- re-reading old findings without a source or evidence delta;
- implementation;
- another general review when the current blocker is an unmade product decision.

Rules:

1. Run one scarce reviewer at a time.
2. Send a bounded source packet with exact paths, scope, known hypotheses,
   evidence limits, and an output location.
3. Ask for ranked findings before diagrams, matrices, or roadmaps.
4. Run the reviewer in normal execution mode with read-only repository
   permissions; do not invoke it in plan mode.
5. Let Fable reframe the problem; label Codex or Claude theories as hypotheses.
6. Verify high-impact file claims locally before changing code or policy.
7. Behavior claims for Flow AI Builder require fresh-session evidence when
   deterministic tests cannot prove them; repeat flaky signals before trusting
   them.
8. After a useful pass, verify, implement, decide, or park the finding. Do not
   spend another broad pass merely to understand the first.

## Antigravity escalation

Use Antigravity only after routine review leaves a specific hard disagreement or
high-cost uncertainty. Give it the concrete plan, diff, evidence, and prior peer
artifact so it can adjudicate rather than repeat discovery.

Do not put Antigravity in hooks, recurring automation, or default validation.
If quota is unavailable, continue from locally verified evidence instead of
weakening the engineering decision.

## Local verification

Before acting on any reviewer finding:

- verify irreversible or high-impact claims in current source;
- separate valid findings from stale, overstated, or wrong claims;
- name the current and proposed canonical owner;
- choose delete, reuse, move, or merge before adding;
- define the smallest reviewable slice;
- identify the behavior or contract check that proves the result;
- record evidence-backed disagreements instead of silently ignoring them.

“The reviewer said so” and a numeric score are never sufficient reasons.

## Review packet modes

Use the smallest packet that permits a correct decision, not the smallest token
count.

| Mode | Use when | Packet | Reviewer job |
|---|---|---|---|
| Source packet | First-pass plan, architecture direction, or ownership choice | Problem, candidate owner, relevant files, standards, tests, unknowns | Challenge framing, owner, proof, and delete/reuse alternatives |
| Diff review | A concrete implementation slice exists | Diff summary, changed files, test results, risky callers, standards | Find bugs, owner drift, missing tests, and new debt |
| Follow-up verification | Prior findings were fixed or rejected | Prior artifact, finding-by-finding response, changed files, validation | Verify each concern and inspect only affected expansion unless ownership moved |
| Live evidence | Behavior depends on deployed API, worker, provider, or Builder behavior | Before/after bundles, commands, fresh-session evidence, source owners | Judge whether evidence proves behavior and what should become deterministic |
| Broad audit | The canonical owner is genuinely unknown | Bounded inventory, search terms, standards, stop conditions | Map owners and risks, then return a narrower next packet |

Follow-up review should not re-inventory the whole repository unless the fix
moved ownership, changed a shared contract, or the packet cannot prove the
result.

## Eneo Flow gates

Flow and Flow AI Builder are pre-production product-critical surfaces.

- Start each slice with current owner, proposed owner, duplicate paths, and
  deletion candidates.
- Public API changes name OpenAPI and generated-client impact and run the
  contract-generation checks.
- Runtime changes follow the
  [Runtime Reliability Standard](runtime-reliability-standard.md); the packet states
  persisted owner, transaction boundary, retry/crash/ambiguous-outcome behavior,
  effects, terminalization, and retention consequences that apply.
- Builder behavior changes include fresh-session API or live-harness evidence
  when deterministic tests cannot prove the user-visible behavior.
- Compatibility for unreleased behavior requires persisted-data evidence, an
  owner, and a deletion trigger.
- Deleting behavior includes deleting obsolete tests and documentation.
- Frontend/backend compatibility deletion checks both owners before removing
  either side.

## Artifacts and tracking

Review artifacts are local by default. “Curated” or “retained” does not mean
Git-tracked.

- `.codex/artifacts/` holds raw stderr, stream output, wrapper transcripts,
  scratch notes, implementation receipts, and large logs.
- `fablereview/<program>/` may hold curated local prompts, reports, status
  sidecars, indexes, and verification summaries that must survive `/tmp`
  cleanup.
- Promote a human-useful conclusion to a tracked engineering standard, ADR,
  product document, issue, or pull request only when the team deliberately wants
  it as shared authority.
- Do not commit raw reviewer output or make future implementers read tool noise.
- Implementation receipts follow the
  [Review-to-Implementation Handoff](maintainability-standards.md#review-to-implementation-handoff).

## What not to build

- No hooks that automatically spend Claude, Codex, Fable, or Antigravity.
- No new reviewer tiers, scorecards, or gates without a concrete missed defect.
- No copied peer-loop CLI, model, timeout, or session instructions in
  `AGENTS.md`, `CLAUDE.md`, prompts, or project hooks; routers may link to this
  standard and name the complementary host.
- No retention daemon for local artifacts; conventions and explicit promotion
  are sufficient.
- No reviewer-generated architecture that bypasses current source, product
  decisions, or the canonical engineering owner.
