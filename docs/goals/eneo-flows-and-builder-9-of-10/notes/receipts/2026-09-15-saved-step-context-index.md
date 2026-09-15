# Saved-step edit context index and saved-step name ownership, 2026-09-15 (round 2)

Paired live measurement of the slice `perf/ai-builder-step-context-index` (commits `8b599f4f0`
eneo-mhr, `1be747b7d` eneo-341, `5b7418e2f` harness case) against the tidy tip. Same protocol
as `2026-09-15-saved-step-context-bounded.md` (round 1), plus the reference-rename case. Per-observation
facts in `saved-step-context-index-2026-09-15/observations.json`.

## Sources and stacks

| Lane | Source | Serves | Space |
| --- | --- | --- | --- |
| parent | tidy `07eb1c172` (full `other_steps` entries; artifact-body normalizer shapes saved steps) | `:8146`, worktree `eneo-ai-builder-parent-20260913` | `9fe65f26` |
| candidate | `5b7418e2f` (unrelated steps as number + name; normalizer shapes only new steps) | `:8144`, worktree `eneo-ai-builder-candidate-341` | `6f18b073` |

Both worktrees clean and serving the stated commit throughout (08:17 to 08:32 CEST). Models
`gpt-5.6-luna` and `gemma4-31b-it` on both stacks. Cases: `edit_chain_10_instruction` and
`edit_chain_30_instruction` (change the target's instruction) and `edit_chain_10_reference`
("Döp om det här steget till samma namn som steg 1 följt av \" - kontroll\". Ändra inget annat.",
step 1 = "Extrahera källfält"). Three repetitions per cell, fresh seeded flow and edit session per
observation, flow deleted afterwards.

## Prompt tokens per observation (provider-reported)

| Lane | Model | Case | n | Median | Range | First pass | Repairs | Untouched unchanged |
| --- | --- | --- | ---: | ---: | --- | --- | ---: | --- |
| parent | luna | 10, instruction | 3 | 11,335 | 11,331 to 11,363 | 3/3 | 0 | 3/3 |
| parent | luna | 30, instruction | 3 | 12,582 | 12,580 to 12,684 | 3/3 | 0 | 3/3 |
| parent | luna | 10, reference | 3 | 11,327 | 11,325 to 11,331 | 3/3 | 0 | 3/3 |
| parent | gemma | 10, instruction | 3 | 8,983 | 8,983 to 8,989 | 3/3 | 0 | 3/3 |
| parent | gemma | 30, instruction | 3 | 10,518 | 10,512 to 10,524 | 3/3 | 0 | 3/3 |
| parent | gemma | 10, reference | 3 | 8,977 | 8,973 to 8,977 | 3/3 | 0 | 3/3 |
| candidate | luna | 10, instruction | 3 | 11,020 | 10,994 to 11,024 | 3/3 | 0 | 3/3 |
| candidate | luna | 30, instruction | 3 | 11,423 | 11,421 to 11,453 | 3/3 | 0 | 3/3 |
| candidate | luna | 10, reference | 3 | 10,982 | 10,982 to 10,986 | 3/3 | 0 | 3/3 |
| candidate | gemma | 10, instruction | 3 | 8,544 | 8,542 to 8,546 | 3/3 | 0 | 3/3 |
| candidate | gemma | 30, instruction | 3 | 9,051 | 9,051 to 9,053 | 3/3 | 0 | 3/3 |
| candidate | gemma | 10, reference | 3 | 8,534 | 8,532 to 8,536 | 3/3 | 0 | 3/3 |

Derived, medians of the instruction cases:

| Comparison | luna | gemma |
| --- | ---: | ---: |
| parent, 10 to 30 steps | +1,247 (+11.0 %) | +1,535 (+17.1 %) |
| parent, per unrelated step | 62 | 77 |
| candidate, 10 to 30 steps | +403 (+3.7 %) | +507 (+5.9 %) |
| candidate, per unrelated step | 20 | 25 |
| candidate vs parent at 10 steps | -315 (-2.8 %) | -439 (-4.9 %) |
| candidate vs parent at 30 steps | -1,159 (-9.2 %) | -1,467 (-13.9 %) |

Measured range 10 to 30 steps. The candidate still grows with the flow, at a third of the
parent's slope: one `{step_number, name}` entry per unrelated step instead of the step's full
shape. Outcomes: all 36 observations first pass, no repair, untouched steps unchanged.

## What each plan changed on the target

| Lane | Case | Fields changed | Name after the edit |
| --- | --- | --- | --- |
| parent | instruction (12) | name, instructions | "Förbered PDF-innehåll" (12/12) |
| parent | reference (6) | name, instructions | "Förbered PDF-innehåll" (6/6) |
| candidate | instruction (12) | instructions | "Skriv beslutsdokument" kept (12/12) |
| candidate | reference (6) | name | "Extrahera källfält - kontroll" (6/6) |

On the parent the artifact-body normalizer rewrites the edited step on every plan: an instruction
edit also renames the step, and the requested rename to "Extrahera källfält - kontroll" is
overwritten before the user sees it, so a reference-based rename cannot succeed on the tidy tip at
all (eneo-mhr). On the candidate the instruction cases change only the instructions and the
reference case changes only the name, to exactly the requested value, on both models. The
reference case also answers the blocker on the earlier deletion candidate: with the name index the
model resolves "steg 1" from the projection.

## Acquisition failures

Ten candidate invocations failed before the turn and were re-run (all re-runs succeeded, n = 3
everywhere). The root cause is one event: at 08:20:40 a seeding `POST .../assistants/` was refused
with 403 `insufficient_scope` 18 ms after the flow's 201, the cleanup `DELETE` was refused the same
way, and the orphaned 10-step flow then made every later 10-step seeding fail on the flow-name
uniqueness constraint (500) until it was deleted by hand. Together with round 1's two 404s on
`PATCH .../assistants/{id}/` right after a 201, this is a read-after-write race: the flow authoring
routes committed their transaction after the response was sent (FastAPI request-scoped yield
dependency), so a client's immediate follow-up request could miss the row. Fixed on this branch by
committing before the response (function-scoped container) on the mutating flow and flow-assistant
routes; the harness itself does not retry.
