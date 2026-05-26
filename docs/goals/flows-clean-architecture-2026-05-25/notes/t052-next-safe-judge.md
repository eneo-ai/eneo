# T052 Judge: Next Safe Task After Run-Contract Provider Consolidation

## Decision

Choose `T053` as the next safe Worker:

```text
refactor(flows-api): delete typed API provider pass-through helpers
```

This is a Flow API adapter consolidation slice. It removes typed one-line private
functions that only return `container.<provider>()` and makes the endpoint handlers
call the existing `Container` providers directly.

The slice is broader than the first draft because source review found the same
provider-helper pattern in sibling Flow API routers. A single pattern-wide cleanup
is more maintainable than committing one file while leaving known duplicates
untracked.

The slice must not touch `_get_flow_version_repo(...)` because that helper still
carries a `reportUnknownMemberType` ignore and needs a separate provider-typing
preflight before deletion.

## Source Evidence

Typed pass-through helpers that can be removed:

| File | Helper | Current behavior |
|---|---|---|
| `backend/src/intric/flows/api/flow_template_router.py:29` | `_get_flow_template_asset_service` | `return container.flow_template_asset_service()` |
| `backend/src/intric/flows/api/flow_assistant_router.py:56` | `_get_flow_service` | `return container.flow_service()` |
| `backend/src/intric/flows/api/flow_assistant_router.py:60` | `_get_assistant_assembler` | `return container.assistant_assembler()` |
| `backend/src/intric/flows/api/flow_authoring_router.py:119` | `_get_flow_service` | `return container.flow_service()` |
| `backend/src/intric/flows/api/flow_run_execution_router.py:393` | `_get_flow_run_service` | `return container.flow_run_service()` |
| `backend/src/intric/flows/api/flow_run_execution_router.py:397` | `_get_flow_run_review_checkpoint_service` | `return container.flow_run_review_checkpoint_service()` |
| `backend/src/intric/flows/api/flow_run_execution_router.py:403` | `_get_flow_run_rerun_service` | `return container.flow_run_rerun_service()` |
| `backend/src/intric/flows/api/flow_run_evidence_router.py:67` | `_get_flow_run_evidence_service` | `return container.flow_run_evidence_service()` |
| `backend/src/intric/flows/api/flow_run_steps_router.py:69` | `_get_flow_run_service` | `return container.flow_run_service()` |
| `backend/src/intric/flows/api/flow_run_steps_router.py:73` | `_get_flow_run_evidence_service` | `return container.flow_run_evidence_service()` |
| `backend/src/intric/flows/api/flow_run_steps_router.py:77` | `_get_flow_service` | `return container.flow_service()` |

Provider-typing blocker that must stay out of this slice:

| File | Helper | Reason retained |
|---|---|---|
| `backend/src/intric/flows/api/flow_run_steps_router.py:81` | `_get_flow_version_repo` | `return container.flow_version_repo()` currently requires `# pyright: ignore[reportUnknownMemberType]`. |

Current bounded search:

```bash
rg -n '^def _get_.*\(|return container\.' backend/src/intric/flows/api -g '*.py'
```

finds only the helpers above in Flow API source.

Current strict-pyright baseline:

```bash
cd backend && uv run pyright \
  src/intric/flows/api/flow_template_router.py \
  src/intric/flows/api/flow_assistant_router.py \
  src/intric/flows/api/flow_authoring_router.py \
  src/intric/flows/api/flow_run_execution_router.py \
  src/intric/flows/api/flow_run_evidence_router.py \
  src/intric/flows/api/flow_run_steps_router.py
```

Result: pass, `0 errors, 0 warnings, 0 informations`.

FastAPI/API adapter review:

- The candidate touches Flow API adapter internals, not endpoint decorators, request
  models, response models, dependency declarations, route signatures, OpenAPI, or
  generated-client code.
- Routers remain thin: dependency resolution still supplies `Container`; endpoint
  handlers call the application service provider directly.
- Expected OpenAPI/generated-client impact: none.

## Candidate Classification

### safe_now

`T053`: delete typed one-line `container.<provider>()` helpers across Flow API
routers and replace their call sites with direct provider calls.

Why safe now:

- The helpers are private, one-line pass-throughs with no policy, validation,
  authorization, transaction boundary, or error translation.
- The route functions already receive `container: Container`.
- Tests already configure the container provider seam.
- The architecture guard can become pattern-shaped instead of file/name scoped.
- This reduces the number of Flow API places a maintainer must inspect for service
  wiring.

### needs_preflight

- `_get_flow_version_repo(container)` deletion or direct inlining, because its
  current helper still needs `reportUnknownMemberType`.
- `flow_api_common.py:239-240` and `:280-281` provider-ignore cleanup for
  `space_service` and `actor_manager`.
