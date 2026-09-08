# Builder field guidance and baseline test fixes, 2026-09-08

The shared Builder prompt now shows complete field objects, including nested members through `children`. Schema type errors identify required properties from the actual tool schema. Structured-JSON guidance follows a requested textual fallback instead of offering null as an interchangeable default. Strict admission and the four-call proposal budget remain unchanged; there is no provider-specific branch or new coercion.

The original report proposal failure no longer occurs in the matched candidate probes: Gemma creates a valid plan with all seven template bindings on its first proposal call. The wider nested-JSON requirement check remains **unsatisfied**: the final plan permits null for `ansvarig` and `tidsfrist`, although the request describes strings. Clearer prompts have not established reliable compliance with that semantic detail. `eneo-3te` remains open for this measured limitation. The ten backend test failures and two frontend checkpoint failures are resolved in `eneo-wqq`.

The remaining semantic mismatch is already owned by `eneo-4ok.7`: carry cited nullability through classification, persisted planning state, proposal admission and the compiled postcondition. The current postcondition does not verify it. That existing contract work is broader than field-shape guidance and was not duplicated here.

Source before this work: `19f309c7d1f6374f916fb720bb815a4ddc2efe79`. Final product source: `8c5c8e24cf8e5853c0d83d0789e5ea1c35d0db2b`, on local branch `feature/builder-schema-guidance`. Receipt and ledger commits do not change product source.

## Matched provider evidence

The [workload manifest](builder-schema-guidance-2026-09-08/provider-manifest.json) was frozen before acquisition. Each revision ran the same three synthetic requests in the same order: Gemma report, Gemma nested JSON, Luna/high report. Each case used a fresh session, at most six UI turns and a 240-second HTTP timeout, with no external retries. Product repair limits were unchanged. Parent acquisition used image source `2c23f4a2545dd79f39ddca1025c86d3b242da836`; its backend tree is identical to `19f309c7d`.

Proposal calls and time below come from actual `proposal_turns[].attempts`, including every repair. They exclude discovery calls and other session work. Raw session times and identifiers are retained in the [checks](builder-schema-guidance-2026-09-08/plan-checks.json). These are individual observations, not a measured failure rate or latency guarantee.

| Source | Case | Proposal calls | Proposal seconds | Proposal tokens | Requirements |
| --- | --- | ---: | ---: | ---: | --- |
| Parent `19f309c7d` | gemma-template_report | 4 | 45.115 | 26,503 | Pass |
| Parent `19f309c7d` | gemma-nested_json | 2 | 9.787 | 8,518 | Fail: string array |
| Parent `19f309c7d` | luna-template_report | 1 | 27.771 | 5,540 | Pass |
| First `19bd53529` | gemma-template_report | 1 | 9.832 | 5,816 | Pass |
| First `19bd53529` | gemma-nested_json | 1 | 4.945 | 4,076 | Fail: string array |
| First `19bd53529` | luna-template_report | 1 | 19.460 | 6,478 | Pass |
| Nested `1c4d4d972` | gemma-template_report | 1 | 14.929 | 6,374 | Pass |
| Nested `1c4d4d972` | gemma-nested_json | 1 | 5.662 | 4,236 | Fail: nullable members |
| Nested `1c4d4d972` | luna-template_report | 1 | 28.253 | 6,608 | Pass |
| Final `8c5c8e24c` | gemma-template_report | 1 | 14.331 | 6,340 | Pass |
| Final `8c5c8e24c` | gemma-nested_json | 1 | 5.432 | 4,251 | Fail: nullable members |
| Final `8c5c8e24c` | luna-template_report | 1 | 19.345 | 5,596 | Pass |

The first candidate removed malformed field objects but still emitted an array of strings for requested object items, as the parent did. The second candidate added a recursive field example and restored all nested members. Its two nullable string fields failed the exact requested type check. The third candidate corrected generic missing-value guidance, but that same nullable-field mismatch persisted. Both failed candidate dimensions are retained, with fresh [second](builder-schema-guidance-2026-09-08/candidate2-freeze.json) and [third](builder-schema-guidance-2026-09-08/candidate3-freeze.json) acquisition freezes; no disappointing leg was silently repeated.

All report plans contain `titel`, `datum`, `forfattare`, `sammanfattning`, `bakgrund`, `analys` and `slutsatser`, with seven string preparation fields and seven DOCX bindings. Final plans: [Gemma report](builder-schema-guidance-2026-09-08/provider-candidate3/gemma-template_report/plan.json), [Gemma JSON](builder-schema-guidance-2026-09-08/provider-candidate3/gemma-nested_json/plan.json), [Luna report](builder-schema-guidance-2026-09-08/provider-candidate3/luna-template_report/plan.json). Each corresponding folder contains proposal diagnostics.

