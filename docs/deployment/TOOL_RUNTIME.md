# Bundled tool runtime

The tool runtime is an isolated container included in the standard Eneo deployment. It serves
Eneo-maintained MCP tools from an isolated process, never from the backend.
It has four endpoints:

- `/mcp/compute`: `run_javascript`, restricted compute over JSON. It is added
  as an ordinary MCP server.
- `/mcp/file-analysis`: `inspect_table`, `query_table` and `assert_table` over
  attached CSV and XLSX files (more formats will follow). It is added as the
  provider of the **Ask a file** capability (`file_analysis`, "Fråga fil" in
  Swedish).
- `/mcp/file-creation`: `create_document`, which writes a Markdown document
  shown beside the conversation (the default, for plans, summaries and drafts)
  or renders Word (DOCX) or PDF from Markdown, optionally into a Word template
  from the conversation,
  `edit_document`, which changes named passages of a Markdown document it
  wrote earlier and leaves the rest as it was,
  `fill_template`, which fills the `{{placeholders}}` of a Word, text or
  Markdown template, and `create_spreadsheet`, which builds XLSX workbooks with
  named sheets and typed cells. It provides **Create a file**
  (`file_creation`).
- `/mcp/charts`: `create_chart`, which draws bar, line, pie and scatter charts
  interactively through an MCP App, with PNG output on request or when app
  views are unavailable. It provides **Charts** (`charts`, "Diagram" in Swedish).

## Chaining tools without copying data

Large data moves between tools as Eneo files, never through the model:

1. `query_table` with `export: true` writes its complete result (up to 200,000
   rows) as a CSV file. Eneo saves it as a visible download and hands the model
   a stable, credential-free `file_ref` for it in the same answer.
2. The model passes that handle in the URL field of a sheet `source` or chart
   `source`. Eneo resolves it to the current authorized signed URL immediately
   before dispatch. `create_spreadsheet` uses it as a sheet `source`, and `create_chart`
   takes it as its `source` with a label column and value columns. Each
   downloads the file with the same checks as the tabular tools: Eneo's origin
   only, and access checked on every download.

The providers share nothing but those Eneo-owned files and links, so any of
them can be replaced by an external provider that follows the same MCP
conventions. The runtime and external providers still receive normal signed URLs;
they do not need to implement Eneo's model-facing handles. Handles are identifiers,
not permissions, and are resolved only against the current conversation's allowed
files. The same-turn reference needs a streaming chat; over the
non-streaming API, the reference arrives on the next turn. Charts normally
use an interactive view in Eneo.

## Exporting a document

A Markdown document opens in the panel beside the conversation, whose Export
menu offers it as Markdown, Word or PDF. For Word and PDF Eneo calls
`create_document` on the provider of the assistant's **Create a file**
capability with the document's own text, checks the returned file like any
generated document, and hands it to the user as a download. Nothing is stored
in the conversation, and the export is written to the audit log. An assistant
without the capability can still download the Markdown; an external provider
serves native export only if its accessible, approved `create_document` tool
accepts Eneo's request: string `title`, `content`, `filename` and `format`,
with supported formats declared in `format.enum`. Word and PDF availability
are checked separately against that schema and the selected document.
Extra required inputs or unsupported schemas make native export unavailable;
the Function may still supply other file-creation tools. Compatibility is
checked again when exporting, and a compatible schema does not guarantee
that a remote provider will render successfully. The returned resource must
have the requested MIME type and pass Eneo's generated-file validation.

## Provider view resources

The runtime ships self-contained MCP Apps table and chart resources for
compatible hosts. Eneo's runtime integration displays tool results as text,
images and downloadable files. Charts fall back to PNG when the caller does
not advertise app-view support.

### Enabling the Charts function after upgrading

