# Eneo tool runtime

Eneo's bundled, isolated MCP provider. It is a small Bun service. Operator
documentation lives in `docs/deployment/TOOL_RUNTIME.md`.

- `POST /mcp/compute` is a stateless Streamable HTTP MCP endpoint (JSON
  responses) exposing `run_javascript`.
- `POST /mcp/file-analysis` exposes `inspect_table`, `query_table` and
  `assert_table` over signed Eneo attachment URLs. It fetches only from the
  origin Eneo sends in `X-Eneo-File-Origin`. `query_table` brings a table view
  (an MCP App, `src/tools/tabular/view/`) that hosts showing tool views render
  with its result. Set `display: "none"` for intermediate queries used by charts
  or other tools; the default `display: "table"` preserves in-chat browsing.
- `POST /mcp/charts` (`create_chart`) provides the **Charts** function: interactive
  MCP App charts from inline series or CSV/XLSX sources. Explicit PNG/SVG
  requests and hosts without app views use MCP image blocks. The view and the
  image are drawn by ECharts from one description (`src/tools/charts/options.ts`),
  so an exported picture matches the chart the reader looked at. The image is
  rendered to SVG without a browser and rasterized by resvg in a sandbox child.
- Documents accept signed PNG/JPEG references through `create_document.images`, in
  every format. Place each as `![alt](image:ID)` on its own line, with an optional
  caption and `width_percent`. Word and PDF embed the bytes; a Markdown document keeps
  a line naming the file by its handle (`![alt](eneo-file:… "caption")`), which Eneo
  shows and embeds on export. Chart exports prepared only for documents use
  `display: "none"`.
- `POST /mcp/file-creation` (`create_document`, Markdown, DOCX or PDF from Markdown;
  `edit_document`, exact passages of an earlier Markdown document replaced in place;
  `fill_template`, a DOCX, TXT or MD template filled, or inspected with
  `inspect: true`; `create_spreadsheet`, XLSX) returns the file as an embedded
  resource that Eneo saves in the conversation.
