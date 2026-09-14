# Saved-step edits leave untouched steps as saved, 2026-09-14

Source measured: `ecf9e908f` on `fix/ai-builder-saved-step-keep-expansion` (base tidy `5b61b8e43`),
served by the candidate stack `:8144` at `GIT_COMMIT=ecf9e908fd2f` (worktree
`/Users/ccimen/eneo/eneo-ai-builder-c2-measure`, DB `eneo_ai_builder_simplify`). The same run on
the earlier candidates `4c5fee24d` and `d5e70b830` (before gate passes 3 and 2) is kept below it.

## What was measured

The exact flow behind eneo-qmo: `38d59091-0054-47a0-9bf6-e8b0a27e23a1` in space
`6f18b073-ea64-4a5e-8236-778a25e72d8f`, four steps (json, json, text, pdf/render_verbatim), whose
third step "Skriv beslutsdokument" writes the document the PDF step renders. Five saved-step
edit sessions, each a new session on the same flow with `edit_context {kind: saved_flow_step}`
on step 1 and the same Swedish message asking the step to always list the missing information
as a bullet list. Per-plan facts and telemetry in `sessions-ecf9e908f.json` (earlier runs: `sessions-4c5fee24d.json`,
`sessions.json`); the probe's stdout is not tracked.

## Before

eneo-qmo recorded this flow at 0/5 on `79db5fab1`: every turn refused with
`ai_builder_scoped_plan_edit_rejected`, four repair rounds, then
`self_correction_quality_failure`. Re-run on the same flow at `d8b5399f7` (refusal reason and
feedback logged) the reason was `unrelated_compiled_step_changed` naming `existing_step_3`: the
artifact-body normalizer renamed the untouched step to "Förbered PDF-innehåll" and prefixed its
instructions on every pass, so the guard saw a model change the model never made (bead comments
17:32, 17:59 UTC).

## After (ecf9e908f)

| Session | Outcome | Planner requests | Repair attempts | Prompt tokens | Total tokens | Seconds |
| --- | --- | ---: | ---: | ---: | ---: | ---: |
| 072bdeec | awaiting_approval, plan 14fa6c4a | 1 | 0 | 10,985 | 11,772 | 8.3 |
| 1928af6f | awaiting_approval, plan dcf983e1 | 1 | 0 | 11,013 | 11,796 | 94.1 |
| 496a10ca | awaiting_approval, plan 084d6fa5 | 1 | 0 | 10,983 | 11,771 | 8.4 |
| 11368097 | awaiting_approval, plan 1e5ce524 | 1 | 0 | 11,015 | 11,802 | 7.6 |
| dcd446d0 | awaiting_approval, plan c4d01552 | 1 | 0 | 11,013 | 11,783 | 6.6 |

Model `openai/gpt-5.6-luna` on every turn. The 94 s turn is one provider call (one planner
request, no repair, same token count as its neighbours): the time sits between credential
resolution and the first-attempt event, so it is provider latency, not Builder work. Every plan's
diff is `modified existing_step_1 [instructions]` and `unchanged` for steps 2, 3 and 4; step 3
keeps its saved name "Skriv beslutsdokument"; no advisories. The API log for the window holds five
`ai_builder_proposal_first_attempt` events and no scoped-edit rejection, no
`scoped_edit_preservation_failed`, no unchanged-target refusal.

## Earlier candidate (4c5fee24d)

| Session | Outcome | Planner requests | Repair attempts | Prompt tokens | Total tokens | Seconds |
| --- | --- | ---: | ---: | ---: | ---: | ---: |
| 85326a4c | awaiting_approval, plan 19f030be | 1 | 0 | 11,015 | 11,808 | 8.2 |
| db059026 | awaiting_approval, plan 97dbbe7c | 1 | 0 | 10,979 | 11,754 | 7.9 |
| 7a6f81ce | awaiting_approval, plan 87b02e25 | 1 | 0 | 10,985 | 11,765 | 8.5 |
| 616021ae | awaiting_approval, plan 62a754d5 | 1 | 0 | 10,979 | 11,736 | 7.3 |
| 2b759746 | awaiting_approval, plan 62b48551 | 1 | 0 | 11,107 | 12,190 | 11.0 |

Model `openai/gpt-5.6-luna` on every turn. Every plan's diff is `modified existing_step_1
[instructions]` and `unchanged` for steps 2, 3 and 4; step 3 keeps its saved name
"Skriv beslutsdokument"; no advisories. The API log for the window holds five
`ai_builder_proposal_first_attempt` events and no scoped-edit rejection, no
`scoped_edit_preservation_failed`, no unchanged-target refusal.

## Earlier candidate (d5e70b830)

| Session | Outcome | Planner requests | Repair attempts | Prompt tokens | Total tokens | Seconds |
| --- | --- | ---: | ---: | ---: | ---: | ---: |
| aa243053 | awaiting_approval, plan 5ce0517d | 1 | 0 | 11,111 | 11,987 | 10.5 |
| 3e4db91c | awaiting_approval, plan 0f682e0c | 1 | 0 | 11,021 | 11,777 | 7.7 |
| cc716baa | awaiting_approval, plan 87ea1d35 | 1 | 0 | 11,011 | 11,791 | 10.3 |
| a791cc36 | awaiting_approval, plan 484b8a23 | 1 | 0 | 10,983 | 11,753 | 7.3 |
| b535a0d3 | awaiting_approval, plan 9515dc88 | 1 | 0 | 10,989 | 11,757 | 6.7 |

Model `openai/gpt-5.6-luna` on every turn. Every plan's diff is `modified existing_step_1
[instructions]` and `unchanged` for steps 2, 3 and 4; step 3 keeps its saved name
"Skriv beslutsdokument"; no advisories; `scoped_target_existing_step_ref = existing_step_1`.
The API log for the window holds five `ai_builder_proposal_first_attempt` events and no
scoped-edit rejection, no `scoped_edit_preservation_failed`, no `saved_flow_invalid`.

## Scope of the claim

One flow, one model, one message, five sessions, one stack: this shows the recorded failure is
gone on the flow that recorded it. It is not a paired parent/candidate measurement over a
cohort; that measurement belongs to the bounded saved-step context slice that follows.
