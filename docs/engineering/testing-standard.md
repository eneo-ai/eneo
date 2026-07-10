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
