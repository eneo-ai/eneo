# Eneo Flows + Flow AI Builder — Master Program (living document)

Status: CONVERGING — iteration 32 (max effort) returned
changes_required at 7; all findings source-verified and absorbed into
the v2 program below; iteration 33 (max effort, min-score 9) is
adjudicating v2. No implementation until convergence, then user
sign-off. This file is self-contained so ANY coding agent can continue
the program. Sibling context: `conformance-program-plan.md` (the
detailed slice protocol and the full verdict ledger, same directory).

## Mission

Production-excellent Flow AI Builder and Flows runtime (9/10): no
errors, near-zero repairs on supported archetypes, plans that satisfy
what the user actually asked, bounded resources, provable recovery,
clean single-owner architecture. Evidence-first: no fix without an
attributed mechanism; no claim without receipts; the 155-case suite
(3 repetitions, margin 5, rescored-case discipline) is the instrument.

## Where we are (2026-08-10 afternoon, HEAD ≈ `2e0a4dced`)

- Three checkpoints: deaths 50→30→27; architecture kills 13→10→2;
  provider wedges 22→6→2; conformance 149→162→170 of 465 (formally
  no_measurable_change; 81/155 cases unstable run-to-run).
- Repair tax: ~21% of accepted plans repaired. Cross-tab of repair
  wrappers: form-field family 7 obs, terminal_output_type_mismatch 6,
  flow_step_invalid 5, singletons after that.
- Shape coverage (clean checkpoint r01): json-terminal 36%,
  document-report 22%, text-terminal 14%, template-fill 3% — ~90% of
  plan-producing usage is server-recognizable.
- Slice 5 commit 1 landed: NamedResultEvidence (typed, cited, bounded)
  replaced the fake prose schema end-to-end; six hardening rounds.
- Runtime: full celery topology works (execute + maintenance + beat);
  crash recovery proven through the scheduled path; one-record-per-
  source enforced; connection budget bounded and logged; production
  compose network P0 fixed.

## THE ARCHITECTURE VERDICT (peer pass 31, max effort — adopted)

The system is NOT misdesigned; it is mid-migration. Create mode
already separates semantic intent from mechanics; the repair tax comes
from semantic decisions still model-owned. Therefore:

- **Never build a second skeleton compiler.** Deepen
  `CreateCompileContext` + `ai_builder_assembly`. `Pattern` stays
  selection metadata, never executable topology.
- **Transfer ownership one typed decision at a time**: each transfer
  moves a decision from proposal-time (model) to compile-time
  (server), then DELETES its prompt text and create-repair path.
- **Metrics of record** (not raw invariant count): supported create
  archetypes reach ZERO normal-path semantic critic hits; repair
  attempts and provider calls per accepted proposal fall
  monotonically; model-authored mechanical fields never increase;
  edit guards and compiler postconditions stay until their owner
  makes them unreachable.
- Honest ceiling without the transfers: conformance plateaus ~45–55%,
  leaf instability 20–30%.
- The free semantic proposal path remains for genuinely novel shapes,
  with explicit observability.

## Done ledger (checkmarks; update when a slice lands + gates)

- [x] Deterministic death families closed (commit-drift, critic
      intent, confirmation loop, evidence churn, lint_warnings,
      citations degrade, critic false-kill/ancestry, model-ref
      degrade) — deaths 50→27 across three checkpoints
- [x] Slice 1 frozen evidence packet + Slice 2 leaf attribution
      (unique grain, stability separated)
- [x] Slice 3 rubric corrections (11 deletions + 30 receipt-verified
      aliases; 25-case rescored discipline proven in comparator)
- [x] Slice 5 commit 1: NamedResultEvidence representation (six
      hardening rounds; schema v17/v20)
- [x] Depth cap 3→4 with publish-gate + runtime proof
- [x] Document-report assembly split (4 concerns, AST-verified)
- [x] Production compose network P0 + isolation note
- [x] Crash recovery proven through the scheduled path (`6559ef503`)
- [x] One-record-per-source runtime contract (`0b45457bd`)
- [x] Database connection budget bounded + logged (`2e0a4dced`)
- [x] Measurement instrument hardened (sentinel checks executable +
      case-gated; comparator case-local waiver; frozen baselines)
