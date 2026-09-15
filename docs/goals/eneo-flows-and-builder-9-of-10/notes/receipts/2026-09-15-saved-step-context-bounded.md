# Saved-step edit context: whole-flow list vs one step's neighbourhood, 2026-09-15

Paired live measurement for eneo-341 (step-focused edit context must not scale with flow size),
run through the harness saved-step edit case (eneo-x1r). Per-observation facts in
`saved-step-context-bounded-2026-09-15/observations.json`.

## Sources and stacks

| Lane | Source | Serves | Space |
| --- | --- | --- | --- |
| parent | tidy `8f575a957` (`other_steps` lists every non-target step) | `:8146`, worktree `eneo-ai-builder-parent-20260913`, DB `eneo_ai_builder_parent` | `9fe65f26` |
| candidate | `5d427fb81` on top of `4936a908e` (`flow.step_count` plus the target's producers and consumers only) | `:8144`, worktree `eneo-ai-builder-candidate-341`, DB `eneo_ai_builder_simplify` | `6f18b073` |

Both worktrees were clean and served the stated commit for the whole acquisition
(07:31 to 07:41 CEST). Two models on both stacks: `gpt-5.6-luna` (OpenAI-compatible provider, strict
tool schema) and `gemma4-31b-it` (tool calling off, non-strict), the latter copied into the parent
DB for this run. Cases `edit_chain_10_instruction` and `edit_chain_30_instruction`: the same
three-step chain, target step 3 "Skriv beslutsdokument" (text, pass-through) and terminal
"Rendera PDF", with 6 or 26 review steps in between; the same Swedish message asks the target to
always list the missing information as a bullet list. Three repetitions per cell, one fresh
seeded flow and one fresh edit session per observation, flow deleted after each.

## Prompt tokens per observation (provider-reported, not estimated)

| Lane | Model | Steps | n | Median | Range | First pass | Repairs | Untouched steps unchanged |
| --- | --- | ---: | ---: | ---: | --- | --- | ---: | --- |
| parent | luna | 10 | 3 | 11,325 | 11,323 to 11,353 | 3/3 | 0 | 3/3 |
| parent | luna | 30 | 3 | 12,576 | 12,534 to 12,672 | 3/3 | 0 | 3/3 |
| parent | gemma | 10 | 3 | 8,981 | 8,977 to 8,983 | 3/3 | 0 | 3/3 |
| parent | gemma | 30 | 2 | 10,523 | 10,522 to 10,524 | 2/2 | 0 | 2/2 |
| candidate | luna | 10 | 3 | 10,970 | 10,868 to 10,976 | 3/3 | 0 | 3/3 |
| candidate | luna | 30 | 3 | 10,840 | 10,840 to 10,844 | 3/3 | 0 | 3/3 |
| candidate | gemma | 10 | 3 | 8,370 | 8,368 to 8,372 | 3/3 | 0 | 3/3 |
| candidate | gemma | 30 | 2 | 8,370 | 8,370 to 8,370 | 2/2 | 0 | 2/2 |

Derived, medians:

| Comparison | luna | gemma |
| --- | ---: | ---: |
| parent, 10 to 30 steps | +1,251 (+11.0 %) | +1,542 (+17.2 %) |
| parent, per added unrelated step | 63 | 77 |
| candidate, 10 to 30 steps | -130 (-1.2 %) | 0 |
| candidate vs parent at 10 steps | -355 (-3.1 %) | -611 (-6.8 %) |
| candidate vs parent at 30 steps | -1,736 (-13.8 %) | -2,153 (-20.5 %) |

Measured range is 10 to 30 steps; nothing here is extrapolated beyond it. The parent's cost is
linear in the number of unrelated steps at roughly 63 to 77 prompt tokens per step, the whole of
one `other_steps` entry (ref, number, name, sources and modes). The candidate is flat: the two
sizes differ by the step count only.

Outcomes are identical across all 22 observations: first-pass plan, no repair, the target
modified, every other step reported unchanged by the server's own diff. This cohort does not
exercise reference-based edits, so it says nothing about the capability loss Astra reproduced
on `5d427fb81` (a step that is neither producer nor consumer has no name in the prompt); that
finding stands on its own.

## Failures

One observation per stack failed before the turn (gemma, 30 steps, repetition 2, 07:39:09 and
07:39:13 CEST): the seeding `PATCH /flows/{id}/assistants/{assistant_id}/` answered 404 right
after the assistant's 201. Harness failure class `harness_configuration`, both half-built flows
deleted, no flow left in either space. The same request succeeded in the other 22 seedings; the
cause is not identified and the harness does not retry it. The cell keeps n = 2.

## What the measurement decides

- The bead's premise holds and is bounded: on the parent every unrelated step costs about one
  `other_steps` entry, 63 to 77 prompt tokens, so a 30-step flow spends 11 to 17 % more prompt
  than a 10-step flow on the same edit. Repair rate and outcome do not change with size in this
  range; the cost is tokens, not reliability.
- `5d427fb81` removes that cost completely, and removes the names with it. Given Astra's
  reproduction, the saving is bought with a capability loss, so the plain deletion should not land.
- The saving is per entry, so most of it survives a projection that keeps the name: an unrelated
  step listed as number and name only is a fraction of the current entry. That is the shape to
  measure next if the owner wants both the bound and reference-based edits, instead of a
  message-based reference parser.

## Side finding (eneo-mhr)

On both sources, both models, all 22 plans: the server renamed the target step from
"Skriv beslutsdokument" to "Förbered PDF-innehåll" and prefixed its instructions with the
artifact-body boilerplate. The model was asked to change the instruction, not the name. The
pre-terminal artifact-body normalizer runs on the rederived target while the mutation scope
protects only the untouched steps. Recorded as its own bug; not part of this comparison.