Apply migration `202610011200`, then add **Built into Eneo** under
**Admin → Tools → Functions → Charts** and activate it. Enable **Charts** on the
space and assistant, and grant its role permission. Existing roles receive no
automatic permission grant; new predefined roles include it. The migration
only widens the capability constraints and preserves all existing settings.
Existing bundled general chart servers keep their current attachments and
can coexist with the new provider. Retire those general servers through the
admin UI after configuring the function to avoid offering the same tool twice.
Their old general-tool access rules continue to apply until then.

## TL;DR

- Included by default. Capabilities remain opt-in; ordinary Eneo runs without it.
- It has no database, no console, no operator mutation API and no registration sync.
  Eneo registers it through **Admin > Tools** like any other MCP server.
- The only credential is a shared bearer (`TOOL_RUNTIME_TOKEN`). Eneo reads it
  from its settings at connect time, so it is never stored in the database.
- Tools go through the normal review, per-tool enablement, space enablement and
  per-call approval. Adding the bundled server grants nobody anything.

## Isolation: what keeps one conversation's data from another

The runtime is one container shared by every tenant and conversation, so the
separation between jobs is what matters for sensitive files. It rests on these
layers:

1. **Eneo decides which files a tool call may name.** A tool call can only
   carry signed links to the files of its own conversation (its attachments
   and the files its tools created). Eneo refuses any other file link in the
   arguments before the runtime is contacted, so a link from another
   conversation is never fetched, whoever put it there.
2. **The runtime holds no credentials and no data of its own.** It has no
   database and no signing key, and with the standard deployment no route to Postgres,
   Redis or the internet. It can only redeem the links Eneo handed it.
