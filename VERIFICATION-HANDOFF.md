# Flow AI Builder, 2026-09-14: what changed and what still needs verifying

Branch `refactor/flows-tidy-ai-builder`, tip `af688faac`, all pushed.
Range landed today: `5ec6aa2c9..af688faac` (8 code commits, 3 board commits).

Every code commit was gated by an independent reviewer at high effort and landed only on a
green verdict with a minimum score of 8.

---

## 1. What changed

### 1.1 Backend, the edit path

**`56e03ed47` give a selected saved step its own authoring context and bounded edit**
Improving one step of a saved flow asked the model to rewrite text it could not see: the
planner got a capability profile and a step overview, never the selected step's own
instructions or contracts. A saved-step turn now carries a focused projection as quoted data,
and uses the bounded edit schema so only the target is modifiable.

**`5110ef066` see every dependency a step has, and refuse a chain that would break**
The dependency projection missed runtime aliases and whole-input reads, and an incompatible
implicit JSON consumer passed both authoring checks while only runtime validation caught it.
Both fixed; a broken chain is now refused as repair feedback.

**`2baa78ca6`** restores two regressions my own rebase had dropped from the test module. No
production code.

**`79db5fab1` stop asking the model to restate the steps it is not changing**
The scoped edit schema demanded the complete ordered step list, so editing one step of a
40-step flow made the model emit 39 `keep` objects and carry 40 refs in an enum, replayed on
every repair round. A saved-step turn now submits only its modifications and the server
expands them into the full ordered plan from the saved revision.

### 1.2 Backend, diagnosability

**`d1400f2a2` make a provider rejection name itself**
Two Builder edit turns died on the test server with a provider 400 that left nothing to
diagnose. One owner now returns a rejection record with the safe code, the normalized
parameter, the extraction source and status, and the provider's correlation id, including on
the streaming path where LiteLLM's error conversion had been dropping it.

### 1.3 Frontend

**`548dab54a`** run evidence printed raw runtime identifiers (`skipped_transcribe_only`,
`no_chunks`, `skipped`) to Swedish users; all now read as sentences, unknown ones say "Okänd".
The history panel no longer repeats the tab's own word as a heading.

**`bff975a04`** the plan review printed the server's English advisory prose to Swedish readers,
and told every edit that "den publicerade versionen körs oförändrad" even for a draft that was
never published and that the screen cannot know about.

---

## 2. What is already verified, and how

| Check | Result |
|---|---|
| `backend/tests/unittests/flows` on the tip | 7476 passed, 10 skipped, 1 xfailed |
| `tests/integration/flows -k ai_builder` on the tip | 136 passed, 332 deselected |
| Bare pyright | 0 new errors (2 pre-existing, in files these commits do not touch) |
| Paired create cohort, candidate vs exact parent | identical: 6 pass / 6 fail each, same outcome distribution |
| The 2 cases that disagreed, re-run x3 per stack | within-stack variance as large as between-stack; explained by non-determinism |
| Scoped schema cost | 10-step and 40-step schemas byte-identical, equal tool-schema and tool-call token counts |
| Other schemas unchanged | 8 whole-flow and review schemas pinned byte-identical to before |
| One manual end-to-end edit in the browser | DOCX template fill changed to PDF: correct plan, 3 untouched steps preserved, confirmed in the database |

Reproduce the cohort:

```
# candidate = the tip, parent = the commit before the slice under test
ENEO_API_KEY=<space-scoped admin key> ENEO_SPACE_ID=<space> \
  python scripts/ai_builder_api_battle_test.py \
  --base-url http://127.0.0.1:<port>/api/v1 --cohort smoke_v3 --repetitions 3 --concurrency 2
```

`--run-suite` is the full benchmark and cannot be combined with `--cohort`.

---

## 3. What is NOT verified, and needs your agent

### 3.1 The blocker: the harness cannot measure an edit at all

