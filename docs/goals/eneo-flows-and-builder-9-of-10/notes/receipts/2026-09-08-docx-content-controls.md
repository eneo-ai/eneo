# DOCX content controls: verification, 2026-09-08

The candidate addresses the DOCX gate findings: neutral templates, preserved pre-title content, structural control inspection, aggregate inline limits, scalar bindings before publish, selected-template metadata in the final Builder prompt, and explicit list limits. A final regression also prevents silent loss of parent-item text after a nested list; that form now fails explicitly. Builder preparation remains one string per placeholder. Templates with no controls are rejected at upload, publish and runtime; ordinary source attachments remain valid. Declared scalar enum, const and union fields are accepted without admitting objects or arrays.

Base: `60436fd4d47cd1777646b519c947cdffad1e281e` (tidy). Original feature: `5993a56aa561c684b3d8393e9be52ff5b39fbe87`. Corrected source identity is recorded in the accompanying SHA-256 manifest; the final commit is linked from `eneo-ytn`. Machine: macOS 26.5.2 arm64, Python 3.11.14. Commands below ran from `/Users/ccimen/eneo/eneo-ai-builder-review-ui` unless another directory is given.

## Table rendering

The benchmark calls the public `DocumentRenderService.render_document` path for DOCX. Each table has ten columns; counts include the header row. Each size has one warm-up followed by three timed runs. The baseline and candidate used the same machine and Python environment. Other local test processes were running, so these are local microbenchmark observations, not a provider latency floor.

| Cells | Baseline median, seconds | Candidate median, seconds |
| ---: | ---: | ---: |
| 250 | 0.289142 | 0.017972 |
| 500 | 1.101421 | 0.024637 |
| 1,000 | 4.409997 | 0.039154 |
| 2,000 | 17.237209 | 0.073267 |

Raw timings: [candidate](docx-content-controls-2026-09-08/benchmark-candidate.jsonl), [tidy baseline](docx-content-controls-2026-09-08/benchmark-base-60436fd4d.jsonl). [Benchmark script](docx-content-controls-2026-09-08/benchmark_docx_tables.py).

Reproduction, from each revision's `backend/` directory with its normal environment available:

```sh
PYTHONPATH=src .venv/bin/python /absolute/path/to/benchmark_docx_tables.py > benchmark.jsonl
```

For the measured baseline, a clean archive of `60436fd4d` was extracted to `/tmp/eneo-docx-baseline-60436fd4d`; its `.venv` pointed to the candidate environment. The candidate measurement preceded a type-only XML factory adapter and installation of official lxml stubs; neither changes table traversal. The shared writer creates cells once instead of repeatedly scanning the growing table through python-docx's cell accessors.

## Tests and static checks

Backend tests used the required wrapper:

```sh
PATH=/Users/ccimen/.local/bin:/opt/homebrew/bin:$PATH \
  /Users/ccimen/.claude/skills/eneo-slice-landing/scripts/lanetest.sh \
  /Users/ccimen/eneo/eneo-ai-builder-review-ui <pytest paths>
```

