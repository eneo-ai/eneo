# Eneo Flows + Flow AI Builder — Master Program (living document)

Status: CONVERGING — iterations 32 (score 7) and 33 (score 8, max
effort) each returned changes_required; every finding was
source-verified locally and absorbed. This file is now program v3;
iteration 34 (max effort, min-score 9) adjudicates it. No
implementation until convergence, then user sign-off. This file is
self-contained so ANY coding agent can continue the program. Sibling
context: `conformance-program-plan.md` (the detailed slice protocol
and the full verdict ledger, same directory).

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

## The Ranked Program (v3 — after iteration 33; under adjudication)

### Completion contract (attempt-level; no accepted-plan denominators)
Every eligible create attempt lands in ONE bucket of an exhaustive
ledger: supported row (exactly one, by ordered exclusive predicates)
or fallback → then first-pass / repaired / failed / stalled /
provider-unknown. Thresholds are per eligible attempt, never per
accepted plan (a death before acceptance must count against us):
- Supported coverage ≥90% of eligible create attempts (exclusive
  row-or-fallback assignment; the old "~90%" used an unstated
  plan-producing denominator — corrected).
- First-pass accepted plan ≥95% of eligible supported attempts;
  repair attempts ≤0.05 per eligible supported attempt.
- Normal-path semantic critic hits on supported archetypes: 0.
- Stable explicit user obligations: zero stable failures; supported
  conformance ≥90%; leaf flip rate ≤10%.
- Deterministic product deaths 0; product-attributable builder errors
  ≤1%; stalls and provider failures tracked separately (≤10/465 stays
  only as an interim tranche target).
- Bounded p95 provider calls, tokens, and planning latency (baseline
  extracted from the clean checkpoint in CP0).
- Release verdict from a powered sample; 3 repetitions stay
  exploratory.
Scope: EXCELLENT CREATE MODE + runtime launch. Edit mode keeps its
guards; edit excellence is a later program (explicitly out of scope).
SURFACE-CLOSURE MILESTONE (greenfield adjudication, iteration 33):
the end state is a CLOSED proposal contract per supported archetype —
every ownership transfer must also remove the transferred field from
that archetype's proposal schema. Closure is a matrix milestone, not
a hoped-for side effect. No rewrite: compile context + assembly stay
the migration seam.

### Critical path (builder stream; each slice design-gated → worker →
### commit-gated → cohort probe)
- [ ] CP0 Matrix freeze (analysis only, no product code). Ordered
    mutually exclusive predicates with precedence for the supported
    archetypes (current draft rows mix terminal type/topology/mode
    and can overlap — e.g. JSON-to-artifact vs text-to-artifact vs
    document-to-structured-report patterns in
    `ai_builder_architecture_derivation.py:186`). Classify EVERY
    frozen create observation into exactly one row or fallback and
    publish the ledger; define the eligible-attempt denominator; map
    ALL 31 invariants to impossible-and-delete / retained
    postcondition / fallback-only (CP1–CP5 alone are not assumed to
    reach zero hits); extract baseline p95 provider calls, tokens,
    latency. Matrix rows get stable IDs + versions.
- [ ] CP1 File-role flip closure (TRIMMED, iteration 33). The margin
    regression IS the task-14 case (same mechanism, confirmed).
    Deepen the EXISTING merge owner `_model_file_role_can_replace`
    (`planning_state_builder.py:1006`) — verified: it checks source
    and heuristic confidence but never the existing role's evidence
    LEVEL, so an inferred re-classification can replace an
    explicit-quote-backed role. Fix: monotonic precedence from
    existing evidence level + citation identity — same-evidence flips
    rejected, genuinely later explicit corrections accepted,
    conflicting evidence becomes explicit ambiguity. NO role-history
    store. The extra question round is attributed inside this same
    case study.
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
    planning state + conversation). Step 2 if confirmed (AMENDED,
    iteration 33): keep the postcondition but feed it
    `CreateCompileContext.final_output_type` — same-owner self-check,
    not dual ownership; delete only the conversation re-derivation on
    the create path and the model-repair ownership (a create mismatch
    becomes a compiler defect, never model-repairable feedback);
    conversation derivation survives only for edit semantics.
    Exit check: no create caller still invokes
    `terminal_output_type_for_conversation`. `flow_step_invalid`
    stays a separate heterogeneous family (`flow_validators.py:227`).
