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
| Error registry and affected template/service/validator suites | 311 passed; 7.27 s. All seven control errors use `FlowApiErrorCode`, with matching generated SDK types and EN/SV translations. |
| Final taxonomy and attachment-publish integration checks | 10 passed; 33.68 s. Includes the startup requirement that taxonomy entries cover the full error registry. |
| Strict backend Pyright, `.venv/bin/pyright --pythonpath .venv/bin/python` | 0 errors, 0 warnings. Official `types-lxml` is a development dependency; checking remains strict. |
| Ruff and frontend ESLint | Changed files pass; Ruff formatting and `git diff --check` pass. |
| Frontend `bun run check` | 0 errors, 0 warnings. |
| Full frontend `bunx vitest run src/lib/features/flows` | 1,252 passed, 104 failed; Node 25 native localStorage broke 102 tests. The 22 template binding tests passed. |
| Five failed frontend files rerun with `NODE_OPTIONS=--no-experimental-webstorage` | 118 passed, 2 failed. |
| Same checkpoint/counts files on clean tidy baseline with that Node setting | 19 passed, the same 2 checkpoint tests failed. |
| Knowledge counts teardown recheck | 3 passed, no unhandled error. |
| Final error-mapping and template-binding frontend suites | 68 passed; 2.14 s. Eight new cases failed before registration, then passed; the no-control error resolves to Swedish conversion guidance through the same function the editor uses. |

The ten remaining backend failures were rerun as exact node IDs on the clean tidy archive: **all ten reproduced**, in 35.75 s. The [node list](docx-content-controls-2026-09-08/baseline-unit-nodeids.txt) is owned by cleanup issue **eneo-wqq**. They cover remote transcription, AI Builder public error/OpenAPI contracts, audit mappings, route audit coverage and router exports. The two frontend baseline failures both concern the checkpoint panel's audio context and missing `Hej` button. These comparisons establish provenance; they do not make either full suite green.

Error registration used `python3 backend/scripts/generate_flow_api_error_codes_ts.py`. OpenAPI types were regenerated from `app.openapi()` with the repository's schema-drift environment, then `bun x openapi-typescript <snapshot> -o src/types/schema.d.ts --default-non-nullable=false` and Prettier, as in CI. `bun run i18n:compile`, `bun run check`, strict Pyright and the final generated-code parity checks passed. No generated types were edited by hand. The browser tool's administrator policy blocked the local editor page; the Swedish check above is an executable test of the editor's error-mapping function, not a claimed browser upload.

The ten Mac skips require the native WeasyPrint stack. DOCX rendering tests ran; this receipt does not claim that the native PDF tests passed on macOS. The built Linux image also rendered a 9,713-byte PDF through the public renderer as a smoke check; that is separate from the skipped Mac tests.

## Word and visual inspection

On 2026-09-08, Microsoft Word for Mac opened the neutral generic output and filled `rapport.docx`, plus the neutral report and meeting templates. Tools → Check Accessibility reported **“Looks good! No issues found.”** for each document. Each of the six visible categories showed zero issues: contrast, alt text, table headers, merged/split cells, headings and restricted access.

- [Generic rendered document and checker](docx-content-controls-2026-09-08/word-generic-accessibility.png): pre-title text retained; styles, marked table header, nested and separate numbering restarts, hyperlink and emphasis inspected.
- [Filled report and checker](docx-content-controls-2026-09-08/word-rapport-accessibility.png): all seven controls filled; fixed headings retained; section heading demoted; table, lists and link inspected.
- [Neutral report template](docx-content-controls-2026-09-08/word-rapport-template-accessibility.png).
- [Neutral meeting template](docx-content-controls-2026-09-08/word-meeting-template-accessibility.png).

LibreOffice page renders of all three templates and both filled samples were also inspected: one page each, no visible clipping or overlap. The placeholder-only generic template intentionally contains no content heading until it is filled. Word's checker result is evidence for these specific samples, not a blanket accessibility certification.

The checked generated samples are identified by [SHA-256 hashes](docx-content-controls-2026-09-08/word-sample-hashes.json). Local delivery copies are in `/Users/ccimen/eneo/eneo-docx-templates/verified-2026-09-08/`; the owner's original files remain intact.

## Landing and live verification

Full `tests/integration/flows`: **448 passed, 1 failed**, 1,374.53 s. `test_ai_builder_turn_retry_survives_hard_process_failures` exceeded its 20-second child-process deadline. The isolated test passed on unchanged tidy in 64.85 s. The isolated candidate recheck also passed, in 60.21 s, without changing recovery code or the deadline. The broad run observed one process-deadline timeout; the isolated rerun is the final result for that test. Claude Opus xhigh cleared commit `2c23f4a2545dd79f39ddca1025c86d3b242da836` with no blockers (green, minimum score 8). The same session verified two bounded corrections; review sidecars remain outside the repository. The feature and tidy branches were fast-forward pushed to that commit, with no force push.


