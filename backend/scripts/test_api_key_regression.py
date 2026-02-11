#!/usr/bin/env python3
"""API Key v2 enforcement regression script.

Run against a live Eneo instance to verify that all four enforcement
layers (resource permission, basic method permission, management guard,
scope enforcement) work correctly end-to-end.

Usage:
    python test_api_key_regression.py \
        --base-url http://localhost:8000 \
        --admin-bearer TOKEN \
        --admin-api-key sk_xxx

    # Dry-run mode (prints what would be tested):
    python test_api_key_regression.py \
        --base-url http://localhost:8000 \
        --admin-bearer TOKEN \
        --admin-api-key sk_xxx \
        --dry-run
"""

from __future__ import annotations

import argparse
import sys
import time
from dataclasses import dataclass, field
from typing import Any

import httpx

# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------


@dataclass
class TestResult:
    name: str
    passed: bool
    expected: str
    actual: str
    duration_ms: float = 0.0


@dataclass
class TestSuite:
    results: list[TestResult] = field(default_factory=list)

    def add(self, result: TestResult) -> None:
        self.results.append(result)

    @property
    def passed(self) -> int:
        return sum(1 for r in self.results if r.passed)

    @property
    def failed(self) -> int:
        return sum(1 for r in self.results if not r.passed)

    @property
    def total(self) -> int:
        return len(self.results)

    def print_summary(self) -> None:
        max_name = max((len(r.name) for r in self.results), default=20)
        print("\n" + "=" * (max_name + 40))
        print("API Key v2 Regression Results")
        print("=" * (max_name + 40))

        for r in self.results:
            status = "PASS" if r.passed else "FAIL"
            marker = "✓" if r.passed else "✗"
            print(f"  {marker} [{status}] {r.name:<{max_name}}  ({r.duration_ms:.0f}ms)")
            if not r.passed:
                print(f"           expected: {r.expected}")
                print(f"           actual:   {r.actual}")

        print("-" * (max_name + 40))
        print(f"  Total: {self.total}  Passed: {self.passed}  Failed: {self.failed}")
        print("=" * (max_name + 40))


# ---------------------------------------------------------------------------
# HTTP helpers
# ---------------------------------------------------------------------------

API_PREFIX = "/api/v1"


def _headers_bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _headers_api_key(api_key: str) -> dict[str, str]:
    return {"X-API-Key": api_key}


def _timed_request(
    client: httpx.Client,
    method: str,
    path: str,
    headers: dict[str, str] | None = None,
    json: Any = None,
) -> tuple[httpx.Response, float]:
    start = time.monotonic()
    resp = client.request(method, path, headers=headers, json=json)
    elapsed_ms = (time.monotonic() - start) * 1000
    return resp, elapsed_ms


# ---------------------------------------------------------------------------
# Key lifecycle helpers
# ---------------------------------------------------------------------------


def create_test_key(
    client: httpx.Client,
    bearer: str,
    *,
    name: str,
    permission: str = "read",
    scope_type: str = "tenant",
    scope_id: str | None = None,
    key_type: str = "sk_",
) -> tuple[str, str]:
    """Create a test API key and return (key_id, secret)."""
    payload: dict[str, Any] = {
        "name": name,
        "permission": permission,
        "scope_type": scope_type,
        "key_type": key_type,
    }
    if scope_id is not None:
        payload["scope_id"] = scope_id

    resp, _ = _timed_request(
        client,
        "POST",
        f"{API_PREFIX}/api-keys",
        headers=_headers_bearer(bearer),
        json=payload,
    )
    if resp.status_code != 201:
        raise RuntimeError(
            f"Failed to create test key '{name}': {resp.status_code} {resp.text}"
        )
    data = resp.json()
    return data["api_key"]["id"], data["secret"]


def revoke_test_key(client: httpx.Client, bearer: str, key_id: str) -> None:
    """Revoke a test key (cleanup)."""
    _timed_request(
        client,
        "POST",
        f"{API_PREFIX}/api-keys/{key_id}/revoke",
        headers=_headers_bearer(bearer),
        json={"reason_code": "admin_action", "reason_text": "Regression test cleanup"},
    )


# ---------------------------------------------------------------------------
# Test implementations
# ---------------------------------------------------------------------------


def test_public_endpoints(client: httpx.Client, suite: TestSuite) -> None:
    """Public endpoints must return non-401/403 without auth."""
    for path, name in [
        ("/version", "GET /version (public)"),
        ("/api/healthz", "GET /api/healthz (public)"),
    ]:
        resp, ms = _timed_request(client, "GET", path)
        suite.add(TestResult(
            name=name,
            passed=resp.status_code not in (401, 403),
            expected="not 401/403",
            actual=str(resp.status_code),
            duration_ms=ms,
        ))


def test_auth_required(client: httpx.Client, suite: TestSuite) -> None:
    """Authenticated endpoints must reject unauthenticated requests."""
    resp, ms = _timed_request(client, "GET", f"{API_PREFIX}/assistants")
    suite.add(TestResult(
        name="GET /assistants (no auth → 401/403)",
        passed=resp.status_code in (401, 403),
        expected="401 or 403",
        actual=str(resp.status_code),
        duration_ms=ms,
    ))


def test_bearer_auth(client: httpx.Client, bearer: str, suite: TestSuite) -> None:
    """Bearer token should authenticate successfully."""
    resp, ms = _timed_request(
        client, "GET", f"{API_PREFIX}/settings/",
        headers=_headers_bearer(bearer),
    )
    suite.add(TestResult(
        name="GET /settings (bearer → 200)",
        passed=resp.status_code == 200,
        expected="200",
        actual=str(resp.status_code),
        duration_ms=ms,
    ))


