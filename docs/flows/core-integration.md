# Flow core integration with develop, web-next and loopback MCP

Status record for the integration branch `feat/flows-core-integration`. It
keeps the reference flow core with its history, brings develop in, and
replaces the dedicated AI Builder interaction with ordinary assistant chat over
a loopback MCP server and a web-next administration. Flows are on for every
tenant: the `flows_core` feature flag is seeded off by 202610211900 and turned
on by 202610221000, which also gives existing predefined Owner roles the four
flow permissions (and AI Configurator roles `flows_trace`), as new tenants get
them. A tenant row with `enabled = false` turns flows off for that tenant.

## Starting points

| What | Commit |
| --- | --- |
| Reference core, `origin/feature/flows-and-builder` | `044ec559c1bb1865149325b0f5c6d7f425f95e2a` |
| Develop merged in, `origin/develop` on 2026-10-21 | `e6c635414b0ee20b622ca32a64d744302f39db26` |
| Develop merged in again, `origin/develop` on 2026-10-23 | `6d7bf6753ffa49e0946bc9828490a6f627f6f4af` |
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
- Password lifecycle (2026-10-23 merge): the branch keeps its own error codes
  for the password errors (9061-9064, where develop uses 9058-9061), and
  develop's `PASSWORD_CHANGE_REQUIRED` keeps 9070. The e2e stacks set
  develop's `DEFAULT_USER_PASSWORD_CHANGE_REQUIRED: "false"` in their shared
  backend environment. eneo-js keeps running its tests with `bun test`, so
  develop's two new tests count calls with plain spies instead of
  `node:test`'s `mock`, which bun does not provide.

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

The 2026-10-23 merge brought develop's `202610211200` (website path index) and
`202610161000` (password lifecycle), both after `202610191600`. The new merge
`202610231000` joins `202610161000` with the flow head `202610221100`, so a
flow database runs both develop migrations on its next upgrade. Re-pointing
`202610151000` again would have marked them applied without running them.

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