3. **Each job runs in its own process, confined before it starts.** The
   launcher ([landrun](https://github.com/zouuup/landrun), Linux Landlock)
   restricts the child to its private directory and the files that one job
   was given. It cannot open another job's files, the parsed-sheet cache
   entries of other users, or the server process's environment, and it has no
   TCP at all. This holds even if a crafted file or query takes over one of the
   engines (DuckDB, the renderers, the JavaScript engine).
4. **The container limits what an escape could reach.** Read-only root
   filesystem, no capabilities, no privilege escalation and an internal
   network (see the standard Compose stack).

Layer 3 needs a host kernel with Landlock: Linux 5.13 or later for files, 6.7
or later for the TCP restriction. Docker's default seccomp profile allows it.
The start-up log line states what is enforced:

```json
{"event":"listening", "confinement":{"files":true,"tcp":true}}
```

On a host that cannot confine jobs the runtime still works, with layers 1, 2
and 4 only. Where sensitive or classified files are handled, set
`TOOL_RUNTIME_REQUIRE_CONFINEMENT=true` in `.env`: the runtime then refuses to
start, and to run any job, unless files are confined.

What this does not cover:

- A kernel exploit from inside a confined job. A sandboxed runtime such as
  gVisor (`runtime: runsc` on the service) adds that layer where the host
  offers it. It protects the host, not one conversation from another, so it
  complements the confinement above and does not replace it.
- Original bytes and parsed sheets stay in `/tmp` (memory-backed) for follow-up questions, 30
  minutes by default. With confinement, only the server process and the jobs
  that query that same file can read them.
  `TOOL_RUNTIME_TABULAR_CACHE_TTL_SECONDS` shortens that, down to 60 seconds,
  and expired entries are removed on a timer.
- Deployments that do not use the standard Compose stack (another orchestrator, the
  development container) must provide layer 4 themselves: no egress, a
  read-only root filesystem and no capabilities.

Setting a security classification on the built-in server in **Admin > Tools**
is the administrator's statement that this deployment may handle files of that
level. Check the start-up line and the points above before raising it.

## What the compute tool can and cannot do

`run_javascript` runs model-written JavaScript over bounded JSON input and
returns bounded JSON output.

- Each call runs in a fresh QuickJS (WebAssembly) runtime. It sees only `input`
  and `console`, with no network, filesystem, timers, imports, host APIs or
  environment, and keeps no state between calls.
- Each call runs in a separate child process that inherits nothing but `PATH`
  and a private temporary directory. The bearer token never reaches it.
- Limits: 20,000 characters of code, 64 KiB input, 256 KiB result, 100 log
  lines, 64 MB memory and a 5 s script deadline. An external watchdog kills
  the child at the whole-job deadline.
- The container runs on an `internal` network that only the backend and worker
  join. It has no route out even if guest code escaped both the engine and
  the child.

## What the file analysis tools can and cannot do

The model passes the attachment's stable `file_ref` in the tool's URL input.
Eneo resolves it against the request's authorized files and sends the signed URL
to the runtime. The runtime then works as follows:

1. It accepts only URLs of the form
   `<origin>/api/v1/files/<id>/original/download/?token=…`. The origin must be
   the one Eneo sends with the call (`X-Eneo-File-Origin`, taken from
   `FILE_REFERENCE_BASE_URL`), never one chosen by the model. Any other URL is
   refused before a request is made. `TOOL_RUNTIME_FILE_ORIGINS` optionally
   pins the allowed origins on the runtime side as well.
2. It revalidates the current signed link on every call. Eneo checks the token,
   tenant, file and content accessibility before returning bytes or HTTP 304
   for unchanged content. Invalid links never use the cache. Downloads remain
   capped at 20 MiB and 15 s, with pinned addresses and checked redirects.
   Older servers without validators return the full file.
3. It parses the file in a sandbox child. CSV must be UTF-8. XLSX goes through
   a zip-bomb guard and is converted to one CSV per sheet. At most 20 sheets
   and 64 MiB expanded.
4. It caches the parsed sheets on local disk for 30 minutes
   (`TOOL_RUNTIME_TABULAR_CACHE_TTL_SECONDS`), keyed by tenant, user and the
   downloaded bytes' hash. The cache never replaces the access check in step 2, so
   it can never grant access. A miss simply parses again, and expired entries
   are removed on a timer.
5. It runs the model's SQL in a separate sandbox child with a fresh DuckDB.
   Before any model SQL is prepared, DuckDB's external access, extensions and
   configuration are locked. Only a single `SELECT` is accepted, as determined
   by DuckDB's own parser. Queries are limited to 500 rows, 10 s, 256 MB and
   1 thread.

Bundled calls forward opaque user and tenant IDs for caching and scheduling.
External providers retain their identity opt-in.
At most `TOOL_RUNTIME_TABULAR_CONCURRENCY` (default 2) DuckDB children run at
once; other calls wait. Formulas are read as their cached values. Writing
spreadsheets is not part of this endpoint.

## Templates

A template is a file the user attached in the chat or an administrator
attached to the assistant, named by its signed reference. The runtime downloads
it under the same policy as other attachments, and Eneo checks the result like
any other generated document. There are two ways to use one:

- **A layout to write into.** `create_document` takes an optional `template`,
  a `.docx`, and renders the content into it: the template keeps its styles,
  headers, footers, numbering and page setup. A paragraph in the template
  reading `{{content}}` marks where the content goes; without one the
  template's body is replaced. Other placeholders in the template (for example
  `{{diarienummer}}` in the header) are filled from the optional `fields`.
- **A form to fill in.** `fill_template` takes a `.docx`, `.txt` or `.md` with
  placeholders such as `{{namn}}` and a value for each. The result is the same
  file with the values in place, in the template's own format. In a Word file
  the placeholders are found in the body, headers and footers, and a value
  takes the formatting of the text its placeholder had.

Values are plain text. Every placeholder needs a value (an empty one leaves it
blank); a call that misses one fails and lists the template's placeholders, so
the assistant can ask the user for what it does not know. Macro-enabled Word
files are refused.

Only the `{{name}}` notation is read. Word's own fields (content controls and
mail-merge fields) are left as they are, repeating rows and conditions are not
supported, and a PDF cannot be used as a template: text in a finished PDF
cannot be replaced reliably, so the Word original is needed.

