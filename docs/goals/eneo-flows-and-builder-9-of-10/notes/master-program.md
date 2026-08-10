# Eneo Flows + Flow AI Builder — Master Program (living document)

Status: CONVERGING — peer iteration 32+ is refining the ranked program
at min-score 9; no implementation until convergence, then user
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

## The Ranked Program (v1 — being converged; update on each pass)

### Tier 1 — Ownership transfers (quality + architecture)
- [ ] 1.1 Runtime-input-field contract compilation. Typed field declarations
    + semantic consumer in the classifier/metadata contract (never
    prose parsing) → existing hints path
    (`ai_builder_create_compiler.py:940,1100`) → delete the prompt
    block + create-repair ownership → retires create-mode
    responsibility of the four form-field invariants. FREEZE THE TYPED
    CONTRACT FIRST; design-gate before code.
- [ ] 1.2 Terminal-shape ownership. terminal_output_type_mismatch (6 obs)
    despite a committed terminal slot — attribute why proposals can
    mismatch, then make it inexpressible (intent schema) or
    compile-time-corrected (assembly).
- [ ] 1.3 Named-result completion for JSON terminals (the 9/9 failing
    probes): compiled terminal contract consumes
    `named_result_obligations` where no declared schema owns the
    terminal; via the existing projection; after 2.1.

### Tier 2 — Classifier correctness (runs FIRST; foundation)
- [ ] 2.1 Diagnostics tranche: (a) partial named-result emission (4 JSON
    cases); (b) file-role flip regression — re-classification
    downgrades an explicit-quote-backed role 3/3 (candidate invariant:
    explicit-evidence roles are sticky absent new contradicting
    evidence; kin of the fc82f0b91 evidence-churn family); (c) the
    added question round in the same case.

### Tier 3 — Launch operability (runtime stream, parallel)
- [ ] 3.1 Durable topology: `.devcontainer` three-role compose + tracked
    max_connections (USER PERMISSION PENDING — path is on the user's
    protected list) + clean-volume recreation proof.
- [ ] 3.2 Provider throttling: fail-fast + typed provider-throttled
    diagnosis + operator/user guidance (adjudicated; NO flow-level
    retry loop).
- [ ] 3.3 Health: execution-consumer presence + beat freshness on the
    existing operator surface; deployment-native healthchecks for
    celery services. No new public liveness endpoint.
- [ ] 3.4 Object-content scope (USER DECISION): if bundled storage is in
    launch scope, attach celery-worker-flows to object_content_net +
    prove one read/write journey.
- [ ] 3.5 Launch receipt: pool-budget arithmetic vs SHOW max_connections
    under bounded load + one queue-recovery smoke at launch
    concurrency.

### Tier 4 — Maintainability / clean architecture (split-when-touched)
Adjudicated rulings (runtime pass 2 + builder passes 24/30/31):
- [ ] 4.1 `planning_state_builder.py` split (3 owners + facade) AFTER Tier 1
    settles — Tier 1 rewrites its evidence lifecycle again.
- [ ] 4.2 `step_input_resolution.py` split when 1.3/Slice-6 touches it
    (seams: orchestration / source-ref projection / file extraction /
    overflow rules; its deps object erases owners to Any — fix then).
- [ ] 4.3 `step_execution_runtime.py` provider-call seam only if 3.2 changes
    provider behavior.
- [ ] 4.4 `executor.py`: DO NOT SPLIT (cohesive around one run transaction).
- [ ] 4.5 `flow_run_repo.py`: future read-only evidence repository seam;
    wait. `flow_models.py`: local fixes only; no 24-importer split.
- [ ] 4.6 `field_diagnostics` → `compile_diagnostics` rename at next touch.
- [ ] 4.7 Slice-5 commit 2 (non-JSON seam completion; 10-obs cohort) —
    re-verify cohort post-commit-1; may fold into 1.3's shadow.
- [ ] 4.8 JSON fan-in (reworked template-fill route) after 1.2.

### Sequencing
- [ ] 2.1 → 1.1 → 1.2 → 1.3 (builder stream, each design-gated then
commit-gated), Tier 3 parallel (runtime stream, own peer session),
Tier 4 rides whichever slice touches its file. Cohort probes (3 reps)
per slice; full 155×3 at tier boundaries; suite runs ≥45 min apart
(provider limits).

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