The local `:8144` lane was rebuilt from that committed backend archive with the repository Dockerfile and frozen dependencies. All four containers (API, worker, execution and maintenance) run the same image, `eneo-docx-review:2c23f4a2545d`, with the matching source-revision label. The old source and virtualenv mounts were removed; only the existing read-only environment directory and a capture directory remain mounted. The original containers are stopped and retained for rollback; shared database/Redis data and the `:8146` lane were preserved. There were zero active flows and zero leased Builder requests before replacement.

The final image passed DOCX and native PDF rendering, taxonomy validation and empty-template rejection. The public health endpoint returned HTTP 200 with backend and worker `HEALTHY`; its object-content substatus remains `NOT_CONFIGURED`. See the [lane receipt](docx-content-controls-2026-09-08/lane-repoint.json) for the exact image identity, container states and health response. This establishes the rebuilt lane's process health, not a successful provider-backed Flow run.

The live Builder and Word checks below are complete. Browser automation of the local editor remains blocked by administrator policy; the owner verified the UI directly. The ten confirmed baseline unit failures remain tracked in `eneo-wqq`.


### Local startup and schema correction

The first backend health check did not establish application readiness. Frontend `:3133` had been stopped for the required static check and was restarted. Its server, browser and server-override backend URLs all point to `:8144`; local ignored environment settings preserve this configuration for restart. The documented development account authenticated successfully. The owner then encountered HTTP 500 while loading the personal space, with trace `6550181a0fe8a2ac8ed8eec7ed3ae748`: the new backend expected `space_capabilities`, which was absent.

The database recorded `202609041000` for the old Flow evidence-classification migration. Tidy merge `60436fd4d` renamed that exact migration to `202609041001` to resolve a collision with the independent-capabilities migration. The schema contained the Flow classification column but neither the capabilities table nor `mcp_servers.purpose`, confirming the old identity. After a 92 MB private backup, the correction was rehearsed on a restored database copy: assert that schema, stamp the renamed Flow revision, and run the repository's canonical migrations to `202609081000`. The same correction then passed on `eneo_ai_builder_simplify`. Counts remained 1 user, 45 spaces, 176 flows, 46 runs and 897 files before the new live probes. No legacy search rows needed conversion. Authenticated current-user, personal-space, organization-space and space-list requests all returned HTTP 200; the owner confirmed that localhost worked.

Recovery now requires the pre-upgrade database backup as well as the retained old containers. Switching only the old image back is insufficient after the schema upgrade. The backup and clone are retained locally and are not committed; the `:8146` database was not changed.

### Real document and template runs

The [live verification record](docx-content-controls-2026-09-08/live-verification.json) preserves identities, artifact checksums, readiness and runtime provider evidence.

- **Verbatim DOCX:** flow `7f3d9665-2d89-46c5-8ab7-8776ba4cbf05`, run `2e13ee99-2bc6-47c0-a2d5-83d5c481db1d`, version 1 completed and produced a 38,128-byte DOCX. The signed download matched the recorded SHA-256. The owner's browser download matched those bytes too. [Layout screenshot](docx-content-controls-2026-09-08/live-word-owner-layout.png) and [editing screenshot](docx-content-controls-2026-09-08/live-word-owner-edit.png) show the preserved pre-title line, emphasis, Swedish characters, table and numbering restarts. The owner confirmed that the document can be edited. [Input](docx-content-controls-2026-09-08/live-verbatim-input.md).
- **Builder with rapport:** session `248ead76-5d4a-4950-a714-4a24a5372272` inspected all seven named controls. After its three discovery questions, the confirmed requirements selected the attached DOCX as a fixed output template. The configured Gemma default returned invalid `output_fields` strings and repeated that shape during automatic repair. An explicit Luna/high attempt against the same confirmed requirements produced the [valid plan](docx-content-controls-2026-09-08/live-builder-plan.json), including the template's guidance for summary paragraphs, analysis tables and numbered recommendations. All seven fields were typed as strings and bound to scalar sources. Materialization and publish passed; the run contract reported `template_readiness=ready` for the pinned asset.
- **Filled template:** the resulting flow `57dd7ace-b44c-4f66-8a64-42db063ac50b` ran unchanged with its Gemma runtime assistant. Run `1d186c2c-b012-4d28-8f2c-727cc199af52`, version 1 completed with one successful completion call, followed by deterministic template filling. The 38,498-byte downloaded DOCX matched its checksum. All seven controls were populated and the date was `2026-09-08`. Both rendered pages were inspected: [page 1](docx-content-controls-2026-09-08/live-template-page-1.png), [page 2](docx-content-controls-2026-09-08/live-template-page-2.png). Fixed headings, relative subheadings, a headered table and the recommendations list are intact. [Synthetic input](docx-content-controls-2026-09-08/live-template-run-input.txt) and [filled control text](docx-content-controls-2026-09-08/live-template-output-controls.json).

Local delivery copies are `live_verbatim_flow.docx` and `live_rapport_flow.docx` in the verified template directory. These probes establish the named cases, not a broad model-quality or accessibility guarantee. The one Gemma authoring failure and its repair are tracked in `eneo-3te`; baseline provenance and failure rate are not established. Gemma succeeded as the runtime content writer in the filled-template run. No malformed tool output was accepted and no planner, topology or compose-text code was changed during live verification.