All 172 cases in `backend/scripts/ai_builder_api_battle_cases.json` are create cases, and
`ai_builder_api_battle_test.py` hardcodes `"target_kind": "create"` (~line 6387). There is no
edit case and no flag to drive one. **So the standing rule of measuring a Builder slice against
its parent has never covered the edit path, for this slice or any earlier one.**

Everything in section 1.1 changes the edit path. The create cohort in section 2 only shows
there was no collateral damage.

**Highest-value work: give the harness an edit case.** It needs to create or adopt a flow,
open a session with `target_kind: "edit"` and a `flow_id`, and send a turn carrying
`edit_context: {"kind": "saved_flow_step", "flow_step_id": <uuid>}`. Then the existing
expectation machinery can score it like any other case.

A standalone probe already exists as a starting point and works end to end:
`<scratchpad>/edit_probe.py` (path in the Beads comment on eneo-341). It creates a flow from a
fixed prompt, applies it, runs N saved-step edits, and records per edit the outcome, duration,
provider calls, tokens, attempts, and whether the stored flow stayed untouched before apply.

Two contract details that cost me time, so your agent does not repeat them:
- authenticate with the **`X-API-Key`** header; `api-key` returns 401, and a naive JSON read of
  that error looks like an empty result;
- confirming requirements is a **structured** turn, not a chat reply:
  `question_answer: {"kind": "requirements_confirmation", "requirements_confirmed": true,
  "ui_language": "sv", "requirements_version": <version from the requirements summary>}`.
  Without it the session sits in `chatting` forever.
- per-turn token cost is not on the session; read
  `/flows/ai-builder/sessions/{id}/_diagnostics/proposal-telemetry`.

### 3.1a SUSPECTED REGRESSION IN `79db5fab1` — investigate this first

A paired live edit probe (5 repetitions per stack, built because the harness cannot do it)
produced a sharp difference. **This was found after the commit had already landed.**

| | parent `d1400f2a2` | candidate `79db5fab1` |
|---|---|---|
| flow built by the probe | 3 steps | 4 steps |
| edits that produced a plan | **5 / 5** | **0 / 5** |
| provider attempts per edit | 1, no repairs | 4 repair rounds, then gave up |
| duration per edit | ~7.5 s | ~55 s |
| stored flow untouched before apply | 5/5 | 5/5 |

Every candidate edit ended with turn error `self_correction_quality_failure`
(eneo_error_code 9007, phase `self_correction`): "The corrected plan still failed the AI
Builder quality checks."

The server log shows the proximate cause, four times per session before it gives up:

```
ai_builder_scoped_plan_edit_rejected session_id=<id> target_step_ref=existing_step_1
logger = eneo.flows.ai_builder.ai_builder_edit_proposal
```

so the scoped-edit admission in `ai_builder_edit_proposal.py` (~line 412, `scoped_rejection`)
is refusing the model's fragment, the repair loop retries, and the turn dies.

**What this means:** slice 2 changed the model's submission from a complete ordered list to a
modification fragment, and on this evidence the fragment is being refused by the admission that
runs after it. The unit tests pass because they build the fragment themselves; only a live model
filling the new schema exposes it.

**Caveats, stated because the result is serious:**
- the two stacks built *different* flows (4 steps vs 3), so this is not a controlled comparison,
  and the target step's content differs;
- my probe reported `provider_calls: 0` for the candidate, which is wrong (repairs clearly ran);
  the token columns for the candidate are a probe artifact and must be ignored;
- 5 observations per stack, one flow each.

**First thing to do, before any fix:** make it a controlled comparison. Run the same probe
against both stacks with the *same* flow shape, or run the candidate probe several times so
each run builds a different flow. If the candidate fails on every flow while the parent
succeeds on every flow, it is the code. Then capture the actual rejection reason, which the log
line does not carry today: instrument or read `scoped_rejection` in
`ai_builder_edit_proposal.py` to see which check refuses the fragment.

