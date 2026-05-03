# Batch 11.0b Claude Reconciliation — Proposal Reliability Measurement

## TL;DR

1. Claude initially rejected the plan because proposal telemetry would have split
   ownership of the `planner_telemetry` schema.
2. The accepted plan keeps `ai_builder_telemetry.py` as the only telemetry dict
   owner and moves proposal turn recording into a narrow module.
3. Claude's second pass found two typed-contract gaps: repair-loop consumers and
   missing-tool taxonomy separation.
4. The final plan reached `GREEN_LIGHT: yes` with minimum score `9`.
5. The implementation review found and then cleared one correctness blocker:
   success telemetry must not be recorded before validation/quality checks.
6. Implementation keeps behavior unchanged and records deterministic baseline
   numbers before 11.1.

## Iteration 1

| Item | Value |
|---|---|
| Artifact | `.codex/artifacts/claude-peer-loop-batch-11-0b-proposal-reliability-measurement-plan-20260503T000534Z.md` |
| Verdict | `changes_required` |
| Green light | `no` |
| Minimum score | `6` |

Accepted findings:

| Finding | Resolution |
|---|---|
| Proposal telemetry fields would create parallel `planner_telemetry` ownership. | Extended canonical `build_planner_telemetry` instead of mutating telemetry dicts in proposal code. |
| Missing-tool forced retry could overwrite the original first-attempt failure. | Defined and tested first-attempt idempotency. |
| `failure_kind` was still stringly typed. | Introduced typed internal and sanitized proposal failure taxonomies. |
| `ProposalUsageTracker` no longer described the class responsibility. | Renamed to `ProposalTurnTelemetry`; no pre-release compatibility alias. |
| Baseline numbers needed to be concrete. | Journal now records deterministic counts and explicitly excludes live LLM pass rate. |

## Iteration 2

| Item | Value |
|---|---|
| Artifact | `.codex/artifacts/claude-peer-loop-batch-11-0b-proposal-reliability-measurement-plan-verification-20260503T000947Z.md` |
| Verdict | `changes_required` |
| Green light | `no` |
| Minimum score | `8` |

Accepted findings:

| Finding | Resolution |
|---|---|
| `ai_builder_proposal_repair.py` also consumes `failure_kind`. | Tightened repair-loop signatures and the self-correction error callback. |
| `missing_submission_tool` is not a tool-result failure. | Split `ToolProcessingFailureKind` from `ProposalFailureKind`. |
| JSON logging strips top-level `None` extras. | Used a nested `ai_builder_proposal_telemetry` payload and omitted success-row failure fields. |
| Drift test wording was mechanism-first. | Implemented an AST-based taxonomy test over a fixed source set. |

## Iteration 3

| Item | Value |
|---|---|
| Artifact | `.codex/artifacts/claude-peer-loop-batch-11-0b-proposal-reliability-measurement-plan-verification-2-20260503T001225Z.md` |
| Verdict | `green` |
| Green light | `yes` |
| Minimum score | `9` |

Accepted polish:

| Finding | Resolution |
|---|---|
| `recoverable_parse` is tested but has no production producer today. | Documented why it remains in the internal taxonomy. |
| `Callable[..., dict[str, str]]` was too loose for the injected error callback. | Added `BuildSelfCorrectionErrorEvent` protocol. |
| `ProposalRepairReason` could drift from `ProposalFailureKind`. | Made it an alias. |
| The drift test needed an explicit file set. | Pinned the AST scan in `test_ai_builder_proposal_telemetry.py`. |

## Iteration 4

| Item | Value |
|---|---|
| Artifact | `.codex/artifacts/claude-peer-loop-batch-11-0b-proposal-telemetry-implementation-20260503T003537Z.md` |
| Verdict | `changes_required` |
| Green light | `no` |
| Minimum score | `5` |

Accepted findings:

| Finding | Resolution |
|---|---|
| The success metadata builder recorded `proposal_first_attempt_success=true` before downstream validation and quality checks completed. | Split success recording from metadata construction and made MCP clarification metadata lazy. |
| Tests stubbed the processing function and missed the eager success-recording path. | Added real outline quality-failure telemetry coverage and edit quality-failure no-success-callback coverage. |
| Metadata-builder naming hid a side effect. | The handler now injects separate `proposal_success_recorder` and pure `assistant_metadata_builder` callbacks. |

## Iteration 5

| Item | Value |
|---|---|
| Artifact | `.codex/artifacts/claude-peer-loop-batch-11-0b-proposal-telemetry-verification-20260503T004709Z.md` |
| Verdict | `GREEN_LIGHT` |
| Green light | `yes` |
| Minimum score | `8.5` |

Accepted verification:

| Finding | Resolution |
|---|---|
| The eager success-recording bug was fixed structurally. | Success recording now occurs only from accepted proposal paths, and first-write-wins remains the guard for forced retry paths. |
| Regression tests protect the invariant. | Focused proposal tests increased to `58 passed`. |
| No typed-contract, comment hygiene, or Flow compatibility blocker remained. | Proceeded to final validation. |

## Remaining Disagreements

No findings were rejected. No disagreements remain.