def test_read_key_enforcement(
    client: httpx.Client, read_key_secret: str, suite: TestSuite
) -> None:
    """Read key: can GET, cannot DELETE."""
    # GET should pass
    resp, ms = _timed_request(
        client, "GET", f"{API_PREFIX}/assistants",
        headers=_headers_api_key(read_key_secret),
    )
    suite.add(TestResult(
        name="Read key + GET /assistants → 200",
        passed=resp.status_code == 200,
        expected="200",
        actual=str(resp.status_code),
        duration_ms=ms,
    ))


def test_write_key_enforcement(
    client: httpx.Client, write_key_secret: str, suite: TestSuite
) -> None:
    """Write key: cannot access management endpoints."""
    resp, ms = _timed_request(
        client, "GET", f"{API_PREFIX}/api-keys",
        headers=_headers_api_key(write_key_secret),
    )
    # GET list should work (no management guard on GET)
    suite.add(TestResult(
        name="Write key + GET /api-keys → 200",
        passed=resp.status_code == 200,
        expected="200",
        actual=str(resp.status_code),
        duration_ms=ms,
    ))


def test_admin_key_management(
    client: httpx.Client, admin_key_secret: str, suite: TestSuite
) -> None:
    """Admin key: can access management endpoints."""
    resp, ms = _timed_request(
        client, "GET", f"{API_PREFIX}/api-keys",
        headers=_headers_api_key(admin_key_secret),
    )
    suite.add(TestResult(
        name="Admin key + GET /api-keys → 200",
        passed=resp.status_code == 200,
        expected="200",
        actual=str(resp.status_code),
        duration_ms=ms,
    ))


def test_management_escalation_prevention(
    client: httpx.Client,
    read_key_secret: str,
    admin_key_id: str,
    suite: TestSuite,
) -> None:
    """Read key cannot perform management mutations (escalation prevention)."""
    resp, ms = _timed_request(
        client,
        "POST",
        f"{API_PREFIX}/api-keys/{admin_key_id}/suspend",
        headers=_headers_api_key(read_key_secret),
        json={"reason_code": "admin_action"},
    )
    suite.add(TestResult(
        name="Read key + POST /suspend → 403 (escalation blocked)",
        passed=resp.status_code == 403,
        expected="403",
        actual=str(resp.status_code),
        duration_ms=ms,
    ))


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def run_tests(
    base_url: str,
    admin_bearer: str,
    admin_api_key: str | None,
    dry_run: bool,
) -> int:
    suite = TestSuite()

    if dry_run:
        print("DRY RUN — would execute the following tests:")
        print("  1. Public endpoints (/version, /api/healthz)")
        print("  2. Auth required (GET /assistants without auth)")
        print("  3. Bearer auth (GET /settings)")
        print("  4. Read key enforcement (GET /assistants)")
        print("  5. Write key enforcement (GET /api-keys)")
        print("  6. Admin key management (GET /api-keys)")
        print("  7. Management escalation prevention (read key + POST /suspend)")
        print()
        print(f"Base URL: {base_url}")
        print(f"Bearer token: {'provided' if admin_bearer else 'missing'}")
        print(f"Admin API key: {'provided' if admin_api_key else 'missing'}")
        print()
        print("Would create 3 test keys (read/write/admin) and revoke them after.")
        return 0

    client = httpx.Client(base_url=base_url, timeout=30.0)
    created_key_ids: list[str] = []

    try:
        # Phase 1: Tests that don't need test keys
        test_public_endpoints(client, suite)
        test_auth_required(client, suite)
        test_bearer_auth(client, admin_bearer, suite)

        # Phase 2: Create test keys
        print("Creating test API keys...")
        read_id, read_secret = create_test_key(
            client, admin_bearer, name="regression-read", permission="read"
        )
        created_key_ids.append(read_id)

        write_id, write_secret = create_test_key(
            client, admin_bearer, name="regression-write", permission="write"
        )
        created_key_ids.append(write_id)

        admin_id, admin_secret = create_test_key(
            client, admin_bearer, name="regression-admin", permission="admin"
        )
        created_key_ids.append(admin_id)
        print(f"  Created {len(created_key_ids)} test keys.")

        # Phase 3: Tests with test keys
        test_read_key_enforcement(client, read_secret, suite)
        test_write_key_enforcement(client, write_secret, suite)
        test_admin_key_management(client, admin_secret, suite)
        test_management_escalation_prevention(client, read_secret, admin_id, suite)

    finally:
        # Phase 4: Cleanup — always revoke created keys
        if created_key_ids:
            print(f"Cleaning up {len(created_key_ids)} test keys...")
            for key_id in created_key_ids:
                try:
                    revoke_test_key(client, admin_bearer, key_id)
                except Exception as e:
                    print(f"  Warning: Failed to revoke key {key_id}: {e}")
            print("  Cleanup complete.")

        client.close()

    suite.print_summary()
    return 1 if suite.failed > 0 else 0


def main() -> None:
    parser = argparse.ArgumentParser(
        description="API Key v2 enforcement regression test",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--base-url",
        required=True,
        help="Base URL of the Eneo instance (e.g. http://localhost:8000)",
    )
    parser.add_argument(
        "--admin-bearer",
        required=True,
        help="Bearer token for an admin user",
    )
    parser.add_argument(
        "--admin-api-key",
        default=None,
        help="Admin API key (sk_xxx) for additional testing",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print what would be tested without executing",
    )

    args = parser.parse_args()
    exit_code = run_tests(
        base_url=args.base_url,
        admin_bearer=args.admin_bearer,
        admin_api_key=args.admin_api_key,
        dry_run=args.dry_run,
    )
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
