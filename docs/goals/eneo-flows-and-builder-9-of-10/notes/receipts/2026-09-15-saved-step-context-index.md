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

## Did the instruction edits do what was asked?

The message asks the step to always list the missing information in the application as a bullet
list. Adjudicated from `target_field_changes` (previous and current instruction text) in every
instruction-edit bundle, candidate and parent, by the presence of "punktlista" together with
"saknas"/"saknade" in the new text and their absence in the old text:

| Lane | Model | n | Requested behaviour present in the new instructions | Present in the old |
| --- | --- | ---: | ---: | ---: |
| candidate | luna | 6 | 6 | 0 |
| candidate | gemma | 6 | 6 | 0 |
| parent | luna | 6 | 6 | 0 |
| parent | gemma | 6 | 6 | 0 |

Examples of the added sentence (gemma, candidate): "Under rubriken 'Saknade uppgifter och
kompletteringar' ska du alltid lista vilka uppgifter som saknas i ansökan i form av en punktlista."
Luna folds the same requirement into a rewritten paragraph under that heading. In all 24 plans the
model rewrote the instruction paragraph rather than appending a sentence, keeping the original
headings and requirements; on the parent the boilerplate prefix is added on top. Every observation
in `observations.json` carries `target_field_changes` with the full previous and current value of
each changed field, and the instruction observations carry `instruction_check` (the rule above
applied to both texts); the reference observations carry `reference_check` (expected name, name
after the edit, exact match, only the name changed).

## Acquisition failures

Ten candidate invocations failed before the turn and were re-run (all re-runs succeeded, n = 3
everywhere). Two distinct events, both the same defect, account for all ten:

- 08:20:40, one 403: a seeding `POST .../assistants/` was refused with `insufficient_scope` 18 ms
  after the flow's 201, the cleanup `DELETE` was refused the same way, and the orphaned 10-step
  flow then made the next eight 10-step seedings (instruction and reference cases, both models)
  fail on the flow-name uniqueness constraint (500) until it was deleted by hand at 08:27.
- 08:23:06, one 404: a seeding `PATCH .../assistants/{id}/` on the 30-step fixture (gemma,
  repetition 2) was refused right after the assistant's 201, the same shape as round 1's two 404s.

Both are the read-after-write race: the flow authoring routes committed their transaction after the
response was sent (FastAPI request-scoped yield dependency), so a client's immediate follow-up
request could miss the row. Fixed on this branch by committing before the response (function-scoped
container) on the mutating flow and flow-assistant routes; the harness itself does not retry. The
parent stack, which serves the tidy tip without the fix, had no failure in 18 seedings this round;
the race is timing-dependent. Tracked population across both receipts: 70 seeding attempts (24 in
round 1, 46 in round 2), 4 primary failures (two 404s in round 1, one 403 and one 404 in round 2)
and 8 consequent 500s; smoke runs outside the receipts are not counted.

## Suite results on the branch

`backend/tests/unittests/flows/ai_builder`: 4533 passed. `backend/tests/integration/flows` on
`8f7f931d6`: 468 passed, 1 failed: `test_hard_exited_worker_stale_recovery_converges`. The failure
is the fixture's worker-startup guard, before the test's own assertions
(`tests/integration/flows/conftest.py:340`):

```
AssertionError: Disposable Flow worker did not report its exact owned queue within 30s. Worker log tail:
WARNING:root:OIDC_REDIRECT_GRACE_PERIOD_SECONDS (900) exceeds state TTL (600). ...
```

The test creates and reads back a queued run first (those assertions passed), then starts the
disposable worker, which did not announce its queue inside the readiness helper's 30 s budget. The
suite ran while both lane stacks were acquiring and an Astra gate was running on the same host;
host contention is the inferred cause, not a proven one. The file re-run alone on the idle host
passed (2 passed). This matches the startup-budget failure the program has on record as its one
known integration flake; nothing in this branch touches worker startup, dispatch or
reconciliation.

Ledger provenance: `observations.json` was re-extracted with lane-qualified bundle paths after a
basename collision (both lanes ran in parallel and produced identically timestamped bundle names)
had copied two candidate payloads into two parent rows. Every row's session and plan id and its
summary fields were verified against its bundle before writing (`extraction_note`,
`bundle_path`).