## Upgrading the runtime

The runtime's tools are Eneo's own code, so they are trusted like a built-in
provider's. A completion lists the running runtime's catalog (cached per
backend process for five minutes) and keeps only the administrator's per-tool
decisions (enabled, display name) from the stored rows, so a new runtime image
is in use as soon as it runs; nobody has to press **Sync tools**. Pressing it
still refreshes the stored rows the admin pages show, and the changes are
approved without review.

## Revising a created file

`create_document` and `create_spreadsheet` take an optional `revises`: the
signed reference of a file the tool created earlier in the conversation. The
model passes the complete revised content; the new file replaces the earlier
one, reuses its filename, and a Word file keeps its layout and the template it
was made from (the earlier file serves as the template). The result names the
file it replaces so the answer can say so. Eneo keeps both files, like an image
and its edited variation.

## Created documents and spreadsheets

The renderers run in a sandbox child and return the file inside the tool result
as a standard MCP embedded resource. The runtime keeps no copy and serves no
download links. Eneo then does the following:

1. It admits the file only because the server provides `file_creation`
   (DOCX, PDF, XLSX, plain text and Markdown). The
   same resource from any other server stays an ordinary result.
2. It checks the bytes: OOXML packages must be well-formed, bounded and free of
   macros, embedded objects and externally loaded content. PDFs must be
   complete and free of script, launch actions and embedded files. Text must
   be UTF-8.
3. It saves the document as a File in the conversation, with extracted text and
   its exact original. The user opens it in the native preview or downloads it. It
   survives reloads, follows the conversation's access rules and is deleted with
   the conversation.

Spreadsheets store text as text: a value starting with `=` is never written as a
formula. A workbook revision creates a new workbook from supplied tables or
source sheets; it does not preserve an arbitrary workbook's formulas, formatting
or embedded objects. Formula writing and spreadsheet templates are unsupported.
`DOCUMENT_ORGANISATION_NAME` sets the name shown in document footers.

## Deploy, upgrade and roll back

Frontend, backend and runtime share one Eneo version and source revision.
The application image workflow publishes a complete bundle only after component
checks and a combined smoke test pass. There is no separate runtime version.

Download `release.env` and `release.json` from the selected GitHub release,
or the completed workflow artifact for a development build. The JSON manifest
records the version, revision and three immutable image digests. Take deployment
templates from that recorded source revision as well. The environment
file supplies those references to Compose, including the backend image used by
workers and initialization jobs. After configuring the usual environment files:

```bash
python3 setup.py
docker compose --env-file .env --env-file release.env up -d
```

The setup helper creates a strong runtime token only when absent, protects
`.env` with mode 0600, and preserves existing settings without printing secrets.
Without a bundle, `python3 setup.py --version X.Y.Z` selects one explicit shared
version. Digest-pinned bundles are preferred.

The standard stack starts the runtime and connects the backend and general
worker. File references default to `http://backend:8000`. Override
`FILE_REFERENCE_BASE_URL` in Compose's `.env` when needed;
`TOOL_RUNTIME_FILE_ORIGINS` follows it unless explicitly overridden.
The setup helper carries existing runtime URL, token, and file-origin overrides
from `env_backend.env` into `.env` when absent there. Thereafter, these Compose
values take precedence; keep overrides in `.env`.

For existing installations, remove the old runtime image pin from `.env`,
adopt the complete bundle, and remove the extra runtime overlay/profile.
`docker-compose.tool-runtime.yml` remains an empty compatibility shim for one
release. Registrations, external providers, permissions and activation decisions
are preserved. Installing the service does not enable capabilities.

In **Admin > Tools > Functions**, turn on **Ask a file**, **Create a file** or
**Charts**, then grant the desired space and assistant access. **Compute**
remains under **MCP servers**. Existing roles still need the permissions
described above; active external providers are not replaced automatically.

