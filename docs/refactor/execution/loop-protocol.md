# Implementation Loop Protocol

This protocol applies to every implementation batch. The loop is NOT
"keep going until something works." It is a fixed sequence with hard
stop conditions.

## Inputs the loop reads (in order)

1. `docs/refactor/phase4/refactor-plan.md`
2. `docs/refactor/implementation-order.md`
3. `docs/refactor/phase0/baseline.md`
4. `docs/refactor/phase7/implementation-readiness.md`
5. `docs/refactor/execution/implementation-bootstrap.md`
6. `docs/refactor/execution/loop-protocol.md` (this file)
7. `docs/refactor/execution/retrospective-checklist.md`
8. The PRD(s) for this batch
9. `docs/refactor/execution/batch-{N}-{name}/journal.md` (if continuing a batch)

### Cross-Batch Handoff Inputs

When a committed batch hands off to the next batch, the next agent must
read the same loop inputs above plus:

- the previous batch journal
- the previous batch latest retrospective
- the previous batch latest Claude reconciliation
- the previous batch carry-forward risks
- the PRD(s) for the next batch, resolved from
  `docs/refactor/implementation-order.md`

After each committed batch, the next agent continues with the next
batch in `implementation-order.md` by running `/plan` first. It should
not ask the user "what next?" unless a protocol gate is hit: validation
fails and is not a known baseline issue, Claude returns accepted or
partial findings, scope changes, a schema/API/migration/runtime
decision appears, deletion is not covered by the plan, push/PR is
wanted, or a dirty file's ownership is unclear.

## The loop

### Step 1 — Plan

Run `/plan`. Produce `docs/refactor/execution/batch-{N}-{name}/plan.md`
containing:

- behavior pins to add or rewrite BEFORE any deletion
- exact files to change, grouped by tier (A: source-only / B:
  persisted/public)
- exact validation commands to run (copy them from the batch's row
  in `implementation-order.md` — do not invent your own)
- acceptance criteria from the PRD, restated verbatim

Do not proceed to Step 2 until the plan exists and lists the
validation commands by exact shell string.

### Step 2 — Implement

Implement against the plan. Constraints:

- behavior pins land before any deletion or destructive change
- no commits, no pushes, no branch creation, no PR opening
- changes stay within the batch's stated file scope
- if implementation reveals the plan was wrong: STOP, update the
  plan, re-run /plan. Do not silently drift.

### Step 3 — Validation

Run EXACTLY the validation commands listed in the batch's row of
`implementation-order.md` plus any pin tests named in the plan and
implemented in the loop.

Capture the output verbatim into
`docs/refactor/execution/batch-{N}-{name}/validation-{iteration}.log`.
Raw validation logs may remain local-only. The durable journal and
retrospective must summarize validation outcomes instead of relying on
ignored raw logs as the only evidence.

If any command fails:
- record the failure in the journal
- go to Step 4 (retrospective will catch it)

If all commands pass:
- proceed to Step 4

### Step 4 — Self-retrospective

Open `docs/refactor/execution/retrospective-checklist.md`. Answer every item with
`pass` / `fail` / `n/a` and a one-line evidence citation
(file:line, test name, command output line, etc.).

Write the answers to
`docs/refactor/execution/batch-{N}-{name}/retrospective-{iteration}.md`.

Compute the gate per the "Final gate" section of
`docs/refactor/execution/retrospective-checklist.md`.

If RED: go back to Step 2 with a focused fix plan. Increment
iteration counter.

If YELLOW or GREEN: proceed to Step 5.

### Step 5 — Adversarial Claude review

Use the local Claude peer-loop script if it is available. Resolve the
script path from `$CLAUDE_PEER_LOOP_SCRIPT`; if it is unset, use this
default:

```bash
${CLAUDE_PEER_LOOP_SCRIPT:-/Users/ccimen/.agents/skills/claude-peer-loop/scripts/claude_peer_loop.py}
```

Use `--timeout-seconds 1500`, preserve the emitted artifact path, and
resume the same Claude session for later iterations. If the script is
not available in the implementation environment, write the packet below
to `docs/refactor/execution/batch-{N}-{name}/claude-packet-{iteration}.md`,
halt, and ask the human to relay it to Claude. Do not treat Codex
self-review as the Claude review.

Send Claude a packet containing:

- the batch's PRD section (the exact acceptance criteria)
- the batch's plan
- the diff summary (file list + brief change description per file)
- the validation log
- the retrospective answers

Use this exact framing:

> Attack this implementation against the PRD. Find regressions,
> missed acceptance criteria, behavior pin gaps, scope drift, and
> sneaky compatibility shims. Cite file:line. Plausibility-only
> attacks ("this might not scale") without a specific failure
> mode and code location should be marked as such — I will reject
> them.

Capture Claude's response verbatim to
`docs/refactor/execution/batch-{N}-{name}/claude-attack-{iteration}.md`.
Raw Claude attack packets may remain local-only. The durable
reconciliation must capture the verdict, accepted/partial/rejected
classifications, and resulting action.
Agents may write `raw-*.md` or `*transcript*.md` files into the batch
directory for local debugging; those files stay local unless the human
explicitly promotes them to a curated artifact.

For each Claude finding, classify:

- `accepted` — concrete evidence, plan changes
- `partial` — some merit, scoped fix
- `rejected: speculative` — no specific failure mode or location
- `rejected: out-of-scope` — real but belongs in a later batch
- `rejected: disagree` — concrete disagreement, document the
  reasoning

Write the classifications to
`docs/refactor/execution/batch-{N}-{name}/claude-reconciliation-{iteration}.md`.

If any `accepted` or `partial` items exist:
- fix them
- go back to Step 3
- increment iteration counter

If only `rejected` items exist:
- proceed to Stop conditions

### Stop conditions

The loop stops when ALL of the following are true:

- retrospective is GREEN or YELLOW with documented carry-forward
- Claude review produced no `accepted` or `partial` findings on
  the latest iteration
- iteration counter is ≥2 (the loop ran at least twice — once is
  not enough to call it stable)

OR when the iteration counter reaches 4 — at that point the loop
is thrashing. Stop, write a `stuck.md` summarizing the unresolved
disagreement, and hand back to the human.

### Step 6 — Commit Boundary (Post-Loop Handoff)

The loop itself never commits, pushes, or opens PRs unless the user
explicitly authorizes that action.

After a batch reaches GREEN or acceptable YELLOW and the latest Claude
review has no accepted or partial findings, the agent reports:

- exact staging list
- exact do-not-stage list
- validation results
- carry-forward risks
- suggested commit message
- next batch name from `docs/refactor/implementation-order.md`

The human approves the commit before the agent stages or commits.

Push requires explicit user approval.

PR creation requires explicit user approval.

### What the loop never does

- Commit/push/PR gating lives in Step 6.
- Never edits this protocol file mid-loop.
- Never edits the retrospective checklist mid-loop.
- Never edits the PRD mid-loop. (PRD changes are a separate human
  decision that triggers a new batch.)
- Never decides "good enough" without running the full
  retrospective.
- Never skips a Claude round even if the previous round was clean
  — the minimum is one full Claude round per loop completion.