Run `python3 check_plans.py` inside the evidence directory to reproduce the offline checks. It prints every result and exits 1 for the known final nullable-field mismatch. This is the unmet provider requirement floor, separate from the passing repository test suites. No broad quality claim or branch landing is recorded. The probes inspect authoring plans; the earlier DOCX receipt contains the actual document execution evidence.

## Test and contract corrections

The baseline failures exposed missing transcript audit mappings, router export/coverage declarations and three untyped Builder edit errors, plus stale transcription, OpenAPI and checkpoint assertions. Content-bearing transcript GET endpoints now reuse the existing evidence snapshot transaction and required trace audit. Their access event must commit before response bytes; audit insertion or commit failure returns 503 without content. HTTP regressions exercise both failures and count the committed event at response start. Generated SDK types include the new documented 503 responses and current audit action count.

Transcription still preserves service text and word timings. OpenAPI tests reflect the current status values and nullable retry request. The two checkpoint tests now find visible transcript text and the timestamp seek control. No product checkpoint behavior or strict API validation was weakened.

| Check | Result |
| --- | --- |
| Reproduce the ten recorded backend nodes on `19f309c7d` | 10 failed, 14.43 s |
| Full backend `tests/unittests/flows tests/unit`, at `19bd53529` | 9,659 passed, 10 skipped, 1 xfailed; 120.45 s |
| Affected evidence API, transcript corrections and transcript words integration suites | 41 passed; 116.27 s |
| Full frontend Flow suite at `19bd53529` | 1,364 passed across 114 files; 42.04 s |
| Final prompt, result-contract, tool and submission suites | 110 passed; 0.77 s |
| Full strict Pyright after the final production edit | 0 errors, 0 warnings |
| Svelte check, ESLint, Ruff, formatting and whitespace | Pass; Svelte reports 0 errors and 0 warnings |
| Actual pre-push checks after the final production edit | Pass, including OpenAPI metadata and generated SDK drift |

The new field-shape feedback cases and schema-validated prompt example failed before correction. Later nested-example and missing-value guidance checks also reproduced before their respective prompt changes. The full backend/frontend suites preceded only the final two prompt refinements; affected suites and full strict Pyright passed after those edits. Native WeasyPrint tests account for the ten Mac skips. The Linux image at `19bd53529` separately passed DOCX and PDF rendering smoke checks.

Backend tests used the repository wrapper:

```sh
PATH=/Users/ccimen/.local/bin:/opt/homebrew/bin:$PATH \
  /Users/ccimen/.claude/skills/eneo-slice-landing/scripts/lanetest.sh \
  /Users/ccimen/eneo/eneo-ai-builder-review-ui <pytest paths>
```

Frontend checks ran from `frontend/apps/web`: `bun run check` and `NODE_OPTIONS=--no-experimental-webstorage bunx vitest run src/lib/features/flows`, using Node 22.23.1. The option avoids the native localStorage environment mismatch established in the earlier receipt. Commit hooks passed; the Pyright hook's unrelated devcontainer target was replaced by the successful full local strict Pyright command, `.venv/bin/pyright --pythonpath .venv/bin/python`. No checks or repository configuration were weakened.

## Local state and template selection

All four local `:8144` app containers run image `eneo-builder-debug:8c5c8e24cf8e`, image ID `sha256:dae18be2f45018cf788ef05aa5de6c06c5581a07bb1baf6d9310ee886ebb95a8`, built from the clean committed backend with the repository Dockerfile and frozen dependencies. The [lane receipt](builder-schema-guidance-2026-09-08/lane-receipt.json) records container identities and retained rollback containers. The [health response](builder-schema-guidance-2026-09-08/health.json) reports backend and worker healthy; object content remains not configured. The frontend is running at `:3133`. This change did not migrate the database or replace the separate `:8146` lane. Remote branch landing is not part of this receipt.

The Swedish unsupported-content-control error comes from template inspection, before model use. Local `rapport_filled.docx` contains a `w:date` date picker tagged `datum`; that control type is unsupported. The exact file selected by the owner has not been confirmed. If it is that file, replace the date picker with a plain-text content control retaining tag `datum`. Use body-level rich-text controls for sections and inline text controls for fields, with unique tags. The supplied local `rapport.docx` already has seven supported controls. Original owner documents were not changed.
