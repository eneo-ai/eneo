# Interactive tool views (MCP Apps)

An MCP server can attach an interactive view to a tool: a small HTML
application that shows the tool's result as something better than text (a
chart, a form, a map). Eneo implements the host side of the MCP Apps extension
(`io.modelcontextprotocol/ui`) using the official `@modelcontextprotocol/ext-apps`
`AppBridge` and `App` APIs. The SDK handles protocol negotiation and RPC. A view is shown
under the answer that used the tool and can move beside the conversation when
it needs more room.

## TL;DR

- Off by default. Eneo behaves exactly as before until it is switched on.
- It needs two settings and one extra hostname that reaches the backend.
- A view is HTML from an MCP server. An administrator approves it together
  with the tool that brings it, and only the approved copy is ever shown.
- A view runs in a sandboxed frame on a separate origin, with no network
  access unless its server declared the hosts it calls.

For the complete responsibility map and design rationale, see
[Skills, Functions, tools and views](../../frontend/apps/docs-site/src/content/docs/architecture.mdx#skills-functions-tools-and-views).
MCP Apps here means interactive tool views, distinct from Eneo Apps configured
in Spaces.

## Relationship to native documents and file previews

MCP Apps provide tool-specific interaction. Eneo's native document workspace
handles Markdown drafts, assistant-driven revisions, version history and
exports, while native file previews display existing attachments and generated
files. The built-in query-result table and interactive chart are apps. Charts
can also return PNG images on request or when app views are unavailable.

These views share one panel beside the conversation. Opening a file returns an
expanded app inline; expanding an app covers the open file, which is shown
again when the app returns inline. The app keeps
the same frame and live state during these layout changes. Document versions
are saved files, whereas app filters and loaded pages are browser state and
are not guaranteed to survive a reload.

The native workspace and previews do not depend on `MCP_APPS_ENABLED` or the
separate app content origin. The document workspace currently supports editing
through requests to the assistant, rather than direct rich-text typing. The
[Functions guide](https://docs.eneo.ai/dev/guides/capabilities#tools-files-and-views)
describes the full workflow, supported previews, revisions and exports.

## Switching it on

1. Give the backend a second hostname, the content origin. Only the path that
   serves views needs to be reachable on it:

   ```yaml
   # labels on the backend service in docker-compose.yml
   - "traefik.http.routers.eneo-mcp-apps.rule=Host(`views.your-domain.com`) && PathRegexp(`^/api/v1/mcp-apps/views/[^/]+/content$`)"
   - "traefik.http.routers.eneo-mcp-apps.entrypoints=websecure"
   - "traefik.http.routers.eneo-mcp-apps.tls=true"
   - "traefik.http.routers.eneo-mcp-apps.tls.certresolver=letsencrypt"
   - "traefik.http.routers.eneo-mcp-apps.service=eneo-backend-svc"
   ```

2. Set these for the backend and the worker:

   ```
   MCP_APPS_ENABLED=true
   MCP_APP_CONTENT_BASE_URL=https://views.your-domain.com
   ```

   Set `PUBLIC_ORIGIN` to the address users open Eneo on as well. A view can
   then be framed by that address only.

3. Sync the MCP servers whose tools have views (**Admin > Tools**, refresh),
   and approve the pending tools. Switching the setting on changes what Eneo
   tells servers it can do, so a server may offer tools it kept back before.

For local development the content origin can be the backend under another
host name: open the app on `http://localhost:3000` and set
`MCP_APP_CONTENT_BASE_URL=http://127.0.0.1:8123`.

Optional settings:

| Setting | Default | Meaning |
|---|---|---|
| `MCP_APP_RESOURCE_MAX_BYTES` | 2 MiB | Largest view HTML Eneo keeps. |
| `MCP_APP_VIEW_TOKEN_EXPIRY_SECONDS` | 3600 | Lifetime of the link a view is loaded from. One hour at most. |

## What an administrator approves

A tool's view is part of the tool's definition. When a server is synced, Eneo
reads each view its tools declare, stores it, and proposes it with the tool:

- A tool with a new or changed view waits for approval like a tool with a
  changed description. The tool list says "New interactive view" or "Changed
  interactive view" on it.
- What is approved is the view's HTML together with its policy (the hosts it
  may reach and the permissions it asks for). If either changes on the server,
  the next sync proposes the change, and users keep seeing the approved copy
  until it is approved.
- The HTML is not fetched from the MCP server when a view is shown. External
  scripts and styles permitted by `resourceDomains` may still be fetched by
  the browser and can change independently of the approved HTML. Prefer
  self-contained views; approving an external resource origin trusts the code
  it serves as well.
- An earlier conversation shows each tool call with the view approved for its
  tool now, not the one approved when the call was made. A new release of a
  server's view therefore does not break old conversations, and a view that is
  no longer approved is never shown again.
- Approving a catalog change that removes the view metadata also removes its
  approved view pin. Old conversation views then become unavailable.

A server can keep a tool for its view only. Such a tool is never offered to
the model.

### Servers built into Eneo

The bundled tool runtime's views are Eneo's own code, like its tools, so
nobody reviews them. When the runtime's catalog differs from what Eneo has
stored (after an upgrade, or the first time a tool is used), Eneo stores the
new definitions and views itself and they are in force at once. No sync and no
approval are needed, and the tool list shows the current tools the next time
it is opened. Each such update is written to the audit log as a change made by
the system, with the views it put in force.

The file reader (**Ask a file**) brings such a view: the rows a query returned
are shown as a table under the answer, which the user can sort, filter, copy
and read on from. The model is told the table is shown, so it describes the
result instead of writing the rows out a second time.

The **Charts** function brings a self-contained ECharts view with hover values,
series or slice selection, x-axis zoom, an accessible data table and expansion.
It uses the official `App` API and requests no network or browser permissions.
Only validated chart data reaches the renderer; tooltip labels never become
HTML. The tool resolves source files before sending values to the view.
Zoom and selection survive expansion and host context changes; a reload
starts from the saved result with the initial view state. See
[TOOL_RUNTIME.md](TOOL_RUNTIME.md#the-chart-view) for limits and image fallback.

## What a view can and cannot do

Eneo serves a trusted sandbox proxy from the separate content origin. The
approved HTML is returned as inert JSON to the authenticated frontend and sent
to that proxy through the official SDK. The proxy creates an inner `srcdoc`
frame with only `allow-scripts`: it has an opaque origin and cannot access the
proxy or Eneo. It inherits the proxy's HTTP Content-Security-Policy.

The parent policy uses `frame-src 'none'` to block the inner frame's navigation
before a request can send arguments or results to another page. Nested frames
(`frameDomains`) are unsupported. An app that attempts to navigate itself may
be replaced by a browser error page; links should use `ui/open-link` instead.

It cannot:

- read or change anything in Eneo, including the conversation, cookies and
  storage;
- reach another view, or keep anything in browser storage;
- reach the network, except the hosts its server declared and an
  administrator approved with the view;
- use the camera, microphone or location. Writing to the clipboard is the only
  permission granted.

It can, through Eneo:

- receive its tool call: the arguments while the model writes them, the
  finished arguments and the result;
- call tools on its own server, for the user. The assistant must still reach
  that server and the tool must be enabled, approved and visible to views.
  Its originating tool must also still be enabled and present, with this exact
  view URI and content hash approved. That is checked on every request, so an
  already-open view loses tool access when its approval is revoked.
  Calls are limited to 30 per minute per user and written to the audit log
  (without their arguments). External views ask for consent for each call,
  showing its tool name and arguments. Only Eneo's built-in views follow the
  user's automatic-tool preference;
- read the same file again in such a call. A view holds its call's arguments
  with every file link's signature removed. A link it passes on is signed
  again only for a file its own call was given and the conversation (or its
  assistant) still holds, and each such link is audited like any other;
- ask to open a web link. The user is shown the address and decides;
- offer the user a message. It is put in the message box and never sent by
  itself;
- ask to be shown beside the conversation. That is granted after the user has
  acted in the view, and once by itself for the answer being written. Expanding
  and returning inline preserve the same frame, filters and loaded rows;
- take no room. A view that reports a height of zero has nothing to show and
  leaves no frame under the answer.

A view's tool calls are not added to the conversation and the model does not
see them.

## For authors of MCP servers

Eneo supports this part of the extension:

| | |
|---|---|
| Declaring a view | `_meta.ui.resourceUri` on the tool (the flat `ui/resourceUri` key is read too); the resource is `text/html;profile=mcp-app` |
| Policy | `_meta.ui.csp` (`connectDomains`, `resourceDomains`, `baseUriDomains`; nested frames are blocked), `prefersBorder`, `permissions.clipboardWrite` |
| Visibility | `_meta.ui.visibility` with `model` and `app` |
| To the view | `ui/notifications/tool-input-partial`, `tool-input`, `tool-result`, `host-context-changed`, `ui/resource-teardown` |
| From the view | `ui/initialize`, `ping`, `tools/call`, `ui/open-link`, `ui/message` (text), `ui/update-model-context` (text), `ui/request-display-mode` (`inline`, `fullscreen`), `ui/notifications/size-changed` |
| Host context | theme, locale, time zone, platform, display mode, container size, colour and font variables |

A view's `ui/update-model-context` is what the reader's next question quotes:
Eneo shows its text above the message box, named after the view, where the
reader can remove it, and sends it once, at the head of that question. Each
update replaces the view's last one and an update without text withdraws it.
Text is taken only on the reader's action in the view and is cut at 1,500
characters; `structuredContent` and other content blocks are left out. The
conversation holds one quote at a time, so a later quote from another view or
a file replaces it.

Not supported yet: `ui/download-file`,
`resources/read` from the view, sampling, picture-in-picture, and file
references to files outside its originating call. A view's tool result reaches it as text
and `structuredContent`; other content blocks are left out.

A view should be one self-contained HTML document. It is kept only if it is at
most `MCP_APP_RESOURCE_MAX_BYTES`, and a server may declare at most 16 views.
A tool result's `structuredContent` is kept for the view up to 256 KiB.

## Without the content origin

With `MCP_APPS_ENABLED` unset, Eneo does not tell servers it can show views
and nothing changes. With it set but `MCP_APP_CONTENT_BASE_URL` missing, tools
work and their views show a note that they cannot be displayed.

## Regression checks

From the devcontainer, after installing the backend, frontend and tool-runtime
dependencies and Chromium, run `bun run test:mcp-apps` in `frontend/apps/web`.
This uses the production proxy, CSP and official SDKs in a real browser with
local test servers. It checks initialization, isolation, blocked early/late
navigation, built-in table state, all four chart types, chart controls,
localisation, safe labels and image fallback. Component tests in the normal frontend
suite also cover frame preservation and per-call approval.