- [x] Architecture verdict adopted (Pass 31) + shape-coverage and
      repair cross-tab evidence
- [ ] Program convergence (iteration 32+ running, min-score 9)
- [ ] User sign-off on the converged program

## The Ranked Program (v2 — after iteration 32; under adjudication)

### Completion contract (proposed; iteration 33 adjudicating)
One matrix row per supported archetype (json-terminal,
document-report, text-terminal, template-fill — ~90% of usage):
admission predicate → canonical compiler owner → model-owned creative
fields → retired create invariants → explicit fallback behavior →
deterministic compile test + publish/run sentinel. Everything
unmatched routes to the observable free-proposal fallback
(`ai_builder_architecture_derivation.py:40`).
Numeric exit thresholds (proposed): first-pass acceptance ≥90% on
supported archetypes (now ~79%); normal-path semantic critic hits on
supported archetypes 0; repairs per accepted create plan ≤0.05;
deterministic deaths on stable cohort 0, total builder_error ≤10/465
(now 27); model-authored mechanical fields monotone non-increasing.
Scope: EXCELLENT CREATE MODE + runtime launch. Edit mode keeps its
guards; edit excellence is a later program (explicitly out of scope).

### Critical path (builder stream; each slice design-gated → worker →
### commit-gated → cohort probe)
- [ ] CP1 File-role flip closure. The margin regression IS the task-14
    case (same mechanism, confirmed). Owner:
    `_merged_model_file_roles` / `_model_file_role_can_replace`
    (`planning_state_builder.py:896`). Candidate invariant:
    explicit-evidence roles are sticky absent new contradicting
    evidence (kin of the evidence-churn family). The extra question
    round is attributed inside this same case study.
- [ ] CP2 Terminal ownership consolidation (premise CORRECTED in
    iteration 32, source-verified): the mismatch is SERVER-vs-SERVER
    dual ownership — compile derives the terminal from
    `architecture_commit` (`ai_builder_create_compiler.py:710`) while
    create preparation re-derives it from conversation text
    (`ai_builder_create_proposal.py:190` →
    `terminal_output_type_for_conversation`,
    `ai_builder_proposal_policy.py:259`) and a guard compares the two
    (`ai_builder_compiled_spec_preparation.py:70`). Ninth
    dual-ownership family. Step 1: attribution table with BOTH
    derivations per observation (re-derive offline from persisted
    planning state + conversation). Step 2 if confirmed: committed
    terminal becomes the single create-path owner; conversation
    derivation survives only for edit semantics; delete the alignment
    guard + create-side mismatch repair. `flow_step_invalid` stays a
    separate heterogeneous family (`flow_validators.py:227`).
- [ ] CP3 Runtime-input-field contract. Classifier output persists into
    the EXISTING typed owner `FlowInputFieldIntent`
    (`planning_state_builder.py:267`) through the existing hints path
    (`ai_builder_create_compiler.py:940,1100`) — no parallel
    declaration; at most a bounded consumer-role field on the
    existing type. Then delete the prompt's mechanical form-field
    block, the create repair mapping, and create-mode responsibility
    of the four form-field invariants (edit guards stay).
- [ ] CP4 JSON partial-emission diagnosis: why OSE captures some
    user-named fields and misses others (4 JSON cases). Diagnosis
    first; bounded fix gated on attributed mechanism.
- [ ] CP5 Named-result completion, redesigned: named evidence owns
    PRESENCE, never design. Bounded proposal interface where
    obligated names are inexpressibly present as keys while the model
    authors each field's type/nesting (candidate: tool-schema
    `required` + open per-key subschema; prove provider support
    first). No new store; no synthesized types; the critic stays
    until the interface makes it unreachable, then dies.
- [ ] Ownership-tranche gate: full 155×3 after CP1–CP3 land (one of
    exactly TWO full runs; the other is the release candidate).

### Launch stream (parallel; a RELEASE GATE, not a lower tier)
- [ ] L1 Durable topology: `.devcontainer` three-role compose + tracked
    max_connections (USER PERMISSION PENDING — protected path) +
    clean-volume recreation proof.
