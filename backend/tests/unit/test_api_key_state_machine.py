from __future__ import annotations

from datetime import datetime, timedelta, timezone

from intric.authentication.auth_models import ApiKeyState, compute_effective_state


def test_effective_state_revoked_has_highest_precedence() -> None:
    now = datetime.now(timezone.utc)
    state = compute_effective_state(
        revoked_at=now,
        suspended_at=now,
        expires_at=now - timedelta(seconds=1),
        now=now,
    )
    assert state == ApiKeyState.REVOKED


def test_effective_state_expired_has_precedence_over_suspended() -> None:
    now = datetime.now(timezone.utc)
    state = compute_effective_state(
        revoked_at=None,
        suspended_at=now,
        expires_at=now - timedelta(seconds=1),
        now=now,
    )
    assert state == ApiKeyState.EXPIRED


def test_effective_state_suspended_when_not_revoked_or_expired() -> None:
    now = datetime.now(timezone.utc)
    state = compute_effective_state(
        revoked_at=None,
        suspended_at=now,
        expires_at=now + timedelta(days=1),
        now=now,
    )
    assert state == ApiKeyState.SUSPENDED


def test_effective_state_active_when_no_state_markers() -> None:
    state = compute_effective_state(
        revoked_at=None,
        suspended_at=None,
        expires_at=None,
    )
    assert state == ApiKeyState.ACTIVE


def test_effective_state_handles_naive_expiry_timestamp() -> None:
    now = datetime(2026, 2, 1, 12, 0, 0, tzinfo=timezone.utc)
    naive_expired = datetime(2026, 2, 1, 11, 0, 0)
    state = compute_effective_state(
        revoked_at=None,
        suspended_at=None,
        expires_at=naive_expired,
        now=now,
    )
    assert state == ApiKeyState.EXPIRED
