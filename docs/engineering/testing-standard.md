# Testing Standard

Tests protect behavior, not implementation.

Prefer:

- domain/unit tests for pure rules
- integration tests for DB/API/runtime wiring
- worker/runtime tests for retries, idempotency, duplicate starts, crash recovery, and terminalization
- frontend component tests for UI behavior
- E2E tests for critical journeys only
- API contract tests for external consumers

Flag:

- tests that mock internal collaborators unnecessarily
- tests that assert private helper calls
- tests that duplicate implementation logic
- tests for legacy behavior we should delete
- huge test files without lifecycle organization
- flaky sleeps and arbitrary polling
- snapshots that preserve incidental details

Good test recommendations must name the behavior under protection, the failure mode, the test layer, required fixtures/factories, and why the test remains useful after refactoring.