- [ ] L2 Provider throttling: fail-fast + typed provider-throttled
    diagnosis + operator/user guidance (NO flow-level retry loop).
- [ ] L3 Health: execution-consumer presence + beat freshness on the
    existing operator surface; deployment-native healthchecks. No new
    public liveness endpoint.
- [ ] L4 Object-content scope (USER DECISION): if in launch scope,
    attach celery-worker-flows to object_content_net + prove one
    read/write journey.
- [ ] L5 Launch receipt: pool-budget arithmetic vs SHOW max_connections
    under bounded load + one queue-recovery smoke at launch
    concurrency.
Release requires L1–L5 resolved or explicitly descoped by the user.

### Standing rulings — NOT slices (adjudicated; apply when touched)
- `planning_state_builder.py` split (3 owners + facade) only AFTER the
  ownership tranche settles. `step_input_resolution.py` splits when
  CP5 touches it. `step_execution_runtime.py` provider seam only if
  L2 changes provider behavior. `executor.py`: never split.
  `flow_run_repo.py` / `flow_models.py`: wait.
- `field_diagnostics`→`compile_diagnostics` rename, Slice-5 commit 2,
  and JSON fan-in: RE-ATTRIBUTE after CP1–CP3 (their cohorts may
  dissolve); implement only what survives re-attribution.
- Edit guards and compiler postconditions stay until their owner makes
  them unreachable; each CP names its deletions in advance.

### Measurement cadence
Cohort probes (3 reps, named cohorts) per slice; full 155×3 at
exactly two points (tranche gate, release candidate); suite runs
≥45 min apart (provider limits).

## Operating protocol (for any agent continuing this)

- Branch: commit/push ONLY `refactor/flows-clean` on eneo-ai/eneo.
  Never stage the user's protected files (`SolReview/`,
  `docs/adr/marketplace-*`, `.devcontainer/`, `goal.md`,
  `notes/handoff.md`, `notes/hermes-*`, `state.yaml`,
  `frontend/package.json`).
- Commits: `ENEO_DEVCONTAINER_NAME=developz_devcontainer-eneo-1
  git commit ...`; the container-side pyright pre-commit checks the
  DEPLOYED tree — if it OOMs (exit 247), run pyright manually on the
  changed files and `SKIP=pyright`, stating so in the message.
- Codex loops: `codex-peer-loop` session `flow-122-strategy`
  (builder; next iteration = check latest artifact under
  `.codex/artifacts/`), session `flows-runtime-readiness` (runtime).
  Implementation via `codex-implement-loop` workers in isolated git
  worktrees; the orchestrator judges every diff, re-runs decisive
  tests, owns all git. Peer-gate designs before code and commits
  after landing.
- Validation: `cd backend && uv run pytest tests/unittests/flows/ -q`
  (currently ~6445 green); ruff check/format + pyright
  (`--pythonpath .venv/bin/python`) on exact changed paths only.
- Measurement: harness + protocol in `conformance-program-plan.md`.
  Deploy bracket before gated runs: sync `/workspace` +
  `/tmp/eneo-clean` in container `developz_devcontainer-eneo-1` to the
  exact SHA, restart backend with fresh `GIT_COMMIT`, verify
  `/version`; celery via `cd /workspace/backend && bash run.sh` inside
  the worker/beat containers (maintenance consumer:
  `FLOW_CELERY_WORKER_QUEUES=flows.maintenance`); NEVER bare
  `docker restart` (kills the processes; safe pkill pattern
  `[b]in/celery`). Postgres max_connections=300 (volume-local — make
  durable per 3.1). Evidence packets:
  `/workspace/.codex/artifacts/slice2-evidence-manifest-20260810/`
  (self-replaying, hashed) and `evidence-freeze-20260809/`.
- Night window: no work 01:00–06:00 Stockholm (Codex included; no
  launches after ~00:10).

## Pending user decisions
1. Permission to edit `.devcontainer/docker-compose.yml` (protected)
   for the durable three-role topology (3.1).
2. Whether bundled object storage is in launch scope (3.4).
