# Codex Verification Prompt: Fable 07 Evidence And Legal Transparency Review

You are Codex running GPT-5.5 with xhigh reasoning as a source-verification reviewer.

Repository root: `/Users/ccimen/eneo/eneo-flows-clean`

## Hard Constraints

- Do not edit source, tests, migrations, package files, config, or docs.
- Do not run Claude, Fable, `claude_peer_loop.py`, `claude`, `agy`, Antigravity, subagents, or any other peer-loop tool.
- Do not browse the internet.
- Use only local source inspection and read-only commands such as `rg`, `sed`, `nl`, `git ls-files`, and test file reads.
- Do not run long test suites unless necessary; this is a verification review, not implementation.
- Treat Fable as a reviewer, not an authority.
- Apply Ponytail pressure: prefer delete/merge/reuse/simplify before adding, and flag broad compliance-platform or generic evidence-framework proposals.

## Inputs

Read:

- `fablereview/2026-07-03-eneo-flows-ai-builder/fable-07-evidence-legal-transparency-v2-review.md`
- `fablereview/2026-07-03-eneo-flows-ai-builder/fable-07-evidence-legal-transparency-v2-prompt.md`
- `fablereview/2026-07-03-eneo-flows-ai-builder/index.md`
- `docs/engineering/maintainability-standards.md`
- `docs/engineering/api-design-standard.md`
- `docs/engineering/testing-standard.md`

Then verify Fable's concrete claims against source.

## Mission

Verify the Fable 07 v2 evidence/legal-transparency review for false positives, missing evidence, priority inflation, and implementation readiness.

Focus especially on:

1. Fable's P1 rerun evidence-loss claim: rerun acceptance resets step result input/output/effective prompt/model params and replaces run input envelope, while superseded attempts keep only previews and `flow_step_attempts.input_payload_json`/`output_payload_json` exist but are never written.
2. Fable's model-setting traceability claim: persisted model parameters are configured kwargs, not necessarily actually sent kwargs, and JSON-mode retry/fallback is not recorded.
3. Fable's outbound HTTP/webhook evidence claim: request/delivery evidence is missing from run evidence and exists only partially/best-effort in audit/webhook rows.
4. Fable's strict export manifest vs debug projection owner reconciliation.
5. Fable's retention/purge honesty claims, including tombstones, dead/unused states, and whether purge deletes rows needed for future disclosure.
6. Any top-ranked findings that should be demoted, split, rejected, or raised.

## Required Output

Write a complete Markdown verification report with:

1. Five-line TL;DR.
2. `Verdict Matrix`
   - finding id/name;
   - Codex verdict: `verified`, `partially verified`, `unverified`, `false positive`, or `needs implementation spike`;
   - source evidence;
   - confidence.
3. `False Positives / Overclaims`
4. `Confirmed Legal/Disclosure Blockers`
5. `Confirmed High-ROI Non-Blockers`
6. `Implementation Backlog`
   - priority;
   - owner/canonical home;
   - smallest safe change;
   - acceptance criteria;
   - tests.
7. `What Not To Fix Now`
8. `Questions For Tomorrow`
9. `Verification Commands / Files Read`

If you verify a claim, include file:line citations. If you cannot verify it directly, say so and lower confidence.
