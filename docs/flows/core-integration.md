# Flow core integration with develop, web-next and loopback MCP

Status record for the integration branch `feat/flows-core-integration`. It
keeps the reference flow core with its history, brings develop in, and
replaces the dedicated AI Builder interaction with ordinary assistant chat over
a loopback MCP server and a web-next administration. The `flows_core` feature
flag stays off until the coverage listed under "Delivery gates" is verified.

## Starting points

| What | Commit |
| --- | --- |
| Reference core, `origin/feature/flows-and-builder` | `044ec559c1bb1865149325b0f5c6d7f425f95e2a` |
| Develop merged in, `origin/develop` on 2026-10-21 | `e6c635414b0ee20b622ca32a64d744302f39db26` |
| Merge base of the two | `ff30fadee32c81ac668ce1e770a7484cf161d835` |
| Earlier develop-based adoption checkpoint, `codex/flows-core-adoption` | `97aafa6d0050df94b73c4c6b27b71bdd0c8c05a4` (parent `e81b3e9d4`) |
| Earlier simplified core with its local HTTP, MCP and webhook work, `feat/flows-core-mcp-wip` | built from stash `cf5f1fb1c136bbcb6f8477185b221340a94a25d5` on `f0dc5236f` |

The adoption checkpoint and the simplified-core branch are local sources for
selective transfer. Neither is merged; nothing from them is applied as a whole
diff.

## Develop merge decisions

- Assistant updates keep the reference's typed `AssistantUpdateCommand`.
  Develop's `rerank_model_id` is a command field: an explicit null clears it on
  a standalone update, as develop's router did, and a change counts as
  security relevant for flow classification.
- Retrieval keeps the reference's `(chunks, embedding_model)` return and
  `include_info_blobs`, with develop's `rerank` parameter.
- MCP clients keep the reference's `MCPHttpClientFactory`. The default factory
  builds develop's client: no redirects and the loopback proxy bypass.
- Space access facts use the reference's rules (current group memberships,
  flow-managed assistants never in a key's scope). Develop's
  `get_space_access_facts` and `get_spaces_access_facts` are kept on top of
  them, with develop's check that a group belongs to the caller's tenant.
- The Svelte `SpacesManager` serializes updates (reference) and drops reads
  that a navigation or an applied update made stale (develop).
- Release notes are develop's: entries for 2.3 are curated on develop, so the
  reference's flow upload-limit note is not carried into 2.3.0.

### Migrations

Develop shipped `202610191000` (What's new marker correction). The reference
used the same id for transcript speaker names, which is now `202610191005`.
The reference's head merge `202610151000` now merges develop's head
`202610191600` with the flow chain, so every flow migration runs after
develop's. A database stamped at the reference's old `202610191000` is refused
by `eneo.database.renumbered_revisions` with the repair:

```
alembic stamp --purge 202610141000 202610142100 && \
alembic upgrade 202610191600 && \
alembic stamp --purge 202610191005
```

## Transfer from the adoption checkpoint

Each group lands as its own commit with the reference tests it touches.

| Group | Source in the checkpoint | Decision |
| --- | --- | --- |
| Shared authoring operations for REST and MCP | `flows/application/flow_authoring_operations.py`, `flow_authoring_router.py`, `flow_models.py` | Transfer |
| Flow-bound chat and loopback `flows` MCP server | `flow_authoring_chat*.py`, `flow_authoring_chats` table, `internal_mcp/flows.py`, session-bound internal tokens | Transfer and tidy |
| Document rendering through tool-runtime | `document_rendering/*`, `docx_template_runtime.py`, `document_runtime_preflight.py`, `document_templates/runtime_client.py`, `tool-runtime/src/tools/documents/control.ts` | Transferred; the reference's template and rendering tests run against a real runtime |
| Worker settings | `worker/flow_tasks.py`, `worker/arq.py` | Not yet: the reference already dispatches through ARQ and JobManager with separate execution and maintenance queues |
| Flow run retention | deletions of retention services | Open decision, see below |
| Develop-era reversions in platform files | for example `worker/routes.py` API key maintenance | Not transferred; the reference behaviour stays |

## Documents

The tool runtime renders Markdown to Word and PDF and fills Word templates; the
Python Word writer, content-control engine and WeasyPrint renderer are gone from
the backend. The core keeps the flow template contract: the runtime reports each
control's facts (container, table cell, heading level, refusal reason) and
`docx_template_runtime.py` applies the reference's profile and error codes on
top. Two runtime changes came from the reference's tests: a single-line text
control joins its lines with spaces, and a control's hint keeps its paragraphs,
line breaks and tabs. Busy runtime answers (429) are retried briefly. The
adoption checkpoint's rewritten template tests were not taken; the reference's
own tests are kept and pass through the runtime, except where they asserted the
retired engine's internals (injected renderers, WeasyPrint options).

Backend tests start `tool-runtime/tests/support/document-control-server.ts`
through the `shared_document_runtime` fixture; CI installs Bun, the runtime and
its PDF sidecar in the backend job.

## Open decisions

- Flow run retention (legal holds, history purge): retention belongs to a
  separate platform initiative. The reference code stays in place until that
  is decided; no new retention surface is added.

## Delivery gates

The flag stays off until these pass on this branch:

- The reference behaviour suites and REST/MCP equivalence.
- Tenant and principal isolation, concurrent edits, snapshots, classification
  and audit.
- Worker interruption, cancellation, review resume, retry and unknown webhook
  outcomes.
- Capabilities, produced files and refused destinations.
- Documents through a real tool-runtime.
- Long material, partial coverage and transcript corrections.
- Migration from develop and the web-next journeys, WCAG 2.2 AA.