| Check | Observed result |
| --- | --- |
| Full backend `tests/unittests/flows tests/unit -v` | 9,631 passed, 11 failed, 10 skipped, 1 xfailed; 616.01 s. One publish fixture needed its referenced form field declared and was corrected. |
| Final affected `test_document_renderer.py`, `test_docx_template_runtime.py`, `test_flow_service.py` | 151 passed, 10 skipped; 7.74 s. Includes the corrected publish fixture. |
| Actual materialized attachment publish, rich + text controls | 3 passed: valid publish pins/reloads/renders; missing and structured bindings leave zero versions; 30.51 s. |
| Final list-continuation regression, DOCX runtime and Builder proposal prompt suites | 99 passed, 10 skipped; 1.70 s. The new unsupported-form test failed before the parser correction. |
| Final contract corrections: renderer, DOCX runtime, template assets, Flow service, graph validators, Builder proposal prompt, template references and variable definitions | 381 passed, 10 skipped; 3.23 s. New empty-template, corrupt-template and scalar-schema cases reproduced before correction. |
| Final `tests/integration/flows/test_flow_template_attachment_persistence.py` | 9 passed; 29.74 s. Actual publish and pinned-template rendering remain valid after the empty-template guard. |
| Strict backend Pyright, `.venv/bin/pyright --pythonpath .venv/bin/python` | 0 errors, 0 warnings. Official `types-lxml` is a development dependency; checking remains strict. |
| Ruff and frontend ESLint | Changed files pass; Ruff formatting and `git diff --check` pass. |
| Frontend `bun run check` | 0 errors, 0 warnings. |
| Full frontend `bunx vitest run src/lib/features/flows` | 1,252 passed, 104 failed; Node 25 native localStorage broke 102 tests. The 22 template binding tests passed. |
| Five failed frontend files rerun with `NODE_OPTIONS=--no-experimental-webstorage` | 118 passed, 2 failed. |
| Same checkpoint/counts files on clean tidy baseline with that Node setting | 19 passed, the same 2 checkpoint tests failed. |
| Knowledge counts teardown recheck | 3 passed, no unhandled error. |

The ten remaining backend failures were rerun as exact node IDs on the clean tidy archive: **all ten reproduced**, in 35.75 s. The [node list](docx-content-controls-2026-09-08/baseline-unit-nodeids.txt) is owned by cleanup issue **eneo-wqq**. They cover remote transcription, AI Builder public error/OpenAPI contracts, audit mappings, route audit coverage and router exports. The two frontend baseline failures both concern the checkpoint panel's audio context and missing `Hej` button. These comparisons establish provenance; they do not make either full suite green.

The ten Mac skips require the native WeasyPrint stack. DOCX rendering tests ran; this receipt does not claim that the native PDF tests passed on macOS. The built Linux image also rendered a 9,713-byte PDF through the public renderer as a smoke check; that is separate from the skipped Mac tests.

## Word and visual inspection

On 2026-09-08, Microsoft Word for Mac opened the neutral generic output and filled `rapport.docx`, plus the neutral report and meeting templates. Tools → Check Accessibility reported **“Looks good! No issues found.”** for each document. Each of the six visible categories showed zero issues: contrast, alt text, table headers, merged/split cells, headings and restricted access.

- [Generic rendered document and checker](docx-content-controls-2026-09-08/word-generic-accessibility.png): pre-title text retained; styles, marked table header, nested and separate numbering restarts, hyperlink and emphasis inspected.
- [Filled report and checker](docx-content-controls-2026-09-08/word-rapport-accessibility.png): all seven controls filled; fixed headings retained; section heading demoted; table, lists and link inspected.
- [Neutral report template](docx-content-controls-2026-09-08/word-rapport-template-accessibility.png).
- [Neutral meeting template](docx-content-controls-2026-09-08/word-meeting-template-accessibility.png).

LibreOffice page renders of all three templates and both filled samples were also inspected: one page each, no visible clipping or overlap. The placeholder-only generic template intentionally contains no content heading until it is filled. Word's checker result is evidence for these specific samples, not a blanket accessibility certification.

The checked generated samples are identified by [SHA-256 hashes](docx-content-controls-2026-09-08/word-sample-hashes.json). Local delivery copies are in `/Users/ccimen/eneo/eneo-docx-templates/verified-2026-09-08/`; the owner's original files remain intact.

## Remaining verification

Full `tests/integration/flows`: **448 passed, 1 failed**, 1,374.53 s. `test_ai_builder_turn_retry_survives_hard_process_failures` exceeded its 20-second child-process deadline. The isolated test passed on unchanged tidy in 64.85 s. The isolated candidate recheck also passed, in 60.21 s, without changing recovery code or the deadline. The broad run observed one process-deadline timeout; the isolated rerun is the final result for that test. Peer review, landing, lane rebuild and live Builder/verbatim-flow verification remain pending.