- [ ] CP3 Runtime-input-field contract (AMENDED, iteration 33).
    `FlowInputFieldIntent` stays the field VALUE schema, but verified
    it carries no citations/confidence
    (`ai_builder_proposal_intent.py:80`) and the classifier exposes
    only boolean form intake
    (`ai_builder_slot_classification_contract.py:162`) — so the
    classifier ships a bounded CITED DELTA ENVELOPE (update/clear +
    per-field citations + confidence; the same transport pattern as
    ClassifiedNamedResultDelta), a transport contract around the
    existing value type, never a second owner. Durable owner stays
    conversation metadata; `PlanningState.input_fields` stays the
    derived view; placement defaults to the archetype's one
    deterministic consumer; semantic purpose only for evidence-backed
    multi-consumer cases; never leak physical `PlannedStepRole`
    upstream. Then delete the prompt's mechanical form-field block,
    the create repair mapping, and create-mode responsibility of the
    four form-field invariants (edit guards stay), and remove
    `input_fields`/`uses_form_fields` from that archetype's proposal
    schema (surface closure).
- [ ] CP4 JSON partial-emission diagnosis: why OSE captures some
    user-named fields and misses others (4 JSON cases). Diagnosis
    first; bounded fix gated on attributed mechanism.
- [ ] CP5 Named-result completion, redesigned (AMENDED, iteration 33):
    named evidence owns PRESENCE, never design. Verified blockers the
    design gate must resolve BEFORE code: the current invariant
    accepts an obligated name at ANY depth
    (`ai_builder_critic_invariants.py:854` via
    `schema_property_names_at_any_depth`), so naive top-level
    `required` keys would silently choose nesting; and the proposal
    tool schema is built independently at TWO sites — token budgeting
    (`ai_builder_planner_request_preparation.py:463`) and submission
    (`ai_builder_proposal_submission.py:171`) — with obligations
    reaching neither. Design gate decides: top-level placement as a
    canonical product rule OR a bounded per-name design map with a
    defined compiler projection; then materialize ONE schema reused
    by both budgeting and submission; then one provider strict-tool
    probe with a nested obligated field. No recursive schema DSL. If
    the provider cannot express the contract, the critic stays.
- [ ] Ownership-tranche gate: full 155×3 after CP1–CP3 land (one of
    exactly TWO full runs; the other is the powered release
    candidate).
- [ ] Post-CP5 re-attribution loop: rerun attribution and continue
    ownership transfers until the completion contract passes — the
    five slices are a starting set, not assumed sufficient (31
    invariants remain in the registry;
    `ai_builder_critic_invariants.py:1823`).

### Launch stream (parallel; a RELEASE GATE, not a lower tier)
- [ ] L1 Durable topology (RE-TARGETED, iteration 33): the release
    proof runs against the ACTUAL launch artifact,
    `docs/deployment/docker-compose.yml` — verified to already own
    the three roles (execute, maintenance with
    `FLOW_CELERY_WORKER_QUEUES=flows.maintenance`, beat) with
    `restart: unless-stopped`. The `.devcontainer` compose (whose
    flow worker just runs `sleep infinity`, no maintenance role) is
    developer ergonomics: bring it to parity under the USER
    PERMISSION GRANTED 2026-08-10 (scoped), but it is OFF the release
    critical path. Fine details with long-term leverage, each traced
    to a real incident, applied to the deployment artifact first:
    - Three first-class compose services (execute worker, maintenance
      worker, beat) with explicit queue env, `restart: unless-stopped`
      and native healthchecks — no manually started processes inside
      `sleep infinity` containers (incident: dead beat + missing
      maintenance consumer orphaned 4 runs and saturated concurrency).
    - Beat is a singleton by construction (duplicate beat = duplicate
      redispatch storms).
    - Queue names get ONE source of truth shared by producer and
      consumer config (the orphan incident was consumer-topology
      drift).
    - Tracked Postgres max_connections=300 in compose/conf, not a
      volume-local ALTER SYSTEM (dies on volume recreation); prove
      with a clean-volume rebuild.
    - GIT_COMMIT stamped at container start so `/version` can never
      lie (retires the manual re-stamp discipline that already bit us
      once).
    - Worker lifecycle for long tasks, design-gate questions: prefetch
      multiplier 1 for the execute role (a dying worker must not
      hoard prefetched runs); redelivery has ONE owner — the
      flow_run_recovery_policy — never broker acks-late as a second
      redelivery mechanism (dual-ownership disease applies to
      infrastructure too); warm-shutdown window vs recovery redispatch
      adjudicated so termination mid-run always leaves recoverable
      state.