To omit the runtime explicitly:

```bash
docker compose --env-file .env --env-file release.env \
  -f docker-compose.yml -f docker-compose.without-tools.yml up -d
```

Stop an existing `tool-runtime` container first when adopting the opt-out.
Do not enable the `disabled-tool-runtime` profile. Backend startup/readiness
does not depend on runtime health.

Upgrade by replacing both bundle files together and recreating application
services. Roll back using the previous complete bundle, observing the release's
normal database rollback constraints. This change adds no database migration.
External deployment automation must consume the bundle; floating image tags
cannot change atomically.

## Diagnostics

**Admin > Tools** shows status even after providers have been registered:
missing configuration, unreachable service, rejected credentials, unknown or
mismatched versions, unavailable confinement and file-origin problems.
Version/revision mismatches warn while calls remain allowed. A reachable file
origin proves only TCP connectivity, not access to a particular file.

Backend probes have a three-second deadline and a 30-second local cache.
They never gate tool execution or ordinary chat. Private `GET /diagnostics`
requires the runtime bearer token; public health endpoints expose basic health.

## File reuse and scheduling

Original bytes and parsed sheets share a 256 MiB cache and a 30-minute idle
lifetime, configured through `TOOL_RUNTIME_TABULAR_CACHE_MB` and
`TOOL_RUNTIME_TABULAR_CACHE_TTL_SECONDS`. Every use revalidates the current
signed link with Eneo. Cache failures never authorize stale data. Entries are
scoped to user and tenant, pinned during jobs, and discarded on restart.
Legacy calls without caller identity bypass original-byte caching.

Defaults are 16 active calls and two native-engine jobs. Waiting caller groups
take turns, borrowing idle capacity. The group currently maps to a tenant;
there are no persistent quotas or distributed scheduling. Each replica schedules
locally. `TOOL_RUNTIME_MAX_QUEUE` permits 32 waiting calls and
`TOOL_RUNTIME_MAX_QUEUE_PER_GROUP` permits eight per group.

Full queues return a busy result. Queue time counts toward the call deadline.
Cancellation removes waiting jobs, aborts downloads and kills active child
process groups before cleanup. Health and discovery do not wait for job slots.

Structured events report request ID, tool, queue/execution time, cache
revalidation, transferred bytes and cancellation. They omit tokens, signed URLs,
file contents and model arguments.

## Rotate the token

Set a new `TOOL_RUNTIME_TOKEN` in `.env` and recreate `tool-runtime`,
`backend` and `worker`. Nothing in the database changes.

## Footprint

These figures were measured on the reference image (`0.1.0-eneo.1`, linux/arm64,
Docker Desktop):

| Condition                                      | Memory   |
| ---------------------------------------------- | -------- |
| Idle                                           | ~69 MiB  |
| 16 concurrent CPU-bound calls (default limit)  | ~580 MiB |
| After the burst                                | ~69 MiB  |

Each concurrent compute call costs about 32 MiB for its child process. A
tabular query child can use up to 256 MB for DuckDB. Such children, and the
document renderers, share `TOOL_RUNTIME_TABULAR_CONCURRENCY` slots, so only
that many run at once. The standard stack caps the
container at 2 GiB, 2 CPUs and 256 processes. `/tmp` is a 512 MiB tmpfs that
holds job scratch space and the 256 MiB parsed-sheet cache, and it counts
towards memory. If you raise either concurrency setting, raise `mem_limit` with
it. Calls wait within the queue limits. Full queues return a busy tool result;
excess HTTP intake gets HTTP 429.

## Failure behaviour

If the runtime is stopped or unreachable, the tool call fails and the assistant
answers without it. Chat is otherwise unaffected. Script errors, timeouts and
oversized results come back to the model as `ok: false` results, so it can
correct its code.