- Every Word file is rendered into a template: the one passed as
  `create_document.template` (a signed `.docx` reference, normally supplied by Eneo
  from the organisation's template library), else Eneo's built-in template, which
  `GET /templates/builtin.docx?language=sv|en` serves for administrators to adapt.
  Content is written in the template's own styles, resolved by style name (a Swedish
  template's `Rubrik1` is "heading 1"), and lists use the template's list styles when
  it has them. A template marks where the document goes with a rich content control
  tagged `content` (or `dokument`), else a paragraph reading `{{content}}`; otherwise
  its body is replaced. Other fields are content controls (tag, alias and placeholder
  text as Word's Developer tab makes them; a text control takes one value, a rich
  control a document in Markdown) or `{{name}}` placeholders. Title, date, year and
  organisation are filled from the call; `fields` and `fill_template.values` cover
  the rest, and an empty value removes a control. `src/tools/documents/engine/word/`
  holds the inspection, numbering and control handling around the docx patcher.
- A PDF follows the same template. The document is rendered into the Word template
  first; its page size and margins, body and heading faces, header, footer (with page
  numbers) and logo are read from that file (`engine/pdf-profile.ts`) and become the
  stylesheet of a semantic HTML rendering (`engine/html.ts`) that WeasyPrint lays out
  as a tagged PDF/UA-1 document. WeasyPrint runs in a Python venv the image installs
  at `/opt/pdf` (`scripts/render_pdf.py`, pinned with hashes in
  `scripts/requirements-pdf.txt`); `PDF_PYTHON` points a developer machine at another
  interpreter, and PDF tests skip when none is found. The image ships DejaVu,
  Liberation, Carlito and Caladea, so Calibri and Cambria templates lay out as in Word;
  other fonts fall back to the nearest of these. Text headers and footers and one logo
  are reproduced; table-based or multi-column headers are not.
- `GET /health/live` and `GET /health/ready` are the health endpoints.

## Layout

| Path                         | Purpose                                                  |
| ---------------------- | -------------------------------------------------------- |
| `src/main.ts`                | Entrypoint: environment config, HTTP server              |
| `src/server.ts`              | Bearer check, Origin refusal, body/result bounds, MCP    |
| `src/sandbox.ts`             | One child process per job (only `PATH` and `TMPDIR` in its env, watchdog, tmpdir) |
| `src/child.ts`               | Child entrypoint                                         |
| `src/tools/compute/`         | QuickJS engine, limits and the tool definition           |
| `src/tools/tabular/`         | Download policy, parsed-sheet cache, DuckDB/XLSX engines |
| `src/tools/documents/`       | Markdown parser, DOCX/PDF/XLSX renderers, Word templates |
| `scripts/render_pdf.py`      | The WeasyPrint sidecar the PDF renderer spawns            |
| `src/tools/charts/`    | Chart spec, ECharts app and SVG/resvg image export       |
| `src/tools/files/`           | Signed Eneo file references shared by all file inputs    |

The compute engine was ported from eneo-tools (`packages/compute`, commit
`585b271`). The tabular engines were ported from `packages/tabular` and
`packages/files` at the same commit, with workspaces, handles and the database
replaced by per-call signed URLs and a disposable cache. The renderers come
from `packages/document-export`, returning embedded resources instead of
download links. New tools belong here only when they need platform-owned
isolation. Domain integrations stay separate MCP services.

## Development

Run these inside the devcontainer:

```bash
cd /workspace/tool-runtime
bun install
bun run test
bun run typecheck
```

## Tool views

A tool view is an MCP App: one HTML page the host shows with a tool's call, in a
sandboxed frame with no network. The views are React apps built on
[Astryx](https://github.com/facebook/astryx) components with its Neutral theme
as shipped, and they share one kit in `src/views/kit/`:

- `ViewFrame` is the frame every view is drawn in: a header toolbar with the
  title, the view's controls and the larger-view button, notices under it, the
  content, and a footer. It follows the host's theme, language and display mode
  and reports its height. On a text selection it offers **Quote in chat**, which
  hands the text to the host (`ui/update-model-context`) for the next question.
  While a selection is dragged in scrolling rows, the frame scrolls them itself
  (`useSteadySelection`): Chrome's own scrolling there makes the host's page
  jump to the top of the view.
- `useHost` is the connection to the host (the official `App` SDK): the host's
  context, and the tool's input and result as they arrive.
- `TableRows` and `columnWidth` give an Astryx `Table` scrolling rows under
  headings that stay in place.

A view lives next to its tool (`src/tools/<tool>/view/`: `index.html`,
`main.tsx`, and `index.ts`, which loads the built page). To add one, write
those files and add the view to `VIEWS` in `scripts/build-views.ts`.

`bun run build:views` builds every view with Vite into one self-contained page
under `dist/views/` (ignored by git). `bun run dev` and `bun run test` build
them first, and the image builds them in its own stage, so React, Astryx and
Vite are development dependencies only. A page larger than the 2 MB a host
reads fails the build.

The runtime reads the built pages when it starts. Eneo stores its own copy of
each view and replaces it by itself when the runtime's catalog changes; the
backend caches that catalog for up to five minutes. To see a changed view in
Eneo: run `bun run build:views`, restart the runtime, wait for the cache to
lapse (or refresh the server's tools under **Admin > Tools > MCP servers** to
pick it up at once), and make a new tool call (earlier messages keep the view
they were made with).

In the devcontainer, run it in its own terminal next to the backend and
frontend:

```bash
cd /workspace/tool-runtime
bun run dev
```

The devcontainer sets `TOOL_RUNTIME_URL=http://localhost:3010` and a shared dev
`TOOL_RUNTIME_TOKEN` for both processes, so **Admin > Tools > MCP servers**
offers the servers built into Eneo right away. Tabular analysis fetches from whatever the backend's
`FILE_REFERENCE_BASE_URL` (or `PUBLIC_ORIGIN`) points at, so that address must
be reachable from inside the devcontainer. In development the runtime shares the
devcontainer's network. The standard production deployment puts it on an internal
network without egress.

Sandbox children are confined with [landrun](https://github.com/zouuup/landrun)
(Linux Landlock) when it is installed. The image builds it in; for local runs
and the confinement tests, build it once from the host, where Docker is
available:

```bash
cd tool-runtime
bun run build:landrun   # writes bin/landrun (ignored by git)
```

Without it children run unconfined and the confinement tests are skipped. The
start-up log line reports what is enforced (`"confinement":{"files":true,"tcp":true}`).

## Configuration

| Variable              | Default | Notes                                  |
| ---------------------------------- | ------- | -------------------------------------------------------- |
| `TOOL_RUNTIME_TOKEN`  | none    | Required, at least 32 characters        |
| `PORT`                | 3010    |                                        |
| `MAX_CONCURRENCY`                  | 16      | Active tool calls                                        |
| `MAX_QUEUE`                        | 32      | Waiting tool calls                                       |
| `MAX_QUEUE_PER_GROUP`              | 8       | Waiting calls per caller group                           |
| `COMPUTE_TIMEOUT_MS`  | 5000    | Script deadline (100 to 30000)         |
| `COMPUTE_MEMORY_MB`   | 64      | Script memory limit (8 to 256)         |
| `TOOL_RUNTIME_FILE_ORIGINS` | none | Optional comma-separated limit on Eneo's file origin |
| `TABULAR_CONCURRENCY` | 2       | DuckDB children running at once        |
| `TABULAR_MAX_UPLOAD_MB` | 20    | Largest attachment downloaded          |
| `TABULAR_CACHE_MB`                 | 256     | Original-byte and parsed-sheet cache budget on `/tmp`    |
| `TABULAR_CACHE_TTL_SECONDS` | 1800 | How long unused original bytes and parsed sheets stay on `/tmp` (60 to 86400) |
| `TOOL_RUNTIME_REQUIRE_CONFINEMENT` | false | Refuse to start or run jobs unless children are confined |
| `DOCUMENT_ORGANISATION_NAME` | none | Name in generated document footers |
| `DOCUMENT_MAX_CONTENT_CHARS` | 50000 | Markdown characters a document may hold (5000 to 1000000); the request body cap follows |
| `DOCUMENT_PDF_CONCURRENCY` | 2 | PDF renders at a time (each a Python sidecar) |
| `PDF_PYTHON` | /opt/pdf/bin/python3 | The Python with WeasyPrint, for development outside the image |

Releases share the frontend/backend version and source revision. The image
publication workflow (`.github/workflows/build_and_push_images.yml`) calls the runtime validation/build workflow and publishes one
verified deployment bundle. There is no runtime-specific version bump.
See `docs/deployment/TOOL_RUNTIME.md` for diagnostics, cache revalidation,
queue limits, migration from the old overlay, and bundle-based upgrades.
