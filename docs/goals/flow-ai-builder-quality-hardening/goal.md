# Flow AI Builder Quality Hardening

## Objective

Improve Eneo Flow AI Builder so it produces genuinely high-quality, logical,
efficient, maintainable flows, starting with the first merge-ready slice that
prevents the known bad multi-section audio-to-DOCX dataflow shape.

## Goal Kind

`specific`

## Current Tranche

Discover the current code/test state, choose the smallest safe implementation
slice, implement it TDD-first, verify it with deterministic tests and type
checks, run Claude peer review, and audit whether this slice makes the known bad
class of flow impossible.

The intended first implementation slice is expected to be around deterministic
dataflow validation and terminal artifact correctness, not a full Flow AI
Builder rewrite. The board may narrow or reorder that after Scout/Judge evidence.

## Non-Negotiable Constraints

- A working-but-dumb flow is a defect.
- TDD first: failing regression tests before implementation.
- Backend owns mechanics; the LLM must not author backend-owned bindings or
  terminal output mechanics directly.
- Do not use `all_previous_steps` as a band-aid for dropped context.
- Prefer explicit structured fields, targeted source text refs, form fields,
  prompt variables, input/output contracts, and bindings.
- Easy flows must remain simple.
- Strict Pyright/type checking must remain meaningful.
- Avoid `Any`, unjustified casts, `type: ignore`, untyped JSON bags, and
  stringly typed payloads unless a boundary reason is explicit.
- Do not commit junk files, scorecards, curl logs, temporary scripts, local eval
  output, API keys, screenshots, cache files, or secrets.
- Use environment variables for live API calls.
- Do not push, open a PR, create/switch branches, or commit unrelated dirty files.
- Treat `docs/refactor/new/flow_ai_builder_merge_ready_prd.md` and
  `docs/refactor/new/flow_ai_builder_merge_readiness_review.md` as starting
  evidence, not unquestionable truth.
- Goal Maker controls only the operating loop; repo-specific refactor docs and
  Claude peer review remain required.
- Prefer validation inside the devcontainer when local services or repo tooling
  require it. The approved command prefix is
  `docker exec eneo-41ae93-eneo-1 ...`; use `-w` to set the repo/backend working
  directory rather than changing branches or copying files.
- Use `ask-claude` for broad design brainstorming when a boundary or quality
  strategy is unclear. Use the stricter Claude peer-review loop for plan/code
  validation gates.

## Known Dirty / Do-Not-Touch Baseline

The board starts on a dirty worktree. The structured baseline lives in
`state.yaml` under `checks.dirty_baseline`. The first Scout task must verify and
classify current dirty files before any Worker implementation.

## Starting Evidence

- `docs/refactor/new/flow_ai_builder_merge_ready_prd.md`
- `docs/refactor/new/flow_ai_builder_merge_readiness_review.md`
- User-reported bad shape:
  - audio transcription step;
  - JSON section extraction steps daisy-chained through previous section JSON;
  - DOCX renderer receiving only the last section JSON;
  - trailing text step making text the terminal output despite DOCX intent.

## Stop Rule

Stop when the tranche audit passes, all safe local work is blocked, or
continuing would require owner input, credentials, destructive operations,
branch operations, push/PR decisions, or product strategy the board cannot
decide. Enforceable stop conditions live in `state.yaml` rules and task
constraints.

Do not stop after planning, discovery, or Judge selection if a safe Worker task
with explicit `allowed_files`, `verify`, and `stop_if` can be activated.

## Canonical Board

Machine truth lives at:

`docs/goals/flow-ai-builder-quality-hardening/state.yaml`

If this charter and `state.yaml` disagree, `state.yaml` wins for task status,
active task, receipts, verification freshness, and completion truth.

## Run Command

```text
/goal Follow docs/goals/flow-ai-builder-quality-hardening/goal.md through the first safe verified implementation slice. Do not stop after planning unless blocked.
```

## PM Loop

On every `/goal` continuation:

1. Read this charter.
2. Read `state.yaml`.
3. Work only on the active board task.
4. Assign Scout, Judge, Worker, or PM according to the task.
5. Write a compact task receipt.
6. Update the board.
7. If Judge selected a safe Worker task with `allowed_files`, `verify`, and
   `stop_if`, activate it and continue unless blocked.
8. Finish only with a Judge/PM audit receipt that maps receipts and verification
   back to the original user outcome.