- [ ] L2 Provider throttling: fail-fast + typed provider-throttled
    diagnosis + operator/user guidance (NO flow-level retry loop).
- [ ] L3 Health: execution-consumer presence + beat freshness on the
    existing operator surface; deployment-native healthchecks. No new
    public liveness endpoint.
- [ ] L4 Object-content scope (DEFAULT OUT, iteration 33): the tracked
    deployment default keeps bounded durable content in PostgreSQL
    with no separate object store (`docs/deployment/README.md:68`),
    so the BASE launch ships PostgreSQL-only. Object storage becomes
    a conditional opt-in gate (attach worker to object_content_net +
    one read/write journey) ONLY if the user opts in.
- [ ] L5 Launch receipt: pool-budget arithmetic vs SHOW
    max_connections under bounded load + one queue-recovery smoke at
    launch concurrency + exact deployment revision/config identity +
    rollback/drain evidence.
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
- Tests are proportional to observable risk (user directive
  2026-08-10): test CORE functionality, not everything reachable.
  When a slice deletes an invariant, repair path, or behavior, the
  tests guarding it are part of that slice's deletion list and die in
  the same commit. New tests pin an attributed mechanism or contract
  — never one-per-code-path, never a sibling of an existing guard.
  The tests themselves stay simple: plain arrange-act-assert on the
  real contract; no elaborate fixture machinery, mock towers, or
  parametrization mazes where a direct case is clearer. Test cleanup
  rides each slice; no standalone test-audit slice.

### Parallelization map (what runs concurrently; worker worktrees)
Commit gates stay sequential per stream, but implementation and
analysis overlap. Lanes that can run AT THE SAME TIME:
- Lane A (analysis, no product code): CP0 matrix freeze + CP2 step 1
  attribution table + CP4 diagnosis — all offline over the frozen
  packet; three independent workers or scripts, anytime.
- Lane B (builder code): CP1 (owner: `planning_state_builder.py`
  merge guard) and CP2 step 2 (owners: create proposal/preparation)
  touch DISJOINT files — separate worker worktrees in parallel once
  their design gates pass; land in sequence.
- Lane C (early design gates): CP5's provider strict-tool probe and
  placement decision need no code and can be adjudicated while Lane B
  implements; CP3's delta-envelope design gate needs only CP0's
  archetype placement rows.
- Lane D (runtime stream): L1–L5 are fully parallel with ALL builder
  work — different files, own peer session
  (`flows-runtime-readiness`), own worker worktrees.
Dependencies that stay hard: CP0 before CP3 implementation (placement
rows) and before the completion-contract verdicts; CP2 step 1 before
CP2 step 2; CP4 attribution before any CP4 fix; the tranche 155×3
after CP1–CP3 land. One live worker per session name; the
orchestrator judges every diff and owns all git.

### Measurement cadence
Cohort probes (3 reps, named cohorts) per slice; full 155×3 at
exactly two points (tranche gate, powered release candidate); suite
runs ≥45 min apart (provider limits).

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
1. ~~Permission to edit `.devcontainer/docker-compose.yml` for the
   durable three-role topology (L1)~~ — GRANTED 2026-08-10, scoped to
   the topology work (now dev-parity only; release proof targets the
   deployment compose).
2. Object storage: the program defaults the base launch to
   PostgreSQL-only (matches the tracked deployment default). Confirm,
   or opt object storage INTO launch scope (activates the L4
   conditional gate).
3. Sign-off on the converged program once the peer loop goes green at
   minimum score 9.
