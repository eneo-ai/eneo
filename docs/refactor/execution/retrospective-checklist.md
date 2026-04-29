# Implementation Retrospective Checklist

Answer every item with `pass` / `fail` / `n/a` and one line of
evidence. Do not skip. Do not rewrite questions to make them
easier to pass.

Evidence in committed retrospectives must be durable. If raw validation
logs, Claude attack packets, or transcripts are kept local-only, cite
the durable source/test/doc line and summarize the raw artifact outcome
in the journal or reconciliation instead of relying on ignored files as
the only evidence.

## A. Plan adherence

- [ ] Did I implement what the plan said I would implement?
- [ ] Did I stay within the file scope listed in the plan?
- [ ] If I changed scope, did I update the plan FIRST and re-run
      /plan, not silently drift?
- [ ] Did the behavior pins land BEFORE any deletion?
- [ ] Did I preserve every load-bearing decision from
      `docs/refactor/phase7/implementation-readiness.md` that
      applies to this batch?

## B. Acceptance criteria

- [ ] Have I checked every acceptance criterion from the PRD
      against the actual code, not just against intent?
- [ ] For each criterion: cite the test or file:line that
      satisfies it.
- [ ] Are there any criteria I marked `done` based on intent
      rather than evidence? (If yes → fail.)

## C. Behavior pins and validation

- [ ] Did every validation command from
      `implementation-order.md` run?
- [ ] Did every command pass, OR is the failure a known baseline
      issue documented in `phase0/baseline.md`?
- [ ] Did the behavior pins added in this batch actually exercise
      the behavior they claim to pin? (Read the test bodies.)

## D. Pre-production deletion discipline

- [ ] Did I delete every Tier A item the plan said to delete?
- [ ] Did I leave every Tier B item alone (or follow the proper
      Tier B protocol with proof)?
- [ ] Did I introduce ANY new compatibility shim, fallback path,
      "support both old and new" branch, or `legacy_*` named
      symbol?
- [ ] Did I introduce any new `Any`, `dict[str, Any]`,
      `except Exception`, `HTTPException` outside HTTP adapters,
      `as any`, `@ts-ignore`, or `@ts-expect-error`?

## E. Single source of truth

- [ ] Did I introduce duplicate logic for any concept the plan
      named as having a canonical home?
- [ ] If I added a new utility/helper file, can I name the
      domain concept it represents? (If no → fail.)

## F. File splits and naming

- [ ] If I split a file, did I split by responsibility, not LOC?
- [ ] Did I avoid prohibited file names (`utils`, `helpers`,
      `common`, `shared`, `manager`, `misc`)?
- [ ] Does every new file represent one named domain concept?

## G. Comments and readability

- [ ] Did I delete comments that restate code instead of
      explaining intent?
- [ ] Did I avoid adding "what" comments where better naming or
      extraction would do?
- [ ] If I added a non-trivial comment, does it explain a
      non-obvious invariant, trade-off, or constraint?

## H. Test quality

- [ ] Are the tests I added behavior tests, not implementation
      tests?
- [ ] Did I avoid mocking internal collaborators just to isolate
      implementation?
- [ ] If I deleted tests, did I delete them because they
      protected code being intentionally removed, not because
      they were inconvenient?

## I. Boundary discipline

- [ ] Did I keep ORM models out of domain/application logic?
- [ ] Did I keep Pydantic schemas out of domain logic?
- [ ] Did I keep `HTTPException` out of domain code?
- [ ] Did I keep Celery payloads as typed commands with IDs, not
      mutable state blobs?

## J. Scope and risk

- [ ] Did I touch any code outside Flow / Flow AI Builder?
- [ ] If yes, was it a shared dependency directly required by
      this batch, and did I document why?
- [ ] Are there carry-forward risks I should record in the
      journal for the next batch?

## Final gate

Count `fail` items. `n/a` answers are not fails.
Section A includes the implementation-readiness load-bearing
decision check; it is also named below so the RED trigger survives if
checklist sections are reorganized.

- 0 fails → GREEN
- 1–2 fails (none in section A, C, or D, and none on a load-bearing
  decision from `docs/refactor/phase7/implementation-readiness.md`)
  → YELLOW with documented carry-forward
- ≥3 fails OR any fail in A / C / D OR any fail on a load-bearing
  decision from `docs/refactor/phase7/implementation-readiness.md`
  → RED, return to implementation
