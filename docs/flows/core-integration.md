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

## Authoring through the core

The editor (`PATCH /flows/{id}/editor/`) and the chat's loopback tools share
`flow_authoring_operations.apply_editor_update`. Moving, inserting and removing
steps (`step_order`, and the `move_step`, `remove_step` and positioned
`add_step` tools) used to be safe only in the AI Builder; the core now does it
in `flow_step_structure.py`: aliases a kept step reads (`step_N` in its
bindings, interpolated configuration and prompt) follow their producers, and a
change that removes a read step or moves it after its reader is refused with
`flow_step_read_lost_producer`.

The `flows_core` gate authenticates in its own session and commits before the
route's container authenticates. Sharing a request with a function-scoped
route, an open gate transaction held the row of a legacy key hash it had just
upgraded, and the route's own authentication of the same key waited on it.

### Rules moved from the AI Builder

The builder enforced some rules only on what it compiled. They now hold for
every author, at publish unless noted:

- An assistant prompt (on a step that runs a model) and an HTTP request
  (`http_get` input, `http_post` webhook) may read only what the run has when it
  interpolates them: a declared form field, a runtime variable, the text,
  status, error or structured output of an earlier step (a webhook also its own
  step), or a field that step's contract declares. A prompt's runtime variables
  include `section_index` only on a step that processes each section. The
  refusals reuse the input binding codes with `field` naming the site.
- A template field may read an earlier step by its name, which is that step's
  text, but nothing below the name.
- `source_refs` may not list the same material twice, and a structured source
  ref must name a producer that yields structured output and a field its
  contract declares.
- A per-source reader writes one `documents` array with the source fields the
  run fills in; an item map reads and writes one array of objects. Both were
  refused only when the run reached the step.
- An audio step's uploads must be audio (`runtime_input.input_format`), checked
  on every save: with another format the run accepts other files and never
  transcribes. A document step may still take audio uploads, which the run
  transcribes.
- A new step's name in the editor update is stripped and must not be blank.

The chat's instructions carry the essentials of the builder's planner guidance:
step kinds, uploads, form fields, `{{ step_N.output... }}` reads and that
publishing names what to fix.

Dismissed: the builder's catalog references (model and knowledge refs), plan
step refs, quality lints, topology preferences and intent heuristics have no
meaning outside its planner. Steps without names stay publishable, because the
run reads steps by position. A flow_input file step without uploads keeps
reading the run's text, as the editor allows. Still open: a full `PUT` of the
steps reorders without renumbering prompt reads (the Svelte editor renumbers
them itself), a rename can make a kept read by step name name another step, and
`update_step` patches a step's assistant even when another step shares it.

### AI Builder removed

The builder's package, router, settings, budgets, permissions
(`flows_ai_builder`, `flows_ai_builder_review`), failure summary, retention job,
OpenAPI surface, SDK client code, Svelte screens and tests are gone. Migration
`202610212200` drops `builder_sessions`, `builder_plans`,
`builder_session_files` and `builder_client_errors` and takes the two
permissions out of every role; its downgrade recreates the tables empty and
grants the permissions to Owner roles again. Audit action types and the
`ai_builder` resource binding source stay for the rows already written;
`metadata_json.ai_builder` is dropped when a flow is read and refused on write.

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

## Long material

A completion step opts in with `input_config.long_material = {"mode":
"digest"}`, through REST, the editor PATCH, flow packages and the loopback
`flows` tools. Without it, input larger than the model's window still fails
with `typed_io_input_exceeds_model_window`, so existing flows run as before.

Taken from #1091: `completion_models/application/map_reduce.py` and its unit
test, byte-identical to `origin/feat/digest-tools` (segment planning, token
budgets, the bounded hierarchical reduce, deadline-aware admission and the
coverage account). Its MCP glue, `internal_mcp/digest.py`, is not taken.

Where it plugs in: `PassThroughStepHandler` (`pass_through` and `http_post`),
after the attempt is activated as before. `step_handlers/long_material.py`
measures the step's own request; only `current_request_input_does_not_fit`
leads to a digest, everything else goes to `complete_step_execution`
unchanged. The digest:

- splits the input into its sources (uploaded files, earlier step outputs,
  the rest) as spans of the exact text, measures the room of a map, a merge
  and the final request with the step's model, and plans the segments;
- is admitted against the organization's mapped-execution ceilings, with the
  codes a mapped step gets; a disabled call ceiling refuses it;
- sends every call through `call_assistant_with_timeout` with the step's model,
  assistant and settings (response format off), one at a time, so the
  provider-call recorder, the cancellation watch and the ownership check apply.
  Each receipt carries `digest_call` (stage `map`, `reduce` or `final`, the
  source indexes, the segment of a map call) in `flow_provider_calls.digest_call`
  (migration `202610212300`);
- starts no call once three quarters of the step's budget are spent, and
  cancels a call still running then, so the final call keeps the last quarter;
  map admission stops earlier and leaves a quarter of the digest's time to the
  merges. A cancelled run, a lost run or an expired step end the step exactly
  as they end any step;
- hands the merged notes to the step's own call, which keeps the step's prompt,
  output contract, native JSON, retrieval and typed output validation.

The step result keeps its real input. `input_payload_json.long_material`, also
`long_material` on the run step API, records the coverage: complete or partial,
the reasons, the sources left out, per source the segments read, failed, cut
and never sent, the call counts and the hash of the notes. The step's token
counts and the usage ledger include every digest call.

Coverage policy: complete coverage completes the step with an info diagnostic.
Partial coverage fails the step with `flow_long_material_partial_coverage`
before the final call, with the record in the failed step's input payload and
the segments read and planned in the run error. On a step with a review policy,
which pauses anyway, a partial digest that read something completes with a
`long_material_partial_coverage` warning and the reviewer approves, edits or
rejects the partial answer. Partial coverage never completes unmarked.

Not done yet: the web-next step editor has no control for the setting (it
travels in `input_config`), and no separate reader model is offered.

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
- Long material and partial coverage (the digest end to end in
  `tests/integration/flows/test_flow_long_material.py`), and transcript
  corrections.
- Migration from develop and the web-next journeys, WCAG 2.2 AA.