- Any Container typed-accessor or dependency-injector provider typing work.
- Draft step id-owned persistence, runtime step identity schema follow-ups, schema
  migrations, JSONB ownership, and index/lock changes.
- Runtime output-mode/output-type movement when the active task reaches the
  output-format tranche.
- Frontend state ownership or generated client cleanup outside a dedicated
  frontend Worker.

### blocked_on_decision

- Retention behavior.
- Service-key identity model.
- Review/rerun service-key capability policy.
- Any schema or API change that depends on those product/data decisions.

### final_docs_only

- `T901`: `docs/flows/architecture.md` maintainer map.
- Do not start it while runtime/API/schema architecture is still actively changing.
  T053 must preserve owner/consolidation evidence so the final docs Worker can
  write from implemented reality.

## Proposed T053 Worker

Objective:

```text
refactor(flows-api): delete typed API provider pass-through helpers
```

Allowed files:

- `docs/goals/flows-clean-architecture-2026-05-25/state.yaml`
- `docs/goals/flows-clean-architecture-2026-05-25/notes/t053-api-provider-pass-throughs.md`
- `backend/src/intric/flows/api/flow_template_router.py`
- `backend/src/intric/flows/api/flow_assistant_router.py`
- `backend/src/intric/flows/api/flow_authoring_router.py`
- `backend/src/intric/flows/api/flow_run_execution_router.py`
- `backend/src/intric/flows/api/flow_run_evidence_router.py`
- `backend/src/intric/flows/api/flow_run_steps_router.py`
- `backend/tests/unittests/flows/test_flow_architecture_guards.py`

Expected implementation:

- Confirm the T053 source/test files are clean before implementation while
  preserving unrelated dirty files.
- Deepen the existing Flow API provider guard instead of adding a parallel guard.
- Replace the name/file-scoped helper ban with a structural AST predicate that
  finds private functions whose body only returns `container.<provider>()`.
- Apply the structural guard across `FLOW_API_ROOT.rglob("*.py")`, not a bounded
  per-file list, so future Flow API files are covered by the same rule.
- Keep exactly one documented temporary exception: `_get_flow_version_repo`.
- Prove the structural guard fails red against the current helper definitions before
  production edits.
- The red guard must report exactly 11 current offenders and must not report
  `_get_flow_version_repo`; a different count means the predicate or exception is
  wrong and the Worker must stop.
- Delete the typed pass-through helpers listed in Source Evidence.
- Replace their call sites with direct provider calls.
- Remove now-unused service/assembler imports.
- Delete the now-redundant file/name-scoped provider-pass-through guard constants.
  Keep the manual-construction guard because direct service construction is a
  separate anti-pattern.
- Verification test modules must pass unmodified. If the Worker needs to edit a
  test other than `test_flow_architecture_guards.py`, stop and return to Judge.
- Do not touch `_get_flow_version_repo`; record it as a temporary retained path
  with owner, reason, deletion trigger, and preflight need.

Verification commands:

```bash
git status --short
git diff --name-only -- \
  backend/src/intric/flows/api/flow_template_router.py \
  backend/src/intric/flows/api/flow_assistant_router.py \
  backend/src/intric/flows/api/flow_authoring_router.py \
  backend/src/intric/flows/api/flow_run_execution_router.py \
  backend/src/intric/flows/api/flow_run_evidence_router.py \
  backend/src/intric/flows/api/flow_run_steps_router.py \
  backend/tests/unittests/flows/test_flow_architecture_guards.py
cd backend && uv run pytest tests/unittests/flows/test_flow_architecture_guards.py::test_flow_api_provider_passthrough_helpers_are_not_reintroduced -q
cd backend && uv run pyright \
  src/intric/flows/api/flow_template_router.py \
  src/intric/flows/api/flow_assistant_router.py \
  src/intric/flows/api/flow_authoring_router.py \
  src/intric/flows/api/flow_run_execution_router.py \
  src/intric/flows/api/flow_run_evidence_router.py \
  src/intric/flows/api/flow_run_steps_router.py \
  tests/unittests/flows/test_flow_architecture_guards.py
cd backend && uv run pytest \
  tests/unittests/flows/test_flow_architecture_guards.py \
  tests/unittests/flows/test_flow_router.py \
  tests/unittests/flows/test_flow_template_router.py \
  tests/unittests/flows/test_flow_run_execution_router.py \
  tests/unittests/flows/test_flow_evidence_router.py \
  tests/unittests/flows/test_flow_scope_errors.py -q
cd backend && uv run ruff check \
  src/intric/flows/api/flow_template_router.py \
  src/intric/flows/api/flow_assistant_router.py \
  src/intric/flows/api/flow_authoring_router.py \
  src/intric/flows/api/flow_run_execution_router.py \
  src/intric/flows/api/flow_run_evidence_router.py \
  src/intric/flows/api/flow_run_steps_router.py \
  tests/unittests/flows/test_flow_architecture_guards.py
cd backend && uv run ruff format --check \
  src/intric/flows/api/flow_template_router.py \
  src/intric/flows/api/flow_assistant_router.py \
  src/intric/flows/api/flow_authoring_router.py \
  src/intric/flows/api/flow_run_execution_router.py \
  src/intric/flows/api/flow_run_evidence_router.py \
  src/intric/flows/api/flow_run_steps_router.py \
  tests/unittests/flows/test_flow_architecture_guards.py
rg -n '^def _get_.*\(|return container\.' backend/src/intric/flows/api -g '*.py'
git diff --check
git diff --staged --name-only
```

