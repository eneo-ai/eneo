# Testing Standard

Tests protect behavior, not implementation.

Prefer:

- domain or unit tests for pure rules;
- integration tests for database, API, and runtime wiring;
- worker and runtime tests for retries, duplicate starts, crash recovery, and
  terminalization;
- frontend component tests for user-visible behavior;
- API contract tests for external consumers;
- end-to-end tests only for journeys whose cross-system behavior cannot be
  proved more cheaply.

Runtime changes use the applicable failure and recovery proofs in the
[Runtime Reliability Standard](runtime-reliability-standard.md).

## Test doubles carry the contract they stand in for

A double that stands in for a typed model must carry every field production
code is entitled to assume. Untyped, duck-typed stubs drift silently: the
model gains a required field, the runtime starts trusting it, and the stub
keeps passing until a later change turns the gap into a failure far from its
cause.

Build the double from the production model itself, through a named factory.
A validated construction fails at the factory the moment the model gains a
required field, which is the only version of this that actually tracks the
contract. A look-alike dataclass does not: it is an independent schema that
drifts exactly like the stub it replaced, and `model_construct` skips
validation, so neither one earns the guarantee.

Where a real model is genuinely unavailable, declare the seam the consumer
depends on as a `Protocol` and type the double against it, so the compiler
checks the substitution. Reuse a canonical factory where one exists rather
than adding another per module.

When a double loses a field the production model guarantees, fix the double
against that contract rather than relaxing the production guard.

This applies to the doubles a change touches. Converting an entire suite is
its own scoped change, not a rider on unrelated work.

Flag:

- mocks of internal collaborators where public behavior is testable;
- assertions about private helper calls or wiring;
- tests that duplicate implementation logic;
- tests for compatibility or fallback behavior that should be deleted;
- giant test files with no lifecycle organization;
- arbitrary sleeps and unbounded polling;
- snapshots that preserve incidental details;
- broad harnesses added when an existing behavior owner can absorb the case.

A test recommendation names the protected behavior, failure mode, appropriate
test layer, and why the test remains useful after refactoring. Name special
fixtures, factories, clocks, brokers, or database setup only when the behavior
actually requires them.