**Until that is resolved, treat `79db5fab1` as suspect.** Reverting it restores the previous
edit behaviour at the cost of the token saving; the two commits before it in the range are
independent of this and do not need to move.

### 3.2 What to measure on the edit path

Compare candidate `79db5fab1` against parent `d1400f2a2`, same flow shape, repetitions >= 5:

1. **Does the model fill the new fragment schema?** A plan produced on the first attempt, with
   no rise in repair attempts. This is the main regression risk: the model no longer restates
   the flow, and restating may have been doing grounding work.
2. **Are untouched steps preserved byte-for-byte** through expansion, after apply, not just
   before it.
3. **Token cost per edit turn** should fall on the candidate and, critically, should stop
   growing with flow size. Build a 10-step and a 40-step flow and compare the curve.
4. **The refusals still refuse**: an unknown step ref, a ref outside the permitted set, a
   duplicate, a stale revision, and an attempt to add or remove a step.
5. **Repair feedback still names the target step** when a proposal is rejected.

### 3.3 Second thing to verify: the provider rejection evidence

`d1400f2a2` is diagnostic-only and changes nothing the model sees, so it carries no quality
risk. What it needs is a **live confirmation** that a real provider rejection now records a
correlation id. The unit tests drive the installed LiteLLM adapter over mocked HTTP; nobody has
seen it work against the real Azure deployment.

The original incident is **still unidentified**: two edit turns on `azure/gpt-5.6-luna`, 400
after ~1s on a 5,669-token request in a 1,050,000-token window, no error code and no parameter
recorded. Local probes ruled out the wrong-parameter-name theory (LiteLLM converts
`max_tokens` to `max_completion_tokens` for Azure GPT-5) and showed an ordinary temperature
refusal would have been captured cleanly. Only two envelope shapes lose everything: a gateway
envelope `{statusCode, message}`, and an Azure error object with a message but no `code` and no
`param`. If it recurs, the correlation id in the failure log is now the thing to trace in
Azure.

### 3.4 Known open defects, filed not fixed

| Bead | What |
|---|---|
| `eneo-s2z` | Two competing owners for user-facing prose: server `ui_language` branches vs client lookup by code. Needs an ownership ruling before more strings are fixed. |
| `eneo-ggw` | One advisory cannot be localized because it interpolates field names into prose instead of carrying parameters. |
| `eneo-j62` | The apply dialog says all 4 steps update while the same screen says 1 changed. |
| `eneo-cls` | Nothing validates that a rag status is a member of its declared enum, so a handler can invent a word that reaches users. |
| `eneo-341` | Slice 3 (the orientation list still grows with flow size) and slice 4. Slice 3 must be measured against planner quality, not assumed. |

---

## 4. Environment for whoever verifies

Two lane stacks, both from `relaunch_stack.sh <parent|simplify> <worktree> <sha12>`:

- candidate: API `:8144`, DB `eneo_ai_builder_simplify`, space `6f18b073-ea64-4a5e-8236-778a25e72d8f`
- parent: API `:8146`, DB `eneo_ai_builder_parent`, space `9fe65f26-b0dd-47e8-9aea-aa02a2e50014`

Both spaces must contain zero flows before a leg; verify with
`GET /api/v1/flows/?space_id=<space>` using `X-API-Key`. Space-scoped **admin** keys are
required: the preflight refuses org-scoped keys, and a non-admin key cannot delete the flows
that apply-plan cases create.

The model in both spaces is `gpt-5.6-luna`, id `69ea7ad9-19e1-4dac-bcbe-9eb715e12644`. Locally
this is an OpenAI route, not Azure, which is why the production 400 does not reproduce here.

One environment trap: the parent database was missing `governance_policies.inline_file_text`
while `alembic_version` already read head, which 500s the flows list. Fixed by adding the
column directly. Check for it before blaming the application.