Expected grep result after T053: only `_get_flow_version_repo` and its retained
`return container.flow_version_repo()` line remain in Flow API source.

Stop if:

- Direct container-provider calls fail strict pyright.
- The structural guard does not fail red against the current helper definitions
  before production edits.
- The structural guard reports anything other than 11 offenders before production
  edits.
- The implementation touches `_get_flow_version_repo` or attempts to solve
  `flow_version_repo` typing without a separate Judge decision.
- The guard is implemented as a parallel test instead of deepening the existing
  Flow API provider guard.
- The fix requires changing endpoint signatures, response models, dependencies,
  OpenAPI, generated clients, or Flow endpoint behavior.
- Any verification test module other than `test_flow_architecture_guards.py`
  requires edits.
- The fix requires changing `Container` provider definitions or service constructor
  semantics.
- The fix requires `Any`, `cast(Any)`, `dict[str, Any]`, a pyright ignore, a generic
  helper, manager, processor, service locator, fake interface, or one-implementation
  protocol.
- The task expands into retention, service-key identity/review/rerun capability
  policy, schema migrations, webhook outbox, output-format architecture, final
  architecture docs, or Flow AI Builder.
- Staged files include anything outside the T053 allowed files.
- Any unrelated pre-existing dirty file is staged, stashed, reset, cleaned, or
  otherwise modified.

## Consolidation Effect

- Reused existing owner: `Container` providers and the corresponding application
  services/assembler.
- Logic moved from: private one-line pass-through functions to direct provider
  calls in Flow API endpoint handlers.
- Logic deleted: all typed one-line provider helpers listed in Source Evidence.
- Duplicate path removed: Flow API adapter service wiring no longer has a parallel
  `_get_*` function family for typed providers.
- New code added: one structural architecture guard predicate and one temporary
  provider-typing exception for `_get_flow_version_repo`; no production helper or
  abstraction.
- Why existing owners were insufficient: they are sufficient; the private helpers
  only forwarded to them.
- Guard/test preventing duplicate logic from returning: generalized structural Flow
  API provider pass-through guard plus existing Flow API router behavior tests.
- Net Flow logic surface area: reduced.
- If increased, why the increase is necessary: not applicable.

## Temporary Parallel Path Remaining

- Owner: `_get_flow_version_repo(container)` in
  `backend/src/intric/flows/api/flow_run_steps_router.py`.
- Reason: direct `container.flow_version_repo()` provider typing currently required
  `reportUnknownMemberType` in the helper. T053 is scoped to typed provider
  pass-throughs only.
- Migration/deletion trigger: a future Judge-approved provider-typing/Container
  typed-accessor task or a preflight proving direct `container.flow_version_repo()`
  passes strict pyright without `Any`, casts, or ignores.
- Test/preflight proving continued need: current source evidence is the pyright
  ignore at `flow_run_steps_router.py:82`; future deletion must prove pyright clean
  and run flow graph/run step tests.

## Naming Gate

- New production names: none.
- New test helper/predicate names must be structural and domain-specific, for
  example provider pass-through detection in Flow API routers.
- The concept belongs in the future `docs/flows/architecture.md` guard-test map and
  "where to change X" table as: Flow API endpoint handlers call canonical Container
  providers directly; private provider pass-through functions are disallowed except
  for documented provider-typing blockers with deletion triggers.

## Peer Review Result

Claude plan gate iteration 1 returned `GREEN_LIGHT: no`, `MIN_SCORE: 5` because
the first T052 draft only targeted `flow_run_steps_router.py` and missed sibling
routers with the same provider-helper pattern. This revised Judge decision adopts
the cleaner option: pattern-wide cleanup, structural guard, and a single retained
provider-typing exception.

Run Claude iteration 2 before activating T053.

Antigravity is not required unless Claude and Codex disagree. This is not a public
contract, schema, data migration, runtime behavior, or disputed product decision.