The editor (`PATCH /flows/{id}/editor/`), the manual update
(`PATCH /flows/{id}/`) and the chat's loopback tools share
`flow_authoring_operations`. Rewriting reads used to happen in the AI Builder
and in the Svelte editor's browser code; the core now does it in
`flow_step_structure.py`, so every client (web-next, the chat's tools, API
keys) gets the same result and every rewrite is part of the saved revision, so
a stale client is fenced by `expected_revision`. A read of another step is its
alias (`step_N`) or the step's name, in the step's bindings (by name: the
question and a source ref's `step_ref`), the configuration its modes
interpolate (HTTP requests, template bindings, tool arguments) and its
assistant's prompt; a read of a run form field is `flow_input.<name>`,
`flow.input.<name>` or the bare name.

- Moving, inserting and removing steps (`step_order`, and the `move_step`,
  `remove_step` and positioned `add_step` tools): aliases follow their
  producers.
- Full replacement (`steps` in `PATCH /flows/{id}/`, or `definition.steps` in
  the editor update): a step that keeps its `id` moves to its `step_order`, a
  step without an `id` is new, and a saved step left out is removed. A read
  column (`input_bindings`, `input_config`, `output_config`) a step sends as
  it was read (stored credentials as sentinels) is the saved one and its reads
  follow the change; one it sends changed is taken as given. Unknown or
  repeated ids and step orders that are not 1 to n are refused by the save as
  before.
- Renaming a step: reads of the old name in every step follow the new one,
  several renames in one edit at once (two steps may swap names).
- Renaming a run form field: `form_field_renames` (`{"old": "new"}`, on the
  manual update, the editor's `definition` and the chat's
  `update_flow_settings`) names it; the reads of the field follow it, and a
  bare read of a field renamed to a name that cannot be bare becomes
  `flow_input.<new>`. A rename the forms do not describe is refused with
  `flow_form_field_rename_invalid` (`context.problem`: `unknown_field`,
  `not_in_form`, `still_in_form`, `name_taken`, `renamed_twice`). web-next
  sends it for every saved field whose technical name changed.
- A change that would make a kept read name another step, or none, is refused
  with `flow_step_read_lost_producer`; `context.reason` says why:
  `producer_removed`, `producer_moved_after_reader`,
  `reader_moved_before_producer` (of the two steps, the one that moved
  farther), `producer_renamed` (the name is cleared, cannot be read in a
  template, or another step takes it; `context.reads_name` holds it) or
  `would_read_another_step` (a forward or dangling read would come to name a
  step it could not read before). A dangling read by name may come to name a
  step that is given that name. Removing a run form field a kept step reads is
  refused with `flow_form_field_still_read`, `context.readers` naming each
  reading step and site.
- Columns and prompts the same edit writes are taken as given.

Changing a published flow or one of its step assistants is refused with
`flow_unpublish_required`, unpublishing a flow that is not published with
`flow_not_published`.

### The authoring chat's model and conversations

`flow_authoring_chats` keeps the person's own `completion_model_id` and
`reasoning_effort` (migration `202610221100`; null follows the default) and
`mode_changed_at`. `PATCH /flows/{id}/authoring-chat/{session_id}/` (operation
`update_flow_authoring_chat`) takes them next to `editing`; the model is
refused unless the space allows it the way it allows an assistant's model
(`space.is_completion_model_available`, the space's classification split) and
it supports tool calling, with `flow_authoring_model_not_in_space`,
`flow_authoring_model_below_classification`,
`flow_authoring_model_without_tools` and
`flow_authoring_reasoning_effort_unsupported`. The organisation default lives in
`tenants.flow_settings["authoring_chat"]` (`/settings/flow-authoring-chat-policy`,
refused without tool calling). `_sync_assistant` runs when a chat is opened and
after every PATCH: the hidden assistant gets the core's instructions, the model
in force (own choice, else the organisation default where the space allows it,
else `space.select_default_completion_model` over the space's tool models) and
the reasoning effort when that model offers it, and only what differs is
written.

The row points at the chat's current session. Entering edit mode after
`FLOW_AUTHORING_CHAT_IDLE_MINUTES` without a question in the current session or
a mode change, and `POST .../conversations/`, point it at a new session of the
same hidden assistant (audited as `flow_authoring_conversation_started`). An
empty conversation is never replaced by the pause rule. Earlier sessions stay
linked by the assistant; `load_authoring_chat` admits only the current one, so
the ask path and the loopback tools refuse an old session and it never reaches
the model. web-next does not list earlier conversations (decision 2026-10-22):
the flow, its revisions and the audit log are the record, and an old
conversation's suggestions may no longer match the flow.

### Caller permissions on a flow

`FlowPublic` and `FlowSparsePublic` carry `permissions` (`can_edit`,
`can_publish`, `can_delete`, `can_run`, `can_view_runs`) for the caller.
`flow_definition_access.flow_permissions` decides them with the checks the
endpoints make, run without raising: editing, publishing and deleting as
`require_flow_edit_access`, `require_flow_publish_access` and
`require_flow_delete_access` (the action's permission, the space's permission
and the draft-ownership rule), running as run creation and reading runs as the
run list (`enforce_flow_scope`, through `check_flow_scope`). The flow's state is
not part of them: a published flow still says `can_edit` for its owner, and
the edit answers `flow_unpublish_required`.
`tests/integration/flows/test_flow_permissions.py` checks each flag against
its endpoint for the owner, another editor, a viewer, a user outside the space
and a space-scoped service key. web-next shows a flow's controls by these flags
(deletion in the flows list; editing, export, publishing, runs and the
authoring chat on the flow page) and still explains a 403 in words.

### Allowed step kinds

`GET /flows/{id}/step-kinds/` answers, for each place a step can be added and
for each saved step turned to another kind, which of the editor's step kinds
(`ai`, `structured`, `compose`, `document`, `template`, `transcribe`,
`speakers`, `review`, `fetch_http`, `tool`, `send_http`) the draft allows and
why it refuses the others. The kinds and their starting configurations live
in `flows/domain/step_kinds.py`; a step added first takes the run's input over
from the step that was first, and an audio kind turns transcription on. Each
kind's change is built as the editor update makes it and judged by that save's
placement, read following, inactive-setting cleanup and step rules
(`flows/application/flow_step_kinds.py`, sharing `sparse_placement`,
`new_flow_step`, `steps_as_written`, `draft_write_metadata` and
`draft_step_refusals` with the save), so `allowed` is true exactly when the
save accepts the change and `refusals` are its errors (`code`, `issue_code`,
the step). `tests/unit/flows/application/test_flow_step_kinds.py` sends every
answer through `apply_editor_update` and checks that the save agrees. Not
judged: the new step's name, the URL or tool the author enters, and the checks
against the space (assistants, classification, transcription service). The
work grows with the square of the step count; `position` and `step_id` narrow
the answer to one place.

The core is the judge: a speaker mapping may follow any step, and a step can
be added before a first step that takes uploads beside a text input (the core
refuses only an upload input type). web-next's add-step dialog and its speaker
step shortcut ask for the place (`position`), offer the kinds it allows,
explain the refusals from their codes and add the step with the answer's
configuration and step edits; it keeps no copy of these rules.

The `flows_core` gate authenticates in its own session and commits before the
route's container authenticates. Sharing a request with a function-scoped
route, an open gate transaction held the row of a legacy key hash it had just
upgraded, and the route's own authentication of the same key waited on it.

### Shared step assistants

An editor assistant change can name its step (`step_id`). When other steps
share that assistant, the step gets its own copy of it (copy on write) with the
change, in the same transaction as the edit, and the other steps keep the
assistant as it was; the saved revision shows the step with its new
`assistant_id`. The copy is made from the assistant's settings as they are
(prompt, model and its settings, knowledge, attachments and their modes,
retention, logging), so copying asks only for the right to create assistants in
the space. The chat's `update_step` tool always names its step; web-next's
step editor does too. A change without `step_id` reaches every step that uses
the assistant, as before. A classification preview candidate takes `step_id`
with the same meaning: the step is explained with its own copy of the shared
assistant, made from the assistant as the other candidates leave it, and the
other steps with the assistant as it was, so the preview judges what the save
will. web-next's step editor names its step in the preview as in the save.

### Audit of an authoring change

The authoring routes (create, update, editor update, publish, unpublish) and
the chat's loopback tools open the change's transaction with
`flow_authoring_operations.authoring_transaction`. The change's audit entries
(`ASSISTANT_UPDATED`, `ASSISTANT_CREATED` for new steps and copies, the prompt
rewrites with `reasons` `step_order_changed`, `step_renamed` or
`form_field_renamed`, `FLOW_UPDATED`, `FLOW_CLASSIFICATION_OVERRIDE`,
`FLOW_CREATED`, `FLOW_PUBLISHED`, `FLOW_UNPUBLISHED`) are held while it runs and
handed to the audit queue once the transaction has committed, before the
response goes out. A refused change, rolled back, leaves no entry. The routes'
audit contract stays configurable and asynchronous: a queue failure after the
commit does not undo the change. An operation called outside such a
transaction logs its entries once every check that can refuse the change has
passed.

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
reading the run's text, as the editor allows.

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

What only the builder used went after it: the edit path of the authoring
command (it now only creates a draft, as a flow package install does), the
edit compilation and saved-step carrying of the draft materialization, the
authoring snapshot, the template attachment (a package's template imports
stay, in `flow_template_import_materialization.py`), the origin policy, the
capability manifest's `proposable_new` projection and the unused
`observability/failure_events.py`. The template asset service's
`create_from_existing_attached_file` has no production caller left; tests
still use it to make an asset from a saved file.

### Svelte flow screens removed

Flows are built, run and administered in web-next only. The SvelteKit app's
space flow pages, editor, run views and `lib/features/flows`, the admin Flow
settings page (with its retention, legal hold, upload, run time and source
text tabs) and the old flow admin redirects, the MCP server flow usage list,
and the recording support only the flow run dialog used are gone, with their
tests, Playwright specs and messages. The space menu's Flows entry opens
web-next's flows page when `NEW_APP_URL` is set and is left out otherwise; the
admin area is for admins again, without the retention-only entry. web-next
keeps every string it reads: the keys only it still used moved to its
`extra/` catalog. The SDK lost the settings client's flow wrappers and the MCP
`flowUsage` wrapper; its flows client stays for applications that run flows.
Run-history retention and legal holds have no screen in either app: they are
set through the API (see the retention guide) until the platform initiative
under Open decisions settles them. The backend is unchanged.

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

The web-next step editor offers the setting as a switch on the steps the core
accepts it on, and the run page shows the coverage record on the step. No
separate reader model is offered.

## Open decisions

- Flow run retention (legal holds, history purge): retention belongs to a
  separate platform initiative. The reference code stays in place until that
  is decided; no new retention surface is added.

## Delivery gates

These must pass on this branch before the PR to develop:

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
